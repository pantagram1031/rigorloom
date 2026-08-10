from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_t93_docs_pin_receipt_custody_and_certified_quarantine():
    paths = (
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "trouble-table.md",
        ROOT / "docs" / "golden-path.md",
        ROOT / "modules" / "report" / "references" / "playbooks" / "stage-5.md",
        ROOT / "modules" / "report" / "references" / "playbooks" / "stage-6.md",
        ROOT / "skill" / "SKILL.md",
        ROOT / "skill" / "references" / "platform-backends.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "T93" in text
    assert "CERTIFIED_PROOF_RELEASE_ENABLED" in text
    assert "certified_runtime_unbound" in text
    assert "one-link" in text
    assert "final" in text.casefold() and "receipt" in text.casefold()
    assert "proof grade" in text.casefold() or "proof_grade" in text.casefold()
    platform = (ROOT / "skill" / "references" / "platform-backends.md").read_text(
        encoding="utf-8"
    )
    assert "`certified_render` → `none` (quarantined)" in platform
    assert "quarantined `certified_render` (`none`)" in platform
    golden = (ROOT / "docs" / "golden-path.md").read_text(encoding="utf-8")
    assert "HARD-quarantined and cannot currently pass" in golden
