"""LiteLLM-backed LLMClient. One Router over config/providers.yaml; every failure surfaces as LLMError."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from airport_agent.contracts import LLMError, LLMResult, ToolCall
from airport_agent.llm.config import LLMConfig, load_llm_config


class LiteLLMClient:
    def __init__(self, config: LLMConfig | None = None, env: Mapping[str, str] | None = None,
                 completion_fn: Callable[..., Any] | None = None) -> None:
        self.config = config or load_llm_config()
        if env is None:
            from dotenv import load_dotenv
            load_dotenv()
            env = os.environ
        self._env = dict(env)
        self._completion = completion_fn
        self.provider_name = self.config.providers[0].name

    def _key(self, i: int = 0) -> str | None:
        return self._env.get(self.config.providers[i].api_key_env) or None

    def status(self) -> list[dict[str, str]]:
        return [{"name": p.name, "model": p.model,
                 "status": "configured" if self._env.get(p.api_key_env) else "missing key",
                 "detail": f"{p.api_key_env} {'set' if self._env.get(p.api_key_env) else 'not set'}; rpm {p.rpm}"}
                for p in self.config.providers]

    def _router_completion(self) -> Callable[..., Any]:
        import litellm
        model_list = [{"model_name": p.name,
                       "litellm_params": {"model": p.model, "api_key": self._env.get(p.api_key_env),
                                          "timeout": p.timeout_s, "rpm": p.rpm}}
                      for p in self.config.providers]
        names = [p.name for p in self.config.providers]
        kwargs: dict[str, Any] = {"model_list": model_list, "num_retries": self.config.providers[0].max_retries}
        if len(names) > 1:
            kwargs["fallbacks"] = [{names[0]: names[1:]}]
        return litellm.Router(**kwargs).completion

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             response_schema: dict[str, Any] | None = None, temperature: float = 0.2) -> LLMResult:
        primary = self.config.providers[0]
        if not self._key(0):
            raise LLMError(primary.name, None, f"{primary.api_key_env} not set")
        if self._completion is None:
            self._completion = self._router_completion()
        kwargs: dict[str, Any] = {"model": primary.name, "messages": messages, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_schema is not None:
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "response", "schema": response_schema}}
        try:
            resp = self._completion(**kwargs)
        except Exception as e:  # noqa: BLE001 - every provider failure must become a loud LLMError
            raise LLMError(primary.name, getattr(e, "status_code", None), str(e)[:400]) from e
        choice = resp.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            raw = tc.function.arguments or "{}"
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    args = {"_raw": raw}
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append(ToolCall(id=str(tc.id), name=tc.function.name, arguments=args))
        usage = getattr(resp, "usage", None)
        return LLMResult(text=msg.content or "", tool_calls=calls, provider=primary.name,
                         model=getattr(resp, "model", None) or primary.model,
                         input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                         output_tokens=getattr(usage, "completion_tokens", None) if usage else None)
