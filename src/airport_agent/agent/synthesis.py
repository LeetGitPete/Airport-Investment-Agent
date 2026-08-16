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

from airport_agent.agent.specialists.runner import compact_deterministic, fit_tool_result
from airport_agent.agent.tables import (
    citations_from,
    data_matrix,
    humanize_metric_ids,
    peer_label,
    ranking_table,
    specialist_ranking_table,
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
BASELINE_ASSUMPTION = ("Every number shown comes from a cited source at the vintage listed; nothing "
                       "is estimated or adjusted by the model")
CONVENTION_MARKERS = ("convention", "spill model", "long-haul", "percentile")
#: QA task 7 (human decision 2026-08-16): assumptions/uncertainty are condensed DETERMINISTICALLY
#: to a hard cap — the LLM may add lines via the specialist but can never remove one. Build-level
#: standing tradeoffs live in the docs, not in every answer.
MAX_ASSUMPTIONS = 7  # + the baseline line = 8 rows max
MAX_NOTES = 8

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


def _first_sentence(text: str) -> str:
    head = text.strip().split(". ")[0].strip()
    return head or FALLBACK_HEADLINE


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

    def __init__(self, llm: LLMClient, specs: list[MetricSpec]) -> None:
        self.llm = llm
        self.specs = list(specs)
        self.by_id = registry_by_id(self.specs)

    # ---------------- prose ----------------

    def _user_message(self, *, message: str, plan: Plan, req: AnalysisRequest | None,
                      deterministic: DeterministicReport | None, specialist: SpecialistReport | None,
                      tool_results: list[tuple[str, dict, dict]],
                      defaults: dict[str, str] | None) -> str:
        blocks = [f"User question: {message}",
                  "Plan: " + json.dumps({"intent": plan.intent, "engines": plan.engines,
                                         "presentation_notes": plan.presentation_notes})]
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

    # ---------------- assembly (numbers never pass through the model) ----------------

    def synthesize(self, *, message: str, plan: Plan, plan_line: str, req: AnalysisRequest | None,
                   deterministic: DeterministicReport | None, specialist: SpecialistReport | None,
                   tool_results: list[tuple[str, dict, dict]], trace: list[ToolCallTrace],
                   defaults: dict[str, str] | None) -> Answer:
        synthesis, degraded = self._prose(self._user_message(
            message=message, plan=plan, req=req, deterministic=deterministic, specialist=specialist,
            tool_results=tool_results, defaults=defaults))

        tables: list[Table] = []
        assumptions: list[str] = []
        notes: list[str] = []
        metrics: list[Metric] = []
        provenance: list[dict] = []

        if deterministic is not None:
            metrics.extend(deterministic.evidence)
            # QA task 6: every analytical answer opens its computed section with the score view
            # (pillar-level contributions); a single airport gets "Scores" without a rank column.
            if deterministic.rows:
                tables.append(ranking_table(deterministic))
            # QA task 5: ONE canonical data matrix, always shown — metric rows, a value column per
            # airport, percentiles and provenance together. No separate evidence table, nothing
            # collapsed behind an expander, and the LLM cannot choose to hide rows.
            matrix = data_matrix(deterministic, self.by_id)
            if matrix.rows:
                tables.append(matrix)
            # QA 2026-08-16: the templated explanation is no longer appended below the first table
            # (poor placement); it still backs the fallback headline and the LLM synthesis input.
            assumptions.extend(self._report_assumptions(req, deterministic))
            notes.extend(self._report_notes(deterministic))
        elif req is not None:
            assumptions.extend(self._report_assumptions(req, None))

        if specialist is not None:
            analyst_table = specialist_ranking_table(specialist, self.by_id)
            if analyst_table is not None:
                tables.append(analyst_table)
            metrics.extend(specialist.evidence)
            assumptions.extend(specialist.assumptions)
            notes.append(f"Specialist confidence {specialist.confidence:.2f}")
            notes.extend(specialist.caveats)
            if specialist.hint_truncated:
                notes.append("The steer sent to the specialist was truncated to its character limit")

        for tool, _args, out in tool_results:
            tables.extend(tool_result_tables(tool, out, self.by_id))
            provenance.extend(out.get("provenance") or [])
            assumptions.extend(self._tool_assumptions(out))
            notes.extend(self._tool_notes(tool, out))

        if defaults:
            assumptions.append("UI defaults applied: "
                               + ", ".join(f"{k}={v}" for k, v in defaults.items() if v))
        if degraded:
            notes.append(FALLBACK_NOTE)
        # QA task 7 (human decision 2026-08-16): condense deterministically — the LLM never picks.
        assumptions = _condense(_unique(assumptions), MAX_ASSUMPTIONS,
                                "further standing conventions apply (documented in KEY-TRADEOFFS.md)")
        notes = _condense(_unique(notes), MAX_NOTES, "further minor notes omitted")
        assumptions.append(BASELINE_ASSUMPTION)  # the assumptions block is never empty (product rule)

        headline = synthesis.headline.strip()
        if not headline:
            headline = _first_sentence(deterministic.explanation) if deterministic else FALLBACK_HEADLINE
        analyst_view = None
        agreement_line = None
        if specialist is not None:
            analyst_view = synthesis.analyst_summary.strip() or specialist.narrative
            disagreements = "; ".join(specialist.disagreements) or "none stated"
            # QA task 10: the line reads against the computed score shown at the top of the answer.
            agreement_line = (f"On the computed score: {specialist.agreement or 'no statement given'}. "
                              f"Where the analyst differs from the numbers: {disagreements}.")
        follow_ups = [f for f in synthesis.follow_ups if f.strip()][:4] or list(FALLBACK_FOLLOW_UPS)

        # QA task 9: LLM prose never shows internal metric ids — deterministic backstop over
        # every text surface (the tables already use display names by construction).
        headline = humanize_metric_ids(headline, self.by_id)
        analyst_view = humanize_metric_ids(analyst_view, self.by_id) if analyst_view else None
        agreement_line = humanize_metric_ids(agreement_line, self.by_id) if agreement_line else None
        assumptions = [humanize_metric_ids(a, self.by_id) for a in assumptions]
        notes = [humanize_metric_ids(n, self.by_id) for n in notes]

        return Answer(plan=plan, plan_line=plan_line, headline=headline, evidence_tables=tables,
                      analyst_view=analyst_view, agreement_line=agreement_line,
                      assumptions=_unique(assumptions), uncertainty_notes=_unique(notes),
                      citations=citations_from(metrics, provenance), follow_ups=follow_ups,
                      tool_trace=list(trace))

    # ---------------- assumption / uncertainty sources ----------------

    @staticmethod
    def _report_assumptions(req: AnalysisRequest | None,
                            rep: DeterministicReport | None) -> list[str]:
        preset = (rep.preset if rep else None) or (req.scoring_preset if req else None) or "engine default"
        horizon = (rep.horizon if rep else None) or (req.horizons[0] if req and req.horizons else "-")
        peer_group = (rep.peer_group if rep else None) or (req.peer_group if req else None) or "hub_class"
        # QA task 7: one line for the request-shaping choices instead of three; standing build
        # facts (tier policy etc.) live in the docs, not in every answer.
        out = [f"Scored with preset {preset}, time period {horizon}, "
               f"percentiles among {peer_label(peer_group)}"]
        if rep is not None:
            out += [c for c in rep.caveats if any(m in c.lower() for m in CONVENTION_MARKERS)]
        return out

    @staticmethod
    def _report_notes(rep: DeterministicReport) -> list[str]:
        notes = [c for c in rep.caveats if not any(m in c.lower() for m in CONVENTION_MARKERS)]
        low = sum(1 for row in rep.rows if row.low_confidence)
        if low:
            notes.append(f"{low} of {len(rep.rows)} airports low confidence (thin metric coverage)")
        # QA task 7: quality flags aggregated per code (was one row per metric per flag).
        by_code: dict[str, tuple[int, str]] = {}
        for metric in rep.evidence:
            for flag in metric.quality:
                count, message = by_code.get(flag.code, (0, flag.message))
                by_code[flag.code] = (count + 1, message)
        for code, (count, message) in by_code.items():
            suffix = f" ({count} metrics affected)" if count > 1 else ""
            notes.append(f"{code}: {message}{suffix}")
        return notes

    @staticmethod
    def _tool_assumptions(out: dict[str, Any]) -> list[str]:
        convention = out.get("convention")
        return [str(convention)] if convention else []

    @staticmethod
    def _tool_notes(tool: str, out: dict[str, Any]) -> list[str]:
        notes = []
        if out.get("error"):
            notes.append(f"{tool} failed: {out['error']}")
        if out.get("truncated"):
            notes.append(f"{tool} result was truncated; more data exists")
        coverage = out.get("coverage")
        if isinstance(coverage, int | float):
            notes.append(f"{tool} metric coverage {coverage:.0%}")
        for note in out.get("data_quality_notes") or []:
            notes.append(str(note))
        return notes


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
