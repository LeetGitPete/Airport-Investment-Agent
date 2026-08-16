"""FAA NAS Status live adapter — current ground stops, ground delays and closures.

Source: `https://nasstatus.faa.gov/api/airport-status-information` (XML, no auth, ~3 KB;
docs/research/2026-08-15-us-aviation-data-sources.md Tier 2). The sibling `/ground-stops`
and `/ground-delays` endpoints 503, so this one document is the whole live picture.

Structure per the FAA's own DTD (v2.2, captured at `tests/fixtures/faa_nasstatus/
AirportStatus.dtd`)::

    AIRPORT_STATUS_INFORMATION (Update_Time, Dtd_File, Delay_type*)
    Delay_type (Name, (CTOP_List | Airport_Closure_List | Ground_Stop_List |
                       Ground_Delay_List | Airspace_Flow_List | Arrival_Departure_Delay_List))

Every per-airport item carries an `ARPT` element; the *list* element decides what it means
(`Ground_Stop_List/Program`, `Ground_Delay_List/Ground_Delay`, `Airport_Closure_List/Airport`,
`Arrival_Departure_Delay_List/Delay`). The parser therefore keys off the list tag and walks
items generically, so an item-level tag change upstream cannot silently mislabel a delay.
`CTOP_List` / `Airspace_Flow_List` describe airspace flow programs, not airports, and are
skipped.

**Caveat carried into the output:** `Airport_Closure_List` mixes full closures (PVD's
overnight curfew in the committed fixture) with partial NOTAM restrictions (LAX "CLSD TO
NON SKED TRANSIENT GA ACFT"). A bare `closure=True` would read as "the airport is shut", so
every closure's verbatim NOTAM text is also appended to `delay_programs`; consumers must
show the text alongside the flag.

Degradation is deliberate and total: any timeout, transport error, non-2xx or unparseable
body returns `None`, and the caller adds the "live status unavailable — snapshot only" data
quality note (design 03). Live status never fails a request and is never cached.
"""
from __future__ import annotations

from typing import Literal
from xml.etree import ElementTree

import httpx

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.http import PACER, claim_live_call

NASSTATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
DTD_URL = "https://nasstatus.faa.gov/AirportStatus.dtd"

#: Seconds. Live status is a nicety: it must never hold up an answer.
DEFAULT_TIMEOUT = 3.0

#: List element → (kind, human prefix). Airspace-level lists are absent on purpose.
LIST_KINDS: dict[str, tuple[str, str]] = {
    "Ground_Stop_List": ("ground_stop", "Ground stop"),
    "Ground_Delay_List": ("delay", "Ground delay program"),
    "Arrival_Departure_Delay_List": ("delay", "Delay"),
    "Airport_Closure_List": ("closure", "Airport closure"),
}


def _text(element: ElementTree.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _describe(kind: str, prefix: str, item: ElementTree.Element) -> str:
    """Render one item as the human-readable string `LiveStatus.delay_programs` holds."""
    reason = _text(item, "Reason")
    if kind == "ground_stop":
        until = _text(item, "End_Time")
        detail = f" until {until}" if until else ""
        return f"{prefix}: {reason}{detail}".strip()
    if kind == "closure":
        reopen = _text(item, "Reopen")
        detail = f" (reopens {reopen})" if reopen else ""
        return f"{prefix}: {reason}{detail}".strip()
    if item.tag == "Ground_Delay":
        avg, maximum = _text(item, "Avg"), _text(item, "Max")
        window = ", ".join(part for part in (f"avg {avg}" if avg else "", f"max {maximum}" if maximum else "") if part)
        return f"{prefix}: {reason}" + (f" ({window})" if window else "")
    parts = []
    for leg in item.findall("Arrival_Departure"):
        low, high, trend = _text(leg, "Min"), _text(leg, "Max"), _text(leg, "Trend")
        span = f"{low} to {high}" if low and high else low or high
        label = leg.get("Type", "Delay")
        parts.append(f"{label} delay {span}" + (f", {trend.lower()}" if trend else ""))
    detail = "; ".join(parts)
    return f"{detail}: {reason}" if detail else f"{prefix}: {reason}"


def parse_status(xml: str | bytes) -> dict[str, dict]:
    """Parse the NAS Status document into `{iata: {delay_programs, ground_stop, closure}}`.

    Only airports the feed actually names appear; everything else is "nothing to report".
    Raises `ElementTree.ParseError` on a malformed document (`fetch_status` turns that into
    `None`).
    """
    root = ElementTree.fromstring(xml) if isinstance(xml, str) else ElementTree.fromstring(xml.decode("utf-8"))
    status: dict[str, dict] = {}
    for delay_type in root.findall("Delay_type"):
        for list_tag, (kind, prefix) in LIST_KINDS.items():
            for item_list in delay_type.findall(list_tag):
                for item in item_list:
                    arpt = _text(item, "ARPT")
                    if not arpt:
                        continue
                    entry = status.setdefault(
                        arpt, {"delay_programs": [], "ground_stop": False, "closure": False}
                    )
                    entry["delay_programs"].append(_describe(kind, prefix, item))
                    if kind == "ground_stop":
                        entry["ground_stop"] = True
                    elif kind == "closure":
                        entry["closure"] = True
    return status


def parse_update_time(xml: str) -> str | None:
    """Return the feed's own `Update_Time` (e.g. "Sat Aug 15 19:38:46 2026 GMT"), if present."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    return _text(root, "Update_Time") or None


@register
class FaaNasStatusLiveAdapter:
    """Read the live FAA NAS Status feed; return `None` rather than fail a request."""

    id: str = "faa_nasstatus"
    kind: Literal["bulk", "live"] = "live"

    def __init__(self) -> None:
        self.update_time: str | None = None

    def fetch_status(
        self, *, timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None
    ) -> dict[str, dict] | None:
        """Return `{iata: {delay_programs, ground_stop, closure}}`, or `None` if unavailable.

        `None` means "unknown", never "no delays": the caller must say so (design 03's
        "live status unavailable — snapshot only" note). There is no bulk `fetch`/`normalize`
        here — a live source is read at question time and never written to the snapshot.
        """
        # QA task 20: the per-turn ceiling is checked BEFORE the pacer — a refused call must cost
        # nothing, not three seconds of sleeping. Returning None is the documented "unknown" answer,
        # so the caller degrades to snapshot data with provenance that no longer claims a live read.
        if not claim_live_call():
            return None
        owns_client = client is None
        http_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        # QA task 17: the one live endpoint we read per question, and the easiest one to get blocked
        # on. Paced through the same process-wide gate as the bulk downloads; still never cached, so
        # the status quoted is always what the FAA is serving right now.
        PACER.wait(NASSTATUS_URL)
        try:
            response = http_client.get(NASSTATUS_URL, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            body = response.text
            status = parse_status(body)
        except (httpx.HTTPError, ElementTree.ParseError, ValueError):
            return None
        finally:
            if owns_client:
                http_client.close()
        self.update_time = parse_update_time(body)
        return status

    def vintage(self) -> SourceVintage:
        """Vintage of the last successful read — the feed's own `Update_Time`."""
        return SourceVintage(
            source_id=self.id,
            description=(
                "FAA NAS Status — live ground stops, ground delay programs and airport "
                "closure NOTAMs (closures include partial NOTAM restrictions; read the text)"
            ),
            period_start=None,
            period_end=None,
            fetched_at=self.update_time,
            url=NASSTATUS_URL,
        )
