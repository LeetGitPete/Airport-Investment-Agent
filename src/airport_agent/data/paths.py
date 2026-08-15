"""Filesystem locations used by the data layer.

All paths are derived from the repo root so the package works the same way
regardless of the caller's current working directory.
"""
from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root (three levels above this file: src/airport_agent/data/paths.py)."""
    return Path(__file__).resolve().parents[3]


def default_snapshot_path() -> Path:
    """Path to the committed DuckDB snapshot: repo_root/data/snapshot/airports.duckdb."""
    return repo_root() / "data" / "snapshot" / "airports.duckdb"


def raw_cache_dir() -> Path:
    """Gitignored cache directory for raw downloads: repo_root/data/raw."""
    return repo_root() / "data" / "raw"


def curated_dir() -> Path:
    """Directory holding hand-curated YAML inputs: repo_root/data/curated."""
    return repo_root() / "data" / "curated"
