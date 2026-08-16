"""Every tool declares where its data comes from, and honours the declaration (QA task 18).

This is the sweep that found the bug, kept as a guard. On 2026-08-16 a manual pass over every tool
found `find_airports` shipping 50 airports with no provenance at all — the key was never set and the
registry's `setdefault` filled in `[]`. A one-off audit finds that once; this finds it forever, and
fails the moment a new tool is added without a declaration.
"""
from __future__ import annotations

import pytest

from airport_agent.agent.tables import PROVENANCE_TITLE, provenance_table, tool_result_tables
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.agent.tools.provenance import PROVENANCE_GAP
from airport_agent.contracts import registry_by_id

#: Representative arguments for every tool, so the sweep exercises real results rather than errors.
CALLS: dict[str, dict] = {
    "find_airports": {"faa_regions": ["ANE"]},
    "get_profile": {"iata": "SFO", "horizons": ["12m"]},
    "get_route_stats": {"iata": "ANC"},
    "get_live_status": {"iata": "SFO"},
    "explain_metric": {"metric_id": "load_factor"},
    "get_metric_series": {"iata": "SFO", "metric_id": "load_factor"},
    "list_sources": {},
    "score_airports": {"airports": ["BOS", "BDL"]},
    "compare_airports": {"airports": ["SFO", "LAX"]},
    "diagnose_unmet_demand": {"airports": ["SFO"]},
}


@pytest.fixture
def registry(fake_data, fake_analyst):
    return build_registry(fake_data, fake_analyst)


def test_the_sweep_covers_every_registered_tool(registry):
    """If a tool is added without a case here, the sweep below would silently skip it."""
    assert set(CALLS) == set(registry.names())


def test_every_tool_declares_its_provenance(registry):
    for name in registry.names():
        spec = registry.provenance_spec(name)
        forms = [bool(spec.sources), bool(spec.derived_from), bool(spec.no_external_source)]
        assert sum(forms) == 1, f"{name} must declare exactly one provenance form"


@pytest.mark.parametrize("name", sorted(CALLS))
def test_every_tool_result_honours_its_declaration(name, registry):
    out = registry.call(name, CALLS[name], engine="concierge")
    assert not out.get("error"), f"{name} errored on its representative args: {out.get('error')}"
    spec = registry.provenance_spec(name)
    entries = out.get("provenance") or []

    if spec.no_external_source:
        # a definition, not measured data: it says so, and does not fake a source
        assert out.get("provenance_note") == spec.no_external_source
        return

    assert entries, f"{name} returned no provenance — this is exactly the find_airports bug"
    for entry in entries:
        assert entry.get("source_id"), f"{name} returned an entry with no source_id"
    for declared in spec.sources:
        assert any(e["source_id"] == declared for e in entries), \
            f"{name} declares it reads {declared} but did not cite it"
    notes = " ".join(out.get("data_quality_notes") or [])
    assert PROVENANCE_GAP not in notes


@pytest.mark.parametrize("name", sorted(CALLS))
def test_every_rendered_table_is_attributable(name, registry, fake_data):
    """Either the table carries its own source column, or the answer's provenance table covers it.

    This is the (C) split the human chose on 2026-08-16: metric-level tables keep inline columns;
    everything else is covered once, at the end.
    """
    by_id = registry_by_id(fake_data.describe_metrics())
    out = registry.call(name, CALLS[name], engine="concierge")
    tables = tool_result_tables(name, out, by_id)
    covered = provenance_table(out.get("provenance") or [])
    for table in tables:
        inline = any(c.lower() in ("source", "data as of", "vintage") for c in table.columns)
        assert inline or covered is not None or out.get("provenance_note"), \
            f"{name}: table {table.title!r} has no inline source and nothing covers it"


def test_the_provenance_table_merges_periods_and_names_its_users():
    entries = [{"source_id": "bts_t100", "vintage": "2026-04", "period_start": "2024-06",
                "period_end": "2026-05"},
               {"source_id": "bts_t100", "vintage": "2026-04"},
               {"source_id": "ourairports", "vintage": "2026-08-15"}]
    table = provenance_table(entries, covers={"bts_t100": ["route mix", "route mix"],
                                              "ourairports": ["the airport list"]})
    assert table is not None and table.title == PROVENANCE_TITLE
    assert table.columns == ["source", "used for", "period", "data as of"]
    assert len(table.rows) == 2  # one row per source, not one per entry
    t100 = next(r for r in table.rows if r[0] == "BTS T-100 route segments")
    assert t100[1] == "route mix"  # deduplicated
    assert t100[2] == "2024-06 to 2026-05" and t100[3] == "2026-04"
    identity = next(r for r in table.rows if r[0] == "OurAirports")
    assert identity[2] == "-"  # no period known, never an invented one
    assert any("not when its publisher released it" in note for note in table.footnotes)


def test_a_source_that_supplied_no_number_is_never_cited(fake_data, fake_analyst):
    """The RESCOPE-cut sources keep a nominal source_id on their empty metrics — never cite them.

    Found by this sweep on 2026-08-16: score_airports was citing bea_msa, bts_db1b, faa_cats and
    bts_delay_cause, none of which have a single row in the snapshot.
    """
    from airport_agent.agent.synthesis import _metric_provenance
    registry = build_registry(fake_data, fake_analyst)
    out = registry.call("score_airports", {"airports": ["BOS", "BDL"]}, engine="concierge")
    cited = {e["source_id"] for e in out["provenance"]}
    empty_sources = {m.source_id for m in _all_metrics(fake_data) if m.value is None}
    valued_sources = {m.source_id for m in _all_metrics(fake_data) if m.value is not None}
    assert cited <= valued_sources
    assert not (cited & (empty_sources - valued_sources))
    assert _metric_provenance([m for m in _all_metrics(fake_data) if m.value is None]) == []


def _all_metrics(fake_data):
    profile = fake_data.get_profile("BOS", ("12m", "5y"))
    return [m for group in profile.metrics.values() for m in group]


def test_only_the_live_feed_is_dated_by_the_fetch(registry, fake_data):
    """Snapshot traffic riding along with a live call keeps the snapshot's date, not "as of now".

    Found on 2026-08-16 when the provenance table put the two side by side and the April snapshot
    claimed the live fetch time.
    """
    out = registry.call("get_live_status", {"iata": "SFO"}, engine="concierge")
    fetched = out["fetched_at"]
    by_source = {e["source_id"]: e for e in out["provenance"]}
    assert by_source["faa_nasstatus"]["vintage"] == fetched
    snapshot_dates = {v.source_id: v for v in fake_data.source_vintages()}
    for source_id, entry in by_source.items():
        if source_id == "faa_nasstatus" or source_id not in snapshot_dates:
            continue
        assert entry["vintage"] != fetched, f"{source_id} is snapshot data wearing the live fetch time"


def test_no_sources_means_no_empty_table():
    assert provenance_table([]) is None
    assert provenance_table([{"source_id": "", "vintage": "x"}]) is None
