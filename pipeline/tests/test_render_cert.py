"""Synthetic tests for renderer measurement, certification, and checking."""
from __future__ import annotations

import hashlib
import hmac
import contextlib
import io
import importlib.util
import json
import os
import stat
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feature_extract  # noqa: E402
import diagnostic_candidate_core  # noqa: E402
import render_cert  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duplicate_json_line(raw: str, fragment: str) -> str:
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if fragment not in line:
            continue
        if line.lstrip().startswith(fragment):
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(index + 1, indent + fragment)
        else:
            lines[index] = line.replace(fragment, fragment + "," + fragment, 1)
        return "\n".join(lines) + "\n"
    raise AssertionError(f"missing JSON line {fragment!r}")


def _write_hwpx(
    path: Path, *, unknown: bool = False, run_child_unknown: bool = False,
    sections: int = 1,
) -> None:
    control = "<hp:ctrl><hp:alien/></hp:ctrl>" if unknown else ""
    run_child = "<hp:chart/>" if run_child_unknown else ""
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="urn:section" xmlns:hp="urn:paragraph">'
        '<hp:p><hp:run><hp:secPr><hp:pagePr width="59528" height="84186">'
        '<hp:margin left="5669" right="5669" top="5669" bottom="5669"/>'
        '</hp:pagePr></hp:secPr><hp:ctrl><hp:colPr colCount="1"/></hp:ctrl>'
        f'{control}{run_child}</hp:run></hp:p></hs:sec>'
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
        self.reference = self.root / "reference.pdf"
        self.reference.write_bytes(b"reference fixture")
        self.candidates = {
            "train-a": self.root / "train-a-candidate.pdf",
            "holdout-a": self.root / "holdout-a-candidate.pdf",
        }
        for entry_id, candidate in self.candidates.items():
            candidate.write_bytes(f"candidate {entry_id}".encode("ascii"))
        self.manifest = self.root / "manifest.json"
        self.profile_root = self.root / "profile"
        self.profile_root.mkdir()
        self.key_path = self.profile_root / "keys" / "render_cert.key"
        self.key_path.parent.mkdir()
        self.key_path.write_bytes(b"test-render-certificate-key-32b")
        os.chmod(self.key_path, 0o600)
        self._environment = mock.patch.dict(
            os.environ, {"RIGORLOOM_PROFILE_ROOT": str(self.profile_root)},
        )
        self._environment.start()
        self._write_manifest()

    def tearDown(self):
        self._environment.stop()
        self._tmp.cleanup()

    def _write_manifest(self):
        payload = {
            "schema_version": 1,
            "documents": [
                {
                    "id": "train-a", "split": "train", "document": "document.hwpx",
                    "generator": {"type": "sanitized-template", "source": "fixture"},
                    "features": self.features,
                    "reference_pdf": {
                        "path": "reference.pdf", "sha256": _sha256(self.reference),
                    },
                    "hancom_version": "Hancom 2024.0",
                },
                {
                    "id": "holdout-a", "split": "holdout", "document": "document.hwpx",
                    "generator": {"type": "sanitized-template", "source": "fixture"},
                    "features": self.features,
                    "reference_pdf": {
                        "path": "reference.pdf", "sha256": _sha256(self.reference),
                    },
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
                 "ok": True, "metrics": _metrics(),
                 "document": str(self.doc),
                 "document_sha256": _sha256(self.doc),
                 "reference_pdf": str(self.reference),
                 "reference_pdf_sha256": _sha256(self.reference),
                 "candidate_pdf": str(self.candidates["train-a"]),
                 "candidate_pdf_sha256": _sha256(self.candidates["train-a"])},
                {"id": "holdout-a", "split": "holdout", "features": self.features,
                 "ok": True, "metrics": _metrics(page_exact=holdout_pass),
                 "document": str(self.doc),
                 "document_sha256": _sha256(self.doc),
                 "reference_pdf": str(self.reference),
                 "reference_pdf_sha256": _sha256(self.reference),
                 "candidate_pdf": str(self.candidates["holdout-a"]),
                 "candidate_pdf_sha256": _sha256(self.candidates["holdout-a"])},
            ],
        }

    def _thresholds(self):
        return {
            "page_count_exact": True,
            "word_anchor_px": 1.0,
            "raster_changed_channel_ratio": 0.01,
        }

    def _run_private_certify(self, output: Path) -> tuple[int, str]:
        """Run the legacy certify CLI against only synthetic private inputs."""
        measurements = self.root / "private-measurements.json"
        measurements.write_text(
            json.dumps(self._measurements()), encoding="utf-8",
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = render_cert.main([
                "certify", "--measurements", str(measurements),
                "--thresholds", json.dumps(self._thresholds()),
                "--issued-at", "2026-07-20T00:00:00Z",
                "--out", str(output),
            ])
        return code, stdout.getvalue()

    def _resign(self, certificate: dict) -> None:
        certificate.pop("certificate_hmac_sha256", None)
        certificate["certificate_sha256"] = render_cert._certificate_digest(certificate)
        canonical = json.dumps(
            certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        certificate["certificate_hmac_sha256"] = hmac.new(
            self.key_path.read_bytes(), canonical, hashlib.sha256,
        ).hexdigest()

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
             "ok": True, "metrics": _metrics()},
            {"id": "small-holdout", "split": "holdout", "features": smaller,
             "ok": True, "metrics": _metrics(page_exact=False)},
            {"id": "large-train", "split": "train", "features": larger,
             "ok": True, "metrics": _metrics()},
            {"id": "large-holdout", "split": "holdout", "features": larger,
             "ok": True, "metrics": _metrics()},
        ]
        for record in measurements["documents"]:
            candidate = self.root / f"{record['id']}.pdf"
            candidate.write_bytes(record["id"].encode("ascii"))
            record.update({
                "document": str(self.doc),
                "document_sha256": _sha256(self.doc),
                "reference_pdf": str(self.reference),
                "reference_pdf_sha256": _sha256(self.reference),
                "candidate_pdf": str(candidate),
                "candidate_pdf_sha256": _sha256(candidate),
            })
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        template = manifest["documents"][0]
        manifest["documents"] = []
        for record in measurements["documents"]:
            entry = deepcopy(template)
            entry.update({
                "id": record["id"],
                "split": record["split"],
                "features": record["features"],
            })
            manifest["documents"].append(entry)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        measurements["corpus"]["manifest_sha256"] = _sha256(self.manifest)

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

    def test_public_verify_is_exact_pathless_contract(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate-public.json"
        render_cert.write_json(cert_path, certificate)

        result = render_cert.verify_certificate(
            cert_path, renderer_binary=self.binary, renderer_version="mock 1.0",
        )

        self.assertEqual(set(result), {"ok", "reason_code", "reason", "reason_codes"})
        self.assertTrue(result["ok"], result)
        self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))

    def test_public_check_is_exact_pathless_contract_on_success_and_refusal(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate-public-check.json"
        render_cert.write_json(cert_path, certificate)

        accepted = render_cert.check_document(
            self.doc, cert_path,
            renderer_binary=self.binary, renderer_version="mock 1.0",
        )
        refused = render_cert.check_document(
            self.root / "missing-document.hwpx", cert_path,
            renderer_binary=self.binary, renderer_version="mock 1.0",
        )
        for result in (accepted, refused):
            self.assertEqual(
                set(result), {"ok", "reason_code", "reason", "reason_codes", "eligible"},
            )
            self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))
        self.assertTrue(accepted["eligible"], accepted)
        self.assertFalse(refused["eligible"], refused)

    def test_cli_operation_failed_is_fixed_and_pathless_in_stdout_and_out(self):
        marker = self.root / "private-operation-marker" / "missing-measurements.json"
        out = self.root / "public-result.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = render_cert.main([
                "certify", "--measurements", str(marker),
                "--thresholds", json.dumps(self._thresholds()),
                "--out", str(out),
            ])
        self.assertEqual(code, 3)
        emitted = json.loads(stdout.getvalue())
        persisted = json.loads(out.read_text(encoding="utf-8"))
        for result in (emitted, persisted):
            self.assertEqual(set(result), {"ok", "reason_code", "reason", "reason_codes"})
            self.assertEqual(result["reason_code"], "operation_failed")
            self.assertNotIn("error", result)
            self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))
        self.assertNotIn(str(self.root), stdout.getvalue())

    def test_cli_check_is_exact_pathless_contract_in_stdout_and_out(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate-cli-check.json"
        render_cert.write_json(cert_path, certificate)
        for label, document in (
            ("accepted", self.doc),
            ("refused", self.root / "missing-cli-document.hwpx"),
        ):
            with self.subTest(label=label):
                out = self.root / f"{label}-result.json"
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = render_cert.main([
                        "check", str(document), str(cert_path),
                        "--renderer-binary", str(self.binary),
                        "--renderer-version", "mock 1.0", "--out", str(out),
                    ])
                expected_code = 0 if label == "accepted" else 3
                self.assertEqual(code, expected_code)
                emitted = json.loads(stdout.getvalue())
                persisted = json.loads(out.read_text(encoding="utf-8"))
                for result in (emitted, persisted):
                    self.assertEqual(
                        set(result), {"ok", "reason_code", "reason", "reason_codes", "eligible"},
                    )
                    self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))
                self.assertEqual(emitted, persisted)

    def test_private_certify_requires_precreated_canonical_parent(self):
        output = self.root / "private-output" / "certificate.json"

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertFalse(output.parent.exists())
        self.assertFalse(output.exists())

    def test_private_certify_refuses_preexisting_target_and_preserves_bytes(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        foreign = b"FOREIGN-CANONICAL-TARGET"
        output.write_bytes(foreign)

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertEqual(output.read_bytes(), foreign)
        self.assertEqual(output.stat().st_nlink, 1)

    def test_private_certify_refuses_leaf_symlink_without_following_or_replacing(self):
        parent = self.root / "private-output"
        parent.mkdir()
        referent = parent / "foreign.json"
        output = parent / "certificate.json"
        referent.write_bytes(b"FOREIGN-REFERENT")
        try:
            output.symlink_to(referent)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertTrue(output.is_symlink())
        self.assertEqual(output.resolve(), referent.resolve())
        self.assertEqual(referent.read_bytes(), b"FOREIGN-REFERENT")

    def test_private_certify_refuses_hardlink_target_without_breaking_alias(self):
        parent = self.root / "private-output"
        parent.mkdir()
        alias = parent / "foreign-alias.json"
        output = parent / "certificate.json"
        alias.write_bytes(b"FOREIGN-HARDLINK")
        try:
            os.link(alias, output)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"hardlink unavailable: {exc}")

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertEqual(alias.read_bytes(), b"FOREIGN-HARDLINK")
        self.assertEqual(output.read_bytes(), b"FOREIGN-HARDLINK")
        self.assertEqual(output.stat().st_nlink, 2)

    def test_private_certify_refuses_parent_symlink_without_external_write(self):
        real_parent = self.root / "private-output-real"
        alias_parent = self.root / "private-output-alias"
        external = self.root / "outside-private-output"
        real_parent.mkdir()
        external.mkdir()
        try:
            alias_parent.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")
        output = alias_parent / "certificate.json"

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertTrue(alias_parent.is_symlink())
        self.assertFalse((external / "certificate.json").exists())
        self.assertFalse(output.exists())

    def test_private_certify_refuses_nested_parent_ancestor_symlink(self):
        """A regular leaf below an interior alias must not redirect output."""
        external = self.root / "outside-private-output"
        external_child = external / "nested"
        alias_parent = self.root / "private-output-alias"
        external_child.mkdir(parents=True)
        try:
            alias_parent.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")
        output = alias_parent / "nested" / "certificate.json"

        code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertTrue(alias_parent.is_symlink())
        self.assertFalse((external_child / "certificate.json").exists())
        self.assertFalse(output.exists())

    def test_private_certify_target_identity_failure_rolls_back_owned_target(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_identity = render_cert._private_bound_identity
        target_calls = 0

        def fail_first_target_identity(binding, name):
            nonlocal target_calls
            if name == output.name:
                target_calls += 1
                if target_calls == 1:
                    raise diagnostic_candidate_core.CoreError(
                        "synthetic target identity failure",
                    )
            return real_identity(binding, name)

        with mock.patch.object(
            render_cert, "_private_bound_identity",
            side_effect=fail_first_target_identity,
        ):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertFalse(output.exists())
        self.assertEqual(list(parent.glob(".*.tmp")), [])
        self.assertEqual(list(parent.glob(".*.rollback.*")), [])

    def test_private_certify_positive_output_is_exact_regular_one_link_file(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"

        code, stdout = self._run_private_certify(output)

        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        self.assertFalse(output.is_symlink())
        self.assertEqual(output.stat().st_nlink, 1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")),
                         json.loads(stdout))
        self.assertEqual(list(parent.glob(".*.tmp")), [])

    def test_private_certify_parent_swap_cannot_redirect_or_leave_temp(self):
        parent = self.root / "private-output"
        moved_parent = self.root / "private-output-moved"
        external = self.root / "outside-private-output"
        parent.mkdir()
        external.mkdir()
        output = parent / "certificate.json"
        link_called = False
        swap_succeeded = False
        real_link = render_cert.os.link

        def swap_parent_then_link(*args, **kwargs):
            nonlocal link_called, swap_succeeded
            link_called = True
            try:
                parent.rename(moved_parent)
                try:
                    parent.symlink_to(external, target_is_directory=True)
                except (OSError, NotImplementedError):
                    moved_parent.rename(parent)
                    raise
                swap_succeeded = True
            except OSError:
                return real_link(*args, **kwargs)
            return real_link(*args, **kwargs)

        with mock.patch.object(render_cert.os, "link",
                               side_effect=swap_parent_then_link):
            code, _ = self._run_private_certify(output)

        try:
            self.assertTrue(link_called)
            if swap_succeeded:
                self.assertEqual(code, 3)
                self.assertFalse((external / "certificate.json").exists())
                self.assertFalse((moved_parent / "certificate.json").exists())
                self.assertEqual(list(self.root.rglob("*.tmp")), [])
            else:
                # A held Windows directory handle legitimately blocks the
                # swap; normal publication remains canonical.
                self.assertEqual(code, 0)
                self.assertTrue(output.is_file())
                self.assertFalse(output.is_symlink())
                self.assertEqual(output.stat().st_nlink, 1)
        finally:
            if parent.is_symlink():
                parent.unlink()
            if moved_parent.exists():
                moved_parent.rename(parent)

    def test_private_certify_precommit_foreign_replacement_is_preserved(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_link = render_cert.os.link

        def foreign_then_link(*args, **kwargs):
            output.write_bytes(b"FOREIGN-BEFORE-COMMIT")
            return real_link(*args, **kwargs)

        with mock.patch.object(render_cert.os, "link",
                               side_effect=foreign_then_link):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertEqual(output.read_bytes(), b"FOREIGN-BEFORE-COMMIT")
        self.assertEqual(output.stat().st_nlink, 1)

    def test_private_certify_postpublish_foreign_replacement_is_preserved(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_link = render_cert.os.link
        real_replace = render_cert.os.replace

        def link_then_foreign(*args, **kwargs):
            result = real_link(*args, **kwargs)
            foreign = parent / "foreign-after.json"
            foreign.write_bytes(b"FOREIGN-AFTER-COMMIT")
            real_replace(foreign, output)
            return result

        with mock.patch.object(render_cert.os, "link",
                               side_effect=link_then_foreign):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertEqual(output.read_bytes(), b"FOREIGN-AFTER-COMMIT")
        self.assertEqual(output.stat().st_nlink, 1)

    def test_private_certify_link_then_raise_rolls_back_owned_target(self):
        """A post-link exception cannot strand the freshly linked receipt."""
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_link = render_cert.os.link

        def link_then_raise(*args, **kwargs):
            real_link(*args, **kwargs)
            raise OSError("synthetic post-link failure")

        with mock.patch.object(render_cert.os, "link",
                               side_effect=link_then_raise):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertFalse(output.exists())
        self.assertEqual(list(parent.glob(".*.tmp")), [])
        self.assertEqual(list(parent.glob(".*.rollback.*")), [])

    def test_private_certify_rollback_capture_unlink_race_preserves_foreign(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_capture_bound = render_cert._private_capture_bound
        quarantine_captures = 0

        def capture_then_foreign(binding, name):
            nonlocal quarantine_captures
            result = real_capture_bound(binding, name)
            if name.startswith(f".{output.name}.rollback."):
                quarantine_captures += 1
                if quarantine_captures == 2:
                    (binding.path / name).write_bytes(b"FOREIGN-ROLLBACK-RACE")
            return result

        def force_publish_failure(*args, **kwargs):
            raise diagnostic_candidate_core.CoreError("synthetic-final-failure")

        with mock.patch.object(render_cert, "_private_capture_bound",
                               side_effect=capture_then_foreign), \
             mock.patch.object(render_cert, "_private_validate_target",
                                side_effect=force_publish_failure):
            with self.assertRaises(diagnostic_candidate_core.CoreError):
                render_cert._write_private_artifact_json(
                    output, {"private": "rollback-race"},
                )

        self.assertEqual(output.read_bytes(), b"FOREIGN-ROLLBACK-RACE")
        self.assertEqual(output.stat().st_nlink, 1)

    def test_private_certify_source_temp_replacement_preserves_foreign_temp(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_link = render_cert.os.link

        def replace_source_then_link(*args, **kwargs):
            source = Path(args[0])
            if not source.is_absolute():
                source = parent / source
            source.write_bytes(b"FOREIGN-STAGED-TEMP")
            return real_link(*args, **kwargs)

        with mock.patch.object(render_cert.os, "link",
                               side_effect=replace_source_then_link):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertFalse(output.exists())
        staged = list(parent.glob(".*.tmp"))
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].read_bytes(), b"FOREIGN-STAGED-TEMP")

    def test_private_certify_final_rebind_same_size_mutation_is_refused(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        payload = {"private": "final-rebind"}
        replacement = b"X" * len(render_cert._private_json_bytes(payload))
        real_validate = render_cert._private_validate_target
        real_lstat = Path.lstat
        mutated = False

        def validate_then_mutate(binding, name, expected, raw, **kwargs):
            nonlocal mutated
            if kwargs.get("lexical_path") != output:
                return real_validate(binding, name, expected, raw, **kwargs)

            def lstat_then_mutate(path):
                nonlocal mutated
                result = real_lstat(path)
                if path == output and not mutated:
                    output.write_bytes(replacement)
                    mutated = True
                return result

            # Scope the mutation to the final lexical validation.  POSIX and
            # Windows take different earlier identity paths, so counting raw
            # os.stat calls made this regression miss the Linux seam in CI.
            with mock.patch.object(Path, "lstat", new=lstat_then_mutate):
                return real_validate(binding, name, expected, raw, **kwargs)

        with mock.patch.object(
                render_cert, "_private_validate_target",
                side_effect=validate_then_mutate):
            with self.assertRaises(diagnostic_candidate_core.CoreError):
                render_cert._write_private_artifact_json(output, payload)

        self.assertTrue(mutated)
        self.assertEqual(output.read_bytes(), replacement)

    def test_private_certify_final_lexical_capture_rejects_parent_swap(self):
        parent = self.root / "private-output"
        moved_parent = self.root / "private-output-moved"
        external = self.root / "outside-private-output"
        parent.mkdir()
        external.mkdir()
        output = parent / "certificate.json"
        real_capture_bound = render_cert._private_capture_bound
        swap_succeeded = False
        swapped = False

        def swap_before_lexical_capture(binding, name, **kwargs):
            nonlocal swap_succeeded, swapped
            lexical_path = kwargs.get("lexical_path")
            if lexical_path == output and not swapped:
                swapped = True
                try:
                    parent.rename(moved_parent)
                    parent.symlink_to(external, target_is_directory=True)
                    swap_succeeded = True
                except (OSError, NotImplementedError):
                    if moved_parent.exists() and not parent.exists():
                        moved_parent.rename(parent)
            return real_capture_bound(binding, name, **kwargs)

        try:
            with mock.patch.object(
                render_cert, "_private_capture_bound",
                side_effect=swap_before_lexical_capture,
            ):
                if os.name == "nt":
                    code, _ = self._run_private_certify(output)
                else:
                    with self.assertRaises(diagnostic_candidate_core.CoreError):
                        render_cert._write_private_artifact_json(
                            output, {"private": "final-parent-swap"},
                        )
            self.assertTrue(swapped)
            if swap_succeeded:
                self.assertFalse((external / "certificate.json").exists())
                self.assertFalse((moved_parent / "certificate.json").exists())
            else:
                self.assertTrue(output.is_file())
                self.assertEqual(output.stat().st_nlink, 1)
        finally:
            if parent.is_symlink():
                parent.unlink()
            if moved_parent.exists():
                moved_parent.rename(parent)

    def test_private_certify_partial_precommit_failure_cleans_owned_temp(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"

        def partial_stage(binding, name, data):
            fd = binding.open_file(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
            )
            before = os.fstat(fd)
            owned = (
                getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
                0, getattr(before, "st_mtime_ns", 0),
                getattr(before, "st_ctime_ns", 0), "",
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"PARTIAL-PRIVATE-TEMP")
                stream.flush()
            error = diagnostic_candidate_core.CoreError(
                "synthetic partial write",
            )
            error.private_owned_identity = owned
            raise error

        with mock.patch.object(
            render_cert, "_private_stage_bytes", new=partial_stage,
        ):
            code, _ = self._run_private_certify(output)

        self.assertEqual(code, 3)
        self.assertFalse(output.exists())
        self.assertEqual(list(parent.glob(".*.tmp")), [])

    def test_private_certify_postcommit_cleanup_failure_keeps_success(self):
        parent = self.root / "private-output"
        parent.mkdir()
        output = parent / "certificate.json"
        real_unlink = render_cert.os.unlink

        def unlink_then_raise(*args, **kwargs):
            result = real_unlink(*args, **kwargs)
            raise OSError("synthetic postcommit cleanup failure")

        with mock.patch.object(render_cert.os, "unlink",
                               side_effect=unlink_then_raise):
            code, stdout = self._run_private_certify(output)

        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        self.assertEqual(output.stat().st_nlink, 1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")),
                         json.loads(stdout))

    def test_generic_write_json_still_overwrites_for_legacy_callers(self):
        target = self.root / "legacy.json"
        target.write_text("FOREIGN", encoding="utf-8")

        render_cert.write_json(target, {"legacy": True})

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"legacy": True})

    def test_private_measure_and_certify_routes_use_dedicated_publisher(self):
        calls = []

        def fake_private_publisher(path, payload):
            calls.append(Path(path))
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        measure_output = self.root / "measure-private" / "measurements.json"
        measure_output.parent.mkdir()
        with mock.patch.object(
            render_cert, "_write_private_artifact_json",
            side_effect=fake_private_publisher, create=True,
        ), mock.patch.object(
            render_cert, "measure_corpus",
            return_value={"documents": [{"ok": True}]},
        ):
            measure_code = render_cert.main([
                "measure", "--renderer", "mock", "--corpus",
                str(self.manifest), "--out", str(measure_output),
            ])

        self.assertEqual(measure_code, 0)
        self.assertEqual(calls, [measure_output])

        calls.clear()
        measurements = self.root / "route-measurements.json"
        measurements.write_text(
            json.dumps(self._measurements()), encoding="utf-8",
        )
        certify_output = self.root / "certify-private" / "certificate.json"
        certify_output.parent.mkdir()
        with mock.patch.object(
            render_cert, "_write_private_artifact_json",
            side_effect=fake_private_publisher, create=True,
        ):
            certify_code = render_cert.main([
                "certify", "--measurements", str(measurements),
                "--thresholds", json.dumps(self._thresholds()),
                "--out", str(certify_output),
            ])

        self.assertEqual(certify_code, 0)
        self.assertEqual(calls, [certify_output])

    def test_direct_and_consumer_loaders_reject_duplicate_certificate_keys(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "duplicate-certificate.json"
        raw = json.dumps(certificate, ensure_ascii=False, indent=2) + "\n"
        cert_path.write_text(_duplicate_json_line(
            raw, '"schema_version": 1,'), encoding="utf-8")

        with self.assertRaises(ValueError):
            render_cert._read_json(cert_path)

        result = render_cert.verify_certificate(
            cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_invalid_json")
        self.assertEqual(set(result), {"ok", "reason_code", "reason", "reason_codes"})

    def test_consumer_rejects_conflicting_duplicate_with_valid_last_value(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "conflicting-duplicate-certificate.json"
        raw = json.dumps(certificate, ensure_ascii=False, indent=2) + "\n"
        needle = '  "renderer_id": "mock",'
        self.assertEqual(raw.count(needle), 1)
        raw = raw.replace(
            needle, '  "renderer_id": "forged",\n' + needle, 1)
        cert_path.write_text(raw, encoding="utf-8")

        result = render_cert.verify_certificate(
            cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_invalid_json")

    def test_consumer_rejects_forged_first_valid_last_hmac_duplicate(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "shadowed-hmac-certificate.json"
        lines = (json.dumps(certificate, ensure_ascii=False, indent=2)
                 + "\n").splitlines()
        for index, line in enumerate(lines):
            if line.lstrip().startswith('"certificate_hmac_sha256":'):
                indent = line[:len(line) - len(line.lstrip())]
                valid_line = line
                forged_line = (
                    indent + '"certificate_hmac_sha256": "' + "f" * 64
                    + '",')
                lines[index:index + 1] = [forged_line, valid_line]
                break
        else:
            raise AssertionError("certificate HMAC member missing")
        cert_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = render_cert.verify_certificate(
            cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_invalid_json")

    def test_unique_key_reordering_and_whitespace_remain_accepted(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "reordered-certificate.json"
        reordered = {
            key: certificate[key] for key in reversed(certificate)
        }
        cert_path.write_text(
            "\n  \n" + json.dumps(reordered, ensure_ascii=False, indent=4)
            + "\n\n",
            encoding="utf-8",
        )
        result = render_cert.verify_certificate(
            cert_path,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )
        self.assertTrue(result["ok"], result)

    def test_cli_check_rejects_duplicate_nested_certificate_key(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "duplicate-nested-certificate.json"
        raw = json.dumps(certificate, ensure_ascii=False, indent=2) + "\n"
        cert_path.write_text(_duplicate_json_line(
            raw, '"page_count_exact": true,'), encoding="utf-8")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = render_cert.main([
                "check", str(self.doc), str(cert_path),
                "--renderer-binary", str(self.binary),
                "--renderer-version", "mock 1.0",
            ])
        self.assertEqual(code, 3)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["reason_code"], "certificate_invalid_json")

    def test_inline_thresholds_loader_rejects_duplicate_key(self):
        args = types.SimpleNamespace(
            thresholds='{"page_count_exact":true,"page_count_exact":false}',
            word_anchor_px=None,
            raster_changed_channel_ratio=None,
            min_matched_unique_words=None,
        )
        with self.assertRaises(ValueError):
            render_cert._threshold_args(args)

    def test_cli_certify_rejects_duplicate_measurement_threshold_inputs(self):
        measurement_path = self.root / "duplicate-measurements.json"
        raw_measurements = (
            json.dumps(self._measurements(), ensure_ascii=False, indent=2)
            + "\n"
        )
        needle = '  "schema_version": 1,'
        self.assertEqual(raw_measurements.count(needle), 1)
        measurement_path.write_text(
            raw_measurements.replace(
                needle, '  "schema_version": 999,\n' + needle, 1),
            encoding="utf-8",
        )
        threshold_path = self.root / "duplicate-thresholds.json"
        threshold_path.write_text(
            '{"page_count_exact":false,"page_count_exact":true}',
            encoding="utf-8",
        )
        cases = (
            (
                ["--measurements", str(measurement_path),
                 "--thresholds", json.dumps(self._thresholds())],
                "measurement_file",
            ),
            (
                ["--measurements", str(self.root / "missing.json"),
                 "--thresholds", str(threshold_path)],
                "threshold_file",
            ),
            (
                ["--measurements", str(self.root / "missing.json"),
                 "--thresholds",
                 '{"page_count_exact":true,"page_count_exact":false}'],
                "inline_thresholds",
            ),
        )
        for args, label in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = render_cert.main(["certify", *args])
                self.assertEqual(code, 3)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["ok"], payload)
                self.assertEqual(payload["reason_code"], "operation_failed")
                self.assertEqual(
                    set(payload), {"ok", "reason_code", "reason", "reason_codes"},
                )
                self.assertNotIn(str(self.root), stdout.getvalue())

    def test_manifest_loader_rejects_duplicate_top_level_or_nested_key(self):
        for fragment in ('"schema_version": 1', '"id": "train-a"'):
            with self.subTest(fragment=fragment):
                raw = self.manifest.read_text(encoding="utf-8")
                self.manifest.write_text(
                    _duplicate_json_line(raw, fragment), encoding="utf-8")
                with self.assertRaises(ValueError):
                    render_cert.load_manifest(self.manifest)
                self._write_manifest()

    def test_manifest_document_id_refuses_unsafe_path_segment_before_work_dir(self):
        for index, bad_id in enumerate(
                ("../escape", "nested/id", ".", "..", "C:\\escape")):
            with self.subTest(bad_id=bad_id):
                payload = json.loads(self.manifest.read_text(encoding="utf-8"))
                payload["documents"][0]["id"] = bad_id
                self.manifest.write_text(json.dumps(payload), encoding="utf-8")
                work_dir = self.root / f"measure-work-unsafe-{index}"
                escaped = self.root / "escape"
                nested = work_dir / "nested"
                drive_target = Path(
                    f"{self.root.drive}\\t159-unsafe-drive-{index}"
                )
                before_drive = drive_target.exists()
                try:
                    with self.assertRaises(ValueError):
                        render_cert.measure_corpus(
                            "mock", self.manifest, work_dir=work_dir,
                            renderer_binary=self.binary,
                            renderer_version="mock 1.0",
                            renderer_argv=[str(self.binary), "{in}", "{out}"],
                            render_callback=lambda entry, source, candidate: None,
                        )
                    self.assertFalse(work_dir.exists())
                    self.assertFalse(escaped.exists())
                    self.assertFalse(nested.exists())
                    self.assertEqual(drive_target.exists(), before_drive)
                finally:
                    self._write_manifest()

    def test_resolve_renderer_refuses_argv_zero_not_matching_configured_binary(self):
        other = self.root / "other-renderer.bin"
        other.write_bytes(b"different renderer")

        with self.assertRaises(ValueError):
            render_cert.resolve_renderer(
                "mock", renderer_binary=self.binary,
                renderer_argv=[str(other), "{in}", "{out}"],
                renderer_version="mock 1.0",
            )

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
        self._resign(certificate)
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

    def test_widened_envelope_with_recomputed_self_hash_and_absent_or_stale_hmac_is_refused(self):
        original = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        self._resign(original)

        absent = deepcopy(original)
        absent["envelope"][0]["features"]["sections"] += 100
        absent.pop("certificate_hmac_sha256")
        absent["certificate_sha256"] = render_cert._certificate_digest(absent)

        stale = deepcopy(original)
        stale["envelope"][0]["features"]["sections"] += 100
        stale["certificate_sha256"] = render_cert._certificate_digest(stale)

        for label, certificate, reason in (
            ("absent", absent, "certificate_hmac_missing"),
            ("stale", stale, "certificate_hmac_mismatch"),
        ):
            with self.subTest(label=label):
                result = render_cert.verify_certificate(
                    certificate,
                    renderer_binary=self.binary,
                    renderer_version="mock 1.0",
                )
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason_code"], reason)

    def test_envelope_must_rederive_from_manifest_features_and_measurements(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["envelope"][0]["features"]["sections"] += 1
        self._resign(certificate)

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_envelope_mismatch")

    def test_embedded_measurement_hash_is_reverified(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["measurement_records"][0]["metrics"]["raster"][
            "changed_channel_ratio"
        ] = 0.5
        self._resign(certificate)

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "measurement_hash_mismatch")

    def test_raised_threshold_with_recomputed_self_hash_and_stale_hmac_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["thresholds"]["word_anchor_px"] = 9999.0
        certificate["certificate_sha256"] = render_cert._certificate_digest(certificate)

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_hmac_mismatch")

    def test_widened_envelope_signed_with_different_key_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        certificate["envelope"][0]["features"]["tables"] = 999
        certificate.pop("certificate_hmac_sha256", None)
        certificate["certificate_sha256"] = render_cert._certificate_digest(certificate)
        canonical = json.dumps(
            certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        certificate["certificate_hmac_sha256"] = hmac.new(
            b"attacker-controlled-key-32-bytes!", canonical, hashlib.sha256,
        ).hexdigest()

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_hmac_mismatch")

    def test_fabricated_corpus_without_valid_key_signature_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        fabricated = self.root / "fabricated-manifest.json"
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        for index, entry in enumerate(payload["documents"]):
            entry["document"] = f"missing-corpus-{index}.hwpx"
            entry["reference_pdf"]["path"] = f"missing-reference-{index}.pdf"
        fabricated.write_text(json.dumps(payload), encoding="utf-8")
        certificate["corpus_manifest_path"] = str(fabricated)
        certificate["corpus_manifest_hash"] = _sha256(fabricated)
        certificate.pop("certificate_hmac_sha256", None)
        certificate["certificate_sha256"] = render_cert._certificate_digest(certificate)

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_hmac_missing")

    def test_missing_operator_key_at_verify_is_refused(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        self.key_path.unlink()

        result = render_cert.verify_certificate(
            certificate,
            renderer_binary=self.binary,
            renderer_version="mock 1.0",
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason_code"], "certificate_key_missing")

    def test_issue_generates_restricted_operator_key_and_hmac(self):
        self.key_path.unlink()

        with mock.patch.object(
            render_cert.receipt_sign.subprocess, "run",
            return_value=mock.Mock(returncode=0),
        ) as restrict_acl:
            certificate = render_cert.issue_certificate(
                self._measurements(), self._thresholds(),
                issued_at="2026-07-20T00:00:00Z",
            )

        self.assertTrue(self.key_path.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.key_path.stat().st_mode), 0o600)
            restrict_acl.assert_not_called()
        else:
            restrict_acl.assert_called_once()
        self.assertEqual(len(self.key_path.read_bytes()), 32)
        self.assertRegex(certificate["certificate_hmac_sha256"], r"^[0-9a-f]{64}$")

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

    def test_unknown_feature_canary_is_not_echoed_by_public_check(self):
        certificate = render_cert.issue_certificate(
            self._measurements(), self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )
        cert_path = self.root / "certificate-canary.json"
        render_cert.write_json(cert_path, certificate)
        canary = "unknown:PRIVATE_CANARY"
        with mock.patch.object(
            render_cert.feature_extract,
            "extract_feature_counts",
            return_value={canary: 1},
        ):
            result = render_cert.check_document(
                self.doc, cert_path,
                renderer_binary=self.binary, renderer_version="mock 1.0",
            )
        self.assertEqual(
            set(result), {"ok", "reason_code", "reason", "reason_codes", "eligible"},
        )
        self.assertFalse(result["eligible"], result)
        self.assertEqual(result["reason_code"], "unknown_feature")
        self.assertNotIn(canary, json.dumps(result, ensure_ascii=False))

    def test_unknown_run_child_is_never_certifiable(self):
        unknown_doc = self.root / "unknown-run-child.hwpx"
        _write_hwpx(unknown_doc, run_child_unknown=True)
        unknown_features = feature_extract.extract_feature_counts(unknown_doc)
        self.assertEqual(unknown_features["unknown:chart"], 1)

        measurements = self._measurements()
        for record in measurements["documents"]:
            record["features"] = unknown_features
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        for entry in manifest["documents"]:
            entry["features"] = unknown_features
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        measurements["corpus"]["manifest_sha256"] = _sha256(self.manifest)

        certificate = render_cert.issue_certificate(
            measurements, self._thresholds(),
            issued_at="2026-07-20T00:00:00Z",
        )

        self.assertEqual(certificate["envelope"], [])

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
    def test_measure_refuses_preexisting_stale_candidate_generation(self):
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
        work_dir = self.root / "stale-measure-work"
        stale_dir = work_dir / "train-a"
        stale_dir.mkdir(parents=True)
        stale = stale_dir / "candidate.pdf"
        shutil.copyfile(reference, stale)

        measured = render_cert.measure_corpus(
            "mock", self.manifest, work_dir=work_dir,
            renderer_binary=self.binary, renderer_version="mock 1.0",
            renderer_argv=[str(self.binary), "{in}", "{out}"],
            render_callback=lambda entry, source, candidate: None,
            dpi=72,
        )

        self.assertFalse(measured["documents"][0]["ok"])
        self.assertIn(
            "renderer_output_stale",
            measured["documents"][0]["reason_codes"],
        )

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_refuses_source_mutation_during_render(self):
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

        def mutate_source(entry, source, candidate):
            self.doc.write_bytes(self.doc.read_bytes() + b"source-generation-mutation")
            return reference

        measured = render_cert.measure_corpus(
            "mock", self.manifest, work_dir=self.root / "source-mutation-work",
            renderer_binary=self.binary, renderer_version="mock 1.0",
            renderer_argv=[str(self.binary), "{in}", "{out}"],
            render_callback=mutate_source, dpi=72,
        )

        self.assertFalse(measured["documents"][0]["ok"])
        self.assertIn(
            "document_changed",
            measured["documents"][0]["reason_codes"],
        )

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_refuses_reference_mutation_during_render(self):
        import fitz

        reference = self.root / "reference.pdf"
        replacement = self.root / "replacement-reference.pdf"
        candidate_source = self.root / "candidate-source.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 72), "alpha beta gamma")
        document.save(reference)
        document.close()
        document = fitz.open()
        document.new_page().insert_text((100, 72), "alpha beta gamma")
        document.save(replacement)
        document.close()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        for entry in manifest["documents"]:
            entry["reference_pdf"]["sha256"] = _sha256(reference)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

        def mutate_reference(entry, source, candidate):
            shutil.copyfile(reference, candidate_source)
            shutil.copyfile(replacement, reference)
            return candidate_source

        measured = render_cert.measure_corpus(
            "mock", self.manifest, work_dir=self.root / "reference-mutation-work",
            renderer_binary=self.binary, renderer_version="mock 1.0",
            renderer_argv=[str(self.binary), "{in}", "{out}"],
            render_callback=mutate_reference, dpi=72,
        )

        self.assertFalse(measured["documents"][0]["ok"])
        self.assertIn(
            "reference_pdf_changed",
            measured["documents"][0]["reason_codes"],
        )

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_uses_owned_snapshots_for_feature_renderer_and_metrics(self):
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

        work_dir = self.root / "owned-snapshot-work"
        live_candidate = work_dir / "train-a" / "candidate.pdf"
        original_metrics = render_cert.compare_pdf_metrics
        seen: dict[str, object] = {"metrics_candidate_paths": []}

        def extract_features(path):
            source = Path(path)
            seen["feature_path"] = source
            seen["feature_bytes"] = source.read_bytes()
            return self.features

        def render(entry, source, candidate):
            source = Path(source)
            seen["renderer_path"] = source
            seen["renderer_bytes"] = source.read_bytes()
            shutil.copyfile(reference, candidate)
            return candidate

        def compare(reference_path, candidate_path, *, dpi):
            reference_path = Path(reference_path)
            candidate_path = Path(candidate_path)
            seen["metrics_reference_path"] = reference_path
            seen["metrics_reference_bytes"] = reference_path.read_bytes()
            seen["metrics_candidate_paths"].append(candidate_path)
            seen.setdefault("metrics_candidate_bytes", []).append(
                candidate_path.read_bytes()
            )
            return original_metrics(reference_path, candidate_path, dpi=dpi)

        with (
            mock.patch.object(
                render_cert.feature_extract, "extract_feature_counts",
                side_effect=extract_features,
            ),
            mock.patch.object(
                render_cert, "compare_pdf_metrics", side_effect=compare,
            ),
        ):
            measured = render_cert.measure_corpus(
                "mock", self.manifest, work_dir=work_dir,
                renderer_binary=self.binary, renderer_version="mock 1.0",
                renderer_argv=[str(self.binary), "{in}", "{out}"],
                render_callback=render, dpi=72,
            )

        self.assertTrue(all(record["ok"] for record in measured["documents"]))
        original_document_bytes = self.doc.read_bytes()
        self.assertNotEqual(seen["feature_path"], self.doc)
        self.assertEqual(seen["feature_bytes"], original_document_bytes)
        self.assertNotEqual(seen["renderer_path"], self.doc)
        self.assertEqual(seen["renderer_bytes"], original_document_bytes)
        self.assertNotEqual(seen["metrics_reference_path"], reference)
        self.assertEqual(seen["metrics_reference_bytes"], reference.read_bytes())
        self.assertTrue(seen["metrics_candidate_paths"])
        self.assertTrue(all(
            path not in {
                live_candidate,
                work_dir / "holdout-a" / "candidate.pdf",
            }
            for path in seen["metrics_candidate_paths"]
        ))
        self.assertTrue(all(
            raw == reference.read_bytes()
            for raw in seen["metrics_candidate_bytes"]
        ))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_preserves_source_basename_for_renderer_output(self):
        import fitz

        reference = self.root / "reference.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 72), "alpha beta gamma")
        document.save(reference)
        document.close()
        source = self.root / "source-name.hwpx"
        shutil.copyfile(self.doc, source)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["documents"][0]["document"] = source.name
        for entry in manifest["documents"]:
            entry["reference_pdf"]["sha256"] = _sha256(reference)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

        def fake_run(command, **kwargs):
            source_path = Path(command[2])
            output_dir = Path(command[4])
            shutil.copyfile(reference, output_dir / f"{source_path.stem}.pdf")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(render_cert.subprocess, "run", side_effect=fake_run):
            measured = render_cert.measure_corpus(
                "mock", self.manifest, work_dir=self.root / "basename-work",
                renderer_binary=self.binary, renderer_version="mock 1.0",
                renderer_argv=[str(self.binary), "--emit", "{in}", "--outdir", "{outdir}"],
                dpi=72,
            )

        self.assertTrue(all(record["ok"] for record in measured["documents"]))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_metrics_live_candidate_mutation_restore_uses_owned_snapshot(self):
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

        work_dir = self.root / "metrics-restore-work"
        live_candidate = work_dir / "train-a" / "candidate.pdf"
        original_metrics = render_cert.compare_pdf_metrics
        mutated = {"done": False}

        def render(entry, source, candidate):
            shutil.copyfile(reference, candidate)
            return candidate

        def compare(reference_path, candidate_path, *, dpi):
            candidate_path = Path(candidate_path)
            self.assertNotEqual(candidate_path, live_candidate)
            if not mutated["done"]:
                mutated["done"] = True
                raw = live_candidate.read_bytes()
                stat_result = live_candidate.stat()
                live_candidate.write_bytes(raw + b"temporary-metric-mutation")
                live_candidate.write_bytes(raw)
                os.utime(
                    live_candidate,
                    ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns),
                )
            return original_metrics(reference_path, candidate_path, dpi=dpi)

        with mock.patch.object(render_cert, "compare_pdf_metrics", side_effect=compare):
            measured = render_cert.measure_corpus(
                "mock", self.manifest, work_dir=work_dir,
                renderer_binary=self.binary, renderer_version="mock 1.0",
                renderer_argv=[str(self.binary), "{in}", "{out}"],
                render_callback=render, dpi=72,
            )

        self.assertTrue(mutated["done"])
        self.assertTrue(all(record["ok"] for record in measured["documents"]))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_measure_refuses_nonrestored_candidate_mutation_during_metrics(self):
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

        work_dir = self.root / "metrics-drift-work"
        live_candidate = work_dir / "train-a" / "candidate.pdf"
        original_metrics = render_cert.compare_pdf_metrics

        def render(entry, source, candidate):
            shutil.copyfile(reference, candidate)
            return candidate

        replacement = self.root / "metrics-drift-replacement.pdf"
        replacement_doc = fitz.open()
        replacement_doc.new_page().insert_text((140, 72), "different content")
        replacement_doc.save(replacement)
        replacement_doc.close()

        def compare(reference_path, candidate_path, *, dpi):
            shutil.copyfile(replacement, live_candidate)
            return original_metrics(reference_path, candidate_path, dpi=dpi)

        with mock.patch.object(render_cert, "compare_pdf_metrics", side_effect=compare):
            measured = render_cert.measure_corpus(
                "mock", self.manifest, work_dir=work_dir,
                renderer_binary=self.binary, renderer_version="mock 1.0",
                renderer_argv=[str(self.binary), "{in}", "{out}"],
                render_callback=render, dpi=72,
            )

        self.assertFalse(measured["documents"][0]["ok"])

    def test_issue_refuses_manifest_drift_before_self_hash_and_cli_has_no_certificate_output(self):
        measurements = self._measurements()
        original_key_loader = render_cert.receipt_sign.load_operator_key

        def key_then_mutate(*args, **kwargs):
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
            payload["documents"][0]["generator"]["source"] = "manifest-drift-before-hmac"
            self.manifest.write_text(json.dumps(payload), encoding="utf-8")
            return original_key_loader(*args, **kwargs)

        with mock.patch.object(
            render_cert.receipt_sign, "load_operator_key", side_effect=key_then_mutate,
        ):
            with self.assertRaisesRegex(ValueError, "manifest_changed"):
                render_cert.issue_certificate(
                    measurements, self._thresholds(),
                    issued_at="2026-08-12T00:00:00Z",
                )

        self._write_manifest()
        measurements_path = self.root / "manifest-drift-measurements.json"
        measurements_path.write_text(json.dumps(measurements), encoding="utf-8")
        output = self.root / "manifest-drift-certificate.json"
        with mock.patch.object(
            render_cert.receipt_sign, "load_operator_key", side_effect=key_then_mutate,
        ):
            code = render_cert.main([
                "certify", "--measurements", str(measurements_path),
                "--thresholds", json.dumps(self._thresholds()),
                "--issued-at", "2026-08-12T00:00:00Z", "--out", str(output),
            ])
        self.assertEqual(code, 3)
        self.assertFalse(output.exists())

    def test_issue_refuses_candidate_drift_during_final_manifest_rebind_and_cli_writes_nothing(self):
        measurements = self._measurements()
        candidate = self.candidates["train-a"]
        original_candidate = candidate.read_bytes()
        original_capture = render_cert._capture_private_generation

        def mutate_on_final_manifest_capture(path, reason):
            result = mutate_on_final_manifest_capture.original(path, reason)
            if reason == "manifest_changed":
                mutate_on_final_manifest_capture.manifest_calls += 1
                # The fourth manifest capture is the old implementation's
                # final post-validation rebind.  Mutating here must be caught
                # by the reordered all-generation final pass.
                if mutate_on_final_manifest_capture.manifest_calls == 4:
                    candidate.write_bytes(original_candidate + b"late-candidate-drift")
            return result

        mutate_on_final_manifest_capture.original = original_capture
        mutate_on_final_manifest_capture.manifest_calls = 0
        with mock.patch.object(
            render_cert, "_capture_private_generation",
            side_effect=mutate_on_final_manifest_capture,
        ):
            with self.assertRaisesRegex(
                ValueError, "measurement_candidate_changed|manifest_changed",
            ):
                render_cert.issue_certificate(
                    measurements, self._thresholds(),
                    issued_at="2026-08-12T00:00:00Z",
                )

        candidate.write_bytes(original_candidate)
        measurements_path = self.root / "candidate-drift-measurements.json"
        measurements_path.write_text(json.dumps(measurements), encoding="utf-8")
        output = self.root / "candidate-drift-certificate.json"
        mutate_on_final_manifest_capture.manifest_calls = 0
        with mock.patch.object(
            render_cert, "_capture_private_generation",
            side_effect=mutate_on_final_manifest_capture,
        ):
            code = render_cert.main([
                "certify", "--measurements", str(measurements_path),
                "--thresholds", json.dumps(self._thresholds()),
                "--issued-at", "2026-08-12T00:00:00Z", "--out", str(output),
            ])
        self.assertEqual(code, 3)
        self.assertFalse(output.exists())

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_issue_certificate_refuses_fabricated_measurement_generation_hash(self):
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
            "mock", self.manifest, work_dir=self.root / "issue-measure-work",
            renderer_binary=self.binary, renderer_version="mock 1.0",
            renderer_argv=[str(self.binary), "{in}", "{out}"],
            render_callback=lambda entry, source, candidate: reference,
            dpi=72,
        )
        for field, forged in (
            ("document_sha256", "0" * 64),
            ("reference_pdf_sha256", "0" * 64),
            ("candidate_pdf_sha256", "0" * 64),
            ("document", str(self.root / "forged-document.hwpx")),
            ("reference_pdf", str(self.root / "forged-reference.pdf")),
            ("candidate_pdf", str(self.root / "forged-candidate.pdf")),
        ):
            with self.subTest(field=field):
                tampered = deepcopy(measured)
                tampered["documents"][0][field] = forged
                with self.assertRaises(ValueError):
                    render_cert.issue_certificate(
                        tampered, self._thresholds(),
                        issued_at="2026-08-12T00:00:00Z",
                    )

    def test_issue_certificate_refuses_candidate_aliasing_source_or_reference(self):
        for alias_field in ("reference_pdf", "document"):
            with self.subTest(alias_field=alias_field):
                tampered = deepcopy(self._measurements())
                record = tampered["documents"][0]
                record["candidate_pdf"] = record[alias_field]
                if alias_field == "reference_pdf":
                    record["candidate_pdf_sha256"] = record["reference_pdf_sha256"]
                else:
                    record["candidate_pdf_sha256"] = record["document_sha256"]
                with self.assertRaisesRegex(ValueError, "measurement_candidate_alias"):
                    render_cert.issue_certificate(
                        tampered, self._thresholds(),
                        issued_at="2026-08-12T00:00:00Z",
                    )

    def test_issue_uses_lexical_manifest_join_not_resolving_helper(self):
        with mock.patch.object(
            render_cert, "_resolve_recorded_path",
            side_effect=AssertionError("legacy resolving helper must not run"),
        ):
            certificate = render_cert.issue_certificate(
                self._measurements(), self._thresholds(),
                issued_at="2026-08-12T00:00:00Z",
            )
        self.assertEqual(certificate["schema_version"], 1)

    @unittest.skipUnless(os.name == "nt", "Windows path-alias regression")
    def test_issue_accepts_windows_short_path_alias_for_bound_document(self):
        import ctypes

        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_short.restype = ctypes.c_uint32
        source = str(self.doc)
        size = 512
        buffer = ctypes.create_unicode_buffer(size)
        result = get_short(source, buffer, size)
        if not result or buffer.value.casefold() == source.casefold():
            self.skipTest("short-path alias unavailable")
        tampered = deepcopy(self._measurements())
        short_root = Path(buffer.value).parent
        tampered["corpus"]["manifest_path"] = str(
            short_root / self.manifest.name,
        )
        for record in tampered["documents"]:
            record["document"] = str(short_root / self.doc.name)
            record["reference_pdf"] = str(short_root / self.reference.name)
            record["candidate_pdf"] = str(
                short_root / self.candidates[record["id"]].name,
            )
        certificate = render_cert.issue_certificate(
            tampered, self._thresholds(), issued_at="2026-08-12T00:00:00Z",
        )
        self.assertEqual(certificate["schema_version"], 1)

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


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_render_cert_json_nonfinite_values_refuse_parser_and_writer(
    tmp_path, literal,
):
    with pytest.raises(ValueError, match="nonfinite_json_value"):
        render_cert._json_loads(f'{{"value":{literal}}}')
    with pytest.raises(ValueError, match="nonfinite_json_value"):
        render_cert._json_bytes({"value": float(literal)})
    target = tmp_path / "nonfinite.json"
    with pytest.raises(ValueError, match="nonfinite_json_value"):
        render_cert.write_json(target, {"value": float(literal)})
    assert not target.exists()


def test_render_cert_finite_exponent_remains_valid_json():
    assert render_cert._json_loads('{"value":1e3}') == {"value": 1000.0}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_render_cert_thresholds_require_finite_numbers(value):
    with pytest.raises(ValueError, match="finite"):
        render_cert._validate_thresholds({
            "page_count_exact": True,
            "word_anchor_px": value,
            "raster_changed_channel_ratio": 0.1,
        })


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_render_cert_threshold_file_and_inline_inputs_refuse_nonfinite(
    tmp_path, literal,
):
    raw = (
        '{"page_count_exact":true,"word_anchor_px":%s,'
        '"raster_changed_channel_ratio":0.1}' % literal
    )
    threshold_file = tmp_path / "thresholds.json"
    threshold_file.write_text(raw, encoding="utf-8")
    file_args = types.SimpleNamespace(
        thresholds=str(threshold_file), word_anchor_px=None,
        raster_changed_channel_ratio=None, min_matched_unique_words=None,
    )
    with pytest.raises(ValueError):
        render_cert._validate_thresholds(render_cert._threshold_args(file_args))
    inline_args = types.SimpleNamespace(
        thresholds=raw, word_anchor_px=None,
        raster_changed_channel_ratio=None, min_matched_unique_words=None,
    )
    with pytest.raises(ValueError, match="nonfinite_json_value"):
        render_cert._threshold_args(inline_args)


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_render_cert_nonfinite_certificate_public_paths_refuse(
    tmp_path, capsys, literal,
):
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        '{"schema_version":1,"certificate_sha256":"%s","x":%s}'
        % ("0" * 64, literal), encoding="ascii")
    verified = render_cert.verify_certificate(certificate)
    assert verified["reason_code"] == "certificate_invalid_json"

    document = tmp_path / "document.hwpx"
    checked = render_cert.check_document(document, certificate)
    assert checked["reason_code"] == "certificate_invalid_json"
    code = render_cert.main(["check", str(document), str(certificate)])
    assert code == 3
    printed = json.loads(capsys.readouterr().out)
    assert printed["reason_code"] == "certificate_invalid_json"


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_render_cert_manifest_nested_nonfinite_value_refuses(tmp_path, literal):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"schema_version":1,"documents":[{"generator":{"weight":%s}}]}'
        % literal, encoding="ascii")
    with pytest.raises(ValueError, match="nonfinite_json_value"):
        render_cert.load_manifest(manifest, require_ready=False)


def test_render_cert_main_nonfinite_payload_is_closed_operation_failure(
    tmp_path, monkeypatch, capsys,
):
    payload = {"ok": True, "eligible": True, "value": float("nan")}
    monkeypatch.setattr(render_cert, "check_document", lambda *args, **kwargs: payload)
    out = tmp_path / "result.json"
    code = render_cert.main([
        "check", str(tmp_path / "document.hwpx"),
        str(tmp_path / "certificate.json"), "--out", str(out),
    ])
    assert code == 3
    stdout_payload = json.loads(capsys.readouterr().out)
    assert stdout_payload["reason_code"] == "operation_failed"
    assert "NaN" not in out.read_text(encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["reason_code"] == (
        "operation_failed")


if __name__ == "__main__":
    unittest.main()
