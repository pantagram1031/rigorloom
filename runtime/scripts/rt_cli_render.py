#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How a tool result looks to a person at the terminal (Korean).

Agents read the compact English text each tool declares (``Tool.text``);
``--json`` prints the result object itself. This module is the third view:
what someone typing ``rigorloom open 보고서.hwpx`` reads. It never decides
anything; it only lays out a result that the registry already produced.
"""
from __future__ import annotations

import re
from typing import Callable

try:  # installed as rigorloom_runtime
    from .rt_term import Term, one_line, path_text, safe_text, truncate, width
except ImportError:  # a checkout, runtime/scripts on sys.path
    from rt_term import Term, one_line, path_text, safe_text, truncate, width

VERB_KO = {
    "open": "열기", "read": "읽기", "find": "찾기", "edit": "고치기", "fill": "채우기",
    "check": "점검", "save": "저장", "preview": "쪽 미리보기", "new": "새 문서",
    "convert": "형식 바꾸기",
}
CHECK_KO = {"style": "문체", "layout": "쪽 배치", "fonts": "글꼴", "guard": "숫자·사실"}
STATE_KO = {"passed": "통과", "failed": "문제 발견", "unavailable": "건너뜀"}
SEVERITY_KO = {"error": "오류", "warning": "주의", "notice": "참고"}
SIGNAL_KO = {
    "lone_heading": "쪽 끝에 홀로 남은 제목", "bottom_heading": "쪽 끝에 붙은 제목",
    "table_split": "두 쪽에 걸친 표", "caption_split": "표·그림과 떨어진 설명",
    "widow": "다음 쪽에 홀로 남은 문단의 마지막 줄", "orphan": "쪽 끝에 홀로 남은 문단의 첫 줄",
    "top_blank": "쪽 위 빈 줄", "approx": "글꼴 대체",
}
KIND_KO = {"heading": "제목", "para": "문단", "table": "표", "place": "칸",
           "cell": "셀", "page": "쪽"}


#: Why a check or verb could not run, as rt_doc names it, in a person's words.
WHY_KO = {
    "engine_not_configured": "한글 엔진이 없어 건너뛰었습니다 (상태 확인: rigorloom doctor)",
    "engine_function_missing": "설치된 엔진은 이 기능을 지원하지 않습니다",
    "rasterizer_missing": "쪽 미리보기를 만들려면 pypdfium2가 필요합니다. 설치: pip install pypdfium2",
    "page_layout_unavailable": "쪽 배치를 계산하려면 한글 엔진이 필요합니다",
}


def shown(path: str) -> str:
    """A path as a person typed it: relative to the current folder when inside it.

    Spaces are kept exactly (Sol re-check F5): a prompt must not show
    "review copy" for "review  copy".
    """
    import os
    raw = str(path)
    if raw.startswith("draft:"):
        return path_text(raw)
    try:
        rel = os.path.relpath(raw)
    except ValueError:  # another drive on Windows
        return path_text(raw)
    return path_text(raw if rel.startswith("..") else rel)


def _q(path: str) -> str:
    return f'"{shown(path)}"'


def _draft_tag(r: dict) -> str | None:
    return f"초안 {r.get('revision')}판" if r.get("source") == "draft" else None


#: rt_doc's own messages are English (it is the engine's layer). A person
#: gets one Korean line per error code; --debug shows the original.
_DOC_ERRORS = {
    "capability_unavailable": ("이 작업은 한글 엔진이 있어야 합니다.",
                               "엔진 상태 확인: rigorloom doctor"),
    "engine_unavailable": ("한글 엔진이 응답하지 않았습니다.", "잠시 뒤 다시 실행하세요."),
    "bad_address": ("주소를 찾지 못했습니다.", "open이나 find 결과에 나온 주소를 쓰세요."),
    "not_found": ("찾지 못했습니다.", "open이나 find 결과에 나온 주소를 쓰세요."),
    "ambiguous_match": ("찾는 말이 여러 곳에 있어 고칠 곳을 정할 수 없습니다.",
                        'at에 고칠 곳의 주소를 지정하거나 "all": true를 추가하세요.'),
    "expect_mismatch": ("읽은 뒤 내용이 바뀌어 고치지 않았습니다.", "다시 읽고 고치세요."),
    "page_out_of_range": ("문서에 없는 쪽입니다.", "open 결과에서 쪽 수를 확인하세요."),
    "locked": ("다른 프로그램이 이 파일을 열고 있습니다.", "한글에서 파일을 닫은 뒤 다시 실행하세요."),
    "source_rejected": ("이 파일은 문서로 열 수 없습니다.", "hwpx 또는 docx 파일을 지정하세요."),
    "invalid_params": ("입력이 맞지 않습니다.", None),
    "engine_refused": ("문서를 처리하지 못했습니다.", None),
}
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|“[^”]*”|‘[^’]*’")


def person_error(err: dict, path: str | None = None) -> tuple[str, str | None]:
    """(message, hint) for a person. Korean errors pass through unchanged."""
    message, hint = err.get("message") or "", err.get("hint")
    # Quoted document text ('근로') does not make an English sentence Korean.
    if _HANGUL.search(_QUOTED.sub("", message)):
        return message, hint
    low = message.lower()
    name = f'"{shown(path)}"' if path else "FILE"
    if ".hwp " in low or "hwp files" in low:
        return ("'.hwp' 파일은 한글 엔진이 있어야 엽니다. .hwpx는 엔진 없이 열 수 있습니다.",
                "한글에서 .hwpx로 저장하거나 엔진 상태를 확인하세요: rigorloom doctor")
    if "markdown" in low and ("new(" in low or "not a document" in low):
        stem = shown(path).rsplit(".", 1)[0] if path else "결과"
        return ("마크다운 파일은 열지 않고 새 문서의 내용으로 씁니다.",
                f'새 문서로 만들기: rigorloom new {name} -o "{stem}.hwpx"')
    span = re.search(r"\((p0\.\.p(\d+))\)", message)
    if span:
        return (f"이 문서의 문단 주소는 p0부터 p{span.group(2)}까지입니다"
                f"{' (' + err['at'] + ' 없음)' if err.get('at') else ''}.",
                f"마지막 문단: rigorloom read {name} --at p{span.group(2)}")
    base, default_hint = _DOC_ERRORS.get(err.get("code", ""), ("문서를 처리하지 못했습니다.", None))
    span = err.get("range")
    if err.get("code") == "bad_address" and isinstance(span, list) and len(span) == 2:
        # A page or offset past the end (doc-core-api ruling 2026-11-19): say the range.
        if str(err.get("at") or "").startswith("page:"):
            base, default_hint = "문서에 없는 쪽입니다.", f"{span[0]}쪽부터 {span[1]}쪽까지 있습니다."
        else:
            base, default_hint = "범위를 벗어난 위치입니다.", f"{span[0]}부터 {span[1]}까지 쓸 수 있습니다."
        hint = None
    if err.get("at") and err.get("code") in ("bad_address", "not_found"):
        base = f"{err['at']}: {base}"
    if hint and not _HANGUL.search(_QUOTED.sub("", hint)):
        hint = None
    return base, hint or default_hint


def candidates_line(items: list) -> str:
    """Candidates on one line; a long run of numbered addresses becomes a range."""
    names = [one_line(str(c)) for c in items]
    if len(names) > 8:
        match = [re.fullmatch(r"(.*?)(\d+)", n) for n in names]
        if all(match) and len({m.group(1) for m in match}) == 1:
            nums = [int(m.group(2)) for m in match]
            prefix = match[0].group(1)
            return f"{prefix}{min(nums)} ~ {prefix}{max(nums)} ({len(names)}개)"
        return ", ".join(names[:8]) + f" 외 {len(names) - 8}개"
    return ", ".join(names)


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
    if _draft_tag(r):
        head.append(_draft_tag(r))
    term.line("  ·  ".join(head))
    draft = r.get("draft") or {}
    if r.get("source") == "disk" and draft.get("sourceChanged"):
        term.line(term.style("초안을 만든 뒤 파일이 바뀌었습니다. 초안은 더 고칠 수 없습니다.", "yellow")
                  + term.dim(f"  (버리기: rigorloom changes discard {_q(r['path'])})"))
    elif r.get("source") == "disk" and draft.get("unsaved"):
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
        # One-cell tables are mostly boxed titles; list them on one line.
        boxes = [t["at"] for t in r["tables"] if (t.get("rows"), t.get("cols")) == (1, 1)
                 and not t.get("caption")]
        term.table([[t["at"], f"{t.get('rows')}×{t.get('cols')}",
                     f"{t['page']}쪽" if t.get("page") else "",
                     safe_text(str(t.get("caption") or ""))] for t in r["tables"]
                    if t["at"] not in boxes], shrink=3)
        if boxes:
            term.line(term.dim(f"셀이 하나인 표(제목 상자 등) {len(boxes)}개: " + ", ".join(boxes)))
    if r.get("places"):
        term.line()
        term.line(term.bold("채울 칸"))
        term.table([[f"place:{p['id']}", p.get("at", ""), safe_text(str(p.get("label", "")))]
                    for p in r["places"]], shrink=2)
    if r.get("personOnly"):
        term.line()
        term.line(term.bold("서명·날인 칸") + term.dim("  fill에서는 이 칸을 비워 둡니다. 저장한 뒤 직접 채우세요."))
        term.table([[f"place:{p['id']}", p.get("at", ""), safe_text(str(p.get("label", "")))]
                    for p in r["personOnly"]], shrink=2)
    if r.get("omitted"):
        parts = {"headings": "제목", "tables": "표", "places": "칸"}
        term.line(term.dim("일부만 표시한 항목: " + ", ".join(
            f"{parts.get(k, k)} {v}개" for k, v in r["omitted"].items())
            + f" (전부 보기: rigorloom read {_q(r['path'])})"))
    missing = [VERB_KO.get(v, v) for v, src in (r.get("capabilities") or {}).items()
               if src == "unavailable"]
    if missing:
        term.line(term.dim("한글 엔진이 필요한 기능: " + ", ".join(missing)))


def show_read(term: Term, r: dict) -> None:
    """Address in a left column, text beside it; runs of empty paragraphs fold."""
    blocks = r["blocks"]
    size = max([width(str(b.get("at", ""))) for b in blocks] + [3]) + 2
    empty: list[str] = []

    def flush() -> None:
        if empty:
            span = empty[0] if len(empty) == 1 else f"{empty[0]}~{empty[-1]}"
            term.line(term.dim(f"{span.ljust(size)}(빈 문단)"))
            empty.clear()

    for b in blocks:
        text = safe_text(str(b.get("text", ""))).rstrip("\n")
        if b.get("kind") == "para" and not text.strip() and not b.get("part"):
            empty.append(str(b["at"]))
            continue
        flush()
        at = str(b.get("at", ""))
        lines = text.split("\n") if text else [""]
        if b.get("kind") not in ("para", "heading", "cell", "place") or b.get("part"):
            label = KIND_KO.get(b.get("kind", ""), b.get("kind", ""))
            part = ""
            if b.get("part"):
                p = b["part"]
                part = f"  {p['from']}–{p['to']}자 / {p['of']}자"
            term.line(term.dim(f"{at.ljust(size)}{label}{part}"))
            for line in lines:
                term.line(" " * size + line)
            continue
        term.line(term.dim(at.ljust(size)) + lines[0])
        for line in lines[1:]:
            term.line(" " * size + line)
    flush()
    if r.get("next"):
        term.line(term.dim(f"이어 읽기: rigorloom read {_q(r['path'])} --cursor {r['next']}"))


def around(text: str, needle: str, limit: int) -> str:
    """``text`` cut to ``limit`` columns with ``needle`` kept in view."""
    text = one_line(text)
    if width(text) <= limit:
        return text
    at = text.lower().find(needle.lower()) if needle else -1
    if at < 0:
        return truncate(text, limit)
    budget = max(limit - width(needle) - 2, 0)
    left = text[:at]
    right = text[at + len(needle):]
    keep_left = budget // 2
    while width(left) > keep_left and left:
        left = left[1:]
    out_left = ("…" + left[1:]) if len(left) < at else left
    room = limit - width(out_left) - width(needle)
    out_right = truncate(right, room) if room > 0 else ""
    return out_left + needle + out_right


def show_find(term: Term, r: dict) -> None:
    term.line(f"{r['total']}곳" + term.dim(f"  ({one_line(r['query'])})"))
    rows = [[h["at"], f"{h['page']}쪽" if h.get("page") else "",
             safe_text(str(h.get("context") or h.get("text", "")))] for h in r["hits"]]
    if rows:
        fixed = max(width(row[0]) for row in rows) + max(width(row[1]) for row in rows) + 4
        room = max(term.columns - fixed, 12)
        needle = "" if r.get("regex") else one_line(r["query"])
        for h, row in zip(r["hits"], rows):
            needle_here = str(h.get("match") or needle)
            row[2] = around(row[2], needle_here, room)
    term.table(rows, shrink=2)
    if r.get("truncated"):
        term.line(term.dim(f"… {r['total'] - len(r['hits'])}곳 더 (--limit로 늘리기)"))


def show_staged(term: Term, r: dict) -> None:
    term.line(f"초안 {r['revision']}판에 반영했습니다."
              + term.dim("  원본 파일은 save 전까지 그대로입니다."))
    if r.get("filled"):
        term.line("채운 칸: " + ", ".join(
            f"{f['place']} ← \"{truncate(one_line(str(f['text'])), 24)}\"" for f in r["filled"][:8]))
    elif r.get("applied"):
        where = []
        for a in r["applied"]:
            at = a.get("at") if isinstance(a, dict) else None
            if at and at not in where:
                where.append(str(at))
        if where:
            term.line("고친 곳: " + ", ".join(where[:12]))
    if r.get("changedPages"):
        term.line("바뀐 쪽: " + ", ".join(map(str, r["changedPages"])))
    if r.get("remap"):
        moved = [f"{m['from']}→{m['to'] or '지움'}" for m in r["remap"][:12]]
        term.line(term.dim("주소가 바뀐 곳: " + ", ".join(moved)))
    _signals(term, r.get("signals") or [])
    if r.get("unfilled"):
        term.line("아직 비어 있는 칸: " + ", ".join(r["unfilled"][:12]))
    if r.get("skipped"):
        term.line(term.style("채우지 않은 서명·날인 칸 (직접 채우세요): "
                             + ", ".join(r["skipped"]), "yellow"))
    elif r.get("personOnly"):
        term.line(term.dim("서명·날인 칸 (직접 채우세요): " + ", ".join(r["personOnly"])))
    path = r["path"]
    save = (f"rigorloom save {_q(path)} --to 새이름.hwpx" if path.startswith("draft:")
            else f"rigorloom save {_q(path)}")
    term.line(term.dim(f"초안 보기  rigorloom read {_q(path)} --source draft"))
    term.line(term.dim(f"점검       rigorloom check {_q(path)} --source draft"))
    term.line(term.dim(f"저장       {save}"))


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
    term.line(one_line(shown(r["path"])) + (f"  ·  {_draft_tag(r)}" if _draft_tag(r) else ""))
    term.line("  ·  ".join(cells))
    rows = []
    for f in r["findings"]:
        where = f.get("at") or (f"{f['page']}쪽" if f.get("page") else "")
        text = safe_text(str(f.get("message") or f.get("why") or ""))
        if f.get("suggest"):
            text += f" ({safe_text(str(f['suggest']))})"
        rows.append([SEVERITY_KO.get(f.get("severity", ""), f.get("severity", "")), where,
                     one_line(text)])
    if rows:
        # Findings wrap instead of being cut: the changed words are often at the end.
        term.line()
        left = max(width(row[0]) for row in rows) + 2
        mid = max(width(row[1]) for row in rows) + 2
        room = max(term.columns - left - mid, 20)
        for sev, where, text in rows:
            chunks = wrap(text, room)
            term.line(sev.ljust(left - (width(sev) - len(sev))) +
                      where + " " * (mid - width(where)) + chunks[0])
            for chunk in chunks[1:]:
                term.line(" " * (left + mid) + chunk)
    if r.get("truncated"):
        term.line(term.dim(f"… {r['truncated']}개 더 (전부 보기: --json)"))
    unavailable = [n for n, c in r["checks"].items() if c["state"] == "unavailable"]
    for name in unavailable:
        check = r["checks"][name]
        reason = WHY_KO.get(check.get("why") or "") or check.get("reason")
        if reason:
            term.line(term.dim(f"{CHECK_KO.get(name, name)}: {one_line(str(reason))}"))
    if r.get("pass") is None:
        term.line(term.style("실행한 점검이 없어 통과 여부를 판단할 수 없습니다.", "yellow"))


def show_save(term: Term, r: dict) -> None:
    if r["replaced"]:
        term.line(f"저장했습니다: {shown(r['saved'])} (이전 내용은 저장 기록에 보관)")
    else:
        term.line(f"새 파일로 저장했습니다: {shown(r['saved'])}")
    if r.get("lossy"):
        term.line(term.style("변환하면서 빠진 항목: ", "yellow") + ", ".join(r["lossy"]))
    if r.get("unreviewed"):
        term.line(term.dim(f"에이전트가 고치고 아직 아무도 확인하지 않은 변경 {r['unreviewed']}건도 "
                           "함께 저장했습니다."))
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
    d = r["draft"]
    state = "저장 안 한 내용 있음" if d.get("unsaved") else "파일과 같음"
    if d.get("sourceChanged"):
        state = "초안을 만든 뒤 파일이 바뀜"
    term.line(f"{term.bold(shown(r['path']))}  ·  초안 {d['revision']}판  ·  {state}")
    status = {"proposed": "저장 안 함", "applied": "저장됨", "rejected": "거절됨",
              "withdrawn": "철회됨"}
    if r["changesets"]:
        term.line()
        term.line(term.bold("초안 편집 기록"))
        term.table([[f"{c.get('revision')}판", VERB_KO.get(c["kind"], c["kind"]),
                     status.get(c["status"], c["status"]),
                     _when(c.get("created")), _who(c),
                     ("바뀐 쪽 " + ", ".join(map(str, c["changedPages"])))
                     if c.get("changedPages") else ""]
                    for c in r["changesets"]], shrink=5)
    if r.get("saves"):
        term.line()
        term.line(term.bold("저장 기록"))
        term.table([[_when(v.get("at")), shown(str(v.get("target", ""))),
                     f"초안 {v.get('revision')}판"] for v in r["saves"]], shrink=1)
        term.line(term.dim(f"마지막 저장 되돌리기: rigorloom undo {_q(r['saves'][-1]['target'])}"))
    if d.get("unsaved"):
        term.line(term.dim(f"저장: rigorloom save {_q(r['path'])}   "
                           f"버리기: rigorloom changes discard {_q(r['path'])}"))


def _when(stamp: str | None) -> str:
    """``2026-11-19T03:27:48Z`` → ``11-19 03:27 UTC`` (the record keeps UTC)."""
    if not stamp or "T" not in stamp:
        return stamp or ""
    day, time = stamp.rstrip("Z").split("T", 1)
    return f"{day[5:]} {time[:5]} UTC"


def _who(c: dict) -> str:
    if c.get("author") == "cli":
        return "터미널"
    agents = (c.get("provenance") or {}).get("agent") or c.get("author") or ""
    return f"에이전트 {agents}".strip() + (" (시험용)" if (c.get("provenance") or {}).get("mock") else "")


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


def wrap(text: str, limit: int) -> list[str]:
    """Split ``text`` into lines of at most ``limit`` columns (Korean-width aware)."""
    out, line, used = [], [], 0
    for word in text.split(" "):
        w = width(word)
        if line and used + 1 + w > limit:
            out.append(" ".join(line))
            line, used = [], 0
        while w > limit:  # one word longer than a line
            head = truncate(word, limit, ellipsis="")
            out.append(head)
            word = word[len(head):]
            w = width(word)
        line.append(word)
        used += (1 if used else 0) + w
    out.append(" ".join(line))
    return out
