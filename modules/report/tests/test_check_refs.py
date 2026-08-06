"""Synthetic tests for advisory figure/table numbering and xref lint."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_refs.py"
_spec = importlib.util.spec_from_file_location("check_refs", SCRIPT)
check_refs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_refs)


class CheckRefsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, text):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")
        return check_refs.check(str(self.ws))

    def test_tag_caption_numbers_define_figures_and_tables(self):
        verdict, code = self.run_check(
            "그림 1에서 첫 조건을 확인하고 [그림 2]와 (그림 3)을 비교한다.\n"
            "표 1에 결과를 정리한다.\n"
            '[[FIG file="one.png" caption="[그림 1] First result"]]\n'
            '[[FIG file="two.png" caption="그림 2. Second result"]]\n'
            '[[FIG file="three.png" caption="그림 3: Third result"]]\n'
            '[[TABLE cols=50,50 caption="표 1: Summary"]]\n'
            "| A | B |\n[[/TABLE]]\n"
        )
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["defined"]["figures"], [1, 2, 3])
        self.assertEqual(verdict["defined"]["tables"], [1])
        self.assertEqual(verdict["counts"]["cross_references"], 4)
        self.assertEqual(verdict["hard"], [])

    def test_figure_gap_and_duplicate_are_warn_only(self):
        verdict, code = self.run_check(
            '[[FIG file="one.png" caption="그림 1. First"]]\n'
            '[[FIG file="three-a.png" caption="그림 3. Third A"]]\n'
            '[[FIG file="three-b.png" caption="그림 3: Third B"]]\n'
        )
        self.assertEqual(code, 0, verdict)
        codes = {item["code"] for item in verdict["warn"]}
        self.assertIn("figure_numbering_gap", codes)
        self.assertIn("figure_numbering_duplicate", codes)
        self.assertEqual(verdict["hard"], [])

    def test_table_gap_and_duplicate_are_warn_only(self):
        verdict, code = self.run_check(
            '[[TABLE cols=50,50 caption="표 1. First"]]\n[[/TABLE]]\n'
            '[[TABLE cols=50,50 caption="표 3. Third"]]\n[[/TABLE]]\n'
            '[[TABLE cols=50,50 caption="표 3: Duplicate"]]\n[[/TABLE]]\n'
        )
        self.assertEqual(code, 0, verdict)
        codes = {item["code"] for item in verdict["warn"]}
        self.assertIn("table_numbering_gap", codes)
        self.assertIn("table_numbering_duplicate", codes)
        self.assertEqual(verdict["hard"], [])

    def test_undefined_body_reference_is_warn_only(self):
        verdict, code = self.run_check(
            "표 5에서 차이를 비교한다.\n"
            '[[TABLE cols=50,50 caption="표 1. First"]]\n'
            "| A | B |\n[[/TABLE]]\n"
        )
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item["code"] == "dangling_xref" and item["at"] == "표 5"
            for item in verdict["warn"]
        ))
        self.assertEqual(verdict["hard"], [])

    def test_decimal_and_counter_prose_are_not_references(self):
        verdict, code = self.run_check(
            "원주율은 표 3.14에 적고 표 1개와 그림 2장을 준비했다.\n"
            '[[TABLE cols=100 caption="표 1. Data"]]\n[[/TABLE]]\n'
            '[[FIG file="two.png" caption="그림 2. Plot"]]\n'
        )
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["cross_references"], 0)
        self.assertFalse(any(
            item["code"] == "dangling_xref" for item in verdict["warn"]
        ))

    def test_bracket_reference_forms_are_recognized(self):
        verdict, code = self.run_check("[그림 7]과 (표 8)을 비교한다.\n")
        self.assertEqual(code, 0, verdict)
        dangling = {(item["at"], item["line"]) for item in verdict["warn"]
                    if item["code"] == "dangling_xref"}
        self.assertEqual(dangling, {("그림 7", 1), ("표 8", 1)})
        self.assertEqual(verdict["counts"]["cross_references"], 2)

    def test_figure_source_list_is_excluded_but_next_section_is_scanned(self):
        verdict, code = self.run_check(
            "그림 1에서 결과를 확인한다.\n"
            '[[FIG file="one.png" caption="[그림 1] Synthetic result"]]\n'
            "# 그림 출처:\n"
            "\n"
            "그림 9에서 가져온 공개 예시 자료\n"
            "\n"
            "## 후속 논의\n"
            "그림 8에서 추가 결과를 확인한다.\n"
        )
        self.assertEqual(code, 0, verdict)
        dangling = {item["at"] for item in verdict["warn"]
                    if item["code"] == "dangling_xref"}
        self.assertEqual(dangling, {"그림 8"})
        self.assertEqual(verdict["counts"]["cross_references"], 2)

    def test_source_section_without_following_heading_does_not_blanket_to_eof(self):
        # A 그림-출처 marker with no trailing heading must not suppress every later
        # reference through EOF: the citation block ends at the blank line after
        # its content, so a later real reference is still scanned.
        verdict, code = self.run_check(
            "그림 1에서 결과를 확인한다.\n"
            '[[FIG file="one.png" caption="[그림 1] Synthetic result"]]\n'
            '[[FIG file="two.png" caption="[그림 2] Second"]]\n'
            "※ 그림 출처\n"
            "그림 1: 공개 예시 출처\n"
            "\n"
            "그림 2에서 후속 결과를 확인한다.\n"
        )
        self.assertEqual(code, 0, verdict)
        dangling = {item["at"] for item in verdict["warn"]
                    if item["code"] == "dangling_xref"}
        self.assertEqual(dangling, set())  # 그림 2 is defined + referenced, no dangling
        self.assertEqual(verdict["counts"]["cross_references"], 2)  # 그림 1 + 그림 2

    def test_empty_caption_is_tolerated_and_not_numbered(self):
        verdict, code = self.run_check(
            '[[FIG file="one.png" caption=""]]\n'
            '[[FIG file="two.png"]]\n'
        )
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["defined"]["figures"], [])
        self.assertEqual(verdict["build_tags"]["figures"], 2)
        self.assertEqual(verdict["hard"], [])

    def test_unreferenced_figure_is_warn_only(self):
        verdict, code = self.run_check(
            '[[FIG file="one.png" caption="그림 1. Synthetic result"]]\n'
        )
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertIn("unreferenced_figure",
                      {item["code"] for item in verdict["warn"]})

    def test_missing_content_is_usage_exit_2(self):
        verdict, code = check_refs.check(str(self.ws))
        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
