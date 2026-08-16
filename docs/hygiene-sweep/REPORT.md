# Hygiene sweep — final report

Branch `chore/hygiene-sweep`, worktree `C:\Users\palis\Desktop\soft-projects\aa-hygiene`, based on
`main` @ 335c81d. Ten commits, each one package or one coherent cleanup, each independently droppable.

## Coverage

| | |
|---|---|
| Files in the inventory | **182** (`docs/hygiene-sweep/CHECKLIST.md`) |
| Files reviewed | **182** — zero `pending` rows |
| Files changed | 86 |
| Net | +973 / −564 lines |
| Findings logged, not fixed | **8** (`docs/hygiene-sweep/FINDINGS.md`) |

Breakdown: `src/` 76 files (contracts 11 read-only, data 30, scoring 7, llm 4, agent 16, ui 7, root 1),
`config/` 8, `scripts/` 1, `conftest.py`, `tests/` 95.

### Verification

Run after every commit; the state below is HEAD.

```
uv run pytest         820 passed, 9 deselected (network), 0 skipped — 56s
uv run ruff check .   All checks passed!
uv run lint-imports   Contracts: 4 kept, 0 broken (76 files, 195 dependencies)
```

Baseline on `main` was 832 collected / 9 deselected → 823 selected: **822 passed + 1 skipped**. Three
tests were removed deliberately (all justified below), giving 820. No test was weakened, and no test
was deleted for failing — nothing failed at any point in this sweep.

> Correction to the earlier commit messages on this branch: they say "823 passed … 1 skipped". The
> accurate baseline is 822 passed + 1 skipped. The commit bodies overcount passes by one; the code
> they describe is unaffected.

## Trivial fixes applied, by category

| Category | n | Examples |
|---|---:|---|
| Comment hygiene (narrative/changelog → durable reason) | ~120 | `QA task N`, `human decision <date>`, `RESCOPE (Option A Core-6)`, `Phase 2/3`, plan-document cross-refs, branch names. Every rationale kept, rewritten as *why* rather than *when*. `MISSING_REASONS` now says why a metric has no data, not which decision dropped it. |
| Decorative separators removed | 25 files | Full-width `# ----` rules deleted; `# --- label ---` reduced to `# label`, label text kept. |
| Dead code deleted | 9 | `sidebar._render_provider` / `_render_vintages` / `_render_defaults` (+3 option lists, unused `pandas` import); `render.metric_ids_in_table` + `_MAX_METRIC_DEFINITION_LINES`; `tables.comparison_table` alias; `p3_market._with_partial_window_flag`; `service._CAPACITY_LABEL_TEXT`; `refresh._ENRICHMENT_SOURCES`; unreachable `return 2`s in `data/__main__.py`. |
| Unreachable / wrong branches | 2 | `analyst._expand_to_peers`'s `else None` (unreachable, and `AirportFilter(hub_sizes=None)` raises); the `args.command != "refresh"` guard argparse already enforces. |
| Magic numbers named | 5 | `LONG_HAUL_MI`, `NPIAS_PLAN_PERIOD`, `NPIAS_PLAN_YEARS`, `_MIN_MONTHS_PER_ROUTE`, `_ALL_ROUTES`. |
| Duplication removed | 3 | `NEW_CHAT_TITLE` (concierge now imports the one `sessions` defines — they must agree); `FakeAnalyst.rank/compare/diagnose` → one `_report()`; duplicate `test_schema_is_portable`. |
| Resource / robustness | 2 | `refresh()` closes its DuckDB connection in a `finally`; `_print_staleness_table`'s `max()` got a `default`. |
| Imports moved to module scope | 4 | `calendar`/`os` in three adapters, `hashlib` in `bts_socrata` (`faa_taf` already did this correctly). |
| Type hints / signatures | 2 | `_print_refresh_report(report: RefreshReport)`; `LiteLLMClient._key(i=0)` → `_primary_key()` (the index was only ever 0). |
| Stale docstrings corrected | 5 | `sidebar` / `streamlit_app` advertised three panels the UI does not render; `fit_tool_result` promised a character cap its fallback cannot honour; `app.MISSING_LAYER` cited a build phase since completed. |
| Test hygiene | 6 | Removed a duplicate test, a skipped empty-bodied stub, and a test of deleted code; replaced an `__init__.__defaults__` tuple comparison with a named `inspect.signature` check; dropped a `time.sleep` made redundant by the `os.utime` beside it; renamed two tests whose names claimed more than they check. |

## Findings — logged, NOT fixed

Full text with options and recommendations in `docs/hygiene-sweep/FINDINGS.md`.

| Id | Severity | Summary |
|---|---|---|
| **F-006** | **high** | `docs/DESIGN.md` does not exist, yet `scripts/make_zip.py` checks for it (and exits 1), the Streamlit sidebar links to it, and design 04/06 require it. The assignment's design deliverable is missing. |
| F-001 | medium | `otp_peak`'s zero-fill grid uses every day seen across *all* months in a refresh, so a 28-day February is padded with 72 hours that never existed. Reproduced: identical February data yields `p95_hourly_ops` 1.0 alone vs 0.0 refreshed with March. Feeds the scored `peak_hour_ops_ratio`. |
| F-002 | medium | The sidebar renders neither provider status, data vintages, nor the per-chat default pickers, all of which design 04 lists — and no limitations-log row records the removal. |
| F-005 | medium | `terminal_expansion` puts weight 3.0 on `pax_per_gate` and `deps_per_gate_day`, which have zero rows for every airport. 48% of its P2 weight lands on absent metrics, so after renormalization the preset's stated gate emphasis is gone. |
| F-007 | medium | `get_routes` orders by `departures DESC` with no tie-break and then truncates, so route-table *membership* depends on DuckDB's execution order. 252 airports have a tie straddling the default `top_n=10`. |
| F-003 | low | `ProvenanceSpec.derived(reason)` validates "a reason the user can read" that no code ever renders. |
| F-004 | low | Synthesis slices follow-ups `[:4]` while the schema instructs the model to return exactly 3. |
| F-008 | low | The `llm` pytest marker is registered but unused: design 03's live specialist smoke tests were never written, so the real provider path has no test coverage. |

## What I deliberately did not touch, and why

**Frozen by contract.** `src/airport_agent/contracts/**` and `config/metrics.yaml` were read in full and
changed in no way. Both are clean: `contracts/` is pure types and Protocols with unusually good docstrings
on the horizon rules, and `metrics.yaml`'s comments are factual. Neither produced a finding.

**Behaviour-visible changes.** The rule applied throughout: if a "cleanup" would change what a user sees,
it is a finding, not a cleanup. That is why F-001, F-004, F-005 and F-007 are logged rather than applied —
each has a one-line fix I would otherwise have made.

**Documented tradeoffs, verified before flagging.** The limitations log has 54 rows and I checked candidate
findings against it. Several things that looked wrong are recorded decisions and were left alone:
mtime-as-vintage (row 45), `PRESET_NAMES` duplicating the preset YAML (row 27), the frozen contract suite's
`ATTEMPT_IDS` still permitting the now-landed `aip_per_enpl_10y` to be absent (row 47 makes editing that
suite a human decision), the ~2–3k-token specialist prompts (row 36), and percentiles computed against the
whole universe (row 30).

**Cross-layer duplication that is duplication by design.** The long-haul 1,500-mile constant exists
separately in `data/`, `scoring/` and `agent/tools/`; the NPIAS label map exists in `data/service`,
`data/adapters/faa_npias` and `scoring/analyst`. Merging any of these would need a cross-layer import the
architecture forbids. I deduplicated only *within* a layer, and left a cross-reference comment where two
constants must track each other (`common.NPIAS_PLAN_PERIOD` ↔ `faa_npias.NPIAS_PLAN_YEARS`).

**Considered and rejected as churn.** ~20 in-function imports in test files are a consistent convention
there, and ruff does not flag them — unlike the four in `src/` I did move, which were inconsistent with a
sibling adapter doing the same thing at module scope. `REPORT_TOOLS` is defined in both `agent/tables.py`
and `agent/specialists/runner.py`; unifying one three-element tuple would add an import edge for no real
gain. `tests/agent/test_concierge.py` imports private helpers from three sibling test modules — a mild
coupling smell, but extracting a shared scripts module is a restructure, not hygiene.

**Checked and found sound** (recorded so the negative result is not re-derived): `percentile_rank`'s float
`==` is exact tie detection, which is correct there, and the shipped snapshot holds zero NaN/inf metric
values; every `fmt_value` unit branch is reachable from the registry, and the only unhandled unit
(`category`) belongs to a tier-C metric that always returns `n/a` first; `runways.closed` is never NULL, so
`ops_per_runway`'s `closed = FALSE` filter drops nothing; no test lacks an assertion; all 9 network tests
carry `@pytest.mark.network` and no test reaches a live LLM; session- and module-scoped fixtures share only
frozen models and read-only connections.

**Dates kept where they are evidence.** "Verified 2026-08-16 against the real June 2026 file" in the adapter
docstrings records when a wire format was last confirmed against a live source — durable provenance, not a
changelog entry, and the only thing telling a future maintainer how stale that verification is. Fixture
timestamps are test data. Both were left in place.

**Not mine to touch.** `.claude/hooks/` and `docs/process-log.raw.jsonl` per the brief. `docs/design/*` was
read as the source of truth but never edited — where code and design disagree (F-002, F-006), that is
escalated rather than reconciled.

## Merge note

`src/airport_agent/agent/planner.py` has **uncommitted work in the main worktree** (QA task 19:
conversational clarify kinds, ~59 added lines). This branch also edits `planner.py` — comment hygiene in
seven places. The edits are in different regions and should merge cleanly, but that file wants attention
rather than a blind resolution.
