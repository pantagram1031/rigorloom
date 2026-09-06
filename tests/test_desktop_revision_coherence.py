# -*- coding: utf-8 -*-
"""Public overlay-click lease: superseded work is a no-op.

Runs the Desktop TypeScript revision helper with controlled replies. The
cases fail on the PR #221 tip before the prepare/commit split and pass after.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent / "desktop_revision_coherence_harness.cjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"


def test_public_click_does_not_reintroduce_helper_refusal_as_a_write():
    """The #254 caller bug: clickOverlaySpan used to await beginParagraphEdit
    and turn any refusal into an overlay/selection write."""
    text = (REPO / "desktop" / "src" / "actions.ts").read_text(encoding="utf-8")
    start = text.index("export async function clickOverlaySpan")
    end = text.index("export async function chooseCandidate")
    body = text[start:end]
    assert "await beginParagraphEdit(span" not in body
    assert "applyOverlayParagraphCommit(effect)" in body
    assert "bumpEditIntent()" in body


def test_superseded_click_does_not_clobber_current_selection():
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
