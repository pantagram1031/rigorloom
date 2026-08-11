"""Bounded, privacy-safe HWPX definition/reference graph inventory (T153).

This lane captures one HWPX generation and inventories only the selected
definition and reference graph envelope.  It never emits document names, IDs,
paths, member names, text, or per-node hashes; the graph digest is an opaque
aggregate binding for the selected snapshot, not an eligibility or fidelity
claim.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

try:  # script execution from pipeline/scripts
    import story_graph as _story
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import story_graph as _story


SCHEMA = "rigorloom/hwpx-definition-graph/v1"
SCOPE = "selected_definition_reference_graph_snapshot_only"
REFUSAL_REASONS = frozenset({
    "input_unavailable", "input_too_large",
    "package_outside_supported_envelope", "definition_member_invalid",
    "definition_collection_invalid", "definition_count_mismatch",
    "definition_id_position_mismatch", "definition_reference_invalid",
    "definition_reference_unresolved", "section_reference_invalid",
    "binary_reference_invalid", "unsupported_definition_branch",
    "graph_limit_exceeded", "output_write_failed", "internal_error",
})

# These are availability bounds, not claims about all HWPX documents.
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 1024
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_XML_DEPTH = 256
MAX_XML_NODES = 100_000
MAX_GRAPH_NODES = 200_000
MAX_GRAPH_EDGES = 400_000

NOT_SCANNED_TOKENS = tuple(sorted({
    "definition.binary_payload_semantics",
    "definition.font_face_bstr",
    "definition.numbering_semantics",
    "definition.style_names",
    "definition.tab_semantics",
    "section.text_and_story_semantics",
    "section.object_payload_semantics",
    "document.generated_numbering_state",
}))

HP = _story.PARAGRAPH_NS
HS = _story.SECTION_NS
HH = _story.HEAD_NS
OPF = _story.OPF_NS
OCF = _story.OCF_NS
CORE = _story.CORE_NS
HWPX_MIMETYPE = _story.HWPX_MIMETYPE
HPF_MIMETYPE = _story.HPF_MIMETYPE

LANGUAGES = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
FONT_ATTRS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
FONT_NODE_LANGS = {
    "hangul": "HANGUL", "latin": "LATIN", "hanja": "HANJA",
    "japanese": "JAPANESE", "other": "OTHER", "symbol": "SYMBOL",
    "user": "USER",
}


class GraphError(ValueError):
    """Internal closed refusal signal; public callers see only reason_code."""


def _refusal(reason: str) -> GraphError:
    # Keep all public reason literals visible to the AST contract test.
    if reason == "input_unavailable":
        return GraphError("input_unavailable")
    if reason == "input_too_large":
        return GraphError("input_too_large")
    if reason == "package_outside_supported_envelope":
        return GraphError("package_outside_supported_envelope")
    if reason == "definition_member_invalid":
        return GraphError("definition_member_invalid")
    if reason == "definition_collection_invalid":
        return GraphError("definition_collection_invalid")
    if reason == "definition_count_mismatch":
        return GraphError("definition_count_mismatch")
    if reason == "definition_id_position_mismatch":
        return GraphError("definition_id_position_mismatch")
    if reason == "definition_reference_invalid":
        return GraphError("definition_reference_invalid")
    if reason == "definition_reference_unresolved":
        return GraphError("definition_reference_unresolved")
    if reason == "section_reference_invalid":
        return GraphError("section_reference_invalid")
    if reason == "binary_reference_invalid":
        return GraphError("binary_reference_invalid")
    if reason == "unsupported_definition_branch":
        return GraphError("unsupported_definition_branch")
    if reason == "graph_limit_exceeded":
        return GraphError("graph_limit_exceeded")
    if reason == "output_write_failed":
        return GraphError("output_write_failed")
    return GraphError("internal_error")


def _qname(node: ET.Element) -> tuple[str, str]:
    tag = node.tag
    if not isinstance(tag, str) or not tag.startswith("{") or "}" not in tag:
        return "", ""
    namespace, local = tag[1:].split("}", 1)
    return namespace, local


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_attrs(node: ET.Element) -> tuple[tuple[str, str], ...]:
    """Normalize expanded attribute names; values are only internal digest input."""
    return tuple(sorted((str(key), str(value)) for key, value in node.attrib.items()))


_REFERENCE_ATTRS = frozenset({
    "id", "idRef", "paraPrIDRef", "charPrIDRef", "nextStyleIDRef",
    "tabPrIDRef", "borderFillIDRef", "binaryItemIDRef", "href", "idref",
})


def _canonical_subtree(node: ET.Element, *, omit: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    """Canonical expanded-QName subtree used only as an opaque graph input.

    Source-controlled labels/IDs and references are excluded or represented by
    typed edges elsewhere; text contributes only an opaque digest and length.
    """
    attrs: list[tuple[str, Any]] = []
    for key, value in node.attrib.items():
        local = key.rsplit("}", 1)[-1]
        if local in _REFERENCE_ATTRS or local in omit:
            continue
        if local in {"face", "name"}:
            attrs.append((key, ("opaque", _sha(str(value).encode("utf-8")))))
        else:
            attrs.append((key, str(value)))
    text = (node.text or "")
    text_sig = (len(text), _sha(text.encode("utf-8"))) if text else None
    children = tuple(_canonical_subtree(child, omit=omit) for child in node)
    return (_qname(node), tuple(sorted(attrs)), text_sig, children)


def _check_xml_bounds(root: ET.Element) -> None:
    count = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_XML_NODES or depth > MAX_XML_DEPTH:
            raise _refusal("graph_limit_exceeded")
        stack.extend((child, depth + 1) for child in node)


def _parse_xml(raw: bytes) -> ET.Element:
    if len(raw) > MAX_XML_BYTES:
        raise _refusal("graph_limit_exceeded")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, UnicodeError, RecursionError):
        raise _refusal("definition_member_invalid")
    _check_xml_bounds(root)
    return root


def _safe_regular_source(path: Path) -> bytes:
    try:
        before = path.lstat()
    except OSError:
        raise _refusal("input_unavailable")
    if not path.is_file() or path.is_symlink() or before.st_nlink != 1:
        raise _refusal("input_unavailable")
    if before.st_size > MAX_INPUT_BYTES:
        raise _refusal("input_too_large")
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except OSError:
        raise _refusal("input_unavailable")
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            getattr(after, "st_ctime_ns", 0), after.st_nlink) != (
                before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                getattr(before, "st_ctime_ns", 0), before.st_nlink):
        raise _refusal("input_unavailable")
    if len(raw) > MAX_INPUT_BYTES:
        raise _refusal("input_too_large")
    return raw


def _zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    try:
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        raise _refusal("package_outside_supported_envelope")
    if len(infos) > MAX_MEMBERS:
        raise _refusal("graph_limit_exceeded")
    compressed = uncompressed = 0
    result: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    for info in infos:
        name = info.filename
        parts = name.split("/") if isinstance(name, str) else []
        if (not name or "\\" in name or name.startswith("/")
                or any(part in {"", ".", ".."} for part in parts)
                or len(name) > 512 or (len(name) > 1 and name[1] == ":")
                or info.is_dir() or name in result or name.casefold() in folded):
            raise _refusal("package_outside_supported_envelope")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise _refusal("package_outside_supported_envelope")
        compressed += info.compress_size
        uncompressed += info.file_size
        if (compressed > MAX_COMPRESSED_BYTES or uncompressed > MAX_UNCOMPRESSED_BYTES
                or (info.file_size and (not info.compress_size
                    or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO))):
            raise _refusal("graph_limit_exceeded")
        result[name] = info
        folded.add(name.casefold())
    return result


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        return archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise _refusal("package_outside_supported_envelope")


def _validate_local_headers_bytes(raw: bytes, infos: Iterable[zipfile.ZipInfo]) -> None:
    """Check physical local records without reopening a path."""
    view = memoryview(raw)
    for info in infos:
        offset = info.header_offset
        if offset < 0 or offset + 30 > len(view):
            raise _refusal("package_outside_supported_envelope")
        fixed = view[offset:offset + 30]
        try:
            import struct
            sig, version, flags, method, mtime, mdate, crc, csize, usize, nlen, elen = struct.unpack(
                "<IHHHHHIIIHH", fixed)
        except (struct.error, ValueError):
            raise _refusal("package_outside_supported_envelope")
        end = offset + 30 + nlen + elen
        try:
            name = bytes(view[offset + 30:offset + 30 + nlen]).decode("ascii")
        except UnicodeDecodeError:
            raise _refusal("package_outside_supported_envelope")
        year, month, day, hour, minute, second = info.date_time
        expected_date = ((year - 1980) << 9) | (month << 5) | day
        expected_time = (hour << 11) | (minute << 5) | (second // 2)
        if (end > len(view) or sig != 0x04034B50 or version != info.extract_version
                or flags != info.flag_bits or method != info.compress_type
                or mtime != expected_time or mdate != expected_date
                or crc != info.CRC or csize != info.compress_size
                or usize != info.file_size or elen != 0 or name != info.filename):
            raise _refusal("package_outside_supported_envelope")


def _zip_envelope(raw: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo], list[dict[str, str]], list[str]]:
    archive: zipfile.ZipFile | None = None
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        names = _zip_members(archive)
        infos = archive.infolist()
        _validate_local_headers_bytes(raw, infos)
        mimetype = names.get("mimetype")
        if (not infos or infos[0].filename != "mimetype" or mimetype is None
                or mimetype.compress_type != zipfile.ZIP_STORED
                or infos[0].header_offset != 0
                or _read_member(archive, mimetype) != HWPX_MIMETYPE):
            raise _refusal("package_outside_supported_envelope")
        for info in infos:
            if info.extra or info.flag_bits not in {0, 0x0004}:
                raise _refusal("package_outside_supported_envelope")
            if info.flag_bits == 0x0004 and info.compress_type != zipfile.ZIP_DEFLATED:
                raise _refusal("package_outside_supported_envelope")
        # Reuse the strict OCF/OPF validators over the captured bytes.  Their
        # diagnostic reasons stay private and are mapped at the outer boundary.
        _story._validate_ocf(archive, names, infos)
        # Classify selected OPF BinData failures separately from generic OPF
        # envelope failures so a missing/non-embedded target cannot be
        # mistaken for a package-format refusal.
        opf_probe = _parse_xml(_read_member(archive, names["Contents/content.hpf"]))
        for item_node in opf_probe.iter():
            if _qname(item_node) != (OPF, "item"):
                continue
            href = item_node.attrib.get("href", "")
            media = item_node.attrib.get("media-type", "")
            if not href.startswith("BinData/"):
                continue
            if (href not in names or media == "application/xml"
                    or href.lower().endswith(".xml")
                    or item_node.attrib.get("isEmbeded") != "1"):
                raise _refusal("binary_reference_invalid")
        items, spine_ids = _story._validate_opf(archive, names)
        return archive, names, items, spine_ids
    except GraphError:
        if archive is not None:
            archive.close()
        raise
    except (OSError, TypeError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            zipfile.LargeZipFile, ET.ParseError, RecursionError):
        if archive is not None:
            archive.close()
        raise _refusal("package_outside_supported_envelope")


def _attr_int(node: ET.Element, name: str, *, required: bool = True,
              lower: int | None = None, upper: int | None = None) -> int | None:
    raw = node.attrib.get(name)
    if raw is None and not required:
        return None
    if raw is None or raw.strip() != raw or not raw or raw.startswith(("+", "-")):
        raise _refusal("definition_reference_invalid")
    try:
        value = int(raw, 10)
    except (TypeError, ValueError):
        raise _refusal("definition_reference_invalid")
    if lower is not None and value < lower or upper is not None and value > upper:
        raise _refusal("definition_reference_invalid")
    return value


def _collection(parent: ET.Element, local: str, *, expected: int | None = None) -> list[ET.Element]:
    children = list(parent)
    q = (HH, local[:-1] if local.endswith("s") else local)
    # A few HWPX collection names do not pluralize by simply removing s.
    aliases = {
        "fontfaces": "fontface", "charProperties": "charPr",
        "paraProperties": "paraPr", "borderFills": "borderFill",
        "numberings": "numbering", "styles": "style", "tabProperties": "tabPr",
    }
    q = (HH, aliases.get(local, q[1]))
    if any(_qname(child) != q for child in children):
        raise _refusal("definition_member_invalid")
    declared = _attr_int(parent, "itemCnt")
    if declared != len(children):
        raise _refusal("definition_count_mismatch")
    if expected is not None and declared != expected:
        raise _refusal("definition_count_mismatch")
    return children


def _check_ordinals(nodes: list[ET.Element], *, base: int, id_name: str = "id") -> dict[int, ET.Element]:
    found: dict[int, ET.Element] = {}
    raw_ids: list[int] = []
    for node in nodes:
        value = _attr_int(node, id_name)
        if value is None:
            raise _refusal("definition_id_position_mismatch")
        raw_ids.append(value)
    if len(raw_ids) != len(set(raw_ids)):
        raise _refusal("definition_collection_invalid")
    for ordinal, node in enumerate(nodes, start=base):
        value = _attr_int(node, id_name)
        if value != ordinal:
            raise _refusal("definition_id_position_mismatch")
        found[value] = node
    return found


class _Graph:
    def __init__(self) -> None:
        self.nodes: Counter[str] = Counter()
        self.edges: Counter[str] = Counter()
        self.parts: list[tuple[Any, ...]] = []

    def node(self, kind: str, *parts: Any) -> None:
        self.nodes[kind] += 1
        self.parts.append(("n", kind, *parts))
        if len(self.parts) > MAX_GRAPH_NODES + MAX_GRAPH_EDGES:
            raise _refusal("graph_limit_exceeded")

    def edge(self, kind: str, *parts: Any) -> None:
        self.edges[kind] += 1
        self.parts.append(("e", kind, *parts))
        if len(self.parts) > MAX_GRAPH_NODES + MAX_GRAPH_EDGES:
            raise _refusal("graph_limit_exceeded")

    def digest(self) -> str:
        canonical = json.dumps(sorted(self.parts, key=repr), ensure_ascii=True,
                                separators=(",", ":"), sort_keys=True).encode("utf-8")
        return _sha(canonical)


def _definition_graph(header: ET.Element, opf_items: list[dict[str, str]],
                      names: dict[str, zipfile.ZipInfo], archive: zipfile.ZipFile,
                      graph: _Graph) -> dict[str, dict[int, ET.Element]]:
    if _qname(header) != (HH, "head"):
        raise _refusal("definition_member_invalid")
    try:
        _story._validate_declared_xml(header, "definition")
    except Exception:
        direct_ref = next((node for node in header if _qname(node) == (HH, "refList")), None)
        if direct_ref is not None and any(
                _qname(node)[0] == HH and _qname(node)[1] in {"bullets", "bullet", "future"}
                for node in direct_ref):
            raise _refusal("unsupported_definition_branch")
        raise _refusal("definition_member_invalid")
    ref_lists = [node for node in header if _qname(node) == (HH, "refList")]
    if len(ref_lists) != 1:
        raise _refusal("definition_collection_invalid")
    ref_list = ref_lists[0]
    allowed_collections = {
        "fontfaces", "charProperties", "paraProperties", "borderFills",
        "numberings", "styles", "tabProperties", "memoProperties",
    }
    if any(_qname(node)[1] not in allowed_collections for node in ref_list):
        # Bullets and future definition branches are intentionally closed.
        if any(_qname(node)[0] == HH and _qname(node)[1] not in allowed_collections
               for node in ref_list):
            raise _refusal("unsupported_definition_branch")
        raise _refusal("definition_member_invalid")
    by_local = {_qname(node)[1]: node for node in ref_list}
    if len(by_local) != len(ref_list):
        raise _refusal("definition_collection_invalid")
    required_collections = {"fontfaces", "charProperties", "paraProperties",
                            "borderFills", "styles", "tabProperties"}
    if not required_collections.issubset(by_local):
        raise _refusal("definition_collection_invalid")
    fonts_col = _collection(by_local["fontfaces"], "fontfaces")
    char_col = _collection(by_local["charProperties"], "charProperties")
    para_col = _collection(by_local["paraProperties"], "paraProperties")
    border_col = _collection(by_local["borderFills"], "borderFills")
    number_col = (_collection(by_local["numberings"], "numberings")
                  if "numberings" in by_local else [])
    style_col = _collection(by_local["styles"], "styles")
    tab_col = _collection(by_local["tabProperties"], "tabProperties")
    if len(fonts_col) != 7:
        raise _refusal("definition_count_mismatch")
    fonts: dict[str, dict[int, ET.Element]] = {}
    for ordinal, node in enumerate(fonts_col):
        if _qname(node) != (HH, "fontface"):
            raise _refusal("definition_member_invalid")
        if node.attrib.get("lang") != LANGUAGES[ordinal]:
            raise _refusal("definition_id_position_mismatch")
        declared = _attr_int(node, "fontCnt")
        children = list(node)
        if declared != len(children) or declared is None or declared <= 0:
            raise _refusal("definition_count_mismatch")
        local_fonts: dict[int, ET.Element] = {}
        for font_ordinal, font in enumerate(children):
            if _qname(font) != (HH, "font"):
                raise _refusal("definition_member_invalid")
            font_id = _attr_int(font, "id")
            if font_id != font_ordinal or font_id in local_fonts:
                raise _refusal("definition_id_position_mismatch")
            embedded = font.attrib.get("isEmbedded")
            binary_ref = font.attrib.get("binaryItemIDRef", "")
            if embedded == "1":
                if not binary_ref:
                    raise _refusal("binary_reference_invalid")
                _binary_edge(binary_ref, opf_items, names, archive, graph, "font",
                             (ordinal, font_ordinal, "font"))
            elif embedded == "0":
                if binary_ref:
                    raise _refusal("binary_reference_invalid")
            else:
                raise _refusal("binary_reference_invalid")
            subst = [child for child in font if _qname(child) == (HH, "substFont")]
            if len(subst) > 1:
                raise _refusal("definition_collection_invalid")
            if subst:
                sub = subst[0]
                if "id" in sub.attrib:
                    raise _refusal("definition_member_invalid")
                sub_ref = sub.attrib.get("binaryItemIDRef", "")
                if sub_ref:
                    _binary_edge(sub_ref, opf_items, names, archive, graph, "substFont",
                                 (ordinal, font_ordinal, "substFont"))
            local_fonts[font_id] = font
        # Face labels are source-controlled names; only their opaque digest
        # enters the aggregate graph binding, never the public receipt.
        graph.node("fontface", ordinal, declared, _canonical_subtree(node))
        fonts[LANGUAGES[ordinal]] = local_fonts
    char = _check_ordinals(char_col, base=0)
    para = _check_ordinals(para_col, base=0)
    border = _check_ordinals(border_col, base=1)
    number = _check_ordinals(number_col, base=1)
    style = _check_ordinals(style_col, base=0)
    tab = _check_ordinals(tab_col, base=0)
    for char_id, node in char.items():
        if _qname(node) != (HH, "charPr"):
            raise _refusal("definition_member_invalid")
        border_id = _attr_int(node, "borderFillIDRef")
        _require_ref(border, border_id, "definition_reference_invalid")
        refs = [child for child in node if _qname(child) == (HH, "fontRef")]
        if len(refs) != 1 or set(refs[0].attrib) != set(FONT_ATTRS):
            raise _refusal("definition_member_invalid")
        for attr in FONT_ATTRS:
            ref = _attr_int(refs[0], attr)
            _require_ref(fonts[FONT_NODE_LANGS[attr]], ref, "definition_reference_unresolved")
            graph.edge("charPr->font", char_id, ref, attr)
        if any(_qname(child)[0] not in {HH, CORE, HP} for child in node):
            raise _refusal("definition_member_invalid")
        graph.node("charPr", char_id, _canonical_subtree(node))
        graph.edge("charPr->borderFill", char_id, border_id)
    for para_id, node in para.items():
        if _qname(node) != (HH, "paraPr"):
            raise _refusal("definition_member_invalid")
        tab_id = _attr_int(node, "tabPrIDRef")
        _require_ref(tab, tab_id, "definition_reference_unresolved")
        border_nodes = [child for child in node if _qname(child) == (HH, "border")]
        if len(border_nodes) != 1:
            raise _refusal("definition_member_invalid")
        border_id = _attr_int(border_nodes[0], "borderFillIDRef")
        _require_ref(border, border_id, "definition_reference_invalid")
        headings = [child for child in node if _qname(child) == (HH, "heading")]
        for heading in headings:
            heading_type = heading.attrib.get("type")
            if heading_type == "NUMBER":
                number_id = _attr_int(heading, "idRef")
                _require_ref(number, number_id, "definition_reference_unresolved")
                graph.edge("paraPr->numbering", para_id, number_id)
            elif heading_type in {"OUTLINE", "NONE"}:
                if heading.attrib.get("idRef") != "0":
                    raise _refusal("definition_reference_invalid")
            else:
                raise _refusal("unsupported_definition_branch")
        child_signature = tuple(
            (child.tag, tuple(sorted(child.attrib.items())))
            for child in node
            if _qname(child) != (HH, "border") and _qname(child) != (HH, "heading")
        )
        graph.node("paraPr", para_id, _canonical_subtree(node))
        graph.edge("paraPr->tabPr", para_id, tab_id)
        graph.edge("paraPr->borderFill", para_id, border_id)
    for border_id, node in border.items():
        if _qname(node) != (HH, "borderFill"):
            raise _refusal("definition_member_invalid")
        if any(_qname(child)[0] not in {HH, CORE} for child in node):
            raise _refusal("definition_member_invalid")
        graph.node("borderFill", border_id, _canonical_subtree(node))
    for number_id, node in number.items():
        if _qname(node) != (HH, "numbering"):
            raise _refusal("definition_member_invalid")
        heads = [child for child in node if _qname(child) == (HH, "paraHead")]
        if not heads or len(heads) != len(list(node)):
            raise _refusal("definition_member_invalid")
        # A numbering definition is one typed node; its paraHead children are
        # ordered entries within that node, not separate definitions.
        graph.node("numbering", number_id, _canonical_subtree(node))
        for head_ordinal, head in enumerate(heads):
            allowed_head_attrs = {
                "idRef", "charPrIDRef", "numFormat", "level", "start", "checkable",
                "textOffset", "textOffsetType", "autoIndent", "widthAdjust", "align",
                "useInstWidth",
            }
            if set(head.attrib) - allowed_head_attrs:
                raise _refusal("unsupported_definition_branch")
            # Official files omit idRef; when present it is a local identity
            # and must bind the ordered paraHead rather than being discarded
            # by the reference-attribute canonicalizer.
            head_id = _attr_int(head, "idRef", required=False)
            graph.edge("numbering->paraHead", number_id, head_ordinal, head_id)
            char_ref = _attr_int(head, "charPrIDRef")
            if char_ref != 4294967295:
                _require_ref(char, char_ref, "definition_reference_unresolved")
                graph.edge("numbering->charPr", number_id, head_ordinal, char_ref)
    for style_id, node in style.items():
        if _qname(node) != (HH, "style"):
            raise _refusal("definition_member_invalid")
        for attr, kind, refs in (("paraPrIDRef", "style->paraPr", para),
                                 ("charPrIDRef", "style->charPr", char),
                                 ("nextStyleIDRef", "style->next", style)):
            ref = _attr_int(node, attr)
            _require_ref(refs, ref, "definition_reference_unresolved")
            graph.edge(kind, style_id, ref)
        graph.node("style", style_id, _canonical_subtree(node))
    for tab_id, node in tab.items():
        if _qname(node) != (HH, "tabPr"):
            raise _refusal("definition_member_invalid")
        for child in node:
            if _qname(child)[0] not in {HH, HP, CORE}:
                raise _refusal("definition_member_invalid")
        graph.node("tabPr", tab_id, _canonical_subtree(node))
    return {"font": fonts, "charPr": char, "paraPr": para,
            "borderFill": border, "numbering": number, "style": style, "tabPr": tab}


def _require_ref(mapping: dict[int, ET.Element], value: int | None, reason: str) -> None:
    if value is None or value not in mapping:
        raise _refusal(reason)


def _binary_edge(ref: str, items: list[dict[str, str]], names: dict[str, zipfile.ZipInfo],
                 archive: zipfile.ZipFile, graph: _Graph, source: str,
                 owner: Any = None) -> None:
    matches = [item for item in items if item["id"] == ref]
    if len(matches) != 1:
        raise _refusal("binary_reference_invalid")
    item = matches[0]
    href, media = item["href"], item["media"]
    if (media == "application/xml" or media.endswith("+xml") or media.endswith("/xml")
            or not href.startswith("BinData/") or href not in names
            or item.get("embedded") != "1"):
        raise _refusal("binary_reference_invalid")
    info = names[href]
    payload = _read_member(archive, info)
    graph.edge(f"{source}->BinData", owner, _sha(payload), len(payload))


def _section_graph(section: ET.Element, refs: dict[str, dict[int, ET.Element]], graph: _Graph,
                   opf_items: list[dict[str, str]], names: dict[str, zipfile.ZipInfo],
                   archive: zipfile.ZipFile, *, spine_ordinal: int = 0) -> None:
    if _qname(section) != (HS, "sec"):
        raise _refusal("section_reference_invalid")
    stack: list[tuple[ET.Element, tuple[str, str] | None]] = [(section, None)]
    encounter = 0
    while stack:
        node, parent = stack.pop()
        ns, local = _qname(node)
        if ns not in {HS, HP, CORE}:
            raise _refusal("section_reference_invalid")
        if local == "sec" and parent is not None:
            raise _refusal("section_reference_invalid")
        if ns == HP:
            if local == "p":
                para_ref = _attr_int(node, "paraPrIDRef")
                style_ref = _attr_int(node, "styleIDRef")
                _require_ref(refs["paraPr"], para_ref, "section_reference_invalid")
                _require_ref(refs["style"], style_ref, "section_reference_invalid")
                graph.edge("p->paraPr", spine_ordinal, encounter, para_ref)
                graph.edge("p->style", spine_ordinal, encounter, style_ref)
                encounter += 1
            elif local == "run":
                char_ref = _attr_int(node, "charPrIDRef")
                _require_ref(refs["charPr"], char_ref, "section_reference_invalid")
                graph.edge("run->charPr", spine_ordinal, encounter, char_ref)
                encounter += 1
            elif local in {"tbl", "tc", "cellzone", "pageBorderFill"}:
                border_ref = _attr_int(node, "borderFillIDRef")
                _require_ref(refs["borderFill"], border_ref, "section_reference_invalid")
                graph.edge(f"{local}->borderFill", spine_ordinal, encounter, border_ref)
                encounter += 1
        # Other story/content nodes are intentionally traversed but not
        # interpreted; selected owner references above are the graph scope.
        elif ns == CORE and local == "img":
            binary_ref = node.attrib.get("binaryItemIDRef", "")
            if not binary_ref:
                raise _refusal("section_reference_invalid")
            _binary_edge(binary_ref, opf_items, names, archive, graph, "img",
                         (spine_ordinal, encounter, "img"))
            encounter += 1
        if local in {"p", "run", "tbl", "tc", "cellzone", "pageBorderFill"}:
            graph.node("section", ns, local, tuple(sorted(node.attrib.items())))
        stack.extend((child, (ns, local)) for child in reversed(list(node)))


def _scan_captured(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_INPUT_BYTES:
        raise _refusal("input_too_large")
    archive, names, items, spine_ids = _zip_envelope(raw)
    try:
        return _scan_archive(raw, archive, names, items, spine_ids)
    finally:
        # The archive owns an in-memory BytesIO and must be closed even when
        # XML/graph validation refuses the captured generation.
        archive.close()


def _scan_archive(raw: bytes, archive: zipfile.ZipFile,
                  names: dict[str, zipfile.ZipInfo],
                  items: list[dict[str, str]], spine_ids: list[str]) -> dict[str, Any]:
    graph = _Graph()
    parsed: dict[str, tuple[ET.Element, str, str]] = {}
    try:
        for item in items:
            href, media = item["href"], item["media"]
            member = _read_member(archive, names[href])
            if media == "application/xml":
                root = _parse_xml(member)
                role = "definition" if _qname(root) == (HH, "head") else (
                    "section" if _qname(root) == (HS, "sec") else "other")
                parsed[href] = (root, _sha(member), role)
            else:
                parsed[href] = (ET.Element("resource"), _sha(member), "binary")
        header_hrefs = [href for href, (_root, _digest, role) in parsed.items() if role == "definition"]
        if len(header_hrefs) != 1:
            raise _refusal("definition_collection_invalid")
        # OPF item metadata does not preserve an `embedded` key in story_graph;
        # recover the closed spelling from the captured OPF manifest.
        opf_root = _parse_xml(_read_member(archive, names["Contents/content.hpf"]))
        opf_manifest = next(child for child in opf_root if _qname(child) == (OPF, "manifest"))
        by_id = {item["id"]: item for item in items}
        for node in opf_manifest:
            if _qname(node) == (OPF, "item"):
                by_id[node.attrib["id"]]["embedded"] = node.attrib.get("isEmbeded")
        refs = _definition_graph(parsed[header_hrefs[0]][0], items, names, archive, graph)
        sections = [href for href, (_root, _digest, role) in parsed.items() if role == "section"]
        spine_hrefs: list[str] = []
        for identifier in spine_ids:
            matches = [item["href"] for item in items if item["id"] == identifier]
            if len(matches) != 1:
                raise _refusal("section_reference_invalid")
            spine_hrefs.append(matches[0])
        spine_sections = [href for href in spine_hrefs if parsed.get(href, (None, None, ""))[2] == "section"]
        if not sections or set(sections) != set(spine_sections) or len(sections) != len(spine_sections):
            raise _refusal("section_reference_invalid")
        for spine_ordinal, href in enumerate(spine_sections):
            _section_graph(parsed[href][0], refs, graph, items, names, archive,
                           spine_ordinal=spine_ordinal)
    except StopIteration:
        raise _refusal("package_outside_supported_envelope")
    node_count = sum(graph.nodes.values())
    edge_count = sum(graph.edges.values())
    if node_count > MAX_GRAPH_NODES or edge_count > MAX_GRAPH_EDGES:
        raise _refusal("graph_limit_exceeded")
    counts = {
        "nodes": dict(sorted(graph.nodes.items())),
        "edges": dict(sorted(graph.edges.items())),
    }
    return {
        "schema": SCHEMA,
        "status": "analyzed",
        "source": {"sha256": _sha(raw), "bytes": len(raw)},
        "scope": SCOPE,
        "counts": counts,
        "graph_sha256": graph.digest(),
        "blocking_tokens": [],
        "not_scanned_tokens": list(NOT_SCANNED_TOKENS),
        "evidence_ceiling": SCOPE,
        "eligibility": "unknown",
        "comparison": {"state": "unknown"},
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
        "promotion": "not_run",
    }


def _scan_bytes(raw: bytes) -> dict[str, Any]:
    try:
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise _refusal("input_unavailable")
        return _scan_captured(bytes(raw))
    except GraphError as exc:
        reason = str(exc) if str(exc) in REFUSAL_REASONS else "internal_error"
        return {"schema": SCHEMA, "status": "refused", "reason_code": reason}
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            zipfile.LargeZipFile, ET.ParseError, RecursionError, UnicodeError):
        return {"schema": SCHEMA, "status": "refused", "reason_code": "internal_error"}


def inspect_path(document: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        if document is None or isinstance(document, bool):
            raise _refusal("input_unavailable")
        path = Path(document)
        if path.suffix.casefold() != ".hwpx":
            raise _refusal("input_unavailable")
        raw = _safe_regular_source(path)
        return _scan_captured(raw)
    except GraphError as exc:
        reason = str(exc) if str(exc) in REFUSAL_REASONS else "internal_error"
        return {"schema": SCHEMA, "status": "refused", "reason_code": reason}
    except (OSError, TypeError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            zipfile.LargeZipFile, ET.ParseError, RecursionError, UnicodeError):
        return {"schema": SCHEMA, "status": "refused", "reason_code": "internal_error"}


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:  # pragma: no cover - argparse control path
        self.exit(2, "hwpx-definition-graph: invalid arguments (usage error)\n")


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = _SafeParser(prog="hwpx-definition-graph",
                         description="privacy-safe HWPX definition/reference graph inventory")
    sub = parser.add_subparsers(dest="command")
    inspect_parser = sub.add_parser("inspect", help="inspect one HWPX document")
    inspect_parser.add_argument("document")
    args = parser.parse_args(argv)
    if args.command != "inspect":
        parser.error("missing command")
    payload = inspect_path(args.document)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")) + "\n"
    try:
        written = sys.stdout.write(encoded)
        if written is not None and written != len(encoded):
            raise OSError("short stdout write")
    except (BrokenPipeError, OSError, UnicodeError):
        # A closed/short stdout is a diagnostic refusal, never a traceback or
        # a partial privacy payload.  Closing the stream avoids interpreter
        # shutdown's second BrokenPipeError on the real CLI path.
        try:
            sys.stdout.close()
        except (AttributeError, OSError):
            pass
        return 3
    return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
