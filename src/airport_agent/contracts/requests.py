"""Structured dispatch types (Concierge → Deterministic Analyst / LLM specialists)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from airport_agent.contracts.models import AirportFilter, Horizon, PeerGroup

QuestionType = Literal["rank", "compare", "diagnose", "custom"]
SpecialistName = Literal["expansion_analyst", "capacity_analyst", "market_analyst", "general_analyst"]
MAX_HINT_CHARS = 200
MAX_HINT_CHARS_GENERAL = 600


class ExtendedOptions(BaseModel):
    """Only honoured for general_analyst."""
    model_config = ConfigDict(extra="forbid")
    requested_sections: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    peer_group: PeerGroup | None = None


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType
    airports: list[str] | None = None
    filter: AirportFilter | None = None
    horizons: list[Horizon] = Field(default_factory=lambda: ["5y"])
    peer_group: PeerGroup | None = None  # None => implementation default ("hub_class")
    scoring_preset: str | None = None
    focus_metrics: list[str] | None = None
    hint: str = ""
    specialist: SpecialistName | None = None
    extended: ExtendedOptions | None = None

    @field_validator("airports", mode="before")
    @classmethod
    def _upper_airports(cls, v: list[str] | None) -> list[str] | None:
        if not isinstance(v, list):
            return v
        return [s.strip().upper() if isinstance(s, str) else s for s in v]

    @model_validator(mode="after")
    def _target(self) -> AnalysisRequest:
        if not self.airports and self.filter is None:
            raise ValueError("AnalysisRequest needs airports or a filter")
        if self.question_type == "custom" and self.specialist != "general_analyst":
            raise ValueError("question_type=custom is only valid for general_analyst")
        if self.extended is not None and self.specialist != "general_analyst":
            raise ValueError("extended options are only valid for general_analyst")
        return self


def hint_limit(req: AnalysisRequest) -> int:
    return MAX_HINT_CHARS_GENERAL if req.specialist == "general_analyst" else MAX_HINT_CHARS


def truncate_hint(req: AnalysisRequest) -> tuple[AnalysisRequest, bool]:
    """Return (request with hint cut to its limit, was_truncated)."""
    limit = hint_limit(req)
    if len(req.hint) <= limit:
        return req, False
    # model_copy(update=...) does not re-run validators. That is acceptable here because
    # no validator on AnalysisRequest depends on `hint` (only on airports/filter/question_type).
    return req.model_copy(update={"hint": req.hint[:limit]}), True
