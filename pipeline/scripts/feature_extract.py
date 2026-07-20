#!/usr/bin/env python3
"""Deterministic, fail-closed feature tagging for HWPX documents.

The public contract is :func:`extract_feature_counts`: a lexicographically
sorted ``{tag: count}`` mapping.  Counts are positive integers.  Controls below
``<...:ctrl>`` that are not in the known control vocabulary are preserved as
``unknown:<local-name>`` tags so certification can never silently cover them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


SCHEMA_VERSION = 1
HWP_UNITS_PER_MM = 7200.0 / 25.4

_KNOWN_CONTROL_CHILDREN = frozenset({
    "autoNum", "bookmark", "clickhere", "colPr", "compose", "ctrlData",
    "dutmal", "endNote", "fieldBegin", "fieldEnd", "footer", "footNote",
    "fwSpace", "header", "hiddenComment", "hyperlink", "indexmark",
    "lineBreak", "memo", "newNum", "nbSpace", "pageHiding", "pageNum",
    "pageNumPos", "revision", "tab", "tbl", "equation", "pic", "image",
    "img", "arc", "connectLine", "container", "curve", "ellipse", "line",
    "ole", "polygon", "rect", "shape", "textart", "video",
})
_IMAGE_TAGS = frozenset({"pic", "image", "img"})
_SHAPE_TAGS = frozenset({
    "arc", "connectLine", "container", "curve", "ellipse", "ole", "polygon",
    "rect", "shape", "textart", "video",
})
_LINE_TAGS = frozenset({"line"})
_FLOATING_TAGS = _IMAGE_TAGS | _SHAPE_TAGS | _LINE_TAGS | frozenset({
    "equation", "tbl",
})


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive(counter: Counter[str], tag: str, value: int) -> None:
    if value > 0:
        counter[tag] += int(value)


def _table_depth(element: ElementTree.Element, depth: int = 0) -> int:
    local = _local_name(element.tag) if isinstance(element.tag, str) else ""
    current = depth + 1 if local == "tbl" else depth
    maximum = current
    for child in list(element):
        maximum = max(maximum, _table_depth(child, current))
    return maximum


def _page_size_class(width: int, height: int) -> str:
    short, long = sorted((width, height))
    known = {
        "a4": (59528, 84189),
        "letter": (61200, 79200),
        "legal": (61200, 100800),
        "b5": (51591, 72850),
    }
    for label, (expected_short, expected_long) in known.items():
        if (math.isclose(short, expected_short, rel_tol=0.012)
                and math.isclose(long, expected_long, rel_tol=0.012)):
            return label
    return "custom"


def _page_margin_class(element: ElementTree.Element) -> str:
    values = []
    for key in ("left", "right", "top", "bottom"):
        try:
            values.append(float(element.attrib[key]) / HWP_UNITS_PER_MM)
        except (KeyError, TypeError, ValueError):
            return "custom"
    mean = sum(values) / len(values)
    if mean < 10.0:
        return "narrow"
    if mean <= 25.4:
        return "normal"
    if mean >= 35.0:
        return "wide"
    return "custom"


def _has_floating_position(element: ElementTree.Element) -> bool:
    for child in element.iter():
        if (_local_name(child.tag) == "pos"
                and str(child.attrib.get("treatAsChar", "1")).strip() in {"0", "false", "False"}):
            return True
    return False


def _read_xml_parts(path: Path) -> list[tuple[str, ElementTree.Element]]:
    if path.suffix.lower() != ".hwpx":
        raise ValueError("feature extraction supports .hwpx documents only")
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"HWPX ZIP CRC failure: {bad}")
            names = sorted(
                name for name in archive.namelist()
                if name.lower().endswith(".xml")
            )
            if not names:
                raise ValueError("HWPX ZIP contains no XML parts")
            return [
                (name.replace("\\", "/"), ElementTree.fromstring(archive.read(name)))
                for name in names
            ]
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"unreadable HWPX: {exc}") from exc


def extract_feature_counts(document: str | Path) -> dict[str, int]:
    """Return the canonical sorted feature-count mapping for ``document``."""
    path = Path(document)
    parts = _read_xml_parts(path)
    counts: Counter[str] = Counter()
    section_roots = [
        root for name, root in parts
        if name.lower().startswith("contents/section") and name.lower().endswith(".xml")
    ]
    _positive(counts, "sections", len(section_roots))

    font_faces: set[str] = set()
    font_refs: set[str] = set()
    explicit_hyperlinks = 0
    hyperlink_fields = 0
    maximum_table_depth = 0

    for _, root in parts:
        maximum_table_depth = max(maximum_table_depth, _table_depth(root))
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            local = _local_name(element.tag)

            if local == "colPr":
                try:
                    columns = int(element.attrib.get("colCount", "1"))
                except (TypeError, ValueError):
                    columns = 1
                _positive(counts, "columns", max(1, columns))
            elif local == "tbl":
                counts["tables"] += 1
            elif local == "equation":
                counts["equations"] += 1
            elif local == "header":
                counts["headers"] += 1
            elif local == "footer":
                counts["footers"] += 1
            elif local == "footNote":
                counts["footnotes"] += 1
            elif local == "endNote":
                counts["endnotes"] += 1
            elif local == "fieldBegin":
                counts["fields"] += 1
                if str(element.attrib.get("type", "")).upper() == "HYPERLINK":
                    hyperlink_fields += 1
            elif local == "hyperlink":
                explicit_hyperlinks += 1

            if local in _SHAPE_TAGS:
                counts["shapes"] += 1
            if local in _LINE_TAGS:
                counts["lines"] += 1
            if local in _FLOATING_TAGS and _has_floating_position(element):
                counts["floating-objects"] += 1

            if local == "font":
                face = str(element.attrib.get("face", "")).strip()
                if face:
                    font_faces.add(face)
            elif local == "fontRef":
                for language, font_id in sorted(element.attrib.items()):
                    font_refs.add(f"{_local_name(language)}:{font_id}")

            if local == "pagePr":
                try:
                    width = int(element.attrib["width"])
                    height = int(element.attrib["height"])
                except (KeyError, TypeError, ValueError):
                    counts["page-size:custom"] += 1
                else:
                    counts[f"page-size:{_page_size_class(width, height)}"] += 1
                margin = next(
                    (child for child in list(element)
                     if isinstance(child.tag, str) and _local_name(child.tag) == "margin"),
                    None,
                )
                counts[f"page-margins:{_page_margin_class(margin) if margin is not None else 'custom'}"] += 1

            if local == "ctrl":
                for child in list(element):
                    if not isinstance(child.tag, str):
                        continue
                    child_local = _local_name(child.tag)
                    if child_local not in _KNOWN_CONTROL_CHILDREN:
                        counts[f"unknown:{child_local}"] += 1

    if maximum_table_depth:
        counts["nested-table-depth"] = maximum_table_depth
    image_count = sum(
        1 for _, root in parts for element in root.iter()
        if isinstance(element.tag, str) and _local_name(element.tag) == "pic"
    )
    if image_count == 0:
        image_count = sum(
            1 for _, root in parts for element in root.iter()
            if isinstance(element.tag, str) and _local_name(element.tag) in {"image", "img"}
        )
    _positive(counts, "images", image_count)
    _positive(counts, "hyperlinks", explicit_hyperlinks or hyperlink_fields)
    _positive(counts, "charpr-font-count", len(font_faces) or len(font_refs))
    return dict(sorted((tag, value) for tag, value in counts.items() if value > 0))


def extract_features(document: str | Path) -> dict:
    path = Path(document)
    return {
        "schema_version": SCHEMA_VERSION,
        "document": str(path.resolve()),
        "document_sha256": _sha256(path),
        "features": extract_feature_counts(path),
    }


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="extract deterministic HWPX feature tags")
    parser.add_argument("document")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        payload = extract_features(args.document)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "reason_code": "document_unreadable", "error": str(exc)}))
        return 3
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
