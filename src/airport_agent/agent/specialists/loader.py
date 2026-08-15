"""Load a specialist from its config artifact (`config/specialists/<name>.md`).

A specialist is configuration, not code (design 03): YAML front matter (allowed tools, default preset, metric
slice, loop budget) followed by a markdown body with three placeholders that the loader fills from live
objects — {METRIC_SLICE} from the metric registry, {ALLOWED_TOOLS} from the front matter, {OUTPUT_SCHEMA}
from the shared response schema. Adding a specialist is a config change.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from airport_agent.agent.specialists.schema import schema_doc
from airport_agent.contracts import MetricSpec

FRONT_MATTER_DELIM = "---"
SLICE_COLUMNS = ["id", "name", "definition", "formula", "unit", "direction", "tier", "sources", "caveats"]


def default_specialists_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "specialists"


class SpecialistConfig(BaseModel):
    """Parsed `config/specialists/<name>.md`."""

    model_config = ConfigDict(extra="forbid")
    name: str
    allowed_tools: list[str]
    default_preset: str | None = None
    # budget: plan (1) + loop (max_turns) + specialist final (1) + synthesis (1) <= 6 calls per question
    max_turns: int = Field(default=2, ge=1, le=3)
    metric_pillars: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    body: str

    def slice_specs(self, specs: list[MetricSpec]) -> list[MetricSpec]:
        """The specialist's metric vocabulary: its pillars plus any explicitly named ids, registry order."""
        return [s for s in specs if s.pillar in self.metric_pillars or s.id in self.metric_ids]

    def metric_slice(self, specs: list[MetricSpec]) -> str:
        header = ("| " + " | ".join(SLICE_COLUMNS) + " |\n|" + "|".join(["---"] * len(SLICE_COLUMNS)) + "|")
        rows = ["| " + " | ".join([s.id, s.name, s.definition, s.formula, s.unit, s.direction, s.tier,
                                   ", ".join(s.sources), "; ".join(s.caveats) or "-"]) + " |"
                for s in self.slice_specs(specs)]
        note = ("\nTier A is computed for every airport, tier B only where curated data exists (majors), tier C "
                "is a documented gap with no usable public source — never quote a tier C value, name it as a "
                "limitation instead.")
        return "\n".join([header, *rows]) + note

    def system_prompt(self, specs: list[MetricSpec]) -> str:
        """The body with its placeholders filled from live objects (registry, schema, front matter)."""
        return (self.body
                .replace("{METRIC_SLICE}", self.metric_slice(specs))
                .replace("{ALLOWED_TOOLS}", ", ".join(self.allowed_tools))
                .replace("{OUTPUT_SCHEMA}", schema_doc()))


def _split_front_matter(text: str, path: Path) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIM:
        raise ValueError(f"{path}: missing YAML front matter (first line must be '---')")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == FRONT_MATTER_DELIM)
    except StopIteration:
        raise ValueError(f"{path}: front matter is not closed by a '---' line") from None
    front = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(front, dict):
        raise ValueError(f"{path}: front matter must be a YAML mapping")
    return front, "\n".join(lines[end + 1:]).strip()


def load_specialist(name: str, specs: list[MetricSpec], config_dir: Path | None = None) -> SpecialistConfig:
    """Load and validate one specialist config. Unknown name -> FileNotFoundError (never a default prompt)."""
    path = (config_dir or default_specialists_dir()) / f"{name}.md"
    front, body = _split_front_matter(path.read_text(encoding="utf-8"), path)
    cfg = SpecialistConfig(**front, body=body)
    if cfg.name != name:
        raise ValueError(f"{path}: front matter name {cfg.name!r} does not match file name {name!r}")
    known = {s.id for s in specs}
    unknown = [m for m in cfg.metric_ids if m not in known]
    if unknown:
        raise ValueError(f"{path}: metric_ids not in the registry: {unknown}")
    known_pillars = {s.pillar for s in specs}
    unknown_pillars = [p for p in cfg.metric_pillars if p not in known_pillars]
    if unknown_pillars:
        raise ValueError(f"{path}: metric_pillars not in the registry: {unknown_pillars}")
    if not cfg.slice_specs(specs):
        raise ValueError(f"{path}: metric slice is empty; the specialist would have no vocabulary")
    return cfg
