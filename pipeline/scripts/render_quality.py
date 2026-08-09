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
import re
import zipfile
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
    "font_capacity_insufficient",
    "ambiguous_font_mapping",
    "font_mapping_missing",
    "font_buffer_unavailable",
    "nonembedded_font",
    "type3_font",
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
    found: set[str] = set()
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
                found.update(_HANGUL_RE.findall(value))
    if found:
        return found
    text = span.get("text")
    return set(_HANGUL_RE.findall(text)) if isinstance(text, str) else set()


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
                        chars = _span_hangul(span)
                        if not chars:
                            continue
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
            try:
                name, ext, font_type, buffer = document.extract_font(xref, info_only=0)
            except Exception:
                return _unknown(
                    pdf_path, source_count, "font_buffer_unavailable",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped, checked=checked, maximum=maximum,
                    minimum=min(capacities) if capacities else 0,
                )
            type_text = str(font_type or "").casefold()
            ext_text = str(ext or "").casefold()
            if "type3" in type_text:
                return _unknown(
                    pdf_path, source_count, "type3_font",
                    page_count=page_count, pdf_count=len(pdf_hangul),
                    mapped=mapped, checked=checked, maximum=maximum,
                    minimum=min(capacities) if capacities else 0,
                )
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
