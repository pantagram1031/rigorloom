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
  {"op": "move",        "to": "doc_end"},            // doc_start|doc_end|line_end
  {"op": "insert_text", "text": "추가 문단\\r\\n"},
  {"op": "insert_equation", "latex": "\\\\frac{1}{2}mv^2"},   // 또는 "hwpeqn": "..."
  {"op": "insert_table", "data": [["헤더1","헤더2"],["a","b"]], "treat_as_char": true},
  {"op": "insert_picture", "path": "C:/img/그래프.png", "width_mm": 80},
  {"op": "edit_equation", "index": 0, "latex": "E=mc^2"},     // n번째 기존 수식 교체
  {"op": "set_cell", "table": 0, "row": 1, "col": 2, "text": "값"}
]
"""

import argparse
import json
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


def op_move(hwp, o):
    to = o.get("to", "doc_end")
    {"doc_end": hwp.MoveDocEnd, "doc_start": hwp.MoveDocBegin,
     "line_end": hwp.MoveLineEnd}[to]()
    return {"moved": to}


def op_insert_text(hwp, o):
    hwp.insert_text(o["text"])
    return {"inserted_chars": len(o["text"])}


def op_insert_equation(hwp, o):
    if "hwpeqn" in o:
        script, warns = o["hwpeqn"], []
    else:
        script, warns = latex_to_hwpeqn(o["latex"])
    ok, msg = hwpeqn_sanity_check(script)
    if not ok:
        raise RuntimeError(f"수식 스크립트 검증 실패({msg}): {script}")
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
    return {"hwpeqn": script, "warnings": warns}


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
    data = o["data"]
    if hasattr(hwp, "table_from_data") and not o.get("plain"):
        hwp.table_from_data(data, treat_as_char=o.get("treat_as_char", True))
    else:
        rows, cols = len(data), len(data[0])
        hwp.create_table(rows, cols,
                         treat_as_char=o.get("treat_as_char", True))
        for r in range(rows):
            for c in range(cols):
                hwp.insert_text(str(data[r][c]))
                if not (r == rows - 1 and c == cols - 1):
                    hwp.TableRightCell()
        hwp.MoveDocEnd()
    return {"rows": len(data), "cols": len(data[0])}


def op_insert_picture(hwp, o):
    path = str(Path(o["path"]).resolve())
    kwargs = {"treat_as_char": o.get("treat_as_char", True), "embedded": True}
    w, h = o.get("width_mm"), o.get("height_mm")
    if w or h:
        kwargs.update(sizeoption=1,
                      width=hwp.MiliToHwpUnit(w) if w else 0,
                      height=hwp.MiliToHwpUnit(h) if h else 0)
    try:
        hwp.insert_picture(path, **kwargs)
    except TypeError:  # pyhwpx 버전별 시그니처 차이 흡수
        hwp.insert_picture(path)
    return {"picture": path}


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
    "move": op_move,
    "insert_text": op_insert_text,
    "insert_equation": op_insert_equation,
    "edit_equation": op_edit_equation,
    "insert_table": op_insert_table,
    "insert_picture": op_insert_picture,
    "set_cell": op_set_cell,
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
