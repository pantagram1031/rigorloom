"""Minimal AgentHost and Runtime glue for QA harness unattended execution.

Audit W0 item 8 from PR #342 fitness report:
Wires `approval/resolve` into agent paths so card 4 and unattended agent tests
can resolve approvals in `mock_approved` mode for plan apply gating without a
human click.

Invariants:
- The agent connection never approves its own plan (authority split intact).
- Host authority resolves approval via `approval/resolve` using `mock_approved`.
- Never claims `human_approved` or GUI/IME PASS.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from qa.approval import (
    ApprovalRecord,
    can_apply_plan,
    resolve_approval,
)


def resolve_agenthost_plan_approval(
    record: ApprovalRecord,
    plan_id: str,
    plan_hash: str,
    *,
    decision: str = "approved",
    approval_mode: str = "mock_approved",
    operator_token: str | None = None,
    workspace_root: Path | None = None,
) -> ApprovalRecord:
    """Resolve an approval originated by Agent Host.

    If workspace_root has runtime/scripts/cli.py, can optionally delegate to runtime CLI.
    Otherwise resolves directly via qa.approval protocol contract.
    """
    if workspace_root is not None:
        cli_py = workspace_root / "runtime/scripts/cli.py"
        if cli_py.exists() and approval_mode == "mock_approved":
            # Runtime CLI is present in workspace: execute host-authority approve command
            root = workspace_root / "work/runtime"
            root.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable,
                str(cli_py),
                "--root",
                str(root),
                "approve",
                "--approval",
                record.approval_id,
                "--plan",
                plan_id,
                "--plan-hash",
                plan_hash,
                "--decision",
                decision,
                "--approver",
                "mock_approved",
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=False)
            except Exception:
                pass

    return resolve_approval(
        record,
        plan_id=plan_id,
        plan_hash=plan_hash,
        decision=decision,
        approver="mock_approved" if approval_mode == "mock_approved" else None,
        mode=approval_mode,
        operator_token=operator_token,
    )


def gate_agenthost_plan_apply(record: ApprovalRecord) -> tuple[bool, str]:
    """Check whether an agent plan can proceed to plan/apply."""
    return can_apply_plan(record)
