# -*- coding: utf-8 -*-
"""Structural checks for the epoch hash evidence collector.

These cases do not run PowerShell, do not build a Windows install, and do
not claim Card 4 IME or Card 5 GUI PASS. They only pin the collector's
honest-hash contract onto this tip.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "desktop" / "scripts" / "capture-build-evidence.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_collector_is_present_and_does_not_claim_card5_gui_pass():
    assert SCRIPT.is_file()
    assert "rigorloom/build-evidence-manifest/v1" in SOURCE
    assert "card5Pass = $false" in SOURCE
    assert "guiImeClaimed = $false" in SOURCE
    assert "HASHED_NOT_UI_ACCEPTED" in SOURCE
    assert "HASHED_BUILD_ARTIFACTS" in SOURCE
    assert "HASHED_INSTALL_PAYLOAD" in SOURCE
    assert "Hash linkage is not GUI, IME, user-flow, or uninstall acceptance." in SOURCE


def test_collector_refuses_dirty_source_and_empty_evidence_dir():
    assert "Tracked source is dirty" in SOURCE
    assert "Evidence directory is not empty" in SOURCE
    assert "AllowInstallerPatchedExecutable" in SOURCE


def test_collector_has_no_user_profile_default():
    assert "Hayul" not in SOURCE
    assert "C:\\Users\\" not in SOURCE
    assert r"C:\Users" not in SOURCE
    assert "LOCALAPPDATA" not in SOURCE
    assert "$env:USERPROFILE" not in SOURCE
