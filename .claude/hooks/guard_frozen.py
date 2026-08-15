"""PreToolUse(Edit|Write|MultiEdit): block edits to frozen contracts/registry unless CONTRACTS_UNFROZEN=1."""
import json
import os
import sys
from pathlib import Path

FROZEN_PREFIXES = ("src/airport_agent/contracts/", "config/metrics.yaml")


def should_block(root: Path, file_path: str) -> bool:
    if os.environ.get("CONTRACTS_UNFROZEN") == "1":
        return False
    if not (Path(root) / ".contracts-frozen").exists():
        return False
    try:
        rel = Path(file_path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return False
    return rel.startswith(FROZEN_PREFIXES)


def main():
    data = json.load(sys.stdin)
    fp = (data.get("tool_input") or {}).get("file_path", "")
    root = Path(data.get("cwd") or os.getcwd())
    if should_block(root, fp):
        print("BLOCKED: contracts/registry are frozen. Escalate a DECISION NEEDED; a human may set CONTRACTS_UNFROZEN=1.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
