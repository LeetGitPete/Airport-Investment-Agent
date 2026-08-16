from __future__ import annotations

import pytest

from airport_agent.contracts import AirportFilter, AnalysisRequest, DeterministicReport
from airport_agent.scoring.analyst import Analyst


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_rank_new_england_terminal_expansion(analyst):
    req = AnalysisRequest(question_type="rank", filter=AirportFilter(faa_regions=["ANE"]),
                          scoring_preset="terminal_expansion", horizons=["5y"])
    rep = analyst.rank(req)
    assert isinstance(rep, DeterministicReport)
    assert rep.preset == "terminal_expansion" and rep.horizon == "5y" and rep.peer_group == "hub_class"
    assert [r.ref.iata for r in rep.rows] and {r.ref.faa_region for r in rep.rows} == {"ANE"}
    assert [r.rank for r in rep.rows] == list(range(1, len(rep.rows) + 1))
    assert all(0 <= r.score <= 100 for r in rep.rows)
    assert rep.weights["P1"] == 0.35 and "load_factor" in rep.weights
    assert rep.percentiles and set(rep.percentiles["load_factor"]) == {r.ref.iata for r in rep.rows}
    assert rep.explanation.startswith("Ranked")
    assert any("Percentiles computed within hub_class" in c for c in rep.caveats)


def test_rank_single_airport_expands_to_hub_size_peers(analyst, fake):
    # One airport cannot be ranked on its own — it is ranked
    # within its hub-size class instead, with the expansion disclosed as a caveat.
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["SFO"], horizons=["12m"]))
    iatas = [r.ref.iata for r in rep.rows]
    assert "SFO" in iatas and len(iatas) > 1
    sfo_hub = fake.get_airport("SFO").hub_size
    assert all(r.ref.hub_size == sfo_hub for r in rep.rows)
    assert len(iatas) <= Analyst.PEER_EXPANSION_LIMIT
    assert any("cannot be ranked" in c and "expanded" in c for c in rep.caveats)
    assert rep.comparison and "SFO" in next(iter(rep.comparison.values()))


def test_rank_evidence_carries_source_and_vintage(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"]))
    assert rep.evidence and all(m.source_id and m.vintage for m in rep.evidence)
    assert {m.id for m in rep.evidence} >= {"load_factor", "avg_dep_delay_min"}
    assert rep.curated_facts and {f.iata for f in rep.curated_facts} <= {"SFO", "LAX"}


def test_rank_percentiles_use_universe_not_only_targets(analyst):
    # BOS alone among the targets is a large hub; its percentiles must still vary because the universe has 5 large hubs
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "PVD"], horizons=["12m"]))
    bos_pcts = {m: v["BOS"] for m, v in rep.percentiles.items() if v.get("BOS") is not None}
    assert len(set(bos_pcts.values())) > 1


def test_rank_default_preset_and_peer_group(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "JFK"]))
    assert rep.preset == "balanced" and rep.peer_group == "hub_class" and rep.horizon == "5y"


def test_rank_unknown_preset_is_rejected_never_invented(analyst):
    with pytest.raises(ValueError, match="unknown scoring preset"):
        analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS"], scoring_preset="made_up"))


def test_rank_focus_metrics_restricts_scored_set(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"],
                                       focus_metrics=["load_factor", "avg_dep_delay_min", "asv_utilization"]))
    assert set(rep.percentiles) == {"load_factor", "avg_dep_delay_min"}  # tier C dropped
    for r in rep.rows:
        assert set(r.metric_contrib) <= {"load_factor", "avg_dep_delay_min"}


def test_rank_region_peer_group_adds_warning(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "PVD"], peer_group="region"))
    assert rep.peer_group == "region" and any("widens comparison" in c for c in rep.caveats)


def test_rank_5y_horizon_marks_12m_only_metrics_missing_not_relabelled(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["5y"]))
    # taxi_out_p80_min declares only 12m -> None at 5y for everyone -> not in any contrib
    assert all("taxi_out_p80_min" not in r.metric_contrib for r in rep.rows)
    taxi = [m for m in rep.evidence if m.id == "taxi_out_p80_min"]
    assert taxi and all(m.value is None and m.horizon == "12m" for m in taxi)


def test_rank_empty_filter_result_raises(analyst):
    with pytest.raises(ValueError, match="no airports"):
        analyst.rank(AnalysisRequest(question_type="rank", filter=AirportFilter(states=["ZZ"])))


def test_golden_congestion_relief_puts_npias_constrained_large_hubs_on_top(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO", "JFK", "ATL", "DEN"],
                                       scoring_preset="congestion_relief", horizons=["12m"]))
    top3 = [r.ref.iata for r in rep.rows[:3]]
    assert set(top3) <= {"SFO", "JFK", "BOS", "LAX"}  # NPIAS constrained/severe in the fake; DEN/ATL below


def test_rank_absent_pillar_caveat_mentions_pillar_and_forgone_weight(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"],
                                       scoring_preset="balanced", focus_metrics=["load_factor"]))
    caveat = next(c for c in rep.caveats if c.startswith("Pillars "))
    assert "P2" in caveat and "0.70" in caveat


def test_rank_absent_weight_reaches_the_explanation_too(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"],
                                       scoring_preset="balanced", focus_metrics=["load_factor"]))
    assert "forgone preset weight 0.70" in rep.explanation


def test_rank_all_focus_metrics_unscoreable_raises_never_ranks_on_nothing(analyst):
    # asv_utilization is tier C -> never scoreable under any preset; ranking must fail loudly, not
    # silently emit an alphabetical (score=0 for everyone) ranking.
    with pytest.raises(ValueError, match="no scoreable metrics"):
        analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["12m"],
                                     focus_metrics=["asv_utilization"]))


def test_rank_focus_metrics_partial_drop_is_disclosed_in_a_caveat(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["12m"],
                                       focus_metrics=["not_a_metric", "load_factor", "asv_utilization"]))
    dropped = next(c for c in rep.caveats if c.startswith("focus_metrics dropped:"))
    assert "not_a_metric" in dropped and "asv_utilization" in dropped
    # the surviving metric still scores normally
    assert set(rep.percentiles) == {"load_factor"}


def test_rank_unknown_target_airport_raises_key_error(analyst):
    with pytest.raises(KeyError):
        analyst.rank(AnalysisRequest(question_type="rank", airports=["ZZZ"], horizons=["12m"]))


def test_rank_duplicate_targets_are_deduped(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "BOS"], horizons=["12m"]))
    assert [r.ref.iata for r in rep.rows].count("BOS") == 1
    assert len(rep.rows) == 2


def test_rank_empty_horizons_raises_value_error_not_index_error(analyst):
    with pytest.raises(ValueError, match="horizons must not be empty"):
        analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS"], horizons=[]))
