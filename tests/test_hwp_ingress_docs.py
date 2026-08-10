"""Pin the public T85 evidence and privacy boundary."""
from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "docs" / "research" / "hwp-ingress-contract.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_hwp_ingress_contract_pins_primary_sources_and_evidence_classes():
    text = _text(RESEARCH)
    normalized = " ".join(text.split())
    for url in (
        "https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf",
        "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/05060311-bfce-4b12-874d-71fd4ce63aea",
        "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/9d33df18-7aee-4065-9121-4eabe41c29d4",
        "https://developer.hancom.com/hwpautomation",
    ):
        assert url in text
    for fragment in (
        "container capability, not semantic or render evidence",
        "one canonical adapter: Windows Hancom COM",
        "proof grade is always",
        "never kills a process",
        "source hash identifies the exact immutable bytes captured",
        "cannot reconstruct or re-prove a deleted source HWP",
    ):
        assert fragment in normalized


def test_hwp_ingress_docs_use_closed_schema_and_do_not_promise_fallback():
    combined = "\n".join(_text(path) for path in (
        RESEARCH,
        ROOT / "skill" / "SKILL.md",
        ROOT / "skill" / "references" / "operations.md",
        ROOT / "docs" / "golden-path.md",
    ))
    assert "rigorloom/hwp-ingress/v1" in combined
    assert "proof_grade: none" in combined
    assert "never falls back to LibreOffice or `rhwp`" in combined
    assert "--kill-stale" in combined
    assert "hwp_ingress.py verify" in combined
    assert "--ingress-receipt" in combined


def test_hwp_ingress_docs_do_not_leak_runtime_paths_or_artifact_hashes():
    text = _text(RESEARCH)
    assert not re.search(r"[A-Za-z]:[\\/]Users[\\/]", text)
    assert "AppData" not in text
    assert not re.search(r"\b[0-9a-f]{64}\b", text)
    assert "text_preview" not in text
