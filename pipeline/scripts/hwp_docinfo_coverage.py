#!/usr/bin/env python3
"""Receipt-only DocInfo cardinality/reference coverage for HWP5 (T90).

The scanner deliberately makes a small structural claim.  It captures one
HWP byte snapshot, applies the T85 CFB/FileHeader preflight, reuses the T89
BodyText envelope scanner, and records only bounded definition/cardinality and
reference *counts*.  Definition payloads are not interpreted and no text,
raw ids, names, paths, or process output are copied into the receipt.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
from typing import Any, Iterable

try:
    import diagnostic_candidate_core as _core
    import hwp_ingress as _ingress
    import hwp_source_coverage as _source
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_ingress as _ingress
    from pipeline.scripts import hwp_source_coverage as _source


SCHEMA = "rigorloom/hwp-docinfo-coverage/v1"
ROOT_LEAF = "hwp-docinfo-coverage"
CLAIM_SCOPE = "docinfo_record_cardinality_and_bodytext_reference_bounds_v1"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

MAX_INPUT_BYTES = getattr(_ingress, "MAX_INPUT_BYTES", 256 * 1024 * 1024)
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_DOCINFO_BYTES = 64 * 1024 * 1024
MAX_DOCINFO_RECORDS = 1_000_000
MAX_DEFINITION_COUNT = 1_000_000
MAX_DEFINITION_TOTAL = 2_000_000
MAX_BODY_SECTIONS = getattr(_source, "MAX_SECTIONS", 1024)
MAX_BODY_RECORDS_TOTAL = getattr(_source, "MAX_RECORDS_TOTAL", 2_000_000)
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

# This is a scanner pin, not a claim that syhwp was installed or executed.
SCANNER = {
    "name": "rigorloom_hwp5_docinfo_coverage",
    "version": 1,
    "target": {
        "package": "syhwp",
        "version": "0.0.7",
        "commit": "d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed",
    },
    "execution": "independent_no_external_tool",
}

# IDMappings is an exact 18-element signed INT32 count array in this v1
# surface.  Names are schema-owned tokens only; versioned shorter/tail forms
# are refused rather than silently reinterpreted.
ID_KEYS = (
    "bin_data", "face_name.kor", "face_name.eng", "face_name.han",
    "face_name.jpn", "face_name.other", "face_name.symbol", "face_name.user",
    "border_fill", "char_shape", "tab_def", "numbering", "bullet",
    "para_shape", "style", "memo_shape", "track_change",
    "track_change_author",
)
FACE_NAME_KEYS = ID_KEYS[1:8]

# Definition record ids are imported from T89 so both scanners use the same
# reviewed wire table.  The numeric values never appear in a receipt.
TAG_DOCUMENT_PROPERTIES = _source.TAG_DOCUMENT_PROPERTIES
TAG_ID_MAPPINGS = _source.TAG_ID_MAPPINGS
TAG_BIN_DATA = _source.TAG_BIN_DATA
TAG_FACE_NAME = _source.TAG_FACE_NAME
TAG_BORDER_FILL = _source.TAG_BORDER_FILL
TAG_CHAR_SHAPE = _source.TAG_CHAR_SHAPE
TAG_TAB_DEF = _source.TAG_TAB_DEF
TAG_NUMBERING = _source.TAG_NUMBERING
TAG_BULLET = _source.TAG_BULLET
TAG_PARA_SHAPE = _source.TAG_PARA_SHAPE
TAG_STYLE = _source.TAG_STYLE
# The pinned HWP 5.0 table uses 0x5C/0x5E for DocInfo MemoShape and forbidden
# character records.  These ids overlap older BodyText tables; the stream
# context is what gives them their meaning.
TAG_MEMO_SHAPE = getattr(_source, "TAG_MEMO_SHAPE", 0x5C)
# 0x20 is observed in public DocInfo tails as BEGIN+16, but this slice does
# not prove whether a given producer uses it for track-change metadata.
TAG_BEGIN_PLUS_16_OPAQUE = 0x20
TAG_FORBIDDEN_CHAR = getattr(_source, "TAG_FORBIDDEN_CHAR", 0x5E)
TAG_PARA_HEADER = _source.TAG_PARA_HEADER
TAG_PARA_TEXT = _source.TAG_PARA_TEXT
TAG_PARA_CHAR_SHAPE = _source.TAG_PARA_CHAR_SHAPE

NOT_SCANNED_TOKENS = [
    "definition.payload_semantics",
    "definition.char_shape_semantics",
    "definition.face_name_bstr",
    "definition.style_names",
    "definition.style_redirects",
    "definition.para_shape_semantics",
    "definition.numbering_formats",
    "definition.bullet_glyphs",
    "definition.generated_numbering_state",
    "definition.versioned_payload_tails",
    "definition.track_change_graph",
    "paragraph.split_state",
    "paragraph.char_shape_position_semantics",
]

_TOP_KEYS = frozenset({
    "schema", "status", "source", "scanner", "coverage", "eligibility",
    "comparison", "render", "proof_grade", "submission_grade",
})
_COVERAGE_KEYS = frozenset({
    "scope", "not_scanned_tokens", "state", "docinfo_records",
    "definition_counts", "bodytext_sections", "bodytext_paragraphs",
    "bodytext_para_shape_refs", "bodytext_style_refs",
    "bodytext_char_shape_refs", "bodytext_char_shape_position_refs",
    "supported_tokens", "blocking_tokens",
})
_SUPPORTED_TOKENS = frozenset({
    "docinfo.document_properties", "docinfo.id_mappings",
    "docinfo.definition_groups", "bodytext.para_header",
    "bodytext.para_text", "bodytext.para_char_shape",
})
_BLOCKING_TOKENS = frozenset({
    "docinfo.record_unknown", "docinfo.record_order", "docinfo.record_level",
    "docinfo.document_properties_missing", "docinfo.document_properties_duplicate",
    "docinfo.id_mappings_missing", "docinfo.id_mappings_duplicate",
    "docinfo.id_mappings_length", "docinfo.id_mappings_count_invalid",
    "docinfo.definition_count_mismatch", "docinfo.definition_order",
    "docinfo.definition_level", "docinfo.definition_unknown",
    "docinfo.version_unsupported", "docinfo.version_tail",
    "docinfo.record_truncated", "docinfo.record_extended_size",
    "docinfo.record_level_jump", "bodytext.reference_out_of_range",
    "bodytext.char_shape_position_invalid", "bodytext.paragraph_invalid",
    "bodytext.section_invalid", "bodytext.envelope_invalid",
})


class CoverageError(Exception):
    """Expected fail-closed refusal with a privacy-safe reason token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageError("receipt_duplicate_key")
        result[key] = value
    return result


def _source_descriptor(value: Any) -> dict[str, Any]:
    try:
        descriptor = value.descriptor()
    except (AttributeError, TypeError, ValueError):
        raise CoverageError("source_descriptor_invalid")
    if (set(descriptor) != {"format", "version", "bytes", "sha256",
                            "compressed", "security_flags"}
            or descriptor.get("format") != "hwp"
            or not isinstance(descriptor.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", descriptor["version"]) is None
            or isinstance(descriptor.get("bytes"), bool)
            or not isinstance(descriptor.get("bytes"), int)
            or descriptor["bytes"] <= 0
            or not isinstance(descriptor.get("sha256"), str)
            or SHA256_RE.fullmatch(descriptor["sha256"]) is None
            or not isinstance(descriptor.get("compressed"), bool)
            or descriptor.get("security_flags") != []):
        raise CoverageError("source_descriptor_invalid")
    return descriptor


def _empty_source() -> dict[str, Any]:
    return {"format": "hwp", "version": None, "bytes": None,
            "sha256": None, "compressed": None, "security_flags": []}


def _base_refusal(reason: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "refused",
        "reason": reason,
        "source": source or _empty_source(),
        "scanner": SCANNER,
        "coverage": {
            "scope": CLAIM_SCOPE,
            "not_scanned_tokens": NOT_SCANNED_TOKENS,
            "state": "incomplete",
            "docinfo_records": 0,
            "definition_counts": {},
            "bodytext_sections": 0,
            "bodytext_paragraphs": 0,
            "bodytext_para_shape_refs": 0,
            "bodytext_style_refs": 0,
            "bodytext_char_shape_refs": 0,
            "bodytext_char_shape_position_refs": 0,
            "supported_tokens": [],
            "blocking_tokens": [],
        },
        "eligibility": "unknown",
        "comparison": {"state": "unknown"},
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
    }


def _coerce_path(value: Any, reason: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise CoverageError(reason)
    try:
        return Path(value)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoverageError(reason)


def _resolve_input_path(path: Path) -> Path:
    if path.suffix.casefold() != ".hwp":
        raise CoverageError("extension_not_hwp")
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
        if resolved.suffix.casefold() != ".hwp":
            raise CoverageError("extension_not_hwp")
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


def _preflight(data: bytes) -> tuple[Any, Any]:
    if not isinstance(data, bytes) or not data:
        raise CoverageError("input_empty")
    try:
        value = _ingress.parse_hwp_bytes(data)
        cfb = _ingress._Cfb(data)
        header = cfb.fileheader()
    except _ingress.IngressError as exc:
        raise CoverageError(exc.reason)
    except (OSError, ValueError, TypeError, struct.error):
        raise CoverageError("preflight_failed")
    return value, (cfb, header)


def _direct_docinfo(cfb: Any) -> Any:
    try:
        root = cfb.root
        children = [cfb.directory[i] for i in cfb._tree_nodes(root.child)]
    except (AttributeError, TypeError, ValueError):
        raise CoverageError("docinfo_invalid")
    # T85 permits case-folded ingress aliases.  T90's claim is narrower:
    # exactly one direct root stream with the canonical spelling.
    exact = [entry for entry in children if entry.name == "DocInfo"]
    matches = [entry for entry in exact if entry.kind == 2]
    if len(exact) != 1 or len(matches) != 1:
        raise CoverageError("docinfo_missing" if not exact
                            else "docinfo_ambiguous")
    if any(entry.name.casefold() == "docinfo" and entry.name != "DocInfo"
           for entry in children):
        raise CoverageError("docinfo_alias")
    return matches[0]


def _iter_records(raw: bytes, *, max_records: int, max_bytes: int) -> Iterable[tuple[int, int, bytes]]:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise CoverageError("docinfo_stream_invalid")
    offset = 0
    count = 0
    previous_level: int | None = None
    while offset < len(raw):
        if count >= max_records:
            raise CoverageError("docinfo_record_limit")
        if len(raw) - offset < 4:
            raise CoverageError("docinfo_record_truncated")
        header = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        if previous_level is None:
            if level != 0:
                raise CoverageError("docinfo_record_level")
        elif level > previous_level + 1:
            raise CoverageError("docinfo_record_level_jump")
        previous_level = level
        if size == 0xFFF:
            if len(raw) - offset < 4:
                raise CoverageError("docinfo_record_extended_size")
            size = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
        if size > max_bytes or size > len(raw) - offset:
            raise CoverageError("docinfo_record_truncated")
        payload = raw[offset:offset + size]
        offset += size
        count += 1
        yield tag, level, payload


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(int(item) for item in version.split("."))
    except (AttributeError, TypeError, ValueError):
        raise CoverageError("docinfo_version_unsupported")
    if len(parts) != 4 or parts[:2] not in ((5, 0), (5, 1)):
        raise CoverageError("docinfo_version_unsupported")
    return parts  # type: ignore[return-value]


def _id_key_count(version: str) -> int:
    # The v1 claim is intentionally narrower than historical parsers: every
    # supported 5.0/5.1 source must carry the complete 18-field mapping.  A
    # version-specific shorter prefix is a refused, versioned-tail surface,
    # not silently reinterpreted as an older schema.
    _version_tuple(version)
    return 18


def _parse_id_mappings(payload: bytes, version: str) -> tuple[dict[str, int], list[int]]:
    key_count = _id_key_count(version)
    if len(payload) != key_count * 4:
        raise CoverageError("docinfo_id_mappings_length")
    values = list(struct.unpack("<%di" % key_count, payload))
    if any(value < 0 or value > MAX_DEFINITION_COUNT for value in values):
        raise CoverageError("docinfo_id_mappings_count_invalid")
    if sum(values) > MAX_DEFINITION_TOTAL:
        raise CoverageError("docinfo_definition_total_limit")
    return dict(zip(ID_KEYS[:key_count], values)), values


def _parse_docinfo(raw: bytes, version: str) -> dict[str, Any]:
    records = list(_iter_records(raw, max_records=MAX_DOCINFO_RECORDS,
                                 max_bytes=MAX_DOCINFO_BYTES))
    if len(records) < 2:
        raise CoverageError("docinfo_record_order")
    first_tag, first_level, first_payload = records[0]
    second_tag, second_level, second_payload = records[1]
    if first_tag != TAG_DOCUMENT_PROPERTIES or first_level != 0:
        raise CoverageError("docinfo_document_properties_missing")
    if len(first_payload) != 26:
        raise CoverageError("docinfo_document_properties_invalid")
    if second_tag != TAG_ID_MAPPINGS or second_level != 0:
        raise CoverageError("docinfo_id_mappings_missing")
    definition_counts, values = _parse_id_mappings(second_payload, version)

    if any(tag == TAG_DOCUMENT_PROPERTIES for tag, _, _ in records[1:]):
        raise CoverageError("docinfo_document_properties_duplicate")
    if any(tag == TAG_ID_MAPPINGS for tag, _, _ in records[2:]):
        raise CoverageError("docinfo_id_mappings_duplicate")

    # Exact physical order: BinData, all seven FACE_NAME categories summed,
    # then the seven core definition groups.  Payload bytes are opaque.
    expected_groups: list[tuple[str, int | None, int]] = [
        ("bin_data", TAG_BIN_DATA, values[0]),
        ("face_name", TAG_FACE_NAME, sum(values[1:8])),
        ("border_fill", TAG_BORDER_FILL, values[8]),
        ("char_shape", TAG_CHAR_SHAPE, values[9]),
        ("tab_def", TAG_TAB_DEF, values[10]),
        ("numbering", TAG_NUMBERING, values[11]),
        ("bullet", TAG_BULLET, values[12]),
        ("para_shape", TAG_PARA_SHAPE, values[13]),
        ("style", TAG_STYLE, values[14]),
    ]
    position = 2
    for token, expected_tag, expected_count in expected_groups:
        if expected_tag is None:
            continue
        if expected_count < 0 or expected_count > MAX_DEFINITION_COUNT:
            raise CoverageError("docinfo_definition_count_invalid")
        for _ in range(expected_count):
            if position >= len(records):
                raise CoverageError("docinfo_definition_count_mismatch")
            tag, level, _payload = records[position]
            if tag != expected_tag:
                raise CoverageError("docinfo_definition_order")
            if level != 1:
                raise CoverageError("docinfo_definition_level")
            position += 1
    # Version fields beyond Style are deliberately not interpreted.  Their
    # physical records are nevertheless cardinality-checked when declared by
    # IDMappings.  (The two track-change fields have had order variants across
    # producer revisions, so the accepted envelope treats each as an opaque
    # reviewed group and never exposes payload semantics.)
    for expected_tag, value_index in (
            (TAG_MEMO_SHAPE, 15),):
        if value_index >= len(values):
            continue
        for _ in range(values[value_index]):
            if position >= len(records) or records[position][0] != expected_tag:
                raise CoverageError("docinfo_definition_order")
            if records[position][1] != 1:
                raise CoverageError("docinfo_definition_level")
            position += 1
    # Track-change and author ID mappings are deliberately outside this first
    # coverage slice.  Their physical tags/ordering differ across producers;
    # a nonzero declaration therefore cannot be certified by this scanner.
    if len(values) > 16 and (values[16] or values[17]):
        raise CoverageError("docinfo_definition_semantics_unscanned")

    # Non-ID-mapped DocInfo metadata is still part of the strict record
    # envelope.  We accept the reviewed classes observed in the public HWP
    # corpus, with their documented level, while refusing every unknown tag
    # and preserving their bytes only as an opaque, not-scanned surface.
    optional_levels = {
        0x1B: 0, TAG_FORBIDDEN_CHAR: 1,
        0x1E: 0, 0x1F: 1, TAG_BEGIN_PLUS_16_OPAQUE: 1,
    }
    seen_optional: set[int] = set()
    last_rank = -1
    optional_order = {
        0x1B: 0, TAG_FORBIDDEN_CHAR: 1,
        0x1E: 2, 0x1F: 3, TAG_BEGIN_PLUS_16_OPAQUE: 4,
    }
    while position < len(records):
        tag, level, _payload = records[position]
        if tag not in optional_levels:
            raise CoverageError("docinfo_definition_unknown")
        if tag in seen_optional:
            raise CoverageError("docinfo_definition_order")
        if level != optional_levels[tag]:
            raise CoverageError("docinfo_definition_level")
        rank = optional_order[tag]
        if rank < last_rank:
            raise CoverageError("docinfo_definition_order")
        seen_optional.add(tag)
        last_rank = rank
        position += 1

    counts = {key: definition_counts[key] for key in ID_KEYS[:len(values)]}
    counts["face_name.total"] = sum(values[1:8])
    return {
        "records": len(records),
        "definition_counts": counts,
    }


def _body_records(cfb: Any, header: Any, definition_counts: dict[str, int]) -> dict[str, Any]:
    try:
        sections = _source._direct_sections(cfb)
    except _source.CoverageError as exc:
        raise CoverageError(exc.reason)
    if len(sections) > MAX_BODY_SECTIONS:
        raise CoverageError("bodytext_section_limit")
    # First run the complete T89 envelope scanner over every captured stream.
    # Its record hierarchy/extended-size/control accounting is deliberately
    # reused; this pass adds only DocInfo reference bounds.
    body_sections = 0
    paragraphs = 0
    para_shape_refs = style_refs = char_shape_refs = position_refs = 0
    total = 0
    records_total = 0
    for entry in sections:
        try:
            raw = cfb.stream(entry)
        except _ingress.IngressError as exc:
            raise CoverageError(exc.reason)
        if header.compressed:
            try:
                raw = _source._inflate(raw)
            except _source.CoverageError as exc:
                raise CoverageError(exc.reason)
        total += len(raw)
        if total > getattr(_source, "MAX_TOTAL_DECOMPRESSED_BYTES", 256 * 1024 * 1024):
            raise CoverageError("bodytext_decompressed_limit")
        try:
            envelope = _source._scan_records(raw)
        except _source.CoverageError as exc:
            raise CoverageError(exc.reason)
        if envelope.get("state") != "complete":
            # The reference claim depends on exact paragraph child/count
            # closure; an incomplete T89 envelope cannot be promoted to a
            # complete DocInfo/body reference result.
            raise CoverageError("bodytext.envelope_incomplete")
        current: dict[str, Any] | None = None
        for tag, level, payload in _iter_records(
                raw, max_records=getattr(_source, "MAX_RECORDS_PER_SECTION", 1_000_000),
                max_bytes=getattr(_source, "MAX_DECOMPRESSED_BYTES", 128 * 1024 * 1024)):
            records_total += 1
            if records_total > MAX_BODY_RECORDS_TOTAL:
                raise CoverageError("bodytext_record_limit")
            if tag == TAG_PARA_HEADER:
                if len(payload) != 24:
                    raise CoverageError("bodytext.paragraph_invalid")
                if current is not None:
                    # T89 has already enforced child count/order closure.
                    current = None
                para_shape_id = struct.unpack_from("<H", payload, 8)[0]
                style_id = payload[10]
                if para_shape_id >= definition_counts.get("para_shape", 0):
                    raise CoverageError("bodytext_reference_out_of_range")
                if style_id >= definition_counts.get("style", 0):
                    raise CoverageError("bodytext_reference_out_of_range")
                current = {"level": level, "char_shape": False}
                paragraphs += 1
                para_shape_refs += 1
                style_refs += 1
            elif tag == TAG_PARA_TEXT:
                if current is None or level != current["level"] + 1:
                    raise CoverageError("bodytext_paragraph_invalid")
            elif tag == TAG_PARA_CHAR_SHAPE:
                if current is None or level != current["level"] + 1:
                    raise CoverageError("bodytext_paragraph_invalid")
                if len(payload) % 8:
                    raise CoverageError("bodytext_paragraph_invalid")
                previous: int | None = None
                for offset in range(0, len(payload), 8):
                    position, shape_id = struct.unpack_from("<II", payload, offset)
                    if previous is None:
                        if position != 0:
                            raise CoverageError("bodytext_char_shape_position_invalid")
                    elif position <= previous:
                        raise CoverageError("bodytext_char_shape_position_invalid")
                    previous = position
                    if shape_id >= definition_counts.get("char_shape", 0):
                        raise CoverageError("bodytext_reference_out_of_range")
                    char_shape_refs += 1
                    position_refs += 1
                current["char_shape"] = True
        body_sections += 1
    return {
        "sections": body_sections,
        "paragraphs": paragraphs,
        "para_shape_refs": para_shape_refs,
        "style_refs": style_refs,
        "char_shape_refs": char_shape_refs,
        "position_refs": position_refs,
    }


def _scan_bytes(data: bytes) -> dict[str, Any]:
    source, (cfb, header) = _preflight(data)
    descriptor = _source_descriptor(source)
    docinfo_entry = _direct_docinfo(cfb)
    try:
        docinfo_raw = cfb.stream(docinfo_entry)
    except _ingress.IngressError as exc:
        raise CoverageError(exc.reason)
    if header.compressed:
        try:
            docinfo_raw = _source._inflate(docinfo_raw)
        except _source.CoverageError as exc:
            raise CoverageError(exc.reason)
    docinfo = _parse_docinfo(docinfo_raw, descriptor["version"])
    body = _body_records(cfb, header, docinfo["definition_counts"])
    supported = sorted([
        "docinfo.document_properties", "docinfo.id_mappings",
        "docinfo.definition_groups", "bodytext.para_header",
        "bodytext.para_text", "bodytext.para_char_shape",
    ])
    return {
        "schema": SCHEMA,
        "status": "analyzed",
        "source": descriptor,
        "scanner": SCANNER,
        "coverage": {
            "scope": CLAIM_SCOPE,
            "not_scanned_tokens": NOT_SCANNED_TOKENS,
            "state": "complete",
            "docinfo_records": docinfo["records"],
            "definition_counts": docinfo["definition_counts"],
            "bodytext_sections": body["sections"],
            "bodytext_paragraphs": body["paragraphs"],
            "bodytext_para_shape_refs": body["para_shape_refs"],
            "bodytext_style_refs": body["style_refs"],
            "bodytext_char_shape_refs": body["char_shape_refs"],
            "bodytext_char_shape_position_refs": body["position_refs"],
            "supported_tokens": supported,
            "blocking_tokens": [],
        },
        "eligibility": "unknown",
        "comparison": {"state": "unknown"},
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
    }


def inspect_path(path: str | Path) -> dict[str, Any]:
    try:
        data = _read_input_once(_coerce_path(path, "input_unavailable"))
        return _scan_bytes(data)
    except CoverageError as exc:
        return _base_refusal(exc.reason)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _validate_source(source: Any) -> dict[str, Any]:
    if (not isinstance(source, dict)
            or set(source) != {"format", "version", "bytes", "sha256",
                                "compressed", "security_flags"}
            or source.get("format") != "hwp"
            or not isinstance(source.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", source["version"]) is None
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not isinstance(source.get("sha256"), str)
            or SHA256_RE.fullmatch(source["sha256"]) is None
            or not isinstance(source.get("compressed"), bool)
            or source.get("security_flags") != []):
        raise CoverageError("receipt_source_invalid")
    return source


def _validate_coverage(value: Any, version: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != _COVERAGE_KEYS
            or value.get("scope") != CLAIM_SCOPE
            or value.get("not_scanned_tokens") != NOT_SCANNED_TOKENS
            or value.get("state") != "complete"):
        raise CoverageError("receipt_coverage_invalid")
    for key in ("docinfo_records", "bodytext_sections", "bodytext_paragraphs",
                "bodytext_para_shape_refs", "bodytext_style_refs",
                "bodytext_char_shape_refs", "bodytext_char_shape_position_refs"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise CoverageError("receipt_coverage_invalid")
    counts = value.get("definition_counts")
    expected_count_keys = set(ID_KEYS[:_id_key_count(version)]) | {"face_name.total"}
    if (not isinstance(counts, dict) or set(counts) != expected_count_keys
            or any(not isinstance(key, str) or key not in expected_count_keys
                   or isinstance(number, bool) or not isinstance(number, int)
                   or number < 0 or number > MAX_DEFINITION_COUNT
                   for key, number in counts.items())):
        raise CoverageError("receipt_coverage_invalid")
    if counts["face_name.total"] != sum(counts[key] for key in FACE_NAME_KEYS):
        raise CoverageError("receipt_coverage_invalid")
    if sum(counts[key] for key in ID_KEYS[:_id_key_count(version)]) > MAX_DEFINITION_TOTAL:
        raise CoverageError("receipt_coverage_invalid")
    for key in ("supported_tokens", "blocking_tokens"):
        items = value.get(key)
        allowed = _SUPPORTED_TOKENS if key == "supported_tokens" else _BLOCKING_TOKENS
        if (not isinstance(items, list)
                or any(not isinstance(item, str) or item not in allowed for item in items)
                or items != sorted(set(items))):
            raise CoverageError("receipt_coverage_invalid")
    return value


def _validate_receipt(path: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _TOP_KEYS:
        raise CoverageError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "analyzed"
            or payload.get("scanner") != SCANNER
            or payload.get("eligibility") != "unknown"
            or payload.get("comparison") != {"state": "unknown"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False):
        raise CoverageError("receipt_state_invalid")
    source = _validate_source(payload.get("source"))
    _validate_coverage(payload.get("coverage"), source["version"])
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
        run_info = run_path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISDIR(run_info.st_mode) or stat.S_ISLNK(run_info.st_mode)
                or getattr(run_info, "st_file_attributes", 0) & reparse):
            raise CoverageError("receipt_layout_invalid")
        children = list(run_path.iterdir())
        if len(children) != 1 or children[0].name != "receipt.json":
            raise CoverageError("receipt_layout_invalid")
        info = children[0].lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse):
            raise CoverageError("receipt_layout_invalid")
    except CoverageError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError):
        raise CoverageError("receipt_layout_invalid")
    return run_path, run_path / "receipt.json"


def _publish(root: Path, guard: dict[str, Any], run_id: str,
             payload: dict[str, Any], source_path: Path, captured_data: bytes) -> dict[str, Any]:
    def publish_from_stage(temp_name: str) -> dict[str, Any]:
        stage = Path(temp_name) / "publish" / run_id
        stage.mkdir(parents=True)
        staged = stage / "receipt.json"
        _core.write_bytes(staged, _json_bytes(payload))

        def check(g: dict[str, Any], *, refresh: bool = False) -> None:
            _core.check_root_guard(g, refresh=refresh, node_identity_fn=_core.node_identity)

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
                if rebound != captured_data:
                    raise CoverageError("input_changed")
                current, _ = _preflight(rebound)
                if _source_descriptor(current) != payload["source"]:
                    raise CoverageError("input_changed")
            except CoverageError as exc:
                raise _core.CoreError(exc.reason)

        run_path = root / run_id
        return _core.publish_owner_token_receipt(
            run_path, stage, payload, root_guard=guard, check_root_guard_fn=check,
            write_bytes_fn=write, node_identity_fn=_core.node_identity,
            same_identity_fn=_core.same_file_identity, remove_owned_fn=_core.remove_owned,
            rollback_fn=rollback,
            validate_receipt_fn=lambda path: _read_receipt(path, allow_hardlink=True),
            before_commit_fn=before_commit, token_prefix=".t90-owner-")

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
        # Publication is already committed once the owner token is removed;
        # cleanup of the staging directory must not turn that receipt into a
        # false refusal.
        if not committed:
            raise CoverageError("diagnostic_publish_failed")
    if result is None:
        raise CoverageError("diagnostic_publish_failed")
    return result


def inspect_and_publish(input_path: str | Path, *, coverage_root: str | Path,
                        run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(coverage_root, "diagnostic_root_invalid")
    source_path = _resolve_input_path(_coerce_path(input_path, "input_unavailable"))
    run_id = _validate_run_id(run_id)
    try:
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        if _path_overlap(root, source_path):
            raise CoverageError("input_root_overlap")
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard)
        data = _read_input_once(source_path)
        payload = _scan_bytes(data)
        _core.check_root_guard(guard)
        return _publish(root, guard, run_id, payload, source_path, data)
    except CoverageError:
        raise
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)


def verify_path(input_path: str | Path, *, coverage_root: str | Path,
                run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(coverage_root, "diagnostic_root_invalid")
    source_path = _resolve_input_path(_coerce_path(input_path, "input_unavailable"))
    run_id = _validate_run_id(run_id)
    try:
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        if _path_overlap(root, source_path):
            raise CoverageError("input_root_overlap")
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard)
        run_path, receipt_path = _public_run_layout(root, run_id)
        run_identity = _core.node_identity(run_path)
        payload, raw = _read_receipt(receipt_path)
        receipt_identity = _core.node_identity(receipt_path)
        data = _read_input_once(source_path)
        recomputed = _scan_bytes(data)
        if recomputed != payload:
            raise CoverageError("receipt_content_mismatch")
        final_data = _read_input_once(source_path)
        if final_data != data:
            raise CoverageError("input_changed")
        final_payload, final_raw = _read_receipt(receipt_path)
        final_run_identity = _core.node_identity(run_path)
        final_receipt_identity = _core.node_identity(receipt_path)
        if (final_payload != payload or final_raw != raw
                or not _core.same_file_identity(final_run_identity, run_identity)
                or not _core.same_file_identity(final_receipt_identity, receipt_identity)):
            raise CoverageError("receipt_changed")
        _core.check_root_guard(guard)
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
    parser = argparse.ArgumentParser(description="bounded receipt-only HWP DocInfo coverage")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="scan one HWP and publish a receipt")
    inspect.add_argument("input")
    inspect.add_argument("--coverage-root", required=True)
    inspect.add_argument("--run-id", required=True)
    verify = sub.add_parser("verify", help="rebind a receipt to current source bytes")
    verify.add_argument("input")
    verify.add_argument("--coverage-root", required=True)
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
            payload = inspect_and_publish(args.input, coverage_root=args.coverage_root,
                                          run_id=args.run_id)
        else:
            payload = verify_path(args.input, coverage_root=args.coverage_root,
                                  run_id=args.run_id)
        _print(payload)
        # Structural coverage is never a semantic eligibility success.
        return EXIT_REFUSED
    except CoverageError as exc:
        try:
            _print(_base_refusal(exc.reason))
        except CoverageError:
            pass
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
