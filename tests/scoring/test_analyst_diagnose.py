from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest
from airport_agent.scoring.analyst import DIAGNOSE_IDS, Analyst


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_diagnose_sfo_bundle(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"]))
    assert rep.question_type == "diagnose" and rep.comparison is not None
    assert set(rep.comparison) == set(DIAGNOSE_IDS)
    assert rep.comparison["load_factor"]["SFO"] == pytest.approx(0.80)
    assert rep.explanation.startswith("Signals of unmet demand at SFO:")
    assert "✔" in rep.explanation
    assert rep.curated_facts and rep.curated_facts[0].category == "slot_level"
    assert {m.id for m in rep.evidence} == set(DIAGNOSE_IDS)
    assert all(m.source_id and m.vintage for m in rep.evidence)
    assert any("heuristics" in c for c in rep.caveats) and any("circular" in c for c in rep.caveats)


def test_diagnose_sfo_flags_delay_and_npias_and_legal_cap(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"]))
    text = rep.explanation
    assert "✔ FAA NPIAS lists the airport as capacity constrained" in text
    assert "✔ legal capacity constraint in force" in text
    assert "✔ delay in top quartile" in text  # SFO has the worst delay among large hubs in the fake


def test_diagnose_small_airport_has_few_signals(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["PWM"], horizons=["12m"]))
    assert "✘ FAA NPIAS" in rep.explanation and "✘ legal capacity" in rep.explanation
    # tier-B metrics are None for PWM -> those signals absent, values reported as None
    assert rep.comparison["peak_hour_ops_ratio"]["PWM"] is None


def test_diagnose_multiple_airports_joined(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO", "LAX"], horizons=["12m"]))
    assert " | " in rep.explanation and "at LAX:" in rep.explanation
