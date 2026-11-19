# -*- coding: utf-8 -*-
"""A fake ``rt_doc`` for the CLI/MCP/agent layer's tests.

Same function names, signatures, result shapes and error envelope as the
contract in doc-core-api.md (draft 1, 2026-11-19), so the layer above can be
tested with no engine and no HWPX parsing. tests/test_rt_doc_contract.py is
the shared contract test that this fake and the real ``rt_doc`` both pass.

Document format ``.fdoc`` (UTF-8, deliberately not a real format):

* ``# ``/``## ``/``### `` lines are headings (levels 1-3).
* blank lines separate paragraphs; consecutive text lines form one paragraph
  (joined with ``\\n``). A line starting with a backslash is literal text with
  the backslash removed; the writer escapes any text line that would
  otherwise parse as markup (and writes an empty text line as ``\\``).
* a GitHub pipe table is a table; its first row (the header) is row 0, the
  ``|---|`` separator is not a row. ``\\|`` and ``\\\\`` escape inside cells.
  Each cell holds exactly one paragraph (``.../p0``); cell text is one line,
  stripped.
* ``[[place:<id>|<label>]]`` (optionally ``[[place:<id>|<label>|<kind>]]``,
  kind defaults to ``text``) is a fill seat; its text is whatever follows
  ``]]`` on that line, empty until filled.
* ``---page---`` is a page break (pages are 1-based).
* ``{style=<name>}`` on its own line gives the next block a style name.

Addresses: ``p<n>`` counts headings, paragraphs and fill seats in document
order (tables do not consume a ``p`` number); ``t<n>``; ``t<n>/r<r>/c<c>``;
``t<n>/r<r>/c<c>/p0``; ``h:"text"`` (exact, then unique prefix);
``place:<id>``; ``page:<n>`` (render/pages only).

Every public function returns ``{"ok": True, ...}`` or
``{"ok": False, "error": {code, message, at?, step?, done?, candidates?,
data?, retryable}}``. Bad input never raises; only programmer error does.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import re
import struct
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

ENGINE = "fake"
FORMAT = "fdoc"
SUFFIX = ".fdoc"
PAGE_W_PT = 595.28
PAGE_H_PT = 841.89
MAX_SCALE = 8.0
MAX_CANDIDATES = 5

#: Every code this fake can emit. All but the first three are in
#: runtime/scripts/rt_codes.py; ``stale``, ``expect_mismatch``, ``not_found``
#: and ``ambiguous_match`` are doc-core-api.md's own vocabulary.
ERROR_CODES = frozenset({
    "stale", "expect_mismatch", "ambiguous_match", "not_found",
    "invalid_params", "capability_unavailable", "source_rejected", "page_out_of_range",
})
RETRYABLE = frozenset({"stale"})

CONVERT_TARGETS = ("hwpx", "hwp", "pdf", "png", "md", "docx")
EDIT_OPS = ("set", "replace", "insert_after", "delete", "table.set_cells", "table.add_row",
            "table.delete_row", "fill", "style", "insert_table", "insert_equation",
            "insert_picture")

PARA_KINDS = ("heading", "para", "place")

EDAE_RULE = "ko.translationese.edae"
EDAE_MATCH = "에 대해"


# --------------------------------------------------------------------------- errors
class _Refusal(Exception):
    """Internal: becomes exactly one error envelope at the public boundary."""

    def __init__(self, code: str, message: str, **extra):
        assert code in ERROR_CODES, f"undeclared error code: {code!r}"
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.extra = {k: v for k, v in extra.items() if v is not None}

    def envelope(self) -> dict:
        error = {"code": self.code, "message": self.message, **self.extra,
                 "retryable": self.code in RETRYABLE}
        return {"ok": False, "error": error}


def _public(fn):
    """Turn every refusal (and every bad-file condition) into an envelope."""

    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _Refusal as refusal:
            return refusal.envelope()

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


# --------------------------------------------------------------------------- model
@dataclass(eq=False)
class Block:
    kind: str                     # heading | para | place | table | break
    text: str = ""
    level: int = 0
    rows: list = field(default_factory=list)   # table: list[list[str]]
    place_id: str = ""
    label: str = ""
    place_kind: str = "text"
    style: str | None = None


class _Doc:
    """An immutable-by-convention view: blocks plus derived address indexes."""

    def __init__(self, blocks: list[Block]):
        self.blocks = blocks
        self.paras: list[Block] = []
        self.tables: list[Block] = []
        self.page_of: dict[int, int] = {}
        page = 1
        for b in blocks:
            if b.kind == "break":
                page += 1
                continue
            self.page_of[id(b)] = page
            if b.kind in PARA_KINDS:
                self.paras.append(b)
            elif b.kind == "table":
                self.tables.append(b)
        self.page_count = page
        self._p = {id(b): i for i, b in enumerate(self.paras)}
        self._t = {id(b): i for i, b in enumerate(self.tables)}

    def addr(self, b: Block) -> str:
        if b.kind == "table":
            return f"t{self._t[id(b)]}"
        return f"p{self._p[id(b)]}"

    def has(self, b: Block) -> bool:
        return id(b) in self._p or id(b) in self._t

    def page(self, b: Block) -> int:
        return self.page_of[id(b)]

    def headings(self) -> list[Block]:
        return [b for b in self.paras if b.kind == "heading"]

    def places(self) -> list[Block]:
        return [b for b in self.paras if b.kind == "place"]

    def units(self) -> list[tuple[str, str, int]]:
        """(address, text, page) for every paragraph and every cell, document order."""
        out = []
        for b in self.blocks:
            if b.kind in PARA_KINDS:
                out.append((self.addr(b), b.text, self.page(b)))
            elif b.kind == "table":
                t = self._t[id(b)]
                for r, row in enumerate(b.rows):
                    for c, cell in enumerate(row):
                        out.append((f"t{t}/r{r}/c{c}", cell, self.page(b)))
        return out


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(row) for row in rows)


def _block_text(b: Block) -> str:
    return _table_text(b.rows) if b.kind == "table" else b.text


# --------------------------------------------------------------------------- parse / write
_HEADING = re.compile(r"(#{1,3}) (.*)")
_PLACE = re.compile(r"\[\[place:([^|\]\s]+)\|([^|\]]*)(?:\|([A-Za-z_]+))?\]\](.*)")
_STYLE = re.compile(r"\{style=([^{}\n]*)\}")
_PAGE = "---page---"


_SEPARATOR = re.compile(r"\|?(\s*:?-{3,}:?\s*\|)+\s*(:?-{3,}:?\s*)?")


def _is_separator(line: str) -> bool:
    """Only the line right after the header row may be the |---| separator."""
    return _SEPARATOR.fullmatch(line.strip()) is not None


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    cells: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur.append(s[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = "".join(cur)
    if tail.strip():
        cells.append(tail)
    return [c.strip() for c in cells]


def parse(text: str, *, markdown: bool = False) -> list[Block]:
    """Parse .fdoc text. ``markdown=True`` also accepts ``####``+ headings (clamped to 3)."""
    blocks: list[Block] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    para: list[str] | None = None
    style: str | None = None

    def add(b: Block) -> None:
        nonlocal style
        if b.kind != "break":
            b.style, style = style, None
        blocks.append(b)

    def flush() -> None:
        nonlocal para
        if para is not None:
            add(Block("para", "\n".join(para)))
            para = None

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("\\"):
            para = (para or []) + [line[1:]]
            continue
        if not line.strip():
            flush()
            continue
        if line == _PAGE:
            flush()
            add(Block("break"))
            continue
        m = _HEADING.fullmatch(line)
        if m is None and markdown:
            m = re.fullmatch(r"(#{1,6}) (.*)", line)
        if m:
            flush()
            add(Block("heading", m.group(2), level=min(len(m.group(1)), 3)))
            continue
        if line.lstrip().startswith("|"):
            flush()
            rows = []
            j = i - 1
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                if not (j == i and _is_separator(lines[j])):
                    rows.append(_split_row(lines[j]))
                j += 1
            i = j
            width = max((len(r) for r in rows), default=0)
            rows = [r + [""] * (width - len(r)) for r in rows if width]
            if rows and width:
                add(Block("table", rows=rows))
            continue
        m = _PLACE.fullmatch(line)
        if m:
            flush()
            add(Block("place", m.group(4), place_id=m.group(1), label=m.group(2),
                      place_kind=m.group(3) or "text"))
            continue
        m = _STYLE.fullmatch(line)
        if m and para is None:
            style = m.group(1)
            continue
        para = (para or []) + [line]
    flush()
    return blocks


def _needs_escape(line: str) -> bool:
    return (not line.strip() or line[0] in "#|\\" or line.lstrip().startswith("|")
            or line.startswith("[[place:") or line.startswith("{style=") or line == _PAGE)


def _cell_out(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _one_line(text: str) -> str:
    return " ".join(text.splitlines())


def serialize(blocks: list[Block]) -> str:
    chunks: list[str] = []
    for b in blocks:
        lines: list[str] = []
        if b.kind == "break":
            chunks.append(_PAGE)
            continue
        if b.style is not None:
            lines.append("{style=%s}" % b.style)
        if b.kind == "heading":
            lines.append("#" * b.level + " " + _one_line(b.text))
        elif b.kind == "para":
            for line in b.text.split("\n"):
                lines.append("\\" + line if _needs_escape(line) else line)
        elif b.kind == "place":
            kind = "" if b.place_kind == "text" else f"|{b.place_kind}"
            lines.append(f"[[place:{b.place_id}|{b.label}{kind}]]{_one_line(b.text)}")
        elif b.kind == "table":
            for r, row in enumerate(b.rows):
                lines.append("| " + " | ".join(_cell_out(c) for c in row) + " |")
                if r == 0:
                    lines.append("|" + "---|" * len(row))
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n"


def _cell_value(value: str) -> str:
    return _one_line(value).strip()


# --------------------------------------------------------------------------- files
def _rev(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _path(value, what: str = "path") -> Path:
    if not isinstance(value, (str, Path)) or not str(value) or "\x00" in str(value):
        raise _Refusal("invalid_params", f"{what}: 경로가 아닙니다")
    return Path(value)


def _load(path, *, suffixes=(SUFFIX,)) -> tuple[_Doc, bytes]:
    p = _path(path)
    if p.suffix.lower() not in suffixes:
        raise _Refusal("capability_unavailable",
                       f"가짜 rt_doc은 {', '.join(suffixes)} 파일만 읽습니다")
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        raise _Refusal("not_found", "파일이 없습니다") from None
    except OSError as exc:
        raise _Refusal("source_rejected", f"파일을 읽지 못했습니다: {exc.strerror or exc}") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Refusal("source_rejected", "UTF-8 문서가 아닙니다") from None
    return _Doc(parse(text, markdown=p.suffix.lower() == ".md")), data


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a.absolute() == b.absolute()


def _write(out: Path, data: bytes) -> None:
    if not out.parent.is_dir():
        raise _Refusal("invalid_params", "저장할 폴더가 없습니다")
    if out.is_dir():
        raise _Refusal("invalid_params", "저장 경로가 폴더입니다")
    try:
        out.write_bytes(data)
    except OSError as exc:
        raise _Refusal("invalid_params", f"저장하지 못했습니다: {exc.strerror or exc}") from None


def _out_path(out, src: Path) -> Path:
    if out is None:
        raise _Refusal("invalid_params", "out을 지정하세요")
    o = _path(out, "out")
    if _same_file(o, src):
        raise _Refusal("invalid_params", "원본에 덮어쓸 수 없습니다. 다른 out을 지정하세요")
    return o


# --------------------------------------------------------------------------- addresses
_A_P = re.compile(r"p(\d+)")
_A_T = re.compile(r"t(\d+)")
_A_CELL = re.compile(r"t(\d+)/r(\d+)/c(\d+)(?:/p(\d+))?")
_A_PAGE = re.compile(r"page:(\d+)")


@dataclass
class _Target:
    kind: str            # para | table | cell
    block: Block
    addr: str
    row: list | None = None
    r: int = 0
    c: int = 0


def _nearest_numbers(n: int, count: int, fmt: str) -> list[str]:
    order = sorted(range(count), key=lambda k: (abs(k - n), k))[:MAX_CANDIDATES]
    return [fmt.format(k) for k in sorted(order)]


def _close(word: str, options: list[str]) -> list[str]:
    near = difflib.get_close_matches(word, options, n=MAX_CANDIDATES, cutoff=0.0)
    seen: list[str] = []
    for o in near + options:
        if o not in seen:
            seen.append(o)
    return seen[:MAX_CANDIDATES]


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _resolve(doc: _Doc, at, *, step: int | None = None) -> _Target:
    if not isinstance(at, str) or not at.strip():
        raise _Refusal("invalid_params", "주소가 비었습니다", step=step)
    at = at.strip()
    if m := _A_P.fullmatch(at):
        n = int(m.group(1))
        if n < len(doc.paras):
            return _Target("para", doc.paras[n], f"p{n}")
        raise _Refusal("not_found", f"{at} 문단이 없습니다", at=at, step=step,
                       candidates=_nearest_numbers(n, len(doc.paras), "p{}"))
    if m := _A_T.fullmatch(at):
        n = int(m.group(1))
        if n < len(doc.tables):
            return _Target("table", doc.tables[n], f"t{n}")
        raise _Refusal("not_found", f"{at} 표가 없습니다", at=at, step=step,
                       candidates=_nearest_numbers(n, len(doc.tables), "t{}"))
    if m := _A_CELL.fullmatch(at):
        t, r, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        p = int(m.group(4)) if m.group(4) is not None else 0
        if t >= len(doc.tables):
            raise _Refusal("not_found", f"t{t} 표가 없습니다", at=at, step=step,
                           candidates=_nearest_numbers(t, len(doc.tables), "t{}"))
        b = doc.tables[t]
        if r < len(b.rows) and c < len(b.rows[r]) and p == 0:
            return _Target("cell", b, f"t{t}/r{r}/c{c}", row=b.rows[r], r=r, c=c)
        cells = [(rr, cc) for rr in range(len(b.rows)) for cc in range(len(b.rows[rr]))]
        cells.sort(key=lambda rc: (abs(rc[0] - r) + abs(rc[1] - c), rc))
        raise _Refusal("not_found", f"{at} 칸이 없습니다", at=at, step=step,
                       candidates=[f"t{t}/r{rr}/c{cc}" for rr, cc in cells[:MAX_CANDIDATES]])
    if at.startswith("h:"):
        want = _unquote(at[2:].strip())
        heads = doc.headings()
        exact = [h for h in heads if h.text == want]
        hits = exact or ([h for h in heads if h.text.startswith(want)] if want else [])
        if len(hits) == 1:
            return _Target("para", hits[0], doc.addr(hits[0]))
        if len(hits) > 1:
            raise _Refusal("ambiguous_match", "같은 제목이 여럿입니다", at=at, step=step,
                           candidates=[doc.addr(h) for h in hits])
        raise _Refusal("not_found", "그런 제목이 없습니다", at=at, step=step,
                       candidates=_close(want, [h.text for h in heads]))
    if at.startswith("place:"):
        return _resolve_place(doc, at[len("place:"):], step=step, at=at)
    if _A_PAGE.fullmatch(at):
        raise _Refusal("invalid_params", "쪽 주소는 render·pages에서만 씁니다", at=at, step=step)
    raise _Refusal("invalid_params", f"주소 형식이 아닙니다: {at}", at=at, step=step)


def _resolve_place(doc: _Doc, pid, *, step=None, at=None) -> _Target:
    if not isinstance(pid, str) or not pid.strip():
        raise _Refusal("invalid_params", "자리 id가 비었습니다", step=step)
    pid = pid.strip()
    if pid.startswith("place:"):
        pid = pid[len("place:"):]
    for b in doc.places():
        if b.place_id == pid:
            return _Target("para", b, doc.addr(b))
    raise _Refusal("not_found", "그런 자리가 없습니다", at=at or f"place:{pid}", step=step,
                   candidates=_close(pid, [b.place_id for b in doc.places()]))


def _target_text(t: _Target) -> str:
    if t.kind == "cell":
        return t.row[t.c]
    return _block_text(t.block)


# --------------------------------------------------------------------------- read side
@_public
def open(path) -> dict:  # noqa: A001 - contract name
    doc, data = _load(path)
    return {"ok": True, "rev": _rev(data), "format": FORMAT, "pages": doc.page_count,
            "sections": 1, "fonts": {"used": [], "substituted": []}, "engine": ENGINE}


@_public
def outline(path) -> dict:
    doc, data = _load(path)
    return {
        "ok": True, "rev": _rev(data),
        "headings": [{"at": doc.addr(b), "level": b.level, "text": b.text, "page": doc.page(b)}
                     for b in doc.headings()],
        "tables": [{"at": doc.addr(b), "rows": len(b.rows), "cols": len(b.rows[0]) if b.rows else 0,
                    "page": doc.page(b)} for b in doc.tables],
        "places": [{"id": b.place_id, "at": doc.addr(b), "label": b.label, "kind": b.place_kind,
                    "page": doc.page(b)} for b in doc.places()],
    }


def _read_block(doc: _Doc, b: Block, addr: str, *, kind: str | None = None, text: str | None = None,
                with_runs: bool) -> dict:
    text = _block_text(b) if text is None else text
    out = {"at": addr, "kind": kind or b.kind, "text": text}
    if b.kind == "heading" and kind is None:
        out["level"] = b.level
    if b.kind == "place" and kind is None:
        out["place"] = b.place_id
    if with_runs:
        out["runs"] = [{"text": text}]
    if b.style is not None and kind is None:
        out["style"] = b.style
    return out


@_public
def read(path, at=None, *, with_runs=False) -> dict:
    doc, data = _load(path)
    if at is None:
        blocks = [_read_block(doc, b, doc.addr(b), with_runs=with_runs)
                  for b in doc.blocks if b.kind != "break"]
    else:
        t = _resolve(doc, at)
        if t.kind == "cell":
            blocks = [_read_block(doc, t.block, t.addr, kind="cell", text=t.row[t.c],
                                  with_runs=with_runs)]
        else:
            blocks = [_read_block(doc, t.block, t.addr, with_runs=with_runs)]
    return {"ok": True, "rev": _rev(data), "blocks": blocks}


def _scope_units(doc: _Doc, scope) -> list[tuple[str, str, int]]:
    units = doc.units()
    if scope is None:
        return units
    t = _resolve(doc, scope)
    if t.kind == "cell":
        return [u for u in units if u[0] == t.addr]
    if t.kind == "table":
        return [u for u in units if u[0].startswith(t.addr + "/")]
    if t.block.kind == "heading":
        # the heading's section: up to the next heading of the same or a higher level
        start = doc.blocks.index(t.block)
        members: list[Block] = [t.block]
        for b in doc.blocks[start + 1:]:
            if b.kind == "heading" and b.level <= t.block.level:
                break
            members.append(b)
        prefixes = {doc.addr(b) for b in members if b.kind != "break"}
        return [u for u in units if u[0].split("/")[0] in prefixes]
    return [u for u in units if u[0] == t.addr]


@_public
def find(path, query, *, regex=False, scope=None) -> dict:
    doc, data = _load(path)
    if not isinstance(query, str) or query == "":
        raise _Refusal("invalid_params", "찾을 글이 비었습니다")
    try:
        pattern = re.compile(query if regex else re.escape(query))
    except re.error as exc:
        raise _Refusal("invalid_params", f"정규식 오류: {exc}") from None
    hits = []
    for addr, text, page in _scope_units(doc, scope):
        for m in pattern.finditer(text):
            if m.end() > m.start():
                hits.append({"at": addr, "start": m.start(), "end": m.end(), "text": m.group(0),
                             "page": page})
    return {"ok": True, "rev": _rev(data), "hits": hits}


# --------------------------------------------------------------------------- pages / render
def _signals(doc: _Doc) -> list[dict]:
    """lone_heading: a heading is the last block before a page break."""
    out = []
    prev: Block | None = None
    for b in doc.blocks:
        if b.kind == "break" and prev is not None and prev.kind == "heading":
            out.append({"page": doc.page(prev), "kind": "lone_heading", "at": doc.addr(prev)})
        if b.kind != "break":
            prev = b
        else:
            prev = None
    return out


@_public
def pages(path) -> dict:
    doc, data = _load(path)
    first: dict[int, str] = {}
    for b in doc.blocks:
        if b.kind != "break":
            first.setdefault(doc.page(b), doc.addr(b))
    sig = _signals(doc)
    return {"ok": True, "rev": _rev(data), "count": doc.page_count,
            "pages": [{"n": n, "starts_with": first.get(n),
                       "signals": [{"kind": s["kind"], "at": s["at"]} for s in sig if s["page"] == n]}
                      for n in range(1, doc.page_count + 1)]}


def _page_numbers(pages_arg, count: int) -> list[int]:
    if pages_arg is None or pages_arg == "all":
        return list(range(1, count + 1))
    items = pages_arg if isinstance(pages_arg, (list, tuple)) else [pages_arg]
    out: list[int] = []
    for item in items:
        if isinstance(item, str) and (m := _A_PAGE.fullmatch(item.strip())):
            item = int(m.group(1))
        if isinstance(item, bool) or not isinstance(item, int):
            raise _Refusal("invalid_params", "쪽 번호는 1부터 세는 정수입니다")
        if not 1 <= item <= count:
            raise _Refusal("page_out_of_range", f"{item}쪽은 없습니다 (전체 {count}쪽)",
                           at=f"page:{item}")
        if item not in out:
            out.append(item)
    if not out:
        raise _Refusal("invalid_params", "쪽을 하나 이상 고르세요")
    return out


def _png(width: int, height: int) -> bytes:
    """A blank white 8-bit grayscale PNG, stdlib only."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    raw = (b"\x00" + b"\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _pdf(count: int) -> bytes:
    """A minimal valid PDF with ``count`` blank A4 pages."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(count))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode()]
    for _ in range(count):
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W_PT} {PAGE_H_PT}] "
                       "/Resources << >> >>".encode())
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


@_public
def render(path, pages=None, *, scale=2.0, fmt="png", out_dir=None) -> dict:  # noqa: A002
    doc, data = _load(path)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 0 < scale <= MAX_SCALE:
        raise _Refusal("invalid_params", f"scale은 0보다 크고 {MAX_SCALE:g} 이하입니다")
    if fmt not in ("png", "pdf"):
        raise _Refusal("invalid_params", "fmt는 png 또는 pdf입니다")
    numbers = _page_numbers(pages, doc.page_count)
    if out_dir is None:
        target = Path(tempfile.mkdtemp(prefix="fake-rt-doc-"))
    else:
        target = _path(out_dir, "out_dir")
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _Refusal("invalid_params", f"출력 폴더를 만들 수 없습니다: {exc.strerror or exc}") from None
    stem = Path(path).stem
    result = []
    if fmt == "pdf":
        pdf = target / f"{stem}.pdf"
        _write(pdf, _pdf(len(numbers)))
        for n in numbers:
            result.append({"n": n, "file": str(pdf), "width_pt": PAGE_W_PT, "height_pt": PAGE_H_PT})
    else:
        w, h = max(1, round(PAGE_W_PT * scale)), max(1, round(PAGE_H_PT * scale))
        png = _png(w, h)
        for n in numbers:
            f = target / f"{stem}-p{n}.png"
            _write(f, png)
            result.append({"n": n, "file": str(f), "width_pt": PAGE_W_PT, "height_pt": PAGE_H_PT,
                           "px_w": w, "px_h": h})
    return {"ok": True, "rev": _rev(data), "pages": result}


# --------------------------------------------------------------------------- edit
class _Session:
    """One edit: blocks keep their identity, so every op resolves against the base."""

    def __init__(self, base: _Doc):
        self.base = base                 # address indexes built on the base snapshot
        self.deleted: set[int] = set()   # id(block)
        self.inserted: dict[int, list[Block]] = {}
        self.new_rows: dict[tuple[int, int | None], list[list]] = {}
        self.deleted_rows: set[int] = set()   # id(row)
        self.touched: dict[int, list[Block]] = {}   # op index -> blocks it changed
        self.step = 0

    def live(self, b: Block) -> bool:
        return id(b) not in self.deleted

    def check_live(self, t: _Target, step: int) -> None:
        if not self.live(t.block):
            raise _Refusal("invalid_params", f"{t.addr}는 이 편집에서 이미 지웠습니다", at=t.addr,
                           step=step)
        if t.row is not None and id(t.row) in self.deleted_rows:
            raise _Refusal("invalid_params", f"{t.addr} 행은 이 편집에서 이미 지웠습니다",
                           at=t.addr, step=step)

    def touch(self, b: Block) -> None:
        self.touched.setdefault(self.step, []).append(b)

    def result_blocks(self) -> list[Block]:
        out: list[Block] = []
        for b in self.base.blocks:
            if self.live(b):
                out.append(b)
            out.extend(self.inserted.get(id(b), []))
            if b.kind == "table":
                rows = list(self.new_rows.get((id(b), None), []))
                for row in b.rows:
                    if id(row) not in self.deleted_rows:
                        rows.append(row)
                    rows.extend(self.new_rows.get((id(b), id(row)), []))
                b.rows = rows
        return out


def _need(op: dict, key: str, kind, step: int, *, optional=False):
    if key not in op or op[key] is None:
        if optional:
            return None
        raise _Refusal("invalid_params", f"{op.get('op')}에 {key}가 없습니다", step=step)
    value = op[key]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise _Refusal("invalid_params", f"{op.get('op')}.{key} 형식이 틀렸습니다", step=step)
    return value


def _check_expect(op: dict, t: _Target, step: int, done: list[int]) -> None:
    if "expect" not in op or op["expect"] is None:
        return
    want = op["expect"]
    if not isinstance(want, str):
        raise _Refusal("invalid_params", "expect는 글자열입니다", step=step)
    actual = _target_text(t)
    if actual != want:
        raise _Refusal("expect_mismatch", f"{t.addr}의 글이 예상과 다릅니다", at=t.addr, step=step,
                       done=list(done), data={"actual": actual})


def _parse_markdown(md: str, step: int) -> list[Block]:
    blocks = parse(md, markdown=True)
    if not [b for b in blocks if b.kind != "break"]:
        raise _Refusal("invalid_params", "넣을 내용이 비었습니다", step=step)
    return blocks


def _grid(value, step: int) -> list[list]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(r, list) for r in value)
            or not all(c is None or isinstance(c, (str, int, float)) and not isinstance(c, bool)
                       for r in value for c in r)):
        raise _Refusal("invalid_params", "grid는 글자열 행의 목록입니다", step=step)
    return value


def _apply(s: _Session, i: int, op: dict, done: list[int]) -> dict:
    doc = s.base
    kind = op.get("op")
    if kind in ("insert_equation", "insert_picture"):
        raise _Refusal("capability_unavailable", f"가짜 rt_doc은 {kind}를 못 합니다", step=i,
                       done=list(done))

    if kind == "set":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        text = _need(op, "text", str, i)
        s.check_live(t, i)
        _check_expect(op, t, i, done)
        if t.kind == "table":
            raise _Refusal("invalid_params", "표 전체는 set할 수 없습니다. 칸 주소를 쓰세요",
                           at=t.addr, step=i)
        if t.kind == "cell":
            t.row[t.c] = _cell_value(text)
        else:
            t.block.text = text if t.block.kind == "para" else _one_line(text)
        s.touch(t.block)
        return {"i": i, "op": kind, "at": t.addr}

    if kind == "replace":
        needle = _need(op, "find", str, i)
        repl = op.get("with")
        if needle == "" or not isinstance(repl, str):
            raise _Refusal("invalid_params", "replace에는 find와 with 글자열이 필요합니다", step=i)
        every = bool(op.get("all", False))
        if op.get("at") is not None:
            t = _resolve(doc, _need(op, "at", str, i), step=i)
            s.check_live(t, i)
            if t.kind == "table":
                scope = [_Target("cell", t.block, f"{t.addr}/r{r}/c{c}", row=row, r=r, c=c)
                         for r, row in enumerate(t.block.rows) if id(row) not in s.deleted_rows
                         for c in range(len(row))]
            else:
                scope = [t]
        else:
            scope = []
            for b in doc.blocks:
                if not s.live(b) or b.kind == "break":
                    continue
                if b.kind == "table":
                    ta = doc.addr(b)
                    scope += [_Target("cell", b, f"{ta}/r{r}/c{c}", row=row, r=r, c=c)
                              for r, row in enumerate(b.rows) if id(row) not in s.deleted_rows
                              for c in range(len(row))]
                else:
                    scope.append(_Target("para", b, doc.addr(b)))
        matched = [(t, _target_text(t).count(needle)) for t in scope]
        matched = [(t, n) for t, n in matched if n]
        total = sum(n for _, n in matched)
        if total == 0:
            raise _Refusal("not_found", "찾는 글이 없습니다", at=op.get("at"), step=i,
                           done=list(done))
        if total > 1 and not every:
            raise _Refusal("ambiguous_match", f"'{needle}'이(가) {total}곳에 있습니다. at이나 all을 쓰세요",
                           step=i, done=list(done), candidates=[t.addr for t, _ in matched])
        if op.get("expect") is not None:
            if len(matched) > 1:
                raise _Refusal("invalid_params", "expect는 한 곳을 바꿀 때만 씁니다", step=i)
            _check_expect(op, matched[0][0], i, done)
        for t, _ in matched:
            if t.kind == "cell":
                t.row[t.c] = _cell_value(t.row[t.c].replace(needle, repl))
            elif t.block.kind == "para":
                t.block.text = t.block.text.replace(needle, repl)
            else:
                t.block.text = _one_line(t.block.text.replace(needle, repl))
            s.touch(t.block)
        at = matched[0][0].addr if len(matched) == 1 else op.get("at")
        return {"i": i, "op": kind, "at": at, "count": total}

    if kind in ("insert_after", "insert_table"):
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        if t.kind == "cell":
            raise _Refusal("invalid_params", "칸 안에는 넣을 수 없습니다. 문단이나 표 주소를 쓰세요",
                           at=t.addr, step=i)
        if kind == "insert_after":
            new = _parse_markdown(_need(op, "markdown", str, i), i)
        else:
            data = _grid(_need(op, "data", list, i), i)
            width = max(len(r) for r in data)
            rows = [[_cell_value("" if c is None else str(c)) for c in r] + [""] * (width - len(r))
                    for r in data]
            if not width:
                raise _Refusal("invalid_params", "표 data가 비었습니다", step=i)
            new = [Block("table", rows=rows)]
        like = op.get("like")
        if like is not None:
            lt = _resolve(doc, like if isinstance(like, str) else "", step=i)
            for b in new:
                if b.kind != "break" and b.style is None:
                    b.style = lt.block.style
        s.inserted.setdefault(id(t.block), []).extend(new)
        for b in new:
            s.touch(b)
        return {"i": i, "op": kind, "at": t.addr}

    if kind == "delete":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        if t.kind == "cell":
            raise _Refusal("invalid_params", "칸은 지울 수 없습니다. table.delete_row를 쓰세요",
                           at=t.addr, step=i)
        s.check_live(t, i)
        _check_expect(op, t, i, done)
        s.deleted.add(id(t.block))
        s.touch(t.block)
        return {"i": i, "op": kind, "at": t.addr}

    if kind == "table.set_cells":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        if t.kind == "para":
            raise _Refusal("invalid_params", "표나 칸 주소를 쓰세요", at=t.addr, step=i)
        s.check_live(t, i)
        grid = _grid(op.get("grid"), i)
        base_rows = t.block.rows
        r0, c0 = (t.r, t.c) if t.kind == "cell" else (0, 0)
        if r0 + len(grid) > len(base_rows) or any(c0 + len(r) > len(base_rows[0]) for r in grid):
            raise _Refusal("invalid_params", "grid가 표 밖으로 나갑니다", at=t.addr, step=i)
        for dr, values in enumerate(grid):
            row = base_rows[r0 + dr]
            if id(row) in s.deleted_rows:
                raise _Refusal("invalid_params", "이 편집에서 지운 행입니다", at=t.addr, step=i)
            for dc, value in enumerate(values):
                if value is not None:
                    row[c0 + dc] = _cell_value(str(value))
        s.touch(t.block)
        ta = doc.addr(t.block)
        return {"i": i, "op": kind, "at": f"{ta}/r{r0}/c{c0}"}

    if kind == "table.add_row":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        if t.kind == "para":
            raise _Refusal("invalid_params", "표 주소를 쓰세요", at=t.addr, step=i)
        s.check_live(t, i)
        rows = t.block.rows
        after = op.get("after", len(rows) - 1)
        if isinstance(after, bool) or not isinstance(after, int) or not -1 <= after < len(rows):
            raise _Refusal("invalid_params", f"after는 -1부터 {len(rows) - 1} 사이 행 번호입니다",
                           at=t.addr, step=i)
        width = len(rows[0])
        values = op.get("values") or []
        if not isinstance(values, list) or len(values) > width:
            raise _Refusal("invalid_params", "values가 표 폭보다 깁니다", at=t.addr, step=i)
        if op.get("like") is not None and (isinstance(op["like"], bool)
                                           or not isinstance(op["like"], int)
                                           or not 0 <= op["like"] < len(rows)):
            raise _Refusal("invalid_params", "like는 행 번호입니다", at=t.addr, step=i)
        new = [_cell_value("" if v is None else str(v)) for v in values] + [""] * (width - len(values))
        key = (id(t.block), None if after == -1 else id(rows[after]))
        s.new_rows.setdefault(key, []).append(new)
        s.touch(t.block)
        return {"i": i, "op": kind, "at": doc.addr(t.block)}

    if kind == "table.delete_row":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        if t.kind == "table" and op.get("row") is not None:
            r = op["row"]
            if isinstance(r, bool) or not isinstance(r, int) or not 0 <= r < len(t.block.rows):
                raise _Refusal("not_found", "그런 행이 없습니다", at=t.addr, step=i,
                               candidates=_nearest_numbers(r if isinstance(r, int) else 0,
                                                           len(t.block.rows), t.addr + "/r{}/c0"))
            t = _Target("cell", t.block, f"{t.addr}/r{r}/c0", row=t.block.rows[r], r=r, c=0)
        if t.kind != "cell":
            raise _Refusal("invalid_params", "지울 행을 칸 주소(t/r/c)로 쓰세요", at=t.addr, step=i)
        s.check_live(t, i)
        live_rows = [row for row in t.block.rows if id(row) not in s.deleted_rows]
        if len(live_rows) <= 1:
            raise _Refusal("invalid_params", "표의 마지막 행은 지울 수 없습니다. delete를 쓰세요",
                           at=t.addr, step=i)
        s.deleted_rows.add(id(t.row))
        s.touch(t.block)
        return {"i": i, "op": kind, "at": t.addr}

    if kind == "fill":
        t = _resolve_place(doc, op.get("place"), step=i)
        text = _need(op, "text", str, i)
        s.check_live(t, i)
        t.block.text = _one_line(text)
        s.touch(t.block)
        return {"i": i, "op": kind, "at": t.addr}

    if kind == "style":
        t = _resolve(doc, _need(op, "at", str, i), step=i)
        name = op.get("style")
        if not isinstance(name, str) or not name or re.search(r"[{}\n]", name):
            raise _Refusal("invalid_params", "style은 중괄호·줄바꿈 없는 이름입니다", step=i)
        if t.kind == "cell":
            raise _Refusal("invalid_params", "칸에는 스타일을 줄 수 없습니다", at=t.addr, step=i)
        s.check_live(t, i)
        t.block.style = name
        s.touch(t.block)
        return {"i": i, "op": kind, "at": t.addr}

    raise _Refusal("invalid_params", f"모르는 op입니다: {kind!r}", step=i,
                   candidates=_close(str(kind), list(EDIT_OPS)))


@_public
def edit(path, ops, *, base, out=None, in_place=False, preview=False) -> dict:
    src = _path(path)
    base_doc, data = _load(src)
    if in_place:
        raise _Refusal("invalid_params", "가짜 rt_doc은 제자리 저장을 하지 않습니다. out을 쓰세요")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{12}", base):
        raise _Refusal("invalid_params", "base는 read가 준 rev(12자리 16진수)입니다")
    if preview:
        out_path = Path(tempfile.mkdtemp(prefix="fake-rt-doc-preview-")) / src.name
    else:
        out_path = _out_path(out, src)
    rev_before = _rev(data)
    if base != rev_before:
        raise _Refusal("stale", "문서가 바뀌었습니다. 다시 읽고 고치세요",
                       data={"rev": rev_before})
    if not isinstance(ops, list) or not ops or not all(isinstance(o, dict) for o in ops):
        raise _Refusal("invalid_params", "ops는 op 객체의 목록입니다")

    work = _Doc(copy.deepcopy(base_doc.blocks))
    origin = {id(w): b for w, b in zip(work.blocks, base_doc.blocks)}
    s = _Session(work)
    applied: list[dict] = []
    for i, op in enumerate(ops):
        s.step = i
        done = [a["i"] for a in applied]
        try:
            applied.append(_apply(s, i, op, done))
        except _Refusal as refusal:
            refusal.extra.setdefault("step", i)
            refusal.extra.setdefault("done", done)
            raise

    new_doc = _Doc(s.result_blocks())
    payload = serialize(new_doc.blocks).encode("utf-8")
    _write(out_path, payload)

    remap = []
    for w in work.blocks:
        if w.kind == "break":
            continue
        before = base_doc.addr(origin[id(w)])
        after = new_doc.addr(w) if new_doc.has(w) else None
        if after != before:
            remap.append({"from": before, "to": after})

    def landing(b: Block) -> tuple[int, int]:
        """(page, position on that page) where ``b`` is, or where it was if deleted."""
        if not new_doc.has(b):
            k = work.blocks.index(b)
            prev = [x for x in work.blocks[:k] if new_doc.has(x)]
            if not prev:
                return 1, 0
            b = prev[-1]
        page = new_doc.page(b)
        same = [x for x in new_doc.blocks if x.kind != "break" and new_doc.page(x) == page]
        return page, same.index(b)

    first_touch = {i: landing(blocks[0]) for i, blocks in s.touched.items()}
    pages_changed = sorted({landing(b)[0] for blocks in s.touched.values() for b in blocks})
    result = {"ok": True, "rev_before": rev_before, "rev": _rev(payload), "out": str(out_path),
              "applied": applied, "remap": remap, "changed_pages": pages_changed,
              "signals": [{"page": x["page"], "kind": x["kind"]} for x in _signals(new_doc)
                          if x["page"] in pages_changed]}
    if preview:
        # The fake has no layout: every block is one 20 pt band from the top margin.
        result["changed"] = [{"i": i, "page": page, "rect": [56.7, 56.7 + 20.0 * k, PAGE_W_PT - 113.4, 20.0]}
                             for i, (page, k) in sorted(first_touch.items())]
    return result


# --------------------------------------------------------------------------- convert / new
def _markdown(doc: _Doc) -> tuple[str, list[str]]:
    lossy: set[str] = set()
    chunks = []
    for b in doc.blocks:
        if b.kind == "break":
            lossy.add("page_breaks")
            continue
        if b.style is not None:
            lossy.add("styles")
        if b.kind == "heading":
            chunks.append("#" * b.level + " " + b.text)
        elif b.kind == "para":
            chunks.append(b.text)
        elif b.kind == "place":
            lossy.add("places")
            chunks.append(f"{b.label}: {b.text}" if b.label else b.text)
        elif b.kind == "table":
            lines = []
            for r, row in enumerate(b.rows):
                lines.append("| " + " | ".join(_cell_out(c) for c in row) + " |")
                if r == 0:
                    lines.append("|" + "---|" * len(row))
            chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n", sorted(lossy)


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

_HWPX_VERSION = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                 '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
                 'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1" '
                 'os="1" xmlVersion="1.4" application="rigorloom-fake-rt-doc" appVersion="0"/>')
_HWPX_CONTAINER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                   '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
                   'media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>')
_HWPX_HPF = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
             '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">'
             '<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>'
             '<opf:manifest>'
             '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
             '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
             '</opf:manifest><opf:spine><opf:itemref idref="header" linear="yes"/>'
             '<opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>')


def _hwpx_header() -> str:
    para_prs = "".join(
        f'<hh:paraPr id="{i}"><hh:heading type="{"OUTLINE" if i else "NONE"}" idRef="0" '
        f'level="{max(i - 1, 0)}"/></hh:paraPr>' for i in range(4))
    styles = ['<hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" '
              'charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/>']
    styles += [f'<hh:style id="{i}" type="PARA" name="개요 {i}" engName="Outline {i}" '
               f'paraPrIDRef="{i}" charPrIDRef="0" nextStyleIDRef="{i}" langID="1042" lockForm="0"/>'
               for i in range(1, 4)]
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<hh:head xmlns:hh="{HH}" version="1.4" secCnt="1">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
            '<hh:refList>'
            '<hh:fontfaces itemCnt="1"><hh:fontface lang="HANGUL" fontCnt="1">'
            '<hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface></hh:fontfaces>'
            '<hh:borderFills itemCnt="1"><hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" '
            'breakCellSeparateLine="0">'
            '<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
            '</hh:borderFill></hh:borderFills>'
            '<hh:charProperties itemCnt="1"><hh:charPr id="0" height="1000" textColor="#000000" '
            'shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
            '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
            '</hh:charPr></hh:charProperties>'
            f'<hh:paraProperties itemCnt="4">{para_prs}</hh:paraProperties>'
            f'<hh:styles itemCnt="4">{"".join(styles)}</hh:styles>'
            '</hh:refList></hh:head>')


_SEC_PR = ('<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" '
           'outlineShapeIDRef="0" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
           '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">'
           '<hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" '
           'bottom="4252"/></hp:pagePr></hp:secPr>')


def _hwpx_t(text: str) -> str:
    return "<hp:t>" + "<hp:lineBreak/>".join(_xml_escape(x) for x in text.split("\n")) + "</hp:t>"


def _hwpx_section(doc: _Doc) -> str:
    out: list[str] = []
    counter = iter(range(1, 1_000_000))
    first = True
    page_break = False

    def para(inner: str, *, style: int = 0) -> str:
        nonlocal first, page_break
        sec = _SEC_PR if first else ""
        first = False
        pb = "1" if page_break else "0"
        page_break = False
        return (f'<hp:p id="{next(counter)}" paraPrIDRef="{style}" styleIDRef="{style}" '
                f'pageBreak="{pb}" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="0">{sec}{inner}</hp:run></hp:p>')

    for b in doc.blocks:
        if b.kind == "break":
            page_break = True
        elif b.kind == "heading":
            out.append(para(_hwpx_t(b.text), style=b.level))
        elif b.kind == "para":
            out.append(para(_hwpx_t(b.text)))
        elif b.kind == "place":
            fid = next(counter)
            out.append(para(
                f'<hp:ctrl><hp:fieldBegin id="{fid}" type="CLICK_HERE" name="{_xml_escape(b.place_id)}" '
                f'editable="1" dirty="0" zorder="-1" fieldid="{fid}">'
                f'<hp:parameters cnt="1" name="">'
                f'<hp:stringParam name="Direction">{_xml_escape(b.label)}</hp:stringParam>'
                f'</hp:parameters></hp:fieldBegin></hp:ctrl>'
                f'{_hwpx_t(b.text)}'
                f'<hp:ctrl><hp:fieldEnd beginIDRef="{fid}" fieldid="{fid}"/></hp:ctrl>'))
        elif b.kind == "table":
            cols = len(b.rows[0])
            width = 42520 // max(cols, 1)
            trs = []
            for r, row in enumerate(b.rows):
                tcs = "".join(
                    f'<hp:tc name="" header="{1 if r == 0 else 0}" hasMargin="0" protect="0" '
                    f'editable="0" dirty="0" borderFillIDRef="1">'
                    f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER">'
                    f'<hp:p id="{next(counter)}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
                    f'columnBreak="0" merged="0"><hp:run charPrIDRef="0">{_hwpx_t(cell)}</hp:run></hp:p>'
                    f'</hp:subList><hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
                    f'<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="{width}" height="1800"/>'
                    f'<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>'
                    for c, cell in enumerate(row))
                trs.append(f"<hp:tr>{tcs}</hp:tr>")
            tid = next(counter)
            out.append(para(
                f'<hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
                f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
                f'rowCnt="{len(b.rows)}" colCnt="{cols}" cellSpacing="0" borderFillIDRef="1" noAdjust="0">'
                f'<hp:sz width="{width * cols}" widthRelTo="ABSOLUTE" height="{1800 * len(b.rows)}" '
                f'heightRelTo="ABSOLUTE" protect="0"/>'
                f'<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
                f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
                f'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
                f'<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
                f'{"".join(trs)}</hp:tbl><hp:t/>'))
    if first:
        out.append(para("<hp:t/>"))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{"".join(out)}</hs:sec>')


def hwpx_bytes(doc_or_text) -> bytes:
    """A small, deterministic HWPX package for a parsed .fdoc (or .fdoc text)."""
    doc = doc_or_text if isinstance(doc_or_text, _Doc) else _Doc(parse(doc_or_text))
    members = [
        ("mimetype", b"application/hwp+zip", zipfile.ZIP_STORED),
        ("version.xml", _HWPX_VERSION.encode("utf-8"), zipfile.ZIP_DEFLATED),
        ("META-INF/container.xml", _HWPX_CONTAINER.encode("utf-8"), zipfile.ZIP_DEFLATED),
        ("Contents/content.hpf", _HWPX_HPF.encode("utf-8"), zipfile.ZIP_DEFLATED),
        ("Contents/header.xml", _hwpx_header().encode("utf-8"), zipfile.ZIP_DEFLATED),
        ("Contents/section0.xml", _hwpx_section(doc).encode("utf-8"), zipfile.ZIP_DEFLATED),
    ]
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data, method in members:
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = method
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


@_public
def convert(src, out, *, to) -> dict:
    src_p = _path(src, "src")
    if to not in CONVERT_TARGETS:
        raise _Refusal("invalid_params", f"to는 {', '.join(CONVERT_TARGETS)} 중 하나입니다")
    if to not in ("md", "hwpx"):
        raise _Refusal("capability_unavailable", f"가짜 rt_doc은 {to}로 바꾸지 못합니다")
    doc, _ = _load(src_p, suffixes=(SUFFIX, ".md"))
    out_p = _out_path(out, src_p)
    if to == "md":
        text, lossy = _markdown(doc)
        _write(out_p, text.encode("utf-8"))
    else:
        lossy = sorted({"styles"} if any(b.style for b in doc.blocks) else set())
        _write(out_p, hwpx_bytes(doc))
    return {"ok": True, "out": str(out_p), "lossy": lossy}


@_public
def new(markdown_path_or_text, out, *, form=None) -> dict:
    if form is not None:
        raise _Refusal("capability_unavailable", "가짜 rt_doc은 양식 위에 만들지 못합니다")
    if not isinstance(markdown_path_or_text, (str, Path)):
        raise _Refusal("invalid_params", "markdown 글이나 .md 경로를 주세요")
    src_path = None
    if isinstance(markdown_path_or_text, Path) or (
            "\n" not in markdown_path_or_text and markdown_path_or_text.lower().endswith(".md")):
        src_path = Path(markdown_path_or_text)
        try:
            text = src_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise _Refusal("not_found", "markdown 파일이 없습니다") from None
        except (OSError, UnicodeDecodeError):
            raise _Refusal("source_rejected", "markdown 파일을 읽지 못했습니다") from None
    else:
        text = markdown_path_or_text
    out_p = _path(out, "out")
    if out_p.suffix.lower() != SUFFIX:
        raise _Refusal("capability_unavailable", f"가짜 rt_doc은 {SUFFIX}만 만듭니다")
    if src_path is not None and _same_file(out_p, src_path):
        raise _Refusal("invalid_params", "원본에 덮어쓸 수 없습니다. 다른 out을 지정하세요")
    blocks = parse(text, markdown=True)
    payload = serialize(blocks).encode("utf-8")
    _write(out_p, payload)
    return {"ok": True, "out": str(out_p), "rev": _rev(payload)}


# --------------------------------------------------------------------------- diff / guard / style
def _two(a, b) -> tuple[_Doc, _Doc]:
    da, _ = _load(a)
    db, _ = _load(b)
    return da, db


@_public
def diff(a, b) -> dict:
    da, db = _two(a, b)
    ua, ub = da.units(), db.units()
    sm = difflib.SequenceMatcher(a=[u[1] for u in ua], b=[u[1] for u in ub], autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for k in range(pairs):
            changes.append({"at": ub[j1 + k][0], "before": ua[i1 + k][1], "after": ub[j1 + k][1]})
        for k in range(i1 + pairs, i2):
            changes.append({"at": ua[k][0], "before": ua[k][1], "after": None})
        for k in range(j1 + pairs, j2):
            changes.append({"at": ub[k][0], "before": None, "after": ub[k][1]})
    return {"ok": True, "changes": changes}


@_public
def guard(a, b) -> dict:
    da, db = _two(a, b)
    ua, ub = da.units(), db.units()
    if len(ua) != len(ub):
        return {"ok": True, "pass": False,
                "changes": [{"at": None, "kind": "paragraph_count", "before": len(ua),
                             "after": len(ub)}]}
    changes = []
    for (_, ta, _), (addr, tb, _) in zip(ua, ub):
        if re.findall(r"\d+", ta) != re.findall(r"\d+", tb):
            changes.append({"at": addr, "kind": "numbers", "before": ta, "after": tb})
    return {"ok": True, "pass": not changes, "changes": changes}


@_public
def style(path) -> dict:
    doc, data = _load(path)
    findings = []
    for addr, text, page in doc.units():
        k = text.find(EDAE_MATCH)
        if k >= 0:
            findings.append({"rule": EDAE_RULE, "severity": "notice", "at": addr, "start": k,
                             "end": k + len(EDAE_MATCH), "match": EDAE_MATCH,
                             "why": "번역 투 표현입니다", "suggest": "'~을/를'로 바꿔 보세요"})
    return {"ok": True, "rev": _rev(data), "findings": findings}


__all__ = ["open", "outline", "read", "find", "edit", "render", "pages", "convert", "new", "diff",
           "guard", "style", "hwpx_bytes", "parse", "serialize", "ERROR_CODES"]
