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
An otherwise unmatched numeral is also backed by a matching, evidenced claim
whose source ids resolve, or by a validated constants allowlist entry whose
optional unit matches.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import claim_extraction  # noqa: E402
import check_claims  # noqa: E402
import claims_ledger  # noqa: E402
import personalization_ctl  # noqa: E402
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)


RESULT_PATHS = (Path("sim/results.json"), Path("results.json"))
PROVENANCE_PATHS = (
    Path("sim/provenance.json"),
    Path("sim/provenance"),
)
DEFAULT_CONSTANTS_PACK = (
    SCRIPTS_DIR.parent
    / "references"
    / "preference_packs"
    / "defaults"
    / "constants_allowlist.json"
)

NUMBER_RE = claim_extraction.NUMBER_RE
UNIT_RE = claim_extraction.UNIT_RE
ENGLISH_COUNT_UNIT_RE = claim_extraction.ENGLISH_COUNT_UNIT_RE
find_body = claim_extraction.find_body
extract_body_numerals = claim_extraction.extract_body_numerals
_is_number = claim_extraction.is_number


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


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


def load_constants_allowlist(path=None) -> list[dict]:
    """Load and validate the unit-aware constants list or its public default."""
    source = Path(path) if path else DEFAULT_CONSTANTS_PACK
    payload, error = _read_json(source)
    if error:
        raise ValueError(f"constants allowlist unreadable: {error}")
    errors = personalization_ctl.validate_instance(
        payload,
        personalization_ctl.pack_schema("constants_allowlist"),
    )
    if errors:
        raise ValueError(
            "constants allowlist failed schema validation: "
            + "; ".join(errors)
        )
    constants = []
    for item in payload:
        value = float(item["value"])
        if not math.isfinite(value):
            raise ValueError("constants allowlist values must be finite")
        constants.append({
            "value": value,
            "unit": item.get("unit"),
            "label": item["label"],
        })
    return constants


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


def _environment_constants_path() -> Path | None:
    configured = os.environ.get("RIGORLOOM_PROFILE_ROOT")
    if not configured:
        return None
    root = Path(configured).expanduser()
    if not root.is_dir():
        return None
    path = root / "packs" / "constants_allowlist.json"
    return path if path.is_file() else None


def _usage(ws, message):
    return usage_error(str(ws), "check_numbers", message)


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


def _normalized_unit(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("²", "^2").replace("·", "*")
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    if normalized.casefold() in {"°c", "℃"}:
        return "°C"
    if normalized.casefold() in {"°f", "℉"}:
        return "°F"
    return normalized


def _candidate_unit(candidate: dict) -> str | None:
    union = candidate.get("union_unit")
    if isinstance(union, dict):
        return _normalized_unit(union.get("canonical") or union.get("raw"))
    return _normalized_unit(candidate.get("unit_raw") or candidate.get("unit"))


def _constant_matches(candidate: dict, constant: dict) -> bool:
    if candidate["value"] != constant["value"]:
        return False
    wanted_unit = _normalized_unit(constant.get("unit"))
    return wanted_unit is None or _candidate_unit(candidate) == wanted_unit


def _backed_ledger_entries(workspace: Path) -> list[dict]:
    """Return evidenced numeric claims only when every source id resolves."""
    if not (workspace / claims_ledger.LEDGER_NAME).is_file():
        return []
    try:
        ledger = claims_ledger.load_claims(workspace, validate_sources=True)
    except claims_ledger.ClaimsLedgerError:
        return []
    return [
        entry
        for entry in ledger["claims"]
        if entry["kind"] == "numeric" and entry["evidence"]
    ]


def check(
    ws,
    tolerance=1e-3,
    allowed_numbers=None,
    require_seed=False,
    constants=None,
):
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
    body = find_body(md)
    candidates, _ = claim_extraction.extract_numeric_claims(
        body,
        policy="saeteuk",
        allowed_numbers=allowed_numbers,
    )
    constant_entries = (
        load_constants_allowlist() if constants is None else list(constants)
    )
    ledger_entries = _backed_ledger_entries(workspace)
    body_lines = body.splitlines()
    constant_backed = 0
    ledger_backed = 0
    for candidate in candidates:
        value = candidate["value"]
        if any(
            _relative_match(value, result, float(tolerance))
            for result in result_values
        ):
            continue
        if any(_constant_matches(candidate, item) for item in constant_entries):
            constant_backed += 1
            continue
        line_number = candidate["line"]
        line_text = (
            body_lines[line_number - 1]
            if 1 <= line_number <= len(body_lines)
            else candidate["snippet"]
        )
        if check_claims.numeric_traced(candidate, line_text, ledger_entries):
            ledger_backed += 1
            continue
        warn.append({
            "code": "unbacked_numeral",
            "msg": (
                "body numeral has no matching result, evidenced ledger claim, "
                "or allowlisted constant"
            ),
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

    verdict = verdict_skeleton(
        str(ws),
        "check_numbers",
        hard=hard,
        warn=warn,
        extra={
            "results_file": (
                results_path.relative_to(workspace).as_posix()
                if results_path else None
            ),
            "tolerance": float(tolerance),
            "seed_required": bool(require_seed),
            "checked_numerals": len(candidates),
            "result_numeric_values": len(result_values),
            "ledger_backed_numerals": ledger_backed,
            "constant_backed_numerals": constant_backed,
            "constants_allowlist_entries": len(constant_entries),
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
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
    parser.add_argument(
        "--constants",
        default=None,
        help=(
            "unit-aware constants_allowlist.json; defaults to the operator "
            "profile pack, then the neutral public default"
        ),
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")

    def invoke(args):
        try:
            allow_path = (
                args.allow
                if args.allow is not None
                else _environment_allowlist_path()
            )
            allowed = load_allowlist(allow_path)
            constants_path = (
                args.constants
                if args.constants is not None
                else _environment_constants_path()
            )
            constants = load_constants_allowlist(constants_path)
        except (OSError, ValueError) as exc:
            return _usage(args.workspace, f"allowlist unreadable: {exc}")
        return check(
            args.workspace,
            tolerance=args.tolerance,
            allowed_numbers=allowed,
            require_seed=args.require_seed,
            constants=constants,
        )

    return cli_main(parser, invoke, argv)


if __name__ == "__main__":
    raise SystemExit(main())
