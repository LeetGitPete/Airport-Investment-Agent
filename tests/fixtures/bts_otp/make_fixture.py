"""Rebuild the committed BTS OTP fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/bts_otp/make_fixture.py

Downloads the real June 2026 On-Time Performance zip once (cached under
`data/raw/`, ~30 MB compressed / ~275 MB CSV, ~608k rows), keeps rows where
`Origin` or `Dest` is one of the 15 fixture airports (~13k rows, still too big
for the fixture budget), and caps each airport's rows to keep the fixture real
but small. Rows are copied verbatim from the real file.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_otp import SOURCE_COLUMNS, BtsOtpAdapter
from airport_agent.data.paths import raw_cache_dir

HERE = Path(__file__).resolve().parent

FIXTURE_IATAS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]

PER_AIRPORT_CAP = 110


def main() -> None:
    adapter = BtsOtpAdapter()
    paths = adapter.fetch(Period(year=2026, month=6), raw_cache_dir())
    raw = pd.read_csv(paths[0], usecols=list(SOURCE_COLUMNS))
    relevant = raw[raw["Origin"].isin(FIXTURE_IATAS) | raw["Dest"].isin(FIXTURE_IATAS)]

    parts = []
    for iata in FIXTURE_IATAS:
        mine = relevant[(relevant["Origin"] == iata) | (relevant["Dest"] == iata)]
        # Keep every cancelled row for this airport (small in number, needed for
        # cancelled_dep tests) plus a capped sample of the rest.
        cancelled = mine[mine["Cancelled"] == 1]
        rest = mine[mine["Cancelled"] == 0].sample(
            n=min(PER_AIRPORT_CAP, len(mine[mine["Cancelled"] == 0])), random_state=0
        )
        parts.append(pd.concat([cancelled, rest]))
    trimmed = pd.concat(parts, ignore_index=True).drop_duplicates()
    # Preserve every calendar day of the month somewhere in the file so the otp_peak
    # day x hour grid still spans the full month (verified: some capped airports would
    # otherwise lose late-month days entirely).
    trimmed = trimmed.sort_values(["Origin", "Dest", "DayofMonth", "CRSDepTime"])

    missing = sorted(set(FIXTURE_IATAS) - set(trimmed["Origin"]) - set(trimmed["Dest"]))
    if missing:
        raise SystemExit(f"missing fixture airports: {missing}")

    out = HERE / "otp_2026_06_subset.csv"
    trimmed.to_csv(out, index=False)
    print(f"wrote {out.name}: {len(trimmed)} rows, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
