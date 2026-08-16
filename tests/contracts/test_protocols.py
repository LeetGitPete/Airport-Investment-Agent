from pydantic import BaseModel

from airport_agent.contracts import (
    AnalysisRequest,
    DataService,
    DeterministicAnalyst,
    LLMClient,
    LLMError,
    LLMResult,
    SpecialistRunner,
    ToolCall,
    ToolSpec,
)


def test_reexports_and_protocol_surface():
    assert hasattr(DataService, "get_feature_matrix") and hasattr(DeterministicAnalyst, "diagnose")
    assert hasattr(LLMClient, "chat") and hasattr(SpecialistRunner, "run")
    r = LLMResult(text="hi", tool_calls=[ToolCall(id="1", name="find_airports", arguments={"states": ["MA"]})],
                  provider="gemini", model="gemini-flash", input_tokens=10, output_tokens=5)
    assert r.tool_calls[0].name == "find_airports"
    e = LLMError(provider="gemini", status=429, detail="quota")
    assert "gemini" in str(e) and "429" in str(e)
    assert AnalysisRequest is not None and ToolSpec is not None

    class P(BaseModel):
        iata: str

    spec = ToolSpec(name="find_airports", description="Find airports.", params_model=P,
                     fn=lambda **kw: {"ok": True}, engines=["concierge"])
    schema = spec.json_schema()
    assert schema["name"] == spec.name
    assert "iata" in schema["parameters"]["properties"]
