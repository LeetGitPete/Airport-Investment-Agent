"""Repo-root conftest: the only place pytest 8 accepts `pytest_plugins`.

Phase 2: the data workstream registers its DuckDB factory here via
`pytest_plugins = ["tests.data.conftest_plugin"]` — that plugin appends
("duckdb", ...) to tests.contracts.conftest.DATA_SERVICE_FACTORIES before collection,
which runs the whole DataService contract suite against the real implementation too.
"""
from __future__ import annotations

pytest_plugins: list[str] = ["tests.data.conftest_plugin"]
