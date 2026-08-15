"""PostToolUse(Edit|Write): run ruff on the edited python file and import-linter; print findings (never blocks)."""
import json
import subprocess
import sys


def wants_lint(file_path: str) -> bool:
    p = (file_path or "").replace("\\", "/")
    return p.endswith(".py") and ("/src/" in p or p.startswith("src/") or "/tests/" in p or p.startswith("tests/"))


def main():
    data = json.load(sys.stdin)
    fp = (data.get("tool_input") or {}).get("file_path", "")
    if not wants_lint(fp):
        return 0
    for cmd in (["uv", "run", "ruff", "check", fp], ["uv", "run", "lint-imports"]):
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            print(f"[lint] {' '.join(cmd)}:\n{r.stdout}{r.stderr}".strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
