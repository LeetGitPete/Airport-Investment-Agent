from __future__ import annotations

import pytest

from airport_agent.agent.concierge import Concierge
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


def test_analytical_without_targets_becomes_clarify(fake_data, fake_analyst, specs):
    js = _plan_json(faa_regions=[], airports=[])
    c, llm = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.plan.intent == "clarify" and len(llm.calls) == 1


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


# --- beyond the brief: shown plan matches what ran, tool order, memory hygiene ---------------------------

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
