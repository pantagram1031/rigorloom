#!/usr/bin/env python3
"""Measure the OWPML surface a corpus of HWPX files actually uses.

E3.1 needs a completeness target that is measured rather than guessed: the
writer is complete when it emits every element and attribute the reader can
meet.  This walks every zip member of every given HWPX and counts what is
there — element by element, attribute by attribute, with the forms each one
appears in.

Values are deliberately NOT recorded.  Corpus documents carry author names,
file paths and titles in ``Contents/content.hpf`` metadata; an inventory that
sampled attribute or text values would carry them into the repository.  Names
and counts answer the completeness question on their own.

    python hwpx_inventory.py tests/corpus/forms --out engine/references/owpml-inventory.json
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402
from hwpx_write import (XML_MEMBER_SUFFIXES, HwpxPackage,  # noqa: E402
                        iter_with_scope, parse_xml_part)

SCHEMA_VERSION = 2


def _sorted(values):
    return sorted(values)


def collect(paths):
    """Element/attribute inventory over the given HWPX files."""
    elements = defaultdict(lambda: {
        "count": 0, "forms": set(), "parts": set(), "attributes": defaultdict(
            lambda: {"count": 0, "forms": set()}),
        "with_text": 0, "with_children": 0, "empty": 0,
        "explicit_end": 0, "namespace": None, "local": None,
    })
    members = defaultdict(lambda: {"forms": set(), "compress": set(),
                                   "xml": False, "bytes_total": 0})
    roots = defaultdict(lambda: {"forms": set(), "parts": set()})
    forms = []

    for path in paths:
        slug = Path(path).stem
        forms.append(slug)
        package = HwpxPackage.read(path)
        for part in package.parts:
            entry = members[part.name]
            entry["forms"].add(slug)
            entry["compress"].add(
                "stored" if part.compress_type == zipfile.ZIP_STORED else "deflated")
            entry["xml"] = part.is_xml
            entry["bytes_total"] += len(part.data)
            if not part.is_xml:
                continue
            parsed = parse_xml_part(part.data)
            roots[parsed.root.qname]["forms"].add(slug)
            roots[parsed.root.qname]["parts"].add(part.name)
            for node, scope in iter_with_scope(parsed):
                key = node.qname
                record = elements[key]
                record["namespace"] = scope.get(node.prefix)
                record["local"] = node.local
                record["count"] += 1
                record["forms"].add(slug)
                record["parts"].add(part.name)
                if node.text:
                    record["with_text"] += 1
                if node.children:
                    record["with_children"] += 1
                if not node.children and not node.text:
                    record["empty"] += 1
                    if node.explicit_end:
                        record["explicit_end"] += 1
                for name, _value in node.attrs:
                    attribute = record["attributes"][name]
                    attribute["count"] += 1
                    attribute["forms"].add(slug)

    # Forms are referenced by index into the top-level ``forms`` array, and an
    # attribute records how MANY forms carry it rather than which: naming every
    # form on all 558 element/attribute pairs made the file 6x larger without
    # answering a question the element-level list does not already answer.
    form_index = {slug: index for index, slug in enumerate(_sorted(forms))}

    inventory = {}
    for key, record in elements.items():
        inventory[key] = {
            "namespace": record["namespace"],
            "local": record["local"],
            "count": record["count"],
            "forms": sorted(form_index[slug] for slug in record["forms"]),
            "parts": _sorted(record["parts"]),
            "with_text": record["with_text"],
            "with_children": record["with_children"],
            "empty": record["empty"],
            "explicit_end_form": record["explicit_end"],
            "attributes": {
                name: {"count": data["count"], "forms": len(data["forms"])}
                for name, data in sorted(record["attributes"].items())
            },
        }

    distinct_attributes = set()
    for record in inventory.values():
        for name in record["attributes"]:
            distinct_attributes.add((record["local"], name))

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "engine/scripts/hwpx_inventory.py",
        "note": ("Element and attribute NAMES with counts only; no attribute "
                 "or text values are recorded (corpus metadata carries author "
                 "names and paths)."),
        "forms": _sorted(forms),
        "form_count": len(forms),
        "summary": {
            "distinct_elements": len(inventory),
            "element_occurrences": sum(r["count"] for r in inventory.values()),
            "distinct_element_attribute_pairs": len(distinct_attributes),
            "distinct_attribute_names": len(
                {name for _local, name in distinct_attributes}),
            "xml_members": sum(1 for m in members.values() if m["xml"]),
            "distinct_members": len(members),
        },
        "roots": {name: {"forms": _sorted(data["forms"]),
                         "parts": _sorted(data["parts"])}
                  for name, data in sorted(roots.items())},
        "members": {name: {"forms": _sorted(data["forms"]),
                           "compress": _sorted(data["compress"]),
                           "xml": data["xml"],
                           "bytes_total": data["bytes_total"]}
                    for name, data in sorted(members.items())},
        "elements": {name: inventory[name] for name in sorted(inventory)},
    }


def discover(target):
    target = Path(target)
    if target.is_file():
        return [target]
    return sorted(target.rglob("*.hwpx"))


def main(argv=None):
    utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="hwpx_inventory.py",
        description="Inventory the OWPML surface used by a corpus of HWPX files.")
    parser.add_argument("target", nargs="+",
                        help="HWPX file(s) or a directory to walk")
    parser.add_argument("--out", help="write JSON here (default: stdout)")
    args = parser.parse_args(argv)

    paths = []
    for target in args.target:
        paths.extend(discover(target))
    if not paths:
        sys.stderr.write("no .hwpx found under %s\n" % ", ".join(args.target))
        return 2

    payload = collect(paths)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps(
            {"ok": True, "out": args.out, **payload["summary"]},
            ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# XML member suffixes are re-exported for callers that want the same rule.
__all__ = ["collect", "discover", "main", "XML_MEMBER_SUFFIXES"]
