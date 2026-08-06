# -*- coding: utf-8 -*-
"""Verdict-contradiction rejection (shared-miss #5).

The proof-loop verdict writer lives in the external hwp-master repo
(``scripts/fill_report.py``): after phase-1 converges it merges the proof
fragment into the same object (``out_obj.update(proof_frag)``), so a proof
exhaust yields ``converged: true`` together with ``status: escalate_human``
in one verdict file. rigorloom does not own that writer, so the fix is
read-time rejection: ``verdict_schema`` flags the pair and Stage 6
``submission_preflight`` HARD-fails on it.

The integration test below is the originally-failing reproduction: before
``submission_preflight`` was wired to ``verdict_schema``, a workspace whose
``output/verdict_v06.json`` carried the contradictory pair sailed through
preflight with exit 0.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import submission_preflight  # noqa: E402
import verdict_schema  # noqa: E402


class ContradictionFindingsTests(unittest.TestCase):
    def test_converged_true_with_escalate_human_is_rejected(self):
        findings = verdict_schema.contradiction_findings(
            {"converged": True, "status": "escalate_human"}
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], "verdict_contradiction")

    def test_status_matching_is_case_and_space_tolerant(self):
        findings = verdict_schema.contradiction_findings(
            {"converged": True, "status": "  Escalate_Human "}
        )
        self.assertEqual(len(findings), 1)

    def test_non_contradictory_pairs_pass(self):
        for verdict in (
            {"converged": True, "status": "awaiting_judge"},
            {"converged": True},
            {"converged": False, "status": "escalate_human"},
            {"converged": False},
            {},
            None,
            "not-a-dict",
        ):
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    verdict_schema.contradiction_findings(verdict), []
                )

    def test_truthy_but_not_true_converged_is_not_flagged(self):
        # Only the writer's boolean true forms the confirmed contradictory
        # pair; a string "true" is a different (shape) defect.
        findings = verdict_schema.contradiction_findings(
            {"converged": "true", "status": "escalate_human"}
        )
        self.assertEqual(findings, [])

    def test_finding_carries_the_at_location(self):
        findings = verdict_schema.contradiction_findings(
            {"converged": True, "status": "escalate_human"},
            at="output/verdict_v06.json",
        )
        self.assertEqual(findings[0]["at"], "output/verdict_v06.json")


class ValidateVerdictFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_file_yields_no_findings(self):
        self.assertEqual(
            verdict_schema.validate_verdict_file(self.base / "gone.json"), []
        )

    def test_contradictory_file_yields_finding(self):
        path = self.base / "verdict_v06.json"
        path.write_text(
            json.dumps({"converged": True, "status": "escalate_human"}),
            encoding="utf-8",
        )
        findings = verdict_schema.validate_verdict_file(path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], "verdict_contradiction")


class PreflightRejectsContradictionTests(unittest.TestCase):
    """Reproduction of the shared bug at rigorloom's fail-closed read point."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-contradiction"
        (self.ws / "output").mkdir(parents=True)
        (self.ws / "PIPELINE.md").write_text(
            "```yaml\n"
            'canonical_output: "output/submission.hwpx"\n'
            "stages:\n```\n",
            encoding="utf-8",
        )
        (self.ws / "request.yaml").write_text(
            'output_filename: "submission.hwpx"\nrequired_fields: []\n',
            encoding="utf-8",
        )
        with zipfile.ZipFile(self.ws / "output" / "submission.hwpx", "w") as z:
            z.writestr(
                "Contents/section0.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<doc xmlns:hp="urn:hancom"><p>31415 Lee</p></doc>',
            )

    def tearDown(self):
        self._tmp.cleanup()

    def run_preflight(self, verdict_payload: dict):
        (self.ws / "output" / "verdict_v06.json").write_text(
            json.dumps(verdict_payload), encoding="utf-8"
        )
        with mock.patch.object(
            submission_preflight.render_probe,
            "probe",
            return_value={"capabilities": {"hancom_com": True}, "renderers": []},
        ):
            return submission_preflight.check(self.ws)

    def test_contradictory_assembly_verdict_hard_fails_preflight(self):
        verdict, code = self.run_preflight({
            "proof_grade": "hancom",
            "converged": True,
            "status": "escalate_human",
            "proof_iter": 4,
        })
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any(
            item["code"] == "verdict_contradiction"
            and item["at"] == "output/verdict_v06.json"
            for item in verdict["hard"]
        ), verdict)

    def test_consistent_assembly_verdict_still_passes(self):
        verdict, code = self.run_preflight({
            "proof_grade": "hancom",
            "converged": True,
            "status": "awaiting_judge",
        })
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])

    def test_escalated_but_not_converged_verdict_is_not_a_contradiction(self):
        # A truthful escalation (converged:false) is not a schema violation —
        # other gates decide whether an unconverged verdict may ship.
        verdict, code = self.run_preflight({
            "proof_grade": "hancom",
            "converged": False,
            "status": "escalate_human",
        })
        self.assertFalse(any(
            item["code"] == "verdict_contradiction"
            for item in verdict["hard"]
        ), verdict)


if __name__ == "__main__":
    unittest.main()
