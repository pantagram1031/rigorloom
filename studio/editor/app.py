"""Localhost-only FastAPI application for the Phase-1 editor spike."""
from __future__ import annotations

import argparse
import html as html_module
import secrets
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .doc_backend import DocumentBackendError, UnsafeEdit, inspect_paragraphs
from .render import PreviewResult, RenderError, SofficeRenderer, discover_soffice
from .session import DocumentSession, NothingToUndo, RevisionConflict


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


class EditRequest(BaseModel):
    text: str = Field(max_length=20_000)
    expected_revision: int = Field(ge=0)


class UndoRequest(BaseModel):
    expected_revision: int = Field(ge=0)


def _trusted_host(value: str | None) -> bool:
    return bool(value and (value.startswith("127.0.0.1") or value.startswith("localhost")))


def create_app(
    document: Path,
    *,
    equation_fixture: Path | None = None,
    data_root: Path | None = None,
    renderer: SofficeRenderer | None = None,
    action_token: str | None = None,
) -> FastAPI:
    document = Path(document).resolve()
    if not document.is_file():
        raise FileNotFoundError(document)
    fixture = Path(equation_fixture).resolve() if equation_fixture else None
    if fixture is not None and not fixture.is_file():
        raise FileNotFoundError(fixture)
    data_root = Path(data_root or (Path(tempfile.gettempdir()) / "rigorloom-studio-editor"))
    session = DocumentSession(document, data_root / f"session-{uuid.uuid4().hex}")
    token = action_token or secrets.token_urlsafe(24)
    probe = {"ok": True, "selected": getattr(renderer, "name", None), "injected": True}
    if renderer is None:
        renderer, probe = discover_soffice(REPO_ROOT)

    app = FastAPI(title="Rigorloom Studio Editor Spike", version="0.1")
    operation_lock = threading.RLock()
    previews: dict[int, PreviewResult] = {}
    preview_errors: dict[int, str] = {}

    def render_revision(revision: int) -> PreviewResult | None:
        if renderer is None:
            preview_errors[revision] = probe.get("reason", "renderer unavailable")
            return None
        try:
            result = renderer.render(
                session.current_path,
                session.session_dir / "preview" / f"revision-{revision:04d}",
            )
        except RenderError as exc:
            preview_errors[revision] = str(exc)
            return None
        previews[revision] = result
        preview_errors.pop(revision, None)
        return result

    def preview_payload(revision: int) -> dict:
        result = previews.get(revision)
        if result is None:
            return {
                "available": False,
                "revision": revision,
                "error": preview_errors.get(revision),
            }
        return {
            "available": True,
            "revision": revision,
            "renderer": result.renderer,
            "page_count": result.page_count,
            "render_ms": result.render_ms,
            "raster_ms": result.raster_ms,
            "total_ms": result.total_ms,
            "image_url": f"/api/preview/{revision}",
        }

    def require_action(token_header: str | None, host_header: str | None) -> None:
        if token_header != token:
            raise HTTPException(status_code=403, detail="missing or invalid editor token")
        if not _trusted_host(host_header):
            raise HTTPException(status_code=403, detail="untrusted Host header")

    # Render once before serving so the initial page and later revisions share
    # the same measured path. A renderer failure remains visible in /api/state.
    render_revision(0)

    @app.get("/", response_class=HTMLResponse)
    def root():
        page = (HERE / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace(
            "__STUDIO_EDITOR_TOKEN__", html_module.escape(token, quote=True)
        ))

    @app.get("/api/state")
    def state():
        hazards = []
        if fixture is not None:
            hazards = [
                item.to_dict() for item in inspect_paragraphs(fixture) if item.has_equation
            ]
        return {
            "revision": session.revision,
            "paragraphs": [item.to_dict() for item in session.paragraphs()],
            "equation_hazards": hazards,
            "preview": preview_payload(session.revision),
            "renderer_probe": probe,
            "session_model": "single ordered writer",
        }

    @app.post("/api/paragraphs/{paragraph_id}")
    def edit_paragraph(
        paragraph_id: str,
        request: EditRequest,
        x_studio_editor_token: str | None = Header(
            default=None, alias="X-Studio-Editor-Token"
        ),
        host: str | None = Header(default=None),
    ):
        require_action(x_studio_editor_token, host)
        with operation_lock:
            started = time.perf_counter()
            try:
                edit_result = session.edit(
                    paragraph_id=paragraph_id,
                    new_text=request.text,
                    expected_revision=request.expected_revision,
                )
            except RevisionConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except UnsafeEdit as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            edit_ms = (time.perf_counter() - started) * 1000
            preview = render_revision(edit_result.revision)
            cycle_ms = (time.perf_counter() - started) * 1000
            return {
                "revision": edit_result.revision,
                "operation": edit_result.operation,
                "fidelity": edit_result.edit_result.fidelity.to_dict(),
                "preview": preview_payload(edit_result.revision),
                "timings": {
                    "edit_ms": round(edit_ms, 3),
                    "render_ms": preview.render_ms if preview else None,
                    "raster_ms": preview.raster_ms if preview else None,
                    "server_cycle_ms": round(cycle_ms, 3),
                },
            }

    @app.post("/api/undo")
    def undo(
        request: UndoRequest,
        x_studio_editor_token: str | None = Header(
            default=None, alias="X-Studio-Editor-Token"
        ),
        host: str | None = Header(default=None),
    ):
        require_action(x_studio_editor_token, host)
        with operation_lock:
            started = time.perf_counter()
            try:
                undo_result = session.undo(expected_revision=request.expected_revision)
            except RevisionConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except NothingToUndo as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            preview = render_revision(undo_result.revision)
            return {
                "revision": undo_result.revision,
                "operation": undo_result.operation,
                "fidelity": undo_result.edit_result.fidelity.to_dict(),
                "preview": preview_payload(undo_result.revision),
                "timings": {
                    "render_ms": preview.render_ms if preview else None,
                    "raster_ms": preview.raster_ms if preview else None,
                    "server_cycle_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            }

    @app.get("/api/preview/{revision}")
    def preview_image(revision: int):
        result = previews.get(revision)
        if result is None or not result.image_path.is_file():
            raise HTTPException(status_code=404, detail="preview unavailable")
        return FileResponse(
            result.image_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(DocumentBackendError)
    def document_error(_request, exc: DocumentBackendError):
        return HTMLResponse(str(exc), status_code=422)

    app.state.document_session = session
    app.state.action_token = token
    app.state.renderer_probe = probe
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rigorloom Studio editor Phase-1 spike")
    parser.add_argument(
        "--document",
        type=Path,
        default=HERE / "sample_data" / "sanitized-editable.hwpx",
    )
    parser.add_argument(
        "--equation-fixture",
        type=Path,
        default=HERE / "sample_data" / "sanitized-equation-hazard.hwpx",
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(
        args.document,
        equation_fixture=args.equation_fixture,
        data_root=args.data_root,
    )
    print("[studio-editor] localhost-only spike; no model calls")
    print(f"[studio-editor] open http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

