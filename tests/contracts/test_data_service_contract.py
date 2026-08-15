import pytest

from airport_agent.contracts import AirportFilter, DataService, FeatureMatrix, load_registry

NE = {"BOS", "BDL", "PVD", "MHT", "PWM"}


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
    ids = [s.id for s in load_registry() if s.tier in ("A", "B")]
    fm = data_service.get_feature_matrix(["BOS", "SFO", "ANC"], ids, "5y")
    assert isinstance(fm, FeatureMatrix)
    assert [a.iata for a in fm.airports] == ["BOS", "SFO", "ANC"] and fm.metric_ids == ids
    assert fm.coverage() > 0.5  # tier A must be mostly present
    assert all(v is None or isinstance(v, float) for row in fm.values for v in row)


def test_feature_matrix_rejects_unknown_metric(data_service):
    with pytest.raises((KeyError, ValueError)):
        data_service.get_feature_matrix(["BOS"], ["not_a_metric"], "5y")


def test_profile_has_all_sections_and_provenance(data_service):
    p = data_service.get_profile("SFO")
    assert p.ref.iata == "SFO" and set(p.metrics) >= {"12m", "5y"}
    assert p.vintages and all(m.source_id and m.vintage for h in p.metrics.values() for m in h)
    assert isinstance(p.data_quality_notes, list)


def test_routes_sorted_and_flagged(data_service):
    rt = data_service.get_routes("ANC", top_n=5)
    assert rt.iata == "ANC" and len(rt.rows) <= 5 and rt.source_id
    deps = [r.departures for r in rt.rows]
    assert deps == sorted(deps, reverse=True)
    intl = data_service.get_routes("JFK", international=True)
    assert all(r.is_international for r in intl.rows)


def test_metric_series_is_chronological(data_service):
    s = data_service.get_metric_series("BOS", "load_factor")
    assert len(s) >= 3 and [m.period_end for m in s] == sorted(m.period_end for m in s)


def test_live_status_and_vintages(data_service):
    ls = data_service.get_live_status("SFO")
    assert ls.iata == "SFO" and ls.fetched_at
    assert data_service.source_vintages()


def test_describe_metrics_matches_registry(data_service):
    assert {s.id for s in data_service.describe_metrics()} == {s.id for s in load_registry()}
