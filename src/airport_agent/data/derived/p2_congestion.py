"""P2 Congestion & Physical Constraint derived metrics.

`nas_delay_share` is documented-missing (no BTS Delay Cause adapter landed) — see
`MISSING_REASONS` in `derived/__init__.py`.
"""
from __future__ import annotations

import pandas as pd

from airport_agent.data.derived import common


def _otp_latest_period(con, table: str = "airport_month", measure: str | None = "dep_count") -> str | None:
    """OTP's own latest period, read from its own data — never Socrata's `latest_period`.

    OTP and Socrata are refreshed independently and do not share a publication cadence
    (verified: OTP's own latest month has been observed both ahead of and behind Socrata's
    — see `adapters/bts_otp.py`/`adapters/bts_socrata.py` docstrings); anchoring the OTP
    12m window on Socrata's latest month would silently drop or shift real OTP data.
    """
    if measure is not None:
        row = con.execute(f"SELECT MAX(period) FROM {table} WHERE measure = ?", [measure]).fetchone()  # noqa: S608
    else:
        row = con.execute(f"SELECT MAX(period) FROM {table}").fetchone()  # noqa: S608
    return row[0] if row and row[0] else None


def _is_otp_current_year(con, ref_year: int, table: str = "airport_month", measure: str | None = "dep_count") -> str | None:
    """OTP's own latest period, if it falls in `ref_year`; else `None` (nothing to compute).

    OTP is ingested for the trailing 12 months only (no multi-year history), so there is
    exactly one meaningful window — this gates every OTP-sourced 12m function to compute it
    only once, under whichever `ref_year` it actually belongs to.
    """
    latest = _otp_latest_period(con, table, measure)
    if latest is None or int(latest.split("-")[0]) != ref_year:
        return None
    return latest


def pct_arr_delay_gt15(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    """OTP is ingested for the trailing 12 months only, so 3y is None — not computed and not
    flagged-partial. The horizon is dropped outright rather than mislabeled."""
    if horizon != "12m":
        return pd.DataFrame()
    otp_end = _is_otp_current_year(con, ref_year, measure="arrivals")
    if otp_end is None:
        return pd.DataFrame()
    start, end = common.window_months("12m", otp_end)
    late = common.sum_airport_month(con, "arr_late15", start, end)
    arr = common.sum_airport_month(con, "arrivals", start, end)
    merged = late.merge(arr, on="iata", suffixes=("_late", "_arr"), how="right")
    merged["value_late"] = merged["value_late"].fillna(0.0)
    rows = []
    for r in merged.itertuples():
        if not r.value_arr or r.value_arr <= 0:
            continue
        v = r.value_late / r.value_arr
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_otp",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def avg_dep_delay_min(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    """Same 12m-only rule as `pct_arr_delay_gt15` (OTP holds no multi-year history)."""
    if horizon != "12m":
        return pd.DataFrame()
    otp_end = _is_otp_current_year(con, ref_year, measure="dep_count")
    if otp_end is None:
        return pd.DataFrame()
    start, end = common.window_months("12m", otp_end)
    total = common.sum_airport_month(con, "dep_delay_min_sum", start, end)
    count = common.sum_airport_month(con, "dep_count", start, end)
    merged = total.merge(count, on="iata", suffixes=("_min", "_n"))
    rows = []
    for r in merged.itertuples():
        if not r.value_n or r.value_n <= 0:
            continue
        v = r.value_min / r.value_n
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_otp",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def taxi_out_p80_min(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    otp_end = _is_otp_current_year(con, ref_year, table="otp_taxi_hist", measure=None)
    if otp_end is None:
        return pd.DataFrame()
    start, end = common.window_months("12m", otp_end)
    hist = con.execute(
        """
        SELECT iata, minute_bucket, SUM(n) AS n FROM otp_taxi_hist
        WHERE period BETWEEN ? AND ? GROUP BY iata, minute_bucket ORDER BY iata, minute_bucket
        """,
        [start, end],
    ).df()
    rows = []
    for iata, g in hist.groupby("iata"):
        g = g.sort_values("minute_bucket")
        total = g["n"].sum()
        if total <= 0:
            continue
        cum = 0.0
        p80 = None
        for _, row in g.iterrows():
            cum += row["n"]
            if cum >= 0.8 * total:
                p80 = row["minute_bucket"]
                break
        if p80 is None:
            continue
        rows.append(
            dict(
                iata=iata,
                value=float(p80),
                period_start=start,
                period_end=end,
                source_id="bts_otp",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def ops_per_runway(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    ops = con.execute(
        """
        SELECT a.iata, th.ops_total, th.year, th.source_id, th.vintage
        FROM airports a JOIN taf_history th ON a.faa_locid = th.faa_locid
        WHERE th.year <= ? AND th.ops_total IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY a.iata ORDER BY th.year DESC) = 1
        """,
        [ref_year],
    ).df()
    rw = con.execute(
        """
        SELECT a.iata, COUNT(*) AS n
        FROM airports a JOIN runways r ON a.faa_locid = r.faa_locid
        WHERE r.closed = FALSE
        GROUP BY a.iata
        """
    ).df()
    merged = ops.merge(rw, on="iata")
    rows = []
    for r in merged.itertuples():
        if not r.n or r.n <= 0:
            continue
        v = r.ops_total / r.n
        period = str(int(r.year))
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=period,
                period_end=period,
                source_id=r.source_id,
                vintage=r.vintage,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def npias_capacity_label(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT a.iata, n.capacity_label AS value, n.source_id, n.vintage
        FROM airports a JOIN npias n ON a.faa_locid = n.faa_locid
        WHERE n.capacity_label IS NOT NULL
        """
    ).df()
    if df.empty:
        return df
    df = df.copy()
    df["value"] = df["value"].astype(float)
    df["period_start"], df["period_end"] = common.NPIAS_PLAN_PERIOD
    df["quality_json"] = common.quality_json([])
    return df[["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"]]


def peak_hour_ops_ratio(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    otp_end = _is_otp_current_year(con, ref_year, table="otp_peak", measure=None)
    if otp_end is None:
        return pd.DataFrame()
    start, end = common.window_months("12m", otp_end)
    peak = con.execute(
        "SELECT iata, MEDIAN(p95_hourly_ops) AS med FROM otp_peak WHERE period BETWEEN ? AND ? GROUP BY iata",
        [start, end],
    ).df()
    vmc = con.execute("SELECT iata, value AS vmc FROM curated_inputs WHERE key = 'declared_rate_vmc'").df()
    merged = peak.merge(vmc, on="iata")
    flags = [
        {
            "code": "otp_reporting_carriers_only",
            "message": "Peak ops from OTP-reporting carriers only; undercounts cargo/regional traffic",
        }
    ]
    rows = []
    for r in merged.itertuples():
        if not r.vmc or r.vmc <= 0:
            continue
        v = r.med / r.vmc
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_otp",
                vintage=end,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def pax_per_gate(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    enpl = common.annual_enplanements(con, ref_year, latest_period)
    gates = con.execute("SELECT iata, value AS gates FROM curated_inputs WHERE key = 'gates'").df()
    merged = enpl.merge(gates, on="iata")
    period = common.period_for_ref_year(ref_year, latest_period)
    rows = []
    for r in merged.itertuples():
        if not r.gates or r.gates <= 0:
            continue
        v = 2 * r.value / r.gates
        flags = [
            {
                "code": "total_pax_estimated_2x",
                "message": "Total pax approximated as 2x enplanements (Socrata reports departing pax only)",
            }
        ]
        if r.quality_code == "partial_year":
            flags.append({"code": "partial_year", "message": "current year incomplete; trailing 12m used"})
        elif r.quality_code == "taf_actual":
            flags.append({"code": "taf_actual", "message": "enplanements from FAA TAF actuals, not Socrata"})
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=period,
                period_end=period,
                source_id=r.source_id,
                vintage=period,
                quality_json=common.quality_json(flags),
            )
        )
    return pd.DataFrame(rows)


def deps_per_gate_day(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    end = common.period_for_ref_year(ref_year, latest_period)
    start, end = common.window_months("12m", end)
    deps = con.execute(
        "SELECT iata, SUM(departures) AS deps FROM routes_month WHERE period BETWEEN ? AND ? AND seats > 0 "
        "GROUP BY iata",
        [start, end],
    ).df()
    gates = con.execute("SELECT iata, value AS gates FROM curated_inputs WHERE key = 'gates'").df()
    merged = deps.merge(gates, on="iata")
    rows = []
    for r in merged.itertuples():
        if not r.gates or r.gates <= 0:
            continue
        v = r.deps / r.gates / 365.0
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=start,
                period_end=end,
                source_id="bts_t100",
                vintage=end,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def imc_capacity_ratio(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT vmc.iata, vmc.value AS vmc, imc.value AS imc, vmc.as_of AS as_of
        FROM curated_inputs vmc JOIN curated_inputs imc
          ON vmc.iata = imc.iata AND vmc.key = 'declared_rate_vmc' AND imc.key = 'declared_rate_imc'
        """
    ).df()
    rows = []
    for r in df.itertuples():
        if not r.vmc or r.vmc <= 0:
            continue
        v = r.imc / r.vmc
        # A static curated fact has no trailing window; its "period" is the single point in
        # time the FAA capacity profile was published (as_of). Every airport_metrics row
        # carries a period, so None is not an option here.
        rows.append(
            dict(
                iata=r.iata,
                value=v,
                period_start=r.as_of,
                period_end=r.as_of,
                source_id="curated",
                vintage=r.as_of,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)


def slot_or_cap_flag(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    df = con.execute("SELECT iata, value, as_of FROM curated_inputs WHERE key = 'slot_or_cap_flag'").df()
    if df.empty:
        return df
    df = df.copy()
    df["period_start"] = df["as_of"]
    df["period_end"] = df["as_of"]
    df["source_id"] = "curated"
    df["vintage"] = df["as_of"]
    df["quality_json"] = common.quality_json([])
    return df[["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"]]
