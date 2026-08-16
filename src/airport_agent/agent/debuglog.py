"""Dev-time debug log: structured JSONL per session, invisible to the user surface.

Rows 65-66 curated the user-facing answer: raw tool errors, pydantic diagnostics, coverage and
truncation chatter no longer reach the screen. That data still matters to whoever develops or debugs
the agent, so every emitter mirrors it here as one JSON object per event in
`<directory>/<session_id>.jsonl`. Files only, no UI panel — the log is gitignored and excluded from
the deliverable zip, like `data/sessions/`.

`NullDebugLog` is the default everywhere a component takes a `debug=` kwarg: tests and one-shot CLI
runs pay nothing unless `build_app` wires a real `DebugLog` in.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path


class DebugLog:
    """Appends one JSON object per `log()` call to `<directory>/<session_id>.jsonl`.

    Each write opens/writes/closes the file (Windows-safe, no held handles) and creates the
    directory on demand. `log()` NEVER raises: any I/O or serialization failure is swallowed after
    one `logging.warning` — a broken debug log must not fail a user turn.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def log(self, session_id: str, turn: int, event: str, **payload: object) -> None:
        try:
            record = {"ts": datetime.now().isoformat(), "turn": turn, "event": event, **payload}
            line = json.dumps(record, default=str, ensure_ascii=False)
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / f"{session_id}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 — deliberate: debug logging must never break a turn
            logging.getLogger(__name__).warning(
                "debug log write failed (session=%s, event=%s)", session_id, event, exc_info=True)


class NullDebugLog:
    """Same `log` signature as `DebugLog`, does nothing — the zero-cost default."""

    def log(self, session_id: str, turn: int, event: str, **payload: object) -> None:
        return
