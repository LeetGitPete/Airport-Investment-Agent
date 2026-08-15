"""P1 Demand Pressure derived-metric tests: synthetic-data unit tests for logic that the
fixture-built test snapshot alone can't exercise (seats_per_dep_trend needs a genuine 5-year
gap; spill_proxy needs >=6 months per route), plus a taxi-out cross-check against `taxi_out_p80_min`
lives in test_derived_p2.py."""
from __future__ import annotations

import pandas as pd
import pytest

from airport_agent.data.derived import p1_demand
from airport_agent.data.store import Store


def _seed_airport(store: Store, iata: str, faa_locid: str | None = None) -> None:
    store.con.execute(
        "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
        "commercial, source_id, vintage) VALUES (?, ?, 'x', 'x', 'XX', 'XXX', 'small', 0, 0, false, "
        "'ourairports', '2026-01-01')",
        [iata, faa_locid or iata],
    )


class TestSeatsPerDepTrend:
    """Proof the function is correct given a genuine 5-year gap (the shared test snapshot's
    Socrata fixture only spans ~4 years — see test_derived_registry.py::Test5yDeclaredCoverage)."""

    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        rows = [
            {"iata": "AAA", "year": 2020, "measure": "seats", "value": 100_000.0,
             "source_id": "bts_socrata", "vintage": "2020-12"},
            {"iata": "AAA", "year": 2020, "measure": "departures", "value": 1000.0,
             "source_id": "bts_socrata", "vintage": "2020-12"},
            {"iata": "AAA", "year": 2025, "measure": "seats", "value": 132_000.0,
             "source_id": "bts_socrata", "vintage": "2025-12"},
            {"iata": "AAA", "year": 2025, "measure": "departures", "value": 1000.0,
             "source_id": "bts_socrata", "vintage": "2025-12"},
        ]
        tmp_store.replace_rows("airport_year", pd.DataFrame(rows), None)
        return tmp_store

    def test_upgauging_ratio(self, store: Store) -> None:
        df = p1_demand.seats_per_dep_trend(store.con, "5y", 2025, "2025-12")
        row = df[df["iata"] == "AAA"].iloc[0]
        # (132000/1000) / (100000/1000) - 1 = 0.32
        assert row["value"] == pytest.approx(0.32)
        assert row["source_id"] == "bts_socrata"

    def test_absent_without_the_older_year(self, store: Store) -> None:
        df = p1_demand.seats_per_dep_trend(store.con, "5y", 2024, "2025-12")  # needs 2019, absent
        assert df.empty


class TestSpillProxy:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        rows = []
        # Route AAA->ZZZ, one carrier, 8 months in-window with varying load factor.
        lfs = [0.6, 0.7, 0.8, 0.9, 0.6, 0.7, 0.8, 0.9]
        for i, lf in enumerate(lfs):
            period = f"2025-{i + 1:02d}"
            rows.append(
                {"iata": "AAA", "dest": "ZZZ", "dest_name": "Z", "period": period, "carrier": "XX",
                 "distance_mi": 500.0, "departures": 30, "seats": 3000, "passengers": int(3000 * lf),
                 "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
                 "source_id": "bts_t100", "vintage": "2025-08"}
            )
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        return tmp_store

    def test_nonzero_cv_for_a_route_with_varying_load_factor(self, store: Store) -> None:
        df = p1_demand.spill_proxy(store.con, "12m", 2025, "2025-08")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] > 0
        assert row["source_id"] == "bts_t100"

    def test_route_below_six_months_is_excluded(self, tmp_store: Store) -> None:
        _seed_airport(tmp_store, "BBB")
        rows = [
            {"iata": "BBB", "dest": "ZZZ", "dest_name": "Z", "period": f"2025-{i:02d}", "carrier": "XX",
             "distance_mi": 500.0, "departures": 30, "seats": 3000, "passengers": 2000,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2025-08"}
            for i in range(1, 4)  # only 3 months
        ]
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        df = p1_demand.spill_proxy(tmp_store.con, "12m", 2025, "2025-08")
        assert df.empty


class TestTafVsActualGap:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        tmp_store.replace_rows(
            "airport_year",
            pd.DataFrame([{"iata": "AAA", "year": 2026, "measure": "enplanements", "value": 900_000.0,
                            "source_id": "bts_socrata", "vintage": "2026-04"}]),
            None,
        )
        tmp_store.replace_rows(
            "taf_forecast",
            pd.DataFrame([{"faa_locid": "AAA", "year": 2026, "enplanements": 990_000.0, "ops_total": 5000.0,
                            "source_id": "faa_taf", "vintage": "2026-01"}]),
            None,
        )
        return tmp_store

    def test_gap_is_forecast_over_actual(self, store: Store) -> None:
        df = p1_demand.taf_vs_actual_gap(store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(990_000.0 / 900_000.0)


class TestEnplCagr:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        tmp_store.replace_rows(
            "airport_year",
            pd.DataFrame(
                [
                    {"iata": "AAA", "year": 2022, "measure": "enplanements", "value": 100_000.0,
                     "source_id": "bts_socrata", "vintage": "2022-12"},
                    {"iata": "AAA", "year": 2025, "measure": "enplanements", "value": 133_100.0,
                     "source_id": "bts_socrata", "vintage": "2025-12"},
                ]
            ),
            None,
        )
        return tmp_store

    def test_3y_cagr(self, store: Store) -> None:
        df = p1_demand.enpl_cagr_3y(store.con, "3y", 2025, "2025-12")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(0.10, abs=1e-3)  # 1.1^3 = 1.331
