"""Tests for verify_format.py — the recompute-based .hwpx format checker.

Synthetic fixtures ONLY: header.xml is hand-built with a plausible hancom
namespace (the parser is namespace-agnostic via local-name matching). No real
report output is ever read.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_format.py"
_spec = importlib.util.spec_from_file_location("verify_format", SCRIPT)
verify_format = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_format)

NS = "http://www.hancom.co.kr/hwpml/2011/head"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _header(char_prs: str, para_prs: str = '<hh:paraPr id="0"><hh:lineSpacing type="PERCENT" value="160"/></hh:paraPr>') -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hh:head xmlns:hh="{NS}">'
        "<hh:refList>"
        f"<hh:charProperties>{char_prs}</hh:charProperties>"
        f"<hh:paraProperties>{para_prs}</hh:paraProperties>"
        "</hh:refList></hh:head>"
    )


def _section(*, top: int = 5668, bottom: int = 4252, left: int = 8504,
             right: int = 8504, gutter: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hp:sec xmlns:hp="{SECTION_NS}"><hp:p><hp:run>'
        '<hp:secPr id="0"><hp:pagePr gutterType="LEFT_ONLY">'
        f'<hp:margin header="4252" footer="4252" gutter="{gutter}" '
        f'left="{left}" right="{right}" top="{top}" bottom="{bottom}"/>'
        '</hp:pagePr></hp:secPr></hp:run></hp:p></hp:sec>'
    )


class VerifyFormatTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "output").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_hwpx(self, header_xml: str, section_xml: str | None = None):
        path = self.ws / "output" / "out.hwpx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Contents/header.xml", header_xml)
            if section_xml is not None:
                z.writestr("Contents/section0.xml", section_xml)
        return path

    def write_pdf(self, pages: int):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        document = fitz.open()
        for _ in range(pages):
            document.new_page()
        document.save(self.ws / "output" / "out.pdf")
        document.close()


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

    def test_missing_expected_line_spacing_is_hard_F5(self):
        self.write_hwpx(_header(
            '<hh:charPr id="0" height="1000" textColor="#000000"/>',
            '<hh:paraPr id="0"><hh:lineSpacing type="PERCENT" value="180"/></hh:paraPr>',
        ))
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "F5" for h in verdict["hard"]))


class TestSkip(VerifyFormatTestCase):
    def test_missing_hwpx_is_skipped_exit_0(self):
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0)
        self.assertTrue(verdict["ok"])
        self.assertTrue(verdict.get("skipped"))

    def test_missing_hwpx_is_hard_when_output_is_required(self):
        verdict, code = verify_format.check(str(self.ws), require_output=True)

        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any(
            item["code"] == "output_missing" for item in verdict["hard"]
        ), verdict)


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


class TestMargins(VerifyFormatTestCase):
    def test_declared_correct_margins_pass(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        (self.ws / "build.yaml").write_text(
            "margins:\n"
            "  top: 5668\n"
            "  bottom: 4252\n"
            "  left: 8504\n"
            "  right: 8504\n"
            "  gutter: 0\n",
            encoding="utf-8",
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["measured"]["margins"][0]["top"], 5668)
        self.assertFalse(any(h["code"] == "F3" for h in verdict["hard"]))

    def test_declared_wrong_margin_is_hard_F3(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(left=8504),
        )
        (self.ws / "build.yaml").write_text(
            "margin_top: 5668\n"
            "margin_bottom: 4252\n"
            "margin_left: 9000\n"
            "margin_right: 8504\n",
            encoding="utf-8",
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3, verdict)
        finding = next(h for h in verdict["hard"] if h["code"] == "F3")
        self.assertIn("left", finding["msg"])

    def test_undeclared_margins_warn_with_measurements(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        warning = next(w for w in verdict["warn"] if w["code"] == "W4")
        self.assertIn("top=5668", warning["at"])

    def test_form_profile_margin_expectation_is_enforced(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(right=8504),
        )
        (self.ws / "form_profile.json").write_text(
            '{"page_metrics":{"margins":{"right":9000}}}',
            encoding="utf-8",
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3, verdict)
        finding = next(h for h in verdict["hard"] if h["code"] == "F3")
        self.assertIn("right", finding["msg"])
        self.assertEqual(verdict["expected"]["margin_source"], "form_profile.json")


class TestGradedExpectations(VerifyFormatTestCase):
    def test_missing_margins_and_page_bounds_are_named_warnings(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        (self.ws / "build.yaml").write_text(
            "submission_grade: graded\n", encoding="utf-8"
        )

        verdict, code = verify_format.check(str(self.ws))

        self.assertEqual(code, 0, verdict)
        warnings = {item["code"]: item["msg"] for item in verdict["warn"]}
        self.assertEqual(
            warnings["margin_expectation_unverifiable"],
            "graded build margins are unverifiable: neither build.yaml nor "
            "form_profile.json declares margins",
        )
        self.assertEqual(
            warnings["page_bounds_unverifiable"],
            "graded build page bounds are unverifiable: neither build.yaml nor "
            "form_profile.json declares page bounds",
        )


class TestPageCount(VerifyFormatTestCase):
    def test_page_count_outside_declared_bounds_is_hard_F4(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        self.write_pdf(2)
        (self.ws / "build.yaml").write_text(
            "min_pages: 3\nmax_pages: 5\n",
            encoding="utf-8",
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3, verdict)
        finding = next(h for h in verdict["hard"] if h["code"] == "F4")
        self.assertIn("2", finding["msg"])

    def test_target_pages_with_tolerance_accepts_in_range_pdf(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        self.write_pdf(4)
        (self.ws / "request.yaml").write_text(
            "target_pages: 3\npage_tolerance: 1\n",
            encoding="utf-8",
        )
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["measured"]["page_count"], 4)
        self.assertEqual(verdict["expected"]["page_bounds"]["max"], 4)

    def test_declared_bounds_without_pdf_are_hard(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        (self.ws / "build.yaml").write_text("min_pages: 3\n", encoding="utf-8")
        verdict, code = verify_format.check(str(self.ws))
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "page_count_unverifiable" for item in verdict["hard"]
        ), verdict)

    def test_declared_bounds_without_pymupdf_are_hard(self):
        self.write_hwpx(
            _header('<hh:charPr id="0" height="1000" textColor="#000000"/>'),
            _section(),
        )
        (self.ws / "output" / "out.pdf").write_bytes(b"synthetic-pdf")
        (self.ws / "build.yaml").write_text("min_pages: 3\n", encoding="utf-8")

        with mock.patch.dict(sys.modules, {"fitz": None}):
            verdict, code = verify_format.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "page_count_unverifiable" for item in verdict["hard"]
        ), verdict)


if __name__ == "__main__":
    unittest.main()
