from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "research" / "hwpx-definition-graph.md"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t153_research_note_pins_the_standalone_snapshot_contract() -> None:
    text = DOC.read_text(encoding="utf-8")
    required = (
        "T153",
        "rigorloom/hwpx-definition-graph/v1",
        "inspect INPUT.hwpx",
        "hwpx_definition_graph.py inspect INPUT.hwpx",
        "selected_definition_reference_graph_snapshot_only",
        "status: analyzed",
        "source{sha256,bytes}",
        "blocking_tokens",
        "not_scanned_tokens",
        "graph_sha256",
        "evidence_ceiling",
        "eligibility",
        "fontface",
        "substFont->BinData",
        "img->BinData",
        "payload identity",
        "image semantics",
        "pixels",
        "remain unscanned",
        "certificate",
        "runtime",
        "comparison: {state: unknown}",
        "render: {state: not_run}",
        "proof_grade: none",
        "submission_grade: false",
        "promotion: not_run",
        "does not execute a renderer",
        "no automatic route",
        "Stage 0",
        "Stage 5",
        "Stage 6",
        "new_report",
        "pathless",
        "no source text",
        "no absolute paths",
        "no raw bytes",
        "no document feature",
    )
    missing = [needle for needle in required if needle not in text]
    assert not missing, missing

    lowered = text.casefold()
    for forbidden in (
        "c:\\users\\",
        "appdata",
        "tests/corpus",
        "private\\",
        "candidate.pdf",
        "certificate.json",
    ):
        assert forbidden not in lowered

    for reason in (
        "input_unavailable",
        "input_too_large",
        "package_outside_supported_envelope",
        "definition_member_invalid",
        "definition_collection_invalid",
        "definition_count_mismatch",
        "definition_id_position_mismatch",
        "definition_reference_invalid",
        "definition_reference_unresolved",
        "section_reference_invalid",
        "binary_reference_invalid",
        "unsupported_definition_branch",
        "graph_limit_exceeded",
        "output_write_failed",
        "internal_error",
    ):
        assert reason in text


def test_t153_docs_repeat_quarantine_without_touching_release_routing() -> None:
    combined = "\n".join(
        _read(path)
        for path in (
            "CHANGELOG.md",
            "docs/trouble-table.md",
            "docs/research/hwpx-definition-graph.md",
        )
    )
    for token in (
        "T153",
        "rigorloom/hwpx-definition-graph/v1",
        "selected_definition_reference_graph_snapshot_only",
        "proof_grade: none",
        "submission_grade: false",
        "promotion: not_run",
        "comparison: {state: unknown}",
        "render: {state: not_run}",
        "no automatic route",
        "CERTIFIED_PROOF_RELEASE_ENABLED",
        "does not execute a renderer",
    ):
        assert token in combined


def test_t153_trouble_row_is_additive_and_keeps_the_existing_id_gap() -> None:
    text = _read("docs/trouble-table.md")
    ids = set(re.findall(r"^\| (T\d+) \|", text, flags=re.MULTILINE))
    assert "T153" in ids
    assert text.index("| T153 |") < text.index("| T152 |")
    for identifier in ("T106", "T107", "T108", "T110", "T111",
                       "T112", "T113", "T114", "T115"):
        assert identifier in ids
    assert "T109" not in ids
