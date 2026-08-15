from __future__ import annotations

import os
import time

import pytest

from airport_agent.agent.sessions import SessionStore
from airport_agent.contracts import Answer, ChatMessage, Plan, RankedItem, SpecialistReport


def _answer(plan):
    return Answer(plan=plan, plan_line="pl", headline="h", evidence_tables=[], analyst_view=None,
                  agreement_line=None, assumptions=["a"], uncertainty_notes=["u"], citations=[],
                  follow_ups=["f"], tool_trace=[])


def _plan():
    return Plan(intent="analytical", engines=["deterministic"], filters={"airports": ["BOS"]},
                tools_to_call=[], specialist=None, presentation_notes="")


def _specialist_report():
    return SpecialistReport(specialist="expansion_analyst", question_type="rank",
                            ranking=[RankedItem(iata="BOS", rank=1, rationale="r", confidence=0.5)],
                            narrative="n", evidence=[], agreement="a", disagreements=[], confidence=0.5,
                            assumptions=[], caveats=[], hint_truncated=False)


def test_new_creates_and_persists(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    state = store.new()
    assert state.title == "New chat" and len(state.session_id) == 12
    assert (tmp_path / "sessions" / f"{state.session_id}.json").exists()
    assert store.load(state.session_id).session_id == state.session_id


def test_roundtrip_keeps_answers_and_reports(tmp_path, fake_analyst):
    from airport_agent.contracts import AnalysisRequest
    store = SessionStore(tmp_path)
    state = store.new("Rank NE")
    plan = _plan()
    answer = _answer(plan)
    state.messages = [ChatMessage(role="user", content="rank NE"),
                      ChatMessage(role="assistant", content="h", answer=answer)]
    state.last_reports["deterministic"] = fake_analyst.rank(
        AnalysisRequest(question_type="rank", airports=["BOS"], horizons=["12m"]))
    state.last_reports["specialist"] = _specialist_report()
    state.last_airports = ["BOS"]
    state.last_preset = "balanced"
    store.save(state)

    loaded = store.load(state.session_id)
    assert loaded.messages[1].answer == answer
    assert loaded.last_reports["deterministic"].report_type == "deterministic"
    assert loaded.last_reports["specialist"].report_type == "specialist"
    assert loaded.last_airports == ["BOS"] and loaded.last_preset == "balanced"


def test_list_is_newest_first(tmp_path):
    store = SessionStore(tmp_path)
    first = store.new("one")
    time.sleep(0.01)
    second = store.new("two")
    os.utime(tmp_path / f"{second.session_id}.json", (time.time() + 5, time.time() + 5))
    assert [s.session_id for s in store.list()][:2] == [second.session_id, first.session_id]


def test_rename_and_delete(tmp_path):
    store = SessionStore(tmp_path)
    state = store.new()
    renamed = store.rename(state.session_id, "New England ranking")
    assert renamed.title == "New England ranking"
    assert store.load(state.session_id).title == "New England ranking"
    store.delete(state.session_id)
    assert store.list() == []
    with pytest.raises(KeyError):
        store.load(state.session_id)


def test_unknown_session_raises_key_error(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(KeyError):
        store.load("does_not_exist")
    with pytest.raises(KeyError):
        store.rename("does_not_exist", "x")
    with pytest.raises(KeyError):
        store.delete("does_not_exist")


def test_directory_is_created_and_only_json_is_listed(tmp_path):
    directory = tmp_path / "deep" / "sessions"
    store = SessionStore(directory)
    assert directory.is_dir()
    (directory / "notes.txt").write_text("ignore me", encoding="utf-8")
    store.new("one")
    assert len(store.list()) == 1
