"""FakeApp — an in-memory stand-in for the real `App` (built by `airport_agent.agent`), used by all UI
tests (`AIRPORT_AGENT_APP_FACTORY="tests.ui.fake_app:make_app"`). Canned `Answer`s only — no scoring, no LLM.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Literal

from airport_agent.contracts import (
    Answer,
    ChatMessage,
    Citation,
    LLMError,
    MetricSpec,
    Plan,
    SessionState,
    SourceVintage,
    Table,
    ToolCallTrace,
    load_registry,
)

VINT = "2026-04"

SAMPLE_QUESTIONS = [
    "Rank the top airports in New England for a 5-year capacity expansion.",
    "Compare LA and Santa Ana airport congestion levels.",
    "Which airports have the largest unmet demand relative to capacity?",
    "What percentage of flights at Logan are long-haul?",
]


def _plan(intent: Literal["informational", "analytical"], notes: str) -> Plan:
    engines = ["tools"] if intent == "informational" else ["tools", "deterministic"]
    return Plan(
        intent=intent,
        engines=engines,
        filters={},
        tools_to_call=["get_feature_matrix"] if intent == "analytical" else ["get_metric_series"],
        specialist=None,
        presentation_notes=notes,
    )


def _table(title: str, columns: list[str], rows: list[list[Any]]) -> Table:
    return Table(title=title, columns=columns, rows=rows, footnotes=[])


def _trace(tool: str) -> ToolCallTrace:
    return ToolCallTrace(tool=tool, args={"horizon": "12m"}, rows=2, provider="fake", latency_ms=12, note=None)


def make_answer(kind: Literal["informational", "rank", "compare", "diagnose"]) -> Answer:
    """Build a canned, contract-valid Answer for a given kind."""
    if kind == "compare":
        plan = _plan("analytical", "Comparing LAX and SNA on avg departure delay (12m).")
        table = _table(
            "Average departure delay (min, 12m)",
            ["iata", "avg_dep_delay_min"],
            [["LAX", 12.9], ["SNA", 13.9]],
        )
        return Answer(
            plan=plan,
            plan_line="Comparing LAX vs SNA on congestion metrics using the deterministic Analyst.",
            headline="LAX (12.9 min avg dep delay) is less congested than SNA (13.9 min) over the trailing 12 months.",
            evidence_tables=[table],
            analyst_view="Deterministic score favors LAX on congestion but SNA leads on demand pressure.",
            agreement_line="Analyst and Concierge agree: LAX is currently less delay-constrained than SNA.",
            assumptions=["12-month trailing window.", "Delay figures are unweighted airport averages."],
            uncertainty_notes=["OTP coverage varies by carrier; regional carriers under-reported."],
            citations=[Citation(source_id="bts_otp", vintage=VINT, url=None)],
            follow_ups=["Compare on taxi-out time instead?", "Extend to a 5-year trend?"],
            tool_trace=[_trace("get_feature_matrix")],
        )
    if kind == "diagnose":
        plan = _plan("analytical", "Diagnosing unmet demand relative to declared capacity.")
        table = _table(
            "Unmet demand proxy (spill_proxy)",
            ["iata", "spill_proxy"],
            [["SNA", 0.09], ["BUR", None]],
        )
        return Answer(
            plan=plan,
            plan_line="Ranking airports by spill/unmet-demand proxy using the deterministic Analyst.",
            headline="SNA shows the largest unmet-demand proxy among the requested peer set.",
            evidence_tables=[table],
            analyst_view="Spill proxy is highest where load factor and delay are both elevated.",
            agreement_line="Analyst and Concierge agree on the ranking direction.",
            assumptions=["Spill proxy is a heuristic, not a measured turn-away rate."],
            uncertainty_notes=["No direct spill/turn-away data source exists; this is a proxy."],
            citations=[Citation(source_id="bts_t100", vintage=VINT, url=None)],
            follow_ups=["Show the underlying load factor trend?"],
            tool_trace=[_trace("get_feature_matrix")],
        )
    if kind == "informational":
        plan = _plan("informational", "Answering a direct factual question via a single tool call.")
        table = _table("Long-haul departure share (BOS)", ["iata", "longhaul_dep_share"], [["BOS", 0.14]])
        return Answer(
            plan=plan,
            plan_line="Looking up the long-haul departure share for Logan.",
            headline="About 14% of departures at Logan (BOS) are long-haul (>=1,500 mi).",
            evidence_tables=[table],
            analyst_view=None,
            agreement_line=None,
            assumptions=["Long-haul convention: stage length >= 1,500 miles."],
            uncertainty_notes=["Based on the most recent 12-month period only."],
            citations=[Citation(source_id="bts_t100", vintage=VINT, url=None)],
            follow_ups=["Show the trend over the last 5 years?"],
            tool_trace=[_trace("get_metric_series")],
        )
    # rank
    plan = _plan("analytical", "Ranking New England airports for 5-year capacity expansion.")
    table = _table(
        "Top New England airports (5y horizon)",
        ["iata", "score"],
        [["BOS", 0.81], ["PVD", 0.62], ["PWM", None]],
    )
    return Answer(
        plan=plan,
        plan_line="Ranking New England airports by composite investment score (5y horizon).",
        headline="BOS ranks first among New England airports for 5-year capacity expansion.",
        evidence_tables=[table],
        analyst_view="Deterministic score driven primarily by demand pressure and congestion pillars.",
        agreement_line="Analyst and Concierge agree on the top-ranked airport.",
        assumptions=["Peer group: hub_class.", "Default scoring preset applied."],
        uncertainty_notes=["PWM has partial metric coverage; score may shift as data fills in."],
        citations=[Citation(source_id="bts_t100", vintage=VINT, url=None)],
        follow_ups=["Break down the score by pillar?"],
        tool_trace=[_trace("get_feature_matrix")],
    )


class FakeSessions:
    """In-memory stand-in for `SessionStore` — same method names."""

    def __init__(self) -> None:
        self._store: dict[str, SessionState] = {}

    def list(self) -> list[SessionState]:
        return list(self._store.values())

    def new(self, title: str = "New chat") -> SessionState:
        state = SessionState(session_id=uuid.uuid4().hex[:12], title=title)
        self._store[state.session_id] = state
        return state

    def load(self, session_id: str) -> SessionState:
        return self._store[session_id]

    def save(self, state: SessionState) -> None:
        self._store[state.session_id] = state

    def delete(self, session_id: str) -> None:
        del self._store[session_id]

    def rename(self, session_id: str, title: str) -> SessionState:
        state = self._store[session_id]
        state.title = title
        self._store[session_id] = state
        return state


class FakeData:
    """In-memory stand-in for the read-only parts of `DataService` exposed to the UI."""

    def source_vintages(self) -> list[SourceVintage]:
        return [
            SourceVintage(source_id="bts_otp", description="fake BTS On-Time Performance",
                          period_start="2016-01", period_end=VINT, fetched_at="2026-08-15T00:00:00", url=None),
            SourceVintage(source_id="bts_t100", description="fake BTS T-100 segment data",
                          period_start="2016-01", period_end=VINT, fetched_at="2026-08-15T00:00:00", url=None),
        ]

    def describe_metrics(self) -> list[MetricSpec]:
        return load_registry()


class FakeApp:
    """Stand-in for the real `App` (design 03/04). Chooses a canned Answer kind by keyword."""

    def __init__(self, sessions_dir: str | None = None) -> None:
        self.sessions_dir = sessions_dir
        self.sessions = FakeSessions()
        self.data = FakeData()
        self.last_defaults: dict[str, str] | None = None

    def _kind_for(self, message: str) -> Literal["informational", "rank", "compare", "diagnose"]:
        m = message.lower()
        if "error" in m:
            raise LLMError("gemini", 429, "quota exceeded")
        if "compare" in m:
            return "compare"
        if "unmet" in m:
            return "diagnose"
        if "long haul" in m or "percentage" in m:
            return "informational"
        return "rank"

    def answer(self, message: str, state: SessionState, *, defaults: dict[str, str] | None = None,
               on_plan: Callable[[Plan], None] | None = None) -> Answer:
        self.last_defaults = defaults
        kind = self._kind_for(message)
        a = make_answer(kind)
        if on_plan is not None:
            on_plan(a.plan)
        state.messages.append(ChatMessage(role="user", content=message))
        state.messages.append(ChatMessage(role="assistant", content=a.headline, answer=a))
        self.sessions.save(state)
        return a

    def provider_status(self) -> list[dict[str, str]]:
        return [{"name": "gemini", "model": "gemini/fake", "status": "configured", "detail": "fake"}]

    def sample_questions(self) -> list[str]:
        return list(SAMPLE_QUESTIONS)


LAST_APP: FakeApp | None = None


def make_app() -> FakeApp:
    global LAST_APP
    LAST_APP = FakeApp()
    return LAST_APP
