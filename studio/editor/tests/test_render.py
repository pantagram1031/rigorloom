from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz

from studio.editor.render import SofficeRenderer
from studio.editor.sample_factory import write_synthetic_hwpx


def test_renderer_substitutes_argv_and_rasterizes_pdf(tmp_path: Path, monkeypatch):
    document = write_synthetic_hwpx(tmp_path / "revision-0001.hwpx")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        out_dir = Path(argv[argv.index("--outdir") + 1])
        pdf = out_dir / "revision-0001.pdf"
        rendered = fitz.open()
        page = rendered.new_page()
        page.insert_text((72, 72), "synthetic preview")
        rendered.save(pdf)
        rendered.close()
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("studio.editor.render.subprocess.run", fake_run)
    renderer = SofficeRenderer([
        "soffice", "--headless", "--convert-to", "pdf", "--outdir",
        "{outdir}", "{in}",
    ], name="soffice-test")

    result = renderer.render(document, tmp_path / "preview")

    assert calls[0][0][-2:] == [str(tmp_path / "preview"), str(document)]
    assert calls[0][1]["shell"] is False
    assert result.pdf_path.is_file()
    assert result.image_path.is_file()
    assert result.page_count == 1
    assert result.renderer == "soffice-test"

