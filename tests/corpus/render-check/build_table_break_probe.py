#!/usr/bin/env python3
"""Author ``table-break-probe.hwpx`` — eleven table-placement variants.

``render-check-01``'s `F47` asked one question this document answers by
measurement: what does Hancom do with a table that does not fit the space
left on the page?  Each case here is one row of that experiment — a
``pageBreak`` value, a row count, and either a fresh page or a page with a
known amount of room already used — and Hancom's own PDF export of the
document is the answer (``docs/research/table-page-break-rule.md``).

Every string is a case label or synthetic filler, so the document carries no
personal data and can be committed to the corpus.

Build:

    python tests/corpus/render-check/build_table_break_probe.py \
        --out tests/corpus/render-check/table-break-probe.hwpx

    python engine/scripts/com_backend.py convert \
        --file tests/corpus/render-check/table-break-probe.hwpx \
        --to   tests/corpus/render-check/table-break-probe.pdf

The writer is ``build_render_check``'s: this module reuses that module's
``hp:tbl`` / ``hp:tc`` / ``hp:secPr`` builders verbatim so the only thing
that differs between the two documents is which cases they carry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import build_render_check as B  # noqa: E402  (path shim above is deliberate)

#: Declared row height, HWPUNIT.  26 rows of it (67 600) is a hair taller than
#: the body box this page geometry gives (65 764), which is exactly the F47
#: geometry the probe exists to explain.
ROW_H = 2600
COL_W = B.BODY_W // 3

#: paraPr ids: ``page_break`` carries ``pageBreakBefore=1``.
PB = B.PP["page_break"][0]
BASE = B.PP["base"][0]

#: id, rows, hp:tbl@pageBreak, repeatHeader, filler lines before the table,
#: whether the table paragraph itself starts a fresh page.
CASES = [
    ("T01", 25, "CELL", 0, 0, True),
    ("T02", 26, "CELL", 1, 0, True),
    ("T03", 30, "CELL", 0, 0, True),
    ("T04", 55, "CELL", 0, 0, True),
    ("T05", 15, "CELL", 0, 20, False),
    ("T06", 15, "TABLE", 0, 20, False),
    ("T07", 15, "NONE", 0, 20, False),
    ("T08", 30, "TABLE", 0, 0, True),
    ("T09", 30, "NONE", 0, 0, True),
    ("T10", 30, "CELL", 1, 0, True),
    ("T11", 27, "CELL", 0, 0, True),
]


def tbl_rows(count: int, tag: str) -> list[str]:
    return ["<hp:tr>" + "".join(
        B.cell("%s R%02d C%d" % (tag, r + 1, c + 1), col=c, row=r,
               width=COL_W, height=ROW_H) for c in range(3)) + "</hp:tr>"
        for r in range(count)]


def table_para(tbl: str, para_pr: int) -> str:
    return ('<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
            '</hp:p>' % (B.oid(), para_pr, B.CP["base"][0], tbl))


def build():
    doc = B.Doc()
    s0 = doc.new_section()
    s0.raw(
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
        '<hp:run charPrIDRef="%d"><hp:t>table placement probe</hp:t></hp:run>'
        '</hp:p>'
        % (B.oid(), BASE, B.CP["base"][0],
           B.sec_pr(width=B.A4_W, height=B.A4_H, landscape="WIDELY",
                    margin=B.MARGIN, col_count=1,
                    furniture=(B.header_ctrl("probe head")
                               + B.footer_ctrl("probe foot"))),
           B.CP["base"][0]))
    manifest = []
    for cid, nrows, pbrk, rh, filler, fresh in CASES:
        s0.blocks.append(
            '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s</hp:p>'
            % (B.oid(), PB,
               B.run("[%s] rows=%d pageBreak=%s repeatHeader=%d filler=%d"
                     % (cid, nrows, pbrk, rh, filler), "label")))
        for i in range(filler):
            s0.blocks.append(
                '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
                ' columnBreak="0" merged="0">%s</hp:p>'
                % (B.oid(), BASE,
                   B.run("%s filler line %02d" % (cid, i + 1), "base")))
        s0.blocks.append(table_para(
            B.table(tbl_rows(nrows, cid), width=COL_W * 3,
                    height=ROW_H * nrows, row_cnt=nrows, col_cnt=3,
                    page_break=pbrk, repeat_header=rh),
            PB if fresh else BASE))
        manifest.append({"id": cid, "rows": nrows, "pageBreak": pbrk,
                         "repeatHeader": rh, "filler": filler,
                         "fresh_page": fresh,
                         "height_hwpunit": ROW_H * nrows})
    return doc, manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(_HERE / "table-break-probe.hwpx"))
    parser.add_argument("--cases", default=None,
                        help="where to write the case sidecar"
                             " (default: <out> with .cases.json)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    doc, cases = build()
    B.assemble(doc).write(out)

    sidecar = (Path(args.cases) if args.cases
               else out.with_suffix("").with_suffix(".cases.json"))
    with sidecar.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({"ok": True, "out": str(out),
                      "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                      "bytes": out.stat().st_size, "cases": len(cases),
                      "sidecar": str(sidecar)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
