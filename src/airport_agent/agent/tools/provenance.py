"""provenance(): every tool result carries `[{source_id, vintage}]` (design 03 §Shared filter vocabulary)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ProvItem = Any  # Metric | RouteTable | SourceVintage | tuple[str, str] — anything carrying a source id


def _pair(item: ProvItem) -> tuple[str, str]:
    if isinstance(item, tuple):
        source_id, vintage = item
        return str(source_id), str(vintage)
    source_id = item.source_id
    # Metric/RouteTable carry `vintage`; SourceVintage is dated by the period it covers, else by its fetch time.
    vintage = getattr(item, "vintage", None) or getattr(item, "period_end", None) or getattr(item, "fetched_at", "")
    return str(source_id), str(vintage)


def prov(items: Iterable[ProvItem]) -> list[dict[str, str]]:
    """Return unique [{"source_id", "vintage"}] in first-seen order."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = _pair(item)
        if key not in seen:
            seen.add(key)
            out.append({"source_id": key[0], "vintage": key[1]})
    return out
