# Airport Investment Intelligence Agent — Design

An agent that ranks and compares US airports as capacity-expansion investment candidates. A **deterministic
scorer** does the arithmetic over public aviation data; an **LLM** routes the question and interprets the
result. The model chooses *what to compute* and explains *what it means* — it never produces a number.

---

## Run it

```
uv sync --extra dev
uv run streamlit run src/airport_agent/ui/streamlit_app.py     # chat UI at localhost:8501
uv run python -m airport_agent.ui.cli "your question"          # same agent, one-shot
uv run pytest                                                  # offline: no network, no API key
```

The shipped `.env` holds a **throwaway Gemini free-tier key that will be revoked** — replace it with your own
from https://aistudio.google.com/apikey. The 40 MB DuckDB snapshot is committed, so nothing downloads at
runtime and everything except the LLM call works offline.

---

## General approach: not every question is the same question

The starting research (below) showed that an analyst evaluating an airport does not ask one kind of question.
They ask *what is the number*, and separately *which of these is the better bet*, and separately *why is this
one behaving oddly* — and those need genuinely different machinery behind them. A single "answer the question"
path would have to fake at least two of the three.

So the first thing the agent does is classify the turn, and the classification decides what runs:

| Interaction | What the analyst is doing | What the agent runs |
|---|---|---|
| **informational** | Looking up a fact | Data tools only. No scoring, no specialist. |
| **analytical** | Judging, ranking, comparing | Deterministic scorer **then** one LLM specialist |
| **followup** | Pressing on the previous answer | Answers from the previous reports if they already contain it — no recompute |
| **clarify** | Hasn't given enough to act on | One targeted question back |

`analytical` splits again by what the analyst actually wants — **rank** (which of these), **compare** (this vs
that), **diagnose** (why is this happening) — and each maps to a different deterministic method and a different
specialist.

Two of the four sample questions are `analytical` but land in different places: *"which New England airports
are candidates for terminal expansion"* is `rank`, *"compare LA and Santa Ana congestion"* is `compare`.
*"what percentage of Anchorage flights are long-haul"* is `informational` — a lookup, and scoring it would be
inventing a judgement nobody asked for. *"what is the unmet demand at SFO and why"* is `diagnose`.

**`clarify` carries a flavour**, added after QA found real users don't only ask well-formed questions:
`off_topic` (not about airports — declines with a constant string so the wording cannot drift turn to turn) and
`needs_direction` (genuinely about airports but not yet actionable — replies with three clickable questions the
agent can actually answer, rather than a generic "which airports?").

**The Plan is shown before anything executes** — intent, airports, preset, horizon, and what was filtered out.
You see what the agent decided to do before you see what it found.

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
upward, and the eight sanctioned exceptions are named in `.importlinter` with a reason each.

The payoff: the scorer has no way to call the LLM. *"The AI cannot alter the numbers"* is a property of the
import graph, not a promise in a prompt.

---

## Scoring methodology

Five pillars, derived from the research rather than invented (see the next section for how). Each answers a
distinct question an investor has to satisfy, and an airport can be strong on one and fatally weak on another —
which is the reason for keeping them separate instead of collapsing to a single blended number.

| Pillar | The question it answers | Weight | Example metrics |
|---|---|---:|---|
| **P1 Demand Pressure** | Is demand growing, and is it structural? | 0.30 | Enplanement CAGR 3/5/10y, FAA TAF forecast growth, load factor, upgauging, spill proxy |
| **P2 Congestion & Physical Constraint** | Is it constrained *now*, or within the investment horizon? | 0.25 | Late-arrival rate, mean departure delay, taxi-out p80, ops per runway, FAA NPIAS constraint label |
| **P3 Market Quality** | Is the traffic worth having, and is it defensible? | 0.15 | Carrier HHI, anchor-carrier share, international mix, long-haul share, route breadth, nearby competition |
| **P4 Economic Base** | Is the catchment large and wealthy enough to sustain it? | 0.15 | CBSA population and 5y growth |
| **P5 Financeability & Pipeline** | Can it actually be paid for? | 0.15 | NPIAS 5-year development need per enplanement, AIP grant history (cost per enplanement is defined but its source was cut) |

P5 always normalizes **within hub class** — airport financials invert with size, so comparing a nonhub's cost
per enplanement against JFK's is meaningless.

### The formula

Every raw value first becomes a **percentile within its peer group**, never an absolute threshold — a 0.83 load
factor means different things at a nonhub and at a large hub, and the research found no authoritative cutoff to
use instead. Each pillar is then the weighted mean of its own metrics, and the score is the weighted mean of
the pillars:

```
pillar_p  =  Σ_metrics  w′_m · percentile(m) · 100

score     =  Σ_pillars  w′_p · pillar_p                        →  0–100
```

`w′` are the weights **renormalized over what that airport actually has**, so a missing metric dilutes rather
than scoring zero. Each row reports its own `coverage`, so a score built on thin data is visibly thin.

### The question picks the weights

The weights are not fixed — that is the point of classifying the interaction. Four presets
(`config/scoring_presets.yaml`) are the only place weights live, and the planner chooses one from the question:

- **`terminal_expansion`** — gate and passenger-side metrics up-weighted, runway/delay damped
- **`congestion_relief`** — delay, taxi-out, NAS share and airfield intensity up-weighted (P2 → 0.50)
- **`market_entry`** — market quality and economic base lead (P3 + P4 → 0.65)
- **`balanced`** — the registry defaults

Asking about terminal expansion and asking about congestion relief should not return the same ranking, and they
don't.

### Conventions are declared, not assumed

Long-haul is **≥1,500 statute miles** — no ICAO or IATA standard exists, so the threshold is stated in every
answer that uses it. Capacity absorption uses a **spill model** rather than a load-factor cutoff, for the same
reason. Percentiles are **within hub class** for P5.

*Full detail: [`SCORING-METHODOLOGY.md`](SCORING-METHODOLOGY.md).*

---

## Key tradeoffs

> **Pete — this section is my draft from the limitations log; edit or replace it.**

**One day, so the data layer was cut rather than the reasoning.** Mid-build the projected work overran the
timebox. Rather than quietly thin everything, the options were written up and decided explicitly: keep six data
sources, cut five. The cost is visible and stated — **27 of the 40 registry metrics carry data** in the shipped
snapshot. Of the 13 that don't: 5 are tier C (documented gaps, never scored), 6 are tier A whose sources were
cut, and 2 are gate metrics no public source supports at all.

**Registry metrics are tiered by how honestly they can be computed**, and the gaps stay visible:

| Tier | Count | Meaning |
|---|---:|---|
| A | 30 | Computable for every airport from bulk public data |
| B | 5 | Needs hand-curated input — realistically majors only |
| C | 5 | **Defined but never scored.** A named gap, not a silent omission |

Tier C is deliberate. `asv_utilization`, `dscr`, `days_cash` all matter to this question and none is published
per airport. Naming them beats a registry that quietly contains only what was easy to get.

**A missing number is reported, never estimated.** On-time data is a trailing 12 months, so the 3-year and
5-year delay horizons return `None` rather than a number computed from too little data and labelled as though
it weren't. A specialist that receives no value for a metric must say it is unavailable and reason without it.

**No public gate-count source exists**, which bites hardest exactly where it matters: `terminal_expansion`
up-weights `pax_per_gate` and `deps_per_gate_day` at 3.0 and both are empty for every airport. Renormalizing
silently would have handed that weight to the very metrics the preset means to damp — so the scorer now detects
the case and says so in the answer.

**One free-tier LLM provider, failing loudly.** If Gemini fails the app raises an actionable error rather than
degrading to a worse answer, because a silently worse answer is the failure mode that actually costs you.

**Offline by default.** The snapshot is committed and queried locally; only FAA NAS Status is live, capped at 5
calls per turn behind a 3-second per-host pacer.

*Full detail: [`KEY-TRADEOFFS.md`](KEY-TRADEOFFS.md) · the running log, 60 entries:
[`design/known-limitations-and-tradeoffs.md`](design/known-limitations-and-tradeoffs.md).*

---

## How AI was used, and how this was built

### 1. Research first — questions before metrics, metrics before data

No metric was chosen because the data existed. The order was deliberately the reverse.

**Started from how professionals actually underwrite airports**, not from intuition: Moody's *Publicly Managed
Airports* scorecard (reconstructed from a public credit opinion, since the methodology itself is gated),
Fitch's five-attribute transportation criteria verified against the PHL rating report, S&P's enterprise ×
financial risk matrix, FAA capacity-planning practice (NPIAS 2025–29, FACT3, the Airport Capacity Profiles),
and ACI/ACRP benchmarking.

**That produced 22 questions an analyst actually asks** — is the growth structural or post-pandemic recovery;
is the binding constraint runway, gate, terminal or legal; is delay endogenous or weather-driven; is traffic
leaking to a competitor nearby; what is leverage per O&D passenger.

**The 22 condensed into the 5 pillars** above — P1 Demand Pressure, P2 Congestion & Physical Constraint,
P3 Market Quality, P4 Economic Base, P5 Financeability & Pipeline — which is simply where the questions
clustered.

**Only then the hunt for data**, one source at a time, each verified by actually fetching it. That produced a
source registry where every entry carries a field report rather than a description: *the T-100 ASP.NET session
cookie must be replayed on the POST or the form silently re-renders*; *NPIAS headers contain embedded newlines*;
*Socrata serializes every number as a string regardless of cast*; *a Census Metropolitan Division sub-row shares
its parent's LSAD and CBSA code, so filtering on LSAD alone double-counts*. Negative results were logged too — a
15-minute timeboxed probe of every candidate T-100 international table code, all of which 302'd to the homepage.

**Metrics were then derived backwards** from what the questions needed and the data could actually support —
which is what produced the A/B/C tiering. A question with no computable metric became a tier-C entry rather than
disappearing.

### 2. Design — separation of concerns, so it could be built in parallel

Design was done through `/brainstorming` into `docs/design/00–06` before code. The decisions that mattered:

- **Layers with one composition root.** `contracts/` ← `data`/`scoring`/`llm` (mutually independent) ← `agent/`
  ← `ui/`. Independence was the goal: each layer could be built in its own git worktree, at the same time,
  without waiting.
- **`contracts/` frozen at a tag** once agreed — pydantic types and `Protocol` ports only, importing nothing.
  Frozen so parallel work could not drift the shared types out from under itself; enforced by a pre-edit hook
  that blocks writes unless a human sets `CONTRACTS_UNFROZEN=1`.
- **Ports and fakes.** Every layer was built against a `Protocol` with a fake implementation, so `agent/` and
  `ui/` were testable before `data/` existed. The full `DataService` contract suite runs against **both** the
  fake and the real DuckDB implementation, so the fake cannot drift from reality.
- **The metric registry as single source of truth.** `config/metrics.yaml` feeds the scorer, the LLM prompts
  and the UI tooltips. One definition, three consumers, no drift — and it is frozen with the contracts.
- **The deterministic Analyst and the LLM specialists never call each other.** Numbers come from one, judgement
  from the other, and the separation is enforced by the import graph rather than by discipline.
- **Architecture as a test.** Four `import-linter` contracts run on every gate, so the layering survives
  refactoring by an agent that never read the design doc.
- **No free-form SQL reaches the model.** Tool arguments are pydantic-validated; the model picks tools, not
  queries.
- **Provenance in code, not in prose.** A specialist cites each figure as a `metric_id` + `iata` pair, and code
  resolves the pair back to the computed value with its source and vintage. **A pair that will not resolve is
  dropped and reported as a caveat** — a hallucinated number cannot reach the user wearing a citation.

Implementation ran as a roster of Claude Code subagents (`.claude/agents/`), one per layer plus a reviewer,
under a written escalation protocol: anything ambiguous, off-design or newly discovered stops and returns a
`DECISION NEEDED` block to the human instead of improvising. The scope cut in the tradeoffs above arrived that
way, and so did every decision in the 60-row limitations log.

### 3. QA — where most of the real improvements came from

Running the app against real questions found what the tests could not. The changes that mattered:

- **A ranking made one live FAA request per airport.** The national default is 140 airports, so a single
  question fired 140 downloads of the *same* national document — a ~7-minute stall and, under timeout, a fatal
  crash. Fixed in two parts: scoring now runs inside a zero live-call budget, and a per-turn ceiling of 5 is
  enforced by `contextvar` so every caller inherits it at any depth. A 3-second per-host pacer sits underneath.
- **Conversational turns had no path.** Both *"what's the most interesting airport fact?"* and *"what's a good
  carbonara recipe?"* fell through to `clarify` and got whatever the planner improvised. Now `off_topic`
  declines with a constant, and `needs_direction` returns three answerable questions as clickable follow-ups.
- **A preset's headline emphasis could silently evaporate.** `terminal_expansion` up-weights two metrics that
  have no data anywhere, and renormalization quietly redistributed that weight to the metrics the preset
  deliberately damps — a result close to the opposite of the stated intent, with every individual number still
  correct. The scorer now names those metrics and the answer says the emphasis did not apply.
- **"Top routes" was not reproducible.** `get_routes` ordered by departures with no tie-break and then
  truncated, so ordering decided *membership*, not just position — 252 airports have a tie straddling the
  default top-10. Adding `dest ASC` makes the order total.
- **Empty sections rendered as dead headings**, and the assumptions block — up to eight items plus uncertainty
  notes — pushed the actual tables off screen. Empty sections are now skipped; the assumptions block is
  collapsed by default but always present.
- **A hygiene sweep** across all 182 files removed dead code and rewrote comments that explained *what* rather
  than *why*. Its unfixed findings were carried into the limitations log rather than deleted with the report —
  including one wrong scored number (a 28-day February zero-filled across 31 days of hour slots) that needs a
  snapshot rebuild to fix and is logged rather than hidden.

`WHERE-HOW-AI-IS-USED.md` carries the full runtime and dev-time account, ending with an honest list of what AI
got wrong during the build and what was done about it.

---

## Where to read more

| | |
|---|---|
| `docs/SCORING-METHODOLOGY.md` | Derivation, full registry, normalization, presets, worked examples |
| `docs/KEY-TRADEOFFS.md` | Every constraint and decision, ending with "out of scope / with more time" |
| `docs/WHERE-HOW-AI-IS-USED.md` | Runtime and dev-time AI in full, plus what AI got wrong |
| `docs/research/` | The three research notes — investment metrics, data sources, LLM providers |
| `docs/design/00–06` | The design docs the build followed |
| `docs/design/known-limitations-and-tradeoffs.md` | The living log — 60 entries, including what is still broken |
| `CLAUDE.md` | The operating rules the build agents worked under |
