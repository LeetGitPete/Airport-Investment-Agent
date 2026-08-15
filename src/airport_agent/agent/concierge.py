"""Concierge: plan -> dispatch -> synthesis, the one path every user message takes (design 03).

The Concierge owns orchestration only. It never computes a number (the Deterministic Analyst does), never
writes evidence (tools do) and never edits a report (the Synthesizer assembles them). What it does own is:
show the plan before executing it, execute exactly what the plan said, degrade to a single clarifying question
when the plan has no target, and keep the session memory that makes follow-ups cheap.

Failure policy: `LLMError` propagates untouched and the session is left unchanged, so the UI can show the
provider error instead of a half-answer. Tool errors are traced and shown, never swallowed.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from airport_agent.agent.planner import PlanFilters, Planner
from airport_agent.agent.synthesis import Synthesizer
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import (
    AnalysisRequest,
    Answer,
    ChatMessage,
    DeterministicAnalyst,
    DeterministicReport,
    LLMClient,
    Plan,
    SessionState,
    SpecialistReport,
    SpecialistRunner,
    ToolCallTrace,
)

CONCIERGE = "concierge"
NEW_CHAT_TITLE = "New chat"
TITLE_CHARS = 60
CLARIFY_TEXT = ("I couldn't determine what to analyse. Which airports or region, and which horizon "
                "(12m/3y/5y/10y)?")
ROW_KEYS = ("rows", "airports", "top_routes", "series", "sources")


def _rows(out: dict[str, Any]) -> int | None:
    """How many rows a tool returned, for the trace (first list-shaped payload it carries)."""
    for key in ROW_KEYS:
        value = out.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class Concierge:
    """Turns a user message into an `Answer`, mutating the session state on success."""

    def __init__(self, *, llm: LLMClient, registry: ToolRegistry, analyst: DeterministicAnalyst,
                 specialists: SpecialistRunner, planner: Planner, synthesizer: Synthesizer) -> None:
        self.llm = llm
        self.registry = registry
        self.analyst = analyst
        self.specialists = specialists
        self.planner = planner
        self.synthesizer = synthesizer
        self.provider_name: str = getattr(llm, "provider_name", None) or "llm"

    # ---------------- plan ----------------

    def _plan(self, message: str, state: SessionState,
              defaults: dict[str, str] | None) -> tuple[Plan, PlanFilters]:
        """Plan the turn. Unusable model output becomes a clarifying question, not a guess."""
        try:
            return self.planner.plan(message, state, defaults)
        except ValueError:
            filters = PlanFilters()
            return self._clarify_plan(filters, CLARIFY_TEXT), filters

    @staticmethod
    def _clarify_plan(filters: PlanFilters, text: str) -> Plan:
        return Plan(intent="clarify", engines=[], filters=filters.model_dump(), tools_to_call=[],
                    specialist=None, presentation_notes=text)

    def _clarify_answer(self, state: SessionState, message: str, filters: PlanFilters, text: str) -> Answer:
        """A clarifying question is a real turn: it is recorded so the next message has its antecedent.

        Only the transcript is touched — `last_reports`, `last_airports` and `last_preset` keep the previous
        turn's analysis, because nothing new was computed.
        """
        plan = self._clarify_plan(filters, text)
        answer = Answer(plan=plan, plan_line=Planner.plan_line(plan, filters), headline=text,
                        evidence_tables=[], analyst_view=None, agreement_line=None, assumptions=[],
                        uncertainty_notes=[], citations=[], follow_ups=[], tool_trace=[])
        state.messages.append(ChatMessage(role="user", content=message))
        state.messages.append(ChatMessage(role="assistant", content=text, answer=answer))
        return answer

    # ---------------- execution ----------------

    @staticmethod
    def _planned_calls(plan: Plan, filters: PlanFilters) -> list[tuple[str, dict[str, Any]]]:
        """Exactly what the plan asked for: each tool_calls entry once, in order."""
        if filters.tool_calls:
            return [(call.tool, call.args()) for call in filters.tool_calls]
        return [(tool, {}) for tool in plan.tools_to_call]

    def _run_tools(self, plan: Plan, filters: PlanFilters) -> tuple[list[tuple[str, dict, dict]],
                                                                    list[ToolCallTrace]]:
        results: list[tuple[str, dict, dict]] = []
        trace: list[ToolCallTrace] = []
        for tool, args in self._planned_calls(plan, filters):
            started = time.perf_counter()
            out = self.registry.call(tool, args, engine=CONCIERGE)
            trace.append(ToolCallTrace(tool=tool, args=args, rows=_rows(out), provider=None,
                                       latency_ms=_ms(started), note=out.get("error")))
            results.append((tool, args, out))
        return results, trace

    def _run_deterministic(self, req: AnalysisRequest) -> tuple[DeterministicReport, ToolCallTrace]:
        name = req.question_type
        if name == "custom":  # the analyst has no 'custom' method: pick the shape the request implies
            name = "compare" if req.airports else "rank"
        method = {"rank": self.analyst.rank, "compare": self.analyst.compare,
                  "diagnose": self.analyst.diagnose}[name]
        started = time.perf_counter()
        report = method(req)
        trace = ToolCallTrace(tool=f"deterministic:{name}", args=req.model_dump(exclude_none=True),
                              rows=len(report.rows), provider=None, latency_ms=_ms(started), note=None)
        return report, trace

    def _run_specialist(self, req: AnalysisRequest,
                        deterministic: DeterministicReport | None) -> tuple[SpecialistReport, ToolCallTrace]:
        started = time.perf_counter()
        report = self.specialists.run(req, deterministic)
        trace = ToolCallTrace(tool=f"specialist:{report.specialist}", args={"hint": req.hint},
                              rows=len(report.evidence), provider=self.provider_name,
                              latency_ms=_ms(started),
                              note="hint truncated" if report.hint_truncated else None)
        return report, trace

    @staticmethod
    def _from_memory(state: SessionState) -> tuple[DeterministicReport | None, SpecialistReport | None,
                                                   ToolCallTrace]:
        stored_det = state.last_reports.get("deterministic")
        stored_spec = state.last_reports.get("specialist")
        trace = ToolCallTrace(tool="session_memory", args={}, rows=None, provider=None, latency_ms=0,
                              note="answered from last reports")
        return (stored_det if isinstance(stored_det, DeterministicReport) else None,
                stored_spec if isinstance(stored_spec, SpecialistReport) else None, trace)

    # ---------------- the turn ----------------

    def answer(self, message: str, state: SessionState, *, defaults: dict[str, str] | None = None,
               on_plan: Callable[[Plan], None] | None = None) -> Answer:
        plan, filters = self._plan(message, state, defaults)
        if on_plan is not None:
            on_plan(plan)
        if plan.intent == "clarify":
            return self._clarify_answer(state, message, filters, plan.presentation_notes or CLARIFY_TEXT)

        tool_results, trace = self._run_tools(plan, filters)
        req: AnalysisRequest | None = None
        deterministic: DeterministicReport | None = None
        specialist: SpecialistReport | None = None

        if "deterministic" in plan.engines or plan.specialist:
            try:
                req = self.planner.to_analysis_request(plan, filters, defaults)
            except ValueError as exc:
                return self._clarify_answer(state, message, filters, f"{CLARIFY_TEXT} ({exc})")
            if "deterministic" in plan.engines:
                try:
                    deterministic, entry = self._run_deterministic(req)
                except ValueError as exc:  # unknown preset, empty filter, unusable metric set
                    return self._clarify_answer(state, message, filters,
                                                f"I could not run that analysis: {exc}")
                trace.append(entry)
            if plan.specialist:
                specialist, entry = self._run_specialist(req, deterministic)
                trace.append(entry)
        elif plan.intent == "followup" and not plan.engines and not tool_results:
            deterministic, specialist, entry = self._from_memory(state)
            trace.append(entry)

        answer = self.synthesizer.synthesize(
            message=message, plan=plan, plan_line=Planner.plan_line(plan, filters, req), req=req,
            deterministic=deterministic, specialist=specialist, tool_results=tool_results, trace=trace,
            defaults=defaults)
        self._remember(state, message, answer, plan, req, deterministic, specialist)
        return answer

    # ---------------- memory ----------------

    @staticmethod
    def _remember(state: SessionState, message: str, answer: Answer, plan: Plan,
                  req: AnalysisRequest | None, deterministic: DeterministicReport | None,
                  specialist: SpecialistReport | None) -> None:
        if state.title == NEW_CHAT_TITLE:
            state.title = message.strip()[:TITLE_CHARS] or NEW_CHAT_TITLE
        state.messages.append(ChatMessage(role="user", content=message))
        state.messages.append(ChatMessage(role="assistant", content=answer.headline, answer=answer))
        airports = list(req.airports) if req and req.airports else None
        if not airports and deterministic is not None:
            airports = [row.ref.iata for row in deterministic.rows]
        if airports:
            state.last_airports = airports
        state.last_filters = plan.filters
        if deterministic is not None:
            state.last_reports["deterministic"] = deterministic
            state.last_preset = deterministic.preset or state.last_preset
        if specialist is not None:
            state.last_reports["specialist"] = specialist
