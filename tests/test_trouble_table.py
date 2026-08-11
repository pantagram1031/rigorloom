# -*- coding: utf-8 -*-
"""T97: integrity of the trouble table itself.

`docs/trouble-table.md` is the project's mechanism ledger — every lesson is
supposed to land in it, and six doc tests read it. Those tests only assert that
particular strings appear, so until now nothing checked the table's own shape.

That gap was not theoretical. `markdown_table_defects` has asserted cell-count
agreement for the shipped skill surface since T29/#37, but the trouble table is
not shipped in any bundle, so the check never reached it — and a row was in fact
broken: T41's `fix` cell contained a literal `|` inside a code span, which GFM
splits on regardless of the backticks, pushing that text into the `origin`
column and the real origin out of the table.

The checker is reused rather than rewritten, because it already splits GFM rows
the way GFM does rather than the way intuition suggests.
"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_module  # noqa: E402

TABLE = ROOT / "docs" / "trouble-table.md"
ROW_RE = re.compile(r"^\| (T\d+) ")


def _text() -> str:
    return TABLE.read_text(encoding="utf-8")


def _rows() -> list[tuple[int, str, str]]:
    """``[(line_number, id, raw_row)]`` for every trouble row."""
    out = []
    for number, line in enumerate(_text().splitlines(), 1):
        match = ROW_RE.match(line)
        if match:
            out.append((number, match.group(1), line))
    return out


def test_the_table_has_rows_at_all():
    """Non-vacuity floor: every other assertion here is trivially true on an
    empty list, so a table that stopped parsing must fail loudly."""
    assert len(_rows()) >= 80


def test_every_row_has_the_headers_cell_count():
    """The T29/#37 defect class, finally checked on this file too.

    A row with an extra cell does not fail to render — it renders WRONG, with
    one column's content in the next column's place and the last column pushed
    out of the table. That is worse than a parse error, because it looks fine.
    """
    defects = package_module.markdown_table_defects(_text())
    assert defects == [], defects


def test_ids_are_unique():
    """Two agents each taking "the next free number" is how a collision
    happens; this makes it a test failure rather than a silent duplicate."""
    ids = [identifier for _, identifier, _ in _rows()]
    duplicates = sorted(i for i, count in Counter(ids).items() if count > 1)
    assert duplicates == []


def test_no_row_has_an_empty_cell():
    """A blank signature, cause, fix or origin is an unfinished row.

    Leading and trailing cells are the artefacts of splitting on the outer
    pipes, so only the five real columns are checked.
    """
    empty = []
    for number, identifier, row in _rows():
        cells = [cell.strip() for cell in package_module.markdown_table_cells(row)]
        if any(not cell for cell in cells[:5]):
            empty.append((number, identifier))
    assert empty == []


def test_a_literal_pipe_inside_a_cell_is_escaped():
    """Guard the exact mechanism that broke T41's row.

    GFM splits a table row on every unescaped ``|``, including inside a code
    span, so a cell that mentions alternatives has to write ``\\|``. Checking
    the escape directly — rather than only the resulting cell count — names the
    cause for whoever trips it next.
    """
    offenders = []
    for number, identifier, row in _rows():
        body = row.strip().strip("|")
        # Un-escape first, then count: an escaped pipe is legal, a bare one is
        # a column boundary and must be one of the four separators.
        bare = re.sub(r"\\\|", "", body).count("|")
        if bare != 4:
            offenders.append((number, identifier, bare))
    assert offenders == []


def test_the_conventions_are_written_down_next_to_the_table():
    """A convention no one can read gets violated by the next contributor.

    This is not decoration: the T96 row was first appended to the historical
    tail because the ordering rule existed only in the arrangement of the file.
    """
    header = _text().split("| id |", 1)[0]
    assert "Ids are unique" in header
    assert "Row order is not significant" in header
    assert "\\|" in header
