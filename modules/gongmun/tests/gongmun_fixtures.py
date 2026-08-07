# -*- coding: utf-8 -*-
"""Synthetic 기안문 fixture builder for the gongmun module's tests.

The shape mirrors 별지 제1호서식 as measured on the corpus form
(``tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx``): ONE outer frame
table whose 본문 cell holds two nested single-cell boxes — the red-bordered 직인
slot and the 발신명의 box — plus the 결재란 row, the 결문 rows and the 비고 row.

Everything is driven by a spec dict so a rule's positive fixture (violation
present) and its still-catches negative (a legitimate document) differ by one
key. ``BLANK`` is the pristine 서식; ``FINISHED`` is a correctly completed 공문.

borderFill ids are chosen to reproduce the trap the real form contains:
id 11 draws the seal box in red, and id 12 (the 발신명의 box) declares
``color="#FF0000"`` on a border whose ``type="NONE"`` — a naive colour scan
calls that a seal slot too.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

BIGO_MARKER = "비고(이 난은 서식에 포함하지 아니한다)"
BIGO_SENTENCE = (
    '문서를 작성할 때 "행정기관명", "발신명", "기안자", "검토자", "결재권자", '
    '"직위(직급) 서명", "처리과명-연도별 일련번호(시행일)", "도로명주소", '
    '"홈페이지 주소", "공무원의 전자우편주소", "공개 구분"의 용어는 표시하지 '
    "아니하고 그 내용을 적는다."
)

#: The pristine 별지 제1호서식 — every guide term intact, nothing written.
BLANK: dict = {
    "form_id": "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식]",
    "agency": "행 정 기 관 명",
    "susin": "수신",
    "gyeongyu": "(경유)",
    "jemok": "제목 ",
    "seal": "직인",
    "balsin": "발신명의",
    "approvers": ["기안자  직위(직급) 서명",
                  "검토자  직위(직급) 서명",
                  "결재권자  직위(직급) 서명"],
    "hyeopjoja": "협조자",
    "siheng_value": "처리과명-연도별 일련번호(시행일)",
    "jeopsu_value": "처리과명-연도별 일련번호(접수일)",
    "doro": "도로명주소",
    "homepage": "홈페이지 주소",
    "email": "공무원의 전자우편주소",
    "gonggae": "공개 구분",
    "bigo": True,
}

#: A correctly finished 공문: every guide term consumed, 비고 gone, 직인 slot
#: reserved for a human, 접수 left to the receiving agency.
FINISHED: dict = {
    **BLANK,
    "agency": "국가유산청",
    "susin": "수신 국가유산청장",
    "jemok": "제목 자료 제출 협조 요청",
    "balsin": "국가유산청장",
    "approvers": ["주무관 홍길동", "과장 김영희", "청장 이철수"],
    "siheng_value": "문화유산정책과-1234(2026. 8. 20.)",
    "jeopsu_value": "",
    "doro": "서울특별시 종로구 삼봉로 81",
    "homepage": "www.khs.go.kr",
    "email": "gongmun@example.com",
    "gonggae": "대외공개",
    "bigo": False,
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
      <hh:borderFill id="11">
        <hh:leftBorder type="SOLID" width="0.4 mm" color="#FF5200"/>
        <hh:rightBorder type="SOLID" width="0.5 mm" color="#FF0000"/>
        <hh:topBorder type="SOLID" width="0.5 mm" color="#FF0000"/>
        <hh:bottomBorder type="SOLID" width="0.5 mm" color="#FF0000"/>
      </hh:borderFill>
      <hh:borderFill id="12">
        <hh:leftBorder type="NONE" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="NONE" width="0.5 mm" color="#FF0000"/>
        <hh:topBorder type="NONE" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="NONE" width="0.12 mm" color="#000000"/>
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


def _box(text: str, *, borderfill: str) -> str:
    """A nested single-cell box (직인 / 발신명의)."""
    return (
        f'<hp:tbl id="900" rowCnt="1" colCnt="1" borderFillIDRef="4">'
        f'<hp:tr>{_cell(0, 0, text, borderfill=borderfill)}</hp:tr></hp:tbl>'
    )


def _row(cells) -> str:
    return f'<hp:tr>{"".join(cells)}</hp:tr>'


def build_section(spec: dict) -> str:
    """The 기안문 frame table, in the corpus form's table/cell order."""
    body_boxes = ""
    if spec.get("seal") is not None:
        body_boxes += _box(spec["seal"], borderfill="11")
    if spec.get("balsin") is not None:
        body_boxes += _box(spec["balsin"], borderfill="12")

    dumun = [spec.get("agency"), "", spec.get("susin"), spec.get("gyeongyu"),
             spec.get("jemok")]
    approvers = list(spec.get("approvers") or [])
    while len(approvers) < 3:
        approvers.append("")

    rows = [
        _row([_cell(0, 0, spec.get("form_id"), span=(1, 15))]),
        _row([_cell(1, 0, dumun, span=(1, 15))]),
        _row([_cell(2, 0, [""], span=(1, 15), extra=body_boxes)]),
        _row([_cell(3, 0, "", span=(1, 15))]),
        _row([_cell(4, 0, approvers[0], span=(1, 3)),
              _cell(4, 3, approvers[1], span=(1, 6)),
              _cell(4, 9, approvers[2], span=(1, 6))]),
        _row([_cell(5, 0, spec.get("hyeopjoja")), _cell(5, 1, ""),
              _cell(5, 5, "", span=(1, 3))]),
        _row([_cell(6, 0, "시행"), _cell(6, 1, spec.get("siheng_value"),
                                       span=(1, 4)),
              _cell(6, 5, "접수", span=(1, 3)),
              _cell(6, 8, spec.get("jeopsu_value"), span=(1, 7))]),
        _row([_cell(7, 0, "우"), _cell(7, 1, spec.get("doro"), span=(1, 5)),
              _cell(7, 6, "/"), _cell(7, 7, spec.get("homepage"), span=(1, 8))]),
        _row([_cell(8, 0, "전화번호(   )", span=(1, 2)),
              _cell(8, 2, "팩스번호(   )", span=(1, 4)), _cell(8, 6, "/"),
              _cell(8, 7, spec.get("email"), span=(1, 4)), _cell(8, 11, "/"),
              _cell(8, 12, spec.get("gonggae"), span=(1, 3))]),
        _row([_cell(9, 0, "210㎜×297㎜(백상지 80g/㎡)", span=(1, 15))]),
    ]
    if spec.get("bigo"):
        rows.append(_row([_cell(10, 0, [BIGO_MARKER, BIGO_SENTENCE],
                                span=(1, 15))]))
    table = ('<hp:tbl id="800" rowCnt="11" colCnt="15" borderFillIDRef="4">'
             + "".join(rows) + "</hp:tbl>")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:secPr id="0"><hp:pagePr width="59528" height="84188">'
        f'<hp:margin left="5669" right="5669" top="5669" bottom="2835" '
        f'header="0" footer="0" gutter="0"/></hp:pagePr></hp:secPr>'
        f'{table}</hp:run></hp:p>'
        "</hs:sec>"
    )


def write_gongmun(path: Path, spec: dict | None = None, *,
                  malformed: bool = False, **overrides) -> Path:
    """Write a synthetic 기안문 hwpx. ``overrides`` patch ``spec`` (default BLANK)."""
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


def write_not_a_gongmun(path: Path) -> Path:
    """A valid hwpx that is not a 공문 at all (structure-absent fixture)."""
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


def write_pack(path: Path, *, organizations=(), departments=(), ranks=(),
               name: str = "test-org") -> Path:
    """A ``gongmun_org`` pack instance for the pack-aware rules."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "rigorloom-gongmun/preference-pack/gongmun_org-v1",
        "pack_type": "gongmun_org",
        "name": name,
        "version": 1,
        "organizations": list(organizations),
        "departments": list(departments),
        "ranks": list(ranks),
    }, ensure_ascii=False), encoding="utf-8")
    return path
