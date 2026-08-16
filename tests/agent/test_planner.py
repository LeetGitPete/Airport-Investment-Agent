from __future__ import annotations

import json

import pytest

from airport_agent.agent.planner import PLAN_SCHEMA, SAMPLE_QUESTIONS, PlanFilters, Planner
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import AnalysisRequest, LLMError, Plan, SessionState
from tests.agent.fake_llm import ScriptedLLM

PRESETS = ["balanced", "terminal_expansion", "congestion_relief", "market_entry"]


def _plan_json(**over):
    base = {"intent": "analytical", "engines": ["deterministic", "specialist:expansion_analyst"], "question_type": "rank",
            "airports": [], "states": [], "faa_regions": ["ANE"], "hub_sizes": [], "horizons": ["5y"],
            "scoring_preset": "terminal_expansion", "focus_metrics": [], "peer_group": "none", "hint": "terminal focus",
            "tool_calls": [], "presentation_notes": "rank table first"}
    base.update(over)
    return base


def _planner(script, fake_data, fake_analyst, specs):
    reg = build_registry(fake_data, fake_analyst)
    return Planner(ScriptedLLM(script), reg, specs, PRESETS)


def test_sample_questions_verbatim():
    assert SAMPLE_QUESTIONS[0].startswith("Which airports in New England") and len(SAMPLE_QUESTIONS) == 4


def test_plan_analytical_rank(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[0], SessionState(session_id="s", title="t"))
    assert isinstance(plan, Plan) and plan.intent == "analytical" and plan.specialist == "expansion_analyst"
    assert f.faa_regions == ["ANE"] and plan.filters["faa_regions"] == ["ANE"]
    req = p.to_analysis_request(plan, f, None)
    assert req.question_type == "rank" and req.filter.faa_regions == ["ANE"] and req.horizons == ["5y"]
    assert req.scoring_preset == "terminal_expansion" and req.specialist == "expansion_analyst" and req.airports is None
    line = Planner.plan_line(plan, f)
    assert line.startswith("How I'm approaching this: analytical · rank · region ANE · time period 5y")
    # the LLM call carried the schema and the system prompt mentions tools, presets, metric ids, samples
    call = p.llm.calls[0]
    assert call["response_schema"] == PLAN_SCHEMA
    sysmsg = call["messages"][0]["content"]
    for token in ("find_airports", "terminal_expansion", "load_factor", "capacity_analyst", "1,500", "Anchorage"):
        assert token in sysmsg


def test_plan_informational_with_tool_calls(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[], horizons=[],
                    scoring_preset="none", tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[2], SessionState(session_id="s", title="t"))
    assert plan.tools_to_call == ["get_route_stats"] and f.args_for("get_route_stats") == {"iata": "ANC"}
    assert plan.specialist is None and f.question_type is None
    assert "lookup" in Planner.plan_line(plan, f)


def test_defaults_and_session_context_reach_prompt_and_request(fake_data, fake_analyst, specs):
    js = _plan_json(horizons=[], scoring_preset="none", peer_group="none")
    p = _planner([js], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t", last_airports=["BOS"], last_preset="balanced")
    plan, f = p.plan("and at 10 years?", state, defaults={"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"})
    req = p.to_analysis_request(plan, f, {"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"})
    assert req.horizons == ["10y"] and req.scoring_preset == "market_entry" and req.peer_group == "all"
    sysmsg = p.llm.calls[0]["messages"][0]["content"]
    assert "10y" in sysmsg and "BOS" in sysmsg


def test_custom_question_type_only_with_general_analyst(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="none", engines=["deterministic", "specialist:general_analyst"], airports=["DEN"],
                    faa_regions=[])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("is DEN cargo growth sustainable?", SessionState(session_id="s", title="t"))
    req = p.to_analysis_request(plan, f, None)
    assert req.question_type == "custom" and req.specialist == "general_analyst" and req.airports == ["DEN"]


def test_diagnose_default_horizon_is_12m(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="diagnose", engines=["deterministic", "specialist:capacity_analyst"], airports=["SFO"],
                    faa_regions=[], horizons=[], scoring_preset="none")
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[3], SessionState(session_id="s", title="t"))
    assert p.to_analysis_request(plan, f, None).horizons == ["12m"]


def test_bad_llm_json_raises_value_error(fake_data, fake_analyst, specs):
    p = _planner(["not json at all"], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError):
        p.plan("x", SessionState(session_id="s", title="t"))


def test_plan_filters_args_for_bad_json_is_empty():
    f = PlanFilters(tool_calls=[{"tool": "x", "args_json": "{oops"}])
    assert f.args_for("x") == {} and f.args_for("y") == {}


# behaviours beyond the brief's list: loud failures and prompt assembly

def test_clarify_intent_drops_engines(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", question_type="none", faa_regions=[], horizons=[], scoring_preset="none")
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("which airports?", SessionState(session_id="s", title="t"))
    assert plan.engines == [] and plan.specialist is None
    assert Planner.plan_line(plan, f).endswith("engines: none")


def test_clarify_intent_drops_tool_calls_too(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=["tools"], question_type="none", faa_regions=[], horizons=[],
                    scoring_preset="none",
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("which airport did you mean?", SessionState(session_id="s", title="t"))
    assert plan.engines == [] and plan.tools_to_call == [] and f.tool_calls == []
    assert plan.filters["tool_calls"] == []


def test_unknown_engine_is_loud(fake_data, fake_analyst, specs):
    p = _planner([_plan_json(engines=["deterministic", "specialist:price_analyst"])], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="unknown engines"):
        p.plan("x", SessionState(session_id="s", title="t"))


def test_two_specialists_is_loud(fake_data, fake_analyst, specs):
    js = _plan_json(engines=["specialist:expansion_analyst", "specialist:market_analyst"])
    p = _planner([js], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="more than one specialist"):
        p.plan("x", SessionState(session_id="s", title="t"))


def test_unknown_preset_or_specialist_is_rejected_at_construction(fake_data, fake_analyst, specs):
    reg = build_registry(fake_data, fake_analyst)
    with pytest.raises(ValueError, match="PRESET_NAMES"):
        Planner(ScriptedLLM([]), reg, specs, ["balanced", "made_up_preset"])
    with pytest.raises(ValueError, match="SPECIALIST_GUIDE"):
        Planner(ScriptedLLM([]), reg, specs, PRESETS, specialists=["price_analyst"])


def test_congestion_compare_defaults_to_12m(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="compare", engines=["deterministic", "specialist:capacity_analyst"],
                    airports=["lax", "sna"], faa_regions=[], horizons=[], scoring_preset="congestion_relief")
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[1], SessionState(session_id="s", title="t"))
    req = p.to_analysis_request(plan, f, None)
    assert req.horizons == ["12m"] and req.airports == ["LAX", "SNA"] and req.filter is None
    assert "LAX, SNA" in Planner.plan_line(plan, f)


def test_request_without_target_falls_back_to_the_national_scope(fake_data, fake_analyst, specs):
    # A themed question with no geography is answerable —
    # rank every commercial-service airport rather than asking the user where to look.
    from airport_agent.agent.planner import NATIONAL_SCOPE_HUBS, NATIONAL_SCOPE_LIMIT, is_national_scope
    js = _plan_json(faa_regions=[])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("which airports gain most if Asian tourism grows?",
                     SessionState(session_id="s", title="t"))
    req = p.to_analysis_request(plan, f, None)
    assert req.airports is None and req.filter is not None
    assert req.filter.hub_sizes == NATIONAL_SCOPE_HUBS  # nonhub GA fields are never padded in
    assert req.filter.limit == NATIONAL_SCOPE_LIMIT >= 140  # the whole set, never silently truncated
    assert is_national_scope(req)
    assert "all commercial-service airports" in Planner.plan_line(plan, f, req)


def test_a_scope_the_user_asked_for_is_not_mistaken_for_the_national_default(fake_data, fake_analyst, specs):
    from airport_agent.agent.planner import is_national_scope
    js = _plan_json(faa_regions=[], hub_sizes=["large", "medium", "small"])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("rank the commercial hubs", SessionState(session_id="s", title="t"))
    req = p.to_analysis_request(plan, f, None)
    assert req.filter.hub_sizes == ["large", "medium", "small"] and not is_national_scope(req)


def test_prompt_carries_recent_turns_and_no_defaults(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    messages = []
    for i in range(1, 9):
        messages.append({"role": "user", "content": f"question {i} " + "x" * 500})
        messages.append({"role": "assistant", "content": f"reply {i}"})
    state = SessionState(session_id="s", title="t", messages=messages)
    p.plan("next", state)
    sysmsg = p.llm.calls[0]["messages"][0]["content"]
    assert "USER DEFAULTS: none set." in sysmsg
    # contracts-v3: the last 5 turns verbatim (as digests), older ones only via the summary.
    assert "[turn 3]" not in sysmsg and "[turn 4]" in sysmsg and "[turn 8]" in sysmsg
    assert "x" * 500 not in sysmsg  # a digest clips each field


def test_prompt_carries_summary_and_archive_index_but_not_folded_turns(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    messages = []
    for i in range(1, 8):
        messages.append({"role": "user", "content": f"question {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}"})
    state = SessionState(session_id="s", title="t", messages=messages, summary="BOS led turn 1.",
                         summary_through_turn=2,
                         report_archive={1: [fake_analyst.rank(AnalysisRequest(
                             question_type="rank", airports=["BOS", "BDL"], horizons=["5y"],
                             scoring_preset="balanced"))]})
    p.plan("and BOS?", state)
    sysmsg = p.llm.calls[0]["messages"][0]["content"]
    assert "SUMMARY OF EARLIER TURNS (through turn 2)" in sysmsg and "BOS led turn 1." in sysmsg
    assert "[turn 2]" not in sysmsg and "[turn 3]" in sysmsg  # folded turns are not repeated verbatim
    assert "ANALYSES IN MEMORY" in sysmsg and "turn 1: rank · preset balanced" in sysmsg


def test_plan_filters_round_trip_through_plan_dict(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[0], SessionState(session_id="s", title="t"))
    assert PlanFilters(**plan.filters) == f


def test_metric_block_marks_tiers(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    sysmsg = p.system_prompt(None)
    assert "load_factor (Load factor)" in sysmsg  # tier A, unmarked
    assert "peak_hour_ops_ratio (Peak demand/capacity)*" in sysmsg  # tier B, marked
    assert "tier C — documented gaps, not computable from our data" in sysmsg and "dscr" in sysmsg


def test_plan_call_is_low_temperature_and_two_messages(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    p.plan(SAMPLE_QUESTIONS[0], SessionState(session_id="s", title="t"))
    call = p.llm.calls[0]
    assert call["temperature"] == 0.1 and call["tools"] is None
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][1]["content"] == SAMPLE_QUESTIONS[0]


def test_llm_error_propagates_from_plan(fake_data, fake_analyst, specs):
    p = _planner([LLMError("gemini", 429, "quota exceeded")], fake_data, fake_analyst, specs)
    with pytest.raises(LLMError, match="quota exceeded"):
        p.plan("x", SessionState(session_id="s", title="t"))


def test_presentation_notes_pass_through(fake_data, fake_analyst, specs):
    p = _planner([_plan_json(presentation_notes="lead with the top 5 rows, collapse the rest")],
                 fake_data, fake_analyst, specs)
    plan, _ = p.plan(SAMPLE_QUESTIONS[0], SessionState(session_id="s", title="t"))
    assert plan.presentation_notes == "lead with the top 5 rows, collapse the rest"


# --- QA task 19: conversational classification ------------------------------------------------------------

def test_conversation_kind_and_suggestions_are_parsed_on_a_clarify(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[], horizons=[],
                    scoring_preset="none", conversation_kind="needs_direction",
                    suggested_questions=["a?", "b?", "c?", "d?"])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("what is interesting?", SessionState(session_id="s", title="t"))
    assert f.conversation_kind == "needs_direction" and f.is_conversational
    assert f.suggested_questions == ["a?", "b?", "c?"]  # capped at 3
    assert PlanFilters(**plan.filters) == f  # rides in the free-form filters dict, not the contract
    assert plan.intent == "clarify"  # the frozen Intent literal is untouched


def test_conversation_kind_is_ignored_when_the_intent_dispatches(fake_data, fake_analyst, specs):
    js = _plan_json(conversation_kind="off_topic", suggested_questions=["x?"])
    p = _planner([js], fake_data, fake_analyst, specs)
    _plan, f = p.plan("rank New England", SessionState(session_id="s", title="t"))
    assert f.conversation_kind == "none" and not f.is_conversational and f.suggested_questions == []


def test_an_unknown_kind_degrades_rather_than_raising(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[],
                    conversation_kind="banana")
    p = _planner([js], fake_data, fake_analyst, specs)
    _plan, f = p.plan("???", SessionState(session_id="s", title="t"))
    assert f.conversation_kind == "none" and not f.is_conversational


def test_the_prompt_orders_conversational_before_the_national_default(fake_data, fake_analyst, specs):
    """Getting this order wrong is how this feature would regress task 15."""
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    sysmsg = p.system_prompt(None)
    assert "ORDER MATTERS" in sysmsg
    assert sysmsg.index("off_topic") < sysmsg.index("commercial-service airport")
    assert "needs_direction" in sysmsg


def test_the_plan_schema_stays_portable_with_the_new_fields():
    dumped = json.dumps(PLAN_SCHEMA)
    for bad in ("anyOf", "$ref", "additionalProperties", "nullable", "oneOf"):
        assert bad not in dumped
    assert set(PLAN_SCHEMA["required"]) == set(PLAN_SCHEMA["properties"])
    assert "conversation_kind" in PLAN_SCHEMA["properties"]
    assert PLAN_SCHEMA["properties"]["conversation_kind"]["enum"] == ["none", "off_topic", "needs_direction"]
