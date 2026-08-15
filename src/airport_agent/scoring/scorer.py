"""Composite scorer: percentiles within peer group -> weighted contributions -> ScoreRows (design 02).

score = sum_p w_p' * sum_m w_m' * pct * 100, with w' = weights renormalized over the metrics/pillars available
for the airport, so ScoreRow.metric_contrib sums to ScoreRow.score (frozen contract docstring in reports.py).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts import FeatureMatrix, MetricSpec, ScoreRow, load_pillars
from airport_agent.scoring.percentiles import percentiles_by_group
from airport_agent.scoring.presets import PILLAR_IDS, Preset


class ScoringResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ScoreRow]
    weights: dict[str, float]
    percentiles: dict[str, dict[str, float | None]]
    pillar_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    scored_metric_ids: list[str] = Field(default_factory=list)
    absent_pillars: list[str] = Field(default_factory=list)


class Scorer:
    def __init__(self, specs: list[MetricSpec], pillars_cfg: dict[str, dict] | None = None) -> None:
        self._by_id = {s.id: s for s in specs}
        cfg = pillars_cfg if pillars_cfg is not None else load_pillars()
        self._pillar_norm = {p: cfg.get(p, {}).get("normalize_within") for p in PILLAR_IDS}

    def scoreable_ids(self, preset: Preset, candidate_ids: list[str] | None = None) -> list[str]:
        ids = candidate_ids if candidate_ids is not None else list(self._by_id)
        ids = list(dict.fromkeys(ids))  # dedupe, preserve order
        return [i for i in ids if i in self._by_id and self._by_id[i].tier != "C"
                and i not in preset.excluded_metrics]

    def score(self, fm: FeatureMatrix, preset: Preset) -> ScoringResult:
        ids = self.scoreable_ids(preset, fm.metric_ids)
        iatas = [a.iata for a in fm.airports]
        # 1) percentiles per metric (P5 always within hub class)
        pct: dict[str, list[float | None]] = {}
        for m in ids:
            spec = self._by_id[m]
            group = "hub_class" if self._pillar_norm.get(spec.pillar) == "hub_class" else fm.peer_group
            pct[m] = percentiles_by_group(fm.airports, fm.column(m), spec.direction, group)
        # 2) nominal weights: pillar -> w_p; metric -> relative weight normalized over all scoreable metrics in pillar
        by_pillar: dict[str, list[str]] = {p: [m for m in ids if self._by_id[m].pillar == p] for p in PILLAR_IDS}
        weights: dict[str, float] = {p: float(preset.pillars[p]) for p in PILLAR_IDS}
        for members in by_pillar.values():
            tot = sum(preset.metric_weight(m) for m in members)
            for m in members:
                weights[m] = preset.metric_weight(m) / tot if tot > 0 else 0.0
        # pillars with preset weight > 0 that have no scoreable metric in this matrix at all (structural, not
        # per-airport availability) -- surfaced so callers can caveat "forgone preset weight" (human decision).
        absent_pillars = [p for p in PILLAR_IDS if preset.pillars[p] > 0 and not by_pillar[p]]
        # 3) per-airport effective weights and contributions
        rows: list[ScoreRow] = []
        pillar_scores: dict[str, dict[str, float]] = {}
        for i, ref in enumerate(fm.airports):
            avail = {m for m in ids if pct[m][i] is not None}
            pillar_w: dict[str, float] = {}
            metric_contrib: dict[str, float] = {}
            pillar_contrib: dict[str, float] = {}
            psub: dict[str, float] = {}
            low = False
            for p, members in by_pillar.items():
                have = [m for m in members if m in avail]
                if members and preset.pillars[p] > 0 and len(have) / len(members) < 0.5:
                    low = True
                tot_m = sum(preset.metric_weight(m) for m in have)
                if have and tot_m > 0:
                    pillar_w[p] = preset.pillars[p]
            tot_pw = sum(pillar_w.values())
            for p, wp in pillar_w.items():
                wp_eff = wp / tot_pw if tot_pw > 0 else 0.0
                have = [m for m in by_pillar[p] if m in avail]
                tot_m = sum(preset.metric_weight(m) for m in have)
                sub = 0.0
                for m in have:
                    wm_eff = preset.metric_weight(m) / tot_m if tot_m > 0 else 0.0
                    c = wp_eff * wm_eff * float(pct[m][i]) * 100.0  # type: ignore[arg-type]
                    metric_contrib[m] = c
                    sub += wm_eff * float(pct[m][i]) * 100.0  # type: ignore[arg-type]
                pillar_contrib[p] = sum(metric_contrib[m] for m in have)
                psub[p] = sub
            for p in PILLAR_IDS:
                pillar_contrib.setdefault(p, 0.0)
                psub.setdefault(p, 0.0)
            score = sum(metric_contrib.values())
            coverage = len(avail) / len(ids) if ids else 0.0
            if not ids or not pillar_w or tot_pw <= 0:
                low = True
            pillar_scores[ref.iata] = psub
            rows.append(ScoreRow(ref=ref, score=score, rank=0, pillar_contrib=pillar_contrib,
                                 metric_contrib=metric_contrib, coverage=coverage, low_confidence=low))
        rows.sort(key=lambda r: (-r.score, r.ref.iata))
        rows = [r.model_copy(update={"rank": k + 1}) for k, r in enumerate(rows)]
        percentiles = {m: dict(zip(iatas, pct[m], strict=True)) for m in ids}
        return ScoringResult(rows=rows, weights=weights, percentiles=percentiles, pillar_scores=pillar_scores,
                             scored_metric_ids=ids, absent_pillars=absent_pillars)
