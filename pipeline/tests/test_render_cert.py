"""Synthetic tests for renderer measurement, certification, and checking."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feature_extract  # noqa: E402
import render_cert  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_hwpx(path: Path, *, unknown: bool = False, sections: int = 1) -> None:
    control = "<hp:ctrl><hp:alien/></hp:ctrl>" if unknown else ""
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="urn:section" xmlns:hp="urn:paragraph">'
        '<hp:p><hp:run><hp:secPr><hp:pagePr width="59528" height="84186">'
        '<hp:margin left="5669" right="5669" top="5669" bottom="5669"/>'
        '</hp:pagePr></hp:secPr><hp:ctrl><hp:colPr colCount="1"/></hp:ctrl>'
        f'{control}</hp:run></hp:p></hs:sec>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(sections):
            archive.writestr(f"Contents/section{index}.xml", section)


def _metrics(*, page_exact: bool = True, anchor: float = 0.0, raster: float = 0.0):
    return {
        "page_count": {"reference": 1, "candidate": 1 if page_exact else 2,
                       "exact": page_exact},
        "word_anchor": {"max_displacement_px": anchor, "matched_unique_words": 4},
        "raster": {"changed_channel_ratio": raster},
    }


class RenderCertTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.binary = self.root / "mock-renderer.bin"
        self.binary.write_bytes(b"mock renderer version 1")
        self.doc = self.root / "document.hwpx"
        _write_hwpx(self.doc)
        self.features = feature_extract.extract_feature_counts(self.doc)
        self.manifest = self.root / "manifest.json"
        self._write_manifest()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_manifest(self):
        payload = {
            "schema_version": 1,
            "documents": [
                {
                    "id": "train-a", "split": "train", "document": "document.hwpx",
                    "generator": {"type": "sanitized-template", "source": "fixture"},
                    "features": self.features,
                    "reference_pdf": {"path": "reference.pdf", "sha256": "0" * 64},
                    "hancom_version": "Hancom 2024.0",
                },
                {
                    "id": "holdout-a", "split": "holdout", "document": "document.hwpx",
                    "generator": {"type": "sanitized-template", "source": "fixture"},
                    "features": self.features,
                    "reference_pdf": {"path": "reference.pdf", "sha256": "0" * 64},
                    "hancom_version": "Hancom 2024.0",
                },
            ],
        }
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")

    def _measurements(self, *, holdout_pass: bool = True):
        return {
            "schema_version": 1,
            "renderer": {
                "id": "mock", "version": "mock 1.0",
                "binary_path": str(self.binary),
                "binary_sha256": _sha256(self.binary),
                "argv": [str(self.binary), "{in}", "{out}"],
            },
            "corpus": {
                "manifest_path": str(self.manifest),
                "manifest_sha256": _sha256(self.manifest),
                "hancom_version": "Hancom 2024.0",
            },
            "documents": [
                {"id": "train-a", "split": "train", "features": self.features,
                 "metrics": _metrics()},
                {"id": "holdout-a", "split": "holdout", "features": self.features,
                 "metrics": _metrics(page_exact=holdout_pass)},
            ],
        }

    def _thresholds(self):
        return {
            "page_count_exact": True,
            "word_anchor_px": 1.0,
            "raster_changed_channel_ratio": 0.01,
        }

    def test_holdout_failure_excludes_affected_feature_combination(self):
        certificate = render_cert.issue_certificate(
            self._measurements(holdout_pass=False),
            self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        self.assertEqual(certificate["envelope"], [])
        self.assertEqual(certificate["holdout_stats"]["failed"], 1)

    def test_holdout_failure_also_carves_a_covering_superset_envelope(self):
        measurements = self._measurements()
        smaller = dict(self.features, tables=1)
        larger = dict(self.features, tables=2)
        measurements["documents"] = [
            {"id": "small-train", "split": "train", "features": smaller,
             "metrics": _metrics()},
            {"id": "small-holdout", "split": "holdout", "features": smaller,
             "metrics": _metrics(page_exact=False)},
            {"id": "large-train", "split": "train", "features": larger,
             "metrics": _metrics()},
            {"id": "large-holdout", "split": "holdout", "features": larger,
             "metrics": _metrics()},
        ]

        certificate = render_cert.issue_certificate(
            measurements, self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )

        self.assertEqual(certificate["envelope"], [])

    def test_check_accepts_valid_envelope_and_returns_stable_reason(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)

        result = render_cert.check_document(
            self.doc, cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(result["reason_code"], "eligible")

    def test_renderer_version_mismatch_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)

        result = render_cert.check_document(
            self.doc, cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 2.0",
        )
        self.assertFalse(result["eligible"])
        self.assertIn("renderer_version_mismatch", result["reason_codes"])

    def test_hancom_version_mismatch_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["hancom_version"] = "Hancom 2025.0"
        certificate["certificate_sha256"] = render_cert._certificate_digest(certificate)
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)

        result = render_cert.check_document(
            self.doc, cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "hancom_version_mismatch")

    def test_edited_certificate_fails_self_hash_reverification(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["renderer_id"] = "edited-after-issue"
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)

        result = render_cert.verify_certificate(
            cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "certificate_hash_mismatch")

    def test_unknown_feature_is_always_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)
        unknown_doc = self.root / "unknown.hwpx"
        _write_hwpx(unknown_doc, unknown=True)

        result = render_cert.check_document(
            unknown_doc, cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "unknown_feature")

    def test_envelope_mismatch_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate.json"
        render_cert.write_json(cert_path, certificate)
        larger_doc = self.root / "two-sections.hwpx"
        _write_hwpx(larger_doc, sections=2)

        result = render_cert.check_document(
            larger_doc, cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "envelope_mismatch")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_uses_mock_renderer_and_verifies_manifest_features_and_hashes(self):
        import fitz

        reference = self.root / "reference.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 72), "alpha beta gamma")
        document.save(reference)
        document.close()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        for entry in manifest["documents"]:
            entry["reference_pdf"]["sha256"] = _sha256(reference)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

        measured = render_cert.measure_corpus(
            "mock", self.manifest,
            work_dir=self.root / "measure-work",
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
            renderer_argv=[str(self.binary), "{in}", "{out}"],
            render_callback=lambda entry, source, candidate: reference,
            dpi=72,
        )

        self.assertTrue(all(record["ok"] for record in measured["documents"]))
        self.assertEqual(measured["renderer"]["binary_sha256"], _sha256(self.binary))
        self.assertTrue(all(
            record["metrics"]["page_count"]["exact"]
            for record in measured["documents"]
        ))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_pdf_metrics_include_exact_pages_word_anchors_and_raster_ratio(self):
        import fitz

        reference = self.root / "reference.pdf"
        identical = self.root / "identical.pdf"
        changed = self.root / "changed.pdf"

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "alpha beta gamma")
        document.save(reference)
        document.close()
        shutil.copyfile(reference, identical)

        document = fitz.open()
        page = document.new_page()
        page.insert_text((100, 72), "alpha beta gamma")
        document.new_page().insert_text((72, 72), "second page")
        document.save(changed)
        document.close()

        same_metrics = render_cert.compare_pdf_metrics(reference, identical, dpi=72)
        self.assertTrue(same_metrics["page_count"]["exact"])
        self.assertEqual(same_metrics["word_anchor"]["max_displacement_px"], 0.0)
        self.assertEqual(same_metrics["raster"]["changed_channel_ratio"], 0.0)

        changed_metrics = render_cert.compare_pdf_metrics(reference, changed, dpi=72)
        self.assertFalse(changed_metrics["page_count"]["exact"])
        self.assertGreater(changed_metrics["word_anchor"]["max_displacement_px"], 0.0)
        self.assertGreater(changed_metrics["raster"]["changed_channel_ratio"], 0.0)


class CorpusGeneratorStubTestCase(unittest.TestCase):
    def test_windows_reference_stub_emits_ops_and_pending_manifest_only(self):
        generator_path = (
            Path(__file__).parents[2] / "tests" / "corpus" / "render-cert" /
            "generate.py"
        )
        spec = importlib.util.spec_from_file_location("render_cert_generate", generator_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.emit_windows_reference_stub(
                root,
                entry_id="form-a-train",
                split="train",
                document_name="form-a.hwpx",
                reference_pdf_name="form-a-reference.pdf",
                template_ref="sanitized/form-a.hwpx",
                ops=[{"op": "insert_text", "text": "synthetic"}],
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            entry = manifest["documents"][0]
            self.assertEqual(entry["status"], "awaiting_windows_reference")
            self.assertTrue(entry["generator"]["requires_windows_reference"])
            self.assertIsNone(entry["features"])
            self.assertIsNone(entry["reference_pdf"]["sha256"])
            self.assertTrue((root / "ops" / "form-a-train.ops.json").is_file())
            self.assertFalse((root / "form-a.hwpx").exists())
            self.assertFalse((root / "form-a-reference.pdf").exists())


if __name__ == "__main__":
    unittest.main()
