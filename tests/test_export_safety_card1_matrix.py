# -*- coding: utf-8 -*-
from __future__ import annotations

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
