#!/usr/bin/env python3
"""How far past its column may a line's advance run before Hancom wraps it?

#242 measured where a text line's box ENDS (``LINE_BOX_END``), #256 and #295
measured the page-BOTTOM fit test, and #297 found that the right-edge test has
never been measured at all: every stand-in variant that corrects substituted
face widths loses the cached break test on ``moel-2025`` ¶64 and ¶160, one
78-character sentence in a 48190 HWPUNIT column, because the corrected width
of the 64 characters the cache keeps on one line lands 15 to 86 HWPUNIT over
the box.  0.03% to 0.18% of the line.  Under the shipped, under-measuring
metric the break matches by accident.

So: is our fit test too strict?  The candidates are not guesses.  Korean
typesetting lets a trailing space hang; 금칙 처리 lets a line-final punctuation
mark hang into the margin; ``hp:paraPr@condense`` (글자 압축) lets a line be
squeezed rather than wrapped; and #283 measured Hancom's pen positions onto a
1/600 inch (12 HWPUNIT) grid, which would make both the sum and the box
integers on that grid before they are compared.

WHAT IS MEASURED
----------------
The cache is a two-sided oracle about the right edge and nobody has read it
that way.  For every cached ``hp:lineseg`` — top level and in cells — this
probe reads two populations off the file:

* **KEPT.**  Hancom put exactly these characters on one line, so whatever our
  width for them is, the true rule must call it a fit.  Every cached line is
  one observation.  ``kept max`` is the largest excess a candidate has to
  forgive.
* **REJECTED.**  Hancom did NOT put the next word on the line.  The breaker is
  greedy and its widths are monotone, so a cut at ``last`` proves that the
  span reaching to the last non-space character before the NEXT break
  opportunity overflowed — that exact span, not the next character, is the
  tight bound.  ``rejected min`` is the smallest excess a candidate must
  still reject.

A candidate with ``kept max < rejected min`` has room for a threshold and the
bracket names it.  A candidate with ``kept max >= rejected min`` is refuted by
the cache itself, whatever it does to the scoreboard.

THE CANDIDATES
--------------
``strict``      the whole cached span, trailing space included, against the box.
``space``       a trailing space hangs (this is what ``compute_lines`` already
                does, by never testing a span that ends in whitespace).
``punct``       ``space``, and a line-final punctuation mark hangs too (금칙).
``condense``    ``space``, less what ``hp:paraPr@condense`` lets the span's
                spaces give up.  The shipped rule.
``tol12``       ``condense``, with the threshold read off the bracket in whole
                12 HWPUNIT pen steps rather than pinned at zero.
``pen``         ``condense``, with the width taken to the nearest 12 HWPUNIT
                before the comparison.

Every excess is ``ours - avail`` in HWPUNIT, where ``avail`` is the cached
``@horzsize`` less :meth:`OwnRenderer._line_indent` — the quantity the breaker
actually fits against, since #297/#268 established that the indent is inside
the box and not part of it.  ``--json`` also carries the raw ``@horzsize``.

THE TWO-SIDED SCORE
-------------------
``--breaks`` installs each candidate in the REAL breaker — by overriding
:meth:`OwnRenderer._line_fits` and nothing else — and runs
``advance_probe.break_scoreboard`` on real column widths, so the bracket above
is checked against the number that decides whether a rule ships: cached break
positions reproduced, split into the installed-face control (which must not
move) and the rest.

``--standin VARIANT`` installs one of ``hft_width_table``'s stand-in width
rules underneath, which is the whole point of the exercise: the question is
not whether the shipped, under-measuring metric survives a looser fit test but
whether a CORRECTED metric does.

THE THREE OVER-BROKEN CELLS
---------------------------
``--cells`` is #312's view and it asks one question of ``OVERBROKEN_CELLS``,
the three cells #311 found behind all 63 ``table_row_heights`` class-B
paragraphs: *why* does our breaker split each of them into one more line than
the cache holds?

For each it prints the cached lines (``hp:lineseg`` ``@horzpos`` /
``@horzsize`` and the text on each), our lines off the REAL breaker on the
REAL column, the column ``_table_tracks`` hands the cell against the cached
``@horzsize`` it is meant to reproduce, our width for each cached line's own
characters under the shipped metric with its runs decomposed
(``advance_probe.OurMetrics``: declared face, resolved file, installed or
HFT-metered, size, ``hh:ratio``, 자간, bold), and the excess over the box.

The excess is then decomposed into the terms that have been measured
separately elsewhere — the trailing 자간 (#307), the installed-face
punctuation residual (#307, ``INSTALLED_PUNCT_RESIDUAL_HWP``), the measured
HFT table against the face metric (#292), the right-edge budget (#301,
``RIGHT_EDGE_TOLERANCE_HWP``) — and what is left over is named as left over.

Because a line the breaker never got to *offer* has no width story at all, the
view also reports whether each cached break position is in our own
``break_opportunities`` set, and scores the mechanisms the three cells
between them ask for against the whole corpus — on
``advance_probe.break_scoreboard`` and on ``lineseg_agreement``, the two
numbers #302 and #307 argued the right-edge budget from:

``syllable``   a Hangul/CJK syllable break is allowed whatever
               ``hh:breakSetting@breakNonLatinWord`` declares;
``syl@just``   the same, scoped to JUSTIFY paragraphs, which is the obvious
               narrowing and is measured so that it is refuted rather than
               assumed;
``budget240``  ``RIGHT_EDGE_TOLERANCE_HWP`` raised from 96 to 240 HWPUNIT.

Usage::

    python engine/scripts/right_edge_probe.py FORM.hwpx
    python engine/scripts/right_edge_probe.py --corpus
    python engine/scripts/right_edge_probe.py --corpus --breaks
    python engine/scripts/right_edge_probe.py --corpus --breaks --standin table+pen
    python engine/scripts/right_edge_probe.py --corpus --cells
    python engine/scripts/right_edge_probe.py --corpus --json out.json --no-text

This is measurement.  On its own it changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import advance_probe  # noqa: E402
import layout_divergence  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

_iattr = own_render._iattr
_local = own_render._local

#: 1/600 inch, the grid #283 measured Hancom's pen positions onto.
PEN_GRID_HWP = advance_probe.DEVICE_GRID_HWP

#: The paragraphs #297 named: ``moel-2025`` ¶64 and ¶160, the same
#: 78-character contract preamble twice.  Reported line by line under every
#: candidate because they are the only two paragraphs in the corpus whose
#: break the stand-in rules move.  Keyed by file stem, not by the short label,
#: which depends on how many forms the run was given.
WATCHED = {"moel-pyojun-geunrogyeyakseo-2025": (64, 160)}

#: The three cells #311 found behind every one of the 63 `table_row_heights`
#: class-B paragraphs: one paragraph each, which our breaker splits into one
#: more line than the cache holds, growing its row and pushing every paragraph
#: below it down.  ``file stem -> {paragraph address: the cell it sits in}``.
OVERBROKEN_CELLS = {
    "moel-pyojun-geunrogyeyakseo-2013": {261: "table 6 row 9 cell 1"},
    "saeopja-deungnok-sinchengseo": {189: "table 1 row 11 cell 0",
                                     393: "table 4 row 0 cell 8"},
}

#: #307's installed-face punctuation residual, PER GLYPH: +253.3 HWPUNIT over
#: the 487 anchored punctuation advances metered off a face this machine has,
#: once the 58 Hancom answered out of its own HFT table are taken out.  A TERM
#: IN A DECOMPOSITION and not a rule — no code in this repo applies it, and
#: #307 recorded it as mixed in sign inside one face and unexplained.
INSTALLED_PUNCT_RESIDUAL_HWP = 253.3 / 487

#: The control #307 pinned and #302 argued the budget from: ``jumin``'s
#: ``lineseg_agreement``, whose ¶139 and ¶160 a lower right-edge budget lost.
#: Any mechanism ``--cells`` scores is asked the same question, because a
#: break rule that moves the breaker moves this too.
LINESEG_CONTROL_STEM = "jumin-deungchobon-sinchengseo"
LINESEG_CONTROL_PARAGRAPHS = (139, 160)

#: What ``--cells`` raises the right-edge budget to when it prices the budget
#: as the term that closes a cell.  20 pen steps: the smallest whole step
#: above `saeopja` ¶393's excess, which is what a budget would have to cover.
CELL_BUDGET_HWP = 240.0

#: How far the tolerance sweep runs, in whole 12 HWPUNIT pen steps.  40 steps
#: is 480 HWPUNIT, about an eighth of a 13 pt Hangul cell and five times what
#: #297's two paragraphs need; past that a "tolerance" is a licence to
#: overflow and not a rounding rule.
MAX_TOLERANCE_STEPS = 40

#: The sweep prints every step up to here and then every fourth one.
SWEEP_DENSE_STEPS = 12

RULE_QUESTION = (
    "for every cached line, what is our advance for exactly those characters "
    "minus the column, and what rule keeps the ones that come out over?")


# --------------------------------------------------------------------------
# The candidates
# --------------------------------------------------------------------------
# Each takes one measured line record and returns the EXCESS it would compare
# against its threshold: negative or zero fits, positive overflows.  Written
# as functions of the record rather than of the renderer so the bracket and
# the installed breaker cannot drift apart.

def _excess_strict(rec):
    return rec["w_full"] - rec["avail"]


def _excess_space(rec):
    return rec["w_visible"] - rec["avail"]


def _excess_punct(rec):
    return rec["w_no_trail_punct"] - rec["avail"]


def _excess_condense(rec):
    return rec["w_visible"] - rec["avail"] - rec["slack"]


def _excess_pen(rec):
    quantised = round(rec["w_visible"] / PEN_GRID_HWP) * PEN_GRID_HWP
    return quantised - rec["avail"] - rec["slack"]


def _excess_gap(rec):
    """``condense``, with the LAST character's own 자간 gap counted in.

    ``_measure`` drops the trailing ``hh:charPr@spacing`` gap because 자간
    opens space BETWEEN characters, and the reference's DRAWN pen positions
    say so (``own_render._spacing_gap``: gianmun's four-cell 발신명의 run at
    ``spacing="50"`` is 5.5 em wide, not 6.0).  That is a measurement of what
    is drawn.  Whether the BREAKER fits the same quantity is a separate
    question the drawn positions cannot answer, and this candidate is it:
    every character carries its own gap, the last one included, so a span of
    ``k`` characters occupies ``k`` cells rather than ``k`` advances and
    ``k - 1`` gaps.
    """
    return (rec["w_visible"] + rec["trailing_gap"]
            - rec["avail"] - rec["slack"])


#: ``name -> (excess function, threshold in HWPUNIT or None to read one off
#: the bracket)``.  ``tol12`` shares ``condense``'s excess on purpose: a
#: tolerance is not a different measurement, it is a different threshold on
#: the same one, and pricing it as its own row is how the bracket says
#: whether any k exists.
CANDIDATES = {
    "strict": (_excess_strict, 0.0),
    "space": (_excess_space, 0.0),
    "punct": (_excess_punct, 0.0),
    "condense": (_excess_condense, 0.0),
    "tol12": (_excess_condense, None),
    "pen": (_excess_pen, 0.0),
    "gap": (_excess_gap, 0.0),
}

CANDIDATE_ORDER = ("strict", "space", "punct", "condense", "tol12", "pen",
                   "gap")

CANDIDATE_BASIS = {
    "strict": "no hang at all: the whole cached span against the box",
    "space": "Korean typesetting hangs a line-final space (#242)",
    "punct": "금칙 처리 / 줄 끝 문장부호 내밀기",
    "condense": "hp:paraPr@condense, an OWPML attribute — the rule before "
                "#298, and this table's baseline",
    "tol12": "a fixed tolerance of k x 12 HWPUNIT (#283's pen grid)",
    "pen": "the sum rounded onto the 12 HWPUNIT pen grid before comparing",
    "gap": "hh:charPr@spacing counted after the LAST character too, so a "
           "span is k cells and not k advances plus k-1 gaps",
}


# --------------------------------------------------------------------------
# Reading the cache
# --------------------------------------------------------------------------

def _is_punct(ch):
    return advance_probe.char_class(ch) in ("punct", "fw_punct")


def _cell_paragraphs(section):
    """``{id(hp:p)}`` for every paragraph seated inside an ``hp:tc``."""
    out = set()
    for el in section.iter():
        if _local(el.tag) != "tc":
            continue
        for kid in el.iter():
            if _local(kid.tag) == "p":
                out.add(id(kid))
    return out


def probe_form(path, repo_root=None):
    """One record per cached line, plus the rejected span that follows it.

    Nothing here renders: the widths come through ``_char_advance_tables``,
    the same seam ``compute_lines`` breaks on and the same one a stand-in
    variant overrides, so a record is the breaker's own arithmetic and not a
    second model of it.
    """
    renderer = own_render.OwnRenderer(path, repo_root=repo_root)
    records = []
    for section in renderer.sections:
        in_cell = _cell_paragraphs(section)
        for el in section.iter():
            if _local(el.tag) != "p":
                continue
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            if not para.linesegs or para.objects:
                continue
            cells = lineseg_vs_pdf.character_cells(para)
            if _iattr(para.linesegs[-1], "textpos") > len(cells):
                continue
            records.extend(_probe_paragraph(
                renderer, para, el,
                address=renderer.paragraph_index.get(id(el)),
                in_cell=id(el) in in_cell))
    return records


def _probe_paragraph(renderer, para, el, address, in_cell):
    del el
    chars = para.chars
    count = len(chars)
    if not count:
        return []
    advances, gaps = renderer._char_advance_tables(None, para)

    def width(start, end):
        if end <= start:
            return 0.0
        return (sum(advances[start:end]) + sum(gaps[start:end])
                - gaps[end - 1])

    pr = para.para_pr
    condense = max(0, min(100, pr.get("condense", 0) or 0))
    align = pr.get("align", "LEFT")

    def slack(start, end):
        spaces = sum(advances[i] for i in range(start, end)
                     if chars[i][0] in own_render.SPACE_CHARS)
        return spaces * condense / 100.0

    opportunities = own_render.break_opportunities(
        para.text, pr.get("break_latin", "KEEP_WORD"),
        pr.get("break_non_latin", "KEEP_WORD"))

    spans = lineseg_vs_pdf.cached_split(para, cells_of(para))
    ranges = []
    for lo, hi in spans:
        seated = advance_probe._para_chars_in_cells(para, lo, hi)
        if not seated:
            ranges.append(None)
            continue
        # A cell no character occupies is a CONTROL -- an explicit
        # hp:lineBreak is the one that matters here.  A cached line that ends
        # on one was not broken by its width, so its break says nothing about
        # the right edge and it is kept out of the rejected population.  On
        # ``moel-2025`` this is the difference between a rejected minimum of
        # -35690 HWPUNIT and a real one: ¶30's first line is fourteen
        # characters in a 48188 box because the author pressed shift-enter.
        ranges.append((seated[0][0], seated[-1][0] + 1,
                       (hi - lo) == len(seated)))

    out = []
    for index, span in enumerate(ranges):
        if span is None:
            continue
        first, last, width_break = span
        # A tab's advance is resolved against the line's own running
        # position inside compute_lines, so a line holding one has no
        # width this probe can state.  Same exclusion as ``fit_scoreboard``.
        if any(chars[i][0] == "\t" for i in range(first, last)):
            continue
        visible = last
        while visible > first and chars[visible - 1][0] in own_render.SPACE_CHARS:
            visible -= 1
        if visible <= first:
            continue
        horzsize = _iattr(para.linesegs[index], "horzsize")
        if horzsize <= 0:
            continue
        indent = renderer._line_indent(para, index)
        avail = float(max(1, horzsize - indent))

        w_full = width(first, last)
        w_visible = width(first, visible)
        trailing = chars[visible - 1][0]
        if last > visible:
            trailing_class = "space"
        elif _is_punct(trailing):
            trailing_class = "punct"
        else:
            trailing_class = "other"
        w_no_trail_punct = (width(first, visible - 1)
                            if trailing_class == "punct" else w_visible)

        rec = {
            "form": None, "stem": None, "address": address, "line": index,
            "in_cell": in_cell, "align": align, "condense": condense,
            "horzsize": horzsize, "indent": indent, "avail": avail,
            # The span's own character indices, so a caller can decompose the
            # width this record states without re-deriving the span.
            "first": first, "visible": visible, "last": last,
            "chars": visible - first,
            # The 자간 gap ``width()`` drops off the end of the span, which
            # the ``gap`` candidate puts back.
            "trailing_gap": gaps[visible - 1],
            "w_full": w_full, "w_visible": w_visible,
            "w_no_trail_punct": w_no_trail_punct,
            "slack": slack(first, visible),
            "trailing": trailing_class,
            "last_line": index == len(ranges) - 1,
            "width_break": width_break,
            "fill": w_visible / avail,
            "rejected": None,
        }

        # The rejected span.  Greedy + monotone: the cut at ``last`` proves
        # that the span reaching the LAST non-space character before the next
        # break opportunity did not fit.  Any earlier character in that run
        # only might have.
        if (width_break and index + 1 < len(ranges)
                and ranges[index + 1] is not None):
            nxt = None
            for position in opportunities:
                if position > last:
                    nxt = position
                    break
            if nxt is None:
                nxt = count
            q = min(nxt, count) - 1
            while q >= last and chars[q][0] in own_render.SPACE_CHARS:
                q -= 1
            if q >= last and not any(chars[i][0] == "\t"
                                     for i in range(first, q + 1)):
                r_full = width(first, q + 1)
                r_punct = (width(first, q)
                           if _is_punct(chars[q][0]) and q > first else r_full)
                rec["rejected"] = {
                    "end": q + 1, "chars": q + 1 - first,
                    "w_full": r_full, "w_visible": r_full,
                    "w_no_trail_punct": r_punct,
                    "slack": slack(first, q + 1),
                    "avail": avail,
                    "trailing_gap": gaps[q],
                }
        out.append(rec)
    return out


def cells_of(para):
    return lineseg_vs_pdf.character_cells(para)


# --------------------------------------------------------------------------
# The bracket
# --------------------------------------------------------------------------

def bracket(records, name):
    """``kept max`` / ``rejected min`` for one candidate, over ``records``."""
    excess, threshold = CANDIDATES[name]
    kept = [excess(rec) for rec in records]
    rejected = [excess(rec["rejected"]) for rec in records
                if rec["rejected"] is not None]
    kept_max = max(kept) if kept else None
    rejected_min = min(rejected) if rejected else None
    row = {
        "candidate": name, "kept": len(kept), "rejected": len(rejected),
        "kept_max": kept_max, "rejected_min": rejected_min,
        "kept_over": sum(1 for value in kept if value > (threshold or 0.0)),
        "consistent": (kept_max is not None and rejected_min is not None
                       and kept_max < rejected_min),
    }
    if threshold is None:
        # The BEST whole pen step, not the one that forgives everything: a
        # threshold high enough to cover every kept line would be 1370
        # HWPUNIT here, which is a third of a character, and it buys that by
        # keeping spans Hancom demonstrably rejected.  Take the k that gets
        # the most lines right on both sides at once, smallest k on a tie.
        best = None
        for step in range(0, MAX_TOLERANCE_STEPS + 1):
            candidate = step * PEN_GRID_HWP
            wrong = (sum(1 for value in kept if value > candidate)
                     + sum(1 for value in rejected if value <= candidate))
            if best is None or wrong < best[0]:
                best = (wrong, candidate, step)
        row["threshold"] = best[1]
        row["k"] = best[2]
    else:
        row["threshold"] = threshold
        row["k"] = None
    if row["kept_max"] is not None and row["rejected_min"] is not None:
        row["room"] = row["rejected_min"] - row["kept_max"]
    else:
        row["room"] = None
    # How many of the two populations the threshold gets right.  This is the
    # cache's own verdict on the candidate, one line at a time, and it is
    # independent of the breaker.
    row["kept_wrong"] = sum(1 for value in kept if value > row["threshold"])
    row["rejected_wrong"] = sum(1 for value in rejected
                                if value <= row["threshold"])
    return row


def tolerance_sweep(records, name="condense"):
    """What a tolerance of ``k`` pen steps costs and buys, k by k.

    The bracket asks whether a threshold EXISTS that gets everything right.
    This asks the question that is actually open once the answer is no: how
    many cached lines does each k rescue, and how many spans Hancom rejected
    does it wrongly keep?  A rule is worth having when the first number moves
    and the second does not.
    """
    excess = CANDIDATES[name][0]
    kept = sorted(excess(rec) for rec in records)
    rejected = sorted(excess(rec["rejected"]) for rec in records
                      if rec["rejected"] is not None)
    rows = []
    for step in range(0, MAX_TOLERANCE_STEPS + 1):
        value = step * PEN_GRID_HWP
        rows.append({
            "k": step, "tolerance": value,
            "kept_wrong": sum(1 for item in kept if item > value),
            "rejected_wrong": sum(1 for item in rejected if item <= value),
        })
    return rows


def boundary_counterexamples(records, name="condense", window=600.0):
    """The kept lines and rejected spans a small tolerance decides between."""
    excess = CANDIDATES[name][0]
    kept = [(excess(rec), rec) for rec in records]
    rejected = [(excess(rec["rejected"]), rec) for rec in records
                if rec["rejected"] is not None]
    out = {"kept_over": [], "rejected_near": []}
    for value, rec in sorted(kept, key=lambda item: item[0]):
        if value <= 0.0:
            continue
        out["kept_over"].append({
            "excess": value, "form": rec["form"], "paragraph": rec["address"],
            "line": rec["line"], "chars": rec["chars"], "fill": rec["fill"],
            "trailing": rec["trailing"], "condense": rec["condense"],
            "in_cell": rec["in_cell"]})
    for value, rec in sorted(rejected, key=lambda item: item[0]):
        if value > window:
            continue
        out["rejected_near"].append({
            "excess": value, "form": rec["form"], "paragraph": rec["address"],
            "line": rec["line"], "chars": rec["rejected"]["chars"],
            "align": rec["align"], "in_cell": rec["in_cell"]})
    return out


def excess_distribution(records):
    """The kept excess, split by trailing class and by the other cuts."""
    out = {}
    groups = {
        "all": records,
        "trailing space": [r for r in records if r["trailing"] == "space"],
        "trailing punct": [r for r in records if r["trailing"] == "punct"],
        "trailing other": [r for r in records if r["trailing"] == "other"],
        "condense > 0": [r for r in records if r["condense"] > 0],
        "condense = 0": [r for r in records if r["condense"] == 0],
        "in cell": [r for r in records if r["in_cell"]],
        "top level": [r for r in records if not r["in_cell"]],
        "JUSTIFY": [r for r in records if r["align"] == "JUSTIFY"],
        "not JUSTIFY": [r for r in records if r["align"] != "JUSTIFY"],
        # The lines that can decide anything.  A line filling a tenth of its
        # box is a forced break or a one-line paragraph and its excess is a
        # statement about the form's layout, not about the fit test.
        "fill >= 0.95": [r for r in records if r["fill"] >= 0.95],
        "width breaks": [r for r in records if r["width_break"]],
    }
    for label, rows in groups.items():
        values = sorted(_excess_space(rec) for rec in rows)
        out[label] = _stats(values)
    return out


def _stats(values):
    if not values:
        return {"n": 0}
    n = len(values)

    def pct(share):
        return values[min(n - 1, max(0, int(round(share * (n - 1)))))]

    over = [value for value in values if value > 0.0]
    return {
        "n": n, "min": values[0], "p50": pct(0.50), "p90": pct(0.90),
        "p99": pct(0.99), "max": values[-1],
        "over": len(over),
        "over_max": max(over) if over else None,
        "over_on_grid": sum(1 for value in over
                            if abs(value / PEN_GRID_HWP
                                   - round(value / PEN_GRID_HWP)) < 1e-6),
    }


def alignment_table(records):
    counts = Counter(rec["align"] for rec in records)
    return sorted(counts.items(), key=lambda item: -item[1])


def watched_rows(records, labels_seen):
    """¶64 / ¶160 of ``moel-2025``, line by line, under every candidate."""
    del labels_seen
    out = []
    for rec in records:
        wanted = WATCHED.get(rec["stem"])
        if not wanted or rec["address"] not in wanted:
            continue
        row = {"form": rec["form"], "paragraph": rec["address"],
               "line": rec["line"], "chars": rec["chars"],
               "avail": rec["avail"], "horzsize": rec["horzsize"],
               "condense": rec["condense"], "align": rec["align"],
               "trailing": rec["trailing"],
               "excess": {name: CANDIDATES[name][0](rec)
                          for name in CANDIDATE_ORDER}}
        if rec["rejected"] is not None:
            row["rejected_excess"] = {
                name: CANDIDATES[name][0](rec["rejected"])
                for name in CANDIDATE_ORDER}
        out.append(row)
    return sorted(out, key=lambda row: (row["paragraph"], row["line"]))


# --------------------------------------------------------------------------
# Installing a candidate in the real breaker
# --------------------------------------------------------------------------

def _fits_factory(name, threshold):
    excess = CANDIDATES[name][0]

    def _line_fits(self, para, width_hwp, avail_hwp, slack_hwp, start, end,
                   trailing_gap_hwp=0.0):
        chars = para.chars
        visible = end
        while visible > start and chars[visible - 1][0] in own_render.SPACE_CHARS:
            visible -= 1
        rec = {
            "w_full": width_hwp, "w_visible": width_hwp,
            "w_no_trail_punct": width_hwp, "avail": avail_hwp,
            "slack": slack_hwp, "trailing_gap": trailing_gap_hwp,
        }
        if visible > start and _is_punct(chars[visible - 1][0]):
            # The breaker never presents a span that ends in whitespace, so
            # the punctuation hang is the only piece it has to compute here:
            # what would this span be worth with its last mark hanging?
            rec["w_no_trail_punct"] = self.span_width(None, para, start,
                                                      visible - 1)
        return excess(rec) <= threshold

    return _line_fits


@contextlib.contextmanager
def installed(name, threshold, standin=None):
    """Run one measurement with ``name`` as the breaker's right-edge rule.

    Rebinding ``own_render.OwnRenderer`` and
    ``advance_probe.BreakRecordingRenderer`` is how ``hft_width_table``
    installs a WIDTH rule; a FIT rule is installed the same way and the two
    compose, which is what ``--standin`` is for.
    """
    if standin:
        import hft_width_table
        stack = contextlib.ExitStack()
        stack.enter_context(hft_width_table.variant(standin))
    else:
        stack = contextlib.ExitStack()
    with stack:
        override = {"_line_fits": _fits_factory(name, threshold)}
        base_renderer = own_render.OwnRenderer
        base_recorder = advance_probe.BreakRecordingRenderer
        safe = name.replace("+", "_")
        own_render.OwnRenderer = type(f"FitRenderer_{safe}",
                                      (base_renderer,), dict(override))
        advance_probe.BreakRecordingRenderer = type(
            f"FitRecorder_{safe}", (base_recorder,), dict(override))
        try:
            yield
        finally:
            own_render.OwnRenderer = base_renderer
            advance_probe.BreakRecordingRenderer = base_recorder


def score_breaks(targets, name, threshold, repo_root, standin=None, dpi=144):
    """``break_scoreboard`` under one fit rule: the two-sided score."""
    totals = {"installed": 0, "installed_match": 0, "other": 0,
              "other_match": 0}
    per_form = defaultdict(lambda: {"installed": 0, "installed_match": 0,
                                    "other": 0, "other_match": 0})
    matched = set()
    with installed(name, threshold, standin=standin):
        for path, _reference in targets:
            stem = Path(path).stem
            for row in advance_probe.break_scoreboard(path, dpi=dpi,
                                                      repo_root=repo_root):
                key = "installed" if row["installed"] else "other"
                totals[key] += 1
                per_form[stem][key] += 1
                if row["match"]:
                    totals[key + "_match"] += 1
                    per_form[stem][key + "_match"] += 1
                    matched.add((stem, row["address"]))
    return {"candidate": name, "threshold": threshold, "totals": totals,
            "per_form": dict(per_form), "matched": matched}


def break_report(targets, repo_root, brackets, standin=None, dpi=144):
    rows = []
    baseline = None
    for name in CANDIDATE_ORDER:
        threshold = brackets[name]["threshold"]
        row = score_breaks(targets, name, threshold, repo_root,
                           standin=standin, dpi=dpi)
        if name == "condense":
            baseline = row
        rows.append(row)
    for row in rows:
        if baseline is None:
            row["regressions"] = None
            continue
        row["regressions"] = sorted(baseline["matched"] - row["matched"])
        row["gains"] = sorted(row["matched"] - baseline["matched"])
    for row in rows:
        row.pop("matched", None)
    return rows


# --------------------------------------------------------------------------
# The three over-broken cells (#312)
# --------------------------------------------------------------------------
# #311 found that all 63 ``table_row_heights`` class-B paragraphs are carried
# by three cells whose single paragraph our breaker splits into one more line
# than the cache holds.  Everything below reads those three, and only those
# three, in the breaker's own arithmetic.

@contextlib.contextmanager
def syllable_opportunities():
    """Allow a Hangul/CJK syllable break whatever ``breakNonLatinWord`` says.

    ``compute_lines`` calls the module-level ``break_opportunities``, so
    rebinding it is the same kind of seam ``installed`` uses for the fit test:
    one function, both renderers, nothing else touched.  The rule is
    ``breakNonLatinWord="BREAK_WORD"`` forced on every paragraph — 글자 단위
    — which is what two of the three cells' cached breaks require.
    """
    base = own_render.break_opportunities

    def patched(text, break_latin="KEEP_WORD", break_non_latin="KEEP_WORD"):
        del break_non_latin
        return base(text, break_latin, "BREAK_WORD")

    own_render.break_opportunities = patched
    try:
        yield
    finally:
        own_render.break_opportunities = base


@contextlib.contextmanager
def syllable_opportunities_in_justify():
    """``syllable_opportunities``, but only where the paragraph is JUSTIFY.

    The obvious narrowing, and the one the three cells suggest: two of them
    are 양쪽 정렬 and the third already declares ``BREAK_WORD``, so a rule
    that only lets 양쪽 정렬 break by syllable would reach both without
    touching a left-aligned paragraph anywhere.  ``break_opportunities`` is
    handed text and not a paragraph, so the scope has to be applied one level
    up, in ``compute_lines`` — which is why this is a renderer swap and not a
    function swap.
    """
    def _override(base):
        def compute_lines(self, draw, para, column_hwp, from_char=0,
                          from_line=0):
            pr = para.para_pr
            saved = pr.get("break_non_latin")
            if pr.get("align") == "JUSTIFY":
                pr["break_non_latin"] = "BREAK_WORD"
            try:
                return base.compute_lines(self, draw, para, column_hwp,
                                          from_char=from_char,
                                          from_line=from_line)
            finally:
                pr["break_non_latin"] = saved
        return compute_lines

    base_renderer = own_render.OwnRenderer
    base_recorder = advance_probe.BreakRecordingRenderer
    own_render.OwnRenderer = type(
        "JustifySyllableRenderer", (base_renderer,),
        {"compute_lines": _override(base_renderer)})
    advance_probe.BreakRecordingRenderer = type(
        "JustifySyllableRecorder", (base_recorder,),
        {"compute_lines": _override(base_recorder)})
    try:
        yield
    finally:
        own_render.OwnRenderer = base_renderer
        advance_probe.BreakRecordingRenderer = base_recorder


@contextlib.contextmanager
def tolerance_budget(value):
    """Run one measurement with a different ``RIGHT_EDGE_TOLERANCE_HWP``.

    ``_line_fits`` reads the module global at call time, so this reaches the
    real breaker without subclassing anything.
    """
    old = own_render.RIGHT_EDGE_TOLERANCE_HWP
    own_render.RIGHT_EDGE_TOLERANCE_HWP = value
    try:
        yield
    finally:
        own_render.RIGHT_EDGE_TOLERANCE_HWP = old


#: ``name -> (basis, context manager factory)``.  ``shipped`` is the tree as
#: it stands and is the row every other one is read against.
CELL_CANDIDATES = {
    "shipped": ("the tree as it stands", contextlib.nullcontext),
    "syllable": ("hh:breakSetting@breakNonLatinWord read as BREAK_WORD on "
                 "every paragraph (글자 단위)", syllable_opportunities),
    "syl@just": ("the same, but only where the paragraph is JUSTIFY "
                 "(양쪽 정렬)", syllable_opportunities_in_justify),
    "budget240": (f"RIGHT_EDGE_TOLERANCE_HWP raised from "
                  f"{own_render.RIGHT_EDGE_TOLERANCE_HWP:.0f} to "
                  f"{CELL_BUDGET_HWP:.0f} HWPUNIT (20 pen steps)",
                  lambda: tolerance_budget(CELL_BUDGET_HWP)),
}

CELL_CANDIDATE_ORDER = ("shipped", "syllable", "syl@just", "budget240")


def _cache_breaks(para):
    """The cached line starts, in the breaker's own ``chars`` index space.

    ``hp:lineseg@textpos`` counts cells, not characters; this is the same walk
    ``advance_probe.break_scoreboard`` does, repeated here so a ``--cells``
    record and a scoreboard row cannot disagree about where the cache broke.
    """
    cells = lineseg_vs_pdf.character_cells(para)
    out = []
    for _lo, hi in lineseg_vs_pdf.cached_split(para, cells)[:-1]:
        cut = len(para.chars)
        for index in range(len(para.chars)):
            if para.cell_start[index] >= hi:
                cut = index
                break
        out.append(cut)
    return out


def _runs_in(metrics, para, start, end):
    """The distinct ``OurMetrics`` runs over ``chars[start:end]``, with counts.

    One row per (declared face, resolved file, installed-or-HFT, size, ratio,
    자간, bold) — the decomposition the question asks for, taken off the
    renderer's own API rather than re-derived from the charPr table.
    """
    rows = {}
    order = []
    for ch, cid in para.chars[start:end]:
        run = metrics.run(ch, cid)
        key = (run["declared"], run["resolved"], run["source"], run["hft"],
               run["size_pt"], run["ratio"], run["spacing"], run["bold"])
        if key not in rows:
            rows[key] = {"declared": run["declared"],
                         "resolved": run["resolved"],
                         "source": run["source"], "hft": run["hft"],
                         "size_pt": run["size_pt"], "ratio": run["ratio"],
                         "spacing": run["spacing"], "bold": run["bold"],
                         "chars": 0, "punct": 0}
            order.append(key)
        rows[key]["chars"] += 1
        if _is_punct(ch):
            rows[key]["punct"] += 1
    return [rows[key] for key in order]


def _hft_terms(renderer, para, start, end):
    """(#292) the measured HFT table against the face metric, per character.

    Two numbers, because the table can be silent in two different ways.
    ``measured_delta`` is the HWPUNIT the table MOVED — summed over the
    characters it carries an advance for — and ``uncovered`` counts the
    characters whose declared face IS an HFT face but which the table says
    nothing about, so their advance is the installed outline's, unchecked
    against Hancom's own pen.
    """
    table = renderer.hft_widths
    delta = 0.0
    measured = 0
    uncovered = 0
    for ch, cid in para.chars[start:end]:
        face = renderer._declared_hft_face(cid, ch)
        if face is None:
            continue
        slot = advance_probe.script_slot(ch)
        ratio, _spacing, rel_sz, _offset = renderer._typography(cid, ch)
        pt = (renderer._charpr(cid).get("height_pt") or 10.0) * rel_sz / 100.0
        scale = pt * own_render.HWPUNIT_PER_PT * ratio / 100.0
        em = table.advance_em(face, ch) if table else None
        if em is None:
            uncovered += 1
            continue
        font = renderer._font_for(cid, rel_sz, slot)
        metric = renderer._metric_font_for_pt(cid, pt, slot, font)
        delta += (em - renderer._em_width(metric, ch)) * scale
        measured += 1
    return {"measured": measured, "measured_delta": delta,
            "uncovered": uncovered}


def _cell_record(renderer, metrics, el, address, label, stem):
    """One over-broken cell, read line by line.  All HWPUNIT."""
    para = own_render.Paragraph(el, renderer.defs["para_pr"])
    pr = para.para_pr
    call = renderer.break_calls.get(address)
    column = float(call["column_hwp"]) if call else None
    advances, gaps = renderer._char_advance_tables(None, para)
    condense = max(0, min(100, pr.get("condense", 0) or 0))
    opportunities = set(own_render.break_opportunities(
        para.text, pr.get("break_latin", "KEEP_WORD"),
        pr.get("break_non_latin", "KEEP_WORD")))

    def width(start, end):
        if end <= start:
            return 0.0
        return sum(advances[start:end]) + sum(gaps[start:end]) - gaps[end - 1]

    def slack(start, end):
        spaces = sum(advances[i] for i in range(start, end)
                     if para.chars[i][0] in own_render.SPACE_CHARS)
        return spaces * condense / 100.0

    cache_breaks = _cache_breaks(para)
    our_breaks = [end for _start, end in call["spans"][:-1]] if call else []

    lines = []
    start = 0
    for index, end in enumerate(cache_breaks + [len(para.chars)]):
        visible = end
        while (visible > start
               and para.chars[visible - 1][0] in own_render.SPACE_CHARS):
            visible -= 1
        seg = para.linesegs[index] if index < len(para.linesegs) else None
        indent = renderer._line_indent(para, index)
        w_visible = width(start, visible)
        trailing_gap = gaps[visible - 1] if visible > start else 0.0
        this_slack = slack(start, visible)
        avail = (column - indent) if column is not None else None
        runs = _runs_in(metrics, para, start, visible)
        punct_installed = sum(row["punct"] for row in runs
                              if row["source"] == "installed"
                              and row["hft"] is None)
        lines.append({
            "line": index,
            "start": start, "visible": visible, "end": end,
            "text": "".join(ch for ch, _cid in para.chars[start:visible]),
            "horzpos": _iattr(seg, "horzpos") if seg is not None else None,
            "horzsize": _iattr(seg, "horzsize") if seg is not None else None,
            "indent": indent,
            "avail": avail,
            "w_visible": w_visible,
            "trailing_gap": trailing_gap,
            "slack": this_slack,
            # The quantity ``_line_fits`` actually compares, and its excess
            # over the box the breaker actually had.
            "w_fit": w_visible + trailing_gap,
            "excess": (w_visible + trailing_gap - avail - this_slack
                       if avail is not None else None),
            "fits_shipped": (renderer._line_fits(
                para, w_visible, avail, this_slack, start, visible,
                trailing_gap) if avail is not None else None),
            "break_offered": (end in opportunities
                              if end < len(para.chars) else True),
            "runs": runs,
            "punct_installed": punct_installed,
            "hft": _hft_terms(renderer, para, start, visible),
        })
        start = end

    our_lines = []
    if call:
        for index, (lo, hi) in enumerate(call["spans"]):
            our_lines.append({
                "line": index, "start": lo, "end": hi,
                "width": call["widths"][index],
                "horzsize": call["horzsize"][index],
                "text": "".join(ch for ch, _cid in para.chars[lo:hi]),
            })

    return {
        "stem": stem, "address": address, "cell": label,
        "align": pr.get("align"), "condense": condense,
        "break_latin": pr.get("break_latin"),
        "break_non_latin": pr.get("break_non_latin"),
        "column_hwp": column,
        "cached_horzsize": [_iattr(seg, "horzsize") for seg in para.linesegs],
        "cached_horzpos": [_iattr(seg, "horzpos") for seg in para.linesegs],
        "cache_breaks": cache_breaks,
        "our_breaks": our_breaks,
        "cached_lines": len(para.linesegs),
        "our_line_count": len(our_lines),
        "lines": lines,
        "our_lines": our_lines,
        "deciding": _deciding_line(cache_breaks, our_breaks),
    }


def _deciding_line(cache_breaks, our_breaks):
    """The first cached line whose end our breaker did not reproduce.

    A greedy breaker's later lines are downstream of its first disagreement,
    so only the first one is evidence about anything.
    """
    for index, cut in enumerate(cache_breaks):
        if index >= len(our_breaks) or our_breaks[index] != cut:
            return index
    return None


def decompose(record):
    """The deciding line's excess, split into the terms measured elsewhere.

    Returns the terms in HWPUNIT plus the verdict: what single quantity would
    have to change, and by how much, for our breaker to put the cached break
    where the cache put it.  A line whose excess is NEGATIVE has no width
    story — the breaker was never offered the cut — and says so.
    """
    index = record["deciding"]
    if index is None:
        return None
    line = record["lines"][index]
    excess = line["excess"]
    punct = line["punct_installed"] * INSTALLED_PUNCT_RESIDUAL_HWP
    budget = own_render.RIGHT_EDGE_TOLERANCE_HWP
    terms = {
        # (a) #307: the last character's own 자간, which _line_fits counts.
        # Reported as the signed amount it contributes to ``w_fit``.
        "trailing_gap": line["trailing_gap"],
        # (b) #307's installed-face punctuation residual, priced per glyph.
        "punct_installed": punct,
        # (c) #292: the measured HFT table against the face metric.
        "hft_measured_delta": line["hft"]["measured_delta"],
        "hft_uncovered_chars": line["hft"]["uncovered"],
        # (d) #301's error budget.
        "budget": budget,
    }
    if excess is None:
        return {"line": index, "terms": terms, "verdict": "no column recorded"}
    if not line["break_offered"]:
        # The cut is not in our opportunity set, so no width closes it: our
        # width for the cache's own line already fits, with room to spare.
        terms["residual"] = None
        return {
            "line": index, "excess": excess, "terms": terms,
            "width_kind": "not width-limited",
            "verdict": (
                f"the cached cut at {line['end']} is not in our "
                f"break_opportunities set; our width for the cache's own line "
                f"is {-excess:.1f} HWPUNIT UNDER the box, so no width term of "
                f"any size reaches it"),
        }
    # A width story: how far the fit test misses by, and what is unexplained
    # once the named terms are taken out of it.
    over_budget = excess - budget
    terms["residual"] = over_budget - punct - terms["hft_measured_delta"]
    return {
        "line": index, "excess": excess, "terms": terms,
        "width_kind": "width-limited",
        "verdict": (
            f"our width must fall by {over_budget:.1f} HWPUNIT "
            f"({over_budget / line['w_fit'] * 100:.2f}% of the line), or the "
            f"budget must rise from {budget:.0f} to {excess:.0f}"),
    }


def _lineseg_control(targets, repo_root, factory):
    """``lineseg_agreement`` over the corpus under one candidate.

    The multi-line break-sequence count summed over the ten forms — the
    number #302 and #307 argued the right-edge budget from — plus whether the
    two ``jumin`` paragraphs #307 named are among the ones it now gets wrong.
    ``lineseg_agreement`` caps its ``disagreements`` listing at 40 rows, so
    that flag is reported alongside the cap rather than as a bare boolean.
    """
    multi = {"scored": 0, "break_sequence_exact": 0, "line_count_exact": 0}
    watched = None
    capped = False
    with factory():
        for path, _reference in targets:
            report = own_render.lineseg_agreement(path, repo_root=repo_root)
            block = report["multiline_paragraphs"]
            multi["scored"] += block["paragraphs_scored"]
            multi["break_sequence_exact"] += \
                block["paragraphs_break_sequence_exact"]
            multi["line_count_exact"] += block["paragraphs_line_count_exact"]
            if Path(path).stem == LINESEG_CONTROL_STEM:
                rows = {row["paragraph"]: row
                        for row in report["disagreements"]}
                watched = {}
                for address in LINESEG_CONTROL_PARAGRAPHS:
                    row = rows.get(address)
                    watched[address] = (
                        "exact" if row is None
                        else f"cache {row['cached']} ours {row['computed']}")
                capped = len(report["disagreements"]) >= 40
    multi["watched"] = watched
    multi["listing_capped"] = capped
    return multi


def score_cells(targets, repo_root, dpi=144):
    """Every candidate, on the two-sided score AND on the three cells.

    The corpus number is ``advance_probe.break_scoreboard`` — the same one a
    fit rule is graded by — so a mechanism that closes a cell and costs the
    corpus is priced in one table with a mechanism that does neither.
    """
    rows = []
    baseline = None
    for name in CELL_CANDIDATE_ORDER:
        _basis, factory = CELL_CANDIDATES[name]
        totals = {"installed": 0, "installed_match": 0, "other": 0,
                  "other_match": 0}
        matched = set()
        cells = {}
        with factory():
            for path, _reference in targets:
                stem = Path(path).stem
                wanted = OVERBROKEN_CELLS.get(stem, {})
                for row in advance_probe.break_scoreboard(
                        path, dpi=dpi, repo_root=repo_root):
                    key = "installed" if row["installed"] else "other"
                    totals[key] += 1
                    if row["match"]:
                        totals[key + "_match"] += 1
                        matched.add((stem, row["address"]))
                    if row["address"] in wanted:
                        cells[(stem, row["address"])] = {
                            "cache": list(row["cache_breaks"]),
                            "ours": list(row["computed_breaks"]),
                            "match": row["match"],
                        }
        row = {"candidate": name, "totals": totals, "cells": cells,
               "matched": matched,
               "lineseg": _lineseg_control(targets, repo_root, factory)}
        if name == "shipped":
            baseline = row
        rows.append(row)
    base = baseline["matched"]
    for row in rows:
        row["regressions"] = sorted(base - row["matched"])
        row["gains"] = sorted(row["matched"] - base)
    for row in rows:
        row.pop("matched")
    return rows


def cell_report(targets, repo_root, dpi=144, score=True):
    records = []
    for path, _reference in targets:
        wanted = OVERBROKEN_CELLS.get(Path(path).stem)
        if not wanted:
            continue
        renderer = advance_probe.BreakRecordingRenderer(
            path, dpi=dpi, repo_root=repo_root, layout_policy="computed")
        renderer.render()
        metrics = advance_probe.OurMetrics(renderer)
        for section in renderer.sections:
            for el in section.iter():
                if _local(el.tag) != "p":
                    continue
                address = renderer.paragraph_index.get(id(el))
                if address not in wanted:
                    continue
                record = _cell_record(renderer, metrics, el, address,
                                      wanted[address], Path(path).stem)
                record["decomposition"] = decompose(record)
                records.append(record)
    out = {"cells": records}
    if score:
        out["candidates"] = score_cells(targets, repo_root, dpi=dpi)
    return out


def _print_cells(report):
    print()
    print("the three cells our breaker over-breaks (#311), line by line")
    print()
    for record in report["cells"]:
        print("=" * 78)
        print(f"{record['stem']} ¶{record['address']} — {record['cell']}")
        print(f"  align={record['align']} condense={record['condense']} "
              f"breakLatinWord={record['break_latin']} "
              f"breakNonLatinWord={record['break_non_latin']}")
        print(f"  text column: ours {record['column_hwp']:.0f}  "
              f"cached @horzsize {record['cached_horzsize']}  "
              f"@horzpos {record['cached_horzpos']}")
        print(f"  cached lines {record['cached_lines']} -> ours "
              f"{record['our_line_count']}   "
              f"cache breaks {record['cache_breaks']}  "
              f"our breaks {record['our_breaks']}")
        print()
        print("  cached lines, our width for exactly those characters")
        print(f"    {'ln':>2}{'chars':>7}{'w_fit':>10}{'trail 자간':>11}"
              f"{'slack':>8}{'indent':>8}{'avail':>9}{'excess':>10}"
              f"{'fits':>6}{'offered':>9}")
        print("    " + "-" * 82)
        for line in record["lines"]:
            avail = "-" if line["avail"] is None else f"{line['avail']:.0f}"
            excess = ("-" if line["excess"] is None
                      else f"{line['excess']:.1f}")
            print(f"    {line['line']:>2}{line['visible'] - line['start']:>7}"
                  f"{line['w_fit']:>10.1f}{line['trailing_gap']:>11.1f}"
                  f"{line['slack']:>8.1f}{line['indent']:>8}{avail:>9}"
                  f"{excess:>10}{str(line['fits_shipped']):>6}"
                  f"{str(line['break_offered']):>9}")
        print()
        for line in record["lines"]:
            print(f"    ln{line['line']} {line['text']!r}")
        print()
        print("  our lines")
        for line in record["our_lines"]:
            print(f"    ln{line['line']} [{line['start']}:{line['end']}] "
                  f"w={line['width']:.1f} {line['text']!r}")
        print()
        print("  runs on the deciding line (advance_probe.OurMetrics)")
        index = record["deciding"]
        rows = record["lines"][index]["runs"] if index is not None else []
        for run in rows:
            print(f"    {run['chars']:>3} chars  declared={run['declared']}"
                  f"  resolved={run['resolved']}  {run['source']}"
                  f"  hft={run['hft']}  {run['size_pt']} pt"
                  f"  ratio={run['ratio']}  자간={run['spacing']}"
                  f"  bold={run['bold']}  punct={run['punct']}")
        print()
        piece = record["decomposition"]
        if piece is None:
            print("  the deciding line: none — our breaker reproduces the "
                  "cache here")
            print()
            continue
        terms = piece["terms"]
        print(f"  the deciding line is ln{piece['line']}, excess "
              f"{piece['excess']:>+.1f} HWPUNIT ({piece['width_kind']})")
        print(f"    (a) trailing 자간 (#307), already counted   "
              f"{terms['trailing_gap']:>+10.1f}")
        print(f"    (b) installed punctuation residual (#307)   "
              f"{terms['punct_installed']:>+10.2f}")
        print(f"    (c) measured HFT table vs face (#292)       "
              f"{terms['hft_measured_delta']:>+10.1f}"
              f"   ({terms['hft_uncovered_chars']} chars on an HFT face the "
              f"table does not carry)")
        print(f"    (d) right-edge budget (#301)                "
              f"{terms['budget']:>+10.1f}")
        if terms["residual"] is None:
            print("    (e) anything else                                  "
                  "   n/a")
        else:
            print(f"    (e) anything else                           "
                  f"{terms['residual']:>+10.1f}")
        print(f"    -> {piece['verdict']}")
        print()
    if not report.get("candidates"):
        return
    print("=" * 78)
    print("the mechanisms the three cells ask for, on the corpus")
    print()
    print(f"{'candidate':<12}{'installed':>12}{'other':>12}{'regress':>9}"
          f"{'gain':>6}  basis")
    print("-" * 100)
    for row in report["candidates"]:
        tot = row["totals"]
        print(f"{row['candidate']:<12}"
              f"{tot['installed_match']:>7} /{tot['installed']:>4}"
              f"{tot['other_match']:>7} /{tot['other']:>4}"
              f"{len(row['regressions']):>9}{len(row['gains']):>6}"
              f"  {CELL_CANDIDATES[row['candidate']][0]}")
    print()
    for row in report["candidates"]:
        print(f"  {row['candidate']}:")
        for (stem, address), cell in sorted(row["cells"].items()):
            print(f"    {stem[:22]:<22} ¶{address:<4} cache={cell['cache']} "
                  f"ours={cell['ours']} match={cell['match']}")
        if row["regressions"]:
            print("    regresses: " + ", ".join(
                f"{stem[:12]} ¶{addr}" for stem, addr in row["regressions"][:8])
                + (" …" if len(row["regressions"]) > 8 else ""))
        control = row.get("lineseg")
        if control:
            print(f"    lineseg_agreement, corpus multi-line: break sequence "
                  f"{control['break_sequence_exact']}/{control['scored']}, "
                  f"line count {control['line_count_exact']}/"
                  f"{control['scored']}"
                  + ("  (jumin listing capped at 40)"
                     if control["listing_capped"] else ""))
            for address, state in sorted((control["watched"] or {}).items()):
                print(f"      {LINESEG_CONTROL_STEM[:5]} ¶{address}: {state}")
    print()


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _f(value, width=9, places=1):
    if value is None:
        return " " * (width - 1) + "-"
    return f"{value:>{width}.{places}f}"


def _print_report(report):
    print()
    print("right-edge fit test — " + RULE_QUESTION)
    print()
    print(f"cached lines measured: {report['lines']}   "
          f"rejected spans: {report['rejected_spans']}   "
          f"forms: {len(report['forms'])}")
    print()
    print("kept excess (ours - (horzsize - indent)) in HWPUNIT, "
          "trailing space dropped")
    print()
    print(f"{'population':<16}{'n':>6}{'min':>9}{'p50':>9}{'p90':>9}"
          f"{'p99':>9}{'max':>9}{'>0':>6}{'on 12':>7}")
    print("-" * 80)
    for label, stats in report["distribution"].items():
        if not stats["n"]:
            print(f"{label:<16}{0:>6}")
            continue
        print(f"{label:<16}{stats['n']:>6}{_f(stats['min'])}"
              f"{_f(stats['p50'])}{_f(stats['p90'])}{_f(stats['p99'])}"
              f"{_f(stats['max'])}{stats['over']:>6}"
              f"{stats['over_on_grid']:>7}")
    print()
    print("the bracket the cache leaves, per candidate")
    print()
    print(f"{'candidate':<10}{'thr':>7}{'kept max':>11}{'rej min':>11}"
          f"{'room':>10}{'kept X':>8}{'rej X':>7}  basis")
    print("-" * 100)
    for name in CANDIDATE_ORDER:
        row = report["bracket"][name]
        print(f"{name:<10}{_f(row['threshold'], 7, 0)}"
              f"{_f(row['kept_max'], 11)}{_f(row['rejected_min'], 11)}"
              f"{_f(row['room'], 10)}{row['kept_wrong']:>8}"
              f"{row['rejected_wrong']:>7}  {CANDIDATE_BASIS[name]}")
    print()
    print("  thr = threshold in HWPUNIT; kept X = cached lines the candidate")
    print("  would have broken; rej X = spans it would have kept.  Both are")
    print("  counted against the cache alone and neither needs a render.")
    print()
    if report["per_form_bracket"]:
        print("per form, kept max / rejected min")
        print()
        header = f"{'form':<14}"
        for name in CANDIDATE_ORDER:
            header += f"{name:>19}"
        print(header)
        print("-" * len(header))
        for form in report["forms"]:
            line = f"{form:<14}"
            for name in CANDIDATE_ORDER:
                row = report["per_form_bracket"][form][name]
                line += (f"{_f(row['kept_max'], 9, 0)}"
                         f" /{_f(row['rejected_min'], 8, 0)}")
            print(line)
        print()
    print("a tolerance of k pen steps on the condense measure: what it costs")
    print()
    print(f"{'k':>4}{'HWPUNIT':>9}{'kept wrong':>12}{'rejected wrong':>16}")
    print("-" * 41)
    for row in report["sweep"]:
        if row["k"] > SWEEP_DENSE_STEPS and row["k"] % 4:
            continue
        print(f"{row['k']:>4}{row['tolerance']:>9.0f}{row['kept_wrong']:>12}"
              f"{row['rejected_wrong']:>16}")
    print()
    over = report["counterexamples"]["kept_over"]
    near = report["counterexamples"]["rejected_near"]
    print(f"every cached line the strict-plus-condense rule calls too wide "
          f"({len(over)}), widest last")
    print()
    for row in over:
        print(f"  {row['excess']:>9.1f}  {row['form']:<12} ¶{row['paragraph']:<5}"
              f" ln {row['line']}  {row['chars']:>3} chars  fill "
              f"{row['fill']:.4f}  trail {row['trailing']:<6}"
              f" condense {row['condense']:<3} "
              f"{'cell' if row['in_cell'] else 'top'}")
    print()
    print(f"the rejected spans a small tolerance would wrongly keep "
          f"({len(near)} within 600 HWPUNIT)")
    print()
    for row in near:
        print(f"  {row['excess']:>9.1f}  {row['form']:<12} ¶{row['paragraph']:<5}"
              f" ln {row['line']}  {row['chars']:>3} chars  {row['align']:<8}"
              f" {'cell' if row['in_cell'] else 'top'}")
    print()
    if report["watched"]:
        print("the two paragraphs #297 named, line by line")
        print()
        header = (f"{'form':<11}{'para':>5}{'ln':>3}{'chars':>6}"
                  f"{'avail':>8}{'trail':>7}")
        for name in CANDIDATE_ORDER:
            header += f"{name:>10}"
        print(header)
        print("-" * len(header))
        for row in report["watched"]:
            line = (f"{row['form']:<11}{row['paragraph']:>5}{row['line']:>3}"
                    f"{row['chars']:>6}{row['avail']:>8.0f}"
                    f"{row['trailing']:>7}")
            for name in CANDIDATE_ORDER:
                line += _f(row["excess"][name], 10)
            print(line)
            if "rejected_excess" in row:
                line = f"{'  (rejected)':<32}{'':>7}"
                for name in CANDIDATE_ORDER:
                    line += _f(row["rejected_excess"][name], 10)
                print(line)
        print()
    if report.get("breaks"):
        print("cached break positions reproduced, the real breaker on real "
              "columns")
        if report.get("standin"):
            print(f"  with the stand-in width rule {report['standin']!r} "
                  f"installed underneath")
        print()
        print(f"{'candidate':<10}{'thr':>7}{'installed':>12}{'other':>12}"
              f"{'regress':>9}{'gain':>6}")
        print("-" * 60)
        for row in report["breaks"]:
            tot = row["totals"]
            regress = ("-" if row["regressions"] is None
                       else str(len(row["regressions"])))
            gain = "-" if row.get("gains") is None else str(len(row["gains"]))
            print(f"{row['candidate']:<10}{row['threshold']:>7.0f}"
                  f"{tot['installed_match']:>7} /{tot['installed']:>4}"
                  f"{tot['other_match']:>7} /{tot['other']:>4}"
                  f"{regress:>9}{gain:>6}")
        print()
        for row in report["breaks"]:
            if row["regressions"]:
                print(f"  {row['candidate']} regresses: "
                      + ", ".join(f"{form} ¶{addr}"
                                  for form, addr in row["regressions"][:8]))
            if row.get("gains"):
                print(f"  {row['candidate']} gains:     "
                      + ", ".join(f"{form} ¶{addr}"
                                  for form, addr in row["gains"][:8]))
        print()


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hwpx", nargs="?", help="one .hwpx form")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form")
    parser.add_argument("--breaks", action="store_true",
                        help="also run the real breaker under each candidate")
    parser.add_argument("--cells", action="store_true",
                        help="the three cells #311 found our breaker "
                             "over-breaking, line by line, with the excess "
                             "decomposed and the mechanisms they ask for "
                             "scored on the corpus")
    parser.add_argument("--no-cell-score", action="store_true",
                        help="with --cells, skip the corpus-wide candidate "
                             "score (the cell tables alone, no renders)")
    parser.add_argument("--standin", metavar="VARIANT",
                        help="install one hft_width_table stand-in width rule "
                             "underneath (e.g. table+pen), so the fit test is "
                             "asked about CORRECTED widths")
    parser.add_argument("--tolerance", type=int, metavar="K",
                        help="score the tol12 candidate at exactly K pen "
                             "steps (K x 12 HWPUNIT) instead of the k the "
                             "bracket picks")
    parser.add_argument("--dpi", type=int, default=144,
                        help="dpi for --breaks (default 144)")
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
    stack = contextlib.ExitStack()
    if args.standin:
        import hft_width_table
        stack.enter_context(hft_width_table.variant(args.standin))
    with stack:
        for path, _reference in targets:
            for rec in probe_form(path, repo_root=repo_root):
                rec["form"] = labels[path.stem]
                rec["stem"] = path.stem
                records.append(rec)

    brackets = {name: bracket(records, name) for name in CANDIDATE_ORDER}
    if args.tolerance is not None:
        forced = args.tolerance * PEN_GRID_HWP
        row = brackets["tol12"]
        row["threshold"] = forced
        row["k"] = args.tolerance
        excess, _ = CANDIDATES["tol12"]
        row["kept_wrong"] = sum(1 for rec in records if excess(rec) > forced)
        row["rejected_wrong"] = sum(
            1 for rec in records
            if rec["rejected"] is not None and excess(rec["rejected"]) <= forced)
    per_form = {}
    for form in sorted(labels.values()):
        rows = [rec for rec in records if rec["form"] == form]
        per_form[form] = {name: bracket(rows, name)
                          for name in CANDIDATE_ORDER}

    report = {
        "question": RULE_QUESTION,
        "forms": sorted(labels.values()),
        "standin": args.standin,
        "lines": len(records),
        "rejected_spans": sum(1 for rec in records
                              if rec["rejected"] is not None),
        "distribution": excess_distribution(records),
        "bracket": brackets,
        "per_form_bracket": per_form,
        "alignments": alignment_table(records),
        "sweep": tolerance_sweep(records),
        "counterexamples": boundary_counterexamples(records),
        "watched": watched_rows(records, labels),
    }
    if args.breaks:
        report["breaks"] = break_report(targets, repo_root, brackets,
                                        standin=args.standin, dpi=args.dpi)
    if args.cells:
        report["cells"] = cell_report(targets, repo_root, dpi=args.dpi,
                                      score=not args.no_cell_score)
    if not args.no_text:
        _print_report(report)
        if args.cells:
            _print_cells(report["cells"])
    if args.json:
        payload = {"report": report}
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                       default=_jsonable) + "\n",
            encoding="utf-8")
    return 0


def _jsonable(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(repr(value))


if __name__ == "__main__":
    raise SystemExit(main())
