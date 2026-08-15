"""Tests for `airport_agent.data.adapters.faa_nasstatus` — parsing and fail-soft fetching.

Assertions run against `tests/fixtures/faa_nasstatus/sample.xml`, an unedited capture of the
live feed (2026-08-15 19:38 GMT). No network: `fetch_status` is exercised through
`httpx.MockTransport`.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.faa_nasstatus import (
    NASSTATUS_URL,
    FaaNasStatusLiveAdapter,
    parse_status,
)

# Shaped from the FAA's own DTD (tests/fixtures/faa_nasstatus/AirportStatus.dtd v2.2):
# `Ground_Stop_List (Program*)`, `Program (ARPT, Reason, End_Time)`. The live capture
# happened to contain no ground stop, so this structural snippet covers that branch.
GROUND_STOP_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Aug 15 19:38:46 2026 GMT</Update_Time>
<Dtd_File>http://www.fly.faa.gov/AirportStatus.dtd</Dtd_File>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>EWR</ARPT>
<Reason>weather / thunderstorms</Reason><End_Time>Aug 15 at 21:00 UTC.</End_Time></Program>
</Ground_Stop_List></Delay_type></AIRPORT_STATUS_INFORMATION>"""


@pytest.fixture
def sample_xml(fixtures_dir: Path) -> str:
    return (fixtures_dir / "faa_nasstatus" / "sample.xml").read_text(encoding="utf-8")


@pytest.fixture
def status(sample_xml: str) -> dict[str, dict]:
    return parse_status(sample_xml)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["faa_nasstatus"] is FaaNasStatusLiveAdapter

    def test_kind_is_live(self) -> None:
        assert FaaNasStatusLiveAdapter.kind == "live"


class TestParseSample:
    def test_only_airports_named_in_the_feed_are_present(self, status: dict[str, dict]) -> None:
        assert set(status) == {"SFO", "PVD", "CYS", "LAX", "HNL", "PHL", "LAS", "ASE", "SAN"}
        assert "BOS" not in status

    def test_every_entry_has_the_three_keys(self, status: dict[str, dict]) -> None:
        for entry in status.values():
            assert set(entry) == {"delay_programs", "ground_stop", "closure"}
            assert isinstance(entry["delay_programs"], list)

    def test_ground_delay_program_is_reported(self, status: dict[str, dict]) -> None:
        programs = status["SFO"]["delay_programs"]
        assert any(p.startswith("Ground delay program:") and "low ceilings" in p for p in programs)
        assert any("36 minutes" in p for p in programs)

    def test_general_departure_delay_is_reported(self, status: dict[str, dict]) -> None:
        programs = status["SFO"]["delay_programs"]
        assert any("Departure delay" in p and "RWY:Construction" in p for p in programs)

    def test_delayed_airport_has_no_stop_or_closure(self, status: dict[str, dict]) -> None:
        assert status["SFO"]["ground_stop"] is False
        assert status["SFO"]["closure"] is False

    def test_closure_sets_the_flag(self, status: dict[str, dict]) -> None:
        assert status["PVD"]["closure"] is True

    def test_closure_reason_is_carried_verbatim(self, status: dict[str, dict]) -> None:
        # The flag alone is ambiguous: LAX's NOTAM is a partial closure, not a shut airport.
        assert status["LAX"]["closure"] is True
        assert any("CLSD TO NON SKED TRANSIENT GA ACFT" in p for p in status["LAX"]["delay_programs"])


class TestParseGroundStop:
    def test_ground_stop_sets_the_flag(self) -> None:
        entry = parse_status(GROUND_STOP_XML)["EWR"]
        assert entry["ground_stop"] is True
        assert any("Ground stop:" in p and "thunderstorms" in p for p in entry["delay_programs"])


class TestFetchStatus:
    def test_returns_the_parsed_feed(self, sample_xml: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == NASSTATUS_URL
            return httpx.Response(200, text=sample_xml)

        with _client(handler) as client:
            status = FaaNasStatusLiveAdapter().fetch_status(client=client)
        assert status is not None
        assert status["SFO"]["delay_programs"]

    def test_timeout_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with _client(handler) as client:
            assert FaaNasStatusLiveAdapter().fetch_status(client=client) is None

    def test_connect_error_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        with _client(handler) as client:
            assert FaaNasStatusLiveAdapter().fetch_status(client=client) is None

    def test_http_error_returns_none(self) -> None:
        with _client(lambda request: httpx.Response(503, text="unavailable")) as client:
            assert FaaNasStatusLiveAdapter().fetch_status(client=client) is None

    def test_malformed_xml_returns_none(self) -> None:
        with _client(lambda request: httpx.Response(200, text="<AIRPORT_STATUS")) as client:
            assert FaaNasStatusLiveAdapter().fetch_status(client=client) is None

    def test_default_timeout_is_three_seconds(self) -> None:
        assert FaaNasStatusLiveAdapter().fetch_status.__defaults__ is None  # keyword-only
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["timeout"] = request.extensions.get("timeout")
            return httpx.Response(200, text="<AIRPORT_STATUS_INFORMATION></AIRPORT_STATUS_INFORMATION>")

        with _client(handler) as client:
            FaaNasStatusLiveAdapter().fetch_status(client=client)
        assert seen["timeout"] == {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0}


class TestVintage:
    def test_vintage_uses_the_feeds_update_time(self, sample_xml: str) -> None:
        adapter = FaaNasStatusLiveAdapter()
        with _client(lambda request: httpx.Response(200, text=sample_xml)) as client:
            adapter.fetch_status(client=client)
        vintage = adapter.vintage()
        assert isinstance(vintage, SourceVintage)
        assert vintage.source_id == "faa_nasstatus"
        assert vintage.url == NASSTATUS_URL
        assert adapter.update_time == "Sat Aug 15 19:38:46 2026 GMT"


@pytest.mark.network
class TestLiveFeed:
    def test_live_feed_parses(self) -> None:
        status = FaaNasStatusLiveAdapter().fetch_status()
        assert status is not None
        assert all(set(entry) == {"delay_programs", "ground_stop", "closure"} for entry in status.values())
