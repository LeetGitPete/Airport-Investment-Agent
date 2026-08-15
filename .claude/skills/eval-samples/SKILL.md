---
name: eval-samples
description: Run the four assignment sample questions plus scripted follow-ups through the CLI and compare with golden files. Use before merges and before delivery.
---
1. `uv run pytest tests/golden -q` (structure + key-number goldens; requires GEMINI_API_KEY for the LLM parts —
   if missing, run only `-m "not llm"` and say so).
2. For each of the four sample questions run `uv run python -m airport_agent.ui.cli "<question>" --json` and
   check: Plan present, evidence table with source+vintage per number, assumptions block, no altered numbers.
3. Report a pass/fail table and diffs; never edit goldens without a human decision.
