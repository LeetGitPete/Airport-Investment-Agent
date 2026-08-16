# Runtime debug log — design (approved 2026-08-16)

## Problem
Rows 65–66 curated the user-facing answer surface: report caveats, quality flags, per-tool
coverage/truncation/limitation chatter, raw errors and pydantic diagnostics no longer reach the user.
That data still matters to whoever develops or debugs the agent. Before deleting the remaining raw
user-facing strings (tool-error cells, registry error text, "Why I stopped" prose, Show work's raw
args), a parallel dev-time log must capture everything, so nothing is lost.

## Decision
Structured JSONL, files only (human decision): `data/debug/<session_id>.jsonl`, one JSON object per
event. No UI panel, no stdlib-logging string records. Gitignored and excluded from the deliverable
zip, like `data/sessions/`.

## Module — `src/airport_agent/agent/debuglog.py`
- `class DebugLog`: `__init__(directory: Path)`; `log(session_id: str, turn: int, event: str,
  **payload) -> None`.
- Record shape: `{"ts": <iso8601 local>, "turn": <int>, "event": <str>, **payload}` — payload values
  must be JSON-serializable; non-serializable values pass through `str()` (`json.dumps(default=str)`).
- Append-per-write (open/write/close each call — Windows-safe, no held handles), `mkdir(parents=True,
  exist_ok=True)` on first write.
- NEVER raises: any I/O or serialization failure is swallowed after one `logging.warning`. A broken
  debug log must not fail a user turn.
- `class NullDebugLog` with the same `log` signature doing nothing — the default everywhere, so
  tests and one-shot CLI runs pay zero cost unless wired.

## Events (emitter → event → payload)
| emitter | event | payload |
|---|---|---|
| Concierge `_plan` | `plan_raw` | the raw plan dict + parsed filters dump (incl. presentation_notes, hint, source_turn, table_display) |
| Concierge `_run_tools` | `tool_call` | tool (raw id), args, rows, coverage, truncated, limitation, error (verbatim), data_quality_notes, latency_ms |
| Concierge `_recover_tool_args` | `tool_repair` | tool, original args, validation error, repaired args or null |
| Concierge `_from_memory` | `memory` | source_turn requested, hit ("archive" / "last_reports" / "none") |
| Concierge clarify paths | `error` | detail/diagnostic verbatim (pydantic prose, LLM error text) |
| Synthesizer `synthesize` | `answer_curation` | dropped_report_caveats (not allow-listed), quality_flag_count, analyst_assumptions_raw vs kept, analyst_caveats_raw vs kept, notes_condensed_from (count before cap) |
| SpecialistRunner | `specialist_result` | specialist, confidence, lens, disagreements, dropped evidence refs, hint_truncated |
| Compactor `compact`/`collect` | `compaction` | through_turn, retry_fired, truncated, chars_before, chars_after; on collect-error: the LLMError text |

## Wiring (no layering change — everything lives in `agent/` or is injected)
- `build_app` constructs `DebugLog(repo_root()/"data"/"debug")` and passes it down.
- `Concierge(..., debug=NullDebugLog())`, `Synthesizer(..., debug=...)`, `Compactor(..., debug=...)`,
  `SpecialistRunnerImpl(..., debug=...)` — optional kwarg, default Null.
- Concierge passes `state.session_id` + turn number; components that lack them receive them as
  `log()` arguments from their caller where needed.
- `.gitignore` += `data/debug/`; `scripts/make_zip.py` EXCLUDE: `data/debug/` added next to
  `data/sessions/`.

## Deletions unblocked (only after the log captures the raw data)
1. Tool-error table: cell text becomes plain ("No data found for that request." for KeyError-like;
   "That lookup couldn't be completed." otherwise); raw error only in the log + trace note.
2. Registry error strings/args-help and pydantic "Why I stopped" prose: mapped to plain sentences on
   the user surface; verbatim to the log via the `error` event.
3. "Show work" table: drops raw `tool` and `args` columns; keeps step (user-facing), rows, provider
   ("source"), latency_ms ("time (ms)"), note. Raw tool+args live in `tool_call` events.
4. (Pending separate approval) Scores table: drop `low_confidence` column, rename `coverage` →
   "data completeness".

## Testing
- Unit: record shape, append across calls, non-serializable payload, I/O failure swallowed,
  NullDebugLog inert.
- Integration (fakes): one analytical turn writes plan_raw + tool_call/deterministic + specialist_result
  + answer_curation; a failing tool writes tool_call with error AND the user surface shows only the
  plain sentence; compaction retry writes compaction with retry_fired.
- Existing lingo guards must stay green.

## Build plan
Subagent 1: module + unit tests. Then in parallel — Subagent 2: emitters + wiring + integration
tests; Subagent 3: user-surface softening (deletions 1–3) + tests. Orchestrator reviews, runs the
full suite, commits.
