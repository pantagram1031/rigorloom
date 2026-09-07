"""Approval and resolve protocol wiring for unattended QA harness runs.

Audit W0 item 8 implementation:
Wires `approval/resolve` into the QA harness with a deterministic `mock_approved` mode.

Rules & Invariants:
1. `mock_approved` mode enables unattended test and card-4 prep execution through plan apply gating.
2. Under no circumstance does `mock_approved` claim `human_approved` or GUI/IME PASS.
3. Real operator approval mode (`human_approved`) refuses automated resolution with clear NOT_RUN notes.
4. Binding invariant: the decision strictly binds exact `planId` AND `planHash`; mismatches are refused.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import asdict, dataclass
from typing import Any


class ApprovalError(Exception):
    """Base exception for approval failures."""
    pass


class ApprovalBindingMismatchError(ApprovalError):
    """Raised when offered planId or planHash does not match bound approval."""
    pass


class ApprovalAlreadyResolvedError(ApprovalError):
    """Raised when attempting to resolve an approval that is no longer pending."""
    pass


class HumanApprovalRequiredError(ApprovalError):
    """Raised when human approval is required but mock_approved mode is disabled."""
    pass


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class ApprovalRecord:
    approval_id: str
    plan_id: str
    plan_hash: str
    state: str  # "pending", "approved", "rejected"
    requested_by: str
    requested_utc: str
    resolved_utc: str | None = None
    approver: str | None = None
    decision: str | None = None
    mode: str = "human_approved"  # "mock_approved" or "human_approved"
    is_mock_approved: bool = False
    is_human_approved: bool = False
    gui_claimed: bool = False  # Invariant: always False in QA harness
    notes: str | None = None

    @property
    def is_pending(self) -> bool:
        return self.state == "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "approvalId": self.approval_id,
            "planId": self.plan_id,
            "planHash": self.plan_hash,
            "state": self.state,
            "requestedBy": self.requested_by,
            "requestedUtc": self.requested_utc,
            "resolvedUtc": self.resolved_utc,
            "approver": self.approver,
            "decision": self.decision,
            "mode": self.mode,
            "is_mock_approved": self.is_mock_approved,
            "is_human_approved": self.is_human_approved,
            "gui_claimed": self.gui_claimed,
            "notes": self.notes,
        }


def create_approval_request(
    plan_id: str,
    plan_hash: str,
    requested_by: str = "agenthost-mock",
    approval_id: str | None = None,
) -> ApprovalRecord:
    """Create a new pending approval request binding plan_id and plan_hash."""
    return ApprovalRecord(
        approval_id=approval_id or uuid.uuid4().hex,
        plan_id=plan_id,
        plan_hash=plan_hash,
        state="pending",
        requested_by=requested_by,
        requested_utc=_now_iso(),
        resolved_utc=None,
        approver=None,
        decision=None,
        mode="human_approved",
        is_mock_approved=False,
        is_human_approved=False,
        gui_claimed=False,
        notes="Awaiting resolution",
    )


def resolve_approval(
    record: ApprovalRecord,
    plan_id: str,
    plan_hash: str,
    *,
    decision: str = "approved",
    approver: str | None = None,
    mode: str = "mock_approved",
    operator_token: str | None = None,
) -> ApprovalRecord:
    """Resolve an approval request.

    If mode == 'mock_approved':
      - Resolves the approval with approver 'mock_approved'.
      - Sets is_mock_approved=True, is_human_approved=False, gui_claimed=False.
      - Strictly binds plan_id and plan_hash.

    If mode == 'human_approved':
      - If no operator_token is provided, raises HumanApprovalRequiredError.
      - Never fabricates human approval in unattended mode.
    """
    if record.state != "pending":
        raise ApprovalAlreadyResolvedError(
            f"Approval '{record.approval_id}' is already {record.state} "
            f"(resolved at {record.resolved_utc} by {record.approver})"
        )

    if plan_id != record.plan_id:
        raise ApprovalBindingMismatchError(
            f"PlanID mismatch: offered '{plan_id}' does not match bound '{record.plan_id}'"
        )

    if plan_hash != record.plan_hash:
        raise ApprovalBindingMismatchError(
            f"Hash mismatch: offered planHash '{plan_hash}' does not match bound '{record.plan_hash}'"
        )

    if mode == "mock_approved":
        target_approver = approver or "mock_approved"
        record.state = decision
        record.decision = decision
        record.approver = target_approver
        record.mode = "mock_approved"
        record.is_mock_approved = True
        record.is_human_approved = False
        record.resolved_utc = _now_iso()
        record.gui_claimed = False
        record.notes = (
            "Resolved in mock_approved mode for unattended QA harness gating; "
            "never claims human approval or GUI/IME PASS."
        )
        return record

    if mode == "human_approved":
        if not operator_token:
            raise HumanApprovalRequiredError(
                f"Real human operator approval required: approval_mode is 'human_approved' "
                f"and unattended harness cannot resolve approval '{record.approval_id}'."
            )
        # Operator token supplied
        record.state = decision
        record.decision = decision
        record.approver = approver or f"human-operator-{operator_token[:8]}"
        record.mode = "human_approved"
        record.is_mock_approved = False
        record.is_human_approved = True
        record.resolved_utc = _now_iso()
        record.gui_claimed = False
        record.notes = "Resolved by human operator."
        return record

    raise ApprovalError(f"Unsupported approval mode: {mode}")


def can_apply_plan(record: ApprovalRecord) -> tuple[bool, str]:
    """Gate whether plan/apply may proceed based on approval status."""
    if record.state == "pending":
        return False, "pending_approval: approval has not been resolved"
    if record.state == "rejected":
        return False, "approval_rejected: plan approval was rejected"
    if record.state == "approved":
        if record.is_mock_approved:
            return True, "mock_approved"
        if record.is_human_approved:
            return True, "human_approved"
        return True, "approved"
    return False, f"unsupported_state: approval is in state '{record.state}'"


def handle_approval_resolve_rpc(
    record: ApprovalRecord,
    params: dict[str, Any],
    *,
    approval_mode: str = "mock_approved",
    operator_token: str | None = None,
) -> dict[str, Any]:
    """RPC handler matching Runtime Protocol v0 approval/resolve entrypoint."""
    approval_id = params.get("approvalId")
    if approval_id and approval_id != record.approval_id:
        raise ApprovalBindingMismatchError(
            f"ApprovalID mismatch: param '{approval_id}' != record '{record.approval_id}'"
        )

    plan_id = params.get("planId") or ""
    plan_hash = params.get("planHash") or ""
    decision = params.get("decision") or "approved"
    approver = params.get("approver")

    resolved = resolve_approval(
        record,
        plan_id=plan_id,
        plan_hash=plan_hash,
        decision=decision,
        approver=approver,
        mode=approval_mode,
        operator_token=operator_token,
    )
    return {"approval": resolved.to_dict()}
