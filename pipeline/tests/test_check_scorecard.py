"""Tests for the fail-closed Stage 5.7 scorecard gate."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_scorecard  # noqa: E402


class CheckScorecardTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-scorecard"
        (self.ws / "output").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_scorecard(self, payload, name="scorecard.json"):
        (self.ws / "output" / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_well_formed_shipping_scorecard_passes(self):
        self.write_scorecard({
            "dimensions": {"logic": 9, "source_coverage": 8},
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "panelists": [{"name": "logic", "verdict": "pass", "findings": [
                {"blocking": False, "message": "minor wording"}
            ]}],
            "verdict": "approved",
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])

    def test_any_true_stop_line_fails_regardless_of_scores(self):
        self.write_scorecard({
            "weighted_score": 100,
            "stop_lines": {
                "SENSITIVE_FRAMING": True,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "panelists": [{"name": "logic", "verdict": "pass"}],
            "verdict": "approved",
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S1" for item in verdict["hard"]))

    def test_any_panelist_blocking_finding_fails(self):
        self.write_scorecard({
            "weighted_score": 99,
            "panelists": [{
                "name": "source",
                "verdict": "pass",
                "findings": [{"blocking": True, "message": "claim has no source"}],
            }],
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "verdict": "approved",
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S2" for item in verdict["hard"]))

    def test_reject_decision_and_panelist_verdict_fail_closed(self):
        self.write_scorecard({
            "decision": "reject",
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "panelists": [{"name": "logic", "verdict": "reject"}],
        })

        verdict, code = check_scorecard.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "S3" and "overall decision" in item["msg"]
            for item in verdict["hard"]
        ), verdict)

        self.write_scorecard({
            "overall_decision": "approved",
            "decision": "reject",
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "panelists": [{"name": "logic", "verdict": "blocked"}],
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S3" for item in verdict["hard"]))
        self.assertTrue(any(item["code"] == "S2" for item in verdict["hard"]))

    def test_missing_or_malformed_scorecard_fails_closed(self):
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        (self.ws / "output" / "scorecard.json").write_text("{bad", encoding="utf-8")
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S0" for item in verdict["hard"]))

    def test_missing_explicit_stop_line_fields_is_malformed(self):
        self.write_scorecard({
            "weighted_score": 100,
            "panelists": [{"name": "logic", "verdict": "pass"}],
            "verdict": "approved",
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S0" for item in verdict["hard"]))

    def test_only_three_false_stop_lines_is_malformed(self):
        self.write_scorecard({
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
        })
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S0" for item in verdict["hard"]))

    def test_panelists_and_decisions_are_required(self):
        base = {
            "stop_lines": {
                "SENSITIVE_FRAMING": False,
                "LOAD_BEARING_DISPUTE": False,
                "UNSUPPORTED_NOVELTY": False,
            },
            "verdict": "approved",
        }
        for panelists in (None, [], [{"name": "logic"}]):
            payload = dict(base)
            if panelists is not None:
                payload["panelists"] = panelists
            self.write_scorecard(payload)
            verdict, code = check_scorecard.check(self.ws)
            self.assertEqual(code, 3, verdict)
            self.assertTrue(any(item["code"] == "S0" for item in verdict["hard"]))

        payload = dict(base)
        payload.pop("verdict")
        payload["panelists"] = [{"name": "logic", "verdict": "pass"}]
        self.write_scorecard(payload)
        verdict, code = check_scorecard.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "S0" for item in verdict["hard"]))


if __name__ == "__main__":
    unittest.main()
