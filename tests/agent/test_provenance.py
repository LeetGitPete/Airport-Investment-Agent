from __future__ import annotations

from airport_agent.agent.tools.provenance import prov
from airport_agent.contracts import Metric


def _m(source_id: str, vintage: str) -> Metric:
    return Metric(id="load_factor", value=0.8, unit="ratio", horizon="12m", period_start="2025-05",
                  period_end=vintage, source_id=source_id, vintage=vintage)


def test_prov_dedups_and_preserves_order():
    items = [_m("bts_t100", "2026-04"), _m("faa_opsnet", "2026-03"), _m("bts_t100", "2026-04"),
             _m("bts_t100", "2026-01")]
    # QA task 18: entries also carry the period when the item knows one, so the provenance table can
    # show what the data covers and not only when it was fetched.
    assert [(e["source_id"], e["vintage"]) for e in prov(items)] == [
        ("bts_t100", "2026-04"), ("faa_opsnet", "2026-03"), ("bts_t100", "2026-01")]
    assert prov(items)[0]["period_start"] == "2025-05" and prov(items)[0]["period_end"] == "2026-04"
    assert prov([]) == []


def test_prov_accepts_pairs_and_skips_items_without_a_source_id():
    class Sourceless:
        vintage = "2026-04"

    assert prov([("faa_nasstatus", "2026-08-15T00:00:00"), Sourceless(), ("faa_nasstatus", "2026-08-15T00:00:00")]) == [
        {"source_id": "faa_nasstatus", "vintage": "2026-08-15T00:00:00"}]
