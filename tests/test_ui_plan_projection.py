"""WP3 UI multi-op plan projection, Vite static bundle, and copy checks."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "tests" / "desktop_plan_projection_harness.cjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"
UI_DIST = REPO / "runtime" / "scripts" / "ui_dist"
DESKTOP_SRC = REPO / "desktop" / "src"

FORBIDDEN_EXTS = {
    ".hwp",
    ".hwpx",
    ".docx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".jsonl",
    ".yaml",
    ".yml",
    ".woff2",
}

FORBIDDEN_LITERALS = [
    "\uc815\ud655\ub3c4 100%",
    "Claude \uae30\ubc18",
    "AI \ud0d0\uc9c0 \ud68c\ud53c",
    "AI \ud2f0 \uc81c\uac70",
    "Astra",
    "Herdr",
    "F:" + "/",
]


def test_ui_plan_projection_harness() -> None:
    """Node TypeScript harness verifies all 4 preedit op projections and safety gates."""
    if not TSC.is_dir():
        pytest.skip("desktop TypeScript is not installed (run npm --prefix desktop ci)")
    completed = subprocess.run(
        [shutil.which("node") or "node", str(HARNESS)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_vite_ui_dist_bundle_constraints() -> None:
    """Built ui_dist must stay small and omit fonts/binary corpus artifacts."""
    if not UI_DIST.is_dir():
        pytest.skip("ui_dist not built yet")
    index_html = UI_DIST / "index.html"
    assert index_html.is_file(), "runtime/scripts/ui_dist/index.html missing"
    total_bytes = 0
    files = [p for p in UI_DIST.rglob("*") if p.is_file()]
    assert files, "ui_dist must not be empty"
    for p in files:
        assert p.suffix.lower() not in FORBIDDEN_EXTS, f"Forbidden suffix in ui_dist: {p}"
        total_bytes += p.stat().st_size
    assert total_bytes < 2 * 1024 * 1024, f"ui_dist too large: {total_bytes} bytes"


def test_no_forbidden_copy_in_desktop_src_or_dist() -> None:
    """Ensure forbidden claims, old brand names, and Windows drive paths are absent."""
    roots = [DESKTOP_SRC]
    if UI_DIST.is_dir():
        roots.append(UI_DIST)
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".woff2", ".png", ".ico"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for bad in FORBIDDEN_LITERALS:
                assert bad not in text, f"Forbidden literal {bad!r} found in {path}"
