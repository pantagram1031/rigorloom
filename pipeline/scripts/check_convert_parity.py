#!/usr/bin/env python3
"""Check that form conversion preserved extracted semantic content.

Two modes, routed on the A-side suffix:

- A = content.md / extraction dir / .hwpx (original contract): full semantic
  parity — normalized text hash, structural counts, equation scripts.
- A = .hwp (W6.2, XC-1 §2 formalized): raw-format conversion parity. A .hwp
  cannot be fingerprinted offline, so the source leg comes from COM
  (engine/scripts/com_backend.py inspect — GetTextFile char total + native
  control counts). Guarded: Windows + pyhwpx only; elsewhere the check SKIPS
  loudly with a non-pass exit, never process-success. Structural counts
  (tables / pictures / equations) must match the converted .hwpx exactly;
  text char totals are ADVISORY only — the two extraction paths normalize
  differently (COM GetTextFile includes field/UI chrome; the XML walk does
  not), so char equality is not expected and not gated (XC-1 §2).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

from checker_base import EXIT_HARD, EXIT_PASS, cli_main, usage_error, verdict_skeleton
from content_extract import (
    MANIFEST_NAME,
    content_markdown_fingerprint,
    extract_document,
    local,
    section_names,
    semantic_fingerprint,
    sha_file,
)

ENGINE_COM_BACKEND = (
    Path(__file__).resolve().parents[2] / "engine" / "scripts" / "com_backend.py"
)


def com_leg_available() -> bool:
    """The .hwp source leg needs Windows + pyhwpx (Hancom COM)."""
    return sys.platform == "win32" and importlib.util.find_spec("pyhwpx") is not None


def _com_inspect(path: str | Path) -> dict:
    """Run com_backend inspect on a .hwp and return its JSON payload."""
    proc = subprocess.run(
        [sys.executable, str(ENGINE_COM_BACKEND), "inspect",
         "--file", str(path), "--preview-chars", "0"],
        capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise ValueError(
            f"COM inspect failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}")
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise ValueError(f"COM inspect not ok: {payload.get('error')}")
    return payload


def _hwpx_text_chars(path: str | Path) -> int:
    """Whitespace-stripped char total of all <hp:t> text in a .hwpx."""
    total = 0
    with zipfile.ZipFile(path) as archive:
        for name in section_names(archive.namelist()):
            for node in ET.fromstring(archive.read(name)).iter():
                if isinstance(node.tag, str) and local(node.tag) == "t":
                    for chunk in node.itertext():
                        total += len(re.sub(r"\s+", "", chunk))
    return total


def check_hwp_conversion(src_hwp: str | Path,
                         converted_hwpx: str | Path) -> tuple[dict, int]:
    """Structural parity for a raw .hwp -> .hwpx conversion (COM source leg)."""
    src, dst = Path(src_hwp), Path(converted_hwpx)
    if not src.is_file():
        return usage_error(src, "check_convert_parity",
                           "A-side .hwp source does not exist")
    if dst.suffix.lower() != ".hwpx" or not dst.is_file():
        return usage_error(dst, "check_convert_parity",
                           "B-side must be the converted, existing .hwpx")
    if not com_leg_available():
        verdict = verdict_skeleton(
            str(dst.resolve()), "check_convert_parity",
            warn=[{
                "code": "hwp_source_leg_unavailable",
                "msg": ".hwp source leg needs Windows + pyhwpx (Hancom COM); "
                       "skipping — this is NOT a pass",
                "at": str(src.resolve()),
            }],
            extra={"mode": "hwp_conversion", "src_hwp": str(src.resolve())},
            verdict="skip")
        # No source leg means no conversion-parity evidence.  Keep the
        # explicit ``skip`` verdict for machine readers, but never let a shell
        # or pipeline mistake an unavailable check for a successful gate.
        return verdict, EXIT_HARD
    try:
        com = _com_inspect(src)
        hwpx = semantic_fingerprint(dst)
        hwpx_chars = _hwpx_text_chars(dst)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError,
            json.JSONDecodeError) as exc:
        return usage_error(dst, "check_convert_parity",
                           f"input could not be fingerprinted: {exc}")
    src_counts = {
        "tables": com.get("tables"),
        "pictures": com.get("pictures"),
        "equations": len(com.get("equations") or []),
    }
    dst_counts = {
        "tables": hwpx["counts"]["tables"],
        "pictures": hwpx["counts"]["pictures"],
        "equations": hwpx["counts"]["equations"],
    }
    hard = []
    if src_counts != dst_counts:
        hard.append({
            "code": "convert_structural_drift",
            "msg": "native control counts differ between .hwp source (COM) "
                   "and converted .hwpx (XML)",
            "at": str(dst.resolve()),
            "expected": src_counts,
            "actual": dst_counts,
        })
    verdict = verdict_skeleton(
        str(dst.resolve()), "check_convert_parity", hard=hard,
        extra={
            "mode": "hwp_conversion",
            "src_hwp": str(src.resolve()),
            "src_counts": src_counts,
            "converted_counts": dst_counts,
            "text_chars": {
                "hwp_com_raw": com.get("text_chars_total"),
                "hwpx_normalized": hwpx_chars,
                "note": "advisory only — COM GetTextFile and the XML walk "
                        "normalize differently (XC-1 §2); not gated",
            },
            "pages_document": com.get("pages"),
        })
    return verdict, EXIT_HARD if hard else EXIT_PASS


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
    if extracted_path.suffix.lower() == ".hwp":
        return check_hwp_conversion(extracted_path, assembled_path)
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
    parser.add_argument(
        "extracted",
        help="content.md, extraction directory, .hwpx — or a source .hwp "
             "for raw conversion parity (COM leg; Windows+pyhwpx, skips "
             "cleanly elsewhere)")
    parser.add_argument("assembled", help="assembled form-B / converted .hwpx")
    return parser


def main(argv=None) -> int:
    return cli_main(
        build_parser(), lambda args: check(args.extracted, args.assembled),
        argv, create_out_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
