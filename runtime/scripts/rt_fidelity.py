#!/usr/bin/env python3
"""Deterministically compare protected report facts before and after style edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from decimal import Decimal
from pathlib import Path


_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
# Korean magnitudes: 500만, 2천만, 1억 2천만. 조 is one only when an amount goes
# on (1조원, 1조 2천억); in 제1조 it is an article.
_MAG = r"(?:[십백천만억]|조(?=\s?원|\s?\d[\d,.]*[십백천만억]))+"
# Units a Korean amount or count is written with. 달 is the same unit as 개월.
_UNIT_KO = r"(?:개월|원|명|개|건|회|일|년|달)"
_UNIT_OTHER = r"(?:%|‰|℃|°[CF]?|[\u3380-\u33df]|[a-zA-ZμµΩ]+[²³]?(?:/[a-zA-Z0-9²³μµ]+)?)"

PATTERNS = {
    # Not after a digit (any script), a Latin letter, underscore or dot (so
    # "v2", "x86" and "1.5" stay whole), but after Hangul: "제17조" holds the
    # number 17. Python's \w includes Hangul, so (?<![\w.]) missed every number
    # written right after a Korean syllable and a "제17조 → 제18조" edit passed.
    # The token takes its Korean magnitude and its unit, so 500만원 and 500원
    # are different numbers and 500만원 and 5,000,000원 the same one.
    "numbers": re.compile(r"(?<![\dA-Za-zＡ-Ｚａ-ｚ_.])[+-]?" + _NUM
                          + r"(?:" + _MAG + r"(?:\s?" + _NUM + _MAG + r")*)?"
                          + r"(?:\s?(?:" + _UNIT_KO + r"|" + _UNIT_OTHER + r"))?"),
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


_SMALL = {"십": 1, "백": 2, "천": 3}
_LARGE = {"만": 4, "억": 8, "조": 12}
_GROUP = re.compile(r"([+-]?\d+(?:\.\d+)?)([십백천만억조]+)")


def _number_key(token: str) -> str:
    """One spelling per number: ASCII digits, no thousands commas, no space
    before the unit, Korean magnitudes multiplied out. "１７" and "17",
    "1,000" and "1000", "20 ℃" and "20℃", "500만원" and "5,000,000원",
    "10㎡" and "10 m²" are the same fact; flagging them would bury the real
    changes."""
    text = re.sub(r"(?<=\d),(?=\d{3})|\s+", "", unicodedata.normalize("NFKC", token))
    total, block, end = Decimal(0), Decimal(0), 0
    for group in _GROUP.finditer(text):
        if group.start() != end:
            break
        mags = group.group(2)
        block += Decimal(group.group(1)).scaleb(sum(_SMALL.get(c, 0) for c in mags))
        large = sum(_LARGE.get(c, 0) for c in mags)
        if large:                       # 2천3백만: (2천 + 3백) × 만
            total += block.scaleb(large)
            block = Decimal(0)
        end = group.end()
    if end:
        number = format((total + block).normalize(), "f")
    else:
        number = re.match(r"[+-]?[\d.]*", text).group(0)
        end = len(number)
    unit = text[end:]
    return number + ("개월" + unit[1:] if unit.startswith("달") else unit)


def _number_tokens(text: str) -> list[re.Match[str]]:
    return list(PATTERNS["numbers"].finditer(text))


# Which number goes with which word. The label of a number is the last word
# before it, after the previous number: 기본급은 300만원, 수당 50만원 pairs
# 300만원 with 기본급 and 50만원 with 수당. A word glued to the previous number
# (조 in 제17조) belongs to that number; particles are dropped so 수당은 and
# 수당 are one label; words that carry no subject are skipped.
_WORD = re.compile(r"[가-힣]+|[A-Za-z]+")
_PARTICLES = sorted((
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "에게", "께서", "로", "으로",
    "와", "과", "도", "만", "까지", "부터", "보다", "에는", "에서는", "으로는", "로는",
    "과는", "와는", "이나", "나", "이란", "란", "이며", "며", "이고", "고",
), key=len, reverse=True)
_NOT_A_LABEL = {
    "금", "약", "총", "각", "및", "제", "또는", "그리고", "등", "중", "단", "대략", "최소", "최대",
    "a", "an", "the", "is", "was", "were", "are", "be", "been", "of", "to", "in", "on",
    "at", "by", "for", "and", "or", "with", "about", "around", "approximately", "than", "as",
}


def _label(segment: str, glued: bool) -> str:
    words = _WORD.findall(segment)
    if glued and words and "가" <= segment[:1] <= "힣":
        words = words[1:]
    for word in reversed(words):
        word = word.lower()
        for particle in _PARTICLES:
            if word.endswith(particle) and len(word) > len(particle):
                word = word[: -len(particle)]
                break
        if word not in _NOT_A_LABEL:
            return word
    return ""


def _number_change(before: str, after: str) -> dict[str, object] | None:
    """The numbers change between two texts, compared on keys and shown in
    the document's own spelling, or None.

    Two kinds: a number appears a different number of times (500만원 became
    50만원), or every number is still there but two labelled numbers traded
    words (기본급은 300만원, 수당은 50만원 → 기본급은 50만원, 수당은 300만원).
    The second is reported only when the same words label the same numbers on
    both sides, so a sentence that is merely reordered stays quiet."""
    sides = []
    for text in (before, after):
        found, end = [], 0
        for m in _number_tokens(text):
            found.append((m.group(0), _number_key(m.group(0)), _label(text[end:m.start()], end > 0)))
            end = m.end()
        sides.append(found)
    b, a = sides
    shown: dict[str, str] = {}
    for token, key, _ in b + a:
        shown.setdefault(key, token)
    keys_b, keys_a = Counter(k for _, k, _ in b), Counter(k for _, k, _ in a)
    if keys_b != keys_a:
        return {"kind": "numbers",
                "before": dict(Counter(shown[k] for _, k, _ in b)),
                "after": dict(Counter(shown[k] for _, k, _ in a))}
    labelled_b = [(lab, k) for _, k, lab in b if lab]
    labelled_a = [(lab, k) for _, k, lab in a if lab]
    pairs_b, pairs_a = Counter(labelled_b), Counter(labelled_a)
    if (pairs_b == pairs_a
            or Counter(lab for lab, _ in labelled_b) != Counter(lab for lab, _ in labelled_a)
            or Counter(k for _, k in labelled_b) != Counter(k for _, k in labelled_a)):
        return None
    def only(pairs: list[tuple[str, str]], extra: Counter) -> list[str]:
        out = []
        for lab, k in pairs:            # in the order the text has them
            if extra[(lab, k)] > 0:
                extra[(lab, k)] -= 1
                out.append(f"{lab} {shown[k]}")
        return out
    return {"kind": "numbers", "order": True,
            "before": only(labelled_b, pairs_b - pairs_a),
            "after": only(labelled_a, pairs_a - pairs_b)}


def extract_protected(text: str) -> dict[str, object]:
    """The protected expressions of ``text`` as written. Numbers are compared
    on their key (``_number_key``) by ``audit_text``; this keeps the
    document's spelling so a caller can find them in the text."""
    result: dict[str, object] = {}
    for name, pattern in PATTERNS.items():
        values = [m.group(0) for m in pattern.finditer(text)]
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
        if kind == "numbers":
            change = _number_change(before, after)
            if change:
                changes.append(change)
        elif expected[kind] != observed[kind]:
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
