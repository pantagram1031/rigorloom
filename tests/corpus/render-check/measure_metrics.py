"""Measure Hancom's line and character metrics off render-check-01.pdf.

Every number this prints is read from the reference PDF's own text layer with
PyMuPDF.  The renderer is never imported: this is the measurement the rules in
``own_render._line_metrics``, ``_spacing_gap_px`` and ``_offset_px`` were
derived from, and it is written up in
``docs/research/line-and-character-metrics.md``.

    python tests/corpus/render-check/measure_metrics.py

The document's own declarations are in ``build_render_check.py``: body text is
10 pt 바탕, labels 11 pt 돋움, every body paragraph ``PERCENT`` 160 unless the
block says otherwise.
"""
from __future__ import annotations

import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, "render-check-01.pdf")

# Hancom exports this A4 document at 595x841 pt against the nominal
# 595.276x841.89, so every measured length is this fraction of its declared
# value.  Divide a measurement by it before comparing to a declared pt.
GEOMETRY_SCALE = 595.0 / 595.276
# Character origins in the PDF sit on a 1/600 in grid.  That is the floor on
# every residual below, and why 0.09 pt counts as exact and 0.8 pt does not.
PDF_GRID_PT = 72.0 / 600.0

# Baseline y of the first and last line of each paragraph measured, as
# (page, first, last).  Read off the PDF once; asserted against, not searched.
PITCH = [
    ("F01-F05 PERCENT 160 @10pt", 16.00,
     [(0, 150.795, 182.900), (0, 224.275, 256.380), (0, 297.874, 329.860),
      (0, 371.354, 403.459), (0, 444.834, 476.939)]),
    ("F06 PERCENT 130 @10pt", 13.00, [(0, 518.433, 570.437)]),
    ("F07 PERCENT 160 @10pt", 16.00, [(0, 608.935, 672.925)]),
    ("F08 PERCENT 200 @10pt", 20.00, [(0, 714.419, 754.436)]),
    ("F09 FIXED 2400 @10pt", 24.00, [(1, 173.211, 269.206)]),
]
# hh:offset runs: (label, run baseline, neutral baseline on the same line).
SHIFTS = [
    ("F16 offset +40, 10pt", 715.740, 711.780, +4.00),
    ("F16 offset -40, 10pt", 723.770, 727.720, -4.00),
    ("F21 offset +35, relSz 65", 341.270, 337.790, +3.50),
    ("F22 offset -35, relSz 65", 375.790, 379.390, -3.50),
]


def main() -> int:
    try:
        import fitz
    except ImportError:
        print("PyMuPDF is not installed; the reference PDF cannot be read")
        return 2
    if not os.path.exists(PDF):
        print("missing reference render: %s" % PDF)
        return 2
    doc = fitz.open(PDF)

    def baselines(pno, lo, hi):
        ys = set()
        for block in doc[pno].get_text("rawdict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    for ch in span["chars"]:
                        y = round(ch["origin"][1], 2)
                        if lo - 0.05 <= y <= hi + 0.05:
                            ys.add(y)
        return sorted(ys)

    print("== 1. line pitch vs declared hh:lineSpacing ==")
    for label, want, spans in PITCH:
        residuals = []
        for pno, lo, hi in spans:
            ys = baselines(pno, lo, hi)
            residuals += [(b - a) / GEOMETRY_SCALE - want
                          for a, b in zip(ys, ys[1:])]
        worst = max(abs(r) for r in residuals)
        print("  %-30s expect %5.2f pt  n=%-3d worst |res| %.4f pt%s"
              % (label, want, len(residuals), worst,
                 "" if worst <= PDF_GRID_PT else "   <-- OFF THE GRID"))

    print()
    print("== 2. the character metrics stay out of the line height ==")
    for label, a, b in (("F13 last line -> F14 label (plain 10pt)",
                         555.113, 578.008),
                        ("F14 last line -> F15 label (ratio 150)",
                         612.650, 635.545),
                        ("F15 last line -> F16 label (relSz 140)",
                         670.188, 693.083)):
        print("  %-42s %.3f pt" % (label, (b - a) / GEOMETRY_SCALE))
    print("  F15 line 1 -> line 2 pitch: %.3f pt  (10pt@160%% = 16.00; "
          "14pt@160%% = 22.40)" % ((670.188 - 654.245) / GEOMETRY_SCALE))
    print("  F14 line 1 -> line 2 pitch: %.3f pt  (a ratio-150 run on the "
          "line)" % ((612.650 - 596.708) / GEOMETRY_SCALE))

    print()
    print("== 3. hh:spacing — a percent of the advance, or of the size? ==")
    s = GEOMETRY_SCALE
    cell_base = (468.946 - 319.027) / 15.0 / s      # 14 cells + 2 half-cells
    cell_tight = (233.394 - 106.262) / 15.0 / s
    latin_base = (505.524 - 468.946) / s            # ABCdef, spacing 0
    latin_tight = (264.457 - 233.394) / s           # ABCdef, spacing -15
    latin_wide = (396.985 - 342.774) / s            # ABCdef + a space, +30
    space_base = (293.961 - 289.043) / s
    space_tight = (106.262 - 101.945) / s
    space_wide = (147.880 - 141.404) / s
    rows = [
        ("full cell (1 em) -15", cell_tight, 10.0 * 0.85, 10.0 - 1.5),
        ("ABCdef           -15", latin_tight, latin_base * 0.85,
         latin_base - 6 * 1.5),
        ("ABCdef + space   +30", latin_wide, (latin_base + 5.0) * 1.3,
         latin_base + 5.0 + 7 * 3.0),
        ("space (0.5 em)   -15", space_tight, 5.0 * 0.85, 5.0 - 1.5),
        ("space (0.5 em)   +30", space_wide, 5.0 * 1.3, 5.0 + 3.0),
    ]
    print("  base: full cell %.4f pt (declared 10.00), space %.4f pt (5.00), "
          "ABCdef %.4f pt" % (cell_base, space_base, latin_base))
    print("  %-22s %-10s %-20s %s"
          % ("span", "measured", "proportional", "flat % of size"))
    for label, got, prop, flat in rows:
        print("  %-22s %-10.4f %-9.4f (%+.4f)  %-9.4f (%+.4f)"
              % (label, got, prop, got - prop, flat, got - flat))

    print()
    print("== 4. hh:ratio — an advance scale, with no vertical effect ==")
    print("  ratio 50  full cell %.4f pt (5.00)   ABCdef %.4f pt (%.4f)"
          % ((170.187 - 97.747) / 14.5 / s, (190.936 - 172.706) / s,
             latin_base * 0.5))
    print("  ratio 150 full cell %.4f pt (15.00)  ABCdef %.4f pt (%.4f)"
          % ((302.474 - 85.034) / 14.5 / s, (364.841 - 309.912) / s,
             latin_base * 1.5))

    print()
    print("== 5. hh:relSz — an advance and size scale ==")
    print("  relSz 60 full cell %.4f pt (6.00)"
          % ((187.219 - 100.266) / 14.5 / s))

    print()
    print("== 6. hh:offset — sign, and which size the percent is of ==")
    residuals = []
    for label, y_run, y_base, want in SHIFTS:
        got = (y_run - y_base) / s
        residuals.append(got - want)
        print("  %-28s drawn %+.3f pt (declared %+.2f, + = LOWER on the page)"
              % (label, got, want))
    print("  worst |residual| %.4f pt over n=%d; the relSz-scaled reading "
          "would put F21/F22 at +-2.275" %
          (max(abs(r) for r in residuals), len(residuals)))

    print()
    print("== 7. paragraph gap vs declared hh:margin ==")
    # baseline_B - baseline_A = last line advance + margin
    #                           + 0.85 * (textheight_B - textheight_A)
    for label, a, b, advance, dth, want in (
            ("title(next 0) -> F01 label(prev 600)",
             108.481, 132.096, 17.6, 0.0, 6.00),
            ("F01 label(next 200) -> body(prev 0)",
             132.096, 150.795, 17.6, -1.0, 2.00),
            ("F01 body(next 0) -> F02 label(prev 600)",
             182.800, 205.575, 16.0, +1.0, 6.00)):
        gap = (b - a) / s - advance - 0.85 * dth
        print("  %-42s %.3f pt (declared %.2f)" % (label, gap, want))
    print("  a bare <hc:prev value=\"600\" unit=\"HWPUNIT\"/> is 6.00 pt: "
          "HWPUNIT at face value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
