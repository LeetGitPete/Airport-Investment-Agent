"""BTS T-100 Segment (Domestic) adapter — the `routes_month` table, domestic only.

Source: BTS TranStats "DL_SelectFields" ASP.NET form,
`https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM&QO_fu146_anzr=Nv4%20Pn44vr45`
(`FIM` = T-100 Domestic Segment; see
docs/research/2026-08-15-us-aviation-data-sources.md §2). Route-level monthly
traffic for **every** US-carrier segment including all-cargo carriers (`SEATS=0`
rows) — the only source with per-route distance, so it drives `spill_proxy`,
`longhaul_dep_share`, `carrier_hhi`, `route_count_nonstop`, `competing_seats_100mi`.

Verified 2026-08-16 by scripting the real form:

* GET the form URL to scrape `__VIEWSTATE`, `__VIEWSTATEGENERATOR`,
  `__EVENTVALIDATION`; POST back to the *same* URL with those three plus
  `cboGeography=All`, `cboYear`, `cboPeriod` (a month number `1`-`12`, or `"All"`
  for the whole year in one file), `chkAllVars=on`, `chkDownloadZip=on`,
  `btnDownload=Download`. **The ASP.NET session cookie set on the GET must be
  replayed on the POST** (an `httpx.Client` instance, reused across both calls,
  does this automatically) — without it the POST just re-renders the form page
  (HTML, not a zip) instead of returning data.
* Response: `Content-Type: application/zip`,
  `T_T100D_SEGMENT_US_CARRIER_ONLY_<timestamp>.zip` containing `Documentation.csv`
  (a field-name glossary) and one data CSV (`T_T100D_SEGMENT_US_CARRIER_ONLY.csv`),
  45 columns. One real month (2026-04, all US airports) = ~1.3 MB zipped / ~10 MB
  CSV, ~130k rows.
* Publication lag: as of 2026-08-16 the latest available month is 2026-05
  (`cboPeriod=6` for June still returns the form page, not a zip) — roughly a
  3-month lag, similar to OTP's ~2 months.
* `AIRCRAFT_CONFIG` is a numeric group code (no lookup table shipped in this
  response) — stored verbatim as text; `CLASS` (scheduled/nonscheduled,
  passenger/cargo) is present in the source but not carried into `routes_month`
  (the store schema has no column for it and every `CLASS` value is already
  present in one undifferentiated file, so cargo-only segments are not filtered
  out — verified: ANC 2026-04 has 247 of 488 origin rows with `SEATS=0.00`,
  all-cargo carriers like Everts Air Cargo and Northern Air Cargo).

**International Segment table: not landed.** A timeboxed probe tried
`FIL`/`FIH`/`FIS`/`FIT`/`FIN`/`FIQ`/`FIP`/
`FIO`/`FIC`/`FIB`/`FID`/`FGH`/`FGJ`..`FGQ`/`FMG` — every one 302-redirects to
`/Homepage.asp` (an invalid `gnoyr_VQ` code), unlike `FIM` which is a direct 200.
The TranStats database-index pages (`Tables.asp?DB_ID=111`, `DatabaseInfo.asp`)
did not surface the international segment table's code either, so `routes_month`
is `is_international=False`-only; international
totals (not route-level) remain available from `bts_socrata`
(`intl_out_passengers`/`intl_in_passengers`). See known-limitations row 2 update.
"""
from __future__ import annotations

import calendar
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage

#: Same URL for the GET (scrape hidden fields) and the POST (submit the form).
FORM_URL = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM&QO_fu146_anzr=Nv4%20Pn44vr45"

_VIEWSTATE_RE = re.compile(r'id="__VIEWSTATE" value="([^"]*)"')
_VIEWSTATEGENERATOR_RE = re.compile(r'id="__VIEWSTATEGENERATOR" value="([^"]*)"')
_EVENTVALIDATION_RE = re.compile(r'id="__EVENTVALIDATION" value="([^"]*)"')

#: Source CSV columns this adapter reads (of the 45 the form can return).
SOURCE_COLUMNS: tuple[str, ...] = (
    "ORIGIN",
    "DEST",
    "DEST_CITY_NAME",
    "DISTANCE",
    "SEATS",
    "PASSENGERS",
    "DEPARTURES_PERFORMED",
    "FREIGHT",
    "MAIL",
    "UNIQUE_CARRIER",
    "AIRCRAFT_CONFIG",
    "YEAR",
    "MONTH",
)

#: `routes_month` columns in store order.
ROUTES_MONTH_COLUMNS: tuple[str, ...] = (
    "iata",
    "dest",
    "dest_name",
    "period",
    "carrier",
    "distance_mi",
    "departures",
    "seats",
    "passengers",
    "freight_lb",
    "mail_lb",
    "is_international",
    "aircraft_config",
    "source_id",
    "vintage",
)


def _scrape_hidden_fields(html: str) -> dict[str, str]:
    """Pull the three ASP.NET postback fields out of the form page's HTML."""
    matches = {
        "__VIEWSTATE": _VIEWSTATE_RE.search(html),
        "__VIEWSTATEGENERATOR": _VIEWSTATEGENERATOR_RE.search(html),
        "__EVENTVALIDATION": _EVENTVALIDATION_RE.search(html),
    }
    missing = [name for name, m in matches.items() if m is None]
    if missing:
        raise ValueError(f"bts_t100 form page is missing expected hidden field(s): {missing}")
    return {name: m.group(1) for name, m in matches.items()}  # type: ignore[union-attr]


def _cache_key(period: Period) -> str:
    return f"bts_t100_dom_{period.label()}"


def _extract_data_csv(zip_path: Path, dest: Path) -> Path:
    """Extract the one data CSV from the zip (`Documentation.csv` is a field glossary, skipped).

    A not-yet-published month (per the module docstring: `cboPeriod` for a future month
    "still returns the form page, not a zip") is an HTTP 200 whose body is the HTML form
    page, not a zip — `download()` has no way to know that and caches it as if it were a
    real response. Detected here (`zipfile.BadZipFile`) and turned into a `ValueError` any
    caller can catch generically as "period not available"; the bad cached file is deleted
    so a later refresh re-fetches instead of replaying the same stale non-zip forever.
    """
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        _extract_from_zip(zip_path, dest)
    except zipfile.BadZipFile as exc:
        zip_path.unlink(missing_ok=True)
        raise ValueError(f"{zip_path.name} is not a zip (likely an unpublished period's form re-render)") from exc
    return dest


def _extract_from_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower() != "documentation.csv" and n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected exactly one data CSV in {zip_path.name}, found {names}")
        member = names[0]
        info = zf.getinfo(member)
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            with zf.open(member) as src, part.open("wb") as fh:
                while chunk := src.read(1 << 20):
                    fh.write(chunk)
            part.replace(dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    # Stamp with the zip entry's own timestamp (see faa_taf._extract for the same idea).
    stamp = calendar.timegm((*info.date_time, 0, 0, -1))
    os.utime(dest, (stamp, stamp))


@register
class BtsT100SegmentAdapter:
    """Fetch/normalize the BTS T-100 Domestic Segment into `routes_month`."""

    id: str = "bts_t100"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw file's own date
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._period_start: str | None = None
        self._period_end: str | None = None

    # fetch
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Submit the DL_SelectFields form for `period` (required) and cache the extracted CSV.

        `period.month=None` requests the whole year in one file (`cboPeriod=All`);
        otherwise one month. There is no "fetch everything" mode for this adapter — the
        form has no such option and a single request would be enormous — so unlike the
        other bulk adapters, `period=None` raises `ValueError` rather than silently
        defaulting.
        """
        if period is None:
            raise ValueError("bts_t100 requires an explicit period (year, or year+month)")
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _cache_key(period)
        zip_dest = cache_dir / f"{key}.zip"
        if not (zip_dest.exists() and zip_dest.stat().st_size > 0):
            client = httpx.Client(follow_redirects=True, timeout=180.0)
            try:
                form_page = client.get(FORM_URL)
                form_page.raise_for_status()
                hidden = _scrape_hidden_fields(form_page.text)
                data = {
                    **hidden,
                    "cboGeography": "All",
                    "cboYear": str(period.year),
                    "cboPeriod": str(period.month) if period.month is not None else "All",
                    "chkAllVars": "on",
                    "chkDownloadZip": "on",
                    "btnDownload": "Download",
                }
                download(FORM_URL, cache_dir, method="POST", data=data, client=client, filename=zip_dest.name)
            finally:
                client.close()
        csv_path = _extract_data_csv(zip_dest, cache_dir / f"{key}.csv")
        self._set_vintage([csv_path])
        return [csv_path]

    # normalize
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"routes_month": df}`. Every row is `is_international=False`."""
        self._set_vintage(paths)
        frames = [pd.read_csv(p, usecols=list(SOURCE_COLUMNS)) for p in paths]
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SOURCE_COLUMNS)
        out = self._routes_frame(raw)
        self._period_start = out["period"].min() if len(out) else None
        self._period_end = out["period"].max() if len(out) else None
        return {"routes_month": out}

    def _routes_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(columns=ROUTES_MONTH_COLUMNS)
        year = pd.to_numeric(raw["YEAR"], errors="coerce").astype("Int64")
        month = pd.to_numeric(raw["MONTH"], errors="coerce").astype("Int64")
        out = pd.DataFrame(
            {
                "iata": raw["ORIGIN"].astype(str).str.strip(),
                "dest": raw["DEST"].astype(str).str.strip(),
                "dest_name": raw["DEST_CITY_NAME"].astype(str).str.strip(),
                "period": year.astype(str) + "-" + month.astype(str).str.zfill(2),
                "carrier": raw["UNIQUE_CARRIER"].astype(str).str.strip(),
                "distance_mi": pd.to_numeric(raw["DISTANCE"], errors="coerce"),
                "departures": pd.to_numeric(raw["DEPARTURES_PERFORMED"], errors="coerce").round().astype("Int64"),
                "seats": pd.to_numeric(raw["SEATS"], errors="coerce").round().astype("Int64"),
                "passengers": pd.to_numeric(raw["PASSENGERS"], errors="coerce").round().astype("Int64"),
                "freight_lb": pd.to_numeric(raw["FREIGHT"], errors="coerce"),
                "mail_lb": pd.to_numeric(raw["MAIL"], errors="coerce"),
                "is_international": False,
                "aircraft_config": raw["AIRCRAFT_CONFIG"].astype(str).str.strip(),
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        return out[list(ROUTES_MONTH_COLUMNS)].sort_values(["iata", "period", "dest", "carrier"]).reset_index(
            drop=True
        )

    # provenance
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw file's mtime (see `file_vintage`)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw file's date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                "BTS T-100 Domestic Segment — route-level monthly departures/seats/passengers/"
                "freight/mail, all US carriers incl. all-cargo (domestic only; international "
                "segment table not landed, see module docstring)"
            ),
            period_start=self._period_start,
            period_end=self._period_end,
            fetched_at=self._fetched_at,
            url=FORM_URL,
        )
