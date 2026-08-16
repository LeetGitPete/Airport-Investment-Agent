from __future__ import annotations

import pytest

from airport_agent.agent.specialists.loader import SpecialistConfig, default_specialists_dir, load_specialist
from airport_agent.agent.tools.data_tools import build_registry

NAMES = ["expansion_analyst", "capacity_analyst", "market_analyst", "general_analyst"]


@pytest.mark.parametrize("name", NAMES)
def test_configs_load_and_render(name, specs):
    cfg = load_specialist(name, specs)
    assert cfg.name == name and cfg.allowed_tools and cfg.max_turns >= 1
    prompt = cfg.system_prompt(specs)
    assert "{METRIC_SLICE}" not in prompt and "{OUTPUT_SCHEMA}" not in prompt and "{ALLOWED_TOOLS}" not in prompt
    assert "evidence_refs" in prompt and "disagree" in prompt.lower()


def test_capacity_slice_is_p2_plus_absorption(specs):
    cfg = load_specialist("capacity_analyst", specs)
    p = cfg.system_prompt(specs)
    assert "taxi_out_p80_min" in p and "spill_proxy" in p and "load_factor" in p
    assert "msa_gdp_per_capita" not in p
    assert "diagnose_unmet_demand" in cfg.allowed_tools and cfg.default_preset == "congestion_relief"


def test_general_has_all_tools_and_600_hint_note(specs):
    cfg = load_specialist("general_analyst", specs)
    assert len(cfg.allowed_tools) >= 10 and "600" in cfg.system_prompt(specs)


def test_unknown_specialist(specs):
    with pytest.raises(FileNotFoundError):
        load_specialist("nope", specs)


# beyond the brief: config/registry consistency and the shared rules block

RULES_MARKER = "## Rules (identical for every specialist)"


@pytest.mark.parametrize("name", NAMES)
def test_body_has_every_placeholder(name, specs):
    body = load_specialist(name, specs).body
    for placeholder in ("{METRIC_SLICE}", "{ALLOWED_TOOLS}", "{OUTPUT_SCHEMA}"):
        assert placeholder in body


def test_rules_block_is_identical_in_all_four_configs(specs):
    blocks = {name: load_specialist(name, specs).body.split(RULES_MARKER)[-1].strip() for name in NAMES}
    assert len(set(blocks.values())) == 1, "the rules block must be identical for every specialist"
    assert all(RULES_MARKER in load_specialist(name, specs).body for name in NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_allowed_tools_match_the_registry_engine_subset(name, specs, fake_data, fake_analyst):
    reg = build_registry(fake_data, fake_analyst)
    assert set(load_specialist(name, specs).allowed_tools) == set(reg.names(engine=name))


def test_front_matter_matches_design_roster(specs):
    presets = {name: load_specialist(name, specs).default_preset for name in NAMES}
    assert presets == {"expansion_analyst": "terminal_expansion", "capacity_analyst": "congestion_relief",
                       "market_analyst": "market_entry", "general_analyst": None}
    assert load_specialist("general_analyst", specs).max_turns == 3
    assert load_specialist("market_analyst", specs).metric_pillars == ["P3", "P4", "P5"]


BROKEN_CONFIG = """
---
name: broken
allowed_tools: [get_profile]
metric_pillars: [P1]
metric_ids: [not_a_metric]
---
body {METRIC_SLICE} {ALLOWED_TOOLS} {OUTPUT_SCHEMA}
""".lstrip()


def test_unknown_metric_id_in_config_is_loud(tmp_path, specs):
    (tmp_path / "broken.md").write_text(BROKEN_CONFIG, encoding="utf-8")
    with pytest.raises(ValueError, match="not in the registry"):
        load_specialist("broken", specs, config_dir=tmp_path)


def test_missing_front_matter_is_loud(tmp_path, specs):
    (tmp_path / "plain.md").write_text("just a body", encoding="utf-8")
    with pytest.raises(ValueError, match="front matter"):
        load_specialist("plain", specs, config_dir=tmp_path)


def test_default_dir_holds_the_four_configs():
    assert {p.stem for p in default_specialists_dir().glob("*.md")} == set(NAMES)


def test_slice_selects_pillars_and_named_ids(specs):
    cfg = SpecialistConfig(name="x", allowed_tools=["get_profile"], metric_pillars=["P4"],
                           metric_ids=["load_factor"], body="{METRIC_SLICE}")
    ids = [s.id for s in cfg.slice_specs(specs)]
    assert "load_factor" in ids and "cbsa_population" in ids and "carrier_hhi" not in ids
