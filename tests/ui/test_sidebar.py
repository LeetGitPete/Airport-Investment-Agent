"""Smoke tests for `sidebar.render_sidebar` via `streamlit.testing.v1.AppTest` + `FakeApp`.

The `FakeApp` instance is stashed in `st.session_state` so it survives across `AppTest` reruns (each
`.run()` re-executes the whole script from scratch; only `session_state` persists between runs).

Note on duplicate-titled chats: `st.radio` (`streamlit/elements/widgets/radio.py`) registers its widget
value as `value_type="string_value"` and deserializes a click via
`options_selector_utils.formatted_option_to_option_index`, which resolves the *formatted display label*
back to an option index — "if formatted labels are duplicated, the last one wins" (per that function's own
docstring). So two conversations that both format to "New chat" are genuinely ambiguous to a click *by
Streamlit's own protocol*, not merely to the `AppTest` harness — selecting the first of two identically
labeled options would land on the last. `sidebar._display_labels` therefore appends a short id suffix to
any title shared by more than one conversation so every on-screen label is unique; see
`test_duplicate_titles_get_unique_labels_and_select_correctly` below.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from airport_agent.ui.sidebar import _DELETE_KEY, _NEW_CHAT_KEY, _RADIO_KEY, _RENAME_BUTTON_KEY, _RENAME_KEY
from tests.ui.fake_app import FakeApp


def _sidebar_script() -> None:
    import streamlit as st

    from airport_agent.ui.sidebar import render_sidebar
    from tests.ui.fake_app import FakeApp

    if "app" not in st.session_state:
        st.session_state["app"] = FakeApp()
    render_sidebar(st.session_state["app"], st.session_state)


def _run() -> AppTest:
    at = AppTest.from_function(_sidebar_script)
    at.run()
    assert not at.exception
    return at


def _app(at: AppTest) -> FakeApp:
    return at.session_state["app"]


def test_new_chat_is_created_and_selected():
    at = _run()
    at.button(key=_NEW_CHAT_KEY).click().run()
    assert not at.exception

    app = _app(at)
    newest = app.sessions.list()[0]
    assert at.session_state["session_id"] == newest.session_id
    assert at.radio(key=_RADIO_KEY).value == newest.session_id


def test_duplicate_titles_get_unique_labels_and_select_correctly():
    at = _run()
    app = _app(at)
    # Three conversations that all default to the title "New chat".
    first = app.sessions.new()
    second = app.sessions.new()
    third = app.sessions.new()
    at.run()

    labels = at.radio(key=_RADIO_KEY).options
    assert len(labels) == len(set(labels))  # every on-screen label is unique

    for target in (first, second, third):
        at.radio(key=_RADIO_KEY).set_value(target.session_id).run()
        assert not at.exception
        assert at.session_state["session_id"] == target.session_id
        assert at.radio(key=_RADIO_KEY).value == target.session_id


def test_rename_targets_the_currently_selected_chat():
    at = _run()
    app = _app(at)
    a = app.sessions.new(title="Chat A")
    b = app.sessions.new(title="Chat B")
    at.run()

    # Select A, type a new title, but switch to B *before* clicking Rename.
    at.radio(key=_RADIO_KEY).set_value(a.session_id).run()
    at.text_input(key=_RENAME_KEY).set_value("Renamed A").run()
    at.radio(key=_RADIO_KEY).set_value(b.session_id).run()

    # Switching reset the rename box to B's own title, not the stale "Renamed A".
    assert at.text_input(key=_RENAME_KEY).value == "Chat B"

    at.text_input(key=_RENAME_KEY).set_value("Renamed B").run()
    at.button(key=_RENAME_BUTTON_KEY).click().run()

    assert app.sessions.load(b.session_id).title == "Renamed B"
    assert app.sessions.load(a.session_id).title == "Chat A"  # untouched


def test_rename_ignores_blank_title():
    at = _run()
    app = _app(at)
    a = app.sessions.new(title="Chat A")
    at.run()

    at.radio(key=_RADIO_KEY).set_value(a.session_id).run()
    at.text_input(key=_RENAME_KEY).set_value("   ").run()
    at.button(key=_RENAME_BUTTON_KEY).click().run()

    assert not at.exception
    assert app.sessions.load(a.session_id).title == "Chat A"  # unchanged


def test_delete_selects_the_newest_remaining_chat():
    at = _run()
    app = _app(at)
    older = app.sessions.new(title="Older")
    newer = app.sessions.new(title="Newer")
    at.run()

    at.radio(key=_RADIO_KEY).set_value(newer.session_id).run()
    at.button(key=_DELETE_KEY).click().run()

    assert not at.exception
    remaining_ids = {s.session_id for s in app.sessions.list()}
    assert newer.session_id not in remaining_ids
    assert at.session_state["session_id"] == older.session_id
    assert at.radio(key=_RADIO_KEY).value == older.session_id


def test_delete_ignores_a_pending_id_that_no_longer_exists():
    at = _run()
    app = _app(at)
    other = app.sessions.new(title="Other")
    at.run()

    at.radio(key=_RADIO_KEY).set_value(other.session_id).run()
    at.button(key=_DELETE_KEY).click()

    # Simulate the pending session having vanished before the deferred delete runs (e.g. deleted
    # elsewhere) — the sidebar must skip it silently rather than raise.
    app.sessions.delete(other.session_id)
    at.run()

    assert not at.exception
