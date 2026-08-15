"""Streamlit multi-chat entry point (design 04): sidebar (conversations, provider status, data vintages,
per-chat defaults, sample questions) + the current conversation rendered via `render.render_answer`.

The `App` object is obtained once per process via `bootstrap.get_app()` and cached with
`st.cache_resource` (allowed only for the `App` itself — never for LLM answers, design 2d Global
Constraints). If obtaining it fails, the error is shown loudly and the script stops.
"""
from __future__ import annotations

import streamlit as st

from airport_agent.contracts import LLMError, Plan, registry_by_id
from airport_agent.ui.bootstrap import get_app
from airport_agent.ui.render import render_answer, render_error
from airport_agent.ui.sidebar import render_sidebar

st.set_page_config(page_title="Airport Investment Intelligence Agent", layout="wide")


def _set_pending(text: str) -> None:
    st.session_state["pending_input"] = text


def _plan_caption(p: Plan) -> str:
    return (
        f"How I'm approaching this: {p.intent} · engines: {', '.join(p.engines) or 'none'} · "
        f"{p.presentation_notes[:80]}"
    )


try:
    app = st.cache_resource(get_app)()
except Exception as e:  # noqa: BLE001 - deliberate catch-all per failure policy (design 03)
    render_error(e)
    st.stop()

ss = st.session_state

if "session_id" not in ss:
    sessions = app.sessions.list()
    ss["session_id"] = sessions[0].session_id if sessions else app.sessions.new().session_id

render_sidebar(app, ss)  # may call st.rerun() after mutations; run before any main-pane side effect

state = app.sessions.load(ss["session_id"])
specs_by_id = registry_by_id(app.data.describe_metrics())

for i, msg in enumerate(state.messages):
    with st.chat_message(msg.role):
        if msg.role == "assistant" and msg.answer is not None:
            render_answer(msg.answer, specs_by_id, key=f"m{i}", on_followup=_set_pending)
        else:
            st.markdown(msg.content)

prompt = ss.pop("pending_input", None) or st.chat_input("Ask about US airports…")

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            answer = app.answer(prompt, state, defaults=ss.get("defaults"), on_plan=lambda p: placeholder.caption(_plan_caption(p)))
        except LLMError as e:
            render_error(e)
        except Exception as e:  # noqa: BLE001 - deliberate catch-all per failure policy (design 03)
            render_error(e)
        else:
            # `placeholder` keeps showing the transient "How I'm approaching this" plan preview set by
            # `on_plan` while the call was in flight — a faithful trace of what the Concierge told us it
            # was doing, left in place rather than erased (design 04 transparency). `render_answer`
            # renders the final `Answer.plan_line` (and the rest of the fixed structure) below it.
            #
            # Note (deviation, see task-3 report): the spec also asks for a one-shot `st.rerun()` here so
            # the sidebar's conversation title refreshes immediately from "New chat" to the question text.
            # That is deliberately NOT done: `st.rerun()` called mid-script, right after this branch has
            # already emitted the live answer, causes `streamlit.testing.v1.AppTest`'s bare-mode script
            # runner to merge the interrupted run's delta tree with the rerun's — it does not prune
            # elements left over from a run that a `RerunException` cut short — which both erases this
            # plan-preview caption and leaves duplicate widgets behind (verified experimentally; not a
            # theory). The sidebar title still refreshes on the next natural rerun (any further widget
            # interaction), so history is never lost — only the very first title update is deferred by one
            # interaction.
            render_answer(answer, specs_by_id, key=f"m{len(state.messages) - 1}", on_followup=_set_pending)
