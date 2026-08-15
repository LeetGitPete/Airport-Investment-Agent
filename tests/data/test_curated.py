"""Curated facts adapter tests — fixture-driven, plus validation of the real YAML."""
from __future__ import annotations

from pathlib import Path

import pytest

from airport_agent.data.adapters import ADAPTERS
from airport_agent.data.adapters.curated import (
    ALLOWED_CATEGORIES,
    CuratedFactsAdapter,
    load_airport_facts,
)
from airport_agent.data.paths import curated_dir

FIXTURE = Path(__file__).parent.parent / "fixtures" / "curated" / "airport_facts_small.yaml"
REAL = curated_dir() / "airport_facts.yaml"


@pytest.fixture()
def tables() -> dict:
    return CuratedFactsAdapter().normalize([FIXTURE])


class TestRegistration:
    def test_registered_under_its_id(self) -> None:
        assert ADAPTERS["curated"] is CuratedFactsAdapter

    def test_kind_is_bulk(self) -> None:
        assert CuratedFactsAdapter.kind == "bulk"


class TestNormalize:
    def test_inputs_rows_one_per_input(self, tables: dict) -> None:
        inputs = tables["curated_inputs"]
        assert len(inputs) == 5  # SFO 3 + PDX 2
        sfo = inputs[inputs.iata == "SFO"].set_index("key")["value"]
        assert sfo["declared_rate_vmc"] == 105.5 and sfo["slot_or_cap_flag"] == 1.0

    def test_omitted_input_produces_no_row(self, tables: dict) -> None:
        pdx = tables["curated_inputs"].query("iata == 'PDX'")
        assert "declared_rate_imc" not in set(pdx["key"])  # left out, never invented

    def test_every_input_row_has_source_and_as_of(self, tables: dict) -> None:
        inputs = tables["curated_inputs"]
        assert inputs["source_url"].str.startswith("https://").all()
        assert inputs["as_of"].str.len().ge(4).all()

    def test_facts_carry_provenance_and_category(self, tables: dict) -> None:
        facts = tables["curated_facts"]
        assert len(facts) == 1
        row = facts.iloc[0]
        assert row.category == "slot_level" and row.value == "2"
        assert row.source_url and row.as_of


class TestValidation:
    def test_unsourced_input_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "airports:\n  AAA:\n    inputs: {gates: 10}\n    inputs_sources: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no source url"):
            load_airport_facts(bad)

    def test_unknown_category_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "airports:\n  AAA:\n    inputs: {}\n    inputs_sources: {}\n"
            "    facts:\n      - {category: rumor, text: t, source_url: u, as_of: '2026'}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="rumor"):
            load_airport_facts(bad)

    def test_unknown_input_key_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "airports:\n  AAA:\n    inputs: {runways: 4}\n"
            "    inputs_sources: {runways: {url: u, as_of: '2026'}}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="runways"):
            load_airport_facts(bad)


class TestRealFile:
    """The shipped curated YAML must satisfy its own validation rules."""

    def test_real_yaml_validates_and_covers_target_hubs(self) -> None:
        airports = load_airport_facts(REAL)
        assert {"BOS", "SFO", "JFK", "LGA", "DCA", "SNA", "ATL", "ORD"} <= set(airports)
        assert len(airports) >= 30

    def test_slot_flags_match_the_faa_lists(self) -> None:
        airports = load_airport_facts(REAL)
        flagged = {i for i, e in airports.items() if e["inputs"].get("slot_or_cap_flag") == 1}
        assert flagged == {"JFK", "LGA", "DCA", "ORD", "LAX", "EWR", "SFO", "SNA"}

    def test_imc_never_exceeds_vmc(self) -> None:
        for iata, entry in load_airport_facts(REAL).items():
            vmc = entry["inputs"].get("declared_rate_vmc")
            imc = entry["inputs"].get("declared_rate_imc")
            if vmc is not None and imc is not None:
                assert imc <= vmc, iata

    def test_real_categories_are_allowed(self) -> None:
        for entry in load_airport_facts(REAL).values():
            for fact in entry.get("facts", []) or []:
                assert fact["category"] in ALLOWED_CATEGORIES
