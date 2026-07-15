"""Synthetic tests for deterministic offline citation-reality checking."""
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


check_sources = _load("check_sources")
content_audit = _load("content_audit")


class CheckSourcesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = mock.patch.dict(os.environ, clear=False)
        self._env_patch.start()
        os.environ.pop("RIGORLOOM_PROFILE_ROOT", None)
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)
        self.profile = Path(self._tmp.name) / "profile"

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def write_content(self, body: str) -> None:
        (self.ws / "bundle" / "content.md").write_text(body, encoding="utf-8")

    def reference(self, title: str, year: int, identifier: str) -> str:
        return (
            "# References\n\n"
            f"- Synthetic Author ({year}). {title}. Journal of Examples. "
            f"{identifier}\n"
        )

    def write_doi_cache(self, doi: str, title: str) -> None:
        target = (
            self.profile / "cache" / "sources" / "doi"
            / f"{check_sources._doi_slug(doi)}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"doi": doi, "title": title}),
            encoding="utf-8",
        )

    def hard_codes(self, verdict):
        return {item["code"] for item in verdict["hard"]}

    def warn_codes(self, verdict):
        return {item["code"] for item in verdict["warn"]}

    def test_malformed_doi_is_hard(self):
        malformed = "DOI: 10." + "12/broken"
        self.write_content(self.reference("Synthetic Citation", 2024, malformed))

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_doi_malformed", self.hard_codes(verdict))

    def test_bad_isbn_checksum_is_hard(self):
        bad_isbn = "ISBN: " + "978" + "0306406158"
        self.write_content(self.reference("Synthetic Book", 2024, bad_isbn))

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_isbn_checksum", self.hard_codes(verdict))

    def test_future_year_is_hard(self):
        doi = "DOI: 10." + "1234/future-study"
        self.write_content(self.reference("Future Study", 2031, doi))

        verdict, code = check_sources.check(self.ws, now=2030)

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_year_future", self.hard_codes(verdict))

    def test_cache_title_mismatch_is_hard(self):
        doi = "10." + "1234/synthetic-source"
        self.write_content(
            self.reference("Study of Synthetic Cats", 2024, f"DOI: {doi}")
        )
        self.write_doi_cache(doi, "Study of Synthetic Dogs")

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_title_mismatch", self.hard_codes(verdict))

    def test_cache_miss_is_warn_only(self):
        doi = "10." + "1234/missing-source"
        self.write_content(
            self.reference("Uncached Synthetic Study", 2024, f"DOI: {doi}")
        )

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertIn("source_unverified", self.warn_codes(verdict))

    def test_matching_cache_is_clean_pass_and_fields_are_structured(self):
        doi = "10." + "1234/verified-source"
        title = "Reliable Synthetic Evidence"
        self.write_content(self.reference(title, 2024, f"DOI: {doi}"))
        self.write_doi_cache(doi, title.lower())

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"], {"hard": 0, "warn": 0, "entries": 1})
        entry = verdict["entries"][0]
        self.assertEqual(entry["author"], "Synthetic Author")
        self.assertEqual(entry["year"], 2024)
        self.assertEqual(entry["title"], title)
        self.assertEqual(entry["container"], "Journal of Examples")
        self.assertEqual(entry["doi"], doi)

    def test_no_reference_section_is_clean_pass(self):
        self.write_content("# Results\nSynthetic body without endnotes.\n")

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["entries"], [])
        self.assertEqual(verdict["counts"], {"hard": 0, "warn": 0, "entries": 0})

    def test_content_audit_merges_check_sources_finding_and_exit(self):
        malformed = "DOI: 10." + "12/composed-break"
        self.write_content(self.reference("Composed Citation", 2024, malformed))

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["sub_exit"]["check_sources"], 3)
        self.assertTrue(any(
            item.get("source") == "check_sources"
            and item.get("code") == "source_doi_malformed"
            for item in verdict["hard"]
        ), verdict)


if __name__ == "__main__":
    unittest.main()
