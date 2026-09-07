#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card1 native force-quit Run-Card.

Starts dest-preserving export publish (the same `export.rs` path the rust
matrix compiles), parks after staging, then force-kills the exporting
process. Asserts prior destination bytes are unchanged.

Windows kill is `taskkill /F /PID` with `Stop-Process -Force` as fallback.
Linux/macOS only run when `--allow-posix-kill` is passed (SIGKILL); the
Card1 matrix never treats that as Windows evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLD_RS = Path(__file__).resolve().parent / "native_force_quit_hold.rs"
DEFAULT_JSON_OUT = Path(__file__).resolve().parent / "_artifacts" / "card1-force-quit.json"
PRIOR_DEST = b"CARD1-PRIOR-DESTINATION-BYTES"
ARTIFACT_BYTES = b"CARD1-NEW-ARTIFACT-BYTES"
RECEIPT_BYTES = b'{"ok":true,"card":"completion-card-1"}'
HOLD_READY_TIMEOUT_SECONDS = 30.0
KILL_WAIT_SECONDS = 15.0
COMPILE_TIMEOUT_SECONDS = 60.0

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith("win")


def write_evidence(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def force_kill(pid: int, *, platform: str | None = None) -> dict:
    """Kill `pid` with a native force-quit. Returns method + command output."""
    platform = platform or sys.platform
    if is_windows(platform):
        taskkill = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if taskkill.returncode == 0:
            return {
                "method": "taskkill /F /PID",
                "command": ["taskkill", "/F", "/PID", str(pid)],
                "exitCode": taskkill.returncode,
                "stdout": (taskkill.stdout or "")[-1000:],
                "stderr": (taskkill.stderr or "")[-1000:],
            }
        stop = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Stop-Process -Id {pid} -Force",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "method": "Stop-Process -Force",
            "command": [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Stop-Process -Id {pid} -Force",
            ],
            "exitCode": stop.returncode,
            "stdout": (stop.stdout or "")[-1000:],
            "stderr": (stop.stderr or "")[-1000:],
            "taskkill": {
                "exitCode": taskkill.returncode,
                "stdout": (taskkill.stdout or "")[-1000:],
                "stderr": (taskkill.stderr or "")[-1000:],
            },
        }
    try:
        os.kill(pid, signal.SIGKILL)
        exit_code = 0
        stderr = ""
    except ProcessLookupError as exc:
        exit_code = 1
        stderr = str(exc)
    return {
        "method": "SIGKILL",
        "command": ["kill", "-9", str(pid)],
        "exitCode": exit_code,
        "stdout": "",
        "stderr": stderr,
    }


def compile_hold_helper(binary: Path, rustc: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [rustc, "--edition", "2021", "-o", str(binary), str(HOLD_RS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT_SECONDS,
        check=False,
    )


def wait_for_ready(ready: Path, proc: subprocess.Popen[str], timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ready.is_file() and ready.stat().st_size > 0:
            return ready.read_text(encoding="utf-8")
        if proc.poll() is not None:
            return None
        time.sleep(0.05)
    return None


def run_force_quit_export(
    *,
    json_out: Path,
    scratch: Path | None = None,
    platform: str | None = None,
    allow_posix_kill: bool = False,
    rustc: str | None = None,
) -> dict:
    platform = platform or sys.platform
    generated_at = datetime.now(timezone.utc).isoformat()
    report: dict = {
        "card": "completion-card-1",
        "id": "native_force_quit_export",
        "name": "Native force-quit during export preserves prior destination",
        "generatedAt": generated_at,
        "platform": platform,
        "holdAfter": "Staged",
        "status": STATUS_NOT_RUN,
    }

    if not is_windows(platform) and not allow_posix_kill:
        report.update(
            {
                "status": STATUS_NOT_RUN,
                "reason": "requires_windows_runner",
                "detail": (
                    "Native force-quit evidence uses taskkill / Stop-Process. "
                    "Re-run on Windows, or pass --allow-posix-kill only for "
                    "local helper checks (the Card1 matrix ignores that)."
                ),
            }
        )
        write_evidence(json_out, report)
        return report

    if not HOLD_RS.is_file():
        report.update(
            {
                "status": STATUS_NOT_RUN,
                "reason": "hold_helper_missing",
                "detail": f"missing {HOLD_RS}",
            }
        )
        write_evidence(json_out, report)
        return report

    rustc = rustc or shutil.which("rustc")
    if rustc is None:
        report.update(
            {
                "status": STATUS_NOT_RUN,
                "reason": "rustc_missing",
                "detail": "rustc is required to compile qa/native_force_quit_hold.rs",
            }
        )
        write_evidence(json_out, report)
        return report

    own_scratch = scratch is None
    scratch = scratch or Path(tempfile.mkdtemp(prefix="card1-force-quit-"))
    binary = scratch / ("hold.exe" if is_windows(platform) else "hold")
    artifact = scratch / "artifact.hwpx"
    receipt = scratch / "receipt.json"
    dest = scratch / "out.hwpx"
    ready = scratch / "hold-ready.json"
    prior_sha = sha256_bytes(PRIOR_DEST)

    try:
        artifact.write_bytes(ARTIFACT_BYTES)
        receipt.write_bytes(RECEIPT_BYTES)
        dest.write_bytes(PRIOR_DEST)

        compiled = compile_hold_helper(binary, rustc)
        if compiled.returncode != 0 or not binary.is_file():
            report.update(
                {
                    "status": STATUS_FAIL,
                    "reason": "hold_helper_compile_failed",
                    "detail": (compiled.stdout or "")[-2000:] + (compiled.stderr or "")[-2000:],
                    "destination": str(dest),
                    "priorDestSha256": prior_sha,
                }
            )
            write_evidence(json_out, report)
            return report

        popen_kwargs: dict = {
            "cwd": str(scratch),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if is_windows(platform):
            # Isolate the exporter so force-quit cannot tear down this card.
            create_new_process_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            popen_kwargs["creationflags"] = create_new_process_group

        proc = subprocess.Popen(
            [
                str(binary),
                "--artifact",
                str(artifact),
                "--receipt",
                str(receipt),
                "--dest",
                str(dest),
                "--ready",
                str(ready),
            ],
            **popen_kwargs,
        )
        ready_text = wait_for_ready(ready, proc, HOLD_READY_TIMEOUT_SECONDS)
        if ready_text is None:
            stdout, stderr = ("", "")
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=5)
            elif proc.poll() is None:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
            report.update(
                {
                    "status": STATUS_FAIL,
                    "reason": "hold_ready_timeout",
                    "detail": "exporter never wrote the staged hold marker",
                    "exporterPid": proc.pid,
                    "destination": str(dest),
                    "priorDestSha256": prior_sha,
                    "stdout": (stdout or "")[-2000:],
                    "stderr": (stderr or "")[-2000:],
                }
            )
            if dest.is_file():
                after = dest.read_bytes()
                report["afterDestSha256"] = sha256_bytes(after)
                report["destPreserved"] = after == PRIOR_DEST
            write_evidence(json_out, report)
            return report

        kill = force_kill(proc.pid, platform=platform)
        try:
            proc.wait(timeout=KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=KILL_WAIT_SECONDS)

        after = dest.read_bytes() if dest.is_file() else b""
        dest_preserved = dest.is_file() and after == PRIOR_DEST
        after_sha = sha256_bytes(after) if dest.is_file() else None
        killed = proc.returncode is not None
        status = STATUS_PASS if dest_preserved and killed else STATUS_FAIL
        report.update(
            {
                "status": status,
                "kill": kill,
                "exporterPid": proc.pid,
                "exporterReturncode": proc.returncode,
                "killed": killed,
                "readyPath": str(ready),
                "readyText": ready_text.strip(),
                "destination": str(dest),
                "artifact": str(artifact),
                "receipt": str(receipt),
                "priorDestSha256": prior_sha,
                "afterDestSha256": after_sha,
                "priorDestBytes": len(PRIOR_DEST),
                "afterDestBytes": len(after) if dest.is_file() else 0,
                "destPreserved": dest_preserved,
                "destExists": dest.is_file(),
            }
        )
        if status == STATUS_FAIL:
            report["reason"] = (
                "destination_not_preserved" if not dest_preserved else "exporter_still_alive"
            )
        write_evidence(json_out, report)
        return report
    finally:
        if own_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        default=str(DEFAULT_JSON_OUT),
        help="Machine-readable PASS/FAIL evidence path.",
    )
    parser.add_argument(
        "--scratch",
        default=None,
        help="Optional scratch directory (kept). Default is a temp dir.",
    )
    parser.add_argument(
        "--allow-posix-kill",
        action="store_true",
        help="Allow SIGKILL on non-Windows for helper checks. Matrix ignores this.",
    )
    args = parser.parse_args()
    report = run_force_quit_export(
        json_out=Path(args.json_out),
        scratch=Path(args.scratch) if args.scratch else None,
        allow_posix_kill=args.allow_posix_kill,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    status = report.get("status")
    if status == STATUS_PASS:
        return EXIT_PASS
    if status == STATUS_NOT_RUN:
        return EXIT_NOT_RUN
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
