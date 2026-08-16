"""Table display policy: never show the same grid twice (design 03, contracts-v2).

A follow-up answered from memory rebuilds its tables from the same reports, so without this every
"tell me more" repeated the whole ranking and data matrix the user already has on screen. The rule is
deterministic: a table's identity is a hash of its CONTENT (columns + rows — not title, not footnotes),
kept per session with the answer turn where it first appeared in full. Identical content later in the
session becomes a `pointer` to that turn; different rows (a narrowed view, a re-sort, a new preset) hash
differently and show in full. The Concierge can only steer the mode (`Plan.table_display`), never pick
tables one by one, and no mode drops numbers: `repeat` re-shows, `minimal` lets renderers tuck NEW
tables behind a collapsed data section so prose leads.
"""
from __future__ import annotations

import hashlib
import json

from airport_agent.contracts import Table, TableDisplay

#: 64 bits of sha256 — plenty for "is this grid already on screen" within one session, and short
#: enough to live in the persisted session file without noise.
HASH_CHARS = 16


def table_hash(table: Table) -> str:
    """Content identity: same columns and rows in the same order -> same hash, whatever the title."""
    payload = json.dumps({"columns": table.columns, "rows": table.rows},
                         sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:HASH_CHARS]


def apply_display_policy(tables: list[Table], shown: dict[str, int], mode: TableDisplay, *,
                         turn: int) -> list[Table]:
    """Return copies of `tables` with `shown_as`/`first_shown_turn` set, and record this turn's new
    full sightings in `shown` (mutated in place — it is the session's memory).

    `repeat` never records: the tables were already on screen from an earlier turn, and re-showing them
    must not move the pointer target away from where they first appeared.
    """
    out: list[Table] = []
    for table in tables:
        digest = table_hash(table)
        first = shown.get(digest)
        if mode != "repeat" and first is not None:
            out.append(table.model_copy(update={"shown_as": "pointer", "first_shown_turn": first}))
            continue
        if first is None:
            shown[digest] = turn
        out.append(table.model_copy(update={"shown_as": "full", "first_shown_turn": None}))
    return out
