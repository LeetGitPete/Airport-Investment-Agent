import pytest
from pydantic import ValidationError

from airport_agent.contracts.models import (
    AirportFilter,
    AirportProfile,
    AirportRef,
    FeatureMatrix,
    Metric,
    MetricSpec,
    RouteRow,
    RouteTable,
    SourceVintage,
)


def ref(iata="BOS"):
    return AirportRef(iata=iata, icao="KBOS", faa_locid="BOS", name="Logan", city="Boston", state="MA",
                      faa_region="ANE", hub_size="large", lat=42.36, lon=-71.01)


def test_airport_ref_normalizes_codes():
    r = AirportRef(iata="bos", icao=None, faa_locid="bos", name="Logan", city="Boston", state="ma",
                   faa_region=" ane ", hub_size="large", lat=42.36, lon=-71.01)
    assert r.iata == "BOS" and r.faa_locid == "BOS" and r.state == "MA" and r.faa_region == "ANE"


def test_airport_filter_normalizes_code_lists():
    f = AirportFilter(states=["ma"], faa_regions=["ane"], cbsa_codes=[" 14460 "], iatas=["bos"])
    assert f.faa_regions == ["ANE"] and f.cbsa_codes == ["14460"]
    assert f.states == ["MA"] and f.iatas == ["BOS"]


def test_metric_requires_provenance():
    with pytest.raises(ValidationError):
        Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05", period_end="2026-04")
    m = Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05", period_end="2026-04",
               source_id="bts_t100", vintage="2026-04")
    assert m.quality == []


def test_metric_spec_direction_and_tier_are_constrained():
    with pytest.raises(ValidationError):
        MetricSpec(id="x", name="x", definition="d", formula="f", unit="u", direction="sideways", pillar="P1",
                   tier="A", sources=["s"], horizons=["12m"])
    s = MetricSpec(id="x", name="x", definition="d", formula="f", unit="u", direction="down", pillar="P5",
                   tier="B", sources=["s"], horizons=["12m", "5y"])
    assert s.caveats == []


def test_feature_matrix_shape_and_helpers():
    fm = FeatureMatrix(airports=[ref("BOS"), ref("BDL")], metric_ids=["a", "b"], horizon="5y",
                       values=[[1.0, None], [2.0, 3.0]], peer_group="hub_class")
    assert fm.coverage() == pytest.approx(0.75)
    assert fm.column("a") == [1.0, 2.0]
    with pytest.raises(ValidationError):
        FeatureMatrix(airports=[ref("BOS")], metric_ids=["a", "b"], horizon="5y", values=[[1.0]], peer_group="all")


def test_airport_filter_defaults_and_limit():
    f = AirportFilter()
    assert f.states == [] and f.limit == 50
    with pytest.raises(ValidationError):
        AirportFilter(limit=0)


def test_airport_ref_rejects_none_and_wrong_types():
    with pytest.raises(ValidationError):
        AirportRef(iata=None, icao=None, faa_locid="BOS", name="Logan", city="Boston", state="MA",
                   faa_region="ANE", hub_size="large", lat=42.36, lon=-71.01)


def test_airport_filter_rejects_none_in_list():
    with pytest.raises(ValidationError):
        AirportFilter(states=[None])


def test_airport_filter_rejects_non_list():
    with pytest.raises(ValidationError):
        AirportFilter(states=123)


def test_metric_spec_rejects_invalid_horizon():
    with pytest.raises(ValidationError):
        MetricSpec(id="x", name="x", definition="d", formula="f", unit="u", direction="down", pillar="P1",
                   tier="A", sources=["s"], horizons=["not-a-horizon"])


def test_route_table_and_profile_construct():
    rt = RouteTable(iata="ANC", period_start="2025-05", period_end="2026-04", source_id="bts_t100", vintage="2026-04",
                    rows=[RouteRow(dest="SEA", dest_name="Seattle", distance_mi=1449, departures=3000, seats=450000,
                                   passengers=380000, freight_lb=1e6, is_international=False)], truncated=False)
    assert rt.rows[0].distance_mi == 1449
    p = AirportProfile(ref=ref(), metrics={"12m": []}, forecast={}, routes_summary={}, curated_facts=[],
                       live=None, data_quality_notes=[], vintages=[SourceVintage(source_id="s", description="d",
                       period_start="2025-01", period_end="2026-04", fetched_at="2026-08-15T00:00:00", url=None)])
    assert p.ref.iata == "BOS"
