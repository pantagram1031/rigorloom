# -*- coding: utf-8 -*-
"""Synthetic 지원사업 신청 packet builder for the grant module's tests.

The shape mirrors the family as measured on the three corpus forms
(``tests/corpus/forms/grant/pps-{hyeopeop-seungin-sinchengseo,
jeongbogonggae-donguiseo}.hwpx`` and
``tests/corpus/forms/converted/kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx``):
a **packet inside one file** — a 신청서 grid, a 작성방법 block whose guide lines
cite 붙임 parts that live in the 공고문 and 별첨 parts that live in this document,
``【별첨 N】`` section headers, a budget grid whose ``합계`` row equals the sum of
its columns, an extendable roster, per-sheet ``(인)`` signature seats, consent
rows offering ``■동의함 / □동의하지 않음``, and an addressee line.

Everything is driven by a spec dict so a rule's positive fixture (violation
present) and its still-catches negative (a legitimate packet) differ by one key.
``BLANK`` is the pristine packet; ``FILLED`` is a correctly completed one — values
written, date written, consents marked, the form's self-deleting guidance and its
worked-example stand-ins removed, and **one extra row added to the roster**,
because extending a table is what this family's applicant legitimately does.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

#: The pristine packet. Nothing written, the date seat unfilled, both consent
#: choices unmarked, the form's own guidance and example stand-ins still in place.
BLANK: dict = {
    "title": "2026년 기술창업 지원사업 신청서",
    #: The 작성방법 block. Two 붙임 citations with no section in this file (the
    #: 공고문 carries them — external by construction) and one 별첨 citation that
    #: must resolve, plus the self-deleting guidance sentence.
    "guide_rows": [
        "【작성방법】",
        "□ 과제명 : 창업 아이템(과제)명 기재",
        "  예시) [기술사업화] ~~~~ 기술을 적용한 ~~~ 개발",
        "  ○ 지원신청액의 합계액 : (최대) 30,000천원을 초과 不",
        "  ○ 전문가 활용비 : 전체 지원신청액의 총 1백만원 이내",
        "  ○ 상세 기준은 붙임 3. 사업화자금지원 사용지침 참고",
        "  ○ 이전기술명은 붙임 5. 소개자료 기술명 기재",
        "  ※ 해당 안내를 포함한, 아래 파란색 안내 문구는 참고하여 작성 후 삭제",
        "  ○ 전문가 활용의 경우 별첨 2-1 자료 활용",
    ],
    #: 신청서 grid — three columns so a row is a record (grid_min_cols).
    "applicant_grid": [
        ["구    분", "성    명", "생년월일"],
        ["지원 신청자", "", ""],
        ["소    속", "", ""],
    ],
    #: 사업비 편성표. Every 합계 equals the sum of its column, as on the corpus
    #: form (whose totals are Hancom =SUM() fields).
    "budget_grid": [
        ["지원분야", "지원신청액", "자부담금", "합계"],
        ["시제품 제작", "11,000", "-", "11,000"],
        ["마케팅 지원", "8,000", "5,000", "13,000"],
        ["전문가 활용", "1,000", "-", "1,000"],
        ["합        계(천원)", "20,000", "5,000", "25,000"],
    ],
    #: The roster the applicant EXTENDS. Header plus two blank record rows.
    "roster_grid": [
        ["기   간", "시행처(발주처)", "사업비(천원)", "추진내용"],
        ["", "", "", ""],
        ["", "", "", ""],
    ],
    #: Consent choices: label cell, 필수 declaration cell, option group cell.
    "consent_rows": [
        ["개인정보", "필수항목 : 개인 식별정보", "( □동의함    □동의하지 않음 )"],
        ["기업정보", "필수항목 : 기업(신용)정보", "( □동의함    □동의하지 않음 )"],
    ],
    #: ``【별첨 N】`` section headers. ``optional`` writes the form's own deletion
    #: licence on the following line, which downgrades packet_section_lost.
    "sections": [
        {"marker": "별첨", "number": "1",
         "note": "  ※ 기술이전 예정 예비창업자 작성"},
        {"marker": "별첨", "number": "2-1",
         "note": "  ※ R&D기획지원 전문가활용 (해당 전문가가 작성)"},
        {"marker": "별첨", "number": "3", "optional": True,
         "note": "  ※ 해당자에 한함 (없을 시 삭제)"},
    ],
    "apply_sentence": "  본인은 위와 같이 2026년 기술창업 지원사업을 신청합니다.",
    "date_row": "                     년      월      일",
    "signature_rows": [
        "                     신 청 자 :                     (인)",
        "                     대 표 자 :                     (인)",
    ],
    "addressee": "광주테크노파크 원장 귀하",
    "closing_placeholder": "                     지원자      ㅇㅇㅇ  (인)",
}

#: A correctly completed packet. The values the operator had are written, the
#: date is written, both consents are marked, the guidance the form told the
#: applicant to delete is gone, the worked-example stand-ins are gone — and the
#: roster carries ONE MORE ROW than the blank form, which must pass.
FILLED: dict = {
    **BLANK,
    "guide_rows": [
        "【작성방법】",
        "□ 과제명 : 창업 아이템(과제)명 기재",
        "  ○ 지원신청액의 합계액 : (최대) 30,000천원을 초과 不",
        "  ○ 전문가 활용비 : 전체 지원신청액의 총 1백만원 이내",
        "  ○ 상세 기준은 붙임 3. 사업화자금지원 사용지침 참고",
        "  ○ 이전기술명은 붙임 5. 소개자료 기술명 기재",
        "  ○ 전문가 활용의 경우 별첨 2-1 자료 활용",
    ],
    "applicant_grid": [
        ["구    분", "성    명", "생년월일"],
        ["지원 신청자", "이서준", ""],
        ["소    속", "한빛정밀 주식회사", ""],
    ],
    "roster_grid": [
        ["기   간", "시행처(발주처)", "사업비(천원)", "추진내용"],
        ["2026.09 ~ 2026.12", "광주테크노파크", "11,000", "시제품 제작"],
        ["2027.01 ~ 2027.03", "광주테크노파크", "8,000", "마케팅 지원"],
        ["2027.04 ~ 2027.06", "광주테크노파크", "1,000", "전문가 활용"],
    ],
    "consent_rows": [
        ["개인정보", "필수항목 : 개인 식별정보", "( ■동의함    □동의하지 않음 )"],
        ["기업정보", "필수항목 : 기업(신용)정보", "( ■동의함    □동의하지 않음 )"],
    ],
    "apply_sentence": "  본인은 위와 같이 2026년 기술창업 지원사업을 신청합니다.",
    "date_row": "                     2026년   8월   20일",
    #: The ㅇㅇㅇ stand-in is replaced by a name and the (인) seat STAYS. The two
    #: things share a line on the corpus form ('지원자      ㅇㅇㅇ  (인)') and
    #: they are opposites: the stand-in must go, the signature seat must not.
    "closing_placeholder": "                     지원자      김도현  (인)",
}

_HEADER = f"""<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="{HH}" version="1.4" secCnt="1">
  <hh:refList>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="4">
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
      </hh:borderFill>
    </hh:borderFills>
    <hh:paraProperties itemCnt="1"><hh:paraPr id="0"/></hh:paraProperties>
    <hh:charProperties itemCnt="1"><hh:charPr id="0" height="1000"/></hh:charProperties>
  </hh:refList>
</hh:head>
"""


def _para(text) -> str:
    if text is None:
        return ""
    return (f'<hp:p id="1" paraPrIDRef="0" styleIDRef="0">'
            f'<hp:run charPrIDRef="0"><hp:t>{escape(text)}</hp:t></hp:run>'
            f'</hp:p>')


def _cell(text: str, row: int, col: int, *, span=(1, 1)) -> str:
    return (
        '<hp:tc name="" header="0" borderFillIDRef="4">'
        f'<hp:subList>{_para(text)}</hp:subList>'
        f'<hp:cellAddr rowAddr="{row}" colAddr="{col}"/>'
        f'<hp:cellSpan rowSpan="{span[0]}" colSpan="{span[1]}"/>'
        '<hp:cellSz width="12000" height="2000"/>'
        '</hp:tc>'
    )


def table(rows, *, cols: int | None = None, table_id: int = 800) -> str:
    """A rowCnt×colCnt table of 1×1 cells, one per entry in ``rows``.

    ``cols`` overrides the declared colCnt without touching the cells — that is
    how the table_column_changed fixture is built, because a column count is a
    *declaration* the reviewer reads, and the rule compares declarations.
    """
    if not rows:
        return ""
    width = cols if cols is not None else max(len(row) for row in rows)
    body = "".join(
        "<hp:tr>" + "".join(_cell(text, index, position)
                            for position, text in enumerate(row)) + "</hp:tr>"
        for index, row in enumerate(rows))
    return (f'<hp:tbl id="{table_id}" rowCnt="{len(rows)}" colCnt="{width}" '
            f'borderFillIDRef="4">{body}</hp:tbl>')


def one_cell_table(text: str, *, table_id: int = 900) -> str:
    return table([[text]], table_id=table_id)


def build_section(spec: dict) -> str:
    """The packet: 신청서 grid, 작성방법, budget, roster, consents, 별첨 sections."""
    pieces = [_para(spec.get("title"))]
    if spec.get("applicant_grid"):
        pieces.append(table(spec["applicant_grid"], table_id=801,
                            cols=spec.get("applicant_cols")))
    pieces.append(_para(spec.get("apply_sentence")))
    pieces.append(_para(spec.get("date_row")))
    for row in spec.get("signature_rows") or []:
        pieces.append(_para(row))
    pieces.append(_para(spec.get("addressee")))
    for row in spec.get("guide_rows") or []:
        pieces.append(_para(row))
    if spec.get("budget_grid"):
        pieces.append(table(spec["budget_grid"], table_id=802,
                            cols=spec.get("budget_cols")))
    if spec.get("roster_grid"):
        pieces.append(table(spec["roster_grid"], table_id=803,
                            cols=spec.get("roster_cols")))
    for index, row in enumerate(spec.get("consent_rows") or []):
        pieces.append(table([row], table_id=810 + index))
    for index, section in enumerate(spec.get("sections") or []):
        pieces.append(_para(f"【{section['marker']} {section['number']}】"
                            f" 관련 자료"))
        pieces.append(_para(section.get("note")))
    pieces.append(_para(spec.get("closing_placeholder")))
    body = "".join(pieces)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:secPr id="0"><hp:pagePr width="59528" height="84188">'
        f'<hp:margin left="5669" right="5669" top="5669" bottom="2835" '
        f'header="0" footer="0" gutter="0"/></hp:pagePr></hp:secPr>'
        f'</hp:run></hp:p>'
        f'{body}'
        "</hs:sec>"
    )


def write_grant(path: Path, spec: dict | None = None, *,
                malformed: bool = False, **overrides) -> Path:
    """Write a synthetic 지원사업 packet hwpx. ``overrides`` patch ``spec``
    (default BLANK)."""
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


def write_not_a_packet(path: Path) -> Path:
    """A valid hwpx that is not a 지원사업 packet at all (structure-absent)."""
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
    """A ``--fill-map`` instance: what the OPERATOR declared for this packet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return path
