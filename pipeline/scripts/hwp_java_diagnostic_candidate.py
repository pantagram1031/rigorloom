"""Create and verify quarantined hwp2hwpx Java diagnostic candidates.

This lane is intentionally separate from canonical HWP ingress.  A successful
run proves only that one approved Java converter snapshot produced a bounded,
structurally valid HWPX package.  It never claims independent semantic parity,
render fidelity, native Hancom execution, or submission readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
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


SCHEMA = "rigorloom/hwp-java-diagnostic-candidate/v1"
LOCK_SCHEMA = "rigorloom/hwp-java-toolchain-lock/v1"
ADAPTER = "hwp2hwpx_java"
MAIN_CLASS = "Hwp2HwpxBridge"
RUNTIME_BINDING = "launcher_rehashed_runtime_unbound"
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
MAX_JAVA_BYTES = 64 * 1024 * 1024
MAX_TOOL_BYTES = 32 * 1024 * 1024
MAX_BRIDGE_BYTES = 1024 * 1024
MAX_LOCK_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 512 * 1024
REFERENCE_ROOT = Path(__file__).parents[1] / "references" / "hwp_java"
LOCK_PATH = REFERENCE_ROOT / "toolchain-lock.json"
EXPECTED_LOCK_SHA256 = "6be2ef8320f8987c7b8025682f4ede5e921cac3cfebc105f1c2fd5abc9f9a017"
EXPECTED_BRIDGE_SHA256 = "df8cf8df7e54e9aaec50817e817afe19f8d7e2c423ff2a043e60d2714d999245"
EXPECTED_TOOL_SHA256 = "06ba7071b9ee2f2256fa62398b5d32dc07496cb47cf764b4cf0b7c6119bd11cd"
ENV_OPTION_KEYS = {
    "CLASSPATH", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS",
}


class JavaDiagnosticError(Exception):
    """Expected fail-closed refusal carrying one stable reason token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _empty_source() -> dict[str, Any]:
    return {
        "format": "hwp", "version": None, "bytes": None,
        "sha256": None, "compressed": None, "security_flags": [],
    }


def _execution(
        state: str, *, exit_code: int | None = None,
        java_sha256: str | None = None, lock_sha256: str | None = None,
        bridge_sha256: str | None = None, tool_sha256: str | None = None,
        aux_rootfiles_pruned: int = 0,
) -> dict[str, Any]:
    if state != "succeeded":
        return {"state": state, "exit_code": exit_code}
    return {
        "state": "succeeded",
        "exit_code": 0,
        "java_launcher_sha256": java_sha256,
        "runtime_binding": RUNTIME_BINDING,
        "toolchain_lock_sha256": lock_sha256,
        "bridge_sha256": bridge_sha256,
        "main_class": MAIN_CLASS,
        "package_normalization": "zip_envelope_canonicalized",
        "missing_aux_rootfiles_pruned": aux_rootfiles_pruned,
        "classpath": [{"role": "hwp2hwpx_fat_jar", "sha256": tool_sha256}],
    }


def _base(*, status: str, reason: str,
          source: dict[str, Any] | None = None,
          execution: dict[str, Any] | None = None,
          output: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "adapter": ADAPTER,
        "source": source or _empty_source(),
        "execution": execution or _execution("not_run"),
        "comparison": {
            "state": "unknown", "method": "none",
            "reason": "independent_source_oracle_not_run",
        },
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
        "output": output or {"state": "none"},
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JavaDiagnosticError("json_duplicate_key")
        result[key] = value
    return result


def _read_json(path: Path, max_bytes: int, reason: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = _core.read_regular_once(path, max_bytes, reason)
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_closed)
    except JavaDiagnosticError:
        raise
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise JavaDiagnosticError(reason)
    if not isinstance(payload, dict):
        raise JavaDiagnosticError(reason)
    return payload, raw


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise JavaDiagnosticError("run_id_invalid")
    return value


def _validate_pin(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise JavaDiagnosticError("java_unpinned")
    value = value.casefold()
    if SHA256_RE.fullmatch(value) is None:
        raise JavaDiagnosticError("java_pin_invalid")
    return value


def _validate_timeout(value: float) -> float:
    try:
        return _ingress._validate_timeout(value)
    except (_ingress.IngressError, TypeError, ValueError, OverflowError):
        raise JavaDiagnosticError("timeout_invalid")


def _closed_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _closed_commit(value: Any) -> bool:
    return isinstance(value, str) and COMMIT_RE.fullmatch(value) is not None


def _validate_toolchain_shape(lock: dict[str, Any]) -> None:
    if set(lock) != {
            "schema", "adapter", "main_class", "runtime_binding", "bridge",
            "tool", "provenance"}:
        raise JavaDiagnosticError("toolchain_lock_invalid")
    if (lock.get("schema") != LOCK_SCHEMA or lock.get("adapter") != ADAPTER
            or lock.get("main_class") != MAIN_CLASS
            or lock.get("runtime_binding") != RUNTIME_BINDING):
        raise JavaDiagnosticError("toolchain_lock_invalid")
    bridge = lock.get("bridge")
    tool = lock.get("tool")
    provenance = lock.get("provenance")
    if (not isinstance(bridge, dict)
            or set(bridge) != {"path", "bytes", "sha256"}
            or bridge.get("path") != "Hwp2HwpxBridge.java"
            or isinstance(bridge.get("bytes"), bool)
            or not isinstance(bridge.get("bytes"), int)
            or not 0 < bridge["bytes"] <= MAX_BRIDGE_BYTES
            or not _closed_sha(bridge.get("sha256"))):
        raise JavaDiagnosticError("toolchain_lock_invalid")
    if (not isinstance(tool, dict)
            or set(tool) != {"filename", "bytes", "sha256", "coordinate"}
            or not isinstance(tool.get("filename"), str)
            or re.fullmatch(r"[A-Za-z0-9._-]+\.jar", tool["filename"]) is None
            or isinstance(tool.get("bytes"), bool)
            or not isinstance(tool.get("bytes"), int)
            or not 0 < tool["bytes"] <= MAX_TOOL_BYTES
            or not _closed_sha(tool.get("sha256"))
            or not isinstance(tool.get("coordinate"), str)
            or not tool["coordinate"]):
        raise JavaDiagnosticError("toolchain_lock_invalid")
    if (not isinstance(provenance, dict)
            or set(provenance) != {
                "hwp2hwpx_upstream_commit", "source_jar_sha256",
                "source_mapping", "embedded_hwplib", "embedded_hwpxlib"}
            or not _closed_commit(provenance.get("hwp2hwpx_upstream_commit"))
            or not _closed_sha(provenance.get("source_jar_sha256"))
            or provenance.get("source_mapping")
            != "project_sources_exact_embedded_dependency_classes_exact"):
        raise JavaDiagnosticError("toolchain_lock_invalid")
    for name in ("embedded_hwplib", "embedded_hwpxlib"):
        row = provenance.get(name)
        if (not isinstance(row, dict)
                or set(row) != {"coordinate", "jar_sha256", "upstream_commit"}
                or not isinstance(row.get("coordinate"), str)
                or not row["coordinate"]
                or not _closed_sha(row.get("jar_sha256"))
                or not _closed_commit(row.get("upstream_commit"))):
            raise JavaDiagnosticError("toolchain_lock_invalid")


def _load_toolchain() -> tuple[dict[str, Any], str, bytes]:
    lock, raw = _read_json(LOCK_PATH, MAX_LOCK_BYTES, "toolchain_lock_invalid")
    lock_digest = hashlib.sha256(raw).hexdigest()
    if lock_digest != EXPECTED_LOCK_SHA256:
        raise JavaDiagnosticError("toolchain_lock_invalid")
    _validate_toolchain_shape(lock)
    if (lock["bridge"]["sha256"] != EXPECTED_BRIDGE_SHA256
            or lock["tool"]["sha256"] != EXPECTED_TOOL_SHA256):
        raise JavaDiagnosticError("toolchain_lock_invalid")
    bridge_path = REFERENCE_ROOT / lock["bridge"]["path"]
    try:
        bridge = _core.read_regular_once(
            bridge_path, MAX_BRIDGE_BYTES, "toolchain_bridge_invalid")
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)
    if (len(bridge) != lock["bridge"]["bytes"]
            or hashlib.sha256(bridge).hexdigest() != lock["bridge"]["sha256"]):
        raise JavaDiagnosticError("toolchain_bridge_invalid")
    return lock, lock_digest, bridge


def _require_single_regular(path: Path, reason: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise JavaDiagnosticError(reason)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse
            or getattr(info, "st_nlink", 1) != 1):
        raise JavaDiagnosticError(reason)


def _read_snapshot(path: Path, max_bytes: int, reason: str) -> tuple[bytes, str]:
    _require_single_regular(path, reason)
    try:
        data = _core.read_regular_once(path, max_bytes, reason)
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)
    if not data:
        raise JavaDiagnosticError(reason)
    return data, hashlib.sha256(data).hexdigest()


def _hash_current(path: Path, max_bytes: int, reason: str) -> str:
    try:
        _require_single_regular(path, reason)
        return _core.hash_regular(path, max_bytes, reason)
    except (_core.CoreError, JavaDiagnosticError):
        raise JavaDiagnosticError(reason)


def _read_source(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.suffix.casefold() != ".hwp":
        raise JavaDiagnosticError("suffix_not_hwp")
    data, _digest = _read_snapshot(path, _ingress.MAX_INPUT_BYTES, "input_invalid")
    try:
        source = _ingress.parse_hwp_bytes(data)
    except _ingress.IngressError as exc:
        if exc.reason == "protected_properties":
            raise JavaDiagnosticError("protected_hwp")
        raise JavaDiagnosticError(exc.reason)
    return data, source.descriptor()


def _validate_hwpx_current(path: Path) -> dict[str, Any]:
    # Publication deliberately creates a temporary second hard link.  Reject
    # links at the public verify boundary, but accept the owned staged/linked
    # inode here while binding its full content identity before and after the
    # package validator.
    try:
        info = path.lstat()
    except OSError:
        raise JavaDiagnosticError("java_output_missing")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse):
        raise JavaDiagnosticError("hwpx_invalid")
    try:
        before = _core.node_identity(
            path, max_bytes=_ingress.MAX_HWPX_ARCHIVE_BYTES,
            reason="hwpx_invalid")
        result = _ingress._validate_hwpx(path)
        after = _core.node_identity(
            path, max_bytes=_ingress.MAX_HWPX_ARCHIVE_BYTES,
            reason="hwpx_invalid")
    except _ingress.IngressError as exc:
        if exc.reason == "hwpx_missing":
            raise JavaDiagnosticError("java_output_missing")
        raise JavaDiagnosticError("hwpx_invalid")
    except _core.CoreError:
        raise JavaDiagnosticError("hwpx_invalid")
    if not _core.same_file_identity(after, before):
        raise JavaDiagnosticError("hwpx_invalid")
    return result


def _closed_container_xml(data: bytes, members: set[str]) -> tuple[bytes, int]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise JavaDiagnosticError("hwpx_invalid")
    q_container = f"{{{_ingress._OCF_NS}}}container"
    q_rootfiles = f"{{{_ingress._OCF_NS}}}rootfiles"
    q_rootfile = f"{{{_ingress._OCF_NS}}}rootfile"
    if (root.tag != q_container or root.attrib
            or (root.text and root.text.strip())):
        raise JavaDiagnosticError("hwpx_invalid")
    children = list(root)
    if (len(children) != 1 or children[0].tag != q_rootfiles
            or children[0].attrib
            or (children[0].text and children[0].text.strip())):
        raise JavaDiagnosticError("hwpx_invalid")
    rootfiles = children[0]
    seen: set[tuple[str, str]] = set()
    pruned = 0
    for item in list(rootfiles):
        if (item.tag != q_rootfile or set(item.attrib) != {"full-path", "media-type"}
                or list(item) or (item.text and item.text.strip())
                or (item.tail and item.tail.strip())):
            raise JavaDiagnosticError("hwpx_invalid")
        row = (item.attrib["full-path"], item.attrib["media-type"])
        if row in seen:
            raise JavaDiagnosticError("hwpx_invalid")
        seen.add(row)
        if row == ("Contents/content.hpf", _ingress._HPF_MEDIA_TYPE):
            if row[0] not in members:
                raise JavaDiagnosticError("hwpx_invalid")
            continue
        if row not in _ingress._AUX_ROOTFILES:
            raise JavaDiagnosticError("hwpx_invalid")
        if row[0] not in members:
            rootfiles.remove(item)
            pruned += 1
    if ("Contents/content.hpf", _ingress._HPF_MEDIA_TYPE) not in seen:
        raise JavaDiagnosticError("hwpx_invalid")
    if pruned == 0:
        return data, 0
    ET.register_namespace("ocf", _ingress._OCF_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), pruned


def _safe_member_name(name: str) -> str:
    if "\\" in name:
        raise JavaDiagnosticError("hwpx_invalid")
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        raise JavaDiagnosticError("hwpx_invalid")
    parts = name.split("/")
    if (not name or name.startswith("/") or name.endswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\x00" in name):
        raise JavaDiagnosticError("hwpx_invalid")
    return name


def _validate_java_writer_envelope(
        data: bytes, archive: zipfile.ZipFile,
        infos: list[zipfile.ZipInfo]) -> None:
    """Accept only the exact descriptor envelope emitted by approved hwpxlib."""
    if archive.comment or not infos or infos[0].header_offset != 0:
        raise JavaDiagnosticError("hwpx_invalid")
    if any(info.flag_bits != 0x0808 or info.compress_type != zipfile.ZIP_DEFLATED
           or info.extra or info.comment for info in infos):
        raise JavaDiagnosticError("hwpx_invalid")
    ordered = sorted(infos, key=lambda row: row.header_offset)
    if ordered != infos:
        raise JavaDiagnosticError("hwpx_invalid")
    local_cursor = 0
    local_rows: dict[int, tuple[int, int, int]] = {}
    for info in infos:
        if info.header_offset != local_cursor or local_cursor + 30 > len(data):
            raise JavaDiagnosticError("hwpx_invalid")
        fields = struct.unpack_from("<IHHHHHIIIHH", data, local_cursor)
        (signature, needed, flags, method, mtime, mdate, crc, csize, usize,
         name_len, extra_len) = fields
        name_start = local_cursor + 30
        name_end = name_start + name_len
        raw_name = info.filename.encode("utf-8")
        if (signature != 0x04034B50 or flags != 0x0808
                or method != zipfile.ZIP_DEFLATED
                or crc != 0 or csize != 0 or usize != 0 or extra_len != 0
                or data[name_start:name_end] != raw_name):
            raise JavaDiagnosticError("hwpx_invalid")
        descriptor = name_end + info.compress_size
        if descriptor + 16 > len(data):
            raise JavaDiagnosticError("hwpx_invalid")
        descriptor_values = struct.unpack_from("<IIII", data, descriptor)
        if descriptor_values != (
                0x08074B50, info.CRC, info.compress_size, info.file_size):
            raise JavaDiagnosticError("hwpx_invalid")
        local_rows[info.header_offset] = (needed, mtime, mdate)
        local_cursor = descriptor + 16
    if local_cursor != archive.start_dir:
        raise JavaDiagnosticError("hwpx_invalid")

    central_cursor = archive.start_dir
    for info in infos:
        if central_cursor + 46 > len(data):
            raise JavaDiagnosticError("hwpx_invalid")
        fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", data, central_cursor)
        (signature, _made, needed, flags, method, mtime, mdate, crc, csize,
         usize, name_len, extra_len, comment_len, disk, _internal, _external,
         local_offset) = fields
        name_start = central_cursor + 46
        name_end = name_start + name_len
        if (signature != 0x02014B50 or flags != 0x0808
                or method != zipfile.ZIP_DEFLATED or crc != info.CRC
                or csize != info.compress_size or usize != info.file_size
                or extra_len != 0 or comment_len != 0 or disk != 0
                or local_offset != info.header_offset
                or data[name_start:name_end] != info.filename.encode("utf-8")
                or local_rows[local_offset] != (needed, mtime, mdate)):
            raise JavaDiagnosticError("hwpx_invalid")
        central_cursor = name_end
    central_size = central_cursor - archive.start_dir
    if central_cursor + 22 != len(data):
        raise JavaDiagnosticError("hwpx_invalid")
    eocd = struct.unpack_from("<IHHHHIIH", data, central_cursor)
    if eocd != (0x06054B50, 0, 0, len(infos), len(infos),
                central_size, archive.start_dir, 0):
        raise JavaDiagnosticError("hwpx_invalid")


def _validate_raw_tool_envelope(
        source: Path, data: bytes, archive: zipfile.ZipFile,
        infos: list[zipfile.ZipInfo]) -> None:
    if archive.comment:
        raise JavaDiagnosticError("hwpx_invalid")
    try:
        _ingress._validate_hwpx(source)
        return
    except _ingress.IngressError:
        pass
    # Permit the already-closed T85 physical form when the only remaining
    # defect is the OCF auxiliary declaration that this adapter documents and
    # repairs below.  Do not inherit the logical validator's permissiveness for
    # flags, comments, extras, or member ordering here.
    try:
        _ingress._validate_zip_physical(source, infos)
        first = min(infos, key=lambda row: row.header_offset)
        if (first.header_offset != 0 or first.filename != "mimetype"
                or first.compress_type != zipfile.ZIP_STORED
                or first.flag_bits != 0 or first.extra or first.comment):
            raise JavaDiagnosticError("hwpx_invalid")
        for info in infos:
            allowed = ({0} if info.compress_type == zipfile.ZIP_STORED
                       else {0, 0x4} if info.compress_type == zipfile.ZIP_DEFLATED
                       else set())
            if info.flag_bits not in allowed or info.extra or info.comment:
                raise JavaDiagnosticError("hwpx_invalid")
        return
    except JavaDiagnosticError:
        raise
    except _ingress.IngressError:
        pass
    _validate_java_writer_envelope(data, archive, infos)


def _normalize_tool_hwpx(source: Path, destination: Path) -> tuple[dict[str, Any], int]:
    """Repack the approved writer's ZIP envelope into the T85 closed form.

    hwpxlib currently emits a deflated, data-descriptor ``mimetype`` member.
    The XML/member payloads are retained exactly, but archive timestamps,
    flags, compression streams, and extras are replaced by a deterministic
    HWPX envelope before the independent T85 validator runs.
    """
    _require_single_regular(source, "hwpx_invalid")
    try:
        source_info = source.lstat()
        if not 0 < source_info.st_size <= _ingress.MAX_HWPX_ARCHIVE_BYTES:
            raise JavaDiagnosticError("hwpx_invalid")
        source_bytes = _core.read_regular_once(
            source, _ingress.MAX_HWPX_ARCHIVE_BYTES, "hwpx_invalid")
        captured_source = destination.with_name(".t87-captured-tool-output.hwpx")
        _core.write_bytes(
            captured_source, source_bytes, exists_reason="hwpx_invalid",
            write_reason="hwpx_invalid")
        captured_identity = _core.node_identity(
            captured_source, max_bytes=_ingress.MAX_HWPX_ARCHIVE_BYTES,
            reason="hwpx_invalid")
        rows: list[tuple[str, bytes]] = []
        folded: set[str] = set()
        total_compressed = 0
        total_uncompressed = 0
        with zipfile.ZipFile(captured_source) as archive:
            infos = archive.infolist()
            if not 0 < len(infos) <= _ingress.MAX_HWPX_MEMBERS:
                raise JavaDiagnosticError("hwpx_invalid")
            if min(info.header_offset for info in infos) != 0:
                raise JavaDiagnosticError("hwpx_invalid")
            _validate_raw_tool_envelope(
                captured_source, source_bytes, archive, infos)
            for info in infos:
                name = _safe_member_name(info.filename)
                if info.is_dir() or name.casefold() in folded:
                    raise JavaDiagnosticError("hwpx_invalid")
                folded.add(name.casefold())
                if (info.flag_bits & (0x1 | 0x20)
                        or info.compress_type not in {
                            zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        or info.file_size < 0
                        or info.file_size > _ingress.MAX_HWPX_MEMBER_BYTES):
                    raise JavaDiagnosticError("hwpx_invalid")
                total_compressed += info.compress_size
                total_uncompressed += info.file_size
                if (total_compressed > _ingress.MAX_HWPX_COMPRESSED_BYTES
                        or total_uncompressed
                        > _ingress.MAX_HWPX_TOTAL_UNCOMPRESSED
                        or (info.file_size and (
                            info.compress_size == 0
                            or info.file_size > info.compress_size
                            * _ingress.MAX_HWPX_COMPRESSION_RATIO))):
                    raise JavaDiagnosticError("hwpx_invalid")
                rows.append((name, archive.read(info)))
            if archive.testzip() is not None:
                raise JavaDiagnosticError("hwpx_invalid")
        data_by_name = {name: data for name, data in rows}
        if data_by_name.get("mimetype") != b"application/hwp+zip":
            raise JavaDiagnosticError("hwpx_invalid")
        container_name = "META-INF/container.xml"
        if container_name not in data_by_name:
            raise JavaDiagnosticError("hwpx_invalid")
        normalized_container, pruned = _closed_container_xml(
            data_by_name[container_name], set(data_by_name))
        with zipfile.ZipFile(destination, "x", allowZip64=False) as output:
            mimetype = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
            mimetype.compress_type = zipfile.ZIP_STORED
            mimetype.create_system = 0
            mimetype.external_attr = 0
            output.writestr(mimetype, data_by_name["mimetype"])
            for name, data in rows:
                if name == "mimetype":
                    continue
                if name == container_name:
                    data = normalized_container
                member = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                member.create_system = 0
                member.external_attr = 0
                output.writestr(member, data, compress_type=zipfile.ZIP_DEFLATED,
                                compresslevel=6)
        result = _validate_hwpx_current(destination)
        if not _core.remove_owned(captured_source, captured_identity):
            raise JavaDiagnosticError("hwpx_invalid")
        return result, pruned
    except JavaDiagnosticError:
        raise
    except _core.CoreError:
        raise JavaDiagnosticError("hwpx_invalid")
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile,
            zipfile.LargeZipFile):
        raise JavaDiagnosticError("hwpx_invalid")
    finally:
        if "captured_source" in locals() and captured_source.exists():
            _core.remove_owned(captured_source, locals().get("captured_identity"))


def _write_bytes(path: Path, data: bytes) -> None:
    try:
        _core.write_bytes(path, data)
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes(path, _json_bytes(payload))


def _core_node_identity(path: Path):
    try:
        return _core.node_identity(
            path, max_bytes=_ingress.MAX_HWPX_ARCHIVE_BYTES,
            reason="diagnostic_publish_failed")
    except _core.CoreError as exc:
        raise _core.CoreError(exc.reason)


def _remove_owned(path: Path, identity) -> bool:
    return _core.remove_owned(path, identity, node_identity_fn=_core_node_identity)


def _remove_owned_dir(path: Path, identity) -> None:
    _core.remove_owned_dir(path, identity, node_identity_fn=_core_node_identity)


def _rollback_publication(run_path: Path, reserved_identity,
                          receipt_target: Path, receipt_identity,
                          candidate_target: Path, candidate_identity,
                          token_target: Path | None = None,
                          token_identity=None) -> None:
    _core.rollback_publication(
        run_path, reserved_identity, receipt_target, receipt_identity,
        candidate_target, candidate_identity, token_target, token_identity,
        remove_owned_fn=_remove_owned, node_identity_fn=_core_node_identity,
        remove_owned_dir_fn=_remove_owned_dir)


def _prepare_root(path: Path) -> Path:
    try:
        return _core.prepare_root(path, expected_leaf="hwp-java-diagnostic")
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)


def _capture_root_guard(supplied: Path, resolved: Path) -> dict[str, Any]:
    try:
        return _core.capture_root_guard(
            supplied, resolved, node_identity_fn=_core_node_identity)
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)


def _check_root_guard(guard: dict[str, Any], *, refresh: bool = False) -> None:
    try:
        _core.check_root_guard(
            guard, refresh=refresh, node_identity_fn=_core_node_identity)
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)


def _validate_receipt_shape(payload: dict[str, Any], *, output: Path | None,
                            run_id: str | None) -> dict[str, Any]:
    if set(payload) != {
            "schema", "status", "reason", "adapter", "source", "execution",
            "comparison", "render", "proof_grade", "submission_grade", "output"}:
        raise JavaDiagnosticError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "candidate"
            or payload.get("reason") != "candidate_created"
            or payload.get("adapter") != ADAPTER
            or payload.get("comparison") != {
                "state": "unknown", "method": "none",
                "reason": "independent_source_oracle_not_run"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False):
        raise JavaDiagnosticError("receipt_state_invalid")
    source = payload.get("source")
    if (not isinstance(source, dict) or set(source) != {
            "format", "version", "bytes", "sha256", "compressed", "security_flags"}
            or source.get("format") != "hwp"
            or not isinstance(source.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", source["version"]) is None
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not _closed_sha(source.get("sha256"))
            or not isinstance(source.get("compressed"), bool)
            or source.get("security_flags") != []):
        raise JavaDiagnosticError("receipt_source_invalid")
    execution = payload.get("execution")
    if (not isinstance(execution, dict) or set(execution) != {
            "state", "exit_code", "java_launcher_sha256", "runtime_binding",
            "toolchain_lock_sha256", "bridge_sha256", "main_class",
            "package_normalization", "missing_aux_rootfiles_pruned", "classpath"}
            or execution.get("state") != "succeeded"
            or execution.get("exit_code") != 0
            or not _closed_sha(execution.get("java_launcher_sha256"))
            or execution.get("runtime_binding") != RUNTIME_BINDING
            or execution.get("package_normalization")
            != "zip_envelope_canonicalized"
            or isinstance(execution.get("missing_aux_rootfiles_pruned"), bool)
            or not isinstance(execution.get("missing_aux_rootfiles_pruned"), int)
            or not 0 <= execution["missing_aux_rootfiles_pruned"] <= 2
            or not _closed_sha(execution.get("toolchain_lock_sha256"))
            or not _closed_sha(execution.get("bridge_sha256"))
            or execution.get("main_class") != MAIN_CLASS
            or not isinstance(execution.get("classpath"), list)):
        raise JavaDiagnosticError("receipt_execution_invalid")
    if (len(execution["classpath"]) != 1
            or not isinstance(execution["classpath"][0], dict)
            or set(execution["classpath"][0]) != {"role", "sha256"}
            or execution["classpath"][0].get("role") != "hwp2hwpx_fat_jar"
            or not _closed_sha(execution["classpath"][0].get("sha256"))):
        raise JavaDiagnosticError("receipt_execution_invalid")
    # A caller-supplied digest only binds the Java launcher.  Converter
    # identity comes exclusively from the release-owned lock and bridge.
    lock, lock_sha256, _bridge = _load_toolchain()
    if (execution["toolchain_lock_sha256"] != lock_sha256
            or execution["bridge_sha256"] != lock["bridge"]["sha256"]
            or execution["classpath"][0]["sha256"] != lock["tool"]["sha256"]):
        raise JavaDiagnosticError("receipt_toolchain_mismatch")
    recorded = payload.get("output")
    if (not isinstance(recorded, dict) or set(recorded) != {
            "state", "path", "sha256", "bytes", "counts"}
            or recorded.get("state") != "quarantined"
            or run_id is None or recorded.get("path") != f"{run_id}/candidate.hwpx"
            or Path(recorded["path"]).is_absolute()
            or not _closed_sha(recorded.get("sha256"))
            or isinstance(recorded.get("bytes"), bool)
            or not isinstance(recorded.get("bytes"), int) or recorded["bytes"] <= 0):
        raise JavaDiagnosticError("receipt_output_invalid")
    counts = recorded.get("counts")
    if (not isinstance(counts, dict) or set(counts) != {
            "tables", "pictures", "equations"}
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in counts.values())):
        raise JavaDiagnosticError("receipt_output_invalid")
    if output is not None:
        try:
            actual = _validate_hwpx_current(output)
        except JavaDiagnosticError:
            raise JavaDiagnosticError("receipt_output_mismatch")
        if (actual["bytes"] != recorded["bytes"]
                or actual["sha256"] != recorded["sha256"]
                or actual["counts"] != counts):
            raise JavaDiagnosticError("receipt_output_mismatch")
    return payload


def _load_receipt(path: Path) -> dict[str, Any]:
    payload, _raw = _read_json(path, MAX_RECEIPT_BYTES, "receipt_invalid")
    return payload


def _child_environment(temp_dir: Path) -> dict[str, str]:
    result = dict(os.environ)
    for key in ENV_OPTION_KEYS:
        result.pop(key, None)
    for key in ("TMP", "TEMP", "TMPDIR", "HOME", "USERPROFILE"):
        result[key] = str(temp_dir)
    return result


def _run_child_capture(argv: list[str], *, timeout: float,
                       cwd: Path | None = None,
                       env: dict[str, str] | None = None):
    return _core.run_child_capture(
        argv, timeout=timeout, cwd=cwd, env=env,
        timeout_validator=_validate_timeout,
        max_output_bytes=_ingress.MAX_CHILD_OUTPUT_BYTES)


def _publish_pair(
        *, run_path: Path, publish_stage: Path, staged_candidate: Path,
        payload: dict[str, Any], run_id: str, root_guard: dict[str, Any],
        source_path: Path, staged_source: Path, source_sha256: str,
        java_path: Path, java_sha256: str, tool_path: Path,
        staged_tool: Path, tool_sha256: str, staged_bridge: Path,
        bridge_sha256: str, final_validated: dict[str, Any],
) -> dict[str, Any]:
    def check_guard(guard, *, refresh=False):
        try:
            _check_root_guard(guard, refresh=refresh)
        except JavaDiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def write_bytes(path: Path, data: bytes):
        try:
            _write_bytes(path, data)
        except JavaDiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def validate_receipt(receipt_target: Path, output: Path):
        try:
            _validate_receipt_shape(
                _load_receipt(receipt_target), output=output, run_id=run_id)
        except JavaDiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def before_candidate_link():
        try:
            if (_hash_current(source_path, _ingress.MAX_INPUT_BYTES, "source_changed")
                    != source_sha256
                    or _hash_current(staged_source, _ingress.MAX_INPUT_BYTES,
                                     "source_changed") != source_sha256):
                raise JavaDiagnosticError("source_changed")
            if (_hash_current(java_path, MAX_JAVA_BYTES, "java_drift") != java_sha256):
                raise JavaDiagnosticError("java_drift")
            if (_hash_current(tool_path, MAX_TOOL_BYTES, "tool_drift") != tool_sha256
                    or _hash_current(staged_tool, MAX_TOOL_BYTES,
                                     "tool_drift") != tool_sha256):
                raise JavaDiagnosticError("tool_drift")
            if (_hash_current(staged_bridge, MAX_BRIDGE_BYTES,
                              "toolchain_bridge_drift") != bridge_sha256):
                raise JavaDiagnosticError("toolchain_bridge_drift")
            if _validate_hwpx_current(staged_candidate) != final_validated:
                raise JavaDiagnosticError("java_output_drift")
            staged_candidate.chmod(0o400)
        except JavaDiagnosticError as exc:
            raise _core.CoreError(exc.reason)
        except OSError:
            raise _core.CoreError("diagnostic_publish_failed")

    try:
        return _core.publish_owner_token_pair(
            run_path, publish_stage, staged_candidate, payload,
            run_id=run_id, root_guard=root_guard,
            validate_receipt_fn=validate_receipt,
            before_candidate_link_fn=before_candidate_link,
            check_root_guard_fn=check_guard,
            write_bytes_fn=write_bytes,
            node_identity_fn=_core_node_identity,
            same_identity_fn=_core.same_file_identity,
            remove_owned_fn=_remove_owned,
            rollback_fn=_rollback_publication,
            token_prefix=".t87-owner-",
        )
    except _core.CoreError as exc:
        raise JavaDiagnosticError(exc.reason)


def run_diagnostic(input_path: str | Path, *, diagnostic_root: str | Path,
                   run_id: str, java: str | Path, java_sha256: str | None,
                   tool_jar: str | Path, timeout: float = 60.0) -> dict[str, Any]:
    source_descriptor: dict[str, Any] | None = None
    execution = _execution("not_run")
    try:
        run_id = _validate_run_id(run_id)
        pin = _validate_pin(java_sha256)
        timeout = _validate_timeout(timeout)
        lock, lock_sha256, bridge_data = _load_toolchain()
        source_path = Path(input_path)
        java_path = Path(java)
        tool_path = Path(tool_jar)
        supplied_root = Path(diagnostic_root)
        root = _prepare_root(supplied_root)
        root_guard = _capture_root_guard(supplied_root, root)
        _check_root_guard(root_guard)
        resolved = [source_path.expanduser().resolve(), java_path.expanduser().resolve(),
                    tool_path.expanduser().resolve(), root]
        if len({str(path).casefold() for path in resolved}) != len(resolved):
            raise JavaDiagnosticError("paths_not_distinct")
        run_path = root / run_id
        if run_path.exists():
            raise JavaDiagnosticError("run_exists")
        source_data, source_descriptor = _read_source(source_path)
        java_data, java_digest = _read_snapshot(
            java_path, MAX_JAVA_BYTES, "java_unavailable")
        execution = _execution("not_run")
        if java_digest != pin:
            raise JavaDiagnosticError("java_hash_mismatch")
        tool_data, tool_digest = _read_snapshot(
            tool_path, MAX_TOOL_BYTES, "tool_unavailable")
        if (tool_path.name != lock["tool"]["filename"]
                or len(tool_data) != lock["tool"]["bytes"]
                or tool_digest != lock["tool"]["sha256"]):
            raise JavaDiagnosticError("tool_hash_mismatch")
        with tempfile.TemporaryDirectory(prefix=".t87-", dir=str(root)) as temp:
            temp_dir = Path(temp)
            _check_root_guard(root_guard, refresh=True)
            staged_source = temp_dir / "input.hwp"
            staged_tool = temp_dir / "hwp2hwpx.jar"
            staged_bridge = temp_dir / "Hwp2HwpxBridge.java"
            raw_output = temp_dir / "tool-output.hwpx"
            staged_output = temp_dir / "candidate.hwpx"
            _write_bytes(staged_source, source_data)
            _write_bytes(staged_tool, tool_data)
            _write_bytes(staged_bridge, bridge_data)
            for path in (staged_source, staged_tool, staged_bridge):
                path.chmod(0o400)
            command = [
                str(java_path.resolve()), "-XX:-UsePerfData",
                "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
                "-Duser.language=en", "-Duser.country=US",
                "-Duser.timezone=UTC", "-Djava.io.tmpdir=" + str(temp_dir),
                "-Duser.home=" + str(temp_dir),
                "-Djava.util.prefs.userRoot=" + str(temp_dir / "prefs-user"),
                "-Djava.util.prefs.systemRoot=" + str(temp_dir / "prefs-system"),
                "-cp", str(staged_tool), str(staged_bridge), "convert",
                str(staged_source), str(raw_output),
            ]
            code, timed_out, overflow = _run_child_capture(
                command, timeout=timeout, cwd=temp_dir,
                env=_child_environment(temp_dir))
            if (type(code) is not int or type(timed_out) is not bool
                    or type(overflow) is not bool):
                raise JavaDiagnosticError("java_failed")
            execution = _execution("failed", exit_code=code)
            if timed_out:
                raise JavaDiagnosticError("java_timeout")
            if overflow:
                raise JavaDiagnosticError("java_output_too_large")
            if code != 0:
                raise JavaDiagnosticError("java_failed")
            validated, aux_pruned = _normalize_tool_hwpx(raw_output, staged_output)
            if (_hash_current(source_path, _ingress.MAX_INPUT_BYTES, "source_changed")
                    != source_descriptor["sha256"]
                    or _hash_current(staged_source, _ingress.MAX_INPUT_BYTES,
                                     "source_changed") != source_descriptor["sha256"]):
                raise JavaDiagnosticError("source_changed")
            if _hash_current(java_path, MAX_JAVA_BYTES, "java_drift") != pin:
                raise JavaDiagnosticError("java_drift")
            if (_hash_current(tool_path, MAX_TOOL_BYTES, "tool_drift") != tool_digest
                    or _hash_current(staged_tool, MAX_TOOL_BYTES,
                                     "tool_drift") != tool_digest):
                raise JavaDiagnosticError("tool_drift")
            if (_hash_current(staged_bridge, MAX_BRIDGE_BYTES,
                              "toolchain_bridge_drift") != lock["bridge"]["sha256"]):
                raise JavaDiagnosticError("toolchain_bridge_drift")

            publish_stage = temp_dir / "publish" / run_id
            publish_stage.mkdir(parents=True, exist_ok=False)
            staged_candidate = publish_stage / "candidate.hwpx"
            shutil.copyfile(staged_output, staged_candidate)
            final_validated = _validate_hwpx_current(staged_candidate)
            if final_validated != validated:
                raise JavaDiagnosticError("java_output_drift")
            output_record = {
                "state": "quarantined",
                "path": f"{run_id}/candidate.hwpx",
                "sha256": final_validated["sha256"],
                "bytes": final_validated["bytes"],
                "counts": final_validated["counts"],
            }
            execution = _execution(
                "succeeded", exit_code=0, java_sha256=pin,
                lock_sha256=lock_sha256,
                bridge_sha256=lock["bridge"]["sha256"],
                tool_sha256=tool_digest,
                aux_rootfiles_pruned=aux_pruned)
            payload = _base(
                status="candidate", reason="candidate_created",
                source=source_descriptor, execution=execution,
                output=output_record)
            _validate_receipt_shape(
                payload, output=staged_candidate, run_id=run_id)
            _write_receipt(publish_stage / "receipt.json", payload)
            return _publish_pair(
                run_path=run_path, publish_stage=publish_stage,
                staged_candidate=staged_candidate, payload=payload,
                run_id=run_id, root_guard=root_guard,
                source_path=source_path, staged_source=staged_source,
                source_sha256=source_descriptor["sha256"],
                java_path=java_path, java_sha256=pin,
                tool_path=tool_path, staged_tool=staged_tool,
                tool_sha256=tool_digest, staged_bridge=staged_bridge,
                bridge_sha256=lock["bridge"]["sha256"],
                final_validated=final_validated)
    except JavaDiagnosticError as exc:
        return _base(status="refused", reason=exc.reason,
                     source=source_descriptor, execution=execution)
    except (OSError, TypeError, ValueError, RuntimeError, _core.CoreError):
        return _base(status="refused", reason="diagnostic_io_failed",
                     source=source_descriptor, execution=execution)


def verify_diagnostic(diagnostic_root: str | Path, run_id: str) -> dict[str, Any]:
    try:
        run_id = _validate_run_id(run_id)
        supplied_root = Path(diagnostic_root)
        root = _prepare_root(supplied_root)
        guard = _capture_root_guard(supplied_root, root)
        _check_root_guard(guard)
        run_path = root / run_id
        try:
            root_info = root.lstat()
            run_info = run_path.lstat()
            entries = {entry.name for entry in run_path.iterdir()}
        except OSError:
            raise JavaDiagnosticError("receipt_invalid")
        if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
                or not stat.S_ISDIR(run_info.st_mode) or stat.S_ISLNK(run_info.st_mode)
                or entries != {"candidate.hwpx", "receipt.json"}):
            raise JavaDiagnosticError("receipt_layout_invalid")
        candidate = run_path / "candidate.hwpx"
        receipt_path = run_path / "receipt.json"
        _require_single_regular(candidate, "receipt_invalid")
        _require_single_regular(receipt_path, "receipt_invalid")
        return _validate_receipt_shape(
            _load_receipt(receipt_path), output=candidate, run_id=run_id)
    except JavaDiagnosticError as exc:
        return _base(status="refused", reason=exc.reason)
    except (OSError, TypeError, ValueError, RuntimeError, _core.CoreError):
        return _base(status="refused", reason="diagnostic_io_failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="quarantined hwp2hwpx Java HWP diagnostic candidate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="create one Java diagnostic candidate")
    run.add_argument("input")
    run.add_argument("--diagnostic-root", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--java", required=True)
    run.add_argument("--java-sha256", required=True)
    run.add_argument("--tool-jar", required=True)
    run.add_argument("--timeout", type=float, default=60.0)
    verify = sub.add_parser("verify", help="verify one Java diagnostic receipt")
    verify.add_argument("--diagnostic-root", required=True)
    verify.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        result = run_diagnostic(
            args.input, diagnostic_root=args.diagnostic_root,
            run_id=args.run_id, java=args.java,
            java_sha256=args.java_sha256, tool_jar=args.tool_jar,
            timeout=args.timeout)
    else:
        result = verify_diagnostic(args.diagnostic_root, args.run_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")))
    return 0 if result.get("status") == "candidate" else 3


if __name__ == "__main__":
    raise SystemExit(main())
