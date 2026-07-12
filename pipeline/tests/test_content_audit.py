"""Tests for content_audit.py — the composite stage 4.5 gate.

Runs the REAL sub-checker chain (verify_content.py + check_style.py) against a
synthetic workspace. Synthetic fixtures ONLY (홍길동-style fakes).
  - clean bundle/content.md            -> exit 0
  - planted '습니다' polite ending     -> exit 3 (via verify_content path)
  - planted '(김철수, 2020)' citation  -> exit 3 (via check_style path, with a
                                          narrative report_structure pack)
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "content_audit.py"
_spec = importlib.util.spec_from_file_location("content_audit", SCRIPT)
content_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(content_audit)


class ContentAuditTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle" / "figures").mkdir(parents=True, exist_ok=True)
        (self.ws / "bundle" / "figures" / "plot.png").write_bytes(b"\x89PNG\r\n")

    def tearDown(self):
        self._tmp.cleanup()

    def write_content(self, text: str):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")

    def make_profile_root_with_structure(self) -> Path:
        root = Path(self._tmp.name) / "profile"
        packs = root / "packs"
        packs.mkdir(parents=True, exist_ok=True)
        structure = {"schema": "x", "pack_type": "report_structure", "name": "t", "version": 1,
                     "title_format": "An Inquiry into {topic}",
                     "citation_style": {"sources": "papers_books_only", "in_text": "narrative"}}
        (packs / "report_structure.json").write_text(
            json.dumps(structure, ensure_ascii=False), encoding="utf-8")
        return root

    def _clean_body(self) -> str:
        return (
            "# 서론\n"
            "이 기록은 홍길동이 측정한 값을 정리한 글이다. 여러 조건에서 값이 안정적으로 나타났다.\n"
            '[[FIG file="plot.png"]]\n'
            "관측값은 표에 정리하였고 해석은 본문에서 이어서 다룬다.\n"
        )


class TestClean(ContentAuditTestCase):
    def test_clean_passes(self):
        self.write_content(self._clean_body())
        verdict, code = content_audit.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"]["hard"], 0)


class TestPoliteEnding(ContentAuditTestCase):
    def test_polite_ending_fails_via_verify_content(self):
        self.write_content(
            "# 서론\n실험을 진행하였고 결과를 확인하였습니다.\n"
            '[[FIG file="plot.png"]]\n'
        )
        verdict, code = content_audit.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertTrue(any(h.get("source") == "verify_content" and h.get("code") == "H2"
                            for h in verdict["hard"]))


class TestCitation(ContentAuditTestCase):
    def test_parenthetical_citation_fails_via_check_style(self):
        self.write_content(
            "# 서론\n선행 연구(김철수, 2020)는 이 현상을 다루었다.\n"
            '[[FIG file="plot.png"]]\n'
        )
        root = self.make_profile_root_with_structure()
        verdict, code = content_audit.check(str(self.ws), profile_root=str(root))
        self.assertEqual(code, 3)
        self.assertTrue(any(h.get("source") == "check_style" and h.get("code") == "CITE"
                            for h in verdict["hard"]))


class TestUsage(ContentAuditTestCase):
    def test_missing_content_md_is_nonzero(self):
        # no bundle/content.md -> both sub-checkers usage-error -> nonzero.
        verdict, code = content_audit.check(str(self.ws))
        self.assertNotEqual(code, 0)
        self.assertFalse(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
