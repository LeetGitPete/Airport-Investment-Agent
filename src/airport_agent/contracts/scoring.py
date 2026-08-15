"""Deterministic Analyst port. Implementations live in airport_agent.scoring (formula-driven, no LLM)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from airport_agent.contracts.models import Horizon, Metric
from airport_agent.contracts.reports import DeterministicReport
from airport_agent.contracts.requests import AnalysisRequest


@runtime_checkable
class DeterministicAnalyst(Protocol):
    """Transparent, formula-driven ranking/comparison/diagnosis over the metric registry."""

    def rank(self, req: AnalysisRequest) -> DeterministicReport:
        """Score and rank the requested airports/region by the request's scoring preset."""
        ...

    def compare(self, req: AnalysisRequest) -> DeterministicReport:
        """Produce a side-by-side comparison of the requested airports."""
        ...

    def diagnose(self, req: AnalysisRequest) -> DeterministicReport:
        """Produce a diagnostic evidence bundle (e.g. unmet-demand) for the requested airports."""
        ...

    def distance_bands(self, iata: str, horizon: Horizon = "12m", freight: bool = False) -> dict[str, float]:
        """Return route-distance band shares (e.g. short/medium/long-haul) for an airport."""
        ...

    def long_haul_share(self, iata: str, threshold_mi: float = 1500, horizon: Horizon = "12m",
                         freight: bool = False) -> Metric:
        """Return the share of traffic on routes longer than threshold_mi, as a Metric."""
        ...
