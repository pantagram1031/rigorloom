#!/usr/bin/env python3
"""COM-free deterministic extraction of content and media from HWPX.

Equation parity depends on symmetric source and Markdown fingerprints. Real
HwpEqn scripts commonly contain literal square brackets; the Markdown tag
parser is therefore quote-aware so a closing bracket inside the hwpeqn
attribute is content, not the end of the EQ tag. This closes the W5 21-to-18
and 39-to-38 equation undercounts without excluding any HWPX container type.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from checker_base import EXIT_HARD, EXIT_PASS, cli_main, usage_error, verdict_skeleton

CONTENT_NAME = "content.md"
MANIFEST_NAME = "extraction_manifest.json"
COUNT_NAMES = {"p": "paragraphs", "tbl": "tables", "pic": "pictures",
               "equation": "equations"}
CAPTIONS = {
    "table": re.compile(r"^\s*(?:\[?\s*)?(?:표|table)\s*\d+", re.I),
    "picture": re.compile(r"^\s*(?:\[?\s*)?(?:그림|figure|fig\.)\s*\d+", re.I),
}
HEADING = re.compile(
    r"^\s*(?:(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d+)\s*[.、)]\s*.+|"
    r"(?:서론|본론|결론|초록|요약|참고문헌|introduction|methods?|results?|"
    r"discussion|conclusion|references))\s*$", re.I)
ATTR = re.compile(r'\b([A-Za-z_][\w-]*)="([^"]*)"')
EQ_TAG = re.compile(r'\[\[EQ\b((?:[^\]"]|"[^"]*")*)\]\]')
PARAGRAPH_MARKER = re.compile(
    r"^<!-- HWPX-SOURCE-PARAGRAPHS: ([1-9]\d*) -->$")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attr(node: ET.Element, wanted: str) -> str | None:
    return next((v for k, v in node.attrib.items() if local(k) == wanted), None)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_hash(chunks: list[str]) -> str:
    value = unicodedata.normalize("NFC", "".join(chunks))
    return sha_bytes(re.sub(r"\s+", "", value).encode("utf-8"))


def _brace_equation_scripts(script: str) -> str:
    """Canonicalize bare HwpEqn ^x/_x atoms like hwp-master's eqn fill path."""
    out: list[str] = []
    index, size = 0, len(script)
    while index < size:
        token = script[index]
        out.append(token)
        if token in "^_":
            atom_index = index + 1
            while atom_index < size and script[atom_index] == " ":
                atom_index += 1
            if atom_index >= size or script[atom_index] == "{":
                index += 1
                continue
            if script[atom_index] == chr(92):
                match = re.match(r"\\([a-zA-Z]+\*?|.)", script[atom_index:])
                atom = match.group(0) if match else chr(92)
                out.append("{" + atom + "}")
                index = atom_index + len(atom)
                continue
            out.append("{" + script[atom_index] + "}")
            index = atom_index + 1
            continue
        index += 1
    return "".join(out)


def normalize_equation_script(script: str) -> str:
    """Normalize HwpEqn for parity without treating formatting spaces as drift."""
    value = unicodedata.normalize("NFC", script)
    value = _brace_equation_scripts(value)
    return re.sub(r"\s+", "", value)


def equation_script(node: ET.Element) -> str:
    return next((
        "".join(item.itertext())
        for item in node.iter()
        if isinstance(item.tag, str) and local(item.tag) == "script"
    ), "")


def section_names(names) -> list[str]:
    selected = [n for n in names if fnmatch.fnmatchcase(
        n.replace("\\", "/"), "Contents/section*.xml")]
    return sorted(selected, key=lambda n: (
        int(re.search(r"section(\d+)\.xml$", n).group(1))
        if re.search(r"section(\d+)\.xml$", n) else 10**9, n))


def semantic_fingerprint(path: str | Path) -> dict:
    """Return the P0 NFC body-text hash and structural object counts."""
    chunks: list[str] = []
    equation_scripts: list[str] = []
    counts = {value: 0 for value in COUNT_NAMES.values()}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        sections = section_names(archive.namelist())
        if not sections:
            raise ValueError("HWPX contains no Contents/section*.xml")
        for name in sections:
            for node in ET.fromstring(archive.read(name)).iter():
                if not isinstance(node.tag, str):
                    continue
                name_ = local(node.tag)
                if name_ == "t":
                    chunks.extend(node.itertext())
                if name_ in COUNT_NAMES:
                    counts[COUNT_NAMES[name_]] += 1
                if name_ == "equation":
                    equation_scripts.append(normalize_equation_script(
                        equation_script(node)))
    return {
        "normalized_text_sha256": text_hash(chunks),
        "counts": counts,
        "equation_scripts": equation_scripts,
    }


def content_markdown_fingerprint(markdown: str) -> dict:
    """Fingerprint visible extracted content for conversion parity."""
    chunks: list[str] = []
    equation_scripts: list[str] = []
    counts = {value: 0 for value in COUNT_NAMES.values()}
    lines, index = markdown.splitlines(), 0
    while index < len(lines):
        line = lines[index].strip()
        marker = PARAGRAPH_MARKER.match(line)
        if marker:
            counts["paragraphs"] += int(marker.group(1))
        elif line.startswith("## SECTION:"):
            anchor = line.split(":", 1)[1].strip()
            if not anchor.startswith("EXTRACTED CONTENT "):
                chunks.append(anchor)
        elif line.startswith("[[TABLE"):
            counts["tables"] += 1
            attrs = dict((k, html.unescape(v)) for k, v in ATTR.findall(line))
            index += 1
            while index < len(lines) and lines[index].strip() != "[[/TABLE]]":
                row = lines[index].strip()
                if row.startswith("|"):
                    chunks.extend(c.strip().replace(r"\|", "|")
                                  for c in row.strip("|").split("|"))
                index += 1
            if attrs.get("caption"):
                chunks.append(attrs["caption"])
        elif line.startswith("[[FIG"):
            counts["pictures"] += 1
            caption = dict((k, html.unescape(v)) for k, v in ATTR.findall(line)).get(
                "caption")
            if caption:
                chunks.append(caption)
        else:
            equations = EQ_TAG.findall(line)
            counts["equations"] += len(equations)
            for equation in equations:
                attrs = dict(
                    (key, html.unescape(value))
                    for key, value in ATTR.findall(equation)
                )
                equation_scripts.append(normalize_equation_script(
                    attrs.get("hwpeqn") or attrs.get("latex") or ""))
            visible = EQ_TAG.sub("", line)
            if visible and not visible.startswith(("[[", "<!--", "---")):
                chunks.append(visible)
        index += 1
    return {
        "normalized_text_sha256": text_hash(chunks),
        "counts": counts,
        "equation_scripts": equation_scripts,
    }


def package_binary_map(members: dict[str, bytes]) -> dict[str, str]:
    names = {name.replace("\\", "/"): name for name in members}
    result: dict[str, str] = {}
    for name, data in members.items():
        if not name.lower().endswith((".xml", ".hpf")):
            continue
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        for node in root.iter():
            item_id, href = attr(node, "id"), attr(node, "href")
            href = (href or "").lstrip("./").replace("\\", "/")
            if item_id and href in names:
                result.setdefault(item_id, names[href])
    for name in sorted(members):
        normalized = name.replace("\\", "/")
        if normalized.startswith("BinData/"):
            result.setdefault(Path(normalized).stem, name)
    return result


def text_outside_structures(node: ET.Element) -> str:
    """Return text owned by this container, excluding nested structural objects."""
    chunks: list[str] = []

    def walk(item: ET.Element, *, root: bool = False) -> None:
        name = local(item.tag) if isinstance(item.tag, str) else ""
        if not root and name in {"tbl", "pic", "equation"}:
            return
        if name == "t":
            chunks.extend(item.itertext())
            return
        for child in list(item):
            walk(child)

    walk(node, root=True)
    return "".join(chunks)


def equation_tag(node: ET.Element, display: bool) -> str:
    script = equation_script(node)
    script = script.replace("&", "&amp;").replace('"', "&quot;")
    return f'[[EQ{" display" if display else ""} hwpeqn="{script}"]]'


def owned_paragraph_count(node: ET.Element) -> int:
    """Count paragraphs owned by a table while leaving nested tables to themselves."""
    count = 0

    def walk(item: ET.Element, *, root: bool = False) -> None:
        nonlocal count
        name = local(item.tag) if isinstance(item.tag, str) else ""
        if not root and name == "tbl":
            return
        if name == "p":
            count += 1
        for child in list(item):
            walk(child)

    walk(node, root=True)
    return count


def picture_block(node: ET.Element, binaries: dict[str, str],
                  members: dict[str, bytes], pictures: list[dict]) -> dict:
    ref = next((attr(item, "binaryItemIDRef") for item in node.iter()
                if attr(item, "binaryItemIDRef")), None)
    member = binaries.get(ref or "")
    number = len(pictures) + 1
    suffix = Path(member).suffix.lower() if member else ".bin"
    record = {
        "index": number,
        "binary_ref": ref,
        "source_member": member,
        "file": f"picture-{number:03d}{suffix or '.bin'}",
        "sha256": sha_bytes(members[member]) if member else None,
        "bytes": len(members[member]) if member else None,
        "data": members.get(member) if member else None,
    }
    pictures.append(record)
    return {
        "kind": "picture",
        "picture": record,
        "caption": "",
        "source_paragraphs": 0,
    }


def table_blocks(node: ET.Element, binaries: dict[str, str],
                 members: dict[str, bytes], pictures: list[dict]) -> list[dict]:
    """Extract one table from direct rows/cells and flatten nested objects after it."""
    rows: list[list[str]] = []
    cells_in_order: list[ET.Element] = []
    direct_rows = [
        child for child in list(node)
        if isinstance(child.tag, str) and local(child.tag) == "tr"
    ]
    for row in direct_rows:
        cells = [
            child for child in list(row)
            if isinstance(child.tag, str) and local(child.tag) == "tc"
        ]
        cells_in_order.extend(cells)
        rows.append([
            re.sub(r"\s+", " ", text_outside_structures(cell)).strip().replace(
                "|", r"\|")
            for cell in cells
        ])
    outer = {
        "kind": "table",
        "rows": rows,
        "caption": "",
        "source_paragraphs": owned_paragraph_count(node),
    }
    companions: list[dict] = []
    for cell in cells_in_order:
        companions.extend(container_structure_blocks(
            cell, binaries, members, pictures))
    return [outer, *companions]


def container_structure_blocks(
    node: ET.Element,
    binaries: dict[str, str],
    members: dict[str, bytes],
    pictures: list[dict],
) -> list[dict]:
    """Recursively extract structural controls from any visited container."""
    blocks: list[dict] = []

    def walk(item: ET.Element, *, equation_display: bool = False) -> None:
        name = local(item.tag) if isinstance(item.tag, str) else ""
        if name == "p":
            equation_display = not text_outside_structures(item).strip()
        if name == "tbl":
            blocks.extend(table_blocks(item, binaries, members, pictures))
            return
        if name == "pic":
            blocks.append(picture_block(item, binaries, members, pictures))
            return
        if name == "equation":
            blocks.append({
                "kind": "equation",
                "tag": equation_tag(item, equation_display),
                "source_paragraphs": 0,
            })
            return
        for child in list(item):
            walk(child, equation_display=equation_display)

    for child in list(node):
        walk(child)
    return blocks


def paragraph_blocks(node: ET.Element, binaries: dict[str, str],
                     members: dict[str, bytes], pictures: list[dict]) -> list[dict]:
    tokens: list[str | dict] = []

    def walk(item: ET.Element) -> None:
        name = local(item.tag) if isinstance(item.tag, str) else ""
        if name == "t":
            tokens.append("".join(item.itertext()))
        elif name == "equation":
            tokens.append({"kind": "equation", "node": item, "display": None})
        elif name == "tbl":
            tokens.extend(table_blocks(item, binaries, members, pictures))
        elif name == "pic":
            tokens.append(picture_block(item, binaries, members, pictures))
        else:
            for child in list(item):
                walk(child)

    walk(node)
    visible = "".join(x for x in tokens if isinstance(x, str)).strip()
    display = not visible and all(
        isinstance(x, str) and not x.strip()
        or isinstance(x, dict) and x["kind"] == "equation" for x in tokens)
    blocks, text = [], []

    def flush() -> None:
        value = "".join(text).strip()
        text.clear()
        if value:
            blocks.append({"kind": "paragraph", "text": value})

    for token in tokens:
        if isinstance(token, str):
            text.append(token)
        elif token["kind"] == "equation":
            equation_display = (
                display if token.get("display") is None else token["display"])
            tag = token.get("tag") or equation_tag(
                token["node"], equation_display)
            if equation_display:
                flush()
                blocks.append({
                    "kind": "equation",
                    "tag": tag,
                    "source_paragraphs": token.get("source_paragraphs", 0),
                })
            else:
                text.append(tag)
        else:
            flush()
            blocks.append(token)
    flush()
    if blocks:
        blocks[0]["source_paragraphs"] = (
            blocks[0].get("source_paragraphs", 0) + 1)
    else:
        blocks.append({"kind": "paragraph_marker", "source_paragraphs": 1})
    return blocks


def attach_captions(blocks: list[dict]) -> list[dict]:
    result, index = [], 0
    while index < len(blocks):
        block = blocks[index]
        if (block["kind"] in CAPTIONS and index + 1 < len(blocks)
                and blocks[index + 1]["kind"] == "paragraph"
                and CAPTIONS[block["kind"]].match(blocks[index + 1]["text"])):
            block = dict(block)
            block["caption"] = blocks[index + 1]["text"].strip()
            block["source_paragraphs"] = (
                block.get("source_paragraphs", 0)
                + blocks[index + 1].get("source_paragraphs", 0)
            )
            index += 1
        result.append(block)
        index += 1
    return result


def render_sections(sections: list[list[dict]]) -> tuple[str, list[dict]]:
    lines, inventory, number = [], [], 0
    for source_section, blocks in enumerate(sections, 1):
        anchored = False
        for block in blocks:
            text = block.get("text", "")
            source_paragraphs = block.get("source_paragraphs", 0)
            heading = (block["kind"] == "paragraph" and len(text.strip()) <= 100
                       and not re.search(r"[.!?。！？]\s*$", text)
                       and HEADING.match(text))
            if heading:
                anchor = re.sub(r"\s+", " ", text).strip()
                lines.extend([f"## SECTION: {anchor}", ""])
                inventory.append({"anchor": anchor, "synthetic": False,
                                  "source_section": source_section})
                anchored = True
                if source_paragraphs:
                    lines.extend([
                        f"<!-- HWPX-SOURCE-PARAGRAPHS: {source_paragraphs} -->",
                        "",
                    ])
                continue
            if not anchored:
                number += 1
                anchor = f"EXTRACTED CONTENT {number}"
                lines.extend([f"## SECTION: {anchor}", ""])
                inventory.append({"anchor": anchor, "synthetic": True,
                                  "source_section": source_section})
                anchored = True
            if source_paragraphs:
                lines.extend([
                    f"<!-- HWPX-SOURCE-PARAGRAPHS: {source_paragraphs} -->",
                    "",
                ])
            if block["kind"] == "paragraph":
                lines.extend([text, ""])
            elif block["kind"] == "equation":
                lines.extend([block["tag"], ""])
            elif block["kind"] == "picture":
                pic = block["picture"]
                attrs = [f'file="{pic["file"]}"']
                if pic["binary_ref"]:
                    attrs.append(f'binary_ref="{pic["binary_ref"]}"')
                if block.get("caption"):
                    attrs.append(f'caption="{block["caption"].replace(chr(34), "&quot;")}"')
                lines.extend([f"[[FIG {' '.join(attrs)}]]", ""])
            elif block["kind"] == "table":
                caption = (f' caption="{block["caption"].replace(chr(34), "&quot;")}"'
                           if block.get("caption") else "")
                lines.append(f"[[TABLE{caption}]]")
                lines.extend("| " + " | ".join(row) + " |" for row in block["rows"])
                lines.extend(["[[/TABLE]]", ""])
    return "\n".join(lines).rstrip() + "\n", inventory


def extract_document(source: str | Path) -> dict:
    source = Path(source)
    with zipfile.ZipFile(source) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        members = {item.filename: archive.read(item.filename)
                   for item in archive.infolist()}
    sections = section_names(list(members))
    if not sections:
        raise ValueError("HWPX contains no Contents/section*.xml")
    binaries, pictures, extracted_sections = package_binary_map(members), [], []
    for name in sections:
        root = ET.fromstring(members[name])
        parents = {child: parent for parent in root.iter() for child in parent}
        blocks = []
        for paragraph in root.iter():
            if not isinstance(paragraph.tag, str) or local(paragraph.tag) != "p":
                continue
            parent, in_cell = parents.get(paragraph), False
            while parent is not None:
                in_cell = in_cell or local(parent.tag) == "tc"
                parent = parents.get(parent)
            if not in_cell:
                blocks.extend(paragraph_blocks(
                    paragraph, binaries, members, pictures))
        extracted_sections.append(attach_captions(blocks))
    content, section_inventory = render_sections(extracted_sections)
    source_fingerprint = semantic_fingerprint(source)
    public_pictures = [{k: v for k, v in item.items() if k != "data"}
                       for item in pictures]
    manifest = {
        "schema": "rigorloom/content-extraction-v1",
        "source": {"path": str(source.resolve()), "sha256": sha_file(source)},
        "counts": source_fingerprint["counts"],
        "semantic_fingerprint": source_fingerprint,
        "content_semantic_fingerprint": content_markdown_fingerprint(content),
        "content_sha256": sha_bytes(content.encode("utf-8")),
        "sections": section_inventory,
        "pictures": public_pictures,
        "structural_representation": {
            "nested_tables": "flattened_sequential",
            "cell_objects": "emitted_after_containing_table_in_source_order",
            "paragraph_counts": "HWPX-SOURCE-PARAGRAPHS markers",
        },
    }
    return {"content": content, "manifest": manifest, "pictures": pictures}


def write_extraction(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    (out_dir / CONTENT_NAME).write_text(result["content"], encoding="utf-8")
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(result["manifest"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for picture in result["pictures"]:
        if picture["data"] is not None:
            (figures / picture["file"]).write_bytes(picture["data"])


def verify_saved(result: dict, out_dir: Path) -> list[dict]:
    hard = []
    try:
        saved = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        content = (out_dir / CONTENT_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{"code": "extraction_infidelity",
                 "msg": f"saved extraction could not be reopened: {exc}",
                 "at": str(out_dir)}]
    expected = result["manifest"]
    actual_content_fingerprint = content_markdown_fingerprint(content)
    checks = {
        "source_sha256": ((saved.get("source") or {}).get("sha256"),
                          expected["source"]["sha256"]),
        "counts": (saved.get("counts"), expected["semantic_fingerprint"]["counts"]),
        "semantic_fingerprint": (saved.get("semantic_fingerprint"),
                                 expected["semantic_fingerprint"]),
        "content_sha256": (saved.get("content_sha256"),
                           sha_bytes(content.encode("utf-8"))),
        "reextracted_content_sha256": (sha_bytes(content.encode("utf-8")),
                                       expected["content_sha256"]),
        "content_semantic_fingerprint": (
            actual_content_fingerprint,
            expected["content_semantic_fingerprint"]),
    }
    for field, (actual, wanted) in checks.items():
        if actual != wanted:
            hard.append({"code": "extraction_infidelity",
                         "msg": f"saved extraction differs at {field}",
                         "at": str(out_dir), "expected": wanted, "actual": actual})
    for field in ("normalized_text_sha256", "counts", "equation_scripts"):
        source_value = expected["semantic_fingerprint"][field]
        content_value = actual_content_fingerprint[field]
        if content_value != source_value:
            hard.append({
                "code": "extraction_infidelity",
                "msg": f"extracted {field} differs from source fingerprint",
                "at": str(out_dir / CONTENT_NAME),
                "expected": source_value,
                "actual": content_value,
            })
    for picture in expected["pictures"]:
        if picture["sha256"] is None:
            continue
        target = out_dir / "figures" / picture["file"]
        try:
            actual = sha_file(target)
        except OSError as exc:
            actual = f"unreadable: {exc}"
        if actual != picture["sha256"]:
            hard.append({"code": "extraction_infidelity",
                         "msg": "extracted picture differs from source binary",
                         "at": str(target), "expected": picture["sha256"],
                         "actual": actual})
    return hard


def run_extract(source: str | Path, out_dir: str | Path, *,
                verify: bool = False) -> tuple[dict, int]:
    source, out_dir = Path(source), Path(out_dir)
    if source.suffix.lower() != ".hwpx" or not source.is_file():
        return usage_error(source, "content_extract",
                           "source must be an existing .hwpx file")
    try:
        result = extract_document(source)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        return usage_error(source, "content_extract", f"invalid HWPX: {exc}")
    if not verify or not all((out_dir / name).is_file()
                             for name in (CONTENT_NAME, MANIFEST_NAME)):
        write_extraction(result, out_dir)
    hard = verify_saved(extract_document(source), out_dir) if verify else []
    warn = [{"code": "picture_binary_unresolved",
             "msg": "picture control has no resolvable BinData member",
             "at": f"picture:{item['index']}"}
            for item in result["manifest"]["pictures"]
            if item["source_member"] is None]
    verdict = verdict_skeleton(
        str(source.resolve()), "content_extract", hard=hard, warn=warn,
        extra={"content": str((out_dir / CONTENT_NAME).resolve()),
               "manifest": str((out_dir / MANIFEST_NAME).resolve()),
               "extraction_counts": result["manifest"]["counts"],
               "source_sha256": result["manifest"]["source"]["sha256"],
               "verified": verify})
    return verdict, EXIT_HARD if hard else EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="extract content.md and a fidelity manifest from a finished HWPX")
    parser.add_argument("source", help="finished .hwpx report")
    parser.add_argument("--out-dir", required=True,
                        help="receives content.md, manifest, and figures/")
    parser.add_argument("--verify", action="store_true",
                        help="re-extract and HARD-fail on saved extraction drift")
    return parser


def main(argv=None) -> int:
    return cli_main(
        build_parser(),
        lambda args: run_extract(args.source, args.out_dir, verify=args.verify),
        argv, create_out_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
