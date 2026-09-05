#!/usr/bin/env python3
"""Which part of a line box the page-bottom fit test clears, on a probe.

``engine/scripts/page_fit_probe.py`` brackets that question against the ten
corpus forms' own cached seats.  The bracket it returns is wide, because no
corpus page keeps a line whose box crosses the bottom margin: the corpus has
no case in the ambiguous band at all.  This probe manufactures that band.

**Path A does not exist here, and path C is NOT RUN.**  A package this repo
writes carries no ``hp:lineseg``, so ``--layout-policy cache`` has nothing to
read and the flow pass is the only layout there is.  No Hancom reference is
exported and none is measured, so nothing below is evidence about what Hancom
would do — it is evidence about which candidate measure this renderer's flow
pass is currently implementing, and about what each other candidate would
cost if adopted.

The instrument is one knob.  Forty-five identical single-line paragraphs fill
the body: ``hh:charPr@height`` 1000 with ``PERCENT`` 160 line spacing, so
every line has ``vertsize`` 1000, ``spacing`` 600, ``baseline`` 850 and an
advance of 1600, and line *k* sits at ``1600k`` from the body top.  The
section's ``hc:bottom`` page margin is then swept, which moves
``usable_height`` across the boundary line's box a few hundred HWPUNIT at a
time.  For each setting the analytic prediction is stated per candidate
measure — line *k* stays iff ``1600k + measure <= usable_height`` — and
compared against the page the flow pass actually seats that paragraph on.

Every string in the package is a case label or synthetic filler, so it
carries no personal data.

    python tests/corpus/render-check/measure_page_fit_probe.py [--out DIR]
                                                               [--dpi 144]
                                                               [--json FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "engine" / "scripts"))

import build_render_check as B  # noqa: E402  (path shim above is deliberate)
import layout_divergence as LD  # noqa: E402
import own_render  # noqa: E402
import page_fit_probe as PFP  # noqa: E402

#: The body every case shares.  ``PP["base"]`` is ``PERCENT`` 160 and
#: ``CP["base"]`` is 1000, which fixes the line box the sweep is measured
#: against.
CHAR_H = 1000
LINE_PERCENT = 160
PITCH = int(round(CHAR_H * LINE_PERCENT / 100.0))       # 1600
VERTSIZE = CHAR_H                                       # 1000
SPACING = PITCH - CHAR_H                                # 600
BASELINE = int(round(own_render.BASELINE_RATIO * CHAR_H))   # 850
PARA_COUNT = 45

#: The paragraph whose seat the sweep is aimed at.  Its analytic top is
#: ``PITCH * BOUNDARY``, and every case puts ``usable_height`` within one line
#: box of that.
BOUNDARY = 40

#: ``vertpos`` offsets, in the same order and under the same names the corpus
#: probe reports, for a line with this document's metrics.
MEASURES = {
    "top": 0,
    "vertsize_minus_spacing": VERTSIZE - SPACING,        # 400
    "half_vertsize": VERTSIZE // 2,                      # 500
    "baseline": BASELINE,                                # 850
    "vertsize": VERTSIZE,                                # 1000
    "vertsize_plus_spacing": VERTSIZE + SPACING,         # 1600
}

#: Each case names the slack it wants between the boundary line's top and the
#: bottom of the body box, and the bottom page margin that produces it.
#: ``usable_height = A4_H - top - bottom - header - footer``.
SLACKS = [1364, 900, 764, 464, 164, -36]


def usable_for(bottom: int) -> int:
    m = dict(B.MARGIN, bottom=bottom)
    return (B.A4_H - m["top"] - m["bottom"] - m["header"] - m["footer"])


def bottom_for(slack: int) -> int:
    """The ``hc:bottom`` that puts the body bottom ``slack`` below line 40."""
    zero = usable_for(0)
    return zero - PITCH * BOUNDARY - slack


def predictions(slack: int) -> dict:
    """``{measure: "page1"|"page2"}`` — where each candidate seats line 40."""
    return {name: ("page1" if offset <= slack else "page2")
            for name, offset in MEASURES.items()}


def build_document(bottom: int, label: str):
    doc = B.Doc()
    section = doc.new_section()
    margin = dict(B.MARGIN, bottom=bottom)
    for index in range(PARA_COUNT):
        head = ""
        if index == 0:
            head = ('<hp:run charPrIDRef="%d">%s</hp:run>'
                    % (B.CP["base"][0],
                       B.sec_pr(width=B.A4_W, height=B.A4_H,
                                landscape="WIDELY", margin=margin,
                                col_count=1, furniture="")))
        run = ('<hp:run charPrIDRef="%d"><hp:t>%s</hp:t></hp:run>'
               % (B.CP["base"][0],
                  B.esc("%s page fit probe line %02d" % (label, index))))
        section.raw(
            '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s%s</hp:p>'
            % (B.oid(), B.PP["base"][0], head, run))
    return doc


def rendered(path, dpi):
    """``(usable_height, {address: page}, [address in document order])``."""
    renderer = LD.TracingRenderer(
        path, dpi=dpi, layout_policy=own_render.LAYOUT_POLICY_COMPUTED)
    renderer.render()
    pages = {}
    for (address, page), _seat in renderer.flow_seats.items():
        pages[address] = min(page, pages.get(address, page))
    facts = {a: f for a, f in renderer.paragraph_facts().items()
             if f.get("top_level")}
    return renderer.page_geometry()["usable_height"], pages, sorted(facts)


def line_metrics(path, dpi):
    """The flow pass's own row for the boundary paragraph, as it measured it.

    Read back rather than assumed: the constants at the top of this module
    are what the document DECLARES, and the point of stating both is that a
    mismatch is visible instead of silently reinterpreted.
    """
    renderer = own_render.OwnRenderer(
        path, dpi=dpi, layout_policy=own_render.LAYOUT_POLICY_COMPUTED)
    draw = renderer._scratch_draw()
    geo = renderer.page_geometry()
    column, _gap, _cols = renderer.column_geometry(geo)
    blocks = renderer._flow_blocks(draw, column)
    block = blocks[BOUNDARY]
    row = block["rows"][0]
    para = block["para"]
    line = next(iter(renderer.compute_lines(draw, para, column)))
    return {
        "vertsize": line["vertsize"],
        "spacing": line["spacing"],
        "baseline": line["baseline"],
        "advance": row["advance"],
        "extent": row["extent"],
        "rows": len(block["rows"]),
    }


def measure(out_dir, dpi):
    results = []
    for slack in SLACKS:
        bottom = bottom_for(slack)
        label = "slack%+d" % slack
        doc = build_document(bottom, label)
        path = Path(out_dir) / ("page-fit-probe-%s.hwpx" % label)
        B.assemble(doc).write(path)
        usable, pages, addresses = rendered(path, dpi)
        metrics = line_metrics(path, dpi)
        address = addresses[BOUNDARY]
        # The flow pass numbers pages from wherever the section starts, so
        # "page 1" is the first page it used, not a literal 1.
        first_page = min(pages.values())
        actual = "page1" if pages.get(address) == first_page else "page2"
        want = predictions(slack)
        results.append({
            "case": label,
            "bottom_margin": bottom,
            "usable_height": usable,
            "declared_usable_height": usable_for(bottom),
            "boundary_top": PITCH * BOUNDARY,
            "slack": usable - PITCH * BOUNDARY,
            "requested_slack": slack,
            "line": metrics,
            "actual": actual,
            "predicted": want,
            "agrees_with": sorted(n for n, v in want.items() if v == actual),
            "document": path.name,
        })
    return results


def table(results):
    names = list(MEASURES)
    head = (f"{'case':<12} {'bottom':>7} {'usable':>7} {'slack':>6} "
            f"{'actual':>7}  " + "  ".join(f"{n[:9]:>9}" for n in names))
    out = [head, "-" * len(head)]
    for row in results:
        out.append(
            f"{row['case']:<12} {row['bottom_margin']:>7} "
            f"{row['usable_height']:>7} {row['slack']:>6} "
            f"{row['actual']:>7}  "
            + "  ".join(f"{row['predicted'][n]:>9}" for n in names))
    return "\n".join(out)


def verdict(results):
    """Which candidate the flow pass agrees with on every case."""
    survivors = set(MEASURES)
    for row in results:
        survivors &= set(row["agrees_with"])
    return sorted(survivors)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=None,
                        help="where to write the probe packages "
                             "(default: a temporary directory)")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(args.out) if args.out else Path(tmp)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = measure(out_dir, args.dpi)

    print(f"line box as the flow pass measured it: {results[0]['line']}")
    print(f"declared: vertsize {VERTSIZE} spacing {SPACING} "
          f"baseline {BASELINE} pitch {PITCH}")
    print(f"boundary paragraph: index {BOUNDARY} of {PARA_COUNT}, "
          f"analytic top {PITCH * BOUNDARY}")
    print()
    print(table(results))
    print()
    survivors = verdict(results)
    print("the flow pass agrees with: "
          + (", ".join(survivors) if survivors else "no single candidate"))
    print("corpus-consistent candidates (page_fit_probe.py --corpus): "
          + ", ".join(n for n in PFP.MEASURE_ORDER if n in MEASURES))
    print()
    print("path A (cached hp:lineseg) does not exist for a Rigorloom-written "
          "package; path C (Hancom) is NOT RUN.")
    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
