"""Tests for verify_format.py — the recompute-based .hwpx format checker.

Synthetic fixtures ONLY: header.xml is hand-built with a plausible hancom
namespace (the parser is namespace-agnostic via local-name matching). No real
report output is ever read.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_format.py"
_spec = importlib.util.spec_from_file_location("verify_format", SCRIPT)
verify_format = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_format)

NS = "http://www.hancom.co.kr/hwpml/2011/head"


def _header(char_prs: str, para_prs: str = '<hh:paraPr id="0"><hh:lineSpacing type="PERCENT" value="160"/></hh:paraPr>') -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hh:head xmlns:hh="{NS}">'
        "<hh:refList>"
        f"<hh:charProperties>{char_prs}</hh:charProperties>"
        f"<hh:paraProperties>{para_prs}</hh:paraProperties>"
        "</hh:refList></hh:head>"
    )


class VerifyFormatTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "output").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_hwpx(self, header_xml: str):
        path = self.ws / "output" / "out.hwpx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Contents/header.xml", header_xml)
        return path


class TestPass(VerifyFormatTestCase):
    def test_body_height_and_line_spacing_pass(self):
        self.write_hwpx(_header(
            '<hh:charPr id="0" height="1000" textColor="#000000"/>'
            '<hh:charPr id="1" height="1400" textColor="#000000"/>'
        ))
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["measured"]["body_height_count"], 1)
        self.assertIn(160, verdict["measured"]["line_spacings"])


class TestHard(VerifyFormatTestCase):
    def test_no_body_height_is_hard_F1(self):
        self.write_hwpx(_header('<hh:charPr id="0" height="1200" textColor="#000000"/>'))
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "F1" for h in verdict["hard"]))

    def test_red_text_is_hard_F2(self):
        self.write_hwpx(_header(
            '<hh:charPr id="0" height="1000" textColor="#FF0000"/>'
        ))
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "F2" for h in verdict["hard"]))


class TestSkip(VerifyFormatTestCase):
    def test_missing_hwpx_is_skipped_exit_0(self):
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0)
        self.assertTrue(verdict["ok"])
        self.assertTrue(verdict.get("skipped"))


class TestExpect(VerifyFormatTestCase):
    def test_expect_json_overrides_default_height(self):
        # expect 11pt (height 1100); a 1000-only doc now fails F1.
        self.write_hwpx(_header('<hh:charPr id="0" height="1000" textColor="#000000"/>'))
        expect = self.ws / "expect.json"
        expect.write_text('{"base_pt": 11, "line_spacing": 160}', encoding="utf-8")
        verdict, code = verify_format.check(str(self.ws), expect_path=str(expect))
        self.assertEqual(code, 3)
        self.assertEqual(verdict["expected"]["height"], 1100)

    def test_build_yaml_supplies_expectations(self):
        self.write_hwpx(_header('<hh:charPr id="0" height="900" textColor="#000000"/>'))
        (self.ws / "build.yaml").write_text("base_pt: 9\nline_spacing: 160\n", encoding="utf-8")
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["expected"]["base_pt"], 9)


if __name__ == "__main__":
    unittest.main()
