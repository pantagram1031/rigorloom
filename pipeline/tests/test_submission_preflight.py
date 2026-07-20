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

    def write_hwpx(
        self, name="submission.hwpx", text="31415 Lee", *, equations=False,
        structure="",
    ):
        target = self.ws / "output" / name
        equation = "<hp:equation/>" if equations else ""
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<doc xmlns:hp="urn:hancom">{structure}<p>{text}</p>'
                f'{equation}</doc>',
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

    def test_saeteuk_exit_three_and_child_inconsistency_fail_closed(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\nrequired_fields: []\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        self.write_proof_grade("none")
        cases = (
            ({
                "ok": False,
                "verdict": "fail",
                "hard": [],
                "warn": [],
                "saeteuk_files": [],
            }, 3, None),
            ({
                "ok": False,
                "verdict": "fail",
                "hard": [],
                "warn": [],
                "saeteuk_files": [],
            }, 0, "saeteuk_checker_inconsistent"),
        )

        for child_verdict, child_code, expected_hard in cases:
            with self.subTest(child_code=child_code):
                with mock.patch.object(
                    submission_preflight.check_saeteuk,
                    "check",
                    return_value=(child_verdict, child_code),
                ):
                    verdict, code = submission_preflight.check(
                        self.ws, allow_unproven=True
                    )

                self.assertEqual(code, 3, verdict)
                self.assertFalse(verdict["ok"])
                if expected_hard:
                    self.assertTrue(any(
                        finding.get("code") == expected_hard
                        for finding in verdict["hard"]
                    ), verdict)

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

    def test_experimental_rhwp_is_never_submission_grade(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("experimental-rhwp")

        verdict, code = submission_preflight.check(
            self.ws,
            allow_advisory=True,
            reason="experimental render evidence only",
        )

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P5" for item in verdict["hard"]))

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


    def test_form_structure_baseline_match_passes(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        structure = '<hp:secPr landscape="false"/>'
        artifact = self.write_hwpx(structure=structure)
        self.write_proof_grade()
        digest = submission_preflight._hwpx_form_structure_sha256(artifact)
        self.write_hwpx(text="changed inserted body text", structure=structure)
        (self.ws / "form_baseline.json").write_text(
            json.dumps({"structure_sha256": digest}), encoding="utf-8"
        )

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["form_structure_sha256"], digest)
        self.assertFalse(any(
            item["code"] == "form_baseline_absent" for item in verdict["warn"]
        ))

    def test_mutated_form_skeleton_is_hard_form_mutated(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        artifact = self.write_hwpx(
            structure='<hp:secPr landscape="false"/>'
        )
        self.write_proof_grade()
        baseline = submission_preflight._hwpx_form_structure_sha256(artifact)
        (self.ws / "form_baseline.json").write_text(
            json.dumps({"structure_sha256": baseline}), encoding="utf-8"
        )
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<doc xmlns:hp="urn:hancom"><hp:secPr landscape="true"/>'
                '<p>different body text</p></doc>',
            )

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "form_mutated" for item in verdict["hard"]
        ), verdict)

    def test_mutated_table_skeleton_is_hard_form_mutated(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        artifact = self.write_hwpx(
            structure=(
                '<hp:tbl rowCnt="1" colCnt="1">'
                '<hp:tc colAddr="0" rowAddr="0"><hp:p/></hp:tc>'
                '</hp:tbl>'
            )
        )
        self.write_proof_grade()
        baseline = submission_preflight._hwpx_form_structure_sha256(artifact)
        (self.ws / "form_baseline.json").write_text(
            json.dumps({"structure_sha256": baseline}), encoding="utf-8"
        )
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<doc xmlns:hp="urn:hancom">'
                '<hp:tbl rowCnt="1" colCnt="2">'
                '<hp:tc colAddr="0" rowAddr="0"><hp:p/></hp:tc>'
                '<hp:tc colAddr="1" rowAddr="0"><hp:p/></hp:tc>'
                '</hp:tbl><p>same body text</p></doc>',
            )

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "form_mutated" for item in verdict["hard"]
        ), verdict)

    def test_no_form_baseline_is_warn(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade()

        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "form_baseline_absent" for item in verdict["warn"]
        ), verdict)

    def _prepare_certified_workspace(self, *, opt_in=True, certificate=True):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n', encoding="utf-8"
        )
        artifact = self.write_hwpx()
        self.write_proof_grade("certified")
        build_lines = ["doc_backend: hwpx"]
        if opt_in:
            build_lines += [
                "certified_render: true",
                "render_certificate: render-certificate.json",
            ]
        (self.ws / "build.yaml").write_text(
            "\n".join(build_lines) + "\n", encoding="utf-8"
        )
        cert_path = self.ws / "render-certificate.json"
        if certificate:
            cert_path.write_text("{}\n", encoding="utf-8")
        return artifact, cert_path

    def test_certified_grade_requires_opt_in_check_pass_and_certificate_reverify(self):
        artifact, cert_path = self._prepare_certified_workspace()
        valid = {"ok": True, "reason_code": "certificate_valid"}
        eligible = {"ok": True, "eligible": True, "reason_code": "eligible"}

        with (
            mock.patch.object(
                submission_preflight.render_cert, "verify_certificate",
                return_value=valid,
            ) as verify,
            mock.patch.object(
                submission_preflight.render_cert, "check_document",
                return_value=eligible,
            ) as check_document,
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 0, verdict)
        verify.assert_called_once_with(cert_path)
        check_document.assert_called_once_with(artifact, cert_path)
        self.assertEqual(verdict["proof_grade"], "certified")
        self.assertEqual(verdict["render_certificate"], "render-certificate.json")
        self.assertEqual(verdict["render_cert_check"]["reason_code"], "eligible")

    def test_certified_grade_without_build_opt_in_is_today_style_p5_failure(self):
        self._prepare_certified_workspace(opt_in=False, certificate=False)

        verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "P5" for item in verdict["hard"]), verdict)

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_certified_pdf_submission_rechecks_the_assembled_hwpx(self):
        import fitz

        self.write_header("output/submission.pdf")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.pdf"\n', encoding="utf-8"
        )
        document = fitz.open()
        document.new_page().insert_text((72, 72), "submission text")
        document.save(self.ws / "output" / "submission.pdf")
        document.close()
        assembled = self.write_hwpx(name="out.hwpx")
        self.write_proof_grade("certified")
        (self.ws / "build.yaml").write_text(
            "certified_render: true\n"
            "render_certificate: render-certificate.json\n",
            encoding="utf-8",
        )
        cert_path = self.ws / "render-certificate.json"
        cert_path.write_text("{}", encoding="utf-8")

        with (
            mock.patch.object(
                submission_preflight.render_cert, "verify_certificate",
                return_value={"ok": True, "reason_code": "certificate_valid"},
            ),
            mock.patch.object(
                submission_preflight.render_cert, "check_document",
                return_value={
                    "ok": True, "eligible": True, "reason_code": "eligible"
                },
            ) as check_document,
        ):
            verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 0, verdict)
        check_document.assert_called_once_with(assembled, cert_path)
        self.assertEqual(verdict["render_cert_document"], "output/out.hwpx")

    def test_certified_grade_fails_when_certificate_reverify_or_check_fails(self):
        self._prepare_certified_workspace()
        cases = (
            ({"ok": False, "reason_code": "certificate_hash_mismatch"},
             {"eligible": True, "reason_code": "eligible"},
             "certificate_hash_mismatch"),
            ({"ok": True, "reason_code": "certificate_valid"},
             {"eligible": False, "reason_code": "envelope_mismatch"},
             "envelope_mismatch"),
        )
        for verification, eligibility, expected in cases:
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    submission_preflight.render_cert, "verify_certificate",
                    return_value=verification,
                ),
                mock.patch.object(
                    submission_preflight.render_cert, "check_document",
                    return_value=eligibility,
                ),
            ):
                verdict, code = submission_preflight.check(self.ws)
            self.assertEqual(code, 3, verdict)
            self.assertTrue(any(
                item["code"] == "P5" and expected in item["msg"]
                for item in verdict["hard"]
            ), verdict)


if __name__ == "__main__":
    unittest.main()
