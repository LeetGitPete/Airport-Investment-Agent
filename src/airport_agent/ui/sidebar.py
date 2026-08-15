"""Sidebar: conversations (new/switch/rename/delete), provider status, data vintages, per-chat
defaults, sample questions (design 04 §Layout — Sidebar). `app` is the `App` object (real or fake);
`ss` is `st.session_state` (passed explicitly so this module never imports `streamlit` state directly).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

HORIZON_OPTIONS = ["12m", "3y", "5y", "10y"]
PRESET_OPTIONS = ["balanced", "terminal_expansion", "congestion_relief", "market_entry"]
PEER_GROUP_OPTIONS = ["hub_class", "region", "all"]

DEFAULT_HORIZON = "5y"
DEFAULT_PRESET = "balanced"
DEFAULT_PEER_GROUP = "hub_class"


def _render_conversations(app: Any, ss: dict) -> None:
    st.subheader("Conversations")

    if st.button("New chat"):
        state = app.sessions.new()
        ss["session_id"] = state.session_id

    sessions = app.sessions.list()
    if not sessions:
        state = app.sessions.new()
        sessions = [state]
        ss["session_id"] = state.session_id

    ids = [s.session_id for s in sessions]
    if ss.get("session_id") not in ids:
        ss["session_id"] = ids[0]

    titles = [s.title for s in sessions]
    current_index = ids.index(ss["session_id"])
    selected_title = st.radio("Chats", titles, index=current_index, key="sidebar_conversations_radio")
    selected_index = titles.index(selected_title)
    ss["session_id"] = ids[selected_index]

    new_title = st.text_input("Rename", value=titles[selected_index], key="sidebar_rename_input")
    if st.button("Rename"):
        app.sessions.rename(ss["session_id"], new_title)

    if st.button("Delete"):
        app.sessions.delete(ss["session_id"])
        remaining = app.sessions.list()
        if remaining:
            ss["session_id"] = remaining[0].session_id
        else:
            state = app.sessions.new()
            ss["session_id"] = state.session_id


def _render_provider(app: Any) -> None:
    st.subheader("Provider")
    for row in app.provider_status():
        st.markdown(f"{row['name']} · {row['model']} · **{row['status']}**")
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
    with st.sidebar:
        _render_conversations(app, ss)
        st.divider()
        _render_provider(app)
        st.divider()
        _render_vintages(app)
        st.divider()
        _render_defaults(ss)
        st.divider()
        _render_samples(app, ss)
        st.divider()
        st.caption("Design: docs/DESIGN.md")
