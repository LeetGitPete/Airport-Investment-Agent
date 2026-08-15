"""Tests for `airport_agent.data.adapters.faa_aip` — normalize on real file subsets."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.faa_aip import (
    AIP_GRANTS_COLUMNS,
    FISCAL_YEARS,
    GRANT_HISTORIES_URL,
    FaaAipAdapter,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_LOCIDS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_paths(fixtures_dir: Path) -> list[Path]:
    base = fixtures_dir / "faa_aip"
    return [base / f"FY{fy}.xlsx" for fy in FISCAL_YEARS]


@pytest.fixture
def grants(fixture_paths: list[Path]) -> pd.DataFrame:
    return FaaAipAdapter().normalize(fixture_paths)["aip_grants"]


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["faa_aip"] is FaaAipAdapter

    def test_kind_is_bulk(self) -> None:
        assert FaaAipAdapter.kind == "bulk"


class TestFiscalYears:
    def test_ten_fiscal_years(self) -> None:
        assert FISCAL_YEARS == tuple(range(2016, 2026))
        assert len(FISCAL_YEARS) == 10


class TestNormalizeShape:
    def test_returns_aip_grants(self, fixture_paths: list[Path]) -> None:
        assert set(FaaAipAdapter().normalize(fixture_paths)) == {"aip_grants"}

    def test_columns(self, grants: pd.DataFrame) -> None:
        assert list(grants.columns) == list(AIP_GRANTS_COLUMNS)

    def test_provenance_on_every_row(self, grants: pd.DataFrame) -> None:
        assert (grants["source_id"] == "faa_aip").all()
        assert grants["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()

    def test_covers_every_fiscal_year(self, grants: pd.DataFrame) -> None:
        assert set(grants["fy"].unique()) == set(FISCAL_YEARS)

    def test_one_row_per_locid_per_fy(self, grants: pd.DataFrame) -> None:
        counts = grants.groupby(["faa_locid", "fy"]).size()
        assert (counts == 1).all()

    def test_amounts_are_positive_or_zero(self, grants: pd.DataFrame) -> None:
        assert (grants["amount_usd"] >= 0).all()


class TestBlockGrantsDropped:
    def test_no_star_prefixed_locid(self, grants: pd.DataFrame) -> None:
        # Fixture files deliberately keep 1-2 real "*"-prefixed block-grant rows per FY
        # (see make_fixture.py) so this proves the filter actually removes them, not just
        # that none happened to be present.
        assert not grants["faa_locid"].str.startswith("*").any()


class TestValues:
    def test_bos_has_a_grant_every_fixture_year(self, grants: pd.DataFrame) -> None:
        bos = grants[grants["faa_locid"] == "BOS"]
        assert set(bos["fy"]) == set(FISCAL_YEARS)
        assert (bos["amount_usd"] > 0).all()

    def test_not_every_airport_has_a_grant_every_year(self, grants: pd.DataFrame) -> None:
        # Real FAA funding cycles: large hubs skip years (verified 2026-08-16, e.g. SNA
        # absent from FY2016, SFO absent from FY2017/2018, ATL absent from FY2019/2025).
        sna_2016 = grants[(grants["faa_locid"] == "SNA") & (grants["fy"] == 2016)]
        assert sna_2016.empty

    def test_fy2018_uses_the_year_named_sheet(self, grants: pd.DataFrame) -> None:
        # FY2018's workbook carries a pivot-summary decoy sheet with no LocID column
        # (Sheet1) plus two equivalent detail sheets ("2018" and a "Copy Of..." dup);
        # normalize() must not crash on the decoy and must still find grant rows for 2018.
        fy2018 = grants[grants["fy"] == 2018]
        assert len(fy2018) >= len(FIXTURE_LOCIDS) - 3  # a few real no-grant-that-year gaps


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_paths: list[Path]) -> None:
        adapter = FaaAipAdapter()
        adapter.normalize(fixture_paths)
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "faa_aip"
        assert vintage.url == GRANT_HISTORIES_URL
        assert vintage.period_start == "2016"
        assert vintage.period_end == "2025"


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_and_normalize(self) -> None:
        adapter = FaaAipAdapter()
        paths = adapter.fetch(None, raw_cache_dir() / "faa_aip")
        assert len(paths) == 10
        out = adapter.normalize(paths)
        grants = out["aip_grants"]
        assert len(grants) > 1000
        assert not grants["faa_locid"].str.startswith("*").any()
