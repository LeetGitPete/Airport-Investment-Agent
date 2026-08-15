# 05 — AI-native Development Process (CLAUDE.md, subagents, hooks, skills, scribe)

Status: DRAFT (brainstorm 2026-08-15).

## Goal
`.claude/` is a working artifact of *how* the project is built: lean enough to serve a one-day build, complete
enough to be a showcase in the deliverable ("where/how AI is used" — dev-time half).

## 5.0 Escalation protocol (applies to every agent, non-negotiable)
- **Trivial** = fully covered by `docs/design/*` and CLAUDE.md. Do it.
- **Non-trivial** = ambiguous, off-design, a new tradeoff, a data surprise, a contract change, a scope question, or
  anything the agent would have to "decide" — **STOP. Do not improvise.** Return a `DECISION NEEDED` block:
  `{what, why it matters, options (2–3), recommendation, what is blocked meanwhile}` and finish any independent
  work that does not depend on the answer.
- The orchestrating session relays every `DECISION NEEDED` to the human verbatim and waits. The orchestrator does
  not resolve design-relevant questions on the human's behalf; the human decides whether it is off-track or new.
- Decisions taken are appended to the relevant design doc and to the limitations log by the orchestrator.

## 5.1 `CLAUDE.md` (root, ~80 lines)
Purpose (3 lines) · layering rule (import only from `contracts/` + own package; `agent/` is the composition root)
· methodology principle (investor questions → metrics → data; metrics follow questions, infrastructure follows
metrics) · pointers: `docs/design/*` is the source of truth; `docs/design/known-limitations-and-tradeoffs.md`
must be updated when a constraint/decision is made · commands (`uv run pytest`, `python -m airport_agent.data
refresh --check`, `python -m airport_agent.ui.cli "…"`, `streamlit run …`) · conventions (Python 3.12, pydantic v2,
`typing.Protocol`, type hints, ruff, no free-form SQL in tools, every number carries source+vintage) · product
rules (state assumptions & uncertainty; show the Plan; never alter numbers; fail loudly on LLM errors) ·
don'ts (invent weights, hardcode model names, cache LLM outputs, silently degrade, edit frozen contracts) ·
escalation protocol (5.0) · process-log expectation.

## 5.2 Subagent roster — `.claude/agents/<name>.md`
Each file: role, model, allowed tools, inputs (which design docs), outputs (which paths), forbidden actions,
escalation protocol, and the report-back format (`changed / tested / untested / assumptions / DECISION NEEDED?`).

| Agent | Model | Job | Reads | Writes |
|---|---|---|---|---|
| `contract-architect` | Fable/Opus | Write & freeze `contracts/`, `tests/fakes.py::FakeDataService`, contract tests, and the metric registry `config/metrics.yaml` — first task, reviewed | 00–03 | `contracts/`, `tests/fakes.py`, `tests/contracts/`, `config/metrics.yaml` |
| `data-engineer` | Opus (adapters) / Sonnet (fixtures) | Adapters, store, derived metrics, refresh, snapshot; verify T-100 intl code; DB1B timeboxed attempt; curated YAML skeleton | 01, 02, research | `data/`, `config/sources.yaml`, `data/snapshot`, `data/curated`, fixtures |
| `scoring-engineer` | Opus | Scorer, presets, Deterministic Analyst methods, templated explanations (reads the frozen registry) | 02 | `scoring/`, `config/scoring_presets.yaml` |
| `agent-engineer` | Opus | LiteLLM router, ToolRegistry, Concierge (Plan → dispatch → synthesis), specialist configs, sessions | 03, LLM research | `agent/`, `llm/`, `config/providers.yaml`, `config/specialists/` |
| `ui-engineer` | Sonnet | Streamlit app (multi-chat, rendering, sidebar), CLI harness | 04 | `ui/` |
| `voice-engineer` | Sonnet | `feature/voice` branch, timeboxed | 04 | branch only |
| `reviewer` | Fable/Opus | Boundary + correctness review per workstream before merge; checks design conformance | diff + docs | review notes (no code edits) |
| `process-scribe` | Sonnet | Maintains `docs/process-log.md` (5.4) | raw feed, git log, agent reports | `docs/process-log.md` |
| `doc-assembler` | Opus | Assemble `docs/DESIGN.md` + README from design/, limitations log, process log | all docs | `docs/DESIGN.md`, `README.md` |

Model rule: architecture/reasoning-heavy → Fable/Opus; well-specified implementation → Sonnet; upkeep → Sonnet/Haiku.

## 5.3 Hooks — `.claude/settings.json` (few, mechanical)
- `PreToolUse` (Bash `git commit|push`): block if `.env` or any `*key*`/`*secret*` file is staged.
- `PreToolUse` (Edit/Write under `src/airport_agent/contracts/`): block after freeze unless `CONTRACTS_UNFROZEN=1`.
- `PostToolUse` (Edit/Write under `src/**`): `ruff check` + `lint-imports` (import-linter: layered + independence
  contracts between data/scoring/agent/ui) — instant feedback on boundary violations.
- `SubagentStop` / `Stop`: append `{ts, agent, one-line summary}` to `docs/process-log.raw.jsonl` (scribe feed).

## 5.4 `process-scribe` design
- **When:** dispatched at milestones (contracts frozen; each workstream merged; integration; final), via `/log-progress`.
- **Inputs:** `docs/process-log.raw.jsonl`, `git log --since <last run>`, agent final reports pasted by the
  orchestrator, the limitations log diff.
- **Output:** appends/updates the current section of `docs/process-log.md`: chronological, tagged
  `[KEY]` / `[AI]` / `[COURSE-CORRECTION]` / `[DECISION]`; records what AI did vs what the human decided;
  failures and retries honestly. Maintains a table **"Where/how AI is used"** with two halves — *runtime* (Concierge,
  specialists, provider chain) and *dev-time* (which agents built what, model per task, review gates) — lifted into
  DESIGN.md by the doc-assembler.
- **Rules:** never delete earlier entries; never invent; facts + one-line rationale; flag unverifiable claims;
  ≤ 25 lines per milestone.

## 5.5 Skills — `.claude/skills/` (three only)
- `/refresh-data` — runs `refresh` (+ `--check`), summarizes staleness and failures.
- `/eval-samples` — runs the four sample questions + scripted follow-ups through the CLI, diffs against golden
  files (structure + key numbers), reports.
- `/log-progress` — dispatches the process-scribe with the inputs above.

## 5.6 Workflow — phases, gates, worktrees
Parallelism only where phases make agents truly disjoint; more sequential is preferred over unsafe parallel.
One machine, one repo: each parallel agent gets its **own git worktree** (`git worktree add ../aa-<ws> feature/<ws>`)
= its own directory checkout on its own branch; agents never see each other's uncommitted work.

| Phase | Mode | Who | Exit gate |
|---|---|---|---|
| 0 Skeleton | sequential (orchestrator) | — | package tree, `pyproject`, CLAUDE.md, hooks, config stubs, docs on `main` |
| 1 Freeze | sequential | `contract-architect` → `reviewer` | `contracts/`, `FakeDataService`, contract tests, **`config/metrics.yaml` registry** frozen on `main`; hooks lock them |
| 2 Workstreams | **parallel, 4 worktrees** | data · scoring · agent · ui | each touches only its own package + tests, builds against the fake + frozen registry; `reviewer` gate per workstream |
| 3 Merge & integrate | sequential | orchestrator + `reviewer` | merge in dependency order data → scoring → agent → ui; real snapshot; `/eval-samples` green |
| 4 Polish | small parallel | `voice-engineer` (own worktree), `doc-assembler`, `process-scribe` | zip checklist (06) |

Rules for Phase 2:
- Shared surface = `contracts/` + `config/metrics.yaml` only, both frozen. Need more? → `DECISION NEEDED` (5.0).
  If a change is approved, `contract-architect` applies it on `main` and **all worktrees rebase** before continuing.
- One owner per shared file (`pyproject.toml` deps → orchestrator; `config/*` → named owner); others report needs.
- No sibling-package imports (hook-enforced), so integration surprises are behavioural, not interface-level.
- Agents must not assume anything about sibling code beyond the frozen contracts; the fake is the only stand-in.
Note: derived-metric *computation* is in `data/`, definitions in the registry used by `scoring/` — which is why the
registry is frozen in Phase 1 rather than authored in Phase 2.
