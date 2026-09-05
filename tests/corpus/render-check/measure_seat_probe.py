#!/usr/bin/env python3
"""Where a paragraph is seated, one declared attribute at a time.

``layout_divergence.py``'s seat pass says which of three terms carries the
first seat difference on a corpus page — the predecessor's seat, the
predecessor's advance, or the gap between the two.  On a Hancom form that
question is answered against the authoring engine's own cache.  This probe
asks it where there is no cache to answer against.

**Path A does not exist here, and path C is not run.**  A package this repo
writes carries no ``hp:lineseg``, so ``--layout-policy cache`` has nothing to
read and the flow pass is the only layout there is.  What the render is
compared against instead is the ANALYTIC seat: the height the paragraph's own
``hh:paraPr`` and ``hh:charPr`` say it should have, computed here from the
values this module authored the document with rather than read back out of
the renderer.  No Hancom reference PDF is exported and none is measured, so
nothing below is evidence about what Hancom itself would do; it is evidence
about whether this renderer's flow pass obeys the document's own declarations.

The analytic model, and every part of it is already measured elsewhere in
``engine/references/own-render-notes.md``:

* a line's height is the tallest character cell on it; an INLINE object's
  cell is its ``hp:sz`` box PLUS its own vertical ``hp:outMargin`` (measured
  on the corpus's 79 object lines, ``docs/research/object-line-box.md``);
* the line spacing is computed from the tallest RUN character size on the
  line, not from that object cell, and a run that emits no text still
  declares one (``hh:charPr@height`` is a property of the ``hp:run``);
* ``PERCENT v`` makes the pitch ``round(pitch_height * v / 100)``,
  ``FIXED v`` makes it ``v`` and ``BETWEEN_LINES v`` makes it
  ``line height + v``; the advance is that pitch;
* an EMPTY paragraph is one line by the same rules — its height is the
  tallest shape its runs declare and its advance is that pitch — which is
  what the ``empty_h*`` grid sweeps;
* a paragraph carrying an ANCHORED object reserves
  ``vertOffset + outMargin.top + height + outMargin.bottom`` and its block
  height is the larger of that and its own lines;
* the gap between two paragraphs is ``prev@margin/next + this@margin/prev``.

Every case is one attribute changed against the same baseline document, so a
row of the table below is a derivative: what moves when line spacing, an
empty run's character height, an object's outer margin or ``treatAsChar``
changes, and nothing else does.

Every string in the document is a case label or synthetic filler, so the
package carries no personal data.

    python tests/corpus/render-check/measure_seat_probe.py [--out DIR]
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

def _extra_pp(name: str, **kw) -> int:
    """Register a paraPr this probe needs and ``build_render_check`` lacks.

    ``header_xml`` reads ``PARA_PRS`` when it is called, so appending here is
    enough; the id is ``len(PP) - 1``, which is where the new XML lands.
    """
    idx = B._pp(name, **kw)
    B.PARA_PRS.append(B.para_pr(idx, **kw))
    return idx


def _extra_cp(name: str, **kw) -> int:
    """The ``_extra_pp`` of character shapes."""
    idx = B._cp(name, **kw)
    B.CHAR_PRS.append(B.char_pr(idx, **kw))
    return idx


#: The spacing types the empty-paragraph grid below needs.  ``BETWEEN_LINES``
#: (줄 간격 '여백만 지정') adds its value to the line box rather than scaling
#: it, and no ``build_render_check`` paraPr declares one.
_extra_pp("ls_180", align="JUSTIFY", line_value=180)
_extra_pp("ls_between_600", align="JUSTIFY", line_type="BETWEEN_LINES",
          line_value=600)
_extra_cp("pt15", height=1500)

#: The probe's own table, so the outer margin and ``treatAsChar`` are dials
#: rather than the constants ``build_render_check.table`` bakes in.
TBL_ROWS, TBL_COLS = 2, 2
ROW_H = 2600
TBL_H = ROW_H * TBL_ROWS


def probe_table(*, out_margin: int, treat_as_char: bool, tag: str) -> str:
    col_w = B.BODY_W // TBL_COLS
    rows = ["<hp:tr>" + "".join(
        B.cell("%s r%dc%d" % (tag, r, c), col=c, row=r, width=col_w,
               height=ROW_H) for c in range(TBL_COLS)) + "</hp:tr>"
        for r in range(TBL_ROWS)]
    return (
        '<hp:tbl id="%d" zOrder="0" numberingType="TABLE"'
        ' textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0"'
        ' dropcapstyle="None" pageBreak="TABLE" repeatHeader="0" rowCnt="%d"'
        ' colCnt="%d" cellSpacing="0" borderFillIDRef="%d" noAdjust="0">'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d"'
        ' heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="%d" affectLSpacing="0" flowWithText="1"'
        ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
        ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0"'
        ' horzOffset="0"/>'
        '<hp:outMargin left="%d" right="%d" top="%d" bottom="%d"/>'
        '<hp:inMargin left="140" right="140" top="140" bottom="140"/>'
        '%s</hp:tbl>'
        % (B.oid(), TBL_ROWS, TBL_COLS, B.BF_SOLID, col_w * TBL_COLS, TBL_H,
           1 if treat_as_char else 0, out_margin, out_margin, out_margin,
           out_margin, "".join(rows)))


def probe_picture(*, out_margin: int, treat_as_char: bool) -> str:
    """``build_render_check.picture`` with its zero outer margin opened up."""
    xml = B.picture(treat_as_char=treat_as_char, text_wrap="TOP_AND_BOTTOM")
    return xml.replace(
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>',
        '<hp:outMargin left="%d" right="%d" top="%d" bottom="%d"/>'
        % (out_margin, out_margin, out_margin, out_margin))


# --- the document ----------------------------------------------------------
#: The baseline paragraph list.  Every case is this with ONE field changed.
#: ``pp`` names a ``build_render_check`` paraPr, ``cp`` a charPr; ``obj`` is
#: the object the paragraph carries and ``margin`` that object's outer margin.
BASELINE = [
    {"id": "P0", "kind": "text", "pp": "base", "cp": "base"},
    {"id": "P1", "kind": "text", "pp": "base", "cp": "base"},
    {"id": "P2", "kind": "empty", "pp": "base", "cp": "base"},
    {"id": "P3", "kind": "empty", "pp": "base", "cp": "base",
     "obj": "pic", "margin": 0, "treat_as_char": True},
    {"id": "P4", "kind": "empty", "pp": "base", "cp": "base",
     "obj": "tbl", "margin": 0, "treat_as_char": True},
    {"id": "P5", "kind": "empty", "pp": "base", "cp": "base",
     "obj": "tbl", "margin": 0, "treat_as_char": False},
    {"id": "P6", "kind": "text", "pp": "base", "cp": "base"},
]

#: ``(case label, paragraph id, ((field, value), …))``.  Every case but the
#: empty-paragraph grid below changes exactly ONE field, so its row of the
#: table is a derivative of that one declaration.
CASES = [
    ("baseline", None, ()),
    ("empty_ls_130", "P2", (("pp", "ls_130"),)),
    ("empty_ls_200", "P2", (("pp", "ls_200"),)),
    ("empty_ls_fixed_2400", "P2", (("pp", "ls_fixed"),)),
    ("empty_charpr_8pt", "P2", (("cp", "pt8"),)),
    ("empty_charpr_14pt", "P2", (("cp", "pt14"),)),
    ("empty_charpr_24pt", "P2", (("cp", "pt24"),)),
    ("empty_margin_prev_next", "P2", (("pp", "label"),)),
    ("inline_pic_margin_141", "P3", (("margin", 141),)),
    ("inline_pic_margin_283", "P3", (("margin", 283),)),
    ("inline_tbl_margin_141", "P4", (("margin", 141),)),
    ("inline_tbl_margin_283", "P4", (("margin", 283),)),
    ("inline_tbl_charpr_24pt", "P4", (("cp", "pt24"),)),
    ("inline_tbl_ls_200", "P4", (("pp", "ls_200"),)),
    ("anchored_tbl_margin_141", "P5", (("margin", 141),)),
    ("anchored_tbl_margin_283", "P5", (("margin", 283),)),
    ("inline_tbl_becomes_anchored", "P4", (("treat_as_char", False),)),
    ("anchored_tbl_becomes_inline", "P5", (("treat_as_char", True),)),
]

#: The empty paragraph's own height, swept across the two declarations that
#: are supposed to set it.  ``P2`` is the empty paragraph; every other
#: paragraph on the page is the baseline's, so the read-out ``P6`` moves by
#: exactly what ``P2``'s block height does.  The corpus says an empty
#: paragraph is ONE line whose ``vertsize`` is the tallest character shape
#: its runs declare and whose advance follows the paragraph's own
#: ``hh:lineSpacing`` — 101 of 101 cached empty top-level paragraphs on
#: ``vertsize``, 91 of 101 on ``spacing`` with every miss inside ±2 HWPUNIT.
EMPTY_HEIGHT_GRID = [
    ("h%s_%s" % (height, spacing), (("cp", char_pr), ("pp", para_pr)))
    for height, char_pr in (("10pt", "base"), ("12pt", "pt12"),
                            ("15pt", "pt15"))
    for spacing, para_pr in (("pct160", "ls_160"), ("pct180", "ls_180"),
                             ("pct200", "ls_200"), ("fixed2400", "ls_fixed"),
                             ("between600", "ls_between_600"))
]
CASES.extend(("empty_" + label, "P2", changes)
             for label, changes in EMPTY_HEIGHT_GRID)


def case_paragraphs(paragraph_id, changes):
    out = []
    for spec in BASELINE:
        spec = dict(spec)
        if spec["id"] == paragraph_id:
            for field, value in changes:
                spec[field] = value
        out.append(spec)
    return out


def char_height_hwp(name: str) -> int:
    """The ``hh:charPr@height`` this module declared for ``name``, HWPUNIT."""
    return B.CP[name][1].get("height", 1000)


def para_spacing(name: str):
    """``(type, value)`` for a ``build_render_check`` paraPr."""
    kw = B.PP[name][1]
    return kw.get("line_type", "PERCENT"), kw.get("line_value", 160)


def para_margins(name: str):
    kw = B.PP[name][1]
    return kw.get("prev", 0), kw.get("nxt", 0)


def object_height(spec) -> int:
    if spec.get("obj") == "pic":
        return B.IMG_H
    if spec.get("obj") == "tbl":
        return TBL_H
    return 0


def analytic_advance(spec) -> int:
    """What the paragraph's own declarations say its block height is."""
    char_h = char_height_hwp(spec["cp"])
    kind, value = para_spacing(spec["pp"])
    inline = spec.get("obj") and spec.get("treat_as_char", True)
    margin = spec.get("margin", 0)
    vertsize = ((object_height(spec) + 2 * margin) if inline else char_h)
    pitch_height = char_h
    if kind == "PERCENT":
        spacing = int(round(pitch_height * value / 100.0)) - pitch_height
    elif kind == "FIXED":
        spacing = value - pitch_height
    elif kind in ("BETWEEN_LINES", "ATLEAST", "AT_LEAST"):
        # 여백만 지정: the value is added BELOW the line box, it does not
        # scale it.
        spacing = max(0, value)
    else:
        spacing = 0
    advance = vertsize + spacing
    if spec.get("obj") and not spec.get("treat_as_char", True):
        # An anchored object does not sit on a line: it reserves its own slot
        # from the paragraph's seat, and the block is the taller of the two.
        advance = max(advance, object_height(spec) + 2 * margin)
    return advance


def analytic_seats(specs):
    """``{id: (top, advance)}`` down one page, from the declarations alone."""
    out = {}
    top = 0
    previous_next = 0
    for spec in specs:
        prev_margin, next_margin = para_margins(spec["pp"])
        top += previous_next + prev_margin
        advance = analytic_advance(spec)
        out[spec["id"]] = (top, advance)
        top += advance
        previous_next = next_margin
    return out


def build_document(specs, label):
    doc = B.Doc()
    section = doc.new_section()
    for index, spec in enumerate(specs):
        body = ""
        if spec.get("obj") == "pic":
            body = probe_picture(out_margin=spec.get("margin", 0),
                                 treat_as_char=spec.get("treat_as_char", True))
        elif spec.get("obj") == "tbl":
            body = probe_table(out_margin=spec.get("margin", 0),
                               treat_as_char=spec.get("treat_as_char", True),
                               tag=spec["id"])
        if spec["kind"] == "text":
            body += "<hp:t>%s</hp:t>" % B.esc(
                "%s %s seat probe line" % (label, spec["id"]))
        elif not body:
            body = "<hp:t/>"
        run = '<hp:run charPrIDRef="%d">%s</hp:run>' % (B.CP[spec["cp"]][0],
                                                        body)
        head = ""
        if index == 0:
            head = ('<hp:run charPrIDRef="%d">%s</hp:run>'
                    % (B.CP["base"][0],
                       B.sec_pr(width=B.A4_W, height=B.A4_H,
                                landscape="WIDELY", margin=B.MARGIN,
                                col_count=1, furniture="")))
        section.raw(
            '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s%s</hp:p>'
            % (B.oid(), B.PP[spec["pp"]][0], head, run))
    return doc


def rendered_seats(path, dpi):
    """``{address: (page, top, advance)}`` from the flow pass, plus the facts.

    Rendered under ``computed`` explicitly.  The provenance rule would pick
    that anyway for a package this repo wrote, and pinning it says so rather
    than relying on the detection.
    """
    renderer = LD.TracingRenderer(path, dpi=dpi,
                                  layout_policy=own_render.LAYOUT_POLICY_COMPUTED)
    renderer.render()
    seats = {}
    for (address, page), seat in renderer.flow_seats.items():
        current = seats.get(address)
        if current is None or page < current[0]:
            seats[address] = (page, seat["top_hwp"], 0)
        seats[address] = (seats[address][0], seats[address][1],
                          seats[address][2] + (seat["height_hwp"] or 0))
    facts = {a: f for a, f in renderer.paragraph_facts().items()
             if f.get("top_level")}
    return seats, facts


def measure(out_dir, dpi):
    results = []
    for label, paragraph_id, changes in CASES:
        specs = case_paragraphs(paragraph_id, changes)
        doc = build_document(specs, label)
        path = Path(out_dir) / ("seat-probe-%s.hwpx" % label)
        B.assemble(doc).write(path)
        seats, facts = rendered_seats(path, dpi)
        expected = analytic_seats(specs)
        addresses = sorted(facts)
        rows = []
        for index, spec in enumerate(specs):
            address = addresses[index] if index < len(addresses) else None
            seat = seats.get(address)
            want_top, want_advance = expected[spec["id"]]
            rows.append({
                "paragraph": spec["id"],
                "address": address,
                "page": None if seat is None else seat[0],
                "top_hwp": None if seat is None else seat[1],
                "advance_hwp": None if seat is None else seat[2],
                "expected_top_hwp": want_top,
                "expected_advance_hwp": want_advance,
                "delta_top_hwp": (None if seat is None
                                  else seat[1] - want_top),
                "delta_advance_hwp": (None if seat is None
                                      else seat[2] - want_advance),
                "cached_linesegs": len(
                    (facts.get(address) or {}).get("linesegs") or []),
            })
        results.append({
            "case": label, "changed": None if not changes else
            {"paragraph": paragraph_id,
             "fields": [{"field": f, "value": v} for f, v in changes]},
            "document": path.name,
            "paragraphs": rows,
        })
    return results


def table(results):
    baseline = {row["paragraph"]: row
                for row in results[0]["paragraphs"]}
    head = (f"{'case':<28} {'para':<5} {'top':>8} {'advance':>8} "
            f"{'want top':>9} {'want adv':>9} {'d top':>7} {'d adv':>7} "
            f"{'vs baseline top':>16}")
    out = [head, "-" * len(head)]
    for result in results:
        for row in result["paragraphs"]:
            base = baseline.get(row["paragraph"]) or {}
            shift = (None if row["top_hwp"] is None
                     or base.get("top_hwp") is None
                     else row["top_hwp"] - base["top_hwp"])
            out.append(
                f"{result['case']:<28} {row['paragraph']:<5} "
                f"{row['top_hwp']:>8} {row['advance_hwp']:>8} "
                f"{row['expected_top_hwp']:>9} "
                f"{row['expected_advance_hwp']:>9} "
                f"{row['delta_top_hwp']:>+7} {row['delta_advance_hwp']:>+7} "
                f"{('' if shift is None else format(shift, '+')):>16}")
        out.append("")
    return "\n".join(out)


def summary(results):
    """One line per case: the read-out paragraph and where it moved to."""
    last = BASELINE[-1]["id"]
    baseline = {row["paragraph"]: row for row in results[0]["paragraphs"]}
    head = (f"{'case':<28} {'changed':<34} {'P6 top':>9} {'want':>9} "
            f"{'d want':>7} {'vs baseline':>12}")
    out = [head, "-" * len(head)]
    for result in results:
        row = next(r for r in result["paragraphs"] if r["paragraph"] == last)
        changed = ("-" if result["changed"] is None else
                   "%s %s" % (result["changed"]["paragraph"],
                              " ".join("%s=%s" % (f["field"], f["value"])
                                       for f in result["changed"]["fields"])))
        shift = row["top_hwp"] - baseline[last]["top_hwp"]
        out.append(f"{result['case']:<28} {changed:<34} "
                   f"{row['top_hwp']:>9} {row['expected_top_hwp']:>9} "
                   f"{row['delta_top_hwp']:>+7} {shift:>+12}")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=None,
                        help="where to write the probe packages "
                             "(default: a temporary directory)")
    parser.add_argument("--dpi", type=int, default=own_render.DEFAULT_DPI)
    parser.add_argument("--json", default=None,
                        help="also write the full per-paragraph result here")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(args.out) if args.out else Path(tmp)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = measure(out_dir, args.dpi)

    print(table(results))
    print()
    print(summary(results))
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
