from __future__ import annotations

from airport_agent.agent.tools.data_tools import build_data_tools, build_registry


def test_all_tools_registered_with_engines(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    assert set(reg.names()) == {"find_airports", "get_profile", "get_route_stats", "get_live_status", "explain_metric",
                                "get_metric_series", "list_sources", "score_airports", "compare_airports",
                                "diagnose_unmet_demand"}
    assert set(reg.names("capacity_analyst")) == {"get_profile", "get_route_stats", "get_live_status", "explain_metric",
                                                  "compare_airports", "diagnose_unmet_demand"}
    assert set(reg.names("expansion_analyst")) == {"find_airports", "get_profile", "explain_metric", "get_metric_series",
                                                   "score_airports"}
    assert set(reg.names("market_analyst")) == {"find_airports", "get_profile", "get_route_stats", "explain_metric",
                                                "get_metric_series", "compare_airports"}
    assert set(reg.names("general_analyst")) == set(reg.names())
    for spec in build_data_tools(fake_data, fake_analyst):
        assert spec.description and spec.json_schema()["parameters"]["type"] == "object"


def test_find_airports_new_england(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("find_airports", {"faa_regions": ["ane"]}, engine="concierge")
    assert {a["iata"] for a in out["airports"]} == {"BOS", "BDL", "PVD", "MHT", "PWM"} and out["truncated"] is False


def test_find_airports_passes_cbsa_codes_to_the_filter(fake_data, fake_analyst):
    seen = []
    real = fake_data.list_airports
    fake_data.list_airports = lambda f: (seen.append(f), real(f))[1]
    out = build_registry(fake_data, fake_analyst).call(
        "find_airports", {"cbsa_codes": ["14460"], "limit": 10}, engine="concierge")
    assert "error" not in out
    assert seen and seen[0].cbsa_codes == ["14460"] and seen[0].limit == 10


def test_get_route_stats_anchorage(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("get_route_stats", {"iata": "anc", "top_n": 3}, engine="concierge")
    assert out["long_haul_share"]["freight"]["value"] > out["long_haul_share"]["passenger"]["value"]
    assert set(out["distance_bands"]["passenger"]) == {"short", "medium", "long", "ultra"}
    assert len(out["top_routes"]) == 3 and out["provenance"] == [{"source_id": "bts_t100", "vintage": "2026-04"}]
    assert "1500" in out["convention"]


def test_profile_series_live_explain_sources(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    prof = reg.call("get_profile", {"iata": "SFO", "horizons": ["12m"]}, engine="capacity_analyst")
    assert prof["ref"]["iata"] == "SFO" and prof["provenance"] and "12m" in prof["metrics"]
    ser = reg.call("get_metric_series", {"iata": "BOS", "metric_id": "load_factor"}, engine="concierge")
    assert len(ser["series"]) > 5 and ser["provenance"]
    live = reg.call("get_live_status", {"iata": "SFO"}, engine="concierge")
    assert live["delay_programs"] == ["Ground Delay Program"] and live["provenance"]
    ex = reg.call("explain_metric", {"metric_id": "load_factor"}, engine="market_analyst")
    assert ex["pillar_name"] == "Demand Pressure" and ex["formula"] == "passengers / seats"
    assert "KeyError" in reg.call("explain_metric", {"metric_id": "nope"}, engine="concierge")["error"]
    assert reg.call("list_sources", {}, engine="concierge")["sources"]


def test_unknown_airport_is_error_dict_not_exception(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("get_profile", {"iata": "ZZZ"}, engine="concierge")
    assert "KeyError" in out["error"]
