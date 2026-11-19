#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, root-confined workspace folder routes for Rigorloom editor v2.

Serves directory listings, file metadata, and read-only document bytes strictly
within the configured workspace root (``문서 폴더`` / ``작업 폴더``).

Security invariants (binding per advisor ruling item B):
- Strictly read-only: no create, write, delete, rename, or move endpoints;
  mutating HTTP methods (PUT/DELETE/PATCH) are refused.
- Path confinement: rejects ``..``, absolute POSIX/Windows paths, drive letters,
  UNC paths, NTFS alternate data streams, NUL/control bytes, hidden dotfiles,
  and symlink escapes (both file and directory symlinks, including chains).
- Zero existence oracle: missing paths, outside-root paths, traversal attempts,
  symlink escapes, and unsupported files return the exact same HTTP 404 status
  and identical JSON error payload.
- HTTP guard parity with ``rt_ui.py``: strict ``127.0.0.1`` bind, ``Host`` and
  ``Origin`` localhost allowlist, ``Sec-Fetch-Site`` cross-site refusal,
  constant-time ``X-Rigorloom-Token`` authentication, and ``MAX_JSON_BODY_BYTES``
  / ``MAX_SOURCE_BYTES`` size caps.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import stat
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

try:
    from .rt_session import MAX_SOURCE_BYTES
except ImportError:
    try:
        from rt_session import MAX_SOURCE_BYTES
    except ImportError:
        MAX_SOURCE_BYTES = 32 * 1024 * 1024

try:
    from .rt_ui import ALLOWED_HOSTS, MAX_JSON_BODY_BYTES, _valid_host_header
except ImportError:
    try:
        from rt_ui import ALLOWED_HOSTS, MAX_JSON_BODY_BYTES, _valid_host_header
    except ImportError:
        ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
        MAX_JSON_BODY_BYTES = max(64 * 1024 * 1024, MAX_SOURCE_BYTES * 2)

        def _valid_host_header(host_value: str | None) -> bool:
            if not host_value:
                return False
            raw = host_value.strip()
            if not raw or any(ch in raw for ch in ("/", "@", "\\", "[", "]", " ", "\t")):
                return False
            host, sep, port_str = raw.partition(":")
            if sep and (not port_str or not port_str.isdigit()):
                return False
            return host.lower() in ALLOWED_HOSTS


WORKSPACE_ROUTE_PREFIX = "/api/workspace/"
SUPPORTED_EXTENSIONS = frozenset({".hwp", ".hwpx", ".docx", ".md"})
MAX_LIST_ENTRIES = 1000
MAX_TREE_DEPTH = 12
MAX_PATH_LENGTH = 4096

UNIFORM_NOT_FOUND_STATUS = HTTPStatus.NOT_FOUND
UNIFORM_NOT_FOUND_CODE = "workspace_not_found"
UNIFORM_NOT_FOUND_MESSAGE = "requested workspace entry was not found"

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SPLIT_SEPS_RE = re.compile(r"[/\\]+")
_ALLOWED_LIST_KEYS = frozenset({"path", "recursive", "maxDepth"})
_ALLOWED_STAT_KEYS = frozenset({"path"})
_ALLOWED_READ_KEYS = frozenset({"path", "format"})


class WorkspaceError(Exception):
    """Structured HTTP error emitted by workspace routes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = HTTPStatus.BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = int(status)

    def to_payload(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


def _uniform_not_found() -> WorkspaceError:
    """Return a constant 404 payload with zero path or existence disclosure."""
    return WorkspaceError(
        UNIFORM_NOT_FOUND_CODE,
        UNIFORM_NOT_FOUND_MESSAGE,
        status=UNIFORM_NOT_FOUND_STATUS,
    )


def validate_host_header(host_value: str | None) -> bool:
    """Allow only 127.0.0.1 or localhost (with optional numeric :port)."""
    return _valid_host_header(host_value)


def validate_origin_header(origin_value: str | None) -> bool:
    """Validate an Origin header when present: localhost / 127.0.0.1 HTTP only."""
    if origin_value is None:
        return True
    raw = origin_value.strip()
    if not raw or raw.lower() == "null":
        return False
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "http":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return False
    return validate_host_header(parsed.netloc)


def validate_sec_fetch_site(value: str | None) -> bool:
    """Reject cross-site fetches, matching rt_ui.py."""
    return (value or "").strip().lower() != "cross-site"


def validate_token(offered: str | None, expected: str) -> bool:
    """Constant-time validation of the per-launch X-Rigorloom-Token header."""
    if not offered or not expected:
        return False
    return hmac.compare_digest(offered, expected)


def _mtime_utc(st: os.stat_result) -> str:
    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_supported_file_name(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_EXTENSIONS


def _parse_bool_flag(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        val = raw.strip().lower()
        if val in ("1", "true", "yes"):
            return True
        if val in ("0", "false", "no", ""):
            return False
    raise WorkspaceError("invalid_params", "boolean flag must be true or false")


def _parse_max_depth(raw: Any, default: int = 1) -> int:
    if raw is None or raw == "":
        return default
    try:
        depth = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError("invalid_params", "maxDepth must be an integer") from exc
    if depth < 1:
        return 1
    return min(depth, MAX_TREE_DEPTH)


def _reject_unknown_keys(body: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(body.keys()) - allowed)
    if unknown:
        raise WorkspaceError(
            "invalid_params",
            f"unsupported parameters: {', '.join(unknown)}",
            status=HTTPStatus.BAD_REQUEST,
        )


def _resolve_root(root: Path) -> Path:
    try:
        resolved = Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise _uniform_not_found() from exc
    if not resolved.is_dir():
        raise _uniform_not_found()
    return resolved


def _is_confined_visible_target(resolved_root: Path, resolved_target: Path) -> bool:
    """Return True iff `resolved_target` is inside `resolved_root` with no hidden segments."""
    if not resolved_target.is_relative_to(resolved_root):
        return False
    rel_parts = resolved_target.relative_to(resolved_root).parts
    return all(part and not part.startswith(".") and ":" not in part for part in rel_parts)


def resolve_confined_path(root: Path, raw_rel: str | None, *, allow_root: bool = False) -> Path:
    """Resolve `raw_rel` strictly inside `root`, raising uniform 404 on any escape.

    Rejects:
    - NUL bytes and ASCII control characters
    - POSIX absolute paths (`/etc/passwd`)
    - Windows drive paths (`C:\\...`, `C:/...`, `C:file`) and NTFS ADS (`a:b`)
    - Windows/POSIX UNC forms (`\\\\server\\share`, `//server/share`)
    - `..`, `.` interior segments, and hidden `.`-prefixed segments
    - Symlinks (including chains) that dangle or resolve outside `root`
    - Missing targets (returning the exact same error as outside-root targets)
    """
    resolved_root = _resolve_root(root)

    if raw_rel is None or raw_rel == "" or raw_rel == ".":
        if allow_root:
            return resolved_root
        raise _uniform_not_found()

    if not isinstance(raw_rel, str):
        raise _uniform_not_found()
    if len(raw_rel) > MAX_PATH_LENGTH:
        raise _uniform_not_found()
    if "\x00" in raw_rel or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_rel):
        raise _uniform_not_found()

    # Reject absolute POSIX paths, UNC paths, leading backslashes, and drive specs.
    if raw_rel.startswith("/") or raw_rel.startswith("\\"):
        raise _uniform_not_found()
    if _WINDOWS_DRIVE_RE.match(raw_rel):
        raise _uniform_not_found()
    if PureWindowsPath(raw_rel).is_absolute() or PureWindowsPath(raw_rel).drive:
        raise _uniform_not_found()
    if PurePosixPath(raw_rel).is_absolute():
        raise _uniform_not_found()

    # Reject trailing slash ambiguity on file paths while cleaning cleanly.
    stripped = raw_rel.rstrip("/\\")
    if not stripped:
        if allow_root:
            return resolved_root
        raise _uniform_not_found()

    raw_parts = _SPLIT_SEPS_RE.split(stripped)
    if not raw_parts:
        raise _uniform_not_found()

    parts: list[str] = []
    for part in raw_parts:
        if not part or part in (".", ".."):
            raise _uniform_not_found()
        if part.startswith("."):
            raise _uniform_not_found()
        if ":" in part:
            raise _uniform_not_found()
        parts.append(part)

    # Walk component-by-component, confining every symlink hop strictly inside root.
    current = resolved_root
    for part in parts:
        candidate = current / part
        try:
            lstat = os.lstat(candidate)
        except OSError as exc:
            raise _uniform_not_found() from exc

        if stat.S_ISLNK(lstat.st_mode):
            try:
                resolved_hop = candidate.resolve(strict=True)
            except OSError as exc:
                raise _uniform_not_found() from exc
            if not _is_confined_visible_target(resolved_root, resolved_hop):
                raise _uniform_not_found()
            current = resolved_hop
        else:
            current = candidate

    try:
        final = current.resolve(strict=True)
    except OSError as exc:
        raise _uniform_not_found() from exc
    if not _is_confined_visible_target(resolved_root, final):
        raise _uniform_not_found()
    return final


class WorkspaceService:
    """Read-only workspace explorer confined to a server-configured root."""

    def __init__(self, root_provider: Path | Callable[[], Path]) -> None:
        self._root_provider = root_provider

    def active_root(self) -> Path:
        raw = self._root_provider() if callable(self._root_provider) else self._root_provider
        return _resolve_root(Path(raw))

    def _safe_rel_posix(self, resolved_root: Path, target: Path) -> str:
        rel = target.relative_to(resolved_root)
        return "" if str(rel) == "." else rel.as_posix()

    def _entry_metadata(
        self,
        resolved_root: Path,
        entry_path: Path,
        st: os.stat_result,
        *,
        is_dir: bool,
    ) -> dict[str, Any]:
        rel_posix = self._safe_rel_posix(resolved_root, entry_path)
        if is_dir:
            return {
                "name": entry_path.name,
                "relPath": rel_posix,
                "kind": "dir",
                "mtimeUtc": _mtime_utc(st),
            }
        return {
            "name": entry_path.name,
            "relPath": rel_posix,
            "kind": "file",
            "extension": entry_path.suffix.lower(),
            "size": int(st.st_size),
            "mtimeUtc": _mtime_utc(st),
        }

    def list_entries(
        self,
        rel_path: str | None = None,
        *,
        recursive: bool = False,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        resolved_root = self.active_root()
        target_dir = resolve_confined_path(resolved_root, rel_path, allow_root=True)
        if not target_dir.is_dir():
            raise _uniform_not_found()

        depth_limit = min(max(1, max_depth), MAX_TREE_DEPTH) if recursive else 1
        entries: list[dict[str, Any]] = []
        truncated = False
        visited_dirs: set[tuple[int, int]] = set()

        def walk(current_dir: Path, depth: int) -> None:
            nonlocal truncated
            try:
                dir_st = current_dir.stat()
            except OSError:
                return
            dir_key = (dir_st.st_dev, dir_st.st_ino)
            if dir_key in visited_dirs:
                return
            visited_dirs.add(dir_key)

            try:
                scanned = list(os.scandir(current_dir))
            except OSError:
                return

            child_dirs: list[tuple[Path, os.stat_result, bool]] = []
            child_files: list[tuple[Path, os.stat_result]] = []

            for item in scanned:
                name = item.name
                if not name or name.startswith(".") or ":" in name:
                    continue
                item_path = current_dir / name
                try:
                    is_sym = item.is_symlink()
                except OSError:
                    continue

                if is_sym:
                    # Resolve symlink strictly; silently omit broken, hidden, or escaping symlinks.
                    try:
                        resolved_item = item_path.resolve(strict=True)
                    except OSError:
                        continue
                    if not _is_confined_visible_target(resolved_root, resolved_item):
                        continue
                    try:
                        st = resolved_item.stat()
                    except OSError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        # Include confined directory entry but never recurse symlinked dirs.
                        child_dirs.append((item_path, st, False))
                    elif (
                        stat.S_ISREG(st.st_mode)
                        and _is_supported_file_name(name)
                        and _is_supported_file_name(resolved_item.name)
                    ):
                        child_files.append((item_path, st))
                else:
                    try:
                        st = item.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        child_dirs.append((item_path, st, True))
                    elif stat.S_ISREG(st.st_mode) and _is_supported_file_name(name):
                        child_files.append((item_path, st))

            child_dirs.sort(key=lambda row: (row[0].name.lower(), row[0].name))
            child_files.sort(key=lambda row: (row[0].name.lower(), row[0].name))

            for dpath, st, can_recurse in child_dirs:
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                    return
                entries.append(self._entry_metadata(resolved_root, dpath, st, is_dir=True))
                if can_recurse and depth < depth_limit:
                    walk(dpath, depth + 1)
                    if truncated:
                        return

            for fpath, st in child_files:
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                    return
                entries.append(self._entry_metadata(resolved_root, fpath, st, is_dir=False))

        walk(target_dir, 1)
        return {
            "ok": True,
            "rootName": resolved_root.name,
            "path": self._safe_rel_posix(resolved_root, target_dir),
            "entries": entries,
            "truncated": truncated,
            "supportedExtensions": sorted(SUPPORTED_EXTENSIONS),
        }

    def stat_entry(self, rel_path: str | None) -> dict[str, Any]:
        resolved_root = self.active_root()
        target = resolve_confined_path(resolved_root, rel_path, allow_root=False)
        try:
            st = target.stat()
        except OSError as exc:
            raise _uniform_not_found() from exc

        if stat.S_ISDIR(st.st_mode):
            meta = self._entry_metadata(resolved_root, target, st, is_dir=True)
            return {"ok": True, "entry": meta}
        if stat.S_ISREG(st.st_mode) and _is_supported_file_name(target.name):
            meta = self._entry_metadata(resolved_root, target, st, is_dir=False)
            return {"ok": True, "entry": meta}
        raise _uniform_not_found()

    def resolve_entry(self, rel_path: str | None) -> dict[str, Any]:
        """The absolute path of one openable file under the 문서 폴더.

        The 파일 pane opens a document by this answer, never by a path it
        composed itself: the confinement is decided here, by the same walk as
        every other route, and a path outside the folder or a file that is not
        a document answers the same 404 as a missing one.
        """
        resolved_root = self.active_root()
        target = resolve_confined_path(resolved_root, rel_path, allow_root=False)
        try:
            st = target.stat()
        except OSError as exc:
            raise _uniform_not_found() from exc
        if not stat.S_ISREG(st.st_mode) or not _is_supported_file_name(target.name):
            raise _uniform_not_found()
        return {
            "ok": True,
            "path": str(target),
            "entry": self._entry_metadata(resolved_root, target, st, is_dir=False),
        }

    def read_file_bytes(self, rel_path: str | None) -> tuple[dict[str, Any], bytes]:
        resolved_root = self.active_root()
        target = resolve_confined_path(resolved_root, rel_path, allow_root=False)
        if not _is_supported_file_name(target.name):
            raise _uniform_not_found()

        flags = os.O_RDONLY
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            fd = os.open(str(target), flags)
        except OSError as exc:
            raise _uniform_not_found() from exc

        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise _uniform_not_found()
            # Re-verify confinement against the opened descriptor's target.
            final_check = target.resolve(strict=True)
            if not final_check.is_relative_to(resolved_root):
                raise _uniform_not_found()
            if st.st_size > MAX_SOURCE_BYTES:
                raise WorkspaceError(
                    "file_too_large",
                    f"file exceeds maximum {MAX_SOURCE_BYTES} bytes",
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            with os.fdopen(fd, "rb", closefd=True) as fh:
                fd = -1
                data = fh.read(MAX_SOURCE_BYTES + 1)
            if len(data) > MAX_SOURCE_BYTES:
                raise WorkspaceError(
                    "file_too_large",
                    f"file exceeds maximum {MAX_SOURCE_BYTES} bytes",
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

        meta = self._entry_metadata(resolved_root, target, st, is_dir=False)
        return meta, data

    def read_file_json(self, rel_path: str | None) -> dict[str, Any]:
        meta, data = self.read_file_bytes(rel_path)
        return {
            "ok": True,
            "entry": meta,
            "bytesBase64": base64.b64encode(data).decode("ascii"),
        }


def _service_from_bridge(bridge: Any) -> WorkspaceService:
    """Build a confined WorkspaceService from an rt_ui.BridgeApplication instance."""
    existing = getattr(bridge, "workspace_service", None)
    if isinstance(existing, WorkspaceService):
        return existing

    def resolve_bridge_root() -> Path:
        root_fn = getattr(bridge, "workspace_root", None)
        if callable(root_fn):
            candidate = root_fn()
            if candidate:
                return Path(candidate)
        prefs_fn = getattr(bridge, "get_prefs", None)
        if callable(prefs_fn):
            prefs = prefs_fn() or {}
            # `docFolder` is the key the shell's 문서 폴더 setting writes;
            # `documentsRoot` is accepted as the earlier name.
            for key in ("docFolder", "documentsRoot"):
                docs_root = prefs.get(key)
                if isinstance(docs_root, str) and docs_root.strip():
                    p = Path(docs_root).expanduser()
                    if p.is_dir():
                        return p
        # No 문서 폴더 chosen: nothing is listed. The runtime's own store (the
        # bridge root, with sessions and candidates) is never offered as one.
        raise _uniform_not_found()

    return WorkspaceService(resolve_bridge_root)


def handle_get(
    bridge_or_service: Any,
    path: str,
    query: dict[str, list[str]],
) -> tuple[int, Any] | None:
    """Extension hook for GET /api/workspace/* routes.

    Returns ``None`` if `path` is outside ``/api/workspace/``, else
    ``(status_code, payload_or_bytes)``.
    """
    if not path.startswith(WORKSPACE_ROUTE_PREFIX):
        return None
    if "root" in query:
        raise WorkspaceError("invalid_params", "root override is not permitted")

    service = (
        bridge_or_service
        if isinstance(bridge_or_service, WorkspaceService)
        else _service_from_bridge(bridge_or_service)
    )
    rel = (query.get("path") or [None])[0]

    if path == "/api/workspace/list":
        allowed_q = {"path", "recursive", "maxDepth"}
        extra_q = sorted(set(query.keys()) - allowed_q)
        if extra_q:
            raise WorkspaceError("invalid_params", f"unsupported parameters: {', '.join(extra_q)}")
        recursive = _parse_bool_flag((query.get("recursive") or [None])[0], default=False)
        max_depth = _parse_max_depth(
            (query.get("maxDepth") or [None])[0],
            default=MAX_TREE_DEPTH if recursive else 1,
        )
        return HTTPStatus.OK, service.list_entries(rel, recursive=recursive, max_depth=max_depth)

    if path == "/api/workspace/stat":
        extra_q = sorted(set(query.keys()) - {"path"})
        if extra_q:
            raise WorkspaceError("invalid_params", f"unsupported parameters: {', '.join(extra_q)}")
        return HTTPStatus.OK, service.stat_entry(rel)

    if path == "/api/workspace/read":
        extra_q = sorted(set(query.keys()) - {"path", "format"})
        if extra_q:
            raise WorkspaceError("invalid_params", f"unsupported parameters: {', '.join(extra_q)}")
        fmt = ((query.get("format") or ["json"])[0] or "json").strip().lower()
        if fmt == "json":
            return HTTPStatus.OK, service.read_file_json(rel)
        if fmt == "raw":
            meta, raw = service.read_file_bytes(rel)
            return HTTPStatus.OK, {"_raw": raw, "_meta": meta}
        raise WorkspaceError("invalid_params", "format must be 'json' or 'raw'")

    raise WorkspaceError("not_found", f"unknown workspace endpoint {path}", status=HTTPStatus.NOT_FOUND)


def handle_post(
    bridge_or_service: Any,
    path: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]] | None:
    """Extension hook for read-only POST /api/workspace/* routes."""
    if not path.startswith(WORKSPACE_ROUTE_PREFIX):
        return None
    if not isinstance(body, dict):
        raise WorkspaceError("invalid_params", "JSON body must be an object")

    service = (
        bridge_or_service
        if isinstance(bridge_or_service, WorkspaceService)
        else _service_from_bridge(bridge_or_service)
    )

    if path == "/api/workspace/list":
        _reject_unknown_keys(body, _ALLOWED_LIST_KEYS)
        recursive = _parse_bool_flag(body.get("recursive"), default=False)
        max_depth = _parse_max_depth(
            body.get("maxDepth"),
            default=MAX_TREE_DEPTH if recursive else 1,
        )
        return HTTPStatus.OK, service.list_entries(
            body.get("path"),
            recursive=recursive,
            max_depth=max_depth,
        )

    if path == "/api/workspace/stat":
        _reject_unknown_keys(body, _ALLOWED_STAT_KEYS)
        return HTTPStatus.OK, service.stat_entry(body.get("path"))

    if path == "/api/workspace/resolve":
        _reject_unknown_keys(body, _ALLOWED_STAT_KEYS)
        return HTTPStatus.OK, service.resolve_entry(body.get("path"))

    if path == "/api/workspace/read":
        _reject_unknown_keys(body, _ALLOWED_READ_KEYS)
        fmt = str(body.get("format") or "json").strip().lower()
        if fmt != "json":
            raise WorkspaceError("invalid_params", "POST read supports format='json' only")
        return HTTPStatus.OK, service.read_file_json(body.get("path"))

    raise WorkspaceError("not_found", f"unknown workspace endpoint {path}", status=HTTPStatus.NOT_FOUND)


def _register_on_router(router: Any) -> None:
    """Register on `rt_ui.ExtensionRouter`: handlers are `handler(bridge, query|body)`.

    A WorkspaceError becomes the router's BridgeError with the same status and
    code, so a path outside the root and a missing one still answer the same
    404 body through `rigorloom ui`.
    """
    bridge_error = router.BridgeError

    def wrap(fn: Callable[..., Any], route: str) -> Callable[[Any, Any], Any]:
        def handler(bridge: Any, arg: Any) -> Any:
            # Raw bytes are the standalone server's; the bridge answers JSON
            # only, and says so before reading anything (finding 10).
            if fn is handle_get and route == "/api/workspace/read" and isinstance(arg, dict):
                fmt = ((arg.get("format") or ["json"])[0] or "json").strip().lower()
                if fmt != "json":
                    raise bridge_error("invalid_params", "use format=json through the bridge", status=HTTPStatus.BAD_REQUEST)
            try:
                status, payload = fn(_service_from_bridge(bridge), route, arg)
            except WorkspaceError as exc:
                raise bridge_error(exc.code, exc.message, status=exc.status) from None
            if not isinstance(payload, dict) or "_raw" in payload:
                raise bridge_error("invalid_params", "use format=json through the bridge", status=HTTPStatus.BAD_REQUEST)
            return payload

        return handler

    for route in ("/api/workspace/list", "/api/workspace/stat", "/api/workspace/read"):
        router.get(route, wrap(handle_get, route))
        router.post(route, wrap(handle_post, route))
    router.post("/api/workspace/resolve", wrap(handle_post, "/api/workspace/resolve"))


def register_routes(bridge: Any) -> dict[str, dict[str, Callable[..., Any]]] | None:
    """Route registration for `rt_ui.py`'s extension hook.

    `rigorloom ui` passes its ExtensionRouter (`router.get/post(path, handler)`),
    and the routes are registered on it. Given a bridge instead, the route
    table is returned (the standalone server and the module's own tests).
    """
    if hasattr(bridge, "get_routes") and hasattr(bridge, "post_routes") and hasattr(bridge, "BridgeError"):
        _register_on_router(bridge)
        return None
    service = _service_from_bridge(bridge)
    return {
        "get": {
            "/api/workspace/list": lambda query: handle_get(service, "/api/workspace/list", query)[1],
            "/api/workspace/stat": lambda query: handle_get(service, "/api/workspace/stat", query)[1],
            "/api/workspace/read": lambda query: handle_get(service, "/api/workspace/read", query)[1],
        },
        "post": {
            "/api/workspace/list": lambda body: handle_post(service, "/api/workspace/list", body)[1],
            "/api/workspace/stat": lambda body: handle_post(service, "/api/workspace/stat", body)[1],
            "/api/workspace/read": lambda body: handle_post(service, "/api/workspace/read", body)[1],
            "/api/workspace/resolve": lambda body: handle_post(service, "/api/workspace/resolve", body)[1],
        },
    }


class WorkspaceHTTPServer(ThreadingHTTPServer):
    """Standalone read-only HTTP server enforcing identical rt_ui security guards."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: WorkspaceService,
        *,
        token: str | None = None,
        max_body_bytes: int = MAX_JSON_BODY_BYTES,
    ) -> None:
        self.service = service
        self.token = token or secrets.token_urlsafe(24)
        self.max_body_bytes = min(int(max_body_bytes), MAX_JSON_BODY_BYTES)
        self.stop_event = threading.Event()
        super().__init__(server_address, WorkspaceHTTPHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def shutdown_workspace(self) -> None:
        self.stop_event.set()
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            self.server_close()
        except Exception:
            pass


class WorkspaceHTTPHandler(BaseHTTPRequestHandler):
    """HTTP/1.1 handler applying rt_ui Host/Origin/token/body-cap guards."""

    protocol_version = "HTTP/1.1"
    server: WorkspaceHTTPServer

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
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, encoded, "application/json; charset=utf-8")

    def _reject_forbidden(self, code: str, message: str) -> None:
        self._send_json(
            HTTPStatus.FORBIDDEN,
            {"ok": False, "error": {"code": code, "message": message}},
        )

    def _check_security_guards(self) -> bool:
        if not validate_host_header(self.headers.get("Host")):
            self._reject_forbidden("invalid_host", "Host header must be 127.0.0.1 or localhost")
            return False
        if not validate_sec_fetch_site(self.headers.get("Sec-Fetch-Site")):
            self._reject_forbidden("cross_site_refused", "cross-site requests are forbidden")
            return False
        if not validate_origin_header(self.headers.get("Origin")):
            self._reject_forbidden("invalid_origin", "Origin header must be localhost or 127.0.0.1")
            return False
        if not validate_token(self.headers.get("X-Rigorloom-Token"), self.server.token):
            self._reject_forbidden("unauthorized", "missing or invalid X-Rigorloom-Token header")
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        if (self.headers.get("Transfer-Encoding") or "").strip():
            raise WorkspaceError(
                "length_required",
                "chunked transfer encoding is not permitted",
                status=HTTPStatus.LENGTH_REQUIRED,
            )
        raw_len = self.headers.get("Content-Length")
        if raw_len is None or not raw_len.strip():
            return {}
        try:
            length = int(raw_len)
        except ValueError as exc:
            raise WorkspaceError("invalid_params", "invalid Content-Length") from exc
        if length < 0 or length > self.server.max_body_bytes:
            raise WorkspaceError(
                "body_too_large",
                "request body exceeds maximum allowed size",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceError("invalid_json", f"malformed JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise WorkspaceError("invalid_params", "JSON body must be an object")
        return parsed

    def _reject_mutating_method(self) -> None:
        if not self._check_security_guards():
            return
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"ok": False, "error": {"code": "method_not_allowed", "message": "workspace routes are read-only"}},
        )

    def do_PUT(self) -> None:
        self._reject_mutating_method()

    def do_DELETE(self) -> None:
        self._reject_mutating_method()

    def do_PATCH(self) -> None:
        self._reject_mutating_method()

    def do_GET(self) -> None:
        if not self._check_security_guards():
            return
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            outcome = handle_get(self.server.service, parsed.path, query)
            if outcome is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": {"code": "not_found", "message": "unknown endpoint"}},
                )
                return
            status, payload = outcome
            if isinstance(payload, dict) and "_raw" in payload:
                self._send_bytes(status, payload["_raw"], "application/octet-stream")
            else:
                self._send_json(status, payload)
        except WorkspaceError as exc:
            self._send_json(exc.status, exc.to_payload())

    def do_POST(self) -> None:
        if not self._check_security_guards():
            return
        parsed = urlsplit(self.path)
        try:
            body = self._read_json_body()
            outcome = handle_post(self.server.service, parsed.path, body)
            if outcome is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": {"code": "not_found", "message": "unknown endpoint"}},
                )
                return
            status, payload = outcome
            self._send_json(status, payload)
        except WorkspaceError as exc:
            self._send_json(exc.status, exc.to_payload())


def create_workspace_server(
    *,
    root: Path,
    port: int = 0,
    token: str | None = None,
    max_body_bytes: int = MAX_JSON_BODY_BYTES,
) -> WorkspaceHTTPServer:
    """Create a read-only WorkspaceHTTPServer strictly bound to 127.0.0.1."""
    service = WorkspaceService(Path(root))
    return WorkspaceHTTPServer(
        ("127.0.0.1", port),
        service,
        token=token,
        max_body_bytes=max_body_bytes,
    )
