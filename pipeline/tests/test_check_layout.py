# -*- coding: utf-8 -*-
"""check_layout delegate: env resolution, pass-through, fail-closed."""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import check_layout  # noqa: E402

FAKE_PASS = (
    "import json,sys\n"
    "print(json.dumps({'ok': True, 'planned': 100}))\n"
    "sys.exit(0)\n"
)
FAKE_FAIL = (
    "import json,sys\n"
    "print(json.dumps({'ok': False, 'errors': ['over budget']}))\n"
    "sys.exit(1)\n"
)


class CheckLayoutTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "ws"
        (self.ws / "bundle").mkdir(parents=True)
        (self.ws / "bundle" / "layout_plan.json").write_text(
            json.dumps({"target_pages": [1, 2], "sections": []}),
            encoding="utf-8")
        (self.ws / "form_profile.json").write_text(
            json.dumps({"page_metrics": {"lines_per_page": 40}}),
            encoding="utf-8")
        self.delegate_dir = Path(self._tmp.name) / "hwp-master-scripts"
        self.delegate_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_delegate(self, body):
        (self.delegate_dir / "layout_plan_check.py").write_text(
            body, encoding="utf-8")

    def test_missing_env_is_usage_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HWP_MASTER_SCRIPTS", None)
            verdict, code = check_layout.check(str(self.ws))
        self.assertEqual(code, 2)
        self.assertIn("HWP_MASTER_SCRIPTS", verdict["error"])

    def test_missing_plan_is_usage_error(self):
        (self.ws / "bundle" / "layout_plan.json").unlink()
        verdict, code = check_layout.check(str(self.ws))
        self.assertEqual(code, 2)

    def test_delegate_pass_maps_to_exit_0(self):
        self._write_delegate(FAKE_PASS)
        with mock.patch.dict(
                os.environ, {"HWP_MASTER_SCRIPTS": str(self.delegate_dir)}):
            verdict, code = check_layout.check(str(self.ws))
        self.assertEqual(code, 0)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["delegate_exit"], 0)

    def test_delegate_fail_maps_to_hard_3(self):
        self._write_delegate(FAKE_FAIL)
        with mock.patch.dict(
                os.environ, {"HWP_MASTER_SCRIPTS": str(self.delegate_dir)}):
            verdict, code = check_layout.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertFalse(verdict["ok"])
        self.assertIn("over budget", verdict["delegate_stdout"])


if __name__ == "__main__":
    unittest.main()
