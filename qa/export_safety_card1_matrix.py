#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Completion card 1 matrix: script-owned export safety evidence.

This harness produces machine-readable PASS / FAIL / NOT_RUN rows for:
1) writer destination preservation tests,
2) export publish crash + destination preservation matrix tests,
3) native force-quit during export (Windows Run-Card only).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]

ROOT = Path(__file__).resolve().parents[1]
CHECK_TIMEOUT_SECONDS = 180.0
FORCE_QUIT_TIMEOUT_SECONDS = 120.0
FORCE_QUIT_CARD = ROOT / "qa" / "native_force_quit_export.py"
FORCE_QUIT_EVIDENCE = ROOT / "qa" / "_artifacts" / "card1-force-quit.json"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"

PYTEST_ROWS = [
    {
        "id": "writer_dest_preserving",
        "name": "Writer keeps destination bytes on failure",
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "engine/tests/test_hwpx_write_export_safety.py",
        ],
    },
    {
        "id": "export_publish_crash_matrix",
        "name": "Export publish matrix keeps destination through crash points",
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_desktop_export_safety.py::test_export_safety_rust_matrix",
        ],
    },
]


def run_command(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _row_for_result(spec: dict, result: subprocess.CompletedProcess[str]) -> dict:
    status = STATUS_PASS if result.returncode == 0 else STATUS_FAIL
    return {
        "id": spec["id"],
        "name": spec["name"],
        "status": status,
        "command": spec["command"],
        "exitCode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def _is_windows(platform: str) -> bool:
    return platform.startswith("win")


def _force_quit_not_run(*, platform: str, reason: str, detail: str, **extra: object) -> dict:
    row = {
        "id": "native_force_quit_export",
        "name": "Native force-quit during export preserves prior destination",
        "status": STATUS_NOT_RUN,
        "reason": reason,
        "detail": detail,
        "platform": platform,
    }
    row.update(extra)
    return row


def _force_quit_row(
    *,
    runner: Runner,
    platform: str,
    force_quit_card: Path,
    evidence_path: Path,
) -> dict:
    if not _is_windows(platform):
        return _force_quit_not_run(
            platform=platform,
            reason="requires_windows_runner",
            detail=(
                "Native force-quit evidence is intentionally NOT_RUN until a "
                "Windows runner executes qa/native_force_quit_export.py "
                "(or qa/native_force_quit_export.ps1)."
            ),
        )
    if not force_quit_card.is_file():
        return _force_quit_not_run(
            platform=platform,
            reason="run_card_missing",
            detail=f"Windows Run-Card is not present at {force_quit_card}",
        )

    command = [
        sys.executable,
        str(force_quit_card),
        "--json-out",
        str(evidence_path),
    ]
    result = runner(command, FORCE_QUIT_TIMEOUT_SECONDS)
    evidence = None
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            evidence = None

    if result.returncode == 0:
        status = STATUS_PASS
        reason = None
    elif result.returncode == 2:
        status = STATUS_NOT_RUN
        reason = (evidence or {}).get("reason") or "run_card_not_run"
    else:
        status = STATUS_FAIL
        reason = (evidence or {}).get("reason") or "run_card_failed"

    row = {
        "id": "native_force_quit_export",
        "name": "Native force-quit during export preserves prior destination",
        "status": status,
        "command": command,
        "exitCode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "evidencePath": str(evidence_path),
        "platform": platform,
    }
    if reason:
        row["reason"] = reason
    if evidence:
        row["evidence"] = {
            "status": evidence.get("status"),
            "reason": evidence.get("reason"),
            "kill": evidence.get("kill"),
            "destination": evidence.get("destination"),
            "priorDestSha256": evidence.get("priorDestSha256"),
            "afterDestSha256": evidence.get("afterDestSha256"),
            "destPreserved": evidence.get("destPreserved"),
            "exporterPid": evidence.get("exporterPid"),
        }
    return row


def build_report(
    *,
    runner: Runner = run_command,
    platform: str | None = None,
    force_quit_card: Path | None = None,
    force_quit_evidence: Path | None = None,
) -> dict:
    platform = platform or sys.platform
    card = FORCE_QUIT_CARD if force_quit_card is None else force_quit_card
    evidence = FORCE_QUIT_EVIDENCE if force_quit_evidence is None else force_quit_evidence
    checks: list[dict] = []
    for spec in PYTEST_ROWS:
        result = runner(spec["command"], CHECK_TIMEOUT_SECONDS)
        checks.append(_row_for_result(spec, result))

    checks.append(
        _force_quit_row(
            runner=runner,
            platform=platform,
            force_quit_card=card,
            evidence_path=evidence,
        )
    )

    summary = {
        "pass": sum(1 for row in checks if row["status"] == STATUS_PASS),
        "fail": sum(1 for row in checks if row["status"] == STATUS_FAIL),
        "not_run": sum(1 for row in checks if row["status"] == STATUS_NOT_RUN),
    }
    windows_note = (
        "PASS / FAIL is script-owned. On Windows the native force-quit "
        "Run-Card sets native_force_quit_export; Linux stays NOT_RUN."
    )
    linux_note = (
        "PASS / FAIL is script-owned. Native force-quit remains NOT_RUN "
        "until the Windows run-card executes."
    )
    return {
        "card": "completion-card-1",
        "topic": "export-safety install-candidate matrix harness",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "checks": checks,
        "summary": summary,
        "ok": summary["fail"] == 0,
        "note": windows_note if _is_windows(platform) else linux_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write the JSON report.",
    )
    args = parser.parse_args()

    report = build_report()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
