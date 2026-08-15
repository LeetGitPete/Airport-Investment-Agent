from __future__ import annotations

import pytest

from airport_agent.contracts import load_registry
from tests.agent.fake_analyst import FakeAnalyst
from tests.fakes import FakeDataService


@pytest.fixture
def fake_data():
    return FakeDataService()


@pytest.fixture
def fake_analyst(fake_data):
    return FakeAnalyst(fake_data)


@pytest.fixture(scope="session")
def specs():
    return load_registry()
