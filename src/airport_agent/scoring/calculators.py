"""Route-distance calculators (design 02 conventions): bands short<500 / medium 500-1500 / long 1500-3000 /
ultra >3000 statute miles; long-haul = >= 1,500 mi by default (adjustable). Passenger and freight separately."""
from __future__ import annotations

from airport_agent.contracts import Horizon, Metric, QualityFlag, RouteRow, RouteTable

BANDS: tuple[tuple[str, float, float], ...] = (
    ("short", 0, 500), ("medium", 500, 1500), ("long", 1500, 3000), ("ultra", 3000, float("inf")))

CONVENTION_NOTE = ("long-haul = routes >= {t:g} statute miles (no ICAO/IATA standard); passenger variant weights "
                   "departures with seats>0, freight variant weights freight lb")


def _weight(r: RouteRow, freight: bool) -> float:
    if freight:
        return float(r.freight_lb)
    return float(r.departures) if r.seats > 0 else 0.0


def distance_bands(routes: RouteTable, freight: bool = False) -> dict[str, float]:
    total = sum(_weight(r, freight) for r in routes.rows)
    out = {name: 0.0 for name, _, _ in BANDS}
    if total <= 0:
        return out
    for name, lo, hi in BANDS:
        out[name] = sum(_weight(r, freight) for r in routes.rows if lo <= r.distance_mi < hi) / total
    return out


def long_haul_share(routes: RouteTable, threshold_mi: float = 1500, freight: bool = False,
                    horizon: Horizon = "12m") -> Metric:
    total = sum(_weight(r, freight) for r in routes.rows)
    value = None if total <= 0 else sum(_weight(r, freight) for r in routes.rows
                                        if r.distance_mi >= threshold_mi) / total
    quality = [QualityFlag(code="convention", message=CONVENTION_NOTE.format(t=threshold_mi))]
    if routes.truncated:
        quality.append(QualityFlag(code="truncated_routes",
                                   message="computed on the top-N routes returned by DataService.get_routes; tail omitted"))
    return Metric(id="longhaul_dep_share", value=value, unit="pct", horizon=horizon,
                  period_start=routes.period_start, period_end=routes.period_end, source_id=routes.source_id,
                  vintage=routes.vintage, quality=quality)
