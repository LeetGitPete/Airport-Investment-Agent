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
| **followup** | Pressing on the previous answer | Answers from the previous reports if they already contain it — no recompute; tables already on screen collapse to a pointer (content-hashed), never repeated |
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

---

## Key tradeoffs

**Important note first:** The design, research and QA process took the majority of the time, and scope creep made it so this codebase is surely lacking a deep manual overview - this is the number one thing I’d dedicate more time to in this project.
Going over each file manually and understanding it more deeply is something I always do in my work with AI agents - it's the only way to truly maintain a codebase throughout time and scale it - but with this project's scope and time it wasn’t something I was able to achieve here.

- More data adapters - of course there's a lot more data that could be gathered and this will be a pure improvement to the project.
- More specialists - currently there are only 3 specialists, and one generalist, this structure is a POC but of course a more complete build would have to include a wider variety of specialists
- Scoring methodology - the scoring system is simple and intuitive, but it lacks more nuance, providing LLMS more freedom here through a wider variety of data sources, that arent cleanly mapped onto metrics could prove very useful - researching what investors actually do to get their data, and some of the more common heauristics would be something I'd look in to.
- Polish - of course there are still many visual ui bugs/ missing features that couldnt be addressed in the amount of time for this project.

---

## How AI was used, and how this was built

### 1. Research — questions before metrics, metrics before data

**Research agents were sent out first**, to find how professionals actually underwrite airports rather than
guessing: Moody's *Publicly Managed Airports* scorecard (reconstructed from a public credit opinion — the
methodology itself is gated), Fitch's transportation criteria, S&P's risk matrix, FAA capacity planning
(NPIAS 2025–29, FACT3, Airport Capacity Profiles), ACI/ACRP benchmarking.

That produced **22 questions an analyst actually asks**, which clustered into the five pillars:

**P1** Demand Pressure · **P2** Congestion & Physical Constraint · **P3** Market Quality ·
**P4** Economic Base · **P5** Financeability & Pipeline

**Only then agents went hunting for data** that could answer those questions, verifying every source by
actually fetching it — so the source registry carries field reports, not descriptions (the T-100 ASP.NET
session cookie must be replayed on the POST; FAA headers contain embedded newlines; Socrata stringifies every
number regardless of cast). Dead ends were logged too, not quietly dropped.

**Metrics were derived backwards** from what the questions needed and the data could actually support. That is
what produced the A/B/C tiering: a question with no computable metric became a documented tier-C gap instead of
disappearing. No metric was chosen because the data happened to exist.

### 2. Designing and implementing

Designed with `/brainstorming` into `docs/design/00–06` before any code. 

The most important design lens that led the entire session was separating and boxing LLMS into strict rules and tool capabilities,
this will hopefully prevent hallucinations and allow the data and deterministic logic to shine through. I'm trying to utilize the llm's superpower which is understanding
human language and dispatching the relevant tools per request, streamlining the data analyst's routing role while providing all the data it needs for judgement.

This comes into play nicely these design decisions:
- Conversation agent — the Concierge owns language, intent and dispatch; it never touches raw data.
- Deterministic Analyst — plain Python, and the only thing in the system that creates a number.
- LLM specialists — interpret numbers handed to them, one lens each, never compute their own.
- Frozen contracts — pydantic types and Protocol ports, agreed once and locked at a tag.
- Structured JSON everywhere — every LLM call answers a fixed schema; nothing is parsed out of prose.
- Required fields — disagreements and assumptions are mandatory, so silence can't hide either.
- Tools, not queries — validated arguments from a fixed set; no free-form SQL ever reaches the model.
- Capability grant per specialist — allowed tools, preset, turn limit and metric slice fixed in front matter. 

### 3. QA 

Testing the product with real questions -> noting issues -> using claude to fix trivial issues directly, and /brainstorming for larger stuff. For example off-topic handling was added here, and many ui-issues like empty rows or missing sources.

