"""The single gate every outbound HTTP request passes through.

Why this exists: nothing in the data layer paced its requests. A refresh pulls dozens of files
back-to-back (ten AIP workbooks, one T-100 and one OTP archive per month of the trailing window), and
the live FAA NAS Status endpoint is read once per user question with no cache at all. Public
government endpoints are the kind that answer a burst with a block, and a blocked host is not
something a demo recovers from.

So every request waits until at least `min_interval_s` has passed since the last request *to the same
host*. Per-host, because pacing SFO-bound calls behind BTS-bound ones would be pointless politeness;
the ban risk is per-operator. The gate is a hard floor on spacing, never a budget or a queue: it
delays, it never drops a request, and it never retries one.

What this deliberately is NOT: a cache. The human decision on 2026-08-16 was "pace only, no cache",
so a repeated question about the same airport still reaches the FAA — design 03's "live status is
never cached" stays literally true, and an answer can never quote a stale operational status as
current. Pacing changes when a request happens, never whether the answer is fresh.

Thread-safe because Streamlit serves each session from its own thread and two users can ask about
live status at the same moment.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

import httpx

#: Seconds between two requests to the same host. Chosen to be unmistakably polite rather than
#: tuned — no published rate limit exists for these endpoints, so the floor is a judgement call.
DEFAULT_MIN_INTERVAL_S = 3.0
#: Escape hatch for a slow refresh on a trusted network, and how the test suite disables pacing.
INTERVAL_ENV = "AIRPORT_AGENT_MIN_REQUEST_INTERVAL_S"


def _configured_interval() -> float:
    raw = os.environ.get(INTERVAL_ENV)
    if raw is None:
        return DEFAULT_MIN_INTERVAL_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_MIN_INTERVAL_S


class RequestPacer:
    """Enforces a minimum interval between requests to each host.

    `monotonic` and `sleep` are injectable so the behaviour can be tested against a fake clock
    instead of by actually waiting three seconds.
    """

    def __init__(self, min_interval_s: float | None = None, *,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._explicit = min_interval_s
        self._monotonic = monotonic
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def min_interval_s(self) -> float:
        """Read at call time, so the env var can be set after import (tests, CLI runs)."""
        return self._explicit if self._explicit is not None else _configured_interval()

    def wait(self, url: str) -> float:
        """Block until this host may be called again. Returns the seconds actually slept.

        The stamp is written before sleeping and again after, so concurrent callers to one host
        queue up behind each other instead of all measuring against the same stale timestamp.
        """
        interval = self.min_interval_s
        if interval <= 0:
            return 0.0
        host = httpx.URL(url).host or url
        with self._lock:
            now = self._monotonic()
            earliest = self._last.get(host)
            start = now if earliest is None else max(now, earliest + interval)
            self._last[host] = start
            delay = start - now
        if delay > 0:
            self._sleep(delay)
        return delay

    def reset(self) -> None:
        """Forget every host's last-call time (test hook; never used in a running app)."""
        with self._lock:
            self._last.clear()


#: The process-wide gate. Both the bulk `download()` helper and the live FAA reader use this one
#: instance, so a refresh running while someone asks a live question still respects the floor.
PACER = RequestPacer()
