"""LLM specialists: config artifacts (config/specialists/*.md) + the bounded tool-loop runner."""
from __future__ import annotations

from airport_agent.agent.specialists.loader import (
    SpecialistConfig,
    default_specialists_dir,
    load_specialist,
)
from airport_agent.agent.specialists.runner import MAX_TOOL_RESULT_CHARS, SpecialistRunnerImpl
from airport_agent.agent.specialists.schema import SPECIALIST_SCHEMA, schema_doc

__all__ = [
    "MAX_TOOL_RESULT_CHARS",
    "SPECIALIST_SCHEMA",
    "SpecialistConfig",
    "SpecialistRunnerImpl",
    "default_specialists_dir",
    "load_specialist",
    "schema_doc",
]
