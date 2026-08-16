from __future__ import annotations

from airport_agent.contracts import FeatureMatrix, Metric
from airport_agent.scoring.explain import explain_compare, explain_diagnose, explain_rank, fmt_value
from airport_agent.scoring.presets import load_presets
from airport_agent.scoring.scorer import Scorer
from tests.fakes import AIRPORTS

REFS = {a.iata: a for a in AIRPORTS}


def _metric(mid, iata, v, unit="pct"):
    return Metric(id=mid, value=v, unit=unit, horizon="12m", period_start="2025-05", period_end="2026-04",
                  source_id="bts_socrata", vintage="2026-04")


def test_fmt_value_units(by_id):
    assert fmt_value(by_id["enpl_cagr_5y"], 0.061) == "6.1%"
    assert fmt_value(by_id["load_factor"], 0.8234) == "0.82"
    assert fmt_value(by_id["avg_dep_delay_min"], 13.5) == "13.5 min"
    assert fmt_value(by_id["cpe_usd"], 18.5) == "$18.50"
    assert fmt_value(by_id["cbsa_population"], 4900000) == "4,900,000"
    assert fmt_value(by_id["load_factor"], None) == "n/a"


def test_fmt_value_turns_one_decimal(by_id):
    assert fmt_value(by_id["deps_per_gate_day"], 8.3) == "8.3"


def test_fmt_value_trips_is_rate_not_count(by_id):
    # pax_per_capita (unit "trips") is enplanements per resident, typically 0.3-12 -- must NOT
    # collapse to a thousands-separated integer ("0"/"1"); format like a ratio.
    assert fmt_value(by_id["pax_per_capita"], 4.1) == "4.10"


def test_fmt_value_flag_and_ordinal_are_plain_integers(by_id):
    assert fmt_value(by_id["slot_or_cap_flag"], 1.0) == "1"
    assert fmt_value(by_id["npias_capacity_label"], 3.0) == "3"


def test_fmt_value_days_and_sqft_are_thousands_ints(by_id):
    assert fmt_value(by_id["days_cash"], 245.0) == "245"
    assert fmt_value(by_id["terminal_sqft_per_nbeg"], 125000.0) == "125,000"


def test_explain_rank_names_pillar_metric_and_source(specs, by_id):
    fm = FeatureMatrix(airports=[REFS["BDL"], REFS["PVD"]], metric_ids=["enpl_cagr_5y", "load_factor"], horizon="5y",
                       values=[[0.061, 0.83], [0.023, 0.84]], peer_group="hub_class")
    # BDL medium, PVD small: different hub classes -> both pct 0.5; force peer_group all for a real ordering
    fm = fm.model_copy(update={"peer_group": "all"})
    res = Scorer(specs).score(fm, load_presets()["balanced"])
    ev = {("BDL", "enpl_cagr_5y"): _metric("enpl_cagr_5y", "BDL", 0.061),
          ("PVD", "enpl_cagr_5y"): _metric("enpl_cagr_5y", "PVD", 0.023),
          ("BDL", "load_factor"): _metric("load_factor", "BDL", 0.83, "ratio"),
          ("PVD", "load_factor"): _metric("load_factor", "PVD", 0.84, "ratio")}
    text = explain_rank(res, by_id, ev, "balanced", "5y", "all")
    assert text.startswith("Ranked 2 airports on balanced weights over 5y, as percentiles among all airports.")
    assert "ranks above" in text and "Demand Pressure" in text
    assert "6.1%" in text and "2.3%" in text and "BTS T-100 airport totals" in text and "2026-04" in text


def test_explain_rank_notes_absent_pillars(specs, by_id):
    fm = FeatureMatrix(airports=[REFS["BDL"], REFS["PVD"]], metric_ids=["enpl_cagr_5y", "load_factor"], horizon="5y",
                       values=[[0.061, 0.83], [0.023, 0.84]], peer_group="all")
    res = Scorer(specs).score(fm, load_presets()["balanced"])
    assert res.absent_pillars  # P3/P4/P5 have no metric in this matrix
    ev: dict = {}
    text = explain_rank(res, by_id, ev, "balanced", "5y", "all", absent_weight=0.45)
    assert "not scored" in text
    assert "forgone preset weight 0.45" in text
    assert "renormalized" in text
    for p in res.absent_pillars:
        from airport_agent.contracts import PILLAR_NAMES
        assert PILLAR_NAMES[p] in text

    text_no_weight = explain_rank(res, by_id, ev, "balanced", "5y", "all")
    assert "not scored" in text_no_weight
    assert "forgone" not in text_no_weight


def test_explain_compare_has_congestion_index_and_gaps(specs, by_id):
    fm = FeatureMatrix(airports=[REFS["LAX"], REFS["SNA"]], metric_ids=["avg_dep_delay_min", "taxi_out_p80_min"],
                       horizon="12m", values=[[12.9, 22.0], [13.9, 15.0]], peer_group="all")
    res = Scorer(specs).score(fm, load_presets()["congestion_relief"])
    ev = {("LAX", "avg_dep_delay_min"): _metric("avg_dep_delay_min", "LAX", 12.9, "min"),
          ("SNA", "avg_dep_delay_min"): _metric("avg_dep_delay_min", "SNA", 13.9, "min"),
          ("LAX", "taxi_out_p80_min"): _metric("taxi_out_p80_min", "LAX", 22.0, "min"),
          ("SNA", "taxi_out_p80_min"): _metric("taxi_out_p80_min", "SNA", 15.0, "min")}
    text = explain_compare(res, by_id, ev, ["LAX", "SNA"], "12m", "all")
    assert "Congestion index" in text and "LAX" in text and "SNA" in text
    assert "12.9 min" in text and "13.9 min" in text


def test_explain_diagnose_lists_signals():
    text = explain_diagnose("SFO", [("lf_spill", True, "high load factor with variable demand (spill likely)"),
                                    ("npias", False, "FAA NPIAS lists the airport as capacity constrained")])
    assert text.startswith("Signals of unmet demand at SFO: 1 of 2 present.")
    assert "✔ high load factor" in text and "✘ FAA NPIAS" in text
