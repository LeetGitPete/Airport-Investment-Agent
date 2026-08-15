from __future__ import annotations

import json

import pytest

from airport_agent.ui import cli


@pytest.fixture(autouse=True)
def _factory(monkeypatch):
    monkeypatch.setenv("AIRPORT_AGENT_APP_FACTORY", "tests.ui.fake_app:make_app")


def test_cli_text_and_json(capsys):
    assert cli.main(["Compare LA and Santa Ana airport congestion levels."]) == 0
    out = capsys.readouterr().out
    assert "HEADLINE:" in out and "12.9" in out
    assert cli.main(["rank New England", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["plan"]["intent"] == "analytical" and data["assumptions"]


def test_cli_llm_error_exit_1(capsys):
    assert cli.main(["please error"]) == 1
    err = capsys.readouterr().err
    assert "LLM provider error" in err and "gemini" in err


def test_cli_defaults_forwarded(capsys):
    from tests.ui import fake_app
    assert cli.main(["rank", "--horizon", "10y", "--preset", "market_entry", "--peer-group", "all"]) == 0
    assert fake_app.LAST_APP.last_defaults == {"horizon": "10y", "scoring_preset": "market_entry", "peer_group": "all"}


def test_cli_session_known_id_reuses_state(monkeypatch, capsys):
    from tests.ui import fake_app

    app = fake_app.FakeApp()
    existing = app.sessions.new(title="Existing chat")
    monkeypatch.setattr(fake_app, "make_singleton_app", lambda: app, raising=False)
    monkeypatch.setenv("AIRPORT_AGENT_APP_FACTORY", "tests.ui.fake_app:make_singleton_app")

    assert cli.main(["rank New England", "--session", existing.session_id]) == 0
    assert capsys.readouterr().err == ""
    reloaded = app.sessions.load(existing.session_id)
    assert len(reloaded.messages) == 2
    assert reloaded.title == "Existing chat"  # title only auto-set from "New chat"


def test_cli_session_unknown_id_creates_new_and_echoes_id(capsys):
    from tests.ui import fake_app

    assert cli.main(["rank New England", "--session", "does-not-exist"]) == 0
    err = capsys.readouterr().err.strip()
    assert err and err != "does-not-exist"
    assert err in [s.session_id for s in fake_app.LAST_APP.sessions.list()]


def test_cli_factory_error_exit_2(monkeypatch, capsys):
    monkeypatch.setenv("AIRPORT_AGENT_APP_FACTORY", "tests.ui.fake_app:make_broken_app")
    assert cli.main(["anything"]) == 2
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "boom" in err
