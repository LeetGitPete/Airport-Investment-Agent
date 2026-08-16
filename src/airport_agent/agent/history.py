"""Conversation history as the model sees it (design 03 §memory, contracts-v3).

A session's transcript is `SessionState.messages`; a TURN is one user message and the assistant reply
that follows it, numbered 1..N by reply (the same number `Table.first_shown_turn` and
`SessionState.summary_through_turn` use). This module turns a turn into ONE fixed plain-text digest —
question, headline, analyst view, agreement, and each table as its title plus a few rows — and that
digest is the only form of history any LLM call receives:

  planner / synthesis  <- `summary` + digests of the last KEEP_VERBATIM turns
  compactor            <- `summary` + digests of the turns older than those, which it folds in

One representation, one place to tune it, one test. Nothing here calls the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

from airport_agent.contracts import Answer, DeterministicReport, SessionState, SpecialistReport, Table

#: How many of the most recent turns every LLM call sees verbatim (as digests). Older turns live in
#: `SessionState.summary`.
KEEP_VERBATIM = 5
#: Per-field caps inside a digest, so one verbose turn cannot crowd the others out of the prompt.
Q_CHARS = 300
HEADLINE_CHARS = 300
ANALYST_CHARS = 300
AGREEMENT_CHARS = 200
TABLE_ROWS = 5
CELL_CHARS = 24


@dataclass(frozen=True)
class Turn:
    number: int  # 1-based, by assistant reply
    question: str
    reply: str  # the assistant message text (headline, or the clarifying question)
    answer: Answer | None


def turns(state: SessionState) -> list[Turn]:
    """The transcript as turns. A user message with no reply yet (mid-turn) is not a turn."""
    out: list[Turn] = []
    pending: str | None = None
    for m in state.messages:
        if m.role == "user":
            pending = m.content
        elif m.role == "assistant":
            out.append(Turn(number=len(out) + 1, question=pending or "", reply=m.content, answer=m.answer))
            pending = None
    return out


def recent_turns(state: SessionState) -> list[Turn]:
    """The turns shown verbatim: the last KEEP_VERBATIM, and never one already folded into the summary."""
    all_turns = turns(state)
    return [t for t in all_turns[-KEEP_VERBATIM:] if t.number > state.summary_through_turn]


def turns_to_fold(state: SessionState) -> list[Turn]:
    """Turns older than the verbatim window that the summary does not cover yet."""
    all_turns = turns(state)
    cutoff = len(all_turns) - KEEP_VERBATIM
    return [t for t in all_turns if state.summary_through_turn < t.number <= cutoff]


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return _clip(str(value), CELL_CHARS)


def table_digest(table: Table) -> str:
    """`Title (n rows: r1 · r2 · …)` — the first TABLE_ROWS rows, cells space-joined."""
    rows = [" ".join(_cell(c) for c in row) for row in table.rows[:TABLE_ROWS]]
    more = f", +{len(table.rows) - TABLE_ROWS} more" if len(table.rows) > TABLE_ROWS else ""
    body = "; ".join(rows)
    return f"{table.title} ({len(table.rows)} rows{more}: {body})" if body else f"{table.title} (0 rows)"


def turn_digest(turn: Turn) -> str:
    """The one fixed plain-text form of a turn that every LLM call sees."""
    lines = [f"[turn {turn.number}] Q: {_clip(turn.question, Q_CHARS)}"]
    a = turn.answer
    if a is None:
        lines.append(f"  A: {_clip(turn.reply, HEADLINE_CHARS)}")
        return "\n".join(lines)
    lines.append(f"  A ({a.plan.intent}): {_clip(a.headline, HEADLINE_CHARS)}")
    if a.analyst_view:
        lines.append(f"  Analyst: {_clip(a.analyst_view, ANALYST_CHARS)}")
    if a.agreement_line:
        lines.append(f"  Agreement: {_clip(a.agreement_line, AGREEMENT_CHARS)}")
    if a.evidence_tables:
        lines.append("  Tables: " + " · ".join(table_digest(t) for t in a.evidence_tables))
    return "\n".join(lines)


def archive_index(state: SessionState) -> list[str]:
    """One line per archived turn — what analysis it holds — so the planner can name a `source_turn`."""
    lines: list[str] = []
    for number in sorted(state.report_archive):
        parts: list[str] = []
        for rep in state.report_archive[number]:
            if isinstance(rep, DeterministicReport):
                airports = [row.ref.iata for row in rep.rows]
                shown = ", ".join(airports[:6]) + (f" +{len(airports) - 6}" if len(airports) > 6 else "")
                parts.append(f"{rep.question_type} · preset {rep.preset or 'default'} · {rep.horizon}"
                             f" · {len(airports)} airports ({shown})")
            elif isinstance(rep, SpecialistReport):
                parts.append(f"specialist {rep.specialist}")
        lines.append(f"turn {number}: " + "; ".join(parts))
    return lines
