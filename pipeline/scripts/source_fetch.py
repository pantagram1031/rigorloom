#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record research-time DOI/ISBN evidence in check_sources' offline cache.

Retrieval authority is explicit: provide both --retrieved-from and
--content-sha256 to store a verification object. With neither option the
record is still useful for contradictions, but its verification field is null.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import check_sources  # noqa: E402
from checker_base import _utf8_stdio, dump_json  # noqa: E402


class SourceFetchError(ValueError):
    """A source record would be invalid or poison an existing cache entry."""


def _retrieved_at(now: str | None) -> str:
    if now is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not isinstance(now, str) or not now.strip():
        raise SourceFetchError("--now must be a non-empty ISO-8601 timestamp")
    candidate = now.strip()
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceFetchError("--now must be an ISO-8601 timestamp") from exc
    return candidate


def _identifier(doi: str | None, isbn: str | None) -> tuple[str, str, str]:
    if bool(doi) == bool(isbn):
        raise SourceFetchError("provide exactly one of --doi or --isbn")
    if doi is not None:
        normalized = check_sources._clean_terminal_token(doi).casefold()
        if not check_sources.DOI_RE.fullmatch(normalized):
            raise SourceFetchError("DOI does not match ^10\\.\\d{4,9}/\\S+$")
        return "doi", normalized, check_sources._doi_slug(normalized) + ".json"
    isbn13 = check_sources._isbn13(isbn or "")
    if isbn13 is None:
        raise SourceFetchError("ISBN-10/ISBN-13 checksum is invalid")
    return "isbn", isbn13, isbn13 + ".json"


def _verification(
    retrieved_from: str | None,
    content_sha256: str | None,
    retrieved_at: str,
) -> dict[str, str] | None:
    if (retrieved_from is None) != (content_sha256 is None):
        raise SourceFetchError(
            "--retrieved-from and --content-sha256 must be provided together"
        )
    if retrieved_from is None:
        return None
    url = retrieved_from.strip()
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise SourceFetchError("--retrieved-from must be an HTTP(S) URL") from exc
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        raise SourceFetchError("--retrieved-from must be an HTTP(S) URL")
    digest = (content_sha256 or "").strip().casefold()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise SourceFetchError("--content-sha256 must be exactly 64 hex characters")
    return {
        "retrieved_from": url,
        "content_sha256": digest,
        "retrieved_at": retrieved_at,
    }


def _existing_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFetchError(f"existing cache record is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceFetchError("existing cache record must be a JSON object")
    return payload


def record_source(
    *,
    profile_root: str | Path | None = None,
    doi: str | None = None,
    isbn: str | None = None,
    title: str,
    container: str | None = None,
    year: int | None = None,
    retrieved_from: str | None = None,
    content_sha256: str | None = None,
    now: str | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Atomically write one cache record using check_sources' identity rules."""
    root = check_sources._resolve_profile_root(profile_root)
    if root is None:
        raise SourceFetchError(
            "profile root required (--profile-root or valid RIGORLOOM_PROFILE_ROOT)"
        )
    if not isinstance(title, str) or not title.strip():
        raise SourceFetchError("title must be a non-empty string")
    if year is not None and (
        isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999
    ):
        raise SourceFetchError("year must be an integer from 1 through 9999")
    key, identifier, filename = _identifier(doi, isbn)
    timestamp = _retrieved_at(now)
    verification = _verification(retrieved_from, content_sha256, timestamp)
    target = Path(root) / "cache" / "sources" / key / filename

    existing_error: str | None = None
    try:
        existing = _existing_payload(target)
    except SourceFetchError as exc:
        if not force:
            raise
        existing = None
        existing_error = str(exc)
    if existing is not None:
        (
            _validated_existing,
            validation_error,
            _existing_authoritative,
        ) = check_sources._load_cache_record(target, key, identifier)
        if validation_error:
            if not force:
                raise SourceFetchError(validation_error)
            existing_error = validation_error
    history: list[dict[str, Any]] = []
    if existing is not None and isinstance(existing.get("history"), list):
        history = list(existing["history"])
    previous_title = existing.get("title") if existing else None
    title_changed = (
        isinstance(previous_title, str)
        and not check_sources._titles_match(previous_title, title.strip())
    )
    if title_changed and not force:
        raise SourceFetchError(
            "refusing to overwrite an existing cache record with a different title; "
            "pass --force to record the replacement"
        )
    if force and title_changed:
        history.append({
            "at": timestamp,
            "writer": "source_fetch",
            "warning": "forced_title_overwrite",
            "previous_title": previous_title,
            "replacement_title": title.strip(),
        })
    if force and existing_error:
        history.append({
            "at": timestamp,
            "writer": "source_fetch",
            "warning": "forced_invalid_record_overwrite",
            "detail": existing_error,
        })

    record: dict[str, Any] = {
        key: identifier,
        "title": title.strip(),
        "writer": "source_fetch",
        "verification": verification,
    }
    if container is not None:
        record["container"] = container
    if year is not None:
        record["year"] = year
    if history:
        record["history"] = history

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(dump_json(record) + "\n", encoding="utf-8", newline="\n")
    validated, error, _authoritative = check_sources._load_cache_record(
        temporary, key, identifier
    )
    if error or validated is None:
        temporary.unlink(missing_ok=True)
        raise SourceFetchError(error or "cache record failed check_sources validation")
    temporary.replace(target)
    return record, target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="write verified research sources through to the offline cache"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record", help="record one DOI or ISBN source")
    identifiers = record.add_mutually_exclusive_group(required=True)
    identifiers.add_argument("--doi")
    identifiers.add_argument("--isbn")
    record.add_argument("--title", required=True)
    record.add_argument("--container")
    record.add_argument("--year", type=int)
    record.add_argument("--retrieved-from", dest="retrieved_from")
    record.add_argument(
        "--content-sha256",
        dest="content_sha256",
        help="SHA-256 of the fetched landing page or PDF",
    )
    record.add_argument(
        "--profile-root",
        default=None,
        help="profile root (default: valid RIGORLOOM_PROFILE_ROOT)",
    )
    record.add_argument(
        "--now", default=None,
        help="ISO-8601 retrieval timestamp override for deterministic tests",
    )
    record.add_argument(
        "--force", action="store_true",
        help="allow a different title and append a warning to history",
    )
    return parser


def main(argv=None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        record, path = record_source(
            profile_root=args.profile_root,
            doi=args.doi,
            isbn=args.isbn,
            title=args.title,
            container=args.container,
            year=args.year,
            retrieved_from=args.retrieved_from,
            content_sha256=args.content_sha256,
            now=args.now,
            force=args.force,
        )
    except SourceFetchError as exc:
        print(dump_json({
            "ok": False,
            "command": "record",
            "error": str(exc),
        }))
        return 2
    print(dump_json({
        "ok": True,
        "command": "record",
        "path": str(path),
        "record": record,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
