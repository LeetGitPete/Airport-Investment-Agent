from __future__ import annotations

import pytest

from airport_agent.scoring.presets import Preset, default_presets_path, load_presets


def test_four_presets_load_and_pillar_weights_sum_to_one():
    presets = load_presets()
    assert set(presets) == {"balanced", "terminal_expansion", "congestion_relief", "market_entry"}
    for p in presets.values():
        assert set(p.pillars) == {"P1", "P2", "P3", "P4", "P5"}
        assert abs(sum(p.pillars.values()) - 1.0) < 1e-6


def test_design_02_weights_are_exact():
    p = load_presets()
    assert p["balanced"].pillars == {"P1": 0.30, "P2": 0.25, "P3": 0.15, "P4": 0.15, "P5": 0.15}
    assert p["terminal_expansion"].pillars == {"P1": 0.35, "P2": 0.30, "P3": 0.15, "P4": 0.10, "P5": 0.10}
    assert p["congestion_relief"].pillars == {"P2": 0.50, "P1": 0.25, "P3": 0.10, "P4": 0.05, "P5": 0.10}
    assert p["market_entry"].pillars == {"P3": 0.35, "P4": 0.30, "P1": 0.20, "P2": 0.05, "P5": 0.10}


def test_metric_weight_defaults_to_one_and_honours_overrides():
    p = load_presets()["terminal_expansion"]
    assert p.metric_weight("pax_per_gate") == 3.0
    assert p.metric_weight("carrier_hhi") == 1.0


def test_metric_ids_in_presets_exist_in_registry(by_id):
    for p in load_presets().values():
        for m in list(p.metric_weights) + p.excluded_metrics:
            assert m in by_id, f"{p.name}: unknown metric {m}"


def test_invalid_pillar_sum_rejected(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("presets:\n  x:\n    description: d\n    pillars: {P1: 0.9, P2: 0.5, P3: 0, P4: 0, P5: 0}\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="sum to 1"):
        load_presets(bad)


def test_default_path_points_at_config():
    assert default_presets_path().name == "scoring_presets.yaml"
    assert default_presets_path().parent.name == "config"


def test_preset_model_is_frozen():
    p = Preset(name="a", description="d", pillars={"P1": 1, "P2": 0, "P3": 0, "P4": 0, "P5": 0})
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen-model error, not our exception type to name
        p.name = "b"  # type: ignore[misc]
