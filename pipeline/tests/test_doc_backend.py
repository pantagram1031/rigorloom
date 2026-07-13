# -*- coding: utf-8 -*-
"""Tests for the pluggable document backends (doc_backend + adapters_impl).

Synthetic fixtures ONLY (Korean-free fake content). Covers:
  * bundle backend end-to-end (files copied, preview.html has img+caption+table,
    manifest sha256 verify against re-hashed files)
  * backend resolution order (flag > build.yaml doc_backend: > default bundle)
  * hwp backend → exit 4 (external adapter)
  * hwpx backend → external XML adapter resolution and argv/JSON propagation
  * docx backend → skipped when python-docx absent, else zipfile-inspects
    word/document.xml for a heading string
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_PIPELINE_DIR = Path(__file__).parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

adapters_impl = importlib.import_module("adapters_impl")
bundle_backend = importlib.import_module("adapters_impl.bundle_backend")
docx_backend = importlib.import_module("adapters_impl.docx_backend")

_DOC_BACKEND = _PIPELINE_DIR / "scripts" / "doc_backend.py"
_spec = importlib.util.spec_from_file_location("doc_backend", _DOC_BACKEND)
doc_backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doc_backend)

CONTENT = (
    "---\n"
    "title: Synthetic Widget Report\n"
    "doc_backend: bundle\n"
    "---\n"
    "## SECTION: I. Intro\n"
    "\n"
    "This is a body paragraph with an inline equation "
    '[[EQ latex="E = mc^2"]] embedded in the flow.\n'
    "\n"
    "## SECTION: II. Results\n"
    "\n"
    '[[FIG file="plot.png" width=90 caption="Figure 1. A synthetic plot"]]\n'
    "\n"
    '[[TABLE cols=50,50 pt=9 caption="Table 1. Synthetic data"]]\n'
    "| Time | Value |\n"
    "| 1 | 16.7 |\n"
    "| 2 | 18.6 |\n"
    "[[/TABLE]]\n"
)


def _make_ws(root: Path, content: str = CONTENT, build_yaml: str | None = None) -> Path:
    ws = root / "report-synthetic"
    (ws / "bundle" / "figures").mkdir(parents=True, exist_ok=True)
    (ws / "bundle" / "content.md").write_text(content, encoding="utf-8")
    (ws / "bundle" / "figures" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    if build_yaml is not None:
        (ws / "build.yaml").write_text(build_yaml, encoding="utf-8")
    return ws


class TestBundleBackend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = _make_ws(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_end_to_end(self):
        result, code = bundle_backend.build(str(self.ws))
        self.assertEqual(code, 0, result)
        deliverable = Path(result["out_dir"])

        # files copied
        self.assertTrue((deliverable / "content.md").is_file())
        self.assertTrue((deliverable / "figures" / "plot.png").is_file())
        self.assertTrue((deliverable / "preview.html").is_file())
        self.assertTrue((deliverable / "manifest.json").is_file())

        # preview.html has img + caption + table + literal equation
        html = (deliverable / "preview.html").read_text(encoding="utf-8")
        self.assertIn("<img", html)
        self.assertIn("Figure 1. A synthetic plot", html)  # caption
        self.assertIn("figcaption", html)
        self.assertIn("<table", html)
        self.assertIn("Table 1. Synthetic data", html)
        self.assertIn("E = mc^2", html)  # honest literal equation, not typeset
        self.assertIn('class="eq"', html)

        # manifest sha256 verify against re-hashed files
        manifest = json.loads((deliverable / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("manifest.json", [e["path"] for e in manifest["files"]])
        for entry in manifest["files"]:
            actual = hashlib.sha256((deliverable / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(actual, entry["sha256"], entry["path"])
        self.assertIn("generated_at", manifest)

    def test_deterministic_preview(self):
        # preview.html content must not depend on wall-clock time
        r1, _ = bundle_backend.build(str(self.ws))
        h1 = (Path(r1["out_dir"]) / "preview.html").read_bytes()
        r2, _ = bundle_backend.build(str(self.ws))
        h2 = (Path(r2["out_dir"]) / "preview.html").read_bytes()
        self.assertEqual(h1, h2)

    def test_missing_content_floor(self):
        (self.ws / "bundle" / "content.md").unlink()
        result, code = bundle_backend.build(str(self.ws))
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])


class TestBackendResolution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_bundle(self):
        ws = _make_ws(self.root)
        self.assertEqual(doc_backend.resolve_backend(str(ws), None), "bundle")

    def test_build_yaml_wins_over_default(self):
        ws = _make_ws(self.root, build_yaml="doc_backend: docx\ntitle: X\n")
        self.assertEqual(doc_backend.resolve_backend(str(ws), None), "docx")

    def test_flag_wins_over_build_yaml(self):
        ws = _make_ws(self.root, build_yaml="doc_backend: docx\n")
        self.assertEqual(doc_backend.resolve_backend(str(ws), "hwp"), "hwp")


class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = _make_ws(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_hwp_exits_4(self):
        code = doc_backend.main([str(self.ws), "--backend", "hwp"])
        self.assertEqual(code, 4)

    def test_hwpx_without_external_adapter_exits_4_with_instructions(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = doc_backend.main([str(self.ws), "--backend", "hwpx"])

        self.assertEqual(code, 4)
        self.assertIn("HWP_MASTER_SCRIPTS", stderr.getvalue())
        self.assertIn("--engine xml", stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["backend"], "hwpx")

    def test_hwpx_dispatches_xml_engine_and_propagates_json_and_exit(self):
        scripts = Path(self._tmp.name) / "hwp-master-scripts"
        scripts.mkdir()
        fake = scripts / "fill_report.py"
        fake.write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': False, 'argv': sys.argv[1:]}))\n"
            "raise SystemExit(7)\n",
            encoding="utf-8",
        )
        (scripts / "eqn.py").write_text("", encoding="utf-8")
        (scripts / "xml_backend.py").write_text("", encoding="utf-8")
        out_dir = self.ws / "output" / "xml"
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"HWP_MASTER_SCRIPTS": str(scripts)}),
            redirect_stdout(stdout),
        ):
            code = doc_backend.main([
                str(self.ws), "--backend", "hwpx", "--out-dir", str(out_dir),
            ])

        self.assertEqual(code, 7)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["argv"], [
            "--engine", "xml",
            "--form", str(self.ws / "output" / "form_copy.hwpx"),
            "--content", str(self.ws / "bundle" / "content.md"),
            "--out-dir", str(out_dir),
        ])

    def test_hwpx_with_missing_marker_siblings_exits_4(self):
        # fill_report.py alone is not enough — eqn.py and xml_backend.py must
        # also be present, or HWP_MASTER_SCRIPTS is treated as misconfigured.
        scripts = Path(self._tmp.name) / "hwp-master-scripts-incomplete"
        scripts.mkdir()
        (scripts / "fill_report.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"HWP_MASTER_SCRIPTS": str(scripts)}),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = doc_backend.main([str(self.ws), "--backend", "hwpx"])

        self.assertEqual(code, 4)
        self.assertIn("eqn.py", stderr.getvalue())
        self.assertIn("xml_backend.py", stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["backend"], "hwpx")

    def test_bundle_via_cli(self):
        code = doc_backend.main([str(self.ws), "--backend", "bundle"])
        self.assertEqual(code, 0)
        self.assertTrue((self.ws / "output" / "deliverable" / "preview.html").is_file())

    def test_out_dir_escape_refused(self):
        # --out-dir must stay under <WS>/output (bundle deletes figure dirs at
        # the target — an arbitrary path would be destructive).
        outside = Path(self._tmp.name) / "elsewhere"
        code = doc_backend.main([str(self.ws), "--backend", "bundle",
                                 "--out-dir", str(outside)])
        self.assertEqual(code, 2)
        self.assertFalse(outside.exists())

    def test_out_dir_inside_output_allowed(self):
        inside = self.ws / "output" / "alt"
        code = doc_backend.main([str(self.ws), "--backend", "bundle",
                                 "--out-dir", str(inside)])
        self.assertEqual(code, 0)
        self.assertTrue((inside / "preview.html").is_file())


class TestDocxBackend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = _make_ws(Path(self._tmp.name),
                           build_yaml="doc_backend: docx\ntitle: Synthetic Widget Report\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_docx_render_or_skip(self):
        if importlib.util.find_spec("docx") is None:
            result, code = docx_backend.build(str(self.ws))
            self.assertEqual(code, 5)
            self.assertIn("python-docx", result.get("hint", ""))
            self.skipTest("python-docx not installed; verified exit-5 install hint")
        result, code = docx_backend.build(str(self.ws))
        self.assertEqual(code, 0, result)
        out = Path(result["out"])
        self.assertTrue(out.is_file())
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        # a section heading string must survive into the document body
        self.assertIn("Intro", xml)


if __name__ == "__main__":
    unittest.main()
