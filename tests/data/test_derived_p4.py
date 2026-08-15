"""P4 Economic Base derived-metric tests."""
from __future__ import annotations

import pandas as pd
import pytest

from airport_agent.data.derived import p4_economy
from airport_agent.data.store import Store


class TestCbsaPopulation:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        tmp_store.replace_rows(
            "catchment",
            pd.DataFrame(
                [
                    {"iata": "AAA", "cbsa_code": "1", "cbsa_name": "A Metro", "year": 2020, "population": 1_000_000.0,
                     "gdp_real_usd": None, "source_id": "census_cbsa", "vintage": "2026-08"},
                    {"iata": "AAA", "cbsa_code": "1", "cbsa_name": "A Metro", "year": 2023, "population": 1_100_000.0,
                     "gdp_real_usd": None, "source_id": "census_cbsa", "vintage": "2026-08"},
                ]
            ),
            None,
        )
        return tmp_store

    def test_uses_latest_year_at_or_before_ref_year(self, store: Store) -> None:
        df = p4_economy.cbsa_population(store.con, "12m", 2025, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(1_100_000.0)  # 2023 is latest <= 2025

    def test_older_ref_year_uses_older_population(self, store: Store) -> None:
        df = p4_economy.cbsa_population(store.con, "12m", 2021, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(1_000_000.0)

    def test_absent_before_any_population_year(self, store: Store) -> None:
        df = p4_economy.cbsa_population(store.con, "12m", 2019, "2026-04")
        assert df.empty

    def test_carries_the_cbsa_proxy_flag(self, store: Store) -> None:
        import json

        df = p4_economy.cbsa_population(store.con, "12m", 2025, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        codes = {f["code"] for f in json.loads(row["quality_json"])}
        assert "cbsa_proxy" in codes


class TestCbsaPopCagr5y:
    def test_exact_years_required(self, tmp_store: Store) -> None:
        tmp_store.replace_rows(
            "catchment",
            pd.DataFrame(
                [
                    {"iata": "AAA", "cbsa_code": "1", "cbsa_name": "A", "year": 2020, "population": 1_000_000.0,
                     "gdp_real_usd": None, "source_id": "census_cbsa", "vintage": "2026-08"},
                    {"iata": "AAA", "cbsa_code": "1", "cbsa_name": "A", "year": 2025, "population": 1_100_000.0,
                     "gdp_real_usd": None, "source_id": "census_cbsa", "vintage": "2026-08"},
                ]
            ),
            None,
        )
        df = p4_economy.cbsa_pop_cagr_5y(tmp_store.con, "5y", 2025, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx((1_100_000.0 / 1_000_000.0) ** (1 / 5) - 1)

    def test_absent_without_both_endpoints(self, tmp_store: Store) -> None:
        tmp_store.replace_rows(
            "catchment",
            pd.DataFrame(
                [{"iata": "AAA", "cbsa_code": "1", "cbsa_name": "A", "year": 2025, "population": 1_100_000.0,
                  "gdp_real_usd": None, "source_id": "census_cbsa", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p4_economy.cbsa_pop_cagr_5y(tmp_store.con, "5y", 2025, "2026-04")
        assert df.empty
