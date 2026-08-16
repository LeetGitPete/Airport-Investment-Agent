"""Refresh: fetch/normalize/write every bulk source into the snapshot, per-source
try/except (a failing source never aborts the run and never leaves the store worse off
than before that source's writes started — see `Store.replace_rows`'s own transaction),
then rebuild `airport_metrics` once at the end.

**Nested-transaction caveat (ledger note, restated here on purpose):** never wrap calls to
`Store.replace_rows` in `store.con.begin()` — `replace_rows` manages its own
delete+insert transaction per call, and DuckDB does not support nested transactions.

**Scheduling** (design 01): no daemon. Run on a schedule externally, e.g.:
  cron:               `0 6 * * * cd /path/to/repo && uv run python -m airport_agent.data refresh --full`
  Windows Task Scheduler: Action = `uv.exe`, Arguments =
      `run python -m airport_agent.data refresh --full`, Start in = the repo root.
Keep `.claude/skills/refresh-data` consistent with this CLI if its wording drifts.

**Period windows for the two form-scraped monthly sources (bts_t100, bts_otp — every other
bulk source ignores `period` and either re-pulls its one file or, for `bts_socrata`, pulls
full history in one API call chain):**
- `--period YYYY-MM` given: fetch exactly that one month (incremental/cron use), scoped so
  only that month's rows are replaced — the rest of the retained window is untouched.
- no `--period`, `--full`: fetch the trailing `t100_months`/`otp_months` (from
  `config/sources.yaml`) months, probing backward from the current UTC month for
  publication lag, and REPLACE the source's entire table (the RESCOPE's "trailing N months
  only" design means old months outside the window are meant to drop off).
- no `--period`, not `--full`: fetch just the single latest available month (a light
  incremental default) — same replace-that-one-month semantics as `--period`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.census_cbsa import apply_cbsa_enrichment
from airport_agent.data.adapters.faa_taf import apply_taf_enrichment
from airport_agent.data.derived import build_derived
from airport_agent.data.paths import default_snapshot_path, raw_cache_dir
from airport_agent.data.sources_config import SourceConfig, load_sources
from airport_agent.data.store import Store

#: `airport_metrics`-independent tables carrying a per-row period/year column, keyed by
#: which column so a single `--period` refresh scopes its delete precisely.
_PERIOD_COLUMN: dict[str, str] = {
    "airport_month": "period", "routes_month": "period", "otp_taxi_hist": "period", "otp_peak": "period",
    "airport_year": "year",
}

#: Sources whose `normalize()` output needs an enrichment UPDATE (`apply_*_enrichment`)
#: instead of a plain `Store.replace_rows` for one or more of its returned tables.
_ENRICHMENT_SOURCES = {"faa_taf", "census_cbsa"}

#: Fallback trailing-months window for bts_t100 if `config/sources.yaml` doesn't set
#: `t100_months` (design 01's original default).
_DEFAULT_T100_MONTHS = 24
_DEFAULT_OTP_MONTHS = 12

#: How many extra months to probe backward before giving up on finding the latest
#: available month (covers publication lag, e.g. OTP ~2mo, T-100 ~3mo).
_PROBE_SLACK_MONTHS = 6


@dataclass(frozen=True)
class SourceResult:
    """Outcome of refreshing one source."""

    source_id: str
    ok: bool
    rows: int
    seconds: float
    error: str | None = None


@dataclass(frozen=True)
class RefreshReport:
    """Outcome of one `refresh()` call."""

    results: list[SourceResult]
    derived_row_counts: dict[str, int] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @property
    def failed(self) -> list[SourceResult]:
        return [r for r in self.results if not r.ok]

    @property
    def ok(self) -> bool:
        """True if every requested source refreshed cleanly (exit-code use only — the CLI
        itself always exits 0 for per-source failures, per the plan)."""
        return not self.failed


def _month_before(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _probe_trailing_periods(adapter, cache_dir: Path, n_months: int, start: tuple[int, int]) -> list[Period]:
    """Fetch (and cache) up to `n_months` periods ending at the latest month that
    successfully downloads, probing backward from `start` for publication lag. Any failure
    to fetch/land a given period — a non-2xx response (`httpx.HTTPStatusError`), or (T-100
    specifically) an HTTP 200 whose body is an HTML form re-render rather than a real zip,
    which `adapters/bts_t100.py::_extract_data_csv` turns into a `ValueError` — is treated
    as "not yet published" and skipped, not a hard failure. If NO period in the whole probe
    budget succeeds, the caller raises (a real outage looks the same as exhausted publication
    lag from here, but genuinely nothing to ingest either way)."""
    y, m = start
    found: list[Period] = []
    max_attempts = n_months + _PROBE_SLACK_MONTHS
    for _ in range(max_attempts):
        if len(found) >= n_months:
            break
        p = Period(year=y, month=m)
        try:
            adapter.fetch(p, cache_dir)
        except (httpx.HTTPStatusError, ValueError):
            pass
        else:
            found.append(p)
        y, m = _month_before(y, m)
    return list(reversed(found))


def _resolve_periods(
    source_id: str, cfg: SourceConfig, adapter, cache_dir: Path, period: Period | None, full: bool
) -> list[Period | None]:
    """The `Period`(s) to pass to `adapter.fetch()` for this source (see module docstring)."""
    if period is not None:
        return [period]
    if source_id == "bts_socrata":
        return [None]  # full history in one API call chain, regardless of `full`
    if source_id not in ("bts_t100", "bts_otp"):
        return [None]  # single-file bulk sources: re-pull the one current file
    now = datetime.now(UTC)
    start = (now.year, now.month)
    n_months = (cfg.t100_months if source_id == "bts_t100" else cfg.otp_months) or (
        _DEFAULT_T100_MONTHS if source_id == "bts_t100" else _DEFAULT_OTP_MONTHS
    )
    n = n_months if full else 1
    periods = _probe_trailing_periods(adapter, cache_dir, n, start)
    if not periods:
        raise RuntimeError(f"{source_id}: no available month found probing back from {start}")
    return periods


def _where_for(table: str, source_id: str, periods: list[Period | None]) -> dict:
    """`Store.replace_rows` `where`: scoped to one period when exactly one was fetched and
    the table carries a matching column; otherwise a full replace of this source's rows
    (the trailing-window sources are meant to drop old months on every full refresh)."""
    where: dict = {"source_id": source_id}
    if len(periods) == 1 and periods[0] is not None and periods[0].month is not None:
        column = _PERIOD_COLUMN.get(table)
        if column == "period":
            where["period"] = periods[0].label()
        elif column == "year":
            where["year"] = periods[0].year
    return where


def _ingest_one(
    store: Store, cache_dir: Path, source_id: str, period: Period | None, full: bool, cfg: SourceConfig | None
) -> int:
    """Fetch + normalize + write one source; return the number of rows written."""
    cls = ADAPTERS[source_id]
    adapter = cls()
    periods = _resolve_periods(source_id, cfg, adapter, cache_dir, period, full) if cfg else [period]

    all_paths: list[Path] = []
    for p in periods:
        all_paths.extend(adapter.fetch(p, cache_dir))
    tables = adapter.normalize(all_paths)

    rows = 0
    if source_id == "faa_taf":
        for table, df in tables.items():
            if table == "airports":
                apply_taf_enrichment(store, df)
            else:
                store.replace_rows(table, df, _where_for(table, source_id, periods))
            rows += len(df)
    elif source_id == "census_cbsa":
        apply_cbsa_enrichment(store, tables["cbsa_population"], tables["cbsa_centroids"])
        rows = len(tables["cbsa_population"])
    else:
        for table, df in tables.items():
            store.replace_rows(table, df, _where_for(table, source_id, periods))
            rows += len(df)

    store.upsert_vintage(adapter.vintage())
    return rows


def refresh(
    sources: list[str] | None = None,
    period: Period | None = None,
    full: bool = False,
    cache_dir: Path | None = None,
    snapshot_path: Path | None = None,
) -> RefreshReport:
    """Refresh `sources` (default: every bulk `ADAPTERS` entry) into the snapshot at
    `snapshot_path`, then rebuild `airport_metrics`. Never raises for a per-source failure —
    see `RefreshReport.failed`."""
    cache_dir = cache_dir or raw_cache_dir()
    snapshot_path = snapshot_path or default_snapshot_path()
    started_at = datetime.now(UTC).isoformat()

    all_configs = load_sources()
    source_ids = sources if sources is not None else [
        s for s, cfg in all_configs.items() if cfg.kind == "bulk" and s in ADAPTERS
    ]

    store = Store(snapshot_path)
    results: list[SourceResult] = []
    for source_id in source_ids:
        t0 = time.monotonic()
        if source_id not in ADAPTERS:
            results.append(
                SourceResult(source_id, False, 0, time.monotonic() - t0, f"no registered adapter for {source_id!r}")
            )
            continue
        cfg = all_configs.get(source_id)
        if cfg is not None and cfg.kind == "live":
            results.append(
                SourceResult(source_id, False, 0, time.monotonic() - t0, "live source, not part of the snapshot refresh")
            )
            continue
        try:
            rows = _ingest_one(store, cache_dir, source_id, period, full, cfg)
            results.append(SourceResult(source_id, True, rows, time.monotonic() - t0, None))
        except Exception as exc:  # noqa: BLE001 (per-source isolation is the point)
            results.append(SourceResult(source_id, False, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}"))

    try:
        derived_row_counts = build_derived(store)
    finally:
        store.close()
    finished_at = datetime.now(UTC).isoformat()
    return RefreshReport(results=results, derived_row_counts=derived_row_counts, started_at=started_at, finished_at=finished_at)


def staleness(snapshot_path: Path | None = None, sources: dict[str, SourceConfig] | None = None) -> list[dict]:
    """Per-source staleness vs `cadence_days`: `[{source_id, status, fetched_at, cadence_days, age_days}]`.

    `status` is `"missing"` (never ingested), `"fresh"` (`cadence_days == 0`, i.e. live/local,
    or age within cadence), or `"stale"` (age beyond cadence)."""
    sources = sources if sources is not None else load_sources()
    store = Store(snapshot_path or default_snapshot_path())
    try:
        vintages = {v.source_id: v for v in store.vintages()}
    finally:
        store.close()
    now = datetime.now(UTC)
    out: list[dict] = []
    for source_id, cfg in sources.items():
        v = vintages.get(source_id)
        if v is None:
            out.append(
                {"source_id": source_id, "status": "missing", "fetched_at": None, "cadence_days": cfg.cadence_days, "age_days": None}
            )
            continue
        if cfg.cadence_days == 0:
            out.append(
                {"source_id": source_id, "status": "fresh", "fetched_at": v.fetched_at, "cadence_days": 0, "age_days": 0}
            )
            continue
        fetched = datetime.fromisoformat(v.fetched_at)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        age_days = (now - fetched).days
        status = "stale" if age_days > cfg.cadence_days else "fresh"
        out.append(
            {"source_id": source_id, "status": status, "fetched_at": v.fetched_at, "cadence_days": cfg.cadence_days, "age_days": age_days}
        )
    return out
