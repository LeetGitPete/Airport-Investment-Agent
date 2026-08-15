# Airport Expansion-Attractiveness: Analyst Questions, Metrics, and Data Feasibility

**Date:** 2026-08-15
**Purpose:** Work backwards from how real airport infrastructure investors and analysts evaluate airports, to a registry of metrics we can honestly compute from public data.
**Status:** All thresholds below were verified against primary sources (PDFs downloaded and text-searched directly) unless explicitly flagged. Corrections applied from three independent research passes.

---

## Part 1 — How professionals evaluate airport capacity investments

### 1a. Rating agency credit methodologies

**Moody's — *Publicly Managed Airports and Related Issuers* (10 Feb 2023).** The methodology itself is gated, but the complete scorecard is reproduced in public credit opinions. Verified from the [Albany County Airport Authority credit opinion, 25 Jul 2023, Exhibit 9](https://www.albanyairport.com/application/files/9217/0300/0327/Credit_Opinion-Albany-County-Airport-25Jul2023-PBM_1370921.pdf):

| Factor | Subfactors |
|---|---|
| 1. Market Position | Size of service area (millions); economic strength & diversity of service area; competition for travel |
| 2. Service Offering | Total enplanements (millions); stability of traffic performance; stability of costs; carrier base (primary carrier as % of total enplanements) |
| 3. Leverage & Coverage | Net revenue debt service coverage ratio; **Debt + ANPL per O&D enplaned passenger** |
| 4. Liquidity | Days cash on hand |
| Notching factors | O&D traffic; connecting traffic; potential for increased leverage; debt service reserves |

Moody's modified the leverage metric to use **gross debt plus adjusted net pension liability**, rather than debt net of debt service reserves.

**Fitch — *Transportation Infrastructure Rating Criteria* (Dec 2023).** Five attributes, verified in operation from the [PHL rating report, 28 Aug 2024](https://www.phl.org/drupalbin/media/philadelphia_international_airport_pa_rating_report.pdf):

| Attribute | PHL assessment and evidence |
|---|---|
| Revenue Risk — Volume | Stronger. 13–14M O&D enplanements; **26% connecting**; **63% American Airlines concentration** |
| Revenue Risk — Price | Stronger. Residual airline use agreement; **CPE under $13**, rising above $20 in rating case |
| Infrastructure Development & Renewal | Midrange. $1.8bn capital development program |
| Debt Structure | Stronger. All senior, fully amortizing, fixed-rate |
| Financial Profile | Leverage (net debt/CFADS) 4.8x; **negative trigger at ≥9x**; coverage ~1.2–1.5x |

**S&P — *U.S. And Canadian Not-For-Profit Transportation Infrastructure Enterprises* (12 Mar 2018).** Two-dimensional **Enterprise Risk Profile × Financial Risk Profile** matrix. Enterprise risk covers market position, service area economics, and competitive position; financial risk covers coverage, liquidity, and debt burden.

**Common ground across all three:** enplanement level and trend, O&D vs connecting mix, carrier concentration, cost per enplanement, leverage per O&D passenger, days cash on hand, and the legal ratemaking framework (residual vs compensatory).

### 1b. Infrastructure funds and airport privatization due diligence

US private equity rarely buys airports outright. Under the FAA **Airport Investment Partnership Program** (49 U.S.C. §47134) airports may be *leased, not sold*; rate increases above inflation require consent from 65% of carriers; and the operator loses access to tax-exempt debt. **San Juan Luis Muñoz Marín is the only US airport operating under the program today.**

Capital therefore flows through two other channels:

- **Special-facility terminal concessions with traffic risk** — JFK New Terminal One ($9.5bn, ~$2.33bn equity), JFK T6 ($4.2bn), LGA Terminal B ($5.1bn).
- **Availability-payment DBFOMs with no traffic risk** — LAX Automated People Mover ($4.9bn).

Diligence factors: catchment demographics and growth, O&D vs transfer mix, anchor-airline credit and hub commitment, aeronautical vs non-aeronautical revenue yield, rate-setting regime, capex program and handback condition, competition/leakage from nearby airports.

**Catchment has no standard definition.** ACRP bounds it by drive-time isochrones and halfway points to competing airports, and explicitly warns that **CBSA ≠ catchment** ([ACRP Tool 2, Defining an Air Service Catchment Area](https://crp.trb.org/wp-content/uploads/sites/7/2016/10/E1_Tool2-DefiningAirServiceCatchmentArea.pdf)). 60- and 90-minute drive bands are common conventions, not standards.

### 1c. FAA capacity planning practice

- **NPIAS 2025–2029** identifies **$67.5bn** of eligible airport development, of which primary airports account for 72% ($48bn) and large hubs $25bn. A national capacity evaluation completed in 2024 found **11 airports runway capacity constrained by 2028, rising to 14 by 2033**, plus 13 more at risk of significant congestion. [Narrative PDF](https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/ARP-NPIAS-2025-2029-Narrative.pdf)
- **FACT3 (Jan 2015)** was the last Future Airport Capacity Task report; the function has since moved into the biennial NPIAS. FACT3 used a delay-based rather than percent-of-capacity criterion. [FACT3 PDF](https://www.faa.gov/sites/faa.gov/files/airports/resources/publications/reports/FACT3-Airport-Capacity-Needs-in-the-NAS.pdf)
- **Airport Capacity Profiles** publish per-weather-condition "called rates" for **34 airports**. Latest edition 2014; newest individual profiles 2019 (BOS, SFO). **PDF only — no CSV, API, or data.gov dataset.** They contain no ASV and no delay estimates. [Index page](https://www.faa.gov/airports/planning_capacity/profiles)
- **Benefit-cost analysis** uses a 7% real discount rate and monetized delay savings. See thresholds table in Part 3.

### 1d. ACI / ACRP benchmarking practice

ACI World's *Guide to Airport Performance Measures* defines 42 indicators across 6 key performance areas, but the list is paywalled — use **ACRP 19A**'s 29 Core Airport Performance Indicators as the citable equivalent. Notably, **cost per enplanement is the only indicator unanimously classified as Core** across surveyed airports.

**ACRP 190** provides definitions rather than formulas, covers airfield/terminal/gates but not landside, and classifies metrics as input (e.g. number of gates), output (enplanements, operations), and outcome (average delay per aircraft, aircraft operations per gate).

**ACRP 25 Vol. 1, Table VI-6** gives the terminal sizing planning factor as **square feet per narrow-body-equivalent gate (NBEG)** — *not* per peak-hour passenger and *not* per million annual passengers:

| Terminal type | Square feet / NBEG |
|---|---|
| Smaller domestic | 15,000–18,000 |
| Larger domestic | 18,000–24,000 |
| International | 28,000–40,000 |

ACRP 25 explicitly recommends comparisons "on the basis of area per NBEG and with airports that have similar characteristics." **FAA AC 150/5360-13A contains no numeric terminal planning factors** — it defers to ACRP 25 and IATA.

### 1e. The top 22 questions an analyst asks

1. Is demand growing, and is the growth structural or post-pandemic recovery?
2. What does the official FAA forecast say through 2035/2045/2055?
3. What is the O&D versus connecting split?
4. How concentrated is the carrier base, and on whose credit does the airport depend?
5. Is the anchor carrier's hub commitment durable?
6. Is the airport physically capacity-constrained *today*?
7. Will it be constrained within the 5–10 year investment horizon?
8. Is the binding constraint runway, gate, terminal, or legal/political?
9. How severe is delay, and how concentrated is it in peak hours?
10. Is delay endogenous (volume/NAS) or exogenous (weather, late-arriving aircraft)?
11. What does instrument weather do to declared capacity?
12. How large and how wealthy is the catchment?
13. Is traffic leaking to competing airports nearby?
14. What is propensity to fly relative to peer markets?
15. Is the international and long-haul mix growing?
16. Is capacity being absorbed — load factors, upgauging, evidence of spilled demand?
17. What is cost per enplanement, and how much headroom exists to raise it?
18. What is leverage per O&D passenger, and debt service coverage?
19. What is liquidity (days cash on hand)?
20. What is non-aeronautical revenue per passenger, and what is the upside?
21. What capital program is already identified, and how is it funded?
22. What is the history of federal grant and PFC support?

---

## Part 2 — Question → metric → formula → computability

Verified free datasets assumed available: BTS T-100 Segment; BTS On-Time Performance (24 months); BTS Airline Delay Cause (airport-month, 2003→); BTS Socrata per-airport monthly totals (2014→, domestic/intl split, load factor); FAA TAF (1976→2055); FAA NPIAS Appendix A; FAA enplanement rankings; OurAirports; FAA NASR; Census CBSA; BEA MSA GDP; FAA AIP grants; FAA CATS Form 127; curated YAML.

| # | Question | Metric / formula | Status |
|---|---|---|---|
| 1, 2 | Demand trend and outlook | Enplanement CAGR (3/5/10 yr); TAF forecast CAGR to 2035/2045 | **COMPUTABLE** — TAF, BTS Socrata |
| 3 | O&D vs connecting | Connecting share = 1 − (O&D pax ÷ total enplanements) | **NOT AVAILABLE** from the listed sets. **Free fix: add BTS DB1B / OD-40.** DB1B is a 10% ticket sample, quarterly, 1993→; from Jul 2025 BTS moved carriers to **monthly reporting at a 40% sample (OD-40)**. This is the single highest-value addition to the stack — O&D share is central to *both* the Moody's and Fitch frameworks. T-100 proxies are weak |
| 4 | Carrier concentration | Top-carrier share; HHI = Σ(carrier passenger share²) | **COMPUTABLE** — T-100 |
| 5 | Hub durability | Seat-share trend; departures/day trend; connecting-bank structure from OTP scheduled times | **COMPUTABLE** — T-100 + OTP |
| 6, 7 | Constrained now / later | Demand-to-capacity ratio = observed hourly ops ÷ declared called rate | **PARTIAL** — hourly *demand* from OTP; hourly *capacity* only in the 34 Capacity Profile PDFs (2014–2019) → curate into YAML. FAA ASPM has live called rates but is **login-gated**. **Shortcut: NPIAS publishes the constrained/congested labels directly (see Part 3)** |
| 8 | Which constraint binds | Runway (D/C ratio), gate (turns/gate), terminal (sq ft/NBEG), legal (slots, caps, settlements) | **PARTIAL** — runway yes; **gate counts and terminal square footage are NOT AVAILABLE** in any free structured source → YAML from FAA Competition Plans and master plans; slots/caps → YAML |
| 9 | Delay severity and peaking | % arrivals >15 min late; mean departure delay; delay distribution by hour-of-day | **COMPUTABLE** — OTP |
| 10 | Delay causation | Share of delay minutes by NAS / carrier / weather / late aircraft / security | **COMPUTABLE** — Airline Delay Cause, 2003→ |
| 11 | IMC exposure | IMC called rate ÷ VMC called rate; % of hours in IMC | **PARTIAL** — ratio from Capacity Profiles (YAML); weather frequency needs NOAA or ASPM |
| 12 | Catchment scale | CBSA population; MSA GDP; GDP per capita | **COMPUTABLE** — Census, BEA. *Caveat: CBSA ≠ catchment* |
| 13 | Competitive leakage | Competing seats within 100 mi (haversine on OurAirports lat/lon); own share of regional seats | **COMPUTABLE as a proxy.** True leakage requires DB1B by passenger ZIP |
| 14 | Propensity to fly | Enplanements ÷ CBSA population | **COMPUTABLE** |
| 15 | International / long-haul mix | Intl pax share (Socrata); long-haul share = departures with `DISTANCE` ≥ threshold ÷ total departures (T-100) | **COMPUTABLE** — threshold is our convention, see Part 3 |
| 16 | Capacity absorption / spill | Load factor = pax ÷ seats; mean seats per departure (upgauging); **load-factor dispersion as spill proxy** | **COMPUTABLE** — T-100 |
| 17 | Cost competitiveness | Airline CPE — **Form 127 line 16.5 reports this directly** | **COMPUTABLE** (upgraded). Caveats: self-reported, un-audited, non-uniform accounting basis across airports |
| 18 | Leverage | Debt ÷ O&D enplanements; DSCR | **PARTIAL** — debt from Form 127; O&D requires DB1B/OD-40; debt service is weakly reported |
| 19 | Liquidity | Days cash = unrestricted cash × 365 ÷ operating expenses | **PARTIAL** — Form 127 cash lines are inconsistently reported |
| 20 | Non-aero yield | Non-aeronautical revenue ÷ enplanements | **COMPUTABLE** (upgraded) — Form 127 |
| 21 | Capex pipeline | NPIAS 5-year development estimate ÷ enplanements | **COMPUTABLE** — NPIAS Appendix A |
| 22 | Federal funding support | AIP dollars per enplanement, 10-year | **COMPUTABLE** |
| — | Airline use agreement type | Residual vs compensatory vs hybrid | **NOT AVAILABLE** → YAML from bond official statements |
| — | Peak-hour passengers | Σ(scheduled departures in peak hour × mean pax/departure by carrier-route) | **PARTIAL** — modelled by joining OTP schedules to T-100 monthly averages. No true PHP source exists publicly |
| — | Annual Service Volume | ASV = C_w × D × H | **NOT AVAILABLE** — not published in Capacity Profiles; requires a commissioned FAA study |
| — | Terminal square feet per Mpax | — | **DROPPED.** ACRP normalizes terminal area per NBEG, not per Mpax; and terminal square footage is unavailable anyway |

**Form 127 access note:** freely queryable per year and hub class at
`https://cats.airports.faa.gov/reports/form_127_all_airports/?year=2024&hub_size=L`

---

## Part 3 — Recommended metric registry

**Convention:** direction ↑ means a higher value increases expansion attractiveness. Horizons: M = monthly, A = annual, F = forecast.

### Pillar P1 — Demand Pressure (weight ~30%)

| id | name | formula | unit | dir | source | horizon |
|---|---|---|---|---|---|---|
| `enpl_cagr_5y` | Enplanement growth | (E_t/E_{t−5})^{1/5} − 1 | % | ↑ | Socrata, TAF | M, A |
| `taf_cagr_10y` | Forecast growth | TAF enplanements, 10-yr CAGR | % | ↑ | TAF | F to 2055 |
| `taf_vs_actual_gap` | Forecast optimism gap | TAF forecast ÷ latest actual | ratio | ↑ | TAF + Socrata | A |
| `load_factor` | Seat fill | passengers ÷ seats | % | ↑ | T-100 | M |
| `spill_proxy` | Demand variability | std-dev of monthly load factor ÷ mean, by route | ratio | ↑ | T-100 | M |
| `seats_per_dep_trend` | Upgauging | Δ(seats ÷ departures performed), 5 yr | % | ↑ | T-100 | M, A |
| `pax_per_capita` | Propensity to fly | enplanements ÷ CBSA population | trips | ↑ | Socrata ÷ Census | A |

### Pillar P2 — Congestion and Physical Constraint (weight ~25%)

| id | name | formula | unit | dir | source | horizon |
|---|---|---|---|---|---|---|
| `pct_arr_delay_gt15` | Late arrival rate | arrivals ≥15 min late ÷ arrivals | % | ↑ | OTP | M, 24 mo |
| `avg_dep_delay_min` | Mean departure delay | mean(DepDelay) | min | ↑ | OTP | M, 24 mo |
| `nas_delay_share` | Systemic delay share | NAS delay minutes ÷ total delay minutes | % | ↑ | Delay Cause | M, 2003→ |
| `taxi_out_p80_min` | Surface congestion | 80th pctile taxi-out time | min | ↑ | OTP | M |
| `peak_hour_ops_ratio` | Peak demand/capacity | peak-hour operations ÷ declared called rate | ratio | ↑ | OTP ÷ YAML | M |
| `imc_capacity_ratio` | Weather fragility | IMC called rate ÷ VMC called rate | ratio | ↓ | YAML (Capacity Profiles) | static |
| `npias_capacity_label` | Official constraint status | {constrained_2028, constrained_2033, severe, congested, none} | ordinal | ↑ | NPIAS 2025–29 | F |
| `ops_per_runway` | Airfield intensity | annual operations ÷ runway count | ops | ↑ | TAF ÷ NASR/OurAirports | A |
| `pax_per_gate` | Gate intensity | annual total passengers ÷ gate count | pax | ↑ | Socrata ÷ YAML | A |
| `deps_per_gate_day` | Gate turns | departures ÷ gates ÷ 365 | turns | ↑ | T-100 ÷ YAML | A |
| `slot_or_cap_flag` | Legal constraint | boolean + order expiry date | flag | ↑ | YAML | dated |

### Pillar P3 — Market Quality (weight ~15%)

| id | name | formula | unit | dir | source |
|---|---|---|---|---|---|
| `carrier_hhi` | Carrier concentration | Σ(passenger share²) × 10,000 | index | ↓ | T-100 |
| `top_carrier_share` | Anchor dependence | max carrier passengers ÷ total | % | ↓ | T-100 |
| `intl_pax_share` | International mix | intl pax ÷ total pax | % | ↑ | Socrata |
| `longhaul_dep_share` | Long-haul mix | departures with DISTANCE ≥ 3,000 mi ÷ total | % | ↑ | T-100 |
| `route_count_nonstop` | Network breadth | distinct nonstop destinations | count | ↑ | T-100 |
| `competing_seats_100mi` | Local competition | Σ seats at airports within 100 mi | seats | ↓ | T-100 + OurAirports |

### Pillar P4 — Economic Base (weight ~15%)

| id | name | formula | unit | dir | source |
|---|---|---|---|---|---|
| `cbsa_population` | Market size | CBSA population estimate | persons | ↑ | Census |
| `cbsa_pop_cagr_5y` | Market growth | 5-yr population CAGR | % | ↑ | Census |
| `msa_gdp_per_capita` | Market wealth | MSA GDP ÷ population | $ | ↑ | BEA |
| `msa_gdp_cagr_5y` | Economic momentum | 5-yr real GDP CAGR | % | ↑ | BEA |

### Pillar P5 — Financeability and Pipeline (weight ~15%) — **normalize within hub class**

| id | name | formula | unit | dir | source |
|---|---|---|---|---|---|
| `npias_dev_per_enpl` | Identified need intensity | NPIAS 5-yr development $ ÷ enplanements | $ | ↑ | NPIAS App. A |
| `aip_per_enpl_10y` | Federal support | AIP grants 10 yr ÷ enplanements | $ | ↑ | FAA AIP |
| `cpe_usd` | Airline cost | Form 127 line 16.5 | $ | ↓ | CATS Form 127 |
| `nonaero_rev_per_enpl` | Commercial yield | non-aero revenue ÷ enplanements | $ | ↑ | CATS Form 127 |

> **Critical normalization rule.** Non-aero revenue per enplanement **inverts with hub size** — FY2024: large hubs $13.21, medium $16.20, small $18.69 (small hubs are parking-dominated; parking is 43% of the North American non-aero mix). CPE moves the other way: large $16.00, medium $11.10, small $8.54, all-US $14.36. **Both must be z-scored within hub class**, or the composite systematically rewards small airports on P5. Large-hub CPE spans $3.93 (ATL) to $36.01 (JFK) with a $12.88 median — the commonly cited "$8–18 band" is far too narrow to use as a scoring anchor.
>
> **Unit trap.** ACI World reports non-aero revenue **per passenger** (global $7.57 in 2024; North America $7.41 in 2023); ACI-NA reports **per enplanement** ($14.70 in 2024). These are the same quantity at denominators differing by ~2×. North America is *not* double the world average — it has run slightly below it. Never compare `nonaero_rev_per_enpl` to an ACI World per-passenger figure without adjusting.

Weighting note: ACRP 19A finds **CPE is the only unanimous Core indicator**, which argues for weighting `cpe_usd` above the other P5 metrics.

### Commonly-used thresholds

| Threshold | Value | Source | Status |
|---|---|---|---|
| **Capacity constrained** | exceeds **80% of hourly runway capacity for at least 50% of the time** | NPIAS 2025–29, p.9 | **Verified, exact quote** |
| Severe constraint | 90% of hourly runway capacity exceeded 75% of the time | NPIAS 2025–29, p.9 | **Verified.** ⚠️ Changed between editions — NPIAS 2023–27 used 80%/75%. Not comparable across vintages |
| Congested | exceeds 60% of hourly capacity for at least 50% of the time | NPIAS 2025–29, p.9 | **Verified** |
| FACT3 congested | ASV delay ≥7 min/flight **and** >30% of hours 0700–2259 congested (congested hour = mean arrival delay ≥6.22 min or departure ≥6.65 min) | FACT3, p.10 & appendix | **Verified** |
| FACT3 severe / caution | 15 min & 50% / 5 min or 20% | FACT3, p.10 | **Verified** |
| **ASV planning trigger** | New/extended runway — **Planning at 60% ASV, Development at 80% ASV** and within 5 yrs of activity reaching ASV. Terminal aprons — 60%+ / 80%+ of apron space used routinely (≥30 days/yr) | **FAA Order 5090.5, Table 4-4** | **Verified.** ⚠️ *Not* in AC 150/5060-5 — that AC has no percent-of-ASV trigger at all. The "60–75%" phrasing is from **cancelled** Order 5090.3C |
| On-time flight | arrives **less than 15 minutes** after published arrival time | 14 CFR 234.2 | **Verified.** CFR definition is arrival-only; BTS also publishes gate-departure OTP |
| Delay-cause reporting floor | carriers code causes only when arrival delay ≥15 min | 14 CFR 234 / BTS | **Verified** |
| Hub size | large ≥1%, medium 0.25–1%, small 0.05–0.25% of US enplanements; primary ≥10,000 enplanements | 49 U.S.C. §47102 | **Verified** |
| Carrier concentration | HHI <1500 unconcentrated / 1500–2500 moderate / >2500 high | [DOJ](https://www.justice.gov/atr/herfindahl-hirschman-index) | **Verified.** 2023 Merger Guidelines use 1800 + Δ100 |
| Terminal sizing | 15,000–24,000 sq ft per NBEG (domestic); 28,000–40,000 (international) | ACRP 25 Vol.1 Table VI-6 | **Verified** |
| Gate turns | 5.0–6.5 departures per gate per day (planning range); observed US large hubs 4.5–6.6, ~360k–570k pax/gate | ACRP 25; computed | **Verified planning range**; observed values depend on weakly-sourced gate counts |
| Value of travel time | **$60.22/person-hour** air, all-purpose (2023$); personal $46.16, business $80.80 | FAA Airport BCA Guidance (2026 ed.), Table F-2 | **Verified** |
| Aircraft delay cost | Part 121 variable **$5,161/block hour (~$86/min)** | FAA *Economic Values* 2024 Update, Table 4-7 | **Verified** |
| BCA discount rate | **7% real** for federally funded airport projects | FAA BCA Guidance §12.5; OMB A-94 (reinstated by OMB M-25-23, Apr 2025) | **Verified** |
| **Long-haul distance** | **No standard exists.** Default to **≥3,000 statute miles** on T-100 `DISTANCE` as *our* convention | — | ⚠️ **ICAO and IATA publish no haul-length cutoff** ("haul" appears zero times in ICAO's Carbon Emissions Calculator Methodology v13.1). The 1,500/4,000 km bands are EUROCONTROL/EASA analytical conventions; EU Reg. 261/2004's 1,500/3,500 km is a compensation tier. **Never attribute a cutoff to ICAO or IATA** |
| **Load factor >80–85% = constrained** | — | — | ⚠️ **NO authoritative source. Do not use as an absolute rule.** The rigorous framing is the spill model: `demand factor = average load factor + spill factor`, with spill governed by demand variability (K-factor ≈ 0.30–0.52). At K=0.3 an 85% LF implies heavy spill; at K=0.1 almost none. Use `load_factor` conditioned on `spill_proxy` and ranked as a percentile |

**Reference load factors (BTS TranStats system):** 2019 83.87% (domestic 85.11%), 2023 83.06%, 2024 83.27%, 2025 81.89%, 2026 YTD ~81.0%. IATA global 2025 83.6%, North America 82.9%.

### Published constraint labels — join directly rather than recomputing

From the FAA's 2024 national capacity evaluation (NPIAS 2025–2029, Figure 1):

- **Runway capacity constrained by 2028 (11):** BOS, DCA, EWR, JFK, LAS, LAX, LGA, ORD, SAN, SEA, SFO
- **Added by 2033 (→14):** ATL, BWI, MIA
- **Severe by 2033 (7):** BOS, EWR, JFK, LAS, SAN, SEA, SFO
- **Congested but not constrained (13):** CLT, DAL, DEN, DFW, FLL, HOU, IAD, MDW, PHL, PHX, SAT, SJC, SNA

⚠️ Two cautions. These were read from a raster figure — counts reconcile with the published totals, but re-verify before publishing externally. And the evaluation is **partly circular**: airports under IATA Level 2/3 or the High Density Rule are "generally considered capacity constrained for the purposes of this evaluation," so BOS, SEA and SAN carry more independent signal than EWR, JFK, LGA and DCA.

### Curated YAML — facts no dataset carries

| Fact | Value | Source |
|---|---|---|
| Level 3 slot-controlled | JFK, LGA, DCA | FAA Slot Administration |
| Level 2 schedule-facilitated | EWR, ORD, LAX, SFO | FAA Slot Administration |
| JFK limit | 81 scheduled ops/hr (order 23 Jun 2026, expires 28 Oct 2028) | 91 FR / govinfo 2026-12591 |
| LGA limit | 71 scheduled + 3 unscheduled ops/hr | govinfo 2026-12592 |
| DCA limit | 48/hr by regulation (37 air carrier + 11 commuter) | 14 CFR 93 Subparts K & S |
| **EWR limit** | **72 ops/hr, extended through 30 Oct 2027** | 91 FR 37766 |
| ORD temporary limit | 2,708 operations/day, 17 May – 24 Oct 2026 | 91 FR 21071 |
| SNA | Community Settlement Agreement (amended 2003) caps commercial operations *and* passengers | FAA SNA Capacity Profile |
| Declared capacities | LAX 167–176 (visual) / 147–153 (marginal) / 133–143 (instrument) ops/hr; SFO 104–107 / 93–98 / 71–78; SNA 49–68 / 46–53 | FAA Airport Capacity Profiles |
| Gate counts, terminal sq ft, use-agreement type | per airport | FAA Competition Plans, master plans, bond official statements |

Slot orders churn annually — **every entry needs a dated expiry field.**

### Sample question mapping

| Question | Metrics and method |
|---|---|
| **Which New England airports are strong terminal-expansion candidates?** | Filter state ∈ {MA, CT, RI, NH, VT, ME}; rank on `enpl_cagr_5y`, `taf_cagr_10y`, `load_factor` × `spill_proxy`, `pax_per_capita`, `npias_dev_per_enpl`, `intl_pax_share`, `pax_per_gate`. BOS is the only one with a Capacity Profile (2019) and carries `npias_capacity_label` = constrained-2028 + severe-2033. BDL, PVD, MHT, PWM, BTV are terminal- and gate-limited rather than runway-limited, so weight P2's gate metrics over the runway ones |
| **Compare LAX vs SNA congestion** | `pct_arr_delay_gt15`, `avg_dep_delay_min`, `taxi_out_p80_min`, `nas_delay_share`, `peak_hour_ops_ratio`. Declared capacity differs by ~3× (LAX 167–176 vs SNA 49–68 ops/hr in visual conditions). **The decisive fact is not in any dataset:** SNA's binding constraint is a community Settlement Agreement capping commercial operations and passengers, so its congestion is legal, not aerodynamic. LAX is `constrained_2028`; SNA is `congested` only |
| **% long-haul flights out of Anchorage** | `longhaul_dep_share` from T-100 `DISTANCE` ≥ 3,000 statute miles, stated as our convention. Compute passenger and **freight** variants separately — ANC is a cargo-dominated gateway, and a passenger-only figure will badly misrepresent it |
| **Unmet flight demand at SFO and why** | `pct_arr_delay_gt15`, `nas_delay_share`, `imc_capacity_ratio`, `load_factor` × `spill_proxy`. **Why:** SFO's parallels are too close for independent instrument approaches, so declared capacity falls from 104–107 ops/hr in visual conditions to **71–78 in instrument conditions** — roughly a 30% loss whenever the marine layer arrives. SFO is IATA Level 2 schedule-facilitated, which NPIAS treats as capacity constrained by definition, and is on both the 2028 constrained and 2033 severe lists. Frame the answer through the spill model, not a load-factor cutoff |

---

## Open gaps and honesty notes

1. **O&D share is the biggest hole.** Add **BTS DB1B / OD-40** — free, and the only way to compute the metric that sits at the centre of both the Moody's and Fitch scorecards.
2. **Hourly runway capacity must be hand-curated** from 34 Capacity Profile PDFs dated 2014–2019. FAA ASPM has current called rates but is login-gated. Prefer the NPIAS published labels where they exist.
3. **Form 127 is self-reported and un-audited**, and AC 150/5100-19D does not mandate a uniform accounting basis — airports report on GAAP, indenture, or historical bases. Never rank airports on CPE alone without surfacing this.
4. **Gate counts and terminal square footage have no free structured source.** Gate metrics are only as good as the YAML behind them; source them from FAA Competition Plans, not Wikipedia.
5. **CBSA is not a catchment area.** Treat `cbsa_population` as a proxy and say so in generated answers.
6. **Annual Service Volume is not publicly available per airport**, so the well-sourced 60%/80% Order 5090.5 trigger cannot actually be evaluated without a commissioned study. Record it as doctrine, not as a computable metric.

## Sources

- [FAA NPIAS 2025–2029 Narrative](https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/ARP-NPIAS-2025-2029-Narrative.pdf)
- [FAA FACT3 (Jan 2015)](https://www.faa.gov/sites/faa.gov/files/airports/resources/publications/reports/FACT3-Airport-Capacity-Needs-in-the-NAS.pdf)
- [FAA Airport Capacity Profiles](https://www.faa.gov/airports/planning_capacity/profiles)
- [FAA Order 5090.5 (NPIAS/ACIP)](https://www.faa.gov/documentLibrary/media/Order/Order-5090-5-NPIAS-ACIP.pdf)
- [FAA AC 150/5060-5 Airport Capacity and Delay](https://www.faa.gov/documentLibrary/media/advisory_circular/150_5060_5.pdf)
- [FAA Airport Benefit-Cost Analysis Guidance](https://www.faa.gov/regulations_policies/policy_guidance/benefit_cost/FAA-Airport-Benefit-Cost-Guidance.pdf)
- [FAA Slot Administration](https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/perf_analysis/slot_administration)
- [FAA CATS Form 127](https://cats.airports.faa.gov/reports/form_127/)
- [FAA Terminal Area Forecast](https://www.faa.gov/data_research/aviation/taf) · [TAF Summary FY2025–FY2055](https://taf.faa.gov/Downloads/TAFSummaryFY2025-FY2055.pdf)
- [BTS Airline On-Time Performance and Causes of Flight Delays](https://www.bts.gov/explore-topics-and-geography/topics/airline-time-performance-and-causes-flight-delays)
- [BTS T-100 Domestic Segment (DB28DS)](https://www.bts.gov/browse-statistical-products-and-data/bts-publications/data-bank-28ds-t-100-domestic-segment-data-us)
- [BTS Origin & Destination Survey (DB1B / OD-40)](https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data-product)
- [14 CFR Part 234 — Airline Service Quality Performance Reports](https://www.ecfr.gov/current/title-14/chapter-II/subchapter-A/part-234)
- [Moody's scorecard via Albany County Airport Authority credit opinion](https://www.albanyairport.com/application/files/9217/0300/0327/Credit_Opinion-Albany-County-Airport-25Jul2023-PBM_1370921.pdf)
- [Fitch criteria in operation — PHL rating report (Aug 2024)](https://www.phl.org/drupalbin/media/philadelphia_international_airport_pa_rating_report.pdf)
- [ACRP Report 25 Vol.1 — Airport Passenger Terminal Planning and Design](https://onlinepubs.trb.org/onlinepubs/acrp/acrp_rpt_025v1.pdf)
- [ACRP Report 190 — Common Performance Metrics](https://crp.trb.org/acrp0715/wp-content/themes/acrp-child/documents/216/original/acrp_r190.pdf)
- [ACRP Tool 2 — Defining an Air Service Catchment Area](https://crp.trb.org/wp-content/uploads/sites/7/2016/10/E1_Tool2-DefiningAirServiceCatchmentArea.pdf)
- [ACI-NA Concessions Benchmarking Survey CY2024](https://airportscouncil.org/wp-content/uploads/2025/07/20250619-ACI-NA-Concession-Survey_BM-Success.pdf)
- [ACI World — Airport Non-Aeronautical Revenues](https://blog.aci.aero/airport-economics/airport-non-aeronautical-revenues-commercial-strategy/)
- [DOJ — Herfindahl-Hirschman Index](https://www.justice.gov/atr/herfindahl-hirschman-index)
