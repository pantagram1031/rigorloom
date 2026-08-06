# -*- coding: utf-8 -*-
"""Tests for the form-scan auto-derived residue gate.

All placeholder names/ids (김선덕, 20101, ...) are the FORM's own fake
placeholders — never real student data.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_residue.py"
_spec = importlib.util.spec_from_file_location("check_residue", SCRIPT)
check_residue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_residue)


FORM_PROFILE = {
    "ok": True,
    "form_hash": "f" * 64,
    "anchors": [
        "논문제목",
        "20101",
        "김선덕",
        "(초록: 논문의 주요 내용의 요약)",
        "I.  서론",
        "II.  이론적 배경",
        "1.  연구설계",
        "(자료를 수집한 대상에 대해 상세히 기술합니다.)",
        "V.  요약 및 논의",
    ],
    "guide_text": [
        {
            "text": "(연구의 필요성 및 목적, 연구를 수행하게 된 동기, "
                    "연구문제 및 가설을 기술합니다.)",
            "reason": "colored",
        },
        {"text": "(자료분석의 방법을 구체적으로 기술합니다.)"},
    ],
    "placeholders": [],
}


class CheckResidueTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.profile_path = self.base / "form_profile.json"
        self.profile_path.write_text(
            json.dumps(FORM_PROFILE, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def write_hwpx(self, name: str, section_text: str) -> Path:
        target = self.base / name
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<doc xmlns:hp="urn:hancom"><p>{section_text}</p></doc>',
            )
        return target

    def run_check(self, artifact, **kwargs):
        return check_residue.check(self.profile_path, artifact, **kwargs)

    # ── still-catches fixture ────────────────────────────────────────
    def test_still_catches_dirty_hwpx_is_hard(self):
        artifact = self.write_hwpx(
            "dirty.hwpx",
            "I.  서론 본문이 채워져 있다. "
            "(초록: 논문의 주요 내용의 요약) "
            "20101 김선덕",
        )
        verdict, code = self.run_check(artifact)
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        residue_at = {item["at"] for item in verdict["hard"]
                      if item["code"] == "form_residue"}
        self.assertIn("(초록: 논문의 주요 내용의 요약)", residue_at)
        self.assertIn("20101", residue_at)
        self.assertIn("김선덕", residue_at)
        # the section heading legitimately remains — never residue
        self.assertNotIn("I.  서론", residue_at)

    def test_cleaned_hwpx_passes(self):
        artifact = self.write_hwpx(
            "clean.hwpx",
            "I.  서론 이 탐구는 실제 초록과 본문으로 채워져 있다. "
            "1.  연구설계 II.  이론적 배경 V.  요약 및 논의",
        )
        verdict, code = self.run_check(artifact)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["hard"], [])
        self.assertEqual(verdict["counts"]["residue"], 0)

    # ── loud failure on missing pinned target (shared-miss #4) ──────
    def test_missing_artifact_is_hard_never_silent_pass(self):
        verdict, code = self.run_check(self.base / "gone.hwpx")
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any(
            item["code"] == "pinned_target_missing"
            for item in verdict["hard"]
        ), verdict)

    def test_missing_form_profile_is_usage_error(self):
        artifact = self.write_hwpx("clean.hwpx", "본문")
        verdict, code = check_residue.check(
            self.base / "no_profile.json", artifact
        )
        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["verdict"], "usage_error")

    def test_invalid_profile_json_is_usage_error(self):
        bad = self.base / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        artifact = self.write_hwpx("clean.hwpx", "본문")
        verdict, code = check_residue.check(bad, artifact)
        self.assertEqual(code, 2, verdict)

    # ── keep-list behavior ───────────────────────────────────────────
    def test_default_keep_pattern_keeps_numbered_headings_only(self):
        forbidden, kept = check_residue.derive_forbidden(FORM_PROFILE)
        kept_set = set(kept)
        self.assertIn("I.  서론", kept_set)
        self.assertIn("II.  이론적 배경", kept_set)
        self.assertIn("1.  연구설계", kept_set)
        self.assertIn("V.  요약 및 논의", kept_set)
        forbidden_texts = {row["text"] for row in forbidden}
        self.assertIn("논문제목", forbidden_texts)
        self.assertIn("20101", forbidden_texts)  # id has no dot: not a heading
        self.assertIn("김선덕", forbidden_texts)
        self.assertIn("(초록: 논문의 주요 내용의 요약)", forbidden_texts)

    def test_explicit_keep_string_suppresses_a_finding(self):
        artifact = self.write_hwpx("titled.hwpx", "논문제목 실제 본문")
        verdict, code = self.run_check(artifact)
        self.assertEqual(code, 3, verdict)
        verdict, code = self.run_check(artifact, keep=("논문제목",))
        self.assertEqual(code, 0, verdict)

    # ── text-dump artifacts and normalization ───────────────────────
    def test_text_dump_artifact_is_supported(self):
        dump = self.base / "final.txt"
        dump.write_text(
            "본문 시작 (자료분석의 방법을 구체적으로 기술합니다.) 끝",
            encoding="utf-8",
        )
        verdict, code = self.run_check(dump)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["at"] == "(자료분석의 방법을 구체적으로 기술합니다.)"
            and item["code"] == "form_residue"
            for item in verdict["hard"]
        ), verdict)

    def test_whitespace_reflow_still_matches(self):
        # The form anchor has a double space; the artifact reflowed it to one.
        dump = self.base / "reflow.txt"
        dump.write_text("(초록:  논문의   주요 내용의 요약)", encoding="utf-8")
        verdict, code = self.run_check(dump)
        self.assertEqual(code, 3, verdict)

    def test_guide_text_split_across_xml_runs_is_caught(self):
        target = self.base / "runs.hwpx"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<doc><p><t>(자료를 수집한 대상에 대해 </t>'
                "<t>상세히 기술합니다.)</t></p></doc>",
            )
        verdict, code = self.run_check(target)
        self.assertEqual(code, 3, verdict)

    def test_verdict_carries_form_hash_and_counts(self):
        artifact = self.write_hwpx("clean.hwpx", "본문만 있다")
        verdict, code = self.run_check(artifact)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["form_hash"], "f" * 64)
        self.assertEqual(verdict["checker"], "check_residue")
        self.assertGreater(verdict["counts"]["forbidden"], 0)
        self.assertGreater(verdict["counts"]["kept"], 0)


if __name__ == "__main__":
    unittest.main()
