"""Build the deliverable zip (design 06) and print a checklist.

Usage: uv run python scripts/make_zip.py [out.zip]
Included: src/, config/, data/snapshot/, data/curated/, tests/, docs/, .claude/,
pyproject.toml, uv.lock, .importlinter, .python-version, conftest.py, README.md,
.env (throwaway Gemini key), .env.example, .contracts-frozen, .gitignore.
Excluded: .venv, .git, data/raw, data/sessions, caches, .superpowers, *.wal.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = ["src", "config", "data/snapshot", "data/curated", "tests", "docs", ".claude", "scripts"]
INCLUDE_FILES = ["pyproject.toml", "uv.lock", ".importlinter", ".python-version", "conftest.py",
                 "README.md", ".env", ".env.example", ".contracts-frozen", ".gitignore", "CLAUDE.md",
                 "project-description.txt"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".import_linter_cache", ".superpowers"}
EXCLUDE_SUFFIX = {".wal", ".pyc"}


def files() -> list[Path]:
    out: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            print(f"  !! missing directory: {d}")
            continue
        for p in base.rglob("*"):
            if p.is_file() and not (set(p.parts) & EXCLUDE_PARTS) and p.suffix not in EXCLUDE_SUFFIX:
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
        "three standalone docs present": all(f"docs/{n}" in names for n in
                                            ("SCORING-METHODOLOGY.md", "KEY-TRADEOFFS.md", "WHERE-HOW-AI-IS-USED.md")),
        "no .venv / .git / raw cache / sessions": not any(
            n.startswith((".venv/", ".git/", "data/raw/", "data/sessions/")) for n in names),
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
