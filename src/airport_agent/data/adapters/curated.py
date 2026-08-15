"""Curated facts adapter — `curated_facts` and `curated_inputs` from a hand-maintained YAML.

Source: `data/curated/airport_facts.yaml` (a local file, not a network source). It holds the
tier-B capacity inputs the public bulk feeds cannot provide (declared VMC/IMC runway rates
from the FAA Airport Capacity Profiles, slot/cap flags from the FAA slot administration
page and the SNA settlement agreement) plus per-airport facts for the unmet-demand
diagnosis. Every input and fact carries its own `source_url` + `as_of`; the product rule is
**no invented numbers**, so a value without a source is a validation error, and airports
with no verifiable source for a value simply omit it (`gates` is currently omitted for all
airports — human decision 2026-08-15, see known-limitations).

Rate conventions (human decision 2026-08-15): `declared_rate_vmc` = midpoint of the best
visual-configuration range in the profile; `declared_rate_imc` = midpoint of the worst
instrument-configuration range (excluding "Low Instrument"), so `imc_capacity_ratio`
measures weather vulnerability and `peak_hour_ops_ratio` compares peak demand to best-case
throughput. The profiles date 2014-2019 and have not been updated by the FAA since.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
import yaml

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, file_vintage
from airport_agent.data.paths import curated_dir

FACTS_FILE = "airport_facts.yaml"

#: The keys `curated_inputs` may hold (plan 2a store schema).
ALLOWED_INPUT_KEYS = {"gates", "declared_rate_vmc", "declared_rate_imc", "slot_or_cap_flag"}

#: The fact categories the design allows (plan 2a Task 12).
ALLOWED_CATEGORIES = {"slot_level", "constraint", "project"}

FACTS_COLUMNS = ("iata", "category", "text", "value", "source_url", "as_of", "expires")
INPUTS_COLUMNS = ("iata", "key", "value", "source_url", "as_of")


def load_airport_facts(path: Path) -> dict[str, dict]:
    """Load and validate the curated YAML; return its `airports` mapping.

    Validation enforces the no-invented-numbers rule structurally: every input must have a
    matching `inputs_sources` entry with a `url`, every fact must carry `source_url` and
    `as_of`, and only known input keys / fact categories are accepted.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    airports = raw.get("airports")
    if not isinstance(airports, dict) or not airports:
        raise ValueError(f"{path.name}: missing or empty 'airports' mapping")
    for iata, entry in airports.items():
        inputs = entry.get("inputs", {}) or {}
        sources = entry.get("inputs_sources", {}) or {}
        bad_keys = set(inputs) - ALLOWED_INPUT_KEYS
        if bad_keys:
            raise ValueError(f"{path.name}: {iata}: unknown input key(s) {sorted(bad_keys)}")
        unsourced = [k for k in inputs if not (sources.get(k) or {}).get("url")]
        if unsourced:
            raise ValueError(
                f"{path.name}: {iata}: input(s) {unsourced} have no source url — "
                "a value without a source is an invented number"
            )
        for fact in entry.get("facts", []) or []:
            if fact.get("category") not in ALLOWED_CATEGORIES:
                raise ValueError(
                    f"{path.name}: {iata}: fact category {fact.get('category')!r} not in "
                    f"{sorted(ALLOWED_CATEGORIES)}"
                )
            if not fact.get("source_url") or not fact.get("as_of"):
                raise ValueError(f"{path.name}: {iata}: every fact needs source_url and as_of")
    return airports


@register
class CuratedFactsAdapter:
    """Normalize `airport_facts.yaml` into the `curated_facts` and `curated_inputs` tables."""

    id: str = "curated"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        self._vintage: str | None = None
        self._fetched_at: str | None = None

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """A local file: nothing to download — return the curated YAML's path."""
        path = curated_dir() / FACTS_FILE
        if not path.exists():
            raise FileNotFoundError(f"curated facts file missing: {path}")
        self._set_vintage([path])
        return [path]

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"curated_facts": df, "curated_inputs": df}`."""
        if len(paths) != 1:
            raise ValueError(f"curated expects exactly one YAML file, got {len(paths)}")
        self._set_vintage(paths)
        airports = load_airport_facts(paths[0])

        fact_rows: list[dict] = []
        input_rows: list[dict] = []
        for iata in sorted(airports):
            entry = airports[iata]
            sources = entry.get("inputs_sources", {}) or {}
            for key in sorted(entry.get("inputs", {}) or {}):
                src = sources[key]
                input_rows.append(
                    {
                        "iata": iata,
                        "key": key,
                        "value": float(entry["inputs"][key]),
                        "source_url": str(src["url"]),
                        "as_of": str(src["as_of"]),
                    }
                )
            for fact in entry.get("facts", []) or []:
                fact_rows.append(
                    {
                        "iata": iata,
                        "category": fact["category"],
                        "text": fact["text"],
                        "value": None if fact.get("value") is None else str(fact["value"]),
                        "source_url": fact["source_url"],
                        "as_of": str(fact["as_of"]),
                        "expires": None if fact.get("expires") is None else str(fact["expires"]),
                    }
                )
        facts = pd.DataFrame(fact_rows, columns=list(FACTS_COLUMNS))
        inputs = pd.DataFrame(input_rows, columns=list(INPUTS_COLUMNS))
        return {"curated_facts": facts, "curated_inputs": inputs}

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        if self._vintage is None:
            raise RuntimeError("curated: normalize/fetch must run before row_vintage")
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                "Hand-curated per-airport facts and tier-B capacity inputs (declared VMC/IMC "
                "rates from FAA Airport Capacity Profiles 2014-2019, slot/cap flags, "
                "settlement constraints); every value carries its own source_url + as_of"
            ),
            period_start=None,
            period_end=None,
            fetched_at=self._fetched_at,
            url=f"data/curated/{FACTS_FILE}",
        )
