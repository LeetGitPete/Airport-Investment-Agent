"""Golden end-to-end tests for the four assignment questions and six follow-ups (no network).

What these lock down is the product promise, not the prose: the plan is shown, every numeric cell in every
table exists in a report or a tool result, assumptions and citations are always present, informational
answers carry no analyst view, and one question never costs more than six LLM calls.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from tests.agent.fake_analyst import FakeAnalyst
from tests.agent.fake_llm import ScriptedLLM
from tests.fakes import FakeDataService
from tests.golden import scripts

from airport_agent.agent import SAMPLE_QUESTIONS, build_app
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import Answer, load_registry

MAX_CALLS_PER_QUESTION = 6
QUESTIONS = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
]


@pytest.fixture
def session(tmp_path):
    """One app per test, wired to the deterministic fakes and a scripted LLM."""

    def build(index: int):
        data = FakeDataService()
        analyst = FakeAnalyst(data)
        llm = ScriptedLLM(scripts.for_question(index))
        app = build_app(data_service=data, analyst=analyst, llm=llm, sessions_dir=tmp_path / f"s{index}")
        return app, llm, build_registry(data, analyst)

    return build


def _numbers(value: Any, out: set[float]) -> set[float]:
    """Every number anywhere in a report dump or tool result (bools are not numbers here)."""
    if isinstance(value, bool):
        return out
    if isinstance(value, int | float):
        out.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, out)
    elif isinstance(value, list):
        for item in value:
            _numbers(item, out)
    return out


def _allowed_numbers(state, answer, registry) -> set[float]:
    """Numbers the answer is allowed to show: from the stored reports and from re-running its tool calls.

    The fakes are pure, so re-running the planned tool calls reproduces exactly what the Concierge saw.
    """
    allowed: set[float] = set()
    for report in state.last_reports.values():
        _numbers(report.model_dump(mode="json"), allowed)
    for call in answer.plan.filters.get("tool_calls") or []:
        args = json.loads(call["args_json"]) if call.get("args_json") else {}
        _numbers(registry.call(call["tool"], args, engine="concierge"), allowed)
    return allowed


def _numeric_cells(answer: Answer) -> list[float]:
    cells = []
    for table in answer.evidence_tables:
        for row in table.rows:
            for cell in row:
                if isinstance(cell, int | float) and not isinstance(cell, bool):
                    cells.append(float(cell))
    return cells


def _check_answer(answer: Answer, state, registry) -> None:
    assert isinstance(answer, Answer)
    assert answer.plan_line.startswith("How I'm approaching this")
    assert answer.headline.strip()
    assert answer.evidence_tables
    # Row 65: an analytical answer always states its scoring settings; an informational lookup with
    # nothing defaulted legitimately assumes nothing, and no filler line is written to fake one.
    if answer.plan.intent == "analytical":
        assert answer.assumptions
    assert answer.citations and all(c.source_id and c.vintage for c in answer.citations)
    allowed = _allowed_numbers(state, answer, registry)
    unexplained = [c for c in _numeric_cells(answer) if c not in allowed]
    assert unexplained == [], f"table cells not traceable to a report or tool result: {unexplained}"


@pytest.mark.parametrize("index", range(4))
def test_sample_question_answers_are_well_formed(index, session):
    app, llm, registry = session(index)
    state = app.sessions.new()
    answer = app.answer(QUESTIONS[index], state, on_plan=lambda plan: None)
    _check_answer(answer, state, registry)
    assert len(llm.calls) <= MAX_CALLS_PER_QUESTION
    assert len(state.messages) == 2 and state.messages[1].answer is answer


def test_q1_ranks_new_england_with_both_engines(session):
    app, _llm, registry = session(0)
    state = app.sessions.new()
    answer = app.answer(QUESTIONS[0], state, on_plan=None)
    assert [t.tool for t in answer.tool_trace] == ["deterministic:rank", "specialist:expansion_analyst"]
    ranking = next(t for t in answer.evidence_tables if t.title.startswith("Ranking"))
    assert {row[ranking.columns.index("airport")] for row in ranking.rows} == {"BOS", "BDL", "PVD", "MHT",
                                                                              "PWM"}
    assert "terminal expansion focus" in ranking.title  # prose, never the internal preset id
    assert answer.analyst_view and answer.agreement_line and "gate scarcity" in answer.agreement_line
    _check_answer(answer, state, registry)


def test_q2_compares_lax_and_sna_with_the_reported_delays(session):
    app, _llm, registry = session(1)
    state = app.sessions.new()
    answer = app.answer(QUESTIONS[1], state, on_plan=None)
    comparison = next(t for t in answer.evidence_tables if t.title.startswith("Comparison"))
    assert "LAX" in comparison.columns and "SNA" in comparison.columns
    # rows carry user-facing metric names, never internal ids
    row = next(r for r in comparison.rows if r[comparison.columns.index("metric")] == "Mean departure delay")
    assert row[comparison.columns.index("LAX")] == pytest.approx(12.9)
    assert row[comparison.columns.index("SNA")] == pytest.approx(13.9)
    _check_answer(answer, state, registry)


def test_q3_is_informational_with_no_analyst_view(session):
    app, llm, registry = session(2)
    state = app.sessions.new()
    answer = app.answer(QUESTIONS[2], state, on_plan=None)
    assert answer.analyst_view is None and answer.agreement_line is None
    assert [t.tool for t in answer.tool_trace] == ["get_route_stats"]
    assert any(t.title.startswith("Long-haul share") for t in answer.evidence_tables)
    assert any("1500" in a or "1,500" in a for a in answer.assumptions)
    assert len(llm.calls) == 2
    _check_answer(answer, state, registry)


def test_q4_diagnose_runs_both_engines_without_the_footnote_explanation(session):
    app, _llm, registry = session(3)
    state = app.sessions.new()
    answer = app.answer(QUESTIONS[3], state, on_plan=None)
    # The templated explanation is not appended below the tables; it still
    # feeds the synthesis prompt and the fallback headline, so the answer must not lose it silently.
    rendered = [note for table in answer.evidence_tables for note in table.footnotes]
    assert not any("Signals of unmet demand" in text for text in rendered)
    assert answer.headline  # a headline is always present, explanation-backed if synthesis is empty
    assert [t.tool for t in answer.tool_trace] == ["deterministic:diagnose", "specialist:capacity_analyst"]
    _check_answer(answer, state, registry)


@pytest.mark.parametrize("index", range(4))
def test_follow_ups_reuse_the_session(index, session):
    app, llm, registry = session(index)
    state = app.sessions.new()
    app.answer(QUESTIONS[index], state, on_plan=None)
    for message, _chunk, expected_calls, from_memory in scripts.follow_ups(index):
        before = len(llm.calls)
        answer = app.answer(message, state, on_plan=None)
        assert len(llm.calls) - before == expected_calls, message
        if from_memory:
            assert answer.tool_trace[0].tool == "session_memory"
            assert answer.analyst_view, "a memory follow-up should still show the stored analyst view"
        _check_answer(answer, state, registry)
    assert len(state.messages) == 2 * (1 + len(scripts.follow_ups(index)))


def test_every_sample_question_is_the_assignment_wording():
    assert list(SAMPLE_QUESTIONS) == QUESTIONS  # the agent offers exactly the assignment wording
    assert {s.id for s in load_registry()} >= {"load_factor", "avg_dep_delay_min"}
