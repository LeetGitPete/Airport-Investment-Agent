"""Rebuild the committed FAA NPIAS Appendix A fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/faa_npias/make_fixture.py

Downloads the real Appendix A workbook once (cached under `data/raw/`), keeps the rows of
the 15 fixture airports from the `All NPIAS Airports` sheet and writes them to
`appendix_a_subset.xlsx` next to this file. Rows and headers (embedded newlines included)
are copied verbatim - fixture values are always real upstream values, never invented.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import download
from airport_agent.data.adapters.faa_npias import NPIAS_FILENAME, NPIAS_URL, SHEET_NAME
from airport_agent.data.paths import raw_cache_dir

FIXTURE_LOCIDS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]
HERE = Path(__file__).resolve().parent


def main() -> None:
    path = download(NPIAS_URL, raw_cache_dir(), filename=NPIAS_FILENAME)
    df = pd.read_excel(path, sheet_name=SHEET_NAME, dtype={"LocID": str})
    keep = df[df["LocID"].str.strip().isin(FIXTURE_LOCIDS)]
    missing = sorted(set(FIXTURE_LOCIDS) - set(keep["LocID"].str.strip()))
    if missing:
        raise SystemExit(f"missing fixture airports in Appendix A: {missing}")
    out = HERE / "appendix_a_subset.xlsx"
    with pd.ExcelWriter(out) as writer:
        keep.to_excel(writer, sheet_name=SHEET_NAME, index=False)
    print(f"wrote {out.name}: {len(keep)} rows, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
