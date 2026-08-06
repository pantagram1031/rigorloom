"""Synthetic contract tests for the workspace claim ledger."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import claims_ledger  # noqa: E402


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "report-synthetic"
    (ws / "bundle").mkdir(parents=True)
    (ws / "research").mkdir()
    (ws / "research" / "sources.json").write_text("[]\n", encoding="utf-8")
    return ws


def test_loads_valid_block_yaml_and_validates_schema(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    source_id = "local-" + "evidence-1"
    (ws / "research" / "sources.json").write_text(
        json.dumps([{"id": source_id, "title": "Synthetic source"}]),
        encoding="utf-8",
    )
    (ws / "claims.yaml").write_text(
        "schema: rigorloom-claims/v1\n"
        "claims:\n"
        "  - id: measured-delay\n"
        '    text: "The measured delay was 12.5 ms."\n'
        "    kind: numeric\n"
        "    evidence:\n"
        f'      - source_id: "{source_id}"\n'
        '        locator: "Table 2"\n'
        '        quote: "The delay was 12.5 ms."\n',
        encoding="utf-8",
    )

    ledger = claims_ledger.load_claims(ws)

    assert ledger["schema"] == "rigorloom-claims/v1"
    assert ledger["claims"][0]["evidence"][0]["source_id"] == source_id


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["claims"][0].pop("text"),
        lambda payload: payload["claims"][0].update(kind="speculative"),
        lambda payload: payload["claims"][0].update(id="Not A Stable Slug"),
        lambda payload: payload["claims"][0].update(extra="not allowed"),
    ],
)
def test_schema_invalid_entries_are_rejected(tmp_path: Path, mutation) -> None:
    ws = _workspace(tmp_path)
    payload = {
        "schema": "rigorloom-claims/v1",
        "claims": [{
            "id": "valid-claim", "text": "A valid qualitative claim.",
            "kind": "qualitative", "evidence": [],
        }],
    }
    mutation(payload)
    (ws / "claims.yaml").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(claims_ledger.ClaimsLedgerError) as caught:
        claims_ledger.load_claims(ws, validate_sources=False)

    assert any(
        finding["code"] == "claim_schema_invalid"
        for finding in caught.value.findings
    )


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    claim = {
        "id": "same-id", "text": "Synthetic claim.",
        "kind": "qualitative", "evidence": [],
    }
    payload = {"schema": "rigorloom-claims/v1", "claims": [claim, dict(claim)]}
    (ws / "claims.yaml").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(claims_ledger.ClaimsLedgerError) as caught:
        claims_ledger.load_claims(ws, validate_sources=False)

    assert {item["code"] for item in caught.value.findings} == {
        "claim_id_duplicate"
    }


@pytest.mark.parametrize("field", ["text", "locator", "quote"])
def test_min_length_rejects_whitespace_only_strings(
    tmp_path: Path, field: str,
) -> None:
    ws = _workspace(tmp_path)
    evidence = {
        "source_id": "synthetic-source",
        "locator": "section 1",
        "quote": "Synthetic support.",
    }
    claim = {
        "id": "whitespace-value",
        "text": "Synthetic claim.",
        "kind": "qualitative",
        "evidence": [evidence],
    }
    target = claim if field == "text" else evidence
    target[field] = "   "
    (ws / "claims.yaml").write_text(
        json.dumps({"schema": "rigorloom-claims/v1", "claims": [claim]}),
        encoding="utf-8",
    )

    with pytest.raises(claims_ledger.ClaimsLedgerError) as caught:
        claims_ledger.load_claims(ws, validate_sources=False)

    assert any(
        finding["code"] == "claim_schema_invalid"
        and "minLength" in finding["msg"]
        for finding in caught.value.findings
    )


def test_duplicate_evidence_items_are_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    evidence = {
        "source_id": "synthetic-source",
        "locator": "section 1",
        "quote": "Synthetic support.",
    }
    claim = {
        "id": "duplicate-evidence",
        "text": "Synthetic claim.",
        "kind": "qualitative",
        "evidence": [evidence, dict(evidence)],
    }
    (ws / "claims.yaml").write_text(
        json.dumps({"schema": "rigorloom-claims/v1", "claims": [claim]}),
        encoding="utf-8",
    )

    with pytest.raises(claims_ledger.ClaimsLedgerError) as caught:
        claims_ledger.load_claims(ws, validate_sources=False)

    assert any(
        finding["code"] == "claim_schema_invalid"
        and "uniqueItems" in finding["msg"]
        for finding in caught.value.findings
    )


def test_dangling_source_ids_are_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    missing_id = "missing-" + "source"
    payload = {
        "schema": "rigorloom-claims/v1",
        "claims": [{
            "id": "dangling-source", "text": "Synthetic claim.",
            "kind": "qualitative",
            "evidence": [{
                "source_id": missing_id,
                "locator": "section 1",
                "quote": "Synthetic support.",
            }],
        }],
    }
    (ws / "claims.yaml").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(claims_ledger.ClaimsLedgerError) as caught:
        claims_ledger.load_claims(ws)

    finding = caught.value.findings[0]
    assert finding["code"] == "claim_source_missing"
    assert finding["source_id"] == missing_id


def test_claim_extract_writes_stable_numeric_skeleton(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    hostile_tail = " evidence:" + " []" + chr(10) + "  - id: injected"
    (ws / "bundle" / "content.md").write_text(
        "# Results\n"
        "The measured delay was 12.5 ms.\n"
        f"A label contained {hostile_tail}.\n",
        encoding="utf-8",
    )

    first = claims_ledger.claim_extract(ws)
    first_bytes = (ws / "claims.yaml").read_bytes()
    second = claims_ledger.claim_extract(ws, force=True)

    assert first == second
    assert (ws / "claims.yaml").read_bytes() == first_bytes
    assert len(first["claims"]) == 1
    claim = first["claims"][0]
    assert claim["kind"] == "numeric"
    assert claim["evidence"] == []
    assert claim["id"].startswith("numeric-measured-delay")
    assert claims_ledger.load_claims(ws, validate_sources=False) == first
