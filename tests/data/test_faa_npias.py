"""Tests for `airport_agent.data.adapters.faa_npias` — normalize on real Appendix A rows.

The capacity-label expectations below are whatever the transcribed FAA lists in
`data/curated/npias_capacity_lists.yaml` say (NPIAS 2025-2029 Figure 1, p. 9): SFO/JFK/BOS
are severe-by-2033 (4), LAX is constrained-by-2028 (3), ATL is constrained-by-2033 (2), SNA
is congested (1) and PWM is not on any list (0).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.faa_npias import (
    NPIAS_COLUMNS,
    NPIAS_URL,
    CapacityLists,
    FaaNpiasAdapter,
    load_capacity_lists,
)
from airport_agent.data.paths import raw_cache_dir

FIXTURE_LOCIDS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "faa_npias" / "appendix_a_subset.xlsx"


@pytest.fixture
def npias(fixture_path: Path) -> pd.DataFrame:
    return FaaNpiasAdapter().normalize([fixture_path])["npias"]


@pytest.fixture
def by_locid(npias: pd.DataFrame) -> pd.DataFrame:
    return npias.set_index("faa_locid")


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["faa_npias"] is FaaNpiasAdapter

    def test_kind_is_bulk(self) -> None:
        assert FaaNpiasAdapter.kind == "bulk"


class TestNormalizeShape:
    def test_returns_the_npias_table(self, fixture_path: Path) -> None:
        assert set(FaaNpiasAdapter().normalize([fixture_path])) == {"npias"}

    def test_columns_match_store_schema(self, npias: pd.DataFrame) -> None:
        assert list(npias.columns) == list(NPIAS_COLUMNS)

    def test_covers_every_fixture_airport(self, npias: pd.DataFrame) -> None:
        assert FIXTURE_LOCIDS <= set(npias["faa_locid"])

    def test_locids_are_stripped(self, npias: pd.DataFrame) -> None:
        assert (npias["faa_locid"] == npias["faa_locid"].str.strip()).all()

    def test_provenance_on_every_row(self, npias: pd.DataFrame) -> None:
        assert (npias["source_id"] == "faa_npias").all()
        assert npias["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()


class TestValues:
    def test_dev_estimate_is_numeric(self, npias: pd.DataFrame) -> None:
        assert npias["dev_estimate_usd"].dtype == float
        assert (npias["dev_estimate_usd"] >= 0).all()

    def test_dev_estimate_matches_the_source_row(self, by_locid: pd.DataFrame) -> None:
        # Appendix A "Development Estimate 2025-2029" for LAX, verbatim.
        assert by_locid.loc["LAX", "dev_estimate_usd"] == 572656460.0

    def test_enplanements_are_numeric(self, by_locid: pd.DataFrame) -> None:
        assert by_locid.loc["ATL", "enplanements"] == 50950068.0

    @pytest.mark.parametrize(
        ("locid", "hub"),
        [("LAX", "large"), ("ANC", "medium"), ("PWM", "small")],
    )
    def test_hub_class_is_the_shared_vocabulary(self, by_locid: pd.DataFrame, locid: str, hub: str) -> None:
        assert by_locid.loc[locid, "hub"] == hub


class TestCapacityLabels:
    @pytest.mark.parametrize("locid", ["SFO", "JFK", "BOS"])
    def test_severe_airports_are_labelled_4(self, by_locid: pd.DataFrame, locid: str) -> None:
        assert by_locid.loc[locid, "capacity_label"] == 4
        assert by_locid.loc[locid, "capacity_label_text"] == "severe_2033"
        assert by_locid.loc[locid, "capacity_label"] >= 2

    def test_constrained_2028_airport_is_labelled_3(self, by_locid: pd.DataFrame) -> None:
        assert by_locid.loc["LAX", "capacity_label"] == 3
        assert by_locid.loc["LAX", "capacity_label_text"] == "constrained_2028"

    def test_constrained_2033_airport_is_labelled_2(self, by_locid: pd.DataFrame) -> None:
        assert by_locid.loc["ATL", "capacity_label"] == 2
        assert by_locid.loc["ATL", "capacity_label_text"] == "constrained_2033"

    def test_congested_airport_is_labelled_1(self, by_locid: pd.DataFrame) -> None:
        assert by_locid.loc["SNA", "capacity_label"] == 1
        assert by_locid.loc["SNA", "capacity_label_text"] == "congested"

    def test_unlisted_airport_is_labelled_0(self, by_locid: pd.DataFrame) -> None:
        assert by_locid.loc["PWM", "capacity_label"] == 0
        assert by_locid.loc["PWM", "capacity_label_text"] == "none"

    def test_label_column_is_integer(self, npias: pd.DataFrame) -> None:
        assert npias["capacity_label"].between(0, 4).all()


class TestCuratedLists:
    @pytest.fixture
    def lists(self) -> CapacityLists:
        return load_capacity_lists()

    def test_counts_match_the_npias_narrative(self, lists: CapacityLists) -> None:
        # NPIAS 2025-2029 p. 9: 11 constrained in 2028, 14 in 2033, 13 additionally congested.
        assert len(lists.constrained_2028) == 11
        assert len(lists.constrained_2033) == 14
        assert len(lists.congested) == 13

    def test_2033_is_a_superset_of_2028(self, lists: CapacityLists) -> None:
        assert set(lists.constrained_2028) <= set(lists.constrained_2033)
        assert set(lists.severe_2033) <= set(lists.constrained_2033)

    def test_congested_and_constrained_are_disjoint(self, lists: CapacityLists) -> None:
        assert not set(lists.congested) & set(lists.constrained_2033)

    def test_lists_agree_with_the_verbatim_figure_transcription(self, lists: CapacityLists) -> None:
        assert lists.derived_lists() == {
            "severe_2033": sorted(lists.severe_2033),
            "constrained_2028": sorted(lists.constrained_2028),
            "constrained_2033": sorted(lists.constrained_2033),
            "congested": sorted(lists.congested),
        }

    def test_provenance_is_recorded(self, lists: CapacityLists) -> None:
        assert lists.source_url.startswith("https://www.faa.gov/")
        assert lists.as_of == "2024-09"


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_path: Path) -> None:
        adapter = FaaNpiasAdapter()
        adapter.normalize([fixture_path])
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "faa_npias"
        assert vintage.url == NPIAS_URL
        assert (vintage.period_start, vintage.period_end) == ("2025", "2029")


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_downloads_and_normalizes_the_real_workbook(self) -> None:
        adapter = FaaNpiasAdapter()
        paths = adapter.fetch(None, raw_cache_dir())
        npias = adapter.normalize(paths)["npias"]
        assert len(npias) > 3000
        assert set(npias.loc[npias["capacity_label"] == 4, "faa_locid"]) == {
            "BOS", "EWR", "JFK", "LAS", "SAN", "SEA", "SFO",
        }
