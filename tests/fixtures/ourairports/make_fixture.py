"""Rebuild the committed OurAirports fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/ourairports/make_fixture.py

Downloads the real `airports.csv` / `runways.csv`, keeps the header plus the rows
for the 15 fixture airports (and their runways), and writes them next to this
file. Fixture rows are always real upstream rows — never hand-invented.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

BASE = "https://davidmegginson.github.io/ourairports-data"
FIXTURE_IATA = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]
HERE = Path(__file__).resolve().parent


def _get(name: str) -> str:
    response = httpx.get(f"{BASE}/{name}", follow_redirects=True, timeout=120.0)
    response.raise_for_status()
    return response.text


def main() -> None:
    airports = pd.read_csv(pd.io.common.StringIO(_get("airports.csv")), dtype=str, keep_default_na=False)
    runways = pd.read_csv(pd.io.common.StringIO(_get("runways.csv")), dtype=str, keep_default_na=False)

    keep = airports[(airports["iso_country"] == "US") & (airports["iata_code"].isin(FIXTURE_IATA))]
    missing = sorted(set(FIXTURE_IATA) - set(keep["iata_code"]))
    if missing:
        raise SystemExit(f"missing fixture airports upstream: {missing}")
    idents = set(keep["ident"])
    rwy = runways[runways["airport_ident"].isin(idents)]

    keep.to_csv(HERE / "airports.csv", index=False, encoding="utf-8", lineterminator="\n")
    rwy.to_csv(HERE / "runways.csv", index=False, encoding="utf-8", lineterminator="\n")
    print(f"wrote {len(keep)} airports, {len(rwy)} runways")


if __name__ == "__main__":
    main()
