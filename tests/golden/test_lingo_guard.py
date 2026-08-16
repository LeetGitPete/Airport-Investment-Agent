"""Lingo guards (decision 2026-08-16): internal ids never reach a user surface.

Two invariants: every source id in config/sources.yaml has a user-facing display name, and a fully
rendered answer (CLI text form, minus the deliberately raw TOOL TRACE debug section) never contains
raw tool ids, engine ids, specialist ids, or tier lingo.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from airport_agent.contracts.display import SOURCE_DISPLAY

ROOT = Path(__file__).resolve().parents[2]

#: Internal tokens that must never appear outside "Show work". Tool/engine/specialist ids plus
#: tier lingo (word-boundary matched, case-insensitive for tiers).
FORBIDDEN = [
    "get_profile", "get_route_stats", "get_live_status", "get_metric_series", "find_airports",
    "list_sources", "explain_metric", "score_airports", "compare_airports", "diagnose_unmet_demand",
    "session_memory", "deterministic:", "specialist:", "expansion_analyst", "capacity_analyst",
    "market_analyst", "general_analyst",
]
TIER = re.compile(r"tier[ -_]?[abc123]", re.IGNORECASE)


def test_every_source_id_has_a_display_name():
    ids = set(yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")))
    missing = ids - set(SOURCE_DISPLAY)
    assert not missing, f"sources without a user-facing name (they would render raw): {sorted(missing)}"


def _visible_text(answer) -> str:
    from airport_agent.ui.textfmt import answer_to_text

    text = answer_to_text(answer)
    return text.split("TOOL TRACE:")[0]  # the trace is the deliberate debug view


def test_rendered_answers_carry_no_internal_lingo(tmp_path):
    from tests.agent.fake_analyst import FakeAnalyst
    from tests.agent.fake_llm import ScriptedLLM
    from tests.fakes import FakeDataService
    from tests.golden import scripts
    from tests.golden.test_sample_questions import QUESTIONS

    from airport_agent.agent import build_app

    for index, question in enumerate(QUESTIONS):
        data = FakeDataService()
        analyst = FakeAnalyst(data)
        app = build_app(data_service=data, analyst=analyst, llm=ScriptedLLM(scripts.for_question(index)),
                        sessions_dir=tmp_path / f"s{index}")
        state = app.sessions.new()
        answer = app.answer(question, state, on_plan=None)
        text = _visible_text(answer)
        for token in FORBIDDEN:
            assert token not in text, f"{token!r} leaked into the answer for {question!r}"
        match = TIER.search(text)
        assert match is None, f"tier lingo {match.group(0)!r} leaked into the answer for {question!r}"
