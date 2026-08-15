"""Data: ingestion, loading, and caching of airport datasets.

`DuckDBDataService` (Task 14) is the only supported way to read the snapshot;
`refresh` (Task 15) is the only supported way to write it.
"""
from __future__ import annotations

from airport_agent.data.paths import default_snapshot_path
from airport_agent.data.service import DuckDBDataService
from airport_agent.data.store import Store

__all__ = ["DuckDBDataService", "Store", "default_snapshot_path"]
