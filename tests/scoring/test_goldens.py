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


def test_scale_metrics_small_ne_airports_do_not_beat_bos_when_peer_group_all(analyst):
    # compare() normalizes percentiles across the whole DataService universe (limitations row 22), same as
    # rank/diagnose; with peer_group="all" that is one flat group, so BOS is not necessarily the global max
    # on scale metrics (JFK/LAX/BUR/ATL are bigger) -- the golden checks BOS ranks above the small NE peers
    # actually being compared, not that BOS is the universe max.
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "PVD", "MHT"], horizons=["12m"],
                                          focus_metrics=["cbsa_population", "route_count_nonstop"],
                                          peer_group="all"))
    for m in ("cbsa_population", "route_count_nonstop"):
        pct = rep.percentiles[m]
        assert pct["BOS"] > pct["PVD"] and pct["BOS"] > pct["MHT"]


def test_sfo_imc_ratio_below_lax(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["SFO", "LAX"], horizons=["12m"],
                                          focus_metrics=["imc_capacity_ratio"]))
    assert rep.comparison["imc_capacity_ratio"]["SFO"] < rep.comparison["imc_capacity_ratio"]["LAX"]
