from __future__ import annotations

import json

import pytest

from airport_agent.agent.specialists.runner import (
    MAX_TOOL_RESULT_CHARS,
    SPECIALIST_SCHEMA,
    SpecialistRunnerImpl,
    fit_tool_result,
)
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import AnalysisRequest, LLMError, LLMResult, SpecialistRunner, ToolCall
from tests.agent.fake_llm import ScriptedLLM

FINAL = {"ranking": [{"iata": "SFO", "rank": 1, "rationale": "constrained", "confidence": 0.7}], "narrative": "SFO shows unmet demand.",
         "evidence_refs": [{"iata": "SFO", "metric_id": "load_factor"}, {"iata": "SFO", "metric_id": "nope_metric"}],
         "agreement": "agrees with the formula", "disagreements": ["formula underweights weather"], "confidence": 0.7,
         "assumptions": ["12m horizon"], "caveats": ["OTP undercounts"], "lens": "capacity"}


def _runner(script, fake_data, fake_analyst, specs):
    reg = build_registry(fake_data, fake_analyst)
    llm = ScriptedLLM(script)
    return SpecialistRunnerImpl(llm, reg, specs), llm, reg


def test_run_with_tool_loop_and_resolved_evidence(fake_data, fake_analyst, specs):
    tool_turn = LLMResult(text="", provider="fake", model="m",
                          tool_calls=[ToolCall(id="c1", name="get_profile", arguments={"iata": "SFO", "horizons": ["12m"]})])
    runner, llm, _ = _runner([tool_turn, LLMResult(text="done", provider="fake", model="m"), FINAL], fake_data, fake_analyst, specs)
    assert isinstance(runner, SpecialistRunner)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst",
                          hint="x" * 250)
    det = fake_analyst.diagnose(req)
    rep = runner.run(req, det)
    assert rep.specialist == "capacity_analyst" and rep.hint_truncated is True
    assert [m.id for m in rep.evidence] == ["load_factor"] and rep.evidence[0].source_id
    assert any("nope_metric" in c for c in rep.caveats) and any("hint truncated" in c for c in rep.caveats)
    assert rep.ranking[0].iata == "SFO" and rep.agreement and rep.disagreements
    # calls: 2 tool-loop turns + 1 final structured
    assert len(llm.calls) == 3 and llm.calls[2]["response_schema"] == SPECIALIST_SCHEMA
    assert llm.calls[0]["tools"] and {t["function"]["name"] for t in llm.calls[0]["tools"]} >= {"diagnose_unmet_demand"}
    tool_msg = next(m for m in llm.calls[1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["ref"]["iata"] == "SFO"


def test_run_without_tools_uses_report_evidence_by_metric_id(fake_data, fake_analyst, specs):
    runner, llm, _ = _runner([LLMResult(text="ok", provider="fake", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    rep = runner.run(req, fake_analyst.diagnose(req))
    assert rep.evidence and rep.evidence[0].id == "load_factor" and rep.hint_truncated is False
    assert len(llm.calls) == 2


def test_max_turns_bounds_calls(fake_data, fake_analyst, specs):
    tc = LLMResult(text="", provider="f", model="m", tool_calls=[ToolCall(id="1", name="get_live_status", arguments={"iata": "SFO"})])
    # FINAL sits at position 3: the 3rd call IS the final structured one (2 loop turns + final).
    # A runner that took more loop turns would eat FINAL in the loop and hit a tc on the final call
    # (no JSON -> ValueError), so this still fails loudly if max_turns is not honoured.
    runner, llm, _ = _runner([tc, tc, FINAL, tc, tc], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    rep = runner.run(req, None)
    assert len(llm.calls) == 3  # max_turns=2 for capacity_analyst + final
    assert rep.narrative


def test_llm_error_propagates_and_malformed_final_is_value_error(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([LLMError("gemini", 429, "quota")], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="rank", airports=["BOS"], specialist="expansion_analyst")
    with pytest.raises(LLMError):
        runner.run(req, None)
    runner2, _, _ = _runner([LLMResult(text="ok", provider="f", model="m"), {"narrative": 5}], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="malformed"):
        runner2.run(req, None)


def test_missing_specialist_name(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="specialist"):
        runner.run(AnalysisRequest(question_type="rank", airports=["BOS"]), None)


# --- beyond the brief: transport shape, truncation and evidence honesty ----------------------------------

def test_tool_result_message_is_valid_json_within_budget(fake_data, fake_analyst, specs):
    tool_turn = LLMResult(text="", provider="f", model="m",
                          tool_calls=[ToolCall(id="c1", name="get_profile", arguments={"iata": "SFO", "horizons": ["12m"]})])
    runner, llm, _ = _runner([tool_turn, LLMResult(text="ok", provider="f", model="m"), FINAL],
                             fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    runner.run(req, None)
    messages = llm.calls[1]["messages"]
    assistant = next(m for m in messages if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["type"] == "function"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_profile"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"iata": "SFO", "horizons": ["12m"]}
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c1" and tool_msg["name"] == "get_profile"
    body = json.loads(tool_msg["content"])  # a raw slice would not parse
    assert len(tool_msg["content"]) <= MAX_TOOL_RESULT_CHARS
    assert body["truncated"] is True and "shortened" in body["truncation_note"]


def test_fit_tool_result_passes_small_results_through():
    small = {"a": 1, "list": list(range(3))}
    assert json.loads(fit_tool_result(small)) == small


def test_deterministic_view_carries_rows_but_not_evidence(fake_data, fake_analyst, specs):
    runner, llm, _ = _runner([LLMResult(text="ok", provider="f", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="rank", filter=None, airports=["BOS", "BDL"], horizons=["12m"],
                          specialist="expansion_analyst")
    det = fake_analyst.rank(req)
    runner.run(req, det)
    user = llm.calls[0]["messages"][1]["content"]
    view = json.loads(user.split("Deterministic view:")[1])
    assert [r["iata"] for r in view["rows"]] and "evidence" not in view
    assert view["horizon"] == "12m" and "explanation" in view


def test_ambiguous_report_evidence_is_flagged(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([LLMResult(text="ok", provider="f", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="compare", airports=["SFO", "LAX"], horizons=["12m"],
                          specialist="capacity_analyst")
    rep = runner.run(req, fake_analyst.compare(req))
    assert any("resolved by metric id" in c for c in rep.caveats)
    assert any("nope_metric" in c for c in rep.caveats)


def test_confidence_is_clamped_and_lens_recorded(fake_data, fake_analyst, specs):
    final = dict(FINAL, confidence=1.7, ranking=[{"iata": "sfo", "rank": 1, "rationale": "r", "confidence": -2}])
    runner, _, _ = _runner([LLMResult(text="ok", provider="f", model="m"), final], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    rep = runner.run(req, None)
    assert rep.confidence == 1.0 and rep.ranking[0].confidence == 0.0 and rep.ranking[0].iata == "SFO"
    assert any(c == "lens: capacity" for c in rep.caveats)


def test_general_analyst_hint_budget_is_600(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([LLMResult(text="ok", provider="f", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="custom", airports=["DEN"], specialist="general_analyst", hint="y" * 400)
    rep = runner.run(req, None)
    assert rep.hint_truncated is False and not any("hint truncated" in c for c in rep.caveats)


def test_tool_error_is_returned_to_the_model_not_raised(fake_data, fake_analyst, specs):
    bad = LLMResult(text="", provider="f", model="m",
                    tool_calls=[ToolCall(id="c9", name="get_profile", arguments={"iata": "ZZZ"})])
    runner, llm, _ = _runner([bad, LLMResult(text="ok", provider="f", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    rep = runner.run(req, None)
    tool_msg = next(m for m in llm.calls[1]["messages"] if m["role"] == "tool")
    assert "error" in json.loads(tool_msg["content"])
    # the failed call yielded no evidence, so both refs are dropped and reported (never assumed)
    assert rep.evidence == []
    assert sum("dropped unresolved evidence ref" in c for c in rep.caveats) == 2
