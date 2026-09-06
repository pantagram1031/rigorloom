# -*- coding: utf-8 -*-
"""Same-run sequential edit: the splice base is the text the range was measured on.

Independent review #338, finding 1: ``commitEdit`` spliced into a string other
than the one ``prepareParagraphEdit`` measured ``rangeStart``/``rangeEnd`` on.
The first fix on #339 switched the base from ``queuedRun.text`` to
``edit.before``. That holds only while the page shows the exact revision the
queued op was opened against: with a ``set_run`` already queued on the run,
``edit.before`` is overridden with that op's baseline, which can be an older
revision's text than the one on screen (head moved under a persisted queue,
or a candidate that already carries the earlier text). Offsets measured on
the displayed text then splice into the baseline at a stale position, and the
overlay field shows the wrong slice.

Fix: the caret effect and the inline edit carry ``rangeText`` — the displayed
run text the offsets were measured on. ``runTextAfterEdit`` (revision.ts)
splices into ``rangeText``; the overlay field slices ``rangeText``;
``before`` stays the op's A→B baseline.

Test commands
-------------
Run from the repo root::

    pytest tests/test_desktop_same_run_range_text.py tests/test_desktop_sequential_edit_offset.py -v
    node tests/desktop_same_run_range_text_harness.cjs

Explicit NOT-claims
-------------------
* No Windows GUI E2E / Tauri IPC.
* No own_render IoU, no rematch, no LayoutSnapshot.
* Rebasing a second edit ON TOP of a queued first edit is not attempted; the
  queue keeps one op per run and the second edit replaces the first relative
  to the displayed text.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "desktop" / "src"
HARNESS = Path(__file__).resolve().parent / "desktop_same_run_range_text_harness.cjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _commit_edit_body(text: str) -> str:
    start = text.index("export async function commitEdit(")
    end = text.index("function cellSlug(", start)
    return text[start:end]


# ---------------------------------------------------------------------------
# Structural guards — fail on the #339 tip, pass with the fix
# ---------------------------------------------------------------------------

def test_caret_effect_carries_range_text():
    """``prepareParagraphEdit`` must return the displayed run text as
    ``rangeText`` next to the range it measured on it."""
    text = _read("revision.ts")
    assert "rangeText: located.runText," in text
    assert "rangeText: effect.rangeText," in text, (
        "commitParagraphClick does not pass rangeText through to the inline edit"
    )


def test_commit_edit_splices_through_run_text_after_edit():
    """``commitEdit`` must not pick its own splice base — not ``edit.before``,
    not ``queuedRun?.text``. The base is ``rangeText`` inside
    ``runTextAfterEdit``."""
    body = _commit_edit_body(_read("actions.ts"))
    assert "runTextAfterEdit(edit, " in body
    assert "runText: edit.before" not in body
    assert "queuedRun?.text" not in body


def test_run_text_after_edit_bases_on_range_text():
    text = _read("revision.ts")
    start = text.index("export function runTextAfterEdit(")
    end = text.index("\n}\n", start)
    body = text[start:end]
    assert "edit.rangeText ?? edit.before" in body
    assert "runText: base," in body


def test_overlay_field_slices_range_text():
    """The caret field's initial value is the clicked line, sliced from the
    text the range was measured on — not from the op baseline."""
    text = _read("components/PageOverlay.tsx")
    assert "editing.rangeText ?? editing.before" in text
    assert "fieldTextForRunEdit(editing.before," not in text


# ---------------------------------------------------------------------------
# Runtime harness — real prepareParagraphEdit -> commitParagraphClick path
# ---------------------------------------------------------------------------

def test_same_run_range_text_harness():
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
    assert "PASS moved_head_splice_lands_on_displayed_text" in completed.stdout
    assert "PASS moved_head_field_shows_clicked_line" in completed.stdout
