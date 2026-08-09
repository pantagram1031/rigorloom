#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic, privacy-safe quality checks for rendered PDFs.

This module deliberately checks one narrow failure that text presence cannot
prove: a source HWPX may contain Korean syllables while a PDF renderer emits
no usable Korean glyphs (or embeds a subset too small for the syllables it
claims to render).  The result contains hashes, bounded machine tokens, and
numeric counts only.  It never stores source text, code points, font names,
paths, or process output.
"""
from __future__ import annotations

import hashlib
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


QUALITY_SCHEMA = "rigorloom/render-quality/v1"
QUALITY_VERSION = "1"
CHECKER_ID = "hangul_glyphs"
QUALITY_STATES = frozenset({"passed", "failed", "unknown", "not_applicable"})
QUALITY_REASON_CODES = frozenset({
    "passed",
    "source_ascii_only",
    "missing_hangul_glyphs",
    "missing_hangul_text",
    "source_visibility_ambiguous",
    "semantic_text_ambiguous",
    "font_capacity_insufficient",
    "ambiguous_font_mapping",
    "font_mapping_missing",
    "font_buffer_unavailable",
    "nonembedded_font",
    "type3_font",
    "glyph_identity_collapse",
    "glyph_geometry_missing",
    "unsupported_charproc_state",
    "unsupported_graphics_state",
    "malformed_pdf_content",
    "pdf_content_unbounded",
    "source_unreadable",
    "pdf_unreadable",
    "pdf_no_pages",
    "pdf_no_extractable_text",
    "checker_unavailable",
    "layout_hard_failed",
    "visual_quality_gate_pending",
})

# Closed v1 payload.  The numeric fields are deliberately aggregate-only:
# xref counts/capacity bounds are useful for diagnosis without exposing a
# document's characters or the installed font inventory.
QUALITY_REQUIRED_KEYS = frozenset({
    "schema", "checker", "version", "artifact_sha256", "artifact_bytes",
    "state", "reason_code", "source_hangul_count", "pdf_hangul_count",
    "page_count", "mapped_font_xrefs", "checked_font_xrefs",
    "max_unique_hangul_per_xref", "min_glyph_capacity",
})
QUALITY_ALLOWED_KEYS = QUALITY_REQUIRED_KEYS
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_MAX_PDF_CONTENT_BYTES = 1024 * 1024
_MAX_FONT_STREAM_BYTES = 256 * 1024
_MAX_PDF_TOKENS = 200_000


@dataclass(frozen=True)
class _PdfToken:
    """One bounded PDF content token.

    Literal strings are deliberately not returned.  They can carry arbitrary
    text/escape state and are not needed for the Type3 proof, which requires
    explicit hex-string character codes.  Comments are similarly discarded.
    """

    kind: str
    value: Any


class _PdfParseError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _PageCodes(list[int]):
    """Target Type3 codes with bounded page-geometry metadata.

    The list keeps the historical two-value ``(codes, reason)`` return shape
    of ``_page_type3_codes`` while carrying details needed by the optional
    trace/bbox gate.  Metadata never leaves the checker result payload.
    """

    def __init__(
        self,
        values: list[int] | tuple[int, ...] = (),
        *,
        groups: list[dict[str, Any]] | None = None,
        uses_geometry: bool = False,
        uses_clip: bool = False,
    ):
        super().__init__(values)
        self.groups = groups or []
        self.uses_geometry = bool(uses_geometry)
        self.uses_clip = bool(uses_clip)


def _pdf_lex(data: bytes) -> list[_PdfToken]:
    """Lex a small PDF stream while excluding comments and literal strings."""
    if not isinstance(data, (bytes, bytearray)):
        raise _PdfParseError("malformed_pdf_content")
    raw = bytes(data)
    if len(raw) > _MAX_PDF_CONTENT_BYTES:
        raise _PdfParseError("pdf_content_unbounded")
    tokens: list[_PdfToken] = []
    index = 0
    length = len(raw)
    delimiters = b"\x00\t\n\f\r ()<>[]{}/%"
    while index < length:
        byte = raw[index]
        if byte in b"\x00\t\n\f\r " or byte == 0x0c:
            index += 1
            continue
        if byte == 0x25:  # % comment
            index += 1
            while index < length and raw[index] not in b"\r\n":
                index += 1
            continue
        if byte == 0x28:  # literal string: validate balanced nesting, discard
            index += 1
            depth = 1
            escaped = False
            while index < length:
                current = raw[index]
                if escaped:
                    escaped = False
                elif current == 0x5c:
                    escaped = True
                elif current == 0x28:
                    depth += 1
                elif current == 0x29:
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            if depth:
                raise _PdfParseError("malformed_pdf_content")
            continue
        if byte == 0x3c:  # <hex> or << dictionary delimiter
            if index + 1 < length and raw[index + 1] == 0x3c:
                tokens.append(_PdfToken("delim", "<<"))
                index += 2
                continue
            start = index + 1
            index = start
            while index < length and raw[index] != 0x3e:
                if raw[index] == 0x25:
                    while index < length and raw[index] not in b"\r\n":
                        index += 1
                    continue
                index += 1
            if index >= length:
                raise _PdfParseError("malformed_pdf_content")
            hex_text = re.sub(rb"\s+", b"", raw[start:index])
            if len(hex_text) % 2:
                hex_text += b"0"
            try:
                value = bytes.fromhex(hex_text.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise _PdfParseError("malformed_pdf_content") from exc
            tokens.append(_PdfToken("hex", value))
            index += 1
            continue
        if byte == 0x3e and index + 1 < length and raw[index + 1] == 0x3e:
            tokens.append(_PdfToken("delim", ">>"))
            index += 2
            continue
        if byte in b"[]{}":
            tokens.append(_PdfToken("delim", chr(byte)))
            index += 1
            continue
        if byte == 0x2f:  # PDF name
            start = index + 1
            index = start
            while index < length and raw[index] not in delimiters:
                index += 1
            if index == start:
                raise _PdfParseError("malformed_pdf_content")
            tokens.append(_PdfToken("name", raw[start:index].decode("latin1")))
        else:
            start = index
            while index < length and raw[index] not in delimiters:
                index += 1
            value = raw[start:index].decode("latin1")
            try:
                number = float(value)
            except ValueError:
                tokens.append(_PdfToken("word", value))
            else:
                if not math.isfinite(number):
                    raise _PdfParseError("malformed_pdf_content")
                if re.fullmatch(rb"[+-]?\d+", raw[start:index]):
                    number_value: int | float = int(value)
                else:
                    number_value = number
                tokens.append(_PdfToken("number", number_value))
        if len(tokens) > _MAX_PDF_TOKENS:
            raise _PdfParseError("pdf_content_unbounded")
    return tokens


def _hash_file(path: Path) -> tuple[str | None, int | None]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return None, None
    return digest.hexdigest(), size


def _new_result(
    pdf_path: Path,
    *,
    state: str,
    reason_code: str,
    source_hangul_count: int = 0,
    pdf_hangul_count: int = 0,
    page_count: int = 0,
    mapped_font_xrefs: int = 0,
    checked_font_xrefs: int = 0,
    max_unique_hangul_per_xref: int = 0,
    min_glyph_capacity: int = 0,
) -> dict[str, Any]:
    artifact_sha256, artifact_bytes = _hash_file(pdf_path)
    return {
        "schema": QUALITY_SCHEMA,
        "checker": CHECKER_ID,
        "version": QUALITY_VERSION,
        "artifact_sha256": artifact_sha256,
        "artifact_bytes": artifact_bytes,
        "state": state,
        "reason_code": reason_code,
        "source_hangul_count": int(max(0, source_hangul_count)),
        "pdf_hangul_count": int(max(0, pdf_hangul_count)),
        "page_count": int(max(0, page_count)),
        "mapped_font_xrefs": int(max(0, mapped_font_xrefs)),
        "checked_font_xrefs": int(max(0, checked_font_xrefs)),
        "max_unique_hangul_per_xref": int(max(0, max_unique_hangul_per_xref)),
        "min_glyph_capacity": int(max(0, min_glyph_capacity)),
    }


def _source_hangul(path: Path) -> tuple[set[str] | None, str | None]:
    """Return visible section-run syllables without exposing source text.

    HWPX packages contain Hangul in headers, metadata, styles, and other
    non-body members that need not be painted in the rendered page.  The
    quality boundary is deliberately limited to ``Contents/sectionN.xml``
    ``<hp:t>`` run text.  Missing section members are unreadable; a section
    with no text runs simply contributes no visible syllables.
    """
    found: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            xml_names = [
                name for name in archive.namelist()
                if re.search(r"(?:^|/)section\d+\.xml$", name,
                             flags=re.IGNORECASE)
            ]
            if not xml_names:
                return None, "source_unreadable"
            for name in xml_names:
                root = ElementTree.fromstring(archive.read(name))
                for node in root.iter():
                    if node.tag.rsplit("}", 1)[-1].casefold() != "t":
                        continue
                    if node.text:
                        found.update(_HANGUL_RE.findall(node.text))
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return None, "source_unreadable"
    return found, None


def _normalise_font_name(value: Any) -> str:
    text = str(value or "").lstrip("/").casefold()
    # PDF subset prefixes are six uppercase letters plus '+'.  They are not
    # stable identity and must not cause two equivalent names to diverge.
    return re.sub(r"^[a-z]{6}\+", "", text)


def _font_xrefs_for_name(font_rows: list[tuple], span_name: Any) -> set[int]:
    wanted = _normalise_font_name(span_name)
    if not wanted:
        return set()
    matches: set[int] = set()
    for row in font_rows:
        if len(row) < 5:
            continue
        try:
            xref = int(row[0])
        except (TypeError, ValueError):
            continue
        candidates = {_normalise_font_name(row[3]), _normalise_font_name(row[4])}
        if wanted in candidates:
            matches.add(xref)
    return matches


def _span_hangul(span: dict[str, Any]) -> set[str]:
    """Return the resolved Hangul claim without merging conflicting fields."""
    sequence = _span_hangul_sequence(span)
    return set(sequence or ())


def _span_hangul_sequence(span: dict[str, Any]) -> list[str] | None:
    """Resolve rawdict ``chars`` and ``text`` Hangul claims conservatively.

    PyMuPDF may expose both a character list and an ActualText/text claim for
    one span.  Equal claims are safe; a longer text claim is retained so an
    ActualText collapse cannot be hidden by a short code list.  A disagreement
    where the text claim is not longer is ambiguous and must fail closed.
    ``None`` is reserved for that ambiguity; an empty list means no Hangul.
    """
    values: list[str] = []
    chars = span.get("chars")
    if isinstance(chars, (list, tuple)):
        for item in chars:
            if not isinstance(item, dict):
                continue
            value = item.get("c")
            if isinstance(value, int):
                try:
                    value = chr(value)
                except (ValueError, TypeError):
                    value = ""
            if isinstance(value, str):
                values.extend(_HANGUL_RE.findall(value))
    text = span.get("text")
    text_values = _HANGUL_RE.findall(text) if isinstance(text, str) else []
    if values and text_values:
        if values == text_values:
            return values
        # Preserve a longer explicit claim when ActualText/text exposes more
        # syllables than the raw character list.  A short code list must not
        # hide a many-syllable semantic claim from the Type3 identity check.
        if len(text_values) > len(values):
            return text_values
        return None
    if values:
        return values
    if text_values:
        return text_values
    return []


_XREF_RE = re.compile(r"(?<!\d)(\d+)\s+0\s+R\b")


def _xref_from_value(kind: Any, value: Any) -> int | None:
    if str(kind).casefold() == "xref":
        match = _XREF_RE.search(str(value or ""))
        if match:
            return int(match.group(1))
    return None


def _pdf_key(document: Any, xref: int, key: str) -> tuple[str, Any]:
    """Read one xref dictionary key through the bounded PyMuPDF API."""
    try:
        result = document.xref_get_key(int(xref), key)
    except Exception:
        result = None
    if isinstance(result, (tuple, list)) and len(result) >= 2:
        kind, value = result[0], result[1]
        if str(kind).casefold() not in {"null", "none"}:
            return str(kind), value
    try:
        source = document.xref_object(int(xref), compressed=0, ascii=0)
    except Exception:
        source = ""
    if not isinstance(source, str):
        return "null", "null"
    marker = "/" + key
    index = source.find(marker)
    if index < 0:
        return "null", "null"
    tail = source[index + len(marker):].lstrip()
    if tail.startswith("<<"):
        end = tail.find(">>")
        return "dict", tail[:end + 2] if end >= 0 else tail
    match = _XREF_RE.match(tail)
    if match:
        return "xref", match.group(0)
    parts = tail.split()
    return ("name", parts[0]) if parts else ("null", "null")


def _stream_bytes(document: Any, xref: int) -> bytes | None:
    """Return decoded stream bytes, falling back to raw only if needed.

    PyMuPDF exposes ``xref_stream`` as the decoded payload and
    ``xref_stream_raw`` as the encoded bytes.  Type3 CMaps/CharProcs are PDF
    programs, so parsing the raw zlib/ASCII85 envelope would silently turn a
    valid font into an uninspectable one.
    """
    try:
        stream = document.xref_stream(int(xref))
    except Exception:
        stream = None
    if not isinstance(stream, (bytes, bytearray)):
        try:
            stream = document.xref_stream_raw(int(xref))
        except Exception:
            return None
    if not isinstance(stream, (bytes, bytearray)):
        return None
    if len(stream) > _MAX_FONT_STREAM_BYTES:
        return None
    return bytes(stream)


def _stream_unbounded(document: Any, xref: int) -> bool:
    """Distinguish an oversized stream from an unavailable one."""
    try:
        stream = document.xref_stream(int(xref))
    except Exception:
        stream = None
    if not isinstance(stream, (bytes, bytearray)):
        try:
            stream = document.xref_stream_raw(int(xref))
        except Exception:
            return False
    return isinstance(stream, (bytes, bytearray)) and len(stream) > _MAX_FONT_STREAM_BYTES


def _dict_refs(value: str) -> dict[str, int] | None:
    stripped = value.strip() if isinstance(value, str) else ""
    if not stripped.startswith("<<") or not stripped.endswith(">>"):
        return None
    refs: dict[str, int] = {}
    pattern = re.compile(r"/([^\s/<>()\[\]]+)\s+(\d+)\s+0\s+R\b")
    for match in pattern.finditer(value):
        name = match.group(1)
        target = int(match.group(2))
        if name in refs and refs[name] != target:
            return None
        refs[name] = target
    return refs


def _resolve_dict(document: Any, kind: str, value: Any) -> str | None:
    target = _xref_from_value(kind, value)
    if target is None:
        return str(value) if str(kind).casefold() == "dict" else None
    try:
        result = document.xref_object(target, compressed=0, ascii=0)
    except Exception:
        return None
    return result if isinstance(result, str) else None


def _parse_tounicode(data: bytes) -> dict[bytes, str] | None:
    try:
        tokens = _pdf_lex(data)
    except _PdfParseError:
        return None
    mapping: dict[bytes, str] = {}
    active = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "word" and token.value in {"beginbfchar", "beginbfrange"}:
            active = True
            mode = token.value
            index += 1
            continue
        if token.kind == "word" and token.value in {"endbfchar", "endbfrange"}:
            active = False
            index += 1
            continue
        if active and token.kind == "hex":
            if mode == "beginbfchar" and index + 1 < len(tokens) \
                    and tokens[index + 1].kind == "hex":
                code = token.value
                target = tokens[index + 1].value
                try:
                    text = target.decode("utf-16-be")
                except UnicodeDecodeError:
                    text = ""
                if code and text:
                    if code in mapping:
                        return None
                    mapping[code] = text
                index += 2
                continue
            if mode == "beginbfrange" and index + 2 < len(tokens) \
                    and tokens[index + 1].kind == "hex" \
                    and tokens[index + 2].kind == "hex":
                first, last, target = token.value, tokens[index + 1].value, tokens[index + 2].value
                if len(first) == len(last) == 1 and len(target) >= 2:
                    base = int.from_bytes(target, "big")
                    for code in range(first[0], last[0] + 1):
                        try:
                            value = (base + code - first[0]).to_bytes(len(target), "big")
                            text = value.decode("utf-16-be")
                        except (UnicodeDecodeError, ValueError):
                            text = ""
                        if text:
                            code_key = bytes([code])
                            if code_key in mapping:
                                return None
                            mapping[code_key] = text
                index += 3
                continue
        index += 1
    return mapping or None


def _parse_differences(value: str) -> dict[int, str] | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"/Differences\s*\[(.*?)\]", value, flags=re.DOTALL)
    if not match:
        return None
    try:
        tokens = _pdf_lex(match.group(1).encode("latin1"))
    except (UnicodeEncodeError, _PdfParseError):
        return None
    differences: dict[int, str] = {}
    current: int | None = None
    for token in tokens:
        if token.kind == "number":
            if isinstance(token.value, int):
                current = token.value
            else:
                return None
        elif token.kind == "name":
            if current is None or current < 0 or current > 255:
                return None
            if current in differences:
                return None
            differences[current] = token.value
            current += 1
    return differences or None


def _page_content_bytes(page: Any, document: Any) -> bytes | None:
    try:
        content = page.read_contents()
    except Exception:
        content = None
    if content is None:
        try:
            refs = page.get_contents()
        except Exception:
            refs = None
        if not isinstance(refs, (list, tuple)):
            return None
        chunks: list[bytes] = []
        for ref in refs:
            try:
                value = document.xref_stream(int(ref))
            except Exception:
                return None
            if not isinstance(value, (bytes, bytearray)):
                return None
            chunks.append(bytes(value))
        content = b"\n".join(chunks)
    if not isinstance(content, (bytes, bytearray)):
        return None
    return bytes(content)


def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = abs(sum(
        points[index][0] * points[index + 1][1]
        - points[index + 1][0] * points[index][1]
        for index in range(len(points) - 1)
    ) + points[-1][0] * points[0][1] - points[0][0] * points[-1][1]) / 2.0
    return area if math.isfinite(area) else 0.0


def _path_has_segment(subpaths: list[dict[str, Any]]) -> bool:
    return any(
        len(item["points"]) >= 2 and any(
            first != second
            for first, second in zip(item["points"], item["points"][1:])
        )
        for item in subpaths
    )


def _clip_path_is_visible(subpaths: list[dict[str, Any]]) -> bool:
    return bool(subpaths) and all(
        item.get("closed") is True
        and len(item.get("points", [])) >= 4
        and _polygon_area(item["points"]) > 1e-9
        for item in subpaths
    )


def _compose_ctm(
    current: tuple[float, float, float, float, float, float],
    values: list[float],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = current
    A, B, C, D, E, F = values
    return (
        A * a + B * c,
        A * b + B * d,
        C * a + D * c,
        C * b + D * d,
        E * a + F * c + e,
        E * b + F * d + f,
    )


def _transform_point(
    matrix: tuple[float, float, float, float, float, float],
    point: tuple[float, float],
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def _page_type3_codes(
    page: Any,
    document: Any,
    resource_names: set[str],
) -> tuple[list[int], str | None]:
    content = _page_content_bytes(page, document)
    if content is None:
        return [], "font_mapping_missing"
    try:
        tokens = _pdf_lex(content)
    except _PdfParseError as exc:
        return [], exc.reason
    operands: list[_PdfToken] = []
    current_font: str | None = None
    codes: list[int] = []
    array_depth = 0
    dict_depth = 0
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack: list[tuple[
        tuple[float, float, float, float, float, float],
        list[list[tuple[float, float]]],
    ]] = []
    subpaths: list[dict[str, Any]] = []
    clip_pending = False
    active_clips: list[list[tuple[float, float]]] = []
    text_open = False
    groups: list[dict[str, Any]] = []
    uses_geometry = False
    uses_clip = False
    for token in tokens:
        if token.kind == "delim":
            if token.value == "[":
                array_depth += 1
            elif token.value == "]":
                if array_depth <= 0:
                    return [], "malformed_pdf_content"
                array_depth -= 1
            elif token.value == "<<":
                dict_depth += 1
            elif token.value == ">>":
                if dict_depth <= 0:
                    return [], "malformed_pdf_content"
                dict_depth -= 1
            operands.append(token)
            continue
        if token.kind != "word":
            operands.append(token)
            continue
        operator = str(token.value)
        if operator == "BT":
            if text_open:
                return [], "malformed_pdf_content"
            text_open = True
        elif operator == "ET":
            if not text_open:
                return [], "malformed_pdf_content"
            text_open = False
        elif operator == "Tf":
            if not text_open:
                return [], "malformed_pdf_content"
            names = [item.value for item in operands if item.kind == "name"]
            current_font = str(names[-1]) if names else None
        elif operator in {"Tj", "TJ"}:
            if not text_open:
                return [], "malformed_pdf_content"
            if current_font in resource_names:
                hex_values = [item.value for item in operands if item.kind == "hex"]
                # Literal strings are intentionally excluded from the lexer.  Do
                # not let an unrelated string operand hide a later explicit code;
                # if every shown run is literal, the final empty-code check keeps
                # the result unknown.
                group_codes: list[int] = []
                for value in hex_values:
                    codes.extend(value)
                    group_codes.extend(value)
                if group_codes:
                    groups.append({
                        "codes": group_codes,
                        "clips": [list(points) for points in active_clips],
                        "ctm": ctm,
                    })
        elif operator in {"m", "l", "c", "v", "y", "re"}:
            numbers = [item.value for item in operands if item.kind == "number"]
            needed = {"m": 2, "l": 2, "c": 6, "v": 4, "y": 4, "re": 4}[operator]
            if len(numbers) < needed or not all(
                isinstance(number, (int, float)) and math.isfinite(float(number))
                for number in numbers[-needed:]
            ):
                return [], "malformed_pdf_content"
            values = [float(number) for number in numbers[-needed:]]
            if operator == "m":
                subpaths.append({
                    "points": [_transform_point(ctm, (values[0], values[1]))],
                    "closed": False,
                })
            elif operator == "re":
                x, y, width, height = values
                subpaths.append({
                    "points": [
                        _transform_point(ctm, (x, y)),
                        _transform_point(ctm, (x + width, y)),
                        _transform_point(ctm, (x + width, y + height)),
                        _transform_point(ctm, (x, y + height)),
                        _transform_point(ctm, (x, y)),
                    ],
                    "closed": True,
                })
            elif not subpaths:
                return [], "malformed_pdf_content"
            elif operator == "l":
                subpaths[-1]["points"].append(
                    _transform_point(ctm, (values[0], values[1])))
            elif operator == "c":
                subpaths[-1]["points"].append(
                    _transform_point(ctm, (values[4], values[5])))
            elif operator in {"v", "y"}:
                subpaths[-1]["points"].append(
                    _transform_point(ctm, (values[-2], values[-1])))
        elif operator == "h":
            if not subpaths or not subpaths[-1]["points"]:
                return [], "malformed_pdf_content"
            points = subpaths[-1]["points"]
            if points[-1] != points[0]:
                points.append(points[0])
            subpaths[-1]["closed"] = True
        elif operator in {"W", "W*"}:
            uses_geometry = True
            uses_clip = True
            if clip_pending or not _clip_path_is_visible(subpaths):
                return [], "unsupported_graphics_state"
            clip_pending = True
        elif operator == "n":
            if not clip_pending or not _clip_path_is_visible(subpaths):
                return [], "unsupported_graphics_state"
            clip_pending = False
            active_clips.extend(
                [list(item["points"]) for item in subpaths])
            subpaths = []
        elif operator == "q":
            ctm_stack.append((ctm, [list(points) for points in active_clips]))
        elif operator == "Q":
            if not ctm_stack:
                return [], "unsupported_graphics_state"
            ctm, active_clips = ctm_stack.pop()
        elif operator == "cm":
            uses_geometry = True
            numbers = [item.value for item in operands if item.kind == "number"]
            if len(numbers) < 6 or not all(
                isinstance(number, (int, float)) and math.isfinite(float(number))
                for number in numbers[-6:]
            ):
                return [], "malformed_pdf_content"
            values = [float(number) for number in numbers[-6:]]
            if abs(values[0] * values[3] - values[1] * values[2]) <= 1e-12:
                return [], "unsupported_graphics_state"
            ctm = _compose_ctm(ctm, values)
            if not all(math.isfinite(value) for value in ctm):
                return [], "unsupported_graphics_state"
        elif operator in {"S", "s", "F", "f", "f*", "B", "b", "B*", "b*"}:
            if not subpaths:
                return [], "unsupported_graphics_state"
            stroke = operator in {"S", "s", "B", "b", "B*", "b*"}
            fill = operator in {"F", "f", "f*", "B", "b", "B*", "b*"}
            if (stroke and not _path_has_segment(subpaths)) \
                    or (fill and not any(_polygon_area(item["points"]) > 1e-9
                                         for item in subpaths)):
                return [], "unsupported_graphics_state"
            subpaths = []
        elif operator == "Tr":
            numbers = [item.value for item in operands if item.kind == "number"]
            if not numbers or numbers[-1] not in {0, 1, 2}:
                return [], "unsupported_graphics_state"
        elif operator in {
            "gs", "BDC", "BMC", "EMC", "Do", "BI", "ID", "EI",
        }:
            return [], "unsupported_graphics_state"
        operands = []
    if array_depth or dict_depth:
        return [], "malformed_pdf_content"
    if text_open:
        return [], "malformed_pdf_content"
    if ctm_stack or clip_pending or subpaths:
        return [], "unsupported_graphics_state"
    return _PageCodes(
        codes,
        groups=groups,
        uses_geometry=uses_geometry,
        uses_clip=uses_clip,
    ), None


def _finite_bbox(value: Any) -> tuple[float, float, float, float] | None:
    """Read one finite, positive rectangle without retaining its coordinates."""
    if isinstance(value, dict):
        value = value.get("bbox", value.get("rect"))
    if value is None:
        return None
    try:
        if all(hasattr(value, name) for name in ("x0", "y0", "x1", "y1")):
            values = [value.x0, value.y0, value.x1, value.y1]
        else:
            values = list(value)[:4]
    except (TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(item) for item in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _page_rect(page: Any) -> tuple[float, float, float, float] | None:
    return _finite_bbox(getattr(page, "rect", None))


def _page_matrix(
    page: Any,
) -> tuple[float, float, float, float, float, float] | None:
    value = getattr(page, "transformation_matrix", None)
    if value is None:
        return None
    try:
        if all(hasattr(value, name) for name in ("a", "b", "c", "d", "e", "f")):
            values = [value.a, value.b, value.c, value.d, value.e, value.f]
        else:
            values = list(value)[:6]
    except (TypeError, ValueError):
        return None
    if len(values) != 6:
        return None
    try:
        result = tuple(float(item) for item in values)
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def _rect_intersection_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    return max(0.0, width) * max(0.0, height)


def _clip_polygon_to_rect(
    points: list[tuple[float, float]],
    rect: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """Clip an arbitrary polygon against a convex rectangle."""
    polygon = list(points)
    left, bottom, right, top = rect
    for axis, bound, keep_greater in (
        (0, left, True), (0, right, False),
        (1, bottom, True), (1, top, False),
    ):
        if not polygon:
            break
        output: list[tuple[float, float]] = []

        def inside(point: tuple[float, float]) -> bool:
            return point[axis] >= bound if keep_greater else point[axis] <= bound

        def intersection(
            first: tuple[float, float], second: tuple[float, float]
        ) -> tuple[float, float]:
            denominator = second[axis] - first[axis]
            if abs(denominator) <= 1e-15:
                return first
            ratio = (bound - first[axis]) / denominator
            return (
                first[0] + ratio * (second[0] - first[0]),
                first[1] + ratio * (second[1] - first[1]),
            )

        previous = polygon[-1]
        for current in polygon:
            current_inside = inside(current)
            previous_inside = inside(previous)
            if current_inside != previous_inside:
                output.append(intersection(previous, current))
            if current_inside:
                output.append(current)
            previous = current
        polygon = output
    return polygon


def _polygon_rect_intersection_area(
    points: list[tuple[float, float]],
    rect: tuple[float, float, float, float],
) -> float:
    if len(points) < 3:
        return 0.0
    return _polygon_area(_clip_polygon_to_rect(points, rect))


def _bboxlog_entry(value: Any) -> tuple[str, tuple[float, float, float, float]] | None:
    if isinstance(value, dict):
        kind = value.get("type", value.get("kind"))
        bbox = value.get("bbox", value.get("rect"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        kind, bbox = value[0], value[1]
    else:
        return None
    if not isinstance(kind, str):
        return None
    parsed = _finite_bbox(bbox)
    return (kind, parsed) if parsed is not None else None


def _trace_hangul(
    trace: dict[str, Any],
    cmap: dict[bytes, str],
) -> list[str] | None:
    values: list[str] = []
    chars = trace.get("chars")
    if chars is not None:
        if not isinstance(chars, (list, tuple)):
            return None
        for item in chars:
            candidate = item
            semantic_value = False
            cmap_value = False
            if isinstance(item, (list, tuple)):
                if len(item) < 1:
                    return None
                candidate = item[0]
                # PyMuPDF's documented tuple[0] is a Unicode code point, not
                # the PDF source code.  Do not remap small ASCII values through
                # a CMap (a code 32 space can otherwise become a Hangul glyph).
                semantic_value = True
            elif isinstance(item, dict):
                if "code" in item or "cid" in item:
                    candidate = item.get("code", item.get("cid"))
                    cmap_value = True
                elif "unicode" in item or "c" in item:
                    candidate = item.get("unicode", item.get("c"))
                    semantic_value = True
                elif "text" in item:
                    candidate = item["text"]
                    semantic_value = True
                else:
                    return None
            if isinstance(candidate, int):
                if candidate < 0:
                    return None
                if semantic_value:
                    try:
                        text = chr(candidate)
                    except (ValueError, OverflowError):
                        return None
                elif cmap_value:
                    if candidate > 255:
                        return None
                    text = cmap.get(bytes([candidate]), "")
                else:
                    try:
                        text = chr(candidate)
                    except (ValueError, OverflowError):
                        return None
            elif isinstance(candidate, (bytes, bytearray)):
                text = cmap.get(bytes(candidate), "")
            elif isinstance(candidate, str):
                text = candidate
            else:
                return None
            values.extend(_HANGUL_RE.findall(text))
    if values:
        return values
    text = trace.get("text")
    return _HANGUL_RE.findall(text) if isinstance(text, str) else []


def _validate_type3_page_geometry(
    page: Any,
    resource_names: set[str],
    cmap: dict[bytes, str],
    shown_chars: list[str],
    codes: _PageCodes,
) -> str | None:
    """Bind cm/clip Type3 text to bounded page trace and path evidence."""
    methods = ("get_texttrace", "get_bboxlog")
    if not all(callable(getattr(page, name, None)) for name in methods):
        return "unsupported_graphics_state"
    page_box = _page_rect(page)
    matrix = _page_matrix(page)
    if page_box is None or matrix is None:
        return "unsupported_graphics_state"
    try:
        traces = page.get_texttrace()
        bboxlog = page.get_bboxlog()
    except Exception:
        return "unsupported_graphics_state"
    if not isinstance(traces, (list, tuple)) or not isinstance(bboxlog, (list, tuple)):
        return "unsupported_graphics_state"
    parsed_bboxlog = [_bboxlog_entry(item) for item in bboxlog]
    if any(item is None for item in parsed_bboxlog):
        return "unsupported_graphics_state"
    target_names = {_normalise_font_name(name) for name in resource_names}
    expected: list[str] = []
    group_ranges: list[tuple[int, int, dict[str, Any]]] = []
    for group in codes.groups:
        if not isinstance(group, dict) or not isinstance(group.get("codes"), list):
            return "unsupported_graphics_state"
        start = len(expected)
        for code in group["codes"]:
            if not isinstance(code, int) or code < 0 or code > 255:
                return "unsupported_graphics_state"
            text = cmap.get(bytes([code]), "")
            expected.extend(_HANGUL_RE.findall(text))
        if len(expected) > start:
            group_ranges.append((start, len(expected), group))
    if expected != shown_chars:
        return "unsupported_graphics_state"
    target_traces: list[tuple[dict[str, Any], list[str], tuple[float, float, float, float]]] = []
    for trace in traces:
        if not isinstance(trace, dict):
            return "unsupported_graphics_state"
        font = trace.get("font", trace.get("font_name"))
        if font is None:
            continue
        if _normalise_font_name(font) not in target_names:
            continue
        sequence = _trace_hangul(trace, cmap)
        if sequence is None or not sequence:
            continue
        bbox = _finite_bbox(trace.get("bbox", trace.get("rect")))
        if bbox is None or _rect_intersection_area(bbox, page_box) <= 0:
            return "unsupported_graphics_state"
        if "opacity" not in trace:
            return "unsupported_graphics_state"
        opacity = trace["opacity"]
        if isinstance(opacity, bool):
            return "unsupported_graphics_state"
        try:
            opacity_value = float(opacity)
        except (TypeError, ValueError):
            return "unsupported_graphics_state"
        if not math.isfinite(opacity_value) or opacity_value <= 0:
            return "unsupported_graphics_state"
        trace_type = trace.get("type")
        if isinstance(trace_type, bool) or trace_type not in {0, 1, 3}:
            return "unsupported_graphics_state"
        target_traces.append((trace, sequence, bbox))
    if not target_traces:
        return "unsupported_graphics_state"
    trace_sequence = [char for _, sequence, _ in target_traces for char in sequence]
    if trace_sequence != expected:
        return "unsupported_graphics_state"
    cursor = 0
    for trace, sequence, trace_box in target_traces:
        seqno = trace.get("seqno")
        if not isinstance(seqno, int) or isinstance(seqno, bool) or seqno < 0:
            return "unsupported_graphics_state"
        if seqno >= len(parsed_bboxlog):
            return "unsupported_graphics_state"
        text_entry = parsed_bboxlog[seqno]
        if text_entry is None:
            return "unsupported_graphics_state"
        trace_type = trace.get("type")
        text_kind = {0: "fill-text", 1: "stroke-text", 3: "ignore-text"}.get(trace_type)
        if text_kind is None or text_entry[0] != text_kind:
            return "unsupported_graphics_state"
        if trace_type == 3:
            if seqno < 2:
                return "unsupported_graphics_state"
            before = parsed_bboxlog[seqno - 2]
            previous = parsed_bboxlog[seqno - 1]
            if before is None or previous is None:
                return "unsupported_graphics_state"
            if {before[0], previous[0]} != {"fill-path", "stroke-path"}:
                return "unsupported_graphics_state"
            for _, path_box in (before, previous):
                if _rect_intersection_area(path_box, page_box) < (
                    path_box[2] - path_box[0]) * (path_box[3] - path_box[1]) - 1e-9:
                    return "unsupported_graphics_state"
                if _rect_intersection_area(path_box, trace_box) < (
                    0.5 * (trace_box[2] - trace_box[0]) * (trace_box[3] - trace_box[1])):
                    return "unsupported_graphics_state"
        end = cursor + len(sequence)
        if expected[cursor:end] != sequence:
            return "unsupported_graphics_state"
        relevant = [group for start, stop, group in group_ranges
                     if start < end and stop > cursor]
        if not relevant:
            return "unsupported_graphics_state"
        for group in relevant:
            group_ctm = group.get("ctm")
            if not isinstance(group_ctm, (list, tuple)) or len(group_ctm) != 6:
                return "unsupported_graphics_state"
            try:
                group_origin = _transform_point(
                    matrix,
                    _transform_point(tuple(float(value) for value in group_ctm), (0.0, 0.0)),
                )
            except (TypeError, ValueError):
                return "unsupported_graphics_state"
            if not all(math.isfinite(value) for value in group_origin):
                return "unsupported_graphics_state"
            if not (
                page_box[0] - 1e-9 <= group_origin[0] <= page_box[2] + 1e-9
                and page_box[1] - 1e-9 <= group_origin[1] <= page_box[3] + 1e-9
            ):
                return "unsupported_graphics_state"
            clips = group.get("clips")
            if codes.uses_clip and not isinstance(clips, list):
                return "unsupported_graphics_state"
            if codes.uses_clip and not clips:
                return "unsupported_graphics_state"
            for polygon in clips or []:
                if not isinstance(polygon, list) or len(polygon) < 3:
                    return "unsupported_graphics_state"
                page_polygon = [_transform_point(matrix, point) for point in polygon]
                if any(not all(math.isfinite(value) for value in point)
                       for point in page_polygon):
                    return "unsupported_graphics_state"
                trace_area = (trace_box[2] - trace_box[0]) * (trace_box[3] - trace_box[1])
                if _polygon_rect_intersection_area(page_polygon, trace_box) < trace_area - 1e-9:
                    return "unsupported_graphics_state"
        cursor = end
    return None


def _charproc_program(
    data: bytes,
) -> tuple[str | None, str | None]:
    """Validate metrics, path construction, and paint in one CharProc."""
    try:
        tokens = _pdf_lex(data)
    except _PdfParseError as exc:
        return None, exc.reason
    operands: list[_PdfToken] = []
    metrics_seen = False
    path_seen = False
    path_points: list[tuple[float, float]] = []
    painted = False
    subpaths: list[dict[str, Any]] = []
    array_depth = 0
    dict_depth = 0

    def _area(points: list[tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        area = abs(sum(
            points[index][0] * points[index + 1][1]
            - points[index + 1][0] * points[index][1]
            for index in range(len(points) - 1)
        ) + points[-1][0] * points[0][1] - points[0][0] * points[-1][1]) / 2.0
        return area if math.isfinite(area) else 0.0

    def _has_segment() -> bool:
        return any(
            len(item["points"]) >= 2 and any(
                first != second
                for first, second in zip(item["points"], item["points"][1:])
            )
            for item in subpaths
        )

    def _has_area() -> bool:
        return any(_area(item["points"]) > 1e-9 for item in subpaths)

    for token in tokens:
        if token.kind == "delim":
            if token.value == "[":
                array_depth += 1
            elif token.value == "]":
                if array_depth <= 0:
                    return None, "malformed_pdf_content"
                array_depth -= 1
            elif token.value == "<<":
                dict_depth += 1
            elif token.value == ">>":
                if dict_depth <= 0:
                    return None, "malformed_pdf_content"
                dict_depth -= 1
            operands.append(token)
            continue
        if token.kind != "word":
            operands.append(token)
            continue
        operator = str(token.value)
        if operator in {"d0", "d1"}:
            numbers = [item.value for item in operands if item.kind == "number"]
            expected = 2 if operator == "d0" else 6
            if len(numbers) < expected:
                return None, "malformed_pdf_content"
            numbers = numbers[-expected:]
            if not all(isinstance(number, (int, float)) and math.isfinite(float(number))
                       for number in numbers):
                return None, "malformed_pdf_content"
            if float(numbers[0]) == 0 and float(numbers[1]) == 0:
                return None, "glyph_geometry_missing"
            if operator == "d1" and (float(numbers[4]) == float(numbers[2])
                                     or float(numbers[5]) == float(numbers[3])):
                return None, "glyph_geometry_missing"
            metrics_seen = True
        elif operator in {"m", "l", "c", "v", "y", "re"}:
            numbers = [item.value for item in operands if item.kind == "number"]
            needed = {"m": 2, "l": 2, "c": 6, "v": 4, "y": 4, "re": 4}[operator]
            if len(numbers) < needed or not all(math.isfinite(float(number)) for number in numbers[-needed:]):
                return None, "malformed_pdf_content"
            values = [float(number) for number in numbers[-needed:]]
            if operator == "m":
                subpaths.append({"points": [(values[0], values[1])], "closed": False})
                path_points.append((values[0], values[1]))
            elif operator == "re":
                x, y, width, height = values
                points = [(x, y), (x + width, y),
                          (x + width, y + height), (x, y + height), (x, y)]
                subpaths.append({"points": points, "closed": True})
                path_points.extend(points)
            elif not subpaths:
                return None, "malformed_pdf_content"
            elif operator == "l":
                point = (values[0], values[1])
                subpaths[-1]["points"].append(point)
                path_points.append(point)
            elif operator == "c":
                subpaths[-1]["points"].append((values[4], values[5]))
                path_points.append((values[4], values[5]))
            elif operator in {"v", "y"}:
                point = (values[-2], values[-1])
                subpaths[-1]["points"].append(point)
                path_points.append(point)
            path_seen = True
        elif operator == "h":
            if not subpaths or not subpaths[-1]["points"]:
                return None, "malformed_pdf_content"
            points = subpaths[-1]["points"]
            if points[-1] != points[0]:
                points.append(points[0])
            subpaths[-1]["closed"] = True
            path_seen = True
        elif operator in {"S", "s", "F", "f", "f*", "B", "b", "B*", "b*", "sh"}:
            if not path_seen or not subpaths:
                return None, "glyph_geometry_missing"
            stroke = operator in {"S", "s", "B", "b", "B*", "b*"}
            fill = operator in {"F", "f", "f*", "B", "b", "B*", "b*"}
            if operator == "sh" and not (_has_segment() or _has_area()):
                return None, "glyph_geometry_missing"
            if (stroke and not _has_segment()) and (fill and not _has_area()):
                return None, "glyph_geometry_missing"
            if stroke and not _has_segment() and not fill:
                return None, "glyph_geometry_missing"
            if fill and not _has_area() and not stroke:
                return None, "glyph_geometry_missing"
            painted = True
            subpaths = []
            path_seen = False
        elif operator in {"cm", "W", "W*", "n", "q", "Q"}:
            return None, "unsupported_graphics_state"
        elif operator == "Do":
            return None, "unsupported_charproc_state"
        elif operator == "Tr":
            numbers = [item.value for item in operands if item.kind == "number"]
            if not numbers or numbers[-1] not in {0, 1, 2}:
                return None, "unsupported_graphics_state"
        elif operator in {"gs", "BDC", "BMC", "EMC", "BI", "ID", "EI"}:
            return None, "unsupported_graphics_state"
        operands = []
    if array_depth or dict_depth:
        return None, "malformed_pdf_content"
    if not metrics_seen:
        return None, "glyph_geometry_missing"
    if not painted or path_seen or len(set(path_points)) < 2:
        return None, "glyph_geometry_missing"
    def _canonical_token(token: _PdfToken) -> str:
        if token.kind == "number":
            return f"{float(token.value):.17g}"
        if token.kind == "hex":
            return bytes(token.value).hex()
        return str(token.value)

    canonical = b"\x1f".join(
        (token.kind + ":" + _canonical_token(token)).encode("utf-8")
        for token in tokens
    )
    return hashlib.sha256(canonical).hexdigest(), None


def _inspect_type3_font(
    document: Any,
    page: Any,
    xref: int,
    resource_names: set[str],
    shown_chars: list[str],
) -> tuple[str, str]:
    """Inspect a Hangul-used Type3 font; returns (state, closed reason)."""
    required_api = ("xref_get_key", "xref_object")
    if (not all(hasattr(document, name) for name in required_api)
            or not (hasattr(document, "xref_stream")
                    or hasattr(document, "xref_stream_raw"))):
        return "unknown", "type3_font"
    encoding_kind, encoding_value = _pdf_key(document, xref, "Encoding")
    encoding_dict = _resolve_dict(document, encoding_kind, encoding_value)
    differences = _parse_differences(encoding_dict or "")
    cmap_kind, cmap_value = _pdf_key(document, xref, "ToUnicode")
    cmap_xref = _xref_from_value(cmap_kind, cmap_value)
    if cmap_xref is not None and _stream_unbounded(document, cmap_xref):
        return "unknown", "pdf_content_unbounded"
    cmap_data = _stream_bytes(document, cmap_xref) if cmap_xref is not None else None
    cmap = _parse_tounicode(cmap_data) if cmap_data is not None else None
    charprocs_kind, charprocs_value = _pdf_key(document, xref, "CharProcs")
    charprocs_dict = _resolve_dict(document, charprocs_kind, charprocs_value)
    charprocs = _dict_refs(charprocs_dict or "")
    if differences is None or cmap is None or charprocs is None:
        return "unknown", "font_mapping_missing"
    codes, content_reason = _page_type3_codes(page, document, resource_names)
    if content_reason:
        return "unknown", content_reason
    if not codes:
        return "unknown", "font_mapping_missing"
    mapped: list[tuple[str, int, str]] = []
    program_hashes: dict[str, str] = {}
    unicode_codes: dict[str, int] = {}
    hash_unicodes: dict[str, str] = {}
    code_to_unicode: dict[int, str] = {}
    for code in codes:
        unicode_text = cmap.get(bytes([code]))
        if not unicode_text:
            continue
        hangul = _HANGUL_RE.findall(unicode_text)
        if not hangul:
            continue
        if len(hangul) != 1 or code not in differences:
            return "unknown", "font_mapping_missing"
        unicode_char = hangul[0]
        glyph_name = differences[code]
        stream_xref = charprocs.get(glyph_name)
        if stream_xref is None:
            return "unknown", "font_mapping_missing"
        if _stream_unbounded(document, stream_xref):
            return "unknown", "pdf_content_unbounded"
        program = _stream_bytes(document, stream_xref)
        if program is None:
            return "unknown", "font_mapping_missing"
        digest, geometry_reason = _charproc_program(program)
        if geometry_reason:
            state = "failed" if geometry_reason == "glyph_geometry_missing" else "unknown"
            return state, geometry_reason
        assert digest is not None
        previous_code = code_to_unicode.get(code)
        if previous_code is not None and previous_code != unicode_char:
            return "failed", "glyph_identity_collapse"
        code_to_unicode[code] = unicode_char
        previous_hash = program_hashes.get(unicode_char)
        if previous_hash is not None and previous_hash != digest:
            return "failed", "glyph_identity_collapse"
        previous_code = unicode_codes.get(unicode_char)
        if previous_code is not None and previous_code != code:
            return "failed", "glyph_identity_collapse"
        previous_unicode = hash_unicodes.get(digest)
        if previous_unicode is not None and previous_unicode != unicode_char:
            return "failed", "glyph_identity_collapse"
        program_hashes[unicode_char] = digest
        unicode_codes[unicode_char] = code
        hash_unicodes[digest] = unicode_char
        mapped.append((unicode_char, code, digest))
    if not mapped:
        return "unknown", "font_mapping_missing"
    if isinstance(codes, _PageCodes) and codes.uses_geometry:
        geometry_reason = _validate_type3_page_geometry(
            page, resource_names, cmap, shown_chars, codes)
        if geometry_reason:
            return "unknown", geometry_reason
    shown_unique = set(shown_chars)
    mapped_unique = {item[0] for item in mapped}
    # ActualText can claim many distinct syllables while the page content has
    # only one code.  The sequence length check is intentionally conservative.
    if len(shown_unique) > len({item[1] for item in mapped}) \
            or len(shown_chars) > len(codes):
        return "failed", "glyph_identity_collapse"
    if not shown_unique.issubset(mapped_unique):
        return "unknown", "font_mapping_missing"
    # A single CharProc program may not stand in for two distinct Hangul
    # syllables, even when ToUnicode/ActualText makes extraction look correct.
    if len(program_hashes) != len({item[2] for item in mapped}):
        return "failed", "glyph_identity_collapse"
    return "passed", "passed"


def _unknown(
    pdf_path: Path,
    source_count: int,
    reason: str,
    *,
    page_count: int = 0,
    pdf_count: int = 0,
    mapped: int = 0,
    checked: int = 0,
    maximum: int = 0,
    minimum: int = 0,
) -> dict[str, Any]:
    return _new_result(
        pdf_path,
        state="unknown",
        reason_code=reason,
        source_hangul_count=source_count,
        pdf_hangul_count=pdf_count,
        page_count=page_count,
        mapped_font_xrefs=mapped,
        checked_font_xrefs=checked,
        max_unique_hangul_per_xref=maximum,
        min_glyph_capacity=minimum,
    )


def inspect(source_hwpx: str | Path, rendered_pdf: str | Path) -> dict[str, Any]:
    """Inspect one HWPX/PDF pair and return a closed quality result.

    A source with no Hangul is intentionally ``not_applicable``.  Callers
    must still require the broader deterministic visual/layout contract before
    promoting any proof grade; this checker alone never promotes that case.
    """
    source = Path(source_hwpx)
    pdf_path = Path(rendered_pdf)
    source_set, source_error = _source_hangul(source)
    if source_set is None:
        return _unknown(pdf_path, 0, source_error or "source_unreadable")
    source_count = len(source_set)

    try:
        import fitz
    except ImportError:
        return _unknown(pdf_path, source_count, "checker_unavailable")

    try:
        document = fitz.open(pdf_path)
    except Exception:
        return _unknown(pdf_path, source_count, "pdf_unreadable")
    try:
        page_count = int(document.page_count)
        if page_count <= 0:
            return _unknown(pdf_path, source_count, "pdf_no_pages")
        if source_count == 0:
            return _new_result(
                pdf_path,
                state="not_applicable",
                reason_code="source_ascii_only",
                page_count=page_count,
            )

        hangul_by_xref: dict[int, set[str]] = {}
        type3_pages_by_xref: dict[int, dict[int, dict[str, Any]]] = {}
        font_rows_by_xref: dict[int, list[tuple]] = {}
        pdf_hangul: set[str] = set()
        mapped = 0
        for page_index in range(page_count):
            page = document[page_index]
            try:
                raw = page.get_text("rawdict")
            except Exception:
                return _unknown(
                    pdf_path, source_count, "pdf_no_extractable_text",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped,
                )
            try:
                font_rows = list(document.get_page_fonts(page_index, full=True))
            except Exception:
                return _unknown(
                    pdf_path, source_count, "font_mapping_missing",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped,
                )
            for block in raw.get("blocks", []) if isinstance(raw, dict) else []:
                if not isinstance(block, dict) or block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    if not isinstance(line, dict):
                        continue
                    for span in line.get("spans", []):
                        if not isinstance(span, dict):
                            continue
                        # Resolve the ordered semantic claim before updating
                        # aggregate PDF Hangul counts.  Do not merge
                        # contradictory rawdict ``chars`` and ``text`` data.
                        sequence = _span_hangul_sequence(span)
                        if sequence is None:
                            return _unknown(
                                pdf_path, source_count,
                                "semantic_text_ambiguous",
                                page_count=page_count,
                                pdf_count=len(pdf_hangul), mapped=mapped,
                            )
                        if not sequence:
                            continue
                        chars = set(sequence)
                        pdf_hangul.update(chars)
                        xrefs = _font_xrefs_for_name(font_rows, span.get("font"))
                        if len(xrefs) == 0:
                            return _unknown(
                                pdf_path, source_count, "font_mapping_missing",
                                page_count=page_count,
                                pdf_count=len(pdf_hangul), mapped=mapped,
                            )
                        if len(xrefs) > 1:
                            return _unknown(
                                pdf_path, source_count, "ambiguous_font_mapping",
                                page_count=page_count,
                                pdf_count=len(pdf_hangul), mapped=mapped,
                            )
                        xref = next(iter(xrefs))
                        if xref not in hangul_by_xref:
                            mapped += 1
                            hangul_by_xref[xref] = set()
                        hangul_by_xref[xref].update(chars)
                        page_resource_names: set[str] = set()
                        for row in font_rows:
                            if len(row) < 5:
                                continue
                            try:
                                row_xref = int(row[0])
                            except (TypeError, ValueError):
                                continue
                            if row_xref != xref:
                                continue
                            font_rows_by_xref.setdefault(xref, []).append(row)
                            for column in (3, 4):
                                resource_name = str(row[column] or "").lstrip("/")
                                if resource_name:
                                    page_resource_names.add(resource_name)
                        font_type = str(next(
                            (row[2] for row in font_rows
                             if len(row) > 2 and str(row[0]) == str(xref)),
                            "",
                        )).casefold()
                        if "type3" in font_type:
                            page_records = type3_pages_by_xref.setdefault(xref, {})
                            record = page_records.setdefault(
                                page_index,
                                {"page": page, "shown": [], "resource_names": set()},
                            )
                            record["shown"].extend(sequence)
                            record["resource_names"].update(page_resource_names)

        if not pdf_hangul:
            # This is the observed LO tofu/fallback failure: extraction sees no
            # Hangul at all even though the source requires it.
            return _new_result(
                pdf_path,
                state="failed",
                reason_code="missing_hangul_glyphs",
                source_hangul_count=source_count,
                pdf_hangul_count=0,
                page_count=page_count,
                mapped_font_xrefs=0,
            )

        missing_source_text = source_set.difference(pdf_hangul)
        if missing_source_text:
            # A high-capacity font cannot rescue source syllables absent from
            # extracted PDF text.  Keep the missing set private and fail
            # closed before any font-capacity pass can claim success.
            return _new_result(
                pdf_path,
                state="unknown",
                reason_code="source_visibility_ambiguous",
                source_hangul_count=source_count,
                pdf_hangul_count=len(pdf_hangul),
                page_count=page_count,
                mapped_font_xrefs=mapped,
            )

        maximum = max((len(chars) for chars in hangul_by_xref.values()), default=0)
        checked = 0
        capacities: list[int] = []
        for xref, chars in hangul_by_xref.items():
            row_font_type = str(next(
                (row[2] for row in font_rows_by_xref.get(xref, []) if len(row) > 2),
                "",
            )).casefold()
            try:
                name, ext, font_type, buffer = document.extract_font(xref, info_only=0)
            except Exception:
                if "type3" in row_font_type:
                    # Some PyMuPDF builds cannot expose a Type3 buffer.  The
                    # bounded xref parser below can still inspect its program;
                    # do not erase that opportunity behind a buffer error.
                    name, ext, font_type, buffer = "", "n/a", "Type3", b""
                else:
                    return _unknown(
                        pdf_path, source_count, "font_buffer_unavailable",
                        page_count=page_count, pdf_count=len(pdf_hangul),
                        mapped=mapped, checked=checked, maximum=maximum,
                        minimum=min(capacities) if capacities else 0,
                    )
            type_text = str(font_type or "").casefold()
            ext_text = str(ext or "").casefold()
            if "type3" in type_text:
                pages = type3_pages_by_xref.get(xref)
                if not pages:
                    return _unknown(
                        pdf_path, source_count, "type3_font",
                        page_count=page_count, pdf_count=len(pdf_hangul),
                        mapped=mapped, checked=checked, maximum=maximum,
                        minimum=min(capacities) if capacities else 0,
                    )
                for record in pages.values():
                    page = record["page"]
                    shown_sequence = record["shown"]
                    resource_names = record["resource_names"]
                    state, reason = _inspect_type3_font(
                        document, page, xref, resource_names, shown_sequence)
                    if state != "passed":
                        if state == "failed":
                            return _new_result(
                                pdf_path,
                                state="failed",
                                reason_code=reason,
                                source_hangul_count=source_count,
                                pdf_hangul_count=len(pdf_hangul),
                                page_count=page_count,
                                mapped_font_xrefs=mapped,
                                checked_font_xrefs=checked,
                                max_unique_hangul_per_xref=maximum,
                                min_glyph_capacity=min(capacities) if capacities else 0,
                            )
                        return _unknown(
                            pdf_path, source_count, reason,
                            page_count=page_count, pdf_count=len(pdf_hangul),
                            mapped=mapped, checked=checked, maximum=maximum,
                            minimum=min(capacities) if capacities else 0,
                        )
                checked += 1
                continue
            if ext_text in {"", "n/a", "none"} or ext_text not in {"ttf", "otf"} \
                    or not isinstance(buffer, (bytes, bytearray)) \
                    or not buffer:
                return _unknown(
                    pdf_path, source_count,
                    "nonembedded_font" if ext_text in {"", "n/a", "none"}
                    else "font_buffer_unavailable",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped, checked=checked, maximum=maximum,
                    minimum=min(capacities) if capacities else 0,
                )
            try:
                font = fitz.Font(fontbuffer=bytes(buffer))
                capacity = int(font.glyph_count)
            except Exception:
                return _unknown(
                    pdf_path, source_count, "font_buffer_unavailable",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped, checked=checked, maximum=maximum,
                    minimum=min(capacities) if capacities else 0,
                )
            capacities.append(capacity)
            checked += 1
            if len(chars) > capacity:
                return _new_result(
                    pdf_path,
                    state="failed",
                    reason_code="missing_hangul_glyphs",
                    source_hangul_count=source_count,
                    pdf_hangul_count=len(pdf_hangul),
                    page_count=page_count,
                    mapped_font_xrefs=mapped,
                    checked_font_xrefs=checked,
                    max_unique_hangul_per_xref=maximum,
                    min_glyph_capacity=min(capacities),
                )
        return _new_result(
            pdf_path,
            state="passed",
            reason_code="passed",
            source_hangul_count=source_count,
            pdf_hangul_count=len(pdf_hangul),
            page_count=page_count,
            mapped_font_xrefs=mapped,
            checked_font_xrefs=checked,
            max_unique_hangul_per_xref=maximum,
            min_glyph_capacity=min(capacities) if capacities else 0,
        )
    except Exception:
        # Any parser/font API drift is an unknown quality result, never a
        # renderer failure or an optimistic pass.
        return _unknown(pdf_path, source_count, "checker_unavailable")
    finally:
        try:
            document.close()
        except Exception:
            pass


def apply_layout_gate(
    quality: dict[str, Any],
    *,
    converged: bool,
    hard_checks: bool,
    style_clean: bool,
    advisory_hold: bool = False,
) -> dict[str, Any]:
    """Apply the existing deterministic layout contract to a quality result."""
    result = dict(quality)
    if result.get("state") != "passed":
        return result
    if not converged or not hard_checks or not style_clean:
        result["state"] = "failed"
        result["reason_code"] = "layout_hard_failed"
    elif advisory_hold:
        result["state"] = "failed"
        result["reason_code"] = "visual_quality_gate_pending"
    return result


def is_passed(quality: Any) -> bool:
    return isinstance(quality, dict) and quality.get("schema") == QUALITY_SCHEMA \
        and quality.get("state") == "passed" and quality.get("reason_code") == "passed"


__all__ = [
    "CHECKER_ID", "QUALITY_ALLOWED_KEYS", "QUALITY_REASON_CODES",
    "QUALITY_REQUIRED_KEYS", "QUALITY_SCHEMA", "QUALITY_STATES",
    "QUALITY_VERSION", "apply_layout_gate", "inspect", "is_passed",
]
