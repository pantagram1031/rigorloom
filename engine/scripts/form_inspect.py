#!/usr/bin/env python3
"""form_inspect.py — .hwpx 양식(form)을 오프라인(비-COM)으로 프로파일링.

한글(Hancom) 없이 .hwpx(zip)를 풀어 header.xml(charPr/paraPr 정의)과
section*.xml(문단/런) 을 대조해, 조립(build_report.py) 전에 알아야 할 양식의
구조 — 앵커(제목/섹션 헤더), 안내문(작성 지침·색깔 강조·예시), 서식 제약
(글자크기·줄간격·분량) — 를 결정론적으로 뽑아낸다.

    python form_inspect.py FORM.hwpx [--out form_profile.json] [--baseline form_baseline.json]
        [--base-pt 10] [--line-spacing 160]
        [--full-text [TABLE:]ROW,COL | PARA:N ...]

--baseline: form_profile.json에 더해 폰트/크기/색/줄간격/사용빈도 분포를
            form_baseline.json으로 추가 기록한다(style_diff.py의 기준선).
--base-pt/--line-spacing: page_metrics의 lines_per_page/chars_per_line 계산에
            쓰는 가정값(각각 기본 10pt/160%).
--full-text: 구조-전용 계약의 **의도적 탈출구**. 이름 붙인 셀
            (`TABLE:ROW,COL`) 또는 문단(`PARA:N`)만 정확한 텍스트/런을
            `full_text`로 emit한다(반복 가능). 셀/문단 단위 opt-in인 이유:
            자리표의 정확한 내부 공백이나 `preedit`의 `at_para` 주소가 필요한
            소수 경로에서만 쓰고, 그 밖에는 profile이 본문 전체를 담지 않아야
            한다. 요청하지 않은 셀·문단은 한 글자도 나오지 않는다. 자리표를
            **고치는** 것이 목적이면 보통 문자열이 아예 필요 없다 —
            `preedit replace --at-cell ROW,COL=값` 이 주소로 대상을 잡는다(T34).

v2 추가 섹션(form_profile.json):
  page_metrics — section0.xml의 hp:pagePr/margin에서 페이지 여백/가용영역과
                 lines_per_page/chars_per_line 파생값.
  table_map    — 모든 hp:tbl의 셀 단위 지도(addr/size/borderFill/음영/분류).
                 분류는 guide / static / fill_target / **spacer** 네 가지다.
                 spacer = 격자를 위해 존재하는 빈 칸(구분 띠, 행렬 모서리) —
                 라벨 이웃이 없고 인쇄물도 없으며 격자의 filler 기하를 갖는다.
                 fill_target 수에서 **빠지고** spacer_cells로 따로 보고한다.
                 `text_preview`는 30자로 자르되 잘렸으면 `truncated: true`를
                 함께 보고한다(T34 — 무표시 잘림이 스켈레톤 중간의 빈칸을
                 숨겼다). 정확한 전문은 --full-text ROW,COL.
  break_audit  — header.xml paraPr들의 hh:breakSetting 플래그 집계.
  anchor_records — 기존 anchors의 legacy `para_idx`/text/section을 보존하면서
                   preedit과 같은 depth-first 문단 주소 `at_para`를 추가한다.
                   `at_para`는 scoped replacement와 PARA:N 조회용이며, 기존
                   `para_idx`를 재번호화하지 않는다(신원 매핑 불가 시 생략).

T30 사전 점검(fill 대상 charPr):
  body_baseline_charpr    — 문서 자신의 본문 baseline charPr(id/height_pt/
                            script signature). 상단에 한 번 보고한다.
  table_map[*].cells[*]   — classification=="fill_target" 셀에만:
      charpr             채우기가 **상속할** 런의 charPrIDRef
      script_anomaly     그 charPr이 baseline과 supscript/subscript/ratio/
                         relSz/offset 중 하나라도 다른가(True/False,
                         판정 불가면 None)
      charpr_suggested   대신 써야 할 id(= baseline id)
  script_anomaly_targets  — script_anomaly인 대상 셀만 모은 목록(빠른 확인용).
  spacer_cells            — 구조용 빈 칸 목록({table, addr, pattern}).
  fill_target_count       — spacer를 제외한 실제 채우기 대상 수.

  절차: form_inspect로 뽑고 → script_anomaly를 보고 → `preedit fill-cells`에
  `--charpr-per-cell ROW,COL=<charpr_suggested>`로 넘긴다. 넘기지 않으면
  fill-cells가 exit 3으로 거부한다(조용히 ~6.35pt 올려찍는 대신).

exit 0: 정상. exit 1: anomaly 없음(항상 0, 이 스크립트는 진단 전용).
exit 2: 사용법/파일 오류.
"""
import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli_io import utf8_stdio  # noqa: E402
from hwpx_tables import find_cell, scan_tables  # noqa: E402
# T30 사전 점검 — script/scale/offset 어휘는 visual_verify(사후 검출)와 공유하고,
# '어느 런을 채우는가'는 preedit(실제 채우는 쪽)에서 그대로 가져온다.
# 두 도구가 어긋날 수 있으면 사전 점검은 없는 것보다 나쁘다.
import charpr_script  # noqa: E402
# --full-text의 런 색인은 `preedit replace --at-cell ROW,COL#RUN`이 편집하는
# 런과 **같은 열거**여야 한다(T34) — 그래서 같은 함수를 쓴다.
from preedit import (_find_paragraphs,
                     _iter_document_paragraphs as _iter_document_paragraphs_with_offsets,
                     cell_text_runs, fill_target_run_charpr,
                     paragraph_text_runs)  # noqa: E402

NS = r'[A-Za-z0-9]+'  # 임의 네임스페이스 prefix(hp/hh 고정 가정 X)
Q = r'["\']'  # 큰따옴표/작은따옴표 모두 허용

# 태그를 통째로 잡은 뒤 속성은 태그 문자열 안에서 별도 탐색 → 속성 순서 무관.
# 자기닫힘 요소(<hp:run .../>, <hp:t/>)는 텍스트가 없는 완결 매치다 —
# [^>]*>(.*?)</ns:tag> 형태로 잡으면 /> 를 attrs로 삼켜버리고 다음 형제
# 요소의 닫는 태그까지 스캔해 그 텍스트를 훔친다(T37, docs/trouble-table.md).
# /> | >(.*?)</ns:tag> 분기로 자기닫힘을 body 없는 매치로 인식한다.
# 네임스페이스는 일부러 논캡처로 둔다: 그룹 수는 이 패턴의 공개 인터페이스이고
# (style_diff·check_gongmun이 findall/group(n)으로 직접 쓴다), 늘리면 호출부가
# 조용히 어긋난다 — T37 1차 수정이 정확히 그렇게 깨졌다.
RUN_TAG_RE = re.compile(
    r'<' + NS + r':run\b([^>]*?)(?:/>|>(.*?)</' + NS + r':run>)', re.S)
P_TAG_RE = re.compile(r'<' + NS + r':p\b([^>]*)>(.*?)</' + NS + r':p>', re.S)
T_RE = re.compile(
    r'<' + NS + r':t\b[^>]*?(?:/>|>(.*?)</' + NS + r':t>)', re.S)
BRACKET_RE = re.compile(r'\[([^\[\]]{1,40})\]')
ROMAN_HEAD_RE = re.compile(r'^\s*([IVXⅠ-Ⅻ]+)[.\)]\s*\S')
NUM_HEAD_RE = re.compile(r'^\s*\d+\.\s*\S')

# A long signature seat is still an anchor, but only when its shape says so:
# a known party/signature label, a field colon, and a trailing parenthetical
# signature marker. Requiring all three keeps arbitrary long prose out of
# ``anchors`` while admitting seats such as ``업체명(성명) : ... (인)``.
SIGNATURE_ANCHOR_RE = re.compile(
    r'^\s*(?:업체명\s*\(\s*성명\s*\)|업체명|성명|대표자|신청인|담당자|'
    r'상호|기관명)\s*[:：][\s._＿\-·…]*'
    r'\(\s*(?:인|서명(?:\s*또는\s*인)?|날인)\s*\)\s*$'
)


def _attr(tag_attrs, name):
    """태그 속성 문자열에서 name="..." 또는 name='...' 값 추출(순서 무관)."""
    m = re.search(name + r'\s*=\s*(' + Q + r')(.*?)\1', tag_attrs, re.S)
    return m.group(2) if m else None


INSTRUCTION_KEYWORDS = (
    "작성하세요", "작성한다", "작성합니다", "입력", "지우고", "삭제",
    "기술합니다", "기술한다", "제시합니다", "표기합니다", "기록합니다",
    # 존대 명령형(-십시오): 관공서 서식 안내문("…결정하여 주십시오",
    # "…작성하십시오"). 보고서 본문(평서체)에는 나타나지 않는 어미.
    # 동기 파일: pps-jeongbogonggae-donguiseo(W6.2).
    "십시오",
)
# 지시형 "기재"(관공서 서식의 대표 지시어): "…만 기재", "등으로 기재",
# "명확히 기재(…)" — 단, 서술형(기재된/기재되어)은 본문 인용체로 오탐이므로
# 제외한다. 동기 파일: moel-pyojun-geunrogyeyakseo-2013/2025(W6.2).
INSTRUCTION_RE = re.compile(r'기재(?![된되])')
EXAMPLE_PREFIXES = ("예:", "예시", "(예")
# 예시 마커가 문두가 아닌 위치에 오는 관공서 관례: "ㅇ (예시①) 주5일 …".
# "(예외…)", "(예상…)" 같은 본문 괄호는 닫는 괄호 직전까지 숫자/원문자만
# 허용하므로 매치되지 않는다. 동기 파일: moel-pyojun-geunrogyeyakseo-2025.
EXAMPLE_MARK_RE = re.compile(r'\(예시?\s*[①-⑳0-9]*\)')
# 주석/안내 접두 기호 관례(관공서 서식): ※·☞·◁·▷·＊·*·주N). 본문 산문이
# 이 기호로 문단을 시작하는 일은 없다(보고서 corpus 스틸-캐치 픽스처로 고정).
# 동기 파일: moel-2025(※/◁◁), pps-jeongbogonggae-donguiseo(※/☞),
# pps-hyeopeop-seungin-sinchengseo(*).
NOTE_PREFIX_RE = re.compile(r'^(?:※|☞|◁|▷|＊|\*|주\d{0,2}\))')


def _has_instruction(text):
    """지시어 포함 여부(키워드 + 지시형 '기재' 정규식)."""
    return any(kw in text for kw in INSTRUCTION_KEYWORDS) or bool(
        INSTRUCTION_RE.search(text))


def die(msg, code=2):
    line = json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.exit(code)


def _charpr_defs(header_xml):
    """charPr id -> {height_pt, color, fontRef}. fontRef는 lang별 font id dict."""
    defs = {}
    for m in re.finditer(r'<' + NS + r':charPr\b([^>]*?)/?>', header_xml):
        attrs = m.group(1)
        cid = _attr(attrs, "id")
        if cid is None:
            continue
        height = _attr(attrs, "height")
        color = _attr(attrs, "textColor")
        tail = header_xml[m.end():m.end() + 400]
        fr = re.search(r'<' + NS + r':fontRef\b([^/>]*)/?>', tail)
        font_ref = {}
        if fr:
            for k, v in re.findall(r'(\w+)\s*=\s*' + Q + r'(\d+)' + Q, fr.group(1)):
                font_ref[k] = v
        defs[cid] = {
            "height_pt": int(height) / 100.0 if height else None,
            "color": (color.upper() if color and re.match(r'#?[0-9A-Fa-f]{6}$', color) else None),
            "fontRef": font_ref,
        }
    return defs


def _fontfaces(header_xml):
    """lang -> {font_id: face_name}."""
    out = {}
    for m in re.finditer(
            r'<' + NS + r':fontface\b([^>]*)>(.*?)</' + NS + r':fontface>', header_xml, re.S):
        lang = _attr(m.group(1), "lang")
        body = m.group(2)
        fonts = {}
        for fm in re.finditer(r'<' + NS + r':font\b([^>]*?)/?>', body):
            fid = _attr(fm.group(1), "id")
            face = _attr(fm.group(1), "face")
            if fid is not None and face is not None:
                fonts[fid] = face
        out[lang] = fonts
    return out


def _paraprops(header_xml):
    """paraPr id -> {lineSpacing_type, lineSpacing_value}. 첫 hp:default 항목 사용."""
    out = {}
    for m in re.finditer(r'<' + NS + r':paraPr\b([^>]*?)/?>', header_xml):
        attrs = m.group(1)
        pid = _attr(attrs, "id")
        if pid is None:
            continue
        tail = header_xml[m.end():m.end() + 2000]
        # hp:default 블록 우선, 없으면 첫 매치.
        default_block = re.search(r'<' + NS + r':default\b[^>]*>(.*?)</' + NS + r':default>', tail, re.S)
        scope = default_block.group(1) if default_block else tail
        lsm = re.search(r'<' + NS + r':lineSpacing\b([^/>]*)/?>', scope)
        ls_type = ls_value = None
        if lsm:
            ls_type = _attr(lsm.group(1), "type")
            v = _attr(lsm.group(1), "value")
            ls_value = int(v) if v is not None else None
        out[pid] = {"type": ls_type, "value": ls_value}
    return out


def font_face(defs, fontref_map, cid, lang="hangul"):
    fr = defs.get(cid, {}).get("fontRef", {})
    fid = fr.get(lang)
    if fid is None:
        return None
    return fontref_map.get("HANGUL" if lang == "hangul" else lang.upper(), {}).get(fid)


def _paragraphs(xml, defs):
    """section xml -> [{text, paraPr, charPrs:[...]}]."""
    out = []
    for pm in P_TAG_RE.finditer(xml):
        p_attrs = pm.group(1)
        para_pr = _attr(p_attrs, "paraPrIDRef")
        if para_pr is None:
            continue
        body = pm.group(2)
        cids, text_parts = [], []
        for rm in RUN_TAG_RE.finditer(body):
            cid = _attr(rm.group(1), "charPrIDRef")
            if cid is None:
                continue
            run_body = rm.group(2)
            # 자기닫힘 런(빈 셀 fill target)은 텍스트가 없다 — id는 T30
            # 사전 점검을 위해 그대로 charPrs에 넣되, 본문에는 아무것도
            # 보태지 않는다(T37).
            cids.append(cid)
            if run_body:
                text_parts.append(re.sub(
                    r"<[^>]+>", "", "".join(T_RE.findall(run_body))))
        text = "".join(text_parts)
        # ``para_idx`` is a historical profile index.  Retain the regex
        # match's XML span privately so new address records can bind the same
        # paragraph to preedit's depth-first ``at_para`` without changing the
        # legacy index or its consumers.
        out.append({"text": text, "paraPr": para_pr, "charPrs": cids,
                    "_start": pm.start(), "_end": pm.end()})
    return out


TOP_TAG_RE = re.compile(r'<(/?)(' + NS + r'):([A-Za-z0-9]+)\b[^>]*?(/?)>', re.S)
TOP_P_OPEN_RE = re.compile(r'<' + NS + r':p\b([^>]*)>', re.S)
TOP_CONTENT_TAGS = ('tbl', 'pic', 'container', 'ole', 'line', 'rect', 'ellipse',
                     'arc', 'polygon', 'curve', 'connectLine', 'equation')
TOP_CONTENT_RE = re.compile(r'<' + NS + r':(' + '|'.join(TOP_CONTENT_TAGS) + r')\b')


def _find_top_level_paragraphs(xml):
    """xml에서 최상위(표 셀 등에 중첩되지 않은) <hp:p> 조각들의 (start, end, text)
    목록 — tidy_hwpx._find_paragraphs와 동일한 스택 기반 판정(well-formed XML
    가정, close 태그는 항상 스택 맨 위 open과 짝). blanks_before 계산은 반드시
    top-level 문단만 봐야 한다 — _paragraphs()는 표 셀 내부 문단까지 문서 순서로
    섞어 넣으므로 여기엔 못 쓴다(별도 함수로 분리)."""
    paras = []
    stack = []
    pos = 0
    length = len(xml)
    while pos < length:
        m = TOP_TAG_RE.search(xml, pos)
        if not m:
            break
        is_close, prefix, local, selfclose = m.groups()
        if selfclose:
            pos = m.end()
            continue
        if not is_close:
            stack.append((prefix, local, m.start()))
        elif stack:
            _op, opened_local, open_start = stack.pop()
            if opened_local == "p":
                is_top = not any(s[1] == "p" for s in stack)
                if is_top:
                    end = m.end()
                    p_xml = xml[open_start:end]
                    text = "".join(re.sub(r"<[^>]+>", "", t)
                                   for t in T_RE.findall(p_xml))
                    paras.append((open_start, end, text))
        pos = m.end()
    return paras


def _is_empty_top_para(p_start, p_end, xml, text):
    """빈 top-level 문단인지(런 텍스트 없고 표/그림 등 내용물도 없음) —
    tidy_hwpx._is_empty_para와 동일 판정."""
    if text.strip():
        return False
    p_xml = xml[p_start:p_end]
    return not TOP_CONTENT_RE.search(p_xml)


def _blanks_before_map(section_names, z, anchor_texts):
    """{anchor_text: blanks_before} — 각 anchor 문단 바로 앞(같은 섹션,
    top-level)에 연속된 빈 문단 개수. anchor가 섹션 전체에서 정확히 1번
    매치될 때만 기록한다(모호/미발견 anchor는 조용히 생략 — tidy_hwpx의
    앵커 유일성 요구와 동일 안전장치, 여기선 진단 전용이라 die하지 않음)."""
    if not anchor_texts:
        return {}
    remaining = set(anchor_texts)
    out = {}
    for sname in section_names:
        if not remaining:
            break
        xml = z.read(sname).decode("utf-8")
        paras = _find_top_level_paragraphs(xml)
        text_hits = {}
        for i, (_s, _e, text) in enumerate(paras):
            stripped = text.strip()
            if stripped in remaining:
                text_hits.setdefault(stripped, []).append(i)
        for anchor, idxs in text_hits.items():
            if len(idxs) != 1:
                continue  # 모호(같은 섹션에 2회+) — 이 섹션에서는 판정 안 함.
            idx = idxs[0]
            count = 0
            j = idx - 1
            while j >= 0 and _is_empty_top_para(paras[j][0], paras[j][1], xml, paras[j][2]):
                count += 1
                j -= 1
            out[anchor] = count
            remaining.discard(anchor)
    return out


def _is_black_or_auto(color):
    if not color:
        return True
    c = color.lstrip("#").upper()
    return c in ("000000", "AUTO")


def _looks_like_citation(text):
    if "『" in text or "」" in text or "「" in text:
        return True
    if re.search(r'https?://\S+', text) and ("접속일" in text or "참고" in text or "날짜" in text):
        return True
    return False


def _classify_guide(text, colored):
    """guide_text 분류 reason 우선순위: colored > note_prefix > example > instruction."""
    stripped = text.strip()
    if colored:
        return "colored"
    if NOTE_PREFIX_RE.match(stripped):
        return "note_prefix"
    if any(stripped.startswith(p) for p in EXAMPLE_PREFIXES) or "예:" in stripped \
            or EXAMPLE_MARK_RE.search(stripped):
        return "example"
    if _has_instruction(stripped):
        return "instruction"
    return None


# 답을 표시할 슬롯을 품은 문단은 삭제 대상이 아니라 표기 대상이다.
# bracket-placeholder를 제외하는 것과 같은 논리이고(removal_targets 주석 참조),
# 그 규칙이 "문단 전체가 `[...]`"인 경우만 잡아 남긴 구멍을 문단 단위로 메운다.
# 같은 원칙이 이미 admrul-gajokdolbom 양식에는 양식 전체 단위로 적용돼 있다
# (test_guide_text_patterns.py docstring: 체크박스를 지우면 양식이 깨진다).
ANSWER_ENUM_RE = re.compile(r'\(\s*[^()]{1,12}?\s*,\s*[^()]{1,12}?\s*\)')
EMPTY_MARK_SLOT_RE = re.compile(r'\[\s*\]|□')


def _answer_slot_reason(text):
    """이 문단이 표기 지점인 이유, 아니면 None.

    12개 코퍼스 양식 전량 실측(#63): 정확히 3개 문단만 해당한다 —
    주민등록 등초본 신청서의 선택 필드 2개(`[  ]전체 포함  [  ]직접 입력…`)와
    정보공개 동의서의 동의 문항(`☞ … 동의하십니까? (예,  아니오)`).

    임계값 2는 고른 값이 아니라 코퍼스가 준 경계다: 표기 규칙을 *설명하기만* 하는
    안내문 7개(`※ [  ]에는 해당하는 곳에 √표를 합니다` 등)는 슬롯이 1개씩이고
    삭제 후보로 남아야 한다. 완화할 때마다 그 7개가 여전히 잡히는지 확인할 것.
    """
    stripped = text.strip()
    if "?" in stripped and ANSWER_ENUM_RE.search(stripped):
        return "interrogative_enumeration"
    if len(EMPTY_MARK_SLOT_RE.findall(stripped)) >= 2:
        return "multiple_mark_slots"
    return None


def _looks_like_anchor(text, para_pr, heading_parapr_ids):
    stripped = text.strip()
    if not stripped:
        return False
    if BRACKET_RE.fullmatch(f"[{stripped}]") or (stripped.startswith("[") and stripped.endswith("]")):
        return True
    if ROMAN_HEAD_RE.match(stripped):
        return True
    if para_pr in heading_parapr_ids:
        return True
    if SIGNATURE_ANCHOR_RE.match(stripped):
        return True
    return False


ALIGN_MAP = {
    "JUSTIFY": "justify", "LEFT": "left", "RIGHT": "right",
    "CENTER": "center", "DISTRIBUTE": "distribute",
    "DISTRIBUTE_SPACE": "distribute",
}


def _align_map(header_xml):
    """paraPr id -> lowercased align value (hh:align horizontal=...).

    align 태그는 실측(대수_추가탐구기록지_양식.hwpx) 결과 paraPr 여는 태그
    바로 뒤(offset 0)에 위치 — 짧은 tail window로 충분.
    """
    out = {}
    for m in re.finditer(r'<' + NS + r':paraPr\b([^>]*?)/?>', header_xml):
        pid = _attr(m.group(1), "id")
        if pid is None:
            continue
        tail = header_xml[m.end():m.end() + 300]
        am = re.search(r'<' + NS + r':align\b([^/>]*)/?>', tail)
        if not am:
            continue
        horiz = _attr(am.group(1), "horizontal")
        if horiz is None:
            continue
        out[pid] = ALIGN_MAP.get(horiz.upper(), horiz.lower())
    return out


def _bold_map(header_xml):
    """charPr id -> True/False (hh:bold 빈 태그 존재 여부, charPr 블록 내부).

    close tag(</...:charPr>)를 못 찾아도(자기 닫힘 등) tail window 안에서
    존재 여부만 보므로 안전 — _charpr_defs()와 동일한 tail-scan 관례.
    """
    out = {}
    for m in re.finditer(r'<' + NS + r':charPr\b([^>]*?)/?>', header_xml):
        cid = _attr(m.group(1), "id")
        if cid is None:
            continue
        tail = header_xml[m.end():m.end() + 500]
        closem = re.search(r'</' + NS + r':charPr>', tail)
        window = tail[:closem.start()] if closem else tail
        out[cid] = bool(re.search(r'<' + NS + r':bold\s*/?>', window))
    return out


def _page_metrics(section0_xml, base_pt=10, line_spacing_pct=160):
    """secPr/pagePr(section0.xml) -> page_metrics dict.

    HWP unit: 1 hwpunit = 1/7200 inch, 1pt = 100 hwpunit.
    usable_width  = width  - left - right
    usable_height = height - top - bottom - header - footer
    (gutter은 원본 값만 기록하고 usable 계산에는 넣지 않음 — gutterType별로
    좌/우/양쪽 중 어디에 더해지는지가 갈려 결정론적으로 단정할 수 없음.)
    """
    m = re.search(r'<' + NS + r':pagePr\b([^>]*)>', section0_xml)
    if not m:
        return None
    pp_attrs = m.group(1)
    width = _attr(pp_attrs, "width")
    height = _attr(pp_attrs, "height")
    tail = section0_xml[m.end():m.end() + 400]
    mm = re.search(r'<' + NS + r':margin\b([^/]*)/?>', tail)
    margin = {}
    if mm:
        for k in ("left", "right", "top", "bottom", "header", "footer", "gutter"):
            v = _attr(mm.group(1), k)
            margin[k] = int(v) if v is not None else None

    width_i = int(width) if width is not None else None
    height_i = int(height) if height is not None else None

    def _m(key):
        return margin.get(key) or 0

    usable_width = usable_height = None
    if width_i is not None:
        usable_width = width_i - _m("left") - _m("right")
    if height_i is not None:
        usable_height = height_i - _m("top") - _m("bottom") - _m("header") - _m("footer")

    line_height = base_pt * 100 * line_spacing_pct / 100
    lines_per_page = int(usable_height // line_height) if usable_height is not None else None
    chars_per_line = int(usable_width // (base_pt * 100)) if usable_width is not None else None

    return {
        "width": width_i,
        "height": height_i,
        "margin": margin,
        "usable_width": usable_width,
        "usable_height": usable_height,
        "lines_per_page": lines_per_page,
        "chars_per_line": chars_per_line,
        "assumptions": {
            "base_pt": base_pt,
            "line_spacing_pct": line_spacing_pct,
            "line_height_hwpunit": line_height,
            "usable_width_formula": "width - left - right",
            "usable_height_formula": "height - top - bottom - header - footer",
            "chars_per_line_formula": "floor(usable_width / (base_pt*100)) — Korean full-width 가정",
        },
    }


def _borderfill_shaded(header_xml):
    """borderFillIDRef -> bool(음영: fillBrush의 face color가 white/none이 아님)."""
    out = {}
    for m in re.finditer(
            r'<' + NS + r':borderFill\b([^>]*)>(.*?)</' + NS + r':borderFill>', header_xml, re.S):
        bfid = _attr(m.group(1), "id")
        if bfid is None:
            continue
        body = m.group(2)
        shaded = False
        fbm = re.search(r'faceColor\s*=\s*(' + Q + r')(.*?)\1', body, re.S)
        if fbm:
            face = fbm.group(2).strip()
            if face and face.lower() not in ("none", "#ffffff", "white"):
                shaded = True
        out[bfid] = shaded
    return out


def _own_cell_body(xml, cell, tables):
    """셀 몸통에서 중첩 표 스팬을 제거한 '이 셀 자신의' XML."""
    lo, hi = cell["body_start"], cell["body_end"]
    spans = sorted((t["start"], t["end"]) for t in tables
                   if t["start"] >= lo and t["end"] <= hi)
    out, cur = [], lo
    for s, e in spans:
        if s < cur:
            continue
        out.append(xml[cur:s])
        cur = e
    out.append(xml[cur:hi])
    return "".join(out)


def _body_charpr_weights(section_names, z):
    """charPr id -> 본문 텍스트 글자수(본문 baseline 선정 가중치).

    visual_verify의 T30 사후 검출이 쓰는 것과 **같은 가중치·같은 스캐너**다
    (charpr_script.iter_runs + 공백 제거 길이). 채우기 전 양식에는 fill 값이
    아직 없으니 텍스트가 있는 모든 런이 본문이다 — 빈 셀의 텍스트 없는 런은
    iter_runs가 애초에 세지 않으므로 양식의 빈칸이 본문을 이길 수 없다.
    """
    weights = {}
    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        for cid, text in charpr_script.iter_runs(xml):
            weights[cid] = weights.get(cid, 0) + len(charpr_script.norm(text))
    return weights


def _fill_preflight(raw_body, script_profiles, baseline_id):
    """fill_target 셀 하나의 T30 사전 점검 필드.

    charpr가 안 잡히거나(쓸 런이 없다 — fill-cells도 거부한다) baseline/프로파일이
    없으면 script_anomaly는 **판정하지 않은 것**을 뜻하는 None이다. False(=검사했고
    깨끗하다)와 구별된다 — 못 본 것을 깨끗하다고 보고하면 사전 점검이 아니다.
    """
    run_charpr = fill_target_run_charpr(raw_body)
    profile = script_profiles.get(run_charpr)
    baseline_profile = script_profiles.get(baseline_id)
    out = {"charpr": run_charpr,
           "script_anomaly": None,
           "charpr_suggested": baseline_id}
    if run_charpr is None or profile is None or baseline_profile is None:
        return out
    differing = charpr_script.differing_keys(profile, baseline_profile)
    out["script_anomaly"] = bool(differing)
    if differing:
        out["script_differing"] = differing
        out["nominal_height_pt"] = profile.get("height_pt")
        rendered = charpr_script.rendered_pt_estimate(profile)
        if rendered is not None:
            out["rendered_pt_estimate"] = rendered
    return out


def _cell_band(cell):
    """(row0, row1, col0, col1) — the half-open grid band a cell occupies."""
    addr = cell.get("addr")
    if not addr:
        return None
    span = cell.get("span") or {}
    return (addr["row"], addr["row"] + (span.get("row") or 1),
            addr["col"], addr["col"] + (span.get("col") or 1))


def _prints_text(cell):
    return bool((cell.get("text_preview") or "").strip())


def _label_neighbour(cells, cell, col_cnt):
    """The printed cell that makes ``cell`` the VALUE half of a label pair.

    Two spellings, and only two, because those are the two the corpus grids
    actually use:

    - **left**: a printed cell ending exactly where this one starts, on the
      same row band (``명 칭`` → the name field, ``법인등록번호`` → its field);
    - **above**: a printed cell ending exactly where this row starts and
      covering **exactly** this cell's column band (a matrix column header:
      ``업 체 명`` over the 협업업체 name column).

    Column-band EQUALITY is what keeps the relation honest. A form's title or
    a preceding prose band also sits "above" a full-width strip, but it does
    not delimit a field, and a narrow label one row up (PPS ``첨부서류`` at
    (17,0)) does not own the full-width strip below it. Two stacked
    full-width bands are document flow, never a label/value pair, so that
    combination is excluded outright.
    """
    band = _cell_band(cell)
    if band is None:
        return None
    r0, r1, c0, c1 = band
    mine_full = (c1 - c0) >= col_cnt if col_cnt else False
    for other in cells:
        if other is cell or not _prints_text(other):
            continue
        oband = _cell_band(other)
        if oband is None:
            continue
        R0, R1, C0, C1 = oband
        if C1 == c0 and R0 == r0 and R1 == r1:
            return {"direction": "left", "addr": other["addr"],
                    "text": (other.get("text_preview") or "").strip()[:30]}
        if R1 == r0 and C0 == c0 and C1 == c1:
            other_full = (C1 - C0) >= col_cnt if col_cnt else False
            if other_full and mine_full:
                continue
            return {"direction": "above", "addr": other["addr"],
                    "text": (other.get("text_preview") or "").strip()[:30]}
    return None


def _filler_geometry(cells, cell, col_cnt, min_text_height):
    """Which of the grid's filler shapes this empty cell has, or None.

    Both shapes are DERIVED from the table itself — no address, no absolute
    height, no tuned ratio:

    ``full_width_band``
        spans every column of its table AND is shorter than the shortest cell
        in that same table that manages to print text. Spanning every column
        means it also spans the label column, so no field can live in it; the
        height says the grid itself never fits a text line at that size.
        These are the hairline rules between blocks and the trailing gap
        bands (PPS (1,0)/(9,0)/(12,0) at 240 and (16,0)/(18,0) at 1280/1080,
        against a 1860 shortest printed cell).

    ``stub_head``
        the empty corner where a header row crosses a label column: every
        OTHER cell in its row prints text and is static, and the cell
        directly beneath it — sharing its exact column band — prints text
        too. That is the matrix stub (PPS (13,0), above ``협업업체`` and
        beside ``업 체 명 / 대표자 / 전 화 / 사업장주소``). Nothing is ever
        written there.
    """
    band = _cell_band(cell)
    if band is None:
        return None
    r0, r1, c0, c1 = band
    if col_cnt and (c1 - c0) >= col_cnt:
        height = cell.get("height")
        if (min_text_height is not None and height is not None
                and height < min_text_height):
            return "full_width_band"
        return None
    row_mates = [o for o in cells
                 if o is not cell and (_cell_band(o) or (None,))[0] == r0]
    if not row_mates:
        return None
    if not all(o.get("classification") == "static" and _prints_text(o)
               for o in row_mates):
        return None
    for other in cells:
        oband = _cell_band(other)
        if oband is None or not _prints_text(other):
            continue
        R0, _R1, C0, C1 = oband
        if R0 == r1 and C0 == c0 and C1 == c1:
            return "stub_head"
    return None


def _mark_spacers(cells, col_cnt):
    """Reclassify structural filler cells ``fill_target`` -> ``spacer``.

    A spacer is an empty cell the GRID needs and no writer ever touches. The
    three conditions are conjunctive: no printed content (it was a
    ``fill_target``), no label neighbour (nothing names it, so nothing can be
    asked for it), and one of the filler geometries above. Codex and the
    round-3 Opus run each had to reason six such cells away on the PPS form
    before they could trust the ``fill_target`` count; a genuinely empty
    fillable cell keeps its label neighbour (PPS (2,7) under
    ``법인등록번호``) and stays a ``fill_target``.

    Returns the spacer entries, in scan order.
    """
    heights = [c["height"] for c in cells
               if _prints_text(c) and c.get("height")]
    min_text_height = min(heights) if heights else None
    spacers = []
    for cell in cells:
        if cell.get("classification") != "fill_target":
            continue
        if _label_neighbour(cells, cell, col_cnt) is not None:
            continue
        pattern = _filler_geometry(cells, cell, col_cnt, min_text_height)
        if not pattern:
            continue
        cell["classification"] = "spacer"
        cell["spacer_pattern"] = pattern
        spacers.append(cell)
    return spacers


def _table_map(section_names, z, defs, borderfill_shaded,
               script_profiles=None, baseline_id=None):
    """모든 section의 모든 hp:tbl -> table_map 엔트리 리스트.

    cell 분류(guide/fill_target/static)는 _classify_guide/_looks_like_anchor와
    동일 휴리스틱을 재사용한다(새 규칙 도입 안 함). 그 위에 _mark_spacers가
    구조용 빈 칸을 fill_target에서 spacer로 내린다 — 판정 근거는 표 자신의
    기하이지 주소 목록이 아니다.

    fill_target 셀에는 T30 사전 점검 필드가 붙는다(그 외 분류에는 붙지 않는다 —
    의도적으로 위첨자인 각주 표식 같은 **비대상** 런은 애초에 비교 대상이
    아니다): charpr(채우기가 상속할 런의 id), script_anomaly(본문 baseline과
    supscript/subscript/ratio/relSz/offset 중 하나라도 다름),
    charpr_suggested(본문 baseline id).

    표 스캔은 `hwpx_tables.scan_tables`(태그 스택, 중첩 안전)에 위임한다 —
    `preedit fill-cells`가 `--table N`으로 가리키는 색인과 **같은 규약**이어야
    하기 때문이다. 옛 비탐욕 정규식 `<hp:tbl>(.*?)</hp:tbl>` 은 바깥 표의 여는
    태그를 안쪽 표의 닫는 태그와 짝지어, 코퍼스 12개 양식 중 6개에서 표 수와
    셀 수를 틀렸다(gianmun-byeolji-1ho: 표 3→2, 셀 34→6). 중첩 표는 자기
    색인을 갖고(depth로 구분), 셀 텍스트에는 중첩 표의 내용이 섞이지 않는다.
    """
    tables = []
    idx = 0
    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        scanned = scan_tables(xml)
        for tbl in scanned:
            t_attrs = tbl["attrs"]
            row_cnt = _attr(t_attrs, "rowCnt")
            col_cnt = _attr(t_attrs, "colCnt")
            page_break = _attr(t_attrs, "pageBreak")
            repeat_header = _attr(t_attrs, "repeatHeader")

            cells = []
            for cell in tbl["cells"]:
                tc_attrs = cell["attrs"]
                tc_body = _own_cell_body(xml, cell, scanned)
                bfid = _attr(tc_attrs, "borderFillIDRef")
                addr = ({"row": cell["addr"][0], "col": cell["addr"][1]}
                        if cell["addr"] else None)
                width = height = None
                szm = re.search(r'<' + NS + r':cellSz\b([^/>]*)/?>', tc_body)
                if szm:
                    w = _attr(szm.group(1), "width")
                    h = _attr(szm.group(1), "height")
                    width = int(w) if w is not None else None
                    height = int(h) if h is not None else None

                paras = _paragraphs(tc_body, defs)
                text = "".join(p["text"] for p in paras)
                cids = [c for p in paras for c in p["charPrs"]]
                colors = [defs.get(cid, {}).get("color") for cid in cids]
                colored = any(not _is_black_or_auto(c) for c in colors)
                reason = _classify_guide(text, colored) if text.strip() else None
                is_empty = not text.strip()
                if reason:
                    classification = "guide"
                elif is_empty:
                    classification = "fill_target"
                else:
                    classification = "static"

                shaded = borderfill_shaded.get(bfid, False) if bfid is not None else False

                entry = {
                    "addr": addr,
                    "span": {"row": cell["span"][0], "col": cell["span"][1]},
                    "width": width,
                    "height": height,
                    "borderFillIDRef": bfid,
                    "shaded": shaded,
                    "text_preview": text[:30],
                    # 잘림은 **말해야** 한다(T34). 무표시 30자 잘림 때문에
                    # 3라운드 클린룸의 Sonnet 티어는 협업기간 스켈레톤
                    # "20   .    .    .  ~  20   .    .    .   (     개월)"
                    # (50자) 중간의 "(     개월)" 빈칸을 아예 못 봤고, 채우기를
                    # 한 번 더 돌려야 했다. preview는 그대로 두고 '더 있다'만
                    # 밝힌다 — 정확한 문자열은 --full-text ROW,COL 이 준다.
                    "truncated": len(text) > 30,
                    "classification": classification,
                }
                # 원본 몸통(중첩 표 제거 전) — preedit의 문단 색인과 같아야
                # 하므로 _own_cell_body 결과를 쓰면 안 된다. spacer 판정이
                # 끝난 뒤에야 T30 사전 점검을 붙이므로 잠시 들고만 있는다.
                entry["_raw_body"] = xml[cell["body_start"]:cell["body_end"]]
                cells.append(entry)

            # spacer는 fill_target에서 **빼는** 분류이므로 T30 사전 점검(대상
            # 셀에만 붙는다)보다 먼저 확정되어야 한다.
            _mark_spacers(cells, int(col_cnt) if col_cnt is not None else 0)
            for entry in cells:
                raw_body = entry.pop("_raw_body", None)
                if entry["classification"] == "fill_target" and raw_body is not None:
                    entry.update(_fill_preflight(
                        raw_body, script_profiles or {}, baseline_id))

            tables.append({
                "index": idx,
                "section": sname,
                "depth": tbl["depth"],
                "rowCnt": int(row_cnt) if row_cnt is not None else None,
                "colCnt": int(col_cnt) if col_cnt is not None else None,
                "pageBreak": page_break,
                "repeatHeader": repeat_header,
                "cells": cells,
            })
            idx += 1
    return tables


def _full_text(section_names, z, wanted):
    """--full-text로 **이름 붙인 셀/문단만** 정확한 텍스트를 반환.

    구조-전용 계약(profile은 본문 텍스트를 담지 않는다)의 **의도적** 탈출구다.
    그래서 opt-in이고, 셀/문단 단위다: 요청하지 않은 셀·문단은 한 글자도
    나오지 않고, 문서 본문 전체를 뽑는 경로는 여기에 없다.

    왜 필요한가(T34): `preedit replace`의 문자열 키는 런의 내부 공백까지 정확히
    같아야 한다. 양식이 인쇄해 둔 자리표(" 우(     -     )")는 30자
    text_preview로는 잘리고 anchors에도 없어서, 3라운드 클린룸의 두 티어가
    **모두** Contents/section0.xml을 손으로 읽었다 — 스킬이 금지한 접촉.
    보통은 주소 키(`--at-cell ROW,COL=…`)가 정답이고 문자열이 아예 필요 없다.
    문자열 키가 꼭 필요할 때(check_residue --fill-map의 키 등) 이 플래그가
    그 문자열을 준다.

    wanted: [(table_index|None, row, col), ...] (table_index None은 표 0),
        또는 [("para", at_para), ...].
    반환: 셀 요청에는 [{table, addr:{row,col}, text, truncated_preview,
        runs:[{index, text, charpr}]}], 문단 요청에는 [{at_para, para_idx,
        section, text, runs:[{index, text, charpr}]}]. 문단 ``at_para``가
        ``preedit``와 같은 0-based 문서 순서 주소다. ``para_idx``는
        이 결과 안에서만 유지하는 backward-compatible alias이며, profile의
        legacy ``para_idx``가 아니다.
    반환 순서는 요청 순서. 없는 표/셀은 ValueError.
    """
    tables = []                       # [(index, xml, table dict)]
    idx = 0
    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        for tbl in scan_tables(xml):
            tables.append((idx, xml, tbl))
            idx += 1
    paragraph_records = None
    out = []
    for request in wanted:
        if (isinstance(request, tuple) and len(request) == 2
                and request[0] == "para"):
            if paragraph_records is None:
                paragraph_records = []
                for sname in section_names:
                    xml = z.read(sname).decode("utf-8")
                    for _start, _end, p_xml in _iter_document_paragraphs_with_offsets(xml):
                        runs = paragraph_text_runs(p_xml)
                        paragraph_records.append({
                            "section": sname,
                            "text": "".join(r["text"] for r in runs),
                            "runs": runs,
                        })
            para_idx = request[1]
            if isinstance(para_idx, bool) or not isinstance(para_idx, int):
                raise ValueError(
                    f"--full-text: PARA address must be a non-negative integer: "
                    f"{para_idx!r}")
            if para_idx < 0 or para_idx >= len(paragraph_records):
                raise ValueError(
                    f"--full-text: PARA:{para_idx} out of range "
                    f"(document has {len(paragraph_records)} paragraphs)")
            record = paragraph_records[para_idx]
            out.append({
                "at_para": para_idx,
                # T49 consumers may still read this name; it aliases the
                # requested at_para and must not be confused with the
                # profile's historical para_idx.
                "para_idx": para_idx,
                "section": record["section"],
                "text": record["text"],
                "runs": [{"index": r["index"], "text": r["text"],
                           "charpr": r["charpr"]}
                          for r in record["runs"]],
            })
            continue

        table_index, row, col = request
        t = 0 if table_index is None else table_index
        match = next((x for x in tables if x[0] == t), None)
        if match is None:
            raise ValueError(
                f"--full-text: 표 index={t} 없음 — 문서 전체 표는 {idx}개")
        _i, xml, tbl = match
        cell = find_cell(tbl, row, col)
        if cell is None:
            known = sorted(c["addr"] for c in tbl["cells"] if c["addr"])
            raise ValueError(
                f"--full-text: 표 {t}에 cellAddr ({row},{col}) 없음 — 병합"
                f" 셀이 덮은 좌표이거나 오타. 실제 주소 {len(known)}개:"
                f" {known[:20]}")
        runs = cell_text_runs(xml[cell["body_start"]:cell["body_end"]])
        text = "".join(r["text"] for r in runs)
        out.append({
            "table": t,
            "addr": {"row": row, "col": col},
            "text": text,
            "truncated_preview": len(text) > 30,
            "runs": [{"index": r["index"], "text": r["text"],
                      "charpr": r["charpr"]} for r in runs],
        })
    return out


def _iter_document_paragraphs(xml):
    """Backward-compatible p_xml-only view of the shared depth-first walk."""
    for _start, _end, p_xml in _iter_document_paragraphs_with_offsets(xml):
        yield p_xml


def _own_paragraph_text(p_xml):
    """Return only the runs owned by this paragraph, excluding nested ``p``."""
    return "".join(run["text"] for run in paragraph_text_runs(p_xml))


def _resolve_at_para(legacy, depth_records):
    """Bind one legacy paragraph scan row to a depth-first address.

    The historical regex can stop at a nested paragraph's closing tag.  A
    start-only lookup would then assign a nested anchor to its outer table
    paragraph.  First require exact start *and* own-text identity; otherwise
    accept the unique descendant whose closing boundary and own text are both
    identical to the legacy match.  Any ambiguity remains unresolved rather
    than becoming a text-first guess.
    """
    start, end, legacy_text = (legacy.get("_start"), legacy.get("_end"),
                               legacy.get("text", ""))
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    def same_text(row):
        own = _own_paragraph_text(row["xml"])
        return own == legacy_text or own.strip() == legacy_text.strip()

    direct = [row for row in depth_records
              if row["start"] == start and row["end"] == end
              and same_text(row)]
    if len(direct) == 1:
        return direct[0]["at_para"]
    candidates = [row for row in depth_records
                  if row["start"] > start and row["end"] == end
                  and same_text(row)]
    if len(candidates) == 1:
        return candidates[0]["at_para"]
    return None


def _break_audit(header_xml):
    """paraPr 정의들의 hh:breakSetting 속성 카운트 + 전체 paraPr 개수."""
    counts = {
        "widowOrphan": 0,
        "keepWithNext": 0,
        "keepLines": 0,
        "pageBreakBefore": 0,
    }
    total_parapr = 0
    for m in re.finditer(r'<' + NS + r':paraPr\b([^>]*?)/?>', header_xml):
        pid = _attr(m.group(1), "id")
        if pid is None:
            continue
        total_parapr += 1
        tail = header_xml[m.end():m.end() + 600]
        bm = re.search(r'<' + NS + r':breakSetting\b([^/]*)/?>', tail)
        if not bm:
            continue
        attrs = bm.group(1)
        for key in counts:
            if _attr(attrs, key) == "1":
                counts[key] += 1
    return {
        "widowOrphan": counts["widowOrphan"],
        "keepWithNext": counts["keepWithNext"],
        "keepLines": counts["keepLines"],
        "pageBreakBefore": counts["pageBreakBefore"],
        "total_parapr": total_parapr,
    }


def _heading_parapr_ids(header_xml):
    """heading type != NONE 인 paraPr id 집합(개요/제목 스타일)."""
    ids = set()
    for m in re.finditer(r'<' + NS + r':paraPr\b([^>]*?)/?>', header_xml):
        pid = _attr(m.group(1), "id")
        if pid is None:
            continue
        tail = header_xml[m.end():m.end() + 600]
        hm = re.search(r'<' + NS + r':heading\b([^/>]*)/?>', tail)
        if hm:
            htype = _attr(hm.group(1), "type")
            if htype and htype != "NONE":
                ids.add(pid)
    return ids


CONSTRAINT_PT_RE = re.compile(r'(\d+)\s*(?:포인트|pt|PT)')
CONSTRAINT_SPACING_RE = re.compile(r'(\d+)\s*%')
CONSTRAINT_MAXPAGE_RE = re.compile(r'(\d+)\s*(?:쪽|페이지|장)\s*(?:이내|이하)')
CONSTRAINT_MINPAGE_RE = re.compile(r'(\d+)\s*(?:쪽|페이지|장)\s*이상')

PT_KEYWORDS = ("글자", "글씨", "폰트", "본문")
SPACING_KEYWORDS = ("줄", "간격")
SENTENCE_SPLIT_RE = re.compile(r'[.,。\n]')


def _sentences(text):
    return [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _parse_constraints(guide_texts):
    base_pt = line_spacing_pct = max_pages = min_pages = None
    for t in guide_texts:
        for sent in _sentences(t):
            if base_pt is None and any(kw in sent for kw in PT_KEYWORDS):
                m = CONSTRAINT_PT_RE.search(sent)
                if m:
                    base_pt = int(m.group(1))
            if line_spacing_pct is None and all(kw in sent for kw in SPACING_KEYWORDS):
                m = CONSTRAINT_SPACING_RE.search(sent)
                if m:
                    line_spacing_pct = int(m.group(1))
            if max_pages is None:
                m = CONSTRAINT_MAXPAGE_RE.search(sent)
                if m:
                    max_pages = int(m.group(1))
            if min_pages is None:
                m = CONSTRAINT_MINPAGE_RE.search(sent)
                if m:
                    min_pages = int(m.group(1))
    return {"base_pt": base_pt, "line_spacing_pct": line_spacing_pct,
            "max_pages": max_pages, "min_pages": min_pages}


def analyze(path, want_baseline=False, base_pt=10, line_spacing_pct=160,
            full_text=None):
    data = Path(path).read_bytes()
    form_hash = hashlib.sha256(data).hexdigest()

    z = zipfile.ZipFile(path)
    header_xml = z.read("Contents/header.xml").decode("utf-8")
    defs = _charpr_defs(header_xml)
    fontref_map = _fontfaces(header_xml)
    parapr_ls = _paraprops(header_xml)
    heading_ids = _heading_parapr_ids(header_xml)
    align_map = _align_map(header_xml)
    bold_map = _bold_map(header_xml)
    borderfill_shaded = _borderfill_shaded(header_xml)
    break_audit = _break_audit(header_xml)

    section_names = sorted(n for n in z.namelist()
                            if re.match(r"Contents/section\d+\.xml", n))

    section0_xml = z.read(section_names[0]).decode("utf-8") if section_names else ""
    page_metrics = _page_metrics(section0_xml, base_pt=base_pt, line_spacing_pct=line_spacing_pct)

    # T30 사전 점검의 기준선 — 문서 자신의 본문 charPr. table_map보다 먼저
    # 구해야 한다(fill_target 셀마다 이 id와 비교하므로).
    script_profiles = charpr_script.profiles_from_header(header_xml)
    script_baseline_id = charpr_script.body_baseline_id(
        _body_charpr_weights(section_names, z))
    baseline_profile = script_profiles.get(script_baseline_id)
    body_baseline_charpr = {
        "id": script_baseline_id,
        "height_pt": (baseline_profile or {}).get("height_pt"),
        "signature": (charpr_script.signature(baseline_profile)
                      if baseline_profile else None),
    }

    table_map = _table_map(section_names, z, defs, borderfill_shaded,
                           script_profiles=script_profiles,
                           baseline_id=script_baseline_id)

    anchors, anchor_records = [], []
    placeholders, guide_text, para_formats = [], [], []
    anchor_para_idx = set()
    table_count = 0
    global_para_idx = 0
    # ``global_para_idx`` below is deliberately legacy: it counts only the
    # paragraphs accepted by the historical regex scanner.  New scoped
    # replacement addresses come from the exact preedit depth-first walk,
    # bound by paragraph XML identity within its section.
    depth_records = {}
    next_at_para = 0
    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        rows = depth_records.setdefault(sname, [])
        for start, end, p_xml in _iter_document_paragraphs_with_offsets(xml):
            rows.append({"start": start, "end": end, "xml": p_xml,
                         "at_para": next_at_para})
            next_at_para += 1
    charpr_hist, parapr_hist = Counter(), Counter()
    # guide-only-color 산출용: guide 문단이 쓴 charPr id 집합(비-guide는 별도 집계).
    guide_charpr_ids, guide_parapr_ids = set(), set()
    nonguide_charpr_hist, nonguide_parapr_hist = Counter(), Counter()

    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        table_count += len(re.findall(r'<' + NS + r':tbl\b', xml))
        paras = _paragraphs(xml, defs)
        for p in paras:
            text = p["text"]
            para_pr = p["paraPr"]
            cids = p["charPrs"]
            parapr_hist[para_pr] += 1
            for cid in cids:
                charpr_hist[cid] += 1

            is_bracket_placeholder = bool(text.strip()) and \
                text.strip().startswith("[") and text.strip().endswith("]")
            for bm in BRACKET_RE.finditer(text):
                placeholders.append(f"[{bm.group(1)}]")

            colors = [defs.get(cid, {}).get("color") for cid in cids]
            colored = any(not _is_black_or_auto(c) for c in colors)

            is_anchor = _looks_like_anchor(text, para_pr, heading_ids)
            is_heading_pattern = bool(text.strip()) and (
                ROMAN_HEAD_RE.match(text.strip()) or NUM_HEAD_RE.match(text.strip())
                or para_pr in heading_ids)

            reason = _classify_guide(text, colored) if text.strip() else None
            if reason:
                instruction_kw = _has_instruction(text)
                answer_slot = _answer_slot_reason(text)
                excluded = (is_anchor or is_heading_pattern
                            or is_bracket_placeholder or bool(answer_slot))
                if reason == "colored" and instruction_kw:
                    confidence = "high"
                else:
                    confidence = "medium"
                entry = {
                    "text": text, "para_idx": global_para_idx,
                    "section": sname, "reason": reason,
                    "removal_confidence": confidence,
                    "excluded_from_removal": excluded,
                }
                # 표기 지점은 이유까지 노출한다. "삭제 후보에서 빠졌다"만으로는
                # 에이전트가 "여기에 표시해야 한다"를 알 수 없다 — A2 실측에서
                # 동의 표기 절차가 어느 문서에도 없어 모듈 소스를 읽어야 했다.
                if answer_slot:
                    entry["answer_slot"] = answer_slot
                    # A marking site needs an EDITABLE address, and legacy
                    # `para_idx` is not one — `preedit` and `--full-text PARA:N`
                    # both take the depth-first `at_para`. The bridge existed
                    # only on `anchor_records`, so it was available exactly when
                    # the paragraph happened to be an anchor: on this corpus the
                    # 수집ㆍ이용 consent question has it (39 -> 42) and its
                    # 제3자 twin does not, which is the same paraPr accident
                    # T110 removed from the removal verdict. Resolved the same
                    # way anchors do, and omitted rather than guessed when the
                    # binding is not provable.
                    at_para = _resolve_at_para(
                        p, depth_records.get(sname, []))
                    if at_para is not None:
                        entry["at_para"] = at_para
                guide_text.append(entry)
                guide_charpr_ids.update(cids)
                guide_parapr_ids.add(para_pr)
            else:
                for cid in cids:
                    nonguide_charpr_hist[cid] += 1
                nonguide_parapr_hist[para_pr] += 1

            if is_anchor:
                anchor_text = text.strip()
                anchors.append(anchor_text)
                record = {
                    "text": anchor_text,
                    "para_idx": global_para_idx,
                    "section": sname,
                }
                # Start identity is the only safe bridge between the legacy
                # regex result and preedit's global address.  If it cannot be
                # proven, omit the new field rather than guessing.
                at_para = _resolve_at_para(p, depth_records.get(sname, []))
                if at_para is not None:
                    record["at_para"] = at_para
                anchor_records.append(record)
                anchor_para_idx.add(global_para_idx)

            # para_formats: 앵커/제목-패턴/bracket-placeholder 문단만 기록
            # (기존에 이미 계산된 플래그 재사용 — 새 휴리스틱 도입 안 함).
            if text.strip() and (is_anchor or is_heading_pattern or is_bracket_placeholder):
                char_pt = sorted({
                    defs.get(cid, {}).get("height_pt") for cid in cids
                    if defs.get(cid, {}).get("height_pt") is not None
                })
                bold_flags = [bold_map[cid] for cid in cids if cid in bold_map]
                bold = all(bold_flags) if bold_flags else None
                ls = parapr_ls.get(para_pr)
                para_formats.append({
                    "text_head": text.strip()[:20],
                    "para_idx": global_para_idx,
                    "align": align_map.get(para_pr),
                    "line_spacing": (
                        {"type": ls["type"], "value": ls["value"]} if ls else None
                    ),
                    "char_pt": char_pt,
                    "bold": bold,
                })

            global_para_idx += 1

    # removal_targets: guide_text 중 anchor/heading-pattern/bracket-placeholder 제외.
    # (placeholder는 삭제가 아니라 치환 대상이므로 여기서도 제외한다.)
    removal_targets = [
        {"para_idx": g["para_idx"], "confidence": g["removal_confidence"]}
        for g in guide_text if not g["excluded_from_removal"]
    ]
    for g in guide_text:
        g.pop("excluded_from_removal", None)
    removal_policy = (
        "high confidence(색+지시어 키워드 동시 충족)만 조립 시 자동 삭제. "
        "medium confidence(둘 중 하나만 충족)는 에이전트가 확인 후 삭제할 것 — "
        "anchors/heading 패턴/bracket-placeholder는 애초에 제외됨. "
        "답 표기 슬롯을 품은 문단도 제외되며(`answer_slot` 사유 표기), "
        "삭제 대상이 아니라 표시할 대상이다."
    )

    # format_hints
    citation_example = None
    for g in guide_text:
        if _looks_like_citation(g["text"]):
            citation_example = g["text"]
            break
    has_eq_placeholder = any("수식" in a or "식" in a for a in placeholders) or \
        any("수식" in g["text"] for g in guide_text)

    constraints = _parse_constraints([g["text"] for g in guide_text])

    # blanks_before(Rule 1): 각 anchor 문단 앞의 pristine-form 빈 문단 개수.
    # tidy_hwpx --before가 앵커당 몇 개까지 남겨야(keep_n) 양식 원본 여백을
    # 보존하는지 판단하는 기준선 — fill_report의 자동 유도 tidy가 이 값을
    # 안 보고 전부 keep=1로 밀어버리면 양식 고유 여백(예: 표지-요약 분리)이
    # 사라진다.
    anchors_blanks_before = _blanks_before_map(section_names, z, set(anchors))

    profile = {
        "ok": True,
        "file": str(path),
        "form_hash": form_hash,
        "anchors": anchors,
        # Keep the historical text-only list for consumers that use it as a
        # keep-list, while exposing paragraph identity for residue attribution.
        # Records are emitted in the same section/document order as ``anchors``.
        "anchor_records": anchor_records,
        "anchors_blanks_before": anchors_blanks_before,
        "placeholders": sorted(set(placeholders)),
        "guide_text": guide_text,
        "format_hints": {
            "citation_example": citation_example,
            "table_count": table_count,
            "has_eq_placeholder": has_eq_placeholder,
        },
        "constraints": constraints,
        "removal_targets": removal_targets,
        "removal_policy": removal_policy,
        "page_metrics": page_metrics,
        "body_baseline_charpr": body_baseline_charpr,
        "table_map": table_map,
        "script_anomaly_targets": [
            {"table": t["index"], "addr": c["addr"], "charpr": c["charpr"],
             "charpr_suggested": c["charpr_suggested"],
             "differing": c.get("script_differing", [])}
            for t in table_map for c in t["cells"]
            if c.get("script_anomaly")],
        # 구조용 빈 칸은 채우기 대상이 **아니다** — 세지 말라고 따로 세어 준다.
        "spacer_cells": [
            {"table": t["index"], "addr": c["addr"],
             "pattern": c.get("spacer_pattern")}
            for t in table_map for c in t["cells"]
            if c.get("classification") == "spacer"],
        "fill_target_count": sum(
            1 for t in table_map for c in t["cells"]
            if c.get("classification") == "fill_target"),
        "break_audit": break_audit,
    }
    if full_text:
        # opt-in 이므로 요청이 없으면 키 자체가 없다 — 구조-전용 계약 유지.
        profile["full_text"] = _full_text(section_names, z, full_text)

    baseline = None
    if want_baseline:
        # 안내문(guide) 문단이 쓰는 charPr/paraPr는 baseline(정상 서식) 후보에서 제외.
        # 안내문은 조립 시 삭제되므로, 안내문 전용 색은 출력에 나타나면 안 된다.
        fonts = set()
        sizes_pt = set()
        colors_seen = set()
        line_spacings = set()
        guide_only_colors = set()
        for cid, cnt in nonguide_charpr_hist.items():
            d = defs.get(cid, {})
            face = font_face(defs, fontref_map, cid, "hangul")
            if face:
                fonts.add(face)
            if d.get("height_pt") is not None:
                sizes_pt.add(d["height_pt"])
            if d.get("color"):
                colors_seen.add(d["color"].upper())
        for pid, cnt in nonguide_parapr_hist.items():
            ls = parapr_ls.get(pid)
            if ls and ls.get("value") is not None:
                line_spacings.add((ls["type"], ls["value"]))
        for cid in guide_charpr_ids:
            d = defs.get(cid, {})
            c = d.get("color")
            if c and c.upper() not in colors_seen:
                guide_only_colors.add(c.upper())
        baseline = {
            "ok": True,
            "file": str(path),
            "form_hash": form_hash,
            "fonts": sorted(fonts),
            "sizes_pt": sorted(sizes_pt),
            "colors": sorted(colors_seen),
            "guide_only_colors": sorted(guide_only_colors),
            "line_spacings": sorted(line_spacings, key=lambda x: (x[0] or "", x[1])),
            "charpr_hist": dict(sorted(charpr_hist.items(), key=lambda kv: int(kv[0]))),
            "parapr_hist": dict(sorted(parapr_hist.items(), key=lambda kv: int(kv[0]))),
            "para_formats": para_formats,
        }

    return profile, baseline


# 습관에서 오는 미지원 플래그 → 무엇을 쓰라는 안내로 바꾼다.
# 출처가 리포 안에 있다: engine/scripts/probe.py 만 기본 출력이 단일행
# 압축이라 --pretty 를 갖는다(SKILL.md 인라인 주입 계약). 나머지 스크립트는
# 전부 indent=2 가 기본이므로 --pretty/--indent 는 이미 가진 동작을 요청하는
# 셈이고, --json 은 유일 출력 형식을 다시 고르는 셈이다. 세 클린룸 라운드 중
# 한 에이전트가 --pretty 를 습관으로 시도했다(T35 계열: 이름은 같은데 의미가
# 스크립트마다 다른 것).
_HABIT_FLAGS = {
    "--pretty": "출력은 항상 indent=2 JSON이다 — --pretty 는 없다",
    "--indent": "출력은 항상 indent=2 JSON이다 — --indent 는 없다",
    "--json": "출력 형식은 JSON뿐이다 — --json 은 없다",
}


class _HabitAwareParser(argparse.ArgumentParser):
    """미지원 플래그가 습관 목록에 있으면 대안을 함께 알려준다."""

    def error(self, message):
        for flag, hint in _HABIT_FLAGS.items():
            if flag in message:
                message = f"{message} ({hint})"
                break
        super().error(message)


def main():
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = _HabitAwareParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter,
                                  epilog="출력은 항상 indent=2 JSON이다"
                                         "(--pretty/--indent/--json 없음). "
                                         "단일행 압축이 필요하면 probe.py 만 "
                                         "그 계약을 갖는다.")
    ap.add_argument("form", help=".hwpx 양식 경로")
    ap.add_argument("--out", help="form_profile.json 출력 경로(생략 시 stdout)")
    ap.add_argument("--baseline", help="form_baseline.json 출력 경로(지정 시 생성)")
    ap.add_argument("--base-pt", type=int, default=10,
                     help="page_metrics 계산에 쓸 기준 본문 글자크기(pt, 기본 10)")
    ap.add_argument("--line-spacing", type=int, default=160,
                     help="page_metrics 계산에 쓸 줄간격(%%, 기본 160)")
    ap.add_argument("--full-text", action="append", default=[],
                    metavar="[TABLE:]ROW,COL|PARA:N",
                    help="이름 붙인 셀([TABLE:]ROW,COL) 또는 문단(PARA:N)만"
                         " 정확한 텍스트/런을 emit (PARA는 preedit at_para;"
                         " 반복 가능, opt-in;"
                         " 요청하지 않은 본문 전체는 뽑지 않음)")
    args = ap.parse_args()

    if not Path(args.form).exists():
        die(f"파일 없음: {args.form}")

    wanted = []
    for spec in args.full_text:
        para = re.fullmatch(r'\s*PARA\s*:\s*(\d+)\s*', spec,
                            flags=re.IGNORECASE)
        if para:
            wanted.append(("para", int(para.group(1))))
            continue
        m = re.fullmatch(r'\s*(?:(\d+)\s*:\s*)?(\d+)\s*,\s*(\d+)\s*', spec)
        if not m:
            die(f"--full-text 형식은 ROW,COL, TABLE:ROW,COL 또는 PARA:N: "
                f"{spec!r}")
        wanted.append((None if m.group(1) is None else int(m.group(1)),
                       int(m.group(2)), int(m.group(3))))

    try:
        profile, baseline = analyze(
            args.form, want_baseline=bool(args.baseline),
            base_pt=args.base_pt, line_spacing_pct=args.line_spacing,
            full_text=wanted)
    except KeyError as e:
        die(f"hwpx 구조 이상(필수 엔트리 없음): {e}")
    except zipfile.BadZipFile:
        die(f"유효한 zip(.hwpx)이 아님: {args.form}")
    except ValueError as e:
        die(str(e))

    text = json.dumps(profile, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: anchors={len(profile['anchors'])} "
              f"guide_text={len(profile['guide_text'])} "
              f"constraints={profile['constraints']} "
              f"body_baseline_charpr={profile['body_baseline_charpr']['id']} "
              f"script_anomaly_targets="
              f"{len(profile['script_anomaly_targets'])} "
              f"fill_target={profile['fill_target_count']} "
              f"spacer={len(profile['spacer_cells'])}")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))

    if baseline is not None:
        btext = json.dumps(baseline, ensure_ascii=False, indent=2)
        Path(args.baseline).write_text(btext, encoding="utf-8")
        print(f"wrote {args.baseline}: fonts={baseline['fonts']} "
              f"sizes_pt={baseline['sizes_pt']}")

    sys.exit(0)


if __name__ == "__main__":
    main()
