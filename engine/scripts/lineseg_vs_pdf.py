#!/usr/bin/env python3
"""Does Hancom's exported PDF reproduce the layout Hancom saved into the file?

The renderer line compares three layouts of the same document:

  * **path A** — the cached ``hp:lineseg`` seats, which are Hancom's own
    layout pass written into the file at save time;
  * **path B** — our flow pass (``--layout-policy computed``);
  * **the reference** — Hancom's exported PDF.

Path A is treated throughout the scoreboard as if it were the reference in
another coordinate system: the same engine laid both out, so they ought to
agree.  This script asks whether they do, and it asks it of the public corpus
rather than of one document.  Per top-level paragraph it reports

  * how many lines the cache seats against how many text lines the PDF draws;
  * where each side put the line breaks — the character split, read from
    ``hp:lineseg@textpos`` on one side and from the PDF's own line grouping on
    the other — and the first line at which the two diverge;
  * ``vertpos`` against the PDF line's glyph-box top, both relative to the
    body top, in HWPUNIT (1 pt = 100 HWPUNIT);
  * which page each side put the line on.

Usage::

    python engine/scripts/lineseg_vs_pdf.py FORM.hwpx REFERENCE.pdf
    python engine/scripts/lineseg_vs_pdf.py --corpus
    python engine/scripts/lineseg_vs_pdf.py A.hwpx A.pdf --json out.json --no-text

THE MATCHING RULE
-----------------
The two sides have no shared identifier: a PDF text line knows nothing about
the paragraph it came from.  So paragraphs are located in the PDF by their
text, under one rule, applied the same way to every document:

1. **Normalise** both sides by deleting every Unicode whitespace character
   (space, tab, newline, U+00A0, U+3000, …) and every soft hyphen (U+00AD).
   Whitespace is exactly what the two sides are entitled to disagree about —
   a line break eats a space on one side and not on the other — so it cannot
   be part of the key.  Nothing else is folded: case, width and punctuation
   are all significant.
2. **Concatenate** the PDF's text lines, in page order and then in the order
   ``page.get_text("dict")`` returns them, into one string, remembering where
   each line starts and ends.  Lines that normalise to nothing are dropped.
3. A paragraph matches the **contiguous run of PDF lines whose concatenation
   equals the paragraph's own normalised text**, found by searching that
   string forward from a cursor that only ever advances.  The match must
   begin exactly at a line start and end exactly at a line end, which is what
   makes it a run of whole lines rather than a substring.
4. **Hyphenation relaxation.** If no run matches, the search is repeated
   against a second concatenation built by dropping a trailing hyphen
   (U+002D or U+2010) from every line.  Korean forms do not hyphenate, so
   this never fires on this corpus; it is here so that the rule is not
   silently wrong on a document that does.
5. If a paragraph matches nowhere at or after the cursor, the whole string is
   searched from the start and the paragraph is flagged ``out_of_order``
   rather than dropped.  PDF text order is draw order, and a document with
   floating frames need not draw its body in document order.

A paragraph whose match is unique-by-construction (the run must equal the
whole paragraph) can still be found in the wrong place if two paragraphs
carry identical text; the forward cursor is what keeps those in document
order, and it is the only ordering assumption the rule makes.

6. **A PyMuPDF line is not a laid-out line.** Hancom draws widely tracked
   text — 배분/나눔 alignment, letter-spaced headings, a run of tab-separated
   cells — as several text-showing operations with large gaps between them,
   and MuPDF's grouper cuts those into separate ``line`` records at the same
   height.  Left alone that reads as "the PDF broke one cached line into
   four", which is an artefact of the reader and not of Hancom.  So once a
   paragraph's run is fixed, the pieces INSIDE that run are regrouped into
   visual lines: consecutive pieces on the same page whose vertical extents
   overlap by at least half the shorter one are one line.  The regrouping is
   applied only inside a run already known to be one paragraph, so it cannot
   weld two columns together; the piece count before regrouping is kept as
   ``pdf_pieces``, and the concatenation order is MuPDF's own, which the
   match already proved is the reading order.

WHAT IS EXCLUDED, AND WHY
-------------------------
Only top-level ``hp:p`` of each section is read, so **table cells never
enter**: a cell's paragraphs hang under ``hp:tbl`` inside a run.  On top of
that, a top-level paragraph is skipped, and counted with its reason, when it

  * carries no ``hp:lineseg`` at all (``no_lineseg``) — there is no path A to
    compare, which is the whole state of a Rigorloom-authored document;
  * carries no character that draws ink (``inkless``);
  * anchors or embeds a table (``table``) — its cached lineseg records the
    table's extent, not a line of text, and the cell text the PDF draws
    belongs to no top-level line;
  * carries any other object in its character stream (``object``) — a
    picture, an equation or a note occupies one ``textpos`` cell and puts a
    different number of characters (usually none) into the PDF, so the two
    splits are not comparable character for character;
  * matches no run of PDF lines (``no_pdf_match``).

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import unicodedata
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import own_render  # noqa: E402
import page_fit_probe  # noqa: E402
from own_render import _iattr, _kids  # noqa: E402


HWPUNIT_PER_PT = own_render.HWPUNIT_PER_PT

# The characters the key deletes.  Whitespace is what a line break is allowed
# to eat; the soft hyphen is a break opportunity that only sometimes prints.
_SOFT_HYPHEN = "­"
_TRAILING_HYPHENS = ("-", "‐")


def normalise(text):
    """The matching key: every whitespace and soft hyphen deleted."""
    out = []
    for ch in text:
        if ch == _SOFT_HYPHEN:
            continue
        if ch.isspace() or unicodedata.category(ch) in ("Zs", "Zl", "Zp"):
            continue
        out.append(ch)
    return "".join(out)


def drop_trailing_hyphen(text):
    """One trailing hyphen removed — the hyphenation half of the rule."""
    if text and text[-1] in _TRAILING_HYPHENS:
        return text[:-1]
    return text


class PdfLines:
    """The reference PDF's text lines, plus the two search strings.

    ``plain`` is the concatenation of the normalised lines; ``dehyphenated``
    is the same with a trailing hyphen dropped from each.  ``starts`` and
    ``ends`` index into whichever string a search used, so both are kept.
    """

    def __init__(self, lines, page_count=None, path=None):
        self.path = path
        self.lines = list(lines)
        self.page_count = (page_count if page_count is not None
                           else 1 + max([line["page"] for line in self.lines]
                                        + [-1]))
        self.plain = _Stream([line["key"] for line in self.lines])
        self.dehyphenated = _Stream(
            [drop_trailing_hyphen(line["key"]) for line in self.lines])

    @classmethod
    def read(cls, pdf_path):
        """Every inked text line of a PDF, in page then draw order."""
        fitz = _require_fitz()
        lines = []
        with fitz.open(pdf_path) as document:
            page_count = document.page_count
            for number, page in enumerate(document):
                for block in page.get_text("dict")["blocks"]:
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        raw = "".join(span.get("text", "")
                                      for span in line.get("spans", []))
                        key = normalise(raw)
                        if not key:
                            continue
                        x0, y0, x1, y1 = line["bbox"]
                        lines.append({
                            "page": number,
                            "text": raw,
                            "key": key,
                            "chars": len(key),
                            "top_hwp": y0 * HWPUNIT_PER_PT,
                            "bottom_hwp": y1 * HWPUNIT_PER_PT,
                            "x0_hwp": x0 * HWPUNIT_PER_PT,
                            "x1_hwp": x1 * HWPUNIT_PER_PT,
                        })
        return cls(lines, page_count=page_count, path=str(pdf_path))

    def find_run(self, target, cursor):
        """``(lo, hi, relaxed, out_of_order)`` or ``None``.

        The run is the contiguous ``self.lines[lo:hi]`` whose normalised
        concatenation equals ``target``.  ``cursor`` is the first line index
        the search may start at; a match found only before it is returned
        with ``out_of_order`` set.
        """
        for relaxed, stream in enumerate((self.plain, self.dehyphenated)):
            hit = stream.search(target, cursor)
            if hit is not None:
                return hit[0], hit[1], bool(relaxed), False
            hit = stream.search(target, 0)
            if hit is not None:
                return hit[0], hit[1], bool(relaxed), True
        return None


class _Stream:
    """One concatenation of per-line keys, searchable by whole-line runs."""

    def __init__(self, keys):
        starts = []
        ends = []
        offset = 0
        for key in keys:
            starts.append(offset)
            offset += len(key)
            ends.append(offset)
        self.text = "".join(keys)
        self.starts = starts
        # A key can normalise to nothing under the hyphen relaxation, so two
        # lines can share an offset: a run starts at the FIRST line seated
        # there and ends at the LAST one ending there.
        self.at_start = {}
        self.at_end = {}
        for index, offset in enumerate(starts):
            self.at_start.setdefault(offset, index)
        for index, offset in enumerate(ends):
            self.at_end[offset] = index

    def search(self, target, from_line):
        """First ``[lo, hi)`` line run at or after ``from_line``."""
        if not target or from_line >= len(self.starts):
            return None
        at = self.text.find(target, self.starts[from_line])
        while at != -1:
            lo = self.at_start.get(at)
            hi = self.at_end.get(at + len(target))
            if lo is not None and hi is not None and hi >= lo:
                return lo, hi + 1
            at = self.text.find(target, at + 1)
        return None


def _require_fitz():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "lineseg_vs_pdf needs PyMuPDF (fitz), the same reader "
            "render_scoreboard.py uses") from exc
    return fitz


def _same_visual_line(left, right, overlap=0.5):
    """Whether two PDF pieces sit at the same height on the same page."""
    if left["page"] != right["page"]:
        return False
    lo = max(left["top_hwp"], right["top_hwp"])
    hi = min(left["bottom_hwp"], right["bottom_hwp"])
    shorter = min(left["bottom_hwp"] - left["top_hwp"],
                  right["bottom_hwp"] - right["top_hwp"])
    if shorter <= 0:
        return False
    return (hi - lo) >= overlap * shorter


def merge_visual_lines(pieces):
    """Regroup a matched run's PyMuPDF pieces into laid-out lines.

    See rule 6 in the module docstring: MuPDF cuts a widely tracked line into
    several ``line`` records, and inside a run already known to be one
    paragraph those records are the same line.
    """
    merged = []
    for piece in pieces:
        if merged and _same_visual_line(merged[-1]["_last"], piece):
            group = merged[-1]
            group["parts"].append(piece)
            group["_last"] = piece
            group["top_hwp"] = min(group["top_hwp"], piece["top_hwp"])
            group["bottom_hwp"] = max(group["bottom_hwp"], piece["bottom_hwp"])
            group["x0_hwp"] = min(group["x0_hwp"], piece["x0_hwp"])
            group["x1_hwp"] = max(group["x1_hwp"], piece["x1_hwp"])
            group["text"] += piece["text"]
            group["key"] += piece["key"]
            group["chars"] += piece["chars"]
            continue
        merged.append({
            "page": piece["page"],
            "text": piece["text"],
            "key": piece["key"],
            "chars": piece["chars"],
            "top_hwp": piece["top_hwp"],
            "bottom_hwp": piece["bottom_hwp"],
            "x0_hwp": piece["x0_hwp"],
            "x1_hwp": piece["x1_hwp"],
            "parts": [piece],
            "_last": piece,
        })
    for group in merged:
        # ``parts`` is kept, not popped: a caller that needs what went INTO a
        # visual line — ``advance_probe`` reads the per-character boxes off
        # the pieces — must not have to re-run the regrouping to get it.
        # Nothing in this module reads it, and no record written out of here
        # carries it.
        group["pieces"] = len(group["parts"])
        group.pop("_last")
    return merged


# What ``hp:lineseg@textpos`` counts.  It indexes the paragraph's TEXT
# STREAM, in which an inline control occupies cells even when it draws no
# glyph: one for a char-type control such as ``<hp:lineBreak/>``, eight for an
# inline or extended one such as ``<hp:tab/>`` or an ``<hp:fieldBegin>``.
# ``own_render.Paragraph`` builds that stream alongside ``chars`` and the map
# between the two (``cell_start``), so this module READS that map rather than
# keeping a second model of the same thing: the comparison below then tests
# the renderer's own reading of ``textpos`` and not a copy of it.
#
# Every cell no character sits in is filled with a space, which the matching
# key deletes -- exactly as it deletes the whitespace a line break eats.
_CONTROL_CELL = " "

# The inline elements whose cell width the renderer is not guessing at.  It
# gives anything it does not name one control's worth of cells, and an
# unnamed one is reported so the guess stays visible in the record.
_NAMED_CONTROLS = (own_render.TEXTPOS_CELLS_CHAR
                   | own_render.TEXTPOS_CELLS_MARK
                   | frozenset({
                       "tab", "tbl", "equation", "pic", "ole", "chart",
                       "container", "rect", "ellipse", "line", "arc",
                       "polygon", "curve", "connectLine", "textart", "video",
                       "secPr", "colPr", "fieldBegin", "fieldEnd", "footNote",
                       "endNote", "header", "footer", "autoNum", "newNum",
                       "pageNum", "pageHiding", "bookmark", "indexmark",
                       "hiddenComment"}))


def character_cells(para, unknown=None):
    """The paragraph's ``textpos`` stream: one entry per cell it counts."""
    unknown = {} if unknown is None else unknown
    cells = [_CONTROL_CELL] * para.cell_count
    for index, (ch, _cid) in enumerate(para.chars):
        cells[para.cell_start[index]] = ch
    for name in _inline_names(para.el):
        if name not in _NAMED_CONTROLS:
            unknown[name] = unknown.get(name, 0) + 1
    return cells


def _inline_names(el):
    """Every inline element name inside this paragraph's runs."""
    for run in own_render._kids(el, "run"):
        for child in run:
            name = own_render._local(child.tag)
            if name in ("t", "ctrl"):
                for sub in child.iter():
                    if sub is not child:
                        yield own_render._local(sub.tag)
            else:
                yield name


def paragraph_text(cells):
    """The cell stream as text, object slots removed."""
    return "".join(ch for ch in cells if ch != own_render.OBJECT_SLOT)


def cached_split(para, cells):
    """``[(lo, hi)]`` — the cell range each cached lineseg holds."""
    positions = [_iattr(seg, "textpos") for seg in para.linesegs]
    total = len(cells)
    spans = []
    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else total
        spans.append((start, max(start, end)))
    return spans


def skip_reason(para, cells):
    """Why this top-level paragraph cannot be compared, or ``None``."""
    if not para.linesegs:
        return "no_lineseg"
    if any(name == "tbl" for _i, name, _el, _cp in para.objects):
        return "table"
    if para.objects:
        return "object"
    if para.linesegs and _iattr(para.linesegs[-1], "textpos") > len(cells):
        # The cell model does not reproduce what this file's textpos counts,
        # so no split read off it would mean anything.
        return "textpos_overruns_stream"
    if not normalise(paragraph_text(cells)):
        return "inkless"
    return None


def _cached_page_map(renderer, section, page_offset):
    """``{paragraph order: {lineseg index: page}}`` for one section."""
    pages = page_fit_probe.cached_pages(renderer, section)
    mapping = {}
    for index, page in enumerate(pages):
        for para, lo, hi in page:
            order = getattr(para, "_probe_order", None)
            if order is None:
                continue
            seats = mapping.setdefault(order, {})
            for seg in range(lo, hi):
                seats[seg] = page_offset + index
    return mapping, len(pages)


def compare_document(hwpx_path, pdf_path, repo_root=None, keep_text=True):
    """Every comparable top-level paragraph of one document, both sides."""
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    pdf = PdfLines.read(pdf_path)
    cursor = 0
    paragraphs = []
    skipped = []
    page_offset = 0
    sections = []
    unknown = {}
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        geo = renderer.page_geometry()
        body_top = geo["body_top"]
        page_map, page_count = _cached_page_map(renderer, section, page_offset)
        sections.append({
            "section": section,
            "body_top": body_top,
            "usable_height": geo["usable_height"],
            "page_height": geo["height"],
            "cached_pages": page_count,
        })
        for order, el in enumerate(_kids(renderer.sections[section], "p")):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = character_cells(para, unknown)
            text = paragraph_text(cells)
            reason = skip_reason(para, cells)
            if reason is not None:
                record = {"section": section, "paragraph": order,
                          "reason": reason,
                          "cached_lines": len(para.linesegs)}
                if keep_text:
                    record["text"] = text
                skipped.append(record)
                continue
            record = _compare_paragraph(
                para, cells, order, section, body_top,
                page_map.get(order, {}), pdf, cursor, keep_text)
            if record.get("reason") == "no_pdf_match":
                skipped.append({"section": section, "paragraph": order,
                                "reason": "no_pdf_match",
                                "cached_lines": len(para.linesegs),
                                **({"text": text} if keep_text else {})})
                continue
            cursor = record.pop("_cursor")
            paragraphs.append(record)
        page_offset += page_count
    return {
        "document": str(hwpx_path),
        "reference": str(pdf_path),
        "pdf_pages": pdf.page_count,
        "pdf_text_lines": len(pdf.lines),
        "unknown_inline_controls": unknown,
        "sections": sections,
        "paragraphs": paragraphs,
        "skipped": skipped,
    }


def _compare_paragraph(para, cells, order, section, body_top, page_map, pdf,
                       cursor, keep_text):
    text = paragraph_text(cells)
    target = normalise(text)
    hit = pdf.find_run(target, cursor)
    if hit is None:
        return {"reason": "no_pdf_match"}
    lo, hi, relaxed, out_of_order = hit
    pieces = pdf.lines[lo:hi]
    pdf_run = merge_visual_lines(pieces)

    spans = cached_split(para, cells)
    cached = []
    running = 0
    for index, (start, end) in enumerate(spans):
        seg = para.linesegs[index]
        chunk = paragraph_text(cells[start:end])
        key = normalise(chunk)
        running += len(key)
        entry = {
            "textpos": _iattr(seg, "textpos"),
            "vertpos": _iattr(seg, "vertpos"),
            "vertsize": _iattr(seg, "vertsize"),
            "spacing": _iattr(seg, "spacing"),
            "horzsize": _iattr(seg, "horzsize"),
            "chars": len(key),
            "chars_raw": end - start,
            "cumulative": running,
            "page": page_map.get(index),
        }
        if keep_text:
            entry["text"] = chunk
        cached.append(entry)

    pdf_lines = []
    running = 0
    for line in pdf_run:
        running += line["chars"]
        entry = {
            "page": line["page"],
            "chars": line["chars"],
            "chars_raw": len(line["text"]),
            "pieces": line["pieces"],
            "cumulative": running,
            "top": int(round(line["top_hwp"] - body_top)),
            "bottom": int(round(line["bottom_hwp"] - body_top)),
            "width": int(round(line["x1_hwp"] - line["x0_hwp"])),
        }
        if keep_text:
            entry["text"] = line["text"]
        pdf_lines.append(entry)

    # The split agrees at line i when both sides have consumed exactly the
    # same characters before it AND after it, which is the same as the two
    # cumulative counts agreeing at i-1 and at i.
    paired = min(len(cached), len(pdf_lines))
    first_divergence = None
    agreeing = []
    previous_ok = True
    for index in range(paired):
        same = cached[index]["cumulative"] == pdf_lines[index]["cumulative"]
        if same and previous_ok:
            agreeing.append(index)
        if not same and first_divergence is None:
            first_divergence = index
        previous_ok = same
    if first_divergence is None and len(cached) != len(pdf_lines):
        first_divergence = paired

    deltas = []
    for index in range(paired):
        dy = cached[index]["vertpos"] - pdf_lines[index]["top"]
        cached[index]["dy"] = dy
        cached[index]["pdf_page"] = pdf_lines[index]["page"]
        deltas.append(dy)

    agree_chars = sum(cached[i]["chars"] for i in agreeing)
    record = {
        "section": section,
        "paragraph": order,
        "cached_lines": len(cached),
        "pdf_lines": len(pdf_lines),
        "pdf_pieces": len(pieces),
        "chars": len(target),
        "chars_in_agreeing_lines": agree_chars,
        "agreeing_lines": len(agreeing),
        "first_divergence": first_divergence,
        "split_equal": first_divergence is None,
        "count_equal": len(cached) == len(pdf_lines),
        "hyphen_relaxed": relaxed,
        "out_of_order": out_of_order,
        "cached_pages": sorted({c["page"] for c in cached
                                if c["page"] is not None}),
        "pdf_pages": sorted({p["page"] for p in pdf_lines}),
        "dy": _stats(deltas),
        "dy_agreeing": _stats([cached[i]["dy"] for i in agreeing]),
        "cached": cached,
        "pdf": pdf_lines,
        "_cursor": _cursor_after(cursor, hi, out_of_order),
    }
    if keep_text:
        record["text"] = text
    return record


def _cursor_after(cursor, hi, out_of_order):
    """The cursor only advances; an out-of-order match must not rewind it."""
    return max(cursor, hi) if out_of_order else hi


def _stats(values):
    if not values:
        return None
    absolute = [abs(v) for v in values]
    return {
        "n": len(values),
        "median": int(statistics.median(values)),
        "median_abs": int(statistics.median(absolute)),
        "min": min(values),
        "max": max(values),
    }


def summarise(report):
    """Per-document totals: counts, character share, dy."""
    equal = more = fewer = 0
    split_differs = 0
    chars = agree_chars = 0
    deltas = []
    spreads = []
    page_deltas = []
    page_differs = 0
    seats = []
    for para in report["paragraphs"]:
        if para["cached_lines"] == para["pdf_lines"]:
            equal += 1
            if not para["split_equal"]:
                split_differs += 1
        elif para["cached_lines"] > para["pdf_lines"]:
            more += 1
        else:
            fewer += 1
        chars += para["chars"]
        agree_chars += para["chars_in_agreeing_lines"]
        here = []
        for line in para["cached"]:
            if "dy" in line:
                deltas.append(line["dy"])
                here.append(line["dy"])
            if line.get("page") is not None and line.get("pdf_page") is not None:
                page_deltas.append(line["pdf_page"] - line["page"])
                seats.append((line["page"], line["pdf_page"]))
                if line["page"] != line["pdf_page"]:
                    page_differs += 1
        if len(here) > 1:
            spreads.append(max(here) - min(here))
    # dy carries a per-form constant — the cached box top sits above the
    # glyph box by whatever the line's leading is — so the residual around
    # the form's own median is what says whether the SEAT was reproduced.
    centre = statistics.median(deltas) if deltas else 0
    residual = [abs(v - centre) for v in deltas]
    # The absolute page index is only as good as the cache's page grouping,
    # which a multi-page table defeats.  Whether two consecutive lines share
    # a page is not: it is the PARTITION, and a constant index offset cannot
    # move it.
    grouping_breaks = sum(
        1 for a, b in zip(seats, seats[1:])
        if (a[0] == b[0]) != (a[1] == b[1]))
    reasons = {}
    for entry in report["skipped"]:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    compared = len(report["paragraphs"])
    return {
        "compared_paragraphs": compared,
        "equal_line_count": equal,
        "more_cached_lines": more,
        "fewer_cached_lines": fewer,
        "equal_count_split_differs": split_differs,
        "characters": chars,
        "characters_in_agreeing_lines": agree_chars,
        "character_share_agreeing": (round(agree_chars / chars, 6)
                                     if chars else None),
        "paired_lines": len(deltas),
        "dy": _stats(deltas),
        "dy_residual_abs_median": (int(statistics.median(residual))
                                   if residual else None),
        "dy_spread_within_paragraph_median": (int(statistics.median(spreads))
                                              if spreads else None),
        "page_delta": _stats(page_deltas),
        "lines_on_a_different_page": page_differs,
        "page_grouping_breaks": grouping_breaks,
        "page_grouping_pairs": max(0, len(seats) - 1),
        "skipped": reasons,
        "skipped_total": len(report["skipped"]),
    }


def corpus_targets(repo_root):
    """``[(hwpx, pdf)]`` — every converted corpus form with a reference."""
    converted = Path(repo_root) / "tests" / "corpus" / "forms" / "converted"
    renders = Path(repo_root) / "tests" / "corpus" / "forms" / "render"
    out = []
    for hwpx in sorted(converted.glob("*.hwpx")):
        pdf = renders / (hwpx.stem + ".pdf")
        if pdf.is_file():
            out.append((hwpx, pdf))
    return out


def _label(stem, heads):
    parts = stem.split("-")
    return parts[0] if heads[parts[0]] == 1 else f"{parts[0]}-{parts[-1]}"


def format_report(rows):
    """The per-form table."""
    from collections import Counter
    stems = [Path(r["document"]).stem for r, _ in rows]
    heads = Counter(stem.split("-")[0] for stem in stems)
    labels = [_label(stem, heads) for stem in stems]
    width = max([len(label) for label in labels] + [4])
    out = ["", "cached hp:lineseg against Hancom's exported PDF, "
                "per top-level paragraph",
           "(dy = cached vertpos - PDF glyph-box top, both relative to "
           "body_top, HWPUNIT)", ""]
    out.append(f"{'form':<{width}} {'cmp':>4} {'equal':>5} {'more':>5} "
               f"{'fewer':>5} {'split!':>6} {'char%':>7} {'dy_med':>7} "
               f"{'|dy|med':>7} {'dy_res':>6} {'spread':>6} {'pg!=':>5} "
               f"{'skip':>5}")
    out.append("-" * (width + 76))
    for (report, summary), label in zip(rows, labels):
        share = summary["character_share_agreeing"]
        dy = summary["dy"] or {}
        out.append(
            f"{label:<{width}} {summary['compared_paragraphs']:>4} "
            f"{summary['equal_line_count']:>5} "
            f"{summary['more_cached_lines']:>5} "
            f"{summary['fewer_cached_lines']:>5} "
            f"{summary['equal_count_split_differs']:>6} "
            f"{'-' if share is None else format(share * 100, '.1f'):>7} "
            f"{dy.get('median', '-'):>7} {dy.get('median_abs', '-'):>7} "
            f"{summary['dy_residual_abs_median'] if summary['dy_residual_abs_median'] is not None else '-':>6} "
            f"{summary['dy_spread_within_paragraph_median'] if summary['dy_spread_within_paragraph_median'] is not None else '-':>6} "
            f"{summary['lines_on_a_different_page']:>5} "
            f"{summary['skipped_total']:>5}")
    reasons = {}
    for _report, summary in rows:
        for reason, count in summary["skipped"].items():
            reasons[reason] = reasons.get(reason, 0) + count
    out.append("")
    out.append("skipped, by reason: "
               + (", ".join(f"{k} {v}" for k, v in sorted(reasons.items()))
                  or "none"))
    total_chars = sum(s["characters"] for _r, s in rows)
    total_agree = sum(s["characters_in_agreeing_lines"] for _r, s in rows)
    if total_chars:
        out.append(f"characters in agreeing lines, all forms: "
                   f"{total_agree}/{total_chars} "
                   f"({total_agree / total_chars * 100:.1f}%)")
    return "\n".join(out)


def format_pages(rows):
    """Cached page groups against the PDF's own page count."""
    out = ["", "pages: the cache's own grouping against the export",
           "(a whole table is ONE cached lineseg however many pages it "
           "takes, so a form with a multi-page table cannot be counted "
           "from the cache)", ""]
    for report, summary in rows:
        stem = Path(report["document"]).stem
        cached = sum(s["cached_pages"] for s in report["sections"])
        delta = summary["page_delta"] or {}
        out.append(f"  {stem}: cached {cached}, pdf {report['pdf_pages']}, "
                   f"lines on a different page "
                   f"{summary['lines_on_a_different_page']}"
                   f"/{summary['paired_lines']}"
                   + (f", page delta {delta['min']}..{delta['max']}"
                      if delta else "")
                   + f", grouping breaks {summary['page_grouping_breaks']}"
                     f"/{summary['page_grouping_pairs']}")
    return "\n".join(out)


def format_divergences(rows, limit=12):
    """The first paragraphs where the two passes disagree, per form."""
    out = ["", "first disagreements"]
    for report, _summary in rows:
        stem = Path(report["document"]).stem
        bad = [p for p in report["paragraphs"]
               if not p["count_equal"] or not p["split_equal"]]
        if not bad:
            out.append(f"  {stem}: none")
            continue
        out.append(f"  {stem}: {len(bad)} of "
                   f"{len(report['paragraphs'])} compared")
        for para in bad[:limit]:
            out.append(
                f"    s{para['section']} p{para['paragraph']:<4} "
                f"cached {para['cached_lines']} / pdf {para['pdf_lines']} "
                f"lines, first divergence at line {para['first_divergence']}, "
                f"cached split "
                f"{[c['chars'] for c in para['cached']]} vs pdf "
                f"{[p['chars'] for p in para['pdf']]}")
        if len(bad) > limit:
            out.append(f"    ... and {len(bad) - limit} more")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Compare cached hp:lineseg layout with Hancom's PDF")
    parser.add_argument("pair", nargs="*", type=Path,
                        metavar="HWPX PDF",
                        help="a document and its reference PDF")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form with a reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None,
                        help="write the full per-paragraph record here")
    parser.add_argument("--no-text", action="store_true",
                        help="omit paragraph and line text from the JSON")
    parser.add_argument("--divergences", type=int, default=12,
                        metavar="N",
                        help="how many disagreeing paragraphs to print per "
                             "form (default 12)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    targets = []
    if args.pair:
        if len(args.pair) % 2:
            build_parser().error("give documents and references in pairs")
        targets.extend(zip(args.pair[0::2], args.pair[1::2]))
    if args.corpus:
        targets.extend(corpus_targets(repo_root))
    if not targets:
        build_parser().error("give a document and a reference, or --corpus")
    rows = []
    for hwpx, pdf in targets:
        report = compare_document(hwpx, pdf, repo_root=repo_root,
                                  keep_text=not args.no_text)
        rows.append((report, summarise(report)))
    print(format_report(rows))
    print(format_pages(rows))
    print(format_divergences(rows, limit=args.divergences))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"documents": [
            {"summary": summary, **report} for report, summary in rows]}
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
