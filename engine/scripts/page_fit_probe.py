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
    """Whether linesegs ``[lo, hi)`` of ``para`` carry any character."""
    positions = [_iattr(seg, "textpos") for seg in para.linesegs]
    start = positions[lo]
    end = positions[hi] if hi < len(positions) else len(para.chars)
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
    return parser


def main(argv=None):
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
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"summary": summary, "documents": reports},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
