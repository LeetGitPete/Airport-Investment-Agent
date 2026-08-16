"""Debug log: JSONL record shape, append semantics, the never-raise guarantee, and the emitters
wired through a real turn (fakes; the scripts mirror tests/agent/test_concierge.py)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from airport_agent.agent.concierge import Concierge
from airport_agent.agent.debuglog import DebugLog, NullDebugLog
from airport_agent.agent.planner import Planner
from airport_agent.agent.specialists.runner import SpecialistRunnerImpl
from airport_agent.agent.synthesis import Synthesizer
from airport_agent.agent.tools.data_tools import build_registry
from airport_agent.contracts import LLMResult, SessionState
from tests.agent.fake_llm import ScriptedLLM
from tests.agent.test_planner import PRESETS, _plan_json
from tests.agent.test_specialist_runner import FINAL
from tests.agent.test_synthesis import SYN


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# record shape


def test_record_has_ts_turn_event_and_payload(tmp_path: Path) -> None:
    DebugLog(tmp_path).log("s1", 3, "tool_call", tool="rank_airports", rows=7)
    (record,) = _lines(tmp_path / "s1.jsonl")
    datetime.fromisoformat(record["ts"])  # ISO-parseable, raises otherwise
    assert record["turn"] == 3
    assert record["event"] == "tool_call"
    assert record["tool"] == "rank_airports"
    assert record["rows"] == 7


# append semantics


def test_multiple_calls_append_to_the_same_file(tmp_path: Path) -> None:
    log = DebugLog(tmp_path)
    log.log("s1", 1, "plan_raw")
    log.log("s1", 2, "tool_call", tool="a")
    records = _lines(tmp_path / "s1.jsonl")
    assert [r["turn"] for r in records] == [1, 2]
    assert [r["event"] for r in records] == ["plan_raw", "tool_call"]


def test_two_sessions_write_two_files(tmp_path: Path) -> None:
    log = DebugLog(tmp_path)
    log.log("s1", 1, "plan_raw")
    log.log("s2", 1, "plan_raw")
    assert (tmp_path / "s1.jsonl").exists()
    assert (tmp_path / "s2.jsonl").exists()


# never raises


def test_non_serializable_payload_is_stringified_not_raised(tmp_path: Path) -> None:
    class Odd:
        def __str__(self) -> str:
            return "odd-object"

    DebugLog(tmp_path).log("s1", 1, "error", detail=Odd(), tags={"a"})
    (record,) = _lines(tmp_path / "s1.jsonl")
    assert record["detail"] == "odd-object"
    assert isinstance(record["tags"], str)  # set degrades to its str() form


def test_io_failure_is_swallowed(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("plain file where the log directory should be", encoding="utf-8")
    DebugLog(blocker).log("s1", 1, "tool_call", tool="a")  # mkdir fails; must not raise
    assert blocker.read_text(encoding="utf-8").startswith("plain file")


# null object


def test_null_debuglog_is_inert(tmp_path: Path) -> None:
    NullDebugLog().log("s1", 1, "tool_call", tool="a", rows=0)
    assert list(tmp_path.iterdir()) == []


# integration: the emitters through real turns (same fakes and scripts as test_concierge)


def _wired(script, fake_data, fake_analyst, specs, log):
    llm = ScriptedLLM(script)
    reg = build_registry(fake_data, fake_analyst)
    return Concierge(llm=llm, registry=reg, analyst=fake_analyst,
                     specialists=SpecialistRunnerImpl(llm, reg, specs),
                     planner=Planner(llm, reg, specs, PRESETS),
                     synthesizer=Synthesizer(llm, specs, debug=log), debug=log)


def _records(tmp_path: Path, session_id: str = "dbg") -> list[dict]:
    records = _lines(tmp_path / f"{session_id}.jsonl")  # every line must json-parse
    for record in records:
        assert set(record) >= {"ts", "turn", "event"}
        datetime.fromisoformat(record["ts"])
    return records


def test_analytical_turn_writes_the_pipeline_events(tmp_path, fake_data, fake_analyst, specs) -> None:
    log = DebugLog(tmp_path)
    c = _wired([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
               fake_data, fake_analyst, specs, log)
    c.answer("Which airports in New England are strong candidates for terminal expansion?",
             SessionState(session_id="dbg", title="t"))
    records = _records(tmp_path)
    events = [r["event"] for r in records]
    for expected in ("plan_raw", "specialist_result", "answer_curation"):
        assert expected in events
    assert all(r["turn"] == 1 for r in records)
    plan_raw = next(r for r in records if r["event"] == "plan_raw")
    assert plan_raw["plan"]["intent"] == "analytical" and "source_turn" in plan_raw["filters"]
    result = next(r for r in records if r["event"] == "specialist_result")
    assert result["specialist"] and "hint_truncated" in result and "dropped_evidence_refs" in result
    curation = next(r for r in records if r["event"] == "answer_curation")
    assert "dropped_report_caveats" in curation and isinstance(curation["notes_before_cap"], int)


def test_followup_from_memory_writes_a_memory_event(tmp_path, fake_data, fake_analyst, specs) -> None:
    log = DebugLog(tmp_path)
    c = _wired([_plan_json(), LLMResult(text="ok", provider="f", model="m"), FINAL, SYN,
                _plan_json(intent="followup", engines=[], question_type="none", faa_regions=[]), SYN],
               fake_data, fake_analyst, specs, log)
    state = SessionState(session_id="dbg", title="t")
    c.answer("rank NE", state)
    c.answer("why is the top one first?", state)
    memory = next(r for r in _records(tmp_path) if r["event"] == "memory")
    assert memory["turn"] == 2 and memory["hit"] == "last_reports"


def test_clarify_diagnostic_writes_the_verbatim_error_event(tmp_path, fake_data, fake_analyst,
                                                            specs) -> None:
    # question_type=custom with a non-general specialist: to_analysis_request raises, the turn
    # degrades to a clarify with a diagnostic — the user sees a plain sentence, the log keeps the
    # validator's own words.
    js = _plan_json(question_type="custom")
    log = DebugLog(tmp_path)
    c = _wired([js, LLMResult(text="ok", provider="f", model="m"), FINAL, SYN],
               fake_data, fake_analyst, specs, log)
    ans = c.answer("do something custom", SessionState(session_id="dbg", title="t"))
    error = next(r for r in _records(tmp_path) if r["event"] == "error")
    assert error["turn"] == 1
    assert error["detail"] == "question_type=custom is only valid for general_analyst"
    assert error["detail"] not in " ".join(ans.uncertainty_notes)  # verbatim only in the log
