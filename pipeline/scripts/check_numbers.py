# -*- coding: utf-8 -*-
"""Check body numerals against simulation results and optional RNG provenance.

The checker is intentionally conservative: after removing ``[[...]]`` build
tags, it considers only decimal tokens with at least two significant digits or
tokens followed by a clear unit. Years, citations, figure/table indices, and
page/section references are ignored. Numeric values are collected recursively
from ``sim/results.json`` (with ``results.json`` as a compatibility fallback).

Exit 0 = pass (WARN findings are advisory), 3 = HARD finding, 2 = usage/input
error. Unmatched body numerals are WARN-only because broad recursive result
matching and prose heuristics are not precise enough to block a valid report.
``--require-seed`` keeps invalid seed values HARD; a missing seed is HARD only
for canonical ``sim/results.json`` containing other numeric results and WARN in
ambiguous, empty, or legacy cases.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path


RESULT_PATHS = (Path("sim/results.json"), Path("results.json"))
PROVENANCE_PATHS = (
    Path("sim/provenance.json"),
    Path("sim/provenance"),
)

NUMBER_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)"
    r"(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])"
)
UNIT_RE = re.compile(
    r"^\s*(?:%|\u2030|\u00b0\s*[CFK]?|dB|Hz|kHz|MHz|GHz|ms|\u03bcs|us|ns|s|min|h|"
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
    r"\s*(?:no\.?\s*)?$",
    re.I,
)
REFERENCE_SUFFIX_RE = re.compile(
    r"^\s*(?:\ucabd|\ud398\uc774\uc9c0|\uc808|\uc7a5)(?![A-Za-z])"
)


def find_body(md: str) -> str:
    """Return content.md with build tags removed, matching sibling checkers."""
    return re.sub(r"\[\[.*?\]\]", " ", md, flags=re.S)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def collect_numeric_values(value) -> list[float]:
    """Collect every finite JSON number recursively; booleans are not numbers."""
    found: list[float] = []
    if _is_number(value):
        found.append(float(value))
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(collect_numeric_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_numeric_values(child))
    return found


def _populated(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, str)):
        return bool(value)
    return True


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _significant_digits(raw: str) -> int:
    mantissa = re.split(r"[eE]", raw.replace(",", ""))[0].lstrip("+-")
    digits = mantissa.replace(".", "").lstrip("0")
    return len(digits)


def _is_ignored_context(body: str, start: int, end: int, raw: str, value: float) -> bool:
    before = body[max(0, start - 48):start]
    after = body[end:end + 24]

    # Four-digit years are metadata/citation context, not simulation claims.
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

    # Markdown headings/list labels are structural indices ("## 3. ...", "1. ...").
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
    """Return conservative body-number candidates not covered by the allowlist."""
    allowed = {float(v) for v in (allowed_numbers or set()) if _is_number(v)}
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


def load_allowlist(path) -> set[float]:
    """Load exact numeric exemptions from JSON or one-number-per-line text."""
    if not path:
        return set()
    source = Path(path)
    raw = source.read_text(encoding="utf-8")
    values = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        values = parsed
    elif isinstance(parsed, dict):
        for key in ("numbers", "values", "allow"):
            if isinstance(parsed.get(key), list):
                values = parsed[key]
                break
    else:
        for line in raw.splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if line:
                values.append(line.strip("\"'"))

    allowed = set()
    for item in values:
        if isinstance(item, bool):
            continue
        try:
            value = float(str(item).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            allowed.add(value)
    return allowed


def _environment_allowlist_path() -> Path | None:
    """Resolve a numeric allowlist from a valid operator profile root."""
    configured = os.environ.get("RIGORLOOM_PROFILE_ROOT")
    if not configured:
        return None
    root = Path(configured).expanduser()
    if not root.is_dir():
        return None
    candidates = (
        root / "packs" / "numeral_allowlist.txt",
        root / "packs" / "numeral_allowlist.json",
        root / "packs" / "number_allowlist.txt",
        root / "packs" / "number_allowlist.json",
        root / "numeral_allowlist.txt",
        root / "number_allowlist.txt",
    )
    return next((path for path in candidates if path.is_file()), None)


def _usage(ws, message):
    return {
        "ok": False,
        "workspace": str(ws),
        "checker": "check_numbers",
        "error": message,
        "hard": [],
        "warn": [],
        "counts": {"hard": 0, "warn": 0},
        "verdict": "usage_error",
    }, 2


def _find_existing(ws: Path, candidates) -> Path | None:
    for relative in candidates:
        path = ws / relative
        if path.is_file():
            return path
    return None


def _relative_match(body_value: float, result_value: float, tolerance: float) -> bool:
    return body_value == result_value or math.isclose(
        body_value, result_value, rel_tol=tolerance, abs_tol=0.0
    )


def check(ws, tolerance=1e-3, allowed_numbers=None, require_seed=False):
    workspace = Path(ws)
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        return _usage(ws, "tolerance must be a finite non-negative number")

    content_path = workspace / "bundle" / "content.md"
    try:
        md = content_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return _usage(ws, "bundle/content.md not found")

    results_path = _find_existing(workspace, RESULT_PATHS)
    results = None
    if results_path:
        results, error = _read_json(results_path)
        if error:
            return _usage(ws, f"invalid results JSON: {error}")

    provenance_items = []
    for relative in PROVENANCE_PATHS:
        path = workspace / relative
        if not path.is_file():
            continue
        payload, error = _read_json(path)
        if error:
            return _usage(ws, f"invalid sim provenance JSON: {error}")
        provenance_items.append(payload)

    hard, warn = [], []
    result_values = collect_numeric_values(results)
    candidates = extract_body_numerals(find_body(md), allowed_numbers=allowed_numbers)
    for candidate in candidates:
        value = candidate["value"]
        if not any(_relative_match(value, result, float(tolerance)) for result in result_values):
            warn.append({
                "code": "unbacked_numeral",
                "msg": "body numeral has no matching numeric value in results.json",
                "at": candidate["raw"],
                "line": candidate["line"],
            })

    if results_path is None:
        warn.append({
            "code": "results_not_recorded_legacy",
            "msg": "results.json not found; legacy workspace compatibility path",
        })

    if require_seed:
        payloads = [results, *provenance_items]
        # The RNG seed is authoritative ONLY at the top level of results.json or a
        # provenance payload. A "seed"-named field nested inside some sub-object is
        # not treated as the run seed (flagging it would false-positive on unrelated
        # metadata). See stage-4.5.md.
        top_level_seeds = [
            value
            for payload in payloads
            if isinstance(payload, dict)
            for key, value in payload.items()
            if str(key).casefold() == "seed"
        ]
        invalid_seed = {
            "code": "invalid_seed",
            "msg": "top-level seed field must contain a finite JSON number",
        }
        if top_level_seeds:
            if all(_is_number(seed) for seed in top_level_seeds):
                pass  # a numeric top-level RNG seed is recorded
            else:
                hard.append(invalid_seed)  # explicit non-numeric top-level seed
        elif _populated(results):
            missing_seed = {
                "code": "missing_seed",
                "msg": "populated results.json does not record a numeric RNG seed",
            }
            canonical_results = workspace / RESULT_PATHS[0]
            clearly_fresh = (
                results_path is not None
                and results_path.resolve() == canonical_results.resolve()
                and bool(result_values)
            )
            (hard if clearly_fresh else warn).append(missing_seed)
        else:
            warn.append({
                "code": "seed_not_recorded_legacy",
                "msg": "numeric seed not found in legacy/empty simulation artifacts",
            })

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "checker": "check_numbers",
        "results_file": (
            results_path.relative_to(workspace).as_posix() if results_path else None
        ),
        "tolerance": float(tolerance),
        "seed_required": bool(require_seed),
        "checked_numerals": len(candidates),
        "result_numeric_values": len(result_values),
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, (0 if not hard else 3)


def _emit(verdict, code, out=None):
    rendered = json.dumps(
        verdict, ensure_ascii=False, indent=2, allow_nan=False
    )
    if out:
        Path(out).write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


def main():
    parser = argparse.ArgumentParser(
        description="check report body numerals against simulation results"
    )
    parser.add_argument("workspace", help="report workspace directory")
    parser.add_argument(
        "--tolerance", type=float, default=1e-3,
        help="relative numeric-match tolerance (default: 1e-3)",
    )
    parser.add_argument(
        "--allow", default=None,
        help=("optional exact-number allowlist (JSON list/object or one per line); "
              "defaults to the allowlist under a valid RIGORLOOM_PROFILE_ROOT"),
    )
    parser.add_argument(
        "--require-seed", action="store_true",
        help="require a numeric seed for populated simulation results",
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    args = parser.parse_args()

    try:
        allow_path = args.allow if args.allow is not None else _environment_allowlist_path()
        allowed = load_allowlist(allow_path)
    except OSError as exc:
        verdict, code = _usage(args.workspace, f"allowlist unreadable: {exc}")
        raise SystemExit(_emit(verdict, code, args.out))

    verdict, code = check(
        args.workspace,
        tolerance=args.tolerance,
        allowed_numbers=allowed,
        require_seed=args.require_seed,
    )
    raise SystemExit(_emit(verdict, code, args.out))


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    main()
