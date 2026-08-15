from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from airport_agent.contracts import LLMClient, LLMError, LLMResult
from airport_agent.llm.client import LiteLLMClient
from airport_agent.llm.config import LLMConfig, ProviderConfig

CFG = LLMConfig(providers=[ProviderConfig(name="gemini", model="gemini/x", api_key_env="GEMINI_API_KEY")])


def _resp(content="hi", tool_calls=None, model="gemini/x"):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], model=model, usage=NS(prompt_tokens=10, completion_tokens=5))


def test_satisfies_protocol_and_status():
    c = LiteLLMClient(CFG, env={"GEMINI_API_KEY": "k"}, completion_fn=lambda **kw: _resp())
    assert isinstance(c, LLMClient) and c.provider_name == "gemini"
    assert c.status()[0]["status"] == "configured"
    assert LiteLLMClient(CFG, env={}, completion_fn=lambda **kw: _resp()).status()[0]["status"] == "missing key"


def test_chat_maps_text_and_tokens():
    calls = []

    def fake(**kw):
        calls.append(kw)
        return _resp("hello")

    c = LiteLLMClient(CFG, env={"GEMINI_API_KEY": "k"}, completion_fn=fake)
    r = c.chat([{"role": "user", "content": "x"}], temperature=0.1)
    assert isinstance(r, LLMResult) and r.text == "hello" and r.provider == "gemini" and r.model == "gemini/x"
    assert r.input_tokens == 10 and r.output_tokens == 5
    assert calls[0]["model"] == "gemini" and calls[0]["temperature"] == 0.1 and "tools" not in calls[0]


def test_chat_passes_tools_and_schema():
    calls = []
    c = LiteLLMClient(CFG, env={"GEMINI_API_KEY": "k"}, completion_fn=lambda **kw: calls.append(kw) or _resp())
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}}}]
    c.chat([{"role": "user", "content": "x"}], tools=tools, response_schema={"type": "object", "properties": {}})
    assert calls[0]["tools"] == tools and calls[0]["tool_choice"] == "auto"
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["schema"] == {"type": "object", "properties": {}}


def test_chat_maps_tool_calls_and_bad_json_args():
    tc = [NS(id="1", function=NS(name="find_airports", arguments='{"states": ["MA"]}')),
          NS(id="2", function=NS(name="x", arguments="not json"))]
    c = LiteLLMClient(CFG, env={"GEMINI_API_KEY": "k"}, completion_fn=lambda **kw: _resp(None, tc))
    r = c.chat([{"role": "user", "content": "x"}])
    assert r.text == "" and r.tool_calls[0].name == "find_airports" and r.tool_calls[0].arguments == {"states": ["MA"]}
    assert r.tool_calls[1].arguments == {"_raw": "not json"}


def test_missing_key_raises_llm_error_at_chat_time():
    c = LiteLLMClient(CFG, env={}, completion_fn=lambda **kw: _resp())
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        c.chat([{"role": "user", "content": "x"}])


def test_provider_exception_becomes_llm_error_with_status():
    class Boom(Exception):
        status_code = 429

    def fake(**kw):
        raise Boom("quota exceeded")

    c = LiteLLMClient(CFG, env={"GEMINI_API_KEY": "k"}, completion_fn=fake)
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.provider == "gemini" and ei.value.status == 429 and "quota" in ei.value.detail
    assert "LLM provider error — gemini: 429" in str(ei.value)
