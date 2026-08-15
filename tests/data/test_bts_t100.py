"""Tests for `airport_agent.data.adapters.bts_t100` — normalize on a real form-download subset."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.base import Period
from airport_agent.data.adapters.bts_t100 import (
    FORM_URL,
    ROUTES_MONTH_COLUMNS,
    BtsT100SegmentAdapter,
    _scrape_hidden_fields,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_IATAS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "bts_t100" / "dom_2026_04_subset.csv"


@pytest.fixture
def routes(fixture_path: Path) -> pd.DataFrame:
    return BtsT100SegmentAdapter().normalize([fixture_path])["routes_month"]


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["bts_t100"] is BtsT100SegmentAdapter

    def test_kind_is_bulk(self) -> None:
        assert BtsT100SegmentAdapter.kind == "bulk"


class TestFetchRequiresPeriod:
    def test_none_period_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="explicit period"):
            BtsT100SegmentAdapter().fetch(None, tmp_path)


class TestScrapeHiddenFields:
    def test_extracts_the_three_fields(self) -> None:
        html = (
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="abc123" />'
            '<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="XYZ" />'
            '<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="def456" />'
        )
        fields = _scrape_hidden_fields(html)
        assert fields == {
            "__VIEWSTATE": "abc123",
            "__VIEWSTATEGENERATOR": "XYZ",
            "__EVENTVALIDATION": "def456",
        }

    def test_missing_field_raises(self) -> None:
        with pytest.raises(ValueError, match="missing expected hidden field"):
            _scrape_hidden_fields("<html>no hidden fields here</html>")


class TestNormalizeShape:
    def test_returns_the_routes_month_table(self, fixture_path: Path) -> None:
        assert set(BtsT100SegmentAdapter().normalize([fixture_path])) == {"routes_month"}

    def test_columns_match_store_schema(self, routes: pd.DataFrame) -> None:
        assert list(routes.columns) == list(ROUTES_MONTH_COLUMNS)

    def test_covers_every_fixture_airport(self, routes: pd.DataFrame) -> None:
        assert FIXTURE_IATAS <= set(routes["iata"])

    def test_every_row_is_domestic(self, routes: pd.DataFrame) -> None:
        assert (routes["is_international"] == False).all()  # noqa: E712

    def test_provenance_on_every_row(self, routes: pd.DataFrame) -> None:
        assert (routes["source_id"] == "bts_t100").all()
        assert routes["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()

    def test_period_is_year_month(self, routes: pd.DataFrame) -> None:
        assert set(routes["period"]) == {"2026-04"}


class TestValues:
    def test_distances_are_numeric_and_nonnegative(self, routes: pd.DataFrame) -> None:
        # A handful of real rows have ORIGIN == DEST (same-airport segments, e.g. maintenance/
        # test flights) with DISTANCE=0 — verified in the raw file, not a parsing artifact.
        assert routes["distance_mi"].dtype == float
        assert (routes["distance_mi"] >= 0).all()
        assert (routes.loc[routes["iata"] != routes["dest"], "distance_mi"] > 0).all()

    def test_anc_has_at_least_six_destinations(self, routes: pd.DataFrame) -> None:
        anc = routes[routes["iata"] == "ANC"]
        assert anc["dest"].nunique() >= 6

    def test_anc_has_cargo_rows_with_zero_seats(self, routes: pd.DataFrame) -> None:
        anc_cargo = routes[(routes["iata"] == "ANC") & (routes["seats"] == 0)]
        assert len(anc_cargo) > 0
        assert (anc_cargo["passengers"] == 0).all()

    def test_seats_and_departures_are_nonnegative(self, routes: pd.DataFrame) -> None:
        assert (routes["seats"] >= 0).all()
        assert (routes["departures"] >= 0).all()

    def test_aircraft_config_is_present(self, routes: pd.DataFrame) -> None:
        assert routes["aircraft_config"].notna().all()
        assert (routes["aircraft_config"] != "").all()


@pytest.mark.skip(reason="T-100 International Segment table not landed (15-min probe, 2026-08-16) — see module docstring")
class TestInternational:
    def test_jfk_has_an_international_route(self) -> None:
        ...


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_path: Path) -> None:
        adapter = BtsT100SegmentAdapter()
        adapter.normalize([fixture_path])
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "bts_t100"
        assert vintage.url == FORM_URL
        assert (vintage.period_start, vintage.period_end) == ("2026-04", "2026-04")


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_and_normalize_one_month(self) -> None:
        adapter = BtsT100SegmentAdapter()
        paths = adapter.fetch(Period(year=2026, month=4), raw_cache_dir())
        routes = adapter.normalize(paths)["routes_month"]
        assert len(routes) > 1000
        assert "ANC" in set(routes["iata"])
