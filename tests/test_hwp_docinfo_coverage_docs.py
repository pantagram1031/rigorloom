from pathlib import Path


DOC = Path(__file__).parents[1] / "docs" / "research" / "hwp-docinfo-coverage.md"


def test_t90_doc_pins_closed_scope_sources_and_nonclaims():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "rigorloom/hwp-docinfo-coverage/v1",
        "docinfo_record_cardinality_and_bodytext_reference_bounds_v1",
        "hwp-docinfo-coverage/<run-id>/receipt.json",
        "case-insensitive on Windows",
        "receipt hard links",
        "ID_MAPPINGS",
        "zero-based",
        "ID 0",
        "BodyText ParaHeader",
        "ParaCharShape",
        "definition payload semantics",
        "generated numbering",
        "eligibility` remains `unknown",
        "comparison` remains `unknown",
        "render` is `not_run",
        "proof_grade` is `none",
        "submission_grade` is false",
        "source fidelity",
        "conversion parity",
        "native execution",
        "render quality",
        "https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf",
        "https://tech.hancom.com/python-hwp-parsing-1/",
        "https://tech.hancom.com/python-hwp-parsing-2/",
        "https://github.com/mete0r/pyhwp/tree/83239f0d3bdf438b2c9f7dcff455a6e841154a39",
        "checked 2026-08-10",
        "corroboration only",
        "10 public HWP",
        "all 10 are refused",
        "bodytext.envelope_incomplete",
        "no raw IDs",
        "style names",
        "numbering formats",
        "bullet glyphs",
        "absolute paths",
    ]
    for needle in required:
        assert needle in text


def test_t90_doc_has_receipt_only_commands_and_privacy_boundary():
    text = DOC.read_text(encoding="utf-8")
    assert "hwp_docinfo_coverage.py inspect INPUT.hwp" in text
    assert "hwp_docinfo_coverage.py verify INPUT.hwp" in text
    for forbidden in ("--out", "candidate.hwpx", "C:\\Users\\"):
        assert forbidden not in text
