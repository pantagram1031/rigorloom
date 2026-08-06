"""Tests for check_style.py — the prose/structure style checker.

Synthetic fixtures ONLY (never real report text; 홍길동-style fakes). Exercises
the default prose pack load, planted banned regex (HARD), signature over cap
(HARD), planted in-text parenthetical citation under a narrative structure pack
(HARD), and a clean pass (exit 0).
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_style.py"
_spec = importlib.util.spec_from_file_location("check_style", SCRIPT)
check_style = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_style)


class CheckStyleTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_content(self, text: str):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")

    def check(self, prose=None, structure=None):
        return check_style.check(str(self.ws), prose_pack=prose, structure_pack=structure)


class TestDefaultPack(unittest.TestCase):
    def test_default_prose_pack_loads(self):
        pack = check_style.personalization_ctl.load_pack_file(check_style.DEFAULT_PROSE_PACK)
        self.assertEqual(pack.get("pack_type"), "prose_rules")
        self.assertIn("banned_patterns", pack)


class TestPositive(CheckStyleTestCase):
    def test_clean_content_passes(self):
        default = check_style.personalization_ctl.load_pack_file(check_style.DEFAULT_PROSE_PACK)
        self.write_content(
            "# 서론\n"
            "이 기록은 홍길동이 관측한 값을 정리한 글이다. 여러 조건에서 결과가 안정적으로 나타났다.\n"
            "관측값은 표에 정리하였고 해석은 본문에서 이어서 다룬다.\n"
        )
        verdict, code = self.check(prose=default)
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"]["hard"], 0)

    def test_missing_content_md_is_usage_exit_2(self):
        verdict, code = self.check(prose={})
        self.assertEqual(code, 2)
        self.assertFalse(verdict["ok"])


class TestNegative(CheckStyleTestCase):
    def test_planted_banned_regex_is_hard(self):
        pack = {"schema": "x", "pack_type": "prose_rules", "name": "t", "version": 1,
                "banned_patterns": [{"id": "no-forbidden", "regex": "금칙어구", "severity": "hard"}]}
        self.write_content("본문에 금칙어구 가 섞여 있다.\n")
        verdict, code = self.check(prose=pack)
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "BAN:no-forbidden" for h in verdict["hard"]))

    def test_signature_over_cap_is_hard(self):
        pack = {"schema": "x", "pack_type": "prose_rules", "name": "t", "version": 1,
                "banned_patterns": [],
                "signature_phrases": [{"regex": "결국", "max_count": 1}]}
        self.write_content("결국 이렇게 되었고 결국 저렇게 되었다.\n")
        verdict, code = self.check(prose=pack)
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "SIG" for h in verdict["hard"]))

    def test_planted_parenthetical_citation_is_hard(self):
        structure = {"schema": "x", "pack_type": "report_structure", "name": "t", "version": 1,
                     "title_format": "An Inquiry into {topic}",
                     "citation_style": {"sources": "papers_books_only", "in_text": "narrative"}}
        self.write_content("선행 연구(김철수, 2020)는 이 현상을 다루었다.\n")
        verdict, code = self.check(prose={}, structure=structure)
        self.assertEqual(code, 3)
        self.assertTrue(any(h["code"] == "CITE" for h in verdict["hard"]))

    def test_narrative_citation_allowed_when_no_structure_pack(self):
        # without a structure pack the citation check is disabled.
        self.write_content("선행 연구(김철수, 2020)는 이 현상을 다루었다.\n")
        verdict, code = self.check(prose={}, structure=None)
        self.assertEqual(code, 0, verdict)


class TestGlossCalibration(CheckStyleTestCase):
    GLOSS_PACK = {
        "schema": "x",
        "pack_type": "prose_rules",
        "name": "synthetic-gloss-ban",
        "version": 1,
        "banned_patterns": [{
            "id": "gloss-english",
            "regex": r"[가-힣]+\([A-Za-z][A-Za-z0-9+.-]*\)",
            "severity": "hard",
            "description": "Synthetic parenthetical English gloss ban.",
        }],
    }

    def test_claim_unit_symbols_and_default_software_names_are_exempt(self):
        self.write_content(
            "거리(AU), 온도(K), 계산(SymPy)은 합법적인 전문 표기다.\n"
        )

        verdict, code = self.check(prose=self.GLOSS_PACK)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item["code"] == "BAN:gloss-english" for item in verdict["hard"]
        ), verdict)

    def test_operator_terms_extend_default_software_names(self):
        self.write_content("계산(SymPy)과 모형(TopicCalc)을 사용했다.\n")

        verdict, code = check_style.check(
            str(self.ws),
            prose_pack=self.GLOSS_PACK,
            allow_terms=["TopicCalc"],
        )

        self.assertEqual(code, 0, verdict)

    def test_unknown_gloss_still_triggers_hard_ban(self):
        self.write_content("계산(Fictronix)을 사용했다.\n")

        verdict, code = self.check(prose=self.GLOSS_PACK)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "BAN:gloss-english" for item in verdict["hard"]
        ), verdict)

    def test_count_word_alias_is_not_a_unit_symbol_exemption(self):
        self.write_content("분류(case)를 사용했다.\n")

        verdict, code = self.check(prose=self.GLOSS_PACK)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "BAN:gloss-english" for item in verdict["hard"]
        ), verdict)

    def test_public_software_term_does_not_exempt_other_ban_ids(self):
        pack = {
            "banned_patterns": [{
                "id": "synthetic-software-ban",
                "regex": "SymPy",
                "severity": "hard",
            }],
        }
        self.write_content("SymPy\n")

        verdict, code = self.check(prose=pack)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "BAN:synthetic-software-ban"
            for item in verdict["hard"]
        ), verdict)


class TestTitleMetadata(CheckStyleTestCase):
    STRUCTURE = {
        "schema": "x",
        "pack_type": "report_structure",
        "name": "synthetic-structure",
        "version": 1,
        "title_format": "An Inquiry into {topic}",
    }

    def test_activity_topic_metadata_without_declared_key_warns(self):
        self.write_content(
            "과목: Synthetic Physics\n"
            "활동주제: An Inquiry into Orbital Motion\n"
            "탐구방법: Synthetic comparison\n\n"
            "# 1. Introduction\n"
        )

        verdict, code = self.check(prose={}, structure=self.STRUCTURE)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(item["code"] == "TITLE" for item in verdict["warn"]))

    def test_pack_declared_activity_topic_metadata_is_used_as_title(self):
        self.write_content(
            "과목: Synthetic Physics\n"
            "활동주제: An Inquiry into Orbital Motion\n"
            "탐구방법: Synthetic comparison\n\n"
            "# 1. Introduction\n"
        )
        structure = {
            **self.STRUCTURE,
            "title_metadata_keys": ["활동주제"],
        }

        verdict, code = self.check(prose={}, structure=structure)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "TITLE" for item in verdict["warn"]))

    def test_pack_keys_extend_documented_title_metadata_defaults(self):
        self.write_content(
            "title: An Inquiry into Orbital Motion\n\n"
            "# 1. Introduction\n"
        )
        structure = {
            **self.STRUCTURE,
            "title_metadata_keys": ["활동주제"],
        }

        verdict, code = self.check(prose={}, structure=structure)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "TITLE" for item in verdict["warn"]))

    def test_mismatching_activity_topic_metadata_still_warns(self):
        self.write_content(
            "과목: Synthetic Physics\n"
            "활동주제: Unrelated label\n\n"
            "# 1. Introduction\n"
        )

        structure = {
            **self.STRUCTURE,
            "title_metadata_keys": ["활동주제"],
        }

        verdict, code = self.check(prose={}, structure=structure)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(item["code"] == "TITLE" for item in verdict["warn"]))


if __name__ == "__main__":
    unittest.main()
