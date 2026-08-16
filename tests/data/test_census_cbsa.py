"""Tests for `airport_agent.data.adapters.census_cbsa` — normalize on real file subsets."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.census_cbsa import (
    CATCHMENT_COLUMNS,
    CBSA_CENTROID_COLUMNS,
    CBSA_POPULATION_COLUMNS,
    GAZETTEER_MEMBER,
    POPULATION_URLS,
    CensusCbsaAdapter,
    apply_cbsa_enrichment,
)
from airport_agent.data.adapters.ourairports import OurAirportsAdapter
from airport_agent.data.paths import raw_cache_dir
from airport_agent.data.store import Store

FIXTURE_IATAS = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_paths(fixtures_dir: Path) -> list[Path]:
    base = fixtures_dir / "census_cbsa"
    return [base / "cbsa_pop_2020-2025.csv", base / "cbsa_pop_2010-2019.csv", base / GAZETTEER_MEMBER]


@pytest.fixture
def normalized(fixture_paths: list[Path]) -> dict[str, pd.DataFrame]:
    return CensusCbsaAdapter().normalize(fixture_paths)


@pytest.fixture
def population(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["cbsa_population"]


@pytest.fixture
def centroids(normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return normalized["cbsa_centroids"]


@pytest.fixture
def seeded_store(fixtures_dir: Path) -> Store:
    store = Store(":memory:")
    base = fixtures_dir / "ourairports"
    tables = OurAirportsAdapter().normalize([base / "airports.csv", base / "runways.csv"])
    store.replace_rows("airports", tables["airports"], None)
    return store


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["census_cbsa"] is CensusCbsaAdapter

    def test_kind_is_bulk(self) -> None:
        assert CensusCbsaAdapter.kind == "bulk"


class TestNormalizeShape:
    def test_returns_both_tables(self, fixture_paths: Path) -> None:
        assert set(CensusCbsaAdapter().normalize(fixture_paths)) == {"cbsa_population", "cbsa_centroids"}

    def test_population_columns(self, population: pd.DataFrame) -> None:
        assert list(population.columns) == list(CBSA_POPULATION_COLUMNS)

    def test_centroid_columns(self, centroids: pd.DataFrame) -> None:
        assert list(centroids.columns) == list(CBSA_CENTROID_COLUMNS)

    def test_provenance_on_every_row(self, population: pd.DataFrame, centroids: pd.DataFrame) -> None:
        for df in (population, centroids):
            assert (df["source_id"] == "census_cbsa").all()
            assert df["vintage"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()

    def test_one_population_row_per_cbsa_per_year(self, population: pd.DataFrame) -> None:
        # The metro-division sub-row filter must collapse each CBSA to a single row per year
        # (verified: 14460 "Boston-Cambridge-Newton" carries a "Boston, MA" MDIV sub-row with
        # the same CBSA code and LSAD in the raw file).
        counts = population.groupby(["cbsa_code", "year"]).size()
        assert (counts == 1).all()

    def test_one_centroid_row_per_cbsa(self, centroids: pd.DataFrame) -> None:
        assert centroids["cbsa_code"].is_unique

    def test_micropolitan_areas_are_excluded(self, centroids: pd.DataFrame) -> None:
        # The fixture gazetteer includes two real Micropolitan (CBSA_TYPE=2) rows to prove
        # the filter actually excludes them, not just that none happened to be present.
        assert "Micro Area" not in " ".join(centroids["cbsa_name"])


class TestValues:
    def test_boston_population_2025(self, population: pd.DataFrame) -> None:
        row = population[(population["cbsa_code"] == "14460") & (population["year"] == 2025)].iloc[0]
        assert row["cbsa_name"].startswith("Boston-Cambridge-Newton")
        assert row["population"] > 4_000_000

    def test_boston_centroid(self, centroids: pd.DataFrame) -> None:
        row = centroids[centroids["cbsa_code"] == "14460"].iloc[0]
        assert row["lat"] == pytest.approx(42.517606, abs=0.01)
        assert row["lon"] == pytest.approx(-71.021993, abs=0.01)

    def test_population_spans_both_vintages(self, population: pd.DataFrame) -> None:
        boston = population[population["cbsa_code"] == "14460"]
        assert boston["year"].min() <= 2011
        assert boston["year"].max() >= 2025


class TestApplyEnrichment:
    def test_updates_cbsa_code_and_name(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        row = seeded_store.con.execute("SELECT cbsa_code, cbsa_name FROM airports WHERE iata = 'BOS'").fetchone()
        assert row[0] == "14460"
        assert row[1].startswith("Boston-Cambridge-Newton")

    def test_la_airports_share_one_cbsa(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        rows = seeded_store.con.execute(
            "SELECT iata, cbsa_code FROM airports WHERE iata IN ('LAX','BUR','SNA') ORDER BY iata"
        ).fetchall()
        assert {code for _, code in rows} == {"31080"}

    def test_anc_within_100mi_gets_a_cbsa(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        # ANC's real nearest metro centroid (Anchorage) is ~72mi away, inside the 100mi radius.
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        row = seeded_store.con.execute("SELECT cbsa_code FROM airports WHERE iata = 'ANC'").fetchone()
        assert row[0] == "11260"

    def test_beyond_max_distance_leaves_cbsa_null(
        self, seeded_store: Store, normalized: dict[str, pd.DataFrame]
    ) -> None:
        apply_cbsa_enrichment(
            seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"], max_distance_mi=1.0
        )
        row = seeded_store.con.execute("SELECT cbsa_code FROM airports WHERE iata = 'BOS'").fetchone()
        assert row[0] is None

    def test_writes_catchment_rows(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        cols = [c[0] for c in seeded_store.con.execute("SELECT * FROM catchment LIMIT 0").description]
        assert cols == list(CATCHMENT_COLUMNS)
        bos_2025 = seeded_store.con.execute(
            "SELECT population, gdp_real_usd FROM catchment WHERE iata = 'BOS' AND year = 2025"
        ).fetchone()
        assert bos_2025[0] > 4_000_000
        assert bos_2025[1] is None  # no BEA source

    def test_is_idempotent(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        n = seeded_store.con.execute("SELECT count(*) FROM catchment WHERE iata = 'BOS'").fetchone()[0]
        n_years = normalized["cbsa_population"][normalized["cbsa_population"]["cbsa_code"] == "14460"].shape[0]
        assert n == n_years

    def test_does_not_insert_or_delete_airport_rows(
        self, seeded_store: Store, normalized: dict[str, pd.DataFrame]
    ) -> None:
        before = seeded_store.con.execute("SELECT count(*) FROM airports").fetchone()[0]
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"])
        assert seeded_store.con.execute("SELECT count(*) FROM airports").fetchone()[0] == before

    def test_empty_centroids_is_a_no_op(self, seeded_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        apply_cbsa_enrichment(seeded_store, normalized["cbsa_population"], normalized["cbsa_centroids"].iloc[0:0])
        assert seeded_store.con.execute("SELECT count(*) FROM catchment").fetchone()[0] == 0


class TestVintage:
    def test_vintage_describes_the_source(self, fixture_paths: Path) -> None:
        adapter = CensusCbsaAdapter()
        adapter.normalize(fixture_paths)
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "census_cbsa"
        assert vintage.url == POPULATION_URLS["2020-2025"]
        assert vintage.period_start == "2010"
        assert vintage.period_end == "2025"


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_and_normalize(self) -> None:
        adapter = CensusCbsaAdapter()
        paths = adapter.fetch(None, raw_cache_dir())
        out = adapter.normalize(paths)
        assert len(out["cbsa_population"]) > 3000
        assert len(out["cbsa_centroids"]) > 300
        assert "14460" in set(out["cbsa_centroids"]["cbsa_code"])
