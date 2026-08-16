# Hygiene sweep checklist

Ledger for the file-by-file hygiene sweep. The sweep is not finished while any row says `pending`.

Total files: **182**

## 0. src (root)

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/__init__.py` | 2 | done | |

## 1. src/contracts (READ-ONLY, log only)

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/contracts/__init__.py` | 119 | done | read-only, logged only |
| `src/airport_agent/contracts/conversation.py` | 82 | done | read-only, logged only |
| `src/airport_agent/contracts/data_service.py` | 86 | done | read-only, logged only |
| `src/airport_agent/contracts/llm.py` | 42 | done | read-only, logged only |
| `src/airport_agent/contracts/models.py` | 190 | done | read-only, logged only |
| `src/airport_agent/contracts/registry.py` | 34 | done | read-only, logged only |
| `src/airport_agent/contracts/reports.py` | 64 | done | read-only, logged only |
| `src/airport_agent/contracts/requests.py` | 66 | done | read-only, logged only |
| `src/airport_agent/contracts/scoring.py` | 34 | done | read-only, logged only |
| `src/airport_agent/contracts/specialists.py` | 16 | done | read-only, logged only |
| `src/airport_agent/contracts/tools.py` | 20 | done | read-only, logged only |

## 10. repo root

| file | lines | status | notes |
|---|---|---|---|
| `conftest.py` | 10 | done |  |

## 2a. src/data/adapters

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/data/adapters/__init__.py` | 30 | done |  |
| `src/airport_agent/data/adapters/base.py` | 134 | done |  |
| `src/airport_agent/data/adapters/bts_otp.py` | 341 | done |  |
| `src/airport_agent/data/adapters/bts_socrata.py` | 281 | done |  |
| `src/airport_agent/data/adapters/bts_t100.py` | 281 | done |  |
| `src/airport_agent/data/adapters/census_cbsa.py` | 307 | done |  |
| `src/airport_agent/data/adapters/curated.py` | 158 | done |  |
| `src/airport_agent/data/adapters/faa_aip.py` | 226 | done |  |
| `src/airport_agent/data/adapters/faa_nasstatus.py` | 173 | done |  |
| `src/airport_agent/data/adapters/faa_npias.py` | 250 | done |  |
| `src/airport_agent/data/adapters/faa_taf.py` | 275 | done |  |
| `src/airport_agent/data/adapters/ourairports.py` | 192 | done |  |

## 2b. src/data/derived

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/data/derived/__init__.py` | 222 | done |  |
| `src/airport_agent/data/derived/common.py` | 153 | done |  |
| `src/airport_agent/data/derived/p1_demand.py` | 275 | done |  |
| `src/airport_agent/data/derived/p2_congestion.py` | 340 | done |  |
| `src/airport_agent/data/derived/p3_market.py` | 209 | done |  |
| `src/airport_agent/data/derived/p4_economy.py` | 64 | done |  |
| `src/airport_agent/data/derived/p5_finance.py` | 64 | done |  |

## 2c. src/data (core)

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/data/__init__.py` | 12 | done |  |
| `src/airport_agent/data/__main__.py` | 101 | done |  |
| `src/airport_agent/data/commercial.py` | 23 | done |  |
| `src/airport_agent/data/geo.py` | 16 | done |  |
| `src/airport_agent/data/http.py` | 97 | done |  |
| `src/airport_agent/data/paths.py` | 28 | done |  |
| `src/airport_agent/data/quality.py` | 98 | done |  |
| `src/airport_agent/data/refresh.py` | 276 | done |  |
| `src/airport_agent/data/service.py` | 396 | done |  |
| `src/airport_agent/data/sources_config.py` | 39 | done |  |
| `src/airport_agent/data/store.py` | 342 | done |  |

## 3. src/scoring

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/scoring/__init__.py` | 8 | done | |
| `src/airport_agent/scoring/analyst.py` | 309 | done | |
| `src/airport_agent/scoring/calculators.py` | 41 | done | |
| `src/airport_agent/scoring/explain.py` | 109 | done | |
| `src/airport_agent/scoring/percentiles.py` | 51 | done | |
| `src/airport_agent/scoring/presets.py` | 50 | done | |
| `src/airport_agent/scoring/scorer.py` | 100 | done | |

## 4. src/llm

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/llm/__init__.py` | 15 | done | |
| `src/airport_agent/llm/client.py` | 83 | done | |
| `src/airport_agent/llm/config.py` | 35 | done | |
| `src/airport_agent/llm/jsonutil.py` | 26 | done | |

## 5a. src/agent/tools

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/agent/tools/__init__.py` | 1 | done | |
| `src/airport_agent/agent/tools/analysis_tools.py` | 144 | done | |
| `src/airport_agent/agent/tools/data_tools.py` | 231 | done | |
| `src/airport_agent/agent/tools/provenance.py` | 111 | done | |
| `src/airport_agent/agent/tools/registry.py` | 148 | done | |

## 5b. src/agent/specialists

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/agent/specialists/__init__.py` | 20 | done | |
| `src/airport_agent/agent/specialists/loader.py` | 97 | done | |
| `src/airport_agent/agent/specialists/runner.py` | 257 | done | |
| `src/airport_agent/agent/specialists/schema.py` | 79 | done | |

## 5c. src/agent (core)

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/agent/__init__.py` | 35 | done | |
| `src/airport_agent/agent/app.py` | 110 | done | |
| `src/airport_agent/agent/concierge.py` | 300 | done | |
| `src/airport_agent/agent/planner.py` | 532 | done | |
| `src/airport_agent/agent/sessions.py` | 56 | done | |
| `src/airport_agent/agent/synthesis.py` | 404 | done | |
| `src/airport_agent/agent/tables.py` | 431 | done | |

## 6. src/ui

| file | lines | status | notes |
|---|---|---|---|
| `src/airport_agent/ui/__init__.py` | 1 | done | |
| `src/airport_agent/ui/bootstrap.py` | 28 | done | |
| `src/airport_agent/ui/cli.py` | 70 | done | |
| `src/airport_agent/ui/render.py` | 164 | done | |
| `src/airport_agent/ui/sidebar.py` | 171 | done | |
| `src/airport_agent/ui/streamlit_app.py` | 76 | done | |
| `src/airport_agent/ui/textfmt.py` | 100 | done | |

## 7. config

| file | lines | status | notes |
|---|---|---|---|
| `config/metrics.yaml` | 119 | done | frozen; comments clean, no findings |
| `config/providers.yaml` | 14 | done |  |
| `config/scoring_presets.yaml` | 39 | done |  |
| `config/sources.yaml` | 138 | done |  |
| `config/specialists/capacity_analyst.md` | 60 | done |  |
| `config/specialists/expansion_analyst.md` | 54 | done |  |
| `config/specialists/general_analyst.md` | 58 | done |  |
| `config/specialists/market_analyst.md` | 55 | done |  |

## 8. scripts

| file | lines | status | notes |
|---|---|---|---|
| `scripts/make_zip.py` | 74 | done |  |

## 9a. tests/contracts

| file | lines | status | notes |
|---|---|---|---|
| `tests/contracts/__init__.py` | 0 | pending | |
| `tests/contracts/conftest.py` | 41 | pending | |
| `tests/contracts/test_data_service_contract.py` | 113 | pending | |
| `tests/contracts/test_factories_extension.py` | 37 | pending | |
| `tests/contracts/test_models.py` | 97 | pending | |
| `tests/contracts/test_protocols.py` | 33 | pending | |
| `tests/contracts/test_registry.py` | 56 | pending | |
| `tests/contracts/test_requests.py` | 118 | pending | |

## 9b. tests/data

| file | lines | status | notes |
|---|---|---|---|
| `tests/data/__init__.py` | 0 | pending | |
| `tests/data/build_test_snapshot.py` | 110 | pending | |
| `tests/data/conftest.py` | 42 | pending | |
| `tests/data/conftest_plugin.py` | 17 | pending | |
| `tests/data/test_base.py` | 183 | pending | |
| `tests/data/test_bts_otp.py` | 165 | pending | |
| `tests/data/test_bts_socrata.py` | 164 | pending | |
| `tests/data/test_bts_t100.py` | 159 | pending | |
| `tests/data/test_census_cbsa.py` | 194 | pending | |
| `tests/data/test_curated.py` | 111 | pending | |
| `tests/data/test_derived_common.py` | 160 | pending | |
| `tests/data/test_derived_p1.py` | 138 | pending | |
| `tests/data/test_derived_p2.py` | 102 | pending | |
| `tests/data/test_derived_p3.py` | 117 | pending | |
| `tests/data/test_derived_p4.py` | 79 | pending | |
| `tests/data/test_derived_p5.py` | 135 | pending | |
| `tests/data/test_derived_registry.py` | 172 | pending | |
| `tests/data/test_faa_aip.py` | 121 | pending | |
| `tests/data/test_faa_nasstatus.py` | 156 | pending | |
| `tests/data/test_faa_npias.py` | 171 | pending | |
| `tests/data/test_faa_taf.py` | 281 | pending | |
| `tests/data/test_http_pacer.py` | 107 | pending | |
| `tests/data/test_ourairports.py` | 290 | pending | |
| `tests/data/test_quality.py` | 66 | pending | |
| `tests/data/test_refresh.py` | 176 | pending | |
| `tests/data/test_service.py` | 99 | pending | |
| `tests/data/test_store.py` | 358 | pending | |

## 9c. tests/scoring

| file | lines | status | notes |
|---|---|---|---|
| `tests/scoring/__init__.py` | 0 | pending | |
| `tests/scoring/conftest.py` | 21 | pending | |
| `tests/scoring/test_analyst_compare.py` | 60 | pending | |
| `tests/scoring/test_analyst_diagnose.py` | 44 | pending | |
| `tests/scoring/test_analyst_rank.py` | 142 | pending | |
| `tests/scoring/test_calculators.py` | 66 | pending | |
| `tests/scoring/test_explain.py` | 98 | pending | |
| `tests/scoring/test_goldens.py` | 53 | pending | |
| `tests/scoring/test_percentiles.py` | 49 | pending | |
| `tests/scoring/test_presets.py` | 52 | pending | |
| `tests/scoring/test_protocol.py` | 9 | pending | |
| `tests/scoring/test_scorer.py` | 203 | pending | |

## 9d. tests/agent

| file | lines | status | notes |
|---|---|---|---|
| `tests/agent/__init__.py` | 0 | pending | |
| `tests/agent/conftest.py` | 22 | pending | |
| `tests/agent/fake_analyst.py` | 134 | pending | |
| `tests/agent/fake_llm.py` | 38 | pending | |
| `tests/agent/test_analysis_tools.py` | 38 | pending | |
| `tests/agent/test_app.py` | 79 | pending | |
| `tests/agent/test_concierge.py` | 254 | pending | |
| `tests/agent/test_data_tools.py` | 64 | pending | |
| `tests/agent/test_fakes.py` | 33 | pending | |
| `tests/agent/test_planner.py` | 227 | pending | |
| `tests/agent/test_provenance.py` | 28 | pending | |
| `tests/agent/test_provenance_sweep.py` | 147 | pending | |
| `tests/agent/test_registry.py` | 112 | pending | |
| `tests/agent/test_schemas.py` | 49 | pending | |
| `tests/agent/test_sessions.py` | 97 | pending | |
| `tests/agent/test_specialist_loader.py` | 101 | pending | |
| `tests/agent/test_specialist_runner.py` | 158 | pending | |
| `tests/agent/test_synthesis.py` | 111 | pending | |
| `tests/agent/test_tables.py` | 196 | pending | |

## 9e. tests/llm

| file | lines | status | notes |
|---|---|---|---|
| `tests/llm/__init__.py` | 0 | pending | |
| `tests/llm/test_client.py` | 106 | pending | |
| `tests/llm/test_config.py` | 33 | pending | |

## 9f. tests/fixtures (fixture builders)

| file | lines | status | notes |
|---|---|---|---|
| `tests/fixtures/bts_otp/make_fixture.py` | 63 | pending | |
| `tests/fixtures/bts_socrata/make_fixture.py` | 53 | pending | |
| `tests/fixtures/bts_t100/make_fixture.py` | 65 | pending | |
| `tests/fixtures/bts_t100/make_fixture_extra_months.py` | 56 | pending | |
| `tests/fixtures/census_cbsa/make_fixture.py` | 91 | pending | |
| `tests/fixtures/faa_aip/make_fixture.py` | 95 | pending | |
| `tests/fixtures/faa_nasstatus/make_fixture.py` | 30 | pending | |
| `tests/fixtures/faa_npias/make_fixture.py` | 41 | pending | |
| `tests/fixtures/faa_taf/make_fixture.py` | 51 | pending | |
| `tests/fixtures/ourairports/make_fixture.py` | 47 | pending | |

## 9g. tests/ui

| file | lines | status | notes |
|---|---|---|---|
| `tests/ui/__init__.py` | 0 | pending | |
| `tests/ui/conftest.py` | 16 | pending | |
| `tests/ui/fake_app.py` | 275 | pending | |
| `tests/ui/test_cli.py` | 64 | pending | |
| `tests/ui/test_persistence.py` | 50 | pending | |
| `tests/ui/test_render.py` | 34 | pending | |
| `tests/ui/test_sidebar.py` | 143 | pending | |
| `tests/ui/test_streamlit_smoke.py` | 114 | pending | |
| `tests/ui/test_textfmt.py` | 43 | pending | |

## 9h. tests/golden

| file | lines | status | notes |
|---|---|---|---|
| `tests/golden/scripts.py` | 195 | pending | |
| `tests/golden/test_sample_questions.py` | 175 | pending | |

## 9i. tests/hooks

| file | lines | status | notes |
|---|---|---|---|
| `tests/hooks/__init__.py` | 0 | pending | |
| `tests/hooks/test_hooks.py` | 61 | pending | |

## 9j. tests (root)

| file | lines | status | notes |
|---|---|---|---|
| `tests/__init__.py` | 0 | pending | |
| `tests/conftest.py` | 31 | pending | |
| `tests/fakes.py` | 389 | pending | |
| `tests/test_smoke.py` | 11 | pending | |
