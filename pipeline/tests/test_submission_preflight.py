"""Tests for the Stage 6 submission package preflight."""
from __future__ import annotations

import json
import importlib.util
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import submission_preflight  # noqa: E402
import document_evidence  # noqa: E402


class SubmissionPreflightTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-preflight"
        (self.ws / "output").mkdir(parents=True)
        # Core tests must be matrix-independent: stub the registry so no real
        # module contribution runs unless a test installs a fake one.
        self._registry_patch = mock.patch.object(
            submission_preflight.module_registry, "ModuleRegistry")
        registry_cls = self._registry_patch.start()
        self.registry = registry_cls.return_value
        self.registry.enabled_preflight.return_value = []

    def tearDown(self):
        self._registry_patch.stop()
        self._tmp.cleanup()

    def install_contribution(self, payload, exit_code, name="fake_preflight"):
        """Declare one fake registry preflight contribution whose script
        prints ``payload`` (dict -> JSON, str -> verbatim) and exits
        ``exit_code``."""
        script = Path(self._tmp.name) / f"{name}.py"
        body = payload if isinstance(payload, str) else json.dumps(payload)
        script.write_text(
            "import sys\n"
            f"sys.stdout.write({body!r})\n"
            f"sys.exit({exit_code})\n", encoding="utf-8")
        self.registry.enabled_preflight.return_value = [
            {"name": name, "script": str(script), "module": "fake"}]
        return script

    def write_header(self, canonical):
        (self.ws / "PIPELINE.md").write_text(
            "```yaml\n" + f'canonical_output: "{canonical}"\n' +
            "stages:\n```\n", encoding="utf-8")

    def write_proof_grade(self, grade="hancom"):
        (self.ws / "output" / "verdict_v06.json").write_text(
            json.dumps({
                "proof_grade": grade,
                "converged": True,
                "checks": {},
                "style_anomalies": [],
            }), encoding="utf-8")
        if grade == "none":
            return
        # Non-none grades now have a deliberately explicit receipt contract.
        # Keep the legacy fixture helper honest by binding its synthetic proof
        # to the artifact written by the test, rather than weakening the
        # production preflight for old fixtures.
        candidates = sorted(
            path for path in (self.ws / "output").iterdir()
            if path.is_file() and path.suffix.lower() in {".hwpx", ".pdf"}
        )
        if not candidates:
            return
        canonical = None
        try:
            pipeline_text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
            match = re.search(
                r'''canonical_output:\s*["']?([^"'\r\n]+)''', pipeline_text)
            if match:
                canonical = self.ws / match.group(1).strip()
        except OSError:
            canonical = None
        artifact = canonical if canonical is not None and canonical.is_file() else candidates[0]
        backend, evidence_class = {
            "hancom": ("native_hancom_windows", "native_render"),
            "certified": ("certified_renderer", "certified_render"),
            "advisory": ("oss_preview_libreoffice", "advisory_render"),
            "experimental-rhwp": ("oss_preview_rhwp", "diagnostic_render"),
        }[grade]
        if artifact.suffix.lower() == ".pdf":
            input_path = self.ws / "output" / "receipt-input.hwpx"
            if not input_path.exists():
                with zipfile.ZipFile(input_path, "w") as archive:
                    archive.writestr(
                        "Contents/section0.xml",
                        '<doc xmlns:hp="urn:hancom"><hp:p>receipt input</hp:p></doc>',
                    )
            output_path = artifact
        else:
            input_path = artifact
            output_path = self.ws / "output" / (
                "receipt-render.svg" if grade == "experimental-rhwp"
                else "receipt-render.pdf"
            )
            output_path.write_bytes(b"rendered bytes")
        receipt = document_evidence.build_receipt(
            self.ws,
            backend=backend,
            evidence_class=evidence_class,
            terminal_state="succeeded",
            input_path=input_path,
            output_path=output_path,
            input_role="assembled_hwpx",
            output_role=("diagnostic_svg" if grade == "experimental-rhwp"
                         else "rendered_pdf"),
            exit_code=0,
            reproducible_here=False,
        )
        document_evidence.write_receipt(self.ws, receipt)

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

    def _passing_workspace(self, proof_grade="none"):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\nrequired_fields: []\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        self.write_proof_grade(proof_grade)

    def test_contribution_exit_three_and_inconsistency_fail_closed(self):
        """A registry preflight contribution that fails, or whose exit code
        contradicts its JSON verdict, rejects the composed gate (the merge
        semantics the in-process saeteuk composition had before W3-S2b)."""
        self._passing_workspace()
        cases = (
            ({
                "ok": False,
                "verdict": "fail",
                "hard": [{"code": "P0", "msg": "request.yaml is missing"}],
                "warn": [],
            }, 3, "P0"),
            ({
                "ok": False,
                "verdict": "fail",
                "hard": [],
                "warn": [],
            }, 0, "preflight_contribution_inconsistent"),
        )

        for child_verdict, child_code, expected_hard in cases:
            with self.subTest(child_code=child_code):
                self.install_contribution(child_verdict, child_code)
                verdict, code = submission_preflight.check(
                    self.ws, allow_unproven=True
                )

                self.assertEqual(code, 3, verdict)
                self.assertFalse(verdict["ok"])
                self.assertTrue(any(
                    finding.get("code") == expected_hard
                    for finding in verdict["hard"]
                ), verdict)
                # every merged finding is source-tagged
                self.assertTrue(all(
                    finding.get("source") == "fake_preflight"
                    for finding in verdict["hard"]
                ), verdict)
                self.assertEqual(
                    verdict["preflight_contributions"],
                    [{"name": "fake_preflight", "module": "fake", "exit": 3}])

    def test_contribution_usage_error_is_source_tagged_usage_exit_two(self):
        self._passing_workspace()
        self.install_contribution({
            "ok": False, "verdict": "usage_error",
            "error": "request.yaml unreadable",
            "hard": [], "warn": [],
        }, 2)
        verdict, code = submission_preflight.check(self.ws, allow_unproven=True)
        self.assertEqual(code, 2, verdict)
        self.assertTrue(any(
            finding.get("code") == "USAGE"
            and finding.get("source") == "fake_preflight"
            for finding in verdict["hard"]
        ), verdict)

    def test_contribution_non_json_output_is_hard_finding(self):
        self._passing_workspace()
        self.install_contribution("this is not a JSON verdict", 0)
        verdict, code = submission_preflight.check(self.ws, allow_unproven=True)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "preflight_contribution_inconsistent"
            for finding in verdict["hard"]
        ), verdict)

    def test_contribution_warn_findings_merge_without_failing(self):
        self._passing_workspace()
        self.install_contribution({
            "ok": True, "verdict": "pass",
            "hard": [], "warn": [{"code": "W1", "msg": "advisory"}],
        }, 0)
        verdict, code = submission_preflight.check(self.ws, allow_unproven=True)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(
            [w for w in verdict["warn"] if w.get("code") == "W1"][0]["source"],
            "fake_preflight")

    def test_no_enabled_contributions_means_checks_simply_absent(self):
        """Core-only semantics: with no modules enabled the workspace-
        vocabulary checks are absent — absence is not failure."""
        self._passing_workspace()
        verdict, code = submission_preflight.check(self.ws, allow_unproven=True)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["preflight_contributions"], [])

    def test_one_optional_request_key_can_be_absent_with_note(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "required_fields: []\n", encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("advisory")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)
        self.assertTrue(any("output_filename" in note for note in verdict["notes"]))

    def test_malformed_request_structure_is_note_p0_is_module_contribution(self):
        """Core keeps only the artifact/proof half (W3-S2b): an unusable
        request.yaml downgrades filename matching to a note here; the P0
        hard finding is the report module's preflight contribution."""
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "submission:\n"
            "  output_filename: submission.hwpx\n"
            "  required_fields: []\n",
            encoding="utf-8",
        )
        self.write_hwpx()
        self.write_proof_grade("advisory")

        verdict, code = submission_preflight.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)
        self.assertFalse(any(item["code"] == "P0" for item in verdict["hard"]))
        self.assertTrue(any("request.yaml unusable" in note
                            for note in verdict["notes"]))

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
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)

    def test_missing_request_yaml_is_note_in_core(self):
        self.write_header("output/submission.hwpx")
        self.write_hwpx()
        self.write_proof_grade("advisory")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)
        self.assertFalse(any(item["code"] == "P0" for item in verdict["hard"]))
        self.assertTrue(any("request.yaml unusable" in note
                            for note in verdict["notes"]))

    def test_malformed_request_yaml_is_note_in_core(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx\n', encoding="utf-8")
        self.write_hwpx()
        self.write_proof_grade("advisory")
        verdict, code = submission_preflight.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)
        self.assertFalse(any(item["code"] == "P0" for item in verdict["hard"]))

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

    def test_hancom_grade_remains_historically_valid_without_local_hancom(self):
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

        self.assertEqual(code, 0, verdict)
        self.assertIn(
            "current-host renderer capabilities are informational; historical proof comes from the validated artifact receipt",
            verdict["notes"],
        )

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

        # A draft flag cannot bypass the T63 quality contract: advisory
        # requires a current, hash-bound passed quality result.
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            finding.get("code") == "proof_quality_missing"
            for finding in verdict["hard"]
        ), verdict)
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

    def test_filename_mismatch_fails(self):
        """P2 stays core; the P4 identity half is the report module's
        preflight contribution since the W3-S2b split."""
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
        self.assertNotIn("P4", codes)

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
        digest = submission_preflight._hwpx_form_structure_sha256(artifact)
        self.write_hwpx(text="changed inserted body text", structure=structure)
        # The receipt must bind the final bytes, not the pre-baseline fixture.
        self.write_proof_grade()
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
