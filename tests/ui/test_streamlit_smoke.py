from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

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
    texts = " ".join(m.value for m in at.sidebar.markdown) + " ".join(c.value for c in at.sidebar.caption)
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
    body = " ".join(m.value for m in at.main.markdown) + " ".join(c.value for c in at.main.caption)
    assert "How I'm approaching this" in body
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
    at.sidebar.button[0].click().run()  # New chat
    assert len(at.main.dataframe) == 0
    at.sidebar.radio[0].set_value(at.sidebar.radio[0].options[-1]).run()
    assert len(at.main.dataframe) == n_before or len(at.main.dataframe) > 0


def test_defaults_are_forwarded():
    from tests.ui import fake_app
    at = _boot()
    at.sidebar.selectbox[0].set_value("10y").run()
    at.chat_input[0].set_value("rank NE").run()
    assert fake_app.LAST_APP.last_defaults["horizon"] == "10y"
