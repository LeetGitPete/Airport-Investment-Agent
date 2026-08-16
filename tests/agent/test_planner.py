from __future__ import annotations

import json

import pytest

from airport_agent.agent.planner import PLAN_SCHEMA, SAMPLE_QUESTIONS, PlanFilters, Planner
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import LLMError, Plan, SessionState
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


def test_schema_is_portable():
    dumped = json.dumps(PLAN_SCHEMA)
    for bad in ("anyOf", "$ref", "additionalProperties", "nullable", "oneOf"):
        assert bad not in dumped
    assert set(PLAN_SCHEMA["required"]) == set(PLAN_SCHEMA["properties"])


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


# --- behaviours beyond the brief's list: loud failures and prompt assembly -------------------------------

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


def test_request_without_target_raises(fake_data, fake_analyst, specs):
    js = _plan_json(faa_regions=[])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("rank them", SessionState(session_id="s", title="t"))
    with pytest.raises(ValueError, match="airports or a filter"):
        p.to_analysis_request(plan, f, None)


def test_prompt_carries_recent_turns_and_no_defaults(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t",
                         messages=[{"role": "user", "content": f"turn {i} " + "x" * 500} for i in range(8)])
    p.plan("next", state)
    sysmsg = p.llm.calls[0]["messages"][0]["content"]
    assert "USER DEFAULTS: none set." in sysmsg
    assert "turn 0" not in sysmsg and "turn 2" in sysmsg  # only the last 6 turns
    assert "x" * 500 not in sysmsg  # content truncated to 400 chars


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
