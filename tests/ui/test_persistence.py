"""Session persistence round trip: `FakeApp(sessions_dir=...)` writes each `SessionState` (including the
saved `Answer`, tables and all) to `<sessions_dir>/<id>.json`, mirroring the real `SessionStore`'s on-disk
semantics closely enough that a fresh `FakeApp` pointed at the same directory sees the prior conversation.
"""
from __future__ import annotations

from tests.ui.fake_app import FakeApp


def test_answer_survives_a_fresh_app_on_the_same_sessions_dir(tmp_path):
    app = FakeApp(sessions_dir=str(tmp_path))
    state = app.sessions.new()
    original = app.answer("rank NE", state)

    # A brand-new FakeApp/FakeSessions instance, same directory — nothing shared in memory.
    reloaded_app = FakeApp(sessions_dir=str(tmp_path))
    sessions = reloaded_app.sessions.list()

    assert sessions, "the session written to disk by the first FakeApp was found by the second"
    reloaded = sessions[0]
    assert reloaded.session_id == state.session_id
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].role == "user"
    assert reloaded.messages[0].content == "rank NE"

    reloaded_answer = reloaded.messages[1].answer
    assert reloaded_answer is not None
    assert reloaded_answer.headline == original.headline
    # A representative sample of the fixed structure, not just the headline: tables (incl. `None` cells),
    # citations and tool trace all round-trip through JSON unchanged.
    assert reloaded_answer.evidence_tables == original.evidence_tables
    assert reloaded_answer.citations == original.citations
    assert reloaded_answer.tool_trace == original.tool_trace
    assert reloaded_answer.assumptions == original.assumptions
    assert reloaded_answer.uncertainty_notes == original.uncertainty_notes


def test_rename_and_delete_persist_to_disk(tmp_path):
    app = FakeApp(sessions_dir=str(tmp_path))
    state = app.sessions.new()
    app.sessions.rename(state.session_id, "Renamed chat")

    reloaded_app = FakeApp(sessions_dir=str(tmp_path))
    assert reloaded_app.sessions.load(state.session_id).title == "Renamed chat"

    reloaded_app.sessions.delete(state.session_id)
    assert not (tmp_path / f"{state.session_id}.json").exists()

    third_app = FakeApp(sessions_dir=str(tmp_path))
    assert third_app.sessions.list() == []
