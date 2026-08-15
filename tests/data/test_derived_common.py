"""Unit tests for `derived/common.py` — the window/CAGR/annual-enplanements helpers every
derived metric function is built on."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from airport_agent.data.derived import common
from airport_agent.data.store import Store


class TestWindowMonths:
    def test_12m_is_the_trailing_year(self):
        assert common.window_months("12m", "2026-04") == ("2025-05", "2026-04")

    def test_3y_is_36_months(self):
        start, end = common.window_months("3y", "2026-04")
        assert end == "2026-04"
        assert start == "2023-05"

    def test_5y_is_60_months(self):
        start, end = common.window_months("5y", "2026-04")
        assert start == "2021-05"

    def test_10y_is_120_months(self):
        start, end = common.window_months("10y", "2026-04")
        assert start == "2016-05"

    def test_crosses_a_year_boundary(self):
        assert common.window_months("12m", "2026-01") == ("2025-02", "2026-01")


class TestPeriodForRefYear:
    def test_past_year_is_december(self):
        assert common.period_for_ref_year(2024, "2026-04") == "2024-12"

    def test_current_year_is_latest_period(self):
        assert common.period_for_ref_year(2026, "2026-04") == "2026-04"

    def test_future_ref_year_also_uses_latest_period(self):
        # ref_year >= latest_year: never invent a period beyond what's actually loaded.
        assert common.period_for_ref_year(2027, "2026-04") == "2026-04"


class TestCagr:
    def test_growth(self):
        assert common.cagr(121.0, 100.0, 2) == pytest.approx(0.1)

    def test_decline(self):
        assert common.cagr(81.0, 100.0, 2) == pytest.approx(-0.1)

    def test_none_when_old_is_missing(self):
        assert common.cagr(100.0, None, 3) is None

    def test_none_when_new_is_missing(self):
        assert common.cagr(None, 100.0, 3) is None

    def test_none_when_old_is_zero_or_negative(self):
        assert common.cagr(100.0, 0.0, 3) is None
        assert common.cagr(100.0, -5.0, 3) is None

    def test_none_when_new_is_nan(self):
        assert common.cagr(float("nan"), 100.0, 3) is None


class TestQualityJson:
    def test_empty_is_empty_list(self):
        assert common.quality_json(None) == "[]"
        assert common.quality_json([]) == "[]"

    def test_round_trips(self):
        flags = [{"code": "partial_year", "message": "x"}]
        assert json.loads(common.quality_json(flags)) == flags


class TestPartialWindowFlag:
    def test_no_flag_when_coverage_meets_nominal(self):
        assert common.partial_window_flag({"BOS": 12}, "BOS", 12) == []

    def test_flag_when_coverage_is_short(self):
        flags = common.partial_window_flag({"BOS": 3}, "BOS", 12)
        assert len(flags) == 1
        assert flags[0]["code"] == "partial_window"
        assert "3 of 12" in flags[0]["message"]

    def test_missing_iata_treated_as_zero_coverage(self):
        flags = common.partial_window_flag({}, "ZZZ", 12)
        assert flags[0]["code"] == "partial_window"


@pytest.fixture
def enpl_store(tmp_store: Store) -> Store:
    airports = pd.DataFrame(
        [
            {"iata": "AAA", "icao": None, "faa_locid": "AAA", "name": "A", "city": "A", "state": "AA",
             "faa_region": "AAA", "hub_size": "small", "lat": 0.0, "lon": 0.0, "cbsa_code": None,
             "cbsa_name": None, "commercial": False, "source_id": "ourairports", "vintage": "2026-01-01"},
        ]
    )
    # BBB has no Socrata data at all for 2024, only a TAF actual.
    airports = pd.concat(
        [
            airports,
            pd.DataFrame(
                [{"iata": "BBB", "icao": None, "faa_locid": "BBB", "name": "B", "city": "B", "state": "BB",
                  "faa_region": "BBB", "hub_size": "small", "lat": 0.0, "lon": 0.0, "cbsa_code": None,
                  "cbsa_name": None, "commercial": False, "source_id": "ourairports", "vintage": "2026-01-01"}]
            ),
        ],
        ignore_index=True,
    )
    tmp_store.replace_rows("airports", airports, None)
    # AAA: a complete Socrata year for 2025, no 2026 Socrata row (so 2026 falls back to
    # trailing-12m), and no TAF at all.
    airport_year = pd.DataFrame(
        [{"iata": "AAA", "year": 2025, "measure": "enplanements", "value": 1_200_000.0,
          "source_id": "bts_socrata", "vintage": "2025-12-31"}]
    )
    tmp_store.replace_rows("airport_year", airport_year, None)
    periods = [f"2025-{m:02d}" for m in range(5, 13)] + [f"2026-{m:02d}" for m in range(1, 5)]
    months = [
        {"iata": "AAA", "period": p, "measure": "total_passengers",
         "value": 100_000.0, "source_id": "bts_socrata", "vintage": "2026-04-30"}
        for p in periods
    ]
    tmp_store.replace_rows("airport_month", pd.DataFrame(months), None)
    taf = pd.DataFrame(
        [{"faa_locid": "BBB", "year": 2024, "enplanements": 500_000.0, "ops_total": 10_000.0,
          "source_id": "faa_taf", "vintage": "2026-01-01"}]
    )
    tmp_store.replace_rows("taf_history", taf, None)
    return tmp_store


class TestAnnualEnplanements:
    def test_complete_socrata_year_is_used_directly(self, enpl_store: Store):
        df = common.annual_enplanements(enpl_store.con, 2025, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(1_200_000.0)
        assert row["source_id"] == "bts_socrata"
        assert row["quality_code"] is None

    def test_current_incomplete_year_falls_back_to_trailing_12m(self, enpl_store: Store):
        df = common.annual_enplanements(enpl_store.con, 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(1_200_000.0)  # 12 months x 100k
        assert row["quality_code"] == "partial_year"

    def test_taf_actual_fallback_when_socrata_has_no_complete_year(self, enpl_store: Store):
        df = common.annual_enplanements(enpl_store.con, 2024, "2026-04")
        row = df[df["iata"] == "BBB"].iloc[0]
        assert row["value"] == pytest.approx(500_000.0)
        assert row["source_id"] == "faa_taf"
        assert row["quality_code"] == "taf_actual"

    def test_zero_or_negative_values_are_dropped(self, enpl_store: Store):
        df = common.annual_enplanements(enpl_store.con, 1999, "2026-04")
        assert df.empty
