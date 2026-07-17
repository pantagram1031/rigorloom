#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load, validate, and mechanically seed the workspace claim ledger.

``claims.yaml`` is JSON-Schema governed but intentionally permits an empty
``evidence`` list. That makes ``claim_extract`` able to write a structural
skeleton; ``check_claims`` is the enforcement point that HARD-fails empty
evidence for numeric and citation claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urldefrag, urlsplit, urlunsplit
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import check_sources  # noqa: E402
from checker_base import _utf8_stdio, dump_json  # noqa: E402
from claim_extraction import extract_numeric_claims  # noqa: E402


LEDGER_SCHEMA = "rigorloom-claims/v1"
SCHEMA_PATH = (
    SCRIPTS_DIR.parent / "references" / "schemas" / "claims.schema.json"
)
LEDGER_NAME = "claims.yaml"


class ClaimsLedgerError(ValueError):
    """One or more structural or semantic ledger errors."""

    def __init__(self, findings: list[dict[str, Any]]):
        self.findings = findings
        message = "; ".join(str(item.get("msg", item)) for item in findings)
        super().__init__(message)


def _yaml_scalar(token: str) -> Any:
    token = token.strip()
    if not token:
        return None
    try:
        return json.loads(token)
    except json.JSONDecodeError:
        return token


def _parse_yaml_subset(text: str) -> Any:
    """Parse the documented ledger block-YAML shape without PyYAML."""
    rows: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError(f"tabs are not valid indentation at line {number}")
        content = raw.lstrip(" ")
        rows.append((len(raw) - len(content), content, number))
    if not rows:
        return None
    position = 0

    def pair(content: str, indent: int, mapping: dict[str, Any]) -> None:
        nonlocal position
        key, separator, value = content.partition(":")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"expected key: value near {content!r}")
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        value = value.strip()
        if value:
            mapping[key] = _yaml_scalar(value)
        elif position < len(rows) and rows[position][0] > indent:
            mapping[key] = block(rows[position][0])
        else:
            mapping[key] = None

    def block(indent: int) -> Any:
        nonlocal position
        if position >= len(rows) or rows[position][0] != indent:
            raise ValueError("invalid YAML indentation")
        if rows[position][1].startswith("- "):
            sequence: list[Any] = []
            while position < len(rows):
                row_indent, content, number = rows[position]
                if row_indent != indent or not content.startswith("- "):
                    break
                rest = content[2:].strip()
                position += 1
                if not rest:
                    if position >= len(rows) or rows[position][0] <= indent:
                        raise ValueError(f"empty sequence item at line {number}")
                    sequence.append(block(rows[position][0]))
                    continue
                if ":" not in rest:
                    sequence.append(_yaml_scalar(rest))
                    continue
                item: dict[str, Any] = {}
                item_indent = indent + 2
                pair(rest, item_indent, item)
                while position < len(rows):
                    next_indent, next_content, _ = rows[position]
                    if next_indent <= indent:
                        break
                    if next_indent != item_indent or next_content.startswith("- "):
                        raise ValueError(
                            f"invalid mapping indentation at line {rows[position][2]}"
                        )
                    position += 1
                    pair(next_content, item_indent, item)
                sequence.append(item)
            return sequence

        mapping: dict[str, Any] = {}
        while position < len(rows):
            row_indent, content, _ = rows[position]
            if row_indent != indent or content.startswith("- "):
                break
            position += 1
            pair(content, indent, mapping)
        return mapping

    payload = block(rows[0][0])
    if position != len(rows):
        raise ValueError(f"unparsed YAML content at line {rows[position][2]}")
    return payload


def parse_ledger_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _parse_yaml_subset(text)


_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _schema_errors(
    instance: Any, schema: dict[str, Any], where: str = "$"
) -> list[str]:
    """Validate every JSON-Schema keyword used by claims.schema.json."""
    errors: list[str] = []
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]
    if expected is not None and not any(
        _TYPE_CHECKS.get(kind, lambda _value: False)(instance)
        for kind in expected_types
    ):
        errors.append(
            f"{where}: expected type {expected!r}, got {type(instance).__name__}"
        )
        return errors
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{where}: value must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{where}: value {instance!r} not in {schema['enum']!r}")
    if isinstance(instance, str):
        if len(instance.strip()) < schema.get("minLength", 0):
            errors.append(f"{where}: string is shorter than minLength")
        if len(instance) > schema.get("maxLength", len(instance)):
            errors.append(f"{where}: string is longer than maxLength")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, instance) is None:
            errors.append(f"{where}: string does not match {pattern!r}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{where}: array has fewer than minItems")
        if schema.get("uniqueItems") and any(
            item == prior
            for index, item in enumerate(instance)
            for prior in instance[:index]
        ):
            errors.append(f"{where}: array items must satisfy uniqueItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(_schema_errors(item, item_schema, f"{where}[{index}]"))
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{where}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{where}: additional property {key!r} not allowed")
        for key, subschema in properties.items():
            if key in instance:
                errors.extend(
                    _schema_errors(instance[key], subschema, f"{where}.{key}")
                )
    return errors


def _schema_findings(payload: Any) -> list[dict[str, Any]]:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{
            "code": "claim_schema_invalid",
            "msg": f"claim ledger schema unreadable: {exc}",
            "at": str(SCHEMA_PATH),
        }]
    return [
        {"code": "claim_schema_invalid", "msg": error, "at": LEDGER_NAME}
        for error in _schema_errors(payload, schema)
    ]


def _duplicate_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    findings: list[dict[str, Any]] = []
    for index, claim in enumerate(payload.get("claims", [])):
        claim_id = claim.get("id")
        if claim_id in seen:
            findings.append({
                "code": "claim_id_duplicate",
                "msg": "claim ledger ids must be unique",
                "at": claim_id,
                "claim_id": claim_id,
                "index": index,
            })
        seen.add(claim_id)
    return findings


def _canonical_url(value: str) -> str | None:
    cleaned = check_sources._clean_terminal_token(value)
    try:
        parts = urlsplit(urldefrag(cleaned)[0])
    except ValueError:
        return None
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((
        parts.scheme.casefold(), parts.netloc.casefold(),
        parts.path, parts.query, "",
    ))


def source_id_tokens(value: str) -> set[str]:
    """Return typed aliases using check_sources' DOI/ISBN/URL rules."""
    if not isinstance(value, str) or not value.strip():
        return set()
    raw = value.strip()
    tokens = {"id:" + raw}

    doi_match = check_sources.DOI_URL_RE.search(raw)
    doi_candidate = doi_match.group("doi") if doi_match else raw
    if doi_candidate.casefold().startswith("doi:"):
        doi_candidate = doi_candidate.split(":", 1)[1].strip()
    doi_candidate = check_sources._clean_terminal_token(doi_candidate)
    if check_sources.DOI_RE.fullmatch(doi_candidate):
        tokens.add("doi:" + doi_candidate.casefold())

    isbn_candidate = raw
    if isbn_candidate.casefold().startswith("isbn") and ":" in isbn_candidate:
        isbn_candidate = isbn_candidate.split(":", 1)[1]
    isbn13 = check_sources._isbn13(isbn_candidate)
    if isbn13:
        tokens.add("isbn:" + isbn13)

    url = _canonical_url(raw)
    if url:
        tokens.add("url:" + url)
    return tokens


def _source_record_tokens(record: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    source_id = record.get("id")
    if isinstance(source_id, str) and source_id.strip():
        tokens.update(source_id_tokens(source_id))
    for key in ("doi", "isbn", "url"):
        value = record.get(key)
        if isinstance(value, str):
            tokens.update(source_id_tokens(value))
    return tokens


def source_identity_groups(
    workspace: str | Path, markdown: str | None = None
) -> list[set[str]]:
    """Group aliases for each reference-list and evidence-pack source."""
    ws = Path(workspace)
    groups: list[set[str]] = []
    if markdown is None:
        try:
            markdown = (ws / "bundle" / "content.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            markdown = ""
    for entry in check_sources.parse_reference_entries(markdown):
        tokens: set[str] = set()
        for key in ("doi", "isbn", "url"):
            value = entry.get(key)
            if isinstance(value, str):
                tokens.update(source_id_tokens(value))
        if tokens:
            groups.append(tokens)

    sources_path = ws / "research" / "sources.json"
    try:
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        sources = []
    if isinstance(sources, list):
        for record in sources:
            if isinstance(record, dict):
                tokens = _source_record_tokens(record)
                if tokens:
                    groups.append(tokens)
    return groups


def available_source_tokens(
    workspace: str | Path, markdown: str | None = None
) -> set[str]:
    """Collect reference-list and evidence-pack identities in one vocabulary."""
    return set().union(*source_identity_groups(workspace, markdown))


def resolved_source_tokens(
    source_id: str, groups: list[set[str]]
) -> set[str]:
    """Return all aliases belonging to sources matched by source_id."""
    requested = source_id_tokens(source_id)
    return set().union(*(
        group for group in groups if requested & group
    ))


def source_resolves(source_id: str, available: set[str]) -> bool:
    return bool(source_id_tokens(source_id) & available)


def dangling_source_findings(
    ledger: dict[str, Any], available: set[str]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for claim in ledger["claims"]:
        for evidence in claim["evidence"]:
            source_id = evidence["source_id"]
            if not source_resolves(source_id, available):
                findings.append({
                    "code": "claim_source_missing",
                    "msg": (
                        "ledger evidence source_id has no matching reference "
                        "or evidence-pack entry"
                    ),
                    "at": source_id,
                    "claim_id": claim["id"],
                    "source_id": source_id,
                })
    return findings


def ledger_path(target: str | Path) -> Path:
    path = Path(target)
    return path if path.suffix.casefold() in {".yaml", ".yml"} else path / LEDGER_NAME


def load_claims(
    target: str | Path, *, validate_sources: bool = True
) -> dict[str, Any]:
    """Load a ledger, enforcing schema, unique ids, and optional source links."""
    path = ledger_path(target)
    workspace = path.parent
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ClaimsLedgerError([{
            "code": "claim_ledger_missing",
            "msg": f"{LEDGER_NAME} not found",
            "at": str(path),
        }]) from exc
    except (OSError, UnicodeError) as exc:
        raise ClaimsLedgerError([{
            "code": "claim_ledger_unreadable",
            "msg": f"claim ledger unreadable: {exc}",
            "at": str(path),
        }]) from exc
    try:
        payload = parse_ledger_text(text)
    except (ValueError, TypeError) as exc:
        raise ClaimsLedgerError([{
            "code": "claim_schema_invalid",
            "msg": f"claim ledger is not valid JSON/block YAML: {exc}",
            "at": str(path),
        }]) from exc

    findings = _schema_findings(payload)
    if not findings and isinstance(payload, dict):
        findings.extend(_duplicate_findings(payload))
    if not findings and validate_sources:
        findings.extend(
            dangling_source_findings(payload, available_source_tokens(workspace))
        )
    if findings:
        raise ClaimsLedgerError(findings)
    return payload


def body_without_references(markdown: str) -> str:
    """Blank only the parsed reference block while preserving line numbers."""
    lines = markdown.splitlines(keepends=True)
    output: list[str] = []
    in_references = False
    for line in lines:
        if not in_references and check_sources.REFERENCE_SECTION_RE.match(line):
            in_references = True
            output.append("\n" if line.endswith("\n") else "")
            continue
        if in_references and check_sources.MARKDOWN_HEADING_RE.match(line):
            in_references = False
        if in_references:
            output.append("\n" if line.endswith("\n") else "")
        else:
            output.append(line)
    return "".join(output)


_SLUG_STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "is", "of",
    "on", "or", "the", "to", "was", "were", "with",
})


def _stable_claim_id(text: str, raw: str, ordinal: int) -> str:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    words = [
        token for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in _SLUG_STOPWORDS
    ]
    readable = "-".join(words[:5]) or "claim"
    readable = readable[:70].strip("-") or "claim"
    digest = hashlib.sha256(
        f"{normalized}\0{raw}\0{ordinal}".encode("utf-8")
    ).hexdigest()[:10]
    return f"numeric-{readable}-{digest}"[:96].rstrip("-")


def claim_extract(
    workspace: str | Path,
    *,
    out: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Write a deterministic numeric-claim skeleton with empty evidence."""
    ws = Path(workspace)
    content_path = ws / "bundle" / "content.md"
    try:
        markdown = content_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ClaimsLedgerError([{
            "code": "claim_content_missing",
            "msg": "bundle/content.md not found",
            "at": str(content_path),
        }]) from exc
    except (OSError, UnicodeError) as exc:
        raise ClaimsLedgerError([{
            "code": "claim_content_unreadable",
            "msg": f"bundle/content.md unreadable: {exc}",
            "at": str(content_path),
        }]) from exc

    if out is None:
        destination = ws / LEDGER_NAME
    else:
        destination = Path(out)
        if not destination.is_absolute():
            destination = ws / destination
    if destination.exists() and not force:
        raise ClaimsLedgerError([{
            "code": "claim_ledger_exists",
            "msg": "refusing to overwrite an existing claim ledger without --force",
            "at": str(destination),
        }])

    body = body_without_references(markdown)
    extracted, _ = extract_numeric_claims(body, policy="saeteuk")
    lines = body.splitlines()
    occurrences: dict[tuple[int, str], int] = {}
    claims: list[dict[str, Any]] = []
    for item in extracted:
        line_number = item["line"]
        text = (
            lines[line_number - 1].strip()
            if 1 <= line_number <= len(lines)
            else item["snippet"]
        )
        signature = (line_number, item["raw"])
        ordinal = occurrences.get(signature, 0) + 1
        occurrences[signature] = ordinal
        claims.append({
            "id": _stable_claim_id(text, item["raw"], ordinal),
            "text": text,
            "kind": "numeric",
            "evidence": [],
        })
    ledger = {"schema": LEDGER_SCHEMA, "claims": claims}
    rendered = dump_json(ledger) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(destination)
    return ledger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="validate or mechanically seed a workspace claim ledger"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser(
        "claim_extract",
        help="extract numeric claims into an intentionally unevidenced skeleton",
    )
    extract.add_argument("workspace", help="report workspace directory")
    extract.add_argument("--out", default=None, help="output path (default: claims.yaml)")
    extract.add_argument(
        "--force", action="store_true", help="replace an existing skeleton"
    )
    validate = subparsers.add_parser("validate", help="validate claims.yaml")
    validate.add_argument("workspace", help="report workspace directory")
    validate.add_argument(
        "--skip-sources", action="store_true",
        help="validate structure and duplicate ids without source resolution",
    )
    return parser


def main(argv=None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "claim_extract":
            ledger = claim_extract(
                args.workspace, out=args.out, force=args.force
            )
            payload = {
                "ok": True,
                "command": "claim_extract",
                "workspace": str(Path(args.workspace)),
                "claims": len(ledger["claims"]),
                "ledger": str(
                    Path(args.out)
                    if args.out is not None
                    else Path(args.workspace) / LEDGER_NAME
                ),
                "note": (
                    "skeleton evidence is empty by design; fill it before "
                    "check_claims"
                ),
            }
        else:
            ledger = load_claims(
                args.workspace, validate_sources=not args.skip_sources
            )
            payload = {
                "ok": True,
                "command": "validate",
                "workspace": str(Path(args.workspace)),
                "claims": len(ledger["claims"]),
            }
    except ClaimsLedgerError as exc:
        print(dump_json({
            "ok": False,
            "command": args.command,
            "findings": exc.findings,
            "error": str(exc),
        }))
        return 2
    print(dump_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
