# HANDOFF — post-compaction prompt (written 2026-08-15, end of Phase 1)

> Paste/point the resumed session at this file. It is the authoritative "where we are, what's next, how we work".

## Who / what
Project: **Airport Investment Intelligence Agent** — a ~1-day take-home assignment (`project-description.txt`).
Repo: `C:\Users\palis\Desktop\soft-projects\airport-agent`, GitHub `LeetGitPete/Airport-Investment-Agent`, branch `main`.
User: Pete (they/them). Deliverable is a **zip** of the repo (+ `.env` with a throwaway-account Gemini key), not the repo link.

## Read these first (in order, ~10 min)
1. `CLAUDE.md` — project rules, layering, product rules, **escalation protocol**, report-back format.
2. `docs/design/00-overview.md` … `06-deliverables.md` + `known-limitations-and-tradeoffs.md` (21 rows) — the design is the source of truth.
3. `docs/design/05-ai-native-dev-process.md` §5.6 — phases/gates/worktrees; §5.0 escalation.
4. `docs/superpowers/plans/2026-08-15-plan1-skeleton-and-contracts.md` — Plan 1 (DONE). Its "Interfaces — Produces" blocks + the actual code in `src/airport_agent/contracts/` are what Phase 2 builds against.
5. `docs/process-log.md` — narrative so far (scribe-maintained). `docs/research/*` — evidence for data sources, LLM providers, investment metrics.
6. `.superpowers/sdd/2026-08-15-plan1-skeleton-and-contracts/progress.md` — the SDD ledger of Plan 1 (deferred minors + notes for Phase 2 live here; gitignored, local only).

## State (verified)
- **Phase 0–1 complete and frozen.** Tag `contracts-v1`; `.contracts-frozen` marker; `src/airport_agent/contracts/**` and `config/metrics.yaml` are FROZEN. 57 tests green, ruff clean, import-linter 4 contracts kept. All pushed.
- Exists: pyproject/uv toolchain; `.claude/` (4 hooks with tests, 9 agent specs, 3 skills: `/refresh-data`, `/eval-samples`, `/log-progress`); contracts package (models, requests, reports, conversation, registry loader, Protocols `DataService`/`DeterministicAnalyst`/`LLMClient`/`SpecialistRunner`, `ToolSpec`); registry (40 ids, 5 pillars, tiers A/B/C); `tests/fakes.py::FakeDataService` (13 airports) + contract suite (`tests/contracts/`, extension via root `conftest.py` `pytest_plugins` → `tests.data.conftest_plugin` appends `("duckdb", factory)` to `DATA_SERVICE_FACTORIES`).
- **Hooks caveat:** `.claude/settings.json` hooks were created mid-session and are NOT active in the current session (verified: an Edit to a frozen file went through). The user does not want to restart the session. Mitigation already in place: `.claude/agents/reviewer.md` **Step 0** makes every reviewer git-verify that `src/airport_agent/contracts` and `config/metrics.yaml` are untouched in the diff and flag Critical if not. Keep doing that in every review dispatch; do not rely on hooks.
- Empty packages awaiting Phase 2: `src/airport_agent/{data,scoring,llm,agent,ui}/`.

## Key decisions (do not re-litigate)
Assignment-first; Python 3.12 + pydantic v2 + DuckDB + LiteLLM (**Gemini free tier only**, others deferred) + Streamlit multi-chat; frozen contracts + registry before parallel work; Concierge (Plan → dispatch → synthesis) + Deterministic Analyst (code) + 4 LLM specialists (expansion/capacity/market/general) via structured `AnalysisRequest` (hint ≤200 chars, 600 for general); 5 pillars, percentile within hub class, presets balanced/terminal_expansion/congestion_relief/market_entry; long-haul = distance bands with ≥1,500 mi default convention, pax vs freight separately; spill model instead of LF cutoff; **no silent degradation** (LLM failure → loud actionable error); **no cross-request LLM/report caching**; multiple chats with persisted history; voice on separate timeboxed branch `feature/voice`; DB1B/OD-40 = timeboxed attempt; deliverable docs = DESIGN.md + standalone SCORING-METHODOLOGY.md / KEY-TRADEOFFS.md (ends with Out-of-scope) / WHERE-HOW-AI-IS-USED.md; process log maintained by `process-scribe` at milestones.

## How we work (user's explicit preferences)
- **Escalate, don't improvise.** Any non-trivial/off-design/new question from any agent → `DECISION NEEDED` block relayed to the user verbatim (use AskUserQuestion); do not resolve design-relevant questions on their behalf.
- Subagent-driven development (superpowers skill): fresh implementer per task, task reviewer after each, scoped re-review after fix rounds, ledger in `.superpowers/sdd/<plan>/progress.md`. Model choice: haiku for transcription, sonnet for code from complete specs, opus for judgement/reviews of substance. Use the project's own agents (`contract-architect`, `data-engineer`, `scoring-engineer`, `agent-engineer`, `ui-engineer`, `reviewer`, `process-scribe`, `doc-assembler`, `voice-engineer`) with an explicit `model` override.
- Prefer safer sequential gates over risky parallelism; agents must not assume anything about sibling code beyond frozen contracts + `FakeDataService`.
- Commit early/often to `main` (git identity: `-c user.name="Pete" -c user.email="Itamarr@voyager-labs.com"`); update the limitations log whenever a constraint/decision is made; run `/log-progress` at milestones.
- Windows host: use forward slashes; `PYTHONIOENCODING=utf-8 uv run lint-imports` (rich chokes on cp1252 when redirected).

## NEXT STEPS (Phase 2)
1. **Write four Phase 2 plans** (superpowers `writing-plans` skill), one file each under `docs/superpowers/plans/`, quoting the FROZEN signatures verbatim from `src/airport_agent/contracts/` (do not paraphrase from memory):
   - `2026-08-15-plan2a-data.md` — adapters (design 01 table incl. T-100 dom+intl, OTP, Delay Cause, Socrata, TAF, NPIAS, AIP, OurAirports, Census/BEA, CATS Form 127, nasstatus live, curated YAML; DB1B timeboxed), DuckDB store + `build_derived()` per registry, `DuckDBDataService`, refresh CLI + `--check`, snapshot (≤100MB), fixtures, `tests/data/conftest_plugin.py` registering the DuckDB factory + root `conftest.py` `pytest_plugins`. Note the fake's known deviations (horizon rule now honoured; unknown iata → KeyError; static/forecast series → []).
   - `2026-08-15-plan2b-scoring.md` — `config/scoring_presets.yaml`, scorer (percentile within peer group, renormalized weights, coverage/low_confidence), `DeterministicAnalyst` impl (rank/compare with percentiles/diagnose_unmet_demand with curated_facts), templated explanations, calculators (distance bands, long-haul share pax/freight), TDD against `FakeDataService`. `metric_contrib = w_p × w_m × pct × 100`. `peer_group=None` → "hub_class".
   - `2026-08-15-plan2c-agent.md` — `llm/` LiteLLM router (Gemini only; `LLMError` loud), `ToolRegistry` from `ToolSpec` (wrap in `{"type":"function","function":…}` for LiteLLM), Concierge (Plan structured output → tools/dispatch → synthesis per design 03 fixed structure), specialists runner + `config/specialists/*.md` (4), sessions (`data/sessions/*.json`), `answer()` entry point, golden tests for the 4 sample questions with a fake LLM.
   - `2026-08-15-plan2d-ui.md` — Streamlit multi-chat app per design 04, CLI harness `python -m airport_agent.ui.cli`, smoke tests with fake LLM + `FakeDataService`.
   Each plan: Global Constraints (frozen surface untouched; layering; product rules), file structure, bite-size TDD tasks with real code, self-review.
2. Create worktrees (`git worktree add ../aa-data feature/data`, etc.) and run the four plans in parallel via subagent-driven development, one ledger per plan; each task review includes the reviewer's frozen-surface Step 0. Any contract change request → DECISION NEEDED to the user (unfreeze protocol in design 05 §5.6).
3. Phase 3: merge in order data → scoring → agent → ui; integration on the real snapshot; `/eval-samples`; fix loop. Phase 4: `voice-engineer` on `feature/voice` (timeboxed), `doc-assembler` (DESIGN.md + the three standalone docs + README), `process-scribe`, zip checklist (design 06). Ship the zip with `.env` (Gemini key from a throwaway account), `.env.example`, `.claude/`, snapshot; exclude `.venv`, raw cache, sessions, `.git`.

## Memory
`C:\Users\palis\.claude\projects\C--Users-palis-Desktop-soft-projects-airport-agent\memory\` has `working-style-escalate-dont-improvise.md` and `airport-agent-methodology.md`; keep them current.
