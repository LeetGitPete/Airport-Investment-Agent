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

