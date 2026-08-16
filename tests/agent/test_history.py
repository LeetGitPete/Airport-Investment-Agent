"""History digests and compaction (contracts-v3)."""
from __future__ import annotations

from concurrent.futures import Executor, Future

from airport_agent.agent.compaction import RETRY_TEMPLATE, Compactor, truncate_at_sentence
from airport_agent.agent.history import (
    KEEP_VERBATIM,
    archive_index,
    recent_turns,
    table_digest,
    turn_digest,
    turns,
    turns_to_fold,
)
from airport_agent.contracts import AnalysisRequest, ChatMessage, LLMError, SessionState, Table
from tests.agent.fake_llm import ScriptedLLM
from tests.ui.fake_app import make_answer


class Inline(Executor):
    """Runs the job on the calling thread — deterministic tests, same Future contract."""

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[override]
        f: Future = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 — the future carries it, as a pool would
            f.set_exception(exc)
        return f


def _state(n_turns: int, **over) -> SessionState:
    messages = []
    for i in range(1, n_turns + 1):
        messages.append({"role": "user", "content": f"question {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}",
                         "answer": make_answer("compare") if i % 2 else None})
    return SessionState(session_id="s", title="t", messages=messages, **over)


# turns and digests


def test_turns_pair_user_and_assistant_and_ignore_a_dangling_user_message():
    st = _state(2)
    st.messages.append(ChatMessage(role="user", content="unanswered"))
    ts = turns(st)
    assert [t.number for t in ts] == [1, 2] and ts[1].question == "question 2" and ts[1].reply == "reply 2"


def test_turn_digest_is_one_fixed_form_with_tables():
    st = _state(1)
    d = turn_digest(turns(st)[0])
    assert d.startswith("[turn 1] Q: question 1")
    assert "A (analytical):" in d and "Analyst:" in d and "Agreement:" in d
    assert "Tables: Average departure delay (min, 12m) (2 rows: LAX 12.9; SNA 13.9)" in d


def test_digest_clips_long_fields_and_a_clarify_turn_has_only_the_reply():
    st = SessionState(session_id="s", title="t", messages=[
        {"role": "user", "content": "q " * 400}, {"role": "assistant", "content": "Which horizon?"}])
    d = turn_digest(turns(st)[0])
    assert len(d.splitlines()[0]) < 320 and d.endswith("A: Which horizon?")


def test_table_digest_shows_first_five_rows_and_counts_the_rest():
    t = Table(title="Ranking", columns=["iata", "score"], rows=[[f"A{i}", float(i)] for i in range(8)])
    d = table_digest(t)
    assert d.startswith("Ranking (8 rows, +3 more: A0 0; A1 1;") and "A7" not in d


def test_recent_and_fold_windows():
    st = _state(8)
    assert [t.number for t in recent_turns(st)] == [4, 5, 6, 7, 8]
    assert [t.number for t in turns_to_fold(st)] == [1, 2, 3]
    st.summary_through_turn = 2
    assert [t.number for t in turns_to_fold(st)] == [3]
    st.summary_through_turn = 5  # a summary that already covers part of the verbatim window
    assert [t.number for t in recent_turns(st)] == [6, 7, 8]
    assert KEEP_VERBATIM == 5


def test_archive_index_names_the_analysis_per_turn(fake_analyst):
    rep = fake_analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "BDL", "PVD"],
                                            horizons=["5y"], scoring_preset="balanced"))
    st = SessionState(session_id="s", title="t", report_archive={2: [rep]})
    line, = archive_index(st)
    assert line.startswith("turn 2: rank · preset balanced · 5y · 3 airports (") and "BOS" in line


# compaction


def test_due_every_second_turn_when_there_is_something_to_fold():
    c = Compactor(ScriptedLLM([]), executor=Inline())
    assert not c.due(_state(5)) and not c.due(_state(6, summary_through_turn=1))
    assert c.due(_state(6)) and not c.due(_state(7)) and c.due(_state(8))


def test_compact_within_limit_is_one_call():
    llm = ScriptedLLM(["BOS led; SNA vs LAX compared."])
    r = Compactor(llm, max_chars=100, executor=Inline()).compact("", ["[turn 1] Q: x"], 1)
    assert r.summary == "BOS led; SNA vs LAX compared." and r.through_turn == 1 and len(llm.calls) == 1
    assert "At most 100 characters" in llm.calls[0]["messages"][0]["content"]


def test_over_limit_gets_exactly_one_retry_with_the_fixed_message():
    llm = ScriptedLLM(["x" * 120, "short enough"])
    r = Compactor(llm, max_chars=100, executor=Inline()).compact("old", ["d1"], 3)
    assert r.summary == "short enough" and len(llm.calls) == 2
    retry = llm.calls[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": "x" * 120}
    assert retry[-1] == {"role": "user", "content": RETRY_TEMPLATE.format(actual=120, allowed=100)}
    assert retry[-1]["content"] == "summary is 120 chars, only 100 chars are allowed"


def test_over_limit_twice_is_truncated_silently():
    long = ("BOS leads on demand. " * 20).strip()
    llm = ScriptedLLM([long, long])
    r = Compactor(llm, max_chars=100, executor=Inline()).compact("", ["d"], 2)
    assert len(r.summary) <= 100 and r.summary.endswith(".") and len(llm.calls) == 2


def test_truncate_prefers_a_sentence_boundary_then_hard_cuts():
    assert truncate_at_sentence("One two. Three four. Five six seven eight.", 24) == "One two. Three four."
    assert truncate_at_sentence("abcdefghij" * 5, 12) == "abcdefghijab"


def test_schedule_then_collect_applies_the_summary_on_the_next_turn():
    llm = ScriptedLLM(["turns 1-3: compared LAX and SNA."])
    c = Compactor(llm, executor=Inline())
    st = _state(8)
    assert c.schedule(st) and c.pending("s")
    assert st.summary == ""  # nothing applied yet: the turn is the only writer
    assert c.collect(st) and not c.pending("s")
    assert st.summary == "turns 1-3: compared LAX and SNA." and st.summary_through_turn == 3
    assert not c.collect(st)  # nothing pending now
    digests = llm.calls[0]["messages"][1]["content"]
    assert "[turn 1]" in digests and "[turn 3]" in digests and "[turn 4]" not in digests


def test_provider_error_keeps_the_old_summary_and_never_raises():
    c = Compactor(ScriptedLLM([LLMError("fake", 429, "quota")]), executor=Inline())
    st = _state(6, summary="old", summary_through_turn=0)
    assert c.schedule(st)
    assert not c.collect(st) and st.summary == "old" and st.summary_through_turn == 0
    assert c.due(st)  # tried again at the next due turn


def test_schedule_is_a_noop_when_not_due_or_already_pending():
    c = Compactor(ScriptedLLM(["s"]), executor=Inline())
    assert not c.schedule(_state(5))
    st = _state(6)
    assert c.schedule(st) and not c.schedule(st)
