"""Provider configuration (config/providers.yaml). Model names never live in code."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    model: str
    api_key_env: str
    rpm: int = 10
    max_retries: int = 2
    timeout_s: int = 60


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    providers: list[ProviderConfig] = Field(default_factory=list)
    default_temperature: float = 0.2


def default_providers_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "providers.yaml"


def load_llm_config(path: Path | None = None) -> LLMConfig:
    raw = yaml.safe_load((path or default_providers_path()).read_text(encoding="utf-8")) or {}
    cfg = LLMConfig(**raw)
    if not cfg.providers:
        raise ValueError("no providers configured in providers.yaml")
    return cfg
