# Process Log — how this project was built (and where AI was used)

Maintained by the `process-scribe` subagent (design in `docs/design/05-ai-native-dev-process.md`); seeded by hand
during the architecture session. Entries are chronological. Tags: `[KEY]` = methodological decision worth
highlighting in the final deliverable; `[AI]` = where/how AI was used; `[COURSE-CORRECTION]` = we changed direction and why.

---

## 2026-08-15 — Architecture session (brainstorm, no code)

### 09:xx  Kickoff — read assignment, set priorities `[AI]`
- Human + Claude Code (Fable 5) in an interactive brainstorming session (superpowers `brainstorming` skill).
- Decision: **assignment-first** — lean AI-native scaffolding, most effort on data, scoring, answer quality.
- Claude flagged items the initial plan glossed over: the ~1-day constraint, the four sample questions as the real
  spec, deterministic scoring as the core deliverable, "communicate uncertainty" as *product behaviour*, and the
  data-access risk. Human accepted.

### Parallel research via subagents `[AI]`
- Two background research agents dispatched (Opus): (1) free-tier LLM providers with tool calling — verified
  limits, recommended Gemini Flash → Groq → NVIDIA NIM chain via LiteLLM; (2) US aviation public data — agent
  actually downloaded/parsed candidate files and verified URLs, auth, formats. Notes saved under `docs/research/`.
- One agent run failed on a spurious safety-filter error and was relaunched on a different model — logged as a
  practical reliability note for multi-agent work.

### Architecture decisions
- Layered ports & adapters; `contracts/` package frozen first; deterministic scorer and LLM ranker are independent
  workstreams with *different* inputs (FeatureMatrix vs AirportProfile) and outputs, both fed by `DataService`.
- Runtime: Python, DuckDB snapshot, LiteLLM provider chain (free tiers), Streamlit chat; in-process tools
  (optional MCP wrapper). Deliverable: zipped source + `.env` with throwaway-account key; no hosting.

### `[COURSE-CORRECTION]` Scope of data — 12 months → multi-horizon, add international & cargo
- First data-layer draft scoped to trailing 12 months, domestic only. Human challenged: investment analysis needs
  3y/5y/10y history and international traffic. On inspection this was a *decision* (snapshot size), not a data
  constraint — Socrata/TAF/T-100 all go back a decade+. Rescoped: `Horizon ∈ {12m,3y,5y,10y}` first-class;
  intl included (route-level to verify, totals verified); cargo, aircraft gauge, catchment demographics, and
  airport financials added. Started `known-limitations-and-tradeoffs.md` distinguishing Constraint vs Decision.

### `[KEY]` Methodology: work backwards from investor questions
- Sequence we ended up following, and are now making explicit as the project's method:
  1. **Investor intent first** — what questions do airport-infrastructure investors/analysts most need answered?
     (rating-agency methodologies, infra-fund due diligence, FAA/ACRP capacity practice, ACI benchmarks).
  2. **Map questions → metrics/pillars** — the metric registry is the core asset; pillars are just a grouping used
     by ranking presets; fact/comparison/causal questions use metrics directly.
  3. **Scan available datasets** — for each metric, can we honestly compute it? COMPUTABLE / PARTIAL / NOT AVAILABLE,
     with the gap logged as a Constraint.
  4. **Build the data infrastructure for exactly those metrics** — adapters and derived tables follow the registry,
     not the other way around.
- Honest note: we did step 3 (data survey) *before* step 1, because data access was the biggest schedule risk on a
  one-day build. Having verified access, we then went back to step 1 and are amending the data layer to what the
  investor questions actually require. Order of discovery ≠ order of justification; the design docs present the
  justified order (questions → metrics → data), and this log records the real one.
- Research agent dispatched for step 1–2 (airport investment evaluation criteria → metric registry).

### Investor-metrics research lands → Section 2 & specialists `[AI]` `[KEY]`
- Research agent (Opus) surveyed Moody's/Fitch/S&P airport methodologies, infra-fund diligence, FAA/ACRP capacity
  practice and ACI/ACRP benchmarks → 22 analyst questions → 28 metrics with computability tiers → 5 pillars.
  Corrected itself mid-run on three points (ASV trigger lives in Order 5090.5; no ICAO/IATA long-haul cutoff;
  ACI per-passenger vs per-enplanement unit trap). Note saved under docs/research/.
- Design consequences: 4 pillars → 5; percentile-within-hub-class made mandatory (P5 metrics invert with size);
  load-factor cutoff replaced by the spill model; long-haul reported as distance bands with ≥1,500 mi default
  convention, pax vs freight separately; FAA CATS Form 127 upgraded to computable; BTS DB1B/OD-40 (O&D share)
  added as a timeboxed attempt.
- Specialist roster fixed only after the registry: expansion_analyst, capacity_analyst, market_analyst, plus a
  general_analyst fallback with a wider (600-char) but still structured dispatch. Sample questions mapped to
  intent → engines → specialist. Long-haul % is informational (no specialist).

### `[DECISION]` Deliverables & provider scope
- The three assignment-required explanations (scoring methodology, key tradeoffs, where/how AI is used) become
  standalone docs *and* sections of DESIGN.md, generated from one source. "Out of scope / with more time" lives at
  the end of KEY-TRADEOFFS.md.
- Runtime LLM: **Gemini free tier only** for now; Groq/NIM fail-over deferred to end-of-project if time remains
  (LiteLLM router keeps it a config change). No silent degradation; no cross-request caching.
- Design docs 00–06 + limitations log committed and pushed; design phase closed pending human review.
