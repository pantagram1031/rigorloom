#!/usr/bin/env python3
"""Run-Cards unattended QA runner (Python implementation).

Performs:
1. Job specification parsing and whitelist validation.
2. Read-only environment preflight checks (OS, disk free, tools present).
3. Test suite invocation for targeted card IDs (e.g. c1, c2, c3).
4. Evidence output logging (preflight JSON, Junit XML / JSONL stubs, verdict JSON).
5. Deterministic exit code mapping (PASS / FAIL / NOT_RUN / BLOCKED) with no GUI/IME success claims.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Ensure qa directory and repo root are importable regardless of invocation directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.verifier import CardVerdict, summarize_verdicts, verify_exit_code, write_verdict_summary


def probe_environment(workspace_root: Path) -> dict[str, Any]:
    """Perform read-only environment preflight checks."""
    total, used, free = shutil.disk_usage(workspace_root)
    # Check PATH and user local bin for pytest if not found
    pytest_bin = shutil.which("pytest")
    if not pytest_bin:
        local_pytest = Path.home() / ".local/bin/pytest"
        if local_pytest.exists() and os.access(local_pytest, os.X_OK):
            pytest_bin = str(local_pytest)

    tools = {
        "python3": shutil.which("python3") or shutil.which("python"),
        "pytest": pytest_bin,
        "rustc": shutil.which("rustc"),
        "cargo": shutil.which("cargo"),
        "pwsh": shutil.which("pwsh") or shutil.which("powershell"),
        "git": shutil.which("git"),
        "node": shutil.which("node"),
        "npm": shutil.which("npm"),
    }

    git_info: dict[str, Any] = {"is_repo": False, "sha": None, "branch": None}
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if head_proc.returncode == 0:
            git_info["is_repo"] = True
            git_info["sha"] = head_proc.stdout.strip()

        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if branch_proc.returncode == 0:
            git_info["branch"] = branch_proc.stdout.strip()
    except Exception as exc:
        git_info["error"] = str(exc)

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "disk_bytes": {
            "total": total,
            "used": used,
            "free": free,
            "free_gb": round(free / (1024**3), 2),
        },
        "tools_present": {k: v is not None for k, v in tools.items()},
        "tool_paths": {k: v for k, v in tools.items() if v is not None},
        "git": git_info,
        "runner_capabilities": {
            "supports_windows_gui": False,
            "supports_windows_ime": False,
            "supports_windows_installer": False,
            "supports_headless_cli": True,
        },
    }


def execute_card(
    card_id: str,
    job: dict[str, Any],
    workspace_root: Path,
    evidence_dir: Path,
) -> CardVerdict:
    """Execute tests for a specific card id if allowed and available."""
    allowed_commands = job.get("allowed_commands", [])
    if card_id not in allowed_commands and "all" not in allowed_commands:
        return verify_exit_code(
            card_id,
            None,
            reason=f"Card '{card_id}' is not in job allowed_commands whitelist",
            is_blocked=True,
        )

    junit_file = evidence_dir / f"junit-{card_id}.xml"
    log_file = evidence_dir / f"{card_id}.log"
    jsonl_file = evidence_dir / f"{card_id}.jsonl"

    if card_id == "c1":
        # Card 1: dest-preserving export pair (pytest + rustc harness if available)
        test_py = [
            "tests/test_desktop_export_safety.py",
            "engine/tests/test_hwpx_write_export_safety.py",
        ]
        existing_py = [p for p in test_py if (workspace_root / p).exists()]

        rust_harness = workspace_root / "tests/desktop_export_safety_harness.rs"
        has_rust = rust_harness.exists() and shutil.which("rustc") is not None

        if not existing_py and not has_rust:
            return verify_exit_code(
                card_id,
                None,
                reason="Card 1 test files not present in checked-out tree (tests/test_desktop_export_safety.py or rust harness)",
                is_not_run=True,
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *existing_py,
            f"--junitxml={junit_file}",
            "-q",
        ]
        try:
            with log_file.open("w", encoding="utf-8") as out:
                proc = subprocess.run(
                    cmd,
                    cwd=workspace_root,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            
            # Record jsonl stub
            _write_jsonl_record(jsonl_file, card_id, proc.returncode, "pytest", cmd)

            # If rust harness is present, also execute it if rustc available
            if has_rust and proc.returncode == 0:
                bin_path = evidence_dir / "export_safety_harness_bin"
                rustc_cmd = [
                    "rustc",
                    "--test",
                    "--edition",
                    "2021",
                    "-o",
                    str(bin_path),
                    str(rust_harness),
                ]
                with log_file.open("a", encoding="utf-8") as out:
                    out.write("\n--- Rust Harness Compilation ---\n")
                    r_build = subprocess.run(rustc_cmd, cwd=workspace_root, stdout=out, stderr=subprocess.STDOUT, check=False)
                    if r_build.returncode == 0:
                        out.write("\n--- Rust Harness Execution ---\n")
                        r_run = subprocess.run([str(bin_path), "--test-threads=1"], cwd=workspace_root, stdout=out, stderr=subprocess.STDOUT, check=False)
                        _write_jsonl_record(jsonl_file, card_id, r_run.returncode, "rustc", [str(bin_path)])
                        if r_run.returncode != 0:
                            return verify_exit_code(card_id, r_run.returncode, reason="Rust export safety harness failed", command=[str(bin_path)], output_files=[str(junit_file), str(log_file)])

            return verify_exit_code(
                card_id,
                proc.returncode,
                reason="Completed pytest execution for card 1",
                command=cmd,
                output_files=[str(junit_file), str(log_file), str(jsonl_file)],
            )
        except Exception as exc:
            return verify_exit_code(card_id, 1, reason=f"Execution error: {exc}", is_blocked=True)

    elif card_id == "c2":
        # Card 2: revision-coherence tests (#330)
        test_py = [
            "tests/test_runtime_revision_coherence.py",
            "tests/test_desktop_revision_coherence.py",
        ]
        existing_py = [p for p in test_py if (workspace_root / p).exists()]
        if not existing_py:
            return verify_exit_code(
                card_id,
                None,
                reason="Card 2 test files not present in tree (tests/test_runtime_revision_coherence.py)",
                is_not_run=True,
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *existing_py,
            f"--junitxml={junit_file}",
            "-q",
        ]
        try:
            with log_file.open("w", encoding="utf-8") as out:
                proc = subprocess.run(
                    cmd,
                    cwd=workspace_root,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            _write_jsonl_record(jsonl_file, card_id, proc.returncode, "pytest", cmd)
            return verify_exit_code(
                card_id,
                proc.returncode,
                reason="Completed pytest execution for card 2",
                command=cmd,
                output_files=[str(junit_file), str(log_file), str(jsonl_file)],
            )
        except Exception as exc:
            return verify_exit_code(card_id, 1, reason=f"Execution error: {exc}", is_blocked=True)

    elif card_id == "c3":
        # Card 3: run-scoped edit tests (#333)
        test_py = [
            "tests/test_desktop_run_scoped_edit.py",
            "tests/test_desktop_revision_coherence.py",
        ]
        existing_py = [p for p in test_py if (workspace_root / p).exists()]
        if not existing_py:
            return verify_exit_code(
                card_id,
                None,
                reason="Card 3 test files not present in tree (tests/test_desktop_run_scoped_edit.py)",
                is_not_run=True,
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *existing_py,
            f"--junitxml={junit_file}",
            "-q",
        ]
        try:
            with log_file.open("w", encoding="utf-8") as out:
                proc = subprocess.run(
                    cmd,
                    cwd=workspace_root,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            _write_jsonl_record(jsonl_file, card_id, proc.returncode, "pytest", cmd)
            return verify_exit_code(
                card_id,
                proc.returncode,
                reason="Completed pytest execution for card 3",
                command=cmd,
                output_files=[str(junit_file), str(log_file), str(jsonl_file)],
            )
        except Exception as exc:
            return verify_exit_code(card_id, 1, reason=f"Execution error: {exc}", is_blocked=True)

    elif card_id == "c4":
        # Card 4: Korean mixed-format E2E. PREP ONLY. The harness probes the
        # fixture, scaffolds the operator's evidence manifest and, if one has
        # been filled in, checks it for completeness. The verdict is ALWAYS
        # NOT_RUN here: PASS is a human reading real GUI evidence from an
        # installed build, never this script.
        # Audit W0 Item 8: wires approval/resolve into harness with mock_approved mode.
        from qa.card4_prep import (
            DEFAULT_FIXTURE,
            create_mock_approval_artifact,
            probe_fixture,
            scaffold_manifest,
            validate_manifest,
        )

        approval_mode = job.get("approval_mode") or (job.get("metadata") or {}).get("approval_mode", "human_approved")
        is_mock_approved = approval_mode == "mock_approved"

        fixture_rel = (job.get("metadata") or {}).get("card4_fixture") or DEFAULT_FIXTURE
        fixture = Path(fixture_rel)
        if not fixture.is_absolute():
            fixture = workspace_root / fixture
        probe = probe_fixture(fixture)
        probe_file = evidence_dir / "c4-fixture-probe.json"
        with probe_file.open("w", encoding="utf-8") as f:
            json.dump(probe, f, indent=2, ensure_ascii=False)
            f.write("\n")
        manifest_file = scaffold_manifest(
            evidence_dir, fixture, job.get("sha"), workspace_root, approval_mode=approval_mode
        )

        output_files = [str(probe_file), str(manifest_file)]
        if is_mock_approved:
            mock_appr_file = evidence_dir / "c4-mock-approval.json"
            if not mock_appr_file.exists():
                create_mock_approval_artifact(
                    evidence_dir,
                    plan_id=f"plan-c4-{job.get('run_id', 'mock')}",
                    plan_hash=f"hash-{probe.get('sha256', 'mock')[:16]}",
                )
            output_files.append(str(mock_appr_file))

        check = validate_manifest(manifest_file, workspace_root)
        check_file = evidence_dir / "c4-manifest-check.json"
        with check_file.open("w", encoding="utf-8") as f:
            json.dump(check, f, indent=2, ensure_ascii=False)
            f.write("\n")
        output_files.extend([str(check_file), str(jsonl_file)])

        _write_jsonl_record(
            jsonl_file,
            card_id,
            0,
            "card4_prep",
            ["probe", "scaffold", "validate"],
            status="NOT_RUN",
            approval_mode=approval_mode,
            mock_approved=is_mock_approved,
        )

        if is_mock_approved:
            reason = (
                f"Card 4 PREP (approval_mode: mock_approved): fixture {'eligible' if probe.get('eligible') else 'NOT eligible (' + probe.get('reason', '') + ')'}; "
                f"evidence {check['result']} ({len(check['problems'])} open items); "
                "approval/resolve wired with mock_approved for unattended plan apply gating. "
                "Verdict remains NOT_RUN: real human operator approval and installed Windows GUI/IME runner required for certified PASS."
            )
        else:
            reason = (
                f"Card 4 PREP (approval_mode: human_approved): fixture {'eligible' if probe.get('eligible') else 'NOT eligible (' + probe.get('reason', '') + ')'}; "
                f"evidence {check['result']} ({len(check['problems'])} open items). "
                "Verdict stays NOT_RUN until a human records a verdict on real installed-build GUI evidence; mock_approved mode is off."
            )

        return verify_exit_code(
            card_id,
            None,
            reason=reason,
            command=[sys.executable, "qa/card4_prep.py", "probe|scaffold|validate"],
            output_files=output_files,
            is_not_run=True,
            approval_mode=approval_mode,
            mock_approved=is_mock_approved,
        )

    elif card_id in ("c5", "gui", "ime", "installer"):
        # Explicitly marked as NOT_RUN per contract until local runner exists
        _write_jsonl_record(jsonl_file, card_id, 0, "not_run", [card_id], status="NOT_RUN")
        return verify_exit_code(
            card_id,
            None,
            reason=f"Interactive/installer card '{card_id}' is NOT_RUN in unattended environment without local runner",
            is_not_run=True,
        )

    else:
        return verify_exit_code(
            card_id,
            None,
            reason=f"Unknown card identifier '{card_id}'",
            is_blocked=True,
        )


def _write_jsonl_record(
    path: Path,
    card_id: str,
    exit_code: int | None,
    runner: str,
    cmd: list[str],
    status: str | None = None,
    approval_mode: str = "human_approved",
    mock_approved: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "card_id": card_id,
        "runner": runner,
        "command": cmd,
        "exit_code": exit_code,
        "status": status or ("PASS" if exit_code == 0 else "FAIL"),
        "approval_mode": approval_mode,
        "mock_approved": mock_approved,
        "gui_ime_claimed": False,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def run_job(job_path: Path, workspace_root: Path) -> dict[str, Any]:
    """Execute full unattended QA job."""
    with job_path.open("r", encoding="utf-8") as f:
        job = json.load(f)

    approval_mode = job.get("approval_mode") or (job.get("metadata") or {}).get("approval_mode", "human_approved")
    is_mock_approved = approval_mode == "mock_approved"

    evidence_dir = Path(job.get("evidence_dir", "evidence"))
    if not evidence_dir.is_absolute():
        evidence_dir = workspace_root / evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # 1. Environment Preflight
    preflight = probe_environment(workspace_root)
    preflight_file = evidence_dir / "preflight.json"
    with preflight_file.open("w", encoding="utf-8") as f:
        json.dump(preflight, f, indent=2, sort_keys=True)
        f.write("\n")

    # 2. Targeted Cards
    cards_to_run = job.get("cards", ["c1", "c2", "c3"])
    verdicts: list[CardVerdict] = []
    for card in cards_to_run:
        v = execute_card(card, job, workspace_root, evidence_dir)
        verdicts.append(v)

    # 3. Deterministic Verdict Summary
    summary = summarize_verdicts(verdicts, approval_mode=approval_mode)
    summary["candidate_id"] = job.get("candidate_id")
    summary["run_id"] = job.get("run_id")
    summary["sha"] = job.get("sha")
    summary["requested_model"] = job.get("requested_model", "gemini-3.8-flash")
    summary["approval_mode"] = approval_mode
    summary["mock_approved"] = is_mock_approved
    summary["preflight_file"] = str(preflight_file)

    verdict_file = evidence_dir / "verdict.json"
    write_verdict_summary(summary, verdict_file)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run-Cards unattended QA evidence collector")
    parser.add_argument("--job", type=Path, default=Path("qa/job.json"), help="Path to job.json definition")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace root directory")
    args = parser.parse_args()

    if not args.job.exists():
        sys.stderr.write(f"Error: Job file {args.job} not found.\n")
        return 2

    summary = run_job(args.job.resolve(), args.workspace.resolve())
    print(json.dumps(summary, indent=2))
    return 0 if summary["overall_status"] in ("PASS", "NOT_RUN") else 1


if __name__ == "__main__":
    sys.exit(main())
