#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify checksums for figures referenced by bundle/content.md.

A referenced PNG is checked against every available checksum source: its sibling
name.png.sha256 and/or figures_manifest.json. Missing PNGs are skipped because
verify_content.py owns the H3 existence finding.
Consistent hand-edits to both a PNG and all checksum records are undetectable
without an external trust anchor; that stronger provenance check is deferred.

Exit 0 = pass (WARNs allowed), 3 = HARD drift, 2 = usage/input error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_FIG_RE = re.compile(r'\[\[FIG\s+file="([^"]+)"')


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_figure(figures: Path, reference: str) -> Path | None:
    normalized = reference.replace("\\", "/")
    if (normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized)):
        return None
    candidate = figures.joinpath(*normalized.split("/"))
    try:
        candidate.resolve().relative_to(figures.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def _manifest_entries(payload) -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}

    def add(file_value, sha_value) -> None:
        if isinstance(file_value, str) and isinstance(sha_value, str):
            key = file_value.replace("\\", "/")
            entries.setdefault(key, []).append(sha_value.strip())

    def collect(value) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return
        if "file" in value and "sha256" in value:
            add(value.get("file"), value.get("sha256"))
        for container_key in ("figures", "files", "entries"):
            nested = value.get(container_key)
            if isinstance(nested, dict):
                for file_value, sha_value in nested.items():
                    if isinstance(sha_value, dict):
                        add(file_value, sha_value.get("sha256"))
                    else:
                        add(file_value, sha_value)
            elif isinstance(nested, list):
                collect(nested)
        reserved = {"file", "sha256", "figures", "files", "entries",
                    "schema", "generated_at"}
        for file_value, sha_value in value.items():
            if file_value in reserved:
                continue
            if isinstance(sha_value, str):
                add(file_value, sha_value)
            elif isinstance(sha_value, dict) and "sha256" in sha_value:
                add(file_value, sha_value.get("sha256"))

    collect(payload)
    return entries


def _load_manifest(path: Path) -> tuple[dict[str, list[str]], str | None]:
    if not path.exists():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"figures_manifest.json is unreadable: {exc}"
    if not isinstance(payload, (dict, list)):
        return {}, "figures_manifest.json must contain an object or array"
    return _manifest_entries(payload), None


def check(workspace: str | Path) -> tuple[dict, int]:
    ws = Path(workspace)
    content_path = ws / "bundle" / "content.md"
    try:
        content = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"ok": False, "error": "bundle/content.md not found"}, 2
    except (OSError, UnicodeError) as exc:
        return {"ok": False, "error": f"bundle/content.md unreadable: {exc}"}, 2

    figures = ws / "bundle" / "figures"
    manifest_path = figures / "figures_manifest.json"
    manifest, manifest_error = _load_manifest(manifest_path)
    if manifest_error:
        return {"ok": False, "error": manifest_error}, 2

    hard: list[dict] = []
    warn: list[dict] = []
    seen: set[str] = set()
    for match in _FIG_RE.finditer(content):
        reference = match.group(1)
        normalized = reference.replace("\\", "/")
        if normalized in seen or not normalized.lower().endswith(".png"):
            continue
        seen.add(normalized)
        figure = _safe_figure(figures, reference)
        if figure is None or not figure.is_file():
            continue

        expected: list[tuple[str, str]] = []
        sidecar = figure.with_name(figure.name + ".sha256")
        if sidecar.exists():
            try:
                tokens = sidecar.read_text(encoding="utf-8").split()
                expected.append((sidecar.relative_to(ws).as_posix(),
                                 tokens[0] if tokens else ""))
            except (OSError, UnicodeError):
                expected.append((sidecar.relative_to(ws).as_posix(), ""))

        for digest in manifest.get(normalized, []):
            expected.append((manifest_path.relative_to(ws).as_posix(), digest))

        if not expected:
            warn.append({
                "code": "figure_unverified",
                "msg": "referenced figure has no checksum sidecar or manifest entry",
                "at": normalized,
            })
            continue

        try:
            actual = _sha256(figure)
        except OSError as exc:
            return {
                "ok": False,
                "error": f"referenced figure is unreadable: {normalized}: {exc}",
            }, 2
        for source, digest in expected:
            normalized_digest = digest.lower()
            if (not _SHA256_RE.fullmatch(digest)
                    or normalized_digest != actual):
                hard.append({
                    "code": "figure_data_drift",
                    "msg": "referenced figure sha256 does not match recorded checksum",
                    "at": normalized,
                    "checksum_source": source,
                    "expected": normalized_digest or None,
                    "actual": actual,
                })

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "checker": "check_figdata",
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="verify referenced figure checksums")
    parser.add_argument("workspace")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace)
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
