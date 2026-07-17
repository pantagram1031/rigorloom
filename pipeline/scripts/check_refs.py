# -*- coding: utf-8 -*-
"""Advisory figure/table numbering and cross-reference lint for content.md.

Definitions come from caption attributes on canonical FIG and TABLE build
tags. In-text references are scanned only after build tags are stripped.
Numbering and xref suspects are WARN-only; only a usage/input error returns
nonzero.

Exit 0 = completed (including WARN findings), 2 = usage/input error.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    usage_error,
    verdict_skeleton,
)


TAG_RE = re.compile(r"\[\[.*?\]\]", re.S)
BUILD_TAG_RE = re.compile(
    r"\[\[(?P<kind>FIG|TABLE)\b(?P<attrs>.*?)\]\]", re.S
)
CAPTION_ATTR_RE = re.compile(
    r'\bcaption\s*=\s*"(?P<caption>(?:\\.|[^"\\])*)"', re.S
)
CAPTION_NUMBER_RE = re.compile(
    r"^\s*(?:"
    r"\[\s*(?P<bracket_label>그림|표)[ \t]+"
    r"(?P<bracket_number>[0-9]+)\s*\]"
    r"|(?P<plain_label>그림|표)[ \t]+"
    r"(?P<plain_number>[0-9]+)\s*[.:]"
    r")"
)
XREF_RE = re.compile(
    r"(?:"
    r"\[\s*(?P<square_label>그림|표)[ \t]*"
    r"(?P<square_number>[0-9]+)\s*\]"
    r"|\(\s*(?P<round_label>그림|표)[ \t]*"
    r"(?P<round_number>[0-9]+)\s*\)"
    r"|(?<!\w)(?P<plain_label>그림|표)[ \t]*"
    r"(?P<plain_number>[0-9]+)"
    r"(?![0-9개장줄]|\.[0-9])"
    r"(?=(?:에서|에|과|와|의)|[,)]|[ \t]|$)"
    r")"
)
FIGURE_SOURCES_RE = re.compile(
    r"^\s*(?:(?:※|#+|-|:)\s*)*그림\s*출처"
    r"\s*(?:(?:※|#+|-|:)\s*)*$"
)


def _without_tags(text: str) -> str:
    """Remove tag content while retaining newlines for useful line numbers."""
    return TAG_RE.sub(
        lambda match: re.sub(r"[^\r\n]", " ", match.group(0)),
        text,
    )


def _caption_definitions(markdown: str) -> tuple[list[int], list[int], Counter]:
    figures: list[int] = []
    tables: list[int] = []
    tag_counts: Counter = Counter()
    expected_label = {"FIG": "그림", "TABLE": "표"}
    destinations = {"FIG": figures, "TABLE": tables}

    for tag in BUILD_TAG_RE.finditer(markdown):
        kind = tag.group("kind")
        tag_counts[kind] += 1
        caption_attr = CAPTION_ATTR_RE.search(tag.group("attrs"))
        if caption_attr is None or not caption_attr.group("caption").strip():
            continue
        number_match = CAPTION_NUMBER_RE.match(caption_attr.group("caption"))
        if number_match is None:
            continue
        label = (
            number_match.group("bracket_label")
            or number_match.group("plain_label")
        )
        number_text = (
            number_match.group("bracket_number")
            or number_match.group("plain_number")
        )
        if label == expected_label[kind]:
            destinations[kind].append(int(number_text))

    return figures, tables, tag_counts


def _xref_parts(match: re.Match) -> tuple[str, int]:
    label = (
        match.group("square_label")
        or match.group("round_label")
        or match.group("plain_label")
    )
    number = (
        match.group("square_number")
        or match.group("round_number")
        or match.group("plain_number")
    )
    return label, int(number)


def _numbering_findings(kind: str, label: str, numbers: list[int]) -> list[dict]:
    findings = []
    counts = Counter(numbers)
    for number, count in counts.items():
        if count > 1:
            findings.append({
                "code": f"{kind}_numbering_duplicate",
                "msg": f"{label} caption number {number} is defined {count} times",
                "at": f"{label} {number}",
            })

    unique_in_order = list(dict.fromkeys(numbers))
    expected = list(range(1, len(unique_in_order) + 1))
    if unique_in_order != expected:
        found_text = ", ".join(map(str, unique_in_order)) or "(none)"
        expected_text = ", ".join(map(str, expected)) or "(none)"
        findings.append({
            "code": f"{kind}_numbering_gap",
            "msg": (
                f"{label} captions must be numbered 1, 2, 3, ... "
                "in document order"
            ),
            "at": f"found {found_text}; expected {expected_text}",
        })
    return findings


def check(ws):
    content_path = Path(ws) / "bundle" / "content.md"
    try:
        markdown = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return usage_error(
            str(ws), None, "bundle/content.md not found", minimal=True
        )
    except (OSError, UnicodeError) as exc:
        return usage_error(
            str(ws), None,
            f"bundle/content.md unreadable: {exc}",
            minimal=True,
        )

    figures, tables, tag_counts = _caption_definitions(markdown)
    body = _without_tags(markdown)
    lines = body.splitlines()

    hard = []
    warn = []
    warn.extend(_numbering_findings("figure", "그림", figures))
    warn.extend(_numbering_findings("table", "표", tables))

    defined = {"그림": set(figures), "표": set(tables)}
    referenced = {"그림": set(), "표": set()}
    cross_reference_count = 0
    in_figure_sources = False
    source_lines_seen = False
    for line_number, line in enumerate(lines, start=1):
        if FIGURE_SOURCES_RE.match(line):
            in_figure_sources = True
            source_lines_seen = False
            continue
        if in_figure_sources:
            stripped = line.strip()
            # The source section ends at the NEXT markdown heading (robust
            # boundary — closes even an empty section, so it never blankets to
            # EOF), OR at a blank line that follows at least one source-list line
            # (the natural end of the citation block). A blank line before any
            # content does not end it (the list may start after a blank).
            if stripped.startswith("#"):
                in_figure_sources = False  # heading closes it; fall through to scan
            elif not stripped:
                if source_lines_seen:
                    in_figure_sources = False
                continue  # blank line has no refs to scan
            else:
                source_lines_seen = True
                continue  # a source-list line — skip (its 그림 N is a citation)
        for match in XREF_RE.finditer(line):
            label, number = _xref_parts(match)
            cross_reference_count += 1
            referenced[label].add(number)
            if number not in defined[label]:
                warn.append({
                    "code": "dangling_xref",
                    "msg": f"{label} {number} has no matching caption definition",
                    "at": f"{label} {number}",
                    "line": line_number,
                })

    for number in dict.fromkeys(figures):
        if number not in referenced["그림"]:
            warn.append({
                "code": "unreferenced_figure",
                "msg": f"defined figure is never referenced in body text: 그림 {number}",
                "at": f"그림 {number}",
            })

    verdict = verdict_skeleton(
        str(ws),
        "check_refs",
        hard=hard,
        warn=warn,
        extra={
            "defined": {"figures": figures, "tables": tables},
            "build_tags": {
                "figures": tag_counts["FIG"],
                "tables": tag_counts["TABLE"],
            },
        },
        counts={
            "hard": len(hard),
            "warn": len(warn),
            "figure_captions": len(figures),
            "table_captions": len(tables),
            "figure_tags": tag_counts["FIG"],
            "table_tags": tag_counts["TABLE"],
            "cross_references": cross_reference_count,
        },
    )
    return verdict, 0


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="lint figure/table numbering and cross-references"
    )
    parser.add_argument(
        "workspace", help="report workspace dir (.../workspaces/report-<slug>)"
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    return cli_main(parser, lambda args: check(args.workspace), argv)


if __name__ == "__main__":
    raise SystemExit(main())
