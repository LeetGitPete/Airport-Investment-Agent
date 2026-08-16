"""Render an `Answer` as plain text / JSON for the CLI harness.

Section order matches the fixed render order on `Answer` (contract docstring, design 04):
plan_line -> headline -> evidence_tables -> analyst_view -> agreement_line ->
assumptions + uncertainty_notes -> citations -> follow_ups -> tool_trace.

Never re-interprets, recomputes or reformats numbers beyond display: table cells are printed via `str()`
(faithful to the value delivered by the Answer), `None` printed as `-`.
"""
from __future__ import annotations

from airport_agent.agent.tables import score_summary, source_name
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


def pointer_line(table: Table) -> str:
    """A `pointer` table (identical content shown earlier in the chat) prints as one line."""
    return f"^ {table.title} -- unchanged since answer #{table.first_shown_turn} above (not repeated)"


def _table_block(table: Table) -> str:
    return pointer_line(table) if table.shown_as == "pointer" else table_to_text(table)


def answer_to_text(a: Answer) -> str:
    lines: list[str] = []
    lines.append(f"PLAN: {a.plan_line}")
    lines.append("")
    lines.append(f"HEADLINE: {a.headline}")
    lines.append("")
    computed = [t for t in a.evidence_tables if not t.title.startswith(_ANALYST_TABLE_PREFIX)]
    analyst_tables = [t for t in a.evidence_tables if t.title.startswith(_ANALYST_TABLE_PREFIX)]
    # The deterministic score leads, with a one-line formula statement.
    summary = score_summary(computed)
    if summary:
        strip = " · ".join(f"{iata} {score:.0f}" if isinstance(score, int | float)
                           else f"{iata} {score}" for iata, score in summary["scores"])
        more = (f" (top {summary['shown']} of {summary['total']})"
                if summary["total"] > summary["shown"] else "")
        lines.append(f"SCORE: {strip} — {summary['label']} (0-100){more}")
        lines.append(summary["caption"])
        lines.append("")
    # Layout: headline -> analyst view -> computed scores & data.
    if analyst_tables or a.analyst_view:
        lines.append("== ANALYST VIEW (AI specialist interpretation) ==")
        lines.append("")
    for table in analyst_tables:
        lines.append(_table_block(table))
        lines.append("")
    if a.analyst_view:
        lines.append(f"ANALYST VIEW: {a.analyst_view}")
        lines.append("")
    if a.agreement_line:
        lines.append(f"DO THE NUMBERS AND THE ANALYST AGREE? {a.agreement_line}")
        lines.append("")
    if computed:
        lines.append("== COMPUTED ANALYSIS (every number computed from the cited data) ==")
        lines.append("")
    # `minimal` (a narrow follow-up): pointers first, then the new tables under a DATA heading so
    # the prose reads first; nothing is dropped.
    if a.plan.table_display == "minimal":
        computed = sorted(computed, key=lambda t: t.shown_as != "pointer")
        if any(t.shown_as == "full" for t in computed):
            lines.append("-- DATA (new tables for this turn) --")
    for table in computed:
        lines.append(_table_block(table))
        lines.append("")
    # QA task 19 (2026-08-16): a section with nothing in it is not printed — a conversational turn
    # computes nothing, and four dead headings trailing every reply read as an error.
    def _section(title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append(title)
        lines.extend(f"- {s}" for s in items)
        lines.append("")

    _section("ASSUMPTIONS:", list(a.assumptions))
    _section("UNCERTAINTY:", list(a.uncertainty_notes))
    _section("SOURCES:", [f"{source_name(c.source_id)} ({c.vintage})" for c in a.citations])
    _section("FOLLOW-UPS:", list(a.follow_ups))
    _section("TOOL TRACE:", [
        f"{t.tool} {t.args} rows={_cell(t.rows)} provider={_cell(t.provider)} "
        f"latency_ms={t.latency_ms} note={_cell(t.note)}"
        for t in a.tool_trace
    ])
    return "\n".join(lines).rstrip() + "\n"


def answer_to_json(a: Answer) -> str:
    return a.model_dump_json(indent=1)
