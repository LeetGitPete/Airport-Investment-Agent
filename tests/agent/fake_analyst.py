"""FakeAnalyst — a deterministic, canned-math DeterministicAnalyst double over FakeDataService.

Score = load_factor * 100 at req.horizons[0] (missing value -> score 0). This is intentionally trivial:
the point of the fake is to exercise the Concierge/tool-dispatch plumbing against valid, provenance-carrying
DeterministicReports, not to reproduce scoring/'s real pillar math.
"""
from __future__ import annotations

from airport_agent.contracts import (
    AirportRef,
    AnalysisRequest,
    CuratedFact,
    DataService,
    DeterministicReport,
    Horizon,
    Metric,
    PeerGroup,
    ScoreRow,
)

_EVIDENCE_IDS = ["load_factor", "avg_dep_delay_min", "taxi_out_p80_min", "npias_capacity_label"]
_WEIGHTS = {"P1": 1.0, "load_factor": 1.0}
_CAVEATS = ["fake analyst"]


class FakeAnalyst:
    """contracts.DeterministicAnalyst double; deterministic canned math, no LLM."""

    def __init__(self, data: DataService) -> None:
        self.data = data

    # --- shared plumbing ---
    def _targets(self, req: AnalysisRequest) -> list[str]:
        if req.airports:
            return list(req.airports)
        return [a.iata for a in self.data.list_airports(req.filter)]

    def _build(self, req: AnalysisRequest) -> tuple[list[ScoreRow], list[Metric], list[CuratedFact],
                                                     dict[str, dict[str, float | None]], Horizon, PeerGroup,
                                                     dict[str, dict[str, float | None]]]:
        horizon: Horizon = req.horizons[0] if req.horizons else "12m"
        peer_group: PeerGroup = req.peer_group or "hub_class"
        iatas = self._targets(req)
        evidence: list[Metric] = []
        curated_facts: list[CuratedFact] = []
        refs: dict[str, AirportRef] = {}
        by_metric: dict[str, dict[str, float | None]] = {mid: {} for mid in _EVIDENCE_IDS}
        for iata in iatas:
            profile = self.data.get_profile(iata, (horizon,))
            refs[iata] = profile.ref
            curated_facts.extend(profile.curated_facts)
            for m in profile.metrics.get(horizon, []):
                if m.id in _EVIDENCE_IDS:
                    evidence.append(m)
                    by_metric[m.id][iata] = m.value

        scores = {iata: (by_metric["load_factor"].get(iata) or 0.0) * 100 for iata in iatas}
        ordered = sorted(iatas, key=lambda i: scores[i], reverse=True)
        n = len(ordered)
        rows = []
        percentiles: dict[str, float | None] = {}
        for rank, iata in enumerate(ordered, start=1):
            score = scores[iata]
            lf_present = by_metric["load_factor"].get(iata) is not None
            rows.append(ScoreRow(ref=refs[iata], score=score, rank=rank, pillar_contrib={"P1": score},
                                  metric_contrib={"load_factor": score}, coverage=1.0 if lf_present else 0.0,
                                  low_confidence=not lf_present))
            percentiles[iata] = (n - rank) / (n - 1) if n > 1 else 0.5
        return rows, evidence, curated_facts, {"load_factor": percentiles}, horizon, peer_group, by_metric

    def rank(self, req: AnalysisRequest) -> DeterministicReport:
        rows, evidence, curated_facts, percentiles, horizon, peer_group, _ = self._build(req)
        return DeterministicReport(question_type=req.question_type, preset=req.scoring_preset, weights=_WEIGHTS,
                                    horizon=horizon, peer_group=peer_group, rows=rows, comparison=None,
                                    evidence=evidence, explanation="fake rank", caveats=list(_CAVEATS),
                                    curated_facts=curated_facts, percentiles=percentiles)

    def compare(self, req: AnalysisRequest) -> DeterministicReport:
        rows, evidence, curated_facts, percentiles, horizon, peer_group, by_metric = self._build(req)
        comparison = {mid: dict(vals) for mid, vals in by_metric.items()}
        return DeterministicReport(question_type=req.question_type, preset=req.scoring_preset, weights=_WEIGHTS,
                                    horizon=horizon, peer_group=peer_group, rows=rows, comparison=comparison,
                                    evidence=evidence, explanation="fake compare", caveats=list(_CAVEATS),
                                    curated_facts=curated_facts, percentiles=percentiles)

    def diagnose(self, req: AnalysisRequest) -> DeterministicReport:
        rows, evidence, curated_facts, percentiles, horizon, peer_group, by_metric = self._build(req)
        comparison = {mid: dict(vals) for mid, vals in by_metric.items()}
        target = self._targets(req)[0]
        delay = (by_metric["avg_dep_delay_min"].get(target) or 0) > 12.0
        npias = (by_metric["npias_capacity_label"].get(target) or 0) > 0
        lf = (by_metric["load_factor"].get(target) or 0) > 0.85
        count = sum([delay, npias, lf])
        mark = lambda ok: "✔" if ok else "✘"  # noqa: E731
        explanation = (f"Signals of unmet demand at {target}: {count} of 3 present. "
                       f"{mark(delay)} delay {mark(npias)} npias {mark(lf)} lf")
        return DeterministicReport(question_type=req.question_type, preset=req.scoring_preset, weights=_WEIGHTS,
                                    horizon=horizon, peer_group=peer_group, rows=rows, comparison=comparison,
                                    evidence=evidence, explanation=explanation, caveats=list(_CAVEATS),
                                    curated_facts=curated_facts, percentiles=percentiles)

    def distance_bands(self, iata: str, horizon: Horizon = "12m", freight: bool = False) -> dict[str, float]:
        rows = self.data.get_routes(iata, horizon=horizon).rows

        def share(lo: float, hi: float) -> float:
            if freight:
                total = sum(r.freight_lb for r in rows)
                num = sum(r.freight_lb for r in rows if lo <= r.distance_mi < hi)
            else:
                valid = [r for r in rows if r.seats > 0]
                total = sum(r.departures for r in valid)
                num = sum(r.departures for r in valid if lo <= r.distance_mi < hi)
            return (num / total) if total else 0.0

        return {"short": share(0, 500), "medium": share(500, 1500), "long": share(1500, 3000),
                "ultra": share(3000, float("inf"))}

    def long_haul_share(self, iata: str, threshold_mi: float = 1500, horizon: Horizon = "12m",
                         freight: bool = False) -> Metric:
        table = self.data.get_routes(iata, horizon=horizon)
        rows = table.rows
        if freight:
            total = sum(r.freight_lb for r in rows)
            num = sum(r.freight_lb for r in rows if r.distance_mi >= threshold_mi)
        else:
            valid = [r for r in rows if r.seats > 0]
            total = sum(r.departures for r in valid)
            num = sum(r.departures for r in valid if r.distance_mi >= threshold_mi)
        share = (num / total) if total else 0.0
        return Metric(id="longhaul_dep_share", value=share, unit="pct", horizon=horizon,
                      period_start=table.period_start, period_end=table.period_end,
                      source_id=table.source_id, vintage=table.vintage)
