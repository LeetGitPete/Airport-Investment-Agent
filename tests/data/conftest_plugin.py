"""Registers the `duckdb` factory into the shared DataService contract suite.

Loaded via the repo-root `conftest.py`'s `pytest_plugins` list (pytest 8 only accepts
`pytest_plugins` there — see `tests.contracts.conftest` for why `DATA_SERVICE_FACTORIES`
must be appended to, not re-parametrized, and why the import path matters).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from airport_agent.data import DuckDBDataService
from tests.contracts.conftest import DATA_SERVICE_FACTORIES
from tests.data.build_test_snapshot import build_test_snapshot

_PATH = build_test_snapshot(Path(tempfile.mkdtemp(prefix="aa-snap-")) / "test.duckdb")
DATA_SERVICE_FACTORIES.append(("duckdb", lambda: DuckDBDataService(_PATH, live=False)))
