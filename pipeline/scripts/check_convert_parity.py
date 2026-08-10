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
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
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
)
import hwp_equation_diagnostic
import hwp_ingress
import hwp_source_coverage
import diagnostic_candidate_core

ENGINE_COM_BACKEND = (
    Path(__file__).resolve().parents[2] / "engine" / "scripts" / "com_backend.py"
)
COM_INSPECT_TIMEOUT = 60.0


def com_leg_available() -> bool:
    """The .hwp source leg needs Windows + pyhwpx (Hancom COM)."""
    return sys.platform == "win32" and importlib.util.find_spec("pyhwpx") is not None


def _com_inspect(path: str | Path) -> dict:
    """Run the T85-bounded, privacy-safe COM inspect and adapt its counts."""
    argv = [
        sys.executable, str(ENGINE_COM_BACKEND), "inspect", "--file", str(path),
        "--preview-chars", "0", "--privacy-safe",
    ]
    payload = hwp_ingress._com_inspect(argv, timeout=COM_INSPECT_TIMEOUT)
    counts = payload.get("counts") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or not isinstance(counts, dict)
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in counts.values())):
        raise hwp_ingress.IngressError("hancom_counts_missing")
    required = ("tables", "pictures", "equations", "shapes", "pages",
                "controls_total", "field_count")
    if any(key not in counts for key in required):
        raise hwp_ingress.IngressError("hancom_counts_missing")
    return {
        "ok": True,
        "text_sha256": payload.get("text_sha256"),
        "text_chars_total": payload.get("text_chars_total"),
        "tables": counts["tables"],
        "pictures": counts["pictures"],
        "equations": counts["equations"],
        "shapes": counts["shapes"],
        "pages": counts["pages"],
        "controls_total": counts["controls_total"],
        "field_count": counts["field_count"],
    }


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
        resolved_src = hwp_source_coverage._resolve_input_path(src)
        captured_src = hwp_source_coverage._read_input_once(resolved_src)
        hwp_source_coverage._preflight(captured_src)
        resolved_dst = hwp_equation_diagnostic._resolve_input_path(dst)
        captured_dst = hwp_equation_diagnostic._read_input_once(resolved_dst)
        with tempfile.TemporaryDirectory(prefix=".convert-parity-") as temp:
            temp_root = Path(temp)
            source_snapshot = temp_root / "source.hwp"
            converted_snapshot = temp_root / "converted.hwpx"
            diagnostic_candidate_core.write_bytes(source_snapshot, captured_src)
            diagnostic_candidate_core.write_bytes(converted_snapshot, captured_dst)
            with hwp_ingress._com_serial_guard():
                com = _com_inspect(source_snapshot)
            hwp_equation_diagnostic.equation_presence(converted_snapshot)
            hwpx = semantic_fingerprint(converted_snapshot)
            hwpx_chars = _hwpx_text_chars(converted_snapshot)
        if (hwp_source_coverage._read_input_once(resolved_src) != captured_src
                or hwp_equation_diagnostic._read_input_once(resolved_dst)
                != captured_dst):
            raise hwp_equation_diagnostic.CoverageError("input_changed")
    except hwp_equation_diagnostic.CoverageError as exc:
        code = ("convert_input_changed" if exc.reason == "input_changed"
                else "convert_equation_envelope_invalid")
        verdict = verdict_skeleton(
            str(dst.resolve()), "check_convert_parity",
            hard=[{
                "code": code,
                "msg": ("converted HWPX changed during parity"
                        if code == "convert_input_changed" else
                        "converted HWPX equation envelope is ambiguous or invalid"),
                "at": str(dst.resolve()),
                "reason": exc.reason,
            }],
            extra={"mode": "hwp_conversion"},
        )
        return verdict, EXIT_HARD
    except hwp_source_coverage.CoverageError as exc:
        verdict = verdict_skeleton(
            str(dst.resolve()), "check_convert_parity",
            hard=[{
                "code": "convert_input_invalid",
                "msg": "source HWP could not be captured for parity",
                "at": str(src.resolve()),
                "reason": exc.reason,
            }],
            extra={"mode": "hwp_conversion"},
        )
        return verdict, EXIT_HARD
    except hwp_ingress.IngressError as exc:
        verdict = verdict_skeleton(
            str(dst.resolve()), "check_convert_parity",
            hard=[{
                "code": "convert_com_inspect_invalid",
                "msg": "bounded COM inspection did not produce a safe fingerprint",
                "at": str(dst.resolve()),
                "reason": exc.reason,
            }],
            extra={"mode": "hwp_conversion"},
        )
        return verdict, EXIT_HARD
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError,
            json.JSONDecodeError) as exc:
        return usage_error(dst, "check_convert_parity",
                           f"input could not be fingerprinted: {exc}")
    equations = com.get("equations")
    equation_count = (
        equations if isinstance(equations, int) and not isinstance(equations, bool)
        else len(equations) if isinstance(equations, list) else -1
    )
    src_counts = {
        "tables": com.get("tables"),
        "pictures": com.get("pictures"),
        "equations": equation_count,
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


def source_hwpx(path: str | Path) -> tuple[Path, str | None]:
    """Resolve the original HWPX behind an extraction input, fail-closed."""
    target = Path(path)
    if target.suffix.lower() == ".hwpx":
        return target, None
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
    if (not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None):
        raise ValueError("source HWPX manifest hash is missing or invalid")
    return source, expected_hash


def content_core(fingerprint: dict) -> dict:
    return {
        "normalized_text_sha256": fingerprint["normalized_text_sha256"],
        "counts": fingerprint["counts"],
    }


def _pack_semantic_piece(value: bytes) -> bytes:
    """Length-delimit a semantic value before hashing it internally."""
    return len(value).to_bytes(8, "big") + value


def _spine_semantic_sequence(path: str | Path) -> tuple[bytes, ...]:
    """Return opaque per-section semantic keys in the resolved OPF spine order.

    This is intentionally not a raw XML digest and never leaves this process.
    It includes exact NFC text boundaries, equation-script cardinality, and
    closed local-tag counts, so a reordered OPF spine cannot be hidden by
    filename sorting or the global ``semantic_fingerprint``. Script bytes are
    compared separately by the exact equation-drift check.
    """
    data = hwp_equation_diagnostic._read_input_once(
        hwp_equation_diagnostic._resolve_input_path(Path(path)))
    sections, _ = hwp_equation_diagnostic._spine_sections(data)
    sequence: list[bytes] = []
    for _member, payload in sections:
        root = ET.fromstring(payload)
        chunks: list[bytes] = [b"rigorloom/t91-section-semantic-v1"]
        local_counts: dict[str, int] = {}
        text_chunks: list[str] = []
        script_chunks: list[str] = []
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            local_name = local(node.tag)
            local_counts[local_name] = local_counts.get(local_name, 0) + 1
            if local_name == "t":
                text_chunks.append("".join(node.itertext()))
            elif local_name == "script":
                script_chunks.append(node.text or "")
        for local_name, count in sorted(local_counts.items()):
            chunks.append(_pack_semantic_piece(local_name.encode("utf-8")))
            chunks.append(_pack_semantic_piece(str(count).encode("ascii")))
        for label, values in ((b"text", text_chunks),
                              (b"script", script_chunks)):
            chunks.append(_pack_semantic_piece(label))
            chunks.append(_pack_semantic_piece(str(len(values)).encode("ascii")))
            for value in values:
                encoded = unicodedata.normalize("NFC", value).encode("utf-8")
                chunks.append(_pack_semantic_piece(encoded))
        sequence.append(hashlib.sha256(b"".join(chunks)).digest())
    return tuple(sequence)


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
        source_path, expected_source_hash = source_hwpx(extracted_path)
        resolved_source = hwp_equation_diagnostic._resolve_input_path(source_path)
        resolved_assembled = hwp_equation_diagnostic._resolve_input_path(assembled_path)
        captured_source = hwp_equation_diagnostic._read_input_once(resolved_source)
        captured_assembled = hwp_equation_diagnostic._read_input_once(resolved_assembled)
        if (expected_source_hash is not None
                and hashlib.sha256(captured_source).hexdigest()
                != expected_source_hash):
            raise hwp_equation_diagnostic.CoverageError(
                "source_manifest_hash_mismatch")
        with tempfile.TemporaryDirectory(prefix=".convert-parity-") as temp:
            temp_root = Path(temp)
            source_snapshot = temp_root / "source.hwpx"
            assembled_snapshot = temp_root / "assembled.hwpx"
            diagnostic_candidate_core.write_bytes(source_snapshot, captured_source)
            diagnostic_candidate_core.write_bytes(
                assembled_snapshot, captured_assembled)
            hwp_equation_diagnostic.equation_presence(source_snapshot)
            hwp_equation_diagnostic.equation_presence(assembled_snapshot)
            before_input = (
                source_snapshot
                if extracted_path.suffix.lower() == ".hwpx"
                else extracted_path
            )
            before = input_fingerprint(before_input)
            after = input_fingerprint(assembled_snapshot)
            source_before = semantic_fingerprint(source_snapshot)
            source_after = semantic_fingerprint(assembled_snapshot)
            source_spine_sequence = _spine_semantic_sequence(source_snapshot)
            assembled_spine_sequence = _spine_semantic_sequence(assembled_snapshot)
        if (hwp_equation_diagnostic._read_input_once(resolved_source)
                != captured_source
                or hwp_equation_diagnostic._read_input_once(resolved_assembled)
                != captured_assembled):
            raise hwp_equation_diagnostic.CoverageError("input_changed")
    except hwp_equation_diagnostic.CoverageError as exc:
        if exc.reason == "input_changed":
            code = "convert_input_changed"
        elif exc.reason == "source_manifest_hash_mismatch":
            code = "convert_source_binding_invalid"
        else:
            code = "convert_equation_envelope_invalid"
        verdict = verdict_skeleton(
            str(assembled_path.resolve()), "check_convert_parity",
            hard=[{
                "code": code,
                "msg": (
                    "source or assembled HWPX changed during parity"
                    if code == "convert_input_changed" else
                    "captured source HWPX does not match extraction manifest"
                    if code == "convert_source_binding_invalid" else
                    "source or assembled HWPX equation envelope is ambiguous or invalid"
                ),
                "at": str(assembled_path.resolve()),
                "reason": exc.reason,
            }],
        )
        return verdict, EXIT_HARD
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
    if (source_spine_sequence != assembled_spine_sequence
            and sorted(source_spine_sequence) == sorted(assembled_spine_sequence)):
        hard.append({
            "code": "convert_section_order_drift",
            "msg": "resolved OPF spine section semantic order changed",
            "at": str(assembled_path.resolve()),
            "expected": {"section_count": len(source_spine_sequence)},
            "actual": {"section_count": len(assembled_spine_sequence)},
            "reason": "spine_semantic_sequence_mismatch",
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
