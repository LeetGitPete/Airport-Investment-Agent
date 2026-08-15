"""Data: ingestion, loading, and caching of airport datasets.

Public surface grows task by task; Task 1 provides the store and paths.
`DuckDBDataService` and `refresh` are added by later tasks in plan 2a.
"""
from __future__ import annotations

from airport_agent.data.paths import default_snapshot_path
from airport_agent.data.store import Store

__all__ = ["Store", "default_snapshot_path"]
