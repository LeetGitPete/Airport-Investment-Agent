from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.ui.fake_app import make_answer

APP = "src/airport_agent/ui/streamlit_app.py"


@pytest.fixture(autouse=True)
def _factory(monkeypatch):
    # `st.cache_resource` (used for the `App` object) is a process-global cache, not scoped to a single
    # `AppTest` script run — without clearing it, one test's fake `App`/sessions would leak into the next.
    st.cache_resource.clear()
    monkeypatch.setenv("AIRPORT_AGENT_APP_FACTORY", "tests.ui.fake_app:make_app")
    yield
    st.cache_resource.clear()


def _boot():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_boots_with_sidebar_sections():
    at = _boot()
    texts = " ".join(m.value for m in at.sidebar.markdown) + " " + " ".join(c.value for c in at.sidebar.caption)
    assert "gemini" in texts and "configured" in texts
    assert any("New chat" in b.label for b in at.sidebar.button)


@pytest.mark.parametrize("q,kind", [("Which airports in New England are strong candidates for terminal expansion?", "rank"),
                                    ("Compare LA and Santa Ana airport congestion levels.", "compare"),
                                    ("What is the percentage of long haul flights out of Anchorage airport?", "informational"),
                                    ("What is the unmet flight demand in SFO airport and why?", "diagnose")])
def test_each_answer_kind_renders_fixed_structure(q, kind):
    at = _boot()
    at.chat_input[0].set_value(q).run()
    assert not at.exception
    answer = make_answer(kind)
    assistant_msg = at.main.chat_message[-1]
    assert assistant_msg.name == "assistant"
    first, second = assistant_msg.children[0], assistant_msg.children[1]
    assert first.type == "caption" and first.value == answer.plan_line, "plan_line caption precedes everything else"
    assert second.type == "markdown" and answer.headline in second.value, "headline follows the plan_line caption"
    assert at.main.dataframe, "evidence table rendered"
    labels = [e.label for e in at.main.expander]
    assert "Assumptions & uncertainty" in labels and "Show work" in labels
    if kind == "informational":
        assert "Analyst view" not in " ".join(h.value for h in at.main.subheader)
    else:
        assert "Analyst view" in " ".join(h.value for h in at.main.subheader)


def test_llm_error_shown_loudly_no_partial_answer():
    at = _boot()
    at.chat_input[0].set_value("please error").run()
    assert at.main.error and "LLM provider error" in at.main.error[0].value
    assert not at.main.dataframe


def test_new_chat_and_switch_keeps_histories_separate():
    at = _boot()
    at.chat_input[0].set_value("rank NE").run()
    n_before = len(at.main.dataframe)
    assert n_before > 0
    at.sidebar.button[0].click().run()  # New chat
    assert len(at.main.dataframe) == 0
    at.sidebar.radio[0].set_value(at.sidebar.radio[0].options[-1]).run()
    assert len(at.main.dataframe) == n_before


def test_defaults_are_forwarded():
    from tests.ui import fake_app
    at = _boot()
    at.sidebar.selectbox[0].set_value("10y").run()
    at.chat_input[0].set_value("rank NE").run()
    assert fake_app.LAST_APP.last_defaults["horizon"] == "10y"


def test_boot_failure_shows_error_and_no_sidebar(monkeypatch):
    monkeypatch.setenv("AIRPORT_AGENT_APP_FACTORY", "tests.ui.fake_app:make_broken_app")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    assert at.main.error and "app factory boom" in at.main.error[0].value
    assert not at.sidebar.markdown and not at.sidebar.button


def test_sidebar_sample_question_renders_answer():
    at = _boot()
    sample_button = next(b for b in at.sidebar.button if b.key and b.key.startswith("sidebar_sample_"))
    sample_button.click().run()
    assert not at.exception
    assert at.main.dataframe, "clicking a sample question produces a rendered answer"


def test_followup_chip_click_produces_second_answer():
    at = _boot()
    at.chat_input[0].set_value("rank NE").run()
    n_messages_after_first = len(at.main.chat_message)
    followup_button = next(b for b in at.button if b.key and "-fu-" in b.key)
    followup_button.click().run()
    assert not at.exception
    assert len(at.main.chat_message) == n_messages_after_first + 2, "a second user+assistant turn was added"
