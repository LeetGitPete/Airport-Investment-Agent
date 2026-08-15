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
