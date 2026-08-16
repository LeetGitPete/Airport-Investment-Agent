"""Rebuild the committed BTS Socrata fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/bts_socrata/make_fixture.py

Queries the real Socrata endpoint (same `$select`/casts the adapter uses) filtered
to the 15 fixture airports and `year >= 2022 OR year = 2020`, and writes the
single-page JSON response next to this file. Full history (2014+) for all 15
airports is ~522 KB — over the fixture budget — so this subset trims to the last
~4.3 years (2022-2026) plus one extra complete year (2020).

The 2020 year is included because the frozen
`tests/contracts/test_data_service_contract.py::test_feature_matrix_conforms_to_registry`
requires `seats_per_dep_trend` (a genuine 5-years-ago comparison, tier A, not in
`ATTEMPT_IDS`) to be non-None at the 5y horizon for BOS/SFO/ANC — the original
2022-2026-only subset has no year 5 years before the fixture's latest complete
year (2025), so `seats_per_dep_trend` was always empty in the test snapshot.
2020 is real, unedited API data, not invented. Rows are copied verbatim from the API.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from airport_agent.data.adapters.bts_socrata import SOCRATA_URL, _select_clause

HERE = Path(__file__).resolve().parent

FIXTURE_IATAS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]


def main() -> None:
    codes = ",".join(f"'{code}'" for code in FIXTURE_IATAS)
    where = f"origin_airport_code in({codes}) AND (year >= '2022' OR year = '2020')"
    params = {
        "$select": _select_clause(),
        "$where": where,
        "$order": "origin_airport_code,reporting_month",
        "$limit": "5000",
    }
    url = httpx.URL(SOCRATA_URL, params=params)
    response = httpx.get(url, timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    out = HERE / "sample.json"
    out.write_bytes(response.content)
    print(f"wrote {out.name}: {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
