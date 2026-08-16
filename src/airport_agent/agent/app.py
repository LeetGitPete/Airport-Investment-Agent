"""Composition root: build the whole agent and hand the UI one object (design 03).

`build_app` is the only place that knows how the layers are wired. The UI imports `App` and nothing else, and
the data/scoring packages are imported lazily so this module still works in a checkout where they are not
implemented yet (the error then says exactly what to pass instead).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from airport_agent.agent.concierge import Concierge
from airport_agent.agent.planner import PRESET_NAMES, SAMPLE_QUESTIONS, Planner
from airport_agent.agent.sessions import SessionStore
from airport_agent.agent.specialists.runner import SpecialistRunnerImpl
from airport_agent.agent.synthesis import Synthesizer
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import (
    Answer,
    DataService,
    DeterministicAnalyst,
    LLMClient,
    Plan,
    SessionState,
    load_registry,
)

MISSING_LAYER = ("data/scoring packages not available in this checkout — pass data_service/analyst "
                 "explicitly")
MISSING_SNAPSHOT = ("data snapshot not found at {path} — run `uv run python -m airport_agent.data refresh` "
                    "to build it, or pass data_service explicitly")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_sessions_dir() -> Path:
    return repo_root() / "data" / "sessions"


def _default_data() -> DataService:
    try:
        from airport_agent.data import DuckDBDataService
        from airport_agent.data.paths import default_snapshot_path
    except ImportError as exc:
        raise RuntimeError(MISSING_LAYER) from exc
    snapshot = default_snapshot_path()
    if not snapshot.exists():
        raise RuntimeError(MISSING_SNAPSHOT.format(path=snapshot))
    return DuckDBDataService()


def _default_analyst(data: DataService) -> DeterministicAnalyst:
    try:
        from airport_agent.scoring import Analyst
    except ImportError as exc:
        raise RuntimeError(MISSING_LAYER) from exc
    return Analyst(data)


class App:
    """Everything the UI needs: one `answer` call, the session store and provider status."""

    def __init__(self, *, data: DataService, analyst: DeterministicAnalyst, llm: LLMClient,
                 registry: ToolRegistry, concierge: Concierge, sessions: SessionStore) -> None:
        self.data = data
        self.analyst = analyst
        self.llm = llm
        self.registry = registry
        self.concierge = concierge
        self.sessions = sessions

    def answer(self, message: str, state: SessionState, *, defaults: dict[str, str] | None = None,
               on_plan: Callable[[Plan], None] | None = None) -> Answer:
        """Answer one turn and persist the session. `LLMError` propagates and nothing is saved."""
        answer = self.concierge.answer(message, state, defaults=defaults, on_plan=on_plan)
        self.sessions.save(state)
        return answer

    def provider_status(self) -> list[dict[str, str]]:
        status = getattr(self.llm, "status", None)
        if callable(status):
            return status()
        return [{"name": getattr(self.llm, "provider_name", "llm"), "model": "?", "status": "unknown",
                 "detail": ""}]

    def sample_questions(self) -> list[str]:
        return list(SAMPLE_QUESTIONS)


def build_app(data_service: DataService | None = None, analyst: DeterministicAnalyst | None = None,
              llm: LLMClient | None = None, sessions_dir: Path | None = None) -> App:
    """Wire the agent. Defaults are imported lazily so a partial checkout fails with a clear message."""
    data = data_service or _default_data()
    deterministic = analyst or _default_analyst(data)
    client: Any = llm
    if client is None:
        from airport_agent.llm import LiteLLMClient
        client = LiteLLMClient()
    specs = load_registry()
    registry = build_registry(data, deterministic)
    planner = Planner(client, registry, specs, list(PRESET_NAMES))
    concierge = Concierge(llm=client, registry=registry, analyst=deterministic,
                          specialists=SpecialistRunnerImpl(client, registry, specs), planner=planner,
                          synthesizer=Synthesizer(client, specs))
    return App(data=data, analyst=deterministic, llm=client, registry=registry, concierge=concierge,
               sessions=SessionStore(sessions_dir or default_sessions_dir()))
