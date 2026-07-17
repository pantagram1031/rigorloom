"""Synthetic tests for deterministic per-claim evidence enforcement."""
from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_claims  # noqa: E402


def _workspace(tmp_path: Path, content: str | None = None) -> Path:
    ws = tmp_path / "report-synthetic"
    if content is not None:
        (ws / "bundle").mkdir(parents=True)
        (ws / "bundle" / "content.md").write_text(content, encoding="utf-8")
    return ws


def _write_claims(ws: Path, claims: list[dict]) -> None:
    (ws / "claims.yaml").write_text(
        json.dumps({"schema": "rigorloom-claims/v1", "claims": claims}),
        encoding="utf-8",
    )


def _evidence(source_id: str, quote: str = "Synthetic support.") -> list[dict]:
    return [{"source_id": source_id, "locator": "section 2", "quote": quote}]


def _codes(verdict: dict, severity: str) -> list[str]:
    return [item["code"] for item in verdict[severity]]


def test_no_ledger_is_single_warn_and_everything_else_is_noop(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)

    verdict, code = check_claims.check(ws)

    assert code == 0
    assert verdict["hard"] == []
    assert _codes(verdict, "warn") == ["ledger_missing"]


def test_require_ledger_blocks_a_deleted_ledger(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, "# Results\nThe measured delay was 12.5 ms.\n")

    verdict, code = check_claims.check(ws, require_ledger=True)

    assert code == 3
    assert _codes(verdict, "hard") == ["ledger_missing"]
    assert verdict["warn"] == []


def test_unledgered_numeric_and_citation_claims_warn(tmp_path: Path) -> None:
    marker = "(" + "Doe, " + "2024)"
    line = f"The measured delay was 12.5 ms {marker}."
    ws = _workspace(tmp_path, f"# Results\n{line}\n")
    _write_claims(ws, [])

    verdict, code = check_claims.check(ws)

    assert code == 0
    assert verdict["hard"] == []
    assert _codes(verdict, "warn").count("claim_unledgered") == 2
    assert {item["kind"] for item in verdict["warn"]} == {"numeric", "citation"}
    assert verdict["counts"]["unledgered"] == 2


def test_require_ledger_makes_unledgered_claims_hard(tmp_path: Path) -> None:
    marker = "(" + "Doe, " + "2024)"
    line = f"The measured delay was 12.5 ms {marker}."
    ws = _workspace(tmp_path, f"# Results\n{line}\n")
    _write_claims(ws, [])

    verdict, code = check_claims.check(ws, require_ledger=True)

    assert code == 3
    assert verdict["warn"] == []
    assert _codes(verdict, "hard").count("claim_unledgered") == 2
    assert verdict["counts"]["unledgered"] == 2


def test_missing_ledger_source_is_hard(tmp_path: Path) -> None:
    line = "The measured delay was 12.5 ms."
    ws = _workspace(tmp_path, line + "\n")
    missing = "10." + "1234/missing-ledger-source"
    _write_claims(ws, [{
        "id": "measured-delay", "text": line, "kind": "numeric",
        "evidence": _evidence(missing),
    }])

    verdict, code = check_claims.check(ws)

    assert code == 3
    assert "claim_source_missing" in _codes(verdict, "hard")


def test_url_only_source_is_resolved_but_warned_as_unverifiable(
    tmp_path: Path,
) -> None:
    url = "https://example.invalid/fabricated-source"
    line = "The measured delay was 12.5 ms."
    content = (
        f"{line}\n\n"
        "# References\n\n"
        f"- Synthetic Author (2024). URL-only evidence. {url}\n"
    )
    ws = _workspace(tmp_path, content)
    _write_claims(ws, [{
        "id": "measured-delay", "text": line, "kind": "numeric",
        "evidence": _evidence(url),
    }])

    verdict, code = check_claims.check(ws)

    assert code == 0, verdict
    assert "claim_source_missing" not in _codes(verdict, "hard")
    assert _codes(verdict, "warn") == ["claim_source_unverifiable"]
    assert verdict["warn"][0]["claim_id"] == "measured-delay"


def test_numeric_or_citation_claim_without_evidence_is_hard(tmp_path: Path) -> None:
    line = "The measured delay was 12.5 ms."
    ws = _workspace(tmp_path, line + "\n")
    _write_claims(ws, [{
        "id": "measured-delay", "text": line, "kind": "numeric",
        "evidence": [],
    }])

    verdict, code = check_claims.check(ws)

    assert code == 3
    assert _codes(verdict, "hard") == ["claim_unevidenced"]
    assert verdict["warn"] == []


def test_full_ledger_and_reference_fixture_passes_cleanly(tmp_path: Path) -> None:
    doi = "10." + "1234/traceable-study"
    marker = "(" + "Doe, " + "2024)"
    line = f"The measured delay was 12.5 ms {marker}."
    content = (
        "# Results\n"
        f"{line}\n\n"
        "# References\n\n"
        f"- Doe (2024). Traceable Delay Study. Journal. DOI: {doi}\n"
    )
    ws = _workspace(tmp_path, content)
    _write_claims(ws, [{
        "id": "measured-delay", "text": line, "kind": "numeric",
        "evidence": _evidence(doi, "The delay was 12.5 ms."),
    }])

    verdict, code = check_claims.check(ws)

    assert code == 0, verdict
    assert verdict["hard"] == []
    assert verdict["warn"] == []
    assert verdict["counts"]["unledgered"] == 0
    assert verdict["counts"]["numeric_claims"] == 1
    assert verdict["counts"]["citation_markers"] == 1
