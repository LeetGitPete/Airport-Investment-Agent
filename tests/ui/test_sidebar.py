"""Smoke tests for `sidebar.render_sidebar` via `streamlit.testing.v1.AppTest` + `FakeApp`.

The `FakeApp` instance is stashed in `st.session_state` so it survives across `AppTest` reruns (each
`.run()` re-executes the whole script from scratch; only `session_state` persists between runs).

Note on duplicate-titled chats: `AppTest`'s `Radio.set_value()` round-trips a *raw* value through
`format_func` to find its position in the widget's already-rendered (formatted) `options` list
(`streamlit.testing.v1.element_tree.Radio.index`). When two options format to the same label (e.g. two
"New chat" conversations), that reverse lookup returns the *first* match — a limitation of the test
harness's simulated click, not of `sidebar.py` (a real browser click is positional, not text-matched, so
production behavior is unaffected). `test_duplicate_titles_keep_their_own_identity` below instead seeds
`session_state` before the very first `.run()` (i.e. before the radio widget has ever been instantiated,
so there is no widget history to round-trip through) to verify id-based — not title-based — selection.
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


def _fresh(app: FakeApp, session_id: str) -> AppTest:
    """A brand-new `AppTest` landing directly on `session_id` (no prior radio interaction — avoids the
    `set_value()`/`format_func` round-trip limitation described in the module docstring)."""
    at = AppTest.from_function(_sidebar_script)
    at.session_state["app"] = app
    at.session_state["session_id"] = session_id
    at.session_state[_RADIO_KEY] = session_id
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


def test_duplicate_titles_keep_their_own_identity():
    app = FakeApp()
    # Two conversations that both default to the title "New chat" — must remain independently
    # selectable by id despite the identical on-screen label.
    first = app.sessions.new()
    second = app.sessions.new()

    at_first = _fresh(app, first.session_id)
    assert at_first.session_state["session_id"] == first.session_id
    assert at_first.radio(key=_RADIO_KEY).value == first.session_id

    at_second = _fresh(app, second.session_id)
    assert at_second.session_state["session_id"] == second.session_id
    assert at_second.radio(key=_RADIO_KEY).value == second.session_id


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
