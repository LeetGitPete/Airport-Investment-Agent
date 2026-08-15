"""Tolerant JSON extraction for structured LLM outputs."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_text(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    m = _FENCE.search(text)
    if m:
        candidates.insert(0, m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"LLM output is not JSON: {text[:200]!r}")
