from __future__ import annotations

import pytest

from airport_agent.agent.tables import (
    citations_from,
    comparison_table,
    evidence_table,
    ranking_table,
    specialist_ranking_table,
    tool_result_tables,
)
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import AnalysisRequest, RankedItem, SpecialistReport, registry_by_id


@pytest.fixture
def by_id(specs):
    return registry_by_id(specs)


@pytest.fixture
def registry(fake_data, fake_analyst):
    return build_registry(fake_data, fake_analyst)


def _rank_report(fake_analyst):
    req = AnalysisRequest(question_type="rank", airports=["BOS", "BDL", "PVD"], horizons=["12m"],
                          scoring_preset="balanced")
    return fake_analyst.rank(req)


def _compare_report(fake_analyst):
    req = AnalysisRequest(question_type="compare", airports=["SFO", "LAX"], horizons=["12m"])
    return fake_analyst.compare(req)


def test_ranking_table_row_per_report_row_with_pillar_columns(fake_analyst):
    rep = _rank_report(fake_analyst)
    table = ranking_table(rep)
    assert table.title.startswith("Ranking") and "balanced" in table.title and "12m" in table.title
    assert [c for c in table.columns if c.startswith("P")] == ["P1", "P2", "P3", "P4", "P5"]
    assert len(table.rows) == len(rep.rows)
    scores = {row[table.columns.index("airport")]: row[table.columns.index("score")] for row in table.rows}
    assert scores == {r.ref.iata: r.score for r in rep.rows}  # verbatim, not reformatted
    ranks = [row[table.columns.index("rank")] for row in table.rows]
    assert ranks == sorted(ranks)


def test_evidence_table_keeps_show_order_and_reports_hidden(fake_analyst, by_id):
    rep = _rank_report(fake_analyst)
    table, hidden = evidence_table(rep, ["taxi_out_p80_min", "load_factor"], by_id)
    shown = [row[table.columns.index("metric")] for row in table.rows]
    assert shown[0].startswith("taxi_out_p80_min") and any(s.startswith("load_factor") for s in shown)
    assert "avg_dep_delay_min" in hidden and "load_factor" not in hidden
    assert "airport" not in table.columns  # three airports: no airport column (evidence carries no iata)
    for column in ("value", "unit", "horizon", "period_end", "source", "vintage"):
        assert column in table.columns


def test_evidence_table_labels_the_airport_when_report_has_one(fake_analyst, by_id):
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"])
    rep = fake_analyst.diagnose(req)
    table, _ = evidence_table(rep, [], by_id)
    assert "airport" in table.columns
    assert {row[table.columns.index("airport")] for row in table.rows} == {"SFO"}


def test_comparison_table_has_a_column_per_airport_with_report_values(fake_analyst, by_id):
    rep = _compare_report(fake_analyst)
    table = comparison_table(rep, by_id)
    for iata in ("SFO", "LAX"):
        assert iata in table.columns and f"pct {iata}" in table.columns
    for row in table.rows:
        metric_id = row[table.columns.index("metric")]
        for iata in ("SFO", "LAX"):
            assert row[table.columns.index(iata)] == rep.comparison[metric_id][iata]


def test_route_stats_gives_bands_and_long_haul_tables(registry, by_id):
    out = registry.call("get_route_stats", {"iata": "ANC"}, engine="concierge")
    tables = tool_result_tables("get_route_stats", out, by_id)
    assert len(tables) == 2
    bands = tables[0]
    assert bands.title.startswith("Distance bands")
    values = {row[0]: row[1:] for row in bands.rows}
    assert values["passenger"] == [out["distance_bands"]["passenger"][b]
                                   for b in ("short", "medium", "long", "ultra")]
    assert tables[1].title.startswith("Long-haul share")
    assert any("1500" in note or "1,500" in note for note in bands.footnotes + tables[1].footnotes)


def test_tool_error_becomes_a_table(registry, by_id):
    out = registry.call("get_profile", {"iata": "ZZZ"}, engine="concierge")
    tables = tool_result_tables("get_profile", out, by_id)
    assert tables[0].title == "Tool error" and tables[0].columns == ["tool", "error"]
    assert "KeyError" in tables[0].rows[0][1]


def test_other_tool_results_render(registry, by_id):
    finds = tool_result_tables("find_airports", registry.call("find_airports", {"faa_regions": ["ANE"]},
                                                              engine="concierge"), by_id)
    assert finds[0].title.startswith("Airports") and len(finds[0].rows) == 5
    profile = tool_result_tables("get_profile", registry.call("get_profile", {"iata": "SFO", "horizons": ["12m"]},
                                                              engine="concierge"), by_id)
    assert any(t.title.startswith("Metrics") for t in profile)
    sources = tool_result_tables("list_sources", registry.call("list_sources", {}, engine="concierge"), by_id)
    assert sources[0].title.startswith("Sources") and sources[0].rows
    definition = tool_result_tables("explain_metric", registry.call("explain_metric", {"metric_id": "load_factor"},
                                                                    engine="concierge"), by_id)
    assert definition[0].title.startswith("Definition") and "load_factor" in str(definition[0].rows)
    scored = tool_result_tables("score_airports", registry.call("score_airports", {"airports": ["BOS", "BDL"]},
                                                                engine="concierge"), by_id)
    assert any(t.title.startswith("Ranking") for t in scored)


def test_specialist_ranking_table_is_optional(fake_analyst):
    base = dict(specialist="expansion_analyst", question_type="rank", narrative="n", evidence=[], agreement=None,
                disagreements=[], confidence=0.5, assumptions=[], caveats=[], hint_truncated=False)
    assert specialist_ranking_table(SpecialistReport(ranking=None, **base)) is None
    table = specialist_ranking_table(SpecialistReport(
        ranking=[RankedItem(iata="BOS", rank=1, rationale="scale", confidence=0.8)], **base))
    assert table is not None and table.rows[0][:2] == [1, "BOS"]


def test_citations_are_unique_pairs(fake_analyst):
    rep = _rank_report(fake_analyst)
    citations = citations_from(rep.evidence, [{"source_id": "bts_t100", "vintage": "2026-04"},
                                              {"source_id": "bts_t100", "vintage": "2026-04"}])
    pairs = [(c.source_id, c.vintage) for c in citations]
    assert len(pairs) == len(set(pairs))
    assert ("bts_t100", "2026-04") in pairs
