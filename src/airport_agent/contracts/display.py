"""User-facing display names shared across layers (pure data — no logic, no I/O).

Lives in contracts so `scoring/` (which may import only contracts and itself) can write
user-legible explanations without reaching into `agent/`. `agent/tables.py` re-exports these
under their historical names. Human decision 2026-08-16 (known-limitations row 66).
"""
from __future__ import annotations

#: User-facing source names. Fallback is the raw id, so an unmapped source stays visible.
SOURCE_DISPLAY: dict[str, str] = {
    "ourairports": "OurAirports",
    "faa_taf": "FAA Terminal Area Forecast",
    "faa_npias": "FAA NPIAS 2025-2029",
    "bts_socrata": "BTS T-100 airport totals",
    "bts_t100": "BTS T-100 route segments",
    "bts_otp": "BTS On-Time Performance",
    "bts_delay_cause": "BTS delay causes",
    "census_cbsa": "Census metro population",
    "bea_msa": "BEA metro GDP",
    "faa_cats": "FAA airport financials (Form 127)",
    "faa_aip": "FAA AIP grants",
    "faa_nasstatus": "FAA NAS Status (live)",
    "curated": "Curated airport facts",
    "bts_db1b": "BTS DB1B O&D survey",
}

#: Peer-group prose ("percentiles among ...").
PEER_GROUP_DISPLAY: dict[str, str] = {
    "hub_class": "airports of the same hub size",
    "region": "airports in the same FAA region",
    "all": "all airports",
}


def source_name(source_id: str | None) -> str:
    """User-facing name for a source id (the id itself when unmapped or empty)."""
    return SOURCE_DISPLAY.get(source_id or "", source_id or "")


def peer_label(peer_group: str | None) -> str:
    return PEER_GROUP_DISPLAY.get(peer_group or "hub_class", peer_group or "peers")
