"""Concierge: plan -> dispatch -> synthesis, the one path every user message takes (design 03).

The Concierge owns orchestration only. It never computes a number (the Deterministic Analyst does), never
writes evidence (tools do) and never edits a report (the Synthesizer assembles them). What it does own is:
show the plan before executing it, execute exactly what the plan said, degrade to a single clarifying question
when the plan has no target, and keep the session memory that makes follow-ups cheap.

Failure policy: `LLMError` propagates untouched and the session is left unchanged, so the UI can show the
provider error instead of a half-answer. Tool errors are traced and shown, never swallowed.
"""
from __future__ import annotations

import re
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
#: QA task 14 (2026-08-16): the registry's prefix for an argument the tool does not accept.
INVALID_ARGS = "invalid arguments"
#: QA task 16 (2026-08-16): a clarify headline is a question addressed to the user. The planner
#: sometimes writes it in instruction voice ("Ask the user to specify which airports..."), which read
#: as stage directions when shown verbatim. Such a note is dropped for the well-formed default.
_INSTRUCTION_VOICE = re.compile(r"^\s*(?:please\s+)?(?:ask|tell|prompt|request|instruct|clarify\s+with)\b"
                                r".*?\b(?:user|them|they)\b", re.IGNORECASE | re.DOTALL)
#: Pydantic decorates every validation error with a docs URL and a `[type=..., input_value=...]`
#: machine suffix. Neither belongs in anything a person reads.
_PYDANTIC_TAIL = re.compile(r"\s*For further information visit https?://\S+", re.IGNORECASE)
_PYDANTIC_META = re.compile(r"\s*\[type=[^\]]*\]\s*$")
ANALYSIS_FAILED_TEXT = ("I couldn't run that analysis on the data I have. Try naming the airports or "
                        "region directly, or a different time period.")


def clarify_text(note: str | None) -> str:
    """The question actually shown when the agent asks something back (QA task 16)."""
    text = (note or "").strip()
    if not text or _INSTRUCTION_VOICE.match(text):
        return CLARIFY_TEXT
    return text


def diagnostic(exc: Exception, limit: int = 160) -> str:
    """A short human-readable trace of an internal failure — never the raw validation dump.

    Pydantic renders a multi-line report with a docs URL; showing that to a user (as the clarify
    headline once did) is noise. The useful sentence is the validator's own message.
    """
    lines = [_PYDANTIC_META.sub("", ln.strip())
             for ln in _PYDANTIC_TAIL.sub("", str(exc)).splitlines() if ln.strip()]
    chosen = next((ln for ln in lines if ln.lower().startswith("value error")), None)
    if chosen is not None:
        chosen = chosen.split(",", 1)[1].strip() if "," in chosen else chosen
    else:
        chosen = lines[0] if lines else type(exc).__name__
    return chosen[:limit].rstrip(" ,;")


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c' — argument names read to a user, not a Python list."""
    if not items:
        return ""
    if len(items) == 1:
        return f"'{items[0]}'"
    quoted = [f"'{i}'" for i in items]
    return ", ".join(quoted[:-1]) + f" and {quoted[-1]}"


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

    def _clarify_answer(self, state: SessionState, message: str, filters: PlanFilters, text: str,
                        detail: str | None = None) -> Answer:
        """A clarifying question is a real turn: it is recorded so the next message has its antecedent.

        Only the transcript is touched — `last_reports`, `last_airports` and `last_preset` keep the previous
        turn's analysis, because nothing new was computed.

        `detail` is why the turn could not run. It goes to the uncertainty notes, condensed (QA task 16):
        the headline stays a plain question, and the reason is still recorded rather than swallowed.
        """
        text = clarify_text(text)
        plan = self._clarify_plan(filters, text)
        answer = Answer(plan=plan, plan_line=Planner.plan_line(plan, filters), headline=text,
                        evidence_tables=[], analyst_view=None, agreement_line=None, assumptions=[],
                        uncertainty_notes=[f"Why I stopped: {detail}"] if detail else [],
                        citations=[], follow_ups=[], tool_trace=[])
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

    def _run_tools(self, plan: Plan, filters: PlanFilters,
                   message: str = "") -> tuple[list[tuple[str, dict, dict]], list[ToolCallTrace]]:
        results: list[tuple[str, dict, dict]] = []
        trace: list[ToolCallTrace] = []
        for tool, args in self._planned_calls(plan, filters):
            started = time.perf_counter()
            out = self.registry.call(tool, args, engine=CONCIERGE)
            if str(out.get("error", "")).startswith(INVALID_ARGS):
                args, out = self._recover_tool_args(tool, args, out, message)
            trace.append(ToolCallTrace(tool=tool, args=args, rows=_rows(out), provider=None,
                                       latency_ms=_ms(started), note=out.get("error")))
            results.append((tool, args, out))
        return results, trace

    def _recover_tool_args(self, tool: str, args: dict[str, Any], out: dict[str, Any],
                           message: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """A rejected tool call gets one LLM repair, then a deterministic prune (QA task 14).

        The user asked a real question; an argument the tool does not have is our problem, not theirs.
        So we try to re-express the intent, fall back to running the call without the unsupported keys,
        and in every case hand synthesis a plain-English `limitation` to state. Only a call that still
        fails for another reason is reported as an error.
        """
        error = str(out.get("error", ""))
        fixed = self.planner.repair_tool_args(tool, args, error, message)
        if fixed is not None and fixed != args:
            repaired = self.registry.call(tool, fixed, engine=CONCIERGE)
            if not repaired.get("error"):
                _, dropped = self.registry.prune_args(tool, args)
                if dropped:
                    repaired["limitation"] = (
                        f"{tool} has no {_and(dropped)} option, so the request was re-expressed with the "
                        f"arguments it does support ({_and(sorted(fixed)) or 'none'}).")
                return fixed, repaired
        pruned, dropped = self.registry.prune_args(tool, args)
        if not dropped:
            return args, out  # nothing to prune: a type/range error the model could not fix
        fallback = self.registry.call(tool, pruned, engine=CONCIERGE)
        if fallback.get("error"):
            return args, out  # the original error is the more informative one
        fallback["limitation"] = (
            f"{tool} cannot filter by {_and(dropped)} — that is not something this data supports. "
            f"The figures below are unfiltered; ask for a different cut and I will say whether it exists.")
        return pruned, fallback

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
            return self._clarify_answer(state, message, filters, plan.presentation_notes)

        tool_results, trace = self._run_tools(plan, filters, message)
        req: AnalysisRequest | None = None
        deterministic: DeterministicReport | None = None
        specialist: SpecialistReport | None = None

        if "deterministic" in plan.engines or plan.specialist:
            try:
                req = self.planner.to_analysis_request(plan, filters, defaults)
            except ValueError as exc:
                # QA task 16: the raw pydantic dump used to be pasted into the headline.
                return self._clarify_answer(state, message, filters, CLARIFY_TEXT, diagnostic(exc))
            if "deterministic" in plan.engines:
                try:
                    deterministic, entry = self._run_deterministic(req)
                except ValueError as exc:  # unknown preset, empty filter, unusable metric set
                    return self._clarify_answer(state, message, filters, ANALYSIS_FAILED_TEXT,
                                                diagnostic(exc))
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
