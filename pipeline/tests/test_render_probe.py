# -*- coding: utf-8 -*-
"""Tests for render_probe.py (capability detector).

Covers: well-formed JSON with all keys when everything is absent (monkeypatch
shutil.which / subprocess.run), the WSL path translation helper, renderer
list construction, best_pdf_cmd selection, and
the human-readable table formatter.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

_SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import render_probe  # noqa: E402


class TestHwpxHasEquations(unittest.TestCase):
    def test_true_when_section_xml_contains_equation_element(self):
        with tempfile.TemporaryDirectory() as tmp:
            hwpx = Path(tmp) / "equations.hwpx"
            with zipfile.ZipFile(hwpx, "w") as archive:
                archive.writestr(
                    "Contents/section0.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<hp:section xmlns:hp="urn:hancom"><hp:equation/></hp:section>',
                )

            self.assertTrue(render_probe.hwpx_has_equations(hwpx))

    def test_false_when_sections_have_no_equations_or_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            hwpx = Path(tmp) / "plain.hwpx"
            with zipfile.ZipFile(hwpx, "w") as archive:
                archive.writestr(
                    "Contents/section0.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<hp:section xmlns:hp="urn:hancom"><hp:p/></hp:section>',
                )
                archive.writestr("Contents/header.xml", "<hp:equation/>")

            self.assertFalse(render_probe.hwpx_has_equations(hwpx))
            self.assertFalse(render_probe.hwpx_has_equations(Path(tmp) / "missing.hwpx"))


class TestProbeAllAbsent(unittest.TestCase):
    def test_well_formed_json_with_all_keys_when_everything_absent(self):
        with (
            mock.patch.object(render_probe.sys, "platform", "linux"),
            mock.patch.object(render_probe.shutil, "which", return_value=None),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            result = render_probe.probe()

        self.assertEqual(result["capabilities"], {
            "hancom_com": False,
            "soffice_path": None,
            "soffice_wsl": False,
            "h2orestart": "unknown",
            "rhwp_path": None,
            "rhwp_wsl": False,
            "rhwp_version": None,
            "rhwp_reason": "not_found",
        })
        self.assertEqual(result["renderers"], [])

    def test_subprocess_failures_are_tolerated_as_unknown_not_raised(self):
        # win32 so soffice_wsl/hancom_com probes actually run their subprocess
        # / import path, and both are made to fail loudly.
        def _boom(*a, **kw):
            raise OSError("wsl not found")

        with (
            mock.patch.object(render_probe.sys, "platform", "win32"),
            mock.patch.object(render_probe.shutil, "which", return_value=None),
            mock.patch.object(render_probe.subprocess, "run", side_effect=_boom),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            result = render_probe.probe()

        self.assertFalse(result["capabilities"]["soffice_wsl"])
        self.assertEqual(result["capabilities"]["h2orestart"], "unknown")
        self.assertEqual(result["renderers"], [])


class TestRhwpProbe(unittest.TestCase):
    def test_native_rhwp_cli_becomes_experimental_svg_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "rhwp"
            binary.write_bytes(b"synthetic executable marker")

            def fake_run(command, **kwargs):
                self.assertEqual(command, [str(binary), "--version"])
                return subprocess.CompletedProcess(
                    command, 0, stdout="rhwp 0.7.18\n", stderr=""
                )

            with (
                mock.patch.object(render_probe.sys, "platform", "linux"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(render_probe.subprocess, "run", side_effect=fake_run),
                mock.patch.dict(os.environ, {
                    "RHWP_BIN": str(binary),
                    "RHWP_SHA256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                }, clear=True),
            ):
                result = render_probe.probe()

        self.assertEqual(result["capabilities"]["rhwp_path"], str(binary))
        self.assertFalse(result["capabilities"]["rhwp_wsl"])
        self.assertEqual(result["capabilities"]["rhwp_version"], "rhwp 0.7.18")
        self.assertEqual(result["capabilities"]["rhwp_reason"], "available")
        renderer = next(item for item in result["renderers"] if item["name"] == "rhwp_svg")
        self.assertEqual(
            renderer["argv"],
            [str(binary), "export-svg", "{in}", "-o", "{outdir}"],
        )
        self.assertEqual(renderer["proof_grade"], "experimental-rhwp")

    def test_rhwp_hash_mismatch_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "rhwp"
            binary.write_bytes(b"synthetic executable marker")
            with (
                mock.patch.object(render_probe.sys, "platform", "linux"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(render_probe.subprocess, "run") as run,
                mock.patch.dict(os.environ, {
                    "RHWP_BIN": str(binary),
                    "RHWP_SHA256": "0" * 64,
                }, clear=True),
            ):
                result = render_probe.probe()

        self.assertEqual(
            result["capabilities"]["rhwp_reason"], "rhwp_hash_mismatch"
        )
        self.assertNotIn("rhwp_svg", [item["name"] for item in result["renderers"]])
        run.assert_not_called()

    def test_unpinned_rhwp_is_unavailable_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "rhwp"
            binary.write_bytes(b"synthetic executable marker")
            with (
                mock.patch.object(render_probe.sys, "platform", "linux"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(render_probe.subprocess, "run") as run,
                mock.patch.dict(os.environ, {"RHWP_BIN": str(binary)}, clear=True),
            ):
                result = render_probe.probe()

        self.assertEqual(result["capabilities"]["rhwp_reason"], "rhwp_unpinned")
        self.assertNotIn("rhwp_svg", [item["name"] for item in result["renderers"]])
        run.assert_not_called()

    def test_windows_linux_binary_is_probed_through_wsl(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "rhwp"
            binary.write_bytes(b"synthetic ELF marker")

            def fake_run(command, **kwargs):
                if command[:2] == ["wsl", "--"]:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="rhwp 0.7.18\n", stderr=""
                    )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

            with (
                mock.patch.object(render_probe.sys, "platform", "win32"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(render_probe.subprocess, "run", side_effect=fake_run),
                mock.patch.dict(os.environ, {
                    "RHWP_BIN": str(binary),
                    "RHWP_SHA256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                }, clear=True),
            ):
                result = render_probe.probe()

        self.assertTrue(result["capabilities"]["rhwp_wsl"])
        renderer = next(item for item in result["renderers"] if item["name"] == "rhwp_svg")
        self.assertTrue(renderer["wsl"])
        self.assertEqual(renderer["argv"][:2], ["wsl", "--"])


class TestCertifiedRendererProbe(unittest.TestCase):
    def test_valid_configured_certificate_advertises_certified_renderer(self):
        certificate = {
            "renderer_id": "mock",
            "renderer_version": "mock 1.0",
            "renderer_binary_path": "/opt/mock-renderer",
            "renderer_argv": ["/opt/mock-renderer", "{in}", "{out}"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "certificate.json"
            cert_path.write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(render_probe.sys, "platform", "linux"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(
                    render_probe.render_cert,
                    "verify_certificate",
                    return_value={
                        "ok": True,
                        "reason_code": "certificate_valid",
                        "certificate": certificate,
                    },
                ),
                mock.patch.dict(os.environ, {
                    "RIGORLOOM_RENDER_CERTIFICATE": str(cert_path),
                }, clear=True),
            ):
                result = render_probe.probe()

        self.assertEqual(
            result["capabilities"]["render_certificate_reason"],
            "certificate_valid",
        )
        renderer = next(
            item for item in result["renderers"]
            if item["proof_grade"] == "certified"
        )
        self.assertEqual(renderer["certificate"], str(cert_path.resolve()))
        self.assertEqual(renderer["argv"], certificate["renderer_argv"])

    def test_invalid_certificate_is_not_advertised(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "certificate.json"
            cert_path.write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(render_probe.sys, "platform", "linux"),
                mock.patch.object(render_probe.shutil, "which", return_value=None),
                mock.patch.object(
                    render_probe.render_cert,
                    "verify_certificate",
                    return_value={
                        "ok": False,
                        "reason_code": "certificate_hash_mismatch",
                    },
                ),
                mock.patch.dict(os.environ, {
                    "RIGORLOOM_RENDER_CERTIFICATE": str(cert_path),
                }, clear=True),
            ):
                result = render_probe.probe()

        self.assertEqual(
            result["capabilities"]["render_certificate_reason"],
            "certificate_hash_mismatch",
        )
        self.assertFalse(any(
            item.get("proof_grade") == "certified"
            for item in result["renderers"]
        ))


class TestSofficePathPresent(unittest.TestCase):
    def test_soffice_local_renderer_has_placeholders(self):
        with (
            mock.patch.object(render_probe.sys, "platform", "linux"),
            mock.patch.object(render_probe.shutil, "which",
                              side_effect=lambda name: "/usr/bin/soffice" if name == "soffice" else None),
            mock.patch.object(render_probe.subprocess, "run",
                              side_effect=subprocess.TimeoutExpired(cmd="unopkg", timeout=10)),
        ):
            result = render_probe.probe()

        self.assertEqual(result["capabilities"]["soffice_path"], "/usr/bin/soffice")
        self.assertEqual(result["capabilities"]["h2orestart"], "unknown")
        names = [r["name"] for r in result["renderers"]]
        self.assertEqual(names, ["soffice_local"])
        renderer = result["renderers"][0]
        self.assertFalse(renderer["wsl"])
        self.assertIn("{in}", renderer["argv"])
        self.assertIn("{outdir}", renderer["argv"])

    def test_h2orestart_yes_when_bundled_list_mentions_it(self):
        def _fake_run(cmd, **kw):
            self.assertEqual(cmd, ["unopkg", "list", "--bundled"])
            return subprocess.CompletedProcess(cmd, 0, stdout="net.sf.h2restart.oxt\n", stderr="")

        with (
            mock.patch.object(render_probe.sys, "platform", "linux"),
            mock.patch.object(render_probe.shutil, "which",
                              side_effect=lambda name: "/usr/bin/soffice" if name == "soffice" else None),
            mock.patch.object(render_probe.subprocess, "run", side_effect=_fake_run),
        ):
            result = render_probe.probe()

        self.assertEqual(result["capabilities"]["h2orestart"], "yes")


class TestWslPathTranslation(unittest.TestCase):
    def test_windows_path_translated_to_mnt_form(self):
        self.assertEqual(
            render_probe.to_wsl_path(r"C:\Users\example\a.hwpx"),
            "/mnt/c/Users/example/a.hwpx",
        )

    def test_lowercases_drive_letter(self):
        self.assertEqual(
            render_probe.to_wsl_path(r"D:\reports\out.pdf"),
            "/mnt/d/reports/out.pdf",
        )

    def test_already_posix_path_left_alone(self):
        self.assertEqual(render_probe.to_wsl_path("/mnt/c/x/a.hwpx"), "/mnt/c/x/a.hwpx")


class TestWslRendererTemplate(unittest.TestCase):
    def test_template_translates_substituted_paths_inside_wsl(self):
        result = render_probe._build_renderers({
            "hancom_com": False,
            "soffice_path": None,
            "soffice_wsl": True,
            "h2orestart": "unknown",
            "rhwp_path": None,
            "rhwp_wsl": False,
            "rhwp_version": None,
        })
        self.assertEqual(len(result), 1)
        renderer = result[0]
        self.assertTrue(renderer["wsl"])
        self.assertEqual(renderer["argv"][:4], ["wsl", "-e", "bash", "-lc"])
        self.assertIn("wslpath", renderer["argv"][4])
        self.assertIn("{outdir}", renderer["argv"])
        self.assertIn("{in}", renderer["argv"])


class TestBestPdfCmd(unittest.TestCase):
    def test_none_when_no_renderers(self):
        self.assertIsNone(render_probe.best_pdf_cmd({"renderers": []}))

    def test_skips_hancom_no_argv_entry(self):
        result = {"renderers": [{"name": "hancom", "wsl": False, "argv": None}]}
        self.assertIsNone(render_probe.best_pdf_cmd(result))

    def test_picks_wsl_entry_with_runtime_path_translation(self):
        result = {"renderers": [
            {"name": "soffice_wsl", "wsl": True,
             "argv": ["wsl", "-e", "bash", "-lc", "wslpath $1",
                      "render_probe", "{outdir}", "{in}"]},
        ]}
        command = render_probe.best_pdf_cmd(result)
        self.assertEqual(command, result["renderers"][0]["argv"])
        self.assertIn("wslpath", command[4])
        self.assertIn("{outdir}", command)
        self.assertIn("{in}", command)

    def test_picks_first_usable_non_wsl_argv(self):
        result = {"renderers": [
            {"name": "hancom", "wsl": False, "argv": None},
            {"name": "soffice_local", "wsl": False, "argv": ["soffice", "--headless"]},
            {"name": "soffice_wsl", "wsl": True, "argv": ["wsl", "-e", "soffice"]},
        ]}
        self.assertEqual(render_probe.best_pdf_cmd(result), ["soffice", "--headless"])

    def test_skips_rhwp_svg_because_it_is_not_a_pdf_command(self):
        result = {"renderers": [
            {"name": "rhwp_svg", "wsl": False,
             "argv": ["rhwp", "export-svg", "{in}", "-o", "{outdir}"]},
        ]}
        self.assertIsNone(render_probe.best_pdf_cmd(result))

    def test_certified_pdf_command_outranks_advisory_soffice(self):
        certified = {
            "name": "certified_mock", "proof_grade": "certified",
            "argv": ["mock-render", "{in}", "{out}"],
        }
        result = {"renderers": [
            {"name": "soffice_local", "argv": ["soffice", "--headless"]},
            certified,
        ]}
        self.assertEqual(render_probe.best_pdf_cmd(result), certified["argv"])


class TestFormatTable(unittest.TestCase):
    def test_contains_all_capability_labels(self):
        result = {
            "capabilities": {"hancom_com": False, "soffice_path": None,
                             "soffice_wsl": False, "h2orestart": "unknown",
                             "rhwp_path": None, "rhwp_wsl": False,
                             "rhwp_version": None, "rhwp_reason": "not_found"},
            "renderers": [],
        }
        table = render_probe.format_table(result)
        for label in ("hancom_com", "soffice_path", "soffice_wsl", "h2orestart",
                      "rhwp_path", "rhwp_wsl", "rhwp_version", "rhwp_reason",
                      "renderers"):
            self.assertIn(label, table)
        self.assertIn("(none usable)", table)


class TestCli(unittest.TestCase):
    def test_main_returns_zero(self):
        with mock.patch.object(render_probe, "probe",
                               return_value={"capabilities": {"hancom_com": False,
                                                               "soffice_path": None,
                                                               "soffice_wsl": False,
                                                               "h2orestart": "unknown",
                                                               "rhwp_path": None,
                                                               "rhwp_wsl": False,
                                                               "rhwp_version": None,
                                                               "rhwp_reason": "not_found"},
                                             "renderers": []}):
            self.assertEqual(render_probe.main(["--json"]), 0)


if __name__ == "__main__":
    unittest.main()
