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
from decimal import Decimal, localcontext
from pathlib import Path


_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
# Korean magnitudes: 500만, 2천만, 1억 2천만. 조 is one only when an amount goes
# on (1조원, 1조 2천억); in 제1조 it is an article.
_MAG = r"(?:[십백천만억]|조(?=\s?원|\s?\d[\d,.]*[십백천만억]))+"
# Spaces between the groups of one amount: 1억 2천만원, -3억   6,200만 410원.
_GAP = r"[ \t\u00a0]*"
# A minus sign covers the whole amount; − (U+2212) and 마이너스 are minus too.
_SIGN = r"(?:[+\-\u2212]|마이너스[ \t\u00a0]?)?"
# Units a Korean amount or count is written with. 달 is the same unit as 개월,
# 인 as 명, 제곱미터 as m². A unit is not the start of another word: 24인치,
# 제12차량, 38 평가, 18 인원 and 68 분기점 hold no 인, 차, 평 or 분기. After a
# space the unit must end the word, but for a particle or a counting suffix
# (5 명이, 3 개월간, 8 차분), so 8차분 and 8 차분 read the same.
_UNITS_KO = ("개월", "원", "명", "인치", "인", "개", "건", "회", "일", "년", "달", "평",
             "분기", "차", "제곱미터")
_UNIT_KO = r"(?:개월|원|명|인치|인(?!원)|개|건|회|일|년|달|평(?!가|균)|분기(?!점)|차(?!량)|제곱미터)"
_UNIT_KO_SPACED = (r"(?:" + "|".join(_UNITS_KO) + r")"
                   r"(?=(?:은|는|이[가-힣]*|을|를|의|에서|에게|에|으로|로|과|와|도|만|까지|부터"
                   r"|씩|간|째|당|분|차|가량|어치|짜리)?(?![가-힣]))")
_UNIT_OTHER = (r"(?:%(?:p(?![A-Za-z])|포인트)?|‰|℃|°[CF]?|[\u3380-\u33df]|[kcm]?m[23²³](?!\d)"
               r"|[a-zA-ZμµΩ]+[²³]?(?:/[a-zA-Z0-9²³μµ]+)?)")

PATTERNS = {
    # Not after a digit (any script), a Latin letter, underscore or dot (so
    # "v2", "x86" and "1.5" stay whole), but after Hangul: "제17조" holds the
    # number 17. Python's \w includes Hangul, so (?<![\w.]) missed every number
    # written right after a Korean syllable and a "제17조 → 제18조" edit passed.
    # The token takes its Korean magnitude and its unit, so 500만원 and 500원
    # are different numbers and 500만원 and 5,000,000원 the same one.
    "numbers": re.compile(r"(?<![\dA-Za-zＡ-Ｚａ-ｚ_.])" + _SIGN + _NUM
                          + r"(?:" + _MAG + r"(?:" + _GAP + _NUM + _MAG + r")*"
                          + r"(?:" + _GAP + _NUM + r"(?=\s?원))?)?"
                          + r"(?:" + _UNIT_KO + r"|\s" + _UNIT_KO_SPACED
                          + r"|\s?" + _UNIT_OTHER + r")?"),
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
_NUMBERED_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[가-하]\.)\s+"
                               r"(?!(?:" + "|".join(_UNITS_KO) + r")(?![가-힣]))\S")


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
_GROUP = re.compile(r"(\d+(?:\.\d+)?)([십백천만억조]+)")
_SAME_UNIT = (("달", "개월"), ("인", "명"), ("제곱미터", "m2"), ("%포인트", "%p"))


def _number_key(token: str) -> str:
    """One spelling per number: ASCII digits, no thousands commas, no space
    before the unit, Korean magnitudes multiplied out. "１７" and "17",
    "1,000" and "1000", "20 ℃" and "20℃", "500만원" and "5,000,000원",
    "10㎡" and "10 m²" are the same fact; flagging them would bury the real
    changes."""
    text = re.sub(r"(?<=\d),(?=\d{3})|\s+", "", unicodedata.normalize("NFKC", token))
    # The sign belongs to the whole amount: -1억 2천만 is -120,000,000.
    sign = "-" if text.startswith(("-", "\u2212", "마이너스")) else ""
    text = re.sub(r"^(?:[+\-\u2212]|마이너스)", "", text)
    total, block, end = Decimal(0), Decimal(0), 0
    with localcontext() as exact:
        # Every digit counts: 0.1234…781 and 0.1234…782 are different numbers.
        exact.prec = len(text) + 40
        # Each group starts where the last one ended. A search over the whole
        # text would try every digit of a long run as a start: 20,000 digits
        # took seconds.
        while group := _GROUP.match(text, end):
            mags = group.group(2)
            block += Decimal(group.group(1)).scaleb(sum(_SMALL.get(c, 0) for c in mags))
            large = sum(_LARGE.get(c, 0) for c in mags)
            if large:                       # 2천3백만: (2천 + 3백) × 만
                total += block.scaleb(large)
                block = Decimal(0)
            end = group.end()
        rest = re.match(r"\d+(?:\.\d+)?", text[end:])
        if rest and (not end or text[end + rest.end():].startswith("원")):
            block += Decimal(rest.group(0))  # 1억 2,000만 3,500원: the won after the last group
            end += rest.end()
        number = format((total + block).normalize(), "f") if end else ""
    unit = text[end:]
    unit = dict(_SAME_UNIT).get(unit, unit)   # 인치 stays 인치
    return (sign if number.strip("0.") else "") + number + unit


def _number_tokens(text: str) -> list[re.Match[str]]:
    return list(PATTERNS["numbers"].finditer(text))


# Which number goes with which word. A number is read two ways: with the
# words before it, after the previous number (기본급은 300만원, 수당은 50만원
# pairs 300만원 with 기본급 and 50만원 with 수당), and with the words after
# it, up to the next number (3건 승인, 5건 보류 pairs 3건 with 승인). A word
# glued to a number (조 in 제17조) belongs to that number; particles are
# dropped so 수당은 and 수당 are one label; words that carry no subject are
# skipped (a single Latin letter is a label: A반, B동). A label stays in its
# own clause: the words before a number start after the last comma or full
# stop (설계비는 38만원을 심사 후 확정했다. 감리비는 47만원 labels 47만원 감리비),
# up to six of them, so 동관에서 근무하는 … 직원 and 서관에서 근무하는 … 직원
# differ; the words after a number stop after the first word with a particle
# or a verb ending (68건 승인 확인을 기록했다 labels 68건 승인 확인, not the
# 기록했다 the whole list shares). 승인하고 and 승인했다 are both 승인, and a
# label that only gained words at its far end (지난 회의에서 총무팀은 for
# 총무팀은) is still the same label.
_WORD = re.compile(r"[가-힣]+|[A-Za-z]+")
_PARTICLES = sorted((
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "에게", "께서", "로", "으로",
    "와", "과", "도", "만", "까지", "부터", "보다", "에는", "에서는", "으로는", "로는",
    "과는", "와는", "이나", "나", "이란", "란", "이며", "며", "이고", "고",
), key=len, reverse=True)
_NOT_A_LABEL = {
    "금", "약", "총", "각", "및", "제", "또는", "그리고", "등", "중", "단", "대략", "최소", "최대",
    "an", "the", "is", "was", "were", "are", "be", "been", "of", "to", "in", "on",
    "at", "by", "for", "and", "or", "with", "about", "around", "approximately", "than", "as",
}
_LABEL_WORDS = 6
_AFTER_WORDS = 3
# A full stop right after a digit is part of a date or list number (2026. 3. 1.).
_CLAUSE_END = re.compile(r"[,;!?\n]|(?<!\d)\.(?!\d)")


#: Verb endings: 승인하고, 승인했다 and 승인한다 all say 승인.
_VERB_ENDINGS = sorted((
    "하였다", "하였으며", "하였고", "했으며", "했다", "했고", "하고", "하며", "한다", "하여",
    "해서", "하는", "하면", "된다", "되었다", "됐다", "되고", "되며", "되어",
), key=len, reverse=True)


def _stem(word: str) -> str:
    word = word.lower()
    for ending in _VERB_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 2:
            return word[: -len(ending)]
    for particle in _PARTICLES:
        # 평가 is a word, not 평 + 가: keep at least two letters.
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def _label(text: str, lo: int, hi: int, glued: bool, *,
           after: bool = False) -> tuple[str, str]:
    """(label, the words as written) for the number before or after
    ``text[lo:hi]``, the words between it and its neighbour."""
    start = lo
    if not after:
        cuts = list(_CLAUSE_END.finditer(text, lo, hi))
        lo = cuts[-1].end() if cuts else lo
    words = [m for m in _WORD.finditer(text, lo, hi)]
    if glued and words and words[0].start() == start and "가" <= text[start:start + 1] <= "힣":
        words = words[1:]
    kept = [w for w in words if _stem(w.group(0)) not in _NOT_A_LABEL
            and w.group(0) not in _PARTICLES]
    if after:
        for n, w in enumerate(kept):
            if _stem(w.group(0)) != w.group(0).lower():   # 확인을: the phrase ends here
                kept = kept[:n + 1]
                break
        kept = kept[:_AFTER_WORDS]
    else:
        kept = kept[-_LABEL_WORDS:]
    if not kept:
        return "", ""
    return (" ".join(_stem(w.group(0)) for w in kept),
            text[kept[0].start():kept[-1].end()])


# A unit declared once for amounts written without one. 연구비(천원)는 75:
# the field's unit, for the next number only. 단위: 백만원 and 천원 단위로:
# for every bare amount after it, up to the next declaration. In a table, a
# header cell's unit (금액(천원)) holds for that column alone, so a row number
# or a year beside it keeps no unit. 정산액(원가) and (만원권) declare nothing.
_WON = r"((?:천|백만|천만|만|억|십억)?원)"
_DECLARED = re.compile(r"\(\s*" + _WON + r"\s*\)"
                       r"|단위\s*[:：]\s*" + _WON + r"(?![가-힣])"
                       r"|(?<![가-힣])" + _WON + r"\s*단위")
_TABLE_RULE = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?")


def _bare(key: str) -> bool:
    return bool(re.fullmatch(r"-?[\d.]+", key))


def _inherited(text: str, tokens: list[re.Match[str]]) -> list[str]:
    """The declared unit each number takes, "" where none applies."""
    out = [""] * len(tokens)
    running, columns, at = "", None, 0
    for line in text.split("\n"):
        start, end, at = at, at + len(line), at + len(line) + 1
        mine = [i for i, m in enumerate(tokens) if start <= m.start() < end]
        cells = line.strip()
        if cells.startswith("|"):
            if _TABLE_RULE.fullmatch(cells):
                continue
            bars = [start + k for k, c in enumerate(line) if c == "|"]
            spans = list(zip(bars, bars[1:]))
            if columns is None:                 # the header row
                columns = {}
                for j, (a, b) in enumerate(spans):
                    found = [next(g for g in d.groups() if g) for d in _DECLARED.finditer(text, a, b)]
                    if found:
                        columns[j] = found[-1]
                continue
            for i in mine:
                j = next((j for j, (a, b) in enumerate(spans) if a < tokens[i].start() < b), None)
                out[i] = columns.get(j, running) if j is not None else running
            continue
        columns = None
        events = [(d.start(), "field" if d.group(1) else "running", next(g for g in d.groups() if g))
                  for d in _DECLARED.finditer(text, start, end)]
        events += [(tokens[i].start(), "number", i) for i in mine]
        field = ""
        for _pos, kind, value in sorted(events, key=lambda e: e[0]):
            if kind == "field":
                field = value
            elif kind == "running":
                running, field = value, ""
            else:
                out[value] = field or running
                field = ""
    return out


def _keys(text: str, tokens: list[re.Match[str]]) -> tuple[list[str], list[str]]:
    """Each number's key, with the unit it inherits from a declaration, and
    how to show it: 7,000 under 금액(천원) is 7,000(천원)."""
    keys, shown = [], []
    for m, unit in zip(tokens, _inherited(text, tokens)):
        key = _number_key(m.group(0))
        if unit and _bare(key):
            keys.append(_number_key(m.group(0) + unit))
            shown.append(f"{m.group(0)}({unit})")
        else:
            keys.append(key)
            shown.append(m.group(0))
    return keys, shown


def number_keys(text: str) -> dict[tuple[int, int], str]:
    """The key of every number in ``text`` by its (start, end): the review
    screen compares spans on these, so it agrees with the guard."""
    tokens = _number_tokens(text)
    return {(m.start(), m.end()): k for m, k in zip(tokens, _keys(text, tokens)[0])}


def _pairs(side: list[tuple], at: int, keys: set[str] | None = None) -> Counter:
    return Counter((t[at], t[1]) for t in side if t[at] and (keys is None or t[1] in keys))


def _aligned(b: list[tuple], a: list[tuple], at: int) -> list[tuple]:
    """``a`` with a label that only gained or lost words at its far end
    (지난 회의에서 총무팀은 for 총무팀은) renamed to the label it was."""
    lb = {t[at] for t in b if t[at]}
    la = {t[at] for t in a if t[at]}
    rename = {}
    for label in la - lb:
        words = label.split()
        near = [old for old in lb - la
                for short, long in ((old.split(), words), (words, old.split()))
                if len(short) < len(long)
                and (long[-len(short):] == short if at == 0 else long[:len(short)] == short)]
        if len(near) == 1:
            rename[label] = near[0]
    if not rename:
        return a
    return [t[:at] + (rename.get(t[at], t[at]),) + t[at + 1:] for t in a]


def _swapped(b: list[tuple], a: list[tuple], at: int) -> set[str]:
    """The numbers one reading (``at`` picks it) sees trade words: among the
    labels both sides have (an edited word elsewhere does not hide a swap),
    the same numbers paired differently."""
    common = Counter(t[at] for t in b if t[at]) & Counter(t[at] for t in a if t[at])
    pb = Counter((t[at], t[1]) for t in b if common[t[at]])
    pa = Counter((t[at], t[1]) for t in a if common[t[at]])
    if pb == pa or (Counter(k for _, k in pb.elements())
                    != Counter(k for _, k in pa.elements())):
        return set()
    return {k for _, k in (pb - pa).elements()}


def _kept(b: list[tuple], a: list[tuple], at: int, keys: set[str]) -> bool:
    """Does the other reading keep those numbers with their words? Only a
    reading that tells every one of them apart counts: 30만원을 청구한다 and
    70만원을 청구한다 share their words after the number, so that reading
    says nothing about them."""
    labels = [t[at] for t in b if t[1] in keys]
    if not all(labels) or len(set(labels)) < len(labels):
        return False
    return _pairs(b, at, keys) == _pairs(a, at, keys)


def _number_change(before: str, after: str) -> dict[str, object] | None:
    """The numbers change between two texts, compared on keys and shown in
    the document's own spelling, or None.

    Two kinds: a number appears a different number of times (500만원 became
    50만원), or every number is still there but labelled numbers traded words
    (기본급은 300만원, 수당은 50만원 → 기본급은 50만원, 수당은 300만원). The
    second is reported when one reading of the labels (the words before each
    number, or the words after it) pairs the same words and numbers
    differently and the other reading, where it tells those numbers apart,
    does not keep them with their words: a sentence that is merely reordered
    (기본급은 300만원 ↔ 수당은 50만원, or 3건 승인 ↔ 5건 보류) stays quiet.

    A bare number under a declared unit (금액(천원), 단위: 백만원) is read
    in that unit, so moving 천원 from the cell to the header is no change and
    changing the header is."""
    sides = []
    for text in (before, after):
        tokens = _number_tokens(text)
        found = []
        for i, (m, key, raw) in enumerate(zip(tokens, *_keys(text, tokens))):
            prev_end = tokens[i - 1].end() if i else 0
            next_start = tokens[i + 1].start() if i + 1 < len(tokens) else len(text)
            pre, pre_shown = _label(text, prev_end, m.start(), i > 0)
            post, post_shown = _label(text, m.end(), next_start, True, after=True)
            found.append((pre, key, post, raw, pre_shown, post_shown))
        sides.append(found)
    b, a = sides
    keys_b, keys_a = Counter(t[1] for t in b), Counter(t[1] for t in a)
    if keys_b != keys_a:
        shown: dict[str, str] = {}
        for t in b + a:
            shown.setdefault(t[1], t[3])
        # A number on both sides is shown in one spelling, so a dropped comma
        # is not listed as lost and added; a new one as the edit wrote it.
        return {"kind": "numbers",
                "before": dict(Counter(shown[t[1]] for t in b)),
                "after": dict(Counter(shown[t[1]] for t in a))}
    a0, a2 = _aligned(b, a, 0), _aligned(b, a, 2)
    pre, post = _swapped(b, a0, 0), _swapped(b, a2, 2)
    if pre and not _kept(b, a2, 2, pre):
        at, keys = 0, pre
    elif post and not _kept(b, a0, 0, post):
        at, keys = 2, post
        # Shown with the words before each number where those name them all
        # (기획팀은 11명), not with the next clause's words (11명 집행팀은).
        if all(t[0] for t in b + a0 if t[1] in keys) and _pairs(b, 0, keys) != _pairs(a0, 0, keys):
            at = 0
    else:
        return None
    a = a0 if at == 0 else a2
    show = (lambda t: f"{t[4]} {t[3]}") if at == 0 else (lambda t: f"{t[3]} {t[5]}")
    pb, pa = _pairs(b, at, keys), _pairs(a, at, keys)

    def only(side: list[tuple], extra: Counter) -> list[str]:
        out = []
        for t in side:                  # in the order the text has them
            if t[at] and extra[(t[at], t[1])] > 0:
                extra[(t[at], t[1])] -= 1
                out.append(show(t))
        return out
    return {"kind": "numbers", "order": True,
            "before": only(b, pb - pa), "after": only(a, pa - pb)}


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
