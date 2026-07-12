#!/usr/bin/env python3
"""Privacy gate scan for a public repo.

Walks a directory tree and flags content that must never ship in a public
repo: binary office documents, denylisted strings, Windows user-profile
paths, email addresses, and (as a heuristic warning) Korean student-record
look-alikes. Stdlib only.

CLI:
    privacy_scan.py <root> [--denylist <path>] [--json]

Exit codes:
    0  clean (or WARN-only findings)
    2  usage error (bad args, bad root/denylist path, denylist inside root)
    3  at least one HARD finding
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

BINARY_EXTS = {
    ".hwp", ".hwpx", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}
EXCLUDED_DIRS = {".git", "__pycache__", "node_modules"}
USER_PATH_EXCEPTIONS = {"<user>", "username", "%userprofile%", "example"}
LARGE_FILE_BYTES = 1024 * 1024
SNIPPET_LIMIT = 60
PROXIMITY_WINDOW = 12

RE_USER_PATH = re.compile(r'C:\\Users\\([^\\/\s"\']+)')
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_DIGIT5 = re.compile(r"(?<!\d)\d{5}(?!\d)")
RE_HANGUL = re.compile(r"(?<![가-힣])[가-힣]{2,4}(?![가-힣])")

_ASCII_UPPER = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _ascii_lower(s: str) -> str:
    """Lowercase only ASCII letters; every other codepoint passes through
    unchanged. Preserves string length so match spans stay valid, unlike
    str.lower()/casefold() which can expand a handful of Unicode codepoints.
    """
    return "".join(c.lower() if c in _ASCII_UPPER else c for c in s)


def _snippet(s: str, limit: int = SNIPPET_LIMIT) -> str:
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= limit else s[:limit]


def _finding(file: str, line: int | None, rule: str, severity: str, snippet: str) -> dict:
    return {"file": file, "line": line, "rule": rule, "severity": severity, "snippet": _snippet(snippet)}


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    if a[1] <= b[0]:
        return b[0] - a[1]
    if b[1] <= a[0]:
        return a[0] - b[1]
    return 0


def load_denylist(path: Path) -> list[tuple[str, str]]:
    data = path.read_bytes()
    text = None
    for enc in ("utf-8", "cp949"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise ValueError(f"cannot decode denylist file as utf-8 or cp949: {path}")

    terms = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        term = unicodedata.normalize("NFC", line)
        terms.append((term, _ascii_lower(term)))
    return terms


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _email_is_exempt(local: str, domain: str) -> bool:
    local_l = local.lower()
    domain_l = domain.lower()
    if local_l.startswith("noreply"):
        return True
    if domain_l.endswith("users.noreply.github.com"):
        return True
    if domain_l == "example.com" or domain_l.endswith(".example.com"):
        return True
    if domain_l == "invalid" or domain_l.endswith(".invalid"):
        return True
    return False


def _scan_dir_name(root: Path, dirpath: Path, denylist_terms: list[tuple[str, str]] | None) -> list[dict]:
    if not denylist_terms:
        return []
    rel = dirpath.relative_to(root).as_posix()
    name = unicodedata.normalize("NFC", dirpath.name)
    name_lower = _ascii_lower(name)
    for _term, term_lower in denylist_terms:
        if term_lower in name_lower:
            return [_finding(rel, None, "denylist_name", "HARD", name)]
    return []


def _scan_file(root: Path, path: Path, denylist_terms: list[tuple[str, str]] | None) -> list[dict]:
    findings: list[dict] = []
    rel = path.relative_to(root).as_posix()
    name = unicodedata.normalize("NFC", path.name)
    suffix = Path(name).suffix.lower()

    if suffix in BINARY_EXTS:
        findings.append(_finding(rel, None, "binary_document_ext", "HARD", name))

    if denylist_terms:
        name_lower = _ascii_lower(name)
        for _term, term_lower in denylist_terms:
            if term_lower in name_lower:
                findings.append(_finding(rel, None, "denylist_name", "HARD", name))
                break

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > LARGE_FILE_BYTES:
        # Flagged for manual review; regex content scanning on huge single-line
        # blobs is quadratic, so only the name/extension checks apply here.
        findings.append(_finding(rel, None, "large_file", "WARN", f"{size} bytes"))
        return findings

    text = _read_text(path)
    if text is None:
        return findings  # undecodable binary blob: only name/extension/size checks apply

    text = unicodedata.normalize("NFC", text)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if denylist_terms:
            line_lower = _ascii_lower(line)
            for _term, term_lower in denylist_terms:
                if term_lower in line_lower:
                    findings.append(_finding(rel, lineno, "denylist_content", "HARD", line))

        for m in RE_USER_PATH.finditer(line):
            seg = m.group(1)
            if seg.lower() in USER_PATH_EXCEPTIONS:
                continue
            findings.append(_finding(rel, lineno, "user_profile_path", "HARD", m.group(0)))

        for m in RE_EMAIL.finditer(line):
            local, _, domain = m.group(0).partition("@")
            if _email_is_exempt(local, domain):
                continue
            findings.append(_finding(rel, lineno, "email_address", "HARD", m.group(0)))

        digit_spans = [m.span() for m in RE_DIGIT5.finditer(line)]
        hangul_spans = [m.span() for m in RE_HANGUL.finditer(line)]
        if digit_spans and hangul_spans:
            seen = set()
            for ds in digit_spans:
                for hs in hangul_spans:
                    if _gap(ds, hs) > PROXIMITY_WINDOW:
                        continue
                    key = (ds, hs)
                    if key in seen:
                        continue
                    seen.add(key)
                    lo, hi = min(ds[0], hs[0]), max(ds[1], hs[1])
                    findings.append(
                        _finding(rel, lineno, "korean_student_id_proximity", "WARN", line[lo:hi])
                    )
    return findings


def scan_tree(root: Path, denylist_terms: list[tuple[str, str]] | None) -> list[dict]:
    findings: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if unicodedata.normalize("NFC", d) not in EXCLUDED_DIRS
        )
        filenames = sorted(filenames)

        dp = Path(dirpath)
        if dp != root:
            findings.extend(_scan_dir_name(root, dp, denylist_terms))

        for fname in filenames:
            findings.extend(_scan_file(root, dp / fname, denylist_terms))
    return findings


def _print_report(root: Path, findings: list[dict], as_json: bool) -> None:
    hard = [f for f in findings if f["severity"] == "HARD"]
    warn = [f for f in findings if f["severity"] == "WARN"]

    if as_json:
        payload = {
            "root": str(root),
            "findings": findings,
            "summary": {"hard": len(hard), "warn": len(warn), "total": len(findings)},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if not findings:
        print(f"privacy_scan: clean -- no findings under {root}")
    else:
        for f in findings:
            line = f["line"] if f["line"] is not None else "-"
            print(f"{f['file']}:{line} [{f['severity']}] ({f['rule']}) {f['snippet']}")
    print(f"summary: HARD={len(hard)} WARN={len(warn)} TOTAL={len(findings)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privacy_scan.py", description="Privacy gate scan for a public repo."
    )
    parser.add_argument("root", help="Root directory to scan")
    parser.add_argument(
        "--denylist", help="Path to a denylist file (one literal string per line, # comments allowed)"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        print(f"error: root path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2
    root = root.resolve()

    denylist_terms = None
    if args.denylist:
        denylist_path = Path(args.denylist)
        if not denylist_path.exists() or not denylist_path.is_file():
            print(f"error: denylist file not found: {denylist_path}", file=sys.stderr)
            return 2

        denylist_resolved = denylist_path.resolve()
        try:
            denylist_resolved.relative_to(root)
        except ValueError:
            pass
        else:
            print(f"error: denylist file must not be inside scan root: {denylist_path}", file=sys.stderr)
            return 2

        try:
            denylist_terms = load_denylist(denylist_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    findings = scan_tree(root, denylist_terms)
    _print_report(root, findings, args.json)

    hard_count = sum(1 for f in findings if f["severity"] == "HARD")
    return 3 if hard_count else 0


if __name__ == "__main__":
    sys.exit(main())
