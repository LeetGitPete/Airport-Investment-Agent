from __future__ import annotations

from airport_agent.contracts import Table, load_registry, registry_by_id
from airport_agent.ui.render import assumptions_expanded, column_help, metric_ids_in_table, table_df
from tests.ui.fake_app import make_answer


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


def test_assumptions_expanded_only_for_analytical():
    assert assumptions_expanded(make_answer("rank")) is True
    assert assumptions_expanded(make_answer("informational")) is False


def test_metric_ids_in_table_dedupes_cell_matches_only():
    by_id = registry_by_id(load_registry())
    table = Table(
        title="t",
        columns=["metric", "value"],
        rows=[["load_factor", 0.8], ["load_factor", 0.9], ["spill_proxy", 0.1], ["not_a_metric_id", 1]],
    )
    assert metric_ids_in_table(table, by_id) == ["load_factor", "spill_proxy"]
