#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charpr_script.py — the ONE definition of the T30 script/scale/offset trap.

T30 (clean-room cross-model run, PPS 협업제품명 cell): a fill inherited a
``charPr`` identical to body text except for a trailing ``<hh:supscript/>``.
Nominal ``height`` never changed, so every height/colour-based offline proof
passed while Hancom rendered the value at ~6.35pt raised off the baseline.

Two tools now need the SAME comparison:

  * ``engine/scripts/form_inspect.py`` — PRE-flight. Flags a fill target whose
    run already carries the anomaly, so ``preedit fill-cells`` can be told the
    right ``charPr`` id BEFORE the fill (T30 becomes preventable).
  * ``pipeline/scripts/visual_verify.py`` — POST-flight. HARDs on a
    fill-modified run whose charPr differs from the body baseline (T30 stays
    detectable).

They must not be able to disagree, so the profile extraction, the signature,
the baseline choice and the difference test all live here and are imported by
both. This module owns NO policy — it never decides that a difference is a
refusal; that is the caller's contract.

Import direction: ``engine/scripts`` is self-contained (nothing here imports
``pipeline/``), and ``visual_verify`` already puts ``engine/scripts`` on
``sys.path``. So this module can be shared without any import cycle.
"""
from __future__ import annotations

import bisect
import re
import xml.etree.ElementTree as ET

#: OWPML ``hh:charPr`` children that move or resize a run WITHOUT changing its
#: nominal ``height``. ``supscript``/``subscript`` are presence-only flags;
#: ``ratio``/``relSz``/``offset`` carry per-language percentages/offsets. A run
#: that inherits any of these differently from body text renders at a
#: different size or baseline while every height-based proof still passes.
SCRIPT_FLAG_TAGS = ("supscript", "subscript")
SCRIPT_SCALE_TAGS = ("ratio", "relSz", "offset")

#: Every key a script signature carries, in a stable order.
SIGNATURE_KEYS = (*SCRIPT_FLAG_TAGS, *SCRIPT_SCALE_TAGS)

#: Hancom renders a supscript/subscript run at roughly this fraction of the
#: nominal height. Reported as evidence, never used as a threshold.
SCRIPT_RENDER_FACTOR = 0.635

_NS = r"[A-Za-z0-9]+"
#: A self-closing element (``<hp:run .../>``, ``<hp:t/>``) owns no body text.
#: ``[^>]*?`` (lazy) followed by the ``/>`` | ``>...</ns:tag>`` alternation
#: recognises the self-close as a complete match with no body, instead of
#: letting a naive ``[^>]*>(.*?)</ns:tag>`` swallow the ``/>`` as ordinary
#: attribute text and keep scanning into the FOLLOWING sibling element for
#: the closing tag (T37 — see docs/trouble-table.md).
#:
#: The namespace prefix stays NON-capturing on purpose. Binding the closing
#: tag with a ``\1`` backreference would be marginally stricter, but it costs
#: a group, and a module-level pattern's group COUNT is part of its public
#: interface: ``findall`` silently changes shape and every ``.group(n)`` in
#: every caller shifts by one. That is how the first attempt at this fix
#: crashed ``check_gongmun`` and silently fed ``style_diff`` an attribute
#: string where it wanted a body. Arity is preserved here for that reason;
#: a mismatched ``<hp:t>…</hh:t>`` is not a shape HWPX produces.
_RUN_RE = re.compile(
    r"<" + _NS + r":run\b[^>]*\bcharPrIDRef=\"(\d+)\"[^>]*?"
    r"(?:/>|>(.*?)</" + _NS + r":run>)", re.S)
_RUN_TEXT_RE = re.compile(
    r"<" + _NS + r":t\b[^>]*?(?:/>|>(.*?)</" + _NS + r":t>)", re.S)


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def norm(text: str) -> str:
    """Whitespace-free comparison form (same convention as visual_verify)."""
    return re.sub(r"\s+", "", text or "")


def profiles_from_header(header_xml) -> dict:
    """``charPr id -> script/scale/offset profile`` from a header.xml body.

    ``header_xml`` is the raw ``Contents/header.xml`` bytes or text. Returns
    ``{}`` on anything unparseable — a caller that cannot read the header must
    say so out loud rather than treat the document as clean.
    """
    try:
        root = ET.fromstring(header_xml)
    except (ET.ParseError, UnicodeDecodeError, TypeError, ValueError):
        return {}
    profiles = {}
    for node in root.iter():
        if localname(node.tag) != "charPr":
            continue
        cid = node.get("id")
        if cid is None:
            continue
        profile = {tag: False for tag in SCRIPT_FLAG_TAGS}
        for tag in SCRIPT_SCALE_TAGS:
            profile[tag] = None
        height = node.get("height")
        profile["height_pt"] = (
            int(height) / 100.0 if height and height.isdigit() else None)
        for child in node:
            name = localname(child.tag)
            if name in SCRIPT_FLAG_TAGS:
                profile[name] = True
            elif name in SCRIPT_SCALE_TAGS:
                profile[name] = {k: v for k, v in sorted(child.attrib.items())}
        profiles[cid] = profile
    return profiles


def iter_runs(section_xml: str):
    """``[(charPrIDRef, text)]`` for every run in ``section_xml`` that carries
    visible text, in document order. Text-less runs (the empty-cell
    self-closing run a fill writes into) are not body text and are excluded —
    weighting the baseline by them would let a form's blanks outvote its prose.

    Delegates to ``iter_seat_runs`` and drops the seat, so the seat-aware and
    seat-blind views of a document can never report different runs, different
    text or a different order.
    """
    return [(cid, text) for _, cid, text in iter_seat_runs(section_xml)]


def signature(profile) -> dict:
    """The comparable part of a profile (``height_pt`` is NOT comparable — the
    whole point of T30 is that the nominal height is identical)."""
    return {key: (profile or {}).get(key) for key in SIGNATURE_KEYS}


def differing_keys(profile, baseline_profile) -> list:
    """Sorted signature keys on which ``profile`` departs from the baseline."""
    own, base = signature(profile), signature(baseline_profile)
    return sorted(key for key in SIGNATURE_KEYS if own[key] != base[key])


def body_baseline_id(weights):
    """The document's own body-baseline charPr id, or None.

    ``weights`` maps charPr id -> body-text weight (character count). The
    heaviest id wins; ties break on the smallest id string, which is what
    visual_verify has always done — the tie-break is arbitrary but it must be
    the SAME arbitrary choice in both tools.
    """
    if not weights:
        return None
    top = max(weights.values())
    return min(cid for cid, weight in weights.items() if weight == top)


def rendered_pt_estimate(profile):
    """~pt Hancom draws a script run at, or None when no script flag is set."""
    if not profile:
        return None
    height = profile.get("height_pt")
    if not height:
        return None
    if not (profile.get("supscript") or profile.get("subscript")):
        return None
    return round(height * SCRIPT_RENDER_FACTOR, 2)


# --------------------------------------------------------------------------
# SEATS — the same field in two documents (T40)
# --------------------------------------------------------------------------
#
# The document-wide body baseline above answers "does this run differ from the
# prose around it". On a mostly-empty FORM that is the wrong question: the
# heaviest charPr is boilerplate (the 기안문 별지's 비고 fine print), so every
# real field differs from it and the comparison inverts.
#
# The right question is "did the FILL introduce this signature, or was the
# printed form always like that", and answering it needs the same field
# located in TWO documents — the blank form and the artifact. That is a seat.
#
# THE SEAT-MATCHING RULE, and why it is not text:
#
#   A seat is the run's STRUCTURAL address — the table cell it sits in,
#   written as ``(<section member>, "t<table>/<row>,<col>", ...)``, outermost
#   enclosing cell first so a nested table is addressed too.
#
# Text cannot be the key. An ``--at-cell-append`` fill deliberately keeps the
# printed label and puts the value after it, so the SAME seat reads "수신" in
# the blank and "수신 국가유산청장" in the artifact (T31); a ``--at-cell``
# fill replaces the seat text outright and leaves nothing shared at all. The
# structural address survives both, because a fill writes text into existing
# runs and never touches the table geometry — ``form_inspect`` on a correct
# fill reports every ``cellAddr``/span/width/height byte-identical to the
# blank. Table ordinal is the count of ``tbl`` opens in that section in
# document order, which is stable for the same reason.
#
# ``cellAddr`` is the primary key because it is what the fill CLIs address
# (``--cell ROW,COL``, ``--at-cell ROW,COL``) — the same coordinate the
# operator typed. A ``tc`` with no ``cellAddr`` child falls back to its
# ordinal within its table so hand-built and minimal documents still address;
# the choice is recorded in the seat string either way, and both documents are
# read by this one function so they cannot disagree about which form was used.
#
# A run outside every table gets the empty seat: unaddressed, NOT "seat 0".
# Prose paragraphs shift when a fill adds one, so there is no honest identity
# to offer, and a caller must treat the empty seat as "no baseline available"
# rather than as a match.

#: ``tbl``/``tc`` boundaries and the ``cellAddr`` that names a cell. Kept as a
#: separate scan (rather than a full parse) so seat text stays byte-identical
#: to what ``iter_runs`` reports: an ElementTree walk would silently unescape
#: entities and the two run lists would stop lining up. Arity is part of the
#: interface (T37) — four groups, in this order.
_SEAT_EVENT_RE = re.compile(
    r"<(/?)" + _NS + r":(tbl|tc|cellAddr)\b([^>]*?)(/?)>", re.S)
_SEAT_ADDR_RE = re.compile(r'\b(colAddr|rowAddr)="(\d+)"')


def _seat_cells(section_xml: str):
    """``[{start, end, label}]`` — every ``hp:tc`` span and its seat label.

    TWO passes are required, not one: OWPML puts ``<hp:cellAddr>`` at the END
    of ``<hp:tc>``, *after* the ``<hp:subList>`` that holds the paragraphs. A
    single forward scan therefore reaches every run in a cell BEFORE it learns
    that cell's address, and would label them all by fallback ordinal. So the
    spans are collected first and the labels resolved against the whole span.
    """
    cells, stack, tables = [], [], 0
    for match in _SEAT_EVENT_RE.finditer(section_xml):
        closing, tag, attrs, selfclose = match.groups()
        if tag == "cellAddr":
            addr = dict(_SEAT_ADDR_RE.findall(attrs))
            if "rowAddr" in addr and "colAddr" in addr:
                for frame in reversed(stack):
                    if frame["kind"] == "tc":
                        frame["addr"] = "%s,%s" % (addr["rowAddr"],
                                                   addr["colAddr"])
                        break
        elif closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index]["kind"] != tag:
                    continue
                for frame in stack[index:]:
                    if frame["kind"] == "tc":
                        frame["end"] = match.start()
                del stack[index:]
                break
        elif selfclose:
            continue            # an empty <hp:tc/> holds no runs
        elif tag == "tbl":
            tables += 1
            stack.append({"kind": "tbl", "table": tables, "cells": 0})
        else:
            table = index = 0
            for frame in reversed(stack):
                if frame["kind"] == "tbl":
                    frame["cells"] += 1
                    table, index = frame["table"], frame["cells"]
                    break
            frame = {"kind": "tc", "table": table, "index": index,
                     "addr": None, "start": match.end(), "end": len(section_xml)}
            stack.append(frame)
            cells.append(frame)
    return [{"start": cell["start"], "end": cell["end"],
             "label": "t%d/%s" % (cell["table"],
                                  cell["addr"] or "#%d" % cell["index"])}
            for cell in cells]


def _seat_timeline(section_xml: str):
    """``[(offset, seat)]`` — the seat in effect from that byte offset on.

    Sorted by offset, so a run's seat is one bisect away. Cells are properly
    nested, so replaying their spans as open/close events (closes first at a
    shared offset) reproduces the enclosing stack, outermost cell first.
    """
    cells = _seat_cells(section_xml)
    events = sorted([(cell["end"], 0, index) for index, cell in enumerate(cells)]
                    + [(cell["start"], 1, index)
                       for index, cell in enumerate(cells)])
    timeline, stack = [(0, ())], []
    for offset, opening, index in events:
        if opening:
            stack.append(index)
        elif index in stack:
            del stack[stack.index(index):]
        timeline.append((offset, tuple(cells[i]["label"] for i in stack)))
    return timeline


def iter_seat_runs(section_xml: str, member: str = ""):
    """``[(seat, charPrIDRef, text)]`` — ``iter_runs`` plus each run's seat.

    Same runs, same order and the same text as ``iter_runs`` (it delegates
    here), so a caller may weight a document-wide baseline and look up a seat
    from ONE traversal. ``seat`` is ``()`` for a run outside every table cell.
    """
    timeline = _seat_timeline(section_xml)
    offsets = [offset for offset, _ in timeline]
    out = []
    for match in _RUN_RE.finditer(section_xml):
        body = match.group(2)
        if not body:
            # Self-closing run: no body, so no text (see iter_runs).
            continue
        text = "".join(_RUN_TEXT_RE.findall(body))
        text = re.sub(r"<[^>]+>", "", text)
        if not text.strip():
            continue
        seat = timeline[bisect.bisect_right(offsets, match.start()) - 1][1]
        out.append(((member, *seat) if seat else (), match.group(1), text))
    return out


def iter_seat_empty_runs(section_xml: str, member: str = ""):
    """``[(seat, charPrIDRef)]`` for text-less runs inside table cells.

    Empty runs are excluded from :func:`iter_seat_runs` on purpose: counting
    reserved form slots as prose would corrupt the document-body baseline.
    An address-keyed fill still needs a separate, non-weighted view of those
    slots to prove which typography the blank form reserved for that exact
    cell (T42). Self-closing, empty ``hp:t`` and empty paired runs all count;
    a run outside a table does not have a stable seat and is omitted.
    """
    timeline = _seat_timeline(section_xml)
    offsets = [offset for offset, _ in timeline]
    out = []
    for match in _RUN_RE.finditer(section_xml):
        body = match.group(2)
        text = "" if not body else "".join(_RUN_TEXT_RE.findall(body))
        text = re.sub(r"<[^>]+>", "", text)
        if text.strip():
            continue
        seat = timeline[bisect.bisect_right(offsets, match.start()) - 1][1]
        if seat:
            out.append(((member, *seat), match.group(1)))
    return out


def seat_addresses(section_xml: str, member: str = "") -> set:
    """Every cell seat in ``section_xml``, whether it carries text or not.

    ``iter_seat_runs`` only knows seats that hold text, so on its own it cannot
    tell "this seat is not in the blank form" from "this seat IS in the blank
    form and is a genuinely empty run". Those are different answers and a
    caller must be able to say which — the second one is the T30 shape.
    """
    return {(member, *seat) for _offset, seat in _seat_timeline(section_xml)
            if seat}


def seat_label_runs(seat_runs, seat, label):
    """Runs in ``seat`` that match the fill-map key ``label``.

    The blank-form baseline must be the run the fill consumed, not whichever
    unrelated sibling carries the most text in the same cell. Prefer an exact
    whitespace-normalised match; only when none exists admit a containing run
    (the fill-map key may intentionally be a unique substring). The caller
    must refuse ambiguity when the returned runs do not share one charPr id.
    """
    key = norm(str(label))
    if not seat or not key:
        return []
    in_seat = [(cid, text) for run_seat, cid, text in seat_runs
               if run_seat == seat]
    exact = [(cid, text) for cid, text in in_seat if norm(text) == key]
    if exact:
        return exact
    return [(cid, text) for cid, text in in_seat if key in norm(text)]
