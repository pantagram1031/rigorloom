# -*- coding: utf-8 -*-
"""H2 advisory-only regression guard — the style module's half.

Variant-audit verdict (docs/research/variant-audit.md, "Humanization
measurement" row): score-based AI-tell detection is ADVISORY ONLY and must
never trigger a gate. The stage-graph and repo-wide script-scan pins live
with the stage machine (modules/report/tests/test_h2_advisory_only.py);
this file pins the humanization controller's own contract: `prepare` must
keep declaring the detector advisory (policy.detector_is_advisory), so
downstream workers inherit the rule.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HUMANIZE = Path(__file__).parents[1] / "scripts" / "humanization_ctl.py"


class HumanizationContractStaysAdvisory(unittest.TestCase):
    def test_prepare_declares_detector_is_advisory(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "report-demo"
            (ws / "bundle").mkdir(parents=True)
            (ws / "bundle" / "content.md").write_text(
                "# 결론\n\n측정 결과를 서술한다.\n", encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, str(HUMANIZE), "prepare", str(ws)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(
                (ws / "bundle" / "humanization_report.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertIs(payload["policy"]["detector_is_advisory"], True)


if __name__ == "__main__":
    unittest.main()
