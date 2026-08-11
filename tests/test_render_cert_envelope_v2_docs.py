from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t151_research_note_pins_exact_document_pathless_contract():
    text = _read("docs/research/render-cert-envelope-v2.md")
    for token in (
        "T151",
        "rigorloom/render-cert-envelope/v2",
        "rigorloom/render-cert-private-manifest/v2",
        "issue PRIVATE_MANIFEST --out CERT",
        "verify CERT",
        "check DOCUMENT CERT",
        "certificate_sha256",
        "certificate_hmac_sha256",
        "exact_document_measurement_only",
        "binding_scope: captured_snapshot_only",
        "runtime_binding: not_established",
        "proof_grade: none",
        "submission_grade: false",
        "promotion: not_run",
        "legacy",
        "certified_runtime_unbound",
        "ADVISORY_PROOF_RELEASE_ENABLED=False",
        "CERTIFIED_PROOF_RELEASE_ENABLED=False",
        "no renderer",
        "auto-route",
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


def test_t151_routing_docs_repeat_quarantine_and_no_promotion():
    paths = (
        "CHANGELOG.md",
        "README.md",
        "docs/trouble-table.md",
        "skill/SKILL.md",
        "skill/references/platform-backends.md",
        "modules/report/references/playbooks/stage-5.md",
        "modules/report/references/playbooks/stage-6.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = "\n".join(_read(path) for path in paths)
    for token in (
        "T151",
        "rigorloom/render-cert-envelope/v2",
        "private manifest",
        "certificate_hmac_sha256",
        "runtime_binding",
        "proof_grade",
        "submission_grade",
        "promotion",
        "CERTIFIED_PROOF_RELEASE_ENABLED",
        "certified_runtime_unbound",
        "no automatic",
    ):
        assert token in combined


def test_t151_docs_do_not_publish_operator_artifacts_or_local_paths():
    # Historical docs may mention the old v1 certificate interface. Keep this
    # privacy gate scoped to the new T151 note and its public contract.
    text = _read("docs/research/render-cert-envelope-v2.md").casefold()
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
