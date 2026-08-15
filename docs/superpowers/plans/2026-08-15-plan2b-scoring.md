# Plan 2b — Deterministic Scoring & Analyst (`scoring/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the formula-driven Deterministic Analyst (`rank` / `compare` / `diagnose` + distance-band calculators) over the frozen `DataService` contract and metric registry, TDD'd against `tests/fakes.py::FakeDataService`, with presets in `config/scoring_presets.yaml` and templated (no-LLM) explanations.

**Architecture:** `scoring/` imports only `airport_agent.contracts` and itself. `presets.py` loads weights; `percentiles.py` ranks within peer groups; `scorer.py` turns a `FeatureMatrix` into `ScoreRow`s (`metric_contrib = w_p × w_m × pct × 100`); `calculators.py` does route distance bands; `explain.py` templates text from contributions; `analyst.py` implements the `DeterministicAnalyst` Protocol by composing them over a `DataService`.

**Tech Stack:** Python 3.12, pydantic v2, PyYAML, pytest. No pandas/numpy needed (pure Python over small lists). No LLM, no network, no I/O except reading `config/scoring_presets.yaml`.

**Spec:** `docs/design/02-metrics-and-scoring.md` (scoring engine, presets, conventions, validation goldens), `docs/design/03-agent-architecture.md` (Deterministic Analyst role), `docs/design/known-limitations-and-tradeoffs.md` rows 19–21. Frozen code this plan builds against: `src/airport_agent/contracts/{models,requests,reports,scoring,data_service,registry}.py`, `config/metrics.yaml`, `tests/fakes.py`.

## Global Constraints
- **FROZEN SURFACE:** `src/airport_agent/contracts/**` and `config/metrics.yaml` MUST NOT change (tag `contracts-v1`, `.contracts-frozen`). Any need to change them → STOP and return `DECISION NEEDED`. Reviewers git-verify this (`git diff --name-only <BASE>..<HEAD> -- src/airport_agent/contracts config/metrics.yaml` must print nothing).
- **Ownership:** this plan writes only `src/airport_agent/scoring/**`, `config/scoring_presets.yaml`, `tests/scoring/**`. Never touch `data/`, `llm/`, `agent/`, `ui/`, `pyproject.toml`, `tests/fakes.py`, `tests/contracts/**`.
- **Layering:** `scoring/` imports only `airport_agent.contracts` and `airport_agent.scoring`. `uv run lint-imports` (run as `PYTHONIOENCODING=utf-8 uv run lint-imports` on Windows) must keep all 4 contracts.
- **No LLM calls, no network** anywhere in `scoring/` or its tests. The only stand-in for data is `tests.fakes.FakeDataService`.
- **Product rules:** every number in a report is a `Metric` carrying `source_id` + `vintage` (evidence) or a value in `comparison`/`percentiles` traceable to `evidence`; weights come only from `config/scoring_presets.yaml` (never invented, never from the caller except by preset name); tier C metrics are never scored; conventions are stated in `caveats`/`explanation` when used (long-haul ≥1,500 mi default; spill model not LF cutoff; percentiles within hub class; P5 always within hub class).
- **Formula (frozen docstring in `contracts/reports.py`):** `ScoreRow.metric_contrib[m] = w_p × w_m × pct × 100`, metric contributions sum to `score`; `DeterministicReport.weights` keyed by pillar id (P1..P5) and metric id (within-pillar weights).
- **Horizon rule (contract):** never relabel; a metric that does not declare the requested horizon comes back `None` from `get_feature_matrix` and is treated as missing.
- **`peer_group=None` on `AnalysisRequest` ⇒ `"hub_class"`.** `req.horizons[0]` is the horizon of the report (contract: `DeterministicReport.horizon` is a single `Horizon`).
- Escalation protocol (design 05 §5.0): anything non-trivial → STOP, `DECISION NEEDED` block (what · why · options · recommendation · blocked); finish independent work meanwhile.
- Conventions: full type hints, ruff clean (`uv run ruff check .`), small focused files, TDD, commit after every task with `type(scope): summary`, git identity `-c user.name="Pete" -c user.email="Itamarr@voyager-labs.com"`.
- Gate before reporting each task: `uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports && uv run pytest tests/scoring tests/contracts -q`.

---

## File structure (what this plan creates)

```
config/scoring_presets.yaml                     presets: balanced, terminal_expansion, congestion_relief, market_entry
src/airport_agent/scoring/__init__.py           exports Analyst, Scorer, load_presets, Preset
src/airport_agent/scoring/presets.py            Preset model + load_presets(path) + validation (weights sum to 1)
src/airport_agent/scoring/percentiles.py        percentile_rank(values, direction), peer_group_key(ref, peer_group), percentiles_by_group(...)
src/airport_agent/scoring/scorer.py             Scorer.score(fm, preset, percentiles) -> ScoringResult (rows, weights, pillar_scores)
src/airport_agent/scoring/calculators.py        distance_bands(routes, freight), long_haul_share(routes, threshold_mi, freight, horizon)
src/airport_agent/scoring/explain.py            explain_rank / explain_compare / explain_diagnose (templated strings)
src/airport_agent/scoring/analyst.py            Analyst(DataService) implements contracts.DeterministicAnalyst
tests/scoring/__init__.py
tests/scoring/conftest.py                       fixtures: fake data service, presets, analyst
tests/scoring/test_presets.py
tests/scoring/test_percentiles.py
tests/scoring/test_scorer.py
tests/scoring/test_calculators.py
tests/scoring/test_explain.py
tests/scoring/test_analyst_rank.py
tests/scoring/test_analyst_compare.py
tests/scoring/test_analyst_diagnose.py
tests/scoring/test_protocol.py
```

Public names other workstreams will import in Phase 3 (composition root `agent/`): `airport_agent.scoring.Analyst(data: DataService, presets_path: Path | None = None)` and `airport_agent.scoring.load_presets(path: Path | None = None) -> dict[str, Preset]`.

---

### Task 1: Presets config + loader

**Files:**
- Create: `config/scoring_presets.yaml`, `src/airport_agent/scoring/presets.py`, `src/airport_agent/scoring/__init__.py`, `tests/scoring/__init__.py`, `tests/scoring/conftest.py`, `tests/scoring/test_presets.py`

**Interfaces:**
- Consumes: `airport_agent.contracts.load_pillars()`, `load_registry()`, `MetricSpec`.
- Produces: `Preset(name, description, pillars: dict[str, float], metric_weights: dict[str, float], excluded_metrics: list[str])`; `load_presets(path: Path | None = None) -> dict[str, Preset]`; `default_presets_path() -> Path`; `Preset.metric_weight(metric_id) -> float` (relative weight within its pillar; 1.0 unless overridden).

Semantics (state these in the module docstring): pillar weights are absolute and sum to 1.0 (±1e-6). `metric_weights` are *relative* within-pillar weights; every scoreable metric not listed has relative weight 1.0; the scorer normalizes relative weights over the metrics actually available for an airport. `excluded_metrics` are registry ids the preset never scores (informational only — design 02 marks `aip_per_enpl_10y` "↑ (info)"). Tier C ids are never scoreable regardless of preset.

- [ ] **Step 1: Write the presets YAML**

`config/scoring_presets.yaml`:
```yaml
# Scoring presets — the ONLY source of weights (design 02). Pillar weights are absolute and sum to 1.
# metric_weights are relative within a pillar (unlisted metric = 1.0); the scorer renormalizes over the
# metrics actually available for an airport. excluded_metrics are never scored under that preset.
presets:
  balanced:
    description: Registry default pillar weights; all tier A/B metrics weighted equally within pillars.
    pillars: {P1: 0.30, P2: 0.25, P3: 0.15, P4: 0.15, P5: 0.15}
    metric_weights: {}
    excluded_metrics: [aip_per_enpl_10y]
  terminal_expansion:
    description: Terminal/gate capacity focus — gate and passenger-side metrics up-weighted vs runway/delay.
    pillars: {P1: 0.35, P2: 0.30, P3: 0.15, P4: 0.10, P5: 0.10}
    metric_weights:
      pax_per_gate: 3.0
      deps_per_gate_day: 3.0
      peak_hour_ops_ratio: 1.5
      load_factor: 2.0
      seats_per_dep_trend: 2.0
      taxi_out_p80_min: 0.5
      ops_per_runway: 0.5
    excluded_metrics: [aip_per_enpl_10y]
  congestion_relief:
    description: Runway/airfield congestion focus — delay, taxi-out, NAS share, airfield intensity up-weighted.
    pillars: {P2: 0.50, P1: 0.25, P3: 0.10, P4: 0.05, P5: 0.10}
    metric_weights:
      pct_arr_delay_gt15: 2.0
      avg_dep_delay_min: 2.0
      taxi_out_p80_min: 2.0
      nas_delay_share: 2.0
      ops_per_runway: 2.0
      npias_capacity_label: 2.0
      pax_per_gate: 0.5
      deps_per_gate_day: 0.5
    excluded_metrics: [aip_per_enpl_10y]
  market_entry:
    description: Market quality and economic base focus for new-entrant/route investment.
    pillars: {P3: 0.35, P4: 0.30, P1: 0.20, P2: 0.05, P5: 0.10}
    metric_weights: {}
    excluded_metrics: [aip_per_enpl_10y]
```

- [ ] **Step 2: Write the failing tests**

`tests/scoring/__init__.py`: empty file.

`tests/scoring/conftest.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import load_registry, registry_by_id
from tests.fakes import FakeDataService


@pytest.fixture(scope="session")
def specs():
    return load_registry()


@pytest.fixture(scope="session")
def by_id(specs):
    return registry_by_id(specs)


@pytest.fixture
def fake():
    return FakeDataService()
```

`tests/scoring/test_presets.py`:
```python
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
    with pytest.raises(Exception):
        p.name = "b"  # type: ignore[misc]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/scoring/test_presets.py -q`
Expected: FAIL with `ModuleNotFoundError: airport_agent.scoring.presets`

- [ ] **Step 4: Implement**

`src/airport_agent/scoring/presets.py`:
```python
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
```

`src/airport_agent/scoring/__init__.py` (for now):
```python
"""Deterministic scoring: presets, percentiles, scorer, calculators, explanations, Analyst."""
from __future__ import annotations

from airport_agent.scoring.presets import Preset, default_presets_path, load_presets

__all__ = ["Preset", "default_presets_path", "load_presets"]
```

- [ ] **Step 5: Run tests, lint, commit**

Run: `uv run pytest tests/scoring/test_presets.py -q && uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports`
Expected: all pass, 4 contracts kept.

```bash
git add config/scoring_presets.yaml src/airport_agent/scoring tests/scoring
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): presets config and loader"
```

---

### Task 2: Percentiles within peer groups

**Files:**
- Create: `src/airport_agent/scoring/percentiles.py`, `tests/scoring/test_percentiles.py`

**Interfaces:**
- Consumes: `AirportRef`, `Direction`, `PeerGroup` from contracts.
- Produces:
  - `percentile_rank(values: list[float | None], direction: Direction = "up") -> list[float | None]` — average-rank percentile in [0,1] among non-None values; single value → 0.5; `direction="down"` → `1 - pct`. None stays None.
  - `peer_group_key(ref: AirportRef, peer_group: PeerGroup) -> str` — `"hub_class"` → `ref.hub_size`; `"region"` → `ref.faa_region`; `"all"` → `"all"`.
  - `percentiles_by_group(refs: list[AirportRef], values: list[float | None], direction: Direction, peer_group: PeerGroup) -> list[float | None]` — percentile of each airport computed only among airports sharing its key.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_percentiles.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.scoring.percentiles import peer_group_key, percentile_rank, percentiles_by_group
from tests.fakes import AIRPORTS


def test_percentile_rank_monotone_and_bounded():
    pct = percentile_rank([10.0, 20.0, 30.0, 40.0])
    assert pct == [0.0, pytest.approx(1 / 3), pytest.approx(2 / 3), 1.0]


def test_percentile_rank_direction_down_flips():
    assert percentile_rank([10.0, 20.0], direction="down") == [1.0, 0.0]


def test_percentile_rank_ties_get_average_rank():
    pct = percentile_rank([5.0, 5.0, 9.0])
    assert pct[0] == pct[1] == pytest.approx(0.25)
    assert pct[2] == 1.0


def test_percentile_rank_none_preserved_and_singleton_is_half():
    assert percentile_rank([None, 3.0, None]) == [None, 0.5, None]
    assert percentile_rank([None]) == [None]
    assert percentile_rank([]) == []


def test_peer_group_key():
    bos = next(a for a in AIRPORTS if a.iata == "BOS")
    assert peer_group_key(bos, "hub_class") == "large"
    assert peer_group_key(bos, "region") == "ANE"
    assert peer_group_key(bos, "all") == "all"


def test_percentiles_by_group_partitions_by_hub_class():
    refs = [a for a in AIRPORTS if a.iata in {"BOS", "LAX", "PVD", "MHT"}]  # 2 large, 2 small
    vals = [1.0, 2.0, 100.0, 200.0]
    pct = percentiles_by_group(refs, vals, "up", "hub_class")
    by = dict(zip([r.iata for r in refs], pct, strict=True))
    assert by["BOS"] == 0.0 and by["LAX"] == 1.0
    assert by["PVD"] == 0.0 and by["MHT"] == 1.0  # small hubs compared only with each other


def test_percentiles_by_group_all_is_global():
    refs = [a for a in AIRPORTS if a.iata in {"BOS", "LAX", "PVD", "MHT"}]
    pct = percentiles_by_group(refs, [1.0, 2.0, 100.0, 200.0], "up", "all")
    assert pct == [0.0, pytest.approx(1 / 3), pytest.approx(2 / 3), 1.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_percentiles.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/airport_agent/scoring/percentiles.py`:
```python
"""Percentile ranks within peer groups (design 02: normalize within hub class by default)."""
from __future__ import annotations

from collections import defaultdict

from airport_agent.contracts import AirportRef, Direction, PeerGroup


def percentile_rank(values: list[float | None], direction: Direction = "up") -> list[float | None]:
    """Average-rank percentile in [0, 1] among non-None values. One value -> 0.5. 'down' flips."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out: list[float | None] = [None] * len(values)
    n = len(idx)
    if n == 0:
        return out
    if n == 1:
        out[idx[0]] = 0.5
        return out
    order = sorted(idx, key=lambda i: values[i])  # type: ignore[arg-type]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2  # 0-based average rank across the tie block
        pct = avg_rank / (n - 1)
        for k in range(i, j + 1):
            out[order[k]] = 1.0 - pct if direction == "down" else pct
        i = j + 1
    return out


def peer_group_key(ref: AirportRef, peer_group: PeerGroup) -> str:
    if peer_group == "hub_class":
        return ref.hub_size
    if peer_group == "region":
        return ref.faa_region
    return "all"


def percentiles_by_group(refs: list[AirportRef], values: list[float | None], direction: Direction,
                         peer_group: PeerGroup) -> list[float | None]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(refs):
        groups[peer_group_key(r, peer_group)].append(i)
    out: list[float | None] = [None] * len(refs)
    for members in groups.values():
        pct = percentile_rank([values[i] for i in members], direction)
        for i, p in zip(members, pct, strict=True):
            out[i] = p
    return out
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `uv run pytest tests/scoring/test_percentiles.py -q && uv run ruff check .`

```bash
git add src/airport_agent/scoring/percentiles.py tests/scoring/test_percentiles.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): percentile ranks within peer groups"
```

---

### Task 3: Scorer (composite score, contributions, coverage, low_confidence)

**Files:**
- Create: `src/airport_agent/scoring/scorer.py`, `tests/scoring/test_scorer.py`

**Interfaces:**
- Consumes: `Preset`, `percentiles_by_group`, contracts `FeatureMatrix`, `MetricSpec`, `ScoreRow`, `load_pillars`.
- Produces:
  ```python
  class ScoringResult(BaseModel):   # not a contract type; internal to scoring
      rows: list[ScoreRow]                     # sorted by score desc, rank 1..n
      weights: dict[str, float]                # P1..P5 -> w_p ; metric_id -> nominal within-pillar w_m (over all scoreable metrics of the preset)
      percentiles: dict[str, dict[str, float | None]]   # metric_id -> {iata: pct}
      pillar_scores: dict[str, dict[str, float]]        # iata -> {P1..P5: 0..100 sub-score, renormalized within pillar}
      scored_metric_ids: list[str]
  class Scorer:
      def __init__(self, specs: list[MetricSpec], pillars_cfg: dict[str, dict] | None = None): ...
      def scoreable_ids(self, preset: Preset, candidate_ids: list[str] | None = None) -> list[str]
      def score(self, fm: FeatureMatrix, preset: Preset) -> ScoringResult
  ```
  Rules (design 02): percentiles within `fm.peer_group`, except metrics of a pillar whose registry `pillars` block has `normalize_within: hub_class` (P5) — those ALWAYS use `"hub_class"`. Direction flips for `down` metrics. Missing (None) ⇒ metric excluded for that airport and within-pillar relative weights renormalized over available metrics; a pillar with no available metric gets weight 0 for that airport and pillar weights renormalize over the remaining pillars. `coverage` = available scoreable metrics ÷ scoreable metrics. `low_confidence` = any pillar with preset weight > 0 has per-airport pillar coverage < 0.5. `score` = Σ_p w_p' Σ_m w_m' pct × 100 ∈ [0,100]; `metric_contrib[m] = w_p' × w_m' × pct × 100` (effective renormalized weights, so contributions sum to score); `pillar_contrib[p]` = Σ of its metric contribs. `pillar_scores[iata][p]` = Σ_m w_m' pct × 100 (0..100 within-pillar sub-score; the "congestion index" is `pillar_scores[iata]["P2"]`).

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_scorer.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import FeatureMatrix
from airport_agent.scoring.presets import load_presets
from airport_agent.scoring.scorer import Scorer
from tests.fakes import AIRPORTS

REFS = {a.iata: a for a in AIRPORTS}


def _fm(iatas, metric_ids, values, horizon="12m", peer_group="hub_class"):
    return FeatureMatrix(airports=[REFS[i] for i in iatas], metric_ids=metric_ids, horizon=horizon,
                         values=values, peer_group=peer_group)


@pytest.fixture
def scorer(specs):
    return Scorer(specs)


@pytest.fixture
def balanced():
    return load_presets()["balanced"]


def test_scoreable_ids_excludes_tier_c_and_excluded(scorer, balanced, by_id):
    ids = scorer.scoreable_ids(balanced)
    assert "asv_utilization" not in ids and "dscr" not in ids  # tier C
    assert "aip_per_enpl_10y" not in ids  # excluded by preset
    assert "load_factor" in ids and "pax_per_gate" in ids  # tier A and B are scoreable
    assert all(by_id[i].tier != "C" for i in ids)


def test_contributions_sum_to_score_and_formula(scorer, balanced):
    # two large hubs, one metric per pillar P1..P5 -> percentiles 0/1
    ids = ["load_factor", "avg_dep_delay_min", "carrier_hhi", "cbsa_population", "cpe_usd"]
    fm = _fm(["BOS", "LAX"], ids, [[0.80, 10.0, 1000.0, 1e6, 10.0], [0.90, 20.0, 2000.0, 2e6, 20.0]])
    res = scorer.score(fm, balanced)
    by = {r.ref.iata: r for r in res.rows}
    for r in res.rows:
        assert r.score == pytest.approx(sum(r.metric_contrib.values()))
        assert r.score == pytest.approx(sum(r.pillar_contrib.values()))
    # LAX: higher LF (up) -> pct 1 -> P1 contrib = 0.30*1*1*100 = 30; delay up -> 25; hhi down -> 0; pop up -> 15; cpe down -> 0
    assert by["LAX"].metric_contrib["load_factor"] == pytest.approx(30.0)
    assert by["LAX"].metric_contrib["carrier_hhi"] == pytest.approx(0.0)
    assert by["LAX"].score == pytest.approx(70.0)
    assert by["BOS"].score == pytest.approx(30.0)  # hhi + cpe (down metrics) give BOS 15 + 15
    assert by["LAX"].rank == 1 and by["BOS"].rank == 2
    assert res.weights["P1"] == 0.30 and res.weights["load_factor"] == pytest.approx(1.0)


def test_missing_metric_renormalizes_and_reports_coverage(scorer, balanced):
    ids = ["load_factor", "spill_proxy", "avg_dep_delay_min"]
    fm = _fm(["BOS", "LAX", "SFO"], ids, [[0.80, 0.05, 10.0], [0.90, None, 20.0], [0.85, 0.07, 15.0]])
    res = scorer.score(fm, balanced)
    lax = next(r for r in res.rows if r.ref.iata == "LAX")
    assert lax.coverage == pytest.approx(2 / 3)
    assert "spill_proxy" not in lax.metric_contrib
    # with spill missing, LF carries the whole P1 weight for LAX: pct(LF)=1 -> P1 contrib = 0.30/(0.30+0.25)*100
    assert lax.pillar_contrib["P1"] == pytest.approx(0.30 / 0.55 * 100)


def test_low_confidence_when_pillar_coverage_below_half(scorer, balanced):
    ids = ["load_factor", "spill_proxy", "pax_per_capita", "enpl_cagr_3y"]  # four P1 metrics
    fm = _fm(["BOS", "LAX"], ids, [[0.8, 0.05, 4.0, 0.03], [0.9, None, None, None]], horizon="3y")
    res = scorer.score(fm, balanced)
    by = {r.ref.iata: r for r in res.rows}
    assert by["LAX"].low_confidence is True
    assert by["BOS"].low_confidence is False


def test_p5_always_normalized_within_hub_class_even_when_peer_group_all(scorer, balanced):
    # BOS large vs PVD small: with peer_group=all, cpe (down) would give PVD pct 1; within hub class both are 0.5
    fm = _fm(["BOS", "PVD"], ["cpe_usd"], [[18.5], [8.9]], peer_group="all")
    res = scorer.score(fm, balanced)
    assert res.percentiles["cpe_usd"] == {"BOS": 0.5, "PVD": 0.5}


def test_non_p5_metric_uses_requested_peer_group(scorer, balanced):
    fm = _fm(["BOS", "PVD"], ["load_factor"], [[0.82], [0.84]], peer_group="all")
    res = scorer.score(fm, balanced)
    assert res.percentiles["load_factor"] == {"BOS": 0.0, "PVD": 1.0}


def test_metric_weight_overrides_change_within_pillar_split(scorer):
    te = load_presets()["terminal_expansion"]
    fm = _fm(["BOS", "LAX"], ["pax_per_gate", "imc_capacity_ratio"], [[400000.0, 0.7], [500000.0, 0.8]])
    res = scorer.score(fm, te)
    # only P2 metrics are in the matrix -> P2's effective pillar weight renormalizes to 1.0;
    # pax_per_gate relative 3.0 vs imc 1.0 -> LAX gets 1.0 * 3/4 * 1 * 100 from pax_per_gate
    lax = next(r for r in res.rows if r.ref.iata == "LAX")
    assert lax.metric_contrib["pax_per_gate"] == pytest.approx(75.0)
    assert lax.metric_contrib["imc_capacity_ratio"] == pytest.approx(0.0)  # direction down: LAX 0.8 > BOS 0.7
    assert res.pillar_scores["LAX"]["P2"] == pytest.approx(75.0)
    assert res.weights["pax_per_gate"] == pytest.approx(0.75)  # nominal within-pillar weight is unaffected


def test_all_none_row_scores_zero_with_zero_coverage(scorer, balanced):
    fm = _fm(["BOS", "LAX"], ["load_factor"], [[None], [0.9]])
    res = scorer.score(fm, balanced)
    bos = next(r for r in res.rows if r.ref.iata == "BOS")
    assert bos.score == 0.0 and bos.coverage == 0.0 and bos.low_confidence is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_scorer.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/airport_agent/scoring/scorer.py`:
```python
"""Composite scorer: percentiles within peer group -> weighted contributions -> ScoreRows (design 02).

score = sum_p w_p' * sum_m w_m' * pct * 100, with w' = weights renormalized over the metrics/pillars available
for the airport, so ScoreRow.metric_contrib sums to ScoreRow.score (frozen contract docstring in reports.py).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from airport_agent.contracts import FeatureMatrix, MetricSpec, ScoreRow, load_pillars
from airport_agent.scoring.percentiles import percentiles_by_group
from airport_agent.scoring.presets import PILLAR_IDS, Preset


class ScoringResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ScoreRow]
    weights: dict[str, float]
    percentiles: dict[str, dict[str, float | None]]
    pillar_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    scored_metric_ids: list[str] = Field(default_factory=list)


class Scorer:
    def __init__(self, specs: list[MetricSpec], pillars_cfg: dict[str, dict] | None = None) -> None:
        self._by_id = {s.id: s for s in specs}
        cfg = pillars_cfg if pillars_cfg is not None else load_pillars()
        self._pillar_norm = {p: cfg.get(p, {}).get("normalize_within") for p in PILLAR_IDS}

    def scoreable_ids(self, preset: Preset, candidate_ids: list[str] | None = None) -> list[str]:
        ids = candidate_ids if candidate_ids is not None else list(self._by_id)
        return [i for i in ids if i in self._by_id and self._by_id[i].tier != "C"
                and i not in preset.excluded_metrics]

    def score(self, fm: FeatureMatrix, preset: Preset) -> ScoringResult:
        ids = self.scoreable_ids(preset, fm.metric_ids)
        iatas = [a.iata for a in fm.airports]
        # 1) percentiles per metric (P5 always within hub class)
        pct: dict[str, list[float | None]] = {}
        for m in ids:
            spec = self._by_id[m]
            group = "hub_class" if self._pillar_norm.get(spec.pillar) == "hub_class" else fm.peer_group
            pct[m] = percentiles_by_group(fm.airports, fm.column(m), spec.direction, group)
        # 2) nominal weights: pillar -> w_p; metric -> relative weight normalized over all scoreable metrics in pillar
        by_pillar: dict[str, list[str]] = {p: [m for m in ids if self._by_id[m].pillar == p] for p in PILLAR_IDS}
        weights: dict[str, float] = {p: float(preset.pillars[p]) for p in PILLAR_IDS}
        for p, members in by_pillar.items():
            tot = sum(preset.metric_weight(m) for m in members)
            for m in members:
                weights[m] = preset.metric_weight(m) / tot if tot > 0 else 0.0
        # 3) per-airport effective weights and contributions
        rows: list[ScoreRow] = []
        pillar_scores: dict[str, dict[str, float]] = {}
        for i, ref in enumerate(fm.airports):
            avail = {m for m in ids if pct[m][i] is not None}
            pillar_w: dict[str, float] = {}
            metric_contrib: dict[str, float] = {}
            pillar_contrib: dict[str, float] = {}
            psub: dict[str, float] = {}
            low = False
            for p, members in by_pillar.items():
                have = [m for m in members if m in avail]
                if members and preset.pillars[p] > 0 and len(have) / len(members) < 0.5:
                    low = True
                if have:
                    pillar_w[p] = preset.pillars[p]
            tot_pw = sum(pillar_w.values())
            for p, wp in pillar_w.items():
                wp_eff = wp / tot_pw if tot_pw > 0 else 0.0
                have = [m for m in by_pillar[p] if m in avail]
                tot_m = sum(preset.metric_weight(m) for m in have)
                sub = 0.0
                for m in have:
                    wm_eff = preset.metric_weight(m) / tot_m if tot_m > 0 else 0.0
                    c = wp_eff * wm_eff * float(pct[m][i]) * 100.0  # type: ignore[arg-type]
                    metric_contrib[m] = c
                    sub += wm_eff * float(pct[m][i]) * 100.0  # type: ignore[arg-type]
                pillar_contrib[p] = sum(metric_contrib[m] for m in have)
                psub[p] = sub
            for p in PILLAR_IDS:
                pillar_contrib.setdefault(p, 0.0)
            score = sum(metric_contrib.values())
            coverage = len(avail) / len(ids) if ids else 0.0
            if not ids or not avail:
                low = True
            pillar_scores[ref.iata] = psub
            rows.append(ScoreRow(ref=ref, score=score, rank=0, pillar_contrib=pillar_contrib,
                                 metric_contrib=metric_contrib, coverage=coverage, low_confidence=low))
        rows.sort(key=lambda r: (-r.score, r.ref.iata))
        rows = [r.model_copy(update={"rank": k + 1}) for k, r in enumerate(rows)]
        percentiles = {m: dict(zip(iatas, pct[m], strict=True)) for m in ids}
        return ScoringResult(rows=rows, weights=weights, percentiles=percentiles, pillar_scores=pillar_scores,
                             scored_metric_ids=ids)
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `uv run pytest tests/scoring -q && uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports`

```bash
git add src/airport_agent/scoring/scorer.py tests/scoring/test_scorer.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): composite scorer with renormalization, coverage, low_confidence"
```

---

### Task 4: Calculators — distance bands & long-haul share (pax vs freight)

**Files:**
- Create: `src/airport_agent/scoring/calculators.py`, `tests/scoring/test_calculators.py`

**Interfaces:**
- Consumes: contracts `RouteTable`, `RouteRow`, `Metric`, `QualityFlag`, `Horizon`.
- Produces:
  - `BANDS = (("short", 0, 500), ("medium", 500, 1500), ("long", 1500, 3000), ("ultra", 3000, float("inf")))` — statute miles, lower bound inclusive, upper exclusive.
  - `distance_bands(routes: RouteTable, freight: bool = False) -> dict[str, float]` — shares that sum to 1 (or all 0.0 when no traffic). **Passenger variant** (`freight=False`): share of `departures` on rows with `seats > 0` (passenger-carrying flights). **Freight variant** (`freight=True`): share of `freight_lb`. Keys: `short, medium, long, ultra`.
  - `long_haul_share(routes: RouteTable, threshold_mi: float = 1500, freight: bool = False, horizon: Horizon = "12m") -> Metric` — `id="longhaul_dep_share"`, `unit="pct"`, `horizon=horizon`, `period_start/end`, `source_id`, `vintage` copied from `routes`; `value` = long-haul share (departures-based for pax, freight_lb-based for freight); `value=None` when there is no traffic of that kind. Quality flags: `QualityFlag(code="convention", message="long-haul = routes >= {threshold} statute miles (no ICAO/IATA standard); passenger variant weights departures with seats>0, freight variant weights freight lb")` always; plus `QualityFlag(code="truncated_routes", message="computed on the top-N routes returned by DataService.get_routes; tail omitted")` when `routes.truncated`.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_calculators.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import RouteRow, RouteTable
from airport_agent.scoring.calculators import BANDS, distance_bands, long_haul_share
from tests.fakes import FakeDataService


def _rt(rows, truncated=False):
    return RouteTable(iata="XXX", period_start="2025-05", period_end="2026-04", source_id="bts_t100",
                      vintage="2026-04", rows=rows, truncated=truncated)


def _row(mi, deps, seats, freight):
    return RouteRow(dest="D", dest_name=None, distance_mi=mi, departures=deps, seats=seats, passengers=seats,
                    freight_lb=freight, is_international=False)


def test_bands_definition_matches_design_02():
    assert [b[0] for b in BANDS] == ["short", "medium", "long", "ultra"]
    assert BANDS[1][1:] == (500, 1500) and BANDS[2][1:] == (1500, 3000)


def test_passenger_bands_share_departures_with_seats():
    rt = _rt([_row(400, 10, 100, 0), _row(1000, 20, 100, 0), _row(2000, 30, 100, 0), _row(5000, 40, 0, 1e6)])
    b = distance_bands(rt, freight=False)
    assert b == {"short": pytest.approx(10 / 60), "medium": pytest.approx(20 / 60), "long": pytest.approx(30 / 60),
                 "ultra": 0.0}


def test_freight_bands_share_freight_lb():
    rt = _rt([_row(400, 10, 100, 100.0), _row(5000, 1, 0, 900.0)])
    assert distance_bands(rt, freight=True) == {"short": 0.1, "medium": 0.0, "long": 0.0, "ultra": 0.9}


def test_bands_boundaries_lower_inclusive():
    rt = _rt([_row(500, 1, 10, 0), _row(1500, 1, 10, 0), _row(3000, 1, 10, 0)])
    assert distance_bands(rt) == {"short": 0.0, "medium": pytest.approx(1 / 3), "long": pytest.approx(1 / 3),
                                  "ultra": pytest.approx(1 / 3)}


def test_no_traffic_gives_zeros_and_none_metric():
    assert distance_bands(_rt([])) == {"short": 0.0, "medium": 0.0, "long": 0.0, "ultra": 0.0}
    assert long_haul_share(_rt([])).value is None


def test_long_haul_share_metric_carries_provenance_and_convention_flag():
    rt = _rt([_row(1000, 50, 100, 0), _row(2000, 50, 100, 0)], truncated=True)
    m = long_haul_share(rt, threshold_mi=1500, horizon="12m")
    assert m.id == "longhaul_dep_share" and m.unit == "pct" and m.horizon == "12m"
    assert m.value == pytest.approx(0.5)
    assert m.source_id == "bts_t100" and m.vintage == "2026-04"
    assert {q.code for q in m.quality} == {"convention", "truncated_routes"}


def test_threshold_is_adjustable():
    rt = _rt([_row(1000, 50, 100, 0), _row(2000, 50, 100, 0)])
    assert long_haul_share(rt, threshold_mi=900).value == pytest.approx(1.0)


def test_golden_anc_freight_long_haul_far_exceeds_passenger():
    rt = FakeDataService().get_routes("ANC", top_n=100)
    pax = long_haul_share(rt, freight=False).value
    frt = long_haul_share(rt, freight=True).value
    assert frt > 0.9 and pax < 0.3 and frt > pax
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_calculators.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/airport_agent/scoring/calculators.py`:
```python
"""Route-distance calculators (design 02 conventions): bands short<500 / medium 500-1500 / long 1500-3000 /
ultra >3000 statute miles; long-haul = >= 1,500 mi by default (adjustable). Passenger and freight separately."""
from __future__ import annotations

from airport_agent.contracts import Horizon, Metric, QualityFlag, RouteRow, RouteTable

BANDS: tuple[tuple[str, float, float], ...] = (
    ("short", 0, 500), ("medium", 500, 1500), ("long", 1500, 3000), ("ultra", 3000, float("inf")))

CONVENTION_NOTE = ("long-haul = routes >= {t:g} statute miles (no ICAO/IATA standard); passenger variant weights "
                   "departures with seats>0, freight variant weights freight lb")


def _weight(r: RouteRow, freight: bool) -> float:
    if freight:
        return float(r.freight_lb)
    return float(r.departures) if r.seats > 0 else 0.0


def distance_bands(routes: RouteTable, freight: bool = False) -> dict[str, float]:
    total = sum(_weight(r, freight) for r in routes.rows)
    out = {name: 0.0 for name, _, _ in BANDS}
    if total <= 0:
        return out
    for name, lo, hi in BANDS:
        out[name] = sum(_weight(r, freight) for r in routes.rows if lo <= r.distance_mi < hi) / total
    return out


def long_haul_share(routes: RouteTable, threshold_mi: float = 1500, freight: bool = False,
                    horizon: Horizon = "12m") -> Metric:
    total = sum(_weight(r, freight) for r in routes.rows)
    value = None if total <= 0 else sum(_weight(r, freight) for r in routes.rows
                                        if r.distance_mi >= threshold_mi) / total
    quality = [QualityFlag(code="convention", message=CONVENTION_NOTE.format(t=threshold_mi))]
    if routes.truncated:
        quality.append(QualityFlag(code="truncated_routes",
                                   message="computed on the top-N routes returned by DataService.get_routes; tail omitted"))
    return Metric(id="longhaul_dep_share", value=value, unit="pct", horizon=horizon,
                  period_start=routes.period_start, period_end=routes.period_end, source_id=routes.source_id,
                  vintage=routes.vintage, quality=quality)
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/scoring -q && uv run ruff check .
git add src/airport_agent/scoring/calculators.py tests/scoring/test_calculators.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): distance bands and long-haul share calculators"
```

---

### Task 5: Templated explanations

**Files:**
- Create: `src/airport_agent/scoring/explain.py`, `tests/scoring/test_explain.py`

**Interfaces:**
- Consumes: `ScoringResult`, `ScoreRow`, `MetricSpec`, `Metric`, `PILLAR_NAMES`.
- Produces (pure functions returning `str`, no LLM):
  - `fmt_value(spec: MetricSpec, value: float | None) -> str` — pct → `"6.1%"`, ratio → `"0.82"`, min → `"13.5 min"`, usd → `"$18.50"`, count/ops/seats/persons/pax → thousands separators, `None` → `"n/a"`.
  - `explain_rank(res: ScoringResult, by_id: dict[str, MetricSpec], evidence: dict[tuple[str, str], Metric], preset_name: str, horizon: str, peer_group: str) -> str` — first line: `"Ranked {n} airports with preset '{preset}' at horizon {horizon}; percentiles within {peer_group}."`; then for the top airport and each next-ranked pair: `"{A} ranks above {B} mainly on {pillar name} (+{delta:.0f}): {metric name} {valA} vs {valB} ({source_id}, through {period_end})"` using the pillar with the largest positive contribution difference and, within it, the metric with the largest difference; ends with the coverage sentence `"{k} of {n} airports have low confidence (pillar coverage < 50%)."` when k > 0.
  - `explain_compare(res: ScoringResult, by_id, evidence, iatas: list[str], horizon: str, peer_group: str) -> str` — `"Side-by-side at horizon {horizon} (percentiles within {peer_group}). Congestion index (P2 sub-score): A 62 · B 41. Largest gaps: {metric name}: A val (pct 0.90) vs B val (pct 0.20) ..."` (top 3 gaps by |pct difference|).
  - `explain_diagnose(iata: str, signals: list[tuple[str, bool, str]]) -> str` — `"Signals of unmet demand at {iata}: {n_true} of {n} present. ✔ {text} … ✘ {text}"`, one line per signal.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_explain.py`:
```python
from __future__ import annotations

from airport_agent.contracts import FeatureMatrix, Metric
from airport_agent.scoring.explain import explain_compare, explain_diagnose, explain_rank, fmt_value
from airport_agent.scoring.presets import load_presets
from airport_agent.scoring.scorer import Scorer
from tests.fakes import AIRPORTS

REFS = {a.iata: a for a in AIRPORTS}


def _metric(mid, iata, v, unit="pct"):
    return Metric(id=mid, value=v, unit=unit, horizon="12m", period_start="2025-05", period_end="2026-04",
                  source_id="bts_socrata", vintage="2026-04")


def test_fmt_value_units(by_id):
    assert fmt_value(by_id["enpl_cagr_5y"], 0.061) == "6.1%"
    assert fmt_value(by_id["load_factor"], 0.8234) == "0.82"
    assert fmt_value(by_id["avg_dep_delay_min"], 13.5) == "13.5 min"
    assert fmt_value(by_id["cpe_usd"], 18.5) == "$18.50"
    assert fmt_value(by_id["cbsa_population"], 4900000) == "4,900,000"
    assert fmt_value(by_id["load_factor"], None) == "n/a"


def test_explain_rank_names_pillar_metric_and_source(specs, by_id):
    fm = FeatureMatrix(airports=[REFS["BDL"], REFS["PVD"]], metric_ids=["enpl_cagr_5y", "load_factor"], horizon="5y",
                       values=[[0.061, 0.83], [0.023, 0.84]], peer_group="hub_class")
    # BDL medium, PVD small: different hub classes -> both pct 0.5; force peer_group all for a real ordering
    fm = fm.model_copy(update={"peer_group": "all"})
    res = Scorer(specs).score(fm, load_presets()["balanced"])
    ev = {("BDL", "enpl_cagr_5y"): _metric("enpl_cagr_5y", "BDL", 0.061),
          ("PVD", "enpl_cagr_5y"): _metric("enpl_cagr_5y", "PVD", 0.023),
          ("BDL", "load_factor"): _metric("load_factor", "BDL", 0.83, "ratio"),
          ("PVD", "load_factor"): _metric("load_factor", "PVD", 0.84, "ratio")}
    text = explain_rank(res, by_id, ev, "balanced", "5y", "all")
    assert text.startswith("Ranked 2 airports with preset 'balanced' at horizon 5y; percentiles within all.")
    assert "ranks above" in text and "Demand Pressure" in text
    assert "6.1%" in text and "2.3%" in text and "bts_socrata" in text and "2026-04" in text


def test_explain_compare_has_congestion_index_and_gaps(specs, by_id):
    fm = FeatureMatrix(airports=[REFS["LAX"], REFS["SNA"]], metric_ids=["avg_dep_delay_min", "taxi_out_p80_min"],
                       horizon="12m", values=[[12.9, 22.0], [13.9, 15.0]], peer_group="all")
    res = Scorer(specs).score(fm, load_presets()["congestion_relief"])
    ev = {("LAX", "avg_dep_delay_min"): _metric("avg_dep_delay_min", "LAX", 12.9, "min"),
          ("SNA", "avg_dep_delay_min"): _metric("avg_dep_delay_min", "SNA", 13.9, "min"),
          ("LAX", "taxi_out_p80_min"): _metric("taxi_out_p80_min", "LAX", 22.0, "min"),
          ("SNA", "taxi_out_p80_min"): _metric("taxi_out_p80_min", "SNA", 15.0, "min")}
    text = explain_compare(res, by_id, ev, ["LAX", "SNA"], "12m", "all")
    assert "Congestion index" in text and "LAX" in text and "SNA" in text
    assert "12.9 min" in text and "13.9 min" in text


def test_explain_diagnose_lists_signals():
    text = explain_diagnose("SFO", [("lf_spill", True, "high load factor with variable demand (spill likely)"),
                                    ("npias", False, "FAA NPIAS lists the airport as capacity constrained")])
    assert text.startswith("Signals of unmet demand at SFO: 1 of 2 present.")
    assert "✔ high load factor" in text and "✘ FAA NPIAS" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_explain.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/airport_agent/scoring/explain.py`:
```python
"""Templated, formula-driven explanations (design 02/03). No LLM in this path."""
from __future__ import annotations

from airport_agent.contracts import PILLAR_NAMES, Metric, MetricSpec
from airport_agent.scoring.scorer import ScoringResult

Evidence = dict[tuple[str, str], Metric]  # (iata, metric_id) -> Metric


def fmt_value(spec: MetricSpec, value: float | None) -> str:
    if value is None:
        return "n/a"
    u = spec.unit
    if u == "pct":
        return f"{value * 100:.1f}%"
    if u == "ratio":
        return f"{value:.2f}"
    if u == "min":
        return f"{value:.1f} min"
    if u == "usd":
        return f"${value:,.2f}"
    if u in ("count", "ops", "seats", "persons", "pax", "turns", "trips", "index"):
        return f"{value:,.0f}" if float(value).is_integer() or u != "turns" else f"{value:.1f}"
    return f"{value:g}"


def _pair_line(a: str, b: str, res: ScoringResult, by_id: dict[str, MetricSpec], ev: Evidence) -> str:
    ra = next(r for r in res.rows if r.ref.iata == a)
    rb = next(r for r in res.rows if r.ref.iata == b)
    pillars = sorted(ra.pillar_contrib, key=lambda p: ra.pillar_contrib[p] - rb.pillar_contrib.get(p, 0.0),
                     reverse=True)
    p = pillars[0]
    delta = ra.pillar_contrib[p] - rb.pillar_contrib.get(p, 0.0)
    metrics = [m for m in ra.metric_contrib if by_id[m].pillar == p]
    if not metrics:
        return f"{a} ranks above {b} on {PILLAR_NAMES[p]} (+{delta:.0f})."
    m = max(metrics, key=lambda x: ra.metric_contrib[x] - rb.metric_contrib.get(x, 0.0))
    ma, mb = ev.get((a, m)), ev.get((b, m))
    va = fmt_value(by_id[m], ma.value if ma else None)
    vb = fmt_value(by_id[m], mb.value if mb else None)
    src = f"{ma.source_id}, through {ma.period_end}" if ma else "source n/a"
    return f"{a} ranks above {b} mainly on {PILLAR_NAMES[p]} (+{delta:.0f}): {by_id[m].name} {va} vs {vb} ({src})."


def explain_rank(res: ScoringResult, by_id: dict[str, MetricSpec], evidence: Evidence, preset_name: str,
                 horizon: str, peer_group: str) -> str:
    n = len(res.rows)
    lines = [f"Ranked {n} airports with preset '{preset_name}' at horizon {horizon}; percentiles within {peer_group}."]
    order = [r.ref.iata for r in res.rows]
    for a, b in zip(order, order[1:], strict=False):
        lines.append(_pair_line(a, b, res, by_id, evidence))
    low = sum(1 for r in res.rows if r.low_confidence)
    if low:
        lines.append(f"{low} of {n} airports have low confidence (pillar coverage < 50%).")
    return " ".join(lines)


def explain_compare(res: ScoringResult, by_id: dict[str, MetricSpec], evidence: Evidence, iatas: list[str],
                    horizon: str, peer_group: str) -> str:
    head = f"Side-by-side at horizon {horizon} (percentiles within {peer_group})."
    idx = " · ".join(f"{i} {res.pillar_scores.get(i, {}).get('P2', 0.0):.0f}" for i in iatas)
    parts = [head, f"Congestion index (P2 sub-score): {idx}."]
    gaps: list[tuple[float, str]] = []
    for m, per in res.percentiles.items():
        vals = [per.get(i) for i in iatas]
        known = [v for v in vals if v is not None]
        if len(known) >= 2:
            gaps.append((max(known) - min(known), m))
    gaps.sort(reverse=True)
    if gaps:
        cells = []
        for _, m in gaps[:3]:
            cell = " vs ".join(
                f"{i} {fmt_value(by_id[m], evidence[(i, m)].value if (i, m) in evidence else None)}"
                f" (pct {res.percentiles[m].get(i) if res.percentiles[m].get(i) is not None else 'n/a'})"
                for i in iatas)
            cells.append(f"{by_id[m].name}: {cell}")
        parts.append("Largest gaps: " + "; ".join(cells) + ".")
    return " ".join(parts)


def explain_diagnose(iata: str, signals: list[tuple[str, bool, str]]) -> str:
    n_true = sum(1 for _, ok, _ in signals if ok)
    lines = [f"Signals of unmet demand at {iata}: {n_true} of {len(signals)} present."]
    lines += [f"{'✔' if ok else '✘'} {text}" for _, ok, text in signals]
    return " ".join(lines)
```

Note for the implementer: `pct` in the compare text may print like `0.9`; format it with `f"{v:.2f}"` when not None (adjust the f-string; the test only asserts presence of names/values).

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/scoring -q && uv run ruff check .
git add src/airport_agent/scoring/explain.py tests/scoring/test_explain.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): templated explanations for rank/compare/diagnose"
```

---

### Task 6: Analyst — `rank`

**Files:**
- Create: `src/airport_agent/scoring/analyst.py`, `tests/scoring/test_analyst_rank.py`
- Modify: `src/airport_agent/scoring/__init__.py` (export `Analyst`, `Scorer`, `ScoringResult`)

**Interfaces:**
- Consumes: `DataService` (contract), `Scorer`, `load_presets`, `explain_rank`, contracts `AnalysisRequest`, `DeterministicReport`, `AirportFilter`, `Metric`.
- Produces: `class Analyst:` with `__init__(self, data: DataService, presets_path: Path | None = None)`, `rank(req) -> DeterministicReport` (this task), `compare/diagnose/distance_bands/long_haul_share` (Tasks 7–8), plus helpers `_resolve_airports(req) -> list[str]`, `_universe() -> list[AirportRef]`, `_evidence(iatas, metric_ids, horizon) -> tuple[list[Metric], Evidence]`.

Behaviour of `rank` (design 02/03):
1. `horizon = req.horizons[0]`; `preset = presets[req.scoring_preset or "balanced"]` (unknown preset name → `ValueError("unknown scoring preset …; choose one of …")` — never invent); `peer_group = req.peer_group or "hub_class"`.
2. Targets = `req.airports` if given else `[a.iata for a in data.list_airports(req.filter)]`. Empty → `ValueError("no airports match the filter")`.
3. Percentiles are computed against the **whole universe** in the peer groups (`data.list_airports(AirportFilter(limit=600))`), not only the targets — otherwise a lone large hub in a regional query gets 0.5 everywhere. Metric ids = `scorer.scoreable_ids(preset, req.focus_metrics)` if `focus_metrics` else `scorer.scoreable_ids(preset)`.
4. `fm = data.get_feature_matrix(universe_iatas, metric_ids, horizon, peer_group)`; `res = scorer.score(fm, preset)`; keep only rows for the targets, re-rank 1..n among targets (sorted by score desc), percentiles restricted to targets.
5. Evidence: for each target, `data.get_profile(iata, horizons=(horizon,))` → collect `Metric`s whose id ∈ metric_ids from `profile.metrics[horizon]` (value may be None; keep — provenance still valid); also collect `profile.curated_facts` into `curated_facts`.
6. `caveats` (always, in this order): `f"Percentiles computed within {peer_group} peer groups across {len(universe)} airports; P5 metrics always within hub class."`; `"Weights are the preset's nominal weights; when a metric is missing for an airport its within-pillar weight is renormalized over the available metrics (see coverage)."`; `"Tier B metrics (curated YAML) contribute only where curated data exists; tier C metrics are never scored."`; a warning `"peer_group '{pg}' widens comparison beyond hub class — scale metrics (P5, size) are less comparable"` when peer_group != hub_class; `"Long-haul convention: routes >= 1,500 mi"` only if `longhaul_dep_share` is among the scored metrics; `"Load factor is interpreted via the spill model (with spill_proxy), not an absolute cutoff"` if `load_factor` is scored; each distinct `MetricSpec.caveats` string of the scored metrics (deduplicated, in registry order).
7. `explanation = explain_rank(res_targets, by_id, evidence, preset.name, horizon, peer_group)`.
8. Return `DeterministicReport(question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon, peer_group=peer_group, rows=rows, comparison=None, evidence=..., explanation=..., caveats=..., curated_facts=..., percentiles=...)`.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_analyst_rank.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import AirportFilter, AnalysisRequest, DeterministicReport
from airport_agent.scoring.analyst import Analyst


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_rank_new_england_terminal_expansion(analyst):
    req = AnalysisRequest(question_type="rank", filter=AirportFilter(faa_regions=["ANE"]),
                          scoring_preset="terminal_expansion", horizons=["5y"])
    rep = analyst.rank(req)
    assert isinstance(rep, DeterministicReport)
    assert rep.preset == "terminal_expansion" and rep.horizon == "5y" and rep.peer_group == "hub_class"
    assert [r.ref.iata for r in rep.rows] and {r.ref.faa_region for r in rep.rows} == {"ANE"}
    assert [r.rank for r in rep.rows] == list(range(1, len(rep.rows) + 1))
    assert all(0 <= r.score <= 100 for r in rep.rows)
    assert rep.weights["P1"] == 0.35 and "load_factor" in rep.weights
    assert rep.percentiles and set(rep.percentiles["load_factor"]) == {r.ref.iata for r in rep.rows}
    assert rep.explanation.startswith("Ranked")
    assert any("Percentiles computed within hub_class" in c for c in rep.caveats)


def test_rank_evidence_carries_source_and_vintage(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"]))
    assert rep.evidence and all(m.source_id and m.vintage for m in rep.evidence)
    assert {m.id for m in rep.evidence} >= {"load_factor", "avg_dep_delay_min"}
    assert rep.curated_facts and {f.iata for f in rep.curated_facts} <= {"SFO", "LAX"}


def test_rank_percentiles_use_universe_not_only_targets(analyst):
    # BOS alone among the targets is a large hub; its percentiles must still vary because the universe has 5 large hubs
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "PVD"], horizons=["12m"]))
    bos_pcts = {m: v["BOS"] for m, v in rep.percentiles.items() if v.get("BOS") is not None}
    assert len(set(bos_pcts.values())) > 1


def test_rank_default_preset_and_peer_group(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "JFK"]))
    assert rep.preset == "balanced" and rep.peer_group == "hub_class" and rep.horizon == "5y"


def test_rank_unknown_preset_is_rejected_never_invented(analyst):
    with pytest.raises(ValueError, match="unknown scoring preset"):
        analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS"], scoring_preset="made_up"))


def test_rank_focus_metrics_restricts_scored_set(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO"], horizons=["12m"],
                                       focus_metrics=["load_factor", "avg_dep_delay_min", "asv_utilization"]))
    assert set(rep.percentiles) == {"load_factor", "avg_dep_delay_min"}  # tier C dropped
    for r in rep.rows:
        assert set(r.metric_contrib) <= {"load_factor", "avg_dep_delay_min"}


def test_rank_region_peer_group_adds_warning(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "PVD"], peer_group="region"))
    assert rep.peer_group == "region" and any("widens comparison" in c for c in rep.caveats)


def test_rank_5y_horizon_marks_12m_only_metrics_missing_not_relabelled(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX"], horizons=["5y"]))
    # taxi_out_p80_min declares only 12m -> None at 5y for everyone -> not in any contrib
    assert all("taxi_out_p80_min" not in r.metric_contrib for r in rep.rows)
    taxi = [m for m in rep.evidence if m.id == "taxi_out_p80_min"]
    assert taxi and all(m.value is None and m.horizon == "12m" for m in taxi)


def test_rank_empty_filter_result_raises(analyst):
    with pytest.raises(ValueError, match="no airports"):
        analyst.rank(AnalysisRequest(question_type="rank", filter=AirportFilter(states=["ZZ"])))


def test_golden_congestion_relief_puts_npias_constrained_large_hubs_on_top(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO", "JFK", "ATL", "DEN"],
                                       scoring_preset="congestion_relief", horizons=["12m"]))
    top3 = [r.ref.iata for r in rep.rows[:3]]
    assert set(top3) <= {"SFO", "JFK", "BOS", "LAX"}  # NPIAS constrained/severe in the fake; DEN/ATL below
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_analyst_rank.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/airport_agent/scoring/analyst.py`:
```python
"""Deterministic Analyst — implements contracts.DeterministicAnalyst over a DataService (design 02/03)."""
from __future__ import annotations

from pathlib import Path

from airport_agent.contracts import (
    AirportFilter,
    AirportRef,
    AnalysisRequest,
    CuratedFact,
    DeterministicReport,
    Horizon,
    Metric,
    PeerGroup,
    ScoreRow,
)
from airport_agent.contracts.data_service import DataService
from airport_agent.scoring.explain import Evidence, explain_rank
from airport_agent.scoring.presets import Preset, load_presets
from airport_agent.scoring.scorer import Scorer, ScoringResult

UNIVERSE_LIMIT = 600
LONGHAUL_CONVENTION = "Long-haul convention: routes >= 1,500 statute miles (bands short<500, medium 500-1500, long 1500-3000, ultra>3000); passenger and freight computed separately"
SPILL_CONVENTION = "Load factor is interpreted via the spill model (with spill_proxy), not an absolute cutoff"


class Analyst:
    def __init__(self, data: DataService, presets_path: Path | None = None) -> None:
        self.data = data
        self.specs = data.describe_metrics()
        self.by_id = {s.id: s for s in self.specs}
        self.presets = load_presets(presets_path)
        self.scorer = Scorer(self.specs)

    # ---- helpers -------------------------------------------------------------------------------
    def _preset(self, name: str | None) -> Preset:
        key = name or "balanced"
        if key not in self.presets:
            raise ValueError(f"unknown scoring preset {key!r}; choose one of {sorted(self.presets)}")
        return self.presets[key]

    def _resolve_airports(self, req: AnalysisRequest) -> list[str]:
        if req.airports:
            return list(dict.fromkeys(req.airports))
        assert req.filter is not None  # guaranteed by AnalysisRequest validator
        iatas = [a.iata for a in self.data.list_airports(req.filter)]
        if not iatas:
            raise ValueError("no airports match the filter")
        return iatas

    def _universe(self) -> list[AirportRef]:
        return self.data.list_airports(AirportFilter(limit=UNIVERSE_LIMIT))

    def _evidence(self, iatas: list[str], metric_ids: list[str], horizon: Horizon
                  ) -> tuple[list[Metric], Evidence, list[CuratedFact]]:
        wanted = set(metric_ids)
        flat: list[Metric] = []
        ev: Evidence = {}
        facts: list[CuratedFact] = []
        for i in iatas:
            prof = self.data.get_profile(i, horizons=(horizon,))
            for m in prof.metrics.get(horizon, []):
                if m.id in wanted:
                    flat.append(m)
                    ev[(i, m.id)] = m
            facts.extend(prof.curated_facts)
        return flat, ev, facts

    def _score_targets(self, targets: list[str], metric_ids: list[str], horizon: Horizon, peer_group: PeerGroup,
                       preset: Preset) -> tuple[ScoringResult, int]:
        universe = self._universe()
        uni_iatas = [a.iata for a in universe]
        for t in targets:
            if t not in uni_iatas:
                uni_iatas.append(t)  # let DataService raise KeyError for unknown iata
        fm = self.data.get_feature_matrix(uni_iatas, metric_ids, horizon, peer_group)
        res = self.scorer.score(fm, preset)
        keep = set(targets)
        rows = [r for r in res.rows if r.ref.iata in keep]
        rows.sort(key=lambda r: (-r.score, r.ref.iata))
        rows = [r.model_copy(update={"rank": k + 1}) for k, r in enumerate(rows)]
        pcts = {m: {i: v for i, v in per.items() if i in keep} for m, per in res.percentiles.items()}
        sub = {i: s for i, s in res.pillar_scores.items() if i in keep}
        return ScoringResult(rows=rows, weights=res.weights, percentiles=pcts, pillar_scores=sub,
                             scored_metric_ids=res.scored_metric_ids), len(uni_iatas)

    def _caveats(self, metric_ids: list[str], peer_group: PeerGroup, n_universe: int) -> list[str]:
        out = [f"Percentiles computed within {peer_group} peer groups across {n_universe} airports; P5 metrics always within hub class.",
               "Weights are the preset's nominal weights; when a metric is missing for an airport its within-pillar weight is renormalized over the available metrics (see coverage).",
               "Tier B metrics (curated YAML) contribute only where curated data exists; tier C metrics are never scored."]
        if peer_group != "hub_class":
            out.append(f"peer_group '{peer_group}' widens comparison beyond hub class — scale metrics (P5, size) are less comparable")
        if "longhaul_dep_share" in metric_ids:
            out.append(LONGHAUL_CONVENTION)
        if "load_factor" in metric_ids:
            out.append(SPILL_CONVENTION)
        for m in metric_ids:
            for c in self.by_id[m].caveats:
                if c not in out:
                    out.append(c)
        return out

    # ---- DeterministicAnalyst -------------------------------------------------------------------
    def rank(self, req: AnalysisRequest) -> DeterministicReport:
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset)
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        metric_ids = self.scorer.scoreable_ids(preset, req.focus_metrics) if req.focus_metrics \
            else self.scorer.scoreable_ids(preset)
        res, n_uni = self._score_targets(targets, metric_ids, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, metric_ids, horizon)
        rows: list[ScoreRow] = res.rows
        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=rows, comparison=None, evidence=evidence,
            explanation=explain_rank(res, self.by_id, ev, preset.name, horizon, peer_group),
            caveats=self._caveats(metric_ids, peer_group, n_uni), curated_facts=facts, percentiles=res.percentiles)
```

Update `src/airport_agent/scoring/__init__.py`:
```python
"""Deterministic scoring: presets, percentiles, scorer, calculators, explanations, Analyst."""
from __future__ import annotations

from airport_agent.scoring.analyst import Analyst
from airport_agent.scoring.presets import Preset, default_presets_path, load_presets
from airport_agent.scoring.scorer import Scorer, ScoringResult

__all__ = ["Analyst", "Preset", "Scorer", "ScoringResult", "default_presets_path", "load_presets"]
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/scoring -q && uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports
git add src/airport_agent/scoring tests/scoring/test_analyst_rank.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): Analyst.rank over DataService with universe percentiles"
```

---

### Task 7: Analyst — `compare`, `distance_bands`, `long_haul_share`

**Files:**
- Modify: `src/airport_agent/scoring/analyst.py`
- Create: `tests/scoring/test_analyst_compare.py`

**Interfaces:**
- Produces: `Analyst.compare(req) -> DeterministicReport` (`comparison` = `{metric_id: {iata: value}}` for the compared metric set at `req.horizons[0]`, `rows` = ScoreRows for the targets under `req.scoring_preset or "balanced"`, `percentiles` restricted to targets, `explanation = explain_compare(...)`), `Analyst.distance_bands(iata, horizon="12m", freight=False) -> dict[str, float]`, `Analyst.long_haul_share(iata, threshold_mi=1500, horizon="12m", freight=False) -> Metric` (both fetch `data.get_routes(iata, horizon=horizon, top_n=1000)` and delegate to `calculators`).
- Compared metric set = `req.focus_metrics` filtered to registry ids (tier C allowed in `comparison`/`evidence` as `None` values so the report can say "not available") if given; else all scoreable ids of the preset. Percentiles/rows only over scoreable ids.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_analyst_compare.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest, Metric
from airport_agent.scoring.analyst import Analyst

P2 = ["pct_arr_delay_gt15", "avg_dep_delay_min", "nas_delay_share", "taxi_out_p80_min", "ops_per_runway",
      "npias_capacity_label", "peak_hour_ops_ratio", "slot_or_cap_flag"]


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_compare_lax_vs_sna_congestion(analyst):
    req = AnalysisRequest(question_type="compare", airports=["LAX", "SNA"], focus_metrics=P2, horizons=["12m"],
                          scoring_preset="congestion_relief")
    rep = analyst.compare(req)
    assert rep.question_type == "compare" and rep.comparison is not None
    assert set(rep.comparison) == set(P2)
    assert rep.comparison["avg_dep_delay_min"] == {"LAX": 12.9, "SNA": 13.9}
    assert {r.ref.iata for r in rep.rows} == {"LAX", "SNA"}
    assert "Congestion index" in rep.explanation
    assert rep.evidence and all(m.source_id and m.vintage for m in rep.evidence)
    assert set(rep.percentiles) == set(P2)


def test_compare_defaults_to_all_scoreable_metrics(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "BDL"]))
    assert rep.comparison is not None and "load_factor" in rep.comparison and "asv_utilization" not in rep.comparison
    assert rep.preset == "balanced" and rep.horizon == "5y"


def test_compare_tier_c_focus_metric_reported_as_unavailable(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "LAX"], horizons=["12m"],
                                          focus_metrics=["load_factor", "asv_utilization"]))
    assert rep.comparison["asv_utilization"] == {"BOS": None, "LAX": None}
    assert "asv_utilization" not in rep.percentiles
    assert any("asv_utilization" in c or "not computable" in c.lower() or "ASV" in c for c in rep.caveats)


def test_compare_single_airport_allowed(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["SFO"], horizons=["12m"]))
    assert [r.ref.iata for r in rep.rows] == ["SFO"]


def test_distance_bands_and_long_haul_share_delegate(analyst):
    bands = analyst.distance_bands("ANC", horizon="12m", freight=False)
    assert set(bands) == {"short", "medium", "long", "ultra"} and abs(sum(bands.values()) - 1) < 1e-9
    m = analyst.long_haul_share("ANC", threshold_mi=1500, horizon="12m", freight=True)
    assert isinstance(m, Metric) and m.id == "longhaul_dep_share" and m.value > 0.9
    pax = analyst.long_haul_share("ANC", horizon="12m", freight=False)
    assert pax.value < m.value


def test_long_haul_unknown_airport_raises_key_error(analyst):
    with pytest.raises(KeyError):
        analyst.long_haul_share("ZZZ")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_analyst_compare.py -q` → `AttributeError: 'Analyst' object has no attribute 'compare'`.

- [ ] **Step 3: Implement** — add to `analyst.py` (imports: `from airport_agent.scoring.calculators import distance_bands as _bands, long_haul_share as _lhs`; `from airport_agent.scoring.explain import explain_compare`):

```python
    def compare(self, req: AnalysisRequest) -> DeterministicReport:
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset)
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        wanted = [m for m in (req.focus_metrics or []) if m in self.by_id] or self.scorer.scoreable_ids(preset)
        scoreable = self.scorer.scoreable_ids(preset, wanted)
        res, n_uni = self._score_targets(targets, scoreable, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, wanted, horizon)
        comparison = {m: {i: (ev[(i, m)].value if (i, m) in ev else None) for i in targets} for m in wanted}
        caveats = self._caveats(scoreable, peer_group, n_uni)
        for m in wanted:
            if self.by_id[m].tier == "C":
                caveats.append(f"{m} ({self.by_id[m].name}) is a documented gap (tier C): not computable from public data — reported as not available")
        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=res.rows, comparison=comparison, evidence=evidence,
            explanation=explain_compare(res, self.by_id, ev, targets, horizon, peer_group),
            caveats=caveats, curated_facts=facts, percentiles=res.percentiles)

    def distance_bands(self, iata: str, horizon: Horizon = "12m", freight: bool = False) -> dict[str, float]:
        return _bands(self.data.get_routes(iata, horizon=horizon, top_n=1000), freight=freight)

    def long_haul_share(self, iata: str, threshold_mi: float = 1500, horizon: Horizon = "12m",
                        freight: bool = False) -> Metric:
        return _lhs(self.data.get_routes(iata, horizon=horizon, top_n=1000), threshold_mi=threshold_mi,
                    freight=freight, horizon=horizon)
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/scoring -q && uv run ruff check .
git add src/airport_agent/scoring/analyst.py tests/scoring/test_analyst_compare.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): Analyst.compare + distance-band calculators"
```

---

### Task 8: Analyst — `diagnose` (unmet-demand evidence bundle) + Protocol conformance

**Files:**
- Modify: `src/airport_agent/scoring/analyst.py`
- Create: `tests/scoring/test_analyst_diagnose.py`, `tests/scoring/test_protocol.py`

**Interfaces:**
- Produces: `Analyst.diagnose(req) -> DeterministicReport`. Bundle metric ids (design 02): `DIAGNOSE_IDS = ["load_factor", "spill_proxy", "seats_per_dep_trend", "pct_arr_delay_gt15", "avg_dep_delay_min", "nas_delay_share", "taxi_out_p80_min", "npias_capacity_label", "slot_or_cap_flag", "peak_hour_ops_ratio", "imc_capacity_ratio", "taf_vs_actual_gap", "taf_cagr_10y"]`. Percentiles for these are computed within hub class over the universe at `req.horizons[0]` (via `_score_targets` with the `congestion_relief` preset unless `req.scoring_preset` given), `comparison` = `{metric_id: {iata: value}}`, `curated_facts` from profiles, `evidence` = the bundle Metrics.
- Signals (per airport, `(code, present, text)`; a signal is `False` when its inputs are None):
  - `lf_spill`: pct(load_factor) ≥ 0.75 and pct(spill_proxy) ≥ 0.5 → "high load factor with variable demand (spill likely): LF {v} (pct {p}), spill proxy {v} (pct {p})"
  - `upgauge`: pct(seats_per_dep_trend) ≥ 0.75 → "upgauging trend in top quartile (airlines add seats per departure — proxy for slot/runway constraint)"
  - `delay`: pct(avg_dep_delay_min) ≥ 0.75 or pct(pct_arr_delay_gt15) ≥ 0.75 → "delay in top quartile of peers ({A} {v})"
  - `nas`: pct(nas_delay_share) ≥ 0.75 → "high systemic (NAS) delay share"
  - `taxi`: pct(taxi_out_p80_min) ≥ 0.75 → "surface congestion: taxi-out p80 in top quartile"
  - `npias`: value(npias_capacity_label) ≥ 2 → "FAA NPIAS lists the airport as capacity constrained (label {label})"
  - `legal_cap`: value(slot_or_cap_flag) == 1 → "legal capacity constraint in force (slot level / hourly cap)"
  - `peak`: value(peak_hour_ops_ratio) ≥ 0.9 → "peak-hour operations at ≥90% of declared VMC rate"
  - `imc`: value(imc_capacity_ratio) ≤ 0.8 → "weather fragility: IMC rate ≤80% of VMC rate"
  - `taf_gap`: value(taf_vs_actual_gap) ≥ 1.03 → "FAA forecast runs ≥3% above latest actuals (forecast optimism / suppressed demand)"
  - `explanation` = for each airport `explain_diagnose(iata, signals)` joined by `" | "`; the signal texts include the formatted values via `fmt_value` where marked `{v}` and pct as `f"{p:.2f}"`.
- `caveats`: the standard `_caveats(...)` list + `"Signals are heuristics over percentiles within hub class (thresholds: top quartile = pct ≥ 0.75); they indicate, not prove, unmet demand"` + `"NPIAS constraint labels are partly circular for slot-controlled airports"` + `"Declared VMC/IMC capacities come from FAA Capacity Profiles 2014–2019 (curated)"` when `peak_hour_ops_ratio` or `imc_capacity_ratio` has a value.
- `tests/scoring/test_protocol.py`: `isinstance(Analyst(FakeDataService()), DeterministicAnalyst)`.

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_analyst_diagnose.py`:
```python
from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest
from airport_agent.scoring.analyst import DIAGNOSE_IDS, Analyst


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_diagnose_sfo_bundle(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"]))
    assert rep.question_type == "diagnose" and rep.comparison is not None
    assert set(rep.comparison) == set(DIAGNOSE_IDS)
    assert rep.comparison["load_factor"]["SFO"] == pytest.approx(0.80)
    assert rep.explanation.startswith("Signals of unmet demand at SFO:")
    assert "✔" in rep.explanation
    assert rep.curated_facts and rep.curated_facts[0].category == "slot_level"
    assert {m.id for m in rep.evidence} == set(DIAGNOSE_IDS)
    assert all(m.source_id and m.vintage for m in rep.evidence)
    assert any("heuristics" in c for c in rep.caveats) and any("circular" in c for c in rep.caveats)


def test_diagnose_sfo_flags_delay_and_npias_and_legal_cap(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO"], horizons=["12m"]))
    text = rep.explanation
    assert "✔ FAA NPIAS lists the airport as capacity constrained" in text
    assert "✔ legal capacity constraint in force" in text
    assert "✔ delay in top quartile" in text  # SFO has the worst delay among large hubs in the fake


def test_diagnose_small_airport_has_few_signals(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["PWM"], horizons=["12m"]))
    assert "✘ FAA NPIAS" in rep.explanation and "✘ legal capacity" in rep.explanation
    # tier-B metrics are None for PWM -> those signals absent, values reported as None
    assert rep.comparison["peak_hour_ops_ratio"]["PWM"] is None


def test_diagnose_multiple_airports_joined(analyst):
    rep = analyst.diagnose(AnalysisRequest(question_type="diagnose", airports=["SFO", "LAX"], horizons=["12m"]))
    assert " | " in rep.explanation and "at LAX:" in rep.explanation
```

`tests/scoring/test_protocol.py`:
```python
from __future__ import annotations

from airport_agent.contracts import DeterministicAnalyst
from airport_agent.scoring import Analyst
from tests.fakes import FakeDataService


def test_analyst_satisfies_protocol():
    assert isinstance(Analyst(FakeDataService()), DeterministicAnalyst)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/scoring/test_analyst_diagnose.py tests/scoring/test_protocol.py -q` → `ImportError: DIAGNOSE_IDS` / `AttributeError`.

- [ ] **Step 3: Implement** — add to `analyst.py` (import `explain_diagnose`, `fmt_value`):

```python
DIAGNOSE_IDS = ["load_factor", "spill_proxy", "seats_per_dep_trend", "pct_arr_delay_gt15", "avg_dep_delay_min",
                "nas_delay_share", "taxi_out_p80_min", "npias_capacity_label", "slot_or_cap_flag",
                "peak_hour_ops_ratio", "imc_capacity_ratio", "taf_vs_actual_gap", "taf_cagr_10y"]
LABELS = {0: "none", 1: "congested", 2: "constrained_2033", 3: "constrained_2028", 4: "severe_2033"}


    def _signals(self, iata: str, ev: Evidence, pcts: dict[str, dict[str, float | None]]
                 ) -> list[tuple[str, bool, str]]:
        def val(m: str) -> float | None:
            x = ev.get((iata, m))
            return None if x is None else x.value

        def pct(m: str) -> float | None:
            return pcts.get(m, {}).get(iata)

        def fv(m: str) -> str:
            return fmt_value(self.by_id[m], val(m))

        def fp(m: str) -> str:
            p = pct(m)
            return "n/a" if p is None else f"{p:.2f}"

        def ge(x: float | None, t: float) -> bool:
            return x is not None and x >= t

        def le(x: float | None, t: float) -> bool:
            return x is not None and x <= t

        delay_metric = "avg_dep_delay_min" if ge(pct("avg_dep_delay_min"), 0.75) else "pct_arr_delay_gt15"
        label = val("npias_capacity_label")
        return [
            ("lf_spill", ge(pct("load_factor"), 0.75) and ge(pct("spill_proxy"), 0.5),
             f"high load factor with variable demand (spill likely): LF {fv('load_factor')} (pct {fp('load_factor')}), spill proxy {fv('spill_proxy')} (pct {fp('spill_proxy')})"),
            ("upgauge", ge(pct("seats_per_dep_trend"), 0.75),
             "upgauging trend in top quartile (airlines add seats per departure — proxy for slot/runway constraint)"),
            ("delay", ge(pct("avg_dep_delay_min"), 0.75) or ge(pct("pct_arr_delay_gt15"), 0.75),
             f"delay in top quartile of peers ({self.by_id[delay_metric].name} {fv(delay_metric)})"),
            ("nas", ge(pct("nas_delay_share"), 0.75), "high systemic (NAS) delay share"),
            ("taxi", ge(pct("taxi_out_p80_min"), 0.75), "surface congestion: taxi-out p80 in top quartile"),
            ("npias", ge(label, 2),
             f"FAA NPIAS lists the airport as capacity constrained (label {LABELS.get(int(label), label) if label is not None else 'n/a'})"),
            ("legal_cap", val("slot_or_cap_flag") == 1, "legal capacity constraint in force (slot level / hourly cap)"),
            ("peak", ge(val("peak_hour_ops_ratio"), 0.9), "peak-hour operations at ≥90% of declared VMC rate"),
            ("imc", le(val("imc_capacity_ratio"), 0.8), "weather fragility: IMC rate ≤80% of VMC rate"),
            ("taf_gap", ge(val("taf_vs_actual_gap"), 1.03),
             "FAA forecast runs ≥3% above latest actuals (forecast optimism / suppressed demand)"),
        ]

    def diagnose(self, req: AnalysisRequest) -> DeterministicReport:
        horizon: Horizon = req.horizons[0]
        preset = self._preset(req.scoring_preset or "congestion_relief")
        peer_group: PeerGroup = req.peer_group or "hub_class"
        targets = self._resolve_airports(req)
        scoreable = self.scorer.scoreable_ids(preset, DIAGNOSE_IDS)
        res, n_uni = self._score_targets(targets, scoreable, horizon, peer_group, preset)
        evidence, ev, facts = self._evidence(targets, DIAGNOSE_IDS, horizon)
        comparison = {m: {i: (ev[(i, m)].value if (i, m) in ev else None) for i in targets} for m in DIAGNOSE_IDS}
        explanation = " | ".join(explain_diagnose(i, self._signals(i, ev, res.percentiles)) for i in targets)
        caveats = self._caveats(scoreable, peer_group, n_uni)
        caveats.append("Signals are heuristics over percentiles within hub class (thresholds: top quartile = pct ≥ 0.75); they indicate, not prove, unmet demand")
        caveats.append("NPIAS constraint labels are partly circular for slot-controlled airports")
        if any(comparison[m][i] is not None for m in ("peak_hour_ops_ratio", "imc_capacity_ratio") for i in targets):
            caveats.append("Declared VMC/IMC capacities come from FAA Capacity Profiles 2014–2019 (curated)")
        return DeterministicReport(
            question_type=req.question_type, preset=preset.name, weights=res.weights, horizon=horizon,
            peer_group=peer_group, rows=res.rows, comparison=comparison, evidence=evidence, explanation=explanation,
            caveats=caveats, curated_facts=facts, percentiles=res.percentiles)
```

(Place `DIAGNOSE_IDS`/`LABELS` at module level, the methods inside `Analyst`.) Note `_caveats` may append duplicate strings from `MetricSpec.caveats` that already say "circular"; that is fine — the tests check presence, not uniqueness. If a caveat string is already present, skip it (`if c not in caveats`).

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/scoring tests/contracts -q && uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports
git add src/airport_agent/scoring/analyst.py tests/scoring/test_analyst_diagnose.py tests/scoring/test_protocol.py
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "feat(scoring): Analyst.diagnose unmet-demand bundle; Protocol conformance test"
```

---

### Task 9: Golden ordering tests + limitations-log note (final)

**Files:**
- Create: `tests/scoring/test_goldens.py`
- Modify (append rows only): `docs/design/known-limitations-and-tradeoffs.md` — this is the one doc file the scoring workstream may touch, append-only, for decisions made in this plan.

**Interfaces:** none new.

- [ ] **Step 1: Write the golden tests (design 02 "Validation")**

`tests/scoring/test_goldens.py`:
```python
"""Golden checks from design 02 §Validation, run against FakeDataService (fixture values, not facts)."""
from __future__ import annotations

import pytest

from airport_agent.contracts import AnalysisRequest
from airport_agent.scoring import Analyst, load_presets


@pytest.fixture
def analyst(fake):
    return Analyst(fake)


def test_monotonicity_higher_up_metric_never_lowers_score(analyst, fake):
    # PVD vs a hypothetical: within the fake, ranking on a single up-metric orders by value
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["PVD", "MHT", "PWM"], horizons=["12m"],
                                       focus_metrics=["load_factor"], peer_group="all"))
    order = [r.ref.iata for r in rep.rows]
    assert order == sorted(order, key=lambda i: -rep.percentiles["load_factor"][i])
    assert order[0] == "PVD"  # highest load_factor in the fake among the three


def test_direction_flip_down_metric(analyst):
    rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["ATL", "JFK"], horizons=["12m"],
                                       focus_metrics=["carrier_hhi"], peer_group="all"))
    assert rep.rows[0].ref.iata == "JFK"  # lower HHI (less concentrated) ranks higher


def test_all_presets_produce_full_rankings(analyst):
    for name in load_presets():
        rep = analyst.rank(AnalysisRequest(question_type="rank", airports=["BOS", "LAX", "SFO", "JFK", "ATL", "DEN"],
                                           scoring_preset=name, horizons=["12m"]))
        assert len(rep.rows) == 6 and rep.preset == name


def test_scale_metrics_small_ne_airports_do_not_beat_bos_when_peer_group_all(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["BOS", "PVD", "MHT"], horizons=["12m"],
                                          focus_metrics=["cbsa_population", "route_count_nonstop"], peer_group="all"))
    for m in ("cbsa_population", "route_count_nonstop"):
        pct = rep.percentiles[m]
        assert pct["BOS"] > pct["PVD"] and pct["BOS"] > pct["MHT"]


def test_sfo_imc_ratio_below_lax(analyst):
    rep = analyst.compare(AnalysisRequest(question_type="compare", airports=["SFO", "LAX"], horizons=["12m"],
                                          focus_metrics=["imc_capacity_ratio"]))
    assert rep.comparison["imc_capacity_ratio"]["SFO"] < rep.comparison["imc_capacity_ratio"]["LAX"]
```

- [ ] **Step 2: Run** `uv run pytest tests/scoring/test_goldens.py -q` → all pass (these are checks of behaviour already built; if one fails, fix the implementation, not the test, unless the fake's fixture values contradict — then STOP and report `DECISION NEEDED`).

- [ ] **Step 3: Append to the limitations log** (append these rows at the end of the table; do not renumber existing rows):

```
| 22 | Scoring percentiles are computed against the whole airport universe (all airports the DataService lists, ≤600) partitioned by peer group, not only the airports in the question | Decision | A regional question still ranks each airport against its national hub-class peers; ranking a lone large hub among small hubs is meaningful | Stated in every report's caveats ("Percentiles computed within … across N airports"); FeatureMatrix fetch is one call | Accepted |
| 23 | Long-haul passenger share weights departures on rows with seats>0; freight share weights freight lb (RouteRow has no per-row pax/cargo departure split) | Decision | Mixed pax/cargo routes count fully as passenger departures | Convention flag on the Metric; freight variant answers cargo questions (ANC) | Accepted |
| 24 | Unmet-demand "signals" are quartile heuristics (pct ≥ 0.75 within hub class) over the diagnose bundle | Decision | Indicative, not causal; thresholds are stated | Explanation lists every signal ✔/✘ with values; caveat says "indicate, not prove" | Accepted |
```

- [ ] **Step 4: Full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && PYTHONIOENCODING=utf-8 uv run lint-imports
git add tests/scoring/test_goldens.py docs/design/known-limitations-and-tradeoffs.md
git -c user.name="Pete" -c user.email="Itamarr@voyager-labs.com" commit -m "test(scoring): design-02 goldens; docs: limitations rows 22-24"
```

---

## Self-review (done by the plan author)

- **Spec coverage (design 02 → tasks):** percentiles within hub class (T2/T3) ✔ · direction flip (T2) ✔ · missing → renormalize, coverage, low_confidence <50% (T3) ✔ · composite formula & contributions retained (T3) ✔ · four presets with exact weights (T1) ✔ · rank/compare/diagnose (T6–8) ✔ · congestion index (P2 sub-score in compare explanation, T5/T7) ✔ · calculators distance bands & long-haul share pax/freight (T4/T7) ✔ · templated explanations, no LLM (T5) ✔ · goldens (T9) ✔ · conventions stated (caveats in T6–8) ✔ · sensitivity table for DESIGN.md → Phase 4 doc-assembler can compute it via `Analyst.rank` across presets/horizons (not a Phase 2 deliverable; noted).
- **Placeholder scan:** none; every step has code. One deliberate note in T5 about pct formatting is guidance on an f-string, not a placeholder.
- **Type consistency:** `ScoringResult(rows, weights, percentiles, pillar_scores, scored_metric_ids)` used identically in T3/T5/T6–8; `Evidence = dict[tuple[str,str], Metric]` in T5/T6–8; `Analyst(data, presets_path=None)` exported from `airport_agent.scoring` (T6) — the name Phase 3 wires.
- **Assumption to surface to the human (not blocking):** `focus_metrics` on `rank` restricts the scored set (weights renormalize) — the alternative reading (focus only affects displayed evidence) was not chosen; `question_type="custom"` requests are handled by whichever method the composition root calls (`compare` when airports are given, `rank` for a filter — see plan 2c). `_score_targets` uses `_universe()` (`AirportFilter(limit=600)`), so with a real DataService that lists ~500 airports one `get_feature_matrix` call per question spans the universe.
