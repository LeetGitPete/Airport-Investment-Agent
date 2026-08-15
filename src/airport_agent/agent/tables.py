"""Code-built tables: every cell comes from a report or a tool result, never from the LLM (design 03).

The Concierge chooses WHICH rows to surface (via `show_metrics`) and must say what it hid; it can never change
a value, a unit or a citation, because the LLM never touches this module's inputs.
"""
from __future__ import annotations

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
METRIC_PROVENANCE_COLUMNS = ["value", "unit", "horizon", "period_end", "source", "vintage"]
#: Tool results that are DeterministicReport dumps.
REPORT_TOOLS = ("score_airports", "compare_airports", "diagnose_unmet_demand")


def _label(metric_id: str, specs_by_id: dict[str, MetricSpec]) -> str:
    spec = specs_by_id.get(metric_id)
    return f"{metric_id} ({spec.name})" if spec else metric_id


def _metric_row(metric: Metric) -> list[Any]:
    return [metric.value, metric.unit, metric.horizon, metric.period_end, metric.source_id, metric.vintage]


def ranking_table(rep: DeterministicReport) -> Table:
    """The deterministic ranking, verbatim: score, coverage and the pillar contributions behind it."""
    columns = ["rank", "airport", "name", "hub", "score", "coverage", "low_confidence", *PILLARS]
    rows = [[row.rank, row.ref.iata, row.ref.name, row.ref.hub_size, row.score, row.coverage,
             row.low_confidence, *[row.pillar_contrib.get(p) for p in PILLARS]]
            for row in sorted(rep.rows, key=lambda r: r.rank)]
    preset = rep.preset or "engine default"
    return Table(title=f"Ranking — preset {preset}, horizon {rep.horizon} "
                       f"(percentiles within {rep.peer_group})",
                 columns=columns, rows=rows,
                 footnotes=["Pillar columns are contributions to the score (weight x percentile x 100)."])


def evidence_table(rep: DeterministicReport, show: list[str],
                   specs_by_id: dict[str, MetricSpec]) -> tuple[Table, list[str]]:
    """Provenance for the metrics behind the report. Returns (table, hidden metric ids).

    A `Metric` carries no airport, so the airport column appears only when the report covers exactly one
    airport. With several airports use `comparison_table` for per-airport values — guessing which metric
    belongs to which airport would be inventing data.
    """
    order: list[str] = []
    for metric in rep.evidence:
        if metric.id not in order:
            order.append(metric.id)
    matched = [m for m in show if m in order]
    unmatched = [m for m in show if m not in order]
    shown = matched or list(order)  # ids we do not have must never collapse the evidence to nothing
    hidden = [m for m in order if m not in shown]
    single = rep.rows[0].ref.iata if len(rep.rows) == 1 else None
    columns = ["metric", *(["airport"] if single else []), *METRIC_PROVENANCE_COLUMNS]
    rows = [[_label(metric.id, specs_by_id), *([single] if single else []), *_metric_row(metric)]
            for metric_id in shown for metric in rep.evidence if metric.id == metric_id]
    footnotes = [] if single else ["Values are per metric across the airports in the report; see the "
                                   "comparison table for per-airport values."]
    if hidden:
        footnotes.append(f"{len(hidden)} further metrics collected but not shown: {', '.join(hidden)}.")
    if unmatched:
        footnotes.append(f"Requested metrics not in this report, so everything is shown: "
                         f"{', '.join(unmatched)}.")
    return Table(title=f"Evidence — {len(shown)} of {len(order)} metrics", columns=columns, rows=rows,
                 footnotes=footnotes), hidden


def comparison_table(rep: DeterministicReport, specs_by_id: dict[str, MetricSpec]) -> Table:
    """Side-by-side values per airport, plus the percentile within the peer group when the report has it."""
    comparison = rep.comparison or {}
    iatas = [row.ref.iata for row in sorted(rep.rows, key=lambda r: r.rank)]
    if not iatas:
        iatas = sorted({iata for values in comparison.values() for iata in values})
    percentiles = rep.percentiles or {}
    columns = ["metric", "name", "unit", *iatas, *([f"pct {i}" for i in iatas] if percentiles else [])]
    rows = []
    for metric_id, values in comparison.items():
        spec = specs_by_id.get(metric_id)
        row: list[Any] = [metric_id, spec.name if spec else metric_id, spec.unit if spec else ""]
        row += [values.get(iata) for iata in iatas]
        if percentiles:
            row += [percentiles.get(metric_id, {}).get(iata) for iata in iatas]
        rows.append(row)
    return Table(title=f"Comparison — horizon {rep.horizon} (percentiles within {rep.peer_group})",
                 columns=columns, rows=rows, footnotes=[])


def specialist_ranking_table(rep: SpecialistReport) -> Table | None:
    """The analyst's own ordering, kept separate from the formula's so the two can be compared."""
    if not rep.ranking:
        return None
    rows = [[item.rank, item.iata, item.rationale, item.confidence]
            for item in sorted(rep.ranking, key=lambda i: i.rank)]
    return Table(title=f"Analyst ranking — {rep.specialist}",
                 columns=["rank", "airport", "rationale", "confidence"], rows=rows,
                 footnotes=["The analyst's ordering and confidence, not the formula's."])


def _report_from_dict(result: dict[str, Any]) -> DeterministicReport:
    fields = set(DeterministicReport.model_fields)
    return DeterministicReport(**{k: v for k, v in result.items() if k in fields})


def _route_tables(result: dict[str, Any]) -> list[Table]:
    iata, horizon = result.get("iata", "?"), result.get("horizon", "?")
    convention = result.get("convention", "")
    bands = result.get("distance_bands") or {}
    band_rows = [[kind, *[(bands.get(kind) or {}).get(band) for band in BANDS]] for kind in bands]
    shares = result.get("long_haul_share") or {}
    share_rows = [[kind, metric.get("value"), metric.get("unit"), metric.get("period_end"),
                   metric.get("source_id"), metric.get("vintage")] for kind, metric in shares.items()]
    footnotes = [convention] if convention else []
    return [
        Table(title=f"Distance bands — {iata} ({horizon})", columns=["kind", *BANDS], rows=band_rows,
              footnotes=list(footnotes)),
        Table(title=f"Long-haul share — {iata} ({horizon})",
              columns=["kind", "share", "unit", "period_end", "source", "vintage"], rows=share_rows,
              footnotes=list(footnotes)),
    ]


def _profile_tables(result: dict[str, Any], specs_by_id: dict[str, MetricSpec]) -> list[Table]:
    iata = (result.get("ref") or {}).get("iata", "?")
    tables: list[Table] = []
    for horizon, metrics in (result.get("metrics") or {}).items():
        present = [m for m in metrics if m.get("value") is not None]
        rows = [[_label(m["id"], specs_by_id), m.get("value"), m.get("unit"), m.get("horizon"),
                 m.get("period_end"), m.get("source_id"), m.get("vintage")] for m in present]
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


def _simple_tables(tool: str, result: dict[str, Any]) -> list[Table]:
    if tool == "find_airports":
        return [_airports_table(result)]
    if tool == "get_metric_series":
        series = result.get("series") or []
        title = f"Series — {result.get('iata', '?')} {result.get('metric_id', '?')}"
        return [Table(title=title, columns=["period_end", "value", "unit", "horizon", "source", "vintage"],
                      rows=[[m.get("period_end"), m.get("value"), m.get("unit"), m.get("horizon"),
                             m.get("source_id"), m.get("vintage")] for m in series], footnotes=[])]
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
            rows.append([source.get("source_id"), source.get("description"), period, source.get("fetched_at")])
        return [Table(title=f"Sources ({len(sources)})",
                      columns=["source_id", "description", "period", "fetched_at"], rows=rows, footnotes=[])]
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
        if report.comparison:
            tables.append(comparison_table(report, specs_by_id))
        evidence, _ = evidence_table(report, [], specs_by_id)
        if evidence.rows:
            tables.append(evidence)
        return tables
    if tool == "get_route_stats":
        return _route_tables(result)
    if tool == "get_profile":
        return _profile_tables(result, specs_by_id)
    return _simple_tables(tool, result)


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
