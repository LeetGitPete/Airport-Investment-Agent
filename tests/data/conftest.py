"""Shared fixtures for the `tests/data` suite."""
from __future__ import annotations

from pathlib import Path

import pytest

from airport_agent.data.store import Store


@pytest.fixture
def fixtures_dir() -> Path:
    """Directory holding committed real-but-tiny fixture subsets."""
    return Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    """A fresh Store backed by a DuckDB file in a pytest tmp_path."""
    return Store(tmp_path / "test.duckdb")
