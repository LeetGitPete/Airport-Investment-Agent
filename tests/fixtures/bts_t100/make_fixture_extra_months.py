"""Add 5 extra months of BTS T-100 Domestic Segment data for BOS/SFO/ANC (needs network).

Usage: uv run python tests/fixtures/bts_t100/make_fixture_extra_months.py

These months exist because the frozen
`tests/contracts/test_data_service_contract.py::test_feature_matrix_12m_covers_tier_a`
requires `spill_proxy` (tier A, 12m, not in `ATTEMPT_IDS`) to be non-None for BOS/SFO/ANC.
`spill_proxy` needs >=6 months of data for at least one (dest, carrier) pair per airport
(plan "Derived metric definitions"); the original single-month fixture
(`dom_2026_04_subset.csv`, 2026-04 only) can never satisfy that. This script fetches
2025-11..2026-03 (5 more real months) for BOS/SFO/ANC only (not all 15 fixture airports,
to stay well under the ~300 KB fixture budget — `spill_proxy` is only golden-checked for
these three) capped at the top 15 routes per origin per month by departures, so the same
real high-frequency routes repeat across months. Rows are copied verbatim from the API.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_t100 import SOURCE_COLUMNS, BtsT100SegmentAdapter
from airport_agent.data.paths import raw_cache_dir

HERE = Path(__file__).resolve().parent

FIXTURE_IATAS = ["BOS", "SFO", "ANC"]
PERIODS = [Period(year=2025, month=11), Period(year=2025, month=12), Period(year=2026, month=1),
           Period(year=2026, month=2), Period(year=2026, month=3)]
PER_ORIGIN_CAP = 15


def main() -> None:
    adapter = BtsT100SegmentAdapter()
    parts = []
    for period in PERIODS:
        paths = adapter.fetch(period, raw_cache_dir())
        raw = pd.read_csv(paths[0], usecols=list(SOURCE_COLUMNS))
        keep = raw[raw["ORIGIN"].isin(FIXTURE_IATAS)].copy()
        for _origin, group in keep.groupby("ORIGIN"):
            by_departures = group.sort_values("DEPARTURES_PERFORMED", ascending=False)
            parts.append(by_departures[by_departures["SEATS"] > 0].head(PER_ORIGIN_CAP))

    trimmed = pd.concat(parts, ignore_index=True).sort_values(["ORIGIN", "YEAR", "MONTH", "DEST"])
    missing = sorted(set(FIXTURE_IATAS) - set(trimmed["ORIGIN"]))
    if missing:
        raise SystemExit(f"missing fixture airports: {missing}")

    out = HERE / "dom_extra_months_subset.csv"
    trimmed.to_csv(out, index=False)
    print(f"wrote {out.name}: {len(trimmed)} rows, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
