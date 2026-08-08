# -*- coding: utf-8 -*-
"""Synthetic 표준근로계약서 fixture builder for the hr module's tests.

The shape mirrors the family as measured on the versioned pair
(``tests/corpus/forms/converted/moel-pyojun-geunrogyeyakseo-{2013,2025}.hwpx``):
a **pack** of contract variants, each one a one-cell banner table followed by
top-level paragraphs — an opening sentence naming the two parties, numbered
clauses whose seats are runs of spaces / ``시  분`` skeletons / ``(  )`` and
``[  ]`` slots, the legal sentences that carry the statutory citations, a
``년 월 일`` date line, and a two-party signature block whose seat labels are
letter-spaced (``주    소 :``, ``대 표 자 :``) with ``(서명)`` markers reserved.

Everything is driven by a spec dict so a rule's positive fixture (violation
present) and its still-catches negative (a legitimate document) differ by one
key. ``BLANK`` is the pristine pack in the 2025 revision's vocabulary; ``BLANK_
2013`` is the same shape in the 2013 vocabulary, which is what makes the version
rules testable; ``FILLED`` is a correctly completed contract.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

#: The pristine pack — nothing marked, nothing written, date seat unfilled.
#: Two variants (a main contract and a 동의서) because contract_variant_lost and
#: clause_block_lost are both about a PACK losing one of its sheets.
BLANK: dict = {
    "banner_main": "표준근로계약서(기간의 정함이 없는 경우)",
    "banner_consent": "친권자(후견인) 동의서",
    "opening": "              (이하 “사업주”라 함)과(와)            "
               "(이하 “근로자”라 함)은 다음과 같이 근로계약을 체결한다.",
    "clauses": [
        "1. 근로개시일 :      년   월   일부터",
        "2. 근 무 장 소 : ",
        "3. 업무의 내용 : ",
        "4. 소정근로시간 :   시  분 ~   시  분 (휴게 :  시  분 ~  시  분)",
        "5. 근무일/휴일 : 매주   일 근무, 주휴일 매주   요일",
        "6. 임  금",
        "7. 연차유급휴가",
        "8. 사회보험 적용여부",
        "9. 근로계약서 교부",
        "10. 근로계약, 취업규칙 등의 성실한 이행의무",
        "11. 그 밖의 사항",
    ],
    # the money rows: the option slots and the blank runs that carry a value
    "wage_rows": [
        "  - 월(일, 시간)급 :                    원",
        "  - 상여금 : 있음 (    )                    원,  없음 (     )",
        "  - 그 밖의 수당(약정수당) : 있음 [    ],   없음 [    ]",
        "  - 임금지급일 : 매월(매주 또는 매일)       일(휴일의 경우는 전날 지급)",
        "  - 지급방법 : 근로자에게 직접(현금)지급 [   ], "
        "근로자 명의 계좌에 입금 [    ]",
    ],
    #: The sentences that make the document the instrument. Every one of these
    #: carries a statute term or an article citation.
    "legal_rows": [
        "  - 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함",
        "  - 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 "
        "교부요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)",
        "  - 사업주와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고 "
        "성실하게 이행하여야 함",
        "  - 이 계약에 정함이 없는 사항은 근로관계법령에 따름",
    ],
    "date_row": "      년      월      일",
    "employer_rows": [
        "(사업주) 사업체명 :                   (전화 :                )",
        "        주    소 :",
        "        대 표 자 :                   (서명)",
    ],
    "worker_rows": [
        "(근로자) 주    소 :",
        "        연 락 처 : ",
        "        성    명 :                   (서명)",
    ],
    #: The 동의서 sheet's 인적사항 block — the identity seats. 2025 asks for
    #: 생년월일 here; 2013 asked for 주민등록번호 (see BLANK_2013).
    "consent_rows": [
        "○ 친권자(후견인) 인적사항",
        "   성    명 :",
        "   생년월일 :",
        "   연 락 처 :",
    ],
    "consent_signature": "친권자(후견인)                     (인)",
}

#: The same pack in the 2013 revision's vocabulary. Every difference below was
#: measured on the corpus pair, and together they are what makes
#: template_version_mixed / template_version_changed decidable.
BLANK_2013: dict = {
    **BLANK,
    "banner_main": "표준근로계약서",
    "clauses": [
        "1. 근로계약기간 :      년   월   일부터      년   월   일까지",
        "2. 근 무 장 소 : ",
        "3. 업무의 내용 : ",
        "4. 소정근로시간 :    시   분부터    시   분까지",
        "5. 근무일/휴일 : 매주   일근무, 주휴일 매주   요일",
        "6. 임  금",
        "7. 연차유급휴가",
        "8. 근로계약서 교부",
        "9. 기  타",
    ],
    "wage_rows": [
        "  - 월(일, 시간)급 :                    원",
        "  - 상여금 : 있음 (    )                    원,  없음 (     )",
        "  - 기타급여(제수당 등) : 있음 (    ),   없음 (    )",
        "  - 임금지급일 : 매월(매주 또는 매일)       일(휴일의 경우는 전일 지급)",
        "  - 지급방법 : 근로자에게 직접지급(    ),  "
        "근로자 명의 예금통장에 입금(    )",
    ],
    "legal_rows": [
        "  - 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함",
        "  - 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 "
        "교부요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)",
        "  - 이 계약에 정함이 없는 사항은 근로기준법령에 의함",
    ],
    "consent_rows": [
        "○ 친권자(후견인) 인적사항",
        "   성    명 :",
        "   주민등록번호 :",
        "   연 락 처 :",
    ],
}

#: A correctly completed contract: both parties identified, the seats the
#: operator had values for written, the date written, the signature markers and
#: every identity seat left for the human, every legal sentence intact.
FILLED: dict = {
    **BLANK,
    "opening": "한빛정밀 주식회사(이하 “사업주”라 함)과(와) 이서준"
               "(이하 “근로자”라 함)은 다음과 같이 근로계약을 체결한다.",
    "clauses": [
        "1. 근로개시일 :  2026년 9월 1일부터",
        "2. 근 무 장 소 : 경기도 화성시 동탄산단로 15",
        "3. 업무의 내용 : 정밀 이송 스테이지 조립 및 검사",
        "4. 소정근로시간 : 09시 00분 ~ 18시 00분 (휴게 : 12시 00분 ~ 13시 00분)",
        "5. 근무일/휴일 : 매주 5 일 근무, 주휴일 매주 일 요일",
        "6. 임  금",
        "7. 연차유급휴가",
        "8. 사회보험 적용여부",
        "9. 근로계약서 교부",
        "10. 근로계약, 취업규칙 등의 성실한 이행의무",
        "11. 그 밖의 사항",
    ],
    "wage_rows": [
        "  - 월(일, 시간)급 :  2,800,000  원",
        "  - 상여금 : 있음 (    )                    원,  없음 ( ○ )",
        "  - 그 밖의 수당(약정수당) : 있음 [    ],   없음 [ ○ ]",
        "  - 임금지급일 : 매월(매주 또는 매일)   25  일(휴일의 경우는 전날 지급)",
        "  - 지급방법 : 근로자에게 직접(현금)지급 [   ], "
        "근로자 명의 계좌에 입금 [ ○ ]",
    ],
    "date_row": "     2026년   8월   20일",
    "employer_rows": [
        "(사업주) 사업체명 : 한빛정밀 주식회사 (전화 : 031-000-0000)",
        "        주    소 : 경기도 화성시 동탄산단로 15",
        "        대 표 자 : 김도현 (서명)",
    ],
    "worker_rows": [
        "(근로자) 주    소 : 경기도 수원시 영통구 반달로 7",
        "        연 락 처 : 010-0000-0000",
        "        성    명 : 이서준 (서명)",
    ],
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


def _para(text: str) -> str:
    if text is None:
        return ""
    return (f'<hp:p id="1" paraPrIDRef="0" styleIDRef="0">'
            f'<hp:run charPrIDRef="0"><hp:t>{escape(text)}</hp:t></hp:run>'
            f'</hp:p>')


def _banner(text: str) -> str:
    """A one-cell banner table — how the pack introduces each variant."""
    if text is None:
        return ""
    return (
        '<hp:tbl id="800" rowCnt="1" colCnt="1" borderFillIDRef="4"><hp:tr>'
        '<hp:tc name="" header="0" borderFillIDRef="4">'
        f'<hp:subList>{_para(text)}</hp:subList>'
        '<hp:cellAddr rowAddr="0" colAddr="0"/>'
        '<hp:cellSpan rowSpan="1" colSpan="1"/>'
        '<hp:cellSz width="40000" height="2000"/>'
        '</hp:tc></hp:tr></hp:tbl>'
    )


def _rows(spec: dict, key: str) -> str:
    return "".join(_para(text) for text in (spec.get(key) or []))


def build_section(spec: dict) -> str:
    """The contract pack: banner + clauses + signature block, twice."""
    main = "".join((
        _para(spec.get("opening")),
        _rows(spec, "clauses"),
        _rows(spec, "wage_rows"),
        _rows(spec, "legal_rows"),
        _para(spec.get("date_row")),
        _rows(spec, "employer_rows"),
        _rows(spec, "worker_rows"),
    ))
    consent = "".join((
        _rows(spec, "consent_rows"),
        _para(spec.get("date_row")),
        _para(spec.get("consent_signature")),
    ))
    body = (_banner(spec.get("banner_main")) + main
            + _banner(spec.get("banner_consent")) + consent)
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


def write_hr(path: Path, spec: dict | None = None, *,
             malformed: bool = False, **overrides) -> Path:
    """Write a synthetic 근로계약서 hwpx. ``overrides`` patch ``spec`` (default
    BLANK)."""
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


def write_not_a_contract(path: Path) -> Path:
    """A valid hwpx that is not a 근로계약서 at all (structure-absent fixture)."""
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
