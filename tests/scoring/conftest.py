from __future__ import annotations

import pytest

from airport_agent.contracts import load_registry, registry_by_id
from tests.fakes import FakeDataService


@pytest.fixture(scope="session")
def specs():
    return load_registry()


@pytest.fixture(scope="session")
def by_id(specs):
    return registry_by_id(specs)


@pytest.fixture
def fake():
    return FakeDataService()
