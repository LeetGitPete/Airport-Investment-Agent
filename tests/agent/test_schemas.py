"""Every structured-output schema stays a portable JSON-schema subset (limitations row 26).

Gemini structured output (and most other providers) rejects or silently ignores anyOf / oneOf / $ref /
additionalProperties / nullable. The three schemas therefore use enums with a "none" sentinel, empty lists and
empty strings instead of optional or union-typed fields.
"""
from __future__ import annotations

import json

import pytest

from airport_agent.agent.planner import PLAN_SCHEMA
from airport_agent.agent.specialists.schema import SPECIALIST_SCHEMA
from airport_agent.agent.synthesis import SYNTHESIS_SCHEMA

FORBIDDEN = ("anyOf", "oneOf", "allOf", "$ref", "additionalProperties", "nullable", "null")
SCHEMAS = {"PLAN_SCHEMA": PLAN_SCHEMA, "SPECIALIST_SCHEMA": SPECIALIST_SCHEMA,
           "SYNTHESIS_SCHEMA": SYNTHESIS_SCHEMA}
ALLOWED_KEYWORDS = {"type", "properties", "required", "items", "enum", "description"}


def _walk(node, path="root"):
    if isinstance(node, dict):
        if "type" in node or "properties" in node:
            unexpected = set(node) - ALLOWED_KEYWORDS
            assert not unexpected, f"{path}: unsupported schema keywords {sorted(unexpected)}"
        for key, value in node.items():
            if key != "properties":
                _walk(value, f"{path}.{key}")
            else:
                for name, sub in value.items():
                    _walk(sub, f"{path}.{name}")


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_is_portable(name):
    schema = SCHEMAS[name]
    dumped = json.dumps(schema)
    for keyword in FORBIDDEN:
        assert keyword not in dumped, f"{name} uses {keyword}"
    assert set(schema["required"]) == set(schema["properties"]), f"{name}: every key must be required"
    _walk(schema, name)


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_property_is_documented(name):
    for prop, node in SCHEMAS[name]["properties"].items():
        assert node.get("description"), f"{name}.{prop} has no description for the model to read"
