# 00 — System Overview & Contracts

Status: DRAFT (brainstorm 2026-08-15) · Owner: architecture session

## Purpose
An AI agent that helps analysts at an airport-modernization investment firm identify US airports where capacity
expansion (terminals, runways, gates) is most likely to be profitable, based on flight and passenger capacity
pressure. It answers ranking, comparison, factual and causal questions in a chat interface, with deterministic
scoring at its core and an LLM for interpretation, opinion and explanation.

Assignment constraints: ~1 day build; public APIs/data; deterministic scoring required; chat UI required; clearly
communicate assumptions, uncertainty and scoping; deliver source + short design doc (scoring methodology, key
tradeoffs, where/how AI is used).

## Architecture — layered ports & adapters, frozen contracts

```
                       ┌──────────────────────────────────────────┐
  Streamlit chat  ───▶ │  agent/  (orchestrator, tools, memory,   │
  CLI harness     ───▶ │          uncertainty & assumption report) │
                       └───────┬─────────────────┬────────────────┘
                               │ tools           │ tools
                 ┌─────────────▼──────┐   ┌───────▼─────────────┐
                 │ scoring/           │   │ agent/specialists/   │
                 │ Deterministic      │   │ LLM Specialists      │
                 │ Analyst (code)     │   │ (config-driven)      │
                 │ FeatureMatrix in   │   │ AirportProfile in    │
                 │ DeterministicReport│   │ SpecialistReport out │
                 └─────────────┬──────┘   └───────┬─────────────┘
                               │                  │
                       ┌───────▼──────────────────▼───────┐
                       │ contracts/  DataService Protocol  │  ◀── frozen first; only shared import
                       └───────────────┬───────────────────┘
                       ┌───────────────▼───────────────────┐
                       │ data/  adapters → DuckDB snapshot │
                       │        + live adapters + refresh  │
                       └───────────────────────────────────┘
                 llm/  LiteLLM router (Gemini → Groq → NVIDIA NIM) — shared infra
```

Rules:
1. `contracts/` contains only types (pydantic v2 models) and `typing.Protocol`s. No logic, no I/O.
2. Every package imports from `contracts/` and its own package only. Cross-package imports are forbidden
   (enforced by a lint hook). `agent/` is the only composition root that wires concrete implementations.
3. The Deterministic Analyst (`scoring/`) and the LLM Specialists (`agent/specialists/`) are independent with
   different inputs and outputs. They never call each other. `agent/synthesis.py` merges their reports (03).
4. `tests/fakes.py::FakeDataService` implements the same Protocol with realistic canned data so scoring, LLM
   ranker, agent and UI develop in parallel before real data lands. Contract tests run against both fake and real.
5. No silent degradation: if the LLM provider chain fails, fail loudly with an actionable message (03). Live data
   down ⇒ snapshot with a freshness note (acceptable).

## Package layout
```
src/airport_agent/
  contracts/   models.py  data_service.py  scoring.py  ranking.py  llm.py  tools.py
  data/        sources/<adapter>.py  store.py  service.py  refresh.py  curated/
  scoring/     scorer.py  presets.py  analyst.py (rank/compare/diagnose)  explain.py  calculators.py
  llm/         router.py  config.py
  agent/       concierge.py  plan.py  tools.py  dispatch.py  specialists/ (runner + config loader)  synthesis.py  session.py
  ui/          streamlit_app.py  cli.py
config/        metrics.yaml (registry, frozen)  scoring_presets.yaml  providers.yaml  sources.yaml  specialists/*.md
data/snapshot/ airports.duckdb (committed)      data/curated/airport_facts.yaml
tests/         contracts/  data/  scoring/  agent/  ui/  fakes.py  fixtures/  golden/
docs/          design/  research/  process-log.md  DESIGN.md (final deliverable, assembled from design/)
.claude/       CLAUDE.md  agents/*.md  hooks/  skills/
```

## Core contract types (sketch — authoritative version lives in code)
- `AirportRef(iata, icao, faa_locid, name, city, state, faa_region, hub_size, lat, lon)`
- `Horizon = Literal["12m","3y","5y","10y"]`; `HubSize = Literal["large","medium","small","nonhub"]`
- `Metric(id, value, unit, horizon, period_start, period_end, source, vintage, quality: QualityFlag|None)`
- `MetricSpec(id, name, definition, unit, direction, sources, horizons_supported)` — single source of truth for
  metric semantics; used by scoring config, LLM prompts and UI tooltips.
- `FeatureMatrix(airports: list[AirportRef], metrics: list[MetricId], values: 2-D floats, coverage mask, period)`
  — dense, for the deterministic scorer.
- `AirportProfile(ref, metrics_by_horizon, forecast, routes_summary, curated_facts, live_status, data_quality_notes)`
  — JSON-serializable, sized ≤ ~2k tokens, for the LLM.
- `RouteTable(iata, period, rows: [dest, distance, departures, seats, passengers, freight, is_international])`
- `LiveStatus(iata, delay_programs, ground_stops, latest_month_totals, fetched_at)`
- `AnalysisRequest`, `DeterministicReport`, `SpecialistReport`, `Plan`, `Answer`, `SessionState` — see 03.

## `DataService` Protocol (sketch)
```
list_airports(filter: AirportFilter) -> list[AirportRef]
get_feature_matrix(airports, metric_ids, horizon) -> FeatureMatrix
get_profile(iata, horizons=("12m","5y")) -> AirportProfile
get_routes(iata, period, top_n=25, international: bool|None=None) -> RouteTable
get_live_status(iata) -> LiveStatus
describe_metrics() -> list[MetricSpec]
source_vintages() -> list[SourceVintage]
```

## LLM-facing tools (agent contract; in-process function calling; optional MCP wrapper)
Data: `find_airports`, `get_airport_profile`, `get_route_stats`, `get_live_status`, `explain_metric`.
Deterministic: `score_airports`, `compare_airports`, `diagnose_unmet_demand`. Dispatch: `dispatch_analysis`
(specialist). Thin, pydantic-validated, compact JSON out with provenance.

## Runtime LLM
Free-tier provider chain via LiteLLM Router: Gemini 3.x Flash (primary) → Groq gpt-oss-120b → NVIDIA NIM.
Config-driven model names; startup health check; ≤4 LLM calls per answer budget. See research note.

## Documents in this folder
00 overview · 01 data layer · 02 scoring methodology · 03 LLM ranker & agent · 04 UI · 05 AI-native dev process ·
06 deliverables & doc plan · known-limitations-and-tradeoffs (living log)
