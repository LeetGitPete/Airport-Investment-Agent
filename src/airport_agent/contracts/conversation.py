"""Concierge-facing types: Plan, Answer, session memory."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts.reports import DeterministicReport, SpecialistReport

Intent = Literal["informational", "analytical", "followup", "clarify"]
#: How this turn's tables are shown (contracts-v2). `auto` = a table whose content was already shown in
#: full earlier in the session collapses to a pointer; `repeat` = show everything in full (the user asked
#: to see it again); `minimal` = pointers as in auto AND new tables go behind a collapsed data section
#: so prose leads. Numbers are never dropped — a pointer names the earlier turn that still holds them.
TableDisplay = Literal["auto", "repeat", "minimal"]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    engines: list[str]  # "tools" | "deterministic" | "specialist:<name>"
    filters: dict[str, Any]
    tools_to_call: list[str]
    specialist: str | None
    presentation_notes: str
    table_display: TableDisplay = "auto"


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    columns: list[str]
    rows: list[list[Any]]
    footnotes: list[str] = Field(default_factory=list)
    #: Set by the display policy, never by the LLM. `pointer` = identical content (same columns and
    #: rows, by content hash) was shown in full at `first_shown_turn`; renderers show a one-line
    #: reference instead of the grid.
    shown_as: Literal["full", "pointer"] = "full"
    first_shown_turn: int | None = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    vintage: str
    url: str | None = None


class ToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any]
    rows: int | None
    provider: str | None
    latency_ms: int
    note: str | None = None


class Answer(BaseModel):
    """Fixed synthesis structure (design 03). Order of rendering: plan_line, headline, evidence_tables,
    analyst_view, agreement_line, assumptions+uncertainty_notes, follow_ups, tool_trace."""
    model_config = ConfigDict(extra="forbid")
    plan: Plan
    plan_line: str
    headline: str
    evidence_tables: list[Table]
    analyst_view: str | None
    agreement_line: str | None
    assumptions: list[str]
    uncertainty_notes: list[str]
    citations: list[Citation]
    follow_ups: list[str]
    tool_trace: list[ToolCallTrace]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "system"]
    content: str
    answer: Answer | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    title: str
    messages: list[ChatMessage] = Field(default_factory=list)
    last_airports: list[str] = Field(default_factory=list)
    last_filters: dict[str, Any] = Field(default_factory=dict)
    last_preset: str | None = None
    last_reports: dict[
        str, Annotated[DeterministicReport | SpecialistReport, Field(discriminator="report_type")]
    ] = Field(default_factory=dict)
    #: Content hash of every table shown in full -> the 1-based answer turn where it first appeared.
    #: Read by the display policy so a rebuilt table (typically a follow-up answered from memory)
    #: becomes a pointer instead of the same grid again.
    shown_tables: dict[str, int] = Field(default_factory=dict)
    #: Conversation memory (contracts-v3). `summary` is the compacted account of every answer turn up to
    #: and including `summary_through_turn`, LLM-written and capped in length; the turns after it are
    #: shown to the model verbatim (as digests). `report_archive` keeps every turn's reports by answer
    #: turn, so a follow-up can be resolved against ANY earlier analysis, not only the most recent one
    #: (`last_reports` remains the most-recent shortcut).
    summary: str = ""
    summary_through_turn: int = 0
    report_archive: dict[
        int, list[Annotated[DeterministicReport | SpecialistReport, Field(discriminator="report_type")]]
    ] = Field(default_factory=dict)
