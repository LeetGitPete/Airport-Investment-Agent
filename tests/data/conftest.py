"""Shared fixtures for the `tests/data` suite."""
from __future__ import annotations

from pathlib import Path

import duckdb
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


@pytest.fixture(scope="session")
def test_snapshot_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped: build the fixture-derived test snapshot once (`build_test_snapshot`
    runs in seconds, but every derived-metrics/service test reusing the same file avoids
    rebuilding it per test)."""
    from tests.data.build_test_snapshot import build_test_snapshot

    path = tmp_path_factory.mktemp("snapshot") / "test.duckdb"
    return build_test_snapshot(path)


@pytest.fixture
def snapshot_con(test_snapshot_path: Path):
    """A read-only DuckDB connection to the session test snapshot."""
    con = duckdb.connect(str(test_snapshot_path), read_only=True)
    try:
        yield con
    finally:
        con.close()
