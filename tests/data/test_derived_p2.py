"""P2 Congestion & Physical Constraint derived-metric tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.data.adapters.bts_otp import BtsOtpAdapter
from airport_agent.data.derived import p2_congestion
from airport_agent.data.store import Store


def _seed_airport(store: Store, iata: str, faa_locid: str | None = None) -> None:
    store.con.execute(
        "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
        "commercial, source_id, vintage) VALUES (?, ?, 'x', 'x', 'XX', 'XXX', 'small', 0, 0, false, "
        "'ourairports', '2026-01-01')",
        [iata, faa_locid or iata],
    )


class TestTaxiOutP80MatchesPandasQuantile:
    def test_bos_within_one_minute_of_a_direct_quantile(self, tmp_store: Store, fixtures_dir: Path) -> None:
        path = fixtures_dir / "bts_otp" / "otp_2026_06_subset.csv"
        tables = BtsOtpAdapter().normalize([path])
        tmp_store.replace_rows("airport_month", tables["airport_month"], None)
        tmp_store.replace_rows("otp_taxi_hist", tables["otp_taxi_hist"], None)
        tmp_store.replace_rows("otp_peak", tables["otp_peak"], None)

        raw = pd.read_csv(path)
        expected = raw.loc[(raw["Origin"] == "BOS") & raw["TaxiOut"].notna(), "TaxiOut"].quantile(0.80)

        df = p2_congestion.taxi_out_p80_min(tmp_store.con, "12m", 2026, "2026-06")
        got = df.loc[df["iata"] == "BOS", "value"].iloc[0]
        assert got == pytest.approx(expected, abs=1.0)


class TestOtpAnchoredOnItsOwnLatestPeriod:
    """OTP-sourced 12m functions must anchor on OTP's own latest month, not Socrata's — the
    two sources are refreshed independently (see p2_congestion._otp_latest_period)."""

    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        # OTP's own latest month is 2026-06, one month after any Socrata latest_period we pass.
        rows = [
            {"iata": "AAA", "period": "2026-06", "measure": "arrivals", "value": 100.0,
             "source_id": "bts_otp", "vintage": "2026-06"},
            {"iata": "AAA", "period": "2026-06", "measure": "arr_late15", "value": 20.0,
             "source_id": "bts_otp", "vintage": "2026-06"},
        ]
        tmp_store.replace_rows("airport_month", pd.DataFrame(rows), None)
        return tmp_store

    def test_uses_otp_own_latest_month_not_the_socrata_anchor(self, store: Store) -> None:
        # latest_period passed in is Socrata's (2026-04); OTP's own data is a month later.
        df = p2_congestion.pct_arr_delay_gt15(store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(0.20)
        assert row["period_end"] == "2026-06"

    def test_no_row_for_a_ref_year_otp_has_no_data_in(self, store: Store) -> None:
        df = p2_congestion.pct_arr_delay_gt15(store.con, "12m", 2025, "2026-04")
        assert df.empty

    def test_3y_horizon_is_always_empty(self, store: Store) -> None:
        # RESCOPE 2026-08-16: OTP ingests 12 trailing months only.
        df = p2_congestion.pct_arr_delay_gt15(store.con, "3y", 2026, "2026-04")
        assert df.empty


class TestOpsPerRunway:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        _seed_airport(tmp_store, "AAA")
        tmp_store.replace_rows(
            "taf_history",
            pd.DataFrame([{"faa_locid": "AAA", "year": 2024, "enplanements": 1e6, "ops_total": 60_000.0,
                            "source_id": "faa_taf", "vintage": "2026-01"}]),
            None,
        )
        tmp_store.replace_rows(
            "runways",
            pd.DataFrame(
                [
                    {"faa_locid": "AAA", "runway_id": "01", "length_ft": 10000, "width_ft": 150,
                     "surface": "ASP", "closed": False, "source_id": "ourairports", "vintage": "2026-01"},
                    {"faa_locid": "AAA", "runway_id": "02", "length_ft": 8000, "width_ft": 150,
                     "surface": "ASP", "closed": False, "source_id": "ourairports", "vintage": "2026-01"},
                    {"faa_locid": "AAA", "runway_id": "03", "length_ft": 5000, "width_ft": 100,
                     "surface": "ASP", "closed": True, "source_id": "ourairports", "vintage": "2026-01"},
                ]
            ),
            None,
        )
        return tmp_store

    def test_excludes_closed_runways(self, store: Store) -> None:
        df = p2_congestion.ops_per_runway(store.con, "12m", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(30_000.0)  # 60000 / 2 open runways
