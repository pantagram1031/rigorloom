#!/usr/bin/env python3
"""Receipt-only, fail-closed HWP5 source coverage (T89).

T89 is deliberately a source-side *coverage* scanner, not a converter or a
general HWP validator.  It captures the input once, runs the existing T85 CFB
and FileHeader preflight on those bytes, then scans only direct
``BodyText/Section0..N`` streams.  No external parser is installed, invoked,
or downloaded.  Successful output is a privacy-safe receipt under a
pre-created ``hwp-source-coverage`` leaf; source text, raw record tags,
control IDs, paths, and process output never enter the receipt.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
from typing import Any, Iterable
import zlib

try:  # The scripts directory is directly importable from the CLI.
    import diagnostic_candidate_core as _core
    import hwp_ingress as _ingress
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_ingress as _ingress


SCHEMA = "rigorloom/hwp-source-coverage/v1"
ROOT_LEAF = "hwp-source-coverage"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
MAX_INPUT_BYTES = getattr(_ingress, "MAX_INPUT_BYTES", 256 * 1024 * 1024)
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_SECTION_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TOTAL_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_SECTIONS = 1024
MAX_RECORDS_PER_SECTION = 1_000_000
MAX_RECORDS_TOTAL = 2_000_000
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SCANNER = {
    "name": "rigorloom_hwp5_record_coverage",
    "version": 1,
    "target": {
        "package": "syhwp",
        "version": "0.0.7",
        "commit": "d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed",
    },
    "execution": "independent_no_external_tool",
}

# HWP5 record IDs.  These names are schema-owned tokens; numeric IDs are
# intentionally never emitted in a receipt.
TAG_DOCUMENT_PROPERTIES = 0x10
TAG_ID_MAPPINGS = 0x11
TAG_BIN_DATA = 0x12
TAG_FACE_NAME = 0x13
TAG_BORDER_FILL = 0x14
TAG_CHAR_SHAPE = 0x15
TAG_TAB_DEF = 0x16
TAG_NUMBERING = 0x17
TAG_BULLET = 0x18
TAG_PARA_SHAPE = 0x19
TAG_STYLE = 0x1A
TAG_DOC_DATA = 0x1B
TAG_DISTRIBUTE_DOC_DATA = 0x1C
TAG_PARA_HEADER = 0x42
TAG_PARA_TEXT = 0x43
TAG_PARA_CHAR_SHAPE = 0x44
TAG_PARA_LINE_SEG = 0x45
TAG_PARA_RANGE_TAG = 0x46
TAG_CTRL_HEADER = 0x47
TAG_LIST_HEADER = 0x48
TAG_PAGE_DEF = 0x49
TAG_FOOTNOTE_SHAPE = 0x4A
TAG_PAGE_BORDER_FILL = 0x4B
TAG_SHAPE_COMPONENT = 0x4C
TAG_TABLE = 0x4D
TAG_SHAPE_COMPONENT_LINE = 0x4E
TAG_SHAPE_COMPONENT_RECTANGLE = 0x4F
TAG_SHAPE_COMPONENT_ELLIPSE = 0x50
TAG_SHAPE_COMPONENT_ARC = 0x51
TAG_SHAPE_COMPONENT_POLYGON = 0x52
TAG_SHAPE_COMPONENT_CURVE = 0x53
TAG_SHAPE_COMPONENT_OLE = 0x54
TAG_SHAPE_COMPONENT_PICTURE = 0x55
TAG_SHAPE_COMPONENT_CONTAINER = 0x56
TAG_CTRL_DATA = 0x57
TAG_RESERVED = 0x59
TAG_TEXTART = 0x5A
TAG_FORBIDDEN_CHAR = 0x5E
# These controls are identified by CtrlID values under TAG_CTRL_HEADER rather
# than by standalone records; aliases keep the token inventory vocabulary
# explicit for callers that need to name the reviewed surfaces.
TAG_SECTION_DEFINE = TAG_CTRL_HEADER
TAG_COLUMN_DEFINE = TAG_CTRL_HEADER
TAG_TABLE_CONTROL = TAG_CTRL_HEADER
TAG_SHEET_CONTROL = TAG_CTRL_HEADER
TAG_LINE_INFO = TAG_CTRL_HEADER
TAG_HIDDEN_COMMENT = TAG_CTRL_HEADER
TAG_HEADER_FOOTER = TAG_CTRL_HEADER
TAG_FOOTNOTE = TAG_CTRL_HEADER
TAG_AUTO_NUMBER = TAG_CTRL_HEADER
TAG_NEW_NUMBER = TAG_CTRL_HEADER
TAG_PAGE_HIDE = TAG_CTRL_HEADER
TAG_PAGE_ODD_EVEN = TAG_CTRL_HEADER
TAG_PAGE_NUMBER = TAG_CTRL_HEADER
TAG_EQEDIT = 0x58
TAG_FORM_OBJECT = 0x5B
TAG_MEMO_SHAPE = 0x5C
TAG_MEMO_LIST = 0x5D
TAG_CHART_DATA = 0x5F
TAG_SHAPE_COMPONENT_UNKNOWN = 0x73

_TAG_TOKENS: dict[int, str] = {
    TAG_DOCUMENT_PROPERTIES: "document.properties",
    TAG_ID_MAPPINGS: "document.id_mappings",
    TAG_BIN_DATA: "document.bin_data",
    TAG_FACE_NAME: "document.face_name",
    TAG_BORDER_FILL: "document.border_fill",
    TAG_CHAR_SHAPE: "document.char_shape",
    TAG_TAB_DEF: "document.tab_def",
    TAG_NUMBERING: "document.numbering",
    TAG_BULLET: "document.bullet",
    TAG_PARA_SHAPE: "document.para_shape",
    TAG_STYLE: "document.style",
    TAG_DOC_DATA: "document.doc_data",
    TAG_DISTRIBUTE_DOC_DATA: "document.distribute_doc_data",
    TAG_PARA_HEADER: "paragraph.header",
    TAG_PARA_TEXT: "paragraph.text",
    TAG_PARA_CHAR_SHAPE: "paragraph.char_shape",
    TAG_PARA_LINE_SEG: "paragraph.line_seg",
    TAG_PARA_RANGE_TAG: "paragraph.range_tag",
    TAG_CTRL_HEADER: "control.header",
    TAG_LIST_HEADER: "control.list_header",
    TAG_PAGE_DEF: "section.page_def",
    TAG_FOOTNOTE_SHAPE: "story.footnote_shape",
    TAG_PAGE_BORDER_FILL: "section.page_border_fill",
    TAG_TABLE: "object.table",
    TAG_SHAPE_COMPONENT: "object.shape_component",
    TAG_SHAPE_COMPONENT_LINE: "object.line",
    TAG_SHAPE_COMPONENT_RECTANGLE: "object.rectangle",
    TAG_SHAPE_COMPONENT_ELLIPSE: "object.ellipse",
    TAG_SHAPE_COMPONENT_ARC: "object.arc",
    TAG_SHAPE_COMPONENT_POLYGON: "object.polygon",
    TAG_SHAPE_COMPONENT_CURVE: "object.curve",
    TAG_SHAPE_COMPONENT_OLE: "object.ole",
    TAG_SHAPE_COMPONENT_PICTURE: "object.picture",
    TAG_SHAPE_COMPONENT_CONTAINER: "object.container",
    TAG_CTRL_DATA: "control.data",
    TAG_RESERVED: "record.reserved",
    TAG_TEXTART: "object.textart",
    TAG_FORBIDDEN_CHAR: "document.forbidden_char",
    TAG_EQEDIT: "object.equation",
    TAG_FORM_OBJECT: "object.form",
    TAG_MEMO_SHAPE: "story.memo_shape",
    TAG_MEMO_LIST: "story.memo_list",
    TAG_CHART_DATA: "object.chart",
    TAG_SHAPE_COMPONENT_UNKNOWN: "object.shape_component_unknown",
}

_SUPPORTED_RECORDS = {
    # The v1 proof surface is intentionally tiny.  Section/page furniture,
    # range tags, and every CTRL_HEADER stay outside the claim until their
    # complete grammar is independently reviewed.
    TAG_PARA_HEADER, TAG_PARA_TEXT, TAG_PARA_CHAR_SHAPE, TAG_PARA_LINE_SEG,
}

# CtrlID is a UINT32 in the format.  The text representation in source files
# is commonly stored in reverse byte order; accept both byte presentations but
# never expose either raw form.  A reversed form is not a second semantic ID.
_CTRL_ID_TOKENS: dict[bytes, str] = {
    b"tbl ": "table",
    b" lbt": "table",
    b"eqed": "equation",
    b"deqe": "equation",
    b"gso ": "picture",
    b" osg": "picture",
    b"$pic": "picture",
    b"cip$": "picture",
    b"$ole": "object",
    b"elo$": "object",
    b"$con": "object",
    b"noc$": "object",
    b"secd": "section",
    b"dces": "section",
    b"cold": "section",
    b"dloc": "section",
    b"head": "story",
    b"daeh": "story",
    b"foot": "story",
    b"toof": "story",
    b"fn  ": "story",
    b"  nf": "story",
    b"en  ": "story",
    b"  ne": "story",
    b"atno": "control",
    b"onta": "control",
    b"nwno": "control",
    b"onwn": "control",
    b"pghd": "control",
    b"dhgp": "control",
    b"pgct": "control",
    b"tcps": "control",
    b"spct": "control",
    b"idxm": "field",
    b"mxdi": "field",
    b"bokm": "field",
    b"mkob": "field",
    b"%beg": "field",
    b"geb%": "field",
    b"%end": "field",
    b"dne%": "field",
}

_RECORD_COUNT_TOKENS = frozenset(_TAG_TOKENS.values()) | {"record.unknown"}
_CTRL_COUNT_TOKENS = frozenset({
    "table", "equation", "picture", "object", "section", "story",
    "field", "control", "unknown",
})
_TEXT_CONTROL_TOKENS = frozenset({
    "line_break", "paragraph_break", "tab", "field", "story",
    "object", "section", "unknown", "char_control",
})
COVERAGE_SCOPE = "bodytext_record_envelope_v1"
NOT_SCANNED_TOKENS = [
    "bodytext.paragraph_header_auxiliary_fields",
    "docinfo.reference_graph", "docinfo.numbering_bullets", "docinfo.styles",
]

# These are the only tokens a v1 receipt may carry.  Keeping the vocabulary
# closed is important: a verifier must not bless an adapter-invented token
# merely because it is a string.
_SUPPORTED_TOKEN_VOCAB = frozenset({
    "paragraph.header", "paragraph.text", "paragraph.char_shape",
    "paragraph.line_seg",
})
_BLOCKING_TOKEN_VOCAB = frozenset(_TAG_TOKENS.values()) | frozenset({
    "record.unknown", "ctrl.unknown", "control.unknown", "control.tab",
    "control.field", "control.story", "control.object", "control.section",
    "control.char_control", "control.line_break", "control.paragraph_break",
    "control.unknown", "control.list", "ctrl.table", "ctrl.equation",
    "ctrl.picture", "ctrl.object", "ctrl.section", "ctrl.story",
    "ctrl.field", "ctrl.control", "paragraph.missing",
    "paragraph.header_missing", "paragraph.text_missing",
    "paragraph.text_duplicate", "paragraph.level_mismatch",
    "paragraph.text_count_mismatch", "paragraph.control_mask_mismatch",
    "paragraph.char_shape_count_mismatch", "paragraph.line_count_mismatch",
    "paragraph.range_count_mismatch", "text.leading_whitespace",
    "text.trailing_whitespace", "text.repeated_whitespace",
    "paragraph.external_style_reference",
    "paragraph.break_flags_unscanned",
    "paragraph.header_high_flag",
    "paragraph.child_order_mismatch",
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


def _source_descriptor(source: Any) -> dict[str, Any]:
    try:
        descriptor = source.descriptor()
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
    return {
        "format": "hwp", "version": None, "bytes": None,
        "sha256": None, "compressed": None, "security_flags": [],
    }


def _base_refusal(reason: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "refused",
        "reason": reason,
        "source": source or _empty_source(),
        "scanner": SCANNER,
        "coverage": {
            "scope": COVERAGE_SCOPE, "not_scanned_tokens": NOT_SCANNED_TOKENS,
            "state": "incomplete", "sections": 0, "records": 0,
            "paragraphs": 0, "record_counts": {}, "ctrl_header_counts": {},
            "para_text_control_counts": {}, "supported_tokens": [],
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
    """Resolve one regular HWP path without any symlink/reparse ancestor."""
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
        return _core.read_regular_once(
            resolved, MAX_INPUT_BYTES, "input_unavailable")
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)


def _preflight(data: bytes) -> tuple[Any, Any]:
    if not isinstance(data, bytes) or len(data) == 0:
        raise CoverageError("input_empty")
    try:
        # Use the public T85 parser first; this is the strict FileHeader/CFB
        # gate.  The second in-memory view exposes only its validated stream
        # handles; it does not reread or reopen the source path.
        source = _ingress.parse_hwp_bytes(data)
        cfb = _ingress._Cfb(data)
        fileheader = cfb.fileheader()
    except _ingress.IngressError as exc:
        raise CoverageError(exc.reason)
    except (OSError, ValueError, TypeError, struct.error):
        raise CoverageError("preflight_failed")
    return source, (cfb, fileheader)


def _direct_sections(cfb: Any) -> list[Any]:
    try:
        root = cfb.root
        root_children = [cfb.directory[i] for i in cfb._tree_nodes(root.child)]
        bodies = [entry for entry in root_children if entry.name == "BodyText"]
        if len(bodies) != 1 or bodies[0].kind != 1:
            raise CoverageError("bodytext_invalid")
        body = bodies[0]
        children = [cfb.directory[i] for i in cfb._tree_nodes(body.child)]
    except CoverageError:
        raise
    except (AttributeError, TypeError, ValueError):
        raise CoverageError("bodytext_invalid")
    if not children:
        raise CoverageError("bodytext_sections_missing")
    if len(children) > MAX_SECTIONS:
        raise CoverageError("section_limit")
    by_number: dict[int, Any] = {}
    for entry in children:
        # The direct-child surface is exact: aliases, case variants, and
        # padded numbers are not equivalent spellings of a Section stream.
        match = re.fullmatch(r"Section(?:0|[1-9]\d*)", entry.name)
        if match is None or entry.kind != 2:
            raise CoverageError("section_surface_unsupported")
        number = int(entry.name[len("Section"):])
        if number in by_number:
            raise CoverageError("section_alias")
        by_number[number] = entry
    expected = list(range(len(by_number)))
    if sorted(by_number) != expected:
        raise CoverageError("section_gap")
    sections = [by_number[index] for index in expected]
    if any(entry.size <= 0 for entry in sections):
        raise CoverageError("section_empty")
    return sections


def _inflate(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_SECTION_BYTES:
        raise CoverageError("section_stream_invalid")
    try:
        decoder = zlib.decompressobj(wbits=-15)
        data = decoder.decompress(raw, MAX_DECOMPRESSED_BYTES + 1)
        if len(data) > MAX_DECOMPRESSED_BYTES:
            raise CoverageError("section_decompressed_too_large")
        tail = decoder.flush()
    except CoverageError:
        raise
    except (zlib.error, ValueError, TypeError):
        raise CoverageError("section_deflate_invalid")
    if len(data) + len(tail) > MAX_DECOMPRESSED_BYTES:
        raise CoverageError("section_decompressed_too_large")
    if not decoder.eof or decoder.unconsumed_tail or tail:
        # ``flush`` should be empty for a complete raw stream; requiring it
        # here catches an implementation that silently accepts trailing data.
        raise CoverageError("section_deflate_trailing")
    trailer = decoder.unused_data
    if trailer:
        if len(trailer) != 8:
            raise CoverageError("section_deflate_trailing")
        expected_crc, expected_size = struct.unpack("<II", trailer)
        actual_crc = zlib.crc32(data) & 0xFFFFFFFF
        if expected_crc != actual_crc or expected_size != (len(data) & 0xFFFFFFFF):
            raise CoverageError("section_deflate_trailer_invalid")
    return data


def _control_token(code: int) -> str:
    if code == 0x09:
        return "tab"
    if code == 0x0A:
        return "line_break"
    if code == 0x0D:
        return "paragraph_break"
    if code in (0x03, 0x04, 0x05, 0x06, 0x07):
        return "field"
    if code == 0x02:
        return "section"
    if code in (0x10, 0x11):
        return "story"
    if code == 0x0B or code == 0x0C or 0x0E <= code <= 0x17:
        return "object"
    if 0x18 <= code <= 0x1F:
        return "char_control"
    return "unknown"


def _scan_para_text(payload: bytes, text_counts: Counter[str], blocking: set[str],
                    *, expected_count: int | None, control_mask: int | None) -> int:
    if len(payload) % 2:
        raise CoverageError("record_odd_payload")
    offset = 0
    units = 0
    saw_control = False
    saw_text = False
    previous_whitespace = False
    first_text = True
    trailing_whitespace = False
    while offset < len(payload):
        if len(payload) - offset < 2:
            raise CoverageError("para_text_truncated")
        code = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
        units += 1
        if code < 0x20:
            saw_control = True
            token = _control_token(code)
            text_counts[token] += 1
            # v1 has no lossless representation for any embedded control,
            # including line/paragraph breaks.  Inventory them, but fail
            # closed for eligibility.
            blocking.add(f"control.{token}")
            if code not in (0x00, 0x0A, 0x0D) and not 0x18 <= code <= 0x1F:
                if len(payload) - offset < 14:
                    raise CoverageError("para_text_control_truncated")
                offset += 14
                # Extended controls occupy eight UTF-16 code units in the
                # paragraph character count (marker plus seven payload units).
                units += 7
            trailing_whitespace = False
            continue
        if 0xD800 <= code <= 0xDBFF:
            # UTF-16 scalar validation is deliberately performed on the wire
            # units; an unpaired surrogate is not silently treated as text.
            if len(payload) - offset < 2:
                raise CoverageError("para_text_invalid_utf16")
            low = struct.unpack_from("<H", payload, offset)[0]
            if not 0xDC00 <= low <= 0xDFFF:
                raise CoverageError("para_text_invalid_utf16")
            offset += 2
            units += 1
            saw_text = True
            first_text = False
            trailing_whitespace = False
            previous_whitespace = False
            continue
        if 0xDC00 <= code <= 0xDFFF:
            raise CoverageError("para_text_invalid_utf16")
        saw_text = True
        is_whitespace = chr(code).isspace()
        if is_whitespace:
            if first_text:
                blocking.add("text.leading_whitespace")
            if previous_whitespace:
                blocking.add("text.repeated_whitespace")
            trailing_whitespace = True
        else:
            trailing_whitespace = False
        previous_whitespace = is_whitespace
        first_text = False
    if saw_text and trailing_whitespace:
        blocking.add("text.trailing_whitespace")
    if expected_count is not None and expected_count != units:
        blocking.add("paragraph.text_count_mismatch")
    if control_mask is not None and bool(control_mask) != saw_control:
        blocking.add("paragraph.control_mask_mismatch")
    return units


def _ctrl_token(payload: bytes) -> str:
    if len(payload) < 4:
        raise CoverageError("ctrl_header_truncated")
    return _CTRL_ID_TOKENS.get(payload[:4], "unknown")


def _finalize_paragraph(current: dict[str, Any] | None, state: str,
                        blocking: set[str]) -> str:
    """Close one paragraph only after all declared child counts are known."""
    if current is None:
        blocking.add("paragraph.missing")
        return "incomplete"
    if not current["text_seen"]:
        blocking.add("paragraph.text_missing")
        state = "incomplete"
    checks = (
        ("char_shape_seen", "char_shape_count", "paragraph.char_shape_count_mismatch"),
        ("line_seen", "line_count", "paragraph.line_count_mismatch"),
        ("range_seen", "range_count", "paragraph.range_count_mismatch"),
    )
    for seen_key, expected_key, token in checks:
        if current[seen_key] != current[expected_key]:
            blocking.add(token)
            state = "incomplete"
    return state


def _scan_records(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_DECOMPRESSED_BYTES:
        raise CoverageError("section_empty")
    records = 0
    paragraphs = 0
    previous_level: int | None = None
    current: dict[str, Any] | None = None
    state = "complete"
    record_counts: Counter[str] = Counter()
    ctrl_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    supported: set[str] = set()
    blocking: set[str] = set()
    offset = 0
    while offset < len(raw):
        if records >= MAX_RECORDS_PER_SECTION:
            raise CoverageError("record_limit")
        if len(raw) - offset < 4:
            raise CoverageError("record_header_truncated")
        header = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        if previous_level is None:
            if level != 0:
                raise CoverageError("record_level_jump")
        elif level > previous_level + 1:
            raise CoverageError("record_level_jump")
        previous_level = level
        if size == 0xFFF:
            if len(raw) - offset < 4:
                raise CoverageError("record_extended_size_truncated")
            size = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
        if size > MAX_DECOMPRESSED_BYTES or size > len(raw) - offset:
            raise CoverageError("record_payload_truncated")
        payload = raw[offset:offset + size]
        offset += size
        records += 1
        token = _TAG_TOKENS.get(tag, "record.unknown")
        record_counts[token] += 1
        if tag in _SUPPORTED_RECORDS:
            supported.add(token)
        elif tag not in _TAG_TOKENS:
            blocking.add("record.unknown")
        else:
            blocking.add(token)

        if tag == TAG_PARA_HEADER:
            if len(payload) != 24:
                raise CoverageError("para_header_shape_unsupported")
            state = _finalize_paragraph(current, state, blocking) \
                if current is not None else state
            char_count_raw = struct.unpack_from("<I", payload, 0)[0]
            if char_count_raw & 0x80000000:
                state = "incomplete"
                blocking.add("paragraph.header_high_flag")
            char_count = char_count_raw & 0x7FFFFFFF
            control_mask = struct.unpack_from("<I", payload, 4)[0]
            para_shape_id = struct.unpack_from("<H", payload, 8)[0]
            style_id = payload[10]
            break_flags = payload[11]
            char_shape_count = struct.unpack_from("<H", payload, 12)[0]
            range_count = struct.unpack_from("<H", payload, 14)[0]
            line_count = struct.unpack_from("<H", payload, 16)[0]
            current = {
                "text_seen": False,
                "phase": "header",
                "level": level,
                "char_count": char_count,
                "control_mask": control_mask,
                "para_shape_id": para_shape_id,
                "style_id": style_id,
                "char_shape_count": char_shape_count,
                "range_count": range_count,
                "line_count": line_count,
                "char_shape_seen": 0,
                "range_seen": 0,
                "line_seen": 0,
            }
            if para_shape_id or style_id:
                state = "incomplete"
                blocking.add("paragraph.external_style_reference")
            if break_flags:
                state = "incomplete"
                blocking.add("paragraph.break_flags_unscanned")
            if level != 0:
                state = "incomplete"
                blocking.add("paragraph.level_mismatch")
            paragraphs += 1
        elif tag == TAG_PARA_TEXT:
            if current is None:
                state = "incomplete"
                blocking.add("paragraph.header_missing")
                _scan_para_text(payload, text_counts, blocking,
                                expected_count=None, control_mask=None)
            else:
                if level != current["level"] + 1:
                    state = "incomplete"
                    blocking.add("paragraph.level_mismatch")
                if current["phase"] != "header":
                    state = "incomplete"
                    blocking.add("paragraph.child_order_mismatch")
                if current["text_seen"]:
                    state = "incomplete"
                    blocking.add("paragraph.text_duplicate")
                current["text_seen"] = True
                current["phase"] = "text"
                _scan_para_text(payload, text_counts, blocking,
                                expected_count=current["char_count"],
                                control_mask=current["control_mask"])
        elif tag == TAG_PARA_CHAR_SHAPE:
            if current is None:
                state = "incomplete"
                blocking.add("paragraph.header_missing")
            else:
                if level != current["level"] + 1:
                    state = "incomplete"
                    blocking.add("paragraph.level_mismatch")
                if (current["phase"] != "text"
                        or current["char_shape_count"] == 0):
                    state = "incomplete"
                    blocking.add("paragraph.child_order_mismatch")
                current["phase"] = "char_shape"
                current["char_shape_seen"] += len(payload) // 8
                if len(payload) % 8:
                    raise CoverageError("para_char_shape_truncated")
        elif tag == TAG_PARA_LINE_SEG:
            if current is None:
                state = "incomplete"
                blocking.add("paragraph.header_missing")
            else:
                if level != current["level"] + 1:
                    state = "incomplete"
                    blocking.add("paragraph.level_mismatch")
                expected_phase = ("char_shape"
                                  if current["char_shape_count"] else "text")
                if (current["phase"] != expected_phase
                        or current["line_count"] == 0):
                    state = "incomplete"
                    blocking.add("paragraph.child_order_mismatch")
                current["phase"] = "line_seg"
                current["line_seen"] += len(payload) // 36
                if len(payload) % 36:
                    raise CoverageError("para_line_seg_truncated")
        elif tag == TAG_PARA_RANGE_TAG:
            if current is None:
                state = "incomplete"
                blocking.add("paragraph.header_missing")
            else:
                if level != current["level"] + 1:
                    state = "incomplete"
                    blocking.add("paragraph.level_mismatch")
                if current["line_count"]:
                    expected_phase = "line_seg"
                elif current["char_shape_count"]:
                    expected_phase = "char_shape"
                else:
                    expected_phase = "text"
                if (current["phase"] != expected_phase
                        or current["range_count"] == 0):
                    state = "incomplete"
                    blocking.add("paragraph.child_order_mismatch")
                current["phase"] = "range_tag"
                current["range_seen"] += len(payload) // 12
                if len(payload) % 12:
                    raise CoverageError("para_range_tag_truncated")
        elif tag == TAG_CTRL_HEADER:
            token = _ctrl_token(payload)
            ctrl_counts[token] += 1
            if token not in _CTRL_COUNT_TOKENS:
                raise CoverageError("ctrl_header_invalid")
            blocking.add(f"ctrl.{token}")
        elif tag == TAG_LIST_HEADER:
            blocking.add("control.list")
        elif tag in _TAG_TOKENS and tag not in _SUPPORTED_RECORDS:
            # A known but non-semantic/object/story surface is complete to
            # inventory, but outside the v1 text-only eligibility envelope.
            pass
    state = _finalize_paragraph(current, state, blocking)
    for item in (record_counts, ctrl_counts, text_counts):
        if any(key not in (_RECORD_COUNT_TOKENS | _CTRL_COUNT_TOKENS
                           | _TEXT_CONTROL_TOKENS)
               for key in item):
            raise CoverageError("coverage_token_invalid")
    if (not supported <= _SUPPORTED_TOKEN_VOCAB
            or not blocking <= _BLOCKING_TOKEN_VOCAB):
        raise CoverageError("coverage_token_invalid")
    if any(token.startswith("record.") or token.startswith("ctrl.")
           or token.startswith("control.") or token.startswith("object.")
           or token.startswith("story.") or token.startswith("paragraph.")
           for token in blocking):
        if ("record.unknown" in blocking or "ctrl.unknown" in blocking
                or "control.unknown" in blocking):
            eligibility = "unknown"
        else:
            eligibility = "ineligible"
    else:
        eligibility = "unknown"
    if eligibility == "unknown":
        state = "complete" if state == "complete" else state
    return {
        "state": state,
        "records": records,
        "paragraphs": paragraphs,
        "record_counts": dict(sorted(record_counts.items())),
        "ctrl_header_counts": dict(sorted(ctrl_counts.items())),
        "para_text_control_counts": dict(sorted(text_counts.items())),
        "supported_tokens": sorted(supported),
        "blocking_tokens": sorted(blocking),
        "eligibility": eligibility,
    }


def _scan_bytes(data: bytes) -> dict[str, Any]:
    source, (cfb, fileheader) = _preflight(data)
    source_descriptor = _source_descriptor(source)
    sections = _direct_sections(cfb)
    all_records: Counter[str] = Counter()
    all_ctrl: Counter[str] = Counter()
    all_text: Counter[str] = Counter()
    supported: set[str] = set()
    blocking: set[str] = set()
    states: list[str] = []
    records = paragraphs = 0
    total_decompressed = 0
    for entry in sections:
        try:
            raw = cfb.stream(entry)
        except _ingress.IngressError as exc:
            raise CoverageError(exc.reason)
        if fileheader.compressed:
            raw = _inflate(raw)
        total_decompressed += len(raw)
        if total_decompressed > MAX_TOTAL_DECOMPRESSED_BYTES:
            raise CoverageError("document_decompressed_too_large")
        result = _scan_records(raw)
        states.append(result["state"])
        records += result["records"]
        paragraphs += result["paragraphs"]
        all_records.update(result["record_counts"])
        all_ctrl.update(result["ctrl_header_counts"])
        all_text.update(result["para_text_control_counts"])
        supported.update(result["supported_tokens"])
        blocking.update(result["blocking_tokens"])
        if records > MAX_RECORDS_TOTAL:
            raise CoverageError("record_limit")
    if ("record.unknown" in blocking or "ctrl.unknown" in blocking
            or "control.unknown" in blocking):
        eligibility = "unknown"
    elif blocking or any(state != "complete" for state in states):
        eligibility = "ineligible"
    else:
        # DocInfo paragraph-shape/style/numbering references are intentionally
        # outside T89's BodyText-only scope.  A clean envelope is therefore
        # unknown, never a semantic eligibility claim.
        eligibility = "unknown"
    return {
        "schema": SCHEMA,
        "status": "analyzed",
        "source": source_descriptor,
        "scanner": SCANNER,
        "coverage": {
            "scope": COVERAGE_SCOPE,
            "not_scanned_tokens": NOT_SCANNED_TOKENS,
            "state": "complete" if all(state == "complete" for state in states)
            else "incomplete",
            "sections": len(sections),
            "records": records,
            "paragraphs": paragraphs,
            "record_counts": dict(sorted(all_records.items())),
            "ctrl_header_counts": dict(sorted(all_ctrl.items())),
            "para_text_control_counts": dict(sorted(all_text.items())),
            "supported_tokens": sorted(supported),
            "blocking_tokens": sorted(blocking),
        },
        "eligibility": eligibility,
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


def _validate_coverage(payload: Any) -> dict[str, Any]:
    if (not isinstance(payload, dict)
            or set(payload) != {"scope", "not_scanned_tokens", "state", "sections", "records", "paragraphs",
                                "record_counts", "ctrl_header_counts",
                                "para_text_control_counts", "supported_tokens",
                                "blocking_tokens"}
            or payload.get("scope") != COVERAGE_SCOPE
            or payload.get("not_scanned_tokens") != NOT_SCANNED_TOKENS
            or payload.get("state") not in {"complete", "incomplete"}):
        raise CoverageError("receipt_coverage_invalid")
    for field in ("sections", "records", "paragraphs"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CoverageError("receipt_coverage_invalid")
    for field, allowed in (("record_counts", _RECORD_COUNT_TOKENS),
                           ("ctrl_header_counts", _CTRL_COUNT_TOKENS),
                           ("para_text_control_counts", _TEXT_CONTROL_TOKENS)):
        value = payload.get(field)
        if (not isinstance(value, dict)
                or any(not isinstance(key, str) or key not in allowed
                       or isinstance(number, bool) or not isinstance(number, int)
                       or number < 0 for key, number in value.items())):
            raise CoverageError("receipt_coverage_invalid")
    for field in ("supported_tokens", "blocking_tokens"):
        value = payload.get(field)
        allowed = (_SUPPORTED_TOKEN_VOCAB if field == "supported_tokens"
                   else _BLOCKING_TOKEN_VOCAB)
        if (not isinstance(value, list)
                or any(not isinstance(item, str) or item not in allowed
                       for item in value)
                or value != sorted(set(value))):
            raise CoverageError("receipt_coverage_invalid")
    return payload


def _validate_receipt(path: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
            "schema", "status", "source", "scanner", "coverage",
            "eligibility", "comparison", "render", "proof_grade",
            "submission_grade"}:
        raise CoverageError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "analyzed"
            or payload.get("scanner") != SCANNER
            or payload.get("eligibility") not in {"ineligible", "unknown"}
            or payload.get("comparison") != {"state": "unknown"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False):
        raise CoverageError("receipt_state_invalid")
    source = payload.get("source")
    if (not isinstance(source, dict) or set(source) != {
            "format", "version", "bytes", "sha256", "compressed", "security_flags"}
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
    coverage = _validate_coverage(payload.get("coverage"))
    expected = (
        "unknown" if ("record.unknown" in coverage["blocking_tokens"]
                       or "ctrl.unknown" in coverage["blocking_tokens"]
                       or "control.unknown" in coverage["blocking_tokens"]
                       or (not coverage["blocking_tokens"]
                           and coverage["state"] == "complete"))
        else "ineligible")
    if payload["eligibility"] != expected:
        raise CoverageError("receipt_state_invalid")
    if (path.name != "receipt.json"
            or RUN_ID_RE.fullmatch(path.parent.name or "") is None):
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
    """Return a stable-looking receipt-only run layout without following links."""
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


def _publish(root_input: Path, root: Path, guard: dict[str, Any], run_id: str,
             payload: dict[str, Any], source_path: Path,
             captured_data: bytes) -> dict[str, Any]:
    def publish_from_stage(temp_name: str) -> dict[str, Any]:
        stage = Path(temp_name) / "publish" / run_id
        stage.mkdir(parents=True)
        staged = stage / "receipt.json"
        _core.write_bytes(staged, _json_bytes(payload))

        def check(g: dict[str, Any], *, refresh: bool = False) -> None:
            _core.check_root_guard(g, refresh=refresh,
                                   node_identity_fn=_core.node_identity)

        def write(path: Path, data: bytes) -> None:
            _core.write_bytes(path, data, exists_reason="run_exists",
                              write_reason="diagnostic_publish_failed")

        def rollback(run_path, reserved, receipt, receipt_identity,
                     candidate, candidate_identity, token=None,
                     token_identity=None):
            _core.rollback_publication(
                run_path, reserved, receipt, receipt_identity,
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
            run_path, stage, payload, root_guard=guard,
            check_root_guard_fn=check, write_bytes_fn=write,
            node_identity_fn=_core.node_identity,
            same_identity_fn=_core.same_file_identity,
            remove_owned_fn=_core.remove_owned,
            rollback_fn=rollback,
            validate_receipt_fn=lambda path: _read_receipt(path, allow_hardlink=True),
            before_commit_fn=before_commit,
            token_prefix=".t89-owner-")

    # The owner-token publisher detaches the staged hard link and validates
    # the public one-link receipt before it commits.  A later best-effort
    # TemporaryDirectory cleanup failure must not turn that committed result
    # into a false refusal while leaving a valid receipt on disk.
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


def inspect_and_publish(input_path: str | Path, *, coverage_root: str | Path,
                        run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(coverage_root, "diagnostic_root_invalid")
    source_path = _resolve_input_path(
        _coerce_path(input_path, "input_unavailable"))
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
        return _publish(root_input, root, guard, run_id, payload,
                        source_path, data)
    except CoverageError:
        raise
    except _core.CoreError as exc:
        raise CoverageError(exc.reason)


def verify_path(input_path: str | Path, *, coverage_root: str | Path,
                run_id: str) -> dict[str, Any]:
    root_input = _coerce_path(coverage_root, "diagnostic_root_invalid")
    source_path = _resolve_input_path(
        _coerce_path(input_path, "input_unavailable"))
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
        # Rebind the exact source bytes and deterministic receipt before the
        # final return; a same-inode replacement or forged receipt must not
        # pass merely because the first read happened to match.
        final_data = _read_input_once(source_path)
        if final_data != data:
            raise CoverageError("input_changed")
        final_payload, final_raw = _read_receipt(receipt_path)
        final_run_identity = _core.node_identity(run_path)
        final_receipt_identity = _core.node_identity(receipt_path)
        if (final_payload != payload or final_raw != raw
                or not _core.same_file_identity(final_run_identity, run_identity)
                or not _core.same_file_identity(final_receipt_identity,
                                                receipt_identity)):
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
    parser = argparse.ArgumentParser(
        description="bounded receipt-only HWP source coverage (no external parser)")
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
        if exc.code == 0:
            return EXIT_OK
        return EXIT_USAGE
    try:
        if args.command == "inspect":
            payload = inspect_and_publish(
                args.input, coverage_root=args.coverage_root, run_id=args.run_id)
        else:
            payload = verify_path(
                args.input, coverage_root=args.coverage_root, run_id=args.run_id)
        _print(payload)
        # Decision A: v1 never emits a semantic eligibility success.  Even a
        # complete BodyText envelope remains unknown until DocInfo reference
        # graphs are independently closed.
        return EXIT_REFUSED
    except CoverageError as exc:
        try:
            _print(_base_refusal(exc.reason))
        except CoverageError:
            pass
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
