---
name: log-progress
description: Dispatch the process-scribe subagent to update docs/process-log.md from the raw hook feed, git log and agent reports. Use at milestones.
---
1. Collect: `docs/process-log.raw.jsonl` (new lines since last scribe run — the scribe records the last ts it
   consumed at the bottom of process-log.md as `<!-- scribe-cursor: TS -->`), `git log --since <that ts> --stat`,
   any agent final reports pasted by the user/orchestrator, `git diff` of the limitations log.
2. Dispatch the `process-scribe` agent with those inputs and the milestone name.
3. Show the appended section to the user.
