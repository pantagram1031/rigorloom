#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WARN-only deterministic unit and dimension consistency checker.

Numeric spans and body cleanup reuse ``check_numbers.find_body`` and
``check_numbers.extract_body_numerals``. The deterministic unit dictionary is:

* SI symbols ``m, s, kg, N, J, W, Pa, Hz, V, A, Ω, C, K, mol, cd, rad``;
* prefixes ``n, µ`` (and keyboard ``μ``/``u`` aliases), ``m, c, k, M, G``
  applied to prefixable SI symbols (mass prefixes are applied to grams);
* percent/``퍼센트``, ``dB``/``데시벨``, and conservative spelled report
  aliases for seconds, minutes, hours, metres/meters, grams, and kilograms;
* Korean ``초, 분, 시간, 미터, 센티미터, 밀리미터, 킬로미터, 그램,
  밀리그램, 킬로그램`` plus unambiguous SI-name aliases; and
* compound ``m/s``, ``m/s^2``/``m/s²``, ``km/h``, and ``N·m``/``N*m``
  (with corresponding Korean long forms).

Semantic checks require an explicit subject binding with ``=``, ``:``, or a
Korean topic/subject particle (``은/는/이/가``). ``unit_mismatch`` compares only
the exact same normalized subject and values equal or within one percent, then
warns when unit dimensions differ. ``unit_impossible`` uses this deliberately
small quantity map: distance/length/거리/길이 -> length;
duration/elapsed time/time/시간/기간 -> time; mass/질량 -> mass;
speed/velocity/속도 -> speed; acceleration/가속도 -> acceleration;
force/힘 -> force; temperature/온도 -> temperature. Quantity words must end
the bound subject, which avoids guessing from surrounding prose.

No finding is HARD. Exit 0 includes WARN findings and no-op reports; exit 2 is
reserved for usage/input errors. The checker has no network, LLM, or external
unit-library dependency.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import sys


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import check_numbers  # noqa: E402


ROUNDING_RELATIVE_TOLERANCE = 0.01
PREFIXES = ('n', 'µ', 'μ', 'u', 'm', 'c', 'k', 'M', 'G')
PREFIXABLE_UNITS = {
    'm': 'length',
    's': 'time',
    'g': 'mass',
    'N': 'force',
    'J': 'energy',
    'W': 'power',
    'Pa': 'pressure',
    'Hz': 'frequency',
    'V': 'voltage',
    'A': 'current',
    'Ω': 'resistance',
    'C': 'charge',
    'K': 'temperature',
    'mol': 'amount',
    'cd': 'luminous_intensity',
    'rad': 'angle',
}
REPORT_UNIT_ALIASES = {
    '%': ('%', 'dimensionless'),
    'percent': ('%', 'dimensionless'),
    '퍼센트': ('%', 'dimensionless'),
    'dB': ('dB', 'logarithmic_ratio'),
    '데시벨': ('dB', 'logarithmic_ratio'),
    'min': ('min', 'time'),
    'minute': ('min', 'time'),
    'minutes': ('min', 'time'),
    'h': ('h', 'time'),
    'hour': ('h', 'time'),
    'hours': ('h', 'time'),
    'second': ('s', 'time'),
    'seconds': ('s', 'time'),
    'meter': ('m', 'length'),
    'meters': ('m', 'length'),
    'metre': ('m', 'length'),
    'metres': ('m', 'length'),
    'kilometer': ('km', 'length'),
    'kilometers': ('km', 'length'),
    'kilometre': ('km', 'length'),
    'kilometres': ('km', 'length'),
    'gram': ('g', 'mass'),
    'grams': ('g', 'mass'),
    'kilogram': ('kg', 'mass'),
    'kilograms': ('kg', 'mass'),
    '°C': ('°C', 'temperature'),
    '°F': ('°F', 'temperature'),
    '초': ('s', 'time'),
    '분': ('min', 'time'),
    '시간': ('h', 'time'),
    '미터': ('m', 'length'),
    '센티미터': ('cm', 'length'),
    '밀리미터': ('mm', 'length'),
    '킬로미터': ('km', 'length'),
    '그램': ('g', 'mass'),
    '밀리그램': ('mg', 'mass'),
    '킬로그램': ('kg', 'mass'),
    '뉴턴': ('N', 'force'),
    '와트': ('W', 'power'),
    '파스칼': ('Pa', 'pressure'),
    '헤르츠': ('Hz', 'frequency'),
    '볼트': ('V', 'voltage'),
    '암페어': ('A', 'current'),
    '옴': ('Ω', 'resistance'),
    '켈빈': ('K', 'temperature'),
    '몰': ('mol', 'amount'),
    '라디안': ('rad', 'angle'),
}

UNIT_ALIASES = {}
for _symbol, _dimension in PREFIXABLE_UNITS.items():
    UNIT_ALIASES[_symbol] = (_symbol, _dimension)
    for _prefix in PREFIXES:
        _canonical_prefix = 'µ' if _prefix in {'µ', 'μ', 'u'} else _prefix
        UNIT_ALIASES[_prefix + _symbol] = (
            _canonical_prefix + _symbol,
            _dimension,
        )
UNIT_ALIASES.update(REPORT_UNIT_ALIASES)

_ATOMIC_ALTERNATIVES = '|'.join(
    re.escape(alias)
    for alias in sorted(UNIT_ALIASES, key=lambda item: (-len(item), item))
)
ATOMIC_UNIT_RE = re.compile(
    rf'^\s*(?P<unit>{_ATOMIC_ALTERNATIVES})(?![A-Za-z가-힣])'
)
COMPOUND_UNIT_PATTERNS = (
    (re.compile(r'^\s*(?P<unit>m\s*/\s*s\s*(?:\^\s*2|²))(?![A-Za-z가-힣])'),
     'm/s^2', 'acceleration'),
    (re.compile(r'^\s*(?P<unit>미터\s*/\s*초\s*(?:\^\s*2|²))(?![A-Za-z가-힣])'),
     'm/s^2', 'acceleration'),
    (re.compile(r'^\s*(?P<unit>km\s*/\s*h)(?![A-Za-z가-힣])'),
     'km/h', 'speed'),
    (re.compile(r'^\s*(?P<unit>킬로미터\s*/\s*시간)(?![A-Za-z가-힣])'),
     'km/h', 'speed'),
    (re.compile(r'^\s*(?P<unit>m\s*/\s*s)(?![A-Za-z가-힣])'),
     'm/s', 'speed'),
    (re.compile(r'^\s*(?P<unit>미터\s*/\s*초)(?![A-Za-z가-힣])'),
     'm/s', 'speed'),
    (re.compile(r'^\s*(?P<unit>N\s*[·*]\s*m)(?![A-Za-z가-힣])'),
     'N·m', 'energy'),
    (re.compile(r'^\s*(?P<unit>뉴턴\s*[·*]\s*미터)(?![A-Za-z가-힣])'),
     'N·m', 'energy'),
)
SUBJECT_PATTERNS = (
    re.compile(
        r'(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)'
        r'\s*(?:=|:)\s*$'
    ),
    re.compile(
        r'(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)'
        r'\s*(?:은|는|이|가)\s*$'
    ),
)
QUANTITY_DIMENSIONS = (
    ('elapsed time', 'time'),
    ('acceleration', 'acceleration'),
    ('temperature', 'temperature'),
    ('distance', 'length'),
    ('duration', 'time'),
    ('velocity', 'speed'),
    ('length', 'length'),
    ('speed', 'speed'),
    ('force', 'force'),
    ('mass', 'mass'),
    ('time', 'time'),
    ('가속도', 'acceleration'),
    ('질량', 'mass'),
    ('거리', 'length'),
    ('길이', 'length'),
    ('기간', 'time'),
    ('시간', 'time'),
    ('속도', 'speed'),
    ('온도', 'temperature'),
    ('힘', 'force'),
)


def _usage(workspace, message):
    return {
        'ok': False,
        'workspace': str(workspace),
        'checker': 'check_units',
        'error': message,
        'hard': [],
        'warn': [],
        'counts': {'hard': 0, 'warn': 0},
        'verdict': 'usage_error',
    }, 2


def _base_verdict(workspace, tolerance):
    return {
        'ok': True,
        'workspace': str(workspace),
        'checker': 'check_units',
        'rounding_relative_tolerance': float(tolerance),
        'checked_numerals': 0,
        'tagged_units': 0,
        'hard': [],
        'warn': [],
        'counts': {'hard': 0, 'warn': 0},
        'verdict': 'pass',
    }


def _match_unit(suffix: str) -> dict | None:
    for pattern, canonical, dimension in COMPOUND_UNIT_PATTERNS:
        match = pattern.match(suffix)
        if match:
            return {
                'raw': match.group('unit'),
                'canonical': canonical,
                'dimension': dimension,
                'start': match.start('unit'),
                'end': match.end('unit'),
            }
    match = ATOMIC_UNIT_RE.match(suffix)
    if match is None:
        return None
    raw = match.group('unit')
    canonical, dimension = UNIT_ALIASES[raw]
    return {
        'raw': raw,
        'canonical': canonical,
        'dimension': dimension,
        'start': match.start('unit'),
        'end': match.end('unit'),
    }


def _extraction_view(body: str) -> str:
    """Make every local dictionary unit visible to check_numbers extraction.

    ``extract_body_numerals`` already accepts integers followed by units in its
    own smaller dictionary. For S3-only aliases, replace just the unit text in a
    same-length view with ``m`` before calling that extractor. Numeric text,
    offsets, newlines, and the source body remain unchanged.
    """
    chars = list(body)
    for number in check_numbers.NUMBER_RE.finditer(body):
        tag = _match_unit(body[number.end():number.end() + 64])
        if tag is None:
            continue
        start = number.end() + tag['start']
        end = number.end() + tag['end']
        chars[start] = 'm'
        for index in range(start + 1, end):
            if chars[index] not in '\r\n':
                chars[index] = ' '
    return ''.join(chars)


def _normalize_subject(value: str) -> str | None:
    value = re.sub(r'^\s*(?:#{1,6}|[-*+])\s*', '', value)
    value = re.sub(r'[\s_]+', ' ', value).strip(' -/:;,.()[]{}').casefold()
    value = re.sub(r'^(?:the|a|an)\s+', '', value)
    return value or None


def _subject_before(line: str, number_start: int) -> str | None:
    prefix = line[:number_start]
    boundary = max(prefix.rfind(mark) for mark in ';,.!?。！？')
    clause = prefix[boundary + 1:]
    for pattern in SUBJECT_PATTERNS:
        match = pattern.search(clause)
        if match:
            return _normalize_subject(match.group('subject'))
    return None


def _subject_dimension(subject: str | None) -> str | None:
    if not subject:
        return None
    for quantity, dimension in QUANTITY_DIMENSIONS:
        if re.search(r'[A-Za-z]', quantity):
            if re.search(rf'(?:^|\s){re.escape(quantity)}$', subject):
                return dimension
        elif subject.endswith(quantity):
            return dimension
    return None


def _number_claims(text: str) -> tuple[list[dict], int]:
    cleaned = check_numbers.find_body(text)
    candidates = check_numbers.extract_body_numerals(_extraction_view(cleaned))
    lines = cleaned.splitlines()
    cursors: dict[int, int] = defaultdict(int)
    claims = []
    for candidate in candidates:
        line_number = candidate['line']
        if not (1 <= line_number <= len(lines)):
            continue
        line = lines[line_number - 1]
        start = line.find(candidate['raw'], cursors[line_number])
        if start < 0:
            start = line.find(candidate['raw'])
        if start < 0:
            continue
        end = start + len(candidate['raw'])
        cursors[line_number] = end
        tag = _match_unit(line[end:end + 64])
        if tag is None:
            continue
        claims.append({
            **candidate,
            'subject': _subject_before(line, start),
            'unit': tag['canonical'],
            'unit_raw': tag['raw'],
            'dimension': tag['dimension'],
            'snippet': line.strip()[:160],
        })
    return claims, len(candidates)


def _compatible(left: float, right: float, tolerance: float) -> bool:
    return left == right or math.isclose(
        left,
        right,
        rel_tol=tolerance,
        abs_tol=0.0,
    )


def check(workspace, tolerance=ROUNDING_RELATIVE_TOLERANCE):
    if (not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool)
            or not math.isfinite(tolerance) or tolerance < 0):
        return _usage(workspace, 'tolerance must be a finite non-negative number')

    ws = Path(workspace)
    content_path = ws / 'bundle' / 'content.md'
    try:
        body = content_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return _usage(workspace, 'bundle/content.md not found')
    except (OSError, UnicodeError) as exc:
        return _usage(workspace, f'bundle/content.md unreadable: {exc}')

    claims, checked_numerals = _number_claims(body)
    warn = []

    for left_index, left in enumerate(claims):
        if not left['subject']:
            continue
        for right in claims[left_index + 1:]:
            if left['subject'] != right['subject']:
                continue
            if left['dimension'] == right['dimension']:
                continue
            if not _compatible(left['value'], right['value'], float(tolerance)):
                continue
            warn.append({
                'code': 'unit_mismatch',
                'severity': 'WARN',
                'msg': 'same explicitly bound subject has close values with incompatible units',
                'at': 'bundle/content.md',
                'line': left['line'],
                'other_line': right['line'],
                'subject': left['subject'],
                'value': left['value'],
                'other_value': right['value'],
                'unit': left['unit_raw'],
                'other_unit': right['unit_raw'],
                'dimension': left['dimension'],
                'other_dimension': right['dimension'],
            })

    for claim in claims:
        expected = _subject_dimension(claim['subject'])
        if expected is None or expected == claim['dimension']:
            continue
        warn.append({
            'code': 'unit_impossible',
            'severity': 'WARN',
            'msg': 'explicitly bound quantity word has an incompatible unit dimension',
            'at': 'bundle/content.md',
            'line': claim['line'],
            'subject': claim['subject'],
            'value': claim['value'],
            'unit': claim['unit_raw'],
            'expected_dimension': expected,
            'actual_dimension': claim['dimension'],
        })

    verdict = _base_verdict(workspace, tolerance)
    verdict['checked_numerals'] = checked_numerals
    verdict['tagged_units'] = len(claims)
    verdict['warn'] = warn
    verdict['counts'] = {'hard': 0, 'warn': len(warn)}
    if not checked_numerals:
        verdict['note'] = 'no body numeric spans found; unit check is a no-op'
    return verdict, 0


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description='advisory unit and dimension consistency check for report body'
    )
    parser.add_argument('workspace', help='report workspace directory')
    parser.add_argument(
        '--tolerance',
        type=float,
        default=ROUNDING_RELATIVE_TOLERANCE,
        help='relative tolerance for close-value restatements (default: 0.01)',
    )
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace, tolerance=args.tolerance)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return code


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


if __name__ == '__main__':
    raise SystemExit(main())
