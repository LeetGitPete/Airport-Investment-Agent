"""Outputs of the two analytical engines."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts.models import AirportRef, Horizon, Metric, PeerGroup
from airport_agent.contracts.requests import QuestionType


class ScoreRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: AirportRef
    score: float  # 0–100
    rank: int
    pillar_contrib: dict[str, float]
    metric_contrib: dict[str, float]
    coverage: float  # 0–1 share of metrics available for this airport
    low_confidence: bool


class DeterministicReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: Literal["deterministic"] = "deterministic"
    question_type: QuestionType
    preset: str | None
    weights: dict[str, float]
    horizon: Horizon
    peer_group: PeerGroup
    rows: list[ScoreRow]
    comparison: dict[str, dict[str, float | None]] | None  # metric_id -> {iata: value}
    evidence: list[Metric]
    explanation: str  # templated, formula-driven
    caveats: list[str]


class RankedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iata: str
    rank: int
    rationale: str
    confidence: float = Field(ge=0, le=1)


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: Literal["specialist"] = "specialist"
    specialist: str
    question_type: QuestionType
    ranking: list[RankedItem] | None
    narrative: str
    evidence: list[Metric]
    agreement: str | None
    disagreements: list[str]
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str]
    caveats: list[str]
    hint_truncated: bool
