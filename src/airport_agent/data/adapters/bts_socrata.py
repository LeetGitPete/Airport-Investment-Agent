"""BTS Socrata REST adapter — the `airport_month` / `airport_year` traffic measures.

Source: `https://data.bts.gov/resource/r495-tyji.json` — "T-100 Segment Summary by
Origin Airport", live Socrata REST, no auth (see
docs/research/2026-08-15-us-aviation-data-sources.md §3). This is the monthly
traffic backbone the enplanement, load-factor and international-mix metrics run on.

Verified 2026-08-15 against the real API (the research note's field names were
close but not exact — the dataset's *real* field names, pinned here from the
Socrata metadata endpoint `.../api/views/r495-tyji.json`):

* `origin_airport_code` is the IATA-style code used everywhere else in the store
  (verified BOS/ANC/JFK/... match); `year` (text, "YYYY") and `reporting_month`
  (a `calendar_date`, "YYYY-MM-01T00:00:00.000") together identify the period.
* Every numeric field is stored as **text** in the JSON response, even when cast
  with `::number` in SoQL (Socrata always serializes numbers as JSON strings for
  precision-safety) — `normalize` always runs `pd.to_numeric(..., errors="coerce")`
  regardless of whether `fetch` requested a cast.
* There is **no single "total load factor" measure written**: `load_factor` is
  computed here as `total_passengers / total_seats` (verified against the vendor's
  own `total_load_factor` column, e.g. BOS 2025-01: 1352775/1836406 = 73.68% vs the
  vendor's reported 73.7%) rather than trusted as a pre-rounded percentage.
* International split fields are **not** named `intl_out_passengers` /
  `intl_in_passengers` upstream — they are `outbound_international_1` /
  `inbound_international_1` (Socrata's auto-generated names for the 2nd/3rd column
  named "... Passengers" in the source spreadsheet; verified against the metadata
  endpoint, not guessed). Domestic passengers is `domestic_passengers`.
* Full history: `min(year)=2014`, `max(year)=2026` (2026-04 latest as of
  2026-08-15), ~131,700 rows total — three pages at the Socrata max `$limit=50000`.

`fetch` pages through the *entire* dataset (every US origin airport, not just the
15 fixture airports) with `$select` casting every numeric field via `::number` (a
belt-and-suspenders measure: it doesn't change the client-side dtype but keeps the
query itself honest about intent) and `$where` narrowed to `period` when one is
given (`year='YYYY'` or `year='YYYY' AND date_extract_m(reporting_month)=M`) —
`period=None` fetches `year >= '2014'`, i.e. everything. Each page is cached
individually via `download()`.

Measures written to `airport_month` (long format, one row per iata/period/measure):
`total_passengers, total_seats, total_departures, dom_passengers,
intl_out_passengers, intl_in_passengers, load_factor`. `airport_year` rollups
(`enplanements=Σtotal_passengers, seats=Σtotal_seats, departures=Σtotal_departures`)
are written only for **complete** years (12 distinct months present for that
iata/year) — partial years are left for callers to handle via TAF/trailing-12m
fallback (see plan "Derived metric definitions", `annual_enplanements`).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage

SOCRATA_URL = "https://data.bts.gov/resource/r495-tyji.json"

#: Socrata's own max page size for this dataset.
PAGE_LIMIT = 50_000

#: Text fields selected verbatim (no cast).
TEXT_FIELDS: tuple[str, ...] = ("origin_airport_code", "year", "reporting_month")

#: Numeric source fields (real Socrata field names, verified against the metadata
#: endpoint — see module docstring) selected with an explicit `::number` cast.
NUMERIC_FIELDS: tuple[str, ...] = (
    "total_departures",
    "total_passengers",
    "total_seats",
    "domestic_passengers",
    "outbound_international_1",
    "inbound_international_1",
)

#: Numeric source field -> `airport_month` measure name (load_factor is derived, not selected).
MEASURE_MAP: dict[str, str] = {
    "total_passengers": "total_passengers",
    "total_seats": "total_seats",
    "total_departures": "total_departures",
    "domestic_passengers": "dom_passengers",
    "outbound_international_1": "intl_out_passengers",
    "inbound_international_1": "intl_in_passengers",
}

#: `airport_month` measures in the order they are emitted for a single period.
MONTH_MEASURES: tuple[str, ...] = (*MEASURE_MAP.values(), "load_factor")

#: `airport_year` measures (only written for complete 12-month years).
YEAR_MEASURES: tuple[str, ...] = ("enplanements", "seats", "departures")

AIRPORT_MONTH_COLUMNS: tuple[str, ...] = ("iata", "period", "measure", "value", "source_id", "vintage")
AIRPORT_YEAR_COLUMNS: tuple[str, ...] = ("iata", "year", "measure", "value", "source_id", "vintage")

EARLIEST_YEAR = 2014


def _select_clause() -> str:
    casts = [f"{field}::number as {field}" for field in NUMERIC_FIELDS]
    return ",".join((*TEXT_FIELDS, *casts))


def _where_clause(period: Period | None) -> str:
    if period is None:
        return f"year >= '{EARLIEST_YEAR}'"
    if period.month is None:
        return f"year='{period.year}'"
    return f"year='{period.year}' AND date_extract_m(reporting_month)={period.month}"


def _page_url(where: str, offset: int) -> str:
    params = {
        "$select": _select_clause(),
        "$where": where,
        "$order": "origin_airport_code,reporting_month",
        "$limit": str(PAGE_LIMIT),
        "$offset": str(offset),
    }
    return str(httpx.URL(SOCRATA_URL, params=params))


def _page_filename(where: str, offset: int) -> str:
    import hashlib

    key = hashlib.sha1(where.encode("utf-8")).hexdigest()[:10]  # noqa: S324 (cache key, not security)
    return f"bts_socrata_{key}_{offset:07d}.json"


def _read_page(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_pages(paths: list[Path]) -> pd.DataFrame:
    rows: list[dict] = []
    for path in paths:
        rows.extend(_read_page(path))
    if not rows:
        return pd.DataFrame(columns=[*TEXT_FIELDS, *NUMERIC_FIELDS])
    return pd.DataFrame(rows)


@register
class BtsSocrataAdapter:
    """Fetch/normalize the BTS Socrata T-100 Segment Summary by Origin Airport."""

    id: str = "bts_socrata"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw files' own dates
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._period_start: str | None = None
        self._period_end: str | None = None

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Page through the API (cached per page) for `period`, or all of history if `None`."""
        where = _where_clause(period)
        paths: list[Path] = []
        offset = 0
        while True:
            url = _page_url(where, offset)
            path = download(url, cache_dir, filename=_page_filename(where, offset))
            paths.append(path)
            if len(_read_page(path)) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        self._set_vintage(paths)
        return paths

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"airport_month": df, "airport_year": df}`."""
        self._set_vintage(paths)
        raw = _read_pages(paths)
        core = self._core_frame(raw)
        self._period_start = core["period"].min() if len(core) else None
        self._period_end = core["period"].max() if len(core) else None
        return {
            "airport_month": self._month_frame(core),
            "airport_year": self._year_frame(core),
        }

    def _core_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            cols = ["iata", "year", "period", *MEASURE_MAP.values(), "load_factor"]
            return pd.DataFrame(columns=cols)
        core = pd.DataFrame(
            {
                "iata": raw["origin_airport_code"].astype(str).str.strip(),
                "year": pd.to_numeric(raw["year"], errors="coerce").astype("Int64"),
                "period": pd.to_datetime(raw["reporting_month"]).dt.strftime("%Y-%m"),
            }
        )
        for source_field, measure in MEASURE_MAP.items():
            # Socrata omits a field from the JSON row entirely when it is null (verified:
            # PWM rows carry no `outbound_international_1`/`inbound_international_1` keys at
            # all), so a whole page can lack a column pandas never created.
            if source_field in raw.columns:
                core[measure] = pd.to_numeric(raw[source_field], errors="coerce")
            else:
                core[measure] = pd.NA
        core["load_factor"] = (core["total_passengers"] / core["total_seats"]).where(
            core["total_seats"] > 0
        )
        return core

    def _month_frame(self, core: pd.DataFrame) -> pd.DataFrame:
        long = core.melt(
            id_vars=["iata", "period"],
            value_vars=list(MONTH_MEASURES),
            var_name="measure",
            value_name="value",
        ).dropna(subset=["value"])
        long["source_id"] = self.id
        long["vintage"] = self.row_vintage()
        return (
            long[list(AIRPORT_MONTH_COLUMNS)]
            .sort_values(["iata", "period", "measure"])
            .reset_index(drop=True)
        )

    def _year_frame(self, core: pd.DataFrame) -> pd.DataFrame:
        if core.empty:
            return pd.DataFrame(columns=AIRPORT_YEAR_COLUMNS)
        by_year = (
            core.dropna(subset=["year"])
            .groupby(["iata", "year"], as_index=False)
            .agg(
                n_months=("period", "nunique"),
                enplanements=("total_passengers", "sum"),
                seats=("total_seats", "sum"),
                departures=("total_departures", "sum"),
            )
        )
        complete = by_year[by_year["n_months"] == 12].copy()
        if complete.empty:
            return pd.DataFrame(columns=AIRPORT_YEAR_COLUMNS)
        complete["year"] = complete["year"].astype("int64")
        long = complete.melt(
            id_vars=["iata", "year"],
            value_vars=list(YEAR_MEASURES),
            var_name="measure",
            value_name="value",
        )
        long["source_id"] = self.id
        long["vintage"] = self.row_vintage()
        return (
            long[list(AIRPORT_YEAR_COLUMNS)]
            .sort_values(["iata", "year", "measure"])
            .reset_index(drop=True)
        )

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw pages' mtimes (see `file_vintage`)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw pages' date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                "BTS Socrata T-100 Segment Summary by Origin Airport — monthly "
                "passengers/seats/departures, domestic + inbound/outbound international"
            ),
            period_start=self._period_start,
            period_end=self._period_end,
            fetched_at=self._fetched_at,
            url=SOCRATA_URL,
        )
