"""What line box did the authoring engine give a line carrying an object?

Every number this prints is read out of the ten converted corpus forms' own
cached ``hp:lineseg`` — the authoring engine's answer, not a render of ours.
``own_render`` is imported only to reuse its paragraph and charPr readers; no
page is drawn and no layout of ours is consulted.

    python tests/corpus/render-check/measure_object_lines.py

Written up in ``docs/research/object-line-box.md``; the rules it settles live
in ``own_render._line_metrics``.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")
sys.path.insert(0, os.path.join(ROOT, "engine", "scripts"))

import own_render  # noqa: E402
from own_render import _iattr, _local, Paragraph  # noqa: E402
from own_render import HWPUNIT_PER_PT, OBJECT_SLOT  # noqa: E402


def object_lines(path):
    """One record per cached line that carries at least one inline object."""
    renderer = own_render.OwnRenderer(path)
    out = []
    for index, section in enumerate(renderer.sections):
        renderer._current_section = index
        for el in section.iter():
            if _local(el.tag) != "p":
                continue
            para = Paragraph(el, renderer.defs["para_pr"])
            if not para.linesegs or not para.objects:
                continue
            pr = para.para_pr
            starts = [_iattr(seg, "textpos") for seg in para.linesegs]
            for i, seg in enumerate(para.linesegs):
                start = starts[i]
                end = (starts[i + 1] if i + 1 < len(starts)
                       else len(para.chars))
                objects, run_h, text_h = [], 0, 0
                for offset in range(start, min(end, len(para.chars))):
                    ch, cid = para.chars[offset]
                    height = (renderer._charpr(cid).get("height_pt")
                              or 10.0) * HWPUNIT_PER_PT
                    record = para.object_at.get(offset)
                    if ch == OBJECT_SLOT and record is not None \
                            and not record[3]:
                        objects.append(record[1])
                        run_h = max(run_h, height)
                    else:
                        text_h = max(text_h, height)
                if not objects:
                    continue
                out.append({
                    "doc": os.path.basename(path),
                    "obj": max(renderer._object_extent(e)[1] for e in objects),
                    "out_v": max(sum(renderer._object_out_margin(e)[1::2])
                                 for e in objects),
                    "run_h": int(round(run_h)),
                    "text_h": int(round(text_h)),
                    "vertsize": _iattr(seg, "vertsize"),
                    "textheight": _iattr(seg, "textheight"),
                    "baseline": _iattr(seg, "baseline"),
                    "spacing": _iattr(seg, "spacing"),
                    "kind": pr.get("line_spacing_type", "PERCENT"),
                    "value": pr.get("line_spacing_value", 100),
                })
    return out


def _score(rows, name, predict):
    residuals = [observed - predict(row) for row, observed in rows]
    exact = sum(1 for d in residuals if d == 0)
    worst = max(abs(d) for d in residuals) if residuals else 0
    near = sum(1 for d in residuals if 0 < abs(d) <= 2)
    print("  %-46s exact %3d/%d  within 2 %2d  worst |res| %d"
          % (name, exact, len(residuals), near, worst))


def _leading(height, row):
    if row["kind"] == "PERCENT":
        return int(round(height * row["value"] / 100.0)) - height
    if row["kind"] == "FIXED":
        return row["value"] - height
    return 0


def main() -> int:
    if not os.path.isdir(CORPUS):
        print("missing corpus: %s" % CORPUS)
        return 2
    rows = []
    for name in sorted(os.listdir(CORPUS)):
        if name.endswith(".hwpx"):
            rows += object_lines(os.path.join(CORPUS, name))
    if not rows:
        print("no cached object lines found")
        return 2
    print("cached lines carrying an inline object: %d over %d forms"
          % (len(rows), len({r["doc"] for r in rows})))

    print()
    print("== 1. the line BOX (hp:lineseg@vertsize) ==")
    box = [(r, r["vertsize"]) for r in rows]
    _score(box, "hh:sz@height", lambda r: r["obj"])
    _score(box, "hh:sz@height + hp:outMargin top+bottom",
           lambda r: r["obj"] + r["out_v"])
    _score(box, "max(hh:sz@height, the run's charPr height)",
           lambda r: max(r["obj"], r["run_h"], r["text_h"]))
    _score([(r, r["textheight"]) for r in rows],
           "...and @textheight carries the same number",
           lambda r: r["obj"] + r["out_v"])
    _score([(r, r["baseline"]) for r in rows],
           "@baseline == round(0.85 * that box)",
           lambda r: int(round(own_render.BASELINE_RATIO * r["vertsize"])))

    print()
    print("== 2. the LEADING (hp:lineseg@spacing) ==")
    lead = [(r, r["spacing"]) for r in rows]
    _score(lead, "off the object-sized line box",
           lambda r: _leading(r["vertsize"], r))
    _score(lead, "off the largest declared CHARACTER size",
           lambda r: _leading(max(r["run_h"], r["text_h"]), r))

    print()
    print("== 3. the misses, one line each ==")
    for row in rows:
        want = _leading(max(row["run_h"], row["text_h"]), row)
        if row["spacing"] == want:
            continue
        print("  obj %-6d out %-4d run %-5d text %-5d  %s %-4d  "
              "spacing %-5d rule %-5d  delta %+d  %s"
              % (row["obj"], row["out_v"], row["run_h"], row["text_h"],
                 row["kind"], row["value"], row["spacing"], want,
                 row["spacing"] - want, row["doc"][:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
