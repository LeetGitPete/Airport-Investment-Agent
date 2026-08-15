"""Shared fixtures for the ui test suite."""
from __future__ import annotations

import pytest

from tests.ui.fake_app import FakeApp, make_answer


@pytest.fixture
def fake_app() -> FakeApp:
    return FakeApp()


@pytest.fixture(params=["informational", "rank", "compare", "diagnose"])
def any_answer(request: pytest.FixtureRequest):
    return make_answer(request.param)
