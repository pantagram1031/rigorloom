#!/usr/bin/env python3
"""Mine a text-free form skeleton and varying fill-slot inventory from HWPX."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from checker_base import EXIT_PASS, cli_main, usage_error, verdict_skeleton
from content_extract import local, section_names, sha_file
from submission_preflight import (
    _hwpx_form_structure_records,
    _hwpx_form_structure_sha256,
)


def normalized_text(node: ET.Element, *, skip_cells: bool = False) -> str:
    parents = {child: parent for parent in node.iter() for child in parent}
    chunks = []
    for item in node.iter():
        if not isinstance(item.tag, str) or local(item.tag) != "t":
            continue
        parent, in_cell = parents.get(item), False
        while parent is not None:
            in_cell = in_cell or local(parent.tag) == "tc"
            parent = parents.get(parent)
        if not (skip_cells and in_cell):
            chunks.append("".join(item.itertext()))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", "".join(chunks))).strip()


def text_units(path: Path) -> dict[tuple[str, str, str], str]:
    units = {}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        for part in section_names(archive.namelist()):
            root = ET.fromstring(archive.read(part))

            def visit(node: ET.Element, xml_path: str, in_cell: bool = False) -> None:
                children = [child for child in list(node)
                            if isinstance(child.tag, str)]
                seen: dict[str, int] = {}
                for child in children:
                    name = local(child.tag)
                    seen[name] = seen.get(name, 0) + 1
                    child_path = f"{xml_path}/{name}[{seen[name]}]"
                    if name == "tc":
                        units[(part, child_path, "cell")] = normalized_text(child)
                        visit(child, child_path, True)
                    elif name == "p" and not in_cell:
                        units[(part, child_path, "paragraph")] = normalized_text(
                            child, skip_cells=True)
                        visit(child, child_path, in_cell)
                    else:
                        visit(child, child_path, in_cell)

            visit(root, f"/{local(root.tag)}[1]")
    return units


def digest_text(value: str | None) -> str | None:
    return (hashlib.sha256(value.encode("utf-8")).hexdigest()
            if value is not None else None)


def slot_inventory(paths: list[Path]) -> dict:
    by_source = [text_units(path) for path in paths]
    keys = sorted(set().union(*(set(item) for item in by_source)))
    slots, chrome = [], []
    for part, xml_path, kind in keys:
        values = [item.get((part, xml_path, kind)) for item in by_source]
        record = {
            "part": part,
            "path": xml_path,
            "kind": kind,
            "value_sha256_by_source": {
                str(path.resolve()): digest_text(value)
                for path, value in zip(paths, values)
            },
        }
        if len(set(values)) == 1:
            record["constant_text"] = values[0]
            chrome.append(record)
        else:
            record["lengths_by_source"] = {
                str(path.resolve()): len(value) if value is not None else None
                for path, value in zip(paths, values)
            }
            slots.append(record)
    return {"slots": slots, "chrome": chrome,
            "counts": {"slots": len(slots), "chrome": len(chrome)}}


def skeleton_divergences(paths: list[Path], records_by_source: list[list[dict]]) -> list[dict]:
    baseline = records_by_source[0]
    differences = []
    for path, records in zip(paths[1:], records_by_source[1:]):
        for index in range(max(len(baseline), len(records))):
            expected = baseline[index] if index < len(baseline) else None
            actual = records[index] if index < len(records) else None
            if expected == actual:
                continue
            marker = expected or actual or {}
            element = marker.get("element") or {}
            differences.append({
                "instance": str(path.resolve()),
                "record_index": index,
                "part": marker.get("part"),
                "occurrence": marker.get("occurrence"),
                "tag": element.get("tag"),
                "change": ("added" if expected is None else
                           "missing" if actual is None else "changed"),
            })
            if len(differences) >= 50:
                return differences
    return differences


def extract_forms(inputs: list[str | Path], out_dir: str | Path) -> tuple[dict, int]:
    paths, out_dir = [Path(item) for item in inputs], Path(out_dir)
    if not paths or any(path.suffix.lower() != ".hwpx" or not path.is_file()
                        for path in paths):
        return usage_error(out_dir, "form_extract",
                           "provide one or more existing .hwpx instances")
    try:
        hashes = [_hwpx_form_structure_sha256(path) for path in paths]
        records_by_source = [_hwpx_form_structure_records(path) for path in paths]
        skeleton = records_by_source[0]
        stable = len(set(hashes)) == 1
        inventory = slot_inventory(paths) if stable else None
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        return usage_error(out_dir, "form_extract", f"invalid HWPX instance: {exc}")
    divergences = [] if stable else skeleton_divergences(paths, records_by_source)
    inventory_reason = (
        None if stable
        else "suppressed because skeleton divergence makes slot alignment unreliable"
    )
    sources = [{"path": str(path.resolve()), "sha256": sha_file(path),
                "skeleton_sha256": digest}
               for path, digest in zip(paths, hashes)]
    record = {
        "schema": "rigorloom/form-template-v1",
        "skeleton_stable": stable,
        "skeleton_sha256": hashes[0],
        "sources": sources,
        "skeleton": skeleton,
        "skeleton_divergences": divergences,
        "fill_slot_inventory": inventory,
        "fill_slot_inventory_reason": inventory_reason,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "form_template.json"
    summary_path = out_dir / "form_template.summary.md"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    inventory_summary = (
        f"- Fill slots: {inventory['counts']['slots']}\n"
        f"- Constant chrome units: {inventory['counts']['chrome']}\n\n"
        "Varying units are content slots; constant units are form chrome. "
        "Slot values are represented by hashes rather than copied content.\n"
        if inventory is not None
        else "- Fill-slot inventory: suppressed (skeleton alignment unreliable)\n"
    )
    summary_path.write_text(
        "# Form template extraction\n\n"
        f"- Instances: {len(paths)}\n"
        f"- Skeleton stable: {'yes' if stable else 'no'}\n"
        + inventory_summary,
        encoding="utf-8")
    warn = [] if stable else [{
        "code": "form_instances_diverge",
        "msg": "form skeleton hashes differ across supplied instances",
        "at": {"sources": [
            {"path": item["path"], "skeleton_sha256": item["skeleton_sha256"]}
            for item in sources], "differences": divergences},
    }]
    verdict = verdict_skeleton(
        str(out_dir.resolve()), "form_extract", warn=warn,
        extra={"form_template": str(json_path.resolve()),
               "summary": str(summary_path.resolve()),
               "skeleton_stable": stable,
               "slot_counts": inventory["counts"] if inventory is not None else None})
    return verdict, EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="extract a shared form skeleton and fill-slot inventory")
    parser.add_argument("inputs", nargs="+", help="HWPX instances sharing a form")
    parser.add_argument("--out-dir", required=True)
    return parser


def main(argv=None) -> int:
    return cli_main(
        build_parser(), lambda args: extract_forms(args.inputs, args.out_dir),
        argv, create_out_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
