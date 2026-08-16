"""Code-built tables: every cell comes from a report or a tool result, never from the LLM (design 03).

The Concierge chooses WHICH rows to surface (via `show_metrics`) and must say what it hid; it can never change
a value, a unit or a citation, because the LLM never touches this module's inputs.
"""
from __future__ import annotations

import re
from typing import Any

from airport_agent.contracts import (
    PILLAR_NAMES,
    Citation,
    DeterministicReport,
    Metric,
    MetricSpec,
    SpecialistReport,
    Table,
)
from airport_agent.contracts.display import (  # noqa: F401 — historical re-export
    PEER_GROUP_DISPLAY,
    SOURCE_DISPLAY,
    peer_label,
    source_name,
)

PILLARS = ["P1", "P2", "P3", "P4", "P5"]
BANDS = ["short", "medium", "long", "ultra"]
#: User-facing labels only. "time period" = the analysis window (12m/3y/5y/10y); "data as of" =
#: the data's own date (period end / source-file date), NOT the moment we fetched it.
METRIC_PROVENANCE_COLUMNS = ["value", "unit", "time period", "period end", "source", "data as of"]
#: Tool results that are DeterministicReport dumps.
REPORT_TOOLS = ("score_airports", "compare_airports", "diagnose_unmet_demand")



#: User-facing names for tools and engines — the ONLY place an internal tool id gets a user name.
#: Raw ids (get_route_stats, specialist:expansion_analyst) are dev-facing and may appear only inside
#: "Show work"; every other surface goes through `tool_label` / `humanize_tool_ids` (human decision
#: 2026-08-16, same pattern as SOURCE_DISPLAY and humanize_metric_ids).
TOOL_DISPLAY: dict[str, str] = {
    "find_airports": "Airport search",
    "get_profile": "Airport profile",
    "get_route_stats": "Route statistics",
    "get_live_status": "Live airport status",
    "get_metric_series": "Metric history",
    "list_sources": "Data sources",
    "explain_metric": "Metric definition",
    "score_airports": "Deterministic scoring",
    "compare_airports": "Deterministic comparison",
    "diagnose_unmet_demand": "Demand diagnosis",
    "session_memory": "Earlier answer (memory)",
    "deterministic": "Deterministic scoring",
    "deterministic:rank": "Deterministic scoring (rank)",
    "deterministic:compare": "Deterministic scoring (compare)",
    "deterministic:diagnose": "Deterministic scoring (diagnose)",
    "deterministic:long_haul_share": "Deterministic scoring (long-haul share)",
    "deterministic:distance_bands": "Deterministic scoring (distance bands)",
    "specialist:expansion_analyst": "AI analyst (expansion)",
    "specialist:capacity_analyst": "AI analyst (capacity)",
    "specialist:market_analyst": "AI analyst (market)",
    "specialist:general_analyst": "AI analyst (general)",
    "expansion_analyst": "AI analyst (expansion)",
    "capacity_analyst": "AI analyst (capacity)",
    "market_analyst": "AI analyst (market)",
    "general_analyst": "AI analyst (general)",
}


def tool_label(tool_id: str) -> str:
    """User-facing name for a tool/engine id. Unmapped ids fall back to a de-snaked title, never raw."""
    if tool_id in TOOL_DISPLAY:
        return TOOL_DISPLAY[tool_id]
    return tool_id.replace("specialist:", "AI analyst: ").replace("_", " ").replace(":", " · ")


def humanize_tool_ids(text: str) -> str:
    """Replace internal tool/engine ids with their user-facing names in prose (deterministic backstop,
    the tool-id counterpart of `humanize_metric_ids`; longest-first so `specialist:x` wins over `x`)."""
    if not text:
        return text
    for tool_id in sorted(TOOL_DISPLAY, key=len, reverse=True):
        if tool_id in text:
            text = re.sub(rf"`?\b{re.escape(tool_id)}\b`?", TOOL_DISPLAY[tool_id], text)
    return text


#: What rank 1 / a high score MEANS under each preset. Percentiles are direction-adjusted per
#: metric, so a higher score always means "stronger case for the preset's objective" — these spell
#: that out per preset so no table needs decoding.
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


def unit_label(unit: str | None) -> str:
    return UNIT_DISPLAY.get(unit or "", unit or "")




def _metric_name(metric_id: str, specs_by_id: dict[str, MetricSpec]) -> str:
    spec = specs_by_id.get(metric_id)
    return spec.name if spec else metric_id


def humanize_metric_ids(text: str, specs_by_id: dict[str, MetricSpec]) -> str:
    """Replace internal metric ids with display names in LLM-written prose.

    The specialist is prompted to use display names, but this is the deterministic backstop —
    ids are distinctive snake_case tokens, replaced longest-first on word boundaries so
    e.g. `enpl_cagr_5y` never partially matches inside `enpl_cagr_5y_x`.
    """
    if not text:
        return text
    for metric_id in sorted(specs_by_id, key=len, reverse=True):
        if metric_id in text:
            text = re.sub(rf"`?\b{re.escape(metric_id)}\b`?", specs_by_id[metric_id].name, text)
    # Pillar ids are internal too: P2 -> "Congestion & Physical Constraint" etc.
    text = re.sub(r"`?\bP([1-5])\b`?", lambda m: PILLAR_NAMES[f"P{m.group(1)}"], text)
    return text


def _metric_row(metric: Metric) -> list[Any]:
    return [metric.value, unit_label(metric.unit), metric.horizon, metric.period_end,
            source_name(metric.source_id), metric.vintage]


def ranking_table(rep: DeterministicReport) -> Table:
    """The deterministic scores, verbatim: score, coverage and the pillar contributions behind them.

    A single-airport report has no meaningful rank: the rank column is dropped and the table is
    titled "Scores". Pillar columns are limited to the pillars the preset actually weights.
    """
    single = len(rep.rows) == 1
    pillars = [p for p in PILLARS if rep.weights.get(p)] or PILLARS
    # User-facing pillar names in columns; "P1..P5" stay internal.
    columns = [*([] if single else ["rank"]), "airport", "name", "airport size", "score", "coverage",
               "low_confidence", *[PILLAR_NAMES[p] for p in pillars]]
    rows = [[*([] if single else [row.rank]), row.ref.iata, row.ref.name, row.ref.hub_size, row.score,
             row.coverage, row.low_confidence, *[row.pillar_contrib.get(p) for p in pillars]]
            for row in sorted(rep.rows, key=lambda r: r.rank)]
    focus = (rep.preset or "balanced").replace("_", " ")
    kind = "Scores" if single else "Ranking"
    footnotes = ["Score = how strong the investment case is (0-100 within the peer group); "
                 "it is a relative standing, not a dollar figure."] if single else [rank_legend(rep.preset)]
    footnotes.append("Pillar columns are contributions to the score (weight x percentile x 100).")
    return Table(title=f"{kind} — {focus} focus, time period {rep.horizon}, "
                       f"percentiles among {peer_label(rep.peer_group)}",
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


PROVENANCE_TITLE = "Where this came from"


def provenance_table(entries: list[dict[str, str]], covers: dict[str, list[str]] | None = None,
                     notes: list[str] | None = None) -> Table | None:
    """One table per answer naming every source behind it.

    Metric-level tables carry their own `source` / `data as of` columns — one row per metric, each
    genuinely from a different place, so the column earns its width there. Everything else (airports,
    live status, distance bands, rankings) would just repeat one value down every row, so those are
    covered here instead.

    `covers` maps a source id to the tools that used it, so a reader can trace a table to its origin.
    Returns None when there is nothing to cite, so an answer with no data does not grow an empty table.
    """
    by_source: dict[str, dict[str, str]] = {}
    for entry in entries:
        source_id = entry.get("source_id") or ""
        if not source_id:
            continue
        held = by_source.setdefault(source_id, {})
        for key in ("vintage", "period_start", "period_end"):
            if entry.get(key) and not held.get(key):
                held[key] = entry[key]
    if not by_source:
        return None
    rows = []
    for source_id, held in by_source.items():
        period = " to ".join(p for p in (held.get("period_start"), held.get("period_end")) if p)
        used_by = ", ".join(sorted(set((covers or {}).get(source_id, []))))
        rows.append([source_name(source_id), used_by or "-", period or "-", held.get("vintage") or "-"])
    footnotes = list(notes or [])
    footnotes.append("'Data as of' is when we fetched the source, not when its publisher released it; "
                     "the period is what the data itself covers.")
    return Table(title=PROVENANCE_TITLE, columns=["source", "used for", "period", "data as of"],
                 rows=rows, footnotes=footnotes)


def data_matrix(rep: DeterministicReport, specs_by_id: dict[str, MetricSpec]) -> Table:
    """THE canonical metrics table for every analytical answer — always shown.

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



#: One-line, user-facing statement of how the deterministic score is computed.
SCORE_FORMULA_CAPTION = ("Score = sum over pillars of (pillar weight × metric weight × percentile "
                         "among peers) × 100, so 100 = the strongest case among peers under this "
                         "preset. The pillar split is in the Scores table.")

_SCORE_TITLE = re.compile(r"^(?:Ranking|Scores) — (.+?) focus,")


def score_summary(tables: list[Table]) -> dict[str, Any] | None:
    """Extract the headline score strip from an answer's tables.

    Returns {label, scores: [(iata, score), ...] (≤4), shown, total, caption} from the
    Ranking/Scores table, or None when the answer has no deterministic scores. Derived from the
    rendered table so the strip can never disagree with it.
    """
    for table in tables:
        match = _SCORE_TITLE.match(table.title)
        if not match or "score" not in table.columns or "airport" not in table.columns:
            continue
        airport_i, score_i = table.columns.index("airport"), table.columns.index("score")
        pairs = [(str(row[airport_i]), row[score_i]) for row in table.rows[:4]]
        if not pairs:
            return None
        preset = match.group(1).replace("_", " ")
        return {"label": f"{preset} score", "scores": pairs, "shown": len(pairs),
                "total": len(table.rows), "caption": SCORE_FORMULA_CAPTION}
    return None


def specialist_ranking_table(rep: SpecialistReport,
                             specs_by_id: dict[str, MetricSpec] | None = None) -> Table | None:
    """The analyst's own ordering, kept separate from the formula's so the two can be compared."""
    if not rep.ranking:
        return None
    rows = [[item.rank, item.iata, humanize_metric_ids(item.rationale, specs_by_id or {}),
             item.confidence]
            for item in sorted(rep.ranking, key=lambda i: i.rank)]
    return Table(title=f"Analyst ranking — {tool_label(rep.specialist)}",
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
        footnotes = ([f"{missing} metrics have no value for this airport in this time period."]
                     if missing else [])
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
    return Table(title=f"Airports ({count})",
                 columns=["iata", "name", "city", "state", "FAA region", "airport size"],
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
        # Internal registry fields (id, tier, pillar code) stay off this table by decision
        # 2026-08-16 — the user asked what a metric MEANS, not how the registry files it.
        keys = ["name", "definition", "formula", "unit", "direction", "pillar_name", "horizons", "caveats"]
        rows = [[k.replace("_", " "),
                 ", ".join(map(str, result[k])) if isinstance(result.get(k), list) else result.get(k)]
                for k in keys if k in result]
        if result.get("sources"):
            rows.append(["sources", ", ".join(source_name(str(x)) for x in result["sources"])])
        return [Table(title=f"Definition — {result.get('name') or result.get('id', '?')}",
                      columns=["field", "value"], rows=rows, footnotes=[])]
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
    return [Table(title=f"Result — {tool_label(tool)}", columns=["field", "value"], rows=scalars, footnotes=[])] \
        if scalars else []


def tool_result_tables(tool: str, result: dict[str, Any],
                       specs_by_id: dict[str, MetricSpec]) -> list[Table]:
    """Render one tool result as tables. An error is shown as an error table, never dropped."""
    if result.get("error"):
        return [Table(title="Tool error", columns=["step", "error"], rows=[[tool_label(tool), result["error"]]],
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
