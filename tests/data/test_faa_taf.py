"""Tests for `airport_agent.data.adapters.faa_taf` — normalize on real fixture rows."""
from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.faa_taf import (
    ENRICHMENT_COLUMNS,
    MEMBER_FILES,
    TAF_COLUMNS,
    FaaTafAdapter,
    apply_taf_enrichment,
)
from airport_agent.data.adapters.ourairports import OurAirportsAdapter
from airport_agent.data.paths import raw_cache_dir
from airport_agent.data.store import Store

FIXTURE_LOCIDS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}
LARGE_HUBS = {"ATL", "BOS", "DEN", "JFK", "LAX", "ORD", "SFO"}


@pytest.fixture
def fixture_paths(fixtures_dir: Path) -> list[Path]:
    base = fixtures_dir / "faa_taf"
    return [base / name for name in MEMBER_FILES]


@pytest.fixture
def normalized(fixture_paths: list[Path]) -> dict[str, pd.DataFrame]:
    return FaaTafAdapter().normalize(fixture_paths)


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["faa_taf"] is FaaTafAdapter

    def test_kind_is_bulk(self) -> None:
        assert FaaTafAdapter.kind == "bulk"


class TestNormalizeShape:
    def test_returns_the_three_tables(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert set(normalized) == {"taf_history", "taf_forecast", "airports"}

    @pytest.mark.parametrize("table", ["taf_history", "taf_forecast"])
    def test_columns_match_store_schema(self, normalized: dict[str, pd.DataFrame], table: str) -> None:
        assert list(normalized[table].columns) == list(TAF_COLUMNS)

    def test_enrichment_columns(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert list(normalized["airports"].columns) == list(ENRICHMENT_COLUMNS)

    def test_covers_the_fixture_airports(self, normalized: dict[str, pd.DataFrame]) -> None:
        for table in ("taf_history", "taf_forecast", "airports"):
            assert set(normalized[table]["faa_locid"]) == FIXTURE_LOCIDS

    def test_locid_padding_is_stripped(self, normalized: dict[str, pd.DataFrame]) -> None:
        # The FAA pads `locid` to four characters ("BOS "); the store key must not.
        assert all(locid == locid.strip() for locid in normalized["taf_history"]["faa_locid"])

    def test_provenance_columns(self, normalized: dict[str, pd.DataFrame]) -> None:
        for table in ("taf_history", "taf_forecast", "airports"):
            frame = normalized[table]
            assert (frame["source_id"] == "faa_taf").all()
            assert frame["vintage"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()


class TestHistoryForecastSplit:
    def test_split_at_the_base_year(self, normalized: dict[str, pd.DataFrame]) -> None:
        history, forecast = normalized["taf_history"], normalized["taf_forecast"]
        assert history["year"].max() == 2024
        assert forecast["year"].min() == 2025

    def test_base_year_is_read_from_the_data(self, fixture_paths: list[Path]) -> None:
        adapter = FaaTafAdapter()
        adapter.normalize(fixture_paths)
        assert adapter.base_year == 2025

    def test_split_is_disjoint(self, normalized: dict[str, pd.DataFrame]) -> None:
        history, forecast = normalized["taf_history"], normalized["taf_forecast"]
        assert set(history["year"]) & set(forecast["year"]) == set()

    def test_forecast_runs_to_2055(self, normalized: dict[str, pd.DataFrame]) -> None:
        forecast = normalized["taf_forecast"]
        assert forecast["year"].max() == 2055
        bos = forecast[forecast["faa_locid"] == "BOS"]
        assert set(range(2025, 2056)) <= set(bos["year"])

    def test_history_reaches_back_to_1976(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert normalized["taf_history"]["year"].min() == 1976


class TestValues:
    def test_bos_2024_enplanements_are_the_sum_of_all_five_components(
        self, normalized: dict[str, pd.DataFrame], fixtures_dir: Path
    ) -> None:
        raw = pd.read_excel(fixtures_dir / "faa_taf" / "Enplanements.xlsx", dtype={"locid": str})
        row = raw[(raw["locid"].str.strip() == "BOS") & (raw["ayear"] == 2024)].iloc[0]
        expected = float(row[["aac", "aat", "commuter", "us_flag", "frgn_flag"]].sum())

        history = normalized["taf_history"]
        got = history[(history["faa_locid"] == "BOS") & (history["year"] == 2024)]["enplanements"].iloc[0]

        assert got == expected
        assert got > 20_000_000  # sanity: BOS enplanes ~21M/yr

    def test_bos_2024_ops_total_sums_itinerant_and_local(
        self, normalized: dict[str, pd.DataFrame], fixtures_dir: Path
    ) -> None:
        raw = pd.read_excel(fixtures_dir / "faa_taf" / "AirportsOperations.xlsx", dtype={"locid": str})
        row = raw[(raw["locid"].str.strip() == "BOS") & (raw["ayear"] == 2024)].iloc[0]
        expected = float(row[["itn_Ac", "itn_at", "itn_ga", "itn_mil", "loc_ga", "loc_mil"]].sum())

        history = normalized["taf_history"]
        got = history[(history["faa_locid"] == "BOS") & (history["year"] == 2024)]["ops_total"].iloc[0]

        assert got == expected
        assert got != expected + float(row["tot_overs"])  # overflights are excluded

    def test_ops_total_positive_for_every_fixture_airport(self, normalized: dict[str, pd.DataFrame]) -> None:
        recent = normalized["taf_history"]
        recent = recent[recent["year"] == 2024]
        assert len(recent) == 15
        assert (recent["ops_total"] > 0).all()
        assert (recent["enplanements"] > 0).all()

    def test_forecast_values_are_positive(self, normalized: dict[str, pd.DataFrame]) -> None:
        forecast = normalized["taf_forecast"]
        assert (forecast["ops_total"] > 0).all()
        assert (forecast["enplanements"] > 0).all()

    def test_years_before_operations_coverage_have_no_ops(self, normalized: dict[str, pd.DataFrame]) -> None:
        # Enplanements start in 1976, operations only in 1990: the join must keep the
        # early enplanement rows with a null ops_total rather than dropping them.
        history = normalized["taf_history"]
        early = history[(history["faa_locid"] == "BOS") & (history["year"] == 1980)]
        assert len(early) == 1
        assert early["enplanements"].iloc[0] > 0
        assert pd.isna(early["ops_total"].iloc[0])


class TestEnrichment:
    def test_bos_is_a_large_hub_in_new_england(self, normalized: dict[str, pd.DataFrame]) -> None:
        row = normalized["airports"].set_index("faa_locid").loc["BOS"]
        assert row["hub_size"] == "large"
        assert row["faa_region"] == "ANE"

    def test_anc_is_in_the_alaskan_region(self, normalized: dict[str, pd.DataFrame]) -> None:
        row = normalized["airports"].set_index("faa_locid").loc["ANC"]
        assert row["faa_region"] == "AAL"
        assert row["hub_size"] == "medium"

    @pytest.mark.parametrize(
        ("locid", "hub_size"),
        [("ATL", "large"), ("BDL", "medium"), ("PWM", "small"), ("BTV", "small")],
    )
    def test_hub_size_mapping(self, normalized: dict[str, pd.DataFrame], locid: str, hub_size: str) -> None:
        assert normalized["airports"].set_index("faa_locid").loc[locid, "hub_size"] == hub_size

    def test_only_documented_hub_sizes_and_regions(self, normalized: dict[str, pd.DataFrame]) -> None:
        airports = normalized["airports"]
        assert set(airports["hub_size"]) <= {"large", "medium", "small", "nonhub"}
        assert set(airports["faa_region"]) <= {
            "ANE", "AEA", "ASO", "AGL", "ACE", "ASW", "ANM", "AWP", "AAL",
        }


class TestApplyEnrichment:
    @pytest.fixture
    def seeded(self, tmp_store: Store, fixtures_dir: Path) -> Store:
        base = fixtures_dir / "ourairports"
        tables = OurAirportsAdapter().normalize([base / "airports.csv", base / "runways.csv"])
        tmp_store.replace_rows("airports", tables["airports"], None)
        return tmp_store

    def test_updates_hub_size_and_region(self, seeded: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_taf_enrichment(seeded, normalized["airports"])

        row = seeded.con.execute(
            "SELECT hub_size, faa_region FROM airports WHERE faa_locid = 'BOS'"
        ).fetchone()
        assert row == ("large", "ANE")
        anc = seeded.con.execute("SELECT faa_region FROM airports WHERE faa_locid = 'ANC'").fetchone()
        assert anc[0] == "AAL"

    def test_does_not_insert_or_delete_rows(self, seeded: Store, normalized: dict[str, pd.DataFrame]) -> None:
        before = seeded.con.execute("SELECT count(*) FROM airports").fetchone()[0]
        apply_taf_enrichment(seeded, normalized["airports"])
        assert seeded.con.execute("SELECT count(*) FROM airports").fetchone()[0] == before

    def test_is_idempotent(self, seeded: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_taf_enrichment(seeded, normalized["airports"])
        apply_taf_enrichment(seeded, normalized["airports"])
        large = seeded.con.execute(
            "SELECT faa_locid FROM airports WHERE hub_size = 'large' ORDER BY faa_locid"
        ).fetchall()
        assert {row[0] for row in large} == LARGE_HUBS

    def test_leaves_airports_absent_from_the_taf_frame_untouched(
        self, seeded: Store, normalized: dict[str, pd.DataFrame]
    ) -> None:
        frame = normalized["airports"]
        apply_taf_enrichment(seeded, frame[frame["faa_locid"] == "BOS"])

        anc = seeded.con.execute(
            "SELECT hub_size, faa_region FROM airports WHERE faa_locid = 'ANC'"
        ).fetchone()
        assert anc == ("nonhub", "")  # OurAirports placeholders, untouched

    def test_empty_frame_is_a_no_op(self, seeded: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_taf_enrichment(seeded, normalized["airports"].iloc[0:0])
        assert seeded.con.execute("SELECT count(*) FROM airports WHERE hub_size = 'large'").fetchone()[0] == 0


class TestStoreRoundTrip:
    def test_history_and_forecast_round_trip(
        self, tmp_store: Store, normalized: dict[str, pd.DataFrame]
    ) -> None:
        tmp_store.replace_rows("taf_history", normalized["taf_history"], None)
        tmp_store.replace_rows("taf_forecast", normalized["taf_forecast"], None)

        n_hist = tmp_store.con.execute("SELECT count(*) FROM taf_history").fetchone()[0]
        assert n_hist == len(normalized["taf_history"])
        enp_2055 = tmp_store.con.execute(
            "SELECT enplanements FROM taf_forecast WHERE faa_locid = 'BOS' AND year = 2055"
        ).fetchone()[0]
        assert enp_2055 > 0


class TestVintage:
    def test_vintage_shape(self) -> None:
        v = FaaTafAdapter().vintage()
        assert isinstance(v, SourceVintage)
        assert v.source_id == "faa_taf"
        assert "TAF 2025" in v.description
        assert v.url is not None and v.fetched_at

    def test_period_spans_history_and_forecast(self, fixture_paths: list[Path]) -> None:
        adapter = FaaTafAdapter()
        adapter.normalize(fixture_paths)
        v = adapter.vintage()
        assert v.period_start == "1976"
        assert v.period_end == "2055"

    def test_vintage_is_file_derived_not_now(self, tmp_path: Path, fixture_paths: list[Path]) -> None:
        when = datetime(2021, 3, 4, 12, 0, tzinfo=UTC)
        copies = []
        for src in fixture_paths:
            dest = tmp_path / src.name
            shutil.copyfile(src, dest)
            os.utime(dest, (when.timestamp(), when.timestamp()))
            copies.append(dest)

        adapter = FaaTafAdapter()
        tables = adapter.normalize(copies)

        assert (tables["taf_history"]["vintage"] == "2021-03-04").all()
        assert adapter.vintage().fetched_at.startswith("2021-03-04T12:00")


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_extracts_the_three_members(self) -> None:
        adapter = FaaTafAdapter()
        paths = adapter.fetch(None, raw_cache_dir())
        assert [p.name for p in paths] == list(MEMBER_FILES)
        assert all(p.stat().st_size > 0 for p in paths)

        tables = adapter.normalize(paths)
        assert len(tables["airports"]) > 3000
        assert tables["taf_forecast"]["year"].max() == 2055
        assert set(tables["airports"][tables["airports"]["hub_size"] == "large"]["faa_locid"]) >= LARGE_HUBS
