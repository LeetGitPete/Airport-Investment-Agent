"""ToolRegistry: named subsets of pydantic-validated tools for the Concierge and each specialist (design 03)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from airport_agent.agent.tools.provenance import PROVENANCE_GAP, ProvenanceSpec, prov
from airport_agent.contracts import LLMError, ToolSpec


class ToolRegistry:
    """Named subsets of pydantic-validated tools, each with a declared provenance.

    `source_vintages` is how a declared-but-missing source gets a real vintage rather than a blank:
    the callable is the DataService's own vintage list, injected so the registry stays free of a data
    dependency it would otherwise have to import.
    """

    def __init__(self, source_vintages: Callable[[], list[Any]] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._provenance: dict[str, ProvenanceSpec] = {}
        self._source_vintages = source_vintages

    def register(self, spec: ToolSpec, *, provenance: ProvenanceSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name {spec.name!r}")
        # A tool must say where its data comes from before it can be called. Declared at registration,
        # so a tool added later cannot ship silently unsourced.
        if not isinstance(provenance, ProvenanceSpec):
            raise ValueError(f"tool {spec.name!r}: provenance must be a ProvenanceSpec — declare the "
                             "sources it reads, or ProvenanceSpec.none(reason) if it reads none")
        self._provenance[spec.name] = provenance
        # Every tool's argument model must forbid extras. That is what puts "additionalProperties": false
        # into the schema the provider sees, and what turns an invented argument into a loud, repairable
        # error instead of a silently ignored key.
        if spec.params_model.model_config.get("extra") != "forbid":
            raise ValueError(f"tool {spec.name!r}: params_model must set extra='forbid' so unknown "
                             "arguments are rejected rather than ignored")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def names(self, engine: str | None = None) -> list[str]:
        return [n for n, s in self._tools.items() if engine is None or engine in s.engines]

    def for_engine(self, engine: str) -> list[ToolSpec]:
        return [s for s in self._tools.values() if engine in s.engines]

    def openai_tools(self, engine: str) -> list[dict[str, Any]]:
        return [{"type": "function", "function": s.json_schema()} for s in self.for_engine(engine)]

    def arg_names(self, name: str) -> tuple[list[str], list[str]]:
        """(all argument names, required ones) for a tool — the single source for prompts and errors."""
        schema = self._tools[name].params_model.model_json_schema()
        return sorted(schema.get("properties") or {}), sorted(schema.get("required") or [])

    def args_help(self, name: str) -> str:
        """One-line statement of what this tool accepts, with required arguments marked."""
        allowed, required = self.arg_names(name)
        if not allowed:
            return f"{name} takes no arguments"
        rendered = ", ".join(f"{a} (required)" if a in required else a for a in allowed)
        return f"allowed arguments for {name}: {rendered}"

    def prune_args(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Drop argument keys the tool does not accept. Returns (kept, dropped) — the last-resort
        recovery so an invented filter costs the user a caveat, not the whole answer."""
        allowed, _ = self.arg_names(name)
        kept = {k: v for k, v in args.items() if k in allowed}
        return kept, sorted(k for k in args if k not in allowed)

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
            # Name what IS accepted, so the caller (LLM or human) can fix it in one step
            # instead of guessing again.
            return err(
                "invalid arguments: "
                + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
                + f"; {self.args_help(name)}"
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
        self._apply_provenance(name, out)
        return out

    def provenance_spec(self, name: str) -> ProvenanceSpec:
        return self._provenance[name]

    def _declared_vintages(self, source_ids: list[str]) -> list[dict[str, str]]:
        """Real vintage rows for declared sources, so a floor entry is dated rather than blank."""
        if not source_ids or self._source_vintages is None:
            return [{"source_id": s, "vintage": ""} for s in source_ids]
        wanted = set(source_ids)
        try:
            records = [v for v in self._source_vintages() if getattr(v, "source_id", None) in wanted]
        except Exception:  # noqa: BLE001 - provenance must never be the thing that breaks a turn
            return [{"source_id": s, "vintage": ""} for s in source_ids]
        entries = prov(records)
        found = {e["source_id"] for e in entries}
        return entries + [{"source_id": s, "vintage": ""} for s in source_ids if s not in found]

    def _apply_provenance(self, name: str, out: dict[str, Any]) -> None:
        """The declaration is the floor; what the tool returned is the detail.

        A tool that promised sources but returned none does not fail the turn — the user gets the
        declared sources plus a note. Silence was the bug; a crash would be a worse one.
        """
        spec = self._provenance.get(name)
        if spec is None:
            return
        entries: list[dict[str, str]] = list(out.get("provenance") or [])
        if spec.no_external_source:
            out["provenance_note"] = spec.no_external_source
            return
        missing = spec.missing_from(entries)
        if missing:
            entries.extend(self._declared_vintages(missing))
            out["provenance"] = entries
        if not entries:
            out.setdefault("data_quality_notes", []).append(
                f"{PROVENANCE_GAP}: {name} did not report where its data came from")
