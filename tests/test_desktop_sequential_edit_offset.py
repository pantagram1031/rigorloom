# -*- coding: utf-8 -*-
"""Sequential same-run edit: second edit must not suffer offset drift.

Bug (present on #336 / #339 tip before this fix)
--------------------------------------------------
``commitEdit`` computed the splice base as ``queuedRun?.text ?? edit.before``.
``queuedRun?.text`` is the TEXT written by a previous edit of the same run
(e.g. "Hi World"), but ``rangeStart``/``rangeEnd`` are UTF-16 offsets computed
by ``prepareParagraphEdit`` against the *displayed revision* — the document
bytes that were shown in the overlay, which have NOT been applied yet and still
read "Hello World".  When the two strings have different lengths the splice
lands at the wrong position.

Example:
  Run text (displayed):     "Hello World" (11 UTF-16 units)
  First queued edit:        rangeStart=0, rangeEnd=5, text="Hi World"
  Second edit click:        visual line "World", rangeStart=6, rangeEnd=11
  Second value typed:       "Earth"

  Bug:   replaceUtf16Range("Hi World", 6, 11, "Earth")
           = "Hi WorEarth"   (length 8; range 6..11 overshoots → stale)

  Fix:   replaceUtf16Range("Hello World", 6, 11, "Earth")
           = "Hello Earth"   (correct)

The structural tests below fail on the tip that has the bug and pass after
the fix is applied.

Test commands
-------------
Run from the repo root::

    pytest tests/test_desktop_sequential_edit_offset.py -v

Harness also runs standalone::

    node tests/desktop_sequential_edit_offset_harness.cjs

Explicit NOT-claims
-------------------
* No Windows GUI E2E / Tauri IPC.
* No own_render IoU, no rematch.
* Human/agent review gate unchanged.
* Draft-fence (card 2) tests remain intact and all pass.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ACTIONS = REPO / "desktop" / "src" / "actions.ts"
HARNESS = Path(__file__).resolve().parent / "desktop_sequential_edit_offset_harness.cjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"


def _commit_edit_body(text: str) -> str:
    """Extract the body of ``commitEdit`` from ``actions.ts``.

    ``cellSlug`` is the private helper immediately after ``commitEdit``'s
    closing brace and serves as an unambiguous end delimiter.
    """
    start = text.index("export async function commitEdit(")
    end = text.index("function cellSlug(", start)
    return text[start:end]


# ---------------------------------------------------------------------------
# Structural tests — fail on the bug code, pass after the fix
# ---------------------------------------------------------------------------

def test_commit_edit_splice_base_is_before_not_queued_text():
    """commitEdit must use ``edit.before`` as the runText for the splice, not
    ``queuedRun?.text``.

    The rangeStart/rangeEnd offsets come from prepareParagraphEdit against
    the DISPLAYED revision (edit.before).  Using queuedRun?.text (the result
    of a prior edit) as the base gives wrong offsets when its length differs
    from edit.before.
    """
    body = _commit_edit_body(ACTIONS.read_text(encoding="utf-8"))
    # The bug pattern: queuedRun?.text used as the splice base
    assert "queuedRun?.text ?? edit.before" not in body, (
        "commitEdit still uses queuedRun?.text as the runText splice base; "
        "offsets from prepareParagraphEdit are valid for edit.before only"
    )
    # The fix: edit.before used directly
    assert "runText: edit.before," in body or "runText: edit.before\n" in body, (
        "commitEdit does not use edit.before as the runText splice base"
    )


def test_commit_edit_range_end_fallback_also_uses_before():
    """The rangeEnd fallback in commitEdit must also use edit.before.length.

    The bug had ``(queuedRun?.text ?? edit.before).length`` for the fallback.
    With the fix both ``rangeStart`` and ``rangeEnd`` are resolved against
    ``edit.before``.
    """
    body = _commit_edit_body(ACTIONS.read_text(encoding="utf-8"))
    # The bug fallback pattern
    assert "(queuedRun?.text ?? edit.before).length" not in body, (
        "commitEdit rangeEnd fallback still uses queuedRun?.text length"
    )


def test_commit_edit_before_field_of_new_op_is_unchanged():
    """The ``before`` field of the new queued op must still be the original
    run text.  It must NOT use ``queuedRun?.text`` as ``before``; that would
    cause the undo path to read the wrong previous value.
    """
    body = _commit_edit_body(ACTIONS.read_text(encoding="utf-8"))
    # The before: field must reference queuedRun?.before or edit.before (original),
    # never queuedRun?.text (the result of a prior edit).
    assert "before: queuedRun?.text" not in body, (
        "commitEdit uses queuedRun?.text as the `before` field — that would "
        "corrupt the undo path"
    )


# ---------------------------------------------------------------------------
# Runtime harness — arithmetic demonstration and source-code guard
# ---------------------------------------------------------------------------

def test_sequential_edit_offset_harness():
    """Node harness proves the offset-drift arithmetic and checks the fix."""
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
