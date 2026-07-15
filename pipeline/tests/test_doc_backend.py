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


class TestPdfCmdWiring(unittest.TestCase):
    """doc_backend auto-passes --pdf-cmd to fill_report only when render_probe
    reports a usable soffice renderer AND fill_report's own --help
    output advertises the flag at dispatch time."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = _make_ws(Path(self._tmp.name), content="Equation-free body.\n")
        self.scripts = Path(self._tmp.name) / "hwp-master-scripts"
        self.scripts.mkdir()
        (self.scripts / "eqn.py").write_text("", encoding="utf-8")
        (self.scripts / "xml_backend.py").write_text("", encoding="utf-8")
        import render_probe
        self.render_probe = render_probe

    def tearDown(self):
        self._tmp.cleanup()

    def _write_fake_fill_report(self, advertises_pdf_cmd: bool) -> Path:
        help_text = "usage: fill_report.py [--engine {com,xml}]"
        if advertises_pdf_cmd:
            help_text += " [--pdf-cmd PDF_CMD]"
        fake = self.scripts / "fill_report.py"
        fake.write_text(
            "import json, sys\n"
            f"HELP = {help_text!r}\n"
            "if '--help' in sys.argv[1:]:\n"
            "    print(HELP)\n"
            "    raise SystemExit(0)\n"
            "print(json.dumps({'ok': True, 'argv': sys.argv[1:]}))\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        return fake

    def _run(self) -> dict:
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"HWP_MASTER_SCRIPTS": str(self.scripts)}),
            redirect_stdout(stdout),
        ):
            code = doc_backend.main([str(self.ws), "--backend", "hwpx"])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _run_mocked_decision(self, probe_result: dict, has_equations: bool) -> tuple[dict, list[str]]:
        stdout = io.StringIO()
        completed = mock.Mock(returncode=0, stdout='{"ok": true}', stderr="")

        def fake_run(command, **kwargs):
            if "--help" in command:
                return mock.Mock(returncode=0,
                                 stdout="usage: fill_report.py [--pdf-cmd PDF_CMD]",
                                 stderr="")
            completed.args = command
            return completed

        with (
            mock.patch.object(doc_backend, "_resolve_hwpx_fill_report",
                              return_value=str(self.scripts / "fill_report.py")),
            mock.patch.object(self.render_probe, "probe", return_value=probe_result),
            mock.patch.object(self.render_probe, "hwpx_has_equations",
                              return_value=has_equations),
            mock.patch.object(doc_backend.subprocess, "run", side_effect=fake_run),
            redirect_stdout(stdout),
        ):
            code = doc_backend.main([str(self.ws), "--backend", "hwpx"])

        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue()), completed.args

    def test_pdf_cmd_passed_when_renderer_usable_and_flag_advertised(self):
        self._write_fake_fill_report(advertises_pdf_cmd=True)
        fake_result = {"renderers": [
            {"name": "soffice_local", "wsl": False, "argv": ["soffice", "--headless"]},
        ]}
        with mock.patch.object(self.render_probe, "probe", return_value=fake_result):
            payload = self._run()
        self.assertIn("--pdf-cmd", payload["argv"])
        idx = payload["argv"].index("--pdf-cmd")
        self.assertEqual(payload["argv"][idx + 1], "soffice --headless")

    def test_pdf_cmd_omitted_when_flag_not_advertised(self):
        self._write_fake_fill_report(advertises_pdf_cmd=False)
        fake_result = {"renderers": [
            {"name": "soffice_local", "wsl": False, "argv": ["soffice", "--headless"]},
        ]}
        with mock.patch.object(self.render_probe, "probe", return_value=fake_result):
            payload = self._run()
        self.assertNotIn("--pdf-cmd", payload["argv"])

    def test_pdf_cmd_omitted_when_no_usable_renderer(self):
        self._write_fake_fill_report(advertises_pdf_cmd=True)
        with mock.patch.object(self.render_probe, "probe", return_value={"renderers": []}):
            payload = self._run()
        self.assertNotIn("--pdf-cmd", payload["argv"])

    def test_pdf_cmd_passed_when_only_wsl_renderer(self):
        self._write_fake_fill_report(advertises_pdf_cmd=True)
        fake_result = {"renderers": [
            {"name": "soffice_wsl", "wsl": True,
             "argv": ["wsl", "-e", "bash", "-lc", "wslpath $1",
                      "render_probe", "{outdir}", "{in}"]},
        ]}
        with mock.patch.object(self.render_probe, "probe", return_value=fake_result):
            payload = self._run()
        self.assertIn("--pdf-cmd", payload["argv"])
        idx = payload["argv"].index("--pdf-cmd")
        self.assertIn("wslpath", payload["argv"][idx + 1])
        self.assertIn("'{outdir}'", payload["argv"][idx + 1])
        self.assertIn("'{in}'", payload["argv"][idx + 1])

    def test_only_soffice_with_equations_omits_pdf_cmd_and_explains_no_proof(self):
        payload, command = self._run_mocked_decision(
            {
                "capabilities": {"hancom_com": False},
                "renderers": [
                    {"name": "soffice_local", "wsl": False,
                     "argv": ["soffice", "--headless"]},
                ],
            },
            has_equations=True,
        )

        self.assertNotIn("--pdf-cmd", command)
        self.assertEqual(payload["proof_grade"], "none")
        self.assertEqual(payload["reason"], "renderer_cannot_eqn")
        self.assertIsNone(payload["renderer_decision"]["selected"])

    def test_content_equation_before_assembly_routes_away_from_soffice(self):
        (self.ws / "bundle" / "content.md").write_text(
            'Before assembly [[EQ latex="E = mc^2"]] is present.\n',
            encoding="utf-8",
        )
        self.assertFalse((self.ws / "output" / "out.hwpx").exists())

        payload, command = self._run_mocked_decision(
            {
                "capabilities": {"hancom_com": False},
                "renderers": [
                    {"name": "soffice_local", "wsl": False,
                     "argv": ["soffice", "--headless"]},
                ],
            },
            has_equations=False,
        )

        self.assertNotIn("--pdf-cmd", command)
        self.assertEqual(payload["reason"], "renderer_cannot_eqn")
        self.assertEqual(payload["proof_grade"], "none")

    def test_only_soffice_without_equations_passes_pdf_cmd(self):
        payload, command = self._run_mocked_decision(
            {
                "capabilities": {"hancom_com": False},
                "renderers": [
                    {"name": "soffice_local", "wsl": False,
                     "argv": ["soffice", "--headless"]},
                ],
            },
            has_equations=False,
        )

        self.assertIn("--pdf-cmd", command)
        self.assertEqual(payload["proof_grade"], "advisory")
        self.assertEqual(payload["renderer_decision"]["selected"], "soffice_local")

    def test_hancom_with_equations_is_preferred_over_soffice(self):
        payload, command = self._run_mocked_decision(
            {
                "capabilities": {"hancom_com": True},
                "renderers": [
                    {"name": "hancom", "wsl": False, "argv": None},
                    {"name": "soffice_local", "wsl": False,
                     "argv": ["soffice", "--headless"]},
                ],
            },
            has_equations=True,
        )

        self.assertNotIn("--pdf-cmd", command)
        self.assertEqual(payload["proof_grade"], "hancom")
        self.assertEqual(payload["renderer_decision"]["selected"], "hancom")

    def test_equation_free_prefers_soffice_over_rhwp_in_either_probe_order(self):
        rhwp_renderer = {
            "name": "rhwp_svg", "wsl": False,
            "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
        }
        soffice_renderer = {
            "name": "soffice_local", "wsl": False,
            "argv": ["soffice", "--headless"],
        }
        for renderers in (
            [rhwp_renderer, soffice_renderer],
            [soffice_renderer, rhwp_renderer],
        ):
            with (
                self.subTest(order=[item["name"] for item in renderers]),
                mock.patch.object(
                    self.render_probe,
                    "probe",
                    return_value={
                        "capabilities": {"hancom_com": False},
                        "renderers": renderers,
                    },
                ),
                mock.patch.object(
                    self.render_probe, "hwpx_has_equations", return_value=False
                ),
            ):
                decision = doc_backend._hwpx_renderer_decision(str(self.ws), None)

            self.assertEqual(decision["selected"], "soffice_local")
            self.assertEqual(decision["proof_grade"], "advisory")
            self.assertEqual(decision["pdf_cmd_argv"], ["soffice", "--headless"])

    def test_rhwp_is_selected_for_equation_documents_as_experimental(self):
        rhwp_renderer = {
            "name": "rhwp_svg",
            "wsl": False,
            "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
            "proof_grade": "experimental-rhwp",
        }
        with (
            mock.patch.object(
                self.render_probe,
                "probe",
                return_value={
                    "capabilities": {"hancom_com": False},
                    "renderers": [
                        rhwp_renderer,
                        {"name": "soffice_local", "wsl": False,
                         "argv": ["soffice", "--headless"]},
                    ],
                },
            ),
            mock.patch.object(
                self.render_probe, "hwpx_has_equations", return_value=True
            ),
        ):
            decision = doc_backend._hwpx_renderer_decision(str(self.ws), None)

        self.assertEqual(decision["selected"], "rhwp_svg")
        self.assertEqual(decision["proof_grade"], "experimental-rhwp")
        self.assertIsNone(decision["pdf_cmd_argv"])
        self.assertEqual(decision["rhwp_renderer"], rhwp_renderer)

    def test_successful_adapter_runs_rhwp_proof_and_emits_receipt_summary(self):
        rhwp_renderer = {
            "name": "rhwp_svg",
            "wsl": False,
            "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"],
            "proof_grade": "experimental-rhwp",
        }
        proof_receipt = {
            "ok": True,
            "proof_grade": "experimental-rhwp",
            "submission_grade": False,
            "page_count": 3,
            "layout_overflow": False,
            "parity_verdict": "partial",
            "reason": "rhwp_svg_rendered",
            "comparison": {"structure_mismatch": False},
        }
        stdout = io.StringIO()
        completed = mock.Mock(returncode=0, stdout='{"ok": true}', stderr="")

        def fake_run(command, **kwargs):
            if "--help" in command:
                return mock.Mock(returncode=0, stdout="usage: fill_report.py", stderr="")
            return completed

        with (
            mock.patch.object(
                doc_backend, "_resolve_hwpx_fill_report",
                return_value=str(self.scripts / "fill_report.py"),
            ),
            mock.patch.object(
                self.render_probe,
                "probe",
                return_value={
                    "capabilities": {"hancom_com": False},
                    "renderers": [rhwp_renderer],
                },
            ),
            mock.patch.object(
                self.render_probe, "hwpx_has_equations", return_value=True
            ),
            mock.patch.object(doc_backend.subprocess, "run", side_effect=fake_run),
            mock.patch.object(
                doc_backend, "_run_experimental_rhwp",
                return_value=proof_receipt,
            ) as run_proof,
            redirect_stdout(stdout),
        ):
            code = doc_backend.main([str(self.ws), "--backend", "hwpx"])

        self.assertEqual(code, 0)
        run_proof.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["proof_grade"], "experimental-rhwp")
        self.assertEqual(payload["render_proof"]["page_count"], 3)
        self.assertFalse(payload["render_proof"]["submission_grade"])
        self.assertNotIn("rhwp_renderer", payload["renderer_decision"])


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
