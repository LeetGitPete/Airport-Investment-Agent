from __future__ import annotations

from airport_agent.contracts import DeterministicAnalyst
from airport_agent.scoring import Analyst
from tests.fakes import FakeDataService


def test_analyst_satisfies_protocol():
    assert isinstance(Analyst(FakeDataService()), DeterministicAnalyst)
