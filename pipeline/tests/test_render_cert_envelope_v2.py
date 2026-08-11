"""Red contract tests for T151 snapshot-bound certificate envelopes.

T151 is a receipt-only, exact-document measurement check.  It is not a
renderer probe and its certificate never authorizes a generalized feature
subset or a proof/submission grade.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
TESTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import render_cert_envelope_v2 as envelope  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


SCHEMA = "rigorloom/render-cert-envelope/v2"
PRIVATE_SCHEMA = "rigorloom/render-cert-private-manifest/v2"
METRICS = {
    "page_count": {"exact": True, "reference": 1, "candidate": 1},
    "word_anchor": {"max_displacement_px": 0.0, "matched_unique_words": 4},
    "raster": {"changed_channel_ratio": 0.0},
}
THRESHOLDS = {
    "page_count_exact": True,
    "word_anchor_px": 1.0,
    "raster_changed_channel_ratio": 0.01,
}


@pytest.fixture(autouse=True)
def _operator_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Issue uses a pre-created temporary operator key, never a shipped key."""
    profile = tmp_path / "profile"
    key = profile / "keys" / "render_cert.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"T151 temporary operator key, never in receipts")
    os.chmod(key, 0o600)
    monkeypatch.setenv("RIGORLOOM_PROFILE_ROOT", str(profile))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_private_manifest(root: Path, *, document: str = "document.hwpx",
                            reference: str = "reference.pdf") -> Path:
    document_path = root / document
    reference_path = root / reference
    write_hwpx(document_path)
    reference_path.write_bytes(b"%PDF-1.4\n% synthetic reference\n")
    metrics_sha256 = hashlib.sha256(
        json.dumps(METRICS, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema": PRIVATE_SCHEMA,
        "reference_renderer": {
            "id": "hancom_windows", "version": "2024.0-test",
        },
        "thresholds": THRESHOLDS,
        "documents": [{
            "id": "opaque-document-a",
            "document": document,
            "reference_pdf": reference,
            "metrics": METRICS,
            "metrics_sha256": metrics_sha256,
        }],
    }
    path = root / "private-manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _issue(root: Path, *, manifest: Path | None = None) -> tuple[Path, Path]:
    manifest = manifest or _write_private_manifest(root)
    certificate = root / "certificate.json"
    result = envelope.issue_certificate(manifest, certificate)
    assert result["ok"] is True
    return manifest, certificate


def test_issue_writes_closed_pathless_snapshot_bound_certificate(tmp_path: Path):
    manifest, certificate = _issue(tmp_path)
    payload = json.loads(certificate.read_text(encoding="utf-8"))

    assert payload["schema"] == SCHEMA
    assert payload["evidence_ceiling"] == "exact_document_measurement_only"
    assert payload["runtime_binding"] == "not_established"
    assert payload["proof_grade"] == "none"
    assert payload["submission_grade"] is False
    assert payload["promotion"] == "not_run"
    assert payload["reference_renderer"] == {
        "id": "hancom_windows", "version": "2024.0-test",
    }
    assert len(payload["manifest_sha256"]) == 64
    assert len(payload["certificate_sha256"]) == 64
    assert len(payload["certificate_hmac_sha256"]) == 64
    assert payload["certificate_sha256"] == payload["certificate_sha256"].lower()
    assert payload["certificate_hmac_sha256"] == payload["certificate_hmac_sha256"].lower()
    expected_thresholds = hashlib.sha256(
        json.dumps(THRESHOLDS, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert payload["thresholds_sha256"] == expected_thresholds
    assert payload["measurements"]
    assert all(set(row) == {
        "id", "source", "reference_pdf_sha256", "reference_pdf_bytes",
        "metrics_sha256",
    } for row in payload["measurements"])
    row = payload["measurements"][0]
    document = tmp_path / "document.hwpx"
    reference = tmp_path / "reference.pdf"
    assert row["source"] == {"bytes": document.stat().st_size, "sha256": _sha(document)}
    assert row["reference_pdf_sha256"] == _sha(reference)
    assert row["reference_pdf_bytes"] == reference.stat().st_size
    assert all("path" not in row and "features" not in row
               for row in payload["measurements"])
    text = certificate.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(manifest) not in text
    assert "argv" not in text and "stdout" not in text and "stderr" not in text


def test_verify_and_check_are_exact_match_not_eligible_or_generalized(tmp_path: Path):
    _manifest, certificate = _issue(tmp_path)
    document = tmp_path / "document.hwpx"

    verified = envelope.verify_certificate(certificate)
    checked = envelope.check_document(document, certificate)

    assert verified["ok"] is True
    assert checked["ok"] is True
    assert checked["match"] == "exact_measurement_match"
    assert "eligible" not in checked
    assert checked["runtime_binding"] == "not_established"
    assert checked["proof_grade"] == "none"
    assert checked["submission_grade"] is False
    assert checked["promotion"] == "not_run"


def test_check_rebinds_current_document_and_refuses_same_features_after_mutation(
        tmp_path: Path):
    _manifest, certificate = _issue(tmp_path)
    document = tmp_path / "document.hwpx"
    original = document.read_bytes()
    with zipfile.ZipFile(document, "r") as source:
        replacement = tmp_path / "replacement.hwpx"
        with zipfile.ZipFile(replacement, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "Contents/section0.xml":
                    data = data.replace(b"Omega.", b"Changed.")
                target.writestr(info, data)
    replacement.replace(document)
    assert document.read_bytes() != original

    result = envelope.check_document(document, certificate)
    assert result["ok"] is False
    assert result["reason_code"] == "exact_measurement_mismatch"


def test_certificate_self_hash_hmac_and_canonical_json_are_closed(tmp_path: Path):
    _manifest, certificate = _issue(tmp_path)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["measurements"][0]["source"]["bytes"] += 1
    certificate.write_bytes((
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n"
    ).encode("utf-8"))

    result = envelope.verify_certificate(certificate)
    assert result["ok"] is False
    assert result["reason_code"] in {
        "certificate_hash_mismatch", "certificate_hmac_mismatch",
    }


def test_unknown_fields_duplicate_keys_and_generalized_envelope_are_refused(
        tmp_path: Path):
    _manifest, certificate = _issue(tmp_path)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["envelope"] = [{"features": {"tables": 999}}]
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    result = envelope.verify_certificate(certificate)
    assert result["ok"] is False
    assert result["reason_code"] in {
        "certificate_hash_mismatch", "certificate_schema_invalid",
    }

    # A duplicate top-level key must not be silently resolved by json.loads.
    raw = certificate.read_bytes()
    duplicate = raw.replace(
        b'"schema": "' + SCHEMA.encode("ascii") + b'"',
        b'"schema": "' + SCHEMA.encode("ascii") + b'", "schema": "'
        + SCHEMA.encode("ascii") + b'"', 1,
    )
    certificate.write_bytes(duplicate)
    result = envelope.verify_certificate(certificate)
    assert result["ok"] is False
    assert result["reason_code"] == "certificate_duplicate_key"


def test_private_manifest_paths_are_relative_contained_and_regular_one_link(
        tmp_path: Path):
    manifest = _write_private_manifest(tmp_path, document="../outside.hwpx")
    with pytest.raises(envelope.EnvelopeError, match="manifest_document_path"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")

    manifest = _write_private_manifest(tmp_path)
    os.link(tmp_path / "document.hwpx", tmp_path / "document-alias.hwpx")
    # Repointing the manifest at a hardlinked alias must not become a valid
    # exact source snapshot.
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for row in payload["documents"]:
        row["document"] = "document-alias.hwpx"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError, match="document_identity"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")


def test_issue_verify_check_never_execute_renderer_and_key_is_not_shipped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest = _write_private_manifest(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("T151 must not execute renderer or key tooling")

    monkeypatch.setattr("subprocess.run", forbidden)
    _manifest, certificate = _issue(tmp_path, manifest=manifest)
    assert envelope.verify_certificate(certificate)["ok"] is True
    assert envelope.check_document(tmp_path / "document.hwpx", certificate)["ok"] is True
    key_path = tmp_path / "profile" / "keys" / "render_cert.key"
    assert key_path.exists()
    assert key_path.read_bytes().hex() not in certificate.read_text(encoding="utf-8")


def test_cli_issue_verify_check_usage_and_refusal_exit_codes(tmp_path: Path, capsys):
    manifest = _write_private_manifest(tmp_path)
    certificate = tmp_path / "certificate.json"

    assert envelope.main(["issue", str(manifest), "--out", str(certificate)]) == 0
    assert envelope.main(["verify", str(certificate)]) == 0
    assert envelope.main([
        "check", str(tmp_path / "document.hwpx"), str(certificate),
    ]) == 3
    assert envelope.main(["check", str(tmp_path / "missing.hwpx"), str(certificate)]) == 3
    assert envelope.main(["--help"]) == 0
    assert envelope.main(["verify"]) == 2
    assert "eligible" not in capsys.readouterr().out


def test_manifest_schema_id_and_metric_digest_are_closed(tmp_path: Path):
    manifest = _write_private_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError, match="manifest_schema_invalid"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")

    manifest = _write_private_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["documents"][0]["id"] = "../private"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError, match="manifest_document_id"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")

    manifest = _write_private_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["documents"][0]["metrics_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError,
                       match="manifest_metrics_hash_mismatch"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")

    manifest = _write_private_manifest(tmp_path)
    raw = manifest.read_bytes().replace(
        b'"schema": "' + PRIVATE_SCHEMA.encode("ascii") + b'"',
        b'"schema": "' + PRIVATE_SCHEMA.encode("ascii")
        + b'", "schema": "' + PRIVATE_SCHEMA.encode("ascii") + b'"',
        1,
    )
    manifest.write_bytes(raw)
    with pytest.raises(envelope.EnvelopeError, match="manifest_duplicate_key"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")


def test_manifest_and_reference_hardlinks_are_refused(tmp_path: Path):
    manifest = _write_private_manifest(tmp_path)
    os.link(manifest, tmp_path / "manifest-alias.json")
    with pytest.raises(envelope.EnvelopeError, match="manifest_identity"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")

    (tmp_path / "manifest-alias.json").unlink()
    manifest = _write_private_manifest(tmp_path)
    os.link(tmp_path / "reference.pdf", tmp_path / "reference-alias.pdf")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["documents"][0]["reference_pdf"] = "reference-alias.pdf"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError, match="reference_identity"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")


def test_symlinked_manifest_and_output_parent_aliases_are_refused(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    manifest = _write_private_manifest(real)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(envelope.EnvelopeError, match="manifest_root_invalid"):
        envelope.issue_certificate(
            alias / manifest.name, tmp_path / "certificate.json")
    with pytest.raises(envelope.EnvelopeError,
                       match="certificate_output_invalid"):
        envelope.issue_certificate(manifest, alias / "certificate.json")


def test_v2_is_not_imported_by_routing_and_release_switches_stay_false():
    root = Path(__file__).resolve().parents[2]
    evidence = (root / "engine/scripts/document_evidence.py").read_text(
        encoding="utf-8")
    assert "ADVISORY_PROOF_RELEASE_ENABLED = False" in evidence
    assert "CERTIFIED_PROOF_RELEASE_ENABLED = False" in evidence
    for relative in (
        "pipeline/scripts/doc_backend.py",
        "pipeline/scripts/render_probe.py",
        "pipeline/scripts/submission_preflight.py",
        "scripts/new_report.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "render_cert_envelope_v2" not in text


def test_check_final_certificate_rebind_closes_document_callback_mutation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _manifest, certificate = _issue(tmp_path)
    original = envelope._identity_bytes_bound

    def mutate_after_document(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("reason") == "document_changed":
            certificate.write_bytes(b'{"forged":true}')
        return result

    monkeypatch.setattr(envelope, "_identity_bytes_bound", mutate_after_document)
    result = envelope.check_document(tmp_path / "document.hwpx", certificate)
    assert result["ok"] is False
    assert result["reason_code"] in {
        "certificate_schema_invalid", "certificate_changed",
    }


def test_publication_hardlink_fault_removes_owned_certificate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest = _write_private_manifest(tmp_path)
    certificate = tmp_path / "certificate.json"
    alias = tmp_path / "certificate-alias.json"
    original = envelope._core.DirectoryBinding.unlink
    injected = False

    def hardlink_after_temp_unlink(binding, name):
        nonlocal injected
        result = original(binding, name)
        if name.startswith(".certificate.json.") and not injected:
            injected = True
            os.link(certificate, alias)
        return result

    monkeypatch.setattr(
        envelope._core.DirectoryBinding, "unlink", hardlink_after_temp_unlink)
    with pytest.raises(envelope.EnvelopeError, match="certificate_publish_failed"):
        envelope.issue_certificate(manifest, certificate)
    assert injected
    assert not certificate.exists()
    assert alias.exists()


def test_publication_refuses_same_inode_mutation_after_first_final_capture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest = _write_private_manifest(tmp_path)
    certificate = tmp_path / "certificate.json"
    original = envelope._capture_bound
    injected = False

    def mutate_after_capture(binding, name, **kwargs):
        nonlocal injected
        raw = original(binding, name, **kwargs)
        if name == certificate.name and certificate.exists() and not injected:
            injected = True
            certificate.write_bytes(b'{"forged":true}')
        return raw

    monkeypatch.setattr(envelope, "_capture_bound", mutate_after_capture)
    with pytest.raises(envelope.EnvelopeError):
        envelope.issue_certificate(manifest, certificate)
    assert injected
    assert certificate.read_bytes() == b'{"forged":true}'


def test_check_refuses_document_mutation_during_final_certificate_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _manifest, certificate = _issue(tmp_path)
    document = tmp_path / "document.hwpx"
    original = envelope._read_certificate_bound
    calls = 0

    def mutate_during_final_certificate(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            raw = bytearray(document.read_bytes())
            raw[-1] ^= 1
            document.write_bytes(bytes(raw))
        return result

    monkeypatch.setattr(
        envelope, "_read_certificate_bound", mutate_during_final_certificate)
    result = envelope.check_document(document, certificate)
    assert calls == 2
    assert result["ok"] is False
    assert result["reason_code"] == "document_changed"


def test_manifest_surrogate_is_closed_for_api_and_cli(tmp_path: Path):
    manifest = _write_private_manifest(tmp_path)
    raw = manifest.read_text(encoding="utf-8")
    raw = raw.replace(
        '"page_count_exact": true',
        '"bad": "\\ud800", "page_count_exact": true',
    )
    manifest.write_text(raw, encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError,
                       match="measurement_value_invalid"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")
    assert envelope.main([
        "issue", str(manifest), "--out", str(tmp_path / "certificate.json"),
    ]) == 3

    manifest = _write_private_manifest(tmp_path)
    raw = manifest.read_text(encoding="utf-8").replace(
        '"2024.0-test"', '"\\ud800"')
    manifest.write_text(raw, encoding="utf-8")
    with pytest.raises(envelope.EnvelopeError,
                       match="manifest_renderer_invalid"):
        envelope.issue_certificate(manifest, tmp_path / "certificate.json")
