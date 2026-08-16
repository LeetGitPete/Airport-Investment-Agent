# Scoring Methodology

How the agent turns public aviation data into a defensible, reproducible ranking of US airports for
capacity-expansion investment. Everything in this document is implemented in code: the registry is
`config/metrics.yaml`, the weights are `config/scoring_presets.yaml`, the engine is
`src/airport_agent/scoring/`. No LLM participates in any step described here.

## 1. Derivation: investor questions -> metrics -> data

The method is deliberately backwards from the usual "what data can we get?".

1. **Investor intent first.** A research pass over rating-agency airport methodologies (Moody's, Fitch, S&P),
   infrastructure-fund due-diligence checklists, FAA capacity-planning doctrine (NPIAS, FACT3, Order 5090.5) and
   ACI/ACRP benchmarking produced **22 questions an airport-infrastructure analyst actually asks** — is demand
   growth structural, is the airport constrained today, will it be within the investment horizon, which
   constraint binds, how concentrated is the carrier base, how large and wealthy is the catchment, what capital
   programme is already identified, and so on. The full list with sources is
   `docs/research/2026-08-15-airport-investment-metrics.md`.
2. **Questions -> metrics + formula.** Each question maps to one or more metrics with an explicit formula and
   direction (up = higher value raises expansion attractiveness).
3. **Computability tier**, assigned against verified data access:
   - **A** — computable for all airports from bulk datasets.
   - **B** — needs the hand-curated YAML (`data/curated/airport_facts.yaml`; a few dozen airports; coverage flagged).
   - **C** — doctrine or non-public: kept in the registry as a *documented gap* that the agent can explain but
     never scores and never estimates.
4. **Five pillars** group the metrics. Pillars exist only so ranking presets can shift emphasis; comparison,
   factual and diagnostic questions use metrics directly.
5. **Data infrastructure follows the registry** — one adapter per source, one derived-metric function per
   registry id (`src/airport_agent/data/derived/`). A metric never enters the registry without a question and a
   source, and the data layer never computes anything the registry does not declare.

The registry was frozen (git tag `contracts-v1`) before any scoring, agent or UI code was written, so every
workstream built against a stable metric vocabulary.

## 2. The metric registry as shipped

40 ids: 35 tier A/B (scoreable) and 5 tier C (documented gaps). "Landed" below is measured against the shipped
snapshot `data/snapshot/airports.duckdb` (~33 MB, ~1,650 commercial airports); the counts are how many airports
actually carry a value.

| Pillar (balanced wt) | id | dir | tier | horizons declared | landed in the shipped snapshot |
|---|---|---|---|---|---|
| **P1 Demand Pressure (.30)** | `enpl_cagr_3y` | up | A | 3y | yes — 1,600 airports |
| | `enpl_cagr_5y` | up | A | 5y | yes — 1,596 |
| | `enpl_cagr_10y` | up | A | 10y | yes — 1,561 (spans COVID; read with 3y/5y) |
| | `taf_cagr_10y` | up | A | forecast | yes — 1,114 |
| | `taf_vs_actual_gap` | up | A | 12m | yes — 1,567 |
| | `load_factor` | up | A | 12m/3y/5y/10y | yes — up to 1,991 |
| | `spill_proxy` | up | A | 12m/3y | yes — 752 (12m) / 808 (3y) |
| | `seats_per_dep_trend` | up | A | 5y | yes — 728 |
| | `pax_per_capita` | up | A | 12m | yes — 1,351 |
| **P2 Congestion & Constraint (.25)** | `pct_arr_delay_gt15` | up | A | 12m/3y | **12m only** — 358 (OTP window cut to 12 months) |
| | `avg_dep_delay_min` | up | A | 12m/3y | **12m only** — 358 |
| | `nas_delay_share` | up | A | 12m/3y/5y/10y | **absent** — BTS Delay Cause cut |
| | `taxi_out_p80_min` | up | A | 12m | yes — 358 |
| | `ops_per_runway` | up | A | 12m | yes — 1,655 |
| | `npias_capacity_label` | up | A | forecast | yes — 1,657 |
| | `peak_hour_ops_ratio` | up | B | 12m | yes — 32 curated airports |
| | `pax_per_gate` | up | B | 12m | **absent** — no public gate-count source |
| | `deps_per_gate_day` | up | B | 12m | **absent** — same |
| | `imc_capacity_ratio` | down | B | static | yes — 31 curated airports |
| | `slot_or_cap_flag` | up | B | static | yes — 32 curated airports |
| **P3 Market Quality (.15)** | `carrier_hhi` | down | A | 12m/5y | yes — 1,334 |
| | `top_carrier_share` | down | A | 12m/5y | yes — 1,334 |
| | `intl_pax_share` | up | A | 12m/3y/5y/10y | yes — up to 1,922 |
| | `longhaul_dep_share` | up | A | 12m/5y | yes — 1,384 (domestic route detail only) |
| | `route_count_nonstop` | up | A | 12m/5y | yes — 1,440 |
| | `competing_seats_100mi` | down | A | 12m | yes — 1,652 |
| | `od_share` | up | A | 12m | **absent** — BTS DB1B attempt not run |
| **P4 Economic Base (.15)** | `cbsa_population` | up | A | 12m | yes — 1,606 |
| | `cbsa_pop_cagr_5y` | up | A | 5y | yes — 1,606 |
| | `msa_gdp_per_capita` | up | A | 12m | **absent** — BEA cut |
| | `msa_gdp_cagr_5y` | up | A | 5y | **absent** — BEA cut |
| **P5 Financeability & Pipeline (.15)** *(always normalized within hub class)* | `npias_dev_per_enpl` | up | A | forecast | yes — 1,144 |
| | `aip_per_enpl_10y` | up | A | 10y | **absent** — FAA AIP cut (also excluded by every preset) |
| | `cpe_usd` | down | A | 12m | **absent** — FAA CATS Form 127 cut |
| | `nonaero_rev_per_enpl` | up | A | 12m | **absent** — same |
| **Tier C — never scored** | `asv_utilization`, `terminal_sqft_per_nbeg`, `dscr`, `days_cash`, `use_agreement_type` | — | C | — | not computable from public data; explained, never estimated |

**Nine of the 35 tier A/B ids are absent for every airport.** Seven were cut by a scope decision on 2026-08-16
(the "Core-6" rescope: BTS Delay Cause, Census-BEA GDP, FAA CATS Form 127, FAA AIP and BTS DB1B were dropped to
fit the one-day budget); two (`pax_per_gate`, `deps_per_gate_day`) have no authoritative public gate-count source
at all. Each absent id still has a registry entry and a derived-metric function that returns zero rows with a
stated reason (`src/airport_agent/data/derived/__init__.py::MISSING_REASONS`), so nothing is silently invented:
the metric is reported as unavailable and the preset renormalizes weight over what did land. In practice **P4
reduces to population and its growth, and P5 reduces to `npias_dev_per_enpl` alone.** Full reasoning per id is in
`docs/KEY-TRADEOFFS.md` (rows 5, 7, 14, 28, 29, 40, 42, 43).

Each id carries a `MetricSpec` (name, definition, formula, unit, direction, pillar, tier, sources, horizons,
caveats). That single object feeds the scorer, the LLM prompts and the UI tooltips, so a metric cannot mean one
thing in the formula and another in the narrative.

## 3. Normalization — percentile within peer group

- Every metric is converted to an **average-rank percentile in [0, 1] within a peer group** before it is
  weighted. Raw units never enter the composite, so minutes, dollars and ratios become commensurable.
- **The default peer group is hub class** (large / medium / small / nonhub, 49 U.S.C. §47102). The user may widen
  to FAA region or "all"; the report then carries an explicit warning that scale-sensitive metrics are less
  comparable.
- **P5 is always normalized within hub class regardless of the requested peer group** (`normalize_within:
  hub_class` on the pillar in `config/metrics.yaml`, honoured in `scoring/scorer.py`), because per-enplanement
  financial metrics invert with airport size.
- `direction: down` metrics (`carrier_hhi`, `top_carrier_share`, `competing_seats_100mi`, `imc_capacity_ratio`,
  `cpe_usd`) are flipped, so a high percentile always means "more attractive for expansion".
- Ties take the average rank; a group with a single member gets 0.5 (no information, no advantage).
- **Percentiles are computed over the whole airport universe, not just the airports in the question.** The
  service returns up to 600 commercial airports ordered by enplanements (all 30 large, 33 medium and 77 small
  hubs, plus 460 nonhubs), partitioned by peer group. Asking about New England therefore still ranks each
  airport against its national hub-class peers, which is what makes a score comparable across questions. Every
  report states it: *"Percentiles computed within <peer group> peer groups across N airports."*

## 4. Presets and weights

`config/scoring_presets.yaml` is the only source of weights. Pillar weights are absolute and must sum to 1.0
(validated at load); `metric_weights` are *relative within a pillar* (unlisted = 1.0); `excluded_metrics` are
never scored under that preset. The LLM may choose a preset by name from this file — it may never invent one or
alter a weight.

| Preset | P1 | P2 | P3 | P4 | P5 | Emphasis |
|---|---|---|---|---|---|---|
| `balanced` | .30 | .25 | .15 | .15 | .15 | Registry defaults; all tier A/B metrics equal within pillars |
| `terminal_expansion` | .35 | .30 | .15 | .10 | .10 | Gate/passenger-side metrics up-weighted vs runway/delay |
| `congestion_relief` | .25 | .50 | .10 | .05 | .10 | Delay, taxi-out, NAS share, airfield intensity up-weighted |
| `market_entry` | .20 | .05 | .35 | .30 | .10 | Market quality and economic base for new-entrant investment |

Within-pillar multipliers (relative, before renormalization):

- `terminal_expansion`: `pax_per_gate` 3.0, `deps_per_gate_day` 3.0, `load_factor` 2.0, `seats_per_dep_trend` 2.0,
  `peak_hour_ops_ratio` 1.5, `taxi_out_p80_min` 0.5, `ops_per_runway` 0.5.
- `congestion_relief`: `pct_arr_delay_gt15` 2.0, `avg_dep_delay_min` 2.0, `taxi_out_p80_min` 2.0,
  `nas_delay_share` 2.0, `ops_per_runway` 2.0, `npias_capacity_label` 2.0, `pax_per_gate` 0.5,
  `deps_per_gate_day` 0.5.
- All four presets exclude `aip_per_enpl_10y` (federal grant history is context, not a ranking signal).

Honest note: the two 3.0 multipliers in `terminal_expansion` and the 2.0 on `nas_delay_share` in
`congestion_relief` currently have no effect, because those three ids did not land (§2). The preset file was
written before the rescope and is deliberately left intact, so the intent stays visible and the weights become
live the moment the sources are added.

## 5. The composite

For airport *i*:

```
metric_contrib[m] = w_p' x w_m' x pct[m,i] x 100
score[i]          = sum of metric_contrib over the metrics scored for i      # 0..100
```

- `w_p'` — the preset pillar weight, renormalized over the pillars that have at least one available metric for
  *this* airport.
- `w_m'` — the preset relative metric weight, renormalized over the metrics available for *this* airport within
  that pillar.
- `pct` — the percentile from §3.

Because both renormalizations are per-airport, `sum(metric_contrib) == score` exactly, and the report shows the
per-metric and per-pillar contributions that produced it. Nothing is hidden in a constant.

**Missing data.** A metric with no value for an airport is dropped and its weight redistributed inside its
pillar; if a whole pillar is unavailable for that airport, its weight is redistributed across the remaining
pillars. Two fields keep this visible:

- `coverage` — the share of scored metric ids that had a value for that airport (per row, and averaged on every
  analysis-tool result).
- `low_confidence` — set when any pillar with non-zero preset weight has **less than 50% of its metrics
  available** for that airport, or when nothing at all could be scored.

**Absent pillars are a caveat, not a confidence flag.** If a pillar has *no* scoreable metric in the matrix at
all (structural — e.g. P5 when only cut sources remain), every airport is affected equally, so flagging them all
"low confidence" would be noise. The report instead states the forgone weight explicitly: *"Pillars P4, P5 not
scored (no metric in the scored set; forgone preset weight 0.20); other pillars renormalized."* This is a
deliberate decision (tradeoff row 26).

Tier B metrics contribute only where curated data exists, and the report says so; tier C metrics are never
scoreable under any preset.

## 6. Conventions (stated in every answer that uses them)

- **Long-haul = departures on routes >= 1,500 statute miles**, reported alongside the full band distribution
  (short <500, medium 500-1,500, long 1,500-3,000, ultra >3,000). There is **no ICAO or IATA long-haul standard**
  — this is our stated convention, and the threshold is a tool argument the user can change. Passenger and
  freight variants are computed separately (ANC is cargo-dominated): the passenger variant weights departures on
  rows with seats > 0, the freight variant weights freight pounds.
- **Load factor is never used as an absolute cutoff.** There is no authoritative ">80% = constrained" rule. We
  use the spill framing (demand = load factor + spill; spill grows with demand variability): `load_factor` is
  ranked as a percentile and read together with `spill_proxy`.
- **Constraint labels are joined, not recomputed.** `npias_capacity_label` comes from the FAA's published NPIAS
  2025-2029 capacity evaluation (none / congested / constrained-2033 / constrained-2028 / severe-2033). The FAA
  treats IATA Level 2/3 airports as constrained by definition, so the label is partly circular for slot-controlled
  airports — stated as a caveat.
- **Multi-year windows are honest about their length.** A metric is only ever published at a horizon its source
  can support: `get_feature_matrix` never relabels a value across horizons (a metric that does not declare the
  requested horizon returns None, so 5y/10y matrices are sparser than 12m). Where the ingested window is shorter
  than the horizon's nominal window — T-100 routes are a trailing 24 months, OTP a trailing 12 — the value is
  computed from the months that exist and carries a `partial_window` quality flag stating how many of the nominal
  months were available. The number is real; the label never overstates it.
- **Verified thresholds used in explanations:** on-time = arrival <15 min late (14 CFR 234); NPIAS "constrained"
  = above 80% of hourly capacity at least 50% of the time; HHI bands 1500/2500 (DOJ); ACRP gate-turn planning
  range 5.0-6.5 per day; hub classes per 49 U.S.C. §47102.

## 7. The Deterministic Analyst

`src/airport_agent/scoring/analyst.py` implements three methods over the `DataService`. All three are pure code,
callable from the CLI or tests without an LLM, and each returns a `DeterministicReport` (rows with contributions,
percentiles, evidence `Metric` objects with source + vintage, curated facts, a templated explanation, caveats).

- **`rank(request)`** — resolve airports (explicit list or filter) -> fetch the universe feature matrix -> score
  -> keep the requested rows and re-rank them. Unknown, tier-C or preset-excluded `focus_metrics` are dropped
  *and disclosed*; if nothing scoreable survives it raises rather than ranking on an empty set.
- **`compare(request)`** — the same scoring plus a side-by-side value table for the requested metric set,
  hub-class percentiles and per-pillar deltas. Tier C ids asked for explicitly come back as "documented gap: not
  computable from public data".
- **`diagnose(request)`** — the unmet-demand evidence bundle over `load_factor`, `spill_proxy`,
  `seats_per_dep_trend`, `pct_arr_delay_gt15`, `avg_dep_delay_min`, `nas_delay_share`, `taxi_out_p80_min`,
  `npias_capacity_label`, `slot_or_cap_flag`, `peak_hour_ops_ratio`, `imc_capacity_ratio`, `taf_vs_actual_gap`,
  `taf_cagr_10y`, defaulting to the `congestion_relief` preset. It emits ten explicit signals, each ticked or
  crossed with its value:

  | Signal | Fires when |
  |---|---|
  | high LF with variable demand (spill likely) | `load_factor` pct >= 0.75 **and** `spill_proxy` pct >= 0.50 |
  | upgauging | `seats_per_dep_trend` pct >= 0.75 |
  | delay | `avg_dep_delay_min` pct >= 0.75 **or** `pct_arr_delay_gt15` pct >= 0.75 |
  | systemic (NAS) delay share | `nas_delay_share` pct >= 0.75 *(never fires — the metric is absent, §2)* |
  | surface congestion | `taxi_out_p80_min` pct >= 0.75 |
  | FAA capacity label | `npias_capacity_label` >= 2 (constrained-2033 or worse) |
  | legal cap | `slot_or_cap_flag` == 1 |
  | peak-hour saturation | `peak_hour_ops_ratio` >= 0.90 of the declared VMC rate |
  | weather fragility | `imc_capacity_ratio` <= 0.80 |
  | forecast gap | `taf_vs_actual_gap` >= 1.03 |

  These are quartile heuristics within hub class, not a causal model, and the report says so: *"they indicate,
  not prove, unmet demand"*.
- **Calculators** — `distance_bands(iata, freight)` and `long_haul_share(iata, threshold_mi, freight)` back the
  informational long-haul answers.
- **Explanations are templated from the contributions**, e.g. *"BOS ranks above BDL mainly on Demand Pressure
  (+12): Load factor 84.1% vs 79.3% (bts_socrata, through 2026-04)."* No LLM writes or edits that string; the
  synthesis layer may quote it, but cannot change a number in it.

## 8. Worked example — how the four sample questions route

The Concierge's first (and only) planning call produces a structured `Plan`; the routing below is the designed
mapping, encoded in the planner prompt and asserted by golden tests (`tests/golden/`).

| Question | Intent | Engines | Deterministic call | Specialist |
|---|---|---|---|---|
| "Which airports in New England are strong candidates for terminal expansion?" | analytical / rank | deterministic + specialist | `rank(filter=faa_regions[ANE], preset=terminal_expansion, horizon=5y, peer_group=hub_class)` | `expansion_analyst` |
| "Compare LA and Santa Ana airport congestion levels." | analytical / compare | deterministic + specialist | `compare(airports=[LAX, SNA], preset=congestion_relief, focus=P2 metric set, horizon=12m)` | `capacity_analyst` |
| "What is the percentage of long haul flights out of Anchorage airport?" | **informational** | tools only | none — `get_route_stats(iata=ANC, threshold_mi=1500)` returns the bands plus passenger and freight long-haul shares | none |
| "What is the unmet flight demand in SFO airport and why?" | analytical / diagnose | deterministic + specialist | `diagnose(airports=[SFO], horizon=12m)` -> the ten signals above | `capacity_analyst` |
| (unmapped, e.g. "is DEN's cargo growth sustainable?") | analytical / custom | deterministic + specialist | `compare` when airports are named, else `rank` | `general_analyst` |

The long-haul question is deliberately *not* an analysis: it is a fact with a stated convention, so it costs no
specialist call, and the answer offers a follow-up analysis instead.

## 9. Validation, and what is not here

- **Unit tests** cover percentile monotonicity and tie handling, direction flips, weight renormalization, missing
  handling, hub-class partitioning, and `sum(metric_contrib) == score`.
- **Golden tests** assert design-02 orderings against the fake data service (NPIAS-constrained airports rank top
  under `congestion_relief`; scale metrics keep BOS above PVD/MHT; ANC freight long-haul share far exceeds its
  passenger share), plus the four sample questions and six scripted follow-ups end-to-end with a scripted LLM.
- **Not produced:** the sensitivity table (top-10 rank stability across presets and horizons) that design 02
  planned for this document. It went with the 2026-08-16 rescope, and no sensitivity harness exists in the code;
  presenting one now would mean fabricating it. The ingredients are in place — `Analyst.rank` takes the preset
  and horizon as arguments — so it is a short follow-up, listed under "with more time" in `docs/KEY-TRADEOFFS.md`.
