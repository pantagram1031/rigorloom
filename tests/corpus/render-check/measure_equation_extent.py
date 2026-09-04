"""How much vertical room does Hancom reserve for an inline ``hp:equation``?

The renderer takes an equation's inline slot from the declared
``hp:sz@height``.  ``docs/research/object-line-box.md`` §5 showed that Hancom
does not: `render-check-01` declares 2400 / 2400 / 3600 / 3600 and Hancom
reserves 2252 / 1304 / 2696 / 2108.  This script is the measurement that names
what Hancom reserves instead, and it is deliberately independent of the rule
it settles: nothing here reads ``_equation_extent_height``.

    python tests/corpus/render-check/measure_equation_extent.py
    python tests/corpus/render-check/measure_equation_extent.py OTHER.hwpx

With no argument it measures ``render-check-01`` against Hancom's own
reference PDF.  With a path it prints that document's declared extents against
this renderer's own layout of the same scripts — which is the cross-check for
a Hancom-**authored** document, where the declared extent *is* Hancom's own
measurement of the equation and no PDF is needed.  Nothing about the argument
document is written to disk; the aggregate is what the write-up quotes.

Written up in ``docs/research/equation-line-box.md``.
"""
from __future__ import annotations

import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
HWPX = os.path.join(HERE, "render-check-01.hwpx")
PDF = os.path.join(HERE, "render-check-01.pdf")
sys.path.insert(0, os.path.join(ROOT, "engine", "scripts"))

import own_render  # noqa: E402
import hwpeqn_parse  # noqa: E402
from own_render import _kid, _kids, _local, _iattr  # noqa: E402
from own_render import HWPUNIT_PER_INCH, HWPUNIT_PER_PT  # noqa: E402

# The renderer's own pinned measurement resolution — see
# ``own_render.EQUATION_EXTENT_DPI``.  Imported rather than re-declared so
# this script cannot drift away from the rule it measures; §5 below shows
# what pinning it is worth.
EXTENT_DPI = own_render.EQUATION_EXTENT_DPI

# The four label paragraphs that bracket render-check-01's equation blocks.
# Each interval is label -> equation paragraph -> label, and the geometry
# outside the equation is identical in all four, so the interval's advance is
# a constant plus the equation's own box.
LABELS = ["[F36]", "[F37]", "[F38]", "[F39]", "[F40]"]


def equations(renderer):
    """Every ``hp:equation`` in document order, with its declared extent."""
    out = []
    for section in renderer.sections:
        for el in section.iter():
            if _local(el.tag) != "equation":
                continue
            sz = _kid(el, "sz")
            script_el = _kid(el, "script")
            out.append({
                "el": el,
                "declared": _iattr(sz, "height") if sz is not None else 0,
                "base_line": _iattr(el, "baseLine"),
                "base_unit": _iattr(el, "baseUnit") or 1000,
                "height_rel_to": (sz.get("heightRelTo") if sz is not None
                                  else None),
                "protect": sz.get("protect") if sz is not None else None,
                "line_mode": el.get("lineMode"),
                "version": el.get("version"),
                "script": ("".join(script_el.itertext())
                           if script_el is not None else "").strip(),
            })
    return out


def laid_out_height(renderer, record, dpi=EXTENT_DPI):
    """This renderer's own layout of the script, in HWPUNIT.

    ``nominal`` is the layout tree's ascent + descent — the stacked character
    cells the equation is built on.  ``ink`` is the rectangle the glyphs
    actually mark, which is what ``_render_equation`` fits against ``hp:sz``.
    Both are wanted: the question this script answers is which of them Hancom
    reserves a line box for.
    """
    if not record["script"]:
        return None, None
    tree, _info = hwpeqn_parse.parse(record["script"])
    renderer._eq_face = renderer._equation_face(record["el"].get("font"))
    size = max(2.0, record["base_unit"] * dpi / HWPUNIT_PER_INCH)
    laid = renderer._eq_layout(tree, size)
    _x0, y0, _x1, y1 = renderer._eq_bounds(laid)
    scale = HWPUNIT_PER_INCH / dpi
    return (laid.asc + laid.desc) * scale, (y1 - y0) * scale


def reference_reserves():
    """What Hancom reserved for each of render-check-01's four equations.

    Derived from the reference PDF's own text layer, with no model of the
    surrounding paragraphs: each label-to-label advance is ``C + H``, where
    ``C`` is everything except the equation box and is the same in all four
    intervals.  ``C`` is read off THIS renderer's own flow pass — where the
    same four advances are ``C + declared`` — so the derivation needs the two
    engines to agree about the surrounding geometry and nothing else, which
    ``measure_block_drift.py`` shows they do to 0.05 pt over 48 blocks.
    Returns ``(reserves, constants)``; the constants are printed because
    their being equal is what makes the derivation sound.
    """
    import fitz

    renderer = own_render.OwnRenderer(HWPX, block_layout="computed")
    geometry = renderer.page_geometry()
    draw = renderer._scratch_draw()
    column, _gap, _count = renderer.column_geometry(geometry)
    blocks = renderer._flow_blocks(draw, column)
    placements, _pages, _counters = renderer.flow(draw)
    first = {}
    for record in placements:
        first.setdefault(record["block"], record)

    doc = fitz.open(PDF)
    page_pt = doc[0].rect.height

    ours = {}
    for position, el in enumerate(_kids(renderer.sections[0], "p")):
        text = "".join("".join(node.itertext())
                       for node in el.iter() if _local(node.tag) == "t")
        for label in LABELS:
            if text.strip().startswith(label):
                record = first.get(renderer.paragraph_index.get(id(el)))
                block = blocks[position]
                baseline = block["rows"][0]["extent"] if block["rows"] else 0
                ours[label] = (record["page"] * page_pt
                               + (geometry["body_top"] + record["top"]
                                  + baseline) / 100.0)
    reference = {}
    for pno in range(len(doc)):
        for block in doc[pno].get_text("rawdict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = "".join(ch["c"] for ch in span["chars"])
                    for label in LABELS:
                        if text.startswith(label) and label not in reference:
                            reference[label] = (pno * page_pt
                                                + span["chars"][0]["origin"][1])
    if len(ours) != len(LABELS) or len(reference) != len(LABELS):
        raise SystemExit("could not locate every equation label")

    # What THIS renderer reserved for each equation, whatever rule it is
    # running.  It cancels out of the derivation below — ``our_adv`` is
    # ``C + ours`` — so the number this function returns for Hancom does not
    # depend on the rule under test, and the same script re-derives the same
    # four reserves before and after the rule changes.
    ours_reserved = []
    for record in equations(renderer):
        _left, top, _right, bottom = \
            renderer._object_out_margin(record["el"])
        ours_reserved.append(renderer._object_extent(record["el"])[1]
                             + top + bottom)
    reserves, constants = [], []
    for index, label in enumerate(LABELS[:-1]):
        nxt = LABELS[index + 1]
        our_adv = ours[nxt] - ours[label]
        ref_adv = reference[nxt] - reference[label]
        constant = our_adv - ours_reserved[index] / float(HWPUNIT_PER_PT)
        constants.append(constant)
        reserves.append(int(round((ref_adv - constant) * HWPUNIT_PER_PT)))
    return reserves, constants


def report_render_check():
    try:
        import fitz  # noqa: F401
    except ImportError:
        print("PyMuPDF is not installed; the reference PDF cannot be read")
        return 2
    reserves, constants = reference_reserves()
    print("== 1. the interval constant, which must not vary ==")
    print("   %s pt  (spread %.3f pt)"
          % (" ".join("%.2f" % c for c in constants),
             max(constants) - min(constants)))
    print()

    renderer = own_render.OwnRenderer(HWPX)
    records = equations(renderer)
    print("== 2. declared vs reserved vs this renderer's own layout ==")
    print("%-34s %8s %8s %8s %8s %7s %7s"
          % ("script", "declared", "reserved", "nominal", "ink",
             "res/dec", "nom/res"))
    ratios = []
    for record, reserved in zip(records, reserves):
        nominal, ink = laid_out_height(renderer, record)
        ratios.append(nominal / reserved)
        print("%-34s %8d %8d %8.0f %8.0f %7.3f %7.3f"
              % (record["script"][:34], record["declared"], reserved,
                 nominal, ink, reserved / float(record["declared"]),
                 nominal / reserved))
    print()
    print("== 3. attributes, which are constant and therefore say nothing ==")
    for record in records:
        print("   heightRelTo=%s protect=%s baseLine=%s lineMode=%s "
              "baseUnit=%d version=%s"
              % (record["height_rel_to"], record["protect"],
                 record["base_line"], record["line_mode"],
                 record["base_unit"], record["version"]))
    print()
    print("== 4. candidate rules, residual against the reserve ==")
    candidates = {
        "declared hp:sz@height (today)":
            [record["declared"] for record in records],
        "nominal content height":
            [laid_out_height(renderer, r)[0] for r in records],
        "ink content height":
            [laid_out_height(renderer, r)[1] for r in records],
        "max(nominal, ink)":
            [max(laid_out_height(renderer, r)) for r in records],
        "min(max(nominal, ink), declared)  ADOPTED":
            [min(max(laid_out_height(renderer, r)), r["declared"])
             for r in records],
    }
    for name, predicted in candidates.items():
        errors = [p - a for p, a in zip(predicted, reserves)]
        print("   %-32s worst %+7.0f HWPUNIT (%.1f%%)  mean |e| %6.0f"
              % (name, max(errors, key=abs),
                 100.0 * max(abs(e) / a for e, a in zip(errors, reserves)),
                 statistics.fmean(abs(e) for e in errors)))
    print()
    print("== 5. the same layout at three resolutions ==")
    for dpi in (300, 600, 1200):
        print("   %5d dpi  %s" % (dpi, " ".join(
            "%.1f" % laid_out_height(renderer, r, dpi)[0] for r in records)))
    return 0


def report_declared(path):
    """A Hancom-authored document: the declared extent IS Hancom's answer."""
    renderer = own_render.OwnRenderer(path)
    records = equations(renderer)
    print("== declared hp:sz@height vs this renderer's own layout ==")
    print("   %d equations" % len(records))
    nominal_ratio, ink_ratio, clamped = [], [], []
    rel_to, modes = set(), set()
    for record in records:
        nominal, ink = laid_out_height(renderer, record)
        if nominal is None or not record["declared"]:
            continue
        nominal_ratio.append(nominal / record["declared"])
        ink_ratio.append(ink / record["declared"])
        clamped.append(min(max(nominal, ink), record["declared"])
                       / record["declared"])
        rel_to.add(record["height_rel_to"])
        modes.add(record["line_mode"])
    for name, series in (("nominal / declared", nominal_ratio),
                         ("ink / declared", ink_ratio),
                         ("adopted / declared", clamped)):
        print("   %-34s mean %.4f  min %.4f  max %.4f  sd %.4f"
              % (name, statistics.fmean(series), min(series), max(series),
                 statistics.pstdev(series)))
    print("   heightRelTo %s  lineMode %s" % (sorted(rel_to), sorted(modes)))
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return report_declared(sys.argv[1])
    return report_render_check()


if __name__ == "__main__":
    sys.exit(main())
