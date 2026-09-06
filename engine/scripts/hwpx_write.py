#!/usr/bin/env python3
"""Canonical OWPML (HWPX) writer — E3.1, the round-trip threshold.

The repo's editing paths (``xml_backend.py``, ``tidy_hwpx.py``, ``preedit.py``)
all parse an HWPX zip member, mutate it, and write the members back.  None of
them owns a *serializer*: ``xml_backend`` hands the tree to
``ElementTree.tostring(..., xml_declaration=True)``, which emits

    <?xml version='1.0' encoding='utf-8'?>\\n

where every Hancom-authored part in ``tests/corpus/forms`` (96/96 measured)
emits

    <?xml version="1.0" encoding="UTF-8" standalone="yes" ?>

and which drops the root element's *unused* namespace declarations, because
``ElementTree`` only declares the namespaces its qnames actually reference.
So a Rigorloom-edited section is structurally sound but textually a different
document from a Hancom-edited one.  This module is the missing serializer.

Design
------
Byte fidelity is impossible over ``ElementTree``'s model: it discards the
prefix a qname was written with, the namespace declarations nothing uses, the
order in which declarations appeared, and the difference between ``<a/>`` and
``<a></a>``.  So the model here is a *lexical* DOM built with expat in
non-namespace mode: an element keeps the qname exactly as written (prefix
included) and the attribute list exactly as written (``xmlns:*`` declarations
are simply attributes, in document order).  Nothing is resolved, nothing is
normalized, nothing is reordered — which is why parse → serialize returns the
input bytes rather than an equivalent document.

Namespace *meaning* is still available: :func:`namespace_scope` resolves the
prefixes in scope at any node, and :meth:`XmlNode.local` gives the local name,
so consumers that want the semantic view get it without the writer having to
throw the lexical view away.

What is byte-identical and what is canonical-equal is measured, not asserted:
see ``engine/tests/test_hwpx_roundtrip.py`` and
``engine/references/owpml-writer-notes.md``.

CLI
---
    python hwpx_write.py roundtrip IN.hwpx --out OUT.hwpx   # parse -> serialize
    python hwpx_write.py blank OUT.hwpx                     # minimal new document
    python hwpx_write.py verify IN.hwpx                     # per-part identity report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.parsers import expat

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402

MIMETYPE = b"application/hwp+zip"
MIMETYPE_MEMBER = "mimetype"

#: Every Hancom part in the corpus opens with exactly these bytes (96/96).
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'

#: Members Hancom stores uncompressed (measured over the corpus): the OCF
#: ``mimetype`` sentinel, ``version.xml``, and every PNG payload.
_STORED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp")

XML_MEMBER_SUFFIXES = (".xml", ".hpf", ".rdf")


class HwpxWriteError(Exception):
    """Raised for malformed packages and unwritable models."""


# --------------------------------------------------------------------------
# lexical XML model
# --------------------------------------------------------------------------

class XmlNode:
    """One element, kept exactly as it was written.

    ``qname`` carries the prefix (``"hh:charPr"``).  ``attrs`` is an ordered
    list of ``[name, value]`` pairs and includes ``xmlns``/``xmlns:*``
    declarations, so a declaration that nothing references survives.
    ``explicit_end`` records whether the source wrote ``<a></a>`` rather than
    ``<a/>`` for an empty element.
    """

    __slots__ = ("qname", "attrs", "text", "tail", "children", "explicit_end")

    def __init__(self, qname, attrs=None, text=None, tail=None,
                 children=None, explicit_end=False):
        self.qname = qname
        self.attrs = [list(pair) for pair in (attrs or [])]
        self.text = text
        self.tail = tail
        self.children = list(children or [])
        self.explicit_end = explicit_end

    # -- naming ------------------------------------------------------------
    @property
    def local(self):
        return self.qname.rsplit(":", 1)[-1]

    @property
    def prefix(self):
        return self.qname.rsplit(":", 1)[0] if ":" in self.qname else ""

    # -- attributes --------------------------------------------------------
    def get(self, name, default=None):
        for key, value in self.attrs:
            if key == name:
                return value
        return default

    def set(self, name, value):
        """Update in place (order preserved) or append at the end."""
        for pair in self.attrs:
            if pair[0] == name:
                pair[1] = value
                return
        self.attrs.append([name, value])

    def attr_names(self):
        return [key for key, _ in self.attrs]

    def ns_declarations(self):
        return [(key, value) for key, value in self.attrs
                if key == "xmlns" or key.startswith("xmlns:")]

    # -- traversal ---------------------------------------------------------
    def __iter__(self):
        return iter(self.children)

    def __len__(self):
        return len(self.children)

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def iter_local(self, local):
        for node in self.iter():
            if node.local == local:
                yield node

    def find_local(self, local):
        return next(self.iter_local(local), None)

    def parent_map(self):
        return {id(child): node for node in self.iter() for child in node.children}

    # -- text --------------------------------------------------------------
    def itertext(self):
        if self.text:
            yield self.text
        for child in self.children:
            yield from child.itertext()
            if child.tail:
                yield child.tail

    def text_content(self):
        return "".join(self.itertext())

    def tobytes(self):
        """This element and its subtree, serialized (no prolog, no tail)."""
        out = bytearray()
        _serialize(self, out)
        return bytes(out)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<XmlNode %s attrs=%d children=%d>" % (
            self.qname, len(self.attrs), len(self.children))


class XmlPart:
    """A parsed XML zip member: raw prolog + root element + raw epilog.

    The prolog is kept verbatim (declaration, any comment or PI before the
    root) so its exact spelling — ``standalone="yes" ?>`` with the space —
    round-trips without the writer having to reconstruct it.
    """

    def __init__(self, prolog, root, epilog=b"", source_had_cr=False):
        self.prolog = prolog
        self.root = root
        self.epilog = epilog
        #: XML 1.0 §2.11 makes every parser normalize a literal CR in content
        #: to LF, so a part whose source carried one cannot come back
        #: byte-identical through ANY conforming parser.  Recorded, not hidden.
        self.source_had_cr = source_had_cr

    def tobytes(self):
        out = bytearray(self.prolog)
        _serialize(self.root, out)
        out += self.epilog
        return bytes(out)

    def iter(self):
        return self.root.iter()

    def iter_local(self, local):
        return self.root.iter_local(local)

    def find_local(self, local):
        return self.root.find_local(local)


def _escape_text(value):
    return (value.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))


def _escape_attr(value):
    return (value.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("\r", "&#13;")
                 .replace("\n", "&#10;")
                 .replace("\t", "&#9;"))


def _serialize(node, out):
    out += b"<"
    out += node.qname.encode("utf-8")
    for name, value in node.attrs:
        out += b' '
        out += name.encode("utf-8")
        out += b'="'
        out += _escape_attr(value).encode("utf-8")
        out += b'"'
    empty = not node.children and not node.text
    if empty and not node.explicit_end:
        out += b"/>"
    else:
        out += b">"
        if node.text:
            out += _escape_text(node.text).encode("utf-8")
        for child in node.children:
            _serialize(child, out)
            if child.tail:
                out += _escape_text(child.tail).encode("utf-8")
        out += b"</"
        out += node.qname.encode("utf-8")
        out += b">"


def _start_tag_self_closes(data, start):
    """True when the start tag beginning at ``start`` ends in ``/>``.

    expat cannot tell ``<a/>`` from ``<a></a>``: it fires the same handler pair
    for both and (measured on this corpus) reports ``CurrentByteIndex`` past
    the tag in the empty case, so the byte at the index belongs to whatever
    follows.  The source bytes are the only ground truth, so scan the start tag
    to its unquoted ``>`` and look at the character before it.
    """
    index = start + 1
    quote = None
    length = len(data)
    while index < length:
        char = data[index:index + 1]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in (b'"', b"'"):
            quote = char
        elif char == b">":
            return data[index - 1:index] == b"/"
        index += 1
    return False


def parse_xml_part(data):
    """Parse XML bytes into an :class:`XmlPart` preserving lexical detail."""
    if not isinstance(data, (bytes, bytearray)):
        raise HwpxWriteError("parse_xml_part needs bytes")
    data = bytes(data)
    parser = expat.ParserCreate()
    parser.ordered_attributes = True
    parser.buffer_text = True
    parser.specified_attributes = False

    stack = []
    starts = []
    state = {"root_start": None}

    def start(name, attrs):
        if state["root_start"] is None:
            state["root_start"] = parser.CurrentByteIndex
        pairs = [[attrs[i], attrs[i + 1]] for i in range(0, len(attrs), 2)]
        node = XmlNode(name, pairs)
        if stack:
            stack[-1].children.append(node)
        stack.append(node)
        starts.append(parser.CurrentByteIndex)

    def end(name):
        node = stack.pop()
        start_index = starts.pop()
        if not node.children and not node.text:
            node.explicit_end = not _start_tag_self_closes(data, start_index)
        if not stack:
            state["root"] = node

    def chars(text):
        if not stack:
            return
        node = stack[-1]
        if node.children:
            last = node.children[-1]
            last.tail = (last.tail or "") + text
        else:
            node.text = (node.text or "") + text

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise HwpxWriteError("XML parse failed: %s" % exc) from exc

    root = state.get("root")
    if root is None:
        raise HwpxWriteError("XML part has no root element")
    prolog = data[:state["root_start"]]
    tail_start = data.rfind(b">")
    epilog = data[tail_start + 1:] if tail_start >= 0 else b""
    return XmlPart(prolog, root, epilog, source_had_cr=b"\r" in data)


def model_equal(left, right):
    """Structural equality of two :class:`XmlNode` trees (or two parts)."""
    if isinstance(left, XmlPart) or isinstance(right, XmlPart):
        if not (isinstance(left, XmlPart) and isinstance(right, XmlPart)):
            return False
        return (left.prolog == right.prolog
                and left.epilog == right.epilog
                and model_equal(left.root, right.root))
    if left.qname != right.qname:
        return False
    if [tuple(pair) for pair in left.attrs] != [tuple(pair) for pair in right.attrs]:
        return False
    if (left.text or "") != (right.text or ""):
        return False
    if (left.tail or "") != (right.tail or ""):
        return False
    if left.explicit_end != right.explicit_end:
        return False
    if len(left.children) != len(right.children):
        return False
    return all(model_equal(a, b) for a, b in zip(left.children, right.children))


def namespace_scope(part_or_root, node=None):
    """Prefix -> URI in scope at ``node`` (root scope when ``node`` is None)."""
    root = part_or_root.root if isinstance(part_or_root, XmlPart) else part_or_root
    chain = [root]
    if node is not None and node is not root:
        parents = root.parent_map()
        chain = []
        cursor = node
        while cursor is not None:
            chain.append(cursor)
            cursor = parents.get(id(cursor))
        chain.reverse()
    scope = {}
    for element in chain:
        for name, value in element.ns_declarations():
            scope["" if name == "xmlns" else name.split(":", 1)[1]] = value
    return scope


def root_ns_declarations(data):
    """The root element's ``xmlns`` declarations, in the order the source wrote them."""
    parser = expat.ParserCreate()
    parser.ordered_attributes = True
    found = []

    class _Done(Exception):
        pass

    def start(_name, attrs):
        for index in range(0, len(attrs), 2):
            name = attrs[index]
            if name == "xmlns" or name.startswith("xmlns:"):
                found.append((name, attrs[index + 1]))
        raise _Done

    parser.StartElementHandler = start
    try:
        parser.Parse(bytes(data), True)
    except _Done:
        pass
    except expat.ExpatError as exc:
        raise HwpxWriteError("XML parse failed: %s" % exc) from exc
    return found


def canonical_from_elementtree(root, ns_declarations=None, prolog=XML_DECLARATION):
    """Serialize an ``ElementTree`` root the way Hancom writes XML.

    ``ElementTree`` is the model the repo's editing paths already hold, and its
    own serializer diverges from Hancom in three measured ways (corpus
    ``admrul-gajokdolbom-hyuga-sinchengseo``):

    * the declaration is ``<?xml version='1.0' encoding='utf-8'?>`` plus a
      newline, not ``<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>``;
    * namespace declarations no qname references are dropped — 13 of 15 on the
      section root, 14 of 15 on ``content.hpf``, which alone shrinks that part
      from 2038 to 1260 bytes;
    * empty elements are written ``<a />``, with a space, not ``<a/>`` — 862
      occurrences in one header.

    None of the three changes what the document *means*, and Hancom reads the
    result; all three make a Rigorloom-edited file trivially distinguishable
    from a Hancom-edited one, which is exactly what E3 must eliminate.  So the
    ElementTree output is re-read into the lexical model and re-emitted here,
    with the root's original declarations restored (``ns_declarations``, from
    :func:`root_ns_declarations` on the source bytes).  Declarations
    ElementTree added for namespaces the original did not carry are kept.
    """
    from xml.etree import ElementTree as ET

    raw = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    part = parse_xml_part(raw)
    if ns_declarations:
        emitted = part.root.ns_declarations()
        known = {uri for _name, uri in ns_declarations}
        added = [pair for pair in emitted if pair[1] not in known]
        rest = [list(pair) for pair in part.root.attrs
                if not (pair[0] == "xmlns" or pair[0].startswith("xmlns:"))]
        part.root.attrs = ([list(pair) for pair in ns_declarations]
                           + [list(pair) for pair in added] + rest)
    part.prolog = prolog
    return part.tobytes()


def iter_with_scope(part_or_root, scope=None):
    """Yield ``(node, prefix -> URI)`` for the whole tree in document order.

    :func:`namespace_scope` walks to the root for one node, which is O(n) per
    node and O(n²) over a document — measured: a 500 KB section took minutes.
    This carries the scope down the walk instead.
    """
    root = part_or_root.root if isinstance(part_or_root, XmlPart) else part_or_root
    stack = [(root, dict(scope or {}))]
    while stack:
        node, inherited = stack.pop()
        declarations = node.ns_declarations()
        if declarations:
            current = dict(inherited)
            for name, value in declarations:
                current["" if name == "xmlns" else name.split(":", 1)[1]] = value
        else:
            current = inherited
        yield node, current
        for child in reversed(node.children):
            stack.append((child, current))


def qualified_name(part, node):
    """``{uri}local`` for ``node``, or the bare local name when unbound."""
    scope = namespace_scope(part, node)
    uri = scope.get(node.prefix)
    return "{%s}%s" % (uri, node.local) if uri else node.local


# --------------------------------------------------------------------------
# package
# --------------------------------------------------------------------------

#: General-purpose bits 1-2 of a deflated member name the compression level the
#: producer used.  Hancom writes 0b10 ("fast"), which is zlib level 2 —
#: measured: level 2 reproduces every deflated member's compressed size and
#: CRC across the corpus, no other level does.
_FLAG_LEVEL = {0x0: 6, 0x2: 9, 0x4: 2, 0x6: 1}
_LEVEL_FLAG = {6: 0x0, 9: 0x2, 2: 0x4, 1: 0x6}
_COMPRESS_OPTION_MASK = 0x6

#: Hancom's own deflate level, used for members this writer creates.
HANCOM_DEFLATE_LEVEL = 2


class HwpxPart:
    """One zip member: its archive metadata, its bytes, and (lazily) its tree."""

    __slots__ = ("name", "data", "compress_type", "date_time", "create_system",
                 "external_attr", "extra", "comment", "internal_attr",
                 "create_version", "extract_version", "flag_bits",
                 "_tree")

    def __init__(self, name, data, compress_type=zipfile.ZIP_DEFLATED,
                 date_time=(1980, 1, 1, 0, 0, 0), create_system=0,
                 external_attr=0, extra=b"", comment=b"", internal_attr=0,
                 create_version=20, extract_version=20, flag_bits=None):
        self.name = name
        self.data = bytes(data)
        self.compress_type = compress_type
        self.date_time = date_time
        self.create_system = create_system
        self.external_attr = external_attr
        self.extra = extra
        self.comment = comment
        self.internal_attr = internal_attr
        self.create_version = create_version
        self.extract_version = extract_version
        if flag_bits is None:
            flag_bits = (_LEVEL_FLAG[HANCOM_DEFLATE_LEVEL]
                         if compress_type == zipfile.ZIP_DEFLATED else 0)
        self.flag_bits = flag_bits
        self._tree = None

    @property
    def compresslevel(self):
        if self.compress_type != zipfile.ZIP_DEFLATED:
            return None
        return _FLAG_LEVEL.get(self.flag_bits & _COMPRESS_OPTION_MASK,
                               HANCOM_DEFLATE_LEVEL)

    @property
    def is_xml(self):
        return self.name.endswith(XML_MEMBER_SUFFIXES)

    def tree(self):
        """Parse on first access; mutations are picked up by :meth:`bytes`."""
        if self._tree is None:
            if not self.is_xml:
                raise HwpxWriteError("%s is not an XML member" % self.name)
            self._tree = parse_xml_part(self.data)
        return self._tree

    def set_bytes(self, data):
        self.data = bytes(data)
        self._tree = None

    def bytes(self):
        """Serialized bytes: from the tree once it has been materialized."""
        if self._tree is not None:
            return self._tree.tobytes()
        return self.data

    def zipinfo(self):
        info = zipfile.ZipInfo(self.name, date_time=self.date_time)
        info.compress_type = self.compress_type
        info.create_system = self.create_system
        info.create_version = self.create_version
        info.extract_version = self.extract_version
        info.external_attr = self.external_attr
        info.internal_attr = self.internal_attr
        info.extra = self.extra
        info.comment = self.comment
        return info


class HwpxPackage:
    """An HWPX archive as an ordered list of parts.

    Part order is preserved because the OCF layout Hancom writes is itself
    ordered: ``mimetype`` must be the first member and stored uncompressed for
    the magic-bytes sniff to work.
    """

    def __init__(self, parts=None, zip_comment=b""):
        self.parts = list(parts or [])
        self.zip_comment = zip_comment

    # -- construction ------------------------------------------------------
    @classmethod
    def read(cls, path):
        path = Path(path)
        parts = []
        with zipfile.ZipFile(path) as zin:
            comment = zin.comment
            for info in zin.infolist():
                if info.is_dir():
                    raise HwpxWriteError(
                        "%s: directory members are not part of the HWPX layout "
                        "Hancom writes (%s)" % (path, info.filename))
                parts.append(HwpxPart(
                    info.filename, zin.read(info.filename),
                    compress_type=info.compress_type,
                    date_time=info.date_time,
                    create_system=info.create_system,
                    external_attr=info.external_attr,
                    extra=info.extra,
                    comment=info.comment,
                    internal_attr=info.internal_attr,
                    create_version=info.create_version,
                    extract_version=info.extract_version,
                    flag_bits=info.flag_bits,
                ))
        package = cls(parts, zip_comment=comment)
        package.validate()
        return package

    def validate(self):
        if not self.parts:
            raise HwpxWriteError("package has no members")
        first = self.parts[0]
        if first.name != MIMETYPE_MEMBER:
            raise HwpxWriteError(
                "first member is %r, OCF requires %r" % (first.name, MIMETYPE_MEMBER))
        if first.compress_type != zipfile.ZIP_STORED:
            raise HwpxWriteError("mimetype member must be stored uncompressed")
        if first.data != MIMETYPE:
            raise HwpxWriteError("mimetype member is %r" % first.data)
        if not self.section_names():
            raise HwpxWriteError("package has no Contents/section*.xml member")
        if "Contents/header.xml" not in self.names():
            raise HwpxWriteError("package has no Contents/header.xml member")

    # -- access ------------------------------------------------------------
    def names(self):
        return [part.name for part in self.parts]

    def section_names(self):
        return [name for name in self.names()
                if name.startswith("Contents/section") and name.endswith(".xml")]

    def part(self, name):
        for part in self.parts:
            if part.name == name:
                return part
        raise KeyError(name)

    def has(self, name):
        return any(part.name == name for part in self.parts)

    def xml_parts(self):
        return [part for part in self.parts if part.is_xml]

    def materialize(self):
        """Parse every XML member, so :meth:`write` re-serializes them all."""
        for part in self.xml_parts():
            part.tree()
        return self

    # -- output ------------------------------------------------------------
    def write(self, path):
        """Write the package, atomically, preserving member order and metadata.

        The destination is replaced only after the temp file is complete and
        fsynced. A failed write leaves pre-existing destination bytes in place.
        ``os.replace`` is used instead of ``shutil.move`` so an existing dest
        is not unlinked before the new file is named.
        """
        import os
        path = Path(path)
        if path.exists() and path.is_dir():
            raise HwpxWriteError("destination is a directory: %s" % path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.tobytes()
        handle, temp_name = tempfile.mkstemp(suffix=".hwpx", dir=str(path.parent))
        temp_path = Path(temp_name)
        try:
            written = 0
            view = memoryview(data)
            while written < len(data):
                n = os.write(handle, view[written:])
                if n <= 0:
                    raise OSError("temp write made no progress")
                written += n
            os.fsync(handle)
        except BaseException:
            os.close(handle)
            if temp_path.exists():
                temp_path.unlink()
            raise
        else:
            os.close(handle)
        try:
            os.replace(str(temp_path), str(path))
        except BaseException:
            if temp_path.exists():
                temp_path.unlink()
            raise
        return path

    def tobytes(self):
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zout:
            zout.comment = self.zip_comment
            for part in self.parts:
                zout.writestr(part.zipinfo(), part.bytes(),
                              compresslevel=part.compresslevel)
        return _restore_flag_bits(buffer.getvalue(),
                                  {part.name: part.flag_bits for part in self.parts})

    # -- measurement -------------------------------------------------------
    def roundtrip_report(self):
        """Per-part identity after parse → serialize, for XML members.

        Three graded claims per part, strongest first:

        ``byte_identical``  emitted bytes == source bytes.
        ``canonical_equal`` re-parsing the emitted bytes yields the same model
                            as parsing the source — the information the source
                            carried survives, only its lexical spelling of
                            line ends does not.
        ``idempotent``      emitting the re-parsed emission reproduces it, so
                            the writer has a fixed point and repeated
                            save cycles do not drift.
        """
        report = {"parts": [], "xml_parts": 0, "byte_identical": 0,
                  "canonical_equal": 0, "idempotent": 0}
        for part in self.parts:
            row = {"name": part.name, "xml": part.is_xml,
                   "bytes": len(part.data)}
            if part.is_xml:
                report["xml_parts"] += 1
                parsed = parse_xml_part(part.data)
                emitted = parsed.tobytes()
                reparsed = parse_xml_part(emitted)
                row["byte_identical"] = emitted == part.data
                row["canonical_equal"] = model_equal(parsed, reparsed)
                row["idempotent"] = reparsed.tobytes() == emitted
                row["source_had_cr"] = parsed.source_had_cr
                for key in ("byte_identical", "canonical_equal", "idempotent"):
                    if row[key]:
                        report[key] += 1
                if not row["byte_identical"]:
                    row["diff"] = _first_difference(part.data, emitted)
            report["parts"].append(row)
        total = report["xml_parts"] or 1
        report["ratio"] = report["byte_identical"] / total
        return report


_CD_SIGNATURE = b"PK\x01\x02"
_EOCD_SIGNATURE = b"PK\x05\x06"


def _restore_flag_bits(archive, flags_by_name):
    """Stamp each member's recorded general-purpose flag word back in.

    ``zipfile`` recomputes ``flag_bits`` from scratch on write (it zeroes the
    compression-option bits Hancom sets), and there is no API to keep them.
    The field is at a fixed offset in both the local file header (+6) and the
    central directory entry (+8), so the recorded value is written back after
    the archive is assembled — nothing else about the archive is touched.
    """
    import struct

    data = bytearray(archive)
    eocd = data.rfind(_EOCD_SIGNATURE)
    if eocd < 0:
        return bytes(data)
    entries, cd_offset = struct.unpack("<HI", bytes(data[eocd + 10:eocd + 12])
                                       + bytes(data[eocd + 16:eocd + 20]))
    cursor = cd_offset
    for _ in range(entries):
        if bytes(data[cursor:cursor + 4]) != _CD_SIGNATURE:
            break
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", bytes(data[cursor + 28:cursor + 34]))
        local_offset = struct.unpack("<I", bytes(data[cursor + 42:cursor + 46]))[0]
        name = bytes(data[cursor + 46:cursor + 46 + name_len]).decode(
            "utf-8", "replace")
        if name in flags_by_name:
            flag = flags_by_name[name]
            data[cursor + 8:cursor + 10] = struct.pack("<H", flag)
            if bytes(data[local_offset:local_offset + 4]) == b"PK\x03\x04":
                data[local_offset + 6:local_offset + 8] = struct.pack("<H", flag)
        cursor += 46 + name_len + extra_len + comment_len
    return bytes(data)


def _first_difference(left, right, window=60):
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            start = max(0, index - window // 2)
            return {"offset": index,
                    "original": left[start:index + window].decode("utf-8", "replace"),
                    "emitted": right[start:index + window].decode("utf-8", "replace")}
    if len(left) != len(right):
        return {"offset": limit, "original_len": len(left), "emitted_len": len(right)}
    return None


def default_compress_type(name):
    """The compression Hancom uses for a member of this name (measured)."""
    if name == MIMETYPE_MEMBER or name == "version.xml":
        return zipfile.ZIP_STORED
    if name.lower().endswith(_STORED_SUFFIXES):
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


# --------------------------------------------------------------------------
# the one archive-assembly seam
# --------------------------------------------------------------------------

#: Archive metadata Hancom stamps on every member.  Measured over all 132
#: members of the 12-form corpus: each field takes exactly one value, with no
#: variation between forms, between members, or between stored and deflated.
HANCOM_DATE_TIME = (1980, 1, 1, 0, 0, 0)
HANCOM_CREATE_SYSTEM = 11
HANCOM_CREATE_VERSION = 23
HANCOM_EXTRACT_VERSION = 20
HANCOM_EXTERNAL_ATTR = 0x81800020


def hancom_part(name, data, compress_type=None):
    """One member carrying the archive metadata Hancom stamps on every member.

    ``compress_type`` defaults to :func:`default_compress_type`, so the
    stored/deflated split is Hancom's regardless of how the source archive (if
    there was one) compressed the member.
    """
    if compress_type is None:
        compress_type = default_compress_type(name)
    deflated = compress_type == zipfile.ZIP_DEFLATED
    return HwpxPart(
        name, data,
        compress_type=compress_type,
        date_time=HANCOM_DATE_TIME,
        create_system=HANCOM_CREATE_SYSTEM,
        create_version=HANCOM_CREATE_VERSION,
        extract_version=HANCOM_EXTRACT_VERSION,
        external_attr=HANCOM_EXTERNAL_ATTR,
        internal_attr=0,
        extra=b"",
        comment=b"",
        flag_bits=_LEVEL_FLAG[HANCOM_DEFLATE_LEVEL] if deflated else 0,
    )


def hancom_package(members, zip_comment=b""):
    """A package built from an ordered ``[(name, bytes)]`` sequence."""
    return HwpxPackage([hancom_part(name, data) for name, data in members],
                       zip_comment=zip_comment)


def write_members(out_path, members, zip_comment=b""):
    """Assemble an HWPX from ordered ``(name, bytes)`` pairs, Hancom-shaped.

    This is the repo's single archive-assembly seam: ``tidy_hwpx``,
    ``preedit``, ``xml_backend`` and the new-document builder all route here,
    so every HWPX Rigorloom emits carries the member metadata, stored/deflated
    split, deflate level (2) and general-purpose flag bits (``0x4``) Hancom
    writes — whatever shape the source archive had.

    Member ORDER is the caller's, because the caller inherits it from the
    source archive it read; nothing here reorders members.
    """
    return hancom_package(members, zip_comment=zip_comment).write(out_path)


# --------------------------------------------------------------------------
# new document
# --------------------------------------------------------------------------

#: Namespace declarations Hancom puts on the root of header/section/content.hpf,
#: in the order it writes them (identical across all 10 converted corpus forms).
HANCOM_ROOT_NS = [
    ("xmlns:ha", "http://www.hancom.co.kr/hwpml/2011/app"),
    ("xmlns:hp", "http://www.hancom.co.kr/hwpml/2011/paragraph"),
    ("xmlns:hp10", "http://www.hancom.co.kr/hwpml/2016/paragraph"),
    ("xmlns:hs", "http://www.hancom.co.kr/hwpml/2011/section"),
    ("xmlns:hc", "http://www.hancom.co.kr/hwpml/2011/core"),
    ("xmlns:hh", "http://www.hancom.co.kr/hwpml/2011/head"),
    ("xmlns:hhs", "http://www.hancom.co.kr/hwpml/2011/history"),
    ("xmlns:hm", "http://www.hancom.co.kr/hwpml/2011/master-page"),
    ("xmlns:hpf", "http://www.hancom.co.kr/schema/2011/hpf"),
    ("xmlns:dc", "http://purl.org/dc/elements/1.1/"),
    ("xmlns:opf", "http://www.idpf.org/2007/opf/"),
    ("xmlns:ooxmlchart", "http://www.hancom.co.kr/hwpml/2016/ooxmlchart"),
    ("xmlns:hwpunitchar", "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"),
    ("xmlns:epub", "http://www.idpf.org/2007/ops"),
    ("xmlns:config", "urn:oasis:names:tc:opendocument:xmlns:config:1.0"),
]

_NS_ATTRS = "".join(' %s="%s"' % pair for pair in HANCOM_ROOT_NS)

_BLANK_VERSION = (
    '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"'
    ' tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1"'
    ' buildNumber="0" os="1" xmlVersion="1.5" application="Rigorloom"'
    ' appVersion="0, 0, 0, 0 WIN32LEWindows_10"/>'
)

_BLANK_HEADER = (
    '<hh:head' + _NS_ATTRS + ' version="1.5" secCnt="1">'
    '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
    '<hh:refList>'
    '<hh:fontfaces itemCnt="1">'
    '<hh:fontface lang="HANGUL" fontCnt="1">'
    '<hh:font id="0" face="함초다소체" type="TTF" isEmbedded="0">'
    '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="0" contrast="0"'
    ' strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/>'
    '</hh:font></hh:fontface></hh:fontfaces>'
    '<hh:borderFills itemCnt="1">'
    '<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE"'
    ' breakCellSeparateLine="0">'
    '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>'
    '<hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>'
    '<hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>'
    '<hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>'
    '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
    '</hh:borderFill></hh:borderFills>'
    '<hh:charProperties itemCnt="1">'
    '<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none"'
    ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
    '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"'
    ' symbol="0" user="0"/>'
    '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"'
    ' symbol="100" user="100"/>'
    '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"'
    ' symbol="0" user="0"/>'
    '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"'
    ' symbol="100" user="100"/>'
    '<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"'
    ' symbol="0" user="0"/>'
    '<hh:underline type="NONE" shape="SOLID" color="#000000"/>'
    '<hh:strikeout shape="NONE" color="#000000"/>'
    '<hh:outline type="NONE"/>'
    '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>'
    '</hh:charPr></hh:charProperties>'
    '<hh:tabProperties itemCnt="1">'
    '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
    '</hh:tabProperties>'
    '<hh:numberings itemCnt="0"/>'
    '<hh:paraProperties itemCnt="1">'
    '<hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0"'
    ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
    '<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>'
    '<hh:heading type="NONE" idRef="0" level="0"/>'
    '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"'
    ' widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"'
    ' lineWrap="BREAK"/>'
    '<hh:margin>'
    '<hc:intent value="0" unit="HWPUNIT"/>'
    '<hc:left value="0" unit="HWPUNIT"/>'
    '<hc:right value="0" unit="HWPUNIT"/>'
    '<hc:prev value="0" unit="HWPUNIT"/>'
    '<hc:next value="0" unit="HWPUNIT"/>'
    '</hh:margin>'
    '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>'
    '<hh:border borderFillIDRef="1" offsetLeft="0" offsetRight="0" offsetTop="0"'
    ' offsetBottom="0" connect="0" ignoreMargin="0"/>'
    '</hh:paraPr></hh:paraProperties>'
    '<hh:styles itemCnt="1">'
    '<hh:style id="0" type="PARA" name="바탕글" engName="Normal"'
    ' paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042"'
    ' lockForm="0"/>'
    '</hh:styles>'
    '</hh:refList>'
    '<hh:compatibleDocument targetProgram="HWP201X">'
    '<hh:layoutCompatibility/>'
    '</hh:compatibleDocument>'
    '<hh:docOption>'
    '<hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/>'
    '</hh:docOption>'
    '</hh:head>'
)

_BLANK_SECTION = (
    '<hs:sec' + _NS_ATTRS + '>'
    '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0"'
    ' merged="0">'
    '<hp:run charPrIDRef="0">'
    '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134"'
    ' tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT"'
    ' outlineShapeIDRef="0" memoShapeIDRef="0" textVerticalWidthHead="0"'
    ' masterPageCnt="0">'
    '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
    '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
    '<hp:visibility hideFirstHeader="0" hideFirstFooter="0"'
    ' hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL"'
    ' hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
    '<hp:lineNumberShape restartType="0" countBy="0" distance="0"'
    ' startNumber="0"/>'
    '<hp:pagePr landscape="WIDELY" width="59528" height="84188"'
    ' gutterType="LEFT_ONLY">'
    '<hp:margin header="4252" footer="4252" gutter="0" left="8504"'
    ' right="8504" top="5668" bottom="4252"/>'
    '</hp:pagePr>'
    '<hp:footNotePr>'
    '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
    ' supscript="0"/>'
    '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="850" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="EACH_COLUMN" beneathText="0"/>'
    '</hp:footNotePr>'
    '<hp:endNotePr>'
    '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
    ' supscript="0"/>'
    '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm"'
    ' color="#000000"/>'
    '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
    '</hp:endNotePr>'
    '<hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER"'
    ' headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
    '</hp:pageBorderFill>'
    '<hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER"'
    ' headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
    '</hp:pageBorderFill>'
    '<hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER"'
    ' headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
    '</hp:pageBorderFill>'
    '</hp:secPr>'
    '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1"'
    ' sameSz="1" sameGap="0"/></hp:ctrl>'
    '</hp:run>'
    '<hp:run charPrIDRef="0"><hp:t/></hp:run>'
    '<hp:linesegarray>'
    '<hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000"'
    ' baseline="850" spacing="600" horzpos="0" horzsize="42520"'
    ' flags="393216"/>'
    '</hp:linesegarray>'
    '</hp:p>'
    '</hs:sec>'
)

_BLANK_CONTENT_HPF = (
    '<opf:package' + _NS_ATTRS + ' version="" unique-identifier="" id="">'
    # Empty elements are self-closing throughout: the corpus contains zero
    # `<a></a>` forms across 96 members, so that is the shape Hancom writes.
    '<opf:metadata>'
    '<opf:title/>'
    '<opf:language>ko</opf:language>'
    '<opf:meta name="creator" content="text"/>'
    '<opf:meta name="subject" content="text"/>'
    '<opf:meta name="description" content="text"/>'
    '</opf:metadata>'
    '<opf:manifest>'
    '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
    '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
    '</opf:manifest>'
    '<opf:spine>'
    '<opf:itemref idref="header" linear="yes"/>'
    '<opf:itemref idref="section0" linear="yes"/>'
    '</opf:spine>'
    '</opf:package>'
)

_BLANK_SETTINGS = (
    '<ha:HWPApplicationSetting'
    ' xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"'
    ' xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
    '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
    '</ha:HWPApplicationSetting>'
)

_BLANK_CONTAINER = (
    '<ocf:container'
    ' xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container"'
    ' xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
    '<ocf:rootfiles>'
    '<ocf:rootfile full-path="Contents/content.hpf"'
    ' media-type="application/hwpml-package+xml"/>'
    '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
    '<ocf:rootfile full-path="META-INF/container.rdf"'
    ' media-type="application/rdf+xml"/>'
    '</ocf:rootfiles>'
    '</ocf:container>'
)

_PKG = "http://www.hancom.co.kr/hwpml/2016/meta/pkg#"
_BLANK_RDF = (
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="">'
    '<ns0:hasPart xmlns:ns0="%(pkg)s" rdf:resource="Contents/header.xml"/>'
    '</rdf:Description>'
    '<rdf:Description rdf:about="Contents/header.xml">'
    '<rdf:type rdf:resource="%(pkg)sHeaderFile"/>'
    '</rdf:Description>'
    '<rdf:Description rdf:about="">'
    '<ns0:hasPart xmlns:ns0="%(pkg)s" rdf:resource="Contents/section0.xml"/>'
    '</rdf:Description>'
    '<rdf:Description rdf:about="Contents/section0.xml">'
    '<rdf:type rdf:resource="%(pkg)sSectionFile"/>'
    '</rdf:Description>'
    '<rdf:Description rdf:about="">'
    '<rdf:type rdf:resource="%(pkg)sDocument"/>'
    '</rdf:Description>'
    '</rdf:RDF>' % {"pkg": _PKG}
)

_BLANK_MANIFEST = (
    '<odf:manifest'
    ' xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
)


def _xml_bytes(body):
    return XML_DECLARATION + body.encode("utf-8")


#: Member order Hancom writes, with the two Preview members dropped: a blank
#: document has no rendered preview to embed, and container.xml lists
#: Preview/PrvText.txt as a rootfile, so the text preview is kept (empty).
BLANK_MEMBER_ORDER = [
    "mimetype",
    "version.xml",
    "Contents/header.xml",
    "Contents/section0.xml",
    "Preview/PrvText.txt",
    "settings.xml",
    "META-INF/container.rdf",
    "Contents/content.hpf",
    "META-INF/container.xml",
    "META-INF/manifest.xml",
]


def blank_package():
    """The smallest package this writer can build: one section, one paragraph.

    Structural validity is proven by round-trip and by the repo's own readers
    (``form_inspect``, ``xml_backend``).  Hancom acceptance is E3.2 and needs
    COM — it is NOT proven here.
    """
    payloads = {
        "mimetype": MIMETYPE,
        "version.xml": _xml_bytes(_BLANK_VERSION),
        "Contents/header.xml": _xml_bytes(_BLANK_HEADER),
        "Contents/section0.xml": _xml_bytes(_BLANK_SECTION),
        "Preview/PrvText.txt": b"",
        "settings.xml": _xml_bytes(_BLANK_SETTINGS),
        "META-INF/container.rdf": _xml_bytes(_BLANK_RDF),
        "Contents/content.hpf": _xml_bytes(_BLANK_CONTENT_HPF),
        "META-INF/container.xml": _xml_bytes(_BLANK_CONTAINER),
        "META-INF/manifest.xml": _xml_bytes(_BLANK_MANIFEST),
    }
    package = hancom_package([(name, payloads[name])
                              for name in BLANK_MEMBER_ORDER])
    package.validate()
    return package


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="hwpx_write.py",
        description="Canonical OWPML writer: parse -> serialize with byte fidelity.")
    sub = parser.add_subparsers(dest="command", required=True)

    rt = sub.add_parser("roundtrip", help="parse IN and re-serialize to OUT")
    rt.add_argument("source")
    rt.add_argument("--out", required=True)

    vf = sub.add_parser("verify", help="per-part byte-identity report as JSON")
    vf.add_argument("source")

    bl = sub.add_parser("blank", help="write a minimal blank HWPX")
    bl.add_argument("out")

    args = parser.parse_args(argv)
    if args.command == "roundtrip":
        package = HwpxPackage.read(args.source).materialize()
        package.write(args.out)
        payload = {"ok": True, "out": str(args.out),
                   "parts": package.names(),
                   "source_sha256": _sha256(args.source)}
    elif args.command == "verify":
        package = HwpxPackage.read(args.source)
        payload = package.roundtrip_report()
        payload["ok"] = (payload["canonical_equal"] == payload["xml_parts"]
                         and payload["idempotent"] == payload["xml_parts"])
        payload["source"] = str(args.source)
    else:
        blank_package().write(args.out)
        payload = {"ok": True, "out": str(args.out), "sha256": _sha256(args.out)}

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
