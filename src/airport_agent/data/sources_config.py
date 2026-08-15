"""Loader for `config/sources.yaml` — the registry of upstream data sources."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from airport_agent.data.paths import repo_root


class SourceConfig(BaseModel):
    """One entry in `config/sources.yaml`."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: Literal["bulk", "live"]
    url: str
    cadence_days: int
    description: str
    notes: str = ""


def default_sources_path() -> Path:
    return repo_root() / "config" / "sources.yaml"


def load_sources(path: Path | None = None) -> dict[str, SourceConfig]:
    """Load `config/sources.yaml` into a dict keyed by source id."""
    p = path or default_sources_path()
    raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    sources: dict[str, SourceConfig] = {}
    for source_id, fields in raw.items():
        sources[source_id] = SourceConfig(id=source_id, **fields)
    return sources
