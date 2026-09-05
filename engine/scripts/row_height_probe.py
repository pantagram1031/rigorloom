#!/usr/bin/env python3
"""How tall does Hancom make a table row, and does this renderer agree?

#265's ``class_b_probe.py`` attributes 109 of the corpus' class-B paragraphs
to ``table_row_heights``: text below a table sits at a different y under
computed layout than under the cache because our table's rows come out a
different height from Hancom's.  #268 fixed which margin insets a cell and
#270 measured the column a row's cells are laid out in; this probe asks the
remaining question on the other axis -- what makes a ROW as tall as it is.

WHAT THE CACHE CAN AND CANNOT SAY
---------------------------------
The task that opened this run proposed reading each row's top out of the
cached ``hp:lineseg@vertpos`` of the cells in it.  It cannot be read that
way, for the same reason #270 could not read a cell's x out of ``horzpos``:
an in-cell ``vertpos`` is measured from the top of the cell's own CONTENT
box, before the cell's vertical alignment offset, so every cell's first line
starts at or near 0 whatever row it is in.  ``vertpos_oracle`` in every
report counts that rather than assuming it.

What the cache does carry is the table's TOTAL height.  A paragraph whose
whole content is one inline table caches one ``hp:lineseg``, and #261
measured that an inline object's cached ``vertsize`` is the object's
``hp:sz`` height plus its own vertical ``hp:outMargin``.  So

    lineseg vertsize - outMargin.top - outMargin.bottom  ==  hp:sz@height

is a check on that reading, and where it holds the declared table height IS
the height Hancom drew.  Summed over a table's rows, that is one equation per
table, and it is the oracle the candidates below are scored against:
**a row-height rule whose rows do not add up to the table's own declared
height is wrong.**

THE CANDIDATES
--------------
Per cell the renderer already has three quantities -- the declared
``cellSz@height``, the content height of its paragraphs, and the cell inset
(``cell_inset``, #268).  The candidates differ in how they combine them and
in what a ``rowSpan`` cell contributes:

``declared``        the declared ``cellSz@height`` alone
``content``         content + top inset + bottom inset alone
``max``             the larger of the two -- what ``_table_tracks`` does today
``max_spacing``     ``max`` with the LAST line's ``spacing`` inside the content
``max_marginnext``  ``max`` with the last paragraph's ``hh:margin`` next added
``max_noinset``     ``max`` with the insets left out of the content term
``max_span_equal``  ``max``, a ``rowSpan`` cell's height split evenly
``max_span_last``   ``max``, all of it charged to the last row it spans
``max_span_ignore`` ``max``, a ``rowSpan`` cell contributing no row constraint

Each is solved with :func:`own_render.solve_tracks` exactly as the renderer
solves it, and scored twice: with the compress-to-``hp:sz@height`` step the
renderer applies, and without it.  The second is the one that measures the
rule, because the first hides every disagreement inside the compress.

A SECOND, CIRCULAR ORACLE, LABELLED AS SUCH
-------------------------------------------
Where every unspanned cell of a row declares the same ``cellSz@height``, that
value is reported as the row's declared height and the candidates are scored
against it.  This is CIRCULAR for the ``declared`` candidate, which scores
100% on it by construction, and it is printed as ``rows_declared`` rather
than as the answer.  It is worth having anyway: a candidate that does NOT
reproduce the declared height on a row whose content fits comfortably inside
it is saying the file's own number is decoration.

THE PDF ORACLE (``--pdf``)
--------------------------
The reference PDF is Hancom's own export, and every horizontal table rule in
it sits on a row boundary.  Scored in the only honest direction, the one
#270 used for the vertical rules: of the horizontal strokes Hancom actually
drew inside a table's x-span, how many does a candidate put a row boundary
under?  A boundary whose ``borderFill`` is ``NONE`` is drawn nowhere, so
scoring the other way would count every deliberately borderless row edge as
a miss.

Usage::

    python engine/scripts/row_height_probe.py FORM.hwpx
    python engine/scripts/row_height_probe.py --corpus
    python engine/scripts/row_height_probe.py --corpus --pdf --json out.json --no-text

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

import layout_divergence  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

#: The candidates, in the order every table prints them.
CANDIDATES = (
    "declared",
    "content",
    "max",
    "max_spacing",
    "max_marginnext",
    "max_noinset",
    "max_span_equal",
    "max_span_last",
    "max_span_ignore",
)

#: A row height is an integer count of HWPUNIT, so "exact" is exact.  The
#: 4-HWPUNIT band is reported beside it because #263 measured the PERCENT
#: leading -- which is what a content height is made of -- on that grid, so a
#: content-driven row can land up to a few units off a declared one without
#: the rule being different.
NEAR_HWP = 4

#: One device pixel at 144 dpi, the tolerance #270 scored its vertical rules
#: at.  1 pt = 100 HWPUNIT.
RULE_TOL = (50, 100)

RULE_QUESTION = (
    "what makes a table row as tall as it is -- the declared cellSz@height, "
    "the height of the cell's own content plus its inset, or the larger of "
    "the two -- and do a table's rows add up to the height the file declares "
    "for it?")


# --------------------------------------------------------------------------
# Reading the renderer
# --------------------------------------------------------------------------

class RowHeightRenderer(own_render.OwnRenderer):
    """``OwnRenderer`` that records every table's row solve as it happens.

    The content height of a cell is captured off ``_paragraph_block_extent``
    -- the renderer's own number, the one ``_table_tracks`` actually feeds
    the row solve -- rather than rederived here, for the same reason #268
    read the text column off ``avail_w_hwp``.  A second derivation could be
    wrong in its own way and would be measuring itself.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: ``{table index in document order: record}`` -- first draw wins, so
        #: a table the flow pass split across two pages is measured once.
        self.tables = {}
        #: ``{id(first hp:p element): content height}``
        self._content = {}
        self._index = None

    def _indexes(self):
        """``({id(hp:tbl): n}, {id(hp:p): n})`` in document order."""
        if self._index is None:
            tbl_index, para_index = {}, {}
            for root in self.sections:
                for el in root.iter():
                    name = own_render._local(el.tag)
                    if name == "tbl":
                        tbl_index[id(el)] = len(tbl_index)
                    elif name == "p":
                        para_index[id(el)] = len(para_index)
            self._index = (tbl_index, para_index)
        return self._index

    def _paragraph_block_extent(self, draw, paras, avail_w_hwp):
        value = super()._paragraph_block_extent(draw, paras, avail_w_hwp)
        if paras:
            self._content.setdefault(id(paras[0].el), value)
        return value

    def _table_tracks(self, draw, tbl, natural_rows=False):
        xs, ys, cells = super()._table_tracks(draw, tbl, natural_rows)
        tbl_index, _paras = self._indexes()
        key = tbl_index.get(id(tbl))
        if key is not None and key not in self.tables:
            self.tables[key] = {
                "tbl": tbl,
                "xs": list(xs),
                "ys": list(ys),
                "natural_rows": bool(natural_rows),
                "cells": [self._cell_record(cell) for cell in cells],
            }
        return xs, ys, cells

    def _cell_record(self, cell):
        paras = cell["paras"]
        content = self._content.get(id(paras[0].el)) if paras else 0
        return {
            "row": cell["row"],
            "col": cell["col"],
            "rspan": cell["rspan"],
            "cspan": cell["cspan"],
            "declared": cell["declared_height"],
            "inset": cell["margin"]["top"] + cell["margin"]["bottom"],
            "content": 0 if content is None else content,
            "content_spacing": _cached_spacing_extent(cell["tc"]),
            "margin_next": (paras[-1].para_pr.get("margin_next", 0)
                            if paras else 0),
            "linesegs": _cell_linesegs(cell["tc"]),
            "first_vertpos": _first_vertpos(cell["tc"]),
        }

    def _render_table(self, draw, tbl, origin_hwp):
        tbl_index, _paras = self._indexes()
        key = tbl_index.get(id(tbl))
        result = super()._render_table(draw, tbl, origin_hwp)
        record = self.tables.get(key)
        if record is not None and "origin" not in record:
            record["origin"] = tuple(origin_hwp)
            record["page"] = self._page
        return result


def _cell_paragraphs(tc):
    return own_render.own_paragraphs(tc)


def _cell_linesegs(tc):
    """Every cached ``hp:lineseg`` of the cell's own paragraphs."""
    out = []
    for para in _cell_paragraphs(tc):
        array = own_render._kid(para, "linesegarray")
        if array is None:
            continue
        for seg in own_render._kids(array, "lineseg"):
            out.append((own_render._iattr(seg, "vertpos"),
                        own_render._iattr(seg, "vertsize"),
                        own_render._iattr(seg, "spacing")))
    return out


def _cached_spacing_extent(tc):
    """The cell's cached content height WITH the last line's ``spacing``.

    ``Paragraph.extent_hwp`` deliberately drops the trailing spacing; this is
    the other reading of the same cache, offered to the fit as a candidate.
    ``None`` where the cell caches no line at all.
    """
    segs = _cell_linesegs(tc)
    if not segs:
        return None
    return max(pos + size + space for pos, size, space in segs)


def _first_vertpos(tc):
    """The ``vertpos`` of the cell's first cached line, or ``None``."""
    segs = _cell_linesegs(tc)
    return segs[0][0] if segs else None


# --------------------------------------------------------------------------
# The candidates
# --------------------------------------------------------------------------

def cell_height(cell, candidate):
    """What one cell asks its row (or rows) to be, under one candidate."""
    declared = cell["declared"]
    inset = cell["inset"]
    content = cell["content"]
    if candidate == "declared":
        return declared
    if candidate == "content":
        return content + inset
    if candidate == "max_spacing":
        spacing = cell["content_spacing"]
        body = content if spacing is None else spacing
        return max(declared, body + inset)
    if candidate == "max_marginnext":
        return max(declared, content + inset + cell["margin_next"])
    if candidate == "max_noinset":
        return max(declared, content)
    return max(declared, content + inset)


def row_constraints(cells, candidate):
    """``[(start row, span, height)]`` for the row solve, per candidate."""
    out = []
    for cell in cells:
        value = cell_height(cell, candidate)
        span = cell["rspan"]
        if span > 1:
            if candidate == "max_span_ignore":
                continue
            if candidate == "max_span_last":
                out.append((cell["row"] + span - 1, 1, value))
                continue
            if candidate == "max_span_equal":
                share = value // span
                for offset in range(span):
                    last = offset == span - 1
                    out.append((cell["row"] + offset, 1,
                                value - share * (span - 1) if last else share))
                continue
        out.append((cell["row"], span, value))
    return out


def solve_rows(record, candidate, compress):
    """One candidate's row heights for one table."""
    tbl = record["tbl"]
    rows = own_render._iattr(tbl, "rowCnt", 0)
    if record["cells"]:
        rows = max(rows, max(c["row"] + c["rspan"] for c in record["cells"]))
    size = own_render._kid(tbl, "sz")
    declared_total = (own_render._iattr(size, "height")
                      if size is not None else None)
    cons = row_constraints(record["cells"], candidate)
    return own_render.solve_tracks(rows, cons,
                                   declared_total if compress else None)


def declared_row_heights(record):
    """``{row: height}`` where every unspanned cell of the row agrees.

    A row whose unspanned cells declare two different heights is left out and
    counted as ``rows_ambiguous``: the file does not say what that row is.
    """
    seen = defaultdict(set)
    for cell in record["cells"]:
        if cell["rspan"] == 1:
            seen[cell["row"]].add(cell["declared"])
    return {row: next(iter(hs)) for row, hs in seen.items() if len(hs) == 1}, \
        sum(1 for hs in seen.values() if len(hs) > 1)


# --------------------------------------------------------------------------
# The total-height oracle
# --------------------------------------------------------------------------

def table_total_oracle(renderer):
    """Hancom's own total height per table, read off the holder's lineseg.

    Only a paragraph whose entire content is the one table can be read this
    way -- anything else on the line makes the lineseg taller than the table.
    A table the cache paginated is excluded too: its holder's ``vertsize``
    describes only the part on that page, which shows up as a large negative
    residual and is reported as ``paginated`` rather than as a miss.
    """
    tbl_index, _paras = renderer._indexes()
    out = {}
    for root in renderer.sections:
        for para in root.iter():
            if own_render._local(para.tag) != "p":
                continue
            runs = own_render._kids(para, "run")
            tables, others, text = [], 0, 0
            for run in runs:
                for kid in run:
                    name = own_render._local(kid.tag)
                    if name == "tbl":
                        tables.append(kid)
                    elif name == "t":
                        text += len("".join(kid.itertext()))
                    elif name in ("pic", "equation", "ole", "chart",
                                  "container", "rect", "ellipse", "line",
                                  "arc", "polygon", "curve", "connectLine",
                                  "textart", "video"):
                        others += 1
            if len(tables) != 1 or others or text:
                continue
            array = own_render._kid(para, "linesegarray")
            segs = own_render._kids(array, "lineseg") if array is not None \
                else []
            if len(segs) != 1:
                continue
            tbl = tables[0]
            key = tbl_index.get(id(tbl))
            size = own_render._kid(tbl, "sz")
            out_margin = own_render._kid(tbl, "outMargin")
            declared = own_render._iattr(size, "height")
            vertical = (own_render._iattr(out_margin, "top")
                        + own_render._iattr(out_margin, "bottom"))
            cached = own_render._iattr(segs[0], "vertsize") - vertical
            out[key] = {"cached_total": cached, "declared_total": declared,
                        "residual": cached - declared}
    return out


# --------------------------------------------------------------------------
# The PDF oracle
# --------------------------------------------------------------------------

def pdf_rule_oracle(renderer, report, pdf_path):
    """Score each candidate's row boundaries against the PDF's horizontal rules.

    A DASHED rule exports as a run of short segments all on one y, so the
    strokes are merged by y into one rule spanning the union of their x --
    the same merge the 2026-09-04 row-height measurement had to make, and
    without it a five-row form reports 158 rules.
    """
    import lineseg_vs_pdf
    fitz = lineseg_vs_pdf._require_fitz()

    merged = defaultdict(dict)
    with fitz.open(str(pdf_path)) as document:
        pages = document.page_count
        for index, page in enumerate(document):
            for drawing in page.get_drawings():
                for item in drawing["items"]:
                    pieces = []
                    if item[0] == "l":
                        p0, p1 = item[1], item[2]
                        if abs(p0.y - p1.y) <= 0.5 and abs(p0.x - p1.x) > 0.5:
                            pieces.append((p0.y, min(p0.x, p1.x),
                                           max(p0.x, p1.x)))
                    elif item[0] == "re":
                        rect = item[1]
                        pieces.append((rect.y0, rect.x0, rect.x1))
                        pieces.append((rect.y1, rect.x0, rect.x1))
                    for y, x0, x1 in pieces:
                        key = round(y * 100.0)
                        low, high = merged[index + 1].get(
                            key, (round(x0 * 100.0), round(x1 * 100.0)))
                        merged[index + 1][key] = (
                            min(low, round(x0 * 100.0)),
                            max(high, round(x1 * 100.0)))
    per_page = {page: {(y, span[0], span[1]) for y, span in rules.items()}
                for page, rules in merged.items()}

    wanted = {name: defaultdict(set) for name in CANDIDATES}
    spans = defaultdict(list)
    for table in report["tables"]:
        page = table.get("page")
        origin = table.get("origin")
        if page is None or origin is None:
            continue
        x0 = origin[0]
        x1 = origin[0] + table["width"]
        spans[page].append((x0, x1))
        for name in CANDIDATES:
            y = origin[1]
            wanted[name][page].add(round(y))
            for height in table["heights"][name]:
                y += height
                wanted[name][page].add(round(y))

    def _inside(page, rule):
        _y, rx0, rx1 = rule
        mid = (rx0 + rx1) / 2.0
        return any(x0 - 100 <= mid <= x1 + 100 for x0, x1 in spans.get(page, ()))

    out = {"pdf_pages": pages,
           "pdf_horizontal_rules": sum(len(v) for v in per_page.values()),
           "pdf_rules_in_a_table": sum(
               1 for page, rules in per_page.items()
               for rule in rules if _inside(page, rule))}
    for name in CANDIDATES:
        scores = {}
        for tol in RULE_TOL:
            hit = total = 0
            for page, rules in per_page.items():
                boundaries = sorted(wanted[name].get(page, ()))
                for rule in rules:
                    if not _inside(page, rule):
                        continue
                    total += 1
                    if any(abs(rule[0] - value) <= tol for value in boundaries):
                        hit += 1
            scores[str(tol)] = {
                "hit": hit, "of": total,
                "predicted": sum(len(v) for v in wanted[name].values())}
        out[name] = scores
    return out


# --------------------------------------------------------------------------
# One form
# --------------------------------------------------------------------------

def probe_form(hwpx_path, dpi=own_render.DEFAULT_DPI, policy="cache",
               repo_root=None, pdf_path=None):
    renderer = RowHeightRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                                 layout_policy=policy)
    renderer.render()
    totals = table_total_oracle(renderer)

    tables = []
    for key in sorted(renderer.tables):
        record = renderer.tables[key]
        tbl = record["tbl"]
        size = own_render._kid(tbl, "sz")
        declared_total = own_render._iattr(size, "height")
        declared_rows, ambiguous = declared_row_heights(record)
        entry = {
            "table": key,
            "page": record.get("page"),
            "origin": list(record["origin"]) if record.get("origin") else None,
            "width": record["xs"][-1] if record["xs"] else 0,
            "rows": own_render._iattr(tbl, "rowCnt", 0),
            "cells": len(record["cells"]),
            "rowspan_cells": sum(1 for c in record["cells"] if c["rspan"] > 1),
            "declared_total": declared_total,
            "declared_rows": declared_rows,
            "rows_ambiguous": ambiguous,
            "natural_rows": record["natural_rows"],
            "cache_total": totals.get(key),
            "heights": {}, "heights_compressed": {},
        }
        for name in CANDIDATES:
            entry["heights"][name] = solve_rows(record, name, compress=False)
            entry["heights_compressed"][name] = solve_rows(record, name,
                                                           compress=True)
        tables.append(entry)

    # -- the cache's own answer on whether it holds a row oracle ----------
    first = [c["first_vertpos"] for record in renderer.tables.values()
             for c in record["cells"] if c["first_vertpos"] is not None]
    vertpos_oracle = {
        "cells_with_a_cached_line": len(first),
        "first_vertpos_zero": sum(1 for v in first if v == 0),
        "max_first_vertpos": max(first) if first else 0,
    }

    scored = score(tables)
    report = {
        "tables": tables,
        "vertpos_oracle": vertpos_oracle,
        "total_oracle": total_oracle_summary(tables),
        "scores": scored,
    }
    if pdf_path is not None:
        report["pdf"] = pdf_rule_oracle(renderer, report, pdf_path)
    return report


def total_oracle_summary(tables):
    """Does the cache agree that a table is as tall as it declares?"""
    read = [t for t in tables if t["cache_total"] is not None]
    exact = sum(1 for t in read if t["cache_total"]["residual"] == 0)
    paginated = sum(1 for t in read if t["cache_total"]["residual"] < -1000)
    return {"tables": len(tables), "readable": len(read), "exact": exact,
            "paginated": paginated,
            "residuals": dict(Counter(t["cache_total"]["residual"]
                                      for t in read))}


def score(tables):
    """Per candidate: rows on the declared height, tables whose rows sum right."""
    out = {}
    for name in CANDIDATES:
        rows_exact = rows_near = rows_of = 0
        totals_exact = 0
        totals_of = 0
        residuals = Counter()
        row_residuals = Counter()
        for table in tables:
            heights = table["heights"][name]
            for row, declared in sorted(table["declared_rows"].items()):
                if row >= len(heights):
                    continue
                rows_of += 1
                delta = heights[row] - declared
                row_residuals[delta] += 1
                if delta == 0:
                    rows_exact += 1
                if abs(delta) <= NEAR_HWP:
                    rows_near += 1
            if table["natural_rows"]:
                continue
            totals_of += 1
            delta = sum(heights) - table["declared_total"]
            residuals[delta] += 1
            if delta == 0:
                totals_exact += 1
        out[name] = {
            "rows_exact": rows_exact, "rows_near": rows_near,
            "rows_of": rows_of,
            "totals_exact": totals_exact, "totals_of": totals_of,
            "total_residuals": dict(sorted(residuals.items())),
            "row_residuals": dict(sorted(row_residuals.items())),
        }
    return out


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def summary_line(stem, report):
    oracle = report["total_oracle"]
    vp = report["vertpos_oracle"]
    return (f"{stem}: {oracle['tables']} tables, {oracle['readable']} whose "
            f"total the cache states, {oracle['exact']} of those exactly "
            f"equal to the declared hp:sz@height "
            f"({oracle['paginated']} paginated); "
            f"{vp['first_vertpos_zero']}/{vp['cells_with_a_cached_line']} "
            f"cells start their first cached line at vertpos 0 "
            f"(max {vp['max_first_vertpos']})")


def score_table(report):
    out = [f"  {'candidate':<16}{'rows exact':>12}{'within 4':>10}"
           f"{'of':>6}{'tables exact':>14}{'of':>5}"]
    for name in CANDIDATES:
        row = report["scores"][name]
        out.append(f"  {name:<16}{row['rows_exact']:>12}{row['rows_near']:>10}"
                   f"{row['rows_of']:>6}{row['totals_exact']:>14}"
                   f"{row['totals_of']:>5}")
    return "\n".join(out)


def worst_tables(stem, report, name="max", limit=6):
    bad = [t for t in report["tables"]
           if not t["natural_rows"]
           and sum(t["heights"][name]) != t["declared_total"]]
    if not bad:
        return ""
    out = [f"  tables whose rows do not sum to hp:sz@height under {name}:"]
    for table in bad[:limit]:
        delta = sum(table["heights"][name]) - table["declared_total"]
        out.append(f"    {stem} table {table['table']}: "
                   f"{table['rows']} rows, declared {table['declared_total']}, "
                   f"solved {sum(table['heights'][name])} ({delta:+})")
    return "\n".join(out)


def pdf_table(report):
    pdf = report.get("pdf")
    if not pdf:
        return ""
    out = [f"  PDF: {pdf['pdf_horizontal_rules']} horizontal strokes, "
           f"{pdf['pdf_rules_in_a_table']} inside a table's x-span"]
    for name in CANDIDATES:
        cells = "  ".join(
            f"{tol}: {pdf[name][str(tol)]['hit']}/{pdf[name][str(tol)]['of']}"
            for tol in RULE_TOL)
        out.append(f"    {name:<16}{cells}   "
                   f"predicted {pdf[name][str(RULE_TOL[0])]['predicted']}")
    return "\n".join(out)


def corpus_scores(rows):
    """The candidate table summed over every form."""
    out = [f"  {'candidate':<16}{'rows exact':>12}{'within 4':>10}{'of':>6}"
           f"{'tables exact':>14}{'of':>5}"]
    for name in CANDIDATES:
        agg = Counter()
        for _stem, report in rows:
            entry = report["scores"][name]
            for key in ("rows_exact", "rows_near", "rows_of",
                        "totals_exact", "totals_of"):
                agg[key] += entry[key]
        out.append(f"  {name:<16}{agg['rows_exact']:>12}{agg['rows_near']:>10}"
                   f"{agg['rows_of']:>6}{agg['totals_exact']:>14}"
                   f"{agg['totals_of']:>5}")
    return "\n".join(out)


def corpus_residuals(rows, name="max"):
    agg = Counter()
    for _stem, report in rows:
        for value, count in report["scores"][name]["total_residuals"].items():
            agg[int(value)] += count
    return f"  total residuals under {name}: {dict(sorted(agg.items()))}"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="row_height_probe.py",
        description="Measure what makes a table row as tall as it is, and "
                    "score candidate rules against the table total the cache "
                    "states. Measures; changes nothing.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every corpus form and print a table")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--layout-policy", default="cache",
                        help="the policy to render under (default cache -- "
                             "the one whose content heights are the cache's "
                             "own)")
    parser.add_argument("--pdf", action="store_true",
                        help="also score every candidate's row boundaries "
                             "against the reference PDF's horizontal rules")
    parser.add_argument("--json", help="write the full per-table report")
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
        for hwpx, pdf in forms:
            report = probe_form(hwpx, dpi=args.dpi, policy=args.layout_policy,
                                repo_root=repo_root,
                                pdf_path=pdf if (args.pdf and pdf) else None)
            stem = labels[hwpx.stem]
            rows.append((stem, report))
            if not quiet:
                print(summary_line(stem, report))
                print(score_table(report))
                worst = worst_tables(stem, report)
                if worst:
                    print(worst)
                block = pdf_table(report)
                if block:
                    print(block)
        if not quiet:
            print()
            print("corpus:")
            print(corpus_scores(rows))
            print(corpus_residuals(rows))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    hwpx = Path(args.input)
    pdf = repo_root / "tests" / "corpus" / "forms" / "render" / (hwpx.stem + ".pdf")
    report = probe_form(hwpx, dpi=args.dpi, policy=args.layout_policy,
                        repo_root=repo_root,
                        pdf_path=pdf if (args.pdf and pdf.is_file()) else None)
    if not quiet:
        print(RULE_QUESTION)
        print(summary_line(hwpx.stem, report))
        print(score_table(report))
        worst = worst_tables(hwpx.stem, report)
        if worst:
            print(worst)
        block = pdf_table(report)
        if block:
            print(block)
    if args.json:
        Path(args.json).write_text(
            json.dumps({hwpx.stem: report}, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
