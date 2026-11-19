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
OPERATOR_MODAL = DESKTOP / "src" / "components" / "OperatorAgentModal.tsx"
NODE_TEST = DESKTOP / "scripts" / "view-state.test.mjs"


def _composer_block(modal_src: str) -> str:
    start = modal_src.index("function OperatorAgentComposer(")
    end = modal_src.index("function OperatorAgentTab(", start)
    return modal_src[start:end]


def test_composer_draft_is_workspace_state():
    """Closing or switching tabs in the operator modal must not own unsent user work."""
    store = STORE.read_text(encoding="utf-8")
    composer = _composer_block(OPERATOR_MODAL.read_text(encoding="utf-8"))

    # One draft per document (a doc slice), so it cannot follow the person to
    # another document either.
    assert 'defineDocSlice<{ draft: ComposerDraft }>("workspace.composer"' in store
    assert "composerDraft: composerDraftOf().text" in store
    assert "composerDraft: { text: string };" not in store
    assert "const text = useComposerDraftText();" in composer
    assert "onChange={(e) => setComposerDraft(e.target.value)}" in composer
    assert "useState" not in composer


def test_late_send_reconciliation_is_wired():
    """A failed old send may restore itself, but may not replace newer typing."""
    composer = _composer_block(OPERATOR_MODAL.read_text(encoding="utf-8"))

    helper = (DESKTOP / "src/workspace/composerDraft.ts").read_text(encoding="utf-8")
    assert "await submitComposerDraft({" in composer
    assert "read: () => composerDraftOf(doc)" in composer
    assert "write: (draft) => writeComposerDraft(draft, doc)" in composer
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
