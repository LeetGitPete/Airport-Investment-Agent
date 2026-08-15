from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest, DeterministicAnalyst, LLMClient, LLMError
from tests.agent.fake_llm import ScriptedLLM


def test_scripted_llm_pops_and_records():
    llm = ScriptedLLM([{"a": 1}, "plain", LLMError("gemini", 429, "quota")])
    assert isinstance(llm, LLMClient)
    assert llm.chat([{"role": "user", "content": "x"}]).text == '{"a": 1}'
    assert llm.chat([]).text == "plain"
    with pytest.raises(LLMError):
        llm.chat([])
    with pytest.raises(AssertionError, match="exhausted"):
        llm.chat([])
    assert len(llm.calls) == 4


def test_fake_analyst_reports_are_valid_and_carry_provenance(fake_analyst):
    assert isinstance(fake_analyst, DeterministicAnalyst)
    rep = fake_analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["12m"]))
    assert [r.rank for r in rep.rows] == [1, 2] and rep.evidence and all(m.vintage for m in rep.evidence)
    cmp_ = fake_analyst.compare(AnalysisRequest(question_type="compare", airports=["LAX", "SNA"], horizons=["12m"]))
    assert cmp_.comparison["avg_dep_delay_min"] == {"LAX": 12.9, "SNA": 13.9}
    assert fake_analyst.long_haul_share("ANC", freight=True).value > fake_analyst.long_haul_share("ANC").value
