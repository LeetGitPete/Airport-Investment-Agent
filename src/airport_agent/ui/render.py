"""Render an `Answer` as Streamlit widgets, in the fixed order (contract docstring on `Answer`, design 04):

plan_line -> headline -> evidence_tables -> analyst_view -> agreement_line -> assumptions + uncertainty_notes
-> citations -> follow_ups -> tool_trace.

Never re-interprets, recomputes or reformats numbers beyond display: table cells are shown as delivered by
the `Answer` (values passed straight into a `pandas.DataFrame`; `None` stays `None`/`NaN`, no rounding).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from airport_agent.contracts import Answer, LLMError, MetricSpec, Table


def table_df(table: Table) -> pd.DataFrame:
    """Table rows/columns as delivered — no reformatting. `None` cells stay `None` (pandas may store a
    numeric column's missing values as `NaN`, which is still "missing", not a reinterpreted value)."""
    return pd.DataFrame(table.rows, columns=table.columns)


def column_help(columns: list[str], specs_by_id: dict[str, MetricSpec]) -> dict[str, Any]:
    """Column tooltip = the matching `MetricSpec.definition` when a column name matches a registered
    metric id; columns with no match are omitted (no tooltip)."""
    cfg: dict[str, Any] = {}
    for col in columns:
        spec = specs_by_id.get(col)
        if spec is not None:
            cfg[col] = st.column_config.Column(help=spec.definition)
    return cfg


def assumptions_expanded(answer: Answer) -> bool:
    """Assumptions & uncertainty expander is open by default on analytical answers, collapsed otherwise."""
    return answer.plan.intent == "analytical"


def render_plan_line(plan_line: str) -> None:
    st.caption(plan_line)


def _render_table(table: Table, specs_by_id: dict[str, MetricSpec]) -> None:
    st.markdown(f"*{table.title}*")
    df = table_df(table)
    st.dataframe(df, column_config=column_help(table.columns, specs_by_id), hide_index=True)
    for note in table.footnotes:
        st.caption(note)


def render_answer(
    answer: Answer,
    specs_by_id: dict[str, MetricSpec],
    *,
    key: str,
    on_followup: Callable[[str], None] | None = None,
) -> None:
    render_plan_line(answer.plan_line)
    st.markdown(f"**{answer.headline}**")

    hidden_tables: list[Table] = []
    for i, table in enumerate(answer.evidence_tables):
        if i >= 2 and (table.title.startswith("Evidence") or table.title.startswith("More")):
            hidden_tables.append(table)
        else:
            _render_table(table, specs_by_id)
    if hidden_tables:
        with st.expander("More metrics"):
            for table in hidden_tables:
                _render_table(table, specs_by_id)

    if answer.analyst_view:
        st.subheader("Analyst view")
        st.markdown(answer.analyst_view)

    if answer.agreement_line:
        st.info(answer.agreement_line)

    with st.expander("Assumptions & uncertainty", expanded=assumptions_expanded(answer)):
        st.markdown("**Assumptions**")
        for line in answer.assumptions or ["none stated"]:
            st.markdown(f"- {line}")
        st.markdown("**Uncertainty**")
        for line in answer.uncertainty_notes or ["none stated"]:
            st.markdown(f"- {line}")

    if answer.citations:
        sources = ", ".join(f"{c.source_id} ({c.vintage})" for c in answer.citations)
        st.caption(f"Sources: {sources}")

    for i, text in enumerate(answer.follow_ups):
        if st.button(text, key=f"{key}-fu-{i}"):
            if on_followup is not None:
                on_followup(text)

    with st.expander("Show work"):
        trace_df = pd.DataFrame(
            [
                {
                    "tool": t.tool,
                    "args": json.dumps(t.args),
                    "rows": t.rows,
                    "provider": t.provider,
                    "latency_ms": t.latency_ms,
                    "note": t.note,
                }
                for t in answer.tool_trace
            ],
            columns=["tool", "args", "rows", "provider", "latency_ms", "note"],
        )
        st.dataframe(trace_df, hide_index=True)


def render_error(exc: BaseException) -> None:
    if isinstance(exc, LLMError):
        st.error(str(exc))
        return
    st.error(f"{type(exc).__name__}: {exc}")
    st.caption("Check the data snapshot (data/snapshot/airports.duckdb), config/, and .env.")
