"""FAA Airport Improvement Program (AIP) grant history adapter — the `aip_grants` table.

Source: the FAA AIP grant-history listing page
(`https://www.faa.gov/airports/aip/grant_histories`) links to one workbook per fiscal
year. FY2016-FY2020 links sit directly on that listing page; FY2021-FY2025 links live on
a per-year sub-page (`.../grant_histories/{fy}`) whose asset path is undated and
unpredictable (e.g. `/sites/faa.gov/files/2025-11/FY_2025_AIP_Grants.xlsx`) — both must be
scraped from the page HTML, never guessed from a fixed pattern.

Verified 2026-08-16 against all ten real workbooks (FY2016-FY2025, downloaded once into
`data/raw/faa_aip/`):

* Sheet name, the header row's offset, the `LocID` column's capitalisation
  (`LOCID`/`LocID`), and the grant-total column name all differ by year:
  - FY2016-FY2020: header on row 0; total = `AIP Federal Funds` (no separate "Total
    Amount" column exists yet — the federal award for that grant row *is* the total).
    FY2018 is a special case: its real per-grant sheet is named after the fiscal year
    itself (`"2018"`); the workbook also carries pivot-summary sheets (`Sheet1`,
    `Sheet3`) and a duplicate detail sheet (`Copy Of AIRPORTS_GRANT_HISTORY`) that must
    not be picked instead (verified: both detail sheets carry identical data, 2,785 rows,
    identical $3,460,467,200 total — the duplicate is harmless if picked, but the pivot
    sheets have no `LocID` column and must be skipped).
  - FY2021-FY2025: 1-2 title rows above the header; total = `Total Amount` (sometimes
    with an embedded newline, `"Total\\nAmount"` — collapse whitespace before lookup).
  `_read_grant_table` handles this by scanning every sheet's first 6 rows for a header
  containing a `LocID`-like column, then among the sheets that qualify (also has a
  total-amount-like column) preferring the one whose name contains the fiscal year's own
  digits, else the one with the most data rows.
* `LocID` values prefixed with `*` (e.g. `*AKS`, `*AKV`, `*GAB`) are FAA state/regional
  block grants, not a single airport (2-19% of rows per year, every year FY2016-FY2025) —
  they never match a real `airports.faa_locid` and are dropped rather than summed into a
  fake per-airport row.
* Every fixture airport that is a real commercial airport receives an AIP grant in some,
  not all, fiscal years (large hubs like ATL/JFK/SFO have grant-free years) — this is
  expected FAA funding-cycle behaviour, not a data gap: `aip_grants` legitimately has no
  row for (LocID, FY) when nothing was awarded that year.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage

GRANT_HISTORIES_URL = "https://www.faa.gov/airports/aip/grant_histories"
FAA_BASE_URL = "https://www.faa.gov"

#: FY2016..FY2025 — the 10 fiscal years the plan asks for.
FISCAL_YEARS: tuple[int, ...] = tuple(range(2016, 2026))

#: FY2016-2020 links sit directly on the listing page; FY2021+ links live on a per-year
#: sub-page with an undated asset path that must be scraped.
MAIN_PAGE_FYS: tuple[int, ...] = tuple(fy for fy in FISCAL_YEARS if fy <= 2020)
SUBPAGE_FYS: tuple[int, ...] = tuple(fy for fy in FISCAL_YEARS if fy > 2020)

_XLSX_HREF_RE = re.compile(r'href="([^"]+\.xlsx)"', re.IGNORECASE)
_FY_IN_FILENAME_RE = re.compile(r"FY(\d{4})", re.IGNORECASE)

#: `LocID` prefix marking a state/regional block grant, not a single airport (dropped).
BLOCK_GRANT_PREFIX = "*"

#: `aip_grants` columns in store order.
AIP_GRANTS_COLUMNS: tuple[str, ...] = ("faa_locid", "fy", "amount_usd", "source_id", "vintage")


def _collapse(x: object) -> str:
    """Collapse embedded newlines/padding some workbooks put inside header cells."""
    return re.sub(r"\s+", " ", str(x)).strip()


def _absolute(href: str) -> str:
    return href if href.startswith("http") else f"{FAA_BASE_URL}{href}"


def _fy_from_filename(path: Path) -> int:
    match = _FY_IN_FILENAME_RE.search(path.stem)
    if not match:
        raise ValueError(f"faa_aip: cannot read a fiscal year out of filename {path.name!r}")
    return int(match.group(1))


def _find_header_row(path: Path, sheet: str) -> int | None:
    """Row index of the header within `sheet`'s first 6 rows, or `None` if it has no `LocID` column."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=6)
    for i, row in raw.iterrows():
        cells = [_collapse(c) for c in row if pd.notna(c)]
        if any(c.lower() == "locid" for c in cells):
            return int(i)
    return None


def _read_grant_table(path: Path) -> pd.DataFrame:
    """Return `(faa_locid, amount_usd)` from whichever sheet holds the real grant rows.

    Scans every sheet for a header row with both a `LocID`-like and a grant-total-like
    column; among sheets that qualify, prefers the one named after the fiscal year (FY2018
    quirk), else the one with the most rows. See module docstring for the verified format
    facts this encodes.
    """
    fy = _fy_from_filename(path)
    xls = pd.ExcelFile(path)
    candidates: list[tuple[str, pd.DataFrame]] = []
    for sheet in xls.sheet_names:
        header_row = _find_header_row(path, sheet)
        if header_row is None:
            continue
        df = pd.read_excel(path, sheet_name=sheet, header=header_row)
        df.columns = [_collapse(c) for c in df.columns]
        locid_col = next((c for c in df.columns if c.lower() == "locid"), None)
        total_col = next((c for c in df.columns if c.lower() == "total amount"), None)
        if total_col is None:
            total_col = next((c for c in df.columns if c.lower() == "aip federal funds"), None)
        if locid_col is None or total_col is None:
            continue
        candidates.append((sheet, df[[locid_col, total_col]].rename(
            columns={locid_col: "faa_locid", total_col: "amount_usd"}
        )))
    if not candidates:
        raise ValueError(f"{path.name}: no sheet with both a LocID and a grant-total column found")
    fy_str = str(fy)
    preferred = [c for c in candidates if fy_str in c[0]]
    pool = preferred or candidates
    _, best = max(pool, key=lambda c: len(c[1]))
    return best


@register
class FaaAipAdapter:
    """Fetch/normalize FAA AIP grant histories (FY2016-FY2025) into `aip_grants`."""

    id: str = "faa_aip"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw files' own dates.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download all 10 fiscal years' grant workbooks (cached). `period` is ignored."""
        urls = self._resolve_urls(cache_dir)
        paths = [download(urls[fy], cache_dir, filename=f"FY{fy}.xlsx") for fy in FISCAL_YEARS]
        self._set_vintage(paths)
        return paths

    @staticmethod
    def _resolve_urls(cache_dir: Path) -> dict[int, str]:
        """Scrape the listing page (FY2016-2020) and each per-year sub-page (FY2021+) for xlsx links."""
        urls: dict[int, str] = {}
        index_path = download(GRANT_HISTORIES_URL, cache_dir, filename="grant_histories_index.html")
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
        index_hrefs = _XLSX_HREF_RE.findall(index_text)
        for fy in MAIN_PAGE_FYS:
            match = next((h for h in index_hrefs if f"fy{fy}-aip-grants.xlsx" in h.lower()), None)
            if match is None:
                raise ValueError(f"faa_aip: no FY{fy} link found on {GRANT_HISTORIES_URL}")
            urls[fy] = _absolute(match)
        for fy in SUBPAGE_FYS:
            sub_path = download(f"{GRANT_HISTORIES_URL}/{fy}", cache_dir, filename=f"grant_histories_{fy}.html")
            sub_text = sub_path.read_text(encoding="utf-8", errors="replace")
            sub_hrefs = _XLSX_HREF_RE.findall(sub_text)
            if not sub_hrefs:
                raise ValueError(f"faa_aip: no xlsx link found on {GRANT_HISTORIES_URL}/{fy}")
            urls[fy] = _absolute(sub_hrefs[0])
        return urls

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"aip_grants": df}`: one row per (faa_locid, fy) with amounts summed."""
        self._set_vintage(paths)
        frames = []
        for path in paths:
            fy = _fy_from_filename(path)
            raw = _read_grant_table(path).copy()
            raw["faa_locid"] = raw["faa_locid"].astype(str).str.strip()
            raw = raw[raw["faa_locid"] != ""]
            raw = raw[~raw["faa_locid"].str.startswith(BLOCK_GRANT_PREFIX)]
            raw["amount_usd"] = pd.to_numeric(raw["amount_usd"], errors="coerce")
            raw = raw.dropna(subset=["amount_usd"])
            grouped = raw.groupby("faa_locid", as_index=False)["amount_usd"].sum()
            grouped["fy"] = fy
            frames.append(grouped)
        out = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["faa_locid", "amount_usd", "fy"])
        )
        out["source_id"] = self.id
        out["vintage"] = self.row_vintage()
        return {
            "aip_grants": out[list(AIP_GRANTS_COLUMNS)]
            .sort_values(["fy", "faa_locid"])
            .reset_index(drop=True)
        }

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw files' mtimes (see `file_vintage`)."""
        xlsx_paths = [p for p in paths if p.suffix.lower() == ".xlsx"] or list(paths)
        self._vintage, self._fetched_at = file_vintage(xlsx_paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw files' date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                f"FAA Airport Improvement Program grant histories, FY{FISCAL_YEARS[0]}-"
                f"FY{FISCAL_YEARS[-1]} ({len(FISCAL_YEARS)} fiscal-year workbooks, scraped from "
                f"{GRANT_HISTORIES_URL})"
            ),
            period_start=str(FISCAL_YEARS[0]),
            period_end=str(FISCAL_YEARS[-1]),
            fetched_at=self._fetched_at,
            url=GRANT_HISTORIES_URL,
        )
