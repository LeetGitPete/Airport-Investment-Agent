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
