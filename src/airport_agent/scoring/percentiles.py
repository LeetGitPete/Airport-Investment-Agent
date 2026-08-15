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
