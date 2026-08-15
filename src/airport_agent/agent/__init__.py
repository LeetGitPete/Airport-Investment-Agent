"""Agent: composition root. Orchestrates the data, scoring and llm layers for the UI.

The UI imports only `App`/`build_app` (plus `SessionStore` for the sidebar); everything else here is the
machinery behind one `App.answer(...)` call: Planner -> tools / Deterministic Analyst / LLM specialists ->
Synthesizer.
"""
from __future__ import annotations

from airport_agent.agent.app import App, build_app, default_sessions_dir
from airport_agent.agent.concierge import Concierge
from airport_agent.agent.planner import PLAN_SCHEMA, SAMPLE_QUESTIONS, PlanFilters, Planner
from airport_agent.agent.sessions import SessionStore
from airport_agent.agent.specialists import SPECIALIST_SCHEMA, SpecialistRunnerImpl, load_specialist
from airport_agent.agent.synthesis import SYNTHESIS_SCHEMA, Synthesizer
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.agent.tools.registry import ToolRegistry

__all__ = [
    "PLAN_SCHEMA",
    "SAMPLE_QUESTIONS",
    "SPECIALIST_SCHEMA",
    "SYNTHESIS_SCHEMA",
    "App",
    "Concierge",
    "PlanFilters",
    "Planner",
    "SessionStore",
    "SpecialistRunnerImpl",
    "Synthesizer",
    "ToolRegistry",
    "build_app",
    "build_registry",
    "default_sessions_dir",
    "load_specialist",
]
