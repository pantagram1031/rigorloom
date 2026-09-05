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


class TracingRenderer(own_render.OwnRenderer):
    """``OwnRenderer`` that stamps each line box with who drew it.

    Both line-drawing entry points are wrapped so the tag is right whichever
    policy is in force, and ``_draw_line`` claims only boxes that are not
    tagged yet: a paragraph holding an inline table draws its cells' lines
    from INSIDE its own ``_draw_line`` call, and the outer call must not
    relabel them as its own.
    """

    _tracing_para = None

    def _render_cached_lines(self, draw, para, *args, **kwargs):
        outer, self._tracing_para = self._tracing_para, para
        try:
            return super()._render_cached_lines(draw, para, *args, **kwargs)
        finally:
            self._tracing_para = outer

    def _render_computed_lines(self, draw, para, *args, **kwargs):
        outer, self._tracing_para = self._tracing_para, para
        try:
            return super()._render_computed_lines(draw, para, *args, **kwargs)
        finally:
            self._tracing_para = outer

    def _draw_line(self, draw, items, *args, **kwargs):
        before = len(self.line_boxes)
        result = super()._draw_line(draw, items, *args, **kwargs)
        fresh = self.line_boxes[before:]
        if fresh:
            para = self._tracing_para
            address = (self.paragraph_index.get(id(para.el))
                       if para is not None else None)
            text = "".join(seg.text for kind, seg in items if kind == "text")
            faces = self._line_faces(items)
            for record in fresh:
                record.setdefault("address", address)
                record.setdefault("text", text)
                record.setdefault("faces", faces)
        return result

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


def divergence_report(hwpx_path, dpi=own_render.DEFAULT_DPI,
                      y_tol=DEFAULT_Y_TOL, include_text=True,
                      repo_root=None, attribution_tol=DEFAULT_ATTRIBUTION_TOL):
    """Classify every line of one document across the two layout policies."""
    hwpx_path = Path(hwpx_path)
    cache = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_CACHE, dpi=dpi,
                        repo_root=repo_root)
    computed = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_COMPUTED,
                           dpi=dpi, repo_root=repo_root)
    walk = walk_paragraphs(by_paragraph(cache["line_boxes"]),
                           by_paragraph(computed["line_boxes"]),
                           y_tol=y_tol, include_text=include_text,
                           attribution_tol=attribution_tol)

    report = {
        "tool": "layout_divergence",
        "source": hwpx_path.name,
        "dpi": dpi,
        "y_tolerance_px": y_tol,
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
    return (f"{stem}: paragraphs agree {paras['agree']} / A {paras['A']} / "
            f"B {paras['B']} / C {paras['C']} (A&B {paras['A_and_B']}); "
            f"lines agree {lines['agree']} / A {lines['A']} / B {lines['B']} "
            f"/ C {lines['C']}{dominant}{split_text}{iou_text}")


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
            f"{'A&B':>5} {'B_inh':>6} {'B_own':>6} {'A_sub':>6} {'A_ins':>6}")
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
        out.append(f"{name:<{width}}  {paras['agree']:>6} {paras['A']:>5} "
                   f"{paras['B']:>5} {paras['C']:>5} {paras['A_and_B']:>5} "
                   f"{cells['B_inherited']:>6} {cells['B_own']:>6} "
                   f"{cells['A_substituted']:>6} {cells['A_installed']:>6}")
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
                               attribution_tol=args.attribution_tol)
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
