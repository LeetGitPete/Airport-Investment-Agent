"""Rebuild the committed FAA TAF fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/faa_taf/make_fixture.py

Downloads the real TAF zip once (cached under `data/raw/`), keeps the rows for the
15 fixture airports across every year (1976-2055) from `Airports.xlsx`,
`Enplanements.xlsx` and `AirportsOperations.xlsx`, and writes the three subsets next
to this file. Rows are copied verbatim (including the trailing-space padding the FAA
puts in `locid`) - fixture values are always real upstream values, never invented.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import download
from airport_agent.data.adapters.faa_taf import MEMBER_FILES, TAF_ZIP_URL, ZIP_FILENAME
from airport_agent.data.paths import raw_cache_dir

FIXTURE_LOCIDS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]
HERE = Path(__file__).resolve().parent


def _subset(zf: zipfile.ZipFile, member: str, locid_column: str) -> pd.DataFrame:
    with zf.open(member) as fh:
        df = pd.read_excel(fh, dtype={locid_column: str})
    keep = df[df[locid_column].str.strip().isin(FIXTURE_LOCIDS)]
    missing = sorted(set(FIXTURE_LOCIDS) - set(keep[locid_column].str.strip()))
    if missing:
        raise SystemExit(f"missing fixture airports in {member}: {missing}")
    return keep


def main() -> None:
    zip_path = download(TAF_ZIP_URL, raw_cache_dir(), filename=ZIP_FILENAME)
    with zipfile.ZipFile(zip_path) as zf:
        for member in MEMBER_FILES:
            locid_column = "LOCID" if member == "Airports.xlsx" else "locid"
            keep = _subset(zf, member, locid_column)
            out = HERE / member
            keep.to_excel(out, index=False)
            print(f"wrote {out.name}: {len(keep)} rows, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
