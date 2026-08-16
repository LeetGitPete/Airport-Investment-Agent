"""Fixtures for the DataService contract suite (runs against every registered implementation).

Extension mechanism: DATA_SERVICE_FACTORIES is a plain module-level list read at collection time by
`pytest_generate_tests` below, so a plugin loaded before collection may append to it and its
implementation is then exercised by the whole suite. The DuckDB implementation registers itself as:

    # repo-root conftest.py
    pytest_plugins = ["tests.data.conftest_plugin"]
    # tests/data/conftest_plugin.py
    from tests.contracts.conftest import DATA_SERVICE_FACTORIES
    DATA_SERVICE_FACTORIES.append(("duckdb", lambda: DuckDBDataService(test_snapshot)))

A `@pytest.fixture(params=DATA_SERVICE_FACTORIES)` would NOT work: params are snapshotted when the
decorator runs, i.e. when this conftest is imported, which is before any plugin can append.

The list is shared by import path, so the plugin and this module must resolve to the same module object:
keep `tests/__init__.py` and `tests/contracts/__init__.py` (and the repo root on sys.path, added by
`tests/conftest.py`), so everything imports it as `tests.contracts.conftest` — a rootdir-relative
re-import under a different name would append to a second, unused copy of the list.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest

from airport_agent.contracts import DataService
from tests.fakes import FakeDataService

DATA_SERVICE_FACTORIES: list[tuple[str, Callable[[], DataService]]] = [("fake", FakeDataService)]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "data_service" in metafunc.fixturenames:
        metafunc.parametrize("data_service", [f for _, f in DATA_SERVICE_FACTORIES],
                             ids=[n for n, _ in DATA_SERVICE_FACTORIES], indirect=True)


@pytest.fixture
def data_service(request):
    return request.param()
