"""Rebuild the committed FAA AIP grant-history fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/faa_aip/make_fixture.py

Downloads all 10 real fiscal-year workbooks once (cached under `data/raw/faa_aip/` via
`FaaAipAdapter._resolve_urls`/`download`), keeps the rows for the 15 fixture airports plus
two real `*`-prefixed block-grant rows (to exercise the block-grant filter) from whichever
sheet `_read_grant_table` picks, and writes one small workbook per fiscal year next to this
file. FY2018's real quirk (two sheets carry the grant detail; a third is a pivot summary
with no `LocID` column) is preserved by also copying its decoy pivot sheet verbatim, so the
adapter's sheet-selection logic is exercised, not just its column parsing. Rows are copied
verbatim from the real workbook (column names, including embedded newlines like FY2021's
`"Total\\nAmount"`, and cell values) — fixture values are always real upstream values, never
invented.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import download
from airport_agent.data.adapters.faa_aip import (
    FISCAL_YEARS,
    FaaAipAdapter,
    _find_header_row,
    _fy_from_filename,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_LOCIDS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]
HERE = Path(__file__).resolve().parent
CACHE_DIR = raw_cache_dir() / "faa_aip"

#: FY2018's decoy pivot sheet (no `LocID` column) — copied verbatim to prove the
#: sheet-selection logic skips it rather than erroring on it.
FY2018_DECOY_SHEET = "Sheet1"


def _real_sheet_and_header(path: Path) -> tuple[str, int]:
    """Same candidate scan as `_read_grant_table`, but returns the winning sheet's name."""
    xls = pd.ExcelFile(path)
    fy = str(_fy_from_filename(path))
    candidates = []
    for sheet in xls.sheet_names:
        header_row = _find_header_row(path, sheet)
        if header_row is None:
            continue
        df = pd.read_excel(path, sheet_name=sheet, header=header_row)
        cols_lower = [str(c).strip().lower() for c in df.columns]
        if "locid" not in cols_lower:
            continue
        if not any("total" in c and "amount" in c for c in cols_lower) and "aip federal funds" not in cols_lower:
            continue
        candidates.append((sheet, header_row, len(df)))
    if not candidates:
        raise SystemExit(f"{path.name}: no qualifying sheet found")
    preferred = [c for c in candidates if fy in c[0]]
    pool = preferred or candidates
    sheet, header_row, _ = max(pool, key=lambda c: c[2])
    return sheet, header_row


def _subset(path: Path, sheet: str, header_row: int) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet, header=header_row)
    locid_col = next(c for c in df.columns if str(c).strip().lower() == "locid")
    df[locid_col] = df[locid_col].astype(str).str.strip()
    keep = df[df[locid_col].isin(FIXTURE_LOCIDS)]
    missing = sorted(set(FIXTURE_LOCIDS) - set(keep[locid_col]))
    if missing:
        print(f"  note: {path.name} has no grant row for {missing} (expected — not every airport gets a grant every year)")
    block = df[df[locid_col].str.startswith("*")].head(2)
    return pd.concat([keep, block], ignore_index=True)


def main() -> None:
    urls = FaaAipAdapter._resolve_urls(CACHE_DIR)
    for fy in FISCAL_YEARS:
        path = download(urls[fy], CACHE_DIR, filename=f"FY{fy}.xlsx")
        sheet, header_row = _real_sheet_and_header(path)
        out_subset = _subset(path, sheet, header_row)
        out_path = HERE / f"FY{fy}.xlsx"
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            out_subset.to_excel(writer, sheet_name=sheet, index=False)
            if fy == 2018:
                decoy = pd.read_excel(path, sheet_name=FY2018_DECOY_SHEET, header=None, nrows=8)
                decoy.to_excel(writer, sheet_name=FY2018_DECOY_SHEET, header=False, index=False)
        print(f"wrote {out_path.name}: sheet={sheet!r} {len(out_subset)} rows, {out_path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
