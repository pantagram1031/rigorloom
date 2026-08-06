# -*- coding: utf-8 -*-
"""H2 advisory-only regression guard (test-as-documentation).

Variant-audit verdict (docs/research/variant-audit.md, "Humanization
measurement" row): score-based AI-tell detection is ADVISORY ONLY and must
never trigger a gate — on the most-changed windpath section (similarity
0.747 pre→post, a ~25% change) the detector scored 0.1 both before and
after: zero discrimination.

At audit time NO code path gated on detector scores; these tests pin that
state so a future change is a conscious decision, not drift:

1. The check registry (the stage graphs stages.yaml / stages-edit.yaml —
   the only place pipeline_ctl binds script gates to checkers) must not
   bind any detector-scored checker.
2. No pipeline script may even reference the detector score APIs
   (score_ai_tells / interference_index). If a legitimate advisory use
   ever lands, add the file to ALLOWED_REFERENCES below together with a
   test asserting the reference cannot reach a gate verdict.
3. The humanization prepare contract must keep declaring the detector
   advisory (policy.detector_is_advisory), so downstream workers inherit
   the rule. That pin lives with the style module since W4.2:
   modules/style/tests/test_h2_advisory_style.py.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

MODULE_SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(MODULE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODULE_SCRIPTS))
import pipeline_ctl as ctl  # noqa: E402

ROOT = Path(__file__).parents[3]
SCRIPTS_DIR = ROOT / "pipeline" / "scripts"

DETECTOR_TOKEN_RE = re.compile(r"score_ai_tells|interference_index")

# Pipeline scripts allowed to mention the detector score APIs. Empty by
# design: any new advisory reference must be added here deliberately, with
# an accompanying test proving it cannot flip a gate.
ALLOWED_REFERENCES: frozenset[str] = frozenset()


class CheckRegistryHasNoDetectorTrigger(unittest.TestCase):
    def test_no_stage_graph_gate_binds_a_detector_checker(self):
        for graph in sorted(ctl.GRAPH_FILES):
            rows = ctl.load_stages_config(graph=graph)
            self.assertTrue(rows, f"stage graph {graph!r} is empty")
            for row in rows:
                gate = row.get("gate")
                if not gate or not gate.get("checker"):
                    continue
                argv = " ".join(gate["checker"])
                self.assertIsNone(
                    DETECTOR_TOKEN_RE.search(argv),
                    f"gate {gate.get('name')!r} ({graph}) binds a "
                    f"detector-scored checker: {argv!r} — H2 is advisory only",
                )

    def test_no_pipeline_script_references_detector_score_apis(self):
        offenders = []
        # The H2-advisory policy governs core pipeline scripts AND every
        # distribution module's payload (this test lives with the stage
        # machine since W3-S2b, but the scan stays a repo-policy scan — a
        # filesystem sweep, no module imports and no module names).
        scan_dirs = (SCRIPTS_DIR, *sorted((ROOT / "modules").glob("*/scripts")))
        for scan_dir in scan_dirs:
            for script in sorted(scan_dir.glob("*.py")):
                if script.name in ALLOWED_REFERENCES:
                    continue
                if DETECTOR_TOKEN_RE.search(script.read_text(encoding="utf-8")):
                    offenders.append(script.name)
        self.assertEqual(
            offenders, [],
            "pipeline scripts reference detector score APIs; H2 is advisory "
            "only — extend ALLOWED_REFERENCES consciously if this is truly "
            "advisory, and prove it cannot reach a gate verdict",
        )


# HumanizationContractStaysAdvisory moved to
# modules/style/tests/test_h2_advisory_style.py (v0.16 W4.2): the prepare
# contract under test is the style module's humanization controller.


if __name__ == "__main__":
    unittest.main()
