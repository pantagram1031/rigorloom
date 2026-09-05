#!/usr/bin/env python3
"""Fit Hancom's ``PERCENT`` line-spacing arithmetic against its own cache.

``own_render._line_metrics`` turns a paragraph's ``hh:lineSpacing`` and its
line's character height into the ``spacing`` the line carries below it.  The
reading it shipped with — ``round(height * value / 100) - height`` — is right
on most lines and off by one or two HWPUNIT on the rest, and #247 and #261
both left that residual open as "a rounding difference, not a rule".

It is a rule.  This probe is the instrument that says so: it reads every
cached ``hp:lineseg`` of the converted corpus, reconstructs the inputs the
authoring engine had (the declared character heights on the line, the
paragraph's line spacing), and scores a family of candidate formulas against
the cached ``spacing`` — exact matches and the residual histogram, per form
and in total.

The corpus is the only oracle here.  A cached ``hp:lineseg`` is what Hancom
itself computed for a line whose inputs are in the same file, so a candidate
that reproduces all of them has been fitted to the authoring engine and not
to this renderer's opinion of it.  Nothing is rendered and no policy is
exercised, so this cannot perturb what ``render_scoreboard.py`` or
``layout_divergence.py`` report.

Usage::

    python engine/scripts/spacing_residual_probe.py --corpus
    python engine/scripts/spacing_residual_probe.py --corpus --json out.json
    python engine/scripts/spacing_residual_probe.py path/to/doc.hwpx

``render-check-01`` is deliberately NOT in ``--corpus``.  It is the one
Rigorloom-written package with a Hancom reference render, but Rigorloom writes
no ``hp:lineseg`` at all, so it carries nothing for this probe to read; pass it
explicitly and the run reports zero lines.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402
from own_render import HWPUNIT_PER_PT, _iattr, _local  # noqa: E402


def _round_half_away(num, den):
    """``num / den`` rounded to an integer, halves going away from zero.

    Integer arithmetic throughout, so no float ever decides a tie.
    """
    sign = -1 if (num < 0) != (den < 0) else 1
    n, d = abs(num), abs(den)
    return sign * ((2 * n + d) // (2 * d))


#: The quantum the fit lands on: every one of the corpus' 3214 cached
#: ``hp:lineseg@spacing`` values is a multiple of 4 HWPUNIT (0.04 pt, 1/1800
#: inch).  The cached ``vertsize`` is NOT — 53 corpus lines carry an inline
#: object whose box is not a multiple of 4 — so it is the LEADING that is
#: quantised, not the total advance, and that distinction is what candidate
#: ``q4_advance`` below exists to refute.
LEADING_QUANTUM = 4


def candidates():
    """``{name: fn(height, value) -> spacing}`` — every reading to be scored.

    ``height`` is the line's pitch height in HWPUNIT (the largest declared
    ``hh:charPr@height`` on the line; an inline object contributes its run's
    point size to the pitch, not its own box).  ``value`` is
    ``hh:lineSpacing@value`` for a ``PERCENT`` paragraph.
    """

    def shipped(h, v):
        # What own_render carried before this probe: round the total advance
        # in whole HWPUNIT, then subtract the height back off.
        return int(round(h * v / 100.0)) - h

    def gap_half_up(h, v):
        # (a) round the GAP, halves up, in whole HWPUNIT.
        return (h * (v - 100) + 50) // 100

    def gap_floor(h, v):
        return (h * (v - 100)) // 100

    def gap_ceil(h, v):
        return -((-h * (v - 100)) // 100)

    def gap_half_even(h, v):
        q, r = divmod(h * (v - 100), 100)
        if r * 2 > 100 or (r * 2 == 100 and q % 2):
            q += 1
        return q

    def advance_total(h, v):
        # (c) round the TOTAL line advance, not the gap.
        return _round_half_away(h * v, 100) - h

    def hundredth_pt(h, v):
        # (b) computed in 1/100 pt.  HWPUNIT *is* 1/100 pt, so this is
        # ``gap_half_up`` under another name and is scored to show that the
        # unit is not where the residual lives.
        return _round_half_away(h * (v - 100), 100)

    def twips(h, v):
        # (b) computed in twips (1/1440 in = 5 HWPUNIT), then converted back.
        return 5 * _round_half_away(h * (v - 100), 500)

    def q2_leading(h, v):
        return 2 * _round_half_away(h * (v - 100), 200)

    def q8_leading(h, v):
        return 8 * _round_half_away(h * (v - 100), 800)

    def q4_leading_half_up(h, v):
        # Quantised leading, but halves going toward +infinity rather than
        # away from zero.  Separates from ``q4_leading`` only where the
        # leading is NEGATIVE, i.e. value < 100.
        return 4 * ((h * (v - 100) + 200) // 400)

    def q4_leading_half_even(h, v):
        q, r = divmod(h * (v - 100), 400)
        if r * 2 > 400 or (r * 2 == 400 and q % 2):
            q += 1
        return 4 * q

    def q4_leading_trunc(h, v):
        return 4 * int(h * (v - 100) / 400)

    def q4_advance(h, v):
        # Quantise the total ADVANCE to 4 HWPUNIT instead of the leading.
        return 4 * _round_half_away(h * v, 400) - h

    def q4_leading(h, v):
        # The fit.  See LEADING_QUANTUM.
        return 4 * _round_half_away(h * (v - 100), 400)

    return {
        "shipped_round_advance": shipped,
        "gap_half_up": gap_half_up,
        "gap_floor": gap_floor,
        "gap_ceil": gap_ceil,
        "gap_half_even": gap_half_even,
        "advance_half_away": advance_total,
        "hundredth_pt": hundredth_pt,
        "twips": twips,
        "q2_leading": q2_leading,
        "q8_leading": q8_leading,
        "q4_leading_half_up": q4_leading_half_up,
        "q4_leading_half_even": q4_leading_half_even,
        "q4_leading_trunc": q4_leading_trunc,
        "q4_advance": q4_advance,
        "q4_leading": q4_leading,
    }


def line_facts(renderer, para, index, lo, hi):
    """Everything one cached line states, plus the heights that produced it.

    The height walk is ``own_render._line_metrics``' own, deliberately
    duplicated rather than called: the point of the probe is to score readings
    the renderer does not implement, so it must own the inputs.
    """
    seg = para.linesegs[index]
    heights = []
    pitch = []
    has_object = False
    for char_index, cid in para.empty_runs:
        # A run that puts no character on the line still declares its shape
        # (#247); the last line owns one sitting at the end of the stream.
        if lo <= char_index < hi or (char_index == hi == len(para.chars)):
            height = (renderer._charpr(cid).get("height_pt") or 10.0) \
                * HWPUNIT_PER_PT
            heights.append(height)
            pitch.append(height)
    for offset, (ch, cid) in enumerate(para.chars[lo:hi]):
        char_height = (renderer._charpr(cid).get("height_pt") or 10.0) \
            * HWPUNIT_PER_PT
        if ch == own_render.OBJECT_SLOT:
            record = para.object_at.get(lo + offset)
            if record is not None and not record[3]:
                _l, top, _r, bottom = renderer._object_out_margin(record[1])
                heights.append(renderer._object_extent(record[1])[1]
                               + top + bottom)
                pitch.append(char_height)
                has_object = True
                continue
        heights.append(char_height)
        pitch.append(char_height)
    if not heights:
        cid = para.chars[0][1] if para.chars else None
        heights.append((renderer._charpr(cid).get("height_pt") or 10.0)
                       * HWPUNIT_PER_PT)
        pitch.append(heights[-1])
    pr = para.para_pr or {}
    return {
        "line": index,
        "lines_in_paragraph": len(para.linesegs),
        "empty_paragraph": not para.chars,
        "has_inline_object": has_object,
        "mixed_heights": len(set(int(round(h)) for h in heights)) > 1,
        "declared_heights": sorted(set(int(round(h)) for h in heights)),
        "height": int(round(max(heights))),
        "pitch_height": int(round(max(pitch))),
        "spacing_type": (pr.get("line_spacing_type") or "PERCENT"),
        "spacing_value": pr.get("line_spacing_value", 100),
        "spacing_unit": pr.get("line_spacing_unit"),
        "cached_vertsize": _iattr(seg, "vertsize"),
        "cached_textheight": _iattr(seg, "textheight"),
        "cached_baseline": _iattr(seg, "baseline"),
        "cached_spacing": _iattr(seg, "spacing"),
        "cached_vertpos": _iattr(seg, "vertpos"),
    }


def probe_document(hwpx_path, repo_root=None):
    """Every cached line of one document, with its inputs reconstructed."""
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    lines = []
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        root = renderer.sections[section]
        # Every hp:p in the section tree, top-level and inside table cells
        # alike: a cell paragraph's lineseg is as much Hancom's arithmetic as
        # a body paragraph's, and the corpus' forms put most of their text in
        # cells.
        for order, el in enumerate(root.iter()):
            if _local(el.tag) != "p":
                continue
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            if not para.linesegs:
                continue
            spans = para.lineseg_spans()
            for index in range(len(para.linesegs)):
                lo, hi = spans[index]
                fact = line_facts(renderer, para, index, lo, hi)
                fact["section"] = section
                fact["paragraph"] = order
                lines.append(fact)
    return {"document": str(hwpx_path),
            "form": Path(hwpx_path).stem,
            "lines": lines}


def score(reports):
    """Per candidate: exact matches and the residual histogram, per form."""
    funcs = candidates()
    per_form = {}
    total = {name: {"exact": 0, "total": 0, "residuals": collections.Counter()}
             for name in funcs}
    for report in reports:
        form = report["form"]
        rows = {name: {"exact": 0, "total": 0,
                       "residuals": collections.Counter()} for name in funcs}
        for fact in report["lines"]:
            if fact["spacing_type"] != "PERCENT":
                continue
            height = fact["pitch_height"]
            value = fact["spacing_value"]
            for name, fn in funcs.items():
                got = fn(height, value)
                residual = fact["cached_spacing"] - got
                for bucket in (rows[name], total[name]):
                    bucket["total"] += 1
                    if residual:
                        bucket["residuals"][residual] += 1
                    else:
                        bucket["exact"] += 1
        per_form[form] = rows
    out = {}
    for name in funcs:
        out[name] = {
            "exact": total[name]["exact"],
            "total": total[name]["total"],
            "residuals": dict(sorted(total[name]["residuals"].items())),
            "per_form": {
                form: {"exact": rows[name]["exact"],
                       "total": rows[name]["total"],
                       "residuals": dict(sorted(
                           rows[name]["residuals"].items()))}
                for form, rows in per_form.items()},
        }
    return out


def population(reports):
    """What the scored lines ARE, so a 100% is read against a known corpus."""
    rows = [f for r in reports for f in r["lines"]]
    percent = [f for f in rows if f["spacing_type"] == "PERCENT"]
    return {
        "documents": len(reports),
        "cached_lines": len(rows),
        "spacing_types": dict(sorted(collections.Counter(
            f["spacing_type"] for f in rows).items())),
        "percent_lines": len(percent),
        "text_lines": sum(1 for f in percent if not f["empty_paragraph"]),
        "empty_paragraph_lines": sum(1 for f in percent
                                     if f["empty_paragraph"]),
        "inline_object_lines": sum(1 for f in percent
                                   if f["has_inline_object"]),
        "mixed_height_lines": sum(1 for f in percent if f["mixed_heights"]),
        "distinct_height_value_cells": len({
            (f["pitch_height"], f["spacing_value"]) for f in percent}),
        "cached_spacing_multiple_of_4": sum(
            1 for f in percent if f["cached_spacing"] % 4 == 0),
        "cached_vertsize_multiple_of_4": sum(
            1 for f in percent if f["cached_vertsize"] % 4 == 0),
    }


#: Only candidates this close to the winner are worth listing line by line.
#: A reading that misses hundreds of lines is refuted by the score table; the
#: interesting evidence is what refutes a reading that misses five.
RIVAL_THRESHOLD = 0.95


def discriminators(reports, scores):
    """The lines that separate the winner from each SURVIVING runner-up.

    A candidate table full of 100%-and-one-off numbers hides which lines
    actually did the work.  These are the cached lines on which the winning
    reading and each near-miss disagree, and they are the whole evidence for
    preferring one over the other.
    """
    funcs = candidates()
    winner = "q4_leading"
    rivals = [n for n in funcs
              if n != winner and scores[n]["total"]
              and scores[n]["exact"] / scores[n]["total"] >= RIVAL_THRESHOLD]
    out = {}
    for name in rivals:
        cells = collections.Counter()
        for report in reports:
            for fact in report["lines"]:
                if fact["spacing_type"] != "PERCENT":
                    continue
                h, v = fact["pitch_height"], fact["spacing_value"]
                mine, theirs = funcs[winner](h, v), funcs[name](h, v)
                if mine == theirs:
                    continue
                cells[(report["form"], h, v, fact["cached_spacing"],
                       mine, theirs)] += 1
        if cells:
            out[name] = [
                {"form": k[0], "height": k[1], "value": k[2],
                 "cached": k[3], "q4_leading": k[4], name: k[5], "lines": n}
                for k, n in sorted(cells.items())]
    return out


def format_report(reports, scores, pop, disc):
    lines = []
    lines.append("PERCENT line-spacing arithmetic against the cached lineseg")
    lines.append("=" * 62)
    lines.append("")
    lines.append(f"documents                    {pop['documents']}")
    lines.append(f"cached hp:lineseg            {pop['cached_lines']}")
    lines.append(f"  spacing types              {pop['spacing_types']}")
    lines.append(f"  scored (PERCENT)           {pop['percent_lines']}")
    lines.append(f"    text lines               {pop['text_lines']}")
    lines.append(f"    empty-paragraph lines    "
                 f"{pop['empty_paragraph_lines']}")
    lines.append(f"    lines with inline object {pop['inline_object_lines']}")
    lines.append(f"    lines of mixed height    {pop['mixed_height_lines']}")
    lines.append(f"  distinct (height, value)   "
                 f"{pop['distinct_height_value_cells']}")
    lines.append(f"  cached spacing % 4 == 0    "
                 f"{pop['cached_spacing_multiple_of_4']}"
                 f" / {pop['percent_lines']}")
    lines.append(f"  cached vertsize % 4 == 0   "
                 f"{pop['cached_vertsize_multiple_of_4']}"
                 f" / {pop['percent_lines']}")
    lines.append("")
    lines.append(f"{'candidate':26s} {'exact':>12s}  residuals (cache - "
                 "candidate)")
    lines.append("-" * 78)
    order = sorted(scores, key=lambda n: (-scores[n]["exact"], n))
    for name in order:
        row = scores[name]
        pct = 100.0 * row["exact"] / row["total"] if row["total"] else 0.0
        residuals = row["residuals"] or {}
        lines.append(f"{name:26s} {row['exact']:6d}/{row['total']:<5d} "
                     f"{pct:5.1f}%  {residuals}")
    lines.append("")
    best = order[0]
    lines.append(f"best: {best} — {scores[best]['exact']} of "
                 f"{scores[best]['total']}")
    lines.append("")
    lines.append("per form (exact / scored), best candidate against shipped")
    lines.append("-" * 78)
    forms = sorted(scores[best]["per_form"])
    lines.append(f"{'form':46s} {'shipped':>14s} {'best':>14s}")
    for form in forms:
        shipped = scores["shipped_round_advance"]["per_form"][form]
        won = scores[best]["per_form"][form]
        lines.append(f"{form:46s} {shipped['exact']:6d}/{shipped['total']:<7d}"
                     f" {won['exact']:6d}/{won['total']:<7d}")
    lines.append("")
    lines.append("what separates q4_leading from each surviving runner-up "
                 f"(>= {RIVAL_THRESHOLD:.0%})")
    lines.append("-" * 78)
    if disc:
        for name in order:
            if name not in disc:
                continue
            rows = disc[name]
            total = sum(r["lines"] for r in rows)
            lines.append(f"  vs {name}: {total} line(s), "
                         f"{len(rows)} (form, height, value) cell(s)")
            for row in rows:
                lines.append(
                    f"    {row['form']:30s} h={row['height']:>6d} "
                    f"v={row['value']:>4d}  cached {row['cached']:>7d}  "
                    f"q4_leading {row['q4_leading']:>7d}  "
                    f"{name} {row[name]:>7d}  x{row['lines']}")
    else:
        lines.append("  nothing within the threshold disagrees with it")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hwpx", nargs="*", type=Path,
                        help="documents to probe")
    parser.add_argument("--corpus", action="store_true",
                        help="probe every converted corpus form")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the full per-line record here")
    parser.add_argument("--repo-root", type=Path, default=None)
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    targets = list(args.hwpx)
    if args.corpus:
        converted = repo_root / "tests" / "corpus" / "forms" / "converted"
        targets.extend(sorted(converted.glob("*.hwpx")))
    if not targets:
        build_parser().error("give a document or --corpus")
    reports = [probe_document(path, repo_root=repo_root) for path in targets]
    scores = score(reports)
    pop = population(reports)
    disc = discriminators(reports, scores)
    print(format_report(reports, scores, pop, disc))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"population": pop, "candidates": scores,
             "discriminators": disc, "documents": reports},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
