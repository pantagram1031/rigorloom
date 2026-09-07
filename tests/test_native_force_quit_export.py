# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from qa import native_force_quit_export as card


def test_run_card_refuses_non_windows_without_posix_flag(tmp_path):
    evidence = tmp_path / "card1-force-quit.json"
    report = card.run_force_quit_export(
        json_out=evidence,
        scratch=tmp_path / "scratch",
        platform="linux",
        allow_posix_kill=False,
    )
    assert report["status"] == "NOT_RUN"
    assert report["reason"] == "requires_windows_runner"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_RUN"


def test_run_card_reports_missing_rustc(tmp_path, monkeypatch):
    evidence = tmp_path / "card1-force-quit.json"
    monkeypatch.setattr(card.shutil, "which", lambda _name: None)
    report = card.run_force_quit_export(
        json_out=evidence,
        scratch=tmp_path / "scratch",
        platform="linux",
        allow_posix_kill=True,
        rustc=None,
    )
    assert report["status"] == "NOT_RUN"
    assert report["reason"] == "rustc_missing"


def test_force_kill_uses_taskkill_on_windows(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(card.subprocess, "run", fake_run)
    result = card.force_kill(99, platform="win32")
    assert result["method"] == "taskkill /F /PID"
    assert calls[0] == ["taskkill", "/F", "/PID", "99"]


def test_force_kill_falls_back_to_stop_process(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if argv and argv[0] == "taskkill":
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "denied"})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(card.subprocess, "run", fake_run)
    result = card.force_kill(100, platform="win32")
    assert result["method"] == "Stop-Process -Force"
    assert "Stop-Process -Id 100 -Force" in calls[1]


def test_force_kill_uses_windows_path_even_if_labeled_linux(monkeypatch):
    """A linux-labeled helper must not evaluate signal.SIGKILL on win32."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(card.sys, "platform", "win32")
    monkeypatch.setattr(card.subprocess, "run", fake_run)
    result = card.force_kill(7, platform="linux")
    assert result["method"] == "taskkill /F /PID"
    assert calls[0] == ["taskkill", "/F", "/PID", "7"]


def test_posix_force_signal_does_not_require_sigkill(monkeypatch):
    class _NoSigkill:
        SIGTERM = 15

    monkeypatch.setattr(card, "signal", _NoSigkill)
    sig, method = card.posix_force_signal()
    assert sig == 15
    assert method == "SIGTERM"


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc is not installed")
def test_hold_helper_force_quit_preserves_prior_dest(tmp_path):
    evidence = tmp_path / "card1-force-quit.json"
    scratch = tmp_path / "scratch"
    windows = sys.platform.startswith("win")
    report = card.run_force_quit_export(
        json_out=evidence,
        scratch=scratch,
        allow_posix_kill=not windows,
    )
    assert report["status"] == "PASS", json.dumps(report, indent=2)
    assert report["destPreserved"] is True
    assert report["priorDestSha256"] == report["afterDestSha256"]
    if windows:
        assert report["kill"]["method"] in {"taskkill /F /PID", "Stop-Process -Force"}
    else:
        assert report["kill"]["method"] in {"SIGKILL", "SIGTERM"}
    dest = Path(report["destination"])
    assert dest.read_bytes() == card.PRIOR_DEST
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["destPreserved"] is True
