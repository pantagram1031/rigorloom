#!/usr/bin/env python3
"""Bounded, privacy-safe HWPX story edit (T80).

The T79 :mod:`story_graph` inventory is the public selector surface.  This
module accepts one closed JSON operation, resolves one schema-owned story /
paragraph address, requires that paragraph to contain exactly one supported
direct text-bearing run, and changes only that run's single ``hp:t`` text
seat.  It does not search source text, consume raw control/member identities,
or serialise an XML tree.  The latter is important: the output ZIP is rebuilt
by copying every unrelated local member record byte-for-byte and changing only
the selected member's payload.

This is a structural edit helper, not a renderer.  Exit codes are 0 for a
successful edit, 2 for usage/output errors, and 3 for a fail-closed refusal.
All public diagnostics are closed machine tokens; untrusted paths, text,
control IDs, and source XML never cross the CLI boundary.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import zlib
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

try:  # script entrypoint
    import story_graph
except ImportError:  # pragma: no cover - package/importlib callers
    from . import story_graph  # type: ignore


SCHEMA = "rigorloom/hwpx-story-edit/v1"
SELECTOR_SCHEMA = "rigorloom/hwpx-story-edit-selector/v1"
_ROLES = frozenset({"header", "footer", "footnote", "endnote"})
_ROLE_LOCAL_MAP = {"header": "header", "footer": "footer", "footNote": "footnote", "endNote": "endnote"}
_EXIT_USAGE = 2
_EXIT_REFUSED = 3
_MAX_OP_BYTES = 256 * 1024
_MAX_REPLACEMENT_CHARS = 2 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ORDINAL = r"(?:0|[1-9][0-9]*)"
_ANCESTRY = rf"{_ORDINAL}/{_ORDINAL}/{_ORDINAL}(?:/{_ORDINAL}/{_ORDINAL}/{_ORDINAL})*"
_ADDRESS_RE = re.compile(
    rf"^section\[(?P<section>{_ORDINAL})\]"
    rf"(?:/container\[(?P<container>{_ANCESTRY})\])?"
    rf"/story\[(?P<role>header|footer|footnote|endnote),(?P<story>{_ORDINAL})\]"
    rf"/paragraph\[(?P<paragraph>{_ORDINAL})\]$"
)
_TAG_NAME_RE = re.compile(rb"^<\s*(?:[A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)")
_END_NAME_RE = re.compile(rb"^</\s*(?:[A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)")
_XML_DECL_ENCODING_RE = re.compile(rb"\bencoding\s*=\s*(['\"])([^'\"]+)\1", re.I)


class EditError(ValueError):
    """A bounded, public refusal token (never carries user input)."""

    def __init__(self, code: str):
        self.code = code if re.fullmatch(r"[a-z0-9_]+", code) else "refused"
        super().__init__(self.code)


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys before closed-schema validation."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EditError("operation_keys")
        result[key] = value
    return result


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:  # pragma: no cover - argparse path
        self.exit(_EXIT_USAGE, "story-edit: invalid arguments (usage error)\n")


def _path_hash(*tokens: str) -> str:
    return hashlib.sha256((SCHEMA + ":" + ":".join(tokens)).encode("ascii")).hexdigest()


def _refusal(code: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": "refused", "reason": code}


def _parse_address(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or len(value) > 1024:
        raise EditError("selector_address")
    match = _ADDRESS_RE.fullmatch(value)
    if not match:
        raise EditError("selector_address")
    values = match.groupdict()
    container_text = values.get("container")
    container: tuple[int, ...] | None = None
    if container_text is not None:
        parts = tuple(int(part) for part in container_text.split("/"))
        if len(parts) % 3 or any(value < 0 for value in parts):
            raise EditError("selector_address")
        container = parts
    return {
        "raw": value,
        "section": int(values["section"]),
        "container": container,
        "story_role": values["role"],
        "story": int(values["story"]),
        "paragraph": int(values["paragraph"]),
        "story_address": (
            f"section[{int(values['section'])}]"
            + (f"/container[{container_text}]" if container_text is not None else "")
            + f"/story[{values['role']},{int(values['story'])}]"
        ),
    }


def _validate_operation(payload: object) -> tuple[dict[str, Any], str]:
    if not isinstance(payload, dict):
        raise EditError("operation_shape")
    if set(payload) != {"schema", "expected_input_sha256", "selector", "replacement"}:
        raise EditError("operation_keys")
    if payload.get("schema") != SCHEMA:
        raise EditError("operation_schema")
    expected_input = payload.get("expected_input_sha256")
    if not isinstance(expected_input, str) or not _HEX64.fullmatch(expected_input):
        raise EditError("input_hash_shape")
    replacement = payload.get("replacement")
    if not isinstance(replacement, str) or len(replacement) > _MAX_REPLACEMENT_CHARS:
        raise EditError("replacement_shape")
    # XML 1.0 normalizes carriage returns before consumers see the text.  A
    # raw CR would therefore make the requested logical replacement
    # non-deterministic, so T80 refuses it explicitly.
    if "\r" in replacement:
        raise EditError("replacement_cr")
    selector = payload.get("selector")
    if not isinstance(selector, dict):
        raise EditError("selector_shape")
    required = {"schema", "address"}
    if set(selector) != required:
        raise EditError("selector_keys")
    if selector.get("schema") != SELECTOR_SCHEMA:
        raise EditError("selector_schema")
    parsed = _parse_address(selector.get("address"))
    parsed["expected_input_sha256"] = expected_input
    return parsed, replacement


def _load_operation(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except (OSError, ValueError):
        raise EditError("operation_read")
    if len(raw) > _MAX_OP_BYTES:
        raise EditError("operation_size")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_closed_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EditError("operation_json")
    return _validate_operation(payload)


def _snapshot_graph(source: bytes) -> dict[str, Any]:
    """Inventory one immutable source snapshot, never the caller's path."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".story-source-", suffix=".hwpx", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(source)
        return story_graph.inspect_story_graph(temporary)
    except (OSError, ValueError, UnicodeError):
        raise EditError("input_refused")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _section_hrefs(source: bytes) -> list[str]:
    """Return section members in validated OPF spine order (never public)."""
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            infos = archive.infolist()
            names = story_graph._zip_members(archive)
            story_graph._validate_ocf(archive, names, infos)
            items, spine_ids = story_graph._validate_opf(archive, names)
            parsed_roles: dict[str, str] = {}
            for item in items:
                if item["media"] == "application/xml":
                    root = story_graph._parse_xml(story_graph._read(archive, names[item["href"]]))
                    parsed_roles[item["href"]] = story_graph._member_role(root)
                else:
                    parsed_roles[item["href"]] = "resource"
            item_by_id = {item["id"]: item for item in items}
            ordered = [item_by_id[item_id]["href"] for item_id in spine_ids]
            result = [href for href in ordered if parsed_roles.get(href) == "section"]
            if not result or any(parsed_roles.get(href) != "section" for href in result):
                raise EditError("section_order")
            return result
    except EditError:
        raise
    except (OSError, ValueError, KeyError, RecursionError, ET.ParseError,
            zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        raise EditError("input_package")


def _graph_target(graph: dict[str, Any], selector: dict[str, Any]) -> dict[str, Any]:
    if graph.get("status") != "passed":
        raise EditError("input_refused")
    found: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for member in graph.get("members", []):
        for story in member.get("stories", []):
            for paragraph in story.get("paragraphs", []):
                if story.get("address") == selector["story_address"] and paragraph.get("order") == selector["paragraph"]:
                    found.append((member, story, paragraph))
    if len(found) != 1:
        raise EditError("selector_ambiguous")
    member, story, paragraph = found[0]
    if story.get("role") not in _ROLES:
        raise EditError("unsupported_story")
    if paragraph.get("address") is None:
        raise EditError("selector_stale")
    return {"member": member, "story": story, "paragraph": paragraph}


def _find_tag_end(data: bytes, start: int) -> int:
    quote: int | None = None
    cursor = start + 1
    while cursor < len(data):
        byte = data[cursor]
        if quote:
            if byte == quote:
                quote = None
        elif byte in (ord("'"), ord('"')):
            quote = byte
        elif byte == ord(">"):
            return cursor + 1
        cursor += 1
    raise EditError("xml_token")


def _local_name(token: bytes, closing: bool = False) -> str:
    match = _END_NAME_RE.match(token) if closing else _TAG_NAME_RE.match(token)
    if not match:
        return ""
    try:
        return match.group(1).decode("ascii")
    except UnicodeDecodeError:
        return ""


def _validate_target_encoding(data: bytes) -> None:
    """Accept only UTF-8 target XML (with an optional UTF-8 BOM)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise EditError("input_encoding")
    probe = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    probe = probe.lstrip(b" \t\r\n")
    if not probe.startswith(b"<?xml"):
        return
    end = probe.find(b"?>", 5)
    if end < 0:
        raise EditError("input_encoding")
    declaration = probe[:end + 2]
    match = _XML_DECL_ENCODING_RE.search(declaration)
    if match is not None and match.group(2).lower() != b"utf-8":
        raise EditError("input_encoding")


def _decode_t_fragment(fragment: bytes) -> str:
    """Decode one hp:t inner fragment with XML entity semantics."""
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(b"<story-edit-text>" + fragment + b"</story-edit-text>", parser=parser)
    except (ET.ParseError, UnicodeError, RecursionError):
        raise EditError("input_text")
    if list(root):
        # The selector contract accepts a text-only hp:t seat.  Child XML
        # would make the logical text ambiguous and is never spliced.
        raise EditError("unsupported_target_run")
    return root.text or ""


def _scan_text_span(data: bytes, selector: dict[str, Any]) -> tuple[tuple[int, int], list[tuple[int, int]]]:
    """Find one target ``hp:t`` span and its own stale-lineseg cache."""
    target_container = selector["container"]
    target_story_key = (selector["story_role"], selector["story"], target_container)
    role_ordinals = {role: 0 for role in _ROLES}
    stack: list[dict[str, Any]] = []
    active_story: dict[str, Any] | None = None
    table_stack: list[dict[str, Any]] = []
    main_table_order = 0
    paragraph_frame: dict[str, Any] | None = None
    target_span: tuple[int, int] | None = None
    target_lineseg_spans: list[tuple[int, int]] = []
    target_paragraph_seen = False
    cursor = 0
    section_index = selector["section"]
    while cursor < len(data):
        opener = data.find(b"<", cursor)
        if opener < 0:
            break
        if data.startswith(b"<!--", opener):
            end = data.find(b"-->", opener + 4)
            if end < 0:
                raise EditError("xml_token")
            cursor = end + 3
            continue
        if data.startswith(b"<![CDATA[", opener):
            end = data.find(b"]]>", opener + 9)
            if end < 0:
                raise EditError("xml_token")
            cursor = end + 3
            continue
        if data.startswith(b"<?", opener):
            # A processing instruction may contain arbitrary ``>`` bytes in
            # quoted data.  `_find_tag_end` is not sufficient here: skip only
            # through the exact PI terminator so fake markup cannot become a
            # routable story.
            end = data.find(b"?>", opener + 2)
            if end < 0:
                raise EditError("xml_token")
            cursor = end + 2
            continue
        if data.startswith(b"<!", opener):
            # T80 has no DTD/entity lexer.  Comments and CDATA were handled
            # above; all other declarations, including DOCTYPE/internal
            # subsets and ENTITY declarations, are fail-closed.
            raise EditError("xml_token")
        end = _find_tag_end(data, opener)
        token = data[opener:end]
        closing = token.startswith(b"</")
        local = _local_name(token, closing=closing)
        if not local:
            raise EditError("xml_token")
        if closing:
            if not stack or stack[-1]["local"] != local:
                raise EditError("xml_token")
            frame = stack.pop()
            if local == "t" and frame.get("target"):
                span = (frame["content_start"], opener)
                frame["span"] = span
                frame["text_count"] = 1
                if frame.get("run_data") is not None:
                    run = frame["run_data"]
                    run["text_count"] += 1
                    run["text_span"] = span
            if local == "run" and frame.get("run_data") is not None:
                run = frame["run_data"]
                owner = frame.get("paragraph_owner")
                if owner is not None and owner.get("target_paragraph"):
                    # A run is text-bearing as soon as it contains one or
                    # more direct hp:t seats.  Count every such run before
                    # checking whether the sole candidate has the supported
                    # exactly-one-t shape; otherwise a multi-t run could be
                    # silently ignored while a second run was edited.
                    if run["text_count"] >= 1:
                        owner["text_run_count"] += 1
                        owner.setdefault("text_runs", []).append({
                            "text_count": run["text_count"],
                            "children": tuple(run["children"]),
                            "span": run["text_span"],
                        })
            if local == "linesegarray" and frame.get("target_lineseg"):
                owner = frame.get("paragraph_owner")
                if owner is not None:
                    owner.setdefault("lineseg_spans", []).append((frame["start"], end))
            if local == "p":
                if frame.get("target_paragraph"):
                    text_runs = frame.get("text_runs", [])
                    if frame.get("text_run_count") != 1 or len(text_runs) != 1:
                        raise EditError("unsupported_target_run")
                    sole_run = text_runs[0]
                    if (sole_run["text_count"] != 1
                            or sole_run["children"] != ("t",)
                            or sole_run["span"] is None):
                        raise EditError("unsupported_target_run")
                    target_span = sole_run["span"]
                    target_lineseg_spans.extend(frame.get("lineseg_spans", []))
                paragraph_frame = frame.get("previous_paragraph")
            if local in _ROLE_LOCAL_MAP:
                active_story = frame.get("previous_story")
            if local == "tbl":
                if table_stack:
                    table_stack.pop()
            cursor = end
            continue

        self_closing = token.rstrip().endswith(b"/>")
        parent = stack[-1] if stack else None
        frame: dict[str, Any] = {"local": local, "start": opener, "content_start": end}
        if local == "tbl":
            frame["table_order"] = main_table_order if active_story is None else -1
            if active_story is None:
                main_table_order += 1
            table_stack.append({"order": frame["table_order"], "cell_count": 0})
        elif local == "tc":
            if not table_stack:
                raise EditError("unsupported_target_run")
            table_stack[-1]["cell_count"] += 1
            table_stack[-1]["cell_ordinal"] = table_stack[-1]["cell_count"] - 1
        elif local in _ROLE_LOCAL_MAP:
            if active_story is not None:
                raise EditError("unsupported_nested_story")
            role = _ROLE_LOCAL_MAP[local]
            ordinal = role_ordinals[role]
            role_ordinals[role] += 1
            ancestry: tuple[int, ...] | None = None
            if table_stack:
                if any(item["order"] < 0 for item in table_stack):
                    raise EditError("unsupported_nested_story")
                # A table story is owned by the current cell at every depth.
                ancestry_parts: list[int] = []
                for depth, table in enumerate(table_stack, start=1):
                    if "cell_ordinal" not in table:
                        raise EditError("unsupported_nested_story")
                    ancestry_parts.extend((depth, table["order"], table["cell_ordinal"]))
                ancestry = tuple(ancestry_parts)
            key = (role, ordinal, ancestry)
            frame["previous_story"] = active_story
            frame["story_key"] = key
            frame["target_story"] = (
                section_index == selector["section"] and key == target_story_key
            )
            frame["paragraph_count"] = 0
            active_story = frame
        elif local == "p":
            target_story = bool(active_story and active_story.get("target_story"))
            para_index = active_story["paragraph_count"] if active_story else -1
            if active_story:
                active_story["paragraph_count"] += 1
            frame["para_index"] = para_index
            frame["target_paragraph"] = target_story and para_index == selector["paragraph"]
            if frame["target_paragraph"]:
                target_paragraph_seen = True
            frame["text_run_count"] = 0
            frame["lineseg_spans"] = []
            frame["previous_paragraph"] = paragraph_frame
            paragraph_frame = frame
        elif local == "run":
            frame["paragraph_owner"] = paragraph_frame
            # Only a run directly owned by the target paragraph is an edit
            # seat.  Nested runs occur in control/sub-list furniture and are
            # never selector-addressable in T80.
            direct_target_run = bool(
                paragraph_frame and paragraph_frame.get("target_paragraph") and parent is paragraph_frame
            )
            frame["run_data"] = {"text_count": 0, "text_span": None, "children": []} if direct_target_run else None
        elif local == "t":
            frame["target"] = bool(parent and parent.get("run_data") is not None)
            if frame["target"]:
                frame["run_data"] = parent["run_data"]
                parent["run_data"]["children"].append("t")
        elif local == "linesegarray":
            frame["target_lineseg"] = bool(parent and parent.get("target_paragraph"))
            frame["paragraph_owner"] = parent
        elif parent and parent.get("run_data") is not None:
            parent["run_data"]["children"].append(local)

        if not self_closing:
            stack.append(frame)
        elif local == "linesegarray" and frame.get("target_lineseg"):
            owner = frame.get("paragraph_owner")
            if owner is not None:
                owner.setdefault("lineseg_spans", []).append((opener, end))
        elif local == "t" and frame.get("target"):
            raise EditError("unsupported_target_run")
        cursor = end
    if stack:
        raise EditError("xml_token")
    if target_span is None:
        if target_paragraph_seen:
            raise EditError("unsupported_target_run")
        raise EditError("address_mismatch")
    return target_span, target_lineseg_spans


def _compress(info: zipfile.ZipInfo, payload: bytes) -> bytes:
    if info.compress_type == zipfile.ZIP_STORED:
        return payload
    if info.compress_type != zipfile.ZIP_DEFLATED:
        raise EditError("zip_compression")
    # PKWARE APPNOTE bit 2 (0x0004) is the DEFLATE "fast" hint, not a
    # maximum-compression request.  Preserve the envelope's semantics while
    # keeping ordinary flag-0 members at the normal level-6 default.
    level = 1 if info.flag_bits & 0x0004 else 6
    compressor = zlib.compressobj(level=level, method=zlib.DEFLATED, wbits=-15)
    return compressor.compress(payload) + compressor.flush()


def _local_bounds(data: bytes, info: zipfile.ZipInfo) -> tuple[int, int, int]:
    start = info.header_offset
    if start < 0 or start + 30 > len(data):
        raise EditError("zip_header")
    fixed = data[start:start + 30]
    values = struct.unpack("<IHHHHHIIIHH", fixed)
    if values[0] != 0x04034B50:
        raise EditError("zip_header")
    name_len, extra_len = values[-2], values[-1]
    content_start = start + 30 + name_len + extra_len
    content_end = content_start + info.compress_size
    if content_end > len(data):
        raise EditError("zip_header")
    return start, content_start, content_end


def _rewrite_zip(source: bytes, output: Path, target_name: str, target_payload: bytes) -> None:
    """Patch one local member while copying all unrelated ZIP bytes exactly."""
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            infos = archive.infolist()
            target_index = next(index for index, info in enumerate(infos) if info.filename == target_name)
            target_info = infos[target_index]
            compressed_target = _compress(target_info, target_payload)
            target_start, target_content_start, target_content_end = _local_bounds(source, target_info)
            eocd = source.rfind(b"PK\x05\x06")
            if eocd < 0 or eocd + 22 > len(source):
                raise EditError("zip_directory")
            _, disk, disk_cd, count_disk, count_total, cd_size, cd_offset, comment_len = struct.unpack_from(
                "<4s4H2LH", source, eocd
            )
            if disk or disk_cd or count_disk != count_total or cd_offset + cd_size > eocd:
                raise EditError("zip_directory")
            if cd_offset + cd_size != eocd:
                raise EditError("zip_directory")

            delta = len(compressed_target) - target_info.compress_size
            result = bytearray()
            cursor = 0
            for index, info in enumerate(infos):
                start, content_start, content_end = _local_bounds(source, info)
                if start < cursor or content_end > cd_offset:
                    raise EditError("zip_layout")
                result.extend(source[cursor:start])
                if index != target_index:
                    result.extend(source[start:content_end])
                else:
                    local = bytearray(source[start:content_start])
                    struct.pack_into("<III", local, 14, zlib.crc32(target_payload) & 0xFFFFFFFF,
                                     len(compressed_target), len(target_payload))
                    result.extend(local)
                    result.extend(compressed_target)
                cursor = content_end
            result.extend(source[cursor:cd_offset])
            new_cd_offset = len(result)

            central_cursor = cd_offset
            for index, info in enumerate(infos):
                if central_cursor + 46 > eocd or source[central_cursor:central_cursor + 4] != b"PK\x01\x02":
                    raise EditError("zip_directory")
                fields = struct.unpack_from("<4s6H3L5H2L", source, central_cursor)
                name_len, extra_len, comment_len_record = fields[10], fields[11], fields[12]
                record_end = central_cursor + 46 + name_len + extra_len + comment_len_record
                if record_end > eocd:
                    raise EditError("zip_directory")
                central = bytearray(source[central_cursor:record_end])
                new_offset = info.header_offset + (delta if info.header_offset > target_start else 0)
                struct.pack_into("<L", central, 42, new_offset)
                if index == target_index:
                    struct.pack_into("<LLL", central, 16, zlib.crc32(target_payload) & 0xFFFFFFFF,
                                     len(compressed_target), len(target_payload))
                result.extend(central)
                central_cursor = record_end
            if central_cursor != eocd:
                raise EditError("zip_directory")
            result.extend(source[eocd:])
            # EOCD is now at the end of the newly copied central directory;
            # adjust its central-directory offset in the copied tail.
            new_eocd = len(result) - (len(source) - eocd)
            struct.pack_into("<L", result, new_eocd + 16, new_cd_offset)
    except EditError:
        raise
    except (OSError, StopIteration, ValueError, zipfile.BadZipFile, struct.error):
        raise EditError("zip_write")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".story-edit-", suffix=".hwpx", dir=output.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:
                raise EditError("zip_write")
        temporary.replace(output)
    except EditError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    except (OSError, zipfile.BadZipFile):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise EditError("output_write")


_ZIPINFO_STABLE_FIELDS = (
    "filename", "orig_filename", "date_time", "compress_type", "compresslevel",
    "comment", "extra", "create_system", "create_version", "extract_version",
    "flag_bits", "volume", "internal_attr", "external_attr", "CRC", "file_size",
    "compress_size", "reserved", "_compresslevel",
)
_ZIPINFO_CONTENT_FIELDS = frozenset({"CRC", "file_size", "compress_size"})


def _zipinfo_values(info: zipfile.ZipInfo, *, target: bool) -> tuple[object, ...]:
    """Return metadata that must survive the binary member splice.

    ``header_offset`` is deliberately absent: changing the target compressed
    size shifts subsequent local headers and central records.  For the target
    member only CRC and sizes are content-derived and may change; all other
    ZipInfo metadata remains an invariant.
    """
    fields = (
        field for field in _ZIPINFO_STABLE_FIELDS
        if not (target and field in _ZIPINFO_CONTENT_FIELDS)
    )
    return tuple(getattr(info, field, None) for field in fields)


def _central_records(data: bytes, archive: zipfile.ZipFile) -> list[bytes]:
    """Extract central records in archive order without normalising bytes."""
    cursor = int(getattr(archive, "start_dir"))
    records: list[bytes] = []
    for _info in archive.infolist():
        if cursor < 0 or cursor + 46 > len(data) or data[cursor:cursor + 4] != b"PK\x01\x02":
            raise EditError("preservation_failed")
        fields = struct.unpack_from("<4s6H3L5H2L", data, cursor)
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        end = cursor + 46 + name_len + extra_len + comment_len
        if end > len(data):
            raise EditError("preservation_failed")
        records.append(data[cursor:end])
        cursor = end
    if cursor != int(getattr(archive, "start_dir")) + sum(len(record) for record in records):
        raise EditError("preservation_failed")
    return records


def _mask_central_record(record: bytes, *, target: bool) -> bytes:
    if len(record) < 46:
        raise EditError("preservation_failed")
    masked = bytearray(record)
    # The local-header offset shifts when a preceding target payload changes.
    masked[42:46] = b"\0\0\0\0"
    if target:
        # CRC, compressed size, and uncompressed size are content-derived.
        masked[16:28] = b"\0" * 12
    return bytes(masked)


def _local_record_and_payload(data: bytes, info: zipfile.ZipInfo) -> tuple[bytes, bytes, bytes]:
    start, content_start, content_end = _local_bounds(data, info)
    return data[start:content_end], data[start:content_start], data[content_start:content_end]


def _eocd_record(data: bytes, archive: zipfile.ZipFile, central: list[bytes]) -> tuple[int, bytes]:
    start = int(getattr(archive, "start_dir")) + sum(len(record) for record in central)
    if start < 0 or start + 22 > len(data) or data[start:start + 4] != b"PK\x05\x06":
        raise EditError("preservation_failed")
    comment_len = struct.unpack_from("<H", data, start + 20)[0]
    end = start + 22 + comment_len
    if end > len(data):
        raise EditError("preservation_failed")
    return start, data[start:end]


def _mask_eocd_offset(record: bytes) -> bytes:
    if len(record) < 22:
        raise EditError("preservation_failed")
    masked = bytearray(record)
    masked[16:20] = b"\0" * 4
    return bytes(masked)


def _verify_preservation(source: bytes, staged: Path, target_name: str,
                         expected_target_payload: bytes) -> None:
    """Fail closed unless the staged package is the exact expected splice.

    T79 graph equality is intentionally *not* used as a preservation proof:
    its public hashes identify structural routes only.  This verifier compares
    the captured source snapshot and staged ZIP directly, including archive
    comment, member order, decompressed bytes, and stable metadata.
    """
    try:
        staged_bytes = staged.read_bytes()
        with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(io.BytesIO(staged_bytes)) as edited:
            if original.comment != edited.comment:
                raise EditError("preservation_failed")
            original_infos = original.infolist()
            edited_infos = edited.infolist()
            if [info.filename for info in original_infos] != [info.filename for info in edited_infos]:
                raise EditError("preservation_failed")
            if target_name not in [info.filename for info in original_infos]:
                raise EditError("preservation_failed")
            original_central = _central_records(source, original)
            edited_central = _central_records(staged_bytes, edited)
            if len(original_central) != len(edited_central):
                raise EditError("preservation_failed")
            target_index = next(index for index, info in enumerate(original_infos)
                                if info.filename == target_name)
            original_target_payload = original.read(original_infos[target_index])
            original_bounds = [_local_bounds(source, info) for info in original_infos]
            edited_bounds = [_local_bounds(staged_bytes, info) for info in edited_infos]
            original_target_compressed = original_bounds[target_index][2] - original_bounds[target_index][1]
            expected_compressed = (
                source[original_bounds[target_index][1]:original_bounds[target_index][2]]
                if expected_target_payload == original_target_payload
                else _compress(original_infos[target_index], expected_target_payload)
            )
            expected_delta = len(expected_compressed) - original_target_compressed
            if int(getattr(edited, "start_dir")) != int(getattr(original, "start_dir")) + expected_delta:
                raise EditError("preservation_failed")
            if sum(len(record) for record in original_central) != sum(len(record) for record in edited_central):
                raise EditError("preservation_failed")
            for index, (original_info, edited_info) in enumerate(zip(original_infos, edited_infos)):
                expected_offset = original_info.header_offset + (
                    expected_delta if index > target_index else 0
                )
                if edited_info.header_offset != expected_offset:
                    raise EditError("preservation_failed")
            # Every inter-record gap (including the bytes before the first
            # local record and between the last local record and the central
            # directory) is part of the physical envelope and must survive.
            for index in range(len(original_infos) + 1):
                original_gap_start = 0 if index == 0 else original_bounds[index - 1][2]
                original_gap_end = (
                    original_bounds[index][0] if index < len(original_infos) else int(getattr(original, "start_dir"))
                )
                edited_gap_start = 0 if index == 0 else edited_bounds[index - 1][2]
                edited_gap_end = (
                    edited_bounds[index][0] if index < len(edited_infos) else int(getattr(edited, "start_dir"))
                )
                if source[original_gap_start:original_gap_end] != staged_bytes[edited_gap_start:edited_gap_end]:
                    raise EditError("preservation_failed")
            original_eocd_start, original_eocd = _eocd_record(source, original, original_central)
            edited_eocd_start, edited_eocd = _eocd_record(staged_bytes, edited, edited_central)
            if _mask_eocd_offset(original_eocd) != _mask_eocd_offset(edited_eocd):
                raise EditError("preservation_failed")
            if struct.unpack_from("<L", edited_eocd, 16)[0] != int(getattr(edited, "start_dir")):
                raise EditError("preservation_failed")
            if struct.unpack_from("<L", edited_eocd, 12)[0] != struct.unpack_from("<L", original_eocd, 12)[0]:
                raise EditError("preservation_failed")
            if source[original_eocd_start + len(original_eocd):] != staged_bytes[edited_eocd_start + len(edited_eocd):]:
                raise EditError("preservation_failed")
            for index, (original_info, edited_info) in enumerate(zip(original_infos, edited_infos)):
                is_target = original_info.filename == target_name
                if original_info.filename != edited_info.filename:
                    raise EditError("preservation_failed")
                if _zipinfo_values(original_info, target=is_target) != _zipinfo_values(
                    edited_info, target=is_target
                ):
                    raise EditError("preservation_failed")
                original_local, original_header, original_compressed = _local_record_and_payload(
                    source, original_info
                )
                edited_local, edited_header, edited_compressed = _local_record_and_payload(
                    staged_bytes, edited_info
                )
                if is_target:
                    if edited.read(edited_info) != expected_target_payload:
                        raise EditError("preservation_failed")
                    if edited_compressed != expected_compressed:
                        raise EditError("preservation_failed")
                    # Local-record bytes must remain identical except the
                    # content-derived CRC/sizes and the compressed stream.
                    if len(original_header) != len(edited_header):
                        raise EditError("preservation_failed")
                    mutable_header = ((14, 26),)
                    for begin, end in mutable_header:
                        original_header = original_header[:begin] + b"\0" * (end - begin) + original_header[end:]
                        edited_header = edited_header[:begin] + b"\0" * (end - begin) + edited_header[end:]
                    if original_header != edited_header:
                        raise EditError("preservation_failed")
                    if _mask_central_record(original_central[index], target=True) != _mask_central_record(
                        edited_central[index], target=True
                    ):
                        raise EditError("preservation_failed")
                    expected_crc = zlib.crc32(expected_target_payload) & 0xFFFFFFFF
                    if (edited_info.CRC != expected_crc
                            or edited_info.file_size != len(expected_target_payload)
                            or edited_info.compress_size != len(expected_compressed)):
                        raise EditError("preservation_failed")
                else:
                    if original.read(original_info) != edited.read(edited_info):
                        raise EditError("preservation_failed")
                    if original_local != edited_local:
                        raise EditError("preservation_failed")
                    if _mask_central_record(original_central[index], target=False) != _mask_central_record(
                        edited_central[index], target=False
                    ):
                        raise EditError("preservation_failed")
    except EditError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise EditError("preservation_failed")


def _topology_only(value: object) -> object:
    """Drop schema-only routing hashes before comparing T79 inventories."""
    if isinstance(value, dict):
        return {key: _topology_only(item) for key, item in value.items() if key != "hash"}
    if isinstance(value, list):
        return [_topology_only(item) for item in value]
    return value


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".story-receipt-", suffix=".json", dir=path.parent,
                                         mode="w", encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
        temporary.replace(path)
    except (OSError, UnicodeError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise EditError("receipt_write")


def _file_identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def _publish_exclusive(staged: Path, final: Path) -> tuple[int, int]:
    """Atomically publish a staged file only when the final path is absent.

    The hard-link succeeds before cleanup of the staging name.  A failure to
    unlink that staging name is harmless and must not turn a successful
    publication into a false failure.
    """
    # Capture the inode before linking.  Once ``os.link`` succeeds there must
    # be no further fallible operation in this helper: the caller receives the
    # identity immediately and TemporaryDirectory performs best-effort stage
    # cleanup later.
    try:
        identity = _file_identity(staged)
    except OSError:
        raise EditError("output_publish")
    try:
        os.link(staged, final)
    except (FileExistsError, OSError) as exc:
        raise EditError("output_exists" if isinstance(exc, FileExistsError) else "output_publish")
    # Do not unlink ``staged`` here.  A cleanup failure cannot invalidate a
    # successful hard-link publication and is handled by the temp-dir owner.
    return identity


def _unlink_if_identity(path: Path, identity: tuple[int, int] | None) -> None:
    """Rollback only our own publication, never an attacker-swapped path."""
    if identity is None:
        return
    try:
        if _file_identity(path) == identity:
            path.unlink()
    except OSError:
        pass


def apply_story_edit(document: str | Path, operation: dict[str, Any], output: str | Path,
                     receipt: str | Path) -> dict[str, Any]:
    """Apply one validated operation and return its privacy-safe receipt."""
    input_path = Path(document)
    output_path = Path(output)
    receipt_path = Path(receipt)
    if input_path.suffix.lower() != ".hwpx" or output_path.suffix.lower() != ".hwpx":
        raise EditError("unsupported_input")
    try:
        resolved_input = input_path.resolve()
        resolved_output = output_path.resolve()
        resolved_receipt = receipt_path.resolve()
        if resolved_input == resolved_output or resolved_input == resolved_receipt:
            raise EditError("in_place_output")
        if resolved_output == resolved_receipt:
            raise EditError("output_conflict")
        if output_path.exists() or receipt_path.exists():
            raise EditError("output_exists")
    except OSError:
        raise EditError("output_path")
    selector, replacement = _validate_operation(operation)
    try:
        input_bytes = input_path.read_bytes()
    except (OSError, ValueError):
        raise EditError("input_read")
    if hashlib.sha256(input_bytes).hexdigest() != selector["expected_input_sha256"]:
        raise EditError("selector_stale")
    section_hrefs = _section_hrefs(input_bytes)
    if selector["section"] >= len(section_hrefs):
        raise EditError("address_mismatch")
    target_name = section_hrefs[selector["section"]]
    try:
        with zipfile.ZipFile(io.BytesIO(input_bytes)) as archive:
            target_info = archive.getinfo(target_name)
            source_payload = archive.read(target_info)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile):
        raise EditError("input_package")
    _validate_target_encoding(source_payload)
    graph = _snapshot_graph(input_bytes)
    target = _graph_target(graph, selector)
    (start, end), lineseg_spans = _scan_text_span(source_payload, selector)
    if start < 0 or end < start or end > len(source_payload):
        raise EditError("address_mismatch")
    try:
        escaped = escape(replacement).encode("utf-8")
        source_text = _decode_t_fragment(source_payload[start:end])
        changed = source_text != replacement
        if not changed:
            modified_payload = source_payload
        else:
            edits = [(start, end, escaped)] + [(line_start, line_end, b"")
                                               for line_start, line_end in lineseg_spans]
            modified_payload = source_payload
            for edit_start, edit_end, edit_value in sorted(edits, key=lambda item: item[0], reverse=True):
                modified_payload = modified_payload[:edit_start] + edit_value + modified_payload[edit_end:]
        ET.fromstring(modified_payload)
    except (UnicodeError, ET.ParseError, RecursionError):
        raise EditError("replacement_xml")
    receipt_payload = {
        "schema": SCHEMA,
        "status": "passed",
        "address": selector["raw"],
        "changed": changed,
        "inventory": "passed",
        "preservation": "passed",
        "render": "not_run",
    }
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise EditError("output_path")
    output_identity: tuple[int, int] | None = None
    receipt_identity: tuple[int, int] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=".story-edit-out-", dir=output_path.parent) as out_dir:
            with tempfile.TemporaryDirectory(prefix=".story-edit-rec-", dir=receipt_path.parent) as rec_dir:
                staged_output = Path(out_dir) / "artifact.hwpx"
                staged_receipt = Path(rec_dir) / "receipt.json"
                if changed:
                    _rewrite_zip(input_bytes, staged_output, target_name, modified_payload)
                else:
                    staged_output.write_bytes(input_bytes)
                updated = story_graph.inspect_story_graph(staged_output)
                if updated.get("status") != "passed":
                    raise EditError("output_refused")
                # Re-run T79 as a topology-only check.  Its schema-only hashes
                # identify routes, but are never treated as byte preservation
                # or freshness evidence.
                if _topology_only(updated) != _topology_only(graph):
                    raise EditError("topology_changed")
                _verify_preservation(input_bytes, staged_output, target_name, modified_payload)
                # Re-resolve the exact structural address from the staged
                # bytes and verify the logical replacement text, not merely
                # XML well-formedness or topology.
                with zipfile.ZipFile(staged_output) as staged_archive:
                    staged_payload = staged_archive.read(target_name)
                _validate_target_encoding(staged_payload)
                (staged_start, staged_end), _ = _scan_text_span(staged_payload, selector)
                try:
                    staged_text = _decode_t_fragment(staged_payload[staged_start:staged_end])
                except EditError as exc:
                    if exc.code == "input_text":
                        raise EditError("output_refused")
                    raise
                if staged_text != replacement:
                    raise EditError("output_refused")
                _write_receipt(staged_receipt, receipt_payload)
                # Capture both intended inode identities before attempting
                # publication.  If a publisher raises after linking but before
                # returning, rollback can still distinguish our file from a
                # concurrently swapped final path.
                output_identity = _file_identity(staged_output)
                _publish_exclusive(staged_output, output_path)
                receipt_identity = _file_identity(staged_receipt)
                _publish_exclusive(staged_receipt, receipt_path)
    except EditError:
        _unlink_if_identity(output_path, output_identity)
        _unlink_if_identity(receipt_path, receipt_identity)
        raise
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile):
        _unlink_if_identity(output_path, output_identity)
        _unlink_if_identity(receipt_path, receipt_identity)
        raise EditError("output_write")
    return receipt_payload


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(prog="story-edit", description="privacy-safe HWPX story-scoped edit")
    parser.add_argument("document")
    parser.add_argument("--ops-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        selector, replacement = _load_operation(Path(args.ops_file))
        operation = {
            "schema": SCHEMA,
            "expected_input_sha256": selector["expected_input_sha256"],
            "selector": {
                "schema": SELECTOR_SCHEMA,
                "address": selector["raw"],
            },
            "replacement": replacement,
        }
        payload = apply_story_edit(args.document, operation, args.out, args.receipt)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0
    except EditError as exc:
        sys.stdout.write(json.dumps(_refusal(exc.code), sort_keys=True) + "\n")
        return _EXIT_REFUSED
    except (OSError, UnicodeError, ValueError, RecursionError):
        sys.stdout.write(json.dumps(_refusal("refused"), sort_keys=True) + "\n")
        return _EXIT_REFUSED


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
