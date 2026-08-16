from __future__ import annotations

import pytest

from airport_agent.agent.planner import PlanFilters
from airport_agent.agent.synthesis import NO_DEFAULTS_ASSUMPTION, SYNTHESIS_SCHEMA, Synthesizer
from airport_agent.contracts import AnalysisRequest, Answer, LLMResult, Plan, RankedItem, SpecialistReport
from tests.agent.fake_llm import ScriptedLLM

SYN = {"headline": "SFO and JFK lead on congestion.", "show_metrics": ["load_factor"], "hidden_reason": "delay metrics collapsed",
       "analyst_summary": "", "follow_ups": ["Compare at 5y?", "Show taxi-out?", "Add DEN?"]}


def _plan():
    return Plan(intent="analytical", engines=["deterministic", "specialist:expansion_analyst"], filters=PlanFilters().model_dump(),
                tools_to_call=[], specialist="expansion_analyst", presentation_notes="")


def test_synthesize_analytical_structure_and_no_altered_numbers(fake_analyst, specs):
    req = AnalysisRequest(question_type="rank", airports=["SFO", "JFK", "BOS"], horizons=["12m"], specialist="expansion_analyst")
    det = fake_analyst.rank(req)
    spec = SpecialistReport(specialist="expansion_analyst", question_type="rank", ranking=[RankedItem(iata="SFO", rank=1, rationale="r", confidence=0.6)],
                            narrative="Narrative.", evidence=det.evidence[:1], agreement="agrees", disagreements=["weather"],
                            confidence=0.6, assumptions=["a1"], caveats=["c1"], hint_truncated=False)
    llm = ScriptedLLM([SYN])
    ans = Synthesizer(llm, specs).synthesize(message="q", plan=_plan(), plan_line="How I'm approaching this: …", req=req,
                                             deterministic=det, specialist=spec, tool_results=[], trace=[], defaults=None)
    assert isinstance(ans, Answer) and ans.headline == SYN["headline"] and ans.plan_line.startswith("How I'm")
    titles = [t.title for t in ans.evidence_tables]
    assert any(t.startswith("Ranking") for t in titles)
    # multi-airport report: evidence carries no airport, so no Evidence table is rendered
    assert not any(t.startswith("Evidence") for t in titles)
    rank_tbl = next(t for t in ans.evidence_tables if t.title.startswith("Ranking"))
    scores = {row[rank_tbl.columns.index("airport")]: row[rank_tbl.columns.index("score")] for row in rank_tbl.rows}
    assert scores == {r.ref.iata: r.score for r in det.rows}  # numbers verbatim from the report
    assert ans.analyst_view == "Narrative." and "agrees" in ans.agreement_line and "weather" in ans.agreement_line
    # QA task 7: the request-shaping choices are one combined line, capped block overall
    # QA task 13: no internal words ("preset") in the user-facing line
    assert any(a.startswith("Scored with") and "12m" in a and "preset" not in a for a in ans.assumptions)
    assert len(ans.assumptions) <= 8 and len(ans.uncertainty_notes) <= 8
    assert "a1" in ans.assumptions and any("confidence 0.60" in u for u in ans.uncertainty_notes)
    assert ans.citations and all(c.source_id and c.vintage for c in ans.citations)
    assert ans.follow_ups == SYN["follow_ups"]
    # QA task 5: nothing is hidden any more, so no hidden-metrics disclosure is emitted
    assert not any("not shown" in u for u in ans.uncertainty_notes)
    assert llm.calls[0]["response_schema"] == SYNTHESIS_SCHEMA


def test_synthesize_informational_from_tool_results(fake_analyst, fake_data, specs):
    from airport_agent.agent.tools.data_tools import build_registry
    out = build_registry(fake_data, fake_analyst).call("get_route_stats", {"iata": "ANC"}, engine="concierge")
    plan = Plan(intent="informational", engines=["tools"], filters={}, tools_to_call=["get_route_stats"], specialist=None, presentation_notes="")
    ans = Synthesizer(ScriptedLLM([{**SYN, "show_metrics": []}]), specs).synthesize(
        message="q", plan=plan, plan_line="pl", req=None, deterministic=None, specialist=None,
        tool_results=[("get_route_stats", {"iata": "ANC"}, out)], trace=[], defaults=None)
    assert ans.analyst_view is None and ans.agreement_line is None
    assert any(t.title.startswith("Distance bands") for t in ans.evidence_tables)
    assert ans.citations[0].source_id == "bts_t100" and any("1,500" in a or "1500" in a for a in ans.assumptions)
    # QA task 13: with no defaults in force the block still closes with an honest line, never empty
    assert ans.assumptions[-1] == NO_DEFAULTS_ASSUMPTION


def test_bad_synthesis_json_falls_back_to_report_text_and_notes_it(fake_analyst, specs):
    req = AnalysisRequest(question_type="rank", airports=["SFO", "JFK"], horizons=["12m"])
    det = fake_analyst.rank(req)
    ans = Synthesizer(ScriptedLLM([LLMResult(text="garbage", provider="f", model="m")]), specs).synthesize(
        message="q", plan=_plan(), plan_line="pl", req=req, deterministic=det, specialist=None, tool_results=[], trace=[], defaults=None)
    assert ans.headline and any("synthesis text unavailable" in u for u in ans.uncertainty_notes)


# --- beyond the brief: coverage notes, loud provider failure, hidden-metric honesty ----------------------

def test_tool_coverage_and_truncation_reach_uncertainty_notes(fake_analyst, fake_data, specs):
    from airport_agent.agent.tools.data_tools import build_registry
    reg = build_registry(fake_data, fake_analyst)
    out = reg.call("score_airports", {"airports": ["BOS", "BDL"]}, engine="concierge")
    plan = Plan(intent="informational", engines=["tools"], filters={}, tools_to_call=["score_airports"],
                specialist=None, presentation_notes="")
    ans = Synthesizer(ScriptedLLM([SYN]), specs).synthesize(
        message="q", plan=plan, plan_line="pl", req=None, deterministic=None, specialist=None,
        tool_results=[("score_airports", {"airports": ["BOS", "BDL"]}, out)], trace=[], defaults=None)
    assert any("coverage" in u for u in ans.uncertainty_notes)
    assert any(t.title.startswith("Ranking") for t in ans.evidence_tables)


def test_llm_error_propagates_from_synthesis(fake_analyst, specs):
    from airport_agent.contracts import LLMError
    req = AnalysisRequest(question_type="rank", airports=["SFO"], horizons=["12m"])
    with pytest.raises(LLMError):
        Synthesizer(ScriptedLLM([LLMError("gemini", 429, "quota")]), specs).synthesize(
            message="q", plan=_plan(), plan_line="pl", req=req, deterministic=fake_analyst.rank(req),
            specialist=None, tool_results=[], trace=[], defaults=None)


def test_defaults_are_disclosed_and_nothing_is_hidden(fake_analyst, specs):
    req = AnalysisRequest(question_type="rank", airports=["SFO", "JFK"], horizons=["12m"])
    det = fake_analyst.rank(req)
    ans = Synthesizer(ScriptedLLM([SYN]), specs).synthesize(
        message="q", plan=_plan(), plan_line="pl", req=req, deterministic=det, specialist=None,
        tool_results=[], trace=[], defaults={"horizon": "12m", "peer_group": "all"})
    # QA task 13: the defaults are disclosed in plain English, never as an internal k=v dump, and
    # they always close the block (never trimmed by the cap, so the block is never empty).
    closing = ans.assumptions[-1]
    assert closing.startswith("Where the question didn't specify")
    assert "time period 12m" in closing and "all airports" in closing
    assert not any("horizon=" in a or "peer_group=" in a for a in ans.assumptions)
    assert not any("comes from a cited source" in a for a in ans.assumptions)  # boilerplate row is gone
    # QA task 5: the data matrix always shows every metric with a value — the LLM cannot hide
    # rows, so there is no hidden-metrics disclosure to make.
    assert not any("not shown" in u for u in ans.uncertainty_notes)
    assert ans.analyst_view is None and ans.agreement_line is None
