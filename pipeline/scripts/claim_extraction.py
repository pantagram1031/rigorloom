#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared numeric-claim, subject, and unit extraction for content checkers.

The union tag and checker-specific comparison tag are intentionally distinct.
For example, Korean long-form unit 미터 must not turn a legacy saeteuk
unsupported claim into a contradiction, while core count unit trials must not
increase check_units' legacy tagged_units count. Regression tests cover both
cases while exposing the union tag to future consumers.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any, Iterable


NUMBER_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)"
    r"(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])"
)
UNIT_RE = re.compile(
    r"^\s*(?:%|\u2030|\u00b0\s*[CFK]?|dB|Hz|kHz|MHz|GHz|ms|\u03bcs|us|ns|s|min|h|AU|"
    r"mm|cm|km|m|mg|kg|g|mL|L|N|Pa|kPa|MPa|J|W|kW|V|mV|A|mA|"
    r"\u03a9|ohm|rad|rpm|m/s|km/h|\ucd08|\ubd84|\uc2dc\uac04|\ub3c4|"
    r"\ud68c|\ubc88|\uac1c|\uba85|\uac74)(?![A-Za-z])",
    re.I,
)
ENGLISH_COUNT_UNIT_RE = re.compile(
    r"^\s*(?:trials?|runs?|samples?|iterations?|cases?|times?)\b", re.I
)
REFERENCE_PREFIX_RE = re.compile(
    r"(?:figure|fig\.?|table|page|pages|p\.?|pp\.?|section|sec\.?|"
    r"\uadf8\ub9bc|\ud45c|\ud398\uc774\uc9c0|\ucabd|\uc808|\uc7a5)"
    r"\s*(?:no\.?\s*)?$", re.I,
)
REFERENCE_SUFFIX_RE = re.compile(
    r"^\s*(?:\ucabd|\ud398\uc774\uc9c0|\uc808|\uc7a5)(?![A-Za-z])"
)


SI_PREFIX_SCALES = {
    "": 1.0, "n": 1e-9, "µ": 1e-6, "μ": 1e-6, "u": 1e-6,
    "m": 1e-3, "c": 1e-2, "k": 1e3, "M": 1e6, "G": 1e9,
}
SI_BASE_UNITS = (
    "mol", "rad", "Pa", "Hz", "cd", "m", "s", "g", "L", "N", "J",
    "W", "V", "A", "Ω", "C", "K",
)
PREFIXES = tuple(prefix for prefix in SI_PREFIX_SCALES if prefix)
PREFIXABLE_UNITS = {
    "m": "length", "s": "time", "g": "mass", "N": "force",
    "J": "energy", "W": "power", "Pa": "pressure", "Hz": "frequency",
    "V": "voltage", "A": "current", "Ω": "resistance", "C": "charge",
    "K": "temperature", "mol": "amount", "cd": "luminous_intensity",
    "rad": "angle",
}
REPORT_UNIT_ALIASES = {
    "%": ("%", "dimensionless"),
    "percent": ("%", "dimensionless"),
    "퍼센트": ("%", "dimensionless"),
    "dB": ("dB", "logarithmic_ratio"),
    "AU": ("AU", "length"),
    "데시벨": ("dB", "logarithmic_ratio"),
    "min": ("min", "time"),
    "minute": ("min", "time"),
    "minutes": ("min", "time"),
    "h": ("h", "time"),
    "hour": ("h", "time"),
    "hours": ("h", "time"),
    "second": ("s", "time"),
    "seconds": ("s", "time"),
    "meter": ("m", "length"),
    "meters": ("m", "length"),
    "metre": ("m", "length"),
    "metres": ("m", "length"),
    "kilometer": ("km", "length"),
    "kilometers": ("km", "length"),
    "kilometre": ("km", "length"),
    "kilometres": ("km", "length"),
    "gram": ("g", "mass"),
    "grams": ("g", "mass"),
    "kilogram": ("kg", "mass"),
    "kilograms": ("kg", "mass"),
    "°C": ("°C", "temperature"),
    "°F": ("°F", "temperature"),
    "초": ("s", "time"),
    "분": ("min", "time"),
    "시간": ("h", "time"),
    "미터": ("m", "length"),
    "센티미터": ("cm", "length"),
    "밀리미터": ("mm", "length"),
    "킬로미터": ("km", "length"),
    "그램": ("g", "mass"),
    "밀리그램": ("mg", "mass"),
    "킬로그램": ("kg", "mass"),
    "뉴턴": ("N", "force"),
    "와트": ("W", "power"),
    "파스칼": ("Pa", "pressure"),
    "헤르츠": ("Hz", "frequency"),
    "볼트": ("V", "voltage"),
    "암페어": ("A", "current"),
    "옴": ("Ω", "resistance"),
    "켈빈": ("K", "temperature"),
    "몰": ("mol", "amount"),
    "라디안": ("rad", "angle"),
}

UNIT_ALIASES: dict[str, tuple[str, str]] = {}
for _symbol, _dimension in PREFIXABLE_UNITS.items():
    UNIT_ALIASES[_symbol] = (_symbol, _dimension)
    for _prefix in PREFIXES:
        _canonical_prefix = "µ" if _prefix in {"µ", "μ", "u"} else _prefix
        UNIT_ALIASES[_prefix + _symbol] = (
            _canonical_prefix + _symbol,
            _dimension,
        )
UNIT_ALIASES.update(REPORT_UNIT_ALIASES)

COMPOUND_UNIT_PATTERNS = (
    (re.compile(r"^\s*(?P<unit>m\s*/\s*s\s*(?:\^\s*2|²))(?![A-Za-z가-힣])"),
     "m/s^2", "acceleration"),
    (re.compile(r"^\s*(?P<unit>미터\s*/\s*초\s*(?:\^\s*2|²))(?![A-Za-z가-힣])"),
     "m/s^2", "acceleration"),
    (re.compile(r"^\s*(?P<unit>km\s*/\s*h)(?![A-Za-z가-힣])"),
     "km/h", "speed"),
    (re.compile(r"^\s*(?P<unit>킬로미터\s*/\s*시간)(?![A-Za-z가-힣])"),
     "km/h", "speed"),
    (re.compile(r"^\s*(?P<unit>m\s*/\s*s)(?![A-Za-z가-힣])"),
     "m/s", "speed"),
    (re.compile(r"^\s*(?P<unit>미터\s*/\s*초)(?![A-Za-z가-힣])"),
     "m/s", "speed"),
    (re.compile(r"^\s*(?P<unit>N\s*[·*]\s*m)(?![A-Za-z가-힣])"),
     "N·m", "energy"),
    (re.compile(r"^\s*(?P<unit>뉴턴\s*[·*]\s*미터)(?![A-Za-z가-힣])"),
     "N·m", "energy"),
)

_CORE_ONLY_ALIASES = {
    "‰": ("‰", "dimensionless"), "°": ("°", "angle"),
    "°K": ("K", "temperature"), "L": ("L", "volume"),
    "mL": ("mL", "volume"), "ohm": ("Ω", "resistance"),
    "rpm": ("rpm", "angular_speed"), "도": ("°", "angle"),
    "회": ("회", "count"), "번": ("번", "count"),
    "개": ("개", "count"), "명": ("명", "count"),
    "건": ("건", "count"),
    "trial": ("trial", "count"), "trials": ("trial", "count"),
    "run": ("run", "count"), "runs": ("run", "count"),
    "sample": ("sample", "count"), "samples": ("sample", "count"),
    "iteration": ("iteration", "count"),
    "iterations": ("iteration", "count"),
    "case": ("case", "count"), "cases": ("case", "count"),
    "time": ("time", "count"), "times": ("times", "count"),
}
UNION_UNIT_ALIASES = dict(UNIT_ALIASES)
for _alias, _tag in _CORE_ONLY_ALIASES.items():
    UNION_UNIT_ALIASES.setdefault(_alias, _tag)


def _atomic_regex(aliases: Iterable[str]) -> re.Pattern:
    alternatives = "|".join(
        re.escape(alias)
        for alias in sorted(aliases, key=lambda item: (-len(item), item))
    )
    return re.compile(rf"^\s*(?P<unit>{alternatives})(?![A-Za-z가-힣])")


ATOMIC_UNIT_RE = _atomic_regex(UNIT_ALIASES)
UNION_ATOMIC_UNIT_RE = _atomic_regex(UNION_UNIT_ALIASES)
SAETEUK_UNIT_EXTENSION_RE = re.compile(
    r"^(?:(?:[/·*^]\s*[A-Za-zΑ-Ωα-ω0-9+-]+)|[²³])+"
)
UNIT_EXTENSION_RE = re.compile(
    r"^(?:(?:[/·*^]\s*[A-Za-z가-힣Α-Ωα-ω0-9+-]+)|[²³])+"
)

BASIC_SUBJECT_PATTERNS = (
    re.compile(
        r"(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)"
        r"\s*(?:=|:)\s*$"
    ),
    re.compile(
        r"(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)"
        r"\s*(?:은|는|이|가)\s*$"
    ),
)
ENGLISH_SUBJECT_PATTERN = re.compile(
    r"(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)"
    r"\s+(?:is|was|were|equals?|measured(?:\s+at)?|reached)\s*$",
    re.I,
)
SUBJECT_PATTERNS = (*BASIC_SUBJECT_PATTERNS, ENGLISH_SUBJECT_PATTERN)


def find_body(markdown: str) -> str:
    """Return content with build tags removed, preserving legacy behavior."""
    return re.sub(r"\[\[.*?\]\]", " ", markdown, flags=re.S)


def is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _significant_digits(raw: str) -> int:
    mantissa = re.split(r"[eE]", raw.replace(",", ""))[0].lstrip("+-")
    digits = mantissa.replace(".", "").lstrip("0")
    return len(digits)


def _is_ignored_context(
    body: str, start: int, end: int, raw: str, value: float
) -> bool:
    before = body[max(0, start - 48):start]
    after = body[end:end + 24]
    if re.fullmatch(r"\d{4}", raw.replace(",", "")) and 1800 <= value <= 2199:
        return True

    line_start = body.rfind("\n", 0, start) + 1
    line_end = body.find("\n", end)
    if line_end < 0:
        line_end = len(body)
    line = body[line_start:line_end]
    relative_start = start - line_start
    relative_end = end - line_start
    open_paren = line.rfind("(", 0, relative_start)
    close_paren = line.find(")", relative_end)
    if open_paren >= 0 and close_paren >= 0:
        parenthetical = line[open_paren:close_paren + 1]
        if re.search(r"(?:18|19|20|21)\d{2}", parenthetical):
            return True
    open_bracket = line.rfind("[", 0, relative_start)
    close_bracket = line.find("]", relative_end)
    if open_bracket >= 0 and close_bracket >= 0:
        bracketed = line[open_bracket:close_bracket + 1]
        if re.search(r"(?:18|19|20|21)\d{2}", bracketed):
            return True
    if REFERENCE_PREFIX_RE.search(before) or REFERENCE_SUFFIX_RE.match(after):
        return True
    line_prefix = before.rsplit("\n", 1)[-1]
    if re.fullmatch(r"\s*#{1,6}\s*", line_prefix):
        return True
    if re.fullmatch(r"\s*", line_prefix) and re.match(r"\s*[.)]\s+", after):
        return True
    return False


def _has_clear_unit(body: str, end: int) -> bool:
    after = body[end:end + 24]
    return bool(UNIT_RE.match(after) or ENGLISH_COUNT_UNIT_RE.match(after))


def extract_body_numerals(body: str, allowed_numbers=None) -> list[dict]:
    """Return the exact conservative candidate set used by check_numbers."""
    allowed = {
        float(value)
        for value in (allowed_numbers or set())
        if is_number(value)
    }
    candidates = []
    for match in NUMBER_RE.finditer(body):
        raw = match.group(0)
        try:
            value = _parse_number(raw)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        if _is_ignored_context(body, match.start(), match.end(), raw, value):
            continue
        has_unit = _has_clear_unit(body, match.end())
        if "." not in raw and "e" not in raw.lower() and not has_unit:
            continue
        if not has_unit and _significant_digits(raw) < 2:
            continue
        if any(value == allowed_value for allowed_value in allowed):
            continue
        line = body.count("\n", 0, match.start()) + 1
        candidates.append({"value": value, "raw": raw, "line": line})
    return candidates


def normalize_subject(value: str) -> str | None:
    value = re.sub(r"^\s*(?:#{1,6}|[-*+])\s*", "", value)
    value = re.sub(r"[\s_]+", " ", value).strip(" -/:;,.()[]{}").casefold()
    value = re.sub(r"^(?:the|a|an)\s+", "", value)
    return value or None


def subject_before(
    line: str, number_start: int, *, include_english: bool = True
) -> str | None:
    prefix = line[:number_start]
    boundary = max(prefix.rfind(mark) for mark in ";,.!?。！？")
    clause = prefix[boundary + 1:]
    patterns = SUBJECT_PATTERNS if include_english else BASIC_SUBJECT_PATTERNS
    for pattern in patterns:
        match = pattern.search(clause)
        if match:
            return normalize_subject(match.group("subject"))
    return None


def canonical_si_unit(value: str | None) -> tuple[str | None, float]:
    """Return a case-sensitive F12 base symbol and SI prefix scale."""
    normalized = re.sub(r"\s+", "", value or "")
    if not normalized:
        return None, 1.0
    for base in SI_BASE_UNITS:
        for prefix, scale in SI_PREFIX_SCALES.items():
            if normalized == prefix + base:
                return base, scale
    return normalized, 1.0


def _unit_payload(
    match: re.Match, canonical: str, dimension: str
) -> dict[str, Any]:
    raw = match.group("unit")
    base, scale = canonical_si_unit(canonical)
    return {
        "raw": raw,
        "canonical": canonical,
        "dimension": dimension,
        "base": base,
        "scale": scale,
        "start": match.start("unit"),
        "end": match.end("unit"),
    }


def _match_dictionary_unit(
    suffix: str, aliases: dict[str, tuple[str, str]], atomic_re: re.Pattern
) -> dict[str, Any] | None:
    for pattern, canonical, dimension in COMPOUND_UNIT_PATTERNS:
        match = pattern.match(suffix)
        if match:
            return _unit_payload(match, canonical, dimension)
    match = atomic_re.match(suffix)
    if match is None:
        return None
    canonical, dimension = aliases[match.group("unit")]
    return _unit_payload(match, canonical, dimension)


def match_unit(suffix: str) -> dict[str, Any] | None:
    """Return the authoritative case-sensitive union tag for a suffix."""
    return _match_dictionary_unit(
        suffix, UNION_UNIT_ALIASES, UNION_ATOMIC_UNIT_RE
    )


def match_units_unit(suffix: str) -> dict[str, Any] | None:
    """Return check_units' legacy dictionary tag."""
    return _match_dictionary_unit(suffix, UNIT_ALIASES, ATOMIC_UNIT_RE)


def match_saeteuk_unit(suffix: str) -> dict[str, Any] | None:
    """Return check_saeteuk's legacy F12/core-regex comparison tag."""
    window = suffix[:24]
    match = UNIT_RE.match(window)
    if match is None:
        match = ENGLISH_COUNT_UNIT_RE.match(window)
    if match is None:
        return None
    raw_with_space = match.group(0)
    extension = SAETEUK_UNIT_EXTENSION_RE.match(window[match.end():])
    if extension:
        raw_with_space += extension.group(0)
    raw = raw_with_space.strip()
    base, scale = canonical_si_unit(raw)
    return {
        "raw": raw,
        "canonical": base,
        "base": base,
        "scale": scale,
        "start": len(raw_with_space) - len(raw_with_space.lstrip()),
        "end": len(raw_with_space),
    }


def _units_extraction_view(body: str) -> str:
    """Preserve check_units' integer-candidate visibility and source offsets."""
    chars = list(body)
    for number in NUMBER_RE.finditer(body):
        tag = match_units_unit(body[number.end():number.end() + 64])
        if tag is None:
            continue
        start = number.end() + tag["start"]
        end = number.end() + tag["end"]
        chars[start] = "m"
        for index in range(start + 1, end):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def extract_numeric_claims(
    text: str,
    *,
    source: str | None = None,
    policy: str = "saeteuk",
    allowed_numbers=None,
) -> tuple[list[dict], int]:
    """Extract enriched claims once using a checker-compatible policy.

    union_unit is always computed. The public unit fields retain the selected
    checker's legacy semantics so union-only aliases cannot change a verdict.
    """
    if policy not in {"saeteuk", "units"}:
        raise ValueError(f"unsupported claim extraction policy: {policy}")
    cleaned = find_body(text)
    extraction_view = (
        _units_extraction_view(cleaned) if policy == "units" else cleaned
    )
    candidates = extract_body_numerals(
        extraction_view, allowed_numbers=allowed_numbers
    )
    lines = cleaned.splitlines()
    cursors: dict[int, int] = defaultdict(int)
    claims = []
    for candidate in candidates:
        line_number = candidate["line"]
        if not (1 <= line_number <= len(lines)):
            continue
        line = lines[line_number - 1]
        start = line.find(candidate["raw"], cursors[line_number])
        if start < 0:
            start = line.find(candidate["raw"])
        if start < 0:
            continue
        end = start + len(candidate["raw"])
        cursors[line_number] = end
        suffix = line[end:end + 64]
        union_tag = match_unit(suffix)
        selected = (
            match_units_unit(suffix)
            if policy == "units"
            else match_saeteuk_unit(suffix)
        )
        if policy == "units" and selected is None:
            continue
        subject = subject_before(
            line, start, include_english=(policy == "saeteuk")
        )
        claim = {
            **candidate,
            "subject": subject,
            "union_unit": union_tag,
            "snippet": line.strip()[:160],
        }
        if source is not None:
            claim["source"] = source
        if policy == "units":
            claim.update({
                "unit": selected["canonical"],
                "unit_raw": selected["raw"],
                "dimension": selected["dimension"],
            })
        else:
            value = candidate["value"]
            scale = selected["scale"] if selected else 1.0
            canonical_value = value * scale
            if not math.isfinite(value) or not math.isfinite(canonical_value):
                continue
            claim.update({
                "unit": selected["canonical"] if selected else None,
                "unit_raw": selected["raw"] if selected else None,
                "unit_scale": scale,
                "canonical_value": canonical_value,
            })
        claims.append(claim)
    return claims, len(candidates)
