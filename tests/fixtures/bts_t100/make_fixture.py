"""Rebuild the committed BTS T-100 Domestic Segment fixture subset (needs network).

Usage: uv run python tests/fixtures/bts_t100/make_fixture.py

Runs the real adapter (`BtsT100SegmentAdapter.fetch`) for 2026-04 (scripts the
DL_SelectFields ASP.NET form, cached under `data/raw/`), keeps only the 15
fixture airports' origin rows, and caps each origin at `PER_ORIGIN_CAP` rows
(by descending departures, so the busiest real routes survive) to stay under
the ~300 KB fixture budget — the un-capped 15-airport subset is ~1.6 MB
(mega-hubs ORD/DEN/ATL/LAX alone contribute 1,000+ rows each). No separate
"keep every cargo row" carve-out: ANC's real `SEATS=0` freighter routes are
high-frequency enough (verified: 37 of ANC's top-80-by-departures rows are
cargo) to survive the departures-based cap on their own, which also keeps
ANC's real nonstop-destination count (34, verified) inside the 6-50 range
`tests/contracts/test_data_service_contract.py::test_routes_sorted_and_flagged`
expects (calibrated to `tests/fakes.py`'s 6-route synthetic ANC) — an earlier
version of this script kept every cargo row unconditionally, which pushed
ANC to 63 destinations and broke that frozen test. Rows are copied verbatim
from the real file.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_t100 import SOURCE_COLUMNS, BtsT100SegmentAdapter
from airport_agent.data.paths import raw_cache_dir

HERE = Path(__file__).resolve().parent

FIXTURE_IATAS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]

PER_ORIGIN_CAP = 80


def main() -> None:
    adapter = BtsT100SegmentAdapter()
    paths = adapter.fetch(Period(year=2026, month=4), raw_cache_dir())
    raw = pd.read_csv(paths[0], usecols=list(SOURCE_COLUMNS))
    keep = raw[raw["ORIGIN"].isin(FIXTURE_IATAS)].copy()

    parts = []
    for _origin, group in keep.groupby("ORIGIN"):
        by_departures = group.sort_values("DEPARTURES_PERFORMED", ascending=False)
        parts.append(by_departures.head(PER_ORIGIN_CAP))
    trimmed = pd.concat(parts, ignore_index=True).sort_values(["ORIGIN", "DEST"])

    missing = sorted(set(FIXTURE_IATAS) - set(trimmed["ORIGIN"]))
    if missing:
        raise SystemExit(f"missing fixture airports: {missing}")

    out = HERE / "dom_2026_04_subset.csv"
    trimmed.to_csv(out, index=False)
    print(f"wrote {out.name}: {len(trimmed)} rows, {out.stat().st_size // 1024} KB")
    anc_cargo = trimmed[(trimmed["ORIGIN"] == "ANC") & (trimmed["SEATS"] == 0)]
    print(f"ANC cargo (SEATS=0) rows: {len(anc_cargo)}, distinct dests: {anc_cargo['DEST'].nunique()}")


if __name__ == "__main__":
    main()
