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
        "limits": {
            "truncatedCells": ("a cell whose text_preview is truncated is "
                               "excluded from matching: a 30-character prefix "
                               "is a guess, not a match"),
            "ambiguity": "reported as candidates; never resolved by picking one",
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
        try:
            for drawing in loaded.get_drawings():
                rect = drawing.get("rect")
                if rect is None:
                    continue
                rects.append([float(rect[0]), float(rect[1]),
                              float(rect[2]), float(rect[3])])
        except Exception:  # noqa: BLE001 - drawings are a refinement, not a need
            rects = []
        return {"pageCount": int(count),
                "widthPt": round(float(box.width), 2),
                "heightPt": round(float(box.height), 2),
                "lines": lines, "drawnRects": rects}
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


def derive_seats(profile: dict, spans: list, drawn: list, width: float,
                 height: float) -> list:
    """A rect for each fill seat, or nothing — never a made-up box.

    Three derivations, best first. ``matched_text`` where the seat already has
    text that matched a span. Otherwise the seat is EMPTY, which is the case
    that matters for editing and the case with nothing to match on, so its
    horizontal extent is inferred from the labels around it in the same table
    row and then, if the page actually draws a box there, snapped to that box.
    A seat with no mapped neighbour in its row is ABSENT from the result: the
    Desktop falls back to tree editing for it, which is honest, where a guessed
    rectangle would put a text cursor somewhere the text is not.
    """
    by_cell = _cell_span_index(spans)
    page_area = max(width * height, 1.0)
    seats = []
    for table in profile.get("table_map") or []:
        table_index = table.get("index")
        cells = table.get("cells") or []
        # every uniquely mapped label in this table, by row
        rows: dict = {}
        for cell in cells:
            addr = cell.get("addr") or {}
            key = (table_index, addr.get("row"), addr.get("col"))
            span = by_cell.get(key)
            if span is not None:
                rows.setdefault(addr.get("row"), []).append(
                    (addr.get("col"), span))
        for row in rows.values():
            row.sort(key=lambda item: (item[0] if item[0] is not None else -1))

        for cell in cells:
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
    return seats


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
    else:
        targets, excluded = build_targets(profile, normalize)
        spans = map_spans(extracted["lines"], targets, normalize, width, height)
        seats = derive_seats(profile, spans, extracted["drawnRects"],
                             width, height)
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
        "mapping": mapping,
        "cache": {"hit": cache_hit, "key": cache_key},
    }
