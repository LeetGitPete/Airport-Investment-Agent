"""The outbound-request gate: spacing per host, verified against a fake clock."""
from __future__ import annotations

import threading

from airport_agent.data.http import DEFAULT_MIN_INTERVAL_S, INTERVAL_ENV, RequestPacer


class FakeClock:
    """A monotonic clock that only advances when something sleeps.

    `advance_on_sleep=False` freezes it, which is how simultaneous arrivals are modelled: every
    caller sees the same instant, exactly as three threads entering `wait()` together would.
    """

    def __init__(self, *, advance_on_sleep: bool = True) -> None:
        self.now = 1000.0
        self.slept: list[float] = []
        self._advance = advance_on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if self._advance:
            self.now += seconds


def _pacer(interval: float = 3.0, *, advance_on_sleep: bool = True) -> tuple[RequestPacer, FakeClock]:
    clock = FakeClock(advance_on_sleep=advance_on_sleep)
    return RequestPacer(interval, monotonic=clock.monotonic, sleep=clock.sleep), clock


def test_the_first_call_to_a_host_never_waits():
    pacer, clock = _pacer()
    assert pacer.wait("https://www.faa.gov/airports/aip/grant_histories") == 0.0
    assert clock.slept == []


def test_a_second_call_to_the_same_host_waits_the_full_interval():
    pacer, clock = _pacer()
    pacer.wait("https://www.faa.gov/a")
    assert pacer.wait("https://www.faa.gov/b") == 3.0  # different path, same operator
    assert clock.slept == [3.0]


def test_a_call_to_another_host_is_not_delayed_behind_the_first():
    # pacing is per-operator: waiting on FAA because we just called BTS would be pointless
    pacer, clock = _pacer()
    pacer.wait("https://transtats.bts.gov/x.zip")
    assert pacer.wait("https://nasstatus.faa.gov/api/airport-status-information") == 0.0
    assert clock.slept == []


def test_time_already_elapsed_counts_towards_the_interval():
    pacer, clock = _pacer()
    pacer.wait("https://www.faa.gov/a")
    clock.now += 2.0  # two seconds of work happened between requests
    assert pacer.wait("https://www.faa.gov/b") == 1.0  # only the remainder is slept


def test_ten_sequential_downloads_are_spaced_not_batched():
    # the shape of a real AIP refresh: ten fiscal-year workbooks from one host
    pacer, clock = _pacer()
    delays = [pacer.wait(f"https://www.faa.gov/FY_{year}_AIP_Grants.xlsx") for year in range(2016, 2026)]
    assert delays[0] == 0.0 and all(d == 3.0 for d in delays[1:])
    assert clock.now == 1000.0 + 9 * 3.0


def test_concurrent_callers_queue_instead_of_all_measuring_the_same_stamp():
    # Streamlit sessions asking for live status at the same moment must not all go straight out.
    # The clock is frozen so every thread genuinely sees one instant: the spacing can then only
    # come from the reservation, and the expected result does not depend on thread interleaving.
    pacer, _clock = _pacer(advance_on_sleep=False)
    results: list[float] = []
    lock = threading.Lock()

    def call() -> None:
        delay = pacer.wait("https://nasstatus.faa.gov/api/airport-status-information")
        with lock:
            results.append(delay)

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [0.0, 3.0, 6.0]  # each one queues behind the last, none skipped


def test_pacing_can_be_switched_off_by_configuration(monkeypatch):
    monkeypatch.setenv(INTERVAL_ENV, "0")
    pacer = RequestPacer()
    url = "https://www.faa.gov/a"
    assert pacer.wait(url) == 0.0 and pacer.wait(url) == 0.0


def test_a_nonsense_interval_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(INTERVAL_ENV, "not a number")
    assert RequestPacer().min_interval_s == DEFAULT_MIN_INTERVAL_S


def test_the_interval_is_read_at_call_time_not_import_time(monkeypatch):
    pacer = RequestPacer()
    monkeypatch.setenv(INTERVAL_ENV, "5")
    assert pacer.min_interval_s == 5.0
