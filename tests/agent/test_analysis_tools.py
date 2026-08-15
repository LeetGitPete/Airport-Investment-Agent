from __future__ import annotations

from airport_agent.agent.tools.data_tools import build_registry


def test_score_airports_by_region(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call(
        "score_airports", {"faa_regions": ["ANE"], "horizon": "5y", "scoring_preset": "terminal_expansion"}, engine="concierge")
    assert out["report_type"] == "deterministic" and out["question_type"] == "rank"
    assert {r["ref"]["iata"] for r in out["rows"]} == {"BOS", "BDL", "PVD", "MHT", "PWM"}
    assert out["provenance"] and all(set(p) == {"source_id", "vintage"} for p in out["provenance"])
    assert out["preset"] == "terminal_expansion" and out["horizon"] == "5y"
    assert out["coverage"] == sum(r["coverage"] for r in out["rows"]) / len(out["rows"])


def test_score_airports_honours_peer_group_and_records_the_filter(fake_data, fake_analyst):
    seen = []
    real = fake_data.list_airports
    fake_data.list_airports = lambda f: (seen.append(f), real(f))[1]
    out = build_registry(fake_data, fake_analyst).call(
        "score_airports", {"states": ["CA"], "cbsa_codes": ["31080"], "peer_group": "region"}, engine="concierge")
    assert out["peer_group"] == "region"
    assert seen and seen[0].cbsa_codes == ["31080"] and seen[0].states == ["CA"]


def test_compare_and_diagnose(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    cmp_ = reg.call("compare_airports", {"airports": ["LAX", "SNA"], "horizon": "12m"}, engine="capacity_analyst")
    assert cmp_["question_type"] == "compare" and cmp_["comparison"]["avg_dep_delay_min"]["LAX"] == 12.9
    dia = reg.call("diagnose_unmet_demand", {"airports": ["SFO"]}, engine="capacity_analyst")
    assert dia["question_type"] == "diagnose" and dia["explanation"].startswith("Signals of unmet demand")


def test_score_requires_airports_or_filter(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("score_airports", {}, engine="concierge")
    assert "error" in out
