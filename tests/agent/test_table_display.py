"""Table display policy: identical content already on screen becomes a pointer, deterministically."""
from __future__ import annotations

from airport_agent.agent.table_display import apply_display_policy, table_hash
from airport_agent.contracts import Table


def _t(title: str = "Ranking", rows: list[list] | None = None, footnotes: list[str] | None = None) -> Table:
    return Table(title=title, columns=["iata", "score"], rows=rows or [["BOS", 71.2], ["BDL", 55.0]],
                 footnotes=footnotes or [])


# hash


def test_hash_is_stable_and_ignores_title_and_footnotes():
    assert table_hash(_t()) == table_hash(_t())
    assert table_hash(_t(title="Scores", footnotes=["Rank 1 = ..."])) == table_hash(_t())


def test_hash_changes_with_rows_or_columns():
    assert table_hash(_t(rows=[["BOS", 71.2]])) != table_hash(_t())
    assert table_hash(_t(rows=[["BDL", 55.0], ["BOS", 71.2]])) != table_hash(_t())  # order matters
    other = Table(title="Ranking", columns=["iata", "rank"], rows=[["BOS", 71.2], ["BDL", 55.0]])
    assert table_hash(other) != table_hash(_t())


def test_hash_is_short_hex():
    h = table_hash(_t())
    assert len(h) == 16 and int(h, 16) >= 0


# policy


def test_auto_first_sighting_stays_full_and_is_recorded():
    shown: dict[str, int] = {}
    out = apply_display_policy([_t()], shown, "auto", turn=1)
    assert out[0].shown_as == "full" and out[0].first_shown_turn is None
    assert shown == {table_hash(_t()): 1}


def test_auto_repeat_becomes_pointer_to_first_turn():
    shown = {table_hash(_t()): 1}
    out = apply_display_policy([_t(title="Scores")], shown, "auto", turn=3)
    assert out[0].shown_as == "pointer" and out[0].first_shown_turn == 1
    assert shown == {table_hash(_t()): 1}  # a pointer is not a new sighting


def test_auto_narrowed_table_is_new_content():
    shown = {table_hash(_t()): 1}
    narrowed = _t(rows=[["BOS", 71.2]])
    out = apply_display_policy([narrowed], shown, "auto", turn=2)
    assert out[0].shown_as == "full"
    assert shown[table_hash(narrowed)] == 2


def test_repeat_shows_everything_in_full_without_rewriting_first_turn():
    shown = {table_hash(_t()): 1}
    out = apply_display_policy([_t()], shown, "repeat", turn=4)
    assert out[0].shown_as == "full" and out[0].first_shown_turn is None
    assert shown == {table_hash(_t()): 1}


def test_minimal_pointers_like_auto():
    shown = {table_hash(_t()): 1}
    new = _t(rows=[["PVD", 40.0]])
    out = apply_display_policy([_t(), new], shown, "minimal", turn=2)
    assert [t.shown_as for t in out] == ["pointer", "full"]
    assert shown[table_hash(new)] == 2


def test_policy_does_not_mutate_inputs():
    t = _t()
    apply_display_policy([t], {table_hash(t): 1}, "auto", turn=2)
    assert t.shown_as == "full"
