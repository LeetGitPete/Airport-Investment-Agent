"""Data-retrieval tools over the DataService port (design 03 §Tools & transport).

One args model + one closure per tool; every description states its limits so the model self-corrects.
The tools never compute analysis themselves — route bands come from the Deterministic Analyst.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from airport_agent.agent.tools.analysis_tools import build_analysis_tools
from airport_agent.agent.tools.provenance import ProvenanceSpec, prov
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import (
    PILLAR_NAMES,
    AirportFilter,
    DataService,
    DeterministicAnalyst,
    Horizon,
    HubSize,
    ToolSpec,
)

CONCIERGE = "concierge"
EXPANSION = "expansion_analyst"
CAPACITY = "capacity_analyst"
MARKET = "market_analyst"
GENERAL = "general_analyst"
ALL_ENGINES = [CONCIERGE, EXPANSION, CAPACITY, MARKET, GENERAL]

BANDS_DOC = "bands short<500, medium 500-1500, long 1500-3000, ultra>3000"
#: What `find_airports` reads. OurAirports supplies identity; the FAA TAF supplies hub size and FAA
#: region by UPDATE into the same rows, so both are cited even though the rows say 'ourairports'.
IDENTITY_SOURCES = ("ourairports", "faa_taf")
#: The only source a live-status call actually fetches at question time; everything else it returns
#: is snapshot data and must keep the snapshot's own date.
LIVE_SOURCE = "faa_nasstatus"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _IataArgs(_Args):
    @field_validator("iata", check_fields=False, mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v


class FindAirportsArgs(_Args):
    states: list[str] = Field(default_factory=list, description="Two-letter state codes, e.g. MA, CT.")
    faa_regions: list[str] = Field(default_factory=list,
                                   description="FAA region codes, e.g. ANE (New England), AWP, AEA.")
    iatas: list[str] = Field(default_factory=list, description="Explicit IATA codes to restrict to.")
    hub_sizes: list[HubSize] = Field(default_factory=list,
                                     description="Hub classes: large, medium, small, nonhub.")
    cbsa_codes: list[str] = Field(default_factory=list,
                                  description="Census CBSA codes; used with `AirportFilter.cbsa_codes`.")
    name_contains: str | None = Field(default=None, description="Case-insensitive substring of the airport name.")
    limit: int = Field(default=50, ge=1, le=600,
                       description="Maximum airports returned (1-600, default 50); truncated is true when the "
                                   "limit was hit and more may exist.")


class GetProfileArgs(_IataArgs):
    iata: str = Field(description="Airport IATA code, e.g. BOS. Unknown code returns an error.")
    horizons: list[Horizon] = Field(default_factory=lambda: ["12m", "5y"],
                                    description="Horizons to include: 12m, 3y, 5y, 10y (default 12m and 5y). "
                                                "A metric that does not declare a horizon is reported at its own.")


class RouteStatsArgs(_IataArgs):
    iata: str = Field(description="Airport IATA code, e.g. ANC. Unknown code returns an error.")
    horizon: Horizon = Field(default="12m", description="Horizon of the route table: 12m, 3y, 5y or 10y.")
    top_n: int = Field(default=10, ge=1, le=50,
                       description="Number of routes returned, ranked by departures (top_n <= 50, default 10); "
                                   "truncated is true when more routes exist.")
    international: bool | None = Field(default=None,
                                       description="Filter top_routes: true = international only, false = domestic "
                                                   "only, null = both. Bands and shares always use all routes.")
    threshold_mi: float = Field(default=1500, gt=0, le=12000,
                                description="Long-haul threshold in statute miles (default 1500, the stated "
                                            "convention). State it whenever you quote the share.")


class LiveStatusArgs(_IataArgs):
    iata: str = Field(description="Airport IATA code, e.g. SFO. Unknown code returns an error.")


class ExplainMetricArgs(_Args):
    metric_id: str = Field(description="Metric id from the registry, e.g. load_factor. Unknown id returns an error.")


class MetricSeriesArgs(_IataArgs):
    iata: str = Field(description="Airport IATA code, e.g. BOS. Unknown code returns an error.")
    metric_id: str = Field(description="Metric id from the registry. Static and forecast metrics have no series "
                                       "and return an empty list.")


class ListSourcesArgs(_Args):
    """No arguments."""


def build_data_tools(data: DataService,
                     analyst: DeterministicAnalyst) -> list[tuple[ToolSpec, ProvenanceSpec]]:
    """Build the data-retrieval tools bound to a DataService (and the analyst, for route bands).

    Each tool is paired with the provenance it declares; `ToolRegistry.register` refuses a tool
    without one, so an unsourced result cannot reach a user by omission.
    """

    def find_airports(p: FindAirportsArgs) -> dict[str, Any]:
        refs = data.list_airports(AirportFilter(states=p.states, faa_regions=p.faa_regions, iatas=p.iatas,
                                                hub_sizes=p.hub_sizes, cbsa_codes=p.cbsa_codes,
                                                name_contains=p.name_contains, limit=p.limit))
        vintages = [v for v in data.source_vintages() if v.source_id in IDENTITY_SOURCES]
        return {"airports": [r.model_dump(mode="json") for r in refs], "count": len(refs),
                "truncated": len(refs) == p.limit, "provenance": prov(vintages)}

    def get_profile(p: GetProfileArgs) -> dict[str, Any]:
        profile = data.get_profile(p.iata, tuple(p.horizons))
        out = profile.model_dump(mode="json")
        out["provenance"] = prov(profile.vintages)
        return out

    def get_route_stats(p: RouteStatsArgs) -> dict[str, Any]:
        routes = data.get_routes(p.iata, horizon=p.horizon, top_n=p.top_n, international=p.international)
        bands = {kind: analyst.distance_bands(p.iata, horizon=p.horizon, freight=freight)
                 for kind, freight in (("passenger", False), ("freight", True))}
        shares = {kind: analyst.long_haul_share(p.iata, threshold_mi=p.threshold_mi, horizon=p.horizon,
                                                freight=freight).model_dump(mode="json")
                  for kind, freight in (("passenger", False), ("freight", True))}
        return {"iata": routes.iata, "horizon": p.horizon, "distance_bands": bands, "long_haul_share": shares,
                "top_routes": [r.model_dump(mode="json") for r in routes.rows],
                "convention": (f"long-haul = routes >= {p.threshold_mi:g} mi ({BANDS_DOC}); passenger share "
                               "weights departures with seats>0, freight share weights freight lb"),
                "provenance": prov([routes]), "truncated": routes.truncated}

    def get_live_status(p: LiveStatusArgs) -> dict[str, Any]:
        live = data.get_live_status(p.iata)
        out = live.model_dump(mode="json")
        # Only the live feed is dated by the fetch. The latest-month traffic riding along comes from
        # the snapshot; stamping it "as of now" would claim a freshness it does not have.
        snapshot = {v.source_id: v for v in data.source_vintages()}
        entries: list[Any] = []
        for source_id in live.source_ids:
            record = snapshot.get(source_id)
            entries.append((source_id, live.fetched_at) if source_id == LIVE_SOURCE or record is None
                           else record)
        out["provenance"] = prov(entries)
        return out

    def explain_metric(p: ExplainMetricArgs) -> dict[str, Any]:
        specs = {s.id: s for s in data.describe_metrics()}
        if p.metric_id not in specs:
            raise KeyError(f"unknown metric id: {p.metric_id!r}")
        spec = specs[p.metric_id]
        out = spec.model_dump(mode="json")
        out["pillar_name"] = PILLAR_NAMES[spec.pillar]
        return out

    def get_metric_series(p: MetricSeriesArgs) -> dict[str, Any]:
        series = data.get_metric_series(p.iata, p.metric_id)
        return {"iata": p.iata, "metric_id": p.metric_id,
                "series": [m.model_dump(mode="json") for m in series], "provenance": prov(series)}

    def list_sources(p: ListSourcesArgs) -> dict[str, Any]:
        vintages = data.source_vintages()
        return {"sources": [v.model_dump(mode="json") for v in vintages], "provenance": prov(vintages)}

    return [
        (ToolSpec(name="find_airports", params_model=FindAirportsArgs, fn=find_airports,
                 engines=[CONCIERGE, EXPANSION, MARKET, GENERAL],
                 description="List airports matching a filter (states, FAA regions, CBSA codes, IATA codes, hub "
                             "sizes, name substring). Returns at most `limit` airports (1-600, default 50); the truncated "
                             "flag is set when the limit was hit. No scoring - use score_airports to rank."),
         ProvenanceSpec.reads(*IDENTITY_SOURCES)),
        (ToolSpec(name="get_profile", params_model=GetProfileArgs, fn=get_profile, engines=list(ALL_ENGINES),
                 description="Structured profile of one airport: metrics per requested horizon, forecast, routes "
                             "summary, curated capacity facts, live status, data-quality notes and source "
                             "vintages. One airport per call; an unknown IATA code returns an error."),
         ProvenanceSpec.derived("cites the sources of the metrics returned for this airport")),
        (ToolSpec(name="get_route_stats", params_model=RouteStatsArgs, fn=get_route_stats,
                 engines=[CONCIERGE, CAPACITY, MARKET, GENERAL],
                 description="Route mix for one airport: distance-band shares and long-haul share for passengers "
                             f"and freight ({BANDS_DOC}; long-haul threshold default 1500 mi - state the "
                             "convention when quoting the share), plus the top routes by departures (top_n <= 50, "
                             "default 10, optionally filtered to international or domestic). The truncated flag "
                             "is set when more routes exist."),
         ProvenanceSpec.reads("bts_t100")),
        (ToolSpec(name="get_live_status", params_model=LiveStatusArgs, fn=get_live_status,
                 engines=[CONCIERGE, CAPACITY, GENERAL],
                 description="Current operational status of one airport: delay programs, ground stop, closure and "
                             "latest-month traffic, with the fetch time. Snapshot data - say so when quoting it."),
         ProvenanceSpec.reads("faa_nasstatus")),
        (ToolSpec(name="explain_metric", params_model=ExplainMetricArgs, fn=explain_metric,
                 engines=list(ALL_ENGINES),
                 description="Registry definition of one metric: definition, formula, unit, direction, pillar (and "
                             "pillar name), tier, sources, horizons and caveats. One metric per call; an unknown "
                             "metric id returns an error rather than an invented definition."),
         ProvenanceSpec.none("Definition from the metric registry (config/metrics.yaml), not measured data")),
        (ToolSpec(name="get_metric_series", params_model=MetricSeriesArgs, fn=get_metric_series,
                 engines=[CONCIERGE, EXPANSION, MARKET, GENERAL],
                 description="Annual series of one metric at one airport, at the metric's own declared horizon. "
                             "Returns an empty series for static and forecast metrics and for metrics unavailable "
                             "at that airport (never an invented number)."),
         ProvenanceSpec.derived("cites the source of the metric series returned")),
        (ToolSpec(name="list_sources", params_model=ListSourcesArgs, fn=list_sources,
                 engines=[CONCIERGE, GENERAL],
                 description="List every loaded data source with its description, the period it covers and its "
                             "fetch time. Takes no arguments. Use it to answer 'where does this number come "
                             "from'."),
         ProvenanceSpec.derived("lists the loaded sources, so it cites every one of them")),
    ]


def build_registry(data: DataService, analyst: DeterministicAnalyst) -> ToolRegistry:
    """Compose the full tool registry (data + analysis tools) for the Concierge and the specialists.

    The registry is given the DataService's vintage list so a declared-but-unreturned source is cited
    with its real date rather than a blank.
    """
    reg = ToolRegistry(source_vintages=data.source_vintages)
    for spec, provenance in [*build_data_tools(data, analyst), *build_analysis_tools(analyst)]:
        reg.register(spec, provenance=provenance)
    return reg
