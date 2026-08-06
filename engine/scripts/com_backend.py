#!/usr/bin/env python3
"""HWP/HWPX COM 백엔드 — pyhwpx로 한글(Hancom Office)을 직접 구동.

Windows + 한컴오피스 설치 환경 전용. 사람이 한글에서 하는 동작을 그대로
재현하므로 기존 양식(글꼴/문단모양/쪽설정)이 자동으로 보존된다.

에이전트 사용 패턴 (stateless 배치 — 매 호출이 열기→편집→저장→닫기):

  1) 구조 파악 (토큰 효율적 — 전체 텍스트 대신 요약 JSON):
     python com_backend.py inspect --file 보고서.hwp

  2) 편집 실행:
     python com_backend.py edit --file 보고서.hwp --ops ops.json \\
         --save-as 보고서_v2.hwpx --export-pdf 검증.pdf

  3) 에이전트가 검증.pdf를 열어 시각 확인 + inspect 재실행으로 회귀 확인.

ops.json 형식 (순서대로 실행):
[
  {"op": "replace_all", "find": "기존문구", "replace": "새문구"},
  {"op": "put_field",   "name": "성명", "value": "홍길동"},
  {"op": "goto_text",   "text": "삽입 위치 앵커 문구"},
  {"op": "find_delete", "text": "지울 문구"},        // 콤마 포함 문구도 안전(분리 안 함)
  {"op": "move",        "to": "doc_end"},            // doc_start|doc_end|line_end
  {"op": "insert_text", "text": "추가 문단\\r\\n"},
  {"op": "insert_equation", "latex": "\\\\frac{1}{2}mv^2"},   // 또는 "hwpeqn": "..."
  {"op": "insert_table", "data": [["헤더1","헤더2"],["a","b"]], "treat_as_char": true},
  {"op": "insert_table", "data": [["a","b","c"]], "col_ratios": [0.2,0.3,0.5], "font_pt": 9},
  {"op": "insert_picture", "path": "C:/img/그래프.png", "width_mm": 80}, // 높이 자동
  {"op": "edit_equation", "index": 0, "latex": "E=mc^2"},     // n번째 기존 수식 교체
  {"op": "set_cell", "table": 0, "row": 1, "col": 2, "text": "값"},
  {"op": "set_char_color", "color": "#000000"},     // 문서 전체 글자색(기본 all)
  {"op": "delete_ctrls", "types": ["tbl", "gso"]},  // 표/그림 삭제(캡션 텍스트는 유지)
  {"op": "collapse_empty_paragraphs"},              // 연속 빈 문단 -> 1빈줄(^n^n^n->^n^n)
  {"op": "delete_blank_after",  "text": "캡션"},    // 캡션 뒤 빈 문단 제거(이미지 밀착)
  {"op": "delete_blank_before", "text": "다음캡션"},// 객체 앞 빈 문단 제거(뒤 캡션 앵커)
  {"op": "insert_picture", "path": "g.png", "width_mm": 125, "own_paragraph": true}, // 자기문단+가운데
  {"op": "insert_equation", "hwpeqn": "E=mc^2", "display": true},  // 자기문단+가운데(display)
  {"op": "set_para_align", "align": "justify", "all": true},       // 본문 양쪽정렬
  {"op": "set_para_align", "align": "center", "anchor": "제목"},   // 특정 문단만
  {"op": "insert_text", "text": "본문\\r\\n", "pt": 10},           // 글자크기 강제(앵커 상속 안 함)
  {"op": "insert_text", "text": "일반 굵게 일반\\r\\n", "pt": 10,   // segments: **굵게** 마크다운 지원
   "segments": [{"text": "일반 ", "bold": false}, {"text": "굵게", "bold": true},
                {"text": " 일반\\r\\n", "bold": false}]},           // (build_report.py가 자동 생성)
  {"op": "insert_blank_before", "text": "I.  서론"},               // 제목 앞 빈 문단 1개 보장
  {"op": "insert_hyperlink", "url": "https://doi.org/..."},        // 진짜 링크 필드(밑줄·색)
  {"op": "page_binding", "mode": "submit"},                        // 제출용 좌우대칭 여백
  {"op": "page_break_before", "text": "I.  서론", "required": false} // 앵커 문단이 새 페이지 시작
]
"""

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eqn import latex_to_hwpeqn, hwpeqn_sanity_check  # noqa: E402


# ---------------------------------------------------------------------------
# Hwp 세션
# ---------------------------------------------------------------------------

def _kill_stale_hwp():
    """잔존 Hwp.exe/HwpApi.exe 프로세스를 강제 종료. opt-in(--kill-stale)에서만 호출.

    이전 세션이 비정상 종료하면 좀비 한글 프로세스가 COM 자동화를 무기한 블록한다
    (문서화된 실패 모드). 파괴적이므로 기본값 아님 — 명시 플래그일 때만 실행한다.
    """
    import subprocess
    for exe in ("Hwp.exe", "HwpApi.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe],
                           capture_output=True, check=False)
        except Exception:
            pass


def open_hwp(filepath, visible=False, kill_stale=False):
    # T25: 입력 파일이 없으면 Hwp가 빈 문서를 조용히 열어 백지 산출물이
    # ok:true로 나간다 — 존재 검사는 COM 기동 전에, 소리나게.
    if not Path(filepath).exists():
        _die(f"입력 파일 없음: {filepath}")
    try:
        from pyhwpx import Hwp
    except ImportError:
        _die("pyhwpx 미설치. 실행: pip install pyhwpx pywin32")
    if kill_stale:
        _kill_stale_hwp()
    hwp = Hwp(visible=visible)  # 보안모듈 자동 등록
    # 모달 다이얼로그(문서 복구/읽기전용 등)가 뜨면 COM 호출이 무한 대기한다.
    # SetMessageBoxMode로 자동 응답시켜 행(hang)을 막는다. API가 다르면 무시.
    try:
        hwp.SetMessageBoxMode(0x00020000)  # 기본 버튼 자동 선택
    except Exception:
        pass
    if filepath:
        hwp.open(str(Path(filepath).resolve()))
    return hwp


def _die(msg, code=2):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)


# ---------------------------------------------------------------------------
# Inspect — 토큰 효율적 구조 요약
# ---------------------------------------------------------------------------

def inspect(hwp, text_chars=600):
    """문서 구조를 작은 JSON으로 요약 (전체 본문 덤프 금지)."""
    info = {"ok": True}

    # 본문 미리보기 (앞부분만)
    try:
        full = hwp.get_text_file("TEXT", "") if hasattr(hwp, "get_text_file") \
            else hwp.GetTextFile("TEXT", "")
        info["text_chars_total"] = len(full)
        info["text_preview"] = full[:text_chars]
    except Exception as e:
        info["text_preview_error"] = str(e)

    # 필드(누름틀) 목록
    try:
        fields = hwp.get_field_list() if hasattr(hwp, "get_field_list") else ""
        if isinstance(fields, str):
            fields = [f for f in fields.replace("\x02", "\n").split("\n") if f]
        info["fields"] = fields
    except Exception:
        info["fields"] = []

    # 컨트롤 인벤토리 (표 / 수식 / 그림)
    tables, equations, pictures = 0, [], 0
    try:
        ctrl = hwp.HeadCtrl
        while ctrl:
            desc = getattr(ctrl, "UserDesc", "")
            cid = getattr(ctrl, "CtrlID", "")
            if cid == "tbl" or desc == "표":
                tables += 1
            elif cid == "eqed" or desc == "수식":
                try:
                    script = ctrl.Properties.Item("String")
                except Exception:
                    script = None
                equations.append({"index": len(equations), "script": script})
            elif cid in ("gso",) or desc in ("그림",):
                pictures += 1
            ctrl = ctrl.Next
    except Exception as e:
        info["ctrl_scan_error"] = str(e)
    info["tables"] = tables
    info["equations"] = equations
    info["pictures"] = pictures

    try:
        info["pages"] = hwp.PageCount
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# 개별 op 구현
# ---------------------------------------------------------------------------

def op_replace_all(hwp, o):
    n = hwp.find_replace_all(o["find"], o["replace"],
                             regex=o.get("regex", False))
    return {"replaced": n}


def op_put_field(hwp, o):
    hwp.put_field_text(o["name"], o["value"])
    return {"field": o["name"]}


def _cursor_para_text(hwp):
    """커서가 있는 문단의 텍스트를 읽는다(커서 위치 보존, 실패 시 None).

    문단 선택(MoveParaBegin→MoveSelParaEnd) 후 get_selected_text로 읽고
    선택 해제·원위치 복원. 읽기 실패는 None을 반환해 호출부가 가드를
    끄도록(구동작 유지) 한다 — 가드 오탐으로 배치를 죽이지 않는다.
    """
    try:
        pos = hwp.get_pos()
        _run(hwp, "MoveParaBegin")
        _run(hwp, "MoveSelParaEnd")
        text = hwp.get_selected_text() if hasattr(hwp, "get_selected_text") else None
        try:
            hwp.Cancel()
        except Exception:
            pass
        hwp.set_pos(*pos)
        return text
    except Exception:
        return None


def op_goto_text(hwp, o):
    hwp.MoveDocBegin()
    found = hwp.find(o["text"]) if hasattr(hwp, "find") else False
    if not found:
        raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
    if o.get("after", True):
        hwp.MoveLineEnd() if o.get("line_end") else hwp.Cancel()
    if o.get("cell_below"):
        # cell_below(T12, kb trouble-table): 앵커가 1열 표의 라벨 셀 전체 텍스트인
        # 경우(예: "요약문" — form_profile table_map에서 classification=static인
        # 라벨 셀), MoveNextParaBegin은 같은 셀 안 유일한 문단이라 no-op되고 T8
        # 가드의 BreakPara도 "같은 셀 안"에서 문단만 쪼갠다 — 라벨 셀 자체가
        # 늘어나며 본문이 라벨 셀에 남는다(음영 배경까지 함께 늘어남). 진짜 목적지는
        # 표의 "다음 행" 셀(같은 열, 별도의 fill_target 셀)이므로 문단 이동이 아니라
        # 표 셀 이동(TableLowerCell)을 써야 한다. next_para의 T8 분기와는 배타적—
        # 이 분기가 성립하면 아래 next_para 처리는 건너뛴다(다른 문제를 겨냥한 가드).
        lower = getattr(hwp, "TableLowerCell", None)
        if not callable(lower):
            raise RuntimeError("cell_below: hwp.TableLowerCell 사용 불가")
        lower()
        _run(hwp, "MoveParaBegin")
        return {"found": True, "cell_below": True}
    if o.get("next_para"):
        # 제목 문단을 쪼개지 않고 다음 문단(양식 안내문) 맨 앞으로 이동한다.
        # 제목 끝에서 \r\n을 넣어 쪼개면 pending 글자크기가 제목에 번져 제목 크기가
        # 바뀐다(15pt 제목이 10pt로). 다음 문단 시작에 본문을 넣으면 제목은 불변.
        _run(hwp, "MoveNextParaBegin")
        # T8 가드(kb trouble-table): 앵커가 표 셀 안 단일 문단(예: '요약문' 라벨)이면
        # MoveNextParaBegin이 no-op되어 커서가 라벨 문단에 남고, 본문이 라벨에
        # 그대로 이어붙는다("요약문영상 속에서…"). 이동 후 현재 문단에 앵커 문구가
        # 아직 있으면 문단 끝에서 BreakPara로 새 문단을 만들어 본문이 새 문단에
        # 들어가게 한다. BreakPara(Run)는 insert_text("\r\n")와 달리 pending
        # 글자크기를 인접 문단에 번지게 하지 않는다(charshape quirk). 문단 텍스트를
        # 읽지 못하면(None) 가드를 끄고 기존 동작을 유지한다.
        cur = _cursor_para_text(hwp)
        if cur is not None and o["text"] in cur:
            _run(hwp, "MoveParaEnd")
            _run(hwp, "BreakPara")
            # T10(kb trouble-table): 새로 쪼갠 문단은 라벨 문단의 가운데정렬
            # paraPr을 상속해(요약문 라벨=CENTER) 삽입될 본문까지 가운데정렬로
            # 렌더된다. 본문은 항상 justify여야 하므로, 쪼갠 직후 새 문단에서
            # 바로 정렬을 교정한다(op_set_para_align과 동일한 _run 메커니즘 재사용).
            _run(hwp, "ParagraphShapeAlignJustify")
            return {"found": True, "t8_break": True}
    return {"found": True}


def op_find_delete(hwp, o):
    """find()로 문구를 선택(콤마 분리 없음)한 뒤 선택분을 삭제.

    find_replace_all은 FindString을 콤마 기준 다중 검색어로 분리하므로 콤마가
    든 안내문/문구 삭제에 부적합하다. find()는 단일 문자열로 매칭하므로 안전.
    """
    n = 0
    while o.get("all", False) or n == 0:
        hwp.MoveDocBegin()
        if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
            break
        hwp.Delete()
        n += 1
        if not o.get("all", False):
            break
    if n == 0 and o.get("required", True):
        raise RuntimeError(f"삭제할 문구를 찾지 못함: {o['text']!r}")
    return {"deleted": n}


def _count_blank_runs(hwp):
    """본문에서 '빈 문단 2개 이상 연속'(개행 3개 이상)의 개수를 센다."""
    try:
        full = hwp.get_text_file("TEXT", "") if hasattr(hwp, "get_text_file") \
            else hwp.GetTextFile("TEXT", "")
    except Exception:
        return 0
    t = full.replace("\r\n", "\n").replace("\r", "\n")
    return len(re.findall(r"\n{3,}", t))


def _count_newlines(hwp):
    """문서 전체 개행(\\n) 총개수 — '런 개수'가 아니라 단조 감소 지표.

    _count_blank_runs는 '연속 빈 문단 런'의 개수를 세므로, 런 하나의 길이가
    (예: 빈 문단 6개 -> 개행 7개) 삭제로 1만 줄어도 런 자체는 여전히 1개라서
    "진전 없음"으로 오판해 반복이 1라운드 만에 멈춘다(실측: delete_blank_before
    all:true가 빈 문단 6개 중 1개만 지우고 중단). 성공적인 빈 문단 삭제는 항상
    개행을 정확히 하나 줄이므로, 개행 총개수는 라운드마다 반드시 감소하는
    단조 지표다 — _repeat_delete_while_progress의 progress 판정에 이 함수를 쓴다.
    """
    try:
        full = hwp.get_text_file("TEXT", "") if hasattr(hwp, "get_text_file") \
            else hwp.GetTextFile("TEXT", "")
    except Exception:
        return 0
    t = full.replace("\r\n", "\n").replace("\r", "\n")
    return t.count("\n")


def _repeat_delete_while_progress(delete_once, count_metric, max_rounds=50):
    """'앵커에 인접한 빈 문단이 없어질 때까지' 반복 삭제하는 순수 루프.

    각 라운드: count_metric()로 전(before) 스냅샷 → delete_once() 1회 실행 →
    count_metric()로 후(after) 스냅샷. after >= before(진전 없음)면 중단.
    max_rounds 도달 시에도 중단(무한루프 가드, all-mode 공통 계약).

    count_metric은 반드시 단조 감소 지표여야 한다 — 호출부는 _count_newlines를
    쓴다(빈 문단 삭제 1회 = 개행 1개 감소, 항상 성립). 이전엔 _count_blank_runs
    ('연속 빈 문단 런' 개수)를 썼는데, 런 하나의 길이가 줄어도(예: 빈 문단 6개
    -> 5개) 런 개수 자체는 그대로 1이라 "진전 없음"으로 오판해 1라운드 만에
    멈췄다(실측: delete_blank_before all:true가 빈 문단 6개 중 1개만 삭제).

    delete_once/count_metric을 주입받아 COM 호출 없이 순수 로직만 테스트 가능
    (op_delete_blank_after/op_delete_blank_before가 COM 클로저를 넘겨 재사용).
    반환: (rounds:int, progressed:bool) — rounds는 실제 delete_once 호출 횟수.
    """
    rounds = 0
    before = count_metric()
    while rounds < max_rounds:
        delete_once()
        rounds += 1
        after = count_metric()
        if after >= before:
            break
        before = after
    return rounds, rounds > 0


def op_collapse_empty_paragraphs(hwp, o):
    """연속 빈 문단을 1개로 줄인다 (^n^n^n -> ^n^n 반복, 0건까지).

    의도적 1빈줄(빈 문단 1개)은 보존된다 — 헤딩/표/그림 앞뒤 구분 공백 유지.

    HWP 문단 끝은 찾기/바꾸기에서 caret 코드 `^n`으로 표현되며 regex=False(리터럴)
    에서만 매칭된다. pyhwpx의 regex=True는 HWP 정규식이 아니라 python re를 본문
    텍스트(\\r\\n)에 적용하는 경로라 `^n`/`\\n` 모두 어긋난다 — 반드시 리터럴 사용.
    find_replace_all 반환값이 불안정하므로 종료는 본문의 '개행 3개 이상' 런 개수로
    판정하고, 한 회차에 줄지 않으면 멈추고 보고한다.
    """
    find = o.get("find", "^n^n^n")
    repl = o.get("replace", "^n^n")
    start = prev = _count_blank_runs(hwp)
    rounds = 0
    while prev > 0 and rounds < 200:
        hwp.find_replace_all(find, repl, regex=False)
        rounds += 1
        cur = _count_blank_runs(hwp)
        if cur >= prev:  # 진전 없음 → 중단
            break
        prev = cur
    return {"rounds": rounds, "blank_runs_before": start,
            "blank_runs_after": prev, "progress": start > prev}


def op_delete_blank_after(hwp, o):
    """앵커 문구가 있는 문단 끝에서 전방 삭제로 바로 뒤 빈 문단(들)을 제거.

    그림 캡션↔이미지처럼 '한 단위'를 밀착시킬 때 사용. count만큼만 문단 끝 마크를
    지우므로(기본 1) 과도 삭제 금지. 캡션 바로 뒤가 이미 본문/이미지면 호출하지 말 것
    (밀착 대상인 단일 빈 문단이 있을 때만 사용).

    "all": true — 앵커 뒤에 인접한 빈 문단이 없어질 때까지 반복 삭제한다(가드:
    최대 50회, 진전 없으면 중단). "required": false면 앵커를 못 찾아도 배치를
    abort하지 않고 {"deleted":0,"found":false}를 반환한다(op_delete_blank_before와
    동일 계약 — m1 감사에서 delete_blank_after만 이 계약을 어기고 있었음, 수정).
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        if o.get("required", True):
            raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
        return {"deleted": 0, "found": False}
    # find가 문구를 선택한 상태. Cancel로 선택을 풀면 커서가 문구 '끝'(문단 끝)에
    # 놓인다. MoveLineEnd는 줄바꿈된 문단에서 첫 시각줄 끝으로 가 문단 중간을
    # 잘라먹으므로 쓰지 않는다.
    hwp.Cancel()
    if o.get("all", False):
        rounds, _ = _repeat_delete_while_progress(
            lambda: hwp.Delete(), lambda: _count_newlines(hwp))
        return {"deleted": rounds, "found": True, "rounds": rounds}
    n = int(o.get("count", 1))
    for _ in range(n):
        hwp.Delete()           # 다음 문단 끝 마크 제거(빈 문단 흡수)
    return {"deleted": n, "found": True, "deleted_breaks": n}


def op_delete_blank_before(hwp, o):
    """앵커 문구가 있는 문단의 '앞' 빈 문단(들)을 제거.

    delete_blank_after의 대칭. 표/객체 바로 앞은 텍스트로 앵커할 수 없으므로,
    뒤따르는 캡션 등을 앵커로 잡아 그 앞의 빈 문단을 줄일 때 쓴다.

    "all": true — 앵커 앞에 인접한 빈 문단이 없어질 때까지 반복 삭제한다(가드:
    최대 50회, 진전 없으면 중단). "required": false 계약은 기존과 동일(변경 없음).
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        # op_find_delete와 동일하게 required 플래그를 존중한다. 선택(required:false)
        # 앵커가 없어도 배치 전체를 abort하지 않고 건너뛴다(부분 편집 잔존 방지).
        if o.get("required", True):
            raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
        return {"deleted": 0, "found": False, "deleted_breaks": 0, "skipped": True}
    hwp.Cancel()
    run = getattr(hwp, "Run", None) or (lambda a: hwp.HAction.Run(a))
    run("MoveParaBegin")       # 앵커 문단 맨 앞으로
    if o.get("all", False):
        rounds, _ = _repeat_delete_while_progress(
            lambda: run("DeleteBack"), lambda: _count_newlines(hwp))
        return {"deleted": rounds, "found": True, "rounds": rounds}
    n = int(o.get("count", 1))
    for _ in range(n):
        run("DeleteBack")      # 앞 문단 끝 마크 제거(앞의 빈 문단 흡수)
    return {"deleted": n, "found": True, "deleted_breaks": n}


def op_move(hwp, o):
    to = o.get("to", "doc_end")
    {"doc_end": hwp.MoveDocEnd, "doc_start": hwp.MoveDocBegin,
     "line_end": hwp.MoveLineEnd}[to]()
    return {"moved": to}


def _set_char_height(hwp, pt, color=0, bold=None):
    """선택 글자크기를 pt로, 글자색을 color로, (지정 시) 굵기를 bold로 설정.

    다른 속성은 GetDefault로 보존. color 기본 0=검정. 조립 본문은 앵커(빨간
    안내문) 자리에 들어가 색을 상속하므로(본문이 빨강으로 박힘), 크기 강제와
    함께 검정으로 못박는다. bold=None이면 Bold 속성은 건드리지 않는다(기존
    호출부 — pt만 강제하는 경로 — 는 굵기를 앵커/기본값 그대로 상속).
    """
    pset = hwp.HParameterSet.HCharShape
    hwp.HAction.GetDefault("CharShape", pset.HSet)
    pset.Height = int(round(float(pt) * 100))  # 1pt = 100 HwpUnit
    pset.TextColor = color
    if bold is not None:
        pset.Bold = 1 if bold else 0
    hwp.HAction.Execute("CharShape", pset.HSet)


def _set_bold(hwp, bold):
    """굵기만 변경(크기·색 등 다른 CharShape 속성은 GetDefault로 보존)."""
    pset = hwp.HParameterSet.HCharShape
    hwp.HAction.GetDefault("CharShape", pset.HSet)
    pset.Bold = 1 if bold else 0
    hwp.HAction.Execute("CharShape", pset.HSet)


def _insert_run_with_shape(hwp, text, pt=None, bold=None):
    """텍스트 한 런을 삽입하고, pt/bold가 주어지면 insert-then-select로 CharShape를 건다.

    pending CharShape는 한 번 밀려(다음 입력에 적용) 신뢰할 수 없다 — 먼저
    삽입하고 삽입 구간을 선택해 CharShape를 거는 결정론적 경로(op_insert_text의
    기존 pt 전용 경로와 동일 메커니즘, bold까지 확장). pt/bold 둘 다 없으면
    아무 CharShape도 걸지 않고 그대로 삽입(앵커 서식 상속, 구동작).
    반환: 삽입 후 커서 위치(end, get_pos() 튜플).
    """
    if pt is None and bold is None:
        hwp.insert_text(text)
        return hwp.get_pos()
    start = hwp.get_pos()           # (list, para, pos)
    hwp.insert_text(text)
    end = hwp.get_pos()
    try:
        if hwp.select_text(start[1], start[2], end[1], end[2], start[0]):
            if pt is not None:
                _set_char_height(hwp, pt, bold=bold)
            else:
                _set_bold(hwp, bold)
        try:
            hwp.Cancel()
        except Exception:
            pass
    finally:
        hwp.set_pos(*end)
    return end


def op_insert_text(hwp, o):
    """본문 텍스트 삽입. pt가 주어지면 앵커 서식 상속 대신 그 크기를 강제 적용한다.

    빈 영역에 CharShape를 거는 'pending font'는 한 번 밀려(다음 입력에 적용) 신뢰할
    수 없다 — 그래서 먼저 삽입하고, 삽입 구간을 선택해 CharShape.Height를 거는
    insert-then-select 경로를 쓴다(결정론적). 제목(15pt) 등 앵커 서식을 상속하지 않는다.

    "segments": [{"text":.., "bold":bool}, ...] — 주어지면 "text"(플레인 폴백)
    대신 세그먼트별로 순서대로 삽입하며, 매 런마다 CharShape.Bold를 명시적으로
    1 또는 0으로 못박는다(insert-then-select 패턴, pt는 모든 런에 공통 적용).
    bold=False 런에서도 Bold를 굳이 0으로 명시하는 이유: GetDefault는 방금
    삽입한 셀렉션의 "pending" 굵기를 그대로 반영할 수 있어(hwp-com-charshape-
    quirks 메모 — pending CharShape가 한 런 밀려 적용됨), 직전 굵게 런 바로
    뒤의 일반 런이 Bold를 건드리지 않으면 굵기가 새어 들어올 위험이 있다.
    segments 없으면 기존 단일-런 경로 그대로(하위호환) — build_report.py가
    `**` 없는 문단에는 segments 키 자체를 생략한다.

    "break_after": true — 삽입한 텍스트 뒤에 문단 구분을 BreakPara(Run)로
    만든다. text 안에 리터럴 "\\r\\n"을 넣어 pyhwpx insert_text에 개행까지
    함께 태우는 구동작과 달리, BreakPara는 인접 문단의 서식(charShape)을
    오염시키지 않는다(hwp-com-charshape-quirks 메모: "\\r\\n"은 pending
    글자크기를 인접 문단에 번지게 함 — 제목 옆 문단 분리에 실측 확인됨).
    이 플래그가 없으면 기존 동작 그대로(text에 개행이 있으면 그대로 삽입) —
    하위호환 유지. break_after는 CharShape 적용(pt/bold) *이후*, 커서가
    삽입 끝에 있는 상태에서 실행해 새 문단이 방금 삽입한 런의 서식을
    그대로 이어받게 한다(끊긴 서식으로 새 문단이 시작되는 것 방지).
    """
    segments = o.get("segments")
    pt = o.get("pt")
    break_after = bool(o.get("break_after"))
    if segments:
        total_chars = 0
        for seg in segments:
            seg_text = seg["text"]
            bold = bool(seg.get("bold"))
            _insert_run_with_shape(hwp, seg_text, pt=pt, bold=bold)
            total_chars += len(seg_text)
        if break_after:
            _run(hwp, "BreakPara")
        return {"inserted_chars": total_chars, "pt": pt, "segments": len(segments),
                "break_after": break_after}
    text = o["text"]
    if not pt:
        hwp.insert_text(text)
        if break_after:
            _run(hwp, "BreakPara")
        return {"inserted_chars": len(text), "break_after": break_after}
    start = hwp.get_pos()           # (list, para, pos)
    hwp.insert_text(text)
    end = hwp.get_pos()
    try:
        if hwp.select_text(start[1], start[2], end[1], end[2], start[0]):
            _set_char_height(hwp, pt)
        try:
            hwp.Cancel()
        except Exception:
            pass
    finally:
        hwp.set_pos(*end)           # 후속 op를 위해 커서를 삽입 끝으로 복귀
    if break_after:
        _run(hwp, "BreakPara")
    return {"inserted_chars": len(text), "pt": pt, "break_after": break_after}


_ALIGN_ACTIONS = {
    "justify": "ParagraphShapeAlignJustify",
    "center": "ParagraphShapeAlignCenter",
    "left": "ParagraphShapeAlignLeft",
    "right": "ParagraphShapeAlignRight",
    "distribute": "ParagraphShapeAlignDistribute",
}


def _run(hwp, action):
    runner = getattr(hwp, "Run", None)
    if callable(runner):
        return runner(action)
    return hwp.HAction.Run(action)


def _para_offset(hwp):
    """현재 커서의 문단 내 글자 위치. 0이면 문단 맨 앞.

    실패하면 -1을 돌려준다(호출부는 0이 아니라고 보고 새 문단을 연다 = 보수적).
    """
    try:
        return hwp.get_pos()[2]
    except Exception:
        return -1


def op_set_para_align(hwp, o):
    """문단 정렬 변경. all=true면 문서 전체, anchor=문구면 그 문단만.

    align: justify(양쪽)|center(가운데)|left|right|distribute(배분).
    그림·수식 문단은 center, 본문은 justify, URL/참고문헌은 left 권장.
    """
    align = o.get("align", "justify")
    act = _ALIGN_ACTIONS.get(align)
    if not act:
        raise RuntimeError(f"알 수 없는 align: {align}")
    if o.get("all"):
        hwp.MoveDocBegin()
        hwp.SelectAll()
    elif o.get("anchor"):
        hwp.MoveDocBegin()
        if not (hwp.find(o["anchor"]) if hasattr(hwp, "find") else False):
            raise RuntimeError(f"앵커 문구를 찾지 못함: {o['anchor']!r}")
        hwp.Cancel()  # 선택 풀고 그 문단에 커서
    _run(hwp, act)
    try:
        hwp.Cancel()
    except Exception:
        pass
    return {"align": align}


def op_insert_equation(hwp, o):
    if "hwpeqn" in o:
        script, warns = o["hwpeqn"], []
    else:
        script, warns = latex_to_hwpeqn(o["latex"])
    ok, msg = hwpeqn_sanity_check(script)
    if not ok:
        raise RuntimeError(f"수식 스크립트 검증 실패({msg}): {script}")
    # display=true: 큰 수식은 본문 문단에 끼지 않고 자기 문단(가운데)에 둔다.
    # 커서가 문단 중간이면 새 문단을 열고, 이미 문단 맨 앞(앞 문단이 \r\n로 끝남)이면
    # 새로 열지 않는다 — 안 그러면 lead-in과 수식 사이에 빈 문단이 끼어 빈 줄이 쌓인다.
    display = o.get("display", False)
    if display and _para_offset(hwp) != 0:
        hwp.insert_text("\r\n")
    pset = hwp.HParameterSet.HEqEdit
    hwp.HAction.GetDefault("EquationCreate", pset.HSet)
    pset.string = script
    pset.BaseUnit = int(o.get("base_pt", 10) * 100)  # 1pt = 100 HwpUnit
    if o.get("font"):
        pset.EqFontName = o["font"]
    hwp.HAction.Execute("EquationCreate", pset.HSet)
    # 수식 컨트롤 밖으로 커서 복귀
    try:
        hwp.Cancel()
    except Exception:
        pass
    if display:
        _run(hwp, "ParagraphShapeAlignCenter")
        # 수식 문단 뒤에 새 문단을 열어 후속 본문이 수식 문단에 붙지 않게 한다
        # (붙으면 본문이 수식 옆에 끼고 가운데정렬을 상속한다). 새 문단은 본문 정렬.
        hwp.insert_text("\r\n")
        _run(hwp, "ParagraphShapeAlignJustify")
    return {"hwpeqn": script, "warnings": warns, "display": display}


def op_edit_equation(hwp, o):
    if "hwpeqn" in o:
        script, warns = o["hwpeqn"], []
    else:
        script, warns = latex_to_hwpeqn(o["latex"])
    idx, cur = o["index"], 0
    ctrl = hwp.HeadCtrl
    while ctrl:
        if getattr(ctrl, "CtrlID", "") == "eqed":
            if cur == idx:
                prop = ctrl.Properties
                old = prop.Item("String")
                prop.SetItem("String", script)
                ctrl.Properties = prop
                return {"index": idx, "old": old, "new": script,
                        "warnings": warns}
            cur += 1
        ctrl = ctrl.Next
    raise RuntimeError(f"수식 index {idx} 없음 (총 {cur}개)")


def _table_total_width(hwp):
    """본문 폭(용지-여백-제본-표 바깥여백 2mm)을 HwpUnit으로 계산.

    pyhwpx create_table과 동일 공식(총 폭 = 용지폭 - 좌우여백 - 제본 - 2mm).
    """
    sec_def = hwp.HParameterSet.HSecDef
    hwp.HAction.GetDefault("PageSetup", sec_def.HSet)
    pd = sec_def.PageDef
    return (int(pd.PaperWidth) - int(pd.LeftMargin) - int(pd.RightMargin)
            - int(pd.GutterLen) - hwp.MiliToHwpUnit(2))


# 셀 안쪽여백(좌우 각 1.8mm = 도합 3.6mm) HwpUnit 상수 — pyhwpx.create_table과
# 동일값. 실측(스모크 테스트, colwidth_spike2.py — s1_base.hwpx 사본에 6열 표
# 삽입 → save-as hwpx → unzip → section0.xml의 <hp:cellSz width="..."> 파싱)
# 재확인: SetItem(i, w)로 준 ColWidth 값은 "내용 폭"이고, 저장된 hwpx의
# cellSz width는 여기에 이 상수가 더해진 "바깥 폭"이다 — 6열 모두 저장폭에서
# 정확히 1020을 빼면 SetItem에 준 값과 완전히 일치(오차 0, 6/6열 재현).
# table_too_wide 버그(HR run evidence): 이 오프셋을 보정 없이 방치하면 저장폭
# 합계가 열 개수 x 1020만큼 텍스트 컬럼 폭을 넘어선다(6열 예시: 47624 대비
# 6120 HwpUnit 초과 = 12.8%). 아래 _col_widths_for_target이 이를 역보정한다.
CELL_INSET_HWU = 1020
MIN_COL_CONTENT_HWU = 100  # 보정 후 최소 내용폭(0 이하로 내려가 표가 깨지는 것 방지)


def _col_widths_for_target(target_total, col_ratios, inset=CELL_INSET_HWU,
                            min_width=MIN_COL_CONTENT_HWU):
    """저장된 hwpx cellSz(=SetItem 값 + inset)의 합이 target_total이 되도록
    역산한 ColWidth.SetItem 값 리스트를 돌려준다(COM 미사용, 순수 함수).

    각 열의 "내용 폭" = round(target_total * ratio) - inset. 열이 많거나
    target_total이 작아 뺀 값이 min_width 밑으로 내려가면 min_width로
    clamp한다(비율이 극단적으로 좁은 열이 있어도 표가 깨지지 않게).
    클램프가 실제로 일어나면 caller가 로그/경고할 수 있게 clamped 플래그를
    함께 돌려준다.
    """
    raw = [round(target_total * r) - inset for r in col_ratios]
    clamped = [w < min_width for w in raw]
    widths = [max(w, min_width) for w in raw]
    return widths, any(clamped)


def _create_table_with_ratios(hwp, rows, cols, col_ratios, treat_as_char):
    """HTableCreation을 직접 호출해 열별 폭을 col_ratios(정규화된 비율, 합=1.0)
    비율대로 임의값(WidthType=2)으로 지정하며 표를 만든다.

    _col_widths_for_target으로 셀 안쪽여백(inset) 역보정을 거친 값을
    SetItem에 준다 — 그래야 실제 저장되는 cellSz width 합이 텍스트 컬럼
    폭(total_width)과 일치한다(table_too_wide 버그 수정). 열 간 비율은
    inset이 모든 열에 동일 상수라 여전히 근사 보존된다(작은 열일수록
    상대오차가 커질 수 있으나, 절대폭이 계약이므로 이쪽이 우선).

    반환: total_width(HwpUnit), col_widths(HwpUnit 리스트, inset 보정 후
    SetItem에 실제로 준 "내용 폭") — 후속 헤더/치수 로깅용.
    """
    pset = hwp.HParameterSet.HTableCreation
    hwp.HAction.GetDefault("TableCreate", pset.HSet)
    pset.Rows = rows
    pset.Cols = cols
    pset.WidthType = 2   # 임의값(custom) — 균등폭(0/1)과 달리 열별 폭 지정 가능
    pset.HeightType = 0

    total_width = _table_total_width(hwp)
    col_widths, _clamped = _col_widths_for_target(total_width, col_ratios)
    pset.CreateItemArray("ColWidth", cols)
    for i, w in enumerate(col_widths):
        pset.ColWidth.SetItem(i, w)
    pset.TableProperties.Width = total_width
    try:
        pset.TableProperties.TreatAsChar = treat_as_char
    except Exception:
        pass
    hwp.HAction.Execute("TableCreate", pset.HSet)
    return total_width, col_widths


def op_insert_table(hwp, o):
    """순수 2차원 리스트만 받아 표를 그린다.

    data는 항상 [[헤더...], [행...], ...] 형태의 2D 리스트여야 한다. pandas
    DataFrame을 넘기지 말 것 — DataFrame을 table_from_data로 그리면 숫자 헤더
    행과 인덱스 열(0,1,2,...)이 셀에 박혀 오염된다. 기본 경로는 create_table +
    셀별 직접 입력(plain)으로, 인덱스/자동 헤더가 절대 생기지 않는다.
    (옛 동작이 필요하면 use_dataframe: true — 권장하지 않음.)

    col_ratios: 정규화된 열 너비 비율 리스트(합=1.0, len==cols). 주어지면
    HTableCreation(WidthType=2) 직접 호출 경로(_create_table_with_ratios)로
    표를 만든다 — pyhwpx.create_table()의 균등폭 경로 대신이다. 없으면(구
    태그 하위호환) create_table() 균등폭 그대로.
    font_pt: 주어지면 셀 삽입 텍스트마다 insert-then-select CharShape 패턴
    (_set_char_height, op_insert_text와 동일 메커니즘)으로 크기를 강제한다.
    없으면 앵커/기본 서식 상속(구동작).
    """
    data = o["data"]
    if o.get("use_dataframe") and hasattr(hwp, "table_from_data"):
        hwp.table_from_data(data, treat_as_char=o.get("treat_as_char", True))
        return {"rows": len(data), "cols": len(data[0]), "mode": "dataframe"}
    rows, cols = len(data), len(data[0])
    col_ratios = o.get("col_ratios")
    font_pt = o.get("font_pt")
    if col_ratios is not None and len(col_ratios) != cols:
        raise RuntimeError(
            f"col_ratios 길이({len(col_ratios)})가 표 열 개수({cols})와 다름")
    # (예전엔 MoveDocEnd로 셀을 빠져나왔는데, 그러면 커서가 문서 끝으로 튀어
    #  이후 본문이 마지막 섹션 뒤에 붙는 순서 붕괴를 일으켰다. 현재는 표
    #  뒤로 커서를 되돌리는 좌표 저장(before=get_pos()) 없이, 마지막 셀
    #  텍스트 삽입 직후 자리에서 MoveRight 액션으로 표를 빠져나간다 — 아래
    #  주석 참고.)
    treat_as_char = o.get("treat_as_char", True)
    if col_ratios is not None:
        _create_table_with_ratios(hwp, rows, cols, col_ratios, treat_as_char)
    else:
        hwp.create_table(rows, cols, treat_as_char=treat_as_char)
    for r in range(rows):
        for c in range(cols):
            text = str(data[r][c])
            if font_pt:
                # insert_text(pt=) op와 동일한 insert-then-select 패턴(pending
                # CharShape는 신뢰 불가 — op_insert_text 문서 주석 참고).
                cell_start = hwp.get_pos()
                hwp.insert_text(text)
                cell_end = hwp.get_pos()
                if hwp.select_text(cell_start[1], cell_start[2],
                                    cell_end[1], cell_end[2], cell_start[0]):
                    _set_char_height(hwp, font_pt)
                try:
                    hwp.Cancel()
                except Exception:
                    pass
                hwp.set_pos(*cell_end)
            else:
                hwp.insert_text(text)
            if not (r == rows - 1 and c == cols - 1):
                hwp.TableRightCell()
    # BUG(Rule 2에서 발견): before[2]+1로 좌표를 직접 산술해 set_pos하면
    # (구동작) 표(inline 문자 1개)를 건너뛰지 못하고 표 삽입 전 위치로 되돌아
    # 간다(실측: 표 셀 편집으로 커서가 다른 internal list로 넘어갔다 오면
    # set_pos(list, para, pos+1)이 조용히 pos+1이 아니라 pos 그대로에 멈춤 —
    # before 저장 당시의 (list, para, pos) 좌표계가 표 삽입 후 더 이상
    # 유효하지 않음). set_pos로 아무 데도 돌아가지 않고, 마지막 셀 텍스트를
    # 넣은 직후(=아직 표 안, 커서가 자연스레 있는 그 자리)에서 곧바로
    # MoveRight 액션(사람이 오른쪽 화살표를 눌러 표를 빠져나가는 것과 동일)
    # 하나만 실행하면 표 바로 뒤(같은 문단, inline 표 문자 다음)로 정확히
    # 이동한다(실측 확인 — set_pos를 개입시키면 오히려 깨짐). 이 버그는 표
    # 뒤에 바로 캡션 텍스트를 넣는 Rule 2 순서(blank->표->캡션->blank)에서
    # 처음 드러났다 — 캡션이 표보다 먼저 삽입되던 구동작에서는 이 좌표 오류가
    # 있어도 후속 본문이 우연히 올바른 자리에 들어가 증상이 안 보였다.
    moved = False
    try:
        _run(hwp, "MoveRight")
        moved = True
    except Exception:
        moved = False
    if not moved:
        hwp.MoveDocEnd()  # 최후 폴백
    # 표 뒤에 새 문단을 열어 후속 본문이 표(셀)에 끼지 않게 한다.
    hwp.insert_text("\r\n")
    _run(hwp, "ParagraphShapeAlignJustify")
    return {"rows": rows, "cols": cols, "mode": "plain", "cursor_after_table": moved,
            "col_ratios": col_ratios, "font_pt": font_pt}


def _png_aspect(path):
    """이미지의 height/width 비율을 구한다. PIL 우선, 실패 시 PNG 헤더 직독."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        return h / w if w else None
    except Exception:
        try:
            import struct
            with open(path, "rb") as f:
                head = f.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return h / w if w else None
        except Exception:
            return None
    return None


def op_insert_picture(hwp, o):
    path = str(Path(o["path"]).resolve())
    kwargs = {"treat_as_char": o.get("treat_as_char", True), "embedded": True}
    w, h = o.get("width_mm"), o.get("height_mm")
    auto_h = False
    # 폭만 주어지면 원본 종횡비로 높이를 자동 계산 (pyhwpx는 sizeoption=1에서
    # width/height 둘 다 요구하므로 한쪽만 주면 ValueError가 난다).
    if w and not h:
        ar = _png_aspect(path)
        if ar:
            h = round(w * ar, 2)
            auto_h = True
    if w or h:
        # pyhwpx insert_picture의 width/height 단위는 mm (HwpUnit 아님!).
        # 과거 MiliToHwpUnit 변환은 거대값을 넘겨 사이즈가 무시됐다(native 삽입).
        kwargs.update(sizeoption=1, width=w or 0, height=h or 0)
    # own_paragraph(기본 true): 큰 그림은 본문 문단에 끼지 않고 자기 문단에 단독으로
    # 들어가야 한다. 인라인 그림은 캡션 줄이 그림 옆에 끼거나 줄이 벌어지는 원인.
    # 호출 전 커서를 캡션 문단 끝에 두면 \r\n으로 새 문단을 만들고 거기에 그림만 둔다.
    own_para = o.get("own_paragraph", True)
    # 캡션이 바로 위 문단(…\r\n)이면 빈 문단을 끼우지 않는다 — 캡션과 그림이 떨어지면
    # 페이지 경계에서 캡션만 앞 쪽에 고립된다. 문단 중간일 때만 새 문단을 연다.
    if own_para and _para_offset(hwp) != 0:
        hwp.insert_text("\r\n")
    try:
        hwp.insert_picture(path, **kwargs)
    except TypeError:  # pyhwpx 버전별 시그니처 차이 흡수
        hwp.insert_picture(path)
    if own_para:
        _run(hwp, "ParagraphShapeAlignCenter")
        # 그림 문단 뒤에 새 문단을 열어 후속 본문이 그림 옆에 끼지 않게 한다
        # (붙으면 "거리에 오차를"처럼 그림 우측에 본문 일부가 고립된다). 새 문단은 본문 정렬.
        hwp.insert_text("\r\n")
        _run(hwp, "ParagraphShapeAlignJustify")
    return {"picture": path, "width_mm": w, "height_mm": h,
            "auto_height": auto_h, "own_paragraph": own_para}


def _parse_color(c):
    """색을 hwp TextColor 정수로. int 그대로, '#RRGGBB'/'RRGGBB' 파싱."""
    if c is None:
        return 0  # black
    if isinstance(c, int):
        return c
    s = str(c).lstrip("#")
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return r | (g << 8) | (b << 16)  # hwp TextColor = 0x00BBGGRR


def op_set_char_color(hwp, o):
    """글자색만 변경. 기본은 문서 전체(SelectAll), 굵기·크기 등은 불변.

    GetDefault로 받은 CharShape 파라미터에서 TextColor만 set하므로 다른 글자
    속성은 건드리지 않는다. all=false면 현재 선택 영역에만 적용.

    순서 주의: insert_hyperlink는 링크를 파랑으로 넣는다. 그 뒤에 all=true 전역
    색 지정을 돌리면 SelectAll이 링크까지 덮어 파랑이 사라진다. 하이퍼링크가
    있으면 전역 색 지정을 링크 삽입 '전에' 하거나 all=false로 범위를 좁혀라.
    """
    color = _parse_color(o.get("color", 0))
    all_doc = o.get("all", True)
    if all_doc:
        hwp.MoveDocBegin()
        hwp.SelectAll()
    # CharShape 파라미터로 TextColor만 직접 set한다. set_font(TextColor=...)는
    # 빈 값 인자를 건너뛰는데 검정(0)도 falsy라 스킵돼 검정 적용이 무효가 된다.
    # 따라서 항상 HParameterSet 경로를 쓴다(크기·굵기 등 다른 속성은 GetDefault로 보존).
    pset = hwp.HParameterSet.HCharShape
    hwp.HAction.GetDefault("CharShape", pset.HSet)
    pset.TextColor = color
    hwp.HAction.Execute("CharShape", pset.HSet)
    try:
        hwp.Cancel()
    except Exception:
        pass
    res = {"text_color": color}
    if all_doc:
        res["warning"] = ("all=true는 하이퍼링크 색도 덮어씀 — 링크 삽입 후 실행 금지")
    return res


def op_delete_ctrls(hwp, o):
    """지정한 CtrlID의 컨트롤을 모두(또는 index 하나) 삭제.

    types: ["tbl"], ["gso"], ["eqed"] 등. 표/그림을 지우고 캡션(본문 텍스트)은
    그대로 두는 용도. Next 순회가 삭제로 깨지지 않게 먼저 수집 후 삭제한다.
    """
    types = o.get("types") or [o.get("type")]
    types = [t for t in types if t]
    targets, c = [], hwp.HeadCtrl
    while c:
        if getattr(c, "CtrlID", "") in types:
            targets.append(c)
        c = c.Next
    if "index" in o:
        targets = [targets[o["index"]]] if o["index"] < len(targets) else []
    deleter = getattr(hwp, "DeleteCtrl", None) or getattr(hwp, "delete_ctrl", None)
    n = 0
    for ctrl in targets:
        deleter(ctrl)
        n += 1
    return {"deleted": n, "types": types}


def op_set_cell(hwp, o):
    hwp.get_into_nth_table(o["table"])
    for _ in range(o["row"]):
        hwp.TableLowerCell()
    for _ in range(o["col"]):
        hwp.TableRightCell()
    hwp.SelectAll()  # 셀 내 전체 선택 (표 안에서는 셀 범위)
    hwp.Delete()
    hwp.insert_text(str(o["text"]))
    hwp.MoveDocEnd()
    return {"cell": [o["table"], o["row"], o["col"]]}


def op_insert_blank_before(hwp, o):
    """앵커(제목) 문단 '앞'에 빈 문단 1개를 보장한다.

    이전 본문 끝과 다음 제목/소제목이 붙는("I. 서론밤하늘") 현상을 막는다. 제목 문단
    맨 앞에서 \\r\\n을 넣어 위에 빈 문단을 만든다. 연속 2개 이상이 생기면 후속
    collapse_empty_paragraphs가 1개로 정규화한다(공백 과잉 방지).
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
    hwp.Cancel()
    pos = hwp.get_pos()              # (list, para, pos) — 제목 문단
    hwp.set_pos(pos[0], pos[1], 0)   # 제목 문단 맨 앞
    _run(hwp, "MoveLeft")           # 이전 문단 끝으로 이동
    # 빈 문단 삽입. insert_text("\r\n")은 pending 글자크기를 제목 런에 번지게 하므로
    # (제목 11pt→10pt 오염), BreakPara(엔터 동작)로 넣는다 — 주변 문단 서식을 상속하고
    # pending을 쓰지 않아 제목이 보존된다. 항상 삽입한다(건너뛰면 첫 섹션 제목이 후속
    # 본문 삽입에 오염되는 사례가 있음).
    _run(hwp, "BreakPara")
    return {"blank_before": o["text"]}


def op_page_break_before(hwp, o):
    """앵커 문단이 항상 새 페이지 맨 위에서 시작하도록 그 앞에 페이지 나누기를 넣는다.

    T11(kb trouble-table): 양식은 원래 빈 문단 다수 + (지금은 삭제된) 유의사항
    표로 제목을 3페이지까지 밀어냈다. 상위 콘텐츠(표/안내문) 삭제 후 그 빈
    문단들만으로 페이지를 미는 방식은 빈 문단 개수에 취약하고(T7 가드 대상이라
    COM으로 못 건드림) 근본적으로 구조가 아니라 우연에 기대는 방식이다. 대신
    앵커 문단 자체에 페이지 나누기 문단 속성을 거는 게 구조적으로 안정적이다.

    앵커 문단 '맨 앞'으로 이동(MoveParaBegin) 후 BreakPage. BreakPage(Run)는
    새 페이지를 여는 빈 페이지-나누기 문단을 만들고 커서가 그 다음(앵커) 문단에
    남는다 — insert_blank_before의 BreakPara와 달리 페이지 속성이 걸린다.

    주의: 이 앵커 문단은 build.yaml의 tidy_blank_before 목록에 있으면 안 된다.
    tidy_blank_before(오프라인 XML 정리, tidy_hwpx.py)가 앵커 앞 문단을 정리하며
    페이지 나누기가 걸린 빈 문단을 함께 먹어버릴 수 있다 — page_break_before와
    tidy_blank_before는 같은 앵커를 공유하지 말 것(build_report.py 주석에도 명시).
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        if o.get("required", False):
            raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
        return {"page_break_before": o["text"], "found": False}
    hwp.Cancel()
    _run(hwp, "MoveParaBegin")
    _run(hwp, "BreakPage")
    return {"page_break_before": o["text"], "found": True}


def _resolve_post_field_pos(pre_field_pos, post_field_pos):
    """필드/컨트롤 삽입 전후 position 재획득 불변식을 검사하는 순수 헬퍼.

    COM 자체(hwp.GetPos() 호출 시점)는 유닛 테스트 불가 — 이 함수는 "어느 좌표를
    신뢰해야 하는가"라는 순수 로직만 분리한 것이다: 필드 삽입 *후* 좌표
    (post_field_pos)가 항상 유일하게 신뢰 가능한 값이다. pre_field_pos는 필드
    마커가 끼어들기 전 스냅샷이라 그대로 set_pos에 쓰면 안 된다(BUG1의 근본 원인).

    반환: 실제 set_pos에 사용해야 할 (list, para, pos) 튜플 = post_field_pos.
    두 값이 같은 para인데 pos가 다르면(post < pre) 필드 삽입으로 오프셋이
    당겨졌다는 신호이므로 caller가 로깅/검증에 쓸 수 있게 그대로 반환한다.
    """
    if pre_field_pos is None or post_field_pos is None:
        raise ValueError("pre_field_pos/post_field_pos required")
    return post_field_pos


def op_insert_hyperlink(hwp, o):
    """URL을 실제 하이퍼링크 필드로 삽입한다.

    한글 GUI의 '스페이스→자동 링크화'는 COM(InsertText) 경로에선 트리거되지 않는다.
    pyhwpx의 insert_hyperlink(hypertext, description)로 진짜 HYPERLINK 필드를 넣는다
    (밑줄·색 링크 서식). text가 url과 다르면 표시문구로 쓴다.
    """
    url = o["url"]
    text = o.get("text") or url
    # insert_hyperlink(url, desc)는 필드만 만들고 표시 글자를 넣지 않아 화면에 아무것도
    # 안 보인다. 표준 패턴: 표시 텍스트를 먼저 타이핑 → 선택 → 그 선택을 하이퍼링크로
    # 감싼다. 그리고 링크 서식(밑줄+파랑)을 직접 입힌다(COM은 자동 서식을 안 넣음).
    start = hwp.get_pos()
    hwp.insert_text(text)
    pre_field_end = hwp.get_pos()   # 필드 삽입 전 임시 끝(아래 재획득 전까지만 사용)
    hwp.select_text(start[1], start[2], pre_field_end[1], pre_field_end[2], start[0])
    ok = hwp.insert_hyperlink(url, text)
    # 불변식: InsertHyperlink 필드/문자 마커가 선택 구간을 감싸며 문서 내부 오프셋을
    # 앞으로 밀어낸다(필드 시작/끝 마커는 보이지 않는 문자로 취급됨). pre_field_end는
    # 필드 삽입 *이전* 좌표라 이후 set_pos에 그대로 쓰면 항상 짧게(관측: 8자) 어긋난다
    # — 반드시 InsertHyperlink 실행 *후* get_pos()로 진짜 끝을 다시 얻어야 한다.
    end = _resolve_post_field_pos(pre_field_end, hwp.get_pos())
    hwp.select_text(start[1], start[2], end[1], end[2], start[0])
    # 링크 서식: 밑줄 + 파랑(#0000FF → hwp TextColor 0xFF0000). 본문 크기(10pt)는 유지.
    pset = hwp.HParameterSet.HCharShape
    hwp.HAction.GetDefault("CharShape", pset.HSet)
    pset.TextColor = 0xFF0000
    if o.get("pt"):                 # URL도 본문 크기로 강제(앵커 자리 크기 상속 방지)
        pset.Height = int(round(float(o["pt"]) * 100))
    try:
        pset.UnderlineType = hwp.UnderlineType("Bottom")
    except Exception:
        pset.UnderlineType = 1
    hwp.HAction.Execute("CharShape", pset.HSet)
    try:
        hwp.Cancel()
    except Exception:
        pass
    # 커서 복귀도 재획득한 end를 써야 한다(pre_field_end 사용 시 다음 op가 필드 안/직전에
    # 착지해 뒤따르는 개행이 필드 꼬리를 잘라먹는다 — 이 버그의 관측된 증상).
    hwp.set_pos(*end)
    return {"hyperlink": url, "text": text, "ok": bool(ok)}


def op_page_binding(hwp, o):
    """제본용(book)↔제출용(submit) 쪽 여백 전환.

    book(기본): 원본 그대로(안쪽/바깥쪽 미러링 + 제본 여백 유지).
    submit: 좌우 여백을 (좌+우+제본)/2로 대칭화하고 제본 여백을 0으로 — 인쇄폭은
    동일하게 두면서 홀짝 페이지 좌우가 같아진다(일반 제출 파일).
    """
    mode = (o.get("mode") or "submit").lower()
    hwp.MoveDocBegin()
    pset = hwp.HParameterSet.HSecDef
    hwp.HAction.GetDefault("PageSetup", pset.HSet)
    pd = pset.PageDef
    if mode == "submit":
        total = int(pd.LeftMargin) + int(pd.RightMargin) + int(pd.GutterLen)
        half = total // 2
        pd.LeftMargin = half
        pd.RightMargin = total - half
        pd.GutterLen = 0
        hwp.HAction.Execute("PageSetup", pset.HSet)
    return {"binding": mode, "left": int(pd.LeftMargin),
            "right": int(pd.RightMargin), "gutter": int(pd.GutterLen)}


def op_set_line_spacing(hwp, o):
    """줄간격을 percent로 설정. 기본 문서 전체(SelectAll). 다른 문단 속성은 GetDefault로 보존.

    삽입 본문이 양식 안내문 문단(180%)을 상속하는 문제를 교정한다. 제출 기본값 160%.
    제목·캡션도 같은 줄간격이 되지만 위계는 글자크기로 유지되므로 시각상 문제 없다.
    LineSpacingType=0(글자에 따라=percent), LineSpacing=percent.
    """
    percent = int(o.get("percent", 160))
    if o.get("all", True):
        hwp.MoveDocBegin()
        hwp.SelectAll()
    pset = hwp.HParameterSet.HParaShape
    hwp.HAction.GetDefault("ParagraphShape", pset.HSet)
    try:
        pset.LineSpacingType = 0
    except Exception:
        pass
    pset.LineSpacing = percent
    hwp.HAction.Execute("ParagraphShape", pset.HSet)
    try:
        hwp.Cancel()
    except Exception:
        pass
    return {"line_spacing_percent": percent}


OPS = {
    "replace_all": op_replace_all,
    "put_field": op_put_field,
    "goto_text": op_goto_text,
    "find_delete": op_find_delete,
    "move": op_move,
    "insert_text": op_insert_text,
    "insert_equation": op_insert_equation,
    "edit_equation": op_edit_equation,
    "insert_table": op_insert_table,
    "insert_picture": op_insert_picture,
    "set_cell": op_set_cell,
    "set_char_color": op_set_char_color,
    "delete_ctrls": op_delete_ctrls,
    "collapse_empty_paragraphs": op_collapse_empty_paragraphs,
    "delete_blank_after": op_delete_blank_after,
    "delete_blank_before": op_delete_blank_before,
    "set_para_align": op_set_para_align,
    "insert_blank_before": op_insert_blank_before,
    "insert_hyperlink": op_insert_hyperlink,
    "page_binding": op_page_binding,
    "set_line_spacing": op_set_line_spacing,
    "page_break_before": op_page_break_before,
}


# op별 필수 키. 여기 없는 op는 op 이름 존재만 검사한다(선택 키만 있는 op).
# 스키마 문서: references/ops_schema.md 와 동기 유지.
OP_REQUIRED_KEYS = {
    "replace_all": ("find", "replace"),
    "put_field": ("name", "text"),
    "goto_text": ("text",),
    "find_delete": ("text",),
    "insert_text": ("text",),
    "insert_picture": ("path",),
    "insert_hyperlink": ("url",),
    "insert_table": ("data",),
    "delete_blank_after": ("text",),
    "delete_blank_before": ("text",),
    "insert_blank_before": ("text",),
    "page_break_before": ("text",),
}


def _validate_ops(payload):
    """편집 op 배치를 한글 실행 '전에' 검증. 잘못된 op가 배치 중간에서 터져
    문서를 절반만 변형시키는 것을 막는다(부분 편집 잔존 방지, 감사 BUG4).

    리스트 또는 {"ops":[...]} 래퍼를 받는다. 선택 "schema" 필드는 무시한다.
    op 이름이 OPS에 없거나 필수 키가 빠지면 첫 위반 지점(index)에서 _die.
    반환: 정규화된 ops 리스트.
    """
    if isinstance(payload, dict) and "ops" in payload:
        ops = payload["ops"]
    else:
        ops = payload
    if not isinstance(ops, list):
        _die("ops가 리스트가 아님(또는 {'ops':[...]} 래퍼 아님)")
    for i, o in enumerate(ops):
        if not isinstance(o, dict) or "op" not in o:
            _die(f"ops[{i}]: 'op' 키 없는 항목")
        name = o["op"]
        if name not in OPS:
            _die(f"ops[{i}]: 알 수 없는 op {name!r}")
        for k in OP_REQUIRED_KEYS.get(name, ()):
            if k not in o:
                _die(f"ops[{i}] ({name}): 필수 키 {k!r} 없음")
    return ops


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="문서 구조 요약(JSON)")
    p_ins.add_argument("--file", required=True)
    p_ins.add_argument("--preview-chars", type=int, default=600)

    p_ed = sub.add_parser("edit", help="배치 편집 실행")
    p_ed.add_argument("--file", required=True)
    p_ed.add_argument("--ops", required=True, help="ops JSON 파일 경로")
    p_ed.add_argument("--save-as", help="저장 경로(.hwp/.hwpx). 생략 시 원본 덮어쓰기 안 함")
    p_ed.add_argument("--export-pdf", help="검증용 PDF 내보내기 경로")
    p_ed.add_argument("--visible", action="store_true", help="한글 창 표시")
    p_ed.add_argument("--kill-stale", action="store_true",
                      help="시작 전 잔존 Hwp.exe 강제 종료(파괴적, 명시할 때만)")

    p_cv = sub.add_parser("convert", help="형식 변환 (hwp<->hwpx, ->pdf)")
    p_cv.add_argument("--file", required=True)
    p_cv.add_argument("--to", required=True)

    args = ap.parse_args()
    hwp = None
    try:
        if args.cmd == "inspect":
            hwp = open_hwp(args.file)
            print(json.dumps(inspect(hwp, args.preview_chars),
                             ensure_ascii=False, indent=2))

        elif args.cmd == "edit":
            # 원본 비파괴(감사 BUG2): --save-as가 입력과 같으면 원본을 덮어쓴다.
            if args.save_as and Path(args.save_as).resolve() == Path(args.file).resolve():
                _die("원본 덮어쓰기 금지: --save-as가 입력 --file과 같음")
            payload = json.loads(Path(args.ops).read_text(encoding="utf-8"))
            # 한글 실행 전에 검증(BUG4): 알 수 없는 op·필수 키 누락을 여기서 걸러
            # 배치 중간 실패로 문서가 절반만 변형되는 것을 막는다. 래퍼/리스트 모두 허용.
            ops = _validate_ops(payload)
            hwp = open_hwp(args.file, visible=args.visible,
                           kill_stale=args.kill_stale)
            results = []
            for i, o in enumerate(ops):
                fn = OPS.get(o.get("op"))
                if fn is None:
                    raise RuntimeError(f"ops[{i}] 알 수 없는 op: {o.get('op')}")
                results.append({"op": o["op"], **fn(hwp, o)})
            saved = None
            if args.save_as:
                hwp.save_as(str(Path(args.save_as).resolve()))
                saved = args.save_as
            pdf = None
            if args.export_pdf:
                p = str(Path(args.export_pdf).resolve())
                try:
                    hwp.save_as(p, "PDF")
                except Exception:
                    hwp.SaveAs(p, "PDF")
                pdf = args.export_pdf
            print(json.dumps({"ok": True, "results": results,
                              "saved": saved, "pdf": pdf,
                              "post_inspect": inspect(hwp, 200)},
                             ensure_ascii=False, indent=2))

        elif args.cmd == "convert":
            # 원본 비파괴(감사 BUG2): --to가 입력과 같으면 원본을 덮어쓴다.
            if Path(args.to).resolve() == Path(args.file).resolve():
                _die("원본 덮어쓰기 금지: --to가 입력 --file과 같음")
            hwp = open_hwp(args.file)
            dst = str(Path(args.to).resolve())
            fmt = {"pdf": "PDF", "hwpx": "HWPX", "hwp": "HWP"}.get(
                Path(dst).suffix.lower().lstrip("."), None)
            hwp.save_as(dst, fmt) if fmt else hwp.save_as(dst)
            print(json.dumps({"ok": True, "converted": dst},
                             ensure_ascii=False))

    except SystemExit:
        raise
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc()},
                         ensure_ascii=False))
        sys.exit(1)
    finally:
        if hwp is not None:
            try:
                hwp.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
