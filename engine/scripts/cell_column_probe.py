#!/usr/bin/env python3
"""Is the text column we give a table cell the column Hancom gave it?

#267 found that two of the seven paragraphs carrying the remaining class-B
divergence are not advance failures at all.  On ``jumin`` paragraph 46 the
text column this renderer hands the paragraphs of a table cell is 631 HWPUNIT
NARROWER than the ``hp:lineseg@horzsize`` Hancom saved for the same lines; on
``saeopja`` paragraph 166 it is 803 wider.  Every cached line on both fits our
own measurement of its text, so the advance widths are not the problem: the
column is, and a wrong column moves breaks.

This probe asks the question for every cell on the corpus at once.  For every
``hp:tc`` the renderer actually draws, it records

* the column the renderer itself passed the cell's paragraphs -- captured off
  the ``avail_w_hwp`` argument ``_render_cell_content`` hands
  ``_render_paragraphs``, so it is the renderer's own number and not a second
  derivation of it that could be wrong in its own way,
* the box the column was cut from (``x1 - x0``, the solved track sum),
* everything the OWPML table model offers as a candidate for the difference:
  ``cellSz@width``, ``cellSpan@colSpan``, the cell's own ``hp:cellMargin``
  when it has one, the table's ``hp:inMargin``, the left/right border widths
  of the cell's ``hh:borderFill``, and ``hp:tbl@cellSpacing``,

and compares it against the cache's ``hp:lineseg@horzsize``.

TWO DELTAS, AND WHY BOTH
------------------------
``horzsize`` is a LINE box, not a column: ``hh:margin`` left/right and a first
line's ``intent`` narrow it inside the column.  So the probe reports

``delta_cell``
    ``column - max(horzsize)`` over the cell's cached lines.  This is the
    delta the task names, and it is the right one whenever the cell's
    paragraphs have no left/right margin -- which is most cell content.

``delta_line``
    per cached line, ``_line_box(para, i, column)[1] - horzsize``.  The
    paragraph's own indents enter both sides identically and cancel, so this
    isolates the CELL geometry from the paragraph's.  A cell whose lines do
    not agree on one value is reported as ``ragged`` and excluded from the
    fit: something other than the column is moving its boxes.

THE FIT
-------
Five candidate terms are read per cell::

    margins    cellMargin.left + cellMargin.right
    inmargin   inMargin.left + inMargin.right
    borders    borderFill left width + right width
    spacing    cellSpacing
    solved     (solved track sum) - (declared cellSz width)

and every signed combination in ``{-1, 0, +1}^5`` is scored by how many cells
it drives to ``delta == 0``.  The winner is reported with its runners-up, so a
combination that wins by a hair says so rather than being read as a rule.

Usage::

    python engine/scripts/cell_column_probe.py FORM.hwpx
    python engine/scripts/cell_column_probe.py --corpus
    python engine/scripts/cell_column_probe.py --corpus --json out.json --no-text
    python engine/scripts/cell_column_probe.py FORM.hwpx --paragraph 46

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout_divergence  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

#: The candidate terms, in the order the fit prints them.  ``inset`` is
#: ``margins`` or ``inmargin`` per ``hp:tc@hasMargin`` — the spec's own rule,
#: offered to the fit as a candidate like any other rather than assumed.
TERMS = ("margins", "inmargin", "inset", "borders", "spacing", "solved")

#: ``hp:lineseg@horzsize`` is saved on a grid of this many HWPUNIT.  Measured,
#: not assumed: ``grid_multiples`` in every report counts how many cached
#: in-cell linesegs land on it.
HORZSIZE_GRID = 4

#: A residual this small is a rounding difference, not a rule: 8 HWPUNIT is
#: 0.03 mm, a third of a pixel at 600 dpi, and no line break turns on it.
NEAR_HWP = 8.0

RULE_QUESTION = (
    "for every cached text line inside a table cell, does the text column "
    "this renderer gives the cell equal the cache's hp:lineseg@horzsize, and "
    "which table attribute explains the difference where it does not?")


class CellColumnRenderer(own_render.OwnRenderer):
    """``OwnRenderer`` that records the text column every cell was given.

    ``_render_cell_content`` computes a cell's column and passes it straight
    to ``_render_paragraphs``; wrapping both is enough to read that number
    off the renderer without recomputing it here.  The stack is what makes
    the reading correct for a table nested inside a cell: the innermost
    pending cell is always the one whose paragraphs are about to be laid out.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: ``{id(hp:tc): record}`` -- first draw wins, so a table the flow
        #: split across two pages is measured once.
        self.cell_columns = {}
        self._cell_stack = []

    def _render_cell_content(self, draw, cell, x0, y0, x1, y1):
        self._cell_stack.append({"cell": cell, "box": x1 - x0, "done": False})
        try:
            return super()._render_cell_content(draw, cell, x0, y0, x1, y1)
        finally:
            self._cell_stack.pop()

    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        if self._cell_stack and not self._cell_stack[-1]["done"]:
            frame = self._cell_stack[-1]
            frame["done"] = True
            self.cell_columns.setdefault(id(frame["cell"]["tc"]), {
                "cell": frame["cell"],
                "column_hwp": avail_w_hwp,
                "box_hwp": frame["box"],
            })
        return super()._render_paragraphs(draw, paragraphs, origin_hwp,
                                          avail_w_hwp, block_offset_hwp)


def _table_of_cells(sections):
    """``{id(hp:tc): the hp:tbl that owns it}`` -- nearest enclosing table."""
    owner = {}
    for root in sections:
        stack = [(root, None)]
        while stack:
            el, tbl = stack.pop()
            name = own_render._local(el.tag)
            if name == "tbl":
                tbl = el
            elif name == "tc" and tbl is not None:
                owner[id(el)] = tbl
            for kid in el:
                stack.append((kid, tbl))
    return owner


def _terms_for(renderer, record, tbl):
    """The five candidate terms for one cell, in HWPUNIT."""
    cell = record["cell"]
    tc = cell["tc"]
    margin = cell["margin"]
    inmargin = own_render._kid(tbl, "inMargin") if tbl is not None else None
    size = own_render._kid(tc, "cellSz")
    declared = own_render._iattr(size, "width") if size is not None else 0
    bf = renderer.defs["border_fill"].get(tc.get("borderFillIDRef") or "") or {}

    def _bw(side):
        spec = bf.get(side) or {}
        if (spec.get("type") or "NONE").upper() == "NONE":
            return 0
        return spec.get("width_hwp") or 0

    margins = margin["left"] + margin["right"]
    table_inset = (own_render._iattr(inmargin, "left")
                   + own_render._iattr(inmargin, "right"))
    return {
        "margins": margins,
        "inmargin": table_inset,
        # hp:tc@hasMargin — 셀 여백 사용 여부.  "1" means the cell's own
        # hp:cellMargin overrides; "0" (and absent) means the table's
        # hp:inMargin is the inset and the cell's stored cellMargin is stale.
        "inset": margins if tc.get("hasMargin") == "1" else table_inset,
        "borders": _bw("left") + _bw("right"),
        "spacing": (own_render._iattr(tbl, "cellSpacing")
                    if tbl is not None else 0),
        "solved": record["box_hwp"] - declared,
    }


def _cell_report(renderer, record, tbl, tol):
    """One cell's comparison, or ``None`` when it caches no measurable line."""
    cell = record["cell"]
    tc = cell["tc"]
    column = record["column_hwp"]
    addr = own_render._kid(tc, "cellAddr")
    size = own_render._kid(tc, "cellSz")

    cached = []
    line_deltas = []
    paragraphs = []
    for para in cell["paras"]:
        index = renderer.paragraph_index.get(id(para.el))
        if para.linesegs:
            paragraphs.append(index)
        for i, seg in enumerate(para.linesegs):
            horzsize = seg.get("horzsize")
            if horzsize is None:
                continue
            try:
                horzsize = int(horzsize)
            except ValueError:
                continue
            cached.append(horzsize)
            ours = renderer._line_box(para, i, column)[1]
            line_deltas.append(ours - horzsize)
    if not cached:
        return None

    lo, hi = min(line_deltas), max(line_deltas)
    return {
        "paragraphs": paragraphs,
        "row": own_render._iattr(addr, "rowAddr"),
        "col": own_render._iattr(addr, "colAddr"),
        "col_span": cell["cspan"],
        "row_span": cell["rspan"],
        "cell_width": own_render._iattr(size, "width") if size is not None else 0,
        "box_hwp": record["box_hwp"],
        "column_hwp": column,
        "lines": len(cached),
        "horzsize_max": max(cached),
        "delta_cell": column - max(cached),
        "delta_line": lo if abs(lo - hi) <= tol else None,
        "delta_line_lo": lo,
        "delta_line_hi": hi,
        "ragged": abs(lo - hi) > tol,
        "has_cell_margin": own_render._kid(tc, "cellMargin") is not None,
        "has_margin_flag": tc.get("hasMargin"),
        "cached_horzsize": cached,
        "terms": _terms_for(renderer, record, tbl),
    }


def _residuals(cells, signs):
    """What each cell has left over after a combination is subtracted."""
    out = []
    for cell in cells:
        if cell["delta_line"] is None:
            continue
        out.append(cell["delta_line"] - sum(
            sign * cell["terms"][name]
            for sign, name in zip(signs, TERMS) if sign))
    return out


def _fit(cells, tol):
    """Score every signed combination of the terms; return it sorted.

    Scored twice.  ``exact`` is how many cells the combination drives to
    zero; ``within`` is how many it drives inside 8 HWPUNIT — 0.03 mm, a
    third of a device pixel at 600 dpi, which no line break can turn on.  A
    combination that is RIGHT but rounds differently from Hancom scores badly
    on the first and well on the second, and the two together say which is
    happening rather than leaving a near-miss looking like a miss.
    """
    scored = []
    measurable = [c for c in cells if c["delta_line"] is not None]
    for signs in itertools.product((-1, 0, 1), repeat=len(TERMS)):
        residuals = _residuals(measurable, signs)
        exact = sum(1 for value in residuals if abs(value) <= tol)
        within = sum(1 for value in residuals if abs(value) <= NEAR_HWP)
        scored.append({
            "signs": dict(zip(TERMS, signs)),
            "label": _label(signs),
            "exact": exact,
            "within": within,
            "of": len(measurable),
            "residuals": dict(sorted(Counter(
                round(value, 3) for value in residuals).items(),
                key=lambda kv: -kv[1])[:8]),
        })
    scored.sort(key=lambda row: (-row["within"], -row["exact"],
                                 sum(1 for s in row["signs"].values() if s),
                                 row["label"]))
    return scored


def _label(signs):
    parts = [("+" if sign > 0 else "-") + name
             for sign, name in zip(signs, TERMS) if sign]
    return " ".join(parts) if parts else "(nothing)"


def probe_form(hwpx_path, dpi=own_render.DEFAULT_DPI, policy="cache",
               tol=0.5, repo_root=None):
    """Compare every drawn cell's text column against its cached horzsize."""
    renderer = CellColumnRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                                  layout_policy=policy)
    renderer.render()
    owner = _table_of_cells(renderer.sections)

    cells = []
    for record in renderer.cell_columns.values():
        tbl = owner.get(id(record["cell"]["tc"]))
        report = _cell_report(renderer, record, tbl, tol)
        if report is not None:
            cells.append(report)
    cells.sort(key=lambda c: (c["paragraphs"] or [10 ** 9], c["row"], c["col"]))

    exact = [c for c in cells if abs(c["delta_cell"]) <= tol]
    off = [c for c in cells if abs(c["delta_cell"]) > tol]
    histogram = Counter(c["delta_cell"] for c in cells)
    dominant = max(histogram.items(), key=lambda kv: (kv[1], -abs(kv[0]))) \
        if histogram else (0, 0)
    off_hist = Counter(c["delta_cell"] for c in off)
    dominant_off = (max(off_hist.items(), key=lambda kv: (kv[1], -abs(kv[0])))
                    if off_hist else None)

    # Does the cache save horzsize on a grid?  A rule that lands 1-3 HWPUNIT
    # above every cached box is the same rule plus a quantiser, and the only
    # way to tell that from a rule that is simply wrong is to count.
    horzsizes = [h for c in cells for h in c["cached_horzsize"]]
    on_grid = sum(1 for h in horzsizes if h % HORZSIZE_GRID == 0)
    for cell in cells:
        cell.pop("cached_horzsize", None)

    return {
        "linesegs": len(horzsizes),
        "horzsize_on_grid": on_grid,
        "horzsize_grid": HORZSIZE_GRID,
        "has_margin_cells": sum(1 for c in cells
                                if c["has_margin_flag"] == "1"),
        "cells_drawn": len(renderer.cell_columns),
        "cells_compared": len(cells),
        "cells_exact": len(exact),
        "cells_off": len(off),
        "cells_ragged": sum(1 for c in cells if c["ragged"]),
        "delta_histogram": {str(k): v for k, v in sorted(histogram.items())},
        "dominant_delta": dominant[0],
        "dominant_delta_cells": dominant[1],
        "dominant_off_delta": dominant_off[0] if dominant_off else None,
        "dominant_off_cells": dominant_off[1] if dominant_off else 0,
        "fit": _fit(cells, tol)[:8],
        "cells": cells,
    }


# -- output --------------------------------------------------------------

def summary_line(stem, report):
    dominant = report["dominant_delta"]
    off_delta = report["dominant_off_delta"]
    tail = ("all exact" if not report["cells_off"]
            else f"dominant off delta {off_delta:+g} on "
                 f"{report['dominant_off_cells']} cells")
    return (f"{stem}: compared {report['cells_compared']} "
            f"(of {report['cells_drawn']} drawn), exact "
            f"{report['cells_exact']}, off {report['cells_off']}, ragged "
            f"{report['cells_ragged']}; hasMargin=1 on "
            f"{report['has_margin_cells']}; horzsize on the "
            f"{report['horzsize_grid']}-HWPUNIT grid "
            f"{report['horzsize_on_grid']}/{report['linesegs']}; "
            f"modal delta {dominant:+g}; {tail}")


def fit_table(report, top=5):
    out = [f"  fit (cells driven to zero / to within {NEAR_HWP:g} HWPUNIT):"]
    for row in report["fit"][:top]:
        out.append(f"    exact {row['exact']:>5}  near {row['within']:>5}"
                   f"  / {row['of']:<5} {row['label']}")
    if report["fit"]:
        out.append(f"    residuals of the best: {report['fit'][0]['residuals']}")
    return "\n".join(out)


def worst_cells(report, count=5, paragraphs=()):
    """The largest deltas, plus any cell holding a named paragraph."""
    named = [c for c in report["cells"]
             if set(c["paragraphs"]) & set(paragraphs)]
    ordered = sorted(report["cells"], key=lambda c: -abs(c["delta_cell"]))
    picked, seen = [], set()
    for cell in named + ordered:
        key = (cell["row"], cell["col"], tuple(cell["paragraphs"]))
        if key in seen:
            continue
        seen.add(key)
        picked.append(cell)
        if len(picked) >= count + len(named):
            break
    out = ["  cell                       delta  colSpan  cellSz   box  column"
           "  terms"]
    for cell in picked:
        terms = " ".join(f"{name}={cell['terms'][name]}" for name in TERMS
                         if cell["terms"][name])
        para = ",".join(str(p) for p in cell["paragraphs"][:3]) or "-"
        out.append(
            f"    r{cell['row']}c{cell['col']} p{para:<14} "
            f"{cell['delta_cell']:>+6g} {cell['col_span']:>8} "
            f"{cell['cell_width']:>7} {cell['box_hwp']:>5g} "
            f"{cell['column_hwp']:>7g}  {terms or '-'}")
    return "\n".join(out)


def corpus_fit(rows, tol=0.5, top=6):
    """The same fit run over every corpus cell at once."""
    cells = [c for _stem, report in rows for c in report["cells"]]
    scored = _fit(cells, tol)
    out = [f"corpus fit over {len([c for c in cells if c['delta_line'] is not None])} "
           f"measurable cells (of {len(cells)} compared):"]
    for row in scored[:top]:
        out.append(f"  exact {row['exact']:>5}  near {row['within']:>5}"
                   f"  / {row['of']:<5} {row['label']}")
    if scored:
        out.append(f"  residuals of the best: {scored[0]['residuals']}")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cell_column_probe.py",
        description="Compare the text column this renderer gives every table "
                    "cell against the cache's hp:lineseg@horzsize, and fit "
                    "the difference against the table attributes. Measures; "
                    "changes nothing.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every corpus form and print a table")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--layout-policy", default="cache",
                        help="the policy to render under (default cache -- "
                             "the one whose columns the cache can be read "
                             "against line for line)")
    parser.add_argument("--tol", type=float, default=0.5,
                        help="a delta at or under this many HWPUNIT is zero "
                             "(default 0.5 -- the quantities are integers)")
    parser.add_argument("--paragraph", type=int, action="append", default=[],
                        help="always print the cell holding this paragraph "
                             "index; repeatable")
    parser.add_argument("--json", help="write the full per-cell report")
    parser.add_argument("--no-text", action="store_true",
                        help="write only the JSON report")
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
        for hwpx, _pdf in forms:
            report = probe_form(hwpx, dpi=args.dpi, policy=args.layout_policy,
                                tol=args.tol, repo_root=repo_root)
            rows.append((labels[hwpx.stem], report))
            if not quiet:
                print(summary_line(labels[hwpx.stem], report))
                if report["cells_off"]:
                    print(worst_cells(report, paragraphs=args.paragraph))
                print(fit_table(report))
        if not quiet:
            print()
            print(corpus_fit(rows, tol=args.tol))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    stem = Path(args.input).stem
    report = probe_form(Path(args.input), dpi=args.dpi,
                        policy=args.layout_policy, tol=args.tol,
                        repo_root=repo_root)
    if not quiet:
        print(summary_line(stem, report))
        print(worst_cells(report, paragraphs=args.paragraph))
        print(fit_table(report))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
