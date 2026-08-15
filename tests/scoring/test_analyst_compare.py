from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest, Metric
from airport_agent.scoring.analyst import Analyst

P2 = ["pct_arr_delay_gt15", "avg_dep_delay_min", "nas_delay_share", "taxi_out_p80_min", "ops_per_runway",
      "npias_capacity_label", "peak_hour_ops_ratio", "slot_or_cap_flag"]


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_compare_lax_vs_sna_congestion(analyst):
    req = AnalysisRequest(question_type="compare", airports=["LAX", "SNA"], focus_metrics=P2, horizons=["12m"],
                          scoring_preset="congestion_relief")
    rep = analyst.compare(req)
    assert rep.question_type == "compare" and rep.comparison is not None
    assert set(rep.comparison) == set(P2)
    assert rep.comparison["avg_dep_delay_min"] == {"LAX": 12.9, "SNA": 13.9}
    assert {r.ref.iata for r in rep.rows} == {"LAX", "SNA"}
    assert "Congestion index" in rep.explanation
    assert rep.evidence and all(m.source_id and m.vintage for m in rep.evidence)
    assert set(rep.percentiles) == set(P2)


def test_compare_defaults_to_all_scoreable_metrics(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "BDL"]))
    assert rep.comparison is not None and "load_factor" in rep.comparison and "asv_utilization" not in rep.comparison
    assert rep.preset == "balanced" and rep.horizon == "5y"


def test_compare_tier_c_focus_metric_reported_as_unavailable(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "LAX"], horizons=["12m"],
                                          focus_metrics=["load_factor", "asv_utilization"]))
    assert rep.comparison["asv_utilization"] == {"BOS": None, "LAX": None}
    assert "asv_utilization" not in rep.percentiles
    assert any("asv_utilization" in c or "not computable" in c.lower() or "ASV" in c for c in rep.caveats)


def test_compare_single_airport_allowed(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["SFO"], horizons=["12m"]))
    assert [r.ref.iata for r in rep.rows] == ["SFO"]


def test_distance_bands_and_long_haul_share_delegate(analyst):
    bands = analyst.distance_bands("ANC", horizon="12m", freight=False)
    assert set(bands) == {"short", "medium", "long", "ultra"} and abs(sum(bands.values()) - 1) < 1e-9
    m = analyst.long_haul_share("ANC", threshold_mi=1500, horizon="12m", freight=True)
    assert isinstance(m, Metric) and m.id == "longhaul_dep_share" and m.value > 0.9
    pax = analyst.long_haul_share("ANC", horizon="12m", freight=False)
    assert pax.value < m.value


def test_long_haul_unknown_airport_raises_key_error(analyst):
    with pytest.raises(KeyError):
        analyst.long_haul_share("ZZZ")
