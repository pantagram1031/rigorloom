#!/usr/bin/env python3
"""tidy_hwpx.py — 오프라인(비-COM) .hwpx 빈 문단 정리 + 문단 서식 복원.

COM 기반 collapse_empty_paragraphs는 폐기(T7: 제목 charPr 오염·문단 병합 위험).
대신 zip 안 section*.xml을 문자열 단위로 직접 편집해, 지정한 앵커 문단 앞/뒤의
빈 문단(런 텍스트도 표·그림·컨트롤도 없는 문단)만 결정론적으로 지운다.

    python tidy_hwpx.py FILE.hwpx --before "앵커1" --before "앵커2" ...
                        [--after "앵커"] [--keep 1] [--out OUT.hwpx]

--before ANCHOR: ANCHOR 텍스트를 담은 문단을 찾아, 그 문단 바로 앞에서부터
    역방향으로 연속된 빈 문단을 --keep(기본 1)개만 남기고 지운다.
--after ANCHOR: 대칭 동작(앵커 문단 뒤에서 정방향).
같은 CLI 호출에 --before/--after를 여러 개 섞어 줄 수 있다(각각 독립 처리).

안전장치: 앵커 텍스트가 섹션 전체에서 0번 또는 2번 이상 발견되면(모호함)
아무것도 쓰지 않고 exit 1. 앵커 문단 자신은 절대 건드리지 않는다. 문단이
표 셀(hp:tbl) 안에 중첩돼 있으면(=앵커와 같은 부모가 아니면) 건드리지 않는다
— 표/그림 등 구조 손상을 원천 차단.

exit 0: 성공(카운트 JSON). exit 1: 모호하거나 앵커 없음(안전 거부, 원본 그대로).
exit 2: 사용법/파일 오류.

--restore-formats form_baseline.json: com_backend.op_set_line_spacing(전체 문서
    SelectAll + ParagraphShape 적용)이 양식 소유 제목/라벨 문단(180~200%)까지
    160%로 뭉개는 회귀를 교정한다. 조사 결과(단발성, 재현 안 함 — 회귀 시
    재확인 필요): HWP COM은 저장 시 paraPr 테이블 전체를 재구성한다 — 같은
    id가 form과 out에서 전혀 다른 (align, lineSpacing) 조합을 가리키므로 id
    자체는 안정적 식별자가 아니다(참조 재대입 + 정의 재구성이 동시에 일어남).
    그래서 이 함수는 style_diff.check_para_formats와 동일하게 text_head로
    출력 문단을 찾은 뒤, 그 문단이 "현재" 가리키는 paraPr def를 복제해
    lineSpacing(및 align)만 baseline 값으로 패치하고 새 id로 append,
    그 문단의 paraPrIDRef만 새 id로 재대입한다. 동일 (원본 def id, 목표
    lineSpacing, 목표 align) 조합은 clone을 재사용해 중복 append하지 않는다.
    매칭된 문단의 paraPrIDRef 속성과 새로 append된 paraPr def 외에는
    아무것도 건드리지 않는다.

--keep-with-next PREFIX (반복 가능): 텍스트(런 이어붙임, whitespace 정규화)가
    PREFIX로 시작하는 모든 top-level 문단에 keepWithNext="1"인 paraPr을
    적용한다(표 캡션이 페이지 하단에 고아로 남고 표 본문이 다음 페이지로
    밀리는 문제의 근본 수정 — 캡션+표를 항상 같은 페이지에 묶는다). 매칭된
    문단이 "현재" 가리키는 paraPr def를 복제해 hh:breakSetting의
    keepWithNext만 "1"로 패치하고 새 id로 append, 그 문단의 paraPrIDRef만
    새 id로 재대입한다(restore_para_formats와 동일 clone/repoint 패턴).
    같은 원본 def id는 clone을 재사용(중복 append 없음). --before/--after와
    달리 앵커 유일성을 강제하지 않는다 — 캡션은 문서에 여러 번 반복되는 게
    정상이라 매치 0건이면 die(캡션 프리픽스가 오타일 가능성), 1건 이상이면
    전부 패치한다(모호함 거부 없음).

--typeset-defaults [--profile form_profile.json] [--caption-prefixes "표 ,[그림"]:
    모든 top-level 본문 문단(표 셀 안에 중첩된 문단 제외 — 기존 구조-보호
    관례와 동일)에 widowOrphan="1"을 적용한다. 추가로, 문단 텍스트가
    --profile의 anchors(제목) 중 하나와 일치/그 텍스트로 시작하거나
    --caption-prefixes(기본 "표 ", "[그림") 중 하나로 시작하면 같은 문단에
    keepWithNext="1"도 함께 적용한다. clone/repoint는 restore_para_formats/
    apply_keep_with_next와 동일 패턴이되, widowOrphan과 keepWithNext가 같은
    hh:breakSetting 태그에 있으므로 문단당 목표 조합을 한 번에 계산해
    (원본 def id, 목표 keepWithNext) 단위로만 clone을 캐시한다(동일 def를
    가리키는 문단이 여럿이면 clone 재사용). 이미 목표 값과 일치하는 def는
    건드리지 않는다 — 두 번 실행해도 byte-identical(idempotent). --dry-run은
    파일을 쓰지 않고 계획된 repoint 목록(문단 인덱스/텍스트 미리보기/적용될
    속성)만 출력한다.

    다른 플래그와 조합 가능. 실행 순서(고정): --before/--after(빈 문단 정리)
    → --restore-formats(줄간격/정렬 복원) → --keep-with-next(캡션 고아 방지)
    → --typeset-defaults(위 세 패스가 만든 최종 문단 구조 위에서 widowOrphan
    전역 적용 + keepWithNext 보강). --typeset-defaults를 맨 뒤에 두는 이유:
    (1) 앞선 패스가 지우거나 재배치한 문단에 영향받지 않도록 최종 구조를
    봐야 하고, (2) --keep-with-next가 이미 세팅한 keepWithNext="1"을 이 패스가
    되돌리지 않고 보존해야 하기 때문(현재 값이 "1"이면 유지, 강등하지 않음).
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

NS = r'[A-Za-z0-9]+'
P_TAG_RE = re.compile(r'<(' + NS + r'):p\b[^>]*>.*?</\1:p>', re.S)
P_OPEN_RE = re.compile(r'<(' + NS + r'):p\b([^>]*)>', re.S)
T_RE = re.compile(r'<' + NS + r':t\b[^>]*>(.*?)</' + NS + r':t>', re.S)
TAG_RE = re.compile(r'<(/?)(' + NS + r'):([A-Za-z0-9]+)\b[^>]*?(/?)>', re.S)
PARAPR_OPEN_RE = re.compile(r'<' + NS + r':paraPr\b[^>]*?\bid\s*=\s*"(\d+)"[^>]*>')
PARAPROPERTIES_RE = re.compile(r'<' + NS + r':paraProperties\b([^>]*)>')


def die(msg, code=1):
    line = json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.exit(code)


def _para_text(p_xml):
    """문단 XML 조각(<hp:p>...</hp:p>) 안 모든 hp:t 텍스트를 이어붙임."""
    return "".join(re.sub(r"<[^>]+>", "", t) for t in T_RE.findall(p_xml))


OBJECT_TAG_RE = re.compile(
    r'<' + NS + r':(tbl|pic|container|ole|line|rect|ellipse|'
    r'arc|polygon|curve|connectLine|equation)\b')


def _is_empty_para(p_xml):
    """런 텍스트가 없고 표(tbl)/그림(pic)/컨트롤(ctrl) 등 내용물이 없는 문단인지."""
    text = _para_text(p_xml)
    if text.strip():
        return False
    # 표/그림/도형/개체 컨트롤이 하나라도 있으면 '빈 문단'이 아니다(구조 보존).
    if OBJECT_TAG_RE.search(p_xml):
        return False
    return True


def _contains_object(p_xml):
    """문단이 표/그림/도형 등 객체 컨트롤을 담고 있는지(Rule 2: object-anchor
    keepWithNext 판정용) — _is_empty_para와 동일 태그 집합 재사용."""
    return bool(OBJECT_TAG_RE.search(p_xml))


def _find_paragraphs(xml):
    """xml에서 최상위(표 셀 등에 중첩되지 않은) <hp:p> 조각들의 (start, end, text) 목록.

    전체 태그 스트림을 스택으로 스캔한다(well-formed XML 가정: close 태그는 항상
    스택 맨 위 open과 짝) — <hp:p>는 표 셀(subList) 안에도 나타날 수 있고, 그 표
    자신이 상위 <hp:p> 안에 인라인으로 들어있을 수도 있다(문단이 표를 담고, 표
    셀이 다시 문단을 담는 구조). 그래서 단순 '첫 </p> 찾기'로는 안 되고, 스택으로
    각 hp:p의 진짜 대응 close를 찾는다. 최상위 판정: pop 시점에 스택에 다른
    hp:p가 안 남아있으면(바깥에 p가 없으면) top-level.
    """
    paras = []
    stack = []  # [(prefix, local, start_pos)]
    pos = 0
    length = len(xml)
    while pos < length:
        m = TAG_RE.search(xml, pos)
        if not m:
            break
        is_close, prefix, local, selfclose = m.groups()
        if selfclose:
            pos = m.end()
            continue
        if not is_close:
            stack.append((prefix, local, m.start()))
        elif stack:
            opened_prefix, opened_local, open_start = stack.pop()
            if opened_local == "p":
                is_top = not any(s[1] == "p" for s in stack)
                if is_top:
                    end = m.end()
                    p_xml = xml[open_start:end]
                    paras.append((open_start, end, p_xml))
        pos = m.end()
    return paras


def _locate_anchor(paras, anchor):
    """anchor 텍스트를 담은 top-level 문단의 인덱스 목록(paras 기준)."""
    hits = []
    for i, (_s, _e, p_xml) in enumerate(paras):
        if anchor in _para_text(p_xml):
            hits.append(i)
    return hits


def _tidy_direction(xml, anchor, keep, forward):
    """anchor 앞(forward=False)/뒤(forward=True)의 연속 빈 문단을 keep개만 남기고 삭제.

    반환: (new_xml, removed_count) 또는 die()로 종료(모호/없음).
    """
    paras = _find_paragraphs(xml)
    hits = _locate_anchor(paras, anchor)
    if len(hits) == 0:
        die(f"앵커를 찾지 못함: {anchor!r}")
    if len(hits) > 1:
        die(f"앵커가 모호함(문단 {len(hits)}개에서 발견): {anchor!r}")
    idx = hits[0]

    if forward:
        run = []
        j = idx + 1
        while j < len(paras) and _is_empty_para(paras[j][2]):
            run.append(j)
            j += 1
    else:
        run = []
        j = idx - 1
        while j >= 0 and _is_empty_para(paras[j][2]):
            run.append(j)
            j -= 1
        run.reverse()

    to_remove = run[:-keep] if keep > 0 else run
    if keep <= 0:
        to_remove = run
    if not to_remove:
        return xml, 0

    # 삭제 대상 구간을 문자열에서 뒤에서부터 잘라내 인덱스 shift를 피한다.
    spans = sorted((paras[i][0], paras[i][1]) for i in to_remove)
    new_xml = xml
    for start, end in reversed(spans):
        new_xml = new_xml[:start] + new_xml[end:]
    return new_xml, len(to_remove)


def tidy_section_xml(xml, before_anchors, after_anchors, keep, keep_map=None):
    """keep_map(선택, {anchor: keep_n})이 주어지면 그 anchor는 keep 대신
    keep_map[anchor]를 쓴다(Rule 1: form-native blanks_before 보존) — 없는
    anchor는 기본 keep 그대로(하위호환)."""
    keep_map = keep_map or {}
    removed = {}
    for anchor in before_anchors:
        n_keep = keep_map.get(anchor, keep)
        xml, n = _tidy_direction(xml, anchor, n_keep, forward=False)
        removed[anchor] = removed.get(anchor, 0) + n
    for anchor in after_anchors:
        n_keep = keep_map.get(anchor, keep)
        xml, n = _tidy_direction(xml, anchor, n_keep, forward=True)
        removed[anchor] = removed.get(anchor, 0) + n
    return xml, removed


def tidy_hwpx(path, before_anchors, after_anchors, keep=1, out_path=None, keep_map=None):
    """keep_map(선택, {anchor: keep_n}): anchor별로 keep 개수를 오버라이드한다
    (Rule 1 — form_inspect.py의 anchors_blanks_before를 그대로 넘기면 앵커별
    양식 원본 여백 개수만큼 보존). 없는 anchor 또는 keep_map 자체가 None이면
    기존처럼 전체에 단일 keep 값을 적용(하위호환)."""
    path = Path(path)
    out_path = Path(out_path) if out_path else path
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        section_names = sorted(n for n in names
                                if re.match(r"Contents/section\d+\.xml", n))
        contents = {n: zin.read(n) for n in names}
        infos = {n: zin.getinfo(n) for n in names}

    total_removed = {}
    changed_sections = {}
    remaining_before = list(before_anchors)
    remaining_after = list(after_anchors)

    for sname in section_names:
        xml = contents[sname].decode("utf-8")
        # 이 섹션에 있는 앵커만 여기서 처리(섹션 여러 개일 수 있으므로 앵커별로
        # 정확히 한 섹션에서만 매치돼야 전체적으로 모호하지 않음).
        b_here = [a for a in remaining_before if _locate_anchor(_find_paragraphs(xml), a)]
        a_here = [a for a in remaining_after if _locate_anchor(_find_paragraphs(xml), a)]
        if not b_here and not a_here:
            continue
        new_xml, removed = tidy_section_xml(xml, b_here, a_here, keep, keep_map=keep_map)
        if new_xml != xml:
            changed_sections[sname] = new_xml.encode("utf-8")
        for a in b_here:
            total_removed[a] = total_removed.get(a, 0) + removed.get(a, 0)
            remaining_before.remove(a)
        for a in a_here:
            total_removed[a] = total_removed.get(a, 0) + removed.get(a, 0)
            remaining_after.remove(a)

    if remaining_before or remaining_after:
        missing = remaining_before + remaining_after
        die(f"앵커를 찾지 못함: {missing}")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".hwpx", dir=str(path.parent))
    import os
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(path) as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = changed_sections.get(item.filename, contents[item.filename])
                zout.writestr(item, data)
        shutil.move(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {"ok": True, "removed": total_removed}


# ---------------------------------------------------------------------------
# --restore-formats: form-owned heading/label paragraph line_spacing(+align)
# 복원 — set_line_spacing 전역 적용이 뭉갠 180~200% 등을 baseline 값으로 되돌림.
# ---------------------------------------------------------------------------

def _find_top_level_paragraphs_with_prattrs(xml):
    """_find_paragraphs()와 동일한 top-level 판정이지만, 각 문단의 여는 태그
    속성 문자열(paraPrIDRef 치환 대상 판별/치환용)도 함께 반환.

    반환: [(p_start, p_end, p_xml, open_tag_end, pr_attrs_str), ...]
    pr_attrs_str은 <hp:p 와 > 사이의 속성 텍스트(paraPrIDRef=".." 포함).
    """
    paras = _find_paragraphs(xml)
    out = []
    for start, end, p_xml in paras:
        om = P_OPEN_RE.match(p_xml)
        if not om:
            continue
        out.append((start, end, p_xml, start + om.end(), om.group(2)))
    return out


def _attr_value(attrs, name):
    m = re.search(name + r'\s*=\s*"([^"]*)"', attrs)
    return m.group(1) if m else None


def _find_para_format_match_xml(paras_with_attrs, text_head):
    """style_diff._find_para_format_match와 동일 매칭(첫 top-level 문단,
    strip 후 text_head로 시작)을 raw XML 조각 목록에 대해 수행."""
    for entry in paras_with_attrs:
        _s, _e, p_xml, _oe, _attrs = entry
        if _para_text(p_xml).strip().startswith(text_head):
            return entry
    return None


def _parapr_defs_by_id(header_xml):
    """paraPr id -> (block_start, block_end_after_close_tag, block_xml).

    block_end는 </.../:paraPr> 닫는 태그까지 포함한 끝 오프셋(자기 닫힘 없음
    — 실측 결과 이 스킬이 다루는 hwpx는 항상 open+children+close 형태).
    """
    out = {}
    for m in PARAPR_OPEN_RE.finditer(header_xml):
        pid = m.group(1)
        close_m = re.search(r'</' + NS + r':paraPr>', header_xml[m.end():])
        if close_m is None:
            continue
        end = m.end() + close_m.end()
        out[pid] = (m.start(), end, header_xml[m.start():end])
    return out


def _set_attr(tag, name, value):
    """<tag ... name="x" .../> 안의 name 속성 값을 value로 치환하고, 속성이
    아예 없으면 태그의 '/>' 앞에 새로 삽입한다. 큰따옴표/작은따옴표 값 모두
    인식(패치는 항상 원래 인용부호 스타일을 보존)."""
    m = re.search(r'\b' + name + r'\s*=\s*(["\'])[^"\']*\1', tag)
    if m:
        quote = m.group(1)
        return tag[:m.start()] + f'{name}={quote}{value}{quote}' + tag[m.end():]
    # 속성 자체가 없음 — self-closing '/>' 직전에 삽입.
    insert_at = tag.rfind("/>")
    if insert_at == -1:
        insert_at = len(tag)
    return tag[:insert_at] + f' {name}="{value}"' + tag[insert_at:]


def _patch_parapr_block(block_xml, new_id, line_spacing=None, align=None,
                         keep_with_next=None, widow_orphan=None):
    """paraPr def 블록 하나를 복제 패치: id 치환 + lineSpacing(2곳: case/default)
    값 치환 + align(1곳) 치환 + breakSetting keepWithNext/widowOrphan(같은 태그,
    최대 2개 속성) 치환.
    각 인자가 None이면 해당 필드는 원본 그대로 둔다(baseline/목표에 값이
    없을 때 굳이 건드리지 않기 위함).

    keepWithNext/widowOrphan은 _set_attr로 처리 — breakSetting 태그에 해당
    속성이 없으면 새로 삽입하고(기존 코드는 속성이 이미 있을 때만 REPLACE
    했으므로, 없으면 아무 일도 안 하고 조용히 "패치됨"으로 잘못 보고했다),
    breakSetting 요소 자체가 블록에 없으면(태그가 아예 없는 paraPr def) 새
    <hh:breakSetting .../> 요소를 만들어 align 요소 뒤(없으면 heading 뒤,
    그마저 없으면 여는 태그 바로 뒤)에 삽입한다 — 형제 요소와 같은 네임스페이스
    프리픽스(NS로 감지)를 그대로 따른다."""
    block = re.sub(r'(\bid\s*=\s*)(["\'])(\d+)\2',
                    lambda m: m.group(1) + m.group(2) + str(new_id) + m.group(2),
                    block_xml, count=1)
    if line_spacing is not None:
        ls_type, ls_value = line_spacing
        def _repl_ls(m):
            tag = m.group(0)
            tag = re.sub(r'(\btype\s*=\s*")[^"]*(")', r'\g<1>' + ls_type + r'\2', tag)
            tag = re.sub(r'(\bvalue\s*=\s*")[^"]*(")', r'\g<1>' + str(ls_value) + r'\2', tag)
            return tag
        block = re.sub(r'<' + NS + r':lineSpacing\b[^/>]*/>', _repl_ls, block)
    if align is not None:
        def _repl_align(m):
            tag = m.group(0)
            return re.sub(r'(\bhorizontal\s*=\s*")[^"]*(")', r'\g<1>' + align + r'\2', tag)
        block = re.sub(r'<' + NS + r':align\b[^/>]*/>', _repl_align, block, count=1)
    if keep_with_next is not None or widow_orphan is not None:
        break_m = re.search(r'<(' + NS + r'):breakSetting\b[^/>]*/>', block)
        if break_m:
            def _repl_break(m):
                tag = m.group(0)
                if keep_with_next is not None:
                    tag = _set_attr(tag, "keepWithNext", keep_with_next)
                if widow_orphan is not None:
                    tag = _set_attr(tag, "widowOrphan", widow_orphan)
                return tag
            block = re.sub(r'<' + NS + r':breakSetting\b[^/>]*/>', _repl_break, block, count=1)
        else:
            # breakSetting 요소 자체가 없음 — 새로 만들어 삽입한다. 형제
            # 요소(align/heading)의 네임스페이스 프리픽스를 그대로 사용.
            prefix_m = (re.search(r'<(' + NS + r'):align\b', block)
                        or re.search(r'<(' + NS + r'):heading\b', block)
                        or re.search(r'<(' + NS + r'):paraPr\b', block))
            prefix = prefix_m.group(1) if prefix_m else "hh"
            attrs = []
            if keep_with_next is not None:
                attrs.append(f'keepWithNext="{keep_with_next}"')
            if widow_orphan is not None:
                attrs.append(f'widowOrphan="{widow_orphan}"')
            new_tag = f'<{prefix}:breakSetting {" ".join(attrs)}/>'

            heading_m = re.search(r'<' + NS + r':heading\b[^/>]*/>', block)
            align_m = re.search(r'<' + NS + r':align\b[^/>]*/>', block)
            if heading_m:
                insert_at = heading_m.end()
            elif align_m:
                insert_at = align_m.end()
            else:
                open_m = re.search(r'<' + NS + r':paraPr\b[^>]*>', block)
                insert_at = open_m.end() if open_m else 0
            block = block[:insert_at] + new_tag + block[insert_at:]
    return block


_ALIGN_TO_HORIZONTAL = {
    "left": "LEFT", "right": "RIGHT", "center": "CENTER",
    "justify": "JUSTIFY", "distribute": "DISTRIBUTE",
}


def restore_para_formats(path, baseline_path, out_path=None):
    """baseline(form_baseline.json)의 para_formats 중 line_spacing/align이 있는
    항목을, text_head로 매칭한 출력 문단에 한해 복원한다.

    매칭 안 되는 항목(out에 해당 문단 없음)은 조용히 스킵 — check_para_formats와
    동일 정책(heading류는 check_headings가 별도 커버).
    baseline 값과 현재 출력 값이 이미 같으면(anomaly 아님) 건드리지 않는다.

    반환: {"ok": True, "restored": [{"text_head":.., "line_spacing":.., "align":..}, ...]}
    """
    path = Path(path)
    out_path = Path(out_path) if out_path else path
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    para_formats = baseline.get("para_formats", [])
    if not para_formats:
        return {"ok": True, "restored": []}

    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}
        infos = {n: zin.getinfo(n) for n in names}

    header_xml = contents["Contents/header.xml"].decode("utf-8")
    defs_by_id = _parapr_defs_by_id(header_xml)
    max_id = max((int(pid) for pid in defs_by_id), default=-1)

    section_names = sorted(n for n in names if re.match(r"Contents/section\d+\.xml", n))
    section_xmls = {n: contents[n].decode("utf-8") for n in section_names}

    # clone 재사용 캐시: (원본 def id, target line_spacing tuple, target align) -> new id
    clone_cache = {}
    new_defs = []  # [(new_id, block_xml)]
    restored = []

    for entry in para_formats:
        target_ls = entry.get("line_spacing")
        target_align = entry.get("align")
        if target_ls is None and target_align is None:
            continue
        text_head = entry["text_head"]

        match_section = None
        match_entry = None
        for sname, sxml in section_xmls.items():
            paras = _find_top_level_paragraphs_with_prattrs(sxml)
            hit = _find_para_format_match_xml(paras, text_head)
            if hit is not None:
                match_section = sname
                match_entry = hit
                break
        if match_entry is None:
            continue  # out에 없음(heading_merged 등은 check_headings 소관).

        _p_start, _p_end, _p_xml, _open_end, pr_attrs = match_entry
        cur_id = _attr_value(pr_attrs, "paraPrIDRef")
        if cur_id is None or cur_id not in defs_by_id:
            continue

        cur_block_start, cur_block_end, cur_block_xml = defs_by_id[cur_id]
        cur_ls_m = re.search(r'<' + NS + r':lineSpacing\b([^/>]*)/>', cur_block_xml)
        cur_ls = None
        if cur_ls_m:
            t = _attr_value(cur_ls_m.group(1), "type")
            v = _attr_value(cur_ls_m.group(1), "value")
            cur_ls = (t, v)
        cur_align_m = re.search(r'<' + NS + r':align\b([^/>]*)/>', cur_block_xml)
        cur_align = _attr_value(cur_align_m.group(1), "horizontal") if cur_align_m else None

        want_ls = None
        if target_ls is not None:
            want_ls = (target_ls["type"], str(target_ls["value"]))
        want_align = _ALIGN_TO_HORIZONTAL.get(target_align) if target_align else None

        ls_changed = want_ls is not None and want_ls != cur_ls
        align_changed = want_align is not None and want_align != cur_align
        if not ls_changed and not align_changed:
            continue  # 이미 baseline과 일치 — anomaly 아님, 손대지 않음.

        cache_key = (cur_id, want_ls if ls_changed else None, want_align if align_changed else None)
        new_id = clone_cache.get(cache_key)
        if new_id is None:
            max_id += 1
            new_id = max_id
            patched = _patch_parapr_block(
                cur_block_xml, new_id,
                line_spacing=want_ls if ls_changed else None,
                align=want_align if align_changed else None,
            )
            new_defs.append((new_id, patched))
            clone_cache[cache_key] = new_id

        # 이 문단의 paraPrIDRef만 새 id로 치환(문단 여는 태그 구간 안에서만 치환
        # — open_end 이후 본문에 우연히 같은 문자열이 있어도 건드리지 않는다).
        open_tag_len = _open_end - _p_start
        old_open_tag = _p_xml[:open_tag_len]
        new_open_tag = re.sub(
            r'(\bparaPrIDRef\s*=\s*")' + re.escape(cur_id) + r'(")',
            r'\g<1>' + str(new_id) + r'\2', old_open_tag, count=1,
        )
        new_p_xml = new_open_tag + _p_xml[open_tag_len:]
        sxml = section_xmls[match_section]
        section_xmls[match_section] = sxml[:_p_start] + new_p_xml + sxml[_p_end:]

        restored.append({
            "text_head": text_head,
            "line_spacing": target_ls if ls_changed else None,
            "align": target_align if align_changed else None,
            "paraPrIDRef": {"from": cur_id, "to": str(new_id)},
        })

    if new_defs:
        # 새 def를 </.../:paraProperties> 직전에 append, itemCnt 갱신.
        close_m = re.search(r'</' + NS + r':paraProperties>', header_xml)
        if close_m is None:
            die("header.xml에 paraProperties 컨테이너 없음 — 구조 이상")
        blocks_xml = "".join(b for _nid, b in new_defs)
        header_xml = header_xml[:close_m.start()] + blocks_xml + header_xml[close_m.start():]

        def _bump_count(m):
            full_tag = m.group(0)
            cm = re.search(r'(itemCnt\s*=\s*")(\d+)(")', full_tag)
            if not cm:
                return full_tag
            new_cnt = int(cm.group(2)) + len(new_defs)
            return full_tag[:cm.start()] + cm.group(1) + str(new_cnt) + cm.group(3) + \
                full_tag[cm.end():]

        header_xml = PARAPROPERTIES_RE.sub(_bump_count, header_xml, count=1)

    if not restored:
        return {"ok": True, "restored": []}

    contents["Contents/header.xml"] = header_xml.encode("utf-8")
    for sname, sxml in section_xmls.items():
        contents[sname] = sxml.encode("utf-8")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".hwpx", dir=str(path.parent))
    import os
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(path) as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = contents[item.filename]
                zout.writestr(item, data)
        shutil.move(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {"ok": True, "restored": restored}


def apply_keep_with_next(path, prefixes, out_path=None):
    """prefixes 중 하나로 시작하는(공백 정규화 text) 모든 top-level 문단에
    keepWithNext="1" paraPr을 적용(clone/repoint — restore_para_formats와
    동일 패턴). 매치 0건인 prefix는 die(오타 방지 — --before/--after와 달리
    모호함은 거부하지 않되, "전혀 없음"은 여전히 사용자 실수 신호).

    주의(Rule 2 — 캡션이 객체 아래로 이동): 이 함수는 범용 "prefix로 시작하는
    문단에 keepWithNext" 유틸이라, prefix로 캡션 텍스트("표 1." 등)를 주면
    캡션 문단 자신에 keepWithNext=1이 걸린다. 캡션이 객체 '아래'에 있는 현재
    레이아웃에서는 이게 캡션을 "다음 본문"에 묶어버려 목적(객체+캡션 결속)과
    반대로 작동한다 — 객체+캡션을 묶으려면 build.yaml keep_with_next에는
    캡션이 아니라 객체 자체를 식별할 프리픽스를 줄 수 없으므로(객체 문단은
    텍스트가 없음), 이 경로 대신 apply_typeset_defaults를 쓸 것 — 그쪽은
    "다음 문단이 캡션인 객체 문단"을 자동 탐지해 객체 문단에 keepWithNext를
    건다(Rule 2 표준 구현). 이 함수는 캡션-무관 범용 prefix 바인딩이 필요한
    옛 호출부와의 하위호환을 위해 남아있다.

    반환: {"ok": True, "patched": [{"prefix":.., "text_head":.., "paraPrIDRef":
    {"from":.., "to":..}}, ...]}
    """
    path = Path(path)
    out_path = Path(out_path) if out_path else path
    if not prefixes:
        return {"ok": True, "patched": []}

    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}

    header_xml = contents["Contents/header.xml"].decode("utf-8")
    defs_by_id = _parapr_defs_by_id(header_xml)
    max_id = max((int(pid) for pid in defs_by_id), default=-1)

    section_names = sorted(n for n in names if re.match(r"Contents/section\d+\.xml", n))
    section_xmls = {n: contents[n].decode("utf-8") for n in section_names}

    clone_cache = {}  # 원본 def id -> new id (keepWithNext="1" 버전)
    new_defs = []      # [(new_id, block_xml)]
    patched = []
    matched_any = {p: False for p in prefixes}

    for sname, sxml in section_xmls.items():
        paras = _find_top_level_paragraphs_with_prattrs(sxml)
        # 뒤에서부터 치환해야 앞쪽 오프셋이 안 흔들림.
        for entry in sorted(paras, key=lambda e: e[0], reverse=True):
            _p_start, _p_end, _p_xml, _open_end, pr_attrs = entry
            text = _para_text(_p_xml).strip()
            hit_prefix = next((p for p in prefixes if text.startswith(p)), None)
            if hit_prefix is None:
                continue
            matched_any[hit_prefix] = True

            cur_id = _attr_value(pr_attrs, "paraPrIDRef")
            if cur_id is None or cur_id not in defs_by_id:
                continue
            cur_block_start, cur_block_end, cur_block_xml = defs_by_id[cur_id]
            cur_kwn_m = re.search(r'<' + NS + r':breakSetting\b([^/>]*)/>', cur_block_xml)
            cur_kwn = _attr_value(cur_kwn_m.group(1), "keepWithNext") if cur_kwn_m else None
            if cur_kwn == "1":
                continue  # 이미 keepWithNext — anomaly 아님, 손대지 않음.

            new_id = clone_cache.get(cur_id)
            if new_id is None:
                max_id += 1
                new_id = max_id
                patched_block = _patch_parapr_block(cur_block_xml, new_id, keep_with_next="1")
                new_defs.append((new_id, patched_block))
                clone_cache[cur_id] = new_id

            open_tag_len = _open_end - _p_start
            old_open_tag = _p_xml[:open_tag_len]
            new_open_tag = re.sub(
                r'(\bparaPrIDRef\s*=\s*")' + re.escape(cur_id) + r'(")',
                r'\g<1>' + str(new_id) + r'\2', old_open_tag, count=1,
            )
            new_p_xml = new_open_tag + _p_xml[open_tag_len:]
            sxml = sxml[:_p_start] + new_p_xml + sxml[_p_end:]
            section_xmls[sname] = sxml

            patched.append({
                "prefix": hit_prefix,
                "text_head": text[:40],
                "paraPrIDRef": {"from": cur_id, "to": str(new_id)},
            })

    missing = [p for p, hit in matched_any.items() if not hit]
    if missing:
        die(f"--keep-with-next 프리픽스 매치 없음(오타 의심): {missing}")

    if new_defs:
        close_m = re.search(r'</' + NS + r':paraProperties>', header_xml)
        if close_m is None:
            die("header.xml에 paraProperties 컨테이너 없음 — 구조 이상")
        blocks_xml = "".join(b for _nid, b in new_defs)
        header_xml = header_xml[:close_m.start()] + blocks_xml + header_xml[close_m.start():]

        def _bump_count(m):
            full_tag = m.group(0)
            cm = re.search(r'(itemCnt\s*=\s*")(\d+)(")', full_tag)
            if not cm:
                return full_tag
            new_cnt = int(cm.group(2)) + len(new_defs)
            return full_tag[:cm.start()] + cm.group(1) + str(new_cnt) + cm.group(3) + \
                full_tag[cm.end():]

        header_xml = PARAPROPERTIES_RE.sub(_bump_count, header_xml, count=1)

    if not patched:
        return {"ok": True, "patched": []}

    contents["Contents/header.xml"] = header_xml.encode("utf-8")
    for sname, sxml in section_xmls.items():
        contents[sname] = sxml.encode("utf-8")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".hwpx", dir=str(path.parent))
    import os
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(path) as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = contents[item.filename]
                zout.writestr(item, data)
        shutil.move(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {"ok": True, "patched": patched}


# ---------------------------------------------------------------------------
# --typeset-defaults: widowOrphan=1 on every top-level body paragraph, plus
# keepWithNext=1 additionally on heading/caption paragraphs. Same clone/repoint
# pattern as restore_para_formats/apply_keep_with_next, but unified into one
# pass per paragraph since both attrs live on the same hh:breakSetting tag of
# the same paraPr def — doing widowOrphan and keepWithNext as two independent
# sequential passes would clone the same def twice (once per pass) instead of
# once per distinct (orig_id, widow_target, kwn_target) combination.
# ---------------------------------------------------------------------------

DEFAULT_CAPTION_PREFIXES = ["표 ", "[그림"]


def _normalize_ws(text):
    """문단 텍스트 앞뒤 whitespace를 strip하고 내부 whitespace 런(런 분할로
    생긴 공백 포함)을 한 칸으로 합친다. prefix/anchor 쪽 문자열은 이 함수를
    거치지 않는다 — 캡션 프리픽스("표 " 등)의 의미 있는 trailing space를
    지우면 "표본을..." 같은 무관한 본문 문단이 "표"로 시작한다는 이유만으로
    오탐되므로, apply_keep_with_next와 동일하게 사용자가 준 프리픽스 문자열은
    있는 그대로(trailing space 포함) 비교해야 한다."""
    return re.sub(r"\s+", " ", text.strip())


def _is_heading(text, anchors):
    """anchors(제목) 중 하나와 whitespace 정규화 후 정확히 같거나 그 문자열로
    시작하면 True. 제목 문단은 Rule 2 캡션 방향 전환과 무관하게 자기 자신이
    keepWithNext=1을 받는다(제목이 다음 본문과 분리되는 것을 막는 기존 의미
    그대로)."""
    norm = _normalize_ws(text)
    if not norm:
        return False
    for a in anchors:
        a_stripped = a.strip()
        if a_stripped and (norm == a_stripped or norm.startswith(a_stripped)):
            return True
    return False


def _is_caption(text, caption_prefixes):
    """caption_prefixes(표·그림 캡션) 중 하나로 시작하면 True. 프리픽스
    문자열 자체는 정규화하지 않는다(있는 그대로 비교, trailing space 보존) —
    apply_keep_with_next와 동일 관례."""
    norm = _normalize_ws(text)
    if not norm:
        return False
    for p in caption_prefixes:
        if p and norm.startswith(p):
            return True
    return False


def _is_heading_or_caption(text, anchors, caption_prefixes):
    """하위호환 별칭(옛 단일 판정) — 테스트/외부 호출자가 참조할 수 있어 유지.
    Rule 2 이후 apply_typeset_defaults 내부는 이 함수를 쓰지 않는다(캡션은
    더 이상 자기 문단에 keepWithNext를 받지 않음 — 대신 object anchor 문단이
    받는다). _is_heading와 _is_caption의 OR로 옛 동작과 동일하게 남겨둔다."""
    return _is_heading(text, anchors) or _is_caption(text, caption_prefixes)


def _object_wants_keep_with_next(paras_text, caption_prefixes):
    """Rule 2: 문단 i가 객체(표/그림 등)를 담고 있고, 바로 다음 top-level
    문단의 텍스트가 caption_prefixes 중 하나로 시작하면, i번째 문단이
    keepWithNext=1을 받아야 한다(객체+캡션을 같은 페이지에 묶음 — 캡션이
    객체 '아래'로 이동한 뒤에는 캡션이 아니라 객체 문단이 다음 문단(캡션)과
    묶여야 페이지 나누기가 객체와 캡션 사이에 끼지 않는다).

    paras_text: [(is_object, text), ...] — top-level 문단 순서 그대로.
    반환: {index: True} — keepWithNext를 받아야 할 문단 인덱스 집합."""
    want = set()
    n = len(paras_text)
    for i in range(n):
        is_object, _text = paras_text[i]
        if not is_object:
            continue
        if i + 1 < n and _is_caption(paras_text[i + 1][1], caption_prefixes):
            want.add(i)
    return want


def apply_typeset_defaults(path, anchors, caption_prefixes=None, out_path=None,
                            dry_run=False):
    """모든 top-level 본문 문단에 widowOrphan="1"을 적용하고, profile의 anchors
    (제목 문단)나 caption_prefixes(표/그림 캡션 등)로 시작하는 문단에는
    keepWithNext="1"도 추가로 적용한다. 표 셀(hp:tbl) 안에 중첩된 문단은
    (top-level 판정 자체가 이를 제외하므로) 건드리지 않는다.

    clone/repoint 패턴은 restore_para_formats/apply_keep_with_next와 동일하되,
    widowOrphan+keepWithNext 두 속성이 같은 breakSetting 태그에 있으므로 문단당
    한 번만 목표 (widowOrphan, keepWithNext) 조합을 계산해 그 조합 단위로 clone을
    캐시한다(원본 def id당 최대 2개 clone: 본문용 widowOrphan-only, 제목/캡션용
    widowOrphan+keepWithNext).

    이미 목표 값과 일치하는 def는 건드리지 않는다(idempotent — 두 번 실행해도
    byte-identical 출력).

    dry_run=True면 파일을 쓰지 않고 계획만 반환한다(patched는 계획된 repoint
    목록, 실제 적용은 하지 않음).

    반환: {"ok": True, "patched": [{"para_idx":.., "text_head":.., "widow_orphan":
    bool, "keep_with_next": bool, "paraPrIDRef": {"from":.., "to":..}}, ...]}
    """
    path = Path(path)
    out_path = Path(out_path) if out_path else path
    caption_prefixes = caption_prefixes if caption_prefixes is not None else DEFAULT_CAPTION_PREFIXES
    anchors = anchors or []

    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}

    header_xml = contents["Contents/header.xml"].decode("utf-8")
    defs_by_id = _parapr_defs_by_id(header_xml)
    max_id = max((int(pid) for pid in defs_by_id), default=-1)

    section_names = sorted(n for n in names if re.match(r"Contents/section\d+\.xml", n))
    section_xmls = {n: contents[n].decode("utf-8") for n in section_names}

    # clone 재사용 캐시: (원본 def id, keep_with_next target bool) -> new id.
    # widowOrphan target은 이 함수 내에서 항상 True 고정이므로 캐시 키에서 생략.
    clone_cache = {}
    new_defs = []  # [(new_id, block_xml)]
    patched = []
    global_para_idx = 0

    for sname in sorted(section_xmls):
        sxml = section_xmls[sname]
        paras = _find_top_level_paragraphs_with_prattrs(sxml)
        # Rule 2: 캡션이 객체 아래로 이동했으므로, keepWithNext는 캡션
        # 문단이 아니라 "바로 다음 문단이 캡션인 객체 문단"이 받아야 한다.
        # 이 판정은 문단 순서(이웃 관계)에 의존하므로 패치 루프(역순) 전에
        # 정방향으로 한 번 미리 계산해둔다.
        paras_text = [(_contains_object(px), _para_text(px)) for (_s, _e, px, _oe, _a) in paras]
        object_kwn_idx = _object_wants_keep_with_next(paras_text, caption_prefixes)
        # 뒤에서부터 치환해야 앞쪽 오프셋이 안 흔들림 — para_idx는 원래(정방향)
        # 순서로 기록해야 하므로 미리 (para_idx, entry) 짝을 만들어둔다.
        indexed = [(global_para_idx + i, entry, i) for i, entry in enumerate(paras)]
        global_para_idx += len(paras)

        for para_idx, entry, local_i in sorted(indexed, key=lambda ie: ie[1][0], reverse=True):
            _p_start, _p_end, _p_xml, _open_end, pr_attrs = entry
            text = _para_text(_p_xml)
            # Rule 2: 제목 문단은 그대로 자기 자신이 keepWithNext=1(다음 본문과
            # 분리 방지). 캡션 문단 자체는 더 이상 대상이 아니다 — 대신 그
            # 캡션 "바로 앞" 객체 문단(local_i가 object_kwn_idx에 있음)이 받는다.
            want_kwn = _is_heading(text, anchors) or (local_i in object_kwn_idx)

            cur_id = _attr_value(pr_attrs, "paraPrIDRef")
            if cur_id is None or cur_id not in defs_by_id:
                continue
            cur_block_start, cur_block_end, cur_block_xml = defs_by_id[cur_id]
            cur_break_m = re.search(r'<' + NS + r':breakSetting\b([^/>]*)/>', cur_block_xml)
            cur_widow = _attr_value(cur_break_m.group(1), "widowOrphan") if cur_break_m else None
            cur_kwn = _attr_value(cur_break_m.group(1), "keepWithNext") if cur_break_m else None

            want_widow_str = "1"
            want_kwn_str = "1" if want_kwn else cur_kwn

            widow_changed = cur_widow != want_widow_str
            kwn_changed = want_kwn and cur_kwn != "1"
            if not widow_changed and not kwn_changed:
                continue  # 이미 목표 상태 — anomaly 아님, 손대지 않음(idempotence).

            # 캐시 키: (원본 id, 최종 목표 keepWithNext 문자열) — widowOrphan은
            # 이 함수에서 항상 "1"로 고정이라 별도 축이 필요 없다.
            cache_key = (cur_id, want_kwn_str)
            new_id = clone_cache.get(cache_key)
            if new_id is None:
                if dry_run:
                    new_id = f"<new:{cur_id}:{want_kwn_str}>"
                else:
                    max_id += 1
                    new_id = max_id
                    patched_block = _patch_parapr_block(
                        cur_block_xml, new_id,
                        keep_with_next=want_kwn_str, widow_orphan=want_widow_str,
                    )
                    new_defs.append((new_id, patched_block))
                clone_cache[cache_key] = new_id

            record = {
                "para_idx": para_idx,
                "text_head": text.strip()[:40],
                "widow_orphan": True,
                "keep_with_next": bool(want_kwn),
                "paraPrIDRef": {"from": cur_id, "to": str(new_id)},
            }
            patched.append(record)

            if dry_run:
                continue

            open_tag_len = _open_end - _p_start
            old_open_tag = _p_xml[:open_tag_len]
            new_open_tag = re.sub(
                r'(\bparaPrIDRef\s*=\s*")' + re.escape(cur_id) + r'(")',
                r'\g<1>' + str(new_id) + r'\2', old_open_tag, count=1,
            )
            new_p_xml = new_open_tag + _p_xml[open_tag_len:]
            sxml = sxml[:_p_start] + new_p_xml + sxml[_p_end:]
            section_xmls[sname] = sxml

    patched.sort(key=lambda r: r["para_idx"])

    if dry_run:
        return {"ok": True, "patched": patched, "dry_run": True}

    if not patched:
        return {"ok": True, "patched": []}

    if new_defs:
        close_m = re.search(r'</' + NS + r':paraProperties>', header_xml)
        if close_m is None:
            die("header.xml에 paraProperties 컨테이너 없음 — 구조 이상")
        blocks_xml = "".join(b for _nid, b in new_defs)
        header_xml = header_xml[:close_m.start()] + blocks_xml + header_xml[close_m.start():]

        def _bump_count(m):
            full_tag = m.group(0)
            cm = re.search(r'(itemCnt\s*=\s*")(\d+)(")', full_tag)
            if not cm:
                return full_tag
            new_cnt = int(cm.group(2)) + len(new_defs)
            return full_tag[:cm.start()] + cm.group(1) + str(new_cnt) + cm.group(3) + \
                full_tag[cm.end():]

        header_xml = PARAPROPERTIES_RE.sub(_bump_count, header_xml, count=1)

    contents["Contents/header.xml"] = header_xml.encode("utf-8")
    for sname, sxml in section_xmls.items():
        contents[sname] = sxml.encode("utf-8")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".hwpx", dir=str(path.parent))
    import os
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(path) as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = contents[item.filename]
                zout.writestr(item, data)
        shutil.move(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {"ok": True, "patched": patched}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help=".hwpx 경로")
    ap.add_argument("--before", action="append", default=[],
                     help="이 앞의 연속 빈 문단을 정리(여러 번 지정 가능)")
    ap.add_argument("--after", action="append", default=[],
                     help="이 뒤의 연속 빈 문단을 정리(여러 번 지정 가능)")
    ap.add_argument("--keep", type=int, default=1, help="각 방향에 남길 빈 문단 개수")
    ap.add_argument("--keep-map",
                     help="anchor별 keep 개수 오버라이드 JSON({\"anchor\": n, ...}) — "
                          "Rule 1: form_inspect.py의 anchors_blanks_before를 그대로 "
                          "주면 양식 원본 여백을 anchor별로 보존한다. 없는 anchor는 "
                          "--keep 기본값 그대로")
    ap.add_argument("--restore-formats",
                     help="form_baseline.json — para_formats의 line_spacing/align을 "
                          "text_head 매칭 문단에 복원(set_line_spacing 전역 적용 회귀 교정)")
    ap.add_argument("--keep-with-next", action="append", default=[],
                     help="이 프리픽스로 시작하는 모든 문단에 keepWithNext=1 적용"
                          "(여러 번 지정 가능, 표 캡션 고아 방지)")
    ap.add_argument("--typeset-defaults", action="store_true",
                     help="모든 top-level 본문 문단에 widowOrphan=1, "
                          "제목(--profile anchors)/캡션(--caption-prefixes) 문단에는 "
                          "keepWithNext=1도 추가 적용")
    ap.add_argument("--profile",
                     help="--typeset-defaults용 form_profile.json(anchors 목록 사용)")
    ap.add_argument("--caption-prefixes",
                     help="--typeset-defaults용 캡션 프리픽스, 쉼표로 구분"
                          f"(기본: {', '.join(DEFAULT_CAPTION_PREFIXES)!r})")
    ap.add_argument("--dry-run", action="store_true",
                     help="--typeset-defaults 계획만 출력하고 파일은 쓰지 않음")
    ap.add_argument("--out", help="출력 경로(생략 시 원본 덮어씀)")
    args = ap.parse_args()

    if not Path(args.file).exists():
        die(f"파일 없음: {args.file}", code=2)
    if not (args.before or args.after or args.restore_formats or args.keep_with_next
            or args.typeset_defaults):
        die("--before/--after/--restore-formats/--keep-with-next/--typeset-defaults "
            "중 최소 하나 필요", code=2)
    if args.dry_run and not args.typeset_defaults:
        die("--dry-run은 --typeset-defaults와 함께만 사용 가능", code=2)

    keep_map = None
    if args.keep_map:
        try:
            keep_map = json.loads(args.keep_map)
        except json.JSONDecodeError as e:
            die(f"--keep-map JSON 파싱 실패: {e}", code=2)

    result = {"ok": True}
    cur = args.file
    out = args.out or args.file

    if args.before or args.after:
        tidy_result = tidy_hwpx(cur, args.before, args.after, keep=args.keep, out_path=out,
                                 keep_map=keep_map)
        result["ok"] = result["ok"] and tidy_result["ok"]
        result["removed"] = tidy_result["removed"]
        cur = out

    if args.restore_formats:
        if not Path(args.restore_formats).exists():
            die(f"baseline 없음: {args.restore_formats}", code=2)
        restore_result = restore_para_formats(cur, args.restore_formats, out_path=out)
        result["ok"] = result["ok"] and restore_result["ok"]
        result["restored"] = restore_result["restored"]
        cur = out

    if args.keep_with_next:
        kwn_result = apply_keep_with_next(cur, args.keep_with_next, out_path=out)
        result["ok"] = result["ok"] and kwn_result["ok"]
        result["patched"] = kwn_result["patched"]
        cur = out

    if args.typeset_defaults:
        anchors = []
        if args.profile:
            if not Path(args.profile).exists():
                die(f"profile 없음: {args.profile}", code=2)
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
            anchors = profile.get("anchors", [])
        caption_prefixes = (
            [p for p in args.caption_prefixes.split(",") if p]
            if args.caption_prefixes else None
        )
        # --typeset-defaults는 다른 모든 패스(빈 문단 정리/포맷 복원/캡션 keepWithNext)
        # 이후 최종 문단 구조 위에서 실행한다 — widowOrphan은 가장 넓은 범위(모든
        # top-level 본문)라 앞선 패스가 지우거나 재배치한 문단에 영향받지 않아야
        # 하고, 앞선 --keep-with-next가 이미 세팅한 keepWithNext="1"을 이 패스가
        # 되돌리지 않고 보존해야 하기 때문(내부적으로 cur_kwn=="1"이면 유지).
        typeset_result = apply_typeset_defaults(
            cur, anchors, caption_prefixes=caption_prefixes, out_path=out,
            dry_run=args.dry_run,
        )
        result["ok"] = result["ok"] and typeset_result["ok"]
        result["typeset_defaults"] = typeset_result["patched"]
        if args.dry_run:
            result["dry_run"] = True
        cur = out

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    sys.exit(0)


if __name__ == "__main__":
    main()
