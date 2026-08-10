#!/usr/bin/env python3
"""Bounded, privacy-safe HWPX story inventory (T79).

This is deliberately an inventory, not an editor or renderer.  It accepts a
small documented OWPML envelope and refuses everything it cannot model.  The
public result is structural only: document-controlled names, IDs, text, URLs,
and metadata never cross the boundary.  Addresses use only schema-owned
role/ordinal paths; member identity uses deterministic ordinals, and hashes are
limited to schema-owned closed tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET


SCHEMA = "rigorloom/hwpx-story-graph/v1"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
CORE_NS = "http://www.hancom.co.kr/hwpml/2011/core"
HEAD_NS = "http://www.hancom.co.kr/hwpml/2011/head"
APP_NS = "http://www.hancom.co.kr/hwpml/2011/app"
PARAGRAPH10_NS = "http://www.hancom.co.kr/hwpml/2016/paragraph"
MASTER_PAGE_NS = "http://www.hancom.co.kr/hwpml/2011/master-page"
OPF_NS = "http://www.idpf.org/2007/opf/"
OCF_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
HWPX_MIMETYPE = b"application/hwp+zip"
HPF_MIMETYPE = "application/hwpml-package+xml"

# Availability limits are intentionally conservative.  This inventory is a
# preflight, never a general-purpose ZIP/XML extractor.
MAX_MEMBERS = 1024
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_XML_DEPTH = 256
MAX_XML_NODES = 100_000

_Q_SECTION = (SECTION_NS, "sec")
_Q_MANIFEST = (OPF_NS, "manifest")
_Q_SPINE = (OPF_NS, "spine")
_Q_ITEM = (OPF_NS, "item")
_Q_ITEMREF = (OPF_NS, "itemref")
_CONTROL_ROLES = {
    "header": "header", "footer": "footer", "footNote": "footnote", "endNote": "endnote",
}
_UNSUPPORTED = {
    "fieldBegin": "unsupported_field", "fieldEnd": "unsupported_field",
    "hiddenComment": "unsupported_hidden_comment", "drawText": "unsupported_draw_text",
    "caption": "unsupported_caption", "masterPage": "unsupported_master_page",
}
# All 12 shipped public forms use only these floating object seats: `pic`,
# `rect`, and `tbl`.  Other object owners stay unsupported until a public
# corpus plus grammar regression demonstrates their exact position contract.
_OBJECTS = frozenset({"pic", "rect"})
# The non-story names are accepted only so ordinary current HWPX forms remain
# inventoryable.  Their detailed semantics are intentionally out of scope.
_KNOWN_PARAGRAPH = frozenset({
    "p", "run", "t", "ctrl", "subList", "header", "footer", "footNote", "endNote",
    "hiddenComment", "fieldBegin", "fieldEnd", "drawText", "caption", "masterPage",
    "tbl", "tr", "tc", "cellAddr", "cellSpan", "cellSz", "cellMargin", "cellzone",
    "cellzoneList", "secPr", "pagePr", "margin", "pos", "pageBorderFill", "offset",
    "visibility", "grid", "lineNumberShape", "colPr", "startNum", "footNotePr",
    "endNotePr", "noteLine", "noteSpacing", "numbering", "placement", "autoNumFormat",
    "lineseg", "linesegarray", "lineBreak", "fwSpace", "tab", "parameters",
    "integerParam", "stringParam", "newNum", "markpenBegin", "markpenEnd", "lineShape",
    "shapeComment", "textMargin", "orgSz", "curSz", "imgRect", "imgClip", "imgDim",
    "effects", "flip", "rotationInfo", "renderingInfo", "shadow", "inMargin", "outMargin",
    "sz", *_OBJECTS,
})
_KNOWN_CORE = frozenset({
    "img", "transMatrix", "scaMatrix", "rotMatrix", "pt0", "pt1", "pt2", "pt3",
    "fillBrush", "winBrush",
})
_HEADER_LOCALS = frozenset({
    "head", "refList", "beginNum", "compatibleDocument", "docOption", "trackchageConfig",
    "fontfaces", "charProperties", "paraProperties", "borderFills", "numberings", "styles",
    "memoProperties", "tabProperties", "fontface", "charPr", "paraPr", "borderFill",
    "numbering", "style", "memoPr", "tabPr", "font", "typeInfo", "substFont", "bold",
    "italic", "underline", "strikeout", "outline", "shadow", "offset", "ratio", "relSz", "supscript",
    "spacing", "fontRef", "align", "autoSpacing", "border", "breakSetting", "heading",
    "backSlash", "bottomBorder", "diagonal", "leftBorder", "rightBorder", "slash",
    "topBorder", "paraHead", "layoutCompatibility", "linkinfo", "lineSpacing", "tabItem", "margin", "intent", "left",
    "next", "prev", "right",
})
_HEADER_CORE = frozenset({"fillBrush", "winBrush", "intent", "left", "next", "prev", "right"})
_HEADER_PARAGRAPH = frozenset({"switch", "case", "default"})
_HEADER_PARENT_LOCAL = {
    "head": {None},
    "refList": {"head"}, "beginNum": {"head"}, "compatibleDocument": {"head"},
    "docOption": {"head"}, "trackchageConfig": {"head"},
    "fontfaces": {"refList"}, "charProperties": {"refList"}, "paraProperties": {"refList"},
    "borderFills": {"refList"}, "numberings": {"refList"}, "styles": {"refList"},
    "memoProperties": {"refList"}, "tabProperties": {"refList"}, "fontface": {"fontfaces"},
    "charPr": {"charProperties"}, "paraPr": {"paraProperties"}, "borderFill": {"borderFills"},
    "numbering": {"numberings"}, "style": {"styles"}, "memoPr": {"memoProperties"},
    "tabPr": {"tabProperties"}, "font": {"fontface"}, "typeInfo": {"font"}, "substFont": {"font"},
    "bold": {"charPr"}, "italic": {"charPr"}, "underline": {"charPr"}, "strikeout": {"charPr"},
    "outline": {"charPr"}, "shadow": {"charPr"}, "offset": {"charPr"}, "ratio": {"charPr"},
    "relSz": {"charPr"}, "spacing": {"charPr"}, "supscript": {"charPr"}, "fontRef": {"charPr"},
    "align": {"paraPr"}, "autoSpacing": {"paraPr"}, "border": {"paraPr"},
    "breakSetting": {"paraPr"}, "paraHead": {"numbering"},
    "layoutCompatibility": {"compatibleDocument"}, "linkinfo": {"docOption"},
    "backSlash": {"borderFill"}, "bottomBorder": {"borderFill"}, "diagonal": {"borderFill"},
    "leftBorder": {"borderFill"}, "rightBorder": {"borderFill"}, "slash": {"borderFill"},
    "topBorder": {"borderFill"}, "heading": {"paraPr", "case", "default"},
    "lineSpacing": {"case", "default"}, "margin": {"case", "default"},
    "tabItem": {"case", "default"},
}
_SECTION_CORE_PARENTS = {
    "img": {(PARAGRAPH_NS, "pic")},
    "pt0": {(PARAGRAPH_NS, "imgRect"), (PARAGRAPH_NS, "rect")},
    "pt1": {(PARAGRAPH_NS, "imgRect"), (PARAGRAPH_NS, "rect")},
    "pt2": {(PARAGRAPH_NS, "imgRect"), (PARAGRAPH_NS, "rect")},
    "pt3": {(PARAGRAPH_NS, "imgRect"), (PARAGRAPH_NS, "rect")},
    "transMatrix": {(PARAGRAPH_NS, "renderingInfo")},
    "scaMatrix": {(PARAGRAPH_NS, "renderingInfo")},
    "rotMatrix": {(PARAGRAPH_NS, "renderingInfo")},
    "fillBrush": {(PARAGRAPH_NS, "rect")},
    "winBrush": {(CORE_NS, "fillBrush")},
}


class GraphError(ValueError):
    """The archive is outside the bounded, safe inventory envelope."""


class _SafeParser(argparse.ArgumentParser):
    """Argparse must not echo an untrusted pathname or argument value."""

    def error(self, _message: str) -> None:  # pragma: no cover - argparse control path
        self.exit(2, "story-graph: invalid arguments (usage error)\n")


def _qname(node: ET.Element) -> tuple[str, str]:
    tag = node.tag
    if not isinstance(tag, str) or not tag.startswith("{") or "}" not in tag:
        return "", ""
    namespace, local = tag[1:].split("}", 1)
    return namespace, local


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _member_id(order: int) -> str:
    return f"member-{order + 1:04d}"


def _path_hash(*tokens: str) -> str:
    """Hash only schema-owned closed tokens, never source names or bytes."""
    return _sha((SCHEMA + ":" + ":".join(tokens)).encode("ascii"))


def _safe_member(name: str) -> str:
    """Validate a ZIP/OPF member name without normalising aliases."""
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise GraphError("unsafe_member")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise GraphError("unsafe_member")
    if len(name) > 512 or (len(name) >= 2 and name[1] == ":"):
        raise GraphError("unsafe_member")
    return name


def _unknown(_member: str, order: int, address: str, role: str, _digest: str) -> dict[str, Any]:
    return {
        "member_id": _member_id(order), "order": order, "address": address,
        "role": role, "hash": _path_hash("unknown", str(order), address, role),
    }


def _check_xml_bounds(root: ET.Element) -> None:
    count = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_XML_NODES:
            raise GraphError("xml_nodes")
        if depth > MAX_XML_DEPTH:
            raise GraphError("xml_depth")
        stack.extend((child, depth + 1) for child in node)


def _parse_xml(data: bytes) -> ET.Element:
    if len(data) > MAX_XML_BYTES:
        raise GraphError("xml_bytes")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, RecursionError, UnicodeError) as exc:
        raise GraphError("xml_parse") from exc
    _check_xml_bounds(root)
    return root


def _iter_children(node: ET.Element) -> Iterator[tuple[int, ET.Element]]:
    # Explicitly iterative at callers; ElementTree children are already a list.
    yield from enumerate(node)


def _children_named(node: ET.Element, namespace: str, local: str) -> list[ET.Element]:
    return [child for child in node if _qname(child) == (namespace, local)]


def _exact_bool(value: str | None) -> bool:
    return value in {"0", "1", "true", "false"}


def _empty_counts() -> Counter[str]:
    return Counter({
        "members": 0, "sections": 0, "main_paragraphs": 0, "stories": 0,
        "story_paragraphs": 0, "headers": 0, "footers": 0, "footnotes": 0,
        "endnotes": 0, "tables": 0, "nested_table_max_depth": 0,
    })


def _refused(counts: Counter[str], role: str = "unreadable_package") -> dict[str, Any]:
    return {
        "schema": SCHEMA, "status": "refused", "manifest": [], "members": [],
        "counts": dict(sorted(counts.items())),
        "unknown": [{
            "member_id": "package", "order": 0, "address": "package",
            "role": role, "hash": _path_hash("refusal", role),
        }],
    }


def _zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise GraphError("member_count")
    compressed = uncompressed = 0
    names: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    for info in infos:
        name = _safe_member(info.filename)
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise GraphError("zip_compression")
        if info.is_dir() or name in names or name.casefold() in folded:
            raise GraphError("duplicate_member")
        compressed += info.compress_size
        uncompressed += info.file_size
        if compressed > MAX_COMPRESSED_BYTES or uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise GraphError("zip_bytes")
        if info.file_size and (not info.compress_size or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO):
            raise GraphError("zip_ratio")
        names[name] = info
        folded.add(name.casefold())
    return names


def _validate_local_mimetype(path: Path) -> None:
    """Read the physical local header independently of ZipInfo metadata."""
    try:
        with path.open("rb") as stream:
            fixed = stream.read(30)
            if len(fixed) != 30:
                raise GraphError("local_mimetype")
            signature, _version, flags, method, _mtime, _mdate, _crc, _compressed, _size, name_len, extra_len = struct.unpack(
                "<IHHHHHIIIHH", fixed,
            )
            name = stream.read(name_len)
            if (signature != 0x04034B50 or flags != 0 or method != zipfile.ZIP_STORED
                    or name != b"mimetype" or extra_len != 0):
                raise GraphError("local_mimetype")
    except OSError as exc:
        raise GraphError("local_mimetype") from exc


def _validate_local_headers(path: Path, infos: list[zipfile.ZipInfo]) -> None:
    """Reconcile every central record with its physical local ZIP header.

    The v1 envelope is deliberately narrower than generic ZIP: ASCII-normal
    member paths, no local/central extras, and either ordinary flags 0 or the
    corpus-proven DEFLATE fast flag 0x0004 (PKWARE APPNOTE bit 2). In
    particular,
    data descriptors and encryption are never accepted.
    """
    try:
        with path.open("rb") as stream:
            for info in infos:
                try:
                    central_name = info.filename.encode("ascii")
                except UnicodeEncodeError as exc:
                    raise GraphError("zip_member_encoding") from exc
                _safe_member(info.filename)
                if info.extra or info.flag_bits not in {0, 0x0004}:
                    raise GraphError("zip_header")
                if info.flag_bits == 0x0004 and info.compress_type != zipfile.ZIP_DEFLATED:
                    raise GraphError("zip_header")
                stream.seek(info.header_offset)
                fixed = stream.read(30)
                if len(fixed) != 30:
                    raise GraphError("zip_header")
                signature, version, flags, method, mtime, mdate, crc, csize, usize, name_len, extra_len = struct.unpack(
                    "<IHHHHHIIIHH", fixed,
                )
                local_name = stream.read(name_len)
                year, month, day, hour, minute, second = info.date_time
                central_mdate = ((year - 1980) << 9) | (month << 5) | day
                central_mtime = (hour << 11) | (minute << 5) | (second // 2)
                if (
                    signature != 0x04034B50
                    or version != info.extract_version
                    or flags != info.flag_bits
                    or method != info.compress_type
                    or mtime != central_mtime
                    or mdate != central_mdate
                    or crc != info.CRC
                    or csize != info.compress_size
                    or usize != info.file_size
                    or extra_len != 0
                    or local_name != central_name
                ):
                    raise GraphError("zip_header")
    except OSError as exc:
        raise GraphError("zip_header") from exc


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    # Limits were checked on the ZipInfo before any member is decompressed.
    try:
        return archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise GraphError("zip_read") from exc


def _validate_ocf(
    archive: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo], infos: list[zipfile.ZipInfo],
) -> None:
    """Validate the fixed HWPX OCF entrypoint before parsing its OPF payload."""
    mimetype = names.get("mimetype")
    container = names.get("META-INF/container.xml")
    if mimetype is None or container is None or not infos:
        raise GraphError("ocf_mimetype")
    first = infos[0]
    if (first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED
            or first.extra or first.header_offset != 0 or _read(archive, mimetype) != HWPX_MIMETYPE):
        raise GraphError("ocf_mimetype")
    root = _parse_xml(_read(archive, container))
    if _qname(root) != (OCF_NS, "container"):
        raise GraphError("ocf_container_root")
    if root.attrib or (root.text and root.text.strip()):
        raise GraphError("ocf_container_shape")
    rootfiles_nodes = _children_named(root, OCF_NS, "rootfiles")
    if len(rootfiles_nodes) != 1 or len(root) != 1:
        raise GraphError("ocf_rootfiles")
    rootfiles = rootfiles_nodes[0]
    if (rootfiles.tail and rootfiles.tail.strip()) or rootfiles.attrib or (rootfiles.text and rootfiles.text.strip()):
        raise GraphError("ocf_rootfiles")
    if any(_qname(node) != (OCF_NS, "rootfile") for node in rootfiles):
        raise GraphError("ocf_rootfile_owner")
    declared: list[tuple[str, str]] = []
    for node in rootfiles:
        if len(node) or (node.text and node.text.strip()) or (node.tail and node.tail.strip()):
            raise GraphError("ocf_rootfile_shape")
        full_path, media_type = node.attrib.get("full-path"), node.attrib.get("media-type")
        if not full_path or not media_type or set(node.attrib) != {"full-path", "media-type"}:
            raise GraphError("ocf_rootfile_shape")
        full_path = _safe_member(full_path)
        if full_path not in names:
            raise GraphError("ocf_missing_rootfile_member")
        declared.append((full_path, media_type))
    if len(declared) != len(set(declared)):
        raise GraphError("ocf_duplicate_rootfile")
    hpf_roots = [node for node in rootfiles if node.attrib.get("media-type") == HPF_MIMETYPE]
    if len(hpf_roots) != 1 or hpf_roots[0].attrib.get("full-path") != "Contents/content.hpf":
        raise GraphError("ocf_hpf_root")
    # Public HWPX fixtures prove these two auxiliary rootfiles.  Treat any
    # other rootfile as conflicting rather than widening the inventory scope.
    allowed_auxiliary = {
        ("Preview/PrvText.txt", "text/plain"),
        ("META-INF/container.rdf", "application/rdf+xml"),
    }
    auxiliary = [item for item in declared if item != ("Contents/content.hpf", HPF_MIMETYPE)]
    if len(auxiliary) != len(set(auxiliary)) or any(item not in allowed_auxiliary for item in auxiliary):
        raise GraphError("ocf_conflicting_rootfile")


def _validate_opf(
    archive: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo]
) -> tuple[list[dict[str, str]], list[str]]:
    manifest_info = names.get("Contents/content.hpf")
    if manifest_info is None:
        raise GraphError("missing_opf")
    root = _parse_xml(_read(archive, manifest_info))
    if _qname(root) != (OPF_NS, "package"):
        raise GraphError("opf_root")
    children = list(root)
    expected_children = [(OPF_NS, "metadata"), _Q_MANIFEST, _Q_SPINE]
    if (set(root.attrib) != {"id", "unique-identifier", "version"}
            or (root.text and root.text.strip())
            or [_qname(child) for child in children] != expected_children
            or any(child.tail and child.tail.strip() for child in children)):
        raise GraphError("opf_cardinality")
    metadata, manifest, spine = children
    if metadata.attrib or (metadata.text and metadata.text.strip()):
        raise GraphError("opf_metadata")
    metadata_children = list(metadata)
    if (len(metadata_children) < 2
            or [_qname(node) for node in metadata_children[:2]] != [(OPF_NS, "title"), (OPF_NS, "language")]
            or any(_qname(node) != (OPF_NS, "meta") for node in metadata_children[2:])):
        raise GraphError("opf_metadata")
    for node in metadata_children:
        qname = _qname(node)
        if len(node) or (node.tail and node.tail.strip()):
            raise GraphError("opf_metadata")
        if qname in {(OPF_NS, "title"), (OPF_NS, "language")}:
            if node.attrib:
                raise GraphError("opf_metadata")
        else:
            allowed_meta = {"name", "content", "{http://www.w3.org/XML/1998/namespace}space"}
            if (set(node.attrib) - allowed_meta or not node.attrib.get("name")
                    or not node.attrib.get("content")
                    or ("{http://www.w3.org/XML/1998/namespace}space" in node.attrib
                        and node.attrib["{http://www.w3.org/XML/1998/namespace}space"] != "preserve")):
                raise GraphError("opf_metadata")
    for owner in (manifest, spine):
        if (set(owner.attrib) - {"id"}
                or ("id" in owner.attrib and not owner.attrib["id"])):
            raise GraphError("opf_owner_identity")
    owner_ids = [owner.attrib["id"] for owner in (manifest, spine) if "id" in owner.attrib]
    if len(owner_ids) != len(set(owner_ids)):
        raise GraphError("opf_owner_identity")
    if ((manifest.text and manifest.text.strip()) or (spine.text and spine.text.strip())
            or (manifest.tail and manifest.tail.strip()) or (spine.tail and spine.tail.strip())):
        raise GraphError("opf_mixed_text")
    if any(_qname(child) != _Q_ITEM for child in manifest):
        raise GraphError("opf_item_parent")
    if any(_qname(child) != _Q_ITEMREF for child in spine):
        raise GraphError("opf_itemref_parent")
    # An item/itemref must not be smuggled below metadata or another OPF node.
    stack: list[tuple[ET.Element, tuple[str, str] | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        qname = _qname(node)
        if qname == _Q_ITEM and parent != _Q_MANIFEST:
            raise GraphError("opf_item_parent")
        if qname == _Q_ITEMREF and parent != _Q_SPINE:
            raise GraphError("opf_itemref_parent")
        stack.extend((child, qname) for child in node)
    items: list[dict[str, str]] = []
    ids: set[str] = set()
    hrefs: set[str] = set()
    href_folds: set[str] = set()
    for node in manifest:
        if len(node) or (node.text and node.text.strip()) or (node.tail and node.tail.strip()):
            raise GraphError("opf_item_shape")
        identifier, href, media = node.attrib.get("id"), node.attrib.get("href"), node.attrib.get("media-type")
        # The pinned public HWPX corpus proves the (Hancom-spelled) optional
        # ``isEmbeded=\"1\"`` flag for embedded binary assets.  Keep that
        # exception closed: it is never a free-form OPF extension and cannot
        # decorate XML story resources.
        allowed_attrs = {"id", "href", "media-type", "isEmbeded"}
        embedded = node.attrib.get("isEmbeded")
        if (not identifier or not href or not media or set(node.attrib) - allowed_attrs
                or (embedded is not None and (embedded != "1" or media == "application/xml"))):
            raise GraphError("opf_item_identity")
        href = _safe_member(href)
        if identifier in ids or identifier.casefold() in {value.casefold() for value in ids}:
            raise GraphError("opf_duplicate_id")
        if href in hrefs or href.casefold() in href_folds or href not in names:
            raise GraphError("opf_duplicate_href")
        if href.lower().endswith(".xml") and media != "application/xml":
            raise GraphError("opf_xml_media")
        if media == "application/xml" and not href.lower().endswith(".xml"):
            raise GraphError("opf_xml_media")
        ids.add(identifier)
        hrefs.add(href)
        href_folds.add(href.casefold())
        items.append({"id": identifier, "href": href, "media": media})
    item_by_id = {item["id"]: item for item in items}
    if any(identifier in ids for identifier in owner_ids):
        raise GraphError("opf_owner_identity")
    spine_ids: list[str] = []
    seen_refs: set[str] = set()
    itemref_ids: set[str] = set()
    for node in spine:
        if len(node) or (node.text and node.text.strip()) or (node.tail and node.tail.strip()):
            raise GraphError("opf_itemref_shape")
        identifier = node.attrib.get("idref")
        node_id = node.attrib.get("id")
        linear = node.attrib.get("linear")
        if (not identifier or identifier not in item_by_id or identifier in seen_refs
                or set(node.attrib) - {"id", "idref", "linear"}
                or (node_id is not None and (not node_id or node_id in itemref_ids or node_id in ids or node_id in owner_ids))
                or (linear is not None and linear not in {"yes", "no"})):
            raise GraphError("opf_spine_ref")
        seen_refs.add(identifier)
        if node_id is not None:
            itemref_ids.add(node_id)
        spine_ids.append(identifier)
    # Every Contents XML is story-bearing or controls the story model.  Its
    # omission is a refusal, including future/master-page paragraph lists.
    for name in names:
        if name == "Contents/content.hpf" or not name.lower().endswith(".xml"):
            continue
        if name.startswith("Contents/") and name not in hrefs:
            raise GraphError("unmanifested_contents_xml")
    return items, spine_ids


def _member_role(root: ET.Element) -> str:
    qname = _qname(root)
    if qname == _Q_SECTION:
        return "section"
    if qname == (HEAD_NS, "head"):
        return "definition"
    if qname == (APP_NS, "HWPApplicationSetting"):
        return "settings"
    if qname[0] in {SECTION_NS, PARAGRAPH_NS, PARAGRAPH10_NS, MASTER_PAGE_NS}:
        return "unsupported_story_resource"
    return "invalid_xml_root"


def _validate_declared_xml(root: ET.Element, role: str) -> None:
    """Closed expanded-QName vocabulary for non-section manifest XML.

    This inventory does not interpret definition content.  It nonetheless
    validates the public-model/corpus vocabulary so a future story subtree
    cannot hide under a valid ``head`` or settings root.
    """
    if role == "definition":
        allowed = {
            HEAD_NS: _HEADER_LOCALS,
            CORE_NS: _HEADER_CORE,
            PARAGRAPH_NS: _HEADER_PARAGRAPH,
        }
        stack: list[tuple[ET.Element, tuple[str, str] | None]] = [(root, None)]
        while stack:
            node, parent = stack.pop()
            namespace, local = _qname(node)
            if local not in allowed.get(namespace, frozenset()):
                raise GraphError("definition_vocabulary")
            if parent is None:
                if (namespace, local) != (HEAD_NS, "head"):
                    raise GraphError("definition_root")
            elif namespace == HEAD_NS:
                if parent[1] not in _HEADER_PARENT_LOCAL[local]:
                    raise GraphError("definition_parent")
                if parent[0] != HEAD_NS and not (
                    parent in {(PARAGRAPH_NS, "case"), (PARAGRAPH_NS, "default")}
                    and local in {"heading", "lineSpacing", "margin", "tabItem"}
                ):
                    raise GraphError("definition_parent")
            elif namespace == PARAGRAPH_NS:
                if (local == "switch" and parent not in {(HEAD_NS, "paraPr"), (HEAD_NS, "tabPr")}) or (
                    local in {"case", "default"} and parent != (PARAGRAPH_NS, "switch")
                ):
                    raise GraphError("definition_parent")
            elif namespace == CORE_NS:
                allowed_parents = {
                    "fillBrush": {(HEAD_NS, "borderFill")},
                    "winBrush": {(CORE_NS, "fillBrush")},
                    "intent": {(HEAD_NS, "margin")}, "left": {(HEAD_NS, "margin")},
                    "next": {(HEAD_NS, "margin")}, "prev": {(HEAD_NS, "margin")},
                    "right": {(HEAD_NS, "margin")},
                }
                if parent not in allowed_parents[local]:
                    raise GraphError("definition_parent")
            qname = (namespace, local)
            stack.extend((child, qname) for child in node)
        return
    if role == "settings":
        allowed_parents = {
            (APP_NS, "HWPApplicationSetting"): {None},
            (APP_NS, "CaretPosition"): {(APP_NS, "HWPApplicationSetting")},
            ("urn:oasis:names:tc:opendocument:xmlns:config:1.0", "config-item-set"): {(APP_NS, "HWPApplicationSetting")},
            ("urn:oasis:names:tc:opendocument:xmlns:config:1.0", "config-item"): {("urn:oasis:names:tc:opendocument:xmlns:config:1.0", "config-item-set")},
        }
        stack = [(root, None)]
        while stack:
            node, parent = stack.pop()
            qname = _qname(node)
            if qname not in allowed_parents or parent not in allowed_parents[qname]:
                raise GraphError("settings_vocabulary")
            stack.extend((child, qname) for child in node)


def _container_ancestry(table_stack: list[dict[str, Any]]) -> tuple[list[dict[str, int]], list[str]] | None:
    """Return closed table/cell ancestry using schema-owned encounter ordinals."""
    if not table_stack:
        return [], []
    rows: list[dict[str, int]] = []
    tokens: list[str] = []
    for depth, table in enumerate(table_stack, start=1):
        cell = table.get("_cell")
        if not isinstance(cell, tuple) or len(cell) != 2:
            return None
        row, col = cell
        if not isinstance(row, int) or not isinstance(col, int) or row < 0 or col < 0:
            return None
        cell_ordinal = table.get("_cell_ordinal")
        if not isinstance(cell_ordinal, int) or cell_ordinal < 0:
            return None
        rows.append({"depth": depth, "table": int(table["order"]), "cell": cell_ordinal})
        tokens.extend((str(depth), str(table["order"]), str(cell_ordinal)))
    return rows, tokens


def _add_unknown(
    unknown: list[dict[str, Any]], member: str, order: int, address: str, role: str, digest: str
) -> None:
    unknown.append(_unknown(member, order, address, role, digest))


def _scan_section(
    *, member: str, order: int, spine_order: int, root: ET.Element, digest: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Iteratively validate the small story/table grammar and build opaque rows."""
    unknown: list[dict[str, Any]] = []
    stories: list[dict[str, Any]] = []
    main_paragraphs: list[dict[str, Any]] = []
    main_tables: list[dict[str, Any]] = []
    table_cells: dict[str, set[tuple[int, int]]] = {}
    note_ids: set[str] = set()
    header_footer_ids: dict[str, set[str]] = {"header": set(), "footer": set()}
    counts = Counter()
    if _qname(root) != _Q_SECTION:
        _add_unknown(unknown, member, order, "section[root]", "invalid_section_root", digest)
        return {"stories": [], "topology": {"spine_order": spine_order, "main_paragraphs": [], "tables": []}}, unknown

    # node, parent QName, safe structural address, current story, table stack.
    stack: list[tuple[ET.Element, tuple[str, str] | None, str, dict[str, Any] | None, list[dict[str, Any]]]] = [
        (root, None, f"section[{spine_order}]", None, [])
    ]
    while stack:
        node, parent, address, story, table_stack = stack.pop()
        namespace, local = _qname(node)
        if node is not root and (namespace, local) == _Q_SECTION:
            _add_unknown(unknown, member, order, address, "nested_section", digest)
            continue
        if namespace not in {SECTION_NS, PARAGRAPH_NS, CORE_NS}:
            _add_unknown(unknown, member, order, address, "foreign_namespace", digest)
            continue
        if namespace == SECTION_NS and local != "sec":
            _add_unknown(unknown, member, order, address, "unknown_xml_element", digest)
            continue
        if namespace == CORE_NS and local not in _KNOWN_CORE:
            _add_unknown(unknown, member, order, address, "unknown_xml_element", digest)
            continue
        if namespace == CORE_NS and parent not in _SECTION_CORE_PARENTS[local]:
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if namespace == PARAGRAPH_NS and local not in _KNOWN_PARAGRAPH:
            role = "unknown_sublist_owner" if _children_named(node, PARAGRAPH_NS, "subList") else "unknown_xml_element"
            _add_unknown(unknown, member, order, address, role, digest)
            continue
        if local in _UNSUPPORTED and namespace == PARAGRAPH_NS:
            _add_unknown(unknown, member, order, address, _UNSUPPORTED[local], digest)
            continue
        if local == "p" and parent not in {_Q_SECTION, (PARAGRAPH_NS, "subList")}:
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "run" and parent != (PARAGRAPH_NS, "p"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "t" and parent != (PARAGRAPH_NS, "run"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "ctrl" and parent != (PARAGRAPH_NS, "run"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local in _CONTROL_ROLES and parent != (PARAGRAPH_NS, "ctrl"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        ancestry = _container_ancestry(table_stack)
        if local in _CONTROL_ROLES and (story is not None or ancestry is None):
            _add_unknown(unknown, member, order, address, "unsupported_nested_story_owner", digest)
            continue
        if local == "subList":
            if parent not in {(PARAGRAPH_NS, "tc"), *((PARAGRAPH_NS, item) for item in _CONTROL_ROLES)}:
                _add_unknown(unknown, member, order, address, "unknown_sublist_owner", digest)
                continue
        # OWPML anchors tables and drawing objects directly in ``hp:run``;
        # controls are a separate run child that owns header/note stories.
        if local == "tbl" and parent != (PARAGRAPH_NS, "run"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "tr" and parent != (PARAGRAPH_NS, "tbl"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "tc" and parent != (PARAGRAPH_NS, "tr"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local in _OBJECTS and parent != (PARAGRAPH_NS, "run"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "tbl" or local in _OBJECTS:
            positions = _children_named(node, PARAGRAPH_NS, "pos")
            if len(positions) != 1:
                _add_unknown(unknown, member, order, address, "invalid_object_position", digest)
                continue
            if not _exact_bool(positions[0].attrib.get("treatAsChar")):
                _add_unknown(unknown, member, order, address, "invalid_treat_as_char", digest)
                continue
        if local in {"cellAddr", "cellSpan", "cellSz", "cellMargin"} and parent != (PARAGRAPH_NS, "tc"):
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        # Current Hancom files place section properties in the first paragraph
        # run; accepting the documented run seat avoids a filename-based
        # special case while still rejecting transplants elsewhere.
        if local == "secPr" and parent not in {_Q_SECTION, (PARAGRAPH_NS, "run")}:
            _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
            continue
        if local == "pos":
            if parent is None or parent[0] != PARAGRAPH_NS or parent[1] not in {*_OBJECTS, "tbl"} or not _exact_bool(node.attrib.get("treatAsChar")):
                _add_unknown(unknown, member, order, address, "invalid_treat_as_char", digest)
                continue

        next_story = story
        next_tables = table_stack
        if local in _CONTROL_ROLES:
            role = _CONTROL_ROLES[local]
            ordinal = sum(1 for item in stories if item["role"] == role)
            ancestry_rows, ancestry_tokens = ancestry or ([], [])
            if role in {"header", "footer"}:
                identifier = node.attrib.get("id")
                if not identifier:
                    _add_unknown(unknown, member, order, address, "missing_header_footer_id", digest)
                elif identifier in header_footer_ids[role]:
                    _add_unknown(unknown, member, order, address, "duplicate_header_footer_id", digest)
                else:
                    header_footer_ids[role].add(identifier)
                page_type = node.attrib.get("applyPageType")
                if page_type not in {"BOTH", "EVEN", "ODD"}:
                    _add_unknown(unknown, member, order, address, "invalid_apply_page_type", digest)
                variant = page_type.lower() if page_type in {"BOTH", "EVEN", "ODD"} else None
            else:
                inst_id = node.attrib.get("instId")
                if not inst_id:
                    _add_unknown(unknown, member, order, address, "missing_note_instance", digest)
                elif inst_id in note_ids:
                    _add_unknown(unknown, member, order, address, "duplicate_note_instance", digest)
                else:
                    note_ids.add(inst_id)
                variant = None
            sublists = _children_named(node, PARAGRAPH_NS, "subList")
            if len(node) != 1 or len(sublists) != 1:
                _add_unknown(unknown, member, order, address, "story_sublist_shape", digest)
            next_story = {
                "role": role, "order": len(stories),
                "address": (
                    f"section[{spine_order}]/story[{role},{ordinal}]" if not ancestry_rows else
                    f"section[{spine_order}]/container[{'/'.join(ancestry_tokens)}]/story[{role},{ordinal}]"
                ),
                "hash": _path_hash("story", str(order), str(spine_order), role, str(ordinal), *ancestry_tokens),
                "counts": {"paragraphs": 0, "tables": 0}, "paragraphs": [], "tables": [],
            }
            if ancestry_rows:
                next_story["container_ancestry"] = ancestry_rows
            if variant is not None:
                next_story["variant"] = variant
            stories.append(next_story)
        elif local == "p":
            target = main_paragraphs if story is None else story["paragraphs"]
            record = {
                "order": len(target), "address": f"{address}/paragraph[{len(target)}]",
                "hash": _path_hash("paragraph", address, str(len(target))),
                "topology": {"table_depth": len(table_stack)},
            }
            target.append(record)
            if story is not None:
                story["counts"]["paragraphs"] += 1
        elif local == "tbl":
            target = main_tables if story is None else story["tables"]
            table = {
                "order": len(target), "address": f"{address}/table[{len(target)}]",
                "hash": _path_hash("table", address, str(len(target))),
                "topology": {
                    "depth": len(table_stack) + 1,
                    "parent": table_stack[-1]["address"] if table_stack else None,
                    "cells": 0,
                },
            }
            target.append(table)
            if story is not None:
                story["counts"]["tables"] += 1
            table_cells[table["address"]] = set()
            next_tables = [*table_stack, table]
        elif local == "tc":
            if not table_stack:
                _add_unknown(unknown, member, order, address, "invalid_xml_parent", digest)
                continue
            cells = _children_named(node, PARAGRAPH_NS, "cellAddr")
            if len(cells) != 1:
                _add_unknown(unknown, member, order, address, "invalid_cell_address", digest)
            else:
                try:
                    pair = (int(cells[0].attrib["rowAddr"]), int(cells[0].attrib["colAddr"]))
                except (KeyError, ValueError):
                    _add_unknown(unknown, member, order, address, "invalid_cell_address", digest)
                else:
                    if pair[0] < 0 or pair[1] < 0:
                        _add_unknown(unknown, member, order, address, "invalid_cell_address", digest)
                        continue
                    scope = table_stack[-1]["address"]
                    if pair in table_cells[scope]:
                        _add_unknown(unknown, member, order, address, "duplicate_cell_address", digest)
                    table_cells[scope].add(pair)
                    cell_ordinal = table_stack[-1]["topology"]["cells"]
                    table_stack[-1]["topology"]["cells"] += 1
                    next_tables = [*table_stack[:-1], {
                        **table_stack[-1], "_cell": pair, "_cell_ordinal": cell_ordinal,
                    }]

        qname = (namespace, local)
        children = list(_iter_children(node))
        for index, child in reversed(children):
            stack.append((child, qname, f"{address}/node[{index}]", next_story, next_tables))
    return {
        "stories": stories,
        "topology": {"spine_order": spine_order, "main_paragraphs": main_paragraphs, "tables": main_tables},
    }, unknown


def inspect_story_graph(document: str | Path) -> dict[str, Any]:
    """Return deterministic JSON-safe inventory; all malformed input is refusal."""
    counts = _empty_counts()
    try:
        path = Path(document)
        if path.suffix.lower() != ".hwpx":
            return _refused(counts, "unsupported_input")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = _zip_members(archive)
            _validate_local_mimetype(path)
            _validate_local_headers(path, infos)
            _validate_ocf(archive, names, infos)
            items, spine_ids = _validate_opf(archive, names)
            parsed: dict[str, tuple[ET.Element, str, str]] = {}
            for item in items:
                href, media = item["href"], item["media"]
                raw = _read(archive, names[href])
                digest = _sha(raw)
                if media == "application/xml":
                    xml_root = _parse_xml(raw)
                    role = _member_role(xml_root)
                    if role in {"definition", "settings"}:
                        _validate_declared_xml(xml_root, role)
                    parsed[href] = (xml_root, digest, role)
                else:
                    parsed[href] = (ET.Element("resource"), digest, "resource")
            section_hrefs = [href for href, (_root, _digest, role) in parsed.items() if role == "section"]
            spine_hrefs = [next(item["href"] for item in items if item["id"] == identifier) for identifier in spine_ids]
            if any(parsed[href][2] not in {"definition", "section"} for href in spine_hrefs):
                raise GraphError("spine_role")
            ordered_sections = [href for href in spine_hrefs if href in section_hrefs]
            if (not section_hrefs or not spine_ids or len(ordered_sections) != len(section_hrefs)
                    or set(ordered_sections) != set(section_hrefs)):
                raise GraphError("section_spine")
            section_order = {href: index for index, href in enumerate(ordered_sections)}
            members: list[dict[str, Any]] = []
            unknown: list[dict[str, Any]] = []
            for order, item in enumerate(items):
                href = item["href"]
                root, digest, role = parsed[href]
                record: dict[str, Any] = {
                    "member_id": _member_id(order), "order": order, "role": role,
                    "hash": _path_hash("member", str(order), role), "stories": [],
                }
                if role == "section":
                    section, found = _scan_section(
                        member=href, order=order, spine_order=section_order[href], root=root, digest=digest,
                    )
                    record.update(section)
                    unknown.extend(found)
                    counts["sections"] += 1
                    counts["main_paragraphs"] += len(section["topology"]["main_paragraphs"])
                    counts["tables"] += len(section["topology"]["tables"])
                    for table in section["topology"]["tables"]:
                        counts["nested_table_max_depth"] = max(
                            counts["nested_table_max_depth"], table["topology"]["depth"],
                        )
                    for story in section["stories"]:
                        counts["stories"] += 1
                        counts["story_paragraphs"] += story["counts"]["paragraphs"]
                        counts["tables"] += story["counts"]["tables"]
                        counts[{"header": "headers", "footer": "footers", "footnote": "footnotes", "endnote": "endnotes"}[story["role"]]] += 1
                        for table in story["tables"]:
                            counts["nested_table_max_depth"] = max(counts["nested_table_max_depth"], table["topology"]["depth"])
                elif role in {"unsupported_story_resource", "invalid_xml_root"}:
                    # A declared XML root is never an opaque generic resource:
                    # paragraph10/master-page/story namespaces are explicitly
                    # unsupported; all other unknown XML roots are invalid.
                    _add_unknown(unknown, href, order, "member[root]", role, digest)
                members.append(record)
            counts["members"] = len(members)
            unknown.sort(key=lambda row: (row["order"], row["address"], row["role"]))
            return {
                "schema": SCHEMA, "status": "refused" if unknown else "passed",
                "manifest": [{"member_id": item["member_id"], "order": item["order"], "role": item["role"], "hash": item["hash"]} for item in members],
                "members": members, "counts": dict(sorted(counts.items())), "unknown": unknown,
            }
    except (OSError, ValueError, KeyError, RecursionError, ET.ParseError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return _refused(counts)


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(prog="story-graph", add_help=True, description="privacy-safe HWPX story inventory")
    parser.add_argument("document")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        payload = inspect_story_graph(args.document)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                Path(args.out).write_text(rendered, encoding="utf-8")
            except (OSError, UnicodeError):
                sys.stderr.write("story-graph: cannot write output (usage error)\n")
                return 2
        sys.stdout.write(rendered)
        return 0 if payload["status"] == "passed" else 3
    except (OSError, UnicodeError, ValueError, RecursionError):
        # A final catch keeps malformed archives and hostile paths from ever
        # producing a traceback or disclosing an exception value.
        sys.stdout.write(json.dumps(_refused(_empty_counts()), sort_keys=True) + "\n")
        return 3


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
