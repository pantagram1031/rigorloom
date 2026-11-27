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
``para`` index of the engine's ``pages()`` flow and form_model's ``k``. ``tN``
counts top-level body tables only, in document order through all sections (the
engine's ``hnc_addr``; doc-core-api.md, ruling 2026-11-19). A nested table is
addressed through its cell: ``t0/r1/c2/t0`` is the first table in that cell,
and ``t0/r1/c2/t0/r0/c0/p0`` goes on below it. Inside ``hp:switch`` only the
branch layout uses (the first ``hp:case``, else ``hp:default``) is counted;
tables in headers, footers, notes, captions and text boxes have no address.
A cell is addressed by its ``<hp:cellAddr>`` row/col; a covered (merged-away)
coordinate answers at its top-left anchor. ``tN/rR/cC/pK`` is the K-th
paragraph directly in that cell (``hnc_edit.Doc.cell_paragraphs``). Internally
every ``<hp:tbl>`` keeps its start-tag index (``Table.g``/``lt``), which is
what engine edit scripts use. Offsets and ``p12:5-18`` ranges count Unicode
code points of the paragraph's text (objects left out).

ADDRESSES. ``p12``, ``t3``, ``t3/r2`` (a row, for table ops), ``t3/r2/c1``,
``t3/r2/c1/p0``, ``h:"제목"`` (exact heading text, then a unique prefix;
quotes optional), ``place:<id>`` (a fill seat from ``outline()``), ``page:4``
(1-based, pages/render/geometry only). An address that does not resolve is
``bad_address`` with ``at`` and the nearest ``candidates``; a page or offset out
of range is ``bad_address`` with ``range: [lo, hi]``.

EDITS. ``edit(path, ops, base=rev)`` reads the file once and refuses with
``stale`` when its rev (first 12 hex of the sha256 of its bytes) is not
``base``; checks every op (address kinds, ranges, ``expect``, overlaps) before
touching anything; turns all ops into ONE engine edit script (applied from the
end of the document backwards, so every address means what it meant in
``base``); builds and verifies the whole result, then publishes it through a
unique temp file, fsync and an atomic replace under the destination's lock
(an in-place edit re-checks the rev there). It writes ``<stem>.edited.hwpx``
next to the input unless ``out`` is given, and the input only with
``in_place=True``. See docs/doc-core.md for errors, remap and fill places.
"""
from __future__ import annotations

import atexit
import builtins
import bisect
import difflib
import hashlib
import importlib.util
import io
import itertools
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

try:  # installed as rigorloom_runtime.rt_doc
    from . import rt_codes as _codes  # type: ignore
except ImportError:  # run from a checkout with runtime/scripts on sys.path
    import rt_codes as _codes  # type: ignore

ENGINE_ENV = "RIGORLOOM_HWP_ENGINE"
TIMEOUT_ENV = "RIGORLOOM_DOC_ENGINE_TIMEOUT"
DEFAULT_TIMEOUT_S = 180.0
ENGINE_API = 1          #: the kit_api envelope version this module speaks
CACHE_ENV = "RIGORLOOM_DOC_CACHE"
_LINEAGE = {}
SCHEMA = "rigorloom/doc-core/v1"

OPS = ("set", "replace", "insert_after", "delete", "table.set_cells", "table.add_row",
       "table.delete_row", "fill", "style", "insert_table", "insert_picture", "insert_equation",
       "char_shape", "para_shape", "numbering", "table.merge", "table.split", "table.add_col",
       "table.delete_col", "table.size", "page_setup", "columns", "break", "header", "page_number",
       "table.cell_style", "table.style", "style.create", "note", "caption", "bookmark", "link", "toc",
       "hide", "new_number", "picture", "table.formula")
#: ops the built-in XML path can do without the engine
FALLBACK_OPS = ("set", "replace", "table.set_cells", "fill", "delete")

_bopen = builtins.open
_RETRYABLE = {"stale": True, "busy": True, "locked": True, "engine_timeout": True, "engine_unavailable": True, "internal": False}


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
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rev_of(path) -> str:
    """First 12 hex of the sha256 of the file's bytes."""
    h = hashlib.sha256()
    with _bopen(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _read_bytes(path) -> bytes:
    """The file's bytes in one read: every rev this module reports is the rev of the bytes it parsed."""
    try:
        with _bopen(path, "rb") as f:
            return f.read()
    except PermissionError as exc:      # Windows: open in Hancom without read sharing
        raise DocError("locked", "%s is locked by another program (%s); close it and retry"
                       % (Path(path).name, exc.strerror or exc), at=str(path), retryable=True)


def _need_file(path):
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise DocError("bad_input", "a document path is a non-empty string")
    p = Path(path)
    if not p.is_file():
        raise DocError("not_found", "no such file: %s" % path)
    return p.resolve()


def _format_of_bytes(head: bytes, path) -> str:
    if head.startswith(b"PK"):
        return "hwpx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    suf = Path(path).suffix.lower().lstrip(".")
    if suf in ("md", "markdown", "txt"):
        return "md"
    raise DocError("bad_input", "not a .hwpx or .hwp document: %s" % Path(path).name)


def _format_of(path) -> str:
    try:
        with _bopen(path, "rb") as f:
            head = f.read(8)
    except PermissionError as exc:
        raise DocError("locked", "%s is locked by another program (%s); close it and retry"
                       % (Path(path).name, exc.strerror or exc), at=str(path), retryable=True)
    return _format_of_bytes(head, path)


_SCRATCH = None
_SCRATCH_LOCK = threading.Lock()
SCRATCH_TTL_S = 3600.0      #: previews and renders older than this are removed from the scratch folder


def _scratch() -> Path:
    """This process's private scratch folder (0700, removed at exit)."""
    global _SCRATCH
    with _SCRATCH_LOCK:
        if _SCRATCH is None or not Path(_SCRATCH).is_dir():
            _SCRATCH = tempfile.mkdtemp(prefix="rigorloom-doc-")
            atexit.register(shutil.rmtree, _SCRATCH, True)
        return Path(_SCRATCH)


def _scratch_sub(name) -> Path:
    d = _scratch() / name
    d.mkdir(exist_ok=True)
    return d


def _prune(folder: Path, ttl=None):
    """Long-lived hosts: drop what an earlier preview or render left in a scratch subfolder."""
    cut = time.time() - (SCRATCH_TTL_S if ttl is None else ttl)
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for ent in entries:
        try:
            if ent.stat(follow_symlinks=False).st_mtime < cut:
                shutil.rmtree(ent.path, True) if ent.is_dir(follow_symlinks=False) else os.remove(ent.path)
        except OSError:
            pass


# ---------------------------------------------------------------------------- output paths
def _real(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _same_file(a, b) -> bool:
    """True when a and b name the same file: same path after links, or the same inode (hard links)."""
    try:
        if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return _real(a) == _real(b)


def _check_out(out, inputs=(), *, suffixes=None, what="out"):
    """The absolute output path. Refused (bad_input) when it is a link, a folder, or any of the inputs (also
    through a hard or symbolic link); not_found when its folder does not exist."""
    if not isinstance(out, (str, os.PathLike)) or not os.fspath(out):
        raise DocError("bad_input", "%s: an output path is required" % what)
    raw = Path(os.path.abspath(os.fspath(out)))
    parent = raw.parent
    if not parent.is_dir():
        raise DocError("not_found", "the output folder does not exist: %s" % parent)
    o = Path(os.path.realpath(parent)) / raw.name
    if os.path.islink(o):
        raise DocError("bad_input", "%s is a symbolic link; name the file itself" % what, at=str(raw))
    if o.is_dir():
        raise DocError("bad_input", "%s is a folder: %s" % (what, raw), at=str(raw))
    if suffixes and o.suffix.lower() not in suffixes:
        raise DocError("bad_input", "%s must end in %s" % (what, " or ".join(suffixes)), at=str(raw))
    for src in inputs:
        if src is not None and _same_file(o, src):
            raise DocError("bad_input", "%s is the input file %s (or a link to it); write somewhere else%s"
                           % (what, Path(src).name, " or pass in_place=True" if what == "out" else ""),
                           at=str(raw))
    return o


# ---------------------------------------------------------------------------- locks and publication
LOCK_TIMEOUT_ENV = "RIGORLOOM_DOC_LOCK_TIMEOUT"
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 120.0        #: a lock file older than this was left by a writer that died; it is broken
_REPLACE_TRIES = 6
_TLOCKS = {}
_TLOCKS_GUARD = threading.Lock()


def _lock_path(target) -> Path:
    t = Path(os.path.realpath(Path(target).parent)) / Path(target).name
    return t.parent / (".~%s.rtdoc-lock" % t.name)


class _PathLock:
    """Serializes writers of one destination: a thread lock for this process and an O_EXCL lock file next to
    the destination for every cooperating process (CLI, MCP, UI). Held only for the final check and replace."""

    def __init__(self, target):
        self.file = _lock_path(target)
        key = os.path.normcase(str(self.file))
        with _TLOCKS_GUARD:
            self.tl = _TLOCKS.setdefault(key, threading.Lock())
        self.timeout = float(os.environ.get(LOCK_TIMEOUT_ENV) or LOCK_TIMEOUT_S)

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        if not self.tl.acquire(timeout=self.timeout):
            raise self._busy()
        try:
            while True:
                try:
                    fd = os.open(str(self.file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except (FileExistsError, PermissionError):     # Windows: a lock file being deleted
                    try:
                        if time.time() - os.stat(self.file).st_mtime > LOCK_STALE_S:
                            # break it by renaming to a name of our own first: of two waiters only one
                            # rename succeeds, so neither can remove a lock the other has just taken
                            gone = self.file.with_name("%s.%d.%s.stale" % (self.file.name, os.getpid(),
                                                                          os.urandom(4).hex()))
                            os.rename(self.file, gone)
                            if time.time() - os.stat(gone).st_mtime > LOCK_STALE_S:
                                os.remove(gone)
                            else:           # it was replaced by a fresh lock between stat and rename
                                try:
                                    os.rename(gone, self.file)
                                except OSError:
                                    os.remove(gone)
                            continue
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise self._busy()
                    time.sleep(0.02)
                    continue
                with os.fdopen(fd, "w") as f:
                    f.write("%d %s\n" % (os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%S")))
                return self
        except BaseException:
            self.tl.release()
            raise

    def __exit__(self, *exc):
        try:
            os.remove(self.file)
        except OSError:
            pass
        self.tl.release()

    def _busy(self):
        return DocError("busy", "another writer is saving %s; retry in a moment" % self.file.name[2:-11],
                        retryable=True)


def _before_publish(dest):
    """Called after the output is staged and before the destination lock is taken (a test hook)."""


def _replace(tmp, dest):
    """os.replace, retried while Windows reports a sharing violation (the file is open elsewhere)."""
    for n in range(_REPLACE_TRIES):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if n + 1 < _REPLACE_TRIES:
                time.sleep(0.02 * (2 ** n))
    raise DocError("locked", "%s is open in another program (or not writable); close it and retry"
                   % Path(dest).name, at=str(dest), retryable=True)


def _fsync_dir(d):
    if os.name == "nt":
        return
    try:
        fd = os.open(str(d), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _umask():
    """The process umask (read once: os.umask can only be read by setting it)."""
    global _UMASK
    if _UMASK is None:
        with _TLOCKS_GUARD:
            if _UMASK is None:
                old = os.umask(0o022)
                os.umask(old)
                _UMASK = old
    return _UMASK


_UMASK = None
TMP_STALE_S = 3600.0        #: a staged .rtdoc-*.tmp older than this was left by a writer that died


def _sweep_tmp(folder: Path):
    """Remove staged files a killed writer left in folder (best effort)."""
    try:
        now = time.time()
        for x in folder.glob(".rtdoc-*.tmp"):
            try:
                if now - x.stat().st_mtime > TMP_STALE_S:
                    x.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _stage(dest, data=None, src=None):
    """A unique temp file next to dest holding data (bytes) or a copy of src, flushed to disk. It gets the
    destination's mode (a new file: 0666 less the umask), not mkstemp's 0600."""
    folder = Path(dest).parent
    _sweep_tmp(folder)
    fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".tmp", dir=str(folder))
    try:
        try:
            mode = os.stat(dest).st_mode & 0o7777
        except OSError:
            mode = 0o666 & ~_umask()
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as f:
            if data is not None:
                f.write(data)
            else:
                with _bopen(src, "rb") as s:
                    shutil.copyfileobj(s, f, 1 << 20)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        _unlink(tmp)
        raise
    return tmp


def _unlink(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _publish(dest, data=None, src=None, check=None):
    """Write dest atomically: stage next to it, then under dest's lock run check (the compare-and-swap of an
    in-place edit; it raises to refuse) and os.replace. The temp file goes on every failure path."""
    return _publish_many([(dest, data, src)], check)


def _publish_many(items, check=None):
    """[(dest, data, src)] staged first (all of them), then each replaced under its lock. Nothing is replaced
    unless everything staged."""
    staged = []
    try:
        for dest, data, src in items:
            staged.append((Path(dest), _stage(dest, data, src)))
        for dest, _tmp in staged:
            _before_publish(dest)
        for dest, tmp in staged:
            with _PathLock(dest):
                if check is not None:
                    check()
                _replace(tmp, dest)
        for d in {dest.parent for dest, _ in staged}:
            _fsync_dir(d)
    finally:
        for _dest, tmp in staged:
            if os.path.exists(tmp):
                _unlink(tmp)
    return [str(d) for d, _ in staged]


# ============================================================================ engine
def _engine_dir(env=None):
    """(absolute engine folder, None) or (None, why). A relative RIGORLOOM_HWP_ENGINE is taken from the current
    folder once, here, so the worker's own working directory cannot change what it means."""
    env = os.environ if env is None else env
    raw = (env.get(ENGINE_ENV) or "").strip()
    if raw:
        d = Path(os.path.abspath(os.path.expanduser(raw)))
        return (d, None) if (d / "kit_api.py").is_file() else (None, "engine_path_missing")
    try:
        spec = importlib.util.find_spec("hwp_engine")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        for loc in list(spec.submodule_search_locations or []) + (
                [str(Path(spec.origin).parent)] if spec.origin else []):
            if (Path(loc) / "kit_api.py").is_file():
                return Path(os.path.abspath(loc)), None
        return None, "engine_package_without_kit_api"
    return None, "engine_not_configured"


class _Transport(Exception):
    """The worker did not answer: it is gone, it timed out, or it spoke something that is not the protocol."""

    def __init__(self, message, *, timeout=False):
        super().__init__(message)
        self.timeout = timeout


class _Worker:
    """One generation of the engine worker: ``kit_api.py serve`` on pipes (JSON lines, UTF-8 both ways).

    A writer thread feeds stdin so a worker that stops reading can never block a caller past its deadline; a
    reader thread hands answers to their waiting callers by id and wakes every caller when the pipe closes."""

    def __init__(self, kit_dir: Path):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"       # the worker reads sys.stdin with its default encoding
        env["PYTHONUTF8"] = "1"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0   # no console flash
        self.proc = subprocess.Popen([sys.executable, str(kit_dir / "kit_api.py"), "serve", "--threads", "4"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=str(kit_dir), env=env,
                                     creationflags=flags)
        self.ids = itertools.count(1)
        self.wait = {}
        self.lock = threading.Lock()
        self.dead = None                        # why it stopped, once it has
        self.ready = threading.Event()          # set once the handshake answered
        self.settled = threading.Event()        # set once it is ready or dead
        self.q = queue.Queue()
        self.writer = threading.Thread(target=self._write, name="rt_doc-engine-writer", daemon=True)
        self.reader = threading.Thread(target=self._read, name="rt_doc-engine-reader", daemon=True)
        self.writer.start()
        self.reader.start()

    def _write(self):
        while True:
            data = self.q.get()
            if data is None:
                return
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self._die("the engine worker stopped reading its requests (%s)" % exc)
                return

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    r = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue                    # not a protocol line; the worker sends those to stderr
                slot = self.wait.get(r.get("id")) if isinstance(r, dict) else None
                if slot is not None:
                    slot[1] = r
                    slot[0].set()
        except (OSError, ValueError):
            pass
        self._die("the engine worker closed the connection")

    def _die(self, why):
        with self.lock:
            if self.dead is None:
                self.dead = why
            slots = list(self.wait.values())
        self.settled.set()
        for slot in slots:
            slot[0].set()

    def alive(self):
        return self.dead is None and self.proc.poll() is None

    def call(self, fn, args, kwargs, deadline):
        i = next(self.ids)
        data = (json.dumps({"id": i, "fn": fn, "args": list(args), "kwargs": dict(kwargs)}, ensure_ascii=False)
                + "\n").encode("utf-8")        # TypeError / ValueError: an argument JSON cannot carry
        slot = [threading.Event(), None]
        with self.lock:
            if self.dead is not None:
                raise _Transport(self.dead)
            self.wait[i] = slot
        try:
            self.q.put(data)
            left = deadline - time.monotonic()
            if left <= 0 or not slot[0].wait(left):
                raise _Transport("no answer to %s within the engine timeout" % fn, timeout=True)
            r = slot[1]
            if r is None:
                raise _Transport(self.dead or "the engine worker closed the connection")
            if not isinstance(r.get("ok"), bool) or (not r["ok"] and not isinstance(r.get("error"), dict)):
                raise _Transport("the engine worker answered %s with something that is not an envelope" % fn)
            return r
        finally:
            with self.lock:
                self.wait.pop(i, None)

    def handshake(self, deadline):
        r = self.call("ping", (), {}, deadline)
        if not r.get("ok") or r.get("api") != ENGINE_API:
            raise _Transport("the engine at hand does not speak kit_api protocol %s (ping: %s)"
                             % (ENGINE_API, {k: r.get(k) for k in ("ok", "api", "error")}))
        self.ready.set()
        self.settled.set()

    def kill(self):
        """End this generation now: no lock of a caller is needed, every waiting caller wakes up."""
        self._die("the engine worker was stopped")
        try:
            self.proc.kill()
        except OSError:
            pass
        self._reap(5)

    def close(self, wait=10.0):
        """End this generation politely: close stdin, wait for the worker, kill it if it lingers."""
        self.q.put(None)
        self.writer.join(1.0)
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(wait)
        except subprocess.TimeoutExpired:
            try:
                self.proc.kill()
            except OSError:
                pass
        self._die("the engine worker was stopped")
        self._reap(5)

    def _reap(self, wait):
        try:
            self.proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass
        self.q.put(None)
        for f in (self.proc.stdin, self.proc.stdout):
            try:
                f.close()
            except (OSError, ValueError):
                pass


class _Engine:
    """The process's engine: one worker generation at a time, started lazily, replaced when it fails.

    Every call has ONE deadline (``RIGORLOOM_DOC_ENGINE_TIMEOUT`` seconds) covering starting the worker, sending
    the request and waiting for the answer. A failure retires only the generation that failed, so a late failure
    of an old worker never stops a newer one. Failed starts back off (0.5 s, doubling, at most 30 s)."""

    def __init__(self, kit_dir: Path):
        self.dir = Path(os.path.abspath(kit_dir))
        self.lock = threading.Lock()
        self.start_lock = threading.Lock()
        self.worker = None
        self.fails = 0
        self.next_start = 0.0
        self.timeout = float(os.environ.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT_S)

    def _current(self, deadline):
        with self.lock:
            w = self.worker
        if w is not None and w.alive():
            if not w.settled.wait(max(0.0, deadline - time.monotonic())):
                raise _Transport("the engine worker did not start in time", timeout=True)
            if w.alive() and w.ready.is_set():
                return w
        if w is not None:
            self._retire(w)
        left = deadline - time.monotonic()
        if left <= 0 or not self.start_lock.acquire(timeout=left):
            raise _Transport("the engine worker did not start in time", timeout=True)
        try:
            with self.lock:
                w = self.worker
            if w is not None and w.alive() and w.ready.is_set():
                return w
            if time.monotonic() < self.next_start:
                raise _Transport("the engine worker failed to start a moment ago; retry shortly")
            w = None
            try:
                w = _Worker(self.dir)
                with self.lock:
                    self.worker = w
                w.handshake(deadline)
            except Exception as exc:  # noqa: BLE001 - OSError, _Transport, a protocol mismatch
                self.fails += 1
                self.next_start = time.monotonic() + min(30.0, 0.5 * 2 ** (self.fails - 1))
                if w is not None:
                    self._retire(w)
                if isinstance(exc, _Transport):
                    raise
                raise _Transport("the engine worker did not start: %s" % exc)
            self.fails = 0
            return w
        finally:
            self.start_lock.release()

    def call(self, fn, *args, **kwargs):
        """The engine's envelope, or an envelope saying why there is none. Never raises."""
        deadline = time.monotonic() + self.timeout
        args = [os.fspath(a) if isinstance(a, os.PathLike) else a for a in args]
        kwargs = {k: os.fspath(v) if isinstance(v, os.PathLike) else v for k, v in kwargs.items()}
        w = None
        try:
            w = self._current(deadline)
            return w.call(fn, args, kwargs, deadline)
        except (TypeError, ValueError) as exc:          # an argument JSON cannot carry: the worker is fine
            return {"ok": False, "error": {"code": "bad_input", "message": str(exc), "retryable": False}}
        except _Transport as exc:
            if w is not None:
                self._retire(w)
            return {"ok": False, "error": {"code": "engine_timeout" if exc.timeout else "engine_unavailable",
                                           "message": str(exc), "retryable": True}}

    def _retire(self, w):
        """Stop generation w; the current worker is touched only when it IS w."""
        with self.lock:
            if self.worker is w:
                self.worker = None
        w.kill()

    def reset(self, kill=False):
        with self.lock:
            w, self.worker = self.worker, None
        if w is not None:
            w.kill() if kill else w.close()


_ENGINE = None
_ENGINE_KEY = None
_ENGINE_LOCK = threading.Lock()


def _engine():
    """The process's engine, or None when none is configured."""
    global _ENGINE, _ENGINE_KEY
    d, _why = _engine_dir()
    key = str(d) if d else None
    old = None
    with _ENGINE_LOCK:
        if key != _ENGINE_KEY:
            old = _ENGINE
            _ENGINE = _Engine(d) if d else None
            _ENGINE_KEY = key
        e = _ENGINE
    if old is not None:
        old.reset()
    return e


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


_RESERVED = ("code", "message", "at", "i", "retryable", "engine_fn")
#: (engine edit step, keyword) -> the engine that first has it, named when an older engine lacks it
ENGINE_NEEDS = {("insert_header", "replace"): "hwp-engine 2077774 or later (PR #23, header replace)",
                ("page_number", "replace"): "hwp-engine 2077774 or later (PR #23, header replace)"}


def _engine_error(env, fn=None, at=None, i=None):
    """An engine failure envelope -> DocError keeping code, message, step, done and the worker's own at /
    retryable (ours win only when we have one)."""
    err = env.get("error") if isinstance(env.get("error"), dict) else {}
    code = str(err.get("code") or "internal")
    msg = str(err.get("message") or "the engine refused %s" % fn)
    if code == "unsupported" and msg.startswith("no such function"):
        return _unavailable("the installed engine has no %s yet" % fn, "engine_function_missing", fn=fn)
    m = re.search(r"unknown hnc_edit operation '([A-Za-z_]\w*)'", msg) if code == "bad_input" else None
    if m:       # an older engine without an edit step an op needs: the op lights up once the engine has it
        return _unavailable("the installed engine has no %s yet; update the HWP engine" % m.group(1),
                            "engine_function_missing", fn=m.group(1), engine_fn=fn,
                            at=at if at is not None else err.get("at"), i=i if i is not None else err.get("i"))
    m = re.search(r"\((\w+)\): TypeError: \S+ got an unexpected keyword argument '(\w+)'", msg) \
        if code == "bad_input" else None
    if m:       # an older engine whose edit step lacks a keyword an op needs (e.g. insert_header replace=)
        need = ENGINE_NEEDS.get((m.group(1), m.group(2)), "a newer HWP engine")
        return _unavailable("the installed engine's %s has no %s yet; this needs %s" % (m.group(1), m.group(2), need),
                            "engine_function_missing", fn=m.group(1), keyword=m.group(2), needs=need,
                            engine_fn=fn, at=at if at is not None else err.get("at"),
                            i=i if i is not None else err.get("i"))
    extra = {k: v for k, v in err.items() if k not in _RESERVED}
    if isinstance(err.get("retryable"), bool):
        retry = err["retryable"]
    else:
        retry = code in ("engine_timeout", "engine_unavailable", "busy")
    return DocError(code, msg, at=at if at is not None else err.get("at"),
                    i=i if i is not None else err.get("i"), retryable=retry, engine_fn=fn, **extra)


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


# ============================================================================ the .hwpx package
class _Zip:
    """A ZIP read from bytes, kept as raw entries so a rewrite copies every untouched member byte for byte
    (local header, compressed data, data descriptor, central record, order, archive comment)."""
    _CD = struct.Struct("<4sHHHHHHIIIHHHHHII")
    _LH = struct.Struct("<4sHHHHHIIIHH")

    def __init__(self, raw: bytes, name="document"):
        self.raw = raw
        bad = lambda why: DocError("bad_input", "%s is not a readable .hwpx (%s)" % (name, why))  # noqa: E731
        i = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 22 - 65535))
        if i < 0 or len(raw) < i + 22:
            raise bad("no zip directory")
        (_sig, disk, cd_disk, n_disk, n, cd_size, cd_off, clen) = struct.unpack("<4sHHHHIIH", raw[i:i + 22])
        if disk or cd_disk or n_disk != n or n == 0xFFFF or cd_off == 0xFFFFFFFF:
            raise bad("multi-part or zip64 archives are not supported")
        if n > _codes.MAX_ZIP_MEMBERS:
            raise DocError("bad_input", "too many zip members in %s" % name)
        self.comment = raw[i + 22:i + 22 + clen]
        self.entries, seen, pos, total = [], set(), cd_off, 0
        for _ in range(n):
            if raw[pos:pos + 4] != b"PK\x01\x02":
                raise bad("a damaged zip directory")
            f = self._CD.unpack(raw[pos:pos + 46])
            flags, method, crc, csize, usize, nlen, xlen, mlen, off = f[3], f[4], f[7], f[8], f[9], f[10], f[11], \
                f[12], f[16]
            bname = raw[pos + 46:pos + 46 + nlen]
            name_ = bname.decode("utf-8" if flags & 0x800 else "cp437", "replace")
            if 0xFFFFFFFF in (csize, usize, off):
                raise bad("zip64 members are not supported")
            if flags & 1:
                raise bad("encrypted members")
            if name_ in seen:
                raise DocError("bad_input", "%s has two members named %s; which one is the document is ambiguous"
                               % (name, name_))
            seen.add(name_)
            if raw[off:off + 4] != b"PK\x03\x04":
                raise bad("a damaged member header")
            lh = self._LH.unpack(raw[off:off + 30])
            start = off + 30 + lh[9] + lh[10]
            end = start + csize
            if flags & 8:                       # data descriptor after the data
                end += 16 if raw[end:end + 4] == b"PK\x07\x08" else 12
            if end > len(raw):
                raise bad("a truncated member")
            total += usize
            self.entries.append({"name": name_, "cd": raw[pos:pos + 46 + nlen + xlen + mlen], "off": off,
                                 "start": start, "end": end, "method": method, "flags": flags, "crc": crc,
                                 "csize": csize, "usize": usize})
            pos += 46 + nlen + xlen + mlen
        if total > _codes.MAX_ZIP_TOTAL_UNCOMPRESSED:
            raise DocError("bad_input", "the document is too large when unpacked")
        self.by_name = {e["name"]: e for e in self.entries}

    def names(self):
        return [e["name"] for e in self.entries]

    def read(self, name):
        e = self.by_name[name]
        data = self.raw[e["start"]:e["start"] + e["csize"]]
        if e["method"] == 8:
            try:
                data = zlib.decompressobj(-15).decompress(data, e["usize"] + 1)
            except zlib.error as exc:
                raise DocError("bad_input", "member %s does not decompress: %s" % (name, exc))
        elif e["method"] != 0:
            raise DocError("bad_input", "member %s uses compression method %d" % (name, e["method"]))
        if len(data) != e["usize"] or (zlib.crc32(data) & 0xFFFFFFFF) != e["crc"]:
            raise DocError("bad_input", "member %s is damaged (size or CRC)" % name)
        return data

    def require_hwpx(self, name="document"):
        if "mimetype" not in self.by_name or not self.read("mimetype").startswith(b"application/hwp"):
            raise DocError("bad_input", "%s is a zip but not an HWPX package (no hwp mimetype)" % name)
        if not any(SECTION_RE.match(n) for n in self.by_name):
            raise DocError("bad_input", "%s is not an HWPX package (no Contents/section*.xml)" % name)

    def rewrite(self, replace: dict) -> bytes:
        """The archive with the members in `replace` ({name: bytes}) recompressed the way they were stored and
        everything else copied as it is."""
        out, cds = bytearray(), {}
        for e in sorted(self.entries, key=lambda x: x["off"]):
            new_off = len(out)
            cd = bytearray(e["cd"])
            if e["name"] in replace:
                data = replace[e["name"]]
                crc = zlib.crc32(data) & 0xFFFFFFFF
                if e["method"] == 8:
                    co = zlib.compressobj(6, zlib.DEFLATED, -15)
                    comp = co.compress(data) + co.flush()
                else:
                    comp = data
                lh = bytearray(self.raw[e["off"]:e["start"]])
                flags = e["flags"] & ~8
                struct.pack_into("<H", lh, 6, flags)
                struct.pack_into("<III", lh, 14, crc, len(comp), len(data))
                out += lh + comp
                struct.pack_into("<H", cd, 8, flags)
                struct.pack_into("<III", cd, 16, crc, len(comp), len(data))
            else:
                out += self.raw[e["off"]:e["end"]]
            struct.pack_into("<I", cd, 42, new_off)
            cds[id(e)] = bytes(cd)
        cd_off = len(out)
        for e in self.entries:
            out += cds[id(e)]
        out += struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, len(self.entries), len(self.entries),
                           len(out) - cd_off, cd_off, len(self.comment)) + self.comment
        return bytes(out)


def _check_zip_bytes(data: bytes, names):
    """The staged archive opens, every member passes its CRC, and the members are the expected ones."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None or z.namelist() != list(names):
                raise DocError("internal", "the rewritten package did not verify; nothing was written")
    except zipfile.BadZipFile as exc:
        raise DocError("internal", "the rewritten package is not a zip (%s); nothing was written" % exc)


# ============================================================================ HWPX reading
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_TOKEN = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![A-Za-z][^>]*>"
                    r"|<(/?)([A-Za-z_][\w:.-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.S)
_XMLNS = re.compile(r"\sxmlns(?::([A-Za-z_][\w.-]*))?\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_XCHAR = re.compile(r"&(?:#[xX]([0-9A-Fa-f]{1,8})|#([0-9]{1,10})|(lt|gt|amp|quot|apos));|.", re.S)
_ENT = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}
_NEXT_TAG = re.compile(r"\s*<([A-Za-z_][\w:.-]*)")
INLINE_W = {"hp:tab": "\t", "hp:lineBreak": "\n", "hp:fwSpace": "　", "hp:nbSpace": " ", "hp:hyphen": " "}
ZERO_CTRL = {"hp:colPr", "hp:fieldBegin", "hp:fieldEnd", "hp:bookmark", "hp:pageNum", "hp:pageHiding",
             "hp:newNum", "hp:indexmark", "hp:header", "hp:footer", "hp:autoNum"}
OBJ = "￼"
#: containers whose tables are not numbered (the engine's hnc_addr.SKIP_LOCAL)
SKIP_TBL = frozenset("hp:" + k for k in ("header", "footer", "footNote", "endNote", "caption", "drawText",
                                         "masterPage"))
SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")


def _xml_char(m):
    if m.group(1) or m.group(2):
        try:
            return chr(int(m.group(1), 16) if m.group(1) else int(m.group(2)))
        except (ValueError, OverflowError):
            return m.group(0)
    if m.group(3):
        return _ENT[m.group(3)]
    return m.group(0)


def _attr(tag, name):
    m = re.search(r'\b%s\s*=\s*"([^"]*)"' % re.escape(name), tag)
    return m.group(1) if m else None


_XML_REF = re.compile(r"&(?:#x([0-9A-Fa-f]+)|#([0-9]+)|(amp|lt|gt|quot|apos));")
_XML_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _xml_unescape(v):
    """An attribute value as the document means it (place ids hash this, as the engine does)."""
    def one(m):
        if m.group(3):
            return _XML_NAMED[m.group(3)]
        try:
            return chr(int(m.group(1), 16) if m.group(1) else int(m.group(2)))
        except (ValueError, OverflowError):
            return m.group(0)
    return _XML_REF.sub(one, v)


def _namespaces(s, name="section"):
    """(canon(name) -> name with the paragraph namespace's prefix spelled hp:, the prefix to write new tags with).
    Matching goes by namespace URI, not by the literal prefix."""
    binds = {}
    for m in _XMLNS.finditer(s):
        pfx, uri = m.group(1) or "", m.group(2) if m.group(2) is not None else m.group(3)
        if binds.setdefault(pfx, uri) != uri:
            raise DocError("bad_input", "%s binds the XML prefix %r to two namespaces; the built-in reader cannot "
                           "follow that" % (name, pfx))
    hps = [p for p, u in binds.items() if u == HP_NS] or (["hp"] if "hp" not in binds else [])
    hpset = set(hps)
    cache = {}

    def canon(n):
        r = cache.get(n)
        if r is None:
            pfx, _, local = n.rpartition(":")
            if pfx in hpset:
                r = "hp:" + local
            elif pfx == "hp":
                r = "?hp:" + local            # an hp: prefix bound to some other namespace
            else:
                r = n
            cache[n] = r
        return r
    write = "hp" if "hp" in hpset else (hps[0] if hps else "hp")
    return canon, write


def _q(pfx, local):
    return "%s:%s" % (pfx, local) if pfx else local


class Para:
    __slots__ = ("si", "k", "start", "end", "parent", "cell", "top", "gp", "chars", "posmap", "xpos", "tnodes",
                 "runs", "objs", "head", "lineseg", "caption_of", "in_box", "fields")

    def __init__(self, si, k, start, head):
        self.si, self.k, self.start, self.end, self.head = si, k, start, None, head
        self.parent = None      # enclosing Para
        self.cell = None        # Cell when directly in a cell
        self.top = False
        self.gp = None
        self.chars = []         # ptext: characters, tabs, breaks, OBJ for objects
        self.posmap = []        # per ptext position: (tnode index, piece index) or None for an object
        self.xpos = []          # per ptext position: where its source starts in the section XML
        self.tnodes = []        # own <hp:t>: {"a","b","open","self","pieces":[[kind, ch, src]], "run"}
        self.runs = []          # own <hp:run>: {"a","open_end","close","b","self","cp"}
        self.objs = []          # own object tags (hp:tbl, hp:pic ...)
        self.lineseg = None     # (a, b) of the own <hp:linesegarray> (a direct child)
        self.caption_of = None
        self.in_box = False
        self.fields = []        # fields that begin here: {type, name, id, direction, b, e, after, endx}

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
    """One <hp:tbl>. `g` is its index among ALL tables (start-tag order, the engine's edit-script index);
    `addr` its public address (``t<N>`` for a top-level body table, ``<cell>/t<K>`` for a nested one), None
    for a table that has none (header, footer, note, caption, text box, an unused hp:switch branch)."""
    __slots__ = ("si", "lt", "g", "start", "end", "host", "cells", "caption", "rows", "cols", "id", "parent",
                 "dead", "addr")

    def __init__(self, si, lt, start, host, tid):
        self.si, self.lt, self.g, self.start, self.end, self.host = si, lt, None, start, None, host
        self.cells, self.caption, self.rows, self.cols, self.id = [], [], 0, 0, tid
        self.parent = None      # the Cell it sits in, None at the top level
        self.dead = False       # inside a container that has no table addresses
        self.addr = None

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


def _scan_section(s, si, canon=None):
    """Paragraphs and tables of one section XML (see the module docstring for the numbering)."""
    if canon is None:
        canon = _namespaces(s)[0]
    paras, tables = [], []
    stack = []              # [name, obj, extra]
    last = 0

    def innermost(*names):
        for fr in reversed(stack):
            if fr[0] in names:
                return fr
        return None

    def add_text(p, tn, text, base):
        for x in _XCHAR.finditer(text):
            tn["pieces"].append(["c", _xml_char(x), x.group(0)])
            p.chars.append(tn["pieces"][-1][1])
            p.posmap.append((len(p.tnodes) - 1, len(tn["pieces"]) - 1))
            p.xpos.append(base + x.start())

    for m in _TOKEN.finditer(s):
        top = stack[-1] if stack else None
        intext = top is not None and top[0] == "hp:t" and top[2] is not None
        if intext and m.start() > last:
            add_text(top[2][0], top[2][1], s[last:m.start()], last)
        last = m.end()
        if m.group(2) is None:                  # comment, CDATA, processing instruction, declaration
            if intext:
                p, tn = top[2]
                tok = m.group(0)
                if tok.startswith("<![CDATA["):
                    for j, ch in enumerate(tok[9:-3]):
                        tn["pieces"].append(["q", ch, None])
                        p.chars.append(ch)
                        p.posmap.append((len(p.tnodes) - 1, len(tn["pieces"]) - 1))
                        p.xpos.append(m.start() + 9 + j)
                else:
                    tn["pieces"].append(["z", "", tok])
            continue
        close, name, selfc = m.group(1), canon(m.group(2)), m.group(4)
        if close:
            if not any(fr[0] == name for fr in stack):
                continue
            while stack and stack[-1][0] != name:
                stack.pop()
            fr = stack.pop()
            if name in ("hp:p", "hp:tbl", "hp:tc"):
                fr[1].end = m.end()
            elif name == "hp:t" and fr[2] is not None:
                fr[2][1]["b"] = m.end()
                fr[2][1]["close"] = m.start()
            elif name == "hp:run" and fr[2] is not None:
                fr[2]["b"] = m.end()
                fr[2]["close"] = m.start()
            elif name == "hp:linesegarray" and fr[1] is not None:
                fr[1].lineseg = (fr[2], m.end())
            elif name == "hp:ctrl" and isinstance(fr[2], dict):
                fr[2]["after"] = m.end()             # the field's text starts after its begin control
            continue
        tag = m.group(0)
        if intext:                              # text-level items inside an own <hp:t>
            p, tn = top[2]
            if name in INLINE_W:
                tn["pieces"].append(["x", INLINE_W[name], tag if selfc else None])
                p.chars.append(INLINE_W[name])
                p.posmap.append((len(p.tnodes) - 1, len(tn["pieces"]) - 1))
                p.xpos.append(m.start())
            else:
                tn["pieces"].append(["z", "", tag])
            if not selfc:
                stack.append([name, None, None])
            continue
        if top is not None and top[0] == "hp:run" and top[2] is not None:      # direct children of an own run
            p = top[1]
            if name == "hp:t":
                tn = {"a": m.start(), "open": tag, "self": bool(selfc), "pieces": [], "run": top[2],
                      "b": m.end() if selfc else None, "close": None}
                p.tnodes.append(tn)
                if not selfc:
                    stack.append([name, None, (p, tn)])
                continue
            zero = name == "hp:secPr"
            if name == "hp:ctrl" and not selfc:
                nx = _NEXT_TAG.match(s, m.end())
                zero = bool(nx) and canon(nx.group(1)) in ZERO_CTRL
            if not zero:
                p.chars.append(OBJ)
                p.posmap.append(None)
                p.xpos.append(m.start())
                p.objs.append(name)
            # fall through: the element itself is scanned for nested structure
        if name in ("hp:fieldBegin", "hp:fieldEnd"):
            fr_p = innermost("hp:p")
            if fr_p is not None:
                _field_mark(s, m, name, tag, selfc, fr_p[1], stack, paras)
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
        elif name == "hp:linesegarray" and top is not None and top[0] == "hp:p":
            if selfc:
                top[1].lineseg = (m.start(), m.end())
            else:
                stack.append([name, top[1], m.start()])
        elif name == "hp:run":
            fr_p = innermost("hp:p")
            if fr_p is not None and stack[-1] is fr_p:
                run = {"a": m.start(), "open_end": m.end(), "self": bool(selfc), "cp": _attr(tag, "charPrIDRef"),
                       "b": m.end() if selfc else None, "close": None}
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
            t.dead = any(fr[0] in SKIP_TBL or fr[2] == "dead" for fr in stack)
            fr_tc = innermost("hp:tc")
            t.parent = fr_tc[1] if fr_tc is not None else None
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
        elif name == "hp:switch" and not selfc:
            stack.append([name, {"case": False, "has_case": _switch_has_case(s, m)}, None])
        elif name in ("hp:case", "hp:default") and not selfc and top is not None and top[0] == "hp:switch":
            sw = top[1]
            # layout reads the first hp:case, else hp:default (hnc_layout._run_children)
            dead = sw["case"] if name == "hp:case" else sw["has_case"]
            if name == "hp:case":
                sw["case"] = True
            stack.append([name, None, "dead" if dead else None])
        elif name == "hp:caption":
            if selfc:
                continue
            fr_t = innermost("hp:tbl", "hp:pic", "hp:p")
            stack.append([name, fr_t[1] if fr_t is not None and fr_t[0] == "hp:tbl" else None, None])
        elif not selfc:
            stack.append([name, None, None])
    return paras, tables


_DIRECTION = re.compile(r"<[\w:.-]*stringParam\b[^>]*\bname=\"Direction\"[^>]*>(.*?)</", re.S)
_COMMAND = re.compile(r"<[\w:.-]*stringParam\b[^>]*\bname=\"Command\"[^>]*>(.*?)</", re.S)


def _switch_has_case(s, m):
    """Whether the hp:switch opened by match m has an hp:case (then its hp:default is not what layout uses)."""
    raw = m.group(2)
    pfx = raw[:raw.index(":") + 1] if ":" in raw else ""
    pat = re.compile(r"<(/?)%s(switch|case)\b" % re.escape(pfx))
    depth = 0
    for x in pat.finditer(s, m.end()):
        if x.group(2) == "switch":
            if x.group(1):
                if depth == 0:
                    return False
                depth -= 1
            else:
                depth += 1
        elif depth == 0 and not x.group(1):
            return True
    return False


def _field_mark(s, m, name, tag, selfc, p, stack, paras):
    """Record a field's begin (in the paragraph that holds it) and its end (ptext positions, XML offsets)."""
    if name == "hp:fieldBegin":
        direction = command = None
        if not selfc:
            close = s.find("</%s" % m.group(2), m.end())
            end_at = close if close >= 0 else len(s)
            d = _DIRECTION.search(s, m.end(), end_at)
            if d:
                direction = "".join(_xml_char(x) for x in _XCHAR.finditer(d.group(1)))
            c = _COMMAND.search(s, m.end(), end_at)
            if c:
                command = "".join(_xml_char(x) for x in _XCHAR.finditer(c.group(1)))
        f = {"type": _attr(tag, "type"), "name": _xml_unescape(_attr(tag, "name") or ""), "id": _attr(tag, "id"),
             "direction": direction, "command": command, "b": len(p.chars), "e": None, "startx": m.start(),
             "after": m.end(), "endx": None, "para": p}
        p.fields.append(f)
        for fr in reversed(stack):              # the control around it, when there is one
            if fr[0] == "hp:ctrl":
                fr[2] = f
                break
            if fr[0] in ("hp:run", "hp:p"):
                break
    else:
        ref = _attr(tag, "beginIDRef")
        for q in reversed(paras):
            f = next((f for f in q.fields if f["id"] == ref and f["e"] is None), None)
            if f is not None:
                if q is p:
                    f["e"], f["endx"] = len(p.chars), m.start()
                else:
                    f["e"], f["end_para"] = "elsewhere", p            # a field across paragraphs
                break


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _header_info(data: bytes):
    """styles, paraPr heading kinds, bold charPrs and font faces of header.xml (namespace-aware)."""
    styles, heads, bold, fonts = {}, {}, set(), []
    try:
        root = ET.fromstring(data) if data else None
    except ET.ParseError:
        root = None
    if root is None:
        return styles, heads, bold, fonts
    for el in root.iter():
        t = _local(el.tag)
        if t == "style":
            styles[el.get("id")] = {"name": el.get("name"), "engName": el.get("engName"), "type": el.get("type"),
                                    "paraPr": el.get("paraPrIDRef"), "charPr": el.get("charPrIDRef")}
        elif t == "paraPr":
            for x in el.iter():
                if _local(x.tag) == "heading" and x.get("type") and (x.get("level") or "").isdigit():
                    heads[el.get("id")] = (x.get("type"), int(x.get("level")))
                    break
        elif t == "charPr":
            if any(_local(x.tag) == "bold" for x in el.iter()):
                bold.add(el.get("id"))
        elif t == "font":
            face = el.get("face")
            if face and face not in fonts:
                fonts.append(face)
    return styles, heads, bold, fonts


class Doc:
    """A parsed .hwpx (or the engine's .hwpx of a .hwp), immutable once built: sections, paragraphs, tables,
    headings. `raw` are the exact .hwpx bytes it was parsed from; `sha` is the sha256 of the file's own bytes."""

    def __init__(self, path, raw: bytes, fmt="hwpx", src_raw=None):
        src_raw = raw if src_raw is None else src_raw
        self.path, self.format, self.raw = Path(path), fmt, raw
        self.sha = _sha(src_raw)
        self.rev = self.sha[:12]
        self.zip = _Zip(raw, Path(path).name)
        self.zip.require_hwpx(Path(path).name)
        self.section_names = sorted((n for n in self.zip.names() if SECTION_RE.match(n)),
                                    key=lambda n: int(SECTION_RE.match(n).group(1)))
        try:
            self.secs = [self.zip.read(n).decode("utf-8") for n in self.section_names]
            hdr = self.zip.read("Contents/header.xml") if "Contents/header.xml" in self.zip.by_name else b""
        except UnicodeDecodeError as exc:
            raise DocError("bad_input", "a section of %s is not UTF-8 (%s)" % (Path(path).name, exc))
        self.canon, self.pfx = [], []
        self.paras, self.tables, self.sec_paras, self.sec_tables = [], [], [], []
        for si, s in enumerate(self.secs):
            canon, pfx = _namespaces(s, self.section_names[si])
            self.canon.append(canon)
            self.pfx.append(pfx)
            ps, ts = _scan_section(s, si, canon)
            self.sec_paras.append(ps)
            self.sec_tables.append(ts)
            self.paras.extend(ps)
            self.tables.extend(ts)
        self.top = [p for p in self.paras if p.top]
        for i, p in enumerate(self.top):
            p.gp = i
        self.cell_table = {}
        for g, t in enumerate(self.tables):
            t.g = g
            if not t.rows and t.cells:
                t.rows = max((c.row or 0) + c.rs for c in t.cells)
            if not t.cols and t.cells:
                t.cols = max((c.col or 0) + c.cs for c in t.cells)
            for c in t.cells:
                self.cell_table[id(c)] = t
        # public table addresses (doc-core-api.md, ruling 2026-11-19): top-level body tables count t0, t1, ...
        # through all sections; a nested table is <its cell>/t<K>, K counting the tables in that cell
        top, inner = 0, {}
        for t in self.tables:
            if t.dead:
                continue
            if t.parent is None:
                t.addr = "t%d" % top
                top += 1
                continue
            host = self.cell_table.get(id(t.parent))
            c = t.parent
            if host is None or host.addr is None or c.row is None or c.col is None:
                continue
            k = inner.get(id(c), 0)
            inner[id(c)] = k + 1
            t.addr = "%s/r%d/c%d/t%d" % (host.addr, c.row, c.col, k)
        self.by_addr = {t.addr: t for t in self.tables if t.addr}
        self.top_tables = [t for t in self.tables if t.addr and t.parent is None]
        self.styles, self.para_heading, self.bold_cp, self.fonts = _header_info(hdr)
        self.meta_lock = threading.Lock()
        self.meta_done = False
        self.meta_errors = []
        self.layout = None
        self.engine_headings = None     # None: no engine analysis (not run, or it failed); [] : it found none
        self.engine_places = None
        self.engine_outline = None      # places of the engine's outline(known=...), when it has that
        self.page_starts = None         # [flow para index of page n's first paragraph]
        self._efile = None

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

    def table_of(self, cell):
        return self.cell_table.get(id(cell))

    def page_of(self, p):
        if not self.page_starts:
            return None
        gp = self.top_of(p).gp
        return bisect.bisect_right(self.page_starts, gp)

    def page_count(self):
        n = (self.layout or {}).get("pages")
        return n if isinstance(n, int) and not isinstance(n, bool) else None

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

    def engine_file(self) -> Path:
        """A private file holding exactly `raw`, for the engine: it reads the bytes this Doc was parsed from,
        never the live file (which may have changed since)."""
        f = _scratch_sub("snap") / ("%s.hwpx" % _sha(self.raw)[:24])
        try:
            if f.stat().st_size == len(self.raw):
                return f
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".hwpx", dir=str(f.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(self.raw)
            os.replace(tmp, f)
        finally:
            _unlink(tmp)
        return f


_DOCS = {}
_DOCS_LOCK = threading.Lock()
_DOCS_MAX = 8
_HWP_LOCK = threading.Lock()


def _hwp_to_hwpx(e, data: bytes, sha: str) -> bytes:
    """The engine's .hwpx of a .hwp's bytes (converted once per content, in the private scratch folder)."""
    d = _scratch_sub("hwp")
    conv = d / ("%s.hwpx" % sha[:24])
    with _HWP_LOCK:
        if not conv.is_file():
            snap = d / ("%s.hwp" % sha[:24])
            snap.write_bytes(data)
            tmp = d / ("%s.%d.tmp.hwpx" % (sha[:24], threading.get_ident()))
            try:
                r = e.call("to_hwpx", str(snap), str(tmp))
                if not r.get("ok"):
                    raise _engine_error(r, "to_hwpx")
                lossy = ["%s x%d not converted" % (k, v) for k, v in (r.get("unsupported") or {}).items()]
                conv.with_suffix(".json").write_text(json.dumps(lossy), encoding="utf-8")
                os.replace(tmp, conv)
            finally:
                _unlink(tmp)
                _unlink(snap)
    return conv.read_bytes()


def _load(path, *, meta=True):
    """The Doc of a file's current bytes (cached by path, content and engine). The rev it carries is the rev of
    exactly the bytes it parsed. With meta, the engine's layout and form analysis are loaded once per Doc, so
    every function resolves addresses against the same metadata whatever ran before. meta="layout" loads only
    the layout (render and geometry take page numbers, not addresses: no outline/analyze for a preview copy)."""
    p = _need_file(path)
    data = _read_bytes(p)
    fmt = _format_of_bytes(data[:8], p)
    if fmt == "md":
        raise DocError("bad_input", "a markdown file is not a document here; use new() or convert()")
    sha = _sha(data)
    e = _engine()
    key = (str(p), sha, id(e) if e is not None else None)
    with _DOCS_LOCK:
        d = _DOCS.get(key)
    if d is None:
        if fmt == "hwp":
            if e is None:
                raise _unavailable(".hwp files need the HWP engine; only .hwpx is supported without it",
                                   "hwp_binary_unsupported")
            d = Doc(p, _hwp_to_hwpx(e, data, sha), "hwp", src_raw=data)
        else:
            d = Doc(p, data, "hwpx")
        with _DOCS_LOCK:
            d = _DOCS.setdefault(key, d)
            while len(_DOCS) > _DOCS_MAX:
                _DOCS.pop(next(iter(_DOCS)))
    if meta and e is not None:
        _ensure_meta(d, e, places=meta != "layout")
    return d


def _set_layout(doc, layout):
    doc.layout = layout
    doc.page_starts = [s["para"] for s in layout.get("page_starts") or []
                       if isinstance(s, dict) and isinstance(s.get("para"), int) and s["para"] >= 0] or [0]


def _ensure_meta(d, e, places=True):
    """Layout (pages) and form analysis (headings, places) from the engine, once per Doc. A transient failure
    (timeout, worker gone) is retried by the next call; any other failure is kept, and the Doc then uses the
    built-in analysis, the same for every caller. places=False: the layout only (the rest waits for a caller
    that resolves addresses)."""
    if d.meta_done or (not places and d.layout is not None):
        return
    with d.meta_lock:
        if d.meta_done or (not places and d.layout is not None):
            return
        f = str(d.engine_file())
        transient = False
        if d.layout is None:
            r = e.call("pages", f)
            if r.get("ok"):
                _set_layout(d, r)
            else:
                transient |= bool((r.get("error") or {}).get("retryable"))
                if places:
                    d.meta_errors.append({"fn": "pages", **(r.get("error") or {})})
        if not places:
            return
        if d.engine_places is None:
            # an engine whose outline takes known=[ids] (doc-core-api.md, amendment 2026-11-19 05:50Z) lists the
            # seats this module filled; one without it (or without outline) is asked for analyze() as before
            o = e.call("outline", f, known=sorted(_known_ids(d)))
            if o.get("ok") and isinstance(o.get("places"), list):
                d.engine_outline = [x for x in o["places"] if isinstance(x, dict) and isinstance(x.get("at"), str)]
            a = e.call("analyze", f)
            if a.get("ok") and isinstance(a.get("places", []), list):
                d.engine_places = [x for x in a.get("places") or [] if isinstance(x, dict)]
                d.engine_headings = [x for x in a.get("headings") or [] if isinstance(x, dict)]
            else:
                transient |= bool((a.get("error") or {}).get("retryable"))
                d.meta_errors.append({"fn": "analyze", **(a.get("error") or {})})
        d.meta_done = not transient


# ============================================================================ addresses
_ADDR = re.compile(r"^(?:p(?P<p>\d+)(?P<rng>:\d+-\d+)?"
                   r"|t(?P<t>\d+)(?P<nest>(?:/r\d+/c\d+/t\d+)*)"
                   r"(?:/r(?P<r>\d+)(?:/c(?P<c>\d+)(?:/p(?P<cp>\d+)(?P<crng>:\d+-\d+)?)?)?)?"
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
        t = {"t": int(g["t"])}
        if g["nest"]:       # t0/r1/c2/t0: the first table in cell (1, 2) of t0
            t["nest"] = [tuple(int(v) for v in x) for x in re.findall(r"/r(\d+)/c(\d+)/t(\d+)", g["nest"])]
        if g["r"] is None:
            return {"kind": "table", **t}
        if g["c"] is None:
            return {"kind": "row", **t, "r": int(g["r"])}
        if g["cp"] is None:
            return {"kind": "cell", **t, "r": int(g["r"]), "c": int(g["c"])}
        return {"kind": "cellpara", **t, "r": int(g["r"]), "c": int(g["c"]), "k": int(g["cp"]),
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
        t = doc.table_of(p.cell)
        if t is None or t.addr is None:
            return None
        return "%s/r%d/c%d/p%d" % (t.addr, p.cell.row, p.cell.col, p.cell.paras.index(p))
    return None


def cell_address(t, c):
    return "%s/r%d/c%d" % (t.addr, c.row, c.col)


def _table_path(doc, a, addr):
    """The Table an address's t<N>[/r/c/t<K>...] part names; bad_address with candidates when none."""
    tops = doc.top_tables
    if a["t"] >= len(tops):
        raise DocError("bad_address", "the document has %d top-level tables" % len(tops), at=addr,
                       candidates=[t.addr for t in tops[:8]])
    t = tops[a["t"]]
    for r, c, k in a.get("nest", ()):
        cell = t.at(r, c)
        if cell is None:
            raise DocError("bad_address", "table %s has no cell at row %d, column %d" % (t.addr, r, c), at=addr,
                           candidates=[cell_address(t, x) for x in t.row_cells(min(r, max(t.rows - 1, 0)))][:8])
        inner = [x for x in doc.tables if x.parent is cell and x.addr]
        if k >= len(inner):
            raise DocError("bad_address", "cell %s holds %d tables" % (cell_address(t, cell), len(inner)), at=addr,
                           candidates=[x.addr for x in inner] or [cell_address(t, cell)])
        t = inner[k]
    return t


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


#: one leading enumerator of a heading (doc-core-api.md, "Label lines and heading keys")
_ENUMERATOR = re.compile(r"\(?\s*(?:[\u2160-\u216B]+|[IVX]+|\d+(?:\.\d+)*|[가나다라마바사아자차카타파하])\s*[.)]\s+")


def _heading_key(text):
    """A heading's key: its text without leading enumerators, letters and digits only."""
    rest = (text or "").strip()
    while True:
        m = _ENUMERATOR.match(rest)
        if not m:
            break
        rest = rest[m.end():]
    return "".join(ch for ch in rest if ch.isalnum())


def _cell_pid(t, c):
    return place_id("cell", t.id or t.addr, c.row, c.col)


def _known_ids(doc):
    """The place ids this module carried into these exact bytes (its lineage cache)."""
    return {x["id"] for x in (_lineage_get(doc.sha) or [])}


def _cell_label(t, c, known=()):
    """A cell seat's label: the text of the cell to its left, else of the cell above, never a seat's (an empty
    cell, or a filled one whose id is known); at most 40 characters."""
    for rr, cc in ((c.row, c.col - 1), (c.row - 1, c.col)):
        lab = t.at(rr, cc) if rr >= 0 and cc >= 0 else None
        if lab is None or lab is c or _cell_pid(t, lab) in known:
            continue
        text = _cell_text(lab).strip()
        if text:
            return text if len(text) <= 40 else None
    return None


def _discover(doc):
    """Fill seats found in this document: [{id, at, label, kind, para, cell?, table?}].

    With the engine: its analyze() places. Without: an empty cell labelled by the cell to its left or above,
    and the blank paragraph right under a heading. Seats that share an id (the same label twice) are all kept,
    each as ``<id>@<at>``; the bare id then names no seat (resolve() refuses it with the candidates)."""
    out = []
    known = _known_ids(doc)
    if doc.engine_outline is not None:
        for pl in doc.engine_outline:
            try:
                r = _resolve(doc, pl["at"], ("para", "cell", "cellpara"))
            except DocError:
                continue
            rec = {"id": pl.get("id"), "at": pl["at"], "label": pl.get("label"), "kind": pl.get("kind"),
                   "para": r.get("para") or (r.get("paras") or [None])[0]}
            if r["kind"] == "cell":
                c = r["cell"]
                if not c.paras or any(q.objs for q in c.paras):
                    continue
                rec.update(table=r["table"], cell=c, para=c.paras[0], at=cell_address(r["table"], c))
            elif rec["para"] is None:
                continue
            out.append(rec)
    elif doc.engine_places is not None:
        for pl in doc.engine_places:
            si = doc.section_names.index(pl["section"]) if pl.get("section") in doc.section_names else 0
            if not isinstance(pl.get("id"), str) or not pl["id"]:
                continue
            rec = {"id": pl["id"], "label": pl.get("label"), "kind": pl.get("kind")}
            if pl.get("kind") in ("cell", "cell_field") and _is_int(pl.get("table")):
                ts = doc.sec_tables[si]
                if not 0 <= pl["table"] < len(ts) or not (_is_int(pl.get("row")) and _is_int(pl.get("col"))):
                    continue
                t = ts[pl["table"]]
                c = t.at(pl["row"], pl["col"])
                if c is None or not c.paras or (pl["kind"] == "cell" and any(q.objs for q in c.paras)):
                    continue                    # a cell holding a table or picture is not a seat fill can type in
                rec.update(table=t, cell=c)
                idx = pl.get("index")
                p = doc.sec_paras[si][idx] if _is_int(idx) and 0 <= idx < len(doc.sec_paras[si]) else c.paras[0]
                rec["para"] = p
                rec["at"] = (cell_address(t, c) if t.addr else None) if pl["kind"] == "cell" else para_address(doc, p)
            else:
                idx = pl.get("index")
                if not _is_int(idx) or not 0 <= idx < len(doc.sec_paras[si]):
                    continue
                p = doc.sec_paras[si][idx]
                rec["para"] = p
                rec["at"] = para_address(doc, p)
            if rec["at"]:
                out.append(rec)
    else:
        for t in doc.tables:
            if t.addr is None:
                continue
            for c in t.cells:
                if any(p.objs for p in c.paras) or not c.paras:
                    continue
                if _cell_text(c).strip() and _cell_pid(t, c) not in known:
                    continue            # a text cell: a seat only when this module filled it
                label = _cell_label(t, c, known)
                if not label or not _heading_key(label):
                    continue
                out.append({"id": None, "at": cell_address(t, c), "label": label,
                            "kind": "cell", "table": t, "cell": c, "para": c.paras[0]})
        heads = _headings(doc)
        hk = {h["para"].gp for h in heads}
        for h in heads:
            k = h["para"].gp + 1
            if k < len(doc.top) and k not in hk and not doc.top[k].text.strip() and not doc.top[k].objs:
                pid = _heading_key(h["text"])
                if pid:
                    out.append({"id": pid, "at": "p%d" % k, "label": h["text"], "kind": "body", "para": doc.top[k]})
        for p in doc.paras:                     # blank label lines ("성명: ", doc-core-api.md)
            ll = label_line(p.text) if not p.objs else None
            at = para_address(doc, p) if ll and ll["blank"] else None
            if at:
                out.append({"id": ll["key"], "at": at, "label": ll["label"],
                            "kind": "cell_field" if p.cell is not None else "cover_field", "para": p})
    have = {r["at"] for r in out}
    for f in _click_fields(doc):
        p = f["para"]
        at = para_address(doc, p)
        if at is None or f["e"] is None or not isinstance(f["e"], int):
            continue
        if doc.engine_places is not None and at in have and not any(
                r.get("field_id") == f["id"] for r in out if r["at"] == at):
            continue                            # the engine already lists a seat there
        rec = {"id": None, "at": at, "label": f["direction"] or f["name"], "kind": "field", "para": p, "field": f,
               "field_id": f["id"]}
        if p.cell is not None:
            rec.update(cell_of=p.cell)
        out.append(rec)
    _identity_ids(doc, out)
    count = {}
    for r in out:
        count[r["id"]] = count.get(r["id"], 0) + 1
    for r in out:
        if count[r["id"]] > 1:
            r["shared"] = r["id"]
            r["id"] = "%s@%s" % (r["id"], r["at"])
    return out


def _label_char(ch, first=False):
    if "\uac00" <= ch <= "\ud7a3" or ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
        return True
    return not first and ch in (" ", "\u00b7")


def label_line(text):
    """The label line in `text` (doc-core-api.md, "Label lines and heading keys"): {"label", "key", "at",
    "value", "blank"} where `at` is the position after the colon and the white space that follows it; None when
    the text is not a label line."""
    lead = len(text) - len(text.lstrip())
    cut = min((i for i in (text.find(":", lead), text.find("\uff1a", lead)) if i >= 0), default=-1)
    if cut < 0:
        return None
    label = text[lead:cut].rstrip()
    if not 1 <= len(label) <= 15 or not _label_char(label[0], True) or not all(_label_char(c) for c in label):
        return None
    at = cut + 1
    while at < len(text) and text[at].isspace():
        at += 1
    value = text[at:].strip()
    return {"label": label, "key": "".join(label.split()), "at": at, "value": value,
            "blank": not value.replace("_", "").strip()}


def place_id(*parts):
    """A place id: the first 12 hex of the sha256 of its identity parts joined by NUL (the engine's
    hnc_addr.place_id hashes kind, label and ordinal the same way)."""
    return hashlib.sha256("\0".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:12]


def _identity_ids(doc, recs):
    """Give each seat the id of an identity that filling it cannot change (ruling 2026-11-19):
    cell ``place_id("cell", <hp:tbl @id, else its address>, row, col)``; body seat ``place_id("body", heading
    text, n)``, n counting the earlier headings with that text; label line ``place_id("field", label, n)``, n
    counting the earlier lines with that label, filled or not; click-here field ``place_id("click", name or
    prompt, n)``, n counting the earlier click-here fields with that name; anything else
    ``place_id(kind, label, n)`` over the seats of that kind and label."""
    heads = _headings(doc)
    head_at, seen = {}, {}
    for h in heads:
        n = seen.get(h["text"], 0)
        seen[h["text"]] = n + 1
        head_at[h["para"].gp] = (h["text"], n)
    gps = sorted(head_at)
    lines, seen = {}, {}
    for p in doc.paras:
        ll = label_line(p.text)
        if ll:
            lab = ll["key"]
            n = seen.get(lab, 0)
            seen[lab] = n + 1
            lines[id(p)] = (lab, n)
    clicks, seen = {}, {}
    for f in _click_fields(doc):
        lab = f["name"] or f["direction"] or ""
        n = seen.get(lab, 0)
        seen[lab] = n + 1
        clicks[id(f)] = (lab, n)
    other = {}
    for r in recs:
        kind, p = r.get("kind"), r.get("para")
        if kind == "cell" and r.get("cell") is not None:
            t, c = r["table"], r["cell"]
            r["id"] = place_id("cell", t.id or t.addr, c.row, c.col)
        elif kind == "field" and r.get("field") is not None:
            r["id"] = place_id("click", *clicks[id(r["field"])])
        elif kind in ("cover_field", "cell_field") and p is not None and id(p) in lines:
            r["id"] = place_id("field", *lines[id(p)])
        elif kind == "body" and p is not None and p.top and gps and gps[0] < p.gp:
            r["id"] = place_id("body", *head_at[gps[bisect.bisect_left(gps, p.gp) - 1]])
        else:
            key = (kind, r.get("label") or "")
            n = other.get(key, 0)
            other[key] = n + 1
            r["id"] = place_id(kind or "place", key[1], n)


def _click_fields(doc):
    return [f for p in doc.paras for f in p.fields if (f.get("type") or "").upper() == "CLICK_HERE"]


_FORM_CTRL = re.compile(r"<(?:[\w.-]+:)?(checkBtn|radioBtn|comboBox|listBox|edit|scrollBar)\b")


def _places_status(doc):
    """(complete, reasons): whether outline's places cover every kind of seat this document has."""
    why = []
    if _engine() is not None and doc.engine_places is None:
        errs = "; ".join("%s: %s" % (x.get("fn"), x.get("message")) for x in doc.meta_errors) or "not run"
        why.append("the engine's form analysis failed (%s); places come from the built-in rules" % errs)
    if doc.engine_places is None:
        kinds = sorted({m.group(1) for sec in doc.secs for m in _FORM_CTRL.finditer(sec)})
        if kinds:
            why.append("form controls (%s) are not listed without the engine" % ", ".join(kinds))
    for f in _click_fields(doc):
        if not isinstance(f["e"], int):
            why.append("a click-here field (%s) runs across paragraphs" % (f["name"] or f["id"]))
        elif para_address(doc, f["para"]) is None:
            why.append("a click-here field (%s) sits in a caption or text box" % (f["name"] or f["id"]))
    return not why, why


def _cache_dir() -> Path:
    raw = (os.environ.get(CACHE_ENV) or "").strip()
    if raw:
        return Path(raw)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "rigorloom" / "doc-core"


def _lineage_get(sha):
    """The place ids an edit by this module carried into the document with these exact bytes, or None."""
    if sha in _LINEAGE:
        return _LINEAGE[sha]
    try:
        data = json.loads((_cache_dir() / "places" / ("%s.json" % sha)).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    data = [x for x in data if isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("at"), str)]
    _LINEAGE[sha] = data
    return data


def _lineage_put(sha, places):
    _LINEAGE[sha] = places
    try:
        d = _cache_dir() / "places"
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".json", dir=str(d))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(places, f, ensure_ascii=False)
            os.replace(tmp, d / ("%s.json" % sha))
        finally:
            _unlink(tmp)
        _prune_lineage(d)
    except OSError:
        pass                                # a cache: without it the ids fall back to discovery


LINEAGE_MAX_AGE_S = 90 * 86400.0    #: lineage entries older than this are dropped
LINEAGE_MAX = 5000                  #: and only this many of the newest are kept


def _prune_lineage(d: Path):
    try:
        ents = []
        for x in d.glob("*.json"):
            try:
                ents.append((x.stat().st_mtime, x))
            except OSError:
                pass
        ents.sort(reverse=True)
        cut = time.time() - LINEAGE_MAX_AGE_S
        for k, (mt, x) in enumerate(ents):
            if k >= LINEAGE_MAX or mt < cut:
                try:
                    x.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _seat_value(doc, rec):
    kind = rec.get("kind")
    if rec.get("cell") is not None and kind == "cell":
        return _cell_text(rec["cell"])
    p = rec.get("para")
    if p is None:
        return ""
    if kind == "field" and rec.get("field") is not None and isinstance(rec["field"]["e"], int):
        return "".join(c for c in p.chars[rec["field"]["b"]:rec["field"]["e"]] if c != OBJ)
    if kind in ("cover_field", "cell_field"):
        ll = label_line(p.text)
        return ll["value"] if ll else ""
    return p.text


def _places(doc):
    """Fill seats: [{id, at, label, kind, value, filled, para, cell?, table?}].

    Ids are stable: when this module wrote the document (edit, fill), the seats of the document it started
    from are carried over by the exact remap (so a filled seat keeps its id and shows its value, and editing
    some other label never moves an id to another seat). Seats it finds that are not carried over get their
    discovered id."""
    disc = _discover(doc)
    carried = _lineage_get(doc.sha) or []
    out, ids, ats = [], set(), set()
    by_at = {(r["at"], r.get("field_id")): r for r in disc}
    for c in carried:
        if c["id"] in ids or (c["at"], c.get("field_id")) in ats:
            continue
        try:
            r = _resolve(doc, c["at"], ("para", "cell", "cellpara"))
        except DocError:
            continue
        cur = by_at.get((c["at"], c.get("field_id")), {})
        if c.get("field_id") is not None and not cur:
            continue                            # the field is gone
        rec = {"id": c["id"], "at": c["at"], "label": cur.get("label", c.get("label")),
               "kind": c.get("kind") or cur.get("kind"), "para": r.get("para") or (r.get("paras") or [None])[0],
               "carried": True}
        if cur.get("field") is not None:
            rec.update(field=cur["field"], field_id=cur["field_id"], para=cur["para"])
        if r.get("cell") is not None and r["kind"] == "cell":
            rec.update(cell=r["cell"], table=r["table"], para=r["cell"].paras[0] if r["cell"].paras else None)
        out.append(rec)
        ids.add(rec["id"])
        ats.add((rec["at"], rec.get("field_id")))
    for r in disc:
        if (r["at"], r.get("field_id")) in ats:
            continue
        if r["id"] in ids:
            r = dict(r, id="%s@%s" % (r["id"], r["at"]))
        out.append(r)
        ids.add(r["id"])
        ats.add((r["at"], r.get("field_id")))
    for r in out:
        r["value"] = _seat_value(doc, r)
        if r.get("kind") == "cover_placeholder":
            r["filled"] = bool(r.get("label")) and r["label"] not in (r["para"].text if r.get("para") else "")
        elif r.get("kind") == "field":
            r["filled"] = bool(r["value"].strip()) and r["value"] != (r.get("field") or {}).get("direction")
        else:
            r["filled"] = bool(r["value"].strip())
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
                           at=addr, range=[0, len(res["para"].text)])
        res["range"] = (x, y)
    return res


def _nearby(doc):
    """Something real to offer when an address does not resolve: places, headings, else the paragraph range."""
    out = []
    try:
        out += ["place:%s" % pl["id"] for pl in _places(doc)][:3]
    except DocError:
        pass
    out += ['h:"%s"' % h["text"] for h in _headings(doc)][:3]
    if doc.tables:
        out.append("t0")
    if doc.top:
        out += ["p0", "p%d" % (len(doc.top) - 1)] if len(doc.top) > 1 else ["p0"]
    return out


def resolve(doc, addr, *, allow=None):
    """An address -> {"kind", "para"|"table"|"cell"|"paras"|"page", ...}. Unresolved: DocError bad_address,
    whose candidates are never empty while the document has anything to offer."""
    try:
        return _resolve(doc, addr, allow)
    except DocError as exc:
        if exc.code == "bad_address" and not exc.extra.get("candidates"):
            exc.extra["candidates"] = _nearby(doc)
        raise


def _resolve(doc, addr, allow):
    a = addr if isinstance(addr, dict) and "kind" in addr else parse_address(addr)
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
        t = _table_path(doc, a, addr)
        if kind == "table":
            return {"kind": "table", "table": t, "paras": [p for c in t.cells for p in c.paras]}
        if a["r"] >= t.rows:
            raise DocError("bad_address", "table %s has %d rows" % (t.addr, t.rows), at=addr,
                           candidates=["%s/r%d" % (t.addr, r) for r in range(max(0, t.rows - 3), t.rows)])
        if kind == "row":
            return {"kind": "row", "table": t, "row": a["r"],
                    "paras": [p for c in t.row_cells(a["r"]) for p in c.paras]}
        c = t.at(a["r"], a["c"])       # a covered (merged-away) coordinate answers at its anchor cell
        if c is None:
            raise DocError("bad_address", "table %s has no cell at row %d, column %d" % (t.addr, a["r"], a["c"]),
                           at=addr, candidates=[cell_address(t, x) for x in t.row_cells(a["r"])]
                           or [cell_address(t, x) for x in t.cells[:5]])
        if kind == "cell":
            return {"kind": "cell", "table": t, "cell": c, "paras": list(c.paras)}
        if a["k"] >= len(c.paras):
            raise DocError("bad_address", "cell %s has %d paragraphs" % (cell_address(t, c), len(c.paras)),
                           at=addr, candidates=["%s/p%d" % (cell_address(t, c), i) for i in range(len(c.paras))])
        p = c.paras[a["k"]]
        return _with_range({"kind": "para", "para": p, "paras": [p], "table": t, "cell": c}, a, addr)
    if kind == "heading":
        heads = _headings(doc)
        want = a["text"]
        exact = [h for h in heads if h["text"] == want]
        if not exact:
            exact = [h for h in heads if h["text"].startswith(want)]
        if not exact:   # numbering and spaces aside
            nk = _heading_key(want)
            exact = [h for h in heads if nk and _heading_key(h["text"]) == nk]
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
                if pl.get("cell") is not None and pl.get("kind") == "cell":
                    out.update(cell=pl["cell"], table=pl["table"], paras=list(pl["cell"].paras))
                return out
        for t in doc.tables:                # place:<id> resolves for every cell, listed or not (amendment 05:50Z)
            if t.addr is None:
                continue
            for c in t.cells:
                if c.paras and c.row is not None and _cell_pid(t, c) == a["id"]:
                    pl = {"id": a["id"], "at": cell_address(t, c), "label": _cell_label(t, c, _known_ids(doc)),
                          "kind": "cell", "table": t, "cell": c, "para": c.paras[0], "value": _cell_text(c)}
                    pl["filled"] = bool(pl["value"].strip())
                    return {"kind": "place", "place": pl, "para": c.paras[0], "paras": list(c.paras),
                            "cell": c, "table": t}
        shared = [pl["id"] for pl in pls if pl.get("shared") == a["id"]]
        if shared:
            raise DocError("bad_address", "%d fill places are labelled %r; name one" % (len(shared), a["id"]),
                           at=addr, candidates=["place:%s" % i for i in shared])
        by_label = {}
        for pl in pls:
            by_label.setdefault(pl.get("label") or "", []).append(pl["id"])
        near = [i for lab in difflib.get_close_matches(a["id"], [x for x in by_label if x], n=5, cutoff=0.3)
                for i in by_label[lab]]
        raise DocError("bad_address", "no fill place %r (place ids come from outline().places)" % a["id"],
                       at=addr, candidates=["place:%s" % i for i in (near or _cands_near([pl["id"] for pl in pls],
                                                                                       a["id"]))][:8])
    return {"kind": "page", "page": a["page"], "paras": []}


# ============================================================================ read side
def _engine_info():
    d, why = _engine_dir()
    return {"available": d is not None, **({"reason": why} if d is None else {})}


#: The engine's note for a font it measured with another face (hwp-engine, 2026-11):
#: "font 함초롬바탕 measured with the system face Noto Serif CJK KR (no Hancom font installed)".
_MEASURED_WITH = re.compile(r"^font (?P<want>.+?) measured with the system face (?P<got>.+?)(?: \(.*\))?$")


def _fonts(doc, approx=None):
    used = []
    for f in doc.fonts:
        if f not in used:
            used.append(f)
    sub, seen = [], {}
    for a in approx or []:
        a = str(a)
        m = _MEASURED_WITH.match(a)
        if "→" in a:
            w, g = (x.strip() for x in a.split("→", 1))
        elif m:
            w, g = m.group("want").strip(), m.group("got").strip()
        elif a in used:
            w, g = a, None
        else:
            continue
        # The engine names a font twice (the note, then the bare name): one entry, with the face if known.
        if w in seen:
            if g and not seen[w]["got"]:
                seen[w]["got"] = g
            continue
        seen[w] = {"want": w, "got": g or None}
        sub.append(seen[w])
    return {"used": used, "substituted": sub}


@_api
def open(path):  # noqa: A001 - the doc_core verb
    """{rev, format, pages?, sections, fonts: {used, substituted}, engine}"""
    doc = _load(path)
    out = {"rev": doc.rev, "format": doc.format, "sections": len(doc.secs), "paragraphs": len(doc.top),
           "tables": len(doc.tables), "engine": _engine_info()}
    lay = getattr(doc, "layout", None)
    if lay:
        out["pages"] = lay.get("pages")
    out["fonts"] = _fonts(doc, lay.get("approx") if lay else None)
    return out


@_api
def outline(path):
    """{rev, paragraphs, paragraph_range, headings: [{at, level, text, page?}],
    tables: [{at, rows, cols, title?, caption?, in?, page?}],
    places: [{id, at, label, kind, value, filled, page?}], places_complete, places_reason?}"""
    doc = _load(path)
    heads = [{"at": h["at"], "level": h["level"], "text": h["text"],
              **({"page": doc.page_of(h["para"])} if doc.page_starts else {})} for h in _headings(doc)]
    tables = []
    for t in doc.tables:
        if t.addr is None:
            continue
        rec = {"at": t.addr, "rows": t.rows, "cols": t.cols}
        first = t.at(0, 0)
        title = " ".join(_cell_text(first).split()) if first is not None else ""
        if title:
            rec["title"] = title if len(title) <= 40 else title[:39].rstrip() + "…"
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
        rec = {"id": pl["id"], "at": pl["at"], "label": pl.get("label"), "kind": pl.get("kind"),
               "value": pl["value"], "filled": pl["filled"]}
        if doc.page_starts and pl.get("para") is not None:
            rec["page"] = doc.page_of(pl["para"])
        places.append(rec)
    complete, why = _places_status(doc)
    out = {"rev": doc.rev, "paragraphs": len(doc.top),
           "paragraph_range": "p0..p%d" % (len(doc.top) - 1) if doc.top else None,
           "headings": heads, "tables": tables, "places": places, "places_complete": complete}
    if why:
        out["places_reason"] = why
    return out


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
    return {"at": t.addr, "kind": "table", "rows": t.rows, "cols": t.cols,
            "text": "\n".join("\t".join(r) for r in grid), "cells": grid}


@_api
def read(path, at=None, *, with_runs=False):
    """{rev, blocks: [{at, kind, text, runs?, style?}]}; a table also gives its cell grid."""
    doc = _load(path)
    blocks = []

    def top_blocks(ps):
        for p in ps:
            blocks.append(_para_block(doc, p, with_runs))
            for t in doc.tables_in(p):
                if t.addr is not None and doc.top_of(t.host) is p and (t.host is p or t.host.cell is not None):
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
    doc = _load(path)
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
    """One edit at one place: engine steps (base-document indices), the built-in path's version, and what it
    does to the document's structure (for the exact remap).

    Execution order is the reverse of ``key`` = (section, anchor, side, intra, rank, i): later in the document
    first. ``side`` breaks a tie at one XML offset: 0 = something inserted at the boundary after the element
    that ends there, 1 = an edit inside the element that starts there, 2 = a style change (applied before the
    text of that paragraph changes). ``rank`` breaks a tie at one character: a span edit (1) runs before an
    insertion at its start (0); two insertions at one point run in reverse input order, so they end up in input
    order."""

    def __init__(self, i, op, at, p, anchor, *, side=1, intra=0, rank=1, steps=(), fb=None, info=None):
        self.i, self.op, self.at, self.p = i, op, at, p
        self.si = p.si
        self.key = (p.si, anchor, side, intra, rank, i)
        self.steps, self.fb = list(steps), fb
        self.info = info or {}
        self.top_adds = []      # (base top gp, n): n new top-level paragraphs right after it
        self.top_dels = []      # base top gps removed
        self.cell_adds = []     # (cell, k, n): n new paragraphs right after the cell's paragraph k
        self.cell_dels = []     # (cell, k)
        self.tbl_adds = []      # (si, xml offset, its Cell | "top" | None) of a new table
        self.tbl_dels = []      # base table gs removed
        self.row_adds = []      # (table g, after)
        self.row_dels = []      # (table g, row)
        self.hf = []            # (si, kind, apply, text) / (si, "pageNum", pos, fmt): a section's own control
        self.col_adds = []      # (table g, after)
        self.col_dels = []      # (table g, col)
        self.merges = []        # (table g, first Cell, [Cells merged into it, reading order], (rs, cs))
        self.splits = []        # (table g, Cell, rows, cols)
        self.resized = []       # table gs whose sizes alone change
        self.restyled = []      # table gs whose cells or table properties alone change (grid and cells kept)
        self.cell_delta = []    # (table g, cells table.add_col adds)
        self.text_of = None     # the base paragraph whose text this act changes
        self.new_style = None   # style.create: {name, eng, kind, char, para} the output's header must have
        self.note = None        # note: (base Para, "footNote" | "endNote", text)
        self.caption = None     # caption: (table g, side, text)
        self.bookmark = None    # bookmark: (base Para, name, after)
        self.link = None        # link: (base Para, phrase, target)
        self.toc = None         # toc: (base Para, levels, leader, n_added)
        self.char_shape = None  # char_shape: (base Para, (a0, b0), fmt)
        self.para_shape = None  # para_shape: (base Para, fmt)
        self.page_setup = None  # page_setup: (si, {start_page?, border?})
        self.hide = None        # hide: (base Para, {header, footer, page_num, border, fill, master_page})
        self.new_num = None     # new_number: (base Para, kind, num)
        self.picture = None     # insert_picture / picture: verification spec
        self.formula = None     # table.formula: (base Para, "func" | "formula", spec)


class _Claims:
    """What every op reads and writes, in base-document terms, so two ops that would interfere are refused
    before anything runs (``conflict``)."""

    def __init__(self, doc):
        self.doc = doc
        self.spans = {}         # id(para) -> [(a, b, whole, i, op)]
        self.removed = []       # (si, start, end, i, op, at)
        self.touched = []       # (si, pos, i, op, at)
        self.tables = {}        # table g -> [(i, op, at, kind, rect, border)]: row and style ops on one table
        self.new_styles = {}    # style name -> the first style.create op that makes it in this edit
        self.created = {}       # style name -> i of the style.create planned so far
        self.auto_styles = {}   # style name -> (i, op) of the first op that needs _auto_styles to add it
        self.bookmarks = {}     # bookmark name -> i of the bookmark op that creates it in this edit
        self.toc_op = None      # i of the toc op in this edit
        self.pictures = {}      # (si, pic_id) -> (i, op) of the picture op in this edit

    def _conflict(self, i, op, j, op2, at):
        raise DocError("conflict", "ops %d (%s) and %d (%s) both change %s; send them in separate edits or as "
                       "one op" % (j, op2, i, op, at), i=i, at=at)

    def span(self, p, a, b, i, op, whole=False):
        at = para_address(self.doc, p)
        for a2, b2, w2, j, op2 in self.spans.get(id(p), []):
            if j == i:
                continue
            if whole or w2:
                self._conflict(i, op, j, op2, at)
            if a == b and a2 == b2:
                continue                                    # two insertions at one point: input order
            if (a == b and a2 < a < b2) or (a2 == b2 and a < a2 < b) or (a != b and a2 != b2 and max(a, a2) < min(b, b2)):
                self._conflict(i, op, j, op2, "%s:%d-%d" % (at, _pub(p, max(a, a2)), _pub(p, min(b, b2))))
        self.spans.setdefault(id(p), []).append((a, b, whole, i, op))
        self.touch(p.si, p.start, i, op, at)

    def touch(self, si, pos, i, op, at):
        for s2, x, y, j, op2, at2 in self.removed:
            if j != i and s2 == si and x <= pos < y:
                self._conflict(i, op, j, op2, at2)
        for s2, pos2, j, op2, _at2 in self.touched:
            if j != i and s2 == si and pos2 == pos and "toc" in (op, op2):
                self._conflict(i, op, j, op2, at)
        self.touched.append((si, pos, i, op, at))

    def remove(self, si, start, end, i, op, at):
        for s2, x, y, j, op2, _at2 in self.removed:
            if j != i and s2 == si and max(x, start) < min(y, end):
                self._conflict(i, op, j, op2, at)
        for s2, pos, j, op2, _at2 in self.touched:
            if j != i and s2 == si and start <= pos < end:
                self._conflict(i, op, j, op2, at)
        self.removed.append((si, start, end, i, op, at))


def _no_list_twice(cl, q, i, name, at):
    """style and numbering both read the paragraph's base style and list state: one of them per paragraph."""
    for s2, pos, j, op2, at2 in cl.touched:
        if j != i and s2 == q.si and pos == q.start and op2 in ("style", "numbering"):
            cl._conflict(i, name, j, op2, at)
    cl.touch(q.si, q.start, i, name, at)


EXPECT_OPS = ("set", "replace", "delete", "fill", "table.delete_row", "char_shape", "para_shape", "numbering",
              "table.delete_col", "break", "header", "note")
RANGE_OPS = ("set", "replace", "char_shape")


_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_UL = ("BOTTOM", "CENTER", "TOP")
_LINE_SHAPES = ("SOLID", "DASH", "DOT", "DASH_DOT", "DASH_DOT_DOT", "LONG_DASH", "CIRCLE", "DOUBLE_SLIM",
                "SLIM_THICK", "THICK_SLIM", "SLIM_THICK_SLIM", "WAVE", "DOUBLE_WAVE")
#: 선 종류 as the engine writes them (Hancom's HwpLineType 0..17)
LINE_TYPES = ("SOLID", "DOT", "DASH", "DASH_DOT", "DASH_DOT_DOT", "LONG_DASH", "CIRCLE", "DOUBLE_SLIM",
              "SLIM_THICK", "THICK_SLIM", "SLIM_THICK_SLIM", "WAVE", "DOUBLEWAVE", "THICK3D", "THICKREV3D", "3D",
              "REV3D")
#: 선 굵기 in millimetres, the list Hancom offers (HwpLineWidth 0..15)
LINE_WIDTHS_MM = (0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
_OUTLINE_TYPES = ("SOLID", "DOT", "THICK", "DASH", "DASH_DOT", "DASH_DOT_DOT")
_SHADOW_TYPES = ("DROP", "CONTINUOUS")
_SYM_MARKS = ("DOT_ABOVE", "RING_ABOVE", "TILDE", "CARON", "SIDE", "COLON", "GRAVE_ACCENT", "ACUTE_ACCENT",
              "CIRCUMFLEX", "MACRON", "HOOK_ABOVE", "DOT_BELOW")
_TAB_TYPES = ("LEFT", "RIGHT", "CENTER", "DECIMAL")
_TAB_LEADERS = ("NONE",) + LINE_TYPES
_TAB_MAX = 32
_BOOL = ("bool",)
#: 글자 모양 (서식 > 글자 모양) an agent can set: key -> kind and range. The engine's hnc_edit.set_char_shape
#: takes them (through _char_engine_fmt); markpen (형광펜) is its own engine step.
CHAR_SHAPE = {
    "bold": _BOOL, "italic": _BOOL, "emboss": _BOOL, "engrave": _BOOL, "sup": _BOOL, "sub": _BOOL,
    "underline": ("underline",), "underline_shape": ("enum", _LINE_SHAPES), "underline_color": ("color",),
    "strike": ("strike",), "strike_color": ("color",),
    "outline": ("false_or_enum", _OUTLINE_TYPES),
    "shadow": ("false_or_enum", _SHADOW_TYPES), "shadow_color": ("color",), "shadow_offset": ("shadow_offset",),
    "emphasis": ("false_or_enum", _SYM_MARKS),
    "char_border": ("border",), "char_fill": ("color_or_none",),
    "color": ("color",), "shade": ("color_or_none",), "markpen": ("color_or_none",),
    "size": ("num", 1.0, 4096.0), "ratio": ("int", 50, 200), "spacing": ("int", -50, 50),
    "rel_size": ("int", 10, 250), "offset": ("int", -100, 100),
    "font": ("font",),
}
#: 문단 모양 (서식 > 문단 모양): lengths in pt, line_spacing in % or {"type", "value" pt}.
PARA_SHAPE = {
    "align": ("enum", ("JUSTIFY", "LEFT", "RIGHT", "CENTER", "DISTRIBUTE", "DISTRIBUTE_SPACE")),
    "left": ("num", 0.0, 1000.0), "right": ("num", 0.0, 1000.0), "indent": ("num", -1000.0, 1000.0),
    "before": ("num", 0.0, 1000.0), "after": ("num", 0.0, 1000.0),
    "line_spacing": ("spacing",),
    "keep_next": _BOOL, "keep_lines": _BOOL, "widow_orphan": _BOOL, "page_break_before": _BOOL,
    "tabs": ("tabs",), "auto_tab_left": _BOOL, "auto_tab_right": _BOOL,
    "border": ("border",), "fill": ("color_or_none",), "offsets": ("offsets",), "connect": _BOOL,
}
_LS_TYPES = ("PERCENT", "FIXED", "BETWEEN_LINES", "AT_LEAST")


def _parse_width_mm(w):
    if isinstance(w, str):
        try:
            w = float(w.lower().replace("mm", "").strip())
        except ValueError:
            return None
    if isinstance(w, bool) or not isinstance(w, (int, float)):
        return None
    for x in LINE_WIDTHS_MM:
        if abs(float(w) - x) < 1e-9:
            return float(x)
    return None


def _parse_border_dict(v):
    if v is False:
        return True, False
    if not isinstance(v, dict) or not v or not (set(v) <= {"type", "width", "color"}):
        return False, v
    typ = v.get("type", "SOLID")
    if not isinstance(typ, str) or typ.upper() not in LINE_TYPES:
        return False, v
    w = _parse_width_mm(v.get("width", 0.12))
    if w is None:
        return False, v
    col = v.get("color", "#000000")
    if not isinstance(col, str) or not _COLOR.match(col):
        return False, v
    return True, {"type": typ.upper(), "width": w, "color": col.upper()}


def _char_engine_fmt(fmt):
    out = dict(fmt)
    if "outline" in out:
        out["text_outline"] = out.pop("outline")
    if "emphasis" in out:
        out["sym_mark"] = out.pop("emphasis")
    return out


def _para_engine_fmt(fmt):
    out = dict(fmt)
    if "tabs" in out or "auto_tab_left" in out or "auto_tab_right" in out:
        out["tab_stops"] = out.pop("tabs", [])
    if any(k in out for k in ("border", "fill", "offsets", "connect")):
        pb = {}
        has_bf = "border" in out or "fill" in out
        bd = out.pop("border", False)
        if has_bf:
            pb["border"] = bd
        if "fill" in out:
            pb["fill"] = out.pop("fill")
        if "offsets" in out:
            pb["offsets_pt"] = out.pop("offsets")
        if "connect" in out:
            pb["connect"] = out.pop("connect")
        out["para_border"] = pb
    return out


def _shape_fmt(name, op, i, at, table=None, key="set"):
    """The checked ``set`` of a char_shape / para_shape op (keys and values an engine accepts); with table and
    key, the same check of another op's shape field (style.create's char / para), named ``name``."""
    table = table or (CHAR_SHAPE if name == "char_shape" else PARA_SHAPE)
    fmt = op.get(key)
    if not isinstance(fmt, dict) or not fmt:
        raise DocError("bad_input", "%s needs %s: {key: value} (keys: %s)" % (name, key, ", ".join(table)),
                       i=i, at=at)
    bad = sorted(k for k in fmt if k not in table)
    if bad:
        raise DocError("bad_input", "%s: unknown key(s) %s (keys: %s)" % (name, ", ".join(map(str, bad)),
                                                                        ", ".join(table)), i=i, at=at,
                       candidates=_cands_near(list(table), str(bad[0])))
    out = {}
    for k, v in fmt.items():
        kind = table[k]
        t = kind[0]
        ok = True
        if t == "bool":
            ok = isinstance(v, bool)
        elif t == "num":
            ok = _num(v) and kind[1] <= v <= kind[2]
            v = float(v) if ok else v
        elif t == "int":
            ok = _is_int(v) and kind[1] <= v <= kind[2]
        elif t == "enum":
            ok = isinstance(v, str) and v.upper() in kind[1]
            v = v.upper() if ok else v
        elif t == "false_or_enum":
            ok = v is False or (isinstance(v, str) and v.upper() in kind[1])
            v = v.upper() if ok and isinstance(v, str) else v
        elif t == "color":
            ok = isinstance(v, str) and bool(_COLOR.match(v))
        elif t == "color_or_none":
            ok = v is None or (isinstance(v, str) and bool(_COLOR.match(v)))
        elif t == "underline":
            ok = isinstance(v, bool) or (isinstance(v, str) and v.upper() in _UL)
            v = v.upper() if ok and isinstance(v, str) else v
        elif t == "strike":
            ok = isinstance(v, bool) or (isinstance(v, str) and v.upper() in _LINE_SHAPES)
            v = v.upper() if ok and isinstance(v, str) else v
        elif t == "shadow_offset":
            ok = isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_int(x) and -100 <= x <= 100 for x in v)
            v = [int(v[0]), int(v[1])] if ok else v
        elif t == "border":
            ok, v = _parse_border_dict(v)
        elif t == "tabs":
            if not isinstance(v, list) or len(v) > _TAB_MAX:
                ok = False
            else:
                norm_tabs = []
                prev_pos = -1.0
                for st in v:
                    if not isinstance(st, dict) or "pos" not in st or not (set(st) <= {"pos", "type", "leader"}):
                        ok = False
                        break
                    pos = st["pos"]
                    typ = st.get("type", "LEFT")
                    lead = st.get("leader", "NONE")
                    if not (_num(pos) and 0.0 <= float(pos) <= 1000.0 and float(pos) > prev_pos):
                        ok = False
                        break
                    if not (isinstance(typ, str) and typ.upper() in _TAB_TYPES
                            and isinstance(lead, str) and lead.upper() in _TAB_LEADERS):
                        ok = False
                        break
                    prev_pos = float(pos)
                    norm_tabs.append({"pos": float(pos), "type": typ.upper(), "leader": lead.upper()})
                if ok:
                    v = norm_tabs
        elif t == "offsets":
            ok = (isinstance(v, (list, tuple)) and len(v) == 4
                  and all(_num(x) and 0.0 <= float(x) <= 1000.0 for x in v))
            v = [float(x) for x in v] if ok else v
        elif t == "font":
            ok = (isinstance(v, str) and 0 < len(v) <= 64 and not _CTRL.search(v)) or (
                isinstance(v, dict) and v and all(kk in ("hangul", "latin", "hanja", "japanese", "other",
                                                        "symbol", "user") and isinstance(vv, str) and
                                                  0 < len(vv) <= 64 and not _CTRL.search(vv)
                                                  for kk, vv in v.items()))
        elif t == "spacing":
            if _is_int(v):
                ok = 50 <= v <= 500
            else:
                ok = (isinstance(v, dict) and set(v) == {"type", "value"} and isinstance(v["type"], str)
                      and v["type"].upper() in _LS_TYPES and _num(v["value"]) and 0 < v["value"] <= 500)
                if ok:
                    v = {"type": v["type"].upper(), "value": v["value"]}
        if not ok:
            raise DocError("bad_input", "%s: %s=%r is out of range (%s)" % (name, k, v, _shape_hint(kind)),
                           i=i, at=at)
        out[k] = v
    if out.get("sup") and out.get("sub"):
        raise DocError("bad_input", "%s: sup and sub cannot both be on" % name, i=i, at=at)
    if table is PARA_SHAPE and "fill" in out and "border" not in out:
        # the engine writes 문단 테두리 and 배경 as one borderFill, so a fill alone would drop the paragraph's lines
        raise DocError("bad_input", "%s: fill needs border too (border: false for a background without lines); "
                                    "a fill alone would replace the paragraph's current 문단 테두리" % name,
                       i=i, at=at)
    return out


NUMBERING_KINDS = ("outline", "number", "bullet", "none")


def _numbering_set(op, i, at):
    """The checked ``set`` of a numbering op: kind, level 1-7, and char / start / restart where they apply."""
    v = op.get("set")
    if not isinstance(v, dict) or "kind" not in v:
        raise DocError("bad_input", "numbering needs set: {kind: outline|number|bullet|none, level?}", i=i, at=at)
    allowed = {"outline": ("kind", "level"), "number": ("kind", "level", "start", "restart"),
               "bullet": ("kind", "level", "char"), "none": ("kind",)}
    kind = v.get("kind")
    if kind not in allowed:
        raise DocError("bad_input", "numbering: kind is one of %s" % ", ".join(NUMBERING_KINDS), i=i, at=at,
                       candidates=list(NUMBERING_KINDS))
    extra = sorted(str(k) for k in v if k not in allowed[kind])
    if extra:
        raise DocError("bad_input", "numbering %s takes %s, not %s" % (kind, ", ".join(allowed[kind]),
                                                                        ", ".join(extra)), i=i, at=at)
    lv = v.get("level", 1 if kind == "outline" else None)
    if lv is not None and not (_is_int(lv) and 1 <= lv <= 7):
        raise DocError("bad_input", "numbering: level is 1 to 7", i=i, at=at)
    ch = v.get("char")
    if ch is not None and not (isinstance(ch, str) and len(ch) == 1 and not _CTRL.search(ch) and not ch.isspace()):
        raise DocError("bad_input", "numbering: char is one visible character", i=i, at=at)
    st = v.get("start")
    if st is not None and not (_is_int(st) and 1 <= st <= 9999):
        raise DocError("bad_input", "numbering: start is 1 to 9999", i=i, at=at)
    if "restart" in v and not isinstance(v["restart"], bool):
        raise DocError("bad_input", "numbering: restart is true or false", i=i, at=at)
    if st is not None and v.get("restart"):
        raise DocError("bad_input", "numbering: give start or restart, not both", i=i, at=at)
    return {"kind": kind, "level": lv, "char": ch, "start": st, "restart": bool(v.get("restart"))}


def _outline_style(doc, n):
    """The id of the document's 개요 n style (engName "Outline n"), or None."""
    for sid, s in doc.styles.items():
        if (s.get("engName") or "") == "Outline %d" % n:
            return sid
    return None


def _numbering_steps(doc, q, want):
    """Engine steps that bring paragraph q from its base list state to `want` (no steps when it is there)."""
    st = doc.styles.get(q.style) or {}
    outline = (st.get("engName") or "").startswith("Outline")
    typ, lv = doc.para_heading.get(q.pr, ("NONE", 0))
    kind, level = want["kind"], want["level"]
    go = ["goto", q.k, 0, q.si]
    if kind == "outline":
        if outline and st.get("engName") == "Outline %d" % level:
            return []
        return [go, ["apply_style", "Outline %d" % level]]
    steps = [go]
    if outline:                                  # out of the 개요 style first, as Hancom's toggle does
        steps.append(["apply_style", "0"])
        typ, lv = "NONE", 0
    if kind == "none":
        if typ == "NUMBER":
            steps.append(["put_para_number"])
        elif typ == "BULLET":
            steps.append(["put_bullet"])
        return steps if len(steps) > 1 else []
    if kind == "number":
        if typ != "NUMBER":
            steps.append(["put_para_number"])
            lv = lv if typ in ("NUMBER", "NONE", "BULLET") else 0
    else:
        if typ == "BULLET" and want["char"] is not None:
            steps.append(["put_bullet"])         # off, then on with the asked character
            typ = "NONE"
        if typ != "BULLET":
            steps.append(["put_bullet", want["char"]] if want["char"] is not None else ["put_bullet"])
            lv = lv or 1
    if level is not None and lv != level - 1:   # level n is the XML's level n-1
        steps.append(["para_level", level - 1 - lv])
    if kind == "number":
        if want["restart"]:
            steps.append(["put_new_para_number"])
        elif want["start"] is not None:
            steps.append({"op": "set_numbering", "kwargs": {"start": want["start"]}})
    return steps if len(steps) > 1 else []


def _shape_hint(kind):
    t = kind[0]
    if t in ("num", "int"):
        return "%s to %s" % (kind[1], kind[2])
    if t == "enum":
        return "one of " + ", ".join(kind[1])
    if t == "false_or_enum":
        return "false or one of " + ", ".join(kind[1])
    return {"bool": "true or false", "color": "#RRGGBB", "color_or_none": "#RRGGBB or null",
            "underline": "true, false or BOTTOM/CENTER/TOP", "strike": "true, false or a line shape",
            "shadow_offset": "[x, y] in % from -100 to 100",
            "border": "false or {type, width, color}",
            "tabs": "up to 32 of {pos: 0-1000 pt, type: LEFT|RIGHT|CENTER|DECIMAL, leader}",
            "offsets": "[left, right, top, bottom] in pt from 0 to 1000",
            "font": "a face name or {hangul, latin, ...}",
            "spacing": "a percent 50-500 or {type: FIXED|BETWEEN_LINES|AT_LEAST|PERCENT, value}"}[t]


def _check_expect(op, i, at, actual, table=None):
    """``expect`` must be the text at ``at``. For a cell, a mismatch names the
    one other cell of the same table that holds exactly the expected text
    (``found_at``): an agent that counted rows from 1 gets told where it meant."""
    if op.get("expect") is not None and op["expect"] != actual:
        found = [c for c in table.cells if _cell_text(c) == op["expect"]] if table is not None else []
        raise DocError("expect_mismatch", "the text at %s is not what the op expected" % at, at=at, i=i,
                       expected=op["expect"], actual=actual[:500],
                       found_at=cell_address(table, found[0]) if len(found) == 1 else None)


def _cell_text(c):
    return "\n".join(p.text for p in c.paras)


def _table_text(t, rows=None):
    grid = _table_block(None, t)["cells"]
    return "\n".join("\t".join(r) for j, r in enumerate(grid) if rows is None or j in rows)


def _need_text_para(p, at, i):
    if p.objs:
        raise DocError("bad_input", "%s holds an object (%s); set its text with replace, or address a cell"
                       % (at, ", ".join(sorted(set(p.objs)))), at=at, i=i)


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￼￾￿]")


def _clean(text, what, i, at):
    """Typed text: \\r\\n and \\r become \\n; characters XML or a paragraph cannot hold are refused."""
    if not isinstance(text, str):
        raise DocError("bad_input", "%s must be text" % what, i=i, at=at)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = _CTRL.search(text)
    if m:
        raise DocError("bad_input", "%s holds the control character U+%04X" % (what, ord(m.group(0))), i=i, at=at)
    return text


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


def _span_steps(p, a, b, text):
    st = [["goto", p.k, a, p.si]]
    if b > a:
        st += [["select", b - a], ["type", text] if text else ["delete"]]
    elif text:
        st += [["type", text]]
    return st


def _set_cell_steps(c, text):
    first, extra = c.paras[0], c.paras[1:]
    st = []
    for q in reversed(extra):
        st.append(["delete_paragraph", q.k, q.si])
    return st + _set_para_steps(first, text)


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


def _row_region(t, r):
    cells = t.row_cells(r)
    return (min(c.start for c in cells), max(c.end for c in cells)) if cells else None


def _tables_within(doc, si, start, end):
    return [t.g for t in doc.sec_tables[si] if start <= t.start < end]


TABLE_SHAPE_OPS = ("table.merge", "table.split", "table.add_col", "table.delete_col", "table.size")
SPLIT_MAX = 20
SIZE_MM = (1, 1000)


def _col_cells(t, c):
    return sorted((x for x in t.cells if x.col == c), key=lambda x: x.row)


def _merge_rect(t, r0, c0, r1, c1):
    """The block from corners (r0, c0) and (r1, c1), grown until no merged cell crosses its edge."""
    ra, rb, ca, cb = min(r0, r1), max(r0, r1), min(c0, c1), max(c0, c1)
    changed = True
    while changed:
        changed = False
        for x in t.cells:
            if x.row <= rb and x.row + x.rs - 1 >= ra and x.col <= cb and x.col + x.cs - 1 >= ca:
                na, nb = min(ra, x.row), max(rb, x.row + x.rs - 1)
                nc, nd = min(ca, x.col), max(cb, x.col + x.cs - 1)
                if (na, nb, nc, nd) != (ra, rb, ca, cb):
                    ra, rb, ca, cb = na, nb, nc, nd
                    changed = True
    return ra, rb, ca, cb


def _mm_value(v, what, i, at, none_ok=False):
    if v is None and none_ok:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not SIZE_MM[0] <= v <= SIZE_MM[1]:
        raise DocError("bad_input", "%s is a number of millimetres from %d to %d" % ((what,) + SIZE_MM),
                       i=i, at=at, range=list(SIZE_MM))
    return float(v)


def _merge_paras(inside):
    """id(paragraph) -> its index in the merged cell. The engine keeps the paragraphs that hold anything, in
    reading order; when none does, the first cell keeps its own (an empty dict)."""
    keep = [q for x in inside for q in x.paras if q.chars]
    return {id(q): k for k, q in enumerate(keep)}


CELL_VALIGN = ("TOP", "CENTER", "BOTTOM")
BORDER_SIDES = ("left", "right", "top", "bottom")
CELL_MARGIN_MM = (0, 50)
TABLE_PAGE_BREAK = ("CELL", "TABLE", "NONE")
CELL_STYLE_KEYS = ("border", "fill", "valign", "margin_mm", "header")
TABLE_STYLE_KEYS = ("repeat_header", "page_break")


def _bool(v, what, i, at):
    if not isinstance(v, bool):
        raise DocError("bad_input", "%s is true or false" % what, i=i, at=at)
    return v


def _line(v, what, i, at):
    """One border line: "none", or {type, width, color} with at least one of them."""
    if isinstance(v, str) and v.lower() == "none":
        return "NONE"
    if not isinstance(v, dict) or not v:
        raise DocError("bad_input", '%s is "none" or {type, width, color}' % what, i=i, at=at)
    extra = sorted(set(v) - {"type", "width", "color"})
    if extra:
        raise DocError("bad_input", "%s takes type, width and color, not %s" % (what, extra[0]), i=i, at=at,
                       candidates=["type", "width", "color"])
    out = {}
    if "type" in v:
        out["type"] = _enum(v["type"], LINE_TYPES + ("NONE",), what + ".type", i, at)
    if "width" in v:
        w = v["width"]
        if isinstance(w, str):
            try:
                w = float(w.lower().replace("mm", "").strip())
            except ValueError:
                w = None
        if isinstance(w, bool) or not isinstance(w, (int, float)) or \
                not any(abs(w - x) < 1e-9 for x in LINE_WIDTHS_MM):
            raise DocError("bad_input", "%s.width is one of Hancom's line widths in millimetres" % what, i=i, at=at,
                           candidates=list(LINE_WIDTHS_MM))
        out["width"] = float(w)
    if "color" in v:
        if not isinstance(v["color"], str) or not _COLOR.match(v["color"]):
            raise DocError("bad_input", "%s.color is #RRGGBB" % what, i=i, at=at)
        out["color"] = v["color"].upper()
    return out


def _border_sides(v, i, at):
    """border -> {side: "NONE" | {type, width, color}} for the four sides."""
    if isinstance(v, dict) and v and set(v) <= set(BORDER_SIDES) | {"all"}:
        sides = {}
        if "all" in v:
            line = _line(v["all"], "border.all", i, at)
            sides = {k: line for k in BORDER_SIDES}
        for k in BORDER_SIDES:
            if k in v:
                sides[k] = _line(v[k], "border." + k, i, at)
        return sides
    if isinstance(v, dict) and v and set(v) & (set(BORDER_SIDES) | {"all"}):
        raise DocError("bad_input", "border is one line for every side ({type, width, color} or \"none\") or "
                       "{all, left, right, top, bottom}, not both", i=i, at=at)
    line = _line(v, "border", i, at)
    return {k: line for k in BORDER_SIDES}


def _margin(v, i, at):
    def one(x, what):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not CELL_MARGIN_MM[0] <= x <= CELL_MARGIN_MM[1]:
            raise DocError("bad_input", "%s is a number of millimetres from %d to %d" % ((what,) + CELL_MARGIN_MM),
                           i=i, at=at, range=list(CELL_MARGIN_MM))
        return float(x)
    if isinstance(v, dict):
        extra = sorted(set(v) - set(BORDER_SIDES))
        if extra or not v:
            raise DocError("bad_input", "margin_mm is a number or {left, right, top, bottom}", i=i, at=at,
                           candidates=list(BORDER_SIDES))
        return {k: one(x, "margin_mm." + k) for k, x in v.items()}
    return one(v, "margin_mm")


def _style_set(op, keys, i, at, name):
    want = op.get("set")
    if not isinstance(want, dict) or not want:
        raise DocError("bad_input", "%s needs set: {%s}" % (name, ", ".join(keys)), i=i, at=at,
                       candidates=list(keys))
    extra = sorted(set(want) - set(keys))
    if extra:
        raise DocError("bad_input", "%s set takes %s, not %s" % (name, ", ".join(keys), extra[0]), i=i, at=at,
                       candidates=list(keys))
    return want


def _table_mark(cl, t, i, name, at, kind, rect=None, border=False):
    """Row and style ops on one table: a style op reads the base table by row and column, so a row added or
    deleted in the same edit is a conflict with a cell style or a table style; two cell styles may share a
    table when their blocks do not overlap (nor touch, when either sets a border: a border is shared with the
    neighbour across it)."""
    for j, op2, at2, kind2, rect2, border2 in cl.tables.get(t.g, []):
        if j == i:
            continue
        clash = False
        if "rows" in (kind, kind2) and ("cell" in (kind, kind2) or "table" in (kind, kind2)
                                        or "formula" in (kind, kind2)):
            clash = True
        elif kind == kind2 == "table":
            clash = True
        elif kind == kind2 == "cell":
            grow = 1 if (border or border2) else 0
            ra, rb, ca, cb = rect
            xa, xb, ya, yb = rect2
            clash = ra - grow <= xb and xa <= rb + grow and ca - grow <= yb and ya <= cb + grow
            if clash and grow and not (ra <= xb and xa <= rb and ca <= yb and ya <= cb):
                # touching only at a corner shares no edge
                clash = (ra - 1 <= xb and xa <= rb + 1 and ca <= yb and ya <= cb) or \
                        (ra <= xb and xa <= rb and ca - 1 <= yb and ya <= cb + 1)
        if clash:
            cl._conflict(i, name, j, op2, at)
    cl.tables.setdefault(t.g, []).append((i, name, at, kind, rect, border))


def _shape_claim(cl, t, i, name, at):
    """A structural op owns the whole table: any other op on it, its cells or what they hold is a conflict."""
    cl.remove(t.si, t.start, t.end, i, name, at)


def _adds_for(doc, act, p, n):
    """Record n new paragraphs right after paragraph p."""
    if not n:
        return
    if p.top:
        act.top_adds.append((p.gp, n))
    elif p.cell is not None:
        act.cell_adds.append((p.cell, p.cell.paras.index(p), n))
    else:
        act.info["unmapped"] = True        # caption / text box paragraphs have no address of their own


def _plan(doc, ops):
    """ops -> [_Act], every op validated against base (addresses, kinds, ranges, expect, overlaps) before any
    step exists. Raises DocError."""
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise DocError("bad_input", "ops: a non-empty list of operations")
    acts = []
    cl = _Claims(doc)
    cl.new_styles = {o["name"]: j for j, o in enumerate(ops) if isinstance(o, dict) and
                     o.get("op") == "style.create" and isinstance(o.get("name"), str)}
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise DocError("bad_input", "op %d: unknown operation %r (known: %s)" % (
                i, op.get("op") if isinstance(op, dict) else op, ", ".join(OPS)), i=i)
        name = op["op"]
        at = op.get("at")
        try:
            if op.get("expect") is not None:
                if name not in EXPECT_OPS:
                    raise DocError("bad_input", "%s takes no expect (expect works with %s)"
                                   % (name, ", ".join(EXPECT_OPS)), i=i, at=at)
                ok = isinstance(op["expect"], str) or (name == "replace" and _is_int(op["expect"]))
                if not ok:
                    raise DocError("bad_input", "expect is the expected text%s" % (
                        ", or for replace the number of matches" if name == "replace" else ""), i=i, at=at)
            if "all" in op and not isinstance(op["all"], bool):
                raise DocError("bad_input", "all is true or false", i=i, at=at)
            if at is not None and name not in RANGE_OPS and isinstance(at, str) and re.match(
                    r"^(?:p\d+|t\d+/r\d+/c\d+/p\d+):\d+-\d+$", at.strip()):
                raise DocError("bad_address", "a character range only works with %s" % ", ".join(RANGE_OPS), i=i, at=at)
            acts.extend(_plan_op(doc, cl, i, name, op, at))
        except DocError as exc:
            exc.extra.setdefault("i", i)
            exc.extra.setdefault("at", at if isinstance(at, str) else None)
            raise
    base_sname = doc.style_name("0") or next((s.get("name") for s in doc.styles.values() if s.get("name")), "바탕글")
    for eng, sname, act in _auto_styles(doc, acts):
        act.info.setdefault("warnings", []).append(
            "auto_style: added missing style %s (%s) to header.xml based on %s" % (sname, eng, base_sname))
    return acts


#: 편집 용지 (F7): paper names and their portrait size in mm, as Hancom's 용지 종류 list names them.
PAPER_MM = {"A3": (297, 420), "A4": (210, 297), "A5": (148, 210), "B4": (257, 364), "B5": (182, 257),
            "LETTER": (215.9, 279.4), "LEGAL": (215.9, 355.6)}
PAGE_SIZE_MM = (50, 1000)
MARGIN_KEYS = ("left", "right", "top", "bottom", "header", "footer", "gutter")
MARGIN_MM = (0, 500)
GUTTER_TYPES = ("LEFT_ONLY", "LEFT_RIGHT", "TOP_BOTTOM")
COLUMN_KINDS = ("NEWSPAPER", "BALANCED_NEWSPAPER", "PARALLEL")
COLUMN_LAYOUTS = ("LEFT", "RIGHT", "MIRROR")
COLUMN_COUNT = (1, 255)
COLUMN_GAP_MM = (0, 100)
BREAK_KINDS = ("page", "column", "section")
PAGE_NUM_RANGE = (1, 65535)
PAGE_BORDER_KEYS = ("type", "width", "color", "fill", "offset_mm", "apply", "text_border",
                    "header_inside", "footer_inside")
PAGE_TEXT_BORDERS = ("PAPER", "CONTENT")
HIDE_KEYS = ("header", "footer", "page_num", "border", "fill", "master_page")
HIDE_ATTRS = (("header", "hideHeader"), ("footer", "hideFooter"), ("master_page", "hideMasterPage"),
              ("border", "hideBorder"), ("fill", "hideFill"), ("page_num", "hidePageNum"))
NEW_NUM_KINDS = ("PAGE", "FOOTNOTE", "ENDNOTE", "PICTURE", "TABLE", "EQUATION")
HU_PER_MM = 7200 / 25.4
PICTURE_WRAPS = ("SQUARE", "TIGHT", "THROUGH", "TOP_AND_BOTTOM", "BEHIND_TEXT", "IN_FRONT_OF_TEXT")
PICTURE_VERT_RELS = ("PARA", "PAGE", "PAPER")
PICTURE_HORZ_RELS = ("COLUMN", "PARA", "PAGE", "PAPER")
PICTURE_OFFSET_MM = (-1000, 1000)
INSERT_PICTURE_KEYS = ("path", "width_mm", "height_mm", "offset", "wrap", "vert_rel", "horz_rel", "x_mm", "y_mm")
PICTURE_SET_KEYS = ("width_mm", "height_mm", "keep_ratio", "wrap", "inline", "vert_rel", "horz_rel", "x_mm", "y_mm")
FORMULA_FUNCS = ("SUM", "AVG", "PRODUCT")
FORMULA_ENGINE_FUNC = {"SUM": "Sum", "AVG": "Avg", "PRODUCT": "Pro"}
FORMULA_MAX = 200
_FORMULA_LEADING_NUM = re.compile(r"\s*([-+]?(?:\d[\d,]*)?\.?\d+)")
_STRING_PARAM = re.compile(r'<[\w:.-]*stringParam\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</', re.S)
_CELL_CTRL_RE = re.compile(
    r"<(?:[\w.-]+:)?(?:ctrl|fieldBegin|fieldEnd|bookmark|autoNum|newNum|pageHiding|indexmark|footNote|endNote)\b"
)


def _cell_is_empty(doc, t, c):
    """True when cell `c` of table `t` has one empty paragraph with no text, objects or controls."""
    if len(c.paras) != 1:
        return False
    p = c.paras[0]
    if p.chars or p.objs or p.fields:
        return False
    return not _CELL_CTRL_RE.search(doc.secs[t.si], p.start, p.end)


def _formula_auto_expect(func, src_cells, is_row):
    """(formula, fmt, res) that Hancom / hnc_edit.formula_auto writes for `func` (SUM|AVG|PRODUCT) over
    `src_cells` along a row (`is_row=True`) or down a column (`is_row=False`)."""
    vals = []
    for x in src_cells:
        txt = "".join(p.text for p in x.paras)
        m = _FORMULA_LEADING_NUM.match(txt)
        vals.append(float(m.group(1).replace(",", "")) if m else 0.0)
    if is_row:
        ref = "%s?:%s?" % (chr(65 + src_cells[0].col), chr(65 + src_cells[-1].col))
    else:
        ref = "?%d:?%d" % (src_cells[0].row + 1, src_cells[-1].row + 1)
    v = (sum(vals) if func == "SUM"
         else (sum(vals) / len(vals) if vals else 0.0) if func == "AVG"
         else math.prod(vals))
    if func == "AVG":
        fmt = "%.2f,"
        q = Decimal(repr(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ip, _, fp = str(q).partition(".")
        res = "{:,}".format(int(ip)) + "." + fp
    else:
        fmt = "%g,"
        if float(v).is_integer():
            res = "{:,}".format(int(v))
        else:
            ip, _, fp = repr(float(v)).partition(".")
            res = "{:,}".format(int(ip)) + "." + fp
    return "=%s(%s)" % (func, ref), fmt, res


def _formula_fields_in(d, p):
    """[(formula, command, result_format, last_result, range_text)] of direct FORMULA fields in paragraph `p`."""
    s = d.secs[p.si]
    out = []
    for f in p.fields:
        if (f.get("type") or "").upper() != "FORMULA":
            continue
        fid = f.get("id")
        if not fid or not isinstance(f.get("e"), int) or f.get("startx") is None or f.get("endx") is None:
            out.append(None)
            continue
        close = s.find("fieldBegin>", f["startx"], f["endx"])
        if close < 0:
            out.append(None)
            continue
        if len(re.findall(r'<[\w:.-]*fieldEnd\b[^>]*\bbeginIDRef="%s"' % re.escape(fid), s[p.start:p.end])) != 1:
            out.append(None)
            continue
        params = {}
        for pm in _STRING_PARAM.finditer(s, f["startx"], close):
            pname = _xml_unescape(pm.group(1))
            pval = "".join(_xml_char(x) for x in _XCHAR.finditer(pm.group(2)))
            params[pname] = pval
        rtext = "".join(c for c in p.chars[f["b"]:f["e"]] if c != OBJ)
        out.append((params.get("Formula"), params.get("Command"),
                    params.get("ResultFormat"), params.get("LastResult"), rtext))
    return out


def _pic_elem_end(s, start):
    """End offset in `s` of the <hp:pic ...> element starting at `start`."""
    pat = re.compile(r"<(/?)hp:pic\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*?(/?)>", re.S)
    depth = 0
    for m in pat.finditer(s, start):
        if m.group(2) == "/":
            if depth == 0:
                return m.end()
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return len(s)


def _int_attr(tag, name):
    if not tag:
        return None
    v = _attr(tag, name)
    return int(v) if v is not None and re.fullmatch(r"-?\d+", v) else None


def _parse_pic(raw):
    """Parsed attributes of one <hp:pic> element (excluding any nested <hp:caption>)."""
    body = re.sub(r"<hp:caption\b[^>]*>.*?</hp:caption>", "", raw, flags=re.S)
    open_tag = body[:body.find(">") + 1]
    sz_m = re.search(r"<hp:sz\b[^<>]*/>", body)
    cur_m = re.search(r"<hp:curSz\b[^<>]*/>", body)
    org_m = re.search(r"<hp:orgSz\b[^<>]*/>", body)
    pos_m = re.search(r"<hp:pos\b[^<>]*/>", body)
    img_m = re.search(r"<hc:img\b[^<>]*/>", body)
    sz_tag = sz_m.group(0) if sz_m else None
    cur_tag = cur_m.group(0) if cur_m else None
    org_tag = org_m.group(0) if org_m else None
    pos_tag = pos_m.group(0) if pos_m else None
    img_tag = img_m.group(0) if img_m else None
    return {
        "id": _attr(open_tag, "id"),
        "wrap": _attr(open_tag, "textWrap"),
        "width": _int_attr(sz_tag, "width"),
        "height": _int_attr(sz_tag, "height"),
        "cur_width": _int_attr(cur_tag, "width"),
        "cur_height": _int_attr(cur_tag, "height"),
        "org_width": _int_attr(org_tag, "width"),
        "org_height": _int_attr(org_tag, "height"),
        "treat_as_char": _attr(pos_tag, "treatAsChar") if pos_tag else None,
        "vert_rel": _attr(pos_tag, "vertRelTo") if pos_tag else None,
        "horz_rel": _attr(pos_tag, "horzRelTo") if pos_tag else None,
        "vert_offset": _int_attr(pos_tag, "vertOffset"),
        "horz_offset": _int_attr(pos_tag, "horzOffset"),
        "bin_ref": _attr(img_tag, "binaryItemIDRef") if img_tag else None,
    }


def _pics_in(d, p):
    """[parsed_pic, ...] of direct <hp:pic> elements in paragraph `p` in XML order (excluding pictures inside
    nested tables, text boxes, captions, notes, headers or footers)."""
    s = d.secs[p.si]
    seg = s[p.start:p.end]
    draw_spans = [(p.start + m.start(), p.start + m.end())
                  for m in re.finditer(r"<hp:drawText\b[^>]*>.*?</hp:drawText>", seg, re.S)]
    out = []
    for m in re.finditer(r"<hp:pic\b[^>]*>", seg):
        pos = p.start + m.start()
        host = next((q for q in reversed(d.sec_paras[p.si]) if q.start < pos < q.end), None)
        if host is not p:
            continue
        if any(p.start < t.start < pos < t.end for t in d.sec_tables[p.si]):
            continue
        if any(da < pos < db for da, db in draw_spans):
            continue
        end_pos = (pos + len(m.group(0))) if m.group(0).endswith("/>") else _pic_elem_end(s, pos)
        out.append(_parse_pic(s[pos:end_pos]))
    return out


def _in(v, lo, hi):
    return _num(v) and lo <= v <= hi


def _page_border_kwargs(bd, i, at):
    """The checked ``border`` of a page_setup op: None (for border: false) or the engine's border dict."""
    if bd is False:
        return None
    if not isinstance(bd, dict) or not bd:
        raise DocError("bad_input", "page_setup: border is false or {type, width, color, fill?, offset_mm?, "
                       "apply?, text_border?, header_inside?, footer_inside?}", i=i, at=at)
    bad = sorted(str(k) for k in bd if k not in PAGE_BORDER_KEYS)
    if bad:
        raise DocError("bad_input", "page_setup: border has no %s (keys: %s)"
                       % (bad[0], ", ".join(PAGE_BORDER_KEYS)), i=i, at=at,
                       candidates=_cands_near(list(PAGE_BORDER_KEYS), bad[0]) or list(PAGE_BORDER_KEYS))
    if "type" not in bd:    # a default line here would draw a frame on every page when only a background was asked
        raise DocError("bad_input", "page_setup: border needs type (a line type, or NONE for a background without "
                       "lines)", i=i, at=at, candidates=["NONE"] + list(LINE_TYPES))
    line_in = {k: bd[k] for k in ("type", "width", "color") if k in bd}
    if isinstance(bd.get("type"), str) and bd["type"].upper() == "NONE":    # 쪽 배경 only, no lines
        if "width" in bd or "color" in bd:
            raise DocError("bad_input", "page_setup: border.type NONE (a background without lines) takes no "
                           "width or color", i=i, at=at)
        ok, line = True, {"type": "NONE", "width": 0.1, "color": "#000000"}
    else:
        ok, line = _parse_border_dict(line_in)
    if not ok:
        if "type" in bd and (not isinstance(bd["type"], str) or bd["type"].upper() not in LINE_TYPES):
            raise DocError("bad_input", "page_setup: border.type is one of %s" % ", ".join(LINE_TYPES),
                           i=i, at=at,
                           candidates=_cands_near(list(LINE_TYPES), str(bd["type"])) or list(LINE_TYPES))
        if "width" in bd and _parse_width_mm(bd["width"]) is None:
            raise DocError("bad_input", "page_setup: border.width is one of Hancom's line widths in millimetres",
                           i=i, at=at, candidates=list(LINE_WIDTHS_MM))
        raise DocError("bad_input", "page_setup: border=%r is out of range (%s)"
                       % (bd, _shape_hint(("border",))), i=i, at=at)
    out = dict(line)
    if "fill" in bd:
        f = bd["fill"]
        if f is not None and not (isinstance(f, str) and _COLOR.match(f)):
            raise DocError("bad_input", "page_setup: border.fill is #RRGGBB or null", i=i, at=at)
        out["fill"] = None if f is None else f.upper()
    if "offset_mm" in bd:
        off = bd["offset_mm"]
        if _in(off, *MARGIN_MM):
            out["offset_mm"] = {k: float(off) for k in BORDER_SIDES}
        elif isinstance(off, (list, tuple)) and len(off) == 4 and all(_in(x, *MARGIN_MM) for x in off):
            out["offset_mm"] = dict(zip(BORDER_SIDES, (float(x) for x in off)))
        elif isinstance(off, dict) and off and set(off) <= set(BORDER_SIDES) \
                and all(_in(x, *MARGIN_MM) for x in off.values()):
            out["offset_mm"] = {k: float(x) for k, x in off.items()}
        else:
            raise DocError("bad_input", "page_setup: border.offset_mm is a number or [left, right, top, bottom] "
                           "from %d to %d mm" % MARGIN_MM, i=i, at=at)
    if "apply" in bd:
        out["apply"] = _enum(bd["apply"], HF_APPLY, "page_setup: border.apply", i, at)
    if "text_border" in bd:
        out["text_border"] = _enum(bd["text_border"], PAGE_TEXT_BORDERS, "page_setup: border.text_border", i, at)
    for k in ("header_inside", "footer_inside"):
        if k in bd:
            if not isinstance(bd[k], bool):
                raise DocError("bad_input", "page_setup: border.%s is true or false" % k, i=i, at=at)
            out[k] = bd[k]
    return out


def _page_setup_kwargs(op, i, at):
    """The checked ``set`` of a page_setup op as hnc_edit.page_setup keyword arguments."""
    v = op.get("set")
    keys = ("paper", "width_mm", "height_mm", "landscape", "margins", "gutter_type", "start_page", "border")
    if not isinstance(v, dict) or not v:
        raise DocError("bad_input", "page_setup needs set: {key: value} (keys: %s)" % ", ".join(keys), i=i, at=at)
    bad = sorted(str(k) for k in v if k not in keys)
    if bad:
        raise DocError("bad_input", "page_setup: unknown key(s) %s (keys: %s)" % (", ".join(bad), ", ".join(keys)),
                       i=i, at=at, candidates=_cands_near(list(keys), bad[0]))
    kw = {}
    if "paper" in v:
        name = v["paper"].upper() if isinstance(v["paper"], str) else None
        if name not in PAPER_MM:
            raise DocError("bad_input", "page_setup: paper is one of %s" % ", ".join(PAPER_MM), i=i, at=at,
                           candidates=list(PAPER_MM))
        if "width_mm" in v or "height_mm" in v:
            raise DocError("bad_input", "page_setup: give paper or width_mm/height_mm, not both", i=i, at=at)
        kw["width_mm"], kw["height_mm"] = PAPER_MM[name]
    for k in ("width_mm", "height_mm"):
        if k in v:
            if not _in(v[k], *PAGE_SIZE_MM):
                raise DocError("bad_input", "page_setup: %s is %d to %d mm" % ((k,) + PAGE_SIZE_MM), i=i, at=at)
            kw[k] = float(v[k])
    if "landscape" in v:
        if not isinstance(v["landscape"], bool):
            raise DocError("bad_input", "page_setup: landscape is true or false", i=i, at=at)
        kw["landscape"] = v["landscape"]
    if "margins" in v:
        m = v["margins"]
        if not isinstance(m, dict) or not m:
            raise DocError("bad_input", "page_setup: margins is {%s: mm}" % ", ".join(MARGIN_KEYS), i=i, at=at)
        bad = sorted(str(k) for k in m if k not in MARGIN_KEYS)
        if bad:
            raise DocError("bad_input", "page_setup: margins has no %s (keys: %s)" % (bad[0], ", ".join(MARGIN_KEYS)),
                           i=i, at=at, candidates=_cands_near(list(MARGIN_KEYS), bad[0]))
        for k, x in m.items():
            if not _in(x, *MARGIN_MM):
                raise DocError("bad_input", "page_setup: margins.%s is %d to %d mm" % ((k,) + MARGIN_MM), i=i, at=at)
        kw["margins_mm"] = {k: float(x) for k, x in m.items()}
    if "gutter_type" in v:
        g = v["gutter_type"].upper() if isinstance(v["gutter_type"], str) else None
        if g not in GUTTER_TYPES:
            raise DocError("bad_input", "page_setup: gutter_type is one of %s" % ", ".join(GUTTER_TYPES), i=i,
                           at=at, candidates=list(GUTTER_TYPES))
        kw["gutter_type"] = g
    if "start_page" in v:
        sp = v["start_page"]
        if not (_is_int(sp) and PAGE_NUM_RANGE[0] <= sp <= PAGE_NUM_RANGE[1]):
            raise DocError("bad_input", "page_setup: start_page is %d to %d" % PAGE_NUM_RANGE,
                           i=i, at=at, range=list(PAGE_NUM_RANGE))
        kw["start_page"] = int(sp)
    if "border" in v:
        kw["border"] = _page_border_kwargs(v["border"], i, at)
    return kw


def _page_fit(doc, si, kw, i, at):
    """Refuse margins that leave no room on the paper (Hancom's 편집 용지 refuses them too): the section's own
    pagePr / margin, with what this op changes, in HWPUNIT (7200 per inch). Landscape pages lay the paper's
    height across, as the engine draws them."""
    sec = doc.secs[si]
    pp = re.search(r"<hp:pagePr\b[^>]*>", sec)
    mg = re.search(r"<hp:margin\b[^>]*/?>", sec[pp.end():]) if pp else None
    if not pp or not mg:
        return

    def num(tag, k):
        m = re.search(r'\b%s="(-?\d+)"' % k, tag)
        return int(m.group(1)) if m else 0
    hu = lambda mm: mm * 7200 / 25.4                            # noqa: E731
    w = hu(kw["width_mm"]) if "width_mm" in kw else num(pp.group(0), "width")
    h = hu(kw["height_mm"]) if "height_mm" in kw else num(pp.group(0), "height")
    land = kw["landscape"] if "landscape" in kw else 'landscape="NARROWLY"' in pp.group(0)
    gt = kw.get("gutter_type") or (re.search(r'gutterType="(\w+)"', pp.group(0)) or [None, "LEFT_ONLY"])[1]
    m = {k: num(mg.group(0), k) for k in MARGIN_KEYS}
    m.update({k: hu(x) for k, x in kw.get("margins_mm", {}).items()})
    across, down = (h, w) if land else (w, h)
    g = m["gutter"]
    used_x = m["left"] + m["right"] + (g if gt != "TOP_BOTTOM" else 0)     # 맞쪽 too: one gutter a page
    used_y = m["top"] + m["bottom"] + m["header"] + m["footer"] + (g if gt == "TOP_BOTTOM" else 0)
    mm = lambda x: round(x * 25.4 / 7200, 1)                    # noqa: E731
    if used_x >= across:
        raise DocError("bad_input", "page_setup: left + right + gutter margins (%s mm) leave no room across the "
                       "%s mm page" % (mm(used_x), mm(across)), i=i, at=at)
    if used_y >= down:
        raise DocError("bad_input", "page_setup: top + bottom + header + footer margins (%s mm) leave no room "
                       "down the %s mm page" % (mm(used_y), mm(down)), i=i, at=at)


def _columns_kwargs(op, i, at):
    """The checked ``set`` of a columns op as hnc_edit.set_columns keyword arguments."""
    v = op.get("set")
    keys = ("count", "gap_mm", "line", "kind", "layout")
    if not isinstance(v, dict) or "count" not in v:
        raise DocError("bad_input", "columns needs set: {count, gap_mm?, line?, kind?, layout?}", i=i, at=at)
    bad = sorted(str(k) for k in v if k not in keys)
    if bad:
        raise DocError("bad_input", "columns: unknown key(s) %s (keys: %s)" % (", ".join(bad), ", ".join(keys)),
                       i=i, at=at, candidates=_cands_near(list(keys), bad[0]))
    if not (_is_int(v["count"]) and COLUMN_COUNT[0] <= v["count"] <= COLUMN_COUNT[1]):
        raise DocError("bad_input", "columns: count is %d to %d" % COLUMN_COUNT, i=i, at=at)
    kw = {"count": v["count"]}
    if "gap_mm" in v:
        if not _in(v["gap_mm"], *COLUMN_GAP_MM):
            raise DocError("bad_input", "columns: gap_mm is %d to %d" % COLUMN_GAP_MM, i=i, at=at)
        kw["gap_mm"] = float(v["gap_mm"])
    if "line" in v:
        if not isinstance(v["line"], bool):
            raise DocError("bad_input", "columns: line (구분선) is true or false", i=i, at=at)
        kw["line"] = v["line"]
    for k, allowed in (("kind", COLUMN_KINDS), ("layout", COLUMN_LAYOUTS)):
        if k in v:
            x = v[k].upper() if isinstance(v[k], str) else None
            if x not in allowed:
                raise DocError("bad_input", "columns: %s is one of %s" % (k, ", ".join(allowed)), i=i, at=at,
                               candidates=list(allowed))
            kw[k] = x
    return kw


#: 머리말/꼬리말 (Ctrl+N,H) and 쪽 번호 매기기 (Ctrl+N,P): the values hnc_edit takes.
HF_KINDS = ("header", "footer")
HF_APPLY = ("BOTH", "ODD", "EVEN")
HF_TEXT_MAX = 1000
HF_PLACEHOLDERS = ("{page}", "{pages}")
_HF_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|([{}])")
_HF_AUTONUM_TEXT = {"PAGE": "{page}", "TOTAL_PAGE": "{pages}"}
_HF_AUTONUM_SEQ = {"PAGE": "\x01", "TOTAL_PAGE": "\x02"}
PAGE_NUM_POS = ("BOTTOM_CENTER", "BOTTOM_LEFT", "BOTTOM_RIGHT", "TOP_CENTER", "TOP_LEFT", "TOP_RIGHT",
                "OUTSIDE_TOP", "OUTSIDE_BOTTOM", "INSIDE_TOP", "INSIDE_BOTTOM", "NONE")
PAGE_NUM_FORMATS = ("DIGIT", "CIRCLED_DIGIT", "ROMAN_CAPITAL", "ROMAN_SMALL", "LATIN_CAPITAL", "LATIN_SMALL",
                    "CIRCLED_LATIN_CAPITAL", "CIRCLED_LATIN_SMALL", "HANGUL_SYLLABLE", "CIRCLED_HANGUL_SYLLABLE",
                    "HANGUL_JAMO", "CIRCLED_HANGUL_JAMO", "HANGUL_PHONETIC", "IDEOGRAPH", "CIRCLED_IDEOGRAPH")


def _enum(v, allowed, what, i, at, default=None):
    if v is None and default is not None:
        return default
    x = v.upper() if isinstance(v, str) else None
    if x not in allowed:
        raise DocError("bad_input", "%s is one of %s" % (what, ", ".join(allowed)), i=i, at=at,
                       candidates=_cands_near(list(allowed), str(v)) or list(allowed))
    return x


def _parse_hf_text(text, i, at):
    """Parse header/footer text into (pieces, want_seq, has_fields).
    `{{` and `}}` are literal `{` and `}`; `{page}` and `{pages}` are PAGE and TOTAL_PAGE autoNum fields."""
    pieces, buf, seq = [], [], []
    has_fields = False
    last = 0
    for m in _HF_TOKEN.finditer(text):
        if m.start() > last:
            lit = text[last:m.start()]
            buf.append(lit)
            seq.append(lit)
        last = m.end()
        tok = m.group(0)
        if tok == "{{":
            buf.append("{")
            seq.append("{")
        elif tok == "}}":
            buf.append("}")
            seq.append("}")
        elif m.group(2) is not None:
            raise DocError("bad_input",
                           "header: unmatched %r in text (placeholders are {page} and {pages}; "
                           "use {{ and }} for literal braces)" % m.group(2),
                           i=i, at=at, candidates=list(HF_PLACEHOLDERS))
        else:
            name = m.group(1)
            if name not in ("page", "pages"):
                raise DocError("bad_input",
                               "header: unknown placeholder {%s} (placeholders are {page} and {pages}; "
                               "use {{ and }} for literal braces)" % name,
                               i=i, at=at, candidates=list(HF_PLACEHOLDERS))
            if buf:
                pieces.append(("text", "".join(buf)))
                buf.clear()
            has_fields = True
            pieces.append(("field", "page" if name == "page" else "total"))
            seq.append("\x01" if name == "page" else "\x02")
    if last < len(text):
        lit = text[last:]
        buf.append(lit)
        seq.append(lit)
    if buf:
        pieces.append(("text", "".join(buf)))
    return pieces, "".join(seq), has_fields


def _hf_para_read(doc, q):
    """(display_text, sentinel_seq) of a header/footer paragraph `q`, interleaving its text characters and its own
    <hp:autoNum> controls in XML order."""
    s = doc.secs[q.si]
    items = [(xp, ch, ch if ch != OBJ else "") for ch, xp in zip(q.chars, q.xpos)]
    for m in re.finditer(r"<hp:autoNum\b[^>]*>", s[q.start:q.end]):
        xp = q.start + m.start()
        if any(q2 is not q and q.start < q2.start < xp < q2.end for q2 in doc.sec_paras[q.si]):
            continue
        nt = _attr(m.group(0), "numType") or ""
        items.append((xp, _HF_AUTONUM_SEQ.get(nt, "\x03" + nt), _HF_AUTONUM_TEXT.get(nt, "")))
    items.sort(key=lambda x: x[0])
    return "".join(x[2] for x in items), "".join(x[1] for x in items)


class _HfPara:
    """A paragraph inside an <hp:header> or <hp:footer>, with page-number autoNums read as {page}/{pages} in text
    and as sentinel markers in seq."""
    __slots__ = ("_p", "text", "seq")

    def __init__(self, doc, p):
        self._p = p
        self.text, self.seq = _hf_para_read(doc, p)

    def __getattr__(self, name):
        return getattr(self._p, name)


def _hf_controls(doc, sec_first, kind, apply=None):
    """The section's own 머리말/꼬리말 (or 쪽 번호) controls: (attrs tag, [their paragraphs]) in its first
    paragraph, where Hancom and the engine keep them."""
    s = doc.secs[sec_first.si]
    seg = s[sec_first.start:sec_first.end]
    out = []
    if kind == "pageNum":
        for m in re.finditer(r"<hp:pageNum\b[^>]*/?>", seg):
            out.append((m.group(0), []))
        return out
    for m in re.finditer(r"<hp:%s\b[^>]*>" % kind, seg):
        if apply is not None and 'applyPageType="%s"' % apply not in m.group(0):
            continue
        end = seg.find("</hp:%s>" % kind, m.end())
        a, b = sec_first.start + m.start(), sec_first.start + (end if end >= 0 else len(seg))
        out.append((m.group(0), [_HfPara(doc, q) for q in doc.sec_paras[sec_first.si] if a < q.start < b]))
    return out


def _section_claim(cl, si, i, name, at):
    """page_setup, columns and a section break (name "break") each own a section's settings for the edit; a
    section break also owns the edit's one new section (the engine adds it after the last one)."""
    held = cl.__dict__.setdefault("sections", [])
    for s2, j, op2, _at2 in held:
        if j != i and ((s2 == si and (op2 == name or "break" in (op2, name))) or op2 == name == "break"):
            cl._conflict(i, name, j, op2, at)
    held.append((si, i, name, at))


#: style.create (스타일 추가, F6 > 추가): the fields it takes, and the 글자 모양 keys a style keeps (형광펜 is a
#: mark in the text, not part of a 글자 모양)
STYLE_CREATE_KEYS = ("name", "eng_name", "kind", "based_on", "char", "para")
STYLE_CHAR = {k: v for k, v in CHAR_SHAPE.items() if k != "markpen"}
STYLE_NAME_MAX = 64
NOTE_KINDS = ("FOOT", "END")
NOTE_TEXT_MAX = 2000
CAPTION_SIDES = ("BOTTOM", "TOP", "LEFT", "RIGHT")
CAPTION_TEXT_MAX = 500
TOC_LEADERS = ("DASH", "DOT", "SOLID", "NONE")
_LINK_URL = re.compile(r"^(?:https?://[^/\s?#][^\s]*|mailto:[^@\s]+@[^@\s]+)$", re.I)
_AUTO_STYLE_NAMES = {"footNote": ("Footnote", "각주"), "endNote": ("Endnote", "미주"), "caption": ("Caption", "캡션")}


def _after_candidates(txt, after, hits):
    """Candidates from paragraph text `txt` when note's `after` is missing or matches more than once."""
    if not hits:
        words = txt.split()
        return _cands_near(words, after) or ([txt[:40]] if txt else ["p0"])
    out = []
    for j in hits[:5]:
        a = txt.rfind(" ", 0, j)
        a = 0 if a < 0 else a + 1
        b = txt.find(" ", j + len(after))
        if b < 0:
            b = len(txt)
        else:
            b2 = txt.find(" ", b + 1)
            b = len(txt) if b2 < 0 else b2
        cand = txt[a:b].strip()
        if not cand or cand == after or cand == txt:
            cand = txt[max(0, j - 8):min(len(txt), j + len(after) + 8)].strip() or after
        if cand not in out:
            out.append(cand)
    return out or [txt[:40]]


def _once_in_para(p, sub, op_name, field_name, i, at):
    """ptext offset of `sub` in paragraph `p`; bad_input (with candidates when missing or ambiguous) otherwise."""
    if not isinstance(sub, str) or not sub or _CTRL.search(sub) or "\n" in sub or "\r" in sub:
        raise DocError("bad_input", "%s: %s is non-empty text in the paragraph" % (op_name, field_name), i=i, at=at)
    hits = []
    j = p.ptext.find(sub)
    while j >= 0:
        hits.append(j)
        j = p.ptext.find(sub, j + len(sub))
    if len(hits) != 1:
        why = ("%r does not occur in %s" % (sub, at) if not hits else
               "%r occurs %d times in %s; give a longer %s" % (sub, len(hits), at, field_name))
        raise DocError("bad_input", "%s: %s" % (op_name, why), i=i, at=at,
                       candidates=_after_candidates(p.text, sub, [_pub(p, x) for x in hits]))
    return hits[0]


def _bookmarks_in(d, si=None, para=None, with_before=False):
    """The names of the <hp:bookmark> controls in `d`, in section `si`, or directly inside `para` (with_before:
    [(name, text_before_bookmark_in_para)])."""
    secs = range(len(d.secs)) if si is None else (si,)
    out = []
    for s_i in secs:
        s = d.secs[s_i]
        for m in re.finditer(r"<hp:bookmark\b[^>]*>", s):
            if para is not None:
                host = next((q for q in reversed(d.sec_paras[s_i]) if q.start < m.start() < q.end), None)
                if host is not para:
                    continue
            bname = _xml_unescape(_attr(m.group(0), "name") or "")
            if with_before and para is not None:
                before = "".join(ch for ch, xp in zip(para.chars, para.xpos) if ch != OBJ and xp < m.start())
                out.append((bname, before))
            else:
                out.append(bname)
    return out


def _doc_bookmarks(doc):
    """All bookmark names in `doc` (point <hp:bookmark> controls and BOOKMARK fields)."""
    out = set(_bookmarks_in(doc))
    for q in doc.paras:
        for f in q.fields:
            if (f.get("type") or "").upper() == "BOOKMARK" and f.get("name"):
                out.add(f["name"])
    return out


def _toc_fields(d):
    return [f for q in d.paras for f in q.fields if (f.get("type") or "").upper() == "TABLEOFCONTENTS"]


def _has_toc(d):
    return bool(_toc_fields(d)) or any('type="TABLEOFCONTENTS"' in s for s in d.secs)


def _page_hidings_in(d, p):
    """[{header, footer, page_num, border, fill, master_page}] of direct <hp:pageHiding> controls in `p`."""
    s = d.secs[p.si]
    out = []
    for m in re.finditer(r"<hp:pageHiding\b[^>]*/?>", s[p.start:p.end]):
        pos = p.start + m.start()
        host = next((q for q in reversed(d.sec_paras[p.si]) if q.start < pos < q.end), None)
        if host is not p:
            continue
        tag = m.group(0)
        vals = {k: _attr(tag, attr) for k, attr in HIDE_ATTRS}
        if any(v not in ("0", "1") for v in vals.values()):
            out.append(None)
        else:
            out.append({k: v == "1" for k, v in vals.items()})
    return out


def _new_nums_in(d, p):
    """[(kind, num)] of direct <hp:newNum> controls in paragraph `p`."""
    s = d.secs[p.si]
    out = []
    for m in re.finditer(r"<hp:newNum\b[^>]*/?>", s[p.start:p.end]):
        pos = p.start + m.start()
        host = next((q for q in reversed(d.sec_paras[p.si]) if q.start < pos < q.end), None)
        if host is not p:
            continue
        tag = m.group(0)
        kind = _attr(tag, "numType")
        num = _attr(tag, "num")
        if kind not in NEW_NUM_KINDS or not (num and num.isdigit() and 1 <= int(num) <= 65535):
            out.append((None, None))
        else:
            out.append((kind, int(num)))
    return out


def _act_needed_styles(a):
    if a.note:
        return [_AUTO_STYLE_NAMES[a.note[1]]]
    if a.caption:
        return [_AUTO_STYLE_NAMES["caption"]]
    if a.toc:
        return [("TOC Heading", "차례 제목")] + [("TOC %d" % k, "차례 %d" % k) for k in range(1, a.toc[1] + 1)]
    return []


def _claim_auto_style(doc, cl, i, name, at, eng, ko):
    have = _style_names(doc)
    if eng in have:
        return
    for v in (eng, ko):
        j = cl.created.get(v)
        if j is not None:
            cl._conflict(i, name, j, "style.create", "style %r" % v)
    for v in (eng, ko):
        cl.auto_styles.setdefault(v, (i, name))


def _auto_styles(doc, acts):
    """[(eng, sname, act)] of built-in styles the engine's note_run / caption_xml / toc_xml looks up by
    English name that this document's header.xml does not have yet."""
    have = _style_names(doc)
    for a in acts:
        if a.new_style:
            have.add(a.new_style["name"])
            if a.new_style.get("eng"):
                have.add(a.new_style["eng"])
    out = []
    for a in sorted(acts, key=lambda x: x.i):
        for eng, ko in _act_needed_styles(a):
            if eng not in have:
                sname = ko if ko not in have else eng
                have.update((eng, sname))
                out.append((eng, sname, a))
    return out


def _style_names(doc):
    """Every name a style answers to in this document: its name, its English name and its id."""
    out = set(doc.styles)
    for st in doc.styles.values():
        out.update(x for x in (st.get("name"), st.get("engName")) if x)
    return out


def _style_create(doc, cl, i, op, at):
    """A new paragraph or character style from based_on with the given 글자 모양 / 문단 모양 changes, checked
    against the document's styles before anything runs. A style belongs to the whole document: no at, no
    expect, nothing in the body changes."""
    name = "style.create"
    if at is not None:
        raise DocError("bad_input", "style.create takes no at: a style belongs to the whole document", i=i, at=at)
    extra = sorted(str(k) for k in set(op) - {"op"} - set(STYLE_CREATE_KEYS))
    if extra:
        raise DocError("bad_input", "style.create takes %s, not %s" % (", ".join(STYLE_CREATE_KEYS), extra[0]),
                       i=i, at=at,
                       candidates=_cands_near(list(STYLE_CREATE_KEYS), extra[0]) or list(STYLE_CREATE_KEYS))
    have = _style_names(doc)

    def text(key, need):
        v = op.get(key)
        if v is None and not need:
            return ""
        if not isinstance(v, str) or not v or v != v.strip() or len(v) > STYLE_NAME_MAX or _CTRL.search(v) \
                or re.search(r"[\t\n\r]", v):
            raise DocError("bad_input", "style.create: %s is 1 to %d characters on one line, no control characters "
                           "and no spaces at either end" % (key, STYLE_NAME_MAX), i=i, at=at)
        if v.isdigit():
            raise DocError("bad_input", "style.create: %s cannot be only digits (that reads as a style id)" % key,
                           i=i, at=at)
        if v in have:
            raise DocError("bad_input", "style.create: this document already has a style called %r; pick another "
                           "%s (style.create makes new styles only)" % (v, key), i=i, at=at)
        return v
    sname = text("name", True)
    eng = text("eng_name", False)
    if eng and eng == sname:
        raise DocError("bad_input", "style.create: eng_name is the same as name", i=i, at=at)
    for v in (sname, eng):
        if not v:
            continue
        j = cl.created.get(v)
        if j is not None:
            cl._conflict(i, name, j, name, "style %r" % v)
        if v in cl.auto_styles:
            j2, op2 = cl.auto_styles[v]
            cl._conflict(i, name, j2, op2, "style %r" % v)
    kind = _enum(op.get("kind"), ("PARA", "CHAR"), "style.create: kind", i, at, "PARA")
    base = op.get("based_on", "바탕글")
    if not isinstance(base, str) or base not in have:
        raise DocError("bad_input", "style.create: no style %r in this document to base it on" % (base,), i=i,
                       at=at, candidates=_cands_near([st["name"] for st in doc.styles.values()], str(base)))
    char = para = None
    if "char" in op:
        if isinstance(op["char"], dict) and "markpen" in op["char"]:
            raise DocError("bad_input", "style.create: char has no markpen (형광펜 is a mark in the text, not part "
                           "of a style's 글자 모양)", i=i, at=at)
        char = _shape_fmt(name, op, i, at, table=STYLE_CHAR, key="char")
    if "para" in op:
        if kind == "CHAR":
            raise DocError("bad_input", "style.create: a character style (kind char) keeps no 문단 모양; leave out "
                           "para or use kind para", i=i, at=at)
        para = _shape_fmt(name, op, i, at, table=PARA_SHAPE, key="para")
    for v in (sname, eng):
        if v:
            cl.created[v] = i
    first = doc.top[0]
    kw = {"name": sname, "base": base, "kind": kind}
    if eng:
        kw["eng_name"] = eng
    if char:
        kw["char"] = _char_engine_fmt(char)
    if para:
        kw["para"] = _para_engine_fmt(para)
    # intra -i: style.create ops run in input order, so the new styles get ids in that order
    a = _Act(i, name, None, first, first.start, side=0, intra=-i, rank=0,
             steps=[{"op": "create_style", "kwargs": kw}])
    a.new_style = {"name": sname, "eng": eng, "kind": kind, "char": char or {}, "para": para or {}}
    return a


def _plan_op(doc, cl, i, name, op, at):
    acts = []

    def set_cell(c, text, cat):
        for q in c.paras:
            _need_text_para(q, cat, i)
        for q in c.paras:
            cl.span(q, 0, len(q.chars), i, name, whole=True)
        for q in c.paras[1:]:
            cl.remove(q.si, q.start, q.end, i, name, cat)
        a = _Act(i, name, cat, c.paras[0], max(q.start for q in c.paras), steps=_set_cell_steps(c, text),
                 fb=("set_cell", c, text))
        a.cell_dels = [(c, k) for k in range(1, len(c.paras))]
        _adds_for(doc, a, c.paras[0], text.count("\n"))
        a.text_of = c.paras[0]
        acts.append(a)

    def set_para(p, text, pat, rng=None):
        if rng is None:
            _need_text_para(p, pat, i)
            a0, b0 = 0, len(p.chars)
            cl.span(p, a0, b0, i, name, whole=True)
            a = _Act(i, name, pat, p, p.start, steps=_set_para_steps(p, text), fb=("set_para", p, text))
        else:
            a0 = _ppos(p, rng[0])
            b0 = _ppos(p, rng[1] - 1) + 1 if rng[1] > rng[0] else a0
            if any(ch == OBJ for ch in p.chars[a0:b0]):
                raise DocError("bad_input", "%s holds an object; set text around it" % pat, i=i, at=pat)
            cl.span(p, a0, b0, i, name)
            a = _Act(i, name, pat, p, p.start, intra=a0, rank=1 if b0 > a0 else 0,
                     steps=_span_steps(p, a0, b0, text), fb=("replace", p, a0, b0 - a0, text))
        _adds_for(doc, a, p, text.count("\n"))
        a.text_of = p
        acts.append(a)

    if name == "set":
        text = _clean(op.get("text"), "set: text", i, at)
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        if r.get("cell") is not None and r["kind"] in ("cell", "place"):
            _check_expect(op, i, at, _cell_text(r["cell"]), r.get("table"))
            set_cell(r["cell"], text, at)
        else:
            p = r["para"]
            rng = r.get("range")
            _check_expect(op, i, at, p.text[rng[0]:rng[1]] if rng else p.text)
            set_para(p, text, at, rng)
    elif name == "replace":
        find_ = op.get("find")
        if not isinstance(find_, str) or not find_:
            raise DocError("bad_input", "replace needs find (non-empty text)", i=i, at=at)
        with_ = _clean(op.get("with"), "replace: with", i, at)
        exp = op.get("expect")
        r = None
        if at is not None:
            r = resolve(doc, at, allow=("para", "cell", "cellpara", "row", "table", "heading", "place"))
            scope = [q for q in r["paras"] if q is not None]
            if isinstance(exp, str):
                if r.get("range"):
                    actual = r["para"].text[r["range"][0]:r["range"][1]]
                elif r["kind"] == "table":
                    actual = _table_text(r["table"])
                elif r["kind"] == "row":
                    actual = _table_text(r["table"], {r["row"]})
                elif r.get("cell") is not None and r["kind"] in ("cell", "place"):
                    actual = _cell_text(r["cell"])
                else:
                    actual = "\n".join(q.text for q in scope)
                _check_expect(op, i, at, actual)
        else:
            if isinstance(exp, str):
                raise DocError("bad_input", "expect as text needs at (the text it is compared with)", i=i)
            scope = [q for q in doc.paras if para_address(doc, q) is not None]
        hits = []
        for q in scope:
            pt = q.ptext
            j = pt.find(find_)
            while j >= 0:
                if r is None or not r.get("range") or (
                        r["range"][0] <= _pub(q, j) and _pub(q, j) + len(find_) <= r["range"][1]):
                    hits.append((q, j))
                j = pt.find(find_, j + len(find_))
        if len(hits) > 1 and not op.get("all"):
            raise DocError("ambiguous_match", "%r occurs %d times; narrow it with at (a candidate), or pass "
                           "all=true" % (find_, len(hits)), at=at, i=i, total=len(hits),
                           candidates=["%s:%d-%d" % (para_address(doc, q), _pub(q, j), _pub(q, j) + len(find_))
                                       for q, j in hits])
        if _is_int(exp) and len(hits) != exp:
            raise DocError("expect_mismatch", "replace expected %d occurrences of %r, found %d" % (
                exp, find_, len(hits)), at=at, i=i, expected=exp, actual=len(hits))
        if not hits:
            raise DocError("not_found", "%r does not occur%s" % (find_, " in %s" % at if at else ""), at=at, i=i)
        for q, j in hits:
            cl.span(q, j, j + len(find_), i, name)
            a = _Act(i, name, para_address(doc, q), q, q.start, intra=j,
                     steps=_span_steps(q, j, j + len(find_), with_), fb=("replace", q, j, len(find_), with_))
            _adds_for(doc, a, q, with_.count("\n"))
            a.text_of = q
            acts.append(a)
    elif name == "insert_after":
        md = op.get("markdown", op.get("text"))
        if not isinstance(md, str):
            raise DocError("bad_input", "insert_after needs markdown", i=i, at=at)
        lines = _md_lines(_clean(md, "insert_after: markdown", i, at))
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
        cl.touch(p.si, p.start, i, name, at)
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
        a = _Act(i, name, at, p, p.end, side=0, rank=0, steps=steps, info={"lines": len(lines)})
        _adds_for(doc, a, p, len(lines))
        acts.append(a)
    elif name == "delete":
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "table", "place"))
        if r["kind"] == "table":
            t = r["table"]
            _check_expect(op, i, at, _table_text(t))
            cl.remove(t.si, t.start, t.end, i, name, at)
            c0 = t.cells[0]
            a = _Act(i, name, at, c0.paras[0], t.start,
                     steps=[["goto_cell", t.lt, c0.row, c0.col, False, t.si], ["delete_table"]])
            a.tbl_dels = _tables_within(doc, t.si, t.start, t.end)
            acts.append(a)
        elif r.get("cell") is not None and r["kind"] in ("cell", "place"):
            _check_expect(op, i, at, _cell_text(r["cell"]), r.get("table"))
            set_cell(r["cell"], "", at)
        else:
            p = r["para"]
            _check_expect(op, i, at, p.text)
            cl.remove(p.si, p.start, p.end, i, name, at)
            a = _Act(i, name, at, p, p.start, steps=[["delete_paragraph", p.k, p.si]])
            if p.top:
                a.top_dels = [p.gp]
            elif p.cell is not None:
                a.cell_dels = [(p.cell, p.cell.paras.index(p))]
            else:
                a.info["unmapped"] = True
            a.tbl_dels = _tables_within(doc, p.si, p.start, p.end)
            acts.append(a)
    elif name == "table.set_cells":
        grid = op.get("grid")
        if not isinstance(grid, list) or not grid or not all(isinstance(rw, list) for rw in grid):
            raise DocError("bad_input", "table.set_cells needs grid: [[text, ...], ...]", i=i, at=at)
        r = resolve(doc, at, allow=("table", "cell"))
        t = r["table"]
        r0, c0 = (r["cell"].row, r["cell"].col) if r["kind"] == "cell" else (0, 0)
        done = set()
        for di, rw in enumerate(grid):
            for dj, val in enumerate(rw):
                if val is None:
                    continue
                if isinstance(val, bool) or not isinstance(val, (str, int, float)):
                    raise DocError("bad_input", "grid values are text, numbers or None", i=i, at=at)
                rr, cc = r0 + di, c0 + dj
                c = t.at(rr, cc) if rr < t.rows and cc < t.cols else None
                if c is None:
                    raise DocError("bad_address", "table %s has no cell at row %d, column %d"
                                   % (t.addr, rr, cc), at="%s/r%d/c%d" % (t.addr, rr, cc), i=i,
                                   candidates=["%s/r%d/c%d" % (t.addr, min(rr, t.rows - 1), min(cc, t.cols - 1))])
                if id(c) in done or (c.row, c.col) != (rr, cc):
                    raise DocError("bad_address", "%s/r%d/c%d is inside the merged cell %s; "
                                   "put None there" % (t.addr, rr, cc, cell_address(t, c)),
                                   at="%s/r%d/c%d" % (t.addr, rr, cc), i=i,
                                   candidates=[cell_address(t, c)])
                done.add(id(c))
                cat = cell_address(t, c)
                set_cell(c, _clean(str(val), "grid value", i, cat), cat)
    elif name in ("table.add_row", "table.delete_row"):
        r = resolve(doc, at, allow=("table", "row", "cell"))
        t = r["table"]
        _table_mark(cl, t, i, name, at, "rows")
        here = r.get("row", r["cell"].row if r.get("cell") is not None else None)
        if name == "table.add_row":
            after = op.get("after", here)
            if not _is_int(after) or not 0 <= after < t.rows:
                raise DocError("bad_address", "table.add_row: after must be a row of %s (0..%d)"
                               % (t.addr, t.rows - 1), at=at, i=i, range=[0, t.rows - 1])
            like = op.get("like", after)
            if not _is_int(like) or like not in (after, after + 1) or like >= t.rows:
                raise DocError("bad_input", "table.add_row: like must be the row before or after the new "
                               "one (%d or %d)" % (after, after + 1), at=at, i=i)
            cands = [x for x in t.row_cells(like) if x.rs == 1] or t.row_cells(like)
            if not cands:
                raise DocError("bad_address", "row %d of %s starts no cell" % (like, t.addr), at=at, i=i)
            c = cands[0]
            for row in {after, like}:
                reg = _row_region(t, row)
                if reg:
                    cl.touch(t.si, reg[0], i, name, "%s/r%d" % (t.addr, row))
            steps = [["goto_cell", t.lt, c.row, c.col, False, t.si], ["insert_row", like == after]]
            vals = op.get("values", op.get("cells"))
            if vals is not None:
                if not isinstance(vals, list) or not all(v is None or isinstance(v, (str, int, float))
                                                         and not isinstance(v, bool) for v in vals):
                    raise DocError("bad_input", "table.add_row: values is a list of texts", at=at, i=i)
                for j, v in enumerate(vals):
                    if v not in (None, ""):
                        steps += [["goto_table_cell", after + 1, j], ["type", _clean(str(v), "value", i, at)]]
            anchor = _row_region(t, after)[1] if _row_region(t, after) else c.end
            a = _Act(i, name, at, c.paras[0], anchor, side=0, rank=0, steps=steps)
            a.row_adds = [(t.g, after)]
            acts.append(a)
        else:
            row = op.get("row", here)
            if not _is_int(row) or not 0 <= row < t.rows:
                raise DocError("bad_address", "table.delete_row needs a row of %s (%s/rN)" % (t.addr, t.addr),
                               at=at, i=i, range=[0, t.rows - 1],
                               candidates=["%s/r%d" % (t.addr, x) for x in range(min(t.rows, 5))])
            cands = [x for x in t.row_cells(row) if x.rs == 1] or t.row_cells(row)
            if not cands:
                raise DocError("bad_address", "row %d of %s starts no cell" % (row, t.addr), at=at, i=i)
            _check_expect(op, i, at, _table_text(t, {row}))
            reg = _row_region(t, row)
            rat = "%s/r%d" % (t.addr, row)
            cl.remove(t.si, reg[0], reg[1], i, name, rat)
            c = cands[0]
            a = _Act(i, name, rat, c.paras[0], reg[0],
                     steps=[["goto_cell", t.lt, c.row, c.col, False, t.si], ["delete_row"]])
            a.row_dels = [(t.g, row)]
            a.tbl_dels = [g for g in _tables_within(doc, t.si, reg[0], reg[1]) if g != t.g]
            acts.append(a)
    elif name == "table.cell_style":
        extra = sorted(set(op) - {"op", "at", "to", "set"})
        if extra:
            raise DocError("bad_input", "table.cell_style takes at, to, set, not %s" % extra[0], i=i, at=at,
                           candidates=["at", "to", "set"])
        want = _style_set(op, CELL_STYLE_KEYS, i, at, name)
        kw, sides = {}, None
        if "border" in want:
            sides = _border_sides(want["border"], i, at)
        if "fill" in want:
            f = want["fill"]
            if f is not None and not (isinstance(f, str) and (_COLOR.match(f) or f.lower() == "none")):
                raise DocError("bad_input", 'fill is #RRGGBB, or null / "none" for no fill', i=i, at=at)
            kw["fill"] = None if f is None or f.lower() == "none" else f.upper()
        if "valign" in want:
            kw["valign"] = _enum(want["valign"], CELL_VALIGN, "valign", i, at)
        if "margin_mm" in want:
            kw["margin_mm"] = _margin(want["margin_mm"], i, at)
        if "header" in want:
            kw["header"] = _bool(want["header"], "header", i, at)
        r = resolve(doc, at, allow=("table", "row", "cell"))
        t = r["table"]
        if t.addr is None:
            raise DocError("bad_address", "%s only works on a body table" % name, i=i, at=at)
        if r["kind"] == "table":
            ra, rb, ca, cb = 0, t.rows - 1, 0, t.cols - 1
        elif r["kind"] == "row":
            ra, rb, ca, cb = _merge_rect(t, r["row"], 0, r["row"], t.cols - 1)
        else:
            c1 = r["cell"]
            ra, rb, ca, cb = _merge_rect(t, c1.row, c1.col, c1.row + c1.rs - 1, c1.col + c1.cs - 1)
        if "to" in op:
            if r["kind"] != "cell" or not isinstance(op["to"], str):
                raise DocError("bad_input", "to (the block's other corner cell) goes with at a cell", i=i, at=at)
            r2 = resolve(doc, op["to"], allow=("cell",))
            if r2["table"] is not t:
                raise DocError("bad_address", "to must be a cell of %s" % t.addr, i=i, at=op["to"])
            c2 = r2["cell"]
            ra, rb, ca, cb = _merge_rect(t, min(ra, c2.row), min(ca, c2.col),
                                         max(rb, c2.row + c2.rs - 1), max(cb, c2.col + c2.cs - 1))
        _table_mark(cl, t, i, name, at, "cell", (ra, rb, ca, cb), border=sides is not None)
        block = [x for x in t.cells if ra <= x.row <= rb and ca <= x.col <= cb]
        for x in block:
            cl.touch(t.si, x.start, i, name, at)
        first = t.at(ra, ca)
        head = [["goto_cell", t.lt, ra, ca, False, t.si], ["cell_block", rb, cb]]
        steps = []
        if sides is not None:
            # as Hancom's 셀 테두리: each block cell's sides, and the neighbour across a side gets it too
            steps += head + [{"op": "cell_border_fill", "kwargs": {"sides": sides}}]
        if kw:
            steps += head + [{"op": "set_cell", "kwargs": kw}]
        a = _Act(i, name, at, first.paras[0], t.start, steps=steps)
        a.restyled = [t.g]
        acts.append(a)
    elif name == "table.style":
        extra = sorted(set(op) - {"op", "at", "set"})
        if extra:
            raise DocError("bad_input", "table.style takes at, set, not %s" % extra[0], i=i, at=at,
                           candidates=["at", "set"])
        want = _style_set(op, TABLE_STYLE_KEYS, i, at, name)
        kw = {}
        if "repeat_header" in want:
            kw["repeat_header"] = _bool(want["repeat_header"], "repeat_header", i, at)
        if "page_break" in want:
            kw["page_break"] = _enum(want["page_break"], TABLE_PAGE_BREAK, "page_break", i, at)
        r = resolve(doc, at, allow=("table",))
        t = r["table"]
        if t.addr is None:
            raise DocError("bad_address", "%s only works on a body table" % name, i=i, at=at)
        _table_mark(cl, t, i, name, at, "table")
        cl.touch(t.si, t.start, i, name, at)
        c0 = t.cells[0]
        a = _Act(i, name, at, c0.paras[0], t.start,
                 steps=[["goto_cell", t.lt, c0.row, c0.col, False, t.si], {"op": "set_table", "kwargs": kw}])
        a.restyled = [t.g]
        acts.append(a)
    elif name in TABLE_SHAPE_OPS:
        known = {"table.merge": ("to",), "table.split": ("rows", "cols"), "table.add_col": ("after", "like"),
                 "table.delete_col": ("col", "expect"),
                 "table.size": ("width_mm", "height_mm", "col_widths_mm", "row_heights_mm")}[name]
        extra = sorted(set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "%s takes %s, not %s" % (name, ", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=list(known))
        r = resolve(doc, at, allow=("table", "row", "cell") if name == "table.size" else
                    ("cell",) if name in ("table.merge", "table.split") else ("table", "cell"))
        t = r["table"]
        if t.addr is None:
            raise DocError("bad_address", "%s only works on a body table" % name, i=i, at=at)
        here = r["cell"] if r.get("cell") is not None else None
        a = None
        if name == "table.merge":
            to = op.get("to")
            if not isinstance(to, str):
                raise DocError("bad_input", "table.merge needs to: the cell at the block's other corner", i=i, at=at)
            r2 = resolve(doc, to, allow=("cell",))
            if r2["table"] is not t:
                raise DocError("bad_address", "to must be a cell of %s" % t.addr, i=i, at=to)
            c2 = r2["cell"]
            ra, rb, ca, cb = _merge_rect(t, here.row, here.col, c2.row, c2.col)
            inside = sorted((x for x in t.cells if ra <= x.row <= rb and ca <= x.col <= cb),
                            key=lambda x: (x.row, x.col))
            if len(inside) < 2:
                raise DocError("bad_input", "%s and %s are one cell already" % (at, to), i=i, at=at)
            first = inside[0]
            for x in inside[1:]:
                if any(t2.parent is x for t2 in doc.tables):
                    raise DocError("bad_input", "%s holds a table; merging cells that hold a table is not "
                                   "supported" % cell_address(t, x), i=i, at=cell_address(t, x))
            a = _Act(i, name, at, first.paras[0], t.start, steps=[
                ["goto_cell", t.lt, ra, ca, False, t.si], ["cell_block", rb, cb], ["merge_cells"]])
            a.merges = [(t.g, first, inside, (rb - ra + 1, cb - ca + 1))]
        elif name == "table.split":
            n = {}
            for k in ("rows", "cols"):
                v = op.get(k, 1)
                if not _is_int(v) or not 1 <= v <= SPLIT_MAX:
                    raise DocError("bad_input", "%s is a whole number from 1 to %d" % (k, SPLIT_MAX),
                                   i=i, at=at, range=[1, SPLIT_MAX])
                n[k] = v
            if n["rows"] == n["cols"] == 1:
                raise DocError("bad_input", "table.split needs rows or cols above 1", i=i, at=at)
            for k, span in (("rows", here.rs), ("cols", here.cs)):
                if span > 1 and span % n[k]:
                    ok = [d for d in range(1, span + 1) if span % d == 0]
                    raise DocError("bad_input", "%s spans %d %s; it splits into %s %s" % (
                        at, span, k, " or ".join(map(str, ok)), k), i=i, at=at, candidates=ok)
            a = _Act(i, name, at, here.paras[0], t.start, steps=[
                ["goto_cell", t.lt, here.row, here.col, False, t.si],
                {"op": "split_cell", "kwargs": {"rows": n["rows"], "cols": n["cols"]}}])
            a.splits = [(t.g, here, n["rows"], n["cols"])]
            if here.rs == 1:
                a.row_adds = [(t.g, here.row)] * (n["rows"] - 1)
            if here.cs == 1:
                a.col_adds = [(t.g, here.col)] * (n["cols"] - 1)
        elif name == "table.add_col":
            after = op.get("after", here.col + here.cs - 1 if here is not None else None)
            if not _is_int(after) or not 0 <= after < t.cols:
                raise DocError("bad_address", "table.add_col: after must be a column of %s (0..%d)"
                               % (t.addr, t.cols - 1), at=at, i=i, range=[0, t.cols - 1])
            like = op.get("like", after)
            if not _is_int(like) or like not in (after, after + 1) or like >= t.cols:
                raise DocError("bad_input", "table.add_col: like must be the column before or after the new "
                               "one (%d or %d)" % (after, after + 1), at=at, i=i)
            cands = [x for x in _col_cells(t, like) if x.cs == 1]
            if not cands:
                raise DocError("bad_address", "no cell of %s sits in column %d alone" % (t.addr, like),
                               at=at, i=i)
            c = cands[0]
            a = _Act(i, name, at, c.paras[0], t.start, steps=[
                ["goto_cell", t.lt, c.row, c.col, False, t.si], ["insert_column", like == after]])
            a.col_adds = [(t.g, after)]
            ref = {id(x): x for x in (t.at(rr, like) for rr in range(t.rows)) if x is not None}
            a.cell_delta = [(t.g, sum(1 for x in ref.values() if not x.col < after + 1 < x.col + x.cs))]
        elif name == "table.delete_col":
            col = op.get("col", here.col if here is not None else None)
            if not _is_int(col) or not 0 <= col < t.cols:
                raise DocError("bad_address", "table.delete_col needs a column of %s (col 0..%d, or a cell)"
                               % (t.addr, t.cols - 1), at=at, i=i, range=[0, t.cols - 1])
            if t.cols == 1:
                raise DocError("bad_input", "%s has one column; delete the table instead" % t.addr, at=at, i=i)
            cands = [x for x in _col_cells(t, col) if x.cs == 1]
            if not cands:
                raise DocError("bad_address", "no cell of %s sits in column %d alone" % (t.addr, col),
                               at=at, i=i)
            grid = _table_block(None, t)["cells"]
            _check_expect(op, i, at, "\n".join(grid[rr][col] for rr in range(t.rows)))
            c = cands[0]
            a = _Act(i, name, at, c.paras[0], t.start, steps=[
                ["goto_cell", t.lt, c.row, c.col, False, t.si], ["delete_column"]])
            a.col_dels = [(t.g, col)]
            a.tbl_dels = [g for x in _col_cells(t, col) if x.cs == 1
                          for g in _tables_within(doc, t.si, x.start, x.end)]
        else:   # table.size
            ws, hs = {}, {}
            for k, sizes, what, lst in (("width_mm", ws, "column", "col_widths_mm"),
                                        ("height_mm", hs, "row", "row_heights_mm")):
                if k not in op:
                    continue
                if here is None and not (k == "height_mm" and r["kind"] == "row"):
                    raise DocError("bad_address", "%s sets the %s of the cell at; address a cell, or use %s on "
                                   "the table" % (k, what, lst), i=i, at=at)
                if here is not None and (here.cs if what == "column" else here.rs) > 1:
                    raise DocError("bad_address", "%s spans more than one %s; use %s on the table"
                                   % (at, what, lst), i=i, at=at)
                idx = r["row"] if here is None else (here.col if what == "column" else here.row)
                sizes[idx] = _mm_value(op[k], k, i, at)
            for k, sizes, count in (("col_widths_mm", ws, t.cols), ("row_heights_mm", hs, t.rows)):
                if k in op:
                    v = op[k]
                    if r["kind"] != "table":
                        raise DocError("bad_address", "%s goes on the table (%s), not a row or cell" % (k, t.addr),
                                       i=i, at=at, candidates=[t.addr])
                    if not isinstance(v, list) or not v or len(v) > count:
                        raise DocError("bad_input", "%s is a list of 1 to %d sizes in millimetres (null keeps "
                                       "one)" % (k, count), i=i, at=at, range=[1, count])
                    for j, x in enumerate(v):
                        x = _mm_value(x, "%s[%d]" % (k, j), i, at, none_ok=True)
                        if x is not None:
                            if j in sizes:
                                raise DocError("bad_input", "%s[%d] is set twice" % (k, j), i=i, at=at)
                            sizes[j] = x
            if not ws and not hs:
                raise DocError("bad_input", "table.size needs width_mm, height_mm, col_widths_mm or "
                               "row_heights_mm", i=i, at=at)
            c0 = here or t.cells[0]
            steps = [["goto_cell", t.lt, c0.row, c0.col, False, t.si]]
            steps += [["set_column_width", w, j] for j, w in sorted(ws.items())]
            steps += [["set_row_height", h, j] for j, h in sorted(hs.items())]
            a = _Act(i, name, at, c0.paras[0], t.start, steps=steps)
            a.resized = [t.g]
        _shape_claim(cl, t, i, name, at)
        acts.append(a)
    elif name == "fill":
        pid = op.get("place")
        if not isinstance(pid, str) or not pid:
            raise DocError("bad_input", "fill needs place and text", i=i)
        text = _clean(op.get("text"), "fill: text", i, at)
        addr = pid if pid.startswith("place:") else "place:" + pid
        at = addr
        r = resolve(doc, addr)
        pl = r["place"]
        kind = pl.get("kind")
        _check_expect(op, i, at, pl.get("value", ""))
        if pl.get("cell") is not None and kind == "cell":
            set_cell(pl["cell"], text, at)
        elif kind == "field":
            f, p = pl["field"], pl["para"]
            b, e = f["b"], f["e"]
            if any(ch == OBJ for ch in p.chars[b:e]):
                raise DocError("bad_input", "the field %s holds an object" % at, at=at, i=i)
            cl.span(p, b, e, i, name)
            a = _Act(i, name, at, p, p.start, intra=b, rank=1 if e > b else 0, steps=_span_steps(p, b, e, text),
                     fb=("field", p, f["id"], text))
            _adds_for(doc, a, p, text.count("\n"))
            a.text_of = p
            acts.append(a)
        else:
            p = pl["para"]
            pt = p.ptext
            if kind == "body" or not pt.strip():
                set_para(p, text, at)
            elif kind == "cover_placeholder":
                lab = pl.get("label") or ""
                j = pt.find(lab) if lab else -1
                if j < 0:
                    raise DocError("bad_address", "the placeholder of %s is gone" % at, at=at, i=i)
                cl.span(p, j, j + len(lab), i, name)
                a = _Act(i, name, at, p, p.start, intra=j, steps=_span_steps(p, j, j + len(lab), text),
                         fb=("replace", p, j, len(lab), text))
                _adds_for(doc, a, p, text.count("\n"))
                a.text_of = p
                acts.append(a)
            else:   # a label line: keep "label:" and the white space after it, replace what follows
                ll = label_line(pt)
                if ll is None:
                    raise DocError("bad_address", "%s is no longer a label line" % at, at=at, i=i)
                j, b = ll["at"], len(pt)
                if not pt[j - 1:j].isspace():
                    text = " " + text
                if any(ch == OBJ for ch in p.chars[j:b]):
                    raise DocError("bad_input", "the value of %s holds an object" % at, at=at, i=i)
                cl.span(p, j, b, i, name)
                a = _Act(i, name, at, p, p.start, intra=j, rank=1 if b > j else 0,
                         steps=_span_steps(p, j, b, text), fb=("replace", p, j, b - j, text) if b > j
                         else ("insert", p, j, text))
                _adds_for(doc, a, p, text.count("\n"))
                a.text_of = p
                acts.append(a)
    elif name == "style":
        sty = op.get("style")
        if not isinstance(sty, str) or not sty:
            raise DocError("bad_input", "style needs a style name", i=i, at=at)
        if sty not in {s["name"] for s in doc.styles.values()} | set(doc.styles) | {
                s["engName"] for s in doc.styles.values()}:
            if sty in cl.new_styles:
                raise DocError("bad_input", "style %r is made by op %d (style.create) in this edit; apply it in "
                               "a later edit, once the document has it" % (sty, cl.new_styles[sty]), i=i, at=at)
            raise DocError("bad_input", "no style %r in this document" % sty, i=i, at=at,
                           candidates=_cands_near([s["name"] for s in doc.styles.values()], sty))
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        for q in r["paras"]:
            _no_list_twice(cl, q, i, name, at)
            acts.append(_Act(i, name, at, q, q.start, side=2, steps=[["goto", q.k, 0, q.si], ["apply_style", sty]]))
    elif name == "style.create":
        acts.append(_style_create(doc, cl, i, op, at))
    elif name == "note":
        known = ("text", "kind", "after", "expect")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "note takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        kind = _enum(op.get("kind"), NOTE_KINDS, "note: kind", i, at, "FOOT")
        nkind = "footNote" if kind == "FOOT" else "endNote"
        text = _clean(op.get("text"), "note: text", i, at)
        if not text.strip() or not 1 <= len(text) <= NOTE_TEXT_MAX:
            raise DocError("bad_input", "note: text is 1 to %d characters" % NOTE_TEXT_MAX, i=i, at=at)
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        if r.get("range"):
            raise DocError("bad_address", "note takes a whole paragraph, not a character range", i=i, at=at)
        if r.get("cell") is not None and r["kind"] in ("cell", "place"):
            _check_expect(op, i, at, _cell_text(r["cell"]), r.get("table"))
            p = r["cell"].paras[-1]
        else:
            p = r["para"]
            _check_expect(op, i, at, p.text)
        after = op.get("after")
        pos = _once_in_para(p, after, "note", "after", i, at) + len(after) if after is not None else len(p.chars)
        _claim_auto_style(doc, cl, i, name, at, *_AUTO_STYLE_NAMES[nkind])
        cl.span(p, 0, len(p.chars), i, name, whole=True)
        step = ({"op": "insert_footnote", "kwargs": {"text": text, "kind": "footNote"}} if kind == "FOOT"
                else {"op": "insert_endnote", "kwargs": {"text": text}})
        a = _Act(i, name, at, p, p.start, side=1, intra=pos, rank=0,
                 steps=[["goto", p.k, pos, p.si], step])
        a.note = (p, nkind, text)
        acts.append(a)
    elif name == "caption":
        known = ("text", "side")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "caption takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        side = _enum(op.get("side"), CAPTION_SIDES, "caption: side", i, at, "BOTTOM")
        text = _clean(op.get("text"), "caption: text", i, at)
        if not text.strip() or not 1 <= len(text) <= CAPTION_TEXT_MAX or "\n" in text:
            raise DocError("bad_input", "caption: text is 1 to %d characters on one line" % CAPTION_TEXT_MAX,
                           i=i, at=at)
        r = resolve(doc, at, allow=("table",))
        t = r["table"]
        if t.addr is None:
            raise DocError("bad_address", "caption only works on a body table", i=i, at=at)
        if t.caption:
            raise DocError("bad_input", "table %s already has a caption (%r)"
                           % (t.addr, " ".join(q.text for q in t.caption).strip()), i=i, at=at)
        _claim_auto_style(doc, cl, i, name, at, *_AUTO_STYLE_NAMES["caption"])
        _table_mark(cl, t, i, name, at, "table")
        cl.touch(t.si, t.start, i, name, at)
        c0 = t.cells[0]
        a = _Act(i, name, at, c0.paras[0], t.start, side=0,
                 steps=[{"op": "insert_caption", "kwargs": {"text": text, "side": side, "obj": t.id}}])
        a.restyled = [t.g]
        a.caption = (t.g, side, text)
        acts.append(a)
    elif name == "bookmark":
        known = ("name", "after")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "bookmark takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        bname = op.get("name")
        if not isinstance(bname, str) or not bname.strip() or bname != bname.strip() \
                or len(bname) > STYLE_NAME_MAX or _CTRL.search(bname) or re.search(r"[\t\n\r]", bname):
            raise DocError("bad_input", "bookmark: name is 1 to %d characters on one line, no control characters"
                           % STYLE_NAME_MAX, i=i, at=at)
        if bname in _doc_bookmarks(doc):
            raise DocError("bad_input", "bookmark: this document already has a bookmark called %r" % bname,
                           i=i, at=at)
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        if r.get("range"):
            raise DocError("bad_address", "bookmark takes a whole paragraph, not a character range", i=i, at=at)
        p = r["cell"].paras[-1] if (r.get("cell") is not None and r["kind"] in ("cell", "place")) else r["para"]
        after = op.get("after")
        pos = _once_in_para(p, after, "bookmark", "after", i, at) + len(after) if after is not None else len(p.chars)
        cl.span(p, 0, len(p.chars), i, name, whole=True)
        if bname in cl.bookmarks:
            raise DocError("bad_input", "bookmark: duplicate bookmark name %r in this edit (already at op %d)"
                           % (bname, cl.bookmarks[bname]), i=i, at=at)
        cl.bookmarks[bname] = i
        a = _Act(i, name, at, p, p.start, side=1, intra=pos, rank=0,
                 steps=[["goto", p.k, pos, p.si], {"op": "insert_bookmark", "kwargs": {"name": bname}}])
        a.bookmark = (p, bname, after)
        acts.append(a)
    elif name == "link":
        known = ("phrase", "target")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "link takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        if r.get("range"):
            raise DocError("bad_address", "link takes a whole paragraph, not a character range", i=i, at=at)
        p = r["cell"].paras[-1] if (r.get("cell") is not None and r["kind"] in ("cell", "place")) else r["para"]
        phrase = op.get("phrase")
        pos = _once_in_para(p, phrase, "link", "phrase", i, at)
        target = op.get("target")
        if not isinstance(target, str) or not target or target != target.strip() or len(target) > 2048 \
                or _CTRL.search(target) or re.search(r"[\t\n\r]", target):
            raise DocError("bad_input", "link: target is an http(s):// or mailto: URL, or #bookmark", i=i, at=at)
        if target.startswith("#"):
            bname = target[1:]
            have_bm = _doc_bookmarks(doc) | set(cl.bookmarks)
            if not bname or len(bname) > STYLE_NAME_MAX or _CTRL.search(bname) or bname not in have_bm:
                raise DocError("bad_input", "link: no bookmark %r in this document" % bname, i=i, at=at,
                               candidates=["#" + x for x in sorted(have_bm)][:8] if have_bm else None)
        elif not _LINK_URL.match(target):
            raise DocError("bad_input", "link: target must be an http(s):// or mailto: URL, or #bookmark", i=i, at=at)
        cl.span(p, 0, len(p.chars), i, name, whole=True)
        steps = [["goto", p.k, pos, p.si], ["select", len(phrase)], ["delete"],
                 {"op": "insert_hyperlink", "kwargs": {"text": phrase, "target": target}}]
        a = _Act(i, name, at, p, p.start, side=1, intra=pos, rank=1, steps=steps)
        a.link = (p, phrase, target)
        acts.append(a)
    elif name == "toc":
        known = ("levels", "leader")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "toc takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        levels = op.get("levels", 2)
        if not _is_int(levels) or not 1 <= levels <= 3:
            raise DocError("bad_input", "toc: levels is 1 to 3", i=i, at=at, range=[1, 3])
        leader = _enum(op.get("leader"), TOC_LEADERS, "toc: leader", i, at, "DASH")
        r = resolve(doc, at, allow=("para", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "toc takes a whole paragraph, not a character range", i=i, at=at)
        p = r["para"]
        if not p.top:
            raise DocError("bad_address", "toc needs a body paragraph, not one in a table, note or box", i=i, at=at)
        if _has_toc(doc):
            raise DocError("bad_input", "toc: this document already has a table of contents", i=i, at=at)
        cl.span(p, 0, len(p.chars), i, name, whole=True)
        if cl.toc_op is not None:
            raise DocError("bad_input", "toc: only one table of contents per edit (already at op %d)" % cl.toc_op,
                           i=i, at=at)
        for eng, ko in [("TOC Heading", "차례 제목")] + [("TOC %d" % k, "차례 %d" % k) for k in range(1, levels + 1)]:
            _claim_auto_style(doc, cl, i, name, at, eng, ko)
        cl.toc_op = i
        n_heads = sum(1 for q in doc.top if (doc.para_heading.get(q.pr) or ("", 99))[0] == "OUTLINE"
                      and doc.para_heading[q.pr][1] < levels)
        n_added = 2 + n_heads
        steps = [["goto", p.k, 0, p.si],
                 {"op": "insert_toc", "kwargs": {"levels": levels, "leader": leader, "tables": False,
                                                 "pictures": False, "equations": False}}]
        a = _Act(i, name, at, p, p.end, side=0, rank=0, steps=steps)
        _adds_for(doc, a, p, n_added)
        a.toc = (p, levels, leader, n_added)
        acts.append(a)
    elif name in ("char_shape", "para_shape"):
        fmt = _shape_fmt(name, op, i, at)
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "row", "table", "heading", "place"))
        rng = r.get("range")
        paras = [q for q in r["paras"] if q is not None]
        if r["kind"] == "table":
            _check_expect(op, i, at, _table_text(r["table"]))
        elif r.get("cell") is not None and r["kind"] in ("cell", "place"):
            _check_expect(op, i, at, _cell_text(r["cell"]), r.get("table"))
        elif len(paras) == 1:
            p0 = paras[0]
            _check_expect(op, i, at, p0.text[rng[0]:rng[1]] if rng else p0.text)
        elif op.get("expect") is not None:
            raise DocError("bad_input", "expect works on one paragraph, cell or table", i=i, at=at)
        if name == "para_shape":
            if rng:
                raise DocError("bad_address", "para_shape takes whole paragraphs, not a character range", i=i,
                               at=at)
            eng_fmt = _para_engine_fmt(fmt)
            for q in paras:
                cl.touch(q.si, q.start, i, name, at)
                a = _Act(i, name, at, q, q.start, side=2,
                         steps=[["goto", q.k, 0, q.si], {"op": "set_para_shape", "kwargs": dict(eng_fmt)}])
                a.para_shape = (q, dict(fmt))
                acts.append(a)
        else:
            mp = fmt.pop("markpen", False)
            eng_fmt = _char_engine_fmt(fmt)
            for q in paras:
                if rng:
                    a0 = _ppos(q, rng[0])
                    b0 = _ppos(q, rng[1] - 1) + 1 if rng[1] > rng[0] else a0
                else:
                    a0, b0 = 0, len(q.chars)
                if b0 <= a0:
                    continue                    # an empty paragraph has no characters to shape
                cl.span(q, a0, b0, i, name)
                st = [["goto", q.k, a0, q.si], ["select", b0 - a0]]
                if eng_fmt:
                    st.append({"op": "set_char_shape", "kwargs": dict(eng_fmt)})
                if mp is not False:
                    st.append(["markpen", mp])
                a = _Act(i, name, at, q, q.start, side=2, intra=a0, steps=st)
                if fmt:
                    a.char_shape = (q, (a0, b0), dict(fmt))
                acts.append(a)
            if not any(a.i == i for a in acts):
                raise DocError("bad_input", "%s has no characters to shape" % at, i=i, at=at)
    elif name in ("page_setup", "columns", "break"):
        known = {"page_setup": ("set",), "columns": ("set",), "break": ("kind", "expect")}[name]
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "%s takes %s, not %s" % (name, ", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=list(known))
        if name == "page_setup":
            kw = _page_setup_kwargs(op, i, at)
        elif name == "columns":
            kw = _columns_kwargs(op, i, at)
        else:
            kind = op.get("kind")
            if kind not in BREAK_KINDS:
                raise DocError("bad_input", "break: kind is one of %s" % ", ".join(BREAK_KINDS), i=i, at=at,
                               candidates=list(BREAK_KINDS))
        r = resolve(doc, at, allow=("para", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "%s takes a whole paragraph, not a character range" % name, i=i, at=at)
        p = r["para"]
        if not p.top:
            raise DocError("bad_address", "%s needs a body paragraph, not one in a table, note or box" % name,
                           i=i, at=at)
        go = ["goto", p.k, 0, p.si]
        if name == "page_setup":
            _page_fit(doc, p.si, kw, i, at)
            _section_claim(cl, p.si, i, name, at)
            a = _Act(i, name, at, p, p.start, side=2, steps=[go, {"op": "page_setup", "kwargs": kw}])
            if "start_page" in kw or "border" in kw:
                a.page_setup = (p.si, {k: kw[k] for k in ("start_page", "border") if k in kw})
            acts.append(a)
        elif name == "columns":
            _section_claim(cl, p.si, i, name, at)
            acts.append(_Act(i, name, at, p, p.start, side=2, steps=[go, {"op": "set_columns", "kwargs": kw}]))
        else:
            _check_expect(op, i, at, p.text)
            for s2, pos, j, op2, at2 in cl.touched:
                if j != i and s2 == p.si and pos == p.start and op2 == "break":
                    cl._conflict(i, name, j, op2, at)
            if kind == "section":
                sec_top = [q for q in doc.top if q.si == p.si]
                if p.si != len(doc.secs) - 1:
                    raise DocError("bad_address", "a section break goes in the last section (구역 %d of %d); "
                                   "this one is in 구역 %d" % (len(doc.secs), len(doc.secs), p.si + 1), i=i, at=at)
                if p is sec_top[0]:
                    raise DocError("bad_address", "%s starts its section already" % at, i=i, at=at)
                _section_claim(cl, p.si, i, name, at)
                # the paragraphs from here on move into the new section: no other op may change them in this edit
                cl.remove(p.si, p.start, max(q.end for q in sec_top), i, name, at)
                acts.append(_Act(i, name, at, p, p.start, side=0, rank=1, steps=[go, ["break_section"]]))
            else:
                cl.touch(p.si, p.start, i, name, at)
                acts.append(_Act(i, name, at, p, p.start, side=2,
                                 steps=[go, ["break_page" if kind == "page" else "break_column"]]))
    elif name in ("header", "page_number"):
        known = ("kind", "apply", "text", "expect") if name == "header" else ("pos", "format", "side_char")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "%s takes %s, not %s" % (name, ", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        if name == "header":
            kind = _enum(op.get("kind"), ("HEADER", "FOOTER"), "header: kind", i, at, "HEADER").lower()
            apply = _enum(op.get("apply"), HF_APPLY, "header: apply", i, at, "BOTH")
            if "text" not in op:
                raise DocError("bad_input", "header needs text (the 머리말/꼬리말's text; \\n starts a new line)",
                               i=i, at=at)
            text = _clean(op["text"], "header: text", i, at)
            if len(text) > HF_TEXT_MAX:
                raise DocError("bad_input", "header: text is at most %d characters" % HF_TEXT_MAX, i=i, at=at)
            pieces, want_seq, has_fields = _parse_hf_text(text, i, at)
        else:
            pos = _enum(op.get("pos"), PAGE_NUM_POS, "page_number: pos", i, at, "BOTTOM_CENTER")
            fmt = _enum(op.get("format"), PAGE_NUM_FORMATS, "page_number: format", i, at, "DIGIT")
            side = op.get("side_char", "-")
            if not isinstance(side, str) or len(side) > 1 or (side and _CTRL.search(side)):
                raise DocError("bad_input", "page_number: side_char is one character (or \"\" for none)", i=i, at=at)
        r = resolve(doc, at, allow=("para", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "%s takes a whole paragraph, not a character range" % name, i=i, at=at)
        p = r["para"]
        if not p.top:
            raise DocError("bad_address", "%s needs a body paragraph (it picks the section), not one in a table, "
                           "note or box" % name, i=i, at=at)
        first = next(q for q in doc.top if q.si == p.si)
        if name == "header":
            if not any((st.get("engName") or "") == "Header" for st in doc.styles.values()):
                # the engine gives the new 머리말/꼬리말 the document's own 머리말 style and has none to add
                raise _unavailable("this document has no 머리말 (Header) style, which the engine needs to write a "
                                   "머리말 or 꼬리말", "engine_needs_style", style="Header")
            have = _hf_controls(doc, first, kind, apply)
            _check_expect(op, i, at, "\n".join(q.text for _tag, ps in have for q in ps))
            _section_claim(cl, p.si, i, "%s %s" % (kind, apply), at)
            if not has_fields:
                lit = pieces[0][1] if pieces else ""
                steps = [["goto", first.k, 0, first.si],
                         {"op": "insert_header", "kwargs": {"text": lit, "kind": kind, "apply": apply,
                                                            "replace": True}}]
            else:
                steps = [["goto", first.k, 0, first.si],
                         {"op": "insert_header", "kwargs": {"text": None, "kind": kind, "apply": apply,
                                                            "replace": True}}]
                for pkind, pval in pieces:
                    if pkind == "text":
                        if pval:
                            steps.append(["type", pval])
                    else:
                        steps.append(["insert_page_field", pval])
            a = _Act(i, name, at, first, first.start, side=0, rank=0, steps=steps)
            a.hf = [(first.si, kind, apply, want_seq)]
        else:
            _section_claim(cl, p.si, i, name, at)
            steps = [["goto", first.k, 0, first.si],
                     {"op": "page_number", "kwargs": {"pos": pos, "fmt": fmt, "side_char": side, "replace": True}}]
            a = _Act(i, name, at, first, first.start, side=0, rank=0, steps=steps)
            a.hf = [(first.si, "pageNum", pos, fmt)]
        cl.touch(first.si, first.start, i, name, at)
        acts.append(a)
    elif name == "hide":
        known = HIDE_KEYS
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "hide takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        for k in HIDE_KEYS:
            if k in op and not isinstance(op[k], bool):
                raise DocError("bad_input", "hide: %s is true or false" % k, i=i, at=at)
        kw = {k: bool(op.get(k, False)) for k in HIDE_KEYS}
        if not any(kw.values()):
            raise DocError("bad_input", "hide needs at least one of %s set to true" % ", ".join(HIDE_KEYS),
                           i=i, at=at, candidates=list(HIDE_KEYS))
        r = resolve(doc, at, allow=("para", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "hide takes a whole paragraph, not a character range", i=i, at=at)
        p = r["para"]
        if not p.top:
            raise DocError("bad_address", "hide needs a body paragraph, not one in a table, note or box", i=i, at=at)
        if _page_hidings_in(doc, p):
            raise DocError("bad_input", "hide: %s already has a pageHiding (감추기) control" % at, i=i, at=at)
        for s2, pos, j, op2, _at2 in cl.touched:
            if j != i and s2 == p.si and pos == p.start and op2 == "hide":
                cl._conflict(i, name, j, op2, at)
        cl.touch(p.si, p.start, i, name, at)
        a = _Act(i, name, at, p, p.start, side=2,
                 steps=[["goto", p.k, 0, p.si], {"op": "hide_on_page", "kwargs": kw}])
        a.hide = (p, kw)
        acts.append(a)
    elif name == "new_number":
        known = ("kind", "num")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "new_number takes %s, not %s" % (", ".join(("at",) + known), extra[0]),
                           i=i, at=at, candidates=_cands_near(list(known), extra[0]) or list(known))
        kind = _enum(op.get("kind"), NEW_NUM_KINDS, "new_number: kind", i, at)
        num = op.get("num")
        if not (_is_int(num) and PAGE_NUM_RANGE[0] <= num <= PAGE_NUM_RANGE[1]):
            raise DocError("bad_input", "new_number: num is %d to %d" % PAGE_NUM_RANGE,
                           i=i, at=at, range=list(PAGE_NUM_RANGE))
        r = resolve(doc, at, allow=("para", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "new_number takes a whole paragraph, not a character range", i=i, at=at)
        p = r["para"]
        if not p.top:
            raise DocError("bad_address", "new_number needs a body paragraph, not one in a table, note or box",
                           i=i, at=at)
        if any(k == kind for k, _n in _new_nums_in(doc, p)):
            raise DocError("bad_input", "new_number: %s already has a newNum (%s) control" % (at, kind), i=i, at=at)
        for s2, pos, j, op2, _at2 in cl.touched:
            if j != i and s2 == p.si and pos == p.start and op2 == "new_number":
                cl._conflict(i, name, j, op2, at)
        cl.touch(p.si, p.start, i, name, at)
        a = _Act(i, name, at, p, p.start, side=2,
                 steps=[["goto", p.k, 0, p.si], {"op": "new_number", "kwargs": {"kind": kind, "num": int(num)}}])
        a.new_num = (p, kind, int(num))
        acts.append(a)
    elif name == "numbering":
        want = _numbering_set(op, i, at)
        if want["kind"] == "outline" and _outline_style(doc, want["level"]) is None:
            raise DocError("bad_input", "this document has no 개요 %d style" % want["level"], i=i, at=at,
                           candidates=[s["name"] for s in doc.styles.values()
                                       if (s.get("engName") or "").startswith("Outline")][:7])
        r = resolve(doc, at, allow=("para", "cell", "cellpara", "heading", "place"))
        if r.get("range"):
            raise DocError("bad_address", "numbering takes whole paragraphs, not a character range", i=i, at=at)
        paras = [q for q in r["paras"] if q is not None]
        if r.get("cell") is not None and r["kind"] in ("cell", "place"):
            _check_expect(op, i, at, _cell_text(r["cell"]), r.get("table"))
        elif len(paras) == 1:
            _check_expect(op, i, at, paras[0].text)
        elif op.get("expect") is not None:
            raise DocError("bad_input", "expect works on one paragraph or cell", i=i, at=at)
        for q in paras:
            _no_list_twice(cl, q, i, name, at)
            st = _numbering_steps(doc, q, want)
            if st:
                acts.append(_Act(i, name, at, q, q.start, side=2, steps=st))
    elif name in ("insert_table", "insert_picture", "insert_equation"):
        r = resolve(doc, at, allow=("para", "cellpara", "heading", "cell", "place"))
        if r.get("range"):
            raise DocError("bad_address", "%s takes a paragraph or cell address, not a character range" % name,
                           i=i, at=at)
        p = r["cell"].paras[-1] if (r.get("cell") is not None and r["kind"] in ("cell", "place")) else r["para"]
        inline = op.get("offset")
        if inline is not None and (not _is_int(inline) or not 0 <= inline <= len(p.text)):
            raise DocError("bad_input", "offset must be 0..%d" % len(p.text), at=at, i=i)
        if inline is not None:
            pos = _ppos(p, inline)
            cl.span(p, pos, pos, i, name)
            head = [["goto", p.k, pos, p.si]]
            kw = dict(anchor=p.start, side=1, intra=pos, rank=0)
            xml_at = p.xpos[pos] if pos < len(p.xpos) else p.end - 1
        else:
            cl.touch(p.si, p.start, i, name, at)
            head = [["goto", p.k, 0, p.si], ["goto_end"], ["enter"]]
            kw = dict(anchor=p.end, side=0, rank=0)
            xml_at = p.end
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
                        steps += [["goto_table_cell", ri, ci], ["type", _clean(str(v), "data", i, at)]]
            a = _Act(i, name, at, p, kw.pop("anchor"), steps=steps, **kw)
            # Enter makes one paragraph and Hancom ends the table's paragraph with another
            _adds_for(doc, a, p, 2 if inline is None else 0)
            a.tbl_adds = [(p.si, xml_at, p.cell if p.cell is not None else ("top" if p.top else None))]
            acts.append(a)
        elif name == "insert_picture":
            extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(INSERT_PICTURE_KEYS))
            if extra:
                raise DocError("bad_input", "insert_picture takes %s, not %s"
                               % (", ".join(("at",) + INSERT_PICTURE_KEYS), extra[0]),
                               i=i, at=at,
                               candidates=_cands_near(list(INSERT_PICTURE_KEYS), extra[0])
                               or list(INSERT_PICTURE_KEYS))
            kwp = {}
            for k in ("width_mm", "height_mm"):
                if k in op:
                    if not _in(op[k], *SIZE_MM):
                        raise DocError("bad_input", "insert_picture: %s is %d to %d mm" % ((k,) + SIZE_MM),
                                       i=i, at=at, range=list(SIZE_MM))
                    kwp[k] = float(op[k])
            has_place_extra = any(k in op for k in ("vert_rel", "horz_rel", "x_mm", "y_mm"))
            if "wrap" in op:
                kwp["treat_as_char"] = False
                kwp["wrap"] = _enum(op["wrap"], PICTURE_WRAPS, "insert_picture: wrap", i, at)
            elif has_place_extra:
                raise DocError("bad_input",
                               "insert_picture: vert_rel, horz_rel, x_mm and y_mm require wrap (a floating picture)",
                               i=i, at=at)
            if "vert_rel" in op:
                kwp["vert_rel"] = _enum(op["vert_rel"], PICTURE_VERT_RELS, "insert_picture: vert_rel", i, at)
            if "horz_rel" in op:
                kwp["horz_rel"] = _enum(op["horz_rel"], PICTURE_HORZ_RELS, "insert_picture: horz_rel", i, at)
            for k in ("x_mm", "y_mm"):
                if k in op:
                    if not _in(op[k], *PICTURE_OFFSET_MM):
                        raise DocError("bad_input", "insert_picture: %s is %d to %d mm" % ((k,) + PICTURE_OFFSET_MM),
                                       i=i, at=at, range=list(PICTURE_OFFSET_MM))
                    kwp[k] = float(op[k])
            img = op.get("path")
            if not isinstance(img, str) or not img.strip():
                raise DocError("bad_input", "insert_picture needs path (an image file path)", i=i, at=at)
            if not Path(img).is_file():
                raise DocError("not_found", "insert_picture: no image at %r" % img, i=i, at=at)
            steps = head + [{"op": "insert_picture", "args": [str(Path(img).resolve())], "kwargs": kwp}]
            a = _Act(i, name, at, p, kw.pop("anchor"), steps=steps, **kw)
            _adds_for(doc, a, p, 1 if inline is None else 0)
            floating = "wrap" in kwp
            a.picture = ("insert", p, {
                "inline_offset": inline is not None,
                "width": int(round(kwp["width_mm"] * HU_PER_MM)) if "width_mm" in kwp else None,
                "height": int(round(kwp["height_mm"] * HU_PER_MM)) if "height_mm" in kwp else None,
                "wrap": kwp["wrap"] if floating else "TOP_AND_BOTTOM",
                "treat_as_char": "0" if floating else "1",
                "vert_rel": kwp.get("vert_rel", "PARA"),
                "horz_rel": kwp.get("horz_rel", "COLUMN"),
                "vert_offset": _mm_hu(kwp.get("y_mm", 0)),
                "horz_offset": _mm_hu(kwp.get("x_mm", 0)),
            })
            acts.append(a)
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
            a = _Act(i, name, at, p, kw.pop("anchor"), steps=head + [step], info=info, **kw)
            _adds_for(doc, a, p, 1 if inline is None else 0)
            acts.append(a)
    elif name == "picture":
        known = ("index", "set")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "picture takes at, index, set, not %s" % extra[0],
                           i=i, at=at,
                           candidates=_cands_near(list(("at",) + known), extra[0]) or list(("at",) + known))
        has_idx = "index" in op
        idx = op.get("index", 0)
        if not _is_int(idx) or idx < 0:
            raise DocError("bad_input", "picture: index is a non-negative integer", i=i, at=at)
        want = op.get("set")
        if not isinstance(want, dict) or not want:
            raise DocError("bad_input", "picture needs set: {%s}" % ", ".join(PICTURE_SET_KEYS),
                           i=i, at=at, candidates=list(PICTURE_SET_KEYS))
        bad = sorted(str(k) for k in want if k not in PICTURE_SET_KEYS)
        if bad:
            raise DocError("bad_input", "picture: unknown key(s) %s in set (keys: %s)"
                           % (", ".join(bad), ", ".join(PICTURE_SET_KEYS)),
                           i=i, at=at,
                           candidates=_cands_near(list(PICTURE_SET_KEYS), bad[0]) or list(PICTURE_SET_KEYS))
        for k in ("width_mm", "height_mm"):
            if k in want and not _in(want[k], *SIZE_MM):
                raise DocError("bad_input", "picture: %s is %d to %d mm" % ((k,) + SIZE_MM),
                               i=i, at=at, range=list(SIZE_MM))
        if "keep_ratio" in want:
            _bool(want["keep_ratio"], "picture: keep_ratio", i, at)
            if "width_mm" not in want and "height_mm" not in want:
                raise DocError("bad_input", "picture: keep_ratio goes with width_mm or height_mm", i=i, at=at)
        if "inline" in want:
            _bool(want["inline"], "picture: inline", i, at)
        wrap = _enum(want["wrap"], PICTURE_WRAPS, "picture: wrap", i, at) if "wrap" in want else None
        vrel = _enum(want["vert_rel"], PICTURE_VERT_RELS, "picture: vert_rel", i, at) if "vert_rel" in want else None
        hrel = _enum(want["horz_rel"], PICTURE_HORZ_RELS, "picture: horz_rel", i, at) if "horz_rel" in want else None
        for k in ("x_mm", "y_mm"):
            if k in want and not _in(want[k], *PICTURE_OFFSET_MM):
                raise DocError("bad_input", "picture: %s is %d to %d mm" % ((k,) + PICTURE_OFFSET_MM),
                               i=i, at=at, range=list(PICTURE_OFFSET_MM))
        if want.get("inline") is True and any(k in want for k in ("wrap", "vert_rel", "horz_rel", "x_mm", "y_mm")):
            raise DocError("bad_input",
                           "picture: inline: true (글자처럼 취급) cannot be combined with wrap, vert_rel, horz_rel, x_mm or y_mm",
                           i=i, at=at)
        r = resolve(doc, at, allow=("para", "cellpara", "heading"))
        if r.get("range"):
            raise DocError("bad_address", "picture takes a whole paragraph, not a character range", i=i, at=at)
        p = r["para"]
        pics = _pics_in(doc, p)
        if not pics:
            cands = [para_address(doc, q) for q in doc.paras if para_address(doc, q) and _pics_in(doc, q)][:8]
            raise DocError("not_found", "picture: %s holds no picture" % at, i=i, at=at,
                           candidates=cands or None)
        if not has_idx and len(pics) > 1:
            raise DocError("bad_input", "picture: %s holds %d pictures; give index (0..%d)"
                           % (at, len(pics), len(pics) - 1), i=i, at=at, range=[0, len(pics) - 1])
        if idx >= len(pics):
            raise DocError("bad_input", "picture: index must be 0..%d (%s holds %d picture(s))"
                           % (len(pics) - 1, at, len(pics)), i=i, at=at, range=[0, len(pics) - 1])
        base_pic = pics[idx]
        pic_id = base_pic["id"]
        if not pic_id or not base_pic["width"] or not base_pic["height"]:
            raise DocError("bad_input", "picture: the picture in %s has no valid id or size" % at, i=i, at=at)
        if want.get("inline") is True:
            treat_as_char = True
            after_floating = False
        elif wrap is not None or want.get("inline") is False:
            treat_as_char = False
            after_floating = True
        else:
            treat_as_char = None
            after_floating = (base_pic["treat_as_char"] == "0")
        if any(k in want for k in ("vert_rel", "horz_rel", "x_mm", "y_mm")) and not after_floating:
            raise DocError("bad_input",
                           "picture: vert_rel, horz_rel, x_mm and y_mm require a floating picture (give wrap, or edit a floating picture)",
                           i=i, at=at)
        w0, h0 = base_pic["width"], base_pic["height"]
        keep_ratio = want.get("keep_ratio", True)
        pic_kw = {"obj": pic_id}
        want_w, want_h = w0, h0
        size_changed = "width_mm" in want or "height_mm" in want
        if "width_mm" in want and "height_mm" in want:
            w_mm, h_mm = float(want["width_mm"]), float(want["height_mm"])
            want_w, want_h = int(round(w_mm * HU_PER_MM)), int(round(h_mm * HU_PER_MM))
            if want.get("keep_ratio") is True and abs(want_w * h0 - want_h * w0) > max(w0, h0):
                raise DocError("bad_input",
                               "picture: width_mm and height_mm do not keep the picture's aspect ratio; give one of them or keep_ratio: false",
                               i=i, at=at)
            pic_kw["width_mm"] = w_mm
            pic_kw["height_mm"] = h_mm
        elif "width_mm" in want:
            w_mm = float(want["width_mm"])
            want_w = int(round(w_mm * HU_PER_MM))
            pic_kw["width_mm"] = w_mm
            if keep_ratio:
                want_h = int(round(h0 * want_w / w0))
            else:
                want_h = h0
                pic_kw["height_mm"] = h0 / HU_PER_MM
        elif "height_mm" in want:
            h_mm = float(want["height_mm"])
            want_h = int(round(h_mm * HU_PER_MM))
            pic_kw["height_mm"] = h_mm
            if keep_ratio:
                want_w = int(round(w0 * want_h / h0))
                pic_kw["width_mm"] = want_w / HU_PER_MM
            else:
                want_w = w0
        if wrap is not None:
            pic_kw["wrap"] = wrap
        if treat_as_char is not None:
            pic_kw["treat_as_char"] = treat_as_char
        pos_kw = {}
        if vrel is not None:
            pos_kw["vertRelTo"] = vrel
        if hrel is not None:
            pos_kw["horzRelTo"] = hrel
        if "y_mm" in want:
            pos_kw["vertOffset"] = str(_mm_hu(want["y_mm"]))
        if "x_mm" in want:
            pos_kw["horzOffset"] = str(_mm_hu(want["x_mm"]))
        pic_key = (p.si, pic_id)
        if pic_key in cl.pictures:
            j, op2 = cl.pictures[pic_key]
            cl._conflict(i, name, j, op2, at)
        cl.pictures[pic_key] = (i, name)
        cl.touch(p.si, p.start, i, name, at)
        steps = [{"op": "set_picture", "kwargs": pic_kw}]
        if pos_kw:
            steps.append({"op": "set_obj_pos", "args": [pic_id], "kwargs": {"tag": "hp:pic", **pos_kw}})
        expected_pic = {
            "id": pic_id,
            "bin_ref": base_pic["bin_ref"],
            "size_changed": size_changed,
            "width": want_w,
            "height": want_h,
            "cur_width": want_w if size_changed else base_pic["cur_width"],
            "cur_height": want_h if size_changed else base_pic["cur_height"],
            "wrap": wrap if wrap is not None else base_pic["wrap"],
            "treat_as_char": ("1" if treat_as_char else "0") if treat_as_char is not None else base_pic["treat_as_char"],
            "vert_rel": vrel if vrel is not None else base_pic["vert_rel"],
            "horz_rel": hrel if hrel is not None else base_pic["horz_rel"],
            "vert_offset": _mm_hu(want["y_mm"]) if "y_mm" in want else base_pic["vert_offset"],
            "horz_offset": _mm_hu(want["x_mm"]) if "x_mm" in want else base_pic["horz_offset"],
        }
        a = _Act(i, name, at, p, p.start, side=2, steps=steps)
        a.picture = ("modify", p, expected_pic)
        acts.append(a)
    elif name == "table.formula":
        known = ("func", "from", "formula")
        extra = sorted(str(k) for k in set(op) - {"op", "at"} - set(known))
        if extra:
            raise DocError("bad_input", "table.formula takes at, func, from, formula, not %s" % extra[0],
                           i=i, at=at,
                           candidates=_cands_near(list(("at",) + known), extra[0]) or list(("at",) + known))
        has_func = "func" in op
        has_formula = "formula" in op
        if has_func == has_formula:
            raise DocError("bad_input", "table.formula needs exactly one of func (with from) or formula",
                           i=i, at=at)
        if has_formula and "from" in op:
            raise DocError("bad_input", "table.formula: from goes with func, not formula", i=i, at=at)
        r = resolve(doc, at, allow=("cell",))
        t, target = r["table"], r["cell"]
        if t.addr is None:
            raise DocError("bad_address", "table.formula only works on a body table", i=i, at=at)
        pa = parse_address(at)
        if (target.row, target.col) != (pa["r"], pa["c"]):
            raise DocError("bad_address", "%s is inside the merged cell %s" % (at, cell_address(t, target)),
                           i=i, at=at, candidates=[cell_address(t, target)])
        if not _cell_is_empty(doc, t, target):
            raise DocError("bad_input", "table.formula: target cell %s must be empty (no text or controls)" % at,
                           i=i, at=at)
        tp = target.paras[0]
        if has_func:
            func = _enum(op.get("func"), FORMULA_FUNCS, "table.formula: func", i, at)
            from_addr = op.get("from")
            if not isinstance(from_addr, str):
                raise DocError("bad_input",
                               "table.formula with func needs from (the first cell of the row or column block)",
                               i=i, at=at)
            r_from = resolve(doc, from_addr, allow=("cell",))
            if r_from["table"] is not t:
                raise DocError("bad_address", "table.formula: from must be a cell of %s" % t.addr,
                               i=i, at=from_addr)
            c_from = r_from["cell"]
            pf = parse_address(from_addr)
            if (c_from.row, c_from.col) != (pf["r"], pf["c"]):
                raise DocError("bad_address", "%s is inside the merged cell %s" % (from_addr, cell_address(t, c_from)),
                               i=i, at=from_addr, candidates=[cell_address(t, c_from)])
            if (c_from.row, c_from.col) == (target.row, target.col):
                raise DocError("bad_input",
                               "table.formula: from (%s) must be left of or above at (%s), not the same cell"
                               % (from_addr, at), i=i, at=at)
            if c_from.row != target.row and c_from.col != target.col:
                raise DocError("bad_input",
                               "table.formula: from (%s) and at (%s) must be in the same row or the same column"
                               % (from_addr, at), i=i, at=at)
            if c_from.row == target.row and c_from.col > target.col:
                raise DocError("bad_input", "table.formula: from (%s) must be left of at (%s)" % (from_addr, at),
                               i=i, at=at)
            if c_from.col == target.col and c_from.row > target.row:
                raise DocError("bad_input", "table.formula: from (%s) must be above at (%s)" % (from_addr, at),
                               i=i, at=at)
            is_row = (c_from.row == target.row)
            if is_row and target.col >= 26:
                raise DocError("bad_input", "table.formula: row formula columns must be A..Z (0..25)",
                               i=i, at=at)
            block_cells = ([t.at(target.row, c) for c in range(c_from.col, target.col + 1)] if is_row
                           else [t.at(rr, target.col) for rr in range(c_from.row, target.row + 1)])
            ra, rb, ca, cb = _merge_rect(t, c_from.row, c_from.col, target.row, target.col)
            if (ra, rb, ca, cb) != (c_from.row, target.row, c_from.col, target.col) \
                    or any(x is None or x.rs != 1 or x.cs != 1 for x in block_cells):
                raise DocError("bad_input", "table.formula: block %s..%s crosses a merged cell" % (from_addr, at),
                               i=i, at=at)
            steps = [
                ["goto_cell", t.lt, c_from.row, c_from.col, False, t.si],
                ["cell_block", target.row, target.col],
                ["formula_auto", FORMULA_ENGINE_FUNC[func]],
            ]
            f_spec = (tp, "func", (func, block_cells[:-1], is_row))
        else:
            formula = op.get("formula")
            if not isinstance(formula, str) or not formula.startswith("=") or not formula[1:].strip() \
                    or formula != formula.strip() or len(formula) > FORMULA_MAX \
                    or _CTRL.search(formula) or re.search(r"[\t\n\r]", formula):
                raise DocError("bad_input",
                               "table.formula: formula is '=' followed by an expression (2 to %d characters on one line, no control characters)"
                               % FORMULA_MAX, i=i, at=at)
            steps = [
                ["goto_cell", t.lt, target.row, target.col, False, t.si],
                ["insert_formula_field", formula],
            ]
            f_spec = (tp, "formula", formula)
        _table_mark(cl, t, i, name, at, "formula")
        cl.span(tp, 0, len(tp.chars), i, name, whole=True)
        cl.remove(t.si, target.start, target.end, i, name, at)
        a = _Act(i, name, at, tp, t.start, side=0, intra=-i, rank=0, steps=steps)
        a.text_of = tp
        a.formula = f_spec
        acts.append(a)
    return acts


# ============================================================================ remap
def _structure(doc, acts):
    """The exact address map of an edit, from what each act does to the base structure.

    Split-paragraph policy: when typed text carries line breaks, the paragraph keeps its address (it holds the
    first line) and the new paragraphs follow it."""
    adds = [(g, n) for a in acts for g, n in a.top_adds]
    dels = sorted({g for a in acts for g in a.top_dels})
    dset = set(dels)

    def newtop(gp):
        if gp in dset:
            return None
        return gp + sum(n for g, n in adds if g < gp) - bisect.bisect_left(dels, gp)
    tadds = [x for a in acts for x in a.tbl_adds]
    tdels = sorted({g for a in acts for g in a.tbl_dels})
    tdset = set(tdels)
    newt = {}
    for t in doc.tables:
        newt[t.g] = None if t.g in tdset else (
            t.g + sum(1 for si, pos, _h in tadds if (si, pos) < (t.si, t.start)) - bisect.bisect_left(tdels, t.g))
    radds, rdels = {}, {}
    for a in acts:
        for g, after in a.row_adds:
            radds.setdefault(g, []).append(after)
        for g, r in a.row_dels:
            rdels.setdefault(g, set()).add(r)

    def newrow(g, r):
        if r in rdels.get(g, ()):
            return None
        return r + sum(1 for x in radds.get(g, ()) if x < r) - sum(1 for x in rdels.get(g, ()) if x < r)
    coladds, coldels, merged = {}, {}, {}
    for a in acts:
        for g, after in a.col_adds:
            coladds.setdefault(g, []).append(after)
        for g, c in a.col_dels:
            coldels.setdefault(g, set()).add(c)
        for g, first, inside, _span in a.merges:
            for x in inside[1:]:
                merged[id(x)] = first

    def newcell(g, x):
        """(row, col) of base cell x of table g in the output; None when it was deleted or merged away."""
        if id(x) in merged:
            return None
        r = newrow(g, x.row)
        if r is None:
            return None
        c = x.col
        if c in coldels.get(g, ()) and x.cs == 1:
            return None
        return r, c + sum(1 for k in coladds.get(g, ()) if k < c) - sum(1 for k in coldels.get(g, ()) if k < c)
    cadds, cdels = {}, {}
    for a in acts:
        for c, k, n in a.cell_adds:
            cadds.setdefault(id(c), (c, []))[1].append((k, n))
        for c, k in a.cell_dels:
            cdels.setdefault(id(c), (c, set()))[1].add(k)

    def same_host(x, host):
        return x is host if host != "top" else x == "top"
    addr_memo = {}

    def newaddr(t):
        """The public address table t has in the output (None: deleted, or it has none)."""
        if t.g in addr_memo:
            return addr_memo[t.g]
        res = None
        if t.addr is not None and t.g not in tdset:
            host = "top" if t.parent is None else t.parent
            sibs = [x for x in doc.tables if x.addr and (x.parent is None if host == "top" else x.parent is host)]
            k = sibs.index(t) - sum(1 for x in sibs if x.g in tdset and x.g < t.g) + sum(
                1 for si, pos, h in tadds if same_host(h, host) and (si, pos) < (t.si, t.start))
            if host == "top":
                res = "t%d" % k
            else:
                pt = doc.table_of(host)
                pa = newaddr(pt) if pt is not None else None
                nc = newcell(pt.g, host) if pa is not None else None
                res = None if nc is None else "%s/r%d/c%d/t%d" % (pa, nc[0], nc[1], k)
        addr_memo[t.g] = res
        return res
    return {"newtop": newtop, "newt": newt, "newrow": newrow, "adds": adds, "dels": dels, "tadds": tadds,
            "tdels": tdels, "radds": radds, "rdels": rdels, "cadds": cadds, "cdels": cdels, "newaddr": newaddr,
            "coladds": coladds, "coldels": coldels, "newcell": newcell}


def _remap(doc, acts):
    """[{from, to}] for top-level paragraphs, tables, rows and cell paragraphs whose address changed; ``to`` is
    None when it was deleted. Addresses below a listed one follow it (see follow_remap)."""
    st = _structure(doc, acts)
    out = []
    for p in doc.top:
        n = st["newtop"](p.gp)
        if n != p.gp:
            out.append({"from": "p%d" % p.gp, "to": None if n is None else "p%d" % n})
    for t in doc.tables:
        if t.addr is not None and st["newaddr"](t) != t.addr:
            out.append({"from": t.addr, "to": st["newaddr"](t)})
    for g in sorted(set(st["radds"]) | set(st["rdels"])):
        t = doc.tables[g]
        ta = st["newaddr"](t)
        if ta is None or t.addr is None:
            continue
        for r in range(t.rows):
            nr = st["newrow"](g, r)
            to = None if nr is None else "%s/r%d" % (ta, nr)
            if to != "%s/r%d" % (t.addr, r):
                out.append({"from": "%s/r%d" % (t.addr, r), "to": to})
    for g in sorted(set(st["coladds"]) | set(st["coldels"])):
        t = doc.tables[g]
        ta = st["newaddr"](t)
        if ta is None or t.addr is None:
            continue
        for x in sorted(t.cells, key=lambda x: (x.row, x.col)):
            base = cell_address(t, x)
            nc = st["newcell"](g, x)
            to = None if nc is None else "%s/r%d/c%d" % (ta, nc[0], nc[1])
            if to != follow_remap(out, base):
                out.append({"from": base, "to": to})
    for a in acts:
        for g, first, inside, _span in a.merges:
            t = doc.tables[g]
            ta = st["newaddr"](t)
            if ta is None or t.addr is None:
                continue
            fa = follow_remap(out, cell_address(t, first))
            moved = _merge_paras(inside)
            for x in inside:
                base = cell_address(t, x)
                if x is not first:
                    out.append({"from": base, "to": None})
                for k, q in enumerate(x.paras):
                    nk = moved.get(id(q), k if (x is first and not moved) else None)
                    if x is first and nk == k:
                        continue
                    out.append({"from": "%s/p%d" % (base, k), "to": None if (nk is None or fa is None)
                                else "%s/p%d" % (fa, nk)})
    for key in set(st["cadds"]) | set(st["cdels"]):
        c = (st["cadds"].get(key) or st["cdels"].get(key))[0]
        adds = st["cadds"].get(key, (c, []))[1]
        dels = st["cdels"].get(key, (c, set()))[1]
        t = doc.table_of(c)
        if t is None or t.addr is None:
            continue
        base = cell_address(t, c)
        cur = follow_remap(out, base)
        for k in range(len(c.paras)):
            if k in dels:
                nk = None
            else:
                nk = k + sum(n for kk, n in adds if kk < k) - sum(1 for kk in dels if kk < k)
            if nk != k:
                out.append({"from": "%s/p%d" % (base, k),
                            "to": None if (nk is None or cur is None) else "%s/p%d" % (cur, nk)})
    return out


def _verify(doc, newdoc, acts):
    """True when the output has exactly the structure the remap describes: paragraph and table counts, the
    text of every paragraph no op changed at its new address, row counts of changed tables, and untouched
    tables cell for cell."""
    if any(a.info.get("unmapped") for a in acts):
        return False
    st = _structure(doc, acts)
    want_top = len(doc.top) + sum(n for _g, n in st["adds"]) - len(st["dels"])
    if len(newdoc.top) != want_top:
        return False
    if len(newdoc.tables) != len(doc.tables) + len(st["tadds"]) - len(st["tdels"]):
        return False
    changed = {id(a.text_of) for a in acts if a.text_of is not None}
    for p in doc.top:
        n = st["newtop"](p.gp)
        if n is None or id(p) in changed:
            continue
        if newdoc.top[n].text != p.text:
            return False
    touched = set()
    for a in acts:
        for t in doc.sec_tables[a.si]:
            if t.start <= a.p.start < t.end:
                touched.add(t.g)
        touched.update(g for g, _ in a.row_adds)
        touched.update(g for g, _ in a.row_dels)
    for t in doc.tables:
        ng = st["newt"][t.g]
        if ng is None:
            continue
        nt = newdoc.tables[ng]
        if t.g in st["radds"] or t.g in st["rdels"]:
            if nt.rows != t.rows + len(st["radds"].get(t.g, ())) - len(st["rdels"].get(t.g, ())):
                return False
        elif t.g not in touched:
            if (nt.rows, nt.cols) != (t.rows, t.cols) or _table_text(nt) != _table_text(t):
                return False
    if not _verify_shapes(doc, newdoc, acts, st):
        return False
    if not _verify_hf(newdoc, acts, st):
        return False
    if not _verify_styles(doc, newdoc, acts):
        return False
    if not _verify_char_para(doc, newdoc, acts, st):
        return False
    if not _verify_notes(doc, newdoc, acts, st):
        return False
    if not _verify_captions(doc, newdoc, acts, st):
        return False
    if not _verify_bookmarks(doc, newdoc, acts, st):
        return False
    if not _verify_links(doc, newdoc, acts, st):
        return False
    if not _verify_toc(doc, newdoc, acts, st):
        return False
    if not _verify_page_setup(doc, newdoc, acts):
        return False
    if not _verify_hide(doc, newdoc, acts, st):
        return False
    if not _verify_new_numbers(doc, newdoc, acts, st):
        return False
    if not _verify_picture(doc, newdoc, acts, st):
        return False
    if not _verify_table_formula(doc, newdoc, acts, st):
        return False
    for t in doc.tables:                # every surviving table is where the remap says, by its public address
        na = st["newaddr"](t)
        ng = st["newt"][t.g]
        if na is not None and (ng is None or newdoc.tables[ng].addr != na):
            return False
    for key in set(st["cadds"]) | set(st["cdels"]):
        c = (st["cadds"].get(key) or st["cdels"].get(key))[0]
        n = len(c.paras) + sum(x for _k, x in st["cadds"].get(key, (c, []))[1]) - \
            len(st["cdels"].get(key, (c, set()))[1])
        t = doc.table_of(c)
        g = st["newt"][t.g]
        if g is None:
            continue
        nr = st["newrow"](t.g, c.row)
        nc = newdoc.tables[g].at(nr, c.col) if nr is not None else None
        if nc is not None and len(nc.paras) != n:
            return False
    return True


def _verify_hf(newdoc, acts, st):
    """Each section a header / page_number op changed has exactly one such control, with the text and page
    fields (or position and format) asked."""
    for a in acts:
        for si, kind, x, y in a.hf:
            first = next((q for q in newdoc.top if q.si == si), None)
            if first is None:
                return False
            if kind == "pageNum":
                have = _hf_controls(newdoc, first, "pageNum")
                if len(have) != 1 or 'pos="%s"' % x not in have[0][0] or 'formatType="%s"' % y not in have[0][0]:
                    return False
                continue
            have = _hf_controls(newdoc, first, kind, x)
            if len(have) != 1 or not have[0][1] or [q.seq for q in have[0][1]] != y.split("\n"):
                return False
    return True


def _width_str(w):
    w = float(str(w).replace("mm", "").strip())
    return f"{w:g} mm"


def _header_maps(newdoc):
    try:
        root = ET.fromstring(newdoc.zip.read("Contents/header.xml"))
    except (ET.ParseError, KeyError, OSError):
        return None
    char_prs, para_prs, bfs, tabs, fonts = {}, {}, {}, {}, {}
    for el in root.iter():
        t = _local(el.tag)
        if t == "charPr":
            char_prs[el.get("id")] = el
        elif t == "paraPr":
            para_prs[el.get("id")] = el
        elif t == "borderFill":
            bfs[el.get("id")] = el
        elif t == "tabPr":
            tabs[el.get("id")] = el
        elif t == "fontface":
            lang = el.get("lang")
            fonts[lang] = {x.get("id"): x.get("face") for x in el if _local(x.tag) == "font"}
    return char_prs, para_prs, bfs, tabs, fonts


def _check_bf_sides(bf, bd):
    for sname in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        sb = next((x for x in bf if _local(x.tag) == sname), None)
        if sb is None:
            return False
        if bd is False:
            if sb.get("type") != "NONE":
                return False
        else:
            if sb.get("type") != bd["type"] or sb.get("width") != _width_str(bd["width"]) \
                    or (sb.get("color") or "").upper() != bd["color"].upper():
                return False
    return True


def _check_bf_fill(bf, fill):
    wb = next((x for x in bf.iter() if _local(x.tag) == "winBrush"), None)
    if fill is None:
        return wb is None or (wb.get("faceColor") or "none").lower() == "none"
    return wb is not None and (wb.get("faceColor") or "").upper() == fill.upper()


def _check_char_pr(cp, ch, bfs, fonts):
    if "size" in ch and cp.get("height") != str(int(round(ch["size"] * 100))):
        return False
    if "color" in ch and (cp.get("textColor") or "").upper() != ch["color"].upper():
        return False
    if "shade" in ch:
        want_sh = "none" if ch["shade"] is None else ch["shade"].upper()
        if (cp.get("shadeColor") or "").upper() != want_sh.upper():
            return False
    for k in ("bold", "italic", "emboss", "engrave"):
        if k in ch and any(_local(x.tag) == k for x in cp) != ch[k]:
            return False
    for k, tag_name in (("sup", "supscript"), ("sub", "subscript")):
        if k in ch and any(_local(x.tag) == tag_name for x in cp) != ch[k]:
            return False
    if any(k in ch for k in ("underline", "underline_shape", "underline_color")):
        ul = next((x for x in cp if _local(x.tag) == "underline"), None)
        if ul is None:
            return False
        if "underline" in ch:
            u = ch["underline"]
            if u is False and ul.get("type") != "NONE":
                return False
            if u is True and ul.get("type") in (None, "NONE"):
                return False
            if isinstance(u, str) and ul.get("type") != u:
                return False
        if "underline_shape" in ch and ul.get("shape") != ch["underline_shape"]:
            return False
        if "underline_color" in ch and (ul.get("color") or "").upper() != ch["underline_color"].upper():
            return False
    if "strike" in ch or "strike_color" in ch:
        sk = next((x for x in cp if _local(x.tag) == "strikeout"), None)
        if sk is None:
            return False
        if "strike" in ch:
            s = ch["strike"]
            if s is False and sk.get("shape") != "NONE":
                return False
            if s is True and sk.get("shape") in (None, "NONE"):
                return False
            if isinstance(s, str) and sk.get("shape") != s:
                return False
        if "strike_color" in ch and (sk.get("color") or "").upper() != ch["strike_color"].upper():
            return False
    for k, tag_name in (("ratio", "ratio"), ("spacing", "spacing"), ("rel_size", "relSz"), ("offset", "offset")):
        if k in ch:
            el = next((x for x in cp if _local(x.tag) == tag_name), None)
            if el is None or el.get("hangul") != str(int(ch[k])):
                return False
    if "font" in ch:
        fref = next((x for x in cp if _local(x.tag) == "fontRef"), None)
        if fref is None:
            return False
        if isinstance(ch["font"], str):
            if fonts.get("HANGUL", {}).get(fref.get("hangul")) != ch["font"]:
                return False
        elif isinstance(ch["font"], dict):
            for lk, lv in ch["font"].items():
                if fonts.get(lk.upper(), {}).get(fref.get(lk)) != lv:
                    return False
    if "outline" in ch:
        ol = next((x for x in cp if _local(x.tag) == "outline"), None)
        want_ol = "NONE" if ch["outline"] is False else ch["outline"]
        if ol is None or ol.get("type") != want_ol:
            return False
    if any(k in ch for k in ("shadow", "shadow_color", "shadow_offset")):
        sh = next((x for x in cp if _local(x.tag) == "shadow"), None)
        if sh is None:
            return False
        if "shadow" in ch:
            want_sh = "NONE" if ch["shadow"] is False else ch["shadow"]
            if sh.get("type") != want_sh:
                return False
        if "shadow_color" in ch and (sh.get("color") or "").upper() != ch["shadow_color"].upper():
            return False
        if "shadow_offset" in ch:
            ox, oy = ch["shadow_offset"]
            if sh.get("offsetX") != str(int(ox)) or sh.get("offsetY") != str(int(oy)):
                return False
    if "emphasis" in ch:
        want_em = "NONE" if ch["emphasis"] is False else ch["emphasis"]
        if (cp.get("symMark") or "NONE") != want_em:
            return False
    if "char_border" in ch or "char_fill" in ch:
        bf = bfs.get(cp.get("borderFillIDRef"))
        if bf is None:
            return False
        if "char_border" in ch and not _check_bf_sides(bf, ch["char_border"]):
            return False
        if "char_fill" in ch and not _check_bf_fill(bf, ch["char_fill"]):
            return False
    return True


def _check_para_pr(pp, pa, bfs, tabs):
    if "align" in pa:
        al = next((x for x in pp.iter() if _local(x.tag) == "align"), None)
        if al is None or al.get("horizontal") != pa["align"]:
            return False
    for k, tag_name in (("left", "left"), ("right", "right"), ("indent", "intent"),
                        ("before", "prev"), ("after", "next")):
        if k in pa:
            el = next((x for x in pp.iter() if _local(x.tag) == tag_name), None)
            if el is None or el.get("value") != str(int(round(pa[k] * 100))):
                return False
    if "line_spacing" in pa:
        ls = next((x for x in pp.iter() if _local(x.tag) == "lineSpacing"), None)
        if ls is None:
            return False
        v = pa["line_spacing"]
        if not isinstance(v, dict):
            if ls.get("type") != "PERCENT" or ls.get("value") != str(v):
                return False
        else:
            want_v = str(int(round(v["value"]))) if v["type"] == "PERCENT" else str(int(round(v["value"] * 100)))
            if ls.get("type") != v["type"] or ls.get("value") != want_v:
                return False
    if any(k in pa for k in ("keep_next", "keep_lines", "widow_orphan", "page_break_before")):
        bs = next((x for x in pp.iter() if _local(x.tag) == "breakSetting"), None)
        if bs is None:
            return False
        for k, attr_name in (("keep_next", "keepWithNext"), ("keep_lines", "keepLines"),
                             ("widow_orphan", "widowOrphan"), ("page_break_before", "pageBreakBefore")):
            if k in pa and bs.get(attr_name) != ("1" if pa[k] else "0"):
                return False
    if any(k in pa for k in ("tabs", "auto_tab_left", "auto_tab_right")):
        tp = tabs.get(pp.get("tabPrIDRef"))
        if tp is None:
            return False
        if "auto_tab_left" in pa and tp.get("autoTabLeft") != ("1" if pa["auto_tab_left"] else "0"):
            return False
        if "auto_tab_right" in pa and tp.get("autoTabRight") != ("1" if pa["auto_tab_right"] else "0"):
            return False
        if "tabs" in pa:
            cases = [x for x in tp.iter() if _local(x.tag) == "case"]
            defaults = [x for x in tp.iter() if _local(x.tag) == "default"]
            items = [x for c in cases for x in c if _local(x.tag) == "tabItem"] if cases else [
                x for x in tp if _local(x.tag) == "tabItem"]
            if len(items) != len(pa["tabs"]):
                return False
            for item, want_st in zip(items, pa["tabs"]):
                want_pos = str(int(round(want_st["pos"] * 100)))
                if item.get("pos") != want_pos or item.get("type") != want_st["type"] \
                        or item.get("leader") != want_st["leader"]:
                    return False
            if defaults:
                ditems = [x for d in defaults for x in d if _local(x.tag) == "tabItem"]
                if len(ditems) != len(pa["tabs"]):
                    return False
                for item, want_st in zip(ditems, pa["tabs"]):
                    want_pos = str(2 * int(round(want_st["pos"] * 100)))
                    if item.get("pos") != want_pos or item.get("type") != want_st["type"] \
                            or item.get("leader") != want_st["leader"]:
                        return False
    if any(k in pa for k in ("border", "fill", "offsets", "connect")):
        bd_el = next((x for x in pp if _local(x.tag) == "border"), None)
        if bd_el is None:
            return False
        if "connect" in pa and bd_el.get("connect") != ("1" if pa["connect"] else "0"):
            return False
        if "offsets" in pa:
            want_offs = [str(int(round(float(v) * 100))) for v in pa["offsets"]]
            if [bd_el.get("offsetLeft"), bd_el.get("offsetRight"),
                    bd_el.get("offsetTop"), bd_el.get("offsetBottom")] != want_offs:
                return False
        if "border" in pa or "fill" in pa:
            bf = bfs.get(bd_el.get("borderFillIDRef"))
            if bf is None:
                return False
            if "border" in pa and not _check_bf_sides(bf, pa["border"]):
                return False
            if "fill" in pa and not _check_bf_fill(bf, pa["fill"]):
                return False
    return True


def _verify_styles(doc, newdoc, acts):
    """Each style a style.create op made (or _auto_styles added) is in the output's header.xml, once, with its
    type and English name, and its charPr / paraPr / borderFill / tabPr hold the values asked; no style of the
    base document went missing."""
    made = [a.new_style for a in acts if a.new_style]
    auto = _auto_styles(doc, acts)
    if not made and not auto:
        return True
    if len(newdoc.styles) != len(doc.styles) + len(made) + len(auto):
        return False
    for eng, sname, _act in auto:
        if not any(st.get("name") == sname and (st.get("engName") or "") == eng for st in newdoc.styles.values()):
            return False
    if not made:
        return True
    hm = _header_maps(newdoc)
    if hm is None:
        return False
    char_prs, para_prs, bfs, tabs, fonts = hm
    for want in made:
        got = [st for st in newdoc.styles.values() if st["name"] == want["name"]]
        if len(got) != 1:
            return False
        st = got[0]
        if st["type"] != want["kind"] or (st["engName"] or "") != want["eng"]:
            return False
        cp, pp = char_prs.get(st["charPr"]), para_prs.get(st["paraPr"])
        if cp is None or pp is None:
            return False
        if not _check_char_pr(cp, want["char"], bfs, fonts):
            return False
        if not _check_para_pr(pp, want["para"], bfs, tabs):
            return False
    return True


def _verify_char_para(doc, newdoc, acts, st):
    """Each char_shape / para_shape op wrote its requested properties to the target runs' charPr or paragraph's
    paraPr (and any referenced borderFill / tabPr / fontface) in header.xml."""
    c_acts = [a for a in acts if a.char_shape]
    p_acts = [a for a in acts if a.para_shape]
    if not c_acts and not p_acts:
        return True
    hm = _header_maps(newdoc)
    if hm is None:
        return False
    char_prs, para_prs, bfs, tabs, fonts = hm
    by_p = {}
    for a in sorted(p_acts, key=lambda x: x.key, reverse=True):
        q, fmt = a.para_shape
        by_p.setdefault(id(q), (q, {}))[1].update(fmt)
    for q, fmt in by_p.values():
        np = _new_para(doc, newdoc, q, st)
        if np is None:
            return False
        pp = para_prs.get(np.pr)
        if pp is None or not _check_para_pr(pp, fmt, bfs, tabs):
            return False
    for a in c_acts:
        q, (a0, b0), fmt = a.char_shape
        np = _new_para(doc, newdoc, q, st)
        if np is None:
            return False
        shift = 0
        split_before = False
        for a2 in acts:
            if a2.fb and a2.fb[0] == "replace" and a2.fb[1] is q:
                _, _, ra, rlen, rtext = a2.fb
                if ra + rlen <= a0:
                    if "\n" in rtext:
                        split_before = True
                    else:
                        shift += len(rtext) - rlen
        if split_before:
            continue
        na0, nb0 = a0 + shift, b0 + shift
        if na0 < 0 or nb0 > len(np.chars):
            return False
        cp_ids = []
        for pos in range(na0, nb0):
            pm = np.posmap[pos]
            if pm is not None:
                cid = np.tnodes[pm[0]]["run"].get("cp")
                if cid is not None and cid not in cp_ids:
                    cp_ids.append(cid)
        if not cp_ids and any(np.posmap[pos] is not None for pos in range(na0, nb0)):
            return False
        for cid in cp_ids:
            cp = char_prs.get(cid)
            if cp is None or not _check_char_pr(cp, fmt, bfs, fonts):
                return False
    return True


def _new_para(doc, newdoc, p, st):
    """The paragraph in `newdoc` that corresponds to base paragraph `p` of `doc`, or None."""
    if p.top:
        ngp = st["newtop"](p.gp)
        return newdoc.top[ngp] if ngp is not None and 0 <= ngp < len(newdoc.top) else None
    if p.cell is not None:
        t = doc.table_of(p.cell)
        ng = st["newt"].get(t.g) if t is not None else None
        rc = st["newcell"](t.g, p.cell) if ng is not None and 0 <= ng < len(newdoc.tables) else None
        nc = newdoc.tables[ng].at(*rc) if rc is not None else None
        k = p.cell.paras.index(p)
        adds = st["cadds"].get(id(p.cell), (p.cell, []))[1]
        dels = st["cdels"].get(id(p.cell), (p.cell, set()))[1]
        if k in dels:
            return None
        nk = k + sum(n for kk, n in adds if kk < k) - sum(1 for kk in dels if kk < k)
        return nc.paras[nk] if nc is not None and 0 <= nk < len(nc.paras) else None
    return None


def _notes_in(d, si, nkind, para=None):
    """The texts of the hp:footNote / hp:endNote controls in section si (or directly inside `para`)."""
    s = d.secs[si]
    out = []
    for m in re.finditer(r"<hp:%s\b[^>]*>.*?</hp:%s>" % (nkind, nkind), s, re.S):
        a, b = m.start(), m.end()
        ps = [q for q in d.sec_paras[si] if a < q.start < b]
        if para is not None:
            host = ps[0].parent if ps else next(
                (q for q in reversed(d.sec_paras[si]) if q.start < a < q.end), None)
            if host is not para:
                continue
        if not ps:
            out.append(None)
            continue
        raw = "\n".join(q.text for q in ps)
        out.append(raw[1:] if raw.startswith(" ") else raw)
    return out


def _verify_notes(doc, newdoc, acts, st):
    """Each note op added one hp:footNote / hp:endNote in its section, inside the addressed paragraph, with the
    text asked."""
    notes = [a for a in acts if a.note]
    if not notes:
        return True
    if len(newdoc.secs) < len(doc.secs):
        return False
    for si in range(len(doc.secs)):
        for nkind in ("footNote", "endNote"):
            want_n = sum(1 for a in notes if a.si == si and a.note[1] == nkind)
            before_sec = _notes_in(doc, si, nkind)
            after_sec = _notes_in(newdoc, si, nkind)
            if None in after_sec or len(after_sec) != len(before_sec) + want_n:
                return False
    for a in notes:
        p, nkind, text = a.note
        np = _new_para(doc, newdoc, p, st)
        if np is None or np.text != p.text:
            return False
        before_p = _notes_in(doc, p.si, nkind, p)
        after_p = list(_notes_in(newdoc, np.si, nkind, np))
        if len(after_p) != len(before_p) + 1:
            return False
        for old in before_p:
            if old not in after_p:
                return False
            after_p.remove(old)
        if after_p != [text]:
            return False
    return True


def _table_captions(d, t):
    """[(side, num, before_num, after_num)] of the direct <hp:caption> controls on table `t`."""
    s = d.secs[t.si]
    inner = [t2 for t2 in d.sec_tables[t.si] if t.start < t2.start < t.end]
    out = []
    for m in re.finditer(r"<hp:caption\b[^>]*>.*?</hp:caption>", s[t.start:t.end], re.S):
        ca, cb = t.start + m.start(), t.start + m.end()
        if any(t2.start < ca < t2.end for t2 in inner):
            continue
        raw = m.group(0)
        open_tag = raw[:raw.find(">") + 1]
        side = _attr(open_tag, "side")
        an = re.search(r"<hp:autoNum\b[^>]*>", raw)
        num = _attr(an.group(0), "num") if an and _attr(an.group(0), "numType") == "TABLE" else None
        ps = [q for q in t.caption if ca < q.start < cb]
        if len(ps) != 1 or an is None:
            out.append((side, num, None, "\n".join(q.text for q in ps)))
            continue
        q = ps[0]
        an_pos = ca + an.start()
        before = "".join(ch for ch, xp in zip(q.chars, q.xpos) if ch != OBJ and xp < an_pos)
        after = "".join(ch for ch, xp in zip(q.chars, q.xpos) if ch != OBJ and xp > an_pos)
        out.append((side, num, before, after))
    return out


def _verify_captions(doc, newdoc, acts, st):
    """Each table a caption op targeted now has one hp:caption with the side and text after Hancom's automatic
    number ("표 N "), and all other tables' captions are untouched."""
    caps = {a.caption[0]: (a.caption[1], a.caption[2]) for a in acts if a.caption}
    if not caps:
        return True
    changed_paras = {id(a.text_of) for a in acts if a.text_of is not None}
    for t in doc.tables:
        ng = st["newt"].get(t.g)
        if ng is None:
            continue
        nt = newdoc.tables[ng]
        got = _table_captions(newdoc, nt)
        if t.g in caps:
            want_side, want_text = caps[t.g]
            if len(got) != 1 or len(nt.caption) != 1:
                return False
            side, num, before, after = got[0]
            if side != want_side or not (num and num.isdigit() and int(num) >= 1):
                return False
            if before != "표 " or after != " " + want_text:
                return False
            if not any(id(q) in changed_paras for q in doc.table_paras(t)) and _table_text(nt) != _table_text(t):
                return False
        else:
            if got != _table_captions(doc, t) or [q.text for q in nt.caption] != [q.text for q in t.caption]:
                return False
    return True


def _verify_bookmarks(doc, newdoc, acts, st):
    """Each bookmark op added one <hp:bookmark> with its name inside the addressed paragraph, and left the
    paragraph's text unchanged."""
    bms = [a for a in acts if a.bookmark]
    if not bms:
        return True
    if len(newdoc.secs) < len(doc.secs):
        return False
    for si in range(len(doc.secs)):
        want = [a.bookmark[1] for a in bms if a.si == si]
        before_sec = _bookmarks_in(doc, si)
        after_sec = list(_bookmarks_in(newdoc, si))
        if len(after_sec) != len(before_sec) + len(want):
            return False
        for old in before_sec:
            if old not in after_sec:
                return False
            after_sec.remove(old)
        if sorted(after_sec) != sorted(want):
            return False
    for a in bms:
        p, bname, after = a.bookmark
        np = _new_para(doc, newdoc, p, st)
        if np is None or np.text != p.text:
            return False
        before_p = _bookmarks_in(doc, p.si, p, with_before=True)
        after_p = list(_bookmarks_in(newdoc, np.si, np, with_before=True))
        if len(after_p) != len(before_p) + 1:
            return False
        for old in before_p:
            if old not in after_p:
                return False
            after_p.remove(old)
        want_before = p.text if after is None else p.text[:p.text.find(after) + len(after)]
        if after_p != [(bname, want_before)]:
            return False
    return True


def _links_in(p):
    """[(command, range_text)] of the HYPERLINK fields in paragraph `p`."""
    out = []
    for f in p.fields:
        if (f.get("type") or "").upper() != "HYPERLINK":
            continue
        if not isinstance(f.get("e"), int):
            out.append((None, None))
            continue
        rtext = "".join(c for c in p.chars[f["b"]:f["e"]] if c != OBJ)
        out.append((f.get("command") or "", rtext))
    return out


def _link_cmd_matches(cmd, target):
    if not isinstance(cmd, str):
        return False
    if target.startswith("#"):
        return cmd.startswith("?" + target[1:] + ";")
    return cmd.startswith(target.replace(";", "\\;") + ";")


def _verify_links(doc, newdoc, acts, st):
    """Each link op kept the paragraph's text unchanged and added one HYPERLINK fieldBegin whose Command holds
    the target and whose range text equals the phrase."""
    links = {id(a.link[0]): a.link for a in acts if a.link}
    if not links:
        return True
    for p in doc.paras:
        np = _new_para(doc, newdoc, p, st)
        if np is None:
            continue
        before_p = _links_in(p)
        after_p = list(_links_in(np))
        if (None, None) in after_p:
            return False
        if id(p) not in links:
            if after_p != before_p:
                return False
            continue
        _p, phrase, target = links[id(p)]
        if np.text != p.text or len(after_p) != len(before_p) + 1:
            return False
        for old in before_p:
            if old not in after_p:
                return False
            after_p.remove(old)
        cmd, rtext = after_p[0]
        if rtext != phrase or not _link_cmd_matches(cmd, target):
            return False
    return True


def _verify_toc(doc, newdoc, acts, st):
    """A toc op inserts one TABLEOFCONTENTS field right after the addressed paragraph, and leaves the original
    paragraphs' text unchanged and in order."""
    tocs = [a for a in acts if a.toc]
    if not tocs:
        return True
    if len(tocs) != 1:
        return False
    p, levels, leader, n_added = tocs[0].toc
    np = _new_para(doc, newdoc, p, st)
    if np is None or not np.top or np.text != p.text:
        return False
    fields = _toc_fields(newdoc)
    if len(fields) != 1:
        return False
    f = fields[0]
    fid = f.get("id")
    if not fid or sum(s.count('type="TABLEOFCONTENTS"') for s in newdoc.secs) != 1:
        return False
    if sum(len(re.findall(r'<hp:fieldEnd\b[^>]*\bbeginIDRef="%s"' % re.escape(fid), s)) for s in newdoc.secs) != 1:
        return False
    if np.gp + n_added >= len(newdoc.top):
        return False
    if f.get("para") is not newdoc.top[np.gp + 1] or f.get("end_para") is not newdoc.top[np.gp + n_added]:
        return False
    if newdoc.top[np.gp + 1].text != "<제목 차례>" or newdoc.top[np.gp + n_added].text != "":
        return False
    heads = [q for q in doc.top if (doc.para_heading.get(q.pr) or ("", 99))[0] == "OUTLINE"
             and doc.para_heading[q.pr][1] < levels]
    entries = newdoc.top[np.gp + 2:np.gp + n_added]
    if len(entries) != len(heads) or any(h.text not in e.text or "\t" not in e.text for h, e in zip(heads, entries)):
        return False
    cmd = f.get("command") or ""
    lead_num = {"NONE": 0, "SOLID": 1, "DOT": 2, "DASH": 3}[leader]
    if "ContentsLevel:int:%d" % levels not in cmd or "ContentsLeader:int:%d" % lead_num not in cmd:
        return False
    changed = {id(a.text_of) for a in acts if a.text_of is not None}
    orig = [q for q in doc.top if st["newtop"](q.gp) is not None and id(q) not in changed]
    mapped = [st["newtop"](q.gp) for q in orig]
    if mapped != sorted(mapped) or [newdoc.top[g].text for g in mapped] != [q.text for q in orig]:
        return False
    return True


def _mm_hu(mm):
    return int(float(mm) * 7200 / 25.4 + 1e-6)


def _verify_page_setup(doc, newdoc, acts):
    """Each page_setup op that set start_page or border wrote startNum/@page or pageBorderFill (and its
    borderFill in header.xml) in the target section."""
    ps_acts = [a for a in acts if a.page_setup]
    if not ps_acts:
        return True
    hm = None
    for a in ps_acts:
        si, kw = a.page_setup
        if si >= len(newdoc.secs):
            return False
        m = re.search(r"<hp:secPr\b.*?</hp:secPr>", newdoc.secs[si], re.S)
        if not m:
            return False
        secpr = m.group(0)
        if "start_page" in kw:
            sn = re.search(r"<hp:startNum\b[^<>]*/?>", secpr)
            if not sn or _attr(sn.group(0), "page") != str(kw["start_page"]):
                return False
        if "border" in kw:
            if hm is None:
                hm = _header_maps(newdoc)
                if hm is None:
                    return False
            _, _, bfs, _, _ = hm
            bd = kw["border"]
            typ = bd.get("apply", "BOTH") if isinstance(bd, dict) else "BOTH"
            pm = re.search(r'<hp:pageBorderFill\b[^>]*\btype="%s"[^>]*>(?:[^<]*<hp:offset\b[^>]*/?>)?' % typ, secpr)
            if not pm:
                return False
            pbf_xml = pm.group(0)
            pbf_open = pbf_xml[:pbf_xml.find(">") + 1]
            bf = bfs.get(_attr(pbf_open, "borderFillIDRef"))
            if bf is None:
                return False
            if bd is None:
                if not _check_bf_sides(bf, False) or not _check_bf_fill(bf, None):
                    return False
            else:
                line = {"type": bd["type"], "width": bd["width"], "color": bd["color"]}
                if not _check_bf_sides(bf, line) or not _check_bf_fill(bf, bd.get("fill")):
                    return False
                if "text_border" in bd and _attr(pbf_open, "textBorder") != bd["text_border"]:
                    return False
                for key, attr_name in (("header_inside", "headerInside"), ("footer_inside", "footerInside")):
                    if key in bd and _attr(pbf_open, attr_name) != ("1" if bd[key] else "0"):
                        return False
                if "offset_mm" in bd:
                    om = re.search(r"<hp:offset\b[^>]*/?>", pbf_xml)
                    if not om:
                        return False
                    for side, val in bd["offset_mm"].items():
                        if _attr(om.group(0), side) != str(_mm_hu(val)):
                            return False
    return True


def _verify_hide(doc, newdoc, acts, st):
    """Each hide op added one <hp:pageHiding> with the requested flags in the addressed body paragraph, and left
    every other paragraph's pageHiding controls unchanged."""
    hides = {id(a.hide[0]): a.hide for a in acts if a.hide}
    if not hides:
        return True
    for p in doc.paras:
        np = _new_para(doc, newdoc, p, st)
        if np is None:
            if id(p) in hides:
                return False
            continue
        before_h = _page_hidings_in(doc, p)
        after_h = _page_hidings_in(newdoc, np)
        if None in after_h:
            return False
        if id(p) not in hides:
            if after_h != before_h:
                return False
        else:
            _p, want_kw = hides[id(p)]
            if after_h != before_h + [want_kw]:
                return False
    return True


def _verify_new_numbers(doc, newdoc, acts, st):
    """Each new_number op added one <hp:newNum> with the requested numType and num in the addressed body
    paragraph, and left every other paragraph's newNum controls unchanged."""
    nns = {id(a.new_num[0]): a.new_num for a in acts if a.new_num}
    if not nns:
        return True
    for p in doc.paras:
        np = _new_para(doc, newdoc, p, st)
        if np is None:
            if id(p) in nns:
                return False
            continue
        before_n = _new_nums_in(doc, p)
        after_n = list(_new_nums_in(newdoc, np))
        if (None, None) in after_n:
            return False
        if id(p) not in nns:
            if after_n != before_n:
                return False
        else:
            _p, want_kind, want_num = nns[id(p)]
            if len(after_n) != len(before_n) + 1:
                return False
            for old in before_n:
                if old not in after_n:
                    return False
                after_n.remove(old)
            if after_n != [(want_kind, want_num)]:
                return False
    return True


def _check_modified_pic(pic, exp):
    if pic.get("id") != exp["id"] or pic.get("bin_ref") != exp["bin_ref"]:
        return False
    if pic.get("width") is None or pic.get("height") is None:
        return False
    if abs(pic["width"] - exp["width"]) > 2 or abs(pic["height"] - exp["height"]) > 2:
        return False
    if exp["size_changed"]:
        if pic.get("cur_width") is None or pic.get("cur_height") is None:
            return False
        if abs(pic["cur_width"] - exp["cur_width"]) > 2 or abs(pic["cur_height"] - exp["cur_height"]) > 2:
            return False
    elif pic.get("cur_width") != exp["cur_width"] or pic.get("cur_height") != exp["cur_height"]:
        return False
    if pic.get("wrap") != exp["wrap"] or pic.get("treat_as_char") != exp["treat_as_char"]:
        return False
    if pic.get("vert_rel") != exp["vert_rel"] or pic.get("horz_rel") != exp["horz_rel"]:
        return False
    if pic.get("vert_offset") != exp["vert_offset"] or pic.get("horz_offset") != exp["horz_offset"]:
        return False
    return True


def _check_inserted_pic(pic, exp):
    if not pic.get("id") or not pic.get("bin_ref"):
        return False
    if pic.get("width") is None or pic.get("height") is None or pic["width"] <= 0 or pic["height"] <= 0:
        return False
    if exp["width"] is not None and abs(pic["width"] - exp["width"]) > 5:
        return False
    if exp["height"] is not None and abs(pic["height"] - exp["height"]) > 5:
        return False
    if pic.get("wrap") != exp["wrap"] or pic.get("treat_as_char") != exp["treat_as_char"]:
        return False
    if pic.get("vert_rel") != exp["vert_rel"] or pic.get("horz_rel") != exp["horz_rel"]:
        return False
    if pic.get("vert_offset") != exp["vert_offset"] or pic.get("horz_offset") != exp["horz_offset"]:
        return False
    return True


def _verify_picture(doc, newdoc, acts, st):
    """Each insert_picture and picture op produced the requested hp:pic size, textWrap, hp:pos and unchanged
    binaryItemIDRef, and left all other pictures in the document unchanged."""
    pic_acts = [a for a in acts if a.picture]
    if not pic_acts:
        return True
    base_for_new = {}
    for p in doc.paras:
        np = _new_para(doc, newdoc, p, st)
        if np is not None:
            base_for_new[id(np)] = p
    ins_by_newp = {}
    mod_by_newp = {}
    for a in pic_acts:
        mode, p, exp = a.picture
        np = _new_para(doc, newdoc, p, st)
        if np is None:
            return False
        if mode == "modify":
            mod_by_newp.setdefault(id(np), {})[exp["id"]] = exp
        else:
            if exp["inline_offset"]:
                tnp = np
            elif np.top:
                tnp = newdoc.top[np.gp + 1] if np.gp + 1 < len(newdoc.top) else None
            elif np.cell is not None:
                nk = np.cell.paras.index(np)
                tnp = np.cell.paras[nk + 1] if nk + 1 < len(np.cell.paras) else None
            else:
                tnp = None
            if tnp is None:
                return False
            ins_by_newp.setdefault(id(tnp), []).append(exp)
    for nq in newdoc.paras:
        bp_para = base_for_new.get(id(nq))
        before_pics = _pics_in(doc, bp_para) if bp_para is not None else []
        after_pics = _pics_in(newdoc, nq)
        if id(nq) not in ins_by_newp and id(nq) not in mod_by_newp:
            if after_pics != before_pics:
                return False
            continue
        ins_exps = ins_by_newp.get(id(nq), [])
        mod_exps = mod_by_newp.get(id(nq), {})
        if len(after_pics) != len(before_pics) + len(ins_exps):
            return False
        before_by_id = {bp["id"]: bp for bp in before_pics if bp.get("id")}
        if len(before_by_id) != len(before_pics):
            return False
        after_by_id = {}
        added_pics = []
        for ap in after_pics:
            aid = ap.get("id")
            if not aid or aid in after_by_id:
                return False
            after_by_id[aid] = ap
            if aid not in before_by_id:
                added_pics.append(ap)
        if len(added_pics) != len(ins_exps):
            return False
        for pid, bp in before_by_id.items():
            ap = after_by_id.get(pid)
            if ap is None:
                return False
            if pid in mod_exps:
                if not _check_modified_pic(ap, mod_exps[pid]):
                    return False
            elif ap != bp:
                return False
        used = [False] * len(added_pics)
        for exp in ins_exps:
            matched = False
            for k, ap in enumerate(added_pics):
                if not used[k] and _check_inserted_pic(ap, exp):
                    used[k] = True
                    matched = True
                    break
            if not matched:
                return False
    return True


def _verify_table_formula(doc, newdoc, acts, st):
    """Each table.formula op wrote one FORMULA field in its empty target cell with the expected Formula, Command
    and result text, and left every other cell and paragraph unchanged."""
    f_acts = [a for a in acts if a.formula]
    if not f_acts:
        return True
    if sum(len(_formula_fields_in(newdoc, nq)) for nq in newdoc.paras) != \
            sum(len(_formula_fields_in(doc, q)) for q in doc.paras) + len(f_acts):
        return False
    changed = {id(a.text_of) for a in acts if a.text_of is not None}
    targets = {}
    for a in f_acts:
        p = a.formula[0]
        if id(p) in targets:
            return False
        targets[id(p)] = a.formula
    for p in doc.paras:
        np = _new_para(doc, newdoc, p, st)
        if np is None:
            if id(p) in targets:
                return False
            continue
        before_f = _formula_fields_in(doc, p)
        after_f = _formula_fields_in(newdoc, np)
        if None in after_f:
            return False
        if id(p) not in targets:
            if after_f != before_f:
                return False
            if p.cell is not None and id(p) not in changed:
                if np.cell is None or np.text != p.text:
                    return False
                if not any(id(q) in changed for q in p.cell.paras) and len(np.cell.paras) != len(p.cell.paras):
                    return False
            continue
        if before_f or np.objs or np.cell is None or len(np.cell.paras) != 1:
            return False
        if len(after_f) != 1:
            return False
        got_formula, got_cmd, got_fmt, got_last, rtext = after_f[0]
        if np.text != rtext:
            return False
        _p, mode, spec = targets[id(p)]
        if mode == "formula":
            want_cmd = spec + ";48"
            if got_formula != want_cmd or got_cmd != want_cmd or rtext != "":
                return False
            if got_fmt is not None or got_last is not None:
                return False
        else:
            func, src_cells, is_row = spec
            new_src = []
            for sc in src_cells:
                if not sc.paras:
                    return False
                nsp = _new_para(doc, newdoc, sc.paras[0], st)
                if nsp is None or nsp.cell is None:
                    return False
                new_src.append(nsp.cell)
            want_formula, want_fmt, want_res = _formula_auto_expect(func, new_src, is_row)
            want_cmd = "%s??%s;;%s" % (want_formula, want_fmt, want_res)
            if got_formula != want_formula or got_cmd != want_cmd:
                return False
            if got_fmt != want_fmt or got_last != want_res or rtext != want_res:
                return False
    return True


def _verify_shapes(doc, newdoc, acts, st):
    """The tables the table.* shape ops changed have the grid, cell count and merged cells they planned."""
    want = {}               # g -> expected change in the number of cells
    for a in acts:
        for g, delta in a.cell_delta:
            want[g] = want.get(g, 0) + delta
        for g, c in a.col_dels:
            want[g] = want.get(g, 0) - sum(1 for x in doc.tables[g].cells if x.col == c and x.cs == 1)
        for g, first, inside, _span in a.merges:
            want[g] = want.get(g, 0) - (len(inside) - 1)
        for g, x, rows, cols in a.splits:
            want[g] = want.get(g, 0) + rows * cols - 1
        for g in a.resized + a.restyled:
            want.setdefault(g, 0)
    for g, delta in want.items():
        t, ng = doc.tables[g], st["newt"][g]
        if ng is None:
            return False
        nt = newdoc.tables[ng]
        rows = t.rows + len(st["radds"].get(g, ())) - len(st["rdels"].get(g, ()))
        cols = t.cols + len(st["coladds"].get(g, ())) - len(st["coldels"].get(g, ()))
        if (nt.rows, nt.cols) != (rows, cols) or len(nt.cells) != len(t.cells) + delta:
            return False
    for a in acts:
        for g in a.resized:
            nt = newdoc.tables[st["newt"][g]]
            if _table_text(nt) != _table_text(doc.tables[g]):
                return False
        for g, first, inside, (rs, cs) in a.merges:
            nt, rc = newdoc.tables[st["newt"][g]], st["newcell"](g, first)
            y = nt.at(*rc) if rc else None
            n = len(_merge_paras(inside)) or len(first.paras)
            if y is None or (y.row, y.col, y.rs, y.cs) != (rc[0], rc[1], rs, cs) or len(y.paras) != n:
                return False
        for g, x, rows, cols in a.splits:
            nt, rc = newdoc.tables[st["newt"][g]], st["newcell"](g, x)
            y = nt.at(*rc) if rc else None
            span = (x.rs // rows if x.rs > 1 else 1, x.cs // cols if x.cs > 1 else 1)
            if y is None or (y.row, y.col) != rc or (y.rs, y.cs) != span or _cell_text(y) != _cell_text(x):
                return False
    return True


def _remap_result(doc, newdoc, acts):
    """(remap, approx): the exact remap when the output confirms it, else a text alignment flagged approx."""
    remap = _remap(doc, acts)
    if newdoc is None or _verify(doc, newdoc, acts):
        return remap, False
    dels = [a for a in acts if a.top_dels or a.tbl_dels or a.row_dels or a.cell_dels or a.col_dels or a.merges
            or a.hf or a.new_style or a.note or a.caption or a.bookmark or a.link or a.toc
            or a.char_shape or a.para_shape or a.page_setup or a.hide or a.new_num or a.picture or a.formula]
    if dels:        # a removal (or a new style) the output does not show was not done: never report it applied
        raise DocError("internal", "the output does not show what op %d (%s) does; nothing was written"
                       % (dels[0].i, dels[0].op), at=dels[0].at, i=dels[0].i, written=False)
    return _align_remap(doc, newdoc), True


def follow_remap(remap, at):
    """Where an address of the base document is after an edit: its own entry, else the longest listed prefix
    (``t1 -> t2`` makes ``t1/r0/c3`` ``t2/r0/c3``); None when it, or what holds it, was deleted."""
    table = remap if isinstance(remap, dict) else {m["from"]: m["to"] for m in remap}
    rng = ""
    if isinstance(at, str) and ":" in at and not at.startswith(("h:", "place:", "page:")):
        at, rng = at.split(":", 1)
        rng = ":" + rng
    if at in table:
        return None if table[at] is None else table[at] + rng
    parts = at.split("/")
    for n in range(len(parts) - 1, 0, -1):
        pre = "/".join(parts[:n])
        if pre in table:
            to = table[pre]
            return None if to is None else "/".join([to] + parts[n:]) + rng
    return at + rng


def _carry_places(doc, newdoc, res):
    """Carry the base's fill places into the output by the exact remap (never by a guessed one)."""
    if newdoc is None or res.get("remap_approx"):
        return
    pls = _places(doc)
    if not pls:
        return
    carried = []
    for pl in pls:
        at = follow_remap(res["remap"], pl["at"])
        if at:
            carried.append({"id": pl["id"], "at": at, "label": pl.get("label"), "kind": pl.get("kind"),
                            **({"field_id": pl["field_id"]} if pl.get("field_id") is not None else {})})
    _lineage_put(newdoc.sha, carried)


def _signals(pl, doc=None, pages=None):
    """The engine's per-page layout findings as [{page, kind, at?, ...}]."""
    out = []
    # a heading on the last page has nothing after its body to be cut off from: a short final section ("## 4.
    # 향후 계획" and one bullet) is short because the document ends there, not because the page breaks
    last = max((e.get("page") for e in pl or [] if isinstance(e.get("page"), int)), default=None)
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
        if bh and not e.get("lone_heading") and n != last and 0 < (bh.get("lines_after") or 0) <= 3:
            out.append({"page": n, "kind": "bottom_heading", "at": at(bh.get("chain_para", bh.get("para"))),
                        "text": bh.get("text"), "lines_after": bh.get("lines_after")})
        for ts in e.get("table_split") or []:
            rec = {"page": n, "kind": "table_split", "at": at(ts.get("para")), "pages": ts.get("pages"),
                   "rows": ts.get("rows")}
            if doc is not None and isinstance(ts.get("para"), int) and 0 <= ts["para"] < len(doc.top):
                tt = [t for t in doc.tables_in(doc.top[ts["para"]]) if t.addr and t.parent is None]
                if tt:
                    rec["at"] = tt[0].addr
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
    changed_pages, signals} (+ changed with preview=True).

    One snapshot: the file's bytes are read once; base is checked against them and every op is planned on
    them. The output is built, parsed back, remapped and described completely before anything is published,
    so a failure leaves every file as it was (``written: false``). An in-place edit is a compare-and-swap:
    under the destination's lock the file must still be ``base`` immediately before the atomic replace."""
    if not isinstance(base, str) or not base:
        raise DocError("bad_input", "base: the rev the ops were written against (open/read give it)")
    doc = _load(path)
    src = doc.path
    if base != doc.rev:
        raise DocError("stale", "the document changed since rev %s (it is now %s); read it again" % (base, doc.rev),
                       rev=doc.rev, retryable=True)
    acts = _plan(doc, ops)
    if preview:
        pdir = _scratch_sub("preview")
        _prune(pdir)
        fd, t = tempfile.mkstemp(prefix="preview-%s-" % doc.rev, suffix=".hwpx", dir=str(pdir))
        os.close(fd)
        target = Path(t)
    elif in_place:
        target = src
    else:
        target = _check_out(out if out is not None else _default_out(src), [src], suffixes=(".hwpx", ".hwp"))
    if target.suffix.lower() not in (".hwpx", ".hwp"):
        raise DocError("bad_input", "out must end in .hwpx or .hwp")
    try:
        res, data, newdoc = _edit_build(doc, acts, target, preview)
    except DocError as exc:
        exc.extra.setdefault("written", False)
        raise
    except Exception as exc:  # noqa: BLE001 - reported with written: false
        raise DocError("internal", "%s: %s" % (type(exc).__name__, exc), written=False)
    try:
        _publish(target, data=data, check=_still(src, base) if target == src else None)
    except DocError as exc:
        exc.extra.setdefault("written", False)
        raise
    res["out"] = str(target)
    try:                                    # after publication nothing may turn the answer into a failure
        _carry_places(doc, newdoc, res)
    except Exception as exc:  # noqa: BLE001
        res.setdefault("warnings", []).append("places: %s: %s" % (type(exc).__name__, exc))
    return res


def _still(src, base):
    """The compare-and-swap of an in-place edit: run under the destination lock right before the replace."""
    def check():
        now = _sha(_read_bytes(src))[:12]
        if now != base:
            raise DocError("stale", "the document changed while it was being edited (it is now %s); nothing was "
                           "written" % now, rev=now, retryable=True)
    return check


def _applied(acts):
    applied, seen = [], set()
    for a in acts:
        k = (a.i, a.at)
        if k in seen:
            continue
        seen.add(k)
        applied.append({"i": a.i, "op": a.op, "at": a.at,
                        **({"warnings": a.info["warnings"]} if a.info.get("warnings") else {})})
    return sorted(applied, key=lambda x: x["i"])


def _edit_build(doc, acts, target, preview):
    """(result without "out", the output's bytes, the output parsed or None). Writes nothing."""
    order = sorted(acts, key=lambda a: a.key, reverse=True)
    res = {"rev_before": doc.rev, "applied": _applied(acts)}
    warnings = []
    e = _engine()
    lay, before = {}, None
    if e is None:
        bad = [a for a in acts if a.fb is None or (a.fb[0] in ("set_para", "set_cell", "replace", "insert", "field")
                                                    and "\n" in a.fb[-1])]
        if bad or doc.format != "hwpx" or target.suffix.lower() != ".hwpx":
            a = bad[0] if bad else acts[0]
            raise _unavailable("%s needs the HWP engine (built in without it: %s on .hwpx, text without line "
                               "breaks)" % (a.op if bad else ".hwp output", ", ".join(FALLBACK_OPS)),
                               "structural_edit_unsupported", at=a.at, i=a.i)
        data = _fallback_apply(doc, order)
    else:
        data, lay, before = _engine_apply(e, doc, order, target, draft=preview)
    newdoc = None
    if target.suffix.lower() == ".hwpx":
        try:
            newdoc = Doc(target, data, "hwpx")
        except DocError as exc:
            raise DocError("internal", "the edited document does not read back (%s); nothing was written"
                           % exc.message)
    res["remap"], approx = _remap_result(doc, newdoc, acts)
    if approx:
        res["remap_approx"] = True
        warnings.append("remap: the output's structure did not match the planned edit; remap is a best guess")
    pl = lay.get("page_list") or []
    old = [x.get("hash") for x in (before.get("page_list") or [])] if before and before.get("ok") else None
    if e is not None:
        if old is not None:
            changed = [x["page"] for j, x in enumerate(pl) if j >= len(old) or x.get("hash") != old[j]]
        else:
            changed = [x["page"] for x in pl]
    else:
        changed = []
    res["changed_pages"] = changed
    try:
        sig = _signals(pl, newdoc, set(changed)) if e is not None else []
        if lay.get("approx"):
            sig.append({"page": None, "kind": "approx", "fonts": list(lay["approx"])})
    except Exception as exc:  # noqa: BLE001 - layout signals are advisory
        sig = []
        warnings.append("signals: %s: %s" % (type(exc).__name__, exc))
    res["signals"] = sig
    if preview:
        try:
            res["changed"] = _preview_changes(doc, acts, res["remap"], lay)
        except Exception as exc:  # noqa: BLE001
            res["changed"] = [{"i": x["i"], "page": None, "rect": None} for x in res["applied"]]
            warnings.append("changed: %s: %s" % (type(exc).__name__, exc))
    res["rev"] = _sha(data)[:12]
    res["engine"] = e is not None
    if warnings:
        res["warnings"] = warnings
    return res, data, newdoc


_NO_OPT = set()      # (engine folder, fn, option): options an older engine does not take (before hwp-engine #20)


def _call_opt(e, fn, args, kw, opt):
    """e.call(fn, *args, **kw, **opt) when the engine takes those options, else without them: an engine that
    answers bad_input "unknown option(s) <name>" is asked again without, and not offered them again."""
    key = _ENGINE_KEY or ""
    names = tuple(sorted(opt))
    if not opt or (key, fn, names) in _NO_OPT:
        return e.call(fn, *args, **kw)
    r = e.call(fn, *args, **kw, **opt)
    err = r.get("error") or {}
    if (not r.get("ok") and err.get("code") == "bad_input"
            and any("unknown option(s) %s" % n in str(err.get("message")) for n in names)):
        _NO_OPT.add((key, fn, names))
        r = e.call(fn, *args, **kw)
    return r


def _engine_apply(e, doc, order, target, draft=False):
    """Run the ops as one engine script on the Doc's own bytes; (output bytes, layout, pages before).
    draft: a preview copy, never handed to the user: the engine may keep the source's thumbnail instead of drawing
    page 1 again (edit(draft=True) inside its serve worker). An engine without that option is asked without it."""
    script, owner = [], []
    base_style = "0" if "0" in doc.styles else (next(iter(doc.styles), "바탕글"))
    for eng, sname, act in _auto_styles(doc, order):
        script.append({"op": "create_style", "kwargs": {"name": sname, "eng_name": eng, "base": base_style}})
        owner.append(act)
    for a in order:
        for st in a.steps:
            script.append(st)
            owner.append(a)
    f = str(doc.engine_file())
    stage = Path(tempfile.mkdtemp(prefix="edit-", dir=str(_scratch())))
    try:
        staged = stage / ("out" + target.suffix.lower())
        before = e.call("pages", f, page_hash=True)
        r = _call_opt(e, "edit", (f, script), {"out": str(staged), "layout": True, "page_hash": True},
                      {"draft": True} if draft else {})
        if not r.get("ok"):
            err = r.get("error") or {}
            step = err.get("step")
            a = owner[step] if isinstance(step, int) and not isinstance(step, bool) and 0 <= step < len(owner) \
                else None
            done_ops = []
            if a is not None:
                ran = order[:order.index(a)]
                done_ops = sorted({x.i for x in ran} - {a.i} - {x.i for x in order[order.index(a):]})
            exc = _engine_error(r, "edit", at=a.at if a else None, i=a.i if a else None)
            exc.extra["done"] = done_ops
            exc.extra["engine_done"] = err.get("done")
            exc.extra["written"] = False
            raise exc
        if not staged.is_file():
            raise DocError("internal", "the engine reported success but wrote no output; nothing was written")
        data = _read_bytes(staged)
    finally:
        shutil.rmtree(stage, True)
    return data, r.get("layout") or {}, before


def _preview_changes(doc, acts, remap, lay):
    starts = [s["para"] for s in lay.get("page_starts", []) if isinstance(s, dict)
              and isinstance(s.get("para"), int) and s["para"] >= 0] or None
    out = []
    for a in acts:
        p = doc.top_of(a.p)
        addr = follow_remap(remap, "p%d" % p.gp)
        pg = bisect.bisect_right(starts, int(addr[1:])) if (starts and addr) else None
        out.append({"i": a.i, "page": pg, "rect": None})
    return out


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


def _piece_xml(pc, pfx):
    kind, ch, src = pc
    if kind == "c":
        return src if src is not None else _esc(ch)
    if kind == "x":
        if src:
            return src
        if ch == "\t":
            return '<%s width="0" leader="0" type="0"/>' % _q(pfx, "tab")
        return {"\n": "<%s/>" % _q(pfx, "lineBreak"), "　": "<%s/>" % _q(pfx, "fwSpace")}.get(ch, " ")
    return None


def _new_pieces(text):
    return [["x", "\t", None] if ch == "\t" else ["c", ch, None] for ch in text]


def _fb_edit_para(s, p, a, b, text, pfx):
    """Section XML with ptext positions [a, b) of paragraph p replaced by text (no objects inside). Untouched
    characters keep their exact source (entities and character references included); only the changed
    paragraph's own linesegarray (its cached line layout) is dropped."""
    if any(p.posmap[j] is None for j in range(a, b)):
        raise DocError("bad_input", "the range holds an object; the built-in path edits text only")
    reps = []      # (start, end, xml)
    t_open, t_close = "<%s>" % _q(pfx, "t"), "</%s>" % _q(pfx, "t")
    if not p.tnodes:
        run = next((r for r in p.runs), None)
        if run is None:
            raise DocError("bad_input", "the paragraph has no run to type into")
        tx = t_open + "".join(_piece_xml(pc, pfx) for pc in _new_pieces(text)) + t_close
        if run["self"]:
            open_tag = s[run["a"]:run["open_end"]]
            run_name = re.match(r"<([^\s/>]+)", open_tag).group(1)
            reps.append((run["a"], run["open_end"], open_tag[:-2].rstrip() + ">" + tx + "</%s>" % run_name))
        else:
            reps.append((run["close"], run["close"], tx))
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
            if any(pc[0] in ("z", "q") for pc in tn["pieces"]) or any(
                    pc[0] == "x" and pc[2] is None and pc[1] != "\t" for pc in tn["pieces"]):
                raise DocError("bad_input", "the paragraph has marks inside its text; edit it with the engine")
            inner = "".join(_piece_xml(pc, pfx) for pc in pieces)
            open_tag = tn["open"]
            if tn["self"]:
                open_tag = open_tag[:-2].rstrip() + ">"
                close_tag = "</%s>" % re.match(r"<([^\s/>]+)", open_tag).group(1)
            else:
                close_tag = s[tn["close"]:tn["b"]]
            reps.append((tn["a"], tn["b"], open_tag + inner + close_tag))
    if p.lineseg:
        reps.append((p.lineseg[0], p.lineseg[1], ""))
    for st, en, x in sorted(reps, key=lambda r: r[0], reverse=True):
        s = s[:st] + x + s[en:]
    return s


def _fb_fill_field(s, p, f, text, pfx):
    """Section XML with a click-here field's text set to text, typed inside the field."""
    if f["e"] > f["b"]:
        return _fb_edit_para(s, p, f["b"], f["e"], text, pfx)
    t_open, t_close = "<%s>" % _q(pfx, "t"), "</%s>" % _q(pfx, "t")
    body = "".join(_piece_xml(pc, pfx) for pc in _new_pieces(text))
    inside = [tn for tn in p.tnodes if f["after"] <= tn["a"] < (f["endx"] or p.end)]
    reps = []
    if inside:
        tn = inside[0]
        if any(pc[0] != "c" for pc in tn["pieces"]):
            raise DocError("bad_input", "the field holds marks; fill it with the engine")
        if tn["self"]:
            open_tag = tn["open"][:-2].rstrip() + ">"
            close_tag = "</%s>" % re.match(r"<([^\s/>]+)", open_tag).group(1)
        else:
            open_tag, close_tag = tn["open"], s[tn["close"]:tn["b"]]
        reps.append((tn["a"], tn["b"], open_tag + body + close_tag))
    else:
        reps.append((f["after"], f["after"], t_open + body + t_close))
    if p.lineseg:
        reps.append((p.lineseg[0], p.lineseg[1], ""))
    for st, en, x in sorted(reps, key=lambda r: r[0], reverse=True):
        s = s[:st] + x + s[en:]
    return s


def _fallback_apply(doc, order):
    """The .hwpx bytes with the ops applied on the built-in XML path (untouched members copied as they are)."""
    secs = list(doc.secs)
    cache = {}

    def para_now(si, k):
        if si not in cache:
            cache[si] = _scan_section(secs[si], si, doc.canon[si])[0]
        return cache[si][k]

    changed = set()
    for a in order:
        kind = a.fb[0]
        si = a.p.si
        pfx = doc.pfx[si]
        if kind == "set_para":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, 0, len(q.chars), a.fb[2], pfx)
        elif kind == "replace":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, a.fb[2], a.fb[2] + a.fb[3], a.fb[4], pfx)
        elif kind == "insert":
            q = para_now(si, a.fb[1].k)
            secs[si] = _fb_edit_para(secs[si], q, a.fb[2], a.fb[2], a.fb[3], pfx)
        elif kind == "field":
            q = para_now(si, a.fb[1].k)
            f = next(f for f in q.fields if f["id"] == a.fb[2])
            secs[si] = _fb_fill_field(secs[si], q, f, a.fb[3], pfx)
        elif kind == "set_cell":
            c = a.fb[1]
            ks = [q.k for q in c.paras]
            for k in reversed(ks[1:]):        # extra paragraphs go
                q = para_now(si, k)
                secs[si] = secs[si][:q.start] + secs[si][q.end:]
                cache.pop(si, None)
            q = para_now(si, ks[0])
            secs[si] = _fb_edit_para(secs[si], q, 0, len(q.chars), a.fb[2], pfx)
        cache.pop(si, None)
        changed.add(si)
    replace = {}
    for si in changed:
        data = secs[si].encode("utf-8")
        try:
            ET.fromstring(data)
        except ET.ParseError as exc:
            raise DocError("internal", "the edited section would not be well-formed XML (%s); nothing written"
                           % exc)
        replace[doc.section_names[si]] = data
    out = doc.zip.rewrite(replace)
    _check_zip_bytes(out, doc.zip.names())
    return out


# ============================================================================ pages, render, geometry
@_api
def page_font_substitutions(path, *, refresh=False):
    """The same substitution report as open(), using just the page layout."""
    doc = _load(path, meta=False if refresh else "layout")
    layout = doc.layout
    if refresh:
        with doc.meta_lock:
            layout = _ecall("pages", str(doc.engine_file()))
            _set_layout(doc, layout)
    return {"rev": doc.rev, "fonts": _fonts(doc, (layout or {}).get("approx"))}


@_api
def pages(path):
    """{rev, count, pages: [{n, starts_with, signals}], approx}"""
    doc = _load(path, meta="layout")
    _need_engine("pages")
    r = doc.layout
    if r is None:
        r = _ecall("pages", str(doc.engine_file()))
    starts = {s["page"]: s.get("para") for s in r.get("page_starts") or [] if isinstance(s, dict) and "page" in s}
    sig = _signals(r.get("page_list"), doc)
    out = []
    for e in r.get("page_list") or []:
        n = e["page"]
        para = starts.get(n)
        out.append({"n": n, "number": e.get("number"), "starts_with": ("p%d" % para) if isinstance(para, int)
                    and para >= 0 else None, "fill": e.get("fill"),
                    "signals": [{k: v for k, v in x.items() if k != "page"} for x in sig if x["page"] == n]})
    return {"rev": doc.rev, "count": r.get("pages"), "pages": out, "approx": r.get("approx") or []}


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _page_list(pages_, count=None):
    """Requested pages, in the caller's order: page numbers 1..count, each once."""
    if pages_ in (None, "all"):
        if count is None:
            raise DocError("bad_input", "pages: a page number, a list of them, or \"all\"")
        return list(range(1, count + 1))
    if isinstance(pages_, str):
        a = parse_address(pages_) if pages_.startswith("page:") else ({"kind": "page", "page": int(pages_)}
                                                                      if pages_.isdigit() else None)
        if not a or a["kind"] != "page":
            raise DocError("bad_address", "pages: page:N, N, a list, or \"all\"", at=pages_)
        sel = [a["page"]]
    elif _is_int(pages_):
        sel = [pages_]
    elif isinstance(pages_, (list, tuple)) and pages_ and all(_is_int(x) for x in pages_):
        sel = list(pages_)
    else:
        raise DocError("bad_input", "pages: a page number, a list of them, or \"all\"")
    if len(set(sel)) != len(sel):
        raise DocError("bad_input", "pages: each page once (%s)" % sel)
    for n in sel:
        if n < 1 or (count is not None and n > count):
            raise DocError("bad_address", "the document has %s pages" % (count if count is not None else "1.."),
                           at="page:%d" % n, range=[1, count] if count is not None else None,
                           candidates=["page:%d" % count] if count else None)
    return sel


def _pdfium():
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415 - optional
        return pdfium
    except ImportError:
        return None


def _out_dir(out_dir, default):
    if out_dir is None:
        d = default
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = Path(os.path.abspath(os.fspath(out_dir)))
    if d.exists() and not d.is_dir():
        raise DocError("bad_input", "out_dir is a file: %s" % d)
    if not d.parent.is_dir():
        raise DocError("not_found", "the output folder's parent does not exist: %s" % d.parent)
    d.mkdir(exist_ok=True)
    return Path(os.path.realpath(d))


def _render(doc, sel, scale, fmt, names, pdf_name=None):
    """Render pages `sel` (in that order) of doc into the files `names` ({n: Path}, png) or `pdf_name` (pdf).
    Everything is drawn into a private staging folder first; nothing is published unless every page drew."""
    e = _need_engine("render")
    f = str(doc.engine_file())
    want = sorted(sel)
    stage = Path(tempfile.mkdtemp(prefix="render-", dir=str(_scratch())))
    try:
        if fmt == "png" and pdf_name is None:
            got = _engine_png(e, f, sel, want, scale, names, stage)
            if got is not None:
                return got
        spdf = stage / "pages.pdf"
        r = e.call("pdf", f, str(spdf), pages=want)
        if not r.get("ok"):
            raise _engine_error(r, "pdf")
        drawn = r.get("drawn", want)
        if not isinstance(drawn, list) or sorted(drawn) != want or not spdf.is_file():
            raise DocError("engine_protocol", "the engine drew pages %s for a request of %s" % (drawn, want))
        pdfium = _pdfium()
        if fmt == "pdf":
            recs = [{"n": n, "index": j} for j, n in enumerate(drawn)]
            if pdfium is not None:
                d = pdfium.PdfDocument(str(spdf))
                try:
                    if len(d) != len(drawn):
                        raise DocError("engine_protocol", "the PDF has %d pages, not %d" % (len(d), len(drawn)))
                    for rec in recs:
                        w, h = d[rec["index"]].get_size()
                        rec.update(width_pt=round(w, 2), height_pt=round(h, 2))
                finally:
                    d.close()
            _publish_many([(pdf_name, None, spdf)])
            for rec in recs:
                rec["file"] = str(pdf_name)
            return {"file": str(pdf_name), "pages": recs, "via": "engine_pdf"}
        if pdfium is None:
            raise _unavailable("PNG pages need pypdfium2 (pip install pypdfium2)", "rasterizer_missing")
        index = {n: j for j, n in enumerate(drawn)}
        res, items = [], []
        d = pdfium.PdfDocument(str(spdf))
        try:
            if len(d) != len(drawn):
                raise DocError("engine_protocol", "the PDF has %d pages, not %d" % (len(d), len(drawn)))
            for n in sel:
                pg = d[index[n]]
                w, h = pg.get_size()
                img = pg.render(scale=float(scale)).to_pil()
                tmp = stage / ("p%d.png" % n)
                img.save(str(tmp), "PNG")
                items.append((names[n], None, tmp))
                res.append({"n": n, "file": str(names[n]), "width_pt": round(w, 2), "height_pt": round(h, 2),
                            "px_w": img.width, "px_h": img.height})
        finally:
            d.close()
        _publish_many(items)
        return {"pages": res, "via": "engine_pdf+pypdfium2"}
    finally:
        shutil.rmtree(stage, True)


def _engine_png(e, f, sel, want, scale, names, stage):
    """The engine's own png(): the same PDF rasterised by the same pypdfium2, written by the engine's PNG writer
    (hwp-engine #20: same pixels, faster; inside its worker it reuses the layout an edit just made). None when the
    engine has no png or it fails, so the caller draws through pdf() + pypdfium2 here as before."""
    pdir = stage / "png"
    pdir.mkdir()
    try:
        # notes="layout": only the chosen pages are drawn (render reports no approx; open()/pages() give the
        # document's own)
        r = _call_opt(e, "png", (f, str(pdir)), {"pages": want, "scale": float(scale)}, {"notes": "layout"})
    except DocError:
        return None
    pages_ = r.get("pages") if r.get("ok") else None
    if not isinstance(pages_, list):
        return None
    got = {}
    for p in pages_:
        if not isinstance(p, dict) or not isinstance(p.get("file"), str):
            return None
        fp = Path(p["file"])
        if not fp.is_absolute() or fp.parent.resolve() != pdir.resolve() or not fp.is_file() or fp.is_symlink():
            return None
        with fp.open("rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
        if not all(_num(p.get(k)) for k in ("width_pt", "height_pt", "px_w", "px_h")):
            return None
        got[p.get("n")] = p
    if sorted(n for n in got if isinstance(n, int)) != want:
        return None
    items, res = [], []
    for n in sel:
        p = got[n]
        items.append((names[n], None, Path(p["file"])))
        res.append({"n": n, "file": str(names[n]), **{k: p.get(k) for k in ("width_pt", "height_pt", "px_w", "px_h")}})
    _publish_many(items)
    return {"pages": res, "via": "engine_png"}


def _render_args(doc, pages_, scale, fmt):
    if fmt not in ("png", "pdf"):
        raise DocError("bad_input", "fmt is png or pdf")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0 < scale <= 20:
        raise DocError("bad_input", "scale: a number above 0 and at most 20")
    count = doc.page_count()
    if count is None:
        r = _ecall("pages", str(doc.engine_file()))
        count = r.get("pages") if _is_int(r.get("pages")) else None
    return _page_list(pages_, count)


@_api
def render(path, pages, *, scale=2.0, fmt="png", out_dir=None):  # noqa: A002 - doc_core name
    """{rev, pages: [{n, file, width_pt, height_pt, px_w, px_h}]} in the order asked for; fmt="pdf" writes one
    PDF ({rev, file, pages: [{n, file, index, width_pt, height_pt}]}, pages in the PDF's ascending order).
    Files are ``<stem>.p<N>.png`` / ``<stem>.pdf`` in out_dir (default: a private scratch folder)."""
    doc = _load(path, meta="layout")
    _need_engine("render")
    sel = _render_args(doc, pages, scale, fmt)
    rdir = _scratch_sub("render")
    if out_dir is None:
        _prune(rdir)
    od = _out_dir(out_dir, rdir / doc.rev)
    stem = doc.path.stem
    if fmt == "pdf":
        name = _check_out(od / ("%s.pdf" % stem), [doc.path])
        r = _render(doc, sel, scale, fmt, None, name)
    else:
        names = {n: _check_out(od / ("%s.p%d.png" % (stem, n)), [doc.path]) for n in sel}
        r = _render(doc, sel, scale, fmt, names)
    r["rev"] = doc.rev
    return r


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _rect(x):
    return isinstance(x, list) and len(x) == 4 and all(_num(v) for v in x)


_SHAPES = {
    "geometry": lambda r: _is_int(r.get("page")) and _num(r.get("width_pt")) and _num(r.get("height_pt"))
    and isinstance(r.get("boxes"), list) and all(
        isinstance(b, dict) and isinstance(b.get("at"), (str, type(None))) and _rect(b.get("rect"))
        and b.get("kind") in ("para", "line", "table", "cell", "place") for b in r["boxes"]),
    "hit_test": lambda r: isinstance(r.get("at"), str) and _is_int(r.get("offset")),
    "caret_rect": lambda r: _is_int(r.get("page")) and _rect(r.get("rect")),
}


def _passthrough(fn, doc, *args):
    """An engine geometry answer, checked against the doc_core contract before it is passed on."""
    r = _ecall(fn, str(doc.engine_file()), *args)
    out = {k: v for k, v in r.items() if k not in ("api", "ok", "backend", "fn", "fallback", "file")}
    if not _SHAPES[fn](out):
        raise DocError("engine_protocol", "the engine's %s answer does not have the doc_core shape" % fn,
                       engine_fn=fn)
    out["rev"] = doc.rev
    return out


def _one_page(doc, page):
    if isinstance(page, (list, tuple)):
        raise DocError("bad_input", "page: one page number")
    return _page_list(page, doc.page_count())[0]


@_api
def geometry(path, page):
    """{rev, page, width_pt, height_pt, boxes: [{at, kind, rect, text?, baseline?, xs?}]} (engine)."""
    doc = _load(path, meta="layout")
    _need_engine("geometry")
    return _passthrough("geometry", doc, _one_page(doc, page))


@_api
def queue_addresses(path):
    """Map document-core body paragraphs and tables to the review queue's addresses."""
    doc = _load(path, meta=False)
    # The queue tools count depth-first in filename order. Document core
    # follows the spine and gives nested tables their own address grammar.
    sections = sorted(range(len(doc.section_names)), key=doc.section_names.__getitem__)
    paragraphs = (p for si in sections for p in doc.sec_paras[si])
    tables = (t for si in sections for t in doc.sec_tables[si])
    addresses = {f"p{p.gp}": f"p{i}" for i, p in enumerate(paragraphs) if p.top}
    addresses.update({t.addr: f"t{i}" for i, t in enumerate(tables) if t.addr})
    return {"rev": doc.rev, "addresses": addresses}


@_api
def hit_test(path, page, x, y):
    """{at, offset} of the point (pt) on the page (engine)."""
    doc = _load(path)
    _need_engine("hit_test")
    if not (_num(x) and _num(y)):
        raise DocError("bad_input", "x and y are numbers (pt)")
    return _passthrough("hit_test", doc, _one_page(doc, page), x, y)


@_api
def caret_rect(path, at, offset):
    """{page, rect} of the caret at offset in the paragraph at (engine)."""
    doc = _load(path)
    _need_engine("caret_rect")
    r = resolve(doc, at, allow=("para",))
    if not _is_int(offset):
        raise DocError("bad_input", "offset is an int (code points into the paragraph's text)", at=at)
    if not 0 <= offset <= len(r["para"].text):
        raise DocError("bad_address", "offset is 0..%d for %s" % (len(r["para"].text), at), at=at,
                       range=[0, len(r["para"].text)])
    return _passthrough("caret_rect", doc, at, offset)


# ============================================================================ convert, new, diff
@_api
def convert(src, out, *, to):
    """{out, lossy: [str]}; to in hwpx, hwp, pdf, png, md, docx.

    to="png": when out ends in .png, a one-page document is written to out itself and a longer one to
    ``<out stem>.p<N>.png`` beside it (out is then the first page's file); otherwise out is a folder that gets
    ``<src stem>.p<N>.png``. Every path returned exists."""
    if to not in ("hwpx", "hwp", "pdf", "png", "md", "docx"):
        raise DocError("bad_input", "to is one of hwpx, hwp, pdf, png, md, docx")
    s = _need_file(src)
    real = _format_of(s)
    if real in ("hwpx", "hwp"):
        doc = _load(s)
        if to == "png":
            _need_engine("converting to png")
            sel = _render_args(doc, "all", 2.0, "png")
            o = Path(os.path.abspath(os.fspath(out)))
            if o.suffix.lower() == ".png":
                if len(sel) == 1:
                    names = {sel[0]: _check_out(o, [s])}
                else:
                    names = {n: _check_out(o.with_name("%s.p%d.png" % (o.stem, n)), [s]) for n in sel}
                r = _render(doc, sel, 2.0, "png", names)
                return {"out": r["pages"][0]["file"], "pages": r["pages"], "lossy": []}
            od = _out_dir(o, o)
            names = {n: _check_out(od / ("%s.p%d.png" % (s.stem, n)), [s]) for n in sel}
            r = _render(doc, sel, 2.0, "png", names)
            return {"out": str(od), "pages": r["pages"], "lossy": []}
        o = _check_out(out, [s], suffixes=("." + to,) if to != "md" else (".md", ".markdown"))
        if to == "hwpx" and doc.format == "hwpx":
            _publish(o, data=doc.raw)
            return {"out": str(o), "lossy": []}
        if to == "hwpx":                    # the engine's conversion of the .hwp, read once into the Doc
            _publish(o, data=doc.raw)
            try:
                lossy = json.loads((_scratch_sub("hwp") / ("%s.json" % doc.sha[:24])).read_text("utf-8"))
            except (OSError, ValueError):
                lossy = []
            return {"out": str(o), "lossy": [str(x) for x in lossy]}
        if _engine() is None and to == "md":
            raise _unavailable("markdown export needs the HWP engine", "engine_not_configured")
        e = _need_engine("converting to %s" % to)
        fn = {"hwp": "save", "pdf": "pdf"}.get(to, "convert")
        stage = Path(tempfile.mkdtemp(prefix="convert-", dir=str(_scratch())))
        try:
            staged = stage / ("out" + o.suffix.lower())
            kw = {"to": to} if fn == "convert" else {}
            r = e.call(fn, str(doc.engine_file()), str(staged), **kw)
            if not r.get("ok"):
                raise _engine_error(r, fn)
            if not staged.is_file():
                raise DocError("engine_protocol", "the engine reported success but wrote no %s" % to)
            _publish(o, src=staged)
        finally:
            shutil.rmtree(stage, True)
        lossy = {"hwp": r.get("warnings"), "pdf": r.get("approx")}.get(to, r.get("lossy"))
        return {"out": str(o), "lossy": [str(x) for x in (lossy or [])]}
    o = _check_out(out, [s], suffixes=("." + to,))
    e = _need_engine("converting to %s" % to)
    stage = Path(tempfile.mkdtemp(prefix="convert-", dir=str(_scratch())))
    try:
        staged = stage / ("out" + o.suffix.lower())
        r = e.call("convert", str(s), str(staged), to=to)
        if not r.get("ok"):
            raise _engine_error(r, "convert")
        if not staged.is_file():
            raise DocError("engine_protocol", "the engine reported success but wrote no %s" % to)
        _publish(o, src=staged)
    finally:
        shutil.rmtree(stage, True)
    return {"out": str(o), "lossy": [str(x) for x in (r.get("lossy") or [])]}


@_api
def new(markdown_path_or_text, out, *, form=None, commonmark=False):
    """{out, rev}: a document built from markdown (a .md path or the text), optionally on a form.

    commonmark=True reads the markdown as CommonMark with GFM tables, the way the engine converts a .md file:
    lists and tables become lists and tables, and headings carry no automatic number (a heading written
    "1. 개요" shows as written). Pictures are taken only from the markdown file's own folder, so pass a .md
    path that sits beside them. Without it the markdown is the report dialect (□/○ markers, TABLE:, \\newpage),
    whose heading style numbers each heading. Not with form."""
    src = markdown_path_or_text
    if isinstance(src, os.PathLike):
        src = os.fspath(src)
    if not isinstance(src, str) or not src.strip():
        raise DocError("bad_input", "new needs markdown text or a .md path")
    inputs = []
    if "\n" not in src and Path(src).is_file():
        src = str(Path(src).resolve())
        inputs.append(src)
    fpath = None
    if form is not None:
        fpath = _need_file(form)
        inputs.append(fpath)
    if commonmark and fpath is not None:
        raise DocError("bad_input", "commonmark markdown is not written on a form")
    o = _check_out(out, inputs, suffixes=(".hwpx",))
    e = _need_engine("new")
    stage = Path(tempfile.mkdtemp(prefix="new-", dir=str(_scratch())))
    try:
        staged = stage / "new.hwpx"
        if commonmark:
            md = src
            if not inputs:
                md = str(stage / "content.md")
                Path(md).write_text(src, encoding="utf-8")
            r = e.call("convert", md, str(staged), to="hwpx")
            if not r.get("ok"):
                raise _engine_error(r, "convert")
            r = {"ok": True, "warnings": list(r.get("lossy") or [])}
        else:
            kw = {"form": str(fpath)} if fpath is not None else {}
            r = e.call("build", src, str(staged), **kw)
        if not r.get("ok"):
            raise _engine_error(r, "build")
        if not staged.is_file():
            raise DocError("engine_protocol", "the engine reported success but wrote no document")
        data = _read_bytes(staged)
        _publish(o, data=data)
    finally:
        shutil.rmtree(stage, True)
    return {"out": str(o), "rev": _sha(data)[:12], "warnings": list(r.get("warnings") or [])}


@_api
def diff(a, b):
    """{changes: [{at, before, after, kind, at_b?}]}: top-level paragraphs and table cells."""
    da, db = _load(a, meta=False), _load(b, meta=False)
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
    for ta in da.tables:
        tb = db.by_addr.get(ta.addr) if ta.addr else None
        if tb is None:
            continue
        for c in ta.cells:
            cb = tb.at(c.row, c.col)
            before, after = _cell_text(c), (_cell_text(cb) if cb is not None else None)
            if before != after:
                ch.append({"at": cell_address(ta, c), "kind": "changed",
                           "before": before, "after": after})
    return {"rev_a": da.rev, "rev_b": db.rev, "changes": ch}


__all__ = ["open", "outline", "read", "find", "edit", "render", "geometry", "hit_test", "caret_rect", "pages",
           "convert", "new", "diff", "parse_address", "resolve", "follow_remap", "rev_of", "close", "engine_status",
           "DocError"]
