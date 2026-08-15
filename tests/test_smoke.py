import importlib

import pytest

PACKAGES = ["airport_agent", "airport_agent.contracts", "airport_agent.data", "airport_agent.scoring",
            "airport_agent.llm", "airport_agent.agent", "airport_agent.ui"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    assert importlib.import_module(name) is not None
