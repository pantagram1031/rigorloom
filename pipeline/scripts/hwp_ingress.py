#!/usr/bin/env python3
"""Fail-closed HWP5 ingress and explicitly selected HWPX adapters.

This module intentionally does not search raw bytes for ``FileHeader``.  HWP5
is an OLE/CFB v3 container; the header stream is located through the FAT,
mini-FAT and directory tree before its 256-byte HWP FileHeader is inspected.
The public JSON surface is deliberately small and contains no paths, document
text, stream names, command output, or raw control identifiers.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import posixpath
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Iterable
from xml.etree import ElementTree as ET


CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
HWP_SIGNATURE = b"HWP Document File"
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_HWPX_MEMBERS = 1024
MAX_HWPX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_HWPX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_HWPX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_HWPX_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
MAX_HWPX_COMPRESSION_RATIO = 100
MAX_MINIFAT_ENTRIES = MAX_INPUT_BYTES // 64
MAX_CHILD_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_CHAIN_SECTORS = 1_000_000
MAX_DIRECTORY_ENTRIES = 1_000_000
HWP_INGRESS_SCHEMA = "rigorloom/hwp-ingress/v1"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
_OCF_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF_NS = "http://www.idpf.org/2007/opf/"
_HPF_MEDIA_TYPE = "application/hwpml-package+xml"
_AUX_ROOTFILES = {
    ("Preview/PrvText.txt", "text/plain"),
    ("META-INF/container.rdf", "application/rdf+xml"),
}
_COM_THREAD_LOCK = threading.RLock()
_COM_MUTEX_STATE = threading.local()


class IngressError(Exception):
    """An expected fail-closed refusal with a stable, closed reason code."""

    def __init__(self, reason: str, message: str = "") -> None:
        self.reason = reason
        self.message = message or reason
        super().__init__(self.message)


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)) or not 0.1 <= float(value) <= 300.0:
        raise IngressError("timeout_invalid")
    return float(value)


@dataclass(frozen=True)
class _Source:
    data: bytes
    sha256: str
    version: str | None = None
    compressed: bool = False
    security_flags: tuple[str, ...] = ()

    def descriptor(self) -> dict[str, Any]:
        return {
            "format": "hwp",
            "version": self.version,
            "bytes": len(self.data),
            "sha256": self.sha256,
            "compressed": self.compressed,
            "security_flags": list(self.security_flags),
        }


@dataclass(frozen=True)
class _FileHeader:
    version: str
    compressed: bool
    security_flags: tuple[str, ...]
    stream: bytes


@dataclass(frozen=True)
class _DirectoryEntry:
    index: int
    name: str
    kind: int
    left: int
    right: int
    child: int
    start: int
    size: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hash a file once, with the same size bound as ingress reads."""
    target = Path(path)
    try:
        data = target.read_bytes()
    except (OSError, ValueError):
        raise IngressError("input_unavailable")
    if len(data) > MAX_INPUT_BYTES:
        raise IngressError("input_too_large")
    return sha256_bytes(data)


def _read_bounded(path: Path) -> bytes:
    if path.suffix.casefold() != ".hwp":
        raise IngressError("extension_not_hwp")
    try:
        data = path.read_bytes()
    except (OSError, ValueError):
        raise IngressError("input_unavailable")
    if len(data) > MAX_INPUT_BYTES:
        raise IngressError("input_too_large")
    return data


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


class _Cfb:
    """Bounded CFB v3 reader for the streams needed by HWP ingress."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        if len(data) < 512:
            raise IngressError("input_too_small")
        if data[:8] != CFB_SIGNATURE:
            raise IngressError("not_cfb")
        self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
        if struct.unpack_from("<H", data, 24)[0] != 0x003E or struct.unpack_from("<H", data, 26)[0] != 3:
            raise IngressError("cfb_version_unsupported")
        if struct.unpack_from("<H", data, 28)[0] != 0xFFFE:
            raise IngressError("cfb_byte_order_invalid")
        if self.sector_size != 512 or self.mini_sector_size != 64:
            raise IngressError("cfb_sector_size_unsupported")
        if (len(data) - 512) % self.sector_size:
            raise IngressError("cfb_trailing_bytes")
        self.sector_count = (len(data) - 512) // self.sector_size
        if self.sector_count <= 0 or self.sector_count > MAX_CHAIN_SECTORS:
            raise IngressError("cfb_size_invalid")
        self.num_dir_sectors = _u32(data, 40)
        self.num_fat_sectors = _u32(data, 44)
        self.first_dir_sector = _u32(data, 48)
        self.mini_cutoff = _u32(data, 56)
        self.first_mini_fat_sector = _u32(data, 60)
        self.num_mini_fat_sectors = _u32(data, 64)
        self.first_difat_sector = _u32(data, 68)
        self.num_difat_sectors = _u32(data, 72)
        if self.num_dir_sectors != 0:
            raise IngressError("cfb_directory_sectors_unsupported")
        if self.mini_cutoff != 4096:
            raise IngressError("cfb_mini_cutoff_invalid")
        self._allocated: dict[int, str] = {}
        self._mini_allocated: dict[int, str] = {}
        self._stream_chains: dict[int, list[int]] = {}
        self.fat_sector_ids = self._read_difat()
        self._claim("difat", getattr(self, "difat_sector_ids", []))
        self._claim("fat", self.fat_sector_ids)
        self.fat = self._read_fat(self.fat_sector_ids)
        self._validate_sector_markers()
        self.directory = self._read_directory()
        self._validate_tree()
        self._validate_hwp_structure()
        self.root = next((x for x in self.directory if x.kind == 5), None)
        if self.root is None:
            raise IngressError("root_missing")
        self.minifat = self._read_minifat()
        self.ministream = self._read_regular(self.root.start, self.root.size,
                                             role="root_mini_stream")
        self._validate_stream_allocations()

    def _validate_sector_markers(self) -> None:
        for sid in self.fat_sector_ids:
            if self.fat[sid] != FATSECT:
                raise IngressError("fat_marker_invalid")
        for sid in getattr(self, "difat_sector_ids", []):
            if self.fat[sid] != DIFSECT:
                raise IngressError("difat_marker_invalid")

    def _claim(self, role: str, sectors: Iterable[int]) -> None:
        for sid in sectors:
            previous = self._allocated.get(sid)
            if previous is not None:
                raise IngressError("cfb_sector_overlap")
            self._allocated[sid] = role

    def _claim_mini(self, role: str, sectors: Iterable[int]) -> None:
        for sid in sectors:
            previous = self._mini_allocated.get(sid)
            if previous is not None:
                raise IngressError("minifat_sector_overlap")
            self._mini_allocated[sid] = role

    def _sector(self, sid: int) -> bytes:
        if sid < 0 or sid >= self.sector_count:
            raise IngressError("cfb_sector_out_of_range")
        start = 512 + sid * self.sector_size
        end = start + self.sector_size
        if end > len(self.data):
            raise IngressError("cfb_sector_truncated")
        return self.data[start:end]

    def _read_difat(self) -> list[int]:
        ids: list[int] = []
        for i in range(109):
            sid = _u32(self.data, 76 + 4 * i)
            if sid == FREESECT:
                continue
            if sid in (ENDOFCHAIN, FATSECT, DIFSECT):
                raise IngressError("fat_header_count_invalid")
            ids.append(sid)
        if len(ids) > self.num_fat_sectors:
            raise IngressError("fat_header_count_invalid")
        current = self.first_difat_sector
        seen: set[int] = set()
        entries_per = self.sector_size // 4 - 1
        difat_ids: list[int] = []
        for _ in range(self.num_difat_sectors):
            if current in (FREESECT, ENDOFCHAIN) or current in seen:
                raise IngressError("difat_chain_invalid")
            seen.add(current)
            difat_ids.append(current)
            raw = self._sector(current)
            for i in range(entries_per):
                sid = _u32(raw, 4 * i)
                if sid == FREESECT:
                    continue
                if sid in (ENDOFCHAIN, FATSECT, DIFSECT):
                    raise IngressError("difat_chain_invalid")
                ids.append(sid)
            current = _u32(raw, self.sector_size - 4)
        if self.num_difat_sectors == 0 and self.first_difat_sector != ENDOFCHAIN:
            raise IngressError("difat_header_invalid")
        if current != ENDOFCHAIN:
            raise IngressError("difat_chain_invalid")
        if len(ids) != self.num_fat_sectors:
            raise IngressError("fat_header_count_invalid")
        if len(set(ids)) != len(ids) or any(x >= self.sector_count for x in ids):
            raise IngressError("fat_sector_invalid")
        self.difat_sector_ids = difat_ids
        return ids

    def _read_fat(self, sector_ids: list[int]) -> list[int]:
        values: list[int] = []
        for sid in sector_ids:
            values.extend(struct.unpack("<%dI" % (self.sector_size // 4), self._sector(sid)))
        if len(values) < self.sector_count:
            raise IngressError("fat_incomplete")
        return values[: self.sector_count]

    def _chain(self, start: int, table: list[int], *, max_count: int | None = None) -> list[int]:
        if start in (FREESECT, ENDOFCHAIN):
            return []
        limit = max_count or min(MAX_CHAIN_SECTORS, len(table) + 1)
        current = start
        result: list[int] = []
        seen: set[int] = set()
        while current != ENDOFCHAIN:
            if current == FREESECT:
                # FREESECT marks an unallocated sector, never the terminator
                # of a live directory/FAT/mini-FAT chain.
                raise IngressError("cfb_chain_unterminated")
            if current in (FATSECT, DIFSECT):
                raise IngressError("cfb_sector_overlap")
            if current < 0 or current >= len(table) or current in seen:
                raise IngressError("cfb_chain_invalid")
            if len(result) >= limit:
                raise IngressError("cfb_chain_too_long")
            seen.add(current)
            result.append(current)
            current = table[current]
        return result

    def _read_regular(self, start: int, size: int, *, role: str | None = None) -> bytes:
        if size == 0:
            return b""
        if size > MAX_INPUT_BYTES:
            raise IngressError("stream_too_large")
        required = (size + self.sector_size - 1) // self.sector_size
        chain = self._chain(start, self.fat, max_count=required)
        if len(chain) < required:
            raise IngressError("cfb_chain_short")
        if len(chain) > required:
            raise IngressError("cfb_chain_overallocated")
        if role is not None:
            self._claim(role, chain)
        return b"".join(self._sector(i) for i in chain)[:size]

    def _read_directory(self) -> list[_DirectoryEntry]:
        chain = self._chain(self.first_dir_sector, self.fat)
        if not chain:
            raise IngressError("directory_missing")
        raw = b"".join(self._sector(i) for i in chain)
        if self.num_dir_sectors and len(chain) != self.num_dir_sectors:
            raise IngressError("directory_chain_count")
        self._claim("directory", chain)
        if len(raw) % 128:
            raise IngressError("directory_alignment")
        entries: list[_DirectoryEntry] = []
        for offset in range(0, len(raw), 128):
            if len(entries) >= MAX_DIRECTORY_ENTRIES:
                raise IngressError("directory_too_large")
            item = raw[offset:offset + 128]
            nlen = struct.unpack_from("<H", item, 64)[0]
            if nlen == 0:
                # Directory SIDs are positional.  Keep unused slots so a
                # pointer to a later entry is never accidentally remapped by
                # compacting the stream.
                entries.append(_DirectoryEntry(
                    len(entries), "", 0, FREESECT, FREESECT, FREESECT,
                    ENDOFCHAIN, 0))
                continue
            if nlen < 2 or nlen > 64 or nlen % 2:
                raise IngressError("directory_name_invalid")
            if item[nlen - 2:nlen] != b"\x00\x00":
                raise IngressError("directory_name_invalid")
            try:
                name = item[: nlen - 2].decode("utf-16le")
            except UnicodeDecodeError:
                raise IngressError("directory_name_invalid")
            entries.append(_DirectoryEntry(
                len(entries), name, item[66], _u32(item, 68), _u32(item, 72),
                _u32(item, 76), _u32(item, 116), _u64(item, 120)))
        roots = [entry.index for entry in entries if entry.kind == 5]
        if roots != [0]:
            raise IngressError("root_invalid" if roots else "root_missing")
        if any(e.size > MAX_INPUT_BYTES for e in entries):
            raise IngressError("stream_too_large")
        return entries

    def _validate_tree(self) -> None:
        entries = self.directory
        nulls = {FREESECT, ENDOFCHAIN}
        for entry in entries:
            for pointer in (entry.left, entry.right, entry.child):
                if pointer not in nulls and pointer >= len(entries):
                    raise IngressError("directory_pointer_invalid")
            if entry.kind not in (0, 1, 2, 5):
                raise IngressError("directory_type_invalid")
        reachable: set[int] = {0}

        def walk_tree(index: int, active: set[int]) -> None:
            if index in nulls:
                return
            if index in active or index in reachable:
                raise IngressError("directory_tree_cycle")
            active.add(index)
            reachable.add(index)
            node = entries[index]
            walk_tree(node.left, active)
            walk_tree(node.right, active)
            active.remove(index)

        def walk_storage(index: int, active: set[int]) -> None:
            if index in nulls:
                return
            if index in active:
                raise IngressError("directory_tree_cycle")
            active.add(index)
            walk_tree(index, set())
            for child in self._tree_nodes(index):
                if entries[child].kind == 1:
                    walk_storage(entries[child].child, active)
            active.remove(index)

        walk_storage(entries[0].child, set())
        unreachable = [entry.index for entry in entries
                       if entry.kind != 0 and entry.index not in reachable]
        if unreachable:
            raise IngressError("directory_unreachable")

    def _validate_hwp_structure(self) -> None:
        """Require the minimum direct-root HWP storage contract."""
        root_children = [self.directory[index]
                         for index in self._tree_nodes(self.directory[0].child)]
        docinfo = [entry for entry in root_children
                   if entry.name.casefold() == "docinfo" and entry.kind == 2]
        bodytext = [entry for entry in root_children
                    if entry.name.casefold() == "bodytext"]
        if len(docinfo) != 1:
            raise IngressError("docinfo_missing" if not docinfo else "docinfo_ambiguous")
        if len(bodytext) != 1:
            raise IngressError("bodytext_missing" if not bodytext else "bodytext_ambiguous")
        body = bodytext[0]
        if body.kind != 1:
            raise IngressError("bodytext_not_storage")
        sections = [self.directory[index] for index in self._tree_nodes(body.child)
                    if self.directory[index].kind == 2
                    and re.fullmatch(r"section\d+", self.directory[index].name.casefold())]
        if not sections:
            raise IngressError("bodytext_sections_missing")

    def _tree_nodes(self, index: int) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()

        def visit(i: int) -> None:
            if i in (FREESECT, ENDOFCHAIN):
                return
            if i in seen:
                raise IngressError("directory_tree_cycle")
            seen.add(i)
            node = self.directory[i]
            visit(node.left)
            result.append(i)
            visit(node.right)

        visit(index)
        return result

    def _read_minifat(self) -> list[int]:
        if self.num_mini_fat_sectors == 0:
            if self.first_mini_fat_sector not in (FREESECT, ENDOFCHAIN):
                raise IngressError("minifat_header_invalid")
            return []
        if self.first_mini_fat_sector in (FREESECT, ENDOFCHAIN):
            raise IngressError("minifat_missing")
        chain = self._chain(self.first_mini_fat_sector, self.fat,
                            max_count=self.num_mini_fat_sectors + 1)
        if len(chain) != self.num_mini_fat_sectors:
            raise IngressError("minifat_chain_count")
        self._claim("minifat", chain)
        values: list[int] = []
        for sid in chain:
            values.extend(struct.unpack("<%dI" % (self.sector_size // 4), self._sector(sid)))
        if len(values) > MAX_MINIFAT_ENTRIES:
            raise IngressError("minifat_too_large")
        return values

    def _validate_stream_allocations(self) -> None:
        """Claim every reachable stream's chain before reading FileHeader.

        CFB permits no sector aliasing between FAT, directory, mini-FAT,
        root mini-stream, or stream chains.  Validating all directory streams
        also catches a decoy that aliases the real FileHeader mini sectors.
        """
        for entry in self.directory:
            if entry.kind != 2 or entry.size == 0:
                continue
            if entry.size < self.mini_cutoff:
                if not self.minifat or not self.ministream:
                    raise IngressError("ministream_missing")
                chain = self._chain(entry.start, self.minifat,
                                    max_count=(entry.size + self.mini_sector_size - 1) // self.mini_sector_size)
                required = (entry.size + self.mini_sector_size - 1) // self.mini_sector_size
                if len(chain) < required:
                    raise IngressError("minifat_chain_short")
                if len(chain) > required:
                    raise IngressError("minifat_chain_overallocated")
                if len(chain) * self.mini_sector_size > len(self.ministream):
                    raise IngressError("ministream_chain_invalid")
                self._claim_mini(f"stream:{entry.index}", chain)
            else:
                chain = self._chain(entry.start, self.fat,
                                    max_count=(entry.size + self.sector_size - 1) // self.sector_size)
                required = (entry.size + self.sector_size - 1) // self.sector_size
                if len(chain) < required:
                    raise IngressError("cfb_chain_short")
                if len(chain) > required:
                    raise IngressError("cfb_chain_overallocated")
                self._claim(f"stream:{entry.index}", chain)
            self._stream_chains[entry.index] = chain
        self._validate_allocation_closure()

    def _validate_allocation_closure(self) -> None:
        """Reject orphan FAT/mini-FAT allocations and bad live markers."""
        for sid, marker in enumerate(self.fat):
            role = self._allocated.get(sid)
            if role is None:
                if marker != FREESECT:
                    raise IngressError("cfb_orphan_allocation")
                continue
            if role == "fat":
                if marker != FATSECT:
                    raise IngressError("fat_marker_invalid")
                continue
            if role == "difat":
                if marker != DIFSECT:
                    raise IngressError("difat_marker_invalid")
                continue
            if marker != ENDOFCHAIN and (marker in (FREESECT, FATSECT, DIFSECT)
                                         or marker >= self.sector_count):
                raise IngressError("cfb_chain_invalid")
        mini_capacity = (len(self.ministream) + self.mini_sector_size - 1) // self.mini_sector_size
        for mini_sid in range(mini_capacity):
            marker = self.minifat[mini_sid] if mini_sid < len(self.minifat) else FREESECT
            if mini_sid not in self._mini_allocated:
                if marker != FREESECT:
                    raise IngressError("minifat_orphan_allocation")
            elif marker != ENDOFCHAIN and (marker in (FREESECT, FATSECT, DIFSECT)
                                           or marker >= len(self.minifat)):
                raise IngressError("minifat_chain_invalid")
        if any(marker != FREESECT for marker in self.minifat[mini_capacity:]):
            raise IngressError("minifat_orphan_allocation")

    def stream(self, entry: _DirectoryEntry) -> bytes:
        if entry.kind != 2:
            raise IngressError("fileheader_not_stream")
        if entry.size < self.mini_cutoff:
            if not self.minifat or not self.ministream:
                raise IngressError("ministream_missing")
            chain = self._stream_chains.get(entry.index) or self._chain(
                entry.start, self.minifat,
                max_count=(entry.size + self.mini_sector_size - 1) // self.mini_sector_size)
            if len(chain) * self.mini_sector_size < entry.size:
                raise IngressError("minifat_chain_short")
            end = len(chain) * self.mini_sector_size
            if end > len(self.ministream):
                raise IngressError("ministream_chain_invalid")
            return b"".join(self.ministream[i * self.mini_sector_size:(i + 1) * self.mini_sector_size]
                            for i in chain)[:entry.size]
        chain = self._stream_chains.get(entry.index)
        if chain is not None:
            return b"".join(self._sector(i) for i in chain)[:entry.size]
        return self._read_regular(entry.start, entry.size, role=f"stream:{entry.index}")

    def fileheader(self) -> _FileHeader:
        # HWP's FileHeader is a direct child of the CFB root storage.  A
        # nested stream carrying the same name is not the document header and
        # must not be promoted by a recursive or raw byte search.
        names = [entry for index in self._tree_nodes(self.root.child)
                 for entry in (self.directory[index],)
                 if entry.kind == 2 and entry.name.casefold() == "fileheader"]
        if len(names) != 1:
            raise IngressError("fileheader_ambiguous" if len(names) > 1 else "fileheader_missing")
        stream = self.stream(names[0])
        if len(stream) != 256:
            raise IngressError("fileheader_size_invalid")
        if stream[: len(HWP_SIGNATURE)] != HWP_SIGNATURE:
            raise IngressError("fileheader_signature_invalid")
        if any(stream[len(HWP_SIGNATURE):32]):
            raise IngressError("fileheader_signature_invalid")
        version_word = _u32(stream, 32)
        version_bytes = struct.pack("<I", version_word)
        major, minor, patch, build = version_bytes[3], version_bytes[2], version_bytes[1], version_bytes[0]
        if major != 5 or minor not in (0, 1):
            raise IngressError("hwp_version_unsupported")
        version = f"{major}.{minor}.{patch}.{build}"
        properties = _u32(stream, 36)
        if properties & 1 == 0:
            compressed = False
        else:
            compressed = True
        if properties & ~1:
            flags: list[str] = []
            names_by_bit = {
                1: "password", 2: "distributable", 3: "script", 4: "drm",
                5: "certificate", 6: "privacy_security", 7: "reserved",
            }
            for bit in range(1, 32):
                if properties & (1 << bit):
                    flags.append(names_by_bit.get(bit, "reserved"))
            raise IngressError("protected_properties")
        return _FileHeader(version, compressed, (), stream)


def parse_hwp_bytes(data: bytes) -> _Source:
    if len(data) > MAX_INPUT_BYTES:
        raise IngressError("input_too_large")
    cfb = _Cfb(data)
    fh = cfb.fileheader()
    return _Source(data, sha256_bytes(data), fh.version, fh.compressed, fh.security_flags)


def _base_manifest(*, status: str, reason: str,
                   source: _Source | None = None,
                   adapter: str | None = None,
                   execution: dict[str, Any] | None = None,
                   comparison: dict[str, Any] | None = None,
                   output: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": HWP_INGRESS_SCHEMA,
        "status": status,
        "reason": reason,
        "source": source.descriptor() if source else {
            "format": "hwp", "version": None, "bytes": None,
            "sha256": None, "compressed": None, "security_flags": [],
        },
        "execution": execution or {"state": "not_run", "adapter": adapter},
        "comparison": comparison or {"state": "unknown"},
        "output": output or {"state": "none"},
        "proof_grade": "none",
    }


def inspect_path(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        source = parse_hwp_bytes(_read_bounded(target))
    except IngressError as exc:
        return _base_manifest(status="refused", reason=exc.reason)
    return _base_manifest(status="candidate", reason="candidate", source=source)


# Stable import aliases for callers that prefer verb-named APIs.
inspect_hwp = inspect_path
inspect_bytes = parse_hwp_bytes


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_manifest(path: Path, payload: dict[str, Any]) -> tuple[int, int]:
    if path.exists():
        raise IngressError("manifest_exists")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise IngressError("manifest_write_failed")
    created_identity: tuple[int, int] | None = None
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            stat = os.fstat(fd)
            created_identity = (getattr(stat, "st_dev", 0), getattr(stat, "st_ino", 0))
        except OSError:
            created_identity = None
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(payload))
            stream.flush()
            os.fsync(stream.fileno())
        if created_identity is None:
            raise IngressError("manifest_write_failed")
        return created_identity
    except FileExistsError:
        raise IngressError("manifest_exists")
    except OSError:
        if created_identity is not None:
            try:
                current = path.stat()
                if (getattr(current, "st_dev", 0), getattr(current, "st_ino", 0)) == created_identity:
                    path.unlink()
            except OSError:
                pass
        raise IngressError("manifest_write_failed")


def _remove_identity(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        current = path.stat()
        current_identity = (getattr(current, "st_dev", 0), getattr(current, "st_ino", 0))
        if current_identity == identity:
            path.unlink()
    except OSError:
        pass


def _validate_distinct(input_path: Path, out: Path | None, manifest: Path | None) -> None:
    paths = [input_path.resolve()]
    for value in (out, manifest):
        if value is None:
            continue
        if value.suffix.casefold() == ".hwp" and value.resolve() == input_path.resolve():
            raise IngressError("source_output_same")
        if value.resolve() in paths:
            raise IngressError("source_manifest_same")
        paths.append(value.resolve())
    if out is not None and out.suffix.casefold() != ".hwpx":
        raise IngressError("output_not_hwpx")


def _drain(pipe, bucket: list[bytes], overflow: list[bool], stop: threading.Event) -> None:
    total = 0
    try:
        while not stop.is_set():
            chunk = pipe.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if total > MAX_CHILD_OUTPUT_BYTES:
                overflow[0] = True
                stop.set()
                return
            bucket.append(chunk)
    except OSError:
        return


def _run_child_capture(argv: list[str], *, timeout: float) -> tuple[int, bool, bool, bytes, bytes]:
    timeout = _validate_timeout(timeout)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, ValueError):
        return -1, False, False, b"", b""
    stdout: list[bytes] = []
    stderr: list[bytes] = []
    overflow = [False]
    stop = threading.Event()
    threads = [threading.Thread(target=_drain, args=(proc.stdout, stdout, overflow, stop), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, stderr, overflow, stop), daemon=True)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + max(0.1, min(float(timeout), 300.0))
    timed_out = False
    while proc.poll() is None:
        if overflow[0]:
            proc.kill()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.01)
    try:
        code = proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = -1
    stop.set()
    for thread in threads:
        thread.join(timeout=1)
    return code, timed_out, overflow[0], b"".join(stdout), b"".join(stderr)


def _run_child(argv: list[str], *, timeout: float) -> tuple[int, bool, bool]:
    code, timed_out, overflow, _, _ = _run_child_capture(argv, timeout=timeout)
    return code, timed_out, overflow


def _validate_zip_physical(path: Path, infos: list[zipfile.ZipInfo]) -> None:
    """Require one gap-free classic ZIP envelope with matching local records.

    ``zipfile`` intentionally tolerates prepended bytes, orphan local records,
    and post-EOCD trailers.  A canonical HWPX must not: every physical local
    record is named by the central directory, the local records are contiguous
    from byte zero to the central directory, and the EOCD/comment ends at EOF.
    ZIP64 and data descriptors are outside the bounded T85 envelope.
    """
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_HWPX_ARCHIVE_BYTES:
            raise IngressError("hwpx_archive_size_invalid")
        data = path.read_bytes()
    except IngressError:
        raise
    except OSError:
        raise IngressError("hwpx_invalid")
    search_start = max(0, len(data) - (0xFFFF + 22))
    eocd = data.rfind(b"PK\x05\x06", search_start)
    if eocd < 0 or eocd + 22 > len(data):
        raise IngressError("hwpx_physical_invalid")
    try:
        (signature, disk_no, central_disk, disk_entries, total_entries,
         central_size, central_offset, comment_len) = struct.unpack_from(
            "<IHHHHIIH", data, eocd)
    except struct.error:
        raise IngressError("hwpx_physical_invalid")
    if (signature != 0x06054B50 or disk_no != 0 or central_disk != 0
            or disk_entries != total_entries or total_entries != len(infos)
            or total_entries == 0 or total_entries == 0xFFFF
            or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF
            or central_offset + central_size != eocd
            or eocd + 22 + comment_len != len(data)):
        raise IngressError("hwpx_physical_invalid")

    central_rows: dict[int, tuple[int, int, int, int, int, int, int, bytes]] = {}
    cursor = central_offset
    for info in infos:
        if cursor + 46 > eocd:
            raise IngressError("hwpx_physical_invalid")
        try:
            fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", data, cursor)
        except struct.error:
            raise IngressError("hwpx_physical_invalid")
        (central_sig, _made_by, needed, flags, method, mtime, mdate, crc,
         csize, usize, name_len, extra_len, member_comment_len, disk_start,
         _internal_attr, _external_attr, local_offset) = fields
        end = cursor + 46 + name_len + extra_len + member_comment_len
        if end > eocd:
            raise IngressError("hwpx_physical_invalid")
        name = data[cursor + 46:cursor + 46 + name_len]
        try:
            expected_name = info.filename.encode("ascii")
        except UnicodeEncodeError:
            raise IngressError("hwpx_member_invalid")
        if (central_sig != 0x02014B50 or flags != info.flag_bits
                or method != info.compress_type or crc != info.CRC
                or csize != info.compress_size or usize != info.file_size
                or local_offset != info.header_offset or name != expected_name
                or extra_len != 0 or member_comment_len != 0 or disk_start != 0
                or info.extra or info.comment):
            raise IngressError("hwpx_physical_invalid")
        if local_offset in central_rows:
            raise IngressError("hwpx_physical_invalid")
        central_rows[local_offset] = (
            needed, flags, method, mtime, mdate, crc, csize, name)
        cursor = end
    if cursor != eocd:
        raise IngressError("hwpx_physical_invalid")

    local_cursor = 0
    for local_offset in sorted(central_rows):
        if local_offset != local_cursor or local_offset + 30 > central_offset:
            raise IngressError("hwpx_physical_invalid")
        try:
            local = struct.unpack_from("<IHHHHHIIIHH", data, local_offset)
        except struct.error:
            raise IngressError("hwpx_physical_invalid")
        (local_sig, needed, flags, method, mtime, mdate, crc, csize, usize,
         name_len, extra_len) = local
        expected = central_rows[local_offset]
        name_start = local_offset + 30
        data_start = name_start + name_len + extra_len
        name = data[name_start:name_start + name_len]
        if (local_sig != 0x04034B50 or extra_len != 0
                or (needed, flags, method, mtime, mdate, crc, csize, name)
                != expected or usize != next(
                    info.file_size for info in infos
                    if info.header_offset == local_offset)):
            raise IngressError("hwpx_physical_invalid")
        local_cursor = data_start + csize
        if local_cursor > central_offset:
            raise IngressError("hwpx_physical_invalid")
    if local_cursor != central_offset:
        raise IngressError("hwpx_physical_invalid")


def _validate_hwpx(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.suffix.casefold() != ".hwpx":
        raise IngressError("hwpx_missing")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) == 0 or len(names) > MAX_HWPX_MEMBERS:
                raise IngressError("hwpx_member_count_invalid")
            folded: set[str] = set()
            total_compressed = 0
            total_uncompressed = 0
            first_local: zipfile.ZipInfo | None = None
            for name in names:
                info = archive.getinfo(name)
                if first_local is None or info.header_offset < first_local.header_offset:
                    first_local = info
                if info.file_size < 0 or info.file_size > MAX_HWPX_MEMBER_BYTES:
                    raise IngressError("hwpx_member_size_invalid")
                total_compressed += info.compress_size
                if total_compressed > MAX_HWPX_COMPRESSED_BYTES:
                    raise IngressError("hwpx_compressed_size_invalid")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_HWPX_TOTAL_UNCOMPRESSED:
                    raise IngressError("hwpx_uncompressed_size_invalid")
                if info.flag_bits & (0x1 | 0x8 | 0x20):
                    raise IngressError("hwpx_flags_unsupported")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise IngressError("hwpx_compression_unsupported")
                allowed_flags = {0} if info.compress_type == zipfile.ZIP_STORED else {0, 0x4}
                if info.flag_bits not in allowed_flags:
                    raise IngressError("hwpx_flags_unsupported")
                if info.file_size and (info.compress_size == 0 or info.file_size > info.compress_size * MAX_HWPX_COMPRESSION_RATIO):
                    raise IngressError("hwpx_compression_ratio_high")
                normalized = name.replace("\\", "/")
                if not normalized or normalized.startswith("/") or "../" in normalized or "\x00" in normalized:
                    raise IngressError("hwpx_member_invalid")
                if normalized.casefold() in folded:
                    raise IngressError("hwpx_member_duplicate")
                folded.add(normalized.casefold())
            _validate_zip_physical(path, archive.infolist())
            if first_local is None or first_local.header_offset != 0 or first_local.filename != "mimetype":
                raise IngressError("hwpx_mimetype_not_first")
            if first_local.compress_type != zipfile.ZIP_STORED or first_local.flag_bits != 0 or first_local.extra:
                raise IngressError("hwpx_mimetype_container_invalid")
            with path.open("rb") as stream:
                local_header = stream.read(30)
                if len(local_header) != 30 or local_header[:4] != b"PK\x03\x04":
                    raise IngressError("hwpx_mimetype_container_invalid")
                fields = struct.unpack("<IHHHHHIIIHH", local_header)
                _, _version, flags, method, _mtime, _mdate, _crc, _compressed_size, _uncompressed_size, name_len, extra_len = fields
                if flags != 0 or method != zipfile.ZIP_STORED or name_len != len(b"mimetype") or extra_len != 0:
                    raise IngressError("hwpx_mimetype_container_invalid")
                if stream.read(name_len) != b"mimetype" or stream.read(extra_len):
                    raise IngressError("hwpx_mimetype_container_invalid")
            if "mimetype" not in names or archive.read("mimetype") != b"application/hwp+zip":
                raise IngressError("hwpx_mimetype_invalid")
            if archive.testzip() is not None:
                raise IngressError("hwpx_crc_invalid")
            container_name = "META-INF/container.xml"
            if container_name not in names:
                raise IngressError("hwpx_container_missing")
            container_root = ET.fromstring(archive.read(container_name))
            def qname(node: ET.Element) -> tuple[str, str] | None:
                tag = node.tag
                if not isinstance(tag, str) or not tag.startswith("{") or "}" not in tag:
                    return None
                namespace, local_name = tag[1:].split("}", 1)
                return namespace, local_name

            # OCF is an expanded-QName grammar.  Local-name matching would
            # let a foreign container/rootfile decoy select an attacker-owned
            # OPF while the visible shape still looked plausible.
            if (qname(container_root) != (_OCF_NS, "container")
                    or container_root.attrib
                    or (container_root.text and container_root.text.strip())):
                raise IngressError("hwpx_container_invalid")
            container_children = list(container_root)
            if (len(container_children) != 1
                    or qname(container_children[0]) != (_OCF_NS, "rootfiles")):
                raise IngressError("hwpx_rootfile_invalid")
            rootfiles_node = container_children[0]
            if (rootfiles_node.attrib
                    or (rootfiles_node.text and rootfiles_node.text.strip())
                    or (rootfiles_node.tail and rootfiles_node.tail.strip())):
                raise IngressError("hwpx_rootfile_invalid")
            declared: list[tuple[str, str]] = []
            for node in rootfiles_node:
                if (qname(node) != (_OCF_NS, "rootfile") or len(node)
                        or (node.text and node.text.strip())
                        or (node.tail and node.tail.strip())
                        or set(node.attrib) != {"full-path", "media-type"}):
                    raise IngressError("hwpx_rootfile_invalid")
                root_path = node.attrib.get("full-path", "").replace("\\", "/")
                media_type = node.attrib.get("media-type", "")
                parts = root_path.split("/")
                if (not root_path or root_path.startswith("/")
                        or "\x00" in root_path or any(part in ("", ".", "..") for part in parts)):
                    raise IngressError("hwpx_rootfile_invalid")
                root_path = posixpath.normpath(root_path)
                if root_path not in names:
                    raise IngressError("hwpx_rootfile_missing")
                declared.append((root_path, media_type))
            if len(declared) != len({(path.casefold(), media.casefold()) for path, media in declared}):
                raise IngressError("hwpx_rootfile_duplicate")
            hpf_roots = [item for item in declared if item[1] == _HPF_MEDIA_TYPE]
            if len(hpf_roots) != 1 or hpf_roots[0][0] != "Contents/content.hpf":
                raise IngressError("hwpx_opf_root_invalid")
            auxiliary = [item for item in declared if item not in hpf_roots]
            if any(item not in _AUX_ROOTFILES for item in auxiliary):
                raise IngressError("hwpx_rootfile_conflict")
            root_path = hpf_roots[0][0]
            opf_root = ET.fromstring(archive.read(root_path))
            if qname(opf_root) != (_OPF_NS, "package"):
                raise IngressError("hwpx_opf_invalid")
            direct = list(opf_root)
            manifests = [node for node in direct if qname(node) == (_OPF_NS, "manifest")]
            spines = [node for node in direct if qname(node) == (_OPF_NS, "spine")]
            if len(manifests) != 1 or len(spines) != 1:
                raise IngressError("hwpx_opf_shape")
            manifest_node, spine_node = manifests[0], spines[0]
            if ((manifest_node.text and manifest_node.text.strip())
                    or (spine_node.text and spine_node.text.strip())):
                raise IngressError("hwpx_opf_shape")
            # IDs are a document-wide OPF identity scope.  Compare casefolded
            # forms as well, so a foreign decoy cannot hide behind case.
            seen_ids: set[str] = set()
            for node in opf_root.iter():
                if "id" not in node.attrib:
                    continue
                value = node.attrib.get("id", "")
                # Hancom's package/manifest/spine containers commonly carry
                # an explicitly empty optional ``id``.  Empty values are not
                # identities; item IDs are still required below.
                if not value:
                    continue
                if value.casefold() in seen_ids:
                    raise IngressError("hwpx_opf_duplicate_id")
                seen_ids.add(value.casefold())
            manifest_items: dict[str, str] = {}
            href_folds: set[str] = set()
            for node in manifest_node:
                if (qname(node) != (_OPF_NS, "item") or len(node)
                        or (node.text and node.text.strip()) or (node.tail and node.tail.strip())):
                    raise IngressError("hwpx_manifest_invalid")
                allowed_attrs = {"id", "href", "media-type", "isEmbeded"}
                if set(node.attrib) - allowed_attrs:
                    raise IngressError("hwpx_manifest_invalid")
                item_id = node.attrib.get("id", "")
                href = node.attrib.get("href", "").replace("\\", "/")
                media_type = node.attrib.get("media-type", "")
                if (not item_id or not href or not media_type
                        or href.startswith("/") or "\x00" in href
                        or "#" in href or "?" in href
                        or any(part in ("", ".", "..") for part in href.split("/"))):
                    raise IngressError("hwpx_manifest_invalid")
                if node.attrib.get("isEmbeded") not in (None, "1"):
                    raise IngressError("hwpx_manifest_invalid")
                # Hancom emits both package-root hrefs (``Contents/foo.xml``)
                # and OPF-relative hrefs (``section0.xml``).  Prefer an
                # exact package member and fall back to the OPF directory.
                item_path = posixpath.normpath(href)
                if item_path not in names:
                    item_path = posixpath.normpath(posixpath.join(posixpath.dirname(root_path), href))
                if item_path not in names:
                    raise IngressError("hwpx_manifest_target_missing")
                if item_path.casefold() in href_folds:
                    raise IngressError("hwpx_manifest_duplicate")
                href_folds.add(item_path.casefold())
                manifest_items[item_id] = item_path
            spine_refs: list[str] = []
            seen_refs: set[str] = set()
            for node in spine_node:
                if (qname(node) != (_OPF_NS, "itemref") or len(node)
                        or (node.text and node.text.strip()) or (node.tail and node.tail.strip())):
                    raise IngressError("hwpx_spine_invalid")
                if set(node.attrib) - {"id", "idref", "linear"}:
                    raise IngressError("hwpx_spine_invalid")
                ref = node.attrib.get("idref", "")
                if not ref or ref not in manifest_items or ref.casefold() in seen_refs:
                    raise IngressError("hwpx_spine_invalid")
                linear = node.attrib.get("linear")
                if linear is not None and linear not in {"yes", "no"}:
                    raise IngressError("hwpx_spine_invalid")
                seen_refs.add(ref.casefold())
                spine_refs.append(ref)
            if not spine_refs:
                raise IngressError("hwpx_spine_invalid")
            declared_sections = [manifest_items[ref] for ref in spine_refs
                                 if re.fullmatch(r"Contents/section\d+\.xml", manifest_items[ref])]
            if not declared_sections:
                raise IngressError("hwpx_sections_undeclared")
            sections = [name.replace("\\", "/") for name in names
                        if re.fullmatch(r"Contents/section\d+\.xml", name.replace("\\", "/"))]
            if not sections:
                raise IngressError("hwpx_sections_missing")
            # Every physical section member is story-bearing and must be
            # declared exactly once in the nonempty OPF spine.  Otherwise an
            # unspined section can carry content outside the comparison set.
            if sorted(declared_sections) != sorted(sections):
                raise IngressError("hwpx_sections_coverage")
            # Use the existing COM-free semantic fingerprint as the XML gate.
            script_dir = Path(__file__).resolve().parent
            if str(script_dir) not in sys.path:
                sys.path.insert(0, str(script_dir))
            from content_extract import semantic_fingerprint
            fingerprint = semantic_fingerprint(path)
            counts = fingerprint.get("counts") or {}
            retained = {key: int(counts.get(key, 0)) for key in ("tables", "pictures", "equations")}
    except IngressError:
        raise
    except (OSError, RuntimeError, KeyError, zipfile.BadZipFile,
            zipfile.LargeZipFile, ValueError, UnicodeError, ImportError,
            ET.ParseError):
        raise IngressError("hwpx_invalid")
    try:
        byte_count = path.stat().st_size
    except OSError:
        raise IngressError("hwpx_invalid")
    return {"format": "hwpx", "bytes": byte_count,
            "sha256": sha256_file(path), "counts": retained}


def _closed_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IngressError("receipt_duplicate_key")
            result[key] = value
        return result

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw, object_pairs_hook=no_duplicates)
    except IngressError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IngressError("receipt_invalid")
    if not isinstance(payload, dict):
        raise IngressError("receipt_invalid")
    return payload


def verify_receipt(output: str | Path, manifest: str | Path) -> dict[str, Any]:
    """Validate one converted receipt against the exact canonical HWPX."""
    payload = _closed_json(Path(manifest))
    if set(payload) != {
            "schema", "status", "reason", "source", "execution",
            "comparison", "output", "proof_grade"}:
        raise IngressError("receipt_schema_invalid")
    if (payload.get("schema") != HWP_INGRESS_SCHEMA
            or payload.get("status") != "converted"
            or payload.get("reason") != "converted"
            or payload.get("proof_grade") != "none"):
        raise IngressError("receipt_state_invalid")

    source = payload.get("source")
    if (not isinstance(source, dict) or set(source) != {
            "format", "version", "bytes", "sha256", "compressed",
            "security_flags"} or source.get("format") != "hwp"
            or not isinstance(source.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", source["version"]) is None
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not isinstance(source.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is None
            or not isinstance(source.get("compressed"), bool)
            or source.get("security_flags") != []):
        raise IngressError("receipt_source_invalid")

    execution = payload.get("execution")
    if (execution != {"state": "succeeded", "adapter": "hancom"}):
        raise IngressError("receipt_execution_invalid")
    comparison = payload.get("comparison")
    comparison_keys = {
        "state", "method", "text_hash_match", "text_chars_match",
        "aggregate_counts_match", "control_counts_match",
    }
    if (not isinstance(comparison, dict) or set(comparison) != comparison_keys
            or comparison.get("state") != "passed"
            or comparison.get("method") != "same_com_extractor"
            or any(comparison.get(key) is not True for key in comparison_keys
                   - {"state", "method"})):
        raise IngressError("receipt_comparison_invalid")

    recorded = payload.get("output")
    if (not isinstance(recorded, dict) or set(recorded) != {
            "state", "format", "bytes", "sha256", "counts"}
            or recorded.get("state") != "published"
            or recorded.get("format") != "hwpx"):
        raise IngressError("receipt_output_invalid")
    counts = recorded.get("counts")
    if (not isinstance(counts, dict)
            or set(counts) != {"tables", "pictures", "equations"}
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in counts.values())):
        raise IngressError("receipt_output_invalid")
    actual = _validate_hwpx(Path(output))
    if (recorded.get("bytes") != actual["bytes"]
            or recorded.get("sha256") != actual["sha256"]
            or counts != actual["counts"]):
        raise IngressError("receipt_output_mismatch")
    return payload


def _com_available() -> bool:
    return sys.platform == "win32" and importlib.util.find_spec("pyhwpx") is not None


@contextlib.contextmanager
def _com_serial_guard():
    """Serialize all Hancom child processes with a crash-safe named mutex.

    The guard is deliberately a no-op off Windows because ``_com_available``
    already refuses there.  Windows' kernel mutex is released automatically if
    this process crashes; no process termination or stale lock file is needed.
    """
    # The local RLock closes same-process thread races.  Thread-local depth
    # permits only genuine same-thread re-entry; a second thread waits here
    # rather than bypassing the Windows named mutex.
    with _COM_THREAD_LOCK:
        if sys.platform != "win32":
            yield
            return
        depth = getattr(_COM_MUTEX_STATE, "depth", 0)
        if depth:
            _COM_MUTEX_STATE.depth = depth + 1
            try:
                yield
            finally:
                _COM_MUTEX_STATE.depth -= 1
            return
        handle = None
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            create_mutex.restype = ctypes.c_void_p
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_bool
            handle = create_mutex(None, False, "Local\\Rigorloom-HwpIngress-T85")
            if not handle:
                raise IngressError("hancom_mutex_unavailable")
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                close_handle(handle)
                handle = None
                raise IngressError("hancom_mutex_busy")
            try:
                _COM_MUTEX_STATE.depth = 1
                yield
            finally:
                _COM_MUTEX_STATE.depth = 0
                close_handle(handle)
                handle = None
        except IngressError:
            raise
        except (AttributeError, OSError, TypeError):
            raise IngressError("hancom_mutex_unavailable")


def _hwp_tasklist_code() -> int:
    if sys.platform != "win32":
        raise IngressError("hancom_platform_unsupported")
    try:
        proc = subprocess.run(["cmd", "/c", 'tasklist | findstr /i hwp'],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)
    except OSError:
        raise IngressError("hancom_precheck_failed")
    return proc.returncode


def _com_precheck() -> None:
    if _hwp_tasklist_code() != 1:
        raise IngressError("hancom_precheck_busy")


def _wait_com_clear(timeout: float) -> None:
    """Wait briefly for this child application's natural shutdown.

    No process is terminated.  The next COM child still performs its own
    immediate `_com_precheck`; this wait only removes the ordinary lag between
    a completed Python/COM child and Hwp.exe disappearing from tasklist.
    """
    deadline = time.monotonic() + min(10.0, _validate_timeout(timeout))
    while True:
        code = _hwp_tasklist_code()
        if code == 1:
            return
        if code != 0:
            raise IngressError("hancom_precheck_failed")
        if time.monotonic() >= deadline:
            raise IngressError("hancom_shutdown_pending")
        time.sleep(0.1)


def _com_inspect(argv: list[str], *, timeout: float) -> dict[str, Any]:
    """Inspect through com_backend while retaining only safe control counts."""
    timeout = _validate_timeout(timeout)
    _com_precheck()
    code, timed_out, overflow, stdout, _ = _run_child_capture(argv, timeout=timeout)
    _wait_com_clear(timeout)
    if timed_out:
        raise IngressError("timeout")
    if overflow:
        raise IngressError("child_output_too_large")
    if code != 0:
        raise IngressError("hancom_execution_failed")
    raw_stdout = stdout
    if not isinstance(raw_stdout, (bytes, bytearray)):
        raise IngressError("hancom_output_invalid")
    try:
        payload = json.loads(bytes(raw_stdout).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise IngressError("hancom_output_invalid")
    if not isinstance(payload, dict):
        raise IngressError("hancom_output_invalid")
    if payload.get("ok") is not True:
        raise IngressError("hancom_execution_failed")
    if any(key in payload for key in (
            "text_fingerprint_unavailable", "ctrl_scan_error",
            "field_scan_error", "page_count_unavailable")):
        raise IngressError("hancom_fingerprint_incomplete")
    try:
        text_hash = payload["text_sha256"]
        if not isinstance(text_hash, str) or len(text_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in text_hash):
            raise ValueError
        text_chars = payload["text_chars_total"]
        if isinstance(text_chars, bool) or not isinstance(text_chars, int) or text_chars < 0:
            raise ValueError
        count_keys = ("tables", "pictures", "equations", "shapes", "pages",
                      "controls_total", "field_count")
        counts = {key: payload[key] for key in count_keys}
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in counts.values()):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise IngressError("hancom_counts_missing")
    return {"text_sha256": text_hash.casefold(), "text_chars_total": text_chars,
            "counts": counts}


def _publish_pair(staged: Path, out: Path, manifest: Path, payload: dict[str, Any]) -> None:
    if out.exists() or manifest.exists():
        raise IngressError("output_exists")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise IngressError("output_parent_unavailable")
    # Receipt first: it commits the exact output hash before the output path
    # becomes visible.  The output hard-link is the final fallible operation.
    receipt_identity = _write_manifest(manifest, payload)
    try:
        os.link(str(staged), str(out))
    except FileExistsError:
        _remove_identity(manifest, receipt_identity)
        raise IngressError("output_exists")
    except OSError:
        _remove_identity(manifest, receipt_identity)
        raise IngressError("output_publish_failed")


def convert_path(input_path: str | Path, *, adapter: str, out: str | Path,
                 manifest: str | Path, timeout: float = 60.0) -> dict[str, Any]:
    source_path = Path(input_path)
    out_path = Path(out)
    manifest_path = Path(manifest)
    source_for_manifest: _Source | None = None
    comparison_for_manifest: dict[str, Any] = {"state": "unknown"}
    adapter_started = False
    guard_cm = None
    guard_active = False
    safe_adapter = "hancom" if adapter == "hancom" else None
    execution_for_manifest = {"state": "not_run", "adapter": safe_adapter}
    try:
        _validate_distinct(source_path, out_path, manifest_path)
        timeout = _validate_timeout(timeout)
        # T85 canonical publication is native Hancom only.  Diagnostic
        # exporters are a separate future surface and cannot publish here.
        if adapter != "hancom":
            raise IngressError("adapter_unsupported")
        # Hold the process-wide COM mutex from canonical destination checks
        # through receipt-first/output-last publication.  A competing call
        # must not write a refusal receipt into the same destination pair.
        guard_cm = _com_serial_guard()
        guard_cm.__enter__()
        guard_active = True
        # Refuse before spawning any adapter.  Publication itself repeats the
        # check with an exclusive link to close the race window.
        if out_path.exists():
            raise IngressError("output_exists")
        if manifest_path.exists():
            raise IngressError("manifest_exists")
        data = _read_bounded(source_path)
        source = parse_hwp_bytes(data)
        source_for_manifest = source
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise IngressError("output_parent_unavailable")
        execution: dict[str, Any] = {"state": "not_run", "adapter": adapter}
        comparison: dict[str, Any] = {"state": "unknown"}
        with tempfile.TemporaryDirectory(prefix="rigorloom-hwp-ingress-", dir=str(out_path.parent.resolve())) as tmp:
            tmp_dir = Path(tmp)
            staged_input = tmp_dir / "input.hwp"
            staged_output = tmp_dir / "output.hwpx"
            staged_input.write_bytes(data)
            if not _com_available():
                raise IngressError("hancom_unavailable")
            engine = Path(__file__).resolve().parents[2] / "engine" / "scripts" / "com_backend.py"
            if not engine.is_file():
                raise IngressError("hancom_unavailable")
            adapter_started = True
            inspect_args = [sys.executable, str(engine), "inspect", "--file", str(staged_input), "--preview-chars", "0", "--privacy-safe"]
            # The outer process-wide mutex is held through publication.  The
            # tasklist precheck remains immediately before each child as an
            # independent busy-engine gate.
            source_fingerprint = _com_inspect(inspect_args, timeout=timeout)
            _com_precheck()
            code, timed_out, overflow = _run_child(
                [sys.executable, str(engine), "convert", "--file", str(staged_input), "--to", str(staged_output)], timeout=timeout)
            _wait_com_clear(timeout)
            if timed_out:
                raise IngressError("timeout")
            if overflow:
                raise IngressError("child_output_too_large")
            if code != 0:
                raise IngressError("hancom_execution_failed")
            execution = {"state": "succeeded", "adapter": "hancom"}
            execution_for_manifest = execution
            output_counts = _validate_hwpx(staged_output)["counts"]
            output_fingerprint = _com_inspect(
                [sys.executable, str(engine), "inspect", "--file", str(staged_output), "--preview-chars", "0", "--privacy-safe"],
                timeout=timeout)
            text_hash_match = source_fingerprint["text_sha256"] == output_fingerprint["text_sha256"]
            text_chars_match = source_fingerprint["text_chars_total"] == output_fingerprint["text_chars_total"]
            aggregate_counts_match = source_fingerprint["counts"] == output_fingerprint["counts"]
            control_keys = ("tables", "pictures", "equations")
            control_counts_match = all(
                source_fingerprint["counts"][key] == output_fingerprint["counts"][key] == output_counts[key]
                for key in control_keys)
            comparison = {
                "state": "passed" if text_hash_match and text_chars_match and aggregate_counts_match and control_counts_match else "mismatch",
                "method": "same_com_extractor",
                "text_hash_match": text_hash_match,
                "text_chars_match": text_chars_match,
                "aggregate_counts_match": aggregate_counts_match,
                "control_counts_match": control_counts_match,
            }
            comparison_for_manifest = comparison
            if not text_hash_match or not text_chars_match:
                raise IngressError("semantic_text_mismatch")
            if not aggregate_counts_match:
                raise IngressError("aggregate_counts_mismatch")
            if not control_counts_match:
                raise IngressError("control_counts_mismatch")
            output_record = {"state": "published", **_validate_hwpx(staged_output)}
            output_record["state"] = "published"
            # Re-read the live source immediately before publication.  The
            # staged input remains immutable even if the original is replaced.
            if sha256_bytes(_read_bounded(source_path)) != source.sha256:
                raise IngressError("source_changed")
            payload = _base_manifest(status="converted", reason="converted", source=source,
                                     adapter=adapter, execution=execution,
                                     comparison=comparison, output=output_record)
            _publish_pair(staged_output, out_path, manifest_path, payload)
            return payload
    except IngressError as exc:
        if adapter_started and execution_for_manifest["state"] == "not_run":
            execution_for_manifest = {"state": "failed", "adapter": adapter}
        payload = _base_manifest(status="refused", reason=exc.reason,
                                 source=source_for_manifest,
                                 adapter=adapter if adapter == "hancom" else None,
                                 execution=execution_for_manifest,
                                 comparison=comparison_for_manifest)
        try:
            if (exc.reason != "hancom_mutex_busy"
                    and manifest_path.suffix.casefold() == ".json"
                    and not manifest_path.exists()):
                _write_manifest(manifest_path, payload)
        except (IngressError, OSError):
            pass
        return payload
    except OSError:
        if adapter_started and execution_for_manifest["state"] == "not_run":
            execution_for_manifest = {"state": "failed", "adapter": adapter}
        payload = _base_manifest(status="refused", reason="io_error",
                                 source=source_for_manifest,
                                 adapter=adapter if adapter == "hancom" else None,
                                 execution=execution_for_manifest,
                                 comparison=comparison_for_manifest)
        try:
            if (manifest_path.suffix.casefold() == ".json"
                    and not manifest_path.exists()):
                _write_manifest(manifest_path, payload)
        except (IngressError, OSError):
            pass
        return payload
    finally:
        if guard_active and guard_cm is not None:
            guard_cm.__exit__(None, None, None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bounded fail-closed HWP5 ingress")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect", help="validate HWP5 candidate")
    inspect_parser.add_argument("input")
    inspect_parser.add_argument("--manifest")
    convert_parser = sub.add_parser("convert", help="convert with one explicit adapter")
    convert_parser.add_argument("input")
    convert_parser.add_argument("--adapter", choices=("hancom",), required=True)
    convert_parser.add_argument("--out", required=True)
    convert_parser.add_argument("--manifest", required=True)
    convert_parser.add_argument("--timeout", type=float, default=60.0)
    verify_parser = sub.add_parser(
        "verify", help="validate a converted receipt against its HWPX")
    verify_parser.add_argument("output")
    verify_parser.add_argument("--manifest", required=True)
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "inspect":
        payload = inspect_path(args.input)
        if args.manifest:
            try:
                _validate_distinct(Path(args.input), None, Path(args.manifest))
                if Path(args.manifest).exists():
                    raise IngressError("manifest_exists")
                _write_manifest(Path(args.manifest), payload)
            except (IngressError, OSError):
                payload = _base_manifest(status="refused", reason="manifest_exists" if Path(args.manifest).exists() else "manifest_write_failed")
        try:
            _print_json(payload)
        except (BrokenPipeError, OSError, UnicodeError):
            return EXIT_REFUSED
        return EXIT_OK if payload["status"] == "candidate" else EXIT_REFUSED
    if args.command == "verify":
        try:
            payload = verify_receipt(args.output, args.manifest)
        except IngressError as exc:
            payload = _base_manifest(status="refused", reason=exc.reason)
        try:
            _print_json(payload)
        except (BrokenPipeError, OSError, UnicodeError):
            return EXIT_REFUSED
        return EXIT_OK if payload["status"] == "converted" else EXIT_REFUSED
    payload = convert_path(args.input, adapter=args.adapter, out=args.out,
                           manifest=args.manifest, timeout=args.timeout)
    try:
        _print_json(payload)
    except (BrokenPipeError, OSError, UnicodeError):
        return EXIT_REFUSED
    return EXIT_OK if payload["status"] == "converted" else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
