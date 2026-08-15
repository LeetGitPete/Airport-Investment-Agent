"""Tests for `airport_agent.data.adapters.bts_socrata` — normalize on a real API subset."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_socrata import (
    AIRPORT_MONTH_COLUMNS,
    AIRPORT_YEAR_COLUMNS,
    MONTH_MEASURES,
    SOCRATA_URL,
    YEAR_MEASURES,
    BtsSocrataAdapter,
    _select_clause,
    _where_clause,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_IATAS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "bts_socrata" / "sample.json"


@pytest.fixture
def normalized(fixture_path: Path) -> dict[str, pd.DataFrame]:
    return BtsSocrataAdapter().normalize([fixture_path])


@pytest.fixture
def month(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["airport_month"]


@pytest.fixture
def year(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["airport_year"]


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["bts_socrata"] is BtsSocrataAdapter

    def test_kind_is_bulk(self) -> None:
        assert BtsSocrataAdapter.kind == "bulk"


class TestWhereClause:
    def test_no_period_is_full_history(self) -> None:
        assert _where_clause(None) == "year >= '2014'"

    def test_year_only(self) -> None:
        assert _where_clause(Period(year=2025)) == "year='2025'"

    def test_year_and_month(self) -> None:
        assert _where_clause(Period(year=2025, month=3)) == "year='2025' AND date_extract_m(reporting_month)=3"

    def test_select_clause_casts_every_numeric_field(self) -> None:
        clause = _select_clause()
        assert "total_passengers::number as total_passengers" in clause
        assert "origin_airport_code" in clause


class TestNormalizeShape:
    def test_returns_both_tables(self, fixture_path: Path) -> None:
        assert set(BtsSocrataAdapter().normalize([fixture_path])) == {"airport_month", "airport_year"}

    def test_month_columns_match_store_schema(self, month: pd.DataFrame) -> None:
        assert list(month.columns) == list(AIRPORT_MONTH_COLUMNS)

    def test_year_columns_match_store_schema(self, year: pd.DataFrame) -> None:
        assert list(year.columns) == list(AIRPORT_YEAR_COLUMNS)

    def test_covers_every_fixture_airport(self, month: pd.DataFrame) -> None:
        assert FIXTURE_IATAS <= set(month["iata"])

    def test_month_measures_are_the_declared_set(self, month: pd.DataFrame) -> None:
        assert set(month["measure"]) <= set(MONTH_MEASURES)

    def test_year_measures_are_the_declared_set(self, year: pd.DataFrame) -> None:
        assert set(year["measure"]) == set(YEAR_MEASURES)

    def test_provenance_on_every_row(self, month: pd.DataFrame, year: pd.DataFrame) -> None:
        assert (month["source_id"] == "bts_socrata").all()
        assert (year["source_id"] == "bts_socrata").all()
        assert month["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()
        assert year["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()


class TestValues:
    def test_bos_2025_has_12_months(self, month: pd.DataFrame) -> None:
        bos_2025 = month[(month["iata"] == "BOS") & (month["period"].str.startswith("2025"))]
        assert bos_2025["period"].nunique() == 12

    def test_intl_out_never_exceeds_total_passengers(self, month: pd.DataFrame) -> None:
        wide = month.pivot_table(index=["iata", "period"], columns="measure", values="value")
        both = wide.dropna(subset=["intl_out_passengers", "total_passengers"])
        assert (both["intl_out_passengers"] <= both["total_passengers"]).all()

    def test_load_factor_matches_passengers_over_seats(self, month: pd.DataFrame) -> None:
        wide = month.pivot_table(index=["iata", "period"], columns="measure", values="value")
        row = wide.loc[("BOS", "2025-01")]
        assert row["load_factor"] == pytest.approx(row["total_passengers"] / row["total_seats"])

    def test_pwm_international_is_rare_but_present(self, month: pd.DataFrame) -> None:
        # PWM is a small hub with only occasional charter/seasonal international departures
        # (verified: 18 of 52 fixture months have any outbound_international_1 at all) —
        # most months carry no `intl_out_passengers` row (the field is absent, not zero).
        pwm = month[month["iata"] == "PWM"]
        n_months = pwm["period"].nunique()
        n_intl_months = pwm[pwm["measure"] == "intl_out_passengers"]["period"].nunique()
        assert 0 < n_intl_months < n_months

    def test_jfk_has_international_measures(self, month: pd.DataFrame) -> None:
        jfk = month[month["iata"] == "JFK"]
        assert "intl_out_passengers" in set(jfk["measure"])

    def test_year_rollup_only_for_complete_years(self, year: pd.DataFrame) -> None:
        # The fixture spans 2022-01..2026-04: 2026 is partial and must be absent.
        assert 2026 not in set(year.loc[year["iata"] == "BOS", "year"])
        assert 2025 in set(year.loc[year["iata"] == "BOS", "year"])

    def test_year_enplanements_matches_month_sum(self, month: pd.DataFrame, year: pd.DataFrame) -> None:
        bos_2025_pax = month[
            (month["iata"] == "BOS") & (month["period"].str.startswith("2025")) & (month["measure"] == "total_passengers")
        ]["value"].sum()
        bos_2025_year = year[(year["iata"] == "BOS") & (year["year"] == 2025) & (year["measure"] == "enplanements")][
            "value"
        ].iloc[0]
        assert bos_2025_year == pytest.approx(bos_2025_pax)


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_path: Path) -> None:
        adapter = BtsSocrataAdapter()
        adapter.normalize([fixture_path])
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "bts_socrata"
        assert vintage.url == SOCRATA_URL
        assert vintage.period_start == "2022-01"


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_downloads_and_normalizes_one_month(self) -> None:
        adapter = BtsSocrataAdapter()
        paths = adapter.fetch(Period(year=2025, month=1), raw_cache_dir())
        month = adapter.normalize(paths)["airport_month"]
        assert len(month) > 100
        bos = month[(month["iata"] == "BOS") & (month["measure"] == "total_passengers")]
        assert bos["value"].iloc[0] > 500_000
