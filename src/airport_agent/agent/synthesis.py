"""Synthesizer: "structure + agency" (design 03 §Answer synthesis).

The structure is code-enforced — plan line, headline, evidence tables, analyst view, agreement line,
assumptions and uncertainty, follow-ups — and every number in it comes from a report or a tool result. The
LLM's agency is limited to the headline, the analyst summary, WHICH metric rows to surface (it must say what
it hid) and the follow-up questions.

If the synthesis JSON cannot be parsed the answer is still produced from the reports and says
"synthesis text unavailable — showing raw report": that is formatting degradation, not reasoning
degradation. A provider failure (`LLMError`) still propagates untouched.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from airport_agent.agent.debuglog import DebugLog, NullDebugLog
from airport_agent.agent.planner import is_national_scope
from airport_agent.agent.specialists.runner import compact_deterministic, fit_tool_result
from airport_agent.agent.table_display import apply_display_policy
from airport_agent.agent.tables import (
    citations_from,
    data_matrix,
    humanize_metric_ids,
    humanize_tool_ids,
    peer_label,
    provenance_table,
    ranking_table,
    specialist_ranking_table,
    tool_label,
    tool_result_tables,
)
from airport_agent.contracts import (
    AnalysisRequest,
    Answer,
    DeterministicReport,
    LLMClient,
    Metric,
    MetricSpec,
    Plan,
    SpecialistReport,
    Table,
    ToolCallTrace,
    registry_by_id,
)
from airport_agent.llm import parse_json_text

MAX_SYNTHESIS_TOOL_CHARS = 2000
FALLBACK_NOTE = "synthesis text unavailable — showing raw report"
FALLBACK_HEADLINE = "Results below."
FALLBACK_FOLLOW_UPS = ["Compare with peer airports?", "Try another horizon?", "Try another preset?"]
CONVENTION_MARKERS = ("convention", "spill model", "long-haul", "percentile")
#: Decision 2026-08-16 (row 65): report caveats reach the ANSWER only from this allow-list — the
#: assumptions/uncertainty blocks are a curated surface, not a drain for every methodology note the
#: engines record. Everything else stays on the report, visible in "Show work" and the archive.
#: Matched case-insensitively as substrings.
ALLOWED_ASSUMPTION_MARKERS = ("long-haul =",)          # the convention actually used by the answer
ALLOWED_NOTE_MARKERS = ("ranked against its",)         # the single-airport peer-expansion disclosure
#: Assumptions/uncertainty are condensed DETERMINISTICALLY to a hard cap — the LLM may add lines
#: via the specialist but can never remove one. Build-level standing tradeoffs live in the docs,
#: not in every answer.
MAX_ASSUMPTIONS = 7  # + the defaults line = 8 rows max
MAX_NOTES = 8
#: The settings the UI supplies, stated in plain English rather than as an internal k=v dump.
#: Each entry renders one default; unknown keys fall back to "key=value".
DEFAULT_PROSE: dict[str, Any] = {
    "horizon": lambda v: f"time period {v}",
    "scoring_preset": lambda v: f"{str(v).replace('_', ' ')} weights",
    "peer_group": lambda v: f"peer comparison against {peer_label(str(v))}",
}

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string",
                     "description": "1-2 sentences answering the question. Only numbers that appear in the "
                                    "inputs; no new figures, no re-rounding."},
        "show_metrics": {"type": "array", "items": {"type": "string"},
                         "description": "Metric ids to surface in the evidence table, most relevant first. "
                                        "Must be ids present in the inputs. Empty means show all."},
        "hidden_reason": {"type": "string",
                          "description": "Why the other metrics are collapsed (the user is told). Empty "
                                         "string when nothing was hidden."},
        "analyst_summary": {"type": "string",
                            "description": "Optional 2-4 sentence rendering of the specialist's view. Empty "
                                           "string to show the specialist's own narrative verbatim."},
        "follow_ups": {"type": "array", "items": {"type": "string"},
                       "description": "Exactly 3 short follow-up questions the user could ask next."},
    },
}
SYNTHESIS_SCHEMA["required"] = list(SYNTHESIS_SCHEMA["properties"])

SYSTEM_PROMPT = """You write the narration around an airport-investment answer that is already assembled by
code. The structure is fixed and you cannot change it: plan line, headline, evidence tables (rendered from the
reports), analyst view, agreement line, assumptions and uncertainty, follow-ups.

Your only outputs are the headline, which metric rows to surface, why the rest are collapsed, an optional
rendering of the specialist's view, and three follow-up questions.

Rules:
- Never state a number that is not in the inputs below, and never re-round or re-scale one. The tables carry
  the numbers with their sources; you carry the meaning.
- Never invent a metric id, a preset or a weight. show_metrics must be ids that appear in the inputs.
- If you collapse metrics, hidden_reason must say why in the user's terms.
- If the specialist disagrees with the formula, the headline must not hide it.
- The headline is 1-2 sentences and answers the question that was asked.
Output ONLY the JSON object."""


class _Synthesis(BaseModel):
    headline: str
    show_metrics: list[str] = Field(default_factory=list)
    hidden_reason: str = ""
    analyst_summary: str = ""
    follow_ups: list[str] = Field(default_factory=list)


#: What each tool was doing, in the user's words, for the "used for" column.
TOOL_PURPOSE: dict[str, str] = {
    "find_airports": "the airport list",
    "get_profile": "the airport profile",
    "get_route_stats": "route mix and long-haul share",
    "get_live_status": "live operational status",
    "get_metric_series": "the metric series",
    "list_sources": "the source list",
    "explain_metric": "the metric definition",
    "score_airports": "the computed analysis",
    "compare_airports": "the computed analysis",
    "diagnose_unmet_demand": "the computed analysis",
}


def _metric_provenance(metrics: list[Metric]) -> list[dict[str, str]]:
    """Provenance entries for the scored metrics, so the table covers the deterministic side too.

    Only metrics that actually carry a value: a registry metric keeps its nominal source_id even when
    the snapshot holds nothing for it, and citing those would credit sources we never read.
    """
    return [{"source_id": m.source_id, "vintage": m.vintage,
             **({"period_start": m.period_start} if m.period_start else {}),
             **({"period_end": m.period_end} if m.period_end else {})}
            for m in metrics if m.source_id and m.value is not None]


def _first_sentence(text: str) -> str:
    head = text.strip().split(". ")[0].strip()
    return head or FALLBACK_HEADLINE


def _defaults_assumption(defaults: dict[str, str] | None, national_scope: bool = False) -> str:
    """The closing assumption row, built from modules — one per setting the answer fell back on,
    " · "-joined so it scans as a list, not a paragraph (decision 2026-08-16, row 65). The national
    scope fallback is one of the modules: it IS a default applied because the question named no
    geography. Empty string when nothing was defaulted — a line that says "nothing assumed" says
    nothing.

    Phrased as "where the question didn't specify" because the planner may legitimately override a
    default from the question itself — the answer must not claim more than it knows.
    """
    parts = [DEFAULT_PROSE[key](value) for key, value in (defaults or {}).items()
             if value and key in DEFAULT_PROSE]
    parts += [f"{key}={value}" for key, value in (defaults or {}).items()
              if value and key not in DEFAULT_PROSE]
    if national_scope:
        parts.append("scope = all commercial-service airports (no geography was named)")
    if not parts:
        return ""
    return "Where the question didn't specify: " + " · ".join(parts)


def _compact_specialist(rep: SpecialistReport) -> dict[str, Any]:
    return {"specialist": rep.specialist, "narrative": rep.narrative, "agreement": rep.agreement,
            "disagreements": rep.disagreements, "confidence": rep.confidence,
            "assumptions": rep.assumptions, "caveats": rep.caveats,
            "ranking": [item.model_dump() for item in rep.ranking or []]}


def _metric_ids(deterministic: DeterministicReport | None) -> list[str]:
    if deterministic is None:
        return []
    ids = [m.id for m in deterministic.evidence]
    ids += list((deterministic.comparison or {}).keys())
    return sorted(set(ids))


class Synthesizer:
    """Turns the engines' outputs into the fixed `Answer` structure with one LLM call for the prose."""

    def __init__(self, llm: LLMClient, specs: list[MetricSpec], *,
                 debug: DebugLog | NullDebugLog | None = None) -> None:
        self.llm = llm
        self.specs = list(specs)
        self.by_id = registry_by_id(self.specs)
        #: Dev-time JSONL mirror of what the curation dropped (debuglog design, 2026-08-16).
        self.debug = debug if debug is not None else NullDebugLog()

    # prose

    def _user_message(self, *, message: str, plan: Plan, req: AnalysisRequest | None,
                      deterministic: DeterministicReport | None, specialist: SpecialistReport | None,
                      tool_results: list[tuple[str, dict, dict]],
                      defaults: dict[str, str] | None, history: str = "") -> str:
        blocks = [f"User question: {message}",
                  "Plan: " + json.dumps({"intent": plan.intent, "engines": plan.engines,
                                         "presentation_notes": plan.presentation_notes})]
        if history:
            # The same summary + recent digests the planner saw, so the prose can refer back to what
            # was said ("as in turn 2, BOS still leads") instead of being written blind.
            blocks.append(history)
        if req is not None:
            blocks.append("Resolved request: " + req.model_dump_json())
        if deterministic is not None:
            blocks.append("Deterministic view: " + json.dumps(compact_deterministic(deterministic)))
            blocks.append("Metric ids available for show_metrics: " + ", ".join(_metric_ids(deterministic)))
        if specialist is not None:
            blocks.append("Specialist view: " + json.dumps(_compact_specialist(specialist)))
        for tool, args, out in tool_results:
            blocks.append(f"Tool {tool} {json.dumps(args)} -> "
                          + fit_tool_result(out, MAX_SYNTHESIS_TOOL_CHARS))
        if defaults:
            blocks.append("UI defaults in force: " + json.dumps(defaults))
        return "\n\n".join(blocks)

    def _prose(self, user: str) -> tuple[_Synthesis, bool]:
        """Returns (synthesis, degraded). LLMError propagates; unusable JSON degrades formatting only."""
        result = self.llm.chat(messages=[{"role": "system", "content": SYSTEM_PROMPT},
                                         {"role": "user", "content": user}],
                               response_schema=SYNTHESIS_SCHEMA, temperature=0.3)
        try:
            return _Synthesis(**parse_json_text(result.text)), False
        except ValueError:
            return _Synthesis(headline="", follow_ups=list(FALLBACK_FOLLOW_UPS)), True

    # assembly (numbers never pass through the model)

    def synthesize(self, *, message: str, plan: Plan, plan_line: str, req: AnalysisRequest | None,
                   deterministic: DeterministicReport | None, specialist: SpecialistReport | None,
                   tool_results: list[tuple[str, dict, dict]], trace: list[ToolCallTrace],
                   defaults: dict[str, str] | None,
                   extra_notes: list[str] | None = None,
                   shown_tables: dict[str, int] | None = None, turn: int = 1,
                   history: str = "", session_id: str = "") -> Answer:
        """`extra_notes` are uncertainty lines the orchestrator knows and the reports cannot see —
        currently the live-call ceiling (QA task 20). They are condensed with the rest, never above it.

        `shown_tables` is the session's table memory (content hash -> first turn) and `turn` this
        answer's 1-based number; together with `plan.table_display` they decide which tables render
        in full and which collapse to a pointer. Passing neither means "first turn, show everything"."""
        synthesis, degraded = self._prose(self._user_message(
            message=message, plan=plan, req=req, deterministic=deterministic, specialist=specialist,
            tool_results=tool_results, defaults=defaults, history=history))

        tables: list[Table] = []
        assumptions: list[str] = []
        notes: list[str] = list(extra_notes or [])
        metrics: list[Metric] = []
        provenance: list[dict] = []
        covers: dict[str, list[str]] = {}
        provenance_notes: list[str] = []

        if deterministic is not None:
            metrics.extend(deterministic.evidence)
            for metric in deterministic.evidence:
                covers.setdefault(metric.source_id, []).append("the computed analysis")
            # Every analytical answer opens its computed section with the score view (pillar-level
            # contributions); a single airport gets "Scores" without a rank column.
            if deterministic.rows:
                tables.append(ranking_table(deterministic))
            # ONE canonical data matrix, always shown — metric rows, a value column per airport,
            # percentiles and provenance together. No separate evidence table, nothing collapsed behind
            # an expander, and the LLM cannot choose to hide rows.
            matrix = data_matrix(deterministic, self.by_id)
            if matrix.rows:
                tables.append(matrix)
            assumptions.extend(self._report_assumptions(req, deterministic))
            notes.extend(self._report_notes(deterministic))
        elif req is not None:
            assumptions.extend(self._report_assumptions(req, None))

        if specialist is not None:
            analyst_table = specialist_ranking_table(specialist, self.by_id)
            if analyst_table is not None:
                tables.append(analyst_table)
            metrics.extend(specialist.evidence)
            # Decision 2026-08-16 (row 65): the analyst may add AT MOST one assumption and one
            # caveat, 100 chars each — the schema says so (maxItems 1) and this clamp enforces it
            # deterministically. Its confidence is on the report (Show work), not a note.
            assumptions.extend(_clamp_analyst_lines(specialist.assumptions))
            notes.extend(_clamp_analyst_lines(specialist.caveats))
            if specialist.hint_truncated:
                notes.append("The steer sent to the specialist was truncated to its character limit")

        for tool, _args, out in tool_results:
            tables.extend(tool_result_tables(tool, out, self.by_id))
            entries = out.get("provenance") or []
            provenance.extend(entries)
            # Remember which tool each source served, so the provenance table can say what it was
            # used for instead of listing bare source names.
            for entry in entries:
                covers.setdefault(entry.get("source_id", ""), []).append(
                    TOOL_PURPOSE.get(tool, tool_label(tool)))
            if out.get("provenance_note"):
                provenance_notes.append(str(out["provenance_note"]))
            assumptions.extend(self._tool_assumptions(out))
        notes.extend(self._tool_failures(tool_results))

        if degraded:
            notes.append(FALLBACK_NOTE)
        # Every answer closes with where its data came from. Metric tables carry inline source
        # columns; this covers everything that does not (airports, live status, distance bands,
        # rankings), so no table is left unattributed.
        sources_table = provenance_table([*_metric_provenance(metrics), *provenance], covers,
                                         provenance_notes)
        if sources_table is not None:
            tables.append(sources_table)
        # Last, so every table (computed, analyst, tool, sources) goes through the same rule.
        tables = apply_display_policy(tables, shown_tables if shown_tables is not None else {},
                                      plan.table_display, turn=turn)
        # Condense deterministically — the LLM never picks which lines survive.
        assumptions = _unique(assumptions)[:MAX_ASSUMPTIONS]  # tail line cut by decision, row 65
        unique_notes = _unique(notes)
        notes_before_cap = len(unique_notes)
        notes = _condense(unique_notes, MAX_NOTES, "further minor notes omitted")
        # The closing line: every setting the answer fell back on, one module each. Omitted entirely
        # when nothing was defaulted (row 65 — the old "nothing was assumed" filler said nothing).
        closing = _defaults_assumption(defaults, national_scope=is_national_scope(req))
        if closing:
            assumptions.append(closing)

        headline = synthesis.headline.strip()
        if not headline:
            headline = _first_sentence(deterministic.explanation) if deterministic else FALLBACK_HEADLINE
        analyst_view = None
        agreement_line = None
        if specialist is not None:
            analyst_view = synthesis.analyst_summary.strip() or specialist.narrative
            disagreements = "; ".join(specialist.disagreements) or "none stated"
            # The line reads against the computed score shown at the top of the answer.
            agreement_line = (f"On the computed score: {specialist.agreement or 'no statement given'}. "
                              f"Where the analyst differs from the numbers: {disagreements}.")
        follow_ups = [f for f in synthesis.follow_ups if f.strip()][:4] or list(FALLBACK_FOLLOW_UPS)

        # LLM prose never shows internal metric ids — a deterministic backstop over every text
        # surface (the tables already use display names by construction).
        headline = humanize_tool_ids(humanize_metric_ids(headline, self.by_id))
        analyst_view = humanize_tool_ids(humanize_metric_ids(analyst_view, self.by_id)) if analyst_view else None
        agreement_line = (humanize_tool_ids(humanize_metric_ids(agreement_line, self.by_id))
                          if agreement_line else None)
        assumptions = [humanize_tool_ids(humanize_metric_ids(a, self.by_id)) for a in assumptions]
        notes = [humanize_tool_ids(humanize_metric_ids(n, self.by_id)) for n in notes]

        # Dev-time mirror of what the row-65 curation dropped from this answer's surface.
        allowed = ALLOWED_ASSUMPTION_MARKERS + ALLOWED_NOTE_MARKERS
        self.debug.log(
            session_id, turn, "answer_curation",
            dropped_report_caveats=[c for c in (deterministic.caveats if deterministic else [])
                                    if not any(m in c.lower() for m in allowed)],
            analyst_assumptions_raw=list(specialist.assumptions) if specialist else [],
            analyst_assumptions_kept=_clamp_analyst_lines(specialist.assumptions) if specialist else [],
            analyst_caveats_raw=list(specialist.caveats) if specialist else [],
            analyst_caveats_kept=_clamp_analyst_lines(specialist.caveats) if specialist else [],
            notes_before_cap=notes_before_cap)

        return Answer(plan=plan, plan_line=plan_line, headline=headline, evidence_tables=tables,
                      analyst_view=analyst_view, agreement_line=agreement_line,
                      assumptions=_unique(assumptions), uncertainty_notes=_unique(notes),
                      citations=citations_from(metrics, provenance), follow_ups=follow_ups,
                      tool_trace=list(trace))

    # assumption / uncertainty sources

    @staticmethod
    def _report_assumptions(req: AnalysisRequest | None,
                            rep: DeterministicReport | None) -> list[str]:
        preset = (rep.preset if rep else None) or (req.scoring_preset if req else None) or "engine default"
        horizon = (rep.horizon if rep else None) or (req.horizons[0] if req and req.horizons else "-")
        peer_group = (rep.peer_group if rep else None) or (req.peer_group if req else None) or "hub_class"
        # One line for the request-shaping choices instead of three; standing build facts (tier
        # policy etc.) live in the docs. "preset" is an internal word, so the user sees the focus
        # instead, as in the table titles.
        out = [f"Scoring weights: {preset.replace('_', ' ')} · time period {horizon} · "
               f"percentiles vs {peer_label(peer_group)}"]
        # The national-scope fallback is stated as a module of the closing defaults line, not here.
        if rep is not None:
            out += [c for c in rep.caveats
                    if any(m in c.lower() for m in ALLOWED_ASSUMPTION_MARKERS)]
        return out

    @staticmethod
    def _report_notes(rep: DeterministicReport) -> list[str]:
        """The report caveats that survive into the answer: the allow-list only (row 65). The full
        set — quality flags, tier policy, weighting mechanics, per-metric nuances — stays on the
        report itself, one click away in "Show work"."""
        return [c for c in rep.caveats if any(m in c.lower() for m in ALLOWED_NOTE_MARKERS)]

    @staticmethod
    def _tool_assumptions(out: dict[str, Any]) -> list[str]:
        convention = out.get("convention")
        return [str(convention)] if convention else []

    @staticmethod
    def _tool_failures(tool_results: list[tuple[str, dict, dict]]) -> list[str]:
        """One modular line naming every tool that errored, by its user-facing name (decision
        2026-08-16, row 65 — the per-tool limitation/truncation/coverage notes were cut as bloat;
        the details stay in "Show work"). Empty when everything ran."""
        notes: list[str] = []
        # KEPT from the old per-tool notes (the one exception to the row-65 cut): a request the
        # tools could not express — the answer must say it shows a different cut than was asked
        # for (product rule: no silent degradation). Rare: only fires on unsupported arguments.
        for tool, _args, out in tool_results:
            if out.get("limitation"):
                notes.append(f"{tool_label(tool)}: {out['limitation']}")
        failed = [tool_label(tool) for tool, _args, out in tool_results if out.get("error")]
        if failed:
            names = " and ".join([", ".join(failed[:-1]), failed[-1]]) if len(failed) > 1 else failed[0]
            plural = "them" if len(failed) > 1 else "it"
            notes.append(f"{names} errored — answered without {plural}")
        return notes


ANALYST_LINE_CHARS = 100


def _clamp_analyst_lines(items: list[str]) -> list[str]:
    """At most ONE analyst-written line, truncated to ANALYST_LINE_CHARS with an ellipsis (decision
    2026-08-16, row 65). The schema asks for this (maxItems 1, "100 characters MAXIMUM"); this is
    the deterministic backstop for a model that ignores it."""
    for line in items:
        text = line.strip()
        if text:
            if len(text) > ANALYST_LINE_CHARS:
                text = text[: ANALYST_LINE_CHARS - 1].rstrip() + "…"
            return [text]
    return []


def _condense(items: list[str], cap: int, tail: str) -> list[str]:
    """Keep the first `cap` lines (they are appended in priority order); summarize the rest.

    Deterministic by design: nothing decides per-line importance at runtime, so the cut is
    predictable and the omitted count is always disclosed.
    """
    if len(items) <= cap:
        return items
    kept = items[: cap - 1]
    return [*kept, f"+{len(items) - len(kept)} {tail}"]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out
