import json
import shutil
import zipfile
from pathlib import Path

from qa.card4_prep import (
    DEFAULT_FIXTURE,
    STEPS,
    create_mock_approval_artifact,
    probe_fixture,
    scaffold_manifest,
    sha256_of,
    validate_manifest,
)
from qa.run_cards import run_job

REPO = Path(__file__).resolve().parents[2]


def _hwpx(path: Path, section_xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", section_xml)
    return path


def test_default_fixture_is_eligible():
    r = probe_fixture(REPO / DEFAULT_FIXTURE)
    assert r["eligible"], r
    assert r["stats"]["tables"] >= 1
    assert r["stats"]["mixed_paragraphs"] >= 1
    assert r["stats"]["longest_paragraph_chars"] >= 200
    assert len(r["sha256"]) == 64


def test_probe_rejects_plain_document(tmp_path: Path):
    xml = '<hp:sec><hp:p><hp:run charPrIDRef="0"><hp:t>짧은 문단</hp:t></hp:run></hp:p></hp:sec>'
    r = probe_fixture(_hwpx(tmp_path / "plain.hwpx", xml))
    assert not r["eligible"]
    assert set(r["failed_requirements"]) == {"tables", "mixed_paragraphs", "long_paragraph", "hangul_chars"}


def test_probe_missing_and_bad_zip(tmp_path: Path):
    assert probe_fixture(tmp_path / "nope.hwpx")["eligible"] is False
    bad = tmp_path / "bad.hwpx"
    bad.write_bytes(b"not a zip")
    assert probe_fixture(bad)["eligible"] is False


def test_scaffold_then_validate_is_incomplete_and_never_pass(tmp_path: Path):
    ev = tmp_path / "ev"
    fixture = REPO / DEFAULT_FIXTURE
    manifest = scaffold_manifest(ev, fixture, "deadbeef", REPO)
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["status"] == "NOT_RUN"
    assert m["gui_ime_claimed"] is False
    assert m["fixture"]["path"] == DEFAULT_FIXTURE  # repo-relative
    assert [s["id"] for s in m["steps"]] == [s["id"] for s in STEPS]

    r = validate_manifest(manifest, REPO)
    assert r["result"] == "EVIDENCE_INCOMPLETE"
    assert "PASS" not in r["result"]
    assert any("s9_reopen" in p for p in r["problems"])

    # scaffold must not clobber an existing manifest
    m["operator"]["name"] = "someone"
    manifest.write_text(json.dumps(m), encoding="utf-8")
    scaffold_manifest(ev, fixture, "deadbeef", REPO)
    assert json.loads(manifest.read_text(encoding="utf-8"))["operator"]["name"] == "someone"


def test_validate_filled_manifest_checks_hashes(tmp_path: Path):
    ev = tmp_path / "ev"
    fixture = REPO / DEFAULT_FIXTURE
    manifest = scaffold_manifest(ev, fixture, "deadbeef", REPO)
    m = json.loads(manifest.read_text(encoding="utf-8"))

    exe = tmp_path / "rigorloom-desktop.exe"
    exe.write_bytes(b"MZ fake")
    saved = tmp_path / "saved.hwpx"
    shutil.copy(fixture, saved)

    m["install"]["exe_path"] = str(exe)
    m["files"]["saved"] = str(saved)
    m["hashes"] = {
        "exe": sha256_of(exe),
        "fixture": sha256_of(fixture),
        "saved": sha256_of(saved),
        "saved_reopened": sha256_of(saved),
    }
    for s in m["steps"]:
        s["status"] = "DONE"
        for art in s["artifacts"]:
            (ev / art).write_bytes(b"x")
    manifest.write_text(json.dumps(m), encoding="utf-8")

    r = validate_manifest(manifest, REPO)
    assert r["result"] == "EVIDENCE_COMPLETE", r["problems"]
    assert r["gui_ime_claimed"] is False
    assert "not PASS" in r["note"]

    # a moved reopen hash breaks it
    m["hashes"]["saved_reopened"] = "0" * 64
    manifest.write_text(json.dumps(m), encoding="utf-8")
    r = validate_manifest(manifest, REPO)
    assert r["result"] == "EVIDENCE_INCOMPLETE"
    assert any("reopen hash" in p for p in r["problems"])


def test_run_cards_c4_is_not_run_with_prep_artifacts(tmp_path: Path):
    job = {
        "candidate_id": "c4",
        "run_id": "t",
        "sha": "deadbeef",
        "allowed_commands": ["c4"],
        "evidence_dir": str(tmp_path / "ev"),
        "cards": ["c4"],
    }
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    summary = run_job(job_file, REPO)
    v = summary["verdicts"][0]
    assert v["card_id"] == "c4"
    assert v["status"] == "NOT_RUN"
    assert v["gui_claimed"] is False
    assert summary["overall_status"] == "NOT_RUN"
    ev = tmp_path / "ev"
    assert (ev / "c4-fixture-probe.json").exists()
    assert (ev / "c4-manifest.json").exists()
    assert (ev / "c4-manifest-check.json").exists()
    assert json.loads((ev / "c4-fixture-probe.json").read_text(encoding="utf-8"))["eligible"] is True


def test_scaffold_with_mock_approved(tmp_path: Path):
    ev = tmp_path / "ev"
    fixture = REPO / DEFAULT_FIXTURE
    manifest = scaffold_manifest(ev, fixture, "deadbeef", REPO, approval_mode="mock_approved")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["approval_mode"] == "mock_approved"
    assert m["is_mock_approved"] is True
    s7 = next(s for s in m["steps"] if s["id"] == "s7_ai_review")
    assert "c4-mock-approval.json" in s7["artifacts"]
    assert "shot-07-ai-decision.png" not in s7["artifacts"]
    assert "mock_approved mode" in s7["note"]


def test_validate_with_mock_approved_complete_and_reject_forged_human(tmp_path: Path):
    ev = tmp_path / "ev"
    fixture = REPO / DEFAULT_FIXTURE
    manifest = scaffold_manifest(ev, fixture, "deadbeef", REPO, approval_mode="mock_approved")
    m = json.loads(manifest.read_text(encoding="utf-8"))

    exe = tmp_path / "rigorloom-desktop.exe"
    exe.write_bytes(b"MZ fake")
    saved = tmp_path / "saved.hwpx"
    shutil.copy(fixture, saved)

    m["install"]["exe_path"] = str(exe)
    m["files"]["saved"] = str(saved)
    m["hashes"] = {
        "exe": sha256_of(exe),
        "fixture": sha256_of(fixture),
        "saved": sha256_of(saved),
        "saved_reopened": sha256_of(saved),
    }

    # Generate mock approval artifact
    create_mock_approval_artifact(ev, plan_id="plan-c4-001", plan_hash="hash-c4-001")

    for s in m["steps"]:
        s["status"] = "DONE"
        for art in s["artifacts"]:
            if not (ev / art).exists():
                (ev / art).write_bytes(b"dummy-artifact-data")
    manifest.write_text(json.dumps(m), encoding="utf-8")

    r = validate_manifest(manifest, REPO)
    assert r["result"] == "EVIDENCE_COMPLETE", r["problems"]
    assert r["approval_mode"] == "mock_approved"
    assert r["is_mock_approved"] is True
    assert r["gui_ime_claimed"] is False
    assert "mock_approved mode active" in r["note"]

    # Forging human approval on mock artifact must be rejected by validator
    bad_mock = json.loads((ev / "c4-mock-approval.json").read_text(encoding="utf-8"))
    bad_mock["is_human_approved"] = True
    (ev / "c4-mock-approval.json").write_text(json.dumps(bad_mock), encoding="utf-8")
    r_bad = validate_manifest(manifest, REPO)
    assert r_bad["result"] == "EVIDENCE_INCOMPLETE"
    assert any("cannot claim is_human_approved" in p for p in r_bad["problems"])


def test_human_approved_mode_demands_human_artifact(tmp_path: Path):
    ev = tmp_path / "ev"
    fixture = REPO / DEFAULT_FIXTURE
    manifest = scaffold_manifest(ev, fixture, "deadbeef", REPO, approval_mode="human_approved")
    m = json.loads(manifest.read_text(encoding="utf-8"))

    exe = tmp_path / "rigorloom-desktop.exe"
    exe.write_bytes(b"MZ fake")
    saved = tmp_path / "saved.hwpx"
    shutil.copy(fixture, saved)

    m["install"]["exe_path"] = str(exe)
    m["files"]["saved"] = str(saved)
    m["hashes"] = {
        "exe": sha256_of(exe),
        "fixture": sha256_of(fixture),
        "saved": sha256_of(saved),
        "saved_reopened": sha256_of(saved),
    }

    for s in m["steps"]:
        s["status"] = "DONE"
        for art in s["artifacts"]:
            if art != "shot-07-ai-decision.png":
                (ev / art).write_bytes(b"dummy")
    manifest.write_text(json.dumps(m), encoding="utf-8")

    r = validate_manifest(manifest, REPO)
    assert r["result"] == "EVIDENCE_INCOMPLETE"
    assert any("real human operator approval required; mock_approved mode is off" in p for p in r["problems"])

