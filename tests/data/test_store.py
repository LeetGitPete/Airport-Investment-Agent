"""Task 1: paths, sources config, Store schema."""
from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data import paths
from airport_agent.data.geo import haversine_mi
from airport_agent.data.sources_config import SourceConfig, load_sources
from airport_agent.data.store import TABLE_NAMES, Store

# paths


def test_default_snapshot_path_is_under_repo_root() -> None:
    snap = paths.default_snapshot_path()
    assert snap == paths.repo_root() / "data" / "snapshot" / "airports.duckdb"


def test_raw_cache_dir_and_curated_dir_under_repo_root() -> None:
    assert paths.raw_cache_dir() == paths.repo_root() / "data" / "raw"
    assert paths.curated_dir() == paths.repo_root() / "data" / "curated"


# store schema


def test_ensure_schema_creates_all_tables(tmp_store: Store) -> None:
    existing = {
        row[0]
        for row in tmp_store.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    for table in TABLE_NAMES:
        assert table in existing, f"missing table {table}"


def test_table_names_matches_schema() -> None:
    assert set(TABLE_NAMES) == {
        "airports",
        "runways",
        "airport_month",
        "airport_year",
        "routes_month",
        "otp_taxi_hist",
        "otp_peak",
        "taf_history",
        "taf_forecast",
        "npias",
        "aip_grants",
        "catchment",
        "financials",
        "od_share",
        "curated_facts",
        "curated_inputs",
        "source_vintage",
        "airport_metrics",
    }


EXPECTED_COLUMNS: dict[str, set[str]] = {
    "airports": {
        "iata", "icao", "faa_locid", "name", "city", "state", "faa_region", "hub_size",
        "lat", "lon", "cbsa_code", "cbsa_name", "commercial", "source_id", "vintage",
    },
    "runways": {
        "faa_locid", "runway_id", "length_ft", "width_ft", "surface", "closed",
        "source_id", "vintage",
    },
    "airport_month": {"iata", "period", "measure", "value", "source_id", "vintage"},
    "airport_year": {"iata", "year", "measure", "value", "source_id", "vintage"},
    "routes_month": {
        "iata", "dest", "dest_name", "period", "carrier", "distance_mi", "departures",
        "seats", "passengers", "freight_lb", "mail_lb", "is_international", "aircraft_config",
        "source_id", "vintage",
    },
    "otp_taxi_hist": {"iata", "period", "minute_bucket", "n", "source_id", "vintage"},
    "otp_peak": {"iata", "period", "p95_hourly_ops", "max_hourly_ops", "source_id", "vintage"},
    "taf_history": {"faa_locid", "year", "enplanements", "ops_total", "source_id", "vintage"},
    "taf_forecast": {"faa_locid", "year", "enplanements", "ops_total", "source_id", "vintage"},
    "npias": {
        "faa_locid", "hub", "enplanements", "dev_estimate_usd", "capacity_label",
        "capacity_label_text", "source_id", "vintage",
    },
    "aip_grants": {"faa_locid", "fy", "amount_usd", "source_id", "vintage"},
    "catchment": {
        "iata", "cbsa_code", "cbsa_name", "year", "population", "gdp_real_usd",
        "source_id", "vintage",
    },
    "financials": {
        "faa_locid", "fy", "hub_size", "cpe_usd", "nonaero_revenue_usd", "enplanements",
        "source_id", "vintage",
    },
    "od_share": {"iata", "year", "od_pax", "total_pax", "source_id", "vintage"},
    "curated_facts": {
        "iata", "category", "text", "value", "source_url", "as_of", "expires",
        "source_id", "vintage",
    },
    "curated_inputs": {"iata", "key", "value", "source_url", "as_of", "source_id", "vintage"},
    "source_vintage": {"source_id", "description", "period_start", "period_end", "fetched_at", "url"},
    "airport_metrics": {
        "iata", "metric_id", "horizon", "ref_year", "value", "period_start", "period_end",
        "quality_json", "source_id", "vintage",
    },
}


def test_schema_columns_match_plan_exactly(tmp_store: Store) -> None:
    assert set(EXPECTED_COLUMNS.keys()) == set(TABLE_NAMES)
    for table, expected_cols in EXPECTED_COLUMNS.items():
        rows = tmp_store.con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ?",
            [table],
        ).fetchall()
        actual_cols = {r[0] for r in rows}
        assert actual_cols == expected_cols, f"{table}: got {actual_cols}, expected {expected_cols}"


def test_source_id_and_vintage_present_on_every_table_except_source_vintage() -> None:
    for table, cols in EXPECTED_COLUMNS.items():
        if table == "source_vintage":
            assert "vintage" not in cols
            continue
        assert {"source_id", "vintage"} <= cols, f"{table} missing source_id/vintage"


def test_replace_rows_is_idempotent_for_same_where(tmp_store: Store) -> None:
    df1 = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-05"],
            "measure": ["total_passengers"],
            "value": [1_000_000.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-05"],
        }
    )
    where = {"source_id": "bts_otp", "period": "2026-05"}
    tmp_store.replace_rows("airport_month", df1, where=where)
    tmp_store.replace_rows("airport_month", df1, where=where)

    rows = tmp_store.con.execute(
        "SELECT iata, value FROM airport_month WHERE source_id = 'bts_otp' AND period = '2026-05'"
    ).fetchall()
    assert rows == [("BOS", 1_000_000.0)]


def test_replace_rows_only_touches_matching_where(tmp_store: Store) -> None:
    df_may = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-05"],
            "measure": ["total_passengers"],
            "value": [1.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-05"],
        }
    )
    df_june = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-06"],
            "measure": ["total_passengers"],
            "value": [2.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-06"],
        }
    )
    tmp_store.replace_rows("airport_month", df_may, where={"source_id": "bts_otp", "period": "2026-05"})
    tmp_store.replace_rows("airport_month", df_june, where={"source_id": "bts_otp", "period": "2026-06"})

    count = tmp_store.con.execute("SELECT count(*) FROM airport_month").fetchone()[0]
    assert count == 2

    # Re-running May should not disturb June's row.
    tmp_store.replace_rows("airport_month", df_may, where={"source_id": "bts_otp", "period": "2026-05"})
    count = tmp_store.con.execute("SELECT count(*) FROM airport_month").fetchone()[0]
    assert count == 2


def test_replace_rows_failed_insert_leaves_previous_rows_intact(tmp_store: Store) -> None:
    good = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-05"],
            "measure": ["total_passengers"],
            "value": [1.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-05"],
        }
    )
    where = {"source_id": "bts_otp", "period": "2026-05"}
    tmp_store.replace_rows("airport_month", good, where=where)

    bad = pd.DataFrame({"iata": ["BOS"], "not_a_real_column": ["x"]})
    with pytest.raises(duckdb.Error):
        tmp_store.replace_rows("airport_month", bad, where=where)

    rows = tmp_store.con.execute(
        "SELECT iata, value FROM airport_month WHERE source_id = 'bts_otp' AND period = '2026-05'"
    ).fetchall()
    assert rows == [("BOS", 1.0)]


def test_replace_rows_where_none_replaces_whole_table(tmp_store: Store) -> None:
    df_otp = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-05"],
            "measure": ["m"],
            "value": [1.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-05"],
        }
    )
    df_socrata = pd.DataFrame(
        {
            "iata": ["JFK"],
            "period": ["2026-06"],
            "measure": ["m"],
            "value": [2.0],
            "source_id": ["bts_socrata"],
            "vintage": ["2026-06"],
        }
    )
    tmp_store.replace_rows("airport_month", df_otp, where={"source_id": "bts_otp", "period": "2026-05"})
    tmp_store.replace_rows(
        "airport_month", df_socrata, where={"source_id": "bts_socrata", "period": "2026-06"}
    )
    assert tmp_store.con.execute("SELECT count(*) FROM airport_month").fetchone()[0] == 2

    # where=None is an explicit contract: it wipes the whole table (both sources'
    # rows), then inserts only df_otp.
    tmp_store.replace_rows("airport_month", df_otp, where=None)
    rows = tmp_store.con.execute("SELECT iata FROM airport_month").fetchall()
    assert rows == [("BOS",)]


def test_replace_rows_empty_df_is_pure_delete_for_partition(tmp_store: Store) -> None:
    df = pd.DataFrame(
        {
            "iata": ["BOS"],
            "period": ["2026-05"],
            "measure": ["m"],
            "value": [1.0],
            "source_id": ["bts_otp"],
            "vintage": ["2026-05"],
        }
    )
    where = {"source_id": "bts_otp", "period": "2026-05"}
    tmp_store.replace_rows("airport_month", df, where=where)
    assert tmp_store.con.execute("SELECT count(*) FROM airport_month").fetchone()[0] == 1

    tmp_store.replace_rows("airport_month", pd.DataFrame(columns=df.columns), where=where)
    assert tmp_store.con.execute("SELECT count(*) FROM airport_month").fetchone()[0] == 0


def test_replace_rows_unknown_table_raises(tmp_store: Store) -> None:
    with pytest.raises(ValueError):
        tmp_store.replace_rows("not_a_table", pd.DataFrame({"a": [1]}))


def test_upsert_vintage_overwrites(tmp_store: Store) -> None:
    v1 = SourceVintage(
        source_id="ourairports",
        description="OurAirports airports+runways",
        period_start="2026-08",
        period_end="2026-08",
        fetched_at=datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
        url="https://davidmegginson.github.io/ourairports-data/airports.csv",
    )
    tmp_store.upsert_vintage(v1)
    v2 = v1.model_copy(update={"fetched_at": datetime(2026, 8, 15, tzinfo=UTC).isoformat()})
    tmp_store.upsert_vintage(v2)

    vintages = tmp_store.vintages()
    assert len(vintages) == 1
    assert vintages[0].source_id == "ourairports"
    assert vintages[0].fetched_at == v2.fetched_at


def test_table_names_returns_list(tmp_store: Store) -> None:
    assert tmp_store.table_names() == list(TABLE_NAMES)


# geo

BOS = (42.3656, -71.0096)
JFK = (40.6413, -73.7781)


def test_haversine_bos_jfk_within_tolerance() -> None:
    dist = haversine_mi(*BOS, *JFK)
    assert 184 <= dist <= 190


# sources config

EXPECTED_CADENCE_DAYS = {
    "ourairports": 1,
    "faa_taf": 365,
    "faa_npias": 730,
    "bts_socrata": 30,
    "bts_t100": 90,
    "bts_otp": 60,
    "bts_delay_cause": 60,
    "census_cbsa": 365,
    "bea_msa": 365,
    "faa_cats": 365,
    "faa_aip": 365,
    "faa_nasstatus": 0,
    "curated": 0,
    "bts_db1b": 90,
}


def test_load_sources_has_expected_ids_and_cadences() -> None:
    sources = load_sources()
    assert set(sources.keys()) == set(EXPECTED_CADENCE_DAYS.keys())
    for source_id, cadence in EXPECTED_CADENCE_DAYS.items():
        cfg = sources[source_id]
        assert isinstance(cfg, SourceConfig)
        assert cfg.id == source_id
        assert cfg.cadence_days == cadence
        assert cfg.url
        assert cfg.kind in ("bulk", "live")


def test_load_sources_faa_nasstatus_is_live() -> None:
    sources = load_sources()
    assert sources["faa_nasstatus"].kind == "live"


def test_load_sources_bts_otp_has_otp_months() -> None:
    sources = load_sources()
    # Trailing 12 months only — see the otp_months note in config/sources.yaml.
    assert sources["bts_otp"].otp_months == 12


def test_load_sources_from_explicit_path(tmp_path) -> None:
    p = tmp_path / "sources.yaml"
    p.write_text(
        "demo:\n"
        "  kind: bulk\n"
        "  url: https://example.com/data.csv\n"
        "  cadence_days: 7\n"
        "  description: demo source\n",
        encoding="utf-8",
    )
    sources = load_sources(p)
    assert list(sources.keys()) == ["demo"]
    assert sources["demo"].notes == ""
