# -*- coding: utf-8 -*-
"""The residue gate can be asked what must be PRESENT, offline (T130).

The gate could only say what must be absent. There was no shipped offline way to
say what must be present, so a clean-room run confirming that its values landed
and that three statutory notices survived hand-rolled a zip/XML scan — not a
shipped tool, therefore unrepeatable by anyone else and absent from every
receipt. `visual_verify --expectations` can assert presence but needs a render,
which on Windows means starting Hancom.

On its first real use the flag disagreed with the run that motivated it. The
agent reported 「동의를 거부할 권리가 있습니다」 present verbatim, twice. It is not:
this corpus splits words across runs and `artifact_text` joins XML entries with
a space, so the notice extracts as 「…권리가 있 습니다. 그러 나…」. The sentence is
in the document and is not one literal.

Collapsing that distinction — matching against a whitespace-stripped haystack —
would have made the flag a wildcard, which is T115's lesson about whitespace
keys. So the finding names which of the two it is instead.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCRIPTS = ROOT / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_residue  # noqa: E402

CORPUS = ROOT / "tests" / "corpus" / "forms"
PPS = CORPUS / "grant" / "pps-hyeopeop-seungin-sinchengseo.hwpx"

MINIMAL_PROFILE = {
    "form_hash": "0" * 64,
    "anchors": [],
    "anchor_records": [],
    "guide_text": [],
    "removal_targets": [],
    "placeholders": [],
}


def _profile(tmp_path, **overrides):
    payload = dict(MINIMAL_PROFILE)
    payload.update(overrides)
    path = tmp_path / "form_profile.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _dump(tmp_path, text, name="artifact.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _missing(verdict):
    return {row["text"]: row["reason"]
            for row in (verdict.get("expected_text") or {}).get("missing", [])}


# ---------------------------------------------------------------------------
# the three outcomes
# ---------------------------------------------------------------------------

def test_a_present_string_is_not_reported(tmp_path):
    verdict, code = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신 국가유산청장 제목 자료 제출"),
        expect_text=("국가유산청장",))
    assert code == 0, verdict
    assert _missing(verdict) == {}
    assert verdict["counts"]["expected_text_missing"] == 0


def test_an_absent_string_is_a_hard_finding(tmp_path):
    verdict, code = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신 국가유산청장"),
        expect_text=("이 문구는 이 문서에 없다",))
    assert code == 3, verdict
    assert _missing(verdict) == {"이 문구는 이 문서에 없다": "absent"}
    codes = [row["code"] for row in verdict["hard"]]
    assert "expected_text_missing" in codes


def test_a_run_split_string_says_so_rather_than_absent(tmp_path):
    """The case that motivated the distinction: in the document, not one literal."""
    verdict, code = check_residue.check(
        _profile(tmp_path),
        _dump(tmp_path, "권리가 있 습니다. 그러 나 동의를 거부할 경우"),
        expect_text=("권리가 있습니다",))
    assert code == 3, verdict
    assert _missing(verdict) == {"권리가 있습니다": "split_across_runs"}
    row = next(r for r in verdict["hard"]
               if r["code"] == "expected_text_missing")
    assert row["reason"] == "split_across_runs"
    assert "split across runs" in row["msg"]


def test_whitespace_differences_alone_are_not_a_miss(tmp_path):
    """Both sides are normalized the same way, so a caller's double space in an
    otherwise contiguous string must not manufacture a finding.

    Both directions are asserted on purpose. A mutation that stopped
    normalizing the DECLARED string passed when only the artifact side varied —
    the haystack arrives already normalized, so that half is free.
    """
    # extra whitespace on the artifact side
    verdict, code = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신   국가유산청장"),
        expect_text=("수신 국가유산청장",))
    assert code == 0, verdict
    assert _missing(verdict) == {}
    # extra whitespace on the DECLARED side — this is the half a mutation got
    # away with, because `haystack` is normalized before it ever arrives
    verdict, code = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신 국가유산청장"),
        expect_text=("수신   국가유산청장",))
    assert code == 0, verdict
    assert _missing(verdict) == {}


# ---------------------------------------------------------------------------
# scope: a text gate is never render evidence
# ---------------------------------------------------------------------------

def test_the_verdict_labels_its_own_evidence_level(tmp_path):
    verdict, _ = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신 국가유산청장"),
        expect_text=("국가유산청장",))
    assert verdict["expected_text"]["evidence_level"] == "text", (
        "presence in the text says nothing about whether the string renders "
        "visibly; the verdict has to say which claim it is making")
    assert verdict["expected_text"]["declared"] == ["국가유산청장"]


def test_the_block_is_absent_when_nothing_was_declared(tmp_path):
    verdict, _ = check_residue.check(
        _profile(tmp_path), _dump(tmp_path, "수신 국가유산청장"))
    assert "expected_text" not in verdict, (
        "a caller who declared nothing must not get an empty claim published "
        "as though a check had run")


# ---------------------------------------------------------------------------
# the real artifact, and the CLI
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PPS.is_file(), reason="corpus absent")
def test_on_a_real_form_the_three_outcomes_separate(tmp_path):
    text = check_residue.artifact_text(PPS)
    assert text, "the corpus form extracted no text"
    present = "협업"
    assert present in text, "fixture assumption broke; pick another fragment"
    verdict, code = check_residue.check(
        _profile(tmp_path), PPS,
        expect_text=(present, "이 문구는 이 문서에 절대로 없다"))
    assert code == 3, verdict
    reasons = _missing(verdict)
    assert reasons == {"이 문구는 이 문서에 절대로 없다": "absent"}, reasons


@pytest.mark.skipif(not PPS.is_file(), reason="corpus absent")
def test_the_flag_reaches_the_check_through_the_cli(tmp_path):
    out = tmp_path / "verdict.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_residue.py"),
         "--form-profile", str(_profile(tmp_path)),
         "--artifact", str(PPS),
         "--expect-text", "이 문구는 이 문서에 절대로 없다",
         "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == 3, (proc.stdout[-1500:], proc.stderr[-1500:])
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert _missing(verdict) == {"이 문구는 이 문서에 절대로 없다": "absent"}
