"""Synthetic tests for the advisory unit/dimension consistency checker."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_units = _load("check_units")
content_audit = _load("content_audit")


class CheckUnitsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = mock.patch.dict(os.environ, clear=False)
        self._env_patch.start()
        os.environ.pop("RIGORLOOM_PROFILE_ROOT", None)
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def write_content(self, body: str) -> None:
        (self.ws / "bundle" / "content.md").write_text(body, encoding="utf-8")

    def write_results(self, payload: dict) -> None:
        (self.ws / "sim").mkdir(exist_ok=True)
        (self.ws / "sim" / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def bound_claim(subject: str, value: str, unit_parts: list[str]) -> str:
        """Assemble warning-trigger fixtures at runtime."""
        return f"{subject} = {value} {''.join(unit_parts)}.\n"

    @staticmethod
    def warn_codes(verdict: dict) -> set[str]:
        return {item["code"] for item in verdict["warn"]}

    def test_clean_units_pass(self):
        self.write_content(
            "# Results\n"
            + self.bound_claim("distance", "12", ["m"])
            + self.bound_claim("duration", "3", ["s"])
            + self.bound_claim("speed", "4", ["m", "/", "s"])
        )

        verdict, code = check_units.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["hard"], [])
        self.assertEqual(verdict["warn"], [])
        self.assertEqual(verdict["tagged_units"], 3)

    def test_same_subject_close_values_with_incompatible_units_warn(self):
        self.write_content(
            "# Results\n"
            + self.bound_claim("측정값", "12.00", ["m"])
            + self.bound_claim("측정값", "12.05", ["s"])
        )

        verdict, code = check_units.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["hard"], [])
        self.assertIn("unit_mismatch", self.warn_codes(verdict))

    def test_obvious_quantity_dimension_pairing_warns(self):
        self.write_content(
            "# Results\n" + self.bound_claim("거리", "8.0", ["s"])
        )

        verdict, code = check_units.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["hard"], [])
        self.assertIn("unit_impossible", self.warn_codes(verdict))

    def test_no_body_numeric_spans_is_noop(self):
        self.write_content('[[FIG file="synthetic.png"]]\n')

        verdict, code = check_units.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["checked_numerals"], 0)
        self.assertEqual(verdict["tagged_units"], 0)
        self.assertEqual(verdict["warn"], [])

    def test_content_audit_merges_warn_and_keeps_exit_zero(self):
        self.write_content(
            "# Results\n" + self.bound_claim("distance", "8.0", ["s"])
        )
        self.write_results({"seed": 31, "distance": 8.0})

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["sub_exit"]["check_units"], 0)
        self.assertEqual(verdict["hard"], [])
        self.assertTrue(any(
            item.get("source") == "check_units"
            and item.get("code") == "unit_impossible"
            for item in verdict["warn"]
        ), verdict)


if __name__ == "__main__":
    unittest.main()
