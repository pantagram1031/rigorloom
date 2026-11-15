"""``rigorloom guard BEFORE AFTER``: which paragraphs changed a protected fact.

Works on plain text, Markdown and HWPX, with no Hancom and no session root.
Paragraphs are compared in order: blank-line blocks for .txt/.md, ``<hp:p>``
elements for .hwpx. Each aligned pair goes through the same deterministic
checker as the report pipeline (``rt_fidelity`` is a byte-for-byte copy of
``modules/style/scripts/prose_fidelity.py``; a test keeps them equal).

guard REPORTS; it never edits or reverts a file. In the report pipeline the
same verdict restores the paragraph; here it only names it.

The output is not privacy-safe the way ``inspect`` is: it quotes the full text
of each changed paragraph (that is the point). File names are reported as
names, never as the paths given.

Inputs are bounded like the Runtime's ingress (``rt_codes``): file size, zip
member count, total uncompressed size and compression ratio; XML with a
DOCTYPE is refused, so entity expansion never runs.

A paragraph passes when every protected expression (numbers, dates, quotations,
negation, bounds, quantifiers, direction words, headings, ...) appears the same
number of times before and after. That is counting, not reading meaning.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from . import rt_fidelity as fidelity
    from .rt_codes import (MAX_SOURCE_BYTES, MAX_ZIP_COMPRESSION_RATIO,
                           MAX_ZIP_MEMBERS, MAX_ZIP_TOTAL_UNCOMPRESSED)
except ImportError:  # run from the checkout as runtime/scripts/cli.py
    import rt_fidelity as fidelity
    from rt_codes import (MAX_SOURCE_BYTES, MAX_ZIP_COMPRESSION_RATIO,
                          MAX_ZIP_MEMBERS, MAX_ZIP_TOTAL_UNCOMPRESSED)

GUARD_SCHEMA = "rigorloom/guard-v1"
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_SECTION = re.compile(r"^Contents/section(\d+)\.xml$")


class GuardInputError(ValueError):
    """The inputs cannot be compared (missing, unsupported, unreadable)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _zip_bounds(zf: zipfile.ZipFile, path: Path) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise GuardInputError(f"{path.name}: too many zip members ({len(infos)} > {MAX_ZIP_MEMBERS})")
    total = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos)
    if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
        raise GuardInputError(f"{path.name}: uncompressed size {total} exceeds {MAX_ZIP_TOTAL_UNCOMPRESSED}")
    if packed and total / packed > MAX_ZIP_COMPRESSION_RATIO:
        raise GuardInputError(f"{path.name}: compression ratio {total / packed:.0f} exceeds "
                              f"{MAX_ZIP_COMPRESSION_RATIO}")


def _hwpx_paragraphs(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            _zip_bounds(zf, path)
            sections = sorted((int(m.group(1)), name) for name in zf.namelist()
                              if (m := _SECTION.match(name)))
            if not sections:
                raise GuardInputError(f"{path.name}: no Contents/section*.xml, not an HWPX body")
            out: list[str] = []
            for _, name in sections:
                with zf.open(name) as member:  # bound real bytes, not declared sizes
                    data = member.read(MAX_ZIP_TOTAL_UNCOMPRESSED + 1)
                if len(data) > MAX_ZIP_TOTAL_UNCOMPRESSED:
                    raise GuardInputError(f"{path.name}: {name} is larger than {MAX_ZIP_TOTAL_UNCOMPRESSED} bytes")
                if b"<!DOCTYPE" in data[:4096].upper():
                    raise GuardInputError(f"{path.name}: {name} declares a DOCTYPE; refused")
                _walk(ET.fromstring(data), None, out)
            return out
    except zipfile.BadZipFile as exc:
        raise GuardInputError(f"{path.name}: not a zip, so not HWPX") from exc
    except ET.ParseError as exc:
        raise GuardInputError(f"{path.name}: section XML does not parse ({exc})") from exc


def _walk(node: ET.Element, current: list[str] | None, out: list[str]) -> None:
    """Collect each <p>'s own text; a <p> nested in a table cell is its own paragraph."""
    name = _local(node.tag)
    if name == "p":
        slot = len(out)
        out.append("")  # reserve the place first: outer paragraph before nested ones
        own: list[str] = []
        for child in node:
            _walk(child, own, out)
        out[slot] = "".join(own)
        return
    if name == "t" and current is not None:
        current.append(node.text or "")
        for child in node:  # tabs/line breaks inside a run carry tail text
            current.append(child.tail or "")
    else:
        for child in node:
            _walk(child, current, out)


def _text_paragraphs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    return [b.strip() for b in blocks if b.strip()]


def read_paragraphs(path: Path) -> list[str]:
    if not path.is_file():
        raise GuardInputError(f"{path.name}: no such file")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise GuardInputError(f"{path.name}: larger than {MAX_SOURCE_BYTES} bytes")
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        return _hwpx_paragraphs(path)
    if suffix in TEXT_SUFFIXES:
        return _text_paragraphs(path)
    raise GuardInputError(f"{path.name}: unsupported type {suffix or '(none)'}; "
                          "use .hwpx, .txt or .md")


def guard(before: Path, after: Path) -> dict:
    if Path(before).suffix.lower() != Path(after).suffix.lower():
        raise GuardInputError("BEFORE and AFTER must be the same kind of file")
    a, b = read_paragraphs(before), read_paragraphs(after)
    result: dict = {"schema": GUARD_SCHEMA, "before": Path(before).name, "after": Path(after).name,
                    "paragraphs": {"before": len(a), "after": len(b)}}
    if len(a) != len(b):
        # Paragraphs were added or removed: alignment would be a guess, and a
        # guess is how a moved number gets missed. Say so instead.
        result.update(pass_=False, reason="paragraph_count_changed", changed=[])
        return _finish(result)
    changed = []
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x == y:
            continue
        r = fidelity.audit_text(x, y)
        if not r["pass"]:
            changed.append({"paragraph": i, "kinds": [c["kind"] for c in r["changes"]],
                            "changes": r["changes"], "before": x, "after": y})
    result.update(pass_=not changed, reason=None if not changed else "protected_change",
                  edited=sum(1 for x, y in zip(a, b) if x != y), changed=changed)
    return _finish(result)


def _finish(result: dict) -> dict:
    result["pass"] = result.pop("pass_")
    return result


LABELS = {
    "numbers": "number/unit", "dates": "date", "source_ids": "source id",
    "citations": "citation", "tags": "document tag", "inline_math": "formula",
    "direct_quotes": "quotation", "urls": "URL", "markdown_links": "link",
    "headings": "heading", "qualifiers": "negation/hedge/bound",
    "quantifiers": "quantifier", "causal_markers": "cause/effect",
    "direction_words": "direction", "protected_spans": "protected span",
}


def _short(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k}×{n}" if n > 1 else str(k) for k, n in v.items()) or "(gone)"
    return ", ".join(map(str, v)) or "(gone)"


def format_table(result: dict) -> str:
    p = result["paragraphs"]
    if result.get("reason") == "paragraph_count_changed":
        return (f"paragraphs: {p['before']} before, {p['after']} after\n"
                "REFUSED: paragraphs were added or removed, so they cannot be "
                "compared one to one.\n")
    lines = [f"paragraphs: {p['before']}, edited: {result['edited']}, "
             f"changed a protected fact: {len(result['changed'])}"]
    for c in result["changed"]:
        lines.append(f"\n¶{c['paragraph']}")
        for ch in c["changes"]:
            label = LABELS.get(ch["kind"], ch["kind"])
            lines.append(f"  {label:<21} {_short(ch['before'])}  ->  {_short(ch['after'])}")
    lines.append("\nOK: every protected fact is unchanged." if result["pass"]
                 else "\nCHANGED: restore or review the paragraphs above.")
    return "\n".join(lines) + "\n"


def _counts(v) -> Counter:
    if isinstance(v, dict):
        return Counter({str(k): int(n) for k, n in v.items()})
    return Counter(str(x) for x in (v or []))


def _delta(c: Counter) -> str:
    return ", ".join(f"{k}×{n}" if n > 1 else k for k, n in c.items())


def _one_line(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "⏎")


def block_diff(before: Path, after: Path) -> tuple[str, bool]:
    """``--mode block-diff`` text, defined in docs/guard-block-diff.md.

    Returns (text, pass). Every edited paragraph gets a block, kept or not.
    """
    result = guard(before, after)
    if result.get("reason") == "paragraph_count_changed":
        return format_table(result), False
    table = format_table(result).splitlines()
    header, closing = table[0], table[-1]
    changed = {c["paragraph"]: c for c in result["changed"]}
    a, b = read_paragraphs(before), read_paragraphs(after)
    blocks = []
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x == y:
            continue
        c = changed.get(i)
        if c is None:
            lines = [f"¶{i} kept"]
        else:
            labels = ", ".join(dict.fromkeys(LABELS.get(k, k) for k in c["kinds"]))
            lines = [f"¶{i} CHANGED: {labels}"]
        lines += [f"- {_one_line(x)}", f"+ {_one_line(y)}"]
        for ch in (c["changes"] if c else []):
            label = LABELS.get(ch["kind"], ch["kind"])
            old, new = _counts(ch["before"]), _counts(ch["after"])
            if old - new:
                lines.append(f"  lost   {label}  {_delta(old - new)}")
            if new - old:
                lines.append(f"  added  {label}  {_delta(new - old)}")
        blocks.append("\n".join(lines))
    return "\n\n".join([header, *blocks, closing]) + "\n", result["pass"]
