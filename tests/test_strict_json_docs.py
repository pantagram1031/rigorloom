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
