# Airport Investment Intelligence Agent — Design

Ranks and compares US airports as capacity-expansion investment candidates. A **deterministic scorer** does the
arithmetic over public aviation data; an **LLM** plans the request and interprets the result. The split is the
whole design: the model chooses *what to compute* and explains *what it means*, but it never produces a number.

This document covers the three things the assignment asks for — scoring methodology, key tradeoffs, and where
and how AI is used. Each has a deeper standalone companion in `docs/`; this is the short version.

---

## Run it

```
uv sync --extra dev
uv run streamlit run src/airport_agent/ui/streamlit_app.py     # chat UI at localhost:8501
uv run python -m airport_agent.ui.cli "your question"          # same agent, one-shot
uv run pytest                                                  # offline, no network, no API key
```

The shipped `.env` holds a **throwaway Gemini free-tier key that will be revoked** — replace it with your own
from https://aistudio.google.com/apikey if it has expired. The data snapshot (`data/snapshot/airports.duckdb`,
40 MB) is committed, so nothing downloads at runtime and the app works offline apart from the LLM call.

The four questions the agent was built against:

- *Which airports in New England are strong candidates for terminal expansion?*
- *Compare LA and Santa Ana airport congestion levels.*
- *What is the percentage of long haul flights out of Anchorage airport?*
- *What is the unmet flight demand in SFO airport and why?*

---

## Architecture

```
                 ┌──────────────────────────────────────────────┐
   your question │  ui/          Streamlit chat · CLI           │
        ───────► │               (imports agent + contracts only)│
                 └───────────────────────┬──────────────────────┘
                                         │
                 ┌───────────────────────▼──────────────────────┐
                 │  agent/       THE COMPOSITION ROOT           │
                 │   Concierge → Plan → tools → specialist      │
                 │             → synthesis → Answer             │
                 └─────┬─────────────┬──────────────┬───────────┘
                       │             │              │
        ┌──────────────▼──┐  ┌───────▼───────┐  ┌───▼────────────┐
        │  data/          │  │  scoring/     │  │  llm/          │
        │  10 adapters →  │  │  percentiles  │  │  LiteLLM →     │
        │  DuckDB         │  │  → composite  │  │  Gemini        │
        │  snapshot       │  │  → Analyst    │  │  (free tier)   │
        └──────────────┬──┘  └───────┬───────┘  └───┬────────────┘
                       └─────────────┼──────────────┘
                 ┌───────────────────▼──────────────────────────┐
                 │  contracts/   pydantic types + Protocols      │
                 │               FROZEN — imports nothing        │
                 └──────────────────────────────────────────────┘
```

`data/`, `scoring/` and `llm/` **cannot import each other** — only `agent/` wires them together. That is not a
convention, it is a build gate: four `import-linter` contracts fail the run if any layer reaches sideways or
upward, and the eight sanctioned exceptions are listed by name in `.importlinter` with a reason each.

The practical payoff is that the scorer has no way to call the LLM. "The AI cannot alter the numbers" is a
property of the import graph, not a promise in a prompt.

---

## 1. Scoring methodology

*Full version: [`SCORING-METHODOLOGY.md`](SCORING-METHODOLOGY.md).*

**Questions first, then metrics, then data.** Every metric exists because an investor question needed it. The
registry (`config/metrics.yaml`) is the single source of truth for the scorer, the LLM prompts and the UI
tooltips — one definition, three consumers, no drift.

**40 metrics across 5 pillars:** P1 Demand Pressure · P2 Congestion & Physical Constraint · P3 Market Quality ·
P4 Economic Base · P5 Financeability & Pipeline.

Each metric is tiered by how honestly it can be computed:

| Tier | Count | Meaning |
|---|---:|---|
| A | 30 | Computable for every airport from bulk public datasets |
| B | 5 | Needs hand-curated input, so realistically majors only |
| C | 5 | **Documented gap — defined in the registry, never scored** |

Tier C exists on purpose. `asv_utilization`, `dscr`, `days_cash` and the rest matter to this question and are
not publicly available per airport. Naming them is more honest than a registry that quietly contains only what
was easy to get.

**Scoring.** For each metric, an airport's raw value becomes a **percentile within its peer group** — never an
absolute threshold, because a 0.83 load factor means different things at a nonhub and at JFK. P5 always
normalizes *within hub class*, since airport financials invert with size.

```
score = Σ_pillars w_p′ · Σ_metrics w_m′ · percentile · 100
```

`w′` are the preset's weights **renormalized over the metrics that airport actually has**, so a missing metric
dilutes rather than scores zero — and each row reports its own `coverage` so a thin score is visible as thin.

**Four presets** (`config/scoring_presets.yaml`) — `balanced`, `terminal_expansion`, `congestion_relief`,
`market_entry` — are the only place weights live. The planner picks one from the question.

**Conventions are stated, not assumed.** Long-haul is ≥1,500 statute miles (no ICAO standard exists, so the
threshold is declared in every answer that uses it). Capacity pressure uses a spill model rather than a
load-factor cutoff, because no authoritative cutoff exists.

**Above the scorer sits a deterministic Analyst** — `rank`, `compare` and `diagnose`, plus route-mix helpers
(`long_haul_share`, `distance_bands`) — turning scores into findings and caveats. It is plain Python. It never
calls the LLM, and the LLM never calls it.

---

## 2. Key tradeoffs

*Full version: [`KEY-TRADEOFFS.md`](KEY-TRADEOFFS.md) · the running log, 60 entries:
[`design/known-limitations-and-tradeoffs.md`](design/known-limitations-and-tradeoffs.md).*

**The timebox was the binding constraint, and it was spent deliberately.** Mid-build, the projected work
exceeded the day. Rather than silently thin the quality, the options were written up and decided: keep six data
sources, cut five. The cut is visible in the shipped snapshot — **27 of the 40 registry metrics carry data**.
Of the 13 that do not: 5 are tier C, absent by design; 6 are tier A whose sources were cut; 2 are the gate
metrics below, which no public source supports at all.

The consequences, stated rather than hidden:

- **No public gate-count source exists**, so `pax_per_gate` and `deps_per_gate_day` are empty for every
  airport. The `terminal_expansion` preset up-weights both at 3.0 — so the preset's headline emphasis can land
  on nothing. The scorer now **detects this and says so** (`dead_weighted_metrics`), because renormalizing
  silently would have handed that weight to the very metrics the preset means to de-emphasise.
- **On-time data is a trailing 12 months**, so the 3-year and 5-year delay horizons return `None` rather than a
  number computed from too little data and labelled as though it weren't.
- **BEA economics, FAA CATS financials and DB1B O&D did not land**, so 6 tier-A metrics are absent. They stay
  in the registry as absences rather than being deleted to make coverage look better.
- **One free-tier LLM provider.** If it fails, the app **fails loudly** with an actionable message. There is no
  fallback to a degraded answer, because a silently worse answer is the failure mode that matters here.
- **The snapshot is committed and queried offline.** Only FAA NAS Status is live, capped at 5 calls per turn
  behind a 3-second per-host pacer — a ranking over 140 airports must not become 140 requests to a government
  endpoint.

**How uncertainty reaches the user, rather than the appendix.** Every number carries its `source_id` and
`vintage`. Every analytical answer carries an assumptions block. A missing metric is reported as unavailable and
reasoned around — never estimated. The Plan is shown before execution, including what was filtered out and why.
Where the deterministic view and the LLM's reading disagree, the disagreement is surfaced as its own line, not
smoothed away.

---

## 3. Where and how AI is used

*Full version: [`WHERE-HOW-AI-IS-USED.md`](WHERE-HOW-AI-IS-USED.md).*

### At runtime

```
question → [LLM] Plan          intent, airports, preset, horizon — shown to you before anything runs
         → [code] tools        pydantic-validated args; no free-form SQL is ever exposed to the model
         → [code] Analyst      the deterministic score. This is where every number is created.
         → [LLM] specialist    interprets the numbers it was handed, under a role prompt
         → [code] synthesis    resolves every cited figure, assembles the Answer
```

Four specialists (`config/specialists/*.md`) are markdown prompts whose YAML frontmatter is an enforced
capability grant: which tools they may call, which preset, how many turns, which slice of the registry. A
specialist cannot cite a metric that does not exist, because its prompt is built from the registry.

**What the LLM may do:** classify the question, choose airports/preset/horizon, decide which tools to call,
interpret results, phrase the explanation, disagree with the deterministic view.

**What it may not do:** alter, recompute or round a number; invent a weight, preset or metric id; hide a
disagreement; omit the assumptions block; estimate a value that came back missing.

The last one is enforced, not merely requested. A specialist must cite each figure as a `metric_id` + `iata`
pair; code resolves the pair back to the computed value with its source and vintage. **A pair that will not
resolve is dropped from the answer and reported as a caveat** — so a hallucinated number cannot reach you
wearing a citation.

### At dev-time

The repo was built by a roster of Claude Code subagents under `.claude/` — one per layer, plus a reviewer, with
model tiers chosen per role. Three mechanisms did the real work of keeping that honest:

- **Frozen contracts.** `contracts/` and `config/metrics.yaml` were frozen at a tag, enforced by a pre-edit hook
  (`.claude/hooks/guard_frozen.py`) that blocks writes unless a human sets `CONTRACTS_UNFROZEN=1`. Parallel
  agents could not drift the shared types out from under each other.
- **Import contracts as the architecture test.** The layering above is verified by `uv run lint-imports` on
  every gate, so "the scorer can't call the LLM" stays true under refactoring by an agent that never read this
  document.
- **A written escalation protocol.** Anything ambiguous, off-design or new stops and returns a
  `DECISION NEEDED` block to the human instead of improvising. The scope cut above arrived that way.

`WHERE-HOW-AI-IS-USED.md` ends with an honest list of what AI got wrong during the build and what was done
about it — including the defects that are still open and logged rather than quietly fixed or ignored.

---

## Where to read more

| | |
|---|---|
| `docs/SCORING-METHODOLOGY.md` | Derivation, full registry, normalization, presets, worked examples |
| `docs/KEY-TRADEOFFS.md` | Every constraint and decision, ending with "out of scope / with more time" |
| `docs/WHERE-HOW-AI-IS-USED.md` | Runtime and dev-time AI in full, plus what AI got wrong |
| `docs/design/00–06` | The design docs the build followed |
| `docs/design/known-limitations-and-tradeoffs.md` | The living log — 62 entries, including what is still broken |
| `docs/research/` | Source research: data sources, LLM providers, investment metrics |
| `CLAUDE.md` | The operating rules the build agents worked under |
