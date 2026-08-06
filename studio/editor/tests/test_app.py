from __future__ import annotations

from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from studio.editor.app import create_app
from studio.editor.render import PreviewResult
from studio.editor.sample_factory import write_synthetic_hwpx


class FakeRenderer:
    name = "fake-soffice"

    def render(self, document: Path, output_dir: Path) -> PreviewResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{document.stem}.pdf"
        image_path = output_dir / f"{document.stem}-page-1.png"
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), document.name)
        pdf.save(pdf_path)
        pixmap = page.get_pixmap()
        pixmap.save(image_path)
        pdf.close()
        return PreviewResult(
            renderer=self.name,
            pdf_path=pdf_path,
            image_path=image_path,
            page_count=1,
            render_ms=10.0,
            raster_ms=2.0,
            total_ms=12.0,
            stdout_tail="",
            stderr_tail="",
        )


def _client(tmp_path: Path) -> TestClient:
    editable = write_synthetic_hwpx(tmp_path / "editable.hwpx")
    equation = write_synthetic_hwpx(tmp_path / "equation.hwpx")
    app = create_app(
        editable,
        equation_fixture=equation,
        data_root=tmp_path / "runtime",
        renderer=FakeRenderer(),
        action_token="test-token",
    )
    return TestClient(app, headers={"host": "localhost"})


def test_state_lists_editable_and_protected_equation_paragraphs(tmp_path: Path):
    with _client(tmp_path) as client:
        response = client.get("/api/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 0
    assert any(item["editable"] for item in payload["paragraphs"])
    assert any(item["has_equation"] for item in payload["equation_hazards"])
    assert payload["preview"]["page_count"] == 1


def test_edit_returns_fidelity_and_new_preview(tmp_path: Path):
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        target = next(item for item in state["paragraphs"] if item["editable"])
        response = client.post(
            f"/api/paragraphs/{target['id']}",
            headers={"X-Studio-Editor-Token": "test-token"},
            json={"text": "Browser accepted edit.", "expected_revision": 0},
        )
        preview = client.get("/api/preview/1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 1
    assert payload["fidelity"]["limited_to_text_payload"] is True
    assert payload["preview"]["renderer"] == "fake-soffice"
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_edit_requires_same_origin_token_and_current_revision(tmp_path: Path):
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        target = next(item for item in state["paragraphs"] if item["editable"])
        missing = client.post(
            f"/api/paragraphs/{target['id']}",
            json={"text": "No token.", "expected_revision": 0},
        )
        accepted = client.post(
            f"/api/paragraphs/{target['id']}",
            headers={"X-Studio-Editor-Token": "test-token"},
            json={"text": "First edit.", "expected_revision": 0},
        )
        stale = client.post(
            f"/api/paragraphs/{target['id']}",
            headers={"X-Studio-Editor-Token": "test-token"},
            json={"text": "Stale edit.", "expected_revision": 0},
        )

    assert missing.status_code == 403
    assert accepted.status_code == 200
    assert stale.status_code == 409

