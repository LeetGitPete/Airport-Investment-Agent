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
