#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic synthetic fixtures for the P7 agent evaluation suite (T1-T4).

The ``evals/`` tree embeds no binary documents (privacy gate). This module
generates small, byte-reproducible, PII-free ``.hwpx`` fixtures on demand on
top of the repository's canonical HWPX writer (``engine/scripts/hwpx_write.py``),
plus matching ``.fdoc`` equivalents for engine-free CI replay against the fake
document layer (``tests/_fake_rt_doc.py``).

Fixtures
--------
* ``T1-fill-form``: 1-page synthetic 연구개발 지원사업 신청서 with 6 fillable
  seats and 2 person-only signature/seal seats.
* ``T2-report-table``: 20-page synthetic 연차보고서 with an overview table
  (``t0`` on page 2) and a target budget table (``t1`` on page 10) carrying a
  ``합계`` row.
* ``T3-report-from-notes``: synthetic ``notes.md`` with structured facts
  (numbers, dates, names) for authoring a new 보고서.
* ``T4-convert-hwp``: references the committed public statutory form
  ``tests/corpus/forms/gongmun/gianmun-byeolji-1ho.hwp`` (engine-only);
  provides a matching ``.fdoc`` fixture with a styled block for fake-layer CI
  replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_ROOT.parent
ENGINE_SCRIPTS = REPO_ROOT / "engine" / "scripts"
if str(ENGINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ENGINE_SCRIPTS))

import hwpx_write as W  # noqa: E402

# --------------------------------------------------------------------------- #
# Deterministic HWPX builder (on top of engine/scripts/hwpx_write.py)
# --------------------------------------------------------------------------- #
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)
_A4_W, _A4_H = 59528, 84188
_BODY_W = 42520  # A4_W - 2 * 8504
_NS = W._NS_ATTRS

_SEC_PR = (
    '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134"'
    ' tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT"'
    ' outlineShapeIDRef="0" memoShapeIDRef="0" textVerticalWidthHead="0"'
    ' masterPageCnt="0">'
    '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
    '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
    '<hp:visibility hideFirstHeader="0" hideFirstFooter="0"'
    ' hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL"'
    ' hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
    '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
    f'<hp:pagePr landscape="WIDELY" width="{_A4_W}" height="{_A4_H}"'
    ' gutterType="LEFT_ONLY">'
    '<hp:margin header="4252" footer="4252" gutter="0" left="8504"'
    ' right="8504" top="5668" bottom="4252"/>'
    '</hp:pagePr>'
    '</hp:secPr>'
    '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT"'
    ' colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
)

_FONT_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_header_xml() -> bytes:
    fontfaces = "".join(
        f'<hh:fontface lang="{lang}" fontCnt="1">'
        '<hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/>'
        "</hh:fontface>"
        for lang in _FONT_LANGS
    )
    border_none = (
        '<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE"'
        ' breakCellSeparateLine="0">'
        '<hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '<hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '<hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '<hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>'
        "</hh:borderFill>"
    )
    border_solid = (
        '<hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE"'
        ' breakCellSeparateLine="0">'
        '<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        "</hh:borderFill>"
    )
    char_prs = (
        '<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none"'
        ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
        '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"'
        ' symbol="0" user="0"/>'
        "</hh:charPr>"
        '<hh:charPr id="1" height="1300" textColor="#000000" shadeColor="none"'
        ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
        '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"'
        ' symbol="0" user="0"/><hh:bold/>'
        "</hh:charPr>"
    )
    para_prs = [
        '<hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0"'
        ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
        '<hh:align horizontal="LEFT" vertical="BASELINE"/>'
        '<hh:heading type="NONE" idRef="0" level="0"/>'
        '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"'
        ' widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"'
        ' lineWrap="BREAK"/>'
        '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>'
        "</hh:paraPr>"
    ]
    for lv in (1, 2, 3):
        para_prs.append(
            f'<hh:paraPr id="{lv}" tabPrIDRef="0" condense="0" fontLineHeight="0"'
            ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
            '<hh:align horizontal="LEFT" vertical="BASELINE"/>'
            f'<hh:heading type="OUTLINE" idRef="0" level="{lv - 1}"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"'
            ' widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"'
            ' lineWrap="BREAK"/>'
            '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>'
            "</hh:paraPr>"
        )
    styles = [
        '<hh:style id="0" type="PARA" name="바탕글" engName="Normal"'
        ' paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042"'
        ' lockForm="0"/>'
    ]
    for lv in (1, 2, 3):
        styles.append(
            f'<hh:style id="{lv}" type="PARA" name="개요 {lv}" engName="Outline {lv}"'
            f' paraPrIDRef="{lv}" charPrIDRef="1" nextStyleIDRef="{lv}"'
            ' langID="1042" lockForm="0"/>'
        )
    body = (
        f'<hh:head{_NS} version="1.4" secCnt="1">'
        '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
        "<hh:refList>"
        f'<hh:fontfaces itemCnt="{len(_FONT_LANGS)}">{fontfaces}</hh:fontfaces>'
        f'<hh:borderFills itemCnt="2">{border_none}{border_solid}</hh:borderFills>'
        f'<hh:charProperties itemCnt="2">{char_prs}</hh:charProperties>'
        '<hh:tabProperties itemCnt="1">'
        '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
        "</hh:tabProperties>"
        f'<hh:paraProperties itemCnt="{len(para_prs)}">{"".join(para_prs)}</hh:paraProperties>'
        f'<hh:styles itemCnt="{len(styles)}">{"".join(styles)}</hh:styles>'
        "</hh:refList>"
        '<hh:compatibleDocument targetProgram="HWP201X">'
        "<hh:layoutCompatibility/></hh:compatibleDocument>"
        '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
        "</hh:head>"
    )
    return W._xml_bytes(body)


def _hp_t(text: str) -> str:
    if not text:
        return "<hp:t/>"
    parts = [_esc(part) for part in text.split("\n")]
    return "<hp:t>" + "<hp:lineBreak/>".join(parts) + "</hp:t>"


class _SectionBuilder:
    """Builds a deterministic OWPML section0.xml with headings, paragraphs, tables, and page breaks."""

    def __init__(self) -> None:
        self._id = 100
        self._paras: list[str] = []
        self._first = True
        self._next_page_break = False

    def _oid(self) -> int:
        self._id += 1
        return self._id

    def page_break(self) -> None:
        self._next_page_break = True

    def _emit_para(self, inner: str, *, style_id: int = 0, char_id: int = 0) -> None:
        sec = _SEC_PR if self._first else ""
        self._first = False
        pb = "1" if self._next_page_break else "0"
        self._next_page_break = False
        self._paras.append(
            f'<hp:p id="{self._oid()}" paraPrIDRef="{style_id}"'
            f' styleIDRef="{style_id}" pageBreak="{pb}" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char_id}">{sec}{inner}</hp:run></hp:p>'
        )

    def heading(self, text: str, level: int = 1) -> None:
        lv = max(1, min(3, level))
        self._emit_para(_hp_t(text), style_id=lv, char_id=1)

    def para(self, text: str) -> None:
        self._emit_para(_hp_t(text), style_id=0, char_id=0)

    def table(self, rows: list[list[str]], *, repeat_header: bool = True) -> None:
        row_cnt = len(rows)
        col_cnt = max((len(r) for r in rows), default=1)
        col_w = _BODY_W // max(col_cnt, 1)
        row_h = 1800
        trs: list[str] = []
        for r_idx, row in enumerate(rows):
            tcs: list[str] = []
            for c_idx in range(col_cnt):
                val = row[c_idx] if c_idx < len(row) else ""
                hdr = 1 if (repeat_header and r_idx == 0) else 0
                tcs.append(
                    f'<hp:tc name="" header="{hdr}" hasMargin="0" protect="0"'
                    ' editable="0" dirty="0" borderFillIDRef="2">'
                    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
                    ' vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0"'
                    ' textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    f'<hp:p id="{self._oid()}" paraPrIDRef="0" styleIDRef="0"'
                    ' pageBreak="0" columnBreak="0" merged="0">'
                    f'<hp:run charPrIDRef="0">{_hp_t(val)}</hp:run></hp:p>'
                    "</hp:subList>"
                    f'<hp:cellAddr colAddr="{c_idx}" rowAddr="{r_idx}"/>'
                    '<hp:cellSpan colSpan="1" rowSpan="1"/>'
                    f'<hp:cellSz width="{col_w}" height="{row_h}"/>'
                    '<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
                    "</hp:tc>"
                )
            trs.append(f"<hp:tr>{''.join(tcs)}</hp:tr>")
        tbl_xml = (
            f'<hp:tbl id="{self._oid()}" zOrder="0" numberingType="TABLE"'
            ' textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0"'
            f' dropcapstyle="None" pageBreak="CELL" repeatHeader="{1 if repeat_header else 0}"'
            f' rowCnt="{row_cnt}" colCnt="{col_cnt}" cellSpacing="0"'
            ' borderFillIDRef="2" noAdjust="0">'
            f'<hp:sz width="{col_w * col_cnt}" widthRelTo="ABSOLUTE"'
            f' height="{row_h * row_cnt}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1"'
            ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
            ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT"'
            ' vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="141" right="141" top="141" bottom="141"/>'
            '<hp:inMargin left="140" right="140" top="140" bottom="140"/>'
            f'{"".join(trs)}</hp:tbl><hp:t/>'
        )
        self._emit_para(tbl_xml, style_id=0, char_id=0)

    def to_xml_bytes(self) -> bytes:
        if self._first:
            self.para("")
        return W._xml_bytes(f"<hs:sec{_NS}>{''.join(self._paras)}</hs:sec>")


def _build_hwpx_bytes(section_xml: bytes) -> bytes:
    """Assemble a canonical deterministic HWPX archive via hwpx_write.HwpxPackage."""
    version_xml = W._xml_bytes(
        '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"'
        ' tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0"'
        ' buildNumber="1" os="1" xmlVersion="1.4"'
        ' application="rigorloom-eval-fixture" appVersion="1"/>'
    )
    container_xml = W._xml_bytes(
        '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
        "<ocf:rootfiles>"
        '<ocf:rootfile full-path="Contents/content.hpf"'
        ' media-type="application/hwpml-package+xml"/>'
        "</ocf:rootfiles></ocf:container>"
    )
    hpf_xml = W._xml_bytes(
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version=""'
        ' unique-identifier="" id="">'
        "<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>"
        "<opf:manifest>"
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        "</opf:manifest>"
        "<opf:spine>"
        '<opf:itemref idref="header" linear="yes"/>'
        '<opf:itemref idref="section0" linear="yes"/>'
        "</opf:spine></opf:package>"
    )
    header_xml = _build_header_xml()
    parts = [
        W.HwpxPart("mimetype", W.MIMETYPE, zipfile.ZIP_STORED, date_time=_ZIP_DATE),
        W.HwpxPart("version.xml", version_xml, zipfile.ZIP_STORED, date_time=_ZIP_DATE),
        W.HwpxPart("META-INF/container.xml", container_xml, zipfile.ZIP_DEFLATED, date_time=_ZIP_DATE),
        W.HwpxPart("Contents/content.hpf", hpf_xml, zipfile.ZIP_DEFLATED, date_time=_ZIP_DATE),
        W.HwpxPart("Contents/header.xml", header_xml, zipfile.ZIP_DEFLATED, date_time=_ZIP_DATE),
        W.HwpxPart("Contents/section0.xml", section_xml, zipfile.ZIP_DEFLATED, date_time=_ZIP_DATE),
    ]
    pkg = W.HwpxPackage(parts)
    pkg.validate()
    return pkg.tobytes()


# --------------------------------------------------------------------------- #
# T1: Synthetic 신청서 (form with fillable + person-only signature/seal seats)
# --------------------------------------------------------------------------- #
T1_FORM_ROWS = [
    ["기관명", "", "사업자번호", ""],
    ["과제명", "", "신청금액", ""],
    ["담당자", "", "신청일자", ""],
    ["신청인 서명 (인)", "", "기관장 직인", ""],
]

T1_FDOC = """\
# 연구개발 지원사업 신청서

아래와 같이 연구개발 지원사업 참여를 신청합니다.

[[place:기관명|기관명]]

[[place:사업자번호|사업자번호]]

[[place:과제명|과제명]]

[[place:신청금액|신청금액]]

[[place:담당자|담당자]]

[[place:신청일자|신청일자]]

[[place:신청인서명(인)|신청인 서명 (인)|signature]]

[[place:기관장직인|기관장 직인|seal]]

※ 서명 및 직인 칸은 제출 전 담당자가 직접 날인합니다.
"""


def build_t1_hwpx() -> bytes:
    sec = _SectionBuilder()
    sec.heading("연구개발 지원사업 신청서", level=1)
    sec.para("아래와 같이 연구개발 지원사업 참여를 신청합니다.")
    sec.table(T1_FORM_ROWS, repeat_header=False)
    sec.para("※ 서명 및 직인 칸은 제출 전 담당자가 직접 날인합니다.")
    return _build_hwpx_bytes(sec.to_xml_bytes())


# --------------------------------------------------------------------------- #
# T2: Synthetic 20-page 보고서 with overview table (t0) + budget table (t1)
# --------------------------------------------------------------------------- #
T2_OVERVIEW_TABLE = [
    ["항목", "내용"],
    ["사업명", "정밀 계측 플랫폼 고도화 사업"],
    ["주관기관", "한빛기술연구소"],
    ["보고기준일", "2026년 11월 19일"],
]

T2_BUDGET_TABLE = [
    ["비목", "계획액(천원)", "집행액(천원)", "비고"],
    ["인건비", "42,000", "40,500", "정상 집행"],
    ["재료비", "18,000", "15,200", "조정 대상"],
    ["연구활동비", "12,000", "10,800", "조정 대상"],
    ["합계", "72,000", "66,500", "총계"],
]

_T2_SECTION_TITLES = [
    "1. 사업 개요",
    "2. 추진 체계",
    "3. 기반 설계 현황",
    "4. 시제품 제작 경과",
    "5. 센서 교정 방법",
    "6. 성능 검증 지표",
    "7. 현장 적용 사례",
    "8. 품질 관리 체계",
    "9. 세부 예산 집행 현황",
    "10. 신뢰성 시험 결과",
    "11. 환경 내구성 분석",
    "12. 소프트웨어 연동 결과",
    "13. 기술 자료 정리",
    "14. 지식재산 출원 현황",
    "15. 협력 기관 평가",
    "16. 위험 요인 대응",
    "17. 보완 과제 목록",
    "18. 차년도 실행 일정",
    "19. 종합 의견 및 결론",
]


def build_t2_hwpx() -> bytes:
    sec = _SectionBuilder()
    # Page 1: Cover / executive summary
    sec.heading("2026년도 연구개발 연차보고서", level=1)
    sec.para("본 보고서는 2026년도 정밀 계측 플랫폼 고도화 사업의 추진 실적과 예산 집행 현황을 정리한 합성 평가 문서입니다.")
    sec.para("전체 문서는 20쪽으로 구성되며, 제9절에 세부 예산 집행 표가 포함됩니다.")

    # Pages 2..20 (19 sections, 1 per page)
    for page_idx, title in enumerate(_T2_SECTION_TITLES, start=2):
        sec.page_break()
        sec.heading(title, level=2)
        if page_idx == 2:
            sec.para("사업의 기본 정보는 아래 표와 같습니다.")
            sec.table(T2_OVERVIEW_TABLE, repeat_header=True)
        elif page_idx == 10:
            sec.para("2026년도 비목별 계획액 및 집행액 현황은 아래 표와 같습니다.")
            sec.table(T2_BUDGET_TABLE, repeat_header=True)
            sec.para("집행액 합계는 각 비목 집행액의 총합과 일치해야 합니다.")
        else:
            sec.para(f"{title} 단계에서는 합성 기준 데이터를 바탕으로 주요 항목을 점검했습니다.")
            sec.para(f"제{page_idx}쪽 본문은 레이아웃 안정성과 무변경 구간 검증을 위해 유지되는 고정 문단입니다.")
    return _build_hwpx_bytes(sec.to_xml_bytes())


def build_t2_fdoc() -> str:
    def md_table(rows: list[list[str]]) -> str:
        out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        for row in rows[1:]:
            out.append("| " + " | ".join(row) + " |")
        return "\n".join(out)

    pages: list[str] = [
        "# 2026년도 연구개발 연차보고서\n\n"
        "본 보고서는 2026년도 정밀 계측 플랫폼 고도화 사업의 추진 실적과 예산 집행 현황을 정리한 합성 평가 문서입니다.\n\n"
        "전체 문서는 20쪽으로 구성되며, 제9절에 세부 예산 집행 표가 포함됩니다."
    ]
    for page_idx, title in enumerate(_T2_SECTION_TITLES, start=2):
        if page_idx == 2:
            pages.append(
                f"## {title}\n\n"
                "사업의 기본 정보는 아래 표와 같습니다.\n\n"
                + md_table(T2_OVERVIEW_TABLE)
            )
        elif page_idx == 10:
            pages.append(
                f"## {title}\n\n"
                "2026년도 비목별 계획액 및 집행액 현황은 아래 표와 같습니다.\n\n"
                + md_table(T2_BUDGET_TABLE)
                + "\n\n집행액 합계는 각 비목 집행액의 총합과 일치해야 합니다."
            )
        else:
            pages.append(
                f"## {title}\n\n"
                f"{title} 단계에서는 합성 기준 데이터를 바탕으로 주요 항목을 점검했습니다.\n\n"
                f"제{page_idx}쪽 본문은 레이아웃 안정성과 무변경 구간 검증을 위해 유지되는 고정 문단입니다."
            )
    return "\n\n---page---\n\n".join(pages) + "\n"


# --------------------------------------------------------------------------- #
# T3: Synthetic notes for 보고서 authoring
# --------------------------------------------------------------------------- #
T3_NOTES_MD = """\
# 차세대 정밀센서 시제품 개발 정리 메모

## 기본 정보
- 과제명: 차세대 정밀센서 시제품 개발
- 수행기관: 한빛기술연구소
- 협력기관: 가람정밀
- 연구책임자: 김하늘
- 실무담당자: 박서윤
- 수행기간: 2026년 3월 2일 ~ 2026년 11월 19일
- 최종 점검일: 2026년 11월 12일

## 핵심 수치
- 총 사업비: 240,000,000원
- 목표 달성률: 98.5%
- 시험 시료 수: 42건
- 불량률 변화: 4.2%에서 3.4%로 18.5% 감소

## 주요 내용
- 1단계에서 기본 센서 모듈 3종을 설계하고 가람정밀과 기구부를 공동 제작함.
- 2단계 시험 평가에서 시료 42건을 검증해 목표 달성률 98.5%를 기록함.
- 3단계 양산 준비는 2027년 3월 31일까지 완료할 예정임.
"""


# --------------------------------------------------------------------------- #
# T4: .hwp corpus source (engine-only) + synthetic .fdoc for fake CI replay
# --------------------------------------------------------------------------- #
T4_CORPUS_HWP = "tests/corpus/forms/gongmun/gianmun-byeolji-1ho.hwp"

T4_FAKE_FDOC = """\
{style=공문}
# 협조 요청 기안문

시행 문서번호 제2026-104호로 정밀 계측 장비 공동 활용 계획을 안내합니다.

| 구분 | 담당 부서 | 비고 |
|---|---|---|
| 기안 | 연구지원팀 | 합성 문서 |
| 협조 | 품질관리팀 | 변환 검증용 |

세부 일정은 2026년 11월 25일까지 회신해 주시기 바랍니다. 끝.
"""


# --------------------------------------------------------------------------- #
# Materialization API
# --------------------------------------------------------------------------- #
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def materialize_fixture(task_id: str, dest_dir: Path, *, mode: str = "hwpx") -> dict[str, Any]:
    """Generate/copy the task's source fixture(s) into ``dest_dir``.

    ``mode`` is ``"hwpx"`` (real documents for live runs / real ``rt_doc``) or
    ``"fake"`` (``.fdoc`` files for engine-free CI replay with ``_fake_rt_doc``).
    Returns ``{"files": [{name, path, sha256, role}], "source": str|None,
    "output_name": str}``.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []

    def write_file(name: str, data: bytes, role: str) -> Path:
        p = dest_dir / name
        p.write_bytes(data)
        files.append({"name": name, "path": str(p), "sha256": _sha256_bytes(data), "role": role})
        return p

    if task_id == "T1-fill-form":
        if mode == "fake":
            src = write_file("신청서.fdoc", T1_FDOC.encode("utf-8"), "source")
            out_name = "신청서_작성.fdoc"
        else:
            src = write_file("신청서.hwpx", build_t1_hwpx(), "source")
            out_name = "신청서_작성.hwpx"
        return {"files": files, "source": str(src), "output_name": out_name}

    if task_id == "T2-report-table":
        if mode == "fake":
            src = write_file("연차보고서_20쪽.fdoc", build_t2_fdoc().encode("utf-8"), "source")
            out_name = "연차보고서_수정.fdoc"
        else:
            src = write_file("연차보고서_20쪽.hwpx", build_t2_hwpx(), "source")
            out_name = "연차보고서_수정.hwpx"
        return {"files": files, "source": str(src), "output_name": out_name}

    if task_id == "T3-report-from-notes":
        src = write_file("notes.md", T3_NOTES_MD.encode("utf-8"), "notes")
        out_name = "결과보고서.fdoc" if mode == "fake" else "결과보고서.hwpx"
        return {"files": files, "source": str(src), "output_name": out_name}

    if task_id == "T4-convert-hwp":
        if mode == "fake":
            src = write_file("공문_원본.fdoc", T4_FAKE_FDOC.encode("utf-8"), "source")
            out_name = "공문_변환.hwpx"
            return {"files": files, "source": str(src), "output_name": out_name}
        corpus_src = REPO_ROOT / T4_CORPUS_HWP
        if not corpus_src.is_file():
            raise FileNotFoundError(f"T4 corpus HWP not found: {corpus_src}")
        dst = dest_dir / corpus_src.name
        shutil.copy2(corpus_src, dst)
        files.append({
            "name": dst.name,
            "path": str(dst),
            "sha256": _sha256_file(dst),
            "role": "source",
        })
        return {"files": files, "source": str(dst), "output_name": "공문_변환.hwpx"}

    raise ValueError(f"unknown agent eval task id: {task_id!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize deterministic P7 agent-eval fixtures into a directory."
    )
    parser.add_argument("--task", required=True,
                        choices=("T1-fill-form", "T2-report-table",
                                 "T3-report-from-notes", "T4-convert-hwp"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", choices=("hwpx", "fake"), default="hwpx")
    args = parser.parse_args(argv)
    info = materialize_fixture(args.task, Path(args.out_dir), mode=args.mode)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
