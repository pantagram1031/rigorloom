from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "docs" / "research" / "hwp-diagnostic-candidate.md"


def test_t86_research_names_upstream_v082_sources_and_cli_contract():
    text = RESEARCH.read_text(encoding="utf-8")
    for url in (
        "https://github.com/edwardkim/rhwp/tree/v0.8.2",
        "https://github.com/edwardkim/rhwp/releases/tag/v0.8.2",
        "https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md",
        "https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md#cli-usage",
    ):
        assert url in text
    for token in (
        "rigorloom/hwp-diagnostic-candidate/v1",
        "work/stage-0/scratch/hwp-diagnostic",
        "--rhwp",
        "--rhwp-sha256",
        "export-hwpx INPUT OUTPUT --verify --verify-pages",
        "comparison",
        "state: unknown",
        "render",
        "proof_grade",
        "pyhwp",
        "LibreOffice",
    ):
        assert token in text


def test_t86_docs_keep_operator_evidence_outside_the_repository():
    text = RESEARCH.read_text(encoding="utf-8")
    for token in (
        "d99b952ce2322d59530b86453a7314ebe18e86bdea165d2b75ef0b2af39ec6de",
        "e38215daddf63b284cbe05322541b44f65efd727ce7f50b9b4ffd94930e7ab72",
        "f386eca6c327a37a2fd965a56efacc50d51e3cec178313364e184656443570c3",
        "23d695387304bf7a29afab382e00617f09240a4aa47fcb7f0558e29ff1d5c2a4",
        "26,082",
        "tables 3",
        "pictures 1",
        "equations 0",
        "8.5 seconds",
        "not shipped",
        "MIT",
        "THIRD_PARTY_LICENSES.md",
    ):
        assert token in text
    # Runtime evidence must not turn into a user- or machine-specific path.
    lowered = text.casefold()
    assert "c:\\users\\" not in lowered
    assert "appdata" not in lowered
    assert "private\\" not in lowered
    assert "tests/corpus" not in lowered
    assert ".hwp" in lowered and ".hwpx" in lowered


def test_t86_routing_docs_repeat_the_quarantine_boundary():
    paths = (
        ROOT / "docs" / "golden-path.md",
        ROOT / "docs" / "trouble-table.md",
        ROOT / "skill" / "SKILL.md",
        ROOT / "skill" / "references" / "operations.md",
        ROOT / "skill" / "references" / "platform-backends.md",
        ROOT / "modules" / "report" / "references" / "playbooks" / "stage-0.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "T86" in combined
    assert "rigorloom/hwp-diagnostic-candidate/v1" in combined
    assert "work/stage-0/scratch/hwp-diagnostic" in combined
    assert "proof_grade" in combined and "not_run" in combined
    assert "LibreOffice" in combined and "pyhwp" in combined
    assert "new_report --ingress-receipt" in combined
    assert "no owned candidate or receipt" in combined
