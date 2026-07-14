#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed Stage 6 canonical submission package preflight.

Exit 0 = pass, 3 = HARD finding, 2 = usage error. ``request.yaml`` is parsed
with a deliberately small top-level line scanner; absent optional keys produce
notes, while artifact extension/size/reopen and proof-grade checks always run.

The current proof handshake compares the recorded grade with local renderer
capabilities. Full artifact-bound proof receipts are deferred to later
attestation work. Until then, ``--allow-advisory`` is an explicit draft escape
that requires a non-empty reason and records it in the verdict JSON.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import render_probe


SUPPORTED_EXTENSIONS = {".hwpx", ".pdf"}
SUBMISSION_PROOF_GRADES = {"hancom", "advisory"}
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
ASSEMBLY_VERDICT_REL = Path("output/verdict_v06.json")


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _without_comment(value: str) -> str:
    quote = None
    for index, char in enumerate(value):
        if char in "\"'":
            quote = None if quote == char else (char if quote is None else quote)
        elif char == "#" and quote is None:
            return value[:index].rstrip()
    return value.strip()


def _unquote(value: str) -> str:
    value = _without_comment(value).strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _inline_value_error(value: str) -> str | None:
    quote = None
    escaped = False
    brackets: list[str] = []
    pairs = {"]": "[", "}": "{"}
    for char in value:
        if escaped:
            escaped = False
            continue
        if ord(char) == 92 and quote == chr(34):
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {chr(34), chr(39)}:
            quote = char
        elif char in "[{":
            brackets.append(char)
        elif char in "]}":
            if not brackets or brackets.pop() != pairs[char]:
                return "unbalanced inline collection"
    if quote:
        return "unterminated quoted scalar"
    if brackets:
        return "unterminated inline collection"
    return None


def _scan_request(
    path: Path,
) -> tuple[dict[str, str], list[str] | None, str | None]:
    scalars: dict[str, str] = {}
    required_fields = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return scalars, required_fields, "request.yaml is missing"
    except (OSError, UnicodeError) as exc:
        return scalars, required_fields, f"request.yaml is unreadable: {exc}"
    if not any(line.strip() and not line.lstrip().startswith("#") for line in lines):
        return scalars, required_fields, "request.yaml is empty"

    seen_keys: set[str] = set()
    collecting_required_fields = False
    for line_number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped in {"---", "..."}:
            continue
        if raw[:1].isspace():
            if collecting_required_fields:
                item = re.match(r"^\s+-\s+(.+?)\s*$", raw)
                if not item:
                    return (
                        scalars, required_fields,
                        f"request.yaml malformed at line {line_number}: "
                        "required_fields must be a list",
                    )
                value = item.group(1)
                error = _inline_value_error(value)
                if error:
                    return (
                        scalars, required_fields,
                        f"request.yaml malformed at line {line_number}: {error}",
                    )
                required_fields.append(_unquote(value))
            continue

        collecting_required_fields = False
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if not match:
            return (
                scalars, required_fields,
                f"request.yaml malformed at line {line_number}: "
                "expected a top-level key: value entry",
            )
        key, raw_value = match.groups()
        if key in seen_keys:
            return (
                scalars, required_fields,
                f"request.yaml malformed at line {line_number}: duplicate key {key!r}",
            )
        seen_keys.add(key)
        error = _inline_value_error(raw_value)
        if error:
            return (
                scalars, required_fields,
                f"request.yaml malformed at line {line_number}: {error}",
            )
        value = _without_comment(raw_value).strip()
        if key == "required_fields":
            if not value:
                required_fields = []
                collecting_required_fields = True
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                required_fields = ([] if not inner else
                                   [_unquote(item.strip()) for item in inner.split(",")])
            else:
                return (
                    scalars, required_fields,
                    f"request.yaml malformed at line {line_number}: "
                    "required_fields must be a list",
                )
        elif key == "output_filename" and value.startswith(("[", "{", ">", "|")):
            return (
                scalars, required_fields,
                f"request.yaml malformed at line {line_number}: "
                "output_filename must be a scalar",
            )
        elif value and not value.startswith(("[", "{", ">", "|")):
            scalars[key] = _unquote(value)
    if not seen_keys:
        return scalars, required_fields, "request.yaml contains no top-level mapping"
    if not scalars.get("output_filename") and required_fields is None:
        return (
            scalars,
            required_fields,
            "request.yaml contains none of the expected usable keys: "
            "output_filename, required_fields",
        )
    return scalars, required_fields, None


def _scan_pipeline_scalar(path: Path, key: str):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*([^#\r\n]+)", text)
    if not match:
        return None
    value = _unquote(match.group(1))
    return None if value.lower() in {"", "null", "none", "~"} else value


def _within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False


def _select_artifact(ws: Path, pattern: str | None):
    canonical = _scan_pipeline_scalar(ws / "PIPELINE.md", "canonical_output")
    if canonical:
        target = ws / canonical
        return target, canonical.replace("\\", "/")
    output = ws / "output"
    if pattern:
        matches = [path for path in output.iterdir()
                   if path.is_file() and fnmatch.fnmatchcase(path.name, pattern)] \
            if output.is_dir() else []
        if len(matches) == 1:
            return matches[0], matches[0].relative_to(ws).as_posix()
    matches = [path for path in output.glob("out.*")
               if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
    if len(matches) == 1:
        return matches[0], matches[0].relative_to(ws).as_posix()
    return None, None


def _hwpx_text(path: Path) -> str:
    chunks = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("HWPX ZIP contains no XML parts")
        for name in xml_names:
            root = ElementTree.fromstring(archive.read(name))
            chunks.extend(text for text in root.itertext() if text)
    return " ".join(chunks)


def _pdf_text(path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError(f"PyMuPDF unavailable: {exc}") from exc
    with fitz.open(path) as document:
        if document.page_count <= 0:
            raise ValueError("PDF contains no pages")
        text = "".join(page.get_text() for page in document)
    if not text.strip():
        raise ValueError("PDF contains no extractable text")
    return text


def _proof_grade(ws: Path):
    source = ws / ASSEMBLY_VERDICT_REL
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, source
    if not isinstance(payload, dict) or "proof_grade" not in payload:
        return None, source
    return str(payload["proof_grade"]).strip().lower(), source


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def check(
    workspace: str | Path,
    *,
    allow_unproven: bool = False,
    allow_advisory: bool = False,
    reason: str | None = None,
) -> tuple[dict, int]:
    ws = Path(workspace)
    advisory_reason = str(reason).strip() if reason is not None else ""
    if allow_advisory and not advisory_reason:
        return {
            "ok": False,
            "workspace": str(ws),
            "checker": "submission_preflight",
            "error": "--allow-advisory requires a non-empty --reason",
            "advisory_reason": None,
            "hard": [],
            "warn": [],
            "counts": {"hard": 0, "warn": 0},
            "verdict": "usage_error",
        }, 2
    hard: list[dict] = []
    warn: list[dict] = []
    notes: list[str] = []
    scalars, required_fields, request_error = _scan_request(ws / "request.yaml")
    if request_error:
        hard.append({
            "code": "P0",
            "msg": request_error,
            "at": "request.yaml",
        })
    pattern = scalars.get("output_filename")
    if not request_error and not pattern:
        notes.append("request.yaml output_filename absent; filename match skipped")
    if not request_error and required_fields is None:
        notes.append("request.yaml required_fields absent; identity checks skipped")

    artifact, artifact_rel = _select_artifact(ws, pattern)
    extracted_text = ""
    document_has_equations = False
    if artifact is None:
        hard.append({"code": "P1", "msg": "canonical submission artifact is missing or ambiguous",
                     "at": "output/out.*"})
    elif not _within(ws / "output", artifact):
        hard.append({"code": "P1", "msg": "canonical artifact escapes output directory",
                     "at": artifact_rel})
    elif not artifact.is_file():
        hard.append({"code": "P1", "msg": "canonical artifact does not exist",
                     "at": artifact_rel})
    else:
        if pattern and not fnmatch.fnmatchcase(artifact.name, pattern):
            hard.append({"code": "P2", "msg": "artifact filename does not match output_filename pattern",
                         "at": f"{artifact.name!r} vs {pattern!r}"})
        suffix = artifact.suffix.lower()
        size = artifact.stat().st_size
        if suffix not in SUPPORTED_EXTENSIONS:
            hard.append({"code": "P3", "msg": f"unsupported submission extension: {suffix or '<none>'}",
                         "at": artifact_rel})
        elif size <= 0 or size > MAX_ARTIFACT_BYTES:
            hard.append({"code": "P3", "msg": f"artifact size is not sane: {size} bytes",
                         "at": artifact_rel})
        else:
            try:
                extracted_text = _hwpx_text(artifact) if suffix == ".hwpx" else _pdf_text(artifact)
                if suffix == ".hwpx":
                    document_has_equations = render_probe.hwpx_has_equations(artifact)
            except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
                hard.append({"code": "P3", "msg": f"artifact reopen failed: {exc}",
                             "at": artifact_rel})

    if required_fields is not None:
        rendered = _normalized(extracted_text)
        for field in required_fields:
            expected = scalars.get(field, "").strip()
            placeholder = expected.casefold() in {"", "null", "none", "todo", "tbd", "~"}
            if placeholder or _normalized(expected) not in rendered:
                hard.append({"code": "P4", "msg": f"required identity field not filled: {field}",
                             "at": artifact_rel or "request.yaml"})

    grade, grade_source = _proof_grade(ws)
    delivery_capabilities = None
    if grade == "none" and allow_unproven:
        notes.append("draft explicitly allows proof_grade none (--allow-unproven)")
    elif grade not in SUBMISSION_PROOF_GRADES:
        hard.append({
            "code": "P5",
            "msg": "graded submission proof_grade must be hancom or advisory",
            "at": ASSEMBLY_VERDICT_REL.as_posix(),
        })
    else:
        probe_result = render_probe.probe()
        capabilities = probe_result.get("capabilities", {})
        delivery_capabilities = {
            "hancom_com": capabilities.get("hancom_com") is True,
            "h2orestart": capabilities.get("h2orestart"),
        }
        reasons = []
        if grade == "hancom" and not delivery_capabilities["hancom_com"]:
            reasons.append(
                "recorded Hancom proof cannot be reproduced on this delivery machine")
        if grade == "advisory" and document_has_equations:
            reasons.append(
                "advisory proof is not meaningful for an equation-bearing document")
        if reasons and not allow_advisory:
            hard.append({
                "code": "proof_grade_unverifiable_here",
                "msg": "; ".join(reasons),
                "at": artifact_rel or ASSEMBLY_VERDICT_REL.as_posix(),
            })
        elif reasons:
            notes.append(
                "draft explicitly accepts locally unverifiable/advisory proof "
                "(--allow-advisory)")
        elif grade == "advisory" and allow_advisory:
            notes.append(
                "draft explicitly accepts advisory proof (--allow-advisory)")

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "artifact": artifact_rel,
        "proof_grade": grade,
        "proof_grade_source": (grade_source.relative_to(ws).as_posix()
                               if grade_source else None),
        "delivery_capabilities": delivery_capabilities,
        "document_has_equations": document_has_equations,
        "advisory_reason": advisory_reason if allow_advisory else None,
        "notes": notes,
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="submission package preflight")
    parser.add_argument("workspace")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--allow-unproven",
        action="store_true",
        help="allow proof_grade none for an explicit draft run only",
    )
    parser.add_argument(
        "--allow-advisory",
        action="store_true",
        help="allow locally unverifiable/advisory proof for an explicit draft only",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="non-empty audit reason required with --allow-advisory",
    )
    args = parser.parse_args(argv)
    verdict, code = check(
        args.workspace,
        allow_unproven=args.allow_unproven,
        allow_advisory=args.allow_advisory,
        reason=args.reason,
    )
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
