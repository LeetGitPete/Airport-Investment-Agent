"""Load and validate the metric registry (config/metrics.yaml) into MetricSpec objects."""
from __future__ import annotations

from pathlib import Path

import yaml

from airport_agent.contracts.models import MetricSpec

PILLAR_NAMES = {"P1": "Demand Pressure", "P2": "Congestion & Physical Constraint", "P3": "Market Quality",
                "P4": "Economic Base", "P5": "Financeability & Pipeline"}


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "metrics.yaml"


def load_registry(path: Path | None = None) -> list[MetricSpec]:
    p = path or default_registry_path()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    specs = [MetricSpec(**m) for m in raw["metrics"]]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate metric ids in registry")
    return specs


def load_pillars(path: Path | None = None) -> dict[str, dict]:
    p = path or default_registry_path()
    return yaml.safe_load(p.read_text(encoding="utf-8"))["pillars"]


def registry_by_id(specs: list[MetricSpec]) -> dict[str, MetricSpec]:
    return {s.id: s for s in specs}
