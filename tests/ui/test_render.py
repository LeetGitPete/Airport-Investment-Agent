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
