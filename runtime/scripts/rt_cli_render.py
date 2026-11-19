#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How a tool result looks to a person at the terminal (Korean).

Agents read the compact English text each tool declares (``Tool.text``);
``--json`` prints the result object itself. This module is the third view:
what someone typing ``rigorloom open 보고서.hwpx`` reads. It never decides
anything; it only lays out a result that the registry already produced.
"""
from __future__ import annotations

from typing import Callable

try:  # installed as rigorloom_runtime
    from .rt_term import Term, one_line, safe_text
except ImportError:  # a checkout, runtime/scripts on sys.path
    from rt_term import Term, one_line, safe_text

VERB_KO = {
    "open": "열기", "read": "읽기", "find": "찾기", "edit": "고치기", "fill": "채우기",
    "check": "점검", "save": "저장", "preview": "쪽 보기", "new": "새 문서",
    "convert": "형식 바꾸기",
}
CHECK_KO = {"style": "문체", "layout": "쪽 배치", "fonts": "글꼴", "guard": "사실 보존"}
STATE_KO = {"passed": "통과", "failed": "걸림", "unavailable": "못 함"}
SEVERITY_KO = {"error": "오류", "warning": "주의", "notice": "참고"}
SIGNAL_KO = {
    "lone_heading": "쪽 끝에 홀로 남은 제목", "bottom_heading": "쪽 끝에 붙은 제목",
    "table_split": "두 쪽에 걸친 표", "caption_split": "표·그림과 떨어진 설명",
    "widow": "다음 쪽 첫 줄에 남은 한 줄", "orphan": "쪽 끝에 남은 한 줄",
    "top_blank": "쪽 위 빈 줄", "approx": "글꼴 대체",
}
KIND_KO = {"heading": "제목", "para": "문단", "table": "표", "place": "칸",
           "cell": "칸", "page": "쪽"}


#: Why a check or verb could not run, as rt_doc names it, in a person's words.
WHY_KO = {
    "engine_not_configured": "한글 엔진이 설치되어 있지 않습니다 (설치: rigorloom engine)",
    "engine_function_missing": "설치된 엔진에 아직 없는 기능입니다",
    "rasterizer_missing": "쪽 그림에는 pypdfium2가 필요합니다 (pip install pypdfium2)",
    "page_layout_unavailable": "쪽 배치는 한글 엔진이 있어야 계산합니다",
}


def shown(path: str) -> str:
    """A path as a person typed it: relative to the current folder when inside it."""
    import os
    text = str(path)
    if text.startswith("draft:"):
        return text
    try:
        rel = os.path.relpath(text)
    except ValueError:  # another drive on Windows
        return text
    return text if rel.startswith("..") else rel


def _q(path: str) -> str:
    return f'"{shown(path)}"'


def _rev(r: dict) -> str:
    return f"판 {r.get('rev')}"


def _fonts(term: Term, fonts: dict) -> None:
    subs = (fonts or {}).get("substituted") or []
    if subs:
        pairs = ", ".join(f"{s.get('want')} → {s.get('got')}" for s in subs[:6])
        term.line(term.dim(f"글꼴 대체: {pairs} (쪽 나눔이 한글과 다를 수 있습니다)"))


def _signals(term: Term, signals: list) -> None:
    if not signals:
        return
    items = []
    for s in signals[:12]:
        kind = s.get("kind") if isinstance(s, dict) else s
        page = s.get("page") if isinstance(s, dict) else None
        items.append((f"{page}쪽 " if page else "") + SIGNAL_KO.get(kind, str(kind)))
    term.line(term.style("쪽 배치: ", "yellow") + ", ".join(items))


def show_open(term: Term, r: dict) -> None:
    head = [term.bold(one_line(shown(r["path"])))]
    if r.get("format"):
        head.append(str(r["format"]))
    if r.get("pages"):
        head.append(f"{r['pages']}쪽")
    head.append(_rev(r))
    if r.get("source") == "draft":
        head.append(f"초안 {r.get('revision')}판")
    term.line("  ·  ".join(head))
    draft = r.get("draft") or {}
    if r.get("source") == "disk" and draft.get("unsaved"):
        term.line(term.style(f"저장 안 한 초안 있음 ({draft['revision']}판)", "yellow")
                  + term.dim(f"  (초안 보기: rigorloom open {_q(r['path'])} --source draft)"))
    _fonts(term, r.get("fonts") or {})
    if r.get("headings"):
        term.line()
        term.line(term.bold("제목"))
        term.table([[h["at"], str(h.get("level", "")), safe_text(str(h.get("text", "")))]
                    for h in r["headings"]], shrink=2)
    if r.get("tables"):
        term.line()
        term.line(term.bold("표"))
        term.table([[t["at"], f"{t.get('rows')}×{t.get('cols')}",
                     f"{t['page']}쪽" if t.get("page") else "",
                     safe_text(str(t.get("caption") or ""))] for t in r["tables"]], shrink=3)
    if r.get("places"):
        term.line()
        term.line(term.bold("채울 칸"))
        term.table([[f"place:{p['id']}", p.get("at", ""), safe_text(str(p.get("label", "")))]
                    for p in r["places"]], shrink=2)
    if r.get("personOnly"):
        term.line()
        term.line(term.bold("서명·날인 칸") + term.dim("  직접 채우세요"))
        term.table([[f"place:{p['id']}", safe_text(str(p.get("label", "")))]
                    for p in r["personOnly"]], shrink=1)
    if r.get("omitted"):
        parts = {"headings": "제목", "tables": "표", "places": "칸"}
        term.line(term.dim("길어서 뺀 것: " + ", ".join(
            f"{parts.get(k, k)} {v}개" for k, v in r["omitted"].items())
            + " (rigorloom read, find로 보세요)"))
    missing = [VERB_KO.get(v, v) for v, src in (r.get("capabilities") or {}).items()
               if src == "unavailable"]
    if missing:
        term.line(term.dim("이 설치에서 안 되는 것: " + ", ".join(missing)
                           + " (엔진 설치: rigorloom engine)"))


def show_read(term: Term, r: dict) -> None:
    for b in r["blocks"]:
        label = KIND_KO.get(b.get("kind", ""), b.get("kind", ""))
        part = ""
        if b.get("part"):
            p = b["part"]
            part = f"  {p['from']}–{p['to']}자 / {p['of']}자"
        term.line(term.dim(f"[{b['at']}] {label}{part}"))
        term.line(b.get("text", ""))
    if r.get("next"):
        term.line(term.dim(f"더 있습니다: rigorloom read {_q(r['path'])} --cursor {r['next']}"))


def show_find(term: Term, r: dict) -> None:
    term.line(f"{r['total']}곳" + term.dim(f"  ({one_line(r['query'])})"))
    term.table([[h["at"], f"{h['page']}쪽" if h.get("page") else "",
                 safe_text(str(h.get("context") or h.get("text", "")))] for h in r["hits"]],
               shrink=2)
    if r.get("truncated"):
        term.line(term.dim(f"… {r['total'] - len(r['hits'])}곳 더 (--limit로 늘리기)"))


def show_staged(term: Term, r: dict) -> None:
    term.line(f"초안에 반영했습니다. {r['revision']}판, {_rev(r)}"
              + term.dim("  아직 파일에는 저장하지 않았습니다."))
    if r.get("changedPages"):
        term.line("바뀐 쪽: " + ", ".join(map(str, r["changedPages"])))
    if r.get("remap"):
        moved = [f"{m['from']}→{m['to'] or '지움'}" for m in r["remap"][:12]]
        term.line(term.dim("주소가 바뀐 곳: " + ", ".join(moved)))
    _signals(term, r.get("signals") or [])
    if r.get("unfilled"):
        term.line("아직 빈 칸: " + ", ".join(r["unfilled"][:12]))
    if r.get("skipped"):
        term.line(term.style("채우지 않음(직접 채울 칸): " + ", ".join(r["skipped"]), "yellow"))
    elif r.get("personOnly"):
        term.line("직접 채울 칸: " + ", ".join(r["personOnly"]))
    path = r["path"]
    save = (f"rigorloom save {_q(path)} --to 새이름.hwpx" if path.startswith("draft:")
            else f"rigorloom save {_q(path)}")
    term.line(term.dim(f"점검  rigorloom check {_q(path)} --source draft"))
    term.line(term.dim(f"저장  {save}"))


def show_preview(term: Term, r: dict) -> None:
    for image in r["images"]:
        term.line(f"{image['page']}쪽  {image['file']}")
    _signals(term, r.get("signals") or [])
    _fonts(term, r.get("fonts") or {})
    if r.get("morePages"):
        term.line(term.dim("한 번에 3쪽까지 보여 줍니다. 남은 쪽: "
                           + ", ".join(map(str, r["morePages"]))))


def show_check(term: Term, r: dict) -> None:
    cells = []
    for name, c in r["checks"].items():
        state = STATE_KO.get(c["state"], c["state"])
        color = {"passed": "green", "failed": "red"}.get(c["state"], "dim")
        cells.append(f"{CHECK_KO.get(name, name)} {term.style(state, color)}")
    term.line(f"{one_line(shown(r['path']))}  {_rev(r)}")
    term.line("   ".join(cells))
    rows = []
    for f in r["findings"]:
        where = f.get("at") or (f"{f['page']}쪽" if f.get("page") else "")
        text = safe_text(str(f.get("message") or f.get("why") or ""))
        if f.get("suggest"):
            text += f" ({safe_text(str(f['suggest']))})"
        rows.append([SEVERITY_KO.get(f.get("severity", ""), f.get("severity", "")), where,
                     text])
    if rows:
        term.line()
        term.table(rows, shrink=2)
    if r.get("truncated"):
        term.line(term.dim(f"… {r['truncated']}개 더 (--json으로 전부 보기)"))
    unavailable = [n for n, c in r["checks"].items() if c["state"] == "unavailable"]
    for name in unavailable:
        check = r["checks"][name]
        reason = WHY_KO.get(check.get("why") or "") or check.get("reason")
        if reason:
            term.line(term.dim(f"{CHECK_KO.get(name, name)}: {one_line(str(reason))}"))
    if r.get("pass") is None:
        term.line(term.style("이 파일은 여기서 점검할 수 있는 것이 없었습니다.", "yellow"))


def show_save(term: Term, r: dict) -> None:
    verb = "덮어썼습니다" if r["replaced"] else "새로 만들었습니다"
    term.line(f"저장했습니다: {shown(r['saved'])} ({verb})")
    if r.get("lossy"):
        term.line(term.style("형식을 바꾸며 빠진 것: ", "yellow") + ", ".join(r["lossy"]))
    if r.get("unreviewed"):
        term.line(term.dim(f"사람이 검토하지 않은 변경 묶음 {r['unreviewed']}개가 함께 저장되었습니다."))
    if r.get("undo"):
        term.line(term.dim(f"되돌리기: rigorloom undo {_q(r['saved'])}"))


def show_changes(term: Term, r: dict) -> None:
    if "drafts" in r:
        if not r["drafts"]:
            term.line("초안이 없습니다.")
            return
        term.table([[safe_text(shown(d["source"]) if d.get("source")
                               else str(d.get("name") or "(새 문서)")),
                     f"{d['revision']}판", f"저장 안 한 변경 {d['pending']}",
                     f"저장 {d['saved']}번"] for d in r["drafts"]], shrink=0)
        return
    if not r.get("draft"):
        term.line(f"{shown(r['path'])}: 초안이 없습니다.")
        return
    term.line(f"{shown(r['path'])}: 초안 {r['draft']['revision']}판, "
              f"변경 묶음 {len(r['changesets'])}개")
    status = {"proposed": "검토 대기", "applied": "저장됨", "rejected": "거절됨",
              "withdrawn": "철회됨"}
    term.table([[c["id"], VERB_KO.get(c["kind"], c["kind"]),
                 status.get(c["status"], c["status"]), f"작업 {c['ops']}개",
                 ", ".join(map(str, c.get("changedPages") or []))]
                for c in r["changesets"]])


def show_guide(term: Term, r: dict) -> None:
    if r.get("text"):
        term.line(r["text"].rstrip())
    else:
        term.line("주제: " + ", ".join(r.get("topics", [])))


SHOW: dict[str, Callable[[Term, dict], None]] = {
    "open": show_open, "read": show_read, "find": show_find, "edit": show_staged,
    "fill": show_staged, "new": show_staged, "preview": show_preview,
    "check": show_check, "save": show_save, "changes": show_changes, "guide": show_guide,
}
