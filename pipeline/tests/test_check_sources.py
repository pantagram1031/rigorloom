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

    def write_doi_cache(
        self, doi: str, title: str, *, verified: bool = True,
    ) -> None:
        target = (
            self.profile / "cache" / "sources" / "doi"
            / f"{check_sources._doi_slug(doi)}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        verification = None
        if verified:
            verification = {
                "retrieved_from": "https://example.invalid/source",
                "content_sha256": "a" * 64,
                "retrieved_at": "2026-07-17T01:02:03+00:00",
            }
        target.write_text(json.dumps({
            "doi": doi, "title": title, "verification": verification,
        }), encoding="utf-8")

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

    def test_partial_overlap_cache_title_mismatch_is_warn(self):
        doi = "10." + "1234/synthetic-source"
        self.write_content(
            self.reference("Study of Synthetic Cats", 2024, f"DOI: {doi}")
        )
        self.write_doi_cache(doi, "Study of Synthetic Dogs")

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 0, verdict)
        self.assertNotIn("source_title_mismatch", self.hard_codes(verdict))
        self.assertIn("source_title_suspect", self.warn_codes(verdict))

    def test_zero_overlap_cache_title_mismatch_is_hard(self):
        doi = "10." + "1234/different-work"
        self.write_content(
            self.reference("Solar Flare Measurements", 2024, f"DOI: {doi}")
        )
        self.write_doi_cache(doi, "Deep Ocean Microbiology")

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_title_mismatch", self.hard_codes(verdict))

    def test_unverified_cache_title_contradiction_is_still_hard(self):
        doi = "10." + "1234/self-authored-contradiction"
        self.write_content(
            self.reference("Solar Flare Measurements", 2024, f"DOI: {doi}")
        )
        self.write_doi_cache(doi, "Deep Ocean Microbiology", verified=False)

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 3, verdict)
        self.assertIn("source_title_mismatch", self.hard_codes(verdict))
        self.assertIn("source_selfauthored", self.warn_codes(verdict))
        self.assertIn("source_unverified", self.warn_codes(verdict))

    def test_cache_miss_is_warn_only(self):
        doi = "10." + "1234/missing-source"
        self.write_content(
            self.reference("Uncached Synthetic Study", 2024, f"DOI: {doi}")
        )

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertIn("source_unverified", self.warn_codes(verdict))
        self.assertEqual(verdict["counts"]["unverified"], 1)

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
        self.assertTrue(verdict["section_found"])
        self.assertEqual(
            verdict["counts"],
            {"hard": 0, "warn": 0, "unverified": 0, "entries": 1},
        )
        entry = verdict["entries"][0]
        self.assertEqual(entry["author"], "Synthetic Author")
        self.assertEqual(entry["year"], 2024)
        self.assertEqual(entry["title"], title)
        self.assertEqual(entry["container"], "Journal of Examples")
        self.assertEqual(entry["doi"], doi)

    def test_matching_cache_without_verification_metadata_stays_unverified(self):
        doi = "10." + "1234/self-authored-source"
        title = "Self Authored Synthetic Evidence"
        self.write_content(self.reference(title, 2024, f"DOI: {doi}"))
        self.write_doi_cache(doi, title, verified=False)

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 0, verdict)
        self.assertIn("source_selfauthored", self.warn_codes(verdict))
        self.assertIn("source_unverified", self.warn_codes(verdict))
        self.assertEqual(verdict["counts"]["unverified"], 1)

    def test_no_reference_section_is_clean_pass(self):
        self.write_content("# Results\nSynthetic body without endnotes.\n")

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(verdict["section_found"])
        self.assertEqual(verdict["entries"], [])
        self.assertEqual(
            verdict["counts"],
            {"hard": 0, "warn": 0, "unverified": 0, "entries": 0},
        )

    def test_recognized_reference_heading_variants_parse_entries(self):
        headings = (
            "참고문헌",
            "참고 문헌",
            "출처",
            "인용 문헌",
            "Reference List",
            "Literature Cited",
            "References and Notes",
            "7. 참고문헌",
            "SECTION: VI. 참고문헌",
            "SECTION: Ⅵ. 참고 문헌",
        )
        doi = "10." + "1234/heading-variant"
        for heading in headings:
            with self.subTest(heading=heading):
                self.write_content(
                    f"## {heading}\n\n"
                    f"- Doe (2024). Heading Variant Evidence. Journal. DOI: {doi}\n"
                )

                verdict, code = check_sources.check(self.ws)

                self.assertEqual(code, 0, verdict)
                self.assertTrue(verdict["section_found"])
                self.assertEqual(verdict["counts"]["entries"], 1)

    def test_citation_like_lines_without_recognized_section_warn_unparsed(self):
        doi = "10." + "1234/unparsed-heading"
        citation = "- Doe (" + "2024" + "). Hidden Entry. DOI: " + doi
        self.write_content("## Research Citations\n\n" + citation + "\n")

        verdict, code = check_sources.check(self.ws)

        self.assertEqual(code, 0, verdict)
        self.assertFalse(verdict["section_found"])
        self.assertEqual(verdict["counts"]["entries"], 0)
        self.assertIn("references_unparsed", self.warn_codes(verdict))

    def test_blank_lines_inside_reference_section_do_not_hide_later_entries(self):
        real_doi = "10." + "1234/real"
        malformed_doi = "10." + "12/bad"
        self.write_content(
            "# References\n\n"
            f"- Real (2024). Real First. Journal. DOI: {real_doi}\n\n"
            f"- Fake (2031). Fabricated Second. Journal. DOI: {malformed_doi}\n"
        )

        verdict, code = check_sources.check(self.ws, now=2030)

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["counts"]["entries"], 2)
        self.assertIn("source_year_future", self.hard_codes(verdict))
        self.assertIn("source_doi_malformed", self.hard_codes(verdict))

    def test_generic_and_reordered_titles_are_suspect_not_matches(self):
        cases = (
            ("Study", "A Completely Different Study of Frogs"),
            ("Effect of A on B", "Effect of B on A"),
        )
        for index, (cited, cached) in enumerate(cases):
            with self.subTest(cited=cited, cached=cached):
                doi = "10." + f"1234/title-case-{index}"
                self.write_content(self.reference(cited, 2024, f"DOI: {doi}"))
                self.write_doi_cache(doi, cached)

                verdict, code = check_sources.check(
                    self.ws, profile_root=self.profile
                )

                self.assertEqual(code, 0, verdict)
                self.assertNotIn(
                    "source_title_mismatch", self.hard_codes(verdict)
                )
                self.assertIn("source_title_suspect", self.warn_codes(verdict))

    def test_malformed_cache_warns_and_remaining_entries_are_checked(self):
        malformed_doi = "10." + "1234/malformed-cache"
        other_doi = "10." + "1234/other-cache"
        self.write_content(
            "# References\n\n"
            f"- Doe (2024). Broken Cache Entry. Journal. DOI: {malformed_doi}\n"
            f"- Roe (2024). Solar Flare Measurements. Journal. DOI: {other_doi}\n"
        )
        malformed_target = (
            self.profile / "cache" / "sources" / "doi"
            / f"{check_sources._doi_slug(malformed_doi)}.json"
        )
        malformed_target.parent.mkdir(parents=True, exist_ok=True)
        malformed_target.write_text("{not json", encoding="utf-8")
        self.write_doi_cache(other_doi, "Deep Ocean Microbiology")

        verdict, code = check_sources.check(
            self.ws, profile_root=self.profile
        )

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["verdict"], "fail")
        self.assertIn("source_cache_unreadable", self.warn_codes(verdict))
        self.assertIn("source_title_mismatch", self.hard_codes(verdict))

    def test_three_token_subtitle_truncation_still_matches(self):
        doi = "10." + "1234/subtitle-truncation"
        cited = "Coastal Light Exposure"
        cached = "Coastal Light Exposure: A Longitudinal Study"
        self.write_content(self.reference(cited, 2024, f"DOI: {doi}"))
        self.write_doi_cache(doi, cached)

        verdict, code = check_sources.check(self.ws, profile_root=self.profile)

        self.assertEqual(code, 0, verdict)
        self.assertNotIn("source_title_mismatch", self.hard_codes(verdict))

    def test_year_range_publication_token_is_fully_consumed(self):
        doi = "10." + "1234/year-range"
        title = "Longitudinal Study"
        year_range = "2020" + chr(0x2013) + "2021"
        self.write_content(
            "# References\n\n"
            f"- Doe ({year_range}). {title}. Journal. DOI: {doi}\n"
        )
        self.write_doi_cache(doi, title)

        verdict, code = check_sources.check(self.ws, profile_root=self.profile)

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["entries"][0]["year"], 2020)
        self.assertEqual(verdict["entries"][0]["title"], title)

    def test_future_in_press_or_forthcoming_year_is_advisory(self):
        for qualifier in ("in " + "press", "forth" + "coming"):
            with self.subTest(qualifier=qualifier):
                doi = "10." + "1234/" + qualifier.replace(" ", "-")
                title = "Forthcoming Result"
                self.write_content(
                    "# References\n\n"
                    f"- Doe (2027, {qualifier}). {title}. Journal. DOI: {doi}\n"
                )
                self.write_doi_cache(doi, title)

                verdict, code = check_sources.check(
                    self.ws, profile_root=self.profile, now=2026
                )

                self.assertEqual(code, 0, verdict)
                self.assertNotIn("source_year_future", self.hard_codes(verdict))
                self.assertIn(
                    "source_year_future_advisory", self.warn_codes(verdict)
                )
                self.assertEqual(verdict["entries"][0]["title"], title)

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
