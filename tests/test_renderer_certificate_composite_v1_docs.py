from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t152_research_note_pins_the_closed_composite_contract():
    text = _read("docs/research/renderer-certificate-composite-v1.md")
    for token in (
        "T152",
        "rigorloom/renderer-certificate-composite/v1",
        "check WORKSPACE --run-id RUN_ID --binary BIN --certificate CERT --out RECEIPT",
        "verify WORKSPACE --run-id RUN_ID --binary BIN --certificate CERT",
        "output/proof/renderer-certificate-composite/<run-id>/receipt.json",
        "binding_scope: captured_snapshot_only",
        "runtime_input_exact_document_certificate_binding_only",
        "certificate_sha256",
        "certificate file SHA-256",
        "certificate-body digest",
        "operator key",
        "dependency_closure: unknown",
        'comparison: {\"state\":\"unknown\"}',
        'render: {\"state\":\"not_run\"}',
        "proof_grade: none",
        "submission_grade: false",
        "promotion: not_run",
        "does not execute a renderer",
        "auto-routes",
        "ADVISORY_PROOF_RELEASE_ENABLED=False",
        "CERTIFIED_PROOF_RELEASE_ENABLED=False",
    ):
        assert token in text

    lowered = text.casefold()
    for forbidden in (
        "c:\\users\\",
        "appdata",
        "tests/corpus",
        "private\\",
        "render_cert.key",
        "candidate.pdf",
        "certificate.json",
    ):
        assert forbidden not in lowered


def test_t152_routing_docs_repeat_snapshot_only_quarantine():
    paths = (
        "CHANGELOG.md",
        "README.md",
        "docs/trouble-table.md",
        "skill/SKILL.md",
        "skill/references/platform-backends.md",
        "modules/report/references/playbooks/stage-5.md",
        "modules/report/references/playbooks/stage-6.md",
        "docs/research/renderer-certificate-composite-v1.md",
    )
    combined = "\n".join(_read(path) for path in paths)
    for token in (
        "T152",
        "rigorloom/renderer-certificate-composite/v1",
        "captured_snapshot_only",
        "runtime_input_exact_document_certificate_binding_only",
        "certificate_sha256",
        "proof_grade",
        "submission_grade",
        "promotion",
        "CERTIFIED_PROOF_RELEASE_ENABLED",
        "no automatic",
    ):
        assert token in combined


def test_t152_research_note_does_not_publish_operator_artifacts():
    text = _read("docs/research/renderer-certificate-composite-v1.md").casefold()
    for forbidden in (
        "c:\\users\\",
        "appdata",
        "tests/corpus",
        "private\\",
        "render_cert.key",
        "candidate.pdf",
        "certificate.json",
    ):
        assert forbidden not in text
