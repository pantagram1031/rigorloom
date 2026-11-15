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
    "cannot", "n't", "nothing", "none", "neither", "nor", "without",
)

QUANTIFIERS = (
    "모든", "대부분", "일부", "각각", "오직", "항상", "반드시", "전혀",
    "all", "most", "some", "each", "only", "always", "must",
)

CAUSAL_MARKERS = (
    "때문", "따라서", "그러므로", "그 결과", "원인", "결과",
    "because", "therefore", "thus", "causes", "results in",
)

# Words that carry the direction of a change. "약 18.6% 감소" -> "약 18.6% 증가"
# keeps every number and hedge, so without these the verdict was "same".
# Sino-Korean nouns match anywhere; native stems only at a word start so that
# 목적은 or 오늘 do not count as 적은 or 늘.
DIRECTION_NOUNS = (
    "증가", "감소", "상승", "하락", "증대", "감축", "향상", "저하", "개선", "악화",
)
DIRECTION_STEMS = (
    "늘어", "늘었", "늘리", "늘린", "줄어", "줄었", "줄이", "줄인",
    "높아", "높은", "높다", "높았", "높게", "낮아", "낮은", "낮다", "낮았", "낮게",
    "많아", "많은", "많다", "많았", "많이", "적어", "적은", "적다", "적었", "적게",
    "빨라", "빠른", "느려", "느린",
)
DIRECTION_EN = (
    "increase", "increased", "increases", "decrease", "decreased", "decreases",
    "rise", "rose", "risen", "fall", "fell", "fallen", "higher", "lower",
    "more", "less", "fewer", "greater", "improve", "improved", "worsen", "worsened",
    "faster", "slower",
)
_STEM_RE = re.compile("(?<![가-힣])(" + "|".join(DIRECTION_STEMS) + ")")
_EN_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(DIRECTION_EN) + r")(?![A-Za-z])", re.I)

# A short line such as "3. 실험 방법" or "II. 결과" is a numbered heading. Lines
# ending in sentence punctuation are list items, not headings.
_NUMBERED_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[가-하]\.)\s+\S")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_heading(line: str) -> bool:
    if re.match(r"^#{1,6}\s+\S", line):
        return True
    stripped = line.strip()
    return (
        len(stripped) <= 40
        and bool(_NUMBERED_HEADING.match(stripped))
        and not re.search(r"[.?!。]$", stripped)
    )


def _headings(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if _is_heading(line)]


def _direction_words(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in DIRECTION_NOUNS:
        if token in text:
            counts[token] = text.count(token)
    counts.update(_STEM_RE.findall(text))
    counts.update(match.lower() for match in _EN_RE.findall(text))
    return counts


# How a token is counted. Plain substring counting made "Really" contain "all",
# "계약서" contain 약 and "이상하다" contain 이상, so style edits that kept every
# fact were reverted. English tokens now need letter boundaries; 약 counts only
# before a number; 이상/이하/미만/초과 count only after a number (and unit).
_BOUND_AFTER_NUMBER = ("이상", "이하", "미만", "초과")


def _token_pattern(token: str) -> re.Pattern[str]:
    if token == "약":
        return re.compile(r"(?<![가-힣])약(?=\s*[\d.])")
    if token == "n't":
        return re.compile(r"n['’]t(?![a-z])")
    if token in _BOUND_AFTER_NUMBER:
        return re.compile(r"\d[가-힣%‰℃°a-zA-Z]{0,2}\s?" + token)
    if token.isascii():
        return re.compile(r"(?<![a-z])" + re.escape(token.strip().lower()) + r"(?![a-z])")
    return re.compile(re.escape(token.lower()))


def _token_counts(text: str, tokens: tuple[str, ...]) -> Counter[str]:
    lowered = text.lower()
    counts: Counter[str] = Counter()
    for token in tokens:
        n = len(_token_pattern(token).findall(lowered))
        if n:
            counts[token] = n
    return counts


def _qualifiers(text: str) -> Counter[str]:
    return _token_counts(text, QUALIFIERS)


def extract_protected(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, pattern in PATTERNS.items():
        values = pattern.findall(text)
        result[name] = values if name in {"tags", "markdown_links"} else dict(Counter(values))
    result["headings"] = _headings(text)
    result["qualifiers"] = dict(_qualifiers(text))
    result["quantifiers"] = dict(_token_counts(text, QUANTIFIERS))
    result["causal_markers"] = dict(_token_counts(text, CAUSAL_MARKERS))
    result["direction_words"] = dict(_direction_words(text))
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



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
