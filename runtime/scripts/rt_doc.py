#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_core: the one document layer every surface calls (CLI, MCP tools, UI ``/rpc``).

Nothing above this module talks to the HWP engine (``kit_api``) or to ``rt_kit``
directly. Every public function returns ``{"ok": True, ...}`` or
``{"ok": False, "error": {code, message, at?, step?, done?, candidates?,
retryable}}`` and never raises.

ENGINE. When an engine is configured (``RIGORLOOM_HWP_ENGINE`` = a directory
holding ``kit_api.py``, or an importable ``hwp_engine`` package whose folder
holds it) this module starts ONE long-lived worker per process
(``kit_api.py serve`` over pipes, through the engine's own ``kit_client``; the
worker keeps its document cache on) the first time a function needs it, and
closes it at exit. Pipes, not a Unix socket, so it works on Windows. A
function the engine does not have yet (``geometry``, ``hit_test``,
``caret_rect``, ``convert``, ``png``) answers ``capability_unavailable`` with
reason ``engine_function_missing``, so it lights up as soon as the engine adds
it. Without an engine, ``.hwpx`` open/outline/read/find and the text edits
(set, replace, table.set_cells, fill, clearing a cell) run on the built-in XML
path below; everything else is ``capability_unavailable``.

NUMBERING (one rule for both paths, the same as the engine's ``hnc_edit.Doc``
and ``pages()``). A section's paragraphs are its ``<hp:p>`` elements in the
order their start tags appear, nested ones (cells, text boxes, captions, notes)
included; that is ``hnc_edit.Doc.paragraphs(si)`` and its ``k``. A paragraph is
*top-level* when no other ``<hp:p>`` encloses it. ``pN`` is the N-th top-level
paragraph counting through all sections in order (0-based); this is the
``para`` index of the engine's ``pages()`` flow and form_model's ``k``. Tables
(``tN``) are ``<hp:tbl>`` elements in start-tag order, section after section,
nested tables included (= ``hnc_edit``'s per-section table list, concatenated).
A cell is addressed by its ``<hp:cellAddr>`` row/col; an address that lands
inside a merged cell answers at the cell that covers it. ``tN/rR/cC/pK`` is the
K-th paragraph directly in that cell (``hnc_edit.Doc.cell_paragraphs``).
Positions inside a paragraph count characters, tabs and line breaks one each
and every inline object (table, picture, equation) as one position too, the
way ``hnc_edit`` moves the caret; text returned to callers leaves objects out
and offsets in results are offsets into that text.

ADDRESSES. ``p12``, ``t3``, ``t3/r2`` (a row, for table ops), ``t3/r2/c1``,
``t3/r2/c1/p0``, ``h:"제목"`` (exact heading text, then a unique prefix;
quotes optional), ``place:<id>`` (a fill seat from ``outline()``), ``page:4``
(1-based, pages/render/geometry only). An address that does not resolve is
``bad_address`` with ``candidates``.

EDITS. ``edit(path, ops, base=rev)`` refuses with ``stale`` when the file's
rev (first 12 hex of the sha256 of its bytes) is not ``base``; checks every op
(addresses, ``expect``) before touching anything; turns all ops into ONE engine
edit script (applied from the end of the document backwards, so every address
means what it meant in ``base``); writes a new file (``<stem>.edited.hwpx``
next to the input unless ``out`` is given; the input only with
``in_place=True``) through a temp file and an atomic replace.
"""
from __future__ import annotations

import atexit
import builtins
import bisect
import difflib
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

try:  # installed as rigorloom_runtime.rt_doc
    from . import rt_codes as _codes  # type: ignore
except ImportError:  # run from a checkout with runtime/scripts on sys.path
    import rt_codes as _codes  # type: ignore

ENGINE_ENV = "RIGORLOOM_HWP_ENGINE"
TIMEOUT_ENV = "RIGORLOOM_DOC_ENGINE_TIMEOUT"
DEFAULT_TIMEOUT_S = 180.0
SCHEMA = "rigorloom/doc-core/v1"

OPS = ("set", "replace", "insert_after", "delete", "table.set_cells", "table.add_row",
       "table.delete_row", "fill", "style", "insert_table", "insert_picture", "insert_equation")
#: ops the built-in XML path can do without the engine
FALLBACK_OPS = ("set", "replace", "table.set_cells", "fill", "delete")

_bopen = builtins.open
_RETRYABLE = {"stale": False, "engine_timeout": True, "engine_unavailable": True, "internal": False}


# ============================================================================ errors
class DocError(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    def to_error(self):
        err = {"code": self.code, "message": self.message}
        err.update({k: v for k, v in self.extra.items() if v is not None})
        err.setdefault("retryable", _RETRYABLE.get(self.code, False))
        return err


def _fail(err):
    return {"ok": False, "error": err}


def _unavailable(message, reason, **extra):
    return DocError("capability_unavailable", message, reason=reason, retryable=False, **extra)


def _api(fn):
    """Public functions answer envelopes and never raise."""
    def wrapper(*args, **kwargs):
        try:
            res = fn(*args, **kwargs)
        except DocError as exc:
            return _fail(exc.to_error())
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return _fail({"code": "internal", "message": "%s: %s" % (type(exc).__name__, exc),
                          "retryable": False})
        out = {"ok": True}
        out.update(res)
        return out
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


# ============================================================================ rev / files
def rev_of(path) -> str:
    """First 12 hex of the sha256 of the file's bytes."""
    h = hashlib.sha256()
    with _bopen(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _need_file(path):
    p = Path(path)
    if not p.is_file():
        raise DocError("not_found", "no such file: %s" % path)
    return p.resolve()


def _format_of(path) -> str:
    with _bopen(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"PK"):
        return "hwpx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    suf = Path(path).suffix.lower().lstrip(".")
    if suf in ("md", "markdown", "txt"):
        return "md"
    raise DocError("bad_input", "not a .hwpx or .hwp document: %s" % Path(path).name)


def _atomic_copy(src, dst):
    dst = Path(dst)
    fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=dst.suffix, dir=str(dst.parent))
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


_SCRATCH = None
_SCRATCH_LOCK = threading.Lock()


def _scratch() -> Path:
    global _SCRATCH
    with _SCRATCH_LOCK:
        if _SCRATCH is None or not Path(_SCRATCH).is_dir():
            _SCRATCH = tempfile.mkdtemp(prefix="rigorloom-doc-")
            atexit.register(shutil.rmtree, _SCRATCH, True)
        return Path(_SCRATCH)


# ============================================================================ engine
def _engine_dir(env=None):
    env = os.environ if env is None else env
    raw = (env.get(ENGINE_ENV) or "").strip()
    if raw:
        d = Path(raw).expanduser()
        return (d, None) if (d / "kit_api.py").is_file() else (None, "engine_path_missing")
    try:
        spec = importlib.util.find_spec("hwp_engine")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        for loc in list(spec.submodule_search_locations or []) + (
                [str(Path(spec.origin).parent)] if spec.origin else []):
            if (Path(loc) / "kit_api.py").is_file():
                return Path(loc), None
        return None, "engine_package_without_kit_api"
    return None, "engine_not_configured"


class _Engine:
    """One lazily started ``kit_api.py serve`` worker on pipes, shared by the process."""

    def __init__(self, kit_dir: Path):
        self.dir = Path(kit_dir)
        self.client = None
        self.lock = threading.Lock()
        self.kc = None
        self.timeout = float(os.environ.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT_S)

    def _module(self):
        if self.kc is None:
            spec = importlib.util.spec_from_file_location("_rigorloom_kit_client", str(self.dir / "kit_client.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.kc = mod
        return self.kc

    def _client(self):
        with self.lock:
            c = self.client
            if c is not None and c.proc is not None and c.proc.poll() is not None:
                self.client = c = None          # the worker died: start a new one
            if c is None:
                kc = self._module()
                c = self.client = kc.KitClient(kit_dir=str(self.dir), timeout=self.timeout)
            return c

    def call(self, fn, *args, **kwargs):
        """The engine's envelope, or an envelope saying why there is none. Never raises."""
        try:
            c = self._client()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": {"code": "engine_unavailable",
                                           "message": "the engine worker did not start: %s" % exc}}
        try:
            return c.call(fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - KitError: timeout or closed pipe
            self.reset(kill=True)
            code = "engine_timeout" if "no answer" in str(exc) else "engine_unavailable"
            return {"ok": False, "error": {"code": code, "message": str(exc)}}

    def reset(self, kill=False):
        with self.lock:
            c, self.client = self.client, None
        if c is not None:
            if kill and c.proc is not None:
                try:
                    c.proc.kill()
                except OSError:
                    pass
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


_ENGINE = None
_ENGINE_KEY = None
_ENGINE_LOCK = threading.Lock()


def _engine():
    """The process's engine, or None when none is configured."""
    global _ENGINE, _ENGINE_KEY
    d, _why = _engine_dir()
    key = str(d) if d else None
    with _ENGINE_LOCK:
        if key != _ENGINE_KEY:
            if _ENGINE is not None:
                _ENGINE.reset()
            _ENGINE = _Engine(d) if d else None
            _ENGINE_KEY = key
        return _ENGINE


def close():
    """Stop the engine worker (it also stops at interpreter exit)."""
    global _ENGINE, _ENGINE_KEY
    with _ENGINE_LOCK:
        e, _ENGINE, _ENGINE_KEY = _ENGINE, None, None
    if e is not None:
        e.reset()


atexit.register(close)


def engine_status() -> dict:
    d, why = _engine_dir()
    if d is None:
        return {"available": False, "reason": why}
    return {"available": True, "dir": str(d)}


def _engine_error(env, fn=None, at=None, i=None):
    """An engine failure envelope -> DocError keeping code, message, step and done."""
    err = env.get("error") if isinstance(env.get("error"), dict) else {}
    code = str(err.get("code") or "internal")
    msg = str(err.get("message") or "the engine refused %s" % fn)
    if code == "unsupported" and msg.startswith("no such function"):
        return _unavailable("the installed engine has no %s yet" % fn, "engine_function_missing", fn=fn)
    extra = {k: v for k, v in err.items() if k not in ("code", "message")}
    retry = code in ("engine_timeout", "engine_unavailable")
    return DocError(code, msg, at=at, i=i, retryable=retry, engine_fn=fn, **extra)


def _need_engine(what):
    e = _engine()
    if e is None:
        _d, why = _engine_dir()
        raise _unavailable("%s needs the HWP engine, which is not installed (set %s)" % (what, ENGINE_ENV),
                           why or "engine_not_configured")
    return e


def _ecall(fn, *args, **kwargs):
    e = _need_engine(fn)
    r = e.call(fn, *args, **kwargs)
    if not r.get("ok"):
        raise _engine_error(r, fn)
    return r


# ============================================================================ HWPX reading
TAG = re.compile(r'<(/?)([A-Za-z][\w:.-]*)((?:[^>"]|"[^"]*")*?)(/?)>')     # = hnc_edit.TAG
INLINE_W = {"hp:tab": "\t", "hp:lineBreak": "\n", "hp:fwSpace": "\u3000", "hp:nbSpace": " ", "hp:hyphen": " "}
ZERO_CTRL = ("hp:colPr", "hp:fieldBegin", "hp:fieldEnd", "hp:bookmark", "hp:pageNum", "hp:pageHiding",
             "hp:newNum", "hp:indexmark", "hp:header", "hp:footer", "hp:autoNum")
_ZERO_CTRL_RE = re.compile(r"\s*<(%s)\b" % "|".join(re.escape(n) for n in ZERO_CTRL))
OBJ = "\ufffc"
TAB_XML = '<hp:tab width="0" leader="0" type="0"/>'
SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")


def _attr(tag, name):
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
    return m.group(1) if m else None


class Para:
    __slots__ = ("si", "k", "start", "end", "parent", "cell", "top", "gp", "chars", "posmap", "tnodes",
                 "runs", "objs", "head", "lineseg", "caption_of", "in_box")

    def __init__(self, si, k, start, head):
        self.si, self.k, self.start, self.end, self.head = si, k, start, None, head
        self.parent = None      # enclosing Para
        self.cell = None        # Cell when directly in a cell
        self.top = False
        self.gp = None
        self.chars = []         # ptext: characters, tabs, breaks, OBJ for objects
        self.posmap = []        # per ptext position: (tnode index, piece index) or None for an object
        self.tnodes = []        # own <hp:t>: {"a","b","open","self","pieces":[[kind, ch, xml]], "run"}
        self.runs = []          # own <hp:run>: {"a","open_end","b","self","cp","text"}
        self.objs = []          # own object tags (hp:tbl, hp:pic ...)
        self.lineseg = None     # (a, b) of own <hp:linesegarray>
        self.caption_of = None
        self.in_box = False

    @property
    def ptext(self):
        return "".join(self.chars)

    @property
    def text(self):
        return "".join(c for c in self.chars if c != OBJ)

    @property
    def pr(self):
        return _attr(self.head, "paraPrIDRef")

    @property
    def style(self):
        return _attr(self.head, "styleIDRef")


class Cell:
    __slots__ = ("row", "col", "rs", "cs", "paras", "start", "end")

    def __init__(self, start):
        self.row = self.col = None
        self.rs = self.cs = 1
        self.paras = []
        self.start, self.end = start, None


class Table:
    __slots__ = ("si", "lt", "g", "start", "end", "host", "cells", "caption", "rows", "cols", "id")

    def __init__(self, si, lt, start, host, tid):
        self.si, self.lt, self.g, self.start, self.end, self.host = si, lt, None, start, None, host
        self.cells, self.caption, self.rows, self.cols, self.id = [], [], 0, 0, tid

    def at(self, r, c):
        for x in self.cells:
            if x.row == r and x.col == c:
                return x
        for x in self.cells:
            if x.row <= r < x.row + x.rs and x.col <= c < x.col + x.cs:
                return x
        return None

    def row_cells(self, r):
        return sorted((x for x in self.cells if x.row == r), key=lambda x: x.col)


def _scan_section(s, si):
    """Paragraphs and tables of one section XML (see the module docstring for the numbering)."""
    paras, tables = [], []
    stack = []              # [name, obj, extra]
    last = 0

    def innermost(*names):
        for fr in reversed(stack):
            if fr[0] in names:
                return fr
        return None

    for m in TAG.finditer(s):
        close, name, selfc = m.group(1), m.group(2), m.group(4)
        top = stack[-1] if stack else None
        if top is not None and top[0] == "hp:t" and top[2] is not None:
            text = s[last:m.start()]
            if text:
                p, tn = top[2]
                for ch in html.unescape(text):
                    tn["pieces"].append(["c", ch, None])
                    p.chars.append(ch)
                    p.posmap.append((len(p.tnodes) - 1, len(tn["pieces"]) - 1))
        last = m.end()
        if close:
            while stack and stack[-1][0] != name:
                stack.pop()
            if not stack:
                continue
            fr = stack.pop()
            if name == "hp:p":
                fr[1].end = m.end()
            elif name == "hp:tbl":
                fr[1].end = m.end()
            elif name == "hp:tc":
                fr[1].end = m.end()
            elif name == "hp:t" and fr[2] is not None:
                fr[2][1]["b"] = m.end()
                fr[2][1]["close"] = m.start()
            elif name == "hp:run" and fr[2] is not None:
                fr[2]["b"] = m.end()
            continue
        tag = m.group(0)
        # text-level items inside an own <hp:t>
        if top is not None and top[0] == "hp:t" and top[2] is not None:
            p, tn = top[2]
            if name in INLINE_W:
                tn["pieces"].append(["x", INLINE_W[name], tag if selfc else None])
                p.chars.append(INLINE_W[name])
                p.posmap.append((len(p.tnodes) - 1, len(tn["pieces"]) - 1))
            else:
                tn["pieces"].append(["z", "", tag])
            if not selfc:
                stack.append([name, None, None])
            continue
        # direct children of an own run
        if top is not None and top[0] == "hp:run" and top[2] is not None:
            p = top[1]
            if name == "hp:t":
                tn = {"a": m.start(), "open": tag, "self": bool(selfc), "pieces": [], "run": top[2],
                      "b": m.end() if selfc else None, "close": None}
                p.tnodes.append(tn)
                if not selfc:
                    stack.append([name, None, (p, tn)])
                continue
            zero = name == "hp:secPr" or (name == "hp:ctrl" and not selfc and _ZERO_CTRL_RE.match(s, m.end()))
            if not zero:
                p.chars.append(OBJ)
                p.posmap.append(None)
                p.objs.append(name)
            # fall through: the element itself is scanned for nested structure
        if name == "hp:p":
            if selfc:
                continue
            p = Para(si, len(paras), m.start(), tag)
            fr_p = innermost("hp:p")
            fr_c = innermost("hp:p", "hp:tc", "hp:caption", "hp:drawText")
            p.parent = fr_p[1] if fr_p else None
            p.top = fr_p is None
            if fr_c is not None and fr_c[0] == "hp:tc" and fr_c[1] is not None:
                fr_c[1].paras.append(p)
                p.cell = fr_c[1]
            elif fr_c is not None and fr_c[0] == "hp:caption" and fr_c[1] is not None:
                fr_c[1].caption.append(p)
                p.caption_of = fr_c[1]
            elif fr_c is not None and fr_c[0] == "hp:drawText":
                p.in_box = True
            paras.append(p)
            stack.append([name, p, None])
        elif name == "hp:run":
            fr_p = innermost("hp:p")
            if fr_p is not None and stack[-1] is fr_p:
                run = {"a": m.start(), "open_end": m.end(), "self": bool(selfc), "cp": _attr(tag, "charPrIDRef"),
                       "b": m.end() if selfc else None}
                fr_p[1].runs.append(run)
                if not selfc:
                    stack.append([name, fr_p[1], run])
            elif not selfc:
                stack.append([name, None, None])
        elif name == "hp:tbl":
            if selfc:
                continue
            fr_p = innermost("hp:p")
            t = Table(si, len(tables), m.start(), fr_p[1] if fr_p else None, _attr(tag, "id"))
            t.rows = int(_attr(tag, "rowCnt") or 0)
            t.cols = int(_attr(tag, "colCnt") or 0)
            tables.append(t)
            stack.append([name, t, None])
        elif name == "hp:tc":
            if selfc:
                continue
            fr_t = innermost("hp:tbl")
            c = Cell(m.start())
            if fr_t is not None:
                fr_t[1].cells.append(c)
            stack.append([name, c, None])
        elif name in ("hp:cellAddr", "hp:cellSpan"):
            fr_c = innermost("hp:tc")
            if fr_c is not None:
                if name == "hp:cellAddr":
                    fr_c[1].row, fr_c[1].col = int(_attr(tag, "rowAddr") or 0), int(_attr(tag, "colAddr") or 0)
                else:
                    fr_c[1].rs, fr_c[1].cs = int(_attr(tag, "rowSpan") or 1), int(_attr(tag, "colSpan") or 1)
            if not selfc:
                stack.append([name, None, None])
        elif name == "hp:caption":
            if selfc:
                continue
            fr_t = innermost("hp:tbl", "hp:pic", "hp:p")
            stack.append([name, fr_t[1] if fr_t is not None and fr_t[0] == "hp:tbl" else None, None])
        elif not selfc:
            stack.append([name, None, None])
    return paras, tables


_LINESEG_RE = re.compile(r"<hp:linesegarray\b[^>]*?(?:/>|>.*?</hp:linesegarray>)", re.S)


class Doc:
    """A parsed .hwpx (or the engine's .hwpx of a .hwp): sections, paragraphs, tables, headings."""

    def __init__(self, path, rev, fmt, hwpx_path):
        self.path, self.rev, self.format, self.hwpx = Path(path), rev, fmt, Path(hwpx_path)
        self.infos, self.contents = _read_zip(self.hwpx)
        self.section_names = sorted((n for n in self.contents if SECTION_RE.match(n)),
                                    key=lambda n: int(SECTION_RE.match(n).group(1)))
        self.secs = [self.contents[n].decode("utf-8") for n in self.section_names]
        self.header = self.contents.get("Contents/header.xml", b"").decode("utf-8", "replace")
        self.paras, self.tables, self.sec_paras, self.sec_tables = [], [], [], []
        for si, s in enumerate(self.secs):
            ps, ts = _scan_section(s, si)
            for p in ps:
                p.lineseg = _own_lineseg(s, p)
            self.sec_paras.append(ps)
            self.sec_tables.append(ts)
            self.paras.extend(ps)
            self.tables.extend(ts)
        self.top = [p for p in self.paras if p.top]
        for i, p in enumerate(self.top):
            p.gp = i
        for g, t in enumerate(self.tables):
            t.g = g
            if not t.rows and t.cells:
                t.rows = max(c.row + c.rs for c in t.cells)
            if not t.cols and t.cells:
                t.cols = max(c.col + c.cs for c in t.cells)
        self.styles = _header_styles(self.header)
        self.para_heading = _header_para_headings(self.header)
        self.bold_cp = _header_bold_charprs(self.header)
        self.engine_headings = None
        self.engine_places = None
        self.page_starts = None     # [flow para index of page n's first paragraph]

    # -- helpers
    def top_of(self, p):
        while p.parent is not None:
            p = p.parent
        return p

    def table_paras(self, t):
        s = self.sec_paras[t.si]
        return [p for p in s if t.start < p.start < t.end]

    def tables_in(self, p):
        return [t for t in self.sec_tables[p.si] if p.start < t.start < p.end]

    def page_of(self, p):
        if not self.page_starts:
            return None
        gp = self.top_of(p).gp
        return bisect.bisect_right(self.page_starts, gp)

    def style_name(self, sid):
        st = self.styles.get(sid or "")
        return st["name"] if st else None

    def heading_level(self, p):
        """(level, kind) of a structural heading or None: an 개요 (outline) paraPr, or a heading/title style."""
        h = self.para_heading.get(p.pr or "")
        if h and h[0] == "OUTLINE":
            return h[1] + 1, "outline"
        name = self.style_name(p.style) or ""
        m = re.match(r"^\s*(?:개요|제목|heading|title)\s*(\d*)", name, re.I)
        if m and name not in ("개요 번호",):
            return (int(m.group(1)) if m.group(1) else 1), "style"
        return None


def _own_lineseg(s, p):
    """(a, b) of the paragraph's own linesegarray (a direct child after its runs), else None."""
    if p.end is None:
        return None
    # the linesegarray of p sits after its last own run and before </hp:p>
    tail_from = p.runs[-1]["b"] if p.runs and p.runs[-1]["b"] else p.start
    close = p.end - len("</hp:p>")
    m = _LINESEG_RE.search(s, tail_from, close)
    if m and m.end() <= close:
        # make sure no nested paragraph sits between (then it is not ours)
        if "<hp:p " not in s[tail_from:m.start()]:
            return (m.start(), m.end())
    return None


def _header_styles(h):
    out = {}
    for m in re.finditer(r"<hh:style\b[^>]*>", h):
        t = m.group(0)
        out[_attr(t, "id")] = {"name": _attr(t, "name"), "engName": _attr(t, "engName"),
                               "type": _attr(t, "type"), "paraPr": _attr(t, "paraPrIDRef"),
                               "charPr": _attr(t, "charPrIDRef")}
    return out


def _header_para_headings(h):
    out = {}
    for m in re.finditer(r'<hh:paraPr\b[^>]*\bid="(\d+)"[^>]*>(.*?)</hh:paraPr>', h, re.S):
        hm = re.search(r'<hh:heading\b[^>]*type="(\w+)"[^>]*level="(\d+)"', m.group(2))
        if hm:
            out[m.group(1)] = (hm.group(1), int(hm.group(2)))
    return out


def _header_bold_charprs(h):
    return {m.group(1) for m in re.finditer(r'<hh:charPr\b[^>]*\bid="(\d+)"[^>]*>(.*?)</hh:charPr>', h, re.S)
            if "<hh:bold" in m.group(2)}


def _read_zip(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > _codes.MAX_ZIP_MEMBERS:
            raise DocError("bad_input", "too many zip members in %s" % Path(path).name)
        total = sum(i.file_size for i in infos)
        if total > _codes.MAX_ZIP_TOTAL_UNCOMPRESSED:
            raise DocError("bad_input", "the document is too large when unpacked")
        return infos, {i.filename: z.read(i.filename) for i in infos}


def _write_zip(out, infos, contents):
    out = Path(out)
    fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".hwpx", dir=str(out.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for info in infos:
                z.writestr(info, contents[info.filename])
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


_DOCS = {}
_DOCS_LOCK = threading.Lock()
_DOCS_MAX = 8


def _load(path, *, layout=False, places=False):
    """The Doc of a file (cached by path and rev). .hwp is read through the engine's .hwpx of it."""
    p = _need_file(path)
    rev = rev_of(p)
    fmt = _format_of(p)
    if fmt == "md":
        raise DocError("bad_input", "a markdown file is not a document here; use new() or convert()")
    key = (str(p), rev)
    with _DOCS_LOCK:
        d = _DOCS.get(key)
    if d is None:
        hwpx = p
        if fmt == "hwp":
            e = _engine()
            if e is None:
                raise _unavailable(".hwp files need the HWP engine; only .hwpx is supported without it",
                                   "hwp_binary_unsupported")
            conv = _scratch() / ("%s.hwpx" % rev)
            if not conv.is_file():
                r = e.call("to_hwpx", str(p), str(conv))
                if not r.get("ok"):
                    raise _engine_error(r, "to_hwpx")
            hwpx = conv
        try:
            d = Doc(p, rev, fmt, hwpx)
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
            raise DocError("bad_input", "not a readable .hwpx: %s" % exc)
        with _DOCS_LOCK:
            _DOCS[key] = d
            while len(_DOCS) > _DOCS_MAX:
                _DOCS.pop(next(iter(_DOCS)))
    e = _engine()
    if layout and e is not None and d.page_starts is None:
        r = e.call("pages", str(p))
        if r.get("ok"):
            d.page_starts = [s["para"] for s in r.get("page_starts", []) if s.get("para", -1) >= 0] or [0]
            d.layout = r
    if places and d.engine_places is None and e is not None:
        r = e.call("analyze", str(p))
        if r.get("ok"):
            d.engine_places = r.get("places") or []
            d.engine_headings = r.get("headings") or []
        else:
            d.engine_places, d.engine_headings = [], []
    return d


# ============================================================================ addresses
_ADDR = re.compile(r"^(?:p(?P<p>\d+)(?P<rng>:\d+-\d+)?"
                   r"|t(?P<t>\d+)(?:/r(?P<r>\d+)(?:/c(?P<c>\d+)(?:/p(?P<cp>\d+)(?P<crng>:\d+-\d+)?)?)?)?"
                   r"|h:(?P<h>.+)|place:(?P<place>.+)|page:(?P<page>\d+))$", re.S)


def parse_address(addr):
    """The parsed form of an address: {"kind": para|table|row|cell|cellpara|heading|place|page, ...}."""
    if not isinstance(addr, str) or not addr.strip():
        raise DocError("bad_address", "an address is a string such as p12, t3/r2/c1, h:\"제목\", place:<id>, page:4",
                       at=addr if isinstance(addr, str) else None)
    a = addr.strip()
    m = _ADDR.match(a)
    if not m:
        raise DocError("bad_address", "not an address: %r (p12, t3, t3/r2/c1, t3/r2/c1/p0, h:\"...\", "
                       "place:<id>, page:4)" % a, at=a)
    g = m.groupdict()
    rng = g.get("rng") or g.get("crng")
    if rng:
        x, y = (int(v) for v in rng[1:].split("-"))
        if y < x:
            raise DocError("bad_address", "a character range is start-end with end >= start", at=a)
        rng = (x, y)
    if g["p"] is not None:
        return {"kind": "para", "p": int(g["p"]), **({"range": rng} if rng else {})}
    if g["t"] is not None:
        t = int(g["t"])
        if g["r"] is None:
            return {"kind": "table", "t": t}
        if g["c"] is None:
            return {"kind": "row", "t": t, "r": int(g["r"])}
        if g["cp"] is None:
            return {"kind": "cell", "t": t, "r": int(g["r"]), "c": int(g["c"])}
        return {"kind": "cellpara", "t": t, "r": int(g["r"]), "c": int(g["c"]), "k": int(g["cp"]),
                **({"range": rng} if rng else {})}
    if g["h"] is not None:
        h = g["h"].strip()
        if len(h) >= 2 and h[0] == h[-1] and h[0] in "\"'":
            h = h[1:-1]
        return {"kind": "heading", "text": h}
    if g["place"] is not None:
        return {"kind": "place", "id": g["place"].strip().strip("\"'")}
    return {"kind": "page", "page": int(g["page"])}


def para_address(doc, p):
    """The address of a paragraph."""
    if p.top:
        return "p%d" % p.gp
    if p.cell is not None:
        t = next(t for t in doc.sec_tables[p.si] if p.cell in t.cells)
        return "t%d/r%d/c%d/p%d" % (t.g, p.cell.row, p.cell.col, p.cell.paras.index(p))
    return None


def _headings(doc):
    """[{at, level, text, kind, para}] in document order."""
    out, seen = [], set()
    if doc.engine_headings:
        for h in doc.engine_headings:
            k = h.get("k")
            if isinstance(k, int) and 0 <= k < len(doc.top):
                p = doc.top[k]
                out.append({"at": "p%d" % k, "level": int(h.get("level") or 0) + 1,
                            "text": p.text.strip(), "para": p})
                seen.add(k)
    for p in doc.top:
        if p.gp in seen:
            continue
        t = p.text.strip()
        if not t or len(t) > 60:
            continue
        lv = doc.heading_level(p)
        if lv is None and doc.engine_headings is None:
            # no engine: a short line whose every run is bold reads as a heading
            cps = [r["cp"] for r in p.runs if r.get("cp") is not None and not r["self"]]
            if cps and len(t) <= 40 and not p.objs and all(c in doc.bold_cp for c in cps) \
                    and not re.match(r"^[→※*\-•ㆍ·○◦]", t):
                lv = (_numbered_level(t), "bold")
        if lv is not None:
            out.append({"at": "p%d" % p.gp, "level": lv[0], "text": t, "para": p})
            seen.add(p.gp)
    out.sort(key=lambda h: h["para"].gp)
    return out


def _numbered_level(t):
    """Outline level a heading's own numbering suggests: Ⅰ. 1, 1. 2, 1.1 / 가. 3, otherwise 2."""
    if re.match(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+)\.", t):
        return 1
    if re.match(r"^\s*\d+\.\d+", t) or re.match(r"^\s*[가-하]\.", t):
        return 3
    return 2


def _norm_key(s):
    s = re.sub(r"^[\sⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d.)(]+(?=\S)", "", s.strip()) if not re.match(r"^\(\d+\)", s.strip()) else s
    s = re.sub(r"^\(\d+\)\s*", "", s.strip())
    return re.sub(r"[\s:：<>〈〉]+", "", s)


def _places(doc):
    """Fill seats: [{id, at, label, kind, para?, cell?, table?, typed_at?}].

    With the engine: its analyze() places. Without: an empty cell labelled by the cell to its left or above,
    and the blank paragraphs right under a heading."""
    out = []
    if doc.engine_places is not None:
        for pl in doc.engine_places:
            si = doc.section_names.index(pl["section"]) if pl.get("section") in doc.section_names else 0
            rec = {"id": pl.get("id"), "label": pl.get("label"), "kind": pl.get("kind")}
            if pl.get("kind") in ("cell", "cell_field") and isinstance(pl.get("table"), int):
                ts = doc.sec_tables[si]
                if pl["table"] >= len(ts):
                    continue
                t = ts[pl["table"]]
                c = t.at(pl["row"], pl["col"])
                if c is None:
                    continue
                rec.update(table=t, cell=c)
                idx = pl.get("index")
                p = doc.sec_paras[si][idx] if isinstance(idx, int) and idx < len(doc.sec_paras[si]) else c.paras[0]
                rec["para"] = p
                rec["at"] = ("t%d/r%d/c%d" % (t.g, c.row, c.col)) if pl["kind"] == "cell" else para_address(doc, p)
            else:
                idx = pl.get("index")
                if not isinstance(idx, int) or idx >= len(doc.sec_paras[si]):
                    continue
                p = doc.sec_paras[si][idx]
                rec["para"] = p
                rec["at"] = para_address(doc, p)
            out.append(rec)
        return out
    seen = set()
    for t in doc.tables:
        texts = {(c.row, c.col): "\n".join(p.text for p in c.paras).strip() for c in t.cells}
        for c in t.cells:
            if texts[(c.row, c.col)] or any(p.objs for p in c.paras) or not c.paras:
                continue
            label = None
            for rr, cc in ((c.row, c.col - 1), (c.row - 1, c.col)):
                lab = t.at(rr, cc) if rr >= 0 and cc >= 0 else None
                if lab is not None and lab is not c and texts.get((lab.row, lab.col)):
                    label = texts[(lab.row, lab.col)]
                    break
            if not label or len(label) > 40:
                continue
            pid = _norm_key(label)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            out.append({"id": pid, "at": "t%d/r%d/c%d" % (t.g, c.row, c.col), "label": label, "kind": "cell",
                        "table": t, "cell": c, "para": c.paras[0]})
    heads = _headings(doc)
    hk = {h["para"].gp for h in heads}
    for h in heads:
        k = h["para"].gp + 1
        if k < len(doc.top) and k not in hk and not doc.top[k].text.strip() and not doc.top[k].objs:
            pid = _norm_key(h["text"])
            if pid and pid not in seen:
                seen.add(pid)
                out.append({"id": pid, "at": "p%d" % k, "label": h["text"], "kind": "body", "para": doc.top[k]})
    return out


def _cands_near(items, want, n=5):
    items = [i for i in items if i]
    close = difflib.get_close_matches(want, items, n=n, cutoff=0.3)
    return close or items[:n]


def _with_range(res, a, addr):
    if "range" in a:
        x, y = a["range"]
        if y > len(res["para"].text):
            raise DocError("bad_address", "%s is %d characters long" % (addr.split(":")[0], len(res["para"].text)),
                           at=addr)
        res["range"] = (x, y)
    return res


def resolve(doc, addr, *, allow=None):
    """An address -> {"kind", "para"|"table"|"cell"|"paras"|"page", ...}. Unresolved: DocError bad_address."""
    a = parse_address(addr) if isinstance(addr, str) else addr
    kind = a["kind"]
    if allow and kind not in allow:
        raise DocError("bad_address", "%s cannot be used here (expected %s)" % (addr, ", ".join(allow)), at=addr)
    if kind == "para":
        if a["p"] >= len(doc.top):
            n = len(doc.top)
            raise DocError("bad_address", "the document has %d top-level paragraphs (p0..p%d)" % (n, n - 1),
                           at=addr, candidates=["p%d" % max(0, n - 1)] + [h["at"] for h in _headings(doc)][:4])
        p = doc.top[a["p"]]
        return _with_range({"kind": "para", "para": p, "paras": [p]}, a, addr)
    if kind in ("table", "row", "cell", "cellpara"):
        if a["t"] >= len(doc.tables):
            raise DocError("bad_address", "the document has %d tables" % len(doc.tables), at=addr,
                           candidates=["t%d" % i for i in range(min(len(doc.tables), 8))])
        t = doc.tables[a["t"]]
        if kind == "table":
            return {"kind": "table", "table": t, "paras": [p for c in t.cells for p in c.paras]}
        if a["r"] >= t.rows:
            raise DocError("bad_address", "table t%d has %d rows" % (t.g, t.rows), at=addr,
                           candidates=["t%d/r%d" % (t.g, r) for r in range(min(t.rows, 8))])
        if kind == "row":
            return {"kind": "row", "table": t, "row": a["r"],
                    "paras": [p for c in t.row_cells(a["r"]) for p in c.paras]}
        c = t.at(a["r"], a["c"])
        if c is None:
            raise DocError("bad_address", "table t%d has no cell at row %d, column %d" % (t.g, a["r"], a["c"]),
                           at=addr, candidates=["t%d/r%d/c%d" % (t.g, x.row, x.col) for x in t.row_cells(a["r"])])
        if kind == "cell":
            return {"kind": "cell", "table": t, "cell": c, "paras": list(c.paras)}
        if a["k"] >= len(c.paras):
            raise DocError("bad_address", "cell t%d/r%d/c%d has %d paragraphs" % (t.g, c.row, c.col, len(c.paras)),
                           at=addr, candidates=["t%d/r%d/c%d/p%d" % (t.g, c.row, c.col, i)
                                                for i in range(len(c.paras))])
        p = c.paras[a["k"]]
        return _with_range({"kind": "para", "para": p, "paras": [p], "table": t, "cell": c}, a, addr)
    if kind == "heading":
        heads = _headings(doc)
        want = a["text"]
        exact = [h for h in heads if h["text"] == want]
        if not exact:
            exact = [h for h in heads if h["text"].startswith(want)]
        if not exact:   # numbering and spaces aside
            nk = _norm_key(want)
            exact = [h for h in heads if nk and _norm_key(h["text"]) == nk]
        if len(exact) != 1:
            why = "no heading matches %r" % want if not exact else "%d headings match %r" % (len(exact), want)
            pool = [h["text"] for h in (exact or heads)]
            raise DocError("bad_address", why, at=addr,
                           candidates=['h:"%s"' % t for t in (_cands_near(pool, want) if not exact else pool[:5])])
        h = exact[0]
        return {"kind": "para", "para": h["para"], "paras": [h["para"]], "heading": h}
    if kind == "place":
        pls = _places(doc)
        for pl in pls:
            if pl["id"] == a["id"]:
                out = {"kind": "place", "place": pl, "para": pl.get("para"), "paras": [pl.get("para")]}
                if pl.get("cell") is not None:
                    out.update(cell=pl["cell"], table=pl["table"], paras=list(pl["cell"].paras))
                return out
        raise DocError("bad_address", "no fill place %r" % a["id"], at=addr,
                       candidates=["place:%s" % i for i in _cands_near([pl["id"] for pl in pls], a["id"])])
    return {"kind": "page", "page": a["page"], "paras": []}


# ============================================================================ read side
def _engine_info():
    d, why = _engine_dir()
    return {"available": d is not None, **({"reason": why} if d is None else {})}


def _fonts(doc, approx=None):
    used = []
    for m in re.finditer(r'<hh:font\b[^>]*\bface="([^"]*)"', doc.header):
        if m.group(1) not in used:
            used.append(m.group(1))
    sub = []
    for a in approx or []:
        if "→" in a:
            w, g = a.split("→", 1)
            sub.append({"want": w.strip(), "got": g.strip()})
        elif a in used:
            sub.append({"want": a, "got": None})
    return {"used": used, "substituted": sub}


@_api
def open(path):  # noqa: A001 - the doc_core verb
    """{rev, format, pages?, sections, fonts: {used, substituted}, engine}"""
    doc = _load(path, layout=True)
    out = {"rev": doc.rev, "format": doc.format, "sections": len(doc.secs), "paragraphs": len(doc.top),
           "tables": len(doc.tables), "engine": _engine_info()}
    lay = getattr(doc, "layout", None)
    if lay:
        out["pages"] = lay.get("pages")
    out["fonts"] = _fonts(doc, lay.get("approx") if lay else None)
    return out


@_api
def outline(path):
    """{rev, headings: [{at, level, text, page?}], tables: [{at, rows, cols, caption?, page?}],
    places: [{id, at, label, kind, page?, rect?}]}"""
    doc = _load(path, layout=True, places=True)
    heads = [{"at": h["at"], "level": h["level"], "text": h["text"],
              **({"page": doc.page_of(h["para"])} if doc.page_starts else {})} for h in _headings(doc)]
    tables = []
    for t in doc.tables:
        rec = {"at": "t%d" % t.g, "rows": t.rows, "cols": t.cols}
        cap = " ".join(p.text for p in t.caption).strip()
        if cap:
            rec["caption"] = cap
        if t.host is not None:
            rec["in"] = para_address(doc, t.host)
            if doc.page_starts:
                rec["page"] = doc.page_of(t.host)
        tables.append(rec)
    places = []
    for pl in _places(doc):
        rec = {"id": pl["id"], "at": pl["at"], "label": pl.get("label"), "kind": pl.get("kind")}
        if doc.page_starts and pl.get("para") is not None:
            rec["page"] = doc.page_of(pl["para"])
        places.append(rec)
    return {"rev": doc.rev, "headings": heads, "tables": tables, "places": places}


def _runs_of(doc, p):
    out = []
    for r in p.runs:
        text = "".join(pc[1] for tn in p.tnodes if tn["run"] is r for pc in tn["pieces"] if pc[0] in ("c", "x"))
        rec = {"text": text, "charPr": r["cp"]}
        if r["cp"] in doc.bold_cp:
            rec["bold"] = True
        out.append(rec)
    return out


def _para_block(doc, p, with_runs):
    b = {"at": para_address(doc, p), "kind": "para", "text": p.text}
    lv = doc.heading_level(p)
    if lv:
        b["kind"], b["level"] = "heading", lv[0]
    sn = doc.style_name(p.style)
    if sn:
        b["style"] = sn
    if p.objs:
        b["objects"] = list(p.objs)
    if with_runs:
        b["runs"] = _runs_of(doc, p)
    if doc.page_starts:
        b["page"] = doc.page_of(p)
    return b


def _table_block(doc, t):
    grid = [["" for _ in range(t.cols)] for _ in range(t.rows)]
    for c in t.cells:
        if c.row < t.rows and c.col < t.cols:
            grid[c.row][c.col] = "\n".join(p.text for p in c.paras)
    return {"at": "t%d" % t.g, "kind": "table", "rows": t.rows, "cols": t.cols,
            "text": "\n".join("\t".join(r) for r in grid), "cells": grid}


@_api
def read(path, at=None, *, with_runs=False):
    """{rev, blocks: [{at, kind, text, runs?, style?}]}; a table also gives its cell grid."""
    doc = _load(path, layout=True, places=isinstance(at, str) and at.startswith("place:"))
    blocks = []

    def top_blocks(ps):
        for p in ps:
            blocks.append(_para_block(doc, p, with_runs))
            for t in doc.tables_in(p):
                if doc.top_of(t.host) is p and (t.host is p or t.host.cell is not None):
                    blocks.append(_table_block(doc, t))

    if at is None:
        top_blocks(doc.top)
    else:
        r = resolve(doc, at)
        if r["kind"] == "page":
            if not doc.page_starts:
                raise _unavailable("reading a page needs the engine's page layout", "page_layout_unavailable")
            n = r["page"]
            if not 1 <= n <= len(doc.page_starts):
                raise DocError("bad_address", "the document has %d pages" % len(doc.page_starts), at=at,
                               candidates=["page:%d" % len(doc.page_starts)])
            a = doc.page_starts[n - 1]
            b = doc.page_starts[n] if n < len(doc.page_starts) else len(doc.top)
            top_blocks(doc.top[a:max(b, a + 1)])
        elif r["kind"] == "table":
            blocks.append(_table_block(doc, r["table"]))
        elif r["kind"] in ("cell", "row") or (r["kind"] == "place" and r.get("cell") is not None):
            for p in r["paras"]:
                blocks.append(_para_block(doc, p, with_runs))
        elif r.get("heading") is not None:
            heads = _headings(doc)
            h = r["heading"]
            i = heads.index(h)
            nxt = next((x for x in heads[i + 1:] if x["level"] <= h["level"]), None)
            end = nxt["para"].gp if nxt else len(doc.top)
            top_blocks(doc.top[h["para"].gp:end])
        else:
            top_blocks([r["para"]]) if r["para"].top else blocks.append(_para_block(doc, r["para"], with_runs))
    return {"rev": doc.rev, "blocks": blocks}


def _pub(p, pos):
    """ptext position -> offset in the text without objects."""
    return pos - p.chars[:pos].count(OBJ)


@_api
def find(path, query, *, regex=False, scope=None):
    """{rev, hits: [{at, start, end, text, page?}]} over every paragraph (cells included)."""
    if not isinstance(query, str) or not query:
        raise DocError("bad_input", "find needs a non-empty query")
    doc = _load(path, layout=True)
    paras = doc.paras
    if scope:
        r = resolve(doc, scope)
        if r.get("heading") is not None:
            heads = _headings(doc)
            h = r["heading"]
            i = heads.index(h)
            nxt = next((x for x in heads[i + 1:] if x["level"] <= h["level"]), None)
            tops = set(doc.top[h["para"].gp:(nxt["para"].gp if nxt else len(doc.top))])
            paras = [p for p in doc.paras if doc.top_of(p) in tops]
        elif r["kind"] == "para" and r["para"].top:
            paras = [p for p in doc.paras if doc.top_of(p) is r["para"]]
        else:
            paras = r["paras"]
    try:
        rx = re.compile(query if regex else re.escape(query))
    except re.error as exc:
        raise DocError("bad_input", "the regular expression does not compile: %s" % exc)
    hits = []
    for p in paras:
        at = para_address(doc, p)
        if at is None:
            continue
        txt = p.text
        for m in rx.finditer(txt):
            if m.end() == m.start():
                continue
            h = {"at": at, "start": m.start(), "end": m.end(), "text": m.group(0)}
            if doc.page_starts:
                h["page"] = doc.page_of(p)
            hits.append(h)
    return {"rev": doc.rev, "hits": hits}


# ============================================================================ edit planning
def _ppos(p, pub):
    """offset in the public text -> ptext position."""
    n = -1
    for i, ch in enumerate(p.chars):
        if ch != OBJ:
            n += 1
            if n == pub:
                return i
    return len(p.chars)


class _Act:
    """One edit at one place: engine steps (base-document indices) and the built-in path's version."""

    def __init__(self, i, op, at, p, anchor, intra=0, *, steps=(), fb=None, dtop=0, dtbl=0, dels=(),
                 deltbl=(), rows=None, info=None):
        self.i, self.op, self.at, self.p = i, op, at, p
        self.key = (p.si, anchor, intra, i)
        self.steps, self.fb = list(steps), fb
        self.dtop, self.dtbl, self.dels, self.deltbl = dtop, dtbl, list(dels), list(deltbl)
        self.anchor = anchor
        self.rows = rows            # (table g, row, delta) for row remaps
        self.info = info or {}


def _check_expect(op, i, at, actual):
    if "expect" in op and op["expect"] is not None and op["expect"] != actual:
        raise DocError("expect_mismatch", "the text at %s is not what the op expected" % at, at=at, i=i,
                       expected=op["expect"], actual=actual[:500])


def _cell_text(c):
    return "\n".join(p.text for p in c.paras)


def _need_text_para(p, at, i):
    if p.objs:
        raise DocError("bad_input", "%s holds an object (%s); set its text with replace, or address a cell"
                       % (at, ", ".join(sorted(set(p.objs)))), at=at, i=i)


def _set_para_steps(p, text):
    st = [["goto", p.k, 0, p.si]]
    n = len(p.chars)
    if n and text:
        st += [["select", n], ["type", text]]
    elif n:
        st += [["select", n], ["delete"]]
    elif text:
        st += [["type", text]]
    return st


def _set_cell_steps(c, text):
    first, extra = c.paras[0], c.paras[1:]
    st = []
    for q in reversed(extra):
        st.append(["delete_paragraph", q.k, q.si])
    return st + _set_para_steps(first, text)


def _top_delta(p, text):
    return text.count("\n") if p.top else 0


def _md_lines(md):
    lines = []
    for ln in str(md).splitlines():
        s = ln.rstrip()
        if not s.strip():
            continue
        s = re.sub(r"^\s*#{1,6}\s+", "", s)
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)
        s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), s)
        lines.append(s)
    return lines


def _eqn_module():
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "engine" / "scripts" / "eqn.py",):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("_rigorloom_eqn", str(cand))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def _plan(doc, ops):
    """ops -> [_Act] (validated: addresses, expect, conflicts). Raises DocError."""
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise DocError("bad_input", "ops: a non-empty list of operations")
    acts = []
    text_touch = {}         # id(para) -> (i, op) for set/delete/replace targets
    need_places = any(isinstance(o, dict) and (o.get("op") == "fill" or str(o.get("at", "")).startswith("place:"))
                      for o in ops)
    if need_places and doc.engine_places is None and _engine() is not None:
        _load(doc.path, places=True)

    def touch(p, i, opname, exclusive):
        prev = text_touch.get(id(p))
        if prev is not None and (exclusive or prev[2]):
            raise DocError("conflict", "ops %d (%s) and %d (%s) both change %s" % (
                prev[0], prev[1], i, opname, para_address(doc, p)), i=i, at=para_address(doc, p))
        text_touch[id(p)] = (i, opname, exclusive)

    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise DocError("bad_input", "op %d: unknown operation %r (known: %s)" % (
                i, op.get("op") if isinstance(op, dict) else op, ", ".join(OPS)), i=i)
        name = op["op"]
        at = op.get("at")
        try:
            if name == "set":
                if not isinstance(op.get("text"), str):
                    raise DocError("bad_input", "set needs text", i=i, at=at)
                r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
                text = op["text"]
                if r.get("cell") is not None and r["kind"] in ("cell", "place"):
                    c = r["cell"]
                    _check_expect(op, i, at, _cell_text(c))
                    for q in c.paras:
                        _need_text_para(q, at, i)
                        touch(q, i, name, True)
                    acts.append(_Act(i, name, at, c.paras[0], c.paras[0].start, steps=_set_cell_steps(c, text),
                                     fb=("set_cell", c, text)))
                else:
                    p = r["para"]
                    _check_expect(op, i, at, p.text)
                    _need_text_para(p, at, i)
                    touch(p, i, name, True)
                    acts.append(_Act(i, name, at, p, p.start, steps=_set_para_steps(p, text),
                                     fb=("set_para", p, text), dtop=_top_delta(p, text)))
            elif name == "replace":
                find_, with_ = op.get("find"), op.get("with")
                if not isinstance(find_, str) or not find_ or not isinstance(with_, str):
                    raise DocError("bad_input", "replace needs find (non-empty) and with", i=i, at=at)
                if at is not None:
                    r = resolve(doc, at)
                    if r.get("range"):
                        scope = [r["para"]]
                    elif r["kind"] == "para" and r["para"].top:
                        scope = [q for q in doc.paras if doc.top_of(q) is r["para"]]
                    else:
                        scope = [q for q in r["paras"] if q is not None]
                    if isinstance(op.get("expect"), str):
                        _check_expect(op, i, at, "\n".join(q.text for q in r["paras"] if q is not None))
                else:
                    scope = doc.paras
                hits = []
                for q in scope:
                    if para_address(doc, q) is None:
                        continue
                    pt = q.ptext
                    j = pt.find(find_)
                    while j >= 0:
                        if at is None or not r.get("range") or (
                                r["range"][0] <= _pub(q, j) and _pub(q, j) + len(find_) <= r["range"][1]):
                            hits.append((q, j))
                        j = pt.find(find_, j + len(find_))
                if len(hits) > 1 and not op.get("all") and not isinstance(op.get("expect"), int):
                    raise DocError("ambiguous_match", "%r occurs %d times; narrow it with at (a candidate), or pass "
                                   "all=true" % (find_, len(hits)), at=at, i=i, total=len(hits),
                                   candidates=["%s:%d-%d" % (para_address(doc, q), _pub(q, j), _pub(q, j) + len(find_))
                                               for q, j in hits])
                if isinstance(op.get("expect"), int) and len(hits) != op["expect"]:
                    raise DocError("expect_mismatch", "replace expected %d occurrences of %r, found %d" % (
                        op["expect"], find_, len(hits)), at=at, i=i, expected=op["expect"], actual=len(hits))
                if not hits:
                    raise DocError("not_found", "%r does not occur%s" % (find_, " in %s" % at if at else ""),
                                   at=at, i=i)
                for q, j in hits:
                    touch(q, i, name, False)
                    acts.append(_Act(i, name, para_address(doc, q), q, q.start, j,
                                     steps=[["goto", q.k, j, q.si], ["select", len(find_)],
                                            ["type", with_] if with_ else ["delete"]],
                                     fb=("replace", q, j, len(find_), with_), dtop=_top_delta(q, with_)))
            elif name == "insert_after":
                md = op.get("markdown", op.get("text"))
                if not isinstance(md, str):
                    raise DocError("bad_input", "insert_after needs markdown", i=i, at=at)
                lines = _md_lines(md)
                if not lines:
                    raise DocError("bad_input", "insert_after: the markdown has no text", i=i, at=at)
                r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "table", "place"))
                if r["kind"] == "table":
                    p = doc.top_of(r["table"].host) if r["table"].host is not None else None
                    if p is None:
                        raise DocError("bad_address", "table %s has no paragraph to insert after" % at, at=at, i=i)
                elif r.get("cell") is not None and r["kind"] in ("cell", "place"):
                    p = r["cell"].paras[-1]
                else:
                    p = r["para"]
                desc = sum(1 for q in doc.sec_paras[p.si] if p.start < q.start < p.end)
                steps = [["goto", p.k, 0, p.si], ["goto_end"], ["type", "\n" + "\n".join(lines)]]
                like = op.get("like")
                if like:
                    lp = resolve(doc, like, allow=("para", "cellpara", "heading"))["para"]
                    sname = doc.style_name(lp.style)
                    cp = next((rr["cp"] for rr in lp.runs if rr.get("cp") is not None), None)
                    for j, ln in enumerate(lines):
                        nk = p.k + desc + 1 + j
                        if sname:
                            steps += [["goto", nk, 0, p.si], ["apply_style", sname]]
                        if cp is not None and ln:
                            steps += [["goto", nk, 0, p.si], ["select", len(ln)], ["set_char_shape_id", cp]]
                acts.append(_Act(i, name, at, p, p.end, steps=steps, dtop=len(lines) if p.top else 0,
                                 info={"lines": len(lines)}))
            elif name == "delete":
                r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "table", "place"))
                if r["kind"] == "table":
                    t = r["table"]
                    gone = [x.g for x in doc.sec_tables[t.si] if t.start <= x.start < t.end]
                    c0 = t.cells[0]
                    acts.append(_Act(i, name, at, c0.paras[0], t.start,
                                     steps=[["goto_cell", t.lt, c0.row, c0.col, False, t.si], ["delete_table"]],
                                     deltbl=gone))
                elif r.get("cell") is not None and r["kind"] in ("cell", "place"):
                    c = r["cell"]
                    _check_expect(op, i, at, _cell_text(c))
                    for q in c.paras:
                        _need_text_para(q, at, i)
                        touch(q, i, name, True)
                    acts.append(_Act(i, name, at, c.paras[0], c.paras[0].start, steps=_set_cell_steps(c, ""),
                                     fb=("set_cell", c, "")))
                else:
                    p = r["para"]
                    _check_expect(op, i, at, p.text)
                    touch(p, i, name, True)
                    gone = [x.g for x in doc.sec_tables[p.si] if p.start < x.start < p.end]
                    acts.append(_Act(i, name, at, p, p.start, steps=[["delete_paragraph", p.k, p.si]],
                                     dels=[p.gp] if p.top else [], deltbl=gone))
            elif name == "table.set_cells":
                grid = op.get("grid")
                if not isinstance(grid, list) or not all(isinstance(rw, list) for rw in grid):
                    raise DocError("bad_input", "table.set_cells needs grid: [[text, ...], ...]", i=i, at=at)
                r = resolve(doc, at, allow=("table", "cell"))
                t = r["table"]
                r0, c0 = (r["cell"].row, r["cell"].col) if r["kind"] == "cell" else (0, 0)
                done = set()
                for di, rw in enumerate(grid):
                    for dj, val in enumerate(rw):
                        if val is None:
                            continue
                        rr, cc = r0 + di, c0 + dj
                        c = t.at(rr, cc) if rr < t.rows and cc < t.cols else None
                        if c is None:
                            raise DocError("bad_address", "table t%d has no cell at row %d, column %d"
                                           % (t.g, rr, cc), at="t%d/r%d/c%d" % (t.g, rr, cc), i=i,
                                           candidates=["t%d (%d x %d)" % (t.g, t.rows, t.cols)])
                        if id(c) in done or (c.row, c.col) != (rr, cc):
                            raise DocError("bad_address", "t%d/r%d/c%d is inside the merged cell t%d/r%d/c%d; "
                                           "put None there" % (t.g, rr, cc, t.g, c.row, c.col),
                                           at="t%d/r%d/c%d" % (t.g, rr, cc), i=i,
                                           candidates=["t%d/r%d/c%d" % (t.g, c.row, c.col)])
                        done.add(id(c))
                        cat = "t%d/r%d/c%d" % (t.g, c.row, c.col)
                        for q in c.paras:
                            _need_text_para(q, cat, i)
                            touch(q, i, name, True)
                        acts.append(_Act(i, name, cat, c.paras[0], c.paras[0].start,
                                         steps=_set_cell_steps(c, str(val)), fb=("set_cell", c, str(val))))
            elif name in ("table.add_row", "table.delete_row"):
                r = resolve(doc, at, allow=("table", "row", "cell"))
                t = r["table"]
                if name == "table.add_row":
                    after = op.get("after", r.get("row", r["cell"].row if r.get("cell") is not None else None))
                    if not isinstance(after, int) or not 0 <= after < t.rows:
                        raise DocError("bad_address", "table.add_row: after must be a row of t%d (0..%d)"
                                       % (t.g, t.rows - 1), at=at, i=i)
                    like = op.get("like", after)
                    if like not in (after, after + 1) or like >= t.rows:
                        raise DocError("bad_input", "table.add_row: like must be the row before or after the new "
                                       "one (%d or %d)" % (after, after + 1), at=at, i=i)
                    ref = like
                    cands = [x for x in t.row_cells(ref) if x.rs == 1] or t.row_cells(ref)
                    if not cands:
                        raise DocError("bad_address", "row %d of t%d starts no cell" % (ref, t.g), at=at, i=i)
                    c = cands[0]
                    steps = [["goto_cell", t.lt, c.row, c.col, False, t.si], ["insert_row", like == after]]
                    vals = op.get("values") or op.get("cells")
                    if isinstance(vals, list):
                        for j, v in enumerate(vals):
                            if v:
                                steps += [["goto_table_cell", after + 1, j], ["type", str(v)]]
                    rowcells = t.row_cells(after) or [c]
                    anchor = max(x.end for x in rowcells)
                    acts.append(_Act(i, name, at, c.paras[0], anchor, steps=steps, rows=(t.g, after + 1, 1)))
                else:
                    row = op.get("row", r.get("row", r["cell"].row if r.get("cell") is not None else None))
                    if not isinstance(row, int) or not 0 <= row < t.rows:
                        raise DocError("bad_address", "table.delete_row needs a row of t%d (t%d/rN)" % (t.g, t.g),
                                       at=at, i=i, candidates=["t%d/r%d" % (t.g, x) for x in range(min(t.rows, 5))])
                    cands = [x for x in t.row_cells(row) if x.rs == 1] or t.row_cells(row)
                    if not cands:
                        raise DocError("bad_address", "row %d of t%d starts no cell" % (row, t.g), at=at, i=i)
                    c = cands[0]
                    acts.append(_Act(i, name, at, c.paras[0], min(x.start for x in cands),
                                     steps=[["goto_cell", t.lt, c.row, c.col, False, t.si], ["delete_row"]],
                                     rows=(t.g, row, -1)))
            elif name == "fill":
                pid = op.get("place")
                text = op.get("text")
                if not isinstance(pid, str) or not isinstance(text, str):
                    raise DocError("bad_input", "fill needs place and text", i=i)
                addr = pid if pid.startswith("place:") else "place:" + pid
                r = resolve(doc, addr)
                pl = r["place"]
                at = addr
                kind = pl.get("kind")
                if pl.get("cell") is not None and kind == "cell":
                    c = pl["cell"]
                    _check_expect(op, i, at, _cell_text(c))
                    for q in c.paras:
                        _need_text_para(q, at, i)
                        touch(q, i, name, True)
                    acts.append(_Act(i, name, at, c.paras[0], c.paras[0].start, steps=_set_cell_steps(c, text),
                                     fb=("set_cell", c, text)))
                else:
                    p = pl["para"]
                    pt = p.ptext
                    touch(p, i, name, True)
                    if kind == "body" or not pt.strip():
                        _need_text_para(p, at, i)
                        acts.append(_Act(i, name, at, p, p.start, steps=_set_para_steps(p, text),
                                         fb=("set_para", p, text), dtop=_top_delta(p, text)))
                    elif kind == "cover_placeholder":
                        lab = pl.get("label") or ""
                        j = pt.find(lab)
                        if j < 0:
                            raise DocError("bad_address", "the placeholder of %s is gone" % at, at=at, i=i)
                        acts.append(_Act(i, name, at, p, p.start, j, steps=[["goto", p.k, j, p.si],
                                                                           ["select", len(lab)], ["type", text]],
                                         fb=("replace", p, j, len(lab), text)))
                    else:   # "label: ___" — typed after the colon
                        m = re.search(r"[:：]", pt)
                        j = m.end() if m else len(pt)
                        acts.append(_Act(i, name, at, p, p.start, j, steps=[["goto", p.k, j, p.si], ["type", text]],
                                         fb=("insert", p, j, text)))
            elif name == "style":
                sty = op.get("style")
                if not isinstance(sty, str) or not sty:
                    raise DocError("bad_input", "style needs a style name", i=i, at=at)
                if sty not in {s["name"] for s in doc.styles.values()} | set(doc.styles) | {
                        s["engName"] for s in doc.styles.values()}:
                    raise DocError("bad_input", "no style %r in this document" % sty, i=i, at=at,
                                   candidates=_cands_near([s["name"] for s in doc.styles.values()], sty))
                r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
                for q in r["paras"]:
                    acts.append(_Act(i, name, at, q, q.start, steps=[["goto", q.k, 0, q.si], ["apply_style", sty]]))
            elif name in ("insert_table", "insert_picture", "insert_equation"):
                r = resolve(doc, at, allow=("para", "cellpara", "heading", "cell", "place"))
                p = r["cell"].paras[-1] if (r.get("cell") is not None and r["kind"] in ("cell", "place")) \
                    else r["para"]
                inline = op.get("offset")
                if inline is not None and (not isinstance(inline, int) or not 0 <= inline <= len(p.text)):
                    raise DocError("bad_input", "offset must be 0..%d" % len(p.text), at=at, i=i)
                if inline is not None:
                    pos = _ppos(p, inline)
                    head = [["goto", p.k, pos, p.si]]
                    anchor, intra, dtop = p.start, pos, 0
                else:
                    head = [["goto", p.k, 0, p.si], ["goto_end"], ["enter"]]
                    anchor, intra, dtop = p.end, 0, (1 if p.top else 0)
                info = {}
                if name == "insert_table":
                    data = op.get("data")
                    if not isinstance(data, list) or not data or not all(isinstance(rw, list) for rw in data):
                        raise DocError("bad_input", "insert_table needs data: [[...], ...]", i=i, at=at)
                    rows, cols = len(data), max(len(rw) for rw in data)
                    if not cols:
                        raise DocError("bad_input", "insert_table: rows are empty", i=i, at=at)
                    steps = head + [{"op": "insert_table", "args": [rows, cols],
                                     "kwargs": {"header_row": bool(op.get("header", True))}}]
                    for ri, rw in enumerate(data):
                        for ci, v in enumerate(rw):
                            if v not in (None, ""):
                                steps += [["goto_table_cell", ri, ci], ["type", str(v)]]
                    dtop += 1 if (p.top and inline is None) else 0   # Hancom ends the table's paragraph
                    acts.append(_Act(i, name, at, p, anchor, intra, steps=steps, dtop=dtop, dtbl=1))
                elif name == "insert_picture":
                    img = op.get("path")
                    if not isinstance(img, str) or not Path(img).is_file():
                        raise DocError("not_found", "insert_picture: no image at %r" % img, i=i, at=at)
                    kw = {}
                    if op.get("width_mm") is not None:
                        kw["width_mm"] = float(op["width_mm"])
                    if op.get("height_mm") is not None:
                        kw["height_mm"] = float(op["height_mm"])
                    steps = head + [{"op": "insert_picture", "args": [str(Path(img).resolve())], "kwargs": kw}]
                    acts.append(_Act(i, name, at, p, anchor, intra, steps=steps, dtop=dtop))
                else:
                    has_l, has_h = op.get("latex") is not None, op.get("hwpeqn") is not None
                    if has_l == has_h:
                        raise DocError("bad_input", "insert_equation needs exactly one of latex or hwpeqn", i=i, at=at)
                    warnings = []
                    eqn = _eqn_module()
                    if eqn is not None:
                        script, warnings, ok, reason = eqn.resolve_equation_input(
                            {"latex": op.get("latex"), "hwpeqn": op.get("hwpeqn")})
                        if not ok:
                            raise DocError("bad_input", "the equation was refused (%s)" % reason, at=at, i=i,
                                           reason=reason, warnings=list(warnings))
                        step = ["insert_equation", script]
                    elif has_h:
                        step = ["insert_equation", op["hwpeqn"]]
                    else:
                        step = {"op": "insert_equation", "args": [op["latex"]], "kwargs": {"latex": True}}
                        warnings = ["converted_by_engine"]
                    if op.get("base_pt") is not None:
                        warnings = list(warnings) + ["base_pt_ignored: the engine sizes an equation by the "
                                                     "character size at the caret"]
                    info["warnings"] = list(warnings)
                    acts.append(_Act(i, name, at, p, anchor, intra, steps=head + [step], dtop=dtop, info=info))
        except DocError as exc:
            exc.extra.setdefault("i", i)
            exc.extra.setdefault("at", at if isinstance(at, str) else None)
            raise
    return acts


def _remap(doc, acts):
    """[{from, to}] for top-level paragraphs, tables and table rows whose address changed."""
    out = []
    ins = sorted(((a.p.si, a.anchor), a.dtop) for a in acts if a.dtop)
    dels = {g for a in acts for g in a.dels}
    for p in doc.top:
        if p.gp in dels:
            out.append({"from": "p%d" % p.gp, "to": None})
            continue
        shift = sum(d for (si, pos), d in ins if (si, pos) <= (p.si, p.start))
        shift -= sum(1 for g in dels if g < p.gp)
        if shift:
            out.append({"from": "p%d" % p.gp, "to": "p%d" % (p.gp + shift)})
    tins = sorted(((a.p.si, a.anchor), a.dtbl) for a in acts if a.dtbl)
    tdel = {g for a in acts for g in a.deltbl}
    for t in doc.tables:
        if t.g in tdel:
            out.append({"from": "t%d" % t.g, "to": None})
            continue
        shift = sum(d for (si, pos), d in tins if (si, pos) <= (t.si, t.start))
        shift -= sum(1 for g in tdel if g < t.g)
        if shift:
            out.append({"from": "t%d" % t.g, "to": "t%d" % (t.g + shift)})
    for a in acts:
        if a.rows:
            g, row, d = a.rows
            t = doc.tables[g]
            if d < 0:
                out.append({"from": "t%d/r%d" % (g, row), "to": None})
            for r in range(row if d > 0 else row + 1, t.rows):
                out.append({"from": "t%d/r%d" % (g, r), "to": "t%d/r%d" % (g, r + d)})
    return out


def _signals(pl, doc=None, pages=None):
    """The engine's per-page layout findings as [{page, kind, at?, ...}]."""
    out = []
    for e in pl or []:
        n = e.get("page")
        if pages is not None and n not in pages:
            continue

        def at(para):
            return "p%d" % para if isinstance(para, int) and para >= 0 else None
        if e.get("lone_heading"):
            h = e["lone_heading"]
            out.append({"page": n, "kind": "lone_heading", "at": at(h.get("para")), "text": h.get("text")})
        bh = e.get("bottom_heading")
        if bh and not e.get("lone_heading") and 0 < (bh.get("lines_after") or 0) <= 3:
            out.append({"page": n, "kind": "bottom_heading", "at": at(bh.get("chain_para", bh.get("para"))),
                        "text": bh.get("text"), "lines_after": bh.get("lines_after")})
        for ts in e.get("table_split") or []:
            rec = {"page": n, "kind": "table_split", "at": at(ts.get("para")), "pages": ts.get("pages"),
                   "rows": ts.get("rows")}
            if doc is not None and isinstance(ts.get("para"), int) and 0 <= ts["para"] < len(doc.top):
                tt = doc.tables_in(doc.top[ts["para"]])
                if tt:
                    rec["at"] = "t%d" % tt[0].g
            out.append(rec)
        for key in ("caption_split", "widows", "orphans"):
            for x in e.get(key) or []:
                out.append({"page": n, "kind": key.rstrip("s") if key != "caption_split" else key,
                            "at": at(x.get("para"))})
        tb = e.get("top_blank")
        if tb and tb.get("cause") == "flow":
            out.append({"page": n, "kind": "top_blank", "at": at(tb.get("para")), "count": tb.get("count")})
    return out


def _default_out(p):
    return p.with_name(p.stem + ".edited.hwpx")


@_api
def edit(path, ops, *, base, out=None, in_place=False, preview=False):
    """Apply declarative ops; see the module docstring. Returns {rev_before, rev, out, applied, remap,
    changed_pages, signals} (+ changed with preview=True)."""
    src = _need_file(path)
    cur = rev_of(src)
    if base != cur:
        raise DocError("stale", "the document changed since rev %s (it is now %s); read it again" % (base, cur),
                       rev=cur, retryable=True)
    doc = _load(src)
    acts = _plan(doc, ops)
    if preview:
        target = _scratch() / ("preview-%s-%d.hwpx" % (cur, len(os.listdir(_scratch()))))
    elif in_place:
        target = src
    else:
        target = Path(out).resolve() if out else _default_out(src)
        if target == src:
            raise DocError("bad_input", "out is the input file; pass in_place=True to overwrite it")
    if not target.parent.is_dir():
        raise DocError("not_found", "the output folder does not exist: %s" % target.parent)
    if target.suffix.lower() not in (".hwpx", ".hwp"):
        raise DocError("bad_input", "out must end in .hwpx or .hwp")
    applied = [{"i": a.i, "op": a.op, "at": a.at, **({"warnings": a.info["warnings"]}
                                                     if a.info.get("warnings") else {})} for a in acts]
    seen, uniq = set(), []
    for x in applied:
        k = (x["i"], x["at"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    applied = sorted(uniq, key=lambda x: x["i"])
    order = sorted(acts, key=lambda a: a.key, reverse=True)
    e = _engine()
    res = {"rev_before": cur, "applied": applied, "remap": _remap(doc, acts)}
    if e is None:
        bad = [a for a in acts if a.fb is None or (a.fb[0] in ("set_para", "set_cell", "replace", "insert")
                                                    and "\n" in a.fb[-1])]
        if bad or doc.format != "hwpx" or target.suffix.lower() != ".hwpx":
            a = bad[0] if bad else acts[0]
            raise _unavailable("%s needs the HWP engine (built in without it: %s on .hwpx, text without line "
                               "breaks)" % (a.op if bad else ".hwp output", ", ".join(FALLBACK_OPS)),
                               "structural_edit_unsupported", at=a.at, i=a.i)
        _fallback_apply(doc, order, target)
        res.update(out=str(target), rev=rev_of(target), changed_pages=[], signals=[], engine=False)
        if preview:
            res["changed"] = [{"i": x["i"], "page": None, "rect": None} for x in applied]
        return res
    script, owner = [], []
    for a in order:
        for st in a.steps:
            script.append(st)
            owner.append(a)
    before = e.call("pages", str(src), page_hash=True)
    fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=target.suffix, dir=str(target.parent))
    os.close(fd)
    os.remove(tmp)
    try:
        r = e.call("edit", str(src), script, out=tmp, layout=True, page_hash=True)
        if not r.get("ok"):
            err = r.get("error") or {}
            step = err.get("step")
            a = owner[step] if isinstance(step, int) and 0 <= step < len(owner) else None
            done_ops = sorted({x.i for x in order[:order.index(a)]}) if a is not None else []
            exc = _engine_error(r, "edit", at=a.at if a else None, i=a.i if a else None)
            exc.extra["done"] = done_ops
            exc.extra["engine_done"] = err.get("done")
            exc.extra["written"] = False
            raise exc
        if rev_of(src) != cur:
            raise DocError("stale", "the document changed while it was being edited; nothing was written",
                           retryable=True)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    lay = r.get("layout") or {}
    pl = lay.get("page_list") or []
    old = [x.get("hash") for x in (before.get("page_list") or [])] if before.get("ok") else None
    if old is not None:
        changed = [x["page"] for j, x in enumerate(pl) if j >= len(old) or x.get("hash") != old[j]]
    else:
        changed = [x["page"] for x in pl]
    res.update(out=str(target), rev=rev_of(target), changed_pages=changed)
    try:
        newdoc = _load(target) if target.suffix.lower() == ".hwpx" else None
    except DocError:
        newdoc = None
    sig = _signals(pl, newdoc, set(changed))
    if lay.get("approx"):
        sig.append({"page": None, "kind": "approx", "fonts": list(lay["approx"])})
    res["signals"] = sig
    if newdoc is not None:
        expect_top = len(doc.top) + sum(a.dtop for a in acts) - sum(len(a.dels) for a in acts)
        if len(newdoc.top) != expect_top:
            res["remap"] = _align_remap(doc, newdoc)
            res["remap_approx"] = True
    if preview:
        starts = [s["para"] for s in lay.get("page_starts", []) if s.get("para", -1) >= 0] or [0]
        moved = {m["from"]: m["to"] for m in res["remap"]}
        ch = []
        for a in acts:
            p = doc.top_of(a.p)
            addr = moved.get("p%d" % p.gp, "p%d" % p.gp)
            pg = bisect.bisect_right(starts, int(addr[1:])) if addr else None
            ch.append({"i": a.i, "page": pg, "rect": None})
        res["changed"] = ch
    res["engine"] = True
    return res


def _align_remap(a, b):
    sm = difflib.SequenceMatcher(None, [p.text for p in a.top], [p.text for p in b.top], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal",) or (tag == "replace" and i2 - i1 == j2 - j1):
            out += [{"from": "p%d" % (i1 + d), "to": "p%d" % (j1 + d)} for d in range(i2 - i1) if i1 + d != j1 + d]
        elif tag in ("delete", "replace"):
            out += [{"from": "p%d" % x, "to": None} for x in range(i1, i2)]
    return out


# ============================================================================ built-in XML edits
def _esc(ch):
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(ch, ch)


def _piece_xml(pc):
    kind, ch, xml = pc
    if kind == "c":
        return _esc(ch)
    if kind == "x":
        return xml or {"\t": TAB_XML, "\n": "<hp:lineBreak/>", "\u3000": "<hp:fwSpace/>"}.get(ch, " ")
    return None


def _new_pieces(text):
    return [["x", "\t", TAB_XML] if ch == "\t" else ["c", ch, None] for ch in text]


def _fb_edit_para(s, p, a, b, text):
    """Section XML with ptext positions [a, b) of paragraph p replaced by text (no objects inside)."""
    if any(p.posmap[j] is None for j in range(a, b)):
        raise DocError("bad_input", "the range holds an object; the built-in path edits text only")
    reps = []      # (start, end, xml)
    if not p.tnodes:
        run = next((r for r in p.runs), None)
        if run is None:
            raise DocError("bad_input", "the paragraph has no run to type into")
        tx = "<hp:t>%s</hp:t>" % "".join(_piece_xml(pc) for pc in _new_pieces(text))
        if run["self"]:
            open_tag = s[run["a"]:run["open_end"]]
            reps.append((run["a"], run["open_end"], open_tag[:-2].rstrip() + ">" + tx + "</hp:run>"))
        else:
            close = run["b"] - len("</hp:run>")
            reps.append((close, close, tx))
    else:
        # where does the insertion go: the node of position a (or the end of the last node before it)
        if a < len(p.posmap) and p.posmap[a] is not None:
            ti, pi = p.posmap[a]
        else:
            prev = [m for m in p.posmap[:a] if m is not None]
            ti, pi = (prev[-1][0], prev[-1][1] + 1) if prev else (0, 0)
        kill = {p.posmap[j] for j in range(a, b)}
        for t_i, tn in enumerate(p.tnodes):
            pieces = [pc for p_i, pc in enumerate(tn["pieces"]) if (t_i, p_i) not in kill]
            changed = len(pieces) != len(tn["pieces"])
            if t_i == ti:
                keep_before = sum(1 for p_i in range(min(pi, len(tn["pieces"]))) if (t_i, p_i) not in kill)
                pieces[keep_before:keep_before] = _new_pieces(text)
                changed = changed or bool(text)
            if not changed:
                continue
            if any(pc[0] == "z" for pc in tn["pieces"]) or any(pc[0] == "x" and pc[2] is None and pc[1] != "\t"
                                                                for pc in pieces):
                raise DocError("bad_input", "the paragraph has marks inside its text; edit it with the engine")
            inner = "".join(_piece_xml(pc) for pc in pieces)
            open_tag = tn["open"]
            if tn["self"]:
                open_tag = open_tag[:-2].rstrip() + ">"
            reps.append((tn["a"], tn["b"], open_tag + inner + "</hp:t>"))
    if p.lineseg:
        reps.append((p.lineseg[0], p.lineseg[1], ""))
    for st, en, x in sorted(reps, key=lambda r: r[0], reverse=True):
        s = s[:st] + x + s[en:]
    return s


def _fallback_apply(doc, order, target):
    secs = list(doc.secs)
    cache = {}

    def para_now(si, k):
        if si not in cache:
            cache[si] = _scan_section(secs[si], si)[0]
            for q in cache[si]:
                q.lineseg = _own_lineseg(secs[si], q)
        return cache[si][k]

    changed = set()
    for a in order:
        kind = a.fb[0]
        si = a.p.si
        if kind == "set_para":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, 0, len(q.chars), a.fb[2])
        elif kind == "replace":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, a.fb[2], a.fb[2] + a.fb[3], a.fb[4])
        elif kind == "insert":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, a.fb[2], a.fb[2], a.fb[3])
        elif kind == "set_cell":
            c = a.fb[1]
            ks = [q.k for q in c.paras]
            for k in reversed(ks[1:]):        # extra paragraphs go
                q = para_now(si, k)
                secs[si] = secs[si][:q.start] + secs[si][q.end:]
                cache.pop(si, None)
            q = para_now(si, ks[0])
            secs[si] = _fb_edit_para(secs[si], q, 0, len(q.chars), a.fb[2])
        cache.pop(si, None)
        changed.add(si)
    contents = dict(doc.contents)
    for si in changed:
        data = secs[si].encode("utf-8")
        try:
            ET.fromstring(data)
        except ET.ParseError as exc:
            raise DocError("internal", "the edited section would not be well-formed XML (%s); nothing written"
                           % exc)
        contents[doc.section_names[si]] = data
    _write_zip(target, doc.infos, contents)


# ============================================================================ pages, render, geometry
@_api
def pages(path):
    """{rev, count, pages: [{n, starts_with, signals}], approx}"""
    src = _need_file(path)
    doc = _load(src)
    r = _ecall("pages", str(src))
    starts = {s["page"]: s.get("para") for s in r.get("page_starts", [])}
    sig = _signals(r.get("page_list"), doc)
    out = []
    for e in r.get("page_list") or []:
        n = e["page"]
        para = starts.get(n)
        out.append({"n": n, "number": e.get("number"), "starts_with": ("p%d" % para) if isinstance(para, int)
                    and para >= 0 else None, "fill": e.get("fill"),
                    "signals": [{k: v for k, v in x.items() if k != "page"} for x in sig if x["page"] == n]})
    return {"rev": doc.rev, "count": r.get("pages"), "pages": out, "approx": r.get("approx") or []}


def _page_list(pages_, count=None):
    if pages_ in (None, "all"):
        if count is None:
            raise DocError("bad_input", "pages: a page number, a list of them, or \"all\"")
        return list(range(1, count + 1))
    if isinstance(pages_, str):
        a = parse_address(pages_) if pages_.startswith("page:") else {"kind": "page", "page": int(pages_)} \
            if pages_.isdigit() else None
        if not a or a["kind"] != "page":
            raise DocError("bad_address", "pages: page:N, N, a list, or \"all\"", at=pages_)
        return [a["page"]]
    if isinstance(pages_, int):
        return [pages_]
    if isinstance(pages_, (list, tuple)) and all(isinstance(x, int) for x in pages_):
        return list(pages_)
    raise DocError("bad_input", "pages: a page number, a list of them, or \"all\"")


def _pdfium():
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415 - optional
        return pdfium
    except ImportError:
        return None


@_api
def render(path, pages, *, scale=2.0, fmt="png", out_dir=None):  # noqa: A002 - doc_core name
    """{rev, pages: [{n, file, width_pt, height_pt, px_w, px_h}]}; fmt="pdf" writes one PDF."""
    src = _need_file(path)
    rev = rev_of(src)
    e = _need_engine("render")
    if fmt not in ("png", "pdf"):
        raise DocError("bad_input", "fmt is png or pdf")
    od = Path(out_dir).resolve() if out_dir else (_scratch() / ("render-" + rev))
    od.mkdir(parents=True, exist_ok=True)
    count = None
    if pages in (None, "all"):
        pr = e.call("pages", str(src))
        if not pr.get("ok"):
            raise _engine_error(pr, "pages")
        count = pr.get("pages")
    sel = _page_list(pages, count)
    stem = src.stem
    if fmt == "png":
        r = e.call("png", str(src), str(od), pages=sel, scale=scale)
        if r.get("ok") and isinstance(r.get("pages"), list):
            return {"rev": rev, "pages": r["pages"], "via": "engine_png"}
    pdf_out = od / ("%s.pdf" % stem if fmt == "pdf" else ".%s-%s.pdf" % (stem, rev))
    r = e.call("pdf", str(src), str(pdf_out), pages=sel)
    if not r.get("ok"):
        raise _engine_error(r, "pdf")
    pdfium = _pdfium()
    if fmt == "pdf":
        out = {"rev": rev, "file": str(pdf_out), "pages": [{"n": n} for n in sel]}
        if pdfium is not None:
            d = pdfium.PdfDocument(str(pdf_out))
            try:
                for j, rec in enumerate(out["pages"]):
                    w, h = d[j].get_size()
                    rec.update(width_pt=round(w, 2), height_pt=round(h, 2))
            finally:
                d.close()
        return out
    if pdfium is None:
        raise _unavailable("PNG pages need pypdfium2 (pip install pypdfium2)", "rasterizer_missing")
    d = pdfium.PdfDocument(str(pdf_out))
    res = []
    try:
        for j, n in enumerate(sel):
            pg = d[j]
            w, h = pg.get_size()
            img = pg.render(scale=float(scale)).to_pil()
            f = od / ("%s.p%d.png" % (stem, n))
            fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".png", dir=str(od))
            os.close(fd)
            img.save(tmp, "PNG")
            os.replace(tmp, f)
            res.append({"n": n, "file": str(f), "width_pt": round(w, 2), "height_pt": round(h, 2),
                        "px_w": img.width, "px_h": img.height})
    finally:
        d.close()
        try:
            pdf_out.unlink()
        except OSError:
            pass
    return {"rev": rev, "pages": res, "via": "engine_pdf+pypdfium2"}


def _passthrough(fn, *args, **kwargs):
    src = _need_file(args[0])
    r = _ecall(fn, str(src), *args[1:], **kwargs)
    out = {k: v for k, v in r.items() if k not in ("api", "ok", "backend", "fn", "fallback")}
    out.setdefault("rev", rev_of(src))
    return out


@_api
def geometry(path, page):
    """{rev, page, width_pt, height_pt, boxes: [{at, kind, rect, text?, baseline?, xs?}]} (engine)."""
    n = _page_list(page)[0]
    return _passthrough("geometry", path, n)


@_api
def hit_test(path, page, x, y):
    """{at, offset} of the point (pt) on the page (engine)."""
    n = _page_list(page)[0]
    return _passthrough("hit_test", path, n, x, y)


@_api
def caret_rect(path, at, offset):
    """{page, rect} of the caret at offset in the paragraph at (engine)."""
    parse_address(at)
    return _passthrough("caret_rect", path, at, offset)


# ============================================================================ convert, new, diff
@_api
def convert(src, out, *, to):
    """{out, lossy: [str]}; to in hwpx, hwp, pdf, png, md, docx."""
    s = _need_file(src)
    o = Path(out).resolve()
    if o == s:
        raise DocError("bad_input", "out is the input file")
    if not o.parent.is_dir():
        raise DocError("not_found", "the output folder does not exist: %s" % o.parent)
    fmt = s.suffix.lower().lstrip(".")
    if to not in ("hwpx", "hwp", "pdf", "png", "md", "docx"):
        raise DocError("bad_input", "to is one of hwpx, hwp, pdf, png, md, docx")
    if fmt in ("hwpx", "hwp"):
        real = _format_of(s)
        if to == "hwpx" and real == "hwpx":
            _atomic_copy(s, o)
            return {"out": str(o), "lossy": []}
        if _engine() is None and to == "md" and real == "hwpx":
            raise _unavailable("markdown export needs the HWP engine", "engine_not_configured")
        if to == "hwpx":
            r = _ecall("to_hwpx", str(s), str(o))
            return {"out": str(o), "lossy": ["%s x%d not converted" % (k, v)
                                             for k, v in (r.get("unsupported") or {}).items()]}
        if to == "hwp":
            r = _ecall("save", str(s), str(o))
            return {"out": str(o), "lossy": list(r.get("warnings") or [])}
        if to == "pdf":
            r = _ecall("pdf", str(s), str(o))
            return {"out": str(o), "lossy": list(r.get("approx") or [])}
        if to == "png":
            r = render.__wrapped__(s, "all", out_dir=o if o.suffix.lower() != ".png" else o.parent)
            return {"out": str(o), "pages": r["pages"], "lossy": []}
    e = _need_engine("converting to %s" % to)
    r = e.call("convert", str(s), str(o), to=to)
    if not r.get("ok"):
        raise _engine_error(r, "convert")
    return {"out": r.get("out", str(o)), "lossy": list(r.get("lossy") or [])}


@_api
def new(markdown_path_or_text, out, *, form=None):
    """{out, rev}: a document built from markdown (a .md path or the text), optionally on a form."""
    o = Path(out).resolve()
    if not o.parent.is_dir():
        raise DocError("not_found", "the output folder does not exist: %s" % o.parent)
    src = markdown_path_or_text
    if isinstance(src, str) and "\n" not in src and Path(src).is_file():
        src = str(Path(src).resolve())
    kw = {"form": str(_need_file(form))} if form else {}
    r = _ecall("build", src, str(o), **kw)
    return {"out": str(o), "rev": rev_of(o), "warnings": list(r.get("warnings") or [])}


@_api
def diff(a, b):
    """{changes: [{at, before, after, kind, at_b?}]}: top-level paragraphs and table cells."""
    da, db = _load(a), _load(b)
    ch = []
    sm = difflib.SequenceMatcher(None, [p.text for p in da.top], [p.text for p in db.top], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n = max(i2 - i1, j2 - j1)
        for d in range(n):
            pa = da.top[i1 + d] if i1 + d < i2 else None
            pb = db.top[j1 + d] if j1 + d < j2 else None
            ch.append({"at": "p%d" % pa.gp if pa else None, "at_b": "p%d" % pb.gp if pb else None,
                       "kind": "changed" if pa and pb else ("deleted" if pa else "inserted"),
                       "before": pa.text if pa else None, "after": pb.text if pb else None})
    for ta, tb in zip(da.tables, db.tables):
        for c in ta.cells:
            cb = tb.at(c.row, c.col)
            before, after = _cell_text(c), (_cell_text(cb) if cb is not None else None)
            if before != after:
                ch.append({"at": "t%d/r%d/c%d" % (ta.g, c.row, c.col), "kind": "changed",
                           "before": before, "after": after})
    return {"rev_a": da.rev, "rev_b": db.rev, "changes": ch}


__all__ = ["open", "outline", "read", "find", "edit", "render", "geometry", "hit_test", "caret_rect", "pages",
           "convert", "new", "diff", "parse_address", "resolve", "rev_of", "close", "engine_status", "DocError"]
