"""Fixtures for the DataService contract suite (runs against every registered implementation)."""
from __future__ import annotations

from collections.abc import Callable

import pytest

from airport_agent.contracts import DataService
from tests.fakes import FakeDataService

# Phase 2's data-engineer appends ("duckdb", lambda: DuckDBDataService(test_snapshot)).
DATA_SERVICE_FACTORIES: list[tuple[str, Callable[[], DataService]]] = [("fake", FakeDataService)]


@pytest.fixture(params=DATA_SERVICE_FACTORIES, ids=lambda p: p[0])
def data_service(request):
    return request.param[1]()
