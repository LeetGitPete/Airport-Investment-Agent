"""Shared adapter contract and cached-download helper.

`SourceAdapter` is the Protocol every source module in `adapters/` implements
(see `docs/design/01-data-layer.md` Sources & adapters). `download` gives every
adapter one idempotent, on-disk-cached way to fetch a URL so `fetch` calls are
safe to repeat and tests never need the network.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.http import PACER


class Period(BaseModel):
    """A fetch/window period: a year, or a specific year-month."""

    model_config = ConfigDict(frozen=True)

    year: int
    month: int | None = None

    def label(self) -> str:
        """Return "YYYY-MM" if month is set, else "YYYY"."""
        if self.month is not None:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}"


@runtime_checkable
class SourceAdapter(Protocol):
    """Contract implemented by every module under `data/adapters/`."""

    id: str
    kind: Literal["bulk", "live"]

    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download (or reuse cached) raw file(s) for `period`; idempotent."""
        ...

    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Turn raw files into tidy DataFrames keyed by store table name."""
        ...

    def vintage(self) -> SourceVintage:
        """Describe the vintage of the most recently fetched/normalized data."""
        ...


def file_vintage(paths: list[Path] | tuple[Path, ...]) -> tuple[str, str]:
    """Return `(vintage "YYYY-MM-DD", fetched_at ISO)` derived from the raw files themselves.

    Provenance must describe the *data*, not the moment the process happened to start: a
    cached download that `download` reused is as old as its file, and `normalize` called on
    committed fixtures must report those files' dates. Both values come from the newest
    mtime among `paths` (UTC). Every adapter uses this instead of `datetime.now()`.
    """
    if not paths:
        raise ValueError("file_vintage() needs at least one path")
    newest = max(p.stat().st_mtime for p in paths)
    stamp = datetime.fromtimestamp(newest, tz=UTC)
    return stamp.date().isoformat(), stamp.isoformat()


def _suffix_from_url(url: str) -> str:
    path = httpx.URL(url).path
    suffix = Path(path).suffix
    if suffix and len(suffix) <= 6:
        return suffix
    return ".bin"


def _cache_key(url: str, data: dict[str, str] | None) -> str:
    payload = url
    if data:
        payload += json.dumps(sorted(data.items()))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]  # noqa: S324 (cache key, not security)


def download(
    url: str,
    cache_dir: Path,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    client: httpx.Client | None = None,
    filename: str | None = None,
    timeout: float = 120.0,
) -> Path:
    """Download `url` into `cache_dir`, reusing an existing non-empty file.

    Cache key = sha1(url + json.dumps(sorted(data.items())) if data)[:16], with a
    suffix guessed from the URL path (`.zip`, `.csv`, `.json`, `.xlsx`, else
    `.bin`), unless `filename` is given (then the cache key is `filename`
    itself). Streams to `<path>.part` then renames, so a crash mid-download
    never leaves a corrupt cached file. Raises `httpx.HTTPStatusError` on a
    non-2xx response and leaves no file behind.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = filename or (_cache_key(url, data) + _suffix_from_url(url))
    dest = cache_dir / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    owns_client = client is None
    http_client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    part = dest.with_suffix(dest.suffix + ".part")
    # QA task 17: pace only a real request. A cache hit returned above never waits, so a re-run of
    # a refresh over already-downloaded files is as fast as it ever was.
    PACER.wait(url)
    try:
        with http_client.stream(method, url, data=data, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            with part.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            http_client.close()
    return dest
