# -*- coding: utf-8 -*-
"""The bundled SKILL.md must say it is not the composed copy (T133).

`skill/SKILL.md` closed on "Module skill fragments ... are appended below by the
installer when their distribution modules are enabled." For that file the
sentence is false and always will be: it is the pre-install source, the
composition happens in `scripts/sync_local.py`, and the result lands in the
installed copy under the Claude skills directory.

A clean-room agent read the sentence in the bundled copy, found nothing appended,
confirmed the module was enabled, and reported the installer as broken. The
installer was fine — the composed copy is 735 lines and carries every fragment.
The defect was that nothing in the bundled file said which copy the reader was
holding, and extracting a bundle and opening `skill/SKILL.md` is the obvious
thing to do.

Verifying that report before building on it is what turned a false P1 into this
one-paragraph fix. The guard exists so the breadcrumb cannot be edited away
again.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "skill" / "SKILL.md"
INSTALLER = ROOT / "scripts" / "sync_local.py"


def _closing_passage() -> str:
    """The tail of the file, where the fragment promise lives."""
    text = BUNDLED.read_text(encoding="utf-8")
    return "\n".join(text.rstrip().split("\n")[-14:])


def test_the_fragment_promise_names_the_installer_and_the_destination():
    passage = _closing_passage()
    assert "sync_local.py" in passage, (
        "the sentence promising appended fragments must name what does the "
        "appending, or a reader cannot tell whether it already happened")
    assert re.search(r"skills[- ]root|skills directory", passage), (
        "it must also name WHERE the composed copy lands, or the reader has no "
        "breadcrumb from this file to the one that carries the fragments")


def test_the_bundled_copy_says_it_is_not_the_composed_one():
    passage = _closing_passage()
    assert "pre-install source" in passage, passage
    assert "never carries them" in passage, (
        "the file has to state plainly that the fragments are not below IN THIS "
        "COPY; 'appended below by the installer' alone is what misled a reader")


def test_the_installer_really_is_the_composer():
    """Derived, not asserted from memory: the file named above must be the one
    that appends fragments, or the breadcrumb points at the wrong script."""
    assert INSTALLER.is_file(), INSTALLER
    body = INSTALLER.read_text(encoding="utf-8")
    assert "FRAGMENT" in body or "fragment" in body, (
        "sync_local.py no longer mentions fragments; if composition moved, the "
        "sentence in skill/SKILL.md has to move with it")
    assert "SKILL.md" in body


def test_the_bundled_copy_is_still_the_uncomposed_one():
    """Non-vacuity for the whole guard: if the bundled file ever DID carry the
    fragments, the warning above would be wrong rather than protective."""
    text = BUNDLED.read_text(encoding="utf-8")
    assert "## Module: " not in text, (
        "the bundled SKILL.md now contains a module section, so it is no longer "
        "the pre-install source and this warning must be revisited")
