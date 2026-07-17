#!/usr/bin/env python3
"""Check that form conversion preserved extracted semantic content."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from checker_base import EXIT_HARD, EXIT_PASS, cli_main, usage_error, verdict_skeleton
from content_extract import (
    MANIFEST_NAME,
    content_markdown_fingerprint,
    extract_document,
    semantic_fingerprint,
    sha_file,
)


def input_fingerprint(path: str | Path) -> dict:
    target = Path(path)
    if target.is_dir():
        target = target / "content.md"
    if target.suffix.lower() == ".md":
        return content_markdown_fingerprint(target.read_text(encoding="utf-8"))
    if target.suffix.lower() == ".hwpx":
        extracted = extract_document(target)
        return content_markdown_fingerprint(extracted["content"])
    raise ValueError("input must be content.md, its directory, or an .hwpx")


def source_hwpx(path: str | Path) -> Path:
    """Resolve the original HWPX behind an extraction input, fail-closed."""
    target = Path(path)
    if target.suffix.lower() == ".hwpx":
        return target
    manifest_path = (
        target / MANIFEST_NAME if target.is_dir()
        else target.parent / MANIFEST_NAME
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_record = manifest["source"]
        source = Path(source_record["path"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            "A-extract requires extraction_manifest.json with source HWPX"
        ) from exc
    if source.suffix.lower() != ".hwpx" or not source.is_file():
        raise ValueError(f"source HWPX from extraction manifest is unavailable: {source}")
    expected_hash = source_record.get("sha256")
    if expected_hash and sha_file(source) != expected_hash:
        raise ValueError("source HWPX hash differs from extraction manifest")
    return source


def content_core(fingerprint: dict) -> dict:
    return {
        "normalized_text_sha256": fingerprint["normalized_text_sha256"],
        "counts": fingerprint["counts"],
    }


def check(extracted: str | Path, assembled: str | Path) -> tuple[dict, int]:
    extracted_path, assembled_path = Path(extracted), Path(assembled)
    if not extracted_path.exists():
        return usage_error(extracted_path, "check_convert_parity",
                           "A-extract input does not exist")
    if assembled_path.suffix.lower() != ".hwpx" or not assembled_path.is_file():
        return usage_error(assembled_path, "check_convert_parity",
                           "B-assembled input must be an existing .hwpx")
    try:
        before = input_fingerprint(extracted_path)
        after = input_fingerprint(assembled_path)
        source_path = source_hwpx(extracted_path)
        source_before = semantic_fingerprint(source_path)
        source_after = semantic_fingerprint(assembled_path)
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile,
            ET.ParseError) as exc:
        return usage_error(assembled_path, "check_convert_parity",
                           f"input could not be fingerprinted: {exc}")
    hard = []
    if (content_core(before) != content_core(after)
            or content_core(source_before) != content_core(source_after)):
        hard.append({
            "code": "convert_content_drift",
            "msg": "normalized text or structural counts changed",
            "at": str(assembled_path.resolve()),
            "expected": {
                "content": content_core(before),
                "source_hwpx": content_core(source_before),
            },
            "actual": {
                "content": content_core(after),
                "source_hwpx": content_core(source_after),
            },
        })
    if (before["equation_scripts"] != after["equation_scripts"]
            or source_before["equation_scripts"] != source_after["equation_scripts"]):
        hard.append({
            "code": "convert_equation_drift",
            "msg": "normalized HwpEqn script text changed",
            "at": str(assembled_path.resolve()),
            "expected": {
                "content": before["equation_scripts"],
                "source_hwpx": source_before["equation_scripts"],
            },
            "actual": {
                "content": after["equation_scripts"],
                "source_hwpx": source_after["equation_scripts"],
            },
        })
    verdict = verdict_skeleton(
        str(assembled_path.resolve()), "check_convert_parity", hard=hard,
        extra={"a_extract": str(extracted_path.resolve()),
               "b_assembled": str(assembled_path.resolve()),
               "source_hwpx": str(source_path.resolve()),
               "before": before, "after": after,
               "source_before": source_before,
               "source_after": source_after})
    return verdict, EXIT_HARD if hard else EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="compare A-extract content with B-assembled HWPX semantics")
    parser.add_argument("extracted", help="content.md or extraction directory")
    parser.add_argument("assembled", help="assembled form-B .hwpx")
    return parser


def main(argv=None) -> int:
    return cli_main(
        build_parser(), lambda args: check(args.extracted, args.assembled),
        argv, create_out_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
