"""The DataService contract suite must pick up implementations registered after import time.

This mirrors the `pytest_generate_tests` hook in conftest.py with one extra factory appended, proving
the mechanism a Phase 2 plugin will use (append to DATA_SERVICE_FACTORIES, then get parametrized).
It cannot append to the real list here: conftest's hook already ran for this module's collection.
"""
from __future__ import annotations

import pytest

from airport_agent.contracts import DataService
from tests.contracts.conftest import DATA_SERVICE_FACTORIES
from tests.fakes import FakeDataService


class Fake2(FakeDataService):
    """Stand-in for a second implementation (Phase 2: DuckDB-backed)."""


EXTENDED = [*DATA_SERVICE_FACTORIES, ("fake2", Fake2)]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "factory" in metafunc.fixturenames:
        metafunc.parametrize("factory", [f for _, f in EXTENDED], ids=[n for n, _ in EXTENDED])


def test_every_registered_factory_is_parametrized_and_conforms(factory, request):
    assert request.node.callspec.id in {"fake", "fake2"}
    assert isinstance(factory(), DataService)


def test_registered_ids_include_the_appended_one():
    assert [n for n, _ in EXTENDED] == ["fake", "fake2"]
