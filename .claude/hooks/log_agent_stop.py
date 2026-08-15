"""Stop / SubagentStop: append {ts, agent, summary} to docs/process-log.raw.jsonl (scribe feed)."""
import datetime as dt
import json
import sys
from pathlib import Path


def append_event(path: Path, data: dict, now: str | None = None) -> None:
    ts = now or dt.datetime.now().isoformat(timespec="seconds")
    agent = data.get("agent_type") or ("main" if data.get("hook_event_name") == "Stop" else "subagent")
    msg = (data.get("last_assistant_message") or "").strip().replace("\r", "")
    summary = msg[:400]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "agent": agent, "event": data.get("hook_event_name"), "summary": summary}) + "\n")


def main():
    data = json.load(sys.stdin)
    root = Path(data.get("cwd") or ".")
    append_event(root / "docs" / "process-log.raw.jsonl", data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
