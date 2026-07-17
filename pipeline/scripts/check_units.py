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
import claim_extraction  # noqa: E402
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    usage_error,
    verdict_skeleton,
)


ROUNDING_RELATIVE_TOLERANCE = 0.01
PREFIXES = claim_extraction.PREFIXES
PREFIXABLE_UNITS = claim_extraction.PREFIXABLE_UNITS
REPORT_UNIT_ALIASES = claim_extraction.REPORT_UNIT_ALIASES
UNIT_ALIASES = claim_extraction.UNIT_ALIASES
ATOMIC_UNIT_RE = claim_extraction.ATOMIC_UNIT_RE
COMPOUND_UNIT_PATTERNS = claim_extraction.COMPOUND_UNIT_PATTERNS
SUBJECT_PATTERNS = claim_extraction.BASIC_SUBJECT_PATTERNS
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
    return usage_error(
        str(workspace), "check_units", message,
        counts={"hard": 0, "warn": 0},
    )


def _base_verdict(workspace, tolerance):
    return verdict_skeleton(
        str(workspace),
        "check_units",
        extra={
            "rounding_relative_tolerance": float(tolerance),
            "checked_numerals": 0,
            "tagged_units": 0,
        },
    )


def _match_unit(suffix: str) -> dict | None:
    return claim_extraction.match_units_unit(suffix)


def _extraction_view(body: str) -> str:
    return claim_extraction._units_extraction_view(body)


def _normalize_subject(value: str) -> str | None:
    return claim_extraction.normalize_subject(value)


def _subject_before(line: str, number_start: int) -> str | None:
    return claim_extraction.subject_before(
        line, number_start, include_english=False
    )


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
    shared, checked = claim_extraction.extract_numeric_claims(
        text, policy="units"
    )
    claims = [
        {
            "value": claim["value"],
            "raw": claim["raw"],
            "line": claim["line"],
            "subject": claim["subject"],
            "unit": claim["unit"],
            "unit_raw": claim["unit_raw"],
            "dimension": claim["dimension"],
            "snippet": claim["snippet"],
        }
        for claim in shared
    ]
    return claims, checked


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
    parser.add_argument('--out', default=None, help='write verdict JSON here')
    return cli_main(
        parser,
        lambda args: check(args.workspace, tolerance=args.tolerance),
        argv,
    )


if __name__ == '__main__':
    raise SystemExit(main())
