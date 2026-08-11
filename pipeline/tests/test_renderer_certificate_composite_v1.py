"""Red contract tests for the T152 composite renderer-certificate receipt."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
TESTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import renderer_certificate_composite_v1 as composite  # noqa: E402
import render_cert_envelope_v2 as envelope  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


SCHEMA = "rigorloom/renderer-certificate-composite/v1"
RUN_ID = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _operator_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    profile = tmp_path / "profile"
    key = profile / "keys" / "render_cert.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"T152 temporary operator key, never in receipts")
    os.chmod(key, 0o600)
    monkeypatch.setenv("RIGORLOOM_PROFILE_ROOT", str(profile))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path) -> dict:
    workspace = tmp_path / "workspace"
    source = workspace / "output" / "out.hwpx"
    write_hwpx(source)
    binary = tmp_path / "rhwp.bin"
    binary.write_bytes(b"renderer binary")
    certificate = tmp_path / "certificate.json"
    certificate_payload = {
        "schema": "rigorloom/render-cert-envelope/v2",
        "certificate_sha256": "c" * 64,
    }
    certificate.write_text(json.dumps(certificate_payload), encoding="utf-8")
    artifact = workspace / "output" / "proof" / "renderer-runtime-v2" / RUN_ID / "artifact.pdf"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fitz
        document = fitz.open()
        document.new_page()
        artifact.write_bytes(document.tobytes())
        document.close()
    except ImportError:
        artifact.write_bytes(b"%PDF-1.7\ncomposite-fixture\n")
    runtime_receipt = artifact.parent / "receipt.json"
    runtime_payload = {
        "schema": "rigorloom/renderer-runtime-v2/v1",
        "status": "analyzed",
        "renderer": {"id": "rhwp_pdf", "binary_sha256": _sha(binary.read_bytes())},
        "input": {
            "format": "hwpx", "bytes": source.stat().st_size,
            "sha256": _sha(source.read_bytes()), "preflight": "strict_complete",
        },
        "output": {
            "format": "pdf", "state": "captured",
            "bytes": artifact.stat().st_size, "sha256": _sha(artifact.read_bytes()),
            "pages": 1,
        },
        "certificate": {
            "bytes": certificate.stat().st_size,
            "sha256": _sha(certificate.read_bytes()), "validation": "not_run",
        },
        "dependency_closure": "unknown",
        "comparison": {"state": "unknown"},
        "render": {"state": "not_run"},
        "proof_grade": "none", "submission_grade": False, "promotion": "not_run",
    }
    runtime_receipt.write_text(
        json.dumps(runtime_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    composite_root = workspace / "output" / "proof" / "renderer-certificate-composite"
    composite_root.mkdir(parents=True, exist_ok=True)
    return {
        "workspace": workspace,
        "source": source,
        "binary": binary,
        "certificate": certificate,
        "artifact": artifact,
        "runtime_receipt": runtime_receipt,
        "runtime_payload": runtime_payload,
        "out": composite_root / RUN_ID / "receipt.json",
    }


def _install_stubs(monkeypatch: pytest.MonkeyPatch, fixture: dict) -> None:
    source = fixture["source"]
    certificate = fixture["certificate"]
    runtime_payload = fixture["runtime_payload"]
    monkeypatch.setattr(
        composite._runtime, "verify_runtime",
        lambda **_kwargs: runtime_payload,
    )
    monkeypatch.setattr(
        composite._envelope, "verify_certificate",
        lambda _path: {
            "ok": True,
            "reason_code": "certificate_verified",
            "certificate_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        composite._envelope, "check_document",
        lambda _document, _certificate: {
            "ok": True,
            "reason_code": "exact_measurement_match",
            "match": "exact_measurement_match",
            "document_id": "opaque-document-a",
            "certificate_sha256": "c" * 64,
            "source_sha256": _sha(source.read_bytes()),
            "source_bytes": source.stat().st_size,
        },
    )
    assert certificate.exists()


def _issue_real_certificate(tmp_path: Path, source: Path, out: Path) -> bytes:
    cert_root = tmp_path / "certificate-inputs"
    cert_root.mkdir()
    measured = cert_root / "document.hwpx"
    measured.write_bytes(source.read_bytes())
    reference = cert_root / "reference.pdf"
    reference.write_bytes(b"%PDF-1.4\n% synthetic reference\n")
    metrics = {
        "page_count": {"exact": True, "reference": 1, "candidate": 1},
        "word_anchor": {"max_displacement_px": 0.0,
                         "matched_unique_words": 4},
        "raster": {"changed_channel_ratio": 0.0},
    }
    thresholds = {
        "page_count_exact": True, "word_anchor_px": 1.0,
        "raster_changed_channel_ratio": 0.01,
    }
    metrics_sha = _sha(json.dumps(
        metrics, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    manifest = cert_root / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "rigorloom/render-cert-private-manifest/v2",
        "reference_renderer": {"id": "hancom_windows", "version": "2024.0-test"},
        "thresholds": thresholds,
        "documents": [{
            "id": "opaque-document-a", "document": measured.name,
            "reference_pdf": reference.name, "metrics": metrics,
            "metrics_sha256": metrics_sha,
        }],
    }), encoding="utf-8")
    issued_path = cert_root / "valid-certificate.json"
    issued = envelope.issue_certificate(manifest, issued_path)
    assert issued["ok"] is True
    out.write_bytes(issued_path.read_bytes())
    return out.read_bytes()


def test_check_binds_t150_t151_artifacts_into_closed_receipt(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)

    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )

    assert result["status"] == "analyzed"
    assert result["schema"] == SCHEMA
    assert result["status"] == "analyzed"
    assert result["binding_scope"] == "captured_snapshot_only"
    assert result["evidence_ceiling"] == (
        "runtime_input_exact_document_certificate_binding_only"
    )
    assert result["dependency_closure"] == "unknown"
    assert result["comparison"] == {"state": "unknown"}
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert result["promotion"] == "not_run"
    assert result["match"] == "exact_measurement_match"
    assert result["certificate"]["file_sha256"] == _sha(
        fixture["certificate"].read_bytes())
    assert result["certificate"]["file_bytes"] == fixture["certificate"].stat().st_size
    assert len(result["certificate"]["body_sha256"]) == 64
    assert result["certificate"]["file_sha256"] != result["certificate"]["body_sha256"]
    assert result["runtime"]["receipt_sha256"] == _sha(
        fixture["runtime_receipt"].read_bytes())
    assert result["output"]["sha256"] == _sha(fixture["artifact"].read_bytes())
    assert result["output"]["pages"] == 1
    encoded = json.dumps(result, ensure_ascii=False)
    assert str(fixture["workspace"]) not in encoded
    assert "argv" not in encoded and "stdout" not in encoded and "stderr" not in encoded
    assert "eligible" not in result


def test_invalid_captured_certificate_cannot_be_replaced_by_valid_path_generation(
        tmp_path, monkeypatch):
    """T151 must validate the exact captured A bytes, never a later B path."""
    fixture = _fixture(tmp_path)
    valid_path = tmp_path / "valid-certificate.json"
    valid_raw = _issue_real_certificate(tmp_path, fixture["source"], valid_path)
    valid_payload = json.loads(valid_raw.decode("utf-8"))
    invalid_payload = dict(valid_payload)
    invalid_payload["certificate_hmac_sha256"] = "0" * 64
    invalid_raw = (json.dumps(invalid_payload, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
    fixture["certificate"].write_bytes(invalid_raw)
    fixture["runtime_payload"]["certificate"] = {
        "bytes": len(invalid_raw), "sha256": _sha(invalid_raw),
        "validation": "not_run",
    }
    fixture["runtime_receipt"].write_text(
        json.dumps(fixture["runtime_payload"], sort_keys=True,
                   separators=(",", ":")) + "\n", encoding="utf-8")
    monkeypatch.setattr(composite._runtime, "verify_runtime",
                        lambda **_kwargs: fixture["runtime_payload"])
    original_verify = envelope.verify_certificate
    staged_paths = []

    def verify_staged(path):
        path = Path(path)
        staged_paths.append(path)
        # A valid B is swapped into the source path after A has been captured.
        fixture["certificate"].write_bytes(valid_raw)
        return original_verify(path)

    monkeypatch.setattr(composite._envelope, "verify_certificate", verify_staged)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert staged_paths and staged_paths[0] != fixture["certificate"]
    assert result["ok"] is False
    assert result["reason_code"] == "certificate_hmac_mismatch"
    assert not fixture["out"].exists()


def test_check_calls_only_verifiers_and_never_executes_renderer(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("renderer executed"))
    calls: list[str] = []
    original_runtime = composite._runtime.verify_runtime
    original_cert = composite._envelope.verify_certificate
    original_doc = composite._envelope.check_document
    monkeypatch.setattr(
        composite._runtime, "verify_runtime",
        lambda **kwargs: (calls.append("runtime") or original_runtime(**kwargs)),
    )
    monkeypatch.setattr(
        composite._envelope, "verify_certificate",
        lambda path: (calls.append("certificate") or original_cert(path)),
    )
    monkeypatch.setattr(
        composite._envelope, "check_document",
        lambda document, certificate: (calls.append("document") or original_doc(document, certificate)),
    )
    # The wrappers above intentionally call the stubbed originals only when
    # the implementation invokes the three verifier APIs; no child process is
    # available to this lane.
    composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert calls == ["runtime", "certificate", "document"]


@pytest.mark.parametrize("reason", [
    "runtime_input_mismatch", "certificate_hash_mismatch",
    "certificate_hmac_mismatch", "artifact_mismatch",
])
def test_mismatch_or_missing_dependency_refuses_without_receipt(
        tmp_path, monkeypatch, reason):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    if reason == "runtime_input_mismatch":
        fixture["runtime_payload"]["input"]["sha256"] = "a" * 64
    elif reason == "certificate_hash_mismatch":
        fixture["runtime_payload"]["certificate"]["sha256"] = "b" * 64
    elif reason == "certificate_hmac_mismatch":
        monkeypatch.setattr(
            composite._envelope, "verify_certificate",
            lambda _path: {"ok": False, "reason_code": reason},
        )
    else:
        fixture["runtime_payload"]["output"]["sha256"] = "d" * 64
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert result["ok"] is False
    assert not fixture["out"].exists()


def test_output_must_be_canonical_and_not_source_or_runtime_receipt_alias(
        tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    for output in (fixture["source"], fixture["runtime_receipt"]):
        result = composite.check_composite(
            workspace=fixture["workspace"], run_id=RUN_ID,
            binary=fixture["binary"], certificate=fixture["certificate"],
            out=output,
        )
        assert result["ok"] is False
        assert result["reason_code"] == "output_invalid"


def test_binary_drift_after_runtime_verify_is_refused(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original = composite._runtime.verify_runtime

    def verify_then_mutate(**kwargs):
        result = original(**kwargs)
        fixture["binary"].write_bytes(b"binary changed after runtime verify")
        return result

    monkeypatch.setattr(composite._runtime, "verify_runtime", verify_then_mutate)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert result["ok"] is False
    assert result["reason_code"] == "binary_mismatch"
    assert not fixture["out"].exists()


def test_certificate_drift_after_t151_check_is_refused(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original = composite._envelope.check_document

    def check_then_mutate(document, certificate):
        result = original(document, certificate)
        fixture["certificate"].write_bytes(b"certificate changed after T151")
        return result

    monkeypatch.setattr(composite._envelope, "check_document", check_then_mutate)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert result["ok"] is False
    assert result["reason_code"] == "certificate_changed"
    assert not fixture["out"].exists()


def test_artifact_drift_after_pdf_validation_is_refused(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original = composite._runtime._validate_pdf
    mutated = False

    def validate_then_mutate(data):
        nonlocal mutated
        pages = original(data)
        if not mutated:
            mutated = True
            fixture["artifact"].write_bytes(data + b"drift")
        return pages

    monkeypatch.setattr(composite._runtime, "_validate_pdf", validate_then_mutate)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert result["ok"] is False
    assert result["reason_code"] == "artifact_mismatch"
    assert not fixture["out"].exists()


def test_verify_rejoins_components_and_refuses_tampered_receipt(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    checked = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert checked["status"] == "analyzed"
    verified = composite.verify_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
    )
    assert verified["status"] == "analyzed"
    payload = json.loads(fixture["out"].read_text(encoding="utf-8"))
    payload["promotion"] = "certified"
    fixture["out"].write_text(json.dumps(payload), encoding="utf-8")
    refused = composite.verify_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
    )
    assert refused["ok"] is False
    assert refused["reason_code"] in {"receipt_not_canonical", "receipt_state_invalid",
                                       "receipt_hash_mismatch"}


def test_verify_refuses_forged_extra_key_without_writing(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    checked = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert checked["status"] == "analyzed"
    forged = dict(checked)
    forged["eligible"] = True
    fixture["out"].write_bytes(
        (json.dumps(forged, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n").encode("utf-8"))
    before = fixture["out"].read_bytes()
    refused = composite.verify_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
    )
    assert refused["ok"] is False
    assert refused["reason_code"] in {"receipt_schema_invalid", "receipt_hash_mismatch",
                                       "receipt_not_canonical"}
    assert fixture["out"].read_bytes() == before


def test_verify_refuses_unexpected_run_sidecar_and_preserves_it(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    checked = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert checked["status"] == "analyzed"
    sidecar = fixture["out"].parent / "unexpected.bin"
    sidecar.write_bytes(b"unrelated sidecar")
    receipt_before = fixture["out"].read_bytes()
    refused = composite.verify_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
    )
    assert refused["ok"] is False
    assert refused["reason_code"] == "run_layout_invalid"
    assert sidecar.read_bytes() == b"unrelated sidecar"
    assert fixture["out"].read_bytes() == receipt_before


def test_verify_refuses_sidecar_added_during_final_receipt_read(
        tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    checked = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert checked["status"] == "analyzed"
    original = composite._read_receipt
    calls = 0
    sidecar = fixture["out"].parent / "late-verify.bin"
    receipt_before = fixture["out"].read_bytes()

    def read_then_add(path, run_id):
        nonlocal calls
        result = original(path, run_id)
        calls += 1
        if calls == 2:
            sidecar.write_bytes(b"late verify sidecar")
        return result

    monkeypatch.setattr(composite, "_read_receipt", read_then_add)
    refused = composite.verify_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
    )
    assert refused["ok"] is False
    assert refused["reason_code"] == "run_layout_invalid"
    assert sidecar.read_bytes() == b"late verify sidecar"
    assert fixture["out"].read_bytes() == receipt_before


def test_check_refuses_sidecar_injected_before_final_layout_validation(
        tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original_validate = composite._validate_run_contents
    injected = False

    def validate_then_inject(binding, expected_identity=None):
        nonlocal injected
        if not injected:
            injected = True
            (binding.path / "unexpected.bin").write_bytes(b"foreign sidecar")
        return original_validate(binding, expected_identity)

    monkeypatch.setattr(composite, "_validate_run_contents", validate_then_inject)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    sidecar = fixture["out"].parent / "unexpected.bin"
    assert injected
    assert result["ok"] is False
    assert result["reason_code"] == "run_layout_invalid"
    assert sidecar.read_bytes() == b"foreign sidecar"
    assert not fixture["out"].exists()


def test_second_check_cannot_clobber_existing_run(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    first = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    before = fixture["out"].read_bytes()
    second = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert first["status"] == "analyzed"
    assert second["ok"] is False
    assert second["reason_code"] == "run_exists"
    assert fixture["out"].read_bytes() == before


def test_held_composite_root_refuses_swap_before_publication(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    root = fixture["out"].parent.parent
    external = tmp_path / "outside"
    external.mkdir()
    alias = root.with_name(root.name + "-real")
    try:
        root.rename(alias)
        root.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        if alias.exists() and not root.exists():
            alias.rename(root)
        pytest.skip("directory symlinks unavailable")
    finally:
        if root.is_symlink():
            root.unlink()
        if alias.exists() and not root.exists():
            alias.rename(root)

    original = composite._component_snapshot

    def snapshot_then_swap(**kwargs):
        result = original(**kwargs)
        try:
            root.rename(alias)
            root.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks unavailable")
        return result

    monkeypatch.setattr(composite, "_component_snapshot", snapshot_then_swap)
    try:
        result = composite.check_composite(
            workspace=fixture["workspace"], run_id=RUN_ID,
            binary=fixture["binary"], certificate=fixture["certificate"],
            out=fixture["out"],
        )
        assert result["ok"] is False
        assert not (external / RUN_ID / "receipt.json").exists()
    finally:
        if root.is_symlink():
            root.unlink()
        if alias.exists() and not root.exists():
            alias.rename(root)


def test_held_composite_root_refuses_directory_replacement(tmp_path, monkeypatch):
    """A held leaf binding must reject replacement even without symlinks."""
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    root = fixture["out"].parent.parent
    alias = root.with_name(root.name + "-held")
    original = composite._component_snapshot

    def snapshot_then_replace(**kwargs):
        result = original(**kwargs)
        try:
            root.rename(alias)
            root.mkdir()
        except OSError:
            if alias.exists() and not root.exists():
                alias.rename(root)
            pytest.skip("directory replacement unavailable")
        return result

    monkeypatch.setattr(composite, "_component_snapshot", snapshot_then_replace)
    try:
        result = composite.check_composite(
            workspace=fixture["workspace"], run_id=RUN_ID,
            binary=fixture["binary"], certificate=fixture["certificate"],
            out=fixture["out"],
        )
        assert result["ok"] is False
        assert not fixture["out"].exists()
        assert not (root / RUN_ID / "receipt.json").exists()
    finally:
        if root.exists() and root.is_dir() and not root.is_symlink():
            try:
                root.rmdir()
            except OSError:
                pass
        if alias.exists() and not root.exists():
            alias.rename(root)


def test_final_root_guard_mutation_is_caught_by_immediate_receipt_rebind(
        tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original_check = composite._core.DirectoryBinding.check
    root = fixture["out"].parent.parent
    calls = 0
    mutated = False
    mutated_bytes = b""

    def check_then_mutate(binding):
        nonlocal calls, mutated, mutated_bytes
        original_check(binding)
        if binding.path == root and calls >= 2 and fixture["out"].exists():
            mutated = True
            raw = fixture["out"].read_bytes()
            mutated_bytes = bytes((raw[0] ^ 1,)) + raw[1:]
            fixture["out"].write_bytes(mutated_bytes)
        calls += 1

    monkeypatch.setattr(composite._core.DirectoryBinding, "check",
                        check_then_mutate)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert mutated
    assert result["ok"] is False
    assert fixture["out"].read_bytes() == mutated_bytes


def test_late_sidecar_during_final_root_guard_is_refused_and_preserved(
        tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original_check = composite._core.DirectoryBinding.check
    root = fixture["out"].parent.parent
    calls = 0
    injected = False

    def check_then_sidecar(binding):
        nonlocal calls, injected
        original_check(binding)
        if binding.path == root and calls >= 2 and fixture["out"].exists():
            injected = True
            (fixture["out"].parent / "late.bin").write_bytes(b"late sidecar")
        calls += 1

    monkeypatch.setattr(composite._core.DirectoryBinding, "check",
                        check_then_sidecar)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert injected
    assert result["ok"] is False
    assert result["reason_code"] == "run_layout_invalid"
    assert (fixture["out"].parent / "late.bin").read_bytes() == b"late sidecar"
    assert not fixture["out"].exists()


def test_foreign_receipt_replacement_survives_owned_rollback(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    original = composite._capture
    injected = False

    def capture_then_replace(path, max_bytes, reason):
        nonlocal injected
        result = original(path, max_bytes, reason)
        if (path.name == "receipt.json"
                and path.parent.name == RUN_ID
                and path.parent.parent.name == composite.ROOT_LEAF
                and not injected):
            injected = True
            path.write_bytes(b"foreign receipt")
        return result

    monkeypatch.setattr(composite, "_capture", capture_then_replace)
    result = composite.check_composite(
        workspace=fixture["workspace"], run_id=RUN_ID,
        binary=fixture["binary"], certificate=fixture["certificate"],
        out=fixture["out"],
    )
    assert injected
    assert result["ok"] is False
    assert fixture["out"].read_bytes() == b"foreign receipt"


def test_cli_success_is_diagnostic_exit_three_and_usage_is_two(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _install_stubs(monkeypatch, fixture)
    assert composite.main([
        "check", str(fixture["workspace"]), "--run-id", RUN_ID,
        "--binary", str(fixture["binary"]), "--certificate",
        str(fixture["certificate"]), "--out", str(fixture["out"]),
    ]) == 3
    assert composite.main([
        "verify", str(fixture["workspace"]), "--run-id", RUN_ID,
        "--binary", str(fixture["binary"]), "--certificate",
        str(fixture["certificate"]),
    ]) == 3
    assert composite.main(["--help"]) == 0
    assert composite.main(["check"]) == 2
