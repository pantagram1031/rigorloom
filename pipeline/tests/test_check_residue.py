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

    # ── validity precedes text scanning (live-fire blind spot) ───────
    def test_malformed_section_xml_is_hard_not_pass(self):
        # The exact live-fire pattern: a self-closed <hp:t/> followed by a
        # stray closing </hp:t> — Hancom renders the document blank, and the
        # old tag-strip fallback scanned it as clean text and PASSED.
        target = self.base / "malformed.hwpx"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<doc xmlns:hp="urn:hancom"><p><hp:t/>본문 텍스트</hp:t></p></doc>',
            )
        verdict, code = self.run_check(target)
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        malformed = [item for item in verdict["hard"]
                     if item["code"] == "artifact_malformed"]
        self.assertEqual(len(malformed), 1, verdict)
        self.assertEqual(malformed[0]["at"], "Contents/section0.xml")
        # msg carries the member and the parser's position
        self.assertIn("Contents/section0.xml", malformed[0]["msg"])
        self.assertRegex(malformed[0]["msg"], r"line \d+, column \d+")
        # no residue scan happened on the broken bytes
        self.assertEqual(verdict["counts"]["residue"], 0)
        self.assertEqual(verdict["malformed_members"][0]["member"],
                         "Contents/section0.xml")

    def test_malformed_header_xml_is_hard(self):
        target = self.base / "badheader.hwpx"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("Contents/header.xml", "<head><open></head>")
            archive.writestr(
                "Contents/section0.xml", "<doc><p>깨끗한 본문</p></doc>"
            )
        verdict, code = self.run_check(target)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "artifact_malformed"
            and item["at"] == "Contents/header.xml"
            for item in verdict["hard"]
        ), verdict)

    def test_wellformed_hwpx_is_unaffected_by_validation(self):
        artifact = self.write_hwpx("fine.hwpx", "I.  서론 잘 조립된 본문")
        verdict, code = self.run_check(artifact)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["hard"], [])
        self.assertNotIn("malformed_members", verdict)

    def test_text_dump_is_exempt_from_xml_validation(self):
        # A text dump may legitimately contain XML-ish fragments; only hwpx
        # zips get well-formedness validation.
        dump = self.base / "dump.txt"
        dump.write_text(
            "<hp:t/>본문 조각</hp:t> 잘린 태그가 있어도 텍스트 덤프는 통과",
            encoding="utf-8",
        )
        verdict, code = self.run_check(dump)
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "artifact_malformed" for item in verdict["hard"]
        ), verdict)

    # ── prefix-preserving fills: per-occurrence attribution (T31) ────
    def write_profile(self, **fields) -> Path:
        target = self.base / "labeled_profile.json"
        target.write_text(json.dumps(fields, ensure_ascii=False),
                          encoding="utf-8")
        return target

    def test_prefix_preserving_fill_is_attributed_not_residue(self):
        """Filling a labeled field keeps the label as a prefix, so the key
        text survives inside the value. That occurrence belongs to the
        value's span."""
        profile = self.write_profile(placeholders=[" http://"])
        artifact = self.write_hwpx(
            "url.hwpx", "누리집 http://hanbit.example.kr 본문")
        verdict, code = check_residue.check(profile, artifact)
        self.assertEqual(code, 3, verdict)          # without the map: residue
        verdict, code = check_residue.check(
            profile, artifact,
            fill_map={" http://": " http://hanbit.example.kr"})
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["residue"], 0)
        self.assertEqual(verdict["fill_attribution"]["attributed"], 1)
        self.assertEqual(verdict["fill_attribution"]["unattributed"], 0)

    def test_second_unfilled_occurrence_of_the_same_key_still_flags(self):
        """Attribution is per occurrence, never a global suppression."""
        profile = self.write_profile(placeholders=[" http://"])
        artifact = self.write_hwpx(
            "two.hwpx",
            "누리집 http://hanbit.example.kr 본문 문단이 아주 길게 이어지면서 "
            "표를 지나 다음 항목까지 계속 흘러가는 서술이 이어진다 그리고 "
            "보조 누리집 http://")
        verdict, code = check_residue.check(
            profile, artifact,
            fill_map={" http://": " http://hanbit.example.kr"})
        self.assertEqual(code, 3, verdict)
        row = verdict["residue"][0]
        self.assertEqual(row["occurrences"], 2)
        self.assertEqual(row["attributed"], 1)
        self.assertEqual(len(row["at_offsets"]), 1)
        self.assertIn("보조 누리집", row["context"][0])
        self.assertNotIn("hanbit", row["context"][0])

    def test_guide_text_inside_a_declared_value_is_never_attributed(self):
        """Instruction prose is not something a correct fill KEEPS, the same
        reason guide text is never keepable."""
        profile = self.write_profile(
            guide_text=["여기에 입력하세요"], placeholders=[])
        artifact = self.write_hwpx(
            "guide.hwpx", "비고 여기에 입력하세요 라고 적혀 있다")
        verdict, code = check_residue.check(
            profile, artifact,
            fill_map={"비고": "비고 여기에 입력하세요 라고 적혀 있다"})
        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["residue"][0]["attributed"], 0)

    def test_value_spans_are_whitespace_normalized_on_both_sides(self):
        haystack = check_residue.normalize_text("가  우(  -  )   나")
        spans = check_residue.value_spans(
            haystack, {" 우(     -     )": " 우(     -     )"})
        self.assertEqual(len(spans), 1)
        start, end = spans[0]["start"], spans[0]["end"]
        self.assertEqual(haystack[start:end], "우( - )")

    def test_fill_map_file_accepts_both_shapes(self):
        flat = self.base / "flat.json"
        flat.write_text(json.dumps({"a": "b"}), encoding="utf-8")
        wrapped = self.base / "wrapped.json"
        wrapped.write_text(json.dumps({"fill_map": {"a": "b"}, "base_pt": 10}),
                           encoding="utf-8")
        for path in (flat, wrapped):
            mapping, error = check_residue.load_fill_map(path)
            self.assertIsNone(error)
            self.assertEqual(mapping, {"a": "b"})
        bad = self.base / "bad.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        mapping, error = check_residue.load_fill_map(bad)
        self.assertIsNone(mapping)
        self.assertIn("--fill-map", error)

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
