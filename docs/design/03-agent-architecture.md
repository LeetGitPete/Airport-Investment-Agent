# 03 — Conversational Agent, Deterministic Analyst & LLM Specialists (architecture)

Status: DRAFT (brainstorm 2026-08-15). Roster and synthesis format decided.

## Roles

| Role | Kind | Input | Output | Purpose |
|---|---|---|---|---|
| **Concierge** (conversational agent) | LLM + tools | user message + `SessionState` | `Plan` → tool calls / dispatches → `Answer` | Understand intent, choose tools/engines, filter & present, explain its choices, keep the conversation |
| **Data tools** | code | typed filters | compact JSON + provenance | Informational retrieval (facts, tables, series) |
| **Deterministic Analyst** | code | `AnalysisRequest` → `FeatureMatrix` | `DeterministicReport` | Rank / compare / diagnose by transparent formula; required by the assignment |
| **LLM Specialists** | LLM + tool subset | `AnalysisRequest` (+ ≤N-char hint) → `AirportProfile`s, routes, evidence bundles | `SpecialistReport` | Judgement, context, causal narrative, disagreement with the formula |
| **Synthesizer** | code + Concierge | `DeterministicReport` + `SpecialistReport` | `Answer` | Merge both views into one response (structure + agency, below) |

## Question classes → path

```
user msg ─▶ Concierge.plan()  ──▶ Plan{intent, filters, engines, show/why}  (shown to user before execution)
   intent = informational ─▶ data tools ─▶ Concierge presents (states what it filtered and why)
   intent = analytical    ─▶ AnalysisRequest ─┬─▶ Deterministic Analyst ─▶ DeterministicReport ─┐
                                              └─▶ LLM Specialist(s)     ─▶ SpecialistReport   ─┴─▶ Synthesizer ─▶ Answer
   intent = followup      ─▶ resolve against SessionState (last reports/airports/filters); re-dispatch only if needed
   intent = clarify       ─▶ ask one targeted question (e.g. which horizon / which preset)
```
Classification is not a separate model call: the Concierge's first LLM turn *is* the Plan (structured output).

## Shared filter vocabulary (all data tools and AnalysisRequest)
`horizon: 12m|3y|5y|10y` · `region: {state | faa_region | cbsa/metro | airports:[iata]}` · `hub_size` ·
`metrics: [metric_id]` (from registry) · `top_n` · `international: bool|None`. No free-form SQL or column names.
Every tool result carries `provenance: [source, vintage]` and `truncated: bool`; **analysis-tool results
additionally carry `coverage`** (the mean `ScoreRow.coverage` of the rows returned) — plain data tools do not,
since coverage is a property of a scored row set, not of a raw lookup.

## Contracts (sketch; authoritative in `contracts/`)
```
Plan { intent, engines: [deterministic|specialist:<name>|tools], filters, tools_to_call, presentation_notes }
AnalysisRequest { question_type: rank|compare|diagnose, airports|region filter, horizons, peer_group|None (None =
                  default hub_class), scoring_preset|None,
                  focus_metrics|None, hint: str  # truncated to MAX_HINT_CHARS (default 200); hint_truncated flag returned }
DeterministicReport { preset, weights, horizon, peer_group, table: [ref, score, rank, pillar & metric contributions,
                      coverage], percentiles (metric_id -> {iata: 0..1 within peer_group}), curated_facts: [CuratedFact],
                      explanation (templated, formula-driven), evidence: [Metric], caveats }
SpecialistReport { specialist, ranking/comparison view, narrative, evidence: [Metric], agreements/disagreements
                   with DeterministicReport (if provided), confidence, assumptions, caveats }
Answer { text, tables, citations, assumptions, uncertainty_notes, plan_shown, tool_trace }
SessionState { history, last_airports, last_filters, last_preset, last_reports (conversation memory for follow-ups) }
```

## Deterministic Analyst (code path)
Wraps `scoring/`: `rank(req)`, `compare(req)`, `diagnose(req)` (e.g. unmet-demand evidence bundle). Always
available (no LLM). Explanations are templated from contributions ("BDL ranks above PVD mainly on Demand Pressure
(+12): 5y enplanement CAGR 6.1% vs 2.3% …"). Definitions of presets/metrics come from 02.

## LLM Specialists (LLM path)
- Each specialist is a **config artifact** (`config/specialists/<name>.md|yaml`): system prompt = its slice of the
  metric registry + methodology + output schema; `allowed_tools` subset; default preset; max tool-loop turns.
- Dispatch is structured (`AnalysisRequest`), never a free-text handoff — low variance. The `hint` is the only
  free-text channel; its limit is stated in the dispatch tool description so the Concierge is terse by design.
- Specialist may call `score_airports` etc., so the deterministic numbers are in its context; it must cite evidence
  by metric id and vintage and separate "data says" from "my judgement".
### Roster (decided after 02)

| Specialist | Owns analyst questions (02) | Metric slice | Allowed tools | Default preset | Built-in caveats |
|---|---|---|---|---|---|
| `expansion_analyst` — composite "where to invest" ranking | Q1–2, 7, 21 + composite | all pillars (summary level) | `score_airports`, `get_profile`, `find_airports`, `explain_metric` | `terminal_expansion` / `balanced` | tier-B coverage; hub-class peer group; forecast optimism |
| `capacity_analyst` — congestion, constraint diagnosis, unmet demand & why | Q6–11, 16 | P2 fully + P1 absorption (LF, spill_proxy, upgauging) + curated capacity facts + NPIAS labels + live status | `compare_airports`, `diagnose_unmet_demand`, `get_profile`, `get_live_status`, `get_route_stats`, `explain_metric` | `congestion_relief` | spill model not LF cutoff; NPIAS circularity for slot airports; declared capacities from 2014–19 profiles; SNA legal cap |
| `market_analyst` — traffic mix, network, catchment, financeability | Q3–5, 12–15, 17–20, 22 | P3, P4, P5 | `get_route_stats`, `get_profile`, `compare_airports`, `find_airports`, `explain_metric`, `get_metric_series` | `market_entry` | CBSA≠catchment; Form 127 unaudited; long-haul = convention; pax vs freight |
| `general_analyst` — fallback when intent maps to no specialist cleanly | any | full registry | all tools | chosen per request or `balanced` | all of the above, plus "state which specialist lens you adopted" |

**`general_analyst` dispatch is wider but still structured:** `AnalysisRequest.extended = { hint ≤ 600 chars
(vs 200), question_type may be `custom`, optional `requested_sections`, optional ad-hoc `metrics` list, optional
`peer_group` override }`. Truncation and limits are stated in the dispatch tool description.

Each specialist = `config/specialists/<name>.md`: role, metric slice with definitions/thresholds/sources
(generated from `MetricSpec`s), methodology rules, caveats, output schema, allowed tools, max loop turns.
Adding a specialist is a config change.

### Sample-question routing
| Question | Intent | Engines | Specialist |
|---|---|---|---|
| Which New England airports are strong terminal-expansion candidates? | analytical / rank | Deterministic `rank(terminal_expansion, region=NE)` + specialist | `expansion_analyst` |
| Compare LAX vs SNA congestion | analytical / compare | Deterministic `compare(P2 set)` + specialist | `capacity_analyst` |
| % long-haul flights out of Anchorage | **informational** | `get_route_stats(ANC, bands, pax+freight)`; Concierge presents and offers a follow-up analysis | — |
| Unmet flight demand at SFO and why | analytical / diagnose | Deterministic `diagnose_unmet_demand(SFO)` + specialist | `capacity_analyst` |
| (unmapped, e.g. "is DEN's cargo growth sustainable?") | analytical / custom | Deterministic `compare/rank` as applicable + specialist | `general_analyst` |

## Tools & transport
Plain Python functions with JSON schemas in one `ToolRegistry`; the Concierge and each specialist receive named
subsets. Function calling via LiteLLM across all providers. Not MCP (optional FastMCP wrapper for external
clients later), not Claude Code "skills" (dev-time concept). Tool args are pydantic-validated; validation errors
return a helpful message so the model self-corrects.

## Presentation & transparency (product behaviour, required by assignment)
- Plan shown before execution ("How I'm approaching this: analytical · terminal expansion · New England ·
  horizon 5y · engines: deterministic + specialist").
- Concierge states what it filtered/omitted and why; offers to expand.
- Every number cites source + vintage; every answer lists assumptions and uncertainty notes (from data-quality
  flags, coverage, and specialist confidence).
- Disagreements between formula and specialist are surfaced, not hidden.

## Call budget & rate limits
Analytical question ≈ Plan (1) + specialist loop (2–4) + synthesis narration (1) = 4–6 LLM calls; informational
≈ 2. Gemini free tier ~10 RPM ⇒ ~2 analytical q/min. Mitigations: follow-ups reuse SessionState.last_reports
instead of re-dispatching; compact tool schemas. No cross-request caching of LLM outputs. Extra providers only if time remains.

## Failure policy (no silent degradation)
- Resilience = LiteLLM retries/cooldowns on the configured provider(s). **For now only Gemini is configured**;
  additional fallbacks (Groq, NIM) are an optional later addition via `config/providers.yaml`.
- If every provider fails for a step that needs the LLM, the app **fails loudly**: a built-in message names the
  provider(s) and status ("LLM provider error — gemini: 429 quota exceeded; groq: 401 invalid key. Check the API
  keys in `.env`, your quota, or add a fallback in `config/providers.yaml`."). No partial deterministic output is
  presented as an answer. All questions pass through the Concierge, so no LLM ⇒ no answers, by design.
- Specialist timeout/error after retries ⇒ same loud error (the DeterministicReport is kept in the tool trace for
  debugging, not shown as the answer).
- Live data adapters down ⇒ snapshot used and the answer says so (this *is* acceptable degradation — data
  freshness, not reasoning).
- The deterministic engine remains independently callable from code/CLI for testing; it is not a user-facing fallback.

## Answer synthesis — "structure + agency" (decided)
Fixed structure (code-enforced, order fixed): 1 Plan line · 2 Headline (Concierge, 1–2 sentences) · 3 Evidence
block (DeterministicReport rendered verbatim — table, contributions/side-by-side, coverage, source+vintage per
number; the LLM cannot alter numbers) · 4 Analyst view (SpecialistReport narrative + explicit agreement/
disagreement line vs the formula) · 5 Assumptions & uncertainty (preset, horizon, peer group, conventions used,
data-quality notes, tier-B gaps, specialist confidence — from structured fields) · 6 Suggested follow-ups.
Concierge agency within it: writes headline/connective text; chooses which evidence rows/metrics to surface (rest
collapsed) and states what it hid and why; quotes vs summarizes the specialist; adapts length to question type.
It cannot change numbers, drop the assumptions block, hide a disagreement, or omit citations.
Informational answers: headline · value/table with provenance · conventions used · follow-ups.

Table display across turns (contracts-v2, 2026-08-16): a table's identity is a content hash (columns + rows,
not title/footnotes) kept in `SessionState.shown_tables` with the answer turn where it first appeared in full.
A table with identical content later in the session (typically a follow-up answered from memory, which rebuilds
its tables from the same reports) renders as a one-line pointer to that turn instead of the grid; different rows
show in full. The Concierge steers only the mode via `Plan.table_display`: `auto` (the rule), `repeat` (the
user asked to see it again — everything in full, pointer targets unchanged), `minimal` (a narrow follow-up —
pointers as in auto, and NEW tables go behind a collapsed data section so prose leads). No mode drops a number.

Conversation memory (contracts-v3, 2026-08-16). A TURN is a user message plus its reply, numbered by reply.
Every LLM call that needs the conversation (planner, synthesis) gets the same `session_context`: the compacted
`SessionState.summary` of older turns, the last 5 turns verbatim as fixed-form digests (`agent/history.py`:
question, headline, analyst view, agreement, each table as title + first rows), and an index of
`report_archive` (turn → that turn's reports) so a follow-up can name `source_turn` and be answered from ANY
earlier analysis, not only the last. Compaction (`agent/compaction.py`) runs after every 2nd answer when a turn
has left the verbatim window: one LLM call folds those digests into the summary, capped at 1,500 chars — one
retry with "summary is X chars, only Y chars are allowed", then a silent truncation at a sentence boundary. It
runs in the background between turns (only the LLM call is off-thread; digests are snapshotted on the turn and
the result is applied by `collect()` at the start of the next turn, which blocks on it), so the session has one
writer and a plan is never made against a moving summary. A provider error keeps the old summary; the CLI
(one-shot) never compacts.

## Testing
- Concierge: golden Plans for the four sample questions + 6 follow-ups (structured-output assertions).
- Deterministic Analyst: unit + golden ordering tests (see 02).
- Specialists: schema-validity tests with a fake LLM; one recorded live smoke test per specialist.
- Synthesizer: contract tests on merge rules once format is decided.

## Deferred decisions
None — roster and synthesis format decided (see above). Worked examples for the four sample questions will be
produced during implementation as golden tests.
