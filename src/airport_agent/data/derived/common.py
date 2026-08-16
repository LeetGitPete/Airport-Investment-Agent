"""Shared helpers for `derived/*` metric functions.

Every metric function has the signature `fn(con, horizon, ref_year, latest_period) ->
pd.DataFrame[iata, value, period_start, period_end, source_id, vintage, quality_json]`
(see `derived/__init__.py::build_derived`). `ref_year` is the calendar year the window
ends in; `latest_period` is the latest "YYYY-MM" with `bts_socrata` traffic data.

Window rule (frozen by the plan's Global Constraints, restated in
`service.py`): level metrics at horizon k are computed over the **trailing k-year
window ending at `ref_year`'s window end**; CAGR-type metrics are k-year growth between
two point-in-time values. `window_months` implements the former; `cagr` the latter.
"""
from __future__ import annotations

import json

import pandas as pd

#: Nominal window length in months per horizon (12m/3y/5y/10y only — static/forecast
#: metrics don't use a window).
WINDOW_MONTHS: dict[str, int] = {"12m": 12, "3y": 36, "5y": 60, "10y": 120}

#: Long-haul threshold in statute miles (design 02 convention: no ICAO/IATA standard exists,
#: so ">= 1,500 mi" is our stated default and every answer using it says so).
LONG_HAUL_MI = 1500.0

#: Plan period of the NPIAS edition currently ingested. NPIAS rows carry no per-row period,
#: so the edition's own span is the honest thing to stamp. Must track
#: `adapters/faa_npias.py::NPIAS_PLAN_YEARS` — bump both when the FAA publishes a new edition.
NPIAS_PLAN_PERIOD = ("2025", "2029")


def _add_months(period: str, delta: int) -> str:
    """`period` ("YYYY-MM") shifted by `delta` months (may be negative)."""
    year, month = (int(p) for p in period.split("-"))
    idx = year * 12 + (month - 1) + delta
    y2, m2 = divmod(idx, 12)
    return f"{y2:04d}-{m2 + 1:02d}"


def window_months(horizon: str, end_period: str) -> tuple[str, str]:
    """Return `(start_period, end_period)` for a horizon's trailing window ending at `end_period`."""
    n = WINDOW_MONTHS[horizon]
    return _add_months(end_period, -(n - 1)), end_period


def period_for_ref_year(ref_year: int, latest_period: str) -> str:
    """The window's end period for `ref_year`: December of that year, or `latest_period`
    itself when `ref_year` is the current (possibly incomplete) year."""
    latest_year = int(latest_period.split("-")[0])
    if ref_year >= latest_year:
        return latest_period
    return f"{ref_year:04d}-12"


def cagr(new: float | None, old: float | None, k: int) -> float | None:
    """Compound annual growth rate over `k` years; `None` if either endpoint is missing/non-positive."""
    if new is None or old is None or old <= 0 or new <= 0:
        return None
    if isinstance(new, float) and pd.isna(new):
        return None
    if isinstance(old, float) and pd.isna(old):
        return None
    return (new / old) ** (1.0 / k) - 1.0


def quality_json(flags: list[dict] | None) -> str:
    """Serialize a list of `{"code":..., "message":...}` dicts into the `quality_json` column."""
    return json.dumps(flags or [])


def sum_airport_month(con, measure: str, start: str, end: str) -> pd.DataFrame:
    """`airport_month` rows for `measure` summed over `[start, end]`; columns `iata, value`."""
    return con.execute(
        """
        SELECT iata, SUM(value) AS value
        FROM airport_month
        WHERE measure = ? AND period BETWEEN ? AND ?
        GROUP BY iata
        """,
        [measure, start, end],
    ).df()


def window_coverage(con, table: str, start: str, end: str) -> dict[str, int]:
    """`{iata: distinct months present in [start, end]}` for a monthly table (`routes_month`, `airport_month`)."""
    df = con.execute(
        f"SELECT iata, COUNT(DISTINCT period) AS n FROM {table} WHERE period BETWEEN ? AND ? GROUP BY iata",  # noqa: S608
        [start, end],
    ).df()
    return dict(zip(df["iata"], df["n"], strict=True))


def partial_window_flag(coverage: dict[str, int], iata: str, nominal_months: int) -> list[dict]:
    """A `partial_window` QualityFlag dict (as a list) if `iata`'s actual coverage is short of `nominal_months`.

    Used for T-100-sourced metrics at 3y/5y horizons when the backfilled `routes_month`
    window has fewer months than the horizon nominally implies (see known-limitations:
    T-100 backfill window). The value itself is still real — computed honestly from
    whatever months are present — this only flags that it reflects less history than
    the horizon label would suggest.
    """
    n = coverage.get(iata, 0)
    if n >= nominal_months:
        return []
    return [
        {
            "code": "partial_window",
            "message": f"only {n} of {nominal_months} months of data available in this window",
        }
    ]


def annual_enplanements(con, year: int, latest_period: str) -> pd.DataFrame:
    """Annual enplanements for `year`: columns `iata, value, source_id, quality_code`.

    Priority (plan "Derived metric definitions", `annual_enplanements`): a complete Socrata
    year first; for an incomplete year, TAF actual if present, else trailing-12m. In
    practice a genuine TAF *actual* (`taf_history`, `scenario=0`) essentially never exists
    for the current year under a live TAF edition (its base year is `>=` the current year,
    so the current year falls in `taf_forecast`, not `taf_history`) — the trailing-12m
    fallback is what actually fires for "the current year is incomplete" in this snapshot.
    The TAF-actual branch matters for a genuinely gapped *historical* year (e.g. a year
    Socrata never fully reported), which is the case it is spec'd for.

    `quality_code` is `None` (a complete Socrata year), `"taf_actual"` (TAF actual used
    because Socrata has no complete year for `year`) or `"partial_year"` (current year,
    neither of the above — trailing-12m fallback).
    """
    latest_year = int(latest_period.split("-")[0])
    socrata = con.execute(
        "SELECT iata, value FROM airport_year WHERE measure = 'enplanements' AND year = ?", [year]
    ).df()
    socrata["source_id"] = "bts_socrata"
    socrata["quality_code"] = None
    frames = [socrata]
    have = set(socrata["iata"])

    taf = con.execute(
        """
        SELECT a.iata, t.enplanements AS value
        FROM airports a JOIN taf_history t ON a.faa_locid = t.faa_locid
        WHERE t.year = ? AND t.enplanements IS NOT NULL
        """,
        [year],
    ).df()
    taf = taf[~taf["iata"].isin(have)].copy()
    taf["source_id"] = "faa_taf"
    taf["quality_code"] = "taf_actual"
    frames.append(taf)
    have = have | set(taf["iata"])

    if year == latest_year:
        start, end = window_months("12m", latest_period)
        trailing = sum_airport_month(con, "total_passengers", start, end)
        trailing = trailing[~trailing["iata"].isin(have)][["iata", "value"]].copy()
        trailing["source_id"] = "bts_socrata"
        trailing["quality_code"] = "partial_year"
        frames.append(trailing)

    out = pd.concat(frames, ignore_index=True)
    return out[out["value"].notna() & (out["value"] > 0)].reset_index(drop=True)
