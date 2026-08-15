"""Specialist runner: bounded tool loop + one structured final report (design 03 §LLM Specialists).

Dispatch is structured (`AnalysisRequest`), never free text; the hint is the only free-text channel and is
truncated to the contract's limit before it reaches the model. The model cites evidence as (iata, metric_id)
pairs and **code** resolves them to the `Metric` objects that tools actually returned — so every number in a
`SpecialistReport` carries a real source and vintage, and an unresolvable citation is dropped and reported
instead of being taken on trust.

Failure policy: `LLMError` propagates; a final report that does not match the schema raises `ValueError`
("specialist returned malformed report"). No partial or invented report is ever returned.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from airport_agent.agent.specialists.loader import SpecialistConfig, load_specialist
from airport_agent.agent.specialists.schema import SPECIALIST_SCHEMA
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import (
    AnalysisRequest,
    DeterministicReport,
    LLMClient,
    Metric,
    MetricSpec,
    RankedItem,
    SpecialistReport,
    hint_limit,
    truncate_hint,
)
from airport_agent.llm import parse_json_text

__all__ = ["MAX_TOOL_RESULT_CHARS", "SPECIALIST_SCHEMA", "SpecialistRunnerImpl"]

MAX_TOOL_RESULT_CHARS = 6000
#: Tools whose results carry per-airport metrics (exact (iata, metric_id) evidence).
PROFILE_TOOLS = {"get_profile"}
#: Tools that return a DeterministicReport (evidence carries no airport — indexed by metric id only).
REPORT_TOOLS = {"score_airports", "compare_airports", "diagnose_unmet_demand"}
FINAL_INSTRUCTION = "Produce the final report now as JSON matching the schema. Do not call tools."


# --------------------------------------------------------------------------------------------------
# the model's final JSON (mirrors SPECIALIST_SCHEMA; defaults keep a terse model from failing the run)
# --------------------------------------------------------------------------------------------------
class _FinalRanking(BaseModel):
    iata: str
    rank: int
    rationale: str = ""
    confidence: float = 0.5


class _FinalRef(BaseModel):
    iata: str = ""
    metric_id: str


class _FinalReport(BaseModel):
    ranking: list[_FinalRanking] = Field(default_factory=list)
    narrative: str
    evidence_refs: list[_FinalRef] = Field(default_factory=list)
    agreement: str = ""
    disagreements: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    lens: str = ""


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _cap_lists(node: Any, cap: int, path: tuple[str, ...], trimmed: list[str]) -> Any:
    if isinstance(node, dict):
        return {k: _cap_lists(v, cap, (*path, str(k)), trimmed) for k, v in node.items()}
    if isinstance(node, list):
        if len(node) > cap:
            trimmed.append(f"{'.'.join(path) or 'result'} ({len(node)} of which {cap} kept)")
            node = node[:cap]
        return [_cap_lists(v, cap, path, trimmed) for v in node]
    return node


def fit_tool_result(out: dict[str, Any]) -> str:
    """Serialize a tool result into at most MAX_TOOL_RESULT_CHARS of **valid** JSON.

    A raw string slice would hand the model broken JSON, so oversized results are shortened structurally:
    lists are capped (shortest cap that fits) and the message says what was cut, so the model can ask for a
    narrower call instead of assuming it saw everything.
    """
    text = json.dumps(out)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    for cap in (16, 8, 4, 2, 1):
        trimmed: list[str] = []
        compact = _cap_lists(out, cap, (), trimmed)
        compact["truncated"] = True
        compact["truncation_note"] = ("result too large; lists shortened - " + "; ".join(trimmed)
                                      + ". Ask for a narrower call if you need the rest.")
        text = json.dumps(compact)
        if len(text) <= MAX_TOOL_RESULT_CHARS:
            return text
    return text


class _EvidenceIndex:
    """Every Metric the run actually saw, keyed precisely where the source allows it."""

    def __init__(self) -> None:
        self.exact: dict[tuple[str, str], Metric] = {}
        self.by_metric_id: dict[str, list[Metric]] = {}

    def add(self, metric: Metric, iata: str | None = None) -> None:
        if iata:
            self.exact.setdefault((iata.upper(), metric.id), metric)
        self.by_metric_id.setdefault(metric.id, []).append(metric)

    def seed_from_report(self, report: DeterministicReport) -> None:
        # DeterministicReport.evidence carries no airport, so it can only be indexed by metric id.
        for metric in report.evidence:
            self.add(metric)

    def index_tool_result(self, tool: str, out: dict[str, Any]) -> None:
        if tool in PROFILE_TOOLS:
            iata = (out.get("ref") or {}).get("iata")
            for metrics in (out.get("metrics") or {}).values():
                for raw in metrics if isinstance(metrics, list) else []:
                    if isinstance(raw, dict):
                        self.add(Metric(**raw), iata)
        elif tool in REPORT_TOOLS:
            for raw in out.get("evidence") or []:
                if isinstance(raw, dict):
                    self.add(Metric(**raw))

    def resolve(self, refs: list[_FinalRef]) -> tuple[list[Metric], list[str]]:
        """Resolve the model's citations. Ambiguous and missing references are reported, never guessed at."""
        evidence: list[Metric] = []
        caveats: list[str] = []
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            iata = ref.iata.strip().upper()
            metric = self.exact.get((iata, ref.metric_id))
            if metric is None:
                candidates = self.by_metric_id.get(ref.metric_id, [])
                metric = candidates[0] if candidates else None
                if metric is not None and len(candidates) > 1:
                    caveats.append(f"evidence for {ref.metric_id} resolved by metric id across "
                                   f"{len(candidates)} airports; it may not be {iata or 'that airport'}'s value")
            if metric is None:
                caveats.append(f"dropped unresolved evidence ref {iata or '?'}/{ref.metric_id}")
                continue
            key = (iata, metric.id)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(metric)
        return evidence, caveats


def compact_deterministic(report: DeterministicReport) -> dict[str, Any]:
    """The deterministic view as the specialist sees it: verdict and shape, no evidence list.

    The evidence list is withheld on purpose — if the model wants a number it must fetch it with a tool, so
    what it cites is what it actually received.
    """
    return {
        "preset": report.preset,
        "horizon": report.horizon,
        "peer_group": report.peer_group,
        "explanation": report.explanation,
        "caveats": report.caveats,
        "rows": [{"iata": row.ref.iata, "score": round(row.score, 2), "rank": row.rank,
                  "coverage": round(row.coverage, 3), "low_confidence": row.low_confidence,
                  "pillar_contrib": row.pillar_contrib} for row in report.rows],
        "comparison": report.comparison,
    }


class SpecialistRunnerImpl:
    """contracts.SpecialistRunner over a config artifact, the shared tool registry and one LLM client."""

    def __init__(self, llm: LLMClient, registry: ToolRegistry, specs: list[MetricSpec],
                 config_dir: Path | None = None) -> None:
        self.llm = llm
        self.registry = registry
        self.specs = list(specs)
        self.config_dir = config_dir

    def _tools(self, cfg: SpecialistConfig) -> list[dict[str, Any]]:
        """The specialist's tools: its config's allowed list, enforced against the registry's engine subset."""
        available = set(self.registry.names(engine=cfg.name))
        missing = [t for t in cfg.allowed_tools if t not in available]
        if missing:
            raise ValueError(f"config/specialists/{cfg.name}.md allows tools the registry does not give "
                             f"engine {cfg.name!r}: {missing}")
        return [t for t in self.registry.openai_tools(cfg.name) if t["function"]["name"] in cfg.allowed_tools]

    def _messages(self, cfg: SpecialistConfig, req: AnalysisRequest,
                  deterministic: DeterministicReport | None) -> list[dict[str, Any]]:
        view = json.dumps(compact_deterministic(deterministic)) if deterministic is not None else "none"
        user = "AnalysisRequest:" + "\n" + req.model_dump_json() + "\n\nDeterministic view:" + "\n" + view
        return [{"role": "system", "content": cfg.system_prompt(self.specs)},
                {"role": "user", "content": user}]

    def run(self, req: AnalysisRequest, deterministic: DeterministicReport | None) -> SpecialistReport:
        name = req.specialist
        if not name:
            raise ValueError("AnalysisRequest.specialist is not set; the runner has no specialist to dispatch to")
        cfg = load_specialist(name, self.specs, self.config_dir)
        req2, truncated = truncate_hint(req)
        index = _EvidenceIndex()
        if deterministic is not None:
            index.seed_from_report(deterministic)

        messages = self._messages(cfg, req2, deterministic)
        tools = self._tools(cfg)
        for _ in range(cfg.max_turns):
            result = self.llm.chat(messages=messages, tools=tools)
            if not result.tool_calls:
                break
            messages.append({
                "role": "assistant",
                "content": result.text or None,
                "tool_calls": [{"id": call.id, "type": "function",
                                "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                               for call in result.tool_calls],
            })
            for call in result.tool_calls:
                out = self.registry.call(call.name, call.arguments, engine=name)
                index.index_tool_result(call.name, out)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                 "content": fit_tool_result(out)})

        final_messages = [*messages, {"role": "user", "content": FINAL_INSTRUCTION}]
        result = self.llm.chat(messages=final_messages, response_schema=SPECIALIST_SCHEMA)
        try:
            final = _FinalReport(**parse_json_text(result.text))
        except ValueError as exc:  # includes pydantic ValidationError
            raise ValueError(f"specialist {name} returned a malformed report: {exc}") from exc

        evidence, caveats = index.resolve(final.evidence_refs)
        caveats = [*final.caveats, *caveats]
        if truncated:
            caveats.append(f"hint truncated to {hint_limit(req)} chars")
        if final.lens:
            caveats.append(f"lens: {final.lens}")
        ranking = [RankedItem(iata=item.iata.strip().upper(), rank=item.rank, rationale=item.rationale,
                              confidence=_clamp(item.confidence)) for item in final.ranking]
        return SpecialistReport(specialist=name, question_type=req.question_type, ranking=ranking or None,
                                narrative=final.narrative, evidence=evidence,
                                agreement=final.agreement or None, disagreements=final.disagreements,
                                confidence=_clamp(final.confidence), assumptions=final.assumptions,
                                caveats=caveats, hint_truncated=truncated)
