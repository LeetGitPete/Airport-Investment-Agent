"""Render an `Answer` as plain text / JSON for the CLI harness.

Section order matches the fixed render order on `Answer` (contract docstring, design 04):
plan_line -> headline -> evidence_tables -> analyst_view -> agreement_line ->
assumptions + uncertainty_notes -> citations -> follow_ups -> tool_trace.

Never re-interprets, recomputes or reformats numbers beyond display: table cells are printed via `str()`
(faithful to the value delivered by the Answer), `None` printed as `-`.
"""
from __future__ import annotations

from airport_agent.agent.tables import source_name
from airport_agent.contracts import Answer, Table

_ANALYST_TABLE_PREFIX = "Analyst ranking"


def _cell(v: object) -> str:
    return "-" if v is None else str(v)


def table_to_text(table: Table) -> str:
    """Title, then a monospace grid: header row + rows, columns padded to their max width
    (except the last column, which is left ragged to avoid trailing whitespace)."""
    header = [str(c) for c in table.columns]
    rows = [[_cell(v) for v in row] for row in table.rows]
    grid = [header, *rows]
    ncols = len(header)
    widths = [max((len(r[i]) for r in grid if i < len(r)), default=0) for i in range(ncols)]

    def _row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.ljust(widths[i]) if i < ncols - 1 and i < len(widths) else cell)
        return "  ".join(parts)

    lines = [table.title, *(_row(r) for r in grid), *table.footnotes]
    return "\n".join(lines)


def answer_to_text(a: Answer) -> str:
    lines: list[str] = []
    lines.append(f"PLAN: {a.plan_line}")
    lines.append("")
    lines.append(f"HEADLINE: {a.headline}")
    lines.append("")
    computed = [t for t in a.evidence_tables if not t.title.startswith(_ANALYST_TABLE_PREFIX)]
    analyst_tables = [t for t in a.evidence_tables if t.title.startswith(_ANALYST_TABLE_PREFIX)]
    if computed:
        lines.append("== COMPUTED ANALYSIS (every number computed from the cited data) ==")
        lines.append("")
    for table in computed:
        lines.append(table_to_text(table))
        lines.append("")
    if analyst_tables or a.analyst_view:
        lines.append("== ANALYST VIEW (AI specialist interpretation) ==")
        lines.append("")
    for table in analyst_tables:
        lines.append(table_to_text(table))
        lines.append("")
    if a.analyst_view:
        lines.append(f"ANALYST VIEW: {a.analyst_view}")
        lines.append("")
    if a.agreement_line:
        lines.append(f"AGREEMENT: {a.agreement_line}")
        lines.append("")
    lines.append("ASSUMPTIONS:")
    lines.extend(f"- {s}" for s in a.assumptions)
    lines.append("")
    lines.append("UNCERTAINTY:")
    lines.extend(f"- {s}" for s in a.uncertainty_notes)
    lines.append("")
    lines.append("SOURCES:")
    lines.extend(f"- {source_name(c.source_id)} ({c.vintage})" for c in a.citations)
    lines.append("")
    lines.append("FOLLOW-UPS:")
    lines.extend(f"- {s}" for s in a.follow_ups)
    lines.append("")
    lines.append("TOOL TRACE:")
    lines.extend(
        f"- {t.tool} {t.args} rows={_cell(t.rows)} provider={_cell(t.provider)} "
        f"latency_ms={t.latency_ms} note={_cell(t.note)}"
        for t in a.tool_trace
    )
    return "\n".join(lines)


def answer_to_json(a: Answer) -> str:
    return a.model_dump_json(indent=1)
