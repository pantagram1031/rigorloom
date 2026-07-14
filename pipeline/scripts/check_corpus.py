# -*- coding: utf-8 -*-
"""Advisory cross-report consistency and prose-reuse checker.

The optional corpus root is a local, private directory for one student's
reports. Its immediate child directories are prior report workspaces containing
``bundle/content.md`` plus a matching ``student_id`` or ``student_name`` in
``build.yaml`` or ``request.yaml``. This checker only reads that corpus and
writes nothing to it or to the current workspace.

Exit 0 = completed, including WARN findings or an optional-root skip.
Exit 2 = usage/input error. Exit 3 is reserved for checker-family compatibility,
but this advisory checker has no HARD rules and never emits it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from difflib import SequenceMatcher
import json
import math
import os
from pathlib import Path
import re
import sys


TAG_RE = re.compile(r"\[\[.*?\]\]", re.S)
TOKEN_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
NAME_WORD = r"[A-Za-z가-힣Α-Ωα-ω][A-Za-z0-9가-힣Α-Ωα-ω_/-]*"
NAME = rf"(?P<name>{NAME_WORD}(?:[ \t]+{NAME_WORD}){{0,3}})"
UNIT = (
    r"(?P<unit>[%‰]|°\s*[CFK]?|"
    r"[A-Za-zµμΩ가-힣][A-Za-z0-9µμΩ가-힣°%./*^·-]{0,15})"
)
LINE_PREFIX = r"^\s*(?:[-*+]\s+)?"
EQUALS_BINDING_RE = re.compile(
    rf"{LINE_PREFIX}{NAME}\s*=\s*(?P<number>{NUMBER})"
    rf"(?:\s*{UNIT})?\s*[.;,。]?\s*$"
)
KOREAN_BINDING_RE = re.compile(
    rf"{LINE_PREFIX}{NAME}\s*(?:은|는)\s*(?P<number>{NUMBER})"
    rf"\s*{UNIT}\s*[.;,。]?\s*$"
)
CAREER_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:"
    r"(?:희망\s*)?진로\s*(?:은|는|[:：=])"
    r"|career(?:\s+track)?\s*[:=]"
    r")\s*(?P<track>[^\n]{2,80}?)\s*$",
    re.I,
)

SHINGLE_SIZE = 8
MIN_REUSED_TOKENS = 12
MIN_PROSE_LINE_TOKENS = 6
JACCARD_THRESHOLD = 0.35
MIN_SHARED_SHINGLES = 4
CONFLICT_RELATIVE_DIFFERENCE = 0.01
MAX_SNIPPET_TOKENS = 20
IDENTITY_KEYS = ("student_id", "student_name")
UNKNOWN_IDENTITY_VALUES = frozenset({"", "null", "none", "todo", "tbd", "~"})


def _usage(workspace, message):
    return {
        "ok": False,
        "workspace": str(workspace),
        "checker": "check_corpus",
        "error": message,
        "hard": [],
        "warn": [],
        "counts": {"hard": 0, "warn": 0, "prior_workspaces": 0},
        "verdict": "usage_error",
    }, 2


def _base_verdict(workspace) -> dict:
    return {
        "ok": True,
        "workspace": str(workspace),
        "checker": "check_corpus",
        "hard": [],
        "warn": [],
        "counts": {"hard": 0, "warn": 0, "prior_workspaces": 0},
        "verdict": "pass",
    }


def _without_tags(markdown: str) -> str:
    return TAG_RE.sub(
        lambda match: re.sub(r"[^\r\n]", " ", match.group(0)),
        markdown,
    )


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _yaml_scalar(value: str) -> str:
    """Return a small top-level YAML scalar without interpreting escapes."""
    value = value.strip()
    if len(value) >= 2 and value[0] in (chr(34), chr(39)) and value[-1] == value[0]:
        return value[1:-1].strip()
    return value.split(" #", 1)[0].strip()


def _student_identity(workspace: Path) -> tuple[str, str] | None:
    """Return one stable recorded identity, preferring student_id over name."""
    found: dict[str, set[str]] = {key: set() for key in IDENTITY_KEYS}
    pattern = re.compile(r"^(student_id|student_name)\s*:\s*(.*?)\s*$", re.I)
    for filename in ("build.yaml", "request.yaml"):
        try:
            text = (workspace / filename).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeError):
            continue
        for line in text.splitlines():
            if not line or line[0].isspace():
                continue
            match = pattern.match(line)
            if match is None:
                continue
            key = match.group(1).casefold()
            value = _normalize_name(_yaml_scalar(match.group(2)))
            if value not in UNKNOWN_IDENTITY_VALUES:
                found[key].add(value)
    for key in IDENTITY_KEYS:
        if len(found[key]) == 1:
            return key, next(iter(found[key]))
        if len(found[key]) > 1:
            return None
    return None


def _contained(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except (OSError, ValueError):
        return False


def _normalize_unit(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").casefold())


def _parse_number(value: str) -> float | None:
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def extract_bindings(markdown: str) -> dict[str, list[dict]]:
    """Extract only explicit, line-level identifier/value declarations."""
    bindings: dict[str, list[dict]] = defaultdict(list)
    for line_number, line in enumerate(_without_tags(markdown).splitlines(), start=1):
        match = EQUALS_BINDING_RE.match(line) or KOREAN_BINDING_RE.match(line)
        if match is None:
            continue
        number = _parse_number(match.group("number"))
        if number is None:
            continue
        raw_name = match.group("name").strip()
        bindings[_normalize_name(raw_name)].append({
            "name": raw_name,
            "value": number,
            "raw_value": match.group("number"),
            "unit": _normalize_unit(match.groupdict().get("unit")),
            "line": line_number,
        })
    return dict(bindings)


def extract_career_track(markdown: str) -> dict | None:
    """Return the first explicit career declaration, if one is present."""
    for line_number, line in enumerate(_without_tags(markdown).splitlines(), start=1):
        match = CAREER_RE.match(line)
        if match is None:
            continue
        track = match.group("track").strip().rstrip(".;,。")
        normalized = " ".join(track.casefold().split())
        if normalized:
            return {"track": track, "normalized": normalized, "line": line_number}
    return None


def _materially_different(left: float, right: float) -> tuple[bool, float]:
    scale = max(abs(left), abs(right))
    difference = abs(left - right)
    relative = 0.0 if scale == 0.0 else difference / scale
    return relative > CONFLICT_RELATIVE_DIFFERENCE, relative


def _constant_findings(current: dict, prior: dict, source: str) -> list[dict]:
    findings = []
    for identifier in sorted(set(current) & set(prior)):
        candidates = []
        for current_item in current[identifier]:
            for prior_item in prior[identifier]:
                # Comparing different or missing-vs-present units would create
                # conversion and context false positives. Equals-only bindings
                # remain comparable when both omit a unit.
                if current_item["unit"] != prior_item["unit"]:
                    continue
                differs, relative = _materially_different(
                    current_item["value"], prior_item["value"]
                )
                if differs:
                    candidates.append((relative, current_item, prior_item))
        if not candidates:
            continue
        relative, current_item, prior_item = max(
            candidates,
            key=lambda item: (
                item[0], item[1]["value"], item[2]["value"],
                item[1]["line"], item[2]["line"],
            ),
        )
        findings.append({
            "code": "cross_report_constant_conflict",
            "severity": "WARN",
            "msg": "named numeric constant differs from a prior report",
            "source_workspace": source,
            "identifier": current_item["name"],
            "current_value": current_item["value"],
            "prior_value": prior_item["value"],
            "unit": current_item["unit"] or None,
            "relative_difference": round(relative, 6),
            "line": current_item["line"],
        })
    return findings


def _career_finding(current: dict | None, prior: dict | None, source: str) -> dict | None:
    if current is None or prior is None:
        return None
    if current["normalized"] == prior["normalized"]:
        return None
    return {
        "code": "career_track_conflict",
        "severity": "WARN",
        "msg": "declared career track differs from a prior report",
        "source_workspace": source,
        "current_track": current["track"],
        "prior_track": prior["track"],
        "line": current["line"],
    }


def _prose_tokens(markdown: str) -> tuple[list[str], list[str]]:
    display: list[str] = []
    normalized: list[str] = []
    for line in _without_tags(markdown).splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^#{1,6}(?:\s|$)", stripped):
            continue
        if stripped.startswith("|") or re.fullmatch(r"[-=_*\s]+", stripped):
            continue
        line_tokens = TOKEN_RE.findall(stripped)
        if len(line_tokens) < MIN_PROSE_LINE_TOKENS:
            continue
        display.extend(line_tokens)
        normalized.extend(token.casefold() for token in line_tokens)
    return display, normalized


def _shingles(tokens: list[str]) -> set[tuple[str, ...]]:
    if len(tokens) < SHINGLE_SIZE:
        return set()
    return {
        tuple(tokens[index:index + SHINGLE_SIZE])
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    }


def _reuse_finding(current_markdown: str, prior_markdown: str, source: str) -> dict | None:
    current_display, current_tokens = _prose_tokens(current_markdown)
    _, prior_tokens = _prose_tokens(prior_markdown)
    if len(current_tokens) < SHINGLE_SIZE or len(prior_tokens) < SHINGLE_SIZE:
        return None

    match = SequenceMatcher(
        None, current_tokens, prior_tokens, autojunk=False
    ).find_longest_match(0, len(current_tokens), 0, len(prior_tokens))
    current_shingles = _shingles(current_tokens)
    prior_shingles = _shingles(prior_tokens)
    shared = current_shingles & prior_shingles
    union = current_shingles | prior_shingles
    jaccard = len(shared) / len(union) if union else 0.0
    is_reused = match.size >= MIN_REUSED_TOKENS or (
        len(shared) >= MIN_SHARED_SHINGLES and jaccard >= JACCARD_THRESHOLD
    )
    if not is_reused:
        return None

    snippet_size = min(max(match.size, SHINGLE_SIZE), MAX_SNIPPET_TOKENS)
    snippet = " ".join(current_display[match.a:match.a + snippet_size])
    return {
        "code": "reused_passage",
        "severity": "WARN",
        "msg": "substantial prose overlap with a prior report",
        "source_workspace": source,
        "snippet": snippet,
        "consecutive_shared_tokens": match.size,
        "shingle_jaccard": round(jaccard, 6),
    }


def _read_content(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, "bundle/content.md not found"
    except (OSError, UnicodeError) as exc:
        return None, f"bundle/content.md unreadable: {exc}"


def check(workspace, corpus_root=None):
    workspace = Path(workspace)
    current_path = workspace / "bundle" / "content.md"
    current_markdown, error = _read_content(current_path)
    if error:
        return _usage(workspace, error)

    configured_root = corpus_root
    if configured_root is None:
        configured_root = os.environ.get("RIGORLOOM_CORPUS_ROOT")
    if not configured_root:
        verdict = _base_verdict(workspace)
        verdict["verdict"] = "skipped"
        verdict["note"] = "optional corpus check skipped: no corpus root configured"
        return verdict, 0

    root = Path(configured_root).expanduser()
    if not root.exists():
        verdict = _base_verdict(workspace)
        verdict["verdict"] = "skipped"
        verdict["note"] = "optional corpus check skipped: configured corpus root not found"
        return verdict, 0
    if not root.is_dir():
        return _usage(workspace, "corpus root is not a directory")

    current_identity = _student_identity(workspace)
    if current_identity is None:
        verdict = _base_verdict(workspace)
        verdict["warn"] = [{
            "code": "corpus_identity_unknown",
            "severity": "WARN",
            "msg": (
                "current workspace has no unambiguous top-level student_id or "
                "student_name in build.yaml/request.yaml; corpus comparison skipped"
            ),
            "at": "build.yaml or request.yaml",
        }]
        verdict["counts"]["warn"] = 1
        return verdict, 0

    try:
        root_resolved = root.resolve(strict=True)
        candidates = []
        for child in root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            child_resolved = child.resolve(strict=True)
            if not _contained(root_resolved, child_resolved):
                continue
            prior_path = child_resolved / "bundle" / "content.md"
            if not prior_path.is_file():
                continue
            prior_resolved = prior_path.resolve(strict=True)
            if not _contained(child_resolved, prior_resolved):
                continue
            candidates.append((child.name, child_resolved, prior_resolved))
        candidates.sort(key=lambda item: (item[0].casefold(), item[0]))
    except OSError as exc:
        return _usage(workspace, f"corpus root unreadable: {exc}")

    current_resolved = current_path.resolve(strict=False)
    current_bindings = extract_bindings(current_markdown)
    current_career = extract_career_track(current_markdown)
    warn = []
    notes = []
    scanned = 0
    for source_name, prior_workspace, prior_path in candidates:
        if prior_path == current_resolved:
            continue
        if _student_identity(prior_workspace) != current_identity:
            continue
        prior_markdown, prior_error = _read_content(prior_path)
        if prior_error:
            notes.append({
                "source_workspace": source_name,
                "note": "prior content could not be read and was skipped",
            })
            continue
        scanned += 1
        warn.extend(_constant_findings(
            current_bindings,
            extract_bindings(prior_markdown),
            source_name,
        ))
        career = _career_finding(
            current_career,
            extract_career_track(prior_markdown),
            source_name,
        )
        if career:
            warn.append(career)
        reused = _reuse_finding(current_markdown, prior_markdown, source_name)
        if reused:
            warn.append(reused)

    verdict = _base_verdict(workspace)
    verdict["warn"] = warn
    verdict["counts"] = {
        "hard": 0,
        "warn": len(warn),
        "prior_workspaces": scanned,
    }
    if notes:
        verdict["notes"] = notes
    return verdict, 0


def main():
    parser = argparse.ArgumentParser(
        description="advisory cross-report consistency and prose-reuse check"
    )
    parser.add_argument("workspace", help="current report workspace directory")
    parser.add_argument(
        "--corpus-root",
        default=None,
        help="local private prior-workspace directory (or RIGORLOOM_CORPUS_ROOT)",
    )
    args = parser.parse_args()
    verdict, code = check(args.workspace, args.corpus_root)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    main()
