# -*- coding: utf-8 -*-
"""Card 3: run-scoped edit with a revision / run / UTF-16 source-map.

These cases fail on the #330 revision-coherence tip (still refuses wrapped
lines and any multi-run paragraph) and pass after the run-map is wired
through prepare/commit. They do not exercise own_render IoU or rematch.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent / "desktop_run_scoped_edit_harness.cjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"


def test_prepare_no_longer_refuses_every_multi_run_paragraph():
    """The #221/#330 helper refused as soon as readRegion returned >1 run."""
    text = (REPO / "desktop" / "src" / "revision.ts").read_text(encoding="utf-8")
    assert "if (runs.length > 1)" not in text
    assert "locateSpanInRuns" in text
    assert "cross_run" in text
    assert 'offsetUnit' in text


def test_run_map_declares_utf16_and_does_not_flatten():
    text = (REPO / "desktop" / "src" / "run_map.ts").read_text(encoding="utf-8")
    assert 'OFFSET_UNIT = "utf-16"' in text
    assert "cross_run" in text
    assert "utf16_split" in text
    assert "replace_paragraph_text" not in text
    assert "join(" in text  # concatenation is a cross-run detector / caret map
    assert "caret" in text


def test_prepare_passes_caret_into_run_map():
    text = (REPO / "desktop" / "src" / "revision.ts").read_text(encoding="utf-8")
    assert "locateSpanInRuns(args.spanText, runs, args.caret)" in text
    assert "args.caret - located.spanOffset" in text


def test_run_scoped_edit_harness():
    if not TSC.is_dir():
        pytest.skip("desktop TypeScript is not installed")
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
