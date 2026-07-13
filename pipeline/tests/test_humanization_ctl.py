"""Tests for humanization_ctl.py v3 additions (W5, v0.8-portability).

Covers pack-driven voice injection, the deterministic check_style pre-pass with
per-paragraph hint mapping, backend-configurable worker resolution, and the
round-over-round no-progress detector. The v2 code paths (no profile root) are
exercised by test_prose_fidelity.py; a focused regression guard lives here too.

Runs the controller as a subprocess so exit codes match what a pipeline step
sees. Synthetic packs only (no personal strings).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
HUMANIZE = ROOT / "pipeline" / "scripts" / "humanization_ctl.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(HUMANIZE), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def make_ws(tmp_path: Path, content: str) -> Path:
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "content.md").write_text(content, encoding="utf-8")
    return ws


def make_profile_root(tmp_path: Path, banned: list[dict]) -> Path:
    root = tmp_path / "profile"
    (root / "packs").mkdir(parents=True)
    (root / "packs" / "prose_rules.json").write_text(
        json.dumps({"pack_type": "prose_rules", "banned_patterns": banned,
                    "advisory_notes": ["prefer connective prose"]}, ensure_ascii=False),
        encoding="utf-8")
    return root


CONTENT_3PARA = (
    "## 탐구 서론\n\n"
    "첫 문단은 평범한 서술 문장이다.\n\n"
    "두 번째 문단에는 금칙어구문이 분명히 들어 있다.\n\n"
    "세 번째 문단도 평범한 마무리이다.\n"
)
PLANTED = [{"id": "planted-run", "regex": "금칙어구문", "severity": "warn",
            "description": "planted test pattern"}]


def test_prepare_with_profile_root_injects_voice_pointer_and_hints(tmp_path: Path):
    ws = make_ws(tmp_path, CONTENT_3PARA)
    root = make_profile_root(tmp_path, PLANTED)
    proc = run("prepare", str(ws), "--profile-root", str(root))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    # v2 schema preserved (additive keys only)
    assert payload["schema"] == "report-pipeline/humanization-v2"

    # voice directives are a POINTER, not inline taste text
    voice = payload["voice"]
    assert voice["source"] == "profile"
    assert "directives_sha256" in voice
    sidecar = Path(voice["directives_path"])
    assert sidecar.is_file()
    # the sidecar lives under the profile root, never in the workspace bundle
    assert str(ws.resolve()) not in str(sidecar.resolve())

    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert [b["id"] for b in sidecar_doc["voice_directives"]["banned_patterns"]] == ["planted-run"]
    assert sidecar_doc["voice_directives"]["advisory_notes"] == ["prefer connective prose"]

    # payload hints carry only content-derived fields (no pack description text)
    planted = [h for h in payload["hints"] if h["rule_id"] == "planted-run"]
    assert planted and "description" not in planted[0]
    # sidecar hints DO carry the description for the rewriter
    assert any(h.get("description") for h in sidecar_doc["hints"])


def test_prepass_maps_finding_to_the_paragraph_that_contains_it(tmp_path: Path):
    ws = make_ws(tmp_path, CONTENT_3PARA)
    root = make_profile_root(tmp_path, PLANTED)
    proc = run("prepare", str(ws), "--profile-root", str(root))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    planted = [h for h in payload["hints"] if h["rule_id"] == "planted-run"]
    assert len(planted) == 1
    # the planted phrase sits only in the second body paragraph -> p0003
    assert planted[0]["paragraph_id"] == "p0003"
    assert planted[0]["matched"] == "금칙어구문"


def test_backends_pack_resolves_worker_roles(tmp_path: Path):
    ws = make_ws(tmp_path, CONTENT_3PARA)
    backends = tmp_path / "backends.json"
    backends.write_text(json.dumps({
        "pack_type": "backends", "name": "t", "version": 1,
        "seats": [
            {"role": "rewriter", "cli": "rw-cli", "args_argv": ["rewrite"], "model": "m1"},
            {"role": "reviewer-fidelity", "cli": "fid-cli", "args_argv": ["fid"]},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    proc = run("prepare", str(ws), "--backends", str(backends))
    assert proc.returncode == 0, proc.stderr
    workers = json.loads(proc.stdout)["workers"]
    assert workers["mode"] == "backends"
    assert workers["roles"]["humanizer-rewriter"] == {
        "cli": "rw-cli", "args_argv": ["rewrite"], "model": "m1", "timeout_s": None}
    assert "reviewer-fidelity" in workers["roles"]
    assert set(workers["unresolved_roles"]) == {"reviewer-ai-tell", "reviewer-naturalness"}


def test_v2_prepare_without_profile_root_is_unchanged(tmp_path: Path):
    ws = make_ws(tmp_path, "## 결과\n\n측정값은 18.6%였다.\n")
    proc = run("prepare", str(ws))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    # no v3 sections leak into the plain v2 payload
    assert "voice" not in payload
    assert "hints" not in payload
    assert "workers" not in payload
    assert payload["schema"] == "report-pipeline/humanization-v2"
    # and no rounds-history file is created on a pure v2 run
    assert not (ws / "bundle" / "humanization_rounds.json").exists()


def _rework_changes(round_number: int) -> dict:
    # a change the independent reviewer rejects (rewrite) -> stays in retry set,
    # content unchanged so `before` remains valid across rounds
    return {
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "REWORK", "skipped": False},
        "round": round_number,
        "changes": [{
            "paragraph_id": "p0002",
            "before": "측정값은 18.6%였다.",
            "after": "측정값은 18.6% 수준이었다.",
            "reviewer_verdict": "rewrite",
        }],
    }


def test_no_progress_detector_holds_and_reports(tmp_path: Path):
    ws = make_ws(tmp_path, "## 결과\n\n측정값은 18.6%였다.\n")
    run("prepare", str(ws))
    bundle = ws / "bundle"
    # identical non-empty pre-pass violation set for both rounds
    hints = bundle / "hints.json"
    hints.write_text(json.dumps([{"paragraph_id": "p0002", "rule_id": "planted-run",
                                  "matched": "x"}]), encoding="utf-8")

    r1 = bundle / "r1.json"
    r1.write_text(json.dumps(_rework_changes(1), ensure_ascii=False), encoding="utf-8")
    out1 = run("apply", str(ws), "--changes", str(r1), "--hints", str(hints))
    assert out1.returncode == 1, out1.stderr
    report1 = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    # round 1 cannot detect no-progress yet (no prior round)
    assert report1["status"] == "needs_retry"
    assert report1["no_progress"] is False

    r2 = bundle / "r2.json"
    r2.write_text(json.dumps(_rework_changes(2), ensure_ascii=False), encoding="utf-8")
    out2 = run("apply", str(ws), "--changes", str(r2), "--hints", str(hints))
    assert out2.returncode == 1, out2.stderr
    report2 = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report2["status"] == "hold_and_report"
    assert report2["no_progress"] is True
    assert report2["hold_reason"] == "no_progress"
    # protected original preserved
    assert "측정값은 18.6%였다." in (bundle / "content.md").read_text(encoding="utf-8")


def test_no_progress_not_triggered_when_violations_change(tmp_path: Path):
    ws = make_ws(tmp_path, "## 결과\n\n측정값은 18.6%였다.\n")
    run("prepare", str(ws))
    bundle = ws / "bundle"

    h1 = bundle / "h1.json"
    h1.write_text(json.dumps([{"paragraph_id": "p0002", "rule_id": "rule-a", "matched": "x"}]),
                  encoding="utf-8")
    h2 = bundle / "h2.json"
    h2.write_text(json.dumps([{"paragraph_id": "p0002", "rule_id": "rule-b", "matched": "y"}]),
                  encoding="utf-8")

    r1 = bundle / "r1.json"
    r1.write_text(json.dumps(_rework_changes(1), ensure_ascii=False), encoding="utf-8")
    run("apply", str(ws), "--changes", str(r1), "--hints", str(h1))

    r2 = bundle / "r2.json"
    r2.write_text(json.dumps(_rework_changes(2), ensure_ascii=False), encoding="utf-8")
    out2 = run("apply", str(ws), "--changes", str(r2), "--hints", str(h2))
    report2 = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    # different violation set between rounds -> normal retry path, not held
    assert report2["no_progress"] is False
    assert report2["status"] == "needs_retry"
