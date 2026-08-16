"""Make the repo root importable so `from tests.fakes import …` works.

`pythonpath = ["src"]` in pyproject.toml puts the package on sys.path; the repo root
(which holds the `tests` package) is what is missing.

Phase 2 hook point: extra suite-wide plugins (e.g. the data workstream's
`tests/data/conftest_plugin.py`, which appends a DuckDB factory to
`tests.contracts.conftest.DATA_SERVICE_FACTORIES`) go in the repo-root `conftest.py`'s
`pytest_plugins` list — pytest 8 rejects `pytest_plugins` in this non-root conftest.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _no_request_pacing(monkeypatch):
    """QA task 17: the 3s per-host floor must never be paid by the test suite.

    Tests that exercise `download()` or the live reader go through fakes, so the wait would be pure
    dead time. The pacer's own behaviour is tested directly against a fake clock instead.
    """
    from airport_agent.data.http import INTERVAL_ENV, PACER

    monkeypatch.setenv(INTERVAL_ENV, "0")
    PACER.reset()
