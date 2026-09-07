"""Deterministic verifier stub for unattended QA runs.

Maps exit codes and execution states into standardized verdicts:
- PASS: Command succeeded (exit code 0) and assertions held.
- FAIL: Command returned non-zero exit code or failed test assertions.
- NOT_RUN: Test was skipped by configuration or requires unavailable target environment
           (e.g., Windows GUI/IME/installer on non-desktop/headless runners).
- BLOCKED: Missing prerequisites, missing target files, or disallowed command.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CardVerdict:
    card_id: str
    status: str  # PASS, FAIL, NOT_RUN, BLOCKED
    exit_code: int | None
    reason: str
    command: list[str] | None = None
    output_files: list[str] | None = None
    approval_mode: str = "human_approved"
    mock_approved: bool = False
    gui_claimed: bool = False  # Always False: deterministic verification never claims GUI/IME success


def verify_exit_code(
    card_id: str,
    exit_code: int | None,
    *,
    reason: str = "",
    command: list[str] | None = None,
    output_files: list[str] | None = None,
    is_blocked: bool = False,
    is_not_run: bool = False,
    approval_mode: str = "human_approved",
    mock_approved: bool = False,
) -> CardVerdict:
    """Deterministically map exit codes and execution context to status."""
    if is_not_run:
        status = "NOT_RUN"
        code = None
        detail = reason or "Skipped or environment unsupported"
    elif is_blocked:
        status = "BLOCKED"
        code = exit_code
        detail = reason or "Execution blocked by unmet prerequisite or security whitelist"
    elif exit_code is None:
        status = "BLOCKED"
        code = None
        detail = reason or "Process did not return an exit code"
    elif exit_code == 0:
        status = "PASS"
        code = 0
        detail = reason or "Command completed successfully with exit code 0"
    else:
        status = "FAIL"
        code = exit_code
        detail = reason or f"Command failed with non-zero exit code {exit_code}"

    return CardVerdict(
        card_id=card_id,
        status=status,
        exit_code=code,
        reason=detail,
        command=command,
        output_files=output_files or [],
        approval_mode=approval_mode,
        mock_approved=mock_approved,
        gui_claimed=False,
    )


def summarize_verdicts(
    verdicts: list[CardVerdict],
    approval_mode: str = "human_approved",
) -> dict[str, Any]:
    """Produce an aggregate verdict summary dictionary."""
    counts = {"PASS": 0, "FAIL": 0, "NOT_RUN": 0, "BLOCKED": 0}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1

    overall = "PASS"
    if counts["FAIL"] > 0:
        overall = "FAIL"
    elif counts["BLOCKED"] > 0:
        overall = "BLOCKED"
    elif counts["PASS"] == 0 and counts["NOT_RUN"] > 0:
        overall = "NOT_RUN"

    mock_count = sum(1 for v in verdicts if v.mock_approved)

    return {
        "overall_status": overall,
        "counts": counts,
        "approval_mode": approval_mode,
        "mock_approved_count": mock_count,
        "gui_ime_claimed": False,
        "verdicts": [asdict(v) for v in verdicts],
    }


def write_verdict_summary(summary: dict[str, Any], output_path: Path) -> None:
    """Write summary to JSON file deterministically."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
