"""Data access port. Implementations live in airport_agent.data (DuckDB-backed)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from airport_agent.contracts.models import (
    AirportFilter,
    AirportProfile,
    AirportRef,
    FeatureMatrix,
    Horizon,
    LiveStatus,
    Metric,
    MetricSpec,
    PeerGroup,
    RouteTable,
    SourceVintage,
)


@runtime_checkable
class DataService(Protocol):
    """Read-only access to airport reference data, metrics, routes, and live status."""

    def list_airports(self, filter: AirportFilter) -> list[AirportRef]:
        """Return airports matching the filter."""
        ...

    def get_airport(self, iata: str) -> AirportRef | None:
        """Return a single airport by IATA code, or None if unknown."""
        ...

    def get_feature_matrix(self, airports: list[str], metric_ids: list[str], horizon: Horizon,
                            peer_group: PeerGroup = "hub_class") -> FeatureMatrix:
        """Return a dense numeric matrix of metric_ids x airports for the Deterministic Analyst.

        Horizon semantics. Horizon-invariant metrics = MetricSpec.horizons is a subset of
        {"static", "forecast"}; they are returned at their own declared horizon regardless of the requested
        one. Non-invariant metrics: returned only if MetricSpec.horizons includes the requested horizon,
        else None. Never relabel across horizons — no implementation may pass a 12m number off as a 5y one.

        Unknown iata -> raise KeyError; unknown metric id -> raise KeyError.
        """
        ...

    def get_profile(self, iata: str, horizons: tuple[Horizon, ...] = ("12m", "5y")) -> AirportProfile:
        """Return a structured profile (metrics, forecast, routes summary, curated facts) for the LLM specialists.

        Metrics follow the same horizon rule as get_feature_matrix: a metric that does not declare the
        requested horizon is reported with value None at its own declared horizon, never relabeled.
        Unknown iata -> raise KeyError.
        """
        ...

    def get_routes(self, iata: str, horizon: Horizon = "12m", top_n: int = 25,
                    international: bool | None = None) -> RouteTable:
        """Return the top routes served by an airport for a horizon, optionally filtered by international status.

        Unknown iata -> raise KeyError (never an empty/fabricated result).
        """
        ...

    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]:
        """Return the annual series for a metric_id at an airport, at the metric's own declared horizon.

        Metrics declaring "12m" -> one Metric per calendar year with horizon "12m"; trend metrics
        (3y/5y/10y) -> one per year at that horizon; horizon-invariant metrics (static/forecast) -> []
        (a static value has no time series).
        Unknown iata -> KeyError; unknown metric id -> KeyError; metric unavailable for this airport -> [].
        """
        ...

    def get_live_status(self, iata: str) -> LiveStatus:
        """Return current operational status (delay programs, ground stops, closures).

        Unknown iata -> raise KeyError (never an empty/fabricated result).
        """
        ...

    def describe_metrics(self) -> list[MetricSpec]:
        """Return the metric registry (definitions, formulas, sources, caveats)."""
        ...

    def source_vintages(self) -> list[SourceVintage]:
        """Return the vintages of all data sources currently loaded."""
        ...
