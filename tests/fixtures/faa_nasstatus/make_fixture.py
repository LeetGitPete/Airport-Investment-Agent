"""Recapture the FAA NAS Status fixtures (needs network; not run by tests).

Usage: uv run python tests/fixtures/faa_nasstatus/make_fixture.py

Writes the live feed and the FAA's DTD verbatim next to this file. The feed is a live
snapshot, so a recapture will contain whatever delays/closures are current at that moment;
`tests/data/test_faa_nasstatus.py` asserts against the committed 2026-08-15 capture and
must be updated together with it.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from airport_agent.data.adapters.faa_nasstatus import DTD_URL, NASSTATUS_URL

HERE = Path(__file__).resolve().parent


def main() -> None:
    for url, name in ((NASSTATUS_URL, "sample.xml"), (DTD_URL, "AirportStatus.dtd")):
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        (HERE / name).write_text(response.text, encoding="utf-8")
        print(f"wrote {name}: {len(response.text)} bytes")


if __name__ == "__main__":
    main()
