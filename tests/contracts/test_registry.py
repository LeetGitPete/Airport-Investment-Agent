import pytest

from airport_agent.contracts.registry import PILLAR_NAMES, load_pillars, load_registry, registry_by_id

EXPECTED_IDS = {
    "enpl_cagr_3y", "enpl_cagr_5y", "enpl_cagr_10y", "taf_cagr_10y", "taf_vs_actual_gap", "load_factor", "spill_proxy",
    "seats_per_dep_trend", "pax_per_capita",
    "pct_arr_delay_gt15", "avg_dep_delay_min", "nas_delay_share", "taxi_out_p80_min", "ops_per_runway", "npias_capacity_label",
    "peak_hour_ops_ratio", "pax_per_gate", "deps_per_gate_day", "imc_capacity_ratio", "slot_or_cap_flag",
    "carrier_hhi", "top_carrier_share", "intl_pax_share", "longhaul_dep_share", "route_count_nonstop", "competing_seats_100mi", "od_share",
    "cbsa_population", "cbsa_pop_cagr_5y", "msa_gdp_per_capita", "msa_gdp_cagr_5y",
    "npias_dev_per_enpl", "aip_per_enpl_10y", "cpe_usd", "nonaero_rev_per_enpl",
    "asv_utilization", "terminal_sqft_per_nbeg", "dscr", "days_cash", "use_agreement_type",
}


def test_registry_loads_all_ids_unique():
    specs = load_registry()
    ids = [s.id for s in specs]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED_IDS


def test_registry_pillars_and_tiers():
    by = registry_by_id(load_registry())
    assert set(PILLAR_NAMES) == {"P1", "P2", "P3", "P4", "P5"}
    assert by["cpe_usd"].direction == "down" and by["cpe_usd"].pillar == "P5" and by["cpe_usd"].tier == "A"
    assert by["pax_per_gate"].tier == "B"
    assert by["asv_utilization"].tier == "C"
    assert all(s.sources for s in by.values()) and all(s.horizons for s in by.values())
    assert any("unaudited" in c.lower() for c in by["cpe_usd"].caveats)


def test_pillars_match_names_and_weights_sum_to_one():
    pillars = load_pillars()
    assert set(pillars) == set(PILLAR_NAMES)
    assert {k: v["name"] for k, v in pillars.items()} == PILLAR_NAMES
    assert abs(sum(v["default_weight"] for v in pillars.values()) - 1.0) < 1e-9




DUP_YAML = """
pillars:
  P1: {name: Demand Pressure, default_weight: 1.0}
metrics:
  - {id: load_factor, name: LF, definition: d, formula: f, unit: ratio, direction: up, pillar: P1,
     tier: A, sources: [bts_t100], horizons: [12m]}
  - {id: load_factor, name: LF again, definition: d, formula: f, unit: ratio, direction: up, pillar: P1,
     tier: A, sources: [bts_t100], horizons: [12m]}
"""


def test_duplicate_metric_ids_rejected(tmp_path):
    dup = tmp_path / "metrics.yaml"
    dup.write_text(DUP_YAML, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(dup)
