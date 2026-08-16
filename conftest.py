"""Repo-root conftest: the only place pytest 8 accepts `pytest_plugins`.

`tests.data.conftest_plugin` appends ("duckdb", ...) to
`tests.contracts.conftest.DATA_SERVICE_FACTORIES` before collection, so the whole DataService
contract suite runs against the real implementation as well as the fake.
"""
from __future__ import annotations

pytest_plugins: list[str] = ["tests.data.conftest_plugin"]
