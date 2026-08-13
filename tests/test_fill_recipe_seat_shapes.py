# -*- coding: utf-8 -*-
"""Every seat shape the recipe names must be answered below it (T131).

`fill-recipe.md` §3c tabulates the seat shapes measured on
`pps-jeongbogonggae-donguiseo` and then works through them. It tabulated three
and answered two: the row for `at_para 64` — one unruled run holding label,
blank and marker together — was never revisited.

Two independent clean-room runs hit that row and both guessed. They guessed
right, which is what makes it worth a guard rather than a shrug: a table that
names a case is read as a promise to handle it, and the next reader may guess
differently.

The guard is derived, not a roster: it reads the seat numbers out of the table
and requires each to reappear in the prose that follows. A fourth row cannot be
added without an answer.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "skill" / "references" / "fill-recipe.md"

#: The §3c table's rows: `| 18 | ... |`, seat number in the first cell.
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
_TABLE_HEAD = "| `at_para` | seat | runs | where the rule is |"


def _table_rows_and_tail() -> tuple[list[int], str]:
    text = RECIPE.read_text(encoding="utf-8")
    assert _TABLE_HEAD in text, (
        "the §3c seat-shape table header moved; this guard reads that table and "
        "has to be re-pointed rather than deleted")
    start = text.index(_TABLE_HEAD)
    # The table ends at the first blank line after its header.
    end = text.index("\n\n", start)
    seats = [int(m.group(1)) for m in _ROW_RE.finditer(text[start:end])]
    return seats, text[end:]


def test_the_table_still_has_rows_to_check():
    """Non-vacuity: an empty parse would satisfy the assertion below."""
    seats, _ = _table_rows_and_tail()
    assert len(seats) >= 3, seats


def test_every_tabulated_seat_shape_is_answered_in_the_prose():
    seats, tail = _table_rows_and_tail()
    unanswered = [seat for seat in seats if f"at_para {seat}" not in tail]
    assert not unanswered, (
        "these seat shapes are named in the §3c table and never worked through "
        "below it, so a reader is left to guess — two clean-room runs already "
        "did: %s" % unanswered)


def test_the_marker_rule_is_stated_where_the_seat_is_answered():
    """The distinction that makes the third answer safe: the name is writable,
    the signature marker is reproduced verbatim and a human still signs."""
    _, tail = _table_rows_and_tail()
    assert "(서명 또는 인)" in tail
    # Pinned on the sentence that draws the distinction, not on a word that
    # appears elsewhere in the section: a mutation replacing this sentence
    # passed while `verbatim` survived in the at_para 20 passage above.
    assert "The name is yours to write; the marker is not." in tail, (
        "the answer must say the marker is reproduced unchanged and the name is "
        "not; without that sentence it reads as permission to overwrite a "
        "signature seat")
    assert "reproduced byte-identically" in tail
