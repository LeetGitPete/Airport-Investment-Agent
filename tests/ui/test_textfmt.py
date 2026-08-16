from __future__ import annotations

import json

from airport_agent.contracts import Table
from airport_agent.ui.textfmt import answer_to_json, answer_to_text, table_to_text
from tests.ui.fake_app import make_answer


def test_text_has_sections_in_fixed_order_and_numbers_verbatim():
    a = make_answer("compare")
    t = answer_to_text(a)
    order = [t.index(h) for h in ("PLAN:", "HEADLINE:", "ASSUMPTIONS:", "UNCERTAINTY:", "SOURCES:", "FOLLOW-UPS:", "TOOL TRACE:")]
    assert order == sorted(order)
    assert "12.9" in t and "13.9" in t
    assert "BTS On-Time Performance (2026-04)" in t  # user-facing source names in SOURCES
    # Layout: analyst view precedes the computed tables
    assert (t.index("ANALYST VIEW:") < t.index("DO THE NUMBERS AND THE ANALYST AGREE?")
            < t.index(a.evidence_tables[0].title))
    assert t.index("== ANALYST VIEW") < t.index("== COMPUTED ANALYSIS") < t.index("ASSUMPTIONS:")


def test_informational_omits_analyst_sections_but_keeps_assumptions():
    t = answer_to_text(make_answer("informational"))
    assert "ANALYST VIEW:" not in t and "AGREEMENT:" not in t and "ASSUMPTIONS:" in t


def test_json_roundtrip():
    a = make_answer("rank")
    assert json.loads(answer_to_json(a))["headline"] == a.headline


def test_none_cell_rendered_as_dash():
    table = Table(title="T", columns=["a", "b"], rows=[[1, None]], footnotes=[])
    lines = table_to_text(table).splitlines()
    assert lines[-1].split("  ")[-1].strip() == "-"


def test_footnotes_rendered():
    table = Table(title="T", columns=["a"], rows=[[1]], footnotes=["note one", "note two"])
    t = table_to_text(table)
    assert "note one" in t and "note two" in t
    assert t.splitlines()[-2:] == ["note one", "note two"]
