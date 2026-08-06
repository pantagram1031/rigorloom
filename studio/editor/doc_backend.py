"""Byte-local HWPX paragraph operations for the Studio editor spike.

The existing Stage-5 dispatcher assembles complete documents.  This spike adds
the narrower operation the web editor needs without changing that dispatcher:
replace the payload of one plain ``hp:t`` element while retaining all XML tags,
run/paragraph properties, objects, and every other ZIP member byte-for-byte.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")
_PREFIX = rb"[A-Za-z_][A-Za-z0-9_.-]*"
_P_TAG_RE = re.compile(
    rb"<(?P<close>/)?(?P<prefix>" + _PREFIX + rb"):p\b(?P<attrs>[^<>]*?)(?P<self>/)?>",
    re.DOTALL,
)
_T_RE = re.compile(
    rb"<(?P<prefix>" + _PREFIX + rb"):t\b(?![^>]*?/>)" rb"[^>]*>"
    rb"(?P<content>.*?)</(?P=prefix):t>",
    re.DOTALL,
)
_EQUATION_RE = re.compile(rb"<(?:" + _PREFIX + rb"):equation\b", re.IGNORECASE)
_OBJECT_RE = re.compile(
    rb"<(?:" + _PREFIX + rb"):(?:tbl|pic|container|ole|line|rect|ellipse|arc|"
    rb"polygon|curve|connectLine)\b",
    re.IGNORECASE,
)


class DocumentBackendError(RuntimeError):
    """Base exception for a fail-closed document operation."""


class UnsafeEdit(DocumentBackendError):
    """The requested paragraph cannot be edited without structural risk."""


@dataclass(frozen=True)
class ParagraphRecord:
    id: str
    section: str
    section_index: int
    paragraph_index: int
    text: str
    display_text: str
    editable: bool
    has_equation: bool
    protected_run_count: int
    hazards: tuple[str, ...]
    text_payload_sha256: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["hazards"] = list(self.hazards)
        return payload


@dataclass(frozen=True)
class FidelityResult:
    ok: bool
    changed_members: tuple[str, ...]
    unchanged_member_count: int
    limited_to_text_payload: bool
    section_sha256_before: str
    section_sha256_after: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["changed_members"] = list(self.changed_members)
        return payload


@dataclass(frozen=True)
class EditResult:
    paragraph_id: str
    old_text: str
    new_text: str
    output_path: Path
    fidelity: FidelityResult


@dataclass(frozen=True)
class _LocatedParagraph:
    record: ParagraphRecord
    paragraph_start: int
    paragraph_end: int
    text_start: int | None
    text_end: int | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_members(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise DocumentBackendError("HWPX contains duplicate ZIP member names")
            return infos, {item.filename: archive.read(item) for item in infos}
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentBackendError(f"cannot open HWPX: {exc}") from exc


def _paragraph_spans(xml: bytes) -> list[tuple[int, int]]:
    stack: list[tuple[bytes, int]] = []
    spans: list[tuple[int, int]] = []
    for match in _P_TAG_RE.finditer(xml):
        if match.group("close"):
            if not stack:
                raise DocumentBackendError("unbalanced paragraph close tag")
            prefix, start = stack.pop()
            if prefix != match.group("prefix"):
                raise DocumentBackendError("mismatched paragraph namespace prefix")
            spans.append((start, match.end()))
        elif match.group("self"):
            spans.append((match.start(), match.end()))
        else:
            stack.append((match.group("prefix"), match.start()))
    if stack:
        raise DocumentBackendError("unbalanced paragraph open tag")
    return sorted(spans)


def _decode_payload(payload: bytes) -> str:
    try:
        return html.unescape(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise DocumentBackendError("section text is not UTF-8") from exc


def _locate_paragraphs(path: Path) -> tuple[dict[str, bytes], list[_LocatedParagraph]]:
    _infos, members = _archive_members(path)
    sections = sorted(name for name in members if SECTION_RE.match(name))
    if not sections:
        raise DocumentBackendError("HWPX has no Contents/section*.xml members")
    located: list[_LocatedParagraph] = []
    for section_index, name in enumerate(sections):
        section = members[name]
        try:
            ET.fromstring(section)
        except ET.ParseError as exc:
            raise DocumentBackendError(f"malformed section XML: {name}: {exc}") from exc
        for paragraph_index, (start, end) in enumerate(_paragraph_spans(section)):
            fragment = section[start:end]
            text_matches = list(_T_RE.finditer(fragment))
            raw_text_parts = [match.group("content") for match in text_matches]
            nested_text_markup = any(b"<" in payload for payload in raw_text_parts)
            text_parts = [
                _decode_payload(re.sub(rb"<[^>]+>", b"", payload))
                for payload in raw_text_parts
            ]
            text = "".join(text_parts)
            equation_count = len(_EQUATION_RE.findall(fragment))
            has_equation = equation_count > 0
            has_object = bool(_OBJECT_RE.search(fragment))
            hazards = tuple(
                label for label, present in (
                    ("equation", has_equation),
                    ("object", has_object),
                    ("multiple-text-runs", len(text_matches) != 1),
                    ("nested-text-markup", nested_text_markup),
                ) if present
            )
            editable = (
                len(text_matches) == 1
                and not has_equation
                and not has_object
                and not nested_text_markup
            )
            display_text = text
            if has_equation:
                display_text = (
                    f"{text_parts[0]}[equation]{''.join(text_parts[1:])}"
                    if text_parts else "[equation]"
                )
            paragraph_id = f"s{section_index}-p{paragraph_index}"
            text_start = text_end = None
            if len(text_matches) == 1:
                text_start = start + text_matches[0].start("content")
                text_end = start + text_matches[0].end("content")
            record = ParagraphRecord(
                id=paragraph_id,
                section=name,
                section_index=section_index,
                paragraph_index=paragraph_index,
                text=text,
                display_text=display_text,
                editable=editable,
                has_equation=has_equation,
                protected_run_count=equation_count,
                hazards=hazards,
                text_payload_sha256=_sha256(
                    text_matches[0].group("content") if len(text_matches) == 1 else b""
                ),
            )
            located.append(_LocatedParagraph(
                record=record,
                paragraph_start=start,
                paragraph_end=end,
                text_start=text_start,
                text_end=text_end,
            ))
    return members, located


def inspect_paragraphs(path: str | os.PathLike[str]) -> list[ParagraphRecord]:
    """List paragraphs with fail-closed editability and equation flags."""
    _members, located = _locate_paragraphs(Path(path))
    return [item.record for item in located]


def _validate_xml_text(value: str) -> None:
    if not isinstance(value, str):
        raise UnsafeEdit("new paragraph text must be a string")
    if len(value) > 20_000:
        raise UnsafeEdit("new paragraph text exceeds the 20,000-character spike limit")
    for char in value:
        code = ord(char)
        valid = (
            code in {0x9, 0xA, 0xD}
            or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD
            or 0x10000 <= code <= 0x10FFFF
        )
        if not valid:
            raise UnsafeEdit(f"new paragraph text contains invalid XML character U+{code:04X}")


def _write_archive(
    output: Path,
    infos: list[zipfile.ZipInfo],
    members: dict[str, bytes],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".hwpx", dir=str(output.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w") as archive:
            for info in infos:
                archive.writestr(info, members[info.filename])
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()


def apply_paragraph_edit(
    source: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    paragraph_id: str,
    new_text: str,
    expected_old_text: str | None = None,
) -> EditResult:
    """Apply one plain-text edit and prove that no other member changed."""
    source_path = Path(source)
    output_path = Path(output)
    if source_path.resolve() == output_path.resolve():
        raise UnsafeEdit("source and output must be different files")
    _validate_xml_text(new_text)
    infos, before = _archive_members(source_path)
    _members, located = _locate_paragraphs(source_path)
    target = next((item for item in located if item.record.id == paragraph_id), None)
    if target is None:
        raise UnsafeEdit("paragraph no longer exists")
    if not target.record.editable:
        detail = ", ".join(target.record.hazards) or "unsupported structure"
        raise UnsafeEdit(f"paragraph is protected: {detail}")
    if expected_old_text is not None and target.record.text != expected_old_text:
        raise UnsafeEdit("paragraph changed since it was read")
    assert target.text_start is not None and target.text_end is not None
    section_name = target.record.section
    section_before = before[section_name]
    encoded = escape(new_text).encode("utf-8")
    section_after = (
        section_before[:target.text_start]
        + encoded
        + section_before[target.text_end:]
    )
    try:
        ET.fromstring(section_after)
    except ET.ParseError as exc:
        raise UnsafeEdit(f"edited section would be malformed XML: {exc}") from exc
    after_payloads = dict(before)
    after_payloads[section_name] = section_after
    _write_archive(output_path, infos, after_payloads)

    _out_infos, written = _archive_members(output_path)
    if set(written) != set(before):
        output_path.unlink(missing_ok=True)
        raise DocumentBackendError("fidelity check failed: ZIP member set changed")
    changed = tuple(name for name in before if before[name] != written[name])
    limited = written.get(section_name) == section_after and all(
        written[name] == before[name] for name in before if name != section_name
    )
    if not limited or changed not in {(section_name,), ()}:
        output_path.unlink(missing_ok=True)
        raise DocumentBackendError("fidelity check failed: change escaped target text payload")
    fidelity = FidelityResult(
        ok=True,
        changed_members=changed,
        unchanged_member_count=len(before) - len(changed),
        limited_to_text_payload=True,
        section_sha256_before=_sha256(section_before),
        section_sha256_after=_sha256(section_after),
    )
    return EditResult(
        paragraph_id=paragraph_id,
        old_text=target.record.text,
        new_text=new_text,
        output_path=output_path,
        fidelity=fidelity,
    )
