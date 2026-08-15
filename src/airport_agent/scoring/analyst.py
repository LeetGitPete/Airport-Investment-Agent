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
from airport_agent.scoring.calculators import distance_bands as _bands
from airport_agent.scoring.calculators import long_haul_share as _lhs
from airport_agent.scoring.explain import Evidence, explain_compare, explain_diagnose, explain_rank, fmt_value
from airport_agent.scoring.presets import Preset, load_presets
from airport_agent.scoring.scorer import Scorer, ScoringResult

UNIVERSE_LIMIT = 600
LONGHAUL_CONVENTION = ("Long-haul convention: routes >= 1,500 statute miles (bands short<500, medium 500-1500, "
                       "long 1500-3000, ultra>3000); passenger and freight computed separately")
SPILL_CONVENTION = "Load factor is interpreted via the spill model (with spill_proxy), not an absolute cutoff"

DIAGNOSE_IDS = ["load_factor", "spill_proxy", "seats_per_dep_trend", "pct_arr_delay_gt15", "avg_dep_delay_min",
                "nas_delay_share", "taxi_out_p80_min", "npias_capacity_label", "slot_or_cap_flag",
                "peak_hour_ops_ratio", "imc_capacity_ratio", "taf_vs_actual_gap", "taf_cagr_10y"]
LABELS = {0: "none", 1: "congested", 2: "constrained_2033", 3: "constrained_2028", 4: "severe_2033"}


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
        if req.filter is None:
            # AnalysisRequest's own validator already guarantees airports or filter is set; this is
            # belt-and-braces so a future relaxation of that validator fails loudly here too, not with
            # an AttributeError deep in list_airports.
            raise ValueError("AnalysisRequest needs airports or a filter")
        iatas = [a.iata for a in self.data.list_airports(req.filter)]
        if not iatas:
            raise ValueError("no airports match the filter")
        return iatas

    def _universe(self) -> list[AirportRef]:
        return self.data.list_airports(AirportFilter(limit=UNIVERSE_LIMIT))

    #: Peer expansion cap: enough context to rank in, small enough to read (QA task 8).
    PEER_EXPANSION_LIMIT = 30

    def _expand_to_peers(self, iata: str) -> tuple[list[str], str]:
        """Expand a lone rank target to its hub-size class (largest first, capped, target kept)."""
        ref = self.data.get_airport(iata)
        if ref is None:
            raise KeyError(iata)  # matches get_feature_matrix's unknown-iata semantics
        peers = [a.iata for a in self.data.list_airports(
            AirportFilter(hub_sizes=[ref.hub_size] if ref.hub_size else None,
                          limit=self.PEER_EXPANSION_LIMIT))]
        targets = list(dict.fromkeys([iata, *peers]))[: self.PEER_EXPANSION_LIMIT]
        hub = ref.hub_size or "unknown"
        return targets, (f"A single airport cannot be ranked: expanded to {len(targets)} "
                         f"{hub}-hub peers so {iata} has context (largest by enplanements, "
                         f"capped at {self.PEER_EXPANSION_LIMIT}).")

    def _resolve_metric_ids(self, preset: Preset, focus_metrics: list[str] | None) -> tuple[list[str], list[str]]:
        """Return (scoreable metric ids, caveats about any focus_metrics dropped).

        Never silently fall back to ranking on an empty metric set: if focus_metrics is given but
        nothing in it is scoreable (all unknown / tier C / excluded by the preset), fail loudly.
        """
        if not focus_metrics:
            return self.scorer.scoreable_ids(preset), []
        candidates = list(dict.fromkeys(focus_metrics))
        ids = self.scorer.scoreable_ids(preset, candidates)
        unknown = [m for m in candidates if m not in self.by_id]
        dropped_tier_or_excluded = [m for m in candidates if m not in unknown and m not in ids]
        if not ids:
            raise ValueError(f"no scoreable metrics for this request: focus_metrics={candidates!r} "
                             "(tier C / excluded / unknown ids)")
        caveats: list[str] = []
        if unknown or dropped_tier_or_excluded:
            dropped = unknown + dropped_tier_or_excluded
            caveats.append(f"focus_metrics dropped: {dropped!r} (unknown: {unknown!r}; "
                           f"tier C/excluded: {dropped_tier_or_excluded!r})")
        return ids, caveats

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
        scored = set(metric_ids)
        for spec in self.specs:  # registry order, not the (possibly focus_metrics-supplied) metric_ids order
            if spec.id not in scored:
                continue
            for c in spec.caveats:
                if c not in out:
                    out.append(c)
        return out

    # ---- DeterministicAnalyst -------------------------------------------------------------------
    def rank(self, req: AnalysisRequest) -> DeterministicReport:
        if not req.horizons:
            raise ValueError("horizons must not be empty")
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset)
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        expansion_caveat: str | None = None
        if len(targets) == 1:
            # QA task 8 (human decision 2026-08-16): a single airport cannot be ranked, so expand
            # to its hub-size peers and rank it in that context ("SNA ranks 4th of 12...").
            targets, expansion_caveat = self._expand_to_peers(targets[0])
        metric_ids, dropped_caveats = self._resolve_metric_ids(preset, req.focus_metrics)
        res, n_uni = self._score_targets(targets, metric_ids, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, metric_ids, horizon)
        rows: list[ScoreRow] = res.rows
        # Per-airport raw values for the answer's data matrix (QA task 5) — same shape compare uses.
        comparison = {m: {i: (ev[(i, m)].value if (i, m) in ev else None) for i in targets}
                      for m in metric_ids}

        absent_weight: float | None = None
        caveats = self._caveats(metric_ids, peer_group, n_uni)
        caveats.extend(dropped_caveats)
        if expansion_caveat:
            caveats.append(expansion_caveat)
        if res.absent_pillars:
            absent_weight = sum(preset.pillars[p] for p in res.absent_pillars)
            caveats.append(f"Pillars {', '.join(res.absent_pillars)} not scored (no metric in the scored set; "
                           f"forgone preset weight {absent_weight:.2f}); other pillars renormalized.")

        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=rows, comparison=comparison, evidence=evidence,
            explanation=explain_rank(res, self.by_id, ev, preset.name, horizon, peer_group,
                                     absent_weight=absent_weight),
            caveats=caveats, curated_facts=facts, percentiles=res.percentiles)

    def compare(self, req: AnalysisRequest) -> DeterministicReport:
        if not req.horizons:
            raise ValueError("horizons must not be empty")
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset)
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        candidates = list(dict.fromkeys(req.focus_metrics)) if req.focus_metrics else []
        wanted = [m for m in candidates if m in self.by_id] or self.scorer.scoreable_ids(preset)
        if not wanted:
            raise ValueError(f"no known metrics for this request: focus_metrics={req.focus_metrics!r}")
        scoreable = self.scorer.scoreable_ids(preset, wanted)
        res, n_uni = self._score_targets(targets, scoreable, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, wanted, horizon)
        comparison = {m: {i: (ev[(i, m)].value if (i, m) in ev else None) for i in targets} for m in wanted}
        caveats = self._caveats(scoreable, peer_group, n_uni)
        unknown = [m for m in candidates if m not in self.by_id]
        if unknown:
            caveats.append(f"focus_metrics dropped: {unknown!r} (unknown ids)")
        for m in wanted:
            if self.by_id[m].tier == "C":
                caveats.append(f"{m} ({self.by_id[m].name}) is a documented gap (tier C): not computable "
                               "from public data — reported as not available")
        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=res.rows, comparison=comparison, evidence=evidence,
            explanation=explain_compare(res, self.by_id, ev, targets, horizon, peer_group),
            caveats=caveats, curated_facts=facts, percentiles=res.percentiles)

    def distance_bands(self, iata: str, horizon: Horizon = "12m", freight: bool = False) -> dict[str, float]:
        return _bands(self.data.get_routes(iata, horizon=horizon, top_n=1000), freight=freight)

    def long_haul_share(self, iata: str, threshold_mi: float = 1500, horizon: Horizon = "12m",
                        freight: bool = False) -> Metric:
        return _lhs(self.data.get_routes(iata, horizon=horizon, top_n=1000), threshold_mi=threshold_mi,
                    freight=freight, horizon=horizon)

    def _signals(self, iata: str, ev: Evidence, pcts: dict[str, dict[str, float | None]]
                 ) -> list[tuple[str, bool, str]]:
        def val(m: str) -> float | None:
            x = ev.get((iata, m))
            return None if x is None else x.value

        def pct(m: str) -> float | None:
            return pcts.get(m, {}).get(iata)

        def fv(m: str) -> str:
            return fmt_value(self.by_id[m], val(m))

        def fp(m: str) -> str:
            p = pct(m)
            return "n/a" if p is None else f"{p:.2f}"

        def ge(x: float | None, t: float) -> bool:
            return x is not None and x >= t

        def le(x: float | None, t: float) -> bool:
            return x is not None and x <= t

        delay_metric = "avg_dep_delay_min" if ge(pct("avg_dep_delay_min"), 0.75) else "pct_arr_delay_gt15"
        label = val("npias_capacity_label")
        return [
            ("lf_spill", ge(pct("load_factor"), 0.75) and ge(pct("spill_proxy"), 0.5),
             f"high load factor with variable demand (spill likely): LF {fv('load_factor')} "
             f"(pct {fp('load_factor')}), spill proxy {fv('spill_proxy')} (pct {fp('spill_proxy')})"),
            ("upgauge", ge(pct("seats_per_dep_trend"), 0.75),
             "upgauging trend in top quartile (airlines add seats per departure — proxy for slot/runway "
             "constraint)"),
            ("delay", ge(pct("avg_dep_delay_min"), 0.75) or ge(pct("pct_arr_delay_gt15"), 0.75),
             f"delay in top quartile of peers ({self.by_id[delay_metric].name} {fv(delay_metric)})"),
            ("nas", ge(pct("nas_delay_share"), 0.75), "high systemic (NAS) delay share"),
            ("taxi", ge(pct("taxi_out_p80_min"), 0.75), "surface congestion: taxi-out p80 in top quartile"),
            ("npias", ge(label, 2),
             f"FAA NPIAS lists the airport as capacity constrained (label "
             f"{LABELS.get(int(label), label) if label is not None else 'n/a'})"),
            ("legal_cap", val("slot_or_cap_flag") == 1,
             "legal capacity constraint in force (slot level / hourly cap)"),
            ("peak", ge(val("peak_hour_ops_ratio"), 0.9), "peak-hour operations at ≥90% of declared VMC rate"),
            ("imc", le(val("imc_capacity_ratio"), 0.8), "weather fragility: IMC rate ≤80% of VMC rate"),
            ("taf_gap", ge(val("taf_vs_actual_gap"), 1.03),
             "FAA forecast runs ≥3% above latest actuals (forecast optimism / suppressed demand)"),
        ]

    def diagnose(self, req: AnalysisRequest) -> DeterministicReport:
        if not req.horizons:
            raise ValueError("horizons must not be empty")
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset or "congestion_relief")
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        scoreable = self.scorer.scoreable_ids(preset, DIAGNOSE_IDS)
        res, n_uni = self._score_targets(targets, scoreable, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, DIAGNOSE_IDS, horizon)
        comparison = {m: {i: (ev[(i, m)].value if (i, m) in ev else None) for i in targets} for m in DIAGNOSE_IDS}
        explanation = " | ".join(explain_diagnose(i, self._signals(i, ev, res.percentiles)) for i in targets)
        caveats = self._caveats(scoreable, peer_group, n_uni)
        for c in ("Signals are heuristics over percentiles within hub class (thresholds: top quartile = "
                 "pct ≥ 0.75); they indicate, not prove, unmet demand",
                 "NPIAS constraint labels are partly circular for slot-controlled airports"):
            if c not in caveats:
                caveats.append(c)
        if any(comparison[m][i] is not None for m in ("peak_hour_ops_ratio", "imc_capacity_ratio")
              for i in targets):
            c = "Declared VMC/IMC capacities come from FAA Capacity Profiles 2014–2019 (curated)"
            if c not in caveats:
                caveats.append(c)
        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=res.rows, comparison=comparison, evidence=evidence,
            explanation=explanation, caveats=caveats, curated_facts=facts, percentiles=res.percentiles)
