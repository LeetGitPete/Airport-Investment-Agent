# Plan 2c — LLM layer, Concierge, Specialists, Sessions (`llm/` + `agent/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runtime AI path: LiteLLM-backed `LLMClient` (Gemini only, loud `LLMError`), `ToolRegistry` over `ToolSpec`, the Concierge (Plan → tools / deterministic dispatch / specialist dispatch → code-enforced synthesis into `Answer`), four config-driven LLM specialists, persisted multi-chat sessions, and the `App.answer()` entry point the UI/CLI call — all testable offline with a scripted fake LLM, `FakeDataService`, and a fake `DeterministicAnalyst`.

**Architecture:** `llm/` (imports contracts only) wraps `litellm.Router`; `agent/` is the composition root and may import `contracts`, `llm`, and (lazily, Phase 3) `data`/`scoring`. The Concierge's first LLM call *is* the `Plan` (structured JSON). Code executes the plan (tools with pydantic-validated args, `AnalysisRequest` to the Deterministic Analyst, structured dispatch to a specialist), then one synthesis LLM call chooses headline/what to surface/follow-ups; **code** assembles the fixed `Answer` structure from the reports so the LLM never writes a number.

**Tech Stack:** Python 3.12, pydantic v2, LiteLLM (`litellm.Router`), python-dotenv, PyYAML, pytest. Gemini via `GEMINI_API_KEY`.

**Spec:** `docs/design/03-agent-architecture.md` (roles, question classes, specialist roster, tools, presentation, call budget, failure policy, synthesis "structure + agency"), `docs/design/04-ui.md` (entry point `answer(message, session_state)`, sessions), `docs/research/2026-08-15-llm-free-tier-providers.md`, limitations rows 9, 12, 13, 15, 16, 18. Frozen code: `src/airport_agent/contracts/{llm,tools,conversation,requests,reports,models,specialists,scoring,data_service}.py`, `tests/fakes.py`.

## Global Constraints
- **FROZEN SURFACE:** `src/airport_agent/contracts/**` and `config/metrics.yaml` MUST NOT change. Need a change → STOP, `DECISION NEEDED`. Reviewers git-verify (`git diff --name-only <BASE>..<HEAD> -- src/airport_agent/contracts config/metrics.yaml` prints nothing).
- **Ownership:** this plan writes only `src/airport_agent/agent/**`, `src/airport_agent/llm/**`, `config/providers.yaml`, `config/specialists/**`, `tests/agent/**`, `tests/llm/**`, `tests/golden/**`. Never touch `data/`, `scoring/`, `ui/`, `pyproject.toml`, `tests/fakes.py`, `tests/contracts/**`. Sibling packages `data/` and `scoring/` are EMPTY in this worktree — never import them at module import time; only the lazy defaults in `build_app()` name them (Task 11).
- **Layering:** `llm/` imports only `airport_agent.contracts` + itself. `agent/` may import contracts, llm (and lazily data/scoring). `PYTHONIOENCODING=utf-8 uv run lint-imports` keeps 4 contracts.
- **No network in the default test run.** Live tests are `@pytest.mark.network` + `@pytest.mark.llm` and skip without `GEMINI_API_KEY`.
- **Failure policy (design 03, limitations 15/16):** any provider failure after retries raises `contracts.LLMError` and propagates to the caller unchanged — no fallback answer, no partial deterministic answer presented as the answer. No cross-request caching of LLM outputs or reports (`SessionState.last_reports` is conversation memory, used only for follow-ups in the same session).
- **LLM may not alter numbers, invent weights, hide a disagreement, or omit the assumptions block.** All tables/citations are built by code from `DeterministicReport`/`SpecialistReport`/tool results. Specialist `evidence` is resolved by code from real `Metric`s (references by `(iata, metric_id)`), never parsed from LLM-typed numbers.
- **Hint limits:** `truncate_hint(req)` before dispatch; `SpecialistReport.hint_truncated` reflects it; the dispatch tool descriptions state the limits (200 / 600 chars).
- **Call budget:** ≤ 6 LLM calls per analytical answer (Plan 1 + specialist ≤ 3 + synthesis 1); informational ≈ 2 (Plan + synthesis). Model names only from `config/providers.yaml`.
- Every rendered number carries `source_id` + `vintage` (from `Metric`s / tool `provenance`).
- Escalation protocol (design 05 §5.0). Conventions: type hints, ruff clean, small files, TDD, commit per task with `-c user.name="Pete" -c user.email="Itamarr@voyager-labs.com"`.
- Gate before reporting each task: `uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports && uv run pytest tests/llm tests/agent tests/golden tests/contracts -q`.

---

## File structure

```
config/providers.yaml                         Gemini-only provider chain
config/specialists/{expansion_analyst,capacity_analyst,market_analyst,general_analyst}.md   front-matter + prompt body
src/airport_agent/llm/__init__.py             exports LiteLLMClient, load_llm_config, LLMConfig, ProviderConfig, parse_json_text
src/airport_agent/llm/config.py               ProviderConfig/LLMConfig + load_llm_config(path)
src/airport_agent/llm/client.py               LiteLLMClient(LLMClient): chat(), status(); maps errors -> LLMError
src/airport_agent/llm/jsonutil.py             parse_json_text(text) -> dict (strips ``` fences)
src/airport_agent/agent/__init__.py           exports App, build_app, SessionStore, Concierge
src/airport_agent/agent/tools/__init__.py
src/airport_agent/agent/tools/registry.py     ToolRegistry
src/airport_agent/agent/tools/data_tools.py   build_data_tools(data, analyst) -> list[ToolSpec]
src/airport_agent/agent/tools/analysis_tools.py  build_analysis_tools(analyst) -> list[ToolSpec]
src/airport_agent/agent/planner.py            PLAN_SCHEMA, PlanFilters, Planner (system prompt, plan(), to_analysis_request())
src/airport_agent/agent/specialists/__init__.py
src/airport_agent/agent/specialists/loader.py SpecialistConfig + load_specialist(name, specs, config_dir)
src/airport_agent/agent/specialists/runner.py SpecialistRunnerImpl(SpecialistRunner)
src/airport_agent/agent/tables.py             code renderers: report -> Table, tool result -> Table
src/airport_agent/agent/synthesis.py          SYNTHESIS_SCHEMA, Synthesizer.synthesize(...) -> Answer
src/airport_agent/agent/concierge.py          Concierge.answer(message, state, defaults, on_plan) -> Answer
src/airport_agent/agent/sessions.py           SessionStore(directory)
src/airport_agent/agent/app.py                App, build_app(...)
tests/llm/{__init__,test_config,test_client}.py
tests/agent/{__init__,conftest,fake_llm,fake_analyst}.py
tests/agent/test_{registry,data_tools,analysis_tools,planner,specialist_loader,specialist_runner,tables,synthesis,concierge,sessions,app}.py
tests/golden/{__init__,test_sample_questions,test_live_smoke}.py
```

**Interfaces other workstreams rely on (Phase 3 / UI plan 2d):**
```python
# airport_agent.agent
class SessionStore:
    def __init__(self, directory: Path) -> None
    def list(self) -> list[SessionState]                 # newest first
    def new(self, title: str = "New chat") -> SessionState  # persisted immediately
    def load(self, session_id: str) -> SessionState      # KeyError if unknown
    def save(self, state: SessionState) -> None
    def delete(self, session_id: str) -> None
    def rename(self, session_id: str, title: str) -> SessionState
class App:
    data: DataService
    sessions: SessionStore
    def answer(self, message: str, state: SessionState, *, defaults: dict[str, str] | None = None,
               on_plan: Callable[[Plan], None] | None = None) -> Answer   # mutates + saves state; raises LLMError loudly
    def provider_status(self) -> list[dict[str, str]]     # [{"name","model","status","detail"}]
    def sample_questions(self) -> list[str]               # the four assignment questions
def build_app(data_service: DataService | None = None, analyst: DeterministicAnalyst | None = None,
              llm: LLMClient | None = None, sessions_dir: Path | None = None) -> App
# defaults keys the UI may pass: "horizon" (12m|3y|5y|10y), "scoring_preset", "peer_group" (hub_class|region|all)
```
Lazy defaults inside `build_app` (Phase 3 wiring; names agreed with plans 2a/2b): `airport_agent.data.DuckDBDataService()`, `airport_agent.scoring.Analyst(data)`, `airport_agent.llm.LiteLLMClient()`.

---

### Task 1: LLM config + `providers.yaml`

**Files:** Create `config/providers.yaml`, `src/airport_agent/llm/config.py`, `src/airport_agent/llm/jsonutil.py`, `src/airport_agent/llm/__init__.py`, `tests/llm/__init__.py`, `tests/llm/test_config.py`.

**Interfaces — Produces:** `ProviderConfig(name, model, api_key_env, rpm=10, max_retries=2, timeout_s=60)`, `LLMConfig(providers: list[ProviderConfig], default_temperature=0.2)`, `default_providers_path()`, `load_llm_config(path=None) -> LLMConfig` (raises `ValueError("no providers configured")` on empty), `parse_json_text(text) -> dict` (accepts raw JSON or fenced ```json … ```; raises `ValueError` with the first 200 chars on failure).

- [ ] **Step 1: providers.yaml**
```yaml
# Runtime LLM providers (LiteLLM model strings). Decision 2026-08-15: Gemini free tier ONLY for now.
# Add Groq / NVIDIA NIM later by appending entries; the first entry is primary, later ones are fallbacks.
providers:
  - name: gemini
    model: gemini/gemini-2.5-flash
    api_key_env: GEMINI_API_KEY
    rpm: 10
    max_retries: 2
    timeout_s: 60
default_temperature: 0.2
```
- [ ] **Step 2: failing tests** — `tests/llm/test_config.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.llm.config import default_providers_path, load_llm_config
from airport_agent.llm.jsonutil import parse_json_text


def test_default_config_is_gemini_only():
    cfg = load_llm_config()
    assert [p.name for p in cfg.providers] == ["gemini"]
    p = cfg.providers[0]
    assert p.model.startswith("gemini/") and p.api_key_env == "GEMINI_API_KEY" and p.rpm == 10
    assert cfg.default_temperature == 0.2
    assert default_providers_path().name == "providers.yaml"


def test_empty_providers_rejected(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("providers: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no providers"):
        load_llm_config(f)


def test_parse_json_text_plain_and_fenced():
    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text('```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}
    assert parse_json_text('text before {"a": 1} after') == {"a": 1}


def test_parse_json_text_error_mentions_text():
    with pytest.raises(ValueError, match="not JSON"):
        parse_json_text("nope")
```
- [ ] **Step 3: run** `uv run pytest tests/llm -q` → ModuleNotFoundError.
- [ ] **Step 4: implement**

`src/airport_agent/llm/config.py`:
```python
"""Provider configuration (config/providers.yaml). Model names never live in code."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    model: str
    api_key_env: str
    rpm: int = 10
    max_retries: int = 2
    timeout_s: int = 60


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    providers: list[ProviderConfig] = Field(default_factory=list)
    default_temperature: float = 0.2


def default_providers_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "providers.yaml"


def load_llm_config(path: Path | None = None) -> LLMConfig:
    raw = yaml.safe_load((path or default_providers_path()).read_text(encoding="utf-8")) or {}
    cfg = LLMConfig(**raw)
    if not cfg.providers:
        raise ValueError("no providers configured in providers.yaml")
    return cfg
```
`src/airport_agent/llm/jsonutil.py`:
```python
"""Tolerant JSON extraction for structured LLM outputs."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_text(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    m = _FENCE.search(text)
    if m:
        candidates.insert(0, m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"LLM output is not JSON: {text[:200]!r}")
```
`src/airport_agent/llm/__init__.py` (Task 2 adds `LiteLLMClient`):
```python
"""LLM layer: LiteLLM router behind the contracts.LLMClient port. Errors are loud (LLMError)."""
from __future__ import annotations

from airport_agent.llm.config import LLMConfig, ProviderConfig, default_providers_path, load_llm_config
from airport_agent.llm.jsonutil import parse_json_text

__all__ = ["LLMConfig", "ProviderConfig", "default_providers_path", "load_llm_config", "parse_json_text"]
```
- [ ] **Step 5: run, lint, commit** `git add config/providers.yaml src/airport_agent/llm tests/llm && git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(llm): provider config and JSON parsing utilities"`

---

### Task 2: `LiteLLMClient` (chat, tools, response schema, loud errors)

**Files:** Create `src/airport_agent/llm/client.py`, `tests/llm/test_client.py`; modify `llm/__init__.py` (export `LiteLLMClient`).

**Interfaces — Produces:**
```python
class LiteLLMClient:  # satisfies contracts.LLMClient
    def __init__(self, config: LLMConfig | None = None, env: Mapping[str, str] | None = None,
                 completion_fn: Callable[..., Any] | None = None) -> None
    provider_name: str                      # primary provider name ("gemini")
    def status(self) -> list[dict[str, str]]   # per provider: name, model, status ("configured"|"missing key"), detail
    def chat(self, messages, tools=None, response_schema=None, temperature=0.2) -> LLMResult
```
Behaviour: `__init__` calls `dotenv.load_dotenv()` (repo root `.env`, no override) unless `env` is given; keys read from `env or os.environ`. `completion_fn` defaults to a lazily built `litellm.Router(model_list=[...], num_retries=p.max_retries, timeout=p.timeout_s, fallbacks=[{first: [others]}] if len>1).completion`. `chat` kwargs: `model=primary.name, messages, temperature, tools (as given), tool_choice="auto" if tools, response_format={"type":"json_schema","json_schema":{"name":"response","schema":response_schema}} if response_schema`. Missing key for the primary → raise `LLMError(provider, None, "GEMINI_API_KEY not set")` at `chat` time (construction never raises). Any exception from completion → `LLMError(provider=primary.name, status=getattr(e, "status_code", None), detail=str(e)[:400])`. Response mapping: `choice = resp.choices[0]`, `text = choice.message.content or ""`, `tool_calls = [ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))]` (bad JSON → `{"_raw": arguments}`), `provider=primary.name`, `model=getattr(resp, "model", primary.model)`, tokens from `resp.usage.prompt_tokens/completion_tokens` when present.

- [ ] **Step 1: failing tests** — `tests/llm/test_client.py`:
```python
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
```
- [ ] **Step 2: run** → ModuleNotFoundError.
- [ ] **Step 3: implement** `src/airport_agent/llm/client.py`:
```python
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
```
Add `LiteLLMClient` to `llm/__init__.py` exports.
- [ ] **Step 4: run, lint, commit** `git commit -m "feat(llm): LiteLLMClient with loud LLMError mapping"`

---

### Task 3: Test doubles — `ScriptedLLM` and `FakeAnalyst`

**Files:** Create `tests/agent/__init__.py`, `tests/agent/fake_llm.py`, `tests/agent/fake_analyst.py`, `tests/agent/conftest.py`, `tests/agent/test_fakes.py`.

**Interfaces — Produces (tests only):**
```python
class ScriptedLLM:  # contracts.LLMClient
    def __init__(self, script: list[LLMResult | dict | str | Exception]): ...  # dict/str -> LLMResult(text=json/str)
    calls: list[dict]   # kwargs of every chat() call
    def chat(self, messages, tools=None, response_schema=None, temperature=0.2) -> LLMResult  # pops script; Exception entries are raised; empty script -> AssertionError("script exhausted")
class FakeAnalyst:  # contracts.DeterministicAnalyst over FakeDataService; deterministic canned math
    def __init__(self, data: DataService)
    rank/compare/diagnose/distance_bands/long_haul_share
```
`FakeAnalyst.rank`: targets = `req.airports` or `data.list_airports(req.filter)`; score = `load_factor*100` at `req.horizons[0]` (None→0); rows sorted; `pillar_contrib={"P1": score}`, `metric_contrib={"load_factor": score}`, coverage 1.0/0.0, low_confidence when None; `weights={"P1":1.0,"load_factor":1.0}`; `evidence` = all `Metric`s from `data.get_profile(iata,(h,))` with ids in `["load_factor","avg_dep_delay_min","taxi_out_p80_min","npias_capacity_label"]`; `percentiles={"load_factor": {iata: rank-based}}`; `curated_facts` from profiles; `explanation="fake rank"`; `caveats=["fake analyst"]`. `compare`: same rows + `comparison={m: {iata: value}}` for the four ids. `diagnose`: same as compare with `explanation="Signals of unmet demand at X: 2 of 3 present. ✔ delay ✔ npias ✘ lf"`. `distance_bands`/`long_haul_share`: pax = share of departures with seats>0 ≥1500 mi; freight = share of freight_lb; Metric id `longhaul_dep_share` with route table provenance.

- [ ] **Step 1: write** the two fakes exactly as specified (code is short; the implementer writes it) and `tests/agent/conftest.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import load_registry
from tests.agent.fake_analyst import FakeAnalyst
from tests.fakes import FakeDataService


@pytest.fixture
def fake_data():
    return FakeDataService()


@pytest.fixture
def fake_analyst(fake_data):
    return FakeAnalyst(fake_data)


@pytest.fixture(scope="session")
def specs():
    return load_registry()
```
`tests/agent/test_fakes.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest, DeterministicAnalyst, LLMClient, LLMError
from tests.agent.fake_llm import ScriptedLLM


def test_scripted_llm_pops_and_records():
    llm = ScriptedLLM([{"a": 1}, "plain", LLMError("gemini", 429, "quota")])
    assert isinstance(llm, LLMClient)
    assert llm.chat([{"role": "user", "content": "x"}]).text == '{"a": 1}'
    assert llm.chat([]).text == "plain"
    with pytest.raises(LLMError):
        llm.chat([])
    with pytest.raises(AssertionError, match="exhausted"):
        llm.chat([])
    assert len(llm.calls) == 4


def test_fake_analyst_reports_are_valid_and_carry_provenance(fake_analyst):
    assert isinstance(fake_analyst, DeterministicAnalyst)
    rep = fake_analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["12m"]))
    assert [r.rank for r in rep.rows] == [1, 2] and rep.evidence and all(m.vintage for m in rep.evidence)
    cmp_ = fake_analyst.compare(AnalysisRequest(question_type="compare", airports=["LAX", "SNA"], horizons=["12m"]))
    assert cmp_.comparison["avg_dep_delay_min"] == {"LAX": 12.9, "SNA": 13.9}
    assert fake_analyst.long_haul_share("ANC", freight=True).value > fake_analyst.long_haul_share("ANC").value
```
- [ ] **Step 2: run, commit** `git commit -m "test(agent): scripted LLM and fake analyst doubles"`

---

### Task 4: `ToolRegistry`

**Files:** Create `src/airport_agent/agent/tools/__init__.py`, `src/airport_agent/agent/tools/registry.py`, `tests/agent/test_registry.py`.

**Interfaces — Produces:**
```python
class ToolRegistry:
    def register(self, spec: ToolSpec) -> None            # duplicate name -> ValueError
    def get(self, name: str) -> ToolSpec                   # KeyError if unknown
    def names(self, engine: str | None = None) -> list[str]
    def for_engine(self, engine: str) -> list[ToolSpec]
    def openai_tools(self, engine: str) -> list[dict]      # [{"type": "function", "function": spec.json_schema()}]
    def call(self, name: str, args: dict, engine: str | None = None) -> dict
```
`call`: unknown tool → `{"error": "unknown tool 'x'; available: [...]", "provenance": [], "truncated": False}`; engine not allowed → error dict; args validated with `spec.params_model(**args)`; `pydantic.ValidationError` → `{"error": "invalid arguments: <compact errors>", ...}` (so the model self-corrects); `fn(params)` result gets `setdefault("provenance", [])`, `setdefault("truncated", False)`; `KeyError`/`ValueError` from fn → error dict with `f"{type(e).__name__}: {e}"`; `LLMError` propagates. Tool functions take the validated params model as their single argument.

- [ ] **Step 1: failing tests** — `tests/agent/test_registry.py`:
```python
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
```
- [ ] **Step 2: run** → ModuleNotFoundError. **Step 3: implement**:
```python
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
            return err("invalid arguments: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
        try:
            out = spec.fn(params)
        except LLMError:
            raise
        except (KeyError, ValueError, TypeError) as e:
            return err(f"{type(e).__name__}: {e}")
        out.setdefault("provenance", [])
        out.setdefault("truncated", False)
        return out
```
- [ ] **Step 4: run, lint, commit** `git commit -m "feat(agent): ToolRegistry with engine subsets and validated calls"`

---

### Task 5: Data tools + analysis tools

**Files:** Create `src/airport_agent/agent/tools/data_tools.py`, `src/airport_agent/agent/tools/analysis_tools.py`, `tests/agent/test_data_tools.py`, `tests/agent/test_analysis_tools.py`.

**Interfaces — Produces:** `build_data_tools(data: DataService, analyst: DeterministicAnalyst) -> list[ToolSpec]`, `build_analysis_tools(analyst) -> list[ToolSpec]`, `build_registry(data, analyst) -> ToolRegistry` (registers both lists), and `def prov(vintages_or_metrics) -> list[dict]` helper returning unique `[{"source_id","vintage"}]`.

Tool table (name · args model fields · engines · result keys):
| tool | args | engines | result |
|---|---|---|---|
| `find_airports` | `states: list[str]=[]`, `faa_regions: list[str]=[]`, `iatas: list[str]=[]`, `hub_sizes: list[HubSize]=[]`, `name_contains: str|None=None`, `limit: int=50 (1..600)` | concierge, expansion_analyst, market_analyst, general_analyst | `airports: [AirportRef dumps]`, `count`, `truncated = count == limit` |
| `get_profile` | `iata: str`, `horizons: list[Horizon]=["12m","5y"]` | all five | `AirportProfile.model_dump()` + `provenance` from `vintages` |
| `get_route_stats` | `iata`, `horizon: Horizon="12m"`, `top_n: int=10`, `international: bool|None=None`, `threshold_mi: float=1500` | concierge, capacity_analyst, market_analyst, general_analyst | `iata`, `distance_bands: {"passenger": {...}, "freight": {...}}`, `long_haul_share: {"passenger": Metric dump, "freight": Metric dump}`, `top_routes: [RouteRow dumps]` (top_n by departures, filtered by `international`), `convention: "long-haul = routes >= {threshold} mi (bands short<500, medium 500-1500, long 1500-3000, ultra>3000); passenger share weights departures with seats>0, freight share weights freight lb"`, `provenance: [{source_id, vintage}]` from the RouteTable, `truncated: routes.truncated` |
| `get_live_status` | `iata` | concierge, capacity_analyst, general_analyst | `LiveStatus.model_dump()` + provenance from `source_ids` with `vintage=fetched_at` |
| `explain_metric` | `metric_id` | all five | `MetricSpec.model_dump()` + `pillar_name` (KeyError → error dict via registry) |
| `get_metric_series` | `iata`, `metric_id` | concierge, expansion_analyst, market_analyst, general_analyst | `series: [Metric dumps]`, `provenance` |
| `list_sources` | — (empty model) | concierge, general_analyst | `sources: [SourceVintage dumps]` |
| `score_airports` | `airports: list[str]|None=None`, `states/faa_regions/hub_sizes` lists, `limit: int=50`, `horizon: Horizon="5y"`, `scoring_preset: str|None=None`, `focus_metrics: list[str]|None=None`, `peer_group: PeerGroup|None=None` | concierge, expansion_analyst, general_analyst | `DeterministicReport.model_dump()` + `provenance` from evidence |
| `compare_airports` | `airports: list[str]` (min 1), `horizon="12m"`, `focus_metrics`, `scoring_preset`, `peer_group` | concierge, capacity_analyst, market_analyst, general_analyst | report dump + provenance |
| `diagnose_unmet_demand` | `airports: list[str]` (min 1), `horizon="12m"`, `peer_group` | concierge, capacity_analyst, general_analyst | report dump + provenance |
Descriptions must state limits (e.g. "top_n ≤ 50", "returns at most `limit` airports; truncated flag set when the limit was hit"). Analysis tools build `AnalysisRequest(question_type=..., airports=..., filter=AirportFilter(...) if no airports, horizons=[horizon], scoring_preset, focus_metrics, peer_group)` and call the analyst method.

- [ ] **Step 1: failing tests** — `tests/agent/test_data_tools.py`:
```python
from __future__ import annotations

from airport_agent.agent.tools.data_tools import build_data_tools, build_registry


def test_all_tools_registered_with_engines(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    assert set(reg.names()) == {"find_airports", "get_profile", "get_route_stats", "get_live_status", "explain_metric",
                                "get_metric_series", "list_sources", "score_airports", "compare_airports",
                                "diagnose_unmet_demand"}
    assert set(reg.names("capacity_analyst")) == {"get_profile", "get_route_stats", "get_live_status", "explain_metric",
                                                  "compare_airports", "diagnose_unmet_demand"}
    assert set(reg.names("expansion_analyst")) == {"find_airports", "get_profile", "explain_metric", "get_metric_series",
                                                   "score_airports"}
    assert set(reg.names("market_analyst")) == {"find_airports", "get_profile", "get_route_stats", "explain_metric",
                                                "get_metric_series", "compare_airports"}
    assert set(reg.names("general_analyst")) == set(reg.names())
    for spec in build_data_tools(fake_data, fake_analyst):
        assert spec.description and spec.json_schema()["parameters"]["type"] == "object"


def test_find_airports_new_england(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("find_airports", {"faa_regions": ["ane"]}, engine="concierge")
    assert {a["iata"] for a in out["airports"]} == {"BOS", "BDL", "PVD", "MHT", "PWM"} and out["truncated"] is False


def test_get_route_stats_anchorage(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("get_route_stats", {"iata": "anc", "top_n": 3}, engine="concierge")
    assert out["long_haul_share"]["freight"]["value"] > out["long_haul_share"]["passenger"]["value"]
    assert set(out["distance_bands"]["passenger"]) == {"short", "medium", "long", "ultra"}
    assert len(out["top_routes"]) == 3 and out["provenance"] == [{"source_id": "bts_t100", "vintage": "2026-04"}]
    assert "1500" in out["convention"]


def test_profile_series_live_explain_sources(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    prof = reg.call("get_profile", {"iata": "SFO", "horizons": ["12m"]}, engine="capacity_analyst")
    assert prof["ref"]["iata"] == "SFO" and prof["provenance"] and "12m" in prof["metrics"]
    ser = reg.call("get_metric_series", {"iata": "BOS", "metric_id": "load_factor"}, engine="concierge")
    assert len(ser["series"]) > 5 and ser["provenance"]
    live = reg.call("get_live_status", {"iata": "SFO"}, engine="concierge")
    assert live["delay_programs"] == ["Ground Delay Program"] and live["provenance"]
    ex = reg.call("explain_metric", {"metric_id": "load_factor"}, engine="market_analyst")
    assert ex["pillar_name"] == "Demand Pressure" and ex["formula"] == "passengers / seats"
    assert "KeyError" in reg.call("explain_metric", {"metric_id": "nope"}, engine="concierge")["error"]
    assert reg.call("list_sources", {}, engine="concierge")["sources"]


def test_unknown_airport_is_error_dict_not_exception(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("get_profile", {"iata": "ZZZ"}, engine="concierge")
    assert "KeyError" in out["error"]
```
`tests/agent/test_analysis_tools.py`:
```python
from __future__ import annotations

from airport_agent.agent.tools.data_tools import build_registry


def test_score_airports_by_region(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call(
        "score_airports", {"faa_regions": ["ANE"], "horizon": "5y", "scoring_preset": "terminal_expansion"}, engine="concierge")
    assert out["report_type"] == "deterministic" and out["question_type"] == "rank"
    assert {r["ref"]["iata"] for r in out["rows"]} == {"BOS", "BDL", "PVD", "MHT", "PWM"}
    assert out["provenance"] and all(set(p) == {"source_id", "vintage"} for p in out["provenance"])


def test_compare_and_diagnose(fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    cmp_ = reg.call("compare_airports", {"airports": ["LAX", "SNA"], "horizon": "12m"}, engine="capacity_analyst")
    assert cmp_["question_type"] == "compare" and cmp_["comparison"]["avg_dep_delay_min"]["LAX"] == 12.9
    dia = reg.call("diagnose_unmet_demand", {"airports": ["SFO"]}, engine="capacity_analyst")
    assert dia["question_type"] == "diagnose" and dia["explanation"].startswith("Signals of unmet demand")


def test_score_requires_airports_or_filter(fake_data, fake_analyst):
    out = build_registry(fake_data, fake_analyst).call("score_airports", {}, engine="concierge")
    assert "error" in out
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement** `data_tools.py` (args models as pydantic `BaseModel`s with `Field` descriptions and bounds; one closure per tool; `build_registry` composes) and `analysis_tools.py` (three tools; `score_airports` with neither airports nor filter fields → `AnalysisRequest` validator raises `ValueError` → registry returns error dict). Use `analyst.distance_bands`/`analyst.long_haul_share` inside `get_route_stats` (both variants), and `data.get_routes(iata, horizon, top_n=top_n, international=international)` for `top_routes`. `prov()` de-duplicates by `(source_id, vintage)` preserving order.
- [ ] **Step 4: run, lint, commit** `git commit -m "feat(agent): data and analysis tools over DataService and DeterministicAnalyst"`

---

### Task 6: Planner (Plan structured output → `Plan` + `AnalysisRequest`)

**Files:** Create `src/airport_agent/agent/planner.py`, `tests/agent/test_planner.py`.

**Interfaces — Produces:**
```python
PLAN_SCHEMA: dict   # provider-portable JSON schema (only type/properties/required/items/enum/description; no anyOf/$ref/additionalProperties/nullable)
class PlannedToolCall(BaseModel): tool: str; args_json: str = "{}"
class PlanFilters(BaseModel):   # validated form of Plan.filters
    question_type: QuestionType | None = None; airports: list[str] = []; states: list[str] = []; faa_regions: list[str] = []
    hub_sizes: list[HubSize] = []; horizons: list[Horizon] = []; scoring_preset: str | None = None
    focus_metrics: list[str] = []; hint: str = ""; peer_group: PeerGroup | None = None
    tool_calls: list[PlannedToolCall] = []
    def args_for(self, tool: str) -> dict            # parses args_json; bad JSON -> {}
SAMPLE_QUESTIONS: list[str]  # the four assignment questions, verbatim
class Planner:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, specs: list[MetricSpec], presets: list[str],
                 specialists: list[str] = ["expansion_analyst","capacity_analyst","market_analyst","general_analyst"])
    def system_prompt(self, defaults: dict[str, str] | None) -> str
    def plan(self, message: str, state: SessionState, defaults: dict[str, str] | None = None) -> tuple[Plan, PlanFilters]
    def to_analysis_request(self, plan: Plan, filters: PlanFilters, defaults: dict[str, str] | None) -> AnalysisRequest
    @staticmethod
    def plan_line(plan: Plan, filters: PlanFilters) -> str
```
LLM JSON shape (PLAN_SCHEMA): `{"intent": enum[informational,analytical,followup,clarify], "engines": [enum[tools,deterministic,specialist:expansion_analyst,specialist:capacity_analyst,specialist:market_analyst,specialist:general_analyst]], "question_type": enum[rank,compare,diagnose,custom,none], "airports": [str], "states": [str], "faa_regions": [str], "hub_sizes": [enum], "horizons": [enum 12m,3y,5y,10y], "scoring_preset": enum[balanced,terminal_expansion,congestion_relief,market_entry,none], "focus_metrics": [str], "peer_group": enum[hub_class,region,all,none], "hint": str, "tool_calls": [{"tool": str, "args_json": str}], "presentation_notes": str}` (all keys required; "none"/[]/"" mean unset). Mapping → `Plan(intent, engines, filters=PlanFilters.model_dump(), tools_to_call=[tc.tool ...], specialist=<name from engines "specialist:x" or None>, presentation_notes)`. `Plan.engines` for a `clarify` intent = `[]`.
System prompt content (assembled from live objects, so it never drifts): role + question classes (design 03 diagram in words); intent definitions; engine rules (analytical ⇒ `deterministic` + exactly one specialist unless the user asks for formula only; informational ⇒ `tools` with `tool_calls`; followup ⇒ prefer answering from the previous reports — set `engines=[]` and `tool_calls=[]` when the last reports already contain what is needed, otherwise re-dispatch; clarify only when the question is unanswerable without one detail); tools list `name — description` for engine `concierge`; presets list; specialist roster with when-to-use + hint limits (200/600); metric ids grouped by pillar with names; conventions (long-haul ≥1,500 mi; spill model; percentiles within hub class; horizon default 5y for rank/compare of investments, 12m for congestion compare/diagnose/informational); the sample routing table from design 03 (4 rows); user defaults if any (`horizon`, `scoring_preset`, `peer_group` — "use unless the user says otherwise"); session context: last airports/filters/preset and the last user/assistant turns (last 6 messages, content truncated to 400 chars); "Output ONLY the JSON object".
`to_analysis_request`: `question_type = filters.question_type or ("compare" if len(airports)>=2 else "diagnose" if question mentions demand … )` — NO: keep deterministic: `question_type = filters.question_type or "custom"`; `custom` requires `general_analyst`, so if specialist is not general_analyst and question_type is None → `"rank"` when no explicit airports else `"compare"`; airports = filters.airports or None; filter = `AirportFilter(states, faa_regions, hub_sizes, limit=50)` when no airports and any filter list is non-empty (else None → validator raises `ValueError` which the Concierge turns into a clarify answer); horizons = filters.horizons or [defaults horizon] or default by question type (rank/compare/custom→"5y", diagnose→"12m"; compare with preset congestion_relief → "12m"); scoring_preset = filters.scoring_preset or defaults; peer_group = filters.peer_group or defaults; focus_metrics or None; hint; specialist=plan.specialist. `plan_line`: `"How I'm approaching this: {intent} · {question_type or 'lookup'} · {targets} · horizon {h or '-'} · preset {p or '-'} · engines: {', '.join(engines) or 'none'}"` where targets = airports joined or filter summary (`"region ANE"`, `"states MA,CT"`) or `"—"`.

- [ ] **Step 1: failing tests** — `tests/agent/test_planner.py`:
```python
from __future__ import annotations

import json

import pytest

from airport_agent.agent.planner import PLAN_SCHEMA, SAMPLE_QUESTIONS, PlanFilters, Planner
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import Plan, SessionState
from tests.agent.fake_llm import ScriptedLLM

PRESETS = ["balanced", "terminal_expansion", "congestion_relief", "market_entry"]


def _plan_json(**over):
    base = {"intent": "analytical", "engines": ["deterministic", "specialist:expansion_analyst"], "question_type": "rank",
            "airports": [], "states": [], "faa_regions": ["ANE"], "hub_sizes": [], "horizons": ["5y"],
            "scoring_preset": "terminal_expansion", "focus_metrics": [], "peer_group": "none", "hint": "terminal focus",
            "tool_calls": [], "presentation_notes": "rank table first"}
    base.update(over)
    return base


def _planner(script, fake_data, fake_analyst, specs):
    reg = build_registry(fake_data, fake_analyst)
    return Planner(ScriptedLLM(script), reg, specs, PRESETS)


def test_schema_is_portable():
    dumped = json.dumps(PLAN_SCHEMA)
    for bad in ("anyOf", "$ref", "additionalProperties", "nullable", "oneOf"):
        assert bad not in dumped
    assert set(PLAN_SCHEMA["required"]) == set(PLAN_SCHEMA["properties"])


def test_sample_questions_verbatim():
    assert SAMPLE_QUESTIONS[0].startswith("Which airports in New England") and len(SAMPLE_QUESTIONS) == 4


def test_plan_analytical_rank(fake_data, fake_analyst, specs):
    p = _planner([_plan_json()], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[0], SessionState(session_id="s", title="t"))
    assert isinstance(plan, Plan) and plan.intent == "analytical" and plan.specialist == "expansion_analyst"
    assert f.faa_regions == ["ANE"] and plan.filters["faa_regions"] == ["ANE"]
    req = p.to_analysis_request(plan, f, None)
    assert req.question_type == "rank" and req.filter.faa_regions == ["ANE"] and req.horizons == ["5y"]
    assert req.scoring_preset == "terminal_expansion" and req.specialist == "expansion_analyst" and req.airports is None
    line = Planner.plan_line(plan, f)
    assert line.startswith("How I'm approaching this: analytical · rank · region ANE · horizon 5y")
    # the LLM call carried the schema and the system prompt mentions tools, presets, metric ids, samples
    call = p.llm.calls[0]
    assert call["response_schema"] == PLAN_SCHEMA
    sysmsg = call["messages"][0]["content"]
    for token in ("find_airports", "terminal_expansion", "load_factor", "capacity_analyst", "1,500", "Anchorage"):
        assert token in sysmsg


def test_plan_informational_with_tool_calls(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[], horizons=[],
                    scoring_preset="none", tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[2], SessionState(session_id="s", title="t"))
    assert plan.tools_to_call == ["get_route_stats"] and f.args_for("get_route_stats") == {"iata": "ANC"}
    assert plan.specialist is None and f.question_type is None
    assert "lookup" in Planner.plan_line(plan, f)


def test_defaults_and_session_context_reach_prompt_and_request(fake_data, fake_analyst, specs):
    js = _plan_json(horizons=[], scoring_preset="none", peer_group="none")
    p = _planner([js], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t", last_airports=["BOS"], last_preset="balanced")
    plan, f = p.plan("and at 10 years?", state, defaults={"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"})
    req = p.to_analysis_request(plan, f, {"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"})
    assert req.horizons == ["10y"] and req.scoring_preset == "market_entry" and req.peer_group == "all"
    sysmsg = p.llm.calls[0]["messages"][0]["content"]
    assert "10y" in sysmsg and "BOS" in sysmsg


def test_custom_question_type_only_with_general_analyst(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="none", engines=["deterministic", "specialist:general_analyst"], airports=["DEN"],
                    faa_regions=[])
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan("is DEN cargo growth sustainable?", SessionState(session_id="s", title="t"))
    req = p.to_analysis_request(plan, f, None)
    assert req.question_type == "custom" and req.specialist == "general_analyst" and req.airports == ["DEN"]


def test_diagnose_default_horizon_is_12m(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="diagnose", engines=["deterministic", "specialist:capacity_analyst"], airports=["SFO"],
                    faa_regions=[], horizons=[], scoring_preset="none")
    p = _planner([js], fake_data, fake_analyst, specs)
    plan, f = p.plan(SAMPLE_QUESTIONS[3], SessionState(session_id="s", title="t"))
    assert p.to_analysis_request(plan, f, None).horizons == ["12m"]


def test_bad_llm_json_raises_value_error(fake_data, fake_analyst, specs):
    p = _planner(["not json at all"], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError):
        p.plan("x", SessionState(session_id="s", title="t"))


def test_plan_filters_args_for_bad_json_is_empty():
    f = PlanFilters(tool_calls=[{"tool": "x", "args_json": "{oops"}])
    assert f.args_for("x") == {} and f.args_for("y") == {}
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement** per the interface (keep `Planner.llm` public for tests). Note: `plan()` calls `self.llm.chat(messages=[system, user], response_schema=PLAN_SCHEMA, temperature=0.1)` and parses with `parse_json_text`; unknown enum strings raise `ValueError` (pydantic) — the Concierge converts `ValueError` from planning into a clarify answer (Task 9); `LLMError` propagates.
- [ ] **Step 4: run, lint, commit** `git commit -m "feat(agent): Planner with portable Plan schema and AnalysisRequest mapping"`

---

### Task 7: Specialist configs + loader

**Files:** Create `config/specialists/{expansion_analyst,capacity_analyst,market_analyst,general_analyst}.md`, `src/airport_agent/agent/specialists/__init__.py`, `src/airport_agent/agent/specialists/loader.py`, `tests/agent/test_specialist_loader.py`.

**Interfaces — Produces:** `SpecialistConfig(name, allowed_tools: list[str], default_preset: str | None, max_turns: int = 2, metric_pillars: list[str], metric_ids: list[str], body: str)`; `load_specialist(name, specs: list[MetricSpec], config_dir: Path | None = None) -> SpecialistConfig`; `SpecialistConfig.system_prompt(specs) -> str` = body with `{METRIC_SLICE}` replaced by a markdown table of the specialist's metrics (`id | name | definition | formula | unit | direction | tier | sources | caveats`) and `{OUTPUT_SCHEMA}` replaced by a description of the final JSON (Task 8's `SPECIALIST_SCHEMA`), and `{ALLOWED_TOOLS}` by the tool names. File format: YAML front matter between `---` lines then markdown body.

Front matter per design 03 roster:
- `expansion_analyst`: allowed_tools `[score_airports, get_profile, find_airports, explain_metric, get_metric_series]`, default_preset `terminal_expansion`, metric_pillars `[P1,P2,P3,P4,P5]`, max_turns 2. Body: composite "where to invest" lens; must use `score_airports` numbers as the formula view; separate "data says" from "my judgement"; caveats: tier-B coverage, hub-class peer group, forecast optimism.
- `capacity_analyst`: `[compare_airports, diagnose_unmet_demand, get_profile, get_live_status, get_route_stats, explain_metric]`, default `congestion_relief`, pillars `[P2]` + metric_ids `[load_factor, spill_proxy, seats_per_dep_trend, taf_vs_actual_gap]`. Caveats: spill model not LF cutoff; NPIAS circularity; declared capacities 2014–19; SNA legal cap; OTP undercounts ANC/cargo.
- `market_analyst`: `[get_route_stats, get_profile, compare_airports, find_airports, explain_metric, get_metric_series]`, default `market_entry`, pillars `[P3,P4,P5]`. Caveats: CBSA≠catchment; Form 127 unaudited; long-haul convention; pax vs freight.
- `general_analyst`: all tools, default_preset none (use request's or balanced), all pillars, max_turns 3, body adds "state which specialist lens you adopted" and honours `extended.requested_sections`/`extended.metrics`.
Every body ends with the same rules block: cite evidence by `metric_id` + `iata` in `evidence_refs`; never restate a number you did not receive from a tool or the deterministic report; state agreement/disagreement with the deterministic view explicitly; list assumptions and caveats; confidence 0–1.

- [ ] **Step 1: failing tests** — `tests/agent/test_specialist_loader.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.agent.specialists.loader import load_specialist

NAMES = ["expansion_analyst", "capacity_analyst", "market_analyst", "general_analyst"]


@pytest.mark.parametrize("name", NAMES)
def test_configs_load_and_render(name, specs):
    cfg = load_specialist(name, specs)
    assert cfg.name == name and cfg.allowed_tools and cfg.max_turns >= 1
    prompt = cfg.system_prompt(specs)
    assert "{METRIC_SLICE}" not in prompt and "{OUTPUT_SCHEMA}" not in prompt and "{ALLOWED_TOOLS}" not in prompt
    assert "evidence_refs" in prompt and "disagree" in prompt.lower()


def test_capacity_slice_is_p2_plus_absorption(specs):
    cfg = load_specialist("capacity_analyst", specs)
    p = cfg.system_prompt(specs)
    assert "taxi_out_p80_min" in p and "spill_proxy" in p and "load_factor" in p
    assert "msa_gdp_per_capita" not in p
    assert "diagnose_unmet_demand" in cfg.allowed_tools and cfg.default_preset == "congestion_relief"


def test_general_has_all_tools_and_600_hint_note(specs):
    cfg = load_specialist("general_analyst", specs)
    assert len(cfg.allowed_tools) >= 10 and "600" in cfg.system_prompt(specs)


def test_unknown_specialist(specs):
    with pytest.raises(FileNotFoundError):
        load_specialist("nope", specs)
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement** the four `.md` files and `loader.py` (parse front matter with `yaml.safe_load`, `pydantic` model, render slice table from `MetricSpec`s where `spec.pillar in metric_pillars or spec.id in metric_ids`).
- [ ] **Step 4: run, lint, commit** `git commit -m "feat(agent): specialist configs (4) and loader"`

---

### Task 8: Specialist runner (tool loop + structured report, evidence resolved by code)

**Files:** Create `src/airport_agent/agent/specialists/runner.py`, `tests/agent/test_specialist_runner.py`.

**Interfaces — Produces:**
```python
SPECIALIST_SCHEMA: dict  # portable: {ranking:[{iata,rank,rationale,confidence}], narrative:str, evidence_refs:[{iata,metric_id}], agreement:str, disagreements:[str], confidence:number, assumptions:[str], caveats:[str], lens:str}
MAX_TOOL_RESULT_CHARS = 6000
class SpecialistRunnerImpl:  # contracts.SpecialistRunner
    def __init__(self, llm: LLMClient, registry: ToolRegistry, specs: list[MetricSpec], config_dir: Path | None = None)
    def run(self, req: AnalysisRequest, deterministic: DeterministicReport | None) -> SpecialistReport
```
Algorithm: `name = req.specialist` (None → `ValueError`); `cfg = load_specialist(name, specs, config_dir)`; `req2, truncated = truncate_hint(req)`; evidence index `dict[tuple[str,str], Metric]` seeded from `deterministic.evidence` (key `(iata_of_metric, id)` — the report's evidence has no iata on the Metric! → seed by walking `deterministic.rows`/`comparison`? `Metric` has no iata. Therefore: seed with `deterministic.evidence` keyed by `id` only into a secondary index `by_metric_id: dict[str, list[Metric]]`, and index tool results precisely: `get_profile` results give `(iata, metric.id) → Metric` for every metric in `metrics[h]`; `score_airports/compare/diagnose` results give `by_metric_id`. Resolution of `evidence_refs[{iata, metric_id}]`: exact `(iata, metric_id)` hit first; else the first `by_metric_id[metric_id]` entry (report evidence is per requested airports; when the report covers exactly one airport this is exact, otherwise the caveat "evidence resolved by metric id" is added); no hit → dropped and caveat `"dropped unresolved evidence ref X/Y"`. Compact deterministic view for the prompt: `{"preset","horizon","peer_group","explanation","caveats","rows":[{"iata","score","rank","coverage","low_confidence","pillar_contrib"}],"comparison"}` (no evidence list — the model may call `get_profile`). Messages: system = `cfg.system_prompt(specs)`; user = `"AnalysisRequest:\n" + req2.model_dump_json() + "\n\nDeterministic view:\n" + json` (or "none"). Loop `for turn in range(cfg.max_turns)`: `res = llm.chat(messages, tools=registry.openai_tools(name))`; if no `tool_calls` → break; else append assistant message `{"role":"assistant","content": res.text or None, "tool_calls":[{"id","type":"function","function":{"name","arguments": json.dumps(args)}}]}` and, per call, `out = registry.call(name_of_tool, args, engine=name)`, index evidence, append `{"role":"tool","tool_call_id": id, "name": tool, "content": json.dumps(out)[:MAX_TOOL_RESULT_CHARS]}`. Final: `messages + [{"role":"user","content":"Produce the final report now as JSON matching the schema. Do not call tools."}]`, `llm.chat(..., response_schema=SPECIALIST_SCHEMA)`; parse; build `SpecialistReport(specialist=name, question_type=req.question_type, ranking=[RankedItem(...)] or None if empty, narrative, evidence=resolved, agreement=agreement or None, disagreements, confidence=clamp 0..1, assumptions, caveats + (["hint truncated to N chars"] if truncated) + resolution caveats + [f"lens: {lens}"] if lens, hint_truncated=truncated)`. Pydantic errors on the final JSON → `ValueError("specialist returned malformed report: …")` (propagates; the Concierge does not swallow it — design: loud). `LLMError` propagates.

- [ ] **Step 1: failing tests** — `tests/agent/test_specialist_runner.py`:
```python
from __future__ import annotations

import json

import pytest

from airport_agent.agent.specialists.runner import SPECIALIST_SCHEMA, SpecialistRunnerImpl
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import AnalysisRequest, LLMError, LLMResult, SpecialistRunner, ToolCall
from tests.agent.fake_llm import ScriptedLLM

FINAL = {"ranking": [{"iata": "SFO", "rank": 1, "rationale": "constrained", "confidence": 0.7}], "narrative": "SFO shows unmet demand.",
         "evidence_refs": [{"iata": "SFO", "metric_id": "load_factor"}, {"iata": "SFO", "metric_id": "nope_metric"}],
         "agreement": "agrees with the formula", "disagreements": ["formula underweights weather"], "confidence": 0.7,
         "assumptions": ["12m horizon"], "caveats": ["OTP undercounts"], "lens": "capacity"}


def _runner(script, fake_data, fake_analyst, specs):
    reg = build_registry(fake_data, fake_analyst)
    llm = ScriptedLLM(script)
    return SpecialistRunnerImpl(llm, reg, specs), llm, reg


def test_run_with_tool_loop_and_resolved_evidence(fake_data, fake_analyst, specs):
    tool_turn = LLMResult(text="", provider="fake", model="m",
                          tool_calls=[ToolCall(id="c1", name="get_profile", arguments={"iata": "SFO", "horizons": ["12m"]})])
    runner, llm, _ = _runner([tool_turn, LLMResult(text="done", provider="fake", model="m"), FINAL], fake_data, fake_analyst, specs)
    assert isinstance(runner, SpecialistRunner)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst",
                          hint="x" * 250)
    det = fake_analyst.diagnose(req)
    rep = runner.run(req, det)
    assert rep.specialist == "capacity_analyst" and rep.hint_truncated is True
    assert [m.id for m in rep.evidence] == ["load_factor"] and rep.evidence[0].source_id
    assert any("nope_metric" in c for c in rep.caveats) and any("hint truncated" in c for c in rep.caveats)
    assert rep.ranking[0].iata == "SFO" and rep.agreement and rep.disagreements
    # calls: 2 tool-loop turns + 1 final structured
    assert len(llm.calls) == 3 and llm.calls[2]["response_schema"] == SPECIALIST_SCHEMA
    assert llm.calls[0]["tools"] and {t["function"]["name"] for t in llm.calls[0]["tools"]} >= {"diagnose_unmet_demand"}
    tool_msg = next(m for m in llm.calls[1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["ref"]["iata"] == "SFO"


def test_run_without_tools_uses_report_evidence_by_metric_id(fake_data, fake_analyst, specs):
    runner, llm, _ = _runner([LLMResult(text="ok", provider="fake", model="m"), FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    rep = runner.run(req, fake_analyst.diagnose(req))
    assert rep.evidence and rep.evidence[0].id == "load_factor" and rep.hint_truncated is False
    assert len(llm.calls) == 2


def test_max_turns_bounds_calls(fake_data, fake_analyst, specs):
    tc = LLMResult(text="", provider="f", model="m", tool_calls=[ToolCall(id="1", name="get_live_status", arguments={"iata": "SFO"})])
    runner, llm, _ = _runner([tc, tc, tc, tc, FINAL], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"], specialist="capacity_analyst")
    runner.run(req, None)
    assert len(llm.calls) == 3  # max_turns=2 for capacity_analyst + final


def test_llm_error_propagates_and_malformed_final_is_value_error(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([LLMError("gemini", 429, "quota")], fake_data, fake_analyst, specs)
    req = AnalysisRequest(question_type="rank", airports=["BOS"], specialist="expansion_analyst")
    with pytest.raises(LLMError):
        runner.run(req, None)
    runner2, _, _ = _runner([LLMResult(text="ok", provider="f", model="m"), {"narrative": 5}], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="malformed"):
        runner2.run(req, None)


def test_missing_specialist_name(fake_data, fake_analyst, specs):
    runner, _, _ = _runner([], fake_data, fake_analyst, specs)
    with pytest.raises(ValueError, match="specialist"):
        runner.run(AnalysisRequest(question_type="rank", airports=["BOS"]), None)
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement** per algorithm. **Step 4: run, lint, commit** `git commit -m "feat(agent): specialist runner with bounded tool loop and code-resolved evidence"`

---

### Task 9: Tables + Synthesizer (code-enforced Answer)

**Files:** Create `src/airport_agent/agent/tables.py`, `src/airport_agent/agent/synthesis.py`, `tests/agent/test_tables.py`, `tests/agent/test_synthesis.py`.

**Interfaces — Produces:**
```python
# tables.py (pure)
def ranking_table(rep: DeterministicReport) -> Table            # "Ranking — preset X, horizon H (percentiles within P)"; cols rank, airport, name, hub, score, coverage, low_confidence, P1..P5
def evidence_table(rep: DeterministicReport, show: list[str], specs_by_id) -> tuple[Table, list[str]]  # rows for metric ids in `show` (order kept), cols metric, airport?, value, unit, horizon, period_end, source, vintage; returns hidden ids
def comparison_table(rep: DeterministicReport, specs_by_id) -> Table  # cols metric, name, unit + one col per iata (values) + "pct " per iata when percentiles present
def specialist_ranking_table(rep: SpecialistReport) -> Table | None
def tool_result_tables(tool: str, result: dict, specs_by_id) -> list[Table]  # get_route_stats -> Distance bands + Long-haul share; find_airports -> Airports; get_profile -> Metrics (per horizon); get_metric_series -> Series; get_live_status -> Live status; explain_metric -> Definition; list_sources -> Sources; score/compare/diagnose -> ranking/comparison tables above; error -> Table("Tool error", ["tool","error"])
def citations_from(metrics: list[Metric], provenance: list[dict]) -> list[Citation]   # unique (source_id, vintage)
# synthesis.py
SYNTHESIS_SCHEMA: dict  # {headline:str, show_metrics:[str], hidden_reason:str, analyst_summary:str, follow_ups:[str]}
class Synthesizer:
    def __init__(self, llm: LLMClient, specs: list[MetricSpec])
    def synthesize(self, *, message: str, plan: Plan, plan_line: str, req: AnalysisRequest | None,
                   deterministic: DeterministicReport | None, specialist: SpecialistReport | None,
                   tool_results: list[tuple[str, dict, dict]], trace: list[ToolCallTrace],
                   defaults: dict[str, str] | None) -> Answer
```
Evidence problem: `DeterministicReport.evidence` Metrics carry no iata. `evidence_table` therefore lists rows in report order and, when `rep.rows` has exactly one airport, labels it; otherwise the "airport" column is derived by pairing: evidence is produced per airport in `rows` order in plans 2b/FakeAnalyst (all metrics of airport 1, then airport 2, …) — do NOT rely on that; instead show `comparison`/`percentiles` (which are keyed by iata) as the per-airport tables and use `evidence_table` for provenance (metric, value, unit, horizon, period_end, source, vintage) without an airport column when >1 airport. Headline/summary come from the LLM; **every table cell comes from report objects**.
Synthesis LLM prompt: fixed structure explained; inputs = user message, plan notes, deterministic compact view (rows, explanation, caveats, comparison), specialist (narrative, agreement, disagreements, confidence, assumptions), tool results (compact, ≤ 2000 chars each), defaults; ask for JSON per `SYNTHESIS_SCHEMA`; rules: headline 1–2 sentences, no numbers that are not in the inputs, `show_metrics` ⊆ metric ids present, `follow_ups` 3 short questions. On `ValueError` from parsing → fallback headline = first sentence of `deterministic.explanation` or `"Results below."` and default follow-ups (this is *formatting* degradation, not reasoning; note it in `uncertainty_notes` as "synthesis text unavailable — showing raw report"). `LLMError` propagates.
Assembly: `evidence_tables` = ranking (if rows and question rank/custom) + comparison (if comparison) + evidence(show) + specialist ranking + tool tables; `analyst_view` = `analyst_summary` if non-empty else `specialist.narrative` (None without specialist); `agreement_line` = `f"Formula vs analyst: {agreement}. Disagreements: {'; '.join(d)}"` (or "none stated"); `assumptions` = [`f"Preset {p}"`, `f"Horizon {h}"`, `f"Peer group {pg}"` (from req/report), conventions from report caveats containing "convention" or "spill model", `"Tier B metrics only where curated data exists; tier C never scored"`, specialist assumptions, `f"UI defaults applied: …"`]; `uncertainty_notes` = remaining report caveats + `f"{k} of {n} airports low confidence"` + evidence quality flags (`code: message`, unique) + `f"Specialist confidence {c:.2f}"` + specialist caveats + hint-truncated + tool `truncated`/`error` notes + hidden metrics note; `citations` from evidence + tool provenance; `follow_ups` from LLM (≤4). Informational: `analyst_view=None`, `agreement_line=None`.

- [ ] **Step 1: failing tests** — `tests/agent/test_tables.py` (ranking table has one row per report row and P1..P5 columns; comparison table has a column per iata and values equal `rep.comparison`; `tool_result_tables("get_route_stats", …)` returns 2 tables with band shares equal to the dict; `citations_from` dedups) and `tests/agent/test_synthesis.py`:
```python
from __future__ import annotations

from airport_agent.agent.planner import PlanFilters
from airport_agent.agent.synthesis import SYNTHESIS_SCHEMA, Synthesizer
from airport_agent.contracts import AnalysisRequest, Answer, LLMResult, Plan, RankedItem, SpecialistReport
from tests.agent.fake_llm import ScriptedLLM

SYN = {"headline": "SFO and JFK lead on congestion.", "show_metrics": ["load_factor"], "hidden_reason": "delay metrics collapsed",
       "analyst_summary": "", "follow_ups": ["Compare at 5y?", "Show taxi-out?", "Add DEN?"]}


def _plan():
    return Plan(intent="analytical", engines=["deterministic", "specialist:expansion_analyst"], filters=PlanFilters().model_dump(),
                tools_to_call=[], specialist="expansion_analyst", presentation_notes="")


def test_synthesize_analytical_structure_and_no_altered_numbers(fake_analyst, specs):
    req = AnalysisRequest(question_type="rank", airports=["SFO", "JFK", "BOS"], horizons=["12m"], specialist="expansion_analyst")
    det = fake_analyst.rank(req)
    spec = SpecialistReport(specialist="expansion_analyst", question_type="rank", ranking=[RankedItem(iata="SFO", rank=1, rationale="r", confidence=0.6)],
                            narrative="Narrative.", evidence=det.evidence[:1], agreement="agrees", disagreements=["weather"],
                            confidence=0.6, assumptions=["a1"], caveats=["c1"], hint_truncated=False)
    llm = ScriptedLLM([SYN])
    ans = Synthesizer(llm, specs).synthesize(message="q", plan=_plan(), plan_line="How I'm approaching this: …", req=req,
                                             deterministic=det, specialist=spec, tool_results=[], trace=[], defaults=None)
    assert isinstance(ans, Answer) and ans.headline == SYN["headline"] and ans.plan_line.startswith("How I'm")
    titles = [t.title for t in ans.evidence_tables]
    assert any(t.startswith("Ranking") for t in titles) and any(t.startswith("Evidence") for t in titles)
    rank_tbl = next(t for t in ans.evidence_tables if t.title.startswith("Ranking"))
    scores = {row[rank_tbl.columns.index("airport")]: row[rank_tbl.columns.index("score")] for row in rank_tbl.rows}
    assert scores == {r.ref.iata: r.score for r in det.rows}  # numbers verbatim from the report
    assert ans.analyst_view == "Narrative." and "agrees" in ans.agreement_line and "weather" in ans.agreement_line
    assert any(a.startswith("Preset") for a in ans.assumptions) and any(a.startswith("Horizon 12m") for a in ans.assumptions)
    assert "a1" in ans.assumptions and any("confidence 0.60" in u for u in ans.uncertainty_notes)
    assert ans.citations and all(c.source_id and c.vintage for c in ans.citations)
    assert ans.follow_ups == SYN["follow_ups"]
    assert any("delay metrics collapsed" in u for u in ans.uncertainty_notes)
    assert llm.calls[0]["response_schema"] == SYNTHESIS_SCHEMA


def test_synthesize_informational_from_tool_results(fake_analyst, fake_data, specs):
    from airport_agent.agent.tools.data_tools import build_registry
    out = build_registry(fake_data, fake_analyst).call("get_route_stats", {"iata": "ANC"}, engine="concierge")
    plan = Plan(intent="informational", engines=["tools"], filters={}, tools_to_call=["get_route_stats"], specialist=None, presentation_notes="")
    ans = Synthesizer(ScriptedLLM([{**SYN, "show_metrics": []}]), specs).synthesize(
        message="q", plan=plan, plan_line="pl", req=None, deterministic=None, specialist=None,
        tool_results=[("get_route_stats", {"iata": "ANC"}, out)], trace=[], defaults=None)
    assert ans.analyst_view is None and ans.agreement_line is None
    assert any(t.title.startswith("Distance bands") for t in ans.evidence_tables)
    assert ans.citations[0].source_id == "bts_t100" and any("1,500" in a or "1500" in a for a in ans.assumptions)


def test_bad_synthesis_json_falls_back_to_report_text_and_notes_it(fake_analyst, specs):
    req = AnalysisRequest(question_type="rank", airports=["SFO", "JFK"], horizons=["12m"])
    det = fake_analyst.rank(req)
    ans = Synthesizer(ScriptedLLM([LLMResult(text="garbage", provider="f", model="m")]), specs).synthesize(
        message="q", plan=_plan(), plan_line="pl", req=req, deterministic=det, specialist=None, tool_results=[], trace=[], defaults=None)
    assert ans.headline and any("synthesis text unavailable" in u for u in ans.uncertainty_notes)
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement** `tables.py` and `synthesis.py` per interface. **Step 4: run, lint, commit** `git commit -m "feat(agent): code-built tables and Synthesizer (structure + agency)"`

---

### Task 10: Concierge + sessions

**Files:** Create `src/airport_agent/agent/concierge.py`, `src/airport_agent/agent/sessions.py`, `tests/agent/test_concierge.py`, `tests/agent/test_sessions.py`.

**Interfaces — Produces:**
```python
class Concierge:
    def __init__(self, *, llm: LLMClient, registry: ToolRegistry, analyst: DeterministicAnalyst, specialists: SpecialistRunner,
                 planner: Planner, synthesizer: Synthesizer)
    provider_name: str   # llm.provider_name if present else "llm"
    def answer(self, message: str, state: SessionState, *, defaults: dict[str, str] | None = None,
               on_plan: Callable[[Plan], None] | None = None) -> Answer
class SessionStore: ...  # as in the interfaces block at the top
```
`answer` algorithm:
1. `plan, filters = planner.plan(message, state, defaults)`; on `ValueError` (unparseable plan) → build a `clarify` Plan (`intent="clarify"`, engines `[]`) with `presentation_notes="I couldn't determine what to analyse. Which airports or region, and which horizon (12m/3y/5y/10y)?"`.
2. `plan_line = Planner.plan_line(plan, filters)`; call `on_plan(plan)` if given.
3. `clarify` → `Answer(plan, plan_line, headline=plan.presentation_notes or default question, evidence_tables=[], analyst_view=None, agreement_line=None, assumptions=[], uncertainty_notes=[], citations=[], follow_ups=[], tool_trace=[])` (no further LLM call).
4. Tools: for each `tc in filters.tool_calls` (or names in `plan.tools_to_call` with `{}` args when `tool_calls` is empty): time it, `out = registry.call(tc.tool, args, engine="concierge")`, `trace.append(ToolCallTrace(tool, args, rows=_rows(out), provider=None, latency_ms, note=out.get("error")))`, `tool_results.append((tool, args, out))`. `_rows(out)` = length of the first list value among keys `rows, airports, top_routes, series, sources` else None.
5. Engines: `needs_req = "deterministic" in engines or plan.specialist`. If needs_req: `req = planner.to_analysis_request(plan, filters, defaults)`; `ValueError` (no airports/filter) → clarify Answer as in 3 with the error text. If `"deterministic" in engines`: method = `{"rank": rank, "compare": compare, "diagnose": diagnose}` by `req.question_type`, `custom` → `compare` if `req.airports` else `rank`; `det = method(req)`; trace `ToolCallTrace(tool=f"deterministic:{name}", args=req.model_dump(exclude_none=True), rows=len(det.rows), provider=None, latency_ms)`. `ValueError` from the analyst (unknown preset, empty filter) → clarify Answer with the message. If `plan.specialist`: `spec = specialists.run(req, det)`; trace `tool=f"specialist:{name}"`, `provider=self.provider_name`, `note="hint truncated" if spec.hint_truncated else None`.
6. `followup` with `engines == []` and no tool calls: `det = state.last_reports.get("deterministic")`, `spec = state.last_reports.get("specialist")`, `req=None`; note in trace `ToolCallTrace(tool="session_memory", args={}, rows=None, provider=None, latency_ms=0, note="answered from last reports")`.
7. `answer = synthesizer.synthesize(...)`.
8. State update: `if state.title == "New chat": state.title = message.strip()[:60]`; append `ChatMessage(role="user", content=message)` and `ChatMessage(role="assistant", content=answer.headline, answer=answer)`; `last_airports` = req.airports or (from det rows) or unchanged; `last_filters = plan.filters`; `last_preset = det.preset if det else state.last_preset`; `last_reports["deterministic"/"specialist"]` set when produced (never cleared by informational turns).
9. `LLMError` propagates untouched (state not appended — the UI shows the error).
`SessionStore`: JSON files `<dir>/<id>.json` = `state.model_dump_json(indent=1)`; `new()` id = `uuid.uuid4().hex[:12]`; `list()` sorted by mtime desc; `load` unknown → `KeyError`; `directory` created on init.

- [ ] **Step 1: failing tests** — `tests/agent/test_sessions.py` (new/save/load roundtrip incl. an `Answer` in messages and `last_reports` with both report types; list order; rename; delete; unknown → KeyError) and `tests/agent/test_concierge.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.agent.concierge import Concierge
from airport_agent.agent.planner import Planner
from airport_agent.agent.specialists.runner import SpecialistRunnerImpl
from airport_agent.agent.synthesis import Synthesizer
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import LLMError, LLMResult, SessionState
from tests.agent.fake_llm import ScriptedLLM
from tests.agent.test_planner import PRESETS, _plan_json
from tests.agent.test_specialist_runner import FINAL
from tests.agent.test_synthesis import SYN


def _concierge(script, fake_data, fake_analyst, specs):
    llm = ScriptedLLM(script)
    reg = build_registry(fake_data, fake_analyst)
    return Concierge(llm=llm, registry=reg, analyst=fake_analyst, specialists=SpecialistRunnerImpl(llm, reg, specs),
                     planner=Planner(llm, reg, specs, PRESETS), synthesizer=Synthesizer(llm, specs)), llm


def test_analytical_rank_flow_updates_state_and_trace(fake_data, fake_analyst, specs):
    c, llm = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="New chat")
    seen = []
    ans = c.answer("Which airports in New England are strong candidates for terminal expansion?", state, on_plan=seen.append)
    assert seen and seen[0].intent == "analytical"
    assert [t.tool for t in ans.tool_trace] == ["deterministic:rank", "specialist:expansion_analyst"]
    assert ans.tool_trace[1].provider == "fake"
    assert state.title.startswith("Which airports") and len(state.messages) == 2 and state.messages[1].answer is ans
    assert set(state.last_reports) == {"deterministic", "specialist"} and state.last_preset == "terminal_expansion"
    assert set(state.last_airports) == {"BOS", "BDL", "PVD", "MHT", "PWM"}
    assert len(llm.calls) == 4  # plan + specialist(1 turn + final) + synthesis


def test_informational_flow(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[], horizons=[], scoring_preset="none",
                    tool_calls=[{"tool": "get_route_stats", "args_json": '{"iata": "ANC"}'}])
    c, llm = _concierge([js, SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    ans = c.answer("What is the percentage of long haul flights out of Anchorage airport?", state)
    assert [t.tool for t in ans.tool_trace] == ["get_route_stats"] and ans.analyst_view is None
    assert len(llm.calls) == 2 and "deterministic" not in state.last_reports


def test_followup_from_memory_makes_one_llm_call(fake_data, fake_analyst, specs):
    c, llm = _concierge([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN,
                         _plan_json(intent="followup", engines=[], question_type="none", faa_regions=[]), SYN], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    c.answer("rank NE", state)
    n = len(llm.calls)
    ans = c.answer("why is the top one first?", state)
    assert len(llm.calls) - n == 2 and ans.tool_trace[0].tool == "session_memory"


def test_clarify_makes_no_extra_calls(fake_data, fake_analyst, specs):
    js = _plan_json(intent="clarify", engines=[], question_type="none", faa_regions=[], presentation_notes="Which horizon?")
    c, llm = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.headline == "Which horizon?" and len(llm.calls) == 1 and ans.evidence_tables == []


def test_analytical_without_targets_becomes_clarify(fake_data, fake_analyst, specs):
    js = _plan_json(faa_regions=[], airports=[])
    c, llm = _concierge([js], fake_data, fake_analyst, specs)
    ans = c.answer("rank them", SessionState(session_id="s", title="t"))
    assert ans.plan.intent == "clarify" and len(llm.calls) == 1


def test_tool_error_is_traced_not_raised(fake_data, fake_analyst, specs):
    js = _plan_json(intent="informational", engines=["tools"], question_type="none", faa_regions=[],
                    tool_calls=[{"tool": "get_profile", "args_json": '{"iata": "ZZZ"}'}])
    c, _ = _concierge([js, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("profile ZZZ", SessionState(session_id="s", title="t"))
    assert "KeyError" in (ans.tool_trace[0].note or "")


def test_llm_error_propagates_and_state_untouched(fake_data, fake_analyst, specs):
    c, _ = _concierge([LLMError("gemini", 429, "quota")], fake_data, fake_analyst, specs)
    state = SessionState(session_id="s", title="t")
    with pytest.raises(LLMError):
        c.answer("x", state)
    assert state.messages == []


def test_custom_with_airports_uses_compare(fake_data, fake_analyst, specs):
    js = _plan_json(question_type="none", engines=["deterministic", "specialist:general_analyst"], airports=["DEN"], faa_regions=[])
    c, _ = _concierge([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN], fake_data, fake_analyst, specs)
    ans = c.answer("is DEN cargo growth sustainable?", SessionState(session_id="s", title="t"))
    assert ans.tool_trace[0].tool == "deterministic:compare"
```
- [ ] **Step 2: run** → ImportError. **Step 3: implement**. **Step 4: run, lint, commit** `git commit -m "feat(agent): Concierge plan→dispatch→synthesis loop and SessionStore"`

---

### Task 11: `App`, `build_app`, package exports

**Files:** Create `src/airport_agent/agent/app.py`, `tests/agent/test_app.py`; modify `src/airport_agent/agent/__init__.py`.

**Interfaces — Produces:** `App`, `build_app` exactly as in the top interfaces block. `build_app` wiring: `data = data_service or _default_data()`, `analyst = analyst or _default_analyst(data)`, `llm = llm or LiteLLMClient()`; the two `_default_*` do lazy imports `from airport_agent.data import DuckDBDataService` / `from airport_agent.scoring import Analyst` inside the function and re-raise `ImportError` as `RuntimeError("data/scoring packages not available in this checkout — pass data_service/analyst explicitly (Phase 3 wires the defaults)")`. `registry = build_registry(data, analyst)`; presets list = `["balanced","terminal_expansion","congestion_relief","market_entry"]` (the Analyst validates names; the planner only lists them); `sessions = SessionStore(sessions_dir or repo_root/"data"/"sessions")`. `App.answer` delegates to the Concierge and then `self.sessions.save(state)`. `provider_status()` = `llm.status()` if the client has `status`, else `[{"name": getattr(llm,'provider_name','llm'), "model": "?", "status": "unknown", "detail": ""}]`. `sample_questions()` returns `planner.SAMPLE_QUESTIONS`.

- [ ] **Step 1: failing tests** — `tests/agent/test_app.py`: `build_app(data_service=fake_data, analyst=fake_analyst, llm=ScriptedLLM([...]), sessions_dir=tmp_path)`; `app.answer` returns an `Answer` and the session file exists with 2 messages; `provider_status()` for a client without `status` gives status "unknown"; `sample_questions()` has 4; `build_app(llm=ScriptedLLM([]))` with no data → `RuntimeError` mentioning "Phase 3"; `from airport_agent.agent import App, build_app, SessionStore, Concierge` works.
- [ ] **Step 2–4:** implement, run full gate, commit `git commit -m "feat(agent): App/build_app composition root and package exports"`

---

### Task 12: Golden tests for the four sample questions + live smoke

**Files:** Create `tests/golden/__init__.py`, `tests/golden/test_sample_questions.py`, `tests/golden/test_live_smoke.py`, `tests/golden/scripts.py` (the scripted LLM outputs per question).

- [ ] **Step 1: write** `tests/golden/scripts.py` with, per sample question, the Plan JSON (Q1 rank/ANE/terminal_expansion/expansion_analyst; Q2 compare LAX,SNA/12m/congestion_relief/capacity_analyst with `focus_metrics` = the P2 ids; Q3 informational `get_route_stats {"iata":"ANC"}`; Q4 diagnose SFO/12m/capacity_analyst), a specialist final JSON (Q1/Q2/Q4), and a synthesis JSON, plus 6 follow-up plans (Q1: "and with congestion_relief?" → analytical re-dispatch; "why BOS first?" → followup memory; Q2: "add BUR" → analytical compare 3; Q3: "and for freight only?" → informational; Q4: "which of those signals is strongest?" → followup memory; global: "which sources did you use?" → informational `list_sources`).
- [ ] **Step 2: write** `test_sample_questions.py`: build the app with `ScriptedLLM(scripts.for_question(i))`, `FakeDataService`, `FakeAnalyst`, `tmp_path` sessions; for each question assert: `Answer` valid; `plan_line` starts with "How I'm approaching this"; headline non-empty; `evidence_tables` non-empty; every table cell that is a number appears in the underlying report/tool result (walk `state.last_reports` / trace) — implement as: collect all floats from `det.model_dump()`+tool results and assert table numeric cells ⊆ that set; `assumptions` non-empty; `citations` non-empty with vintage; Q3 has no `analyst_view`; Q2 tables include a comparison column for both LAX and SNA with `avg_dep_delay_min` 12.9/13.9; Q4 explanation text "Signals of unmet demand" reaches a table or note; the total number of `llm.calls` per question ≤ 6; follow-ups run in the same session and the memory follow-ups add exactly 2 calls.
- [ ] **Step 3: write** `test_live_smoke.py`: `@pytest.mark.network @pytest.mark.llm`, `pytest.importorskip("litellm")`, skip if `not os.getenv("GEMINI_API_KEY")`; builds `LiteLLMClient()` and asks Q3 (informational, 2 calls) through the app with fakes; asserts an `Answer` and prints the model used. Run manually with `uv run pytest tests/golden/test_live_smoke.py -m "network and llm" -q -s`.
- [ ] **Step 4:** run full gate, commit `git commit -m "test(golden): scripted goldens for the four sample questions + live smoke"`

---

### Task 13: Limitations-log rows (append-only) + package docstrings

- [ ] Append to `docs/design/known-limitations-and-tradeoffs.md`:
```
| 25 | Plan.filters carries the AnalysisRequest fields and per-tool `tool_calls[{tool,args_json}]` (JSON string) so the Plan is one portable structured-output call with no free-form nested objects | Decision | Slightly clunkier schema; args parsed by code | Args are still pydantic-validated by the ToolRegistry; bad JSON ⇒ tool error in the trace | Accepted |
| 26 | Specialist evidence is resolved by code from tool results / deterministic evidence via `evidence_refs[{iata,metric_id}]`; unresolved refs are dropped and listed in caveats | Decision | The specialist cannot introduce numbers; a lazy specialist may cite less | Prompt requires refs; report evidence by metric id as fallback | Accepted |
| 27 | Synthesis JSON parse failure ⇒ headline falls back to the deterministic explanation with an explicit uncertainty note (formatting, not reasoning, degradation) | Decision | Rare, visible | Provider errors still raise LLMError loudly | Accepted |
```
- [ ] Commit `git commit -m "docs: limitations rows 25-27 (agent decisions)"`.

---

## Self-review
- **Spec coverage (design 03):** roles ✔ (Concierge T10, tools T4–5, Deterministic dispatch T10, specialists T7–8, synthesizer T9) · question classes incl. followup memory + clarify (T6/T10) · shared filter vocabulary (T5/T6) · structured dispatch + hint truncation (T8) · roster with tools/presets/caveats (T7) · general_analyst extended (T7 body honours `extended`) · sample routing (T6 prompt, T12 goldens) · in-process tools with pydantic validation (T4) · presentation/transparency (plan line, hidden-metrics reason, citations, assumptions — T9) · call budget (T10/T12 asserts) · failure policy (LLMError propagates T2/T8/T10) · synthesis structure (T9) · testing goldens/schema tests (T12) · sessions (T10) · UI entry point (T11).
- **Placeholder scan:** Tasks 5, 7, 8, 9, 10, 11 give the full behavioural spec + tests but leave straightforward code to the implementer (opus/sonnet with complete tests) — acceptable per SDD; no "TBD".
- **Type consistency:** `ToolRegistry.call(name, args, engine)` used identically in T4/T5/T8/T10; `Planner.plan → (Plan, PlanFilters)` in T6/T10; `SpecialistRunnerImpl.run(req, det)` in T8/T10; `Synthesizer.synthesize(**kw)` keyword signature identical in T9/T10; `App`/`SessionStore` match plan 2d.
- **Assumptions surfaced to the human:** default model string `gemini/gemini-2.5-flash` (verify live in Phase 3 — Gemini 3.x flash id may differ); `custom` ⇒ `compare` if airports else `rank`; follow-ups with empty engines answer from `last_reports`.
