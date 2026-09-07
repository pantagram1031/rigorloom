#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Completion card 1 matrix: script-owned export safety evidence.

This harness produces machine-readable PASS / FAIL / NOT_RUN rows for:
1) writer destination preservation tests,
2) export publish crash + destination preservation matrix tests,
3) native force-quit evidence placeholder (NOT_RUN until Windows runner executes).
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


def build_report(
    *,
    runner: Runner = run_command,
    platform: str | None = None,
) -> dict:
    platform = platform or sys.platform
    checks: list[dict] = []
    for spec in PYTEST_ROWS:
        result = runner(spec["command"], CHECK_TIMEOUT_SECONDS)
        checks.append(_row_for_result(spec, result))

    checks.append(
        {
            "id": "native_force_quit_export",
            "name": "Native force-quit during export preserves prior destination",
            "status": STATUS_NOT_RUN,
            "reason": "requires_windows_runner",
            "detail": (
                "Native force-quit evidence is intentionally NOT_RUN until a "
                "Windows runner executes the force-quit run-card."
            ),
            "platform": platform,
        }
    )

    summary = {
        "pass": sum(1 for row in checks if row["status"] == STATUS_PASS),
        "fail": sum(1 for row in checks if row["status"] == STATUS_FAIL),
        "not_run": sum(1 for row in checks if row["status"] == STATUS_NOT_RUN),
    }
    return {
        "card": "completion-card-1",
        "topic": "export-safety install-candidate matrix harness",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "checks": checks,
        "summary": summary,
        "ok": summary["fail"] == 0,
        "note": (
            "PASS / FAIL is script-owned. Native force-quit remains NOT_RUN "
            "until the Windows run-card executes."
        ),
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
