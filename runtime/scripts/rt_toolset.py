#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The eleven document tools, declared once for the CLI, MCP and the agent.

open · read · find · edit · fill · new · preview · check · save · changes · guide

Every tool reaches documents only through ``rt_doc`` (the document layer) and
writes only into the state directory, except ``save``, which goes through
:func:`rt_commit.commit`, the one writer into a person's folder.

Agent surfaces (MCP, the agent loop) read a document's DRAFT head when one
exists; the person's CLI reads the file on disk and mentions the draft. The
``source`` and ``revision`` fields in every result say which one was read.

Model-facing text (``description``) is English and short: it is read on every
turn. People-facing text (titles, messages, hints) is Korean.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

try:  # installed as rigorloom_runtime
    from . import rt_commit
    from .rt_drafts import Input, Ref, is_virtual, rev_of, summary
    from .rt_paths import (PathRefused, canonical, check_readable, mark_state, private_dir,
                           sha256_file)
    from .rt_term import one_line, path_text, safe_text, shell_arg
    from .rt_tools import Context, Tool, ToolError, doc_call, register, sibling
except ImportError:  # a checkout, runtime/scripts on sys.path
    import rt_commit
    from rt_drafts import Input, Ref, is_virtual, rev_of, summary
    from rt_paths import (PathRefused, canonical, check_readable, mark_state, private_dir,
                          sha256_file)
    from rt_term import one_line, path_text, safe_text, shell_arg
    from rt_tools import Context, Tool, ToolError, doc_call, register, sibling

READ_DEFAULT_CHARS = 6000
READ_MAX_CHARS = 20000
OPEN_BUDGET_CHARS = 6000
FIND_DEFAULT_LIMIT = 50
CHECK_MAX_FINDINGS = 60
PREVIEW_MAX_PAGES = 3
EDIT_MAX_OPS = 200

FORMATS_IN = ("hwpx", "hwp", "docx", "md")
FORMATS_OUT = ("hwpx", "hwp", "pdf", "png", "md", "docx")

#: Labels a person signs, seals or stamps. Agents never fill these; they are
#: listed so the person knows what is left for them.
#: Seats only the person fills: signature, seal, and the date of approval.
PERSON_ONLY = re.compile(r"(서명|날인|직인|도장|\(인\)|（인）|인\s*\)|sign(ature)?\b"
                         r"|(결재|승인)\s*(일|일자|날짜|일시)|approv(al|ed)\s*date)",
                         re.IGNORECASE)

REV_PATTERN = "^[0-9a-f]{12}$"

# ---------------------------------------------------------------------------
# shared schema pieces
# ---------------------------------------------------------------------------

S_PATH = {"type": "string", "minLength": 1, "maxLength": 4096,
          "description": "Document path (.hwpx .hwp .docx .md), or draft:<id> "
                         "for a document made with `new`."}
S_REV = {"type": "string", "pattern": REV_PATTERN,
         "description": "The `rev` you last read (12 hex). Edits on a "
                        "different revision are refused as stale."}
S_AT = {"type": "string", "minLength": 1, "maxLength": 300,
        "description": "Address: p12, t3, t3/r2/c1, t3/r2/c1/p0, "
                       "h:\"heading text\", place:<id>."}

O_DOCREF = {
    "path": {"type": "string"},
    "rev": {"type": "string"},
    "source": {"type": "string", "enum": ["draft", "disk"]},
    "revision": {"type": "integer"},
}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required or [], "additionalProperties": False}


def _out(props: dict) -> dict:
    # Results may grow fields; agents rely on the documented ones.
    return {"type": "object", "properties": props}


# ---------------------------------------------------------------------------
# resolution: which file, which draft, may we touch it
# ---------------------------------------------------------------------------

_REFUSAL_HINTS = {
    "outside_roots": "이 폴더를 허용하려면 사용자에게 MCP 설정에 --allow <폴더>를 추가해 달라고 요청하세요.",
    "not_found": "상대 경로는 작업 폴더를 기준으로 합니다. 경로가 맞는지 사용자에게 확인하세요.",
}


def resolve(ctx: Context, raw: str) -> Ref:
    """A Ref for ``raw``, after the roots check. Refuses what may not be read."""
    if is_virtual(raw):
        ref = ctx.drafts.ref(raw)
        source = ((ctx.drafts.load(ref) or {}).get("source") or {}).get("path")
        if source is None:
            return ref  # made with `new`: no file behind it to confine
        # A draft of a file is that file: the same roots apply to its id.
        try:
            path = ctx.roots.check(source) if ctx.roots is not None else canonical(source)
        except PathRefused as exc:
            raise ToolError(exc.code, exc.message, hint=exc.hint or _REFUSAL_HINTS.get(exc.code),
                            at=raw) from exc
        return type(ref)(ref.key, path)
    try:
        path = ctx.roots.check(raw) if ctx.roots is not None else canonical(raw)
        check_readable(path)
    except PathRefused as exc:
        hint = exc.hint or _REFUSAL_HINTS.get(exc.code)
        raise ToolError(exc.code, exc.message, hint=hint, at=exc.path) from exc
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in FORMATS_IN:
        raise ToolError("unsupported_format",
                        f"'{path.suffix or '(확장자 없음)'}' 형식의 파일은 열 수 없습니다.",
                        hint=".hwpx, .hwp, .docx, .md 중 한 형식으로 된 파일을 선택하세요.", at=str(path))
    return ctx.drafts.ref(path, scope=ctx.draft_scope)


def current(ctx: Context, ref: Ref) -> Input:
    return ctx.drafts.input_for(ref, use_draft=(ctx.source == "draft"))


def _docref(ref: Ref, inp: Input) -> dict:
    return {"path": ref.label, "rev": inp.rev, "source": inp.source,
            "revision": inp.revision}


def _provenance(ctx: Context) -> dict:
    out = {"client": ctx.client}
    out.update(ctx.provenance or {})
    out.setdefault("mock", False)
    return out


#: Every way markdown can pull in a file: inline images, reference
#: definitions, and HTML <img>. Each target is checked and made absolute, so
#: the document layer resolves exactly the file that was checked.
_ASSET_PATTERNS = (
    re.compile(r"(!\[[^\]]*\]\()(<[^>]*>|[^)\s]+)"),
    re.compile(r"(?m)(^[ \t]{0,3}\[[^\]]+\]:[ \t]*)(<[^>]*>|\S+)"),
    re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*["']?)([^"'\s>]+)""", re.IGNORECASE),
)


def _gate_markdown_assets(ctx: Context, markdown: str, base: Path | None) -> str:
    """Markdown with every file it pulls in checked against the roots and absolute.

    A reference definition can also be a plain link; it is checked the same
    way, which may refuse a link that only looks like a path. That is the
    safe side.
    """
    def fix(match: re.Match, paren: bool = False) -> str:
        target = match.group(2).strip("<>")
        if target.startswith("#"):
            return match.group(0)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) and \
                not re.match(r"^[a-z]:[\\/]", target, re.IGNORECASE):
            if re.match(r"^(https?|mailto):", target, re.IGNORECASE) and \
                    not match.group(1).startswith(("!", "<")):
                return match.group(0)  # a plain link in a reference definition
            raise ToolError("invalid_params",
                            f"그림을 파일 경로 대신 주소로 지정했습니다({target}).",
                            hint="허용한 폴더에 그림을 내려받고 그 파일의 경로를 입력하세요.")
        try:
            path = (ctx.roots.check(target, base=base) if ctx.roots is not None
                    else canonical(target, base=base))
        except PathRefused as exc:
            raise ToolError(exc.code, f"이 그림 경로는 사용할 수 없습니다({target}).",
                            hint=exc.hint or "사용자에게 허용된 폴더 안에 있는 그림 파일의 경로를 알려 달라고 요청하세요.",
                            at=exc.path) from exc
        text = str(path).replace("\\", "/")
        if paren:  # keep the spelling the converter's own syntax used
            return match.group(1) + (f"<{text}>" if match.group(2).startswith("<") else text)
        if " " in text and not match.group(1).lower().startswith("<img"):
            text = f"<{text}>"  # CommonMark: a destination with spaces goes in <>
        return match.group(1) + text
    for pattern in _ASSET_PATTERNS:
        markdown = pattern.sub(fix, markdown)
    # The converter reads more than CommonMark (a "[그림 1] 제목 (그림.png)"
    # caption line, for one). Any image file named in parentheses gets the
    # same check and is made absolute, whatever syntax it sits in.
    return _IMAGE_IN_PARENS.sub(lambda m: fix(m, paren=True), markdown)


_IMAGE_EXT = r"(?:png|jpe?g|gif|bmp|tiff?|webp|svg|emf|wmf)"
_IMAGE_IN_PARENS = re.compile(
    r"(\(\s*)(<[^<>\n]*\." + _IMAGE_EXT + r">|[^()\s<>][^()\n<>]*?\." + _IMAGE_EXT + r")(?=\s*\))",
    re.IGNORECASE)


def is_person_only(place: dict) -> bool:
    label = f"{place.get('label') or ''} {place.get('id') or ''}"
    return bool(PERSON_ONLY.search(label)) or place.get("kind") in ("signature", "seal",
                                                                    "approval_date")


# ---------------------------------------------------------------------------
# open
# ---------------------------------------------------------------------------

def _run_open(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    inp = current(ctx, ref)
    info = doc_call(ctx.doc.open, str(inp.path))
    outline = doc_call(ctx.doc.outline, str(inp.path))
    headings = outline.get("headings", [])
    tables = outline.get("tables", [])
    places = outline.get("places", [])
    person = [p for p in places if is_person_only(p)]
    fillable = [p for p in places if not is_person_only(p)]
    result: dict[str, Any] = {
        **_docref(ref, inp),
        "format": info.get("format"),
        "pages": info.get("pages"),
        "sections": info.get("sections"),
        "fonts": info.get("fonts", {}),
        "engine": info.get("engine"),
        "draft": inp.draft,
        "headings": headings,
        "tables": tables,
        "places": fillable,
        "personOnly": person,
        "capabilities": capability_row(ctx, info.get("format") or ""),
    }
    # Budget: drop from the longest lists until the compact text fits, and say
    # how much was left out so the agent knows to ask with `read`.
    omitted: dict[str, int] = {}
    for key in ("places", "tables", "headings"):
        while len(_open_text(result)) > OPEN_BUDGET_CHARS and result[key]:
            keep = max(0, len(result[key]) - max(1, len(result[key]) // 4))
            omitted[key] = omitted.get(key, 0) + len(result[key]) - keep
            result[key] = result[key][:keep]
    if omitted:
        result["omitted"] = omitted
    return result


def _fonts_line(fonts: dict) -> str | None:
    subs = fonts.get("substituted") or []
    if not subs:
        return None
    pairs = ", ".join(f"{s.get('want')}→{s.get('got')}" for s in subs[:6])
    return f"fonts substituted: {pairs} (page breaks may differ from Hancom)"


def _open_text(r: dict) -> str:
    lines = [f"{r['path']}  rev {r['rev']}  {r.get('format') or ''}"
             + (f"  {r['pages']} pages" if r.get("pages") else "")
             + (f"  [draft revision {r['revision']}]" if r["source"] == "draft" else "")]
    draft = r.get("draft")
    if r["source"] == "disk" and draft and draft.get("unsaved"):
        lines.append(f"draft exists: revision {draft['revision']}, not saved")
    fl = _fonts_line(r.get("fonts") or {})
    if fl:
        lines.append(fl)
    if r.get("headings"):
        lines.append("headings:")
        for h in r["headings"]:
            page = f"  p.{h['page']}" if h.get("page") else ""
            lines.append(f"  {h['at']}  L{h.get('level', '?')}  "
                         f"{one_line(str(h.get('text', '')))[:80]}{page}")
    if r.get("tables"):
        lines.append("tables:")
        for t in r["tables"]:
            cap = f"  {one_line(str(t['caption']))[:60]}" if t.get("caption") else ""
            page = f"  p.{t['page']}" if t.get("page") else ""
            lines.append(f"  {t['at']}  {t.get('rows')}x{t.get('cols')}{page}{cap}")
    if r.get("places"):
        lines.append("places (fill these by id):")
        for p in r["places"]:
            lines.append(f"  place:{p['id']}  {p.get('at', '')}  "
                         f"{one_line(str(p.get('label', '')))[:50]}")
    if r.get("personOnly"):
        lines.append("person-only seats (never fill): " + ", ".join(
            f"place:{p['id']}" for p in r["personOnly"]))
    if r.get("omitted"):
        lines.append("omitted for size: " + ", ".join(
            f"{k} {v}" for k, v in r["omitted"].items()) + " (use read/find)")
    caps = r.get("capabilities") or {}
    missing = [v for v, src in caps.items() if src == "unavailable"]
    if missing:
        lines.append("unavailable here: " + ", ".join(missing))
    return "\n".join(lines)


register(Tool(
    name="open", title="문서 열기",
    description="Open a document: revision, pages, fonts, headings, tables and "
                "fillable places with their addresses, and whether a draft "
                "exists. Start every task here.",
    group="read",
    input_schema=_obj({"path": S_PATH}, ["path"]),
    output_schema=_out({**O_DOCREF, "headings": {"type": "array"},
                        "tables": {"type": "array"}, "places": {"type": "array"},
                        "personOnly": {"type": "array"}, "draft": {}}),
    run=_run_open, text=_open_text, budget_chars=OPEN_BUDGET_CHARS + 500,
))


# ---------------------------------------------------------------------------
# capability matrix
# ---------------------------------------------------------------------------

#: verb -> formats the built-in path (no engine) serves. Everything else needs
#: the engine. rt_doc.capabilities(), when present, is the authority.
_BUILTIN = {
    "open": {"hwpx"}, "read": {"hwpx"}, "find": {"hwpx"},
    "edit": {"hwpx"}, "fill": {"hwpx"}, "check": {"hwpx", "md"},
    "save": {"hwpx"}, "preview": set(), "new": set(), "convert": set(),
}


def capability_row(ctx: Context, fmt: str) -> dict[str, str]:
    caps = getattr(ctx.doc, "capabilities", None)
    if callable(caps):
        try:
            got = caps()
            verbs = got.get("verbs") if isinstance(got, dict) else None
            if isinstance(verbs, dict):
                return {verb: (cells.get(fmt) or "unavailable")
                        for verb, cells in verbs.items() if isinstance(cells, dict)}
        except Exception:  # noqa: BLE001 - fall back to the static table
            pass
    engine = False
    status = getattr(ctx.doc, "engine_status", None)
    if callable(status):
        try:
            engine = bool((status() or {}).get("available"))
        except Exception:  # noqa: BLE001 - unknown means not available
            engine = False
    return {verb: ("engine" if engine else
                   ("builtin" if fmt in fmts else "unavailable"))
            for verb, fmts in _BUILTIN.items()}


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

def _grid_markdown(grid: list) -> str:
    rows = [[safe_text(str(c)).replace("|", "\\|").replace("\n", " ") for c in row]
            for row in grid]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _block_text(block: dict) -> str:
    grid = block.get("cells", block.get("grid"))
    if block.get("kind") == "table" and isinstance(grid, list):
        return _grid_markdown(grid)
    return safe_text(str(block.get("text") or ""))


#: Block fields the read budget replaces with ``text`` (and ``part``).
_BULKY = frozenset({"text", "grid", "cells", "runs"})


def _scope(at: str | None) -> str:
    """Which part of the document a cursor walks (the whole of it, or `at`)."""
    import hashlib
    return hashlib.sha256((at or "").encode("utf-8")).hexdigest()[:6]


def _parse_cursor(cursor: str, rev: str, at: str | None, blocks: list) -> tuple[int, int]:
    bad = ToolError("invalid_params", "이어 읽을 위치의 형식이 맞지 않습니다.",
                    hint="이전 read 결과의 이어 읽기 값을 그대로 입력하세요. 주소(at)도 이전과 같아야 합니다.")
    try:
        crev, scope, index, offset = cursor.split(":")
        index_i, offset_i = int(index), int(offset)
    except ValueError:
        raise bad from None
    if crev != rev:
        raise ToolError("stale", "읽던 사이 문서가 바뀌었습니다.",
                        hint="이어 읽기 값을 빼고 처음부터 다시 읽으세요.", retryable=True,
                        data={"reason": "superseded_by_newer_candidate"})
    if scope != _scope(at) or not 0 <= index_i < len(blocks) \
            or not 0 <= offset_i <= len(_block_text(blocks[index_i])):
        raise bad
    return index_i, offset_i


def _run_read(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    inp = current(ctx, ref)
    budget = min(args.get("max_chars", READ_DEFAULT_CHARS), READ_MAX_CHARS)
    data = doc_call(ctx.doc.read, str(inp.path), args.get("at"),
                    with_runs=bool(args.get("with_runs", False)))
    blocks = data.get("blocks", [])
    start, offset = (_parse_cursor(args["cursor"], inp.rev, args.get("at"), blocks)
                     if args.get("cursor") else (0, 0))
    scope = _scope(args.get("at"))
    out: list[dict] = []
    used = 0
    index = start
    next_cursor = None
    while index < len(blocks):
        block = blocks[index]
        text = _block_text(block)
        piece = text[offset:]
        room = budget - used
        if len(piece) > room:
            if out and room < 200:
                next_cursor = f"{inp.rev}:{scope}:{index}:{offset}"
                break
            take = max(room, 1)
            item = {k: v for k, v in block.items() if k not in _BULKY}
            item.update(text=piece[:take], part={"from": offset, "to": offset + take,
                                                 "of": len(text)})
            out.append(item)
            next_cursor = f"{inp.rev}:{scope}:{index}:{offset + take}"
            break
        item = {k: v for k, v in block.items() if k not in _BULKY - {"runs"}}
        item["text"] = piece
        if offset:
            item["part"] = {"from": offset, "to": len(text), "of": len(text)}
        out.append(item)
        used += len(piece)
        index += 1
        offset = 0
    result = {**_docref(ref, inp), "blocks": out, "total": len(blocks)}
    if next_cursor:
        result["next"] = next_cursor
    return result


def _read_text(r: dict) -> str:
    head = f"{r['path']}  rev {r['rev']}" + (
        f"  [draft revision {r['revision']}]" if r["source"] == "draft" else "")
    lines = [head]
    for b in r["blocks"]:
        part = ""
        if b.get("part"):
            part = f"  (chars {b['part']['from']}-{b['part']['to']} of {b['part']['of']})"
        style = f"  [{b['style']}]" if b.get("style") else ""
        lines.append(f"[{b['at']}] {b.get('kind', '')}{style}{part}")
        lines.append(b.get("text", ""))
    if r.get("next"):
        lines.append(f"more: read with cursor={r['next']}")
    return "\n".join(lines)


register(Tool(
    name="read", title="본문 읽기",
    description="Read text at an address (or the whole document) as blocks with "
                "addresses; tables come back as markdown grids. Long results "
                "page: pass `next` back as `cursor`.",
    group="read",
    input_schema=_obj({
        "path": S_PATH, "at": S_AT,
        "cursor": {"type": "string", "maxLength": 100},
        "max_chars": {"type": "integer", "minimum": 500, "maximum": READ_MAX_CHARS},
        "with_runs": {"type": "boolean"},
    }, ["path"]),
    output_schema=_out({**O_DOCREF, "blocks": {"type": "array"},
                        "next": {"type": "string"}, "total": {"type": "integer"}}),
    run=_run_read, text=_read_text, budget_chars=READ_MAX_CHARS + 2000,
))


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

def _run_find(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    inp = current(ctx, ref)
    if args.get("regex"):
        try:
            re.compile(args["query"])
        except re.error as exc:
            raise ToolError("invalid_params", f"검색에 쓴 정규식의 문법이 맞지 않습니다({exc}).",
                            hint="오류 설명을 보고 정규식을 고치세요.") from None
    data = doc_call(ctx.doc.find, str(inp.path), args["query"],
                    regex=bool(args.get("regex", False)), scope=args.get("scope"))
    hits = data.get("hits", [])
    limit = args.get("limit", FIND_DEFAULT_LIMIT)
    shown = [dict(h) for h in hits[:limit]]
    _add_context(ctx, inp.path, shown)
    return {**_docref(ref, inp), "query": args["query"], "total": len(hits),
            "hits": shown, "truncated": len(hits) > limit}


FIND_CONTEXT_CHARS = 30
FIND_CONTEXT_LOOKUPS = 20


def _add_context(ctx: Context, path: Path, hits: list[dict]) -> None:
    """Give each hit the words around it, so nobody has to read to know which.

    One whole-document read covers top-level paragraphs; addresses inside
    tables are read one by one, up to FIND_CONTEXT_LOOKUPS of them.
    """
    if not hits:
        return
    texts: dict[str, str] = {}
    try:
        for block in doc_call(ctx.doc.read, str(path)).get("blocks", []):
            if block.get("kind") != "table":
                texts[str(block.get("at"))] = str(block.get("text") or "")
    except ToolError:
        return
    lookups = 0
    for hit in hits:
        at = str(hit.get("at"))
        if at not in texts and lookups < FIND_CONTEXT_LOOKUPS:
            lookups += 1
            try:
                blocks = doc_call(ctx.doc.read, str(path), at).get("blocks", [])
                texts[at] = str(blocks[0].get("text") or "") if blocks else ""
            except ToolError:
                texts[at] = ""
        text = texts.get(at) or ""
        start, end = hit.get("start"), hit.get("end")
        if not text or not isinstance(start, int) or not isinstance(end, int):
            continue
        lo, hi = max(0, start - FIND_CONTEXT_CHARS), min(len(text), end + FIND_CONTEXT_CHARS)
        tail = "…" if hi < len(text) else ""
        hit["context"] = ("…" if lo else "") + one_line(text[lo:hi]) + tail


def _find_text(r: dict) -> str:
    lines = [f"{r['total']} hits for {r['query']!r} in {r['path']} rev {r['rev']}"]
    for h in r["hits"]:
        page = f" p.{h['page']}" if h.get("page") else ""
        lines.append(f"  {h['at']}{page}  "
                     f"{one_line(str(h.get('context') or h.get('text', '')))[:120]}")
    if r.get("truncated"):
        lines.append(f"  … {r['total'] - len(r['hits'])} more (raise limit or narrow scope)")
    return "\n".join(lines)


register(Tool(
    name="find", title="찾기",
    description="Find text (or a regex) and get the address of every hit. Use "
                "it before `edit` so you change the right place.",
    group="read",
    input_schema=_obj({
        "path": S_PATH,
        "query": {"type": "string", "minLength": 1, "maxLength": 500},
        "regex": {"type": "boolean"},
        "scope": S_AT,
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
    }, ["path", "query"]),
    output_schema=_out({**O_DOCREF, "hits": {"type": "array"},
                        "total": {"type": "integer"}, "truncated": {"type": "boolean"}}),
    run=_run_find, text=_find_text,
))


# ---------------------------------------------------------------------------
# edit / fill (both stage into the draft)
# ---------------------------------------------------------------------------

#: op -> required keys (beyond "op"), optional keys. From doc-core-api.md.
OP_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "set": (("at", "text"), ("expect",)),
    "replace": (("find", "with"), ("at", "all", "expect")),
    "insert_after": (("at", "markdown"), ("like",)),
    "delete": (("at",), ("expect",)),
    "table.set_cells": (("at", "grid"), ()),
    "table.add_row": (("at", "after"), ("like",)),
    "table.delete_row": (("at",), ()),
    "fill": (("place", "text"), ()),
    "style": (("at", "style"), ()),
}


#: One correct op of each kind, shown when an op is missing or misnames a field.
OP_EXAMPLES = {
    "set": '{"op":"set","at":"p1","text":"새 문장"}',
    "replace": '{"op":"replace","at":"p1","find":"옛말","with":"새말"}',
    "insert_after": '{"op":"insert_after","at":"p1","markdown":"덧붙일 문단"}',
    "delete": '{"op":"delete","at":"p1"}',
    "table.set_cells": '{"op":"table.set_cells","at":"t0/r1/c0","grid":[["값"]]}',
    "table.add_row": '{"op":"table.add_row","at":"t0","after":2}',
    "table.delete_row": '{"op":"table.delete_row","at":"t0/r2"}',
    "fill": '{"op":"fill","place":"성명","text":"홍길동"}',
    "style": '{"op":"style","at":"p1","style":"개요 1"}',
}
#: Field names people and agents reach for first, and the one each op uses.
OP_ALIASES = {"old": "find", "from": "find", "search": "find", "new": "with",
              "to": "with", "replace": "with", "replacement": "with", "value": "text",
              "content": "text", "address": "at", "where": "at", "md": "markdown"}


def _check_ops(ops: list) -> None:
    for index, op in enumerate(ops):
        where = f"ops[{index}]"
        if not isinstance(op, dict):
            raise ToolError("invalid_params", f"{where}: 작업의 입력 형식이 맞지 않습니다.",
                            hint="작업 이름과 필요한 값을 중괄호로 묶어 입력하세요.", at=where)
        kind = op.get("op")
        if kind not in OP_FIELDS:
            raise ToolError("invalid_params", f"{where}.op: 지원하지 않는 작업입니다({kind!r}).",
                            hint="목록에서 사용할 작업 이름을 고르세요.",
                            at=where, candidates=sorted(OP_FIELDS))
        required, optional = OP_FIELDS[kind]
        allowed = {"op", *required, *optional}
        extra = sorted(set(op) - allowed)
        for key in extra:
            alias = OP_ALIASES.get(key)
            if alias in allowed and alias not in op:
                raise ToolError("invalid_params",
                                f"{where}: {kind} 작업에는 '{key}' 대신 '{alias}'를 씁니다.",
                                hint="예: " + OP_EXAMPLES[kind], at=f"{where}.{key}")
        for key in required:
            if key not in op:
                raise ToolError("invalid_params",
                                f"{where}: {kind} 작업에 '{key}' 항목이 없습니다.",
                                hint="예: " + OP_EXAMPLES[kind], at=f"{where}.{key}")
        if extra:
            raise ToolError("invalid_params",
                            f"{where}: {kind} 작업에 쓸 수 없는 항목입니다('{extra[0]}').",
                            hint="예: " + OP_EXAMPLES[kind],
                            at=where, candidates=sorted(allowed - {"op"}))


def _stage(ctx: Context, ref: Ref, base: str | None, ops: list, kind: str) -> dict:
    def apply(in_path: Path, in_rev: str, out_path: Path) -> dict:
        return doc_call(ctx.doc.edit, str(in_path), ops, base=in_rev,
                        out=str(out_path))
    staged = ctx.drafts.stage(ref, base=base, ops=ops, author=ctx.client,
                              provenance=_provenance(ctx), apply=apply, kind=kind)
    cs = staged["changeset"]
    result = {
        "path": ref.label, "source": "draft",
        "revision": cs["revision"], "rev": cs["rev"], "revBefore": cs["base"]["rev"],
        "changeset": cs["id"], "applied": cs["applied"], "remap": cs["remap"],
        "changedPages": cs["changedPages"], "signals": cs["signals"],
        "saved": False,
    }
    engine = staged.get("engine") or {}
    if engine.get("changed"):
        result["changed"] = engine["changed"]
    return result


def _edit_text(r: dict) -> str:
    lines = [f"staged in draft: {r['path']} revision {r['revision']} rev {r['rev']} "
             f"(was {r.get('revBefore')}); not saved"]
    if r.get("applied"):
        lines.append("applied: " + ", ".join(
            f"#{a.get('i')} {a.get('op')} {a.get('at', '')}" for a in r["applied"][:20]))
    if r.get("remap"):
        lines.append("address shifts: " + ", ".join(
            f"{m['from']}→{m['to']}" for m in r["remap"][:20]))
    if r.get("changedPages"):
        lines.append("changed pages: " + ", ".join(map(str, r["changedPages"]))
                     + " → look with preview(pages=\"changed\")")
    if r.get("signals"):
        lines.append("layout signals: " + ", ".join(
            f"p.{s.get('page')} {s.get('kind')}" for s in r["signals"][:12]))
    if r.get("skipped"):
        lines.append("not filled, the person's to fill: " + ", ".join(r["skipped"]))
    if r.get("personOnly"):
        lines.append("left for the person: " + ", ".join(r["personOnly"]))
    if r.get("unfilled"):
        lines.append("still empty: " + ", ".join(r["unfilled"][:20]))
    lines.append("when done: check, then save")
    return "\n".join(lines)


def _run_edit(ctx: Context, args: dict) -> dict:
    ops = args["ops"]
    _check_ops(ops)
    ref = resolve(ctx, args["path"])
    _refuse_person_seats(ctx, ref, ops)
    for op in ops:
        if op["op"] == "insert_after":
            op["markdown"] = _gate_markdown_assets(
                ctx, str(op.get("markdown", "")), ref.source.parent if ref.source else None)
    return _stage(ctx, ref, args["base"], ops, "edit")


def _refuse_person_seats(ctx: Context, ref: Ref, ops: list) -> None:
    """edit cannot do what fill may not: write a signature, seal or approval-date seat."""
    named = set()
    for op in ops:
        if op["op"] == "fill":
            named.add(_place_id(str(op["place"])))
        elif str(op.get("at", "")).startswith("place:"):
            named.add(_place_id(str(op["at"])))
    if not named:
        return
    outline = doc_call(ctx.doc.outline, str(ctx.drafts.input_for(ref).path))
    blocked = sorted(f"place:{p['id']}" for p in outline.get("places", [])
                     if p.get("id") in named and is_person_only(p))
    if blocked:
        raise ToolError("person_only_seat",
                        "직접 작성해야 하는 서명·날인·결재일 칸: " + ", ".join(blocked),
                        hint="이 칸은 비워 두고 작성자에게 알리세요.", candidates=blocked)


register(Tool(
    name="edit", title="고치기",
    description="Change the document with declarative ops, staged into its draft "
                "(the person's file is not touched until `save`). Ops: set{at,text,"
                "expect?}, replace{find,with,at?,all?,expect?}, insert_after{at,"
                "markdown,like?}, delete{at,expect?}, table.set_cells{at,grid}, "
                "table.add_row{at,after,like?}, table.delete_row{at}, style{at,style}. "
                "Pass the `rev` you read as `base`; use `expect` to guard the text "
                "you are replacing. Returns changed pages: preview them.",
    group="write", read_only=False, idempotent=False,
    input_schema=_obj({
        "path": S_PATH, "base": S_REV,
        "ops": {"type": "array", "minItems": 1, "maxItems": EDIT_MAX_OPS,
                "items": {"type": "object"}},
    }, ["path", "base", "ops"]),
    output_schema=_out({**O_DOCREF, "changeset": {"type": "string"},
                        "changedPages": {"type": "array"}, "remap": {"type": "array"},
                        "signals": {"type": "array"}}),
    run=_run_edit, text=_edit_text,
))


def _place_id(key: str) -> str:
    return key[len("place:"):] if key.startswith("place:") else key


def _run_fill(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    # The places of what fill writes into: the draft head when there is one.
    # Reading the file instead listed seats an earlier fill already filled.
    inp = ctx.drafts.input_for(ref)
    outline = doc_call(ctx.doc.outline, str(inp.path))
    places = {p["id"]: p for p in outline.get("places", [])}
    values: dict = args["values"]
    blocked = []
    ops = []
    for key, text in values.items():
        pid = _place_id(key)
        place = places.get(pid)
        if place is None:
            _refuse_filled_place(ctx, ref, inp, pid)
            near = [f"place:{p}" for p in places if pid in p or p in pid][:5] or \
                [f"place:{p}" for p in list(places)[:5]]
            raise ToolError("bad_address", f"'{pid}' 칸을 찾지 못했습니다.",
                            hint="open 결과에서 채울 칸의 주소를 확인하세요.",
                            at=f"place:{pid}", candidates=near)
        if is_person_only(place):
            blocked.append(f"place:{pid}")
            continue
        if not isinstance(text, str):
            raise ToolError("invalid_params", f"place:{pid} 칸에는 값을 글자로 입력해야 합니다.",
                            hint="칸에 넣을 값을 큰따옴표로 감싸서 입력하세요.",
                            at=f"place:{pid}")
        ops.append({"op": "fill", "place": pid, "text": text})
    if blocked and not ops:
        raise ToolError("person_only_seat",
                        "직접 작성해야 하는 서명·날인·결재일 칸: " + ", ".join(blocked),
                        hint="이 칸은 비워 두고 작성자에게 알리세요.", candidates=blocked)
    if not ops:
        raise ToolError("invalid_params", "채울 값이 없습니다.", hint="채울 칸과 값을 한 쌍 이상 입력하세요.")
    result = _stage(ctx, ref, args.get("base") or inp.rev, ops, "fill")
    # Seats this draft already filled, whether or not the document layer
    # still lists a filled cell as a place.
    filled = {op["place"] for cs in (ctx.drafts.load(ref) or {}).get("changesets", [])
              for op in cs.get("ops") or [] if isinstance(op, dict) and op.get("op") == "fill"}
    filled |= {op["place"] for op in ops}
    result["filled"] = [{"place": f"place:{op['place']}", "text": op["text"]} for op in ops]
    result["personOnly"] = [f"place:{p['id']}" for p in places.values()
                            if is_person_only(p)]
    result["skipped"] = blocked
    result["unfilled"] = [f"place:{pid}" for pid, p in places.items()
                          if pid not in filled and not is_person_only(p) and not p.get("filled")
                          and not str(p.get("value") or "").strip()]
    return result


def _refuse_filled_place(ctx: Context, ref: Ref, inp, pid: str) -> None:
    """A seat the draft already filled is no longer a place; say where it went."""
    if inp.source != "draft" or ref.source is None:
        return
    try:
        original = doc_call(ctx.doc.outline, str(ref.source))
    except ToolError:
        return
    for p in original.get("places", []):
        if p.get("id") == pid:
            at = p.get("at") or f"place:{pid}"
            raise ToolError("not_found", f"place:{pid} 칸은 초안에서 이미 채웠습니다({at}).",
                            hint=f"값을 바꾸려면 edit로 해당 셀의 값을 바꾸세요: "
                                 f'{{"op":"set","at":"{at}","text":"새 값"}}',
                            at=at)


register(Tool(
    name="fill", title="양식 채우기",
    description="Fill form places by id (from `open` → places): {\"values\": "
                "{\"place:성명\": \"홍길동\"}}. Staged into the draft. Signature, "
                "seal and approval-date seats are skipped and listed in `skipped`; "
                "tell the person to fill them.",
    group="write", read_only=False, idempotent=False,
    input_schema=_obj({
        "path": S_PATH, "base": S_REV,
        "values": {"type": "object", "description": "place id → text"},
    }, ["path", "values"]),
    output_schema=_out({**O_DOCREF, "changeset": {"type": "string"},
                        "personOnly": {"type": "array"}, "unfilled": {"type": "array"},
                        "skipped": {"type": "array"}, "filled": {"type": "array"}}),
    run=_run_fill, text=_edit_text,
))


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------

def _run_new(ctx: Context, args: dict) -> dict:
    markdown = args["markdown"]
    form_path = None
    if args.get("form"):
        form_ref = resolve(ctx, args["form"])
        form_path = current(ctx, form_ref).path
    base_dir = None
    if args.get("base_dir"):
        try:
            base_dir = (ctx.roots.check(args["base_dir"]) if ctx.roots is not None
                        else canonical(args["base_dir"]))
        except PathRefused as exc:
            raise ToolError(exc.code, exc.message, hint=getattr(exc, "hint", None),
                            at=exc.path) from exc
    markdown = _gate_markdown_assets(ctx, markdown, base_dir)
    if "\n" not in markdown:
        # The document layer reads a one-line argument naming a file as that
        # file. A body is never a file name.
        markdown += "\n"

    def build(out_path: Path) -> dict:
        return doc_call(ctx.doc.new, markdown, str(out_path),
                        form=str(form_path) if form_path else None)
    ref, staged = ctx.drafts.create_virtual(
        name=args.get("name"), author=ctx.client, provenance=_provenance(ctx),
        build=build, suffix=getattr(ctx.doc, "NATIVE_SUFFIX", ".hwpx"))
    cs = staged["changeset"]
    return {"path": ref.label, "source": "draft", "revision": 1, "rev": cs["rev"],
            "changeset": cs["id"], "saved": False,
            "signals": cs["signals"], "changedPages": cs["changedPages"]}


register(Tool(
    name="new", title="새 문서",
    description="Write a new document from markdown (optionally on a form). "
                "Returns draft:<id>, usable as `path` in every tool; `save` it to "
                "a file when done.",
    group="write", read_only=False, idempotent=False,
    input_schema=_obj({
        "markdown": {"type": "string", "minLength": 1, "maxLength": 500000},
        "form": S_PATH,
        "name": {"type": "string", "maxLength": 200},
        "base_dir": {"type": "string", "maxLength": 4096},
    }, ["markdown"]),
    output_schema=_out({**O_DOCREF, "changeset": {"type": "string"}}),
    run=_run_new, text=_edit_text,
))


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

def _preview_dir(ctx: Context, ref: Ref, rev: str) -> Path:
    mark_state(ctx.drafts.home)
    return private_dir(ctx.drafts.home / "previews" / ref.key / rev)


def _run_preview(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    inp = current(ctx, ref)
    pages = args.get("pages", "changed" if inp.source == "draft" else [1])
    if pages == "changed":
        record = ctx.drafts.load(ref) or {}
        last = (record.get("changesets") or [{}])[-1]
        pages = list(last.get("changedPages") or [])
        if not pages:
            pages = [1]
    if not isinstance(pages, list) or not all(isinstance(p, int) and p >= 1 for p in pages):
        raise ToolError("invalid_params", "미리 볼 쪽을 잘못 지정했습니다.",
                        hint="1 이상인 쪽 번호를 [1, 2]처럼 입력하거나 바뀐 쪽을 보려면 \"changed\"를 입력하세요.")
    asked = sorted(set(pages))
    shown = asked[:PREVIEW_MAX_PAGES]
    data = doc_call(ctx.doc.render, str(inp.path), shown,
                    scale=float(args.get("scale", 1.5)), fmt="png",
                    out_dir=str(_preview_dir(ctx, ref, inp.rev)))
    images = [{"page": p.get("n"), "file": p.get("file"), "mime": "image/png",
               "width": p.get("px_w"), "height": p.get("px_h")}
              for p in data.get("pages", [])]
    signals: list = []
    pages_info = doc_call(ctx.doc.pages, str(inp.path)) if hasattr(ctx.doc, "pages") else {}
    for page in pages_info.get("pages", []):
        if page.get("n") in shown:
            for s in page.get("signals", []) or []:
                signals.append({"page": page["n"], "kind": s if isinstance(s, str)
                                else s.get("kind")})
    info = doc_call(ctx.doc.open, str(inp.path))
    result = {**_docref(ref, inp), "images": images, "signals": signals,
              "pageCount": pages_info.get("count") or info.get("pages"),
              "fonts": info.get("fonts", {})}
    if len(asked) > len(shown):
        result["morePages"] = asked[len(shown):]
    return result


def _preview_text(r: dict) -> str:
    pages = ", ".join(str(i["page"]) for i in r["images"])
    lines = [f"{r['path']} rev {r['rev']}: page image(s) {pages} of {r.get('pageCount')}"]
    if r.get("signals"):
        lines.append("layout signals: " + ", ".join(
            f"p.{s['page']} {s['kind']}" for s in r["signals"]))
    else:
        lines.append("layout signals: none on these pages")
    fl = _fonts_line(r.get("fonts") or {})
    if fl:
        lines.append(fl)
    if r.get("morePages"):
        lines.append("not shown (max 3 per call): " + ", ".join(map(str, r["morePages"])))
    return "\n".join(lines)


register(Tool(
    name="preview", title="쪽 미리보기",
    description="See pages as images (max 3 per call) with layout signals "
                "(heading alone at page bottom, table split, font substitution). "
                "pages=\"changed\" shows what the last edit touched. Look before "
                "you say a document is done.",
    group="read",
    input_schema=_obj({
        "path": S_PATH,
        "pages": {"type": ["array", "string"], "items": {"type": "integer", "minimum": 1}},
        "scale": {"type": "number", "minimum": 0.5, "maximum": 3.0},
    }, ["path"]),
    output_schema=_out({**O_DOCREF, "images": {"type": "array"},
                        "signals": {"type": "array"}}),
    run=_run_preview, text=_preview_text,
))


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def _units(ctx: Context, path: Path) -> list[tuple[str, str]]:
    """(address, text) for every block, in document order, from rt_doc.read."""
    data = doc_call(ctx.doc.read, str(path))
    units = []
    for block in data.get("blocks", []):
        grid = block.get("cells", block.get("grid"))
        if block.get("kind") == "table" and isinstance(grid, list):
            text = "\n".join("\t".join(str(c) for c in row) for row in grid)
        else:
            text = str(block.get("text") or "")
        units.append((str(block.get("at")), text))
    return units


def _style_findings(ctx: Context, path: Path, pack: str | None) -> list[dict]:
    """Korean style findings with document addresses.

    rt_doc.style when the document layer has one; otherwise the rule set in
    rt_style, run over rt_doc's own blocks so every finding has an ``at``.
    """
    own = getattr(ctx.doc, "style", None)
    if callable(own):
        return doc_call(own, str(path), **({"pack": pack} if pack else {})).get("findings", [])
    rt_style = sibling("rt_style")
    try:
        rules = rt_style.rules_for("any")
        if pack:
            loaded = rt_style.load_pack(pack)
            rules = rt_style.rules_for(loaded.base_doc_type) + list(loaded.rules)
    except rt_style.StyleInputError as exc:
        raise ToolError("capability_unavailable", f"문체 규칙을 불러오지 못했습니다: {exc}") from exc
    units = _units(ctx, path)
    out = []
    for f in rt_style.check_text([text for _, text in units], rules):
        at = units[f["line"] - 1][0]
        out.append({"rule": f["rule"], "severity": f["severity"], "at": at,
                    "start": f["col"] - 1, "end": f["col"] - 1 + len(f["match"]),
                    "match": f["match"], "message": f["why"], "suggest": f["suggest"]})
    return out


def _guard(ctx: Context, before: Path, after: Path) -> dict:
    """Did the edit change a protected fact (number, date, quote, negation...)?

    Blocks are aligned by text (difflib), so inserting a paragraph does not
    shift every later comparison. A changed block is audited by rt_fidelity;
    a removed block fails only if it carried a protected fact; an added block
    is reported for the person to read but does not fail the check.
    """
    own = getattr(ctx.doc, "guard", None)
    if callable(own):
        return doc_call(own, str(before), str(after))
    import difflib

    fidelity = sibling("rt_fidelity")
    a, b = _units(ctx, before), _units(ctx, after)
    matcher = difflib.SequenceMatcher(a=[t for _, t in a], b=[t for _, t in b],
                                      autojunk=False)
    changes: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for k in range(pairs):
            (_, x), (at, y) = a[i1 + k], b[j1 + k]
            audit = fidelity.audit_text(x, y)
            if not audit["pass"]:
                changes.append({"at": at, "kind": "changed",
                                "kinds": [c["kind"] for c in audit["changes"]],
                                "before": x, "after": y})
        for k in range(i1 + pairs, i2):
            at, x = a[k]
            audit = fidelity.audit_text(x, "")
            if not audit["pass"]:
                changes.append({"at": at, "kind": "removed",
                                "kinds": [c["kind"] for c in audit["changes"]],
                                "before": x, "after": None})
        for k in range(j1 + pairs, j2):
            at, y = b[k]
            if not fidelity.audit_text("", y)["pass"]:
                changes.append({"at": at, "kind": "added", "notice": True,
                                "before": None, "after": y})
    return {"pass": not any(not c.get("notice") for c in changes), "changes": changes}


def _tri(fn) -> tuple[str, Any]:
    """passed | failed | unavailable — unavailable is never shown as a pass."""
    try:
        return "ran", fn()
    except ToolError as exc:
        if exc.code in ("capability_unavailable", "unsupported_format"):
            why = (exc.data or {}).get("reason")
            return "unavailable", {"reason": exc.message, **({"why": why} if why else {})}
        raise


def _run_check(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    inp = current(ctx, ref)
    only = set(args.get("only") or ["style", "layout", "fonts", "guard"])
    checks: dict[str, dict] = {}
    findings: list[dict] = []

    if "style" in only:
        state, data = _tri(lambda: _style_findings(ctx, inp.path, args.get("pack")))
        if state == "unavailable":
            checks["style"] = {"state": "unavailable", **data}
        else:
            items = data
            errors = [f for f in items if f.get("severity") == "error"]
            checks["style"] = {"state": "failed" if errors else "passed",
                               "count": len(items)}
            for f in items:
                findings.append({"check": "style", **f})

    if "layout" in only:
        state, data = _tri(lambda: doc_call(ctx.doc.pages, str(inp.path)))
        if state != "unavailable" and not data.get("pages"):
            # No page list is no evidence, not a clean layout.
            state, data = "unavailable", {"reason": "no_pages",
                                          "why": "the document layer returned no pages"}
        if state == "unavailable":
            checks["layout"] = {"state": "unavailable", **data}
        else:
            sig = [(p.get("n"), s) for p in data.get("pages", [])
                   for s in (p.get("signals") or [])]
            layout_bad = [x for x in sig if (x[1] if isinstance(x[1], str)
                                            else x[1].get("kind")) != "approx"]
            checks["layout"] = {"state": "failed" if layout_bad else "passed",
                                "count": len(layout_bad)}
            for page, s in layout_bad:
                kind = s if isinstance(s, str) else s.get("kind")
                findings.append({"check": "layout", "rule": f"layout.{kind}",
                                 "severity": "warning", "page": page,
                                 "message": _LAYOUT_MSG.get(kind, kind)})

    if "fonts" in only:
        state, data = _tri(lambda: doc_call(ctx.doc.open, str(inp.path)))
        if state == "unavailable":
            checks["fonts"] = {"state": "unavailable", **data}
        else:
            subs = (data.get("fonts") or {}).get("substituted") or []
            checks["fonts"] = {"state": "failed" if subs else "passed",
                               "count": len(subs)}
            for s in subs:
                findings.append({"check": "fonts", "rule": "fonts.substituted",
                                 "severity": "notice",
                                 "message": f"{s.get('want')} 글꼴이 없어 {s.get('got')}로 그렸습니다. "
                                            "쪽 나눔이 한글과 다를 수 있습니다."})

    against = args.get("against")
    if "guard" in only and (against or (inp.source == "draft" and ref.source)):
        if against:
            # The document named, at the revision it names: a draft's head
            # for draft:<id>, the file on disk otherwise. Never a fallback.
            other = resolve(ctx, against)
            base_path = (ctx.drafts.input_for(other, use_draft=True).path
                         if is_virtual(against) else other.source)
        else:
            base_path = ref.source
        state, data = _tri(lambda: _guard(ctx, base_path, inp.path))
        if state == "unavailable":
            checks["guard"] = {"state": "unavailable", **data}
        else:
            changes = data.get("changes", [])
            checks["guard"] = {"state": "passed" if data.get("pass") else "failed",
                               "count": len(changes), "against": str(base_path)}
            for c in changes:
                notice = c.get("notice")
                findings.append({"check": "guard", "rule": "guard.fact_" + (
                    "added" if notice else "changed"),
                    "severity": "notice" if notice else "warning",
                    "message": _guard_message(c),
                    **{k: v for k, v in c.items() if k != "notice"}})

    total = len(findings)
    states = [c["state"] for c in checks.values()]
    # None when nothing could run: "no check failed" is not "it passed".
    verdict = (all(s != "failed" for s in states)
               if any(s != "unavailable" for s in states) else None)
    result = {**_docref(ref, inp), "checks": checks,
              "findings": findings[:CHECK_MAX_FINDINGS], "total": total,
              "pass": verdict}
    if total > CHECK_MAX_FINDINGS:
        result["truncated"] = total - CHECK_MAX_FINDINGS
    return result


#: rt_fidelity's protected kinds, in the words a person reads.
_FACT_KO = {
    "numbers": "숫자", "dates": "날짜", "source_ids": "출처 번호", "citations": "인용 출처",
    "tags": "문서 표시", "inline_math": "수식", "direct_quotes": "인용문", "urls": "주소",
    "markdown_links": "링크", "headings": "제목", "qualifiers": "부정·한정 표현",
    "quantifiers": "수량 표현", "causal_markers": "인과 표현", "direction_words": "방향 표현",
    "protected_spans": "보호 구간",
}


def _clip(text, size: int = 40) -> str:
    text = one_line(str(text or ""))
    return text if len(text) <= size else text[:size - 1] + "…"


def _subject(word: str) -> str:
    """``word`` with 이/가 chosen by its last syllable."""
    last = word[-1:] or "가"
    if "가" <= last <= "힣":
        return word + ("이" if (ord(last) - 0xAC00) % 28 else "가")
    return word + "이(가)"


def _guard_message(change: dict) -> str:
    kinds = [_FACT_KO.get(k, k) for k in change.get("kinds") or []]
    what = "·".join(dict.fromkeys(kinds)) or "내용"
    if change.get("kind") == "removed":
        return f"{_subject(what)} 든 문단이 빠졌습니다: {_clip(change.get('before'))}"
    if change.get("kind") == "added":
        return f"새로 쓴 문단에 사실 표현이 있습니다. 근거를 확인하세요: {_clip(change.get('after'))}"
    if change.get("before") is not None and change.get("after") is not None:
        return (f"{_subject(what)} 바뀌었습니다: {_clip(change['before'])} → "
                f"{_clip(change['after'])}")
    return f"{_subject(what)} 바뀌었습니다."


_LAYOUT_MSG = {
    "lone_heading": "제목이 쪽 끝에 홀로 남았습니다. 다음 쪽으로 넘기거나 앞 내용을 줄이세요.",
    "bottom_heading": "쪽 끝에서 제목 뒤에 본문이 몇 줄 남지 않았습니다.",
    "table_split": "표가 두 쪽에 걸쳐 나뉘었습니다. 머리행 반복이나 쪽 나눔을 확인하세요.",
}


def _check_text(r: dict) -> str:
    states = "  ".join(f"{k} {v['state']}" for k, v in r["checks"].items())
    lines = [f"{r['path']} rev {r['rev']}: {states}"]
    for f in r["findings"]:
        where = f.get("at") or (f"p.{f['page']}" if f.get("page") else "")
        fix = ""
        if f.get("wrong") and f.get("right"):
            fix = f"  ({f['wrong']} → {f['right']})"
        src = f"  [{f['source']}]" if f.get("source") else ""
        lines.append(f"  {f.get('severity', '')} {f.get('rule', '')} {where}: "
                     f"{one_line(str(f.get('message', '')))[:160]}{fix}{src}")
    if r.get("truncated"):
        lines.append(f"  … {r['truncated']} more")
    if r.get("pass") is None:
        lines.append("no check could run on this file here")
    return "\n".join(lines)


register(Tool(
    name="check", title="점검",
    description="Check style (Korean document conventions, with rule ids and "
                "fixes), layout (lone headings, split tables), fonts, and — for a "
                "draft or with `against` — whether numbers, dates and names "
                "changed. Each check is passed, failed or unavailable.",
    group="check",
    input_schema=_obj({
        "path": S_PATH,
        "against": S_PATH,
        "pack": {"type": "string", "enum": ["gongmun", "minwon", "hr", "grant"]},
        "only": {"type": "array", "items": {"type": "string",
                                            "enum": ["style", "layout", "fonts", "guard"]}},
    }, ["path"]),
    output_schema=_out({**O_DOCREF, "checks": {"type": "object"},
                        "findings": {"type": "array"},
                        "pass": {"type": ["boolean", "null"]}}),
    run=_run_check, text=_check_text,
))


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def _target(ctx: Context, raw: str) -> Path:
    try:
        path = ctx.roots.check(raw) if ctx.roots is not None else canonical(raw)
    except PathRefused as exc:
        raise ToolError(exc.code, exc.message, hint=exc.hint, at=exc.path) from exc
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in FORMATS_OUT:
        raise ToolError("unsupported_format",
                        f"'{path.suffix or '(확장자 없음)'}' 형식으로는 저장할 수 없습니다.",
                        hint="저장할 파일의 확장자는 "
                        + ", ".join("." + f for f in FORMATS_OUT) + " 중 하나로 지정하세요.")
    return path


def _arg(text: str) -> str:
    """A path in a command line for a person: quoted for the shell when it can
    be, else shown escaped (such a name has to be typed some other way)."""
    return shell_arg(text) or f'"{path_text(text)}"'


def _person_line(ref: Ref, target: Path) -> str:
    if ref.source is not None and _same_path(target, ref.source):
        return f"rigorloom save {_arg(ref.label)}"
    return f"rigorloom save {_arg(ref.label)} --to {_arg(str(target))}"


def _draft_id(ref: Ref, record: dict | None) -> str:
    """The draft as save history names it: its key plus the instance, so a
    new draft on the same path is not the one that created a file. A save
    with no draft record (a plain conversion) or a record without an instance
    gets a name used once, so it never makes a file "ours" for a later save."""
    instance = (record or {}).get("instance")
    if instance:
        return f"{ref.key}#{instance}"
    import secrets
    return f"{ref.key}#once-{secrets.token_hex(6)}"


def _run_save(ctx: Context, args: dict) -> dict:
    ref = resolve(ctx, args["path"])
    record = ctx.drafts.load(ref)
    writer = _draft_id(ref, record)
    head_input = ctx.drafts.input_for(ref, use_draft=True)
    if args.get("to"):
        target = _target(ctx, args["to"])
    elif ref.source is not None:
        target = ref.source
    else:
        raise ToolError("invalid_params", "새 문서를 저장할 경로가 빠졌습니다.",
                        hint="보고서.hwpx처럼 파일 이름을 포함한 저장 경로를 입력하세요.")
    fmt = target.suffix.lower().lstrip(".")
    has_edits = head_input.source == "draft"
    if not has_edits and fmt == (ref.source.suffix.lower().lstrip(".") if ref.source else ""):
        raise ToolError("no_draft", "저장할 변경 사항이 없습니다.",
                        hint="먼저 edit나 fill로 문서를 고치세요.")

    # Candidate bytes: the head, converted when the target format differs.
    candidate = head_input.path
    lossy: list[str] = []
    if candidate.suffix.lower().lstrip(".") != fmt:
        candidate, lossy = _converted(ctx, ref, head_input, fmt)

    digest = sha256_file(candidate)
    if target.exists() and sha256_file(target) == digest:
        raise ToolError("no_draft", "저장하려는 내용과 파일 내용이 같습니다.",
                        at=str(target))
    # A change set the person made at the terminal is reviewed by definition.
    unreviewed = sum(1 for c in (record or {}).get("changesets", [])
                     if c.get("status") == "proposed" and c.get("author") != "cli")
    # A "no" is final for these bytes at this target when an agent would ask
    # again. A person at the terminal who runs save again is asking themself,
    # but only by answering the question again: --force does not undo a "no".
    said_no = rt_commit.declined(target, digest, ctx.drafts.home)
    if said_no:
        if ctx.client != "cli":
            raise ToolError("declined_by_person",
                            "사용자가 이 내용으로 파일을 덮어쓰지 않기로 했습니다.",
                            hint="덮어쓸지 다시 묻지 마세요. 저장하려면 먼저 사용자에게 새 파일 이름을 물어보세요.",
                            at=str(target))
        if ctx.force:
            hint = ("다른 이름으로 저장하세요: -o 새이름" if ctx.draft_scope else
                    f"터미널에서 --force 없이 저장하면 덮어쓸지 직접 선택할 수 있습니다: {_person_line(ref, target)}")
            raise ToolError("declined_by_person",
                            "사용자가 이 내용으로 덮어쓰기를 거절한 기록이 있어 --force로 저장하지 않았습니다.",
                            hint=hint, at=str(target))

    if not target.exists():
        expected, policy = rt_commit.ABSENT, "policy:new-file"
    elif ctx.create_only:
        # `-o OUT` without --force: the CLI checked OUT was absent; a file
        # that appeared since is not ours to replace.
        raise ToolError("target_exists", f"같은 이름이 이미 있어 저장하지 않았습니다({target}).",
                        hint="덮어쓰려면 --force를 붙이세요. 이전 내용은 저장 기록에 남습니다.",
                        at=str(target))
    elif not said_no and (
            ours := rt_commit.owned_sha256(target, ctx.drafts.home, draft=writer)) is not None:
        # A "no" on record for these bytes means the person is asked, even
        # over a file this draft created (Sol re-check F1, round 2).
        # The digest the ownership check matched, not a fresh hash: a foreign
        # write after the check fails the commit as target_changed.
        expected, policy = ours, "policy:own-file"
    elif ctx.force and ctx.client == "cli":
        # The person named this target and typed --force; history says so.
        expected, policy = sha256_file(target), "person:force"
    else:
        expected = sha256_file(target)
        question = f'"{path_text(str(target))}" 파일을 덮어쓸까요?'
        detail = {"target": str(target), "revision": head_input.revision,
                  "changedPages": sorted({p for c in (record or {}).get("changesets", [])
                                          for p in c.get("changedPages", [])}),
                  "unreviewed": unreviewed, "lossy": lossy,
                  "fontsSubstituted": _substituted_fonts(ctx, head_input.path),
                  "undo": _undo_command(target)}
        other = ("다른 이름으로 저장: --to 새이름" if ctx.client == "cli"
                 else "다른 이름으로 저장하려면 to에 새 경로를 입력하세요.")
        if ctx.ask is None:
            raise ToolError("needs_person",
                            "기존 파일을 덮어쓰려면 사용자 확인이 필요합니다.",
                            hint=f"사람이 터미널에서 실행: {_person_line(ref, target)}. {other}",
                            at=str(target), data=detail)
        answer = ctx.ask(question, detail)
        if answer is not True:
            if answer is False:
                # Final for these bytes at this target, whichever draft asks next.
                rt_commit.record_decline(target, digest, by=ctx.client, home=ctx.drafts.home)
                raise ToolError("declined_by_person",
                                "덮어쓰지 않았습니다. 초안은 그대로 있습니다.",
                                hint=other, at=str(target))
            if ctx.client == "cli":
                raise ToolError("needs_person",
                                "덮어쓰기 확인에 터미널이 필요해 저장하지 않았습니다.",
                                hint=f"터미널에서 다시 실행하거나 --force를 붙이세요. {other}",
                                at=str(target), data=detail)
            raise ToolError("needs_person", "확인을 받지 못해 덮어쓰지 않았습니다.",
                            hint=f"사람이 터미널에서 실행: {_person_line(ref, target)}. {other}",
                            at=str(target), data=detail)
        policy = "person:" + ("tty" if ctx.client == "cli" else "elicitation")
        # The answer may have taken minutes: the path must still name the same
        # place, and that place must still be one the person allows (the
        # client may have taken a folder away meanwhile).
        if ctx.current_roots is not None:
            ctx.roots = ctx.current_roots()
        again = _target(ctx, args["to"] if args.get("to") else str(ref.source))
        if not _same_path(again, target):
            raise ToolError("target_changed", "확인하는 사이에 저장 경로가 바뀌었습니다.",
                            hint="경로를 확인하고 다시 저장하세요.", at=str(target))
        if ref.source is not None and ctx.roots is not None:
            try:
                ctx.roots.check(ref.source)
            except PathRefused as exc:
                raise ToolError(exc.code, exc.message, hint=exc.hint, at=exc.path) from exc

    provenance = _saved_provenance(record)
    if record is None and has_edits:
        # A draft appeared while we decided: what we checked is not what we'd write.
        raise ToolError("stale", "확인하는 사이에 초안이 바뀌어 저장하지 않았습니다.",
                        hint="초안을 다시 확인하고 저장하세요.", retryable=True,
                        data={"reason": "superseded_by_newer_candidate"})
    # An agent's save never publishes bytes a person refused here, even when
    # the "no" came from another session while this one was asking.
    honour = ctx.client != "cli"
    if record is None:
        receipt = rt_commit.commit(candidate, target, expected=expected, by=ctx.client,
                                   policy=policy, home=ctx.drafts.home,
                                   provenance=provenance, candidate_sha256=digest,
                                   draft=writer, honour_declines=honour)
    else:
        with ctx.drafts.lock(ref):
            # Re-read under the lock: an edit or another save may have landed
            # while we asked. Writing the old record back would lose it.
            first = record
            record = ctx.drafts.load(ref)
            if record is None:
                # Discarded while we asked: there is nothing the person agreed to.
                raise ToolError("stale", "확인하는 사이에 초안이 폐기되어 저장하지 않았습니다.",
                                hint="초안을 다시 만든 뒤 저장하세요.", retryable=False,
                                data={"reason": "superseded_by_newer_candidate"})
            head = record.get("head") or {}
            if record.get("instance") != first.get("instance") or (
                    has_edits and head.get("sha256") != head_input.sha256):
                raise ToolError("stale", "확인하는 사이에 초안이 바뀌어 저장하지 않았습니다.",
                                hint="초안을 다시 확인하고 저장하세요.", retryable=True,
                                data={"reason": "superseded_by_newer_candidate"})
            receipt = rt_commit.commit(candidate, target, expected=expected, by=ctx.client,
                                       policy=policy, home=ctx.drafts.home,
                                       provenance=provenance, candidate_sha256=digest,
                                       draft=writer, honour_declines=honour)
            record.setdefault("saves", []).append({
                "target": str(target), "sha256": receipt["sha256"],
                "revision": head_input.revision, "policy": policy,
                "unreviewed": unreviewed, "at": receipt["at"], "provenance": provenance})
            for cs in record.get("changesets", []):
                if cs.get("status") == "proposed":
                    cs["status"] = "applied"
            if ref.source is not None and _same_path(target, ref.source):
                # The person's file now holds the head, so the draft is based on
                # these bytes; without this the next read would call the file
                # "changed since the draft started".
                record["source"]["sha256"] = receipt["sha256"]
                record["source"]["rev"] = rev_of(receipt["sha256"])
            ctx.drafts.write(ref, record)
    return {"path": ref.label, "saved": str(target), "sha256": receipt["sha256"],
            "format": fmt, "replaced": receipt["replaced"] is not None,
            "acceptedVia": policy, "unreviewed": unreviewed, "lossy": lossy,
            "provenance": provenance,
            "undo": _undo_command(target) if receipt["undo"] or
            receipt["replaced"] is None else None}


def _undo_command(target: Path) -> str | None:
    """``rigorloom undo <target>`` to paste in a shell, or None when the name
    cannot be passed through one unchanged (``rt_term.shell_arg``)."""
    arg = shell_arg(str(target))
    return f"rigorloom undo {arg}" if arg else None


#: Formats the converter reads as markdown: their pictures are files on disk.
_MARKDOWN = (".md", ".markdown")


def _converted(ctx: Context, ref: Ref, head: Input, fmt: str) -> tuple[Path, list[str]]:
    """The head converted to ``fmt``, and what the conversion loses.

    A converted file is kept per revision with its loss list beside it, so a
    second save asks the person about the same losses as the first; a kept
    file without its list is converted again. Markdown pulls pictures in from
    other files, so for a confined caller (MCP) every picture it names passes
    the roots check on every save, kept file or not, and a fresh conversion
    reads a copy whose picture paths are the checked, absolute ones.
    """
    out_dir = private_dir(ctx.drafts.home / "exports" / ref.key)
    converted = out_dir / f"{head.rev}.{fmt}"
    meta = out_dir / f"{head.rev}.{fmt}.lossy.json"
    source = head.path
    gated = None
    if ctx.roots is not None and source.suffix.lower() in _MARKDOWN:
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError("invalid_params", "마크다운 파일이 UTF-8로 저장되어 있지 않습니다.",
                            hint="UTF-8로 다시 저장한 뒤 시도하세요.", at=str(source)) from exc
        gated = _gate_markdown_assets(
            ctx, text, ref.source.parent if ref.source is not None else None)
    try:
        cached = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    if converted.exists() and isinstance(cached, list):
        return converted, [str(x) for x in cached]
    temp = out_dir / f".{head.rev}.{secrets.token_hex(4)}.{fmt}"
    copy = None
    if gated is not None:
        copy = out_dir / f".{head.rev}.{secrets.token_hex(4)}.md"
        copy.write_text(gated, encoding="utf-8")
    try:
        data = doc_call(ctx.doc.convert, str(copy or source), str(temp), to=fmt)
        lossy = [str(x) for x in data.get("lossy") or []]
        # The layer names what it wrote (a PNG of a longer document is its
        # first page, beside ``temp``).
        os.replace(Path(data.get("out") or temp), converted)
        note = out_dir / f".{head.rev}.{secrets.token_hex(4)}.json"
        note.write_text(json.dumps(lossy, ensure_ascii=False), encoding="utf-8")
        os.replace(note, meta)
    finally:
        for leftover in (temp, copy):
            if leftover is not None and leftover.exists():
                try:
                    leftover.unlink()
                except OSError:
                    pass
    return converted, lossy


def _substituted_fonts(ctx: Context, path: Path) -> list[dict]:
    """Fonts the saved file will show with a stand-in, for the overwrite question.
    Unknown (the layer cannot tell) is an empty list, never a guess."""
    try:
        info = doc_call(ctx.doc.open, str(path))
    except ToolError:
        return []
    return [s for s in ((info.get("fonts") or {}).get("substituted") or [])
            if isinstance(s, dict)][:6]


def _saved_provenance(record: dict | None) -> dict:
    """Who wrote the bytes being saved. Any test-only (mock) change set in the
    head marks the whole save as mock, so the UI's 시험용 label cannot be lost."""
    sets = [c for c in (record or {}).get("changesets", [])
            if c.get("status") not in ("rejected", "withdrawn")]
    provs = [c.get("provenance") or {} for c in sets]
    return {"mock": any(p.get("mock") for p in provs),
            "agents": sorted({str(p["agent"]) for p in provs if p.get("agent")}),
            "providers": sorted({str(p["provider"]) for p in provs if p.get("provider")})}


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _save_text(r: dict) -> str:
    verb = "replaced" if r["replaced"] else "created"
    lines = [f"saved ({verb}): {r['saved']}  [{r['acceptedVia']}]"]
    if r.get("lossy"):
        lines.append("lost in conversion: " + ", ".join(r["lossy"]))
    if r.get("unreviewed"):
        lines.append(f"{r['unreviewed']} change set(s) were not reviewed by a person")
    if r.get("undo"):
        lines.append(f"undo: {r['undo']}")
    return "\n".join(lines)


register(Tool(
    name="save", title="저장",
    description="Write the draft to a file: a new path is created (never "
                "replacing anything); replacing an existing file asks the person "
                "first and keeps the old bytes for undo. `to` with .pdf/.docx/"
                ".hwp/.md/.png converts. The only tool that writes outside "
                "Rigorloom's own folder.",
    group="write", read_only=False, destructive=True, idempotent=False,
    input_schema=_obj({"path": S_PATH,
                       "to": {"type": "string", "minLength": 1, "maxLength": 4096}},
                      ["path"]),
    output_schema=_out({"path": {"type": "string"}, "saved": {"type": "string"},
                        "sha256": {"type": "string"}, "replaced": {"type": "boolean"},
                        "acceptedVia": {"type": "string"},
                        "provenance": {"type": "object"}}),
    run=_run_save, text=_save_text,
))


# ---------------------------------------------------------------------------
# changes
# ---------------------------------------------------------------------------

def _run_changes(ctx: Context, args: dict) -> dict:
    action = args.get("action", "list")
    if action == "list" and not args.get("path"):
        drafts = ctx.drafts.list()
        if ctx.roots is not None:
            # A client sees drafts of files inside its own roots, and new ones.
            def visible(d: dict) -> bool:
                if not d.get("source"):
                    return True
                try:
                    ctx.roots.check(d["source"])
                    return True
                except PathRefused:
                    return False
            drafts = [d for d in drafts if visible(d)]
        return {"action": "list", "drafts": drafts}
    if not args.get("path"):
        raise ToolError("invalid_params", "기록을 볼 문서의 경로가 빠졌습니다.", hint="문서 경로를 입력하세요.")
    ref = resolve(ctx, args["path"])
    record = ctx.drafts.load(ref)
    if record is None:
        return {"action": action, "path": ref.label, "draft": None, "changesets": []}
    sets = record.get("changesets", [])
    if args.get("id"):
        sets = [c for c in sets if c["id"] == args["id"]]
        if not sets:
            raise ToolError("not_found", f"번호가 {args['id']}인 변경 묶음을 찾을 수 없습니다.",
                            hint="이 문서의 초안 편집 기록에서 변경 묶음 번호를 확인하세요.",
                            candidates=[c["id"] for c in record.get("changesets", [])][-10:])
    slim = [{k: c.get(k) for k in ("id", "kind", "revision", "rev", "status", "author",
                                   "provenance", "base", "changedPages", "created",
                                   "items", "notes")}
            | {"ops": len(c.get("ops", []))} for c in sets]
    return {"action": action, "path": ref.label, "draft": summary(record),
            "changesets": slim, "saves": record.get("saves", [])}


def _changes_text(r: dict) -> str:
    if "drafts" in r:
        if not r["drafts"]:
            return "no drafts"
        return "\n".join(f"{d.get('source') or d.get('name') or '(new)'}  revision "
                         f"{d['revision']}  pending {d['pending']}  saved {d['saved']}"
                         for d in r["drafts"])
    if not r.get("draft"):
        return f"{r['path']}: no draft"
    lines = [f"{r['path']}: revision {r['draft']['revision']}, "
             f"{len(r['changesets'])} change set(s)"]
    for c in r["changesets"]:
        lines.append(f"  {c['id']}  {c['kind']}  {c['status']}  ops {c['ops']}  "
                     f"pages {c.get('changedPages') or []}")
        for note in c.get("notes") or []:
            lines.append(f"    person note: {safe_text(str(note))[:200]}")
    return "\n".join(lines)


register(Tool(
    name="changes", title="초안과 저장 기록",
    description="List drafts, or show a document's change sets with their status "
                "and any notes a person left when rejecting an item. Read this "
                "before re-proposing something.",
    group="changes",
    input_schema=_obj({"action": {"type": "string", "enum": ["list", "show"]},
                       "path": S_PATH, "id": {"type": "string", "maxLength": 64}}),
    output_schema=_out({"action": {"type": "string"}, "drafts": {"type": "array"},
                        "changesets": {"type": "array"}}),
    run=_run_changes, text=_changes_text,
))


# ---------------------------------------------------------------------------
# guide
# ---------------------------------------------------------------------------

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


def _topics() -> dict[str, Path]:
    if not KNOWLEDGE_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(KNOWLEDGE_DIR.glob("*.md"))
            if not p.stem.startswith("_")}


def _run_guide(ctx: Context, args: dict) -> dict:
    topics = _topics()
    if not topics:
        raise ToolError("capability_unavailable", "설치한 프로그램에 문서 작성 안내가 없습니다.")
    topic = args.get("topic")
    if not topic:
        index = KNOWLEDGE_DIR / "_index.md"
        return {"topics": sorted(topics),
                "text": index.read_text(encoding="utf-8") if index.exists() else ""}
    if topic not in topics:
        raise ToolError("not_found", f"'{topic}' 주제의 작성 안내가 없습니다.",
                        hint="주제를 빼고 guide를 실행해 주제 목록을 확인하세요.", candidates=sorted(topics))
    return {"topic": topic, "text": topics[topic].read_text(encoding="utf-8")}


register(Tool(
    name="guide", title="작성 안내",
    description="Korean document conventions with sources: gongmun (공문 항목 기호, "
                "날짜, 끝. 표시, 붙임), report (보고서), forms (양식), layout, writing, "
                "workflow. Read the one that fits before writing.",
    group="help",
    input_schema=_obj({"topic": {"type": "string", "maxLength": 40}}),
    output_schema=_out({"topic": {"type": "string"}, "topics": {"type": "array"},
                        "text": {"type": "string"}}),
    run=_run_guide, text=lambda r: r.get("text") or "topics: " + ", ".join(r.get("topics", [])),
    budget_chars=12000,
))
