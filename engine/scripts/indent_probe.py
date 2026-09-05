#!/usr/bin/env python3
"""Where does Hancom start the first line of a paragraph that declares an indent?

``hh:margin`` gives a paragraph a ``left``, a ``right`` and an ``intent``.
OWPML calls ``intent`` the first-line indent and the HWP 5.0 paragraph-shape
record stores the same signed quantity: positive is 들여쓰기 (the first line
starts further in), negative is 내어쓰기 (a hanging indent, and the textbook
reading is that the FIRST line starts at ``left + intent`` while every
continuation line starts at ``left``).

``_line_box`` implements ``max(0, left + intent)`` on line 0 and ``left`` on
every other line.  #268 measured three readings of a negative ``intent``
across all 3214 cached line boxes and none of them was exact -- the clamped
one scores 2860, "a negative intent moves nothing" 2895, the textbook hanging
indent 2710 -- and #277 found the same disagreement again from the table
side, as five cells whose cached ``horzpos`` sits at the paragraph's
``margin_left`` while our clamp puts it at 0.

Neither run fitted the question directly.  This one does: for every cached
first line whose paragraph declares ``intent != 0``, what IS ``horzpos`` as a
function of ``left`` and ``intent``?

WHAT IS RECORDED
----------------
For every ``hp:p`` carrying an ``hp:linesegarray``, read straight out of the
file (no raster, no track solve, so nothing here can be wrong in the way the
column is wrong):

* the paragraph's ``hh:margin`` ``left`` / ``right`` / ``intent``, through
  ``own_render.parse_header`` so the ``hh:switch`` branch and its unit halving
  are resolved exactly as the renderer resolves them,
* the first cached line's ``horzpos`` and ``horzsize``, and the second's
  ``horzpos`` where the paragraph has one,
* the container -- top-level, or the enclosing ``hp:tc`` with its declared
  ``cellSz@width`` and the inset ``cell_inset`` resolves for it,
* ``hh:align@horizontal``, the ``hp:heading`` type and level of the
  paragraph's ``paraPr``, whether the paragraph carries an ``hp:tab``, and
  whether it declares a ``tabPrIDRef``.

THE FIT
-------
Every candidate is scored as an exact integer match against the cache, over
the whole corpus and per form, with the first few counter-examples printed
rather than summarised away.  The first-line candidates are the readings the
question names: ours, the unclamped one, the two clamp floors, the hanging
reading, the "moves nothing" reading, and the unit/sign variants (``intent``
halved, doubled, taken absolute).  The second line gets its own, smaller set.

``horzsize`` is asked the same question from the other side: does a negative
``intent`` WIDEN the first line, i.e. does the first line's right edge equal
the second line's?  A paragraph whose lines all share one right edge says the
indent moves the left edge only.

Usage::

    python engine/scripts/indent_probe.py FORM.hwpx
    python engine/scripts/indent_probe.py --corpus
    python engine/scripts/indent_probe.py --corpus --pdf
    python engine/scripts/indent_probe.py --corpus --json out.json --no-text

THE CACHE IS NOT THE ONLY ORACLE
--------------------------------
``horzpos`` is a saved LINE BOX, and a box that ignores the indent is not by
itself proof that the drawn TEXT ignores it: Hancom could be seating the box
at the margin and offsetting the glyphs inside it.  ``--pdf`` asks the
reference render directly.  For every top-level ``LEFT``/``JUSTIFY``
paragraph whose text can be located in the exported PDF -- located by the
same whole-line text match ``lineseg_vs_pdf`` uses, so the two scripts cannot
disagree about which PDF lines a paragraph owns -- it compares the first
drawn line's ``x0`` against ``body_left + left`` and against
``body_left + max(0, left + intent)``.  ``CENTER`` and ``RIGHT`` paragraphs
are excluded because their text start is a function of the text width and
says nothing about the box.

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout_divergence  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

RULE_QUESTION = (
    "for every cached first line whose paragraph declares a non-zero "
    "hh:intent, what is hp:lineseg@horzpos as a function of the paragraph's "
    "hh:margin left and intent?")

#: How many counter-examples a candidate prints before it is cut off.  A
#: candidate that fails is more useful as three concrete lines than as a
#: number, and more than a few lines is a table nobody reads.
MAX_COUNTEREXAMPLES = 4


# --------------------------------------------------------------------------
# The candidates
# --------------------------------------------------------------------------
# Each takes (left, intent) in HWPUNIT and returns the predicted horzpos of
# the line.  Named for what they SAY, not for who implements them, so a
# reading that turns out to be right is not called "ours" forever after.

def _first_line_candidates():
    return {
        # What _line_box does today.
        "max(0, left+intent)": lambda l, i: max(0, l + i),
        # The same arithmetic with no floor at all -- a negative result would
        # put the first line left of the column, which is what a hanging
        # indent bigger than the margin means if nothing clamps it.
        "left+intent": lambda l, i: l + i,
        # The floor at the left margin rather than at zero: an intent may
        # pull the first line in but never out past the paragraph's own
        # left margin.
        "max(left+intent, left)": lambda l, i: max(l + i, l),
        # ... which is the same statement as this one, written the way the
        # attribute reads: only a POSITIVE intent moves the first line.
        "left+max(intent,0)": lambda l, i: l + max(i, 0),
        # The intent never moves any line box.
        "left": lambda l, i: l,
        # Unit readings.  parse_header already halves a `default`-branch
        # length; these ask whether intent alone takes a different scale.
        "max(0, left+intent/2)": lambda l, i: max(0, l + int(round(i / 2))),
        "max(0, left+2*intent)": lambda l, i: max(0, l + 2 * i),
        # Sign readings: intent stored as a magnitude, or relative to left.
        "max(0, left+abs(intent))": lambda l, i: max(0, l + abs(i)),
        "max(0, intent)": lambda l, i: max(0, i),
        # The floor is on the intent, not on the sum: a negative intent is
        # dropped and a positive one applies.  (Distinct from
        # left+max(intent,0) only when left itself is negative, which the
        # corpus may or may not contain -- scored so the report can say.)
        "max(0, left)+max(0, intent)": lambda l, i: max(0, l) + max(0, i),
    }


def _second_line_candidates():
    return {
        "left": lambda l, i: l,
        "left+max(intent,0)": lambda l, i: l + max(i, 0),
        "max(0, left+intent)": lambda l, i: max(0, l + i),
        "max(0, left)": lambda l, i: max(0, l),
        # The textbook hanging indent puts the CONTINUATION lines in by the
        # magnitude of a negative intent.
        "left+abs(min(intent,0))": lambda l, i: l + abs(min(i, 0)),
    }


# --------------------------------------------------------------------------
# Reading the file
# --------------------------------------------------------------------------

def _para_pr_extras(hwpx_path):
    """``{paraPr id: {heading/tab attributes}}`` off the header.

    ``own_render.parse_header`` keeps the tab-definition id but no heading or
    bullet information -- this tier draws neither -- so a probe that wants to
    rule a bullet out has to read the attribute rather than report the
    absence of a field nothing ever filled in.
    """
    out = {}
    with zipfile.ZipFile(hwpx_path) as archive:
        name = next((n for n in archive.namelist()
                     if n.endswith("header.xml")), None)
        if name is None:
            return out
        root = ET.fromstring(archive.read(name))
    for pp in root.iter():
        if own_render._local(pp.tag) != "paraPr":
            continue
        head = own_render._kid(pp, "heading")
        out[pp.get("id")] = {
            "heading_type": head.get("type") if head is not None else None,
            "heading_level": head.get("level") if head is not None else None,
            "heading_idref": head.get("idRef") if head is not None else None,
        }
    return out


def _containers(sections):
    """``{id(hp:p): container record}`` for every paragraph in the document.

    The walk carries the nearest enclosing ``hp:tc`` and its table, so a
    paragraph inside a table nested in a cell is attributed to the INNER
    cell.  A paragraph with no enclosing cell is top-level -- which here
    means body, header, footer or note body alike: none of them is a cell,
    and the distinction does not enter the first-line question.
    """
    out = {}
    for root in sections:
        stack = [(root, None, None)]
        while stack:
            el, tc, tbl = stack.pop()
            name = own_render._local(el.tag)
            if name == "tbl":
                tbl = el
            elif name == "tc":
                tc = el
            elif name == "p":
                out[id(el)] = {"tc": tc, "tbl": tbl}
            for kid in el:
                stack.append((kid, tc, tbl))
    return out


def probe_form(hwpx_path):
    """Every cached first line of one form, with its paragraph's margins."""
    renderer = own_render.OwnRenderer(hwpx_path)
    extras = _para_pr_extras(hwpx_path)
    containers = _containers(renderer.sections)

    lines = []
    for el, index in sorted(
            ((el, renderer.paragraph_index[id(el)])
             for section in renderer.sections
             for el in section.iter()
             if own_render._local(el.tag) == "p"),
            key=lambda pair: pair[1]):
        para = own_render.Paragraph(el, renderer.defs["para_pr"])
        if not para.linesegs:
            continue
        pr = para.para_pr
        left = pr.get("margin_left", 0)
        right = pr.get("margin_right", 0)
        intent = pr.get("indent", 0)
        segs = para.linesegs

        held = containers.get(id(el)) or {"tc": None, "tbl": None}
        tc, tbl = held["tc"], held["tbl"]
        if tc is not None:
            size = own_render._kid(tc, "cellSz")
            inset = own_render.cell_inset(tc, tbl)
            container = {
                "kind": "cell",
                "declared_width": (own_render._iattr(size, "width")
                                   if size is not None else None),
                "inset_left": inset["left"],
                "inset_right": inset["right"],
                "has_margin": tc.get("hasMargin"),
            }
        else:
            container = {"kind": "top", "declared_width": None,
                         "inset_left": None, "inset_right": None,
                         "has_margin": None}

        para_pr_id = el.get("paraPrIDRef")
        record = {
            "paragraph": index,
            "para_pr": para_pr_id,
            "left": left,
            "right": right,
            "intent": intent,
            "align": para.align,
            "tabs": para.tabs,
            "tab_pr": pr.get("tab_pr"),
            "lines": len(segs),
            "horzpos0": own_render._iattr(segs[0], "horzpos"),
            "horzsize0": own_render._iattr(segs[0], "horzsize"),
            "horzpos1": (own_render._iattr(segs[1], "horzpos")
                         if len(segs) > 1 else None),
            "horzsize1": (own_render._iattr(segs[1], "horzsize")
                          if len(segs) > 1 else None),
            "chars": len(para.chars),
            "objects": len(para.objects),
            "container": container,
            # Every cached line, so the claim can be made about all 3214 of
            # them rather than about the first two of each paragraph.
            "seg_horzpos": [own_render._iattr(s, "horzpos") for s in segs],
            "seg_horzsize": [own_render._iattr(s, "horzsize") for s in segs],
        }
        record.update(extras.get(para_pr_id or "") or {})
        lines.append(record)
    return lines


# --------------------------------------------------------------------------
# The second oracle: where the reference PDF draws the first line
# --------------------------------------------------------------------------
#: How far a PDF text line's ``x0`` may sit from a prediction and still count
#: as that prediction, in HWPUNIT.  50 is half a point -- a glyph's own left
#: side bearing is inside it and no indent on this corpus is within an order
#: of magnitude of it (the smallest non-zero ``intent`` is 100).
PDF_TOLERANCE_HWP = 50


def probe_pdf(hwpx_path, pdf_path):
    """First-drawn-line ``x0`` against the two readings, per top-level para.

    Only ``LEFT`` and ``JUSTIFY`` paragraphs are asked: a centred or
    right-aligned line starts where its own width puts it, so its ``x0``
    carries no information about the line box.  A paragraph whose text the
    matcher cannot find in the PDF is counted, not guessed at.
    """
    renderer = own_render.OwnRenderer(hwpx_path)
    pdf = lineseg_vs_pdf.PdfLines.read(pdf_path)
    cursor = 0
    rows = []
    unmatched = 0
    unknown = {}
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        body_left = renderer.page_geometry()["body_left"]
        for order, el in enumerate(
                own_render._kids(renderer.sections[section], "p")):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = lineseg_vs_pdf.character_cells(para, unknown)
            if lineseg_vs_pdf.skip_reason(para, cells) is not None:
                continue
            target = lineseg_vs_pdf.normalise(
                lineseg_vs_pdf.paragraph_text(cells))
            hit = pdf.find_run(target, cursor)
            if hit is None:
                unmatched += 1
                continue
            lo, hi, _relaxed, out_of_order = hit
            if not out_of_order:
                cursor = hi
            pr = para.para_pr
            if (pr.get("align", "LEFT") or "LEFT").upper() not in (
                    "LEFT", "JUSTIFY"):
                continue
            left = pr.get("margin_left", 0)
            intent = pr.get("indent", 0)
            merged = lineseg_vs_pdf.merge_visual_lines(pdf.lines[lo:hi])
            drawn = merged[0]["x0_hwp"] - body_left
            second = (merged[1]["x0_hwp"] - body_left
                      if len(merged) > 1 else None)
            rows.append({
                "form": None,
                "paragraph": order,
                "left": left,
                "intent": intent,
                "align": pr.get("align"),
                "drawn_lines": len(merged),
                "drawn_x0": int(round(drawn)),
                "d_left": int(round(drawn - left)),
                "d_left_plus_intent": int(round(drawn - max(0, left + intent))),
                "drawn_x0_second": (None if second is None
                                    else int(round(second))),
                "d_second_left": (None if second is None
                                  else int(round(second - left))),
                "d_second_hanging": (
                    None if second is None
                    else int(round(second - (left + abs(min(intent, 0)))))),
            })
    return rows, unmatched


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def analyse_pdf(rows, unmatched):
    """How often each reading lands the first drawn line, within tolerance."""
    def _tally(subset):
        at_left = sum(1 for r in subset
                      if abs(r["d_left"]) <= PDF_TOLERANCE_HWP)
        at_sum = sum(1 for r in subset
                     if abs(r["d_left_plus_intent"]) <= PDF_TOLERANCE_HWP)
        return {"total": len(subset), "at_left": at_left,
                "at_left_plus_intent": at_sum,
                "d_left_within_1pt": sum(
                    1 for r in subset if abs(r["d_left"]) <= 100),
                "d_left_median": _median([r["d_left"] for r in subset]),
                "d_left_plus_intent_median": _median(
                    [r["d_left_plus_intent"] for r in subset])}

    with_intent = [r for r in rows if r["intent"] != 0]
    # The only paragraphs whose drawn x0 can tell the two readings apart are
    # the ones where the two readings differ at all: a negative intent needs
    # a non-zero left to separate `left` from `max(0, left + intent)`, and a
    # positive intent separates them by its own size.
    discriminating = [r for r in with_intent
                      if r["left"] != max(0, r["left"] + r["intent"])]
    # Where the second drawn line goes -- the textbook hanging indent says
    # `left + |intent|`, this cache's line boxes say `left`.
    second = [r for r in with_intent
              if r["intent"] < 0 and r["drawn_x0_second"] is not None]
    return {
        "tolerance_hwp": PDF_TOLERANCE_HWP,
        "unmatched_paragraphs": unmatched,
        "all": _tally(rows),
        "intent_zero": _tally([r for r in rows if r["intent"] == 0]),
        "intent_nonzero": _tally(with_intent),
        "intent_negative": _tally([r for r in with_intent if r["intent"] < 0]),
        "intent_positive": _tally([r for r in with_intent if r["intent"] > 0]),
        "discriminating": _tally(discriminating),
        "second_line": {
            "total": len(second),
            "at_left": sum(1 for r in second
                           if abs(r["d_second_left"]) <= PDF_TOLERANCE_HWP),
            "at_left_plus_abs_intent": sum(
                1 for r in second
                if abs(r["d_second_hanging"]) <= PDF_TOLERANCE_HWP),
        },
        "discriminating_rows": [
            {k: r[k] for k in ("form", "paragraph", "left", "intent",
                               "drawn_x0", "d_left", "d_left_plus_intent")}
            for r in discriminating],
        "examples": [
            {k: r[k] for k in ("form", "paragraph", "left", "intent",
                               "drawn_x0", "d_left", "d_left_plus_intent")}
            for r in with_intent[:12]],
        "meaning": (
            "drawn_x0 is the first PDF text line's x0 measured from the "
            "section's body_left, in HWPUNIT.  at_left counts the "
            "paragraphs it puts within tolerance of the paragraph's own "
            "hh:margin left; at_left_plus_intent counts the ones it puts at "
            "max(0, left + intent).  The two differ only where intent != 0."),
    }


# --------------------------------------------------------------------------
# The fit
# --------------------------------------------------------------------------

def _score(records, candidates, observed_key, predict_from):
    """``{name: {exact, total, misses[]}}`` for one population."""
    out = {}
    for name, fn in candidates.items():
        exact = 0
        misses = []
        for rec in records:
            observed = rec[observed_key]
            if observed is None:
                continue
            predicted = fn(*predict_from(rec))
            if predicted == observed:
                exact += 1
            elif len(misses) < MAX_COUNTEREXAMPLES:
                misses.append({
                    "form": rec.get("form"),
                    "paragraph": rec["paragraph"],
                    "left": rec["left"],
                    "intent": rec["intent"],
                    "observed": observed,
                    "predicted": predicted,
                })
        out[name] = {
            "exact": exact,
            "total": sum(1 for r in records if r[observed_key] is not None),
            "counterexamples": misses,
        }
    return out


def _population(records, predicate):
    return [r for r in records if predicate(r)]


def analyse(all_records, labels):
    """The whole fit: candidates x populations, corpus-wide and per form."""
    with_intent = _population(all_records, lambda r: r["intent"] != 0)
    negative = _population(all_records, lambda r: r["intent"] < 0)
    positive = _population(all_records, lambda r: r["intent"] > 0)

    first = _first_line_candidates()
    second = _second_line_candidates()
    key = (lambda r: (r["left"], r["intent"]))

    report = {
        "question": RULE_QUESTION,
        "counts": {
            "paragraphs_with_cache": len(all_records),
            "lines_cached": sum(r["lines"] for r in all_records),
            "intent_nonzero": len(with_intent),
            "intent_negative": len(negative),
            "intent_positive": len(positive),
            "intent_nonzero_in_cell": sum(
                1 for r in with_intent if r["container"]["kind"] == "cell"),
            "intent_nonzero_multiline": sum(
                1 for r in with_intent if r["lines"] > 1),
        },
        "first_line": {
            "intent_nonzero": _score(with_intent, first, "horzpos0", key),
            "intent_negative": _score(negative, first, "horzpos0", key),
            "intent_positive": _score(positive, first, "horzpos0", key),
            "all_paragraphs": _score(all_records, first, "horzpos0", key),
        },
        "second_line": {
            "intent_nonzero": _score(
                _population(with_intent, lambda r: r["horzpos1"] is not None),
                second, "horzpos1", key),
            "all_paragraphs": _score(
                _population(all_records, lambda r: r["horzpos1"] is not None),
                second, "horzpos1", key),
        },
        "per_form": {},
    }

    for label in sorted(set(r["form"] for r in all_records)):
        rows = [r for r in all_records if r["form"] == label]
        rows_i = [r for r in rows if r["intent"] != 0]
        report["per_form"][label] = {
            "paragraphs_with_cache": len(rows),
            "intent_nonzero": len(rows_i),
            "first_line": {
                name: bucket["exact"]
                for name, bucket in _score(rows_i, first, "horzpos0",
                                           key).items()},
        }
    del labels

    report["horzsize"] = _horzsize_fit(all_records, with_intent)
    report["intent_values"] = _intent_shape(with_intent)
    report["all_lines"] = _all_lines_fit(all_records)
    return report


def _all_lines_fit(all_records):
    """``horzpos == left`` over EVERY cached line, not just the first two.

    The first-line and second-line tables above cover 2995 + 161 of the
    corpus's 3214 cached boxes; this one covers all of them, so "the intent
    never enters the saved line box" is a statement about the whole cache.
    """
    candidates = {
        "left": lambda l, i, n: l,
        "left, intent on line 0": lambda l, i, n: (
            max(0, l + i) if n == 0 else l),
        "hanging: left+|intent| after line 0": lambda l, i, n: (
            l if n == 0 else l + abs(min(i, 0))),
    }
    out = {}
    for name, fn in candidates.items():
        exact = 0
        total = 0
        misses = []
        for rec in all_records:
            for number, observed in enumerate(rec["seg_horzpos"]):
                total += 1
                predicted = fn(rec["left"], rec["intent"], number)
                if predicted == observed:
                    exact += 1
                elif len(misses) < MAX_COUNTEREXAMPLES:
                    misses.append({
                        "form": rec.get("form"),
                        "paragraph": rec["paragraph"], "line": number,
                        "left": rec["left"], "intent": rec["intent"],
                        "observed": observed, "predicted": predicted})
        out[name] = {"exact": exact, "total": total,
                     "counterexamples": misses}
    return out


def _horzsize_fit(all_records, with_intent):
    """Does a negative ``intent`` WIDEN the first line, or only move it?

    The question is asked without needing the container's width: if the
    indent only moves the left edge then the first line's right edge is the
    second line's, and if it widens the first line then the two differ by the
    intent.  Only a multi-line paragraph can answer, so the count of those is
    part of the answer.
    """
    multi = [r for r in all_records if r["horzpos1"] is not None]
    multi_i = [r for r in with_intent if r["horzpos1"] is not None]

    def _edges(rows):
        same = 0
        deltas = Counter()
        examples = []
        for rec in rows:
            edge0 = rec["horzpos0"] + rec["horzsize0"]
            edge1 = rec["horzpos1"] + rec["horzsize1"]
            deltas[edge0 - edge1] += 1
            if edge0 == edge1:
                same += 1
            elif len(examples) < MAX_COUNTEREXAMPLES:
                examples.append({
                    "form": rec.get("form"), "paragraph": rec["paragraph"],
                    "left": rec["left"], "intent": rec["intent"],
                    "edge0": edge0, "edge1": edge1,
                })
        return {"same_right_edge": same, "total": len(rows),
                "delta_histogram": dict(sorted(deltas.items())),
                "counterexamples": examples}

    return {
        "all_multiline": _edges(multi),
        "intent_multiline": _edges(multi_i),
        "meaning": (
            "same_right_edge counts paragraphs whose first and second cached "
            "lines end at the same x.  A negative intent that WIDENS the "
            "first line would show as a delta equal to the intent; a negative "
            "intent that only MOVES the left edge shows as delta 0."),
    }


def _intent_shape(with_intent):
    """What the corpus's non-zero intents actually look like."""
    pairs = Counter((r["left"], r["intent"]) for r in with_intent)
    return {
        "distinct_left_intent_pairs": len(pairs),
        "top_pairs": [
            {"left": left, "intent": intent, "paragraphs": count}
            for (left, intent), count in pairs.most_common(12)],
        "intent_larger_than_left": sum(
            1 for r in with_intent if r["left"] + r["intent"] < 0),
        "aligns": dict(Counter(r["align"] for r in with_intent)),
        "with_tab": sum(1 for r in with_intent if r["tabs"]),
        "with_tab_pr": sum(1 for r in with_intent if r["tab_pr"]),
        "with_heading": sum(
            1 for r in with_intent
            if (r.get("heading_type") or "NONE").upper() != "NONE"),
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _print_report(report, per_form_labels):
    print(f"question: {report['question']}")
    print()
    counts = report["counts"]
    print("population")
    for key in ("paragraphs_with_cache", "lines_cached", "intent_nonzero",
                "intent_negative", "intent_positive",
                "intent_nonzero_in_cell", "intent_nonzero_multiline"):
        print(f"  {key:<26} {counts[key]}")
    print()

    for section, populations in (("first_line", ("intent_nonzero",
                                                 "intent_negative",
                                                 "intent_positive",
                                                 "all_paragraphs")),
                                 ("second_line", ("intent_nonzero",
                                                  "all_paragraphs"))):
        print(f"{section}: exact matches / scored")
        names = list(report[section][populations[0]])
        head = "  " + f"{'candidate':<26}" + "".join(
            f"{p:>22}" for p in populations)
        print(head)
        for name in names:
            row = f"  {name:<26}"
            for pop in populations:
                bucket = report[section][pop][name]
                row += f"{bucket['exact']:>13} /{bucket['total']:>7}"
            print(row)
        print()

    print("first_line counter-examples (intent != 0)")
    for name, bucket in report["first_line"]["intent_nonzero"].items():
        if not bucket["counterexamples"]:
            print(f"  {name:<26} none -- exact on all "
                  f"{bucket['total']}")
            continue
        misses = bucket["total"] - bucket["exact"]
        print(f"  {name:<26} {misses} misses, first "
              f"{len(bucket['counterexamples'])}:")
        for miss in bucket["counterexamples"]:
            print(f"      {miss['form']} p{miss['paragraph']} "
                  f"left={miss['left']} intent={miss['intent']} "
                  f"cache={miss['observed']} predicted={miss['predicted']}")
    print()

    print("per form: first-line exact / paragraphs with intent != 0")
    names = list(report["first_line"]["intent_nonzero"])
    width = max(len(f) for f in report["per_form"]) if report["per_form"] else 8
    print("  " + " " * width + "".join(f"{n[:20]:>21}" for n in names))
    for label in sorted(report["per_form"]):
        bucket = report["per_form"][label]
        row = f"  {label:<{width}}"
        for name in names:
            row += f"{bucket['first_line'][name]:>13}/{bucket['intent_nonzero']:<7}"
        print(row)
    print()

    print("every cached line box, not just the first two")
    for name, bucket in report["all_lines"].items():
        print(f"  {name:<38} {bucket['exact']:>5} / {bucket['total']}")
        for miss in bucket["counterexamples"]:
            print(f"      {miss['form']} p{miss['paragraph']} "
                  f"line {miss['line']} left={miss['left']} "
                  f"intent={miss['intent']} cache={miss['observed']} "
                  f"predicted={miss['predicted']}")
    print()

    size = report["horzsize"]
    print("horzsize: does a negative intent widen the first line?")
    print(f"  {size['meaning']}")
    for key in ("all_multiline", "intent_multiline"):
        bucket = size[key]
        print(f"  {key:<20} same right edge {bucket['same_right_edge']} / "
              f"{bucket['total']}, deltas {bucket['delta_histogram']}")
        for ex in bucket["counterexamples"]:
            print(f"      {ex['form']} p{ex['paragraph']} left={ex['left']} "
                  f"intent={ex['intent']} edge0={ex['edge0']} "
                  f"edge1={ex['edge1']}")
    print()

    shape = report["intent_values"]
    print("what the non-zero intents look like")
    print(f"  distinct (left, intent) pairs   "
          f"{shape['distinct_left_intent_pairs']}")
    print(f"  left + intent < 0               "
          f"{shape['intent_larger_than_left']}")
    print(f"  aligns                          {shape['aligns']}")
    print(f"  carrying an hp:tab              {shape['with_tab']}")
    print(f"  declaring a tabPrIDRef          {shape['with_tab_pr']}")
    print(f"  carrying an hp:heading          {shape['with_heading']}")
    print("  most common pairs:")
    for pair in shape["top_pairs"]:
        print(f"      left={pair['left']:>6} intent={pair['intent']:>7}  "
              f"{pair['paragraphs']} paragraphs")

    if "pdf" in report:
        pdf = report["pdf"]
        print()
        print("the reference PDF: where the first line is actually drawn")
        print(f"  {pdf['meaning']}")
        print(f"  tolerance {pdf['tolerance_hwp']} HWPUNIT; "
              f"{pdf['unmatched_paragraphs']} paragraphs unmatched; "
              f"forms without a reference: "
              f"{pdf['forms_without_reference'] or 'none'}")
        print(f"  {'population':<20}{'scored':>8}{'at left':>10}"
              f"{'at left+intent':>16}{'med d_left':>13}")
        for key in ("all", "intent_zero", "intent_nonzero", "intent_negative",
                    "intent_positive", "discriminating"):
            bucket = pdf[key]
            print(f"  {key:<20}{bucket['total']:>8}{bucket['at_left']:>10}"
                  f"{bucket['at_left_plus_intent']:>16}"
                  f"{str(bucket['d_left_median']):>13}")
        second = pdf["second_line"]
        print(f"  second drawn line of a negative-intent paragraph: "
              f"{second['at_left']} at left, "
              f"{second['at_left_plus_abs_intent']} at left+|intent|, of "
              f"{second['total']}")
        print("  every paragraph whose two readings differ:")
        for row in pdf["discriminating_rows"]:
            print(f"      {row['form']} p{row['paragraph']} "
                  f"left={row['left']} intent={row['intent']} "
                  f"drawn_x0={row['drawn_x0']} "
                  f"(-left {row['d_left']}, "
                  f"-max(0,left+intent) {row['d_left_plus_intent']})")
        for row in pdf["examples"]:
            print(f"      {row['form']} p{row['paragraph']} "
                  f"left={row['left']} intent={row['intent']} "
                  f"drawn_x0={row['drawn_x0']} "
                  f"(-left {row['d_left']}, "
                  f"-max(0,left+intent) {row['d_left_plus_intent']})")
    del per_form_labels


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hwpx", nargs="?", help="one .hwpx form")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form")
    parser.add_argument("--pdf", action="store_true",
                        help="also ask each form's reference PDF where it "
                             "draws the first line")
    parser.add_argument("--json", metavar="PATH",
                        help="write the full report as JSON")
    parser.add_argument("--no-text", action="store_true",
                        help="suppress the text report (use with --json)")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    targets = []
    if args.hwpx:
        targets.append((Path(args.hwpx), None))
    if args.corpus:
        targets.extend(layout_divergence.corpus_forms(repo_root))
    if not targets:
        build_parser().error("give a form, or --corpus")

    labels = layout_divergence.short_labels([p.stem for p, _ in targets])
    records = []
    for path, _reference in targets:
        for rec in probe_form(path):
            rec["form"] = labels[path.stem]
            records.append(rec)

    report = analyse(records, labels)
    report["forms"] = sorted(labels.values())

    if args.pdf:
        pdf_rows = []
        unmatched = 0
        missing = []
        for path, reference in targets:
            if reference is None or not Path(reference).is_file():
                missing.append(labels[path.stem])
                continue
            rows, miss = probe_pdf(path, reference)
            for row in rows:
                row["form"] = labels[path.stem]
            pdf_rows.extend(rows)
            unmatched += miss
        report["pdf"] = analyse_pdf(pdf_rows, unmatched)
        report["pdf"]["forms_without_reference"] = missing
    if not args.no_text:
        _print_report(report, labels)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"report": report, "records": records},
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
