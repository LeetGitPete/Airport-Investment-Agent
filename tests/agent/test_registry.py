from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from airport_agent.agent.tools.provenance import ProvenanceSpec
from airport_agent.agent.tools.registry import ToolRegistry
from airport_agent.contracts import LLMError, ToolSpec


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")  # QA task 14: the registry requires this of every tool
    text: str
    n: int = 1


class LooseArgs(BaseModel):
    text: str = ""


#: QA task 18: every registration must declare provenance; these fakes read nothing real.
ECHO_PROV = ProvenanceSpec.none("test double, no data source")


def _echo(p: EchoArgs) -> dict:
    return {"out": p.text * p.n}


def _boom(p: EchoArgs) -> dict:
    raise LLMError("gemini", 500, "x")


@pytest.fixture
def reg():
    r = ToolRegistry()
    r.register(ToolSpec(name="echo", description="Echo text n times.", params_model=EchoArgs, fn=_echo,
                        engines=["concierge", "general_analyst"]), provenance=ECHO_PROV)
    r.register(ToolSpec(name="boom", description="Raises.", params_model=EchoArgs, fn=_boom, engines=["concierge"]),
               provenance=ECHO_PROV)
    return r


def test_register_and_openai_shape(reg):
    assert reg.names() == ["echo", "boom"] and reg.names("general_analyst") == ["echo"]
    tools = reg.openai_tools("concierge")
    assert tools[0]["type"] == "function" and tools[0]["function"]["name"] == "echo"
    assert "properties" in tools[0]["function"]["parameters"]
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(ToolSpec(name="echo", description="d", params_model=EchoArgs, fn=_echo, engines=[]),
                     provenance=ECHO_PROV)


def test_call_validates_and_fills_defaults(reg):
    # QA task 18: a no-external-source tool carries its reason into the result, so the answer can
    # say "registry definition, not measured data" instead of showing an empty source list.
    assert reg.call("echo", {"text": "ab", "n": 2}) == {
        "out": "abab", "provenance": [], "truncated": False,
        "provenance_note": "test double, no data source"}
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
                        fn=lambda p: ["not", "a", "dict"], engines=["concierge"]), provenance=ECHO_PROV)
    out = r.call("bad", {"text": "a"}, engine="concierge")
    assert out["error"] == "TypeError: tool 'bad' returned non-dict result"
    assert out["provenance"] == [] and out["truncated"] is False


def test_non_str_arg_keys_is_error_dict(reg):
    out = reg.call("echo", {1: "a"}, engine="concierge")
    assert "invalid arguments" in out["error"]


# --- QA task 14: invented arguments are rejected loudly and actionably ------------------------------------

def test_a_tool_that_would_ignore_unknown_arguments_cannot_be_registered():
    r = ToolRegistry()
    with pytest.raises(ValueError, match="extra='forbid'"):
        r.register(ToolSpec(name="loose", description="d", params_model=LooseArgs, fn=lambda p: {},
                            engines=["concierge"]), provenance=ECHO_PROV)


def test_every_tool_schema_forbids_extra_properties(reg):
    for tool in reg.openai_tools("concierge"):
        assert tool["function"]["parameters"]["additionalProperties"] is False


def test_invented_argument_is_rejected_and_the_error_names_what_is_allowed(reg):
    out = reg.call("echo", {"text": "a", "domestic_only": True}, engine="concierge")
    assert "invalid arguments" in out["error"] and "domestic_only" in out["error"]
    assert "allowed arguments for echo: n, text (required)" in out["error"]


def test_arg_introspection_and_pruning(reg):
    assert reg.arg_names("echo") == (["n", "text"], ["text"])
    kept, dropped = reg.prune_args("echo", {"text": "a", "domestic_only": True, "zzz": 1})
    assert kept == {"text": "a"} and dropped == ["domestic_only", "zzz"]
    assert reg.prune_args("echo", {"text": "a"}) == ({"text": "a"}, [])
