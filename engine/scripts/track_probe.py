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
    python engine/scripts/track_probe.py FORM.hwpx --table 1 --rows

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import cell_column_probe  # noqa: E402
import layout_divergence  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

MODELS = ("global", "literal", "addr", "stretch")

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
            })
        rows.append(row)
    sz = own_render._kid(tbl, "sz")
    return {
        "rows": rows,
        "row_cnt": own_render._iattr(tbl, "rowCnt", len(rows)),
        "col_cnt": own_render._iattr(tbl, "colCnt", 0),
        "declared_width": own_render._iattr(sz, "width") if sz is not None else 0,
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


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def probe_form(hwpx_path, dpi=own_render.DEFAULT_DPI, policy="cache",
               repo_root=None, pdf_path=None):
    """Score the three column models on one form."""
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
        # ``stretch``: how much the last cell a row lists has to grow (or
        # shrink) for the row to end at the table's declared right edge.
        table["stretch"] = {}
        for r, last in enumerate(table["last_of_row"]):
            if last is None or not table["declared_width"]:
                continue
            table["stretch"][id(last["tc"])] = (table["declared_width"]
                                                - table["row_totals"][r])
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

        # The rendered box is the global model's box by construction; every
        # other model's per-line residual is the rendered one shifted by the
        # difference in box width, because the cell inset and the
        # paragraph's own margins enter both sides identically.
        rendered_box = record["box_hwp"]
        model_box = {
            "global": rendered_box,
            "literal": declared,
            "addr": declared,
            "stretch": declared + table["stretch"].get(id(tc), 0),
        }
        gx = xs[min(col, len(xs) - 1)] if xs else 0
        lx = table["literal_x"].get(id(tc), 0)
        model_x = {
            "global": gx,
            "literal": lx,
            "addr": gx,
            "stretch": lx,
        }
        delta = base["delta_line"]
        base.update({
            "model_box": model_box,
            "model_x": model_x,
            "model_delta": {
                name: (None if delta is None
                       else delta + (model_box[name] - rendered_box))
                for name in MODELS},
            "rendered_box": rendered_box,
            "rendered_x0": box.get("x0"),
            "page": box.get("page"),
            "table": id(tbl),
            "col_walked": table["walked"].get(id(tc)),
            "row_total": (table["row_totals"][base["row"]]
                          if base["row"] < len(table["row_totals"]) else None),
            "declared_total": table["declared_width"],
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
        "grid": {n: sum(1 for c in contested
                        if 0 <= c["model_delta"][n] < 4) for n in MODELS},
    }
    report["regressions"] = {
        n: sum(1 for c in cells
               if c["delta_line"] is not None
               and 0 <= c["model_delta"]["global"] < 4
               and not 0 <= c["model_delta"][n] < 4)
        for n in MODELS}
    report["horzpos"] = horzpos_oracle(renderer, cells)
    if pdf_path is not None:
        report["rules"] = pdf_rule_oracle(renderer, tables, cells, pdf_path)
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

def summary_line(stem, report):
    parts = [f"{stem}: {report['cells_compared']} cells "
             f"({report['cells_measurable']} measurable, "
             f"{report['cells_ragged']} ragged) in {report['tables']} tables, "
             f"{report['tables_row_disagreement']} with rows that disagree; "
             f"colAddr==walk {report['coladdr_matches_walk']}"
             f"/{report['cells_compared']}"]
    for name in MODELS:
        w = report["width"][name]
        parts.append(f"  width {name:<8} exact {w['exact']:>5}  "
                     f"grid {w['grid']:>5}  near {w['near']:>5}  "
                     f"/ {w['of']}")
    return "\n".join(parts)


def histogram_block(report, top=6):
    out = []
    for name in MODELS:
        hist = report["width"][name]["histogram"]
        shown = " ".join(f"{k:+g}x{v}" for k, v in list(hist.items())[:top])
        out.append(f"    {name:<8} residuals: {shown}")
    return "\n".join(out)


def rows_block(report, cells, table_id=None):
    """What each row of a table declares, and which model reproduces it."""
    by_table = defaultdict(list)
    for cell in cells:
        by_table[cell["table"]].append(cell)
    out = []
    for tid, group in by_table.items():
        totals = sorted({c["row_total"] for c in group if c["row_total"]})
        if table_id is None and len(totals) < 2:
            continue
        declared = group[0]["declared_total"]
        out.append(f"  table {tid}: declared {declared}, row totals "
                   f"{totals}")
        seen = set()
        for cell in sorted(group, key=lambda c: (c["row"], c["col"])):
            if cell["row"] in seen:
                continue
            seen.add(cell["row"])
            deltas = " ".join(
                f"{name[0]}={cell['model_delta'][name]:+g}"
                if cell["model_delta"][name] is not None else f"{name[0]}=-"
                for name in MODELS)
            out.append(
                f"    r{cell['row']:<3} total {cell['row_total']:>6}  "
                f"cellSz {cell['cell_width']:>6}  box {cell['rendered_box']:>6g}"
                f"  {deltas}")
    return "\n".join(out)


def corpus_block(rows):
    """The three models over every corpus cell at once."""
    out = ["corpus width fit (cells whose cached horzsize the model "
           "reproduces):"]
    totals = {name: {"exact": 0, "grid": 0, "near": 0, "of": 0}
              for name in MODELS}
    for _stem, report in rows:
        for name in MODELS:
            for key in ("exact", "grid", "near", "of"):
                totals[name][key] += report["width"][name][key]
    for name in MODELS:
        t = totals[name]
        out.append(f"  {name:<8} exact {t['exact']:>5}  grid {t['grid']:>5}"
                   f"  near {t['near']:>5}  / {t['of']}"
                   f"   ({100.0 * t['grid'] / max(1, t['of']):.1f}% on the "
                   f"4-HWPUNIT grid)")
    contested = sum(report["contested"]["cells"] for _s, report in rows)
    out.append(f"  of the {contested} cells the models place differently, on "
               "the grid:")
    for name in MODELS:
        got = sum(report["contested"]["grid"][name] for _s, report in rows)
        back = sum(report["regressions"][name] for _s, report in rows)
        out.append(f"    {name:<8} {got:>5} / {contested}"
                   f"   (cells the global solve had on the grid and this "
                   f"model does not: {back})")
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
        for name in MODELS:
            line = []
            for tol in RULE_TOL:
                hit = sum(report["rules"][name][str(tol)]["hit"]
                          for _s, report in rows if "rules" in report)
                of = sum(report["rules"][name][str(tol)]["of"]
                         for _s, report in rows if "rules" in report)
                line.append(f"{hit}/{of}")
            predicted = sum(report["rules"][name][str(RULE_TOL[0])]["predicted"]
                            for _s, report in rows if "rules" in report)
            out.append(f"    {name:<8} " + "   ".join(line)
                       + f"   (edges predicted {predicted})")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="track_probe.py",
        description="Score three column models -- the global track solve, a "
                    "literal per-row tiling, and declared widths on the "
                    "global x grid -- against the cache's horzsize and the "
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
                        help="print, per table whose rows disagree, what each "
                             "row declares and each model's residual")
    parser.add_argument("--json", help="write the full per-cell report")
    parser.add_argument("--no-text", action="store_true")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    quiet = args.no_text

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
                print(summary_line(labels[hwpx.stem], report))
                print(histogram_block(report))
                if args.rows:
                    block = rows_block(report, report["cells"])
                    if block:
                        print(block)
        if not quiet:
            print()
            print(corpus_block(rows))
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
        print(summary_line(hwpx.stem, report))
        print(histogram_block(report))
        if args.rows:
            print(rows_block(report, report["cells"], table_id=True))
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
