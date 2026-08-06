# -*- coding: utf-8 -*-
"""Tests for the report module's submission-preflight contribution
(P0 request.yaml + P4 identity fields + check_saeteuk composition), plus the
end-to-end registry composition through core submission_preflight."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

MODULE_SCRIPTS = Path(__file__).parents[1] / "scripts"
CORE_SCRIPTS = Path(__file__).parents[3] / "pipeline" / "scripts"
SCRIPT = MODULE_SCRIPTS / "preflight_report.py"

_spec = importlib.util.spec_from_file_location("preflight_report", SCRIPT)
preflight_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight_report)


class PreflightReportTestCase(unittest.TestCase):
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

    def write_hwpx(self, name="submission.hwpx", text="31415 Lee"):
        target = self.ws / "output" / name
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<doc xmlns:hp="urn:hancom"><p>{text}</p></doc>',
            )
        return target

    def test_missing_request_yaml_is_p0_hard(self):
        self.write_header("output/submission.hwpx")
        self.write_hwpx()
        verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item.get("code") == "P0"
                            for item in verdict["hard"]))

    def test_malformed_request_yaml_is_p0_hard(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            "submission:\n"
            "  output_filename: submission.hwpx\n"
            "  required_fields: []\n",
            encoding="utf-8",
        )
        self.write_hwpx()
        verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item.get("code") == "P0"
                            for item in verdict["hard"]))

    def test_identity_fields_pass_and_fail(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n'
            "required_fields: [student_id, student_name]\n"
            'student_id: "31415"\nstudent_name: "Lee"\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["verdict"], "pass")

        # placeholder value -> P4 hard
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n'
            "required_fields: [student_id]\nstudent_id: TBD\n",
            encoding="utf-8",
        )
        verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item.get("code") == "P4"
                            for item in verdict["hard"]))

    def test_identity_field_absent_from_artifact_is_p4(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\n'
            "required_fields: [student_id]\nstudent_id: 99999\n",
            encoding="utf-8",
        )
        self.write_hwpx(text="no identity here")
        verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item.get("code") == "P4"
                            for item in verdict["hard"]))

    def test_saeteuk_findings_merge_source_tagged(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\nrequired_fields: []\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        child = {
            "ok": False, "verdict": "fail",
            "hard": [{"code": "S1", "msg": "provable contradiction"}],
            "warn": [], "saeteuk_files": ["refs/saeteuk.md"],
        }
        with mock.patch.object(preflight_report.check_saeteuk, "check",
                               return_value=(child, 3)):
            verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 3, verdict)
        tagged = [item for item in verdict["hard"]
                  if item.get("source") == "check_saeteuk"]
        self.assertTrue(any(item.get("code") == "S1" for item in tagged))
        self.assertEqual(verdict["saeteuk_files"], ["refs/saeteuk.md"])

    def test_saeteuk_usage_error_is_exit_two(self):
        self.write_header("output/submission.hwpx")
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\nrequired_fields: []\n',
            encoding="utf-8",
        )
        self.write_hwpx()
        child = {"ok": False, "verdict": "usage_error", "error": "bad input",
                 "hard": [], "warn": []}
        with mock.patch.object(preflight_report.check_saeteuk, "check",
                               return_value=(child, 2)):
            verdict, code = preflight_report.check(self.ws)
        self.assertEqual(code, 2, verdict)
        self.assertEqual(verdict["verdict"], "usage_error")

    def test_end_to_end_composition_through_core_preflight(self):
        """Registry-driven hook: core submission_preflight subprocess-runs
        this contribution (report module enabled) and merges its P0 finding
        source-tagged into the composed verdict."""
        self.write_header("output/submission.hwpx")
        self.write_hwpx()
        (self.ws / "output" / "verdict_v06.json").write_text(
            json.dumps({"proof_grade": "advisory"}), encoding="utf-8")
        # no request.yaml: core notes it; the module contribution emits P0
        core = subprocess.run(
            [sys.executable, str(CORE_SCRIPTS / "submission_preflight.py"),
             str(self.ws)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(core.returncode, 3, core.stdout or core.stderr)
        verdict = json.loads(core.stdout)
        p0 = [item for item in verdict["hard"] if item.get("code") == "P0"]
        self.assertTrue(p0, verdict)
        self.assertEqual(p0[0]["source"], "preflight_report")
        self.assertIn(
            {"name": "preflight_report", "module": "report", "exit": 3},
            verdict["preflight_contributions"])


if __name__ == "__main__":
    unittest.main()
