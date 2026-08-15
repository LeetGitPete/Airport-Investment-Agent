"""Tests for `airport_agent.data.adapters.base`: Period, SourceAdapter, download."""
from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pydantic
import pytest

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters.base import Period, SourceAdapter, download


class _CountingHandler:
    """MockTransport handler that counts calls and can 404 on demand."""

    def __init__(self, body: bytes = b"hello world", status_code: int = 200) -> None:
        self.calls: list[httpx.Request] = []
        self.body = body
        self.status_code = status_code

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status_code, content=self.body)


def _client(handler: _CountingHandler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestPeriod:
    def test_label_year_month(self) -> None:
        assert Period(year=2024, month=3).label() == "2024-03"

    def test_label_year_only(self) -> None:
        assert Period(year=2024).label() == "2024"

    def test_frozen(self) -> None:
        p = Period(year=2024)
        with pytest.raises(pydantic.ValidationError):
            p.year = 2025  # type: ignore[misc]


class TestDownloadCaching:
    def test_second_call_uses_cache(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)
        url = "https://example.com/data/report.csv"

        path1 = download(url, tmp_path, client=client)
        path2 = download(url, tmp_path, client=client)

        assert path1 == path2
        assert path1.exists()
        assert path1.read_bytes() == b"hello world"
        assert len(handler.calls) == 1

    def test_post_data_changes_cache_key(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)
        url = "https://example.com/data/report.csv"

        path_a = download(url, tmp_path, method="POST", data={"year": "2023"}, client=client)
        path_b = download(url, tmp_path, method="POST", data={"year": "2024"}, client=client)

        assert path_a != path_b
        assert len(handler.calls) == 2

    def test_filename_overrides_key(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)
        url = "https://example.com/data/report.csv"

        path = download(url, tmp_path, client=client, filename="custom.csv")

        assert path == tmp_path / "custom.csv"

    def test_404_raises_and_leaves_no_file(self, tmp_path: Path) -> None:
        handler = _CountingHandler(status_code=404)
        client = _client(handler)
        url = "https://example.com/missing.csv"

        with pytest.raises(httpx.HTTPStatusError):
            download(url, tmp_path, client=client)

        assert list(tmp_path.iterdir()) == []

    def test_suffix_guessed_from_url(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)

        path = download("https://example.com/x/report.zip", tmp_path, client=client)

        assert path.suffix == ".zip"

    def test_unknown_suffix_falls_back_to_bin(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)

        path = download("https://example.com/x/report", tmp_path, client=client)

        assert path.suffix == ".bin"

    def test_creates_cache_dir(self, tmp_path: Path) -> None:
        handler = _CountingHandler()
        client = _client(handler)
        cache_dir = tmp_path / "nested" / "cache"

        path = download("https://example.com/x/report.csv", cache_dir, client=client)

        assert path.exists()
        assert cache_dir.is_dir()


class TestSourceAdapterProtocol:
    def test_conforming_class_satisfies_isinstance(self) -> None:
        class TinyAdapter:
            id = "tiny"
            kind = "bulk"

            def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
                return []

            def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
                return {}

            def vintage(self) -> SourceVintage:
                return SourceVintage(
                    source_id="tiny",
                    description="tiny test source",
                    period_start=None,
                    period_end=None,
                    fetched_at="2026-08-15T00:00:00Z",
                )

        assert isinstance(TinyAdapter(), SourceAdapter)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        class NotAnAdapter:
            id = "nope"

        assert not isinstance(NotAnAdapter(), SourceAdapter)
