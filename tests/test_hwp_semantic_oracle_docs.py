"""T88 documentation and evidence-boundary regressions."""
from pathlib import Path


DOC = Path(__file__).parents[1] / "docs" / "research" / "hwp-semantic-oracle.md"


def test_t88_research_contract_has_official_sources_and_boundary():
    text = DOC.read_text(encoding="utf-8")
    for fragment in (
        "https://github.com/edwardkim/rhwp/tree/v0.8.2",
        "https://github.com/edwardkim/rhwp/releases/tag/v0.8.2",
        "https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md",
        "README_EN.md#cli-usage",
        "rigorloom/hwp-semantic-oracle/v1",
        "paired_converter_bounded_content_object_v1",
        "story_table_topology",
        "referenced_pictures",
        "explicit_controls",
        "style_definitions",
        "bounded content/object",
        "bounded_content_object_mismatch",
        "receipt-only",
        "source_fidelity: not_established",
        "`not_run`, proof `none`",
        "syhwp",
    ):
        assert fragment in text
    assert "output/form_copy.hwpx" in text
    assert "content_extract.semantic_fingerprint" in text
    assert "exactly `receipt.json`" in text
    assert "defense-in-depth guard" in text
    assert "forged/reserved" in text
    assert "candidate.hwpx" in text
    assert "argv" in text and "child output" in text
