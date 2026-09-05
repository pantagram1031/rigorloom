#!/usr/bin/env python3
"""layout_divergence.py — where a computed layout stops agreeing with the cache.

``own_render.py`` can lay a document out two ways: ``--layout-policy cache``
keeps the authoring engine's cached ``hp:lineseg`` boxes, ``--layout-policy
computed`` re-derives every line and every block seat.  The scoreboard prices
the difference as one IoU number per form.  This tool says WHAT the difference
is made of, line by line, so a regression can be attributed to a mechanism
instead of to "computed layout is worse".

    python layout_divergence.py FORM.hwpx --out DIR [--dpi 144] [--no-text]
    python layout_divergence.py --corpus --out DIR [--dpi 144]

Writes ``DIR/<stem>.divergence.json`` and prints a one-line summary; with
``--corpus`` it does that for every form under ``tests/corpus/forms/converted``
and prints a per-form table.

HOW THE TWO RENDERS ARE PAIRED
------------------------------
The sidecar's ``line_boxes`` records carry page and geometry but no identity,
and pairing boxes by proximity — which is what the scoreboard has to do
against a PDF — cannot tell a moved break from a moved line: a line 20 px down
the page pairs with its neighbour and reads as a break error.  So this tool
renders through a subclass that tags every box with the ``address`` of the
paragraph that drew it (own_render's own global ``paragraph_index``: document
order over every ``hp:p``, sections in spine order, table cells included,
counting from 0 — table-cell paragraphs are already distinct members of that
flat namespace, so the index alone addresses a cell) and with that line's
text.  Paragraph identity comes from the XML tree, so it is the SAME under
both policies whatever the layout did.  Within a paragraph, lines are paired
by draw order: nth cache line against nth computed line.

THE CLASSIFICATION RULE
-----------------------
This is #247's rule, restated so it can be re-run.  A paired line is exactly
one of four classes, tested in this order:

* **A — the break moved.**  One side has no nth line at all (the paragraph
  broke into a different number of lines), or the two nth lines carry
  different text.  Different text on the same ordinal IS a different break
  decision; it is the only direct read of the breaker there is.
* **C — the line changed page.**  Same text, different ``page``.  Page comes
  before the vertical test because a box on another page has no meaningful
  ``dy``: its ``y0`` is measured from a different page top.
* **B — same break, different y.**  Same text, same page, ``|dy| >
  --y-tol`` (default 0.01 px, i.e. exact up to the sidecar's 3-decimal
  rounding).  This is the line that sits in the right place across the
  column and the wrong place down the page.
* **agree** — everything else.

A horizontal difference alone does not make a class: #247 has three classes
and this reproduces them.  ``dx`` is still recorded on the first divergent
line of each paragraph so an x-only drift is visible rather than silently
folded into ``agree``.

A paragraph's classes are the union of its lines' classes, which is what
makes the per-form table comparable to #247's: the table counts PARAGRAPHS,
and a paragraph that both re-broke and drifted is counted under A and under
B (and once more in the ``A&B`` column).

ATTRIBUTING CLASS B
-------------------
Most of class B is not its own error.  A paragraph that breaks into one more
computed line than the cache pushes everything below it down by one line
pitch, and every one of those pushed paragraphs is booked class B even though
its own layout is correct.  So this tool also walks the paragraphs of each
page in reading order carrying two running totals over the paragraphs BEFORE
the current one:

* ``upstream_line_delta`` -- the sum of ``computed lines - cache lines``;
* ``expected_dy_px``      -- the sum of that per-paragraph delta times THAT
  paragraph's own line pitch.

A class-B paragraph is then ``B_inherited`` when ``upstream_line_delta`` is
non-zero AND the dy of its first class-B line lands within
``--attribution-tol`` of ``expected_dy_px``; otherwise it is ``B_own``.  The
non-zero guard is not a formality: with nothing re-broken above it the
prediction is exactly 0, and every sub-pixel drift would otherwise read as
"explained by an upstream delta of zero lines".  Where every paragraph on the
page shares one pitch -- the normal case in a body column -- ``expected_dy_px``
IS the simple ``upstream_line_delta x pitch``, and the report carries that
simpler reading too (``simple_expected_px``, ``residual_simple_px``) so the
two can be compared rather than trusted.

A paragraph's **pitch** is the dominant step between the ``y0`` of its
consecutive computed lines on one page.  That step is ``vertsize + spacing``
by own_render's own line-position relation (``vertpos[i] == vertpos[i-1] +
vertsize[i-1] + spacing[i-1]``), so it is the per-line advance, measured off
the render rather than re-derived from the tree.  A paragraph with only one
computed line has no step of its own; it falls back to the same dominant step
over its CACHED lines -- which is that paragraph's own ``hp:lineseg``
``vertsize + spacing`` by the same relation -- and then to the pitch carried
down from the nearest preceding paragraph that had one.

The accumulators reset at every page boundary: a dy is measured from a page
top, so a total carried across one means nothing.

WHAT SITS ABOVE THE FIRST DRIFT ON A PAGE
-----------------------------------------
The attribution above says class B is mostly NOT inherited from a re-break:
on the corpus, 318 of 538 class-B paragraphs have nothing re-broken above
them at all.  If the extra height is not a line, it is added BETWEEN
paragraphs or at a paragraph's bottom, and the paragraph immediately above
the first drift on a page is the only place it can have come from.  So per
page this tool walks the paragraphs in document order, finds the first whose
ordinal-0 line is paired on the same page and whose ``dy`` exceeds
``--y-tol``, and reports its PREDECESSOR: that paragraph's last line under
each policy (the cache's ``vertpos``/``vertsize``/``spacing``, the computed
side's ``y0``/``y1``/pitch), the two candidate bottoms it implies, the gap
between that bottom and the drifting paragraph's first line under both
policies, and the predecessor's own ``hh:paraPr`` — line spacing type and
value, ``hh:margin/prev`` and ``/next``, whether its text is empty, and every
object it carries with that object's extent under both policies.

The population that matters here is the one the A/B/C classification cannot
see.  A paragraph with no characters draws no line box — both render paths
``continue`` on ``not para.chars`` — so it is in neither policy's
``line_boxes``, its line-count delta is 0 either way, and every paragraph
below it is booked ``B_own_no_upstream_rebreak`` however wrong its height is.
For those the report leaves the pixel domain and states the cache's height
(the sum of the paragraph's ``hp:lineseg`` advances) against the flow pass's
(its seat height), whose difference is the drift in the units it was made in.

A paragraph that draws nothing and that the flow pass never seated — the
empty one inside a table cell — is placed on a page by ENCLOSURE: when the
paragraph before it and the paragraph after it in document order are both on
one page, so is it.  A paragraph whose neighbours disagree is left unplaced
rather than guessed at.

``first_drift_predecessors.kinds`` is a histogram over those predecessors
keyed on ``(anchor kind, empty text, line spacing type)``, and
``dominant_kind`` is its tallest bar — the one number that says what kind of
paragraph the drift starts under.

THE SEAT PASS
-------------
The predecessor pass still reads the two renders through their LINE boxes, so
a run of paragraphs that draws no line at all is one opaque step: #252 found
every first-drift predecessor to be inkless, its own height exactly the
cache's (``height_delta_hwp`` 0), and the drifting paragraph below it already
3600 or 5400 HWPUNIT low — the divergence had begun somewhere above, inside
paragraphs the line-box pairing cannot see.  The seat pass leaves the line
domain entirely.

For EVERY top-level ``hp:p`` of every section, in document order, it records
the paragraph's SEAT under both policies:

* under ``cache``, the page ``_render_paragraphs`` drew it on and the
  ``hp:lineseg@vertpos`` of its first cached line, which is the authoring
  engine's own statement of where the paragraph starts, measured from the
  body top;
* under ``computed``, the page and ``top`` of the flow-pass placement
  (``_render_flow_page``'s records), which is the same quantity in the same
  units;

together with each side's advance (cache: the sum of the paragraph's lineseg
``vertsize + spacing``; computed: the flow record's ``height``), its drawn
line count, and the static properties that could explain a difference: every
empty ``hp:run`` with its ``hh:charPr@height``, every inline and anchored
object with its extent, out-margins, ``treatAsChar``, ``flowWithText`` and
``vertRelTo``, and the paragraph's own ``hh:paraPr`` — line spacing type and
value, ``hh:margin/prev`` and ``/next``, ``pageBreakBefore``, ``keepWithNext``,
``keepLines``, ``widowOrphan`` — plus its section, its ``columnBreak`` and
that section's column count.

An inkless paragraph has a seat under both policies, so the pass sees it.

THE DECOMPOSITION
-----------------
Per page (keyed on the CACHE page, which is the reading order the cache
declares), the first paragraph whose seat differs — a different page, or
``|Δtop| > --seat-tol`` HWPUNIT — is reported in full together with the
paragraph immediately before it in document order, and the delta is split
into the three terms it is made of:

    Δtop(this) = Δtop(prev) + Δadvance(prev) + Δgap

where ``gap`` is ``this.top − (prev.top + prev.advance)`` measured separately
under each policy.  The identity is exact by construction — it is the same
number written two ways — and that is the point: it says WHICH of the three
places the height entered.  ``d_prev_top`` means the divergence is older than
this pair and the pass will have reported it higher up the page (or it came
across a page boundary); ``d_prev_advance`` means the predecessor's own height
is measured differently; ``d_gap`` means the space BETWEEN the two paragraphs
is different, which is the inter-paragraph margin channel and nothing else.

``carrier`` is the term with the largest magnitude among those over the
tolerance, and ``single_term`` says whether the other two are both under it,
so a genuinely mixed row is visible rather than rounded to its biggest half.
A pair the terms cannot be computed for is named instead of guessed:
``page_top`` (the page's first seated paragraph is the one that differs),
``page_move`` (the two policies put one of the pair on different pages), or
``no_seat`` (one side never seated it).

``first_seat_divergences.kinds`` is a histogram keyed on
``(predecessor kind, this paragraph's kind, carrier)`` where a kind is the
same ``anchor/empty/lineSpacing`` label the predecessor pass uses.  It is the
one table that says what shape of paragraph pair the divergence starts at and
which term it enters through.

ATTRIBUTING CLASS A
-------------------
For each class-A paragraph the report names its first divergent line's break
cause as far as the two renders can say it cheaply: how many lines each
policy made, how many characters that ordinal carried on each side (so
"computed broke earlier" is readable as a shorter computed line), the drawn
width of the line in px on each side, and the faces of the runs on it --
declared name, the family it resolved to, and whether that resolution was
``installed``, ``bundled`` (the repo's OFL substitute for a Hancom face) or
``system`` (the single machine-dependent fallback).  A class A whose runs all
resolve to a substituted face is a candidate advance-width artefact rather
than a breaking-rule difference; this does not prove which, it makes the
split countable.

WHAT THE NUMBERS ARE NOT
------------------------
Class A is partly a font-substitution artefact on this corpus — the forms
name Hancom faces this machine resolves to bundled substitutes with different
advances — so an A count mixes breaking rules with metrics.  And every number
here is 144 dpi and this machine's font stack unless ``--dpi`` says otherwise.

PRIVACY
-------
The JSON carries up to 12 characters of each divergent line's text, which is
document content.  It is private by default in the sense that nothing writes
it outside ``--out``; ``--no-text`` omits the field entirely, which is what a
holdout measurement that has to leave the operator's machine should use.
The attribution sections added on top of that carry no text under any flag: a
line's CHARACTER COUNT and its drawn width are measurements, and a declared
font name is a property of the document's style tree, not of what it says.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402
import own_render  # noqa: E402

#: Two boxes closer than this in ``y0`` are the same seat.  The sidecar
#: rounds to 3 decimals and both policies do integer HWPUNIT arithmetic, so
#: this is "exact" with room for the last decimal, not a real tolerance.
DEFAULT_Y_TOL = 0.01

#: How much of a line's text the report keeps.  Enough to find the line in
#: the document, not enough to reconstruct it.
TEXT_CHARS = 12

CLASSES = ("agree", "A", "B", "C")

CLASS_MEANING = {
    "A": "the break moved: a different line count, or different text on the "
         "same ordinal",
    "B": "same break, different y: same text on the same page, |dy| over the "
         "tolerance",
    "C": "the line changed page",
    "agree": "same text, same page, same y",
}

RULE = ("per paragraph, nth cache line against nth computed line; "
        "A if unpaired or the text differs, else C if the page differs, "
        "else B if |dy| > y_tol, else agree")

#: How far a class-B paragraph's drift may sit from what the re-breaks above
#: it predict and still be called inherited.  One pixel: the prediction is a
#: sum of whole line pitches (tens of px) and the noise under it is the +-2
#: HWPUNIT PERCENT spacing residual, 0.02-0.08 px a line, accumulating down a
#: column.  A pitch is never this small, so no real own-drift hides here.
DEFAULT_ATTRIBUTION_TOL = 1.0

ATTRIBUTION_RULE = (
    "per page, paragraphs in reading order: carry upstream_line_delta (sum of "
    "computed lines - cache lines over the paragraphs before this one) and "
    "expected_dy_px (the same sum weighted by each of those paragraphs' own "
    "line pitch); a class-B paragraph is B_inherited when upstream_line_delta "
    "is non-zero AND the dy of its first class-B line is within "
    "attribution_tol of expected_dy_px, else B_own. "
    "A paragraph's pitch is the dominant y0 step between its consecutive "
    "computed lines on one page (= vertsize + spacing), falling back to the "
    "same step over its cached linesegs, then to the pitch carried down from "
    "the nearest preceding paragraph that had one.")

#: A sentinel for "no page has been walked yet", so page 0 (or None) does not
#: read as "same page as the start" and skip the first reset.
_UNSET = object()


PREDECESSOR_RULE = (
    "per page, paragraphs in document order (every hp:p seated on the page by "
    "its boxes, by its flow seat, or by lying between two paragraphs that are "
    "both on it, so one that draws no line box still counts): find the FIRST "
    "whose ordinal-0 "
    "line is paired on the same page under both policies and whose dy exceeds "
    "y_tol, and report the paragraph immediately BEFORE it on that page. "
    "A page whose first seated paragraph is already the drifting one has no "
    "predecessor and is reported as page_top.")

#: A predecessor's kind, and the whole of what the histogram is keyed on.
PREDECESSOR_KEY_FIELDS = ("anchor_kind", "empty_text", "line_spacing_type")


def anchor_kind(objects):
    """One label for what a paragraph carries, for the histogram key.

    ``anchored:<kind>`` beats ``inline:<kind>`` because the two are different
    layout mechanisms and only the anchored one is placed outside the line —
    a paragraph carrying both is named by the anchored object.  Ties inside a
    class go to the first object in the character stream, which is the one
    the line metrics meet first.
    """
    if not objects:
        return "none"
    for obj in objects:
        if not obj["treat_as_char"]:
            return f"anchored:{obj['kind']}"
    return f"inline:{objects[0]['kind']}"


def cached_line_metrics(para):
    """``{character index: metrics}`` over a paragraph's cached ``hp:lineseg``.

    Keyed on the line's first CHARACTER because that is the argument
    ``_render_cached_lines`` hands ``_line_items``, so the latch finds the
    right line without counting draw calls — a line whose chunk is empty is
    skipped and never drawn, and an ordinal counter would be off by one from
    there on.  It is not the raw ``textpos``: that counts cells, and a
    paragraph carrying an inline control has fewer characters than cells.
    """
    metrics = {}
    for (start, _end), seg in zip(para.lineseg_spans(), para.linesegs):
        vertsize = own_render._iattr(seg, "vertsize")
        spacing = own_render._iattr(seg, "spacing")
        metrics[start] = {
            "source": "lineseg",
            "vertpos_hwp": own_render._iattr(seg, "vertpos"),
            "vertsize_hwp": vertsize,
            "spacing_hwp": spacing,
            "advance_hwp": vertsize + spacing,
        }
    return metrics


def computed_line_metrics(lines):
    """``{line["start"]: metrics}`` over this renderer's own computed lines."""
    metrics = {}
    for line in lines or ():
        metrics[line["start"]] = {
            "source": "computed",
            "vertpos_hwp": line["vertpos"],
            "vertsize_hwp": line["vertsize"],
            "spacing_hwp": line["spacing"],
            "advance_hwp": line["vertsize"] + line["spacing"],
        }
    return metrics


class TracingRenderer(own_render.OwnRenderer):
    """``OwnRenderer`` that stamps each line box with who drew it.

    Both line-drawing entry points are wrapped so the tag is right whichever
    policy is in force, and ``_draw_line`` claims only boxes that are not
    tagged yet: a paragraph holding an inline table draws its cells' lines
    from INSIDE its own ``_draw_line`` call, and the outer call must not
    relabel them as its own.
    """

    _tracing_para = None
    #: ``{first character index of a line: that line's advance metrics}`` for
    #: the paragraph currently drawing, under whichever policy is drawing it.
    _tracing_metrics = None
    #: The one entry of that map for the line ``_draw_line`` is about to draw,
    #: latched by ``_line_items`` — the last thing either render path calls
    #: before ``_draw_line``, and the only place a line's identity (its first
    #: character index) is in scope on both paths.
    _tracing_line = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: ``{(address, page): seat}`` for every block the flow pass placed,
        #: INCLUDING one that draws no line box at all.  An empty paragraph
        #: never reaches a line render path — ``_render_paragraphs`` and
        #: ``_render_flow_page`` both ``continue`` on ``not para.chars`` — so
        #: its flow seat is the only place its computed height is stated.
        self.flow_seats = {}
        #: ``{address: {page, ...}}`` for every paragraph the CACHE path drew,
        #: including one that drew no line.  ``_paginate`` decides the page
        #: under that policy and nothing else records it, so the seat pass
        #: would otherwise have no cache-side page for an inkless paragraph.
        self.cache_seats = {}

    def _render_cached_lines(self, draw, para, *args, **kwargs):
        outer, self._tracing_para = self._tracing_para, para
        outer_metrics = self._tracing_metrics
        self._tracing_metrics = cached_line_metrics(para)
        try:
            return super()._render_cached_lines(draw, para, *args, **kwargs)
        finally:
            self._tracing_para = outer
            self._tracing_metrics = outer_metrics

    def _render_computed_lines(self, draw, para, origin_hwp, lines, *args,
                               **kwargs):
        outer, self._tracing_para = self._tracing_para, para
        outer_metrics = self._tracing_metrics
        self._tracing_metrics = computed_line_metrics(lines)
        try:
            return super()._render_computed_lines(draw, para, origin_hwp,
                                                  lines, *args, **kwargs)
        finally:
            self._tracing_para = outer
            self._tracing_metrics = outer_metrics

    def _render_flow_page(self, draw, records, origin_hwp, avail_w_hwp):
        """Record where the flow pass seated each block before drawing it."""
        for record in records:
            para = record.get("para")
            address = (self.paragraph_index.get(id(para.el))
                       if para is not None else None)
            if address is None:
                continue
            seat = self.flow_seats.setdefault((address, self._page), {
                "address": address,
                "page": self._page,
                "top_hwp": record.get("top"),
                "height_hwp": 0,
            })
            seat["height_hwp"] += record.get("height") or 0
        return super()._render_flow_page(draw, records, origin_hwp,
                                         avail_w_hwp)

    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        """Record which page the CACHE path put each paragraph on.

        Called for table cells and footnote bodies as well as for the page's
        own paragraph list, so the seat pass filters on ``top_level`` rather
        than on this hook: a cell paragraph's ``vertpos`` is measured from its
        cell, not from the body box, and comparing it against a flow seat
        would be comparing two different origins.

        A paragraph the cache carries across a page break arrives here once
        per page; ``setdefault`` keeps the first, which is the page its seat
        is on.
        """
        for para in paragraphs:
            address = self.paragraph_index.get(id(para.el))
            if address is None:
                continue
            self.cache_seats.setdefault(address, {
                "address": address,
                "page": self._page,
                "drawn_pages": 0,
            })["drawn_pages"] += 1
        return super()._render_paragraphs(draw, paragraphs, origin_hwp,
                                          avail_w_hwp, block_offset_hwp)

    def _line_items(self, para, chars, base_index):
        self._tracing_line = (self._tracing_metrics or {}).get(base_index)
        return super()._line_items(para, chars, base_index)

    def _draw_line(self, draw, items, *args, **kwargs):
        before = len(self.line_boxes)
        # Latched BEFORE the call: a paragraph holding an inline table draws
        # its cells' lines from inside this very call, and every one of them
        # goes through ``_line_items`` and overwrites the latch.
        metrics = self._tracing_line
        result = super()._draw_line(draw, items, *args, **kwargs)
        fresh = self.line_boxes[before:]
        if fresh:
            para = self._tracing_para
            address = (self.paragraph_index.get(id(para.el))
                       if para is not None else None)
            text = "".join(seg.text for kind, seg in items if kind == "text")
            faces = self._line_faces(items)
            for record in fresh:
                # The desktop renderer stamps its own OWPML ``address`` dict
                # (kind / atPara / table / row / col) on every box.  This tool
                # keys paragraphs by its flat document-order index, so that
                # index takes the slot and the dict moves aside, unchanged.
                if "address" in record and record["address"] != address:
                    record.setdefault("owpml_address", record["address"])
                record["address"] = address
                record.setdefault("text", text)
                record.setdefault("faces", faces)
                record.setdefault("metrics", metrics)
        return result

    def paragraph_facts(self):
        """Static facts for EVERY ``hp:p`` in the document, keyed by address.

        Read off the tree rather than off the render on purpose: a paragraph
        with no characters draws nothing under either policy and so is absent
        from ``line_boxes`` entirely, and that is exactly the population the
        predecessor pass exists to see.  Object extents come from the
        renderer's own ``_object_extent``, so calling this on both renderers
        states them "under both policies" without re-implementing the rule.
        """
        facts = {}
        for index, section in enumerate(self.sections):
            top_level = {id(el) for el in own_render._kids(section, "p")}
            for el in section.iter():
                if own_render._local(el.tag) != "p":
                    continue
                address = self.paragraph_index.get(id(el))
                if address is None:
                    continue
                facts[address] = self._paragraph_fact(
                    el, address, section=index,
                    top_level=id(el) in top_level)
        return facts

    def section_columns(self):
        """``{section index: colCount}`` — the seat pass's column channel.

        Read after the render, with ``_current_section`` saved and put back:
        ``column_geometry`` answers for whichever section is current, and the
        renderer leaves the last one selected.
        """
        saved = self._current_section
        out = {}
        try:
            for index in range(len(self.sections)):
                self._current_section = index
                geo = self.page_geometry()
                out[index] = self.column_geometry(geo)[2]
        finally:
            self._current_section = saved
        return out

    def _paragraph_fact(self, el, address, section=0, top_level=True):
        para = own_render.Paragraph(el, self.defs["para_pr"])
        pr = para.para_pr
        objects = []
        for char_index, name, obj, _charpr in para.objects:
            record = para.object_at.get(char_index)
            pos = own_render._kid(obj, "pos")
            width, height = self._object_extent(obj)
            left, top, right, bottom = self._object_out_margin(obj)
            objects.append({
                "kind": name,
                "treat_as_char": not (record[3] if record else False),
                "width_hwp": width,
                "height_hwp": height,
                "out_margin_left_hwp": left,
                "out_margin_right_hwp": right,
                "out_margin_top_hwp": top,
                "out_margin_bottom_hwp": bottom,
                "text_wrap": obj.get("textWrap"),
                "vert_offset_hwp": (own_render._iattr(pos, "vertOffset")
                                    if pos is not None else None),
                "vert_rel_to": (pos.get("vertRelTo") if pos is not None
                                else None),
                "horz_rel_to": (pos.get("horzRelTo") if pos is not None
                                else None),
                "flow_with_text": (pos.get("flowWithText") if pos is not None
                                   else None),
            })
        text = "".join(ch for ch, _cid in para.chars
                       if ch != own_render.OBJECT_SLOT)
        linesegs = [{
            "textpos": own_render._iattr(seg, "textpos"),
            "vertpos": own_render._iattr(seg, "vertpos"),
            "vertsize": own_render._iattr(seg, "vertsize"),
            "spacing": own_render._iattr(seg, "spacing"),
        } for seg in para.linesegs]
        # hh:charPr@height is a property of the RUN, not of the characters in
        # it (#247): a run that emits no text still declares the height of the
        # line its paragraph mark sits on, and that is the one channel by
        # which an INKLESS paragraph can be a different height under the two
        # policies without anything else about it differing.
        empty_runs = []
        for char_index, cid in getattr(para, "empty_runs", ()):
            height_pt = self._charpr(cid).get("height_pt")
            empty_runs.append({
                "char_index": char_index,
                "charpr": cid,
                "height_pt": height_pt,
                "height_hwp": (None if height_pt is None else
                               int(round(height_pt
                                         * own_render.HWPUNIT_PER_PT))),
            })
        return {
            "address": address,
            "section": section,
            "top_level": bool(top_level),
            "empty_text": not text.strip(),
            "characters": len(para.chars),
            "objects": objects,
            "anchor_kind": anchor_kind(objects),
            "empty_runs": empty_runs,
            "line_spacing_type": pr.get("line_spacing_type"),
            "line_spacing_value": pr.get("line_spacing_value"),
            "margin_prev_hwp": pr.get("margin_prev", 0),
            "margin_next_hwp": pr.get("margin_next", 0),
            # Both spellings of "break here", the way _flow_blocks reads them:
            # hp:p@pageBreak is the instruction on the paragraph and
            # hh:breakSetting@pageBreakBefore the one carried by its shape.
            "page_break_before": bool(own_render._iattr(el, "pageBreak")
                                      or pr.get("page_break_before")),
            "column_break": bool(own_render._iattr(el, "columnBreak")),
            "keep_with_next": bool(pr.get("keep_with_next")),
            "keep_lines": bool(pr.get("keep_lines")),
            "widow_orphan": bool(pr.get("widow_orphan")),
            "linesegs": linesegs,
            "cache_advance_hwp": sum(seg["vertsize"] + seg["spacing"]
                                     for seg in linesegs),
            "cache_extent_hwp": (
                linesegs[-1]["vertpos"] + linesegs[-1]["vertsize"]
                - linesegs[0]["vertpos"] if linesegs else None),
        }

    def _line_faces(self, items):
        """Every ``(charPr, slot, bold)`` this line draws, resolved.

        The resolution is not re-implemented: ``_face_for`` is the renderer's
        own answer and it fills ``_face_cache`` with the record that names the
        declared face, the family it landed on and the ``source``
        (``installed`` / ``bundled`` / ``system``).  Calling it here costs a
        cache hit per distinct triple and nudges the sidecar's per-face
        character tally, which this tool does not emit.
        """
        seen = {}
        for kind, seg in items:
            if kind != "text":
                continue
            cid = seg.charpr
            bold = bool(self._charpr(cid).get("bold"))
            for ch in seg.text:
                slot = own_render.script_slot(ch)
                key = (cid, slot, bold)
                hit = seen.get(key)
                if hit is not None:
                    hit["characters"] += 1
                    continue
                self._face_for(cid, slot, bold)
                cached = self._face_cache.get(key)
                record = cached[1] if cached else None
                seen[key] = {
                    "declared": record.get("declared") if record else None,
                    "slot": slot,
                    "bold": bold,
                    "source": record.get("source") if record else "system",
                    "resolved_family": (
                        (record.get("installed_family")
                         or record.get("family_map")) if record else None),
                    "resolved_file": (
                        record.get("file")
                        or record.get("substituted_with")) if record else None,
                    "characters": 1,
                }
        return sorted(seen.values(),
                      key=lambda f: (-f["characters"], f["slot"]))


def trace_lines(hwpx_path, policy, dpi=own_render.DEFAULT_DPI, repo_root=None):
    """Render ``hwpx_path`` under ``policy`` and return its tagged line boxes.

    Rendering is in-process on purpose: two subprocesses would pay the font
    scan twice and could not share the paragraph index that makes the pairing
    meaningful.
    """
    renderer = TracingRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                               layout_policy=policy)
    images, sidecar = renderer.render()
    return {
        "pages": len(images),
        "line_boxes": sidecar.get("line_boxes") or [],
        "layout_policy": sidecar.get("layout_policy", policy),
        # Read AFTER the render: the object extents an equation carries are
        # measured during it, and the flow seats only exist once the flow
        # pass has run.
        "facts": renderer.paragraph_facts(),
        "flow_seats": dict(renderer.flow_seats),
        "cache_seats": dict(renderer.cache_seats),
        "section_columns": renderer.section_columns(),
        "px_per_hwp": dpi / own_render.HWPUNIT_PER_INCH,
        # Section 0's body box.  A multi-section document can page differently
        # per section and this does not follow that; it is here to be read
        # against a cached ``vertpos``, which is measured from the body top.
        "usable_height_hwp": renderer.page_geometry().get("usable_height"),
    }


def by_paragraph(line_boxes):
    """Group tagged boxes by paragraph address, keeping draw order.

    Untagged boxes — page furniture this renderer stamps outside any
    paragraph, such as a page number — are dropped: they have no paragraph to
    be paired inside.
    """
    grouped = {}
    for box in line_boxes:
        address = box.get("address")
        if address is None:
            continue
        grouped.setdefault(address, []).append(box)
    return grouped


def classify_line(cache_box, computed_box, y_tol=DEFAULT_Y_TOL):
    """One paired line's class.  See the module docstring for the rule."""
    if cache_box is None or computed_box is None:
        return "A"
    if cache_box.get("text") != computed_box.get("text"):
        return "A"
    if cache_box.get("page") != computed_box.get("page"):
        return "C"
    if abs(cache_box["y0"] - computed_box["y0"]) > y_tol:
        return "B"
    return "agree"


def classify_paragraph(cache_lines, computed_lines, y_tol=DEFAULT_Y_TOL):
    """Every line of one paragraph, paired by ordinal and classified."""
    rows = []
    for index in range(max(len(cache_lines), len(computed_lines))):
        cache_box = cache_lines[index] if index < len(cache_lines) else None
        computed_box = (computed_lines[index]
                        if index < len(computed_lines) else None)
        rows.append({
            "line": index,
            "class": classify_line(cache_box, computed_box, y_tol),
            "cache": cache_box,
            "computed": computed_box,
        })
    return rows


def _delta(cache_box, computed_box, key):
    if cache_box is None or computed_box is None:
        return None
    return round(computed_box[key] - cache_box[key], 3)


def _first_divergence(address, rows, include_text):
    for row in rows:
        if row["class"] == "agree":
            continue
        cache_box, computed_box = row["cache"], row["computed"]
        record = {
            "paragraph": address,
            "line": row["line"],
            "class": row["class"],
            "cache_page": cache_box["page"] if cache_box else None,
            "computed_page": computed_box["page"] if computed_box else None,
            "cache_y": cache_box["y0"] if cache_box else None,
            "computed_y": computed_box["y0"] if computed_box else None,
            "dy_px": _delta(cache_box, computed_box, "y0"),
            "dx_px": _delta(cache_box, computed_box, "x0"),
        }
        if include_text:
            source = computed_box or cache_box
            record["text"] = (source.get("text") or "")[:TEXT_CHARS]
        return record
    return None


def _histogram(values, count_key, value_key="residual_px", places=2):
    """Tallest bar first, the way ``class_b_dy_px`` reads.

    A constant offset shared by a run of paragraphs is one tall bar here and
    a scatter is not, which is the whole reason these are histograms and not
    means.
    """
    tally = Counter(round(value, places) for value in values)
    return [{value_key: value, count_key: count}
            for value, count in sorted(tally.items(),
                                       key=lambda kv: (-kv[1], kv[0]))]


def dominant_pitch(boxes):
    """The dominant ``y0`` step between consecutive boxes on one page.

    That step is the line's advance — ``vertsize + spacing`` — by own_render's
    own line-position relation, so this reads the per-line pitch off the
    render instead of re-deriving it from the tree.  Steps across a page
    boundary are skipped (the next page's ``y0`` restarts at its own top) and
    so are non-positive ones (a table cell's lines are not a column).  Ties go
    to the larger step, so the answer does not depend on dict order.
    """
    steps = Counter()
    for previous, following in zip(boxes, boxes[1:]):
        if previous.get("page") != following.get("page"):
            continue
        step = round(following["y0"] - previous["y0"], 2)
        if step > 0:
            steps[step] += 1
    if not steps:
        return None
    return max(steps.items(), key=lambda kv: (kv[1], kv[0]))[0]


def paragraph_pitch(computed_lines, cache_lines, carried=None):
    """``(pitch_px, where_it_came_from)`` for one paragraph.

    Preference order, and the reason for it: a paragraph's OWN computed lines
    are the pitch the computed layout actually used, so they answer first; its
    own cached lines are its ``hp:lineseg`` ``vertsize + spacing``, which is
    the same quantity as the authoring engine measured it; and a paragraph
    with one line either way has no pitch of its own and borrows the one
    carried down from the nearest preceding paragraph that had one.
    """
    own = dominant_pitch(computed_lines)
    if own is not None:
        return own, "own_computed"
    cached = dominant_pitch(cache_lines)
    if cached is not None:
        return cached, "own_lineseg"
    if carried is not None:
        return carried, "preceding_computed"
    return None, "none"


def attribute_class_b(dy_px, expected_dy_px, tol, upstream_line_delta=None):
    """``B_inherited`` when the drift is what the upstream re-breaks predict.

    ``upstream_line_delta`` of zero is a hard ``B_own`` and not a tolerance
    question: nothing above this paragraph re-broke, so there is nothing for
    it to have inherited, and without the guard every sub-pixel drift — the
    +-2 HWPUNIT PERCENT spacing residual, which is most of class B at the
    default ``--y-tol`` — would read as "explained by an upstream delta of
    zero lines" and quietly disappear.
    """
    if dy_px is None or expected_dy_px is None:
        return "B_own"
    if not upstream_line_delta:
        return "B_own"
    return ("B_inherited" if abs(dy_px - expected_dy_px) <= tol
            else "B_own")


def _line_width(box):
    if box is None:
        return None
    return round(box["x1"] - box["x0"], 3)


def _break_direction(cache_box, computed_box):
    """Which way the break moved on this ordinal, in characters."""
    if cache_box is None:
        return "computed_only"
    if computed_box is None:
        return "cache_only"
    cache_chars = len(cache_box.get("text") or "")
    computed_chars = len(computed_box.get("text") or "")
    if computed_chars < cache_chars:
        return "computed_broke_earlier"
    if computed_chars > cache_chars:
        return "computed_broke_later"
    return "same_length_different_text"


def _class_a_record(address, row, cache_lines, computed_lines):
    """One class-A paragraph's break cause, as far as it is cheap to say."""
    cache_box, computed_box = row["cache"], row["computed"]
    # The union over both sides, keyed on the RESOLUTION as well as the
    # declared name: the same declared face resolving two ways across the two
    # policies would be the finding, so it must not dedupe itself away.  The
    # normal case is one entry per declared face, because resolution is
    # deterministic on a machine and both policies draw the same runs.
    faces = {}
    for box in (cache_box, computed_box):
        for face in (box or {}).get("faces") or []:
            key = (face["declared"], face["slot"], face["bold"],
                   face["source"])
            faces.setdefault(key, face)
    return {
        "paragraph": address,
        "line": row["line"],
        "cache_lines": len(cache_lines),
        "computed_lines": len(computed_lines),
        "line_delta": len(computed_lines) - len(cache_lines),
        "cache_chars": (len(cache_box.get("text") or "")
                        if cache_box else None),
        "computed_chars": (len(computed_box.get("text") or "")
                           if computed_box else None),
        "break": _break_direction(cache_box, computed_box),
        "cache_width_px": _line_width(cache_box),
        "computed_width_px": _line_width(computed_box),
        "dwidth_px": (
            None if cache_box is None or computed_box is None
            else round(_line_width(computed_box) - _line_width(cache_box), 3)),
        "faces": sorted(faces.values(),
                        key=lambda f: (-f["characters"], f["slot"])),
        "all_runs_substituted": bool(faces) and all(
            face["source"] != "installed" for face in faces.values()),
    }


def _font_source_share(class_a_lines):
    """How class-A lines split by where their faces resolved.

    Two denominators, deliberately: ``lines`` books each class-A line once,
    under ``substituted`` if ANY run on it resolved to a bundled or system
    face (that one run is enough to move the advance), and ``characters``
    weights each face by how much of the line it draws.
    """
    lines = Counter()
    characters = Counter()
    for record in class_a_lines:
        sources = {face["source"] for face in record["faces"]}
        for face in record["faces"]:
            characters[face["source"]] += face["characters"]
        if not sources:
            lines["no_runs"] += 1
        elif sources <= {"installed"}:
            lines["installed"] += 1
        else:
            lines["substituted"] += 1
            for name in ("bundled", "system"):
                if name in sources:
                    lines[f"substituted_{name}"] += 1
    total = sum(lines[name] for name in
                ("installed", "substituted", "no_runs"))
    return {
        "lines": {name: lines.get(name, 0) for name in
                  ("installed", "substituted", "substituted_bundled",
                   "substituted_system", "no_runs")},
        "characters": dict(sorted(characters.items())),
        "substituted_share": (round(lines["substituted"] / total, 6)
                              if total else None),
        "note": ("a line counts as substituted when ANY run on it resolved to "
                 "a bundled or system face; the two substituted_* rows "
                 "overlap when a line mixes them"),
    }


def walk_paragraphs(cache_paras, computed_paras, y_tol=DEFAULT_Y_TOL,
                    include_text=True,
                    attribution_tol=DEFAULT_ATTRIBUTION_TOL):
    """Classify and attribute every paragraph, in reading order.

    Takes the two ``{address: [box, ...]}`` maps and nothing else, so the
    whole rule — the A/B/C classification, the per-page accumulators, the
    class-B attribution and the class-A break cause — can be exercised on
    synthetic boxes without rendering a document.  ``divergence_report`` is
    the renderer around it.
    """
    line_counts = Counter()
    para_counts = Counter()
    both_a_and_b = 0
    divergences = []
    dy_histogram = Counter()

    # The reading-order walk of the attribution pass, reset at every page.
    carried_pitch = None
    page_seen = _UNSET
    upstream_delta = 0
    upstream_dy = 0.0
    b_counts = Counter()
    class_b_rows = []
    class_a_lines = []

    for address in sorted(set(cache_paras) | set(computed_paras)):
        cache_lines = cache_paras.get(address, [])
        computed_lines = computed_paras.get(address, [])
        rows = classify_paragraph(cache_lines, computed_lines, y_tol)
        classes = set()
        for row in rows:
            line_counts[row["class"]] += 1
            classes.add(row["class"])
            if row["class"] == "B":
                dy_histogram[round(_delta(row["cache"], row["computed"],
                                          "y0"), 2)] += 1

        # -- attribution ---------------------------------------------------
        # The page is read off the CACHE side: a class-B paragraph agrees on
        # its page by definition, and the cache side is the one that does not
        # move under the thing being measured.
        anchor = (cache_lines or computed_lines)
        page = anchor[0].get("page") if anchor else None
        if page != page_seen:
            page_seen = page
            upstream_delta = 0
            upstream_dy = 0.0
        pitch, pitch_from = paragraph_pitch(computed_lines, cache_lines,
                                            carried_pitch)
        if pitch is not None and pitch_from != "preceding_computed":
            carried_pitch = pitch

        if "B" in classes:
            first_b = next(row for row in rows if row["class"] == "B")
            dy = _delta(first_b["cache"], first_b["computed"], "y0")
            verdict = attribute_class_b(dy, upstream_dy, attribution_tol,
                                        upstream_delta)
            b_counts[verdict] += 1
            if verdict == "B_own":
                b_counts["B_own_with_upstream_rebreak" if upstream_delta
                         else "B_own_no_upstream_rebreak"] += 1
            simple = (round(upstream_delta * pitch, 3)
                      if pitch is not None else None)
            class_b_rows.append({
                "paragraph": address,
                "line": first_b["line"],
                "page": page,
                "dy_px": dy,
                "pitch_px": pitch,
                "pitch_from": pitch_from,
                "upstream_line_delta": upstream_delta,
                "expected_dy_px": round(upstream_dy, 3),
                "residual_px": (None if dy is None
                                else round(dy - upstream_dy, 3)),
                "simple_expected_px": simple,
                "residual_simple_px": (None if dy is None or simple is None
                                       else round(dy - simple, 3)),
                "attribution": verdict,
            })

        if "A" in classes:
            first_a = next(row for row in rows if row["class"] == "A")
            class_a_lines.append(_class_a_record(address, first_a,
                                                 cache_lines, computed_lines))

        # Walk past this paragraph: what IT added is upstream of the next one.
        delta = len(computed_lines) - len(cache_lines)
        if delta and pitch is not None:
            upstream_dy += delta * pitch
        upstream_delta += delta

        if classes == {"agree"}:
            para_counts["agree"] += 1
            continue
        for name in ("A", "B", "C"):
            if name in classes:
                para_counts[name] += 1
        if {"A", "B"} <= classes:
            both_a_and_b += 1
        first = _first_divergence(address, rows, include_text)
        if first is not None:
            divergences.append(first)

    return {
        "lines": {name: line_counts.get(name, 0) for name in CLASSES},
        "paragraphs": {
            **{name: para_counts.get(name, 0) for name in CLASSES},
            "A_and_B": both_a_and_b,
            "compared": len(set(cache_paras) | set(computed_paras)),
        },
        "class_b_dy_px": [
            {"dy_px": dy, "lines": count}
            for dy, count in sorted(dy_histogram.items(),
                                    key=lambda kv: (-kv[1], kv[0]))
        ],
        "first_divergence_per_paragraph": divergences,
        "attribution": {
            "rule": ATTRIBUTION_RULE,
            "tolerance_px": attribution_tol,
            "class_b_paragraphs": {
                "B_inherited": b_counts.get("B_inherited", 0),
                "B_own": b_counts.get("B_own", 0),
                # A B_own that DOES have a re-break above it is a different
                # animal from one that does not: the cause is upstream, only
                # the predicted magnitude is wrong.  Keeping the two apart is
                # what stops "B_own" from reading as "class B is not
                # downstream of class A".
                "B_own_with_upstream_rebreak": b_counts.get(
                    "B_own_with_upstream_rebreak", 0),
                "B_own_no_upstream_rebreak": b_counts.get(
                    "B_own_no_upstream_rebreak", 0),
            },
            "class_b_residual_px": _histogram(
                (row["residual_px"] for row in class_b_rows
                 if row["attribution"] == "B_own"
                 and row["residual_px"] is not None), "paragraphs"),
            "class_b_upstream_delta": [
                {"upstream_line_delta": delta, "paragraphs": count}
                for delta, count in sorted(Counter(
                    row["upstream_line_delta"]
                    for row in class_b_rows).items())
            ],
            "class_b": class_b_rows,
            "class_a_lines": class_a_lines,
            "class_a_font_sources": _font_source_share(class_a_lines),
        },
    }


def merge_facts(cache_facts, computed_facts):
    """One fact map, with each object's extent stated under BOTH policies.

    Everything else a fact carries is read off the XML tree and cannot differ
    between two renders of the same file; the extent can, because an
    equation's height is measured during the render
    (``_equation_extent_height``).  Where the two agree — every corpus object
    — ``height_hwp_computed`` simply repeats ``height_hwp``, and
    ``extent_differs`` says so in one boolean rather than asking a reader to
    compare two numbers.
    """
    merged = {}
    for address, fact in (cache_facts or {}).items():
        fact = dict(fact)
        other = ((computed_facts or {}).get(address) or {}).get("objects") or []
        objects = []
        for index, obj in enumerate(fact.get("objects") or []):
            obj = dict(obj)
            twin = other[index] if index < len(other) else None
            obj["width_hwp_computed"] = (twin or obj).get("width_hwp")
            obj["height_hwp_computed"] = (twin or obj).get("height_hwp")
            obj["extent_differs"] = (
                obj["width_hwp_computed"] != obj["width_hwp"]
                or obj["height_hwp_computed"] != obj["height_hwp"])
            objects.append(obj)
        fact["objects"] = objects
        merged[address] = fact
    return merged


def _page_of(boxes):
    """The page a paragraph's boxes sit on, or ``None`` when they disagree."""
    pages = {box.get("page") for box in boxes}
    return pages.pop() if len(pages) == 1 else None


def _edge_line(boxes, page, which):
    """This paragraph's first or last box on ``page``, in draw order."""
    on_page = [box for box in boxes if box.get("page") == page]
    if not on_page:
        return None
    return on_page[0] if which == "first" else on_page[-1]


def _bottoms(box, px_per_hwp):
    """``(ink bottom, advance bottom)`` in px for one drawn line.

    Two of them because they are the two candidate readings of where a
    paragraph ENDS, and the whole question this pass was opened on is which
    one the gap below the paragraph is measured from.  ``ink`` is
    ``y0 + vertsize`` — the cache's own ``_cached_extent`` reading, the last
    line's trailing ``spacing`` excluded.  ``advance`` is ``y0 + vertsize +
    spacing``, which is what the flow pass sums into a block height.
    """
    if box is None:
        return None, None
    metrics = box.get("metrics")
    if not metrics:
        return None, None
    y0 = box["y0"]
    return (round(y0 + metrics["vertsize_hwp"] * px_per_hwp, 3),
            round(y0 + metrics["advance_hwp"] * px_per_hwp, 3))


def _side(boxes, page, px_per_hwp):
    """One policy's view of a predecessor paragraph on one page."""
    last = _edge_line(boxes, page, "last")
    ink, advance = _bottoms(last, px_per_hwp)
    metrics = (last or {}).get("metrics") or {}
    return {
        "lines_on_page": sum(1 for box in boxes if box.get("page") == page),
        "last_line": None if last is None else {
            "y0_px": last["y0"],
            "y1_px": last["y1"],
            "vertpos_hwp": metrics.get("vertpos_hwp"),
            "vertsize_hwp": metrics.get("vertsize_hwp"),
            "spacing_hwp": metrics.get("spacing_hwp"),
            "advance_hwp": metrics.get("advance_hwp"),
        },
        "pitch_px": dominant_pitch([box for box in boxes
                                    if box.get("page") == page]),
        "bottom_ink_px": ink,
        "bottom_advance_px": advance,
    }


def _gap(bottom_px, first_box):
    if bottom_px is None or first_box is None:
        return None
    return round(first_box["y0"] - bottom_px, 3)


def seated_pages(cache_paras, computed_paras, facts, seats):
    """``{page: {address, ...}}`` — every paragraph seated on each page.

    Three sources, in decreasing directness.  A paragraph that DREW is on the
    page its boxes are on.  A paragraph the flow pass placed is on the page
    its seat names, drawn or not.  And a paragraph with neither — the empty
    one inside a table cell, which no flow seat covers — is placed by
    ENCLOSURE: if the paragraph before it and the paragraph after it in
    document order are both on one page, so is it.  Enclosure is an
    inference, but a safe one, and refusing to make it is what would hide the
    population this pass exists to see; a paragraph whose neighbours disagree
    is left unplaced rather than guessed at.
    """
    placed = {}
    for address, boxes in list(cache_paras.items()) + list(
            computed_paras.items()):
        for box in boxes:
            placed.setdefault(address, box.get("page"))
    for (address, page), _seat in (seats or {}).items():
        placed.setdefault(address, page)

    known = sorted(placed)
    if known:
        for address in sorted(facts or ()):
            if address in placed:
                continue
            before = [value for value in known if value < address]
            after = [value for value in known if value > address]
            if not before or not after:
                continue
            page = placed[before[-1]]
            if page == placed[after[0]]:
                placed[address] = page

    pages = {}
    for address, page in placed.items():
        pages.setdefault(page, set()).add(address)
    return pages


def predecessor_key(fact):
    """The histogram key: ``(anchor kind, empty text, line spacing type)``."""
    return (fact.get("anchor_kind", "none"),
            bool(fact.get("empty_text")),
            fact.get("line_spacing_type") or "PERCENT")


def first_drift_predecessors(cache_paras, computed_paras, facts, seats,
                             px_per_hwp, y_tol=DEFAULT_Y_TOL,
                             usable_height_hwp=None):
    """Per page, what sits immediately above the first paragraph that drifts.

    Takes plain dicts and nothing else — the two ``{address: [box, ...]}``
    maps, the per-address static facts, the computed flow seats and the
    HWPUNIT-to-pixel scale — so the whole rule can be exercised on synthetic
    input without rendering a document.

    A predecessor that drew nothing (the empty paragraph, the paragraph whose
    only content is an anchored object) has no box to measure, and it is the
    reason this pass exists at all: it is invisible to the A/B/C
    classification, its line-count delta is 0 either way, so every paragraph
    below it is booked ``B_own_no_upstream_rebreak``.  For those the report
    falls back to the HWPUNIT domain, where the cache states a height (the
    sum of its ``hp:lineseg`` advances) and the flow pass states another (its
    seat height), and the difference between the two is the drift in the
    units it was made in.
    """
    pages = seated_pages(cache_paras, computed_paras, facts, seats)

    rows = []
    kinds = Counter()
    for page in sorted(pages, key=lambda value: (value is None, value)):
        order = sorted(pages[page])
        drift_at = None
        for position, address in enumerate(order):
            cache_first = _edge_line(cache_paras.get(address, []), page,
                                     "first")
            computed_first = _edge_line(computed_paras.get(address, []), page,
                                        "first")
            if cache_first is None or computed_first is None:
                continue
            dy = round(computed_first["y0"] - cache_first["y0"], 3)
            if abs(dy) > y_tol:
                drift_at = (position, address, dy, cache_first, computed_first)
                break
        if drift_at is None:
            continue
        position, address, dy, cache_first, computed_first = drift_at
        row = {
            "page": page,
            "drift_paragraph": address,
            "drift_dy_px": dy,
            "predecessor": None,
        }
        if position == 0:
            row["predecessor_note"] = ("page_top: the first paragraph seated "
                                       "on this page is the one that drifts")
            rows.append(row)
            continue
        previous = order[position - 1]
        fact = dict(facts.get(previous) or {})
        cache_boxes = cache_paras.get(previous, [])
        computed_boxes = computed_paras.get(previous, [])
        cache_side = _side(cache_boxes, page, px_per_hwp)
        computed_side = _side(computed_boxes, page, px_per_hwp)
        seat = (seats or {}).get((previous, page))
        drawn = bool(cache_side["last_line"] or computed_side["last_line"])
        row.update({
            "predecessor": previous,
            "predecessor_drawn": drawn,
            "cache": cache_side,
            "computed": computed_side,
            "gap_px": {
                "cache_from_ink": _gap(cache_side["bottom_ink_px"],
                                       cache_first),
                "cache_from_advance": _gap(cache_side["bottom_advance_px"],
                                           cache_first),
                "computed_from_ink": _gap(computed_side["bottom_ink_px"],
                                          computed_first),
                "computed_from_advance": _gap(
                    computed_side["bottom_advance_px"], computed_first),
            },
            "para_pr": {
                "line_spacing_type": fact.get("line_spacing_type"),
                "line_spacing_value": fact.get("line_spacing_value"),
                "margin_prev_hwp": fact.get("margin_prev_hwp"),
                "margin_next_hwp": fact.get("margin_next_hwp"),
            },
            "empty_text": bool(fact.get("empty_text")),
            "anchor_kind": fact.get("anchor_kind", "none"),
            "objects": fact.get("objects") or [],
            "cache_advance_hwp": fact.get("cache_advance_hwp"),
            "cache_extent_hwp": fact.get("cache_extent_hwp"),
            "flow_seat_height_hwp": (seat or {}).get("height_hwp"),
            "flow_seat_top_hwp": (seat or {}).get("top_hwp"),
            # Where the CACHE seats this paragraph, read against the body box
            # it is supposed to fit in.  A cached seat at or past the bottom
            # is the authoring engine declining to paginate a paragraph the
            # flow pass does paginate, and that is the whole difference on a
            # predecessor that draws nothing: the flow pass carries it to the
            # next page and every paragraph below it moves down by its height.
            "cache_seat_vertpos_hwp": (
                (fact.get("linesegs") or [{}])[0].get("vertpos")),
            "usable_height_hwp": usable_height_hwp,
        })
        seat_top = row["cache_seat_vertpos_hwp"]
        row["cache_seat_past_page_bottom"] = (
            None if seat_top is None or usable_height_hwp is None
            else seat_top >= usable_height_hwp)
        cached_height = fact.get("cache_advance_hwp")
        seat_height = (seat or {}).get("height_hwp")
        row["height_delta_hwp"] = (
            None if seat_height is None or cached_height is None
            else seat_height - cached_height)
        row["height_delta_px"] = (
            None if row["height_delta_hwp"] is None
            else round(row["height_delta_hwp"] * px_per_hwp, 3))
        rows.append(row)
        kinds[predecessor_key(fact)] += 1

    histogram = [
        {"anchor_kind": key[0], "empty_text": key[1],
         "line_spacing_type": key[2], "pages": count}
        for key, count in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    total = sum(kinds.values())
    dominant = None
    if histogram:
        top = histogram[0]
        dominant = {
            "kind": (f"{top['anchor_kind']}/empty={int(top['empty_text'])}"
                     f"/{top['line_spacing_type']}"),
            "pages": top["pages"],
            "share": round(top["pages"] / total, 6) if total else None,
        }
    return {
        "rule": PREDECESSOR_RULE,
        "key_fields": list(PREDECESSOR_KEY_FIELDS),
        "pages_with_drift": len(rows),
        "pages_with_a_predecessor": total,
        "kinds": histogram,
        "dominant_kind": dominant,
        "pages": rows,
    }


#: A seat difference under this many HWPUNIT is the same seat.  Both policies
#: state a seat as an integer HWPUNIT measured from the body top, so half a
#: unit means "any difference at all"; it is stated in HWPUNIT and not in
#: pixels because the seat pass never leaves the units the layout was made in.
DEFAULT_SEAT_TOL_HWP = 0.5

SEAT_RULE = (
    "for every top-level hp:p in document order, the seat under each policy: "
    "cache = the page _render_paragraphs drew it on plus its first "
    "hp:lineseg@vertpos, computed = the page and top of its flow-pass "
    "placement, both measured from the body top in HWPUNIT. Per cache page, "
    "the FIRST paragraph whose seat differs (different page, or |delta top| > "
    "seat_tol) is reported with the paragraph before it and the delta split "
    "as delta_top(this) = d_prev_top + d_prev_advance + d_gap, where gap is "
    "this.top - (prev.top + prev.advance) under each policy. The carrier is "
    "the largest of the three terms that is over the tolerance; single_term "
    "says the other two are both under it.")

SEAT_KEY_FIELDS = ("prev_kind", "kind", "carrier")

#: The three ways a pair cannot be decomposed, named rather than guessed at.
SEAT_NON_TERMS = ("page_top", "page_move", "no_seat")


def kind_label(fact):
    """``anchor/empty=N/SPACING`` — the predecessor pass's key, as one string."""
    anchor, empty, spacing = predecessor_key(fact or {})
    return f"{anchor}/empty={int(empty)}/{spacing}"


def _flow_seats_by_address(flow_seats):
    """``{address: [seat, ...]}`` in page order over the flow placements."""
    grouped = {}
    for (address, _page), seat in (flow_seats or {}).items():
        grouped.setdefault(address, []).append(seat)
    for seats in grouped.values():
        seats.sort(key=lambda seat: (seat.get("page") is None,
                                     seat.get("page")))
    return grouped


def _computed_seat(seats):
    """One paragraph's computed seat: its first page's top, its total height.

    A paragraph the flow pass carried across a page boundary leaves one record
    per page.  Its SEAT is where it starts — the first record's ``top`` on the
    first record's page — and its advance is what the whole block consumed,
    which is the sum, because that is the quantity the next paragraph's seat
    is measured after.
    """
    if not seats:
        return None
    first = seats[0]
    return {
        "page": first.get("page"),
        "top_hwp": first.get("top_hwp"),
        "advance_hwp": sum(seat.get("height_hwp") or 0 for seat in seats),
        "records": len(seats),
    }


def _cache_seat(fact, cache_seats, address):
    """One paragraph's cache seat: the page it drew on, its first ``vertpos``.

    ``advance_hwp`` is the sum of the paragraph's lineseg ``vertsize +
    spacing`` — the same reading ``_flow_lines`` sums into a block height, so
    the two sides' advances are the same quantity.  A paragraph with no
    cached lineseg at all (a package this repo wrote has none) has no cache
    seat, and the pass says so rather than inventing a zero.
    """
    drawn = (cache_seats or {}).get(address)
    linesegs = (fact or {}).get("linesegs") or []
    if drawn is None or not linesegs:
        return None
    return {
        "page": drawn.get("page"),
        "top_hwp": linesegs[0]["vertpos"],
        "advance_hwp": (fact or {}).get("cache_advance_hwp"),
        "records": drawn.get("drawn_pages", 1),
    }


def seat_rows(facts, cache_seats, flow_seats, cache_paras, computed_paras,
              px_per_hwp, section_columns=None):
    """One seat record per TOP-LEVEL paragraph, in document order.

    Takes plain dicts, like the predecessor pass, so the rule can be exercised
    on synthetic input without rendering anything.

    Top-level only.  A paragraph inside a table cell has a ``vertpos``
    measured from its own cell and no flow seat at all, so putting it beside a
    body-box seat would be comparing two origins; ``top_level`` on the fact
    is what separates them.
    """
    grouped = _flow_seats_by_address(flow_seats)
    rows = []
    for address in sorted(facts or ()):
        fact = facts[address]
        if not fact.get("top_level", True):
            continue
        cache = _cache_seat(fact, cache_seats, address)
        computed = _computed_seat(grouped.get(address))
        for side, boxes in (("cache", cache_paras), ("computed",
                                                     computed_paras)):
            seat = cache if side == "cache" else computed
            if seat is not None:
                seat["text_lines"] = len((boxes or {}).get(address) or [])
        delta = None
        if cache is not None and computed is not None:
            top = _sub(computed["top_hwp"], cache["top_hwp"])
            advance = _sub(computed["advance_hwp"], cache["advance_hwp"])
            delta = {
                "page": _sub(computed["page"], cache["page"]),
                "top_hwp": top,
                "top_px": (None if top is None
                           else round(top * px_per_hwp, 3)),
                "advance_hwp": advance,
                "advance_px": (None if advance is None
                               else round(advance * px_per_hwp, 3)),
                "text_lines": _sub(computed.get("text_lines"),
                                   cache.get("text_lines")),
            }
        rows.append({
            "address": address,
            "section": fact.get("section"),
            "column_count": (section_columns or {}).get(fact.get("section")),
            "kind": kind_label(fact),
            "cache": cache,
            "computed": computed,
            "delta": delta,
            "empty_text": bool(fact.get("empty_text")),
            "characters": fact.get("characters"),
            "cached_linesegs": len(fact.get("linesegs") or []),
            "empty_runs": fact.get("empty_runs") or [],
            "objects": fact.get("objects") or [],
            "anchor_kind": fact.get("anchor_kind", "none"),
            "para_pr": {
                "line_spacing_type": fact.get("line_spacing_type"),
                "line_spacing_value": fact.get("line_spacing_value"),
                "margin_prev_hwp": fact.get("margin_prev_hwp"),
                "margin_next_hwp": fact.get("margin_next_hwp"),
                "page_break_before": fact.get("page_break_before"),
                "column_break": fact.get("column_break"),
                "keep_with_next": fact.get("keep_with_next"),
                "keep_lines": fact.get("keep_lines"),
                "widow_orphan": fact.get("widow_orphan"),
            },
        })
    return rows


def _sub(left, right):
    return None if left is None or right is None else left - right


def _seat_gap(prev, row, side):
    """``this.top - (prev.top + prev.advance)`` under one policy."""
    a, b = prev.get(side), row.get(side)
    if a is None or b is None:
        return None
    if a.get("top_hwp") is None or b.get("top_hwp") is None:
        return None
    return b["top_hwp"] - (a["top_hwp"] + (a.get("advance_hwp") or 0))


def decompose_seat_delta(prev, row, tol=DEFAULT_SEAT_TOL_HWP):
    """Split one pair's seat delta into its three terms, or name why not.

    ``delta_top(this) = d_prev_top + d_prev_advance + d_gap`` is an identity,
    not a model: the same number written two ways.  What it buys is WHERE the
    height entered — the predecessor's own seat (older, reported further up),
    the predecessor's own height, or the space between the two paragraphs.
    ``identity_ok`` re-checks the arithmetic rather than asserting it.
    """
    if prev is None:
        return {"carrier": "page_top", "terms": None, "single_term": None,
                "note": "the first seated paragraph on this page is the one "
                        "whose seat differs"}
    if prev.get("cache") is None or prev.get("computed") is None:
        return {"carrier": "no_seat", "terms": None, "single_term": None,
                "note": "the paragraph above has no seat under one policy"}
    if row["delta"].get("page"):
        return {"carrier": "page_move", "terms": None, "single_term": None,
                "note": "the two policies put this paragraph on different "
                        "pages, so its tops are measured from different "
                        "page tops"}
    same_page = (prev["cache"]["page"] == row["cache"]["page"]
                 and prev["computed"]["page"] == row["computed"]["page"])
    if not same_page:
        return {"carrier": "page_top", "terms": None, "single_term": None,
                "note": "the paragraph above sits on another page, so there "
                        "is no gap between the two to measure"}
    gap_cache = _seat_gap(prev, row, "cache")
    gap_computed = _seat_gap(prev, row, "computed")
    terms = {
        "d_prev_top_hwp": _sub(prev["computed"]["top_hwp"],
                               prev["cache"]["top_hwp"]),
        "d_prev_advance_hwp": _sub(prev["computed"].get("advance_hwp"),
                                   prev["cache"].get("advance_hwp")),
        "d_gap_hwp": _sub(gap_computed, gap_cache),
    }
    terms["gap_cache_hwp"] = gap_cache
    terms["gap_computed_hwp"] = gap_computed
    named = ("d_prev_top_hwp", "d_prev_advance_hwp", "d_gap_hwp")
    if any(terms[key] is None for key in named):
        return {"carrier": "no_seat", "terms": terms, "single_term": None,
                "note": "a term could not be measured"}
    total = sum(terms[key] for key in named)
    significant = [key for key in named if abs(terms[key]) > tol]
    if not significant:
        carrier = "none"
    else:
        carrier = max(significant, key=lambda key: abs(terms[key]))
    return {
        "carrier": carrier,
        "terms": terms,
        "single_term": (None if not significant else len(significant) == 1),
        "identity_ok": abs(total - (row["delta"]["top_hwp"] or 0)) <= tol,
        "identity_sum_hwp": total,
    }


def first_seat_divergences(rows, tol=DEFAULT_SEAT_TOL_HWP, px_per_hwp=None):
    """Per cache page, the first paragraph whose seat differs, decomposed.

    Pages are keyed on the CACHE page because that is the reading order the
    document itself declares; a paragraph the computed pass moved to another
    page is still reported on the page the cache put it, with ``page_move``
    as its carrier.
    """
    comparable = [row for row in rows if row.get("delta") is not None]
    pages = {}
    for index, row in enumerate(comparable):
        pages.setdefault(row["cache"]["page"], []).append(index)

    reported = []
    kinds = Counter()
    carriers = Counter()
    for page in sorted(pages, key=lambda value: (value is None, value)):
        for index in pages[page]:
            row = comparable[index]
            delta = row["delta"]
            if not delta.get("page") and abs(delta.get("top_hwp") or 0) <= tol:
                continue
            prev = comparable[index - 1] if index else None
            split = decompose_seat_delta(prev, row, tol=tol)
            record = {
                "page": page,
                "paragraph": row["address"],
                "delta_top_hwp": delta["top_hwp"],
                "delta_top_px": delta["top_px"],
                "delta_page": delta["page"],
                "carrier": split["carrier"],
                "single_term": split.get("single_term"),
                "identity_ok": split.get("identity_ok"),
                "terms_hwp": split.get("terms"),
                "note": split.get("note"),
                "section_changed": (
                    None if prev is None
                    else prev.get("section") != row.get("section")),
                "this": row,
                "previous": prev,
            }
            if px_per_hwp is not None and split.get("terms"):
                record["terms_px"] = {
                    key: round(value * px_per_hwp, 3)
                    for key, value in split["terms"].items()
                    if value is not None}
            reported.append(record)
            kinds[(kind_label_of(prev), row["kind"], split["carrier"])] += 1
            carriers[split["carrier"]] += 1
            break

    histogram = [
        {"prev_kind": key[0], "kind": key[1], "carrier": key[2],
         "pages": count}
        for key, count in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    total = sum(kinds.values())
    dominant = None
    if histogram:
        top = histogram[0]
        dominant = {
            "kind": f"{top['prev_kind']} -> {top['kind']} [{top['carrier']}]",
            "carrier": top["carrier"],
            "pages": top["pages"],
            "share": round(top["pages"] / total, 6) if total else None,
        }
    return {
        "rule": SEAT_RULE,
        "key_fields": list(SEAT_KEY_FIELDS),
        "seat_tolerance_hwp": tol,
        "paragraphs_seated_both": len(comparable),
        "paragraphs_seated_neither_or_one": len(rows) - len(comparable),
        "paragraphs_with_a_seat_delta": sum(
            1 for row in comparable
            if row["delta"].get("page")
            or abs(row["delta"].get("top_hwp") or 0) > tol),
        "pages_with_a_seat_divergence": len(reported),
        "carriers": dict(sorted(carriers.items())),
        "kinds": histogram,
        "dominant_kind": dominant,
        "pages": reported,
    }


def kind_label_of(row):
    """A seat row's kind, or ``page_top`` when there is no row."""
    return "page_top" if row is None else row["kind"]


def divergence_report(hwpx_path, dpi=own_render.DEFAULT_DPI,
                      y_tol=DEFAULT_Y_TOL, include_text=True,
                      repo_root=None, attribution_tol=DEFAULT_ATTRIBUTION_TOL,
                      seat_tol=DEFAULT_SEAT_TOL_HWP, include_seat_rows=False):
    """Classify every line of one document across the two layout policies."""
    hwpx_path = Path(hwpx_path)
    cache = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_CACHE, dpi=dpi,
                        repo_root=repo_root)
    computed = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_COMPUTED,
                           dpi=dpi, repo_root=repo_root)
    cache_paras = by_paragraph(cache["line_boxes"])
    computed_paras = by_paragraph(computed["line_boxes"])
    walk = walk_paragraphs(cache_paras, computed_paras,
                           y_tol=y_tol, include_text=include_text,
                           attribution_tol=attribution_tol)
    facts = merge_facts(cache["facts"], computed["facts"])
    walk["first_drift_predecessors"] = first_drift_predecessors(
        cache_paras, computed_paras, facts,
        computed["flow_seats"], computed["px_per_hwp"], y_tol=y_tol,
        usable_height_hwp=cache["usable_height_hwp"])
    rows = seat_rows(facts, cache["cache_seats"], computed["flow_seats"],
                     cache_paras, computed_paras, computed["px_per_hwp"],
                     section_columns=computed["section_columns"])
    seats = first_seat_divergences(rows, tol=seat_tol,
                                   px_per_hwp=computed["px_per_hwp"])
    if include_seat_rows:
        seats["seat_rows"] = rows
    walk["first_seat_divergences"] = seats

    report = {
        "tool": "layout_divergence",
        "source": hwpx_path.name,
        "dpi": dpi,
        "y_tolerance_px": y_tol,
        "seat_tolerance_hwp": seat_tol,
        "text_included": include_text,
        "rule": RULE,
        "class_meaning": CLASS_MEANING,
        "pages": {"cache": cache["pages"], "computed": computed["pages"]},
        **walk,
        "iou": None,
        "iou_note": (
            "not measured: scoring both policies needs the form's Hancom "
            "reference PDF, which a classification run does not otherwise "
            "touch. Pass --iou with a reference PDF (about five times the "
            "cost of the classification), or run render_scoreboard.py "
            "--layout-policy cache/computed yourself."
        ),
    }
    return report

def add_iou(report, hwpx_path, reference_pdf, dpi=own_render.DEFAULT_DPI):
    """Score both policies against a reference PDF and record the delta.

    Kept out of ``divergence_report`` and opt-in because it needs a reference
    render the classification never touches — a holdout measured on the
    operator's machine may not have one — and because it rasterises and SSIMs
    the whole document once per policy, which is about five times the cost of
    the classification (the ten corpus forms: 17 s without, 78 s with).
    """
    import render_scoreboard

    scores = {}
    for policy in own_render.LAYOUT_POLICIES:
        scored = render_scoreboard.score_form(
            hwpx_path, reference_pdf, dpi=dpi, layout_policy=policy)
        summary = scored.get("summary") or {}
        scores[policy] = summary.get("text_line_iou_mean")
    cache_iou = scores.get(own_render.LAYOUT_POLICY_CACHE)
    computed_iou = scores.get(own_render.LAYOUT_POLICY_COMPUTED)
    delta = (round(computed_iou - cache_iou, 6)
             if cache_iou is not None and computed_iou is not None else None)
    report["iou"] = {
        "channel": "text_line_iou_mean",
        "cache": cache_iou,
        "computed": computed_iou,
        "delta": delta,
        "reference": Path(reference_pdf).name,
    }
    report["iou_note"] = ("render_scoreboard.score_form, both policies "
                          "pinned, same reference PDF")
    return report


def write_report(report, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.divergence.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    return path


def summary_line(stem, report):
    paras = report["paragraphs"]
    lines = report["lines"]
    top = report["class_b_dy_px"][0] if report["class_b_dy_px"] else None
    dominant = (f", dominant B dy {top['dy_px']:+.2f}px x{top['lines']}"
                if top else "")
    iou = report.get("iou") or {}
    iou_text = (f", IoU delta {iou['delta']:+.5f}"
                if iou.get("delta") is not None else "")
    split = (report.get("attribution") or {}).get("class_b_paragraphs") or {}
    split_text = (f" [B inherited {split.get('B_inherited', 0)} / own "
                  f"{split.get('B_own', 0)}]" if split else "")
    predecessors = report.get("first_drift_predecessors") or {}
    dominant_kind = predecessors.get("dominant_kind")
    pred_text = (
        f"; first-drift predecessor {dominant_kind['kind']} "
        f"{dominant_kind['pages']}/{predecessors['pages_with_a_predecessor']}"
        if dominant_kind else "")
    seats = report.get("first_seat_divergences") or {}
    seat_dominant = seats.get("dominant_kind")
    seat_text = (
        f"; first seat divergence {seat_dominant['kind']} "
        f"{seat_dominant['pages']}/{seats['pages_with_a_seat_divergence']}"
        if seat_dominant else "")
    return (f"{stem}: paragraphs agree {paras['agree']} / A {paras['A']} / "
            f"B {paras['B']} / C {paras['C']} (A&B {paras['A_and_B']}); "
            f"lines agree {lines['agree']} / A {lines['A']} / B {lines['B']} "
            f"/ C {lines['C']}{dominant}{split_text}{iou_text}{pred_text}"
            f"{seat_text}")


def corpus_forms(repo_root):
    """Every converted corpus form, with its reference PDF when there is one."""
    converted = Path(repo_root) / "tests" / "corpus" / "forms" / "converted"
    renders = Path(repo_root) / "tests" / "corpus" / "forms" / "render"
    out = []
    for hwpx in sorted(converted.glob("*.hwpx")):
        pdf = renders / (hwpx.stem + ".pdf")
        out.append((hwpx, pdf if pdf.is_file() else None))
    return out


def short_labels(stems):
    """Short table names for a set of form stems.

    ``admrul-gajokdolbom-hyuga-sinchengseo`` is ``admrul``; where the leading
    token is shared — the two ``gianmun`` annexes, the two ``moel`` contracts
    — the stem's last token disambiguates, giving ``gianmun-1ho`` and
    ``moel-2025``.  Derived from the stems present, never a hand-kept map.
    """
    heads = Counter(stem.split("-")[0] for stem in stems)
    labels = {}
    for stem in stems:
        parts = stem.split("-")
        labels[stem] = (parts[0] if heads[parts[0]] == 1
                        else f"{parts[0]}-{parts[-1]}")
    return labels


def corpus_table(rows):
    """A compact per-form table in #247's shape: paragraphs, not lines.

    The three attribution columns hang off the same paragraph counts: ``B_inh``
    and ``B_own`` split the ``B`` column, and ``A_sub`` is how many of the
    class-A lines reported draw at least one run on a face that is not the
    declared one.
    """
    width = max([len(name) for name, _ in rows] + [4])
    head = (f"{'form':<{width}}  {'agree':>6} {'A':>5} {'B':>5} {'C':>5} "
            f"{'A&B':>5} {'B_inh':>6} {'B_own':>6} {'A_sub':>6} {'A_ins':>6}"
            f"  {'dominant first-drift predecessor'}")
    out = [head, "-" * len(head)]
    total = Counter()
    for name, report in rows:
        paras = report["paragraphs"]
        attribution = report.get("attribution") or {}
        split = attribution.get("class_b_paragraphs") or {}
        faces = ((attribution.get("class_a_font_sources") or {})
                 .get("lines") or {})
        cells = {
            "B_inherited": split.get("B_inherited", 0),
            "B_own": split.get("B_own", 0),
            "A_substituted": faces.get("substituted", 0),
            "A_installed": faces.get("installed", 0),
        }
        predecessors = report.get("first_drift_predecessors") or {}
        dominant_kind = predecessors.get("dominant_kind")
        pred = ("-" if not dominant_kind else
                f"{dominant_kind['kind']} "
                f"{dominant_kind['pages']}/"
                f"{predecessors['pages_with_a_predecessor']}")
        out.append(f"{name:<{width}}  {paras['agree']:>6} {paras['A']:>5} "
                   f"{paras['B']:>5} {paras['C']:>5} {paras['A_and_B']:>5} "
                   f"{cells['B_inherited']:>6} {cells['B_own']:>6} "
                   f"{cells['A_substituted']:>6} {cells['A_installed']:>6}"
                   f"  {pred}")
        for key in ("agree", "A", "B", "C", "A_and_B"):
            total[key] += paras[key]
        for key, value in cells.items():
            total[key] += value
    out.append("-" * len(head))
    out.append(f"{'total':<{width}}  {total['agree']:>6} {total['A']:>5} "
               f"{total['B']:>5} {total['C']:>5} {total['A_and_B']:>5} "
               f"{total['B_inherited']:>6} {total['B_own']:>6} "
               f"{total['A_substituted']:>6} {total['A_installed']:>6}")
    return "\n".join(out)


def seat_table(rows):
    """The seat pass's own per-form table: the FIRST seat divergence.

    One row per form, and the columns are the question the pass was opened
    on: where the document's first seat difference is, how big it is, and
    which of the three terms carries it.
    """
    width = max([len(name) for name, _ in rows] + [4])
    head = (f"{'form':<{width}}  {'seats':>6} {'differ':>6} {'pages':>5} "
            f"{'1st pg':>6} {'1st para':>8} {'delta top':>10} "
            f"{'carrier':<20} {'prev -> this'}")
    out = [head, "-" * len(head)]
    for name, report in rows:
        seats = report.get("first_seat_divergences") or {}
        pages = seats.get("pages") or []
        first = pages[0] if pages else None
        if first is None:
            out.append(f"{name:<{width}}  "
                       f"{seats.get('paragraphs_seated_both', 0):>6} "
                       f"{seats.get('paragraphs_with_a_seat_delta', 0):>6} "
                       f"{0:>5} {'-':>6} {'-':>8} {'-':>10} "
                       f"{'-':<20} -")
            continue
        delta = ("page" if first["delta_top_hwp"] is None
                 else f"{first['delta_top_hwp']:+d}")
        pair = f"{kind_label_of(first['previous'])} -> {first['this']['kind']}"
        out.append(f"{name:<{width}}  "
                   f"{seats.get('paragraphs_seated_both', 0):>6} "
                   f"{seats.get('paragraphs_with_a_seat_delta', 0):>6} "
                   f"{len(pages):>5} {str(first['page']):>6} "
                   f"{first['paragraph']:>8} {delta:>10} "
                   f"{first['carrier']:<20} {pair}")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="layout_divergence.py",
        description="Classify every line-level disagreement between "
                    "own_render's cache and computed layout policies. "
                    "Measures; changes nothing.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--y-tol", type=float, default=DEFAULT_Y_TOL,
                        help="a vertical difference at or under this many "
                             "pixels is the same seat (default 0.01)")
    parser.add_argument("--attribution-tol", type=float,
                        default=DEFAULT_ATTRIBUTION_TOL,
                        help="how far a class-B paragraph's drift may sit "
                             "from what the re-breaks above it predict and "
                             "still be called inherited (default 1.0 px)")
    parser.add_argument("--seat-tol", type=float,
                        default=DEFAULT_SEAT_TOL_HWP,
                        help="a paragraph seat difference at or under this "
                             "many HWPUNIT is the same seat (default 0.5, "
                             "i.e. any difference at all — seats are "
                             "integers)")
    parser.add_argument("--seat-rows", action="store_true",
                        help="also write the seat record of EVERY top-level "
                             "paragraph, not just the reported pairs; large, "
                             "and off by default")
    parser.add_argument("--no-text", action="store_true",
                        help="omit line text from the JSON entirely")
    parser.add_argument("--corpus", action="store_true",
                        help="classify every corpus form and print a table")
    parser.add_argument("--reference", help="Hancom reference .pdf for --iou")
    parser.add_argument("--iou", action="store_true",
                        help="also score both policies against the reference "
                             "PDF: a full SSIM pass per policy, roughly five "
                             "times the cost of the classification")
    return parser


def _one(hwpx, pdf, args):
    report = divergence_report(hwpx, dpi=args.dpi, y_tol=args.y_tol,
                               include_text=not args.no_text,
                               attribution_tol=args.attribution_tol,
                               seat_tol=args.seat_tol,
                               include_seat_rows=args.seat_rows)
    if args.iou:
        if pdf is None:
            report["iou_note"] = ("--iou asked for but no reference PDF was "
                                  "given or found")
        else:
            add_iou(report, hwpx, pdf, dpi=args.dpi)
    write_report(report, args.out, hwpx.stem)
    return report


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    if args.corpus:
        forms = corpus_forms(repo_root)
        labels = short_labels([hwpx.stem for hwpx, _ in forms])
        rows = []
        for hwpx, pdf in forms:
            report = _one(hwpx, pdf, args)
            rows.append((labels[hwpx.stem], report))
            print(summary_line(labels[hwpx.stem], report))
        print()
        print(corpus_table(rows))
        print()
        print(seat_table(rows))
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    hwpx = Path(args.input)
    pdf = Path(args.reference) if args.reference else None
    report = _one(hwpx, pdf, args)
    print(summary_line(hwpx.stem, report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
