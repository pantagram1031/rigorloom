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
  {"op": "set_para_align", "align": "center", "anchor": "제목"}    // 특정 문단만
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

def open_hwp(filepath, visible=False):
    try:
        from pyhwpx import Hwp
    except ImportError:
        _die("pyhwpx 미설치. 실행: pip install pyhwpx pywin32")
    hwp = Hwp(visible=visible)  # 보안모듈 자동 등록
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


def op_goto_text(hwp, o):
    hwp.MoveDocBegin()
    found = hwp.find(o["text"]) if hasattr(hwp, "find") else False
    if not found:
        raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
    if o.get("after", True):
        hwp.MoveLineEnd() if o.get("line_end") else hwp.Cancel()
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
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
    # find가 문구를 선택한 상태. Cancel로 선택을 풀면 커서가 문구 '끝'(문단 끝)에
    # 놓인다. MoveLineEnd는 줄바꿈된 문단에서 첫 시각줄 끝으로 가 문단 중간을
    # 잘라먹으므로 쓰지 않는다.
    hwp.Cancel()
    n = int(o.get("count", 1))
    for _ in range(n):
        hwp.Delete()           # 다음 문단 끝 마크 제거(빈 문단 흡수)
    return {"deleted_breaks": n}


def op_delete_blank_before(hwp, o):
    """앵커 문구가 있는 문단의 '앞' 빈 문단(들)을 제거.

    delete_blank_after의 대칭. 표/객체 바로 앞은 텍스트로 앵커할 수 없으므로,
    뒤따르는 캡션 등을 앵커로 잡아 그 앞의 빈 문단을 줄일 때 쓴다.
    """
    hwp.MoveDocBegin()
    if not (hwp.find(o["text"]) if hasattr(hwp, "find") else False):
        raise RuntimeError(f"앵커 문구를 찾지 못함: {o['text']!r}")
    hwp.Cancel()
    run = getattr(hwp, "Run", None) or (lambda a: hwp.HAction.Run(a))
    run("MoveParaBegin")       # 앵커 문단 맨 앞으로
    n = int(o.get("count", 1))
    for _ in range(n):
        run("DeleteBack")      # 앞 문단 끝 마크 제거(앞의 빈 문단 흡수)
    return {"deleted_breaks": n}


def op_move(hwp, o):
    to = o.get("to", "doc_end")
    {"doc_end": hwp.MoveDocEnd, "doc_start": hwp.MoveDocBegin,
     "line_end": hwp.MoveLineEnd}[to]()
    return {"moved": to}


def op_insert_text(hwp, o):
    hwp.insert_text(o["text"])
    return {"inserted_chars": len(o["text"])}


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


def op_insert_table(hwp, o):
    """순수 2차원 리스트만 받아 표를 그린다.

    data는 항상 [[헤더...], [행...], ...] 형태의 2D 리스트여야 한다. pandas
    DataFrame을 넘기지 말 것 — DataFrame을 table_from_data로 그리면 숫자 헤더
    행과 인덱스 열(0,1,2,...)이 셀에 박혀 오염된다. 기본 경로는 create_table +
    셀별 직접 입력(plain)으로, 인덱스/자동 헤더가 절대 생기지 않는다.
    (옛 동작이 필요하면 use_dataframe: true — 권장하지 않음.)
    """
    data = o["data"]
    if o.get("use_dataframe") and hasattr(hwp, "table_from_data"):
        hwp.table_from_data(data, treat_as_char=o.get("treat_as_char", True))
        return {"rows": len(data), "cols": len(data[0]), "mode": "dataframe"}
    rows, cols = len(data), len(data[0])
    # 표 삽입 위치를 기억해 두었다가 표 바로 뒤로 커서를 되돌린다.
    # (예전엔 MoveDocEnd로 셀을 빠져나왔는데, 그러면 커서가 문서 끝으로 튀어
    #  이후 본문이 마지막 섹션 뒤에 붙는 순서 붕괴를 일으켰다.)
    try:
        before = hwp.get_pos()  # (list, para, pos)
    except Exception:
        before = None
    hwp.create_table(rows, cols, treat_as_char=o.get("treat_as_char", True))
    for r in range(rows):
        for c in range(cols):
            hwp.insert_text(str(data[r][c]))
            if not (r == rows - 1 and c == cols - 1):
                hwp.TableRightCell()
    moved = False
    if before is not None:
        try:
            hwp.set_pos(before[0], before[1], before[2] + 1)  # 표(문자 1개) 바로 뒤
            moved = True
        except Exception:
            moved = False
    if not moved:
        hwp.MoveDocEnd()  # 최후 폴백
    # 표 뒤에 새 문단을 열어 후속 본문이 표(셀)에 끼지 않게 한다.
    hwp.insert_text("\r\n")
    _run(hwp, "ParagraphShapeAlignJustify")
    return {"rows": rows, "cols": cols, "mode": "plain", "cursor_after_table": moved}


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
    """
    color = _parse_color(o.get("color", 0))
    if o.get("all", True):
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
    return {"text_color": color}


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
}


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
            ops = json.loads(Path(args.ops).read_text(encoding="utf-8"))
            hwp = open_hwp(args.file, visible=args.visible)
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
