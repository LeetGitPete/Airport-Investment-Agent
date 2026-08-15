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
