#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Page rasters, and an honest account of when there cannot be one.

WHAT CAN PRODUCE A PAGE IMAGE TODAY, WITHOUT COM — the reality check this
module is built on rather than around:

  * A PDF can be rasterised offline, if PyMuPDF is importable. It is an
    OPTIONAL dependency (``pyproject.toml`` lists ``pymupdf`` only under the
    ``studio`` and ``engine`` extras), so it is imported lazily inside the call
    and its absence is a reported state, never an import error at startup.
  * An HWPX cannot become a PDF in THIS module. Conversion is Hancom COM,
    and it lives one door along in ``rt_convert``, behind the host-only
    ``document/renderPrepare``: a human clicks, a bounded child runs
    ``engine/scripts/com_backend.py convert`` against the session COPY, and
    the resulting PDF becomes something this module can read. Until somebody
    does that, an HWPX session has no page image and says so.

So ``document/render`` returns a raster when the session already HAS a PDF —
because the opened document is one, or because a candidate run produced one —
and otherwise returns a structured unavailable state naming what is missing.
There is no fabricated layout, no approximate page box drawn from
``page_metrics``, and no "preview" that is really a guess. A form scan knows a
page's margins; it does not know what the page looks like.

A RASTER IS NOT EVIDENCE. Every successful result carries
``evidence.class = "structural_only"`` and ``proofGrade: "none"``, using
``engine/scripts/document_evidence.py``'s closed vocabularies (:40 and :780).
Rendering bytes tells you what they draw, not that they are the right bytes;
proof stays where ``derive_proof_grade`` put it.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    DEFAULT_RENDER_DPI,
    MAX_INLINE_IMAGE_BYTES,
    MAX_RENDER_DPI,
    MIN_RENDER_DPI,
    RpcError,
)
from rt_session import atomic_write_bytes, sha256_file  # noqa: E402

#: Import candidates for the rasteriser, newest name first. PyMuPDF ships both.
RASTERIZER_MODULES = ("pymupdf", "fitz")

#: Suffixes this module can rasterise. Deliberately short: it is a PDF reader,
#: not a format zoo.
RASTERIZABLE_SUFFIXES = (".pdf",)

#: Why a session has no page image. One closed set, so the Desktop can switch
#: on it exhaustively instead of matching on prose.
UNAVAILABLE_REASONS = (
    "rasterizer_missing",       # no PyMuPDF in this interpreter
    "no_rasterizable_artifact",  # nothing here is a PDF
    "needs_conversion",         # an hwpx/hwp that a converter could turn into one
    "artifact_missing",         # a runId was named and its bytes are gone
)

#: Same three-state style as ``pipeline/scripts/render_probe.py:22``.
CAPABILITY_STATES = ("yes", "no", "unknown")


def rasterizer_module():
    """Import the rasteriser, or return None. Never raises, never at startup."""
    for name in RASTERIZER_MODULES:
        if importlib.util.find_spec(name) is None:
            continue
        try:
            return __import__(name)
        except Exception:  # noqa: BLE001 - a broken optional dep is "absent"
            continue
    return None


def rasterizer_facts() -> dict:
    """Cheap. A ``find_spec``, not a probe, so it can sit on the hot path."""
    for name in RASTERIZER_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is not None:
            return {"state": "yes", "module": name,
                    "reason": None, "formats": list(RASTERIZABLE_SUFFIXES)}
    return {"state": "no", "module": None,
            "reason": ("PyMuPDF is not importable in this interpreter; it is an "
                       "optional dependency (pyproject extras: studio, engine)"),
            "formats": []}


def render_capability() -> dict:
    """The ``capabilities.render`` block. No subprocess, no probe, no wait.

    The converter row is flatly ``no`` and says why: this build calls no
    converter, whatever the machine happens to have installed. A caller that
    wants the machine's inventory asks ``capabilities/list`` with
    ``probeRenderers: true``, which runs ``render_probe`` in a bounded child —
    an explicit, opt-in ~8 second call, never something ``initialize`` pays for.
    """
    from rt_convert import prepare_capability

    return {
        "rasterizer": rasterizer_facts(),
        "prepare": prepare_capability(),
        "converter": {
            "state": "no",
            "reason": ("document/render itself converts nothing: it needs a "
                       "PDF that already exists. document/renderPrepare is the "
                       "host-only step that can make one, where Hancom is "
                       "installed — see the prepare row"),
            "wouldNeed": ["a PDF artifact in the session",
                          "or document/renderPrepare on a machine with Hancom"],
        },
        "evidence": {
            "class": "structural_only",
            "proofGrade": "none",
            "note": ("a page image is a view of bytes, not evidence about them; "
                     "proof stays with document_evidence.derive_proof_grade"),
        },
        "unavailableReasons": list(UNAVAILABLE_REASONS),
    }


def _unavailable(session, reason: str, detail: str, **extra) -> dict:
    assert reason in UNAVAILABLE_REASONS, reason
    return {
        "sessionId": session.id,
        "available": False,
        "unavailable": {"reason": reason, "detail": detail, **extra},
        "capability": render_capability(),
    }


def resolve_artifact(session, run_id: str | None) -> tuple[Path | None, str, dict]:
    """(path, kind, facts) for the thing we could rasterise, if anything."""
    if run_id is not None:
        if not isinstance(run_id, str) or not run_id or "/" in run_id or "\\" in run_id:
            raise RpcError("invalid_params", "runId must be a bare identifier",
                           runId=run_id)
        # Read the receipt first: it re-verifies the candidate bytes against
        # their binding (rt_apply.read_receipt), so a raster is never taken from
        # an artifact that drifted after publication.
        from rt_apply import read_receipt
        receipt = read_receipt(session, run_id)
        candidate = receipt["candidate"]
        # A PDF prepared FROM this candidate, if renderPrepare made one and it
        # still binds the candidate's digest. Without this, a candidate render
        # of an HWPX would always answer `needs_conversion` even after the
        # conversion had run — E1.2's 다시 그리기 would have had nowhere to
        # put its result.
        from rt_convert import existing_pdf

        prepared = existing_pdf(session, run_id=run_id,
                                expect_sha256=candidate["sha256"])
        if prepared is not None:
            return (session.dir / prepared["path"], "candidate_prepared",
                    {"runId": run_id, "sha256": prepared["sha256"],
                     "bytes": prepared["bytes"],
                     "producedBy": prepared["producedBy"],
                     "candidateSha256": candidate["sha256"]})
        path = session.candidates_dir / run_id / candidate["path"]
        return path, "candidate", {"runId": run_id, "sha256": candidate["sha256"],
                                   "bytes": candidate["bytes"]}
    source = session.source
    if source.suffix.lower() in RASTERIZABLE_SUFFIXES:
        digest, size = session.meta["sourceSha256"], session.meta["sourceBytes"]
        return source, "session_source", {"sha256": digest, "bytes": size}
    # A PDF prepared from this source by document/renderPrepare, if there is
    # one and it still binds these bytes.
    from rt_convert import existing_pdf

    prepared = existing_pdf(session)
    if prepared is not None:
        return (session.dir / prepared["path"], "prepared",
                {"sha256": prepared["sha256"], "bytes": prepared["bytes"],
                 "producedBy": prepared["producedBy"]})
    digest, size = session.meta["sourceSha256"], session.meta["sourceBytes"]
    return source, "session_source", {"sha256": digest, "bytes": size}


def render_page(session, *, page: int = 0, dpi: int = DEFAULT_RENDER_DPI,
                run_id: str | None = None, inline: bool = True) -> dict:
    """Rasterise one page, or say precisely why there is no page to rasterise."""
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        raise RpcError("invalid_params", "page must be a non-negative integer",
                       page=page)
    if not isinstance(dpi, int) or isinstance(dpi, bool):
        raise RpcError("invalid_params", "dpi must be an integer", dpi=dpi)
    if not MIN_RENDER_DPI <= dpi <= MAX_RENDER_DPI:
        raise RpcError("invalid_params",
                       f"dpi must be between {MIN_RENDER_DPI} and "
                       f"{MAX_RENDER_DPI}", dpi=dpi,
                       min=MIN_RENDER_DPI, max=MAX_RENDER_DPI)

    path, kind, facts = resolve_artifact(session, run_id)
    suffix = path.suffix.lower() if path is not None else ""
    document_kind = session.meta.get("ingress", {}).get("documentKind", "opaque")

    if suffix not in RASTERIZABLE_SUFFIXES:
        if document_kind in ("hwpx",) or suffix in (".hwpx", ".hwp"):
            from rt_convert import prepare_capability

            prepare = prepare_capability()
            return _unavailable(
                session, "needs_conversion",
                ("this session holds an HWPX; a page image needs a PDF. Call "
                 "document/renderPrepare (host) to make one"
                 if prepare["state"] == "yes" else
                 "this session holds an HWPX; a page image needs a PDF, and "
                 "this machine cannot make one: " + str(prepare["reason"])),
                artifactKind=kind, documentKind=document_kind, suffix=suffix,
                prepare=prepare)
        return _unavailable(
            session, "no_rasterizable_artifact",
            f"nothing here is a PDF (the {kind} is {suffix or 'extensionless'})",
            artifactKind=kind, documentKind=document_kind, suffix=suffix)

    if path is None or not path.is_file():
        return _unavailable(session, "artifact_missing",
                            "the artifact named by this request is not on disk",
                            artifactKind=kind)

    module = rasterizer_module()
    if module is None:
        return _unavailable(
            session, "rasterizer_missing",
            "a PDF is present but PyMuPDF is not importable in this "
            "interpreter, so it cannot be rasterised",
            artifactKind=kind, artifact=facts)

    try:
        document = module.open(str(path))
    except Exception as exc:  # noqa: BLE001 - any reader fault is one refusal
        raise RpcError("render_failed", "the PDF could not be opened",
                       detail=f"{type(exc).__name__}: {exc}"[:400]) from exc
    try:
        count = document.page_count
        if page >= count:
            raise RpcError("page_out_of_range",
                           f"page {page} does not exist; the document has "
                           f"{count}", page=page, pageCount=count)
        try:
            loaded = document.load_page(page)
            matrix = module.Matrix(dpi / 72.0, dpi / 72.0)
            pixmap = loaded.get_pixmap(matrix=matrix, alpha=False)
            png = pixmap.tobytes("png")
            box = loaded.rect
            page_size = {"widthPt": round(float(box.width), 2),
                         "heightPt": round(float(box.height), 2)}
        except RpcError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RpcError("render_failed", "the page could not be rasterised",
                           page=page,
                           detail=f"{type(exc).__name__}: {exc}"[:400]) from exc
    finally:
        try:
            document.close()
        except Exception:  # noqa: BLE001
            pass

    # Always write the raster; a path is a stable reference the host can read
    # without pushing a megabyte through a frame.
    target = session.renders_dir / f"{kind}-{run_id or 'source'}-p{page}-{dpi}dpi.png"
    atomic_write_bytes(target, png)
    written_sha, written_bytes = sha256_file(target)

    image = {
        "mediaType": "image/png",
        "widthPx": int(pixmap.width),
        "heightPx": int(pixmap.height),
        "bytes": written_bytes,
        "sha256": written_sha,
        "path": target.relative_to(session.dir).as_posix(),
        "inline": False,
        "inlineLimit": MAX_INLINE_IMAGE_BYTES,
    }
    if inline and written_bytes <= MAX_INLINE_IMAGE_BYTES:
        image["inline"] = True
        image["encoding"] = "base64"
        image["data"] = base64.b64encode(png).decode("ascii")
    elif inline:
        image["reason"] = ("larger than the inline limit; read it from path, or "
                           "ask for a lower dpi")

    return {
        "sessionId": session.id,
        "available": True,
        "source": {"kind": f"{kind}_pdf", **facts},
        "page": page,
        "pageCount": int(count),
        "pageSize": page_size,
        "dpi": dpi,
        "image": image,
        "evidence": render_capability()["evidence"],
    }


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
