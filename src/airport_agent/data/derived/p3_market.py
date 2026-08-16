"""P3 Market Quality derived metrics.

`od_share` is documented-missing (BTS DB1B timeboxed attempt did not land) — see
`MISSING_REASONS` in `derived/__init__.py`.
"""
from __future__ import annotations

import pandas as pd

from airport_agent.data.commercial import commercial_airports
from airport_agent.data.derived import common
from airport_agent.data.geo import haversine_mi

_T100_TABLE = "routes_month"


def _carrier_pax(con, start: str, end: str) -> pd.DataFrame:
    return con.execute(
        "SELECT iata, carrier, SUM(passengers) AS pax FROM routes_month WHERE period BETWEEN ? AND ? "
        "GROUP BY iata, carrier",
        [start, end],
    ).df()


def carrier_hhi(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    df = _carrier_pax(con, start, end)
    coverage = common.window_coverage(con, _T100_TABLE, start, end) if horizon != "12m" else {}
    nominal = common.WINDOW_MONTHS[horizon]
    rows = []
    for iata, g in df.groupby("iata"):
        total = g["pax"].sum()
        if total <= 0:
            continue
        shares = g["pax"] / total
        hhi = float((shares**2).sum() * 10000)
        flags = common.partial_window_flag(coverage, iata, nominal) if horizon != "12m" else []
        rows.append(
            dict(
                iata=iata,
                value=hhi,
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def top_carrier_share(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    df = _carrier_pax(con, start, end)
    coverage = common.window_coverage(con, _T100_TABLE, start, end) if horizon != "12m" else {}
    nominal = common.WINDOW_MONTHS[horizon]
    rows = []
    for iata, g in df.groupby("iata"):
        total = g["pax"].sum()
        if total <= 0:
            continue
        v = float(g["pax"].max() / total)
        flags = common.partial_window_flag(coverage, iata, nominal) if horizon != "12m" else []
        rows.append(
            dict(
                iata=iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def intl_pax_share(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    intl = common.sum_airport_month(con, "intl_out_passengers", start, end)
    total = common.sum_airport_month(con, "total_passengers", start, end)
    merged = intl.merge(total, on="iata", suffixes=("_intl", "_tot"), how="right")
    merged["value_intl"] = merged["value_intl"].fillna(0.0)
    rows = []
    for r in merged.itertuples():
        if not r.value_tot or r.value_tot <= 0:
            continue
        v = r.value_intl / r.value_tot
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_socrata",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def longhaul_dep_share(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    df = con.execute(
        """
        SELECT iata,
               SUM(CASE WHEN distance_mi >= ? THEN departures ELSE 0 END) AS long_deps,
               SUM(departures) AS total_deps
        FROM routes_month WHERE period BETWEEN ? AND ? AND seats > 0
        GROUP BY iata
        """,
        [common.LONG_HAUL_MI, start, end],
    ).df()
    coverage = common.window_coverage(con, _T100_TABLE, start, end) if horizon != "12m" else {}
    nominal = common.WINDOW_MONTHS[horizon]
    rows = []
    for r in df.itertuples():
        if not r.total_deps or r.total_deps <= 0:
            continue
        v = float(r.long_deps / r.total_deps)
        flags = common.partial_window_flag(coverage, r.iata, nominal) if horizon != "12m" else []
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def route_count_nonstop(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    df = con.execute(
        "SELECT iata, COUNT(DISTINCT dest) AS n FROM routes_month WHERE period BETWEEN ? AND ? AND departures > 0 "
        "GROUP BY iata",
        [start, end],
    ).df()
    coverage = common.window_coverage(con, _T100_TABLE, start, end) if horizon != "12m" else {}
    nominal = common.WINDOW_MONTHS[horizon]
    rows = []
    for r in df.itertuples():
        flags = common.partial_window_flag(coverage, r.iata, nominal) if horizon != "12m" else []
        rows.append(
            dict(
                iata=r.iata,
                value=float(r.n),
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def competing_seats_100mi(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months("12m", end)
    seats = con.execute(
        "SELECT iata, SUM(seats) AS seats FROM routes_month WHERE period BETWEEN ? AND ? GROUP BY iata",
        [start, end],
    ).df()
    airports = commercial_airports(con)
    merged = airports.merge(seats, on="iata", how="left")
    merged["seats"] = merged["seats"].fillna(0.0)
    recs = merged.to_dict("records")
    rows = []
    for me in recs:
        if me["lat"] is None or me["lon"] is None or pd.isna(me["lat"]) or pd.isna(me["lon"]):
            continue
        total = 0.0
        for other in recs:
            if other["iata"] == me["iata"]:
                continue
            if other["lat"] is None or other["lon"] is None or pd.isna(other["lat"]) or pd.isna(other["lon"]):
                continue
            if haversine_mi(me["lat"], me["lon"], other["lat"], other["lon"]) <= 100.0:
                total += other["seats"]
        rows.append(
            dict(
                iata=me["iata"],
                value=float(total),
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)
