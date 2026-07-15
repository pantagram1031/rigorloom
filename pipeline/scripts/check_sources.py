#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministically verify bibliography identifiers against an offline cache.

Reference/endnote entries are parsed from bundle/content.md into author, year,
title, container, DOI, ISBN, and URL fields. A decorated heading starts the
block; the next Markdown heading or EOF ends it. Blank lines are allowed inside
the block. Identifier-only lines continue the preceding entry.

No network or model calls are made. Optional cache records use this schema::

    <PROFILE_ROOT>/cache/sources/doi/<slug>.json
      {"doi": "10.1234/example", "title": "Cached title", ...}
    <PROFILE_ROOT>/cache/sources/isbn/<isbn13>.json
      {"isbn": "9781234567897", "title": "Cached title", ...}

DOI slugs are lowercase with runs outside [a-z0-9.-] replaced by "_".
ISBN-10 is converted to ISBN-13 for lookup. Extra JSON fields are allowed.
The pinned default current year is 2026; override it with --now YYYY.

This gate can only HARD-block citations whose identifiers are provably broken
or whose cache record contradicts them. A fabricated-but-syntactically-valid
DOI with no cache record is WARN ``source_unverified`` BY DESIGN. A green
verdict therefore does not mean "citations verified real"; it means only that
the gate found no provable break or cached contradiction.

``<PROFILE_ROOT>/cache/sources/`` SHOULD be populated write-through by the
research-time fetch tooling, not hand-authored. A hand-authored cache adds no
adversarial resistance.

Exit 0 = pass (WARNs allowed), 3 = HARD contradiction, 2 = usage/input error.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import sys
import unicodedata


DEFAULT_NOW_YEAR = 2026
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
REFERENCE_SECTION_RE = re.compile(
    r"^\s*(?:(?:\u203b|#+|-|:)\s*)*"
    r"(?:references?(?:\s+and\s+notes)?|reference\s+list|bibliography|"
    r"works\s+cited|literature\s+cited|endnotes?|sources?|source\s+list|"
    r"\ucc38\uace0\s*\ubb38\ud5cc|\ucc38\uace0\s*\uc790\ub8cc|"
    r"\uc778\uc6a9\s*\ubb38\ud5cc|\ubbf8\uc8fc|\ucd9c\ucc98)"
    r"\s*(?:(?:#+|:|-)\s*)*$",
    re.I,
)
DOI_URL_RE = re.compile(r"https?://(?:dx\.)?doi\.org/(?P<doi>\S+)", re.I)
DOI_LABEL_RE = re.compile(r"\bdoi\s*[:=]?\s*(?P<doi>\S+)", re.I)
PLAIN_DOI_RE = re.compile(r"(?<![\w/])(?P<doi>10\.\d{4,9}/\S+)", re.I)
ISBN_LABEL_RE = re.compile(
    r"\bisbn(?:-1[03])?\s*[:=]?\s*(?P<isbn>[0-9Xx][0-9Xx\s-]{8,23})",
    re.I,
)
URL_RE = re.compile(r"https?://\S+", re.I)
YEAR_RE = re.compile(r"(?<!\d)(?P<year>\d{4})(?!\d)")
PUBLICATION_TOKEN_RE = re.compile(
    r"\(\s*(?P<year>\d{4})"
    r"(?:\s*[-\u2013]\s*\d{4})?"
    r"(?:\s*,\s*(?P<qualifier>in\s+press|forthcoming))?"
    r"\s*\)",
    re.I,
)
CITATION_LIKE_LINE_RE = re.compile(
    r"(?:\(\s*\d{4}\s*\)\s*\.|\b(?:doi|isbn(?:-1[03])?)\s*:)",
    re.I,
)
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}(?:\s+|$)")
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\[\d+\]\s*|\d+[.)]\s+)")
TITLE_STOPWORDS = frozenset({
    "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the",
    "to", "with",
})


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _resolve_profile_root(profile_root) -> Path | None:
    """Match content_audit: explicit root, else a valid environment root."""
    if profile_root is not None:
        return Path(profile_root)
    configured = os.environ.get("RIGORLOOM_PROFILE_ROOT")
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    return candidate if candidate.is_dir() else None


def _clean_terminal_token(value: str) -> str:
    return value.strip().strip("<>").rstrip(".,;:)]}")


def _doi_slug(doi: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "_", doi.casefold()).strip("_")


def _isbn_digits(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value).upper()


def _valid_isbn10(value: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", value):
        return False
    digits = [10 if char == "X" else int(char) for char in value]
    return sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0


def _valid_isbn13(value: str) -> bool:
    if not re.fullmatch(r"\d{13}", value):
        return False
    return sum(
        int(char) * (1 if index % 2 == 0 else 3)
        for index, char in enumerate(value)
    ) % 10 == 0


def _isbn13(value: str) -> str | None:
    normalized = _isbn_digits(value)
    if _valid_isbn13(normalized):
        return normalized
    if not _valid_isbn10(normalized):
        return None
    stem = "978" + normalized[:9]
    subtotal = sum(
        int(char) * (1 if index % 2 == 0 else 3)
        for index, char in enumerate(stem)
    )
    return stem + str((10 - subtotal % 10) % 10)


def _reference_section(markdown: str) -> tuple[bool, list[tuple[int, str]]]:
    """Return whether a recognized section exists and its nonblank lines."""
    located: list[tuple[int, str]] = []
    in_sources = False
    section_found = False
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if not in_sources:
            if REFERENCE_SECTION_RE.match(line):
                in_sources = True
                section_found = True
            continue

        stripped = line.strip()
        if MARKDOWN_HEADING_RE.match(line):
            break
        if not stripped:
            continue
        located.append((line_number, line))
    return section_found, located


def _reference_lines(markdown: str) -> list[tuple[int, str]]:
    return _reference_section(markdown)[1]


def _identifier_continuation(line: str) -> bool:
    stripped = LIST_PREFIX_RE.sub("", line).strip()
    without_ids = DOI_URL_RE.sub("", stripped)
    without_ids = DOI_LABEL_RE.sub("", without_ids)
    without_ids = ISBN_LABEL_RE.sub("", without_ids)
    without_ids = URL_RE.sub("", without_ids)
    return not without_ids.strip(" .;,()[]")


def _entry_texts(markdown: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for line_number, line in _reference_lines(markdown):
        stripped = line.strip()
        if entries and _identifier_continuation(stripped):
            first_line, previous = entries[-1]
            entries[-1] = (first_line, f"{previous} {stripped}")
        else:
            entries.append((line_number, stripped))
    return entries


def _extract_doi(text: str) -> tuple[str | None, bool]:
    match = DOI_URL_RE.search(text) or DOI_LABEL_RE.search(text)
    if match:
        candidate = _clean_terminal_token(match.group("doi"))
        return candidate or None, bool(candidate and DOI_RE.fullmatch(candidate))
    match = PLAIN_DOI_RE.search(text)
    if match:
        candidate = _clean_terminal_token(match.group("doi"))
        return candidate, bool(DOI_RE.fullmatch(candidate))
    return None, False


def _extract_isbn(text: str) -> str | None:
    match = ISBN_LABEL_RE.search(text)
    return _isbn_digits(match.group("isbn")) if match else None


def _without_identifiers(text: str) -> str:
    cleaned = DOI_URL_RE.sub("", text)
    cleaned = DOI_LABEL_RE.sub("", cleaned)
    cleaned = PLAIN_DOI_RE.sub("", cleaned)
    cleaned = ISBN_LABEL_RE.sub("", cleaned)
    return URL_RE.sub("", cleaned)


def _bibliographic_fields(
    text: str,
) -> tuple[str | None, int | None, str | None, str | None, bool]:
    plain = LIST_PREFIX_RE.sub("", text).strip()
    publication_match = PUBLICATION_TOKEN_RE.search(plain)
    year_match = publication_match or YEAR_RE.search(plain)
    if year_match is None:
        return None, None, None, None, False

    author = plain[:year_match.start()].strip(" ,.;:()[]") or None
    tail = _without_identifiers(plain[year_match.end():])
    tail = tail.lstrip(" ),.;:-")
    parts = [part.strip(" ,;:()[]") for part in re.split(r"\.\s+", tail)]
    parts = [part for part in parts if part]
    title = parts[0] if parts else None
    container = ". ".join(parts[1:]) if len(parts) > 1 else None
    advisory = bool(
        publication_match is not None
        and publication_match.group("qualifier")
    )
    return author, int(year_match.group("year")), title, container, advisory


def parse_reference_entries(markdown: str) -> list[dict]:
    """Return structured entries from the first reference/endnote section."""
    parsed: list[dict] = []
    for line_number, text in _entry_texts(markdown):
        doi, doi_valid = _extract_doi(text)
        isbn = _extract_isbn(text)
        url_match = URL_RE.search(text)
        author, year, title, container, publication_advisory = (
            _bibliographic_fields(text)
        )
        parsed.append({
            "author": author,
            "year": year,
            "title": title,
            "container": container,
            "doi": doi,
            "isbn": isbn,
            "url": _clean_terminal_token(url_match.group(0)) if url_match else None,
            "line": line_number,
            "text": text,
            "doi_valid": doi_valid,
            "publication_advisory": publication_advisory,
        })
    return parsed


def _normalized_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _meaningful_title_tokens(normalized: str) -> list[str]:
    return [
        token for token in normalized.split()
        if token not in TITLE_STOPWORDS
    ]


def _ordered_token_coverage(shorter: list[str], longer: list[str]) -> float:
    if not shorter:
        return 0.0
    cursor = 0
    matched = 0
    for token in shorter:
        try:
            cursor = longer.index(token, cursor) + 1
        except ValueError:
            continue
        matched += 1
    return matched / len(shorter)


def _titles_match(cited: str, cached: str) -> bool:
    left = _normalized_title(cited)
    right = _normalized_title(cached)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter_text, longer_text = sorted((left, right), key=len)
    shorter_meaningful = _meaningful_title_tokens(shorter_text)
    if len(shorter_meaningful) >= 3 and shorter_text in longer_text:
        return True
    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens = left.split()
    right_tokens = right.split()
    shorter_tokens, longer_tokens = sorted(
        (left_tokens, right_tokens), key=len
    )
    left_set, right_set = set(left_tokens), set(right_tokens)
    union = left_set | right_set
    jaccard = len(left_set & right_set) / len(union) if union else 0.0
    ordered = _ordered_token_coverage(shorter_tokens, longer_tokens)
    return ratio >= 0.92 or (
        len(_meaningful_title_tokens(" ".join(shorter_tokens))) >= 3
        and jaccard >= 0.80
        and ordered == 1.0
    )


def _titles_clearly_different(cited: str, cached: str) -> bool:
    left = _normalized_title(cited)
    right = _normalized_title(cached)
    if not left or not right or left in right or right in left:
        return False
    left_tokens = set(_meaningful_title_tokens(left))
    right_tokens = set(_meaningful_title_tokens(right))
    return bool(left_tokens and right_tokens) and not (left_tokens & right_tokens)


def _usage(ws, message: str) -> tuple[dict, int]:
    return {
        "ok": False,
        "workspace": str(ws),
        "checker": "check_sources",
        "error": message,
        "hard": [],
        "warn": [],
        "counts": {"hard": 0, "warn": 0, "unverified": 0},
        "verdict": "usage_error",
    }, 2


def _load_cache_record(
    path: Path, key: str, expected: str
) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"source cache record unreadable: {path}: {exc}"
    if not isinstance(payload, dict):
        return None, f"source cache record must contain an object: {path}"
    identifier = payload.get(key)
    title = payload.get("title")
    if not isinstance(identifier, str) or not isinstance(title, str) or not title.strip():
        return None, f"source cache record requires string {key} and title: {path}"
    actual = identifier.casefold() if key == "doi" else _isbn_digits(identifier)
    wanted = expected.casefold() if key == "doi" else expected
    if actual != wanted:
        return None, f"source cache record {key} does not match its lookup key: {path}"
    return payload, None


def check(
    workspace: str | Path,
    profile_root=None,
    now: int = DEFAULT_NOW_YEAR,
) -> tuple[dict, int]:
    ws = Path(workspace)
    if isinstance(now, bool) or not isinstance(now, int) or not 1 <= now <= 9999:
        return _usage(ws, "now must be an integer year from 1 through 9999")
    content_path = ws / "bundle" / "content.md"
    try:
        markdown = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _usage(ws, "bundle/content.md not found")
    except (OSError, UnicodeError) as exc:
        return _usage(ws, f"bundle/content.md unreadable: {exc}")

    root = _resolve_profile_root(profile_root)
    cache_root = root / "cache" / "sources" if root else None
    section_found, _ = _reference_section(markdown)
    entries = parse_reference_entries(markdown)
    hard: list[dict] = []
    warn: list[dict] = []

    if not section_found:
        for line_number, line in enumerate(markdown.splitlines(), start=1):
            if CITATION_LIKE_LINE_RE.search(line):
                warn.append({
                    "code": "references_unparsed",
                    "msg": (
                        "citation-like content exists without a recognized "
                        "reference section"
                    ),
                    "at": line.strip()[:120],
                    "line": line_number,
                })
                break

    for entry in entries:
        cited_at = entry["title"] or entry["author"] or entry["text"][:80]
        doi = entry["doi"]
        isbn = entry["isbn"]
        isbn13 = _isbn13(isbn) if isbn else None

        if doi is not None and not entry["doi_valid"]:
            hard.append({
                "code": "source_doi_malformed",
                "msg": r"cited DOI does not match ^10\.\d{4,9}/\S+$",
                "at": doi,
                "line": entry["line"],
            })
        if isbn is not None and isbn13 is None:
            hard.append({
                "code": "source_isbn_checksum",
                "msg": "cited ISBN-10/ISBN-13 checksum is invalid",
                "at": isbn,
                "line": entry["line"],
            })
        if entry["year"] is not None and entry["year"] > now:
            finding = {
                "code": (
                    "source_year_future_advisory"
                    if entry["publication_advisory"]
                    else "source_year_future"
                ),
                "msg": (
                    "future publication year is marked in press/forthcoming"
                    if entry["publication_advisory"]
                    else f"publication year exceeds configured current year {now}"
                ),
                "at": str(entry["year"]),
                "line": entry["line"],
            }
            (warn if entry["publication_advisory"] else hard).append(finding)

        identifiers = []
        if doi and entry["doi_valid"]:
            identifiers.append(("doi", doi.casefold(), _doi_slug(doi) + ".json"))
        if isbn13:
            identifiers.append(("isbn", isbn13, isbn13 + ".json"))

        cache_hit = False
        for key, identifier, filename in identifiers:
            if cache_root is None:
                continue
            path = cache_root / key / filename
            record, error = _load_cache_record(path, key, identifier)
            if error:
                warn.append({
                    "code": "source_cache_unreadable",
                    "msg": error,
                    "at": cited_at,
                    "line": entry["line"],
                    "identifier": identifier,
                    "cache_path": str(path),
                })
                continue
            if record is None:
                continue
            cache_hit = True
            cached_title = record["title"].strip()
            cited_title = entry["title"]
            if cited_title and not _titles_match(cited_title, cached_title):
                clearly_different = _titles_clearly_different(
                    cited_title, cached_title
                )
                finding = {
                    "code": (
                        "source_title_mismatch"
                        if clearly_different
                        else "source_title_suspect"
                    ),
                    "msg": (
                        f"cached {key.upper()} record maps to a different work"
                        if clearly_different
                        else (
                            f"cited and cached {key.upper()} titles only "
                            "partially overlap"
                        )
                    ),
                    "at": cited_at,
                    "line": entry["line"],
                    "identifier": identifier,
                    "cited_title": cited_title,
                    "cached_title": cached_title,
                }
                (hard if clearly_different else warn).append(finding)

        if not cache_hit:
            warn.append({
                "code": "source_unverified",
                "msg": "source has no matching offline DOI/ISBN cache record",
                "at": cited_at,
                "line": entry["line"],
            })
        if doi is None and isbn is None and entry["url"] is None:
            warn.append({
                "code": "source_unidentifiable",
                "msg": "source entry has no DOI, ISBN, or URL",
                "at": cited_at,
                "line": entry["line"],
            })

    public_entries = [
        {
            key: value
            for key, value in entry.items()
            if key not in {"text", "doi_valid", "publication_advisory"}
        }
        for entry in entries
    ]
    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "checker": "check_sources",
        "section_found": section_found,
        "entries": public_entries,
        "hard": hard,
        "warn": warn,
        "counts": {
            "hard": len(hard),
            "warn": len(warn),
            "unverified": sum(
                item["code"] == "source_unverified" for item in warn
            ),
            "entries": len(entries),
        },
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="verify bibliography identifiers against an offline cache"
    )
    parser.add_argument("workspace", help="report workspace directory")
    parser.add_argument(
        "--profile-root",
        default=None,
        help=(
            "profile root containing cache/sources "
            "(default: valid RIGORLOOM_PROFILE_ROOT)"
        ),
    )
    parser.add_argument(
        "--now",
        type=int,
        default=DEFAULT_NOW_YEAR,
        metavar="YYYY",
        help=f"current year for future-year checks (default: {DEFAULT_NOW_YEAR})",
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    args = parser.parse_args(argv)
    verdict, code = check(
        args.workspace,
        profile_root=args.profile_root,
        now=args.now,
    )
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
