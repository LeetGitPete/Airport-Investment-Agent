import pytest

from airport_agent.contracts import AirportFilter, DataService, FeatureMatrix, load_registry

NE = {"BOS", "BDL", "PVD", "MHT", "PWM"}
# Registry-declared optional metrics (caveat says the value may be absent, e.g. od_share / DB1B adapter).
MAY_BE_ABSENT = {s.id for s in load_registry() if any("absent" in c.lower() for c in s.caveats)}


def test_is_data_service(data_service):
    assert isinstance(data_service, DataService)


def test_list_airports_by_state_and_region(data_service):
    by_state = {a.iata for a in data_service.list_airports(AirportFilter(states=["MA", "CT", "RI", "NH", "VT", "ME"]))}
    by_region = {a.iata for a in data_service.list_airports(AirportFilter(faa_regions=["ANE"]))}
    assert NE <= by_state and NE <= by_region
    assert all(a.faa_region == "ANE" for a in data_service.list_airports(AirportFilter(faa_regions=["ANE"])))


def test_list_airports_limit_and_hub(data_service):
    assert len(data_service.list_airports(AirportFilter(limit=2))) == 2
    assert all(a.hub_size == "large" for a in data_service.list_airports(AirportFilter(hub_sizes=["large"])))


def test_get_airport(data_service):
    assert data_service.get_airport("bos").iata == "BOS"
    assert data_service.get_airport("ZZZ") is None


def test_feature_matrix_conforms_to_registry(data_service):
    """Horizon rule (see DataService.get_feature_matrix): a metric that does not declare the requested
    horizon (nor 'static'/'forecast') MUST be None — no implementation may relabel another horizon."""
    specs = [s for s in load_registry() if s.tier in ("A", "B")]
    ids = [s.id for s in specs]
    fm = data_service.get_feature_matrix(["BOS", "SFO", "ANC"], ids, "5y")
    assert isinstance(fm, FeatureMatrix)
    assert [a.iata for a in fm.airports] == ["BOS", "SFO", "ANC"] and fm.metric_ids == ids
    assert all(v is None or isinstance(v, float) for row in fm.values for v in row)
    for j, spec in enumerate(specs):
        column = [fm.values[i][j] for i in range(len(fm.airports))]
        if {"5y", "static", "forecast"} & set(spec.horizons):
            if spec.tier == "A" and spec.id not in MAY_BE_ABSENT:  # tier B is curated majors only
                assert all(v is not None for v in column), f"{spec.id}: tier-A gap at 5y"
        else:
            assert all(v is None for v in column), f"{spec.id}: value invented for an undeclared horizon"


def test_feature_matrix_12m_covers_tier_a(data_service):
    specs = [s for s in load_registry() if s.tier == "A" and "12m" in s.horizons and s.id not in MAY_BE_ABSENT]
    fm = data_service.get_feature_matrix(["BOS", "SFO", "ANC"], [s.id for s in specs], "12m")
    for j, spec in enumerate(specs):
        assert all(fm.values[i][j] is not None for i in range(3)), f"{spec.id}: tier-A gap at 12m"


def test_feature_matrix_rejects_unknown_metric(data_service):
    with pytest.raises((KeyError, ValueError)):
        data_service.get_feature_matrix(["BOS"], ["not_a_metric"], "5y")


def test_unknown_airport_raises(data_service):
    with pytest.raises(KeyError):
        data_service.get_feature_matrix(["ZZZ"], ["load_factor"], "12m")
    with pytest.raises(KeyError):
        data_service.get_profile("ZZZ")


def test_profile_has_all_sections_and_provenance(data_service):
    p = data_service.get_profile("SFO")
    assert p.ref.iata == "SFO" and set(p.metrics) >= {"12m", "5y"}
    assert p.vintages and all(m.source_id and m.vintage for h in p.metrics.values() for m in h)
    assert isinstance(p.data_quality_notes, list)


def test_routes_sorted_and_flagged(data_service):
    rt = data_service.get_routes("ANC", top_n=5)
    assert rt.iata == "ANC" and len(rt.rows) == 5 and rt.source_id
    deps = [r.departures for r in rt.rows]
    assert deps == sorted(deps, reverse=True)
    assert rt.truncated is True  # ANC has more than 5 routes
    assert data_service.get_routes("ANC", top_n=50).truncated is False
    intl = data_service.get_routes("JFK", international=True)
    assert all(r.is_international for r in intl.rows)


def test_metric_series_is_chronological(data_service):
    s = data_service.get_metric_series("BOS", "load_factor")
    assert len(s) >= 3 and [m.period_end for m in s] == sorted(m.period_end for m in s)


def test_metric_series_empty_when_metric_missing(data_service):
    assert data_service.get_metric_series("ANC", "pax_per_gate") == []  # tier B, not curated for ANC
    assert data_service.get_metric_series("BOS", "asv_utilization") == []  # tier C, never available


def test_live_status_and_vintages(data_service):
    ls = data_service.get_live_status("SFO")
    assert ls.iata == "SFO" and ls.fetched_at
    assert data_service.source_vintages()


def test_describe_metrics_matches_registry(data_service):
    assert {s.id for s in data_service.describe_metrics()} == {s.id for s in load_registry()}
