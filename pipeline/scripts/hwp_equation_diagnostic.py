#!/usr/bin/env python3
"""Privacy-safe, receipt-only structural inventory for HWPX equations.

This scanner deliberately does not interpret HwpEqn.  It proves only that a
captured, T85-valid HWPX package has a closed OPF spine and that every official
paragraph-namespace equation is a direct child of a run with exactly one
direct, nonempty, text-only script child.  Script text and script hashes never
leave the process.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import sys
import tempfile
from typing import Any
import zipfile
from xml.etree import ElementTree as ET

try:
    import diagnostic_candidate_core as _core
    import hwp_ingress as _ingress
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_ingress as _ingress


SCHEMA = "rigorloom/hwp-equation-diagnostic/v1"
ROOT_LEAF = "hwp-equation-diagnostic"
METHOD = "owpml_equation_script_envelope_inventory_v1"
PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF_NS = "http://www.idpf.org/2007/opf/"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

MAX_INPUT_BYTES = getattr(_ingress, "MAX_HWPX_BYTES", 256 * 1024 * 1024)
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_SECTIONS = 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_XML_NODES = 2_000_000
MAX_EQUATIONS = 1_000_000
MAX_SCRIPT_BYTES = 1024 * 1024
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SECTION_RE = re.compile(r"Contents/section\d+\.xml\Z")

SCANNER = {
    "name": "rigorloom_hwpx_equation_diagnostic",
    "version": 1,
    "execution": "independent_no_external_tool",
}

_TOP_KEYS = frozenset({
    "schema", "status", "source", "scanner", "structure", "equations",
    "execution", "diagnostic_artifact", "native", "render", "comparison",
    "proof_grade", "submission_grade",
})


class CoverageError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _PrivateArgumentParser(argparse.ArgumentParser):
    """Argparse surface that never reflects caller-supplied values."""

    def error(self, message: str) -> None:
        del message
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, "error: invalid arguments\n")


def _qname(tag: Any) -> tuple[str, str]:
    if not isinstance(tag, str) or not tag.startswith("{") or "}" not in tag:
        return "", str(tag) if isinstance(tag, str) else ""
    namespace, local = tag[1:].split("}", 1)
    return namespace, local


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CoverageError("receipt_duplicate_key")
        value[key] = item
    return value


def _coerce_path(value: Any, reason: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise CoverageError(reason)
    try:
        return Path(value)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoverageError(reason)


def _resolve_input_path(path: Path) -> Path:
    if path.suffix.casefold() != ".hwpx":
        raise CoverageError("extension_not_hwpx")
    try:
        candidate = path.expanduser().absolute()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        probe = candidate
        leaf = True
        while True:
            info = probe.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & reparse
                    or (leaf and not stat.S_ISREG(info.st_mode))):
                raise CoverageError("input_unavailable")
            if probe == probe.parent:
                break
            probe = probe.parent
            leaf = False
        resolved = candidate.resolve(strict=True)
        if resolved.suffix.casefold() != ".hwpx":
            raise CoverageError("extension_not_hwpx")
        return resolved
    except CoverageError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoverageError("input_unavailable")


def _read_input_once(path: Path) -> bytes:
    resolved = _resolve_input_path(path)
    try:
        return _core.read_regular_once(resolved, MAX_INPUT_BYTES,
                                       "input_unavailable")
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)


def _validate_captured_package(data: bytes) -> None:
    if not isinstance(data, bytes) or not data:
        raise CoverageError("input_empty")
    try:
        with tempfile.TemporaryDirectory(prefix=".equation-capture-") as temp:
            captured = Path(temp) / "captured.hwpx"
            _core.write_bytes(captured, data, write_reason="input_invalid")
            _ingress._validate_hwpx(captured)
    except CoverageError:
        raise
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)
    except _ingress.IngressError as exc:
        raise CoverageError(exc.reason)
    except (OSError, RuntimeError, TypeError, ValueError, zipfile.BadZipFile,
            ET.ParseError):
        raise CoverageError("hwpx_invalid")


def _resolve_opf_href(href: str, names: set[str]) -> str:
    value = href.replace("\\", "/")
    direct = posixpath.normpath(value)
    relative = posixpath.normpath(posixpath.join("Contents", value))
    if direct in names:
        return direct
    if relative in names:
        return relative
    raise CoverageError("opf_target_missing")


def _spine_sections(data: bytes) -> tuple[list[tuple[str, bytes]], set[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None:
                raise CoverageError("hwpx_crc_invalid")
            names = {item.filename.replace("\\", "/") for item in archive.infolist()}
            opf = ET.fromstring(archive.read("Contents/content.hpf"))
            manifest = next((node for node in opf
                             if _qname(node.tag) == (OPF_NS, "manifest")), None)
            spine = next((node for node in opf
                          if _qname(node.tag) == (OPF_NS, "spine")), None)
            if manifest is None or spine is None:
                raise CoverageError("opf_shape_invalid")
            items: dict[str, str] = {}
            for node in manifest:
                if _qname(node.tag) != (OPF_NS, "item"):
                    continue
                identifier = node.attrib.get("id", "")
                if not identifier or identifier in items:
                    raise CoverageError("opf_manifest_invalid")
                items[identifier] = _resolve_opf_href(
                    node.attrib.get("href", ""), names)
            ordered: list[tuple[str, bytes]] = []
            seen: set[str] = set()
            for node in spine:
                if _qname(node.tag) != (OPF_NS, "itemref"):
                    raise CoverageError("opf_spine_invalid")
                reference = node.attrib.get("idref", "")
                member = items.get(reference)
                if not member or member in seen:
                    raise CoverageError("opf_spine_invalid")
                seen.add(member)
                if SECTION_RE.fullmatch(member):
                    payload = archive.read(member)
                    if len(payload) > MAX_XML_BYTES:
                        raise CoverageError("section_too_large")
                    ordered.append((member, payload))
            physical = {name for name in names if SECTION_RE.fullmatch(name)}
            if (not ordered or len(ordered) > MAX_SECTIONS
                    or {name for name, _ in ordered} != physical):
                raise CoverageError("section_spine_invalid")
            return ordered, names
    except CoverageError:
        raise
    except (OSError, KeyError, RuntimeError, TypeError, ValueError,
            zipfile.BadZipFile, ET.ParseError):
        raise CoverageError("hwpx_invalid")


def section_equation_count(xml_bytes: bytes) -> int:
    """Count equations in one strict section, raising on ambiguous grammar."""
    if not isinstance(xml_bytes, bytes) or not xml_bytes or len(xml_bytes) > MAX_XML_BYTES:
        raise CoverageError("section_invalid")
    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, ValueError, TypeError):
        raise CoverageError("section_xml_invalid")
    if _qname(root.tag) != (SECTION_NS, "sec"):
        raise CoverageError("section_root_invalid")
    count = 0
    nodes = 0
    stack: list[tuple[ET.Element, tuple[str, str] | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        nodes += 1
        if nodes > MAX_XML_NODES:
            raise CoverageError("section_nodes_exceeded")
        namespace, local = _qname(node.tag)
        if local in {"equation", "script"} and namespace != PARAGRAPH_NS:
            raise CoverageError("equation_namespace_invalid")
        if ((namespace, local) == (PARAGRAPH_NS, "script")
                and parent != (PARAGRAPH_NS, "equation")):
            raise CoverageError("equation_script_orphan")
        if (namespace, local) == (PARAGRAPH_NS, "equation"):
            if parent != (PARAGRAPH_NS, "run"):
                raise CoverageError("equation_parent_invalid")
            direct_scripts = [child for child in node
                              if _qname(child.tag) == (PARAGRAPH_NS, "script")]
            all_scripts = [child for child in node.iter()
                           if child is not node
                           and _qname(child.tag) == (PARAGRAPH_NS, "script")]
            if len(direct_scripts) != 1 or len(all_scripts) != 1:
                raise CoverageError("equation_script_count_invalid")
            script = direct_scripts[0]
            if (len(node) != 1
                    or (node.text is not None and node.text.strip())
                    or (node.tail is not None and node.tail.strip())
                    or len(script) or script.attrib
                    or script.text is None or not script.text.strip()
                    or (script.tail is not None and script.tail.strip())
                    or len(script.text.encode("utf-8")) > MAX_SCRIPT_BYTES):
                raise CoverageError("equation_script_invalid")
            count += 1
            if count > MAX_EQUATIONS:
                raise CoverageError("equation_count_exceeded")
        children = list(node)
        qn = (namespace, local)
        stack.extend((child, qn) for child in reversed(children))
    return count


def _scan_bytes(data: bytes) -> dict[str, Any]:
    _validate_captured_package(data)
    sections, _ = _spine_sections(data)
    counts = [section_equation_count(payload) for _, payload in sections]
    total = sum(counts)
    if total > MAX_EQUATIONS:
        raise CoverageError("equation_count_exceeded")
    return {
        "schema": SCHEMA,
        "status": "analyzed",
        "source": {
            "format": "hwpx", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "scanner": SCANNER,
        "structure": {"state": "complete", "method": METHOD},
        "equations": {
            "count": total,
            "spine_ordinal_counts": counts,
            "script_semantics": "not_scanned",
        },
        "execution": {"state": "not_run"},
        "diagnostic_artifact": {"state": "none"},
        "native": {"state": "not_run"},
        "render": {"state": "not_run"},
        "comparison": {"state": "unknown"},
        "proof_grade": "none",
        "submission_grade": False,
    }


def _base_refusal(reason: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": "refused", "reason": reason,
            "proof_grade": "none", "submission_grade": False}


def inspect_path(path: str | Path) -> dict[str, Any]:
    try:
        source = _resolve_input_path(_coerce_path(path, "input_unavailable"))
        return _scan_bytes(_read_input_once(source))
    except CoverageError as exc:
        return _base_refusal(exc.reason)


def equation_presence(path: str | Path) -> bool:
    source = _resolve_input_path(_coerce_path(path, "input_unavailable"))
    return _scan_bytes(_read_input_once(source))["equations"]["count"] > 0


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _validate_receipt(path: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _TOP_KEYS:
        raise CoverageError("receipt_schema_invalid")
    source = payload.get("source")
    equations = payload.get("equations")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "analyzed"
            or payload.get("scanner") != SCANNER
            or payload.get("structure") != {"state": "complete", "method": METHOD}
            or payload.get("execution") != {"state": "not_run"}
            or payload.get("diagnostic_artifact") != {"state": "none"}
            or payload.get("native") != {"state": "not_run"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("comparison") != {"state": "unknown"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False):
        raise CoverageError("receipt_state_invalid")
    if (not isinstance(source, dict) or set(source) != {"format", "bytes", "sha256"}
            or source.get("format") != "hwpx"
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not isinstance(source.get("sha256"), str)
            or SHA256_RE.fullmatch(source["sha256"]) is None):
        raise CoverageError("receipt_source_invalid")
    if (not isinstance(equations, dict)
            or set(equations) != {"count", "spine_ordinal_counts", "script_semantics"}
            or equations.get("script_semantics") != "not_scanned"
            or isinstance(equations.get("count"), bool)
            or not isinstance(equations.get("count"), int)
            or equations["count"] < 0 or equations["count"] > MAX_EQUATIONS
            or not isinstance(equations.get("spine_ordinal_counts"), list)
            or not equations["spine_ordinal_counts"]
            or len(equations["spine_ordinal_counts"]) > MAX_SECTIONS
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in equations["spine_ordinal_counts"])
            or sum(equations["spine_ordinal_counts"]) != equations["count"]):
        raise CoverageError("receipt_equations_invalid")
    if path.name != "receipt.json" or RUN_ID_RE.fullmatch(path.parent.name or "") is None:
        raise CoverageError("receipt_layout_invalid")
    return payload


def _read_receipt(path: Path, *, allow_hardlink: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        info = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse
                or (not allow_hardlink and getattr(info, "st_nlink", 1) != 1)):
            raise CoverageError("receipt_invalid")
        raw = _core.read_regular_once(path, MAX_RECEIPT_BYTES, "receipt_invalid")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_closed)
    except CoverageError:
        raise
    except (_core.CoreError, OSError, UnicodeError, json.JSONDecodeError,
            TypeError, ValueError):
        raise CoverageError("receipt_invalid")
    _validate_receipt(path, payload)
    if raw != _json_bytes(payload):
        raise CoverageError("receipt_not_canonical")
    return payload, raw


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise CoverageError("run_id_invalid")
    return run_id


def _path_overlap(left: Path, right: Path) -> bool:
    try:
        left = left.expanduser().absolute()
        right = right.expanduser().absolute()
        return left == right or left in right.parents or right in left.parents
    except (OSError, RuntimeError, TypeError, ValueError):
        return True


def _public_run_layout(root: Path, run_id: str) -> tuple[Path, Path]:
    run_path = root / run_id
    try:
        info = run_path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse):
            raise CoverageError("receipt_layout_invalid")
        children = list(run_path.iterdir())
        if len(children) != 1 or children[0].name != "receipt.json":
            raise CoverageError("receipt_layout_invalid")
    except CoverageError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoverageError("receipt_layout_invalid")
    return run_path, run_path / "receipt.json"


def _publish(root: Path, guard: dict[str, Any], run_id: str,
             payload: dict[str, Any], source_path: Path, captured: bytes) -> dict[str, Any]:
    def publish_from_stage(temp_name: str) -> dict[str, Any]:
        stage = Path(temp_name) / "publish" / run_id
        stage.mkdir(parents=True)
        _core.write_bytes(stage / "receipt.json", _json_bytes(payload))

        def check(value: dict[str, Any], *, refresh: bool = False) -> None:
            _core.check_root_guard(value, refresh=refresh,
                                   node_identity_fn=_core.node_identity)

        def write(path: Path, data: bytes) -> None:
            _core.write_bytes(path, data, exists_reason="run_exists",
                              write_reason="diagnostic_publish_failed")

        def rollback(run_path, reserved, receipt, receipt_identity,
                     candidate, candidate_identity, token=None, token_identity=None):
            _core.rollback_publication(run_path, reserved, receipt, receipt_identity,
                                       candidate, candidate_identity, token, token_identity)

        def before_commit() -> None:
            try:
                rebound = _read_input_once(source_path)
                if rebound != captured or _scan_bytes(rebound) != payload:
                    raise CoverageError("input_changed")
            except CoverageError as exc:
                raise _core.CoreError(exc.reason)

        def final_commit() -> None:
            try:
                if _read_input_once(source_path) != captured:
                    raise CoverageError("input_changed")
            except CoverageError as exc:
                raise _core.CoreError(exc.reason)

        return _core.publish_owner_token_receipt(
            root / run_id, stage, payload, root_guard=guard,
            check_root_guard_fn=check, write_bytes_fn=write,
            node_identity_fn=_core.node_identity,
            same_identity_fn=_core.same_file_identity,
            remove_owned_fn=_core.remove_owned, rollback_fn=rollback,
            validate_receipt_fn=lambda path: _read_receipt(path, allow_hardlink=True),
            before_commit_fn=before_commit, final_commit_fn=final_commit,
            token_prefix=".t91-owner-")

    committed = False
    result: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=f".{ROOT_LEAF}-",
                                          dir=str(root.parent)) as temp:
            result = publish_from_stage(temp)
            committed = True
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)
    except OSError:
        if not committed:
            raise CoverageError("diagnostic_publish_failed")
    if result is None:
        raise CoverageError("diagnostic_publish_failed")
    return result


def inspect_and_publish(input_path: str | Path, *, diagnostic_root: str | Path,
                        run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(diagnostic_root, "diagnostic_root_invalid")
    source = _resolve_input_path(_coerce_path(input_path, "input_unavailable"))
    run_id = _validate_run_id(run_id)
    try:
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        if _path_overlap(root, source):
            raise CoverageError("input_root_overlap")
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard)
        captured = _read_input_once(source)
        payload = _scan_bytes(captured)
        _core.check_root_guard(guard)
        return _publish(root, guard, run_id, payload, source, captured)
    except CoverageError:
        raise
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)


def verify_path(input_path: str | Path, *, diagnostic_root: str | Path,
                run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(diagnostic_root, "diagnostic_root_invalid")
    source = _resolve_input_path(_coerce_path(input_path, "input_unavailable"))
    run_id = _validate_run_id(run_id)
    try:
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        if _path_overlap(root, source):
            raise CoverageError("input_root_overlap")
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard)
        run_path, receipt_path = _public_run_layout(root, run_id)
        run_identity = _core.node_identity(run_path)
        payload, raw = _read_receipt(receipt_path)
        receipt_identity = _core.node_identity(receipt_path)
        captured = _read_input_once(source)
        if _scan_bytes(captured) != payload:
            raise CoverageError("receipt_content_mismatch")
        if _read_input_once(source) != captured:
            raise CoverageError("input_changed")
        final_payload, final_raw = _read_receipt(receipt_path)
        final_run = _core.node_identity(run_path)
        final_receipt = _core.node_identity(receipt_path)
        if (final_payload != payload or final_raw != raw
                or not _core.same_file_identity(final_run, run_identity)
                or not _core.same_file_identity(final_receipt, receipt_identity)):
            raise CoverageError("receipt_changed")
        _core.check_root_guard(guard)
        if _read_input_once(source) != captured:
            raise CoverageError("input_changed")
        _core.check_root_guard(guard)
        last_payload, last_raw = _read_receipt(receipt_path)
        last_run = _core.node_identity(run_path)
        last_receipt = _core.node_identity(receipt_path)
        if (last_payload != payload or last_raw != raw
                or not _core.same_file_identity(last_run, run_identity)
                or not _core.same_file_identity(last_receipt, receipt_identity)):
            raise CoverageError("receipt_changed")
        return payload
    except CoverageError:
        raise
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoverageError("receipt_layout_invalid")


def _print(payload: dict[str, Any]) -> None:
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except (BrokenPipeError, OSError, UnicodeError):
        raise CoverageError("output_write_failed")


def build_parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(
        prog="hwp-equation-diagnostic",
        description="receipt-only opaque HWPX equation structural inventory")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="scan one HWPX and publish a receipt")
    inspect.add_argument("input")
    inspect.add_argument("--diagnostic-root", required=True)
    inspect.add_argument("--run-id", required=True)
    verify = sub.add_parser("verify", help="rebind a receipt to current source bytes")
    verify.add_argument("input")
    verify.add_argument("--diagnostic-root", required=True)
    verify.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    try:
        if args.command == "inspect":
            payload = inspect_and_publish(
                args.input, diagnostic_root=args.diagnostic_root, run_id=args.run_id)
        else:
            payload = verify_path(
                args.input, diagnostic_root=args.diagnostic_root, run_id=args.run_id)
        _print(payload)
        return EXIT_REFUSED
    except CoverageError as exc:
        try:
            _print(_base_refusal(exc.reason))
        except CoverageError:
            pass
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
