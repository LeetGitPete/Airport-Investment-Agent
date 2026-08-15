# Known Limitations & Key Tradeoffs (living log)

Each entry: **What** · **Type** (Constraint = imposed by data/time; Decision = our choice) · **Impact** · **Mitigation** · **Status**.
This log feeds the "Key tradeoffs" section of the final DESIGN.md.

| # | What | Type | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| 1 | OTP raw detail (taxi-out, per-flight distance groups) only for trailing 24 months; ~270MB/month makes 10y raw infeasible in a day | Constraint | Delay *detail* trends limited to 2y | BTS Delay Cause dataset (airport-month, 2003→) for 10y delay trend | Accepted |
| 2 | T-100 International Segment table code not yet verified | To verify | Route-level intl detail may be missing | Socrata intl inbound/outbound totals (verified) as fallback | Open |
| 3 | FAA ASPM/OPSNET (official capacity/throughput) login-walled and unreachable | Constraint | No official hourly capacity vs demand; congestion inferred from delays, taxi-out, load factor, upgauging | Curated slot-level/runway facts; state as inference | Accepted |
| 4 | Pre-2014 per-airport monthly totals not in Socrata | Constraint (soft) | 10y horizon = 2016→2026 fine; deeper only via TAF annual actuals | TAF actuals 1976→ for enplanements/ops | Accepted |
| 5 | Terminal/gate counts not in any free dataset | Constraint | Cannot compute gates-per-Mpax directly | Curated YAML for ~30 major airports; note absence elsewhere | Accepted |
| 6 | Future airline schedules (OAG/Cirium) paid | Constraint | No forward capacity supply signal | FAA TAF forecast as demand-side substitute | Accepted |
| 7 | Airport financials (FAA CATS Form 127) | Resolved | Queryable per year/hub class; CPE on line 16.5 | Caveat: self-reported, unaudited, non-uniform basis — surface in answers | Resolved |
| 8 | Causal "why" (runway geometry, ATC rules) not structured | Constraint | Explanations need text | Curated, sourced airport_facts.yaml; LLM must cite it or say unknown | Accepted |
| 9 | Free-tier LLM limits (~10 RPM Gemini) | Constraint | Tool loops must be short; bursts hit 429 | ≤6 calls/answer, follow-ups reuse session memory; **no silent fallback — fail loudly with actionable message** | Accepted |
| 16 | Single LLM provider (Gemini free tier) for now; Groq/NIM fallbacks deferred | Decision | 429/outage ⇒ loud error rather than fail-over | LiteLLM router keeps the door open via `providers.yaml`; revisit at the end if time remains | Accepted |
| 10 | Snapshot committed in repo (≤100MB) rather than fetched at first run | Decision | Reviewer runs offline instantly; data ages | `refresh` command + `--check` staleness; vintages shown in answers | Accepted |
| 11 | In-process tools rather than MCP as primary transport | Decision | Simpler, provider-agnostic | Optional FastMCP wrapper over same registry | Accepted |
| 12 | One Concierge + structured dispatch to code (Deterministic Analyst) and LLM specialists, rather than free conversational multi-agent handoffs | Decision | Low variance, bounded LLM calls | Structured `AnalysisRequest` with ≤200-char hint (600 for general_analyst) | Accepted |
| 13 | Gemini key shipped in `.env` inside zip (throwaway account), not hosted | Decision | Zero-setup for reviewer; key revoked after review | `.env` gitignored; commit-guard hook; clear error if key missing/invalid | Accepted |
| 14 | O&D vs connecting share needs BTS DB1B/OD-40 (large quarterly files) | To verify | Central to Moody's/Fitch; without it P3 lacks the strongest market-quality signal | Timeboxed adapter attempt (1 recent year); else drop `od_share` and log | Open |
| 15 | No silent LLM degradation | Decision | If all providers fail, no answer is produced | Loud, actionable error message; provider chain is the resilience | Accepted |
