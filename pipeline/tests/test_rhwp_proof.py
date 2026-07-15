"""Synthetic tests for experimental rhwp SVG proof receipts."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rhwp_proof  # noqa: E402
from test_hwpx_render_surrogate import _write_fixture  # noqa: E402


class RhwpProofTests(unittest.TestCase):
    def test_svg_success_is_experimental_and_records_structural_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "out.hwpx"
            proof_dir = root / "proof" / "rhwp"
            _write_fixture(canonical)
            comparison = {
                "render_diff": {
                    "max_displacement_px": 676.33,
                    "structural_mismatch_pages": 2,
                },
                "ir_diff": {"difference_count": 109},
            }

            def fake_run(command, **kwargs):
                out_dir = Path(command[-1])
                out_dir.mkdir(parents=True, exist_ok=True)
                for page in range(1, 4):
                    (out_dir / f"page-{page}.svg").write_text("<svg/>", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "rendered 3 pages", "")

            renderer = {
                "name": "rhwp_svg",
                "wsl": False,
                "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
                "version": "rhwp 0.7.18",
            }
            with mock.patch.object(rhwp_proof.subprocess, "run", side_effect=fake_run):
                receipt = rhwp_proof.run_svg_proof(
                    canonical, proof_dir, renderer, comparison=comparison
                )

            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["proof_grade"], "experimental-rhwp")
            self.assertFalse(receipt["submission_grade"])
            self.assertEqual(receipt["page_count"], 3)
            self.assertFalse(receipt["layout_overflow"])
            self.assertEqual(receipt["parity_verdict"], "fail")
            self.assertEqual(receipt["comparison"]["ir_diff"]["difference_count"], 109)
            self.assertTrue(receipt["comparison"]["structure_mismatch"])
            self.assertTrue((proof_dir / "receipt.json").is_file())

    def test_layout_overflow_is_detected_in_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "out.hwpx"
            _write_fixture(canonical)
            renderer = {
                "name": "rhwp_svg", "wsl": False,
                "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
            }

            def fake_run(command, **kwargs):
                out_dir = Path(command[-1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "page-1.svg").write_text("<svg/>", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "LAYOUT_OVERFLOW paragraph=1")

            with mock.patch.object(rhwp_proof.subprocess, "run", side_effect=fake_run):
                receipt = rhwp_proof.run_svg_proof(canonical, root / "proof", renderer)

            self.assertTrue(receipt["layout_overflow"])
            self.assertEqual(receipt["parity_verdict"], "fail")

    def test_timeout_fails_closed_and_keeps_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "out.hwpx"
            _write_fixture(canonical)
            before = canonical.read_bytes()
            renderer = {
                "name": "rhwp_svg", "wsl": False,
                "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
            }
            with mock.patch.object(
                rhwp_proof.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["rhwp"], 0.1),
            ):
                receipt = rhwp_proof.run_svg_proof(
                    canonical, root / "proof", renderer, timeout=0.1
                )

            self.assertFalse(receipt["ok"])
            self.assertEqual(receipt["proof_grade"], "none")
            self.assertEqual(receipt["reason"], "rhwp_timeout")
            self.assertEqual(receipt["fallback"], "canonical_hwpx_without_render_proof")
            self.assertEqual(canonical.read_bytes(), before)

    def test_corrupt_hwpx_fails_closed_with_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "out.hwpx"
            canonical.write_bytes(b"not a zip")
            renderer = {
                "name": "rhwp_svg", "wsl": False,
                "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
            }

            receipt = rhwp_proof.run_svg_proof(
                canonical, root / "proof", renderer
            )

            self.assertFalse(receipt["ok"])
            self.assertEqual(receipt["proof_grade"], "none")
            self.assertEqual(
                receipt["reason"], "rhwp_unavailable_or_surrogate_failed"
            )
            self.assertTrue((root / "proof" / "receipt.json").is_file())

    def test_verdict_merge_never_promotes_experimental_to_submission_grade(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict_path = Path(tmp) / "verdict_v06.json"
            verdict_path.write_text(json.dumps({"ok": True, "proof_grade": "advisory"}), encoding="utf-8")
            receipt = {
                "ok": True,
                "proof_grade": "experimental-rhwp",
                "submission_grade": False,
                "page_count": 3,
                "layout_overflow": False,
                "parity_verdict": "partial",
                "reason": "rhwp_svg_rendered",
                "comparison": {"structure_mismatch": False},
            }

            merged = rhwp_proof.merge_assembly_verdict(verdict_path, receipt)

            self.assertEqual(merged["proof_grade"], "experimental-rhwp")
            self.assertFalse(merged["render_proof"]["submission_grade"])
            on_disk = json.loads(verdict_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, merged)

    def test_missing_assembly_verdict_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict_path = Path(tmp) / "verdict_v06.json"
            receipt = {
                "ok": True,
                "proof_grade": "experimental-rhwp",
                "submission_grade": False,
            }

            merged = rhwp_proof.merge_assembly_verdict(verdict_path, receipt)

            self.assertIsNone(merged)
            self.assertFalse(verdict_path.exists())


if __name__ == "__main__":
    unittest.main()
