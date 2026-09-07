import json
from pathlib import Path

import pytest

from qa.verifier import verify_exit_code, summarize_verdicts
from qa.run_cards import probe_environment, run_job


def test_verifier_exit_codes():
    v_pass = verify_exit_code("c1", 0)
    assert v_pass.status == "PASS"
    assert v_pass.exit_code == 0
    assert not v_pass.gui_claimed

    v_fail = verify_exit_code("c1", 1)
    assert v_fail.status == "FAIL"
    assert v_fail.exit_code == 1
    assert not v_fail.gui_claimed

    v_not_run = verify_exit_code("c4", None, is_not_run=True, reason="Interactive mode")
    assert v_not_run.status == "NOT_RUN"
    assert v_not_run.exit_code is None
    assert not v_not_run.gui_claimed

    v_blocked = verify_exit_code("unknown", None, is_blocked=True, reason="Disallowed")
    assert v_blocked.status == "BLOCKED"
    assert not v_blocked.gui_claimed


def test_summarize_verdicts():
    v1 = verify_exit_code("c1", 0)
    v2 = verify_exit_code("c2", None, is_not_run=True)
    summary = summarize_verdicts([v1, v2])
    assert summary["overall_status"] == "PASS"
    assert summary["counts"]["PASS"] == 1
    assert summary["counts"]["NOT_RUN"] == 1
    assert summary["gui_ime_claimed"] is False

    v3 = verify_exit_code("c3", 2)
    summary_fail = summarize_verdicts([v1, v2, v3])
    assert summary_fail["overall_status"] == "FAIL"
    assert summary_fail["counts"]["FAIL"] == 1


def test_preflight_probe(tmp_path: Path):
    preflight = probe_environment(tmp_path)
    assert "platform" in preflight
    assert "disk_bytes" in preflight
    assert "tools_present" in preflight
    assert preflight["runner_capabilities"]["supports_windows_gui"] is False
    assert preflight["runner_capabilities"]["supports_windows_ime"] is False


def test_run_job_execution(tmp_path: Path):
    job_spec = {
        "candidate_id": "test-c1",
        "run_id": "test-run-1",
        "sha": "HEAD",
        "allowed_commands": ["c1", "c2", "c3", "gui"],
        "evidence_dir": str(tmp_path / "evidence"),
        "cards": ["c1", "c2", "gui"],
        "requested_model": "gemini-3.8-flash",
    }
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job_spec), encoding="utf-8")

    summary = run_job(job_file, Path.cwd())
    assert summary["candidate_id"] == "test-c1"
    assert summary["requested_model"] == "gemini-3.8-flash"
    assert summary["gui_ime_claimed"] is False
    
    # Evidence files created
    ev_dir = tmp_path / "evidence"
    assert (ev_dir / "preflight.json").exists()
    assert (ev_dir / "verdict.json").exists()

    # GUI card should be NOT_RUN
    gui_v = next(v for v in summary["verdicts"] if v["card_id"] == "gui")
    assert gui_v["status"] == "NOT_RUN"
    assert not gui_v["gui_claimed"]


def test_verifier_mock_approved():
    v1 = verify_exit_code("c4", None, is_not_run=True, reason="Unattended", approval_mode="mock_approved", mock_approved=True)
    assert v1.status == "NOT_RUN"
    assert v1.approval_mode == "mock_approved"
    assert v1.mock_approved is True
    assert v1.gui_claimed is False

    summary = summarize_verdicts([v1], approval_mode="mock_approved")
    assert summary["overall_status"] == "NOT_RUN"
    assert summary["approval_mode"] == "mock_approved"
    assert summary["mock_approved_count"] == 1
    assert summary["gui_ime_claimed"] is False


def test_run_job_with_mock_approved_c4(tmp_path: Path):
    job_spec = {
        "candidate_id": "test-c4-mock",
        "run_id": "test-c4-mock-run-1",
        "sha": "HEAD",
        "allowed_commands": ["c4"],
        "evidence_dir": str(tmp_path / "evidence_c4"),
        "cards": ["c4"],
        "requested_model": "gemini-3.8-flash",
        "approval_mode": "mock_approved",
    }
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job_spec), encoding="utf-8")

    summary = run_job(job_file, Path.cwd())
    assert summary["candidate_id"] == "test-c4-mock"
    assert summary["approval_mode"] == "mock_approved"
    assert summary["mock_approved"] is True
    assert summary["gui_ime_claimed"] is False

    ev_dir = tmp_path / "evidence_c4"
    assert (ev_dir / "c4-fixture-probe.json").exists()
    assert (ev_dir / "c4-manifest.json").exists()
    assert (ev_dir / "c4-manifest-check.json").exists()
    assert (ev_dir / "c4-mock-approval.json").exists()

    manifest_data = json.loads((ev_dir / "c4-manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["approval_mode"] == "mock_approved"
    assert manifest_data["is_mock_approved"] is True

    mock_appr = json.loads((ev_dir / "c4-mock-approval.json").read_text(encoding="utf-8"))
    assert mock_appr["is_mock_approved"] is True
    assert mock_appr["is_human_approved"] is False
    assert mock_appr["gui_claimed"] is False
    assert mock_appr["approver"] == "mock_approved"

    c4_v = next(v for v in summary["verdicts"] if v["card_id"] == "c4")
    assert c4_v["status"] == "NOT_RUN"
    assert c4_v["mock_approved"] is True
    assert c4_v["approval_mode"] == "mock_approved"
    assert c4_v["gui_claimed"] is False
    assert "mock_approved for unattended plan apply gating" in c4_v["reason"]
    assert "Verdict remains NOT_RUN" in c4_v["reason"]

