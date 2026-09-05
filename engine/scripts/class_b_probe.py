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

Usage::

    python engine/scripts/class_b_probe.py --corpus
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
        self._container_stack = [(0, 0)]
        self._table_origin = None
        self._floating_para = None

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

    def _render_table(self, draw, tbl, origin_hwp):
        holder = self._floating_para or self._tracing_para
        address = (self.paragraph_index.get(id(holder.el))
                   if holder is not None else None)
        outer = self._table_origin
        self._table_origin = (id(tbl), origin_hwp[1], address)
        try:
            return super()._render_table(draw, tbl, origin_hwp)
        finally:
            self._table_origin = outer

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
        return super()._render_cell_content(draw, cell, x0, y0, x1, y1)

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
        self._note_origin(para, origin_hwp[1] + rebase,
                          (lines[0]["vertpos"] if lines else 0),
                          len(lines or ()), advance, "computed")
        return super()._render_computed_lines(draw, para, origin_hwp, lines,
                                              *args, **kwargs)

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


def trace(hwpx_path, policy, dpi, repo_root=None):
    """One render under one policy: seats, cell boxes, line boxes, facts."""
    renderer = SeatingRenderer(hwpx_path, dpi=dpi, repo_root=repo_root,
                               layout_policy=policy)
    _images, sidecar = renderer.render()
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
    return {
        "origins": dict(renderer.paragraph_origins),
        "cell_boxes": dict(renderer.cell_boxes),
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
    }


def top_level_seats(cache, computed):
    """``{address: d_seat}`` for TOP-LEVEL paragraphs, inkless ones included.

    The cache seat is the paragraph's first ``hp:lineseg@vertpos``, measured
    from the body top, and the computed one is where the flow pass placed its
    block: exactly the pair ``layout_divergence``'s seat pass compares, reused
    here rather than re-derived.  Under ``cache`` no top-level paragraph is
    relaid out, so the cursor never shifts and this agrees with the drawn
    origin wherever both exist; what it adds is the paragraphs that draw
    nothing at all.
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
                         "advance_hwp": later.get("advance_hwp")})
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


def _root(record, tol):
    """ONE mechanism per class-B paragraph: the biggest term, followed down.

    The histogram over ``mechanisms`` books a paragraph under every mechanism
    it inherits from, which is honest but does not rank.  This picks the term
    that carries most of the paragraph's ``dy``, follows a moved table up to
    the paragraph that holds it, and names what it finds there — so the roots
    partition the population and can be counted against each other.
    """
    term = record.get("carrier_term")
    if term == "d_container_y_hwp":
        cell = record.get("cell") or {}
        if cell.get("carrier") == "table_origin":
            largest = _largest((record.get("holder") or {}).get("carriers"))
            return (largest["mechanism"] if largest
                    else "table_origin_unattributed")
        return "table_row_heights" if cell.get("carrier") else "cell_unattributed"
    if term == "d_block_offset_hwp":
        return "cell_valign"
    if term == "d_seat_hwp":
        largest = _largest(record.get("carriers"))
        return largest["mechanism"] if largest else "seat_unattributed"
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
    for address, later in computed["origins"].items():
        earlier = cache["origins"].get(address)
        if earlier is None or later["page"] != earlier["page"]:
            continue
        d_seat[address] = later["seat_hwp"] - earlier["seat_hwp"]
    #: Per-address metrics for ``mechanism``, preferring what was drawn.
    metrics = {"cache": dict(cache["origins"]),
               "computed": dict(computed["origins"])}
    for address, (delta, before, after) in top_level_seats(cache,
                                                           computed).items():
        d_seat[address] = delta
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
    #: chain, because the cursor it did not move is exactly the point.
    steps = {}
    for key, addresses in by_container.items():
        previous = None
        for address in addresses:
            here = d_seat.get(address)
            if here is None:
                continue
            if previous is not None:
                prior_address, prior = previous
                steps.setdefault(key, {})[prior_address] = here - prior
            previous = (address, here)

    def carriers_for(address):
        """Every predecessor in ``address``' container charged with a step."""
        found = []
        for prior in by_container.get(keys.get(address), ()):
            if prior >= address:
                break
            step = (steps.get(keys.get(address)) or {}).get(prior)
            if step is None or abs(step) <= tol:
                continue
            name, detail = mechanism(facts.get(prior) or {},
                                     metrics["cache"].get(prior),
                                     metrics["computed"].get(prior), tol=tol)
            found.append({"paragraph": prior, "step_hwp": step,
                          "mechanism": name, "detail": detail})
        return found

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
                    named.append("via_holder:unattributed")
        if abs(terms["d_block_offset_hwp"]) > tol:
            named.append("cell_valign")
        carriers = []
        if abs(terms["d_seat_hwp"]) > tol:
            carriers = carriers_for(address)
            named.extend(entry["mechanism"] for entry in carriers)
            if not carriers:
                named.append("seat_unattributed")
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
        record["root_mechanism"] = _root(record, tol)
        record["single_term"] = len(significant) == 1
        record["split"] = (
            "inherited" if record["carrier_term"] == "d_seat_hwp"
            else "own" if record["carrier_term"] == "d_first_offset_hwp"
            else "container" if significant else "unattributed")
        records.append(record)
    return records


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
               repo_root=None):
    hwpx_path = Path(hwpx_path)
    cache = trace(hwpx_path, own_render.LAYOUT_POLICY_CACHE, dpi, repo_root)
    computed = trace(hwpx_path, own_render.LAYOUT_POLICY_COMPUTED, dpi,
                     repo_root)
    records = decompose(cache, computed, y_tol, tol=tol)
    rows, breadth = histogram(records)
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
    parser.add_argument("--json", help="write the full per-paragraph report")
    return parser


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
                                tol=args.tol, repo_root=repo_root)
            if report["class_b_paragraphs"]:
                print(summary_line(labels[hwpx.stem], report))
            rows.append((labels[hwpx.stem], report))
        print()
        print(corpus_table(rows))
        print()
        print(corpus_table(rows, key="mechanisms", title="every mechanism"))
        if args.json:
            Path(args.json).write_text(
                json.dumps(dict(rows), ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.input:
        build_parser().error("an input .hwpx is required without --corpus")
    stem = Path(args.input).stem
    report = probe_form(Path(args.input), dpi=args.dpi, y_tol=args.y_tol,
                        tol=args.tol, repo_root=repo_root)
    print(summary_line(stem, report))
    print()
    print(corpus_table([(stem, report)]))
    print()
    print(corpus_table([(stem, report)], key="mechanisms",
                       title="every mechanism"))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
