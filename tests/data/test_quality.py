"""Tests for `airport_agent.data.quality.data_quality_notes`."""
from __future__ import annotations

import pandas as pd
import pytest

from airport_agent.data import quality
from airport_agent.data.store import Store


class TestOnTheTestSnapshot:
    def test_anc_gets_the_known_otp_undercount_note(self, snapshot_con) -> None:
        notes = quality.data_quality_notes(snapshot_con, "ANC")
        assert any("OTP undercounts this airport" in n for n in notes)

    def test_bos_has_no_curated_inputs_note(self, snapshot_con) -> None:
        # BOS is not in the small curated fixture (only SFO/PDX are).
        notes = quality.data_quality_notes(snapshot_con, "BOS")
        assert any("no curated capacity inputs" in n for n in notes)

    def test_sfo_curated_note_is_absent(self, snapshot_con) -> None:
        notes = quality.data_quality_notes(snapshot_con, "SFO")
        assert not any("no curated capacity inputs" in n for n in notes)

    def test_jfk_gets_the_intl_detail_note(self, snapshot_con) -> None:
        # JFK has real Socrata international traffic in the fixture.
        notes = quality.data_quality_notes(snapshot_con, "JFK")
        assert any("international segment detail" in n for n in notes)


class TestSyntheticOtpUndercount:
    @pytest.fixture
    def store(self, tmp_store: Store) -> Store:
        rows = [
            {"iata": "AAA", "dest": "X", "dest_name": "x", "period": "2026-04", "carrier": "C1",
             "distance_mi": 300.0, "departures": 1000, "seats": 1000, "passengers": 800,
             "freight_lb": 0.0, "mail_lb": 0.0, "is_international": False, "aircraft_config": "1",
             "source_id": "bts_t100", "vintage": "2026-04"},
        ]
        tmp_store.replace_rows("routes_month", pd.DataFrame(rows), None)
        otp_rows = [
            {"iata": "AAA", "period": "2026-04", "measure": "dep_count", "value": 100.0,
             "source_id": "bts_otp", "vintage": "2026-04"},
        ]
        tmp_store.replace_rows("airport_month", pd.DataFrame(otp_rows), None)
        return tmp_store

    def test_flags_when_otp_departures_are_under_80pct_of_t100(self, store: Store) -> None:
        # OTP reports 100 departures vs T-100's 1000 -> 10% coverage, well under 80%.
        notes = quality.data_quality_notes(store.con, "AAA")
        assert any("OTP undercounts this airport" in n and "%" in n for n in notes)


class TestQualityFlagNotes:
    def test_surfaces_partial_year_flag_from_airport_metrics(self, tmp_store: Store) -> None:
        rows = pd.DataFrame(
            [
                {"iata": "AAA", "metric_id": "load_factor", "horizon": "12m", "ref_year": 9999, "value": 0.8,
                 "period_start": "2025-05", "period_end": "2026-04", "source_id": "bts_socrata",
                 "vintage": "2026-04",
                 "quality_json": '[{"code": "partial_year", "message": "current year incomplete"}]'},
            ]
        )
        tmp_store.replace_rows("airport_metrics", rows, None)
        notes = quality.data_quality_notes(tmp_store.con, "AAA")
        assert any("partial_year" in n for n in notes)
