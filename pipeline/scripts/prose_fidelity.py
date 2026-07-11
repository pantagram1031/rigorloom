#!/usr/bin/env python3
"""Deterministically compare protected report facts before and after style edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


PATTERNS = {
    "numbers": re.compile(r"(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s?(?:%|‰|℃|°[CF]?|[a-zA-ZμµΩ]+(?:/[a-zA-Z0-9²³μµ]+)?))?"),
    "dates": re.compile(r"(?<!\d)(?:\d{4}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?)(?!\d)"),
    "source_ids": re.compile(r"(?<![\w-])(?:SRC|SOURCE|REF|S|R)[-_]?\d+(?![\w-])", re.I),
    "citations": re.compile(r"(?:\[\d+(?:\s*[-,]\s*\d+)*\]|\([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,\s*\d{4}\))"),
    "tags": re.compile(r"\[\[(?:EQ|FIG|TABLE|URL)\b[^\]]*\]\]", re.I),
    "inline_math": re.compile(r"(?<!\\)\$(?:\\.|[^$])+\$"),
    "direct_quotes": re.compile(r"(?:\"[^\"\n]+\"|“[^”\n]+”|‘[^’\n]+’)"),
    "urls": re.compile(r"https?://[^\s)>\]]+"),
    "markdown_links": re.compile(r"\[[^\]]+\]\(https?://[^)]+\)"),
}

QUALIFIERS = (
    "약", "대략", "가능", "추정", "최소", "최대", "이상", "이하", "미만", "초과",
    "않", "아니", "없", "못", "may", "might", "approximately", "at least", "at most",
    "not", "never", "no ",
)

QUANTIFIERS = (
    "모든", "대부분", "일부", "각각", "오직", "항상", "반드시", "전혀",
    "all", "most", "some", "each", "only", "always", "must",
)

CAUSAL_MARKERS = (
    "때문", "따라서", "그러므로", "그 결과", "원인", "결과",
    "because", "therefore", "thus", "causes", "results in",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _headings(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if re.match(r"^#{1,6}\s+\S", line)]


def _qualifiers(text: str) -> Counter[str]:
    lowered = text.lower()
    return Counter({token: lowered.count(token.lower()) for token in QUALIFIERS if token.lower() in lowered})


def _token_counts(text: str, tokens: tuple[str, ...]) -> Counter[str]:
    lowered = text.lower()
    return Counter({token: lowered.count(token.lower()) for token in tokens if token.lower() in lowered})


def extract_protected(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, pattern in PATTERNS.items():
        values = pattern.findall(text)
        result[name] = values if name in {"tags", "markdown_links"} else dict(Counter(values))
    result["headings"] = _headings(text)
    result["qualifiers"] = dict(_qualifiers(text))
    result["quantifiers"] = dict(_token_counts(text, QUANTIFIERS))
    result["causal_markers"] = dict(_token_counts(text, CAUSAL_MARKERS))
    return result


def audit_text(before: str, after: str) -> dict[str, object]:
    expected = extract_protected(before)
    observed = extract_protected(after)
    changes = []
    for kind in expected:
        if expected[kind] != observed[kind]:
            changes.append({"kind": kind, "before": expected[kind], "after": observed[kind]})
    return {
        "schema": "report-pipeline/prose-fidelity-v1",
        "pass": not changes,
        "before_sha256": _sha256(before),
        "after_sha256": _sha256(after),
        "changes": changes,
        "protected": sorted(expected),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.before.is_file() or not args.after.is_file():
        print("error: both input files must exist", file=sys.stderr)
        return 2
    result = audit_text(args.before.read_text(encoding="utf-8"), args.after.read_text(encoding="utf-8"))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
