#!/usr/bin/env python3
"""How wide is a glyph?  Our advances against Hancom's own glyph positions.

#265 left the largest remaining class-B mechanism named but unsolved:
``text_rebreak:width``, 167 of 320 class-B paragraphs, descending from seven
text paragraphs whose computed line count differs from the cache.  Three of
the seven resolve every run to the declared, INSTALLED face and re-break
anyway, so font substitution is not the cause -- the advance widths this
renderer measures differ from Hancom's.  #258 measured that Hancom's exported
PDF reproduces the saved ``hp:lineseg`` exactly, which makes the reference PDF
a faithful oracle for where Hancom actually put each glyph.

This script reads that oracle.  For every text line the pairing of
``lineseg_vs_pdf`` already establishes, it takes the PDF's per-character
positions and asks, per character:

    Hancom's advance   = the next character's x origin minus this one's
                         (the last character of a line has no next one, so it
                         is reported from its bbox width and excluded from
                         every ratio below)
    our advance        = ``OwnRenderer._measure_hwp`` for the same character
                         under the same ``hh:charPr``, plus the ``hh:spacing``
                         gap that follows it -- which is exactly what
                         ``_char_advance_tables`` hands the line breaker

and groups the pair by ``(declared face -> resolved face, size pt, spacing %,
character class)``.  It then tests, explicitly, whether the residual is a
rounding grid: whether Hancom's own per-character advances land on whole
HWPUNIT, on 4 HWPUNIT (the grid #263 measured the PERCENT leading on), on a
1/64 pt grid, or on a device pixel at 96 / 144 / 600 dpi, and whether
quantising OUR advances onto any of those grids reproduces Hancom's per-line
widths better than not quantising them.

Finally it walks the seven carriers of #265 line by line: where the cache
broke, where our breaker breaks, and the cumulative width delta at that point.

Usage::

    python engine/scripts/advance_probe.py FORM.hwpx REFERENCE.pdf
    python engine/scripts/advance_probe.py --corpus
    python engine/scripts/advance_probe.py --corpus --json out.json --no-text
    python engine/scripts/advance_probe.py --corpus --punct

``--punct`` adds the #281 punctuation pass, restricted to advances whose own
face and whose successor's face are both the DECLARED, installed one: the
advance of every punctuation CODE POINT against Hancom's, in HWPUNIT and in
em; the inter-class boundary (Hangul→Latin and the rest) as Hancom's pen move
minus the same class's own same-class baseline, split by the paragraph's
``autoSpaceEAsianEng`` / ``autoSpaceEAsianNum``; and ``break_scoreboard``, the
two-sided score ``fit_scoreboard`` cannot be — the cached break positions
against ``compute_lines``' own, all-or-nothing per paragraph.

WHAT IS MEASURED, AND WHAT IS NOT
---------------------------------
* **Only interior characters carry a ratio.**  A line's last character has no
  successor to subtract from, and its ink bbox is its advance minus a side
  bearing this script does not model, so it is counted and reported apart.
* **Alignment is per line and exact or nothing.**  Our line's characters and
  the PDF line's characters are aligned with ``difflib``; a line whose two
  sides do not align character for character contributes its unmatched
  characters to a counter and nothing to any statistic.
* **The reference is a PDF, so its numbers are floats.**  Every comparison
  below carries a tolerance, and the grid tests report the tolerance they
  used.  A PDF text-showing operator positions a whole string, and MuPDF
  reconstructs per-character origins from the font's own widths for the
  characters inside one operator -- so "Hancom's advance" is Hancom's
  *declared* advance for that glyph, which is precisely the quantity the line
  breaker needs, but it is read through MuPDF's reconstruction and not off the
  page description.
* **Table cells are outside the pairing.**  ``lineseg_vs_pdf`` reads top-level
  paragraphs only.  Three of the seven carriers live in cells; for those the
  carrier pass falls back to matching the paragraph's text anywhere in the
  PDF, and says so per carrier.

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402
from own_render import _iattr, _kids, _local, script_slot  # noqa: E402


HWPUNIT_PER_PT = own_render.HWPUNIT_PER_PT

#: The seven paragraphs #265 found the class-B ``text_rebreak:width``
#: population descending from, by ``OwnRenderer.paragraph_index``.
CARRIERS = {
    "jumin-deungchobon-sinchengseo": (46,),
    "moel-pyojun-geunrogyeyakseo-2013": (118, 141),
    "moel-pyojun-geunrogyeyakseo-2025": (6, 37, 241),
    "saeopja-deungnok-sinchengseo": (166,),
}

#: A pair of advances counts as equal within this many HWPUNIT (0.02 pt).
#: The reference side is read out of a PDF through MuPDF's own float
#: reconstruction, so an exact comparison would be measuring the reader.
TOL_HWP = 2.0

#: Grids the rounding hypotheses quantise onto, in HWPUNIT.  ``1/100 pt`` is
#: not listed separately because 1 HWPUNIT IS 1/100 pt -- the unit the file
#: format is written in is already that grid.
GRIDS = {
    "none": None,
    "1 HWPUNIT (= 1/100 pt)": 1.0,
    "4 HWPUNIT (#263 leading grid)": 4.0,
    "1/64 pt": HWPUNIT_PER_PT / 64.0,
    "px @ 96 dpi": HWPUNIT_PER_PT * 72.0 / 96.0,
    "px @ 144 dpi": HWPUNIT_PER_PT * 72.0 / 144.0,
    "px @ 600 dpi (= 12 HWPUNIT)": HWPUNIT_PER_PT * 72.0 / 600.0,
}

#: 1/600 inch, in HWPUNIT.  The grid the reference PDF's own font sizes sit
#: on: see ``pdf_size_table``.
DEVICE_GRID_HWP = own_render.HWPUNIT_PER_INCH / 600.0


def cell_on_grid(size_hwp):
    """A run's character cell, rounded to the nearest 1/600 inch."""
    return round(size_hwp / DEVICE_GRID_HWP) * DEVICE_GRID_HWP


def truncate_to_grid(value):
    """An advance, truncated onto the 1/600 inch grid."""
    return math.floor(value / DEVICE_GRID_HWP) * DEVICE_GRID_HWP


#: The character classes a full-width cell rule governs, decided by Unicode's
#: own East Asian Width property rather than by a range list of this repo's.
#: MEASURED against the reference: over the 3746 (character, embedded face)
#: pairs the ten reference PDFs carry, ``W``/``F`` predicts an advance of
#: exactly 1.000 em, and anything else predicts less than one em, on 3630 of
#: them.  The 116 that miss are 40 ``A`` (ambiguous) characters that these
#: Korean faces do draw full width, and two display faces -- ``HaanYHeadB``
#: at 0.85 em and ``HCRBatang-Bold`` at 0.97 -- whose whole em is not 1.
FULL_WIDTH_EAW = frozenset(("W", "F"))

#: Candidate advance rules for a run whose face was SUBSTITUTED.  Each is a
#: complete answer to "how wide is this character", applied only where
#: ``fonts.faces[].source`` is not ``installed``; an installed face keeps its
#: own outlines' advance under every one of them.
FALLBACK_RULES = (
    "current",
    "cell",
    "cell+grid:round",
    "cell+grid:floor",
    "cell+grid:ceil",
    "cell+grid, space floor",
    "cell+grid, space floor, latin oracle",
)


def is_full_width(ch):
    """Does this character occupy a whole character cell?  See ``FULL_WIDTH_EAW``."""
    return unicodedata.east_asian_width(ch) in FULL_WIDTH_EAW


def quantise_grid(value, how):
    """``value`` onto the 1/600 inch grid, rounded / floored / ceiled."""
    units = value / DEVICE_GRID_HWP
    if how == "floor":
        units = math.floor(units + 1e-9)
    elif how == "ceil":
        units = math.ceil(units - 1e-9)
    else:
        units = round(units)
    return units * DEVICE_GRID_HWP


def rule_advance(name, base, ch, cell, oracle_em=None):
    """One character's advance in HWPUNIT under ``name``, on a substituted face.

    ``base`` is what the renderer measures today -- the stand-in face's own
    outlines, or, for a space, half the declared cell.  ``cell`` is the
    declared character cell (declared size x ``hh:ratio``), which is the
    quantity the reference says Hancom advances a full-width glyph by.
    """
    if name == "current":
        return base
    grid = "round"
    if name.startswith("cell+grid:"):
        grid = name.split(":", 1)[1]
    on_grid = name != "cell"
    cell_used = quantise_grid(cell, "round") if on_grid else cell
    if is_full_width(ch):
        return cell_used
    if ch in own_render.HALF_WIDTH_CELL_CHARS:
        half = cell_used * own_render.SPACE_CELL_FRACTION
        if not on_grid:
            return half
        if "space floor" in name:
            return quantise_grid(half, "floor")
        return quantise_grid(half, grid)
    if oracle_em is not None and "latin oracle" in name:
        return cell_used * oracle_em
    if not on_grid or cell <= 0:
        return base
    return quantise_grid(base / cell * cell_used, grid)


def readable_font_name(name):
    """A PDF font name, with a mis-decoded Korean name put back together.

    Hancom writes the Korean face name into the PDF as CP949 bytes, and a
    reader that takes them for Latin-1 hands back ``ÈÞ¸Õ¸íÁ¶`` where the
    document said 휴먼명조.  The round trip is attempted and dropped the
    moment it does not survive, so a genuinely Latin name is never mangled.
    """
    if not name:
        return name
    try:
        decoded = name.encode("latin-1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return decoded if decoded != name and decoded.isprintable() else name


# -- character classes ---------------------------------------------------

def char_class(ch):
    """The class an advance is grouped under.  Coarse on purpose.

    The question is which KIND of character our metrics disagree with Hancom
    about, so the classes are the ones a Korean form's line is made of and
    the ones the renderer treats differently: a Hangul syllable is a
    full-width cell, a space is the half-width cell ``SPACE_CELL_FRACTION``
    declares, and full-width punctuation is a full-width cell that is not a
    syllable.
    """
    code = ord(ch)
    if ch in own_render.SPACE_CHARS or ch.isspace() or code == 0x3000:
        return "space"
    if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF \
            or 0x3130 <= code <= 0x318F:
        return "hangul"
    if 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
        return "hanja"
    if ch.isdigit() and code < 0x80:
        return "digit"
    if ch.isascii() and ch.isalpha():
        return "latin"
    if code < 0x80:
        return "punct"
    if 0x3000 <= code <= 0x303F or 0xFF01 <= code <= 0xFF60 \
            or 0x2000 <= code <= 0x206F or 0x25A0 <= code <= 0x25FF \
            or 0x2460 <= code <= 0x24FF:
        return "fw_punct"
    if unicodedata.category(ch).startswith("P") \
            or unicodedata.category(ch).startswith("S"):
        return "fw_punct"
    return "other"


# -- the PDF side --------------------------------------------------------

#: ``hp:paraPr`` attributes that would switch Hancom's 한글-영문 / 한글-숫자
#: automatic spacing on.  Read off the file rather than assumed, because the
#: OWPML default when the attribute is absent is not stated in the schema
#: this repo holds and the corpus turns out to omit both everywhere.
AUTOSPACE_ATTRS = ("autoSpaceEAsianEng", "autoSpaceEAsianNum")


def autospace_flags(hwpx_path):
    """``{paraPr id: {attr: value or None}}`` straight out of ``header.xml``.

    ``own_render`` parses neither attribute, so this reads the header itself
    rather than adding an unused field to the renderer's ``para_pr``.  A
    ``None`` value means the attribute is ABSENT on that paragraph shape,
    which is a different statement from it being ``"0"``.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    out = {}
    try:
        with zipfile.ZipFile(hwpx_path) as archive:
            data = archive.read("Contents/header.xml")
    except (KeyError, OSError, zipfile.BadZipFile):
        return out
    for el in ET.fromstring(data).iter():
        if _local(el.tag) != "paraPr":
            continue
        pid = el.get("id")
        if pid is None:
            continue
        out[pid] = {name: el.get(name) for name in AUTOSPACE_ATTRS}
    return out


def read_pdf_chars(pdf_path):
    """``lineseg_vs_pdf.PdfLines``, with every line's characters attached.

    Same reader, same line records, same ordering as ``PdfLines.read`` -- the
    pairing has to be the one #258 measured, or the numbers here are about a
    different set of lines.  ``rawdict`` is ``dict`` plus a ``chars`` list per
    span, so the line grouping is identical and only the payload grows.
    """
    fitz = lineseg_vs_pdf._require_fitz()
    lines = []
    piece_seq = 0
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        for number, page in enumerate(document):
            for block in page.get_text("rawdict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    piece_seq += 1
                    raw = []
                    boxes = []
                    for span_index, span in enumerate(line.get("spans", [])):
                        for entry in span.get("chars", []):
                            ch = entry.get("c", "")
                            raw.append(ch)
                            cx0, cy0, cx1, cy1 = entry["bbox"]
                            boxes.append({
                                "c": ch,
                                "ox": entry["origin"][0],
                                "oy": entry["origin"][1],
                                "x0": cx0, "x1": cx1,
                                "y0": cy0, "y1": cy1,
                                "size": span.get("size"),
                                "font": readable_font_name(span.get("font")),
                                # Which text-showing run this character came
                                # out of.  An advance may only be taken
                                # BETWEEN two characters of the same run: the
                                # gap between two runs is Hancom moving the
                                # pen (a tab, a 배분 spread, a field), not a
                                # glyph's width.  ``piece`` is made unique per
                                # MuPDF line record downstream, so the merge
                                # that welds a tracked line back together
                                # cannot hide a run boundary.
                                "piece": (piece_seq, span_index),
                            })
                    text = "".join(raw)
                    key = lineseg_vs_pdf.normalise(text)
                    if not key:
                        continue
                    x0, y0, x1, y1 = line["bbox"]
                    lines.append({
                        "page": number,
                        "text": text,
                        "key": key,
                        "chars": len(key),
                        "top_hwp": y0 * HWPUNIT_PER_PT,
                        "bottom_hwp": y1 * HWPUNIT_PER_PT,
                        "x0_hwp": x0 * HWPUNIT_PER_PT,
                        "x1_hwp": x1 * HWPUNIT_PER_PT,
                        "dir": tuple(line.get("dir", (1.0, 0.0))),
                        "boxes": boxes,
                    })
    return lineseg_vs_pdf.PdfLines(lines, page_count=page_count,
                                   path=str(pdf_path))


def merge_lines_with_boxes(pieces):
    """``lineseg_vs_pdf.merge_visual_lines``, carrying the character boxes.

    The regrouping rule is the upstream one, character for character; the
    only addition is that the merged group keeps the concatenation of its
    pieces' ``boxes`` in the same order, which is the order the match already
    proved is reading order.
    """
    merged = lineseg_vs_pdf.merge_visual_lines(pieces)
    for group in merged:
        boxes = []
        for part in group.pop("parts"):
            boxes.extend(part["boxes"])
        group["boxes"] = boxes
    return merged


# -- our side ------------------------------------------------------------

def declared_face(renderer, cid, slot):
    """The face name ``hh:fontRef`` declares for ``(cid, slot)``, or ``None``.

    ``OwnRenderer._face_for`` resolves the same lookup to a FILE and caches
    it; the declared NAME is what the disagreement has to be grouped by, so
    the two lines of table walk it does are repeated here rather than the
    cache being reverse-engineered.
    """
    font_ids = renderer._charpr(cid).get("font_ids") or {}
    for slot_key in (slot, slot.upper()):
        font_id = font_ids.get(slot_key)
        if font_id is None:
            continue
        table = (renderer.defs["fontfaces"].get(slot.upper())
                 or renderer.defs["fontfaces"].get(slot) or {})
        name = table.get(font_id)
        if name:
            return name
    return None


class OurMetrics:
    """Our advance for one character under one ``hh:charPr``, plus its run.

    Everything here is asked of the renderer's own API -- ``_measure_hwp`` is
    the call ``_char_advance_tables`` makes per character, so an advance read
    out of this class is the advance the LINE BREAKER used, not a
    reconstruction of it.
    """

    def __init__(self, renderer, oracle=None):
        self.renderer = renderer
        #: ``(declared face, class) -> em`` read off Hancom's own drawn
        #: advances, for the one rule that is fitted rather than derived.
        self.oracle = oracle or {}
        self._cache = {}

    def run(self, ch, cid):
        """``(declared, resolved, size_pt, spacing, ratio, class)``."""
        key = (ch, cid)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._compute(ch, cid)
            self._cache[key] = hit
        return hit

    def _compute(self, ch, cid):
        renderer = self.renderer
        slot = script_slot(ch)
        ratio, spacing, rel_sz, _offset = renderer._typography(cid, ch)
        cp = renderer._charpr(cid)
        bold = bool(cp.get("bold"))
        size_pt = (cp.get("height_pt") or 10.0) * rel_sz / 100.0
        chosen = renderer._face_for(cid, slot, bold)
        # ``_face_for`` files its own answer in ``face_resolution`` under the
        # declared name, and that record carries the one fact this pass needs
        # beside the file: whether the face is the DECLARED one (installed) or
        # a stand-in (bundled, system).  Read rather than re-derived, so the
        # split below is the renderer's own classification.
        declared = declared_face(renderer, cid, slot)
        record = renderer.face_resolution.get(
            (declared or "(no hh:fontRef for this slot)", slot, bold))
        source = record["source"] if record else "system"
        if chosen is None:
            resolved = "(fallback)"
        else:
            resolved = Path(chosen[0]).name
            if chosen[1]:
                resolved += f"#{chosen[1]}"
        advance = renderer._measure_hwp(None, ch, cid)
        gap = renderer._spacing_gap(advance, spacing) if spacing else 0.0
        # The same advance under the DEVICE-GRID hypothesis: the run's cell is
        # rounded to 1/600 inch first (which is where the reference PDF's own
        # font sizes sit -- see ``pdf_size_table``), the face's em advance is
        # taken against THAT cell, and the result is truncated onto the same
        # grid.  A space keeps the half-cell rule, on the grid.
        cell_hwp = size_pt * HWPUNIT_PER_PT * ratio / 100.0
        cell = cell_on_grid(cell_hwp)
        if cell_hwp <= 0:
            grid_advance = advance
        elif ch in own_render.HALF_WIDTH_CELL_CHARS:
            grid_advance = truncate_to_grid(cell * own_render.SPACE_CELL_FRACTION)
        else:
            grid_advance = truncate_to_grid(advance / cell_hwp * cell)
        grid_gap = (renderer._spacing_gap(grid_advance, spacing)
                    if spacing else 0.0)
        # Every candidate fallback rule, priced on this one character.  An
        # installed face is untouched by all of them, which is what makes the
        # installed lines a control rather than a second treatment.
        klass = char_class(ch)
        oracle_em = self.oracle.get((declared, klass))
        rules = {}
        rule_gaps = {}
        for name in FALLBACK_RULES:
            if source == "installed" or cell_hwp <= 0:
                value = advance
            else:
                value = rule_advance(name, advance, ch, cell_hwp, oracle_em)
            rules[name] = value
            rule_gaps[name] = (renderer._spacing_gap(value, spacing)
                               if spacing else 0.0)
        return {
            "declared": declared,
            "cell_hwp": cell_hwp,
            "resolved": resolved,
            "source": source,
            "slot": slot,
            "bold": bold,
            "size_pt": round(size_pt, 2),
            "spacing": spacing,
            "ratio": ratio,
            "class": klass,
            "advance_hwp": advance,
            "gap_hwp": gap,
            "grid_advance_hwp": grid_advance,
            "grid_gap_hwp": grid_gap,
            "rule_advance_hwp": rules,
            "rule_gap_hwp": rule_gaps,
        }


# -- the pairing ---------------------------------------------------------

def align(ours, theirs):
    """``[(i, j)]`` -- our character index against the PDF's, 1:1.

    ``difflib`` rather than a hand-rolled walk because the two sides are
    entitled to disagree about whitespace and about nothing else, and an
    opcode-level alignment says exactly which characters were left out
    instead of silently sliding the rest of the line by one.
    """
    left = "".join(ch for ch, _cid in ours)
    right = "".join(box["c"] for box in theirs)
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    pairs = []
    for a, b, size in matcher.get_matching_blocks():
        for step in range(size):
            pairs.append((a + step, b + step))
    return pairs, len(left), len(right)


def hancom_advances(boxes):
    """Per-character advance in HWPUNIT, and whether it is a run's last.

    The advance of a character is where the NEXT one starts minus where it
    starts -- but only when the next one comes out of the same text-showing
    run.  Across a run boundary the difference is Hancom moving the pen, and
    the very first version of this probe counted those as glyph widths, which
    is what made ASCII punctuation look like it had a 0.03-to-2.5 spread.

    A run's last character has no successor: its bbox WIDTH is reported in
    its place and it is flagged, because a bbox is ink and an advance is not
    -- the difference is the right side bearing, which this script does not
    model and does not need to.
    """
    out = []
    for index, box in enumerate(boxes):
        nxt = boxes[index + 1] if index + 1 < len(boxes) else None
        if nxt is not None and nxt["piece"] == box["piece"]:
            out.append(((nxt["ox"] - box["ox"]) * HWPUNIT_PER_PT, False))
        else:
            out.append(((box["x1"] - box["x0"]) * HWPUNIT_PER_PT, True))
    return out


def _para_chars_in_cells(para, lo, hi):
    """``[(index, ch, cid)]`` -- the characters seated in cells ``[lo, hi)``."""
    out = []
    for index, (ch, cid) in enumerate(para.chars):
        cell = para.cell_start[index]
        if lo <= cell < hi and ch != own_render.OBJECT_SLOT:
            out.append((index, ch, cid))
    return out


def analyse_line(ours, boxes, metrics, keep_text=True):
    """One line of ours against one PDF line: the anchored segments.

    HANCOM DOES NOT DRAW EVERY CHARACTER.  On this corpus a line of 60
    characters commonly reaches the PDF as 31 glyphs in 19 text-showing runs:
    the spaces are not glyphs at all, they are the pen being moved between
    runs.  So the comparison is not glyph-against-glyph but ANCHOR-TO-ANCHOR:
    between two characters the alignment matched, the distance Hancom moved
    the pen is exactly ``ox[j2] - ox[j1]`` in absolute page coordinates, and
    what we should have moved it by is the sum of our advances over our own
    characters ``i1 .. i2-1``.  A segment spanning one character on each side
    is a pure per-glyph advance and is the only kind the ratio table uses; a
    segment that swallowed undrawn characters carries the space model as well
    as the glyph, and is kept apart for that reason.

    Both sides of a segment cover the SAME characters.  Summing our advances
    over the anchors alone while taking Hancom's distance across the gaps
    between them would compare a line to a different line, which is a mistake
    the first version of the carrier pass made and this function exists to
    make impossible.
    """
    pairs, n_ours, n_theirs = align([(ch, cid) for _i, ch, cid in ours], boxes)
    chars = []
    segments = []
    for step in range(len(pairs) - 1):
        i1, j1 = pairs[step]
        i2, j2 = pairs[step + 1]
        covered = [ours[i] for i in range(i1, i2)]
        ours_hwp = 0.0
        grid_hwp = 0.0
        rule_hwp = dict.fromkeys(FALLBACK_RULES, 0.0)
        for _pos, ch, cid in covered:
            run = metrics.run(ch, cid)
            ours_hwp += run["advance_hwp"] + run["gap_hwp"]
            grid_hwp += run["grid_advance_hwp"] + run["grid_gap_hwp"]
            for name in FALLBACK_RULES:
                rule_hwp[name] += (run["rule_advance_hwp"][name]
                                   + run["rule_gap_hwp"][name])
        hancom_hwp = (boxes[j2]["ox"] - boxes[j1]["ox"]) * HWPUNIT_PER_PT
        has_tab = any(ch == "\t" for _p, ch, _c in covered)
        singleton = (i2 == i1 + 1 and j2 == j1 + 1
                     and boxes[j1]["piece"] == boxes[j2]["piece"])
        head = metrics.run(covered[0][1], covered[0][2])
        segments.append({
            "ours_hwp": ours_hwp, "hancom_hwp": hancom_hwp,
            "grid_hwp": grid_hwp, "rule_hwp": rule_hwp,
            "chars": len(covered), "tab": has_tab, "singleton": singleton,
            "resolved": head["resolved"], "class": head["class"],
            "sources": sorted({metrics.run(ch, cid)["source"]
                               for _p, ch, cid in covered}),
        })
        if singleton and not has_tab:
            # The character that FOLLOWS this one in our own text, and its
            # class.  A singleton segment's Hancom distance is the pen move
            # from this glyph's origin to the next one's, so it is this
            # glyph's advance PLUS whatever Hancom inserts at the boundary
            # between the two classes -- which is the quantity the
            # inter-class gap table reads.  Recorded here because this is
            # the only place both sides of the boundary are in hand.
            nxt = ours[i2] if i2 < len(ours) else None
            nxt_run = metrics.run(nxt[1], nxt[2]) if nxt is not None else None
            chars.append({
                "char": covered[0][1] if keep_text else None,
                "class": head["class"],
                "slot": head["slot"],
                "source": head["source"],
                "next_char": (nxt[1] if (nxt is not None and keep_text)
                              else None),
                "next_class": nxt_run["class"] if nxt_run else None,
                "next_source": nxt_run["source"] if nxt_run else None,
                # The full-width cell this advance is a fraction of: the
                # declared point size times ``hh:ratio``.  Dividing by it
                # turns every advance into em and makes sizes comparable.
                "cell_hwp": head["declared"],
                "declared": head["declared"],
                "cell_hwp": head["cell_hwp"],
                "source": head["source"],
                "resolved": head["resolved"],
                # What Hancom's own exporter embedded for this glyph.  The
                # declared name is what the FILE asks for; this is what the
                # reference actually drew with, and the two together say
                # whether a ratio is a substitution or a metric disagreement
                # inside one face.
                "pdf_font": boxes[j1].get("font"),
                "pdf_size": (round(boxes[j1]["size"], 4)
                             if boxes[j1].get("size") else None),
                "size_pt": head["size_pt"],
                "spacing": head["spacing"],
                "ratio": head["ratio"],
                "bold": head["bold"],
                "ours_hwp": ours_hwp,
                "hancom_hwp": hancom_hwp,
                "rule_hwp": dict(rule_hwp),
            })
    return pairs, n_ours, n_theirs, chars, segments


def pair_lines(para, cells, pdf_run, metrics, keep_text):
    """One paragraph's cached lines against the PDF's, line by line."""
    spans = lineseg_vs_pdf.cached_split(para, cells)
    align_mode = para.para_pr.get("align", "LEFT")
    lines = []
    for index, (lo, hi) in enumerate(spans):
        if index >= len(pdf_run):
            break
        ours = _para_chars_in_cells(para, lo, hi)
        boxes = pdf_run[index]["boxes"]
        if not ours or not boxes:
            continue
        pairs, n_ours, n_theirs, chars, segments = analyse_line(
            ours, boxes, metrics, keep_text)
        advances = hancom_advances(boxes)
        # The line's own width, guess-free: the pen distance from the first
        # anchored character to the last, against the sum of our advances over
        # the same stretch of our own characters.  No side bearing, no bbox
        # and no unmatched tail on either side enters it.
        #
        # Alignment is what most of this corpus's lines are excluded by.  A
        # DISTRIBUTE line has its gaps opened by the paragraph and never
        # carries a width; a JUSTIFY line does too, EXCEPT its last, which
        # has no slack to distribute and is therefore drawn at its natural
        # width.  Dropping every justified line drops nine tenths of the
        # corpus, so the last line of a JUSTIFY paragraph is kept and
        # everything else about a justified paragraph is not.
        is_last = (index == len(spans) - 1)
        stretched = (align_mode == "DISTRIBUTE"
                     or (align_mode == "JUSTIFY" and not is_last))
        usable = (bool(pairs) and not any(seg["tab"] for seg in segments)
                  and not stretched)
        record = {
            "line": index,
            "cells": [lo, hi],
            "ours_chars": n_ours,
            "pdf_chars": n_theirs,
            "aligned": len(pairs),
            "fully_aligned": len(pairs) == n_ours == n_theirs,
            "pdf_pieces": len({box["piece"] for box in boxes}),
            "align": align_mode,
            "last_line": is_last,
            "stretched": stretched,
            "undrawn_chars": n_ours - len(pairs),
            "has_tab": any(seg["tab"] for seg in segments),
            "ours_span_hwp": sum(seg["ours_hwp"] for seg in segments),
            "hancom_span_hwp": sum(seg["hancom_hwp"] for seg in segments),
            "comparable": usable and len(pairs) > 1,
            "singleton_segments": sum(1 for s in segments if s["singleton"]),
            "last_char_bbox_hwp": advances[-1][0],
            "horzsize": _iattr(para.linesegs[index], "horzsize"),
            "chars": chars,
            "segments": segments,
        }
        if keep_text:
            record["text"] = "".join(box["c"] for box in boxes)
        lines.append(record)
    return lines


def probe_document(hwpx_path, pdf_path, repo_root=None, keep_text=True,
                   oracle=None):
    """Every paired top-level text line of one document, both sides."""
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    metrics = OurMetrics(renderer, oracle=oracle)
    pdf = read_pdf_chars(pdf_path)
    flags = autospace_flags(hwpx_path)
    cursor = 0
    paragraphs = []
    skipped = defaultdict(int)
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        for order, el in enumerate(_kids(renderer.sections[section], "p")):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = lineseg_vs_pdf.character_cells(para)
            reason = lineseg_vs_pdf.skip_reason(para, cells)
            if reason is not None:
                skipped[reason] += 1
                continue
            target = lineseg_vs_pdf.normalise(
                lineseg_vs_pdf.paragraph_text(cells))
            hit = pdf.find_run(target, cursor)
            if hit is None:
                skipped["no_pdf_match"] += 1
                continue
            lo, hi, _relaxed, out_of_order = hit
            pdf_run = merge_lines_with_boxes(pdf.lines[lo:hi])
            cursor = lineseg_vs_pdf._cursor_after(cursor, hi, out_of_order)
            paragraphs.append({
                "section": section,
                "paragraph": order,
                "address": renderer.paragraph_index.get(id(el)),
                "para_pr": el.get("paraPrIDRef"),
                "autospace": flags.get(el.get("paraPrIDRef") or "",
                                       {name: None
                                        for name in AUTOSPACE_ATTRS}),
                "condense": para.para_pr.get("condense"),
                "cached_lines": len(para.linesegs),
                "pdf_lines": len(pdf_run),
                "lines": pair_lines(para, cells, pdf_run, metrics, keep_text),
            })
    return {
        "document": str(hwpx_path),
        "reference": str(pdf_path),
        "paragraphs": paragraphs,
        "skipped": dict(skipped),
    }


# -- statistics ----------------------------------------------------------

def _pct(values, share):
    if not values:
        return None
    ordered = sorted(values)
    at = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return ordered[at]


def run_table(reports):
    """Per ``(declared -> resolved, size pt, spacing %, class)``: the ratio."""
    buckets = defaultdict(list)
    undrawn = 0
    zero_hancom = 0
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                undrawn += line.get("undrawn_chars", 0)
                for entry in line.get("chars", []):
                    if abs(entry["hancom_hwp"]) < 1e-9:
                        zero_hancom += 1
                        continue
                    # The cell, not the declared face name: two runs of the
                    # same face at the same size but different ``hh:ratio``
                    # are different advances and stay different rows.
                    key = (entry["cell_hwp"], entry["resolved"],
                           entry.get("pdf_font"),
                           entry["size_pt"], entry["spacing"], entry["class"])
                    buckets[key].append((entry["ours_hwp"],
                                         entry["hancom_hwp"]))
    rows = []
    for key, pairs in buckets.items():
        ratios = [ours / theirs for ours, theirs in pairs]
        deltas = [ours - theirs for ours, theirs in pairs]
        rows.append({
            "cell_hwp": key[0], "resolved": key[1], "pdf_font": key[2],
            "size_pt": key[3], "spacing": key[4], "class": key[5],
            "n": len(pairs),
            "ratio_median": statistics.median(ratios),
            "ratio_p10": _pct(ratios, 0.10),
            "ratio_p90": _pct(ratios, 0.90),
            "delta_median_hwp": statistics.median(deltas),
            "hancom_median_hwp": statistics.median(t for _o, t in pairs),
            "ours_median_hwp": statistics.median(o for o, _t in pairs),
        })
    rows.sort(key=lambda row: -row["n"])
    return rows, undrawn, zero_hancom


def class_table(reports):
    """The same ratio, collapsed onto the character class alone."""
    buckets = defaultdict(list)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if abs(entry["hancom_hwp"]) < 1e-9:
                        continue
                    buckets[entry["class"]].append(
                        (entry["ours_hwp"], entry["hancom_hwp"]))
    rows = []
    for name, pairs in buckets.items():
        ratios = [o / t for o, t in pairs]
        rows.append({
            "class": name, "n": len(pairs),
            "ratio_median": statistics.median(ratios),
            "ratio_p10": _pct(ratios, 0.10),
            "ratio_p90": _pct(ratios, 0.90),
            "delta_median_hwp": statistics.median(o - t for o, t in pairs),
        })
    rows.sort(key=lambda row: -row["n"])
    return rows


#: The two classes ``char_class`` puts a punctuation mark in.  ``fw_punct``
#: is everything outside ASCII that is not a syllable, so it also holds the
#: CJK brackets and the general-punctuation quotation marks.
PUNCT_CLASSES = frozenset({"punct", "fw_punct"})


def installed_chars(reports, classes=None):
    """Every anchored single-character advance drawn in an INSTALLED face.

    Restricted on BOTH sides of the boundary: the character's own face is the
    declared one and so is its successor's, because a segment's distance is a
    pen move whose far end is the next glyph's origin and a substituted
    successor can be positioned by a metric that is not the declared face's.
    The fallback slice is measuring the other half of this population; the
    filter here is what keeps the two disjoint.
    """
    out = []
    for report in reports:
        for para in report["paragraphs"]:
            auto = para.get("autospace") or {}
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if entry.get("source") != "installed":
                        continue
                    if entry.get("next_source") not in (None, "installed"):
                        continue
                    if abs(entry["hancom_hwp"]) < 1e-9:
                        continue
                    if not entry.get("cell_hwp"):
                        continue
                    if classes is not None and entry["class"] not in classes:
                        continue
                    row = dict(entry)
                    row["form"] = Path(report["document"]).stem
                    row["autospace"] = auto
                    out.append(row)
    return out


def punct_char_table(reports):
    """Per punctuation CODE POINT, on installed faces: Hancom's em vs ours.

    Grouped by the character itself rather than by class, because the class
    is the hypothesis under test: #267 found ``fw_punct`` and ``punct``
    over-measuring in aggregate, and an aggregate over a class cannot say
    whether every mark in it is wrong by the same amount or one mark is
    wrong by all of it.

    ``em`` is the advance over the run's full-width cell (declared size times
    ``hh:ratio``), so 1.0 is a full-width cell and 0.5 a half-width one.
    """
    buckets = defaultdict(list)
    for row in installed_chars(reports, PUNCT_CLASSES):
        buckets[(row["char"], row["class"], row["resolved"])].append(row)
    rows = []
    for (ch, klass, face), group in buckets.items():
        hancom = [g["hancom_hwp"] for g in group]
        ours = [g["ours_hwp"] for g in group]
        cells = [g["cell_hwp"] for g in group]
        rows.append({
            "char": ch,
            "codepoint": f"U+{ord(ch):04X}" if ch else None,
            "class": klass,
            "slot": group[0]["slot"],
            "resolved": face,
            "pdf_fonts": sorted({str(g["pdf_font"]) for g in group}),
            "forms": sorted({g["form"] for g in group}),
            "n": len(group),
            "hancom_median_hwp": statistics.median(hancom),
            "ours_median_hwp": statistics.median(ours),
            "hancom_em": statistics.median(h / c for h, c
                                           in zip(hancom, cells)),
            "ours_em": statistics.median(o / c for o, c in zip(ours, cells)),
            "ratio": statistics.median(o / h for o, h in zip(ours, hancom)),
            "delta_median_hwp": statistics.median(o - h for o, h
                                                  in zip(ours, hancom)),
            "total_delta_hwp": sum(o - h for o, h in zip(ours, hancom)),
        })
    rows.sort(key=lambda row: -abs(row["total_delta_hwp"]))
    return rows


def gap_table(reports):
    """The inter-class boundary, on installed faces, in em.

    A singleton segment's Hancom distance is the pen move from one glyph's
    origin to the next one's: the first glyph's own advance PLUS anything
    Hancom inserts at the boundary.  The first glyph's own advance is not
    separately observable in a PDF, so the baseline is measured rather than
    assumed: for the same (character class, face, size) the median distance
    when the SUCCESSOR IS OF THE SAME CLASS, where no inter-class rule can
    apply.  The gap is the difference of the two medians, and the same
    subtraction is done on our side so the two columns answer the same
    question.

    ``autoSpaceEAsianEng`` / ``autoSpaceEAsianNum`` are carried through from
    the paragraph so the table can be split by them.  On this corpus both
    attributes are ABSENT from every ``hp:paraPr``, which the formatter says
    out loud rather than reporting a split that does not exist.
    """
    rows = installed_chars(reports)
    baseline = defaultdict(list)
    for row in rows:
        if row["next_class"] == row["class"]:
            key = (row["class"], row["resolved"], row["size_pt"])
            baseline[key].append((row["hancom_hwp"] / row["cell_hwp"],
                                  row["ours_hwp"] / row["cell_hwp"]))
    base_med = {k: (statistics.median(h for h, _o in v),
                    statistics.median(o for _h, o in v))
                for k, v in baseline.items()}
    pairs = defaultdict(list)
    for row in rows:
        if row["next_class"] is None or row["next_class"] == row["class"]:
            continue
        key = (row["class"], row["resolved"], row["size_pt"])
        if key not in base_med:
            continue
        h_base, o_base = base_med[key]
        flags = row["autospace"]
        pairs[(row["class"], row["next_class"],
               flags.get("autoSpaceEAsianEng"),
               flags.get("autoSpaceEAsianNum"))].append(
            (row["hancom_hwp"] / row["cell_hwp"] - h_base,
             row["ours_hwp"] / row["cell_hwp"] - o_base,
             row["hancom_hwp"] - row["ours_hwp"]))
    out = []
    for (left, right, eng, num), group in pairs.items():
        out.append({
            "from": left, "to": right,
            "autoSpaceEAsianEng": eng, "autoSpaceEAsianNum": num,
            "n": len(group),
            "hancom_gap_em": statistics.median(h for h, _o, _d in group),
            "ours_gap_em": statistics.median(o for _h, o, _d in group),
            "gap_delta_em": statistics.median(h - o for h, o, _d in group),
        })
    out.sort(key=lambda row: -row["n"])
    return out


def comparable_lines(reports):
    """The lines a per-line width may be read off: aligned, one run, non-empty."""
    out = []
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                if line.get("comparable"):
                    out.append(line)
    return out


def comparability_counts(reports):
    """Why a paired line does or does not carry a per-line width.

    The width tables run on a small fraction of the paired lines and it has
    to be visible why: a JUSTIFY or DISTRIBUTE line's gaps are its alignment,
    a tab is a stop this renderer declares it does not place, and a line with
    one anchor has no distance between two of them.
    """
    counts = defaultdict(int)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                counts["paired"] += 1
                if line.get("has_tab"):
                    counts["tab"] += 1
                elif line.get("stretched"):
                    counts["stretched"] += 1
                elif line.get("aligned", 0) < 2:
                    counts["one_anchor"] += 1
                else:
                    counts["comparable"] += 1
    return dict(counts)


def _delta_stats(deltas):
    if not deltas:
        return None
    return {
        "n": len(deltas),
        "median": statistics.median(deltas),
        "median_abs": statistics.median(abs(d) for d in deltas),
        "p10": _pct(deltas, 0.10),
        "p90": _pct(deltas, 0.90),
        "min": min(deltas), "max": max(deltas),
        "within_tol": sum(1 for d in deltas if abs(d) <= TOL_HWP),
    }


def line_delta_stats(reports):
    """The per-line width delta, ours minus Hancom, in HWPUNIT.

    Split by whether every face on the line is the DECLARED one.  A line
    drawn entirely in installed faces is a line where the disagreement can
    only be metrics; a line carrying a bundled or fallback stand-in is a line
    where it can be the face itself, and mixing the two hides which.
    """
    lines = comparable_lines(reports)
    everything = []
    installed = []
    substituted = []
    for line in lines:
        delta = line["ours_span_hwp"] - line["hancom_span_hwp"]
        everything.append(delta)
        sources = {source for seg in line["segments"]
                   for source in seg.get("sources", ())}
        (installed if sources <= {"installed"} else substituted).append(delta)
    return {
        "all": _delta_stats(everything),
        "installed_only": _delta_stats(installed),
        "substituted": _delta_stats(substituted),
    }


def quantise(value, grid):
    return value if grid is None else round(value / grid) * grid


def grid_residual_table(reports, tol=0.05):
    """Are HANCOM's own advances on a grid?  Read straight off the PDF.

    The share of Hancom's per-character advances that sit within ``tol``
    HWPUNIT of a multiple of each candidate grid.  This is the direct form of
    the rounding question and it does not go through our metrics at all: if
    Hancom quantised each advance onto a grid, its own numbers say so.

    ``expected_by_chance`` is what a UNIFORM advance would score on the same
    grid at the same tolerance, and it is the only thing that makes the share
    readable: at a half-step tolerance every grid scores 100% and the test
    says nothing, which is why the tolerance here is 0.05 HWPUNIT (1/2000 pt)
    and not the ``TOL_HWP`` the width comparisons use.
    """
    values = []
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    values.append(entry["hancom_hwp"])
    rows = []
    for name, grid in GRIDS.items():
        if grid is None:
            continue
        on = sum(1 for v in values
                 if abs(v - quantise(v, grid)) <= min(tol, grid / 2.0))
        rows.append({"grid": name, "step_hwp": grid, "n": len(values),
                     "on_grid": on,
                     "share": on / len(values) if values else None,
                     "expected_by_chance": min(1.0, 2 * min(tol, grid / 2.0)
                                               / grid)})
    return rows


def rounding_table(reports):
    """Does quantising OUR advances reproduce Hancom's per-line widths?"""
    lines = comparable_lines(reports)
    rows = []
    candidates = [(name, grid, False) for name, grid in GRIDS.items()]
    # The one hypothesis that is not a post-hoc rounding of our own number:
    # the run's CELL goes onto the 1/600 inch grid before the face's em
    # advance is scaled by it, and the advance is then truncated onto the
    # same grid.  It is a different rule from "round the answer", because it
    # moves the point size the answer is computed from.
    candidates.append(("1/600 in cell (size + truncate)", None, True))
    for name, grid, use_cell in candidates:
        exact = 0
        deltas = []
        for line in lines:
            if use_cell:
                total = sum(seg["grid_hwp"] for seg in line["segments"])
            else:
                total = sum(quantise(seg["ours_hwp"], grid)
                            for seg in line["segments"])
            delta = total - line["hancom_span_hwp"]
            deltas.append(delta)
            if abs(delta) <= TOL_HWP:
                exact += 1
        rows.append({
            "grid": name, "step_hwp": grid if not use_cell else DEVICE_GRID_HWP,
            "paired": len(lines), "exact": exact,
            "median_abs_hwp": (statistics.median(abs(d) for d in deltas)
                               if deltas else None),
            "median_hwp": statistics.median(deltas) if deltas else None,
        })
    return rows


def pdf_size_table(reports):
    """Is the reference PDF's own font size on the 1/600 inch grid?

    Read straight off the export, with no metric of ours in it.  For every
    (declared point size, PDF font) the probe saw, the size MuPDF reports for
    the span against the size the file declares and against that size rounded
    to a whole 1/600 inch.  This is the public basis a device-grid rule would
    rest on: it is a property of the reference, measurable by anyone holding
    the same two files.
    """
    seen = defaultdict(set)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if entry.get("pdf_size") is None:
                        continue
                    seen[(entry["size_pt"], entry["pdf_font"])].add(
                        entry["pdf_size"])
    rows = []
    for (declared, font), sizes in seen.items():
        predicted = cell_on_grid(declared * HWPUNIT_PER_PT) / HWPUNIT_PER_PT
        for size in sorted(sizes):
            rows.append({
                "declared_pt": declared, "pdf_font": font,
                "pdf_pt": size, "grid_pt": round(predicted, 4),
                "on_grid": abs(size - predicted) < 0.005,
            })
    rows.sort(key=lambda row: (row["declared_pt"], str(row["pdf_font"])))
    return rows


# -- the substituted-face question (#280) ---------------------------------

def line_source(line):
    """``installed`` or ``substituted`` for one comparable line."""
    sources = {source for seg in line["segments"]
               for source in seg.get("sources", ())}
    return "installed" if sources <= {"installed"} else "substituted"


def latin_oracle(reports):
    """``(declared face, class) -> em``, off Hancom's OWN drawn advances.

    The one candidate rule that is fitted rather than derived: for every
    class on a SUBSTITUTED face, the median of Hancom's advance divided by
    the run's declared cell.  It is an oracle in the strict sense -- it was
    read off the reference it is then scored against -- so what it measures
    is the ceiling a per-face Latin table could reach, not a shippable rule.
    """
    buckets = defaultdict(list)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if entry.get("source") == "installed":
                        continue
                    cell = entry.get("cell_hwp") or 0.0
                    if cell <= 0 or abs(entry["hancom_hwp"]) < 1e-9:
                        continue
                    buckets[(entry["declared"], entry["class"])].append(
                        entry["hancom_hwp"] / cell)
    return {key: statistics.median(values) for key, values in buckets.items()}


def substituted_em_table(reports):
    """Per (declared face, resolved stand-in, class): Hancom's em against ours.

    Both sides divided by the run's own declared cell, so the numbers are
    face metrics and not point sizes: ``hancom_em`` is what the reference
    advances that character by, ``ours_em`` is what the stand-in's outlines
    say, and ``on_grid`` is the share of Hancom's advances that land on a
    whole 1/600 inch -- which is how a Latin advance is told apart from a
    full cell.
    """
    buckets = defaultdict(list)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    cell = entry.get("cell_hwp") or 0.0
                    if cell <= 0 or abs(entry["hancom_hwp"]) < 1e-9:
                        continue
                    buckets[(entry.get("source"), entry["declared"],
                             entry["resolved"], entry["class"])].append(
                        (entry["hancom_hwp"], entry["ours_hwp"], cell))
    rows = []
    for key, values in buckets.items():
        hancom = [h / c for h, _o, c in values]
        ours = [o / c for _h, o, c in values]
        on_grid = sum(1 for h, _o, _c in values
                      if abs(h - quantise_grid(h, "round")) <= 0.05)
        rows.append({
            "source": key[0], "declared": key[1], "resolved": key[2],
            "class": key[3], "n": len(values),
            "hancom_em": statistics.median(hancom),
            "ours_em": statistics.median(ours),
            "on_grid": on_grid / len(values),
        })
    # Substituted first: they are the population this report is about, and a
    # truncated table has to keep them rather than the control.
    rows.sort(key=lambda row: (row["source"] == "installed", -row["n"]))
    return rows


def fullwidth_cell_table(reports):
    """The full-width advance, MEAN against MODAL, per (face, size).

    #267 read "13 pt advances by 1296, the declared size rounded to a whole
    1/600 inch" off the MEDIAN of Hancom's per-character advances.  The
    median is not the advance.  At 13 pt Hancom's individual full-width
    advances are 108 units of 1/600 inch on 1515 characters and 109 on 797,
    and the mean of those is 108.29 against the 108.333 that 13 pt actually
    is: the 1/600 inch grid is on the PEN POSITION, not on the advance, so a
    single advance is the declared cell rounded up or down by at most one
    unit while a run of them accumulates the declared cell exactly.

    Which is the quantity a line breaker needs -- so this table is the one
    that says what a rule should use, and it says the declared cell.
    """
    buckets = defaultdict(list)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if entry["spacing"] or not entry.get("cell_hwp"):
                        continue
                    if entry["class"] not in ("hangul", "hanja"):
                        continue
                    buckets[(entry.get("source"), entry.get("pdf_font"),
                             entry["size_pt"], entry["cell_hwp"])].append(
                        entry["hancom_hwp"])
    rows = []
    for (source, font, size_pt, cell), values in buckets.items():
        if len(values) < 30:
            continue
        units = defaultdict(int)
        for value in values:
            units[int(round(value / DEVICE_GRID_HWP))] += 1
        rows.append({
            "source": source, "pdf_font": font, "size_pt": size_pt,
            "cell_hwp": cell, "n": len(values),
            "mean_hwp": statistics.mean(values),
            "median_hwp": statistics.median(values),
            "grid_cell_hwp": cell_on_grid(cell),
            "mean_over_cell": statistics.mean(values) / cell,
            "units": dict(sorted(units.items())),
        })
    rows.sort(key=lambda row: -row["n"])
    return rows


def fallback_rule_table(reports):
    """Every candidate rule, scored on the comparable lines it can move.

    Split installed / substituted, because a rule that only fires on a
    substituted face MUST leave the installed lines exactly where they were
    and the table has to show that rather than assert it.
    """
    lines = comparable_lines(reports)
    rows = []
    for name in FALLBACK_RULES:
        row = {"rule": name}
        for group in ("installed", "substituted"):
            deltas = []
            for line in lines:
                if line_source(line) != group:
                    continue
                total = sum(seg["rule_hwp"][name] for seg in line["segments"])
                deltas.append(total - line["hancom_span_hwp"])
            row[group] = {
                "n": len(deltas),
                "exact": sum(1 for d in deltas if abs(d) <= TOL_HWP),
                "median": statistics.median(deltas) if deltas else None,
                "median_abs": (statistics.median(abs(d) for d in deltas)
                               if deltas else None),
                "p10": _pct(deltas, 0.10), "p90": _pct(deltas, 0.90),
            }
        rows.append(row)
    return rows


def fallback_class_residual(reports):
    """Per rule and character class, the residual on SUBSTITUTED characters.

    One anchored character against the next, so this is a per-glyph residual
    and not a line's accumulation of them: ours under the rule minus
    Hancom's, in HWPUNIT, median and the share inside 2 HWPUNIT.
    """
    buckets = defaultdict(list)
    for report in reports:
        for para in report["paragraphs"]:
            for line in para["lines"]:
                for entry in line.get("chars", []):
                    if entry.get("source") == "installed":
                        continue
                    if abs(entry["hancom_hwp"]) < 1e-9:
                        continue
                    for name in FALLBACK_RULES:
                        buckets[(name, entry["class"])].append(
                            entry["rule_hwp"][name] - entry["hancom_hwp"])
    rows = []
    for (name, klass), deltas in buckets.items():
        rows.append({
            "rule": name, "class": klass, "n": len(deltas),
            "median": statistics.median(deltas),
            "median_abs": statistics.median(abs(d) for d in deltas),
            "within_tol": sum(1 for d in deltas if abs(d) <= TOL_HWP),
        })
    rows.sort(key=lambda row: (FALLBACK_RULES.index(row["rule"]), -row["n"]))
    return rows


def embedded_font_report(pdf_path):
    """What face did Hancom's own exporter EMBED, and is it a substitute?

    The declared name is what the file asks for; the reference PDF says what
    Hancom drew with.  Every Type0 font's ``/BaseFont`` is read (Hancom writes
    a Korean face name into it as CP949 bytes, escaped ``#XX``), and the
    embedded program's own advances are read out of its ``hmtx``.  A subset
    Hancom embeds carries no ``name`` table, so the program cannot name
    itself -- what it CAN say is its units per em and its advances, and a
    substitute betrays itself there: a full-width Korean face advances a
    syllable by exactly 1.000 em, and two faces of different families rarely
    agree on the em they use.
    """
    try:
        import fitz
        from fontTools.ttLib import TTFont
    except ImportError as exc:                      # pragma: no cover
        return [{"error": f"{exc}"}]
    doc = fitz.open(str(pdf_path))
    xrefs = {}
    for page in range(doc.page_count):
        for font in doc.get_page_fonts(page, full=True):
            xrefs.setdefault(font[0], font[3])
    rows = []
    for xref, listed in sorted(xrefs.items()):
        obj = doc.xref_object(xref, compressed=True)
        match = re.search(r"/BaseFont\s*/([^\s/>\]]+)", obj)
        raw = match.group(1) if match else (listed or "?")
        name = re.sub(r"#([0-9A-Fa-f]{2})",
                      lambda hit: chr(int(hit.group(1), 16)), raw)
        row = {"xref": xref, "base_font": readable_font_name(name),
               "type3": "/Type3" in obj, "upem": None, "hangul_em": None,
               "advances_em": None}
        if not row["type3"]:
            try:
                data = doc.extract_font(xref)[3]
                face = TTFont(io.BytesIO(data), fontNumber=0, lazy=True,
                              ignoreDecompileErrors=True)
                upem = face["head"].unitsPerEm
                widths = sorted({adv for adv, _lsb
                                 in face["hmtx"].metrics.values()})
                row["upem"] = upem
                row["advances_em"] = [round(w / upem, 4) for w in widths[:8]]
                row["hangul_em"] = (1.0 if upem in widths else None)
                row["named"] = "name" in face.reader.keys()
            except Exception as exc:                # pragma: no cover
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    doc.close()
    return rows


class RuleRenderer(own_render.OwnRenderer):
    """The renderer with one candidate substituted-face advance rule in it.

    The rule goes in at ``_advance_hwp`` and ``_half_cell_hwp`` -- the two
    places every advance the line breaker sees comes out of -- so a break
    test run through this class is the real breaker on real inputs, not a
    reconstruction of one.
    """

    def __init__(self, *args, rule=None, oracle=None, **kwargs):
        self.rule = rule
        self.rule_oracle = oracle or {}
        super().__init__(*args, **kwargs)

    def _substituted(self, cid, slot):
        bold = bool(self._charpr(cid).get("bold"))
        return self._face_source(cid, slot, bold) != "installed"

    def _advance_hwp(self, font, chunk, cid, slot, pt, ratio):
        base = super()._advance_hwp(font, chunk, cid, slot, pt, ratio)
        if not self.rule or self.rule == "current" or not chunk:
            return base
        if not self._substituted(cid, slot):
            return base
        cell = pt * HWPUNIT_PER_PT * ratio / 100.0
        if cell <= 0:
            return base
        if not any(is_full_width(ch) for ch in chunk):
            # Nothing in this chunk is a full cell; the whole kerned
            # measurement stands, quantised as one where the rule quantises.
            if self.rule == "cell":
                return base
            return quantise_grid(base / cell * quantise_grid(cell, "round"),
                                 self.rule.split(":", 1)[1]
                                 if self.rule.startswith("cell+grid:")
                                 else "round")
        # A mixed chunk is measured character by character.  It costs the
        # face's kern table, which no Korean full-width run has anyway.
        declared = declared_face(self, cid, slot)
        total = 0.0
        for ch in chunk:
            per = self._em_width(font, ch) * pt * HWPUNIT_PER_PT * ratio / 100.0
            oracle_em = self.rule_oracle.get((declared, char_class(ch)))
            total += rule_advance(self.rule, per, ch, cell, oracle_em)
        return total

    def _half_cell_hwp(self, cid, rel_sz, ratio):
        base = super()._half_cell_hwp(cid, rel_sz, ratio)
        if not self.rule or self.rule == "current" or self.rule == "cell":
            return base
        if not self._substituted(cid, script_slot(" ")):
            return base
        pt = (self._charpr(cid).get("height_pt") or 10.0) * rel_sz / 100.0
        cell = pt * HWPUNIT_PER_PT * ratio / 100.0
        if cell <= 0:
            return base
        return rule_advance(self.rule, base, " ", cell, None)


class BreakTestRenderer(RuleRenderer):
    """``RuleRenderer``, recording every ``compute_lines`` call it makes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.break_calls = {}

    def compute_lines(self, draw, para, column_hwp, from_char=0, from_line=0):
        lines = super().compute_lines(draw, para, column_hwp,
                                      from_char=from_char, from_line=from_line)
        address = self.paragraph_index.get(id(para.el))
        if address is not None and from_char == 0:
            self.break_calls.setdefault(
                address, [line["end"] for line in lines[:-1]])
        return lines


def cache_break_positions(para, cells):
    """The cache's own break positions, in our character index."""
    out = []
    for _lo, hi in lineseg_vs_pdf.cached_split(para, cells)[:-1]:
        cut = len(para.chars)
        for index in range(len(para.chars)):
            if para.cell_start[index] >= hi:
                cut = index
                break
        out.append(cut)
    return out


def break_test(hwpx_path, rule, oracle=None, repo_root=None, dpi=144):
    """Does ``rule`` reproduce the cached break positions?  Per paragraph.

    Every paragraph the cache broke -- top level and in cells alike -- is
    read, its ``hp:lineseg`` break positions taken as truth, and our own
    breaker run against the column its container actually gave it.  A
    paragraph is counted ``substituted`` when any character on it resolves to
    a stand-in face, which is the population the rule is allowed to move;
    every other paragraph is the control and must not move at all.
    """
    renderer = BreakTestRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                                 layout_policy="computed", rule=rule,
                                 oracle=oracle)
    renderer.render()
    rows = []
    for section in renderer.sections:
        for el in section.iter():
            if _local(el.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(el))
            if address is None or address not in renderer.break_calls:
                continue
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            if not para.linesegs or para.objects:
                continue
            cells = lineseg_vs_pdf.character_cells(para)
            if _iattr(para.linesegs[-1], "textpos") > len(cells):
                continue
            substituted = False
            for ch, cid in para.chars:
                if ch == own_render.OBJECT_SLOT:
                    continue
                slot = script_slot(ch)
                bold = bool(renderer._charpr(cid).get("bold"))
                if renderer._face_source(cid, slot, bold) != "installed":
                    substituted = True
                    break
            rows.append({
                "address": address,
                "cached_lines": len(para.linesegs),
                "substituted": substituted,
                "cache_breaks": cache_break_positions(para, cells),
                "our_breaks": renderer.break_calls[address],
            })
    return rows


def break_summary(rows):
    """``matched / total`` per population, and multi-line only."""
    out = {}
    for group, want in (("substituted", True), ("installed", False)):
        picked = [row for row in rows if row["substituted"] is want]
        multi = [row for row in picked if row["cached_lines"] > 1]
        out[group] = {
            "paragraphs": len(picked),
            "matched": sum(1 for row in picked
                           if row["cache_breaks"] == row["our_breaks"]),
            "multiline": len(multi),
            "multiline_matched": sum(1 for row in multi
                                     if row["cache_breaks"] == row["our_breaks"]),
        }
    return out


# -- the cache's own one-sided score --------------------------------------

def fit_scoreboard(hwpx_path, repo_root=None):
    """How many cached lines does our own measurement say do not fit?

    #265 recorded that the cache "cannot score a candidate advance, because
    ``hp:lineseg`` records where a line STARTS, not how wide its text was".
    It records something else that does the job in ONE direction:
    ``@horzsize`` is the box Hancom fitted that line into.  Hancom put those
    characters on that line, so our width for them MUST be no greater than
    that box.  A cached line our metrics call too wide is a proven
    over-measurement, no reference render needed, and the count of them is a
    score a candidate advance rule can be graded by.

    It is one-sided on purpose.  A line our metrics call NARROW enough may
    still be one we would break differently, because the break also depends
    on the next word and on ``@condense``; only the overflow direction is a
    proof.  Every paragraph with a lineseg is read, cells included, which is
    where three quarters of this corpus's text lives.

    Returns one row per cached line under the current rule and under the
    1/600 inch device-grid rule.
    """
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    metrics = OurMetrics(renderer)
    rows = []
    for section in renderer.sections:
        for el in section.iter():
            if _local(el.tag) != "p":
                continue
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            if not para.linesegs or para.objects:
                continue
            cells = lineseg_vs_pdf.character_cells(para)
            if _iattr(para.linesegs[-1], "textpos") > len(cells):
                continue
            for index, (lo, hi) in enumerate(
                    lineseg_vs_pdf.cached_split(para, cells)):
                ours = _para_chars_in_cells(para, lo, hi)
                if not ours or any(ch == "\t" for _p, ch, _c in ours):
                    continue
                first = ours[0][0]
                last = ours[-1][0] + 1
                visible = last
                while visible > first and \
                        para.chars[visible - 1][0] in own_render.SPACE_CHARS:
                    visible -= 1
                if visible <= first:
                    continue
                horzsize = _iattr(para.linesegs[index], "horzsize")
                if horzsize <= 0:
                    continue
                now = renderer.span_width(None, para, first, visible)
                grid = 0.0
                for pos in range(first, visible):
                    run = metrics.run(*para.chars[pos])
                    grid += run["grid_advance_hwp"] + run["grid_gap_hwp"]
                run = metrics.run(*para.chars[visible - 1])
                grid -= run["grid_gap_hwp"]
                rows.append({
                    "address": renderer.paragraph_index.get(id(el)),
                    "line": index, "horzsize": horzsize,
                    "now_hwp": now, "grid_hwp": grid,
                    "now_over": now > horzsize,
                    "grid_over": grid > horzsize,
                })
    return rows


def break_scoreboard(hwpx_path, dpi=144, repo_root=None):
    """Does our breaker put the line ends where the cache put them?

    ``fit_scoreboard`` is one-sided -- it can only prove an over-measurement.
    This is the two-sided score and it is the one a candidate advance rule
    has to pass: for every paragraph the cache broke into more than one line,
    the cached break positions in ``chars`` index against the ones
    ``compute_lines`` produced on the real column.  A paragraph counts as
    reproduced only when every break matches, so a rule that fixes one break
    and breaks another scores worse, not the same.

    Split by whether EVERY face on the paragraph is the declared, installed
    one, because that is the only half of the corpus this slice may move:
    a paragraph carrying a stand-in is the fallback slice's population and a
    change that moved it would be measuring the other worker's subject.
    """
    renderer = BreakRecordingRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                                      layout_policy="computed")
    renderer.render()
    metrics = OurMetrics(renderer)
    rows = []
    for section in renderer.sections:
        for el in section.iter():
            if _local(el.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(el))
            call = renderer.break_calls.get(address)
            if call is None:
                continue
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            if len(para.linesegs) < 2 or para.objects:
                continue
            cells = lineseg_vs_pdf.character_cells(para)
            if _iattr(para.linesegs[-1], "textpos") > len(cells):
                continue
            spans = lineseg_vs_pdf.cached_split(para, cells)
            cache_breaks = []
            for _lo, hi in spans[:-1]:
                cut = len(para.chars)
                for index in range(len(para.chars)):
                    if para.cell_start[index] >= hi:
                        cut = index
                        break
                cache_breaks.append(cut)
            computed = [end for _start, end in call["spans"][:-1]]
            sources = {metrics.run(ch, cid)["source"]
                       for ch, cid in para.chars}
            rows.append({
                "address": address,
                "installed": sources <= {"installed"},
                "cache_breaks": cache_breaks,
                "computed_breaks": computed,
                "match": cache_breaks == computed,
            })
    return rows


def format_breaks(rows_by_form):
    out = ["", "cached break positions reproduced by our own breaker, "
                "multi-line paragraphs", ""]
    out.append(f"{'form':<14} {'installed ¶':>12} {'match':>7} "
               f"{'other ¶':>9} {'match':>7}")
    out.append("-" * 54)
    tot = [0, 0, 0, 0]
    for stem, rows in rows_by_form:
        inst = [r for r in rows if r["installed"]]
        rest = [r for r in rows if not r["installed"]]
        hit_i = sum(1 for r in inst if r["match"])
        hit_r = sum(1 for r in rest if r["match"])
        tot[0] += len(inst)
        tot[1] += hit_i
        tot[2] += len(rest)
        tot[3] += hit_r
        out.append(f"{stem[:14]:<14} {len(inst):>12} {hit_i:>7} "
                   f"{len(rest):>9} {hit_r:>7}")
    out.append("-" * 54)
    share = f"{tot[1] / tot[0]:.4f}" if tot[0] else "n/a"
    out.append(f"{'all':<14} {tot[0]:>12} {tot[1]:>7} {tot[2]:>9} {tot[3]:>7}"
               f"   installed share {share}")
    return "\n".join(out)


def format_fit(rows_by_form):
    out = ["", "cached lines our own metrics say do NOT fit their own "
                "hp:lineseg@horzsize", "(Hancom fitted them, so every one is "
                "a proven over-measurement -- one-sided, no PDF)", ""]
    out.append(f"{'form':<36} {'lines':>7} {'over now':>9} {'over grid':>10} "
               f"{'worst fill':>11}")
    out.append("-" * 78)
    total = now_over = grid_over = 0
    for stem, rows in rows_by_form:
        worst = max((row["now_hwp"] / row["horzsize"] for row in rows),
                    default=0.0)
        a = sum(1 for row in rows if row["now_over"])
        b = sum(1 for row in rows if row["grid_over"])
        total += len(rows)
        now_over += a
        grid_over += b
        out.append(f"{stem[:36]:<36} {len(rows):>7} {a:>9} {b:>10} "
                   f"{worst:>11.4f}")
    out.append("-" * 78)
    out.append(f"{'all forms':<36} {total:>7} {now_over:>9} {grid_over:>10}")
    return "\n".join(out)


# -- the seven carriers --------------------------------------------------

class BreakRecordingRenderer(own_render.OwnRenderer):
    """The renderer, recording every ``compute_lines`` call it makes.

    The column width a paragraph is broken against comes from its container --
    the body box for a top-level paragraph, the cell box minus its margins for
    one in a table -- and reproducing that outside the renderer would be a
    second model of the thing being measured.  So the real call is recorded
    instead, keyed by the paragraph's own ``paragraph_index`` address.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.break_calls = {}

    def compute_lines(self, draw, para, column_hwp, from_char=0, from_line=0):
        lines = super().compute_lines(draw, para, column_hwp,
                                      from_char=from_char, from_line=from_line)
        address = self.paragraph_index.get(id(para.el))
        if address is not None and from_char == 0:
            self.break_calls.setdefault(address, {
                "column_hwp": column_hwp,
                "spans": [(line["start"], line["end"]) for line in lines],
                "widths": [line["width_hwpunit"] for line in lines],
                "horzsize": [line["horzsize"] for line in lines],
            })
        return lines


def carrier_report(hwpx_path, pdf_path, addresses, dpi=144, repo_root=None,
                   keep_text=True):
    """Line by line for one form's carriers: cache break, our break, delta."""
    renderer = BreakRecordingRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                                      layout_policy="computed")
    renderer.render()
    metrics = OurMetrics(renderer)
    pdf = read_pdf_chars(pdf_path)
    by_address = {}
    for section in renderer.sections:
        for el in section.iter():
            if _local(el.tag) == "p":
                by_address[renderer.paragraph_index[id(el)]] = el
    out = []
    for address in addresses:
        el = by_address.get(address)
        if el is None:
            out.append({"address": address, "reason": "not_found"})
            continue
        para = own_render.Paragraph(el, renderer.defs["para_pr"])
        cells = lineseg_vs_pdf.character_cells(para)
        call = renderer.break_calls.get(address)
        spans = lineseg_vs_pdf.cached_split(para, cells)
        # The cache's break, expressed in the same character index our own
        # spans use: the first character seated at or after the cell the next
        # lineseg starts at.
        cache_breaks = []
        for _lo, hi in spans[:-1]:
            cut = len(para.chars)
            for index in range(len(para.chars)):
                if para.cell_start[index] >= hi:
                    cut = index
                    break
            cache_breaks.append(cut)
        target = lineseg_vs_pdf.normalise(
            lineseg_vs_pdf.paragraph_text(cells))
        hit = pdf.find_run(target, 0)
        pdf_lines = None
        pdf_source = "none"
        if hit is not None:
            lo, hi, _relaxed, _ooo = hit
            pdf_lines = merge_lines_with_boxes(pdf.lines[lo:hi])
            pdf_source = "pdf_text_match"
        record = {
            "address": address,
            "cached_lines": len(para.linesegs),
            "computed_lines": len(call["spans"]) if call else None,
            "column_hwp": call["column_hwp"] if call else None,
            "cache_breaks": cache_breaks,
            "computed_breaks": ([end for _s, end in call["spans"][:-1]]
                                if call else None),
            "pdf_source": pdf_source,
            "pdf_lines": len(pdf_lines) if pdf_lines else 0,
            "lines": [],
        }
        if keep_text:
            record["text"] = "".join(ch for ch, _cid in para.chars)
        # Line by line, on the CACHE's split: how wide we make Hancom's own
        # line, how wide its box is, and -- where the PDF paired -- how wide
        # Hancom actually drew it.
        for index, (lo, hi) in enumerate(spans):
            ours = _para_chars_in_cells(para, lo, hi)
            if not ours:
                continue
            first = ours[0][0]
            last = ours[-1][0] + 1
            # The breaker's own quantity: trailing whitespace hangs outside
            # the box rather than forcing a break, so it is not in the width
            # a line is fitted by (``compute_lines.width_hwpunit``).
            visible = last
            while visible > first and \
                    para.chars[visible - 1][0] in own_render.SPACE_CHARS:
                visible -= 1
            width = renderer.span_width(None, para, first, visible)
            grid_width = 0.0
            for pos in range(first, visible):
                run = metrics.run(*para.chars[pos])
                grid_width += run["grid_advance_hwp"] + run["grid_gap_hwp"]
            if visible > first:
                run = metrics.run(*para.chars[visible - 1])
                grid_width -= run["grid_gap_hwp"]
            horzsize = _iattr(para.linesegs[index], "horzsize")
            entry = {
                "line": index,
                "cache_span": [first, last],
                "visible_end": visible,
                "ours_width_hwp": width,
                "grid_width_hwp": grid_width,
                "horzsize": horzsize,
                "overflow_hwp": width - horzsize,
                "grid_overflow_hwp": grid_width - horzsize,
                "fill": width / horzsize if horzsize else None,
                "grid_fill": grid_width / horzsize if horzsize else None,
            }
            if pdf_lines and index < len(pdf_lines):
                boxes = pdf_lines[index]["boxes"]
                pairs, n_ours, n_theirs, _chars, segments = analyse_line(
                    ours, boxes, metrics, keep_text)
                contributions = defaultdict(float)
                for seg in segments:
                    contributions[(seg["resolved"], seg["class"],
                                   seg["chars"] > 1)] += (seg["ours_hwp"]
                                                          - seg["hancom_hwp"])
                worst = max(contributions.items(),
                            key=lambda kv: abs(kv[1]), default=None)
                entry.update({
                    "aligned": len(pairs),
                    "fully_aligned": len(pairs) == n_ours == n_theirs,
                    "undrawn_chars": n_ours - len(pairs),
                    "hancom_span_hwp": sum(s["hancom_hwp"] for s in segments),
                    "ours_span_hwp": sum(s["ours_hwp"] for s in segments),
                    "contributions": {
                        f"{k[0]}/{k[1]}{'+undrawn' if k[2] else ''}": v
                        for k, v in sorted(contributions.items(),
                                           key=lambda kv: -abs(kv[1]))[:5]},
                    "largest_contributor": (
                        f"{worst[0][0]}/{worst[0][1]}"
                        f"{'+undrawn' if worst[0][2] else ''}"
                        if worst else None),
                    "largest_contribution_hwp": worst[1] if worst else None,
                })
            record["lines"].append(entry)
        out.append(record)
    return out


# -- output --------------------------------------------------------------

def format_runs(rows, undrawn, zero_hancom, limit=20):
    out = ["", "advance ratio ours/Hancom, per (declared -> resolved, size, "
                "spacing %, class)",
           "(one anchored character against the next, same text-showing run; "
           f"{undrawn} of our characters never reach the PDF as a glyph at "
           f"all -- Hancom moves the pen instead -- and {zero_hancom} scored "
           "a zero advance)", ""]
    out.append(f"{'resolved (ours)':<26} {'pdf font (Hancom)':<24} {'pt':>5} "
               f"{'sp':>4} {'class':<9} {'n':>6} {'median':>8} {'p10':>8} "
               f"{'p90':>8} {'d_med':>8}")
    out.append("-" * 118)
    for row in rows[:limit]:
        out.append(
            f"{row['resolved'][:26]:<26} "
            f"{str(row['pdf_font'])[:24]:<24} "
            f"{row['size_pt']:>5} {row['spacing']:>4} {row['class']:<9} "
            f"{row['n']:>6} {row['ratio_median']:>8.4f} "
            f"{row['ratio_p10']:>8.4f} {row['ratio_p90']:>8.4f} "
            f"{row['delta_median_hwp']:>8.2f}")
    if len(rows) > limit:
        out.append(f"... and {len(rows) - limit} more runs")
    return "\n".join(out)


def format_classes(rows):
    out = ["", "the same ratio by character class alone", ""]
    out.append(f"{'class':<10} {'n':>7} {'median':>9} {'p10':>9} {'p90':>9} "
               f"{'d_med':>9}")
    out.append("-" * 56)
    for row in rows:
        out.append(f"{row['class']:<10} {row['n']:>7} "
                   f"{row['ratio_median']:>9.4f} {row['ratio_p10']:>9.4f} "
                   f"{row['ratio_p90']:>9.4f} "
                   f"{row['delta_median_hwp']:>9.2f}")
    return "\n".join(out)


def format_punct(rows, limit=40):
    out = ["", "punctuation advance per CODE POINT, installed faces only "
                "(em = advance / declared cell)", ""]
    if not rows:
        out.append("  (no punctuation advance is anchored on an installed "
                   "face in this run)")
        return "\n".join(out)
    out.append(f"{'cp':<8} {'ch':<3} {'class':<9} {'slot':<8} "
               f"{'n':>5} {'hancom':>8} {'h_em':>7} {'ours':>8} {'o_em':>7} "
               f"{'ratio':>7} {'sum d':>9}  {'resolved':<26}")
    out.append("-" * 118)
    for row in rows[:limit]:
        out.append(f"{row['codepoint'] or '?':<8} {row['char'] or '?':<3} "
                   f"{row['class']:<9} {row['slot']:<8} {row['n']:>5} "
                   f"{row['hancom_median_hwp']:>8.1f} {row['hancom_em']:>7.4f} "
                   f"{row['ours_median_hwp']:>8.1f} {row['ours_em']:>7.4f} "
                   f"{row['ratio']:>7.4f} {row['total_delta_hwp']:>9.1f}  "
                   f"{row['resolved'][:26]:<26}")
    if len(rows) > limit:
        out.append(f"  ... {len(rows) - limit} further code points")
    out.append(f"  total over-measure on installed punctuation: "
               f"{sum(r['total_delta_hwp'] for r in rows):+.1f} HWPUNIT over "
               f"{sum(r['n'] for r in rows)} advances")
    return "\n".join(out)


def format_gaps(rows, limit=24):
    out = ["", "inter-class boundary, installed faces only: Hancom's pen "
                "move minus the same class's same-class baseline, in em", ""]
    if not rows:
        out.append("  (no inter-class boundary is anchored on an installed "
                   "face in this run)")
        return "\n".join(out)
    flagged = [row for row in rows
               if row["autoSpaceEAsianEng"] is not None
               or row["autoSpaceEAsianNum"] is not None]
    out.append(f"{'from':<9} {'to':<9} {'eng':>6} {'num':>6} {'n':>6} "
               f"{'hancom em':>10} {'ours em':>9} {'delta em':>9}")
    out.append("-" * 70)
    for row in rows[:limit]:
        eng = "-" if row["autoSpaceEAsianEng"] is None \
            else row["autoSpaceEAsianEng"]
        num = "-" if row["autoSpaceEAsianNum"] is None \
            else row["autoSpaceEAsianNum"]
        out.append(f"{row['from']:<9} {row['to']:<9} {eng:>6} {num:>6} "
                   f"{row['n']:>6} {row['hancom_gap_em']:>10.4f} "
                   f"{row['ours_gap_em']:>9.4f} {row['gap_delta_em']:>9.4f}")
    if not flagged:
        out.append("  `-` in both flag columns: hp:paraPr declares NEITHER "
                   "autoSpaceEAsianEng NOR autoSpaceEAsianNum anywhere in "
                   "this run, so the split has one bucket and nothing here "
                   "is evidence about what either flag does.")
    return "\n".join(out)


def format_pdf_sizes(rows, limit=18):
    out = ["", "the reference PDF's own font size against 1/600 inch "
                "(no metric of ours enters this)", ""]
    on = sum(1 for row in rows if row["on_grid"])
    out.append(f"{'declared':>9} {'pdf':>9} {'1/600in':>9} {'ok':>3}  "
               f"{'pdf font':<28}")
    out.append("-" * 64)
    for row in rows[:limit]:
        out.append(f"{row['declared_pt']:>9} {row['pdf_pt']:>9} "
                   f"{row['grid_pt']:>9} "
                   f"{'yes' if row['on_grid'] else 'NO':>3}  "
                   f"{str(row['pdf_font'])[:28]:<28}")
    if len(rows) > limit:
        out.append(f"... and {len(rows) - limit} more")
    out.append(f"on the 1/600 inch grid: {on}/{len(rows)} "
               f"(declared size, PDF font) sizes")
    return "\n".join(out)


def format_grids(residual, rounding, line_stats, counts):
    out = ["", "paired lines: "
           + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
           "", "is HANCOM on a grid?  (share of its own per-character "
                "advances within tol of a multiple)", ""]
    out.append(f"{'grid':<30} {'step':>9} {'on grid':>9} {'share':>8} "
               f"{'chance':>8}")
    out.append("-" * 68)
    for row in residual:
        out.append(f"{row['grid']:<30} {row['step_hwp']:>9.4f} "
                   f"{row['on_grid']:>9} "
                   f"{(row['share'] or 0) * 100:>7.2f}% "
                   f"{row['expected_by_chance'] * 100:>7.2f}%")
    out += ["", "does quantising OUR advances reproduce Hancom's per-line "
                f"width?  (exact = within {TOL_HWP:g} HWPUNIT)", ""]
    out.append(f"{'grid':<30} {'step':>9} {'exact/paired':>16} "
               f"{'|delta| med':>12} {'delta med':>11}")
    out.append("-" * 82)
    for row in rounding:
        if row["median_abs_hwp"] is None:
            out.append(f"{row['grid']:<30} (no comparable line)")
            continue
        out.append(f"{row['grid']:<30} "
                   f"{(row['step_hwp'] if row['step_hwp'] else 0):>9.4f} "
                   f"{row['exact']:>7}/{row['paired']:<8} "
                   f"{row['median_abs_hwp']:>12.2f} "
                   f"{row['median_hwp']:>11.2f}")
    out += ["", "per-line width delta, ours - Hancom, HWPUNIT", ""]
    out.append(f"{'lines':<22} {'n':>6} {'median':>9} {'|med|':>9} "
               f"{'p10':>10} {'p90':>10} {'|d|<=tol':>9}")
    out.append("-" * 80)
    for label, key in (("all", "all"),
                       ("installed faces only", "installed_only"),
                       ("a face substituted", "substituted")):
        stats = (line_stats or {}).get(key)
        if not stats:
            out.append(f"{label:<22} (none)")
            continue
        out.append(f"{label:<22} {stats['n']:>6} {stats['median']:>9.2f} "
                   f"{stats['median_abs']:>9.2f} {stats['p10']:>10.2f} "
                   f"{stats['p90']:>10.2f} {stats['within_tol']:>9}")
    return "\n".join(out)


def format_carriers(carriers):
    out = ["", "the seven carriers of #265, line by line", ""]
    for stem, records in carriers:
        for record in records:
            if record.get("reason"):
                out.append(f"  {stem} #{record['address']}: "
                           f"{record['reason']}")
                continue
            cached_box = record["lines"][0]["horzsize"] if record["lines"] \
                else None
            column = record["column_hwp"]
            out.append(
                f"  {stem} #{record['address']}: cache "
                f"{record['cached_lines']} lines, computed "
                f"{record['computed_lines']}, pdf {record['pdf_lines']} "
                f"({record['pdf_source']})")
            out.append(
                f"      our column {column} vs the cache's own horzsize "
                f"{cached_box}"
                + (f"  (d {column - cached_box:+d} -- the BOX differs, not "
                   f"only the text)" if cached_box and column
                   and column != cached_box else ""))
            out.append(f"      cache breaks at {record['cache_breaks']}, "
                       f"ours at {record['computed_breaks']}")
            for line in record["lines"]:
                head = (f"      line {line['line']}: chars "
                        f"{line['cache_span'][0]}..{line['cache_span'][1]}, "
                        f"ours {line['ours_width_hwp']:.0f} / box "
                        f"{line['horzsize']} = {line['fill']:.4f}"
                        f", on 1/600in grid {line['grid_width_hwp']:.0f} "
                        f"= {line['grid_fill']:.4f}"
                        if line["fill"] else "")
                if "hancom_span_hwp" in line:
                    head += (f", anchored hancom "
                             f"{line['hancom_span_hwp']:.0f} vs ours "
                             f"{line['ours_span_hwp']:.0f} "
                             f"(d {line['ours_span_hwp'] - line['hancom_span_hwp']:+.0f})")
                out.append(head)
                if line.get("largest_contributor"):
                    out.append(f"          largest: "
                               f"{line['largest_contributor']} "
                               f"{line['largest_contribution_hwp']:+.1f}")
    return "\n".join(out)


def format_fullwidth_cells(rows, limit=12):
    out = ["", "the full-width advance: MEAN against MODAL, per (face, size)",
           "(the 1/600 inch grid is on the pen POSITION, so one advance is "
           "the cell +-1 unit and a run of them is the cell exactly)", ""]
    out.append(f"{'src':<10} {'pdf font':<14} {'pt':>6} {'n':>6} {'cell':>8} "
               f"{'mean':>9} {'median':>9} {'grid cell':>10} "
               f"{'mean/cell':>10}  units")
    out.append("-" * 116)
    for row in rows[:limit]:
        units = ", ".join(f"{unit}x{count}"
                          for unit, count in list(row["units"].items())[:4])
        out.append(f"{str(row['source'])[:10]:<10} "
                   f"{str(row['pdf_font'])[:14]:<14} {row['size_pt']:>6.2f} "
                   f"{row['n']:>6} {row['cell_hwp']:>8.1f} "
                   f"{row['mean_hwp']:>9.2f} {row['median_hwp']:>9.2f} "
                   f"{row['grid_cell_hwp']:>10.1f} "
                   f"{row['mean_over_cell']:>10.4f}  {units}")
    return "\n".join(out)


def format_fallback_rules(rows, class_rows, em_rows, embedded, breaks):
    """The #280 report: what a substituted face should advance by."""
    out = ["", "=" * 100, "SUBSTITUTED-FACE ADVANCE RULES (#280)", "=" * 100,
           "", "what Hancom's own exporter EMBEDDED, per reference",
           "(a subset carries no name table, so the program cannot name "
           "itself; its em and its advances can)", ""]
    out.append(f"{'/BaseFont':<26} {'kind':<7} {'upem':>6} {'names itself':<13} "
               f"{'refs':>5} {'distinct advances, em':<38}")
    out.append("-" * 104)
    seen = {}
    for _stem, faces in embedded:
        for face in faces:
            key = (str(face.get("base_font")), face.get("upem"),
                   str(face.get("advances_em")))
            seen[key] = (seen.get(key, (0, face))[0] + 1, face)
    for (_name, _upem, _adv), (count, face) in sorted(
            seen.items(), key=lambda kv: (-kv[1][0], kv[0][0])):
        kind = "Type3" if face["type3"] else "Type0"
        named = ("-" if face["type3"]
                 else ("yes" if face.get("named") else "NO (subset)"))
        out.append(f"{str(face['base_font'])[:26]:<26} {kind:<7} "
                   f"{str(face['upem'] or '-'):>6} {named:<13} {count:>5} "
                   f"{str(face.get('advances_em') or '-')[:38]:<38}")
    out += ["", "Hancom's em against the stand-in's, per (declared face, "
                "class), both over the run's declared cell",
            "(on_grid = the share of Hancom's advances that land on a whole "
            "1/600 inch)", ""]
    out.append(f"{'src':<11} {'declared':<22} {'resolved (ours)':<26} "
               f"{'class':<9} {'n':>6} {'hancom em':>10} {'ours em':>9} "
               f"{'on grid':>8}")
    out.append("-" * 108)
    for row in em_rows[:26]:
        out.append(f"{str(row['source'])[:11]:<11} "
                   f"{str(row['declared'])[:22]:<22} "
                   f"{str(row['resolved'])[:26]:<26} {row['class']:<9} "
                   f"{row['n']:>6} {row['hancom_em']:>10.4f} "
                   f"{row['ours_em']:>9.4f} {row['on_grid']:>7.1%}")
    if len(em_rows) > 26:
        out.append(f"... {len(em_rows) - 26} further rows")
    out += ["", "each candidate rule against Hancom's per-line widths "
                "(exact = within 2 HWPUNIT)", ""]
    out.append(f"{'rule':<38} {'subst exact':>12} {'med abs':>9} "
               f"{'median':>9} | {'inst exact':>11} {'med abs':>9} "
               f"{'median':>9}")
    out.append("-" * 104)
    for row in rows:
        sub, inst = row["substituted"], row["installed"]
        out.append(
            f"{row['rule'][:38]:<38} "
            f"{sub['exact']:>5} / {sub['n']:<4} {sub['median_abs']:>9.2f} "
            f"{sub['median']:>9.2f} | "
            f"{inst['exact']:>4} / {inst['n']:<4} {inst['median_abs']:>9.2f} "
            f"{inst['median']:>9.2f}")
    out += ["", "per-character residual on SUBSTITUTED characters, ours minus "
                "Hancom in HWPUNIT", ""]
    out.append(f"{'rule':<38} {'class':<9} {'n':>6} {'median':>9} "
               f"{'med abs':>9} {'within 2':>9}")
    out.append("-" * 84)
    for row in class_rows:
        if row["n"] < 20:
            continue
        out.append(f"{row['rule'][:38]:<38} {row['class']:<9} {row['n']:>6} "
                   f"{row['median']:>9.2f} {row['median_abs']:>9.2f} "
                   f"{row['within_tol']:>9}")
    if breaks:
        out += ["", "the break test: does the rule reproduce hp:lineseg's own "
                    "break positions?", ""]
        out.append(f"{'rule':<38} {'substituted ¶':>14} {'multi-line':>12} "
                   f"| {'installed ¶':>13} {'multi-line':>12}")
        out.append("-" * 98)
        for name, summary, _per_form in breaks:
            sub, inst = summary["substituted"], summary["installed"]
            out.append(
                f"{name[:38]:<38} "
                f"{sub['matched']:>6} / {sub['paragraphs']:<5} "
                f"{sub['multiline_matched']:>5} / {sub['multiline']:<4} | "
                f"{inst['matched']:>5} / {inst['paragraphs']:<5} "
                f"{inst['multiline_matched']:>5} / {inst['multiline']:<4}")
        out += ["", "the same test per form: substituted multi-line "
                    "paragraphs whose break positions match the cache", ""]
        forms = [stem for stem, _s in breaks[0][2]]
        head = f"{'rule':<38}" + "".join(f" {stem.split('-')[0][:8]:>9}"
                                         for stem in forms)
        out.append(head)
        out.append("-" * len(head))
        for name, _summary, per_form in breaks:
            cells = "".join(
                f" {s['substituted']['multiline_matched']:>4}/"
                f"{s['substituted']['multiline']:<4}"
                for _stem, s in per_form)
            out.append(f"{name[:38]:<38}{cells}")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Our glyph advances against Hancom's PDF glyph positions")
    parser.add_argument("pair", nargs="*", type=Path, metavar="HWPX PDF",
                        help="a document and its reference PDF")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form with a reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--no-text", action="store_true",
                        help="omit document text from the report")
    parser.add_argument("--dpi", type=int, default=144,
                        help="dpi the carrier pass renders at (the advances "
                             "themselves are dpi-free; see "
                             "LAYOUT_REFERENCE_PX)")
    parser.add_argument("--runs", type=int, default=20,
                        help="how many run rows to print")
    parser.add_argument("--no-carriers", action="store_true",
                        help="skip the #265 carrier pass")
    parser.add_argument("--no-fit", action="store_true",
                        help="skip the cache-only overflow scoreboard")
    parser.add_argument("--punct", action="store_true",
                        help="the punctuation pass: per code point and per "
                             "inter-class boundary, INSTALLED faces only, "
                             "plus the candidate-rule scoreboard")
    parser.add_argument("--fallback-rules", action="store_true",
                        help="score candidate advance rules for a run whose "
                             "declared face is not installed (#280), and run "
                             "the cached-break test for each")
    parser.add_argument("--no-break-test", action="store_true",
                        help="with --fallback-rules, skip the break test "
                             "(it renders the corpus once per rule)")
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
        targets.extend(lineseg_vs_pdf.corpus_targets(repo_root))
    if not targets:
        build_parser().error("give a document and a reference, or --corpus")
    keep_text = not args.no_text
    reports = []
    for hwpx, pdf in targets:
        reports.append(probe_document(hwpx, pdf, repo_root=repo_root,
                                      keep_text=keep_text))
    oracle = None
    if args.fallback_rules:
        # The oracle rule needs Hancom's own per-class em before it can be
        # scored, so the pass that scores it is a SECOND one over the same
        # documents with the table in hand.  Every other rule is derived and
        # gives the same answer in both passes.
        oracle = latin_oracle(reports)
        reports = [probe_document(hwpx, pdf, repo_root=repo_root,
                                  keep_text=keep_text, oracle=oracle)
                   for hwpx, pdf in targets]
    rows, undrawn, zero_hancom = run_table(reports)
    classes = class_table(reports)
    residual = grid_residual_table(reports)
    rounding = rounding_table(reports)
    line_stats = line_delta_stats(reports)
    counts = comparability_counts(reports)
    sizes = pdf_size_table(reports)
    puncts = punct_char_table(reports) if args.punct else []
    gaps = gap_table(reports) if args.punct else []
    print(format_runs(rows, undrawn, zero_hancom, limit=args.runs))
    print(format_classes(classes))
    if args.punct:
        print(format_punct(puncts))
        print(format_gaps(gaps))
    print(format_pdf_sizes(sizes))
    print(format_grids(residual, rounding, line_stats, counts))
    breaks = []
    if args.punct:
        for hwpx, _pdf in targets:
            breaks.append((Path(hwpx).stem,
                           break_scoreboard(hwpx, dpi=args.dpi,
                                            repo_root=repo_root)))
        print(format_breaks(breaks))
    fits = []
    if not args.no_fit:
        for hwpx, _pdf in targets:
            fits.append((Path(hwpx).stem,
                         fit_scoreboard(hwpx, repo_root=repo_root)))
        print(format_fit(fits))
    fallback = None
    if args.fallback_rules:
        rule_rows = fallback_rule_table(reports)
        class_rows = fallback_class_residual(reports)
        em_rows = substituted_em_table(reports)
        cell_rows = fullwidth_cell_table(reports)
        embedded = [(Path(pdf).stem, embedded_font_report(pdf))
                    for _hwpx, pdf in targets]
        breaks = []
        if not args.no_break_test:
            for name in FALLBACK_RULES:
                rows_all = []
                per_form = []
                for hwpx, _pdf in targets:
                    rows = break_test(hwpx, name, oracle=oracle,
                                      repo_root=repo_root, dpi=args.dpi)
                    per_form.append((Path(hwpx).stem, break_summary(rows)))
                    rows_all.extend(rows)
                breaks.append((name, break_summary(rows_all), per_form))
        print(format_fallback_rules(rule_rows, class_rows, em_rows, embedded,
                                    breaks))
        print(format_fullwidth_cells(cell_rows))
        fallback = {
            "rules": rule_rows, "class_residual": class_rows,
            "substituted_em": em_rows, "full_width_cell": cell_rows,
            "embedded_fonts": [{"reference": stem, "faces": faces}
                               for stem, faces in embedded],
            "break_test": [{"rule": name, "summary": summary,
                            "per_form": [{"form": stem, "summary": rows}
                                         for stem, rows in per_form]}
                           for name, summary, per_form in breaks],
            "latin_oracle": {f"{key[0]}|{key[1]}": value
                             for key, value in sorted(
                                 (oracle or {}).items(),
                                 key=lambda kv: str(kv[0]))},
        }
    carriers = []
    if not args.no_carriers:
        for hwpx, pdf in targets:
            addresses = CARRIERS.get(Path(hwpx).stem)
            if not addresses:
                continue
            carriers.append((Path(hwpx).stem,
                             carrier_report(hwpx, pdf, addresses,
                                            dpi=args.dpi, repo_root=repo_root,
                                            keep_text=keep_text)))
        print(format_carriers(carriers))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs": rows,
            "classes": classes,
            "punctuation": puncts,
            "inter_class_gaps": gaps,
            "break_scoreboard": [{"form": stem, "paragraphs": rows}
                                 for stem, rows in breaks],
            "pdf_font_sizes": sizes,
            "hancom_grid_residual": residual,
            "rounding_hypotheses": rounding,
            "line_delta": line_stats,
            "line_comparability": counts,
            "fit_scoreboard": [{"form": stem, "lines": rows}
                               for stem, rows in fits],
            "carriers": [{"form": stem, "paragraphs": records}
                         for stem, records in carriers],
            "documents": reports,
        }
        if fallback is not None:
            payload["fallback_rules"] = fallback
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                        default=_jsonable),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


def _jsonable(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
