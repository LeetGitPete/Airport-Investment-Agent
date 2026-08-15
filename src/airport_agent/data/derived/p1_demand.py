"""P1 Demand Pressure derived metrics: enpl_cagr_{3y,5y,10y}, taf_cagr_10y, taf_vs_actual_gap,
load_factor, spill_proxy, seats_per_dep_trend, pax_per_capita.

See plan "Derived metric definitions" table and `derived/common.py` for the window/CAGR rules.
"""
from __future__ import annotations

import functools

import pandas as pd

from airport_agent.data.derived import common


def _enpl_cagr(con, horizon: str, ref_year: int, latest_period: str, *, k: int) -> pd.DataFrame:
    new = common.annual_enplanements(con, ref_year, latest_period)
    old = common.annual_enplanements(con, ref_year - k, latest_period)
    merged = new.merge(old, on="iata", suffixes=("_new", "_old"))
    period = common.period_for_ref_year(ref_year, latest_period)
    rows = []
    for r in merged.itertuples():
        v = common.cagr(r.value_new, r.value_old, k)
        if v is None:
            continue
        flags = []
        if r.source_id_new != "bts_socrata" or r.source_id_old != "bts_socrata":
            flags.append({"code": "source_mix", "message": "one or both endpoints from TAF actuals, not Socrata"})
        if r.quality_code_new == "partial_year":
            flags.append({"code": "partial_year", "message": "current year incomplete; trailing 12m used"})
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=f"{ref_year - k}",
                period_end=period,
                source_id=r.source_id_new,
                vintage=period,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


enpl_cagr_3y = functools.partial(_enpl_cagr, k=3)
enpl_cagr_5y = functools.partial(_enpl_cagr, k=5)
enpl_cagr_10y = functools.partial(_enpl_cagr, k=10)


def taf_cagr_10y(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    base_row = con.execute("SELECT MIN(year) FROM taf_forecast").fetchone()
    base_year = base_row[0] if base_row else None
    if base_year is None:
        return pd.DataFrame()
    df = con.execute(
        """
        SELECT a.iata, f0.enplanements AS e0, f10.enplanements AS e10, f10.source_id, f10.vintage
        FROM airports a
        JOIN taf_forecast f0 ON a.faa_locid = f0.faa_locid AND f0.year = ?
        JOIN taf_forecast f10 ON a.faa_locid = f10.faa_locid AND f10.year = ?
        """,
        [base_year, base_year + 10],
    ).df()
    rows = []
    for r in df.itertuples():
        v = common.cagr(r.e10, r.e0, 10)
        if v is None:
            continue
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=str(base_year),
                period_end=str(base_year + 10),
                source_id=r.source_id,
                vintage=r.vintage,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def taf_vs_actual_gap(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    actual = common.annual_enplanements(con, ref_year, latest_period)
    taf = con.execute(
        """
        SELECT a.iata, tf.enplanements AS value, tf.source_id, tf.vintage, 1 AS is_forecast
        FROM airports a JOIN taf_forecast tf ON a.faa_locid = tf.faa_locid AND tf.year = ?
        WHERE tf.enplanements IS NOT NULL
        """,
        [ref_year],
    ).df()
    if taf.empty:
        taf = con.execute(
            """
            SELECT a.iata, th.enplanements AS value, th.source_id, th.vintage, 0 AS is_forecast
            FROM airports a JOIN taf_history th ON a.faa_locid = th.faa_locid AND th.year = ?
            WHERE th.enplanements IS NOT NULL
            """,
            [ref_year],
        ).df()
    merged = actual.merge(taf, on="iata", suffixes=("_act", "_taf"))
    period = common.period_for_ref_year(ref_year, latest_period)
    rows = []
    for r in merged.itertuples():
        if not r.value_act or r.value_act <= 0:
            continue
        v = r.value_taf / r.value_act
        flags = []
        if r.is_forecast == 0:
            flags.append(
                {"code": "taf_actual", "message": "TAF has only historical actuals for this year, not a forecast"}
            )
        if r.quality_code == "partial_year":
            flags.append({"code": "partial_year", "message": "current year incomplete; trailing 12m used"})
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=period,
                period_end=period,
                source_id=r.source_id_taf,
                vintage=r.vintage,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def load_factor(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    pax = common.sum_airport_month(con, "total_passengers", start, end)
    seats = common.sum_airport_month(con, "total_seats", start, end)
    merged = pax.merge(seats, on="iata", suffixes=("_pax", "_seats"))
    rows = []
    for r in merged.itertuples():
        if not r.value_seats or r.value_seats <= 0:
            continue
        v = r.value_pax / r.value_seats
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


#: T-100 backfill is time/size-constrained (see known-limitations); flag 3y/5y route
#: metrics computed from a shorter-than-nominal window.
_T100_TABLE = "routes_month"


def spill_proxy(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months(horizon, end)
    df = con.execute(
        """
        SELECT iata, dest, carrier, period, departures, seats, passengers
        FROM routes_month
        WHERE period BETWEEN ? AND ? AND seats > 0
        """,
        [start, end],
    ).df()
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["lf"] = df["passengers"] / df["seats"]
    stats = (
        df.groupby(["iata", "dest", "carrier"])
        .agg(n=("period", "nunique"), mean_lf=("lf", "mean"), std_lf=("lf", "std"), deps=("departures", "sum"))
        .reset_index()
    )
    stats = stats[(stats["n"] >= 6) & (stats["mean_lf"] > 0)].copy()
    stats["cv"] = stats["std_lf"].fillna(0.0) / stats["mean_lf"]
    coverage = common.window_coverage(con, _T100_TABLE, start, end) if horizon != "12m" else {}
    nominal = common.WINDOW_MONTHS[horizon]
    rows = []
    for iata, g in stats.groupby("iata"):
        total_deps = g["deps"].sum()
        if total_deps <= 0:
            continue
        v = float((g["cv"] * g["deps"]).sum() / total_deps)
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


def seats_per_dep_trend(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    def _ratio(year: int) -> pd.Series:
        df = con.execute(
            """
            SELECT iata,
                   MAX(CASE WHEN measure = 'seats' THEN value END) AS seats,
                   MAX(CASE WHEN measure = 'departures' THEN value END) AS deps
            FROM airport_year WHERE year = ? GROUP BY iata
            """,
            [year],
        ).df()
        df = df.dropna()
        df = df[df["deps"] > 0]
        return (df["seats"] / df["deps"]).set_axis(df["iata"])

    r_new, r_old = _ratio(ref_year), _ratio(ref_year - 5)
    idx = r_new.index.intersection(r_old.index)
    period_start, period_end = f"{ref_year - 5}-12", f"{ref_year}-12"
    rows = []
    for iata in idx:
        old = r_old[iata]
        if old <= 0:
            continue
        v = float(r_new[iata] / old - 1.0)
        rows.append(
            dict(
                iata=iata,
                value=v,
                period_start=period_start,
                period_end=period_end,
                source_id="bts_socrata",
                vintage=period_end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def pax_per_capita(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    enpl = common.annual_enplanements(con, ref_year, latest_period)
    pop = con.execute(
        """
        SELECT iata, population FROM catchment
        WHERE year <= ? AND population IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY iata ORDER BY year DESC) = 1
        """,
        [ref_year],
    ).df()
    merged = enpl.merge(pop, on="iata")
    period = common.period_for_ref_year(ref_year, latest_period)
    rows = []
    for r in merged.itertuples():
        if not r.population or r.population <= 0:
            continue
        v = r.value / r.population
        flags = [{"code": "cbsa_proxy", "message": "CBSA population is a proxy for true catchment"}]
        if r.quality_code == "partial_year":
            flags.append({"code": "partial_year", "message": "current year incomplete; trailing 12m used"})
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=period,
                period_end=period,
                source_id="bts_socrata",
                vintage=period,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)
