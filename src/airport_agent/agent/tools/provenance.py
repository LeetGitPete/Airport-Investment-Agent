"""Provenance: every tool result says where its data came from (design 03 §Shared filter vocabulary).

Two pieces live here. `prov()` turns whatever a tool holds — metrics, route tables, source vintages —
into `[{source_id, vintage, period_start?, period_end?}]`. `ProvenanceSpec` is the *declaration* a tool
makes at registration: which sources it reads, or an explicit statement that it reads none.

Why a declaration and not just the returned list: a sweep of every tool found
`find_airports` returning provenance that was silently empty — the key was never set, and the registry's
`setdefault` filled in `[]`, so 50 airports shipped with no source at all. A returned list can only
describe the call that happened; it cannot promise anything about the call that returns no rows, and it
cannot fail loudly when a new tool forgets. The declaration is the floor, checked at registration, so
"empty by accident" stops being expressible.

`ProvenanceSpec` cannot live on `ToolSpec` itself, which is frozen (`contracts/tools.py`).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

ProvItem = Any  # Metric | RouteTable | SourceVintage | tuple[str, str] — anything carrying a source id
#: Attached to a result whose tool promised sources but returned none, so the gap reaches the user.
PROVENANCE_GAP = "provenance_gap"


def _pair(item: ProvItem) -> tuple[str, str] | None:
    """(source_id, vintage) for one item, or None if it carries no source id (nothing to cite)."""
    if isinstance(item, tuple):
        source_id, vintage = item
        return str(source_id), str(vintage)
    source_id = getattr(item, "source_id", None)
    if source_id is None:
        return None
    # Metric/RouteTable carry `vintage`; SourceVintage is dated by the period it covers, else by its fetch time.
    vintage = getattr(item, "vintage", None) or getattr(item, "period_end", None) or getattr(item, "fetched_at", "")
    return str(source_id), str(vintage)


def _period(item: ProvItem) -> dict[str, str]:
    """The span the item covers, when it knows one. Metric and SourceVintage both carry these."""
    out = {}
    for key in ("period_start", "period_end"):
        value = getattr(item, key, None)
        if value:
            out[key] = str(value)
    return out


def prov(items: Iterable[ProvItem]) -> list[dict[str, str]]:
    """Return unique [{"source_id", "vintage", ...}] in first-seen order; items without a source id are skipped.

    The period keys are added when the item carries them, so a provenance table can show the span a
    source covers, not only when we fetched it. Consumers read by key, so the extra keys are inert
    for anything that only wants source_id and vintage.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = _pair(item)
        if key is not None and key not in seen:
            seen.add(key)
            out.append({"source_id": key[0], "vintage": key[1], **_period(item)})
    return out


@dataclass(frozen=True)
class ProvenanceSpec:
    """What a tool promises about its sources. Exactly one of the three forms is set.

    - `reads(...)` — the source ids this tool ALWAYS consults, true even for a call that matches
      nothing, because the source was still read. These become a floor under the returned list.
    - `derived(reason)` — the tool cites real sources, but which ones depends on the query (a scoring
      run cites whatever metrics it scored). No floor can be stated without lying, so there is none;
      an empty result still raises the gap note.
    - `none(reason)` — the tool returns no measured data at all (a registry definition). The reason is
      shown to the user rather than hidden.
    """

    sources: tuple[str, ...] = ()
    no_external_source: str | None = None
    derived_from: str | None = None

    def __post_init__(self) -> None:
        forms = [bool(self.sources), bool(self.no_external_source), bool(self.derived_from)]
        if sum(forms) != 1:
            raise ValueError("ProvenanceSpec takes exactly one form — reads(), derived() or none(); a "
                             "tool that cites nothing must say why")

    @classmethod
    def reads(cls, *source_ids: str) -> ProvenanceSpec:
        if not source_ids:
            raise ValueError("ProvenanceSpec.reads() needs at least one source id")
        return cls(sources=tuple(source_ids))

    @classmethod
    def derived(cls, reason: str) -> ProvenanceSpec:
        if not reason.strip():
            raise ValueError("ProvenanceSpec.derived() needs a reason the user can read")
        return cls(derived_from=reason.strip())

    @classmethod
    def none(cls, reason: str) -> ProvenanceSpec:
        if not reason.strip():
            raise ValueError("ProvenanceSpec.none() needs a reason the user can read")
        return cls(no_external_source=reason.strip())

    def missing_from(self, entries: list[dict[str, str]]) -> list[str]:
        """Declared source ids that the returned provenance did not account for."""
        present = {e.get("source_id") for e in entries}
        return [s for s in self.sources if s not in present]
