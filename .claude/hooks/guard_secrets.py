"""PreToolUse(Bash): block git commit/push if secret-looking files are staged. Exit 2 = block."""
import json
import re
import subprocess
import sys

SECRET_PATTERNS = [r"(^|/)\.env$", r"(^|/)\.env\.[^e].*$", r"key", r"secret"]  # .env, .env.local; not .env.example
ALLOW = [r"\.env\.example$", r"keybindings", r"monkey"]


def is_git_write(cmd: str) -> bool:
    return bool(re.search(r"\bgit\s+(commit|push)\b", cmd or ""))


def blocked_files(paths):
    out = []
    for p in paths:
        pl = p.lower()
        if any(re.search(a, pl) for a in ALLOW):
            continue
        if any(re.search(s, pl) for s in SECRET_PATTERNS):
            out.append(p)
    return out


def staged_files():
    try:
        r = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=False)
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:  # noqa: BLE001
        return []


def main():
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not is_git_write(cmd):
        return 0
    bad = blocked_files(staged_files())
    if bad:
        print(f"BLOCKED: secret-looking files staged: {bad}. Unstage them (git restore --staged <file>).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
