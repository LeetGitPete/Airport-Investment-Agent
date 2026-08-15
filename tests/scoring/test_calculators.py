from __future__ import annotations

import pytest

from airport_agent.contracts import RouteRow, RouteTable
from airport_agent.scoring.calculators import BANDS, distance_bands, long_haul_share
from tests.fakes import FakeDataService


def _rt(rows, truncated=False):
    return RouteTable(iata="XXX", period_start="2025-05", period_end="2026-04", source_id="bts_t100",
                      vintage="2026-04", rows=rows, truncated=truncated)


def _row(mi, deps, seats, freight):
    return RouteRow(dest="D", dest_name=None, distance_mi=mi, departures=deps, seats=seats, passengers=seats,
                    freight_lb=freight, is_international=False)


def test_bands_definition_matches_design_02():
    assert [b[0] for b in BANDS] == ["short", "medium", "long", "ultra"]
    assert BANDS[1][1:] == (500, 1500) and BANDS[2][1:] == (1500, 3000)


def test_passenger_bands_share_departures_with_seats():
    rt = _rt([_row(400, 10, 100, 0), _row(1000, 20, 100, 0), _row(2000, 30, 100, 0), _row(5000, 40, 0, 1e6)])
    b = distance_bands(rt, freight=False)
    assert b == {"short": pytest.approx(10 / 60), "medium": pytest.approx(20 / 60), "long": pytest.approx(30 / 60),
                 "ultra": 0.0}


def test_freight_bands_share_freight_lb():
    rt = _rt([_row(400, 10, 100, 100.0), _row(5000, 1, 0, 900.0)])
    assert distance_bands(rt, freight=True) == {"short": 0.1, "medium": 0.0, "long": 0.0, "ultra": 0.9}


def test_bands_boundaries_lower_inclusive():
    rt = _rt([_row(500, 1, 10, 0), _row(1500, 1, 10, 0), _row(3000, 1, 10, 0)])
    assert distance_bands(rt) == {"short": 0.0, "medium": pytest.approx(1 / 3), "long": pytest.approx(1 / 3),
                                  "ultra": pytest.approx(1 / 3)}


def test_no_traffic_gives_zeros_and_none_metric():
    assert distance_bands(_rt([])) == {"short": 0.0, "medium": 0.0, "long": 0.0, "ultra": 0.0}
    assert long_haul_share(_rt([])).value is None


def test_long_haul_share_metric_carries_provenance_and_convention_flag():
    rt = _rt([_row(1000, 50, 100, 0), _row(2000, 50, 100, 0)], truncated=True)
    m = long_haul_share(rt, threshold_mi=1500, horizon="12m")
    assert m.id == "longhaul_dep_share" and m.unit == "pct" and m.horizon == "12m"
    assert m.value == pytest.approx(0.5)
    assert m.source_id == "bts_t100" and m.vintage == "2026-04"
    assert {q.code for q in m.quality} == {"convention", "truncated_routes"}


def test_threshold_is_adjustable():
    rt = _rt([_row(1000, 50, 100, 0), _row(2000, 50, 100, 0)])
    assert long_haul_share(rt, threshold_mi=900).value == pytest.approx(1.0)


def test_golden_anc_freight_long_haul_far_exceeds_passenger():
    rt = FakeDataService().get_routes("ANC", top_n=100)
    pax = long_haul_share(rt, freight=False).value
    frt = long_haul_share(rt, freight=True).value
    assert frt > 0.9 and pax < 0.3 and frt > pax
