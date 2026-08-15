"""Concierge-facing types: Plan, Answer, session memory."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts.reports import DeterministicReport, SpecialistReport

Intent = Literal["informational", "analytical", "followup", "clarify"]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    engines: list[str]  # "tools" | "deterministic" | "specialist:<name>"
    filters: dict[str, Any]
    tools_to_call: list[str]
    specialist: str | None
    presentation_notes: str


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    columns: list[str]
    rows: list[list[Any]]
    footnotes: list[str] = Field(default_factory=list)


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
