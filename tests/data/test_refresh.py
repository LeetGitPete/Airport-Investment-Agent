"""Tests for `refresh()`/`staleness()`/the CLI — per-source failure isolation and `--check`."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data import adapters as adapters_module
from airport_agent.data.__main__ import main as cli_main
from airport_agent.data.adapters.base import Period
from airport_agent.data.refresh import refresh, staleness
from airport_agent.data.sources_config import SourceConfig
from airport_agent.data.store import Store


class FakeGoodAdapter:
    id: str = "fake_good"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        pass

    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        return []

    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        return {
            "curated_facts": pd.DataFrame(
                [
                    {"iata": "ZZZ", "category": "project", "text": "fake fact", "value": None,
                     "source_url": "https://example.test", "as_of": "2026-01", "expires": None,
                     "source_id": "fake_good", "vintage": "2026-01-01"}
                ]
            )
        }

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id="fake_good", description="fake good source", period_start=None, period_end=None,
            fetched_at=datetime.now(UTC).isoformat(), url=None,
        )


class FakeBadAdapter:
    id: str = "fake_bad"
    kind: Literal["bulk", "live"] = "bulk"

    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        raise RuntimeError("simulated fetch failure")

    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        return {}

    def vintage(self) -> SourceVintage:
        raise AssertionError("never called: fetch always raises first")


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(adapters_module.ADAPTERS, "fake_good", FakeGoodAdapter)
    monkeypatch.setitem(adapters_module.ADAPTERS, "fake_bad", FakeBadAdapter)


class TestRefreshFailureIsolation:
    def test_report_lists_both_sources(self, fake_registry: None, tmp_path: Path) -> None:
        report = refresh(sources=["fake_good", "fake_bad"], snapshot_path=tmp_path / "snap.duckdb", cache_dir=tmp_path)
        ids = {r.source_id: r for r in report.results}
        assert set(ids) == {"fake_good", "fake_bad"}
        assert ids["fake_good"].ok is True
        assert ids["fake_bad"].ok is False
        assert "simulated fetch failure" in ids["fake_bad"].error

    def test_snapshot_keeps_the_good_source_data(self, fake_registry: None, tmp_path: Path) -> None:
        snapshot = tmp_path / "snap.duckdb"
        refresh(sources=["fake_good", "fake_bad"], snapshot_path=snapshot, cache_dir=tmp_path)
        store = Store(snapshot)
        try:
            row = store.con.execute("SELECT iata FROM curated_facts WHERE source_id = 'fake_good'").fetchone()
            assert row == ("ZZZ",)
        finally:
            store.close()

    def test_a_failing_source_never_raises(self, fake_registry: None, tmp_path: Path) -> None:
        report = refresh(sources=["fake_bad"], snapshot_path=tmp_path / "snap.duckdb", cache_dir=tmp_path)
        assert report.failed and report.results[0].source_id == "fake_bad"

    def test_unknown_source_id_is_reported_not_raised(self, tmp_path: Path) -> None:
        report = refresh(sources=["does_not_exist"], snapshot_path=tmp_path / "snap.duckdb", cache_dir=tmp_path)
        assert report.failed
        assert "no registered adapter" in report.results[0].error

    def test_derived_metrics_are_rebuilt_even_with_a_failure(self, fake_registry: None, tmp_path: Path) -> None:
        report = refresh(sources=["fake_good", "fake_bad"], snapshot_path=tmp_path / "snap.duckdb", cache_dir=tmp_path)
        assert isinstance(report.derived_row_counts, dict)


class TestStaleness:
    @pytest.fixture
    def snapshot(self, tmp_path: Path) -> Path:
        path = tmp_path / "snap.duckdb"
        store = Store(path)
        fresh = datetime.now(UTC) - timedelta(days=1)
        stale = datetime.now(UTC) - timedelta(days=400)
        store.upsert_vintage(
            SourceVintage(source_id="a", description="x", period_start=None, period_end=None,
                          fetched_at=fresh.isoformat(), url=None)
        )
        store.upsert_vintage(
            SourceVintage(source_id="b", description="x", period_start=None, period_end=None,
                          fetched_at=stale.isoformat(), url=None)
        )
        store.close()
        return path

    def test_fresh_and_stale_and_missing(self, snapshot: Path) -> None:
        cfgs = {
            "a": SourceConfig(id="a", kind="bulk", url="u", cadence_days=30, description="d"),
            "b": SourceConfig(id="b", kind="bulk", url="u", cadence_days=30, description="d"),
            "c": SourceConfig(id="c", kind="bulk", url="u", cadence_days=30, description="d"),
        }
        rows = {r["source_id"]: r for r in staleness(snapshot, cfgs)}
        assert rows["a"]["status"] == "fresh"
        assert rows["b"]["status"] == "stale"
        assert rows["c"]["status"] == "missing"

    def test_zero_cadence_is_always_fresh(self, snapshot: Path) -> None:
        cfgs = {"b": SourceConfig(id="b", kind="live", url="u", cadence_days=0, description="d")}
        rows = staleness(snapshot, cfgs)
        assert rows[0]["status"] == "fresh"


class TestCli:
    def test_check_prints_stale_and_fresh(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        snapshot = tmp_path / "snap.duckdb"
        store = Store(snapshot)
        stale = datetime.now(UTC) - timedelta(days=9999)
        store.upsert_vintage(
            SourceVintage(source_id="ourairports", description="x", period_start=None, period_end=None,
                          fetched_at=stale.isoformat(), url=None)
        )
        store.close()

        cli_main(["refresh", "--check", "--snapshot", str(snapshot)])
        out = capsys.readouterr().out
        assert "stale" in out
        assert "missing" in out  # every other configured source has no vintage in this snapshot

    def test_invalid_period_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["refresh", "--period", "not-a-period"])
        assert exc_info.value.code == 2

    def test_unknown_source_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["refresh", "--sources", "does_not_exist"])
        assert exc_info.value.code == 2

    def test_refresh_prints_a_report(self, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
        # "curated" is a real configured source but a local file (no network) -- a real,
        # fast CLI smoke test of the report-printing path (--sources validates against
        # config/sources.yaml, so this can't use the fake_registry fixture's made-up ids).
        cli_main(
            [
                "refresh", "--sources", "curated", "--snapshot", str(tmp_path / "snap.duckdb"),
                "--cache-dir", str(tmp_path),
            ]
        )
        out = capsys.readouterr().out
        assert "curated" in out
        assert "ok" in out
