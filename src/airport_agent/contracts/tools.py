"""Tool specification shared by the ToolRegistry (agent) and specialists' allowed-tool subsets."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    name: str
    description: str  # states limits (e.g. hint truncation) explicitly
    params_model: type[BaseModel]
    fn: Callable[..., dict[str, Any]]  # returns JSON-serializable dict with 'provenance' and 'truncated'
    engines: list[str]  # which callers may use it: "concierge", "expansion_analyst", ...

    def json_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": self.params_model.model_json_schema()}
