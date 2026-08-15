"""Templated, formula-driven explanations (design 02/03). No LLM in this path."""
from __future__ import annotations

from airport_agent.contracts import PILLAR_NAMES, Metric, MetricSpec
from airport_agent.scoring.scorer import ScoringResult

Evidence = dict[tuple[str, str], Metric]  # (iata, metric_id) -> Metric

# Count-like units: whole quantities (persons, seats, ops) -> thousands-separated integers.
_THOUSANDS_UNITS = ("count", "ops", "seats", "persons", "pax", "index", "days", "sqft")
# Small-magnitude ratio-like units -> 2 decimals, no thousands separator. "trips" here is a rate
# (enplanements per resident, e.g. pax_per_capita ~0.3-12), not a count -- thousands-int would collapse it.
_RATIO_UNITS = ("ratio", "trips")
# Discrete label-coded units -> plain integer, no decimals, no thousands separator.
_INTEGER_UNITS = ("flag", "ordinal")


def fmt_value(spec: MetricSpec, value: float | None) -> str:
    if value is None:
        return "n/a"
    unit = spec.unit
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit in _RATIO_UNITS:
        return f"{value:.2f}"
    if unit == "min":
        return f"{value:.1f} min"
    if unit == "usd":
        return f"${value:,.2f}"
    if unit == "turns":
        return f"{value:.1f}"
    if unit in _INTEGER_UNITS:
        return f"{value:.0f}"
    if unit in _THOUSANDS_UNITS:
        return f"{value:,.0f}"
    return f"{value:g}"


def _pair_line(a: str, b: str, res: ScoringResult, by_id: dict[str, MetricSpec], ev: Evidence) -> str:
    ra = next(r for r in res.rows if r.ref.iata == a)
    rb = next(r for r in res.rows if r.ref.iata == b)
    pillars = sorted(ra.pillar_contrib, key=lambda p: ra.pillar_contrib[p] - rb.pillar_contrib.get(p, 0.0),
                     reverse=True)
    p = pillars[0]
    delta = ra.pillar_contrib[p] - rb.pillar_contrib.get(p, 0.0)
    metrics = [m for m in ra.metric_contrib if by_id[m].pillar == p]
    if not metrics:
        return f"{a} ranks above {b} on {PILLAR_NAMES[p]} (+{delta:.0f})."
    m = max(metrics, key=lambda x: ra.metric_contrib[x] - rb.metric_contrib.get(x, 0.0))
    ma, mb = ev.get((a, m)), ev.get((b, m))
    va = fmt_value(by_id[m], ma.value if ma else None)
    vb = fmt_value(by_id[m], mb.value if mb else None)
    src = f"{ma.source_id}, through {ma.period_end}" if ma else "source n/a"
    return f"{a} ranks above {b} mainly on {PILLAR_NAMES[p]} (+{delta:.0f}): {by_id[m].name} {va} vs {vb} ({src})."


def explain_rank(res: ScoringResult, by_id: dict[str, MetricSpec], evidence: Evidence, preset_name: str,
                 horizon: str, peer_group: str, absent_weight: float | None = None) -> str:
    n = len(res.rows)
    lines = [f"Ranked {n} airports with preset '{preset_name}' at horizon {horizon}; percentiles within {peer_group}."]
    order = [r.ref.iata for r in res.rows]
    for a, b in zip(order, order[1:], strict=False):
        lines.append(_pair_line(a, b, res, by_id, evidence))
    if res.absent_pillars:
        names = ", ".join(PILLAR_NAMES[p] for p in res.absent_pillars)
        if absent_weight is not None:
            lines.append(f"Pillars {names} not scored (no metric in the scored set; forgone preset weight "
                         f"{absent_weight:.2f}); other pillars renormalized.")
        else:
            lines.append(f"Pillars {names} not scored (no metric in the scored set); other pillars renormalized.")
    low = sum(1 for r in res.rows if r.low_confidence)
    if low:
        lines.append(f"{low} of {n} airports have low confidence (pillar coverage < 50%).")
    return " ".join(lines)


def explain_compare(res: ScoringResult, by_id: dict[str, MetricSpec], evidence: Evidence, iatas: list[str],
                    horizon: str, peer_group: str) -> str:
    head = f"Side-by-side at horizon {horizon} (percentiles within {peer_group})."
    idx = " · ".join(f"{i} {res.pillar_scores.get(i, {}).get('P2', 0.0):.0f}" for i in iatas)
    parts = [head, f"Congestion index (P2 sub-score): {idx}."]
    gaps: list[tuple[float, str]] = []
    for m, per in res.percentiles.items():
        vals = [per.get(i) for i in iatas]
        known = [v for v in vals if v is not None]
        if len(known) >= 2:
            gaps.append((max(known) - min(known), m))
    gaps.sort(reverse=True)
    if gaps:
        cells = []
        for _, m in gaps[:3]:
            cell = " vs ".join(
                f"{i} {fmt_value(by_id[m], evidence[(i, m)].value if (i, m) in evidence else None)} "
                f"(pct {_fmt_pct(res.percentiles[m].get(i))})"
                for i in iatas)
            cells.append(f"{by_id[m].name}: {cell}")
        parts.append("Largest gaps: " + "; ".join(cells) + ".")
    return " ".join(parts)


def _fmt_pct(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def explain_diagnose(iata: str, signals: list[tuple[str, bool, str]]) -> str:
    n_true = sum(1 for _, ok, _ in signals if ok)
    lines = [f"Signals of unmet demand at {iata}: {n_true} of {len(signals)} present."]
    lines += [f"{'✔' if ok else '✘'} {text}" for _, ok, text in signals]
    return " ".join(lines)
