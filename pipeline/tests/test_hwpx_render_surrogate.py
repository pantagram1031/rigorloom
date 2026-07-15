"""Synthetic tests for the non-canonical HWPX render surrogate."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hwpx_render_surrogate  # noqa: E402


STALE_LINESEG = (
    '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" '
    'vertsize="1000" textheight="1000" baseline="850" spacing="600" '
    'horzpos="0" horzsize="51024" flags="393216" /></hp:linesegarray>'
)


def _write_fixture(path: Path) -> None:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hp:section xmlns:hp="urn:hancom">'
        f'<hp:p id="1"><hp:run><hp:t>Long synthetic body</hp:t></hp:run>{STALE_LINESEG}</hp:p>'
        '<hp:p id="2"><hp:run><hp:t>Real laid-out line</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="1200" '
        'vertsize="1000" textheight="1000" baseline="850" spacing="600" '
        'horzpos="0" horzsize="51024" flags="0" /></hp:linesegarray></hp:p>'
        '<hp:tbl rowCnt="1" colCnt="1"/><hp:pic/><hp:equation/>'
        '</hp:section>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = b"synthetic"
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/section0.xml", section, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("Contents/header.xml", "<header/>", compress_type=zipfile.ZIP_DEFLATED)


class RenderSurrogateTests(unittest.TestCase):
    def test_strips_only_xml_backend_placeholder_and_preserves_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = Path(tmp) / "canonical.hwpx"
            surrogate = Path(tmp) / "proof" / "render-surrogate.hwpx"
            _write_fixture(canonical)
            before = canonical.read_bytes()

            receipt = hwpx_render_surrogate.create_render_surrogate(
                canonical, surrogate
            )

            self.assertEqual(canonical.read_bytes(), before)
            self.assertEqual(
                receipt["canonical_sha256"], hashlib.sha256(before).hexdigest()
            )
            self.assertEqual(receipt["canonical_sha256_after"], receipt["canonical_sha256"])
            self.assertEqual(receipt["stale_linesegarrays_removed"], 1)
            self.assertTrue(receipt["semantic_parity"])
            self.assertEqual(
                receipt["canonical_fingerprint"], receipt["surrogate_fingerprint"]
            )
            self.assertEqual(
                receipt["canonical_fingerprint"]["counts"],
                {"paragraphs": 2, "tables": 1, "pictures": 1, "equations": 1},
            )

            with zipfile.ZipFile(canonical) as source, zipfile.ZipFile(surrogate) as rendered:
                self.assertEqual(source.comment, rendered.comment)
                self.assertEqual(source.read("Contents/header.xml"), rendered.read("Contents/header.xml"))
                section = rendered.read("Contents/section0.xml")
                self.assertEqual(section.count(b"linesegarray"), 2)
                self.assertNotIn(b'flags="393216"', section)
                self.assertIn(b'flags="0"', section)

    def test_refuses_to_overwrite_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = Path(tmp) / "canonical.hwpx"
            _write_fixture(canonical)
            with self.assertRaises(ValueError):
                hwpx_render_surrogate.create_render_surrogate(canonical, canonical)


if __name__ == "__main__":
    unittest.main()
