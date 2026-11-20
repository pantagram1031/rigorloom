"""문체 점검 route for the browser bridge (WP4, advisor ruling B).

``POST /api/style/check`` runs ``rt_style.check`` on the document a session
shows: its source copy, or one published candidate (수정본) of it. The route
is read-only. It never writes, never takes a path from the caller, and only
reads files under the bridge's configured root, so the same token, Host and
Origin checks and body caps as every other ``/api/`` route apply.

The bridge loads this module through its extension hook (WP2) and calls
``handle_post(bridge, path, body)``; a ``None`` return means "not mine".
"""
from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:  # package import (wheel) or flat import (checkout, tests)
    from . import rt_style  # type: ignore[no-redef]
    from .rt_session import Session  # type: ignore[no-redef]
    from . import rt_apply  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - exercised by the flat layout
    import rt_style  # type: ignore[no-redef]
    from rt_session import Session  # type: ignore[no-redef]
    import rt_apply  # type: ignore[no-redef]

ROUTE = "/api/style/check"

#: Session and run ids are opaque hex-ish tokens; nothing else is accepted.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DOC_TYPES = frozenset(("any",) + tuple(rt_style.ALL))
_MAX_FINDINGS = 500


class StyleRouteError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


def _not_found() -> StyleRouteError:
    # One answer for "absent", "outside the root" and "not readable", so the
    # route cannot be used to probe for files.
    return StyleRouteError(HTTPStatus.NOT_FOUND, "not_found", "no such document")


def _id(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _ID_RE.match(value) or "\x00" in value:
        raise StyleRouteError(HTTPStatus.BAD_REQUEST, "invalid_params", f"{name} must be an id")
    return value


def _confined(root: Path, target: Path) -> Path:
    """``target`` resolved, or not_found when it leaves ``root`` in any way."""
    try:
        resolved_root = root.resolve(strict=True)
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _not_found() from None
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise _not_found()
    # A symlink anywhere below the root is refused even when it lands inside.
    # The root itself may be one (macOS /tmp, a Documents folder redirected
    # to a cloud drive): it is canonicalised above and never walked.
    if target.is_relative_to(root):
        base, below = root, target.relative_to(root).parts
    elif target.is_relative_to(resolved_root):
        base, below = resolved_root, target.relative_to(resolved_root).parts
    else:
        raise _not_found()
    probe = base
    for part in below:
        probe = probe / part
        if probe.is_symlink():
            raise _not_found()
    return resolved


def resolve_document(root: Path, session_id: str, run_id: str | None) -> Path:
    session = Session.load(root, session_id)
    if session is None:
        raise _not_found()
    if run_id is None:
        name = str(session.meta.get("sourceName") or "")
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise _not_found()
        return _confined(root, session.source_dir / name)
    try:
        path, _receipt = rt_apply.candidate_artifact(session, run_id)
    except Exception:  # noqa: BLE001 - a missing or drifted receipt is "not found"
        raise _not_found() from None
    return _confined(root, Path(path))


def style_check(root: Path, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise StyleRouteError(HTTPStatus.BAD_REQUEST, "invalid_params", "body must be an object")
    unknown = sorted(set(body) - {"sessionId", "runId", "docType"})
    if unknown:
        raise StyleRouteError(HTTPStatus.BAD_REQUEST, "unknown_field", "unknown fields: " + ", ".join(unknown))
    session_id = _id(body.get("sessionId"), "sessionId")
    run_id = _id(body.get("runId"), "runId", optional=True)
    doc_type = body.get("docType")
    if doc_type is not None and (not isinstance(doc_type, str) or doc_type not in _DOC_TYPES):
        raise StyleRouteError(HTTPStatus.BAD_REQUEST, "invalid_params", "docType is not a known document type")
    path = resolve_document(root, session_id, run_id)
    try:
        result = rt_style.check(path, doc_type=doc_type)
    except rt_style.StyleInputError as exc:
        raise StyleRouteError(HTTPStatus.UNPROCESSABLE_ENTITY, "style_unavailable", str(exc)) from None
    findings = [
        {
            "rule": f["rule"],
            "severity": f["severity"],
            "message": f["why"],
            "suggest": f["suggest"],
            "excerpt": f["match"],
            # Paragraph units are 1-based in rt_style; addresses are 0-based.
            "at": f"p{int(f['line']) - 1}" if result.get("unit") == "paragraph" else None,
        }
        for f in result["findings"][:_MAX_FINDINGS]
    ]
    return {
        "ok": True,
        "docType": result["docType"],
        "ruleset": result["ruleset"],
        "counts": result["counts"],
        "findings": findings,
    }


def handle_post(bridge: Any, path: str, body: Any) -> tuple[HTTPStatus, dict[str, Any]] | None:
    """The bridge hook. Auth, Host/Origin and body caps run before this."""
    if path != ROUTE:
        return None
    try:
        return HTTPStatus.OK, style_check(Path(bridge.current_root()), body)
    except StyleRouteError as exc:
        return exc.status, exc.payload()


def install(handler_cls: Any) -> None:
    """Route ``POST /api/style/check`` on a ``BridgeHTTPHandler`` class.

    For a bridge without WP2's extension hook. The wrapped ``do_POST`` runs
    the handler's own Origin/Host guard, token check and body cap first, so
    this route can never be reached with less than the others require.
    Idempotent.
    """
    if getattr(handler_cls, "_rl_style_installed", False):
        return
    original = handler_cls.do_POST

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        from urllib.parse import urlsplit

        if urlsplit(self.path).path != ROUTE:
            original(self)
            return
        if not self._check_origin_guards():
            return
        if not self._require_header_token():
            return
        try:
            body = self._read_json_body()
        except Exception as exc:  # noqa: BLE001 - the bridge's own BridgeError
            status = getattr(exc, "status", HTTPStatus.BAD_REQUEST)
            to_payload = getattr(exc, "to_payload", None)
            self._send_json(status, to_payload() if callable(to_payload) else
                            {"ok": False, "error": {"code": "invalid_body", "message": str(exc)}})
            return
        status, payload = handle_post(self.server.bridge, ROUTE, body)  # type: ignore[misc]
        self._send_json(status, payload)

    handler_cls.do_POST = do_POST
    handler_cls._rl_style_installed = True
