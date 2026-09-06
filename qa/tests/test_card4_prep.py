import json
import shutil
import zipfile
from pathlib import Path

from qa.card4_prep import (
    DEFAULT_FIXTURE,
    STEPS,
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
