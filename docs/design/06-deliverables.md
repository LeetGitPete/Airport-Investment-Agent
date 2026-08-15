# 06 — Deliverables & Documentation Plan

Status: DRAFT (brainstorm 2026-08-15).

## What is sent (zip; reviewer receives files, not the repo link)
Included: `src/`, `config/`, `data/snapshot/` (DuckDB, ≤100MB), `data/curated/`, `tests/`, `docs/`, `.claude/`,
`pyproject.toml` (+ `requirements.txt` export), `.env` (throwaway-account Gemini key + optional Groq/NIM keys),
`.env.example`, `README.md`.
Excluded: `.venv/`, raw download cache, `data/sessions/`, `.git/`.
A `scripts/make_zip.py` (or `/make-zip`) produces it and prints a checklist: hidden dirs included, only the intended
`.env` present, snapshot present, app boots from the extracted folder.

## Documents
- `README.md` (~10 lines): what it is; `uv sync` (or `pip install -r requirements.txt`) → `streamlit run
  src/airport_agent/ui/streamlit_app.py`; the four sample questions; where DESIGN.md is; note that the key is a
  throwaway and will be revoked.
- `docs/DESIGN.md` — the required short design/architecture document, **assembled** by `doc-assembler` from
  `docs/design/*`, target 4–6 pages:
  1. Problem, scope, assumptions (00, limitations)
  2. Architecture (diagram from 00; contracts; runtime roles from 03)
  3. **Scoring methodology** (02: derivation questions → metrics → data; registry summary; normalization within hub
     class; presets; conventions; sensitivity table)
  4. **Key tradeoffs** (limitations log, Constraint vs Decision)
  5. **Where/how AI is used** — runtime (Concierge, specialists, provider chain, what the LLM may/may not do) and
     dev-time (agents, models per task, review gates, escalation protocol) — from the scribe's table
  6. Assumptions/uncertainty/scoping as product behaviour (Plan line, evidence, assumptions block, loud failures)
  7. What we would do with more time
  Detailed `docs/design/*`, `docs/research/*` and `docs/process-log.md` remain as appendices/evidence.
- `docs/process-log.md` — the AI-native build narrative (scribe).
- `docs/research/*` — the three research notes (LLM providers, data sources, investment metrics).

## Definition of done
- `/eval-samples` green: four sample questions + ≥6 scripted follow-ups produce structurally valid answers with
  correct key numbers against golden files.
- App runs from the extracted zip on a clean machine with only the shipped `.env`.
- DESIGN.md covers the three required sections; limitations log has no `Open` row without an outcome; process log
  has entries through the final milestone; `.claude/` contains CLAUDE.md, agents, hooks, skills as designed.
- Pushed to GitHub `main` (backup); zip produced by the script.
