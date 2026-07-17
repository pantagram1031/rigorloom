#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministically trace report numerals/citations through claims.yaml.

No ledger is legacy-safe by default: one ledger_missing WARN and no other
work. With a ledger present, structural errors are usage failures, untraced
body numeric/citation content is WARN, and provably missing support is HARD.
Without --require-ledger, a fabricated number simply omitted from the ledger
passes this gate with a WARN: the default ledger provides auditability, not
blocking. Strict campaign runs use --require-ledger to make a missing ledger
or any numeric/citation claim_unledgered finding HARD.
No network or model calls are made.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)
from claim_extraction import extract_numeric_claims, find_body  # noqa: E402
import claims_ledger  # noqa: E402


PAREN_CITATION_RE = re.compile(
    r"\([^\n()]{1,80},\s*(?:18|19|20|21)\d{2}[a-z]?\)", re.I
)
NUMERIC_CITATION_RE = re.compile(
    r"(?<!\[)\[(?:\d{1,3}(?:\s*[-\u2013,]\s*\d{1,3})*)\](?!\])"
)
PANDOC_CITATION_RE = re.compile(
    r"\[@[A-Za-z0-9_.:-]+(?:\s*;\s*@[A-Za-z0-9_.:-]+)*\]"
)
NARRATIVE_CITATION_RE = re.compile(
    r"\b[A-Z][A-Za-z'\u2019-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\u2019-]+)?"
    r"\s+\((?:18|19|20|21)\d{2}[a-z]?\)"
)
CITATION_PATTERNS = (
    PANDOC_CITATION_RE,
    PAREN_CITATION_RE,
    NARRATIVE_CITATION_RE,
    NUMERIC_CITATION_RE,
)


def _usage(ws: Path, message: str, findings=None) -> tuple[dict, int]:
    return usage_error(
        str(ws),
        "check_claims",
        message,
        counts={
            "hard": 0, "warn": 0, "ledger_entries": 0,
            "numeric_claims": 0, "citation_markers": 0, "unledgered": 0,
        },
        extra={"ledger_findings": list(findings or [])},
    )


def extract_citation_markers(text: str) -> list[dict[str, Any]]:
    """Return non-overlapping body citation markers with stable locations."""
    cleaned = find_body(text)
    matches: list[tuple[int, int, str]] = []
    for pattern in CITATION_PATTERNS:
        for match in pattern.finditer(cleaned):
            matches.append((match.start(), match.end(), match.group(0)))
    selected: list[tuple[int, int, str]] = []
    for start, end, marker in sorted(matches, key=lambda item: (item[0], -item[1])):
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in selected):
            continue
        selected.append((start, end, marker))
    lines = cleaned.splitlines()
    markers: list[dict[str, Any]] = []
    for start, _end, marker in selected:
        line = cleaned.count("\n", 0, start) + 1
        snippet = lines[line - 1].strip() if 1 <= line <= len(lines) else marker
        markers.append({"marker": marker, "line": line, "snippet": snippet[:240]})
    return markers


def _without_citations(text: str) -> str:
    for pattern in CITATION_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _normalized_assertion(text: str, *, remove_citations: bool = False) -> str:
    if remove_citations:
        text = _without_citations(text)
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"^\s*(?:#{1,6}|[-*+])\s*", "", normalized)
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _assertion_overlap(left: str, right: str, *, citations: bool = False) -> bool:
    left_key = _normalized_assertion(left, remove_citations=citations)
    right_key = _normalized_assertion(right, remove_citations=citations)
    return bool(left_key and right_key) and (
        left_key in right_key or right_key in left_key
    )


def _numeric_entry_values(entry: dict[str, Any]) -> set[float]:
    claims, _ = extract_numeric_claims(entry["text"], policy="saeteuk")
    return {claim["value"] for claim in claims}


def _numeric_traced(
    candidate: dict[str, Any], line_text: str, entries: list[dict[str, Any]]
) -> bool:
    for entry in entries:
        if candidate["value"] not in _numeric_entry_values(entry):
            continue
        if _assertion_overlap(entry["text"], line_text):
            return True
    return False


def _citation_traced(marker: dict[str, Any], entries: list[dict[str, Any]]) -> bool:
    marker_key = unicodedata.normalize("NFKC", marker["marker"]).casefold()
    for entry in entries:
        entry_key = unicodedata.normalize("NFKC", entry["text"]).casefold()
        if marker_key in entry_key:
            return True
        if _assertion_overlap(entry["text"], marker["snippet"], citations=True):
            return True
    return False


def check(
    workspace: str | Path, *, require_ledger: bool = False
) -> tuple[dict, int]:
    ws = Path(workspace)
    ledger_path = ws / claims_ledger.LEDGER_NAME
    if not ledger_path.is_file():
        finding = {
            "code": "ledger_missing",
            "msg": (
                "claims.yaml is absent; claim tracing cannot run"
            ),
            "at": str(ledger_path),
        }
        hard = [finding] if require_ledger else []
        warn = [] if require_ledger else [finding]
        verdict = verdict_skeleton(
            str(ws),
            "check_claims",
            hard=hard,
            warn=warn,
            counts={
                "hard": len(hard), "warn": len(warn), "ledger_entries": 0,
                "numeric_claims": 0, "citation_markers": 0, "unledgered": 0,
            },
        )
        return verdict, exit_code(hard=hard)

    try:
        ledger = claims_ledger.load_claims(ws, validate_sources=False)
    except claims_ledger.ClaimsLedgerError as exc:
        return _usage(ws, str(exc), exc.findings)

    content_path = ws / "bundle" / "content.md"
    try:
        markdown = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _usage(ws, "bundle/content.md not found")
    except (OSError, UnicodeError) as exc:
        return _usage(ws, f"bundle/content.md unreadable: {exc}")

    hard: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    entries = ledger["claims"]
    for entry in entries:
        if entry["kind"] in {"numeric", "citation"} and not entry["evidence"]:
            hard.append({
                "code": "claim_unevidenced",
                "msg": (
                    "numeric and citation ledger entries require at least one "
                    "evidence item"
                ),
                "at": entry["id"],
                "claim_id": entry["id"],
                "kind": entry["kind"],
            })

    source_groups = claims_ledger.source_identity_groups(ws, markdown)
    available = set().union(*source_groups)
    hard.extend(claims_ledger.dangling_source_findings(ledger, available))
    for entry in entries:
        for evidence in entry["evidence"]:
            source_id = evidence["source_id"]
            resolved = claims_ledger.resolved_source_tokens(
                source_id, source_groups
            )
            has_url = any(token.startswith("url:") for token in resolved)
            has_verifiable_id = any(
                token.startswith(("doi:", "isbn:")) for token in resolved
            )
            if has_url and not has_verifiable_id:
                warn.append({
                    "code": "claim_source_unverifiable",
                    "msg": (
                        "claim evidence resolves only to a URL; DOI/ISBN "
                        "verification is unavailable"
                    ),
                    "at": source_id,
                    "claim_id": entry["id"],
                    "source_id": source_id,
                })

    body = claims_ledger.body_without_references(markdown)
    numeric_claims, _ = extract_numeric_claims(body, policy="saeteuk")
    citation_markers = extract_citation_markers(body)
    body_lines = body.splitlines()
    numeric_entries = [entry for entry in entries if entry["kind"] == "numeric"]
    # A cited numeric assertion remains one numeric ledger entry; its matching
    # evidence also traces the citation marker, avoiding duplicate ledger rows.
    citation_entries = [
        entry for entry in entries
        if entry["kind"] in {"numeric", "citation"}
    ]

    unledgered: list[dict[str, Any]] = []
    for candidate in numeric_claims:
        line_number = candidate["line"]
        line_text = (
            body_lines[line_number - 1]
            if 1 <= line_number <= len(body_lines)
            else candidate["snippet"]
        )
        if not _numeric_traced(candidate, line_text, numeric_entries):
            unledgered.append({
                "code": "claim_unledgered",
                "msg": "body numeric claim has no matching numeric ledger entry",
                "at": candidate["raw"],
                "line": line_number,
                "kind": "numeric",
                "snippet": candidate["snippet"],
            })

    for marker in citation_markers:
        if not _citation_traced(marker, citation_entries):
            unledgered.append({
                "code": "claim_unledgered",
                "msg": "body citation marker has no matching citation ledger entry",
                "at": marker["marker"],
                "line": marker["line"],
                "kind": "citation",
                "snippet": marker["snippet"],
            })
    (hard if require_ledger else warn).extend(unledgered)

    verdict = verdict_skeleton(
        str(ws),
        "check_claims",
        hard=hard,
        warn=warn,
        counts={
            "hard": len(hard),
            "warn": len(warn),
            "ledger_entries": len(entries),
            "numeric_claims": len(numeric_claims),
            "citation_markers": len(citation_markers),
            "unledgered": len(unledgered),
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="trace body numeric/citation claims through claims.yaml"
    )
    parser.add_argument("workspace", help="report workspace directory")
    parser.add_argument(
        "--require-ledger",
        action="store_true",
        help="HARD-fail a missing ledger or unledgered numeric/citation claim",
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    return cli_main(
        parser,
        lambda args: check(
            args.workspace, require_ledger=args.require_ledger
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
