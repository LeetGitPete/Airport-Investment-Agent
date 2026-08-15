"""DuckDB-backed store: schema, provenance-tagged writes, vintage bookkeeping.

Every raw table carries `source_id TEXT, vintage TEXT` (the frozen provenance
contract — see docs/design/01-data-layer.md). `Store.replace_rows` deletes rows
matching a `where` dict then inserts the replacement rows, making writes
idempotent per (source, period) or similar key.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from airport_agent.contracts.models import SourceVintage

_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS airports (
        iata TEXT PRIMARY KEY,
        icao TEXT,
        faa_locid TEXT,
        name TEXT,
        city TEXT,
        state TEXT,
        faa_region TEXT,
        hub_size TEXT,
        lat DOUBLE,
        lon DOUBLE,
        cbsa_code TEXT,
        cbsa_name TEXT,
        commercial BOOLEAN,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runways (
        faa_locid TEXT,
        runway_id TEXT,
        length_ft INTEGER,
        width_ft INTEGER,
        surface TEXT,
        closed BOOLEAN,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS airport_month (
        iata TEXT,
        period TEXT,
        measure TEXT,
        value DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS airport_year (
        iata TEXT,
        year INTEGER,
        measure TEXT,
        value DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routes_month (
        iata TEXT,
        dest TEXT,
        dest_name TEXT,
        period TEXT,
        carrier TEXT,
        distance_mi DOUBLE,
        departures INTEGER,
        seats INTEGER,
        passengers INTEGER,
        freight_lb DOUBLE,
        mail_lb DOUBLE,
        is_international BOOLEAN,
        aircraft_config TEXT,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS otp_taxi_hist (
        iata TEXT,
        period TEXT,
        minute_bucket INTEGER,
        n INTEGER,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS otp_peak (
        iata TEXT,
        period TEXT,
        p95_hourly_ops DOUBLE,
        max_hourly_ops INTEGER,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taf_history (
        faa_locid TEXT,
        year INTEGER,
        enplanements DOUBLE,
        ops_total DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taf_forecast (
        faa_locid TEXT,
        year INTEGER,
        enplanements DOUBLE,
        ops_total DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS npias (
        faa_locid TEXT,
        hub TEXT,
        enplanements DOUBLE,
        dev_estimate_usd DOUBLE,
        capacity_label INTEGER,
        capacity_label_text TEXT,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aip_grants (
        faa_locid TEXT,
        fy INTEGER,
        amount_usd DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catchment (
        iata TEXT,
        cbsa_code TEXT,
        cbsa_name TEXT,
        year INTEGER,
        population DOUBLE,
        gdp_real_usd DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financials (
        faa_locid TEXT,
        fy INTEGER,
        hub_size TEXT,
        cpe_usd DOUBLE,
        nonaero_revenue_usd DOUBLE,
        enplanements DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS od_share (
        iata TEXT,
        year INTEGER,
        od_pax DOUBLE,
        total_pax DOUBLE,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS curated_facts (
        iata TEXT,
        category TEXT,
        text TEXT,
        value TEXT,
        source_url TEXT,
        as_of TEXT,
        expires TEXT,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS curated_inputs (
        iata TEXT,
        key TEXT,
        value DOUBLE,
        source_url TEXT,
        as_of TEXT,
        source_id TEXT,
        vintage TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_vintage (
        source_id TEXT PRIMARY KEY,
        description TEXT,
        period_start TEXT,
        period_end TEXT,
        fetched_at TEXT,
        url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS airport_metrics (
        iata TEXT,
        metric_id TEXT,
        horizon TEXT,
        ref_year INTEGER,
        value DOUBLE,
        period_start TEXT,
        period_end TEXT,
        quality_json TEXT,
        source_id TEXT,
        vintage TEXT
    )
    """,
]

TABLE_NAMES: tuple[str, ...] = (
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
)


class Store:
    """Owns one DuckDB connection and its schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path), read_only=False)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        for statement in _SCHEMA_STATEMENTS:
            self.con.execute(statement)

    def table_names(self) -> list[str]:
        return list(TABLE_NAMES)

    def replace_rows(self, table: str, df: pd.DataFrame, where: dict[str, Any] | None = None) -> None:
        """Delete rows matching `where` (all rows if None) then insert `df` — idempotent per key."""
        if table not in TABLE_NAMES:
            raise ValueError(f"unknown table: {table}")
        if where:
            clause = " AND ".join(f"{col} = ?" for col in where)
            self.con.execute(f"DELETE FROM {table} WHERE {clause}", list(where.values()))
        else:
            self.con.execute(f"DELETE FROM {table}")
        if len(df) == 0:
            return
        self.con.register("_replace_rows_df", df)
        columns = ", ".join(df.columns)
        self.con.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM _replace_rows_df")
        self.con.unregister("_replace_rows_df")

    def upsert_vintage(self, v: SourceVintage) -> None:
        self.con.execute(
            """
            INSERT INTO source_vintage (source_id, description, period_start, period_end, fetched_at, url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_id) DO UPDATE SET
                description = excluded.description,
                period_start = excluded.period_start,
                period_end = excluded.period_end,
                fetched_at = excluded.fetched_at,
                url = excluded.url
            """,
            [v.source_id, v.description, v.period_start, v.period_end, v.fetched_at, v.url],
        )

    def vintages(self) -> list[SourceVintage]:
        rows = self.con.execute(
            "SELECT source_id, description, period_start, period_end, fetched_at, url FROM source_vintage"
        ).fetchall()
        return [
            SourceVintage(
                source_id=r[0],
                description=r[1],
                period_start=r[2],
                period_end=r[3],
                fetched_at=r[4],
                url=r[5],
            )
            for r in rows
        ]

    def close(self) -> None:
        self.con.close()
