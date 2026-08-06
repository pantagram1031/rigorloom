#!/usr/bin/env python3
"""Privacy gate scan for a public repo.

Walks a directory tree and flags content that must never ship in a public
repo: binary office documents, denylisted strings, Windows user-profile
paths, email addresses, and (as a heuristic warning) Korean student-record
look-alikes. Stdlib only.

Binary documents are categorically HARD except through the sha256-pinned
corpus allowlist (``--binary-allowlist``, auto-detected at
``tests/corpus/forms/manifest.json``): a listed, hash-verified blank template
passes the extension rule but its extracted text is still content-scanned
(RRN / filled phone / email / user-path / denylist all HARD) — see the
"Corpus binary allowlist" section below.

CLI:
    privacy_scan.py <root> [--denylist <path>] [--binary-allowlist <manifest.json>] [--json]

Exit codes:
    0  clean (or WARN-only findings)
    2  usage error (bad args, bad root/denylist path, denylist inside root)
    3  at least one HARD finding
"""
from __future__ import annotations

import argparse
import codecs
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
# "me" is a generic placeholder profile name that shows up in doc examples.
USER_PATH_EXCEPTIONS = {"<user>", "username", "%userprofile%", "example", "me"}
LARGE_FILE_BYTES = 1024 * 1024
SNIPPET_LIMIT = 60
PROXIMITY_WINDOW = 12
# Bounded regex WINDOWING (replaces the old blunt per-line truncation). A single
# logical line is scanned as overlapping [window] segments so RE_EMAIL /
# RE_USER_PATH never run on an unbounded string (they have `+` runs that
# backtrack quadratically on a pathological megabyte-long line), yet a secret
# past the first window is still caught. Overlap must exceed the longest
# realistic path/email so a match straddling a window edge appears whole in one
# segment. Findings are deduped by (rule, snippet) since the overlap is scanned
# twice.
LINE_REGEX_WINDOW = 10_000
LINE_REGEX_OVERLAP = 256
# Kept only for the digit/hangul proximity heuristic (a WARN), which stays on a
# length-capped line — it is not a hard secret detector.
LINE_REGEX_CAP = 10_000
# Streaming scan of files above LARGE_FILE_BYTES: read this much per read().
STREAM_CHUNK_BYTES = 1024 * 1024
# Minimum TEXT-domain carry (in characters) re-prepended between decoded chunks
# so a denylist term / path / email straddling a chunk boundary is still caught.
# The actual carry is max(this, 4 * longest denylist term) so even a very long
# denylist term crossing the boundary appears whole (see _scan_large_file).
STREAM_CARRY_MIN_CHARS = 4096

# --- Profile-store leak markers (v0.16 W4.1) --------------------------------
# A build/packaging staging dir must never contain personalization-store
# content. Two marker classes, both HARD:
#   profile_store_path    a staged file whose PATH sits inside a store layout
#                         (`.local/personalization/...`). Path-based, so docs
#                         that merely *mention* the store location in prose do
#                         not false-positive.
#   profile_store_content a staged .json/.jsonl document whose top-level
#                         "schema" is a personalization-store schema: store
#                         manifests (current AND legacy string), identity,
#                         writing profile/rules, layout/academic profiles,
#                         forms index/records, feedback logs, humanize voice
#                         sidecars, portability export manifests, and the
#                         extension-pack registry/receipts (pack registry ids).
# Structural (parsed JSON), not substring: source code that names these
# schema strings in string literals stays clean.
PROFILE_STORE_SCHEMAS = frozenset({
    "rigorloom/personalization-v1",
    "report-pipeline/personalization-v1",
    "rigorloom/personalization-export-v1",
    "report-pipeline/identity-v1",
    "report-pipeline/writing-profile-v1",
    "report-pipeline/writing-rules-v1",
    "report-pipeline/layout-profile-v1",
    "report-pipeline/academic-profile-v1",
    "report-pipeline/subject-profile-v1",
    "report-pipeline/forms-index-v1",
    "report-pipeline/form-record-v1",
    "report-pipeline/form-conditions-v1",
    "report-pipeline/feedback-event-v1",
    "report-pipeline/feedback-candidate-v1",
    "report-pipeline/feedback-decision-v1",
    "report-pipeline/floor-override-warning-v1",
    "report-pipeline/humanization-voice-v1",
    "rigorloom/extension-registry-v1",
    "rigorloom/extension-receipt-v1",
})
_STORE_PATH_SEGMENTS = (".local", "personalization")

RE_USER_PATH = re.compile(r'C:\\Users\\([^\\/\s"\']+)')
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_DIGIT5 = re.compile(r"(?<!\d)\d{5}(?!\d)")
RE_HANGUL = re.compile(r"(?<![가-힣])[가-힣]{2,4}(?![가-힣])")

# --- Corpus binary allowlist (W5.2 privacy ruling) ---------------------------
# A binary document may pass the categorical `binary_document_ext` rule ONLY
# when BOTH hold:
#   (a) its path is listed in a manifest given via --binary-allowlist (or the
#       auto-detected corpus manifest, see CORPUS_MANIFEST_RELPATH), AND
#   (b) its current sha256 equals the manifest-pinned hash.
# Still-catches #1: any unlisted binary anywhere, or a listed file whose hash
# drifted, is HARD exactly as before (tamper/substitution stays detected).
# Still-catches #2: an allowlisted binary is NOT exempt from content scanning —
# its text is extracted (hwpx zip parts; hwp UTF-16 run harvest) and scanned
# with the PII patterns below plus the existing email/user-path/denylist rules.
# A filled document can never hide behind the allowlist.
CORPUS_MANIFEST_RELPATH = Path("tests") / "corpus" / "forms" / "manifest.json"
# Korean resident registration number: 6-digit birth + 7-digit tail whose
# first digit is 1-4 (5-8 are foreigner codes pre-2020; kept out to limit
# false positives on arbitrary 13-digit spans — the manifest pin, not this
# net, is the primary gate).
RE_RRN = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)")
# A *filled* Korean mobile number (blank forms carry only labels/placeholders).
RE_PHONE_FILLED = re.compile(r"(?<!\d)01[016789]\s*-\s*\d{3,4}\s*-\s*\d{4}(?!\d)")
# hwpx zip members whose text is worth scanning.
_HWPX_TEXT_SUFFIXES = (".xml", ".txt", ".hpf", ".rdf")

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


def _windows(line: str, window: int = LINE_REGEX_WINDOW, overlap: int = LINE_REGEX_OVERLAP):
    """Yield overlapping segments of `line` so a bounded regex covers the whole
    line without ever running on an unbounded string. Lines <= window yield once.
    Consecutive windows overlap by `overlap` chars so a match spanning a window
    edge is still fully inside one segment."""
    n = len(line)
    if n <= window:
        yield line
        return
    step = window - overlap
    start = 0
    while start < n:
        yield line[start:start + window]
        if start + window >= n:
            break
        start += step


def _regex_line_findings(line: str) -> list[tuple[str, str]]:
    """Run the bounded user-path + email regexes over overlapping windows of one
    logical line, returning deduped (rule, matched_text) pairs (dedup absorbs the
    double scan of the overlap region). Applies the same exemptions as callers."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for seg in _windows(line):
        for m in RE_USER_PATH.finditer(seg):
            if m.group(1).lower() in USER_PATH_EXCEPTIONS:
                continue
            key = ("user_profile_path", m.group(0))
            if key not in seen:
                seen.add(key)
                out.append(key)
        for m in RE_EMAIL.finditer(seg):
            local, _, domain = m.group(0).partition("@")
            if _email_is_exempt(local, domain):
                continue
            key = ("email_address", m.group(0))
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


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


def _scan_text_segment(text: str, denylist_terms: list[tuple[str, str]] | None,
                       add) -> None:
    """Run the denylist substring check + the windowed user-path/email regexes
    over one decoded text segment, routing matches through `add(rule, snippet)`."""
    if denylist_terms:
        text_lower = _ascii_lower(text)
        for term, term_lower in denylist_terms:
            if term_lower in text_lower:
                add("denylist_content", term)
    for line in text.splitlines():
        for rule, matched in _regex_line_findings(line):
            add(rule, matched)


def _scan_large_file_pass(rel: str, path: Path,
                          denylist_terms: list[tuple[str, str]] | None,
                          decoder_factory, carry_chars: int) -> list[dict]:
    """One streaming decode+scan pass over `path` using `decoder_factory`. A
    strict incremental decoder raises UnicodeDecodeError on the first byte that
    is invalid in its codec; the caller catches that and retries with the next
    codec. Carry is TEXT-domain so a term/path/email spanning a decoded-chunk
    boundary is re-prepended whole into the next segment."""
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(rule: str, snippet: str) -> None:
        key = (rule, _snippet(snippet))
        if key in seen:
            return
        seen.add(key)
        findings.append(_finding(rel, None, rule, "HARD", snippet))

    dec = decoder_factory()
    carry = ""
    with path.open("rb") as fh:
        while True:
            block = fh.read(STREAM_CHUNK_BYTES)
            final = not block
            # strict decoders raise UnicodeDecodeError here on invalid bytes
            chunk_text = dec.decode(block, final)
            if chunk_text:
                text = unicodedata.normalize("NFC", carry + chunk_text)
                _scan_text_segment(text, denylist_terms, _add)
                carry = text[-carry_chars:] if carry_chars else ""
            if final:
                break
    return findings


def _scan_large_file(rel: str, path: Path, denylist_terms: list[tuple[str, str]] | None) -> list[dict]:
    """STREAMING content scan for files above LARGE_FILE_BYTES. Streams the file
    in bounded chunks (never a whole-file regex) with per-line WINDOWING so no
    regex runs on an unbounded string and no secret past the first window is
    missed.

    Decoding is per-file incremental with a real codec ladder (unlike the old
    utf-8 errors='ignore', which always 'succeeded' and silently mangled cp949):
    try a full strict utf-8 pass; on UnicodeDecodeError restart the file strict
    as cp949; if both fail, a final utf-8 errors='ignore' pass. Only the winning
    pass's findings count. Findings are deduped by (rule, snippet); line numbers
    are not tracked for streamed matches (reported as None)."""
    # Text-domain carry: >= 4 * longest denylist term so even a long term
    # straddling a chunk boundary appears whole in one segment (a byte-domain
    # overlap of 4096 could be shorter than the term and miss it).
    carry_chars = STREAM_CARRY_MIN_CHARS
    if denylist_terms:
        longest = max((len(term) for term, _ in denylist_terms), default=0)
        carry_chars = max(STREAM_CARRY_MIN_CHARS, 4 * longest)

    attempts = (
        lambda: codecs.getincrementaldecoder("utf-8")(errors="strict"),
        lambda: codecs.getincrementaldecoder("cp949")(errors="strict"),
        lambda: codecs.getincrementaldecoder("utf-8")(errors="ignore"),
    )
    for factory in attempts:
        try:
            return _scan_large_file_pass(rel, path, denylist_terms, factory, carry_chars)
        except UnicodeDecodeError:
            continue
        except OSError:
            return []
    return []


def _store_schema_of(payload) -> str | None:
    if isinstance(payload, dict):
        schema = payload.get("schema")
        if isinstance(schema, str) and schema in PROFILE_STORE_SCHEMAS:
            return schema
    return None


def _scan_profile_store_json(rel: str, suffix: str, text: str) -> list[dict]:
    """Structural profile-store content detection for .json/.jsonl files."""
    findings: list[dict] = []
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            return findings
        schema = _store_schema_of(payload)
        if schema:
            findings.append(_finding(
                rel, None, "profile_store_content", "HARD", schema))
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (ValueError, RecursionError):
            continue
        schema = _store_schema_of(payload)
        if schema:
            findings.append(_finding(
                rel, lineno, "profile_store_content", "HARD", schema))
    return findings


def _profile_store_path_finding(rel: str, parts: tuple[str, ...]) -> dict | None:
    for index in range(len(parts) - 1):
        if parts[index] == _STORE_PATH_SEGMENTS[0] and parts[index + 1] == _STORE_PATH_SEGMENTS[1]:
            return _finding(rel, None, "profile_store_path", "HARD", rel)
    return None


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_binary_allowlist(manifest_path: Path) -> dict[Path, str]:
    """{resolved file path: pinned sha256} from a corpus manifest.

    The manifest is the corpus index (tests/corpus/forms/manifest.json style):
    a top-level ``documents`` list whose entries carry ``path`` (relative to
    the manifest's own directory) and ``sha256``. A malformed manifest or an
    entry without both fields is a loud refusal (ValueError) — a broken
    allowlist must never silently degrade into "everything passes" or
    "nothing is listed".
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read binary allowlist manifest: {manifest_path}: {exc}")
    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list):
        raise ValueError(f"binary allowlist manifest has no documents[] list: {manifest_path}")
    base = manifest_path.resolve().parent
    allowlist: dict[Path, str] = {}
    for entry in documents:
        rel = entry.get("path") if isinstance(entry, dict) else None
        sha = entry.get("sha256") if isinstance(entry, dict) else None
        if not rel or not isinstance(sha, str) or len(sha) != 64:
            raise ValueError(
                f"binary allowlist entry needs path + 64-hex sha256: {entry!r}")
        allowlist[(base / rel).resolve()] = sha.lower()
    return allowlist


def _hwpx_text(path: Path) -> str | None:
    """Concatenated text of an hwpx (zip) package's XML/text parts, or None
    when the file is not a readable zip."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            parts = []
            for name in archive.namelist():
                if name.lower().endswith(_HWPX_TEXT_SUFFIXES):
                    parts.append(archive.read(name).decode("utf-8", "replace"))
            return "\n".join(parts)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return None


def _hwp_utf16_harvest(path: Path) -> str:
    """UTF-16LE decode of a binary .hwp (CFB) at both byte alignments.

    Stdlib-only stand-in for a CFB parser: the uncompressed streams that can
    carry text (PrvText preview, SummaryInformation author metadata) are
    stored as UTF-16LE and surface as decodable runs; compressed body text
    does not decode into anything pattern-shaped. Sector boundaries can split
    a run — this net is heuristic; the manifest sha256 pin is the primary
    gate and this scan is the filled-document backstop on top of it.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    texts = []
    for offset in (0, 1):
        texts.append(data[offset:].decode("utf-16-le", errors="ignore"))
    return "\n".join(texts)


def _scan_allowlisted_binary(rel: str, path: Path, suffix: str,
                             denylist_terms: list[tuple[str, str]] | None) -> list[dict]:
    """Content scan for a hash-verified allowlisted binary (still-catches #2).

    Extracted text runs through the PII nets (RRN, filled mobile number) plus
    the existing email/user-path regexes and the denylist. Any hit is HARD:
    the allowlist admits *blank* templates only.
    """
    findings: list[dict] = []
    if suffix == ".hwpx":
        text = _hwpx_text(path)
        if text is None:
            # Hash matched the manifest yet the package is unreadable: the
            # reviewed bytes are intact, but the content backstop cannot run.
            findings.append(_finding(
                rel, None, "binary_extract_failed", "WARN",
                "allowlisted hwpx is not a readable zip; content backstop skipped"))
            return findings
    else:
        text = _hwp_utf16_harvest(path)

    seen: set[tuple[str, str]] = set()

    def add(rule: str, snippet: str) -> None:
        key = (rule, snippet)
        if key not in seen:
            seen.add(key)
            findings.append(_finding(rel, None, rule, "HARD", snippet))

    for match in RE_RRN.finditer(text):
        add("binary_pii_rrn", match.group(0))
    for match in RE_PHONE_FILLED.finditer(text):
        add("binary_pii_phone", match.group(0))
    if denylist_terms:
        text_lower = _ascii_lower(text)
        for term, term_lower in denylist_terms:
            if term_lower in text_lower:
                add("denylist_content", term)
    for line in text.splitlines():
        for rule, matched in _regex_line_findings(line):
            add(rule, matched)
    return findings


def _scan_file(root: Path, path: Path, denylist_terms: list[tuple[str, str]] | None,
               binary_allowlist: dict[Path, str] | None = None) -> list[dict]:
    findings: list[dict] = []
    relative = path.relative_to(root)
    rel = relative.as_posix()
    name = unicodedata.normalize("NFC", path.name)
    suffix = Path(name).suffix.lower()

    store_path_finding = _profile_store_path_finding(rel, relative.parts)
    if store_path_finding:
        findings.append(store_path_finding)

    if suffix in BINARY_EXTS:
        pinned = binary_allowlist.get(path.resolve()) if binary_allowlist else None
        if pinned is None:
            # Unlisted binary anywhere: HARD exactly as before.
            findings.append(_finding(rel, None, "binary_document_ext", "HARD", name))
        elif _sha256_file(path) != pinned:
            # Listed but drifted: tamper/substitution, HARD (still-catches #1).
            findings.append(_finding(
                rel, None, "binary_allowlist_hash_mismatch", "HARD", name))
        else:
            # Listed + hash-verified: content backstop instead of a free pass.
            findings.extend(
                _scan_allowlisted_binary(rel, path, suffix, denylist_terms))

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
        # Flagged for manual review AND streamed for content: a naive full-file
        # regex on a huge single-line blob is quadratic, so we scan in bounded
        # chunks with per-line truncation instead of skipping content entirely.
        findings.append(_finding(rel, None, "large_file", "WARN", f"{size} bytes"))
        findings.extend(_scan_large_file(rel, path, denylist_terms))
        if suffix == ".jsonl":
            # A store feedback log can exceed the large-file bound; its schema
            # marker sits on every line, so a bounded head read suffices.
            try:
                head = path.open("rb").read(8 * STREAM_CHUNK_BYTES)
            except OSError:
                head = b""
            head_text = head.decode("utf-8", errors="ignore")
            head_lines = head_text.splitlines()[:-1] or [head_text]
            findings.extend(_scan_profile_store_json(
                rel, ".jsonl", "\n".join(head_lines)))
        return findings

    text = _read_text(path)
    if text is None:
        return findings  # undecodable binary blob: only name/extension/size checks apply

    text = unicodedata.normalize("NFC", text)
    if suffix in (".json", ".jsonl"):
        findings.extend(_scan_profile_store_json(rel, suffix, text))
    for lineno, full_line in enumerate(text.splitlines(), start=1):
        # denylist is a linear substring check: safe on the full (untruncated)
        # line so a term past the regex cap is still caught.
        if denylist_terms:
            line_lower = _ascii_lower(full_line)
            for _term, term_lower in denylist_terms:
                if term_lower in line_lower:
                    findings.append(_finding(rel, lineno, "denylist_content", "HARD", full_line))

        # user-path + email regexes run over overlapping WINDOWS of the full
        # line, so a secret past the first window (e.g. char 20k) is still caught
        # while no regex ever runs on an unbounded string.
        for rule, matched in _regex_line_findings(full_line):
            findings.append(_finding(rel, lineno, rule, "HARD", matched))

        # the digit/hangul proximity heuristic (a WARN, not a hard secret) stays
        # on a length-capped line.
        line = full_line[:LINE_REGEX_CAP]
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


def scan_tree(root: Path, denylist_terms: list[tuple[str, str]] | None,
              binary_allowlist: dict[Path, str] | None = None) -> list[dict]:
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
            findings.extend(_scan_file(root, dp / fname, denylist_terms,
                                       binary_allowlist))
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
    parser.add_argument(
        "--binary-allowlist",
        help="Corpus manifest.json whose sha256-pinned documents[] may pass the "
             "binary_document_ext rule (content scan still applies). When omitted, "
             "<root>/tests/corpus/forms/manifest.json is auto-detected.",
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

    binary_allowlist = None
    allowlist_path: Path | None = None
    if args.binary_allowlist:
        allowlist_path = Path(args.binary_allowlist)
        if not allowlist_path.is_file():
            print(f"error: binary allowlist manifest not found: {allowlist_path}",
                  file=sys.stderr)
            return 2
    else:
        # Auto-detect the repo corpus manifest: scanning the repo root picks
        # it up at tests/corpus/forms/manifest.json; scanning the corpus dir
        # itself picks up its own manifest.json.
        for candidate in (root / CORPUS_MANIFEST_RELPATH,
                          root / "manifest.json"
                          if root.parts[-3:] == ("tests", "corpus", "forms")
                          else None):
            if candidate is not None and candidate.is_file():
                allowlist_path = candidate
                break
    if allowlist_path is not None:
        try:
            binary_allowlist = load_binary_allowlist(allowlist_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"binary allowlist: {allowlist_path} "
              f"({len(binary_allowlist)} sha256-pinned entries)", file=sys.stderr)

    findings = scan_tree(root, denylist_terms, binary_allowlist)
    _print_report(root, findings, args.json)

    hard_count = sum(1 for f in findings if f["severity"] == "HARD")
    return 3 if hard_count else 0



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
    sys.exit(main())
