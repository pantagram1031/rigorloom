# -*- coding: utf-8 -*-
"""Card 5: install-candidate hash harness.

These cases do not exercise own_render, rematch, IoU, LayoutSnapshot, GUI,
IME, or a real Windows install. A synthetic evidence directory that PASSes
is a harness unit test, not an install-candidate result for this checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from qa import install_candidate_hash as card

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / "qa" / "install_candidate_hash.py").read_text(encoding="utf-8")
PS1 = (REPO / "qa" / "install_candidate_hash.ps1").read_text(encoding="utf-8")


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _context() -> dict:
    return {
        "gitSha": "aa" * 20,
        "branch": "test",
        "sourceTreeSha256": "bb" * 32,
        "note": "injected",
    }


def _complete_evidence(root: Path, *, outside: bool = True, mutate: dict | None = None) -> Path:
    files = root / "files"
    exe = _write(files / "Rigorloom.exe", b"exe-bytes")
    sidecar = _write(files / "rigorloomd.exe", b"sidecar-bytes")
    installer = _write(files / "Rigorloom_0.1.0_x64-setup.exe", b"nsis-bytes")
    manifest = {
        "schema": card.SCHEMA,
        "collectedOutsideCheckout": outside,
        "gui_ime_claimed": False,
        "source": {"gitSha": "aa" * 20, "sourceTreeSha256": "bb" * 32},
        "artifacts": {
            "exe": {"path": str(exe), "sha256": card.sha256_file(exe)},
            "sidecar": [{"path": str(sidecar), "sha256": card.sha256_file(sidecar)}],
            "installer": [{"path": str(installer), "sha256": card.sha256_file(installer)}],
        },
    }
    if mutate:
        manifest.update(mutate)
    card.write_json(root / "card5-evidence.json", manifest)
    return root


def test_source_has_no_machine_home_default():
    combined = SOURCE + PS1
    assert "Hayul" not in combined
    assert "C:\\Users\\" not in combined
    assert r"C:\Users" not in combined
    assert card.EVIDENCE_DIR_ENV == "RIGORLOOM_CARD5_EVIDENCE_DIR"
    assert "LOCALAPPDATA" not in SOURCE


def test_checkout_without_evidence_is_not_run_and_not_pass():
    report = card.build_report(
        workspace=REPO,
        environ={},
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["reason"] == "external_windows_evidence_absent"
    assert report["installCandidatePass"] is False
    assert report["guiImeClaimed"] is False
    assert report["ok"] is True
    assert "not an install candidate" in (report["detail"] or "").lower()
    summary = card.format_summary(report)
    assert "installCandidatePass: False" in summary
    assert "NOT_RUN" in summary


def test_local_checkout_artifacts_do_not_pass(tmp_path):
    workspace = tmp_path / "repo"
    exe = _write(
        workspace / "desktop/src-tauri/target/release/Rigorloom.exe",
        b"local-exe",
    )
    _write(workspace / "desktop/src-tauri/resources/rigorloomd/rigorloomd.exe", b"local-sidecar")
    _write(
        workspace / "desktop/src-tauri/target/release/bundle/nsis/Rigorloom_0.1.0_x64-setup.exe",
        b"local-nsis",
    )
    report = card.build_report(
        workspace=workspace,
        environ={},
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["installCandidatePass"] is False
    assert report["localCheckoutArtifacts"]["present"] is True
    assert report["localCheckoutArtifacts"]["exe"][0]["sha256"] == card.sha256_file(exe)
    assert "not an install candidate" in report["localCheckoutArtifacts"]["note"].lower() or "cannot PASS" in report["localCheckoutArtifacts"]["note"]


def test_evidence_inside_checkout_cannot_pass(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(workspace / "qa" / "_artifacts" / "card5")
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["reason"] == "evidence_dir_inside_checkout"
    assert report["installCandidatePass"] is False


def test_mock_collection_without_outside_flag_cannot_pass(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(tmp_path / "evidence", outside=False)
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["reason"] == "not_collected_outside_checkout"
    assert report["installCandidatePass"] is False
    assert all(row["status"] != card.STATUS_PASS for row in report["checks"])


def test_complete_external_evidence_passes(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(tmp_path / "evidence", outside=True)
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_PASS
    assert report["installCandidatePass"] is True
    assert report["guiImeClaimed"] is False
    assert report["summary"] == {"pass": 4, "fail": 0, "not_run": 0}
    by_id = {row["role"]: row for row in report["checks"]}
    assert by_id["exe"]["status"] == card.STATUS_PASS
    assert by_id["sidecar"]["status"] == card.STATUS_PASS
    assert by_id["installer"]["status"] == card.STATUS_PASS
    assert by_id["source"]["status"] == card.STATUS_PASS


def test_hash_mismatch_fails(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(
        tmp_path / "evidence",
        outside=True,
        mutate={
            "artifacts": {
                "exe": {"sha256": "cc" * 32},
                "sidecar": [{"sha256": "cc" * 32}],
                "installer": [{"sha256": "cc" * 32}],
            }
        },
    )
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_FAIL
    assert report["installCandidatePass"] is False
    assert report["ok"] is False
    assert report["reason"] == "hash_mismatch"


def test_json_only_hashes_are_not_run(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    card.write_json(
        evidence / "card5-evidence.json",
        {
            "collectedOutsideCheckout": True,
            "source": {"gitSha": "aa" * 20},
            "artifacts": {
                "exe": {"sha256": "dd" * 32},
                "sidecar": [{"sha256": "dd" * 32}],
                "installer": [{"sha256": "dd" * 32}],
            },
        },
    )
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["installCandidatePass"] is False
    assert report["reason"] == "artifact_bytes_absent_cannot_rehash"


def test_source_mismatch_fails(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(
        tmp_path / "evidence",
        outside=True,
        mutate={"source": {"gitSha": "ff" * 20, "sourceTreeSha256": "bb" * 32}},
    )
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_FAIL
    assert report["reason"] == "source_sha_mismatch"
    assert report["installCandidatePass"] is False


def test_forbidden_gui_claim_fails(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(
        tmp_path / "evidence",
        outside=True,
        mutate={"gui_ime_claimed": True},
    )
    report = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["status"] == card.STATUS_FAIL
    assert report["reason"] == "forbidden_gui_ime_or_install_claim"
    assert report["guiImeClaimed"] is False
    assert report["installCandidatePass"] is False


def test_env_evidence_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(tmp_path / "evidence", outside=True)
    report = card.build_report(
        workspace=workspace,
        environ={card.EVIDENCE_DIR_ENV: str(evidence)},
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert report["evidenceDirSource"] == "env"
    assert report["status"] == card.STATUS_PASS


def test_source_tree_manifest_is_stable(tmp_path):
    workspace = tmp_path / "tree"
    _write(workspace / "a.txt", b"one")
    _write(workspace / "b/c.txt", b"two")
    first = card.source_tree_manifest(workspace, ["a.txt", "b/c.txt"])
    second = card.source_tree_manifest(workspace, ["b/c.txt", "a.txt"])
    assert first["sha256"] == second["sha256"]
    assert first["fileCount"] == 2
    assert len(first["sha256"]) == 64


def test_collect_never_labels_pass(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    exe = _write(tmp_path / "Rigorloom.exe", b"exe-bytes")
    sidecar = _write(tmp_path / "rigorloomd.exe", b"sidecar-bytes")
    installer = _write(tmp_path / "Rigorloom_0.1.0_x64-setup.exe", b"nsis-bytes")
    report = card.collect_report(
        workspace=workspace,
        evidence_dir=evidence,
        exe=exe,
        sidecars=[sidecar],
        installers=[installer],
        outside_checkout=True,
        copy_files=True,
        hash_source_tree=False,
        checkout=_context(),
    )
    assert report["installCandidatePass"] is False
    assert report["status"] == card.STATUS_NOT_RUN
    assert report["reason"] == "collect_draft_run_verify"
    verified = card.build_report(
        workspace=workspace,
        evidence_dir=evidence,
        hash_source_tree=False,
        checkout=_context(),
        platform="linux",
    )
    assert verified["status"] == card.STATUS_PASS
    assert verified["installCandidatePass"] is True


def test_cli_linux_checkout_is_not_run(tmp_path):
    out = tmp_path / "card5-hashes.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "qa" / "install_candidate_hash.py"),
            "--workspace",
            str(REPO),
            "--no-source-tree",
            "--json-out",
            str(out),
            "--summary-only",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != card.EVIDENCE_DIR_ENV},
    )
    assert proc.returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_RUN"
    assert payload["installCandidatePass"] is False
    assert payload["guiImeClaimed"] is False
    assert "installCandidatePass: False" in proc.stdout


def test_cli_verify_mismatch_exits_fail(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = _complete_evidence(tmp_path / "evidence", outside=True)
    manifest_path = evidence / "card5-evidence.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["exe"]["sha256"] = "ee" * 32
    card.write_json(manifest_path, manifest)
    out = tmp_path / "card5-hashes.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "qa" / "install_candidate_hash.py"),
            "verify",
            "--workspace",
            str(workspace),
            "--evidence-dir",
            str(evidence),
            "--no-source-tree",
            "--json-out",
            str(out),
            "--summary-only",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == card.EXIT_FAIL
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["installCandidatePass"] is False
    assert "FAIL" in proc.stdout
