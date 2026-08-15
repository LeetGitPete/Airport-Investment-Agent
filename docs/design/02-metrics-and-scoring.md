# 02 — Metric Registry & Deterministic Scoring Methodology

Status: DRAFT (brainstorm 2026-08-15). Research basis: `docs/research/2026-08-15-airport-investment-metrics.md`
(rating-agency methodologies, infra-fund diligence, FAA/ACRP capacity practice, ACI/ACRP benchmarks).

## Derivation — investor questions → metrics → data → pillars
1. **22 analyst questions** an airport-infrastructure investor asks (demand trend/forecast, O&D vs connecting,
   carrier concentration, hub durability, constrained now/later, which constraint binds, delay severity & cause,
   IMC exposure, catchment size/wealth, leakage, propensity to fly, intl/long-haul mix, absorption/spill, CPE,
   leverage, liquidity, non-aero yield, capex pipeline, federal support). Full list in the research note.
2. Each question → metric(s) + formula → **computability tier** against our verified data:
   - **A** computable for all airports from datasets · **B** needs curated YAML (majors only; coverage flagged) ·
   - **C** doctrine / not computable — kept in the registry as documented gaps the agent can *explain* but never scores.
3. Metrics grouped into **five pillars** used by ranking presets. Fact/compare/diagnose questions use metrics directly.
4. Data infrastructure (01) is amended to supply exactly these metrics.

## Metric registry (28 + 1 attempt) — authoritative copy lives in `config/metrics.yaml`
Direction ↑ = higher value raises expansion attractiveness. Horizons: 12m/3y/5y/10y where the source allows.

| Pillar (default wt) | id | definition | dir | source | tier |
|---|---|---|---|---|---|
| **P1 Demand Pressure (.30)** | `enpl_cagr_{3y,5y,10y}` | enplanement CAGR | ↑ | Socrata/TAF | A |
| | `taf_cagr_10y` | FAA TAF forecast 10y CAGR | ↑ | TAF | A |
| | `taf_vs_actual_gap` | TAF forecast ÷ latest actual | ↑ | TAF+Socrata | A |
| | `load_factor` | pax ÷ seats | ↑ | T-100/Socrata | A |
| | `spill_proxy` | std-dev of monthly LF ÷ mean (per route, aggregated) | ↑ | T-100 | A |
| | `seats_per_dep_trend` | Δ(seats/departure) 5y (upgauging) | ↑ | T-100 | A |
| | `pax_per_capita` | enplanements ÷ CBSA population | ↑ | Socrata÷Census | A |
| **P2 Congestion & Physical Constraint (.25)** | `pct_arr_delay_gt15` | arrivals ≥15 min late ÷ arrivals | ↑ | OTP | A |
| | `avg_dep_delay_min` | mean departure delay | ↑ | OTP | A |
| | `nas_delay_share` | NAS delay min ÷ total delay min (10y) | ↑ | Delay Cause | A |
| | `taxi_out_p80_min` | 80th pctile taxi-out | ↑ | OTP | A |
| | `ops_per_runway` | annual ops ÷ runway count | ↑ | TAF÷OurAirports/NASR | A |
| | `npias_capacity_label` | {constrained_2028, constrained_2033, severe_2033, congested, none} | ↑ | NPIAS 2025–29 lists | A |
| | `peak_hour_ops_ratio` | peak-hour ops ÷ declared called rate | ↑ | OTP÷YAML | B |
| | `pax_per_gate`, `deps_per_gate_day` | vs ACRP 5.0–6.5 turns/gate/day | ↑ | Socrata/T-100÷YAML | B |
| | `imc_capacity_ratio` | IMC ÷ VMC called rate | ↓ | YAML (Capacity Profiles) | B |
| | `slot_or_cap_flag` | Level 2/3, hourly caps, settlement caps (+expiry) | ↑ | YAML | B |
| **P3 Market Quality (.15)** | `carrier_hhi`, `top_carrier_share` | concentration | ↓ | T-100 | A |
| | `intl_pax_share` | intl ÷ total pax | ↑ | Socrata | A |
| | `longhaul_dep_share` | departures with DISTANCE ≥ threshold ÷ total (see conventions) | ↑ | T-100 | A |
| | `route_count_nonstop` | distinct nonstop dests | ↑ | T-100 | A |
| | `competing_seats_100mi` | Σ seats at airports within 100 mi | ↓ | T-100+OurAirports | A |
| | `od_share` | O&D pax ÷ total (1 − connecting share) | ↑ | **BTS DB1B/OD-40 — timeboxed attempt** | A if lands |
| **P4 Economic Base (.15)** | `cbsa_population`, `cbsa_pop_cagr_5y` | market size/growth | ↑ | Census | A |
| | `msa_gdp_per_capita`, `msa_gdp_cagr_5y` | wealth/momentum | ↑ | BEA | A |
| **P5 Financeability & Pipeline (.15)** — *normalize within hub class* | `npias_dev_per_enpl` | NPIAS 5y development $ ÷ enpl | ↑ | NPIAS | A |
| | `aip_per_enpl_10y` | AIP grants 10y ÷ enpl | ↑ (info) | FAA AIP | A |
| | `cpe_usd` | airline cost per enplanement (Form 127 line 16.5) | ↓ | CATS Form 127 | A |
| | `nonaero_rev_per_enpl` | non-aero revenue ÷ enpl | ↑ | CATS Form 127 | A |
| **Tier C (documented, not scored)** | `asv_utilization` (Order 5090.5 60%/80% trigger), `terminal_sqft_per_nbeg`, `dscr`, `days_cash`, `use_agreement_type` | doctrine or unavailable | — | — | C |

`MetricSpec` for every id carries: name, definition, formula, unit, direction, sources, horizons, tier, known caveats
(e.g. "Form 127 self-reported/unaudited", "CBSA ≠ catchment", "OTP undercounts ANC"). One source of truth for the
scorer, the LLM prompts, and UI tooltips.

## Conventions (stated in every answer that uses them)
- **Long-haul:** no ICAO/IATA standard. We report a **distance-band distribution** — short <500 · medium 500–1,500 ·
  long 1,500–3,000 · ultra >3,000 statute miles — and define "long-haul" as **≥1,500 mi by default**, adjustable.
  Passenger and freight departures computed **separately** (ANC is cargo-dominated).
- **Load factor:** no authoritative cutoff. Use the **spill model** (demand = LF + spill; spill ∝ demand variability):
  rank `load_factor` conditioned on `spill_proxy`, never an absolute ">80% = constrained" rule.
- **Constraint labels:** join FAA's published NPIAS lists (constrained 2028/2033, severe, congested) rather than
  recompute; note the circularity for slot-controlled airports (Level 2/3 are constrained by definition).
- **Verified thresholds** used in explanations: on-time = <15 min (14 CFR 234); NPIAS constrained = >80% hourly
  capacity ≥50% of time; HHI bands (DOJ); ACRP gate turns 5.0–6.5/day; hub size classes (49 USC §47102).

## Scoring engine (`scoring/`)
- **Input:** `FeatureMatrix` (airports × metric ids, one horizon or a horizon set) from `DataService`.
- **Normalization:** percentile rank **within hub class** (mandatory default; P5 metrics invert with size). User may
  widen peer group to region/all — the report then carries an explicit warning. Direction flips for ↓ metrics.
- **Missing values:** metric excluded, weights renormalized over available metrics; coverage % per pillar and per
  airport in the output; pillar coverage <50% ⇒ `low_confidence` flag; tier-B metrics contribute only where YAML
  exists and the report says so.
- **Composite:** score = Σ_pillar w_p · Σ_metric w_m · pct(metric), scaled 0–100. Contributions retained per metric.
- **Presets** (`config/scoring_presets.yaml`, weights sum to 1; LLM may choose, never invent):
  - `balanced` — pillar defaults above.
  - `terminal_expansion` — P1 .35, P2 .30 (gate/terminal metrics up-weighted vs runway), P3 .15, P4 .10, P5 .10.
  - `congestion_relief` — P2 .50 (runway/delay), P1 .25, P3 .10, P4 .05, P5 .10.
  - `market_entry` — P3 .35, P4 .30, P1 .20, P2 .05, P5 .10.
- **Methods (Deterministic Analyst):**
  - `rank(filter, preset, horizon, peer_group)` → `DeterministicReport` (table + contributions + templated explanation).
  - `compare(airports, metric_set | pillar)` → side-by-side values, hub-class percentiles, deltas, and a
    **congestion index** (P2 alone) when asked about congestion.
  - `diagnose_unmet_demand(iata)` → evidence bundle: LF × spill_proxy, upgauging, delay & NAS share, taxi-out,
    NPIAS label, slot/cap facts, declared VMC/IMC capacities, TAF gap → templated "signals of unmet demand" text.
  - Calculators: `distance_band_distribution(iata, pax|freight)`, `long_haul_share(iata, threshold)`.
- **Explanations** are templated from contributions: "BDL > PVD mainly on P1 Demand Pressure (+12): 5y CAGR 6.1% vs
  2.3% (Socrata, through 2026-04) …". No LLM in this path.

## Validation
- Unit: monotonicity, weight renormalization, missing handling, direction flips, hub-class partitioning.
- Golden: NPIAS-constrained airports rank top of `congestion_relief`; small NE airports don't outrank BOS on scale
  metrics; ANC freight long-haul share ≫ passenger share; SFO IMC ratio < LAX.
- Sensitivity table in DESIGN.md: rank stability of top-10 across presets and horizons.

## Open items
- DB1B/OD-40 adapter — timeboxed attempt (see 01); log outcome in limitations file.
- Curated YAML coverage list (which ~30 airports get gates, declared capacities, slot facts) — decide in build.
