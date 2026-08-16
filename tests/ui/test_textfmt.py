from __future__ import annotations

import json

from airport_agent.contracts import Table
from airport_agent.ui.textfmt import answer_to_json, answer_to_text, table_to_text
from tests.ui.fake_app import make_answer


def test_text_has_sections_in_fixed_order_and_numbers_verbatim():
    a = make_answer("compare")
    t = answer_to_text(a)
    order = [t.index(h) for h in ("PLAN:", "HEADLINE:", "ASSUMPTIONS:", "UNCERTAINTY:", "FOLLOW-UPS:", "TOOL TRACE:")]
    assert order == sorted(order)
    assert "12.9" in t and "13.9" in t
    # Row 65: the SOURCES paragraph is gone — provenance lives in the "Where this came from" table.
    assert "SOURCES:" not in t
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


def test_empty_sections_are_not_printed_at_all():
    """QA task 19: a conversational turn computes nothing — dead headings read as a broken answer."""
    from airport_agent.contracts import Answer, Plan
    plan = Plan(intent="clarify", engines=[], filters={}, tools_to_call=[], specialist=None,
                presentation_notes="")
    a = Answer(plan=plan, plan_line="How I'm approaching this: outside what I cover — no analysis run",
               headline="I fail to see how this relates to airport investments.", evidence_tables=[],
               analyst_view=None, agreement_line=None, assumptions=[], uncertainty_notes=[],
               citations=[], follow_ups=[], tool_trace=[])
    t = answer_to_text(a)
    for heading in ("ASSUMPTIONS:", "UNCERTAINTY:", "FOLLOW-UPS:", "TOOL TRACE:"):
        assert heading not in t
    assert "PLAN:" in t and "HEADLINE:" in t
    assert t.rstrip().endswith("airport investments.")


def test_a_section_with_content_is_still_printed():
    t = answer_to_text(make_answer("compare"))
    for heading in ("ASSUMPTIONS:", "UNCERTAINTY:", "TOOL TRACE:"):
        assert heading in t


def test_follow_ups_survive_when_they_are_the_only_extra_section():
    """needs_direction: no data, but three suggestions the user can click."""
    from airport_agent.contracts import Answer, Plan
    plan = Plan(intent="clarify", engines=[], filters={}, tools_to_call=[], specialist=None,
                presentation_notes="")
    a = Answer(plan=plan, plan_line="pl", headline="Which of these is closest?", evidence_tables=[],
               analyst_view=None, agreement_line=None, assumptions=[], uncertainty_notes=[],
               citations=[], follow_ups=["Rank New England for expansion"], tool_trace=[])
    t = answer_to_text(a)
    assert "FOLLOW-UPS:" in t and "Rank New England for expansion" in t
    assert "ASSUMPTIONS:" not in t and "SOURCES:" not in t


def test_pointer_table_prints_as_one_line_and_never_the_grid():
    a = make_answer("compare")
    table = a.evidence_tables[0].model_copy(update={"shown_as": "pointer", "first_shown_turn": 1})
    a = a.model_copy(update={"evidence_tables": [table]})
    text = answer_to_text(a)
    assert "already shown earlier in this chat (answer 1)" in text and table.title in text
    assert "12.9" not in text.split("== COMPUTED ANALYSIS")[1].split("ASSUMPTIONS:")[0]


def test_minimal_mode_puts_new_tables_under_a_data_heading():
    a = make_answer("compare")
    a = a.model_copy(update={"plan": a.plan.model_copy(update={"table_display": "minimal"})})
    text = answer_to_text(a)
    assert "-- DATA (new tables for this turn) --" in text and "12.9" in text  # nothing dropped
