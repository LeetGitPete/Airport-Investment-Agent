"""The specialist's final-report schema (provider-portable) and its prompt rendering.

Kept in its own module so the config loader (which prints the schema into every system prompt) and the
runner (which sends it as `response_schema`) share one definition and cannot drift apart.
Portability rules are the same as the planner's: only type/properties/required/items/enum/description —
no anyOf, oneOf, $ref, additionalProperties or nullable.
"""
from __future__ import annotations

from typing import Any

SPECIALIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "description": "Your ordering of the airports in the request. Empty list when the question is "
                           "not a ranking or comparison.",
            "items": {
                "type": "object",
                "properties": {
                    "iata": {"type": "string", "description": "Airport IATA code."},
                    "rank": {"type": "integer", "description": "1 = best candidate for the question asked."},
                    "rationale": {"type": "string", "description": "One sentence, evidence-based."},
                    "confidence": {"type": "number", "description": "0-1 confidence in this placement."},
                },
                "required": ["iata", "rank", "rationale", "confidence"],
            },
        },
        "narrative": {"type": "string",
                      "description": "Your analysis. Separate what the data says from your judgement. Every "
                                     "number in it must also appear in evidence_refs."},
        "evidence_refs": {
            "type": "array",
            "description": "Every number you used, as (iata, metric_id) pairs. Code resolves them to metrics "
                           "with source and vintage; an unresolvable pair is dropped and reported.",
            "items": {
                "type": "object",
                "properties": {
                    "iata": {"type": "string", "description": "Airport IATA code the number belongs to."},
                    "metric_id": {"type": "string", "description": "Metric id from your metric slice."},
                },
                "required": ["iata", "metric_id"],
            },
        },
        "agreement": {"type": "string",
                      "description": "One sentence on where you agree with the deterministic view. Empty "
                                     "string when no deterministic view was provided."},
        "disagreements": {"type": "array", "items": {"type": "string"},
                          "description": "Explicit disagreements with the deterministic view, one per entry. "
                                         "Never hide one."},
        "confidence": {"type": "number", "description": "0-1 overall confidence, given coverage and how far "
                                                        "you reasoned beyond the evidence."},
        "assumptions": {"type": "array", "items": {"type": "string"},
                        "description": "Assumptions you made (horizon, conventions, proxies)."},
        "caveats": {"type": "array", "items": {"type": "string"},
                    "description": "Data caveats that apply to your answer."},
        "lens": {"type": "string",
                 "description": "The analytical lens you adopted (e.g. 'capacity'). Empty string if obvious."},
    },
}
SPECIALIST_SCHEMA["required"] = list(SPECIALIST_SCHEMA["properties"])


def _type_name(node: dict[str, Any]) -> str:
    if node["type"] == "array":
        item = node["items"]
        if item["type"] == "object":
            return "[{" + ", ".join(item["properties"]) + "}]"
        return f"[{item['type']}]"
    return str(node["type"])


def schema_doc(schema: dict[str, Any] = SPECIALIST_SCHEMA) -> str:
    """Render the schema as prompt text, so the prompt can never describe a stale shape."""
    lines = [f"- {key} ({_type_name(node)}): {node['description']}"
             for key, node in schema["properties"].items()]
    return ("Return ONLY a JSON object with exactly these keys (all required; use [] or \"\" when you have "
            "nothing to put in one):\n" + "\n".join(lines))
