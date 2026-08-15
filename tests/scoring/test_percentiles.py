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
