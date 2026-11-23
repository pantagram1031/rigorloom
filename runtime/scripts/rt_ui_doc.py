"""Revision-bound page reads for the editor's document canvas."""
from __future__ import annotations

import base64
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from itertools import count
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Condition
import time
from uuid import uuid4

try:
    from . import rt_apply, rt_doc, rt_font_install, rt_own, rt_render
    from .rt_codes import MAX_INLINE_IMAGE_BYTES, MIN_RENDER_DPI, RpcError
    from .rt_engine import EngineTools
    from .rt_session import Session, sha256_file
except ImportError:
    import rt_apply
    import rt_doc
    import rt_font_install
    import rt_own
    import rt_render
    from rt_codes import MAX_INLINE_IMAGE_BYTES, MIN_RENDER_DPI, RpcError
    from rt_engine import EngineTools
    from rt_session import Session, sha256_file


MAX_SCALE = 3
PREVIEW_LIMIT = 128
PREVIEW_TTL = 300
IMAGE_TTL = 60
NATIVE_PREVIEW_BYTES = 16 * 1024
CELL_ADDRESS = re.compile(r"t[0-9]+/r[0-9]+/c[0-9]+")
PARA_ADDRESS = re.compile(r"p[0-9]+")
FIELDS = {
    "pages": set(),
    "fonts": {"faces", "source", "refresh"},
    "render": {"page", "scale"},
    "geometry": {"page"},
    "preview": {"ops"},
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
    required = FIELDS[operation] | {"sessionId", "rev"}
    optional = {"previewId"} if operation in {"render", "geometry"} else set()
    if operation == "render":
        optional.add("refreshFonts")
    if not required <= body.keys() or body.keys() - required - optional:
        raise PageError("invalid_params", "unexpected or missing page request fields")
    session_id, rev = body["sessionId"], body["rev"]
    if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise PageError("invalid_params", "sessionId must be a session identifier")
    if not isinstance(rev, str) or not re.fullmatch(r"[a-f0-9]{64}", rev):
        raise PageError("invalid_params", "rev must be a document digest")
    args = {}
    if operation == "fonts":
        faces, source, refresh = body["faces"], body["source"], body["refresh"]
        if (not isinstance(faces, list) or len(faces) > rt_font_install.MAX_FACES
                or any(not isinstance(face, str) or len(face) > rt_font_install.MAX_FACE_LENGTH for face in faces)
                or source not in ("engine", "own-uncertified", "projection", "pdf", "hancom")
                or type(refresh) is not bool):
            raise PageError("invalid_params", "invalid font request")
        args.update(faces=faces, source=source, refresh=refresh)
    if "refreshFonts" in body:
        if body["refreshFonts"] != "1":
            raise PageError("invalid_params", "invalid font refresh flag")
        args["refresh_fonts"] = True
    if "page" in body:
        if isinstance(body["page"], list) or "," in str(body["page"]):
            raise PageError("page_limit", "a page request accepts one page")
        args["page"] = _integer(body["page"], "page", 1)
    if operation == "render":
        scale = _number(body["scale"], "scale")
        if not 0 < scale <= MAX_SCALE:
            raise PageError("scale_limit", "render scale must be above zero and at most 3")
        args["scale"] = scale
    if "previewId" in body:
        preview_id = body["previewId"]
        if not isinstance(preview_id, str) or not re.fullmatch(r"[a-f0-9]{32}", preview_id):
            raise PageError("invalid_params", "previewId must be a preview identifier")
        args["preview_id"] = preview_id
    if operation == "preview":
        ops = body["ops"]
        if not isinstance(ops, list) or not 1 <= len(ops) <= PREVIEW_LIMIT:
            raise PageError("invalid_params", "preview requires a bounded list of text edits")
        for op in ops:
            if not isinstance(op, dict) or not isinstance(op.get("at"), str) or not isinstance(op.get("text"), str):
                raise PageError("invalid_params", "invalid preview text edit")
            at = op["at"]
            if (set(op) == {"at", "text"} and CELL_ADDRESS.fullmatch(at)):
                continue
            if (set(op) != {"at", "run", "before", "text"} or not PARA_ADDRESS.fullmatch(at) or
                    type(op["run"]) is not int or op["run"] < 0 or not isinstance(op["before"], str)):
                raise PageError("invalid_params", "invalid preview text edit")
        args["ops"] = ops
    return session_id, rev, args


def _engine_result(result, rev):
    if not result.get("ok"):
        code = result["error"]["code"]
        if code == "stale":
            raise _stale()
        if code in {"bad_address", "bad_input"}:
            raise PageError(code, "invalid page or document position")
        if code == "engine_timeout":
            raise PageError(code, "the page engine timed out", HTTPStatus.GATEWAY_TIMEOUT)
        if code == "capability_unavailable":
            raise PageError(code, "the page engine is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
        raise PageError("render_failed", "the page engine could not complete the request",
                        HTTPStatus.UNPROCESSABLE_ENTITY)
    # rt_doc exposes a short digest, while the session records the full SHA-256.
    if rev is not None and result["rev"] != rev[:12]:
        raise _stale()
    return result


@dataclass
class RenderQueue:
    latest: int
    active: bool = False


@dataclass(frozen=True)
class Preview:
    id: str
    session_dir: Path
    base: str
    path: Path
    rev: str
    count: int
    pages: frozenset[int]
    changed: list
    targets: list
    addresses: dict
    expires: float


def _queue_form(text):
    """Run text without U+3000 and newlines, the two inline elements the queue path drops."""
    return text.replace("\u3000", "").replace("\n", "")


def changed_region(old, new):
    """Return (prefix_len, old_end, new_end) for the changed region of old vs new.

    Aligns by common prefix p and common suffix s, capping s so p + s never
    exceeds min(len(old), len(new)). Changed region in old is [p, old_end),
    in new is [p, new_end), where old_end = len(old) - s and new_end = len(new) - s.
    """
    n_old, n_new = len(old), len(new)
    limit = min(n_old, n_new)
    p = 0
    while p < limit and old[p] == new[p]:
        p += 1
    s = 0
    max_s = limit - p
    while s < max_s and old[n_old - 1 - s] == new[n_new - 1 - s]:
        s += 1
    return p, n_old - s, n_new - s


def _queued_run_edit(core_run, new_text):
    """Map a queue-form run edit onto the changed range [start, end) of a doc-core run."""
    old = _queue_form(core_run)
    new = _queue_form(new_text)
    p, old_end, new_end = changed_region(old, new)
    pos = [i for i, ch in enumerate(core_run) if ch not in ("\u3000", "\n")]
    if p < old_end:
        c_start, c_end = pos[p], pos[old_end - 1] + 1
    elif not pos:
        c_start = c_end = len(core_run)
    elif p == len(pos):
        c_start = c_end = pos[-1] + 1
    else:
        c_start = c_end = pos[p]
    return c_start, c_end, new[p:new_end]


class PageGateway:
    def __init__(self):
        self._ready = Condition()
        self._sequence = count(1)
        self._renders: dict[tuple[Path, str], RenderQueue] = {}
        self._previews: OrderedDict[str, Preview] = OrderedDict()

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
            if operation in {"render", "preview"}:
                with self._render_turn((root, session_id)) as seq:
                    if operation == "preview":
                        result, png = self._preview(head, **args), None
                    else:
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

    def _preview(self, head, ops):
        if not self._uses_engine(head):
            raise PageError("capability_unavailable", "preview needs the document engine",
                            HTTPStatus.SERVICE_UNAVAILABLE)
        # Translate queued paragraph runs to doc-core character ranges on the
        # same head that was used to choose the run.
        addresses = _engine_result(rt_doc.queue_addresses(head.path), head.rev)["addresses"]
        core_addresses = {value: key for key, value in addresses.items()}
        edits = []
        targets = []
        paragraphs = {}
        for op in ops:
            base_at, sep, tail = op["at"].partition("/")
            if base_at not in core_addresses:
                raise PageError("bad_address", "the queued text target is unavailable")
            at = core_addresses[base_at] + sep + tail
            targets.append(at)
            text = op["text"]
            if "run" in op:
                if at not in paragraphs:
                    read = _engine_result(rt_doc.read(head.path, at, with_runs=True), head.rev)
                    paragraphs[at] = read["blocks"][0]
                block = paragraphs[at]
                runs = [run["text"] for run in block["runs"]]
                idx = op["run"]
                # The queue path strips inline <hp:fwSpace/> and <hp:lineBreak/> tags
                # when reading run text, while doc-core reads them as U+3000 and "\n".
                # Narrow the doc-core replacement range to the changed region in queue
                # form so inline elements outside the changed region survive, matching apply.
                if (idx >= len(runs)
                        or _queue_form(runs[idx]) != _queue_form(op["before"])
                        or "".join(runs) != block["text"]):
                    raise PageError("bad_address", "the queued run no longer matches the document")
                start = sum(map(len, runs[:idx]))
                c_start, c_end, text = _queued_run_edit(runs[idx], text)
                at = f"{at}:{start + c_start}-{start + c_end}"
            edits.append({"op": "set", "at": at, "text": text})
        # rt_doc snapshots the session head and writes the edit to its own private scratch.
        result = _engine_result(rt_doc.edit(head.path, edits,
                                            base=head.rev[:12], preview=True), None)
        if result["rev_before"] != head.rev[:12]:
            raise _stale()
        path = Path(result["out"])
        info = _engine_result(rt_doc.pages(path), result["rev"])
        changed = result["changed"]
        pages = frozenset(page for page in (*result["changed_pages"], *(row["page"] for row in changed))
                          if type(page) is int and 1 <= page <= info["count"])
        remap = {item["from"]: item["to"] for item in result["remap"]}
        targets = [rt_doc.follow_remap(remap, at) for at in targets]
        preview_addresses = {mapped: at for core, at in addresses.items()
                             if (mapped := rt_doc.follow_remap(remap, core)) is not None}
        preview = Preview(uuid4().hex, head.session.dir, head.rev, path, result["rev"], info["count"],
                          pages, changed, targets, preview_addresses, time.monotonic() + PREVIEW_TTL)
        with self._ready:
            self._previews[preview.id] = preview
            while len(self._previews) > PREVIEW_LIMIT:
                self._previews.popitem(last=False)
        return {"previewId": preview.id, "previewRev": preview.rev, "count": preview.count,
                "changedPages": sorted(preview.pages), "changed": changed}

    def _get_preview(self, head, preview_id, page):
        if preview_id is None:
            return None
        with self._ready:
            preview = self._previews.get(preview_id)
        if (preview is None or preview.session_dir != head.session.dir or preview.base != head.rev
                or preview.expires < time.monotonic() or not preview.path.is_file()):
            raise PageError("preview_expired", "the page preview is unavailable", HTTPStatus.NOT_FOUND)
        if page not in preview.pages:
            raise PageError("page_unchanged", "the page is outside the preview's changed set")
        return preview

    @staticmethod
    def _uses_engine(head):
        return head.path.suffix.lower() in {".hwp", ".hwpx"} and rt_doc.engine_status()["available"]

    def _fonts(self, head, faces, source, refresh):
        if source == "engine" and self._uses_engine(head):
            result = _engine_result(rt_doc.page_font_substitutions(head.path, refresh=refresh), head.rev)
            substitutions = result["fonts"]["substituted"]
        elif source == "own-uncertified":
            record = rt_own.any_own_for(head.session, subject_sha256=head.rev, confine=head.confine, latest=True)
            if record is None:
                substitutions = []
            else:
                fonts = rt_own.font_summary(rt_own.read_sidecar(head.session, record), include_bundled=True)
                substitutions = [{"want": row["declared"], "got": row["drawnWith"]}
                                 for row in fonts.get("substituted", [])]
        elif source == "projection":
            substitutions = [{"want": name, "got": None} for name in faces]
        else:
            substitutions = []
        return {"faces": rt_font_install.substitution_states(substitutions)}

    def _read(self, head, operation, args):
        if operation == "fonts":
            return self._fonts(head, **args)
        if not self._uses_engine(head):
            if operation == "pages":
                return {"source": "fallback", "count": None, "pages": [], "approx": []}
            raise PageError("capability_unavailable", "page geometry needs the document engine",
                            HTTPStatus.SERVICE_UNAVAILABLE)
        if operation == "pages":
            result = _engine_result(rt_doc.pages(head.path), head.rev)
            return {"source": "engine", **{key: result[key] for key in ("count", "pages", "approx")}}
        page = args["page"]
        preview = self._get_preview(head, args.get("preview_id"), page)
        result = _engine_result(rt_doc.geometry(preview.path if preview else head.path, page),
                                preview.rev if preview else head.rev)
        payload = {key: value for key, value in result.items() if key not in {"ok", "rev"}}
        addresses = (preview.addresses if preview else
                     _engine_result(rt_doc.queue_addresses(head.path), head.rev)["addresses"])
        for box in payload["boxes"]:
            at = box["at"] or ""
            if at.startswith("t") and "/r" in at:
                base_at, tail = at.rsplit("/r", 1)
                suffix = "/r" + tail
            else:
                base_at, sep, tail = at.partition("#")
                suffix = sep + tail
            if base_at in addresses:
                box["queueAddress"] = addresses[base_at] + suffix
        if preview:
            changed = [row for row in preview.changed if row["page"] == page and row["rect"]]
            measured = {row["i"] for row in changed}
            # Some engine versions return the affected page without an edit rect.
            # Use the actual target box on that page when available.
            boxes = defaultdict(list)
            for box in result["boxes"]:
                if box["at"] and box["kind"] in {"para", "cell"}:
                    boxes[box["at"]].append(box["rect"])
            for i, at in enumerate(preview.targets):
                if i not in measured:
                    changed.extend({"i": i, "page": page, "rect": rect} for rect in boxes.get(at, []))
            payload.update(previewId=preview.id, previewRev=preview.rev, changed=changed)
        return payload

    def _render(self, head, tools, page, scale, preview_id=None, refresh_fonts=False):
        preview = self._get_preview(head, preview_id, page)
        if self._uses_engine(head):
            path, rev = (preview.path, preview.rev) if preview else (head.path, head.rev)
            info = _engine_result(rt_doc.pages(path), rev)
            with TemporaryDirectory(prefix="rigorloom-page-") as output:
                # Hand the engine the canonical directory: the temp root can be
                # a link or, on Windows, an 8.3 short name, and the containment
                # check compares canonical paths.
                output_dir = Path(output).resolve()
                result = _engine_result(rt_doc.render(path, page, scale=scale, out_dir=str(output_dir)), rev)
                image = result["pages"][0]
                image_path = Path(image["file"])
                _confined(output_dir, image_path)
                png = image_path.read_bytes()
            payload = {"source": "engine", "page": page, "count": info["count"], "approx": bool(info["approx"]),
                       "widthPt": image["width_pt"], "heightPt": image["height_pt"]}
            if preview:
                payload.update(previewId=preview.id, previewRev=preview.rev)
            return payload, png

        if preview:
            raise PageError("capability_unavailable", "preview needs the document engine",
                            HTTPStatus.SERVICE_UNAVAILABLE)

        dpi = max(MIN_RENDER_DPI, round(72 * scale))
        result = rt_render.render_page(head.session, page=page - 1, dpi=dpi,
                                       run_id=head.run_id, inline=False, tools=tools, confine=head.confine,
                                       refresh_fonts=refresh_fonts)
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
            if "previewId" in payload:
                headers["X-Rigorloom-Preview-Id"] = payload["previewId"]
                headers["X-Rigorloom-Preview-Rev"] = payload["previewRev"]
            return router.Bytes(png, "image/png", headers)
        return read

    for operation in FIELDS:
        is_query = operation not in {"preview", "fonts"}
        register = router.get if is_query else router.post
        register(f"/api/doc/{operation}", handler(operation, is_query))


_native_gateway = PageGateway()


def _native_render_dir(head):
    directory = head.session.renders_dir / "page-view"
    head.confine(directory)
    return directory


def _native_image(root, params):
    if set(params) != {"operation", "sessionId", "rev", "imageId", "offset"}:
        raise PageError("invalid_params", "invalid page image request")
    session_id, rev, _ = _params("pages", {key: params[key] for key in ("sessionId", "rev")})
    image_id = params["imageId"]
    match = re.fullmatch(r"([0-9]{1,15})-[a-f0-9]{32}", image_id) if isinstance(image_id, str) else None
    if not match:
        raise PageError("invalid_params", "imageId must be a page image identifier")
    offset = _integer(params["offset"], "offset", 0)
    head = _head(root.resolve(), session_id, rev)
    directory = _native_render_dir(head)
    path = directory / f"{rev}-{image_id}.png"
    _confined(directory, path)
    try:
        with path.open("rb") as image:
            if time.time() - path.stat().st_mtime > IMAGE_TTL:
                raise _missing()
            image.seek(offset)
            chunk = image.read(MAX_INLINE_IMAGE_BYTES)
    except OSError:
        raise _missing() from None
    _head(root.resolve(), session_id, rev)
    return {"rev": rev, "seq": int(match[1]), "offset": offset, "png": base64.b64encode(chunk).decode("ascii")}


def native_page_view(root, tools, params):
    """The packaged editor uses the same page service via its host sidecar."""
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in FIELDS.keys() | {"image"}:
        raise RpcError("invalid_params", "unknown page operation")
    try:
        if operation == "image":
            return _native_image(root, params)
        if operation == "preview" and len(json.dumps(params, ensure_ascii=False).encode()) > NATIVE_PREVIEW_BYTES:
            raise PageError("body_too_large", "the preview request exceeds the page request limit",
                            HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        payload, png = _native_gateway.read(
            root, tools, operation, {key: value for key, value in params.items() if key != "operation"},
        )
        if png is not None:
            head = _head(root.resolve(), params["sessionId"], payload["rev"])
            directory = _native_render_dir(head)
            directory.mkdir(exist_ok=True)
            for path in directory.glob("*.png"):
                if time.time() - path.stat(follow_symlinks=False).st_mtime > IMAGE_TTL:
                    path.unlink(missing_ok=True)
            image_id = f"{payload['seq']}-{uuid4().hex}"
            path = directory / f"{head.rev}-{image_id}.png"
            with path.open("xb") as image:
                image.write(png)
            payload.update(imageId=image_id, imageBytes=len(png))
    except PageError as exc:
        raise RpcError(exc.code, str(exc)) from None
    except OSError:
        raise RpcError("render_failed", "the page image could not be stored") from None
    return payload
