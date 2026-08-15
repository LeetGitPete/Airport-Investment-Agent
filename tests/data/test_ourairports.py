"""Tests for `airport_agent.data.adapters.ourairports` — normalize on real fixture rows."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.ourairports import (
    AIRPORT_COLUMNS,
    RUNWAY_COLUMNS,
    OurAirportsAdapter,
)
from airport_agent.data.paths import raw_cache_dir
from airport_agent.data.store import Store

FIXTURE_IATA = {
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
}


@pytest.fixture
def fixture_paths(fixtures_dir: Path) -> list[Path]:
    base = fixtures_dir / "ourairports"
    return [base / "airports.csv", base / "runways.csv"]


@pytest.fixture
def normalized(fixture_paths: list[Path]) -> dict[str, pd.DataFrame]:
    return OurAirportsAdapter().normalize(fixture_paths)


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["ourairports"] is OurAirportsAdapter

    def test_kind_is_bulk(self) -> None:
        assert OurAirportsAdapter.kind == "bulk"


class TestNormalizeAirports:
    def test_fifteen_fixture_airports(self, normalized: dict[str, pd.DataFrame]) -> None:
        airports = normalized["airports"]
        assert len(airports) == 15
        assert set(airports["iata"]) == FIXTURE_IATA

    def test_columns_match_store_schema(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert list(normalized["airports"].columns) == list(AIRPORT_COLUMNS)

    def test_ord_icao(self, normalized: dict[str, pd.DataFrame]) -> None:
        row = normalized["airports"].set_index("iata").loc["ORD"]
        assert row["icao"] == "KORD"
        assert row["faa_locid"] == "ORD"

    def test_pwm_state_and_city(self, normalized: dict[str, pd.DataFrame]) -> None:
        row = normalized["airports"].set_index("iata").loc["PWM"]
        assert row["state"] == "ME"
        assert row["city"] == "Portland"

    def test_anc_latitude_above_60(self, normalized: dict[str, pd.DataFrame]) -> None:
        row = normalized["airports"].set_index("iata").loc["ANC"]
        assert row["lat"] > 60
        assert row["lon"] < -140

    def test_placeholder_columns_left_for_later_sources(self, normalized: dict[str, pd.DataFrame]) -> None:
        airports = normalized["airports"]
        assert (airports["faa_region"] == "").all()
        assert (airports["hub_size"] == "nonhub").all()
        assert airports["cbsa_code"].isna().all()
        assert airports["cbsa_name"].isna().all()
        assert (~airports["commercial"]).all()

    def test_provenance_columns(self, normalized: dict[str, pd.DataFrame]) -> None:
        airports = normalized["airports"]
        assert (airports["source_id"] == "ourairports").all()
        assert airports["vintage"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()


def _raw_airport_row(**overrides: str) -> dict[str, str]:
    """One raw OurAirports row (shape of the real CSV), overridable per test."""
    row = {
        "ident": "KBOS",
        "type": "large_airport",
        "name": "Boston Logan International Airport",
        "latitude_deg": "42.36197",
        "longitude_deg": "-71.0079",
        "iso_country": "US",
        "iso_region": "US-MA",
        "municipality": "Boston",
        "icao_code": "KBOS",
        "iata_code": "BOS",
        "gps_code": "KBOS",
        "local_code": "BOS",
    }
    row.update(overrides)
    return row


class TestIcaoResolution:
    """`icao` prefers the authoritative `icao_code` column, then `ident`, then `gps_code`."""

    def test_fixture_rows_use_icao_code(self, normalized: dict[str, pd.DataFrame], fixtures_dir: Path) -> None:
        raw = pd.read_csv(
            fixtures_dir / "ourairports" / "airports.csv", dtype=str, keep_default_na=False
        )
        expected = dict(zip(raw["iata_code"], raw["icao_code"], strict=True))
        got = dict(zip(normalized["airports"]["iata"], normalized["airports"]["icao"], strict=True))
        assert got == expected

    def test_prefers_icao_code_over_a_local_ident(self) -> None:
        # Real upstream shape: Nunapitchuk (NUP) has ident "16A" but icao_code "PPIT".
        raw = pd.DataFrame(
            [
                _raw_airport_row(
                    ident="16A", icao_code="PPIT", gps_code="PPIT", local_code="16A",
                    iata_code="NUP", type="small_airport", iso_region="US-AK",
                )
            ]
        )
        out = OurAirportsAdapter()._airports_frame(raw)
        assert out.loc[0, "icao"] == "PPIT"
        assert out.loc[0, "faa_locid"] == "16A"

    def test_falls_back_to_ident_when_icao_code_blank(self) -> None:
        # Real upstream shape: many small US fields have no ICAO code at all.
        raw = pd.DataFrame(
            [_raw_airport_row(ident="07FA", icao_code="", gps_code="07FA", local_code="07FA", iata_code="OCA")]
        )
        assert OurAirportsAdapter()._airports_frame(raw).loc[0, "icao"] == "07FA"

    def test_falls_back_to_gps_code_when_icao_code_and_ident_blank(self) -> None:
        raw = pd.DataFrame([_raw_airport_row(ident="", icao_code="", gps_code="KBOS")])
        assert OurAirportsAdapter()._airports_frame(raw).loc[0, "icao"] == "KBOS"


class TestNormalizeRunways:
    def test_columns_match_store_schema(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert list(normalized["runways"].columns) == list(RUNWAY_COLUMNS)

    def test_bos_has_at_least_four_runways(self, normalized: dict[str, pd.DataFrame]) -> None:
        runways = normalized["runways"]
        assert len(runways[runways["faa_locid"] == "BOS"]) >= 4

    def test_keyed_by_faa_locid_not_ident(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert set(normalized["runways"]["faa_locid"]) <= FIXTURE_IATA

    def test_longest_atl_runway_is_realistic(self, normalized: dict[str, pd.DataFrame]) -> None:
        runways = normalized["runways"]
        atl = runways[runways["faa_locid"] == "ATL"]
        assert atl["length_ft"].max() >= 9000

    def test_closed_is_boolean(self, normalized: dict[str, pd.DataFrame]) -> None:
        assert normalized["runways"]["closed"].dtype == bool


class TestVintage:
    def test_vintage_shape(self) -> None:
        v = OurAirportsAdapter().vintage()
        assert isinstance(v, SourceVintage)
        assert v.source_id == "ourairports"
        assert v.period_start is None and v.period_end is None
        assert v.url is not None and v.fetched_at


class TestStoreRoundTrip:
    def test_replace_rows_airports_and_runways(
        self, tmp_store: Store, normalized: dict[str, pd.DataFrame]
    ) -> None:
        tmp_store.replace_rows("airports", normalized["airports"], None)
        tmp_store.replace_rows("runways", normalized["runways"], None)

        assert tmp_store.con.execute("SELECT count(*) FROM airports").fetchone()[0] == 15
        lat = tmp_store.con.execute("SELECT lat FROM airports WHERE iata = 'ANC'").fetchone()[0]
        assert lat > 60
        n_bos = tmp_store.con.execute(
            "SELECT count(*) FROM runways WHERE faa_locid = 'BOS'"
        ).fetchone()[0]
        assert n_bos >= 4

    def test_replace_rows_is_idempotent(self, tmp_store: Store, normalized: dict[str, pd.DataFrame]) -> None:
        tmp_store.replace_rows("airports", normalized["airports"], None)
        tmp_store.replace_rows("airports", normalized["airports"], None)
        assert tmp_store.con.execute("SELECT count(*) FROM airports").fetchone()[0] == 15


@pytest.mark.network
class TestLiveFetch:
    def test_fetch_and_normalize_real_files(self) -> None:
        adapter = OurAirportsAdapter()
        paths = adapter.fetch(None, raw_cache_dir())
        assert len(paths) == 2
        tables = adapter.normalize(paths)
        assert len(tables["airports"]) > 1000
        assert FIXTURE_IATA <= set(tables["airports"]["iata"])
        assert tables["airports"]["iata"].is_unique
