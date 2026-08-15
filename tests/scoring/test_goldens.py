"""Golden checks from design 02 §Validation, run against FakeDataService (fixture values, not facts)."""
from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest
from airport_agent.scoring import Analyst, load_presets


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_monotonicity_higher_up_metric_never_lowers_score(analyst, fake):
    # PVD vs a hypothetical: within the fake, ranking on a single up-metric orders by value
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["PVD", "MHT", "PWM"], horizons=["12m"],
                                       focus_metrics=["load_factor"], peer_group="all"))
    order = [r.ref.iata for r in rep.rows]
    assert order == sorted(order, key=lambda i: -rep.percentiles["load_factor"][i])
    assert order[0] == "PVD"  # highest load_factor in the fake among the three


def test_direction_flip_down_metric(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["ATL", "JFK"], horizons=["12m"],
                                       focus_metrics=["carrier_hhi"], peer_group="all"))
    assert rep.rows[0].ref.iata == "JFK"  # lower HHI (less concentrated) ranks higher


def test_all_presets_produce_full_rankings(analyst):
    for name in load_presets():
        rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO", "JFK", "ATL", "DEN"],
                                           scoring_preset=name, horizons=["12m"]))
        assert len(rep.rows) == 6 and rep.preset == name


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DECISION NEEDED (see task-7-9-report.md): this golden assumes BOS's cbsa_population/"
        "route_count_nonstop percentile is 1.0 when compared against PVD/MHT with peer_group='all'. "
        "Analyst.compare computes percentiles across the whole DataService universe (13 airports in "
        "FakeDataService, per limitations row 22 / task-7 brief, reusing _score_targets exactly as "
        "rank/diagnose do) then filters the display to the 3 targets. With peer_group='all' that universe "
        "is one flat group of all 13 fake airports, and BOS (cbsa_population 4.9e6, route_count_nonstop 140) "
        "is NOT the max there -- JFK/LAX/BUR/ATL are bigger on population, DEN/LAX/ATL on route count -- so "
        "BOS's percentile is 0.667, not 1.0. The assertion only holds if compare() scoped percentiles to "
        "just the compared airports (BOS alone in the 'large' hub bucket -> trivially 1.0) instead of the "
        "full universe. Left as an unresolved xfail pending a human decision; not weakened."
    ),
)
def test_scale_metrics_small_ne_airports_do_not_beat_bos_when_peer_group_all(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "PVD", "MHT"], horizons=["12m"],
                                          focus_metrics=["cbsa_population", "route_count_nonstop"],
                                          peer_group="all"))
    for m in ("cbsa_population", "route_count_nonstop"):
        assert rep.percentiles[m]["BOS"] == 1.0


def test_sfo_imc_ratio_below_lax(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["SFO", "LAX"], horizons=["12m"],
                                          focus_metrics=["imc_capacity_ratio"]))
    assert rep.comparison["imc_capacity_ratio"]["SFO"] < rep.comparison["imc_capacity_ratio"]["LAX"]
