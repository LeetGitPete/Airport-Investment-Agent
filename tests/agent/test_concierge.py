from __future__ import annotations

import pytest

from airport_agent.agent.concierge import CLARIFY_TEXT, Concierge
from airport_agent.agent.planner import Planner
from airport_agent.agent.specialists.runner import SpecialistRunnerImpl
from airport_agent.agent.synthesis import Synthesizer
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import LLMError, LLMResult, SessionState
from tests.agent.fake_llm import ScriptedLLM
from tests.agent.test_planner import PRESETS, _plan_json
from tests.agent.test_specialist_runner import FINAL
from tests.agent.test_synthesis import SYN


def _concierge(script, fake_data, fake_analyst, specs):
    llm = ScriptedLLM(script)
    reg = build_registry(fake_data, fake_analyst)
    return Concierge(llm=llm, registry=reg, analyst=fake_analyst, specialists=SpecialistRunnerImpl(llm, reg, specs),
                     planner=Planner(llm, reg, specs, PRESETS), synthesizer=Synthesizer(llm, specs)), llm


def test_analytical_rank_flow_updates_state_and_trace(fake_data, fake_analyst, specs):
    c, llm = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="New chat")
    seen = []
    ans = c.answer("Which airports in New England are strong candidates for terminal expansion?", state, on_plan=seen.append)
    assert seen and seen[0].intent == "analytical"
    assert [t.tool for t in ans.tool_trace] == ["deterministic:rank", "specialist:expansion_analyst"]
    assert ans.tool_trace[1].provider == "fake"
    assert state.title.startswith("Which airports") and len(state.messages) == 2 and state.messages[1].answer is ans
    assert set(state.last_reports) == {"deterministic", "specialist"} and state.last_preset == "terminal_expansion"
    assert set(state.last_airports) == {"BOS", "BDL", "PVD", "MHT", "PWM"}
    assert len(llm.calls) == 4  # plan + specialist(1 turn + final) + synthesis


def test_informational_flow(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[], horizons=[], scoring_preset="none",
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    c, llm = _concierge([js, SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    ans = c.answer("What is the percentage of long haul flights out of Anchorage airport?", state)
    assert [t.tool for t in ans.tool_trace] == ["get_route_stats"] and ans.analyst_view is None
    assert len(llm.calls) == 2 and "deterministic" not in state.last_reports


def test_followup_from_memory_makes_one_llm_call(fake_data, fake_analyst, specs):
    c, llm = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN,
                         _plan_json(intent="followup", engines=[], question_type="none", faa_regions=[]), SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    c.answer("rank NE", state)
    n = len(llm.calls)
    ans = c.answer("why is the top one first?", state)
    assert len(llm.calls) - n == 2 and ans.tool_trace[0].tool == "session_memory"


def test_clarify_makes_no_extra_calls(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[], presentation_notes="Which horizon?")
    c, llm = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.headline == "Which horizon?" and len(llm.calls) == 1 and ans.evidence_tables == []


def test_analytical_without_targets_ranks_the_nation_and_says_so(fake_data, fake_analyst, specs):
    # A themed question with no geography must not become a clarify — it is answerable nationally.
    js = _plan_json(faa_regions=[], airports=[])
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
                      fake_data, fake_analyst, specs)
    ans = c.answer("which airports gain most if Asian tourism grows?",
                   SessionState(session_id="s", title="t"))
    assert ans.plan.intent == "analytical"
    assert "all commercial-service airports" in ans.plan_line
    assert any("commercial-service airport" in a for a in ans.assumptions)
    assert ans.tool_trace[0].tool == "deterministic:rank"


def test_tool_error_is_traced_not_raised(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                    tool_calls=[{"tool": "get_profile", "args_json": '{"iata": "ZZZ"}'}])
    c, _ = _concierge([js, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("profile ZZZ", SessionState(session_id="s", title="t"))
    assert "KeyError" in (ans.tool_trace[0].note or "")


def test_llm_error_propagates_and_state_untouched(fake_data, fake_analyst, specs):
    c, _ = _concierge([LLMError("gemini", 429, "quota")], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    with pytest.raises(LLMError):
        c.answer("x", state)
    assert state.messages == []


def test_custom_with_airports_uses_compare(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="none", engines=["deterministic", "specialist:general_analyst"], airports=["DEN"], faa_regions=[])
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("is DEN cargo growth sustainable?", SessionState(session_id="s", title="t"))
    assert ans.tool_trace[0].tool == "deterministic:compare"


# beyond the brief: shown plan matches what ran, tool order, memory hygiene

def test_plan_line_shows_the_resolved_request(fake_data, fake_analyst, specs):
    js = _plan_json(horizons=[], scoring_preset="none", peer_group="none")
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("rank New England", SessionState(session_id="s", title="t"),
                   defaults={"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"})
    assert "time period 10y" in ans.plan_line and "market entry focus" in ans.plan_line
    assert "peers: all airports" in ans.plan_line and "region ANE" in ans.plan_line


def test_every_tool_call_entry_runs_once_in_order(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'},
                                {"tool": "get_route_stats", "args_json": '{"iata": "SFO"}'},
                                {"tool": "get_live_status", "args_json": '{"iata": "SFO"}'}])
    c, _ = _concierge([js, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("routes", SessionState(session_id="s", title="t"))
    assert [t.tool for t in ans.tool_trace] == ["get_route_stats", "get_route_stats", "get_live_status"]
    assert [t.args["iata"] for t in ans.tool_trace] == ["ANC", "SFO", "SFO"]


def test_planned_calls_falls_back_to_tool_names_without_args(fake_data, fake_analyst, specs):
    from airport_agent.agent.planner import PlanFilters
    from airport_agent.contracts import Plan
    plan = Plan(intent="informational", engines=["tools"], filters={}, tools_to_call=["list_sources"],
                specialist=None, presentation_notes="")
    assert Concierge._planned_calls(plan, PlanFilters()) == [("list_sources", {})]


def test_unparseable_plan_becomes_a_clarify_without_further_calls(fake_data, fake_analyst, specs):
    c, llm = _concierge(["this is not json"], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    ans = c.answer("???", state)
    assert ans.plan.intent == "clarify" and len(llm.calls) == 1
    assert "Which airports or region" in ans.headline
    # The clarify exchange is a real turn: recorded so the next message has its antecedent,
    # but no analysis state is touched.
    assert [m.role for m in state.messages] == ["user", "assistant"]
    assert state.messages[0].content == "???" and state.messages[1].answer is ans
    assert state.last_reports == {} and state.last_airports == []


# A clarify answer never leaks internals.

def test_clarify_headline_is_never_a_raw_validation_dump(fake_data, fake_analyst, specs):
    # the plan asks to rank with a preset the analyst rejects -> ValueError deep in the engine
    js = _plan_json(faa_regions=[], airports=[], scoring_preset="balanced", question_type="compare")
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
                      fake_data, fake_analyst, specs)
    ans = c.answer("compare nothing in particular", SessionState(session_id="s", title="t"))
    for banned in ("pydantic", "validation error", "[type=", "input_value="):
        assert banned not in ans.headline.lower()


def test_instruction_voice_clarify_note_is_replaced_with_a_real_question(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[],
                    presentation_notes="Ask the user to specify which airports, region, or hub size "
                                       "they wish to analyze regarding long-distance hauls.")
    c, _ = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("maybe long distance hauls?", SessionState(session_id="s", title="t"))
    assert not ans.headline.lower().startswith("ask the user")
    assert ans.headline == CLARIFY_TEXT and ans.headline.endswith("?")


def test_a_well_written_clarify_question_is_kept_verbatim(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[],
                    presentation_notes="Which horizon did you mean, 12m or 5y?")
    c, _ = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.headline == "Which horizon did you mean, 12m or 5y?"


def test_the_reason_is_recorded_even_though_it_left_the_headline():
    from pydantic import BaseModel, field_validator

    from airport_agent.agent.concierge import diagnostic

    class M(BaseModel):
        x: int
        @field_validator("x")
        @classmethod
        def _check(cls, v):
            raise ValueError("AnalysisRequest needs airports or a filter")

    try:
        M(x=1)
    except Exception as exc:  # noqa: BLE001 - exactly the shape the Concierge catches
        note = diagnostic(exc)
    assert note == "AnalysisRequest needs airports or a filter"
    assert "pydantic.dev" not in note and "\n" not in note


# An argument the tools do not have never costs the user their answer.

def _invented_arg_plan():
    """The real QA case: 'domestic flights out of ANC' planned with a filter the tool has no key for."""
    return _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                      tool_calls=[{"tool": "get_route_stats",
                                   "args_json": '{"iata": "ANC", "domestic_only": true}'}])


def test_invented_tool_argument_is_repaired_by_one_retry(fake_data, fake_analyst, specs):
    # the repair call re-expresses "domestic only" with the argument the tool actually has
    repair = '{"args_json": "{\\"iata\\": \\"ANC\\", \\"international\\": false}"}'
    c, llm = _concierge([_invented_arg_plan(), repair, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("domestic flights out of ANC?", SessionState(session_id="s", title="t"))
    assert ans.tool_trace[0].args == {"iata": "ANC", "international": False}
    assert ans.tool_trace[0].note is None  # the call succeeded; nothing is reported as a failure
    assert len(llm.calls) == 3  # plan + one bounded repair + synthesis
    assert any("domestic_only" in note for note in ans.uncertainty_notes)  # still told, in plain English


def test_unrepairable_argument_falls_back_to_the_nearest_data_with_a_stated_limitation(
        fake_data, fake_analyst, specs):
    # the repair gives up (returns the same broken args): we prune the key, run anyway, and say so
    repair = '{"args_json": "{\\"iata\\": \\"ANC\\", \\"domestic_only\\": true}"}'
    c, llm = _concierge([_invented_arg_plan(), repair, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("domestic flights out of ANC?", SessionState(session_id="s", title="t"))
    assert ans.tool_trace[0].args == {"iata": "ANC"} and ans.tool_trace[0].note is None
    assert ans.tool_trace[0].rows  # the user still gets the route data
    limitation = next(n for n in ans.uncertainty_notes if "domestic_only" in n)
    assert "cannot filter by 'domestic_only'" in limitation and "unfiltered" in limitation
    assert len(llm.calls) == 3  # bounded: exactly one repair attempt, never a loop


def test_a_type_error_the_model_cannot_fix_is_still_reported(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "SFO", "top_n": 999}'}])
    c, _ = _concierge([js, '{"args_json": "{\\"iata\\": \\"SFO\\", \\"top_n\\": 999}"}', SYN],
                      fake_data, fake_analyst, specs)
    ans = c.answer("top 999 routes from SFO?", SessionState(session_id="s", title="t"))
    # nothing to prune, so the honest outcome is the original validation error, naming what is allowed
    assert "invalid arguments" in (ans.tool_trace[0].note or "")
    assert "allowed arguments for get_route_stats" in ans.tool_trace[0].note


def test_the_planner_prompt_lists_the_arguments_of_every_tool(fake_data, fake_analyst, specs):
    c, _ = _concierge([_plan_json()], fake_data, fake_analyst, specs)
    sysmsg = c.planner.system_prompt(None)
    assert "args: horizon, iata*, international, threshold_mi, top_n" in sysmsg
    assert "invented key is rejected" in sysmsg


def test_informational_turn_keeps_previous_reports(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    c, _ = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN, js, SYN],
                      fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="New chat")
    c.answer("rank NE", state)
    c.answer("long haul out of ANC?", state)
    assert set(state.last_reports) == {"deterministic", "specialist"}  # never cleared by a lookup
    assert state.last_preset == "terminal_expansion" and len(state.messages) == 4


# --- QA task 19: conversational turns ---------------------------------------------------------------------

def _conversational(kind, notes="", suggestions=None):
    return _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[], horizons=[],
                      scoring_preset="none", presentation_notes=notes, conversation_kind=kind,
                      suggested_questions=suggestions or [])


def test_off_topic_answers_with_the_fixed_decline(fake_data, fake_analyst, specs):
    from airport_agent.agent.concierge import OFF_TOPIC_TEXT
    # the model's own prose is discarded: one consistent voice, turn after turn
    c, llm = _concierge([_conversational("off_topic", notes="Sorry, I only do airports I guess?")],
                        fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    ans = c.answer("what's a good recipe for carbonara?", state)
    assert ans.headline == OFF_TOPIC_TEXT
    assert ans.evidence_tables == [] and ans.follow_ups == [] and ans.tool_trace == []
    assert ans.assumptions == [] and ans.uncertainty_notes == [] and ans.citations == []
    assert "outside what I cover" in ans.plan_line
    assert len(llm.calls) == 1  # one call for the whole turn, no dispatch, no synthesis
    assert state.last_reports == {}  # a decline never touches the analysis memory


def test_needs_direction_hands_back_questions_the_agent_can_answer(fake_data, fake_analyst, specs):
    suggestions = ["Which large hubs score highest for terminal expansion?",
                   "Which airports show the most unmet demand?",
                   "Compare congestion at LAX and SNA"]
    c, _ = _concierge([_conversational("needs_direction",
                                       notes="I can rank US airports on expansion potential. "
                                             "Which of these is closest?",
                                       suggestions=suggestions)],
                      fake_data, fake_analyst, specs)
    ans = c.answer("what is the most interesting data point about airports?",
                   SessionState(session_id="s", title="t"))
    assert ans.headline.startswith("I can rank US airports")
    assert ans.follow_ups == suggestions  # the UI renders these as clickable questions
    assert "no data lookup needed" in ans.plan_line
    assert "time period" not in ans.plan_line and "focus" not in ans.plan_line


def test_a_conversational_turn_never_becomes_a_national_ranking(fake_data, fake_analyst, specs):
    """The task 15 guard: 'rank everything' must not swallow a question with no theme and no target."""
    c, _ = _concierge([_conversational("needs_direction", notes="What would you like to look at?",
                                       suggestions=["Rank New England for expansion"])],
                      fake_data, fake_analyst, specs)
    ans = c.answer("what is most interesting?", SessionState(session_id="s", title="t"))
    assert ans.tool_trace == [] and ans.evidence_tables == []
    assert "commercial-service airports" not in ans.plan_line


def test_suggestions_are_ignored_when_the_turn_is_not_conversational(fake_data, fake_analyst, specs):
    # a stray label on a dispatchable question must not divert it
    js = _plan_json(conversation_kind="needs_direction", suggested_questions=["nope"])
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
                      fake_data, fake_analyst, specs)
    ans = c.answer("rank New England for terminal expansion", SessionState(session_id="s", title="t"))
    assert ans.plan.intent == "analytical"
    assert ans.tool_trace[0].tool == "deterministic:rank" and ans.follow_ups != ["nope"]


def test_an_unknown_conversation_kind_degrades_to_an_ordinary_clarify(fake_data, fake_analyst, specs):
    c, _ = _concierge([_conversational("banana", notes="Which airports did you mean?")],
                      fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.headline == "Which airports did you mean?"
    assert "outside what I cover" not in ans.plan_line


# --- QA task 20: live calls happen only where they are needed ---------------------------------------------

class _CountingLive:
    """Wraps the fake data service and counts live reads, honouring the budget the way the real one does."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0
        self.refused = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def get_live_status(self, iata):
        from airport_agent.data.http import claim_live_call
        if not claim_live_call():
            self.refused += 1
        else:
            self.calls += 1
        return self._inner.get_live_status(iata)


def test_scoring_makes_no_live_calls_at_all(fake_data, fake_analyst, specs):
    """The 140-airport stall: ranking used to fetch the national FAA feed once per airport."""
    counting = _CountingLive(fake_data)
    from tests.agent.fake_analyst import FakeAnalyst
    analyst = FakeAnalyst(counting)
    c, _ = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
                      counting, analyst, specs)
    c.answer("rank New England for terminal expansion", SessionState(session_id="s", title="t"))
    assert counting.calls == 0, "scoring fetched live status it never reads"


def test_a_turn_is_capped_and_says_so_when_the_cap_bites(fake_data, fake_analyst, specs):
    from airport_agent.data.http import DEFAULT_LIVE_BUDGET, claim_live_call, live_budget
    calls = []
    with live_budget(DEFAULT_LIVE_BUDGET) as budget:
        for _ in range(9):
            calls.append(claim_live_call())
        note = _live_budget_note_for(budget)
    assert calls.count(True) == DEFAULT_LIVE_BUDGET
    assert note and "fell back to the most recent snapshot" in note[0]
    assert str(DEFAULT_LIVE_BUDGET) in note[0] and "4 more" in note[0]


def test_a_turn_within_the_cap_says_nothing(fake_data, fake_analyst, specs):
    from airport_agent.data.http import claim_live_call, live_budget
    with live_budget(5) as budget:
        claim_live_call()
        assert _live_budget_note_for(budget) == []


def _live_budget_note_for(budget):
    from airport_agent.agent.concierge import _live_budget_note
    return _live_budget_note(budget)
