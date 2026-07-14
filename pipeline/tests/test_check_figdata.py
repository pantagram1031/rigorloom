"""Tests for figure/data checksum integrity checking."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_figdata.py"
_spec = importlib.util.spec_from_file_location("check_figdata", SCRIPT)
check_figdata = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_figdata)


class CheckFigdataTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        self.figures = self.ws / "bundle" / "figures"
        self.figures.mkdir(parents=True)
        self.figure = self.figures / "plot.png"
        self.figure.write_bytes(b"\x89PNG\r\nsynthetic")
        (self.ws / "bundle" / "content.md").write_text(
            '[[FIG file="plot.png"]]\n', encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def digest(self) -> str:
        return hashlib.sha256(self.figure.read_bytes()).hexdigest()

    def test_matching_manifest_entry_passes(self):
        (self.figures / "figures_manifest.json").write_text(
            json.dumps({"plot.png": self.digest()}), encoding="utf-8"
        )

        verdict, code = check_figdata.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"], {"hard": 0, "warn": 0})

    def test_mismatching_sidecar_is_hard_figure_data_drift(self):
        self.figure.with_name("plot.png.sha256").write_text(
            "0" * 64 + "  plot.png\n", encoding="utf-8"
        )

        verdict, code = check_figdata.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "figure_data_drift" for item in verdict["hard"]
        ))

    def test_no_checksum_record_is_warn_figure_unverified(self):
        verdict, code = check_figdata.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "figure_unverified" for item in verdict["warn"]
        ))

    def test_missing_content_is_usage_exit_2(self):
        (self.ws / "bundle" / "content.md").unlink()

        verdict, code = check_figdata.check(self.ws)

        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])

    def test_missing_png_is_left_to_verify_content(self):
        self.figure.unlink()

        verdict, code = check_figdata.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"], {"hard": 0, "warn": 0})


if __name__ == "__main__":
    unittest.main()
