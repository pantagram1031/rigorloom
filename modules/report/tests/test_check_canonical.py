# -*- coding: utf-8 -*-
"""Tests for canonical/FINAL pointer validation (shared-miss #3/#4)."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_canonical.py"
_spec = importlib.util.spec_from_file_location("check_canonical", SCRIPT)
check_canonical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_canonical)


class CheckCanonicalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        self.ws.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_header(self, canonical: str, stages: dict[str, str]):
        stage_lines = "\n".join(
            f'  "{num}":   {{status: {status}, gate: null}}'
            for num, status in stages.items()
        )
        (self.ws / "PIPELINE.md").write_text(
            "```yaml\n"
            "# pipeline-state: v0.4\n"
            f"canonical_output: {canonical}\n"
            "stages:\n"
            f"{stage_lines}\n"
            "```\n",
            encoding="utf-8",
        )

    def write_handoff(self, payload: dict):
        pipeline_dir = self.ws / ".pipeline"
        pipeline_dir.mkdir(exist_ok=True)
        (pipeline_dir / "handoff.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def write_output(self, rel="output/out.hwpx") -> str:
        target = self.ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"artifact")
        return rel

    # ── HARD: null pointer while delivery stages claim done ─────────
    def test_literal_null_with_done_delivery_stage_is_hard(self):
        self.write_header("null", {"5": "done", "6": "done"})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "canonical_null_after_done"
            for item in verdict["hard"]
        ), verdict)

    def test_handoff_done_claim_without_pointer_is_hard(self):
        # No PIPELINE.md at all — E-shape workspace with only a handoff that
        # says the workflow completed but never named its ship artifact.
        self.write_handoff({"completed_stage": "6", "next_stage": None})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "canonical_null_after_done"
            for item in verdict["hard"]
        ), verdict)

    # ── HARD: pointer at a nonexistent path ──────────────────────────
    def test_pointer_to_missing_path_is_hard(self):
        self.write_header('"output/out.hwpx"', {"5": "done"})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "canonical_target_missing"
            for item in verdict["hard"]
        ), verdict)

    def test_pointer_to_missing_path_is_hard_even_without_done_claims(self):
        # A declared pointer must always resolve — rot is rot regardless of
        # what the stage table currently claims.
        self.write_header('"output/out.hwpx"', {"5": "in_progress"})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 3, verdict)

    # ── pass cases ───────────────────────────────────────────────────
    def test_pointer_set_and_existing_passes(self):
        rel = self.write_output()
        self.write_header(f'"{rel}"', {"5": "done", "6": "done"})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["canonical_output"], rel)
        self.assertEqual(verdict["pointer_source"], "PIPELINE.md")
        self.assertEqual(len(verdict["done_claims"]), 2)

    def test_early_workspace_with_null_pointer_passes(self):
        self.write_header("null", {"1": "done", "3": "in_progress"})
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["done_claims"], [])

    def test_handoff_declared_pointer_is_honored(self):
        rel = self.write_output()
        self.write_handoff({
            "completed_stage": "6",
            "next_stage": None,
            "canonical_output": rel,
        })
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["pointer_source"], ".pipeline/handoff.json")

    def test_done_after_threshold_is_parameterizable(self):
        self.write_header("null", {"3": "done"})
        verdict, code = check_canonical.check(self.ws, done_after=3.0)
        self.assertEqual(code, 3, verdict)

    # ── usage errors ─────────────────────────────────────────────────
    def test_missing_workspace_is_usage_error(self):
        verdict, code = check_canonical.check(self.ws / "nope")
        self.assertEqual(code, 2, verdict)

    def test_no_declarations_at_all_is_usage_error(self):
        verdict, code = check_canonical.check(self.ws)
        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])

    def test_helper_is_null_pointer_covers_rot_tokens(self):
        for token in (None, "", "null", "NULL", "~", "none"):
            self.assertTrue(check_canonical.is_null_pointer(token), token)
        self.assertFalse(check_canonical.is_null_pointer("output/out.hwpx"))


if __name__ == "__main__":
    unittest.main()
