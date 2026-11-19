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
import importlib.util
import io
import itertools
import json
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
       "table.delete_row", "fill", "style", "insert_table", "insert_picture", "insert_equation")
#: ops the built-in XML path can do without the engine
FALLBACK_OPS = ("set", "replace", "table.set_cells", "fill", "delete")

_bopen = builtins.open
_RETRYABLE = {"stale": True, "busy": True, "engine_timeout": True, "engine_unavailable": True, "internal": False}


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
    with _bopen(path, "rb") as f:
        return f.read()


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
    with _bopen(path, "rb") as f:
        return _format_of_bytes(f.read(8), path)


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
                            os.remove(self.file)
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
    raise DocError("busy", "%s is open in another program (or not writable); close it and retry" % Path(dest).name,
                   at=str(dest), retryable=True)


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


def _stage(dest, data=None, src=None):
    """A unique temp file next to dest holding data (bytes) or a copy of src, flushed to disk."""
    fd, tmp = tempfile.mkstemp(prefix=".rtdoc-", suffix=".tmp", dir=str(Path(dest).parent))
    try:
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
        self.proc = subprocess.Popen([sys.executable, str(kit_dir / "kit_api.py"), "serve", "--threads", "4"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=str(kit_dir), env=env)
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


def _engine_error(env, fn=None, at=None, i=None):
    """An engine failure envelope -> DocError keeping code, message, step, done and the worker's own at /
    retryable (ours win only when we have one)."""
    err = env.get("error") if isinstance(env.get("error"), dict) else {}
    code = str(err.get("code") or "internal")
    msg = str(err.get("message") or "the engine refused %s" % fn)
    if code == "unsupported" and msg.startswith("no such function"):
        return _unavailable("the installed engine has no %s yet" % fn, "engine_function_missing", fn=fn)
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
                 "runs", "objs", "head", "lineseg", "caption_of", "in_box")

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
        for g, t in enumerate(self.tables):
            t.g = g
            if not t.rows and t.cells:
                t.rows = max(c.row + c.rs for c in t.cells)
            if not t.cols and t.cells:
                t.cols = max(c.col + c.cs for c in t.cells)
        self.styles, self.para_heading, self.bold_cp, self.fonts = _header_info(hdr)
        self.meta_lock = threading.Lock()
        self.meta_done = False
        self.meta_errors = []
        self.layout = None
        self.engine_headings = None     # None: no engine analysis (not run, or it failed); [] : it found none
        self.engine_places = None
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
        return next((t for t in self.tables if cell in t.cells), None)

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
    every function resolves addresses against the same metadata whatever ran before."""
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
        _ensure_meta(d, e)
    return d


def _ensure_meta(d, e):
    """Layout (pages) and form analysis (headings, places) from the engine, once per Doc. A transient failure
    (timeout, worker gone) is retried by the next call; any other failure is kept, and the Doc then uses the
    built-in analysis, the same for every caller."""
    if d.meta_done:
        return
    with d.meta_lock:
        if d.meta_done:
            return
        f = str(d.engine_file())
        transient = False
        if d.layout is None:
            r = e.call("pages", f)
            if r.get("ok"):
                d.layout = r
                d.page_starts = [s["para"] for s in r.get("page_starts") or []
                                 if isinstance(s, dict) and isinstance(s.get("para"), int) and s["para"] >= 0] or [0]
            else:
                transient |= bool((r.get("error") or {}).get("retryable"))
                d.meta_errors.append({"fn": "pages", **(r.get("error") or {})})
        if d.engine_places is None:
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
    for f in doc.fonts:
        if f not in used:
            used.append(f)
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
    """{rev, headings: [{at, level, text, page?}], tables: [{at, rows, cols, caption?, page?}],
    places: [{id, at, label, kind, page?, rect?}]}"""
    doc = _load(path)
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
    doc = _load(path)
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


def _remap_result(doc, newdoc, acts):
    remap = _remap(doc, acts)
    if newdoc is not None:
        expect_top = len(doc.top) + sum(a.dtop for a in acts) - sum(len(a.dels) for a in acts)
        if len(newdoc.top) != expect_top:
            return _align_remap(doc, newdoc), True
    return remap, False


def _carry_places(doc, newdoc, res):
    pass


def follow_remap(remap, at):
    """Where an address of the base document is after an edit: its own entry, else the longest listed prefix
    (``t1 -> t2`` makes ``t1/r0/c3`` ``t2/r0/c3``); None when it was deleted."""
    table = {m["from"]: m["to"] for m in remap}
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
    check = None
    if target == src:
        def check():
            now = _sha(_read_bytes(src))[:12]
            if now != base:
                raise DocError("stale", "the document changed while it was being edited (it is now %s); nothing "
                               "was written" % now, rev=now, retryable=True)
    try:
        _publish(target, data=data, check=check)
    except DocError as exc:
        exc.extra.setdefault("written", False)
        raise
    res["out"] = str(target)
    try:                                    # after publication nothing may turn the answer into a failure
        _carry_places(doc, newdoc, res)
    except Exception as exc:  # noqa: BLE001
        res.setdefault("warnings", []).append("places: %s: %s" % (type(exc).__name__, exc))
    return res


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
        bad = [a for a in acts if a.fb is None or (a.fb[0] in ("set_para", "set_cell", "replace", "insert")
                                                    and "\n" in a.fb[-1])]
        if bad or doc.format != "hwpx" or target.suffix.lower() != ".hwpx":
            a = bad[0] if bad else acts[0]
            raise _unavailable("%s needs the HWP engine (built in without it: %s on .hwpx, text without line "
                               "breaks)" % (a.op if bad else ".hwp output", ", ".join(FALLBACK_OPS)),
                               "structural_edit_unsupported", at=a.at, i=a.i)
        data = _fallback_apply(doc, order)
    else:
        data, lay, before = _engine_apply(e, doc, order, target)
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


def _engine_apply(e, doc, order, target):
    """Run the ops as one engine script on the Doc's own bytes; (output bytes, layout, pages before)."""
    script, owner = [], []
    for a in order:
        for st in a.steps:
            script.append(st)
            owner.append(a)
    f = str(doc.engine_file())
    stage = Path(tempfile.mkdtemp(prefix="edit-", dir=str(_scratch())))
    try:
        staged = stage / ("out" + target.suffix.lower())
        before = e.call("pages", f, page_hash=True)
        r = e.call("edit", f, script, out=str(staged), layout=True, page_hash=True)
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
def pages(path):
    """{rev, count, pages: [{n, starts_with, signals}], approx}"""
    doc = _load(path)
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
                           at="page:%d" % n, candidates=["page:%d" % count] if count else None)
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
    doc = _load(path)
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
    doc = _load(path)
    _need_engine("geometry")
    return _passthrough("geometry", doc, _one_page(doc, page))


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
    if not _is_int(offset) or not 0 <= offset <= len(r["para"].text):
        raise DocError("bad_input", "offset is 0..%d for %s" % (len(r["para"].text), at), at=at)
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
def new(markdown_path_or_text, out, *, form=None):
    """{out, rev}: a document built from markdown (a .md path or the text), optionally on a form."""
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
    o = _check_out(out, inputs, suffixes=(".hwpx",))
    e = _need_engine("new")
    stage = Path(tempfile.mkdtemp(prefix="new-", dir=str(_scratch())))
    try:
        staged = stage / "new.hwpx"
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
    for ta, tb in zip(da.tables, db.tables):
        for c in ta.cells:
            cb = tb.at(c.row, c.col)
            before, after = _cell_text(c), (_cell_text(cb) if cb is not None else None)
            if before != after:
                ch.append({"at": "t%d/r%d/c%d" % (ta.g, c.row, c.col), "kind": "changed",
                           "before": before, "after": after})
    return {"rev_a": da.rev, "rev_b": db.rev, "changes": ch}


__all__ = ["open", "outline", "read", "find", "edit", "render", "geometry", "hit_test", "caret_rect", "pages",
           "convert", "new", "diff", "parse_address", "resolve", "follow_remap", "rev_of", "close", "engine_status",
           "DocError"]
