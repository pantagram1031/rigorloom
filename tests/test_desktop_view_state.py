# -*- coding: utf-8 -*-
"""Headless contract for the Agent composer's shared draft state."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / "desktop"
STORE = DESKTOP / "src" / "store.ts"
COMPOSER = DESKTOP / "src" / "components" / "Composer.tsx"
NODE_TEST = DESKTOP / "scripts" / "view-state.test.mjs"


def test_composer_draft_is_workspace_state():
    """The unmounted Agent view must not own unsent user work."""
    store = STORE.read_text(encoding="utf-8")
    composer = COMPOSER.read_text(encoding="utf-8")

    assert "composerDraft: { text: string };" in store
    assert 'composerDraft: { text: "" }' in store
    assert "composerDraft: s.composerDraft.text" in store
    assert "useWorkspace((s) => s.composerDraft.text)" in composer
    assert "setState({ composerDraft: { text: e.target.value } })" in composer
    assert "useState" not in composer


def test_late_send_reconciliation_is_wired():
    """A failed old send may restore itself, but may not replace newer typing."""
    store = STORE.read_text(encoding="utf-8")
    composer = COMPOSER.read_text(encoding="utf-8")

    helper = (DESKTOP / "src/workspace/composerDraft.ts").read_text(encoding="utf-8")
    assert "await submitComposerDraft({" in composer
    assert "read: () => getState().composerDraft" in composer
    assert "write: (composerDraft) => setState({ composerDraft })" in composer
    assert "port.read() === cleared" in helper


def test_view_state_node_regressions():
    """Exercise the store transitions when desktop dependencies are installed."""
    if not (DESKTOP / "node_modules" / "react").is_dir():
        pytest.skip("desktop dependencies are not installed")
    completed = subprocess.run(
        [
            shutil.which("node") or "node",
            "--experimental-strip-types",
            "--test",
            str(NODE_TEST),
        ],
        cwd=str(DESKTOP),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
