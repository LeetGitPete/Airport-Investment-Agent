"""Scoring presets — the only source of weights (design 02).

Pillar weights are absolute and sum to 1.0. `metric_weights` are RELATIVE within a pillar (unlisted = 1.0);
the Scorer normalizes them over the metrics actually available for an airport. `excluded_metrics` are never
scored under the preset. Tier C metrics are never scoreable regardless of preset.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PILLAR_IDS = ("P1", "P2", "P3", "P4", "P5")


class Preset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str
    pillars: dict[str, float]
    metric_weights: dict[str, float] = Field(default_factory=dict)
    excluded_metrics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Preset:
        if set(self.pillars) != set(PILLAR_IDS):
            raise ValueError(f"preset {self.name}: pillars must be exactly {PILLAR_IDS}")
        total = sum(self.pillars.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"preset {self.name}: pillar weights must sum to 1 (got {total:.4f})")
        if any(w < 0 for w in self.pillars.values()) or any(w < 0 for w in self.metric_weights.values()):
            raise ValueError(f"preset {self.name}: weights must be non-negative")
        return self

    def metric_weight(self, metric_id: str) -> float:
        return float(self.metric_weights.get(metric_id, 1.0))


def default_presets_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "scoring_presets.yaml"


def load_presets(path: Path | None = None) -> dict[str, Preset]:
    p = path or default_presets_path()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out: dict[str, Preset] = {}
    for name, body in raw["presets"].items():
        out[name] = Preset(name=name, **body)
    return out
