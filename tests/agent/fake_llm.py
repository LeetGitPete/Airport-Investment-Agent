"""ScriptedLLM — a canned, order-preserving LLMClient double. No network, no randomness.

Each call to `chat()` pops the next entry off the script: a dict becomes a JSON-encoded LLMResult, a str
becomes a plain-text LLMResult, an LLMResult passes through unchanged, and an Exception (e.g. LLMError) is
raised. Every call's kwargs are recorded in `.calls`, including calls that raise or exhaust the script, so
tests can assert on exactly what the caller sent.
"""
from __future__ import annotations

import json
from typing import Any

from airport_agent.contracts import LLMResult


class ScriptedLLM:
    """contracts.LLMClient double driven by a fixed script of responses."""

    def __init__(self, script: list[LLMResult | dict | str | Exception]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
              response_schema: dict[str, Any] | None = None, temperature: float = 0.2) -> LLMResult:
        self.calls.append({"messages": messages, "tools": tools, "response_schema": response_schema,
                            "temperature": temperature})
        assert self._script, "script exhausted"
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResult):
            return item
        if isinstance(item, dict):
            return LLMResult(text=json.dumps(item), provider="fake", model="scripted")
        return LLMResult(text=item, provider="fake", model="scripted")
