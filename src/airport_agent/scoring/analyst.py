"""Deterministic Analyst — implements contracts.DeterministicAnalyst over a DataService (design 02/03)."""
from __future__ import annotations

from pathlib import Path

from airport_agent.contracts import (
    AirportFilter,
    AirportRef,
    AnalysisRequest,
    CuratedFact,
    DeterministicReport,
    Horizon,
    Metric,
    PeerGroup,
    ScoreRow,
)
from airport_agent.contracts.data_service import DataService
from airport_agent.scoring.explain import Evidence, explain_rank
from airport_agent.scoring.presets import Preset, load_presets
from airport_agent.scoring.scorer import Scorer, ScoringResult

UNIVERSE_LIMIT = 600
LONGHAUL_CONVENTION = ("Long-haul convention: routes >= 1,500 statute miles (bands short<500, medium 500-1500, "
                       "long 1500-3000, ultra>3000); passenger and freight computed separately")
SPILL_CONVENTION = "Load factor is interpreted via the spill model (with spill_proxy), not an absolute cutoff"


class Analyst:
    def __init__(self, data: DataService, presets_path: Path | None = None) -> None:
        self.data = data
        self.specs = data.describe_metrics()
        self.by_id = {s.id: s for s in self.specs}
        self.presets = load_presets(presets_path)
        self.scorer = Scorer(self.specs)

    # ---- helpers -------------------------------------------------------------------------------
    def _preset(self, name: str | None) -> Preset:
        key = name or "balanced"
        if key not in self.presets:
            raise ValueError(f"unknown scoring preset {key!r}; choose one of {sorted(self.presets)}")
        return self.presets[key]

    def _resolve_airports(self, req: AnalysisRequest) -> list[str]:
        if req.airports:
            return list(dict.fromkeys(req.airports))
        assert req.filter is not None  # guaranteed by AnalysisRequest validator
        iatas = [a.iata for a in self.data.list_airports(req.filter)]
        if not iatas:
            raise ValueError("no airports match the filter")
        return iatas

    def _universe(self) -> list[AirportRef]:
        return self.data.list_airports(AirportFilter(limit=UNIVERSE_LIMIT))

    def _evidence(self, iatas: list[str], metric_ids: list[str], horizon: Horizon
                  ) -> tuple[list[Metric], Evidence, list[CuratedFact]]:
        wanted = set(metric_ids)
        flat: list[Metric] = []
        ev: Evidence = {}
        facts: list[CuratedFact] = []
        for i in iatas:
            prof = self.data.get_profile(i, horizons=(horizon,))
            for m in prof.metrics.get(horizon, []):
                if m.id in wanted:
                    flat.append(m)
                    ev[(i, m.id)] = m
            facts.extend(prof.curated_facts)
        return flat, ev, facts

    def _score_targets(self, targets: list[str], metric_ids: list[str], horizon: Horizon, peer_group: PeerGroup,
                       preset: Preset) -> tuple[ScoringResult, int]:
        universe = self._universe()
        uni_iatas = [a.iata for a in universe]
        for t in targets:
            if t not in uni_iatas:
                uni_iatas.append(t)  # let DataService raise KeyError for unknown iata
        fm = self.data.get_feature_matrix(uni_iatas, metric_ids, horizon, peer_group)
        res = self.scorer.score(fm, preset)
        keep = set(targets)
        rows = [r for r in res.rows if r.ref.iata in keep]
        rows.sort(key=lambda r: (-r.score, r.ref.iata))
        rows = [r.model_copy(update={"rank": k + 1}) for k, r in enumerate(rows)]
        pcts = {m: {i: v for i, v in per.items() if i in keep} for m, per in res.percentiles.items()}
        sub = {i: s for i, s in res.pillar_scores.items() if i in keep}
        return ScoringResult(rows=rows, weights=res.weights, percentiles=pcts, pillar_scores=sub,
                             scored_metric_ids=res.scored_metric_ids,
                             absent_pillars=res.absent_pillars), len(uni_iatas)

    def _caveats(self, metric_ids: list[str], peer_group: PeerGroup, n_universe: int) -> list[str]:
        out = [f"Percentiles computed within {peer_group} peer groups across {n_universe} airports; "
               "P5 metrics always within hub class.",
               "Weights are the preset's nominal weights; when a metric is missing for an airport its "
               "within-pillar weight is renormalized over the available metrics (see coverage).",
               "Tier B metrics (curated YAML) contribute only where curated data exists; tier C metrics "
               "are never scored."]
        if peer_group != "hub_class":
            out.append(f"peer_group '{peer_group}' widens comparison beyond hub class — scale metrics "
                       "(P5, size) are less comparable")
        if "longhaul_dep_share" in metric_ids:
            out.append(LONGHAUL_CONVENTION)
        if "load_factor" in metric_ids:
            out.append(SPILL_CONVENTION)
        for m in metric_ids:
            for c in self.by_id[m].caveats:
                if c not in out:
                    out.append(c)
        return out

    # ---- DeterministicAnalyst -------------------------------------------------------------------
    def rank(self, req: AnalysisRequest) -> DeterministicReport:
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset)
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        metric_ids = self.scorer.scoreable_ids(preset, req.focus_metrics) if req.focus_metrics \
            else self.scorer.scoreable_ids(preset)
        res, n_uni = self._score_targets(targets, metric_ids, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, metric_ids, horizon)
        rows: list[ScoreRow] = res.rows

        absent_weight: float | None = None
        caveats = self._caveats(metric_ids, peer_group, n_uni)
        if res.absent_pillars:
            absent_weight = sum(preset.pillars[p] for p in res.absent_pillars)
            caveats.append(f"Pillars {', '.join(res.absent_pillars)} not scored (no metric in the scored set; "
                           f"forgone preset weight {absent_weight:.2f}); other pillars renormalized.")

        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=rows, comparison=None, evidence=evidence,
            explanation=explain_rank(res, self.by_id, ev, preset.name, horizon, peer_group,
                                     absent_weight=absent_weight),
            caveats=caveats, curated_facts=facts, percentiles=res.percentiles)
