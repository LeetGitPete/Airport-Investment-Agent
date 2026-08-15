"""Data-quality notes surfaced on `AirportProfile.data_quality_notes` (design 01 "Error
handling & data quality"): human-readable strings the Concierge relays verbatim, never
raw QualityFlag codes.
"""
from __future__ import annotations

import json

from airport_agent.data.derived import CURRENT_REF_YEAR, common

#: Airports design 01 explicitly flags as OTP-undercounted (contiguous-48-only coverage;
#: also matches `tests/fakes.py::FakeDataService`'s ANC note).
KNOWN_OTP_UNDERCOUNT_AIRPORTS = {"ANC", "HNL"}

#: OTP departure coverage below this share of T-100 departures over the same window
#: triggers the undercount note (design 01: "OTP coverage < 80% of T-100 departures").
OTP_COVERAGE_THRESHOLD = 0.80


def _t100_departures_12m(con, iata: str) -> float | None:
    row = con.execute("SELECT MAX(period) FROM routes_month").fetchone()
    latest = row[0] if row else None
    if latest is None:
        return None
    start, end = common.window_months("12m", latest)
    row = con.execute(
        "SELECT SUM(departures) FROM routes_month WHERE iata = ? AND period BETWEEN ? AND ?", [iata, start, end]
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _otp_departures_12m(con, iata: str) -> float | None:
    row = con.execute("SELECT MAX(period) FROM airport_month WHERE measure = 'dep_count'").fetchone()
    latest = row[0] if row else None
    if latest is None:
        return None
    start, end = common.window_months("12m", latest)
    row = con.execute(
        "SELECT SUM(value) FROM airport_month WHERE iata = ? AND measure = 'dep_count' AND period BETWEEN ? AND ?",
        [iata, start, end],
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _otp_undercount_note(con, iata: str) -> str | None:
    if iata in KNOWN_OTP_UNDERCOUNT_AIRPORTS:
        return "OTP undercounts this airport (cargo/regional carriers not in OTP)"
    t100 = _t100_departures_12m(con, iata)
    otp = _otp_departures_12m(con, iata)
    if t100 and t100 > 0 and otp is not None and otp < OTP_COVERAGE_THRESHOLD * t100:
        pct = round(100 * otp / t100)
        return f"OTP undercounts this airport (~{pct}% of T-100 departures)"
    return None


def _has_intl_traffic(con, iata: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM airport_month WHERE iata = ? AND measure = 'intl_out_passengers' AND value > 0 LIMIT 1",
        [iata],
    ).fetchone()
    return row is not None


def _has_curated_inputs(con, iata: str) -> bool:
    row = con.execute("SELECT 1 FROM curated_inputs WHERE iata = ? LIMIT 1", [iata]).fetchone()
    return row is not None


def _quality_flag_notes(con, iata: str) -> list[str]:
    """Human-readable notes derived from the QualityFlag codes attached to this airport's
    current-value metrics (`airport_metrics.quality_json`); deduped by code."""
    rows = con.execute(
        "SELECT DISTINCT quality_json FROM airport_metrics WHERE iata = ? AND ref_year = ? "
        "AND quality_json != '[]'",
        [iata, CURRENT_REF_YEAR],
    ).fetchall()
    messages: dict[str, str] = {}
    for (raw,) in rows:
        for flag in json.loads(raw):
            messages.setdefault(flag["code"], flag["message"])
    return [f"{code}: {message}" for code, message in sorted(messages.items())]


def data_quality_notes(con, iata: str) -> list[str]:
    """Human-readable data-quality notes for `iata` (design 01 "Error handling & data quality")."""
    notes: list[str] = []
    otp_note = _otp_undercount_note(con, iata)
    if otp_note:
        notes.append(otp_note)
    if _has_intl_traffic(con, iata):
        notes.append(
            "T-100 international segment detail not available; only Socrata international "
            "passenger totals (no route-level intl breakdown)"
        )
    if not _has_curated_inputs(con, iata):
        notes.append("no curated capacity inputs for this airport (tier-B metrics unavailable)")
    notes.extend(_quality_flag_notes(con, iata))
    return notes
