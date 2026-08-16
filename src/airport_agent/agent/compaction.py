"""Compaction of conversation history into `SessionState.summary` (design 03 §memory, contracts-v3).

Every EVERY_TURNS answers, the turns that have fallen out of the verbatim window (`history.KEEP_VERBATIM`)
are folded into the running summary by one LLM call. The summary is capped at MAX_CHARS: a reply over
the cap gets ONE retry carrying exactly "summary is X chars, only Y chars are allowed"; over the cap
again, it is truncated to Y at a sentence boundary — silently (a log line, nothing to the Concierge,
nothing in any answer). A provider error keeps the previous summary and tries again at the next due
turn: compaction never fails a user turn.

It runs in the BACKGROUND, between turns: `schedule()` is called as an answer completes, and only the
LLM call runs on the worker — the digests are taken on the calling thread and the result is applied
by `collect()` at the start of the NEXT turn, which blocks on the pending call. So the session has one
writer (the turn), the user's next message is only ever planned against a settled summary, and a crash
mid-compaction loses nothing (the next due turn recompacts the same turns).
"""
from __future__ import annotations

import logging
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass

from airport_agent.agent.history import turn_digest, turns, turns_to_fold
from airport_agent.contracts import LLMClient, LLMError, SessionState

log = logging.getLogger(__name__)

MAX_CHARS = 1500
EVERY_TURNS = 2
RETRY_TEMPLATE = "summary is {actual} chars, only {allowed} chars are allowed"

SYSTEM_PROMPT = (
    "You maintain the running summary of a conversation between an analyst and an airport investment "
    "intelligence agent (US airports, capacity/terminal expansion). You are given the current summary "
    "and the digests of the turns that must now be folded into it. Rewrite the summary so it covers "
    "everything so far. Keep, in this order of priority: the airports/regions discussed; findings with "
    "their key numbers (scores, ranks, values as given — never recompute); presets, horizons and "
    "conventions used; open threads or questions the user seemed to be building towards. Drop "
    "pleasantries and repetition. Plain text, no headings, no bullets, no code fences. "
    "At most {max_chars} characters."
)


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    through_turn: int


def truncate_at_sentence(text: str, limit: int) -> str:
    """Cut to `limit`, preferring the last sentence end past 60% of the limit; else hard cut."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for mark in (". ", "; ", ", "):
        cut = head.rfind(mark)
        if cut >= int(limit * 0.6):
            return head[: cut + 1].rstrip()
    return head.rstrip()


class Compactor:
    """Owns the LLM call, the retry rule and the per-session pending futures."""

    def __init__(self, llm: LLMClient, *, max_chars: int = MAX_CHARS, every: int = EVERY_TURNS,
                 executor: Executor | None = None) -> None:
        self.llm = llm
        self.max_chars = max_chars
        self.every = every
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="compaction")
        self._pending: dict[str, Future[CompactionResult]] = {}

    # the rule

    def due(self, state: SessionState) -> bool:
        """After every `every`-th answer, when there is something to fold."""
        n = len(turns(state))
        return n > 0 and n % self.every == 0 and bool(turns_to_fold(state))

    # the call (synchronous; runs on the worker)

    def compact(self, summary: str, digests: list[str], through_turn: int) -> CompactionResult:
        """One call, one bounded retry, then a silent truncation. Raises LLMError only if the provider fails."""
        user = ("CURRENT SUMMARY:\n" + (summary or "(none yet)") + "\n\nTURNS TO FOLD IN:\n"
                + "\n".join(digests))
        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(max_chars=self.max_chars)},
                    {"role": "user", "content": user}]
        text = self.llm.chat(messages=messages, temperature=0.1).text.strip()
        if len(text) > self.max_chars:
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": RETRY_TEMPLATE.format(actual=len(text),
                                                                               allowed=self.max_chars)})
            text = self.llm.chat(messages=messages, temperature=0.1).text.strip()
        if len(text) > self.max_chars:
            log.warning("compaction summary still %d chars after retry; truncated to %d",
                        len(text), self.max_chars)
            text = truncate_at_sentence(text, self.max_chars)
        return CompactionResult(summary=text, through_turn=through_turn)

    # background plumbing

    def schedule(self, state: SessionState) -> bool:
        """If due, snapshot the digests now and start the LLM call in the background. Returns whether
        anything was scheduled. A previous pending call for the session is left to finish first."""
        if not self.due(state) or state.session_id in self._pending:
            return False
        folds = turns_to_fold(state)
        digests = [turn_digest(t) for t in folds]
        through = folds[-1].number
        summary = state.summary
        self._pending[state.session_id] = self._executor.submit(self.compact, summary, digests, through)
        return True

    def collect(self, state: SessionState) -> bool:
        """Block on the session's pending compaction (if any) and apply it. Returns whether the
        summary changed. Provider errors are logged and dropped — the old summary stands."""
        future = self._pending.pop(state.session_id, None)
        if future is None:
            return False
        try:
            result = future.result()
        except LLMError as exc:
            log.warning("compaction skipped for %s: %s", state.session_id, exc)
            return False
        if result.through_turn <= state.summary_through_turn:
            return False
        state.summary = result.summary
        state.summary_through_turn = result.through_turn
        return True

    def pending(self, session_id: str) -> bool:
        return session_id in self._pending
