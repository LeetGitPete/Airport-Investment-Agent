"""ToolRegistry: named subsets of pydantic-validated tools for the Concierge and each specialist (design 03)."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from airport_agent.contracts import LLMError, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name {spec.name!r}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def names(self, engine: str | None = None) -> list[str]:
        return [n for n, s in self._tools.items() if engine is None or engine in s.engines]

    def for_engine(self, engine: str) -> list[ToolSpec]:
        return [s for s in self._tools.values() if engine in s.engines]

    def openai_tools(self, engine: str) -> list[dict[str, Any]]:
        return [{"type": "function", "function": s.json_schema()} for s in self.for_engine(engine)]

    def call(self, name: str, args: dict[str, Any], engine: str | None = None) -> dict[str, Any]:
        def err(msg: str) -> dict[str, Any]:
            return {"error": msg, "provenance": [], "truncated": False}

        spec = self._tools.get(name)
        if spec is None:
            return err(f"unknown tool {name!r}; available: {self.names(engine)}")
        if engine is not None and engine not in spec.engines:
            return err(f"tool {name!r} is not available to engine {engine!r}")
        try:
            params = spec.params_model(**args)
        except ValidationError as e:
            return err(
                "invalid arguments: "
                + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            )
        except TypeError as e:  # e.g. non-string argument keys from a malformed tool call
            return err(f"invalid arguments: {e}")
        try:
            out = spec.fn(params)
        except LLMError:
            raise
        except (KeyError, ValueError, TypeError) as e:
            return err(f"{type(e).__name__}: {e}")
        if not isinstance(out, dict):
            return err(f"TypeError: tool {name!r} returned non-dict result")
        out.setdefault("provenance", [])
        out.setdefault("truncated", False)
        return out
