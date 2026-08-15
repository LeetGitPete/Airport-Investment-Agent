from __future__ import annotations

import pytest
from pydantic import BaseModel

from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import LLMError, ToolSpec


class EchoArgs(BaseModel):
    text: str
    n: int = 1


def _echo(p: EchoArgs) -> dict:
    return {"out": p.text * p.n}


def _boom(p: EchoArgs) -> dict:
    raise LLMError("gemini", 500, "x")


@pytest.fixture
def reg():
    r = ToolRegistry()
    r.register(ToolSpec(name="echo", description="Echo text n times.", params_model=EchoArgs, fn=_echo,
                        engines=["concierge", "general_analyst"]))
    r.register(ToolSpec(name="boom", description="Raises.", params_model=EchoArgs, fn=_boom, engines=["concierge"]))
    return r


def test_register_and_openai_shape(reg):
    assert reg.names() == ["echo", "boom"] and reg.names("general_analyst") == ["echo"]
    tools = reg.openai_tools("concierge")
    assert tools[0]["type"] == "function" and tools[0]["function"]["name"] == "echo"
    assert "properties" in tools[0]["function"]["parameters"]
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(ToolSpec(name="echo", description="d", params_model=EchoArgs, fn=_echo, engines=[]))


def test_call_validates_and_fills_defaults(reg):
    assert reg.call("echo", {"text": "ab", "n": 2}) == {"out": "abab", "provenance": [], "truncated": False}
    bad = reg.call("echo", {"n": "x"})
    assert "invalid arguments" in bad["error"] and bad["provenance"] == []
    unk = reg.call("nope", {})
    assert "unknown tool" in unk["error"] and "echo" in unk["error"]


def test_engine_gate(reg):
    assert "not available to engine" in reg.call("boom", {"text": "a"}, engine="general_analyst")["error"]


def test_llm_error_propagates(reg):
    with pytest.raises(LLMError):
        reg.call("boom", {"text": "a"}, engine="concierge")


def test_non_dict_result_is_error_dict():
    r = ToolRegistry()
    r.register(ToolSpec(name="bad", description="Returns a list.", params_model=EchoArgs,
                        fn=lambda p: ["not", "a", "dict"], engines=["concierge"]))
    out = r.call("bad", {"text": "a"}, engine="concierge")
    assert out["error"] == "TypeError: tool 'bad' returned non-dict result"
    assert out["provenance"] == [] and out["truncated"] is False


def test_non_str_arg_keys_is_error_dict(reg):
    out = reg.call("echo", {1: "a"}, engine="concierge")
    assert "invalid arguments" in out["error"]
