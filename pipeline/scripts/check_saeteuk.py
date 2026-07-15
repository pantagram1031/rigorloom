#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''Deterministic saeteuk-to-report consistency checker.

Artifact convention is workspace-scoped: UTF-8 ``*.txt`` and ``*.md`` files in
``<workspace>/_saeteuk/`` are read. Parent-directory fallback is intentionally
not used because it can bind another report's artifact. Unsafe symlinks and
paths whose real path escapes the selected directory are ignored. No local
directory is an intentional no-op PASS; an existing directory with no readable
artifact is WARN ``saeteuk_missing``.

Numeric candidates come directly from check_numbers.extract_body_numerals.
A numeric context is HARD-comparable only when both sides use an explicit
binding (``subject = value``, ``subject: value``, Korean topic particle, or a
small English copula list), have the exact same normalized subject and
case-sensitive compatible unit, and each side has one distinct value for that
key. A subject consisting only of a generic quantity word is instead WARN
``saeteuk_possible_contradiction``, because the two values may describe
different physical objects. SI prefixes are scaled before comparison. Values within the larger of
1 percent relative tolerance and the lower-precision value's
half-unit-in-last-place are rounding-compatible. Multiple values for one key
are WARN ``saeteuk_ambiguous``. Unsupported numeric claims and deterministic
named-entity anchors are WARN.

Named entities are backtick spans, English title-case sequences or acronyms
(sentence-initial single title-case words are excluded), and Korean tokens with
an explicit organization/project suffix. This is an anchor heuristic, not NER.

Exit 0 = pass, including WARN findings or no artifact. Exit 3 = HARD numeric
contradiction. Exit 2 = usage/input error after an artifact is discovered.
'''
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import re
import sys


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import check_numbers  # noqa: E402
import check_units  # noqa: E402


ROUNDING_RELATIVE_TOLERANCE = 0.01
SI_PREFIX_SCALES = {
    '': 1.0,
    'n': 1e-9,
    'µ': 1e-6,
    'μ': 1e-6,
    'u': 1e-6,
    'm': 1e-3,
    'c': 1e-2,
    'k': 1e3,
    'M': 1e6,
    'G': 1e9,
}
SI_BASE_UNITS = (
    'mol', 'rad', 'Pa', 'Hz', 'cd', 'm', 's', 'g', 'L', 'N', 'J', 'W',
    'V', 'A', 'Ω', 'C', 'K',
)
ENGLISH_ENTITY_RE = re.compile(
    r'(?<![\w])(?:[A-Z][a-z][A-Za-z0-9-]*|[A-Z]{2,})'
    r'(?:[ \t]+(?:[A-Z][a-z][A-Za-z0-9-]*|[A-Z]{2,})){0,3}(?![\w])'
)
BACKTICK_ENTITY_RE = re.compile(r'`(?P<entity>[^`\r\n]{2,60})`')
KOREAN_ENTITY_RE = re.compile(
    r'(?<![가-힣])(?P<entity>[가-힣]{2,24}(?:대학교|대학|연구소|학회|재단|박물관|관측소|프로젝트))(?![가-힣])'
)
UNIT_EXTENSION_RE = re.compile(
    r'^(?:(?:[/·*^]\s*[A-Za-zΑ-Ωα-ω0-9+-]+)|[²³])+'
)
SINGLE_TITLE_STOPWORDS = frozenset({
    'a', 'an', 'and', 'as', 'at', 'for', 'from', 'in', 'measurements', 'result',
    'results', 'the', 'this', 'to', 'using', 'we', 'with',
})
SUBJECT_PATTERNS = (
    re.compile(
        r'(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)'
        r'\s*(?:=|:)\s*$'
    ),
    re.compile(
        r'(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)'
        r'\s*(?:은|는|이|가)\s*$'
    ),
    re.compile(
        r'(?P<subject>[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω _/-]{0,79}?)'
        r'\s+(?:is|was|were|equals?|measured(?:\s+at)?|reached)\s*$',
        re.I,
    ),
)
GENERIC_QUANTITY_SUBJECTS = frozenset(
    re.sub(r'[\s_]+', ' ', quantity).strip().casefold()
    for quantity, _dimension in check_units.QUANTITY_DIMENSIONS
)


def _usage(workspace, message):
    return {
        'ok': False,
        'workspace': str(workspace),
        'checker': 'check_saeteuk',
        'error': message,
        'hard': [],
        'warn': [],
        'counts': {'hard': 0, 'warn': 0},
        'verdict': 'usage_error',
    }, 2


def _base_verdict(workspace) -> dict:
    return {
        'ok': True,
        'workspace': str(workspace),
        'checker': 'check_saeteuk',
        'saeteuk_files': [],
        'rounding_relative_tolerance': ROUNDING_RELATIVE_TOLERANCE,
        'checked_numbers': 0,
        'checked_entities': 0,
        'hard': [],
        'warn': [],
        'counts': {'hard': 0, 'warn': 0},
        'verdict': 'pass',
    }


def _contained(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except (OSError, ValueError):
        return False


def _display_path(workspace: Path, path: Path) -> str:
    try:
        return Path(os.path.relpath(path, workspace)).as_posix()
    except (OSError, ValueError):
        return path.name


def _safe_text_files(directory: Path) -> tuple[list[Path], list[str], str | None]:
    notes = []
    if directory.is_symlink():
        return [], [f'unsafe symlinked saeteuk directory skipped: {directory.name}'], None
    if not directory.exists():
        return [], notes, None
    if not directory.is_dir():
        return [], notes, f'saeteuk path is not a directory: {directory}'
    try:
        allowed_parent = directory.parent.resolve(strict=True)
        root = directory.resolve(strict=True)
        if not _contained(allowed_parent, root):
            return [], [f'escaping saeteuk directory skipped: {directory.name}'], None
        files = []
        for child in sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if (
                child.suffix.casefold() not in {'.txt', '.md'}
                or child.is_symlink()
                or not child.is_file()
            ):
                continue
            resolved = child.resolve(strict=True)
            if _contained(root, resolved):
                files.append(resolved)
            else:
                notes.append(f'escaping saeteuk path skipped: {child.name}')
        return files, notes, None
    except OSError as exc:
        notes.append(f'saeteuk directory unreadable: {exc}')
        return [], notes, None


def _discover_saeteuk(
    workspace: Path,
) -> tuple[list[Path], list[str], str | None, bool]:
    """Discover workspace-local artifacts only; never consult the parent."""
    directory = workspace / '_saeteuk'
    directory_found = directory.exists() or directory.is_symlink()
    if not directory_found:
        return [], [], None, False
    # TODO(v0.12): bind discovered artifacts to a workspace manifest and hash.
    files, notes, error = _safe_text_files(directory)
    return files, notes, error, True


def _canonical_unit(value: str | None) -> tuple[str | None, float]:
    """Return a case-sensitive base symbol and SI prefix scale."""
    normalized = re.sub(r'\s+', '', value or '')
    if not normalized:
        return None, 1.0
    for base in SI_BASE_UNITS:
        for prefix, scale in SI_PREFIX_SCALES.items():
            if normalized == prefix + base:
                return base, scale
    return normalized, 1.0


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


def _unit_after(
    line: str, number_end: int
) -> tuple[str | None, str | None, float]:
    suffix = line[number_end:number_end + 24]
    match = check_numbers.UNIT_RE.match(suffix)
    if match is None:
        match = check_numbers.ENGLISH_COUNT_UNIT_RE.match(suffix)
    if match is None:
        return None, None, 1.0
    raw_with_space = match.group(0)
    extension = UNIT_EXTENSION_RE.match(suffix[match.end():])
    if extension:
        raw_with_space += extension.group(0)
    raw = raw_with_space.strip()
    unit, scale = _canonical_unit(raw)
    return raw, unit, scale


def _number_claims(text: str, source: str) -> list[dict]:
    '''Enrich check_numbers candidates without performing a second extraction.'''
    cleaned = check_numbers.find_body(text)
    candidates = check_numbers.extract_body_numerals(cleaned)
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
        unit_raw, unit, unit_scale = _unit_after(line, end)
        value = candidate['value']
        canonical_value = value * unit_scale
        if not math.isfinite(value) or not math.isfinite(canonical_value):
            continue
        claims.append({
            **candidate,
            'source': source,
            'subject': _subject_before(line, start),
            'unit': unit,
            'unit_raw': unit_raw,
            'unit_scale': unit_scale,
            'canonical_value': canonical_value,
            'snippet': line.strip()[:160],
        })
    return claims


def _sentence_initial(text: str, start: int) -> bool:
    prefix = text[max(0, start - 80):start]
    return not prefix.strip() or bool(re.search(r'[.!?。！？]\s*$', prefix))


def extract_entities(text: str) -> list[dict]:
    '''Return deterministic proper-name anchors with stable line numbers.'''
    cleaned = check_numbers.find_body(text)
    found = []
    for match in BACKTICK_ENTITY_RE.finditer(cleaned):
        found.append((match.start(), match.group('entity').strip()))
    for match in ENGLISH_ENTITY_RE.finditer(cleaned):
        entity = match.group(0).strip()
        words = entity.split()
        normalized = entity.casefold()
        if len(words) == 1:
            if normalized in SINGLE_TITLE_STOPWORDS:
                continue
            if not entity.isupper() and _sentence_initial(cleaned, match.start()):
                continue
        if words and words[0].casefold() in {'a', 'an', 'the'}:
            entity = ' '.join(words[1:])
        if entity:
            found.append((match.start(), entity))
    for match in KOREAN_ENTITY_RE.finditer(cleaned):
        found.append((match.start(), match.group('entity')))

    entities = []
    seen = set()
    for start, entity in sorted(found, key=lambda item: (item[0], item[1].casefold())):
        normalized = _compact(entity)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        entities.append({
            'entity': entity,
            'normalized': normalized,
            'line': cleaned.count('\n', 0, start) + 1,
        })
    return entities


def _compact(value: str) -> str:
    return re.sub(r'[\W_]+', '', value.casefold(), flags=re.UNICODE)


def _written_unit_in_last_place(raw: str) -> float:
    cleaned = raw.replace(',', '').lstrip('+-')
    mantissa, marker, exponent_text = cleaned.partition('e')
    if not marker:
        mantissa, marker, exponent_text = cleaned.partition('E')
    exponent = int(exponent_text) if marker else 0
    decimal_places = len(mantissa.partition('.')[2])
    try:
        return 10.0 ** (exponent - decimal_places)
    except OverflowError:
        return math.inf


def _compatible(left: dict, right: dict, tolerance: float) -> bool:
    left_value = left['canonical_value']
    right_value = right['canonical_value']
    if not math.isfinite(left_value) or not math.isfinite(right_value):
        return False
    relative_limit = tolerance * max(abs(left_value), abs(right_value))
    absolute_limit = 0.5 * max(
        _written_unit_in_last_place(left['raw']) * left['unit_scale'],
        _written_unit_in_last_place(right['raw']) * right['unit_scale'],
    )
    return abs(left_value - right_value) <= max(
        relative_limit, absolute_limit
    )


def _context_key(claim: dict) -> tuple[str, str] | None:
    if claim['subject'] and claim['unit']:
        return claim['subject'], claim['unit']
    return None


def check(workspace, tolerance=ROUNDING_RELATIVE_TOLERANCE):
    ws = Path(workspace)
    if (not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool)
            or not math.isfinite(tolerance) or tolerance < 0):
        return _usage(workspace, 'tolerance must be a finite non-negative number')

    saeteuk_paths, discovery_notes, error, directory_found = (
        _discover_saeteuk(ws)
    )
    if error:
        return _usage(workspace, error)
    if not saeteuk_paths:
        verdict = _base_verdict(workspace)
        if directory_found:
            verdict['warn'] = [{
                'code': 'saeteuk_missing',
                'severity': 'WARN',
                'msg': (
                    'workspace _saeteuk directory has no readable .txt or .md '
                    'artifact'
                ),
                'at': '_saeteuk',
            }]
            verdict['counts'] = {'hard': 0, 'warn': 1}
            verdict['note'] = 'saeteuk directory exists but no artifact was checked'
        else:
            verdict['note'] = (
                'no workspace-local saeteuk directory found; '
                'consistency check is a no-op'
            )
        if discovery_notes:
            verdict['notes'] = discovery_notes
        return verdict, 0

    try:
        workspace_root = ws.resolve(strict=True)
        body_path = (ws / 'bundle' / 'content.md').resolve(strict=True)
    except FileNotFoundError:
        return _usage(workspace, 'bundle/content.md not found')
    except OSError as exc:
        return _usage(workspace, f'bundle/content.md unreadable: {exc}')
    if not _contained(workspace_root, body_path):
        return _usage(workspace, 'bundle/content.md escapes the workspace')

    try:
        body = body_path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        return _usage(workspace, f'bundle/content.md unreadable: {exc}')

    saeteuk_numbers = []
    saeteuk_entities = []
    saeteuk_files = []
    try:
        for path in saeteuk_paths:
            display = _display_path(ws, path)
            text = path.read_text(encoding='utf-8')
            saeteuk_files.append(display)
            saeteuk_numbers.extend(_number_claims(text, display))
            for entity in extract_entities(text):
                saeteuk_entities.append({**entity, 'source': display})
    except (OSError, UnicodeError) as exc:
        return _usage(workspace, f'saeteuk artifact unreadable: {exc}')

    body_numbers = _number_claims(body, 'bundle/content.md')
    saeteuk_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    body_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for claim in saeteuk_numbers:
        key = _context_key(claim)
        if key:
            saeteuk_by_key[key].append(claim)
    for claim in body_numbers:
        key = _context_key(claim)
        if key:
            body_by_key[key].append(claim)

    hard = []
    warn = []
    evaluated_keys = set()
    for key in sorted(saeteuk_by_key):
        saeteuk_claims = saeteuk_by_key[key]
        body_claims = body_by_key.get(key, [])
        saeteuk_values = sorted({
            claim['canonical_value'] for claim in saeteuk_claims
        })
        body_values = sorted({
            claim['canonical_value'] for claim in body_claims
        })
        ambiguous_sides = []
        if len(saeteuk_values) > 1:
            ambiguous_sides.append('saeteuk')
        if len(body_values) > 1:
            ambiguous_sides.append('body')
        if ambiguous_sides:
            claim = saeteuk_claims[0]
            warn.append({
                'code': 'saeteuk_ambiguous',
                'severity': 'WARN',
                'kind': 'number',
                'msg': 'subject/unit key has multiple distinct numeric values',
                'at': claim['source'],
                'line': claim['line'],
                'subject': claim['subject'],
                'unit': claim['unit_raw'],
                'ambiguous_sides': ambiguous_sides,
                'saeteuk_values': saeteuk_values,
                'body_values': body_values,
            })
            evaluated_keys.add(key)
            continue
        if len(saeteuk_values) != 1 or len(body_values) != 1:
            continue

        evaluated_keys.add(key)
        claim = saeteuk_claims[0]
        body_claim = body_claims[0]
        if _compatible(claim, body_claim, float(tolerance)):
            continue
        scale = max(
            abs(claim['canonical_value']),
            abs(body_claim['canonical_value']),
        )
        relative = (
            0.0 if scale == 0.0
            else abs(
                claim['canonical_value'] - body_claim['canonical_value']
            ) / scale
        )
        generic_subject = claim['subject'] in GENERIC_QUANTITY_SUBJECTS
        finding = {
            'code': (
                'saeteuk_possible_contradiction'
                if generic_subject
                else 'saeteuk_number_contradiction'
            ),
            'severity': 'WARN' if generic_subject else 'HARD',
            'msg': (
                'bare quantity-word subject may refer to different objects'
                if generic_subject
                else (
                    'single distinct same-subject same-unit numeric values '
                    'contradict'
                )
            ),
            'at': claim['source'],
            'line': claim['line'],
            'subject': claim['subject'],
            'unit': claim['unit_raw'],
            'saeteuk_value': claim['value'],
            'body_value': body_claim['value'],
            'body_line': body_claim['line'],
            'relative_difference': round(relative, 6),
        }
        (warn if generic_subject else hard).append(finding)

    for claim in saeteuk_numbers:
        key = _context_key(claim)
        if key in evaluated_keys:
            continue
        fallback_match = (
            claim['subject'] is None
            and claim['unit'] is not None
            and any(
                item['subject'] is None
                and claim['unit'] == item['unit']
                and _compatible(claim, item, float(tolerance))
                for item in body_numbers
            )
        )
        if fallback_match:
            continue
        warn.append({
            'code': 'saeteuk_unsupported',
            'severity': 'WARN',
            'kind': 'number',
            'msg': 'saeteuk numeric claim has no supporting body mention',
            'at': claim['source'],
            'line': claim['line'],
            'claim': claim['raw'],
            'subject': claim['subject'],
            'unit': claim['unit_raw'],
        })

    compact_body = _compact(body)
    warned_entities = set()
    for entity in saeteuk_entities:
        normalized = entity['normalized']
        if normalized in compact_body or normalized in warned_entities:
            continue
        warned_entities.add(normalized)
        warn.append({
            'code': 'saeteuk_unsupported',
            'severity': 'WARN',
            'kind': 'entity',
            'msg': 'saeteuk named entity has no supporting body mention',
            'at': entity['source'],
            'line': entity['line'],
            'claim': entity['entity'],
        })

    verdict = _base_verdict(workspace)
    verdict['saeteuk_files'] = saeteuk_files
    verdict['rounding_relative_tolerance'] = float(tolerance)
    verdict['checked_numbers'] = len(saeteuk_numbers)
    verdict['checked_entities'] = len(saeteuk_entities)
    verdict['hard'] = hard
    verdict['warn'] = warn
    verdict['counts'] = {'hard': len(hard), 'warn': len(warn)}
    verdict['ok'] = not hard
    verdict['verdict'] = 'pass' if not hard else 'fail'
    if discovery_notes:
        verdict['notes'] = discovery_notes
    return verdict, (0 if not hard else 3)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description='check saeteuk numeric and named-entity consistency with report body'
    )
    parser.add_argument('workspace', help='report workspace directory')
    parser.add_argument(
        '--tolerance',
        type=float,
        default=ROUNDING_RELATIVE_TOLERANCE,
        help='relative rounding tolerance (default: 0.01)',
    )
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace, tolerance=args.tolerance)
    print(json.dumps(
        verdict, ensure_ascii=False, indent=2, allow_nan=False
    ))
    return code


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


if __name__ == '__main__':
    raise SystemExit(main())
