#!/usr/bin/env python3
"""form_inspect.py — .hwpx 양식(form)을 오프라인(비-COM)으로 프로파일링.

한글(Hancom) 없이 .hwpx(zip)를 풀어 header.xml(charPr/paraPr 정의)과
section*.xml(문단/런) 을 대조해, 조립(build_report.py) 전에 알아야 할 양식의
구조 — 앵커(제목/섹션 헤더), 안내문(작성 지침·색깔 강조·예시), 서식 제약
(글자크기·줄간격·분량) — 를 결정론적으로 뽑아낸다.

    python form_inspect.py FORM.hwpx [--out form_profile.json] [--baseline form_baseline.json]
        [--base-pt 10] [--line-spacing 160]

--baseline: form_profile.json에 더해 폰트/크기/색/줄간격/사용빈도 분포를
            form_baseline.json으로 추가 기록한다(style_diff.py의 기준선).
--base-pt/--line-spacing: page_metrics의 lines_per_page/chars_per_line 계산에
            쓰는 가정값(각각 기본 10pt/160%).

v2 추가 섹션(form_profile.json):
  page_metrics — section0.xml의 hp:pagePr/margin에서 페이지 여백/가용영역과
                 lines_per_page/chars_per_line 파생값.
  table_map    — 모든 hp:tbl의 셀 단위 지도(addr/size/borderFill/음영/분류).
  break_audit  — header.xml paraPr들의 hh:breakSetting 플래그 집계.

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
from hwpx_tables import scan_tables  # noqa: E402
# T30 사전 점검 — script/scale/offset 어휘는 visual_verify(사후 검출)와 공유하고,
# '어느 런을 채우는가'는 preedit(실제 채우는 쪽)에서 그대로 가져온다.
# 두 도구가 어긋날 수 있으면 사전 점검은 없는 것보다 나쁘다.
import charpr_script  # noqa: E402
from preedit import fill_target_run_charpr  # noqa: E402

NS = r'[A-Za-z0-9]+'  # 임의 네임스페이스 prefix(hp/hh 고정 가정 X)
Q = r'["\']'  # 큰따옴표/작은따옴표 모두 허용

# 태그를 통째로 잡은 뒤 속성은 태그 문자열 안에서 별도 탐색 → 속성 순서 무관.
RUN_TAG_RE = re.compile(r'<' + NS + r':run\b([^>]*)>(.*?)</' + NS + r':run>', re.S)
P_TAG_RE = re.compile(r'<' + NS + r':p\b([^>]*)>(.*?)</' + NS + r':p>', re.S)
T_RE = re.compile(r'<' + NS + r':t\b[^>]*>(.*?)</' + NS + r':t>', re.S)
BRACKET_RE = re.compile(r'\[([^\[\]]{1,40})\]')
ROMAN_HEAD_RE = re.compile(r'^\s*([IVXⅠ-Ⅻ]+)[.\)]\s*\S')
NUM_HEAD_RE = re.compile(r'^\s*\d+\.\s*\S')


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
            cids.append(cid)
            text_parts.append(re.sub(r"<[^>]+>", "", "".join(T_RE.findall(run_body))))
        text = "".join(text_parts)
        out.append({"text": text, "paraPr": para_pr, "charPrs": cids})
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
                    text = "".join(re.sub(r"<[^>]+>", "", t) for t in T_RE.findall(p_xml))
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


def _table_map(section_names, z, defs, borderfill_shaded,
               script_profiles=None, baseline_id=None):
    """모든 section의 모든 hp:tbl -> table_map 엔트리 리스트.

    cell 분류(guide/fill_target/static)는 _classify_guide/_looks_like_anchor와
    동일 휴리스틱을 재사용한다(새 규칙 도입 안 함).

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
                    "classification": classification,
                }
                if classification == "fill_target":
                    # 원본 몸통(중첩 표 제거 전)을 넘긴다 — preedit의 문단 색인과
                    # 같아야 하므로 _own_cell_body 결과를 쓰면 안 된다.
                    raw_body = xml[cell["body_start"]:cell["body_end"]]
                    entry.update(_fill_preflight(
                        raw_body, script_profiles or {}, baseline_id))
                cells.append(entry)

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


def analyze(path, want_baseline=False, base_pt=10, line_spacing_pct=160):
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

    anchors, placeholders, guide_text, para_formats = [], [], [], []
    anchor_para_idx = set()
    table_count = 0
    global_para_idx = 0
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
                excluded = is_anchor or is_heading_pattern or is_bracket_placeholder
                if reason == "colored" and instruction_kw:
                    confidence = "high"
                else:
                    confidence = "medium"
                guide_text.append({
                    "text": text, "para_idx": global_para_idx,
                    "section": sname, "reason": reason,
                    "removal_confidence": confidence,
                    "excluded_from_removal": excluded,
                })
                guide_charpr_ids.update(cids)
                guide_parapr_ids.add(para_pr)
            else:
                for cid in cids:
                    nonguide_charpr_hist[cid] += 1
                nonguide_parapr_hist[para_pr] += 1

            if is_anchor:
                anchors.append(text.strip())
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
        "anchors/heading 패턴/bracket-placeholder는 애초에 제외됨."
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
        "break_audit": break_audit,
    }

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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("form", help=".hwpx 양식 경로")
    ap.add_argument("--out", help="form_profile.json 출력 경로(생략 시 stdout)")
    ap.add_argument("--baseline", help="form_baseline.json 출력 경로(지정 시 생성)")
    ap.add_argument("--base-pt", type=int, default=10,
                     help="page_metrics 계산에 쓸 기준 본문 글자크기(pt, 기본 10)")
    ap.add_argument("--line-spacing", type=int, default=160,
                     help="page_metrics 계산에 쓸 줄간격(%%, 기본 160)")
    args = ap.parse_args()

    if not Path(args.form).exists():
        die(f"파일 없음: {args.form}")

    try:
        profile, baseline = analyze(
            args.form, want_baseline=bool(args.baseline),
            base_pt=args.base_pt, line_spacing_pct=args.line_spacing)
    except KeyError as e:
        die(f"hwpx 구조 이상(필수 엔트리 없음): {e}")
    except zipfile.BadZipFile:
        die(f"유효한 zip(.hwpx)이 아님: {args.form}")

    text = json.dumps(profile, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: anchors={len(profile['anchors'])} "
              f"guide_text={len(profile['guide_text'])} "
              f"constraints={profile['constraints']} "
              f"body_baseline_charpr={profile['body_baseline_charpr']['id']} "
              f"script_anomaly_targets="
              f"{len(profile['script_anomaly_targets'])}")
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
