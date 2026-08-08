# -*- coding: utf-8 -*-
"""Synthetic 민원 서식 fixture builder for the minwon module's tests.

The shape mirrors the family as measured on the four corpus forms
(``tests/corpus/forms/converted/{jumin-deungchobon,jeongbo-gonggae,
saeopja-deungnok,admrul-gajokdolbom}-*.hwpx``): ONE page-filling outer table
carrying, in order, the 별지서식 header line, the title, the form's own
instruction lines, a shaded 접수·처리 block, the applicant's 인적사항 rows
(including an identity seat and a signature seat), a 선택 항목 row, the date and
addressee rows, a nested 직인 box, the 유의사항 guide block and the paper-spec
footer — plus one top-level paragraph pair reproducing the 행정규칙 서식's
paragraph-resident '신청인 : ○○○ (인)' seat.

Everything is driven by a spec dict so a rule's positive fixture (violation
present) and its still-catches negative (a legitimate document) differ by one
key. ``BLANK`` is the pristine 서식; ``FILLED`` is a correctly completed 신청서.

borderFill ids reproduce the trap the real corpus contains: id 8 paints
``#B2B2B2`` (the 정보공개 청구서 staff-only shade, brightness 0.698) and id 9
paints ``#F2F2F2`` (a light tint above the threshold, so shading alone must not
make it staff-only).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

#: The form's own words. Each one IS a rule (see check_minwon's docstring).
SELECT_INSTRUCTION = "※ 해당하는 내용 앞의 [ ]에 √표를 합니다."
SHADING_DECLARATION = "※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다."

#: The pristine 별지서식 — nothing marked, nothing written, date seat unfilled.
BLANK: dict = {
    "form_header": "■ 민원 처리에 관한 법률 시행규칙 [별지 제1호서식] <개정 2026. 1. 1.>",
    # No ○ run here on purpose: the ○-placeholder rule is about the APPLICANT's
    # own name seat (the paragraph below), and a decorative ○○ in the title
    # would make every fixture trip it.
    "title": "민원 신청서",
    "select_instruction": SELECT_INSTRUCTION,
    "shading_declaration": SHADING_DECLARATION,
    "jeopsu_number": "접수번호",
    "jeopsu_date": "접수일",
    "chori_period": "처리기간",
    "name_label": "성명",
    "name_value": "(서명 또는 인)",
    "rrn_label": "주민등록번호",
    "rrn_value": "",
    "birth_label": "생년월일",
    "birth_value": "",
    "select_row": "[ ]열람ㆍ시청 [ ]사본ㆍ출력물 [ ]전자파일",
    "copies_row": "교부 [ ]통",
    "fee_row": "수수료 [ ]감면 대상임 [ ]감면 대상 아님",
    "date_row": "년 월 일",
    "addressee": "(접수 기관의 장) 귀하",
    "seal": "접수기관장직인",
    "guide_header": "유 의 사 항",
    "guide_body": "1. 제출서류는 3쪽의 작성방법을 읽고 준비하시기 바랍니다.",
    "paper_spec": "210mm×297mm[백상지 80g/㎡(재활용품)]",
    "paragraph_applicant": "신청인 : ○○○ (인)",
    "paragraph_confirmer": "확인자 : (부서장) (인)",
    "drop_chori_period": False,
}

#: A correctly completed 신청서: a selection marked, the date written, the
#: identity seats left for the applicant, the staff block untouched, every guide
#: block and signature seat intact.
FILLED: dict = {
    **BLANK,
    "name_label": "성명 김도현",
    "select_row": "[√]열람ㆍ시청 [ ]사본ㆍ출력물 [ ]전자파일",
    "copies_row": "교부 [1]통",
    "date_row": "2026년 8월 20일",
    "paragraph_applicant": "신청인 : 김도현 (인)",
}

_HEADER = f"""<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="{HH}" version="1.4" secCnt="1">
  <hh:refList>
    <hh:borderFills itemCnt="3">
      <hh:borderFill id="4">
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
      </hh:borderFill>
      <hh:borderFill id="8">
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:fillBrush><hh:winBrush faceColor="#B2B2B2" hatchColor="#FFFFFF"
          alpha="0"/></hh:fillBrush>
      </hh:borderFill>
      <hh:borderFill id="9">
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:fillBrush><hh:winBrush faceColor="#F2F2F2" hatchColor="#000000"
          alpha="0"/></hh:fillBrush>
      </hh:borderFill>
    </hh:borderFills>
    <hh:paraProperties itemCnt="1"><hh:paraPr id="0"/></hh:paraProperties>
    <hh:charProperties itemCnt="1"><hh:charPr id="0" height="1000"/></hh:charProperties>
  </hh:refList>
</hh:head>
"""


def _para(texts, extra: str = "") -> str:
    """One ``hp:p``; ``texts`` may be a string or a list of run texts."""
    if isinstance(texts, str):
        texts = [texts]
    runs = "".join(
        f'<hp:run charPrIDRef="0"><hp:t>{escape(text)}</hp:t></hp:run>'
        for text in texts if text is not None
    )
    if extra:
        runs += f'<hp:run charPrIDRef="0">{extra}</hp:run>'
    if not runs:
        runs = '<hp:run charPrIDRef="0"/>'
    return f'<hp:p id="1" paraPrIDRef="0" styleIDRef="0">{runs}</hp:p>'


def _cell(row: int, col: int, paragraphs, *, span=(1, 1),
          borderfill: str = "4", extra: str = "") -> str:
    if isinstance(paragraphs, (str, type(None))):
        paragraphs = [paragraphs]
    bodies = [_para(text) for text in paragraphs if text is not None]
    if extra:
        bodies.append(_para([], extra=extra))
    if not bodies:
        bodies = [_para([])]
    return (
        f'<hp:tc name="" header="0" borderFillIDRef="{borderfill}">'
        f'<hp:subList>{"".join(bodies)}</hp:subList>'
        f'<hp:cellAddr rowAddr="{row}" colAddr="{col}"/>'
        f'<hp:cellSpan rowSpan="{span[0]}" colSpan="{span[1]}"/>'
        f'<hp:cellSz width="10000" height="2000"/>'
        "</hp:tc>"
    )


def _box(text: str) -> str:
    """A nested single-cell box (the 직인 placement)."""
    return (
        f'<hp:tbl id="900" rowCnt="1" colCnt="1" borderFillIDRef="4">'
        f'<hp:tr>{_cell(0, 0, text)}</hp:tr></hp:tbl>'
    )


def _row(cells) -> str:
    return f'<hp:tr>{"".join(cells)}</hp:tr>'


def build_section(spec: dict) -> str:
    """The 신청서 frame table, in the corpus forms' row order."""
    seal_box = _box(spec["seal"]) if spec.get("seal") is not None else ""
    rows = [
        _row([_cell(0, 0, spec.get("form_header"), span=(1, 6))]),
        _row([_cell(1, 0, spec.get("title"), span=(1, 6))]),
        _row([_cell(2, 0, [spec.get("select_instruction"),
                           spec.get("shading_declaration")], span=(1, 6))]),
        # the 접수·처리 block: shaded AND labelled, exactly as 정보공개 청구서.
        # ``drop_chori_period`` removes the CELL (not its text), which is the
        # only way to fixture staff_seat_removed.
        _row([_cell(3, 0, spec.get("jeopsu_number"), span=(1, 2),
                    borderfill="8"),
              _cell(3, 2, spec.get("jeopsu_date"), span=(1, 2),
                    borderfill="8")]
             + ([] if spec.get("drop_chori_period") else
                [_cell(3, 4, spec.get("chori_period"), span=(1, 2),
                       borderfill="8")])),
        _row([_cell(4, 0, spec.get("name_label"), span=(1, 3)),
              _cell(4, 3, spec.get("name_value"), span=(1, 3))]),
        # identity seats: one in-cell (주민등록번호) and one right-neighbour
        # (생년월일), the two topologies the corpus uses
        _row([_cell(5, 0, [spec.get("rrn_label"), spec.get("rrn_value")]
                    if spec.get("rrn_value") else spec.get("rrn_label"),
                    span=(1, 3)),
              _cell(5, 3, spec.get("birth_label")),
              _cell(5, 4, spec.get("birth_value"), span=(1, 2))]),
        _row([_cell(6, 0, spec.get("select_row"), span=(1, 4)),
              _cell(6, 4, spec.get("copies_row"), span=(1, 2))]),
        # a light tint (#F2F2F2) above the shading threshold: shading alone must
        # not make this staff-only
        _row([_cell(7, 0, spec.get("fee_row"), span=(1, 6), borderfill="9")]),
        _row([_cell(8, 0, spec.get("date_row"), span=(1, 6))]),
        _row([_cell(9, 0, spec.get("addressee"), span=(1, 5)),
              _cell(9, 5, [""], extra=seal_box)]),
        _row([_cell(10, 0, spec.get("guide_header"), span=(1, 6))]),
        _row([_cell(11, 0, spec.get("guide_body"), span=(1, 6))]),
        _row([_cell(12, 0, spec.get("paper_spec"), span=(1, 6))]),
    ]
    table = ('<hp:tbl id="800" rowCnt="13" colCnt="6" borderFillIDRef="4">'
             + "".join(rows) + "</hp:tbl>")
    tail = "".join(
        _para(spec[key]) for key in
        ("paragraph_applicant", "paragraph_confirmer")
        if spec.get(key) is not None)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:secPr id="0"><hp:pagePr width="59528" height="84188">'
        f'<hp:margin left="5669" right="5669" top="5669" bottom="2835" '
        f'header="0" footer="0" gutter="0"/></hp:pagePr></hp:secPr>'
        f'{table}</hp:run></hp:p>'
        f'{tail}'
        "</hs:sec>"
    )


def write_minwon(path: Path, spec: dict | None = None, *,
                 malformed: bool = False, **overrides) -> Path:
    """Write a synthetic 신청서 hwpx. ``overrides`` patch ``spec`` (default BLANK)."""
    merged = {**(spec if spec is not None else BLANK), **overrides}
    section = build_section(merged)
    if malformed:
        section = section.replace("</hs:sec>", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", _HEADER)
        archive.writestr("Contents/section0.xml", section)
    return path


def write_not_a_minwon(path: Path) -> Path:
    """A valid hwpx that is not a 민원 서식 at all (structure-absent fixture)."""
    section = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        + _para("탐구 보고서 초안") + _para("1. 서론") + "</hs:sec>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", _HEADER)
        archive.writestr("Contents/section0.xml", section)
    return path


def write_fill_map(path: Path, mapping: dict) -> Path:
    """A ``--fill-map`` instance: what the OPERATOR declared for a document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return path
