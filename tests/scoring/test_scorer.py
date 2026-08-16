from __future__ import annotations

import pytest

from airport_agent.contracts import FeatureMatrix
from airport_agent.scoring.presets import load_presets
from airport_agent.scoring.scorer import Scorer
from tests.fakes import AIRPORTS

REFS = {a.iata: a for a in AIRPORTS}


def _fm(iatas, metric_ids, values, horizon="12m", peer_group="hub_class"):
    return FeatureMatrix(airports=[REFS[i] for i in iatas], metric_ids=metric_ids, horizon=horizon,
                         values=values, peer_group=peer_group)


@pytest.fixture
def scorer(specs):
    return Scorer(specs)


@pytest.fixture
def balanced():
    return load_presets()["balanced"]


def test_scoreable_ids_excludes_tier_c_and_excluded(scorer, balanced, by_id):
    ids = scorer.scoreable_ids(balanced)
    assert "asv_utilization" not in ids and "dscr" not in ids  # tier C
    assert "aip_per_enpl_10y" not in ids  # excluded by preset
    assert "load_factor" in ids and "pax_per_gate" in ids  # tier A and B are scoreable
    assert all(by_id[i].tier != "C" for i in ids)


def test_contributions_sum_to_score_and_formula(scorer, balanced):
    # two large hubs, one metric per pillar P1..P5 -> percentiles 0/1
    ids = ["load_factor", "avg_dep_delay_min", "carrier_hhi", "cbsa_population", "cpe_usd"]
    fm = _fm(["BOS", "LAX"], ids, [[0.80, 10.0, 1000.0, 1e6, 10.0], [0.90, 20.0, 2000.0, 2e6, 20.0]])
    res = scorer.score(fm, balanced)
    by = {r.ref.iata: r for r in res.rows}
    for r in res.rows:
        assert r.score == pytest.approx(sum(r.metric_contrib.values()))
        assert r.score == pytest.approx(sum(r.pillar_contrib.values()))
    # LAX: higher LF (up) -> pct 1 -> P1 contrib = 0.30*1*1*100 = 30; delay up -> 25; hhi down -> 0; pop up -> 15; cpe down -> 0
    assert by["LAX"].metric_contrib["load_factor"] == pytest.approx(30.0)
    assert by["LAX"].metric_contrib["carrier_hhi"] == pytest.approx(0.0)
    assert by["LAX"].score == pytest.approx(70.0)
    assert by["BOS"].score == pytest.approx(30.0)  # hhi + cpe (down metrics) give BOS 15 + 15
    assert by["LAX"].rank == 1 and by["BOS"].rank == 2
    assert res.weights["P1"] == 0.30 and res.weights["load_factor"] == pytest.approx(1.0)


def test_missing_metric_renormalizes_and_reports_coverage(scorer, balanced):
    ids = ["load_factor", "spill_proxy", "avg_dep_delay_min"]
    fm = _fm(["BOS", "LAX", "SFO"], ids, [[0.80, 0.05, 10.0], [0.90, None, 20.0], [0.85, 0.07, 15.0]])
    res = scorer.score(fm, balanced)
    lax = next(r for r in res.rows if r.ref.iata == "LAX")
    assert lax.coverage == pytest.approx(2 / 3)
    assert "spill_proxy" not in lax.metric_contrib
    # with spill missing, LF carries the whole P1 weight for LAX: pct(LF)=1 -> P1 contrib = 0.30/(0.30+0.25)*100
    assert lax.pillar_contrib["P1"] == pytest.approx(0.30 / 0.55 * 100)


def test_low_confidence_when_pillar_coverage_below_half(scorer, balanced):
    ids = ["load_factor", "spill_proxy", "pax_per_capita", "enpl_cagr_3y"]  # four P1 metrics
    fm = _fm(["BOS", "LAX"], ids, [[0.8, 0.05, 4.0, 0.03], [0.9, None, None, None]], horizon="3y")
    res = scorer.score(fm, balanced)
    by = {r.ref.iata: r for r in res.rows}
    assert by["LAX"].low_confidence is True
    assert by["BOS"].low_confidence is False


def test_p5_always_normalized_within_hub_class_even_when_peer_group_all(scorer, balanced):
    # BOS large vs PVD small: with peer_group=all, cpe (down) would give PVD pct 1; within hub class both are 0.5
    fm = _fm(["BOS", "PVD"], ["cpe_usd"], [[18.5], [8.9]], peer_group="all")
    res = scorer.score(fm, balanced)
    assert res.percentiles["cpe_usd"] == {"BOS": 0.5, "PVD": 0.5}


def test_non_p5_metric_uses_requested_peer_group(scorer, balanced):
    fm = _fm(["BOS", "PVD"], ["load_factor"], [[0.82], [0.84]], peer_group="all")
    res = scorer.score(fm, balanced)
    assert res.percentiles["load_factor"] == {"BOS": 0.0, "PVD": 1.0}


def test_metric_weight_overrides_change_within_pillar_split(scorer):
    te = load_presets()["terminal_expansion"]
    fm = _fm(["BOS", "LAX"], ["pax_per_gate", "imc_capacity_ratio"], [[400000.0, 0.7], [500000.0, 0.8]])
    res = scorer.score(fm, te)
    # only P2 metrics are in the matrix -> P2's effective pillar weight renormalizes to 1.0;
    # pax_per_gate relative 3.0 vs imc 1.0 -> LAX gets 1.0 * 3/4 * 1 * 100 from pax_per_gate
    lax = next(r for r in res.rows if r.ref.iata == "LAX")
    assert lax.metric_contrib["pax_per_gate"] == pytest.approx(75.0)
    assert lax.metric_contrib["imc_capacity_ratio"] == pytest.approx(0.0)  # direction down: LAX 0.8 > BOS 0.7
    assert res.pillar_scores["LAX"]["P2"] == pytest.approx(75.0)
    assert res.weights["pax_per_gate"] == pytest.approx(0.75)  # nominal within-pillar weight is unaffected


def test_all_none_row_scores_zero_with_zero_coverage(scorer, balanced):
    fm = _fm(["BOS", "LAX"], ["load_factor"], [[None], [0.9]])
    res = scorer.score(fm, balanced)
    bos = next(r for r in res.rows if r.ref.iata == "BOS")
    assert bos.score == 0.0 and bos.coverage == 0.0 and bos.low_confidence is True


def test_pillar_scores_include_all_pillars_even_when_metric_missing(scorer, balanced):
    # BOS's only P2 metric (load_factor's pillar is P1; use avg_dep_delay_min for P2) is None -> P2 still keyed, 0.0
    fm = _fm(["BOS", "LAX"], ["avg_dep_delay_min"], [[None], [20.0]])
    res = scorer.score(fm, balanced)
    assert res.pillar_scores["BOS"]["P2"] == pytest.approx(0.0)
    assert set(res.pillar_scores["BOS"]) == {"P1", "P2", "P3", "P4", "P5"}
    assert set(res.pillar_scores["LAX"]) == {"P1", "P2", "P3", "P4", "P5"}


def test_duplicate_metric_ids_dedupe_to_one_metric(scorer, balanced):
    fm = _fm(["BOS", "LAX"], ["load_factor", "load_factor"], [[0.80, 0.80], [0.90, 0.90]])
    res = scorer.score(fm, balanced)
    assert res.scored_metric_ids == ["load_factor"]
    for r in res.rows:
        assert r.score == pytest.approx(sum(r.metric_contrib.values()))
        assert list(r.metric_contrib) == ["load_factor"]


def test_zero_relative_weight_metrics_drop_pillar_entirely():
    from airport_agent.scoring.presets import Preset
    preset = Preset(
        name="zero_p1",
        description="test",
        pillars={"P1": 0.30, "P2": 0.25, "P3": 0.15, "P4": 0.15, "P5": 0.15},
        metric_weights={"load_factor": 0.0},
        excluded_metrics=["aip_per_enpl_10y"],
    )
    from airport_agent.contracts import load_registry
    scorer = Scorer(load_registry())
    fm = _fm(["BOS", "LAX"], ["load_factor"], [[0.80], [0.90]])
    res = scorer.score(fm, preset)
    bos = next(r for r in res.rows if r.ref.iata == "BOS")
    assert bos.score == 0.0
    assert bos.low_confidence is True
    assert bos.pillar_contrib["P1"] == pytest.approx(0.0)
    assert res.pillar_scores["BOS"]["P1"] == pytest.approx(0.0)


def test_tier_c_and_excluded_ids_absent_from_result_and_dont_dilute_coverage(scorer, balanced):
    ids = ["load_factor", "dscr", "aip_per_enpl_10y"]
    fm = _fm(["BOS", "LAX"], ids, [[0.80, 1.5, 5.0], [0.90, 2.0, 6.0]])
    res = scorer.score(fm, balanced)
    assert "dscr" not in res.percentiles and "aip_per_enpl_10y" not in res.percentiles
    assert res.scored_metric_ids == ["load_factor"]
    for r in res.rows:
        assert "dscr" not in r.metric_contrib and "aip_per_enpl_10y" not in r.metric_contrib
        assert r.coverage == pytest.approx(1.0)


def test_absent_pillars_reports_structurally_missing_weighted_pillars(scorer):
    te = load_presets()["terminal_expansion"]
    fm = _fm(["BOS", "LAX"], ["pax_per_gate", "imc_capacity_ratio"], [[400000.0, 0.7], [500000.0, 0.8]])
    res = scorer.score(fm, te)
    assert res.absent_pillars == ["P1", "P3", "P4", "P5"]


def test_dead_weighted_metrics_names_an_upweighted_metric_with_no_data_anywhere(scorer):
    """terminal_expansion puts 3.0 on the gate metrics; with no gate data its focus silently
    inverts, because renormalization hands that weight to the metrics it damped to 0.5."""
    te = load_presets()["terminal_expansion"]
    ids = ["pax_per_gate", "taxi_out_p80_min"]
    fm = _fm(["BOS", "LAX"], ids, [[None, 10.0], [None, 20.0]])
    res = scorer.score(fm, te)
    assert res.dead_weighted_metrics == ["pax_per_gate"]
    # it is scoreable, so absent_pillars cannot see it — that is why this signal is separate
    assert "P2" not in res.absent_pillars
    assert all(r.metric_contrib.get("pax_per_gate") is None for r in res.rows)


def test_a_metric_with_data_for_some_airports_is_not_dead_weight(scorer):
    """One airport's gap is per-airport coverage, not a defeated preset — must not fire."""
    te = load_presets()["terminal_expansion"]
    fm = _fm(["BOS", "LAX"], ["pax_per_gate"], [[400000.0], [None]])
    assert scorer.score(fm, te).dead_weighted_metrics == []


def test_dead_weight_ignores_metrics_the_preset_never_upweighted(scorer, balanced):
    """balanced weights pax_per_gate at the 1.0 default: absent, but no stated emphasis is lost."""
    fm = _fm(["BOS", "LAX"], ["pax_per_gate", "taxi_out_p80_min"], [[None, 10.0], [None, 20.0]])
    assert scorer.score(fm, balanced).dead_weighted_metrics == []


def test_absent_pillars_empty_when_full_matrix(scorer, balanced):
    ids = ["load_factor", "avg_dep_delay_min", "carrier_hhi", "cbsa_population", "cpe_usd"]
    fm = _fm(["BOS", "LAX"], ids, [[0.80, 10.0, 1000.0, 1e6, 10.0], [0.90, 20.0, 2000.0, 2e6, 20.0]])
    res = scorer.score(fm, balanced)
    assert res.absent_pillars == []


def test_zero_relative_weight_multi_pillar_redistributes_to_remaining_pillar():
    from airport_agent.contracts import load_registry
    from airport_agent.scoring.presets import Preset

    preset = Preset(
        name="zero_p1_multi",
        description="test",
        pillars={"P1": 0.30, "P2": 0.25, "P3": 0.15, "P4": 0.15, "P5": 0.15},
        metric_weights={"load_factor": 0.0},
    )
    scorer = Scorer(load_registry())
    fm = _fm(["BOS", "LAX"], ["load_factor", "avg_dep_delay_min"], [[0.80, 10.0], [0.90, 20.0]])
    res = scorer.score(fm, preset)
    lax = next(r for r in res.rows if r.ref.iata == "LAX")
    assert "load_factor" not in lax.metric_contrib  # P1 dropped: its only metric has zero relative weight
    assert lax.metric_contrib["avg_dep_delay_min"] == pytest.approx(100.0)  # P2 absorbs full effective weight
    assert lax.score == pytest.approx(100.0)


def test_preset_pillar_weight_zero_with_only_that_pillar_present_sets_low_confidence():
    from airport_agent.contracts import load_registry
    from airport_agent.scoring.presets import Preset

    preset = Preset(
        name="p1_zero_weight",
        description="test",
        pillars={"P1": 0.0, "P2": 1.0, "P3": 0.0, "P4": 0.0, "P5": 0.0},
    )
    scorer = Scorer(load_registry())
    fm = _fm(["BOS", "LAX"], ["load_factor"], [[0.80], [0.90]])
    res = scorer.score(fm, preset)
    for r in res.rows:
        assert r.score == 0.0
        assert r.low_confidence is True
