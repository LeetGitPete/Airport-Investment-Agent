"""Sidebar: conversations (new/switch/rename/delete), provider status, data vintages, per-chat
defaults, sample questions (design 04 §Layout — Sidebar). `app` is the `App` object (real or fake);
`ss` is `st.session_state` (passed explicitly so this module never imports `streamlit` state directly).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd
import streamlit as st

HORIZON_OPTIONS = ["12m", "3y", "5y", "10y"]
PRESET_OPTIONS = ["balanced", "terminal_expansion", "congestion_relief", "market_entry"]
PEER_GROUP_OPTIONS = ["hub_class", "region", "all"]

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


def _render_provider(app: Any) -> None:
    st.subheader("Provider")
    for row in app.provider_status():
        name = row.get("name", "?")
        model = row.get("model", "?")
        status = row.get("status", "?")
        st.markdown(f"{name} · {model} · **{status}**")
        st.caption(row.get("detail", ""))


def _render_vintages(app: Any) -> None:
    st.subheader("Data vintages")
    vintages = app.data.source_vintages()
    df = pd.DataFrame(
        [{"source_id": v.source_id, "period_end": v.period_end, "fetched_at": v.fetched_at} for v in vintages],
        columns=["source_id", "period_end", "fetched_at"],
    )
    st.dataframe(df, hide_index=True)
    st.caption("staleness hint: refresh with `python -m airport_agent.data refresh --check`")


def _render_defaults(ss: dict) -> None:
    st.subheader("Defaults for this chat")
    current = ss.get("defaults", {})
    horizon = st.selectbox(
        "Horizon", HORIZON_OPTIONS,
        index=HORIZON_OPTIONS.index(current.get("horizon", DEFAULT_HORIZON)), key="sidebar_horizon",
    )
    preset = st.selectbox(
        "Scoring preset", PRESET_OPTIONS,
        index=PRESET_OPTIONS.index(current.get("scoring_preset", DEFAULT_PRESET)), key="sidebar_preset",
    )
    peer_group = st.selectbox(
        "Peer group", PEER_GROUP_OPTIONS,
        index=PEER_GROUP_OPTIONS.index(current.get("peer_group", DEFAULT_PEER_GROUP)), key="sidebar_peer_group",
    )
    ss["defaults"] = {"horizon": horizon, "scoring_preset": preset, "peer_group": peer_group}


def _render_samples(app: Any, ss: dict) -> None:
    st.subheader("Sample questions")
    for i, question in enumerate(app.sample_questions()):
        if st.button(question, key=f"sidebar_sample_{i}"):
            ss["pending_input"] = question


def render_sidebar(app: Any, ss: dict) -> None:
    # QA task 11 (2026-08-16): provider status, data vintages and the per-chat defaults widgets
    # are gone from the sidebar. The defaults still apply — set silently here, overridable by
    # asking (e.g. "over 10 years", "use the market entry preset"); vintages stay visible per
    # answer ("data as of") and via the list_sources tool.
    ss.setdefault("defaults", {"horizon": DEFAULT_HORIZON, "scoring_preset": DEFAULT_PRESET,
                               "peer_group": DEFAULT_PEER_GROUP})
    with st.sidebar:
        _render_conversations(app, ss)
        st.divider()
        _render_samples(app, ss)
        st.divider()
        st.caption("Design: docs/DESIGN.md")
