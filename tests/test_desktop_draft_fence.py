# -*- coding: utf-8 -*-
"""Completion card 2: draft-fence / async-staleness on the plan path.

These cases fail on the PR #336 tip (no generation fence on setQueue) and
pass after the fence is wired through store.ts / actions.ts.

What was missing on the #336 tip
---------------------------------
``setQueue`` in ``actions.ts`` awaits two runtime calls
(``rt.proposePlan`` then ``rt.validatePlan``) and writes the result into the
store.  Nothing stopped a concurrent, newer ``setQueue`` call from bumping the
store into a "ready" state while the earlier call was still suspended; when the
older call's await finally resumed it would unconditionally overwrite the newer
result with stale data.

The existing ``draftStaleness`` / ``canRequestApproval`` gate (``other_session``
+ ``source_changed``) only caught race conditions from document switches or
backend-signalled staleness — not concurrent in-flight calls from the same
session.  ``plan_stale`` was structurally unreachable on this build because
nothing ever writes to the open session's source bytes.

The fix
-------
``store.ts`` exports a module-level monotonic counter
(``bumpPlanGeneration`` / ``currentPlanGeneration`` / ``_resetPlanGenerationForTest``).
``setQueue`` captures its generation token before the first await and checks
``currentPlanGeneration() !== gen`` after each async suspension — after
``rt.proposePlan``, after ``rt.validatePlan``, and before writing the error
path.  A stale call returns without touching the store.

Ported from ``4f214ace`` (epoch desktop): a replacement queue also drops the
preceding ``plan`` / ``validation`` / ``boundSha256`` before the first await,
and an identity/session/head ``ownsDraft`` fence ignores late completions
after a clear, document switch, or candidate-head change.  The generation
token still covers concurrent ``setQueue``.

Test commands
-------------
Run from the repo root::

    pytest tests/test_desktop_draft_fence.py -v

The harness also runs standalone::

    node tests/desktop_draft_fence_harness.cjs

Explicit NOT-claims
-------------------
* These tests do NOT exercise Windows GUI E2E or Tauri IPC.
* They do NOT test the own_render IoU path or rematch.
* ``requestApproval`` / ``resolveApprovalDecision`` are unchanged;
  human/agent review gate is kept as-is.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "desktop" / "src" / "store.ts"
ACTIONS = REPO / "desktop" / "src" / "actions.ts"
HARNESS = Path(__file__).resolve().parent / "desktop_draft_fence_harness.cjs"
FRESHNESS = REPO / "desktop" / "scripts" / "set-queue-freshness.test.mjs"
HEAD_FRESHNESS = REPO / "desktop" / "scripts" / "set-head-freshness.test.mjs"
REVIEW_FRESHNESS = REPO / "desktop" / "scripts" / "review-apply-freshness.test.mjs"
TSC = REPO / "desktop" / "node_modules" / "typescript"
DOCUMENT_CONTEXT = REPO / "desktop" / "src" / "components" / "DocumentContext.tsx"
AGENT_VIEW = REPO / "desktop" / "src" / "views" / "AgentView.tsx"
CONVERSATION = REPO / "desktop" / "src" / "components" / "Conversation.tsx"


# ---------------------------------------------------------------------------
# Structural tests — verify the fence is wired; fail on the #336 tip
# ---------------------------------------------------------------------------

def test_store_exports_bump_plan_generation():
    """store.ts must export the fence primitives added in card 2."""
    text = STORE.read_text(encoding="utf-8")
    assert "bumpPlanGeneration" in text
    assert "currentPlanGeneration" in text
    assert "_resetPlanGenerationForTest" in text


def test_store_fence_is_module_level_not_workspace_state():
    """The fence counter must NOT appear inside WorkspaceState.

    Putting it in WorkspaceState would trigger a React re-render on every
    plan bump, which is both unnecessary and contrary to the design intent.
    The counter is a plain module-level variable.
    """
    text = STORE.read_text(encoding="utf-8")
    # The WorkspaceState block ends just before 'export const EMPTY_DRAFT'.
    ws_end = text.index("export const EMPTY_DRAFT")
    ws_block = text[:ws_end]
    # planGeneration must not appear as a field inside WorkspaceState.
    assert "planGeneration:" not in ws_block


def test_actions_imports_plan_generation_fence():
    """actions.ts must import both fence accessors from ./store."""
    text = ACTIONS.read_text(encoding="utf-8")
    # Both names must appear in the import block.
    store_import_start = text.index('from "./store"')
    import_block = text[:store_import_start]
    assert "bumpPlanGeneration" in import_block
    assert "currentPlanGeneration" in import_block


def _setqueue_body(text: str) -> str:
    """Extract the precise body of ``setQueue`` from ``actions.ts``.

    ``reproposeDraft`` immediately follows ``setQueue`` and is used as the
    end delimiter.  This avoids including unrelated catch blocks from the
    many other async functions in the file.
    """
    start = text.index("async function setQueue(")
    end = text.index("export async function reproposeDraft")
    return text[start:end]


def test_set_queue_bumps_generation_before_first_await():
    """setQueue must call bumpPlanGeneration() before the first rt.proposePlan call.

    The token capture must precede the first await; otherwise a concurrent
    call that starts between the first await and the token capture would get
    a stale comparison.
    """
    body = _setqueue_body(ACTIONS.read_text(encoding="utf-8"))
    bump_pos = body.index("bumpPlanGeneration()")
    propose_pos = body.index("rt.proposePlan(")
    assert bump_pos < propose_pos, (
        "bumpPlanGeneration() must appear before the first rt.proposePlan call "
        f"(bump at {bump_pos}, propose at {propose_pos})"
    )


def test_set_queue_checks_fence_after_propose_and_validate():
    """setQueue must check currentPlanGeneration() after BOTH awaits.

    One check after propose and one after validate; missing either leaves a
    window where an older call can overwrite a newer result.
    """
    body = _setqueue_body(ACTIONS.read_text(encoding="utf-8"))

    guard = "currentPlanGeneration() !== gen"
    guards = [i for i in range(len(body)) if body[i:].startswith(guard)]
    assert len(guards) >= 2, (
        f"Expected ≥2 fence guards in setQueue, found {len(guards)}. "
        "Need one after rt.proposePlan and one after rt.validatePlan."
    )

    propose_pos = body.index("rt.proposePlan(")
    validate_pos = body.index("rt.validatePlan(")

    after_propose = [g for g in guards if g > propose_pos]
    assert after_propose, "No fence guard found after rt.proposePlan"

    after_validate = [g for g in guards if g > validate_pos]
    assert after_validate, "No fence guard found after rt.validatePlan"


def test_set_queue_clears_stale_plan_before_propose():
    """A replacement queue must hide the preceding plan before the first await."""
    body = _setqueue_body(ACTIONS.read_text(encoding="utf-8"))
    plan_null = body.index("plan: null")
    validation_null = body.index("validation: null")
    bound_null = body.index("boundSha256: null")
    propose_pos = body.index("rt.proposePlan(")
    assert plan_null < propose_pos
    assert validation_null < propose_pos
    assert bound_null < propose_pos


def test_set_queue_owns_draft_identity_session_and_head():
    """Late completions after a clear, session switch, or head change must not land."""
    text = ACTIONS.read_text(encoding="utf-8")
    body = _setqueue_body(text)
    owner_start = text.index("interface DraftOwner")
    owner_end = text.index("/** Load a session's inspect", owner_start)
    owner = text[owner_start:owner_end]
    assert "state.draft === owner.draft" in owner
    assert "state.activeSessionId === owner.sessionId" in owner
    assert "headCandidate(state)?.runId" in owner
    assert "const owner = captureDraftOwner()" in body
    propose_pos = body.index("rt.proposePlan(")
    owns = [i for i in range(len(body)) if body[i:].startswith("if (!ownsDraft(owner)) return;")]
    assert len(owns) >= 3, f"Expected ≥3 ownsDraft guards, found {len(owns)}"
    assert any(i > propose_pos for i in owns)
    catch_pos = body.rindex("} catch (e) {")
    assert any(i > catch_pos for i in owns)


def test_agent_plan_adoption_uses_the_same_draft_owner():
    """Agent completions must not overwrite a newer document, head, or queue."""
    text = ACTIONS.read_text(encoding="utf-8")
    start = text.index("async function adoptAgentPlan(")
    end = text.index("/** Ids are the shell's", start)
    body = text[start:end]
    assert "owner: DraftOwner" in body
    assert "if (!ownsDraft(owner)) return null;" in body
    assert body.index("await rt.validatePlan") < body.index("if (!ownsDraft(owner))")

    mock_start = text.index("export async function runAgentProposal")
    mock_end = text.index("// --- checking", mock_start)
    mock = text[mock_start:mock_end]
    assert mock.index("const owner = captureDraftOwner()") < mock.index("await rt.runMockAgent")
    assert "approval?.approvalId ?? null,\n      owner," in mock

    send_start = text.index("export async function sendInstruction")
    send_end = text.index("/** Stop the run in flight", send_start)
    send = text[send_start:send_end]
    assert send.index("const owner = captureDraftOwner()") < send.index("await rt.agentHostRun")
    assert "if (adopted) patchTurn(id, { planId });" in send


def test_approval_actions_keep_their_draft_owner_across_awaits():
    """Late approval completions must not attach to a replacement draft."""
    text = ACTIONS.read_text(encoding="utf-8")
    request_start = text.index("export async function requestApprovalForDraft")
    resolve_start = text.index("export async function resolveApprovalDecision")
    apply_start = text.index("// --- apply", resolve_start)
    request = text[request_start:resolve_start]
    resolve = text[resolve_start:apply_start]

    assert request.index("const owner = captureDraftOwner()") < request.index(
        "await rt.requestApproval"
    )
    assert request.count("!ownsDraft(owner)") >= 2
    assert request.count("getState().draft.plan !== plan") >= 2

    assert resolve.index("const owner = captureDraftOwner()") < resolve.index(
        "await rt.resolveApproval"
    )
    assert resolve.count("!ownsDraft(owner)") >= 2
    assert resolve.count("getState().draft.plan !== plan") >= 2
    assert resolve.count("getState().approval !== approval") >= 2


def test_agent_document_context_reads_shared_work_state():
    """The agent pane must project the store, not hard-coded duplicate state."""
    context = DOCUMENT_CONTEXT.read_text(encoding="utf-8")
    assert "export function DocumentContext()" in context
    assert "useWorkspace(activeSession)" in context
    assert "useWorkspace(activeInspect)" in context
    assert "useWorkspace(activeCandidates)" in context
    assert "useWorkspace((s) => s.draft)" in context
    assert "useWorkspace((s) => s.approval)" in context
    assert "draft.ops.length" in context
    assert "draft.validation" in context
    assert "이 단계에서는 문서를 읽기만 합니다" not in context
    assert "<DocumentContext />" in AGENT_VIEW.read_text(encoding="utf-8")


def test_superseded_agent_plan_is_not_described_as_queued():
    """A turn card must distinguish a runtime plan from an adopted draft."""
    conversation = CONVERSATION.read_text(encoding="utf-8")
    assert "turn.planId ?" in conversation
    assert "대기열에는 넣지 않았습니다." in conversation


def test_set_queue_error_path_is_also_fenced():
    """The catch block in setQueue must also check the fence before setState.

    Without this, a late-arriving network error from an older call would set
    phase='failed' on top of a newer call's 'ready' state.

    ``reproposeDraft`` immediately follows ``setQueue`` in the file, so we
    use it as the precise end-of-body delimiter instead of the next
    ``async function`` declaration (which could be far away and contain
    other catch blocks that would confuse the rindex search).
    """
    text = ACTIONS.read_text(encoding="utf-8")
    start = text.index("async function setQueue(")
    # reproposeDraft is the first thing declared right after setQueue closes.
    end = text.index("export async function reproposeDraft")
    body = text[start:end]

    catch_pos = body.rindex("} catch (e) {")
    guard = "currentPlanGeneration() !== gen"
    guards_after_catch = [i for i in range(len(body)) if i > catch_pos and body[i:].startswith(guard)]
    assert guards_after_catch, "No fence guard found inside the catch block of setQueue"


def test_review_apply_and_agent_adoption_share_draft_fence():
    """Every async publisher in review → apply must prove it still owns the draft."""
    text = ACTIONS.read_text(encoding="utf-8")
    assert "function captureDraftFence(" in text
    assert "function ownsDraftFence(" in text
    for start, end in (
        ("export async function requestApprovalForDraft", "export async function resolveApprovalDecision"),
        ("export async function resolveApprovalDecision", "// --- apply"),
        ("export async function applyApproved", "/** Cooperative cancel"),
        ("async function adoptAgentPlan(", "/** Ids are the shell's"),
    ):
        body = text[text.index(start) : text.index(end, text.index(start))]
        assert "ownsDraftFence(" in body, f"{start} does not fence stale publication"


def test_empty_queue_replacement_invalidates_async_publishers():
    """Clear/last-op undo must advance the generation even without another proposal."""
    text = ACTIONS.read_text(encoding="utf-8")
    clear = text[text.index("export async function clearQueue") : text.index("/**\n * Replace the queue")]
    assert "bumpPlanGeneration()" in clear

    body = _setqueue_body(text)
    bump_pos = body.index("bumpPlanGeneration()")
    empty_pos = body.index("if (ops.length === 0 || !sessionId)")
    assert bump_pos < empty_pos


def test_set_head_uses_invocation_and_identity_fence():
    """Only the latest head choice may publish a receipt or rebase the queue."""
    text = ACTIONS.read_text(encoding="utf-8")
    helper_start = text.index("interface HeadSelectionLease")
    helper_end = text.index("/**\n * Make a candidate", helper_start)
    helper = text[helper_start:helper_end]
    assert "generation: ++headSelectionGeneration" in helper
    assert "headSelectionGeneration === lease.generation" in helper
    assert "state.activeSessionId === lease.sessionId" in helper
    assert "state.head === lease.runId" in helper

    start = text.index("export async function setHead")
    end = text.index("// --- approval", start)
    body = text[start:end]
    capture = body.index("const lease = captureHeadSelection(runId)")
    receipt = body.index("await loadReceipt")
    final_guard = body.index("if (!ownsHeadSelection(lease)) return;", receipt)
    rebase = body.index("await setQueue", final_guard)
    assert capture < receipt < final_guard < rebase
    assert "await loadReceipt(runId, () => ownsHeadSelection(lease))" in body


def test_receipt_publication_checks_session_and_caller_lease():
    """Receipt success and error paths must both refuse stale publication."""
    text = ACTIONS.read_text(encoding="utf-8")
    start = text.index("export async function loadReceipt")
    end = text.index("export function openReceipt", start)
    body = text[start:end]
    guard = "getState().activeSessionId !== sessionId || !ownsPublication()"
    assert body.count(guard) >= 2


# ---------------------------------------------------------------------------
# Runtime harness — interleaved schedules and out-of-order resolve
# ---------------------------------------------------------------------------

def test_draft_fence_harness():
    """Node harness verifies the fence under out-of-order async resolution."""
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


def test_draft_freshness_node_tests():
    """Ported epoch freshness cases: session, head, clear, and late error."""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--test", str(FRESHNESS)],
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


def test_head_freshness_node_tests():
    """Out-of-order head receipts cannot publish stale verdicts or queue bases."""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--test", str(HEAD_FRESHNESS)],
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


def test_review_apply_freshness_node_tests():
    """Approval, apply, and agent adoption cannot publish into a newer draft."""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--test", str(REVIEW_FRESHNESS)],
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
