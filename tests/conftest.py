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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
