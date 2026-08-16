"""Planner: the Concierge's first LLM turn *is* the Plan (design 03 §Question classes → path).

One structured-output call returns a flat JSON object (`PLAN_SCHEMA`); this module maps it to the frozen
`Plan` contract plus a validated `PlanFilters` view, and from there to an `AnalysisRequest` for the
Deterministic Analyst / specialists. The system prompt is assembled from live objects (tool registry, metric
registry, preset list, specialist roster) so it can never drift from what the code actually offers.

Failure policy: malformed or off-vocabulary model output raises `ValueError` (the Concierge turns that into a
clarify answer); provider failures raise `LLMError` and propagate untouched. Nothing is guessed silently.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from airport_agent.agent.tables import PEER_GROUP_DISPLAY as PEER_GROUP_PROSE
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import (
    MAX_HINT_CHARS,
    MAX_HINT_CHARS_GENERAL,
    PILLAR_NAMES,
    AirportFilter,
    AnalysisRequest,
    Horizon,
    HubSize,
    LLMClient,
    MetricSpec,
    PeerGroup,
    Plan,
    QuestionType,
    SessionState,
)
from airport_agent.llm import parse_json_text

CONCIERGE = "concierge"
NONE = "none"  # sentinel for "unset" in the portable schema (no nullable types)

INTENTS = ["informational", "analytical", "followup", "clarify"]
QUESTION_TYPES = ["rank", "compare", "diagnose", "custom"]
HORIZON_VALUES = ["12m", "3y", "5y", "10y"]
HUB_SIZES = ["large", "medium", "small", "nonhub"]
PEER_GROUPS = ["hub_class", "region", "all"]
PRESET_NAMES = ["balanced", "terminal_expansion", "congestion_relief", "market_entry"]
DEFAULT_SPECIALISTS = ["expansion_analyst", "capacity_analyst", "market_analyst", "general_analyst"]
ENGINE_VALUES = ["tools", "deterministic", *[f"specialist:{s}" for s in DEFAULT_SPECIALISTS]]

#: The four assignment questions, verbatim (used in the prompt's routing table and in golden tests).
SAMPLE_QUESTIONS = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
]

#: Roster guidance (design 03 §Roster). Keys must cover every configured specialist name.
SPECIALIST_GUIDE = {
    "expansion_analyst": "composite 'where to invest' ranking across all five pillars; use for rank/compare of "
                         "terminal- or capacity-expansion candidates. Presets: terminal_expansion or balanced.",
    "capacity_analyst": "congestion, physical constraint and unmet demand ('and why'); P2 in full plus demand "
                        "absorption (load_factor, spill_proxy, upgauging), curated capacity facts, NPIAS "
                        "labels and live status. Preset: congestion_relief.",
    "market_analyst": "traffic mix, network breadth, catchment and financeability (pillars P3, P4, P5); use "
                      "for route/market/economic questions. Preset: market_entry.",
    "general_analyst": "fallback when the question maps to no other specialist cleanly; full registry, all "
                       "tools, question_type may be 'custom'. It must state which lens it adopted.",
}

_ANC_TOOL_CALL = '[{"tool": "get_route_stats", "args_json": "{\\"iata\\": \\"ANC\\"}"}]'

_ROUTING_TABLE = [
    (SAMPLE_QUESTIONS[0], "analytical / rank", "deterministic + specialist:expansion_analyst",
     "faa_regions=[ANE], scoring_preset=terminal_expansion, horizons=[5y]"),
    (SAMPLE_QUESTIONS[1], "analytical / compare", "deterministic + specialist:capacity_analyst",
     "airports=[LAX, SNA], scoring_preset=congestion_relief, horizons=[12m]"),
    (SAMPLE_QUESTIONS[2], "informational", "tools", "tool_calls=" + _ANC_TOOL_CALL),
    (SAMPLE_QUESTIONS[3], "analytical / diagnose", "deterministic + specialist:capacity_analyst",
     "airports=[SFO], horizons=[12m]"),
    ("is DEN's cargo growth sustainable? (maps to no specialist cleanly)", "analytical / custom",
     "deterministic + specialist:general_analyst", "airports=[DEN], question_type=custom"),
]

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS,
                   "description": "informational = fact lookup via tools; analytical = deterministic scoring "
                                  "plus one specialist; followup = answer from the previous reports when they "
                                  "already contain what is needed; clarify = one targeted question back."},
        "engines": {"type": "array", "items": {"type": "string", "enum": ENGINE_VALUES},
                    "description": "Engines to run. Empty for clarify and for follow-ups answered from memory."},
        "question_type": {"type": "string", "enum": [*QUESTION_TYPES, NONE],
                          "description": "Deterministic engine method; 'none' when no analysis is dispatched. "
                                         "'custom' is only valid with specialist:general_analyst."},
        "airports": {"type": "array", "items": {"type": "string"},
                     "description": "Explicit IATA codes, e.g. LAX. Empty when a region filter is used."},
        "states": {"type": "array", "items": {"type": "string"},
                   "description": "Two-letter state codes, e.g. MA, CT. Empty when unset."},
        "faa_regions": {"type": "array", "items": {"type": "string"},
                        "description": "FAA region codes, e.g. ANE for New England. Empty when unset."},
        "hub_sizes": {"type": "array", "items": {"type": "string", "enum": HUB_SIZES},
                      "description": "Hub classes to restrict to. Empty when unset."},
        "horizons": {"type": "array", "items": {"type": "string", "enum": HORIZON_VALUES},
                     "description": "Requested horizons. Empty means: use the default for the question type."},
        "scoring_preset": {"type": "string", "enum": [*PRESET_NAMES, NONE],
                           "description": "Fixed preset from config; 'none' leaves the engine default. Never "
                                          "invent weights or preset names."},
        "focus_metrics": {"type": "array", "items": {"type": "string"},
                          "description": "Metric ids from the registry to focus on. Empty when unset."},
        "peer_group": {"type": "string", "enum": [*PEER_GROUPS, NONE],
                       "description": "Percentile peer group; 'none' keeps the hub_class default."},
        "hint": {"type": "string",
                 "description": f"Free-text steer for the specialist, at most {MAX_HINT_CHARS} characters "
                                f"({MAX_HINT_CHARS_GENERAL} for general_analyst). Empty string when unset."},
        "tool_calls": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {
                          "tool": {"type": "string", "description": "Tool name from the list you were given."},
                          "args_json": {"type": "string",
                                        "description": "Arguments as a JSON object encoded in a string, e.g. "
                                                       "{\"iata\": \"ANC\"}."}},
                      "required": ["tool", "args_json"]},
            "description": "Data tools to run for informational intent. Empty otherwise."},
        "presentation_notes": {"type": "string",
                               "description": "How to present the answer (what to surface first, what to omit "
                                              "and why). Empty string when you have no preference."},
    },
}
PLAN_SCHEMA["required"] = list(PLAN_SCHEMA["properties"])

#: QA task 14 (2026-08-16): the one bounded retry after a tool rejects its arguments. Same portable
#: subset as PLAN_SCHEMA (no $ref/anyOf/additionalProperties — Gemini rejects them in response_schema).
REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "args_json": {"type": "string",
                      "description": "JSON object of arguments that the tool accepts, as a string. "
                                     "Only argument names from the schema you were given. '{}' if the "
                                     "user's request cannot be expressed with this tool's arguments."},
    },
}
REPAIR_SCHEMA["required"] = list(REPAIR_SCHEMA["properties"])

#: QA task 15 (human decision 2026-08-16): what "all airports" means when the user names no geography.
#: Commercial-service hubs only — the snapshot's other ~1,805 airports are nonhub GA fields that carry
#: no metric coverage, so ranking them would pad the list with noise rather than widen the answer.
NATIONAL_SCOPE_HUBS: list[HubSize] = ["large", "medium", "small"]
#: Headroom over the ~140 commercial-service airports that exist, so the default scope is never
#: silently truncated — the assumption line claims the whole set and must not be lying.
NATIONAL_SCOPE_LIMIT = 200


def national_scope() -> AirportFilter:
    """The default filter for an analytical question that named no airports, region or hub size."""
    return AirportFilter(hub_sizes=list(NATIONAL_SCOPE_HUBS), limit=NATIONAL_SCOPE_LIMIT)


def is_national_scope(req: AnalysisRequest | None) -> bool:
    """Did this request fall back to the national default (rather than a filter the user asked for)?"""
    f = req.filter if req is not None else None
    return bool(f and not f.states and not f.faa_regions and not f.cbsa_codes and not f.iatas
                and not f.name_contains and list(f.hub_sizes) == NATIONAL_SCOPE_HUBS
                and f.limit == NATIONAL_SCOPE_LIMIT)


class PlannedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args_json: str = "{}"

    def args(self) -> dict[str, Any]:
        """This call's arguments. Unparseable or non-object JSON yields {} — the tool then reports the
        missing required argument itself, which is how the model self-corrects."""
        try:
            parsed = json.loads(self.args_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


class PlanFilters(BaseModel):
    """Validated view of `Plan.filters` (which the frozen contract types as a plain dict)."""

    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType | None = None
    airports: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    faa_regions: list[str] = Field(default_factory=list)
    hub_sizes: list[HubSize] = Field(default_factory=list)
    horizons: list[Horizon] = Field(default_factory=list)
    scoring_preset: str | None = None
    focus_metrics: list[str] = Field(default_factory=list)
    hint: str = ""
    peer_group: PeerGroup | None = None
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)

    @field_validator("airports", "states", "faa_regions", mode="before")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            return v
        return [s.strip().upper() if isinstance(s, str) else s for s in v]

    def args_for(self, tool: str) -> dict[str, Any]:
        """Arguments planned for the first call of `tool` ({} when it was not planned or the JSON was bad)."""
        for call in self.tool_calls:
            if call.tool == tool:
                return call.args()
        return {}


def _unset(value: Any) -> str | None:
    """Map the schema's sentinels ('none', '', absent) to None."""
    return None if value in (None, "", NONE) else str(value)


def _target_text(airports: list[str], states: list[str], faa_regions: list[str],
                 hub_sizes: list[str]) -> str:
    if airports:
        return ", ".join(airports)
    parts = []
    if faa_regions:
        parts.append("region " + ",".join(faa_regions))
    if states:
        parts.append("states " + ",".join(states))
    if hub_sizes:
        parts.append("hub " + ",".join(hub_sizes))
    return " ".join(parts) or "—"


def _targets(filters: PlanFilters) -> str:
    return _target_text(filters.airports, filters.states, filters.faa_regions, list(filters.hub_sizes))


def _request_targets(req: AnalysisRequest) -> str:
    if is_national_scope(req):
        return "all commercial-service airports"  # QA task 15: the plan says so before it runs
    f = req.filter
    return _target_text(list(req.airports or []), list(f.states) if f else [],
                        list(f.faa_regions) if f else [], list(f.hub_sizes) if f else [])


def _default_horizon(question_type: QuestionType, preset: str | None) -> Horizon:
    if question_type == "diagnose" or (question_type == "compare" and preset == "congestion_relief"):
        return "12m"
    return "5y"


class Planner:
    """Turns a user message + session memory into a `Plan` with one structured-output LLM call."""

    def __init__(self, llm: LLMClient, registry: ToolRegistry, specs: list[MetricSpec], presets: list[str],
                 specialists: list[str] = DEFAULT_SPECIALISTS) -> None:
        unknown_presets = [p for p in presets if p not in PRESET_NAMES]
        if unknown_presets:
            raise ValueError(f"presets {unknown_presets} are absent from PLAN_SCHEMA; add them to PRESET_NAMES")
        unknown_specialists = [s for s in specialists if s not in SPECIALIST_GUIDE]
        if unknown_specialists:
            raise ValueError(f"no roster guidance for {unknown_specialists}; add them to SPECIALIST_GUIDE")
        self.llm = llm
        self.registry = registry
        self.specs = list(specs)
        self.presets = list(presets)
        self.specialists = list(specialists)

    # ---------------- prompt (assembled from live objects) ----------------

    def _tools_block(self) -> str:
        # QA task 14 (2026-08-16): the argument names are listed from the live tool models. Planning
        # args_json without them is guesswork, and a guessed key (e.g. domestic_only) is rejected.
        lines = []
        for spec in self.registry.for_engine(CONCIERGE):
            allowed, required = self.registry.arg_names(spec.name)
            rendered = ", ".join(f"{a}*" if a in required else a for a in allowed) or "no arguments"
            lines.append(f"- {spec.name} — {spec.description}\n  args: {rendered}")
        return ("TOOLS you may plan (informational intent only; at most ONE tool_calls entry per tool "
                "name — call a tool once with all its args; the Concierge executes each entry).\n"
                "args_json may use ONLY the argument names listed under each tool (* = required) — an "
                "invented key is rejected and the question goes unanswered. When the user asks for a cut "
                "the arguments cannot express, plan the closest call the tool does support and say so in "
                "presentation_notes, so the answer states the limitation instead of inventing a filter:\n"
                + "\n".join(lines))

    def _metrics_block(self) -> str:
        lines = []
        for pillar, pillar_name in PILLAR_NAMES.items():
            ids = [f"{s.id} ({s.name}){'*' if s.tier == 'B' else ''}"
                   for s in self.specs if s.pillar == pillar and s.tier != "C"]
            if ids:
                lines.append(f"- {pillar} {pillar_name}: " + "; ".join(ids))
        gaps = [s.id for s in self.specs if s.tier == "C"]
        if gaps:
            lines.append("- tier C — documented gaps, not computable from our data; never scored "
                         "(name them only as a limitation): " + ", ".join(gaps))
        return ("METRIC IDS (registry — focus_metrics must come from this list; never invent an id; "
                "* = tier B, curated data for major airports only):\n" + "\n".join(lines))

    def _specialists_block(self) -> str:
        lines = [f"- specialist:{name} — {SPECIALIST_GUIDE[name]}" for name in self.specialists]
        return ("SPECIALISTS (choose exactly one for an analytical question):\n" + "\n".join(lines)
                + f"\nThe hint is the only free-text channel: at most {MAX_HINT_CHARS} characters "
                  f"({MAX_HINT_CHARS_GENERAL} for general_analyst); it is truncated beyond that.")

    def _routing_block(self) -> str:
        rows = [f"- {question}\n    -> intent {intent}; engines {engines}; {fields}"
                for question, intent, engines, fields in _ROUTING_TABLE]
        return "SAMPLE ROUTING (follow these patterns):\n" + "\n".join(rows)

    @staticmethod
    def _defaults_block(defaults: dict[str, str] | None) -> str:
        items = [f"{k}={v}" for k, v in (defaults or {}).items() if v]
        if not items:
            return "USER DEFAULTS: none set."
        return "USER DEFAULTS (use unless the user says otherwise): " + "; ".join(items)

    @staticmethod
    def _session_block(state: SessionState | None) -> str:
        lines: list[str] = []
        if state is not None:
            if state.last_airports:
                lines.append("- last airports: " + ", ".join(state.last_airports))
            if state.last_filters:
                lines.append("- last filters: " + json.dumps(state.last_filters, default=str))
            if state.last_preset:
                lines.append(f"- last preset: {state.last_preset}")
            if state.last_reports:
                lines.append("- reports already in memory: " + ", ".join(sorted(state.last_reports)))
            for message in [m for m in state.messages if m.role in ("user", "assistant")][-6:]:
                lines.append(f"- {message.role}: {message.content[:400]}")
        if not lines:
            return "SESSION CONTEXT: none (first turn)."
        return "SESSION CONTEXT:\n" + "\n".join(lines)

    def system_prompt(self, defaults: dict[str, str] | None = None,
                      state: SessionState | None = None) -> str:
        """Assemble the planning prompt from live objects, so it cannot drift from the code."""
        blocks = [
            "You are the Concierge of an airport investment intelligence agent: US airports, capacity- and "
            "terminal-expansion investment. Your job on this turn is ONLY to plan — classify the question, "
            "choose engines, fill the filters, and say how the answer should be presented. You produce no "
            "numbers here and you never invent metrics, weights or presets.",

            "QUESTION CLASSES (each user message takes exactly one path):\n"
            "- informational -> data tools answer a fact/lookup; the Concierge presents the value with its "
            "provenance and offers a follow-up analysis.\n"
            "- analytical -> a structured request goes to the deterministic scoring engine AND to one LLM "
            "specialist; the two views are synthesized (disagreements are shown, never hidden).\n"
            "- followup -> resolve against the session memory (last reports, airports, filters, preset); "
            "re-dispatch only if the answer is not already there.\n"
            "- clarify -> ONLY when the message carries no answerable question at all (it is empty, "
            "unintelligible, or names nothing this product covers). A missing region, airport list, hub "
            "size or horizon is NEVER a reason to clarify: leave those keys unset and the engine ranks "
            "every commercial-service airport at the default horizon, which the answer states as an "
            "assumption. A themed question with no geography ('which airports gain most if Asian tourism "
            "grows', 'best bets for long-haul') is analytical, not clarify.",

            "ENGINE RULES:\n"
            "- analytical => engines = ['deterministic', 'specialist:<one name>'] (both), unless the user asks "
            "only for a formula or definition, in which case 'deterministic' alone is right.\n"
            "- informational => engines = ['tools'] plus one or more tool_calls.\n"
            "- followup => prefer the reports already in memory: set engines = [] and tool_calls = [] when "
            "they contain what is needed; otherwise plan as informational or analytical.\n"
            "- clarify => engines = [] and tool_calls = [].\n"
            "- Exactly one specialist per plan, never two.",

            self._tools_block(),

            "SCORING PRESETS (fixed in config; pick one or 'none' — never invent weights): "
            + ", ".join(self.presets) + "\n"
            "- A generic investment question with no stated focus ('should I invest in X', 'how much "
            "to invest') takes 'balanced'; pick a focused preset only when the question names that "
            "focus (terminal/gates, congestion/runways, market entry).\n"
            "- A rank over a single named airport is automatically expanded to its hub-size peers by "
            "the deterministic engine, so ranking one airport IS a valid plan for 'should I invest "
            "in X' questions.",

            self._specialists_block(),
            self._metrics_block(),

            "CONVENTIONS (they must be stated in the answer whenever they are used):\n"
            "- long-haul = a route of 1,500 statute miles or more (default threshold).\n"
            "- unmet demand is judged with a spill model (load-factor dispersion, upgauging, delay), never an "
            "absolute load-factor cutoff.\n"
            "- percentiles are computed within hub class (peer_group=hub_class) unless the user widens them.\n"
            "- horizon defaults: 5y for rank/compare of investment candidates, 12m for congestion "
            "compare/diagnose and for informational lookups.",

            self._routing_block(),
            self._defaults_block(defaults),
            self._session_block(state),

            "Sentinels: 'none' for an unset enum, [] for an unset list, '' for unset text. Every key is "
            "required. Output ONLY the JSON object — no prose, no code fence.",
        ]
        return "\n\n".join(blocks)

    # ---------------- planning ----------------

    def plan(self, message: str, state: SessionState,
             defaults: dict[str, str] | None = None) -> tuple[Plan, PlanFilters]:
        """One structured-output call. Raises ValueError on unusable output, LLMError on provider failure."""
        messages = [{"role": "system", "content": self.system_prompt(defaults, state)},
                    {"role": "user", "content": message}]
        result = self.llm.chat(messages=messages, response_schema=PLAN_SCHEMA, temperature=0.1)
        return self._parse(parse_json_text(result.text))

    def repair_tool_args(self, tool: str, args: dict[str, Any], error: str,
                         message: str) -> dict[str, Any] | None:
        """One bounded retry for a tool call the registry rejected (QA task 14).

        The validation error and the tool's real argument list go back to the model, which either
        re-expresses the intent with supported arguments (domestic_only -> international=false) or
        gives up. Returns the corrected arguments, or None when it could not fix them. Never raises
        on bad model output — the caller has a deterministic fallback.
        """
        try:
            spec = self.registry.get(tool)
        except KeyError:
            return None
        prompt = (f"A planned call to the tool `{tool}` was rejected by argument validation. Rewrite the "
                  f"arguments so the call runs, keeping as much of the user's intent as the tool can "
                  f"actually express. Drop what it cannot express — never invent an argument name.\n\n"
                  f"TOOL: {tool} — {spec.description}\n"
                  f"{self.registry.args_help(tool)}\n"
                  f"JSON SCHEMA: {json.dumps(spec.params_model.model_json_schema())}\n"
                  f"REJECTED ARGUMENTS: {json.dumps(args)}\nVALIDATION ERROR: {error}\n"
                  f"USER QUESTION: {message}\n\n"
                  "Return args_json = a JSON object of valid arguments as a string ({} if none can be "
                  "salvaged). Output ONLY the JSON object.")
        try:
            result = self.llm.chat(messages=[{"role": "system", "content": prompt},
                                             {"role": "user", "content": message}],
                                   response_schema=REPAIR_SCHEMA, temperature=0.0)
            raw = parse_json_text(result.text)
        except (ValueError, TypeError):
            return None
        try:
            fixed = json.loads(raw.get("args_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        return fixed if isinstance(fixed, dict) else None

    def _parse(self, raw: dict[str, Any]) -> tuple[Plan, PlanFilters]:
        clarify = raw.get("intent") == "clarify"  # a clarify turn executes nothing: no engines, no tools
        filters = PlanFilters(
            question_type=_unset(raw.get("question_type")),
            airports=raw.get("airports") or [],
            states=raw.get("states") or [],
            faa_regions=raw.get("faa_regions") or [],
            hub_sizes=raw.get("hub_sizes") or [],
            horizons=raw.get("horizons") or [],
            scoring_preset=_unset(raw.get("scoring_preset")),
            focus_metrics=raw.get("focus_metrics") or [],
            hint=raw.get("hint") or "",
            peer_group=_unset(raw.get("peer_group")),
            tool_calls=[] if clarify else (raw.get("tool_calls") or []),
        )
        engines = [] if clarify else list(raw.get("engines") or [])
        allowed = {"tools", "deterministic", *[f"specialist:{s}" for s in self.specialists]}
        unknown = [e for e in engines if e not in allowed]
        if unknown:
            raise ValueError(f"plan names unknown engines {unknown}; allowed: {sorted(allowed)}")
        chosen = [e.split(":", 1)[1] for e in engines if e.startswith("specialist:")]
        if len(chosen) > 1:
            raise ValueError(f"plan names more than one specialist: {chosen}")
        plan = Plan(intent=raw.get("intent"), engines=engines, filters=filters.model_dump(),
                    tools_to_call=[c.tool for c in filters.tool_calls],
                    specialist=chosen[0] if chosen else None,
                    presentation_notes=raw.get("presentation_notes") or "")
        return plan, filters

    # ---------------- dispatch ----------------

    def to_analysis_request(self, plan: Plan, filters: PlanFilters,
                            defaults: dict[str, str] | None) -> AnalysisRequest:
        """Map the plan onto the frozen dispatch contract.

        A request with neither airports nor a filter falls back to the national scope (QA task 15,
        human decision 2026-08-16): a question with a theme but no geography is answerable, so it is
        answered over every commercial-service airport and the answer states that as an assumption.
        Asking the user where to look was the wrong default — it stalled real questions.
        """
        user_defaults = defaults or {}
        question_type = filters.question_type
        if question_type is None:
            if plan.specialist == "general_analyst":
                question_type = "custom"  # only general_analyst may take 'custom' (frozen contract)
            else:
                question_type = "compare" if filters.airports else "rank"
        preset = filters.scoring_preset or user_defaults.get("scoring_preset") or None
        horizons = list(filters.horizons)
        if not horizons:
            default_horizon = user_defaults.get("horizon")
            horizons = [default_horizon] if default_horizon else [_default_horizon(question_type, preset)]
        airports = filters.airports or None
        airport_filter = None
        if airports is None and (filters.states or filters.faa_regions or filters.hub_sizes):
            airport_filter = AirportFilter(states=filters.states, faa_regions=filters.faa_regions,
                                           hub_sizes=filters.hub_sizes, limit=50)
        elif airports is None:
            airport_filter = national_scope()
        return AnalysisRequest(question_type=question_type, airports=airports, filter=airport_filter,
                               horizons=horizons,
                               peer_group=filters.peer_group or user_defaults.get("peer_group") or None,
                               scoring_preset=preset, focus_metrics=filters.focus_metrics or None,
                               hint=filters.hint, specialist=plan.specialist)

    @staticmethod
    def plan_line(plan: Plan, filters: PlanFilters, req: AnalysisRequest | None = None) -> str:
        """The one-line plan shown to the user before execution (design 03 §Presentation).

        With a resolved `AnalysisRequest` the line shows what will actually run (horizon, preset and peer
        group after defaults and engine rules), so the user is never shown a plan the engines did not get.
        """
        engines = ", ".join(plan.engines) or "none"
        if req is not None:
            focus = (req.scoring_preset or "balanced").replace("_", " ")
            return (f"How I'm approaching this: {plan.intent} · {req.question_type} · "
                    f"{_request_targets(req)} · time period {', '.join(req.horizons) or '-'} · "
                    f"{focus} focus · "
                    f"peers: {PEER_GROUP_PROSE.get(req.peer_group or 'hub_class', req.peer_group)} · "
                    f"engines: {engines}")
        focus = (filters.scoring_preset or "-").replace("_", " ")
        return (f"How I'm approaching this: {plan.intent} · {filters.question_type or 'lookup'} · "
                f"{_targets(filters)} · time period {', '.join(filters.horizons) or '-'} · "
                f"{focus} focus · engines: {engines}")
