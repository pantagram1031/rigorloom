from pathlib import Path


DOC = Path(__file__).parents[1] / "docs" / "research" / "hwp-source-coverage.md"


def test_t89_doc_states_closed_boundary_and_nonclaims():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "rigorloom/hwp-source-coverage/v1",
        "BodyText/Section0..N",
        "bodytext_record_envelope_v1",
        "bodytext.paragraph_header_auxiliary_fields",
        "24-byte ParaHeader",
        "docinfo.reference_graph",
        "T89 currently makes no\nsemantic `eligible` claim",
        "https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf",
        "https://github.com/sysphere/syhwp/tree/d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed",
        "checked 2026-08-10",
        "syhwp is not",
        "comparison` remains `unknown",
        "render` is `not_run",
        "proof_grade`\nis `none",
        "submission_grade` is false",
        "public forms contain",
        "analyzed ineligible",
        "source fidelity",
        "conversion parity",
        "native execution",
        "render quality",
    ]
    for needle in required:
        assert needle in text
    forbidden = ["--out", "candidate.hwpx", "new_report", "Stage 0 acceptance"]
    for needle in forbidden:
        assert needle not in text


def test_t89_doc_has_receipt_only_commands():
    text = DOC.read_text(encoding="utf-8")
    assert "hwp-source-coverage --run-id HEX" in text
    assert "receipt.json" in text
    assert "raw control IDs" in text
    assert "absolute paths" in text
