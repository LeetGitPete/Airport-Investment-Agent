"""Sidebar: conversations (new/switch/rename/delete) and the sample questions (design 04 §Layout).

`app` is the `App` object (real or fake); `ss` is `st.session_state`, passed explicitly so this module
never reaches into Streamlit's state directly.

Provider status, data vintages and the per-chat default pickers are deliberately NOT rendered — see
`render_sidebar` for what replaced them.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

DEFAULT_HORIZON = "5y"
DEFAULT_PRESET = "balanced"
DEFAULT_PEER_GROUP = "hub_class"


_RADIO_KEY = "sidebar_conversations_radio"
_RENAME_KEY = "sidebar_rename_input"
_NEW_CHAT_KEY = "sidebar_new_chat"
_RENAME_BUTTON_KEY = "sidebar_rename_button"
_DELETE_KEY = "sidebar_delete"
_PENDING_DELETE_KEY = "_sidebar_pending_delete"


def _select(ss: dict, session_id: str) -> None:
    """Point both the logical selection and the radio widget's own stored value at `session_id`. Must
    happen *before* the radio widget is instantiated in the current run — Streamlit raises if a widget's
    session_state key is written to after that widget has already been instantiated this run."""
    ss["session_id"] = session_id
    ss[_RADIO_KEY] = session_id


def _display_labels(sessions: list[Any]) -> dict[str, str]:
    """Radio display label per session id. `st.radio` deserializes a selection by looking up its
    *formatted* (displayed) label among the options — not the raw value — and when two options format
    to the same label, the last one registered wins (Streamlit's `formatted_option_to_option_index`).
    So any title shared by more than one conversation must get a unique label; disambiguate with a short
    id suffix. Titles that are already unique are shown unchanged."""
    titles = [s.title for s in sessions]
    counts = Counter(titles)
    return {
        s.session_id: (f"{s.title} · {s.session_id[:4]}" if counts[s.title] > 1 else s.title)
        for s in sessions
    }


def _render_conversations(app: Any, ss: dict) -> None:
    st.subheader("Conversations")

    # Deletion is deferred one run: the "Delete" button is rendered *after* the radio widget below, so
    # acting on it immediately would mutate the radio's session_state key after that widget has already
    # been instantiated this run (Streamlit forbids this). Instead we stash the id and act on it here, at
    # the top of the *next* run, before any widget in this function has been instantiated.
    pending_delete = ss.pop(_PENDING_DELETE_KEY, None)
    if pending_delete is not None:
        existing_ids = {s.session_id for s in app.sessions.list()}
        if pending_delete in existing_ids:
            app.sessions.delete(pending_delete)
            remaining = app.sessions.list()
            new_id = remaining[0].session_id if remaining else app.sessions.new().session_id
            _select(ss, new_id)
            ss.pop("_rename_for", None)
        # else: already gone (e.g. deleted elsewhere in the meantime) — nothing to do; the pending
        # key has already been cleared by the `pop` above.

    if st.button("New chat", key=_NEW_CHAT_KEY):
        state = app.sessions.new()
        _select(ss, state.session_id)
        st.rerun()

    sessions = app.sessions.list()
    if not sessions:
        state = app.sessions.new()
        sessions = [state]
        _select(ss, state.session_id)

    ids = [s.session_id for s in sessions]
    titles_by_id = {s.session_id: s.title for s in sessions}
    labels_by_id = _display_labels(sessions)

    if ss.get("session_id") not in ids:
        ss["session_id"] = ids[0]
    if ss.get(_RADIO_KEY) not in ids:
        ss[_RADIO_KEY] = ss["session_id"]

    # Radio options are session IDs (stable, unique); `format_func` supplies the on-screen label. Labels
    # must themselves be unique (see `_display_labels`) since Streamlit resolves a click by label, not id.
    selected_id = st.radio("Chats", ids, format_func=lambda sid: labels_by_id[sid], key=_RADIO_KEY)
    ss["session_id"] = selected_id

    # The rename box must reset to the *current* chat's title whenever the selection changes — otherwise
    # a value typed while chat A was selected gets applied to chat B after switching.
    if ss.get("_rename_for") != selected_id:
        ss[_RENAME_KEY] = titles_by_id[selected_id]
        ss["_rename_for"] = selected_id

    new_title = st.text_input("Rename", key=_RENAME_KEY)
    if st.button("Rename", key=_RENAME_BUTTON_KEY):
        if new_title.strip():
            app.sessions.rename(selected_id, new_title)
            st.rerun()

    if st.button("Delete", key=_DELETE_KEY):
        ss[_PENDING_DELETE_KEY] = selected_id
        st.rerun()


def _render_samples(app: Any, ss: dict) -> None:
    st.subheader("Sample questions")
    for i, question in enumerate(app.sample_questions()):
        if st.button(question, key=f"sidebar_sample_{i}"):
            ss["pending_input"] = question


def render_sidebar(app: Any, ss: dict) -> None:
    # Provider status, data vintages and the per-chat default pickers are not shown. The defaults
    # still apply — set silently here and overridable by asking ("over 10 years", "use the market
    # entry preset"); vintages stay visible per answer ("data as of") and via the list_sources tool.
    ss.setdefault("defaults", {"horizon": DEFAULT_HORIZON, "scoring_preset": DEFAULT_PRESET,
                               "peer_group": DEFAULT_PEER_GROUP})
    with st.sidebar:
        _render_conversations(app, ss)
        st.divider()
        _render_samples(app, ss)
        st.divider()
        st.caption("Design: docs/DESIGN.md")
