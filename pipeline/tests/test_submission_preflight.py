"""Tests for the Stage 6 submission package preflight."""
from __future__ import annotations

import json
import importlib.util
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import submission_preflight  # noqa: E402


class SubmissionPreflightTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-preflight"
        (self.ws / "output").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_header(self, canonical):
        (self.ws / "PIPELINE.md").write_text(
            "```yaml\n" + f'canonical_output: "{canonical}"\n' +
            "stages:\n```\n", encoding="utf-8")

    def write_proof_grade(self, grade="hancom"):
        (self.ws / "output" / "verdict_v06.json").write_text(
            json.dumps({"proof_grade": grade}), encoding="utf-8")

    def write_hwpx(self, name="submission.hwpx", text="31415 Lee", *, equations=False):
        target = self.ws / "output" / name
        equation = "<hp:equation/>" if equations else ""
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<doc xmlns:hp="urn:hancom"><p>{text}</p>{equation}</doc>',
            )
        return target

    def test_valid_hwpx_filename_identity_reopen_and_proof_pass(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n'
            "required_fields: [student_id, student_name]\n"
            'student_id: "31415"\nstudent_name: "Lee"\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        self.write_proof_grade()
        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["artifact"], "output/submission.hwpx")
        self.assertEqual(verdict["proof_grade"], "hancom")

    def test_one_optional_request_key_can_be_absent_with_note(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "required_fields: []\n", encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("advisory")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any("output_filename" in note for note in verdict["notes"]))

    def test_wrong_structure_with_only_indented_expected_keys_is_malformed(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "submission:\n"
            "  output_filename: submission.hwpx\n"
            "  required_fields: []\n",
            encoding="utf-8",
        )
        self.write_hwpx()
        self.write_proof_grade()

        verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P0" for item in verdict["hard"]))
        self.assertFalse(any("skipped" in note for note in verdict["notes"]))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_valid_text_bearing_pdf_reopens(self):
        import fitz
        self.write_header("output/submission.pdf")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.pdf"\n', encoding="utf-8")
        document = fitz.open()
        document.new_page().insert_text((72, 72), "submission text")
        document.save(self.ws / "output" / "submission.pdf")
        document.close()
        self.write_proof_grade("advisory")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 0, verdict)

    def test_missing_request_yaml_fails_closed(self):
        self.write_header("output/submission.hwpx")
        self.write_hwpx()
        self.write_proof_grade()
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P0" for item in verdict["hard"]))

    def test_malformed_request_yaml_fails_closed(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade()
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P0" for item in verdict["hard"]))

    def test_none_proof_grade_requires_explicit_draft_escape(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("none")

        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P5" for item in verdict["hard"]))

        verdict, code = submission_preflight.check(self.ws, allow_unproven=True)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any("draft" in note for note in verdict["notes"]))

    def test_hancom_grade_without_local_hancom_is_unverifiable_here(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("hancom")

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": False}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "proof_grade_unverifiable_here"
            for item in verdict["hard"]
        ), verdict)

    def test_advisory_grade_with_equations_is_unverifiable(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx(equations=True)
        self.write_proof_grade("advisory")

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": False}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "proof_grade_unverifiable_here"
            for item in verdict["hard"]
        ), verdict)

    def test_advisory_no_equations_allows_explicit_draft_escape(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("advisory")

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": False}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(
                self.ws,
                allow_advisory=True,
                reason="delivery host lacks the print-grade renderer",
            )

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any("draft" in note for note in verdict["notes"]))
        self.assertEqual(
            verdict["advisory_reason"],
            "delivery host lacks the print-grade renderer",
        )

    def test_allow_advisory_without_reason_is_usage_error(self):
        verdict, code = submission_preflight.check(
            self.ws, allow_advisory=True
        )

        self.assertEqual(code, 2, verdict)
        self.assertIn("--reason", verdict["error"])

    def test_newer_scorecard_cannot_spoof_canonical_proof_grade(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("none")
        genuine = self.ws / "output" / "verdict_v06.json"
        spoof = self.ws / "output" / "scorecard.json"
        spoof.write_text(
            json.dumps({"proof_grade": "advisory"}), encoding="utf-8")
        genuine_mtime = genuine.stat().st_mtime
        os.utime(spoof, (genuine_mtime + 10, genuine_mtime + 10))

        verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["proof_grade"], "none")
        self.assertEqual(
            verdict["proof_grade_source"], "output/verdict_v06.json")
        self.assertTrue(any(item["code"] == "P5" for item in verdict["hard"]))

    def test_filename_or_identity_mismatch_fails(self):
        self.write_header("output/wrong.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "expected.hwpx"\n'
            "required_fields: [student_id]\nstudent_id: 31415\n",
            encoding="utf-8",
        )
        self.write_hwpx("wrong.hwpx", "no identity here")
        self.write_proof_grade()
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        codes = {item["code"] for item in verdict["hard"]}
        self.assertIn("P2", codes)
        self.assertIn("P4", codes)

    def test_corrupt_hwpx_and_missing_proof_grade_fail_closed(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "required_fields: []\n", encoding="utf-8")
        (self.ws / "output" / "submission.hwpx").write_bytes(b"not a zip")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        codes = {item["code"] for item in verdict["hard"]}
        self.assertIn("P3", codes)
        self.assertIn("P5", codes)


if __name__ == "__main__":
    unittest.main()
