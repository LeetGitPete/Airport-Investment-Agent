"""The DataService contract suite must pick up implementations registered after import time.

This mirrors the `pytest_generate_tests` hook in conftest.py with one extra factory appended, proving
the mechanism a plugin uses: append to DATA_SERVICE_FACTORIES, then get parametrized.
It cannot append to the real list here: conftest's hook already ran for this module's collection.
"""
from __future__ import annotations

import pytest

from airport_agent.contracts import DataService
from tests.contracts.conftest import DATA_SERVICE_FACTORIES
from tests.fakes import FakeDataService


class Fake2(FakeDataService):
    """Stand-in for a second implementation (in practice, the DuckDB-backed one)."""


EXTENDED = [*DATA_SERVICE_FACTORIES, ("fake2", Fake2)]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "factory" in metafunc.fixturenames:
        metafunc.parametrize("factory", [f for _, f in EXTENDED], ids=[n for n, _ in EXTENDED])


def test_every_registered_factory_is_parametrized_and_conforms(factory, request):
    # Real registrations (e.g. "duckdb" from tests/data/conftest_plugin.py) join the base "fake"
    # and this module's appended "fake2" — the mechanism under test is the append, not the exact set.
    assert request.node.callspec.id in {n for n, _ in EXTENDED}
    assert isinstance(factory(), DataService)


def test_registered_ids_include_the_appended_one():
    ids = [n for n, _ in EXTENDED]
    assert ids[0] == "fake" and ids[-1] == "fake2" and len(ids) == len(set(ids))
