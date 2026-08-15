import pytest
from pydantic import ValidationError

from airport_agent.contracts.conversation import Answer, ChatMessage, Plan, SessionState, Table
from airport_agent.contracts.models import CuratedFact
from airport_agent.contracts.reports import DeterministicReport, ScoreRow, SpecialistReport
from airport_agent.contracts.requests import (
    MAX_HINT_CHARS,
    MAX_HINT_CHARS_GENERAL,
    AnalysisRequest,
    truncate_hint,
)
from tests.contracts.test_models import ref


def test_analysis_request_defaults():
    r = AnalysisRequest(question_type="rank", filter={"states": ["MA", "CT"]})
    assert r.horizons == ["5y"] and r.hint == "" and r.specialist is None and r.extended is None


def test_analysis_request_normalizes_airports():
    r = AnalysisRequest(question_type="rank", airports=["bos", " sfo "])
    assert r.airports == ["BOS", "SFO"]


def test_analysis_request_airports_rejects_non_string_items():
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="rank", airports=[None])


def test_analysis_request_needs_airports_or_filter():
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="compare")


def test_hint_truncation_default_and_general():
    long = "x" * 1000
    r, cut = truncate_hint(AnalysisRequest(question_type="diagnose", airports=["SFO"], hint=long))
    assert cut and len(r.hint) == MAX_HINT_CHARS
    r2, cut2 = truncate_hint(AnalysisRequest(question_type="custom", airports=["DEN"], hint=long,
                                             specialist="general_analyst", extended={}))
    assert cut2 and len(r2.hint) == MAX_HINT_CHARS_GENERAL
    r3, cut3 = truncate_hint(AnalysisRequest(question_type="rank", airports=["BOS"], hint="short"))
    assert not cut3 and r3.hint == "short"


def test_truncated_hint_round_trips_through_validation():
    long = "x" * 1000
    r, cut = truncate_hint(AnalysisRequest(question_type="diagnose", airports=["SFO"], hint=long))
    assert cut
    round_tripped = AnalysisRequest.model_validate(r.model_dump())
    assert len(round_tripped.hint) == MAX_HINT_CHARS


def test_custom_requires_general_specialist():
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="custom", airports=["DEN"], specialist="capacity_analyst")


def test_analysis_request_peer_group():
    assert AnalysisRequest(question_type="rank", airports=["BOS"]).peer_group is None  # None = impl default
    assert AnalysisRequest(question_type="rank", airports=["BOS"], peer_group="region").peer_group == "region"
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="rank", airports=["BOS"], peer_group="galaxy")


def test_deterministic_report_curated_facts_and_percentiles_round_trip():
    fact = CuratedFact(iata="SFO", category="slot_level", text="IATA Level 2 schedule-facilitated", value=2,
                       source_url="https://www.faa.gov/slot_administration", as_of="2026-06", expires=None)
    d = DeterministicReport(question_type="rank", preset=None, weights={"P1": 0.35, "load_factor": 0.1}, horizon="5y",
                            peer_group="hub_class", rows=[], comparison=None, evidence=[], explanation="…",
                            caveats=[], curated_facts=[fact],
                            percentiles={"load_factor": {"SFO": 0.42, "BOS": 0.77, "ANC": None}})
    restored = DeterministicReport.model_validate(d.model_dump(mode="json"))
    assert restored.curated_facts[0].iata == "SFO"
    assert restored.percentiles["load_factor"]["BOS"] == 0.77 and restored.percentiles["load_factor"]["ANC"] is None


def test_reports_construct():
    row = ScoreRow(ref=ref("BOS"), score=71.2, rank=1, pillar_contrib={"P1": 20.0}, metric_contrib={"enpl_cagr_5y": 8.0},
                   coverage=0.9, low_confidence=False)
    d = DeterministicReport(question_type="rank", preset="terminal_expansion", weights={"P1": 0.35}, horizon="5y",
                            peer_group="hub_class", rows=[row], comparison=None, evidence=[], explanation="BOS leads…",
                            caveats=[])
    s = SpecialistReport(specialist="expansion_analyst", question_type="rank", ranking=[], narrative="…", evidence=[],
                         agreement="agrees on top 3", disagreements=[], confidence=0.7, assumptions=[], caveats=[],
                         hint_truncated=False)
    assert d.rows[0].rank == 1 and 0 <= s.confidence <= 1
    with pytest.raises(ValidationError):
        SpecialistReport(specialist="x", question_type="rank", ranking=[], narrative="", evidence=[], agreement=None,
                         disagreements=[], confidence=1.5, assumptions=[], caveats=[], hint_truncated=False)


def test_plan_answer_session():
    p = Plan(intent="analytical", engines=["deterministic", "specialist:capacity_analyst"], filters={"airports": ["LAX", "SNA"]},
             tools_to_call=["compare_airports"], specialist="capacity_analyst", presentation_notes="show P2 only")
    a = Answer(plan=p, plan_line="compare · congestion · 12m", headline="SNA is more constrained relative to capacity",
               evidence_tables=[Table(title="P2 metrics", columns=["metric", "LAX", "SNA"], rows=[["avg_dep_delay_min", 12.9, 13.9]],
                                      footnotes=["OTP through 2026-06"])],
               analyst_view=None, agreement_line=None, assumptions=["OTP 24m"], uncertainty_notes=[], citations=[],
               follow_ups=["Why is SNA capped?"], tool_trace=[])
    s = SessionState(session_id="s1", title="test")
    s.messages.append(ChatMessage(role="user", content="hi"))
    assert a.headline and s.last_reports == {} and s.messages[0].role == "user"


def test_session_state_last_reports_discriminates_report_types():
    d = DeterministicReport(question_type="rank", preset=None, weights={"P1": 0.35}, horizon="5y",
                            peer_group="hub_class", rows=[], comparison=None, evidence=[], explanation="…",
                            caveats=[])
    s = SpecialistReport(specialist="expansion_analyst", question_type="rank", ranking=[], narrative="…",
                         evidence=[], agreement=None, disagreements=[], confidence=0.6, assumptions=[], caveats=[],
                         hint_truncated=False)
    session = SessionState(session_id="s1", title="test", last_reports={"deterministic": d, "specialist": s})
    dumped = session.model_dump(mode="json")
    restored = SessionState.model_validate(dumped)
    assert isinstance(restored.last_reports["deterministic"], DeterministicReport)
    assert isinstance(restored.last_reports["specialist"], SpecialistReport)
