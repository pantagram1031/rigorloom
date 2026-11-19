# -*- coding: utf-8 -*-
"""Build the shared addressing fixture (doc-core-api.md, ruling 2026-11-19 04:30Z).

    python tests/fixtures/doc_core/build_addressing.py [BASE.hwpx]

BASE is the package whose header and metadata are kept (default: the engine's forms/blank_a4.hwpx, found
through RIGORLOOM_HWP_ENGINE). Writes addressing.hwpx and addressing.json next to this file. The JSON is what
both implementations must answer on it (rt_doc: tests/test_rt_doc_addressing.py; the engine runs the same
file). The document:

    p0  신청서 양식
    p1  t0 (id 5001), 3 x 3:  성명 | _ | 비고 (rowSpan 2, so r1/c2 is covered)
                              주소 | _ |
                              연락 | t0/r2/c1/t0 (id 5002, 2 x 2: 전화 | _ / 메일 | _) | 끝
    p2  hp:switch: hp:case holds t1 (id 5003, 1 x 2: 분류 | _); hp:default holds id 5004 (no address)
    p3  두 번째 양식
    p4  t2 (id 5005), 2 x 2: 성명 | _ / 주소 | _     (the same labels as t0)
    p5  성명:                                        (two label lines with the same label)
    p6  성명:
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SECTION = "Contents/section0.xml"
FIXED_TIME = (2026, 11, 19, 0, 0, 0)
CASE_NS = "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"
_pid = [100]


def place_id(*parts):
    return hashlib.sha256("\0".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:12]


def para(inner="", text=None):
    _pid[0] += 1
    run = '<hp:run charPrIDRef="0">%s%s</hp:run>' % (inner, "<hp:t>%s</hp:t>" % text if text is not None else "")
    return ('<hp:p id="%d" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">%s</hp:p>'
            % (_pid[0], run))


def cell(r, c, body, width, rs=1, cs=1):
    return ('<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="1">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER">%s</hp:subList>'
            '<hp:cellAddr colAddr="%d" rowAddr="%d"/><hp:cellSpan colSpan="%d" rowSpan="%d"/>'
            '<hp:cellSz width="%d" height="%d"/><hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
            '</hp:tc>' % (body, c, r, cs, rs, width, 1800 * rs))


def table(tid, rows, cols, trs, width):
    return ('<hp:tbl id="%s" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" '
            'lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="%d" colCnt="%d" '
            'cellSpacing="0" borderFillIDRef="1" noAdjust="0"><hp:sz width="%d" widthRelTo="ABSOLUTE" '
            'height="%d" heightRelTo="ABSOLUTE" protect="0"/><hp:pos treatAsChar="0" affectLSpacing="0" '
            'flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" '
            'vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/><hp:outMargin left="283" '
            'right="283" top="283" bottom="283"/><hp:inMargin left="510" right="510" top="141" bottom="141"/>'
            '%s</hp:tbl>' % (tid, rows, cols, width, 1800 * rows, "".join("<hp:tr>%s</hp:tr>" % x for x in trs)))


def two_by_two(tid, labels, width):
    w = width // 2
    return table(tid, len(labels), 2, [cell(r, 0, para(text=lab), w) + cell(r, 1, para(text=""), w)
                                       for r, lab in enumerate(labels)], width)


def section(base_xml):
    head = base_xml[:base_xml.index("</hp:run></hp:p>")]          # the first paragraph's run, up to its end
    tail = base_xml[base_xml.index("</hp:run></hp:p>") + len("</hp:run></hp:p>"):]
    w = 14000
    nested = two_by_two("5002", ["전화", "메일"], w - 1200)
    t0 = table("5001", 3, 3, [
        cell(0, 0, para(text="성명"), w) + cell(0, 1, para(text=""), w) + cell(0, 2, para(text="비고"), w, rs=2),
        cell(1, 0, para(text="주소"), w) + cell(1, 1, para(text=""), w),
        cell(2, 0, para(text="연락"), w) + cell(2, 1, para(nested), w) + cell(2, 2, para(text="끝"), w),
    ], 3 * w)
    switch = ('<hp:switch><hp:case hp:required-namespace="%s">%s</hp:case><hp:default>%s</hp:default></hp:switch>'
              % (CASE_NS, two_by_two("5003", ["분류"], 2 * w), two_by_two("5004", ["분류(구)"], 2 * w)))
    body = (head + "<hp:t>신청서 양식</hp:t></hp:run></hp:p>" + para(t0) + para(switch) + para(text="두 번째 양식")
            + para(two_by_two("5005", ["성명", "주소"], 2 * w)) + para(text="성명: ") + para(text="성명: "))
    return body + tail


def expected():
    cells = [("t0/r0/c1", "5001", 0, 1, "성명"), ("t0/r1/c1", "5001", 1, 1, "주소"),
             ("t0/r2/c1/t0/r0/c1", "5002", 0, 1, "전화"), ("t0/r2/c1/t0/r1/c1", "5002", 1, 1, "메일"),
             ("t1/r0/c1", "5003", 0, 1, "분류"),
             ("t2/r0/c1", "5005", 0, 1, "성명"), ("t2/r1/c1", "5005", 1, 1, "주소")]
    return {
        "_doc": "What rt_doc and the engine must both answer on addressing.hwpx (doc-core-api.md, ruling "
                "2026-11-19 04:30Z). place ids: place_id(*parts) = sha256('\\0'.join(parts))[:12].",
        "tables": [{"at": "t0", "id": "5001", "rows": 3, "cols": 3},
                   {"at": "t0/r2/c1/t0", "id": "5002", "rows": 2, "cols": 2},
                   {"at": "t1", "id": "5003", "rows": 1, "cols": 2},
                   {"at": "t2", "id": "5005", "rows": 2, "cols": 2}],
        "text": {"t0/r0/c0": "성명", "t0/r2/c1/t0/r0/c0": "전화", "t0/r2/c1/t0/r1/c0/p0": "메일",
                 "t1/r0/c0": "분류", "t2/r1/c0": "주소", "t0/r0/c2": "비고", "p3": "두 번째 양식"},
        "covered": {"t0/r1/c2": "t0/r0/c2"},
        "bad_address": ["t3", "t0/r2/c1/t1", "t0/r9/c0", "t0/r0/c1/t0", "p99"],
        "cell_places": [{"at": at, "id": place_id("cell", tid, r, c), "label": lab, "parts": ["cell", tid, r, c]}
                        for at, tid, r, c, lab in cells],
        "label_lines": [{"at": "p5", "id": place_id("field", "성명", 0), "parts": ["field", "성명", 0]},
                        {"at": "p6", "id": place_id("field", "성명", 1), "parts": ["field", "성명", 1]}],
    }


def build(base: Path, out: Path):
    with zipfile.ZipFile(base) as z:
        members = [(i, z.read(i)) for i in z.infolist()]
    with zipfile.ZipFile(out, "w") as w:
        for info, data in members:
            if info.filename == SECTION:
                data = section(data.decode("utf-8")).encode("utf-8")
            elif info.filename == "Preview/PrvText.txt":
                data = b""
            zi = zipfile.ZipInfo(info.filename, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            w.writestr(zi, data)
    return out


def main(argv):
    if len(argv) > 1:
        base = Path(argv[1])
    else:
        eng = os.environ.get("RIGORLOOM_HWP_ENGINE", "").strip()
        if not eng:
            sys.exit("usage: build_addressing.py BASE.hwpx (or set RIGORLOOM_HWP_ENGINE to use forms/blank_a4.hwpx)")
        base = Path(eng) / "forms" / "blank_a4.hwpx"
    build(base, HERE / "addressing.hwpx")
    (HERE / "addressing.json").write_text(json.dumps(expected(), ensure_ascii=False, indent=1) + "\n", "utf-8")
    print("wrote", HERE / "addressing.hwpx", "and addressing.json")


if __name__ == "__main__":
    main(sys.argv)
