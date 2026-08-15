"""SessionStore: conversations on disk, one JSON file per session.

Deliberately dumb persistence — a `SessionState` (with its answers and last reports) round-trips through
pydantic, so a reloaded conversation can answer follow-ups from memory without re-running the engines.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from airport_agent.contracts import SessionState

NEW_CHAT_TITLE = "New chat"
ID_CHARS = 12


class SessionStore:
    """Sessions as `<directory>/<session_id>.json`. Unknown ids raise KeyError, never a blank session."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.json"

    def list(self) -> list[SessionState]:
        """Every stored session, newest first (by file modification time)."""
        paths = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [SessionState.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]

    def new(self, title: str = NEW_CHAT_TITLE) -> SessionState:
        state = SessionState(session_id=uuid.uuid4().hex[:ID_CHARS], title=title)
        self.save(state)
        return state

    def load(self, session_id: str) -> SessionState:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"unknown session {session_id!r}")
        return SessionState.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, state: SessionState) -> None:
        self._path(state.session_id).write_text(state.model_dump_json(indent=1), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"unknown session {session_id!r}")
        path.unlink()

    def rename(self, session_id: str, title: str) -> SessionState:
        state = self.load(session_id)
        state.title = title
        self.save(state)
        return state
