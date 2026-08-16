"""Build the deliverable zip (design 06) and print a checklist.

Usage: uv run python scripts/make_zip.py [out.zip]
Included: src/, config/, data/snapshot/, data/curated/, tests/, docs/, .claude/,
pyproject.toml, uv.lock, .importlinter, .python-version, conftest.py,
.env (throwaway Gemini key), .env.example, .contracts-frozen, .gitignore.
No README: docs/DESIGN.md is the reviewer's entry point and carries the quickstart
(human decision 2026-08-16, known-limitations row 60) — two entry docs drift apart.
Excluded: .venv, .git, data/raw, data/sessions, data/debug, caches, .superpowers, *.wal.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = ["src", "config", "data/snapshot", "data/curated", "tests", "docs", ".claude", "scripts"]
INCLUDE_FILES = ["pyproject.toml", "uv.lock", ".importlinter", ".python-version", "conftest.py",
                 ".env", ".env.example", ".contracts-frozen", ".gitignore", "CLAUDE.md"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".import_linter_cache", ".superpowers"}
EXCLUDE_SUFFIX = {".wal", ".pyc"}
#: Named files that live under an included directory but must never ship. Both are scribe output that
#: is RE-CREATED on any agent run (`process-log.raw.jsonl` by the Stop hook, `process-log.md` by the
#: process-scribe), so deleting them once is not enough -- without this they would silently reappear
#: in the next zip, since docs/ ships by rglob (known-limitations rows 61-62).
EXCLUDE_NAMES = {"process-log.raw.jsonl", "process-log.md"}


def files() -> list[Path]:
    out: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            print(f"  !! missing directory: {d}")
            continue
        for p in base.rglob("*"):
            if (p.is_file() and not (set(p.parts) & EXCLUDE_PARTS)
                    and p.suffix not in EXCLUDE_SUFFIX and p.name not in EXCLUDE_NAMES):
                out.append(p)
    for f in INCLUDE_FILES:
        p = ROOT / f
        if p.exists():
            out.append(p)
        else:
            print(f"  !! missing file: {f}")
    return out


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "airport-investment-agent.zip"
    fs = files()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in fs:
            z.write(p, p.relative_to(ROOT).as_posix())
    size_mb = dest.stat().st_size / 1e6
    names = {p.relative_to(ROOT).as_posix() for p in fs}
    print(f"wrote {dest} ({size_mb:.1f} MB, {len(fs)} files)")
    print("checklist:")
    checks = {
        ".env with GEMINI_API_KEY present": ".env" in names,
        ".claude/ included (hidden dir)": any(n.startswith(".claude/") for n in names),
        "snapshot present": "data/snapshot/airports.duckdb" in names,
        "DESIGN.md present": "docs/DESIGN.md" in names,
        "no .venv / .git / raw cache / sessions / debug log": not any(
            n.startswith((".venv/", ".git/", "data/raw/", "data/sessions/", "data/debug/"))
            for n in names),
        "no .wal": not any(n.endswith(".wal") for n in names),
    }
    ok = True
    for label, passed in checks.items():
        print(f"  [{'x' if passed else ' '}] {label}")
        ok &= passed
    print("NOTE: extract to a clean dir and run: uv sync --extra dev && uv run pytest -q "
          "&& uv run streamlit run src/airport_agent/ui/streamlit_app.py")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
