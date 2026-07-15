#!/usr/bin/env python3
"""Build a non-canonical HWPX copy for experimental layout renderers.

The XML backend historically emitted a synthetic one-line linesegarray for new
paragraphs without performing line layout. Some renderers trust that metadata
and therefore refuse to reflow the paragraph. This module removes only that
exact placeholder signature from a separate render surrogate. It never
overwrites the canonical HWPX and verifies semantic content parity after the
byte-local rewrite.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree


_LINESEGARRAY_RE = re.compile(
    br"<(?P<array_prefix>[A-Za-z_][\w.-]*:)?linesegarray\b[^>]*>\s*"
    br"<(?P<line_prefix>[A-Za-z_][\w.-]*:)?lineseg\b(?P<attrs>[^>]*)/\s*>\s*"
    br"</(?P<close_prefix>[A-Za-z_][\w.-]*:)?linesegarray\s*>"
)
_ATTR_RE = re.compile(
    br"(?P<name>[A-Za-z_][\w:.-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
)
_PLACEHOLDER_ATTRS = frozenset({
    "textpos", "vertpos", "vertsize", "textheight", "baseline",
    "spacing", "horzpos", "horzsize", "flags",
})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def semantic_fingerprint(path: str | os.PathLike[str]) -> dict:
    """Hash normalized body text and count structural body objects."""
    source = Path(path)
    chunks: list[str] = []
    counts = {"paragraphs": 0, "tables": 0, "pictures": 0, "equations": 0}
    count_names = {
        "p": "paragraphs",
        "tbl": "tables",
        "pic": "pictures",
        "equation": "equations",
    }
    with zipfile.ZipFile(source) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        section_names = [
            name for name in archive.namelist()
            if fnmatch.fnmatchcase(name.replace("\\", "/"), "Contents/section*.xml")
        ]
        if not section_names:
            raise ValueError("HWPX contains no Contents/section*.xml")
        for name in sorted(section_names):
            root = ElementTree.fromstring(archive.read(name))
            for element in root.iter():
                if not isinstance(element.tag, str):
                    continue
                local = _local_name(element.tag)
                if local == "t":
                    chunks.extend(element.itertext())
                count_key = count_names.get(local)
                if count_key:
                    counts[count_key] += 1
    normalized = unicodedata.normalize("NFC", "".join(chunks))
    normalized = re.sub(r"\s+", "", normalized)
    return {
        "normalized_text_sha256": hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest(),
        "counts": counts,
    }


def _placeholder_attributes(blob: bytes) -> dict[str, str] | None:
    parsed: dict[str, str] = {}
    for match in _ATTR_RE.finditer(blob):
        parsed[match.group("name").decode("ascii")] = match.group("value").decode(
            "ascii", errors="strict"
        )
    if set(parsed) != _PLACEHOLDER_ATTRS:
        return None
    try:
        values = {key: int(value) for key, value in parsed.items()}
    except ValueError:
        return None
    if not (
        values["textpos"] == 0
        and values["horzpos"] == 0
        and values["flags"] == 393216
        and values["vertpos"] >= 0
        and values["horzsize"] > 0
        and values["textheight"] > 0
        and values["vertsize"] == values["textheight"]
        and values["baseline"] * 100 == values["textheight"] * 85
        and values["spacing"] >= 0
    ):
        return None
    return parsed


def strip_stale_linesegarrays(xml_bytes: bytes) -> tuple[bytes, int]:
    """Remove exact XML-backend one-line placeholders without reserializing XML."""
    removed = 0

    def replace(match: re.Match[bytes]) -> bytes:
        nonlocal removed
        prefixes = (
            match.group("array_prefix") or b"",
            match.group("line_prefix") or b"",
            match.group("close_prefix") or b"",
        )
        if prefixes[0] != prefixes[1] or prefixes[0] != prefixes[2]:
            return match.group(0)
        if _placeholder_attributes(match.group("attrs")) is None:
            return match.group(0)
        removed += 1
        return b""

    return _LINESEGARRAY_RE.sub(replace, xml_bytes), removed


def create_render_surrogate(
    canonical: str | os.PathLike[str],
    surrogate: str | os.PathLike[str],
) -> dict:
    """Create and verify a render-only surrogate, preserving the source file."""
    source = Path(canonical).resolve()
    target = Path(surrogate).resolve()
    if source == target:
        raise ValueError("render surrogate must not overwrite canonical HWPX")
    if not source.is_file():
        raise FileNotFoundError(source)

    target.parent.mkdir(parents=True, exist_ok=True)
    canonical_sha256 = _sha256_file(source)
    canonical_fingerprint = semantic_fingerprint(source)
    removed_total = 0
    modified_parts: list[dict] = []
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".tmp",
            dir=target.parent, delete=False,
        ) as temp:
            temp_path = Path(temp.name)
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(temp_path, "w") as rendered:
            bad = original.testzip()
            if bad:
                raise ValueError(f"ZIP CRC failure: {bad}")
            for info in original.infolist():
                payload = original.read(info.filename)
                removed = 0
                normalized_name = info.filename.replace("\\", "/")
                if fnmatch.fnmatchcase(normalized_name, "Contents/section*.xml"):
                    payload, removed = strip_stale_linesegarrays(payload)
                rendered.writestr(info, payload)
                if removed:
                    modified_parts.append({
                        "part": normalized_name,
                        "stale_linesegarrays_removed": removed,
                    })
                    removed_total += removed
            rendered.comment = original.comment
        os.replace(temp_path, target)
        temp_path = None

        canonical_sha256_after = _sha256_file(source)
        if canonical_sha256_after != canonical_sha256:
            target.unlink(missing_ok=True)
            raise RuntimeError("canonical HWPX changed while creating render surrogate")
        surrogate_fingerprint = semantic_fingerprint(target)
        semantic_parity = surrogate_fingerprint == canonical_fingerprint
        if not semantic_parity:
            target.unlink(missing_ok=True)
            raise RuntimeError("render surrogate changed normalized content or object counts")
        return {
            "canonical": str(source),
            "surrogate": str(target),
            "canonical_sha256": canonical_sha256,
            "canonical_sha256_after": canonical_sha256_after,
            "surrogate_sha256": _sha256_file(target),
            "canonical_fingerprint": canonical_fingerprint,
            "surrogate_fingerprint": surrogate_fingerprint,
            "semantic_parity": semantic_parity,
            "stale_linesegarrays_removed": removed_total,
            "modified_parts": modified_parts,
            "canonical_unchanged": True,
            "canonical_submission_artifact": True,
            "surrogate_submission_artifact": False,
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="create render-only HWPX surrogate")
    parser.add_argument("canonical")
    parser.add_argument("surrogate")
    parser.add_argument("--receipt")
    args = parser.parse_args(argv)
    try:
        receipt = create_render_surrogate(args.canonical, args.surrogate)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile,
            ElementTree.ParseError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False))
        return 3
    if args.receipt:
        receipt_path = Path(args.receipt)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"ok": True, **receipt}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
