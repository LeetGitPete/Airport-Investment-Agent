# 01 — Data Layer

Status: DRAFT (brainstorm 2026-08-15). Research basis: `docs/research/2026-08-15-us-aviation-data-sources.md`.

## Purpose
Turn heterogeneous public sources into one normalized, provenance-tagged local store and expose it only through
the `DataService` contract. Consumers never touch raw files or SQL.

## Scope (decisions, not constraints — see limitations log for the constraints)
- Geography: US commercial-service airports (~500; NPIAS/TAF universe), all FAA regions.
- Time: multi-horizon is first-class. `Horizon ∈ {12m, 3y, 5y, 10y}`. Annual history 2014→ (Socrata, TAF, Delay
  Cause), monthly detail trailing 24 months (T-100, OTP), TAF actuals pre-2014 for enplanements/ops.
- Traffic: domestic **and** international (Socrata intl split verified; route-level intl T-100 to be verified —
  fallback = Socrata intl totals). Passenger **and** cargo (T-100 freight/mail).
- Forecast: FAA TAF to 2055 (use 5y/10y forward growth).

## Sources & adapters
All adapters implement `SourceAdapter`:
```
class SourceAdapter(Protocol):
    id: str; kind: Literal["bulk","live"]
    def fetch(self, period: Period | None, cache_dir) -> list[Path]      # idempotent, cached by URL+period
    def normalize(self, paths) -> dict[str, DataFrame]                   # tidy tables keyed by target table
    def vintage(self) -> SourceVintage
```

| Adapter | Source | Feeds | Notes |
|---|---|---|---|
| `BtsT100SegmentAdapter` | transtats T-100 Segment (form POST; dom = FIM, intl = to verify) | routes_month, routes_year, airport_month | distance, seats, pax, departures, freight, mail, aircraft type/class |
| `BtsOtpAdapter` | transtats PREZIP OTP monthly zips | airport_month (delay, taxi, cancel, causes, distance groups) | aggregate at ingest, discard raw; trailing 24m only |
| `BtsDelayCauseAdapter` | BTS Airline Delay Cause (airport-month, 2003→, small) | airport_year / airport_month delay history | 10y trend source |
| `BtsSocrataLiveAdapter` | data.bts.gov r495-tyji (REST, no key) | airport_month/airport_year totals incl. intl split, load factor | cast text→number in SoQL |
| `FaaTafAdapter` | taf.faa.gov APO100 zip | airports (hub, region), taf_history, taf_forecast | enplanements + ops, 1976–2055 |
| `FaaNpiasAdapter` | NPIAS 2025–2029 App. A xlsx | npias | development estimate, hub |
| `FaaEnplanementsAdapter` | FAA CY enplanement xlsx | airport_year cross-check | optional |
| `OurAirportsAdapter` | ourairports airports/runways CSV | airports, runways | identity, lat/lon, runway count/max len |
| `CensusBeaAdapter` | Census CBSA pop est CSV + BEA MARPP zip | catchment | MSA pop/GDP, growth; airport→CBSA by lat/lon nearest |
| `FaaCatsAdapter` | FAA CATS Form 127 (`cats.airports.faa.gov/reports/form_127_all_airports/?year=&hub_size=`) | financials | CPE (line 16.5), non-aero revenue, debt; self-reported/unaudited — caveat carried in MetricSpec |
| `FaaAipAdapter` | FAA AIP grants xlsx (FY2021+ URLs scraped) | aip_grants | 10y $ per airport |
| `BtsDb1bAdapter` (timeboxed attempt) | BTS DB1B / OD-40 (form POST, large quarterly files; 1 recent year) | od_share | O&D vs connecting share; if it fails, log and drop `od_share` |
| `FaaNasStatusLiveAdapter` | nasstatus.faa.gov XML (REST, no key) | live | ground stops/delay programs |
| `CuratedFactsAdapter` | data/curated/airport_facts.yaml | curated_facts | slot level, runway constraints, projects; each fact has source URL |

## Store
DuckDB file `data/snapshot/airports.duckdb` (committed; target ≤100MB) + optional parquet exports.
Tables: `airports`, `runways`, `airport_month`, `airport_year`, `routes_month`, `routes_year`, `taf_history`,
`taf_forecast`, `npias`, `aip_grants`, `catchment`, `financials`, `od_share`, `curated_facts`, `source_vintage`.
Every fact row carries `source_id`, `vintage`, `period_start`, `period_end`. Derived metrics are computed by
`store.build_derived()` into `airport_metrics(iata, metric_id, horizon, value, ...)` — the table `DataService`
reads for FeatureMatrix/Profile, so metric math lives in one place. **The set of derived metrics is exactly the
registry `config/metrics.yaml` (frozen in Phase 1, see 02/05)** — one function per metric id, tier A/B.

## Refresh
`python -m airport_agent.data refresh [--sources a,b] [--period YYYY-MM] [--full]` — idempotent, per-source
try/except, writes `source_vintage`, rebuilds derived. `refresh --check` prints staleness per source vs its
publication cadence (OTP ~2mo lag, T-100 ~3mo, TAF annual, NPIAS biennial, NASR 28d, OurAirports nightly).
Scheduling: Claude Code skill `/refresh-data` + documented cron / Windows Task Scheduler line. No daemon.

## `DataService` implementation
`DuckDBDataService(DataService)` — read-only over the snapshot; live adapters called with 3s timeout and fallback
to snapshot; results memoized per process. `FakeDataService` in tests with ~12 realistic airports (BOS, BDL, PVD,
MHT, LAX, SNA, SFO, ANC, JFK, ATL, DEN, BUR) mirroring real magnitudes.

## Error handling & data quality
- Adapter failure ⇒ its metrics are `missing` with reason; refresh continues; snapshot keeps last good.
- `FeatureMatrix.coverage` mask; scorer decides how to treat gaps (see 02).
- `AirportProfile.data_quality_notes` auto-generated from rules (e.g. OTP coverage <80% of T-100 departures ⇒
  "OTP undercounts this airport"; ANC/HNL flags; intl route detail missing ⇒ note).
- Every number the agent shows is traceable to `source_id` + `vintage`.

## Testing
- Contract test suite parametrized over `[FakeDataService, DuckDBDataService(test_snapshot)]`.
- Adapter tests on small committed fixture files (one month, few airports); a `--network` marker for live smoke tests.
- Golden checks: ANC long-haul % from T-100 within known range; SFO LF > LAX LF; NE region returns BOS/BDL/PVD/MHT/PWM/BTV.

## Open items
- Verify T-100 International Segment table code (form probe) — fallback documented.
- DB1B/OD-40 timeboxed attempt (~1h) — outcome to limitations log.
- Curated YAML coverage: ~30 major airports (gates, declared VMC/IMC capacities, slot/cap facts with expiry, key projects).
- Decide snapshot horizon for routes_year (5y proposed) after measuring size.
