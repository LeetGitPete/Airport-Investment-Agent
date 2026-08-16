from __future__ import annotations

from airport_agent.contracts import Table, load_registry, registry_by_id
from airport_agent.ui.render import column_help, table_df


def test_table_df_keeps_values_and_none():
    df = table_df(Table(title="t", columns=["a", "b"], rows=[[1.25, None], ["x", 2]]))
    assert list(df.columns) == ["a", "b"]
    assert df.iloc[0, 0] == 1.25
    cell = df.iloc[0, 1]
    assert cell is None or cell != cell  # None kept, or pandas coerced it to NaN (still "missing")


def test_column_help_uses_metric_definitions():
    by_id = registry_by_id(load_registry())
    cfg = column_help(["airport", "load_factor"], by_id)
    assert "load_factor" in cfg and "airport" not in cfg


def _pointer_script():
    from airport_agent.contracts import load_registry, registry_by_id
    from airport_agent.ui.render import render_answer
    from tests.ui.fake_app import make_answer

    a = make_answer("compare")
    table = a.evidence_tables[0].model_copy(update={"shown_as": "pointer", "first_shown_turn": 2})
    render_answer(a.model_copy(update={"evidence_tables": [table]}), registry_by_id(load_registry()), key="k")


def _minimal_script():
    from airport_agent.contracts import load_registry, registry_by_id
    from airport_agent.ui.render import render_answer
    from tests.ui.fake_app import make_answer

    a = make_answer("compare")
    a = a.model_copy(update={"plan": a.plan.model_copy(update={"table_display": "minimal"})})
    render_answer(a, registry_by_id(load_registry()), key="k")


def test_pointer_table_renders_as_a_caption_not_a_grid():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_pointer_script, default_timeout=30)
    at.run()
    assert not at.exception
    # The only grid left is the tool trace inside "Show work"; the evidence table itself is gone.
    top_level = [c for c in at.main.children.values() if c.type == "arrow_data_frame"]
    assert not top_level
    assert any("already shown earlier in this chat (answer 2)" in c.value for c in at.main.caption)


def _trace_script():
    from airport_agent.contracts import load_registry, registry_by_id
    from airport_agent.ui.render import render_answer
    from tests.ui.fake_app import make_answer

    render_answer(make_answer("compare"), registry_by_id(load_registry()), key="k")


def test_show_work_trace_has_user_facing_columns_and_no_raw_tool_or_args():
    """Rows 65-66: Show work keeps step/rows/source/time (ms)/note; the raw tool id and args
    columns are gone (they stay on ToolCallTrace for the debug log and archive)."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_trace_script, default_timeout=30)
    at.run()
    assert not at.exception
    trace = next(d.value for d in at.main.dataframe if "step" in d.value.columns)
    assert list(trace.columns) == ["step", "rows", "source", "time (ms)", "note"]
    assert "get_feature_matrix" not in trace.to_string()  # fake's raw tool id never rendered
    assert "horizon" not in trace.to_string()  # no args dump


def test_minimal_mode_keeps_new_tables_behind_a_data_expander():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_minimal_script, default_timeout=30)
    at.run()
    assert not at.exception
    assert any(e.label.startswith("Data (1 table") for e in at.main.expander)
    assert at.main.dataframe  # still rendered, one click away
