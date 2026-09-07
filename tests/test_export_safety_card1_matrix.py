# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess

from qa import export_safety_card1_matrix as matrix


def test_report_runs_script_owned_checks_and_counts_them():
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    report = matrix.build_report(runner=fake_runner, platform="linux")

    by_id = {row["id"]: row for row in report["checks"]}
    assert by_id["writer_dest_preserving"]["status"] == "PASS"
    assert by_id["export_publish_crash_matrix"]["status"] == "PASS"
    assert by_id["native_force_quit_export"]["status"] == "NOT_RUN"
    assert by_id["native_force_quit_export"]["reason"] == "requires_windows_runner"
    assert report["summary"] == {"pass": 2, "fail": 0, "not_run": 1}
    assert report["ok"] is True
    assert len(calls) == 2


def test_report_marks_fail_when_a_scripted_check_fails():
    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if "engine/tests/test_hwpx_write_export_safety.py" in " ".join(argv):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    report = matrix.build_report(runner=fake_runner, platform="linux")
    by_id = {row["id"]: row for row in report["checks"]}

    assert by_id["writer_dest_preserving"]["status"] == "FAIL"
    assert report["summary"] == {"pass": 1, "fail": 1, "not_run": 1}
    assert report["ok"] is False


def test_force_quit_is_not_run_until_windows_runner_executes():
    report = matrix.build_report(platform="linux")
    row = next(item for item in report["checks"] if item["id"] == "native_force_quit_export")
    assert row["status"] == "NOT_RUN"
    assert row["reason"] == "requires_windows_runner"
    assert "Windows runner" in row["detail"]
    assert "command" not in row


def test_force_quit_runs_on_windows_when_card_exists(tmp_path):
    calls: list[list[str]] = []
    evidence = tmp_path / "card1-force-quit.json"
    evidence.write_text(
        json.dumps(
            {
                "status": "PASS",
                "destPreserved": True,
                "priorDestSha256": "aa",
                "afterDestSha256": "aa",
                "exporterPid": 4242,
                "kill": {"method": "taskkill /F /PID"},
                "destination": "C:\\\\out.hwpx",
            }
        ),
        encoding="utf-8",
    )

    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    report = matrix.build_report(
        runner=fake_runner,
        platform="win32",
        force_quit_card=matrix.FORCE_QUIT_CARD,
        force_quit_evidence=evidence,
    )
    row = next(item for item in report["checks"] if item["id"] == "native_force_quit_export")
    assert row["status"] == "PASS"
    assert row["command"][-1] == str(evidence)
    assert "native_force_quit_export.py" in " ".join(row["command"])
    assert row["evidence"]["destPreserved"] is True
    assert row["evidence"]["kill"]["method"] == "taskkill /F /PID"
    assert report["summary"] == {"pass": 3, "fail": 0, "not_run": 0}
    assert len(calls) == 3


def test_force_quit_fails_on_windows_when_card_fails(tmp_path):
    evidence = tmp_path / "card1-force-quit.json"
    evidence.write_text(
        json.dumps({"status": "FAIL", "reason": "destination_not_preserved"}),
        encoding="utf-8",
    )

    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="wiped")

    report = matrix.build_report(
        runner=fake_runner,
        platform="win32",
        force_quit_evidence=evidence,
    )
    row = next(item for item in report["checks"] if item["id"] == "native_force_quit_export")
    assert row["status"] == "FAIL"
    assert row["reason"] == "destination_not_preserved"
    assert report["ok"] is False


def test_force_quit_not_run_on_windows_when_card_missing(tmp_path):
    missing = tmp_path / "missing-card.py"

    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    report = matrix.build_report(
        runner=fake_runner,
        platform="win32",
        force_quit_card=missing,
    )
    row = next(item for item in report["checks"] if item["id"] == "native_force_quit_export")
    assert row["status"] == "NOT_RUN"
    assert row["reason"] == "run_card_missing"
    assert report["summary"]["not_run"] == 1


def test_force_quit_maps_card_exit_2_to_not_run(tmp_path):
    evidence = tmp_path / "card1-force-quit.json"
    evidence.write_text(json.dumps({"status": "NOT_RUN", "reason": "rustc_missing"}), encoding="utf-8")

    def fake_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="")

    report = matrix.build_report(
        runner=fake_runner,
        platform="win32",
        force_quit_evidence=evidence,
    )
    row = next(item for item in report["checks"] if item["id"] == "native_force_quit_export")
    assert row["status"] == "NOT_RUN"
    assert row["reason"] == "rustc_missing"
    assert report["ok"] is True
