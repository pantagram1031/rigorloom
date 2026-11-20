"""Revision-bound page reads for the editor's document canvas."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from itertools import count
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Condition

try:
    from . import rt_apply, rt_doc, rt_render
    from .rt_codes import MAX_INLINE_IMAGE_BYTES, MIN_RENDER_DPI, RpcError
    from .rt_engine import EngineTools
    from .rt_session import Session, sha256_file
except ImportError:
    import rt_apply
    import rt_doc
    import rt_render
    from rt_codes import MAX_INLINE_IMAGE_BYTES, MIN_RENDER_DPI, RpcError
    from rt_engine import EngineTools
    from rt_session import Session, sha256_file


MAX_SCALE = 3
FIELDS = {
    "pages": set(),
    "render": {"page", "scale"},
    "geometry": {"page"},
    "hit": {"page", "x", "y"},
    "caret": {"at", "offset"},
}


class PageError(Exception):
    def __init__(self, code, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.code, self.status = code, status


def _missing():
    return PageError("not_found", "no such session document", HTTPStatus.NOT_FOUND)


def _stale():
    return PageError("stale_rev", "revision is no longer the session head", HTTPStatus.CONFLICT)


def _confined(base: Path, path: Path) -> None:
    """Check lexical containment and refuse links below the canonical root."""
    try:
        if not path.is_relative_to(base) or path.resolve() != path:
            raise _missing()
        if path.is_file() and path.stat().st_nlink != 1:
            raise _missing()
    except (OSError, RuntimeError):
        raise _missing() from None


@dataclass(frozen=True)
class Head:
    session: Session
    path: Path
    run_id: str | None
    rev: str

    def confine(self, path: Path) -> None:
        _confined(self.session.dir, path)


def _head(root: Path, session_id: str, rev: str) -> Head:
    _confined(root, root / "sessions" / session_id / "meta.json")
    session = Session.load(root, session_id)
    if session is None:
        raise _missing()
    def confine(path):
        _confined(session.dir, path)

    rows = rt_apply.list_candidates(session, confine=confine)
    if rows:
        row = rows[-1]
        if row.get("sha256") != rev:
            raise _stale()
        run_id = row["runId"]
        run_dir = session.candidates_dir / run_id
        receipt = rt_apply.read_receipt(
            session, run_id, confine=lambda path: _confined(run_dir, path),
        )["candidate"]
        if receipt["sha256"] != rev:
            raise _stale()
        return Head(session, run_dir / receipt["path"], run_id, rev)

    if session.meta.get("sourceSha256") != rev:
        raise _stale()
    name = session.meta.get("sourceName")
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        raise _missing()
    confine(session.source)
    if not session.source.is_relative_to(session.source_dir) or not session.source.is_file():
        raise _missing()
    if sha256_file(session.source)[0] != rev:
        raise _stale()
    return Head(session, session.source, None, rev)


def _integer(value, name, minimum):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= 2**31 - 1:
        raise PageError("invalid_params", f"{name} must be an integer of at least {minimum}")
    return value


def _number(value, name):
    try:
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
    except (OverflowError, ValueError):
        pass
    raise PageError("invalid_params", f"{name} must be a finite number")


def _params(operation, body):
    if operation == "render" and "pages" in body:
        raise PageError("page_limit", "a render request accepts one page")
    if set(body) != FIELDS[operation] | {"sessionId", "rev"}:
        raise PageError("invalid_params", "unexpected or missing page request fields")
    session_id, rev = body["sessionId"], body["rev"]
    if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise PageError("invalid_params", "sessionId must be a session identifier")
    if not isinstance(rev, str) or not re.fullmatch(r"[a-f0-9]{64}", rev):
        raise PageError("invalid_params", "rev must be a document digest")
    args = {}
    if "page" in body:
        if isinstance(body["page"], list) or "," in str(body["page"]):
            raise PageError("page_limit", "a page request accepts one page")
        args["page"] = _integer(body["page"], "page", 1)
    if operation == "render":
        scale = _number(body["scale"], "scale")
        if not 0 < scale <= MAX_SCALE:
            raise PageError("scale_limit", "render scale must be above zero and at most 3")
        args["scale"] = scale
    if operation == "hit":
        args.update(x=_number(body["x"], "x"), y=_number(body["y"], "y"))
    if operation == "caret":
        at = body["at"]
        if not isinstance(at, str) or not at or len(at) > 256:
            raise PageError("invalid_params", "at must be a document address")
        args.update(at=at, offset=_integer(body["offset"], "offset", 0))
    return session_id, rev, args


def _engine_result(result, rev):
    if not result.get("ok"):
        code = result["error"]["code"]
        if code in {"bad_address", "bad_input"}:
            raise PageError(code, "invalid page or document position")
        if code == "engine_timeout":
            raise PageError(code, "the page engine timed out", HTTPStatus.GATEWAY_TIMEOUT)
        if code == "capability_unavailable":
            raise PageError(code, "the page engine is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
        raise PageError("render_failed", "the page engine could not complete the request",
                        HTTPStatus.UNPROCESSABLE_ENTITY)
    # rt_doc exposes a short digest, while the session records the full SHA-256.
    if result["rev"] != rev[:12]:
        raise _stale()
    return result


@dataclass
class RenderQueue:
    latest: int
    active: bool = False


class PageGateway:
    def __init__(self):
        self._ready = Condition()
        self._sequence = count(1)
        self._renders: dict[tuple[Path, str], RenderQueue] = {}

    @contextmanager
    def _render_turn(self, key):
        def superseded():
            return PageError("render_superseded", "a newer render was requested", HTTPStatus.CONFLICT)

        with self._ready:
            seq = next(self._sequence)
            queue = self._renders.setdefault(key, RenderQueue(seq))
            queue.latest = seq
            self._ready.notify_all()
            self._ready.wait_for(lambda: not queue.active or queue.latest != seq)
            if queue.latest != seq:
                raise superseded()
            queue.active = True
        try:
            yield seq
            with self._ready:
                if queue.latest != seq:
                    raise superseded()
        finally:
            with self._ready:
                queue.active = False
                if queue.latest == seq:
                    del self._renders[key]
                self._ready.notify_all()

    def read(self, root, tools, operation, body):
        session_id, rev, args = _params(operation, body)
        root = root.resolve()
        try:
            head = _head(root, session_id, rev)
            if operation == "render":
                with self._render_turn((root, session_id)) as seq:
                    result, png = self._render(head, tools, **args)
                    _head(root, session_id, rev)
            else:
                seq = next(self._sequence)
                result, png = self._read(head, operation, args), None
                _head(root, session_id, rev)
        except RpcError as exc:
            if exc.code == "candidate_hash_mismatch":
                raise _stale() from None
            if exc.code == "page_out_of_range":
                raise PageError(exc.code, "page does not exist") from None
            raise PageError("render_failed", "the session document could not be read",
                            HTTPStatus.UNPROCESSABLE_ENTITY) from None
        return {**result, "rev": rev, "seq": seq}, png

    @staticmethod
    def _uses_engine(head):
        return head.path.suffix.lower() in {".hwp", ".hwpx"} and rt_doc.engine_status()["available"]

    def _read(self, head, operation, args):
        if not self._uses_engine(head):
            if operation == "pages":
                return {"source": "fallback", "count": None, "pages": [], "approx": []}
            raise PageError("capability_unavailable", "page geometry needs the document engine",
                            HTTPStatus.SERVICE_UNAVAILABLE)
        if operation == "pages":
            result = _engine_result(rt_doc.pages(head.path), head.rev)
            return {"source": "engine", **{key: result[key] for key in ("count", "pages", "approx")}}
        handler = {"geometry": rt_doc.geometry, "hit": rt_doc.hit_test, "caret": rt_doc.caret_rect}
        result = _engine_result(handler[operation](head.path, **args), head.rev)
        return {key: value for key, value in result.items() if key not in {"ok", "rev"}}

    def _render(self, head, tools, page, scale):
        if self._uses_engine(head):
            info = _engine_result(rt_doc.pages(head.path), head.rev)
            with TemporaryDirectory(prefix="rigorloom-page-") as output:
                result = _engine_result(rt_doc.render(head.path, page, scale=scale, out_dir=output), head.rev)
                image = result["pages"][0]
                png = Path(image["file"]).read_bytes()
                return {"source": "engine", "page": page, "count": info["count"], "approx": bool(info["approx"]),
                        "widthPt": image["width_pt"], "heightPt": image["height_pt"]}, png

        dpi = max(MIN_RENDER_DPI, round(72 * scale))
        result = rt_render.render_page(head.session, page=page - 1, dpi=dpi,
                                       run_id=head.run_id, inline=False, tools=tools, confine=head.confine)
        if not result["available"]:
            if (result.get("own") or {}).get("reason") == "render_failed":
                raise PageError("render_failed", "the fallback renderer could not draw the page",
                                HTTPStatus.UNPROCESSABLE_ENTITY)
            return {"source": "projection", "page": page}, None
        path = head.session.dir / result["image"]["path"]
        head.confine(path)
        png = path.read_bytes()
        return {"source": result["grade"], "page": page, "count": result["pageCount"],
                **result["pageSize"]}, png


def register_routes(router):
    gateway = PageGateway()

    def handler(operation, is_query):
        def read(bridge, params):
            try:
                if is_query:
                    # Repeated values survive parsing and are refused as a list.
                    params = {key: values[0] if len(values) == 1 else values
                              for key, values in params.items()}
                payload, png = gateway.read(bridge.current_root(), EngineTools(bridge.engine_root),
                                            operation, params)
            except PageError as exc:
                raise router.BridgeError(exc.code, str(exc), status=exc.status) from None
            if png is None:
                return payload
            headers = {"X-Rigorloom-Page": str(payload["page"]),
                       "X-Rigorloom-Rev": payload["rev"],
                       "X-Rigorloom-Seq": str(payload["seq"]),
                       "X-Rigorloom-Source": payload["source"],
                       "X-Rigorloom-Width-Pt": str(payload["widthPt"]),
                       "X-Rigorloom-Height-Pt": str(payload["heightPt"])}
            if "count" in payload:
                headers["X-Rigorloom-Page-Count"] = str(payload["count"])
            if payload.get("approx"):
                headers["X-Rigorloom-Approx"] = "1"
            return router.Bytes(png, "image/png", headers)
        return read

    for operation in FIELDS:
        is_query = operation not in {"hit", "caret"}
        register = router.get if is_query else router.post
        register(f"/api/doc/{operation}", handler(operation, is_query))


_native_gateway = PageGateway()


def native_page_view(root, tools, params):
    """The packaged editor uses the same page service via its host sidecar."""
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in FIELDS:
        raise RpcError("invalid_params", "unknown page operation")
    try:
        payload, png = _native_gateway.read(
            root, tools, operation, {key: value for key, value in params.items() if key != "operation"},
        )
    except PageError as exc:
        raise RpcError(exc.code, str(exc)) from None
    if png is not None:
        if len(png) > MAX_INLINE_IMAGE_BYTES:
            raise RpcError("render_failed", "page image exceeds the sidecar frame limit")
        payload["png"] = base64.b64encode(png).decode("ascii")
    return payload
