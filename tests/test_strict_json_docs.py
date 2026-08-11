"""Documentation regression for T155 recursive duplicate-key handling."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t155_docs_pin_recursive_duplicate_refusal_and_boundaries():
    combined = "\n".join(
        _read(path)
        for path in (
            "CHANGELOG.md",
            "docs/trouble-table.md",
            "docs/golden-path.md",
            "docs/research/render-cert-envelope-v2.md",
        )
    )
    combined = " ".join(combined.split())
    for token in (
        "T155",
        "duplicate JSON object members",
        "nested object",
        "receipt_duplicate_key",
        "certificate_invalid_json",
        "operation_failed",
        "no authentication",
        "no automatic route",
        "proof_grade: none",
        "promotion: not_run",
        "quarantined and diagnostic-only",
        "duplicate-member rejection only",
        "does not expand canonical JSON",
        "non-finite-value",
        "HMAC semantics",
    ):
        assert token in combined


def test_t155_docs_keep_legacy_v1_out_of_the_release_route():
    text = _read("docs/research/render-cert-envelope-v2.md")
    assert "legacy `pipeline/scripts/render_cert.py` v1 certificate workflow" in text
    assert "certificate `verify`/`check`" in text
    assert "reports `certificate_invalid_json`" in text
    assert "reports `operation_failed`" in text
    assert "does not upgrade the closed" in text
    assert "auto-routes a document" in text
    assert "promotion: not_run" in text


def test_t156_docs_pin_finite_json_only_boundary():
    paths = (
        "CHANGELOG.md",
        "docs/trouble-table.md",
        "docs/golden-path.md",
        "docs/research/render-cert-envelope-v2.md",
        "docs/research/renderer-runtime-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T156",
        "receipt_nonfinite_value",
        "certificate_invalid_json",
        "operation_failed",
        "NaN",
        "Infinity",
        "-Infinity",
        "recursively",
        "allow_nan=False",
        "thresholds must be finite",
        "T151 and T152 were already strict and remain unchanged",
        "finite-JSON enforcement only",
        "no canonical JSON, HMAC, authentication, route, proof, promotion, or privacy expansion",
    ):
        assert token in combined

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T156 |") < trouble.index("| T155 |")
    assert trouble.index("| T155 |") < trouble.index("| T154 |")
    assert "| T109 |" not in trouble


def test_t157_docs_pin_legacy_public_summary_and_cli_privacy_boundary():
    paths = (
        "CHANGELOG.md",
        "README.md",
        "docs/trouble-table.md",
        "docs/golden-path.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T157",
        "verify_certificate",
        "ok",
        "reason_code",
        "reason_codes",
        "check_document",
        "eligible",
        "raw errors",
        "feature maps",
        "renderer streams",
        "private, pathful v1 operator artifacts",
        "never public receipts",
        "render_certificate_configured",
        "render_certificate_reason",
        "no `verify` subcommand",
        "no authentication",
        "no automatic",
        "proof",
        "submission",
        "release switches remain false",
    ):
        assert token in combined

    for path in ("README.md", "docs/golden-path.md", "CHANGELOG.md"):
        text = _read(path)
        assert "measure`/`certify`/`verify`/`check" not in text
        assert "measure/verify/check" not in text

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T157 |") < trouble.index("| T156 |")
    assert trouble.index("| T156 |") < trouble.index("| T155 |")
    assert trouble.index("| T155 |") < trouble.index("| T154 |")
    assert "| T109 |" not in trouble


def test_t158_docs_pin_legacy_private_artifact_custody_boundary():
    paths = (
        "CHANGELOG.md",
        "README.md",
        "docs/trouble-table.md",
        "docs/golden-path.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T158",
        "fresh private artifact publisher",
        "pre-created canonical parent",
        "absent output leaf",
        "regular one-link",
        "symlink",
        "reparse",
        "hardlink",
        "held-parent",
        "exact bytes",
        "identity",
        "owned-only rollback",
        "foreign replacements",
        "pathless `operation_failed`",
        "generic `write_json`",
        "`doc_backend`",
        "pathful private v1",
        "stdout/privacy",
        "authentication",
        "routing",
        "proof",
        "release-switch",
    ):
        assert token in combined

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T158 |") < trouble.index("| T157 |")
    assert trouble.index("| T157 |") < trouble.index("| T156 |")
    assert trouble.index("| T156 |") < trouble.index("| T155 |")
    assert "| T109 |" not in trouble


def test_t159_docs_pin_legacy_private_measurement_binding_boundary():
    paths = (
        "CHANGELOG.md",
        "README.md",
        "docs/trouble-table.md",
        "docs/golden-path.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T159",
        "safe single non-dot manifest ID segment",
        "before `mkdir`",
        "argv[0]",
        "configured binary",
        "bounded no-follow regular one-link",
        "source, reference, and candidate",
        "before and after render",
        "manifest reference hash",
        "fresh candidate",
        "alternate output",
        "candidate_pdf",
        "aliases either the manifest reference PDF or source document",
        "issue_certificate",
        "live manifest",
        "every document/reference/candidate path and hash",
        "second rebind",
        "before HMAC",
        "pathful private measure/certify payload",
        "public `verify_certificate` remains exactly four",
        "check` adds only `eligible`",
        "generic `write_json`",
        "`doc_backend`",
        "authentication",
        "execution",
        "eligibility",
        "routing",
        "proof",
        "submission",
        "promotion",
        "both release switches remain false",
    ):
        assert token in combined

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T159 |") < trouble.index("| T158 |")
    assert trouble.index("| T158 |") < trouble.index("| T157 |")
    assert trouble.index("| T157 |") < trouble.index("| T156 |")
    assert trouble.index("| T156 |") < trouble.index("| T155 |")
    assert "| T109 |" not in trouble


def test_t160_docs_pin_producer_snapshot_integrity_boundary():
    paths = (
        "CHANGELOG.md",
        "docs/trouble-table.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T160",
        "owned captured snapshots",
        "feature extraction",
        "renderer input",
        "PDF metrics",
        "captured snapshot files",
        "rather than rereading live",
        "After metrics",
        "final live document/reference/candidate generations are rebound",
        "mutation restored before the final check",
        "operator key is loaded",
        "immediately before HMAC",
        "live manifest",
        "every measurement document/reference/candidate generation",
        "public `verify_certificate` remains",
        "exact four-field projection",
        "`check_document` adds only `eligible`",
        "Schema",
        "routing",
        "proof",
        "release switches",
        "Successful measure/certify artifacts and stdout remain pathful private",
        "final pre-HMAC manifest drift publishes no stale certificate artifact",
        "generic failure/projection semantics otherwise remain unchanged",
    ):
        assert token in combined

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T160 |") < trouble.index("| T159 |")
    assert trouble.index("| T159 |") < trouble.index("| T158 |")
    assert trouble.index("| T158 |") < trouble.index("| T157 |")
    assert trouble.index("| T157 |") < trouble.index("| T156 |")
    assert trouble.index("| T156 |") < trouble.index("| T155 |")
    assert "| T109 |" not in trouble


def test_t161_docs_pin_reader_snapshot_custody_boundary():
    paths = (
        "CHANGELOG.md",
        "docs/trouble-table.md",
        "docs/research/render-cert-envelope-v2.md",
    )
    combined = " ".join(" ".join(_read(path).split()) for path in paths)
    for token in (
        "T161",
        "reader-side verifier custody",
        "current certificate",
        "manifest",
        "renderer binary",
        "check_document",
        "bounded no-follow regular one-link snapshots",
        "captured bytes",
        "owned staged copies",
        "self-hash/HMAC",
        "feature extraction",
        "renderer-version checks",
        "final rebind",
        "symlink",
        "hardlink",
        "certificate_changed",
        "manifest_changed",
        "renderer_binary_changed",
        "document_changed",
        "Historical measurement document/reference/candidate paths are not reread",
        "not public dependencies",
        "public `verify_certificate` remains exactly",
        "`check_document` adds only `eligible`",
        "private rich route",
        "Schema",
        "routing",
        "proof",
        "submission",
        "promotion",
        "release switches",
    ):
        assert token in combined

    trouble = _read("docs/trouble-table.md")
    assert trouble.index("| T161 |") < trouble.index("| T160 |")
    assert trouble.index("| T160 |") < trouble.index("| T159 |")
    assert trouble.index("| T159 |") < trouble.index("| T158 |")
    assert "| T109 |" not in trouble
