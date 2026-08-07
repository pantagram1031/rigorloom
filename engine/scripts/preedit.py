#!/usr/bin/env python3
"""preedit.py — 감사 승자(variant-audit "Form preprocessing" 행)의 양식 선처리
오퍼레이션을 엔진 라이브러리로 고정 (오프라인, 비-COM).

세 오퍼레이션 — 모두 원본 비파괴(hwpx_in은 읽기만, 출력은 임시파일→이동):

  1. replace_placeholders   : dict 기반 자리표시자 치환 (work/preedit_form.py 승계).
     러너 텍스트 strip-비교 tier를 추가해 hawkes sim의 trailing-space 결함
     클래스를 근본 수정 — ">텍스트<" 정확일치는 런 텍스트에 앞뒤 공백이
     있으면 조용히 실패(무보고 no-op)했다. 0-hit 키는 기본 ERROR.
  2. delete_guide_paragraphs: 가이드 charPr(색/명시 id) 참조 문단 삭제
     (sim/preedit_official.py의 메커니즘 승계 + T18 보호 가드 내장 —
     guards.is_protected_para. 표/secPr/ctrl/개체 문단은 절대 삭제하지 않는다).
     공백뿐인 런은 텍스트 런으로 치지 않는다(결함 클래스 동일 수정).
  3. normalize_clones       : 정규화형 postedit (sim/postedit_byline_black.py 승계)
     — 기존 클론 전부 제거 → 정확히 하나씩 재생성 → itemCnt 실측 재계산 →
     guards.assert_no_dangling_charpr 내장 사후검사(T22).

멱등성 계약: 어떤 오퍼레이션이든 자기 출력에 다시 적용하면 content-identical
(zip 멤버 내용 기준 — 타임스탬프 무시, content_fingerprint로 비교).
replace_placeholders는 2회차에 자리표시자가 이미 소진되므로
on_zero_hits="ignore"로 재실행할 때의 계약이다.

사후 불변식(모든 오퍼레이션 공통): 수정된 XML 멤버는 출력 zip에 쓰기 전
전부 xml.etree 파싱(well-formed 검증)을 통과해야 한다 — 실패 시
PreeditError, 아무것도 쓰지 않는다. 실전 사고(2026 공식 양식): 자기닫힘
<hp:t/>를 여는 태그로 오인한 치환이 짝 없는 닫는 태그를 만들었고 한컴은
문서 전체를 백지로 렌더했다 — 손상 출력은 구조적으로 불가능해야 한다.

stale-lineseg(P0, 실사격 후속 사고): 문단 텍스트를 바꾸면서 한컴의 캐시
레이아웃 <hp:linesegarray>를 남겨두면 옛 좌표에 겹쳐 그린다(74자 제목
overprint). 텍스트가 바뀐 '그' 문단의 linesegarray만 제거한다 — 한컴은
없으면 열 때 재계산하고, 바뀌지 않은 문단은 바이트 그대로 보존한다.

CLI(얇은 래퍼):
    python preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
    python preedit.py delete-guides IN.hwpx --out OUT.hwpx [--color '#0000FF'|blue]
                      [--charpr-ids 5,6]
    python preedit.py normalize-clones IN.hwpx --out OUT.hwpx --clone SRC:NEW ...
                      [--set textColor=#000000 ...] [--repoint FROM:TO:TEXT ...]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import guards

# tidy_hwpx와 동일 관용구: 접두사(hp:/hs:/hh:)는 가변이므로 로컬네임 매칭.
NS = r'[A-Za-z0-9]+'
SECTION_RE = re.compile(r"Contents/section\d+\.xml")
# 여는 태그의 (?<!/) — 자기닫힘 <hp:t/>(빈 텍스트 런, 한컴이 흔히 이렇게
# 직렬화)를 여는 태그로 오인하면 안 된다. 실전 사고(2026 공식 양식):
# <hp:t/>를 opener로 잡은 치환이 다음 요소의 진짜 여는 태그까지 group(2)로
# 집어삼켜 '<hp:t/>제목…</hp:t>'(짝 없는 닫는 태그)를 만들었고, 한컴은
# 문서 전체를 백지로 렌더했다. <hp:t />(공백+자기닫힘)도 매칭 불가.
T_FULL_RE = re.compile(
    r'(<' + NS + r':t\b[^>]*(?<!/)>)(.*?)(</' + NS + r':t>)', re.S)
RUN_RE = re.compile(r'<(' + NS + r'):run\b([^>]*?)(?:/>|>(.*?)</\1:run>)', re.S)
P_OPEN_RE = re.compile(r'<' + NS + r':p\b[^>]*>')
# 한컴의 문단별 캐시 레이아웃. 텍스트를 바꾼 문단에 이걸 남겨두면 한컴이
# 옛 좌표에 세그먼트를 그대로 그려 겹쳐 찍힌다(stale-lineseg — 실사격에서
# 74자 제목이 옛 자리표시자 레이아웃 위에 OVERPRINT). linesegarray가 없으면
# 한컴은 열 때 레이아웃을 재계산한다(rigorloom P0 parity와 동일 원리).
LINESEG_RE = re.compile(
    r'<' + NS + r':linesegarray\b(?:[^>]*/>|[^>]*>.*?</' + NS
    + r':linesegarray>)', re.S)
CHARPR_OPEN_RE = re.compile(r'<' + NS + r':charPr\b')
CHARPROPERTIES_RE = re.compile(r'<' + NS + r':charProperties\b[^>]*>')

# 문단 파서·개체 태그 집합은 tidy_hwpx의 검증된 구현을 재사용한다
# (스택 기반 top-level 판정 — 표 셀 안 문단은 top-level이 아니므로
# 삭제 후보에서 구조적으로 제외된다 = sim의 in_tbl 배제와 동등).
from tidy_hwpx import OBJECT_TAG_RE, _find_paragraphs, _para_text  # noqa: E402
from hwpx_tables import find_cell, scan_tables  # noqa: E402


class PreeditError(RuntimeError):
    """선처리 계약 위반(0-hit 키, src charPr 부재 등) — 출력을 쓰기 전에 터진다."""


# ---------------------------------------------------------------------------
# zip 공통 유틸 — 원본 비파괴(읽기 전용) + 원자적 쓰기(temp → move)
# ---------------------------------------------------------------------------

def _read_zip(path):
    """hwpx zip을 통째로 메모리에 — (infolist 순서 보존, {name: bytes})."""
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        contents = {i.filename: z.read(i.filename) for i in infos}
    return infos, contents


def _write_zip(out_path, infos, contents):
    """임시파일에 쓴 뒤 move — 실패 시 out_path는 생성/변경되지 않는다."""
    out_path = Path(out_path)
    fd, tmp = tempfile.mkstemp(suffix=".hwpx", dir=str(out_path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for info in infos:
                z.writestr(info, contents[info.filename])
        shutil.move(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _section_names(contents):
    return sorted(n for n in contents if SECTION_RE.fullmatch(n))


def _header_name(contents):
    for n in contents:
        if n.endswith("header.xml"):
            return n
    raise PreeditError("hwpx에 header.xml 멤버 없음 — 구조 이상")


def _assert_members_well_formed(contents, member_names):
    """수정된 XML 멤버 전부를 ET.fromstring으로 검증 — 실패 시 PreeditError.

    사후 불변식(모든 오퍼레이션 공통): 구조가 깨진 XML은 출력 zip에 절대
    쓰지 않는다. failing-before(실전 사고, 2026 공식 양식): 자기닫힘
    <hp:t/> 오인 치환이 '<hp:t/>제목…</hp:t>'(짝 없는 닫는 태그)를 만들어
    ET ParseError(mismatched tag) — 한컴은 문서 전체를 백지로 렌더했다.
    """
    for name in sorted(member_names):
        try:
            ET.fromstring(contents[name])
        except ET.ParseError as exc:
            raise PreeditError(
                f"산출 XML이 well-formed 아님({name}): {exc}"
                " — 손상 출력 차단, 아무것도 쓰지 않음") from exc


def content_fingerprint(path):
    """zip 멤버 내용 지문 {name: sha256} — 타임스탬프 등 메타는 무시.

    멱등성 계약 검증용: 두 파일의 fingerprint가 같으면 content-identical.
    """
    with zipfile.ZipFile(path) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest()
                for n in sorted(z.namelist())}


def _strip_tags(xml_text):
    return re.sub(r"<[^>]+>", "", xml_text)


# ---------------------------------------------------------------------------
# 1) replace_placeholders — dict 기반 치환, whitespace-tolerant, 0-hit=ERROR
# ---------------------------------------------------------------------------

def _overlaps(start, end, spans):
    """[start, end) 가 spans 중 하나라도 겹치면 True."""
    return any(start < s_end and s_start < end for s_start, s_end in spans)


def _apply_edits(text, edits, protected):
    """정렬·비중첩 edits [(start, end, replacement)] 를 한 번에 적용.

    protected 스팬(이미 '쓴' 값의 위치)은 어떤 edit과도 겹치지 않는다는 게
    호출자 계약이므로, 새 좌표로 평행이동만 하면 된다. 삽입된 replacement의
    스팬도 protected에 추가해 돌려준다 — 그래야 다음 tier/다음 키가 방금 쓴
    값을 다시 건드리지 않는다(D1 double-apply의 근본 차단).

    반환: (new_text, new_protected)
    """
    if not edits:
        return text, protected
    edits = sorted(edits)
    out, cursor, shift = [], 0, 0
    written = []
    shifts = []  # (old_pos, delta_before_this_pos) — protected 재매핑용
    for start, end, repl in edits:
        out.append(text[cursor:start])
        new_start = start + shift
        out.append(repl)
        shift += len(repl) - (end - start)
        written.append((new_start, new_start + len(repl)))
        shifts.append((end, shift))
        cursor = end
    out.append(text[cursor:])

    def _shift_at(pos):
        d = 0
        for edit_end, delta in shifts:
            if edit_end <= pos:
                d = delta
            else:
                break
        return d

    remapped = [(s + _shift_at(s), e + _shift_at(s)) for s, e in protected]
    return "".join(out), sorted(remapped + written)


def _apply_tiers(text, mapping, hits):
    """치환 2단(tier A: 런 strip-비교 / tier B: raw 부분문자열)을 문자열
    조각에 적용하고 새 문자열을 돌려준다. hit는 hits dict에 누적.

    D1(값이 키를 포함하면 이중 적용): tier B는 tier A가 이미 다시 쓴 스팬 위를
    또 훑었다. operations.md가 스스로 문서화한 예제
    `{" http://": " http://example.kr"}` 가 실측으로 `" http://example.krexample.kr"`
    (hits=2)를 만들었다 — 문서대로 따라 하면 셀이 망가진다. 이제 '이미 쓴 값'의
    스팬을 protected로 추적하고, 어떤 tier·어떤 키도 그 위를 다시 치환하지
    않는다. 한 번 쓴 값은 최종값이다(single-pass 치환 시맨틱).
    """
    protected = []
    for key, value in mapping.items():
        key_stripped = str(key).strip()
        value_esc = escape(str(value))
        needles = [n for n in dict.fromkeys([str(key), escape(str(key))]) if n]

        # 값이 키를 품는 매핑(" http://" → " http://example.kr")은 재실행
        # 멱등성도 깨뜨렸다 — 2회차에는 tier A 재작성이 없고, 이미 최종값인
        # 셀 안의 키를 tier B가 또 잡아 값을 한 번 더 이어붙인다. 그래서
        # '이미 최종값인 스팬'을 먼저 protected로 올린다. 한 번 값이 된
        # 텍스트는 다시 치환 대상이 아니다.
        if any(n != value_esc and n in value_esc for n in needles):
            pos = 0
            while True:
                i = text.find(value_esc, pos)
                if i < 0:
                    break
                protected.append((i, i + len(value_esc)))
                pos = i + len(value_esc)
            protected.sort()

        # tier A — 런 텍스트 strip-비교(whole-run). 이미 쓴 스팬과 겹치는
        # 런은 건너뛴다(그 런의 내용은 앞선 키가 확정한 값이다).
        edits = []
        for m in T_FULL_RE.finditer(text):
            inner = m.group(2)
            if _strip_tags(inner).strip() != key_stripped or inner == value_esc:
                continue
            if _overlaps(m.start(2), m.end(2), protected):
                continue
            edits.append((m.start(2), m.end(2), value_esc))
        if edits:
            hits[key] += len(edits)
            text, protected = _apply_edits(text, edits, protected)

        # tier B — raw 부분문자열. protected 스팬(방금 쓴 값 포함)은 불가침.
        for needle in needles:
            edits, pos = [], 0
            while True:
                i = text.find(needle, pos)
                if i < 0:
                    break
                j = i + len(needle)
                if _overlaps(i, j, protected):
                    pos = i + 1
                    continue
                edits.append((i, j, value_esc))
                pos = j
            if edits:
                hits[key] += len(edits)
                text, protected = _apply_edits(text, edits, protected)
    return text


def _replace_in_paragraph(p_xml, mapping, hits):
    """문단 하나에 치환 적용(중첩 셀 문단은 재귀). 자신의 텍스트가 바뀐
    문단만 자기 linesegarray를 제거한다(stale-lineseg P0).

    귀속 규칙: 문단 inner를 '중첩 문단 스팬'과 그 밖의 gap(자기 런·개체
    래퍼 태그·자기 linesegarray)으로 나눈다. <hp:t>는 항상 gap 안에 통째로
    있으므로 gap 치환은 문단 구조를 깨지 않는다. gap이 바뀌면 이 문단
    '자신의' 텍스트가 바뀐 것 — 자기 gap의 linesegarray만 제거하고, 중첩
    문단은 각자 재귀에서 판단한다(바뀌지 않은 문단의 lineseg는 바이트
    그대로 보존 — byte-fidelity)."""
    open_m = P_OPEN_RE.match(p_xml)
    if not open_m:  # 방어 — _find_paragraphs 조각이면 항상 매치
        return _apply_tiers(p_xml, mapping, hits)
    close_idx = p_xml.rfind("</")
    open_tag = p_xml[:open_m.end()]
    inner = p_xml[open_m.end():close_idx]
    close_tag = p_xml[close_idx:]

    nested = _find_paragraphs(inner)
    gaps, nested_out, last = [], [], 0
    for start, end, np_xml in nested:
        gaps.append(inner[last:start])
        nested_out.append(_replace_in_paragraph(np_xml, mapping, hits))
        last = end
    gaps.append(inner[last:])

    new_gaps = [_apply_tiers(g, mapping, hits) for g in gaps]
    if new_gaps != gaps:  # 이 문단 자신의 텍스트가 바뀜 → 캐시 레이아웃 제거
        new_gaps = [LINESEG_RE.sub("", g) for g in new_gaps]

    out = []
    for i, np_new in enumerate(nested_out):
        out.append(new_gaps[i])
        out.append(np_new)
    out.append(new_gaps[-1])
    return open_tag + "".join(out) + close_tag


def _replace_in_section(xml, mapping, hits):
    """섹션 XML 전체에 문단 단위 치환 적용(문단 밖 영역은 raw tier만)."""
    paras = _find_paragraphs(xml)
    out, last = [], 0
    for start, end, p_xml in paras:
        out.append(_apply_tiers(xml[last:start], mapping, hits))
        out.append(_replace_in_paragraph(p_xml, mapping, hits))
        last = end
    out.append(_apply_tiers(xml[last:], mapping, hits))
    return "".join(out)


def replace_placeholders(hwpx_in, hwpx_out, mapping, *, on_zero_hits="error"):
    """section*.xml 전반에 dict 기반 자리표시자 치환. 키별 hit 수를 보고한다.

    매칭 2단 (키마다, 섹션마다 순서대로):
      tier A — 런 텍스트 strip-비교: <hp:t> 내용(내부 태그 제거 후 strip)이
        key.strip()과 같으면 내용 전체를 값으로 교체. hawkes sim 결함
        (">key<" 정확일치가 trailing/leading 공백에 조용히 실패) 의
        근본 수정 — 잔여 공백 없이 정확히 값만 남는다.
      tier B — 원문 부분문자열 치환: work/preedit_form.py(감사 승자)와 동일한
        raw str.replace. 런 일부만 차지하는 키(표 셀 안 학번 등)를 커버.

    값은 XML 이스케이프(&, <, >)해 삽입한다. 키가 XML 이스케이프 형태로만
    존재하는 경우도 tier B에서 잡는다.

    0 hit 키: on_zero_hits="error"(기본)면 PreeditError — 출력 파일은 쓰지
    않는다(sim의 무보고 no-op가 바로 이 결함이었다). "ignore"면 0으로 보고만
    한다(멱등 재실행용).

    주의: 치환된 텍스트는 그 런의 원래 charPr을 그대로 상속한다 — 가이드
    색(파랑 등)일 수 있다. 색 전환(예: 저자명 파랑→검정)은 이 함수의 일이
    아니라 normalize_clones의 소관이다.

    자기닫힘 <hp:t/>는 여는 태그로 매칭되지 않는다(실전 사고 수정 — 위
    T_FULL_RE 주석). 사후 불변식: 수정된 모든 XML 멤버는 쓰기 전에
    well-formed 검증을 통과해야 한다(실패 시 PreeditError, 출력 미작성).

    stale-lineseg(P0): 텍스트가 바뀐 문단은 <hp:linesegarray>(한컴의 캐시
    레이아웃)를 제거한다 — 남겨두면 한컴이 옛 좌표에 겹쳐 그린다(실사격:
    74자 제목이 자리표시자 레이아웃 위에 overprint). linesegarray가 없으면
    한컴이 열 때 재계산한다. 바뀌지 않은 문단(중첩 셀 문단 포함)의
    linesegarray는 바이트 그대로 보존.

    반환: {"ok": True, "hits": {key: n}}
    """
    if on_zero_hits not in ("error", "ignore"):
        raise ValueError(f"on_zero_hits는 'error'|'ignore': {on_zero_hits!r}")
    for key in mapping:
        if not str(key).strip():
            raise PreeditError(f"빈(공백뿐인) 키는 치환 불가: {key!r}")

    infos, contents = _read_zip(hwpx_in)
    hits = {key: 0 for key in mapping}
    modified = set()

    for sname in _section_names(contents):
        original = contents[sname]
        xml = _replace_in_section(original.decode("utf-8"), mapping, hits)
        data = xml.encode("utf-8")
        if data != original:
            contents[sname] = data
            modified.add(sname)

    zero = [k for k, n in hits.items() if n == 0]
    if zero and on_zero_hits == "error":
        raise PreeditError(
            f"자리표시자 {len(zero)}개가 어느 섹션에서도 발견되지 않음"
            f" (무보고 no-op 금지): {zero}")

    _assert_members_well_formed(contents, modified)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "hits": hits}


# ---------------------------------------------------------------------------
# 1b) fill_cells — cellAddr로 '진짜 빈' 표 셀 채우기 (오프라인)
#
# T27(첫 클린룸 교차모델 런): 양식의 빈 셀은 텍스트가 '비어 있는' 게 아니라
# <hp:t>가 아예 없다 — <hp:run charPrIDRef="7"/> 자기닫힘 런 하나뿐이다.
# PPS 협업승인신청서 실측: 빈 셀 19/19가 전부 이 모양. replace는 텍스트
# 키 기반이라 잡을 문자열 자체가 없어 구조적으로 도달 불가인데도 SKILL.md는
# 양식 채우기를 replace로 안내했다 — 그래서 두 에이전트 모두 COM으로
# 넘어갔고 거기서 D3(셀 주소 오류)에 걸려 라벨 셀을 파괴했다.
# 오프라인으로 빈 셀에 도달하는 경로가 이 오퍼레이션이다.
# ---------------------------------------------------------------------------

T_SELFCLOSE_RE = re.compile(r'<(' + NS + r'):t\b[^>]*/>')
RUN_OPEN_RE = re.compile(r'<' + NS + r':run\b[^>]*?/?>')
TBL_TAG_RE = re.compile(r'<' + NS + r':tbl\b')


def _strip_nested_tbls(fragment):
    """조각에서 표(hp:tbl) 스팬을 통째로 제거 — '이 셀 자신의' 텍스트만 남긴다.

    중첩 표(코퍼스 12개 양식 중 6개에서 실측)가 있는 셀에서 안쪽 표의 텍스트를
    바깥 셀의 내용으로 오독하면 '비었는지' 판정이 통째로 뒤집힌다.
    """
    if not TBL_TAG_RE.search(fragment):
        return fragment
    spans = [(t["start"], t["end"]) for t in scan_tables(fragment)
             if t["depth"] == 0]
    out, cur = [], 0
    for s, e in spans:
        out.append(fragment[cur:s])
        cur = e
    out.append(fragment[cur:])
    return "".join(out)


def _fragment_text(fragment):
    """조각의 자기 텍스트(중첩 표 제외, hp:t 내용 이어붙임)."""
    own = _strip_nested_tbls(fragment)
    return _strip_tags("".join(t for _o, t, _c in T_FULL_RE.findall(own)))


def _write_text_into_paragraph(p_xml, text_esc, charpr):
    """문단의 '첫 런'에 텍스트를 쓴다 — 런의 charPr은 charpr가 없으면 보존.

    빈 셀의 표준형 <hp:run charPrIDRef="7"/>(자기닫힘, hp:t 없음)를 열린 런 +
    <hp:t>로 확장하는 것이 이 함수의 핵심 동작이다. 새로 만드는 <hp:t>는 항상
    짝 있는 태그다(자기닫힘 <hp:t/>는 만들지 않는다 — 그게 한컴 백지 렌더
    사고의 원인이었다).
    """
    m = RUN_RE.search(p_xml)
    if m is None:
        raise PreeditError("셀 문단에 hp:run이 없음 — 쓸 자리 없음")
    prefix = m.group(1)
    open_m = RUN_OPEN_RE.match(m.group(0))
    open_tag = open_m.group(0)
    if charpr is not None:
        open_tag = _tag_set_attr(open_tag, "charPrIDRef", str(charpr))
    t_new = f'<{prefix}:t>{text_esc}</{prefix}:t>'

    if m.group(3) is None:                       # 자기닫힘 런 — 확장한다
        open_tag = (open_tag[:-2] + '>') if open_tag.endswith('/>') else open_tag
        new_run = f'{open_tag}{t_new}</{prefix}:run>'
    else:
        body = m.group(3)
        tm = T_FULL_RE.search(body)
        if tm is not None:                        # 기존 hp:t 내용만 교체
            new_body = body[:tm.start(2)] + text_esc + body[tm.end(2):]
        else:
            scm = T_SELFCLOSE_RE.search(body)
            if scm is not None:                   # <hp:t/> → 짝 있는 태그로
                new_body = body[:scm.start()] + t_new + body[scm.end():]
            else:                                 # hp:t 자체가 없음 → 추가
                new_body = body + t_new
        new_run = f'{open_tag}{new_body}</{prefix}:run>'
    return p_xml[:m.start()] + new_run + p_xml[m.end():]


def _blank_paragraph_text(p_xml):
    """문단의 자기 hp:t 내용을 전부 비운다(overwrite 시 잔여 텍스트 제거)."""
    changed = False

    def _sub(m):
        nonlocal changed
        if m.group(2) == "":
            return m.group(0)
        changed = True
        return m.group(1) + m.group(3)

    if TBL_TAG_RE.search(p_xml):     # 중첩 표를 품은 문단은 건드리지 않는다
        return p_xml, False
    return T_FULL_RE.sub(_sub, p_xml), changed


def _fill_cell_body(body, text, *, overwrite, charpr):
    """셀 몸통(hp:tc의 자식 스팬)에 텍스트를 쓴 새 몸통을 만든다.

    반환: (new_body, current_text). 비어 있지 않은데 overwrite가 아니면
    PreeditError — 라벨 셀 덮어쓰기는 이 엔진에서 사고이지 기능이 아니다.
    """
    current = _fragment_text(body)
    if current.strip() and not overwrite:
        raise PreeditError(
            f"셀이 비어 있지 않음(현재 {current.strip()[:30]!r})"
            " — 덮어쓰려면 --overwrite")

    paras = _find_paragraphs(body)
    if not paras:
        raise PreeditError("셀에 문단(hp:p)이 없음 — 쓸 자리 없음")
    target = next((i for i, (_s, _e, p) in enumerate(paras)
                   if not TBL_TAG_RE.search(p)), None)
    if target is None:
        raise PreeditError("셀의 모든 문단이 중첩 표를 담고 있음 — 쓸 자리 없음")

    text_esc = escape(str(text))
    out, last = [], 0
    for i, (start, end, p_xml) in enumerate(paras):
        out.append(body[last:start])
        if i == target:
            new_p = _write_text_into_paragraph(p_xml, text_esc, charpr)
            changed = True
        else:
            new_p, changed = _blank_paragraph_text(p_xml)
        if changed:
            # T24 stale-lineseg: 텍스트가 바뀐 문단의 캐시 레이아웃은 제거한다.
            # 남기면 한컴이 옛 좌표에 그려 겹쳐 찍힌다(빈 셀의 lineseg는
            # '빈 줄' 좌표라 새 텍스트가 통째로 어긋난다).
            new_p = LINESEG_RE.sub("", new_p)
        out.append(new_p)
        last = end
    out.append(body[last:])
    return "".join(out), current


def fill_cells(hwpx_in, hwpx_out, fills, *, table=0, overwrite=False,
               charpr=None):
    """표 셀을 cellAddr(row, col)로 직접 채운다 — 텍스트 키 없이(오프라인).

    fills: [(row, col, text), ...] — row/col은 `<hp:cellAddr rowAddr colAddr>`
    그대로, 즉 `form_inspect`의 `table_map[...]["cells"][...]["addr"]`가
    보고하는 값이다. 병합 셀의 주소는 좌상단 격자 좌표이며, rowSpan/colSpan이
    덮는 좌표에는 셀이 존재하지 않는다(주소는 연속이 아니다).

    table: 문서 전체 표를 '여는 태그 문서 순서'로 센 색인(기본 0). 중첩 표도
    자기 색인을 갖고, 바깥 표가 항상 먼저다(form_inspect table_map과 동일
    규약 — 같은 스캐너를 쓴다).

    계약:
      - 대상 셀이 비어 있지 않으면 거부(PreeditError). --overwrite에서만 덮어씀.
      - 빈 셀의 표준형 자기닫힘 런 <hp:run charPrIDRef="7"/> 안에 <hp:t>를
        만든다. 런의 charPr은 보존(charpr 인자를 주면 그 id로 덮어씀).
      - 텍스트가 바뀐 문단의 <hp:linesegarray>는 제거(T24).
      - 쓰기 전 수정 멤버 well-formed 검증(실패 시 아무것도 쓰지 않음),
        charpr 재지정 시 T22 dangling-charPr 사후검사.
      - 같은 주소를 두 번 지정하면 오류(조용한 마지막-승리 금지).

    멱등성: 같은 값으로 --overwrite 재실행하면 content-identical.

    반환: {"ok": True, "table": n, "filled": n, "cells":
           [{"addr": [r, c], "hits": 1, "action": "filled"|"overwritten",
             "previous": "…"}, ...]}
    """
    fills = [(int(r), int(c), "" if t is None else str(t)) for r, c, t in fills]
    if not fills:
        raise ValueError("채울 셀이 하나도 없음")
    seen = set()
    for row, col, _t in fills:
        if (row, col) in seen:
            raise PreeditError(f"같은 셀 주소가 중복 지정됨: {row},{col}")
        seen.add((row, col))

    infos, contents = _read_zip(hwpx_in)
    section_names = _section_names(contents)

    index, target_section, target_table, total = 0, None, None, 0
    parsed = {}
    for sname in section_names:
        xml = contents[sname].decode("utf-8")
        tables = scan_tables(xml)
        parsed[sname] = (xml, tables)
        for tbl in tables:
            if index == table:
                target_section, target_table = sname, tbl
            index += 1
    total = index
    if target_table is None:
        raise PreeditError(
            f"표 index={table} 없음 — 문서 전체 표는 {total}개"
            " (form_inspect table_map의 index와 같은 규약)")

    xml, _tables = parsed[target_section]
    known = sorted(c["addr"] for c in target_table["cells"] if c["addr"])
    edits, report = [], []
    for row, col, text in fills:
        cell = find_cell(target_table, row, col)
        if cell is None:
            raise PreeditError(
                f"표 {table}에 cellAddr ({row},{col}) 없음 — 병합 셀이 덮은"
                f" 좌표이거나 오타. 실제 주소 {len(known)}개: {known[:20]}")
        body = xml[cell["body_start"]:cell["body_end"]]
        new_body, previous = _fill_cell_body(
            body, text, overwrite=overwrite, charpr=charpr)
        edits.append((cell["body_start"], cell["body_end"], new_body))
        report.append({
            "addr": [row, col],
            "hits": 0 if new_body == body else 1,
            "action": "overwritten" if previous.strip() else "filled",
            "previous": previous.strip()[:30],
        })

    for start, end, new_body in sorted(edits, reverse=True):
        xml = xml[:start] + new_body + xml[end:]

    data = xml.encode("utf-8")
    modified = set()
    if data != contents[target_section]:
        contents[target_section] = data
        modified.add(target_section)

    _assert_members_well_formed(contents, modified)
    if charpr is not None:
        header = contents[_header_name(contents)].decode("utf-8")
        for sname in section_names:
            guards.assert_no_dangling_charpr(
                contents[sname].decode("utf-8"), header)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "table": table, "tables_total": total,
            "filled": sum(c["hits"] for c in report), "cells": report}


# ---------------------------------------------------------------------------
# 2) delete_guide_paragraphs — 가이드 charPr 문단 삭제 + T18 보호 가드
# ---------------------------------------------------------------------------

def _guide_charpr_ids(header_xml, color=None, charpr_ids=None):
    """가이드 charPr id 집합 결정.

    color: "#RRGGBB" 정확 일치(대소문자 무시) 또는 "blue"(파랑 계열 휴리스틱 —
    sim/preedit_official.py의 판정식 그대로: b>=128 and b>r+40 and b>g+40).
    charpr_ids: 명시 id 목록(문자/정수 혼용 허용). 둘 다 주면 합집합.
    """
    ids = set(str(i) for i in (charpr_ids or []))
    if color is not None:
        want_hex = None
        if color.lower() != "blue":
            m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", color)
            if not m:
                raise ValueError(f"color는 '#RRGGBB' 또는 'blue': {color!r}")
            want_hex = m.group(1).upper()
        for m in re.finditer(r'<' + NS + r':charPr\b[^>]*\bid="(\d+)"[^>]*?>',
                             header_xml):
            cm = re.search(r'textColor="#?([0-9A-Fa-f]{6})"', m.group(0))
            if not cm:
                continue
            hexval = cm.group(1).upper()
            if want_hex is not None:
                if hexval == want_hex:
                    ids.add(m.group(1))
            else:
                r, g, b = (int(hexval[i:i + 2], 16) for i in (0, 2, 4))
                if b >= 128 and b > r + 40 and b > g + 40:
                    ids.add(m.group(1))
    return ids


def _para_runs(p_xml):
    """문단 내 런 목록 [(match, cid|None, body_text)] — 자기닫힘 런 포함."""
    out = []
    for m in RUN_RE.finditer(p_xml):
        attrs = m.group(2)
        body = m.group(3) or ""
        cm = re.search(r'\bcharPrIDRef="(\d+)"', attrs)
        cid = cm.group(1) if cm else None
        text = _strip_tags("".join(
            t for _o, t, _c in T_FULL_RE.findall(body)))
        out.append((m, cid, text))
    return out


def delete_guide_paragraphs(hwpx_in, hwpx_out, *, color=None, charpr_ids=None):
    """가이드 charPr을 참조하는 top-level 문단을 삭제(전부 가이드), 혼합 문단은
    가이드 런만 제거. 보호 문단(T18: guards.is_protected_para — 표/secPr/ctrl,
    추가로 그림 등 개체 문단)은 절대 건드리지 않고 protected_skipped로 센다.

    whitespace 규약(결함 클래스 수정): 공백뿐인 런은 텍스트 런으로 치지
    않는다 — 가이드 문단에 공백만 담은 비가이드 런이 섞여 있어도 '혼합'으로
    오판해 삭제를 놓치지 않는다.

    표 셀 내부 문단은 top-level이 아니므로 구조적으로 후보에서 제외
    (초록 표 등 양식 구조 보존 — sim의 in_tbl 배제와 동등).

    이 함수는 <hp:t>를 재작성하지 않는다 — 런 전체 스팬만 제거하므로
    자기닫힘 <hp:t/>를 새로 만들지 않는다(양식 원본에 이미 있는 <hp:t/>는
    유효한 XML이며 그대로 통과). 사후 불변식: 수정된 XML 멤버는 쓰기 전
    well-formed 검증 통과(실패 시 PreeditError, 출력 미작성).

    stale-lineseg(P0): 혼합 문단에서 가이드 런을 걷어내면 문단 텍스트가
    바뀌므로 그 문단의 <hp:linesegarray>도 제거한다(한컴이 열 때 재계산).
    통째로 삭제되는 문단은 lineseg째 사라지니 해당 없음. 건드리지 않은
    문단의 linesegarray는 바이트 그대로.

    반환: {"ok": True, "deleted": n, "protected_skipped": n,
           "mixed_runs_removed": n, "guide_charpr_ids": [...]}
    """
    if color is None and not charpr_ids:
        raise ValueError("color 또는 charpr_ids 중 최소 하나 필요")

    infos, contents = _read_zip(hwpx_in)
    header_xml = contents[_header_name(contents)].decode("utf-8")
    guide = _guide_charpr_ids(header_xml, color=color, charpr_ids=charpr_ids)

    deleted = protected_skipped = mixed_runs_removed = 0
    modified = set()

    for sname in _section_names(contents):
        original = contents[sname]
        xml = original.decode("utf-8")
        paras = _find_paragraphs(xml)
        # 뒤에서부터 편집해야 앞쪽 스팬 오프셋이 안 흔들린다.
        for start, end, p_xml in reversed(paras):
            # T18 — 보호 판정을 런 분석보다 먼저: 표/secPr/ctrl/개체 문단은
            # 절대 불가침. 가이드 charPr을 (셀 내부 포함) 참조하면 skipped로
            # 센다(초록 표처럼 가이드 텍스트를 품은 표의 보존을 보고).
            if guards.is_protected_para(p_xml) or OBJECT_TAG_RE.search(p_xml):
                used = set(re.findall(r'\bcharPrIDRef="(\d+)"', p_xml))
                if used & guide:
                    protected_skipped += 1
                continue
            runs = _para_runs(p_xml)
            text_runs = [(cid, t) for _m, cid, t in runs if t.strip()]
            guide_text = [1 for cid, _t in text_runs if cid in guide]
            if not guide_text:
                continue
            if len(guide_text) == len(text_runs):
                xml = xml[:start] + xml[end:]  # 전부 가이드 → 문단 삭제
                deleted += 1
            else:
                # 혼합 → 가이드 런만 제거(텍스트 없는 가이드 런 포함, 정규화)
                new_p = p_xml
                removed_here = 0
                for m, cid, _t in reversed(runs):
                    if cid in guide:
                        new_p = new_p[:m.start()] + new_p[m.end():]
                        removed_here += 1
                if removed_here:
                    # stale-lineseg(P0): 런을 걷어내 텍스트가 바뀐 문단은
                    # 캐시 레이아웃도 제거(비보호 문단 = 개체·중첩 문단
                    # 없음이 보장되므로 조각 전체 strip이 곧 자기 것만 제거).
                    new_p = LINESEG_RE.sub("", new_p)
                    xml = xml[:start] + new_p + xml[end:]
                    mixed_runs_removed += removed_here
        data = xml.encode("utf-8")
        if data != original:
            contents[sname] = data
            modified.add(sname)

    _assert_members_well_formed(contents, modified)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "deleted": deleted,
            "protected_skipped": protected_skipped,
            "mixed_runs_removed": mixed_runs_removed,
            "guide_charpr_ids": sorted(guide, key=int)}


# ---------------------------------------------------------------------------
# 3) normalize_clones — 정규화형 postedit + itemCnt 실측 + T22 사후검사
#
# 위치-해석 발견(form_final2 실사격 감식): 한컴은 charPrIDRef를 id 속성이
# 아니라 charProperties 배열의 '순서'로 해석한다 — id ≠ 위치가 되는 순간
# 참조가 조용히 이웃 def로 미끄러진다. 증거(XML+렌더 4건 전부 일치):
# ref35('20822', 검정 def) → 파랑 렌더, ref36('초록', 검정 def) → 파랑 렌더.
# 원흉은 클론을 src 바로 뒤에 '중간 삽입'하던 옛 postedit 패턴(참조 sim
# 스크립트 계승분) — pos23부터 전부 밀린다. 그래서 이 함수는 클론을 배열
# '끝'에 append하고, 최종 header의 id↔위치 불일치를 결과에 보고한다.
# 새 id는 반드시 '현재 def 개수'(= 최종 위치)로 고를 것.
# ---------------------------------------------------------------------------

FIELD_CTRL_RE = re.compile(
    r'<' + NS + r':(ctrl|secPr|fieldBegin|fieldEnd)\b')


def _repoint_text_runs(fragment, to_id):
    """fragment 안 텍스트 런의 charPrIDRef를 to_id로 재지정.

    텍스트 런 = 비공백 텍스트가 있고 개체(표/그림/수식 등)·컨트롤·필드
    태그가 없는 런. 개체/필드 런은 불가침. 이미 to_id인 런은 그대로(멱등).
    반환: (new_fragment, changed_count)
    """
    edits = []
    for m in RUN_RE.finditer(fragment):
        body = m.group(3) or ""
        text = _strip_tags("".join(
            t for _o, t, _c in T_FULL_RE.findall(body)))
        if not text.strip():
            continue
        if OBJECT_TAG_RE.search(body) or FIELD_CTRL_RE.search(body):
            continue  # 개체/필드 런은 건드리지 않는다
        open_m = re.match(r'<' + NS + r':run\b[^>]*?/?>', m.group(0))
        old_open = open_m.group(0)
        cm = re.search(r'\bcharPrIDRef="(\d+)"', old_open)
        if cm and cm.group(1) == str(to_id):
            continue  # 이미 목표 — 멱등
        if cm:
            new_open = (old_open[:cm.start(1)] + str(to_id)
                        + old_open[cm.end(1):])
        else:
            new_open = _tag_set_attr(old_open, "charPrIDRef", str(to_id))
        edits.append((m.start(), m.start() + open_m.end(), new_open))
    for s, e, new_open in reversed(edits):
        fragment = fragment[:s] + new_open + fragment[e:]
    return fragment, len(edits)


def _scope_repoint_paragraph(p_xml, to_id, anchor_norm):
    """문단 하나(중첩 셀 문단 재귀)에 스코프 재지정 적용.

    문단 '자신의' 텍스트(중첩 문단 밖 gap의 런들)가 anchor를 포함하면
    (공백 전부 제거 후 부분일치 — 분할 런·공백 런에 관용) 자기 gap의
    모든 텍스트 런을 to_id로 재지정한다. 중첩 문단은 각자 판단(표를 담은
    바깥 문단의 own text에는 셀 텍스트가 포함되지 않으므로 과잉 매치 없음).
    텍스트는 바꾸지 않으므로 linesegarray는 건드릴 필요가 없다(stale-lineseg
    조건 아님 — 색만 바뀌고 메트릭 불변).
    반환: (new_xml, paragraphs_hit, runs_changed)
    """
    open_m = P_OPEN_RE.match(p_xml)
    if not open_m:
        return p_xml, 0, 0
    close_idx = p_xml.rfind("</")
    open_tag = p_xml[:open_m.end()]
    inner = p_xml[open_m.end():close_idx]
    close_tag = p_xml[close_idx:]

    nested = _find_paragraphs(inner)
    gaps, nested_out, last = [], [], 0
    paras_hit = runs_changed = 0
    for start, end, np_xml in nested:
        gaps.append(inner[last:start])
        nx, ph, rc = _scope_repoint_paragraph(np_xml, to_id, anchor_norm)
        nested_out.append(nx)
        paras_hit += ph
        runs_changed += rc
        last = end
    gaps.append(inner[last:])

    own_text = "".join(
        _strip_tags("".join(t for _o, t, _c in T_FULL_RE.findall(g)))
        for g in gaps)
    if anchor_norm in re.sub(r"\s+", "", own_text):
        paras_hit += 1
        new_gaps = []
        for g in gaps:
            g2, rc = _repoint_text_runs(g, to_id)
            runs_changed += rc
            new_gaps.append(g2)
        gaps = new_gaps

    out = []
    for i, nx in enumerate(nested_out):
        out.append(gaps[i])
        out.append(nx)
    out.append(gaps[-1])
    return open_tag + "".join(out) + close_tag, paras_hit, runs_changed

def _tag_set_attr(tag, name, value):
    """여는 태그 문자열의 속성을 치환(없으면 '>' 또는 '/>' 직전에 삽입)."""
    m = re.search(r'\b' + re.escape(name) + r'\s*=\s*(["\'])(.*?)\1', tag)
    if m:
        q = m.group(1)
        return tag[:m.start()] + f'{name}={q}{value}{q}' + tag[m.end():]
    if tag.endswith('/>'):
        return tag[:-2] + f' {name}="{value}"/>'
    return tag[:-1] + f' {name}="{value}">'


def _charpr_block(header_xml, cpr_id, start_at=0):
    """id=cpr_id인 charPr def 블록 (start, end, block) — 자기닫힘/자식형 모두.

    없으면 None. charPr은 중첩되지 않으므로 열림 뒤 첫 닫힘이 곧 짝이다.
    """
    m = re.search(r'<' + NS + r':charPr\b[^>]*\bid="'
                  + re.escape(str(cpr_id)) + r'"[^>]*?(/?)>',
                  header_xml[start_at:])
    if not m:
        return None
    open_start = start_at + m.start()
    open_end = start_at + m.end()
    if m.group(1) == "/":
        return open_start, open_end, header_xml[open_start:open_end]
    close = re.search(r'</' + NS + r':charPr>', header_xml[open_end:])
    if close is None:
        raise PreeditError(f"charPr id={cpr_id} 블록의 닫는 태그 없음 — 구조 이상")
    end = open_end + close.end()
    return open_start, end, header_xml[open_start:end]


def normalize_clones(hwpx_in, hwpx_out, clones=None, *, clone_attrs=None,
                     repoints=None, scope_repoints=None):
    """정규화형 charPr 클론 postedit — sim/postedit_byline_black.py의 패턴 승계.

    절차(멱등):
      1) new_id를 가진 기존 def를 **전부** 제거(중복 클론 정리),
      2) 각 (src_id, new_id)마다 src def를 복제해 id 치환 + clone_attrs 적용,
         charProperties 배열 **끝에** 정확히 하나 append. (src 바로 뒤 중간
         삽입이던 참조 sim 패턴은 id↔위치 desync의 원흉 — 한컴은
         charPrIDRef를 id 속성이 아니라 배열 위치로 해석한다. form_final2
         감식: ref35/36이 검정 def를 가리키는데 파랑으로 렌더 — 4개 관측
         전부 위치-해석과 일치, id-해석과 모순. 새 id는 반드시 현재 def
         개수(= append 후 위치)로 고를 것.)
      3) charProperties itemCnt를 실측(charPr 요소 수)으로 재계산,
      4) repoints: (from_id, to_id, text) — charPrIDRef=from_id 런 중 런 텍스트가
         strip-비교로 text와 같은 것을 to_id로 재지정(text=None이면 전부).
         whitespace-tolerant — trailing/leading 공백이 있어도 매칭(결함 클래스
         수정). 0건이어도 오류 아님(2회차 실행에서 이미 재지정된 상태가 정상).
         repoint는 런 텍스트를 편집하지 않는다(여는 태그의 charPrIDRef만) —
         linesegarray는 건드리지 않는다(stale-lineseg 조건 아님). 단, 클론이
         글자 크기/폰트 등 메트릭을 바꾸면 레이아웃이 낡을 수 있다 — 색
         전환(#0000FF→#000000) 용도로만 쓸 것.
      4b) scope_repoints: (to_id, anchor) — anchor 텍스트를 (공백 전부 제거
         후 부분일치로) '자신의' 런 텍스트에 담은 문단을 전부 찾아, 그 문단
         안 모든 텍스트 런을 to_id로 재지정한다. 분할 런 대응(저자표의
         '학번 런 + 이름 런'처럼 한 문단이 여러 charPr 런으로 쪼개진 경우
         전부 검정 클론으로) — 표 셀 문단도 대상. 개체/컨트롤/필드 런은
         불가침. 앵커당 매치 문단 0개면 PreeditError(오타 방지). 매치
         여러 문단 허용 — 문단·런 수를 앵커별로 보고. 텍스트 불변이므로
         linesegarray 제거 불필요(scoped repoint는 stale-lineseg 조건이
         아니다 — 확인됨).
      5) 내장 사후검사 2종 — 실패 시 출력 파일은 쓰지 않는다:
         (a) 수정된 XML 멤버 전부 well-formed(_assert_members_well_formed,
             실패 시 PreeditError — 실전 사고: 자기닫힘 <hp:t/> 손상 →
             한컴 백지 렌더),
         (b) 모든 섹션에 guards.assert_no_dangling_charpr (T22, 실패 시
             AssertionError).

    clones: [(src_id, new_id)] / clone_attrs: 클론 여는 태그에 적용할 속성
    dict(예: {"textColor": "#000000"}) / repoints: [(from_id, to_id, text|None)]
    / scope_repoints: [(to_id, anchor)].

    결과의 id_position_mismatch: 최종 header에서 id ≠ 배열 위치인 def 목록
    (위치-해석 desync 진단 — 비어 있지 않으면 한컴 렌더가 참조를 이웃 def로
    미끄러뜨릴 수 있다. 이미 뒤틀린 파일의 전면 수리는 별도 op: 모든 charPr
    id를 위치로 재번호 + 섹션·스타일의 charPrIDRef 전부 재매핑 — 미구현,
    필요 시 후속 슬라이스).

    반환: {"ok": True, "stale_clones_removed": n, "clones": [[src,new],...],
           "item_cnt": n, "repointed": [{"from":..,"to":..,"text":..,"count":n}],
           "scope_repointed": [{"to":..,"anchor":..,"paragraphs":n,"runs":n}],
           "id_position_mismatch": [{"pos":i,"id":..}, ...]}
    """
    clones = [(str(a), str(b)) for a, b in (clones or [])]
    for src_id, new_id in clones:
        if src_id == new_id:
            raise ValueError(f"src_id == new_id ({src_id}) — 클론이 아님")
    clone_attrs = dict(clone_attrs or {})
    repoints = [(str(f), str(t), x) for f, t, x in (repoints or [])]
    scope_repoints = [(str(t), a) for t, a in (scope_repoints or [])]
    if not clones and not repoints and not scope_repoints:
        raise ValueError("clones/repoints/scope_repoints 중 최소 하나 필요")

    infos, contents = _read_zip(hwpx_in)
    header_name = _header_name(contents)
    header = contents[header_name].decode("utf-8")

    # 1) 기존 클론 전부 제거 (정규화 — 중복이 몇 개든 0개로)
    stale_removed = 0
    for _src, new_id in clones:
        while True:
            blk = _charpr_block(header, new_id)
            if blk is None:
                break
            s, e, _x = blk
            header = header[:s] + header[e:]
            stale_removed += 1

    # 2) 클론을 정확히 하나씩 재생성 — 배열 '끝'에 append (중간 삽입 금지:
    #    id↔위치 desync 생성기였다 — 위치-해석 발견 참조)
    for src_id, new_id in clones:
        if not guards.charpr_id_present(header, src_id):
            raise PreeditError(
                f"클론 원본 charPr id={src_id} 이 header에 없음 (T22 가드)")
        _s, _e, block = _charpr_block(header, src_id)
        open_end = block.find(">") + 1
        open_tag = block[:open_end]
        open_tag = re.sub(r'(\bid\s*=\s*")' + re.escape(src_id) + r'(")',
                          r'\g<1>' + new_id + r'\g<2>', open_tag, count=1)
        for name, value in clone_attrs.items():
            open_tag = _tag_set_attr(open_tag, name, value)
        clone_block = open_tag + block[open_end:]
        cp_close = re.search(r'</' + NS + r':charProperties>', header)
        if cp_close is None:
            raise PreeditError("header에 charProperties 닫는 태그 없음 — 구조 이상")
        header = (header[:cp_close.start()] + clone_block
                  + header[cp_close.start():])

    # 3) itemCnt 실측 재계산
    item_cnt = len(CHARPR_OPEN_RE.findall(header))
    cp_m = CHARPROPERTIES_RE.search(header)
    if cp_m is None:
        raise PreeditError("header에 charProperties 컨테이너 없음 — 구조 이상")
    header = (header[:cp_m.start()]
              + _tag_set_attr(cp_m.group(0), "itemCnt", str(item_cnt))
              + header[cp_m.end():])

    # 4) 본문 런 재지정 (strip-비교, whitespace-tolerant)
    repointed = []
    section_names = _section_names(contents)
    orig_sections = {n: contents[n] for n in section_names}
    for from_id, to_id, text in repoints:
        want = text.strip() if text is not None else None
        count = 0
        for sname in section_names:
            xml = contents[sname].decode("utf-8")
            edits = []
            for m in RUN_RE.finditer(xml):
                attrs = m.group(2)
                cm = re.search(r'\bcharPrIDRef="(\d+)"', attrs)
                if not cm or cm.group(1) != from_id:
                    continue
                if want is not None:
                    body = m.group(3) or ""
                    run_text = _strip_tags("".join(
                        t for _o, t, _c in T_FULL_RE.findall(body))).strip()
                    if run_text != want:
                        continue
                # 여는 태그 안 charPrIDRef만 치환(본문은 건드리지 않음)
                open_m = re.match(r'<' + NS + r':run\b[^>]*?/?>', m.group(0))
                new_open = re.sub(
                    r'(\bcharPrIDRef=")' + re.escape(from_id) + r'(")',
                    r'\g<1>' + to_id + r'\g<2>', open_m.group(0), count=1)
                edits.append((m.start(), m.start() + open_m.end(), new_open))
            for s, e, new_open in reversed(edits):
                xml = xml[:s] + new_open + xml[e:]
                count += 1
            contents[sname] = xml.encode("utf-8")
        repointed.append({"from": from_id, "to": to_id,
                          "text": text, "count": count})

    # 4b) 스코프 재지정 — anchor 문단의 모든 텍스트 런을 to_id로
    scope_repointed = []
    for to_id, anchor in scope_repoints:
        anchor_norm = re.sub(r"\s+", "", str(anchor))
        if not anchor_norm:
            raise ValueError(f"scope 앵커가 비어 있음: {anchor!r}")
        p_total = r_total = 0
        for sname in section_names:
            xml = contents[sname].decode("utf-8")
            out, last = [], 0
            for start, end, p_xml in _find_paragraphs(xml):
                out.append(xml[last:start])
                nx, ph, rc = _scope_repoint_paragraph(p_xml, to_id,
                                                      anchor_norm)
                out.append(nx)
                p_total += ph
                r_total += rc
                last = end
            out.append(xml[last:])
            contents[sname] = "".join(out).encode("utf-8")
        if p_total == 0:
            raise PreeditError(
                f"scope 앵커 매치 문단 0개(오타 의심): {anchor!r}")
        scope_repointed.append({"to": to_id, "anchor": anchor,
                                "paragraphs": p_total, "runs": r_total})

    # id↔위치 진단 — 위치-해석 desync 검출(비어 있어야 정상)
    id_order = re.findall(r'<' + NS + r':charPr\b[^>]*?\bid="(\d+)"', header)
    id_position_mismatch = [
        {"pos": i, "id": cid} for i, cid in enumerate(id_order)
        if int(cid) != i]

    # 5) 내장 사후검사 — 실패 시 출력 미작성:
    #    (a) 수정 멤버 well-formed, (b) 공중 charPr 참조 없음(T22)
    contents[header_name] = header.encode("utf-8")
    modified = {header_name} | {n for n in section_names
                                if contents[n] != orig_sections[n]}
    _assert_members_well_formed(contents, modified)
    for sname in section_names:
        guards.assert_no_dangling_charpr(
            contents[sname].decode("utf-8"), header)

    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "stale_clones_removed": stale_removed,
            "clones": [list(c) for c in clones], "item_cnt": item_cnt,
            "repointed": repointed, "scope_repointed": scope_repointed,
            "id_position_mismatch": id_position_mismatch}


# ---------------------------------------------------------------------------
# CLI — 얇은 래퍼 (원본 비파괴 원칙: --out 필수)
# ---------------------------------------------------------------------------

def _die(msg, code=1):
    sys.stdout.buffer.write(
        (json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n")
        .encode("utf-8"))
    sys.exit(code)


def _emit(result):
    sys.stdout.buffer.write(
        (json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rep = sub.add_parser("replace", help="dict 기반 자리표시자 치환")
    p_rep.add_argument("file")
    p_rep.add_argument("--out", required=True)
    p_rep.add_argument("--map", required=True,
                       help="치환 dict JSON 파일 경로({old: new, ...})")
    p_rep.add_argument("--allow-missing", action="store_true",
                       help="0-hit 키를 오류 대신 0으로 보고(멱등 재실행용)")

    p_fc = sub.add_parser("fill-cells",
                          help="cellAddr(row,col)로 표 셀 채우기(빈 셀 도달 경로)")
    p_fc.add_argument("file")
    p_fc.add_argument("--out", required=True)
    p_fc.add_argument("--table", type=int, default=0,
                      help="표 색인(문서 순서, form_inspect table_map과 동일). 기본 0")
    p_fc.add_argument("--cell", action="append", default=[],
                      metavar="ROW,COL=TEXT",
                      help="채울 셀(반복 가능). ROW/COL은 cellAddr 값")
    p_fc.add_argument("--map",
                      help='셀 JSON 파일({"2,3": "값", ...}) — --cell과 병용 가능')
    p_fc.add_argument("--overwrite", action="store_true",
                      help="비어 있지 않은 셀도 덮어씀(기본은 거부)")
    p_fc.add_argument("--charpr",
                      help="쓰는 런의 charPrIDRef를 이 id로 덮어씀(기본: 보존)")

    p_del = sub.add_parser("delete-guides", help="가이드 charPr 문단 삭제(T18 가드)")
    p_del.add_argument("file")
    p_del.add_argument("--out", required=True)
    p_del.add_argument("--color", help="'#RRGGBB' 정확 일치 또는 'blue'(계열)")
    p_del.add_argument("--charpr-ids", help="명시 id 목록, 쉼표 구분")

    p_nc = sub.add_parser("normalize-clones",
                          help="정규화형 charPr 클론 postedit(T22 사후검사)")
    p_nc.add_argument("file")
    p_nc.add_argument("--out", required=True)
    p_nc.add_argument("--clone", action="append", default=[],
                      metavar="SRC:NEW", help="클론 짝(반복 가능)")
    p_nc.add_argument("--set", action="append", default=[], dest="attrs",
                      metavar="NAME=VALUE",
                      help="클론에 적용할 속성(예: textColor=#000000)")
    p_nc.add_argument("--repoint", action="append", default=[],
                      metavar="FROM:TO:TEXT",
                      help="런 재지정(TEXT 생략 시 전부: FROM:TO)")
    p_nc.add_argument("--repoint-scope", action="append", default=[],
                      metavar="TO:ANCHOR",
                      help="ANCHOR 텍스트를 담은 문단(표 셀 포함)의 모든 "
                           "텍스트 런을 charPr TO로 재지정(분할 런 저자표 "
                           "일괄 검정 전환용, 개체/필드 런은 불가침)")

    args = ap.parse_args(argv)
    if not Path(args.file).exists():
        _die(f"파일 없음: {args.file}", code=2)

    try:
        if args.cmd == "replace":
            mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
            result = replace_placeholders(
                args.file, args.out, mapping,
                on_zero_hits="ignore" if args.allow_missing else "error")
        elif args.cmd == "fill-cells":
            fills = []
            for spec in args.cell:
                addr, sep, value = spec.partition("=")
                row, comma, col = addr.partition(",")
                if not sep or not comma:
                    _die(f"--cell 형식은 ROW,COL=TEXT: {spec!r}", code=2)
                try:
                    fills.append((int(row.strip()), int(col.strip()), value))
                except ValueError:
                    _die(f"--cell의 ROW/COL은 정수: {spec!r}", code=2)
            if args.map:
                cell_map = json.loads(
                    Path(args.map).read_text(encoding="utf-8"))
                if not isinstance(cell_map, dict):
                    _die("--map JSON은 {\"ROW,COL\": \"값\"} 객체여야 함", code=2)
                for addr, value in cell_map.items():
                    row, comma, col = str(addr).partition(",")
                    if not comma:
                        _die(f"--map 키 형식은 \"ROW,COL\": {addr!r}", code=2)
                    try:
                        fills.append((int(row.strip()), int(col.strip()), value))
                    except ValueError:
                        _die(f"--map 키의 ROW/COL은 정수: {addr!r}", code=2)
            if not fills:
                _die("--cell 또는 --map 중 최소 하나 필요", code=2)
            result = fill_cells(args.file, args.out, fills, table=args.table,
                                overwrite=args.overwrite, charpr=args.charpr)
        elif args.cmd == "delete-guides":
            ids = ([i.strip() for i in args.charpr_ids.split(",") if i.strip()]
                   if args.charpr_ids else None)
            result = delete_guide_paragraphs(
                args.file, args.out, color=args.color, charpr_ids=ids)
        else:  # normalize-clones
            clones = []
            for spec in args.clone:
                src, _, new = spec.partition(":")
                if not src or not new:
                    _die(f"--clone 형식은 SRC:NEW: {spec!r}", code=2)
                clones.append((src, new))
            attrs = {}
            for spec in args.attrs:
                name, _, value = spec.partition("=")
                if not name or not value:
                    _die(f"--set 형식은 NAME=VALUE: {spec!r}", code=2)
                attrs[name] = value
            repoints = []
            for spec in args.repoint:
                parts = spec.split(":", 2)
                if len(parts) == 2:
                    repoints.append((parts[0], parts[1], None))
                elif len(parts) == 3:
                    repoints.append((parts[0], parts[1], parts[2]))
                else:
                    _die(f"--repoint 형식은 FROM:TO[:TEXT]: {spec!r}", code=2)
            scope_repoints = []
            for spec in args.repoint_scope:
                to_id, sep, anchor = spec.partition(":")
                if not to_id or not sep or not anchor:
                    _die(f"--repoint-scope 형식은 TO:ANCHOR: {spec!r}", code=2)
                scope_repoints.append((to_id, anchor))
            result = normalize_clones(args.file, args.out, clones,
                                      clone_attrs=attrs, repoints=repoints,
                                      scope_repoints=scope_repoints)
    except (PreeditError, ValueError, AssertionError) as exc:
        _die(str(exc))
    except json.JSONDecodeError as exc:
        _die(f"JSON 파싱 실패: {exc}", code=2)

    _emit(result)
    sys.exit(0)


if __name__ == "__main__":
    main()
