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

T30 사전 점검(fill-cells): "런의 charPr을 보존한다"는 계약은 그 런의 charPr이
본문과 같은 서식일 때만 안전하다. PPS 양식의 (10,2) 셀은 빈 런이 본문과
동일한 charPr + <hh:supscript/>를 지고 있었고, 올바르게 보이는 채우기가
~6.35pt 올려찍힘으로 렌더됐다(nominal height는 그대로이므로 charpr_check도
style_diff도 통과). 그래서 fill-cells는 재지정 id 없이 script_anomaly 런을
채우기를 **거부**한다(exit 3, 셀 주소·이상 charPr·권장 id·넘겨야 할 플래그를
전부 이름 붙여서). 사전에 어느 셀인지 보려면 form_inspect의 table_map
fill_target 셀에 붙는 charpr/script_anomaly/charpr_suggested를 읽으면 된다.

T34 seat-text(주소로 잡는 치환): 양식이 **인쇄해 둔 자리표**(" 우(     -     )",
"20   .    .    .  ~  20   .    .    .   (     개월)", " http://")를 고치려면
문자열 키가 런의 내부 공백까지 정확히 같아야 한다 — 그런데 그 문자열을 얻을
경로가 제품에 없었다(text_preview는 30자 무표시 잘림, 스켈레톤은 anchors에
없음, content_extract는 공백을 접는다). 그래서 정확한 문자열을 **필요 없게**
만든다: replace가 셀 주소로 대상 런을 잡는다(--at-cell / --at-cell-append).

T41 모호한 키(문단 텍스트에도 주소가 있어야 한다): replace의 tier A/B에는
--at-cell과 달리 **위치 한정자가 없었다**. 표준근로계약서 팩은 6종 계약서가
한 파일에 있고 조항 라벨("2. 근 무 장 소 :")이 장마다 똑같이 인쇄돼 있어서,
문서가 안내하던 --map 경로가 형제 5장을 같은 값으로 덮어썼다 — 그리고 그
파괴를 잡는 오프라인 게이트가 없다(라벨은 접두로 살아남으므로 구조 규칙이
전부 통과한다). 그래서 무스코프 키가 두 곳 이상이면 **거부**하고(exit 2,
replace_key_ambiguous) 발생 위치를 전부 이름 붙여 나열한다. 좁히는 형식은
값 객체다 — {"키": {"text": "값", "at_para": N}}(그 문단만) /
{"text": "값", "all_occurrences": true}(정말 전부, 명시적으로).

CLI(얇은 래퍼):
    python preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
                      # MAP 값은 문자열 또는 {"text": …, "at_para": N} /
                      # {"text": …, "all_occurrences": true}
    python preedit.py replace IN.hwpx --out OUT.hwpx [--table 0]     # 주소 키(T34)
                      --at-cell 'ROW,COL[#RUN]=TEXT' ...      # 런 텍스트 전체 교체
                      --at-cell-append 'ROW,COL[#RUN]=TEXT' ...  # 인쇄된 접두 보존
                      [--at-cell-map JSON] [--at-cell-expect 'ROW,COL[#RUN]=부분문자열']
                      [--at-cell-charpr 'ROW,COL[#RUN]=ID']
    python preedit.py fill-cells IN.hwpx --out OUT.hwpx [--table 0]
                      --cell 'ROW,COL=TEXT' ... [--map CELLS.json] [--overwrite]
                      --cell-line 'ROW,COL=TEXT' ...  # 문단 하나씩 쌓기(T39)
                      [--charpr ID]                # 배치 전체(T32)
                      [--charpr-per-cell ROW,COL=ID ...]   # 셀 단위(우선)
                      [--parapr-per-cell ROW,COL=ID ...]   # 문단서식, 셀 단위
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
from xml.sax.saxutils import escape, unescape

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402
import guards  # noqa: E402

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
# T30 어휘(script/scale/offset 프로파일·본문 baseline·차이 판정)는
# form_inspect(사전 점검)·visual_verify(사후 검출)와 **같은 모듈**을 쓴다.
import charpr_script  # noqa: E402


class PreeditError(RuntimeError):
    """선처리 계약 위반(0-hit 키, src charPr 부재 등) — 출력을 쓰기 전에 터진다."""


class ScriptAnomalyError(PreeditError):
    """T30 사전 점검 거부 — 대상 셀의 런 charPr이 본문 baseline과 다르다.

    ``anomalies``: [{addr, charpr, differing, charpr_suggested, …}] — 어느
    셀인지, 어떤 charPr인지, 무엇을 대신 써야 하는지가 전부 들어 있다.
    exit code 3(= '발견', 사용법 오류 아님).
    """

    exit_code = 3

    def __init__(self, anomalies, flag="--charpr-per-cell"):
        self.anomalies = list(anomalies)
        self.flag = flag
        lines, flags = [], []
        for a in self.anomalies:
            # spec: 플래그에 그대로 넣을 대상 표기. fill-cells는 "ROW,COL",
            # --at-cell은 런까지 특정하는 "ROW,COL#RUN" 이다.
            addr = a.get("spec") or f"{a['addr'][0]},{a['addr'][1]}"
            rendered = a.get("rendered_pt_estimate")
            rendered_note = (f", 렌더 추정 ~{rendered}pt"
                             if rendered is not None else "")
            # nominal height는 baseline과 나란히 보여준다 — 코퍼스 실측에서
            # 이상 대상의 런이 1~2pt 간격용 런인 경우가 있었다(본문 10pt).
            # 그건 T30(높이로는 안 보이는 차이)이 아니라 그냥 잘못된 대상이고,
            # 나란히 찍어주지 않으면 "nominal 2.0pt"만 보고는 알 수 없다.
            lines.append(
                f"셀 ({addr}): 런 charPr={a['charpr']}이 본문 baseline"
                f" charPr={a['charpr_suggested']}과"
                f" {'/'.join(a['differing'])}에서 다름"
                f"(nominal {a.get('nominal_height_pt')}pt vs baseline"
                f" {a.get('baseline_height_pt')}pt{rendered_note})")
            flags += [flag, f"{addr}={a['charpr_suggested']}"]
        # 그대로 붙여넣을 수 있는 플래그 목록 — 코퍼스 실측으로 이상 대상이 한
        # 양식에 18개까지 나온다(jeongbo-gonggae-cheongguseo). 셀별 문구를 읽고
        # 손으로 플래그를 조립하게 만들면 사전 점검이 아니라 숙제다.
        self.suggested_flags = flags
        super().__init__(
            "T30 사전 점검 거부: charPr 보존이 곧 '작게/좁게 찍기'인 대상 셀이"
            f" {len(self.anomalies)}개다 — " + " | ".join(lines)
            + ". baseline 서식으로 채우려면 그대로 붙여넣을 것: "
            + " ".join(flags)
            + " (그 셀이 의도적으로 다른 서식이라면 원하는 id를 직접 지정한다)")


class AmbiguousCellRunError(PreeditError):
    """--at-cell 대상 셀에 텍스트 런이 둘 이상 — 어느 런인지 명시해야 한다.

    조용히 '첫 런'을 고르는 것도, '셀 텍스트 전체'를 값으로 밀어버리는 것도
    선택지가 아니다. PPS 양식의 (15,0)은 한 셀 안에 규정 인용문·"년 월 일"
    신청일 줄·"신청인"·"(서명 또는 인)"·"조달청장 귀하"가 각각 자기 런으로
    들어 있는 병합 셀이다 — 첫 런을 고르면 규정 인용문을 지우고, 셀 전체를
    밀면 나머지 다섯 줄을 함께 지운다.

    ``runs``: 그 셀의 모든 텍스트 런과 **정확한** 문자열([{index, text, charpr}]).
    이 목록 자체가 탈출구다 — section XML을 열 이유가 없다.
    exit code 2(사용법: 주소가 덜 특정됐다).
    """

    exit_code = 2

    def __init__(self, addr, runs, flag="--at-cell"):
        self.addr = [addr[0], addr[1]]
        self.runs = [{"index": r["index"], "text": r["text"],
                      "charpr": r["charpr"]} for r in runs]
        self.suggested_flags = [
            x for r in self.runs
            for x in (flag, f"{addr[0]},{addr[1]}#{r['index']}=<TEXT>")]
        listing = " | ".join(f"#{r['index']}={r['text']!r}" for r in self.runs)
        super().__init__(
            f"셀 ({addr[0]},{addr[1]})에 텍스트 런이 {len(self.runs)}개다 —"
            " 어느 런인지 ROW,COL#RUN 으로 지정할 것(조용히 첫 런을 고르거나"
            f" 셀 텍스트 전체를 밀지 않는다): {listing}")


#: 스코프를 붙인 ``replace --map`` 값 객체가 가질 수 있는 멤버 — **합집합**이다.
#: 한 파일이 `preedit replace --map`과 게이트의 `--fill-map`을 동시에 섬긴다(T35).
#: 그래서 양쪽 모두 상대편 멤버를 **받아들이되 자기 멤버만 해석**한다. 게이트
#: 절반은 pipeline/scripts/check_residue.py의 FILL_SCOPE_MEMBERS에 있다 —
#: 한쪽이 상대 멤버를 unknown으로 거부하면 "한 파일" 계약이 깨진다.
MAP_SCOPE_MEMBERS = ("text", "at_para", "all_occurrences", "other_occurrences")

#: preedit이 실제로 해석하는 멤버(나머지는 게이트 소관 — 받아들이고 무시).
_MAP_SCOPE_OWN = ("at_para", "all_occurrences")


class AmbiguousReplaceKeyError(PreeditError):
    """``replace --map`` 키가 문서에서 두 곳 이상에 걸린다 — 어디인지 말해야 한다.

    tier A(런 strip-비교)도 tier B(raw 부분문자열)도 **위치 한정자가 없다**.
    그래서 6종 계약서가 한 파일에 들어 있는 표준근로계약서 팩에서
    ``"2. 근 무 장 소 : "`` 한 키가 5장 전부를 같은 값으로 덮어쓴다 — 그리고
    그 파괴를 잡는 오프라인 도구는 없다(라벨은 접두로 살아남으므로
    clause_block_lost도 clause_text_consumed도 울리지 않는다). 조용히
    '전부'를 고르는 것은 선택지가 아니다.

    ``keys``: [{key, occurrences:[{occurrence, at_para, section, tier,
    matched, para_text, preceded_by, context_before}], ...}] — 몇 번째가 어느
    문단인지, 그 문단의 텍스트와 최근 앞 문단 문맥(variant 제목 포함)까지
    들어 있다. 이 목록 자체가 탈출구다 — section XML을 열 이유가 없다.
    ``suggested_map``: 그대로 붙여넣을 수 있는 map 조각.
    exit code 2(사용법: 키가 덜 특정됐다).
    """

    exit_code = 2

    def __init__(self, keys):
        self.keys = list(keys)
        self.suggested_map = {}
        lines = []
        for row in self.keys:
            occ = row["occurrences"]
            where = " | ".join(
                f"#{o['occurrence']}(at_para={o['at_para']},"
                f" 앞문맥={' ← '.join(o.get('context_before', [])[-4:])[:80]!r})"
                for o in occ)
            lines.append(f"키 {row['key']!r}가 {len(occ)}곳에 걸림: {where}")
            first = occ[0]
            self.suggested_map[row["key"]] = {
                "text": "<VALUE>", "at_para": first["at_para"]}
        super().__init__(
            f"replace --map 키 {len(self.keys)}개가 문서에서 한 곳으로"
            " 좁혀지지 않는다 — 어느 곳인지 값 객체로 말할 것"
            ' ({"키": {"text": "값", "at_para": N}}), 전부를 정말 원하면'
            ' {"text": "값", "all_occurrences": true}로 명시할 것'
            "(조용히 전부 덮어쓰지 않는다): " + " / ".join(lines))


def _split_map_scopes(mapping):
    """``--map`` 을 (값 매핑, 스코프 매핑)으로 분리 + 값 객체 형식 검증.

    값이 문자열/스칼라면 예전과 완전히 동일한 무스코프 키다. 값이 객체면
    ``text``(필수) + :data:`MAP_SCOPE_MEMBERS` 만 허용한다 — 오타를 조용히
    '무스코프'로 읽으면 스코프를 붙였다고 믿는 호출자가 전부 덮어쓴다.
    """
    values, scopes = {}, {}
    for key, value in (mapping or {}).items():
        if not isinstance(value, dict):
            values[key] = value
            continue
        unknown = sorted(set(value) - set(MAP_SCOPE_MEMBERS))
        if unknown:
            raise PreeditError(
                f"--map[{key!r}] 값 객체에 알 수 없는 멤버 {unknown} —"
                f" 허용: {list(MAP_SCOPE_MEMBERS)}")
        if "text" not in value:
            raise PreeditError(
                f'--map[{key!r}] 값 객체에 "text"가 없음'
                ' (스코프만 있고 쓸 값이 없다)')
        values[key] = value["text"]
        scope = {}
        if value.get("all_occurrences"):
            scope["all_occurrences"] = True
        if value.get("at_para") is not None:
            if isinstance(value["at_para"], bool) or \
                    not isinstance(value["at_para"], int):
                raise PreeditError(
                    f"--map[{key!r}]의 at_para는 정수(문단 주소): "
                    f"{value['at_para']!r}")
            scope["at_para"] = value["at_para"]
        if len(scope) > 1:
            raise PreeditError(
                f"--map[{key!r}]에 at_para와 all_occurrences가 함께 있음 —"
                " 하나만 고를 것(주소로 좁히는 것과 전부를 원하는 것은"
                " 서로 다른 의도다)")
        if scope:
            scopes[key] = scope
    return values, scopes


class _ReplaceCtx:
    """치환 1회분 문맥 — 문단 주소 부여 + (스캔 패스에서) 발생 위치 기록.

    ``para_index``(= 값 객체의 ``at_para``)는 이 클래스가 부여한다: 섹션 이름
    사전순 → 각 섹션 안 ``<hp:p>`` 여는 태그 **문서 순서**(바깥 문단 먼저,
    그 안 셀 문단은 그다음)로 0부터 센다. 스캔 패스와 쓰기 패스는 같은 원본
    구조를 같은 순서로 걷기 때문에 두 패스의 번호가 어긋날 수 없다.
    """

    def __init__(self, scopes=None, record=None):
        self.scopes = scopes or {}
        self.record = record          # 스캔 패스만 list, 쓰기 패스는 None
        self.section = None
        self.para_count = 0
        self.last_nonempty = None
        self.recent_nonempty = []

    def next_para(self):
        idx = self.para_count
        self.para_count += 1
        return idx

    def allowed(self, mapping, at_para):
        """이 문단(또는 문단 밖 gap)에서 쓸 수 있는 키만 남긴 매핑."""
        if not self.scopes:
            return mapping
        out = {}
        for key, value in mapping.items():
            scope = self.scopes.get(key)
            if not scope or scope.get("all_occurrences") \
                    or scope.get("at_para") == at_para:
                out[key] = value
        return out

    def logger(self, at_para, para_text):
        """``_apply_tiers`` 에 넘길 기록 콜백(스캔 패스 전용, 아니면 None)."""
        if self.record is None:
            return None
        section, preceded_by = self.section, self.last_nonempty
        context_before = list(self.recent_nonempty[-12:])

        def _log(key, tier, matched):
            self.record.append({
                "key": key, "tier": tier, "matched": matched[:80],
                "section": section, "at_para": at_para,
                "para_text": (para_text or "")[:90] or None,
                "preceded_by": preceded_by,
                "context_before": context_before})
        return _log


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


def _iter_document_paragraphs(xml, base_offset=0):
    """Yield paragraphs in the same depth-first order as replacement.

    ``replace_placeholders`` gives an outer paragraph its ``at_para`` before
    recursing into paragraphs nested in that paragraph's table/cell.  Keep the
    iterator here, next to that implementation, so inspection can bind a
    paragraph address to its actual XML start rather than guessing from a
    legacy regex index.  ``base_offset`` is only used while recursing into a
    paragraph fragment and keeps yielded starts absolute to the section XML.
    """
    for start, end, p_xml in _find_paragraphs(xml):
        absolute_start = base_offset + start
        absolute_end = base_offset + end
        yield absolute_start, absolute_end, p_xml

        open_m = P_OPEN_RE.match(p_xml)
        if not open_m:
            continue
        close_idx = p_xml.rfind("</")
        if close_idx <= open_m.end():
            continue
        inner = p_xml[open_m.end():close_idx]
        yield from _iter_document_paragraphs(
            inner, base_offset + start + open_m.end())


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


def _apply_tiers(text, mapping, hits, log=None):
    """치환 2단(tier A: 런 strip-비교 / tier B: raw 부분문자열)을 문자열
    조각에 적용하고 새 문자열을 돌려준다. hit는 hits dict에 누적.

    ``log``(선택, ``ctx.logger()``)가 주어지면 실제로 고친 스팬마다
    ``log(key, tier, matched)``를 부른다 — 스캔 패스가 "이 키가 어디에 걸리나"
    를 **쓰기와 똑같은 규칙으로** 세는 유일한 경로다(두 경로로 세면 언젠가
    어긋난다).

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
            if log is not None:
                for start, end, _repl in sorted(edits):
                    log(key, "A", unescape(_strip_tags(text[start:end])))
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
                if log is not None:
                    for _ in edits:
                        log(key, "B", unescape(_strip_tags(needle)))
                text, protected = _apply_edits(text, edits, protected)
    return text


def _replace_in_paragraph(p_xml, mapping, hits, ctx):
    """문단 하나에 치환 적용(중첩 셀 문단은 재귀). 자신의 텍스트가 바뀐
    문단만 자기 linesegarray를 제거한다(stale-lineseg P0).

    귀속 규칙: 문단 inner를 '중첩 문단 스팬'과 그 밖의 gap(자기 런·개체
    래퍼 태그·자기 linesegarray)으로 나눈다. <hp:t>는 항상 gap 안에 통째로
    있으므로 gap 치환은 문단 구조를 깨지 않는다. gap이 바뀌면 이 문단
    '자신의' 텍스트가 바뀐 것 — 자기 gap의 linesegarray만 제거하고, 중첩
    문단은 각자 재귀에서 판단한다(바뀌지 않은 문단의 lineseg는 바이트
    그대로 보존 — byte-fidelity).

    ``ctx``가 이 문단의 주소(``at_para``)를 부여한다: 자기 번호를 먼저 받고
    그다음 중첩 문단이 받는다(= 문서 순서). 스코프가 걸린 키는 자기 번호와
    맞을 때만 이 문단에서 쓰인다."""
    open_m = P_OPEN_RE.match(p_xml)
    if not open_m:  # 방어 — _find_paragraphs 조각이면 항상 매치
        return _apply_tiers(p_xml, ctx.allowed(mapping, None), hits,
                            ctx.logger(None, None))
    close_idx = p_xml.rfind("</")
    open_tag = p_xml[:open_m.end()]
    inner = p_xml[open_m.end():close_idx]
    close_tag = p_xml[close_idx:]

    at_para = ctx.next_para()
    nested = _find_paragraphs(inner)
    gaps, last = [], 0
    for start, end, _np_xml in nested:
        gaps.append(inner[last:start])
        last = end
    gaps.append(inner[last:])
    # 자기 텍스트(중첩 셀 문단 제외) — 거부 payload가 "몇 번째 문단"이 아니라
    # "무슨 문단"인지 말할 수 있어야 한다. gap 치환 전 원본에서 읽는다.
    own_text = unescape(_strip_tags("".join(gaps))).strip()
    log = ctx.logger(at_para, own_text)
    if own_text:
        ctx.last_nonempty = own_text
        ctx.recent_nonempty.append(own_text[:90])
        if len(ctx.recent_nonempty) > 12:
            del ctx.recent_nonempty[:-12]

    nested_out = [_replace_in_paragraph(np_xml, mapping, hits, ctx)
                  for _s, _e, np_xml in nested]

    local = ctx.allowed(mapping, at_para)
    new_gaps = [_apply_tiers(g, local, hits, log) for g in gaps]
    if new_gaps != gaps:  # 이 문단 자신의 텍스트가 바뀜 → 캐시 레이아웃 제거
        new_gaps = [LINESEG_RE.sub("", g) for g in new_gaps]

    out = []
    for i, np_new in enumerate(nested_out):
        out.append(new_gaps[i])
        out.append(np_new)
    out.append(new_gaps[-1])
    return open_tag + "".join(out) + close_tag


def _replace_in_section(xml, mapping, hits, ctx):
    """섹션 XML 전체에 문단 단위 치환 적용(문단 밖 영역은 raw tier만).

    문단 밖 영역의 ``at_para``는 None이다 — 주소로 좁힐 수 없는 자리이므로
    스코프가 걸린 키는 거기서 쓰이지 않고, 무스코프 키는 (한 곳이 아니면)
    애초에 거부된다."""
    paras = _find_paragraphs(xml)
    out, last = [], 0
    for start, end, p_xml in paras:
        out.append(_apply_tiers(xml[last:start], ctx.allowed(mapping, None),
                                hits, ctx.logger(None, None)))
        out.append(_replace_in_paragraph(p_xml, mapping, hits, ctx))
        last = end
    out.append(_apply_tiers(xml[last:], ctx.allowed(mapping, None), hits,
                            ctx.logger(None, None)))
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

    모호한 키는 **거부**한다(T41). tier A도 tier B도 위치 한정자가 없어서
    무스코프 키는 문서의 **모든** 발생을 같은 값으로 덮어쓴다 — 6종 계약서가
    한 파일에 들어 있는 표준근로계약서 팩에서는 그게 형제 5장을 조용히
    파괴하는 동작이고, 잡아내는 오프라인 게이트가 없다. 그래서 발생 위치가
    둘 이상인 무스코프 키는 AmbiguousReplaceKeyError(exit 2)로 거부하며,
    거부 payload가 발생 위치를 전부 이름 붙여 나열한다. 좁히는 방법(값 객체):

      {"2. 근 무 장 소 : ": {"text": "…", "at_para": 61}}   # 그 문단만
      {"…": {"text": "…", "all_occurrences": true}}          # 정말 전부

    ``at_para``는 문서 순서 문단 주소(0-based) — ``--at-cell``의 ``ROW,COL``과
    같은 역할을 문단 텍스트에 대해 한다. 값은 거부 payload에서 읽으면 된다.

    반환: {"ok": True, "hits": {key: n}, "occurrences": {key: n},
           "scope": {key: "at_para:N"|"all_occurrences"}}
    ``occurrences``는 스코프를 적용하지 **않았을 때** 그 키가 걸리는 곳의 수다
    (= "hit 수를 예상과 맞춰 보라"는 지침의 기계 판독 형태).
    """
    if on_zero_hits not in ("error", "ignore"):
        raise ValueError(f"on_zero_hits는 'error'|'ignore': {on_zero_hits!r}")
    mapping, scopes = _split_map_scopes(mapping)
    for key in mapping:
        if not str(key).strip():
            raise PreeditError(f"빈(공백뿐인) 키는 치환 불가: {key!r}")

    infos, contents = _read_zip(hwpx_in)

    # 패스 1(스캔) — 아무것도 쓰지 않고, 키마다 원본 위에서 쓰기와 **같은
    # 코드**로 발생 위치를 센다. 스코프 없이 세야 거부 payload가 전부를
    # 나열할 수 있고, at_para가 실제로 존재하는 문단인지도 여기서 검증된다.
    occurrences = _scan_occurrences(contents, mapping)
    _assert_map_keys_unambiguous(occurrences, scopes)

    hits = {key: 0 for key in mapping}
    modified = set()
    ctx = _ReplaceCtx(scopes=scopes)
    for sname in _section_names(contents):
        original = contents[sname]
        ctx.section = sname
        ctx.last_nonempty = None
        ctx.recent_nonempty = []
        xml = _replace_in_section(original.decode("utf-8"), mapping, hits, ctx)
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
    result = {"ok": True, "hits": hits,
              "occurrences": {k: len(v) for k, v in occurrences.items()}}
    if scopes:
        result["scope"] = {
            key: ("all_occurrences" if scope.get("all_occurrences")
                  else f"at_para:{scope['at_para']}")
            for key, scope in scopes.items()}
    return result


def _scan_occurrences(contents, mapping):
    """{key: [{occurrence, at_para, section, tier, matched, para_text,
    preceded_by, context_before}]} — 스코프를 적용하지 않은 전체 발생 목록.

    각 키를 원본에 대해 **독립적으로**, 쓰기 패스와 같은
    ``_replace_in_section``으로 센다(결과 XML은 버린다). 여러 키를 한 복사본에
    차례로 적용하면 앞 키가 뒤 키의 원래 발생을 지워서, 특히 앞 키에 at_para
    스코프가 있을 때 스캔과 실제 쓰기가 서로 다른 문서를 보게 된다. 독립 스캔은
    `occurrences`가 약속한 그대로 "스코프 전 원본에서 이 키가 걸리는 곳"이다.
    원본은 건드리지 않는다(``contents``는 읽기만).
    """
    out = {}
    for key, value in mapping.items():
        record = []
        hits = {key: 0}
        ctx = _ReplaceCtx(record=record)
        for sname in _section_names(contents):
            ctx.section = sname
            ctx.last_nonempty = None
            ctx.recent_nonempty = []
            _replace_in_section(contents[sname].decode("utf-8"),
                                {key: value}, hits, ctx)
        bucket = []
        for row in record:
            entry = {k: v for k, v in row.items() if k != "key"}
            entry["occurrence"] = len(bucket) + 1
            bucket.append(entry)
        out[key] = bucket
    return out


def _assert_map_keys_unambiguous(occurrences, scopes):
    """무스코프 키가 두 곳 이상이면 거부. 스코프 키는 정확히 한 곳으로
    좁혀지는지 검증한다(0곳/여러 곳 모두 사용법 오류)."""
    ambiguous = []
    for key, found in occurrences.items():
        scope = scopes.get(key) or {}
        if scope.get("all_occurrences"):
            continue
        if "at_para" in scope:
            here = [o for o in found if o["at_para"] == scope["at_para"]]
            if len(here) == 1:
                continue
            if not here:
                raise PreeditError(
                    f"--map[{key!r}]의 at_para={scope['at_para']} 문단에 그 키가"
                    f" 없음 — 실제로 걸리는 문단: "
                    f"{sorted({o['at_para'] for o in found})}")
            raise PreeditError(
                f"--map[{key!r}]가 at_para={scope['at_para']} 한 문단 안에서만"
                f" {len(here)}번 걸림 — 문단 주소로는 더 좁힐 수 없다."
                " 키를 더 길게 잡거나(그 문단에서 유일한 문자열),"
                ' all_occurrences: true 로 전부를 명시할 것')
        elif len(found) > 1:
            ambiguous.append({"key": key, "occurrences": found})
    if ambiguous:
        raise AmbiguousReplaceKeyError(ambiguous)


# ---------------------------------------------------------------------------
# 1c) set_runs — (at_para, run) 주소로 런 텍스트를 직접 쓴다 (오프라인)
#
# T112: 양식의 빈칸은 밑줄(괘선)을 그리는 런이고, 값은 그 런 안에 들어가야
# 괘선이 값 아래로 이어진다. 라벨 런에 이어 쓰면 값은 밑줄 없는 런에 앉고
# 괘선 런은 그대로 남아 다음 줄로 밀린다 — A2의 승인된 산출물이 실제로 그렇게
# 렌더됐다.
#
# replace로는 도달할 수 없다(#66, 실측으로 확인): 괘선 런의 텍스트가 공백뿐인
# 경우 잡을 문자열이 없고, 공백뿐인 키는 tier A의 strip-비교에서 '모든 공백뿐인
# 런'에 매치되는 와일드카드가 되어 문단으로 좁혀도 모호하다(주소 문단에도
# 들여쓰기 런이 함께 있으므로). 키 규칙을 완화하는 쪽은 건전하지만 동기가 된
# 자리에 도달하지 못한다 — 그래서 fill_cells가 셀에 대해 한 것과 같이, 구조
# 주소로 쓰는 별개 오퍼레이션이다.
#
# 주소는 form_inspect가 이미 보고하는 것을 그대로 쓴다:
# `--full-text PARA:N`의 `at_para`와 그 안 `runs[].index`(그리고 어느 런이
# 괘선인지는 `runs[].ruled`).
# ---------------------------------------------------------------------------


def _strip_own_linesegarray(p_xml):
    """이 문단 '자신의' linesegarray만 제거(T24) — 중첩 문단 것은 보존.

    `_replace_in_paragraph`와 같은 귀속 규칙이다: 문단 inner를 중첩 문단 스팬과
    그 밖의 gap으로 나누고 gap에서만 지운다. 문단 전체에 sub를 걸면 바뀌지도
    않은 중첩 문단의 캐시된 좌표까지 버리게 되고, 그건 이유 없는
    byte-fidelity 손실이다.
    """
    open_m = P_OPEN_RE.match(p_xml)
    if not open_m:
        return LINESEG_RE.sub("", p_xml)
    close_idx = p_xml.rfind("</")
    inner = p_xml[open_m.end():close_idx]
    out, last = [], 0
    for start, end, nested in _find_paragraphs(inner):
        out.append(LINESEG_RE.sub("", inner[last:start]))
        out.append(nested)
        last = end
    out.append(LINESEG_RE.sub("", inner[last:]))
    return p_xml[:open_m.end()] + "".join(out) + p_xml[close_idx:]


def set_runs(hwpx_in, hwpx_out, sets):
    """런 텍스트를 (at_para, run index) 주소로 직접 쓴다.

    sets: [(at_para, run_index, value), ...]

    계약:
      - 런 오프너는 손대지 않는다 → charPrIDRef 보존이 곧 이 오퍼레이션의
        요점이다(괘선 런에 써야 괘선이 값 아래로 간다).
      - 런의 첫 ``<hp:t>``에 값을 쓰고 나머지 ``<hp:t>``는 비운다. 한 런이
        여러 조각으로 쪼개져 있어도 결과 텍스트는 정확히 값 하나다.
      - ``<hp:t>``가 아예 없는 런(빈 셀의 자기닫힘 런)은 거부한다 — 그것은
        fill_cells의 영역이고, 여기서 <hp:t>를 만들면 두 오퍼레이션이 같은
        구조를 서로 다르게 다루게 된다.
      - 범위를 벗어난 at_para/run index는 거부(문서가 가진 수를 함께 보고).
      - 같은 주소를 두 번 지정하면 거부(조용한 마지막-승리 금지).
      - 텍스트가 바뀐 문단의 ``<hp:linesegarray>``는 제거(T24) — 바뀌지 않은
        문단의 것은 바이트 그대로 보존.
      - 쓰기 전 수정 멤버 well-formed 검증(실패 시 아무것도 쓰지 않는다).

    멱등성: 같은 값으로 재실행하면 content-identical.

    반환: {"ok": True, "written": n, "runs": [{"at_para": N, "run": i,
           "charpr": "19"|None, "previous": "…"}, ...]}
    """
    wanted = {}
    for at_para, run_index, value in sets:
        at_para, run_index = int(at_para), int(run_index)
        if at_para < 0 or run_index < 0:
            raise PreeditError(
                f"주소는 0 이상이어야 한다: at_para={at_para}, run={run_index}")
        if (at_para, run_index) in wanted:
            raise PreeditError(
                f"같은 런 주소가 중복 지정됨: at_para={at_para}, run={run_index}")
        wanted[(at_para, run_index)] = str(value)
    if not wanted:
        raise ValueError("쓸 런이 하나도 없음")

    infos, contents = _read_zip(hwpx_in)
    written, modified, para_total = [], [], 0
    for sname in _section_names(contents):
        xml = contents[sname].decode("utf-8")
        edits = []           # (absolute_start, absolute_end, replacement)
        for p_start, p_end, p_xml in _iter_document_paragraphs(xml):
            at_para = para_total
            para_total += 1
            here = {k: v for k, v in wanted.items() if k[0] == at_para}
            if not here:
                continue
            runs = paragraph_text_runs(p_xml)
            new_p = p_xml
            for (_a, run_index), value in sorted(here.items()):
                if run_index >= len(runs):
                    # 0개는 그 문단이 <hp:t> 없는 자기닫힘 런만 갖는 경우다
                    # (빈 셀의 표준형) — 여기서 <hp:t>를 만들면 fill_cells와
                    # 같은 구조를 서로 다르게 다루게 되므로 그쪽으로 보낸다.
                    # `paragraph_text_runs`가 <hp:t> 없는 런을 애초에 반환하지
                    # 않으므로 이 한 곳이 그 사례의 유일한 출구다.
                    hint = (" — <hp:t>가 없는 런만 있는 문단이다"
                            "(빈 셀의 자기닫힘 런): fill_cells를 쓸 것"
                            if not runs else "")
                    raise PreeditError(
                        f"at_para={at_para}에 run={run_index}이 없음 — "
                        f"텍스트 런 {len(runs)}개{hint}")
                run = runs[run_index]
                spans = sorted(run["t_spans"])
                pieces, last = [], 0
                for i, (s, e) in enumerate(spans):
                    pieces.append(new_p[last:s])
                    pieces.append(escape(value) if i == 0 else "")
                    last = e
                pieces.append(new_p[last:])
                new_p = "".join(pieces)
                written.append({"at_para": at_para, "run": run_index,
                                "charpr": run["charpr"],
                                "previous": run["text"]})
                # 같은 문단에 두 번째 런을 쓰려면 오프셋이 밀렸으므로 다시 읽는다.
                runs = paragraph_text_runs(new_p)
            if new_p != p_xml:
                new_p = _strip_own_linesegarray(new_p)
                edits.append((p_start, p_end, new_p))
        if edits:
            out, last = [], 0
            for start, end, replacement in sorted(edits):
                out.append(xml[last:start])
                out.append(replacement)
                last = end
            out.append(xml[last:])
            contents[sname] = "".join(out).encode("utf-8")
            modified.append(sname)

    unresolved = sorted(k for k in wanted
                        if not any(w["at_para"] == k[0] and w["run"] == k[1]
                                   for w in written))
    if unresolved:
        raise PreeditError(
            f"문서에 없는 문단 주소: {unresolved} — 문단 {para_total}개")
    _assert_members_well_formed(contents, modified)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "written": len(written), "runs": written}


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


def _body_charpr_weights(contents, section_names):
    """charPr id -> 본문 텍스트 글자수. 본문 baseline 선정의 가중치.

    visual_verify가 T30 사후 검출에서 쓰는 것과 **같은 가중치**다
    (charpr_script.iter_runs + 공백 제거 길이) — 채우기 전 양식에는 fill 값이
    아직 없으므로 모든 텍스트 런이 본문이다.
    """
    weights = {}
    for sname in section_names:
        xml = contents[sname].decode("utf-8")
        for cid, text in charpr_script.iter_runs(xml):
            weights[cid] = weights.get(cid, 0) + len(charpr_script.norm(text))
    return weights


def _locate_table(contents, section_names, table):
    """문서 순서 표 색인 → (section 이름, 표 dict, 문서 전체 표 수, section xml).

    `form_inspect` table_map의 index와 **같은 규약**(같은 스캐너, 여는 태그
    문서 순서, 중첩 표도 자기 색인). fill-cells와 replace --at-cell이 이 함수를
    공유하므로 `--table N`이 두 오퍼레이션에서 다른 표를 가리킬 수 없다.
    """
    index, target = 0, None
    for sname in section_names:
        xml = contents[sname].decode("utf-8")
        for tbl in scan_tables(xml):
            if index == table:
                target = (sname, tbl, xml)
            index += 1
    if target is None:
        raise PreeditError(
            f"표 index={table} 없음 — 문서 전체 표는 {index}개"
            " (form_inspect table_map의 index와 같은 규약)")
    sname, tbl, xml = target
    return sname, tbl, index, xml


def _script_baseline(contents, section_names):
    """(header의 charPr script 프로파일, 본문 baseline id, baseline 프로파일).

    T30 사전 점검의 재료. form_inspect(사전 점검 보고)·visual_verify(사후 검출)와
    **같은 모듈·같은 가중치**를 쓴다.
    """
    header_xml = contents[_header_name(contents)].decode("utf-8")
    profiles = charpr_script.profiles_from_header(header_xml)
    baseline_id = charpr_script.body_baseline_id(
        _body_charpr_weights(contents, section_names))
    return profiles, baseline_id, profiles.get(baseline_id)


def _script_anomaly(profile, baseline_profile, baseline_id):
    """런 charPr 하나의 T30 판정. 이상이 없거나 판정 불가면 None.

    반환(이상일 때): {charpr_suggested, differing, nominal_height_pt,
    baseline_height_pt, rendered_pt_estimate} — 호출자가 addr/spec을 붙여
    ScriptAnomalyError에 넘긴다.
    """
    if profile is None or baseline_profile is None:
        return None
    differing = charpr_script.differing_keys(profile, baseline_profile)
    if not differing:
        return None
    return {
        "differing": differing,
        "charpr_suggested": baseline_id,
        "nominal_height_pt": profile.get("height_pt"),
        "baseline_height_pt": baseline_profile.get("height_pt"),
        "rendered_pt_estimate": charpr_script.rendered_pt_estimate(profile),
    }


def _fill_target_paragraph_index(paras):
    """fill_cells가 쓸 문단의 색인(중첩 표를 담지 않은 첫 문단). 없으면 None."""
    return next((i for i, (_s, _e, p) in enumerate(paras)
                 if not TBL_TAG_RE.search(p)), None)


def _fill_slot_indices(paras, target):
    """target에서 시작하는 **연속** 비-중첩표 문단들의 색인(= 쓸 수 있는 자리).

    T39 다문단 채우기의 지형이다. 연속(contiguous)인 것이 핵심 — 기안문
    별지의 본문 셀은 빈 문단 18개 다음에 직인·발신명의를 담은 **중첩 표
    문단**이 오고 그 뒤에 또 빈 문단이 있다. 중첩 표를 건너뛰고 뒤쪽 빈
    문단까지 자리로 세면 본문 한 줄이 발신명의 아래에 찍힌다.
    """
    slots = []
    for i in range(target, len(paras)):
        if TBL_TAG_RE.search(paras[i][2]):
            break
        slots.append(i)
    return slots


def _para_first_run_charpr(p_xml):
    m = RUN_RE.search(p_xml)
    if m is None:
        return None
    cm = re.search(r'\bcharPrIDRef="(\d+)"', m.group(2) or "")
    return cm.group(1) if cm else None


def fill_target_run_charprs(body, lines=1):
    """`lines`개 문단을 채울 때 텍스트가 **실제로 상속할** charPrIDRef 목록.

    문서 순서, 자리마다 한 개(charPr이 없는 자리는 None). 자리가 모자라
    새로 만들 문단은 target 문단의 클론이므로 target의 charPr을 상속한다.
    T30 사전 점검은 이 목록 **전부**를 본다 — 첫 줄만 검사하면 두 번째 줄이
    supscript 클론을 물고 6.35pt 올려찍히는 T30 사고가 한 문단 아래에서
    그대로 재현된다.
    """
    paras = _find_paragraphs(body)
    if not paras:
        return []
    target = _fill_target_paragraph_index(paras)
    if target is None:
        return []
    slots = _fill_slot_indices(paras, target)
    out = [_para_first_run_charpr(paras[i][2]) for i in slots[:lines]]
    if lines > len(slots):                    # 클론은 target 서식을 물려받는다
        out += [_para_first_run_charpr(paras[target][2])] * (lines - len(slots))
    return out


def fill_target_run_charpr(body):
    """이 셀을 채울 때 텍스트가 **실제로 상속할** charPrIDRef. 없으면 None.

    "런의 charPr을 보존한다"는 계약이 구체적으로 어느 런을 뜻하는지가 T30의
    핵심이다 — 빈 셀의 자기닫힘 런 <hp:run charPrIDRef="7"/>이 본문과 같은
    charPr에 <hh:supscript/>만 붙은 클론이면, 올바르게 보이는 채우기가 6.35pt
    올려찍힘으로 렌더된다. form_inspect(사전 점검)는 이 함수를 import해서
    같은 런을 본다 — 두 도구가 '어느 런인가'에서 어긋날 수 없게 하기 위함.

    body: hp:tc의 자식 스팬(중첩 표 제거 전 원본 — 문단 색인이 fill_cells와
    같아야 한다).
    """
    got = fill_target_run_charprs(body, 1)
    return got[0] if got else None


P_OPEN_HEAD_RE = re.compile(r'^<' + NS + r':p\b[^>]*>')


def _set_para_pr(p_xml, parapr):
    """문단 여는 태그의 paraPrIDRef만 바꾼다(그 외 한 바이트도 건드리지 않음).

    양식이 그 셀의 빈 문단에 걸어 둔 문단서식이 **본문용이 아닐 수** 있다 —
    기안문 별지의 본문 셀은 발신명의·직인을 함께 담고 있어서 빈 문단이 전부
    가운데 정렬(paraPr 15)이다. 그대로 채우면 1./가./1) 계층이 전부 가운데로
    모여 들여쓰기가 사라진다. 그 셀에 맞는 id를 운영자가 지정하는 경로다.
    """
    if parapr is None:
        return p_xml
    m = P_OPEN_HEAD_RE.match(p_xml)
    if m is None:
        return p_xml
    return _tag_set_attr(m.group(0), "paraPrIDRef",
                         str(parapr)) + p_xml[m.end():]


def _clone_target_paragraph(template, text_esc, charpr):
    """target 문단을 복제해 한 줄을 담은 **새 문단**을 만든다.

    양식이 예약해 둔 빈 문단이 모자랄 때만 쓴다. 복제 대상은 target 문단
    통째 — 즉 `paraPrIDRef`(들여쓰기·정렬·줄간격)도, 런의 charPr도 양식
    자신의 설계 그대로다. 기본 문단 서식을 새로 지어내면 이어지는 줄만
    다른 들여쓰기로 찍힌다.

    새 문단은 `linesegarray`를 절대 갖지 않는다(T24: 남의 좌표를 물려받은
    캐시 레이아웃 = 겹쳐 찍힘). 한컴이 열 때 재계산한다.
    """
    blank, _changed = _blank_paragraph_text(template)
    blank = LINESEG_RE.sub("", blank)
    return _write_text_into_paragraph(blank, text_esc, charpr)


def _fill_cell_body(body, lines, *, overwrite, charpr, parapr=None):
    """셀 몸통(hp:tc의 자식 스팬)에 `lines`(문단당 한 줄)를 쓴 새 몸통을 만든다.

    자리 배정(T39): 양식이 그 셀에 **이미 예약해 둔** 연속 빈 문단부터 쓰고,
    모자란 만큼만 target 문단을 복제해 마지막으로 쓴 자리 **바로 뒤**에
    끼운다. 예약된 자리를 두고 무조건 새 문단을 만들면 셀이 예약분만큼
    통째로 길어져 표가 자라고 페이지가 늘어난다(기안문 본문 셀 = 빈 문단
    18개). 쓰지 않은 자리는 종전대로 비운다.

    반환: (new_body, current_text, stats). 비어 있지 않은데 overwrite가
    아니면 PreeditError — 라벨 셀 덮어쓰기는 이 엔진에서 사고이지 기능이 아니다.
    """
    current = _fragment_text(body)
    if current.strip() and not overwrite:
        raise PreeditError(
            f"셀이 비어 있지 않음(현재 {current.strip()[:30]!r})"
            " — 덮어쓰려면 --overwrite")

    paras = _find_paragraphs(body)
    if not paras:
        raise PreeditError("셀에 문단(hp:p)이 없음 — 쓸 자리 없음")
    target = _fill_target_paragraph_index(paras)
    if target is None:
        raise PreeditError("셀의 모든 문단이 중첩 표를 담고 있음 — 쓸 자리 없음")

    slots = _fill_slot_indices(paras, target)
    reused = slots[:len(lines)]
    extra = lines[len(reused):]
    line_at = {idx: lines[k] for k, idx in enumerate(reused)}
    last_reused = reused[-1]
    template = paras[target][2]

    out, last = [], 0
    for i, (start, end, p_xml) in enumerate(paras):
        out.append(body[last:start])
        if i in line_at:
            new_p = _set_para_pr(
                _write_text_into_paragraph(p_xml, escape(line_at[i]), charpr),
                parapr)
            changed = True
        else:
            new_p, changed = _blank_paragraph_text(p_xml)
        if changed:
            # T24 stale-lineseg: 텍스트가 바뀐 문단의 캐시 레이아웃은 제거한다.
            # 남기면 한컴이 옛 좌표에 그려 겹쳐 찍힌다(빈 셀의 lineseg는
            # '빈 줄' 좌표라 새 텍스트가 통째로 어긋난다).
            new_p = LINESEG_RE.sub("", new_p)
        out.append(new_p)
        if i == last_reused:
            for line in extra:
                out.append(_set_para_pr(_clone_target_paragraph(
                    template, escape(line), charpr), parapr))
        last = end
    out.append(body[last:])
    stats = {"paragraphs": len(lines),
             "paragraphs_reused": len(reused),
             "paragraphs_created": len(extra)}
    return "".join(out), current, stats


def split_fill_lines(value):
    """채우기 값 하나 → 문단 목록. 다문단 표기를 한 규칙으로 모은다(T39).

    - 리스트/튜플: 원소 하나가 문단 하나(JSON `--map` 값의 배열 형태).
    - 문자열: 개행(\\n, \\r\\n, \\r)으로 나눈다.
    빈 값도 문단 하나(빈 줄)다 — 자리를 지우는 것과 구별한다.
    """
    if isinstance(value, (list, tuple)):
        lines = ["" if v is None else str(v) for v in value]
        return lines or [""]
    text = "" if value is None else str(value)
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def fill_cells(hwpx_in, hwpx_out, fills, *, table=0, overwrite=False,
               charpr=None, charpr_per_cell=None, parapr_per_cell=None):
    """표 셀을 cellAddr(row, col)로 직접 채운다 — 텍스트 키 없이(오프라인).

    fills: [(row, col, value), ...] — row/col은 `<hp:cellAddr rowAddr colAddr>`
    그대로, 즉 `form_inspect`의 `table_map[...]["cells"][...]["addr"]`가
    보고하는 값이다. 병합 셀의 주소는 좌상단 격자 좌표이며, rowSpan/colSpan이
    덮는 좌표에는 셀이 존재하지 않는다(주소는 연속이 아니다).

    value는 문자열(개행이 문단 구분) 또는 문자열 리스트(원소 = 문단)다 —
    `split_fill_lines`가 둘을 같은 문단 목록으로 만든다. 공문 본문은 규정상
    `1.` / `가.` / `1)` / `가)`가 각각 자기 문단이므로 다문단이 정상이고
    한 문단이 예외다(T39).

    table: 문서 전체 표를 '여는 태그 문서 순서'로 센 색인(기본 0). 중첩 표도
    자기 색인을 갖고, 바깥 표가 항상 먼저다(form_inspect table_map과 동일
    규약 — 같은 스캐너를 쓴다).

    charpr: **배치 전체**에 적용되는 charPrIDRef 재지정이다(모든 대상 셀이
    같은 charPr을 공유할 때만 안전 — T32). 셀마다 다른 id가 필요하면
    charpr_per_cell을 쓴다.

    charpr_per_cell: {(row, col): id} — 그 셀에만 적용되는 재지정. charpr보다
    우선한다.

    parapr_per_cell: {(row, col): id} — 그 셀에 **쓰는 문단들**의 paraPrIDRef
    재지정(들여쓰기·정렬·줄간격). 배치 전체 형태는 일부러 두지 않는다(T32의
    교훈: 서식 플래그는 셀 단위여야 한다). 쓰지 않은 문단은 그대로 둔다.

    계약:
      - 대상 셀이 비어 있지 않으면 거부(PreeditError). --overwrite에서만 덮어씀.
      - 빈 셀의 표준형 자기닫힘 런 <hp:run charPrIDRef="7"/> 안에 <hp:t>를
        만든다. 런의 charPr은 보존(charpr/charpr_per_cell을 주면 그 id로 덮어씀).
      - **다문단(T39)**: 값이 여러 줄이면 양식이 그 셀에 예약해 둔 연속 빈
        문단부터 채우고, 모자란 만큼만 target 문단을 복제한다(paraPr·charPr
        = 양식 자신의 설계). 재지정 id는 그 셀의 **모든** 문단에 똑같이
        적용된다.
      - **T30 사전 점검**: 재지정 id가 주어지지 않은 대상 셀에서 **쓰게 될
        문단 전부**의 런이 script_anomaly(본문 baseline과
        supscript/subscript/ratio/relSz/offset이 다름)를 지고 있으면
        ScriptAnomalyError로 거부한다 — '보존'이 6.35pt 올려찍힘을 뜻하는
        셀을 조용히 채우는 것이 T30 사고 그 자체였다.
      - 텍스트가 바뀐 문단의 <hp:linesegarray>는 제거(T24). 새로 만든 문단은
        아예 갖지 않는다.
      - 쓰기 전 수정 멤버 well-formed 검증(실패 시 아무것도 쓰지 않음),
        charPr 재지정 시 T22 dangling-charPr 사후검사.
      - 같은 주소를 두 번 지정하면 오류(조용한 마지막-승리 금지).

    멱등성: 같은 값으로 --overwrite 재실행하면 content-identical(2회차는
    1회차가 만든 문단을 '예약된 자리'로 그대로 다시 쓴다).

    반환: {"ok": True, "table": n, "filled": n, "cells":
           [{"addr": [r, c], "hits": 1, "action": "filled"|"overwritten",
             "previous": "…", "charpr": "9"|None, "paragraphs": n,
             "paragraphs_reused": n, "paragraphs_created": n}, ...]}
    """
    fills = [(int(r), int(c), split_fill_lines(t)) for r, c, t in fills]
    if not fills:
        raise ValueError("채울 셀이 하나도 없음")
    seen = set()
    for row, col, _t in fills:
        if (row, col) in seen:
            raise PreeditError(f"같은 셀 주소가 중복 지정됨: {row},{col}")
        seen.add((row, col))
    per_cell = {(int(r), int(c)): str(v)
                for (r, c), v in (charpr_per_cell or {}).items()}
    para_per_cell = {(int(r), int(c)): str(v)
                     for (r, c), v in (parapr_per_cell or {}).items()}
    for flag, mapping in (("--charpr-per-cell", per_cell),
                          ("--parapr-per-cell", para_per_cell)):
        unknown = sorted(addr for addr in mapping if addr not in seen)
        if unknown:
            raise PreeditError(
                f"{flag} 주소가 채울 셀 목록에 없음: {unknown}"
                " — 오타이거나 --cell/--cell-line/--map을 빠뜨렸다")

    infos, contents = _read_zip(hwpx_in)
    section_names = _section_names(contents)

    target_section, target_table, total, xml = _locate_table(
        contents, section_names, table)
    known = sorted(c["addr"] for c in target_table["cells"] if c["addr"])

    # T30 사전 점검용 재료 — header의 charPr script 프로파일과 본문 baseline.
    # 대상 셀을 하나도 손대기 전에 전부 모아서 한 번에 판정한다(부분 편집 후
    # 중간에 터지는 일이 없게).
    script_profiles, baseline_id, baseline_profile = _script_baseline(
        contents, section_names)

    resolved, anomalies, seen_anomaly = {}, [], set()
    for row, col, lines in fills:
        cell = find_cell(target_table, row, col)
        if cell is None:
            raise PreeditError(
                f"표 {table}에 cellAddr ({row},{col}) 없음 — 병합 셀이 덮은"
                f" 좌표이거나 오타. 실제 주소 {len(known)}개: {known[:20]}")
        explicit = per_cell.get((row, col), charpr)
        resolved[(row, col)] = explicit
        if explicit is not None or baseline_profile is None:
            continue
        # 쓰게 될 문단 **전부**를 본다 — 재사용 자리는 target과 다른 charPr을
        # 지고 있을 수 있고, 그러면 두 번째 줄부터 T30 사고가 그대로 난다.
        for run_charpr in fill_target_run_charprs(
                xml[cell["body_start"]:cell["body_end"]], len(lines)):
            if run_charpr is None or (row, col, run_charpr) in seen_anomaly:
                continue
            found = _script_anomaly(script_profiles.get(run_charpr),
                                    baseline_profile, baseline_id)
            if found:
                seen_anomaly.add((row, col, run_charpr))
                anomalies.append(
                    dict(found, addr=[row, col], charpr=run_charpr))
    if anomalies:
        raise ScriptAnomalyError(anomalies)

    edits, report = [], []
    for row, col, lines in fills:
        cell = find_cell(target_table, row, col)
        cell_charpr = resolved[(row, col)]
        body = xml[cell["body_start"]:cell["body_end"]]
        cell_parapr = para_per_cell.get((row, col))
        new_body, previous, stats = _fill_cell_body(
            body, lines, overwrite=overwrite, charpr=cell_charpr,
            parapr=cell_parapr)
        edits.append((cell["body_start"], cell["body_end"], new_body))
        report.append({
            "addr": [row, col],
            "hits": 0 if new_body == body else 1,
            "action": "overwritten" if previous.strip() else "filled",
            "previous": previous.strip()[:30],
            "charpr": cell_charpr,
            "parapr": cell_parapr,
            **stats,
        })

    for start, end, new_body in sorted(edits, reverse=True):
        xml = xml[:start] + new_body + xml[end:]

    data = xml.encode("utf-8")
    modified = set()
    if data != contents[target_section]:
        contents[target_section] = data
        modified.add(target_section)

    _assert_members_well_formed(contents, modified)
    if any(v is not None for v in resolved.values()) or para_per_cell:
        header = contents[_header_name(contents)].decode("utf-8")
        for sname in section_names:
            sec = contents[sname].decode("utf-8")
            guards.assert_no_dangling_charpr(sec, header)
            if para_per_cell:
                guards.assert_no_dangling_parapr(sec, header)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "table": table, "tables_total": total,
            "filled": sum(c["hits"] for c in report), "cells": report,
            "body_baseline_charpr_id": baseline_id}


# ---------------------------------------------------------------------------
# 1c) replace_at_cells — 주소로 키를 잡는 치환 ('seat text' 클래스, T34)
#
# 3라운드 클린룸에서 **두 티어가 독립적으로** 걸린 마지막 큰 구멍이다. 양식이
# 인쇄해 둔 '자리표'(seat) — " 우(     -     )", " http://",
# "20   .    .    .  ~  20   .    .    .   (     개월)" — 를 고치려면
# `replace`의 문자열 키가 런의 **내부 공백까지** 정확해야 하는데, 그 문자열을
# 제품 안에서 얻을 경로가 없었다:
#   · table_map.text_preview 는 text[:30] 이고 잘림 표시가 없었다 → Sonnet은
#     협업기간 스켈레톤 중간의 "(     개월)" 빈칸을 아예 못 보고 2차 치환을
#     한 번 더 써야 했다,
#   · 스켈레톤은 30자를 넘고 anchors에도 없다,
#   · content_extract는 공백을 접는다.
# 결과: 두 티어 모두 Contents/section0.xml을 손으로 읽었다 — 스킬이 금지한
# 바로 그 접촉이고, Opus는 거기서 키 두 개를 손으로 조립했다.
#
# 근본 수정은 '정확한 문자열을 주는 것'이 아니라 '정확한 문자열을 필요 없게
# 하는 것'이다: 주소(cellAddr + 셀 안 런 색인)로 대상을 잡는다. 주소 규약·
# 스캐너·가드(stale-lineseg, well-formed 불변식, T30 사전 점검, T22 사후검사)는
# fill-cells와 전부 공유한다.
# ---------------------------------------------------------------------------

def _no_ws(text):
    """공백 전부 제거 — --at-cell-expect의 비교 정규화.

    운영자는 자리표의 정확한 공백을 볼 수 없다(그게 T34의 전제다). 그러니
    **편집**은 주소로 하고, **사전조건**은 공백에 관용적으로 본다:
    `--at-cell-expect 4,3='우(-)'` 가 " 우(     -     )" 에 맞아야 한다.
    `_scope_repoint_paragraph`의 anchor 매칭과 같은 정규화다.
    """
    return re.sub(r"\s+", "", text)


_PARA_XML_TAG_RE = re.compile(
    r'<(?P<close>/)?(?P<prefix>' + NS + r'):(?P<local>[A-Za-z0-9]+)\b'
    r'(?P<attrs>[^>]*?)(?P<self>/)?>', re.S)


def paragraph_text_runs(p_xml):
    """Return the outer paragraph's text runs, excluding nested paragraphs.

    A valid HWPX run may wrap a table (and therefore nested ``hp:p``
    elements), with more ``hp:t`` children after that table.  Fragmenting the
    paragraph around nested paragraphs loses the run opener and its
    ``charPrIDRef``.  Instead, walk the local XML while carrying the active
    run frame across nested elements.  Only text whose paragraph depth is the
    outer paragraph's depth is attributed to that run; nested paragraph text
    is ignored.  One returned record therefore preserves one run's identity
    and concatenates its own ``hp:t`` segments in document order.

    The returned run shape matches ``cell_text_runs`` for the fields consumed
    by form inspection.  Offsets are relative to ``p_xml`` because this helper
    receives one paragraph rather than a cell body.
    """
    runs = []
    active_runs = []
    text_frames = []
    paragraph_depth = 0

    def finish_run(frame):
        if frame is None or not frame["t_spans"]:
            return
        spans = frame["t_spans"]
        runs.append({
            "index": len(runs),
            "text": unescape(_strip_tags(
                "".join(p_xml[s:e] for s, e in spans))),
            "charpr": frame["charpr"],
            "para_start": 0,
            "para_end": len(p_xml),
            "open_start": frame["open_start"],
            "open_end": frame["open_end"],
            "t_spans": spans,
        })

    for token in _PARA_XML_TAG_RE.finditer(p_xml):
        is_close = token.group("close")
        local = token.group("local")
        self_closing = bool(token.group("self"))

        if is_close:
            if local == "t" and text_frames:
                owner, capture, start = text_frames.pop()
                if capture and owner is not None:
                    owner["t_spans"].append((start, token.start()))
            elif local == "run" and active_runs:
                finish_run(active_runs.pop())
            elif local == "p":
                paragraph_depth = max(0, paragraph_depth - 1)
            continue

        if local == "p":
            paragraph_depth += 1
        elif local == "run":
            frame = None
            # ``p_xml`` is one paragraph; depth one is its own content.
            # Runs opened deeper belong to a nested paragraph and must not
            # become part of the outer record, even though they are valid XML.
            if paragraph_depth == 1 and not self_closing:
                cm = re.search(
                    r'\bcharPrIDRef\s*=\s*(["\'])(\d+)\1',
                    token.group("attrs") or "")
                frame = {
                    "charpr": cm.group(2) if cm else None,
                    "open_start": token.start(),
                    "open_end": token.end(),
                    "t_spans": [],
                }
            active_runs.append(frame)
        elif local == "t":
            owner = next((frame for frame in reversed(active_runs)
                          if frame is not None), None)
            capture = owner is not None and paragraph_depth == 1
            if not self_closing:
                text_frames.append((owner, capture, token.end()))

        if self_closing:
            if local == "run" and active_runs:
                active_runs.pop()
            elif local == "p":
                paragraph_depth = max(0, paragraph_depth - 1)

    # Well-formed HWPX closes all runs, but sorting protects document order if
    # an unusual nested wrapper causes close-order differences.
    runs.sort(key=lambda row: row["open_start"])
    for index, row in enumerate(runs):
        row["index"] = index
    return runs


def cell_text_runs(body):
    """셀 몸통(hp:tc의 자식 스팬)의 '자기' 텍스트 런 목록 — 문서 순서.

    반환: [{index, text, charpr, para_start, para_end, open_start, open_end,
            t_spans:[(s,e), ...]}] — 모든 offset은 body 기준.
      · text  — 그 런의 hp:t 내용을 이어붙여 XML 언이스케이프한 **정확한**
        문자열. 내부 공백을 그대로 보존한다(그게 seat-text의 전부다).
      · t_spans — 짝 있는 <hp:t>의 **내용** 스팬만.

    중첩 표를 담은 문단은 통째로 제외한다(그 표의 셀은 그 표 자신의 색인에
    속한다 — scan_tables 규약, `_fill_cell_body`의 배제와 동일).
    짝 있는 hp:t가 없는 런(빈 셀의 표준형 자기닫힘 런)은 목록에 **없다** —
    거기엔 고칠 텍스트가 없고 그건 fill-cells의 소관이다(T27).

    form_inspect --full-text 가 이 함수를 import해서 같은 색인을 보고한다 —
    보고한 #RUN과 편집이 가리키는 런이 어긋날 수 없게 하기 위함
    (fill_target_run_charpr을 공유하는 것과 같은 이유).
    """
    runs = []
    for p_start, p_end, p_xml in _find_paragraphs(body):
        if TBL_TAG_RE.search(p_xml):
            continue
        for m in RUN_RE.finditer(p_xml):
            inner = m.group(3)
            if inner is None:
                continue                  # 자기닫힘 런 — 채울 자리(T27)
            open_m = RUN_OPEN_RE.match(m.group(0))
            inner_off = p_start + m.start() + open_m.end()
            spans = [(inner_off + tm.start(2), inner_off + tm.end(2))
                     for tm in T_FULL_RE.finditer(inner)]
            if not spans:
                continue                  # hp:t 없음/자기닫힘 hp:t
            cm = re.search(r'\bcharPrIDRef="(\d+)"', m.group(2) or "")
            runs.append({
                "index": len(runs),
                "text": unescape(_strip_tags(
                    "".join(body[s:e] for s, e in spans))),
                "charpr": cm.group(1) if cm else None,
                "para_start": p_start,
                "para_end": p_end,
                "open_start": p_start + m.start(),
                "open_end": p_start + m.start() + open_m.end(),
                "t_spans": spans,
            })
    return runs


def _spec_text(row, col, run_index=None):
    return (f"{row},{col}" if run_index is None
            else f"{row},{col}#{run_index}")


def _edit_cell_runs(body, items):
    """셀 몸통에 런 단위 편집을 적용한 새 몸통.

    items: [{run, text, mode, charpr}] — run은 cell_text_runs 항목.
      text=None 은 '텍스트는 손대지 않고 charPr만 재지정' (멱등 재실행에서
      원본 바이트를 흔들지 않기 위해).
    문단 단위로 묶어 뒤에서부터 적용하고, 텍스트가 바뀐 문단의
    <hp:linesegarray>만 제거한다(T24 stale-lineseg — 건드리지 않은 문단의
    캐시 레이아웃은 바이트 그대로 보존).
    """
    by_para = {}
    for item in items:
        run = item["run"]
        key = (run["para_start"], run["para_end"])
        by_para.setdefault(key, []).append(item)

    out = body
    for (p_start, p_end), group in sorted(by_para.items(), reverse=True):
        p_xml = body[p_start:p_end]
        edits, text_changed = [], False
        for item in group:
            run = item["run"]
            if item["text"] is not None:
                text_changed = True
                esc = escape(str(item["text"]))
                spans = [(s - p_start, e - p_start) for s, e in run["t_spans"]]
                if item["mode"] == "append":
                    # 인쇄된 접두를 남기고 뒤에 이어붙인다(T31의 정상 형태).
                    # 분할 런이면 마지막 hp:t 뒤 — 그게 '끝'이다.
                    s, e = spans[-1]
                    edits.append((s, e, p_xml[s:e] + esc))
                else:
                    # 런 텍스트 전체 교체: 첫 hp:t에 값을 쓰고 나머지를 비운다.
                    # 사이의 탭·제어 요소는 스팬 밖이므로 바이트 그대로 남는다.
                    s, e = spans[0]
                    edits.append((s, e, esc))
                    edits += [(s2, e2, "") for s2, e2 in spans[1:]]
            if item["charpr"] is not None:
                o_s = run["open_start"] - p_start
                o_e = run["open_end"] - p_start
                edits.append((o_s, o_e, _tag_set_attr(
                    p_xml[o_s:o_e], "charPrIDRef", str(item["charpr"]))))
        for s, e, repl in sorted(edits, reverse=True):
            p_xml = p_xml[:s] + repl + p_xml[e:]
        if text_changed:
            p_xml = LINESEG_RE.sub("", p_xml)
        out = out[:p_start] + p_xml + out[p_end:]
    return out


def replace_at_cells(hwpx_in, hwpx_out, edits, *, table=0, expects=None,
                     charpr_at_cell=None):
    """표 셀 **주소**로 대상 런을 잡는 치환 — 정확한 문자열 키가 필요 없다(T34).

    edits: [(row, col, run_index|None, text, mode), ...]
      · row/col — `<hp:cellAddr>` 그대로, 즉 `form_inspect` table_map의
        `addr`. fill-cells와 같은 스캐너·같은 색인(`--table N` 동일 규약).
      · run_index — 셀 안 텍스트 런의 0-기반 색인(cell_text_runs 순서 =
        `form_inspect --full-text`의 `runs[].index`). None이면 '셀에 텍스트
        런이 정확히 하나'일 때만 그 런으로 해석하고, 둘 이상이면
        AmbiguousCellRunError로 거부한다(조용히 첫 런을 고르지 않는다).
      · mode — "replace": 그 런의 텍스트 **전체**를 text로 교체.
                "append": 그 런의 텍스트를 **접두로 남기고** 뒤에 text를
                이어붙인다(" http://" → " http://host" — 라벨 필드의 정상
                형태, T31). 둘 중 무엇인지는 항상 명시된다 — 추측하지 않는다.

    다중 hp:t 런(탭 등을 사이에 둔 분할 런): replace는 첫 hp:t에 값을 쓰고
    나머지 hp:t를 비운다(사이 요소는 보존), append는 마지막 hp:t 뒤에 붙인다.

    expects: {(row, col, run_index): 부분문자열} — 편집 전 사전조건. 그 런의
      현재 텍스트가 (양쪽 공백 전부 제거 후) 부분문자열을 포함하지 않으면
      아무것도 쓰지 않고 거부한다. 키는 edits의 대상 표기와 **같은 형태**여야
      한다(edits에 없는 대상을 지정하면 사용법 오류).

    charpr_at_cell: {(row, col, run_index): id} — 그 런의 charPrIDRef 재지정.
      T30 사전 점검을 통과하는 유일한 경로이기도 하다(아래).

    계약(fill-cells와 공유):
      - 대상 셀에 텍스트 런이 없으면(= 진짜 빈 셀) 거부 — fill-cells를 쓸 것(T27).
      - **T30 사전 점검**: 재지정 id 없이 대상 런의 charPr이 본문 baseline과
        supscript/subscript/ratio/relSz/offset에서 다르면 ScriptAnomalyError로
        거부한다(exit 3). 자리표를 고쳐 넣은 값은 사후 게이트
        (visual_verify fill_charpr_script_mismatch)가 같은 다섯 속성으로 보므로,
        사전 점검이 통과시킨 것을 게이트가 막으면 최악이다.
      - 텍스트가 바뀐 문단의 <hp:linesegarray> 제거(T24), 쓰기 전 수정 멤버
        well-formed 검증(실패 시 아무것도 쓰지 않음), charPr 재지정 시 T22
        dangling-charPr 사후검사.
      - 같은 (셀, 런)을 두 번 지정하면 오류(조용한 마지막-승리 금지).

    멱등성: 이미 최종값인 런은 no-op이다 — replace는 텍스트가 이미 같으면,
    append는 이미 그 접미로 끝나면 손대지 않는다(hits 0). 그래서 재실행이
    content-identical이고, append가 값을 두 번 이어붙이지 않는다(T26과 같은 원리).

    반환: {"ok": True, "mode": "at-cell", "table": n, "tables_total": n,
           "replaced": n, "body_baseline_charpr_id": id,
           "cells": [{"addr": [r, c], "run": i, "mode": "replace"|"append",
                      "hits": 0|1, "action": "replaced"|"appended"|"noop",
                      "before": "…", "after": "…", "charpr": id|None}]}
    """
    norm = []
    for row, col, run_index, text, mode in edits:
        if mode not in ("replace", "append"):
            raise ValueError(f"mode는 'replace'|'append': {mode!r}")
        norm.append((int(row), int(col),
                     None if run_index is None else int(run_index),
                     "" if text is None else str(text), mode))
    if not norm:
        raise ValueError("편집할 대상이 하나도 없음")
    if any(t == "" for _r, _c, _i, t, m in norm if m == "append"):
        raise PreeditError("--at-cell-append에 빈 텍스트는 의미 없음")

    specs = {(r, c, i) for r, c, i, _t, _m in norm}
    if len(specs) != len(norm):
        raise PreeditError(
            "같은 대상이 중복 지정됨: "
            + str(sorted(_spec_text(*s) for s in specs)))
    expects = {tuple(k): str(v) for k, v in (expects or {}).items()}
    charpr_at_cell = {tuple(k): str(v)
                      for k, v in (charpr_at_cell or {}).items()}

    infos, contents = _read_zip(hwpx_in)
    section_names = _section_names(contents)
    target_section, target_table, total, xml = _locate_table(
        contents, section_names, table)
    known = sorted(c["addr"] for c in target_table["cells"] if c["addr"])
    _profiles, baseline_id, baseline_profile = _script_baseline(
        contents, section_names)

    # 1패스: 대상 런 해석 + 사전조건 + T30 판정. 아무것도 쓰기 전에 전부 본다
    # (부분 편집 후 중간에 터지는 일이 없게 — fill-cells와 동일 정책).
    #
    # --at-cell-expect / --at-cell-charpr 의 키는 '쓴 그대로'(ROW,COL)와
    # '해석된 것'(ROW,COL#RUN) 둘 다로 맞춘다. 거부 메시지의 suggested_flags는
    # 항상 런까지 특정한 형태(#RUN)로 나오므로, 그걸 그대로 붙여넣어도 원래
    # --at-cell 이 ROW,COL 이었을 때 '편집 목록에 없다'로 튕기면 안 된다 —
    # 붙여넣으면 통하는 것이 suggested_flags의 존재 이유다(T30과 동일 계약).
    plan, resolved_keys, anomalies, accepted = [], set(), [], set()
    for row, col, run_index, text, mode in norm:
        cell = find_cell(target_table, row, col)
        if cell is None:
            raise PreeditError(
                f"표 {table}에 cellAddr ({row},{col}) 없음 — 병합 셀이 덮은"
                f" 좌표이거나 오타. 실제 주소 {len(known)}개: {known[:20]}")
        body = xml[cell["body_start"]:cell["body_end"]]
        runs = cell_text_runs(body)
        if not runs:
            raise PreeditError(
                f"셀 ({row},{col})에 텍스트 런이 없음 — 자리표가 인쇄돼 있지"
                " 않은 '진짜 빈' 셀이다. 채우려면 fill-cells를 쓸 것(T27)")
        if run_index is None:
            if len(runs) > 1:
                raise AmbiguousCellRunError((row, col), runs)
            run = runs[0]
        else:
            if not 0 <= run_index < len(runs):
                raise PreeditError(
                    f"셀 ({row},{col})의 런 색인 #{run_index} 범위 밖 —"
                    f" 텍스트 런은 {len(runs)}개(#0..#{len(runs) - 1})")
            run = runs[run_index]
        key = (row, col, run_index)
        resolved = (row, col, run["index"])
        if resolved in resolved_keys:
            raise PreeditError(
                f"같은 런이 두 번 지정됨: {_spec_text(*resolved)}")
        resolved_keys.add(resolved)
        accepted.update({key, resolved})

        want = expects.get(key, expects.get(resolved))
        if want is not None and _no_ws(want) not in _no_ws(run["text"]):
            raise PreeditError(
                f"사전조건 불일치 {_spec_text(*resolved)}: 기대 {want!r}가"
                f" 현재 런 텍스트 {run['text']!r}에 없음 — 아무것도 쓰지 않음"
                " (주소가 밀렸거나 이미 편집된 파일이다)")

        cell_charpr = charpr_at_cell.get(key, charpr_at_cell.get(resolved))
        if cell_charpr is None:
            found = _script_anomaly(_profiles.get(run["charpr"]),
                                    baseline_profile, baseline_id)
            if found:
                anomalies.append(dict(
                    found, addr=[row, col], charpr=run["charpr"],
                    spec=_spec_text(row, col, run["index"])))
        plan.append({"cell": cell, "addr": (row, col), "run": run,
                     "text": text, "mode": mode, "charpr": cell_charpr})

    for name, given in (("--at-cell-expect", expects),
                        ("--at-cell-charpr", charpr_at_cell)):
        unknown = sorted(_spec_text(*k) for k in given if k not in accepted)
        if unknown:
            raise PreeditError(
                f"{name} 대상이 편집 목록에 없음: {unknown}"
                " — 오타이거나 --at-cell/--at-cell-append를 빠뜨렸다")
    if anomalies:
        raise ScriptAnomalyError(anomalies, flag="--at-cell-charpr")

    # 2패스: 셀별로 묶어 편집. 셀 몸통 스팬은 뒤에서부터 갈아넣는다.
    by_cell, report = {}, []
    for item in plan:
        run, text, mode = item["run"], item["text"], item["mode"]
        if mode == "append":
            after = run["text"] + text
            noop = run["text"].endswith(text)   # 이미 최종값 — 두 번 붙이지 않는다
        else:
            after = text
            noop = run["text"] == text
        report.append({
            "addr": [item["addr"][0], item["addr"][1]],
            "run": run["index"],
            "mode": mode,
            "hits": 0 if noop else 1,
            "action": "noop" if noop
                      else ("appended" if mode == "append" else "replaced"),
            "before": run["text"],
            "after": run["text"] if noop else after,
            "charpr": item["charpr"],
        })
        if noop and item["charpr"] is None:
            continue
        key = (item["cell"]["body_start"], item["cell"]["body_end"])
        # noop인데 charPr 재지정이 있으면 텍스트는 손대지 않는다(text=None) —
        # 같은 값을 다시 escape해 써넣으면 원본 바이트가 흔들릴 수 있다.
        by_cell.setdefault(key, []).append(
            {"run": run, "text": None if noop else text, "mode": mode,
             "charpr": item["charpr"]})

    for (body_start, body_end), items in sorted(by_cell.items(), reverse=True):
        body = xml[body_start:body_end]
        xml = xml[:body_start] + _edit_cell_runs(body, items) + xml[body_end:]

    data = xml.encode("utf-8")
    modified = set()
    if data != contents[target_section]:
        contents[target_section] = data
        modified.add(target_section)

    _assert_members_well_formed(contents, modified)
    if charpr_at_cell:
        header = contents[_header_name(contents)].decode("utf-8")
        for sname in section_names:
            guards.assert_no_dangling_charpr(
                contents[sname].decode("utf-8"), header)
    _write_zip(hwpx_out, infos, contents)
    return {"ok": True, "mode": "at-cell", "table": table,
            "tables_total": total,
            "replaced": sum(c["hits"] for c in report), "cells": report,
            "body_baseline_charpr_id": baseline_id}


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

def _die(msg, code=1, **extra):
    payload = {"ok": False, "error": msg}
    payload.update(extra)
    sys.stdout.buffer.write(
        (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.exit(code)


_AT_ADDR_RE = re.compile(r'^\s*(-?\d+)\s*,\s*(-?\d+)\s*(?:#\s*(\d+)\s*)?$')


def _parse_at_addr(spec_addr, flag):
    """'ROW,COL' 또는 'ROW,COL#RUN' → (row, col, run_index|None)."""
    m = _AT_ADDR_RE.match(spec_addr)
    if not m:
        _die(f"{flag} 주소 형식은 ROW,COL 또는 ROW,COL#RUN: {spec_addr!r}",
             code=2)
    return (int(m.group(1)), int(m.group(2)),
            None if m.group(3) is None else int(m.group(3)))


def _parse_at_specs(specs, flag):
    """['ROW,COL[#RUN]=VALUE', ...] → [((row, col, run), value), ...]."""
    out = []
    for spec in specs:
        addr, sep, value = spec.partition("=")
        if not sep:
            _die(f"{flag} 형식은 ROW,COL[#RUN]=VALUE: {spec!r}", code=2)
        out.append((_parse_at_addr(addr, flag), value))
    return out


def _run_at_cell(args):
    """replace의 주소 키 모드 — CLI 문자열을 replace_at_cells 인자로."""
    edits = []
    for key, value in _parse_at_specs(args.at_cell, "--at-cell"):
        edits.append((key[0], key[1], key[2], value, "replace"))
    for key, value in _parse_at_specs(args.at_cell_append, "--at-cell-append"):
        edits.append((key[0], key[1], key[2], value, "append"))
    if args.at_cell_map:
        raw = json.loads(Path(args.at_cell_map).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _die('--at-cell-map JSON은 {"ROW,COL[#RUN]": 값} 객체여야 함',
                 code=2)
        for addr, value in raw.items():
            key = _parse_at_addr(str(addr), "--at-cell-map")
            if isinstance(value, dict):
                mode = value.get("mode", "replace")
                if mode not in ("replace", "append"):
                    _die("--at-cell-map의 mode는 'replace'|'append': "
                         f"{mode!r}", code=2)
                if "text" not in value:
                    _die(f'--at-cell-map[{addr!r}]에 "text"가 없음', code=2)
                edits.append((key[0], key[1], key[2], value["text"], mode))
            else:
                edits.append((key[0], key[1], key[2], value, "replace"))
    if not edits:
        _die("--at-cell/--at-cell-append/--at-cell-map 중 최소 하나 필요",
             code=2)

    expects, charpr = {}, {}
    for name, specs, sink in (
            ("--at-cell-expect", args.at_cell_expect, expects),
            ("--at-cell-charpr", args.at_cell_charpr, charpr)):
        for key, value in _parse_at_specs(specs, name):
            if key in sink:
                _die(f"{name} 대상이 중복 지정됨: {_spec_text(*key)}", code=2)
            if not str(value).strip():
                _die(f"{name}의 값이 빔: {_spec_text(*key)}", code=2)
            sink[key] = value
    return replace_at_cells(args.file, args.out, edits, table=args.table,
                            expects=expects, charpr_at_cell=charpr)


def _emit(result):
    sys.stdout.buffer.write(
        (json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))


def main(argv=None):
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rep = sub.add_parser(
        "replace",
        help="자리표시자 치환 — 문자열 키(--map) 또는 셀 주소 키(--at-cell)")
    p_rep.add_argument("file")
    p_rep.add_argument("--out", required=True)
    p_rep.add_argument("--map",
                       help="치환 dict JSON 파일 경로({old: new, ...}) —"
                            " 문자열 키 모드. --at-cell*과 함께 쓸 수 없다")
    p_rep.add_argument("--allow-missing", action="store_true",
                       help="0-hit 키를 오류 대신 0으로 보고(멱등 재실행용)."
                            " 문자열 키 모드 전용")
    p_rep.add_argument("--table", type=int, default=0,
                       help="주소 키 모드의 표 색인(문서 순서, form_inspect"
                            " table_map과 동일). 기본 0")
    p_rep.add_argument("--at-cell", action="append", default=[],
                       metavar="ROW,COL[#RUN]=TEXT",
                       help="셀 주소로 대상 런을 잡아 **텍스트 전체를 교체**"
                            "(반복 가능). 양식이 인쇄해 둔 자리표의 정확한"
                            " 내부 공백을 몰라도 된다(T34). 셀에 텍스트 런이"
                            " 둘 이상이면 #RUN으로 지정해야 한다 —"
                            " 색인은 form_inspect --full-text가 보고한다")
    p_rep.add_argument("--at-cell-append", action="append", default=[],
                       metavar="ROW,COL[#RUN]=TEXT",
                       help="인쇄된 접두를 **남기고** 뒤에 이어붙인다"
                            "(' http://' → ' http://host' — 라벨 필드의 정상"
                            " 형태, T31). 반복 가능")
    p_rep.add_argument("--at-cell-map",
                       help='주소 키 JSON({"11,2": "값", "15,0#2": {"text":'
                            ' "…", "mode": "append"}}) — 문자열 값은 replace')
    p_rep.add_argument("--at-cell-expect", action="append", default=[],
                       metavar="ROW,COL[#RUN]=부분문자열",
                       help="편집 전 사전조건(반복 가능): 그 런의 현재 텍스트가"
                            " 이 부분문자열을 포함해야 한다(양쪽 공백 전부"
                            " 제거 후 비교). 불일치면 아무것도 쓰지 않는다")
    p_rep.add_argument("--at-cell-charpr", action="append", default=[],
                       metavar="ROW,COL[#RUN]=ID",
                       help="그 런의 charPrIDRef 재지정(반복 가능)."
                            " T30 사전 점검 거부를 넘기는 경로다")

    p_sr = sub.add_parser(
        "set-runs",
        help="(at_para,run) 주소로 런 텍스트 쓰기 — 괘선 런에 값을 넣는 경로")
    p_sr.add_argument("file")
    p_sr.add_argument("--out", required=True)
    p_sr.add_argument("--run", action="append", default=[],
                      metavar="AT_PARA,RUN=TEXT",
                      help="쓸 런(반복 가능). 주소는 form_inspect"
                           " `--full-text PARA:N`의 at_para와 그 안"
                           " runs[].index다 — 어느 런이 괘선인지는"
                           " runs[].ruled가 말해준다(T112). 런의 charPrIDRef는"
                           " 보존되며, 그게 이 오퍼레이션의 요점이다")
    p_sr.add_argument("--map",
                      help='런 JSON 파일({"18,2": "값"}) — --run과 병용 가능')

    p_fc = sub.add_parser("fill-cells",
                          help="cellAddr(row,col)로 표 셀 채우기(빈 셀 도달 경로)")
    p_fc.add_argument("file")
    p_fc.add_argument("--out", required=True)
    p_fc.add_argument("--table", type=int, default=0,
                      help="표 색인(문서 순서, form_inspect table_map과 동일). 기본 0")
    p_fc.add_argument("--cell", action="append", default=[],
                      metavar="ROW,COL=TEXT",
                      help="채울 셀(반복 가능). ROW/COL은 cellAddr 값."
                           " 값 안의 개행은 문단 구분이다 — 같은 주소를 두 번"
                           " 주는 것은 오류이니, 여러 문단은 --cell-line을 쓸 것")
    p_fc.add_argument("--cell-line", action="append", default=[],
                      dest="cell_line", metavar="ROW,COL=TEXT",
                      help="그 셀의 **문단 하나**(반복 가능, 준 순서가 문단"
                           " 순서). 같은 주소를 여러 번 주면 문단이 쌓인다 —"
                           " 공문 본문의 1./가./1) 계층을 PowerShell에서 개행"
                           " 없이 쓰는 표기다(T39). 같은 주소를 --cell과"
                           " 섞어 쓰는 것은 오류")
    p_fc.add_argument("--map",
                      help='셀 JSON 파일({"2,3": "값", "2,0": ["1. …", "  가. …"]})'
                           " — --cell과 병용 가능. 값이 배열이면 원소 하나가"
                           " 문단 하나, 문자열이면 개행이 문단 구분")
    p_fc.add_argument("--overwrite", action="store_true",
                      help="비어 있지 않은 셀도 덮어씀(기본은 거부)")
    p_fc.add_argument("--charpr",
                      help="쓰는 런의 charPrIDRef를 이 id로 덮어씀(기본: 보존)."
                           " **배치 전체**에 적용된다 — 대상 셀들이 서로 다른"
                           " charPr을 필요로 하면 --charpr-per-cell을 쓸 것(T32)")
    p_fc.add_argument("--charpr-per-cell", action="append", default=[],
                      metavar="ROW,COL=ID",
                      help="그 셀에만 적용되는 charPrIDRef 재지정(반복 가능)."
                           " --charpr보다 우선한다")
    p_fc.add_argument("--parapr-per-cell", action="append", default=[],
                      metavar="ROW,COL=ID",
                      help="그 셀에 **쓰는 문단들**의 paraPrIDRef 재지정"
                           "(들여쓰기·정렬·줄간격, 반복 가능). 양식이 빈 문단에"
                           " 걸어 둔 서식이 본문용이 아닐 때 쓴다 — 기안문"
                           " 별지 본문 셀의 빈 문단은 발신명의와 같은 가운데"
                           " 정렬이라, 그대로 채우면 1./가./1) 들여쓰기가"
                           " 사라진다(T39). 배치 전체 형태는 없다(T32)")

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
            at_cell_given = bool(args.at_cell or args.at_cell_append
                                 or args.at_cell_map)
            if args.map and at_cell_given:
                _die("--map(문자열 키)와 --at-cell*(주소 키)는 함께 쓸 수 없음"
                     " — 두 번 호출해 연결할 것(한 호출 안에서 섞으면 주소"
                     " 오프셋과 치환 결과가 서로를 덮는다)", code=2)
            if not args.map and not at_cell_given:
                _die("--map 또는 --at-cell/--at-cell-append/--at-cell-map 중"
                     " 최소 하나 필요", code=2)
            if at_cell_given:
                result = _run_at_cell(args)
            else:
                mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
                result = replace_placeholders(
                    args.file, args.out, mapping,
                    on_zero_hits="ignore" if args.allow_missing else "error")
        elif args.cmd == "set-runs":
            sets = []
            specs = list(args.run)
            if args.map:
                payload = json.loads(
                    Path(args.map).read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise PreeditError("--map은 {\"at_para,run\": \"값\"} 객체")
                specs += [f"{k}={v}" for k, v in payload.items()]
            for spec in specs:
                addr, sep, value = spec.partition("=")
                if not sep:
                    raise PreeditError(
                        f"--run 형식은 AT_PARA,RUN=TEXT: {spec!r}")
                try:
                    at_para, run_index = (int(x) for x in addr.split(","))
                except ValueError:
                    raise PreeditError(
                        f"--run 주소는 AT_PARA,RUN 두 정수: {addr!r}") from None
                sets.append((at_para, run_index, value))
            result = set_runs(args.file, args.out, sets)
        elif args.cmd == "fill-cells":
            fills, cell_addrs, line_order, line_by = [], set(), [], {}
            for spec in args.cell:
                addr, sep, value = spec.partition("=")
                row, comma, col = addr.partition(",")
                if not sep or not comma:
                    _die(f"--cell 형식은 ROW,COL=TEXT: {spec!r}", code=2)
                try:
                    key = (int(row.strip()), int(col.strip()))
                except ValueError:
                    _die(f"--cell의 ROW/COL은 정수: {spec!r}", code=2)
                cell_addrs.add(key)
                fills.append((key[0], key[1], value))
            # --cell-line은 같은 주소를 여러 번 받는 유일한 채우기 플래그다.
            # --cell이 중복을 오류로 막는 이유(조용한 마지막-승리 금지)는
            # 그대로 두고, '이 셀은 여러 문단'이라는 의도를 표기로 분리한다.
            for spec in args.cell_line:
                addr, sep, value = spec.partition("=")
                row, comma, col = addr.partition(",")
                if not sep or not comma:
                    _die(f"--cell-line 형식은 ROW,COL=TEXT: {spec!r}", code=2)
                try:
                    key = (int(row.strip()), int(col.strip()))
                except ValueError:
                    _die(f"--cell-line의 ROW/COL은 정수: {spec!r}", code=2)
                if key in cell_addrs:
                    _die(f"셀 {key[0]},{key[1]}이 --cell과 --cell-line에 모두"
                         " 지정됨 — 한 쪽으로 통일할 것(두 플래그의 상대 순서는"
                         " 정의되지 않는다)", code=2)
                if key not in line_by:
                    line_order.append(key)
                    line_by[key] = []
                line_by[key] += split_fill_lines(value)
            for key in line_order:
                fills.append((key[0], key[1], line_by[key]))
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
                _die("--cell / --cell-line / --map 중 최소 하나 필요", code=2)
            per_cell, para_cell = {}, {}
            for flag, specs, sink in (
                    ("--charpr-per-cell", args.charpr_per_cell, per_cell),
                    ("--parapr-per-cell", args.parapr_per_cell, para_cell)):
                for spec in specs:
                    addr, sep, cpr = spec.partition("=")
                    row, comma, col = addr.partition(",")
                    if not sep or not comma or not cpr.strip():
                        _die(f"{flag} 형식은 ROW,COL=ID: {spec!r}", code=2)
                    try:
                        key = (int(row.strip()), int(col.strip()))
                    except ValueError:
                        _die(f"{flag}의 ROW/COL은 정수: {spec!r}", code=2)
                    if key in sink:
                        _die(f"{flag} 주소가 중복 지정됨: "
                             f"{key[0]},{key[1]}", code=2)
                    sink[key] = cpr.strip()
            result = fill_cells(args.file, args.out, fills, table=args.table,
                                overwrite=args.overwrite, charpr=args.charpr,
                                charpr_per_cell=per_cell,
                                parapr_per_cell=para_cell)
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
    except AmbiguousCellRunError as exc:
        # exit 2 = 사용법(주소가 덜 특정됐다). 거부 payload가 그 셀의 모든 런과
        # **정확한** 문자열을 들고 있으므로, 이 JSON만 읽고 #RUN을 골라 다시
        # 부르면 된다 — section XML을 열 이유가 없다(그게 T34의 요점).
        _die(str(exc), code=exc.exit_code,
             code_name="at_cell_run_ambiguous",
             addr=exc.addr, runs=exc.runs,
             suggested_flags=exc.suggested_flags)
    except AmbiguousReplaceKeyError as exc:
        # exit 2 = 사용법(키가 덜 특정됐다). payload가 그 키의 모든 발생 위치를
        # at_para·문단 텍스트·최근 앞 문맥까지 붙여 나열하므로, 이 JSON만 읽고
        # at_para를 골라 다시 부르면 된다 — section XML을 열 이유가 없다
        # (at_cell_run_ambiguous와 같은 모양, 같은 이유).
        _die(str(exc), code=exc.exit_code,
             code_name="replace_key_ambiguous",
             keys=exc.keys, suggested_map=exc.suggested_map)
    except ScriptAnomalyError as exc:
        # exit 3 = '발견'. 거부 메시지에 셀 주소·이상 charPr·권장 id·정확히
        # 넘겨야 하는 플래그가 다 들어 있어야 한다 — 이 거부를 읽고 header.xml을
        # 손으로 뒤져야 한다면 사전 점검이 아니다.
        _die(str(exc), code=exc.exit_code,
             code_name="fill_charpr_script_anomaly",
             anomalies=exc.anomalies,
             suggested_flags=exc.suggested_flags)
    except (PreeditError, ValueError, AssertionError) as exc:
        _die(str(exc))
    except json.JSONDecodeError as exc:
        _die(f"JSON 파싱 실패: {exc}", code=2)

    _emit(result)
    sys.exit(0)


if __name__ == "__main__":
    main()
