"""P3 Market Quality derived-metric tests."""
from __future__ import annotations

import pandas as pd
import pytest

from airport_agent.data.derived import p3_market
from airport_agent.data.store import Store


def _seed_airport(store: Store, iata: str, lat: float = 0.0, lon: float = 0.0) -> None:
    store.con.execute(
        "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
        "commercial, source_id, vintage) VALUES (?, ?, 'x', 'x', 'XX', 'XXX', 'small', ?, ?, true, "
        "'ourairports', '2026-01-01')",
        [iata, iata, lat, lon],
    )
    # commercial_airports() (data/commercial.py) is EXISTS-based on traffic tables, not the
    # stored `commercial` column — give every seeded airport a qualifying enplanement row.
    store.con.execute(
        "INSERT INTO airport_year (iata, year, measure, value, source_id, vintage) VALUES (?, 2025, "
        "'enplanements', 1.0, 'bts_socrata', '2025-12')",
        [iata],
    )


class TestCarrierHhiAndTopShare:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        rows = [
            {"iata": "AAA", "dest": "X1", "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 500.0, "departures": 10, "seats": 1000, "passengers": 800,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"},
            {"iata": "AAA", "dest": "X2", "dest_name": "x", "period": "2026-04", "carrier": "C2",
             "distance_mi": 500.0, "departures": 10, "seats": 1000, "passengers": 200,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"},
        ]
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        return tmp_store

    def test_hhi_reflects_the_concentration(self, store: Store) -> None:
        df = p3_market.carrier_hhi(store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        # shares 0.8, 0.2 -> (0.64 + 0.04) * 10000 = 6800
        assert row["value"] == pytest.approx(6800.0)

    def test_top_carrier_share_is_the_max_share(self, store: Store) -> None:
        df = p3_market.top_carrier_share(store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(0.8)


class TestLonghaulDepShare:
    def test_long_and_short_routes(self, tmp_store: Store) -> None:
        _seed_airport(tmp_store, "AAA")
        rows = [
            {"iata": "AAA", "dest": "LONG", "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 2000.0, "departures": 10, "seats": 1000, "passengers": 800,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"},
            {"iata": "AAA", "dest": "SHORT", "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 300.0, "departures": 30, "seats": 1000, "passengers": 800,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"},
        ]
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        df = p3_market.longhaul_dep_share(tmp_store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(10 / 40)


class TestRouteCountNonstop:
    def test_counts_distinct_destinations_with_departures(self, tmp_store: Store) -> None:
        _seed_airport(tmp_store, "AAA")
        rows = [
            {"iata": "AAA", "dest": d, "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 300.0, "departures": 5, "seats": 100, "passengers": 80,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"}
            for d in ["X1", "X2", "X3"]
        ]
        # a zero-departure row must not count.
        rows.append(
            {"iata": "AAA", "dest": "X4", "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 300.0, "departures": 0, "seats": 0, "passengers": 0,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"}
        )
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        df = p3_market.route_count_nonstop(tmp_store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == 3


class TestCompetingSeats100mi:
    def test_only_counts_airports_within_100mi(self, tmp_store: Store) -> None:
        # Two airports ~50mi apart (near BOS/PVD real distance), one far away.
        _seed_airport(tmp_store, "AAA", lat=42.36, lon=-71.01)  # BOS-ish
        _seed_airport(tmp_store, "BBB", lat=41.73, lon=-71.43)  # PVD-ish, ~50mi
        _seed_airport(tmp_store, "CCC", lat=61.17, lon=-150.0)  # ANC-ish, far away
        for iata, seats in [("AAA", 1000), ("BBB", 500), ("CCC", 300)]:
            tmp_store.replace_rows(
                "routes_month",
                pd.DataFrame(
                    [{"iata": iata, "dest": "X", "dest_name": "x", "period": "2026-04", "carrier": "C1",
                      "distance_mi": 300.0, "departures": 5, "seats": seats, "passengers": 400,
                      "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
                      "source_id": "bts_t100", "vintage": "2026-04"}]
                ),
                {"iata": iata},
            )
        df = p3_market.competing_seats_100mi(tmp_store.con, "12m", 2026, "2026-04")
        aaa = df[df["iata"] == "AAA"].iloc[0]
        assert aaa["value"] == pytest.approx(500.0)  # only BBB, not the far-away CCC
