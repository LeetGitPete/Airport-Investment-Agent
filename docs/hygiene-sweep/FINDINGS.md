# Hygiene sweep — findings (non-trivial, NOT fixed)

Everything here is deliberately **not fixed**: it is ambiguous, off-design, behaviour-changing, in a frozen
file, or otherwise a human's call. Trivial fixes were applied directly and are listed in `REPORT.md` instead.

Format per the project escalation protocol: what · why it matters · options · recommendation · blocked.

### F-001 — `otp_peak` day-grid spans every month in the refresh, not each month's own days   [severity: medium] [src/airport_agent/data/adapters/bts_otp.py:299]
what:            `_peak_frame` builds ONE zero-fill grid for all periods in the call:

                     days = sorted(raw["DayofMonth"].unique())
                     grid = pd.MultiIndex.from_product([days, HOURS_IN_DAY], ...)
                     for (iata, period), group in hourly.groupby(["iata", "period"]):
                         merged = grid.merge(group[...], how="left")
                         merged["ops"] = merged["ops"].fillna(0)

                 `refresh._ingest_one` fetches every month of the trailing window and calls
                 `normalize(all_paths)` once, so `raw` spans ~12 months and `days` is always
                 1..31. A 28-day February is then zero-filled over 31x24 = 744 hour-slots
                 instead of its own 28x24 = 672 — 72 phantom idle hours that never existed.
                 Reproduced on synthetic data: identical February input yields
                 `p95_hourly_ops = 1.0` when February is refreshed alone and `0.0` when
                 February and March are refreshed together.
why it matters:  `p95_hourly_ops` feeds `peak_hour_ops_ratio` (tier B, P2), a scored metric.
                 The phantom zeros drag the 95th percentile down, so short months look quieter
                 than they were and the airport reads as less capacity-constrained. The size of
                 the error depends on which months happen to be in the refresh window, so the
                 same airport's stored number changes with refresh scope rather than with data.
                 It is a wrong number, not a missing one — nothing flags it.
options:         1) Build the grid per period from that period's own days
                    (`group["DayofMonth"].unique()`, or a calendar month-length lookup).
                 2) Derive the day set per period inside the groupby from `raw`, keeping one
                    grid per (period) rather than one global grid.
                 3) Leave as-is and document it as a known approximation in the limitations log.
recommendation:  Option 1 — it is the smallest change and makes the metric independent of
                 refresh scope, which is the property that is actually broken. It changes stored
                 values for every short month, so it needs a snapshot rebuild and a golden
                 refresh; that is why it is logged here rather than fixed in this sweep.
blocked:         nothing — `peak_hour_ops_ratio` is computed and scored today; this changes its
                 value for affected airports.

### F-002 — the sidebar drops three panels design 04 requires, and no doc records it   [severity: medium] [src/airport_agent/ui/sidebar.py:130]
what:            `render_sidebar` renders only conversations and sample questions. Provider
                 status, data vintages and the per-chat horizon/preset/peer-group pickers are
                 not rendered — their three functions were left defined but uncalled (removed
                 in this sweep as dead code; see git). Design 04 §Layout — Sidebar lists all of
                 them as required content:

                     - Provider status: configured provider(s) and startup health check result
                     - Data vintages per source (from `DataService.source_vintages()`)
                     - Defaults the user may override for this chat: horizon, preset, peer group

                 `docs/design/known-limitations-and-tradeoffs.md` has no row for the removal, so
                 the design docs and the shipped UI disagree with nothing reconciling them.
why it matters:  CLAUDE.md makes `docs/design/00-06` the source of truth and requires the
                 limitations log to be updated whenever a decision is made. A reviewer reading
                 design 04 and then running the app sees three missing features and cannot tell
                 whether that is a deliberate choice or an unfinished one. Two of the three are
                 also assignment-relevant transparency surfaces (provider health, data vintage).
                 The in-code comment says the defaults still apply silently and vintages appear
                 per answer, which is true — but that reasoning lives only in a code comment.
options:         1) Add a limitations-log row and amend design 04's sidebar list to match the
                    shipped UI (documentation-only; no code change).
                 2) Restore the three panels (they are one `git show` away) so the UI matches
                    design 04 as written.
                 3) Restore only provider status — the one panel with no alternative surface —
                    and document the other two as deliberate simplifications.
recommendation:  Option 1. The removal reads as a deliberate de-cluttering with real substitutes
                 for the defaults (ask in chat) and the vintages (the per-answer "Where this came
                 from" table and `list_sources`). It is a documentation gap, not a product bug —
                 but it is the human's call, and I did not touch the design docs.
blocked:         nothing.

### F-003 — `ProvenanceSpec.derived(reason)` validates a user-facing reason that is never shown   [severity: low] [src/airport_agent/agent/tools/provenance.py:97]
what:            `derived()` rejects an empty reason with "needs a reason the user can read", and
                 five tools supply one ("cites the sources of every metric that entered the score").
                 `ToolRegistry._apply_provenance` surfaces `no_external_source` as
                 `out["provenance_note"]`, which synthesis renders into the provenance table's
                 footnotes — but `derived_from` is never read anywhere. It is write-only.
why it matters:  Small, but it is the kind of thing that quietly rots: the validator's message
                 promises the string reaches a user, and a future maintainer will believe it.
                 Either the reason should be shown or it should be documented as author-facing.
options:         1) Render it like `no_external_source` when a derived tool returns no provenance
                    (today that case only produces the generic `provenance_gap` note).
                 2) Keep it author-facing and reword the validation message to say so.
                 3) Drop the field and let `derived()` take no argument.
recommendation:  Option 1 — it is the behaviour the code already implies, and it makes a tool that
                 legitimately cannot declare a source floor explain itself instead of tripping a
                 generic gap note. Behaviour-visible, so not done here.
blocked:         nothing.

### F-004 — synthesis accepts 4 follow-ups where the schema asks the model for exactly 3   [severity: low] [src/airport_agent/agent/synthesis.py:307]
what:            `SYNTHESIS_SCHEMA` tells the model "Exactly 3 short follow-up questions" and
                 `FALLBACK_FOLLOW_UPS` has three, but the assembly slices `[:4]`:

                     follow_ups = [f for f in synthesis.follow_ups if f.strip()][:4] or list(FALLBACK_FOLLOW_UPS)

why it matters:  A compliant model gives 3 and nothing differs; a model that returns 4+ ships a
                 fourth chip the prompt never sanctioned, so the UI's follow-up row is 3 or 4
                 items depending on model behaviour rather than on a decision. Cosmetic, but it
                 is an unintended inconsistency between the stated contract and the code.
options:         1) Slice `[:3]` to match the schema.
                 2) Change the schema description to "at most 4".
                 3) Leave it — a 4th useful follow-up is harmless.
recommendation:  Option 1: the schema is the stated contract and 3 is what the fallback provides,
                 so the rendered count stops depending on which model answered. It changes what a
                 user can see, so it is logged rather than applied.
blocked:         nothing.

### F-005 — `terminal_expansion` up-weights two metrics that have no data for any airport   [severity: medium] [config/scoring_presets.yaml:11]
what:            `terminal_expansion` is the preset behind the assignment's first sample question
                 ("Which airports in New England are strong candidates for terminal expansion?").
                 It up-weights the gate metrics hardest:

                     pax_per_gate: 3.0
                     deps_per_gate_day: 3.0

                 Both are absent for every airport in the shipped snapshot (0 rows each) because no
                 public gate-count source was secured (known-limitations rows 5 and 42). Measured
                 against the snapshot, the share of each pillar's nominal metric weight that sits on
                 zero-row metrics is:

                     terminal_expansion  P2 (weight .30): 48%  [nas_delay_share, pax_per_gate, deps_per_gate_day]
                                         P4 (weight .10): 50%  [msa_gdp_per_capita, msa_gdp_cagr_5y]
                                         P5 (weight .10): 67%  [cpe_usd, nonaero_rev_per_enpl]
                     congestion_relief   P2 (weight .50): 19%
                     balanced            P2 (weight .25): 27%

                 The scorer is not wrong: it renormalizes within-pillar weights over the metrics an
                 airport actually has, reports `coverage`, and caveats tier-B gaps. No number is
                 miscomputed.
why it matters:  What the preset DOES no longer matches what it SAYS. Its description reads "gate and
                 passenger-side metrics up-weighted vs runway/delay", but after renormalization the
                 gate emphasis is gone entirely and P2 reduces to the delay/runway metrics the
                 description says are de-emphasised — close to the opposite of the stated intent.
                 `taxi_out_p80_min` and `ops_per_runway` are deliberately damped to 0.5, so the
                 surviving P2 signal is skewed by a choice made on the assumption that the 3.0-weighted
                 gate metrics would carry the pillar. A reader comparing the preset table in design 02
                 with the answer cannot see this; the per-answer caveat says only that tier-B metrics
                 contribute where curated data exists.
options:         1) Documentation only: state in the preset description (and in the answer's caveats)
                    that the gate metrics are unavailable, so the terminal focus rests on load factor,
                    upgauging and peak-hour ratio. No scoring change.
                 2) Re-tune `terminal_expansion` for the metrics that exist — e.g. drop the 0.5 damping
                    on taxi_out/ops_per_runway and raise load_factor / seats_per_dep_trend /
                    peak_hour_ops_ratio — so the weights express the intent using available data.
                 3) Have the Scorer surface it: when a metric with an explicit `metric_weights` entry
                    resolves to zero rows for every airport in the matrix, add a caveat naming it.
recommendation:  Option 3 plus option 1. Option 3 is the general fix — it catches the same class of
                 problem for any future preset and keeps the report honest without re-tuning weights
                 that were derived from the research note. Re-tuning (option 2) is a methodology
                 change and should be a deliberate, human decision, not a hygiene edit.
blocked:         nothing — rankings today are internally consistent and coverage is reported. This is
                 about the preset meaning what it claims.

### F-006 — `docs/DESIGN.md` does not exist, but the packaging script, the UI and design 06 all require it   [severity: high] [docs/]
what:            `docs/` contains SCORING-METHODOLOGY.md, KEY-TRADEOFFS.md, WHERE-HOW-AI-IS-USED.md
                 and process-log.md. There is no `DESIGN.md`. Five places assume there is:

                   scripts/make_zip.py:57      checklist entry "DESIGN.md present" -> fails, main() returns 1
                   src/airport_agent/ui/sidebar.py:130  st.caption("Design: docs/DESIGN.md") — a dead pointer in the app
                   docs/design/06-deliverables.md:31    "`docs/DESIGN.md` — the required short design/architecture document"
                   docs/design/06-deliverables.md:43    the release check: "DESIGN.md exists and the three standalone docs ... match its sections 3-5"
                   docs/design/04-ui.md:18              the sidebar must "Link to `docs/DESIGN.md`"

                 So `uv run python scripts/make_zip.py` builds the deliverable zip and exits 1 with an
                 unticked checklist line, and the shipped Streamlit app shows the user a path to a file
                 that is not in the zip.
why it matters:  Design 06 names DESIGN.md as *the* required design/architecture deliverable for the
                 assignment ("deliver source + short design doc"), with the three standalone docs
                 embedded as its sections 3-5. Its absence is a missing deliverable, not a tidiness
                 problem, and the one automated check that would have caught it (make_zip's checklist)
                 is advisory output rather than something CI runs.
options:         1) Assemble `docs/DESIGN.md` from `docs/design/00-06`, the limitations log and the three
                    standalone docs — this is exactly the `doc-assembler` subagent's job per design 05.
                 2) Drop DESIGN.md from the plan: point the sidebar caption and make_zip at
                    `docs/design/` and the three standalone docs, and amend design 04/06 to match.
                 3) Ship as-is and fix the dangling references only.
recommendation:  Option 1. The three standalone docs exist, so the content largely does; what is missing
                 is the assembled overview the assignment asks for. Writing it is authoring work well
                 outside a hygiene sweep, so I did not attempt it — but nothing else in this report is
                 as likely to matter at delivery.
blocked:         the deliverable zip: `scripts/make_zip.py` exits non-zero until this is resolved either way.

### F-007 — `get_routes` truncates a tie-broken-by-nothing ordering, so "top routes" is not reproducible   [severity: medium] [src/airport_agent/data/service.py:310]
what:            The route query orders by one column and the result is then sliced:

                     ORDER BY departures DESC        -- service.py, get_routes
                 ...
                     rows[:top_n]                    -- truncated = len(rows) > top_n

                 SQL gives no ordering guarantee among rows with equal `departures`, and the slice
                 makes that ordering decide *membership*, not just position. Measured on the shipped
                 snapshot over the trailing 12 months:

                     252 airports have a departures tie straddling the default top_n=10 cutoff
                     169 airports have one straddling top_n=25

                 So for roughly a quarter of the airport universe, which destinations appear in the
                 "top routes" table is decided by DuckDB's execution order rather than by any stated
                 rule. Nothing else in the codebase leaves this open: `_airport_universe` orders
                 `... DESC, a.iata ASC`, and `Scorer.score` sorts on `(-score, iata)`.
why it matters:  The route table is user-visible output and feeds an assignment sample question
                 ("percentage of long haul flights out of Anchorage"). Two runs against the same
                 snapshot may show different destinations, and a rebuilt snapshot or a DuckDB upgrade
                 can silently change the answer with no data change behind it. It also makes any
                 golden test over route membership quietly fragile. (`long_haul_share` and
                 `distance_bands` are unaffected: the Analyst calls `get_routes` with top_n=1000, so
                 no truncation occurs and the shares are computed over the whole network.)
options:         1) Add the tie-break the rest of the codebase already uses: `ORDER BY departures DESC,
                    dest ASC`.
                 2) Tie-break on a second meaningful measure first, e.g. `departures DESC, seats DESC,
                    dest ASC`, so a tie resolves toward the larger route.
                 3) Leave it and document that the top-N cut is arbitrary among equal-departure routes.
recommendation:  Option 1 — it matches `_airport_universe` and the Scorer, and `dest` is unique per
                 grouped row so the order becomes total. It changes which routes some airports show
                 (that is the point), so it is a behaviour change and logged rather than applied.
                 `tests/fakes.py::FakeDataService.get_routes` sorts a fixed list with Python's stable
                 sort, so the fake is already deterministic and would not need changing.
blocked:         nothing.

### F-008 — the `llm` marker is declared but no live smoke test exists   [severity: low] [pyproject.toml]
what:            `pyproject.toml` registers `llm: tests that call a live LLM provider (need
                 GEMINI_API_KEY)`, and design 03 §Testing asks for "one recorded live smoke test per
                 specialist". No test anywhere carries `@pytest.mark.llm`; every LLM test injects
                 `completion_fn`, so nothing has ever exercised the real provider path
                 (`LiteLLMClient._router_completion`, the LiteLLM Router construction, the real
                 response shape) under test.
why it matters:  The one code path that talks to Gemini is the one path with no coverage, and it is
                 also where a provider change bites first. The 9 network-marked data tests show the
                 pattern works; the LLM equivalent was simply never written. Low severity because a
                 manual run of the CLI exercises it, but it is a stated design commitment that is not met.
options:         1) Add one `@pytest.mark.llm` smoke test per specialist as design 03 asks.
                 2) Add a single `@pytest.mark.llm` test that plans one sample question end to end.
                 3) Drop the marker from pyproject.toml and amend design 03.
recommendation:  Option 2 as the cheap version of the commitment: one live test that proves the router
                 builds, authenticates and returns a schema-valid Plan catches nearly all of the risk
                 for a fraction of the quota. Writing tests is outside a hygiene sweep, so I left the
                 marker in place rather than removing the hook.
blocked:         nothing.

