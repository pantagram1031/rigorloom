"""Tests for verify_content.py — the stage 4.5 content_audit checker.

Synthetic fixtures ONLY (never real report text). Exercises the HARD rules
(exit 3), a clean pass (exit 0), and the --allowlist merge over the neutral
builtin gloss set.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_content.py"

_spec = importlib.util.spec_from_file_location("verify_content", SCRIPT)
verify_content = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_content)


class VerifyContentTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle" / "figures").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_content(self, text: str):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")

    def add_figure(self, name: str):
        (self.ws / "bundle" / "figures" / name).write_bytes(b"\x89PNG\r\n")

    def check(self, allow=None):
        return verify_content.check(str(self.ws), allow_gloss=allow)


class TestPositive(VerifyContentTestCase):
    def test_clean_content_passes(self):
        self.add_figure("plot1.png")
        self.write_content(
            "# 서론\n"
            "이 글은 측정 결과를 정리한 기록이다. 여러 조건에서 값이 안정적으로 나타났다.\n"
            '[[FIG file="plot1.png"]]\n'
            "관측값은 표에 정리하였고 해석은 본문에서 다룬다.\n"
        )
        verdict, code = self.check()
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"]["hard"], 0)


class TestNegative(VerifyContentTestCase):
    def test_missing_content_md_is_usage_exit_2(self):
        verdict, code = self.check()
        self.assertEqual(code, 2)
        self.assertFalse(verdict["ok"])

    def test_planted_url_is_hard_H1(self):
        self.write_content(
            "본문에 링크가 섞여 있다 참고 https://example.com/data 를 보라.\n"
        )
        verdict, code = self.check()
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "H1" for h in verdict["hard"]))

    def test_planted_polite_ending_is_hard_H2(self):
        self.write_content("실험을 진행하였고 결과를 확인하였습니다.\n")
        verdict, code = self.check()
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "H2" for h in verdict["hard"]))

    def test_missing_fig_file_is_hard_H3(self):
        self.write_content(
            "그림을 참조한다.\n"
            '[[FIG file="missing.png"]]\n'
        )
        verdict, code = self.check()
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "H3" for h in verdict["hard"]))

    def test_multiple_hard_violations_reported_together(self):
        self.write_content(
            "링크 http://a.b/c 가 있고 확인하였습니다.\n"
            '[[FIG file="nope.png"]]\n'
        )
        verdict, code = self.check()
        self.assertEqual(code, 3)
        codes = {h["code"] for h in verdict["hard"]}
        self.assertEqual({"H1", "H2", "H3"}, codes)


class TestAllowlistMerge(VerifyContentTestCase):
    def test_gloss_warns_without_allowlist_then_clears_with_it(self):
        self.add_figure("f.png")
        # a Korean word immediately followed by a parenthesised Latin term not
        # in the neutral builtin -> W1 warn.
        self.write_content(
            "측정 장치(Fictronix)를 사용하였고 값이 안정적이었다.\n"
            '[[FIG file="f.png"]]\n'
        )
        verdict, code = self.check()
        self.assertEqual(code, 0, verdict)  # W1 is a WARN, never fails the gate
        self.assertTrue(any(w["code"] == "W1" for w in verdict["warn"]))

        verdict2, code2 = self.check(allow=["Fictronix"])
        self.assertEqual(code2, 0, verdict2)
        self.assertFalse(any(w["code"] == "W1" for w in verdict2["warn"]))

    def test_builtin_units_do_not_warn(self):
        self.add_figure("g.png")
        self.write_content(
            "신호(dB) 및 주파수(Hz)는 표준 단위로 기록하였다.\n"
            '[[FIG file="g.png"]]\n'
        )
        verdict, code = self.check()
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(w["code"] == "W1" for w in verdict["warn"]))

    def test_load_allowlist_reads_plain_and_yaml_list(self):
        p_plain = self.ws / "allow_plain.txt"
        p_plain.write_text("# comment\nAlpha\nBeta\n\n", encoding="utf-8")
        self.assertEqual(verify_content.load_allowlist(str(p_plain)), {"Alpha", "Beta"})

        p_yaml = self.ws / "allow.yaml"
        p_yaml.write_text('- "Gamma"\n- Delta\n', encoding="utf-8")
        self.assertEqual(verify_content.load_allowlist(str(p_yaml)), {"Gamma", "Delta"})


if __name__ == "__main__":
    unittest.main()
