"""The derived-metrics registry: `METRIC_FUNCS`, `build_derived`, `assert_registry_covered`.

`build_derived(store, years=None)` is exactly the frozen registry (`config/metrics.yaml`),
one function per tier A/B metric id, run at every horizon the id declares, and written to
`airport_metrics`. `assert_registry_covered` fails the build if a tier A/B id has no function
at all; an id whose source never landed still has a function — it returns zero rows, always,
with the reason recorded in `MISSING_REASONS`.
"""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from airport_agent.contracts.registry import load_registry
from airport_agent.data.derived import p1_demand, p2_congestion, p3_market, p4_economy, p5_finance
from airport_agent.data.store import Store

MetricFn = Callable[..., pd.DataFrame]

#: Tier A/B ids whose source never landed, so the function below always returns zero rows.
#: Each reason is the durable one — why the data does not exist here, not when it was dropped.
#: See docs/design/known-limitations-and-tradeoffs.md for the decisions behind them.
MISSING_REASONS: dict[str, str] = {
    "nas_delay_share": "No BTS Delay Cause adapter: nothing in the snapshot attributes delay minutes to the NAS.",
    "cpe_usd": "No FAA CATS Form 127 adapter: airport financials were never ingested.",
    "nonaero_rev_per_enpl": "No FAA CATS Form 127 adapter: airport financials were never ingested.",
    "od_share": "The BTS DB1B adapter did not land (design 01 open item), so O&D share is unknown.",
    "msa_gdp_per_capita": (
        "BEA publishes no keyless-bulk MSA real-GDP table (MARPP is MSA personal income/price parity, "
        "not GDP; only State and County GDP zips exist)."
    ),
    "msa_gdp_cagr_5y": (
        "BEA publishes no keyless-bulk MSA real-GDP table (MARPP is MSA personal income/price parity, "
        "not GDP; only State and County GDP zips exist)."
    ),
}


def _missing(reason: str) -> MetricFn:
    """A stub derived-metric function for an id whose source was cut: always zero rows."""

    def _fn(con, horizon: str, ref_year: int, latest_period: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["iata", "value", "period_start", "period_end", "source_id", "vintage", "quality_json"])

    _fn.__doc__ = reason
    return _fn


#: One function per tier A/B registry id.
METRIC_FUNCS: dict[str, MetricFn] = {
    # P1 Demand Pressure
    "enpl_cagr_3y": p1_demand.enpl_cagr_3y,
    "enpl_cagr_5y": p1_demand.enpl_cagr_5y,
    "enpl_cagr_10y": p1_demand.enpl_cagr_10y,
    "taf_cagr_10y": p1_demand.taf_cagr_10y,
    "taf_vs_actual_gap": p1_demand.taf_vs_actual_gap,
    "load_factor": p1_demand.load_factor,
    "spill_proxy": p1_demand.spill_proxy,
    "seats_per_dep_trend": p1_demand.seats_per_dep_trend,
    "pax_per_capita": p1_demand.pax_per_capita,
    # P2 Congestion & Physical Constraint
    "pct_arr_delay_gt15": p2_congestion.pct_arr_delay_gt15,
    "avg_dep_delay_min": p2_congestion.avg_dep_delay_min,
    "nas_delay_share": _missing(MISSING_REASONS["nas_delay_share"]),
    "taxi_out_p80_min": p2_congestion.taxi_out_p80_min,
    "ops_per_runway": p2_congestion.ops_per_runway,
    "npias_capacity_label": p2_congestion.npias_capacity_label,
    "peak_hour_ops_ratio": p2_congestion.peak_hour_ops_ratio,
    "pax_per_gate": p2_congestion.pax_per_gate,
    "deps_per_gate_day": p2_congestion.deps_per_gate_day,
    "imc_capacity_ratio": p2_congestion.imc_capacity_ratio,
    "slot_or_cap_flag": p2_congestion.slot_or_cap_flag,
    # P3 Market Quality
    "carrier_hhi": p3_market.carrier_hhi,
    "top_carrier_share": p3_market.top_carrier_share,
    "intl_pax_share": p3_market.intl_pax_share,
    "longhaul_dep_share": p3_market.longhaul_dep_share,
    "route_count_nonstop": p3_market.route_count_nonstop,
    "competing_seats_100mi": p3_market.competing_seats_100mi,
    "od_share": _missing(MISSING_REASONS["od_share"]),
    # P4 Economic Base
    "cbsa_population": p4_economy.cbsa_population,
    "cbsa_pop_cagr_5y": p4_economy.cbsa_pop_cagr_5y,
    "msa_gdp_per_capita": _missing(MISSING_REASONS["msa_gdp_per_capita"]),
    "msa_gdp_cagr_5y": _missing(MISSING_REASONS["msa_gdp_cagr_5y"]),
    # P5 Financeability & Pipeline
    "npias_dev_per_enpl": p5_finance.npias_dev_per_enpl,
    "aip_per_enpl_10y": p5_finance.aip_per_enpl_10y,
    "cpe_usd": _missing(MISSING_REASONS["cpe_usd"]),
    "nonaero_rev_per_enpl": _missing(MISSING_REASONS["nonaero_rev_per_enpl"]),
}

_AIRPORT_METRICS_COLUMNS: tuple[str, ...] = (
    "iata",
    "metric_id",
    "horizon",
    "ref_year",
    "value",
    "period_start",
    "period_end",
    "quality_json",
    "source_id",
    "vintage",
)

#: `ref_year` sentinel meaning "the current/latest value".
CURRENT_REF_YEAR = 9999

#: First calendar year in the derived series (Socrata's earliest complete history).
SERIES_START_YEAR = 2016


def _latest_period(con) -> str | None:
    """Latest `YYYY-MM` with `bts_socrata` traffic data — the anchor for `ref_year` ranges."""
    row = con.execute("SELECT MAX(period) FROM airport_month WHERE measure = 'total_passengers'").fetchone()
    return row[0] if row else None


def assert_registry_covered(specs: list | None = None) -> None:
    """Raise `AssertionError` if a tier A/B registry id has no entry in `METRIC_FUNCS`.

    Ids in `MISSING_REASONS` still have a (stub) function, so they pass this check; they
    are allowed to yield zero rows (mirrors the frozen contract suite's `od_share` rule).
    """
    specs = specs if specs is not None else load_registry()
    ab_ids = {s.id for s in specs if s.tier in ("A", "B")}
    missing_fn = ab_ids - set(METRIC_FUNCS)
    if missing_fn:
        raise AssertionError(f"derived metric function(s) missing for tier A/B id(s): {sorted(missing_fn)}")
    stray = set(MISSING_REASONS) - ab_ids
    if stray:
        raise AssertionError(f"MISSING_REASONS references id(s) not in the tier A/B registry: {sorted(stray)}")


def build_derived(store: Store, years: range | None = None) -> dict[str, int]:
    """Rebuild `airport_metrics` for every tier A/B registry id; return `{metric_id: row_count}`.

    For each id, runs its function at every horizon the registry declares. Horizon-scoped
    ids (12m/3y/5y/10y) are computed for every `ref_year` in `years` (default
    `range(2016, latest_year+1)`); the latest `ref_year` that produced any rows is also
    written again at `ref_year=9999` ("current"). Horizon-invariant
    ids (static/forecast) are computed once and written only at `ref_year=9999` (no time
    series: `get_metric_series` returns `[]` for these per the contract).
    """
    con = store.con
    assert_registry_covered()
    latest_period = _latest_period(con)
    if latest_period is None:
        return {}
    latest_year = int(latest_period.split("-")[0])
    yrs = list(years) if years is not None else list(range(SERIES_START_YEAR, latest_year + 1))

    specs = {s.id: s for s in load_registry() if s.tier in ("A", "B")}
    metric_ids = list(specs)
    placeholders = ",".join("?" for _ in metric_ids)
    con.execute(f"DELETE FROM airport_metrics WHERE metric_id IN ({placeholders})", metric_ids)  # noqa: S608

    row_counts: dict[str, int] = {}
    all_frames: list[pd.DataFrame] = []
    for metric_id, spec in specs.items():
        fn = METRIC_FUNCS[metric_id]
        count = 0
        for horizon in spec.horizons:
            if horizon in ("static", "forecast"):
                df = fn(con, horizon, latest_year, latest_period)
                if df is not None and not df.empty:
                    df = df.copy()
                    df["metric_id"] = metric_id
                    df["horizon"] = horizon
                    df["ref_year"] = CURRENT_REF_YEAR
                    all_frames.append(df)
                    count += len(df)
                continue
            year_frames: dict[int, pd.DataFrame] = {}
            for ref_year in yrs:
                df = fn(con, horizon, ref_year, latest_period)
                if df is None or df.empty:
                    continue
                df = df.copy()
                df["metric_id"] = metric_id
                df["horizon"] = horizon
                df["ref_year"] = ref_year
                year_frames[ref_year] = df
                all_frames.append(df)
                count += len(df)
            if year_frames:
                latest_available = max(year_frames)
                current = year_frames[latest_available].copy()
                current["ref_year"] = CURRENT_REF_YEAR
                all_frames.append(current)
                count += len(current)
        row_counts[metric_id] = count
        print(f"[build_derived] {metric_id}: {count} rows")  # noqa: T201 (pipeline progress, not logging infra)

    if all_frames:
        out = pd.concat(all_frames, ignore_index=True)[list(_AIRPORT_METRICS_COLUMNS)]
        con.register("_derived_rows", out)
        try:
            con.execute(
                "INSERT INTO airport_metrics "
                "(iata, metric_id, horizon, ref_year, value, period_start, period_end, quality_json, "
                "source_id, vintage) SELECT * FROM _derived_rows"
            )
        finally:
            con.unregister("_derived_rows")
    return row_counts


__all__ = ["CURRENT_REF_YEAR", "METRIC_FUNCS", "MISSING_REASONS", "assert_registry_covered", "build_derived"]
