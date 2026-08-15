"""LLM client port. Implementations live in airport_agent.llm (LiteLLM router). Errors are never swallowed."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMError(Exception):
    """Raised after retries are exhausted. Must surface to the user verbatim (design 03 failure policy)."""

    def __init__(self, provider: str, status: int | None, detail: str):
        self.provider, self.status, self.detail = provider, status, detail
        super().__init__(f"LLM provider error — {provider}: {status if status is not None else 'error'} {detail}. "
                          "Check the API key in .env, your quota, or configure a provider in config/providers.yaml.")


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic chat/tool-calling interface."""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
              response_schema: dict[str, Any] | None = None, temperature: float = 0.2) -> LLMResult:
        """Send a chat turn, optionally offering tools and/or requesting a structured response schema."""
        ...
