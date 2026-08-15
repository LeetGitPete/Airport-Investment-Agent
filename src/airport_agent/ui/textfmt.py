"""Render an `Answer` as plain text / JSON for the CLI harness.

Section order matches the fixed render order on `Answer` (contract docstring, design 04):
plan_line -> headline -> evidence_tables -> analyst_view -> agreement_line ->
assumptions + uncertainty_notes -> citations -> follow_ups -> tool_trace.

Never re-interprets, recomputes or reformats numbers beyond display: table cells are printed via `str()`
(faithful to the value delivered by the Answer), `None` printed as `-`.
"""
from __future__ import annotations

from airport_agent.contracts import Answer, Table


def _cell(v: object) -> str:
    return "-" if v is None else str(v)


def table_to_text(table: Table) -> str:
    lines = [table.title, "  ".join(table.columns)]
    lines.extend("  ".join(_cell(v) for v in row) for row in table.rows)
    lines.extend(table.footnotes)
    return "\n".join(lines)


def answer_to_text(a: Answer) -> str:
    lines: list[str] = []
    lines.append(f"PLAN: {a.plan_line}")
    lines.append("")
    lines.append(f"HEADLINE: {a.headline}")
    lines.append("")
    for table in a.evidence_tables:
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
    lines.extend(f"- {c.source_id} ({c.vintage})" for c in a.citations)
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
