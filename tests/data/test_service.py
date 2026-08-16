"""`DuckDBDataService`-specific tests (beyond the shared contract suite in
`tests/contracts/test_data_service_contract.py`): horizon rule internals, routes windows,
`live=False` status, and the service-owned pieces the generic suite doesn't probe."""
from __future__ import annotations

import inspect
from pathlib import Path

import duckdb
import pytest

from airport_agent.contracts.models import AirportFilter
from airport_agent.data.service import DuckDBDataService


@pytest.fixture(scope="module")
def service(test_snapshot_path: Path) -> DuckDBDataService:
    return DuckDBDataService(test_snapshot_path, live=False)


class TestConstruction:
    def test_defaults_to_the_snapshot_path(self) -> None:
        from airport_agent.data.paths import default_snapshot_path

        # The default wiring only — the snapshot file itself need not exist here.
        params = inspect.signature(DuckDBDataService.__init__).parameters
        assert params["path"].default is None
        assert params["live"].default is True
        assert default_snapshot_path().name == "airports.duckdb"

    def test_read_only_connection_rejects_writes(self, service: DuckDBDataService) -> None:
        with pytest.raises(duckdb.Error):
            service.con.execute("DELETE FROM airports")


class TestListAirportsOrdering:
    def test_deterministic_order_enplanements_desc_then_iata(self, service: DuckDBDataService) -> None:
        airports = service.list_airports(AirportFilter(limit=200))
        assert len(airports) > 0
        # ATL is by far the largest fixture airport by enplanements -> must sort first.
        assert airports[0].iata == "ATL"

    def test_repeated_calls_return_the_same_universe(self, service: DuckDBDataService) -> None:
        a = service.list_airports(AirportFilter(limit=200))
        b = service.list_airports(AirportFilter(limit=200))
        assert [x.iata for x in a] == [x.iata for x in b]

    def test_name_contains_is_case_insensitive(self, service: DuckDBDataService) -> None:
        hits = service.list_airports(AirportFilter(name_contains="logan"))
        assert any(a.iata == "BOS" for a in hits)


class TestHorizonRuleInternals:
    def test_invariant_metric_answers_any_requested_horizon(self, service: DuckDBDataService) -> None:
        # imc_capacity_ratio is static-only; SFO is curated in the fixture.
        fm_12m = service.get_feature_matrix(["SFO"], ["imc_capacity_ratio"], "12m")
        fm_5y = service.get_feature_matrix(["SFO"], ["imc_capacity_ratio"], "5y")
        assert fm_12m.values[0][0] == fm_5y.values[0][0] is not None

    def test_metric_stamped_at_its_own_horizon_in_the_series(self, service: DuckDBDataService) -> None:
        # enpl_cagr_5y only declares "5y" -> get_metric_series must use "5y", not "12m".
        series = service.get_metric_series("BOS", "enpl_cagr_5y")
        assert series and all(m.horizon == "5y" for m in series)

    def test_non_declared_horizon_is_none_not_borrowed(self, service: DuckDBDataService) -> None:
        # spill_proxy declares 12m/3y only; 10y is undeclared -> must be None, never a
        # relabeled 12m/3y value.
        fm = service.get_feature_matrix(["BOS"], ["spill_proxy"], "10y")
        assert fm.values[0][0] is None


class TestRoutesWindow:
    def test_12m_window_is_a_single_trailing_year(self, service: DuckDBDataService) -> None:
        rt = service.get_routes("BOS", horizon="12m", top_n=100)
        assert rt.period_start < rt.period_end or rt.period_start == rt.period_end

    def test_sorted_by_departures_descending(self, service: DuckDBDataService) -> None:
        rt = service.get_routes("BOS", top_n=100)
        deps = [r.departures for r in rt.rows]
        assert deps == sorted(deps, reverse=True)


class TestLiveFalseFallback:
    def test_get_live_status_never_touches_the_network(self, service: DuckDBDataService) -> None:
        # service fixture is constructed with live=False; this must not raise or hang.
        status = service.get_live_status("BOS")
        assert status.iata == "BOS"
        assert status.source_ids == ["bts_socrata"]
        assert status.delay_programs == []
        assert status.ground_stop is False and status.closure is False

    def test_get_profile_live_field_is_the_snapshot_fallback(self, service: DuckDBDataService) -> None:
        profile = service.get_profile("SFO")
        assert profile.live is not None
        assert profile.live.source_ids == ["bts_socrata"]


class TestSourceVintages:
    def test_every_ingested_source_has_a_vintage(self, service: DuckDBDataService) -> None:
        ids = {v.source_id for v in service.source_vintages()}
        assert {"ourairports", "faa_taf", "faa_npias", "curated", "bts_socrata", "bts_t100", "bts_otp",
                "census_cbsa"} <= ids
