import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import document_evidence as evidence  # noqa: E402
import fill_report  # noqa: E402


def _workspace(tmp_path: Path):
    (tmp_path / "output" / "proof" / "backend").mkdir(parents=True)
    return tmp_path


def _write_bound(ws: Path, name: str, data: bytes) -> Path:
    path = ws / "output" / name
    path.write_bytes(data)
    return path


def _quality_for(path: Path, *, state="passed", reason="passed"):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema": evidence.QUALITY_SCHEMA,
        "checker": "hangul_glyphs",
        "version": "1",
        "artifact_sha256": digest,
        "artifact_bytes": path.stat().st_size,
        "state": state,
        "reason_code": reason,
        "source_hangul_count": 3,
        "pdf_hangul_count": 3,
        "page_count": 1,
        "mapped_font_xrefs": 1,
        "checked_font_xrefs": 1,
        "max_unique_hangul_per_xref": 3,
        "min_glyph_capacity": 8,
    }


def test_closed_enums_and_grade_derivation_fail_closed():
    assert "xml_only" in evidence.BACKEND_IDS
    assert "native_hancom_windows" in evidence.BACKEND_IDS
    assert "oss_preview_libreoffice" in evidence.BACKEND_IDS
    assert "oss_preview_rhwp" in evidence.BACKEND_IDS
    assert "certified_renderer" in evidence.BACKEND_IDS
    assert "none" in evidence.BACKEND_IDS
    assert evidence.derive_proof_grade("structural_only", "succeeded") == "none"
    quality = {
        "state": "passed",
    }
    assert evidence.derive_proof_grade("diagnostic_render", "succeeded", quality) == "experimental-rhwp"
    assert evidence.derive_proof_grade("advisory_render", "succeeded") == "none"
    assert evidence.derive_proof_grade("advisory_render", "succeeded", quality) == "none"
    assert evidence.derive_proof_grade("certified_render", "succeeded") == "none"
    assert evidence.derive_proof_grade("native_render", "succeeded") == "hancom"
    for state in ("failed", "refused", "not_run", "unknown", "hash_mismatch"):
        assert evidence.derive_proof_grade("native_render", state) == "none"
    assert evidence.derive_proof_grade("not-an-evidence-class", "succeeded") == "none"


def test_advisory_release_switch_is_shared_and_default_closed(monkeypatch):
    quality = {"state": "passed"}
    assert evidence.ADVISORY_PROOF_RELEASE_ENABLED is False
    assert evidence.derive_proof_grade(
        "advisory_render", "succeeded", quality) == "none"
    monkeypatch.setattr(evidence, "ADVISORY_PROOF_RELEASE_ENABLED", True)
    assert evidence.derive_proof_grade(
        "advisory_render", "succeeded", quality) == "advisory"


def test_native_unknown_type3_keeps_renderer_provenance_but_failed_downgrades(
    tmp_path,
):
    ws = _workspace(tmp_path)
    assembled = _write_bound(ws, "out.hwpx", b"assembled")
    rendered = _write_bound(ws, "out.pdf", b"pdf")
    unknown = _quality_for(rendered, state="unknown", reason="type3_font")
    receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=assembled,
        output_path=rendered,
        input_role="assembled_hwpx",
        output_role="rendered_pdf",
        exit_code=0,
        quality=unknown,
    )
    assert receipt["proof_grade"] == "hancom"
    failed = _quality_for(rendered, state="failed", reason="missing_hangul_glyphs")
    failed_receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=assembled,
        output_path=rendered,
        input_role="assembled_hwpx",
        output_role="rendered_pdf",
        exit_code=0,
        quality=failed,
    )
    assert failed_receipt["proof_grade"] == "none"
    assert failed_receipt["proof_unavailable"] is True
    certified_unknown = evidence.derive_proof_grade(
        "certified_render", "succeeded", unknown)
    assert certified_unknown == "none"


def test_support_matrix_keeps_receipt_backend_ids_in_sync():
    matrix = (Path(__file__).resolve().parents[2] /
              "skill" / "references" / "platform-backends.md").read_text(
                  encoding="utf-8")
    for backend in evidence.BACKEND_IDS:
        assert f"`{backend}`" in matrix
    for evidence_class in evidence.EVIDENCE_CLASSES:
        assert f"`{evidence_class}`" in matrix


def test_capability_does_not_establish_xml_proof(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    receipt = evidence.build_receipt(
        ws,
        backend="xml_only",
        evidence_class="structural_only",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        input_role="source_form",
        output_role="assembled_hwpx",
        exit_code=0,
        reason_code="xml_verified_no_proof",
        capability_facts={"hancom_com": True},
    )
    assert receipt["proof_grade"] == "none"
    assert receipt["proof_unavailable"] is True
    assert receipt["execution"]["backend"] == "xml_only"
    assert receipt["capability_facts"] == {"hancom_com": True}


@pytest.mark.parametrize(
    ("backend", "evidence_class", "grade"),
    [
        ("native_hancom_windows", "native_render", "hancom"),
        ("oss_preview_libreoffice", "advisory_render", "none"),
        ("oss_preview_rhwp", "diagnostic_render", "experimental-rhwp"),
        ("certified_renderer", "certified_render", "none"),
    ],
)
def test_successful_named_runtime_is_hash_bound(tmp_path, backend, evidence_class, grade):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    rendered = _write_bound(
        ws,
        "out.svg" if evidence_class == "diagnostic_render" else "out.pdf",
        b"svg" if evidence_class == "diagnostic_render" else b"pdf",
    )
    receipt = evidence.build_receipt(
        ws,
        backend=backend,
        evidence_class=evidence_class,
        terminal_state="succeeded",
            input_path=source,
            output_path=rendered,
            output_role=("diagnostic_svg" if evidence_class == "diagnostic_render"
                         else "rendered_pdf"),
        renderer_id=backend,
        exit_code=0,
        reason_code="render_succeeded",
        quality=(
            _quality_for(rendered)
            if evidence_class != "diagnostic_render" else None
        ),
    )
    evidence.write_receipt(ws, receipt)
    loaded = evidence.load_and_validate_receipt(ws)
    assert loaded["proof_grade"] == grade
    assert loaded["execution"]["input"]["sha256"] == hashlib.sha256(b"assembled").hexdigest()
    expected_output = b"svg" if evidence_class == "diagnostic_render" else b"pdf"
    assert loaded["execution"]["output"]["sha256"] == hashlib.sha256(expected_output).hexdigest()


def test_backend_evidence_pairing_and_roles_fail_closed(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    assembled = _write_bound(ws, "out.hwpx", b"assembled")
    rendered = _write_bound(ws, "out.pdf", b"pdf")

    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="xml_only",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=source,
            output_path=rendered,
            exit_code=0,
        )
    assert any(error["code"] == "backend_evidence_mismatch"
               for error in exc.value.errors)

    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="native_hancom_windows",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=assembled,
            output_path=assembled,
            exit_code=0,
        )
    assert any(error["code"] == "artifact_binding_not_distinct"
               for error in exc.value.errors)

    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="native_hancom_windows",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=assembled,
            output_path=rendered,
        )
    assert any(error["code"] == "successful_exit_code_missing"
               for error in exc.value.errors)

    wrong_output = _write_bound(ws, "out.svg", b"svg")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="native_hancom_windows",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=assembled,
            output_path=wrong_output,
            exit_code=0,
        )
    assert any(error["code"] == "render_output_role_invalid"
               for error in exc.value.errors)


def test_receipt_metadata_and_capabilities_are_privacy_safe(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    assembled = _write_bound(ws, "out.hwpx", b"assembled")
    rendered = _write_bound(ws, "out.pdf", b"pdf")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="native_hancom_windows",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=assembled,
            output_path=rendered,
            exit_code=0,
            # Assemble the synthetic user-profile path at runtime.  Keeping a
            # literal drive-letter user-profile token in a public test would
            # correctly trip the repository privacy gate that this behavior
            # is meant to defend.
            reason_code="failed_at_C:" + r"\Users\Alice\secret.hwpx",
        )
    assert any(error["code"] == "invalid_reason_code"
               for error in exc.value.errors)
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="native_hancom_windows",
            evidence_class="native_render",
            terminal_state="succeeded",
            input_path=assembled,
            output_path=rendered,
            exit_code=0,
            capability_facts={"hancom_com": "yes"},
        )
    assert any(error["code"] == "invalid_capability_fact"
               for error in exc.value.errors)


def _rehash(receipt):
    receipt["receipt_sha256"] = hashlib.sha256(
        evidence._canonical_bytes(receipt, omit_hash=True)
    ).hexdigest()
    return receipt


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda receipt: receipt.update(memo="unbounded"),
         "unknown_receipt_field"),
        (lambda receipt: receipt["execution"].update(extra="unbounded"),
         "unknown_execution_field"),
        (lambda receipt: receipt["execution"]["input"].update(extra="unbounded"),
         "unknown_artifact_field"),
        (lambda receipt: receipt.update(created_utc="not-a-time"),
         "invalid_created_utc"),
    ],
)
def test_receipt_v1_rejects_rehashed_unknown_fields_and_bad_timestamp(
    tmp_path, mutate, code
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    rendered = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=rendered,
        exit_code=0,
    )
    mutate(receipt)
    _rehash(receipt)
    with pytest.raises(evidence.EvidenceError) as write_error:
        evidence.write_receipt(ws, receipt)
    assert any(error["code"] == code for error in write_error.value.errors)
    (ws / evidence.RECEIPT_REL).write_text(
        json.dumps(receipt), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError) as load_error:
        evidence.load_and_validate_receipt(ws)
    assert any(error["code"] == code for error in load_error.value.errors)


def test_structural_success_requires_zero_exit_and_failure_role_is_closed(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    assembled = _write_bound(ws, "out.hwpx", b"assembled")
    for supplied_exit, expected_code in (
        (None, "successful_exit_code_missing"),
        (7, "successful_exit_nonzero"),
    ):
        kwargs = {}
        if supplied_exit is not None:
            kwargs["exit_code"] = supplied_exit
        with pytest.raises(evidence.EvidenceError) as exc:
            evidence.build_receipt(
                ws,
                backend="xml_only",
                evidence_class="structural_only",
                terminal_state="succeeded",
                input_path=source,
                output_path=assembled,
                input_role="source_form",
                output_role="assembled_hwpx",
                **kwargs,
            )
        assert any(error["code"] == expected_code for error in exc.value.errors)
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws,
            backend="xml_only",
            evidence_class="structural_only",
            terminal_state="failed",
            input_path=source,
            output_path=assembled,
            input_role="not-a-role",
            output_role="assembled_hwpx",
            exit_code=7,
        )
    assert any(error["code"] == "invalid_artifact_role"
               for error in exc.value.errors)


def test_product_docs_keep_receipt_boundaries_and_source_register(tmp_path):
    root = Path(__file__).resolve().parents[2]
    golden = (root / "docs" / "golden-path.md").read_text(encoding="utf-8")
    matrix = (root / "skill" / "references" / "platform-backends.md").read_text(
        encoding="utf-8")
    assert "## 4B. Assemble without Hancom (hwpx" in golden
    assert "grade requires an executed renderer" in golden
    assert "repository research notes" not in matrix
    assert "source register above" in matrix


def test_stale_receipt_cleanup_failure_aborts_before_execution(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    form = output / "form_copy.hwpx"
    form.write_bytes(b"form")
    target = tmp_path / evidence.RECEIPT_REL
    target.parent.mkdir(parents=True)
    target.write_text("stale", encoding="utf-8")
    original_unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path == target:
            raise OSError("synthetic lock")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    with pytest.raises(RuntimeError, match="could not invalidate prior evidence receipt"):
        fill_report._invalidate_evidence_receipt(form, output)
    assert target.exists()


def test_failed_or_stale_render_downgrades_to_none(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    failed = evidence.build_receipt(
        ws,
        backend="oss_preview_rhwp",
        evidence_class="diagnostic_render",
        terminal_state="failed",
        input_path=source,
        output_path=output,
        exit_code=7,
        reason_code="renderer_nonzero",
    )
    assert failed["proof_grade"] == "none"
    evidence.write_receipt(ws, failed)
    output.write_bytes(b"changed")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.load_and_validate_receipt(ws)
    assert any(error["code"] == "artifact_hash_mismatch" for error in exc.value.errors)


def test_validation_rejects_missing_malformed_unknown_and_escaping_receipts(tmp_path):
    ws = _workspace(tmp_path)
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)
    receipt_path = ws / evidence.RECEIPT_REL
    receipt_path.write_text("[]", encoding="utf-8")
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)
    receipt_path.write_text(json.dumps({"schema": evidence.RECEIPT_SCHEMA}), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)

    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
            input_path=source,
            output_path=output,
            exit_code=0,
    )
    receipt["execution"]["backend"] = "future_unlisted_backend"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.load_and_validate_receipt(ws)
    assert any(error["code"] == "unknown_backend" for error in exc.value.errors)

    # Restore a valid receipt before exercising path traversal.
    receipt = evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        exit_code=0,
    )
    receipt["execution"]["input"]["path"] = "../secret.hwpx"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.load_and_validate_receipt(ws)
    assert any(error["code"] == "path_escape" for error in exc.value.errors)


def test_validation_rejects_self_hash_and_privacy_fields(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="certified_renderer",
        evidence_class="certified_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        exit_code=0,
    )
    receipt["receipt_sha256"] = "0" * 64
    receipt["argv"] = ["C:\\Users\\operator\\secret"]
    (ws / evidence.RECEIPT_REL).write_text(
        json.dumps(receipt), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.load_and_validate_receipt(ws)
    codes = {error["code"] for error in exc.value.errors}
    assert "receipt_hash_mismatch" in codes
    assert "privacy_field" in codes


def test_valid_windows_receipt_is_historically_valid_on_linux(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        exit_code=0,
        reproducible_here=False,
        quality=_quality_for(output),
    )
    evidence.write_receipt(ws, receipt)
    loaded = evidence.load_and_validate_receipt(ws)
    assert loaded["proof_grade"] == "hancom"
    assert loaded["reproducible_here"] is False


def test_receipt_is_private_and_atomic(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    assembled = _write_bound(ws, "out.hwpx", b"assembled")
    receipt = evidence.build_receipt(
        ws,
        backend="xml_only",
        evidence_class="structural_only",
        terminal_state="succeeded",
        input_path=source,
        output_path=assembled,
        input_role="source_form",
        output_role="assembled_hwpx",
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    path = ws / evidence.RECEIPT_REL
    assert path.is_file()
    assert path.read_text(encoding="utf-8").endswith("\n")
    encoded = path.read_text(encoding="utf-8")
    assert "Users" not in encoded
    assert "argv" not in encoded
    assert "stdout" not in encoded
    assert "stderr" not in encoded
    assert "hostname" not in encoded
    assert evidence.load_and_validate_receipt(ws)["schema"] == evidence.RECEIPT_SCHEMA


def test_artifact_capture_rejects_hardlink_alias(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    alias = ws / "alias.hwpx"
    try:
        alias.hardlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("hard links unavailable")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    with pytest.raises(evidence.EvidenceError):
        evidence.build_receipt(
            ws,
            backend="xml_only",
            evidence_class="structural_only",
            terminal_state="succeeded",
            input_path=alias,
            output_path=output,
            input_role="source_form",
            output_role="assembled_hwpx",
            exit_code=0,
        )


def test_build_receipt_rebinds_input_after_first_hash(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    original = evidence._capture_file
    calls = {"source": 0}

    def mutate_after_first_hash(path):
        capture = original(path)
        if path == source:
            calls["source"] += 1
            if calls["source"] == 1:
                source.write_bytes(b"source-mutated")
        return capture

    monkeypatch.setattr(evidence, "_capture_file", mutate_after_first_hash)
    with pytest.raises(evidence.EvidenceError):
        evidence.build_receipt(
            ws,
            backend="xml_only",
            evidence_class="structural_only",
            terminal_state="succeeded",
            input_path=source,
            output_path=output,
            input_role="source_form",
            output_role="assembled_hwpx",
            exit_code=0,
        )


def test_build_receipt_rebinds_source_after_final_sibling_capture(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    original = evidence._capture_artifact
    calls = {"count": 0}

    def seam(workspace, path, role, **kwargs):
        calls["count"] += 1
        result = original(workspace, path, role, **kwargs)
        # Initial input/output are calls 1/2.  Final output/input are 3/4.
        # Mutating after call 4 must still be caught by the second final pass.
        if calls["count"] == 4:
            source.write_bytes(b"source-mutated-after-final-capture")
        return result

    monkeypatch.setattr(evidence, "_capture_artifact", seam)
    with pytest.raises(evidence.EvidenceError):
        evidence.build_receipt(
            ws, backend="xml_only", evidence_class="structural_only",
            terminal_state="succeeded", input_path=source,
            output_path=output, input_role="source_form",
            output_role="assembled_hwpx", exit_code=0,
        )


def test_load_receipt_rebinds_raw_and_identity_after_validation(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    target = ws / evidence.RECEIPT_REL
    original = evidence._validate_artifact
    changed = {"done": False}

    def mutate_receipt(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed["done"]:
            changed["done"] = True
            target.write_text("[]", encoding="utf-8")
        return result

    monkeypatch.setattr(evidence, "_validate_artifact", mutate_receipt)
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)


def test_load_receipt_rejects_hardlinked_public_receipt(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=source,
        output_path=output,
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    alias = ws / "receipt-alias.json"
    try:
        alias.hardlink_to(ws / evidence.RECEIPT_REL)
    except (OSError, NotImplementedError):
        pytest.skip("hard links unavailable")
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)


def test_load_final_rebind_catches_source_swap_before_last_capture(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    target = ws / evidence.RECEIPT_REL
    original = evidence._capture_artifact
    calls = {"count": 0}

    def seam(workspace, path, role, **kwargs):
        calls["count"] += 1
        # Initial validation is input/output (1/2); the final pass captures
        # output then input (3/4).  Mutate before the source's final capture.
        if calls["count"] == 4:
            source.write_bytes(b"source-swapped")
        return original(workspace, path, role, **kwargs)

    monkeypatch.setattr(evidence, "_capture_artifact", seam)
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)
    assert target.is_file()


def test_load_final_rebind_catches_output_swap_and_receipt_forge(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    target = ws / evidence.RECEIPT_REL
    original = evidence._capture_artifact
    calls = {"count": 0}

    def seam(workspace, path, role, **kwargs):
        calls["count"] += 1
        # Final output capture is call 3; mutate the artifact before that
        # capture.  Receipt forgery is also attempted after the capture so a
        # future implementation cannot validate again after its final read.
        if calls["count"] == 3:
            output.write_bytes(b"output-swapped")
        result = original(workspace, path, role, **kwargs)
        if calls["count"] == 3:
            target.write_text("[]", encoding="utf-8")
        return result

    monkeypatch.setattr(evidence, "_capture_artifact", seam)
    with pytest.raises(evidence.EvidenceError):
        evidence.load_and_validate_receipt(ws)


def test_write_callback_mutation_preserves_foreign_receipt(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    target = ws / evidence.RECEIPT_REL

    def mutate_public_receipt():
        target.write_text("foreign", encoding="utf-8")

    with pytest.raises(evidence.EvidenceError):
        evidence.write_receipt(ws, receipt, before_final_rebind=mutate_public_receipt)
    assert target.read_text(encoding="utf-8") == "foreign"


def test_write_hardlink_callback_rolls_back_owned_canonical_link(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    target = ws / evidence.RECEIPT_REL
    alias = ws / "receipt-hardlink-owner"

    def add_hardlink():
        alias.hardlink_to(target)

    with pytest.raises(evidence.EvidenceError):
        evidence.write_receipt(ws, receipt, before_final_rebind=add_hardlink)
    # Rollback removes only the owned canonical link; the callback's alias is
    # foreign and is left for the caller to clean up.
    assert not target.exists()
    assert alias.is_file()
    alias.unlink()


def test_owned_rollback_does_not_unlink_replacement_after_read(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    target = ws / evidence.RECEIPT_REL
    target.write_bytes(b"owned")
    expected_raw = target.read_bytes()
    owned_identity = evidence._capture_identity(target)
    original_unlink = Path.unlink
    raced = {"done": False}

    def swap_before_quarantine_unlink(path, *args, **kwargs):
        if (not raced["done"] and path.parent == target.parent
                and ".rollback-" in path.name):
            raced["done"] = True
            target.write_bytes(b"foreign-replacement")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", swap_before_quarantine_unlink)
    evidence._remove_owned_receipt(target, owned_identity, expected_raw)
    assert target.read_bytes() == b"foreign-replacement"


def test_write_callback_removes_target_then_leaves_no_receipt(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    target = ws / evidence.RECEIPT_REL

    def remove_target():
        target.unlink()

    with pytest.raises(evidence.EvidenceError):
        evidence.write_receipt(ws, receipt, before_final_rebind=remove_target)
    assert not target.exists()


def test_write_destination_parent_swap_never_publishes_outside(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    destination = ws / evidence.RECEIPT_REL.parent
    outside = tmp_path / "outside-receipt"
    outside.mkdir()
    backup = destination.with_name("backend-original")
    probe = ws / "output" / "__symlink_probe__"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")

    original_open = evidence._DestinationDirectoryBinding.open
    swapped = {"done": False, "blocked": False}

    def swap_after_binding(path):
        binding = original_open(path)
        try:
            destination.rename(backup)
            destination.symlink_to(outside, target_is_directory=True)
        except OSError:
            # Windows' no-FILE_SHARE_DELETE directory handle is the expected
            # protection: the attacker cannot swap the parent at all.
            swapped["blocked"] = True
            return binding
        swapped["done"] = True
        return binding

    monkeypatch.setattr(evidence._DestinationDirectoryBinding, "open",
                        staticmethod(swap_after_binding))
    error = None
    try:
        try:
            evidence.write_receipt(ws, receipt)
        except evidence.EvidenceError as exc:
            error = exc
    finally:
        if destination.is_symlink():
            destination.unlink()
        if backup.exists():
            backup.rename(destination)
    assert swapped["done"] or swapped["blocked"]
    if swapped["blocked"]:
        assert error is None
        assert (ws / evidence.RECEIPT_REL).is_file()
    else:
        assert error is not None
    assert not (outside / "receipt.json").exists()
    assert not (outside / "output" / "proof" / "backend" / "receipt.json").exists()


def test_destination_binding_removes_partial_temporary_on_write_failure(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    destination = ws / evidence.RECEIPT_REL.parent
    binding = evidence._DestinationDirectoryBinding.open(destination)
    original_write = evidence.os.write
    calls = {"count": 0}

    def fail_after_partial(fd, data):
        calls["count"] += 1
        if calls["count"] == 1:
            return original_write(fd, data[:1])
        raise OSError("synthetic temporary write failure")

    monkeypatch.setattr(evidence.os, "write", fail_after_partial)
    try:
        with pytest.raises(OSError, match="synthetic temporary write failure"):
            binding.create_temp(b"receipt-bytes")
    finally:
        binding.close()
    assert not list(destination.glob(".receipt-*.tmp"))


def test_write_rolls_back_owned_receipt_hardlinked_after_replace(
    tmp_path, monkeypatch,
):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    target = ws / evidence.RECEIPT_REL
    alias = ws / "receipt-after-replace-alias.json"
    original_replace = evidence._DestinationDirectoryBinding.replace

    def hardlink_after_replace(binding, temporary, name):
        original_replace(binding, temporary, name)
        try:
            alias.hardlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("hard links unavailable")

    monkeypatch.setattr(
        evidence._DestinationDirectoryBinding, "replace", hardlink_after_replace)
    with pytest.raises(evidence.EvidenceError):
        evidence.write_receipt(ws, receipt)
    assert not target.exists()
    alias.unlink()
    assert not target.exists()


def test_load_final_hardlink_error_is_receipt_relative(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "out.hwpx", b"assembled")
    output = _write_bound(ws, "out.pdf", b"pdf")
    receipt = evidence.build_receipt(
        ws, backend="native_hancom_windows", evidence_class="native_render",
        terminal_state="succeeded", input_path=source, output_path=output,
        exit_code=0,
    )
    evidence.write_receipt(ws, receipt)
    target = ws / evidence.RECEIPT_REL
    foreign = ws / "foreign-receipt.json"
    original = evidence._capture_receipt_artifacts
    calls = {"count": 0}

    def seam(workspace, payload):
        calls["count"] += 1
        result = original(workspace, payload)
        if calls["count"] == 2:
            foreign.write_text("foreign", encoding="utf-8")
            target.unlink()
            target.hardlink_to(foreign)
        return result

    monkeypatch.setattr(evidence, "_capture_receipt_artifacts", seam)
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.load_and_validate_receipt(ws)
    assert all(str(ws) not in str(item) for item in exc.value.errors)
    assert all("receipt.json" in str(item.get("path"))
               for item in exc.value.errors)


def test_artifact_parent_symlink_is_refused(tmp_path):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    alias = ws / "alias"
    try:
        alias.symlink_to(ws / "output", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(evidence.EvidenceError):
        evidence.build_receipt(
            ws, backend="xml_only", evidence_class="structural_only",
            terminal_state="succeeded", input_path=alias / source.name,
            output_path=output, input_role="source_form",
            output_role="assembled_hwpx", exit_code=0,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows path aliases only")
def test_safe_relative_path_accepts_same_node_windows_spelling_alias(
    tmp_path, monkeypatch,
):
    workspace = tmp_path / "workspace-short"
    alias_root = tmp_path / "workspace-long"
    workspace.mkdir()
    (alias_root / "output").mkdir(parents=True)
    candidate = alias_root / "output" / "out.hwpx"
    candidate.write_bytes(b"artifact")
    original = evidence._same_filesystem_node

    def same_node(left, right):
        if {Path(left), Path(right)} == {alias_root, workspace}:
            return True
        return original(Path(left), Path(right))

    monkeypatch.setattr(evidence, "_same_filesystem_node", same_node)
    assert evidence._safe_relative_path(workspace, candidate) == "output/out.hwpx"


def test_open_regular_accepts_same_node_handle_spelling_alias(
    tmp_path, monkeypatch,
):
    artifact = tmp_path / "artifact.hwpx"
    artifact.write_bytes(b"artifact")
    alternate = tmp_path / "alternate-spelling.hwpx"
    monkeypatch.setattr(evidence, "_opened_real_path", lambda _fd: alternate)
    monkeypatch.setattr(
        evidence, "_same_filesystem_node",
        lambda left, right: {Path(left), Path(right)} == {alternate, artifact},
    )
    fd, _info = evidence._open_regular(artifact, "regular artifact required")
    os.close(fd)


def test_destination_binding_accepts_same_node_handle_spelling_alias(
    tmp_path, monkeypatch,
):
    destination = tmp_path / "output" / "proof" / "backend"
    destination.mkdir(parents=True)
    alternate = tmp_path / "alternate-backend-spelling"
    original_opened = evidence._opened_real_path
    monkeypatch.setattr(evidence, "_opened_real_path", lambda _fd: alternate)
    monkeypatch.setattr(
        evidence, "_same_filesystem_node",
        lambda left, right: {Path(left), Path(right)} == {alternate, destination},
    )
    binding = evidence._DestinationDirectoryBinding.open(destination)
    try:
        binding.validate()
    finally:
        binding.close()
    monkeypatch.setattr(evidence, "_opened_real_path", original_opened)


def test_open_regular_requires_handle_path_binding(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    monkeypatch.setattr(evidence, "_opened_real_path", lambda _fd: None)
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws, backend="xml_only", evidence_class="structural_only",
            terminal_state="succeeded", input_path=source, output_path=output,
            input_role="source_form", output_role="assembled_hwpx", exit_code=0,
        )
    assert any(item.get("code") == "artifact_parent_binding_unavailable"
               for item in exc.value.errors)


def test_open_regular_rejects_handle_path_mismatch(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = _write_bound(ws, "form_copy.hwpx", b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(evidence, "_opened_real_path", lambda _fd: outside / "other")
    with pytest.raises(evidence.EvidenceError) as exc:
        evidence.build_receipt(
            ws, backend="xml_only", evidence_class="structural_only",
            terminal_state="succeeded", input_path=source, output_path=output,
            input_role="source_form", output_role="assembled_hwpx", exit_code=0,
        )
    assert any(item.get("code") == "artifact_parent_changed"
               for item in exc.value.errors)


def test_opened_real_path_uses_darwin_fgetpath(monkeypatch, tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"x")
    fd = os.open(str(artifact), os.O_RDONLY)
    fake_fcntl = types.SimpleNamespace(
        F_GETPATH=50,
        fcntl=lambda _fd, _command, _buffer: str(artifact).encode()
        + b"\0",
    )
    class FakePath:
        def __init__(self, value):
            self.value = str(value)

        def exists(self):
            return False

        def resolve(self, strict=True):
            return self

    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    monkeypatch.setattr(evidence, "Path", FakePath)
    original_os_name = evidence.os.name
    original_platform = evidence.sys.platform
    evidence.os.name = "posix"
    evidence.sys.platform = "darwin"
    try:
        actual = evidence._opened_real_path(fd)
    finally:
        # ``os.name`` is process-global; restore it before pytest teardown so
        # pathlib keeps its native Windows flavour for the remaining hooks.
        evidence.os.name = original_os_name
        evidence.sys.platform = original_platform
        os.close(fd)
    assert actual.value == str(artifact)


def test_artifact_parent_swap_after_lexical_walk_is_refused(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    nested = ws / "output" / "nested"
    nested.mkdir()
    source = nested / "form_copy.hwpx"
    source.write_bytes(b"source")
    output = _write_bound(ws, "out.hwpx", b"assembled")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / source.name).write_bytes(b"outside")
    backup = ws / "output" / "nested-original"
    original_check = evidence._check_directory_chain
    swapped = {"done": False}

    def swap_after_walk(workspace, directory):
        original_check(workspace, directory)
        if directory == nested and not swapped["done"]:
            swapped["done"] = True
            nested.rename(backup)
            nested.symlink_to(outside, target_is_directory=True)

    probe = ws / "output" / "__symlink_probe__"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    monkeypatch.setattr(evidence, "_check_directory_chain", swap_after_walk)
    try:
        with pytest.raises(evidence.EvidenceError):
            evidence.build_receipt(
                ws, backend="xml_only", evidence_class="structural_only",
                terminal_state="succeeded", input_path=source,
                output_path=output, input_role="source_form",
                output_role="assembled_hwpx", exit_code=0,
            )
    finally:
        if nested.is_symlink():
            nested.unlink()
        if backup.exists():
            backup.rename(nested)
