"""Tests for agenthost QA harness glue (Audit W0 item 8).

Verifies:
1. Glue resolves pending approval in mock_approved mode for agent/plan paths.
2. Refusal in human_approved mode when operator signature is absent.
3. Escalate / refusal path gating: agent cannot approve itself; host-authority glue resolves with mock_approved.
"""

from __future__ import annotations

import pytest
from qa.approval import create_approval_request, HumanApprovalRequiredError
from qa.agenthost_glue import (
    resolve_agenthost_plan_approval,
    gate_agenthost_plan_apply,
)


def test_glue_resolves_mock_approval():
    req = create_approval_request(
        plan_id="plan-ah-001",
        plan_hash="hash-ah-001",
        requested_by="agenthost-mock",
    )

    res = resolve_agenthost_plan_approval(
        req,
        plan_id="plan-ah-001",
        plan_hash="hash-ah-001",
        approval_mode="mock_approved",
    )
    assert res.state == "approved"
    assert res.approver == "mock_approved"
    assert res.is_mock_approved is True
    assert res.is_human_approved is False
    assert res.gui_claimed is False


def test_glue_refuses_in_human_mode():
    req = create_approval_request(
        plan_id="plan-ah-002",
        plan_hash="hash-ah-002",
        requested_by="agenthost-mock",
    )

    with pytest.raises(HumanApprovalRequiredError) as exc:
        resolve_agenthost_plan_approval(
            req,
            plan_id="plan-ah-002",
            plan_hash="hash-ah-002",
            approval_mode="human_approved",
        )
    assert "real human operator approval required" in str(exc.value).lower()


def test_glue_escalation_gating():
    req = create_approval_request(
        plan_id="plan-ah-003",
        plan_hash="hash-ah-003",
        requested_by="agenthost-mock",
    )

    # 1. Unapproved: plan apply gating refuses
    can_apply, reason = gate_agenthost_plan_apply(req)
    assert can_apply is False
    assert "pending" in reason

    # 2. Host resolves via mock_approved
    resolved = resolve_agenthost_plan_approval(
        req,
        plan_id="plan-ah-003",
        plan_hash="hash-ah-003",
        approval_mode="mock_approved",
    )

    # 3. Plan apply gating permits execution under mock_approved
    can_apply, reason = gate_agenthost_plan_apply(resolved)
    assert can_apply is True
    assert reason == "mock_approved"
    assert resolved.is_human_approved is False
