"""P5 Financeability & Pipeline derived metrics.

`aip_per_enpl_10y` (FAA AIP), `cpe_usd`/`nonaero_rev_per_enpl` (FAA CATS Form 127) are
documented-missing — both sources cut by the 2026-08-16 RESCOPE — see `MISSING_REASONS`
in `derived/__init__.py`.
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
    df["period_start"] = "2025"
    df["period_end"] = "2029"
    df["quality_json"] = common.quality_json([])
    return df[["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"]]
