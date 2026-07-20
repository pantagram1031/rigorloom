"""Tests for deterministic, fail-closed HWPX feature extraction."""
from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feature_extract  # noqa: E402


HEADER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="urn:head" xmlns:hp="urn:paragraph">
  <hh:fontfaces>
    <hh:fontface><hh:font id="0" face="Alpha"/></hh:fontface>
    <hh:fontface><hh:font id="1" face="Beta"/></hh:fontface>
  </hh:fontfaces>
  <hh:charProperties>
    <hh:charPr id="0"><hh:fontRef hangul="0" latin="1"/></hh:charPr>
  </hh:charProperties>
</hh:head>
"""

SECTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="urn:section" xmlns:hp="urn:paragraph">
  <hp:p><hp:run>
    <hp:secPr><hp:pagePr width="59528" height="84186">
      <hp:margin left="5669" right="5669" top="5669" bottom="5669"/>
    </hp:pagePr></hp:secPr>
    <hp:ctrl><hp:colPr colCount="2"/></hp:ctrl>
  </hp:run></hp:p>
  <hp:tbl><hp:tr><hp:tc><hp:tbl/></hp:tc></hp:tr></hp:tbl>
  <hp:equation><hp:pos treatAsChar="0"/></hp:equation>
  <hp:pic><hp:pos treatAsChar="0"/></hp:pic>
  <hp:header/><hp:footer/><hp:footNote/><hp:endNote/>
  <hp:fieldBegin type="HYPERLINK"/><hp:hyperlink/>
  <hp:rect/><hp:line/>
  <hp:ctrl><hp:mysteryControl/></hp:ctrl>
</hs:sec>
"""

RUN_CHILD_UNKNOWN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="urn:section" xmlns:hp="urn:paragraph">
  <hp:p><hp:run><hp:t>body</hp:t><hp:chart/></hp:run></hp:p>
</hs:sec>
"""


def _write_hwpx(path: Path, entries: list[tuple[str, str]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)


class FeatureExtractTestCase(unittest.TestCase):
    def test_deterministic_sorted_vocabulary_and_unknown_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.hwpx"
            second = Path(tmp) / "second.hwpx"
            entries = [
                ("Contents/header.xml", HEADER_XML),
                ("Contents/section0.xml", SECTION_XML),
            ]
            _write_hwpx(first, entries)
            _write_hwpx(second, list(reversed(entries)))

            first_features = feature_extract.extract_feature_counts(first)
            second_features = feature_extract.extract_feature_counts(second)

        self.assertEqual(first_features, second_features)
        self.assertEqual(list(first_features), sorted(first_features))
        self.assertEqual(first_features["sections"], 1)
        self.assertEqual(first_features["columns"], 2)
        self.assertEqual(first_features["tables"], 2)
        self.assertEqual(first_features["nested-table-depth"], 2)
        self.assertEqual(first_features["equations"], 1)
        self.assertEqual(first_features["images"], 1)
        self.assertEqual(first_features["headers"], 1)
        self.assertEqual(first_features["footers"], 1)
        self.assertEqual(first_features["footnotes"], 1)
        self.assertEqual(first_features["endnotes"], 1)
        self.assertEqual(first_features["floating-objects"], 2)
        self.assertEqual(first_features["shapes"], 1)
        self.assertEqual(first_features["lines"], 1)
        self.assertEqual(first_features["fields"], 1)
        self.assertEqual(first_features["hyperlinks"], 1)
        self.assertEqual(first_features["charpr-font-count"], 2)
        self.assertEqual(first_features["page-size:a4"], 1)
        self.assertEqual(first_features["page-margins:normal"], 1)
        self.assertEqual(first_features["unknown:mysteryControl"], 1)

    def test_cli_payload_is_canonical_and_rejects_non_hwpx(self):
        with tempfile.TemporaryDirectory() as tmp:
            hwpx = Path(tmp) / "plain.hwpx"
            _write_hwpx(hwpx, [("Contents/section0.xml", SECTION_XML)])
            payload = feature_extract.extract_features(hwpx)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["features"], dict(sorted(payload["features"].items())))

            bad = Path(tmp) / "plain.txt"
            bad.write_text("not an hwpx", encoding="utf-8")
            with self.assertRaises(ValueError):
                feature_extract.extract_feature_counts(bad)

    def test_unknown_run_child_is_emitted_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / "unknown-run-child.hwpx"
            _write_hwpx(document, [("Contents/section0.xml", RUN_CHILD_UNKNOWN_XML)])

            features = feature_extract.extract_feature_counts(document)

        self.assertEqual(features["unknown:chart"], 1)
        self.assertFalse(any(
            tag.startswith("unknown:") and tag != "unknown:chart"
            for tag in features
        ))


if __name__ == "__main__":
    unittest.main()
