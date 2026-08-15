from __future__ import annotations

import json

from airport_agent.ui.textfmt import answer_to_json, answer_to_text
from tests.ui.fake_app import make_answer


def test_text_has_sections_in_fixed_order_and_numbers_verbatim():
    a = make_answer("compare")
    t = answer_to_text(a)
    order = [t.index(h) for h in ("PLAN:", "HEADLINE:", "ASSUMPTIONS:", "UNCERTAINTY:", "SOURCES:", "FOLLOW-UPS:", "TOOL TRACE:")]
    assert order == sorted(order)
    assert "12.9" in t and "13.9" in t and "bts_otp (2026-04)" in t
    assert t.index(a.evidence_tables[0].title) < t.index("ANALYST VIEW:") < t.index("AGREEMENT:") < t.index("ASSUMPTIONS:")


def test_informational_omits_analyst_sections_but_keeps_assumptions():
    t = answer_to_text(make_answer("informational"))
    assert "ANALYST VIEW:" not in t and "AGREEMENT:" not in t and "ASSUMPTIONS:" in t


def test_json_roundtrip():
    a = make_answer("rank")
    assert json.loads(answer_to_json(a))["headline"] == a.headline
