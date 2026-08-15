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

        Horizon semantics. Horizon-invariant metrics (MetricSpec.horizons containing only "static" and/or
        "forecast", or level metrics declaring the requested horizon) are returned at their own declared
        horizon. Trend/level metrics whose MetricSpec.horizons does NOT include the requested horizon MUST
        return None — implementations never relabel a 12m number as a 5y number.

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
        """Return the top routes served by an airport for a horizon, optionally filtered by international status."""
        ...

    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]:
        """Return the annual time series for a metric_id at an airport (used for trends)."""
        ...

    def get_live_status(self, iata: str) -> LiveStatus:
        """Return current operational status (delay programs, ground stops, closures)."""
        ...

    def describe_metrics(self) -> list[MetricSpec]:
        """Return the metric registry (definitions, formulas, sources, caveats)."""
        ...

    def source_vintages(self) -> list[SourceVintage]:
        """Return the vintages of all data sources currently loaded."""
        ...
