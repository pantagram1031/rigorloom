"""``rigorloom guard BEFORE AFTER``: which paragraphs changed a protected fact.

Works on plain text, Markdown and HWPX, with no Hancom and no session root.
Paragraphs are compared in order: blank-line blocks for .txt/.md, ``<hp:p>``
elements for .hwpx. Each aligned pair goes through the same deterministic
checker as the report pipeline (``rt_fidelity`` is a byte-for-byte copy of
``modules/style/scripts/prose_fidelity.py``; a test keeps them equal).

A paragraph passes when every protected expression (numbers, dates, quotations,
negation, bounds, quantifiers, direction words, headings, ...) appears the same
number of times before and after. That is counting, not reading meaning.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from . import rt_fidelity as fidelity
except ImportError:  # run from the checkout as runtime/scripts/cli.py
    import rt_fidelity as fidelity

GUARD_SCHEMA = "rigorloom/guard-v1"
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_SECTION = re.compile(r"^Contents/section(\d+)\.xml$")


class GuardInputError(ValueError):
    """The inputs cannot be compared (missing, unsupported, unreadable)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hwpx_paragraphs(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            sections = sorted((int(m.group(1)), name) for name in zf.namelist()
                              if (m := _SECTION.match(name)))
            if not sections:
                raise GuardInputError(f"{path.name}: no Contents/section*.xml, not an HWPX body")
            out: list[str] = []
            for _, name in sections:
                _walk(ET.fromstring(zf.read(name)), None, out)
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
        raise GuardInputError(f"{path}: no such file")
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
    result: dict = {"schema": GUARD_SCHEMA, "before": str(before), "after": str(after),
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


def _short(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k}×{n}" if n > 1 else str(k) for k, n in v.items()) or "-"
    return ", ".join(map(str, v)) or "-"


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
            lines.append(f"  {ch['kind']:<16} {_short(ch['before'])}  ->  {_short(ch['after'])}")
    lines.append("\nOK: every protected fact is unchanged." if result["pass"]
                 else "\nREVERT the paragraphs above.")
    return "\n".join(lines) + "\n"
