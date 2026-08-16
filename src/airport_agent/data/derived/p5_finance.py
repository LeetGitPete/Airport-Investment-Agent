"""P5 Financeability & Pipeline derived metrics.

`cpe_usd`/`nonaero_rev_per_enpl` (FAA CATS Form 127) are documented-missing — no adapter
landed for that source. See `MISSING_REASONS` in `derived/__init__.py`.
"""
from __future__ import annotations

import pandas as pd

from airport_agent.data.derived import common


def npias_dev_per_enpl(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT a.iata, n.dev_estimate_usd, n.enplanements, n.source_id, n.vintage
        FROM airports a JOIN npias n ON a.faa_locid = n.faa_locid
        WHERE n.dev_estimate_usd IS NOT NULL AND n.enplanements IS NOT NULL AND n.enplanements > 0
        """
    ).df()
    if df.empty:
        return df
    df = df.copy()
    df["value"] = df["dev_estimate_usd"] / df["enplanements"]
    df["period_start"], df["period_end"] = common.NPIAS_PLAN_PERIOD
    df["quality_json"] = common.quality_json([])
    return df[["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"]]


def aip_per_enpl_10y(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    """Σ`aip_grants.amount_usd` for FY in `[ref_year-9, ref_year]`, per `ref_year` enplanement."""
    fy_start, fy_end = ref_year - 9, ref_year
    grants = con.execute(
        """
        SELECT a.iata, SUM(g.amount_usd) AS total_amount
        FROM airports a JOIN aip_grants g ON a.faa_locid = g.faa_locid
        WHERE g.fy BETWEEN ? AND ?
        GROUP BY a.iata
        """,
        [fy_start, fy_end],
    ).df()
    if grants.empty:
        return grants
    enpl = common.annual_enplanements(con, ref_year, latest_period)[["iata", "value"]]
    merged = grants.merge(enpl, on="iata")
    period = common.period_for_ref_year(ref_year, latest_period)
    rows = []
    for r in merged.itertuples():
        if not r.value or r.value <= 0:
            continue
        rows.append(
            dict(
                iata=r.iata,
                value=r.total_amount / r.value,
                period_start=str(fy_start),
                period_end=str(fy_end),
                source_id="faa_aip",
                vintage=period,
                quality_json=common.quality_json([]),
            )
        )
    return pd.DataFrame(rows)
