#!/usr/bin/env python3
"""Decompose every class-B paragraph's first-line ``dy`` into named terms.

``layout_divergence.py`` says WHICH paragraphs the two layout policies seat
differently, and its seat pass (#255) says which term carries the difference —
but only for TOP-LEVEL paragraphs, because a paragraph inside a table cell has
a ``vertpos`` measured from its own cell and no flow seat to put beside it.
That limit is recorded in ``own-render-notes.md`` and it is load-bearing: on
the corpus as #263 left it, 232 of the 320 class-B paragraphs are inside a
cell, so the channel that explains class B cannot see three quarters of it.

This probe answers the same question in the frame the paragraph is actually
drawn in.  Every paragraph reaches its line-drawing call through a CONTAINER —
the page body under ``_render_flow_page`` or ``_render_paragraphs``, a table
cell under ``_render_cell_content``, a header or note body under
``_draw_stacked`` — and the container hands it an origin::

    absolute top of first line
        = container_y            the container's own top
        + block_offset           the container's vertical-align offset
        + seat                   where the container seats the paragraph's
                                 block, cursor shift and all
        + first_offset           where its first line sits inside that block

Every term is read off the arguments the renderer really passed, under each
policy, so the four differences are a measurement and their sum is an
identity that ``identity_ok`` re-checks rather than asserts.  What the split
buys is WHERE the height entered:

* ``d_container_y`` — the cell moved.  Its table was placed differently, or
  the rows above it came out a different height.
* ``d_block_offset`` — the cell re-centred.  ``hp:cellzone``'s vertical
  alignment is solved against the block height that will actually be drawn,
  so a cell whose content is a different height under the two policies moves
  its content by half (CENTER) or all (BOTTOM) of the difference.
* ``d_seat`` — INHERITED.  A paragraph above it in the same container came
  out a different height and ``_render_paragraphs`` moved the cursor by the
  difference.  This term telescopes, so each step is charged to the
  predecessor that paid for it and that predecessor is named.
* ``d_first_offset`` — the paragraph's OWN.  Its first line sits at a
  different offset inside its own block.

Two things the walk refuses to do, both because doing them produced a wrong
answer on the corpus:

* it does not charge a step ACROSS a page boundary.  A seat is measured from
  the top of the page it is drawn on, so two seats on different pages are
  numbers in different frames; subtracting them telescopes into ± pairs that
  cancel and whose largest member is then charged to an innocent paragraph
  pages back.  When no predecessor on the same page paid for a paragraph's
  seat, the drift entered at the page TOP, and there are two named things to
  measure there: paragraphs the flow pass carried across the break that the
  cache left behind, and the head's own ``hh:margin/hc:prev`` space-before,
  which the cache keeps at a page top and the flow pass drops.

* it does not stop at "the table moved".  A table nested in another table's
  cell has a holder whose OWN top moved for a container reason of its own, so
  the same four-term question is asked of the holder, and of its holder,
  until a term that is not a container answers it.

Usage::

    python engine/scripts/class_b_probe.py --corpus
    python engine/scripts/class_b_probe.py --corpus --table-origin
    python engine/scripts/class_b_probe.py --corpus --page-top
    python engine/scripts/class_b_probe.py --corpus --empty
    python engine/scripts/class_b_probe.py --corpus --line-height
    python engine/scripts/class_b_probe.py --corpus --valign
    python engine/scripts/class_b_probe.py --corpus --json out.json
    python engine/scripts/class_b_probe.py path/to/doc.hwpx

The probe renders each form once per policy, exactly as ``layout_divergence``
does, and writes nothing back into either renderer, so it cannot perturb what
``render_scoreboard.py`` or ``layout_divergence.py`` report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout_divergence  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

#: A term at or under this many HWPUNIT is no term.  Origins, offsets and
#: lineseg tops are integers on both sides, so 0.5 means "any at all".
DEFAULT_TOL_HWP = 0.5

RULE = (
    "per class-B paragraph, in the container that draws it: d_top = "
    "d_container_y + d_block_offset + d_seat + d_first_offset, every term "
    "read off the arguments the render path passed under each policy. "
    "d_seat telescopes over the container, so each step is charged to the "
    "predecessor that paid for it and that predecessor is named.")


class SeatingRenderer(layout_divergence.TracingRenderer):
    """``TracingRenderer`` that also records how each paragraph was seated.

    The three container entry points are wrapped to keep a stack of
    ``(container top, vertical-align offset)``, and both line-drawing entry
    points are wrapped again — the base class needs its own wrapping to tag
    line boxes — to record the origin each paragraph was handed against the
    container it was handed it in.  A paragraph the cache carries across a
    page break arrives twice; the FIRST arrival is its seat and
    ``setdefault`` keeps it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: ``{address: seat record}`` — see the module docstring for the terms.
        self.paragraph_origins = {}
        #: ``{id(hp:tc): {y0, row, col, table, table_y}}`` under this policy.
        self.cell_boxes = {}
        #: ``{address: [line record]}`` — the SPAN and the metrics of every
        #: line each paragraph actually drew under this policy.  The span is
        #: the load-bearing half: ``_line_metrics`` is handed ``[start, end)``
        #: and answers for the characters in it, so a line that is a different
        #: HEIGHT because it holds different CHARACTERS is a break difference
        #: wearing a height difference's label, and only the span tells them
        #: apart.
        self.paragraph_lines = {}
        #: ``{id(hp:tc): {vertAlign, avail_h, block extent, offset}}`` — the
        #: four numbers ``_render_cell_content`` solves a cell's vertical
        #: alignment from, recorded as it solves them.
        self.cell_valign = {}
        #: Set while a ``_render_cell_content`` call is in flight, so the
        #: block extent that call measures can be read off the shared
        #: ``_paragraph_block_extent`` without measuring the cell twice.  The
        #: FIRST call under the flag is this cell's; a nested table's cells
        #: raise the flag again for themselves.
        self._want_block_extent = False
        self._last_block_extent = None
        self._container_stack = [(0, 0)]
        self._table_origin = None
        self._floating_para = None
        #: ``{table address: seat record}`` — how each table was placed.
        self.table_seats = {}
        #: Document-order index over ``hp:tbl``, the join key across policies.
        #: ``id()`` is per-render, so the tables have to be numbered the way
        #: ``paragraph_index`` numbers paragraphs before either policy's
        #: record can be put beside the other's.  Built on first use because
        #: the section trees are loaded lazily, exactly as they are there.
        self._table_index = None
        self._awaiting_tbl = None

    @property
    def table_index(self):
        if self._table_index is None:
            self._table_index = {
                id(el): index
                for index, el in enumerate(
                    e for section in self.sections for e in section.iter()
                    if own_render._local(e.tag) == "tbl")
            }
        return self._table_index

    # -- containers ------------------------------------------------------
    def _render_flow_page(self, draw, records, origin_hwp, avail_w_hwp):
        self._container_stack.append((origin_hwp[1], 0))
        try:
            return super()._render_flow_page(draw, records, origin_hwp,
                                             avail_w_hwp)
        finally:
            self._container_stack.pop()

    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        self._container_stack.append((origin_hwp[1], block_offset_hwp))
        try:
            return super()._render_paragraphs(draw, paragraphs, origin_hwp,
                                              avail_w_hwp, block_offset_hwp)
        finally:
            self._container_stack.pop()

    def _render_floating(self, draw, para, origin_hwp, *args, **kwargs):
        """An anchored object is drawn outside any line, so latch its owner.

        An INLINE object is drawn from inside ``_draw_line`` and the base
        class' ``_tracing_para`` already names its paragraph; an anchored one
        is not, and this is the only place its paragraph is in scope.
        """
        outer, self._floating_para = self._floating_para, para
        try:
            return super()._render_floating(draw, para, origin_hwp,
                                            *args, **kwargs)
        finally:
            self._floating_para = outer

    def _table_tracks(self, draw, tbl, **kwargs):
        """Latch the row track the table was actually laid out on.

        ``_render_table`` asks for the tracks before it draws anything, so
        the first call after a ``_render_table`` entry is that table's own and
        a nested table's call cannot be mistaken for it.  The last ``ys`` is
        the table's drawn height, which is the term (c) of the origin
        question — a table above this one being taller moves this one down.
        """
        xs, ys, cells = super()._table_tracks(draw, tbl, **kwargs)
        if self._awaiting_tbl is not None and self._awaiting_tbl == id(tbl):
            self._awaiting_tbl = None
            record = self.table_seats.get(self.table_index.get(id(tbl)))
            if record is not None:
                record["height_hwp"] = ys[-1] if ys else 0
                record["rows"] = max(0, len(ys) - 1)
                record["cols"] = max(0, len(xs) - 1)
                record["col_edges_hwp"] = list(xs)
                record["row_edges_hwp"] = list(ys)
        return xs, ys, cells

    def _render_table(self, draw, tbl, origin_hwp):
        holder = self._floating_para or self._tracing_para
        address = (self.paragraph_index.get(id(holder.el))
                   if holder is not None else None)
        self._note_table_seat(tbl, origin_hwp, address,
                              anchored=self._floating_para is not None)
        outer = self._table_origin
        outer_await = self._awaiting_tbl
        self._table_origin = (id(tbl), origin_hwp[1], address)
        self._awaiting_tbl = id(tbl)
        try:
            return super()._render_table(draw, tbl, origin_hwp)
        finally:
            self._table_origin = outer
            self._awaiting_tbl = outer_await

    def _note_table_seat(self, tbl, origin_hwp, holder, anchored):
        """Where this table was seated, and everything that decided it.

        ``origin_hwp`` is the object BOX's top-left — ``_object_origin`` has
        already inset it by ``hp:outMargin@left/top`` — so the SLOT the
        placement path chose is ``origin - outMargin``, and that is the number
        the two policies have to be compared on: the box offset is a constant
        of the document and cannot move between them.
        """
        index = self.table_index.get(id(tbl))
        if index is None or index in self.table_seats:
            return
        pos = own_render._kid(tbl, "pos")
        margin = self._object_out_margin(tbl)
        sz = own_render._kid(tbl, "sz")
        self.table_seats[index] = {
            "table": index,
            "page": self._page,
            "holder": holder,
            "anchored": bool(anchored),
            "inline": bool(self._table_is_inline(tbl)),
            "box_y_hwp": origin_hwp[1],
            "box_x_hwp": origin_hwp[0],
            "slot_y_hwp": origin_hwp[1] - margin[1],
            "out_margin_hwp": {"left": margin[0], "top": margin[1],
                               "right": margin[2], "bottom": margin[3]},
            "declared_height_hwp": (own_render._iattr(sz, "height")
                                    if sz is not None else None),
            "declared_width_hwp": (own_render._iattr(sz, "width")
                                   if sz is not None else None),
            "tree_level": tbl.get("treeLevel"),
            "page_break": tbl.get("pageBreak"),
            "text_wrap": tbl.get("textWrap"),
            "pos": (None if pos is None else {
                "treatAsChar": pos.get("treatAsChar"),
                "vertRelTo": pos.get("vertRelTo"),
                "horzRelTo": pos.get("horzRelTo"),
                "vertAlign": pos.get("vertAlign"),
                "horzAlign": pos.get("horzAlign"),
                "vertOffset": own_render._iattr(pos, "vertOffset"),
                "horzOffset": own_render._iattr(pos, "horzOffset"),
                "flowWithText": pos.get("flowWithText"),
                "affectLSpacing": pos.get("affectLSpacing"),
                "allowOverlap": pos.get("allowOverlap"),
            }),
        }

    def _paragraph_block_extent(self, draw, paras, avail_w_hwp):
        extent = super()._paragraph_block_extent(draw, paras, avail_w_hwp)
        if self._want_block_extent:
            self._want_block_extent = False
            self._last_block_extent = extent
        return extent

    def _render_cell_content(self, draw, cell, x0, y0, x1, y1):
        table, table_y, holder = self._table_origin or (None, None, None)
        self.cell_boxes.setdefault(id(cell["tc"]), {
            "row": cell["row"],
            "col": cell["col"],
            "y0_hwp": y0,
            "margin_top_hwp": cell["margin"]["top"],
            "table": table,
            "table_y_hwp": table_y,
            "holder": holder,
            "page": self._page,
        })
        margin = cell["margin"]
        sub = own_render._kid(cell["tc"], "subList")
        valign = ((sub.get("vertAlign") if sub is not None else "TOP")
                  or "TOP").upper()
        avail_h = max(0, (y1 - y0) - margin["top"] - margin["bottom"])
        outer_want, outer_last = self._want_block_extent, self._last_block_extent
        self._want_block_extent, self._last_block_extent = True, None
        try:
            result = super()._render_cell_content(draw, cell, x0, y0, x1, y1)
            block = self._last_block_extent
        finally:
            self._want_block_extent = outer_want
            self._last_block_extent = outer_last
        cached_block = max([para.extent_hwp() for para in cell["paras"]]
                           or [0])
        offset = 0
        if block is not None:
            if valign == "CENTER":
                offset = max(0, (avail_h - block) // 2)
            elif valign == "BOTTOM":
                offset = max(0, avail_h - block)
        self.cell_valign.setdefault(id(cell["tc"]), {
            "row": cell["row"],
            "col": cell["col"],
            "table": self.table_index.get(table) if table is not None else None,
            "vert_align": valign,
            "cell_height_hwp": y1 - y0,
            "avail_height_hwp": avail_h,
            "declared_height_hwp": cell.get("declared_height"),
            "margin_top_hwp": margin["top"],
            "margin_bottom_hwp": margin["bottom"],
            "block_extent_hwp": block,
            "cached_block_extent_hwp": cached_block,
            "offset_hwp": offset,
            "paragraphs": len(cell["paras"]),
            "page": self._page,
        })
        return result

    # -- paragraphs ------------------------------------------------------
    def _render_cached_lines(self, draw, para, origin_hwp, *args, **kwargs):
        # The cached path draws line i at origin + lineseg[i]@vertpos, so the
        # paragraph's block starts at its first lineseg and its first line
        # sits at offset 0 inside it, by definition.
        seat = origin_hwp[1] + (own_render._iattr(para.linesegs[0], "vertpos")
                                if para.linesegs else 0)
        advance = sum(own_render._iattr(seg, "vertsize")
                      + own_render._iattr(seg, "spacing")
                      for seg in para.linesegs)
        self._note_lines(para, [
            {"start": start, "end": end,
             "vertpos_hwp": own_render._iattr(seg, "vertpos"),
             "vertsize_hwp": own_render._iattr(seg, "vertsize"),
             "textheight_hwp": own_render._iattr(seg, "textheight"),
             "baseline_hwp": own_render._iattr(seg, "baseline"),
             "spacing_hwp": own_render._iattr(seg, "spacing")}
            for (start, end), seg in zip(para.lineseg_spans(), para.linesegs)
        ], "lineseg")
        self._note_origin(para, seat, 0, len(para.linesegs), advance,
                          "lineseg")
        return super()._render_cached_lines(draw, para, origin_hwp,
                                            *args, **kwargs)

    def _render_computed_lines(self, draw, para, origin_hwp, lines,
                               *args, **kwargs):
        rows = kwargs.get("rows")
        if rows is None and args:
            rows = args[0]
        # The container path rebases onto the paragraph's cached top; the flow
        # path hands an absolute one.  Mirror ``_render_computed_lines``
        # rather than guess which it was.  Either way the paragraph's BLOCK
        # top is that origin and ``lines[0]["vertpos"]`` is where its first
        # line sits inside the block — the same convention as the cached path,
        # which is what makes the two seats comparable.
        rebase = (own_render._iattr(para.linesegs[0], "vertpos")
                  if para.linesegs and rows is None else 0)
        advance = sum(line["vertsize"] + line["spacing"]
                      for line in lines or ())
        self._note_lines(para, [
            {"start": line["start"], "end": line["end"],
             "vertpos_hwp": line["vertpos"],
             "vertsize_hwp": line["vertsize"],
             "textheight_hwp": line["textheight"],
             "baseline_hwp": line["baseline"],
             "spacing_hwp": line["spacing"]}
            for line in lines or ()
        ], "computed")
        self._note_origin(para, origin_hwp[1] + rebase,
                          (lines[0]["vertpos"] if lines else 0),
                          len(lines or ()), advance, "computed")
        return super()._render_computed_lines(draw, para, origin_hwp, lines,
                                              *args, **kwargs)

    def _note_lines(self, para, lines, mode):
        """``paragraph_lines[address]`` — the spans and metrics actually drawn.

        ``setdefault`` for the same reason ``_note_origin`` uses it: a
        paragraph the cache carries across a page break arrives twice and the
        first arrival is the one the seat was measured against.
        """
        address = self.paragraph_index.get(id(para.el))
        if address is None or not lines:
            return
        self.paragraph_lines.setdefault(address, {"mode": mode,
                                                  "lines": lines})

    def _note_origin(self, para, block_top, first_offset, line_count, advance,
                     mode):
        address = self.paragraph_index.get(id(para.el))
        if address is None:
            return
        container_y, block_offset = self._container_stack[-1]
        self.paragraph_origins.setdefault(address, {
            "address": address,
            "page": self._page,
            "container_y_hwp": container_y,
            "block_offset_hwp": block_offset,
            "seat_hwp": block_top - container_y - block_offset,
            "first_offset_hwp": first_offset,
            "abs_top_hwp": block_top + first_offset,
            "line_count": line_count,
            "advance_hwp": advance,
            "mode": mode,
        })


def parent_map(sections):
    """``{id(child): parent element}`` over every section tree.

    ``xml.etree`` elements carry no parent pointer, and the container a
    paragraph is drawn in is exactly its parent element — the section for a
    body paragraph, the ``hp:subList`` of a cell, a header or a note body for
    the rest.
    """
    parents = {}
    for section in sections:
        for element in section.iter():
            for child in element:
                parents[id(child)] = element
    return parents


def containers(renderer):
    """``{address: container key}``, and the cell each container belongs to.

    The key is the paragraph's parent element.  It is an ``id()`` and so is
    only comparable within one render, which is why both policies' maps are
    built and the join is on the paragraph ADDRESS, never on the key.
    """
    parents = parent_map(renderer.sections)
    keys = {}
    cells = {}
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(element))
            if address is None:
                continue
            parent = parents.get(id(element))
            keys[address] = id(parent) if parent is not None else None
            # A cell paragraph's parent is the hp:subList of an hp:tc.
            grand = parents.get(id(parent)) if parent is not None else None
            if grand is not None and own_render._local(grand.tag) == "tc":
                cells[address] = id(grand)
    return keys, cells


def _own_inkless_metrics(renderer):
    """``{address: {textheight, vertsize, baseline, spacing}}`` for INKLESS ``hp:p``.

    ``_line_metrics(para, 0, 0)`` IS the renderer's empty-paragraph rule — the
    same call ``_flow_lines`` makes on a paragraph that has neither characters
    nor a cached ``hp:linesegarray``.  Asking it here, of every paragraph with
    no characters at all, states our height for one WITHOUT letting the cache
    answer on our behalf, which is the only way path B can be put beside path A
    on a document the authoring engine saved.

    A paragraph holding an object is excluded: its character stream is not
    empty (the object occupies a slot), so its height is the object seam's
    question and not this one's.
    """
    out = {}
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(element))
            if address is None:
                continue
            para = own_render.Paragraph(element, renderer.defs["para_pr"])
            if para.chars:
                continue
            textheight, vertsize, baseline, spacing = renderer._line_metrics(
                para, 0, 0)
            out[address] = {"textheight_hwp": textheight,
                            "vertsize_hwp": vertsize,
                            "baseline_hwp": baseline,
                            "spacing_hwp": spacing,
                            "advance_hwp": vertsize + spacing}
    return out


def _cached_span_metrics(renderer):
    """PATH A for the line HEIGHT: our rule, on the cache's own line spans.

    ``_line_metrics(para, start, end)`` answers for the characters in
    ``[start, end)``, so putting our answer beside the cached ``hp:lineseg``
    is only a test of the height RULE when both are asked about the same
    characters.  ``lineseg_spans()`` reconstructs the cache's spans from
    ``@textpos``, so this asks our rule the cache's own question and the
    residual it reports is the rule's alone — no break difference can leak
    into it.

    That separation is the whole point of the ``--line-height`` view: the
    same paragraph measured on OUR spans mixes two faults, and the corpus has
    one of each.

    ``{address: {lines: [...], exact, total}}``.
    """
    out = {}
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(element))
            if address is None:
                continue
            para = own_render.Paragraph(element, renderer.defs["para_pr"])
            if not para.linesegs or not para.chars:
                continue
            lines = []
            for (start, end), seg in zip(para.lineseg_spans(), para.linesegs):
                textheight, vertsize, baseline, spacing = \
                    renderer._line_metrics(para, start, end)
                cached_vertsize = own_render._iattr(seg, "vertsize")
                cached_spacing = own_render._iattr(seg, "spacing")
                # A cached boundary that has CELLS between it and the last
                # character before it has a control sitting on it — an
                # ``hp:lineBreak`` and its kind take a ``textpos`` cell and
                # put nothing in ``chars``.  ``cell_start`` is the renderer's
                # own bookkeeping for exactly that, so this is read off it
                # rather than re-walked.
                control_before = 0
                if 0 < start < len(para.cell_start):
                    control_before = (para.cell_start[start]
                                      - para.cell_start[start - 1] - 1)
                lines.append({
                    "span": [start, end],
                    "control_cells_before_start": control_before,
                    "vertsize_hwp": vertsize,
                    "textheight_hwp": textheight,
                    "baseline_hwp": baseline,
                    "spacing_hwp": spacing,
                    "cached_vertsize_hwp": cached_vertsize,
                    "cached_textheight_hwp": own_render._iattr(seg,
                                                               "textheight"),
                    "cached_baseline_hwp": own_render._iattr(seg, "baseline"),
                    "cached_spacing_hwp": cached_spacing,
                    "exact": (vertsize == cached_vertsize
                              and spacing == cached_spacing),
                })
            out[address] = {
                "lines": lines,
                "exact": sum(1 for line in lines if line["exact"]),
                "total": len(lines),
            }
    return out


def _run_declarations(renderer, element):
    """What each ``hp:run`` of one paragraph DECLARES about its line height.

    Everything the height rule could read and everything it deliberately does
    not: ``hh:charPr@height`` (which it reads), ``hh:ratio`` / ``hh:relSz``
    (which it excludes — see ``_line_metrics``' docstring), the ``hh:fontRef``
    face per language slot, and whether that face is metered off the measured
    HFT table or off an installed/bundled file.  A mechanism that turned out
    to be one of the excluded ones would show up here as the only thing the
    carriers have in common.
    """
    runs = []
    for run in element.iter():
        if own_render._local(run.tag) != "run":
            continue
        cid = run.get("charPrIDRef")
        pr = renderer._charpr(cid)
        text = "".join(node for node in run.itertext())
        hft = None
        for ch in text:
            face = renderer._declared_hft_face(cid, ch)
            if face:
                hft = face
                break
        typography = pr.get("typography") or {}
        slot = own_render.script_slot(text[0]) if text else "hangul"
        bold = bool(pr.get("bold"))
        renderer._face_for(cid, slot, bold)
        resolved = renderer._face_cache.get((cid, slot, bold))
        face = resolved[1] if resolved else None
        runs.append({
            "charpr": cid,
            "face_source": (face or {}).get("source"),
            "face_declared": (face or {}).get("declared"),
            "height_pt": pr.get("height_pt"),
            "height_hwp": (None if pr.get("height_pt") is None else
                           int(round(pr["height_pt"]
                                     * own_render.HWPUNIT_PER_PT))),
            "characters": len(text),
            "empty": not text,
            "font_ids": pr.get("font_ids"),
            "ratio": (typography.get("ratio") or {}).get("hangul"),
            "rel_sz": (typography.get("relSz") or {}).get("hangul"),
            "spacing": (typography.get("spacing") or {}).get("hangul"),
            "hft_face": hft,
        })
    return runs


def _paragraph_declarations(renderer):
    """``{address: {para: ..., runs: [...]}}`` — everything a height could read.

    The paragraph half carries the two ``hh:paraPr`` attributes that could
    change a line's height and are not already in ``paragraph_facts``:
    ``@snapToGrid``, which the renderer declares it does not implement, and
    ``@fontLineHeight``, which it declares the same way.
    """
    out = {}
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(element))
            if address is None:
                continue
            para = own_render.Paragraph(element, renderer.defs["para_pr"])
            pr = para.para_pr
            out[address] = {
                "para": {
                    "snap_to_grid": pr.get("snap_to_grid"),
                    "font_line_height": pr.get("font_line_height"),
                    "condense": pr.get("condense"),
                    "line_spacing_type": pr.get("line_spacing_type"),
                    "line_spacing_value": pr.get("line_spacing_value"),
                    "line_spacing_unit": pr.get("line_spacing_unit"),
                },
                "runs": _run_declarations(renderer, element),
            }
    return out


def _section_grids(renderer):
    """``{section index: hp:secPr/hp:grid attributes}``.

    ``hp:paraPr@snapToGrid`` is one of the renderer's declared skips, so a
    paragraph that sets it is a candidate mechanism on its face.  It is only a
    mechanism if the SECTION actually has a grid: ``lineGrid``/``charGrid`` at
    zero is "no grid", and snapping to nothing is a no-op however the flag is
    set.  Both halves are reported so the reader does not have to take the
    negative on trust.
    """
    out = {}
    for index, section in enumerate(renderer.sections):
        record = None
        for element in section.iter():
            if own_render._local(element.tag) != "secPr":
                continue
            for kid in element:
                if own_render._local(kid.tag) == "grid":
                    record = {
                        "line_grid": own_render._iattr(kid, "lineGrid"),
                        "char_grid": own_render._iattr(kid, "charGrid"),
                        "wonggoji": own_render._iattr(kid, "wonggojiFormat"),
                    }
                    break
            break
        out[index] = record
    return out


def trace(hwpx_path, policy, dpi, repo_root=None):
    """One render under one policy: seats, cell boxes, line boxes, facts."""
    renderer = SeatingRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                               layout_policy=policy)
    _images, sidecar = renderer.render()
    geometry = renderer.page_geometry()
    keys, cells = containers(renderer)
    facts = renderer.paragraph_facts()
    # ``hp:tab`` is the one control this renderer declares it does not place,
    # and a re-break has a different name depending on whether the paragraph
    # carries one.  ``paragraph_facts`` does not carry the count, so read it
    # off the tree the same way ``Paragraph`` does.
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            address = renderer.paragraph_index.get(id(element))
            if address is None or address not in facts:
                continue
            facts[address]["tabs"] = sum(
                1 for node in element.iter()
                if own_render._local(node.tag) == "tab")
            # ``hp:lineBreak`` for the same reason: it takes a ``textpos``
            # cell (``TEXTPOS_CELLS_CHAR``), so the CACHE's spans break at it,
            # and it is not in the character stream at all, so ours cannot.
            # Whether a span difference sits on one is the question the
            # ``--line-height`` view exists to answer.
            facts[address]["line_breaks"] = sum(
                1 for node in element.iter()
                if own_render._local(node.tag) == "lineBreak")
    return {
        # What THIS renderer's own empty-paragraph rule (#247's empty-run pass,
        # reached through #261's inkless branch) makes of every paragraph that
        # puts no character on its line.  It is the only number that states our
        # height for such a paragraph independently of the cache: ``_flow_lines``
        # falls back on the cached ``hp:lineseg`` whenever there is one, so a
        # document Hancom saved never exercises the rule and the two policies
        # agree on the height by construction rather than by agreement.
        "own_inkless_metrics": _own_inkless_metrics(renderer),
        # PATH A for the height rule, and the spans each policy actually drew.
        # Kept apart on purpose: the first is our rule on the CACHE's spans,
        # the second is what our own break pass handed it.
        "cached_span_metrics": _cached_span_metrics(renderer),
        "paragraph_lines": dict(renderer.paragraph_lines),
        "cell_valign": dict(renderer.cell_valign),
        "section_grids": _section_grids(renderer),
        "declarations": _paragraph_declarations(renderer),
        "origins": dict(renderer.paragraph_origins),
        "cell_boxes": dict(renderer.cell_boxes),
        "table_seats": dict(renderer.table_seats),
        "table_of_cell": {
            cell_id: renderer.table_index.get(box["table"])
            for cell_id, box in renderer.cell_boxes.items()
            if box.get("table") is not None
        },
        "line_boxes": sidecar.get("line_boxes") or [],
        "facts": facts,
        "containers": keys,
        "cell_of": cells,
        # The seat pass' own two channels.  A paragraph with no characters
        # never reaches a line-drawing call and so has no origin, but it does
        # have a seat under both policies, and on the corpus those paragraphs
        # are most of what sits between a class-B paragraph and its cause.
        "flow_seats": dict(renderer.flow_seats),
        "cache_seats": dict(renderer.cache_seats),
        "px_per_hwp": dpi / own_render.HWPUNIT_PER_INCH,
        # The page box, for the page-top and page-bottom passes: a seat is
        # only a page top relative to a usable height, and a space-after is
        # only "reserved" relative to the same number.
        "usable_height_hwp": max(1, geometry["usable_height"]),
        "col_count": renderer.column_geometry(geometry)[2],
    }


def top_level_seats(cache, computed):
    """``{address: (d_seat, before, after, page)}`` for TOP-LEVEL paragraphs.

    The cache seat is the paragraph's first ``hp:lineseg@vertpos``, measured
    from the body top, and the computed one is where the flow pass placed its
    block: exactly the pair ``layout_divergence``'s seat pass compares, reused
    here rather than re-derived.  Under ``cache`` no top-level paragraph is
    relaid out, so the cursor never shifts and this agrees with the drawn
    origin wherever both exist; what it adds is the paragraphs that draw
    nothing at all.

    Both seats are measured from the top of the paragraph's OWN page, so the
    page comes back with them: two seats on different pages are numbers in
    different frames and subtracting them is not a step (``decompose``).
    """
    grouped = layout_divergence._flow_seats_by_address(computed["flow_seats"])
    out = {}
    for address, fact in (computed["facts"] or {}).items():
        if not fact.get("top_level"):
            continue
        earlier = layout_divergence._cache_seat(fact, cache["cache_seats"],
                                                address)
        later = layout_divergence._computed_seat(grouped.get(address))
        if earlier is None or later is None:
            continue
        if earlier["page"] != later["page"]:
            continue
        out[address] = (later["top_hwp"] - earlier["top_hwp"],
                        {"line_count": len(fact.get("linesegs") or []),
                         "advance_hwp": earlier.get("advance_hwp")},
                        {"line_count": later.get("records"),
                         "advance_hwp": later.get("advance_hwp")},
                        later["page"])
    return out


def _obj_kind(fact):
    kinds = [obj["kind"] for obj in fact.get("objects") or ()]
    return kinds[0] if kinds else None


def mechanism(fact, cache, computed, tol=DEFAULT_TOL_HWP):
    """One label for WHY this paragraph is a different height, and its detail.

    The order is the order the layout engine meets them in: a forced break
    beats everything because it decides the page before any height is asked
    for, an object placed outside the line beats one inside it, an object
    inside the line beats the text around it, and a paragraph with no
    characters at all is its own case because its height comes from the empty
    run's declared ``charPr`` and nothing else.  Only then does the text
    answer, and it answers twice: the break moved (a different line count) or
    the same lines came out a different height.
    """
    anchor = fact.get("anchor_kind") or "none"
    detail = {
        "anchor_kind": anchor,
        "characters": fact.get("characters"),
        "line_spacing_type": fact.get("line_spacing_type"),
        "line_spacing_value": fact.get("line_spacing_value"),
        "margin_prev_hwp": fact.get("margin_prev_hwp"),
        "margin_next_hwp": fact.get("margin_next_hwp"),
        "cache_lines": (cache or {}).get("line_count"),
        "computed_lines": (computed or {}).get("line_count"),
        "cache_advance_hwp": (cache or {}).get("advance_hwp"),
        "computed_advance_hwp": (computed or {}).get("advance_hwp"),
    }
    for flag in ("page_break_before", "column_break", "keep_with_next",
                 "keep_lines", "widow_orphan"):
        if fact.get(flag):
            detail[flag] = True
    if fact.get("page_break_before") or fact.get("column_break"):
        return "forced_break", detail
    if anchor.startswith("anchored:"):
        detail["objects"] = fact.get("objects") or []
        return f"anchored_object:{_obj_kind(fact)}", detail
    if anchor.startswith("inline:"):
        detail["objects"] = fact.get("objects") or []
        return f"inline_object:{_obj_kind(fact)}", detail
    if fact.get("empty_text"):
        detail["empty_runs"] = fact.get("empty_runs") or []
        return "empty_paragraph", detail
    cache_n = (cache or {}).get("line_count")
    computed_n = (computed or {}).get("line_count")
    if cache_n is not None and computed_n is not None and cache_n != computed_n:
        detail["line_delta"] = computed_n - cache_n
        # A re-break splits two ways and the split matters: a paragraph
        # carrying ``hp:tab`` is one this renderer DECLARES it cannot measure
        # (``_skip("hp:tab", ...)``: the control is not placed in the
        # character stream, so the line it sits on is measured without it),
        # and a paragraph with no tab in it re-broke on glyph advances alone.
        if fact.get("tabs"):
            detail["tabs"] = fact["tabs"]
            return "text_rebreak:tab", detail
        return "text_rebreak:width", detail
    cache_adv = (cache or {}).get("advance_hwp")
    computed_adv = (computed or {}).get("advance_hwp")
    if (cache_adv is not None and computed_adv is not None
            and abs(computed_adv - cache_adv) > tol):
        detail["advance_delta_hwp"] = computed_adv - cache_adv
        return "text_line_height", detail
    # The predecessor is the same height under both policies, so the step it
    # was charged with is the SPACE between the two paragraphs and not the
    # paragraph itself.
    return "interparagraph_gap", detail


def class_b_addresses(cache_boxes, computed_boxes, y_tol):
    """``{address: its first class-B line}`` — the population to explain."""
    cache_paras = layout_divergence.by_paragraph(cache_boxes)
    computed_paras = layout_divergence.by_paragraph(computed_boxes)
    out = {}
    for address in sorted(set(cache_paras) | set(computed_paras)):
        rows = layout_divergence.classify_paragraph(
            cache_paras.get(address) or [], computed_paras.get(address) or [],
            y_tol=y_tol)
        for row in rows:
            if row["class"] != "B":
                continue
            out[address] = {
                "line": row["line"],
                "page": row["cache"]["page"],
                "dy_px": round(row["computed"]["y0"] - row["cache"]["y0"], 3),
            }
            break
    return out


def _cell_terms(address, cache, computed, tol):
    """Why a cell's own top moved: the table, or the rows above it."""
    cell_id_cache = cache["cell_of"].get(address)
    cell_id_computed = computed["cell_of"].get(address)
    if cell_id_cache is None or cell_id_computed is None:
        return None
    a = cache["cell_boxes"].get(cell_id_cache)
    b = computed["cell_boxes"].get(cell_id_computed)
    if a is None or b is None:
        return None
    d_table = None
    if a.get("table_y_hwp") is not None and b.get("table_y_hwp") is not None:
        d_table = b["table_y_hwp"] - a["table_y_hwp"]
    d_cell = b["y0_hwp"] - a["y0_hwp"]
    terms = {
        "row": a["row"],
        "col": a["col"],
        "d_cell_y_hwp": d_cell,
        "d_table_y_hwp": d_table,
        "d_row_top_hwp": (None if d_table is None else d_cell - d_table),
    }
    terms["holder"] = b.get("holder")
    if d_table is not None and abs(d_table) > tol:
        terms["carrier"] = "table_origin"
    elif terms["d_row_top_hwp"] and abs(terms["d_row_top_hwp"]) > tol:
        terms["carrier"] = "table_row_heights"
    else:
        terms["carrier"] = "none"
    return terms


def _largest(carriers):
    """The carrier that paid for most of the step, or ``None``."""
    if not carriers:
        return None
    return max(carriers, key=lambda entry: abs(entry["step_hwp"]))


def _root(record, tol, holder_root=None, seat_root=None):
    """ONE mechanism per class-B paragraph: the biggest term, followed down.

    The histogram over ``mechanisms`` books a paragraph under every mechanism
    it inherits from, which is honest but does not rank.  This picks the term
    that carries most of the paragraph's ``dy``, follows a moved table up to
    the paragraph that holds it, and names what it finds there — so the roots
    partition the population and can be counted against each other.

    ``holder_root`` and ``seat_root`` are the two places the walk can run out
    of record and has to go back to the trace: a holder whose own top moved
    for a container reason of its own (a table nested in a table's cell), and
    a paragraph seated first on its page, with no predecessor to charge.
    ``decompose`` supplies both; without them this falls back to the answer
    the record alone supports, which is what the unit tests pin.
    """
    term = record.get("carrier_term")
    if term == "d_container_y_hwp":
        cell = record.get("cell") or {}
        if cell.get("carrier") == "table_origin":
            if holder_root is not None:
                return holder_root(cell.get("holder"))
            largest = _largest((record.get("holder") or {}).get("carriers"))
            return (largest["mechanism"] if largest
                    else "table_origin_unattributed")
        return "table_row_heights" if cell.get("carrier") else "cell_unattributed"
    if term == "d_block_offset_hwp":
        return "cell_valign"
    if term == "d_seat_hwp":
        largest = _largest(record.get("carriers"))
        if largest:
            return largest["mechanism"]
        if seat_root is not None:
            return seat_root(record["paragraph"])
        return "seat_unattributed"
    if term == "d_first_offset_hwp":
        return "own:" + (record.get("own_mechanism") or "unknown")
    return "unattributed"


def decompose(cache, computed, y_tol, tol=DEFAULT_TOL_HWP):
    """Every class-B paragraph, split into its four terms and attributed."""
    px_per_hwp = computed["px_per_hwp"]
    facts = computed["facts"]
    keys = computed["containers"]
    targets = class_b_addresses(cache["line_boxes"], computed["line_boxes"],
                                y_tol)

    #: ``{address: d_seat}`` for every paragraph seated on the same page
    #: under both policies — the only pairs whose terms are comparable.
    d_seat = {}
    #: ``{address: page}`` for every seat in ``d_seat``.  A seat is measured
    #: from the top of the container on the page it was drawn on, so two
    #: seats on different pages are numbers in different frames.
    page_of = {}
    for address, later in computed["origins"].items():
        earlier = cache["origins"].get(address)
        if earlier is None or later["page"] != earlier["page"]:
            continue
        d_seat[address] = later["seat_hwp"] - earlier["seat_hwp"]
        page_of[address] = later["page"]
    #: Per-address metrics for ``mechanism``, preferring what was drawn.
    metrics = {"cache": dict(cache["origins"]),
               "computed": dict(computed["origins"])}
    for address, (delta, before, after, page) in top_level_seats(
            cache, computed).items():
        d_seat[address] = delta
        page_of[address] = page
        metrics["cache"].setdefault(address, before)
        metrics["computed"].setdefault(address, after)

    by_container = {}
    for address, key in keys.items():
        by_container.setdefault(key, []).append(address)
    for addresses in by_container.values():
        addresses.sort()

    #: ``{container: {address: the step this paragraph contributed}}``.  A
    #: paragraph with no characters never reaches a line-drawing call and so
    #: has no d_seat of its own; it is stepped OVER rather than breaking the
    #: chain, because the cursor it did not move is exactly the point.  A page
    #: boundary is NOT stepped over: the cursor is reset there, both seats are
    #: measured from the new page's own top, and their difference is a change
    #: of frame rather than a height anybody paid for.  Charging it produced
    #: the one attribution this probe was found to get wrong — moel-2025's
    #: page-7 table was charged to a paragraph on page 3.
    steps = {}
    for key, addresses in by_container.items():
        previous = None
        for address in addresses:
            here = d_seat.get(address)
            if here is None:
                continue
            if previous is not None:
                prior_address, prior = previous
                if page_of.get(prior_address) == page_of.get(address):
                    steps.setdefault(key, {})[prior_address] = here - prior
            previous = (address, here)

    def carriers_for(address):
        """Every predecessor in ``address``' container charged with a step."""
        found = []
        for prior in by_container.get(keys.get(address), ()):
            if prior >= address:
                break
            if page_of.get(prior) != page_of.get(address):
                continue
            step = (steps.get(keys.get(address)) or {}).get(prior)
            if step is None or abs(step) <= tol:
                continue
            name, detail = mechanism(facts.get(prior) or {},
                                     metrics["cache"].get(prior),
                                     metrics["computed"].get(prior), tol=tol)
            found.append({"paragraph": prior, "step_hwp": step,
                          "mechanism": name, "detail": detail})
        return found

    def terms_for(address):
        """The four-term split of ONE paragraph's own top, or ``None``."""
        later = computed["origins"].get(address)
        earlier = cache["origins"].get(address)
        if earlier is None or later is None:
            return None
        if later["page"] != earlier["page"]:
            return None
        return {
            "d_container_y_hwp": (later["container_y_hwp"]
                                  - earlier["container_y_hwp"]),
            "d_block_offset_hwp": (later["block_offset_hwp"]
                                   - earlier["block_offset_hwp"]),
            "d_seat_hwp": later["seat_hwp"] - earlier["seat_hwp"],
            "d_first_offset_hwp": (later["first_offset_hwp"]
                                   - earlier["first_offset_hwp"]),
        }

    #: Which page each policy put a TOP-LEVEL paragraph on, and how tall the
    #: flow pass made it.  A paragraph the two policies page differently has
    #: no ``d_seat`` at all — the frames are different — but it is exactly
    #: what pushed the page it landed on, so the pages are kept.
    grouped_flow = layout_divergence._flow_seats_by_address(
        computed["flow_seats"])
    cache_pages = {address: entry.get("page")
                   for address, entry in (cache["cache_seats"] or {}).items()}
    flow_first = {address: entries[0]
                  for address, entries in grouped_flow.items() if entries}

    def page_head(address):
        """The first paragraph seated on ``address``' page, same container."""
        page = page_of.get(address)
        for candidate in by_container.get(keys.get(address), ()):
            if candidate in d_seat and page_of.get(candidate) == page:
                return candidate
        return None

    def carried_over(head):
        """The run of paragraphs the flow pass carried onto ``head``' page.

        Read straight off the two policies' own page assignments: walking up
        from ``head``, a predecessor the CACHE left on the previous page and
        the flow pass put on this one is a paragraph this page is carrying
        that the cache never had, and its computed height is room ``head``
        does not get.  The walk stops at the first predecessor both policies
        agree about, so it is the contiguous run and not a search.
        """
        out = []
        priors = [p for p in by_container.get(keys.get(head), ()) if p < head]
        for prior in reversed(priors):
            earlier_page = cache_pages.get(prior)
            later = flow_first.get(prior)
            if earlier_page is None or later is None:
                break
            if later.get("page") == earlier_page:
                break
            out.append({"paragraph": prior,
                        "height_hwp": later.get("height_hwp") or 0})
        return out

    def seat_root(address, seen=None):
        """The root of a paragraph whose OWN seat carries it.

        A predecessor charged with the step on the SAME page names it.  When
        there is none the drift did not enter on this page: it entered at the
        page top, and the page's own head is where to look.  Two things can
        be measured there, and both are checked rather than assumed:

        * the flow pass CARRIED paragraphs across the break that the cache
          left on the page before, and their computed heights add up to
          exactly the head's ``d_seat`` — then the tallest of them is the
          root, named the ordinary way (nrf's two empty paragraphs);
        * nothing was carried, and the head's cache seat is exactly its
          ``hh:margin/hc:prev`` while the flow pass seats it at zero — the
          cache keeps a paragraph's space-before at the top of a page and the
          flow pass drops it (moel-2025 page 7, kstartup page 9).

        Neither sum matching, the answer is ``page_top_unattributed``: a named
        band, still visible, and not a paragraph three pages back charged with
        a step that was only ever a change of frame.
        """
        largest = _largest(carriers_for(address))
        if largest:
            return largest["mechanism"]
        seen = seen or set()
        head = page_head(address)
        if (head is not None and head != address and head not in seen
                and abs((d_seat.get(head) or 0)
                        - (d_seat.get(address) or 0)) <= tol):
            return seat_root(head, seen | {address})
        delta = d_seat.get(address) or 0
        carried = carried_over(address)
        if carried and abs(sum(entry["height_hwp"] for entry in carried)
                           - delta) <= tol:
            worst = max(carried, key=lambda entry: abs(entry["height_hwp"]))
            name, _detail = mechanism(
                facts.get(worst["paragraph"]) or {},
                metrics["cache"].get(worst["paragraph"]),
                metrics["computed"].get(worst["paragraph"]), tol=tol)
            return name
        earlier = cache["origins"].get(address)
        later = computed["origins"].get(address)
        margin = (facts.get(address) or {}).get("margin_prev_hwp") or 0
        if (earlier is not None and later is not None and margin
                and abs(later["seat_hwp"]) <= tol
                and abs(earlier["seat_hwp"] - margin) <= tol
                and abs(delta + margin) <= tol):
            return "page_top:margin_prev"
        if head is not None:
            return "page_top_unattributed"
        return "seat_unattributed"

    def root_of(address, seen=None):
        """ONE root for a paragraph, following every container it inherits.

        The walk used to stop one level up — at the paragraph holding the
        table whose origin moved — and call it a day if that paragraph had no
        predecessor charged with a step.  A table nested in another table's
        cell breaks that: the holder's own top moved because ITS container
        moved, and the answer is one more table up.  So the same four-term
        question is asked of the holder, and of the holder's holder, until a
        term that is not a container answers it.  ``seen`` makes the walk
        terminate on a cycle it should never see.
        """
        seen = seen or set()
        if address is None or address in seen:
            return "table_origin_unattributed"
        seen = seen | {address}
        terms = terms_for(address)
        if terms is None:
            return "unattributed"
        significant = [name for name, value in terms.items()
                       if abs(value) > tol]
        if not significant:
            return "unattributed"
        term = max(significant, key=lambda name: abs(terms[name]))
        if term == "d_container_y_hwp":
            cell = _cell_terms(address, cache, computed, tol)
            carrier = (cell or {}).get("carrier")
            if carrier == "table_origin":
                holder = (cell or {}).get("holder")
                if holder is None:
                    return "table_origin_unattributed"
                return root_of(holder, seen)
            return ("table_row_heights" if carrier
                    else "cell_unattributed")
        if term == "d_block_offset_hwp":
            return "cell_valign"
        if term == "d_seat_hwp":
            return seat_root(address)
        name, _detail = mechanism(facts.get(address) or {},
                                  metrics["cache"].get(address),
                                  metrics["computed"].get(address), tol=tol)
        return "own:" + name

    records = []
    for address, hit in sorted(targets.items()):
        later = computed["origins"].get(address)
        earlier = cache["origins"].get(address)
        key = keys.get(address)
        fact = facts.get(address) or {}
        record = {
            "paragraph": address,
            "page": hit["page"],
            "dy_px": hit["dy_px"],
            "container": ("top_level" if fact.get("top_level")
                          else "in_cell"),
        }
        if earlier is None or later is None or later["page"] != earlier["page"]:
            record["split"] = "unmeasurable"
            record["note"] = ("the paragraph has no seat under one policy, or "
                              "the two policies drew it on different pages")
            record["carriers"] = []
            records.append(record)
            continue
        terms = {
            "d_container_y_hwp": (later["container_y_hwp"]
                                  - earlier["container_y_hwp"]),
            "d_block_offset_hwp": (later["block_offset_hwp"]
                                   - earlier["block_offset_hwp"]),
            "d_seat_hwp": later["seat_hwp"] - earlier["seat_hwp"],
            "d_first_offset_hwp": (later["first_offset_hwp"]
                                   - earlier["first_offset_hwp"]),
        }
        total = sum(terms.values())
        record["terms_hwp"] = terms
        record["d_top_hwp"] = total
        record["d_own_advance_hwp"] = later["advance_hwp"] - earlier["advance_hwp"]
        record["identity_ok"] = abs(total * px_per_hwp - hit["dy_px"]) <= 0.02

        named = []
        if abs(terms["d_container_y_hwp"]) > tol:
            cell = _cell_terms(address, cache, computed, tol)
            record["cell"] = cell
            carrier = (cell or {}).get("carrier") or "none"
            named.append("cell_top:" + carrier)
            # A table whose ORIGIN moved did not move itself: the paragraph
            # that holds it was seated differently, and the cell inherits the
            # whole of that.  Follow it up one level rather than stopping at
            # "the table moved", which names nothing.
            holder = (cell or {}).get("holder")
            if carrier == "table_origin" and holder is not None:
                via = carriers_for(holder)
                record["holder"] = {
                    "paragraph": holder,
                    "d_seat_hwp": d_seat.get(holder),
                    "carriers": via,
                }
                named.extend("via_holder:" + entry["mechanism"]
                             for entry in via)
                if not via:
                    # The holder's own top moved for a reason of its own —
                    # a table nested in a cell, or a page top.  Name what the
                    # walk finds up there rather than shrugging at it.
                    named.append("via_holder:"
                                 + root_of(holder, {address}))
        if abs(terms["d_block_offset_hwp"]) > tol:
            named.append("cell_valign")
        carriers = []
        if abs(terms["d_seat_hwp"]) > tol:
            carriers = carriers_for(address)
            named.extend(entry["mechanism"] for entry in carriers)
            if not carriers:
                named.append(seat_root(address))
        if abs(terms["d_first_offset_hwp"]) > tol:
            name, detail = mechanism(fact, earlier, later, tol=tol)
            record["own_mechanism"] = name
            record["own_detail"] = detail
            named.append("own:" + name)
        record["carriers"] = carriers
        record["mechanisms"] = sorted(set(named)) or ["unattributed"]
        significant = [name for name, value in terms.items()
                       if abs(value) > tol]
        record["carrier_term"] = (
            max(significant, key=lambda name: abs(terms[name]))
            if significant else "none")
        record["root_mechanism"] = _root(
            record, tol,
            holder_root=lambda holder, here=address: root_of(holder, {here}),
            seat_root=seat_root)
        record["single_term"] = len(significant) == 1
        record["split"] = (
            "inherited" if record["carrier_term"] == "d_seat_hwp"
            else "own" if record["carrier_term"] == "d_first_offset_hwp"
            else "container" if significant else "unattributed")
        records.append(record)
    return records


def paragraph_classes(cache_boxes, computed_boxes, y_tol):
    """``{address: the classes layout_divergence gives its lines}``.

    A paragraph that draws no ink at all — one whose only content is an
    anchored object, say — has no line box under either policy and so appears
    in neither map.  It is reported as ``no_lines`` rather than as class A,
    because "the two policies agree" and "there was nothing to disagree
    about" are different answers to the table-origin question.
    """
    cache_paras = layout_divergence.by_paragraph(cache_boxes)
    computed_paras = layout_divergence.by_paragraph(computed_boxes)
    out = {}
    for address in sorted(set(cache_paras) | set(computed_paras)):
        rows = layout_divergence.classify_paragraph(
            cache_paras.get(address) or [], computed_paras.get(address) or [],
            y_tol=y_tol)
        out[address] = sorted({row["class"] for row in rows}) or ["none"]
    return out


#: The four candidate causes of a moved table origin, in the order the
#: placement path meets them.  ``a`` is a probe bug and ``b`` a renderer one;
#: ``c`` and ``d`` are already named roots and appear here only when the walk
#: reached this bucket by mistake.
TABLE_ORIGIN_CAUSES = {
    "a": "holder_upstream — the holder paragraph's own block top moved",
    "b": "table_seat — the table sits at a different offset inside its "
         "holder under the two policies",
    "c": "table_height — a table above it came out a different height",
    "d": "columns — the table's own column solve moved its content",
    "other": "no term above tolerance carries the origin delta",
}


def _table_origin_terms(seat_a, seat_b, holder_a, holder_b, tol):
    """Split a table's origin delta into holder, in-holder and box terms."""
    d_slot = seat_b["slot_y_hwp"] - seat_a["slot_y_hwp"]
    d_box = seat_b["box_y_hwp"] - seat_a["box_y_hwp"]
    d_margin = (seat_b["out_margin_hwp"]["top"]
                - seat_a["out_margin_hwp"]["top"])
    d_offset = ((seat_b["pos"] or {}).get("vertOffset", 0)
                - (seat_a["pos"] or {}).get("vertOffset", 0))

    def block_top(record):
        if record is None:
            return None
        return (record["container_y_hwp"] + record["block_offset_hwp"]
                + record["seat_hwp"])

    top_a, top_b = block_top(holder_a), block_top(holder_b)
    d_holder = None if top_a is None or top_b is None else top_b - top_a
    terms = {
        "d_box_y_hwp": d_box,
        "d_slot_y_hwp": d_slot,
        "d_out_margin_top_hwp": d_margin,
        "d_vert_offset_hwp": d_offset,
        "d_holder_block_top_hwp": d_holder,
        "d_within_holder_hwp": (None if d_holder is None
                                else d_slot - d_holder),
        "d_height_hwp": ((seat_b.get("height_hwp") or 0)
                         - (seat_a.get("height_hwp") or 0)),
        "d_cols": (seat_b.get("cols") or 0) - (seat_a.get("cols") or 0),
        "d_col_edges_hwp": (
            [b - a for a, b in zip(seat_a.get("col_edges_hwp") or (),
                                   seat_b.get("col_edges_hwp") or ())]),
    }
    if abs(d_margin) > tol or abs(d_offset) > tol:
        cause = "b"
    elif d_holder is not None and abs(d_holder) > tol:
        cause = ("a" if abs(terms["d_within_holder_hwp"] or 0) <= abs(d_holder)
                 else "b")
    elif d_holder is not None and abs(terms["d_within_holder_hwp"]) > tol:
        cause = "b"
    elif any(abs(value) > tol for value in terms["d_col_edges_hwp"]):
        cause = "d"
    elif abs(terms["d_height_hwp"]) > tol:
        cause = "c"
    else:
        cause = "other"
    terms["cause"] = cause
    return terms


def table_origin_report(cache, computed, records, y_tol, tol=DEFAULT_TOL_HWP):
    """One row per class-B paragraph whose cell rode a MOVED table origin.

    The row carries what the four candidate causes need to be told apart: the
    holder paragraph and its own class and seat, the table's positioning
    attributes, its seat and height under both policies, and the paragraph
    before the holder.  Nothing here is inferred from a name — every term is a
    subtraction of two measured numbers, and ``d_slot_y`` is checked against
    the sum of the terms it was split into.
    """
    classes = paragraph_classes(cache["line_boxes"], computed["line_boxes"],
                                y_tol)
    order = sorted(computed["containers"])
    prev_of = {address: (order[i - 1] if i else None)
               for i, address in enumerate(order)}
    rows = []
    for record in records:
        cell = record.get("cell") or {}
        if cell.get("carrier") != "table_origin":
            continue
        address = record["paragraph"]
        cell_id_a = cache["cell_of"].get(address)
        cell_id_b = computed["cell_of"].get(address)
        table = (computed["table_of_cell"].get(cell_id_b)
                 if cell_id_b is not None else None)
        table_a = (cache["table_of_cell"].get(cell_id_a)
                   if cell_id_a is not None else None)
        seat_a = cache["table_seats"].get(table_a)
        seat_b = computed["table_seats"].get(table)
        row = {
            "paragraph": address,
            "root_mechanism": record.get("root_mechanism"),
            "page": record.get("page"),
            "dy_px": record.get("dy_px"),
            "cell": {"row": cell.get("row"), "col": cell.get("col")},
            "table": table,
            "d_table_y_hwp": cell.get("d_table_y_hwp"),
            "d_row_top_hwp": cell.get("d_row_top_hwp"),
        }
        holder = cell.get("holder")
        row["holder"] = {
            "paragraph": holder,
            "classes": classes.get(holder),
            "d_seat_hwp": (record.get("holder") or {}).get("d_seat_hwp"),
            "carriers": [entry["mechanism"]
                         for entry in (record.get("holder") or {}).get(
                             "carriers") or ()],
        }
        prior = prev_of.get(holder) if holder is not None else None
        prior_a = cache["origins"].get(prior)
        prior_b = computed["origins"].get(prior)
        row["preceding"] = {
            "paragraph": prior,
            "classes": classes.get(prior),
            "d_top_hwp": (None if prior_a is None or prior_b is None
                          else prior_b["abs_top_hwp"] - prior_a["abs_top_hwp"]),
        }
        if seat_a is None or seat_b is None:
            row["cause"] = "other"
            row["note"] = "the table was not drawn under one of the policies"
            rows.append(row)
            continue
        row["placement"] = {
            "inline": seat_b["inline"],
            "anchored": seat_b["anchored"],
            "pos": seat_b["pos"],
            "out_margin_hwp": seat_b["out_margin_hwp"],
            "text_wrap": seat_b["text_wrap"],
            "page_break": seat_b["page_break"],
            "declared_height_hwp": seat_b["declared_height_hwp"],
        }
        row["seat"] = {
            "cache": {"slot_y_hwp": seat_a["slot_y_hwp"],
                      "box_y_hwp": seat_a["box_y_hwp"],
                      "height_hwp": seat_a.get("height_hwp"),
                      "page": seat_a["page"]},
            "computed": {"slot_y_hwp": seat_b["slot_y_hwp"],
                         "box_y_hwp": seat_b["box_y_hwp"],
                         "height_hwp": seat_b.get("height_hwp"),
                         "page": seat_b["page"]},
        }
        holder_a = cache["origins"].get(holder)
        holder_b = computed["origins"].get(holder)
        row["holder"]["lines"] = {
            "cache": (holder_a or {}).get("line_count"),
            "computed": (holder_b or {}).get("line_count"),
        }
        terms = _table_origin_terms(seat_a, seat_b, holder_a, holder_b, tol)
        row["cause"] = terms.pop("cause")
        row["terms_hwp"] = terms
        rows.append(row)
    return rows


def table_origin_summary(rows):
    """Cause histogram, and the table each cause was measured on."""
    causes = Counter(row["cause"] for row in rows)
    per_table = {}
    for row in rows:
        key = row["cause"]
        per_table.setdefault(key, Counter())[row.get("table")] += 1
    return {
        "paragraphs": len(rows),
        "causes": dict(causes),
        "tables_per_cause": {name: dict(counter)
                             for name, counter in per_table.items()},
        "roots": dict(Counter(row.get("root_mechanism") for row in rows)),
    }


#: What each candidate predicts a page head's cached ``vertpos`` to be.  The
#: names are the ones the research question posed them under; ``b`` is what
#: the flow pass does today and the rest are ways of keeping the space-before.
PAGE_TOP_CANDIDATES = {
    "a_margin_prev": "vertpos = margin_prev — the space-before is kept whole",
    "b_dropped": "vertpos = 0 — the space-before is dropped (the flow pass)",
    "c_collapsed": "vertpos = max(margin_prev, previous margin_next)",
    "d_pages_2plus": "vertpos = margin_prev, but 0 on the first page",
    "e_pushed_whole": "vertpos = margin_prev, but 0 when the page was "
                      "started by an overflow rather than by a whole block",
    "f_uncollapsed": "vertpos = previous margin_next + margin_prev — the "
                     "mid-page gap, applied unchanged at a page top",
}


def _page_top_candidates(margin_prev, prev_margin_next, page, pushed_whole):
    """Each candidate's predicted ``vertpos`` for one page head."""
    return {
        "a_margin_prev": margin_prev,
        "b_dropped": 0,
        "c_collapsed": max(margin_prev, prev_margin_next),
        "d_pages_2plus": margin_prev if page > 1 else 0,
        "e_pushed_whole": margin_prev if pushed_whole else 0,
        "f_uncollapsed": prev_margin_next + margin_prev,
    }


def _holds(fact):
    """What a paragraph carries, for the page-top row."""
    kinds = [obj["kind"] for obj in (fact.get("objects") or ())]
    return {
        "object_kinds": kinds,
        "table": "tbl" in kinds,
        "picture": bool({"pic", "picture"} & set(kinds)),
        "empty": bool(fact.get("empty_text")),
    }


def page_top_report(cache, computed, tol=DEFAULT_TOL_HWP):
    """Every CACHE page head, and what each candidate rule predicts for it.

    The population is the first TOP-LEVEL paragraph the cache seats on each
    page — the frame ``hp:lineseg@vertpos`` is measured in, so its seat is
    directly a number of HWPUNIT below the body top — plus, as the container
    mirror, the first paragraph of every table cell, whose ``vertpos`` is
    measured from its own cell in exactly the same way.  A cell top is not a
    page top, but it IS a container top, and it is the only place on this
    corpus where the "does a fresh container keep ``hh:margin/hc:prev``"
    question has more than two instances to answer it.

    Nothing here is inferred from a name: the predicted seat of every
    candidate is put beside the measured one and the mismatches are listed.
    """
    facts = cache["facts"]
    cache_seats = cache["cache_seats"] or {}
    grouped_flow = layout_divergence._flow_seats_by_address(
        computed["flow_seats"])
    flow_first = {address: entries[0]
                  for address, entries in grouped_flow.items() if entries}
    top_level = sorted(address for address, fact in facts.items()
                       if fact.get("top_level"))
    seats = {}
    for address in top_level:
        seat = layout_divergence._cache_seat(facts.get(address), cache_seats,
                                             address)
        if seat is not None:
            seats[address] = seat
    ordered = [address for address in top_level if address in seats]
    #: The table each paragraph holds, so a head that is an object paragraph
    #: can be shown with the seat its table actually got.
    table_of_holder = {}
    for index, record in (cache["table_seats"] or {}).items():
        table_of_holder.setdefault(record.get("holder"), (index, record))

    by_page = {}
    for address in ordered:
        by_page.setdefault(seats[address]["page"], []).append(address)

    rows = []
    for page in sorted(by_page):
        address = by_page[page][0]
        fact = facts.get(address) or {}
        seat = seats[address]
        position = ordered.index(address)
        prior = ordered[position - 1] if position else None
        prior_fact = facts.get(prior) or {}
        prior_seat = seats.get(prior)
        # The cache draws a straddling paragraph once per page it spans, and
        # ``drawn_pages`` counts those, so the last page it occupies is its
        # seat page plus the rest of its runs.
        prior_last_page = (None if prior_seat is None else
                           prior_seat["page"] + prior_seat["records"] - 1)
        straddled_in = prior_last_page == page
        margin_prev = fact.get("margin_prev_hwp") or 0
        prev_margin_next = prior_fact.get("margin_next_hwp") or 0
        candidates = _page_top_candidates(margin_prev, prev_margin_next, page,
                                          not straddled_in)
        table = table_of_holder.get(address)
        rows.append({
            "page": page,
            "paragraph": address,
            "cache_vertpos_hwp": seat["top_hwp"],
            "computed_top_hwp": (flow_first.get(address) or {}).get("top_hwp"),
            "computed_page": (flow_first.get(address) or {}).get("page"),
            "margin_prev_hwp": margin_prev,
            "line_spacing": {
                "type": fact.get("line_spacing_type"),
                "value": fact.get("line_spacing_value"),
            },
            "holds": _holds(fact),
            "page_break_before": bool(fact.get("page_break_before")),
            "keep_with_next": bool(fact.get("keep_with_next")),
            "column": page % max(1, cache["col_count"]),
            "col_count": cache["col_count"],
            "prev": {
                "paragraph": prior,
                "margin_next_hwp": prev_margin_next,
                "last_page": prior_last_page,
                "ended_previous_page": (prior_last_page is not None
                                        and prior_last_page == page - 1),
                "straddled_into_this_page": bool(straddled_in),
            },
            "started_by_overflow": bool(straddled_in),
            "table_seat": (None if table is None else {
                "table": table[0],
                "slot_y_hwp": table[1]["slot_y_hwp"],
                "box_y_hwp": table[1]["box_y_hwp"],
                "page": table[1]["page"],
            }),
            "candidates_hwp": candidates,
            "matches": {name: abs(value - seat["top_hwp"]) <= tol
                        for name, value in candidates.items()},
        })

    #: The container mirror: every table cell's FIRST paragraph.  Its
    #: ``vertpos`` is measured from the cell's own content top, so "does the
    #: cache keep the space-before at the top of a fresh container" is the
    #: same equality asked of a much larger population.
    cell_first = {}
    for address, cell in sorted((cache["cell_of"] or {}).items()):
        cell_first.setdefault(cell, address)
    cell_rows = []
    for cell, address in sorted(cell_first.items(), key=lambda kv: kv[1]):
        fact = facts.get(address) or {}
        linesegs = fact.get("linesegs") or []
        if not linesegs:
            continue
        margin_prev = fact.get("margin_prev_hwp") or 0
        cell_rows.append({
            "paragraph": address,
            "cache_vertpos_hwp": linesegs[0]["vertpos"],
            "margin_prev_hwp": margin_prev,
            "keeps_margin_prev": abs(linesegs[0]["vertpos"] - margin_prev)
            <= tol,
            "dropped": abs(linesegs[0]["vertpos"]) <= tol,
        })
    return {"page_tops": rows, "cell_tops": cell_rows}


def page_top_summary(block):
    """Exact matches per candidate, and every row that refutes one."""
    rows = block["page_tops"]
    counts = {name: sum(1 for row in rows if row["matches"][name])
              for name in PAGE_TOP_CANDIDATES}
    #: Only a head with a nonzero space-before can tell the candidates apart;
    #: everywhere else every candidate predicts the same zero.
    discriminating = [row for row in rows
                      if row["margin_prev_hwp"] or row["prev"]["margin_next_hwp"]]
    misses = {
        name: [{"page": row["page"], "paragraph": row["paragraph"],
                "cache_vertpos_hwp": row["cache_vertpos_hwp"],
                "predicted_hwp": row["candidates_hwp"][name]}
               for row in rows if not row["matches"][name]]
        for name in PAGE_TOP_CANDIDATES
    }
    cells = block["cell_tops"]
    with_margin = [row for row in cells if row["margin_prev_hwp"]]
    return {
        "page_tops": len(rows),
        "discriminating_page_tops": len(discriminating),
        "exact": counts,
        "counter_examples": misses,
        "cell_tops": len(cells),
        "cell_tops_with_margin_prev": len(with_margin),
        "cell_tops_keeping_margin_prev": sum(1 for row in with_margin
                                             if row["keeps_margin_prev"]),
        "cell_tops_dropping_margin_prev": sum(1 for row in with_margin
                                              if row["dropped"]),
    }


def page_bottom_report(cache, tol=DEFAULT_TOL_HWP):
    """The mirror: was ``hh:margin/hc:prev``'s partner reserved at a page foot?

    For the LAST top-level paragraph the cache seats on each page, the row
    states its bottom (``vertpos + vertsize + spacing`` of its last lineseg —
    #256's fit bracket, which does NOT add ``margin_next``), its
    ``hh:margin/hc:next``, the usable height, and whether the next page's head
    would have fitted below it with and without that space-after reserved.

    A page only DISCRIMINATES when the last paragraph declares a nonzero
    space-after and the head that follows would have fitted without it: then
    reserving the space-after is the only thing that explains the break.  A
    page whose head does not fit either way, or that is opened by an explicit
    ``hp:p@pageBreak``, says nothing about the reserve and is counted apart
    rather than folded in.
    """
    facts = cache["facts"]
    cache_seats = cache["cache_seats"] or {}
    usable = cache["usable_height_hwp"]
    top_level = sorted(address for address, fact in facts.items()
                       if fact.get("top_level"))
    seats = {}
    for address in top_level:
        seat = layout_divergence._cache_seat(facts.get(address), cache_seats,
                                             address)
        if seat is not None:
            seats[address] = seat
    ordered = [address for address in top_level if address in seats]
    by_page = {}
    for address in ordered:
        by_page.setdefault(seats[address]["page"], []).append(address)

    rows = []
    for page in sorted(by_page):
        address = by_page[page][-1]
        fact = facts.get(address) or {}
        linesegs = fact.get("linesegs") or []
        if not linesegs:
            continue
        last = linesegs[-1]
        bottom = last["vertpos"] + last["vertsize"] + last["spacing"]
        margin_next = fact.get("margin_next_hwp") or 0
        head = by_page.get(page + 1, [None])[0]
        head_fact = facts.get(head) or {}
        head_segs = head_fact.get("linesegs") or []
        head_advance = ((head_segs[0]["vertsize"] + head_segs[0]["spacing"])
                        if head_segs else None)
        head_margin = head_fact.get("margin_prev_hwp") or 0
        need = (None if head_advance is None
                else head_margin + head_advance)
        rows.append({
            "page": page,
            "paragraph": address,
            "bottom_hwp": bottom,
            "margin_next_hwp": margin_next,
            "usable_hwp": usable,
            "next_head": head,
            "next_head_needs_hwp": need,
            "next_head_page_break_before": bool(
                head_fact.get("page_break_before")),
            "fits_without_margin_next": (None if need is None
                                         else bottom + need <= usable + tol),
            "fits_with_margin_next": (
                None if need is None
                else bottom + margin_next + need <= usable + tol),
        })
    return rows


def page_bottom_bracket(rows):
    """The bracket: how many page feet can tell the reserve apart, and which.

    ``reserve_required`` — the next head would have fitted but for the
    space-after, so the cache must have reserved it.  ``reserve_refuted`` —
    the space-after was NOT reserved, because the head sits where it could
    only sit if it were not.  ``silent`` — everything else.
    """
    required = refuted = silent = 0
    detail = []
    for row in rows:
        if not row["margin_next_hwp"] or row["fits_without_margin_next"] is None:
            silent += 1
            continue
        if row["next_head_page_break_before"]:
            silent += 1
            continue
        if row["fits_without_margin_next"] and not row["fits_with_margin_next"]:
            required += 1
            detail.append(row)
        elif row["fits_with_margin_next"]:
            refuted += 1
            detail.append(row)
        else:
            silent += 1
    return {
        "page_feet": len(rows),
        "with_margin_next": sum(1 for row in rows if row["margin_next_hwp"]),
        "reserve_required": required,
        "reserve_refuted": refuted,
        "silent": silent,
        "detail": detail,
    }


#: What each candidate says the CACHE does at a page foot when the next block
#: does not fit.  ``a`` is the flow pass as it ships; the rest keep an inkless
#: paragraph — no characters at all, so no object either — on the page.
EMPTY_FOOT_CANDIDATES = {
    "a_break_always": "any block that does not fit opens a new page (the flow "
                      "pass as it ships)",
    "b_inkless_never_breaks": "an inkless paragraph never opens a new page",
    "c_inkless_past_bottom_stays": "an inkless paragraph does not open a new "
                                   "page when the cursor has ALREADY reached "
                                   "the page bottom; anywhere else it breaks "
                                   "like any other block",
    "d_any_block_past_bottom_stays": "any block, inkless or not, stays on the "
                                     "page once the cursor is past the bottom",
}

#: Why a cached step says nothing about the candidates.
EMPTY_FOOT_SILENT = {
    "hard_break": "the head declares hp:p@pageBreak or @columnBreak",
    "object": "the head or its predecessor holds an object, whose placement "
              "the anchored/inline seam decides and this rule does not",
    "no_cursor": "the step starts at the top of a page, where every block is "
                 "placed whatever its height",
}


def _empty_step_kind(fact):
    """``bare_inkless`` / ``object`` / ``ink`` for one paragraph."""
    if fact.get("objects"):
        return "object"
    return "bare_inkless" if not fact.get("characters") else "ink"


def _empty_foot_predictions(kind, need, room):
    """Each candidate's answer to "does the cache break the page here?"."""
    short = need > room
    return {
        "a_break_always": short,
        "b_inkless_never_breaks": short and kind != "bare_inkless",
        "c_inkless_past_bottom_stays": short and not (
            kind == "bare_inkless" and room <= 0),
        "d_any_block_past_bottom_stays": short and room > 0,
    }


def empty_report(cache, computed, records, tol=DEFAULT_TOL_HWP):
    """Every INKLESS paragraph, path A beside path B, and the page-foot rule.

    Two separate questions, kept apart because they have different answers.

    **The height.**  For every paragraph that puts no character on its line,
    the row states what the cache gives (``hp:lineseg@vertpos``, ``vertsize``,
    ``spacing``), what the paragraph DECLARES (``hh:lineSpacing`` type and
    value, the ``hh:charPr@height`` of each empty run, whether there is an
    ``hp:linesegarray`` at all) and what our own rule makes of it
    (``own_inkless_metrics``, i.e. ``_line_metrics(para, 0, 0)``).  The last
    one is the load-bearing column: ``_flow_lines`` reads the cached lineseg
    whenever there is one, so on a Hancom-saved document the two POLICIES
    agree on an inkless paragraph's height by construction, and the only way
    to find out whether the RULE is right is to ask it separately.

    **The page foot.**  The height being right does not make the pagination
    right.  Every step from one top-level paragraph to the next is scored
    against ``EMPTY_FOOT_CANDIDATES``: the cursor the previous paragraph left,
    the room to the page bottom, what the head needs, and whether the cache
    actually broke the page there.  Steps the object seam or an explicit break
    decides are counted as silent (``EMPTY_FOOT_SILENT``) rather than folded
    in, and a candidate is only tested where the four disagree.
    """
    facts = cache["facts"]
    own = cache.get("own_inkless_metrics") or {}
    usable = cache["usable_height_hwp"]
    seats = cache["cache_seats"] or {}
    grouped = layout_divergence._flow_seats_by_address(computed["flow_seats"])
    roots = {record["paragraph"]: record.get("root_mechanism")
             for record in records}
    class_b = {record["paragraph"]: record for record in records}

    rows = []
    for address, fact in sorted(facts.items()):
        if not fact.get("empty_text"):
            continue
        segs = fact.get("linesegs") or []
        first = segs[0] if segs else {}
        mine = own.get(address)
        flow = grouped.get(address) or []
        cached_advance = fact.get("cache_advance_hwp")
        rows.append({
            "paragraph": address,
            "place": ("body" if fact.get("top_level")
                      else ("cell" if address in (cache["cell_of"] or {})
                            else "other")),
            "characters": fact.get("characters"),
            "objects": [obj["kind"] for obj in (fact.get("objects") or ())],
            "linesegarray": bool(segs),
            "line_spacing": {"type": fact.get("line_spacing_type"),
                             "value": fact.get("line_spacing_value")},
            "empty_runs": fact.get("empty_runs") or [],
            "margin_prev_hwp": fact.get("margin_prev_hwp"),
            "margin_next_hwp": fact.get("margin_next_hwp"),
            "cache": {"vertpos_hwp": first.get("vertpos"),
                      "vertsize_hwp": first.get("vertsize"),
                      "spacing_hwp": first.get("spacing"),
                      "advance_hwp": cached_advance,
                      "page": (seats.get(address) or {}).get("page")},
            "own_rule": mine,
            "flow": ({"top_hwp": flow[0]["top_hwp"], "page": flow[0]["page"],
                      "height_hwp": sum(seat.get("height_hwp") or 0
                                        for seat in flow)} if flow else None),
            # Our RULE against the cache, where both exist and the paragraph
            # has exactly one cached line to compare against.
            "height_exact": (None if mine is None or len(segs) != 1 else
                             (abs(mine["vertsize_hwp"] - first["vertsize"])
                              <= tol
                              and abs(mine["spacing_hwp"] - first["spacing"])
                              <= tol)),
            "class_b": address in class_b,
            "root_mechanism": roots.get(address),
        })

    scored = [row for row in rows if row["height_exact"] is not None]
    heights = {
        "inkless_paragraphs": len(rows),
        "comparable": len(scored),
        "vertsize_exact": sum(
            1 for row in scored
            if row["own_rule"]["vertsize_hwp"] == row["cache"]["vertsize_hwp"]),
        "spacing_exact": sum(
            1 for row in scored
            if row["own_rule"]["spacing_hwp"] == row["cache"]["spacing_hwp"]),
        "advance_exact": sum(1 for row in scored if row["height_exact"]),
        "by_place": dict(Counter(row["place"] for row in rows)),
        "misses": [{"paragraph": row["paragraph"], "place": row["place"],
                    "cache": row["cache"], "own_rule": row["own_rule"]}
                   for row in scored if not row["height_exact"]],
    }

    steps = []
    ordered = [address for address in sorted(facts)
               if facts[address].get("top_level")
               and (facts[address].get("linesegs") or [])]
    for position in range(1, len(ordered)):
        prior, address = ordered[position - 1], ordered[position]
        fact, prior_fact = facts[address], facts[prior]
        page = (seats.get(address) or {}).get("page")
        prior_page = (seats.get(prior) or {}).get("page")
        if page is None or prior_page is None:
            continue
        last = prior_fact["linesegs"][-1]
        head = fact["linesegs"][0]
        cursor = (last["vertpos"] + last["vertsize"] + last["spacing"]
                  + (prior_fact.get("margin_next_hwp") or 0))
        room = usable - cursor
        # ``_place_block``'s own fit test is against the row EXTENT, which is
        # the baseline and not the vertsize (docs/research/line-fit-rule.md).
        need = head.get("baseline") or int(round(
            own_render.BASELINE_RATIO * head["vertsize"]))
        kind = _empty_step_kind(fact)
        broke = page != prior_page
        silent = None
        if fact.get("page_break_before") or fact.get("column_break"):
            silent = "hard_break"
        elif fact.get("objects") or prior_fact.get("objects"):
            silent = "object"
        elif cursor <= 0:
            silent = "no_cursor"
        predictions = _empty_foot_predictions(kind, need, room)
        steps.append({
            "paragraph": address,
            "prev": prior,
            "page": page,
            "prev_page": prior_page,
            "kind": kind,
            "cursor_hwp": cursor,
            "room_hwp": room,
            "need_hwp": need,
            "usable_hwp": usable,
            "broke": broke,
            "silent": silent,
            "discriminating": (silent is None
                               and len(set(predictions.values())) > 1),
            "predictions": predictions,
            "matches": {name: value == broke
                        for name, value in predictions.items()},
        })

    # An inkless paragraph draws no line box, so it is never itself class B:
    # what it does is move the paragraphs BELOW it, and those are the class-B
    # population ``decompose`` roots at ``empty_paragraph``.  The carriers are
    # the inkless paragraphs the two policies actually seat differently.
    carriers = [
        {"paragraph": row["paragraph"],
         "cache": row["cache"], "flow": row["flow"],
         "line_spacing": row["line_spacing"],
         "empty_runs": row["empty_runs"],
         "d_page": (None if not row["flow"] or row["cache"]["page"] is None
                    else row["flow"]["page"] - row["cache"]["page"]),
         "d_top_hwp": (None if not row["flow"]
                       or row["cache"]["vertpos_hwp"] is None
                       else row["flow"]["top_hwp"]
                       - row["cache"]["vertpos_hwp"])}
        for row in rows
        if row["place"] == "body" and row["flow"] and not row["objects"]
        and (row["flow"]["page"] != row["cache"]["page"]
             or row["flow"]["top_hwp"] != row["cache"]["vertpos_hwp"])]
    rooted = [{"paragraph": record["paragraph"], "dy_px": record.get("dy_px"),
               "container": record.get("container"),
               "split": record.get("split")}
              for record in records
              if record.get("root_mechanism") == "empty_paragraph"]

    live = [step for step in steps if step["silent"] is None]
    discriminating = [step for step in live if step["discriminating"]]
    candidates = {
        name: {
            "exact": sum(1 for step in live if step["matches"][name]),
            "exact_discriminating": sum(1 for step in discriminating
                                        if step["matches"][name]),
            "counter_examples": [
                {"paragraph": step["paragraph"], "prev": step["prev"],
                 "kind": step["kind"], "cursor_hwp": step["cursor_hwp"],
                 "room_hwp": step["room_hwp"], "need_hwp": step["need_hwp"],
                 "cache_broke": step["broke"],
                 "predicted_break": step["predictions"][name]}
                for step in live if not step["matches"][name]],
        }
        for name in EMPTY_FOOT_CANDIDATES
    }
    return {
        "heights": heights,
        "paragraphs": rows,
        "carriers": carriers,
        "class_b_rooted_here": rooted,
        "page_feet": {
            "steps": len(steps),
            "live": len(live),
            "discriminating": len(discriminating),
            "silent": dict(Counter(step["silent"] for step in steps
                                   if step["silent"])),
            "candidates": candidates,
            "rows": [step for step in steps
                     if step["discriminating"] or not all(
                         step["matches"].values())],
        },
    }


def empty_table(rows):
    """The inkless population, the height check, and the page-foot bracket."""
    blocks = [(stem, report["empty"]) for stem, report in rows
              if report.get("empty")]
    if not blocks:
        return "empty: nothing measured"
    out = []
    total = sum(block["heights"]["inkless_paragraphs"] for _s, block in blocks)
    comparable = sum(block["heights"]["comparable"] for _s, block in blocks)
    exact = sum(block["heights"]["advance_exact"] for _s, block in blocks)
    vs_exact = sum(block["heights"]["vertsize_exact"] for _s, block in blocks)
    sp_exact = sum(block["heights"]["spacing_exact"] for _s, block in blocks)
    places = Counter()
    for _stem, block in blocks:
        places.update(block["heights"]["by_place"])
    out.append("inkless paragraphs (hp:p that puts no character on its line)")
    out.append(f"  population {total} — " + ", ".join(
        f"{place} {count}" for place, count in sorted(places.items())))
    out.append(f"  our own rule vs the cache, over the {comparable} with "
               f"exactly one cached line:")
    out.append(f"    vertsize exact {vs_exact}/{comparable}, spacing exact "
               f"{sp_exact}/{comparable}, advance exact {exact}/{comparable}")
    for stem, block in blocks:
        for miss in block["heights"]["misses"]:
            out.append(f"    MISS {stem} p{miss['paragraph']} "
                       f"({miss['place']}): cache {miss['cache']} vs own "
                       f"{miss['own_rule']}")
    out.append("")
    rooted = sum(len(block["class_b_rooted_here"]) for _s, block in blocks)
    out.append(f"an inkless paragraph draws no line box, so it is never itself "
               f"class B: it MOVES the paragraphs below it. {rooted} class-B "
               f"paragraphs are rooted at empty_paragraph, and these are the "
               f"inkless paragraphs the two policies seat differently:")
    header = (f"  {'form':<12} {'para':>5} {'A page':>6} {'A vertpos':>10} "
              f"{'A adv':>7} {'B page':>6} {'B top':>10} {'B height':>9} "
              f"{'lineSpacing':>13}  runs (charPr@height pt)")
    out.append(header)
    out.append("  " + "-" * (len(header) - 2))
    carriers = 0
    for stem, block in blocks:
        for row in block["carriers"]:
            carriers += 1
            runs = ",".join(f"{run['charpr']}@{run['height_pt']}"
                            for run in row["empty_runs"]) or "-"
            spacing = (f"{row['line_spacing']['type']}"
                       f"/{row['line_spacing']['value']}")
            out.append(
                f"  {stem:<12} {row['paragraph']:>5} "
                f"{str(row['cache']['page']):>6} "
                f"{str(row['cache']['vertpos_hwp']):>10} "
                f"{str(row['cache']['advance_hwp']):>7} "
                f"{str(row['flow']['page']):>6} "
                f"{str(row['flow']['top_hwp']):>10} "
                f"{str(row['flow']['height_hwp']):>9} "
                f"{spacing:>13}  {runs}")
    if not carriers:
        out.append("  (none — every top-level inkless paragraph is seated "
                   "identically under both policies)")
    for stem, block in blocks:
        rows_here = block["class_b_rooted_here"]
        if rows_here:
            out.append(f"  {stem}: class B rooted at empty_paragraph "
                       f"{len(rows_here)} — " + ", ".join(
                           f"p{row['paragraph']}({row['split']},"
                           f"{row['dy_px']:+g}px)" for row in rows_here[:6])
                       + (f", +{len(rows_here) - 6} more"
                          if len(rows_here) > 6 else ""))
    out.append("")
    out.append("page foot: does a block that does not fit open a new page?")
    steps = sum(block["page_feet"]["steps"] for _s, block in blocks)
    live = sum(block["page_feet"]["live"] for _s, block in blocks)
    disc = sum(block["page_feet"]["discriminating"] for _s, block in blocks)
    silent = Counter()
    for _stem, block in blocks:
        silent.update(block["page_feet"]["silent"])
    out.append(f"  {steps} cached steps, {live} live, {disc} tell the "
               f"candidates apart; silent " + (", ".join(
                   f"{name} {count}" for name, count in sorted(silent.items()))
                   or "none"))
    width = max(len(name) for name in EMPTY_FOOT_CANDIDATES)
    out.append(f"  {'candidate':<{width}} {'exact/live':>12} "
               f"{'exact/discriminating':>21}  counter-examples")
    out.append("  " + "-" * (width + 60))
    for name in EMPTY_FOOT_CANDIDATES:
        hits = sum(block["page_feet"]["candidates"][name]["exact"]
                   for _s, block in blocks)
        dhits = sum(
            block["page_feet"]["candidates"][name]["exact_discriminating"]
            for _s, block in blocks)
        misses = [(stem, entry)
                  for stem, block in blocks
                  for entry in
                  block["page_feet"]["candidates"][name]["counter_examples"]]
        shown = ", ".join(f"{stem} p{entry['paragraph']}"
                          for stem, entry in misses[:4])
        if len(misses) > 4:
            shown += f", +{len(misses) - 4} more"
        out.append(f"  {name:<{width}} {hits:>6}/{live:<5} {dhits:>10}/{disc:<10}"
                   f"  {shown or '-'}")
    out.append("")
    for name, text in EMPTY_FOOT_CANDIDATES.items():
        out.append(f"  {name}: {text}")
    out.append("")
    for name, text in EMPTY_FOOT_SILENT.items():
        out.append(f"  silent/{name}: {text}")
    out.append("")
    out.append("the steps that tell them apart, and the silent ones no "
               "candidate reproduces")
    for stem, block in blocks:
        for step in block["page_feet"]["rows"]:
            failed = sorted(name for name, ok in step["matches"].items()
                            if not ok)
            verdict = (f"SILENT/{step['silent']}, not scored"
                       if step["silent"] else f"refutes {failed or '-'}")
            out.append(
                f"  {stem} p{step['prev']} -> p{step['paragraph']} "
                f"({step['kind']}) cursor={step['cursor_hwp']} "
                f"room={step['room_hwp']} need={step['need_hwp']} "
                f"usable={step['usable_hwp']} cache "
                f"{'BROKE' if step['broke'] else 'stayed'} -> {verdict}")
    return "\n".join(out)


#: The mechanisms a ``text_line_height`` paragraph can be charged to, in the
#: order the question is asked.  Only the first is a LINE-HEIGHT mechanism;
#: the other two are break-position faults that the root label
#: ``text_line_height`` cannot tell apart from one, because ``mechanism()``
#: sees an equal line COUNT and an unequal ADVANCE and has nothing else to go
#: on.  Separating them is the whole job of this view.
LINE_HEIGHT_MECHANISMS = {
    "height_rule": (
        "our _line_metrics disagrees with the cached hp:lineseg ON THE "
        "CACHE'S OWN SPANS — a height rule fault, and the only one of these "
        "that the line-height seam can fix"),
    "span:control_break": (
        "path A is exact, but our line SPANS differ from the cache's and a "
        "cached boundary the flow pass does not share has a control cell on "
        "it (hp:lineBreak and its kind take a textpos cell and put nothing "
        "in the character stream, so the cache breaks there and we cannot). "
        "The line is a different height because it holds different "
        "CHARACTERS, not because the height rule read them differently"),
    "span:width": (
        "path A is exact and the spans differ with no control on the "
        "boundary — the break moved on glyph advances alone"),
    "advance_unattributed": (
        "path A is exact and the spans agree, and the advance still differs"),
}


def _carrier_of(record):
    """The paragraph whose own height a class-B record is charged to."""
    if record.get("carrier_term") == "d_seat_hwp":
        largest = _largest(record.get("carriers"))
        if largest:
            return largest["paragraph"]
    return record.get("paragraph")


def _spans_of(entry):
    return [[line["start"], line["end"]] for line in (entry or {}).get("lines")
            or ()]


def _line_height_mechanism(path_a, cached_spans, our_spans, line_breaks):
    if path_a and path_a["exact"] < path_a["total"]:
        return "height_rule"
    if cached_spans and our_spans and cached_spans != our_spans:
        ours = {tuple(span) for span in our_spans}
        controls = any(
            line.get("control_cells_before_start")
            for line, span in zip((path_a or {}).get("lines") or (),
                                  cached_spans)
            if tuple(span) not in ours)
        if controls and line_breaks:
            return "span:control_break"
        return "span:width"
    return "advance_unattributed"


def line_height_report(cache, computed, records, tol=DEFAULT_TOL_HWP):
    """Every ``text_line_height`` paragraph, and WHICH of two faults it is.

    ``mechanism()`` reaches ``text_line_height`` by elimination: the two
    policies drew the same NUMBER of lines and the lines add up to a different
    total.  That is true of a paragraph whose height rule misread its runs and
    equally true of one whose lines hold different CHARACTERS because the
    break moved without changing the count, and the two want opposite fixes.

    So the view scores the height rule on its own, against the authoring
    engine's cache, on the cache's own spans (``_cached_span_metrics``): PATH
    A, in which no break difference can participate.  What is left over after
    that is a span difference, and a span difference is named by what sits on
    the boundary.

    Every class-B paragraph is reported against its CARRIER — the predecessor
    whose height it inherited — because a run of inherited paragraphs is one
    fault, not twenty, and counting them as twenty is what makes the root
    histogram look like a population.
    """
    facts = computed["facts"]
    path_a = cache.get("cached_span_metrics") or {}
    decls = cache.get("declarations") or {}
    grids = cache.get("section_grids") or {}

    victims = {}
    for record in records:
        if record.get("root_mechanism") != "text_line_height":
            continue
        carrier = _carrier_of(record)
        if carrier is None:
            continue
        victims.setdefault(carrier, []).append(record["paragraph"])

    # PATH A over the WHOLE form, not only the carriers: a rule is only clean
    # if it is clean on every line the cache states, and the counter-example
    # this looks for would not be in the class-B population by construction.
    corpus_lines = sum(entry["total"] for entry in path_a.values())
    corpus_exact = sum(entry["exact"] for entry in path_a.values())
    span_agree = span_differ = 0
    span_diff_rows = []
    for address, entry in sorted(path_a.items()):
        cached_spans = [line["span"] for line in entry["lines"]]
        ours = _spans_of(computed["paragraph_lines"].get(address))
        if not ours:
            continue
        if ours == cached_spans:
            span_agree += 1
            continue
        span_differ += 1
        fact = facts.get(address) or {}
        span_diff_rows.append({
            "paragraph": address,
            "line_breaks": fact.get("line_breaks"),
            "cached_lines": len(cached_spans),
            "computed_lines": len(ours),
            "cached_advance_hwp": fact.get("cache_advance_hwp"),
        })

    rows = []
    for carrier, inherited in sorted(victims.items()):
        fact = facts.get(carrier) or {}
        entry = path_a.get(carrier)
        cached_spans = [line["span"] for line in (entry or {}).get("lines")
                        or ()]
        ours = _spans_of(computed["paragraph_lines"].get(carrier))
        decl = decls.get(carrier) or {}
        runs = decl.get("runs") or []
        heights = sorted({run["height_hwp"] for run in runs
                          if run["height_hwp"] is not None})
        cache_origin = cache["origins"].get(carrier) or {}
        computed_origin = computed["origins"].get(carrier) or {}
        rows.append({
            "paragraph": carrier,
            "page": computed_origin.get("page"),
            "class_b_paragraphs": len(inherited),
            "inherited_by": sorted(inherited),
            "cached_spans": cached_spans,
            "computed_spans": ours,
            "spans_agree": bool(cached_spans) and cached_spans == ours,
            "cached_advance_hwp": cache_origin.get("advance_hwp"),
            "computed_advance_hwp": computed_origin.get("advance_hwp"),
            "advance_delta_hwp": (
                None if cache_origin.get("advance_hwp") is None
                or computed_origin.get("advance_hwp") is None
                else computed_origin["advance_hwp"]
                - cache_origin["advance_hwp"]),
            "path_a": (None if entry is None else
                       {"exact": entry["exact"], "total": entry["total"]}),
            "cached_lines": [
                {"span": line["span"],
                 "vertsize_hwp": line["cached_vertsize_hwp"],
                 "textheight_hwp": line["cached_textheight_hwp"],
                 "baseline_hwp": line["cached_baseline_hwp"],
                 "spacing_hwp": line["cached_spacing_hwp"],
                 "ours_vertsize_hwp": line["vertsize_hwp"],
                 "ours_spacing_hwp": line["spacing_hwp"],
                 "control_cells_before_start":
                     line["control_cells_before_start"]}
                for line in (entry or {}).get("lines") or ()],
            "computed_lines": (
                computed["paragraph_lines"].get(carrier) or {}).get("lines"),
            "line_spacing": {"type": fact.get("line_spacing_type"),
                             "value": fact.get("line_spacing_value")},
            "snap_to_grid": (decl.get("para") or {}).get("snap_to_grid"),
            "font_line_height": (decl.get("para")
                                 or {}).get("font_line_height"),
            "section_grid": grids.get(fact.get("section")),
            "line_breaks": fact.get("line_breaks"),
            "tabs": fact.get("tabs"),
            "objects": [obj["kind"] for obj in (fact.get("objects") or ())],
            "run_heights_hwp": heights,
            "mixed_run_sizes": len(heights) > 1,
            "runs": runs,
            "hft_faces": sorted({run["hft_face"] for run in runs
                                 if run["hft_face"]}),
            "face_sources": sorted({run["face_source"] for run in runs
                                    if run["face_source"]}),
            "typography_not_neutral": sorted({
                name for run in runs for name, value in
                (("ratio", run["ratio"]), ("relSz", run["rel_sz"]))
                if value not in (None, 100)}),
            "mechanism": _line_height_mechanism(
                path_a.get(carrier), cached_spans, ours,
                fact.get("line_breaks")),
        })
    return {
        "mechanisms": LINE_HEIGHT_MECHANISMS,
        "carriers": rows,
        "path_a": {"exact": corpus_exact, "total": corpus_lines},
        "spans": {"agree": span_agree, "differ": span_differ},
        "span_differences": span_diff_rows,
    }


def valign_report(cache, computed, records, tol=DEFAULT_TOL_HWP):
    """Every ``cell_valign`` paragraph, and WHICH input to the offset moved.

    ``_render_cell_content`` solves one equation::

        offset = 0                                    vertAlign TOP
               = max(0, (avail_h - block) // 2)                 CENTER
               = max(0, avail_h - block)                        BOTTOM

    so ``d_block_offset`` has exactly two channels, and which one carries it
    decides whose fault it is:

    * ``avail_h`` moved — the ROW under the cell came out a different height,
      and the cell re-centred content it laid out identically.  The cell's
      alignment did nothing wrong; it faithfully re-solved a moved box.
    * ``block`` moved — the cell's own content is a different height, and the
      alignment moved it by half (CENTER) or all (BOTTOM) of that.

    Both terms are recorded as ``_render_cell_content`` solves them, and the
    equation is re-solved here from the recorded inputs rather than asserted,
    so a row whose ``formula_ok`` is false would mean the recorded inputs do
    not explain the drawn offset — which is the answer this view could give
    and does not.
    """
    rows = []
    for record in records:
        if record.get("root_mechanism") != "cell_valign":
            continue
        address = record["paragraph"]
        before = cache["cell_valign"].get(cache["cell_of"].get(address)) or {}
        after = (computed["cell_valign"].get(computed["cell_of"].get(address))
                 or {})
        fact = computed["facts"].get(address) or {}
        segs = fact.get("linesegs") or []
        d_avail = ((after.get("avail_height_hwp") or 0)
                   - (before.get("avail_height_hwp") or 0))
        d_block = ((after.get("block_extent_hwp") or 0)
                   - (before.get("block_extent_hwp") or 0))
        d_offset = (record.get("terms_hwp") or {}).get("d_block_offset_hwp")
        if abs(d_avail) > tol and abs(d_block) > tol:
            channel = "both"
        elif abs(d_avail) > tol:
            channel = "row_height"
        elif abs(d_block) > tol:
            channel = "block_extent"
        else:
            channel = "neither"
        rows.append({
            "paragraph": address,
            "dy_px": record.get("dy_px"),
            "table": before.get("table"),
            "row": before.get("row"),
            "col": before.get("col"),
            "vert_align": before.get("vert_align"),
            "cached_first_line_vertpos_hwp": (segs[0]["vertpos"] if segs
                                              else None),
            "declared_height_hwp": before.get("declared_height_hwp"),
            "cache": {k: before.get(k) for k in
                      ("cell_height_hwp", "avail_height_hwp",
                       "block_extent_hwp", "cached_block_extent_hwp",
                       "offset_hwp", "paragraphs")},
            "computed": {k: after.get(k) for k in
                         ("cell_height_hwp", "avail_height_hwp",
                          "block_extent_hwp", "cached_block_extent_hwp",
                          "offset_hwp", "paragraphs")},
            "d_avail_height_hwp": d_avail,
            "d_block_extent_hwp": d_block,
            "d_block_offset_hwp": d_offset,
            "channel": channel,
            "formula_ok": (d_offset is not None
                           and (after.get("offset_hwp") or 0)
                           - (before.get("offset_hwp") or 0) == d_offset),
        })

    # The counter-example sweep: EVERY aligned cell in the form, not only the
    # ones a class-B paragraph sits in.  A cell whose offset the recorded
    # inputs do not reproduce would refute the equation above wherever it is.
    checked = exact = moved = 0
    for cell_id, after in computed["cell_valign"].items():
        if after.get("vert_align") == "TOP":
            continue
        checked += 1
        block = after.get("block_extent_hwp")
        avail = after.get("avail_height_hwp") or 0
        if block is None:
            continue
        if after["vert_align"] == "CENTER":
            want = max(0, (avail - block) // 2)
        else:
            want = max(0, avail - block)
        if want == after.get("offset_hwp"):
            exact += 1
        if after.get("offset_hwp"):
            moved += 1
    return {
        "rows": rows,
        "channels": dict(Counter(row["channel"] for row in rows)),
        "formula_failures": sum(1 for row in rows if not row["formula_ok"]),
        "aligned_cells": {"checked": checked, "formula_exact": exact,
                          "offset_nonzero": moved},
    }


def line_height_table(rows):
    """The carrier grouping over every form, then the corpus path-A score."""
    blocks = [(stem, report["line_height"]) for stem, report in rows
              if report.get("line_height")]
    if not blocks:
        return "line height: nothing measured"
    out = []
    names = sorted(LINE_HEIGHT_MECHANISMS)
    width = max(len(name) for name in names)
    totals = Counter()
    paras = Counter()
    carrier_of = {}
    for stem, block in blocks:
        for row in block["carriers"]:
            totals[row["mechanism"]] += 1
            paras[row["mechanism"]] += row["class_b_paragraphs"]
            carrier_of.setdefault(row["mechanism"],
                                  f"{stem} para {row['paragraph']}")
    out.append(f"{'mechanism':<{width}} {'carriers':>9} {'class B':>8}  "
               f"one carrier")
    out.append("-" * (width + 40))
    for name in names:
        if not totals[name]:
            continue
        out.append(f"{name:<{width}} {totals[name]:>9} {paras[name]:>8}  "
                   f"{carrier_of.get(name, '-')}")
    exact = sum(block["path_a"]["exact"] for _stem, block in blocks)
    total = sum(block["path_a"]["total"] for _stem, block in blocks)
    agree = sum(block["spans"]["agree"] for _stem, block in blocks)
    differ = sum(block["spans"]["differ"] for _stem, block in blocks)
    out.append("")
    out.append(f"path A (our _line_metrics on the CACHE's own spans): "
               f"{exact} / {total} exact")
    out.append(f"spans (our break pass vs the cache's): {agree} agree / "
               f"{differ} differ")
    out.append("")
    for stem, block in blocks:
        for row in block["carriers"]:
            out.append(
                f"{stem} para {row['paragraph']} p{row['page']}: "
                f"{row['mechanism']}; class B {row['class_b_paragraphs']}; "
                f"advance {row['cached_advance_hwp']} -> "
                f"{row['computed_advance_hwp']} "
                f"({row['advance_delta_hwp']:+d}); path A "
                f"{row['path_a']['exact']}/{row['path_a']['total']}; "
                f"lineBreak {row['line_breaks']}; "
                f"spacing {row['line_spacing']['type']} "
                f"{row['line_spacing']['value']}; "
                f"snapToGrid {row['snap_to_grid']} "
                f"grid {row['section_grid']}; "
                f"run heights {row['run_heights_hwp']}")
            out.append(f"    cached spans {row['cached_spans']}")
            out.append(f"    our spans    {row['computed_spans']}")
    return "\n".join(out)


def valign_table(rows):
    """Which input to the vertical-align offset moved, over every form."""
    blocks = [(stem, report["valign"]) for stem, report in rows
              if report.get("valign")]
    if not blocks:
        return "cell valign: nothing measured"
    totals = Counter()
    carrier_of = {}
    for stem, block in blocks:
        for row in block["rows"]:
            totals[row["channel"]] += 1
            carrier_of.setdefault(
                row["channel"],
                f"{stem} para {row['paragraph']} "
                f"(table {row['table']} r{row['row']}c{row['col']})")
    width = max([len(name) for name in totals] + [len("channel")])
    out = [f"{'channel':<{width}} {'paras':>6}  one carrier",
           "-" * (width + 40)]
    for name, count in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"{name:<{width}} {count:>6}  {carrier_of.get(name, '-')}")
    failures = sum(block["formula_failures"] for _stem, block in blocks)
    checked = sum(block["aligned_cells"]["checked"] for _stem, block in blocks)
    exact = sum(block["aligned_cells"]["formula_exact"]
                for _stem, block in blocks)
    out.append("")
    out.append(f"the recorded inputs reproduce d_block_offset on "
               f"{sum(totals.values()) - failures} of {sum(totals.values())} "
               f"class-B rows")
    out.append(f"offset == the vertAlign equation on {exact} of {checked} "
               f"non-TOP cells in the corpus")
    out.append("")
    for stem, block in blocks:
        for row in block["rows"]:
            out.append(
                f"{stem} para {row['paragraph']} "
                f"(table {row['table']} r{row['row']}c{row['col']} "
                f"{row['vert_align']}): {row['channel']}; "
                f"d_offset {row['d_block_offset_hwp']:+d}; "
                f"avail {row['cache']['avail_height_hwp']} -> "
                f"{row['computed']['avail_height_hwp']}; "
                f"block {row['cache']['block_extent_hwp']} -> "
                f"{row['computed']['block_extent_hwp']}; "
                f"declared {row['declared_height_hwp']}; "
                f"cached first-line vertpos "
                f"{row['cached_first_line_vertpos_hwp']}")
    return "\n".join(out)


def root_histogram(records):
    """One row per ROOT mechanism.  These partition the population."""
    paragraphs = Counter()
    carried = Counter()
    for record in records:
        name = record.get("root_mechanism") or "unmeasurable"
        paragraphs[name] += 1
        carried[name] += abs(record.get("dy_px") or 0.0)
    rows = [{"mechanism": name, "paragraphs": count,
             "dy_px_carried": round(carried[name], 2)}
            for name, count in paragraphs.items()]
    rows.sort(key=lambda row: (-row["paragraphs"], row["mechanism"]))
    return rows


def histogram(records):
    """Mechanism -> paragraphs charged and total |dy| px carried.

    A paragraph can inherit from more than one mechanism, so it is booked
    once per DISTINCT label in its list and its |dy| is booked whole under
    each; the column therefore does not sum to the paragraph count, and
    ``mechanism_breadth`` says how often that matters.
    """
    paragraphs = Counter()
    carried = Counter()
    breadth = Counter()
    for record in records:
        names = record.get("mechanisms") or ["unmeasurable"]
        for name in names:
            paragraphs[name] += 1
            carried[name] += abs(record.get("dy_px") or 0.0)
        breadth["single" if len(names) == 1 else "multiple"] += 1
    rows = [{"mechanism": name, "paragraphs": count,
             "dy_px_carried": round(carried[name], 2)}
            for name, count in paragraphs.items()]
    rows.sort(key=lambda row: (-row["paragraphs"], row["mechanism"]))
    return rows, dict(breadth)


def probe_form(hwpx_path, dpi=own_render.DEFAULT_DPI,
               y_tol=layout_divergence.DEFAULT_Y_TOL, tol=DEFAULT_TOL_HWP,
               repo_root=None, table_origin=False, page_top=False,
               empty=False, line_height=False, valign=False):
    hwpx_path = Path(hwpx_path)
    cache = trace(hwpx_path, own_render.LAYOUT_POLICY_CACHE, dpi, repo_root)
    computed = trace(hwpx_path, own_render.LAYOUT_POLICY_COMPUTED, dpi,
                     repo_root)
    records = decompose(cache, computed, y_tol, tol=tol)
    rows, breadth = histogram(records)
    extra = {}
    if table_origin:
        origin_rows = table_origin_report(cache, computed, records, y_tol,
                                          tol=tol)
        extra["table_origin"] = {
            "summary": table_origin_summary(origin_rows),
            "causes": TABLE_ORIGIN_CAUSES,
            "rows": origin_rows,
        }
    if page_top:
        block = page_top_report(cache, computed, tol=tol)
        bottoms = page_bottom_report(cache, tol=tol)
        extra["page_top"] = {
            "summary": page_top_summary(block),
            "candidates": PAGE_TOP_CANDIDATES,
            "usable_height_hwp": cache["usable_height_hwp"],
            "bottom_bracket": page_bottom_bracket(bottoms),
            "bottoms": bottoms,
            **block,
        }
    if empty:
        extra["empty"] = empty_report(cache, computed, records, tol=tol)
    if line_height:
        extra["line_height"] = line_height_report(cache, computed, records,
                                                  tol=tol)
    if valign:
        extra["valign"] = valign_report(cache, computed, records, tol=tol)
    return {
        "tool": "class_b_probe",
        "source": hwpx_path.name,
        "dpi": dpi,
        "y_tolerance_px": y_tol,
        "tolerance_hwp": tol,
        "rule": RULE,
        "class_b_paragraphs": len(records),
        "split": dict(Counter(record.get("split") for record in records)),
        "carrier_term": dict(Counter(record.get("carrier_term")
                                     for record in records)),
        "container": dict(Counter(record.get("container")
                                  for record in records)),
        "identity_failures": sum(1 for record in records
                                 if record.get("identity_ok") is False),
        "mechanisms": rows,
        "root_mechanisms": root_histogram(records),
        "mechanism_breadth": breadth,
        "paragraphs": records,
        **extra,
    }


def summary_line(stem, report):
    split = report["split"]
    place = report["container"]
    roots = report["root_mechanisms"]
    top = roots[0]["mechanism"] if roots else "-"
    return (f"{stem}: class B {report['class_b_paragraphs']} "
            f"[inherited {split.get('inherited', 0)} / own "
            f"{split.get('own', 0)} / container {split.get('container', 0)} / "
            f"unmeasurable {split.get('unmeasurable', 0)}] "
            f"(top-level {place.get('top_level', 0)} / in-cell "
            f"{place.get('in_cell', 0)}); top mechanism {top}; "
            f"identity failures {report['identity_failures']}")


def corpus_table(rows, key="root_mechanisms", title="root mechanism"):
    totals = Counter()
    carried = Counter()
    for _stem, report in rows:
        for entry in report[key]:
            totals[entry["mechanism"]] += entry["paragraphs"]
            carried[entry["mechanism"]] += entry["dy_px_carried"]
    names = sorted(totals, key=lambda name: (-totals[name], name))
    width = max([len(name) for name in names] + [len(title)])
    out = [f"{title:<{width}} {'paras':>6} {'|dy| px':>10}  per form"]
    out.append("-" * (width + 34))
    for name in names:
        per = " ".join(
            f"{stem}:{entry['paragraphs']}"
            for stem, report in rows
            for entry in report[key] if entry["mechanism"] == name)
        out.append(f"{name:<{width}} {totals[name]:>6} "
                   f"{carried[name]:>10.2f}  {per}")
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="class_b_probe.py",
        description="Decompose every class-B paragraph's first-line dy into "
                    "named container, inherited and own terms. Measures; "
                    "changes nothing.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every corpus form and print a table")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--y-tol", type=float,
                        default=layout_divergence.DEFAULT_Y_TOL,
                        help="the class-B threshold, in pixels "
                             "(default 0.01, layout_divergence's own)")
    parser.add_argument("--tol", type=float, default=DEFAULT_TOL_HWP,
                        help="a term at or under this many HWPUNIT is zero "
                             "(default 0.5 — the terms are integers)")
    parser.add_argument("--table-origin", action="store_true",
                        help="also dump, for every class-B paragraph riding a "
                             "MOVED table origin, the holder paragraph, the "
                             "table's hp:pos attributes, its seat and height "
                             "under both policies, and which term carries the "
                             "delta")
    parser.add_argument("--page-top", action="store_true",
                        help="also dump, for the first cached paragraph on "
                             "every page, its space-before, the previous "
                             "paragraph's space-after and how the page was "
                             "started, and score every candidate rule for "
                             "its cached seat against the measurement; plus "
                             "the mirror at the page foot")
    parser.add_argument("--empty", action="store_true",
                        help="also dump every INKLESS paragraph — what the "
                             "cache gives it, what it declares, and what this "
                             "renderer's own empty-paragraph rule makes of it "
                             "— and score the page-foot candidates for what "
                             "the cache does with one that does not fit")
    parser.add_argument("--line-height", action="store_true",
                        help="also score our line-height rule against the "
                             "cached hp:lineseg ON THE CACHE'S OWN SPANS "
                             "(path A), then name what is left over: every "
                             "text_line_height paragraph against the carrier "
                             "it inherited from, with the spans both passes "
                             "produced, what the paragraph and its runs "
                             "declare, and whether a control cell sits on the "
                             "cached boundary")
    parser.add_argument("--valign", action="store_true",
                        help="also dump, for every cell_valign paragraph, the "
                             "cell's vertAlign, its declared / cached / drawn "
                             "height, the block extent we solve the alignment "
                             "against and the cached first-line vertpos, and "
                             "say which of the two inputs to the offset moved")
    parser.add_argument("--json", help="write the full per-paragraph report")
    return parser


def page_top_table(rows):
    """Candidate scores over every form, then the rows that discriminate."""
    blocks = [(stem, report["page_top"]) for stem, report in rows
              if report.get("page_top")]
    if not blocks:
        return "page top: nothing measured"
    out = []
    width = max(len(name) for name in PAGE_TOP_CANDIDATES)
    total = sum(block["summary"]["page_tops"] for _stem, block in blocks)
    out.append(f"{'candidate':<{width}} {'exact':>9}  per form")
    out.append("-" * (width + 40))
    for name in PAGE_TOP_CANDIDATES:
        hits = sum(block["summary"]["exact"][name] for _stem, block in blocks)
        per = " ".join(
            f"{stem}:{block['summary']['exact'][name]}/"
            f"{block['summary']['page_tops']}"
            for stem, block in blocks)
        out.append(f"{name:<{width}} {hits:>4}/{total:<4}  {per}")
    out.append("")
    for name, text in PAGE_TOP_CANDIDATES.items():
        out.append(f"{name}: {text}")
    out.append("")
    discriminating = sum(block["summary"]["discriminating_page_tops"]
                         for _stem, block in blocks)
    out.append(f"page tops {total}, of which {discriminating} carry a nonzero "
               f"space-before or space-after and can tell the candidates "
               f"apart")
    for stem, block in blocks:
        for row in block["page_tops"]:
            if not (row["margin_prev_hwp"] or row["prev"]["margin_next_hwp"]):
                continue
            failed = sorted(name for name, ok in row["matches"].items()
                            if not ok)
            out.append(
                f"  {stem} page {row['page']} head p{row['paragraph']} "
                f"vertpos={row['cache_vertpos_hwp']} "
                f"margin_prev={row['margin_prev_hwp']} "
                f"prev p{row['prev']['paragraph']} "
                f"margin_next={row['prev']['margin_next_hwp']} "
                f"ended_prev_page={row['prev']['ended_previous_page']} "
                f"overflow_start={row['started_by_overflow']} "
                f"pageBreakBefore={row['page_break_before']} "
                f"keepWithNext={row['keep_with_next']} "
                f"lineSpacing={row['line_spacing']['type']}"
                f"/{row['line_spacing']['value']} "
                f"holds={row['holds']['object_kinds'] or '-'} "
                f"col={row['column']}/{row['col_count']} "
                f"ours={row['computed_top_hwp']} -> refutes {failed or '-'}")
    out.append("")
    orphans = [(stem, row) for stem, block in blocks
               for row in block["page_tops"]
               if not any(row["matches"].values())]
    out.append(f"page tops no candidate reproduces: {len(orphans)}")
    for stem, row in orphans:
        out.append(
            f"  {stem} page {row['page']} head p{row['paragraph']} "
            f"vertpos={row['cache_vertpos_hwp']} "
            f"margin_prev={row['margin_prev_hwp']} "
            f"overflow_start={row['started_by_overflow']} "
            f"holds={row['holds']['object_kinds'] or '-'} "
            f"ours={row['computed_top_hwp']}")
    out.append("")
    kept = sum(block["summary"]["cell_tops_keeping_margin_prev"]
               for _stem, block in blocks)
    with_margin = sum(block["summary"]["cell_tops_with_margin_prev"]
                      for _stem, block in blocks)
    cells = sum(block["summary"]["cell_tops"] for _stem, block in blocks)
    dropped = sum(block["summary"]["cell_tops_dropping_margin_prev"]
                  for _stem, block in blocks)
    out.append(f"container mirror: {cells} cell-first paragraphs, "
               f"{with_margin} with a nonzero space-before, {kept} seat it at "
               f"exactly margin_prev, {dropped} at zero")
    out.append("")
    out.append("page foot mirror (was margin_next reserved?)")
    for stem, block in blocks:
        bracket = block["bottom_bracket"]
        out.append(f"  {stem}: feet {bracket['page_feet']}, with "
                   f"margin_next {bracket['with_margin_next']}, reserve "
                   f"required {bracket['reserve_required']}, refuted "
                   f"{bracket['reserve_refuted']}, silent {bracket['silent']}")
    return "\n".join(out)


def table_origin_table(rows):
    """The per-cause histogram, plus one line per table it was measured on."""
    out = []
    per_cause = {}
    for stem, report in rows:
        block = report.get("table_origin")
        if not block:
            continue
        for row in block["rows"]:
            per_cause.setdefault(row["cause"], []).append((stem, row))
    if not per_cause:
        return "table origin: no class-B paragraph rides a moved table origin"
    width = max(len(name) for name in per_cause)
    out.append(f"{'cause':<{width}} {'paras':>6}  tables (form:table:paras)")
    out.append("-" * (width + 40))
    for cause in sorted(per_cause, key=lambda c: (-len(per_cause[c]), c)):
        entries = per_cause[cause]
        tally = Counter((stem, row.get("table")) for stem, row in entries)
        per = " ".join(f"{stem}:tbl{table}:{count}"
                       for (stem, table), count in sorted(tally.items()))
        out.append(f"{cause:<{width}} {len(entries):>6}  {per}")
    out.append("")
    for cause in sorted(per_cause):
        out.append(f"{cause}: {TABLE_ORIGIN_CAUSES.get(cause, '?')}")
    out.append("")
    seen = set()
    for cause, entries in sorted(per_cause.items()):
        for stem, row in entries:
            key = (stem, row.get("table"))
            if key in seen:
                continue
            seen.add(key)
            place = row.get("placement") or {}
            pos = place.get("pos") or {}
            terms = row.get("terms_hwp") or {}
            out.append(
                f"{stem} tbl{row.get('table')} page {row.get('page')} "
                f"holder p{(row.get('holder') or {}).get('paragraph')} "
                f"(class {(row.get('holder') or {}).get('classes')}, "
                f"lines {(row.get('holder') or {}).get('lines')}) "
                f"{'inline' if place.get('inline') else 'anchored'} "
                f"vertRelTo={pos.get('vertRelTo')} "
                f"vertOffset={pos.get('vertOffset')} "
                f"treatAsChar={pos.get('treatAsChar')} "
                f"textWrap={place.get('text_wrap')} "
                f"outMargin.top={(place.get('out_margin_hwp') or {}).get('top')}"
                f" | d_slot={terms.get('d_slot_y_hwp')} "
                f"d_holder_top={terms.get('d_holder_block_top_hwp')} "
                f"d_within={terms.get('d_within_holder_hwp')} "
                f"d_height={terms.get('d_height_hwp')} "
                f"-> {cause}")
    return "\n".join(out)


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    if args.corpus:
        forms = layout_divergence.corpus_forms(repo_root)
        labels = layout_divergence.short_labels([hwpx.stem
                                                 for hwpx, _ in forms])
        rows = []
        for hwpx, _pdf in forms:
            report = probe_form(hwpx, dpi=args.dpi, y_tol=args.y_tol,
                                tol=args.tol, repo_root=repo_root,
                                table_origin=args.table_origin,
                                page_top=args.page_top, empty=args.empty,
                                line_height=args.line_height,
                                valign=args.valign)
            if report["class_b_paragraphs"]:
                print(summary_line(labels[hwpx.stem], report))
            rows.append((labels[hwpx.stem], report))
        print()
        print(corpus_table(rows))
        print()
        print(corpus_table(rows, key="mechanisms", title="every mechanism"))
        if args.table_origin:
            print()
            print(table_origin_table(rows))
        if args.page_top:
            print()
            print(page_top_table(rows))
        if args.empty:
            print()
            print(empty_table(rows))
        if args.line_height:
            print()
            print(line_height_table(rows))
        if args.valign:
            print()
            print(valign_table(rows))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    stem = Path(args.input).stem
    report = probe_form(Path(args.input), dpi=args.dpi, y_tol=args.y_tol,
                        tol=args.tol, repo_root=repo_root,
                        table_origin=args.table_origin,
                        page_top=args.page_top, empty=args.empty,
                        line_height=args.line_height, valign=args.valign)
    print(summary_line(stem, report))
    print()
    print(corpus_table([(stem, report)]))
    print()
    print(corpus_table([(stem, report)], key="mechanisms",
                       title="every mechanism"))
    if args.table_origin:
        print()
        print(table_origin_table([(stem, report)]))
    if args.page_top:
        print()
        print(page_top_table([(stem, report)]))
    if args.empty:
        print()
        print(empty_table([(stem, report)]))
    if args.line_height:
        print()
        print(line_height_table([(stem, report)]))
    if args.valign:
        print()
        print(valign_table([(stem, report)]))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
