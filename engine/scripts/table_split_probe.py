#!/usr/bin/env python3
"""Where does Hancom split a table that does not fit the page, and do we?

#276 established that the CACHE says nothing about table pagination: every
one of the corpus' 81 table holders carries a single ``hp:lineseg``, an
inline table's lineseg spans the whole table however many pages it takes,
``hp:tbl@pageBreak`` is a static authoring setting and ``@repeatHeader`` is
``"1"`` on all 81.  So the only witness to what Hancom actually DID at a page
boundary is its own export, and #258 measured that the export reproduces the
saved layout.  This probe reads that witness.

WHAT IT MEASURES
----------------
Two independent readings of the same reference PDF, because neither alone is
safe:

``text``
    Every paragraph inside every table cell, normalised and kept only when
    its text is UNIQUE in the document (no other cell paragraph anywhere has
    it) and at least ``MIN_TEXT`` characters long.  Each such paragraph is
    located on the one reference page whose text contains it.  A table whose
    unique paragraphs land on more than one page is a table Hancom split,
    and the ROW index of each paragraph says where: the split row is the
    lowest row seen on the continuation page, and the row is DIVIDED (a cell
    cut across the boundary, which ``pageBreak="CELL"`` is what permits)
    when one row's paragraphs appear on both pages.  A repeated header
    would show as row 0's own paragraphs appearing on the continuation page
    as well as the first.

``rules``
    Every stroke the PDF draws, merged into horizontal (``y, x0, x1``) and
    vertical (``x, y0, y1``) rules and grouped into table REGIONS by their
    x-span, so the top and bottom edge of the table on each page can be read
    directly.  A table start draws its full outer border across the top of
    the region; a CONTINUATION does not — it draws only the interior rule
    the split cut through, which is narrower.  That is the geometric
    signature of a continuation, and it is reported beside the text answer
    rather than merged into it.

The scale from HWPUNIT to PDF points is taken per form from ``hp:pagePr``
against the PDF MediaBox (#276: kstartup's 59528 x 84188 exports to
595.0 x 841.0, a non-uniform 0.9995297 x 0.9989547), so every measurement
below is reported in HWPUNIT, comparable with the file's own numbers.

OUR SIDE
--------
``own_render`` is instrumented, once per policy (``cache`` and ``computed``),
to record every ``_render_table`` call for a top-level table: the page, the
origin the table was drawn at, the half-open row range that call drew, and
the row heights solved for it.  A table drawn more than once is a table this
render split.  Row ranges are in the row space ``_expand_segmented_rows``
produces, which can hold more rows than the file's own ``hp:tr`` count; the
report prints both.

Usage::

    python engine/scripts/table_split_probe.py FORM.hwpx [REFERENCE.pdf]
    python engine/scripts/table_split_probe.py --corpus
    python engine/scripts/table_split_probe.py --corpus --json out.json --no-text

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout_divergence  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

#: A cell paragraph shorter than this is not evidence -- "합계" appears on
#: every page of some forms.
MIN_TEXT = 8

#: Two strokes are the same rule when their coordinates agree this closely,
#: in PDF points.  A double border draws its two strokes 0.5-1.1 pt apart and
#: they must stay distinct, so this is deliberately tight.
RULE_TOL = 0.6

#: Two regions are the same table when their x-span agrees this closely, in
#: points.  A continuation drops the outer border stroke, which moves the
#: region's own x edge by about one border width.
SPAN_TOL = 2.5

QUESTION = (
    "for every corpus table that crosses a page in the reference PDF, where "
    "did Hancom split it and what did it draw, and does our pagination "
    "(cache and computed) reproduce the split, the repeated header and the "
    "continuation seat?")

WS = re.compile(r"\s+")
SECTION = re.compile(r"Contents/section\d+\.xml$")


def _norm(text):
    return WS.sub("", text or "")


# --------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------

def _sections(hwpx_path):
    with zipfile.ZipFile(hwpx_path) as archive:
        names = sorted(n for n in archive.namelist() if SECTION.match(n))
        return [ET.fromstring(archive.read(name)) for name in names]


def _page_geometry(roots):
    """``hp:pagePr`` reduced to the body box, in HWPUNIT."""
    page_pr = next((e for root in roots for e in root.iter()
                    if own_render._local(e.tag) == "pagePr"), None)
    if page_pr is None:
        raise ValueError("no hp:pagePr")
    margin = own_render._kid(page_pr, "margin")
    m = {k: own_render._iattr(margin, k) for k in
         ("left", "right", "top", "bottom", "header", "footer")}
    width = own_render._iattr(page_pr, "width")
    height = own_render._iattr(page_pr, "height")
    return {
        "width": width,
        "height": height,
        "body_left": m["left"],
        "body_top": m["top"] + m["header"],
        "usable_width": width - m["left"] - m["right"],
        "usable_height": height - m["top"] - m["bottom"] - m["header"]
                         - m["footer"],
    }


def _tables(roots):
    """Every ``hp:tbl`` in document order, with its nesting depth."""
    out = []
    for root in roots:
        for el in root.iter():
            if own_render._local(el.tag) == "tbl":
                out.append(el)
    inner = set()
    for tbl in out:
        for el in tbl.iter():
            if el is not tbl and own_render._local(el.tag) == "tbl":
                inner.add(id(el))
    return out, inner


def _row_paragraphs(tbl):
    """``[(row index, paragraph text)]`` for the table's OWN cells.

    A paragraph belonging to a table nested inside one of this table's cells
    is charged to the nested table, not to this one: it says nothing about
    where THIS table's rows went.
    """
    out = []
    for tr_index, tr in enumerate(own_render._kids(tbl, "tr")):
        for tc in own_render._kids(tr, "tc"):
            addr = own_render._kid(tc, "cellAddr")
            row = (own_render._iattr(addr, "rowAddr")
                   if addr is not None else tr_index)
            for para in tc.iter():
                if own_render._local(para.tag) != "p":
                    continue
                if _paragraph_owner_is_nested(tc, para):
                    continue
                text = _norm("".join(
                    "".join(node.itertext()) for node in para.iter()
                    if own_render._local(node.tag) == "t"))
                if len(text) >= MIN_TEXT:
                    out.append((row, text))
    return out


def _paragraph_owner_is_nested(tc, para):
    """Is ``para`` inside a table nested in ``tc`` rather than in ``tc``?"""
    for node in tc.iter():
        if own_render._local(node.tag) != "tbl":
            continue
        if any(child is para for child in node.iter()):
            return True
    return False


def _table_attributes(tbl):
    pos = own_render._kid(tbl, "pos")
    size = own_render._kid(tbl, "sz")
    trs = own_render._kids(tbl, "tr")
    return {
        "page_break": tbl.get("pageBreak"),
        "repeat_header": tbl.get("repeatHeader"),
        "treat_as_char": (pos.get("treatAsChar") if pos is not None else None),
        "declared_height": (own_render._iattr(size, "height")
                            if size is not None else None),
        "declared_width": (own_render._iattr(size, "width")
                           if size is not None else None),
        "file_rows": len(trs),
        "rows_flagged_header": sum(1 for tr in trs
                                   if (tr.get("header") or "0") not in
                                   ("0", "false", "FALSE")),
    }


# --------------------------------------------------------------------------
# The reference PDF
# --------------------------------------------------------------------------

def _page_rules(page):
    """``([(y, x0, x1)], [(x, y0, y1)])`` for one page, strokes merged by
    coordinate.  A dashed rule exports as many short segments on one y, so
    the merge by coordinate is what keeps it one rule (the same merge
    ``row_height_probe.pdf_rule_oracle`` makes).
    """
    horizontal, vertical = {}, {}
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            pieces = []
            if item[0] == "l":
                p0, p1 = item[1], item[2]
                pieces.append((p0.x, p0.y, p1.x, p1.y))
            elif item[0] == "re":
                rect = item[1]
                pieces += [(rect.x0, rect.y0, rect.x1, rect.y0),
                           (rect.x0, rect.y1, rect.x1, rect.y1),
                           (rect.x0, rect.y0, rect.x0, rect.y1),
                           (rect.x1, rect.y0, rect.x1, rect.y1)]
            for x0, y0, x1, y1 in pieces:
                if abs(y0 - y1) <= RULE_TOL and abs(x0 - x1) > RULE_TOL:
                    key = round(y0, 1)
                    low, high = horizontal.get(key, (x0, x1))
                    horizontal[key] = (min(low, x0, x1), max(high, x0, x1))
                elif abs(x0 - x1) <= RULE_TOL and abs(y0 - y1) > RULE_TOL:
                    key = round(x0, 1)
                    low, high = vertical.get(key, (y0, y1))
                    vertical[key] = (min(low, y0, y1), max(high, y0, y1))
    return ([(y, span[0], span[1]) for y, span in sorted(horizontal.items())],
            [(x, span[0], span[1]) for x, span in sorted(vertical.items())])


def _page_regions(horizontal, vertical, min_width):
    """Table regions on one page, keyed by x-span.

    A region is every rule whose x-span is within ``SPAN_TOL`` of the same
    left and right edge -- which is what a table draws, whatever its interior
    looks like, and unlike a connected-component grouping it does not fall
    apart on a table whose middle rows declare ``borderFill`` NONE.
    """
    regions = []
    for y, x0, x1 in horizontal:
        if x1 - x0 < min_width:
            continue
        for region in regions:
            if (abs(region["x0"] - x0) <= SPAN_TOL
                    and abs(region["x1"] - x1) <= SPAN_TOL):
                region["x0"] = min(region["x0"], x0)
                region["x1"] = max(region["x1"], x1)
                region["rules"].append(y)
                break
        else:
            regions.append({"x0": x0, "x1": x1, "rules": [y]})
    for region in regions:
        region["rules"].sort()
        region["top"] = region["rules"][0]
        region["bottom"] = region["rules"][-1]
        region["verticals"] = [
            (x, y0, y1) for x, y0, y1 in vertical
            if region["x0"] - SPAN_TOL <= x <= region["x1"] + SPAN_TOL
            and y1 - y0 > 2.0]
    return sorted(regions, key=lambda r: r["top"])


def read_reference(pdf_path, geometry):
    """Per-page text and table regions, with the HWPUNIT scale."""
    fitz = lineseg_vs_pdf._require_fitz()
    with fitz.open(str(pdf_path)) as document:
        rect = document[0].rect
        scale_x = rect.width / (geometry["width"] / 100.0)
        scale_y = rect.height / (geometry["height"] / 100.0)
        pages = []
        for page in document:
            horizontal, vertical = _page_rules(page)
            pages.append({
                "text": _norm(page.get_text()),
                "horizontal": horizontal,
                "vertical": vertical,
            })
    return {"pages": pages, "scale_x": scale_x, "scale_y": scale_y,
            "page_count": len(pages)}


def _pt_to_hwp(value, scale):
    return int(round(value * 100.0 / scale))


# --------------------------------------------------------------------------
# What the PDF says each table did
# --------------------------------------------------------------------------

def pdf_splits(roots, reference, geometry):
    """Per top-level table: which reference pages carry which of its rows."""
    tables, inner = _tables(roots)
    entries = []
    for index, tbl in enumerate(tables):
        if id(tbl) in inner:
            continue
        for row, text in _row_paragraphs(tbl):
            entries.append((index, row, text))
    counts = Counter(text for _index, _row, text in entries)

    pagetext = [page["text"] for page in reference["pages"]]
    located = defaultdict(lambda: defaultdict(set))
    ambiguous = 0
    for index, row, text in entries:
        if counts[text] != 1:
            continue
        pages = [n + 1 for n, body in enumerate(pagetext) if text in body]
        if len(pages) != 1:
            ambiguous += 1
            continue
        located[index][pages[0]].add(row)

    out = []
    for index, tbl in enumerate(tables):
        if id(tbl) in inner:
            continue
        where = located.get(index, {})
        attrs = _table_attributes(tbl)
        record = {"table": index, "pages": sorted(where),
                  "rows_on_page": {str(p): sorted(rs)
                                   for p, rs in sorted(where.items())},
                  "unique_paragraphs": sum(len(rs) for rs in where.values()),
                  "split": len(where) > 1}
        record.update(attrs)
        if record["split"]:
            record.update(_describe_split(where, reference, geometry, attrs))
        out.append(record)
    return out


def _describe_split(where, reference, geometry, attrs):
    """What Hancom drew at a split, from the rows and from the rules."""
    pages = sorted(where)
    first, second = pages[0], pages[1]
    rows_first, rows_second = where[first], where[second]
    split_row = min(rows_second)
    divided = sorted(rows_first & rows_second)
    header_rows = sorted(r for r in rows_second if r in rows_first and r == 0)

    scale_y = reference["scale_y"]
    scale_x = reference["scale_x"]
    width_pt = (attrs["declared_width"] or 0) / 100.0 * scale_x
    body_top_pt = geometry["body_top"] / 100.0 * scale_y
    body_bottom_pt = ((geometry["body_top"] + geometry["usable_height"])
                      / 100.0 * scale_y)

    def region_for(page_number):
        page = reference["pages"][page_number - 1]
        regions = _page_regions(page["horizontal"], page["vertical"],
                                max(1.0, width_pt * 0.8))
        best = None
        for region in regions:
            span = region["x1"] - region["x0"]
            if best is None or abs(span - width_pt) < abs(best[0] - width_pt):
                best = (span, region)
        return best[1] if best else None

    first_region = region_for(first)
    second_region = region_for(second)
    out = {
        "split_row": split_row,
        "boundary_row_divided": bool(divided),
        "divided_rows": divided,
        "repeated_header": bool(header_rows),
        "repeated_header_rows": header_rows,
        "continuation_page": second,
    }
    if first_region is not None:
        out["first_top_hwp"] = _pt_to_hwp(first_region["top"], scale_y)
        out["first_bottom_hwp"] = _pt_to_hwp(first_region["bottom"], scale_y)
        out["first_height_hwp"] = _pt_to_hwp(
            first_region["bottom"] - first_region["top"], scale_y)
        out["first_bottom_below_body_top_hwp"] = _pt_to_hwp(
            first_region["bottom"] - body_top_pt, scale_y)
        out["room_left_under_first_hwp"] = _pt_to_hwp(
            body_bottom_pt - first_region["bottom"], scale_y)
        out["first_top_strokes"] = _stroke_widths(first_region, scale_x)
    if second_region is not None:
        out["continuation_top_hwp"] = _pt_to_hwp(second_region["top"], scale_y)
        out["continuation_top_below_body_top_hwp"] = _pt_to_hwp(
            second_region["top"] - body_top_pt, scale_y)
        out["continuation_height_hwp"] = _pt_to_hwp(
            second_region["bottom"] - second_region["top"], scale_y)
        out["continuation_top_strokes"] = _stroke_widths(second_region,
                                                         scale_x)
        # A repeated header would be the band between the continuation's own
        # top and its first interior rule.  Reported whether or not the text
        # says a header repeated, so the two readings can disagree in public.
        rules = second_region["rules"]
        out["continuation_first_band_hwp"] = (
            _pt_to_hwp(rules[1] - rules[0], scale_y) if len(rules) > 1
            else None)
        out["repeated_header_height_hwp"] = (
            out["continuation_first_band_hwp"] if header_rows else 0)
    return out


def _stroke_widths(region, scale_x):
    """The x-widths of the strokes on the region's own top edge, in HWPUNIT.

    A table START draws its full outer border there (two or three strokes at
    the outer width); a CONTINUATION draws only the interior rule the cut
    passed through, which is narrower and alone.
    """
    top = region["rules"][0]
    return sorted({_pt_to_hwp(region["x1"] - region["x0"], scale_x)
                   for y in region["rules"] if abs(y - top) <= 1.2})


# --------------------------------------------------------------------------
# What this renderer did
# --------------------------------------------------------------------------

class SplitRenderer(own_render.OwnRenderer):
    """``OwnRenderer`` that records every table fragment it draws."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fragments = []
        self._tbl_index = None

    def _table_index(self):
        if self._tbl_index is None:
            index = {}
            for root in self.sections:
                for el in root.iter():
                    if own_render._local(el.tag) == "tbl":
                        index[id(el)] = len(index)
            self._tbl_index = index
        return self._tbl_index

    def _render_table(self, draw, tbl, origin_hwp):
        key = self._table_index().get(id(tbl))
        rows = self._table_splits.get(id(tbl))
        natural = id(tbl) in self._table_natural_height
        self._quiet += 1
        try:
            _xs, ys, _cells = self._table_tracks(draw, tbl, natural)
        finally:
            self._quiet -= 1
        result = super()._render_table(draw, tbl, origin_hwp)
        low, high = rows if rows else (0, max(0, len(ys) - 1))
        high = min(high, max(0, len(ys) - 1))
        self.fragments.append({
            "table": key,
            "page": self._page,
            "origin_hwp": [int(origin_hwp[0]), int(origin_hwp[1])],
            "rows": [low, high],
            "height": (ys[high] - ys[low]) if len(ys) > high else 0,
            "solved_rows": [ys[i + 1] - ys[i] for i in range(len(ys) - 1)],
            "split": rows is not None,
            "natural_rows": natural,
        })
        return result


def our_splits(hwpx_path, policy, dpi, repo_root, inner, geometry):
    renderer = SplitRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                             layout_policy=policy)
    renderer.render()
    by_table = defaultdict(list)
    for fragment in renderer.fragments:
        by_table[fragment["table"]].append(fragment)
    tables = []
    for key in sorted(by_table):
        fragments = by_table[key]
        if fragments[0]["table"] is None:
            continue
        record = {
            "table": key,
            "pages": sorted({f["page"] for f in fragments}),
            "fragments": [{
                "page": f["page"],
                "rows": f["rows"],
                "height": f["height"],
                "top_below_body_top_hwp": (f["origin_hwp"][1]
                                           - geometry["body_top"]),
            } for f in fragments],
            "solved_rows": fragments[0]["solved_rows"],
            "split": len(fragments) > 1,
            "natural_rows": fragments[0]["natural_rows"],
        }
        if record["split"]:
            record["split_row"] = fragments[0]["rows"][1]
            record["boundary_row_divided"] = False
            record["repeated_header"] = False
            record["continuation_page"] = fragments[1]["page"]
            record["continuation_top_below_body_top_hwp"] = \
                fragments[1]["origin_hwp"][1] - geometry["body_top"]
            record["first_height_hwp"] = fragments[0]["height"]
            record["continuation_height_hwp"] = fragments[1]["height"]
        tables.append(record)
    return {"pages": renderer._page, "tables": tables,
            "top_level_split": sum(1 for t in tables
                                   if t["split"] and t["table"] not in inner)}


# --------------------------------------------------------------------------
# One form
# --------------------------------------------------------------------------

def probe_form(hwpx_path, pdf_path=None, dpi=own_render.DEFAULT_DPI,
               repo_root=None, policies=("cache", "computed")):
    roots = _sections(hwpx_path)
    geometry = _page_geometry(roots)
    tables, inner = _tables(roots)
    report = {
        "geometry": geometry,
        "tables": len(tables),
        "top_level_tables": sum(1 for t in tables if id(t) not in inner),
        "rows_flagged_header": sum(
            1 for t in tables for tr in own_render._kids(t, "tr")
            if (tr.get("header") or "0") not in ("0", "false", "FALSE")),
        "rows_total": sum(len(own_render._kids(t, "tr")) for t in tables),
        "tr_attributes": dict(Counter(
            own_render._local(k)
            for t in tables for tr in own_render._kids(t, "tr")
            for k in tr.attrib)),
    }
    if pdf_path is not None:
        reference = read_reference(pdf_path, geometry)
        report["pdf_pages"] = reference["page_count"]
        report["pdf"] = pdf_splits(roots, reference, geometry)
        report["pdf_split_tables"] = [t["table"] for t in report["pdf"]
                                      if t["split"]]
    inner_keys = {i for i, t in enumerate(tables) if id(t) in inner}
    report["ours"] = {}
    for policy in policies:
        report["ours"][policy] = our_splits(hwpx_path, policy, dpi, repo_root,
                                            inner_keys, geometry)
        report["ours"][policy]["split_tables"] = [
            t["table"] for t in report["ours"][policy]["tables"]
            if t["split"]]
    return report


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def summary_line(stem, report):
    pdf_pages = report.get("pdf_pages")
    ours = report["ours"]
    pages = "  ".join("%s %d" % (name, data["pages"])
                      for name, data in sorted(ours.items()))
    return ("%-34s tables %2d (top-level %2d)  pages: pdf %s  %s  "
            "hp:tr@header %d/%d"
            % (stem, report["tables"], report["top_level_tables"],
               pdf_pages if pdf_pages is not None else "-", pages,
               report["rows_flagged_header"], report["rows_total"]))


def split_block(report):
    """One line per table anyone split, PDF beside both policies."""
    pdf = {t["table"]: t for t in report.get("pdf", []) if t["split"]}
    lines = []
    interesting = set(pdf)
    for name, data in sorted(report["ours"].items()):
        interesting |= {t["table"] for t in data["tables"] if t["split"]}
    if not interesting:
        return ""
    lines.append("  split by anyone: %s" % sorted(interesting))
    for key in sorted(interesting):
        entry = pdf.get(key)
        if entry is not None:
            lines.append(
                "    tbl%-3d PDF      pages %s  split row %s  divided %s  "
                "header repeated %s  seat %+d  first %d  cont %d"
                % (key, entry["pages"], entry["split_row"],
                   entry["boundary_row_divided"], entry["repeated_header"],
                   entry.get("continuation_top_below_body_top_hwp", 0),
                   entry.get("first_height_hwp", 0),
                   entry.get("continuation_height_hwp", 0)))
            lines.append(
                "           rows/page %s  pageBreak=%s repeatHeader=%s "
                "treatAsChar=%s declared %s"
                % (entry["rows_on_page"], entry["page_break"],
                   entry["repeat_header"], entry["treat_as_char"],
                   entry["declared_height"]))
        else:
            attrs = next((t for t in report.get("pdf", [])
                          if t["table"] == key), None)
            lines.append("    tbl%-3d PDF      not split%s"
                         % (key, ("  pages %s" % attrs["pages"])
                            if attrs else ""))
        for name, data in sorted(report["ours"].items()):
            ours = next((t for t in data["tables"] if t["table"] == key), None)
            if ours is None:
                lines.append("           %-8s not drawn" % name)
            elif not ours["split"]:
                lines.append("           %-8s not split  pages %s"
                             % (name, ours["pages"]))
            else:
                lines.append(
                    "           %-8s pages %s  split row %s  divided %s  "
                    "header repeated %s  seat %+d  first %d  cont %d"
                    % (name, ours["pages"], ours["split_row"],
                       ours["boundary_row_divided"], ours["repeated_header"],
                       ours["continuation_top_below_body_top_hwp"],
                       ours["first_height_hwp"],
                       ours["continuation_height_hwp"]))
    return "\n".join(lines)


def corpus_table(rows):
    out = ["  %-30s %5s %5s %5s   %-16s %-16s" %
           ("form", "pdf", "cache", "comp", "split by Hancom",
            "split by us"),
           "  " + "-" * 84]
    for stem, report in rows:
        cache = report["ours"].get("cache", {})
        computed = report["ours"].get("computed", {})
        out.append("  %-30s %5s %5s %5s   %-16s %-16s" % (
            stem[:30],
            report.get("pdf_pages", "-"),
            cache.get("pages", "-"), computed.get("pages", "-"),
            str(report.get("pdf_split_tables", [])),
            "c=%s p=%s" % (cache.get("split_tables", []),
                           computed.get("split_tables", []))))
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description=QUESTION)
    parser.add_argument("input", nargs="?", help="a .hwpx form")
    parser.add_argument("reference", nargs="?",
                        help="its reference PDF (default: the corpus render)")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
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
            report = probe_form(hwpx, pdf, dpi=args.dpi, repo_root=repo_root)
            stem = labels[hwpx.stem]
            rows.append((stem, report))
            if not quiet:
                print(summary_line(stem, report))
                block = split_block(report)
                if block:
                    print(block)
        if not quiet:
            print()
            print("corpus:")
            print(corpus_table(rows))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    hwpx = Path(args.input)
    if args.reference:
        pdf = Path(args.reference)
    else:
        pdf = (repo_root / "tests" / "corpus" / "forms" / "render"
               / (hwpx.stem + ".pdf"))
    report = probe_form(hwpx, pdf if pdf.is_file() else None, dpi=args.dpi,
                        repo_root=repo_root)
    if not quiet:
        print(QUESTION)
        print(summary_line(hwpx.stem, report))
        block = split_block(report)
        if block:
            print(block)
    if args.json:
        Path(args.json).write_text(
            json.dumps({hwpx.stem: report}, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
