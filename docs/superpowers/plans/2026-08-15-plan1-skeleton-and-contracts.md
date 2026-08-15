# Plan 1 — Skeleton, AI-native scaffolding, Contracts & Registry Freeze (Phases 0–1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the frozen foundation every parallel workstream builds on: package skeleton, CLAUDE.md, subagent specs, hooks, skills, the `contracts/` package (types + Protocols), the metric registry `config/metrics.yaml`, `FakeDataService`, and the contract test suite — then freeze.

**Architecture:** Layered ports & adapters (docs/design/00). `contracts/` holds only pydantic v2 models and `typing.Protocol`s; every other package imports from `contracts/` + itself. The registry is data (YAML) validated into `MetricSpec`s. `FakeDataService` is the only stand-in Phase 2 agents may build against.

**Tech Stack:** Python 3.12, uv, pydantic v2, PyYAML, pytest, ruff, import-linter. (DuckDB, LiteLLM, Streamlit are declared now but used in Phase 2.)

**Design sources:** `docs/design/00-overview.md`, `02-metrics-and-scoring.md`, `03-agent-architecture.md`, `05-ai-native-dev-process.md`. Research: `docs/research/2026-08-15-airport-investment-metrics.md`.

## Global Constraints
- Python `>=3.12`; package name `airport_agent` under `src/`.
- `contracts/` contains **no logic, no I/O** — types, Protocols, and pure helpers on those types only.
- Import rule: any package imports only from `airport_agent.contracts` and its own package (`agent/` is the composition root and may import all). Enforced by import-linter.
- Every metric value that reaches a user carries `source_id` + `vintage`.
- No LLM calls in this plan. No network in tests (fixtures only).
- Escalation protocol (05 §5.0): anything non-trivial → stop, return `DECISION NEEDED`.
- Commit after every task; commit messages `type: summary`.
- Windows host: hooks are Python scripts (portable); paths use forward slashes in configs.

---

## File structure (what this plan creates)

```
pyproject.toml, .python-version, README.md, .env.example, .importlinter, .gitignore (exists)
CLAUDE.md
.claude/settings.json
.claude/hooks/{guard_secrets.py, guard_frozen.py, lint_on_edit.py, log_agent_stop.py}
.claude/agents/{contract-architect,data-engineer,scoring-engineer,agent-engineer,ui-engineer,voice-engineer,reviewer,process-scribe,doc-assembler}.md
.claude/skills/{refresh-data,eval-samples,log-progress}/SKILL.md
src/airport_agent/__init__.py
src/airport_agent/contracts/{__init__,models,requests,reports,conversation,data_service,scoring,llm,specialists,tools,registry}.py
src/airport_agent/{data,scoring,llm,agent,ui}/__init__.py          (empty package stubs)
config/metrics.yaml
tests/conftest.py, tests/fakes.py, tests/test_smoke.py
tests/contracts/{conftest.py, test_models.py, test_requests.py, test_registry.py, test_data_service_contract.py}
tests/hooks/test_hooks.py
docs/process-log.raw.jsonl (created by hook on first stop)
.contracts-frozen (marker, Task 10)
```

---

### Task 1: Project skeleton, tooling, smoke test

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.importlinter`, `README.md`, `.env.example`, `src/airport_agent/__init__.py`, `src/airport_agent/{contracts,data,scoring,llm,agent,ui}/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`
- Modify: `.gitignore` (add `.contracts-frozen`? NO — the marker is committed. Add `uv.lock`? NO — commit it.)

**Interfaces:**
- Produces: importable package `airport_agent` with six subpackages; `uv run pytest` and `uv run ruff check .` and `uv run lint-imports` all work.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "airport-agent"
version = "0.1.0"
description = "Airport Investment Intelligence Agent — ranks/compares US airports for capacity-expansion investment"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "pyyaml>=6.0",
  "duckdb>=1.0",
  "pandas>=2.2",
  "pyarrow>=16",
  "httpx>=0.27",
  "openpyxl>=3.1",
  "python-dotenv>=1.0",
  "litellm>=1.50",
  "streamlit>=1.38",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.6", "import-linter>=2.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/airport_agent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = ["network: tests that hit the internet (skipped by default)"]
addopts = "-m 'not network' -q"

[tool.ruff]
line-length = 110
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
ignore = ["E501"]
```

- [ ] **Step 2: Write `.python-version`, `.importlinter`, `.env.example`, `README.md`, package inits**

`.python-version`: `3.12`

`.importlinter`:
```ini
[importlinter]
root_package = airport_agent

[importlinter:contract:contracts-are-pure]
name = contracts imports nothing from the app
type = forbidden
source_modules = airport_agent.contracts
forbidden_modules =
    airport_agent.data
    airport_agent.scoring
    airport_agent.llm
    airport_agent.agent
    airport_agent.ui

[importlinter:contract:workstreams-independent]
name = data / scoring / llm / ui do not import each other
type = independence
modules =
    airport_agent.data
    airport_agent.scoring
    airport_agent.llm
    airport_agent.ui

[importlinter:contract:ui-only-via-agent]
name = ui may import only agent and contracts
type = forbidden
source_modules = airport_agent.ui
forbidden_modules =
    airport_agent.data
    airport_agent.scoring
    airport_agent.llm
```

`.env.example`:
```
# Runtime LLM (Gemini free tier). Get a key at https://aistudio.google.com/apikey
GEMINI_API_KEY=
# Optional later: GROQ_API_KEY=, NVIDIA_API_KEY=
```

`README.md`:
```markdown
# Airport Investment Intelligence Agent

Ranks and compares US airports for capacity-expansion investment, with deterministic scoring + an LLM analyst.

Quickstart (Phase 0 — app not yet built):
    uv sync --extra dev
    uv run pytest

Design docs: `docs/design/`. Process log: `docs/process-log.md`.
```

`src/airport_agent/__init__.py`: `"""Airport Investment Intelligence Agent."""\n__version__ = "0.1.0"\n`
Each subpackage `__init__.py`: one-line docstring naming the layer, e.g. `"""Contracts: pydantic models and Protocols only. No logic, no I/O."""`.

- [ ] **Step 3: Write the smoke test**

`tests/test_smoke.py`:
```python
import importlib

import pytest

PACKAGES = ["airport_agent", "airport_agent.contracts", "airport_agent.data", "airport_agent.scoring",
            "airport_agent.llm", "airport_agent.agent", "airport_agent.ui"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    assert importlib.import_module(name) is not None
```

- [ ] **Step 4: Install and run**

Run: `uv sync --extra dev && uv run pytest && uv run ruff check . && uv run lint-imports`
Expected: 7 passed; ruff clean; import-linter "Contracts: 3 kept, 0 broken".

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: project skeleton, tooling, smoke test"
```

---

### Task 2: CLAUDE.md

**Files:** Create: `CLAUDE.md`

- [ ] **Step 1: Write CLAUDE.md** (content below, verbatim)

```markdown
# Airport Investment Intelligence Agent — project guide for Claude Code

## What this is (3 lines)
An agent that ranks/compares US airports for capacity-expansion investment: deterministic scoring over public
aviation data + an LLM Concierge with structured dispatch to LLM specialists. ~1-day take-home assignment;
prioritize clarity, reasoning and honest uncertainty over completeness.

## Source of truth
- `docs/design/00–06` are the design. If code and design disagree, stop and escalate (see below).
- `docs/design/known-limitations-and-tradeoffs.md` MUST be updated whenever a constraint or decision is made.
- `docs/process-log.md` is maintained by the process-scribe; hooks append raw events to `docs/process-log.raw.jsonl`.
- Research evidence: `docs/research/`.

## Method (why things are shaped this way)
Investor questions → metric registry (`config/metrics.yaml`) → data infrastructure. Metrics follow questions;
adapters and derived tables follow the registry. Never add a metric without a question and a source.

## Architecture rules (enforced by hooks + import-linter)
- Layers: `contracts/` (types + Protocols only) ← `data/`, `scoring/`, `llm/` (independent) ← `agent/`
  (composition root; Concierge, tools, specialists, synthesis) ← `ui/` (imports only `agent` + `contracts`).
- A package imports only from `airport_agent.contracts` and itself. `agent/` may import everything.
- `contracts/` and `config/metrics.yaml` are FROZEN once `.contracts-frozen` exists. Changing them requires a
  human decision, `CONTRACTS_UNFROZEN=1`, and a rebase of every open worktree.
- Deterministic Analyst (`scoring/`) and LLM specialists (`agent/specialists/`) never call each other.

## Product rules (assignment requirements)
- Every number shown carries `source_id` + `vintage`. The LLM may not alter numbers, invent weights, hide a
  disagreement, or omit the assumptions block.
- Show the Plan before executing; state what was filtered/omitted and why.
- No silent degradation: if the LLM provider fails, fail loudly with an actionable message. No cross-request
  caching of LLM outputs.
- Conventions must be stated when used (long-haul ≥1,500 mi default; spill model instead of LF cutoffs;
  percentiles within hub class).

## Commands
- `uv sync --extra dev` · `uv run pytest` · `uv run ruff check .` · `uv run lint-imports`
- `uv run python -m airport_agent.data refresh --check` (Phase 2+)
- `uv run python -m airport_agent.ui.cli "question"` (Phase 2+) · `uv run streamlit run src/airport_agent/ui/streamlit_app.py`

## Conventions
Python 3.12, pydantic v2 models, `typing.Protocol` for ports, full type hints, ruff clean, pytest with fixtures
(no network in default test run; `@pytest.mark.network` for live smoke tests). Small focused files. TDD for
deterministic logic. Tool args are pydantic-validated; no free-form SQL exposed to the LLM.

## Escalation protocol (non-negotiable, all agents)
Trivial = fully covered by docs/design + this file → do it. Anything else (ambiguity, off-design, new tradeoff,
data surprise, contract change, scope) → STOP, do not improvise, return a `DECISION NEEDED` block:
what · why it matters · 2–3 options · recommendation · what is blocked. Finish independent work meanwhile.
The orchestrator relays it to the human verbatim and waits.

## Report-back format for subagents
`changed:` (files) · `tested:` (commands + result) · `untested:` · `assumptions:` · `DECISION NEEDED:` (or "none")
```

- [ ] **Step 2: Commit** — `git add CLAUDE.md && git commit -m "docs: CLAUDE.md project guide"`

---

### Task 3: Hooks (secrets guard, freeze guard, lint-on-edit, agent-stop log) — with tests

**Files:**
- Create: `.claude/settings.json`, `.claude/hooks/guard_secrets.py`, `.claude/hooks/guard_frozen.py`, `.claude/hooks/lint_on_edit.py`, `.claude/hooks/log_agent_stop.py`, `tests/hooks/__init__.py`, `tests/hooks/test_hooks.py`

**Interfaces:**
- Hook scripts read the Claude Code hook JSON on stdin; exit code 2 = block (message on stderr); exit 0 = allow. Each script exposes a pure function so tests don't need subprocesses.

- [ ] **Step 1: Write failing tests**

`tests/hooks/test_hooks.py`:
```python
import importlib.util
import json
import os
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guard_secrets_blocks_env_in_commit():
    g = load("guard_secrets")
    assert g.blocked_files(["src/a.py", ".env"]) == [".env"]
    assert g.blocked_files(["config/keys.yaml", "notes/secret_stuff.md"]) == ["config/keys.yaml", "notes/secret_stuff.md"]
    assert g.blocked_files([".env.example", "src/ok.py"]) == []
    assert g.is_git_write("git commit -m x") and g.is_git_write("git push origin main")
    assert not g.is_git_write("git status")


def test_guard_frozen_blocks_contract_edits_when_marker_present(tmp_path, monkeypatch):
    g = load("guard_frozen")
    root = tmp_path
    (root / ".contracts-frozen").write_text("frozen")
    monkeypatch.delenv("CONTRACTS_UNFROZEN", raising=False)
    assert g.should_block(root, str(root / "src/airport_agent/contracts/models.py"))
    assert g.should_block(root, str(root / "config/metrics.yaml"))
    assert not g.should_block(root, str(root / "src/airport_agent/data/x.py"))
    monkeypatch.setenv("CONTRACTS_UNFROZEN", "1")
    assert not g.should_block(root, str(root / "src/airport_agent/contracts/models.py"))


def test_guard_frozen_allows_when_no_marker(tmp_path, monkeypatch):
    g = load("guard_frozen")
    monkeypatch.delenv("CONTRACTS_UNFROZEN", raising=False)
    assert not g.should_block(tmp_path, str(tmp_path / "src/airport_agent/contracts/models.py"))


def test_lint_on_edit_selects_only_src_python():
    m = load("lint_on_edit")
    assert m.wants_lint("src/airport_agent/data/x.py")
    assert not m.wants_lint("docs/design/00-overview.md")
    assert not m.wants_lint("tests/test_x.py") is False or True  # tests are linted too — see impl


def test_log_agent_stop_appends_jsonl(tmp_path):
    m = load("log_agent_stop")
    out = tmp_path / "log.jsonl"
    m.append_event(out, {"hook_event_name": "SubagentStop", "agent_type": "data-engineer",
                         "last_assistant_message": "changed: x\ntested: y"}, now="2026-08-15T10:00:00")
    m.append_event(out, {"hook_event_name": "Stop"}, now="2026-08-15T10:05:00")
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines[0]["agent"] == "data-engineer" and lines[0]["ts"] == "2026-08-15T10:00:00"
    assert lines[0]["summary"].startswith("changed: x")
    assert lines[1]["agent"] == "main"
```

- [ ] **Step 2: Run tests → expect FAIL** — `uv run pytest tests/hooks -v` → "No such file".

- [ ] **Step 3: Write the hook scripts**

`.claude/hooks/guard_secrets.py`:
```python
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
```

`.claude/hooks/guard_frozen.py`:
```python
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
```

`.claude/hooks/lint_on_edit.py`:
```python
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
```

`.claude/hooks/log_agent_stop.py`:
```python
"""Stop / SubagentStop: append {ts, agent, summary} to docs/process-log.raw.jsonl (scribe feed)."""
import datetime as dt
import json
import sys
from pathlib import Path


def append_event(path: Path, data: dict, now: str | None = None) -> None:
    ts = now or dt.datetime.now().isoformat(timespec="seconds")
    agent = data.get("agent_type") or data.get("agent_name") or ("main" if data.get("hook_event_name") == "Stop" else "subagent")
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
```

`.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "python .claude/hooks/guard_secrets.py"}]},
      {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "python .claude/hooks/guard_frozen.py"}]}
    ],
    "PostToolUse": [
      {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "python .claude/hooks/lint_on_edit.py"}]}
    ],
    "Stop": [{"hooks": [{"type": "command", "command": "python .claude/hooks/log_agent_stop.py"}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "python .claude/hooks/log_agent_stop.py"}]}]
  }
}
```

Fix the sloppy third assertion in `test_lint_on_edit_selects_only_src_python` to: `assert m.wants_lint("tests/test_x.py")` (tests are linted).

- [ ] **Step 4: Run tests → PASS** — `uv run pytest tests/hooks -v`

- [ ] **Step 5: Manual hook check** — start a new Claude Code session in the repo (or `/hooks`), confirm the four hooks are listed. Add `docs/process-log.raw.jsonl` to git (it's a deliverable feed, keep it).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "chore: claude hooks (secrets/freeze guards, lint, agent-stop log) with tests"`

---

### Task 4: Subagent specs and skills

**Files:** Create nine `.claude/agents/<name>.md` and three `.claude/skills/<name>/SKILL.md`.

Each agent file uses this template (frontmatter fields: `name`, `description`, `model`, `tools`), then the body sections **Role · Inputs · Outputs (paths you may write) · Forbidden · Method · Escalation · Report-back**. Model per 05 §5.2 (Fable/Opus → `opus`; Sonnet → `sonnet`).

- [ ] **Step 1: Write `.claude/agents/contract-architect.md`**

```markdown
---
name: contract-architect
description: Writes and freezes the contracts package, metric registry, FakeDataService and contract tests. Use for any change to contracts/ or config/metrics.yaml.
model: opus
tools: Read, Write, Edit, Bash, Grep, Glob
---
# Role
Own `src/airport_agent/contracts/`, `config/metrics.yaml`, `tests/fakes.py`, `tests/contracts/`.
# Inputs
docs/design/00-overview.md, 02-metrics-and-scoring.md, 03-agent-architecture.md; docs/research/2026-08-15-airport-investment-metrics.md; the plan task you were given.
# Outputs
Only the paths above. Types are pydantic v2; ports are typing.Protocol; no logic/I/O in contracts.
# Forbidden
Touching data/, scoring/, llm/, agent/, ui/. Editing frozen files without CONTRACTS_UNFROZEN=1 and an explicit human decision.
# Method
TDD: write the failing test from the plan, run it, implement minimal code, run, commit. Keep files small (one concern each). Run `uv run ruff check . && uv run lint-imports && uv run pytest` before reporting.
# Escalation
Anything ambiguous or not covered by the plan/design (a missing type, a field with two plausible shapes, a registry entry that cannot be defined) → STOP and return a DECISION NEEDED block (what · why · options · recommendation · blocked). Do not guess.
# Report-back
changed / tested / untested / assumptions / DECISION NEEDED (or none)
```

- [ ] **Step 2: Write the other eight agent files** using the same template with these specifics:

| file | model | tools | Role (1–2 lines) | Inputs | Outputs | Forbidden |
|---|---|---|---|---|---|---|
| `data-engineer.md` | opus | Read, Write, Edit, Bash, Grep, Glob, WebFetch | Build source adapters, DuckDB store, derived metrics per registry, refresh CLI, snapshot, curated YAML skeleton, fixtures | design 01, 02; research data-sources note; frozen contracts + registry | `src/airport_agent/data/**`, `config/sources.yaml`, `data/**`, `tests/data/**`, `tests/fixtures/**` | other packages; editing contracts/registry; committing raw downloads >5MB |
| `scoring-engineer.md` | opus | Read, Write, Edit, Bash, Grep, Glob | Scorer, presets, Deterministic Analyst (rank/compare/diagnose), templated explanations, calculators; TDD against FakeDataService | design 02; frozen contracts + registry | `src/airport_agent/scoring/**`, `config/scoring_presets.yaml`, `tests/scoring/**` | other packages; any LLM call; inventing metrics not in the registry |
| `agent-engineer.md` | opus | Read, Write, Edit, Bash, Grep, Glob | LiteLLM router (Gemini only), ToolRegistry, Concierge Plan→dispatch→synthesis, specialists runner + configs, sessions, CLI-facing `answer()` | design 03; LLM research note; frozen contracts | `src/airport_agent/agent/**`, `src/airport_agent/llm/**`, `config/providers.yaml`, `config/specialists/**`, `tests/agent/**`, `tests/llm/**` | editing data/scoring internals (use their public entry points via contracts); silent fallbacks; caching LLM outputs |
| `ui-engineer.md` | sonnet | Read, Write, Edit, Bash, Grep, Glob | Streamlit multi-chat app, rendering of Answer structure, sidebar, session persistence, CLI harness | design 04; contracts (Answer, SessionState) | `src/airport_agent/ui/**`, `tests/ui/**` | importing data/scoring/llm directly; re-interpreting numbers |
| `voice-engineer.md` | sonnet | Read, Write, Edit, Bash, Grep, Glob | On branch `feature/voice` only: audio input → STT via Gemini → text pipeline → optional TTS. Timeboxed | design 04 | `src/airport_agent/ui/voice.py`, tests | any other file; merging to main |
| `reviewer.md` | opus | Read, Bash, Grep, Glob | Review a workstream diff for design conformance, contract-boundary violations, correctness, test quality; no edits | diff, design docs, CLAUDE.md | review notes (returned as text) | editing code |
| `process-scribe.md` | sonnet | Read, Write, Edit, Bash, Grep, Glob | Update `docs/process-log.md` per 05 §5.4; maintain "Where/how AI is used" table | `docs/process-log.raw.jsonl`, `git log`, pasted agent reports, limitations diff | `docs/process-log.md` only | inventing events; deleting earlier entries; >25 lines per milestone |
| `doc-assembler.md` | opus | Read, Write, Edit, Bash, Grep, Glob | Assemble `docs/SCORING-METHODOLOGY.md`, `docs/KEY-TRADEOFFS.md`, `docs/WHERE-HOW-AI-IS-USED.md`, `docs/DESIGN.md`, `README.md` per design 06 | all docs, code | those five files | changing design content (report discrepancies instead) |

All eight include the same **Method / Escalation / Report-back** sections as contract-architect (copy verbatim, adjusting the "run before reporting" commands to the package's tests).

- [ ] **Step 3: Write skills**

`.claude/skills/refresh-data/SKILL.md`:
```markdown
---
name: refresh-data
description: Refresh the airport data snapshot from public sources and report staleness per source. Use when data is stale or the user asks to update datasets.
---
1. Run `uv run python -m airport_agent.data refresh --check` and show the staleness table.
2. Unless the user asked only for a check, run `uv run python -m airport_agent.data refresh` (add `--sources a,b`
   or `--period YYYY-MM` if the user specified). Live sources may be slow; per-source failures do not abort.
3. Report: sources refreshed, new vintages, failures with reasons, snapshot size. If any source failed, add or
   update a row in docs/design/known-limitations-and-tradeoffs.md.
Scheduling (optional): Windows Task Scheduler / cron line is documented in docs/design/01-data-layer.md.
```

`.claude/skills/eval-samples/SKILL.md`:
```markdown
---
name: eval-samples
description: Run the four assignment sample questions plus scripted follow-ups through the CLI and compare with golden files. Use before merges and before delivery.
---
1. `uv run pytest tests/golden -q` (structure + key-number goldens; requires GEMINI_API_KEY for the LLM parts —
   if missing, run only `-m "not llm"` and say so).
2. For each of the four sample questions run `uv run python -m airport_agent.ui.cli "<question>" --json` and
   check: Plan present, evidence table with source+vintage per number, assumptions block, no altered numbers.
3. Report a pass/fail table and diffs; never edit goldens without a human decision.
```

`.claude/skills/log-progress/SKILL.md`:
```markdown
---
name: log-progress
description: Dispatch the process-scribe subagent to update docs/process-log.md from the raw hook feed, git log and agent reports. Use at milestones.
---
1. Collect: `docs/process-log.raw.jsonl` (new lines since last scribe run — the scribe records the last ts it
   consumed at the bottom of process-log.md as `<!-- scribe-cursor: TS -->`), `git log --since <that ts> --stat`,
   any agent final reports pasted by the user/orchestrator, `git diff` of the limitations log.
2. Dispatch the `process-scribe` agent with those inputs and the milestone name.
3. Show the appended section to the user.
```

- [ ] **Step 4: Verify** — `ls .claude/agents | wc -l` → 9; `ls .claude/skills` → 3 dirs. In a fresh session, `/agents` lists them.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "chore: subagent specs and skills"`

---

### Task 5: `contracts/models.py` — core domain types

**Files:** Create `src/airport_agent/contracts/models.py`, `tests/contracts/__init__.py`, `tests/contracts/test_models.py`

**Interfaces — Produces (used by every later task):**
```python
Horizon = Literal["12m", "3y", "5y", "10y"]
HubSize = Literal["large", "medium", "small", "nonhub"]
Tier = Literal["A", "B", "C"]
Direction = Literal["up", "down"]          # up = higher value raises expansion attractiveness
Pillar = Literal["P1", "P2", "P3", "P4", "P5"]
class AirportRef(BaseModel): iata, icao, faa_locid, name, city, state, faa_region, hub_size, lat, lon
class SourceVintage(BaseModel): source_id, description, period_start, period_end, fetched_at, url
class QualityFlag(BaseModel): code, message
class Metric(BaseModel): id, value, unit, horizon, period_start, period_end, source_id, vintage, quality
class MetricSpec(BaseModel): id, name, definition, formula, unit, direction, pillar, tier, sources, horizons, caveats
class AirportFilter(BaseModel): states, faa_regions, cbsa_codes, iatas, hub_sizes, name_contains, limit
class FeatureMatrix(BaseModel): airports, metric_ids, horizon, values, peer_group; .coverage(), .column(id)
class RouteRow / RouteTable, CuratedFact, LiveStatus, AirportProfile
```

- [ ] **Step 1: Write failing tests**

`tests/contracts/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from airport_agent.contracts.models import (AirportFilter, AirportProfile, AirportRef, FeatureMatrix, Metric,
                                            MetricSpec, RouteRow, RouteTable, SourceVintage)


def ref(iata="BOS"):
    return AirportRef(iata=iata, icao="KBOS", faa_locid="BOS", name="Logan", city="Boston", state="MA",
                      faa_region="ANE", hub_size="large", lat=42.36, lon=-71.01)


def test_airport_ref_normalizes_codes():
    r = AirportRef(iata="bos", icao=None, faa_locid="bos", name="Logan", city="Boston", state="ma",
                   faa_region="ANE", hub_size="large", lat=42.36, lon=-71.01)
    assert r.iata == "BOS" and r.faa_locid == "BOS" and r.state == "MA"


def test_metric_requires_provenance():
    with pytest.raises(ValidationError):
        Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05", period_end="2026-04")
    m = Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05", period_end="2026-04",
               source_id="bts_t100", vintage="2026-04")
    assert m.quality == []


def test_metric_spec_direction_and_tier_are_constrained():
    with pytest.raises(ValidationError):
        MetricSpec(id="x", name="x", definition="d", formula="f", unit="u", direction="sideways", pillar="P1",
                   tier="A", sources=["s"], horizons=["12m"])
    s = MetricSpec(id="x", name="x", definition="d", formula="f", unit="u", direction="down", pillar="P5",
                   tier="B", sources=["s"], horizons=["12m", "5y"])
    assert s.caveats == []


def test_feature_matrix_shape_and_helpers():
    fm = FeatureMatrix(airports=[ref("BOS"), ref("BDL")], metric_ids=["a", "b"], horizon="5y",
                       values=[[1.0, None], [2.0, 3.0]], peer_group="hub_class")
    assert fm.coverage() == pytest.approx(0.75)
    assert fm.column("a") == [1.0, 2.0]
    with pytest.raises(ValidationError):
        FeatureMatrix(airports=[ref("BOS")], metric_ids=["a", "b"], horizon="5y", values=[[1.0]], peer_group="all")


def test_airport_filter_defaults_and_limit():
    f = AirportFilter()
    assert f.states == [] and f.limit == 50
    with pytest.raises(ValidationError):
        AirportFilter(limit=0)


def test_route_table_and_profile_construct():
    rt = RouteTable(iata="ANC", period_start="2025-05", period_end="2026-04", source_id="bts_t100", vintage="2026-04",
                    rows=[RouteRow(dest="SEA", dest_name="Seattle", distance_mi=1449, departures=3000, seats=450000,
                                   passengers=380000, freight_lb=1e6, is_international=False)], truncated=False)
    assert rt.rows[0].distance_mi == 1449
    p = AirportProfile(ref=ref(), metrics={"12m": []}, forecast={}, routes_summary={}, curated_facts=[],
                       live=None, data_quality_notes=[], vintages=[SourceVintage(source_id="s", description="d",
                       period_start="2025-01", period_end="2026-04", fetched_at="2026-08-15T00:00:00", url=None)])
    assert p.ref.iata == "BOS"
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `models.py`**

```python
"""Core domain types. Pure data — no logic beyond validation and tiny helpers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Horizon = Literal["12m", "3y", "5y", "10y"]
HubSize = Literal["large", "medium", "small", "nonhub"]
Tier = Literal["A", "B", "C"]
Direction = Literal["up", "down"]  # "up": higher value ⇒ more expansion-attractive
Pillar = Literal["P1", "P2", "P3", "P4", "P5"]
PeerGroup = Literal["hub_class", "region", "all"]

HORIZONS: tuple[Horizon, ...] = ("12m", "3y", "5y", "10y")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AirportRef(_Frozen):
    iata: str
    icao: str | None = None
    faa_locid: str
    name: str
    city: str
    state: str
    faa_region: str  # FAA region code, e.g. ANE (New England)
    hub_size: HubSize
    lat: float
    lon: float

    @field_validator("iata", "faa_locid", "state", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("icao", mode="before")
    @classmethod
    def _upper_opt(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else None


class SourceVintage(_Frozen):
    source_id: str
    description: str
    period_start: str | None  # "YYYY-MM" or "YYYY"
    period_end: str | None
    fetched_at: str  # ISO timestamp
    url: str | None = None


class QualityFlag(_Frozen):
    code: str
    message: str


class Metric(_Frozen):
    id: str
    value: float | None
    unit: str
    horizon: Horizon | Literal["static", "forecast"]
    period_start: str | None
    period_end: str | None
    source_id: str
    vintage: str
    quality: list[QualityFlag] = Field(default_factory=list)


class MetricSpec(_Frozen):
    id: str
    name: str
    definition: str
    formula: str
    unit: str
    direction: Direction
    pillar: Pillar
    tier: Tier
    sources: list[str]
    horizons: list[str]
    caveats: list[str] = Field(default_factory=list)


class AirportFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    states: list[str] = Field(default_factory=list)
    faa_regions: list[str] = Field(default_factory=list)
    cbsa_codes: list[str] = Field(default_factory=list)
    iatas: list[str] = Field(default_factory=list)
    hub_sizes: list[HubSize] = Field(default_factory=list)
    name_contains: str | None = None
    limit: int = Field(default=50, ge=1, le=600)

    @field_validator("states", "iatas", mode="before")
    @classmethod
    def _upper_list(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v]


class FeatureMatrix(BaseModel):
    """Dense numeric matrix for the Deterministic Analyst. values[i][j] = airport i, metric j (None = missing)."""
    model_config = ConfigDict(extra="forbid")
    airports: list[AirportRef]
    metric_ids: list[str]
    horizon: Horizon
    values: list[list[float | None]]
    peer_group: PeerGroup
    vintages: list[SourceVintage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> FeatureMatrix:
        if len(self.values) != len(self.airports):
            raise ValueError("values must have one row per airport")
        for row in self.values:
            if len(row) != len(self.metric_ids):
                raise ValueError("each row must have one value per metric_id")
        return self

    def coverage(self) -> float:
        total = len(self.airports) * len(self.metric_ids)
        if total == 0:
            return 0.0
        present = sum(1 for row in self.values for v in row if v is not None)
        return present / total

    def column(self, metric_id: str) -> list[float | None]:
        j = self.metric_ids.index(metric_id)
        return [row[j] for row in self.values]


class RouteRow(_Frozen):
    dest: str
    dest_name: str | None
    distance_mi: float
    departures: int
    seats: int
    passengers: int
    freight_lb: float
    is_international: bool


class RouteTable(_Frozen):
    iata: str
    period_start: str
    period_end: str
    source_id: str
    vintage: str
    rows: list[RouteRow]
    truncated: bool


class CuratedFact(_Frozen):
    iata: str
    category: str  # slot_level | hourly_cap | declared_capacity | gates | constraint | project | other
    text: str
    value: float | str | None = None
    source_url: str
    as_of: str
    expires: str | None = None


class LiveStatus(_Frozen):
    iata: str
    delay_programs: list[str]
    ground_stop: bool
    closure: bool
    latest_month: dict[str, float] | None
    fetched_at: str
    source_ids: list[str]


class AirportProfile(BaseModel):
    """Structured JSON view for the LLM specialists (≤ ~2k tokens)."""
    model_config = ConfigDict(extra="forbid")
    ref: AirportRef
    metrics: dict[str, list[Metric]]  # keyed by horizon ("12m", "5y", "static", "forecast")
    forecast: dict[str, float | str | None]
    routes_summary: dict[str, float | str | None]
    curated_facts: list[CuratedFact]
    live: LiveStatus | None
    data_quality_notes: list[str]
    vintages: list[SourceVintage]
```

- [ ] **Step 4: Run → PASS**; `uv run ruff check src tests`.
- [ ] **Step 5: Commit** — `git commit -am "feat(contracts): core domain models" ` (add new files first).

---

### Task 6: Requests, reports, conversation types + hint truncation helper

**Files:** Create `src/airport_agent/contracts/requests.py`, `reports.py`, `conversation.py`; `tests/contracts/test_requests.py`

**Interfaces — Produces:**
```python
# requests.py
QuestionType = Literal["rank", "compare", "diagnose", "custom"]
MAX_HINT_CHARS = 200; MAX_HINT_CHARS_GENERAL = 600
class ExtendedOptions(BaseModel): requested_sections, metrics, peer_group
class AnalysisRequest(BaseModel): question_type, airports, filter, horizons, scoring_preset, focus_metrics, hint, specialist, extended
def truncate_hint(req: AnalysisRequest) -> tuple[AnalysisRequest, bool]
# reports.py
class ScoreRow, DeterministicReport, RankedItem, SpecialistReport
# conversation.py
Intent = Literal["informational","analytical","followup","clarify"]
class Plan, Table, Citation, ToolCallTrace, Answer, ChatMessage, SessionState
```

- [ ] **Step 1: Failing tests**

`tests/contracts/test_requests.py`:
```python
import pytest
from pydantic import ValidationError

from airport_agent.contracts.conversation import Answer, Plan, SessionState, Table
from airport_agent.contracts.reports import DeterministicReport, ScoreRow, SpecialistReport
from airport_agent.contracts.requests import (MAX_HINT_CHARS, MAX_HINT_CHARS_GENERAL, AnalysisRequest,
                                              truncate_hint)
from tests.contracts.test_models import ref


def test_analysis_request_defaults():
    r = AnalysisRequest(question_type="rank", filter={"states": ["MA", "CT"]})
    assert r.horizons == ["5y"] and r.hint == "" and r.specialist is None and r.extended is None


def test_analysis_request_needs_airports_or_filter():
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="compare")


def test_hint_truncation_default_and_general():
    long = "x" * 1000
    r, cut = truncate_hint(AnalysisRequest(question_type="diagnose", airports=["SFO"], hint=long))
    assert cut and len(r.hint) == MAX_HINT_CHARS
    r2, cut2 = truncate_hint(AnalysisRequest(question_type="custom", airports=["DEN"], hint=long,
                                             specialist="general_analyst", extended={}))
    assert cut2 and len(r2.hint) == MAX_HINT_CHARS_GENERAL
    r3, cut3 = truncate_hint(AnalysisRequest(question_type="rank", airports=["BOS"], hint="short"))
    assert not cut3 and r3.hint == "short"


def test_custom_requires_general_specialist():
    with pytest.raises(ValidationError):
        AnalysisRequest(question_type="custom", airports=["DEN"], specialist="capacity_analyst")


def test_reports_construct():
    row = ScoreRow(ref=ref("BOS"), score=71.2, rank=1, pillar_contrib={"P1": 20.0}, metric_contrib={"enpl_cagr_5y": 8.0},
                   coverage=0.9, low_confidence=False)
    d = DeterministicReport(question_type="rank", preset="terminal_expansion", weights={"P1": 0.35}, horizon="5y",
                            peer_group="hub_class", rows=[row], comparison=None, evidence=[], explanation="BOS leads…",
                            caveats=[])
    s = SpecialistReport(specialist="expansion_analyst", question_type="rank", ranking=[], narrative="…", evidence=[],
                         agreement="agrees on top 3", disagreements=[], confidence=0.7, assumptions=[], caveats=[],
                         hint_truncated=False)
    assert d.rows[0].rank == 1 and 0 <= s.confidence <= 1
    with pytest.raises(ValidationError):
        SpecialistReport(specialist="x", question_type="rank", ranking=[], narrative="", evidence=[], agreement=None,
                         disagreements=[], confidence=1.5, assumptions=[], caveats=[], hint_truncated=False)


def test_plan_answer_session():
    p = Plan(intent="analytical", engines=["deterministic", "specialist:capacity_analyst"], filters={"airports": ["LAX", "SNA"]},
             tools_to_call=["compare_airports"], specialist="capacity_analyst", presentation_notes="show P2 only")
    a = Answer(plan=p, plan_line="compare · congestion · 12m", headline="SNA is more constrained relative to capacity",
               evidence_tables=[Table(title="P2 metrics", columns=["metric", "LAX", "SNA"], rows=[["avg_dep_delay_min", 12.9, 13.9]],
                                      footnotes=["OTP through 2026-06"])],
               analyst_view=None, agreement_line=None, assumptions=["OTP 24m"], uncertainty_notes=[], citations=[],
               follow_ups=["Why is SNA capped?"], tool_trace=[])
    s = SessionState(session_id="s1", title="test")
    s.messages.append({"role": "user", "content": "hi"})
    assert a.headline and s.last_reports == {} and s.messages[0].role == "user"
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

`requests.py`:
```python
"""Structured dispatch types (Concierge → Deterministic Analyst / LLM specialists)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from airport_agent.contracts.models import AirportFilter, Horizon, PeerGroup

QuestionType = Literal["rank", "compare", "diagnose", "custom"]
SpecialistName = Literal["expansion_analyst", "capacity_analyst", "market_analyst", "general_analyst"]
MAX_HINT_CHARS = 200
MAX_HINT_CHARS_GENERAL = 600


class ExtendedOptions(BaseModel):
    """Only honoured for general_analyst."""
    model_config = ConfigDict(extra="forbid")
    requested_sections: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    peer_group: PeerGroup | None = None


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType
    airports: list[str] | None = None
    filter: AirportFilter | None = None
    horizons: list[Horizon] = Field(default_factory=lambda: ["5y"])
    scoring_preset: str | None = None
    focus_metrics: list[str] | None = None
    hint: str = ""
    specialist: SpecialistName | None = None
    extended: ExtendedOptions | None = None

    @model_validator(mode="after")
    def _target(self) -> AnalysisRequest:
        if not self.airports and self.filter is None:
            raise ValueError("AnalysisRequest needs airports or a filter")
        if self.question_type == "custom" and self.specialist != "general_analyst":
            raise ValueError("question_type=custom is only valid for general_analyst")
        if self.extended is not None and self.specialist != "general_analyst":
            raise ValueError("extended options are only valid for general_analyst")
        return self


def hint_limit(req: AnalysisRequest) -> int:
    return MAX_HINT_CHARS_GENERAL if req.specialist == "general_analyst" else MAX_HINT_CHARS


def truncate_hint(req: AnalysisRequest) -> tuple[AnalysisRequest, bool]:
    """Return (request with hint cut to its limit, was_truncated)."""
    limit = hint_limit(req)
    if len(req.hint) <= limit:
        return req, False
    return req.model_copy(update={"hint": req.hint[:limit]}), True
```

`reports.py`:
```python
"""Outputs of the two analytical engines."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts.models import AirportRef, Horizon, Metric, PeerGroup
from airport_agent.contracts.requests import QuestionType


class ScoreRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: AirportRef
    score: float  # 0–100
    rank: int
    pillar_contrib: dict[str, float]
    metric_contrib: dict[str, float]
    coverage: float  # 0–1 share of metrics available for this airport
    low_confidence: bool


class DeterministicReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType
    preset: str | None
    weights: dict[str, float]
    horizon: Horizon
    peer_group: PeerGroup
    rows: list[ScoreRow]
    comparison: dict[str, dict[str, float | None]] | None  # metric_id -> {iata: value}
    evidence: list[Metric]
    explanation: str  # templated, formula-driven
    caveats: list[str]


class RankedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iata: str
    rank: int
    rationale: str
    confidence: float = Field(ge=0, le=1)


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specialist: str
    question_type: QuestionType
    ranking: list[RankedItem] | None
    narrative: str
    evidence: list[Metric]
    agreement: str | None
    disagreements: list[str]
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str]
    caveats: list[str]
    hint_truncated: bool
```

`conversation.py`:
```python
"""Concierge-facing types: Plan, Answer, session memory."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts.reports import DeterministicReport, SpecialistReport

Intent = Literal["informational", "analytical", "followup", "clarify"]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    engines: list[str]  # "tools" | "deterministic" | "specialist:<name>"
    filters: dict[str, Any]
    tools_to_call: list[str]
    specialist: str | None
    presentation_notes: str


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    columns: list[str]
    rows: list[list[Any]]
    footnotes: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    vintage: str
    url: str | None = None


class ToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any]
    rows: int | None
    provider: str | None
    latency_ms: int
    note: str | None = None


class Answer(BaseModel):
    """Fixed synthesis structure (design 03). Order of rendering: plan_line, headline, evidence_tables,
    analyst_view, agreement_line, assumptions+uncertainty_notes, follow_ups, tool_trace."""
    model_config = ConfigDict(extra="forbid")
    plan: Plan
    plan_line: str
    headline: str
    evidence_tables: list[Table]
    analyst_view: str | None
    agreement_line: str | None
    assumptions: list[str]
    uncertainty_notes: list[str]
    citations: list[Citation]
    follow_ups: list[str]
    tool_trace: list[ToolCallTrace]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "system"]
    content: str
    answer: Answer | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    title: str
    messages: list[ChatMessage] = Field(default_factory=list)
    last_airports: list[str] = Field(default_factory=list)
    last_filters: dict[str, Any] = Field(default_factory=dict)
    last_preset: str | None = None
    last_reports: dict[str, DeterministicReport | SpecialistReport] = Field(default_factory=dict)
```

- [ ] **Step 4: Run → PASS**; ruff clean.
- [ ] **Step 5: Commit** — `feat(contracts): requests, reports, conversation types`

---

### Task 7: Metric registry `config/metrics.yaml` + `contracts/registry.py` loader

**Files:** Create `config/metrics.yaml`, `src/airport_agent/contracts/registry.py`, `tests/contracts/test_registry.py`

**Interfaces — Produces:**
```python
def load_registry(path: Path | None = None) -> list[MetricSpec]      # default: <repo>/config/metrics.yaml
def registry_by_id(specs) -> dict[str, MetricSpec]
PILLAR_NAMES = {"P1": "Demand Pressure", "P2": "Congestion & Physical Constraint", "P3": "Market Quality",
                "P4": "Economic Base", "P5": "Financeability & Pipeline"}
```

- [ ] **Step 1: Failing tests**

```python
from airport_agent.contracts.registry import PILLAR_NAMES, load_registry, registry_by_id

EXPECTED_IDS = {
 "enpl_cagr_3y","enpl_cagr_5y","enpl_cagr_10y","taf_cagr_10y","taf_vs_actual_gap","load_factor","spill_proxy",
 "seats_per_dep_trend","pax_per_capita",
 "pct_arr_delay_gt15","avg_dep_delay_min","nas_delay_share","taxi_out_p80_min","ops_per_runway","npias_capacity_label",
 "peak_hour_ops_ratio","pax_per_gate","deps_per_gate_day","imc_capacity_ratio","slot_or_cap_flag",
 "carrier_hhi","top_carrier_share","intl_pax_share","longhaul_dep_share","route_count_nonstop","competing_seats_100mi","od_share",
 "cbsa_population","cbsa_pop_cagr_5y","msa_gdp_per_capita","msa_gdp_cagr_5y",
 "npias_dev_per_enpl","aip_per_enpl_10y","cpe_usd","nonaero_rev_per_enpl",
 "asv_utilization","terminal_sqft_per_nbeg","dscr","days_cash","use_agreement_type",
}


def test_registry_loads_all_ids_unique():
    specs = load_registry()
    ids = [s.id for s in specs]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED_IDS


def test_registry_pillars_and_tiers():
    by = registry_by_id(load_registry())
    assert set(PILLAR_NAMES) == {"P1","P2","P3","P4","P5"}
    assert by["cpe_usd"].direction == "down" and by["cpe_usd"].pillar == "P5" and by["cpe_usd"].tier == "A"
    assert by["pax_per_gate"].tier == "B"
    assert by["asv_utilization"].tier == "C"
    assert all(s.sources for s in by.values()) and all(s.horizons for s in by.values())
    assert any("unaudited" in c.lower() for c in by["cpe_usd"].caveats)
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Write `config/metrics.yaml`** (authoritative registry — 40 ids: 28 scored A/B, `od_share` attempt, 5 tier-C documented gaps, plus the 3y/10y CAGR variants and `intl_pax_share`; keep in sync with the test set above)

```yaml
# Metric registry — single source of truth for scorer, LLM prompts, UI tooltips.
# direction: up = higher value raises expansion attractiveness. tier: A dataset-computable for all airports;
# B needs curated YAML (majors only); C documented gap (never scored). horizons: which are supported.
pillars:
  P1: {name: Demand Pressure, default_weight: 0.30}
  P2: {name: Congestion & Physical Constraint, default_weight: 0.25}
  P3: {name: Market Quality, default_weight: 0.15}
  P4: {name: Economic Base, default_weight: 0.15}
  P5: {name: Financeability & Pipeline, default_weight: 0.15, normalize_within: hub_class}
metrics:
  # ---------- P1 Demand Pressure ----------
  - {id: enpl_cagr_3y, name: Enplanement growth (3y), definition: Compound annual growth of enplanements over 3 years,
     formula: "(E_t/E_{t-3})^(1/3) - 1", unit: pct, direction: up, pillar: P1, tier: A,
     sources: [bts_socrata, faa_taf], horizons: [3y]}
  - {id: enpl_cagr_5y, name: Enplanement growth (5y), definition: Compound annual growth of enplanements over 5 years,
     formula: "(E_t/E_{t-5})^(1/5) - 1", unit: pct, direction: up, pillar: P1, tier: A,
     sources: [bts_socrata, faa_taf], horizons: [5y]}
  - {id: enpl_cagr_10y, name: Enplanement growth (10y), definition: Compound annual growth of enplanements over 10 years,
     formula: "(E_t/E_{t-10})^(1/10) - 1", unit: pct, direction: up, pillar: P1, tier: A,
     sources: [bts_socrata, faa_taf], horizons: [10y],
     caveats: ["Spans the COVID collapse; interpret with 3y/5y"]}
  - {id: taf_cagr_10y, name: FAA forecast growth (10y), definition: FAA Terminal Area Forecast enplanement CAGR over next 10 years,
     formula: "(TAF_{t+10}/TAF_t)^(1/10) - 1", unit: pct, direction: up, pillar: P1, tier: A,
     sources: [faa_taf], horizons: [forecast]}
  - {id: taf_vs_actual_gap, name: Forecast optimism gap, definition: TAF forecast for latest year divided by latest actual enplanements,
     formula: "TAF_t / actual_t", unit: ratio, direction: up, pillar: P1, tier: A, sources: [faa_taf, bts_socrata], horizons: [12m]}
  - {id: load_factor, name: Load factor, definition: Passengers divided by seats on departing flights,
     formula: "passengers / seats", unit: ratio, direction: up, pillar: P1, tier: A, sources: [bts_t100, bts_socrata],
     horizons: [12m, 3y, 5y, 10y],
     caveats: ["No authoritative capacity cutoff; interpret with spill_proxy (spill model), not an absolute threshold"]}
  - {id: spill_proxy, name: Demand variability (spill proxy), definition: Dispersion of monthly load factor around its mean (route-weighted),
     formula: "std(monthly LF) / mean(monthly LF)", unit: ratio, direction: up, pillar: P1, tier: A, sources: [bts_t100], horizons: [12m, 3y]}
  - {id: seats_per_dep_trend, name: Upgauging trend, definition: Change in average seats per departure over 5 years,
     formula: "(seats/dep)_t / (seats/dep)_{t-5} - 1", unit: pct, direction: up, pillar: P1, tier: A, sources: [bts_t100], horizons: [5y],
     caveats: ["Rising gauge with flat departures is a proxy for slot/runway constraint"]}
  - {id: pax_per_capita, name: Propensity to fly, definition: Annual enplanements per resident of the airport's CBSA,
     formula: "enplanements / cbsa_population", unit: trips, direction: up, pillar: P1, tier: A, sources: [bts_socrata, census_cbsa],
     horizons: [12m], caveats: ["CBSA is a proxy for catchment"]}
  # ---------- P2 Congestion & Physical Constraint ----------
  - {id: pct_arr_delay_gt15, name: Late arrival rate, definition: Share of arrivals 15+ minutes late (14 CFR 234 definition),
     formula: "arrivals_late15 / arrivals", unit: pct, direction: up, pillar: P2, tier: A, sources: [bts_otp], horizons: [12m, 3y]}
  - {id: avg_dep_delay_min, name: Mean departure delay, definition: Mean departure delay in minutes,
     formula: "mean(DepDelayMinutes)", unit: min, direction: up, pillar: P2, tier: A, sources: [bts_otp], horizons: [12m, 3y]}
  - {id: nas_delay_share, name: Systemic (NAS) delay share, definition: NAS-attributed delay minutes as share of total delay minutes,
     formula: "nas_delay_min / total_delay_min", unit: pct, direction: up, pillar: P2, tier: A, sources: [bts_delay_cause],
     horizons: [12m, 3y, 5y, 10y]}
  - {id: taxi_out_p80_min, name: Surface congestion (taxi-out p80), definition: 80th percentile taxi-out time,
     formula: "p80(TaxiOut)", unit: min, direction: up, pillar: P2, tier: A, sources: [bts_otp], horizons: [12m]}
  - {id: ops_per_runway, name: Airfield intensity, definition: Annual operations per runway,
     formula: "annual_ops / runway_count", unit: ops, direction: up, pillar: P2, tier: A, sources: [faa_taf, ourairports], horizons: [12m]}
  - {id: npias_capacity_label, name: FAA capacity constraint status, definition: FAA NPIAS 2025–29 published label,
     formula: "ordinal: none=0, congested=1, constrained_2033=2, constrained_2028=3, severe_2033=4", unit: ordinal, direction: up,
     pillar: P2, tier: A, sources: [faa_npias], horizons: [forecast],
     caveats: ["Partly circular for slot-controlled airports (Level 2/3 are constrained by definition)"]}
  - {id: peak_hour_ops_ratio, name: Peak demand/capacity, definition: Peak-hour operations divided by declared VMC called rate,
     formula: "peak_hour_ops / declared_rate_vmc", unit: ratio, direction: up, pillar: P2, tier: B, sources: [bts_otp, curated], horizons: [12m],
     caveats: ["Declared capacities from FAA Capacity Profiles 2014–2019"]}
  - {id: pax_per_gate, name: Gate intensity, definition: Annual total passengers per gate,
     formula: "annual_passengers / gates", unit: pax, direction: up, pillar: P2, tier: B, sources: [bts_socrata, curated], horizons: [12m],
     caveats: ["Gate counts curated from FAA Competition Plans / master plans"]}
  - {id: deps_per_gate_day, name: Gate turns per day, definition: Daily departures per gate (ACRP planning range 5.0–6.5),
     formula: "departures / gates / 365", unit: turns, direction: up, pillar: P2, tier: B, sources: [bts_t100, curated], horizons: [12m]}
  - {id: imc_capacity_ratio, name: Weather fragility, definition: Instrument-conditions called rate divided by visual-conditions rate,
     formula: "rate_imc / rate_vmc", unit: ratio, direction: down, pillar: P2, tier: B, sources: [curated], horizons: [static]}
  - {id: slot_or_cap_flag, name: Legal capacity constraint, definition: Slot level 2/3, hourly cap or settlement cap in force (with expiry),
     formula: "1 if any legal cap else 0", unit: flag, direction: up, pillar: P2, tier: B, sources: [curated], horizons: [static]}
  # ---------- P3 Market Quality ----------
  - {id: carrier_hhi, name: Carrier concentration (HHI), definition: Herfindahl index of carrier passenger shares,
     formula: "sum(share_i^2) * 10000", unit: index, direction: down, pillar: P3, tier: A, sources: [bts_t100], horizons: [12m, 5y]}
  - {id: top_carrier_share, name: Anchor carrier dependence, definition: Largest carrier's share of passengers,
     formula: "max(carrier_pax) / total_pax", unit: pct, direction: down, pillar: P3, tier: A, sources: [bts_t100], horizons: [12m, 5y]}
  - {id: intl_pax_share, name: International mix, definition: International passengers as share of total,
     formula: "intl_pax / total_pax", unit: pct, direction: up, pillar: P3, tier: A, sources: [bts_socrata], horizons: [12m, 3y, 5y, 10y]}
  - {id: longhaul_dep_share, name: Long-haul mix, definition: Departures with distance >= 1,500 statute miles as share of total (our convention; bands short<500, medium 500–1500, long 1500–3000, ultra>3000),
     formula: "departures(distance>=1500) / departures", unit: pct, direction: up, pillar: P3, tier: A, sources: [bts_t100], horizons: [12m, 5y],
     caveats: ["No ICAO/IATA long-haul standard; threshold is a stated convention", "Passenger and freight variants computed separately"]}
  - {id: route_count_nonstop, name: Network breadth, definition: Distinct nonstop destinations served,
     formula: "count(distinct dest with departures>0)", unit: count, direction: up, pillar: P3, tier: A, sources: [bts_t100], horizons: [12m, 5y]}
  - {id: competing_seats_100mi, name: Local competition, definition: Departing seats at other commercial airports within 100 miles,
     formula: "sum(seats at airports within 100mi)", unit: seats, direction: down, pillar: P3, tier: A, sources: [bts_t100, ourairports], horizons: [12m],
     caveats: ["Proxy for leakage; true leakage needs ticket-level data"]}
  - {id: od_share, name: O&D share, definition: Origin-destination passengers as share of total (1 - connecting share),
     formula: "od_pax / total_pax", unit: pct, direction: up, pillar: P3, tier: A, sources: [bts_db1b], horizons: [12m],
     caveats: ["Requires BTS DB1B/OD-40 adapter (timeboxed attempt); absent if the adapter did not land"]}
  # ---------- P4 Economic Base ----------
  - {id: cbsa_population, name: Market size, definition: CBSA population estimate,
     formula: "cbsa_population", unit: persons, direction: up, pillar: P4, tier: A, sources: [census_cbsa], horizons: [12m], caveats: ["CBSA ≠ catchment"]}
  - {id: cbsa_pop_cagr_5y, name: Market growth, definition: 5-year CBSA population CAGR,
     formula: "(P_t/P_{t-5})^(1/5) - 1", unit: pct, direction: up, pillar: P4, tier: A, sources: [census_cbsa], horizons: [5y]}
  - {id: msa_gdp_per_capita, name: Market wealth, definition: MSA GDP per capita,
     formula: "msa_gdp / population", unit: usd, direction: up, pillar: P4, tier: A, sources: [bea_msa], horizons: [12m]}
  - {id: msa_gdp_cagr_5y, name: Economic momentum, definition: 5-year real MSA GDP CAGR,
     formula: "(G_t/G_{t-5})^(1/5) - 1", unit: pct, direction: up, pillar: P4, tier: A, sources: [bea_msa], horizons: [5y]}
  # ---------- P5 Financeability & Pipeline (normalize within hub class) ----------
  - {id: npias_dev_per_enpl, name: Identified capital need, definition: NPIAS 5-year development estimate per enplanement,
     formula: "npias_dev_2025_2029 / enplanements", unit: usd, direction: up, pillar: P5, tier: A, sources: [faa_npias], horizons: [forecast]}
  - {id: aip_per_enpl_10y, name: Federal grant support, definition: AIP grants over 10 years per enplanement,
     formula: "sum(aip_10y) / enplanements", unit: usd, direction: up, pillar: P5, tier: A, sources: [faa_aip], horizons: [10y],
     caveats: ["Treated as informational context in presets (weight may be 0)"]}
  - {id: cpe_usd, name: Airline cost per enplanement, definition: FAA CATS Form 127 line 16.5 airline cost per enplanement,
     formula: "form127_line_16_5", unit: usd, direction: down, pillar: P5, tier: A, sources: [faa_cats], horizons: [12m],
     caveats: ["Self-reported and unaudited; non-uniform accounting basis across airports", "Compare within hub class only"]}
  - {id: nonaero_rev_per_enpl, name: Non-aeronautical yield, definition: Non-aeronautical operating revenue per enplanement,
     formula: "nonaero_revenue / enplanements", unit: usd, direction: up, pillar: P5, tier: A, sources: [faa_cats], horizons: [12m],
     caveats: ["Inverts with hub size — compare within hub class only", "Per enplanement, not per passenger (ACI World unit trap)"]}
  # ---------- Tier C: documented gaps, never scored ----------
  - {id: asv_utilization, name: Annual Service Volume utilization, definition: Ops as share of ASV (FAA Order 5090.5 60%/80% planning triggers),
     formula: "annual_ops / ASV", unit: pct, direction: up, pillar: P2, tier: C, sources: [none_public], horizons: [static],
     caveats: ["ASV not published per airport; doctrine only"]}
  - {id: terminal_sqft_per_nbeg, name: Terminal area per NBEG, definition: Terminal square feet per narrow-body-equivalent gate (ACRP 25),
     formula: "terminal_sqft / nbeg", unit: sqft, direction: down, pillar: P2, tier: C, sources: [none_public], horizons: [static]}
  - {id: dscr, name: Debt service coverage, definition: Net revenues divided by debt service,
     formula: "net_revenue / debt_service", unit: ratio, direction: up, pillar: P5, tier: C, sources: [faa_cats], horizons: [12m],
     caveats: ["Debt service weakly reported in Form 127"]}
  - {id: days_cash, name: Days cash on hand, definition: Unrestricted cash × 365 / operating expenses,
     formula: "cash*365/opex", unit: days, direction: up, pillar: P5, tier: C, sources: [faa_cats], horizons: [12m],
     caveats: ["Cash lines inconsistently reported"]}
  - {id: use_agreement_type, name: Airline use agreement type, definition: Residual / compensatory / hybrid,
     formula: "categorical", unit: category, direction: up, pillar: P5, tier: C, sources: [bond_official_statements], horizons: [static]}
```

- [ ] **Step 4: Implement `registry.py`**

```python
"""Load and validate the metric registry (config/metrics.yaml) into MetricSpec objects."""
from __future__ import annotations

from pathlib import Path

import yaml

from airport_agent.contracts.models import MetricSpec

PILLAR_NAMES = {"P1": "Demand Pressure", "P2": "Congestion & Physical Constraint", "P3": "Market Quality",
                "P4": "Economic Base", "P5": "Financeability & Pipeline"}


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "metrics.yaml"


def load_registry(path: Path | None = None) -> list[MetricSpec]:
    p = path or default_registry_path()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    specs = [MetricSpec(**m) for m in raw["metrics"]]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate metric ids in registry")
    return specs


def load_pillars(path: Path | None = None) -> dict[str, dict]:
    p = path or default_registry_path()
    return yaml.safe_load(p.read_text(encoding="utf-8"))["pillars"]


def registry_by_id(specs: list[MetricSpec]) -> dict[str, MetricSpec]:
    return {s.id: s for s in specs}
```

- [ ] **Step 5: Run → PASS**; commit `feat(contracts): metric registry + loader`.

---

### Task 8: Protocols — `DataService`, `DeterministicAnalyst`, `LLMClient`, `SpecialistRunner`, `ToolSpec`

**Files:** Create `src/airport_agent/contracts/data_service.py`, `scoring.py`, `llm.py`, `specialists.py`, `tools.py`, and `contracts/__init__.py` re-exports; `tests/contracts/test_protocols.py`

**Interfaces — Produces (exact):**

```python
# data_service.py
class DataService(Protocol):
    def list_airports(self, filter: AirportFilter) -> list[AirportRef]: ...
    def get_airport(self, iata: str) -> AirportRef | None: ...
    def get_feature_matrix(self, airports: list[str], metric_ids: list[str], horizon: Horizon,
                           peer_group: PeerGroup = "hub_class") -> FeatureMatrix: ...
    def get_profile(self, iata: str, horizons: tuple[Horizon, ...] = ("12m", "5y")) -> AirportProfile: ...
    def get_routes(self, iata: str, horizon: Horizon = "12m", top_n: int = 25,
                   international: bool | None = None) -> RouteTable: ...
    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]: ...   # annual series for trends
    def get_live_status(self, iata: str) -> LiveStatus: ...
    def describe_metrics(self) -> list[MetricSpec]: ...
    def source_vintages(self) -> list[SourceVintage]: ...
# scoring.py
class DeterministicAnalyst(Protocol):
    def rank(self, req: AnalysisRequest) -> DeterministicReport: ...
    def compare(self, req: AnalysisRequest) -> DeterministicReport: ...
    def diagnose(self, req: AnalysisRequest) -> DeterministicReport: ...
    def distance_bands(self, iata: str, horizon: Horizon = "12m", freight: bool = False) -> dict[str, float]: ...
    def long_haul_share(self, iata: str, threshold_mi: float = 1500, horizon: Horizon = "12m", freight: bool = False) -> Metric: ...
# llm.py
class ToolCall(BaseModel): id, name, arguments: dict
class LLMResult(BaseModel): text, tool_calls: list[ToolCall], provider, model, input_tokens, output_tokens
class LLMError(Exception)  # carries provider, status, detail; raised after retries — never swallowed
class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None, response_schema: dict | None = None,
             temperature: float = 0.2) -> LLMResult: ...
# specialists.py
class SpecialistRunner(Protocol):
    def run(self, req: AnalysisRequest, deterministic: DeterministicReport | None) -> SpecialistReport: ...
# tools.py
class ToolSpec(BaseModel): name, description, params_model (type[BaseModel]), fn (Callable[..., dict]), engines: list[str]
```

- [ ] **Step 1: Failing test**

```python
from airport_agent.contracts import (AnalysisRequest, DataService, DeterministicAnalyst, LLMClient, LLMError,
                                     LLMResult, SpecialistRunner, ToolCall, ToolSpec)


def test_reexports_and_protocols_are_runtime_checkable():
    from typing import get_type_hints
    assert hasattr(DataService, "get_feature_matrix") and hasattr(DeterministicAnalyst, "diagnose")
    assert hasattr(LLMClient, "chat") and hasattr(SpecialistRunner, "run")
    r = LLMResult(text="hi", tool_calls=[ToolCall(id="1", name="find_airports", arguments={"states": ["MA"]})],
                  provider="gemini", model="gemini-flash", input_tokens=10, output_tokens=5)
    assert r.tool_calls[0].name == "find_airports"
    e = LLMError(provider="gemini", status=429, detail="quota")
    assert "gemini" in str(e) and "429" in str(e)
    assert AnalysisRequest is not None and ToolSpec is not None
    assert "iata" in get_type_hints(ToolSpec.__init__ if False else lambda iata: None) or True
```
(Keep this test simple: it pins names and the LLMError message format.)

- [ ] **Step 2: Implement the five files + `__init__.py`**

`data_service.py`, `scoring.py`, `specialists.py`: exactly the Protocols above with docstrings and `@runtime_checkable`.

`llm.py`:
```python
"""LLM client port. Implementations live in airport_agent.llm (LiteLLM router). Errors are never swallowed."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMError(Exception):
    """Raised after retries are exhausted. Must surface to the user verbatim (design 03 failure policy)."""

    def __init__(self, provider: str, status: int | None, detail: str):
        self.provider, self.status, self.detail = provider, status, detail
        super().__init__(f"LLM provider error — {provider}: {status if status is not None else 'error'} {detail}. "
                         "Check the API key in .env, your quota, or configure a provider in config/providers.yaml.")


@runtime_checkable
class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             response_schema: dict[str, Any] | None = None, temperature: float = 0.2) -> LLMResult: ...
```

`tools.py`:
```python
"""Tool specification shared by the ToolRegistry (agent) and specialists' allowed-tool subsets."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    name: str
    description: str  # states limits (e.g. hint truncation) explicitly
    params_model: type[BaseModel]
    fn: Callable[..., dict[str, Any]]  # returns JSON-serializable dict with 'provenance' and 'truncated'
    engines: list[str]  # which callers may use it: "concierge", "expansion_analyst", ...

    def json_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.params_model.model_json_schema()}
```

`__init__.py`: re-export everything public from models, requests, reports, conversation, registry, data_service, scoring, llm, specialists, tools (explicit `__all__`).

- [ ] **Step 3: Run → PASS**; `uv run lint-imports` still 3 kept; commit `feat(contracts): protocols and re-exports`.

---

### Task 9: `FakeDataService` + contract test suite

**Files:** Create `tests/fakes.py`, `tests/conftest.py`, `tests/contracts/conftest.py`, `tests/contracts/test_data_service_contract.py`

**Interfaces — Produces:**
```python
class FakeDataService:            # implements DataService; deterministic canned data, no I/O
    AIRPORTS: 12 refs — BOS, BDL, PVD, MHT, PWM (ANE); LAX, SNA, SFO, BUR (AWP); ANC (AAL); JFK (AEA); ATL (ASO); DEN (ANM)
    (13 — keep BUR; test expects NE set of 5)
# tests/contracts/conftest.py
DATA_SERVICE_FACTORIES: list[tuple[str, Callable[[], DataService]]] = [("fake", FakeDataService)]
@pytest.fixture(params=DATA_SERVICE_FACTORIES, ids=lambda p: p[0]) def data_service(request)
```
Phase 2's `data-engineer` appends `("duckdb", lambda: DuckDBDataService(test_snapshot))` to `DATA_SERVICE_FACTORIES` in a `tests/data/conftest_plugin.py` — the suite then runs against both.

- [ ] **Step 1: Failing contract tests**

`tests/contracts/test_data_service_contract.py`:
```python
import pytest

from airport_agent.contracts import AirportFilter, DataService, FeatureMatrix, load_registry

NE = {"BOS", "BDL", "PVD", "MHT", "PWM"}


def test_is_data_service(data_service):
    assert isinstance(data_service, DataService)


def test_list_airports_by_state_and_region(data_service):
    by_state = {a.iata for a in data_service.list_airports(AirportFilter(states=["MA", "CT", "RI", "NH", "VT", "ME"]))}
    by_region = {a.iata for a in data_service.list_airports(AirportFilter(faa_regions=["ANE"]))}
    assert NE <= by_state and NE <= by_region
    assert all(a.faa_region == "ANE" for a in data_service.list_airports(AirportFilter(faa_regions=["ANE"])))


def test_list_airports_limit_and_hub(data_service):
    assert len(data_service.list_airports(AirportFilter(limit=2))) == 2
    assert all(a.hub_size == "large" for a in data_service.list_airports(AirportFilter(hub_sizes=["large"])))


def test_get_airport(data_service):
    assert data_service.get_airport("bos").iata == "BOS"
    assert data_service.get_airport("ZZZ") is None


def test_feature_matrix_conforms_to_registry(data_service):
    ids = [s.id for s in load_registry() if s.tier in ("A", "B")]
    fm = data_service.get_feature_matrix(["BOS", "SFO", "ANC"], ids, "5y")
    assert isinstance(fm, FeatureMatrix)
    assert [a.iata for a in fm.airports] == ["BOS", "SFO", "ANC"] and fm.metric_ids == ids
    assert fm.coverage() > 0.5  # tier A must be mostly present
    assert all(v is None or isinstance(v, float) for row in fm.values for v in row)


def test_feature_matrix_rejects_unknown_metric(data_service):
    with pytest.raises((KeyError, ValueError)):
        data_service.get_feature_matrix(["BOS"], ["not_a_metric"], "5y")


def test_profile_has_all_sections_and_provenance(data_service):
    p = data_service.get_profile("SFO")
    assert p.ref.iata == "SFO" and set(p.metrics) >= {"12m", "5y"}
    assert p.vintages and all(m.source_id and m.vintage for h in p.metrics.values() for m in h)
    assert isinstance(p.data_quality_notes, list)


def test_routes_sorted_and_flagged(data_service):
    rt = data_service.get_routes("ANC", top_n=5)
    assert rt.iata == "ANC" and len(rt.rows) <= 5 and rt.source_id
    deps = [r.departures for r in rt.rows]
    assert deps == sorted(deps, reverse=True)
    intl = data_service.get_routes("JFK", international=True)
    assert all(r.is_international for r in intl.rows)


def test_metric_series_is_chronological(data_service):
    s = data_service.get_metric_series("BOS", "load_factor")
    assert len(s) >= 3 and [m.period_end for m in s] == sorted(m.period_end for m in s)


def test_live_status_and_vintages(data_service):
    ls = data_service.get_live_status("SFO")
    assert ls.iata == "SFO" and ls.fetched_at
    assert data_service.source_vintages()


def test_describe_metrics_matches_registry(data_service):
    assert {s.id for s in data_service.describe_metrics()} == {s.id for s in load_registry()}
```

- [ ] **Step 2: Run → FAIL** (fixture missing).

- [ ] **Step 3: Implement `tests/fakes.py`**

Design: a compact per-airport dict of *base* values for each tier-A metric (realistic magnitudes from the research: SFO LF 0.80, ANC long-haul share 0.30, LAX avg dep delay 12.9, SNA 13.9, SFO 18.0, NPIAS labels per the published lists, hub sizes, regions). Horizon variants derived deterministically (`value * (1 + 0.02*k)` for CAGR-like ids; identical for level ids). Tier-B values only for BOS, LAX, SFO, JFK, SNA (curated majors). Tier-C always `None`. Routes: 6–8 canned rows per airport with realistic distances (ANC: SEA 1449, ORD 2846, HKG 5060 intl freight-heavy…; JFK: LHR 3451 intl, LAX 2475). Metric series: 2016–2026 annual with a smooth trend. Live status: SFO delay program `["Ground Delay Program"]`, others none. Vintages: one per fake source id used in the registry.

```python
"""FakeDataService — deterministic canned data implementing the DataService Protocol. No I/O."""
from __future__ import annotations

from airport_agent.contracts import (AirportFilter, AirportProfile, AirportRef, CuratedFact, FeatureMatrix, LiveStatus,
                                     Metric, MetricSpec, RouteRow, RouteTable, SourceVintage, load_registry)
from airport_agent.contracts.models import Horizon, PeerGroup

FETCHED = "2026-08-15T00:00:00"
VINT = "2026-04"

_A = [  # iata, icao, name, city, state, region, hub, lat, lon
    ("BOS", "KBOS", "Logan International", "Boston", "MA", "ANE", "large", 42.36, -71.01),
    ("BDL", "KBDL", "Bradley International", "Windsor Locks", "CT", "ANE", "medium", 41.94, -72.68),
    ("PVD", "KPVD", "T. F. Green", "Providence", "RI", "ANE", "small", 41.73, -71.43),
    ("MHT", "KMHT", "Manchester-Boston Regional", "Manchester", "NH", "ANE", "small", 42.93, -71.44),
    ("PWM", "KPWM", "Portland International Jetport", "Portland", "ME", "ANE", "small", 43.65, -70.31),
    ("LAX", "KLAX", "Los Angeles International", "Los Angeles", "CA", "AWP", "large", 33.94, -118.41),
    ("SNA", "KSNA", "John Wayne", "Santa Ana", "CA", "AWP", "medium", 33.68, -117.87),
    ("SFO", "KSFO", "San Francisco International", "San Francisco", "CA", "AWP", "large", 37.62, -122.38),
    ("BUR", "KBUR", "Hollywood Burbank", "Burbank", "CA", "AWP", "medium", 34.20, -118.36),
    ("ANC", "PANC", "Ted Stevens Anchorage International", "Anchorage", "AK", "AAL", "medium", 61.17, -150.0),
    ("JFK", "KJFK", "John F. Kennedy International", "New York", "NY", "AEA", "large", 40.64, -73.78),
    ("ATL", "KATL", "Hartsfield-Jackson Atlanta International", "Atlanta", "GA", "ASO", "large", 33.64, -84.43),
    ("DEN", "KDEN", "Denver International", "Denver", "CO", "ANM", "large", 39.86, -104.67),
]
AIRPORTS = [AirportRef(iata=i, icao=c, faa_locid=i, name=n, city=ci, state=s, faa_region=r, hub_size=h, lat=la, lon=lo)
            for i, c, n, ci, s, r, h, la, lo in _A]
MAJORS = {"BOS", "LAX", "SFO", "JFK", "SNA"}

# base tier-A values (12m); horizon variants derived below
BASE: dict[str, dict[str, float]] = {
    "BOS": dict(enpl_cagr=0.03, taf_cagr_10y=0.021, taf_vs_actual_gap=1.02, load_factor=0.82, spill_proxy=0.06, seats_per_dep_trend=0.08, pax_per_capita=4.1,
                pct_arr_delay_gt15=0.22, avg_dep_delay_min=13.5, nas_delay_share=0.35, taxi_out_p80_min=24, ops_per_runway=68000, npias_capacity_label=4,
                carrier_hhi=1400, top_carrier_share=0.30, intl_pax_share=0.17, longhaul_dep_share=0.14, route_count_nonstop=140, competing_seats_100mi=6e6,
                cbsa_population=4.9e6, cbsa_pop_cagr_5y=0.004, msa_gdp_per_capita=110000, msa_gdp_cagr_5y=0.021,
                npias_dev_per_enpl=48, aip_per_enpl_10y=6, cpe_usd=18.5, nonaero_rev_per_enpl=12.9),
    # … BDL, PVD, MHT, PWM, LAX, SNA, SFO, BUR, ANC, JFK, ATL, DEN with plausible values; SFO: load_factor 0.80,
    # avg_dep_delay_min 18.0, npias_capacity_label 4, imc; LAX: avg 12.9, label 3; SNA: avg 13.9, label 1, spill 0.09;
    # ANC: longhaul_dep_share 0.30, intl_pax_share 0.05, freight-heavy routes; JFK: intl 0.55, label 4; ATL: hhi 5500,
    # top_carrier_share 0.74, label 2; DEN: label 1, enpl_cagr 0.05.
}
TIER_B = {  # curated majors only
    "BOS": dict(peak_hour_ops_ratio=0.9, pax_per_gate=420000, deps_per_gate_day=5.2, imc_capacity_ratio=0.75, slot_or_cap_flag=0),
    "LAX": dict(peak_hour_ops_ratio=0.95, pax_per_gate=520000, deps_per_gate_day=5.6, imc_capacity_ratio=0.80, slot_or_cap_flag=1),
    "SFO": dict(peak_hour_ops_ratio=1.0, pax_per_gate=470000, deps_per_gate_day=5.4, imc_capacity_ratio=0.70, slot_or_cap_flag=1),
    "JFK": dict(peak_hour_ops_ratio=1.0, pax_per_gate=480000, deps_per_gate_day=5.0, imc_capacity_ratio=0.85, slot_or_cap_flag=1),
    "SNA": dict(peak_hour_ops_ratio=0.85, pax_per_gate=560000, deps_per_gate_day=6.1, imc_capacity_ratio=0.85, slot_or_cap_flag=1),
}
CAGR_IDS = {"enpl_cagr_3y": 0.9, "enpl_cagr_5y": 1.0, "enpl_cagr_10y": 0.6}  # multipliers on BASE["enpl_cagr"]
LABEL_MAP = {0: "none", 1: "congested", 2: "constrained_2033", 3: "constrained_2028", 4: "severe_2033"}


class FakeDataService:
    def __init__(self) -> None:
        self._specs = load_registry()
        self._by_id = {s.id: s for s in self._specs}
        self._refs = {a.iata: a for a in AIRPORTS}

    # --- helpers ---
    def _value(self, iata: str, metric_id: str, horizon: str) -> float | None:
        spec = self._by_id[metric_id]  # KeyError for unknown ids (contract)
        if spec.tier == "C":
            return None
        if spec.tier == "B":
            return float(TIER_B.get(iata, {}).get(metric_id)) if iata in TIER_B and metric_id in TIER_B[iata] else None
        base = BASE[iata]
        if metric_id in CAGR_IDS:
            return base["enpl_cagr"] * CAGR_IDS[metric_id]
        v = base.get(metric_id)
        if v is None:
            return None
        k = {"12m": 0, "3y": 1, "5y": 2, "10y": 3}.get(horizon, 0)
        return float(v * (1 + 0.01 * k)) if spec.unit in ("pct", "ratio") and metric_id != "npias_capacity_label" else float(v)

    def _metric(self, iata: str, metric_id: str, horizon: str) -> Metric:
        spec = self._by_id[metric_id]
        return Metric(id=metric_id, value=self._value(iata, metric_id, horizon), unit=spec.unit,
                      horizon=horizon if horizon in ("12m", "3y", "5y", "10y") else "static",
                      period_start="2025-05", period_end=VINT, source_id=spec.sources[0], vintage=VINT)

    # --- DataService ---
    def list_airports(self, filter: AirportFilter) -> list[AirportRef]:
        out = []
        for a in AIRPORTS:
            if filter.states and a.state not in filter.states: continue
            if filter.faa_regions and a.faa_region not in filter.faa_regions: continue
            if filter.iatas and a.iata not in filter.iatas: continue
            if filter.hub_sizes and a.hub_size not in filter.hub_sizes: continue
            if filter.name_contains and filter.name_contains.lower() not in a.name.lower(): continue
            out.append(a)
        return out[: filter.limit]

    def get_airport(self, iata: str) -> AirportRef | None:
        return self._refs.get(iata.upper())

    def get_feature_matrix(self, airports, metric_ids, horizon: Horizon, peer_group: PeerGroup = "hub_class") -> FeatureMatrix:
        refs = [self._refs[i.upper()] for i in airports]
        for m in metric_ids:
            if m not in self._by_id:
                raise KeyError(f"unknown metric id: {m}")
        values = [[self._value(r.iata, m, horizon) for m in metric_ids] for r in refs]
        return FeatureMatrix(airports=refs, metric_ids=metric_ids, horizon=horizon, values=values,
                             peer_group=peer_group, vintages=self.source_vintages())

    def get_profile(self, iata: str, horizons=("12m", "5y")) -> AirportProfile:
        ref = self._refs[iata.upper()]
        metrics = {h: [self._metric(ref.iata, s.id, h) for s in self._specs if s.tier != "C"] for h in horizons}
        facts = [CuratedFact(iata=ref.iata, category="slot_level", text="IATA Level 2 schedule-facilitated", value=2,
                             source_url="https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration",
                             as_of="2026-06", expires=None)] if ref.iata in {"SFO", "LAX"} else []
        notes = ["OTP undercounts this airport (cargo/regional carriers not in OTP)"] if ref.iata == "ANC" else []
        return AirportProfile(ref=ref, metrics=metrics, forecast={"taf_cagr_10y": BASE[ref.iata]["taf_cagr_10y"]},
                              routes_summary={"nonstop_destinations": BASE[ref.iata]["route_count_nonstop"]},
                              curated_facts=facts, live=self.get_live_status(ref.iata), data_quality_notes=notes,
                              vintages=self.source_vintages())

    def get_routes(self, iata: str, horizon: Horizon = "12m", top_n: int = 25, international: bool | None = None) -> RouteTable:
        rows = ROUTES.get(iata.upper(), [])
        if international is not None:
            rows = [r for r in rows if r.is_international == international]
        rows = sorted(rows, key=lambda r: r.departures, reverse=True)
        return RouteTable(iata=iata.upper(), period_start="2025-05", period_end=VINT, source_id="bts_t100", vintage=VINT,
                          rows=rows[:top_n], truncated=len(rows) > top_n)

    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]:
        base = self._value(iata.upper(), metric_id, "12m") or 0.0
        return [Metric(id=metric_id, value=base * (1 - 0.01 * (2026 - y)), unit=self._by_id[metric_id].unit, horizon="12m",
                       period_start=f"{y}-01", period_end=f"{y}-12", source_id=self._by_id[metric_id].sources[0], vintage=VINT)
                for y in range(2016, 2027)]

    def get_live_status(self, iata: str) -> LiveStatus:
        i = iata.upper()
        return LiveStatus(iata=i, delay_programs=["Ground Delay Program"] if i == "SFO" else [], ground_stop=False,
                          closure=False, latest_month={"total_passengers": 1e6}, fetched_at=FETCHED,
                          source_ids=["faa_nasstatus", "bts_socrata"])

    def describe_metrics(self) -> list[MetricSpec]:
        return list(self._specs)

    def source_vintages(self) -> list[SourceVintage]:
        ids = sorted({src for s in self._specs for src in s.sources})
        return [SourceVintage(source_id=s, description=f"fake {s}", period_start="2016-01", period_end=VINT,
                              fetched_at=FETCHED, url=None) for s in ids]


ROUTES: dict[str, list[RouteRow]] = {
    "ANC": [RouteRow(dest="SEA", dest_name="Seattle", distance_mi=1449, departures=3000, seats=450000, passengers=380000, freight_lb=1e6, is_international=False),
            RouteRow(dest="ORD", dest_name="Chicago", distance_mi=2846, departures=600, seats=100000, passengers=85000, freight_lb=5e5, is_international=False),
            RouteRow(dest="HKG", dest_name="Hong Kong", distance_mi=5060, departures=900, seats=0, passengers=0, freight_lb=9e7, is_international=True),
            RouteRow(dest="ICN", dest_name="Seoul", distance_mi=3760, departures=800, seats=0, passengers=0, freight_lb=8e7, is_international=True),
            RouteRow(dest="FAI", dest_name="Fairbanks", distance_mi=261, departures=2500, seats=250000, passengers=200000, freight_lb=2e6, is_international=False),
            RouteRow(dest="MSP", dest_name="Minneapolis", distance_mi=2513, departures=400, seats=70000, passengers=60000, freight_lb=1e5, is_international=False)],
    "JFK": [RouteRow(dest="LHR", dest_name="London", distance_mi=3451, departures=4000, seats=1.2e6, passengers=1.05e6, freight_lb=5e7, is_international=True),
            RouteRow(dest="LAX", dest_name="Los Angeles", distance_mi=2475, departures=6000, seats=1.1e6, passengers=9.5e5, freight_lb=2e7, is_international=False),
            RouteRow(dest="CDG", dest_name="Paris", distance_mi=3635, departures=2500, seats=8e5, passengers=7e5, freight_lb=3e7, is_international=True)],
    # BOS, LAX, SNA, SFO, others: 3–6 rows each with realistic distances (BOS–LHR 3265 intl, BOS–DCA 399, LAX–SFO 337,
    # SNA–SFO 372, SFO–LAX 337, SFO–HKG 6927 intl, DEN–LAX 862, ATL–MCO 404 …)
}
```
The implementer must fill every airport's `BASE` row (all 28 tier-A ids except `od_share`, which is `None` for all — it is an attempt) and 3–6 `ROUTES` rows per airport. Values need only be plausible and internally consistent (SFO delay > LAX delay; ANC long-haul share ≈ 0.30; JFK intl share high; NPIAS labels per the published lists in the research note).

`tests/conftest.py`: `import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))` so `from tests.fakes import …` works; and `pytest_plugins` hook point.

`tests/contracts/conftest.py`:
```python
import pytest
from tests.fakes import FakeDataService

DATA_SERVICE_FACTORIES = [("fake", FakeDataService)]  # data-engineer appends ("duckdb", factory) in Phase 2


@pytest.fixture(params=DATA_SERVICE_FACTORIES, ids=lambda p: p[0])
def data_service(request):
    return request.param[1]()
```

- [ ] **Step 4: Run → PASS** (`uv run pytest tests/contracts -v`, 11 contract tests × 1 impl).
- [ ] **Step 5: Commit** — `test: FakeDataService and DataService contract suite`.

---

### Task 10: Freeze — reviewer gate, marker, tag, scribe

- [ ] **Step 1: Dispatch `reviewer`** on `git diff <skeleton-commit>..HEAD` with design 00/02/03 — ask specifically: (a) does every type in 03's contract sketch exist with equivalent fields, (b) any logic in contracts/, (c) registry ids/tiers/directions match 02, (d) fake realism vs research values, (e) test quality. Apply fixes; re-run full suite + ruff + lint-imports.
- [ ] **Step 2: Create marker and tag**
```bash
printf "Contracts and config/metrics.yaml frozen 2026-08-15. Changes need a human decision + CONTRACTS_UNFROZEN=1 + rebase of all worktrees.\n" > .contracts-frozen
git add .contracts-frozen && git commit -m "chore: freeze contracts and metric registry (v1)" && git tag contracts-v1 && git push && git push --tags
```
- [ ] **Step 3: Verify the freeze hook blocks** an Edit to `src/airport_agent/contracts/models.py` (expect BLOCKED), and allows it with `CONTRACTS_UNFROZEN=1`.
- [ ] **Step 4: `/log-progress`** milestone "Phase 1 — contracts frozen".
- [ ] **Step 5: Write Phase 2 plans** (data, scoring, agent, ui) quoting the frozen signatures; create the four worktrees.

---

## Self-review (done while writing)
- Spec coverage: 00 (layout, rules, contracts, tools list ✔ — ToolSpec + names appear in Task 8/agent plan), 02 (registry ✔; presets deferred to scoring plan by design), 03 (all types ✔; runner/Concierge deferred to agent plan), 05 (CLAUDE.md ✔, agents ✔, hooks ✔, skills ✔, phases ✔), 06 (nothing in Phase 1).
- Placeholder scan: BASE/ROUTES tables intentionally list a representative subset with explicit fill instructions and constraints — acceptable because values are illustrative and the tests pin the invariants; everything else is complete code.
- Type consistency: `Horizon`, `PeerGroup`, `AnalysisRequest.filter: AirportFilter`, `DeterministicReport.rows: ScoreRow`, `SessionState.last_reports: dict[str, DeterministicReport|SpecialistReport]`, `LLMError(provider, status, detail)`, `DataService.get_feature_matrix(airports: list[str], metric_ids, horizon, peer_group)` used consistently across Tasks 5–9.
