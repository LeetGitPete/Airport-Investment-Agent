"""Analysis tools: the LLM's only route into the Deterministic Analyst (design 03 §Question classes → path).

Each tool builds a validated AnalysisRequest and returns the DeterministicReport verbatim — the numbers are
the formula's, never the model's. A request with neither airports nor a filter fails validation and comes back
as an error dict, so the model asks for a target instead of getting a silent all-airports ranking.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from airport_agent.agent.tools.provenance import ProvenanceSpec, prov
from airport_agent.contracts import (
    AirportFilter,
    AnalysisRequest,
    DeterministicAnalyst,
    DeterministicReport,
    Horizon,
    HubSize,
    PeerGroup,
    ToolSpec,
)

CONCIERGE = "concierge"
EXPANSION = "expansion_analyst"
CAPACITY = "capacity_analyst"
MARKET = "market_analyst"
GENERAL = "general_analyst"

_PRESET_DOC = ("Scoring preset (e.g. terminal_expansion, congestion_relief, market_entry, balanced); "
               "null uses the engine default. Presets are fixed in config - never invent weights.")
_PEER_DOC = "Peer group for percentiles: hub_class (default), region or all."
_FOCUS_DOC = "Metric ids to focus the comparison on; null uses the preset's metrics."


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("airports", check_fields=False, mode="before")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        if not isinstance(v, list):
            return v
        return [s.strip().upper() if isinstance(s, str) else s for s in v]


class ScoreAirportsArgs(_Args):
    airports: list[str] | None = Field(default=None,
                                       description="Explicit IATA codes to score. Give either airports or a "
                                                   "filter (states / faa_regions / hub_sizes) - with neither the "
                                                   "call is rejected.")
    states: list[str] = Field(default_factory=list, description="Two-letter state codes to score.")
    faa_regions: list[str] = Field(default_factory=list, description="FAA region codes, e.g. ANE, AWP.")
    hub_sizes: list[HubSize] = Field(default_factory=list,
                                     description="Hub classes: large, medium, small, nonhub.")
    cbsa_codes: list[str] = Field(default_factory=list,
                                  description="Census CBSA codes; used with `AirportFilter.cbsa_codes`.")
    limit: int = Field(default=50, ge=1, le=600,
                       description="Maximum airports pulled in by the filter (1-600, default 50); ignored when "
                                   "airports are given explicitly.")
    horizon: Horizon = Field(default="5y", description="Scoring horizon: 12m, 3y, 5y (default) or 10y.")
    scoring_preset: str | None = Field(default=None, description=_PRESET_DOC)
    focus_metrics: list[str] | None = Field(default=None, description=_FOCUS_DOC)
    peer_group: PeerGroup | None = Field(default=None, description=_PEER_DOC)


class CompareAirportsArgs(_Args):
    airports: list[str] = Field(min_length=1, description="IATA codes to compare side by side (at least 1).")
    horizon: Horizon = Field(default="12m", description="Comparison horizon: 12m (default), 3y, 5y or 10y.")
    focus_metrics: list[str] | None = Field(default=None, description=_FOCUS_DOC)
    scoring_preset: str | None = Field(default=None, description=_PRESET_DOC)
    peer_group: PeerGroup | None = Field(default=None, description=_PEER_DOC)


class DiagnoseArgs(_Args):
    airports: list[str] = Field(min_length=1, description="IATA codes to diagnose (at least 1).")
    horizon: Horizon = Field(default="12m", description="Diagnosis horizon: 12m (default), 3y, 5y or 10y.")
    peer_group: PeerGroup | None = Field(default=None, description=_PEER_DOC)


def _report_dict(report: DeterministicReport) -> dict[str, Any]:
    out = report.model_dump(mode="json")
    # Cite only sources that actually supplied a number. Every registry metric carries a nominal
    # source_id even when it has no value, so citing the evidence wholesale would claim sources the
    # snapshot has zero rows of. A citation for data we never had is worse than a missing one.
    out["provenance"] = prov([m for m in report.evidence if m.value is not None])
    # design 03: every tool result carries coverage. For a report it is the mean metric coverage of its rows.
    out["coverage"] = (sum(r.coverage for r in report.rows) / len(report.rows)) if report.rows else None
    return out


def build_analysis_tools(analyst: DeterministicAnalyst) -> list[tuple[ToolSpec, ProvenanceSpec]]:
    """Build the rank / compare / diagnose tools bound to a Deterministic Analyst.

    Each is paired with its declared provenance. All three are `derived`: which sources they cite
    depends on which metrics the query actually scored, so a static list would be a lie.
    """

    def score_airports(p: ScoreAirportsArgs) -> dict[str, Any]:
        has_filter = bool(p.states or p.faa_regions or p.hub_sizes or p.cbsa_codes)
        filter_ = AirportFilter(states=p.states, faa_regions=p.faa_regions, hub_sizes=p.hub_sizes,
                                cbsa_codes=p.cbsa_codes,
                                limit=p.limit) if not p.airports and has_filter else None
        req = AnalysisRequest(question_type="rank", airports=p.airports, filter=filter_, horizons=[p.horizon],
                              peer_group=p.peer_group, scoring_preset=p.scoring_preset,
                              focus_metrics=p.focus_metrics)
        return _report_dict(analyst.rank(req))

    def compare_airports(p: CompareAirportsArgs) -> dict[str, Any]:
        req = AnalysisRequest(question_type="compare", airports=p.airports, horizons=[p.horizon],
                              peer_group=p.peer_group, scoring_preset=p.scoring_preset,
                              focus_metrics=p.focus_metrics)
        return _report_dict(analyst.compare(req))

    def diagnose_unmet_demand(p: DiagnoseArgs) -> dict[str, Any]:
        req = AnalysisRequest(question_type="diagnose", airports=p.airports, horizons=[p.horizon],
                              peer_group=p.peer_group)
        return _report_dict(analyst.diagnose(req))

    return [
        (ToolSpec(name="score_airports", params_model=ScoreAirportsArgs, fn=score_airports,
                 engines=[CONCIERGE, EXPANSION, GENERAL],
                 description="Rank airports with the deterministic scoring engine. Give either explicit airports "
                             "or a filter (states / faa_regions / hub_sizes / cbsa_codes, at most `limit` "
                             "airports, default 50) - a call with neither is rejected. Returns scores, ranks, pillar and metric "
                             "contributions, coverage, percentiles, evidence and caveats. The numbers are the "
                             "formula's: report them as returned, never recompute or reweight them."),
         ProvenanceSpec.derived("cites the sources of every metric that entered the score")),
        (ToolSpec(name="compare_airports", params_model=CompareAirportsArgs, fn=compare_airports,
                 engines=[CONCIERGE, CAPACITY, MARKET, GENERAL],
                 description="Side-by-side deterministic comparison of the given airports (at least 1) on the "
                             "preset's metrics or on focus_metrics. Returns the comparison table, scores, "
                             "evidence with source and vintage, and caveats. Report the numbers as returned."),
         ProvenanceSpec.derived("cites the sources of every metric compared")),
        (ToolSpec(name="diagnose_unmet_demand", params_model=DiagnoseArgs, fn=diagnose_unmet_demand,
                 engines=[CONCIERGE, CAPACITY, GENERAL],
                 description="Deterministic unmet-demand evidence bundle for the given airports (at least 1): "
                             "load factor and spill proxy, delay and taxi-out, NPIAS capacity label and curated "
                             "capacity facts, with a templated explanation. Evidence of pressure, not proof of "
                             "unmet demand - keep that distinction in the answer."),
         ProvenanceSpec.derived("cites the sources of every metric behind the diagnosis")),
    ]
