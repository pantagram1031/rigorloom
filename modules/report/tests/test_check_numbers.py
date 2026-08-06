"""Synthetic tests for the Stage 4.5 numeric-provenance checker."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_numbers.py"
_spec = importlib.util.spec_from_file_location("check_numbers", SCRIPT)
check_numbers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_numbers)


class CheckNumbersTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)
        (self.ws / "sim").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_content(self, text: str) -> None:
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")

    def write_results(self, payload) -> None:
        (self.ws / "sim" / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def write_backed_claim(
        self,
        text: str,
        *,
        evidence: bool = True,
        resolvable: bool = True,
    ) -> None:
        (self.ws / "research").mkdir(exist_ok=True)
        source_id = "synthetic-source"
        (self.ws / "research" / "sources.json").write_text(
            json.dumps(
                [{"id": source_id, "title": "Synthetic evidence"}]
                if resolvable else []
            ),
            encoding="utf-8",
        )
        evidence_items = ([{
            "source_id": source_id,
            "locator": "section 1",
            "quote": "Synthetic numeric support.",
        }] if evidence else [])
        (self.ws / "claims.yaml").write_text(json.dumps({
            "schema": "rigorloom-claims/v1",
            "claims": [{
                "id": "synthetic-numeric-claim",
                "text": text,
                "kind": "numeric",
                "evidence": evidence_items,
            }],
        }), encoding="utf-8")


class TestNumericProvenance(CheckNumbersTestCase):
    def test_body_numeral_present_in_results_passes(self):
        self.write_content("# Result\nThe measured level was 12.345 dB.\n")
        self.write_results({"seed": 17, "metrics": {"level_db": 12.345}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["hard"], 0)
        self.assertEqual(verdict["checked_numerals"], 1)

    def test_environment_profile_allowlist_is_used_by_cli(self):
        self.write_content("# Result\nThe measured level was 98.765 dB.\n")
        self.write_results({"seed": 17, "metrics": {"level_db": 12.345}})
        root = Path(self._tmp.name) / "profile"
        (root / "packs").mkdir(parents=True)
        (root / "packs" / "numeral_allowlist.txt").write_text(
            "98.765\n", encoding="utf-8"
        )
        env = dict(
            os.environ,
            RIGORLOOM_PROFILE_ROOT=str(root),
            PYTHONIOENCODING="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--require-seed", str(self.ws)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        verdict = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0, verdict)
        self.assertFalse(any(
            item["code"] == "unbacked_numeral"
            for item in verdict["hard"] + verdict["warn"]
        ), verdict)

    def test_environment_constants_pack_is_used_by_cli(self):
        self.write_content("# Result\nThe calibration value was 98.765 dB.\n")
        self.write_results({"seed": 17, "metrics": {"level_db": 12.345}})
        root = Path(self._tmp.name) / "profile-constants"
        (root / "packs").mkdir(parents=True)
        (root / "packs" / "constants_allowlist.json").write_text(
            json.dumps([{
                "value": 98.765,
                "unit": "dB",
                "label": "synthetic calibration constant",
            }]),
            encoding="utf-8",
        )
        env = dict(
            os.environ,
            RIGORLOOM_PROFILE_ROOT=str(root),
            PYTHONIOENCODING="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--require-seed", str(self.ws)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        verdict = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0, verdict)
        self.assertFalse(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_explicit_allowlist_precedes_environment_profile(self):
        self.write_content("# Result\nThe measured level was 98.765 dB.\n")
        self.write_results({"seed": 17, "metrics": {"level_db": 12.345}})
        root = Path(self._tmp.name) / "profile-explicit"
        (root / "packs").mkdir(parents=True)
        (root / "packs" / "numeral_allowlist.txt").write_text(
            "98.765\n", encoding="utf-8"
        )
        explicit = Path(self._tmp.name) / "explicit-allowlist.txt"
        explicit.write_text("12.345\n", encoding="utf-8")
        env = dict(
            os.environ,
            RIGORLOOM_PROFILE_ROOT=str(root),
            PYTHONIOENCODING="utf-8",
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--require-seed",
                "--allow",
                str(explicit),
                str(self.ws),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        verdict = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0, verdict)
        self.assertTrue(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_body_numeral_absent_from_results_is_warn(self):
        self.write_content("# Result\nThe measured level was 98.765 dB.\n")
        self.write_results({"seed": 17, "metrics": {"level_db": 12.345}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ))

    def test_evidenced_resolvable_ledger_claim_backs_matching_numeral(self):
        line = "The reference acceleration was 12.345 m/s^2."
        self.write_content(f"# Result\n{line}\n")
        self.write_results({"seed": 17, "other_value": 4.5})
        self.write_backed_claim(line)

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_unevidenced_ledger_claim_does_not_back_matching_numeral(self):
        line = "The reference acceleration was 12.345 m/s^2."
        self.write_content(f"# Result\n{line}\n")
        self.write_results({"seed": 17, "other_value": 4.5})
        self.write_backed_claim(line, evidence=False)

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_unresolvable_ledger_source_does_not_back_matching_numeral(self):
        line = "The reference acceleration was 12.345 m/s^2."
        self.write_content(f"# Result\n{line}\n")
        self.write_results({"seed": 17, "other_value": 4.5})
        self.write_backed_claim(line, resolvable=False)

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_public_constant_with_matching_unit_is_exempt(self):
        self.write_content("# Method\nReference gravity was 9.81 m/s^2.\n")
        self.write_results({"seed": 17, "other_value": 4.5})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_public_constant_value_with_wrong_unit_still_warns(self):
        self.write_content("# Result\nThe synthetic level was 9.81 dB.\n")
        self.write_results({"seed": 17, "other_value": 4.5})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "unbacked_numeral" for item in verdict["warn"]
        ), verdict)

    def test_year_and_allowlisted_count_pass(self):
        self.write_content("# Method\nIn 2024, 12 trials used a duration of 3.25 ms.\n")
        self.write_results({"seed": 4, "duration_ms": 3.25})

        verdict, code = check_numbers.check(
            str(self.ws), require_seed=True, allowed_numbers={12.0}
        )

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["hard"], 0)
        self.assertEqual(verdict["checked_numerals"], 1)


class TestSeedProvenance(CheckNumbersTestCase):
    def test_invalid_top_level_seed_precedes_nested_numeric_seed(self):
        self.write_content("# Result\nThe qualitative result was recorded.\n")
        self.write_results({"seed": "invalid", "run": {"seed": 42}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "invalid_seed" for item in verdict["hard"]
        ), verdict)

    def test_valid_top_level_seed_ignores_nested_invalid_seed(self):
        # Only the top-level RNG seed is authoritative; a nested "seed" string is
        # unrelated metadata and must not fail a run whose top-level seed is numeric.
        self.write_content("# Result\nThe qualitative result was recorded.\n")
        self.write_results({"seed": 42, "run": {"seed": "invalid"}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "invalid_seed" for item in verdict.get("hard", [])
        ), verdict)

    def test_numeric_top_level_seed_passes(self):
        self.write_content("# Result\nThe qualitative result was recorded.\n")
        self.write_results({"seed": 42})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["hard"], 0)
    def test_missing_seed_on_ambiguous_populated_results_is_warn(self):
        self.write_content("# Result\nThe qualitative result was recorded.\n")
        self.write_results({"metrics": {"passed": True}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "missing_seed" for item in verdict["warn"]
        ))

    def test_missing_seed_on_canonical_numeric_results_is_hard(self):
        self.write_content("# Result\nThe measured level was 12.345 dB.\n")
        self.write_results({"metrics": {"level_db": 12.345}})

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "missing_seed" for item in verdict["hard"]
        ))

    def test_seed_may_be_recorded_in_sim_provenance(self):
        self.write_content("# Result\nThe qualitative result was recorded.\n")
        self.write_results({"metrics": {"passed": True}})
        (self.ws / "sim" / "provenance.json").write_text(
            json.dumps({"run": {"seed": 0}}), encoding="utf-8"
        )

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)

    def test_legacy_workspace_without_results_gets_advisory(self):
        self.write_content("# Result\nThe qualitative result was recorded.\n")

        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(w["code"] == "seed_not_recorded_legacy" for w in verdict["warn"]))


class TestUsage(CheckNumbersTestCase):
    def test_non_finite_body_number_is_dropped_and_cli_emits_strict_json(self):
        overflow = "1e" + "309"
        self.write_content(f"# Result\nOverflow = {overflow} ms.\n")
        self.write_results({"seed": 1, "value": 1.0})

        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.ws)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("Infinity", proc.stdout)
        self.assertNotIn("NaN", proc.stdout)
        verdict = json.loads(proc.stdout)
        self.assertEqual(verdict["checked_numerals"], 0)

    def test_empty_workspace_is_graceful_usage_error(self):
        verdict, code = check_numbers.check(str(self.ws), require_seed=True)

        self.assertEqual(code, 2)
        self.assertFalse(verdict["ok"])
        self.assertIn("error", verdict)


if __name__ == "__main__":
    unittest.main()
