#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text geometry from the REAL render, mapped back to editable addresses.

This is what makes editing ON the page possible instead of beside it. Every
rectangle here comes out of a PDF that Hancom itself laid out — read with
PyMuPDF — so the positions are Hancom's, not ours. Nothing is synthesized. When
there is no PDF there is no geometry, and the answer says so in the same
structured shape ``document/render`` uses.

A SEPARATE METHOD, NOT A FIELD ON RENDER. ``document/render`` returns bytes for
one zoom; geometry is zoom-independent. Bundling them would force a client to
re-extract every span each time the user zooms, and would push a raster plus a
few hundred spans through one frame that already caps inline images at 512 KiB.
So ``document/pageGeometry`` is its own call, cached on the PDF's hash.

COORDINATES: normalized. Every rect is ``[x0, y0, x1, y1]`` as fractions of the
page, origin TOP-LEFT with y increasing downward — PyMuPDF's own convention,
and the one a raster is drawn in, so the Desktop multiplies by its pixel size
and is done. ``pageSize`` carries the points if a caller wants them back.

THE UNIT IS A LINE. PyMuPDF splits a line into spans at every font run, so a
form label set in two weights arrives as two fragments and would never match
its own text. Lines are the unit a label actually occupies, so lines are what
this emits and what mapping matches on.

AMBIGUITY IS REAL AND IS NEVER RESOLVED BY GUESSING. A label printed on six
sheets of one document matches six addresses; that span reports all six as
candidates with ``confidence: "ambiguous"`` and ``address: null``. Silently
taking the first is precisely the defect T41 records
(engine/scripts/preedit.py:221) — a single key overwrote five sibling
contracts, and no offline gate caught it because the label survived as a
prefix. An unmapped span is ``address: null`` too, and still renders: it is
text on a page that happens not to be editable.

EMPTY SEATS COME FROM THE DRAWN GRID. An empty fill cell has no text, so text
matching can never reach it — measured against the whole corpus, 10 forms and
51 pages, text-based derivation placed 0 of 473 editable fill regions. What
does enclose an empty cell is the ruling Hancom actually strokes on the page,
so the grid is rebuilt from those segments and aligned to the form scan. The
alignment is checked against the page's own text at every step and abandoned
where the check fails; see ``align_drawn_grid``. A seat it cannot reach stays
absent with a reason, because a box in the wrong place is worse than no box.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import RpcError  # noqa: E402
from rt_render import (  # noqa: E402
    RASTERIZABLE_SUFFIXES,
    UNAVAILABLE_REASONS,
    rasterizer_facts,
    rasterizer_module,
    resolve_artifact,
)

#: Fractions of the page, origin top-left, y down.
GEOMETRY_UNIT = "normalized"
GEOMETRY_ORIGIN = "top-left"

#: How a seat's rectangle was arrived at. Closed, and reported per seat so the
#: Desktop can style certainty instead of implying it.
DERIVATION_METHODS = (
    "matched_text",   # the seat has text, and that text matched a span
    "cell_borders",   # a rule actually drawn on the page encloses the seat
    "interpolated",   # inferred from a matched label in the same table row
)

#: How sure the mapping is for one span.
CONFIDENCES = ("unique", "ambiguous", "unmapped")

#: Cached extractions, keyed on the PDF's sha256 and the page index. Bounded,
#: because a cache without a bound is a leak with a nice name.
MAX_CACHE_ENTRIES = 64

#: A drawn rect is only believed to be a cell when it is not the whole page and
#: not a hairline: sanity, not cleverness.
MIN_SEAT_AREA_PT = 4.0
MAX_SEAT_PAGE_FRACTION = 0.6

#: Why a fill seat has no rect on this page. Closed, reported per page, and
#: counted — absence the Desktop can explain beats absence it has to invent a
#: story for.
ABSENCE_REASONS = (
    "no_drawn_grid",       # the page draws no closed cell at all
    "no_anchor_on_page",   # nothing of this table was identified on this page
    "no_anchor_in_row",    # the table is anchored here, this row is not reached
    "grid_gap",            # no drawn cell adjacent where the next one should be
    "cell_mismatch",       # the drawn cell there contradicts the declared cell
    "alignment_failed",    # two anchors disagree, or an anchor failed its check
)

# -- reconstructing the drawn grid ---------------------------------------------
# Hancom does NOT emit table cells as rectangles. Measured on all 10 corpus
# renders: every ruling arrives as a stroked LINE segment ("l" items), so the
# per-drawing ``rect`` is a hairline and MIN_SEAT_AREA_PT threw every one of
# them away. That is precisely why 473 fill regions got 0 seats. The grid has
# to be rebuilt from the segments themselves.

#: A segment counts as axis-parallel within this many points.
RULE_AXIS_TOL = 0.8
#: Below this a segment is a rounding artefact, not a mark. Length is judged
#: on the JOINED rule, not on the pieces: measured on the corpus renders,
#: 12,045 of 13,972 horizontal segments are under 3pt and their collinear gaps
#: cluster at 0.4-0.8pt — those are dashes, and a dashed border is a border.
#: Discarding the pieces first would throw the rule away before it existed.
RULE_MIN_SEGMENT_PT = 0.2
#: A joined rule shorter than this is a tick or a glyph stroke, not a rule.
RULE_MIN_LENGTH_PT = 3.0
#: Segments this close on the cross axis are one rule drawn more than once.
RULE_CLUSTER_TOL = 2.0
#: Collinear segments with a gap no larger than this are one rule.
RULE_JOIN_TOL = 2.0
#: Slack allowed when asking whether a rule spans an edge.
RULE_COVER_TOL = 2.0
#: Below these a "cell" is the gap between a double rule, not a cell.
MIN_CELL_WIDTH_PT = 6.0
MIN_CELL_HEIGHT_PT = 5.0

#: Drawn cells share a row when their top and bottom agree within this.
SEAT_BAND_TOL = 2.5
#: Two drawn cells are neighbours when one's right edge is the other's left.
SEAT_ADJACENCY_TOL = 2.5


def normalizer():
    """The residue gate's normalizer, imported — never re-derived.

    ``pipeline/scripts/check_residue.py:96`` publishes ``normalize_text`` as a
    public alias precisely so that anything deciding whether two strings are
    "the same string" agrees with the gate. A second whitespace rule here would
    be a second vocabulary, and the two would drift the first time one of them
    was tuned.
    """
    try:
        pipeline = Path(__file__).resolve().parents[2] / "pipeline" / "scripts"
        if str(pipeline) not in sys.path:
            sys.path.insert(0, str(pipeline))
        from check_residue import normalize_text
    except Exception:  # noqa: BLE001 - absence is reported, not worked around
        return None
    return normalize_text


def geometry_capability() -> dict:
    raster = rasterizer_facts()
    return {
        "state": raster["state"],
        "reason": raster["reason"],
        "method": "document/pageGeometry",
        "unit": GEOMETRY_UNIT,
        "origin": GEOMETRY_ORIGIN,
        "spanUnit": "line",
        "derivationMethods": list(DERIVATION_METHODS),
        "confidences": list(CONFIDENCES),
        "normalizer": ("pipeline/scripts/check_residue.py normalize_text — "
                       "imported, so page matching and the residue gate cannot "
                       "disagree about what the same string is"),
        "mappingSource": "the session's form scan (anchors and table cells)",
        "absenceReasons": list(ABSENCE_REASONS),
        "limits": {
            "truncatedCells": ("a cell whose text_preview is truncated is "
                               "excluded from matching: a 30-character prefix "
                               "is a guess, not a match"),
            "ambiguity": "reported as candidates; never resolved by picking one",
            "cellBorders": ("a seat is placed only where the page draws a "
                            "closed box AND the text in the boxes walked to "
                            "reach it matches the form scan; an unruled form "
                            "and an unanchored table both place nothing"),
        },
        "unavailableReasons": list(UNAVAILABLE_REASONS),
    }


def _unavailable(session, reason: str, detail: str, **extra) -> dict:
    assert reason in UNAVAILABLE_REASONS, reason
    return {
        "sessionId": session.id,
        "available": False,
        "unavailable": {"reason": reason, "detail": detail, **extra},
        "capability": geometry_capability(),
    }


# --- extraction ---------------------------------------------------------------

def _norm_rect(rect, width: float, height: float) -> list:
    x0, y0, x1, y1 = (float(v) for v in rect)
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [round(max(0.0, min(1.0, x0 / width)), 6),
            round(max(0.0, min(1.0, y0 / height)), 6),
            round(max(0.0, min(1.0, x1 / width)), 6),
            round(max(0.0, min(1.0, y1 / height)), 6)]


def ruling_segments(drawings: list) -> tuple[list, list]:
    """Axis-parallel rules actually stroked on the page, in POINTS.

    ``(horizontal, vertical)``, each entry ``[position, low, high]`` — a
    horizontal rule is a y with an x range, a vertical rule an x with a y
    range. Both ``l`` (line) and ``re`` (rectangle) items contribute; a
    rectangle is taken apart into its four edges, because a rule drawn as a
    thin filled box is still a rule. Anything neither horizontal nor vertical
    is dropped: a diagonal is not a cell border.
    """
    horizontal: list = []
    vertical: list = []
    for drawing in drawings:
        for item in drawing.get("items") or []:
            if not item:
                continue
            kind = item[0]
            if kind == "l":
                start, end = item[1], item[2]
                edges = [(start[0], start[1], end[0], end[1])]
            elif kind == "re":
                box = item[1]
                x0, y0, x1, y1 = (float(box[0]), float(box[1]),
                                  float(box[2]), float(box[3]))
                edges = [(x0, y0, x1, y0), (x1, y0, x1, y1),
                         (x1, y1, x0, y1), (x0, y1, x0, y0)]
            else:
                continue
            for ax, ay, bx, by in edges:
                ax, ay, bx, by = float(ax), float(ay), float(bx), float(by)
                if abs(ay - by) <= RULE_AXIS_TOL and \
                        abs(ax - bx) >= RULE_MIN_SEGMENT_PT:
                    horizontal.append([(ay + by) / 2.0, min(ax, bx), max(ax, bx)])
                elif abs(ax - bx) <= RULE_AXIS_TOL and \
                        abs(ay - by) >= RULE_MIN_SEGMENT_PT:
                    vertical.append([(ax + bx) / 2.0, min(ay, by), max(ay, by)])
    return horizontal, vertical


def cluster_rules(rules: list) -> list:
    """Segments -> ``[(position, [covered intervals])]``, sorted by position.

    Two passes of the same idea: segments within ``RULE_CLUSTER_TOL`` on the
    cross axis are one rule (a border drawn twice, or a rule with a shadow),
    and collinear pieces within ``RULE_JOIN_TOL`` are one stretch of it. A
    dashed border therefore comes back as the continuous rule a reader sees.
    """
    grouped: list = []
    for position, low, high in sorted(rules):
        if grouped and position - grouped[-1][0] <= RULE_CLUSTER_TOL:
            grouped[-1][1].append([low, high])
        else:
            grouped.append((position, [[low, high]]))
    out = []
    for position, intervals in grouped:
        intervals.sort()
        merged: list = []
        for low, high in intervals:
            if merged and low <= merged[-1][1] + RULE_JOIN_TOL:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        kept = [span for span in merged
                if span[1] - span[0] >= RULE_MIN_LENGTH_PT]
        if kept:
            out.append((position, kept))
    return out


def _spans_edge(intervals: list, low: float, high: float) -> bool:
    """Does one unbroken stretch of this rule run from ``low`` to ``high``?"""
    return any(start <= low + RULE_COVER_TOL and end >= high - RULE_COVER_TOL
               for start, end in intervals)


def drawn_cells(horizontal: list, vertical: list, width: float,
                height: float) -> list:
    """The smallest rectangles whose four sides are all actually drawn.

    Minimality is the whole point, and it is why this cannot be a plain
    product of the x and y rule positions. A page carries several independent
    tables; a vertical rule belonging to the lower one would otherwise slice
    the upper one's columns into cells nobody drew. So each candidate grows
    from a corner to the NEAREST partner rules that genuinely close it, which
    keeps every table's own geometry to itself.
    """
    rows = cluster_rules(horizontal)
    columns = cluster_rules(vertical)
    ys = [position for position, _ in rows]
    xs = [position for position, _ in columns]
    by_y = dict(rows)
    by_x = dict(columns)
    page_area = max(width * height, 1.0)
    cells = []
    for top_index, top in enumerate(ys):
        for left_index, left in enumerate(xs):
            # the corner itself has to exist before anything is built on it
            if not (_spans_edge(by_y[top], left, left)
                    and _spans_edge(by_x[left], top, top)):
                continue
            found = None
            for right in xs[left_index + 1:]:
                if right - left < MIN_CELL_WIDTH_PT:
                    continue
                if not _spans_edge(by_y[top], left, right):
                    break   # the top rule stops here; nothing wider can close
                for bottom in ys[top_index + 1:]:
                    if bottom - top < MIN_CELL_HEIGHT_PT:
                        continue
                    if not _spans_edge(by_x[left], top, bottom):
                        break   # the left rule stops here
                    if _spans_edge(by_x[right], top, bottom) and \
                            _spans_edge(by_y[bottom], left, right):
                        found = (left, top, right, bottom)
                        break
                if found:
                    break
            if found is None:
                continue
            area = (found[2] - found[0]) * (found[3] - found[1])
            if area < MIN_SEAT_AREA_PT:
                continue
            if area / page_area > MAX_SEAT_PAGE_FRACTION:
                continue    # that is the page frame, not a cell
            cells.append(found)
    return cells


def extract_page(module, path: Path, page: int) -> dict:
    """Lines and drawn rects for one page, in POINTS. Mapping normalizes later."""
    try:
        document = module.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise RpcError("render_failed", "the PDF could not be opened",
                       detail=f"{type(exc).__name__}: {exc}"[:400]) from exc
    try:
        count = document.page_count
        if page >= count:
            raise RpcError("page_out_of_range",
                           f"page {page} does not exist; the document has "
                           f"{count}", page=page, pageCount=count)
        loaded = document.load_page(page)
        box = loaded.rect
        lines = []
        try:
            payload = loaded.get_text("dict")
        except Exception as exc:  # noqa: BLE001
            raise RpcError("render_failed", "the page text could not be read",
                           page=page,
                           detail=f"{type(exc).__name__}: {exc}"[:400]) from exc
        for block in payload.get("blocks", []):
            for line in block.get("lines", []) or []:
                spans = line.get("spans") or []
                text = "".join(str(span.get("text") or "") for span in spans)
                if not text.strip():
                    continue
                lines.append({"text": text, "bbox": list(line.get("bbox") or
                                                         (0, 0, 0, 0)),
                              "spanCount": len(spans)})
        rects = []
        cells = []
        try:
            drawings = list(loaded.get_drawings())
        except Exception:  # noqa: BLE001 - drawings are a refinement, not a need
            drawings = []
        for drawing in drawings:
            rect = drawing.get("rect")
            if rect is None:
                continue
            rects.append([float(rect[0]), float(rect[1]),
                          float(rect[2]), float(rect[3])])
        try:
            horizontal, vertical = ruling_segments(drawings)
            cells = drawn_cells(horizontal, vertical,
                                float(box.width), float(box.height))
        except Exception:  # noqa: BLE001 - a grid that cannot be read is absent
            cells = []
        return {"pageCount": int(count),
                "widthPt": round(float(box.width), 2),
                "heightPt": round(float(box.height), 2),
                "lines": lines, "drawnRects": rects, "drawnCells": cells}
    finally:
        try:
            document.close()
        except Exception:  # noqa: BLE001
            pass


# --- mapping -------------------------------------------------------------------

def build_targets(profile: dict, normalize) -> tuple[dict, dict]:
    """normalized text -> [addresses], plus what was deliberately left out."""
    targets: dict[str, list] = {}
    truncated = 0

    def add(key: str, address: dict) -> None:
        if not key:
            return
        targets.setdefault(key, []).append(address)

    for record in profile.get("anchor_records") or []:
        text = record.get("text")
        if not isinstance(text, str):
            continue
        add(normalize(text), {"kind": "anchor", "text": text,
                              "atPara": record.get("at_para")})

    for table in profile.get("table_map") or []:
        for cell in table.get("cells") or []:
            addr = cell.get("addr") or {}
            preview = cell.get("text_preview")
            if not isinstance(preview, str) or not preview.strip():
                continue
            if cell.get("truncated"):
                # A 30-char prefix is a guess. Excluded, and counted so the
                # answer can say how much it declined to guess about.
                truncated += 1
                continue
            add(normalize(preview), {
                "kind": "cell", "table": table.get("index"),
                "row": addr.get("row"), "col": addr.get("col"),
                "classification": cell.get("classification"),
                "text": preview,
            })
    return targets, {"truncatedCells": truncated}


def map_spans(lines: list, targets: dict, normalize, width: float,
              height: float) -> list:
    """One span per line, with a unique address, candidates, or nothing."""
    spans = []
    for index, line in enumerate(lines):
        key = normalize(line["text"])
        matches = targets.get(key) or []
        span = {
            "index": index,
            "text": line["text"],
            "rect": _norm_rect(line["bbox"], width, height),
            "address": None,
            "confidence": "unmapped",
        }
        if len(matches) == 1:
            span["address"] = matches[0]
            span["confidence"] = "unique"
        elif len(matches) > 1:
            # Never pick one. T41: a single unscoped key overwrote five sibling
            # contracts and every offline gate passed.
            span["confidence"] = "ambiguous"
            span["candidates"] = list(matches)
        spans.append(span)
    return spans


# --- empty seats ----------------------------------------------------------------

def _cell_span_index(spans: list) -> dict:
    """(table,row,col) -> span, for uniquely mapped cells only."""
    index: dict = {}
    for span in spans:
        address = span.get("address")
        if not address or address.get("kind") != "cell":
            continue
        key = (address.get("table"), address.get("row"), address.get("col"))
        index.setdefault(key, span)
    return index


def _containing_drawn_rect(rects: list, point: tuple, page_area: float):
    """The smallest drawn rectangle that encloses a point and looks like a cell."""
    x, y = point
    best = None
    best_area = None
    for rect in rects:
        x0, y0, x1, y1 = rect
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        area = (x1 - x0) * (y1 - y0)
        if area < MIN_SEAT_AREA_PT:
            continue
        if page_area > 0 and area / page_area > MAX_SEAT_PAGE_FRACTION:
            continue  # that is the page frame, not a cell
        if best_area is None or area < best_area:
            best, best_area = rect, area
    return best


def sole_cell_address(span: dict):
    """The one table cell this span can be, or None — for GRID ANCHORING only.

    This is deliberately weaker than ``span["address"]`` and never writes to
    it. Measured on the corpus: a form label is routinely registered twice in
    the target set, once as an ``anchor_record`` and once as the table cell it
    sits in, so ``map_spans`` sees two matches and correctly reports
    ``ambiguous`` — the span could be either KIND of address. Across the 10
    corpus forms that left 11 uniquely-mapped cell spans in total, far too few
    to align anything.

    But a candidate list naming one anchor and ONE cell does not disagree
    about WHERE it is; it disagrees about what to call it. For placing a
    rectangle only the cell matters, and there is exactly one, so nothing is
    being picked. Two DISTINCT cells still refuse — that is T41, untouched.
    Under this rule the same corpus yields 336 anchors.
    """
    address = span.get("address")
    if address and address.get("kind") == "cell":
        return (address.get("table"), address.get("row"), address.get("col"))
    places = {(c.get("table"), c.get("row"), c.get("col"))
              for c in span.get("candidates") or [] if c.get("kind") == "cell"}
    return next(iter(places)) if len(places) == 1 else None


def _smallest_cell_at(cells: list, x: float, y: float):
    """The tightest drawn cell containing a point, or None."""
    best = None
    best_area = None
    for cell in cells:
        if not (cell[0] <= x <= cell[2] and cell[1] <= y <= cell[3]):
            continue
        area = (cell[2] - cell[0]) * (cell[3] - cell[1])
        if best_area is None or area < best_area:
            best, best_area = cell, area
    return best


def text_by_drawn_cell(lines: list, cells: list, normalize) -> dict:
    """What each drawn cell actually contains, normalized. The oracle.

    A correspondence between a drawn cell and a declared cell is checkable
    whenever the declared cell has text: the page has to show that text in
    that box. This is what turns "the grid looked plausible" into something
    the render itself either confirms or refuses.
    """
    collected: dict = {}
    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        cell = _smallest_cell_at(cells, (x0 + x1) / 2.0, (y0 + y1) / 2.0)
        if cell is not None:
            collected.setdefault(cell, []).append(line["text"])
    return {cell: normalize("".join(parts))
            for cell, parts in collected.items()}


def cell_agrees(declared: dict, drawn, inside: dict, normalize) -> bool:
    """Does the render confirm that this drawn cell is that declared cell?"""
    shown = inside.get(drawn, "")
    if declared.get("classification") == "fill_target":
        # An empty seat has to be empty on the page. If the box holds text,
        # this is somebody else's box.
        return not shown
    declared_text = normalize(declared.get("text_preview") or "")
    if not declared_text:
        return True     # nothing declared, so nothing can contradict it
    if declared.get("truncated"):
        # A 30-char prefix cannot be matched, but it can still REFUTE.
        return shown.startswith(declared_text)
    return shown == declared_text


def _walk_row(cells: list, anchor_cell, declared: list, index: int,
              inside: dict, normalize) -> tuple[dict, dict]:
    """Step outward from an anchor along one drawn row band.

    The drawn cells sharing the anchor's band, left to right, are walked in
    lockstep with the declared cells of that row. Each step must be ADJACENT
    (this cell's right edge is the next one's left edge) and must AGREE with
    the page's own text. The first step that fails ends the walk in that
    direction; nothing past it is placed. That is the whole discipline — an
    empty seat is trusted only because the labelled cells on the way to it
    were verified.
    """
    band = sorted([cell for cell in cells
                   if abs(cell[1] - anchor_cell[1]) <= SEAT_BAND_TOL
                   and abs(cell[3] - anchor_cell[3]) <= SEAT_BAND_TOL],
                  key=lambda cell: cell[0])
    if anchor_cell not in band:
        return {}, {}
    start = band.index(anchor_cell)
    placed = {index: anchor_cell}
    stops: dict = {}

    def note(reason):
        stops[reason] = stops.get(reason, 0) + 1

    here, slot = start, index
    while here + 1 < len(band) and slot + 1 < len(declared):
        if abs(band[here][2] - band[here + 1][0]) > SEAT_ADJACENCY_TOL:
            note("grid_gap")
            break
        if not cell_agrees(declared[slot + 1], band[here + 1], inside,
                           normalize):
            note("cell_mismatch")
            break
        here, slot = here + 1, slot + 1
        placed[slot] = band[here]
    here, slot = start, index
    while here - 1 >= 0 and slot - 1 >= 0:
        if abs(band[here - 1][2] - band[here][0]) > SEAT_ADJACENCY_TOL:
            note("grid_gap")
            break
        if not cell_agrees(declared[slot - 1], band[here - 1], inside,
                           normalize):
            note("cell_mismatch")
            break
        here, slot = here - 1, slot - 1
        placed[slot] = band[here]
    return placed, stops


def align_drawn_grid(profile: dict, spans: list, cells: list, lines: list,
                     width: float, height: float, normalize
                     ) -> tuple[dict, dict]:
    """Drawn cells -> fill seats. ``({(table,row,col): rect}, {reason: n})``.

    Alignment is earned in three stages and abandoned the moment it is not.
    An anchor is a span that names exactly one table cell AND whose drawn cell
    carries that cell's text. From each surviving anchor the row is walked
    outward under the text gate. Where two anchors reach the same declared
    cell and disagree about which box it is, that cell is refused.
    """
    placed: dict = {}
    absences: dict = {}

    def refuse(reason, count=1):
        absences[reason] = absences.get(reason, 0) + count

    inside = text_by_drawn_cell(lines, cells, normalize)

    anchors: dict = {}
    for span in spans:
        key = sole_cell_address(span)
        if key is None:
            continue
        x0, y0, x1, y1 = span["rect"]
        cell = _smallest_cell_at(cells, (x0 + x1) / 2.0 * width,
                                 (y0 + y1) / 2.0 * height)
        if cell is not None:
            anchors.setdefault(key, cell)

    for table in profile.get("table_map") or []:
        table_index = table.get("index")
        by_row: dict = {}
        for cell in table.get("cells") or []:
            row = (cell.get("addr") or {}).get("row")
            by_row.setdefault(row, []).append(cell)
        for row_cells in by_row.values():
            row_cells.sort(key=lambda cell: (cell.get("addr") or {}).get("col")
                           if (cell.get("addr") or {}).get("col") is not None
                           else -1)

        mine = {key: cell for key, cell in anchors.items()
                if key[0] == table_index}
        fills_total = sum(1 for row_cells in by_row.values()
                          for cell in row_cells
                          if cell.get("classification") == "fill_target")
        if not mine:
            # Nothing of this table was identified here. It may simply live on
            # another page; either way this page cannot place it.
            if fills_total:
                refuse("no_anchor_on_page", fills_total)
            continue

        proposals: dict = {}
        for (_, row, col), anchor_cell in mine.items():
            declared = by_row.get(row) or []
            index = next((i for i, cell in enumerate(declared)
                          if (cell.get("addr") or {}).get("col") == col), None)
            if index is None:
                continue
            if not cell_agrees(declared[index], anchor_cell, inside, normalize):
                # The box holding this label is not the box the scan describes
                # — a sub-cell, or a neighbour. An anchor that cannot verify
                # itself cannot vouch for anything else.
                refuse("alignment_failed")
                continue
            reached, stops = _walk_row(cells, anchor_cell, declared, index,
                                       inside, normalize)
            for reason, count in stops.items():
                refuse(reason, count)
            for slot, cell in reached.items():
                proposals.setdefault((row, slot), set()).add(cell)

        reached_fills = set()
        for (row, slot), candidates in proposals.items():
            declared = by_row.get(row) or []
            cell = declared[slot]
            if cell.get("classification") != "fill_target":
                continue
            col = (cell.get("addr") or {}).get("col")
            reached_fills.add((row, col))
            if len(candidates) != 1:
                refuse("alignment_failed")
                continue
            placed[(table_index, row, col)] = next(iter(candidates))

        for row, row_cells in by_row.items():
            for cell in row_cells:
                if cell.get("classification") != "fill_target":
                    continue
                col = (cell.get("addr") or {}).get("col")
                if (row, col) not in reached_fills:
                    refuse("no_anchor_in_row")
    return placed, absences


def derive_seats(profile: dict, spans: list, drawn: list, width: float,
                 height: float, *, cells: list | None = None,
                 lines: list | None = None, normalize=None) -> tuple[list, dict]:
    """A rect for each fill seat, or nothing — never a made-up box.

    Returns ``(seats, absences)``, where ``absences`` counts by
    ``ABSENCE_REASONS`` — the Desktop already renders absence honestly, and
    now it can say WHY.

    Three derivations, best first. ``matched_text`` where the seat already has
    text that matched a span. ``cell_borders`` where the rules drawn on the
    page enclose a box that alignment tied to this seat — the only derivation
    that reaches an empty cell nowhere near a label, and the reason this
    module exists. ``interpolated`` last, from a label in the same table row.

    A seat none of the three reach is ABSENT: the Desktop falls back to tree
    editing for it, which is honest, where a guessed rectangle would put a
    text cursor somewhere the text is not.
    """
    by_cell = _cell_span_index(spans)
    page_area = max(width * height, 1.0)
    seats = []
    border_rects: dict = {}
    absences: dict = {}
    if cells and normalize is not None:
        border_rects, absences = align_drawn_grid(
            profile, spans, cells, lines or [], width, height, normalize)
    elif normalize is not None:
        fills = sum(1 for table in profile.get("table_map") or []
                    for cell in table.get("cells") or []
                    if cell.get("classification") == "fill_target")
        if fills:
            absences = {"no_drawn_grid": fills}
    for table in profile.get("table_map") or []:
        table_index = table.get("index")
        table_cells = table.get("cells") or []
        # every uniquely mapped label in this table, by row
        rows: dict = {}
        for cell in table_cells:
            addr = cell.get("addr") or {}
            key = (table_index, addr.get("row"), addr.get("col"))
            span = by_cell.get(key)
            if span is not None:
                rows.setdefault(addr.get("row"), []).append(
                    (addr.get("col"), span))
        for row in rows.values():
            row.sort(key=lambda item: (item[0] if item[0] is not None else -1))

        for cell in table_cells:
            if cell.get("classification") != "fill_target":
                continue
            addr = cell.get("addr") or {}
            row_index, col_index = addr.get("row"), addr.get("col")
            seat = {"table": table_index, "row": row_index, "col": col_index}

            own = by_cell.get((table_index, row_index, col_index))
            if own is not None:
                seat.update({"rect": own["rect"], "derivation": "matched_text",
                             "basis": {"spanIndex": own["index"]}})
                seats.append(seat)
                continue

            bordered = border_rects.get((table_index, row_index, col_index))
            if bordered is not None:
                seat.update({
                    "rect": _norm_rect(bordered, width, height),
                    "derivation": "cell_borders",
                    "basis": {"drawnCell": [round(v, 2) for v in bordered],
                              "verifiedBy": "the text the page shows in the "
                                            "cells walked to reach this one"}})
                seats.append(seat)
                continue

            neighbours = rows.get(row_index) or []
            before = [item for item in neighbours
                      if item[0] is not None and col_index is not None
                      and item[0] < col_index]
            after = [item for item in neighbours
                     if item[0] is not None and col_index is not None
                     and item[0] > col_index]
            if not before:
                # Nothing in this row anchors it. Absent beats invented.
                continue
            label_col, label_span = before[-1]
            if col_index != (label_col or 0) + 1:
                # Only the seat immediately after a label can be placed. With a
                # single label and seven seats in the row we know where the
                # FIRST one starts and nothing about the rest, and handing all
                # seven the same rectangle would be seven wrong answers wearing
                # one right one's clothes. The others are absent; the Desktop
                # edits them in the tree.
                continue
            lx0, ly0, lx1, ly1 = label_span["rect"]
            right = after[0][1]["rect"][0] if after else 1.0
            if right <= lx1:
                continue
            candidate = [round(lx1, 6), round(ly0, 6), round(right, 6),
                         round(ly1, 6)]
            basis = {"fromCell": {"table": table_index, "row": row_index,
                                  "col": label_col},
                     "fromSpanIndex": label_span["index"]}

            midpoint = (((candidate[0] + candidate[2]) / 2.0) * width,
                        ((candidate[1] + candidate[3]) / 2.0) * height)
            drawn_rect = _containing_drawn_rect(drawn, midpoint, page_area)
            if drawn_rect is not None:
                seat.update({"rect": _norm_rect(drawn_rect, width, height),
                             "derivation": "cell_borders",
                             "basis": {**basis, "snappedTo": "a rule drawn on "
                                                             "the page"}})
            else:
                seat.update({"rect": candidate, "derivation": "interpolated",
                             "basis": basis})
            seats.append(seat)
    return seats, absences


# --- the call ---------------------------------------------------------------------

def page_geometry(session, *, page: int = 0, run_id=None,
                  profile: dict | None, cache: dict | None = None) -> dict:
    """Spans, addresses and seat rects for one page — or an honest absence."""
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        raise RpcError("invalid_params", "page must be a non-negative integer",
                       page=page)

    path, kind, facts = resolve_artifact(session, run_id)
    suffix = path.suffix.lower() if path is not None else ""
    document_kind = session.meta.get("ingress", {}).get("documentKind", "opaque")
    if suffix not in RASTERIZABLE_SUFFIXES:
        if document_kind == "hwpx" or suffix in (".hwpx", ".hwp"):
            from rt_convert import prepare_capability

            prepare = prepare_capability()
            return _unavailable(
                session, "needs_conversion",
                ("geometry comes out of the rendered PDF; call "
                 "document/renderPrepare (host) to make one"
                 if prepare["state"] == "yes" else
                 "geometry comes out of the rendered PDF, and this machine "
                 "cannot make one: " + str(prepare["reason"])),
                artifactKind=kind, documentKind=document_kind, prepare=prepare)
        return _unavailable(
            session, "no_rasterizable_artifact",
            f"nothing here is a PDF (the {kind} is {suffix or 'extensionless'})",
            artifactKind=kind, documentKind=document_kind)

    if path is None or not path.is_file():
        return _unavailable(session, "artifact_missing",
                            "the artifact named by this request is not on disk",
                            artifactKind=kind)

    module = rasterizer_module()
    if module is None:
        return _unavailable(
            session, "rasterizer_missing",
            "a PDF is present but PyMuPDF is not importable, so its text "
            "positions cannot be read", artifactKind=kind, artifact=facts)

    digest = facts.get("sha256")
    cache_key = f"{digest}:{page}"
    extracted = None
    cache_hit = False
    if cache is not None and cache_key in cache:
        extracted, cache_hit = cache[cache_key], True
    if extracted is None:
        extracted = extract_page(module, path, page)
        if cache is not None:
            if len(cache) >= MAX_CACHE_ENTRIES:
                cache.pop(next(iter(cache)))
            cache[cache_key] = extracted

    width, height = extracted["widthPt"], extracted["heightPt"]
    normalize = normalizer()
    missing_profile = profile is None
    if missing_profile:
        normalize = None
    if normalize is None:
        # Positions are still real; only the mapping is missing, and saying so
        # beats inventing a second whitespace rule to keep going.
        spans = [{"index": index, "text": line["text"],
                  "rect": _norm_rect(line["bbox"], width, height),
                  "address": None, "confidence": "unmapped"}
                 for index, line in enumerate(extracted["lines"])]
        mapping = {"state": "unavailable",
                   "reason": ("this session has no form scan to map onto "
                              "\u2014 a PDF opened directly is pages, not "
                              "a form"
                              if missing_profile else
                              "pipeline/scripts/check_residue.py is not "
                              "importable, so no normalizer is available "
                              "and nothing is matched")}
        seats: list = []
        absences: dict = {}
    else:
        targets, excluded = build_targets(profile, normalize)
        spans = map_spans(extracted["lines"], targets, normalize, width, height)
        seats, absences = derive_seats(
            profile, spans, extracted["drawnRects"], width, height,
            cells=extracted.get("drawnCells"), lines=extracted["lines"],
            normalize=normalize)
        mapping = {
            "state": "ran",
            "normalizer": "pipeline/scripts/check_residue.normalize_text",
            "targets": sum(len(rows) for rows in targets.values()),
            "excluded": excluded,
            "unique": sum(1 for s in spans if s["confidence"] == "unique"),
            "ambiguous": sum(1 for s in spans if s["confidence"] == "ambiguous"),
            "unmapped": sum(1 for s in spans if s["confidence"] == "unmapped"),
        }

    return {
        "sessionId": session.id,
        "available": True,
        "source": {"kind": f"{kind}_pdf", **facts},
        "page": page,
        "pageCount": extracted["pageCount"],
        "pageSize": {"widthPt": width, "heightPt": height},
        "unit": GEOMETRY_UNIT,
        "origin": GEOMETRY_ORIGIN,
        "spanUnit": "line",
        "spans": spans,
        "seats": seats,
        "seatDerivations": {
            method: sum(1 for seat in seats if seat["derivation"] == method)
            for method in DERIVATION_METHODS
        },
        "seatAbsences": {reason: absences.get(reason, 0)
                         for reason in ABSENCE_REASONS},
        "drawnCells": len(extracted.get("drawnCells") or []),
        "mapping": mapping,
        "cache": {"hit": cache_hit, "key": cache_key},
    }
