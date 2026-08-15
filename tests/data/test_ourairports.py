"""Tests for `airport_agent.data.adapters.ourairports` — normalize on real fixture rows."""
from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
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

    def test_closed_matches_real_rows(self, normalized: dict[str, pd.DataFrame]) -> None:
        closed = normalized["runways"].set_index(["faa_locid", "runway_id"])["closed"]
        assert bool(closed[("ORD", "14L")]) is True  # decommissioned ORD runway
        assert bool(closed[("BOS", "04L")]) is False  # active BOS runway


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


def _write_raw_csvs(tmp_path: Path, rows: list[dict[str, str]]) -> list[Path]:
    """Write a raw-shaped airports.csv (+ empty runways.csv) that `normalize` can read."""
    airports = tmp_path / "ourairports_airports.csv"
    runways = tmp_path / "ourairports_runways.csv"
    pd.DataFrame(rows).to_csv(airports, index=False, encoding="utf-8")
    pd.DataFrame(
        columns=["airport_ident", "length_ft", "width_ft", "surface", "closed", "le_ident"]
    ).to_csv(runways, index=False, encoding="utf-8")
    return [airports, runways]


class TestRowFilter:
    """Only US large/medium/small airports that have an IATA code reach the store."""

    def test_keeps_valid_row_drops_heliport_foreign_and_blank_iata(self, tmp_path: Path) -> None:
        paths = _write_raw_csvs(
            tmp_path,
            [
                _raw_airport_row(),  # US large_airport with IATA -> kept
                _raw_airport_row(  # heliport (wrong type) -> dropped
                    ident="KJRB", type="heliport", name="Downtown Manhattan Heliport",
                    iata_code="JRB", local_code="JRB", icao_code="KJRB", gps_code="KJRB",
                    iso_region="US-NY", municipality="New York",
                ),
                _raw_airport_row(  # Canadian airport -> dropped
                    ident="CYYZ", icao_code="CYYZ", gps_code="CYYZ", local_code="",
                    iata_code="YYZ", iso_country="CA", iso_region="CA-ON", municipality="Toronto",
                    name="Toronto Pearson International Airport",
                ),
                _raw_airport_row(  # US airport without an IATA code -> dropped
                    ident="KBED", icao_code="KBED", gps_code="KBED", local_code="BED",
                    iata_code="", name="Laurence G Hanscom Field", municipality="Bedford",
                ),
            ],
        )

        airports = OurAirportsAdapter().normalize(paths)["airports"]

        assert list(airports["iata"]) == ["BOS"]

    @pytest.mark.parametrize("kept_type", ["large_airport", "medium_airport", "small_airport"])
    def test_all_three_airport_types_are_kept(self, tmp_path: Path, kept_type: str) -> None:
        paths = _write_raw_csvs(tmp_path, [_raw_airport_row(type=kept_type)])
        assert list(OurAirportsAdapter().normalize(paths)["airports"]["iata"]) == ["BOS"]

    @pytest.mark.parametrize("dropped_type", ["heliport", "seaplane_base", "closed", "balloonport"])
    def test_non_airport_types_are_dropped(self, tmp_path: Path, dropped_type: str) -> None:
        paths = _write_raw_csvs(tmp_path, [_raw_airport_row(type=dropped_type)])
        assert len(OurAirportsAdapter().normalize(paths)["airports"]) == 0


class TestVintageIsDataDerived:
    """Vintage describes the raw files (mtime), never the wall clock — cached files stay old."""

    def _aged_copy(self, tmp_path: Path, fixture_paths: list[Path], when: datetime) -> list[Path]:
        copies = []
        for src in fixture_paths:
            dest = tmp_path / f"ourairports_{src.name}"
            shutil.copyfile(src, dest)
            os.utime(dest, (when.timestamp(), when.timestamp()))
            copies.append(dest)
        return copies

    def test_normalize_uses_file_mtime_not_now(self, tmp_path: Path, fixture_paths: list[Path]) -> None:
        aged = self._aged_copy(tmp_path, fixture_paths, datetime(2021, 3, 4, 12, 0, tzinfo=UTC))
        adapter = OurAirportsAdapter()

        tables = adapter.normalize(aged)

        assert (tables["airports"]["vintage"] == "2021-03-04").all()
        assert (tables["runways"]["vintage"] == "2021-03-04").all()
        assert adapter.vintage().fetched_at.startswith("2021-03-04T12:00")

    def test_newest_file_wins(self, tmp_path: Path, fixture_paths: list[Path]) -> None:
        aged = self._aged_copy(tmp_path, fixture_paths, datetime(2021, 3, 4, 12, 0, tzinfo=UTC))
        newer = datetime(2022, 6, 7, 8, 0, tzinfo=UTC).timestamp()
        os.utime(aged[1], (newer, newer))

        adapter = OurAirportsAdapter()
        tables = adapter.normalize(aged)

        assert (tables["airports"]["vintage"] == "2022-06-07").all()


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
