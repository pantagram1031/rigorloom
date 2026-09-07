"""Tests for approval/resolve contract and mock_approved mode in QA harness.

Tests:
1. Deterministic approval/resolve with mock_approved mode.
2. Binding validation: planId and planHash must match.
3. Invariant: mock_approved never claims human_approved or GUI/IME PASS.
4. Refusal in human_approved mode when operator is absent (clear NOT_RUN notes).
5. Plan apply gating: plan/apply permits execution only after approval resolution.
6. Protocol RPC compatibility matching Runtime Protocol v0 approval/resolve.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from qa.approval import (
    ApprovalBindingMismatchError,
    ApprovalAlreadyResolvedError,
    HumanApprovalRequiredError,
    ApprovalRecord,
    create_approval_request,
    resolve_approval,
    can_apply_plan,
    handle_approval_resolve_rpc,
)


def test_create_approval_request():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="sha256-hash-aaa111",
        requested_by="agenthost-mock",
    )
    assert req.approval_id
    assert req.plan_id == "plan-test-001"
    assert req.plan_hash == "sha256-hash-aaa111"
    assert req.requested_by == "agenthost-mock"
    assert req.state == "pending"
    assert req.is_pending is True
    assert req.approver is None
    assert req.decision is None


def test_mock_approved_resolution_binds_plan_and_hash():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="sha256-hash-aaa111",
        requested_by="agenthost-mock",
    )

    resolved = resolve_approval(
        req,
        plan_id="plan-test-001",
        plan_hash="sha256-hash-aaa111",
        decision="approved",
        approver="mock_approved",
        mode="mock_approved",
    )

    assert resolved.state == "approved"
    assert resolved.decision == "approved"
    assert resolved.approver == "mock_approved"
    assert resolved.mode == "mock_approved"
    assert resolved.is_mock_approved is True
    assert resolved.is_human_approved is False
    assert resolved.resolved_utc is not None
    assert resolved.gui_claimed is False


def test_mock_approved_never_claims_human_approved():
    req = create_approval_request(
        plan_id="plan-test-002",
        plan_hash="hash-bbb222",
    )
    resolved = resolve_approval(
        req,
        plan_id="plan-test-002",
        plan_hash="hash-bbb222",
        mode="mock_approved",
    )

    public_dict = resolved.to_dict()
    assert public_dict["is_mock_approved"] is True
    assert public_dict["is_human_approved"] is False
    assert public_dict["gui_claimed"] is False
    assert "mock_approved" in public_dict["approver"]
    assert public_dict["approver"] != "human_approved"


def test_approval_resolve_binding_mismatch():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="hash-correct",
    )

    # Hash mismatch
    with pytest.raises(ApprovalBindingMismatchError) as exc_info:
        resolve_approval(
            req,
            plan_id="plan-test-001",
            plan_hash="hash-wrong",
            mode="mock_approved",
        )
    assert "hash mismatch" in str(exc_info.value).lower()

    # Plan ID mismatch
    with pytest.raises(ApprovalBindingMismatchError) as exc_info_id:
        resolve_approval(
            req,
            plan_id="plan-wrong",
            plan_hash="hash-correct",
            mode="mock_approved",
        )
    assert "planid mismatch" in str(exc_info_id.value).lower()


def test_approval_resolve_already_resolved():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="hash-correct",
    )
    resolve_approval(
        req,
        plan_id="plan-test-001",
        plan_hash="hash-correct",
        mode="mock_approved",
    )

    with pytest.raises(ApprovalAlreadyResolvedError):
        resolve_approval(
            req,
            plan_id="plan-test-001",
            plan_hash="hash-correct",
            mode="mock_approved",
        )


def test_human_approved_mode_refuses_automatic_resolution():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="hash-correct",
    )

    # Without an operator signature/override, human_approved mode refuses
    with pytest.raises(HumanApprovalRequiredError) as exc:
        resolve_approval(
            req,
            plan_id="plan-test-001",
            plan_hash="hash-correct",
            mode="human_approved",
        )
    assert "real human operator approval required" in str(exc.value).lower()
    assert req.state == "pending"


def test_plan_apply_gating():
    req = create_approval_request(
        plan_id="plan-test-001",
        plan_hash="hash-correct",
    )

    # Pending cannot apply
    can_apply, reason = can_apply_plan(req)
    assert can_apply is False
    assert "pending" in reason

    # Mock approved can apply in QA harness gating, clearly labeled
    mock_resolved = resolve_approval(
        req,
        plan_id="plan-test-001",
        plan_hash="hash-correct",
        mode="mock_approved",
    )
    can_apply, reason = can_apply_plan(mock_resolved)
    assert can_apply is True
    assert reason == "mock_approved"

    # Rejected cannot apply
    req2 = create_approval_request(plan_id="plan-2", plan_hash="hash-2")
    rejected = resolve_approval(
        req2,
        plan_id="plan-2",
        plan_hash="hash-2",
        decision="rejected",
        mode="mock_approved",
    )
    can_apply, reason = can_apply_plan(rejected)
    assert can_apply is False
    assert "rejected" in reason


def test_handle_approval_resolve_rpc():
    req = create_approval_request(
        plan_id="plan-rpc-1",
        plan_hash="hash-rpc-1",
        requested_by="agenthost-mock",
    )

    rpc_params = {
        "approvalId": req.approval_id,
        "planId": "plan-rpc-1",
        "planHash": "hash-rpc-1",
        "decision": "approved",
    }

    # In mock_approved mode
    res = handle_approval_resolve_rpc(
        req,
        rpc_params,
        approval_mode="mock_approved",
    )
    assert "approval" in res
    appr = res["approval"]
    assert appr["state"] == "approved"
    assert appr["decision"] == "approved"
    assert appr["approver"] == "mock_approved"
    assert appr["is_mock_approved"] is True
    assert appr["is_human_approved"] is False

    # In human_approved mode -> fails RPC with refusal
    req_human = create_approval_request(
        plan_id="plan-rpc-2",
        plan_hash="hash-rpc-2",
    )
    with pytest.raises(HumanApprovalRequiredError):
        handle_approval_resolve_rpc(
            req_human,
            {
                "approvalId": req_human.approval_id,
                "planId": "plan-rpc-2",
                "planHash": "hash-rpc-2",
                "decision": "approved",
            },
            approval_mode="human_approved",
        )
