"""Use rigorloom's discovered soffice command and PyMuPDF for web previews."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


class RenderError(RuntimeError):
    """The local renderer could not produce a usable PDF preview."""


@dataclass(frozen=True)
class PreviewResult:
    renderer: str
    pdf_path: Path
    image_path: Path
    page_count: int
    render_ms: float
    raster_ms: float
    total_ms: float
    stdout_tail: str
    stderr_tail: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["pdf_path"] = str(self.pdf_path)
        payload["image_path"] = str(self.image_path)
        return payload


class SofficeRenderer:
    def __init__(self, argv_template: list[str], *, name: str, timeout: float = 120.0):
        if not argv_template or "{in}" not in argv_template or "{outdir}" not in argv_template:
            raise ValueError("renderer argv must contain {in} and {outdir} tokens")
        self.argv_template = list(argv_template)
        self.name = name
        self.timeout = timeout

    def command(self, document: Path, output_dir: Path) -> list[str]:
        replacements = {"{in}": str(document.resolve()), "{outdir}": str(output_dir.resolve())}
        return [replacements.get(token, token) for token in self.argv_template]

    def render(self, document: Path, output_dir: Path) -> PreviewResult:
        document = Path(document).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{document.stem}.pdf"
        if pdf_path.exists():
            pdf_path.unlink()
        started = time.perf_counter()
        argv = self.command(document, output_dir)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RenderError(f"{self.name} failed to launch: {exc}") from exc
        render_ms = (time.perf_counter() - started) * 1000
        if completed.returncode != 0 or not pdf_path.is_file():
            detail = ((completed.stderr or "") + "\n" + (completed.stdout or ""))[-1200:]
            raise RenderError(
                f"{self.name} did not produce {pdf_path.name} "
                f"(exit {completed.returncode}): {detail.strip()}"
            )

        raster_started = time.perf_counter()
        try:
            import fitz

            with fitz.open(pdf_path) as pdf:
                if pdf.page_count < 1:
                    raise RenderError("rendered PDF has no pages")
                image_path = output_dir / f"{document.stem}-page-1.png"
                pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                pixmap.save(image_path)
                page_count = pdf.page_count
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"PyMuPDF could not rasterize the preview: {exc}") from exc
        raster_ms = (time.perf_counter() - raster_started) * 1000
        total_ms = (time.perf_counter() - started) * 1000
        return PreviewResult(
            renderer=self.name,
            pdf_path=pdf_path,
            image_path=image_path,
            page_count=page_count,
            render_ms=round(render_ms, 3),
            raster_ms=round(raster_ms, 3),
            total_ms=round(total_ms, 3),
            stdout_tail=(completed.stdout or "")[-1000:],
            stderr_tail=(completed.stderr or "")[-1000:],
        )


def discover_soffice(repo_root: Path) -> tuple[SofficeRenderer | None, dict]:
    """Run the repo's capability probe and select its first soffice renderer."""
    repo_root = Path(repo_root).resolve()
    probe_script = repo_root / "pipeline" / "scripts" / "render_probe.py"
    if not probe_script.is_file():
        return None, {"ok": False, "reason": "render_probe_missing"}
    try:
        completed = subprocess.run(
            [sys.executable, str(probe_script), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
            shell=False,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return None, {"ok": False, "reason": "render_probe_failed", "error": str(exc)}
    renderers = payload.get("renderers", []) if isinstance(payload, dict) else []
    selected = next(
        (
            item for item in renderers
            if isinstance(item, dict)
            and item.get("name") in {"soffice_local", "soffice_wsl"}
            and isinstance(item.get("argv"), list)
        ),
        None,
    )
    if selected is None:
        return None, {"ok": False, "reason": "soffice_unavailable", "probe": payload}
    return (
        SofficeRenderer(selected["argv"], name=selected["name"]),
        {"ok": True, "selected": selected["name"], "probe": payload},
    )


def environment_summary(renderer: SofficeRenderer | None) -> dict:
    try:
        import fitz
        fitz_version = fitz.VersionBind
    except Exception:
        fitz_version = None
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "pymupdf": fitz_version,
        "renderer": renderer.name if renderer else None,
        "renderer_argv": renderer.argv_template if renderer else None,
    }
