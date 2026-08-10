from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_t91_docs_pin_privacy_and_evidence_boundary():
    research = (ROOT / "docs" / "research" /
                "hwp-equation-diagnostic.md").read_text(encoding="utf-8")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "CHANGELOG.md",
            ROOT / "docs" / "golden-path.md",
            ROOT / "docs" / "trouble-table.md",
            ROOT / "skill" / "SKILL.md",
            ROOT / "skill" / "references" / "operations.md",
            ROOT / "skill" / "references" / "platform-backends.md",
            ROOT / "docs" / "research" / "hwp-equation-diagnostic.md",
        )
    )
    for fragment in (
        "rigorloom/hwp-equation-diagnostic/v1",
        "hwp-equation-diagnostic",
        "script_semantics:not_scanned",
        "comparison `unknown`",
        "proof `none`",
        "submission false",
        "per-script hashes",
        "expanded QName",
        "sin x",
        "sinx",
    ):
        assert fragment in combined
    assert "does not claim to understand HwpEqn" in " ".join(research.split())
    assert "https://swlab.hancom.co.kr/support/downloadCenter/hwpOwpml" in research
    assert "C:\\Users" not in combined
    assert "AppData" not in combined
