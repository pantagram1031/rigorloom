# -*- coding: utf-8 -*-
"""DraftOwner / DraftFence must be one identity rule plus a generation token.

Residual risk after the setHead lease (#363): review, apply, undo, and agent
adoption used a second identity snapshot (``DraftFence``) that restated
draft/session/head checks and captured ``sessionId`` from a caller argument.
Those two helpers could drift independently.

This file locks the reconciliation: ``DraftFence extends DraftOwner``,
``captureDraftFence`` copies an owner, and ``ownsDraftFence`` reuses
``ownsDraft``. It does not re-test the setHead lease.

Test commands
-------------
Run from the repo root::

    pytest tests/test_desktop_draft_owner_fence.py -v

The harness also runs standalone::

    node --test desktop/scripts/draft-owner-fence.test.mjs

Explicit NOT-claims
-------------------
* Does NOT exercise rematch, own_render, LayoutSnapshot, or renderer pins.
* Does NOT change or re-test the setHead lease in #363.
* Does NOT claim Card4 IME / Card5 GUI PASS.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACTIONS = REPO / "desktop" / "src" / "actions.ts"
HARNESS = REPO / "desktop" / "scripts" / "draft-owner-fence.test.mjs"


def _lease_block() -> str:
    text = ACTIONS.read_text(encoding="utf-8")
    start = text.index("interface DraftOwner")
    end = text.index("/** Load a session's inspect", start)
    return text[start:end]


def test_fence_extends_owner_instead_of_restating_identity():
    """The fence type must not grow a second draft/session/head predicate."""
    lease = _lease_block()
    assert "interface DraftFence extends DraftOwner" in lease
    assert "generation: number" in lease
    assert lease.count("state.draft === owner.draft") == 1
    assert lease.count("state.activeSessionId === owner.sessionId") == 1
    assert lease.count("headCandidate(state)?.runId") == 2
    assert "function captureDraftFence(" in lease
    assert "function ownsDraftFence(" in lease


def test_capture_and_owns_compose_rather_than_diverge():
    """Capture copies the owner; owns reuses the identity predicate."""
    lease = _lease_block()
    capture_start = lease.index("function captureDraftFence(")
    capture = lease[capture_start : lease.index("function ownsDraftFence(")]
    owns = lease[lease.index("function ownsDraftFence(") :]
    assert "owner: DraftOwner = captureDraftOwner()" in capture
    assert "...owner" in capture
    assert "generation: currentPlanGeneration()" in capture
    assert "sessionId" not in capture.split("(", 1)[1].split(")", 1)[0]
    assert "currentPlanGeneration() === fence.generation && ownsDraft(fence)" in owns
    assert "state.draft === fence.draft" not in owns


def test_async_publishers_bind_fence_to_the_same_owner():
    """Review/apply/adopt must not recapture identity independently of owner."""
    text = ACTIONS.read_text(encoding="utf-8")
    request = text[
        text.index("export async function requestApprovalForDraft") : text.index(
            "export async function resolveApprovalDecision"
        )
    ]
    resolve = text[
        text.index("export async function resolveApprovalDecision") : text.index("// --- apply")
    ]
    apply_body = text[
        text.index("export async function applyApproved") : text.index("/** Cooperative cancel")
    ]
    adopt = text[
        text.index("async function adoptAgentPlan(") : text.index("/** Ids are the shell's")
    ]
    undo = text[
        text.index("export async function proposeUndoOf") : text.index(
            "/** The text the runtime returned"
        )
    ]

    assert "const owner = captureDraftOwner()" in request
    assert "const fence = captureDraftFence(owner)" in request
    assert "const owner = captureDraftOwner()" in resolve
    assert "const fence = captureDraftFence(owner)" in resolve
    assert "const fence = captureDraftFence()" in apply_body
    assert "const fence = captureDraftFence(owner)" in adopt
    assert "const fence = captureDraftFence()" in undo
    assert "captureDraftFence(sessionId)" not in text


def test_draft_owner_fence_node_tests():
    """Positive, stale-generation, and owner/fence divergence cases."""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--test", str(HARNESS)],
        cwd=str(REPO / "desktop"),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
