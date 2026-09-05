#!/usr/bin/env python3
"""Bracket Hancom's page-bottom fit test against the cached layout.

The flow pass in ``own_render.py`` decides whether one more line still fits
above the bottom of the body box.  Which part of the line box that test has to
clear is not written down in OWPML: ``hp:lineseg`` records ``vertpos``,
``vertsize``, ``textheight``, ``baseline`` and ``spacing``, and any of those
combinations is a candidate for the extent Hancom itself measures.

This script does not guess.  It reads the *cached* layout — the seats Hancom
wrote into the file — and, at every page break the cache contains, reports two
numbers per candidate measure:

  - **kept**: how far the last line the cache left on the page overhangs
    ``usable_height`` under that measure.  A candidate is refuted the moment
    a kept line overhangs it, because Hancom kept a line the candidate
    rejects.
  - **rejected**: how far the first line the cache moved to the next page
    *would* have overhung had it stayed where the previous line's advance put
    it.  A candidate is refuted the moment a rejected line does NOT overhang
    it, because Hancom rejected a line the candidate accepts.

The two together bracket the rule: ``max(kept) < the boundary <= min(rejected)``
for whichever measure survives.  Breaks inside one paragraph (``hp:lineseg``
records of one paragraph on two pages) are reported separately from breaks
between paragraphs, because only the first kind is certainly the fit test —
a break between paragraphs can also be a hard break, a ``keepWithNext`` push
or a column change.

Usage::

    python engine/scripts/page_fit_probe.py --corpus
    python engine/scripts/page_fit_probe.py path/to/doc.hwpx --json out.json
    python engine/scripts/page_fit_probe.py --corpus --offset-scan
    python engine/scripts/page_fit_probe.py --corpus --scan-all

``--scan-all`` drops the page-break structure the bracket is built out of.
The bracket can only speak about a page that ENDS, it was measured on
top-level paragraphs, and it discarded breaks inside a table cell and pages
carrying an anchored object.  The scan instead walks every cached
``hp:lineseg`` the cache path seats — in a cell as well as at the top level,
the former converted to page coordinates through the cell's own seat — and
reports the top tail of the overhang distribution directly, plus the
reference PDF's ink for each line in it.

``--offset-scan`` asks the further question the bracket cannot.  The bracket
takes ``usable_height`` as given, and that number is DERIVED — if the
derivation is short, every overhang printed above is off by one constant.  The
scan varies that constant and reports, per form and jointly, the offsets at
which no kept line is refused and no moved line is accepted.

Deliberately a separate script rather than a ``--page-fit`` mode on
``layout_divergence.py``: this reads the cached seats alone and never renders
either path, so it cannot perturb a field that tool already reports.  The
synthetic counterpart, which manufactures the ambiguous band the corpus does
not contain, is ``tests/corpus/render-check/measure_page_fit_probe.py``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402
from own_render import _iattr, _kids, _local  # noqa: E402


# The measures a page-bottom fit test could plausibly use, each as the offset
# added to the line's own ``vertpos`` before the comparison with
# ``usable_height``.  ``vertsize`` is what the flow pass used before #255;
# ``baseline`` is what it uses now (docs/research/line-fit-rule.md).
def candidate_measures(seg):
    """``{name: offset}`` — what each candidate adds to ``vertpos``."""
    vertsize = _iattr(seg, "vertsize")
    textheight = _iattr(seg, "textheight") or vertsize
    baseline = _iattr(seg, "baseline") or int(
        round(own_render.BASELINE_RATIO * textheight))
    spacing = _iattr(seg, "spacing")
    return {
        "top": 0,
        "vertsize_minus_spacing": max(0, vertsize - spacing),
        "half_vertsize": vertsize // 2,
        "baseline": baseline,
        "textheight": textheight,
        "vertsize": vertsize,
        "vertsize_plus_spacing": vertsize + spacing,
    }


MEASURE_ORDER = [
    "top",
    "vertsize_minus_spacing",
    "half_vertsize",
    "baseline",
    "textheight",
    "vertsize",
    "vertsize_plus_spacing",
]


def seg_facts(seg):
    vertsize = _iattr(seg, "vertsize")
    textheight = _iattr(seg, "textheight") or vertsize
    return {
        "vertpos": _iattr(seg, "vertpos"),
        "vertsize": vertsize,
        "textheight": textheight,
        "baseline": _iattr(seg, "baseline") or None,
        "spacing": _iattr(seg, "spacing"),
        "horzsize": _iattr(seg, "horzsize"),
    }


def _has_text(para, lo, hi):
    """Whether linesegs ``[lo, hi)`` of ``para`` carry any character.

    Through the paragraph's cell map: ``textpos`` counts cells an inline
    control occupies and ``chars`` has no entry for.
    """
    spans = para.lineseg_spans()
    start = spans[lo][0]
    end = spans[hi][0] if hi < len(spans) else len(para.chars)
    return any(ch.strip() for ch, _ in para.chars[start:end])


def _para_has_inline_table(para):
    return any(name == "tbl" for _idx, name, _el, _cp in para.objects)


def _has_floating_object(para):
    """Whether this paragraph anchors an object that floats out of the flow.

    An anchored object takes room on the page that NO ``hp:lineseg`` records,
    so a page holding one can be full while its deepest cached line sits near
    the top.  Every such page has to leave the rejected-side evidence: the
    room the moved line was refused is not measurable from the cache.
    """
    return any(record[3] for record in para.object_at.values())


def _break_flags(para):
    """The block-level instructions that break a page WITHOUT the fit test."""
    pr = para.para_pr or {}
    return {
        "page_break_before": bool(_iattr(para.el, "pageBreak")
                                  or pr.get("page_break_before")),
        "column_break": bool(_iattr(para.el, "columnBreak")),
        "keep_with_next": bool(pr.get("keep_with_next")),
        "keep_lines": bool(pr.get("keep_lines")),
        "widow_orphan": bool(pr.get("widow_orphan")),
        "margin_prev": pr.get("margin_prev", 0),
        "margin_next": pr.get("margin_next", 0),
    }


def classify(seg_info, has_text, usable):
    """Which of three shapes this line is, because only one is a text line.

    ``taller_than_page`` — the line's own box exceeds the whole body box, so
    no fit test can ever accept it and ``_place_block``'s ``cursor > 0`` guard
    places it regardless (``own_render.py``'s "a block taller than a page
    splits wherever it is put").  ``empty`` — the line carries no character,
    so it draws no ink and nothing about it is evidence for where ink is
    allowed to sit.  ``text`` — everything else, and the only class a
    page-bottom fit rule is about.
    """
    if seg_info["vertsize"] > usable:
        return "taller_than_page"
    if not has_text:
        return "empty"
    return "text"


def cached_pages(renderer, section):
    """``[[(para, lo, hi)]]`` — the cache's page groups for one section.

    A re-implementation of ``own_render.paginate``'s restart rule that keeps
    the *lineseg range* each page holds, which ``paginate`` itself discards
    into ``Paragraph.page_run`` views.  Same two clauses, same quarter-page
    floor, so the page split here is the one the renderer draws.
    """
    renderer._current_section = section
    usable = max(1, renderer.page_geometry()["usable_height"])
    pages = []
    current = []
    prev_first = -1
    prev_bottom = -1
    for order, el in enumerate(_kids(renderer.sections[section], "p")):
        para = own_render.Paragraph(el, renderer.defs["para_pr"])
        para._probe_order = order
        runs = para.page_runs()
        if para.linesegs:
            first = _iattr(para.linesegs[0], "vertpos")
            last = para.linesegs[-1]
            bottom = _iattr(last, "vertpos") + _iattr(last, "vertsize")
            restart = (first < prev_first
                       or (prev_bottom - first) > usable // 4)
            if restart and current:
                pages.append(current)
                current = []
            prev_first = _iattr(para.linesegs[runs[-1][0]], "vertpos")
            prev_bottom = bottom
        if len(runs) == 1:
            current.append((para, runs[0][0], runs[0][1]))
            continue
        for index, (lo, hi) in enumerate(runs):
            if index:
                pages.append(current)
                current = []
            current.append((para, lo, hi))
    if current or not pages:
        pages.append(current)
    return pages


def break_events(renderer, section, usable):
    """One record per cached page break, with both sides measured."""
    pages = cached_pages(renderer, section)
    events = []
    for page_index in range(len(pages) - 1):
        here = pages[page_index]
        nxt = pages[page_index + 1]
        seated = [(p, lo, hi) for (p, lo, hi) in here if p.linesegs]
        after = [(p, lo, hi) for (p, lo, hi) in nxt if p.linesegs]
        if not seated or not after:
            continue
        last_para, last_lo, last_hi = seated[-1]
        next_para, next_lo, _next_hi = after[0]
        inside = last_para is next_para
        last_seg = last_para.linesegs[last_hi - 1]
        next_seg = next_para.linesegs[next_lo]
        # Where the moved line WOULD have sat had the page kept it: the
        # previous line's own advance, which is the relation the flow pass
        # uses (``vertsize + spacing``, measured across the corpus).
        last_facts = seg_facts(last_seg)
        last_flags = _break_flags(last_para)
        next_flags = _break_flags(next_para)
        # Where the moved line WOULD have sat had the page kept it.  Inside
        # one paragraph that is just the previous line's advance; between two
        # paragraphs the flow pass also opens ``margin_next + margin_prev``
        # between them, and leaving that out understates the would-be top by
        # up to a whole line.
        gap = 0 if inside else (last_flags["margin_next"]
                                + next_flags["margin_prev"])
        would_be_top = (last_facts["vertpos"] + last_facts["vertsize"]
                        + last_facts["spacing"] + gap)
        # The deepest line anywhere on the page, which constrains the rule
        # just as hard as the last one in document order does.
        deepest = None
        for para, lo, hi in seated:
            for index in range(lo, hi):
                seg = para.linesegs[index]
                facts = seg_facts(seg)
                depth = facts["vertpos"] + facts["vertsize"]
                if deepest is None or depth > deepest[0]:
                    deepest = (depth, seg, para, index)
        kept = {name: last_facts["vertpos"] + off - usable
                for name, off in candidate_measures(last_seg).items()}
        deep_facts = seg_facts(deepest[1])
        deep_kept = {name: deep_facts["vertpos"] + off - usable
                     for name, off in candidate_measures(deepest[1]).items()}
        rejected = {name: would_be_top + off - usable
                    for name, off in candidate_measures(next_seg).items()}
        next_facts = seg_facts(next_seg)
        deep_text = _has_text(deepest[2], deepest[3], deepest[3] + 1)
        events.append({
            "section": section,
            "page": page_index,
            "inside_paragraph": inside,
            "usable_height": usable,
            "gap_between": gap,
            "last_para_order": last_para._probe_order,
            "last_lineseg": last_hi - 1,
            "last": last_facts,
            "last_has_text": _has_text(last_para, last_hi - 1, last_hi),
            "last_has_inline_table": _para_has_inline_table(last_para),
            "deepest": deep_facts,
            "deepest_para_order": deepest[2]._probe_order,
            "deepest_class": classify(deep_facts, deep_text, usable),
            "next_para_order": next_para._probe_order,
            "next_lineseg": next_lo,
            "next": next_facts,
            "next_has_text": _has_text(next_para, next_lo, next_lo + 1),
            "next_has_inline_table": _para_has_inline_table(next_para),
            "next_class": classify(
                next_facts, _has_text(next_para, next_lo, next_lo + 1),
                usable),
            "next_forced": (next_flags["page_break_before"]
                            or next_flags["column_break"]),
            "next_flags": next_flags,
            "last_flags": last_flags,
            "next_lineseg_count": len(next_para.linesegs),
            "page_has_floating_object": any(
                _has_floating_object(p) for p, _lo, _hi in seated),
            "next_keep_with_next": next_flags["keep_with_next"],
            "last_keep_with_next": last_flags["keep_with_next"],
            "would_be_top": would_be_top,
            "kept_overhang": kept,
            "deepest_overhang": deep_kept,
            "rejected_overhang": rejected,
        })
    return events, len(pages)


def probe_document(hwpx_path, dpi=own_render.DEFAULT_DPI, repo_root=None):
    """Every cached page break in one document, both sides measured."""
    renderer = own_render.OwnRenderer(hwpx_path, dpi=dpi, repo_root=repo_root)
    out = {"document": str(hwpx_path), "sections": []}
    events = []
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        geo = renderer.page_geometry()
        usable = max(1, geo["usable_height"])
        section_events, page_count = break_events(renderer, section, usable)
        root = renderer.sections[section]
        out["sections"].append({
            "section": section,
            "usable_height": usable,
            "page_height": geo["height"],
            "margin": geo["margin"],
            "cached_pages": page_count,
            "footnotes": sum(1 for e in root.iter()
                             if _local(e.tag) == "footNote"),
            "endnotes": sum(1 for e in root.iter()
                            if _local(e.tag) == "endNote"),
            "headers": sum(1 for e in root.iter()
                           if _local(e.tag) == "header"),
            "footers": sum(1 for e in root.iter()
                           if _local(e.tag) == "footer"),
        })
        events.extend(section_events)
    out["events"] = events
    return out


def _stats(values):
    if not values:
        return None
    return {
        "n": len(values),
        "min": min(values),
        "median": int(statistics.median(values)),
        "max": max(values),
    }


def is_evidence_kept(event):
    """Whether the deepest kept line says anything about the fit rule.

    Only a text line does.  A line taller than the whole body box is placed
    by a guard that never consults the fit test, and an empty line draws no
    ink, so neither can refute a candidate measure.
    """
    return event["deepest_class"] == "text"


def is_evidence_rejected(event):
    """Whether the moved line says anything about the fit rule.

    It does not when the break is forced (``hp:p@pageBreak``,
    ``pageBreakBefore``, ``columnBreak``) or pushed by ``keepWithNext``, when
    the moved unit is taller than a page, when the moved unit is a whole
    inline TABLE — a table that does not fit moves whole
    (``docs/research/table-page-break-rule.md``), so its rejection is the
    table rule speaking, not the line rule — or when the page it was refused
    from holds an anchored object, whose room no ``hp:lineseg`` records.
    """
    return (event["next_class"] == "text"
            and not event["next_forced"]
            and not event["last_keep_with_next"]
            and not event["next_has_inline_table"]
            and not event["page_has_floating_object"])


def summarise(reports):
    """Per-measure kept/rejected brackets across every document probed."""
    total = 0
    inside = 0
    kept_events = []
    rejected_events = []
    classes = {}
    for report in reports:
        for event in report["events"]:
            total += 1
            if event["inside_paragraph"]:
                inside += 1
            classes[event["deepest_class"]] = (
                classes.get(event["deepest_class"], 0) + 1)
            if is_evidence_kept(event):
                kept_events.append(event)
            if is_evidence_rejected(event):
                rejected_events.append(event)
    out = {
        "events": total,
        "inside_paragraph": inside,
        "between_paragraphs": total - inside,
        "deepest_class_counts": classes,
        "kept_evidence": len(kept_events),
        "rejected_evidence": len(rejected_events),
        "measures": {},
    }
    for name in MEASURE_ORDER:
        deep = [e["deepest_overhang"][name] for e in kept_events]
        rej = [e["rejected_overhang"][name] for e in rejected_events]
        out["measures"][name] = {
            "kept": _stats(deep),
            "rejected": _stats(rej),
            # A candidate survives when every kept text line clears the
            # boundary and every rejected text line does not.
            "kept_violations": sum(1 for v in deep if v > 0),
            "rejected_violations": sum(1 for v in rej if v <= 0),
            "consistent": (all(v <= 0 for v in deep)
                           and all(v > 0 for v in rej)),
        }
    return out


def format_report(reports, summary):
    lines = []
    lines.append("cached page breaks per form")
    width = max([len(Path(r["document"]).stem) for r in reports] + [4])
    lines.append(f"{'form':<{width}}  {'usable':>7} {'pages':>5} "
                 f"{'breaks':>6} {'inpara':>6} {'fn':>3} {'hdr':>3}")
    for report in reports:
        stem = Path(report["document"]).stem
        sec = report["sections"][0] if report["sections"] else {}
        breaks = len(report["events"])
        inpara = sum(1 for e in report["events"] if e["inside_paragraph"])
        lines.append(
            f"{stem:<{width}}  {sec.get('usable_height', 0):>7} "
            f"{sum(s['cached_pages'] for s in report['sections']):>5} "
            f"{breaks:>6} {inpara:>6} "
            f"{sum(s['footnotes'] for s in report['sections']):>3} "
            f"{sum(s['headers'] for s in report['sections']):>3}")
    lines.append("")
    lines.append(f"events {summary['events']}  "
                 f"inside-paragraph {summary['inside_paragraph']}  "
                 f"between-paragraphs {summary['between_paragraphs']}")
    lines.append(f"deepest kept line by class {summary['deepest_class_counts']}")
    lines.append(f"kept evidence (text lines) {summary['kept_evidence']}  "
                 f"rejected evidence (unforced text lines, no inline table) "
                 f"{summary['rejected_evidence']}")
    if not summary["kept_evidence"] and not summary["rejected_evidence"]:
        lines.append("no cached page break carries fit-test evidence "
                     "— no bracket")
        return "\n".join(lines)
    lines.append("")
    lines.append("overhang against usable_height, HWPUNIT "
                 "(kept: deepest text line the page kept; "
                 "rejected: first text line it moved, had it stayed)")
    head = (f"{'measure':<24} {'kept_min':>9} {'kept_med':>9} "
            f"{'kept_MAX':>9} {'rej_MIN':>9} {'rej_med':>9} {'rej_max':>9} "
            f"{'k!':>3} {'r!':>3} {'fits':>5}")
    lines.append(head)
    for name in MEASURE_ORDER:
        row = summary["measures"][name]
        kept = row["kept"] or {"min": 0, "median": 0, "max": 0}
        rej = row["rejected"] or {"min": 0, "median": 0, "max": 0}
        lines.append(
            f"{name:<24} {kept['min']:>9} {kept['median']:>9} "
            f"{kept['max']:>9} {rej['min']:>9} {rej['median']:>9} "
            f"{rej['max']:>9} {row['kept_violations']:>3} "
            f"{row['rejected_violations']:>3} "
            f"{'yes' if row['consistent'] else 'no':>5}")
    lines.append("")
    lines.append("k! = kept lines the measure would have refused "
                 "(refutes it); r! = moved lines it would have kept")
    lines.append("the bracket: kept_MAX < the boundary <= rej_MIN, "
                 "for a measure with k!=0 and r!=0")
    return "\n".join(lines)


# -- the offset scan ------------------------------------------------------
#
# The bracket above takes ``usable_height`` as given.  It is a DERIVED number
# — ``height - top - bottom - header - footer`` in ``own_render.page_geometry``
# — and if that derivation is short, every overhang the probe prints is off by
# the same constant.  The scan below varies that constant and asks which
# offsets leave the fit rule consistent.
#
# Only the fit boundary moves.  The cached page grouping and the
# taller-than-a-page classification are computed once, at the derivation the
# renderer actually uses, and held fixed: the page split is a fact read out of
# the cache rather than something the offset should be allowed to reshuffle,
# and letting the guard flip would let a large offset invent kept evidence out
# of a multi-page table's whole-table ``vertsize``.  So every overhang here is
# exactly ``raw_overhang - offset``, which is linear and needs no re-probe.

SCAN_MEASURES = ("vertsize", "baseline")


def form_evidence(report, measures=SCAN_MEASURES):
    """``{measure: (kept[], rejected[])}`` for one document, at offset 0."""
    out = {}
    for name in measures:
        kept = [e["deepest_overhang"][name] for e in report["events"]
                if is_evidence_kept(e)]
        rej = [e["rejected_overhang"][name] for e in report["events"]
               if is_evidence_rejected(e)]
        out[name] = (kept, rej)
    return out


def evidence_band(kept, rejected):
    """``(lo, hi)`` — the offsets at which this evidence gives k!=0 and r!=0.

    Every kept line has to clear the boundary (``v - offset <= 0``, so
    ``offset >= max(kept)``) and every rejected line has to miss it
    (``v - offset > 0``, so ``offset < min(rejected)``).  The band is the
    half-open interval ``[max(kept), min(rejected))``; ``None`` on a side
    means that side carries no evidence and does not bound the offset.
    """
    lo = max(kept) if kept else None
    hi = min(rejected) if rejected else None
    return lo, hi


def _band_text(lo, hi):
    left = "-inf" if lo is None else str(lo)
    right = "+inf" if hi is None else str(hi)
    empty = "" if lo is None or hi is None or lo < hi else "  EMPTY"
    return f"[{left}, {right}){empty}"


def _in_band(offset, lo, hi):
    return ((lo is None or offset >= lo) and (hi is None or offset < hi))


def named_offsets(report):
    """The spec-shaped candidates, from this document's own margins.

    Each is a term ``page_geometry`` currently subtracts from the body box.
    Adding it back is the derivation rule "this margin is not part of the
    body after all"; ``footer_if_no_footer`` is the narrower reading that the
    footer band only exists when the section declares an ``hp:footer``.
    """
    out = {"zero": 0}
    header = footer = 0
    no_footer = True
    no_header = True
    for sec in report["sections"]:
        m = sec.get("margin") or {}
        header = max(header, m.get("header", 0))
        footer = max(footer, m.get("footer", 0))
        no_footer = no_footer and not sec.get("footers")
        no_header = no_header and not sec.get("headers")
    out["header"] = header
    out["footer"] = footer
    out["header_plus_footer"] = header + footer
    out["footer_if_no_footer"] = footer if no_footer else 0
    out["header_if_no_header"] = header if no_header else 0
    return out


def offset_scan(reports, measures=SCAN_MEASURES,
                lo=-1000, hi=1500, step=50):
    """Which offsets to ``usable_height`` leave the fit rule consistent."""
    grid = list(range(lo, hi + 1, step))
    per_form = {}
    joint = {}
    for name in measures:
        joint_kept = []
        joint_rej = []
        for report in reports:
            stem = Path(report["document"]).stem
            kept, rej = form_evidence(report, (name,))[name]
            joint_kept.extend(kept)
            joint_rej.extend(rej)
            band_lo, band_hi = evidence_band(kept, rej)
            entry = per_form.setdefault(stem, {"named": named_offsets(report),
                                               "measures": {}})
            entry["measures"][name] = {
                "kept_n": len(kept),
                "rejected_n": len(rej),
                "band": [band_lo, band_hi],
                "grid": [{"offset": off,
                          "k": sum(1 for v in kept if v - off > 0),
                          "r": sum(1 for v in rej if v - off <= 0)}
                         for off in grid],
            }
        band_lo, band_hi = evidence_band(joint_kept, joint_rej)
        joint[name] = {
            "kept_n": len(joint_kept),
            "rejected_n": len(joint_rej),
            "band": [band_lo, band_hi],
            "grid": [{"offset": off,
                      "k": sum(1 for v in joint_kept if v - off > 0),
                      "r": sum(1 for v in joint_rej if v - off <= 0)}
                     for off in grid],
        }
    return {"grid": grid, "per_form": per_form, "joint": joint,
            "measures": list(measures)}


def top_refuters(reports):
    """Every moved line whose would-be TOP was already inside the body box.

    These are the events that refute the ``top`` candidate outright: Hancom
    pushed a line to the next page whose own top edge, at the seat the
    previous line's advance gives it, still sat above ``usable_height``.  They
    are also the events that bound the offset scan from above hardest, because
    an offset that grows the body box grows the room they were refused.
    """
    out = []
    for report in reports:
        stem = Path(report["document"]).stem
        for event in report["events"]:
            if not is_evidence_rejected(event):
                continue
            if event["rejected_overhang"]["top"] > 0:
                continue
            out.append({
                "form": stem,
                "section": event["section"],
                "page": event["page"],
                "next_para_order": event["next_para_order"],
                "usable_height": event["usable_height"],
                "would_be_top": event["would_be_top"],
                "inside_by": -event["rejected_overhang"]["top"],
                "vertsize_overhang": event["rejected_overhang"]["vertsize"],
                "baseline_overhang": event["rejected_overhang"]["baseline"],
            })
    return out


def format_offset_scan(scan, tops, band=None):
    lines = []
    lines.append("")
    lines.append("offset scan: the offset is added to usable_height, so "
                 "every overhang shifts by -offset")
    lines.append("page grouping and the taller-than-a-page guard stay at "
                 "the renderer's own derivation")
    width = max([len(s) for s in scan["per_form"]] + [4])
    for name in scan["measures"]:
        lines.append("")
        lines.append(f"measure {name}: the offsets giving k!=0 and r!=0")
        lines.append(f"{'form':<{width}}  {'kept':>4} {'rej':>4}  "
                     f"{'band [lo, hi)':<26} named offsets inside the band")
        for stem in sorted(scan["per_form"]):
            entry = scan["per_form"][stem]
            row = entry["measures"][name]
            lo, hi = row["band"]
            inside = [f"{k}={v}" for k, v in entry["named"].items()
                      if _in_band(v, lo, hi)]
            lines.append(f"{stem:<{width}}  {row['kept_n']:>4} "
                         f"{row['rejected_n']:>4}  "
                         f"{_band_text(lo, hi):<26} "
                         f"{', '.join(inside) if inside else '-'}")
        jlo, jhi = scan["joint"][name]["band"]
        lines.append(f"{'JOINT':<{width}}  "
                     f"{scan['joint'][name]['kept_n']:>4} "
                     f"{scan['joint'][name]['rejected_n']:>4}  "
                     f"{_band_text(jlo, jhi):<26}")
        if band is not None:
            blo, bhi = band
            ok = ((jlo is None or blo >= jlo)
                  and (jhi is None or bhi <= jhi))
            lines.append(f"the supplied band [{blo}, {bhi}) is "
                         f"{'inside' if ok else 'NOT inside'} the joint band")
        lines.append("")
        lines.append(f"{'offset':>7} {'k!':>4} {'r!':>4}  (joint, "
                     f"{step_note(scan)})")
        for cell in scan["joint"][name]["grid"]:
            flag = "  <- consistent" if not cell["k"] and not cell["r"] else ""
            lines.append(f"{cell['offset']:>7} {cell['k']:>4} "
                         f"{cell['r']:>4}{flag}")
    lines.append("")
    lines.append("moved lines whose would-be TOP was already inside the "
                 "body box (these refute the `top` candidate)")
    if not tops:
        lines.append("  none")
    else:
        lines.append(f"  {'form':<{width}} {'page':>5} {'para':>6} "
                     f"{'usable':>7} {'would_be_top':>13} {'inside_by':>10} "
                     f"{'vertsize':>9} {'baseline':>9}")
        for rec in tops:
            lines.append(
                f"  {rec['form']:<{width}} {rec['page']:>5} "
                f"{rec['next_para_order']:>6} {rec['usable_height']:>7} "
                f"{rec['would_be_top']:>13} {rec['inside_by']:>10} "
                f"{rec['vertsize_overhang']:>9} "
                f"{rec['baseline_overhang']:>9}")
    return "\n".join(lines)


def step_note(scan):
    grid = scan["grid"]
    if len(grid) < 2:
        return "single offset"
    return f"{grid[0]}..{grid[-1]} step {grid[1] - grid[0]}"


# -- the body box against the reference PDF -------------------------------
#
# The cache says where Hancom SEATED a line.  The reference PDF says where
# Hancom DREW it, and on a form whose page is one full-page table that is a
# far tighter measurement of the body box than any lineseg: a table sized to
# the room available pins the bottom of that room to the width of its own
# ruling.  So this mode reads the deepest *ruling* (vector) and the deepest
# text on every reference page and reports both against the derived body box.
#
# Vector and text are reported apart on purpose.  A Korean government form
# prints its paper-spec line in the bottom MARGIN from a page-anchored object,
# which is text far below any body box and evidence about nothing; the table
# ruling has no such escape.

HWPUNIT_PER_PT = own_render.HWPUNIT_PER_INCH / 72.0


def _require_fitz():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "--reference-ink needs PyMuPDF (fitz), the same reader "
            "render_scoreboard.py uses") from exc
    return fitz


def reference_ink(hwpx_path, pdf_path, repo_root=None):
    """Deepest ruling and deepest text per reference page, in HWPUNIT."""
    fitz = _require_fitz()
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    renderer._current_section = 0
    geo = renderer.page_geometry()
    body_top = geo["body_top"]
    body_bottom = body_top + geo["usable_height"]
    margin_bottom = geo["height"] - geo["margin"]["bottom"]
    pages = []
    with fitz.open(pdf_path) as document:
        for page in document:
            vec_lo = vec_hi = None
            for drawing in page.get_drawings():
                rect = drawing["rect"]
                lo, hi = rect.y0 * HWPUNIT_PER_PT, rect.y1 * HWPUNIT_PER_PT
                vec_lo = lo if vec_lo is None else min(vec_lo, lo)
                vec_hi = hi if vec_hi is None else max(vec_hi, hi)
            txt_lo = txt_hi = None
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        lo = span["bbox"][1] * HWPUNIT_PER_PT
                        hi = span["bbox"][3] * HWPUNIT_PER_PT
                        txt_lo = lo if txt_lo is None else min(txt_lo, lo)
                        txt_hi = hi if txt_hi is None else max(txt_hi, hi)
            pages.append({
                "vector_top": None if vec_lo is None else int(round(vec_lo)),
                "vector_bottom": None if vec_hi is None else int(round(vec_hi)),
                "text_top": None if txt_lo is None else int(round(txt_lo)),
                "text_bottom": None if txt_hi is None else int(round(txt_hi)),
            })
    return {
        "document": str(hwpx_path),
        "reference": str(pdf_path),
        "body_top": body_top,
        "body_bottom": body_bottom,
        "margin_bottom": margin_bottom,
        "pages": pages,
    }


def format_reference_ink(records):
    lines = ["", "reference-PDF ink against the derived body box, HWPUNIT",
             "(vector = ruling and rules; text = glyph boxes, which include "
             "a form's paper-spec line in the bottom margin)"]
    width = max([len(Path(r["document"]).stem) for r in records] + [4])
    lines.append(f"{'form':<{width}} {'pg':>3} {'body_top':>8} "
                 f"{'body_bot':>8} {'vec_top':>8} {'vec_bot':>8} "
                 f"{'v-btop':>7} {'v-bbot':>7} {'t-bbot':>7} {'v-marg':>7}")
    tightest = None
    for rec in records:
        stem = Path(rec["document"]).stem
        for index, page in enumerate(rec["pages"]):
            vt = page["vector_top"]
            vb = page["vector_bottom"]
            tb = page["text_bottom"]
            if vb is None:
                lines.append(f"{stem:<{width}} {index:>3} "
                             f"{rec['body_top']:>8} {rec['body_bottom']:>8} "
                             f"{'-':>8} {'-':>8} {'-':>7} {'-':>7} "
                             f"{'-' if tb is None else tb - rec['body_bottom']:>7} "
                             f"{'-':>7}")
                continue
            delta = vb - rec["body_bottom"]
            if tightest is None or abs(delta) < abs(tightest[0]):
                tightest = (delta, stem, index)
            lines.append(
                f"{stem:<{width}} {index:>3} {rec['body_top']:>8} "
                f"{rec['body_bottom']:>8} {vt:>8} {vb:>8} "
                f"{vt - rec['body_top']:>+7} {delta:>+7} "
                f"{'-' if tb is None else format(tb - rec['body_bottom'], '+'):>7} "
                f"{vb - rec['margin_bottom']:>+7}")
    if tightest is not None:
        lines.append("")
        lines.append(f"tightest ruling against the derived body bottom: "
                     f"{tightest[0]:+} HWPUNIT on {tightest[1]} "
                     f"page {tightest[2]}")
        lines.append("an offset to usable_height has to survive that number: "
                     "it moves the body bottom and the ruling does not move "
                     "with it")
    return "\n".join(lines)


# -- the direct scan: every cached line, anywhere ------------------------
#
# The bracket above is built out of page BREAKS, and a break is a structure:
# it needs a page that ends and a page that starts, it was measured on
# top-level paragraphs only, and #256 threw away the breaks that happen
# inside a table cell or on a page carrying an anchored object.  Two whole
# populations never got looked at, and either could hold the witness the
# corpus was missing — a line Hancom SEATED across the bottom of the body
# box.
#
# So this mode drops the event structure entirely.  It walks every cached
# ``hp:lineseg`` the renderer draws, top-level and inside a table cell, and
# asks one question of each: where does its box end relative to the body
# bottom?  A cell lineseg's ``vertpos`` is measured from its own cell's text
# origin, so the answer needs the cell's seat, and the only honest source for
# that is the renderer's own cache-path placement — the table's origin from
# ``_render_floating``/``_object_origin``, the row offset from
# ``_table_tracks``, the inset and the vertical alignment from
# ``_render_cell_content``.  ``SeatScanner`` therefore rederives none of it:
# it renders the document under the cache policy and records the origin every
# ``_render_paragraphs`` call is handed.
#
# The ``shift`` ``_render_paragraphs`` accumulates for a relaid-out paragraph
# is deliberately NOT applied.  That number is this renderer's correction to
# its own reflow; the seat under measurement is Hancom's, which is the
# container origin plus the cached ``vertpos`` and nothing else.

#: A line is in the top tail when its box, under ``vertsize``, ends within
#: this much of the body bottom.  Wide enough to hold #256's tightest kept
#: line so the scan can be read against that number directly.
SCAN_TAIL_FLOOR = -300

#: A moved line is a near miss when it would have overhung by less than this.
SCAN_NEAR_MISS_CEILING = 300

#: The measure the tail and the near-miss list are SORTED by.  Not a claim
#: that it is the right one — it is the plainest reading of "the line's box"
#: and the one the research question is phrased in.
SCAN_SORT_MEASURE = "vertsize"


def line_overhangs(rel_top, seg, usable):
    """``{measure: overhang}`` for a line seated ``rel_top`` below the body top.

    The overhang is what the line's box does to the body bottom under each
    candidate: positive means the box crosses it.
    """
    return {name: rel_top + off - usable
            for name, off in candidate_measures(seg).items()}


def _line_text(para, index):
    """The characters one cached lineseg carries, through the cell map.

    The same slice ``_has_text`` counts and ``_render_cached_lines`` draws:
    ``hp:lineseg@textpos`` counts CELLS, so the range has to go through
    ``lineseg_spans`` before it indexes ``chars``.
    """
    spans = para.lineseg_spans()
    if index >= len(spans):
        return ""
    start = spans[index][0]
    end = (spans[index + 1][0] if index + 1 < len(spans)
           else len(para.chars))
    return "".join(ch for ch, _cp in para.chars[start:end])


def scan_evidence_reason(record):
    """Why this line says nothing about the fit rule, or ``None``.

    The kept side of #256 already excluded an empty line (no ink) and a line
    taller than the whole body box (placed by a guard that never runs the fit
    test).  The scan adds one exclusion the event pass never needed: a line
    inside a table Hancom is not PERMITTED to split moves with its table or
    not at all, so its seat is the table rule speaking
    (``docs/research/table-page-break-rule.md``) and not the line rule.
    """
    if not record["on_sheet"]:
        return "seat off the sheet (a wild anchor offset)"
    if record["line_class"] == "empty":
        return "empty line"
    if record["line_class"] == "taller_than_page":
        return "line taller than the body box"
    if record["container"] == "cell" and not record["table_may_split"]:
        return "cell of a table that may not split"
    return None


def seat_on_sheet(rel_top, vertsize, body_top, page_height):
    """Whether this seat's box intersects the sheet at all.

    kstartup's table 36 declares ``hp:pos@vertOffset="4294967083"`` — an
    unsigned wrap of a small negative number, and the same broken POSITION
    ``_place_block``'s wild-``vertOffset`` guard (kstartup's own limit 12)
    already refuses to treat as content.  Its cells' seats land four
    thousand million HWPUNIT down the page, and a scan that measured them
    against the body bottom would report the largest overhang in the corpus
    from a coordinate no page has.  A seat whose box misses the paper
    entirely is not a fit-test decision; it is a broken offset.
    """
    top = body_top + rel_top
    return top + vertsize > 0 and top < page_height


def scan_tail(records, floor=SCAN_TAIL_FLOOR, measure=SCAN_SORT_MEASURE):
    """Every scanned line whose box ends within ``floor`` of the body bottom.

    A seat that misses the sheet is dropped rather than listed: it would
    otherwise fill the whole tail with one broken anchor offset and hide the
    lines the tail exists to show.  The count survives in the exclusion
    tally.
    """
    return sorted((r for r in records
                   if r["on_sheet"] and r["overhang"][measure] > floor),
                  key=lambda r: -r["overhang"][measure])


def scan_bracket(records, rejected, kept_events=()):
    """``{measure: {kept_max, rejected_min, …}}`` after the direct scan.

    The kept side is now every scanned line that carries evidence, not the
    deepest line of each page that happens to end in a break; the rejected
    side is unchanged, because a line that was never seated cannot be
    scanned and only the event pass knows about it.

    ``kept_events`` folds the event pass's own kept side back in, and it is
    not redundant.  The two readings differ on one line in this corpus:
    the event pass groups pages by the cache's raw ``vertpos`` restarts,
    while the scan reports the seat the cache PATH draws, and #278's
    anchor-overflow fix rebases one kstartup page between the two.  Neither
    reading owns that line, so ``union_max`` takes the larger — the bound a
    measure has to clear under either.
    """
    kept = [r for r in records if r["evidence"]]
    plain = [r for r in kept if not r["inline_table"]]
    out = {}
    for name in MEASURE_ORDER:
        keeps = [r["overhang"][name] for r in kept]
        texts = [r["overhang"][name] for r in plain]
        events = [e["deepest_overhang"][name] for e in kept_events]
        rejects = [e["rejected_overhang"][name] for e in rejected]
        both = keeps + events
        out[name] = {
            "kept_n": len(keeps),
            "kept_max": max(keeps) if keeps else None,
            "text_n": len(texts),
            "text_max": max(texts) if texts else None,
            "event_n": len(events),
            "event_max": max(events) if events else None,
            "union_max": max(both) if both else None,
            "rejected_n": len(rejects),
            "rejected_min": min(rejects) if rejects else None,
            "kept_violations": sum(1 for v in both if v > 0),
            "rejected_violations": sum(1 for v in rejects if v <= 0),
            "consistent": (all(v <= 0 for v in both)
                           and all(v > 0 for v in rejects)),
        }
    return out


def near_misses(reports, ceiling=SCAN_NEAR_MISS_CEILING,
                measure=SCAN_SORT_MEASURE):
    """Every line the cache MOVED whose would-be overhang was under ``ceiling``.

    The mirror of the tail: a moved line this close to the boundary bounds
    the rule from above as hard as a kept line bounds it from below, and a
    moved line whose would-be overhang is at or below zero would be a second
    public witness — of the opposite sign.
    """
    out = []
    for report in reports:
        stem = Path(report["document"]).stem
        for event in report["events"]:
            value = event["rejected_overhang"][measure]
            if value >= ceiling:
                continue
            out.append({
                "form": stem,
                "page": event["page"],
                "para": event["next_para_order"],
                "lineseg": event["next_lineseg"],
                "vertsize": event["next"]["vertsize"],
                "spacing": event["next"]["spacing"],
                "would_be_top": event["would_be_top"],
                "usable": event["usable_height"],
                "evidence": is_evidence_rejected(event),
                "class": event["next_class"],
                "forced": event["next_forced"],
                "keep_with_next": event["last_keep_with_next"],
                "inline_table": event["next_has_inline_table"],
                "anchored_page": event["page_has_floating_object"],
                "overhang": dict(event["rejected_overhang"]),
            })
    return sorted(out, key=lambda r: r["overhang"][measure])


class SeatScanner(own_render.OwnRenderer):
    """Renders under the cache policy and records where every line was seated.

    Four overrides, each of them a place the renderer already knows a
    coordinate this probe would otherwise have to guess:

    * ``_render_paragraphs`` is handed the container origin every cached
      ``vertpos`` in that container is measured from — the body top for a
      top-level page, the cell's text origin (inset and vertical alignment
      included) for a cell;
    * ``_render_table`` names the table a container belongs to and whether
      the flow is drawing it as a split fragment;
    * ``_render_cell_content`` names the row and column;
    * ``_render_floating`` says whether the table is anchored.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: One record per cached lineseg the render placed.
        self.seats = []
        #: ``{(id(hp:p), lineseg index)}`` — a paragraph drawn twice (a split
        #: table's cells are filtered by row, but a guard is cheaper than
        #: proving it) is measured once.
        self._seen = set()
        self._ctx = []
        self._floating = 0
        self._index = None
        #: ``{table index: [(row_from, row_to)]}`` for every table drawn as
        #: more than one fragment.
        self.fragments = {}

    # -- identity ---------------------------------------------------------
    def _indexes(self):
        if self._index is None:
            tbl, para = {}, {}
            for root in self.sections:
                for el in root.iter():
                    name = _local(el.tag)
                    if name == "tbl":
                        tbl[id(el)] = len(tbl)
                    elif name == "p":
                        para[id(el)] = len(para)
            self._index = (tbl, para)
        return self._index

    # -- context ----------------------------------------------------------
    def _render_floating(self, draw, para, origin_hwp, *args, **kwargs):
        self._floating += 1
        try:
            return super()._render_floating(draw, para, origin_hwp,
                                            *args, **kwargs)
        finally:
            self._floating -= 1

    def _render_table(self, draw, tbl, origin_hwp):
        tbl_index, _paras = self._indexes()
        split = self._table_splits.get(id(tbl))
        key = tbl_index.get(id(tbl))
        if split is not None:
            self.fragments.setdefault(key, []).append(tuple(split))
        self._ctx.append({
            "table": key,
            "may_split": self._table_may_split(tbl),
            "anchored": bool(self._floating),
            "fragment": None if split is None else tuple(split),
            "row": None,
            "col": None,
            "valign": None,
        })
        try:
            return super()._render_table(draw, tbl, origin_hwp)
        finally:
            self._ctx.pop()

    def _render_cell_content(self, draw, cell, x0, y0, x1, y1):
        sub = own_render._kid(cell["tc"], "subList")
        valign = (sub.get("vertAlign") if sub is not None else "TOP") or "TOP"
        if self._ctx:
            self._ctx[-1].update({"row": cell["row"], "col": cell["col"],
                                  "valign": valign.upper()})
        try:
            return super()._render_cell_content(draw, cell, x0, y0, x1, y1)
        finally:
            if self._ctx:
                self._ctx[-1].update({"row": None, "col": None,
                                      "valign": None})

    # -- the recording ----------------------------------------------------
    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        base = origin_hwp[1] + block_offset_hwp
        for para in paragraphs:
            self._record_seats(para, base, block_offset_hwp)
        return super()._render_paragraphs(draw, paragraphs, origin_hwp,
                                          avail_w_hwp, block_offset_hwp)

    def _record_seats(self, para, base_hwp, block_offset_hwp=0):
        geo = self.page_geometry()
        usable = max(1, geo["usable_height"])
        body_top = geo["body_top"]
        _tbl, para_index = self._indexes()
        order = para_index.get(id(para.el))
        first, last = (para.rows if para.rows is not None
                       else (0, len(para.linesegs)))
        ctx = self._ctx[-1] if self._ctx else None
        in_cell = ctx is not None and ctx["row"] is not None
        for index in range(first, min(last, len(para.linesegs))):
            key = (id(para.el), index)
            if key in self._seen:
                continue
            self._seen.add(key)
            seg = para.linesegs[index]
            facts = seg_facts(seg)
            rel_top = base_hwp + facts["vertpos"] - body_top
            has_text = _has_text(para, index, index + 1)
            record = {
                "form": self.path.stem,
                "section": self._current_section,
                "page": max(0, (self._page or 1) - 1),
                "para": order,
                "lineseg": index,
                "container": "cell" if in_cell else "top-level",
                "table": ctx["table"] if in_cell else None,
                "row": ctx["row"] if in_cell else None,
                "col": ctx["col"] if in_cell else None,
                "valign": ctx["valign"] if in_cell else None,
                "table_may_split": bool(ctx["may_split"]) if in_cell else None,
                "table_anchored": (bool(ctx["anchored"]) if in_cell
                                   else None),
                "fragment": ctx["fragment"] if in_cell else None,
                "under_anchor": (bool(_has_floating_object(para))
                                 and not in_cell),
                "usable": usable,
                "body_top": body_top,
                "base": base_hwp,
                # ``_render_paragraphs``' fifth argument is two different
                # things depending on who calls it.  From a CELL it is the
                # vertical-alignment offset, which is part of the seat and
                # nothing to flag; from ``render`` it is
                # ``_auto_anchor_page_offsets`` — the page rebase #278 added
                # for kstartup's table 7 — and there the seat this scan
                # reports is the cache's ``vertpos`` PLUS a Rigorloom
                # correction rather than Hancom's own page coordinate.
                "valign_offset": block_offset_hwp if in_cell else 0,
                "rebased": (not in_cell) and bool(block_offset_hwp),
                "rel_top": rel_top,
                "line_class": classify(facts, has_text, usable),
                "on_sheet": seat_on_sheet(rel_top, facts["vertsize"],
                                          body_top, geo["height"]),
                # A paragraph carrying an inline table has a lineseg whose
                # ``vertsize`` is the whole TABLE's height, not a text line's.
                # #256 excluded those from the rejected side and not from the
                # kept side; the scan keeps that parity and flags them, so
                # the text-only bracket can be read off separately.
                "inline_table": _para_has_inline_table(para),
                "text": _line_text(para, index),
                "overhang": line_overhangs(rel_top, seg, usable),
            }
            record.update({k: facts[k] for k in
                           ("vertpos", "vertsize", "textheight", "baseline",
                            "spacing")})
            reason = scan_evidence_reason(record)
            record["evidence"] = reason is None
            record["excluded"] = reason
            self.seats.append(record)


def scan_document(hwpx_path, dpi=own_render.DEFAULT_DPI, repo_root=None):
    """Every cached lineseg one document seats, in page coordinates."""
    scanner = SeatScanner(hwpx_path, dpi=dpi, repo_root=repo_root)
    scanner.render()
    return scanner


def scan_corpus(targets, dpi=own_render.DEFAULT_DPI, repo_root=None):
    """``(records, fragments)`` over every document given."""
    records = []
    fragments = {}
    for path in targets:
        scanner = scan_document(path, dpi=dpi, repo_root=repo_root)
        records.extend(scanner.seats)
        if scanner.fragments:
            fragments[Path(path).stem] = scanner.fragments
    return records, fragments


# -- does the export draw the seat the cache states? ----------------------

def pdf_confirmations(records, repo_root, render_dir=None):
    """Where the reference PDF drew the ink of each scanned line.

    The cache says where Hancom SEATED a line; this says where it DREW it.
    The two are in the same frame (HWPUNIT from the top of the sheet), so the
    comparison is direct — with one systematic caveat kept in the output
    rather than corrected for: a PDF text line's bbox is its GLYPH box, which
    is tighter than the line box the cache records, so the ink top is
    expected to sit below ``rel_top`` and the ink bottom above
    ``rel_top + vertsize`` even when the two agree perfectly.  What the check
    is for is the page and the gross position: ink on another page, or
    hundreds of HWPUNIT away, is the export having MOVED the line.
    """
    import lineseg_vs_pdf as LVP
    render_dir = render_dir or (repo_root / "tests" / "corpus" / "forms"
                                / "render")
    cache = {}
    out = []
    for record in records:
        stem = record["form"]
        if stem not in cache:
            pdf = render_dir / (stem + ".pdf")
            cache[stem] = LVP.PdfLines.read(pdf) if pdf.exists() else None
        pdf_lines = cache[stem]
        key = LVP.normalise(record["text"])
        entry = {"form": stem, "page": record["page"], "para": record["para"],
                 "lineseg": record["lineseg"], "key": key,
                 "matches": 0, "pdf_page": None, "pdf_top": None,
                 "pdf_bottom": None, "top_delta": None,
                 "ink_overhang": None, "verdict": "no reference",
                 "_record": record}
        if pdf_lines is None or not key:
            if pdf_lines is not None:
                entry["verdict"] = "line carries no text"
            out.append(entry)
            continue
        hits = [line for line in pdf_lines.lines
                if key == line["key"] or key in line["key"]]
        entry["matches"] = len(hits)
        if not hits:
            entry["verdict"] = "text not found in the export"
            out.append(entry)
            continue
        # The nearest hit in the frame the cache predicts, so a line whose
        # text repeats is not scored against an unrelated copy.
        want = record["body_top"] + record["rel_top"]
        best = min(hits, key=lambda line: (line["page"] != record["page"],
                                           abs(line["top_hwp"] - want)))
        entry["pdf_page"] = best["page"]
        entry["pdf_top"] = int(round(best["top_hwp"] - record["body_top"]))
        entry["pdf_bottom"] = int(round(best["bottom_hwp"]
                                        - record["body_top"]))
        entry["top_delta"] = entry["pdf_top"] - record["rel_top"]
        entry["ink_overhang"] = entry["pdf_bottom"] - record["usable"]
        entry["verdict"] = ("MOVED to another page"
                            if best["page"] != record["page"]
                            else "seat drawn")
        out.append(entry)
    return out


def _fragment_tail(records, stem):
    """The deepest cell line on the first fragment of a split table."""
    rows = [r for r in records
            if r["form"] == stem and r["container"] == "cell"
            and r["fragment"] is not None and r["fragment"][0] == 0
            and r["line_class"] == "text" and r["on_sheet"]]
    if not rows:
        return None
    return max(rows, key=lambda r: r["overhang"][SCAN_SORT_MEASURE])


def format_scan(records, fragments, bracket, tail, misses, confirmations):
    lines = []
    lines.append("")
    lines.append("direct scan: every cached lineseg the cache path seats, "
                 "top-level and in-cell")
    forms = sorted({r["form"] for r in records})
    width = max([len(s) for s in forms] + [4])
    lines.append(f"{'form':<{width}} {'lines':>6} {'cell':>6} {'anchor':>6} "
                 f"{'text':>6} {'evid':>6} {'max_evid':>9} {'max_any':>9} "
                 f"{'excluded':>9}")
    for stem in forms:
        rows = [r for r in records if r["form"] == stem]
        cells = [r for r in rows if r["container"] == "cell"]
        evid = [r for r in rows if r["evidence"]]
        peak = max((r["overhang"][SCAN_SORT_MEASURE] for r in evid),
                   default=None)
        # Every line on the sheet, other exclusions included: a line in a
        # table that may not split is not evidence about the fit RULE, but it
        # is still ink, and a reader has to be able to see whether any of it
        # crosses at all.
        peak_any = max((r["overhang"][SCAN_SORT_MEASURE] for r in rows
                        if r["on_sheet"]), default=None)
        lines.append(
            f"{stem:<{width}} {len(rows):>6} {len(cells):>6} "
            f"{sum(1 for r in rows if r['under_anchor']):>6} "
            f"{sum(1 for r in rows if r['line_class'] == 'text'):>6} "
            f"{len(evid):>6} "
            f"{'-' if peak is None else peak:>9} "
            f"{'-' if peak_any is None else peak_any:>9} "
            f"{len(rows) - len(evid):>9}")
    reasons = {}
    for record in records:
        if record["excluded"]:
            reasons[record["excluded"]] = reasons.get(record["excluded"], 0) + 1
    lines.append("")
    lines.append(f"scanned {len(records)} linesegs; "
                 f"{sum(1 for r in records if r['evidence'])} carry "
                 f"kept-side evidence")
    rebased = sum(1 for r in records if r["rebased"])
    if rebased:
        lines.append(f"  on a page the anchor-overflow fix rebased (#278): "
                     f"{rebased} — there the seat is the cache's vertpos plus "
                     "a Rigorloom correction, not Hancom's own")
    for reason, count in sorted(reasons.items()):
        lines.append(f"  excluded: {reason} — {count}")

    lines.append("")
    lines.append(f"top tail: every scanned line whose box ends within "
                 f"{-SCAN_TAIL_FLOOR} HWPUNIT of the body bottom "
                 f"(measure {SCAN_SORT_MEASURE})")
    if not tail:
        lines.append("  none — every cached line in the corpus ends more "
                     f"than {-SCAN_TAIL_FLOOR} HWPUNIT above the body bottom")
    else:
        head = (f"  {'form':<{width}} {'pg':>3} {'para':>5} {'seg':>4} "
                f"{'where':<18} {'vsz':>6} {'spc':>5} {'ev':>3}")
        head += "".join(f" {name[:9]:>9}" for name in MEASURE_ORDER)
        lines.append(head)
        for r in tail:
            where = ("top-level" if r["container"] == "top-level"
                     else f"tbl{r['table']} r{r['row']},c{r['col']}")
            if r["under_anchor"]:
                where += "*"
            if r["inline_table"]:
                where += "+tbl"
            if not r["on_sheet"]:
                where += "!off"
            row = (f"  {r['form']:<{width}} {r['page']:>3} {r['para']:>5} "
                   f"{r['lineseg']:>4} {where:<18} {r['vertsize']:>6} "
                   f"{r['spacing']:>5} {'y' if r['evidence'] else 'n':>3}")
            row += "".join(f" {r['overhang'][name]:>9}"
                           for name in MEASURE_ORDER)
            lines.append(row)
        lines.append("  * = a top-level paragraph that anchors a floating "
                     "object; +tbl = the lineseg is a whole inline table's "
                     "box; !off = the seat misses the sheet; "
                     "ev = carries kept-side evidence")

    lines.append("")
    lines.append(f"near misses: every line the cache MOVED whose would-be "
                 f"overhang was under +{SCAN_NEAR_MISS_CEILING} "
                 f"(measure {SCAN_SORT_MEASURE})")
    if not misses:
        lines.append("  none")
    else:
        head = (f"  {'form':<{width}} {'pg':>3} {'para':>5} {'vsz':>6} "
                f"{'spc':>5} {'ev':>3}")
        head += "".join(f" {name[:9]:>9}" for name in MEASURE_ORDER)
        lines.append(head)
        for r in misses:
            row = (f"  {r['form']:<{width}} {r['page']:>3} {r['para']:>5} "
                   f"{r['vertsize']:>6} {r['spacing']:>5} "
                   f"{'y' if r['evidence'] else 'n':>3}")
            row += "".join(f" {r['overhang'][name]:>9}"
                           for name in MEASURE_ORDER)
            lines.append(row)

    lines.append("")
    lines.append("the public bracket after the scan, HWPUNIT")
    lines.append(f"{'measure':<24} {'kept_n':>7} {'kept_MAX':>9} "
                 f"{'text_MAX':>9} {'evt_MAX':>9} {'union_MAX':>10} "
                 f"{'rej_MIN':>9} {'k!':>3} {'r!':>3} {'fits':>5}")
    for name in MEASURE_ORDER:
        row = bracket[name]
        lines.append(
            f"{name:<24} {row['kept_n']:>7} "
            f"{'-' if row['kept_max'] is None else row['kept_max']:>9} "
            f"{'-' if row['text_max'] is None else row['text_max']:>9} "
            f"{'-' if row['event_max'] is None else row['event_max']:>9} "
            f"{'-' if row['union_max'] is None else row['union_max']:>10} "
            f"{'-' if row['rejected_min'] is None else row['rejected_min']:>9}"
            f" {row['kept_violations']:>3} {row['rejected_violations']:>3} "
            f"{'yes' if row['consistent'] else 'no':>5}")
    lines.append("kept_MAX is every evidence line the scan seated; text_MAX "
                 "drops the ones whose lineseg is a whole inline TABLE's box;")
    lines.append("evt_MAX is the page-break pass's own kept side; union_MAX "
                 "is the bound a measure has to clear under either reading")

    lines.append("")
    lines.append("tables the cache path drew as more than one fragment "
                 "— the one place Hancom cut through a cell")
    if not fragments:
        lines.append("  none")
    for stem in sorted(fragments):
        for key, ranges in sorted(fragments[stem].items()):
            lines.append(f"  {stem} table {key}: "
                         + ", ".join(f"rows [{a}, {b})" for a, b in ranges))
        deepest = _fragment_tail(records, stem)
        if deepest is None:
            lines.append("  no text line on the first fragment")
            continue
        lines.append(f"  deepest cell line on the FIRST fragment: page "
                     f"{deepest['page']} r{deepest['row']},c{deepest['col']} "
                     f"vertpos {deepest['rel_top']} vertsize "
                     f"{deepest['vertsize']} spacing {deepest['spacing']}")
        for name in MEASURE_ORDER:
            lines.append(f"      {name:<24} "
                         f"{deepest['overhang'][name]:>+9}")

    lines.append("")
    lines.append("the reference PDF for each tail line: is the cache's seat "
                 "the ink Hancom drew?")
    if not confirmations:
        lines.append("  nothing in the tail to confirm")
    else:
        lines.append(f"  {'form':<{width}} {'pg':>3} {'para':>5} "
                     f"{'pdfpg':>5} {'cache_top':>10} {'ink_top':>8} "
                     f"{'d_top':>7} {'ink_bot':>8} {'ink_over':>9}  verdict")
        for c in confirmations:
            record = c["_record"]
            lines.append(
                f"  {c['form']:<{width}} {c['page']:>3} {c['para']:>5} "
                f"{'-' if c['pdf_page'] is None else c['pdf_page']:>5} "
                f"{record['rel_top']:>10} "
                f"{'-' if c['pdf_top'] is None else c['pdf_top']:>8} "
                f"{'-' if c['top_delta'] is None else format(c['top_delta'], '+'):>7} "
                f"{'-' if c['pdf_bottom'] is None else c['pdf_bottom']:>8} "
                f"{'-' if c['ink_overhang'] is None else format(c['ink_overhang'], '+'):>9}"
                f"  {c['verdict']}")
        lines.append("  ink_top/ink_bot are GLYPH boxes, tighter than the "
                     "line box by design; the check is the page and the "
                     "gross position, not the last HWPUNIT")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Bracket the page-bottom fit test against cached seats")
    parser.add_argument("hwpx", nargs="*", type=Path,
                        help="documents to probe")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every converted corpus form")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None,
                        help="write the full per-event record here")
    parser.add_argument("--offset-scan", action="store_true",
                        help="vary usable_height and report the offsets "
                             "that keep the fit rule consistent")
    parser.add_argument("--scan-range", default="-1000:1500:50",
                        metavar="LO:HI:STEP",
                        help="the free scan, HWPUNIT (default -1000:1500:50)")
    parser.add_argument("--reference-ink", action="store_true",
                        help="also measure the reference PDF's deepest "
                             "ruling and text against the derived body box")
    parser.add_argument("--band", default=None, metavar="LO:HI",
                        help="an externally measured offset band to test "
                             "against the corpus band, HWPUNIT")
    parser.add_argument("--scan-all", action="store_true",
                        help="scan EVERY cached lineseg, top-level and "
                             "in-cell, for a box that crosses the body "
                             "bottom — no page-break structure at all")
    parser.add_argument("--tail-floor", type=int, default=SCAN_TAIL_FLOOR,
                        metavar="HWPUNIT",
                        help="how close to the body bottom a line has to "
                             f"end to be in the tail (default "
                             f"{SCAN_TAIL_FLOOR})")
    parser.add_argument("--near-miss", type=int,
                        default=SCAN_NEAR_MISS_CEILING, metavar="HWPUNIT",
                        help="how small a moved line's would-be overhang "
                             "has to be to be a near miss (default "
                             f"{SCAN_NEAR_MISS_CEILING})")
    parser.add_argument("--no-pdf", action="store_true",
                        help="skip the reference-PDF confirmation of each "
                             "tail line")
    return parser


def main(argv=None):
    # BEFORE parse_args: this module's own description carries an em-dash and
    # a cp949 console kills ``--help`` on it (cli_io's docstring).
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    targets = list(args.hwpx)
    if args.corpus:
        converted = repo_root / "tests" / "corpus" / "forms" / "converted"
        targets.extend(sorted(converted.glob("*.hwpx")))
    if not targets:
        build_parser().error("give a document or --corpus")
    reports = [probe_document(path, dpi=args.dpi, repo_root=repo_root)
               for path in targets]
    summary = summarise(reports)
    print(format_report(reports, summary))
    scan = None
    if args.offset_scan:
        lo, hi, step = (int(v) for v in args.scan_range.split(":"))
        band = None
        if args.band:
            blo, bhi = (int(v) for v in args.band.split(":"))
            band = (blo, bhi)
        scan = offset_scan(reports, lo=lo, hi=hi, step=step)
        tops = top_refuters(reports)
        print(format_offset_scan(scan, tops, band=band))
    scan_payload = None
    if args.scan_all:
        records, fragments = scan_corpus(targets, dpi=args.dpi,
                                         repo_root=repo_root)
        rejected = [e for r in reports for e in r["events"]
                    if is_evidence_rejected(e)]
        kept_events = [e for r in reports for e in r["events"]
                       if is_evidence_kept(e)]
        bracket = scan_bracket(records, rejected, kept_events)
        tail = scan_tail(records, floor=args.tail_floor)
        misses = near_misses(reports, ceiling=args.near_miss)
        confirmations = ([] if args.no_pdf
                         else pdf_confirmations(tail, repo_root))
        print(format_scan(records, fragments, bracket, tail, misses,
                          confirmations))
        scan_payload = {
            "tail_floor": args.tail_floor,
            "near_miss_ceiling": args.near_miss,
            "sort_measure": SCAN_SORT_MEASURE,
            "lines_scanned": len(records),
            "bracket": bracket,
            "tail": tail,
            "near_misses": misses,
            "fragments": {stem: {str(k): [list(r) for r in v]
                                 for k, v in table.items()}
                          for stem, table in fragments.items()},
            "pdf": [{k: v for k, v in c.items() if k != "_record"}
                    for c in confirmations],
        }
    ink = None
    if args.reference_ink:
        render_dir = repo_root / "tests" / "corpus" / "forms" / "render"
        ink = []
        for path in targets:
            pdf = render_dir / (Path(path).stem + ".pdf")
            if not pdf.exists():
                continue
            ink.append(reference_ink(path, pdf, repo_root=repo_root))
        print(format_reference_ink(ink))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": summary, "documents": reports}
        if scan is not None:
            payload["offset_scan"] = scan
            payload["top_refuters"] = top_refuters(reports)
        if ink is not None:
            payload["reference_ink"] = ink
        if scan_payload is not None:
            payload["scan_all"] = scan_payload
        args.json.write_text(json.dumps(payload, indent=2,
                                        ensure_ascii=False),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
