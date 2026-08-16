"""Code-built tables: every cell comes from a report or a tool result, never from the LLM (design 03).

The Concierge chooses WHICH rows to surface (via `show_metrics`) and must say what it hid; it can never change
a value, a unit or a citation, because the LLM never touches this module's inputs.
"""
from __future__ import annotations

import re
from typing import Any

from airport_agent.contracts import (
    Citation,
    DeterministicReport,
    Metric,
    MetricSpec,
    SpecialistReport,
    Table,
)

PILLARS = ["P1", "P2", "P3", "P4", "P5"]
BANDS = ["short", "medium", "long", "ultra"]
#: Presentation standard (QA 2026-08-16): user-facing labels only. "time period" = analysis
#: window (12m/3y/5y/10y); "data as of" = the data's own date (period end / source-file date),
#: NOT the moment we fetched it.
METRIC_PROVENANCE_COLUMNS = ["value", "unit", "time period", "period end", "source", "data as of"]
#: Tool results that are DeterministicReport dumps.
REPORT_TOOLS = ("score_airports", "compare_airports", "diagnose_unmet_demand")

#: User-facing source names. Fallback is the raw id, so an unmapped source stays visible.
SOURCE_DISPLAY: dict[str, str] = {
    "ourairports": "OurAirports",
    "faa_taf": "FAA Terminal Area Forecast",
    "faa_npias": "FAA NPIAS 2025-2029",
    "bts_socrata": "BTS T-100 airport totals",
    "bts_t100": "BTS T-100 route segments",
    "bts_otp": "BTS On-Time Performance",
    "bts_delay_cause": "BTS delay causes",
    "census_cbsa": "Census metro population",
    "bea_msa": "BEA metro GDP",
    "faa_cats": "FAA airport financials (Form 127)",
    "faa_aip": "FAA AIP grants",
    "faa_nasstatus": "FAA NAS Status (live)",
    "curated": "Curated airport facts",
    "bts_db1b": "BTS DB1B O&D survey",
}


def source_name(source_id: str | None) -> str:
    """User-facing name for a source id (the id itself when unmapped or empty)."""
    return SOURCE_DISPLAY.get(source_id or "", source_id or "")


#: What rank 1 / a high score MEANS under each preset (QA task 2). Percentiles are
#: direction-adjusted per metric, so a higher score is always "stronger case for the
#: preset's objective" — these spell that out per preset so no table needs decoding.
PRESET_LEGENDS: dict[str, str] = {
    "balanced": "Rank 1 = strongest overall investment candidate under balanced pillar weights.",
    "terminal_expansion": ("Rank 1 = strongest terminal-expansion candidate — the most gate/terminal "
                           "pressure relative to peers, i.e. the most to gain from new terminal capacity."),
    "congestion_relief": ("Rank 1 = strongest congestion-relief candidate — the most airfield congestion "
                          "relative to peers, i.e. the most to gain from added runway/airfield capacity."),
    "market_entry": ("Rank 1 = strongest market-entry candidate — the most attractive market "
                     "fundamentals for a new entrant or route."),
}
DEFAULT_LEGEND = ("Rank 1 = highest score under this preset; a higher score always means a stronger "
                  "case for the preset's objective (each metric's direction is already accounted for).")


def rank_legend(preset: str | None) -> str:
    return PRESET_LEGENDS.get(preset or "", DEFAULT_LEGEND)


#: Unit display: "pct" is the registry's unit for PERCENT (not percentile) — shown as "%".
UNIT_DISPLAY: dict[str, str] = {"pct": "%"}

#: Peer-group values rendered as prose (QA task 4): "hub_class" is the FAA hub-size class.
PEER_GROUP_DISPLAY: dict[str, str] = {
    "hub_class": "airports of the same hub size",
    "region": "airports in the same FAA region",
    "all": "all airports",
}


def unit_label(unit: str | None) -> str:
    return UNIT_DISPLAY.get(unit or "", unit or "")


def peer_label(peer_group: str | None) -> str:
    return PEER_GROUP_DISPLAY.get(peer_group or "", peer_group or "peers")


def _metric_name(metric_id: str, specs_by_id: dict[str, MetricSpec]) -> str:
    spec = specs_by_id.get(metric_id)
    return spec.name if spec else metric_id


def humanize_metric_ids(text: str, specs_by_id: dict[str, MetricSpec]) -> str:
    """Replace internal metric ids with display names in LLM-written prose (QA task 9).

    The specialist is prompted to use display names, but this is the deterministic backstop —
    ids are distinctive snake_case tokens, replaced longest-first on word boundaries so
    e.g. `enpl_cagr_5y` never partially matches inside `enpl_cagr_5y_x`.
    """
    if not text:
        return text
    for metric_id in sorted(specs_by_id, key=len, reverse=True):
        if metric_id in text:
            text = re.sub(rf"`?\b{re.escape(metric_id)}\b`?", specs_by_id[metric_id].name, text)
    return text


def _metric_row(metric: Metric) -> list[Any]:
    return [metric.value, unit_label(metric.unit), metric.horizon, metric.period_end,
            source_name(metric.source_id), metric.vintage]


def ranking_table(rep: DeterministicReport) -> Table:
    """The deterministic scores, verbatim: score, coverage and the pillar contributions behind them.

    A single-airport report has no meaningful rank (QA task 6): the rank column is dropped and the
    table is titled "Scores". Pillar columns are limited to pillars the preset actually weights.
    """
    single = len(rep.rows) == 1
    pillars = [p for p in PILLARS if rep.weights.get(p)] or PILLARS
    columns = [*([] if single else ["rank"]), "airport", "name", "hub", "score", "coverage",
               "low_confidence", *pillars]
    rows = [[*([] if single else [row.rank]), row.ref.iata, row.ref.name, row.ref.hub_size, row.score,
             row.coverage, row.low_confidence, *[row.pillar_contrib.get(p) for p in pillars]]
            for row in sorted(rep.rows, key=lambda r: r.rank)]
    preset = rep.preset or "engine default"
    kind = "Scores" if single else "Ranking"
    footnotes = ["Score = how strong the case is under this preset (0-100 within the peer group); "
                 "it is a relative standing, not a dollar figure."] if single else [rank_legend(rep.preset)]
    footnotes.append("Pillar columns are contributions to the score (weight x percentile x 100).")
    return Table(title=f"{kind} — preset {preset}, time period {rep.horizon} "
                       f"(percentiles among {peer_label(rep.peer_group)})",
                 columns=columns, rows=rows, footnotes=footnotes)


def _provenance_by_id(rep: DeterministicReport) -> dict[str, list[str]]:
    """Per metric id: [time period, period end, source, data as of], distinct values joined by ' / '.

    Evidence entries for one id normally share provenance (same source and window per airport); when
    they genuinely differ, every distinct value is shown rather than picking one.
    """
    fields: dict[str, list[list[str]]] = {}
    for metric in rep.evidence:
        slots = fields.setdefault(metric.id, [[], [], [], []])
        values = [metric.horizon, metric.period_end, source_name(metric.source_id), metric.vintage]
        for slot, value in zip(slots, values, strict=True):
            text = "" if value is None else str(value)
            if text and text not in slot:
                slot.append(text)
    return {mid: [" / ".join(slot) for slot in slots] for mid, slots in fields.items()}


def _matrix_values(rep: DeterministicReport, iatas: list[str]) -> dict[str, dict[str, Any]]:
    """Per metric id: {iata: value}. `rep.comparison` when present; a single-airport report
    falls back to its evidence (a `Metric` carries no airport, so this is only honest for one)."""
    if rep.comparison:
        return dict(rep.comparison)
    if len(iatas) != 1:
        return {}
    single = iatas[0]
    values: dict[str, dict[str, Any]] = {}
    for metric in rep.evidence:
        values.setdefault(metric.id, {})
        if metric.value is not None and single not in values[metric.id]:
            values[metric.id][single] = metric.value
    return values


def data_matrix(rep: DeterministicReport, specs_by_id: dict[str, MetricSpec]) -> Table:
    """THE canonical metrics table for every analytical answer (QA task 5) — always shown.

    One row per metric (user-facing name), one value column per airport (one airport = one
    column), percentile columns when the report carries them, and provenance (source, data as
    of) on every row. Rows where no airport has a value are hidden and counted in a footnote.
    """
    iatas = [row.ref.iata for row in sorted(rep.rows, key=lambda r: r.rank)]
    comparison = _matrix_values(rep, iatas)
    if not iatas:
        iatas = sorted({iata for values in comparison.values() for iata in values})
    percentiles = rep.percentiles or {}
    provenance = _provenance_by_id(rep)
    columns = ["metric", "unit", *iatas,
               *([f"percentile {i}" for i in iatas] if percentiles else []),
               "time period", "period end", "source", "data as of"]
    rows = []
    hidden_empty = 0
    for metric_id, values in comparison.items():
        airport_values = [values.get(iata) for iata in iatas]
        if all(v is None for v in airport_values):
            hidden_empty += 1
            continue
        spec = specs_by_id.get(metric_id)
        row: list[Any] = [_metric_name(metric_id, specs_by_id), unit_label(spec.unit if spec else "")]
        row += airport_values
        if percentiles:
            row += [percentiles.get(metric_id, {}).get(iata) for iata in iatas]
        row += provenance.get(metric_id, [rep.horizon, "", "", ""])
        rows.append(row)
    footnotes = [("Percentiles are within the peer group and direction-adjusted per metric: "
                  "1.0 always means the strongest case for investment on that metric "
                  "(e.g. most delay for a congestion metric, lowest cost for a cost metric).")] \
        if percentiles else []
    if hidden_empty:
        footnotes.append(f"{hidden_empty} metrics have no value for these airports and are not shown.")
    title = (f"Comparison — time period {rep.horizon}" if len(iatas) > 1
             else f"Data — {iatas[0] if iatas else '?'}, time period {rep.horizon}")
    return Table(title=title, columns=columns, rows=rows, footnotes=footnotes)


#: Back-compat alias: the comparison table IS the data matrix.
comparison_table = data_matrix


def specialist_ranking_table(rep: SpecialistReport,
                             specs_by_id: dict[str, MetricSpec] | None = None) -> Table | None:
    """The analyst's own ordering, kept separate from the formula's so the two can be compared."""
    if not rep.ranking:
        return None
    rows = [[item.rank, item.iata, humanize_metric_ids(item.rationale, specs_by_id or {}),
             item.confidence]
            for item in sorted(rep.ranking, key=lambda i: i.rank)]
    return Table(title=f"Analyst ranking — {rep.specialist}",
                 columns=["rank", "airport", "rationale", "confidence"], rows=rows,
                 footnotes=["Rank 1 = the analyst's strongest candidate for the question asked.",
                            "The analyst's ordering and confidence, not the formula's."])


def _report_from_dict(result: dict[str, Any]) -> DeterministicReport:
    fields = set(DeterministicReport.model_fields)
    return DeterministicReport(**{k: v for k, v in result.items() if k in fields})


def _route_tables(result: dict[str, Any]) -> list[Table]:
    iata, horizon = result.get("iata", "?"), result.get("horizon", "?")
    convention = result.get("convention", "")
    bands = result.get("distance_bands") or {}
    band_rows = [[kind, *[(bands.get(kind) or {}).get(band) for band in BANDS]] for kind in bands]
    shares = result.get("long_haul_share") or {}
    share_rows = [[kind, metric.get("value"), unit_label(metric.get("unit")), metric.get("period_end"),
                   source_name(metric.get("source_id")), metric.get("vintage")]
                  for kind, metric in shares.items()]
    footnotes = [convention] if convention else []
    return [
        Table(title=f"Distance bands — {iata} ({horizon})", columns=["kind", *BANDS], rows=band_rows,
              footnotes=list(footnotes)),
        Table(title=f"Long-haul share — {iata} ({horizon})",
              columns=["kind", "share", "unit", "period end", "source", "data as of"], rows=share_rows,
              footnotes=list(footnotes)),
    ]


def _profile_tables(result: dict[str, Any], specs_by_id: dict[str, MetricSpec]) -> list[Table]:
    iata = (result.get("ref") or {}).get("iata", "?")
    tables: list[Table] = []
    for horizon, metrics in (result.get("metrics") or {}).items():
        present = [m for m in metrics if m.get("value") is not None]
        rows = [[_metric_name(m["id"], specs_by_id), m.get("value"), unit_label(m.get("unit")),
                 m.get("horizon"), m.get("period_end"), source_name(m.get("source_id")),
                 m.get("vintage")] for m in present]
        missing = len(metrics) - len(present)
        footnotes = [f"{missing} metrics have no value at this airport/horizon."] if missing else []
        tables.append(Table(title=f"Metrics — {iata} ({horizon})",
                            columns=["metric", *METRIC_PROVENANCE_COLUMNS], rows=rows, footnotes=footnotes))
    facts = result.get("curated_facts") or []
    if facts:
        tables.append(Table(title=f"Curated capacity facts — {iata}",
                            columns=["category", "text", "value", "as of", "source"],
                            rows=[[f.get("category"), f.get("text"), f.get("value"), f.get("as_of"),
                                   f.get("source_url")] for f in facts], footnotes=[]))
    return tables


def _airports_table(result: dict[str, Any]) -> Table:
    airports = result.get("airports") or []
    count = result.get("count", len(airports))
    footnotes = ["Truncated at the requested limit; more airports may match."] if result.get("truncated") else []
    return Table(title=f"Airports ({count})", columns=["iata", "name", "city", "state", "region", "hub"],
                 rows=[[a.get("iata"), a.get("name"), a.get("city"), a.get("state"), a.get("faa_region"),
                        a.get("hub_size")] for a in airports], footnotes=footnotes)


def _simple_tables(tool: str, result: dict[str, Any],
                   specs_by_id: dict[str, MetricSpec]) -> list[Table]:
    if tool == "find_airports":
        return [_airports_table(result)]
    if tool == "get_metric_series":
        series = result.get("series") or []
        title = f"Series — {result.get('iata', '?')} {_metric_name(result.get('metric_id', '?'), specs_by_id)}"
        return [Table(title=title,
                      columns=["period end", "value", "unit", "time period", "source", "data as of"],
                      rows=[[m.get("period_end"), m.get("value"), m.get("unit"), m.get("horizon"),
                             source_name(m.get("source_id")), m.get("vintage")] for m in series],
                      footnotes=[])]
    if tool == "get_live_status":
        rows = [["delay programs", ", ".join(result.get("delay_programs") or []) or "none"],
                ["ground stop", result.get("ground_stop")], ["closure", result.get("closure")],
                ["latest month", result.get("latest_month")], ["fetched at", result.get("fetched_at")]]
        return [Table(title=f"Live status — {result.get('iata', '?')}", columns=["field", "value"], rows=rows,
                      footnotes=["Snapshot at the fetch time above."])]
    if tool == "explain_metric":
        keys = ["id", "name", "definition", "formula", "unit", "direction", "pillar", "pillar_name", "tier",
                "sources", "horizons", "caveats"]
        rows = [[k, ", ".join(map(str, result[k])) if isinstance(result.get(k), list) else result.get(k)]
                for k in keys if k in result]
        return [Table(title=f"Definition — {result.get('id', '?')}", columns=["field", "value"], rows=rows,
                      footnotes=[])]
    if tool == "list_sources":
        sources = result.get("sources") or []
        rows = []
        for source in sources:
            period = f"{source.get('period_start') or '?'} to {source.get('period_end') or '?'}"
            rows.append([source_name(source.get("source_id")), source.get("description"), period,
                         source.get("fetched_at")])
        return [Table(title=f"Sources ({len(sources)})",
                      columns=["source", "description", "period", "fetched at"], rows=rows, footnotes=[])]
    scalars = [[k, v] for k, v in result.items()
               if k not in ("provenance", "truncated")
               and isinstance(v, str | int | float | bool | type(None))]
    return [Table(title=f"Result — {tool}", columns=["field", "value"], rows=scalars, footnotes=[])] \
        if scalars else []


def tool_result_tables(tool: str, result: dict[str, Any],
                       specs_by_id: dict[str, MetricSpec]) -> list[Table]:
    """Render one tool result as tables. An error is shown as an error table, never dropped."""
    if result.get("error"):
        return [Table(title="Tool error", columns=["tool", "error"], rows=[[tool, result["error"]]],
                      footnotes=[])]
    if tool in REPORT_TOOLS:
        report = _report_from_dict(result)
        tables = [ranking_table(report)] if report.rows else []
        matrix = data_matrix(report, specs_by_id)
        if matrix.rows:
            tables.append(matrix)
        return tables
    if tool == "get_route_stats":
        return _route_tables(result)
    if tool == "get_profile":
        return _profile_tables(result, specs_by_id)
    return _simple_tables(tool, result, specs_by_id)


def citations_from(metrics: list[Metric], provenance: list[dict]) -> list[Citation]:
    """Unique (source_id, vintage) pairs in first-seen order — one citation per distinct source vintage."""
    pairs = [(m.source_id, m.vintage) for m in metrics]
    pairs += [(p.get("source_id", ""), p.get("vintage", "")) for p in provenance]
    seen: set[tuple[str, str]] = set()
    citations: list[Citation] = []
    for source_id, vintage in pairs:
        if not source_id or (source_id, vintage) in seen:
            continue
        seen.add((source_id, vintage))
        citations.append(Citation(source_id=source_id, vintage=vintage))
    return citations
