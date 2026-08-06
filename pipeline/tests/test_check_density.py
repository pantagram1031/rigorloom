# -*- coding: utf-8 -*-
"""Tests for the H5 bold-subhead density gate."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_density.py"
_spec = importlib.util.spec_from_file_location("check_density", SCRIPT)
check_density = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_density)


def synthetic_content(subheads: int, total_bytes: int,
                      subhead_texts: list[str] | None = None) -> str:
    """Build content.md-shaped text with an exact UTF-8 byte length.

    The gate's denominator is UTF-8 bytes (matching the corpus calibration
    on file size), so the fixture pads with ASCII filler where one char is
    exactly one byte, letting tests hit the byte count exactly.
    """
    lines = ["## SECTION: I.  서론", ""]
    for index in range(subheads):
        if subhead_texts and index < len(subhead_texts):
            lines.append(f"**{subhead_texts[index]}**")
        else:
            lines.append(f"**소제목 {index + 1}**")
        lines.append("")
    text = "\n".join(lines) + "\n"
    base_bytes = len(text.encode("utf-8"))
    pad = total_bytes - base_bytes
    assert pad >= 0, "fixture too small for its subhead block"
    filler = ("x" * 79 + "\n") * (pad // 80 + 1)
    text += filler[:pad]
    assert len(text.encode("utf-8")) == total_bytes
    return text


class CheckDensityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, text, **kwargs):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")
        return check_density.check(str(self.ws), **kwargs)

    # ── still-catches: windpath pre-fix density class ───────────────
    def test_still_catches_prefix_density_is_hard(self):
        # windpath pre-fix was ~18 subheads / ~40k bytes = 4.5/10k. The bound
        # is inclusive, so the calibration point itself must be HARD.
        verdict, code = self.run_check(synthetic_content(18, 36000))
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any(
            item["code"] == "subhead_density_hard" for item in verdict["hard"]
        ), verdict)
        self.assertGreaterEqual(verdict["density_per_10k"], 4.5)

    def test_exact_hard_boundary_is_hard(self):
        # 18 subheads in exactly 40000 bytes = 4.5/10k → inclusive HARD.
        verdict, code = self.run_check(synthetic_content(18, 40000))
        self.assertEqual(code, 3, verdict)

    def test_postfix_density_passes_clean(self):
        # windpath post-fix: 6 subheads / 40k bytes = 1.5/10k.
        verdict, code = self.run_check(synthetic_content(6, 40000))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["hard"], [])
        self.assertEqual(verdict["warn"], [])

    def test_hawkes_class_density_passes(self):
        # hawkes: 10 subheads / 56k bytes = 1.8/10k — acceptable.
        verdict, code = self.run_check(synthetic_content(10, 56000))
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["hard"], [])

    def test_warn_band_is_warn_only(self):
        # 13 subheads / 40k bytes = 3.25/10k — above WARN, below HARD.
        verdict, code = self.run_check(synthetic_content(13, 40000))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertTrue(any(
            item["code"] == "subhead_density_warn" for item in verdict["warn"]
        ), verdict)
        self.assertEqual(verdict["hard"], [])

    # ── what counts as a subhead ─────────────────────────────────────
    def test_section_headings_do_not_count(self):
        text = (
            "## SECTION: I.  서론\n\n" + ("가나다라마바사아자차" * 8 + "\n") * 20
            + "## SECTION: II.  이론적 배경\n\n"
            + ("가나다라마바사아자차" * 8 + "\n") * 20
        )
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["subheads"], 0)

    def test_deep_headings_count_as_subheads(self):
        text = "### 깊은 소제목\n\n#### 더 깊은 소제목\n\n본문.\n"
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")
        verdict, _ = check_density.check(
            str(self.ws), warn_per_10k=1000.0, hard_per_10k=1000.0
        )
        self.assertEqual(verdict["counts"]["subheads"], 2)

    def test_inline_bold_is_not_a_subhead(self):
        text = "본문 중간의 **강조 표현**은 소제목이 아니다.\n" * 5
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["counts"]["subheads"], 0)

    # ── guide-label echo ─────────────────────────────────────────────
    def test_guide_label_echo_bold_lines_warn(self):
        text = synthetic_content(
            3, 40000,
            subhead_texts=["결과 요약", "결과의 의미", "한계 및 제언"],
        )
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        echoes = [item for item in verdict["warn"]
                  if item["code"] == "guide_label_echo"]
        self.assertEqual({item["at"] for item in echoes},
                         {"결과 요약", "결과의 의미", "한계 및 제언"})
        # density 3/40k = 0.75 → echo findings must not depend on density
        self.assertEqual(verdict["hard"], [])

    def test_original_subhead_names_do_not_warn_as_echo(self):
        text = synthetic_content(
            2, 40000, subhead_texts=["가중 그래프와 최단경로", "검증 설계의 배경"],
        )
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "guide_label_echo" for item in verdict["warn"]
        ), verdict)

    # ── parameters and usage errors ──────────────────────────────────
    def test_thresholds_are_parameterizable(self):
        text = synthetic_content(6, 40000)  # 1.5/10k
        verdict, code = self.run_check(
            text, warn_per_10k=1.0, hard_per_10k=1.4
        )
        self.assertEqual(code, 3, verdict)

    def test_invalid_threshold_order_is_usage_error(self):
        verdict, code = self.run_check(
            synthetic_content(6, 40000), warn_per_10k=5.0, hard_per_10k=4.0
        )
        self.assertEqual(code, 2, verdict)

    def test_missing_content_is_usage_error(self):
        verdict, code = check_density.check(str(self.ws))
        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])

    def test_empty_content_is_usage_error(self):
        verdict, code = self.run_check("")
        self.assertEqual(code, 2, verdict)


if __name__ == "__main__":
    unittest.main()
