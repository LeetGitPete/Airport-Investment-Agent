# Public data sources for US airport capacity-expansion ranking — research note (verified 2026-08-15)

"Verified" = fetched and parsed by the research agent on this date.

## Tier 1 — build on these (no auth, scriptable, high value)

### 1. BTS On-Time Performance (OTP) — highest-value single file
- URL pattern: `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YYYY}_{M}.zip`
- No auth. Stable URLs. Lag ~2 months (2026_6 = 200; 2026_7 = 404 on 2026-08-15).
- ~30 MB zip → ~270 MB CSV, 110 cols, ~600k rows/month.
- Key cols: `Origin, Dest, Distance, DistanceGroup, DepDelayMinutes, ArrDelayMinutes, TaxiOut, TaxiIn, Cancelled, Diverted, CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay`.
- Delay *causes* are included — no need for the separate "Airline Delay Cause" dataset.
- Gotcha: covers passenger carriers ≥0.5% of domestic revenue at contiguous-48 airports; **badly undercounts Alaska (ANC)** and cargo.

### 2. BTS T-100 Segment (Domestic) — route-level, all carriers incl. cargo
- Form: `https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM&QO_fu146_anzr=Nv4%20Pn44vr45` (FIM = Domestic Segment; FIL = Domestic Market).
- No stable PREZIP file. ASP.NET form **is automatable**: GET page → scrape `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` → POST `cboGeography=All, cboYear, cboPeriod, chkAllVars=on, chkDownloadZip=on, btnDownload=Download`. Verified: returns zip, ~1.3 MB/month, 45 cols × ~36k rows.
- Key cols: `ORIGIN, DEST, DISTANCE, SEATS, PASSENGERS, DEPARTURES_PERFORMED, AIRCRAFT_CONFIG, CLASS`.
- **International Segment table code NOT identified (FIK/FIJ/FII 404) — unverified.**

### 3. BTS Socrata API (data.bts.gov) — genuine live REST, zero auth
- `https://data.bts.gov/resource/r495-tyji.json` — T-100 Segment Summary by Origin Airport.
- Monthly, 2014 → 2026-04, per airport: `total_passengers, total_seats, total_load_factor, total_departures, total_distance_flight_sm`, split domestic / outbound-intl / inbound-intl.
- Gotcha: **all numerics stored as text** — cast in SoQL (`total_passengers::number`).
- One call answered the "New England ranking" query.

### 4. FAA Terminal Area Forecast (TAF) — the "should we expand" signal
- `https://taf.faa.gov/Downloads/APO100_TAF_Final_2025.zip` — 15.7 MB, no auth.
- `Enplanements.xlsx` (`locid, scenario, ayear, aac, aat, commuter, us_flag, frgn_flag`; 1976–2055), `AirportsOperations.xlsx` (`itn_Ac, itn_at, itn_ga, itn_mil, loc_ga, loc_mil, tot_overs`), `Airports.xlsx` (`HUB_SIZE` 0–3, FAA `REGION`; `ANE` = New England).
- FAA's own 30-year per-airport demand forecast → forecast growth = core expansion KPI.

### 5. FAA NPIAS Appendix A — capital need quantified by FAA
- `https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/ARP-NPIAS-2025-2029-AppendixA.xlsx` — 2.3 MB, 3,287 airports.
- Cols incl. `Hub (FY25), Enplaned (CY23/FY25), Development Estimate 2025-2029`.
- Gotcha: page has a malformed href with leading space — strip whitespace if scraping.

### 6. OurAirports — airports + runways
- `https://davidmegginson.github.io/ourairports-data/airports.csv` (12.7 MB), `.../runways.csv` (4.0 MB). Public domain, rebuilt nightly. Lat/lon, IATA/ICAO, region, runway count/length.

### 7. FAA NASR 28-day subscription CSV
- e.g. `https://nfdc.faa.gov/webContent/28DaySub/extra/06_Aug_2026_APT_CSV.zip` (8 MB). `APT_BASE.csv` (19,426×90), `APT_RWY.csv` (23,196×25).
- Gotcha: host **503s on HEAD**, serves GET fine. Date in URL changes every 28 days.

### 8. FAA enplanements / AIP grants
- CY2024 final + CY2025 preliminary xlsx: `Rank, RO, ST, Locid, City, Airport Name, S/L, Hub, Enplanements, % Change` (fraction).
- AIP: `FY_2025_AIP_Grants.xlsx`, 3,707 rows, `LocID`, `Total Amount`. FY2021+ URLs must be scraped (undated paths).

## Tier 2 — live status
- **FAA NAS Status**: `https://nasstatus.faa.gov/api/airport-status-information` — 200, XML, no key, live ground stops/delays/closures. Sibling `/ground-stops`, `/ground-delays` **503**. FAA ASWS (`soa.smext.faa.gov`) unreachable/unverified — use nasstatus.
- **OpenSky**: basic auth removed 2026-03-18; OAuth2 client-credentials only (token URL `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`, 30-min tokens). Anonymous 400 credits/day; registered 4,000. Arrivals/departures windows 2 days max.
- **adsb.lol**: 200, no key, ODbL (live positions).
- aviationstack free = 100 req/month, historical paid; AeroDataBox 600 units/mo (~100 delay calls); AeroAPI Personal $5/mo credit.

## Avoid for a one-day build
- FAA ASPM/OPSNET: login-walled, emailed Excel, aspm.faa.gov 503 to all requests.
- FAA Airport Capacity Profiles: per-airport PDFs 2014–2019, stale.
- Census/BEA APIs: key on every request (instant, self-serve; latency unverified). Use keyless bulk instead: `cbsa-est2025-alldata.csv` (827 KB), `apps.bea.gov/regional/zip/MARPP.zip`.
- ACAIS: no public host.

## Recommended minimum stack
**OTP + T-100 Segment + TAF + NPIAS App. A + OurAirports** (+ Socrata live + nasstatus live). No API keys, all joinable on FAA LocID / IATA.

- **Long-haul %** → T-100 `DISTANCE` per route (not OTP: ANC OTP shows 1,333 flights / 24.4% ≥1500 mi vs T-100 4,946 departures / 30.0% — OTP misses cargo/regional).
- **Congestion** → OTP `DepDelayMinutes`, `TaxiOut`, `Cancelled`; Socrata `total_load_factor`; TAF ops counts. Verified Apr 2026: LAX 12.9 min avg dep delay vs SNA 13.9, SFO 18.0.
- **Unmet demand** → load factor (SFO 80.4% overall, inbound intl 86.6%) + delay + slot/level status (SFO = FAA Level 2 schedule-facilitated). FAA constraint threshold: >80% of hourly runway capacity ≥50% of the time; 11 airports projected runway-constrained by 2028 (14 by 2033).

## Caveat on "why"
Causal explanations (e.g., SFO's 28L/28R 750-ft runway spacing and the 2026 FAA restriction on simultaneous parallel approaches cutting arrival rate ~54→36/hr) are not in any structured dataset. Budget a small curated "airport facts" text layer (hand-written YAML per major airport, sourced) alongside the numbers.
