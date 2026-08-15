"""Obtain the `App` object used by the CLI and Streamlit app.

Real usage: lazily imports `airport_agent.agent.build_app` (never at module import time, since `ui/`
must not depend on `agent/` being importable at collection time — the agent workstream may be built
in a parallel worktree). Tests inject a fake App via the `AIRPORT_AGENT_APP_FACTORY` env var
(format `"module:callable"`), e.g. `"tests.ui.fake_app:make_app"`.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

ENV_VAR = "AIRPORT_AGENT_APP_FACTORY"


def get_app() -> Any:
    spec = os.environ.get(ENV_VAR)
    if spec:
        module_name, _, attr = spec.partition(":")
        module = importlib.import_module(module_name)
        factory = getattr(module, attr)
        return factory()
    from airport_agent.agent import build_app

    return build_app()
