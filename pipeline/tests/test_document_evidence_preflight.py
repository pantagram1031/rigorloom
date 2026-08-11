import json
import hashlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ENGINE = Path(__file__).resolve().parents[2] / "engine" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ENGINE))

import document_evidence  # noqa: E402
import submission_preflight  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


def _workspace(tmp_path: Path, grade: str = "hancom") -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    (ws / "output" / "proof" / "backend").mkdir(parents=True)
    write_hwpx(ws / "output" / "submission.hwpx", body="content")
    (ws / "PIPELINE.md").write_text(
        '```yaml\ncanonical_output: "output/submission.hwpx"\n```\n',
        encoding="utf-8")
    (ws / "request.yaml").write_text(
        'output_filename: "submission.hwpx"\nrequired_fields: []\n',
        encoding="utf-8")
    (ws / "output" / "verdict_v06.json").write_text(
        json.dumps({
            "proof_grade": grade,
            "converged": True,
            "checks": {},
            "style_anomalies": [],
        }), encoding="utf-8")
    return ws, ws / "output" / "submission.hwpx"


def _valid_receipt(ws: Path, artifact: Path, grade: str = "hancom"):
    backend, cls = {
        "hancom": ("native_hancom_windows", "native_render"),
        "advisory": ("oss_preview_libreoffice", "advisory_render"),
        "experimental-rhwp": ("oss_preview_rhwp", "diagnostic_render"),
        "certified": ("certified_renderer", "certified_render"),
    }[grade]
    if artifact.suffix.lower() == ".pdf":
        input_path = ws / "output" / "receipt-input.hwpx"
        if not input_path.exists():
            write_hwpx(input_path, body="receipt input")
        output_path = artifact
    else:
        input_path = artifact
        output_path = ws / "output" / (
            "receipt-render.svg" if grade == "experimental-rhwp"
            else "receipt-render.pdf"
        )
        output_path.write_bytes(b"rendered bytes")
    receipt = document_evidence.build_receipt(
        ws,
        backend=backend,
        evidence_class=cls,
        terminal_state="succeeded",
        input_path=input_path,
        output_path=output_path,
        input_role="assembled_hwpx",
        output_role=("diagnostic_svg" if grade == "experimental-rhwp"
                     else "rendered_pdf"),
        exit_code=0,
        reproducible_here=False,
    )
    document_evidence.write_receipt(ws, receipt)


def _prepend_conflicting_duplicate_receipt_grade(ws: Path) -> None:
    receipt_path = ws / document_evidence.RECEIPT_REL
    raw = receipt_path.read_text(encoding="utf-8")
    needle = '  "proof_grade": "hancom",'
    assert raw.count(needle) == 1
    receipt_path.write_text(
        raw.replace(needle, '  "proof_grade": "certified",\n' + needle, 1),
        encoding="utf-8",
    )


def _prepend_shadowed_execution_canary(ws: Path) -> None:
    receipt_path = ws / document_evidence.RECEIPT_REL
    raw = receipt_path.read_text(encoding="utf-8")
    needle = '    "backend": "native_hancom_windows",'
    assert raw.count(needle) == 1
    receipt_path.write_text(
        raw.replace(
            needle,
            '    "backend": "canary-C:/Users/Alice/secret.hwpx",\n'
            + needle,
            1,
        ),
        encoding="utf-8",
    )


def _quality_for(pdf: Path, *, state: str = "passed",
                 reason: str = "passed") -> dict:
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return {
        "schema": document_evidence.QUALITY_SCHEMA,
        "checker": "hangul_glyphs",
        "version": "1",
        "artifact_sha256": digest,
        "artifact_bytes": pdf.stat().st_size,
        "state": state,
        "reason_code": reason,
        "source_hangul_count": 1,
        "pdf_hangul_count": 1,
        "page_count": 1,
        "mapped_font_xrefs": 1,
        "checked_font_xrefs": 1,
        "max_unique_hangul_per_xref": 1,
        "min_glyph_capacity": 1,
    }


def test_non_none_legacy_grade_without_receipt_is_hard(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_receipt_missing" for item in verdict["hard"])


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_submission_preflight_nonfinite_receipt_is_hard_and_privacy_safe(
    tmp_path, monkeypatch, literal,
):
    ws, artifact = _workspace(tmp_path)
    _valid_receipt(ws, artifact)
    receipt_path = ws / document_evidence.RECEIPT_REL
    raw = receipt_path.read_text(encoding="utf-8")
    assert '  "exit_code": 0,' in raw
    receipt_path.write_text(raw.replace(
        '  "exit_code": 0,', f'  "exit_code": {literal},', 1),
        encoding="utf-8")
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    finding = next(item for item in verdict["hard"]
                   if item["code"] == "proof_receipt_invalid")
    assert any(error["code"] == "receipt_nonfinite_value"
               for error in finding["errors"])
    finding_json = json.dumps(finding, ensure_ascii=True, allow_nan=False)
    assert literal not in finding_json
    assert str(ws) not in finding_json


def test_legacy_certified_grade_is_quarantined_even_with_certificate_config(
    tmp_path, monkeypatch,
):
    ws, _artifact = _workspace(tmp_path, grade="certified")
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "certified_runtime_unbound"
               for item in verdict["hard"])


def test_valid_windows_receipt_survives_linux_host_probe(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path)
    _valid_receipt(ws, artifact)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    monkeypatch.setattr(
        submission_preflight.render_probe,
        "probe", lambda: {"capabilities": {"hancom_com": False}, "renderers": []})
    verdict, code = submission_preflight.check(ws)
    assert code == 0, verdict
    assert verdict["proof_grade"] == "hancom"
    assert any("informational" in note for note in verdict["notes"])


def test_submission_preflight_rejects_conflicting_duplicate_receipt_grade(
    tmp_path, monkeypatch,
):
    ws, artifact = _workspace(tmp_path)
    _valid_receipt(ws, artifact)
    _prepend_conflicting_duplicate_receipt_grade(ws)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    finding = next(item for item in verdict["hard"]
                   if item["code"] == "proof_receipt_invalid")
    assert any(error["code"] == "receipt_duplicate_key"
               for error in finding["errors"])
    assert str(ws) not in json.dumps(finding["errors"], ensure_ascii=False)


def test_submission_preflight_rejects_shadowed_execution_canary(
    tmp_path, monkeypatch,
):
    ws, artifact = _workspace(tmp_path)
    _valid_receipt(ws, artifact)
    _prepend_shadowed_execution_canary(ws)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    finding = next(item for item in verdict["hard"]
                   if item["code"] == "proof_receipt_invalid")
    assert any(error["code"] == "receipt_duplicate_key"
               for error in finding["errors"])
    rendered = json.dumps(finding["errors"], ensure_ascii=False)
    assert "canary-" not in rendered
    assert "secret.hwpx" not in rendered
    assert str(ws) not in rendered


def test_verdict_receipt_grade_mismatch_is_hard(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    _valid_receipt(ws, artifact, "hancom")
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_receipt_grade_mismatch"
               for item in verdict["hard"])


def test_proof_unavailable_cannot_claim_non_none_grade(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path)
    _valid_receipt(ws, artifact)
    (ws / "output" / "verdict_v06.json").write_text(
        json.dumps({"proof_grade": "hancom", "proof_unavailable": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_unavailable_non_none"
               for item in verdict["hard"])


def test_non_none_receipt_must_bind_canonical_artifact_not_decoy(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path)
    decoy = ws / "output" / "decoy.hwpx"
    decoy.write_bytes(b"unrelated decoy")
    rendered = ws / "output" / "decoy.pdf"
    rendered.write_bytes(b"decoy render")
    receipt = document_evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=decoy,
        output_path=rendered,
        exit_code=0,
    )
    document_evidence.write_receipt(ws, receipt)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_receipt_canonical_unbound"
               for item in verdict["hard"])


def test_identical_renamed_hwp_bytes_can_bind_canonical_input(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path)
    renamed = ws / "output" / "renamed.hwpx"
    renamed.write_bytes(artifact.read_bytes())
    rendered = ws / "output" / "renamed.pdf"
    rendered.write_bytes(b"rendered")
    receipt = document_evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=renamed,
        output_path=rendered,
        exit_code=0,
    )
    document_evidence.write_receipt(ws, receipt)
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 0, verdict


def test_none_allow_unproven_draft_remains_allowed_without_receipt(tmp_path, monkeypatch):
    ws, _artifact = _workspace(tmp_path, grade="none")
    monkeypatch.setattr(
        submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws, allow_unproven=True)
    assert code == 0, verdict
    assert any("allow" in note for note in verdict["notes"])


def test_advisory_qualityless_receipt_is_hard(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    _valid_receipt(ws, artifact, "advisory")
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_quality_missing"
               for item in verdict["hard"])


def test_advisory_unknown_or_failed_quality_is_hard(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    rendered = ws / "output" / "quality.pdf"
    rendered.write_bytes(b"quality-bound-pdf")
    quality = _quality_for(rendered, state="unknown", reason="font_mapping_missing")
    receipt = document_evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
        input_path=artifact,
        output_path=rendered,
        exit_code=0,
        quality=quality,
    )
    document_evidence.write_receipt(ws, receipt)
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_quality_failed"
               for item in verdict["hard"])


def test_advisory_quality_hash_swap_is_invalid(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    rendered = ws / "output" / "quality.pdf"
    rendered.write_bytes(b"quality-bound-pdf")
    quality = _quality_for(rendered)
    receipt = document_evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
        input_path=artifact,
        output_path=rendered,
        exit_code=0,
        quality=quality,
    )
    receipt["quality"]["artifact_sha256"] = "f" * 64
    receipt["receipt_sha256"] = hashlib.sha256(
        document_evidence._canonical_bytes(receipt, omit_hash=True)
    ).hexdigest()
    (ws / document_evidence.RECEIPT_REL).write_text(
        json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_receipt_invalid"
               for item in verdict["hard"])


def test_advisory_requires_converged_assembly(tmp_path, monkeypatch):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    rendered = ws / "output" / "quality.pdf"
    rendered.write_bytes(b"quality-bound-pdf")
    quality = _quality_for(rendered)
    receipt = document_evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
        input_path=artifact,
        output_path=rendered,
        exit_code=0,
        quality=quality,
    )
    document_evidence.write_receipt(ws, receipt)
    (ws / "output" / "verdict_v06.json").write_text(
        json.dumps({
            "proof_grade": "advisory",
            "converged": False,
            "checks": {"layout": "needs_review"},
            "style_anomalies": [],
        }), encoding="utf-8")
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    monkeypatch.setattr(
        submission_preflight, "_rerun_receipt_quality",
        lambda workspace, receipt, assembly_payload: quality,
    )
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_not_converged"
               for item in verdict["hard"])


def test_native_hancom_provenance_still_requires_converged_assembly(
    tmp_path, monkeypatch
):
    ws, artifact = _workspace(tmp_path, grade="hancom")
    rendered = ws / "output" / "native.pdf"
    rendered.write_bytes(b"native-rendered-pdf")
    receipt = document_evidence.build_receipt(
        ws,
        backend="native_hancom_windows",
        evidence_class="native_render",
        terminal_state="succeeded",
        input_path=artifact,
        output_path=rendered,
        input_role="assembled_hwpx",
        output_role="rendered_pdf",
        exit_code=0,
        quality=_quality_for(rendered, state="unknown", reason="type3_font"),
    )
    document_evidence.write_receipt(ws, receipt)
    (ws / "output" / "verdict_v06.json").write_text(
        json.dumps({
            "proof_grade": "hancom",
            "converged": False,
            "checks": {"layout": "needs_review"},
            "style_anomalies": [],
        }), encoding="utf-8")
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "proof_not_converged"
               for item in verdict["hard"])


def test_forged_valid_advisory_receipt_is_held_by_stage6_policy(
    tmp_path, monkeypatch
):
    ws, artifact = _workspace(tmp_path, grade="advisory")
    rendered = ws / "output" / "quality.pdf"
    rendered.write_bytes(b"quality-bound-pdf")
    receipt = document_evidence.build_receipt(
        ws,
        backend="oss_preview_libreoffice",
        evidence_class="advisory_render",
        terminal_state="succeeded",
        input_path=artifact,
        output_path=rendered,
        exit_code=0,
        quality=_quality_for(rendered),
    )
    # The shared release switch makes even a complete quality receipt derive
    # none; a forged advisory verdict must therefore be HARD at Stage 6.
    assert receipt["proof_grade"] == "none"
    document_evidence.write_receipt(ws, receipt)
    monkeypatch.setattr(submission_preflight, "_hwpx_text", lambda path: "content")
    verdict, code = submission_preflight.check(ws)
    assert code == 3
    assert any(item["code"] == "advisory_proof_release_hold"
               for item in verdict["hard"])
