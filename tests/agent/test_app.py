from __future__ import annotations

import json

import pytest

from airport_agent.agent import App, Concierge, SessionStore, build_app
from airport_agent.contracts import Answer, LLMResult
from tests.agent.fake_llm import ScriptedLLM
from tests.agent.test_planner import _plan_json
from tests.agent.test_specialist_runner import FINAL
from tests.agent.test_synthesis import SYN

ANALYTICAL_SCRIPT = [_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN]


class _StatusClient(ScriptedLLM):
    provider_name = "gemini"

    def status(self):
        return [{"name": "gemini", "model": "gemini/gemini-2.5-flash", "status": "ready", "detail": ""}]


def _app(tmp_path, fake_data, fake_analyst, script=None):
    return build_app(data_service=fake_data, analyst=fake_analyst,
                     llm=ScriptedLLM(script if script is not None else list(ANALYTICAL_SCRIPT)),
                     sessions_dir=tmp_path / "sessions")


def test_exports_are_importable():
    assert App and build_app and SessionStore and Concierge


def test_answer_saves_the_session(tmp_path, fake_data, fake_analyst):
    app = _app(tmp_path, fake_data, fake_analyst)
    state = app.sessions.new()
    answer = app.answer("Which airports in New England are strong candidates for terminal expansion?", state)
    assert isinstance(answer, Answer) and answer.headline
    path = tmp_path / "sessions" / f"{state.session_id}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored["messages"]) == 2 and stored["title"].startswith("Which airports")
    assert app.sessions.load(state.session_id).last_reports


def test_app_exposes_data_and_samples(tmp_path, fake_data, fake_analyst):
    app = _app(tmp_path, fake_data, fake_analyst)
    assert app.data is fake_data
    questions = app.sample_questions()
    assert len(questions) == 4 and questions[0].startswith("Which airports in New England")


def test_provider_status_without_a_status_method_is_unknown(tmp_path, fake_data, fake_analyst):
    app = _app(tmp_path, fake_data, fake_analyst, script=[])
    status = app.provider_status()
    assert status == [{"name": "fake", "model": "?", "status": "unknown", "detail": ""}]


def test_provider_status_uses_the_client_when_available(tmp_path, fake_data, fake_analyst):
    app = build_app(data_service=fake_data, analyst=fake_analyst, llm=_StatusClient([]),
                    sessions_dir=tmp_path / "sessions")
    assert app.provider_status()[0]["status"] == "ready"


def test_missing_data_layer_fails_with_an_actionable_error(tmp_path):
    with pytest.raises(RuntimeError, match="Phase 3"):
        build_app(llm=ScriptedLLM([]), sessions_dir=tmp_path / "sessions")


def test_llm_error_leaves_the_session_file_untouched(tmp_path, fake_data, fake_analyst):
    from airport_agent.contracts import LLMError
    app = _app(tmp_path, fake_data, fake_analyst, script=[LLMError("gemini", 429, "quota")])
    state = app.sessions.new()
    with pytest.raises(LLMError):
        app.answer("rank NE", state)
    stored = json.loads((tmp_path / "sessions" / f"{state.session_id}.json").read_text(encoding="utf-8"))
    assert stored["messages"] == []
