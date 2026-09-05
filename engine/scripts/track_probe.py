#!/usr/bin/env python3
"""Does Hancom solve one column set per table, or lay each row out on its own?

#268 fixed which margin insets a cell and named what was left: the track
solve.  ``own_render.solve_tracks`` forces ONE global column set on a table
whose rows do not agree on one -- ``jumin`` table 1 declares 50897 across its
first thirty-one rows and 48067 across its last eight, for the same five
columns -- and the even-split and proportional-rescale fallbacks smear that
contradiction over every column of every row.

The public basis says a global solve is our invention.  OWPML (KS X 6101)
gives ``hp:tbl`` a ``sz``, a ``rowCnt``/``colCnt`` and a list of ``hp:tr``;
every ``hp:tc`` under those carries its OWN ``cellSz@width`` and its own
``cellAddr``/``cellSpan``.  There is no table-level column definition to read.
So this probe puts three readings of that data side by side and asks the
cache which one Hancom used.

THE THREE MODELS
----------------
``global`` (what the renderer does today)
    ``solve_tracks`` recovers one width per column from every cell's span
    constraint, rescales the set to ``hp:tbl/hp:sz@width``, and a cell's box
    is ``xs[col + colSpan] - xs[col]``.

``literal`` (no solve at all)
    A cell's box is its own ``cellSz@width``, full stop.  Its x is the
    running sum of the widths already placed in ITS row, where a cell held
    over from an earlier row by ``rowSpan`` contributes its width to that
    sum at the grid column it occupies.  Each row tiles itself; rows need
    not agree, and on this corpus they do not.

``addr`` (declared width, global x)
    A cell's box is its own ``cellSz@width`` and its x is ``xs[col]`` off the
    global solve -- the reading that keeps one column grid for x while
    letting each cell state its own width.  ``xs`` is used rather than the
    first row's widths because on the corpus's contradictory tables the first
    row is a single ``colSpan``-wide cell and declares no per-column width at
    all; the probe reports how many tables have a first row that could serve.

``stretch`` (``literal``, with the row closed to the table's box)
    ``literal`` again, except that the LAST cell a row lists absorbs whatever
    is left between the row's own total and ``hp:tbl/hp:sz@width``, so every
    row ends exactly at the table's right edge.  This is not a fourth guess:
    it is what ``jumin`` table 1 rows 31-38 say out loud.  Those rows total
    48067 against a table of 50897, and the cache breaks the text of rows
    31/32/35/37 -- one 5-column cell each -- in a box of 50897, while on rows
    33/34/38 it breaks the first cell (29386) at exactly its declared width
    and the second (18681) at 21511 = 50897 - 29386.  A proportional rescale
    would have moved the first cell too, and it did not move.

WHICH CELL PAYS: THE ALLOCATION MODELS
--------------------------------------
``stretch`` left one question open -- it hands a row's whole shortfall to the
last cell the row lists, and 37 ``saeopja`` cells say that is not always
where it goes.  Six more models tile the row the same way and differ only in
who pays: ``prop4`` (proportional to the declared widths, each share floored
onto the 4-HWPUNIT grid, remainder to the last cell), ``prop_round`` (the
same, rounded, remainder to the last), ``prop_widest`` (remainder to the
widest cell), ``quanta`` (4 HWPUNIT at a time left to right until spent) and
``colspan`` (the largest ``colSpan`` in the row takes it all).

Three more do not hand the shortfall to anybody, because they never compute
one.  They build ONE column grid for the table and let a cell's box be the
distance between the two boundaries it sits between:

``gridfirst``
    ``x[0]`` is 0, ``x[colCnt]`` is ``hp:tbl/hp:sz@width``, and every other
    boundary is written by the FIRST cell, in document order, whose declared
    width reaches it.  A later cell that reaches an already-written boundary
    is stretched or shrunk to it instead of writing its own.
``firstrow``
    the same, but only row 0 may write boundaries -- the task's "the first
    row's tracks" reading.
``gridlast``
    the same, but a later row overwrites an earlier one.  The control that
    says whether "first" is doing any work.
``gridmax``
    the same grid with no ordering rule at all: a boundary sits at the
    LARGEST x any cell reaching it produces from its own declared width.
    A cell's ``cellSz@width`` is read as a lower bound on the distance
    between its two boundaries rather than as a statement of it, so a row
    whose widths do not add up to the table under-claims and is fitted to
    the cells that claim more.  Solved to a fixpoint, because a claim
    depends on the boundary it starts from.

``gridfirst`` is what the corpus picks, and the datum that picks it is
``saeopja``'s 47996-wide table.  Rows 8/9 there total 47868 and the 128
short does NOT go to the last cell: the cache gives +26 to the ``colSpan=3``
cell at column 10 and +98 to the ``colSpan=1`` cell at column 17.  Under
``gridfirst`` that is not two allocations, it is two boundaries.  Row 7's
``colSpan=7`` cell at column 6 runs 14383 + 19010 and writes ``x[13]`` =
33393; row 8's ``colSpan=3`` cell at column 10 starts at ``x[10]`` = 26433
and reaches ``x[13]``, so its box is 6960 against a declared 6932 -- +28,
which the cache's 4-HWPUNIT quantiser saves as +26.  Its last cell reaches
``x[18]`` = 47996 from ``x[17]`` = 44144 for a box of 3852 against a declared
3752 -- +100, saved as +98.  Neither number is proportional to anything and
neither is a choice; both fall out of boundaries two earlier rows had
already written.

TWO ORACLES, AND WHAT EACH CAN SEE
----------------------------------
**Width** is observable.  ``hp:lineseg@horzsize`` is the box Hancom broke the
cell's text in, and it differs from the model's box only by the cell inset
and the paragraph's own margins.  Those last two are identical across the
three models, so a model's per-line residual is the renderer's own residual
shifted by ``model_box - rendered_box`` -- exact, with no second derivation
of the inset to get wrong.

**x is not**, and the probe measures that rather than assuming it.  The task
proposed ``hp:lineseg@horzpos`` as a second oracle on the reading that it is
a text start.  It is -- but relative to the cell's own content box, not to
the page: ``--horzpos`` counts how many in-cell cached linesegs equal the
paragraph-relative prediction ``max(0, margin_left + intent)`` against how
many equal any absolute placement.  A cache that never records an absolute
x cannot separate ``literal`` from ``addr``.

So x gets a third oracle, off the reference PDF: ``--pdf`` reads every
vertical stroke Hancom's own export draws with ``page.get_drawings()``, and
scores each model's cell boundaries against them.  A table rule is exactly
the boundary a model predicts, in absolute page coordinates, and it is the
only absolute statement about x this corpus contains.

Usage::

    python engine/scripts/track_probe.py FORM.hwpx
    python engine/scripts/track_probe.py --corpus
    python engine/scripts/track_probe.py --corpus --pdf --horzpos
    python engine/scripts/track_probe.py --corpus --heights
    python engine/scripts/track_probe.py --corpus --rows \
        --models stretch,gridfirst
    python engine/scripts/track_probe.py --corpus --residuals \
        --models gridfirst,gridmax
    python engine/scripts/track_probe.py FORM.hwpx --rows

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import cell_column_probe  # noqa: E402
import layout_divergence  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

#: Every column model the probe scores, in the order they are reported.
#: The first four are #270's; the rest answer the question #270 left open --
#: when a row's cells do not add up to the table, WHICH cell takes the
#: difference.  ``gridfirst`` is the one the corpus picks; see the module
#: docstring's ALLOCATION MODELS section.
MODELS = (
    "global", "literal", "addr", "stretch",
    "prop4", "prop_round", "prop_widest", "quanta", "colspan",
    "firstrow", "gridfirst", "gridlast", "gridmax",
    "gridmin", "gridexact", "gridwide", "gridback", "gridsnap",
)

#: Models built by walking a shared column grid rather than by handing one
#: row's shortfall to one of that row's own cells.
GRID_MODELS = ("firstrow", "gridfirst", "gridlast", "gridmax",
               "gridmin", "gridexact", "gridwide", "gridback", "gridsnap")

#: Models that tile a row from its own declared widths and then hand the
#: shortfall out among that row's own cells, ``{name: allocation mode}``.
ROW_MODELS = {
    "stretch": "last",
    "prop4": "prop4",
    "prop_round": "prop_round",
    "prop_widest": "prop_widest",
    "quanta": "quanta",
    "colspan": "colspan",
}

#: A residual at or under this many HWPUNIT is zero.  The quantities are
#: integers; the tolerance exists only so a float column compares cleanly.
TOL = 0.5

#: 8 HWPUNIT is 0.03 mm and no line break turns on it -- #268's near band,
#: kept identical here so the two probes' numbers can be read together.
NEAR_HWP = cell_column_probe.NEAR_HWP

#: A model x and a PDF rule within this many HWPUNIT are the same line.  One
#: device pixel at 144 dpi is 50 HWPUNIT; Hancom strokes a rule centred on
#: the boundary, so half a stroke width (a hairline is 40-ish) plus rounding
#: is what this has to absorb.  Reported at three tolerances, not one.
RULE_TOL = (0.5, 20.0, 50.0)

RULE_QUESTION = (
    "when a table's rows declare contradictory totals, does Hancom lay each "
    "row out from its own cells' cellSz@width, or solve one column set for "
    "the whole table?")


# --------------------------------------------------------------------------
# The instrumented renderer
# --------------------------------------------------------------------------

class TrackRenderer(cell_column_probe.CellColumnRenderer):
    """Records the solved tracks, and where every cell box actually landed.

    ``CellColumnRenderer`` already captures the text column each cell's
    paragraphs were given.  This adds the two things a column MODEL has to
    be scored against: the solved ``xs`` for the table (so the ``addr``
    model can be evaluated without re-solving and possibly re-solving
    differently), and the absolute page origin of each drawn cell box (so a
    PDF rule can be looked for where the renderer actually drew one).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: ``{id(hp:tbl): xs}`` -- the solved column boundaries, in HWPUNIT.
        self.table_xs = {}
        #: ``{id(hp:tc): {"x0", "x1", "page"}}`` -- absolute, first draw wins.
        self.cell_boxes = {}
        self._cur_tbl = None

    def _table_tracks(self, draw, tbl, natural_rows=False):
        xs, ys, cells = super()._table_tracks(draw, tbl,
                                              natural_rows=natural_rows)
        self.table_xs.setdefault(id(tbl), list(xs))
        return xs, ys, cells

    def _render_table(self, draw, tbl, origin_hwp):
        outer, self._cur_tbl = self._cur_tbl, tbl
        try:
            return super()._render_table(draw, tbl, origin_hwp)
        finally:
            self._cur_tbl = outer

    def _render_cell_content(self, draw, cell, x0, y0, x1, y1):
        self.cell_boxes.setdefault(id(cell["tc"]), {
            "x0": x0, "x1": x1, "page": self._page,
            "tbl": self._cur_tbl,
        })
        return super()._render_cell_content(draw, cell, x0, y0, x1, y1)


# --------------------------------------------------------------------------
# The models, read straight off the XML
# --------------------------------------------------------------------------

def read_table(tbl):
    """``hp:tbl`` reduced to the per-cell facts the three models run on."""
    rows = []
    for tr in own_render._kids(tbl, "tr"):
        row = []
        for tc in own_render._kids(tr, "tc"):
            addr = own_render._kid(tc, "cellAddr")
            span = own_render._kid(tc, "cellSpan")
            size = own_render._kid(tc, "cellSz")
            if addr is None or size is None:
                continue
            row.append({
                "tc": tc,
                "row": own_render._iattr(addr, "rowAddr"),
                "col": own_render._iattr(addr, "colAddr"),
                "cspan": max(1, own_render._iattr(span, "colSpan", 1)),
                "rspan": max(1, own_render._iattr(span, "rowSpan", 1)),
                "width": own_render._iattr(size, "width"),
                "height": own_render._iattr(size, "height"),
            })
        rows.append(row)
    sz = own_render._kid(tbl, "sz")
    return {
        "rows": rows,
        "row_cnt": own_render._iattr(tbl, "rowCnt", len(rows)),
        "col_cnt": own_render._iattr(tbl, "colCnt", 0),
        "declared_width": own_render._iattr(sz, "width") if sz is not None else 0,
        "declared_height": (own_render._iattr(sz, "height")
                            if sz is not None else 0),
        "cell_spacing": own_render._iattr(tbl, "cellSpacing"),
        "repeat_header": tbl.get("repeatHeader"),
        "page_break": tbl.get("pageBreak"),
        "no_adjust": tbl.get("noAdjust"),
    }


def literal_layout(table):
    """``{id(tc): x}`` -- each row tiled from its own cells' declared widths.

    A ``rowSpan`` cell is not repeated in the rows it reaches into, so the
    walk carries it: ``held[(row, col)]`` is ``(width, colSpan)`` for a cell
    started above, and the cursor steps over it -- advancing x by that cell's
    declared width -- before placing the next cell the row does list.  Without
    that carry every row under a merge would start at x=0 and the model would
    be measuring the carry's absence rather than the literal reading.

    Also returned: ``col_walked`` per cell, the grid column the walk lands on,
    against which the file's own ``cellAddr@colAddr`` can be checked.
    """
    xs, walked, held = {}, {}, {}
    row_totals, last_of_row = [], []
    for r, row in enumerate(table["rows"]):
        x, col, last = 0, 0, None
        for cell in row:
            while (r, col) in held:
                w, cspan = held[(r, col)]
                x += w
                col += cspan
            xs[id(cell["tc"])] = x
            walked[id(cell["tc"])] = col
            for rr in range(r + 1, r + cell["rspan"]):
                held[(rr, col)] = (cell["width"], cell["cspan"])
            x += cell["width"]
            col += cell["cspan"]
            last = cell
        while (r, col) in held:
            w, cspan = held[(r, col)]
            x += w
            col += cspan
        row_totals.append(x)
        last_of_row.append(last)
    return xs, walked, row_totals, last_of_row


def first_row_prefix(table):
    """``[x0, x1, ...]`` off the first row, when that row states every column.

    The task's ``addr`` model wanted the FIRST row's widths as the grid.  On
    this corpus that is usually impossible -- the row is one merged cell --
    and the probe says so with a count rather than silently substituting
    something else.  ``None`` when the first row does not resolve every
    column with unit spans.
    """
    if not table["rows"]:
        return None
    row = table["rows"][0]
    if sum(c["cspan"] for c in row) != table["col_cnt"]:
        return None
    if any(c["cspan"] != 1 for c in row):
        return None
    out = [0]
    for cell in row:
        out.append(out[-1] + cell["width"])
    return out


def allocate(widths, spans, shortfall, mode):
    """How ``shortfall`` HWPUNIT is shared among one row's own listed cells.

    ``widths`` are the cells' declared ``cellSz@width`` in row order and
    ``spans`` their ``colSpan``; the return is a list of per-cell additions
    that sums to ``shortfall`` exactly, so every model closes the row at the
    table's declared width and they differ only in WHO pays.

    ``last``          the last cell the row lists takes all of it (#270's
                      ``stretch``).
    ``prop4``         proportional to the cells' declared widths, each share
                      floored onto the 4-HWPUNIT grid the cache quantises on,
                      the remainder to the last cell.
    ``prop_round``    proportional, each share rounded to the nearest
                      HWPUNIT, remainder to the last cell.
    ``prop_widest``   the same, remainder to the widest cell instead.
    ``quanta``        4 HWPUNIT at a time, left to right, wrapping until the
                      shortfall is spent; the sub-quantum tail goes to the
                      last cell touched.
    ``colspan``       the cell holding the largest ``colSpan`` takes all of
                      it, the leftmost of those on a tie.
    """
    n = len(widths)
    if n == 0:
        return []
    add = [0] * n
    if shortfall == 0:
        return add
    if mode == "last":
        add[-1] = shortfall
        return add
    if mode == "colspan":
        add[max(range(n), key=lambda i: (spans[i], -i))] = shortfall
        return add
    if mode == "quanta":
        step = 4 if shortfall > 0 else -4
        left, i = shortfall, 0
        while abs(left) >= 4:
            add[i % n] += step
            left -= step
            i += 1
        add[(i - 1) % n if i else 0] += left
        return add
    total = sum(widths)
    if total <= 0:
        add[-1] = shortfall
        return add
    raw = [shortfall * w / float(total) for w in widths]
    if mode == "prop4":
        add = [int(math.floor(v / 4.0)) * 4 for v in raw]
    else:
        add = [int(round(v)) for v in raw]
    slack = shortfall - sum(add)
    if mode == "prop_widest":
        add[max(range(n), key=lambda i: (widths[i], -i))] += slack
    else:
        add[-1] += slack
    return add


def row_alloc_layout(table, mode):
    """``{id(tc): (x, width)}`` -- each row tiled from its own declared
    widths, with the row's shortfall against ``hp:tbl/hp:sz@width`` shared
    out by ``allocate``.

    The ``rowSpan`` carry is the same one ``literal_layout`` measured against
    the file's own ``cellAddr``: a held cell contributes its DECLARED width
    to the rows it reaches into, not the width its own row gave it, because
    the row it was listed in is the only row that adjusts it.
    """
    out, held = {}, {}
    declared = table["declared_width"]
    for r, row in enumerate(table["rows"]):
        # First pass: where each listed cell starts, and the row's total.
        starts, x, col = [], 0, 0
        for cell in row:
            while (r, col) in held:
                w, cspan = held[(r, col)]
                x += w
                col += cspan
            starts.append(x)
            for rr in range(r + 1, r + cell["rspan"]):
                held[(rr, col)] = (cell["width"], cell["cspan"])
            x += cell["width"]
            col += cell["cspan"]
        while (r, col) in held:
            w, cspan = held[(r, col)]
            x += w
            col += cspan
        if not row:
            continue
        shortfall = (declared - x) if declared else 0
        add = allocate([c["width"] for c in row],
                       [c["cspan"] for c in row], shortfall, mode)
        # Second pass: re-tile with the adjusted widths, keeping the leading
        # gap each cell had (a held cell's width is unchanged, so the gap is
        # the same quantity in both passes).
        shift = 0
        for i, cell in enumerate(row):
            width = cell["width"] + add[i]
            out[id(cell["tc"])] = (starts[i] + shift, width)
            shift += add[i]
    return out


def grid_boundaries_first(table, rows_used=None, last_wins=False):
    """``{column: x}`` -- the boundaries :func:`grid_layout` walks out.

    Reporting only; ``grid_layout`` builds the same dictionary and returns
    boxes instead of it.
    """
    xs = {}
    grid_layout(table, rows_used=rows_used, last_wins=last_wins, out_xs=xs)
    return xs


def grid_layout(table, rows_used=None, last_wins=False, out_xs=None):
    """``{id(tc): (x, width)}`` -- one column grid for the table, built by
    walking the rows in document order.

    ``x[0]`` is 0 and ``x[colCnt]`` is ``hp:tbl/hp:sz@width``: the table
    closes at its own declared box, which is the one thing every row on this
    corpus agrees about.  Every other boundary is written by the FIRST cell
    whose declared width reaches it, and a later cell that reaches an
    already-written boundary is stretched or shrunk to it instead of writing
    its own.  A cell's box is the distance between the two boundaries it sits
    between, so a row whose cells do not add up does not hand its shortfall
    to any one cell -- the shortfall lands wherever the grid already
    disagrees with the row, which can be several cells and in unequal
    amounts.

    ``rows_used`` restricts which rows may WRITE boundaries (``{0}`` is the
    task's "first row's tracks" reading); every row still reads them.
    ``last_wins`` is the control: a later row overwrites an earlier row's
    boundary rather than yielding to it.
    """
    ncol = table["col_cnt"]
    declared = table["declared_width"]
    xs = {0: 0}
    if declared and ncol:
        xs[ncol] = declared
    fixed = set(xs)
    out, held = {}, {}
    for r, row in enumerate(table["rows"]):
        writes = rows_used is None or r in rows_used
        pos, col = 0, 0
        for cell in row:
            while (r, col) in held:
                w, cspan = held[(r, col)]
                col += cspan
                pos = xs.get(col, pos + w)
            c = cell["col"] if cell["col"] is not None else col
            left = xs.get(c, pos)
            right_col = c + cell["cspan"]
            if right_col in xs and not (last_wins and writes
                                        and right_col not in fixed):
                right = xs[right_col]
            else:
                right = left + cell["width"]
                if writes:
                    xs[right_col] = right
            out[id(cell["tc"])] = (left, right - left)
            for rr in range(r + 1, r + cell["rspan"]):
                held[(rr, c)] = (cell["width"], cell["cspan"])
            pos, col = right, right_col
    if out_xs is not None:
        out_xs.update(xs)
    return out


def grid_boundaries_max(table, clamp=True):
    """``{column: x}`` -- the envelope of every cell's claim on the grid.

    ``gridfirst`` resolves two cells reaching the same boundary by document
    order.  This resolves it by size: a boundary sits at the LARGEST x any
    cell reaching it produces, which reads ``cellSz@width`` as a LOWER BOUND
    on the distance between a cell's two boundaries rather than as a
    statement of it.  A row whose widths sum short of ``hp:sz@width``
    under-claims every boundary it writes, and the rows that claim more are
    what the grid takes.

    Solved to a fixpoint because a claim depends on the boundary it starts
    from.  The iteration only ever raises a boundary and ``clamp`` caps every
    claim at ``hp:sz@width``, so it is monotone and bounded and terminates;
    the loop bound is belt and braces.  ``clamp=False`` is the control for a
    row that overflows its table -- on this corpus the two agree, because no
    row does.
    """
    ncol = table["col_cnt"]
    declared = table["declared_width"]
    fixed = {0: 0}
    if declared and ncol:
        fixed[ncol] = declared
    xs = dict(fixed)
    for _ in range(len(table["rows"]) + 4):
        changed = False
        for row in table["rows"]:
            pos = 0
            for cell in row:
                col = cell["col"]
                if col is None:
                    continue
                left = xs.get(col, pos)
                right_col = col + cell["cspan"]
                claim = left + cell["width"]
                if clamp and ncol in xs:
                    claim = min(claim, xs[ncol])
                if right_col not in fixed and claim > xs.get(right_col, -1):
                    xs[right_col] = claim
                    changed = True
                pos = xs.get(right_col, claim)
        if not changed:
            break
    return xs


def place_on_grid(table, xs):
    """``{id(tc): (x, width)}`` -- read every cell back off a finished grid.

    A boundary no cell ever claimed is not in ``xs``; the walk falls back to
    the running cursor there, which is the same thing ``grid_layout`` does
    and keeps a table whose grid has a gap from collapsing.
    """
    out, held = {}, {}
    for r, row in enumerate(table["rows"]):
        pos, col = 0, 0
        for cell in row:
            while (r, col) in held:
                w, cspan = held[(r, col)]
                col += cspan
                pos = xs.get(col, pos + w)
            c = cell["col"] if cell["col"] is not None else col
            left = xs.get(c, pos)
            right_col = c + cell["cspan"]
            right = xs.get(right_col, left + cell["width"])
            out[id(cell["tc"])] = (left, right - left)
            for rr in range(r + 1, r + cell["rspan"]):
                held[(rr, c)] = (cell["width"], cell["cspan"])
            pos, col = right, right_col
    return out


def grid_max_layout(table, clamp=True):
    """``gridmax``: :func:`place_on_grid` on :func:`grid_boundaries_max`."""
    return place_on_grid(table, grid_boundaries_max(table, clamp=clamp))


def _row_claims(table, xs):
    """``{column: [(claim, colSpan, row, exact), ...]}`` at a settled grid.

    Every cell reaching a boundary, with the x it produces from the grid's
    own left boundary and the three things a tie rule could read off it: how
    many columns the cell spans, which row it is on, and whether that row's
    declared widths sum to the table's own ``hp:sz@width``.  Computed at a
    FIXED ``xs`` so the candidate rules below all read the same left edges
    and differ only in which claim they take.
    """
    total = table["declared_width"]
    out = defaultdict(list)
    for r, row in enumerate(table["rows"]):
        row_total = sum(c["width"] or 0 for c in row)
        exact = bool(total) and row_total == total
        for cell in row:
            col = cell["col"]
            if col is None or col not in xs:
                continue
            edge = col + cell["cspan"]
            out[edge].append((xs[col] + max(0, cell["width"] or 0),
                              cell["cspan"], r, exact))
    return out


def grid_boundaries_pick(table, pick):
    """``{column: x}`` -- :func:`grid_boundaries_max`'s grid, re-resolved.

    The envelope reading settles every boundary at the largest claim.  Where
    two rows claim one boundary a few HWPUNIT apart that is a CHOICE, and
    this is the instrument for the alternatives: the grid is solved to the
    max fixpoint first, and then each interior boundary is rewritten by
    ``pick(claims)`` over the cells reaching it, in ascending column order so
    a rewritten boundary is the left edge the next one is claimed from.  The
    two ends stay pinned and the result is forced non-decreasing, because a
    boundary left of the one before it is not a grid.
    """
    ncol = table["col_cnt"]
    total = table["declared_width"]
    xs = dict(grid_boundaries_max(table))
    for _ in range(2):
        claims = _row_claims(table, xs)
        prev = 0
        for col in range(1, ncol):
            if col not in xs:
                continue
            here = claims.get(col)
            if here:
                xs[col] = pick(here)
            xs[col] = max(prev, xs[col])
            if total:
                xs[col] = min(xs[col], total)
            prev = xs[col]
    return xs


def grid_boundaries_back(table):
    """``{column: x}`` -- every boundary as far RIGHT as the cells allow.

    ``gridmax`` propagates ``x[b] >= x[a] + width`` forwards from ``x[0]``,
    which makes each boundary a LOWER bound.  The same inequality read
    backwards from ``x[colCnt]`` makes it an UPPER bound, and this takes
    that: a row short of the table's box is right-anchored, its shortfall
    landing in its FIRST cell rather than its last.  The control for the two
    ``saeopja`` rows the envelope reading misses, and the reason it is a
    control and not a proposal is that the same table's other rows go the
    other way.
    """
    ncol = table["col_cnt"]
    total = table["declared_width"]
    lo = grid_boundaries_max(table)
    if not total or not ncol:
        return lo
    hi = {ncol: total}
    for _ in range(ncol + 2):
        changed = False
        for row in table["rows"]:
            for cell in row:
                col = cell["col"]
                if col is None:
                    continue
                edge = min(col + cell["cspan"], ncol)
                if edge not in hi or col == 0:
                    continue
                bound = hi[edge] - max(0, cell["width"] or 0)
                if bound < hi.get(col, total + 1):
                    hi[col] = bound
                    changed = True
        if not changed:
            break
    xs, prev = dict(lo), 0
    for col in range(1, ncol):
        if col not in xs:
            continue
        xs[col] = max(prev, min(hi.get(col, xs[col]), total))
        xs[col] = max(xs[col], lo[col])
        prev = xs[col]
    return xs


def grid_boundaries_snap(table, step=4):
    """``{column: x}`` -- ``gridmax`` with every interior boundary on a grid.

    ``hp:lineseg@horzsize`` is saved quantised onto a 4 HWPUNIT grid, and one
    reading of the misses is that the BOUNDARY is quantised too rather than
    only the record of it.  Rounded to nearest, which is the only snap that
    can move a cell in either direction.
    """
    ncol = table["col_cnt"]
    total = table["declared_width"]
    xs, prev = dict(grid_boundaries_max(table)), 0
    for col in range(1, ncol):
        if col not in xs:
            continue
        value = int(step * round(xs[col] / float(step)))
        xs[col] = max(prev, min(value, total) if total else value)
        prev = xs[col]
    return xs


#: The tie rules ``--models`` can score, ``{name: boundary function}``.  Each
#: takes the table and returns ``{column: x}``; :func:`place_on_grid` reads
#: every cell back off whichever grid comes out.
GRID_RULES = {
    "gridmin": lambda t: grid_boundaries_pick(t, lambda cs: min(c[0]
                                                                for c in cs)),
    "gridexact": lambda t: grid_boundaries_pick(t, _pick_exact_row),
    "gridwide": lambda t: grid_boundaries_pick(t, _pick_widest_span),
    "gridback": grid_boundaries_back,
    "gridsnap": grid_boundaries_snap,
}


def _pick_exact_row(claims):
    """The claim from a row whose widths sum to ``hp:sz@width``, else the max.

    #277 scored an ordinal version of this and it reached 1583.  Here it is a
    tie rule rather than a write order: a boundary two rows reach is written
    by the row that adds up, and a boundary no such row reaches keeps the
    envelope's answer.
    """
    exact = [c[0] for c in claims if c[3]]
    return max(exact) if exact else max(c[0] for c in claims)


def _pick_widest_span(claims):
    """The claim from the cell spanning the most columns, ties to the max."""
    widest = max(c[1] for c in claims)
    return max(c[0] for c in claims if c[1] == widest)


def grid_sources(table, xs):
    """``{column: "rRcC+S"}`` -- which cell's claim a boundary sits on.

    Reporting only.  A boundary is attributed to the first cell, in document
    order, whose left boundary plus its declared width lands on it; the two
    ends are labelled by where they come from instead.  A boundary no cell
    accounts for is labelled ``?``, which is what a grid the file does not
    determine looks like.
    """
    ncol = table["col_cnt"]
    src = {0: "x0", ncol: "sz@width"}
    for r, row in enumerate(table["rows"]):
        for cell in row:
            col = cell["col"]
            if col is None:
                continue
            right_col = col + cell["cspan"]
            if right_col in src or right_col not in xs or col not in xs:
                continue
            if xs[col] + cell["width"] == xs[right_col]:
                src[right_col] = "r%dc%d+%d" % (r, col, cell["cspan"])
    return {col: src.get(col, "?") for col in xs}


def row_height_shape(tables):
    """The shape of the row-height question, before anyone tries to solve it.

    ``hp:tr`` carries no height in OWPML; every ``hp:tc`` carries its own
    ``cellSz@height``, and a row's height has to be recovered from them.  The
    two readings that could be right are "a row is as tall as the tallest
    cell listed in it" and "a ``rowSpan`` cell constrains the SUM of the rows
    it covers, so the heights need solving together".  This does not score
    them against an oracle -- there is no cached row height to score against
    -- it counts how often the data even lets them differ:

    ``unit_rows_agreeing``   rows where every ``rowSpan=1`` cell declares the
                             same height, so "tallest" and "any of them" are
                             the same answer.
    ``span_exact``           ``rowSpan`` cells whose declared height equals
                             the sum of the unit heights of the rows it
                             covers -- the merge adds no constraint.
    ``span_residual``        the histogram of the difference when it does
                             not, which is what a solve would have to move.
    ``table_exact``          tables whose row heights sum to
                             ``hp:tbl/hp:sz@height``.
    """
    out = {"tables": 0, "rows": 0, "unit_rows_agreeing": 0,
           "rows_without_unit_cell": 0, "span_cells": 0, "span_exact": 0,
           "table_exact": 0, "span_residual": Counter(),
           "table_residual": Counter(), "unit_row_spread": Counter()}
    for table in tables.values():
        out["tables"] += 1
        unit = {}
        for r, row in enumerate(table["rows"]):
            out["rows"] += 1
            heights = sorted({c["height"] for c in row if c["rspan"] == 1})
            if not heights:
                out["rows_without_unit_cell"] += 1
                continue
            unit[r] = heights[-1]
            out["unit_row_spread"][heights[-1] - heights[0]] += 1
            if len(heights) == 1:
                out["unit_rows_agreeing"] += 1
        for r, row in enumerate(table["rows"]):
            for cell in row:
                if cell["rspan"] == 1:
                    continue
                out["span_cells"] += 1
                covered = [unit.get(rr) for rr in range(r, r + cell["rspan"])]
                if any(v is None for v in covered):
                    out["span_residual"]["unknown"] += 1
                    continue
                gap = cell["height"] - sum(covered)
                out["span_exact"] += gap == 0
                out["span_residual"][gap] += 1
        total = sum(unit.get(r, 0) for r in range(len(table["rows"])))
        gap = table["declared_height"] - total
        out["table_exact"] += gap == 0
        out["table_residual"][gap] += 1
    for key in ("span_residual", "table_residual", "unit_row_spread"):
        out[key] = dict(sorted(out[key].items(),
                               key=lambda kv: -kv[1])[:8])
    return out


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _on_grid(residual):
    """Has a model reproduced the column?  ``[0, 4)`` is the cache's own
    quantiser (#268: 3164 of 3177 cached ``horzsize`` are multiples of 4);
    ``None`` is a cell whose lines disagree under this model, and is not."""
    return residual is not None and 0 <= residual < 4


def model_residual(renderer, record, model_box):
    """One cell's residual under a model that gives it ``model_box``.

    #270 and #272 scored a model by SHIFTING the rendered residual by
    ``model_box - rendered_box``, on the reading that the cell inset and the
    paragraph's own margins enter our line box and the cache's identically
    and cancel.  They do -- but #275 put a 1440 HWPUNIT floor under the text
    column, and a floor is not linear: on a cell whose column is already
    saturated, a model that gives it a different BOX gives it the same
    COLUMN, and the shift reports a difference that the renderer would not
    make.  So the residual is recomputed rather than shifted: the model's box
    goes through ``cell_text_width`` and the cell's cached lines are measured
    against ``_line_box`` in that column, which is exactly what the renderer
    would do if the model shipped.

    On the corpus the two agree on 1598 of 1599 cells; the one they differ on
    is ``saeopja`` ``r3c6``, the cell #275 recorded as a regression that was
    the baseline moving rather than a model failing.  It is not a regression
    under this arithmetic, because it never was one.

    ``None`` when the cell's lines disagree, matching ``delta_line``.
    """
    column = own_render.cell_text_width(model_box, record["cell"]["margin"])
    deltas = []
    for para in record["cell"]["paras"]:
        for i, seg in enumerate(para.linesegs):
            horzsize = seg.get("horzsize")
            if horzsize is None:
                continue
            try:
                horzsize = int(horzsize)
            except ValueError:
                continue
            deltas.append(renderer._line_box(para, i, column)[1] - horzsize)
    if not deltas:
        return None
    lo, hi = min(deltas), max(deltas)
    return lo if abs(lo - hi) <= TOL else None


def probe_form(hwpx_path, dpi=own_render.DEFAULT_DPI, policy="cache",
               repo_root=None, pdf_path=None, keep_renderer=False):
    """Score the three column models on one form.

    ``keep_renderer`` hands the rendered ``TrackRenderer`` back under the
    report's ``renderer`` key, so a caller that wants the ELEMENTS behind a
    cell — ``cell_column_probe --residuals`` does — can reach them through
    ``renderer.cell_columns[cell["cell_id"]]`` instead of rendering the form
    a second time and matching the two runs up by address.  The key is not
    JSON-serialisable and the caller pops it.
    """
    renderer = TrackRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                             layout_policy=policy)
    renderer.render()
    owner = cell_column_probe._table_of_cells(renderer.sections)

    tables = {}
    for record in renderer.cell_columns.values():
        tbl = owner.get(id(record["cell"]["tc"]))
        if tbl is None or id(tbl) in tables:
            continue
        table = read_table(tbl)
        table["xs"] = renderer.table_xs.get(id(tbl), [])
        (table["literal_x"], table["walked"], table["row_totals"],
         table["last_of_row"]) = literal_layout(table)
        table["first_row_grid"] = first_row_prefix(table)
        # Every model that is not the global solve reduces to a
        # ``{id(tc): (x, width)}`` placement, computed once per table.
        placed = {name: row_alloc_layout(table, mode)
                  for name, mode in ROW_MODELS.items()}
        placed["firstrow"] = grid_layout(table, rows_used={0})
        placed["gridfirst"] = grid_layout(table)
        placed["gridlast"] = grid_layout(table, last_wins=True)
        placed["gridmax"] = grid_max_layout(table)
        for name, boundaries in GRID_RULES.items():
            placed[name] = place_on_grid(table, boundaries(table))
        table["placed"] = placed
        # Reporting only: which cell's claim each grid boundary sits on, so
        # ``--residuals`` can name the boundary that placed an off-grid cell
        # rather than leaving it to be worked out by hand.
        table["grid_xs"] = {
            "gridfirst": grid_boundaries_first(table),
            "gridmax": grid_boundaries_max(table),
        }
        table["grid_src"] = {name: grid_sources(table, xs)
                             for name, xs in table["grid_xs"].items()}
        table["index"] = len(tables)
        tables[id(tbl)] = table

    cells = []
    for record in renderer.cell_columns.values():
        tc = record["cell"]["tc"]
        tbl = owner.get(id(tc))
        base = cell_column_probe._cell_report(renderer, record, tbl, TOL)
        if base is None or tbl is None:
            continue
        table = tables[id(tbl)]
        box = renderer.cell_boxes.get(id(tc), {})
        col, cspan = base["col"], base["col_span"]
        xs = table["xs"]
        declared = base["cell_width"]

        rendered_box = record["box_hwp"]
        gx = xs[min(col, len(xs) - 1)] if xs else 0
        lx = table["literal_x"].get(id(tc), 0)
        model_box = {"global": rendered_box, "literal": declared,
                     "addr": declared}
        model_x = {"global": gx, "literal": lx, "addr": gx}
        for name, placed in table["placed"].items():
            x0, width = placed.get(id(tc), (lx, declared))
            model_box[name] = width
            model_x[name] = x0
        base.update({
            "model_box": model_box,
            "model_x": model_x,
            "model_delta": {name: model_residual(renderer, record,
                                                 model_box[name])
                            for name in MODELS},
            "rendered_box": rendered_box,
            "rendered_x0": box.get("x0"),
            "page": box.get("page"),
            "cell_id": id(tc),
            "table": id(tbl),
            "col_walked": table["walked"].get(id(tc)),
            "row_total": (table["row_totals"][base["row"]]
                          if base["row"] < len(table["row_totals"]) else None),
            "declared_total": table["declared_width"],
            "boundaries": {
                name: [src.get(col, "?"), src.get(col + cspan, "?")]
                for name, src in table["grid_src"].items()},
            "table_index": table["index"],
        })
        base.pop("cached_horzsize", None)
        cells.append(base)
    cells.sort(key=lambda c: (c["paragraphs"] or [10 ** 9], c["row"], c["col"]))

    report = {
        "cells_compared": len(cells),
        "cells_measurable": sum(1 for c in cells
                                if c["delta_line"] is not None),
        "cells_ragged": sum(1 for c in cells if c["ragged"]),
        "tables": len(tables),
        "tables_row_disagreement": sum(
            1 for t in tables.values()
            if len({x for x in t["row_totals"] if x}) > 1),
        "tables_first_row_grid": sum(1 for t in tables.values()
                                     if t["first_row_grid"] is not None),
        "coladdr_matches_walk": sum(1 for c in cells
                                    if c["col_walked"] == c["col"]),
        "width": {},
        "cells": cells,
    }
    for name in MODELS:
        residuals = [c["model_delta"][name] for c in cells
                     if c["model_delta"][name] is not None]
        report["width"][name] = {
            "exact": sum(1 for v in residuals if abs(v) <= TOL),
            # #268 measured that 3164 of 3177 cached in-cell horzsize values
            # are multiples of 4 HWPUNIT: the cache saves the line box
            # quantised DOWN onto that grid.  A model whose residual lands in
            # [0, 4) has therefore reproduced the column exactly, and the
            # remainder is the quantiser.  A NEGATIVE residual is not that:
            # it means the model's box is narrower than a box the cache
            # already rounded down, which no quantiser can produce.
            "grid": sum(1 for v in residuals if 0 <= v < 4),
            "near": sum(1 for v in residuals if abs(v) <= NEAR_HWP),
            "of": len(residuals),
            "histogram": dict(sorted(Counter(round(v, 3)
                                             for v in residuals).items(),
                                     key=lambda kv: -kv[1])[:10]),
        }

    # The corpus-wide grid percentage mixes two populations: cells the four
    # models place identically (where a residual measures something other
    # than the track solve -- an inset, an advance, a paragraph indent) and
    # cells they disagree about.  Only the second population is evidence
    # about tracks, and only there can a model regress.
    contested = [c for c in cells
                 if c["delta_line"] is not None
                 and len({c["model_box"][n] for n in MODELS}) > 1]
    report["contested"] = {
        "cells": len(contested),
        "grid": {n: sum(1 for c in contested if _on_grid(c["model_delta"][n]))
                 for n in MODELS},
    }
    # Two baselines, because the question this run asks is not "beat the
    # global solve" but "beat ``stretch``, which already does".
    report["regressions"] = {
        n: sum(1 for c in cells
               if c["delta_line"] is not None
               and _on_grid(c["model_delta"]["global"])
               and not _on_grid(c["model_delta"][n]))
        for n in MODELS}
    report["regressions_vs_stretch"] = {
        n: sum(1 for c in cells
               if c["delta_line"] is not None
               and _on_grid(c["model_delta"]["stretch"])
               and not _on_grid(c["model_delta"][n]))
        for n in MODELS}
    report["off_grid"] = {
        n: [{"table": c["table_index"], "row": c["row"], "col": c["col"],
             "span": c["col_span"], "declared": c["cell_width"],
             "box": c["model_box"][n], "residual": c["model_delta"][n],
             "horzsize": c["horzsize_max"], "paragraphs": c["paragraphs"],
             "boundaries": c["boundaries"].get(n),
             "row_total": c["row_total"], "table_width": c["declared_total"]}
            for c in cells
            if c["delta_line"] is not None
            and not _on_grid(c["model_delta"][n])]
        for n in MODELS}
    report["rows"] = row_height_shape(tables)
    report["horzpos"] = horzpos_oracle(renderer, cells)
    if pdf_path is not None:
        report["rules"] = pdf_rule_oracle(renderer, tables, cells, pdf_path)
    if keep_renderer:
        report["renderer"] = renderer
    return report


def horzpos_oracle(renderer, cells):
    """Is a cell's x observable in ``hp:lineseg@horzpos``?

    Two readings are counted over every cached in-cell lineseg: the
    paragraph-relative one (``max(0, margin_left + intent)``, which is what
    ``_line_box`` computes and what a cell-content-box-relative horzpos
    would be) and the absolute one (the cell's drawn x plus its left inset).
    Whichever the cache agrees with is what horzpos means.
    """
    relative = absolute = total = 0
    biggest = 0
    for record in renderer.cell_columns.values():
        cell = record["cell"]
        box = renderer.cell_boxes.get(id(cell["tc"]), {})
        abs_x = (box.get("x0") or 0) + cell["margin"]["left"]
        for para in cell["paras"]:
            for i, seg in enumerate(para.linesegs):
                raw = seg.get("horzpos")
                if raw is None:
                    continue
                try:
                    cached = int(raw)
                except ValueError:
                    continue
                total += 1
                biggest = max(biggest, cached)
                if abs(renderer._line_box(para, i, 0)[0] - cached) <= TOL:
                    relative += 1
                if abs(abs_x - cached) <= NEAR_HWP:
                    absolute += 1
    return {"linesegs": total, "paragraph_relative": relative,
            "absolute": absolute, "max_horzpos": biggest}


def pdf_rule_oracle(renderer, tables, cells, pdf_path):
    """Score each model's cell boundaries against the PDF's vertical rules.

    The reference PDF is Hancom's own export of the same file, and its table
    rules are drawn where Hancom put the columns.  Both sides are in absolute
    page coordinates -- ours in HWPUNIT from the page's top-left corner,
    which is where ``own_render`` puts its canvas origin, and the PDF's in
    points, 1 pt = 100 HWPUNIT -- so no registration is needed and none is
    applied.  A boundary counts as reproduced when some vertical stroke on
    the same page lies within the tolerance.
    """
    import lineseg_vs_pdf
    fitz = lineseg_vs_pdf._require_fitz()

    per_page = defaultdict(set)
    with fitz.open(str(pdf_path)) as document:
        pages = document.page_count
        for index, page in enumerate(document):
            for drawing in page.get_drawings():
                for item in drawing["items"]:
                    if item[0] == "l":
                        p0, p1 = item[1], item[2]
                        if abs(p0.x - p1.x) <= 0.5 and abs(p0.y - p1.y) > 0.5:
                            per_page[index + 1].add(round(p0.x * 100.0))
                    elif item[0] == "re":
                        rect = item[1]
                        per_page[index + 1].add(round(rect.x0 * 100.0))
                        per_page[index + 1].add(round(rect.x1 * 100.0))

    #: A cell contributes its two vertical edges, deduplicated per table so a
    #: column shared by forty rows is one boundary and not forty.
    wanted = {name: defaultdict(set) for name in MODELS}
    for cell in cells:
        page = cell["page"]
        if page is None or cell["rendered_x0"] is None:
            continue
        origin = cell["rendered_x0"] - cell["model_x"]["global"]
        for name in MODELS:
            left = origin + cell["model_x"][name]
            wanted[name][page].add(round(left))
            wanted[name][page].add(round(left + cell["model_box"][name]))

    out = {"pdf_pages": pages,
           "pdf_vertical_rules": sum(len(v) for v in per_page.values())}
    for name in MODELS:
        scores = {}
        for tol in RULE_TOL:
            # RECALL is the honest direction.  A model predicts a boundary at
            # every cell edge and the PDF draws a rule only where the
            # borderFill says to, so scoring model->rule counts every
            # deliberately borderless edge as a miss.  Scoring rule->model
            # asks the question that has an answer: of the vertical strokes
            # Hancom actually drew, how many does the model put a cell edge
            # under?  ``predicted`` is reported alongside so a model that
            # scores by predicting everywhere is visible as such.
            hit = total = 0
            for page, rules in per_page.items():
                boundaries = sorted(wanted[name].get(page, ()))
                for rule in rules:
                    total += 1
                    if any(abs(rule - value) <= tol for value in boundaries):
                        hit += 1
            predicted = sum(len(v) for v in wanted[name].values())
            scores[str(tol)] = {"hit": hit, "of": total,
                                "predicted": predicted}
        out[name] = scores
    return out


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def summary_line(stem, report, models=MODELS):
    parts = [f"{stem}: {report['cells_compared']} cells "
             f"({report['cells_measurable']} measurable, "
             f"{report['cells_ragged']} ragged) in {report['tables']} tables, "
             f"{report['tables_row_disagreement']} with rows that disagree; "
             f"colAddr==walk {report['coladdr_matches_walk']}"
             f"/{report['cells_compared']}"]
    for name in models:
        w = report["width"][name]
        parts.append(f"  width {name:<11} exact {w['exact']:>5}  "
                     f"grid {w['grid']:>5}  near {w['near']:>5}  "
                     f"/ {w['of']}")
    return "\n".join(parts)


def histogram_block(report, top=6, models=MODELS):
    out = []
    for name in models:
        hist = report["width"][name]["histogram"]
        shown = " ".join(f"{k:+g}x{v}" for k, v in list(hist.items())[:top])
        out.append(f"    {name:<11} residuals: {shown}")
    return "\n".join(out)


def rows_block(report, cells, table_id=None, models=MODELS):
    """Every cell of every row that does not add up, and what the cache did.

    The cache's own box is printed alongside the models: a model's residual
    is its box minus the cache's, so the cache's box is
    ``cellSz@width - literal_residual`` for any cell, and ``alloc`` is how
    much the cache gave that cell over and above its declared width.  That
    column is the measurement; the models are guesses at reproducing it.
    """
    by_table = defaultdict(list)
    for cell in cells:
        by_table[cell["table"]].append(cell)
    out = []
    for tid, group in by_table.items():
        totals = sorted({c["row_total"] for c in group if c["row_total"]})
        declared = group[0]["declared_total"]
        if table_id is None and len(totals) < 2 and totals[:1] == [declared]:
            continue
        out.append(f"  table {tid}: declared {declared}, row totals "
                   f"{totals}")
        for cell in sorted(group, key=lambda c: (c["row"], c["col"])):
            if cell["row_total"] == declared:
                continue
            delta = cell["model_delta"]
            cache = (None if delta["literal"] is None
                     else cell["cell_width"] - delta["literal"])
            alloc = None if cache is None else cache - cell["cell_width"]
            deltas = " ".join(
                f"{name}={delta[name]:+g}" if delta[name] is not None
                else f"{name}=-" for name in models)
            out.append(
                f"    r{cell['row']:<3} c{cell['col']:<3}+{cell['col_span']:<2}"
                f" total {cell['row_total']:>6} short "
                f"{declared - (cell['row_total'] or 0):>+6}  cellSz "
                f"{cell['cell_width']:>6}  cache "
                f"{'-' if cache is None else format(cache, '.0f'):>6}  alloc "
                f"{'-' if alloc is None else format(alloc, '+.0f'):>6}"
                f"  {deltas}")
    return "\n".join(out)


def corpus_block(rows, models=MODELS):
    """Every model over every corpus cell at once."""
    out = ["corpus width fit (cells whose cached horzsize the model "
           "reproduces):"]
    totals = {name: {"exact": 0, "grid": 0, "near": 0, "of": 0}
              for name in models}
    for _stem, report in rows:
        for name in models:
            for key in ("exact", "grid", "near", "of"):
                totals[name][key] += report["width"][name][key]
    for name in models:
        t = totals[name]
        out.append(f"  {name:<11} exact {t['exact']:>5}  grid {t['grid']:>5}"
                   f"  near {t['near']:>5}  / {t['of']}"
                   f"   ({100.0 * t['grid'] / max(1, t['of']):.1f}% on the "
                   f"4-HWPUNIT grid)")
    contested = sum(report["contested"]["cells"] for _s, report in rows)
    out.append(f"  of the {contested} cells the models place differently, on "
               "the grid, and what each loses against the two baselines:")
    for name in models:
        got = sum(report["contested"]["grid"][name] for _s, report in rows)
        back = sum(report["regressions"][name] for _s, report in rows)
        vs = sum(report["regressions_vs_stretch"][name] for _s, report in rows)
        out.append(f"    {name:<11} {got:>5} / {contested}"
                   f"   regressions vs global {back:>3}, vs stretch {vs:>3}")
    hp = {"linesegs": 0, "paragraph_relative": 0, "absolute": 0,
          "max_horzpos": 0}
    for _stem, report in rows:
        for key in ("linesegs", "paragraph_relative", "absolute"):
            hp[key] += report["horzpos"][key]
        hp["max_horzpos"] = max(hp["max_horzpos"],
                                report["horzpos"]["max_horzpos"])
    out.append(f"  horzpos over {hp['linesegs']} in-cell linesegs: "
               f"paragraph-relative {hp['paragraph_relative']}, "
               f"absolute {hp['absolute']}, max {hp['max_horzpos']}")
    if any("rules" in report for _stem, report in rows):
        out.append("  drawn PDF vertical rules a model puts a cell edge "
                   f"under, per tolerance {RULE_TOL} HWPUNIT:")
        for name in models:
            line = []
            for tol in RULE_TOL:
                hit = sum(report["rules"][name][str(tol)]["hit"]
                          for _s, report in rows if "rules" in report)
                of = sum(report["rules"][name][str(tol)]["of"]
                         for _s, report in rows if "rules" in report)
                line.append(f"{hit}/{of}")
            predicted = sum(report["rules"][name][str(RULE_TOL[0])]["predicted"]
                            for _s, report in rows if "rules" in report)
            out.append(f"    {name:<11} " + "   ".join(line)
                       + f"   (edges predicted {predicted})")
    return "\n".join(out)


def residuals_block(rows, models=MODELS):
    """Every cell a model leaves off the grid, with what placed it.

    This is the list a run has to account for one by one before a model can
    ship: the cell, its declared ``cellSz@width`` and ``colSpan``, the box
    the model gave it, the two grid boundaries it sits between and which
    cell's claim each of those sits on, the residual against the cache's
    quantised ``horzsize``, and the row's own declared total beside the
    table's ``hp:sz@width`` -- because a row that does not add up is the only
    place a column model can disagree with itself.
    """
    out = []
    for name in models:
        cells = [(stem, entry) for stem, report in rows
                 for entry in report["off_grid"][name]]
        out.append(f"{name}: {len(cells)} cells off the 4-HWPUNIT grid")
        for stem, e in cells:
            bounds = e.get("boundaries")
            where = (f" [{bounds[0]}..{bounds[1]}]" if bounds else "")
            out.append(
                f"  {stem:<12} t{e['table']} r{e['row']}c{e['col']}"
                f"+{e['span']}{where} declared {e['declared']} "
                f"box {e['box']} residual {e['residual']:+g} "
                f"horzsize {e['horzsize']} "
                f"row total {e['row_total']} of {e['table_width']} "
                f"paras {e['paragraphs']}")
    return "\n".join(out)


def heights_block(rows):
    """The row-height histogram, summed over the corpus."""
    keys = ("tables", "rows", "unit_rows_agreeing", "rows_without_unit_cell",
            "span_cells", "span_exact", "table_exact")
    total = {key: 0 for key in keys}
    hists = {"unit_row_spread": Counter(), "span_residual": Counter(),
             "table_residual": Counter()}
    for _stem, report in rows:
        shape = report["rows"]
        for key in keys:
            total[key] += shape[key]
        for name, hist in hists.items():
            for key, count in shape[name].items():
                hist[key] += count
    out = [f"row heights ({total['tables']} tables, {total['rows']} rows):",
           f"  rows whose rowSpan=1 cells all declare one height: "
           f"{total['unit_rows_agreeing']}/{total['rows']}"
           f"   (rows listing no rowSpan=1 cell at all: "
           f"{total['rows_without_unit_cell']})",
           f"  rowSpan cells whose height equals the sum of the rows it "
           f"covers: {total['span_exact']}/{total['span_cells']}",
           f"  tables whose row heights sum to hp:sz@height: "
           f"{total['table_exact']}/{total['tables']}"]
    for name in ("unit_row_spread", "span_residual", "table_residual"):
        shown = " ".join(f"{k}x{v}" for k, v in
                         sorted(hists[name].items(), key=lambda kv: -kv[1])[:8])
        out.append(f"  {name}: {shown}")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="track_probe.py",
        description="Score every column model -- the global track solve, a "
                    "literal per-row tiling, six ways of handing a row's "
                    "shortfall to its own cells, and four shared column "
                    "grids -- against the cache's horzsize and the "
                    "reference PDF's own table rules. Measures; changes "
                    "nothing.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every corpus form")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--layout-policy", default="cache")
    parser.add_argument("--pdf", action="store_true",
                        help="also score cell x against the reference PDF's "
                             "vertical rules (needs PyMuPDF)")
    parser.add_argument("--rows", action="store_true",
                        help="print, per table whose rows disagree, every "
                             "cell of every disagreeing row: what it "
                             "declares, what the cache gave it, and each "
                             "model's residual")
    parser.add_argument("--residuals", action="store_true",
                        help="list every cell each model leaves off the "
                             "4-HWPUNIT grid, with the boundaries that "
                             "placed it and the row's declared total")
    parser.add_argument("--heights", action="store_true",
                        help="also report the shape of the row-height "
                             "question: hp:tr has no height, so a row's "
                             "height has to come from its cells")
    parser.add_argument("--models", default=",".join(MODELS),
                        help="comma-separated subset of "
                             + ",".join(MODELS))
    parser.add_argument("--json", help="write the full per-cell report")
    parser.add_argument("--no-text", action="store_true")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    quiet = args.no_text
    models = tuple(name for name in MODELS
                   if name in {n.strip() for n in args.models.split(",")})
    if not models:
        build_parser().error("--models named none of " + ",".join(MODELS))

    if args.corpus:
        forms = layout_divergence.corpus_forms(repo_root)
        labels = layout_divergence.short_labels([hwpx.stem
                                                 for hwpx, _ in forms])
        rows = []
        for hwpx, pdf in forms:
            report = probe_form(hwpx, dpi=args.dpi, policy=args.layout_policy,
                                repo_root=repo_root,
                                pdf_path=pdf if args.pdf else None)
            rows.append((labels[hwpx.stem], report))
            if not quiet:
                print(summary_line(labels[hwpx.stem], report, models))
                print(histogram_block(report, models=models))
                if args.rows:
                    block = rows_block(report, report["cells"], models=models)
                    if block:
                        print(block)
        if not quiet:
            print()
            print(corpus_block(rows, models))
            if args.residuals:
                print()
                print(residuals_block(rows, models))
            if args.heights:
                print()
                print(heights_block(rows))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True, default=str) + "\n",
                encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    hwpx = Path(args.input)
    pdf = None
    if args.pdf:
        for candidate, reference in layout_divergence.corpus_forms(repo_root):
            if candidate.stem == hwpx.stem:
                pdf = reference
    report = probe_form(hwpx, dpi=args.dpi, policy=args.layout_policy,
                        repo_root=repo_root, pdf_path=pdf)
    if not quiet:
        print(summary_line(hwpx.stem, report, models))
        print(histogram_block(report, models=models))
        if args.rows:
            print(rows_block(report, report["cells"], table_id=True,
                             models=models))
        if args.residuals:
            print(residuals_block([(hwpx.stem, report)], models))
        if args.heights:
            print(heights_block([(hwpx.stem, report)]))
        if "rules" in report:
            print(f"  PDF rules: {json.dumps(report['rules'], sort_keys=True)}")
        print(f"  horzpos: {json.dumps(report['horzpos'], sort_keys=True)}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                       default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
