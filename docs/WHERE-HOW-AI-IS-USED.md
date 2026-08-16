# Where and How AI Is Used

Two separate stories: the AI **inside the product** at runtime, and the AI that **built the product**. Both are
deliberately bounded, and in both the rule is the same — the model reasons, the code owns the numbers.

---

# Part 1 — Runtime

## The one path every message takes

```
user message
   |
   v
Concierge.plan()            1 structured LLM call  ->  Plan {intent, engines, filters, tool_calls, specialist}
   |                                                    (shown to the user before anything executes)
   +-- intent = informational --> data tools (code) ------------------------+
   +-- intent = analytical -----> Deterministic Analyst (code, no LLM) --+  |
   |                          \-> LLM specialist (bounded loop) --------+|  |
   +-- intent = followup -------> reuse SessionState.last_reports -------+  |
   +-- intent = clarify --------> one targeted question, no engines         |
                                                                            v
                                                   Synthesizer  1 LLM call -> Answer
                                                   (fixed structure, code-assembled)
```

**1. Plan (1 LLM call).** Intent classification is not a separate model call — the Concierge's first turn *is*
the Plan, emitted as structured output against a portable JSON schema. The Plan names the intent, the engines,
the filters (region / airports / hub size / horizon / preset / peer group / focus metrics), the exact tool calls
with their arguments, and the specialist if any. It is rendered to the user as a plan line *before* execution, so
what the agent is about to do is visible and challengeable.

**2. Dispatch (no LLM).** Code executes exactly what the Plan asked for:

- **Data tools** (retrieval, compact JSON + provenance): `find_airports`, `get_profile`, `get_route_stats`,
  `get_live_status`, `explain_metric`, `get_metric_series`, `list_sources`.
- **Analysis tools / the Deterministic Analyst** (pure code): `score_airports`, `compare_airports`,
  `diagnose_unmet_demand` — the rank / compare / diagnose methods described in `docs/SCORING-METHODOLOGY.md`.
- Every tool has a pydantic argument model and a JSON schema. There is **no free-form SQL and no column names**
  in the model-facing surface; invalid arguments come back as a readable error the model can correct, and the
  error stays in the trace.

**3. LLM specialist (bounded loop, then one structured report).** A specialist is a *config artefact*, not code:
`config/specialists/<name>.md` carries its role, its slice of the metric registry (full definitions, formulas,
tiers, sources, caveats), its methodology rules, its allowed tool subset, its default preset and its loop budget.
Four exist — `expansion_analyst`, `capacity_analyst`, `market_analyst` and a `general_analyst` fallback. Dispatch
is a validated `AnalysisRequest`, never a free-text handoff; the only free-text channel is a hint capped at 200
characters (600 for `general_analyst`). The runner allows at most `max_turns` tool-calling turns (2 for the three
focused specialists, 3 for `general_analyst`) and then demands the final report as JSON matching the schema. The
specialist cites evidence as `(iata, metric_id)` refs, and **code** resolves those refs against what the tools
actually returned: an unresolvable citation is dropped and reported in the caveats rather than taken on trust.

**4. Synthesis (1 LLM call).** The answer structure is code-enforced and fixed in order: plan line, headline,
evidence tables, analyst view with an explicit agreement/disagreement line, assumptions and uncertainty, and
follow-ups. Tables, citations and the assumptions block are built by `agent/tables.py` from the reports — never
by the model. The model's agency inside that structure is: the headline, the analyst summary, *which* metric rows
to surface (plus a one-line reason for what it collapsed), and the follow-up suggestions.

## What the LLM may and may not do

| May | May not |
|---|---|
| Choose the intent, the engines, the filters and the horizon | Alter, re-round or re-derive any number — every table is built by code from the reports |
| Choose a scoring preset **by name** from `config/scoring_presets.yaml` | Invent a preset or change a weight |
| Decide which evidence rows to surface, and say what it hid and why | Hide a disagreement between the specialist and the formula — the agreement line is a required field |
| Write the headline, the narrative and the follow-ups | Omit the assumptions and uncertainty block, or the citations |
| Say "not available" and explain a documented gap | Estimate a metric that did not land, or attribute a number to a source that did not produce it |
| Ask one clarifying question when the request has no target | Silently guess a target when planning fails |

## Call budget and rate limits

| Question type | Calls |
|---|---|
| Informational (e.g. the Anchorage long-haul question) | ~2 — Plan + synthesis |
| Analytical | 4-6 — Plan (1) + specialist loop (<=3) + specialist final report (1) + synthesis (1) |
| Follow-up answered from session memory | ~2 — Plan + synthesis, reusing `last_reports` |

The Gemini free tier allows roughly 10 requests per minute, so about two analytical questions per minute.
Follow-ups reuse `SessionState.last_reports` instead of re-dispatching; tool schemas and tool results are kept
compact (tool payloads are truncated to a character budget before entering a prompt).

## Failure policy — no silent degradation

- One provider is configured (Gemini free tier, model name from `config/providers.yaml`, key from `.env`).
  Resilience is LiteLLM retries; the router supports fallbacks, and adding Groq or NVIDIA NIM is a config entry
  plus a key.
- If a step that needs the LLM fails, the app **fails loudly**: an `LLMError` naming the provider and the status
  ("gemini: 429 quota exceeded"), surfaced as an error in the UI and a non-zero exit in the CLI. **No partial
  deterministic output is dressed up as an answer.** The deterministic engine remains callable from code and
  tests, but it is not a user-facing fallback.
- A specialist that returns a malformed report raises rather than returning a partial or invented one. The single
  exception is cosmetic: if the *synthesis* JSON fails to parse, the answer is still assembled from the reports
  with the note "synthesis text unavailable - showing raw report" — formatting degrades, reasoning does not.
- **No cross-request caching of LLM outputs or reports.** Conversation memory (`last_reports`) is scoped to a
  session and is a memory of what was computed for that user, not a cache keyed by question. The only cached
  object is the `App` itself (process-level wiring).
- Live data adapters going down *is* acceptable degradation: the snapshot is used and the answer says so.

## Portable structured output

`PLAN_SCHEMA`, `SPECIALIST_SCHEMA` and `SYNTHESIS_SCHEMA` are deliberately restricted JSON-schema subsets —
`type`, `properties`, `required`, `items`, `enum`, `description` only, with `"none"` / `[]` / `""` as unset
sentinels that code maps back to None. No `anyOf`, `oneOf`, `$ref`, `additionalProperties` or `nullable`; a test
asserts those keywords never appear. The cost is that every field is required and unset values need sentinels;
the benefit is that the same schemas work on any structured-output provider we might add later.

*Implementation note:* design 00 sketched a model-callable `dispatch_analysis` tool. As built, dispatch is a
`specialist` field on the Plan that code acts on, which is stricter — the model declares who should analyse in
the same structured call it declares everything else, rather than deciding mid-loop.

---

# Part 2 — Dev-time

The repository is also an artefact of *how* it was built. `.claude/` contains the project's own agent-facing
spec (`CLAUDE.md`), nine subagent definitions, four hooks and three skills.

## Process shape

- **Design before code.** An interactive brainstorming session produced `docs/design/00-06` plus a living
  limitations log. Those documents — not the chat history — are the source of truth, and every agent reads them.
- **Frozen contracts first.** Phase 1 wrote and froze `contracts/` (pydantic models plus `typing.Protocol` ports)
  and the metric registry `config/metrics.yaml`, tagged `contracts-v1`. Only then did parallel work start, so no
  workstream could invent a field or a metric id.
- **Worktrees for parallelism.** Phase 2 ran four workstreams (data, scoring, agent, ui) in separate git
  worktrees on separate branches. The only shared surface was the frozen contracts and registry; anything else
  had to be escalated rather than negotiated across branches.
- **A review gate per task.** A fresh implementer subagent per task, a reviewer after each task, a scoped
  re-review after each fix round, and a ledger per plan. Six of the ten Phase-1 tasks needed exactly one fix
  round.
- **Escalation over improvisation.** Anything ambiguous, off-design, or introducing a new tradeoff had to STOP
  and return a `DECISION NEEDED` block (what, why it matters, 2-3 options, recommendation, what is blocked). The
  orchestrator relayed those to the human verbatim and waited. Design-relevant questions were never resolved on
  the human's behalf.
- **Mechanical guardrails, not vibes.** Hooks block commits that stage `.env` or key-like files, block edits to
  frozen contracts unless explicitly unfrozen, and run `ruff` plus `import-linter` on every write under `src/`.
  Four import-linter contracts encode the layering (contracts imports nothing; data/scoring/llm/ui are mutually
  independent; ui reaches the rest only through agent; lower layers never import the composition root).

## Model per role

| Phase | Work | Model | Gate |
|---|---|---|---|
| Design | Architecture brainstorm with the human; three research notes (LLM providers, aviation data sources, investment metrics) | Opus-class, research agents dispatched in parallel | Human review of each design document |
| 1 Freeze | Subagent specs and skills (pure transcription) | Haiku | Task reviewer + fix round |
| 1 Freeze | Contracts, hooks, tooling, import-linter config | Sonnet | Task reviewer per task; fix rounds on 5 of 9 |
| 1 Freeze | `FakeDataService` (horizon semantics, factory extension) and the whole-branch freeze review | Opus | Freeze gate -> human decision -> scoped re-review |
| 2 Workstreams | Adapters, store, derived metrics, scorer, analyst, router, tools, Concierge, specialists, Streamlit UI | Sonnet implementers (Opus where source-format verification was needed) | Reviewer per task; after the rescope, diff-only Sonnet reviewers with one Opus whole-branch review per workstream |
| 3 Integration | Merge data -> scoring -> agent -> ui, real snapshot, wiring fixes, golden runs | Controller inline (Opus) | Full gate: ruff, import-linter, pytest |
| 4 Deliverables | This documentation set, the process log, the zip builder | Opus | Human review |

The rule: architecture and judgement to the strongest model, well-specified implementation to a mid model, pure
transcription to the cheapest, upkeep to whatever is idle.

## The rescope — an honest course correction

Halfway through Phase 2 the *process* was consuming more budget than the code: roughly four to five agent
dispatches per task (implementer, reviewer, fix round, re-review), with reviewers re-running full gates each
time. At the projected rate the remaining work needed ~150 dispatches. Rather than quietly cutting quality, the
options were written up (`docs/superpowers/RESCOPE-2026-08-15.md`) and put to the human as a decision with three
scoped alternatives. The chosen option, "Core-6", kept six data sources and cut five, and changed the process:
diff-only reviewers, fix rounds only for Critical/Important findings, batched tasks, one whole-branch review per
workstream. Everything it cut is recorded per metric id in `docs/KEY-TRADEOFFS.md` and returns zero rows with a
stated reason in code, so the product tells the truth about what it no longer knows.

## What AI got wrong, and what we did about it

An honest list, mined from the build's raw hook feed, the git history and the review ledgers. (The scribe's
running narrative is a dev-time artifact and is not shipped — design 06; this section is what it was for.)

1. **A research agent died on a spurious safety-filter error** and had to be relaunched on a different model — a
   practical reliability note for anyone running multi-agent research.
2. **A research agent self-corrected mid-run on three factual points**: the 60%/80% ASV planning trigger lives in
   FAA Order 5090.5 (not the advisory circular everyone cites), neither ICAO nor IATA publishes a long-haul
   distance cutoff, and ACI benchmarks are per *passenger* while airport financials are per *enplanement*. All
   three would have produced confidently wrong metrics. They are why the long-haul threshold is presented as our
   stated convention.
3. **The freeze gate returned NOT READY.** An Opus review of the whole contracts branch found `peer_group`
   missing from `AnalysisRequest` and `curated_facts` / `percentiles` missing from `DeterministicReport`. It was
   relayed verbatim; the human chose "amend now, then freeze". Catching this before the freeze saved four
   worktrees from rebasing.
4. **Most Phase-1 review findings were plan defects, not typos**: an import-linter rule that forgot the agent
   layer, an `ALLOW` bypass in the secrets guard, before-validators crashing on `None`, a no-op test assertion, a
   fixture snapshot that silently broke the `DataService` factory-extension mechanism, and `get_feature_matrix`
   horizon semantics left undefined — which the fake had "solved" by inventing horizon variants. The reviews were
   catching specification gaps, which is the argument for having them at all.
5. **The import-linter config was over-restrictive**, forbidding `ui` from importing `agent` even though design
   04 requires exactly that. The lint failed honestly and the contract was corrected to match the design, not the
   design to match the lint.
6. **A scoring golden test asserted a percentile of exactly 1.0** that the fake's own fixture data could not
   produce — a slip inherited from the task brief. The implementer stopped and escalated instead of "fixing" the
   test blind; the assertion became a relative ordering (BOS above PVD/MHT), which is what the design actually
   claims.
7. **Briefs occasionally contradicted the fixtures or the frozen docstrings** (the case above; a horizon
   relabeling that would have contradicted the `get_feature_matrix` contract). The standing rule became: if a
   brief and a frozen contract disagree, STOP and escalate — never silently pick one.
8. **The Streamlit sidebar picked the wrong conversation.** `st.radio` deserializes a click by its *display
   label*, so two chats with the same title resolved to the same session. Fixed by making the options session ids
   with a `format_func` for display, plus guards for the delete race and blank renames. Separately, rendering a
   live turn inline and then rerunning was untestable under Streamlit's `AppTest`; the app now renders every turn
   from history through one path (tradeoff row 39).
9. **A frozen test suite was edited unilaterally.** Two assertions in the frozen contract suite were provably
   unpassable once a real DuckDB implementation registered itself. The fix was right, the process was wrong —
   it needed a human decision first. The breach is recorded as tradeoff row 47 and was ratified retroactively
   after the human reviewed the diff, rather than being quietly absorbed.
10. **Hooks that were not actually running.** The guard hooks were created mid-session and were not active in the
    session that created them; a frozen-file edit went through. Mitigation was a reviewer "Step 0" that
    git-verifies the frozen surface in every diff — belt and braces beat trusting the automation you just wrote.
11. **Two external surprises, absorbed honestly, not papered over.** The T-100 International Segment table code
    could not be found after a timeboxed probe of fifteen candidates, so route-level international data is
    absent and the fallback is documented (tradeoff row 2). And the configured Gemini model was retired for new
    accounts mid-build (a 404), so `config/providers.yaml` now pins the Google-maintained `-latest` alias.

**Verification status, stated plainly.** The deterministic engine, the tools, the planner, the specialist runner,
the synthesizer and the UI are covered by 749 automated tests that run offline against a fake LLM and the real
snapshot. The live Gemini path was exercised end to end through the CLI; the wiring is verified, and the run
also exercised the loud-failure policy for real when the free-tier key hit its quota — a 429 produced the named,
actionable error and no partial answer, exactly as designed.
