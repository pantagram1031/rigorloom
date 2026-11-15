#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local HTTP/SSE UI bridge and Host sidecar manager for Rigorloom Runtime.

Serves the built frontend bundle (preferring packaged ``ui_dist/`` over a repo
checkout's ``desktop/dist/``, with a minimal standalone HTML fallback) strictly on
``127.0.0.1``, validates ``Host``, ``Sec-Fetch-Site``, and per-launch bearer
tokens, forwards JSON-RPC to ``serve.py --entry host`` over stdio, and streams
runtime / agent-host notifications over Server-Sent Events (``/events``).
"""
from __future__ import annotations

import base64
import binascii
from collections import Counter
from datetime import datetime, timezone
import difflib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit
import uuid
import webbrowser
import xml.etree.ElementTree as ET
import zipfile

try:
    from .rt_apply import _argv_for as _apply_argv_for
    from .rt_codes import IMPL_VERSION, PROTOCOL_VERSION, RpcError
    from .rt_session import MAX_SOURCE_BYTES, atomic_write_bytes, sha256_file
except ImportError:
    from rt_apply import _argv_for as _apply_argv_for
    from rt_codes import IMPL_VERSION, PROTOCOL_VERSION, RpcError
    from rt_session import MAX_SOURCE_BYTES, atomic_write_bytes, sha256_file

HERE = Path(__file__).resolve().parent
SERVE_SCRIPT = HERE / "serve.py"
MOCK_AGENT_SCRIPT = HERE / "mock_agent.py"

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
ALLOWED_GATE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_CREDENTIAL_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
VALID_UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SECTION_MEMBER_RE = re.compile(r"^Contents/section(\d+)\.xml$")

MAX_JSON_BODY_BYTES = max(64 * 1024 * 1024, MAX_SOURCE_BYTES * 2)
SSE_KEEPALIVE_SECONDS = 15.0

AGENTHOST_CONFIG_KEYS = frozenset({
    "providerId",
    "baseUrl",
    "model",
    "credential",
    "capabilities",
    "maxTokens",
    "timeoutSeconds",
    "maxResponseBytes",
    "anthropicVersion",
    "extraHeaders",
    "notes",
})
AGENTHOST_SECRET_KEYS = frozenset({
    "apikey",
    "token",
    "accesstoken",
    "secret",
    "password",
    "authorization",
    "bearer",
    "credentialvalue",
    "xapikey",
})
AGENTHOST_PROVIDERS = ("mock", "anthropic", "router")

FALLBACK_INDEX_HTML = (
    "<!doctype html>\n"
    "<html lang=\"en\">\n"
    "<head><meta charset=\"utf-8\"><title>Rigorloom UI</title></head>\n"
    "<body><div id=\"root\">Rigorloom UI</div></body>\n"
    "</html>\n"
)

_MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

_SCRIPT_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)
_BODY_CLOSE_RE = re.compile(r"</body>", re.IGNORECASE)


class BridgeError(Exception):
    """Structured error turned into a consistent JSON HTTP error response."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = HTTPStatus.BAD_REQUEST,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.data = data

    def to_payload(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return {"ok": False, "error": err}


def default_runtime_root() -> Path:
    """Resolve the XDG/home default runtime root directory for `rigorloom ui`."""
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else (Path.home() / ".local" / "share")
    return base / "rigorloom" / "runtime-root"


def _discover_repo_root(engine_root: Path | None) -> Path | None:
    """Locate the checkout root when running from a source tree (None in wheel)."""
    candidates: list[Path] = []
    if engine_root is not None:
        candidates.append(Path(engine_root).resolve())
    env_root = os.environ.get("RIGORLOOM_ENGINE_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    # runtime/scripts/rt_ui.py -> parents[1] is the repo root in a checkout.
    if len(HERE.parents) >= 2:
        candidates.append(HERE.parents[1])
    if len(HERE.parents) >= 3:
        candidates.append(HERE.parents[2])
    for candidate in candidates:
        if ((candidate / "modules").is_dir()
                or (candidate / "runtime" / "scripts" / "serve.py").is_file()
                or (candidate / "engine").is_dir()):
            return candidate
    return None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _valid_host_header(host_value: str | None) -> bool:
    """Allow only 127.0.0.1 or localhost (with optional numeric :port)."""
    if not host_value:
        return False
    raw = host_value.strip()
    if not raw or any(ch in raw for ch in ("/", "@", "\\", "[", "]", " ", "\t")):
        return False
    host, sep, port_str = raw.partition(":")
    if sep and (not port_str or not port_str.isdigit()):
        return False
    return host.lower() in ALLOWED_HOSTS


def _inject_bootstrap(html: str, payload: dict[str, Any]) -> str:
    """Inject window.__RIGORLOOM_UI__ before </head> with script-breakout escaping."""
    serialized = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    script = f"<script>window.__RIGORLOOM_UI__={serialized};</script>"
    if _SCRIPT_CLOSE_RE.search(html):
        return _SCRIPT_CLOSE_RE.sub(lambda _: script + "</head>", html, count=1)
    if _BODY_CLOSE_RE.search(html):
        return _BODY_CLOSE_RE.sub(lambda _: script + "</body>", html, count=1)
    return script + html


def _sanitize_upload_filename(raw_name: str) -> str:
    """Clean an uploaded filename into a single safe component with .hwpx/.hwp."""
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise BridgeError("invalid_params", "filename must be a non-empty string")
    base = Path(raw_name.replace("\\", "/")).name.strip()
    base = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", base)
    if not base or base in (".", "..") or ".." in base:
        raise BridgeError("invalid_filename", f"unsafe upload filename: {raw_name!r}")
    if len(base) > 160:
        stem, suffix = os.path.splitext(base)
        base = stem[:140] + suffix[:20]
    return base


def _require_bare_component(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or not VALID_UPLOAD_NAME_RE.match(value):
        raise BridgeError("invalid_params", f"{name} must be a bare identifier matching [A-Za-z0-9._-]+", status=HTTPStatus.BAD_REQUEST)
    if value in (".", "..") or ".." in value:
        raise BridgeError("invalid_params", f"{name} contains forbidden path segment", status=HTTPStatus.BAD_REQUEST)
    return value


def _resolve_relative_candidate(candidate_dir: Path, raw_rel: str) -> Path:
    if not isinstance(raw_rel, str) or not raw_rel.strip():
        raise BridgeError("invalid_params", "candidatePath must be a non-empty string")
    p = Path(raw_rel)
    resolved_dir = candidate_dir.resolve()
    target = (p if p.is_absolute() else (resolved_dir / p)).resolve()
    if not target.is_relative_to(resolved_dir):
        raise BridgeError(
            "invalid_params",
            "candidatePath escapes candidate directory",
            status=HTTPStatus.BAD_REQUEST,
        )
    return target


def _paths_alias(a: Path, b: Path) -> bool:
    """Return True if two paths refer to the same file/target (fail-closed)."""
    if a == b:
        return True
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        return True
    ra = os.path.normcase(str(a.resolve(strict=False)))
    rb = os.path.normcase(str(b.resolve(strict=False)))
    return ra == rb


def _atomic_copy_durable(src: Path, dst: Path) -> None:
    """Copy src to dst via a same-directory temp file, fsync, and os.replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{uuid.uuid4().hex[:10]}.tmp"
    try:
        with src.open("rb") as fin, tmp.open("wb") as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
            fout.flush()
            os.fsync(fout.fileno())
        os.replace(tmp, dst)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _check_secret_keys(obj: Any, where: str = "settings") -> None:
    """Reject secret-shaped config keys recursively."""
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        norm = str(key).replace("-", "").replace("_", "").lower()
        if norm in AGENTHOST_SECRET_KEYS:
            raise BridgeError(
                "secret_in_config",
                f"{where} key {key!r} looks like a credential; store secrets via "
                "/api/credential/set instead of config files",
                data={"member": str(key)},
            )
        if isinstance(value, dict):
            _check_secret_keys(value, f"{where}.{key}")


def _validate_agenthost_settings(provider: str, settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise BridgeError("invalid_params", "settings must be an object")
    _check_secret_keys(settings, "settings")
    unknown = sorted(set(settings) - AGENTHOST_CONFIG_KEYS)
    if unknown:
        raise BridgeError(
            "unknown_field",
            f"settings contains unsupported keys for {provider}: {', '.join(unknown)}",
            data={"unknown": unknown, "allowed": sorted(AGENTHOST_CONFIG_KEYS)},
        )
    return dict(settings)


def _load_python_module(name: str, path: Path):
    """Load an auxiliary Python script cleanly by path."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise BridgeError(
            "module_load_failed",
            f"could not load module from {path}",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _try_import_rt_guard():
    """Return rt_guard module if present on this branch, else None."""
    for mod_name in ("rigorloom_runtime.rt_guard", "rt_guard"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            return mod
    try:
        from . import rt_guard  # type: ignore[attr-defined]
        return rt_guard
    except ImportError:
        try:
            import rt_guard  # type: ignore[import-not-found]
            return rt_guard
        except ImportError:
            return None


def _localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _collect_direct_paragraph_text(p_elem: ET.Element) -> str:
    """Extract <hp:t> text belonging directly to `p_elem` (not nested tables)."""
    chunks: list[str] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            lname = _localname(child.tag)
            if lname in ("tbl", "subList", "p"):
                continue
            if lname == "t":
                chunks.append("".join(child.itertext()))
            elif lname == "tab":
                chunks.append("\t")
            else:
                walk(child)

    walk(p_elem)
    return "".join(chunks)


def _extract_hwpx_paragraphs(hwpx_path: Path) -> list[str]:
    """Extract paragraph strings in document reading order from HWPX section XMLs."""
    paragraphs: list[str] = []
    with zipfile.ZipFile(hwpx_path, "r") as zf:
        section_names = [n for n in zf.namelist() if SECTION_MEMBER_RE.match(n)]
        section_names.sort(key=lambda n: int(SECTION_MEMBER_RE.match(n).group(1)))
        for member in section_names:
            root = ET.fromstring(zf.read(member))

            def visit(elem: ET.Element) -> None:
                if _localname(elem.tag) == "p":
                    has_direct_run = any(_localname(c.tag) == "run" for c in elem)
                    text = _collect_direct_paragraph_text(elem)
                    has_nested_tbl = any(
                        _localname(c.tag) in ("tbl", "subList")
                        or any(_localname(gc.tag) in ("tbl", "subList") for gc in c)
                        for c in elem
                    )
                    if text or (has_direct_run and not has_nested_tbl):
                        paragraphs.append(text)
                    for child in elem:
                        if _localname(child.tag) != "run":
                            visit(child)
                        else:
                            for gc in child:
                                if _localname(gc.tag) != "t":
                                    visit(gc)
                else:
                    for child in elem:
                        visit(child)

            visit(root)
    return paragraphs


def _pair_paragraphs(before_paras: list[str], after_paras: list[str]) -> list[tuple[str, str]]:
    """Align paragraphs between before and after versions cleanly."""
    if len(before_paras) == len(after_paras):
        return list(zip(before_paras, after_paras))
    matcher = difflib.SequenceMatcher(None, before_paras, after_paras)
    paired: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                paired.append((before_paras[i1 + k], after_paras[j1 + k]))
        else:
            b_slice = before_paras[i1:i2]
            a_slice = after_paras[j1:j2]
            n = max(len(b_slice), len(a_slice))
            for k in range(n):
                paired.append((
                    b_slice[k] if k < len(b_slice) else "",
                    a_slice[k] if k < len(a_slice) else "",
                ))
    return paired


def _extract_raw_protected_spans(pf_module: Any, text: str) -> list[dict[str, Any]]:
    """Find character offsets for every protected expression category in `text`."""
    spans: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()

    def add_span(start: int, end: int, kind: str, matched_text: str) -> None:
        key = (start, end, kind)
        if not matched_text or key in seen:
            return
        seen.add(key)
        spans.append({"start": start, "end": end, "kind": kind, "text": matched_text})

    patterns = getattr(pf_module, "PATTERNS", {}) or {}
    for kind, regex in patterns.items():
        for m in regex.finditer(text):
            add_span(m.start(), m.end(), str(kind), m.group(0))

    extract_fn = getattr(pf_module, "extract_protected", None)
    if callable(extract_fn) and text:
        extracted = extract_fn(text) or {}
        for kind, values in extracted.items():
            kind_str = str(kind)
            if kind_str in patterns:
                continue
            if isinstance(values, dict):
                tokens = values.keys()
            elif isinstance(values, (list, tuple, set)):
                tokens = values
            else:
                continue
            for raw_tok in sorted({str(t) for t in tokens if t}, key=len, reverse=True):
                for m in re.finditer(re.escape(raw_tok), text):
                    add_span(m.start(), m.end(), kind_str, m.group(0))

    spans.sort(key=lambda item: (item["start"], item["end"], item["kind"]))
    return spans


def _annotate_protected_status(
    before_raw: list[dict[str, Any]],
    after_raw: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Label each protected span occurrence as kept, removed, or added."""
    b_counts = Counter((s["kind"], s["text"]) for s in before_raw)
    a_counts = Counter((s["kind"], s["text"]) for s in after_raw)
    kept_quota = {k: min(b_counts[k], a_counts[k]) for k in set(b_counts) | set(a_counts)}

    b_seen: Counter[tuple[str, str]] = Counter()
    before_out: list[dict[str, Any]] = []
    for item in before_raw:
        k = (item["kind"], item["text"])
        b_seen[k] += 1
        status = "kept" if b_seen[k] <= kept_quota.get(k, 0) else "removed"
        before_out.append({**item, "status": status})

    a_seen: Counter[tuple[str, str]] = Counter()
    after_out: list[dict[str, Any]] = []
    for item in after_raw:
        k = (item["kind"], item["text"])
        a_seen[k] += 1
        status = "kept" if a_seen[k] <= kept_quota.get(k, 0) else "added"
        after_out.append({**item, "status": status})

    return before_out, after_out


def _preedit_argv_for(op: dict[str, Any], src: Path, dst: Path, tmp_dir: Path, idx: int) -> list[str]:
    """Build `preedit.py` subcommand argv for one normalised OperationPlan step."""
    del tmp_dir, idx  # retained in signature; rt_apply._argv_for builds direct args
    kind = str(op.get("kind") or "")
    params = op.get("params") if isinstance(op.get("params"), dict) else op
    try:
        return _apply_argv_for(kind, params, src, dst)
    except RpcError as exc:
        raise BridgeError("unsupported_op", exc.message, data=exc.data) from exc
    except KeyError as exc:
        raise BridgeError("invalid_params", f"{kind} op missing required field {exc}") from exc


class SSEHub:
    """Thread-safe fanout hub for Server-Sent Event streams."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[queue.Queue[tuple[str, Any] | None]] = set()

    def subscribe(self) -> queue.Queue[tuple[str, Any] | None]:
        q: queue.Queue[tuple[str, Any] | None] = queue.Queue(maxsize=256)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[tuple[str, Any] | None]) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, event_name: str, payload: Any) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait((event_name, payload))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait((event_name, payload))
                except (queue.Empty, queue.Full):
                    pass

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(None)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(None)
                except (queue.Empty, queue.Full):
                    pass


class HostSidecarManager:
    """Owns the single Host-authority `serve.py --entry host` child process."""

    def __init__(self, sse: SSEHub, engine_root: Path | None) -> None:
        self._sse = sse
        self._engine_root = engine_root
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._root: Path | None = None
        self._initialized = False
        self._handshake: dict[str, Any] | None = None
        self._last_exit: int | None = None
        self._last_failure: str | None = None
        self._next_id = 1
        self._activity_seq = 0
        self._waiters: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._inflight_tags: dict[str, str] = {}
        self._write_lock = threading.Lock()

    def _emit_activity(self, kind: str, text: str, frame: Any = None) -> None:
        with self._lock:
            self._activity_seq += 1
            seq = self._activity_seq
        self._sse.publish(
            "runtime://activity",
            [{"seq": seq, "atMs": _now_ms(), "kind": kind, "text": text, "frame": frame}],
        )

    def _status_unlocked(self) -> dict[str, Any]:
        proc = self._proc
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "root": str(self._root) if self._root else None,
            "pid": proc.pid if running and proc else None,
            "mode": "interpreter",
            "jobConfined": None,
            "jobError": None,
            "exitCode": self._last_exit,
            "lastExit": self._last_exit,
            "failure": self._last_failure,
            "initialized": self._initialized if running else False,
            "protocolVersion": PROTOCOL_VERSION,
            "implVersion": IMPL_VERSION,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def active_root(self) -> Path | None:
        with self._lock:
            return self._root

    def start(self, root: Path) -> dict[str, Any]:
        target_root = Path(root).expanduser().resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            proc = self._proc
            running = proc is not None and proc.poll() is None
            if running and self._root == target_root and self._initialized and self._handshake:
                return {"handshake": self._handshake, "status": self._status_unlocked()}
        if running:
            self.stop()

        argv = [sys.executable, str(SERVE_SCRIPT), "--entry", "host", "--root", str(target_root)]
        if self._engine_root is not None:
            argv += ["--engine-root", str(self._engine_root)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            with self._lock:
                self._last_failure = f"failed to spawn serve.py: {exc}"
            self._sse.publish("runtime://status", self.status())
            raise BridgeError("sidecar_spawn_failed", str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)

        with self._lock:
            self._proc = proc
            self._root = target_root
            self._initialized = False
            self._handshake = None
            self._last_exit = None
            self._last_failure = None

        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()
        self._emit_activity("lifecycle", f"started host sidecar (pid={proc.pid}, root={target_root})")

        try:
            ok, payload = self.rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "client": {"name": "rigorloom-ui", "version": IMPL_VERSION},
                    "unknownFieldPolicy": "reject",
                },
                timeout=30.0,
            )
            if not ok:
                raise BridgeError(
                    str(payload.get("code", "initialize_failed")),
                    str(payload.get("message", "sidecar initialize failed")),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    data=payload.get("data"),
                )
        except Exception:
            self.stop()
            raise

        with self._lock:
            self._initialized = True
            self._handshake = payload
            status = self._status_unlocked()
        self._sse.publish("runtime://status", status)
        return {"handshake": payload, "status": status}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._initialized = False
            self._handshake = None
        if proc is not None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
            with self._lock:
                self._last_exit = proc.returncode
        self._fail_all_waiters("sidecar_stopped", "Runtime sidecar stopped")
        self._emit_activity("lifecycle", "stopped host sidecar")
        self._sse.publish("runtime://status", self.status())
        return {"stopped": True}

    def _fail_all_waiters(self, code: str, message: str) -> None:
        with self._lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
            self._inflight_tags.clear()
        for ev, slot in waiters:
            slot["ok"] = False
            slot["payload"] = {"code": code, "message": message}
            ev.set()

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        stdout = proc.stdout
        if stdout is None:
            return
        try:
            for raw_line in stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    self._emit_activity("log", f"non-JSON stdout from serve.py: {line}")
                    continue
                if not isinstance(frame, dict):
                    continue
                kind = frame.get("kind")
                if kind in ("response", "error"):
                    req_id = str(frame.get("id", ""))
                    with self._lock:
                        waiter = self._waiters.pop(req_id, None)
                    if waiter is not None:
                        ev, slot = waiter
                        slot["ok"] = kind == "response"
                        slot["payload"] = (
                            frame.get("result") if kind == "response" else frame.get("error", {})
                        )
                        ev.set()
                elif kind == "notification" and frame.get("method") == "event":
                    params = frame.get("params")
                    if isinstance(params, dict):
                        self._sse.publish("runtime://events", [params])
                else:
                    self._emit_activity("frame", f"notification {frame.get('method', kind)}", frame)
        finally:
            code = proc.poll()
            if code is None:
                try:
                    code = proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    code = None
            with self._lock:
                is_current = self._proc is proc
                if is_current:
                    self._proc = None
                    self._initialized = False
                    self._last_exit = code
                    if code not in (None, 0):
                        self._last_failure = f"serve.py exited with code {code}"
            if is_current:
                self._fail_all_waiters("sidecar_exited", f"serve.py exited (code={code})")
                self._sse.publish("runtime://status", self.status())

    def _read_stderr(self, proc: subprocess.Popen[str]) -> None:
        stderr = proc.stderr
        if stderr is None:
            return
        for raw_line in stderr:
            line = raw_line.rstrip("\r\n")
            if line:
                self._emit_activity("log", line)

    def rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        tag: str | None = None,
        timeout: float = 120.0,
    ) -> tuple[bool, Any]:
        if not isinstance(method, str) or not method:
            raise BridgeError("invalid_params", "method must be a non-empty string")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise BridgeError("invalid_params", "params must be an object or null")

        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                return False, {
                    "code": "sidecar_not_running",
                    "message": "Runtime sidecar is not running; call /api/runtime/start first",
                }
            req_id = f"ui-{self._next_id}"
            self._next_id += 1
            ev = threading.Event()
            slot: dict[str, Any] = {}
            self._waiters[req_id] = (ev, slot)
            if tag:
                self._inflight_tags[tag] = req_id

        frame = {"kind": "request", "id": req_id, "method": method, "params": params}
        encoded = json.dumps(frame, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(encoded)
                proc.stdin.flush()
        except OSError as exc:
            with self._lock:
                self._waiters.pop(req_id, None)
                if tag and self._inflight_tags.get(tag) == req_id:
                    self._inflight_tags.pop(tag, None)
            return False, {"code": "sidecar_io_error", "message": str(exc)}

        try:
            finished = ev.wait(timeout=timeout)
            if not finished:
                return False, {
                    "code": "rpc_timeout",
                    "message": f"RPC {method} timed out after {timeout}s",
                }
            return bool(slot.get("ok")), slot.get("payload")
        finally:
            with self._lock:
                self._waiters.pop(req_id, None)
                if tag and self._inflight_tags.get(tag) == req_id:
                    self._inflight_tags.pop(tag, None)

    def cancel(self, tag: str) -> bool:
        if not isinstance(tag, str) or not tag:
            return False
        with self._lock:
            req_id = self._inflight_tags.get(tag)
            proc = self._proc
        if req_id is None or proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        frame = json.dumps({"kind": "cancel", "id": req_id}, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(frame)
                proc.stdin.flush()
            return True
        except OSError:
            return False


class BridgeApplication:
    """State and business logic behind HTTP/SSE routes."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        engine_root: Path | None = None,
        token: str | None = None,
        explicit_root: bool = False,
        prefs_path: Path | None = None,
    ) -> None:
        self.default_root = (
            Path(root).expanduser().resolve()
            if root is not None
            else default_runtime_root().expanduser().resolve()
        )
        self.explicit_root = explicit_root
        self.engine_root = Path(engine_root).expanduser().resolve() if engine_root else None
        self.repo_root = _discover_repo_root(self.engine_root)
        if self.engine_root is None and self.repo_root is not None:
            self.engine_root = self.repo_root
        self.token = token or secrets.token_urlsafe(32)
        self.sse = SSEHub()
        self.sidecar = HostSidecarManager(self.sse, self.engine_root)
        self._prefs_lock = threading.Lock()
        self._prefs_path = (
            Path(prefs_path).expanduser().resolve()
            if prefs_path is not None
            else (default_runtime_root().parent / "ui-prefs.json").resolve()
        )
        self._root_pinned_in_session = False
        self._cred_lock = threading.Lock()
        # Kept strictly in RAM for this server process; never written or returned.
        self._credentials: dict[str, str] = {}
        self._agent_lock = threading.Lock()
        self._agent_proc: subprocess.Popen[str] | None = None
        self._prose_fidelity_mod: Any = None
        self._pipeline_ctl_mod: Any = None

    def current_root(self) -> Path:
        return self.sidecar.active_root() or self.default_root

    def _ui_dist_dir(self) -> Path | None:
        packaged = HERE / "ui_dist"
        if (packaged / "index.html").is_file():
            return packaged
        if self.repo_root is not None:
            fallback = self.repo_root / "desktop" / "dist"
            if (fallback / "index.html").is_file():
                return fallback
        return None

    def render_index_html(self) -> bytes:
        dist_dir = self._ui_dist_dir()
        if dist_dir is not None:
            html = (dist_dir / "index.html").read_text(encoding="utf-8")
        else:
            html = FALLBACK_INDEX_HTML
        injected = _inject_bootstrap(
            html,
            {"token": self.token, "root": str(self.current_root())},
        )
        return injected.encode("utf-8")

    def resolve_static_asset(self, rel_path: str) -> tuple[Path, str] | None:
        clean = rel_path.lstrip("/")
        if clean == "assets/fonts/PretendardVariable.woff2":
            dist_dir = self._ui_dist_dir()
            if dist_dir is not None:
                candidate = (dist_dir / clean).resolve()
                if candidate.is_relative_to(dist_dir.resolve()) and candidate.is_file():
                    return candidate, "font/woff2"
            if self.repo_root is not None:
                checkout_font = (
                    self.repo_root / "desktop" / "src" / "assets" / "fonts" / "PretendardVariable.woff2"
                ).resolve()
                if checkout_font.is_file():
                    return checkout_font, "font/woff2"
            return None

        dist_dir = self._ui_dist_dir()
        if dist_dir is None or not clean or ".." in Path(clean).parts:
            return None
        resolved_dist = dist_dir.resolve()
        target = (resolved_dist / clean).resolve()
        if not target.is_relative_to(resolved_dist) or not target.is_file():
            return None
        suffix = target.suffix.lower()
        ctype = _MIME_OVERRIDES.get(suffix)
        if not ctype:
            guessed, _ = mimetypes.guess_type(str(target))
            ctype = guessed or "application/octet-stream"
        return target, ctype

    # --- Runtime / Prefs / Corpus / Upload -----------------------------------

    def runtime_start(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_root = body.get("root")
        if raw_root is not None:
            if not isinstance(raw_root, str) or not raw_root.strip():
                raise BridgeError("invalid_params", "root must be a non-empty string")
            target = Path(raw_root).expanduser()
        else:
            target = self.current_root()
        return self.sidecar.start(target)

    def get_prefs(self) -> dict[str, Any]:
        with self._prefs_lock:
            data: dict[str, Any] = {}
            if self._prefs_path.is_file():
                try:
                    loaded = json.loads(self._prefs_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except (OSError, json.JSONDecodeError):
                    data = {}
            if self.explicit_root and not self._root_pinned_in_session:
                data["root"] = str(self.default_root)
            return data

    def patch_prefs(self, body: dict[str, Any]) -> dict[str, Any]:
        patch = body.get("patch")
        if not isinstance(patch, dict):
            raise BridgeError("invalid_params", "patch must be an object")
        with self._prefs_lock:
            current: dict[str, Any] = {}
            if self._prefs_path.is_file():
                try:
                    loaded = json.loads(self._prefs_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        current = loaded
                except (OSError, json.JSONDecodeError):
                    current = {}
            for key, value in patch.items():
                if not isinstance(key, str):
                    raise BridgeError("invalid_params", "prefs keys must be strings")
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
                if key == "root":
                    self._root_pinned_in_session = True
            self._prefs_path.parent.mkdir(parents=True, exist_ok=True)
            encoded = (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            atomic_write_bytes(self._prefs_path, encoded)
            return dict(current)

    def list_corpus_files(self) -> dict[str, Any]:
        if self.engine_root is None:
            return {"files": []}
        corpus_dir = self.engine_root / "tests" / "corpus"
        if not corpus_dir.is_dir():
            return {"files": []}
        entries = []
        for path in corpus_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(corpus_dir).parts):
                continue
            if path.suffix.lower() not in (".hwpx", ".hwp"):
                continue
            entries.append({
                "name": path.relative_to(corpus_dir).as_posix(),
                "path": str(path.resolve()),
                "size": path.stat().st_size,
            })
        entries.sort(key=lambda row: row["name"])
        return {"files": entries}

    def open_upload(self, body: dict[str, Any]) -> dict[str, Any]:
        filename = _sanitize_upload_filename(body.get("filename", ""))
        raw_b64 = body.get("bytesBase64")
        if not isinstance(raw_b64, str) or not raw_b64:
            raise BridgeError("invalid_params", "bytesBase64 must be a non-empty base64 string")
        try:
            raw_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BridgeError("invalid_params", f"invalid base64 payload: {exc}") from exc
        if not raw_bytes:
            raise BridgeError("invalid_params", "uploaded file cannot be empty")
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise BridgeError(
                "file_too_large",
                f"upload exceeds maximum {MAX_SOURCE_BYTES} bytes",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        root = self.current_root()
        uploads_dir = (root / "uploads").resolve()
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = (uploads_dir / f"{uuid.uuid4().hex[:12]}-{filename}").resolve()
        if not dest.is_relative_to(uploads_dir):
            raise BridgeError("invalid_filename", "upload path escapes uploads directory")
        atomic_write_bytes(dest, raw_bytes)

        ok, res = self.sidecar.rpc("workspace/openPath", {"path": str(dest)})
        if not ok:
            raise BridgeError(
                str(res.get("code", "open_failed")),
                str(res.get("message", "workspace/openPath failed")),
                data=res.get("data"),
            )
        return res

    # --- Export & Download ----------------------------------------------------

    def _read_verified_receipt(
        self, root: Path, session_id: str, run_id: str
    ) -> tuple[Path, Path, dict[str, Any]]:
        cand_dir = (root / "sessions" / session_id / "candidates" / run_id).resolve()
        receipt_path = cand_dir / "receipt.json"
        if not receipt_path.is_file():
            raise BridgeError("receipt_missing", f"no receipt for {session_id}/{run_id}", status=HTTPStatus.NOT_FOUND)
        ok, res = self.sidecar.rpc("receipt/read", {"sessionId": session_id, "runId": run_id})
        if not ok:
            code = str((res or {}).get("code", "receipt_invalid"))
            msg = str((res or {}).get("message", "receipt verification failed"))
            status = HTTPStatus.SERVICE_UNAVAILABLE if code == "sidecar_not_running" else HTTPStatus.CONFLICT
            raise BridgeError(code, msg, status=status, data=(res or {}).get("data"))
        receipt = res.get("receipt") if isinstance(res, dict) else None
        if not isinstance(receipt, dict):
            raise BridgeError("receipt_invalid", "invalid receipt payload", status=HTTPStatus.CONFLICT)
        return cand_dir, receipt_path, receipt

    def export_candidate(self, body: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_bare_component(body.get("sessionId"), "sessionId")
        run_id = _require_bare_component(body.get("runId"), "runId")
        root = self.current_root()
        cand_dir, receipt_path, receipt = self._read_verified_receipt(root, session_id, run_id)

        cand_meta = receipt.get("candidate") or {}
        rel_artifact = body.get("candidatePath") or cand_meta.get("path") or "artifact.hwpx"
        artifact_path = _resolve_relative_candidate(cand_dir, rel_artifact)
        if not artifact_path.is_file():
            raise BridgeError("candidate_missing", f"candidate artifact missing: {artifact_path}", status=HTTPStatus.NOT_FOUND)

        expected_sha = str(cand_meta.get("sha256") or "")
        expected_bytes = cand_meta.get("bytes")
        actual_sha, actual_bytes = sha256_file(artifact_path)
        if expected_sha and actual_sha != expected_sha:
            raise BridgeError(
                "candidate_hash_mismatch",
                "candidate artifact sha256 does not match verified receipt",
                status=HTTPStatus.CONFLICT,
                data={"expected": expected_sha, "actual": actual_sha},
            )
        if isinstance(expected_bytes, int) and actual_bytes != expected_bytes:
            raise BridgeError(
                "candidate_size_mismatch",
                "candidate artifact byte length does not match receipt",
                status=HTTPStatus.CONFLICT,
                data={"expected": expected_bytes, "actual": actual_bytes},
            )

        raw_dest = body.get("destination")
        if raw_dest is not None and raw_dest != "":
            if not isinstance(raw_dest, str):
                raise BridgeError("invalid_params", "destination must be a string path")
            dest_path = Path(raw_dest).expanduser()
            dest_receipt_path = Path(f"{dest_path}.receipt.json")
            for a, b in (
                (artifact_path, dest_path),
                (artifact_path, dest_receipt_path),
                (receipt_path, dest_path),
                (receipt_path, dest_receipt_path),
                (dest_path, dest_receipt_path),
            ):
                if _paths_alias(a, b):
                    raise BridgeError(
                        "export_alias",
                        "destination or sidecar receipt aliases the candidate source or each other",
                        status=HTTPStatus.CONFLICT,
                    )
            _atomic_copy_durable(receipt_path, dest_receipt_path)
            _atomic_copy_durable(artifact_path, dest_path)
            if sha256_file(dest_path)[0] != actual_sha:
                raise BridgeError(
                    "export_verification_failed",
                    "exported file sha256 drifted after copy",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return {
                "path": str(dest_path.resolve(strict=False)),
                "sha256": actual_sha,
                "bytes": actual_bytes,
                "receiptPath": str(dest_receipt_path.resolve(strict=False)),
                "downloadUrl": None,
            }

        exports_dir = (root / "exports").resolve()
        exports_dir.mkdir(parents=True, exist_ok=True)
        staged_name = f"{session_id}-{run_id}{artifact_path.suffix or '.hwpx'}"
        staged_path = exports_dir / staged_name
        staged_receipt = exports_dir / f"{staged_name}.receipt.json"
        _atomic_copy_durable(receipt_path, staged_receipt)
        _atomic_copy_durable(artifact_path, staged_path)
        if sha256_file(staged_path)[0] != actual_sha:
            raise BridgeError(
                "export_verification_failed",
                "staged export sha256 drifted after copy",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return {
            "path": str(staged_path),
            "sha256": actual_sha,
            "bytes": actual_bytes,
            "receiptPath": str(staged_receipt),
            "downloadUrl": f"/api/export-download?token={quote(self.token, safe='')}&name={quote(staged_name, safe='')}",
        }

    def resolve_export_download(self, name: str) -> Path:
        if not name or not VALID_UPLOAD_NAME_RE.match(name) or ".." in name:
            raise BridgeError("invalid_params", "invalid export download filename")
        exports_dir = (self.current_root() / "exports").resolve()
        target = (exports_dir / name).resolve()
        if not target.is_relative_to(exports_dir) or not target.is_file():
            raise BridgeError("not_found", f"staged export not found: {name}", status=HTTPStatus.NOT_FOUND)
        return target

    # --- Credentials (in-memory only) ----------------------------------------

    def _validate_cred_key(self, body: dict[str, Any]) -> str:
        key = body.get("key")
        if not isinstance(key, str) or not VALID_CREDENTIAL_KEY_RE.match(key):
            raise BridgeError("invalid_key", "credential key must match ^[A-Za-z0-9_.-]{1,128}$")
        return key

    def credential_status(self, body: dict[str, Any]) -> dict[str, Any]:
        key = self._validate_cred_key(body)
        with self._cred_lock:
            present = bool(self._credentials.get(key))
        return {"key": key, "present": present}

    def credential_set(self, body: dict[str, Any]) -> dict[str, Any]:
        key = self._validate_cred_key(body)
        secret = body.get("secret")
        if not isinstance(secret, str) or not secret:
            raise BridgeError("invalid_params", "secret must be a non-empty string")
        with self._cred_lock:
            self._credentials[key] = secret
        return {"key": key, "present": True}

    def credential_delete(self, body: dict[str, Any]) -> dict[str, Any]:
        key = self._validate_cred_key(body)
        with self._cred_lock:
            self._credentials.pop(key, None)
        return {"key": key, "present": False}

    # --- Mock Agent & Agent Host ---------------------------------------------

    def agent_tool_status(self) -> dict[str, Any]:
        root = self.current_root()
        if not MOCK_AGENT_SCRIPT.is_file():
            return {"available": False, "root": str(root), "script": None, "reason": "mock_agent.py not found"}
        if not root.is_dir():
            return {
                "available": False,
                "root": str(root),
                "script": str(MOCK_AGENT_SCRIPT),
                "reason": f"runtime root does not exist yet: {root}",
            }
        return {"available": True, "root": str(root), "script": str(MOCK_AGENT_SCRIPT), "reason": None}

    def run_mock_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        if not MOCK_AGENT_SCRIPT.is_file():
            raise BridgeError("tool_unavailable", "mock_agent.py is unavailable", status=HTTPStatus.SERVICE_UNAVAILABLE)
        root = self.current_root()
        root.mkdir(parents=True, exist_ok=True)
        marker = body.get("marker") or "MOCK-AGENT-0001"
        scenario = body.get("scenario") or "propose-one"
        door = body.get("door") or "protocol"
        if not isinstance(marker, str) or not marker:
            raise BridgeError("invalid_params", "marker must be a non-empty string")
        argv = [
            sys.executable,
            str(MOCK_AGENT_SCRIPT),
            "--root", str(root),
            "--scenario", str(scenario),
            "--door", str(door),
            "--marker", marker,
        ]
        if body.get("sessionId"):
            argv += ["--session", _require_bare_component(body["sessionId"], "sessionId")]
        if self.engine_root is not None:
            argv += ["--engine-root", str(self.engine_root)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        try:
            payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        except json.JSONDecodeError as exc:
            raise BridgeError(
                "mock_agent_invalid_output",
                f"mock_agent produced invalid JSON: {exc}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                data={"stderr": proc.stderr[-1000:]},
            ) from exc
        if not isinstance(payload, dict):
            raise BridgeError(
                "mock_agent_failed",
                f"mock_agent exited {proc.returncode} with no JSON output",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                data={"stderr": proc.stderr[-1000:]},
            )
        return payload

    def _host_script(self) -> Path | None:
        if self.repo_root is None:
            return None
        candidate = self.repo_root / "agenthost" / "scripts" / "host.py"
        return candidate if candidate.is_file() else None

    def _agenthost_config_dir(self) -> Path:
        return self._prefs_path.parent / "agenthost"

    def _agenthost_config_path(self, provider: str) -> tuple[Path, str]:
        if provider not in ("anthropic", "router"):
            raise BridgeError("invalid_params", f"config is only supported for anthropic or router, got {provider!r}")
        store_key = f"rigorloom.agenthost.{provider}"
        return self._agenthost_config_dir() / f"{provider}.json", store_key

    def agent_host_status(self) -> dict[str, Any]:
        script = self._host_script()
        with self._agent_lock:
            running = self._agent_proc is not None and self._agent_proc.poll() is None
        return {
            "available": script is not None,
            "running": running,
            "root": str(self.current_root()),
            "providers": list(AGENTHOST_PROVIDERS),
            "script": str(script) if script else None,
            "reason": None if script else "agenthost/scripts/host.py not available in this installation",
        }

    def agent_host_save_config(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = body.get("provider")
        cfg_path, store_key = self._agenthost_config_path(str(provider or ""))
        settings = _validate_agenthost_settings(str(provider), body.get("settings"))
        has_credential = bool(body.get("hasCredential"))
        if has_credential and "credential" not in settings:
            settings["credential"] = {
                "source": "env",
                "key": "RIGORLOOM_PROVIDER_CREDENTIAL",
            }
        elif not has_credential and "credential" not in settings:
            settings["credential"] = {"source": "none"}
        payload = {"schema": "rigorloom-router-config/v1", **settings}
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            cfg_path,
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return {"configPath": str(cfg_path), "storeKey": store_key, "saved": True}

    def agent_host_read_config(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = body.get("provider")
        cfg_path, store_key = self._agenthost_config_path(str(provider or ""))
        if not cfg_path.is_file():
            return {"exists": False, "configPath": str(cfg_path), "storeKey": store_key, "settings": {}}
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeError("config_invalid", f"failed to read agenthost config: {exc}") from exc
        if not isinstance(loaded, dict):
            raise BridgeError("config_invalid", "saved config is not a JSON object")
        loaded.pop("schema", None)
        return {"exists": True, "configPath": str(cfg_path), "storeKey": store_key, "settings": loaded}

    def _agenthost_child_env(self, provider: str, store_key: str | None, cfg_path: Path | None) -> dict[str, str]:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        lookup_key = store_key or f"rigorloom.agenthost.{provider}"
        with self._cred_lock:
            secret = self._credentials.get(lookup_key)
        if not secret:
            return env
        cred_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "RIGORLOOM_PROVIDER_CREDENTIAL"
        if cfg_path is not None and cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cred_spec = cfg.get("credential")
                if isinstance(cred_spec, dict) and cred_spec.get("source") == "env" and cred_spec.get("key"):
                    cred_var = str(cred_spec["key"])
            except (OSError, json.JSONDecodeError):
                pass
        env[cred_var] = secret
        if cred_var != "RIGORLOOM_PROVIDER_CREDENTIAL":
            env["RIGORLOOM_PROVIDER_CREDENTIAL"] = secret
        return env

    def agent_host_capabilities(self, body: dict[str, Any]) -> dict[str, Any]:
        script = self._host_script()
        if script is None:
            raise BridgeError("tool_unavailable", "agenthost/scripts/host.py is unavailable", status=HTTPStatus.SERVICE_UNAVAILABLE)
        provider = str(body.get("provider") or "mock")
        if provider not in AGENTHOST_PROVIDERS:
            raise BridgeError("invalid_params", f"unsupported provider {provider!r}")
        argv = [sys.executable, str(script), "--capabilities", "--provider", provider]
        cfg_path = None
        if provider in ("anthropic", "router"):
            cand_cfg, default_key = self._agenthost_config_path(provider)
            if cand_cfg.is_file():
                cfg_path = cand_cfg
                argv += ["--config", str(cand_cfg)]
            store_key = body.get("storeKey") or default_key
        else:
            store_key = body.get("storeKey")
        env = self._agenthost_child_env(provider, store_key, cfg_path)
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        try:
            payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        except json.JSONDecodeError as exc:
            raise BridgeError("agenthost_invalid_output", str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR) from exc
        if not isinstance(payload, dict):
            raise BridgeError(
                "agenthost_failed",
                f"host.py --capabilities exited {proc.returncode}",
                status=HTTPStatus.BAD_REQUEST if proc.returncode == 2 else HTTPStatus.INTERNAL_SERVER_ERROR,
                data={"stderr": proc.stderr[-1000:]},
            )
        return payload

    def agent_host_run(self, body: dict[str, Any]) -> dict[str, Any]:
        script = self._host_script()
        if script is None:
            raise BridgeError("tool_unavailable", "agenthost/scripts/host.py is unavailable", status=HTTPStatus.SERVICE_UNAVAILABLE)
        provider = str(body.get("provider") or "mock")
        if provider not in AGENTHOST_PROVIDERS:
            raise BridgeError("invalid_params", f"unsupported provider {provider!r}")
        turn_id = str(body.get("turnId") or uuid.uuid4().hex[:12])
        root = self.current_root()
        root.mkdir(parents=True, exist_ok=True)
        cfg_path = None
        if provider in ("anthropic", "router"):
            cand_cfg, default_key = self._agenthost_config_path(provider)
            if cand_cfg.is_file():
                cfg_path = cand_cfg
            store_key = body.get("storeKey") or default_key
        else:
            store_key = body.get("storeKey")

        with tempfile.TemporaryDirectory(prefix="rigorloom-ah-") as tmp_str:
            events_path = Path(tmp_str) / "events.jsonl"
            argv = [
                sys.executable,
                str(script),
                "--root", str(root),
                "--provider", provider,
                "--door", "protocol",
                "--events", str(events_path),
            ]
            if body.get("sessionId"):
                argv += ["--session", _require_bare_component(body["sessionId"], "sessionId")]
            if body.get("instruction"):
                argv += ["--instruction", str(body["instruction"])]
            if provider == "mock" and body.get("scenario"):
                argv += ["--scenario", str(body["scenario"])]
            if cfg_path is not None:
                argv += ["--config", str(cfg_path)]
            if self.engine_root is not None:
                argv += ["--engine-root", str(self.engine_root)]
            env = self._agenthost_child_env(provider, store_key, cfg_path)

            with self._agent_lock:
                if self._agent_proc is not None and self._agent_proc.poll() is None:
                    raise BridgeError("agenthost_busy", "an agent-host run is already in progress", status=HTTPStatus.CONFLICT)
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env=env,
                )
                self._agent_proc = proc

            stop_tail = threading.Event()
            tail_thread = threading.Thread(
                target=self._tail_agenthost_events,
                args=(events_path, turn_id, stop_tail),
                daemon=True,
            )
            tail_thread.start()
            try:
                stdout_text, stderr_text = proc.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_text, stderr_text = proc.communicate()
                raise BridgeError("agenthost_timeout", "agent-host run timed out", status=HTTPStatus.GATEWAY_TIMEOUT)
            finally:
                stop_tail.set()
                tail_thread.join(timeout=1.0)
                with self._agent_lock:
                    if self._agent_proc is proc:
                        self._agent_proc = None

        try:
            payload = json.loads(stdout_text) if stdout_text.strip() else None
        except json.JSONDecodeError as exc:
            raise BridgeError("agenthost_invalid_output", str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR) from exc
        if not isinstance(payload, dict):
            raise BridgeError(
                "agenthost_failed",
                f"agenthost exited {proc.returncode}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                data={"stderr": stderr_text[-1000:]},
            )
        return payload

    def _tail_agenthost_events(self, events_path: Path, turn_id: str, stop_event: threading.Event) -> None:
        offset = 0
        while not stop_event.is_set():
            offset = self._flush_agenthost_events(events_path, turn_id, offset)
            stop_event.wait(timeout=0.1)
        self._flush_agenthost_events(events_path, turn_id, offset)

    def _flush_agenthost_events(self, events_path: Path, turn_id: str, offset: int) -> int:
        if not events_path.is_file():
            return offset
        try:
            with events_path.open("r", encoding="utf-8") as fh:
                fh.seek(offset)
                chunk = fh.read()
                new_offset = fh.tell()
        except OSError:
            return offset
        if not chunk:
            return new_offset
        batch: list[dict[str, Any]] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            batch.append({"turnId": turn_id, "event": ev})
        if batch:
            self.sse.publish("agenthost://events", batch)
        return new_offset

    def agent_host_stop(self) -> dict[str, Any]:
        with self._agent_lock:
            proc = self._agent_proc
        if proc is None or proc.poll() is not None:
            return {"stopped": False}
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
        return {"stopped": True}

    # --- Task Packs -----------------------------------------------------------

    def list_task_packs(self) -> dict[str, Any]:
        if self.repo_root is None:
            return {
                "available": False,
                "reason": "pipeline/scripts/module_registry.py not present (repo checkout required)",
                "modules": [],
            }
        reg_script = self.repo_root / "pipeline" / "scripts" / "module_registry.py"
        if not reg_script.is_file():
            return {
                "available": False,
                "reason": f"module registry script missing: {reg_script}",
                "modules": [],
            }
        argv = [
            sys.executable,
            str(reg_script),
            "--modules-root", str(self.repo_root / "modules"),
            "--pyproject", str(self.repo_root / "pyproject.toml"),
            "list",
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        try:
            raw = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError as exc:
            return {
                "available": False,
                "reason": f"module_registry invalid JSON: {exc}",
                "modules": [],
            }
        raw_mods = raw.get("modules") or {}
        if isinstance(raw_mods, dict):
            mod_list = [
                {"name": name, **(info if isinstance(info, dict) else {})}
                for name, info in sorted(raw_mods.items())
            ]
        elif isinstance(raw_mods, list):
            mod_list = raw_mods
        else:
            mod_list = []
        return {
            "available": True,
            "reason": None if raw.get("ok") else raw.get("error"),
            "schema": raw.get("schema"),
            "registryOk": bool(raw.get("ok")),
            "error": raw.get("error"),
            "enabledFile": raw.get("enabled_file") or raw.get("enabledFile"),
            "enabled": raw.get("enabled") or [],
            "modules": mod_list,
        }

    # --- Guard Diff -----------------------------------------------------------

    def _get_prose_fidelity(self) -> Any:
        if self._prose_fidelity_mod is not None:
            return self._prose_fidelity_mod
        search_roots = [r for r in (self.repo_root, self.engine_root) if r is not None]
        for root in search_roots:
            pf_path = root / "modules" / "style" / "scripts" / "prose_fidelity.py"
            if pf_path.is_file():
                self._prose_fidelity_mod = _load_python_module("rigorloom_prose_fidelity", pf_path)
                return self._prose_fidelity_mod
        raise BridgeError(
            "guard_unavailable",
            "modules/style/scripts/prose_fidelity.py not found in this installation",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _session_source_hwpx(self, root: Path, session_id: str) -> Path:
        session_dir = root / "sessions" / session_id
        if not session_dir.is_dir():
            raise BridgeError("session_not_found", f"unknown session {session_id}", status=HTTPStatus.NOT_FOUND)
        source_dir = session_dir / "source"
        if source_dir.is_dir():
            files = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in (".hwpx", ".hwp"))
            if files:
                return files[0]
        meta_path = session_dir / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            src = meta.get("source") or {}
            for key in ("storedPath", "path"):
                val = src.get(key)
                if val and Path(val).is_file():
                    return Path(val)
        raise BridgeError("source_not_found", f"source HWPX not found for session {session_id}", status=HTTPStatus.NOT_FOUND)

    def _verified_candidate_hwpx(self, root: Path, session_id: str, run_id: str) -> Path:
        cand_dir, _, receipt = self._read_verified_receipt(root, session_id, run_id)
        rel = (receipt.get("candidate") or {}).get("path") or "artifact.hwpx"
        artifact = _resolve_relative_candidate(cand_dir, rel)
        if not artifact.is_file():
            raise BridgeError("candidate_not_found", f"missing candidate artifact {artifact}", status=HTTPStatus.NOT_FOUND)
        expected_sha = (receipt.get("candidate") or {}).get("sha256")
        if expected_sha and sha256_file(artifact)[0] != expected_sha:
            raise BridgeError("candidate_hash_mismatch", "candidate artifact sha256 mismatch", status=HTTPStatus.CONFLICT)
        return artifact

    def _load_plan_record(self, root: Path, session_id: str, plan_id: str) -> dict[str, Any]:
        plan_file = root / "sessions" / session_id / "plans" / f"{plan_id}.json"
        if plan_file.is_file():
            return json.loads(plan_file.read_text(encoding="utf-8"))
        ok, res = self.sidecar.rpc("plan/get", {"planId": plan_id})
        if ok and isinstance(res, dict) and isinstance(res.get("plan"), dict):
            plan = res["plan"]
            if plan.get("sessionId") == session_id:
                return plan
        raise BridgeError("plan_not_found", f"plan {plan_id} not found in session {session_id}", status=HTTPStatus.NOT_FOUND)

    def _preview_plan_paragraphs(
        self,
        base_hwpx: Path,
        plan: dict[str, Any],
    ) -> list[str]:
        ops = plan.get("ops") or []
        if not isinstance(ops, list) or not ops:
            return _extract_hwpx_paragraphs(base_hwpx)
        search_roots = [r for r in (self.engine_root, self.repo_root) if r is not None]
        preedit_script = next(
            (r / "engine" / "scripts" / "preedit.py" for r in search_roots
             if (r / "engine" / "scripts" / "preedit.py").is_file()),
            None,
        )
        if preedit_script is None:
            raise BridgeError(
                "guard_preview_unavailable",
                "engine/scripts/preedit.py not found in this installation",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        with tempfile.TemporaryDirectory(prefix="rigorloom-guard-preview-") as td:
            tmp_dir = Path(td)
            current = tmp_dir / "step-0.hwpx"
            shutil.copyfile(base_hwpx, current)
            for idx, op in enumerate(ops, start=1):
                next_out = tmp_dir / f"step-{idx}.hwpx"
                argv = _preedit_argv_for(op, current, next_out, tmp_dir, idx)
                proc = subprocess.run(
                    [sys.executable, str(preedit_script), *argv],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    timeout=60,
                )
                if proc.returncode != 0 or not next_out.is_file():
                    raise BridgeError(
                        "guard_preview_failed",
                        f"preedit preview failed at op {idx} (exit {proc.returncode})",
                        status=HTTPStatus.UNPROCESSABLE_ENTITY,
                        data={"step": idx, "stderr": proc.stderr[-1000:], "stdout": proc.stdout[-1000:]},
                    )
                current = next_out
            return _extract_hwpx_paragraphs(current)

    def guard_diff(self, body: dict[str, Any]) -> dict[str, Any]:
        rt_guard = _try_import_rt_guard()
        if rt_guard is not None and callable(getattr(rt_guard, "guard_diff", None)):
            return rt_guard.guard_diff(body, root=self.current_root(), engine_root=self.engine_root)

        before_text = body.get("beforeText")
        after_text = body.get("afterText")
        if before_text is not None or after_text is not None:
            if not isinstance(before_text, str) or not isinstance(after_text, str):
                raise BridgeError("invalid_params", "beforeText and afterText must both be strings")
            before_label = "text:before"
            after_label = "text:after"
            before_paras = before_text.splitlines() if before_text else [""]
            after_paras = after_text.splitlines() if after_text else [""]
        else:
            raw_session = body.get("sessionId")
            if not raw_session:
                raise BridgeError(
                    "invalid_params",
                    "provide beforeText+afterText or sessionId with runId/planId",
                )
            session_id = _require_bare_component(raw_session, "sessionId")
            root = self.current_root()

            plan_record = None
            if body.get("planId"):
                plan_id = _require_bare_component(body["planId"], "planId")
                plan_record = self._load_plan_record(root, session_id, plan_id)

            if body.get("againstRunId"):
                against_id = _require_bare_component(body["againstRunId"], "againstRunId")
                before_hwpx = self._verified_candidate_hwpx(root, session_id, against_id)
                before_label = f"run:{against_id}"
            elif plan_record and isinstance(plan_record.get("base"), dict) and plan_record["base"].get("runId"):
                base_run = _require_bare_component(plan_record["base"]["runId"], "base.runId")
                before_hwpx = self._verified_candidate_hwpx(root, session_id, base_run)
                before_label = f"run:{base_run}"
            else:
                before_hwpx = self._session_source_hwpx(root, session_id)
                before_label = "source"

            before_paras = _extract_hwpx_paragraphs(before_hwpx)

            if body.get("runId"):
                run_id = _require_bare_component(body["runId"], "runId")
                after_hwpx = self._verified_candidate_hwpx(root, session_id, run_id)
                after_label = f"run:{run_id}"
                after_paras = _extract_hwpx_paragraphs(after_hwpx)
            elif plan_record is not None:
                after_label = f"plan:{plan_record['planId']}"
                after_paras = self._preview_plan_paragraphs(before_hwpx, plan_record)
            else:
                after_label = before_label
                after_paras = list(before_paras)

        pf = self._get_prose_fidelity()
        paired = _pair_paragraphs(before_paras, after_paras)
        all_rows: list[dict[str, Any]] = []
        changed_rows: list[dict[str, Any]] = []

        for idx, (b_para, a_para) in enumerate(paired, start=1):
            edited = b_para != a_para
            b_spans_raw = _extract_raw_protected_spans(pf, b_para)
            a_spans_raw = _extract_raw_protected_spans(pf, a_para)
            b_prot, a_prot = _annotate_protected_status(b_spans_raw, a_spans_raw)
            if edited:
                audit = pf.audit_text(b_para, a_para)
                changes = list(audit.get("changes") or [])
                para_pass = bool(audit.get("pass", True))
                kinds = sorted({str(c.get("kind")) for c in changes if isinstance(c, dict) and c.get("kind")})
            else:
                changes = []
                para_pass = True
                kinds = []
            row = {
                "paragraph": idx,
                "pass": para_pass,
                "edited": edited,
                "kinds": kinds,
                "changes": changes,
                "before": b_para,
                "after": a_para,
                "beforeProtected": b_prot,
                "afterProtected": a_prot,
            }
            all_rows.append(row)
            if edited:
                changed_rows.append(row)

        overall_audit = pf.audit_text("\n".join(b for b, _ in paired), "\n".join(a for _, a in paired))
        overall_pass = all(r["pass"] for r in changed_rows) and bool(overall_audit.get("pass", True))
        if not changed_rows:
            reason = "no text changes detected"
        elif overall_pass:
            reason = f"all protected expressions preserved across {len(changed_rows)} edited paragraph(s)"
        else:
            failed = [
                f"p{r['paragraph']}({','.join(r['kinds']) or 'drift'})"
                for r in changed_rows if not r["pass"]
            ]
            reason = "protected expression drift in " + (", ".join(failed) or "document")

        return {
            "schema": "rigorloom/guard-v1",
            "before": before_label,
            "after": after_label,
            "paragraphs": len(all_rows),
            "pass": overall_pass,
            "reason": reason,
            "edited": len(changed_rows),
            "changed": changed_rows,
            "allParagraphs": all_rows,
        }

    # --- Pipeline Gates -------------------------------------------------------

    def _get_pipeline_ctl(self) -> tuple[Path, Any]:
        search_roots = [r for r in (self.repo_root, self.engine_root) if r is not None]
        for root in search_roots:
            script = root / "modules" / "report" / "scripts" / "pipeline_ctl.py"
            if script.is_file():
                if self._pipeline_ctl_mod is None:
                    self._pipeline_ctl_mod = _load_python_module("rigorloom_pipeline_ctl", script)
                return script, self._pipeline_ctl_mod
        raise BridgeError(
            "pipeline_unavailable",
            "modules/report/scripts/pipeline_ctl.py not found in this installation",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _validate_workspace(self, raw_ws: Any) -> Path:
        if not isinstance(raw_ws, str) or not raw_ws.strip():
            raise BridgeError("invalid_params", "workspace must be a non-empty directory path")
        ws = Path(raw_ws).expanduser().resolve()
        if not ws.is_dir():
            raise BridgeError("workspace_not_found", f"workspace directory does not exist: {ws}", status=HTTPStatus.NOT_FOUND)
        if not (ws / "PIPELINE.md").is_file():
            raise BridgeError("pipeline_missing", f"PIPELINE.md missing in workspace: {ws}", status=HTTPStatus.NOT_FOUND)
        return ws

    def pipeline_gates(self, raw_ws: str) -> dict[str, Any]:
        ws = self._validate_workspace(raw_ws)
        _, pctl = self._get_pipeline_ctl()
        loaded = pctl.load_header(ws)
        if loaded is None:
            raise BridgeError("pipeline_invalid", "PIPELINE.md lacks a valid v0.4 header")
        _, _, _, hdr = loaded
        try:
            graph_ctx = pctl.graph_context_for_header(hdr)
        except Exception as exc:
            raise BridgeError("pipeline_invalid", f"invalid pipeline graph: {exc}") from exc

        stages = hdr.get("stages") or {}
        next_stage = None
        gates: list[dict[str, Any]] = []
        for stage_id in graph_ctx["order"]:
            st = stages.get(stage_id)
            if not isinstance(st, dict):
                continue
            status = st.get("status", "pending")
            if next_stage is None and status in ("pending", "in_progress", "awaiting_gate"):
                next_stage = stage_id
            gate = st.get("gate")
            if not isinstance(gate, dict) or not gate.get("name"):
                continue
            gate_name = str(gate["name"])
            try:
                gtype = pctl._gate_type_for(stage_id, gate_name, graph_ctx)
            except Exception as exc:
                raise BridgeError("pipeline_invalid", f"gate lookup failed: {exc}") from exc
            gates.append({
                "stage": stage_id,
                "stageStatus": status,
                "gate": gate_name,
                "type": gtype,
                "state": gate.get("state", "pending"),
                "by": gate.get("by"),
                "at": gate.get("at"),
                "resolvable": gtype == "human",
            })

        return {
            "workspace": str(ws),
            "mode": hdr.get("mode", "autonomous"),
            "graph": graph_ctx["name"],
            "nextStage": next_stage,
            "gates": gates,
        }

    def pipeline_gate_resolve(self, body: dict[str, Any]) -> dict[str, Any]:
        ws = self._validate_workspace(body.get("workspace"))
        gate = body.get("gate")
        if not isinstance(gate, str) or not ALLOWED_GATE_RE.match(gate):
            raise BridgeError("invalid_params", "gate must match ^[A-Za-z0-9_.-]+$")
        decision = body.get("decision")
        if decision not in ("approved", "rejected"):
            raise BridgeError("invalid_params", "decision must be 'approved' or 'rejected'")

        script, pctl = self._get_pipeline_ctl()
        loaded = pctl.load_header(ws)
        if loaded is None:
            raise BridgeError("pipeline_invalid", "PIPELINE.md lacks a valid v0.4 header")
        _, _, _, hdr = loaded
        try:
            graph_ctx = pctl.graph_context_for_header(hdr)
        except Exception as exc:
            raise BridgeError("pipeline_invalid", f"invalid pipeline graph: {exc}") from exc

        stages = hdr.get("stages") or {}
        matched_stage = None
        for stage_id in graph_ctx["order"]:
            st = stages.get(stage_id) or {}
            g = st.get("gate") or {}
            if g.get("name") == gate:
                matched_stage = stage_id
                break
        if matched_stage is None:
            raise BridgeError("gate_not_found", f"gate {gate!r} is not present in workspace PIPELINE.md", status=HTTPStatus.NOT_FOUND)
        try:
            gtype = pctl._gate_type_for(matched_stage, gate, graph_ctx)
        except Exception as exc:
            raise BridgeError("pipeline_invalid", f"gate validation failed: {exc}") from exc
        if gtype != "human":
            raise BridgeError(
                "script_gate_not_human",
                f"gate {gate!r} has type {gtype!r}; script gates must run via `check`, not UI approval",
                status=HTTPStatus.BAD_REQUEST,
            )

        ts = _utc_iso()
        if decision == "approved":
            raw_approver = str(body.get("approver") or "human").strip() or "human"
            approver = re.sub(r"[\r\n]+", " ", raw_approver).strip()
            new_line = f"{gate}: approved by {approver} via ui at={ts}"
        else:
            raw_reason = str(body.get("reason") or "").strip()
            if not raw_reason:
                raise BridgeError("invalid_params", "reason is required when decision is 'rejected'")
            reason = re.sub(r"[\r\n]+", " ", raw_reason).strip()
            new_line = f"{gate}: rejected {reason} at={ts}"

        approvals_path = ws / "APPROVALS.md"
        existing_lines: list[str] = []
        if approvals_path.is_file():
            existing_lines = approvals_path.read_text(encoding="utf-8").splitlines()
        prior_pat = re.compile(rf"^{re.escape(gate)}\s*:\s*(?:approved|rejected)\b")
        kept = [line for line in existing_lines if not prior_pat.match(line)]
        kept.append(new_line)
        atomic_write_bytes(approvals_path, ("\n".join(kept) + "\n").encode("utf-8"))

        gate_result: dict[str, Any] | None = None
        if (ws / "PIPELINE.md").is_file():
            argv = [sys.executable, str(script), "gate", str(ws), gate, "--mode", "supervised"]
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
            try:
                gate_result = json.loads(proc.stdout) if proc.stdout.strip() else None
            except json.JSONDecodeError:
                gate_result = None
            if proc.returncode != 0:
                msg = (
                    (gate_result or {}).get("error")
                    or proc.stderr.strip()
                    or proc.stdout.strip()
                    or f"pipeline_ctl gate exited {proc.returncode}"
                )
                raise BridgeError("pipeline_gate_failed", str(msg), status=HTTPStatus.CONFLICT, data={"gateResult": gate_result})

        return {
            "ok": True,
            "workspace": str(ws),
            "gate": gate,
            "decision": decision,
            "state": decision,
            "at": ts,
            "approvalsLine": new_line,
            "gateResult": gate_result,
        }


class BridgeHTTPServer(ThreadingHTTPServer):
    """Threading HTTP/1.1 server bound strictly to 127.0.0.1."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], bridge: BridgeApplication) -> None:
        self.bridge = bridge
        self.stop_event = threading.Event()
        super().__init__(server_address, BridgeHTTPHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def token(self) -> str:
        return self.bridge.token

    def shutdown_bridge(self) -> None:
        self.stop_event.set()
        self.bridge.sse.close_all()
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            self.server_close()
        except Exception:
            pass
        self.bridge.agent_host_stop()
        self.bridge.sidecar.stop()


class BridgeHTTPHandler(BaseHTTPRequestHandler):
    """HTTP/1.1 request handler implementing the Rigorloom UI bridge contract."""

    protocol_version = "HTTP/1.1"
    server: BridgeHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        status: int,
        payload: Any,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Cache-Control": "no-store", **(extra_headers or {})}
        self._send_bytes(status, encoded, "application/json; charset=utf-8", extra_headers=headers)

    def _reject_forbidden(self, code: str, message: str) -> None:
        self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"code": code, "message": message}})

    def _check_origin_guards(self) -> bool:
        if not _valid_host_header(self.headers.get("Host")):
            self._reject_forbidden("invalid_host", "Host header must be 127.0.0.1 or localhost")
            return False
        if (self.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
            self._reject_forbidden("cross_site_refused", "cross-site requests are forbidden")
            return False
        return True

    def _require_header_token(self) -> bool:
        offered = self.headers.get("X-Rigorloom-Token", "")
        if not offered or not hmac.compare_digest(offered, self.server.bridge.token):
            self._reject_forbidden("unauthorized", "missing or invalid X-Rigorloom-Token header")
            return False
        return True

    def _require_query_token(self, query: dict[str, list[str]]) -> bool:
        values = query.get("token") or []
        offered = values[0] if values else ""
        if not offered or not hmac.compare_digest(offered, self.server.bridge.token):
            self._reject_forbidden("unauthorized", "missing or invalid ?token= query parameter")
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None or not raw_len.strip():
            return {}
        try:
            length = int(raw_len)
        except ValueError as exc:
            raise BridgeError("invalid_params", "invalid Content-Length") from exc
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            raise BridgeError("body_too_large", "request body exceeds maximum allowed size", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError("invalid_json", f"malformed JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BridgeError("invalid_params", "JSON body must be an object")
        return parsed

    def _handle_sse(self, query: dict[str, list[str]]) -> None:
        if not self._require_query_token(query):
            return
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def write_chunk(chunk: str) -> None:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        sub = self.server.bridge.sse.subscribe()
        try:
            status_json = json.dumps(self.server.bridge.sidecar.status(), ensure_ascii=False)
            write_chunk(f"event: runtime://status\ndata: {status_json}\n\n")
            while not self.server.stop_event.is_set():
                try:
                    item = sub.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    write_chunk(": keepalive\n\n")
                    continue
                if item is None:
                    break
                channel, payload = item
                encoded = json.dumps(payload, ensure_ascii=False)
                write_chunk(f"event: {channel}\ndata: {encoded}\n\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.bridge.sse.unsubscribe(sub)

    def do_GET(self) -> None:
        if not self._check_origin_guards():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/events":
            self._handle_sse(query)
            return

        if path == "/api/export-download":
            if not self._require_query_token(query):
                return
            try:
                names = query.get("name") or []
                target = self.server.bridge.resolve_export_download(names[0] if names else "")
                data = target.read_bytes()
            except BridgeError as exc:
                self._send_json(exc.status, exc.to_payload())
                return
            self._send_bytes(
                HTTPStatus.OK,
                data,
                "application/octet-stream",
                extra_headers={
                    "Content-Disposition": f'attachment; filename="{target.name}"',
                    "Cache-Control": "no-store",
                },
            )
            return

        if path.startswith("/api/"):
            if not self._require_header_token():
                return
            try:
                if path == "/api/runtime/status":
                    self._send_json(HTTPStatus.OK, self.server.bridge.sidecar.status())
                elif path == "/api/prefs":
                    self._send_json(HTTPStatus.OK, self.server.bridge.get_prefs())
                elif path == "/api/default-root":
                    self._send_json(HTTPStatus.OK, {"root": str(self.server.bridge.default_root)})
                elif path == "/api/corpus-files":
                    self._send_json(HTTPStatus.OK, self.server.bridge.list_corpus_files())
                elif path == "/api/agent-tool-status":
                    self._send_json(HTTPStatus.OK, self.server.bridge.agent_tool_status())
                elif path == "/api/agent-host/status":
                    self._send_json(HTTPStatus.OK, self.server.bridge.agent_host_status())
                elif path == "/api/task-packs":
                    self._send_json(HTTPStatus.OK, self.server.bridge.list_task_packs())
                elif path == "/api/pipeline/gates":
                    ws = (query.get("workspace") or [""])[0]
                    self._send_json(HTTPStatus.OK, self.server.bridge.pipeline_gates(ws))
                else:
                    raise BridgeError("not_found", f"unknown GET endpoint {path}", status=HTTPStatus.NOT_FOUND)
            except BridgeError as exc:
                self._send_json(exc.status, exc.to_payload())
            return

        if path in ("/", "/index.html"):
            html_bytes = self.server.bridge.render_index_html()
            self._send_bytes(
                HTTPStatus.OK,
                html_bytes,
                "text/html; charset=utf-8",
                extra_headers={"Cache-Control": "no-store"},
            )
            return

        resolved = self.server.bridge.resolve_static_asset(path)
        if resolved is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": path}})
            return
        asset_path, ctype = resolved
        self._send_bytes(
            HTTPStatus.OK,
            asset_path.read_bytes(),
            ctype,
            extra_headers={"Cache-Control": "public, max-age=3600"},
        )

    def do_POST(self) -> None:
        if not self._check_origin_guards():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path != "/rpc" and not path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": path}})
            return
        if not self._require_header_token():
            return

        try:
            body = self._read_json_body()
            if path == "/rpc":
                method = body.get("method")
                params = body.get("params")
                tag = body.get("tag")
                if tag is not None and not isinstance(tag, str):
                    raise BridgeError("invalid_params", "tag must be a string")
                ok, payload = self.server.bridge.sidecar.rpc(method, params, tag=tag)
                if ok:
                    self._send_json(HTTPStatus.OK, {"ok": True, "result": payload})
                else:
                    self._send_json(HTTPStatus.OK, {"ok": False, "error": payload})
                return

            routes = {
                "/api/runtime/start": self.server.bridge.runtime_start,
                "/api/runtime/stop": lambda _b: self.server.bridge.sidecar.stop(),
                "/api/runtime/cancel": lambda b: {"cancelled": self.server.bridge.sidecar.cancel(str(b.get("tag") or ""))},
                "/api/prefs": self.server.bridge.patch_prefs,
                "/api/open-upload": self.server.bridge.open_upload,
                "/api/export": self.server.bridge.export_candidate,
                "/api/run-mock-agent": self.server.bridge.run_mock_agent,
                "/api/agent-host/capabilities": self.server.bridge.agent_host_capabilities,
                "/api/agent-host/save-config": self.server.bridge.agent_host_save_config,
                "/api/agent-host/read-config": self.server.bridge.agent_host_read_config,
                "/api/agent-host/run": self.server.bridge.agent_host_run,
                "/api/agent-host/stop": lambda _b: self.server.bridge.agent_host_stop(),
                "/api/credential/status": self.server.bridge.credential_status,
                "/api/credential/set": self.server.bridge.credential_set,
                "/api/credential/delete": self.server.bridge.credential_delete,
                "/api/guard/diff": self.server.bridge.guard_diff,
                "/api/pipeline/gate-resolve": self.server.bridge.pipeline_gate_resolve,
            }
            handler = routes.get(path)
            if handler is None:
                raise BridgeError("not_found", f"unknown POST endpoint {path}", status=HTTPStatus.NOT_FOUND)
            result = handler(body)
            self._send_json(HTTPStatus.OK, result)
        except BridgeError as exc:
            self._send_json(exc.status, exc.to_payload())
        except Exception as exc:  # noqa: BLE001 - keep HTTP server alive on unexpected faults
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}},
            )


def create_bridge_server(
    *,
    root: Path | None = None,
    engine_root: Path | None = None,
    port: int = 8765,
    token: str | None = None,
    explicit_root: bool = False,
    prefs_path: Path | None = None,
    auto_start: bool = False,
) -> BridgeHTTPServer:
    """Create a configured BridgeHTTPServer bound strictly to 127.0.0.1."""
    app = BridgeApplication(
        root=root,
        engine_root=engine_root,
        token=token,
        explicit_root=explicit_root,
        prefs_path=prefs_path,
    )
    server = BridgeHTTPServer(("127.0.0.1", port), app)
    if auto_start:
        try:
            app.sidecar.start(app.default_root)
        except Exception:
            pass
    return server


def _should_open_browser(no_open: bool) -> bool:
    if no_open:
        return False
    if os.environ.get("CI"):
        return False
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_ui(
    *,
    root: Path | None,
    engine_root: Path | None = None,
    port: int = 8765,
    no_open: bool = False,
    explicit_root: bool = False,
) -> int:
    """Launch the HTTP/SSE UI bridge server and block until interrupted."""
    server = create_bridge_server(
        root=root,
        engine_root=engine_root,
        port=port,
        explicit_root=explicit_root,
        auto_start=True,
    )
    sys.stdout.write(f"Rigorloom UI listening on {server.url}\n")
    sys.stdout.flush()

    if _should_open_browser(no_open):
        try:
            webbrowser.open(server.url, new=1)
        except Exception:
            pass

    def _on_signal(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown_bridge, daemon=True).start()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except ValueError:
                pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_bridge()
    return 0
