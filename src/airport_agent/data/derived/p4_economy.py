"""P4 Economic Base derived metrics.

`msa_gdp_per_capita`/`msa_gdp_cagr_5y` are documented-missing (no BEA source — the
2026-08-16 RESCOPE kept `census_cbsa` for population/centroids only) — see
`MISSING_REASONS` in `derived/__init__.py`.
"""
from __future__ import annotations

import pandas as pd

from airport_agent.data.derived import common

_CBSA_PROXY_FLAG = [{"code": "cbsa_proxy", "message": "CBSA population is a proxy for true catchment"}]


def cbsa_population(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT iata, population AS value, year, source_id, vintage
        FROM catchment WHERE year <= ? AND population IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY iata ORDER BY year DESC) = 1
        """,
        [ref_year],
    ).df()
    if df.empty:
        return df
    df = df.copy()
    df["period_start"] = df["year"].astype(int).astype(str)
    df["period_end"] = df["period_start"]
    df["quality_json"] = common.quality_json(_CBSA_PROXY_FLAG)
    return df[["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"]]


def cbsa_pop_cagr_5y(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
    def _pop_at(year: int) -> pd.Series:
        df = con.execute(
            "SELECT iata, population FROM catchment WHERE year = ? AND population IS NOT NULL", [year]
        ).df()
        return df.set_index("iata")["population"]

    new, old = _pop_at(ref_year), _pop_at(ref_year - 5)
    idx = new.index.intersection(old.index)
    rows = []
    for iata in idx:
        v = common.cagr(new[iata], old[iata], 5)
        if v is None:
            continue
        rows.append(
            dict(
                iata=iata,
                value=v,
                period_start=str(ref_year - 5),
                period_end=str(ref_year),
                source_id="census_cbsa",
                vintage=str(ref_year),
                quality_json=common.quality_json(_CBSA_PROXY_FLAG),
            )
        )
    return pd.DataFrame(rows)
