from __future__ import annotations

from airport_agent.agent.tools.provenance import prov
from airport_agent.contracts import Metric


def _m(source_id: str, vintage: str) -> Metric:
    return Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05",
                  period_end=vintage, source_id=source_id, vintage=vintage)


def test_prov_dedups_and_preserves_order():
    items = [_m("bts_t100", "2026-04"), _m("faa_opsnet", "2026-03"), _m("bts_t100", "2026-04"),
             _m("bts_t100", "2026-01")]
    assert prov(items) == [{"source_id": "bts_t100", "vintage": "2026-04"},
                           {"source_id": "faa_opsnet", "vintage": "2026-03"},
                           {"source_id": "bts_t100", "vintage": "2026-01"}]
    assert prov([]) == []


def test_prov_accepts_pairs_and_skips_items_without_a_source_id():
    class Sourceless:
        vintage = "2026-04"

    assert prov([("faa_nasstatus", "2026-08-15T00:00:00"), Sourceless(), ("faa_nasstatus", "2026-08-15T00:00:00")]) == [
        {"source_id": "faa_nasstatus", "vintage": "2026-08-15T00:00:00"}]
