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
            for record in fresh:
                record.setdefault("address", address)
                record.setdefault("text", text)
        return result


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


def divergence_report(hwpx_path, dpi=own_render.DEFAULT_DPI,
                      y_tol=DEFAULT_Y_TOL, include_text=True,
                      repo_root=None):
    """Classify every line of one document across the two layout policies."""
    hwpx_path = Path(hwpx_path)
    cache = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_CACHE, dpi=dpi,
                        repo_root=repo_root)
    computed = trace_lines(hwpx_path, own_render.LAYOUT_POLICY_COMPUTED,
                           dpi=dpi, repo_root=repo_root)
    cache_paras = by_paragraph(cache["line_boxes"])
    computed_paras = by_paragraph(computed["line_boxes"])

    line_counts = Counter()
    para_counts = Counter()
    both_a_and_b = 0
    divergences = []
    dy_histogram = Counter()

    for address in sorted(set(cache_paras) | set(computed_paras)):
        rows = classify_paragraph(cache_paras.get(address, []),
                                  computed_paras.get(address, []), y_tol)
        classes = set()
        for row in rows:
            line_counts[row["class"]] += 1
            classes.add(row["class"])
            if row["class"] == "B":
                dy_histogram[round(_delta(row["cache"], row["computed"],
                                          "y0"), 2)] += 1
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

    report = {
        "tool": "layout_divergence",
        "source": hwpx_path.name,
        "dpi": dpi,
        "y_tolerance_px": y_tol,
        "text_included": include_text,
        "rule": RULE,
        "class_meaning": CLASS_MEANING,
        "pages": {"cache": cache["pages"], "computed": computed["pages"]},
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
    return (f"{stem}: paragraphs agree {paras['agree']} / A {paras['A']} / "
            f"B {paras['B']} / C {paras['C']} (A&B {paras['A_and_B']}); "
            f"lines agree {lines['agree']} / A {lines['A']} / B {lines['B']} "
            f"/ C {lines['C']}{dominant}{iou_text}")


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
    """A compact per-form table in #247's shape: paragraphs, not lines."""
    width = max([len(name) for name, _ in rows] + [4])
    head = (f"{'form':<{width}}  {'agree':>6} {'A':>5} {'B':>5} {'C':>5} "
            f"{'A&B':>5}")
    out = [head, "-" * len(head)]
    total = Counter()
    for name, report in rows:
        paras = report["paragraphs"]
        out.append(f"{name:<{width}}  {paras['agree']:>6} {paras['A']:>5} "
                   f"{paras['B']:>5} {paras['C']:>5} {paras['A_and_B']:>5}")
        for key in ("agree", "A", "B", "C", "A_and_B"):
            total[key] += paras[key]
    out.append("-" * len(head))
    out.append(f"{'total':<{width}}  {total['agree']:>6} {total['A']:>5} "
               f"{total['B']:>5} {total['C']:>5} {total['A_and_B']:>5}")
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
                               include_text=not args.no_text)
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
