"""Tests for `airport_agent.data.adapters.bts_otp` — normalize on a real PREZIP subset."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_otp import (
    ARR_MEASURES,
    DEP_MEASURES,
    URL_TEMPLATE,
    BtsOtpAdapter,
    _hour_of,
    _url,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_IATAS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "bts_otp" / "otp_2026_06_subset.csv"


@pytest.fixture
def raw(fixture_path: Path) -> pd.DataFrame:
    return pd.read_csv(fixture_path)


@pytest.fixture
def normalized(fixture_path: Path) -> dict[str, pd.DataFrame]:
    return BtsOtpAdapter().normalize([fixture_path])


@pytest.fixture
def month(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["airport_month"]


@pytest.fixture
def taxi_hist(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["otp_taxi_hist"]


@pytest.fixture
def peak(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["otp_peak"]


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["bts_otp"] is BtsOtpAdapter

    def test_kind_is_bulk(self) -> None:
        assert BtsOtpAdapter.kind == "bulk"


class TestUrl:
    def test_builds_the_prezip_url(self) -> None:
        assert _url(Period(year=2026, month=6)) == (
            "https://transtats.bts.gov/PREZIP/"
            "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2026_6.zip"
        )

    def test_year_only_period_raises(self) -> None:
        with pytest.raises(ValueError, match="specific month"):
            _url(Period(year=2026))


class TestFetchRequiresPeriod:
    def test_none_period_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="explicit period"):
            BtsOtpAdapter().fetch(None, tmp_path)


class TestHourOf:
    def test_hhmm_to_hour(self) -> None:
        hours = _hour_of(pd.Series([1, 1649, 2359, 100]))
        assert list(hours) == [0, 16, 23, 1]


class TestNormalizeShape:
    def test_returns_three_tables(self, fixture_path: Path) -> None:
        assert set(BtsOtpAdapter().normalize([fixture_path])) == {
            "airport_month",
            "otp_taxi_hist",
            "otp_peak",
        }

    def test_month_measures_are_the_declared_set(self, month: pd.DataFrame) -> None:
        assert set(month["measure"]) <= set(DEP_MEASURES) | set(ARR_MEASURES)

    def test_covers_every_fixture_airport(self, month: pd.DataFrame) -> None:
        assert FIXTURE_IATAS <= set(month["iata"])

    def test_provenance_on_every_row(self, month: pd.DataFrame, taxi_hist: pd.DataFrame, peak: pd.DataFrame) -> None:
        for df in (month, taxi_hist, peak):
            assert (df["source_id"] == "bts_otp").all()
            assert df["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()


class TestValues:
    def test_sfo_avg_dep_delay_matches_the_source_rows(self, raw: pd.DataFrame, month: pd.DataFrame) -> None:
        sfo_dep = raw[(raw["Origin"] == "SFO") & (raw["Cancelled"] == 0)]
        expected_sum = sfo_dep["DepDelayMinutes"].sum()
        expected_count = len(sfo_dep)
        wide = month[month["iata"] == "SFO"].set_index("measure")["value"]
        assert wide["dep_delay_min_sum"] == pytest.approx(expected_sum)
        assert wide["dep_count"] == expected_count
        assert wide["dep_delay_min_sum"] / wide["dep_count"] == pytest.approx(expected_sum / expected_count)

    def test_cancelled_dep_matches_the_source_rows(self, raw: pd.DataFrame, month: pd.DataFrame) -> None:
        expected = int((raw[raw["Origin"] == "SFO"]["Cancelled"] == 1).sum())
        wide = month[month["iata"] == "SFO"].set_index("measure")["value"]
        assert wide["cancelled_dep"] == expected

    def test_histogram_sums_to_dep_count_with_taxiout(self, raw: pd.DataFrame, taxi_hist: pd.DataFrame, month: pd.DataFrame) -> None:
        for iata in ["BOS", "SFO", "ANC"]:
            expected = raw[(raw["Origin"] == iata) & raw["TaxiOut"].notna()].shape[0]
            actual = taxi_hist[taxi_hist["iata"] == iata]["n"].sum()
            assert actual == expected

    def test_taxi_bucket_is_capped_at_180(self, taxi_hist: pd.DataFrame) -> None:
        assert taxi_hist["minute_bucket"].max() <= 180

    def test_peak_p95_never_exceeds_max(self, peak: pd.DataFrame) -> None:
        assert (peak["p95_hourly_ops"] <= peak["max_hourly_ops"]).all()

    def test_peak_values_are_nonnegative(self, peak: pd.DataFrame) -> None:
        assert (peak["p95_hourly_ops"] >= 0).all()
        assert (peak["max_hourly_ops"] >= 0).all()

    def test_arr_late15_never_exceeds_arrivals(self, month: pd.DataFrame) -> None:
        wide = month.pivot_table(index="iata", columns="measure", values="value")
        both = wide.dropna(subset=["arr_late15", "arrivals"])
        assert (both["arr_late15"] <= both["arrivals"]).all()


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_path: Path) -> None:
        adapter = BtsOtpAdapter()
        adapter.normalize([fixture_path])
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "bts_otp"
        assert vintage.url == URL_TEMPLATE
        assert (vintage.period_start, vintage.period_end) == ("2026-06", "2026-06")


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_and_normalize_one_month(self) -> None:
        adapter = BtsOtpAdapter()
        paths = adapter.fetch(Period(year=2026, month=6), raw_cache_dir())
        out = adapter.normalize(paths)
        assert len(out["airport_month"]) > 1000
        assert "BOS" in set(out["airport_month"]["iata"])
