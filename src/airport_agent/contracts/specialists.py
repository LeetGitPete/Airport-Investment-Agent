"""LLM Specialist port. Implementations live in airport_agent.agent (specialist runner + tool loop)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from airport_agent.contracts.reports import DeterministicReport, SpecialistReport
from airport_agent.contracts.requests import AnalysisRequest


@runtime_checkable
class SpecialistRunner(Protocol):
    """Runs a configured LLM specialist over an AnalysisRequest, optionally given the deterministic view."""

    def run(self, req: AnalysisRequest, deterministic: DeterministicReport | None) -> SpecialistReport:
        """Dispatch to the specialist named in req.specialist and return its structured report."""
        ...
