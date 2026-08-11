# -*- coding: utf-8 -*-
"""check_minwon.py — deterministic 민원·신고 서식 gate for a filled artifact.

The 민원 family (HWP usage landscape family ①) is the highest-prevalence HWP
work type: nearly every statute's 별지서식 is a 신청서/청구서/신고서 published as
a page-filling fixed grid. Its rules are the **inverse** of 공문's. A 기안문's
별지서식 declares that its guide vocabulary must be replaced by content; a 민원
서식 declares the opposite — its printed guide text is part of the document a
citizen submits:

    ※ 3쪽의 유의 사항을 읽고 작성하시기 바라며, 해당하는 내용 앞의 [ ]에 √표를 합니다.
    ※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다.

Both lines are the forms' own words, and each one *is* a rule: the 유의사항 must
survive, the selection must be made, and the shaded 접수·처리 block belongs to
the receiving office. This module carries **no Korean literals in code** — every
term and pattern lives in ``references/minwon_vocabulary.json``, asserted by
``tests/test_module_contract.py``.

Rules — see ``skill/references/minwon_flow.md`` §3 for the full table; each has a
positive fixture and a still-catches negative in ``tests/``:

  R0  artifact_missing / artifact_malformed / minwon_structure_absent
  R1  furniture:  byeolji_header_lost, paper_spec_footer_lost,
                  addressee_line_lost                       (needs --baseline)
  R2  staff:      staff_seat_filled, staff_seat_removed      (needs --baseline)
  R3  select:     checkbox_selection_absent,
                  checkbox_option_lost                      (needs --baseline)
  R4  human:      signature_marker_lost, seal_seat_overwritten
                                                            (needs --baseline)
  R5  guide:      guide_block_lost                           (needs --baseline)
  R6  identity:   identity_value_invented (no baseline needed),
                  identity_seat_autofilled                   (needs --baseline)
  R7  placeholder_glyphs_retained

Ten of the thirteen structural rules (everything under R1, R2, R4, R5 plus
checkbox_option_lost and identity_seat_autofilled) need the blank form as
``--baseline``: the family's rules are overwhelmingly PRESERVATION rules, and
"was this destroyed?" is only decidable against the form the artifact came from.

R6 is the privacy rule and the reason this module exists as much as any layout
concern: **the tool never invents an identity number.** A 주민등록번호-shaped
value that the operator did not declare in ``--fill-map`` is a HARD finding
whether or not a baseline is available, and a value written into a 주민등록번호 /
생년월일 seat the blank form left empty is HARD unless the fill map declared it.

Document state decides severity, and the document says which state it is in. A
pristine 별지서식 has no marked checkbox and still shows its unfilled 년 월 일
seat, so ``--mode auto`` classifies it ``blank`` and *reports* the unfilled shape
instead of failing it. ``draft`` = something was written but the date seat is
still unfilled: preservation rules are HARD, finishing rules WARN. ``final`` = no
unfilled date seat remains, everything HARD. ``--mode`` forces a state.

Exit 0 = clean, 2 = usage/input error, 3 = HARD finding. Rules that cannot be
decided from the inputs given are listed under ``skipped`` with a reason — never
silently passed.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
MODULE_ROOT = SCRIPTS_DIR.parent
INSTALL_ROOT = SCRIPTS_DIR.parents[2]
CORE_SCRIPTS_DIR = INSTALL_ROOT / "pipeline" / "scripts"
ENGINE_SCRIPTS_DIR = INSTALL_ROOT / "engine" / "scripts"
for _dir in (CORE_SCRIPTS_DIR, ENGINE_SCRIPTS_DIR, SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    resolve_state,
    usage_error,
    rule_states,
    verdict_skeleton,
)
import check_residue  # noqa: E402  (core: render-critical XML validation)
import form_inspect  # noqa: E402  (core engine: paragraph/cell scanners)
from hwpx_tables import attr as tbl_attr, scan_tables  # noqa: E402

CHECKER = "check_minwon"

#: This checker's rule inventory. Needed so a rule that never appears in any
#: bucket can be reported ``clean`` rather than by silence — the convention T118
#: retired. DERIVED, not remembered: a regression parses this module's own
#: ``_finding("<name>"`` and ``{"rule": "<name>"}`` literals and asserts set
#: equality, so adding a rule without listing it here fails.
RULES = (
    "addressee_line_lost", "artifact_malformed", "artifact_missing",
    "byeolji_header_lost", "checkbox_option_lost",
    "checkbox_selection_absent", "guide_block_lost",
    "identity_seat_autofilled", "identity_value_invented",
    "minwon_structure_absent", "paper_spec_footer_lost",
    "placeholder_glyphs_retained", "seal_seat_overwritten",
    "signature_marker_lost", "staff_seat_filled", "staff_seat_removed",
)
VOCABULARY_SCHEMA = "rigorloom-minwon-vocabulary/v1"
DEFAULT_VOCABULARY = MODULE_ROOT / "references" / "minwon_vocabulary.json"

MODES = ("auto", "blank", "draft", "final")
STATE_BLANK, STATE_DRAFT, STATE_FINAL = "blank", "draft", "final"

#: Every regex key the rules compile. Validated at load time so a broken
#: vocabulary is a usage refusal, not a traceback in the middle of a rule.
REGEX_KEYS = (
    "byeolji_header_re", "paper_spec_re", "unfilled_date_seat_re",
    "unmarked_glyph_re", "marked_glyph_re", "select_instruction_re",
    "shading_declaration_re", "signature_marker_re", "rrn_re",
    "placeholder_glyph_re", "noise_re",
)

_WS_RE = re.compile(r"\s+")
_SECTION_MEMBER_RE = re.compile(r"^Contents/section\d*\.xml$", re.IGNORECASE)
_HEADER_MEMBER = "Contents/header.xml"


class MinwonError(Exception):
    """Usage-level refusal (exit 2)."""


# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #
def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MinwonError(f"{label} not found: {path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MinwonError(f"{label} unreadable: {exc}")
    if not isinstance(payload, dict):
        raise MinwonError(f"{label} must be a JSON object: {path}")
    return payload


def load_vocabulary(path: Path | str | None = None) -> dict:
    """The family's structural vocabulary, as data (never code literals)."""
    vocabulary = _load_json(Path(path or DEFAULT_VOCABULARY), "vocabulary")
    if vocabulary.get("schema") != VOCABULARY_SCHEMA:
        raise MinwonError(
            f"vocabulary schema must be {VOCABULARY_SCHEMA!r} "
            f"(got {vocabulary.get('schema')!r})")
    sections = vocabulary.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise MinwonError("vocabulary.sections must be a non-empty object")
    for name, spec in sections.items():
        if not isinstance(spec, dict):
            raise MinwonError(f"vocabulary.sections.{name} must be an object")
    for key in REGEX_KEYS:
        if not isinstance(vocabulary.get(key), str) or not vocabulary[key]:
            raise MinwonError(f"vocabulary.{key} must be a non-empty string")
        try:
            re.compile(vocabulary[key])
        except re.error as exc:
            raise MinwonError(f"vocabulary.{key} is not a valid regex: {exc}")
    brightness = vocabulary.get("shaded_face_max_brightness")
    if not isinstance(brightness, (int, float)) or not 0 <= brightness <= 1:
        raise MinwonError(
            "vocabulary.shaded_face_max_brightness must be a number in 0..1")
    return vocabulary


def load_fill_map(path: Path | str | None) -> dict | None:
    """The values the OPERATOR declared for this document, or None.

    Shape handling is core's (``check_residue.load_fill_map``): a bare
    ``{placeholder: value}`` object (the ``preedit.py replace --map`` shape) OR
    a wrapper object carrying a ``fill_map`` member, so ONE file serves this
    checker and ``visual_verify`` alike (T35). Only the values matter here —
    they are what makes an identity number "declared" rather than "invented".
    """
    if path is None:
        return None
    payload, error = check_residue.load_fill_map(Path(path))
    if error:
        raise MinwonError(error)
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float)):
            raise MinwonError(
                "fill map must map strings to scalar values "
                f"(offending key {key!r})")
    return payload


def declared_values(fill_map: dict | None) -> list[str]:
    if not fill_map:
        return []
    return [str(value) for value in fill_map.values() if str(value).strip()]


def _terms(vocabulary: dict, section: str, key: str) -> list[str]:
    spec = vocabulary["sections"].get(section) or {}
    value = spec.get(key) or []
    if isinstance(value, str):
        value = [value]
    return [item for item in value if isinstance(item, str) and item.strip()]


def _dedupe(items) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def keep_labels(vocabulary: dict) -> list[str]:
    """The minwon keep-list: printed guide blocks that must survive a fill."""
    return _dedupe(_terms(vocabulary, "guide", "keep_labels"))


# --------------------------------------------------------------------------- #
# whitespace-insensitive term matching
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _squeeze(text: str) -> str:
    """Drop every whitespace character.

    The 별지서식 letter-spaces its own labels ('접 수 증', '유 의 사 항',
    '연 락 처'), so a plain substring test misses them. Every term comparison in
    this module runs on squeezed text.
    """
    return _WS_RE.sub("", text or "")


def _contains(text: str, term: str) -> bool:
    return bool(term) and _squeeze(term) in _squeeze(text)


def _findall(pattern: str, text: str) -> list[str]:
    """Regex hits over squeezed text — patterns are written to tolerate both."""
    return re.findall(pattern, _squeeze(text))


def _count(pattern: str, text: str) -> int:
    return len(_findall(pattern, text))


def residual_text(text: str, terms, vocabulary: dict) -> str:
    """What is left of ``text`` once the given terms and layout noise go."""
    remainder = _squeeze(text)
    for term in sorted((item for item in terms if item), key=len, reverse=True):
        remainder = remainder.replace(_squeeze(term), " ")
    remainder = re.sub(vocabulary["placeholder_glyph_re"], " ", remainder)
    remainder = re.sub(vocabulary["unmarked_glyph_re"], " ", remainder)
    remainder = re.sub(vocabulary["marked_glyph_re"], " ", remainder)
    remainder = re.sub(vocabulary["noise_re"], " ", remainder)
    return remainder.strip()


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #
_WINBRUSH_RE = re.compile(r"<" + form_inspect.NS + r":winBrush\b([^>]*?)/?>", re.S)


def _brightness(color: str | None) -> float | None:
    """Mean-channel brightness of ``#RRGGBB`` (or ``#AARRGGBB``), 0..1.

    ``none`` and unparseable values are not a fill and return None. Mean channel
    rather than sRGB relative luminance on purpose: the vocabulary's threshold is
    a measured, human-checkable number ('#B2B2B2 is 0.698'), and a perceptual
    curve would make the declared value unreadable without buying any accuracy —
    every shade in the corpus is a neutral grey.
    """
    if not color or not color.startswith("#"):
        return None
    digits = color[1:]
    if len(digits) == 8:  # #AARRGGBB
        digits = digits[2:]
    if len(digits) != 6:
        return None
    try:
        channels = [int(digits[index:index + 2], 16) for index in (0, 2, 4)]
    except ValueError:
        return None
    return sum(channels) / (3 * 255)


def _borderfill_shading(header_xml: str) -> dict[str, float]:
    """borderFillIDRef -> mean-channel brightness of the fill it paints."""
    out: dict[str, float] = {}
    pattern = (r"<" + form_inspect.NS + r":borderFill\b([^>]*)>(.*?)</"
               + form_inspect.NS + r":borderFill>")
    for match in re.finditer(pattern, header_xml, re.S):
        bfid = form_inspect._attr(match.group(1), "id")
        if bfid is None:
            continue
        for brush in _WINBRUSH_RE.finditer(match.group(2)):
            value = _brightness(
                form_inspect._attr(brush.group(1), "faceColor"))
            if value is not None:
                out[bfid] = value
                break
    return out


def document_model(path: Path) -> dict:
    """Tables with per-cell paragraph text and shading, plus top-level text.

    Cell text is the cell's OWN text (nested-table spans removed, via the
    engine's ``_own_cell_body``) and top-level paragraphs come from the
    stack-based scanner, so a paragraph that merely *holds* a table never absorbs
    that table's cell text. XML entities are unescaped: the 별지서식 header line
    is stored as ``&lt;개정 2024. 12. 20.&gt;`` and a rule that reads it must see
    the characters, not the entities.
    """
    tables: list[dict] = []
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        header_xml = ""
        if _HEADER_MEMBER in names:
            header_xml = archive.read(_HEADER_MEMBER).decode(
                "utf-8", errors="replace")
        shading = _borderfill_shading(header_xml)
        index = 0
        for name in names:
            if not _SECTION_MEMBER_RE.match(name.replace("\\", "/")):
                continue
            xml = archive.read(name).decode("utf-8", errors="replace")
            scanned = scan_tables(xml)
            for table in scanned:
                cells = []
                for cell in table["cells"]:
                    body = form_inspect._own_cell_body(xml, cell, scanned)
                    texts = [html.unescape(para["text"])
                             for para in form_inspect._paragraphs(body, {})]
                    bfid = form_inspect._attr(cell["attrs"], "borderFillIDRef")
                    cells.append({
                        "addr": list(cell["addr"]) if cell["addr"] else None,
                        "span": list(cell["span"]),
                        "borderFillIDRef": bfid,
                        "face_brightness": shading.get(bfid or ""),
                        "paragraphs": texts,
                        "text": _normalize(" ".join(texts)),
                    })
                tables.append({
                    "index": index,
                    "section": name,
                    "depth": table["depth"],
                    "rowCnt": _int_or_none(tbl_attr(table["attrs"], "rowCnt")),
                    "colCnt": _int_or_none(tbl_attr(table["attrs"], "colCnt")),
                    "cells": cells,
                })
                index += 1
            paragraphs.extend(_own_top_level_texts(xml, scanned))
    return {"tables": tables, "paragraphs": paragraphs}


def _own_top_level_texts(xml: str, scanned: list[dict]) -> list[str]:
    """Top-level paragraph text with depth-0 table spans removed.

    ``form_inspect._find_top_level_paragraphs`` returns the paragraph's WHOLE
    span, so the paragraph that merely *holds* a form's frame table would report
    every cell's text as its own. 행정규칙 서식 (가족돌봄 휴가 신청서) keeps half
    its seats in top-level paragraphs, so this has to be right.
    """
    spans = sorted((table["start"], table["end"]) for table in scanned
                   if table["depth"] == 0)
    texts = []
    for start, end, _text in form_inspect._find_top_level_paragraphs(xml):
        pieces, cursor = [], start
        for table_start, table_end in spans:
            if table_end <= start or table_start >= end:
                continue
            pieces.append(xml[cursor:max(cursor, table_start)])
            cursor = max(cursor, table_end)
        pieces.append(xml[min(cursor, end):end])
        own = "".join(pieces)
        texts.append(html.unescape("".join(
            re.sub(r"<[^>]+>", "", found)
            for found in form_inspect.T_RE.findall(own))))
    return texts


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iter_cells(model: dict):
    """(location, cell, table) for every table cell."""
    for table in model["tables"]:
        for cell in table["cells"]:
            yield {"table": table["index"], "addr": cell["addr"]}, cell, table


def iter_seats(model: dict):
    """(location, text) at seat granularity: one entry per paragraph."""
    for table in model["tables"]:
        for cell in table["cells"]:
            base = {"table": table["index"], "addr": cell["addr"]}
            for position, text in enumerate(cell["paragraphs"]):
                if _normalize(text):
                    yield {**base, "para": position}, _normalize(text)
    for position, text in enumerate(model["paragraphs"]):
        if _normalize(text):
            yield {"paragraph": position}, _normalize(text)


def haystack(model: dict) -> str:
    return " ".join(text for _at, text in iter_seats(model))


def addressed_cells(model: dict) -> dict:
    """(table, addr) -> cell, for the addressable cells (merged-cell topology
    means addresses are sparse, never a dense grid)."""
    return {(location["table"], tuple(location["addr"])): cell
            for location, cell, _table in iter_cells(model)
            if location["addr"]}


# --------------------------------------------------------------------------- #
# seat locators — every one of them reads the form, not a hardcoded map
# --------------------------------------------------------------------------- #
def declares_shading_rule(model: dict, vocabulary: dict) -> bool:
    """Does the form itself say that its dark cells are not the citizen's?

    정보공개 청구서: '※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다.'
    Without that sentence, shading means something else — 주민등록 등초본 신청서
    paints its section headers and its instruction blocks #B2B2B2 too, and one of
    those instruction blocks CARRIES CHECKBOXES the citizen must mark.
    """
    return bool(_findall(vocabulary["shading_declaration_re"],
                         haystack(model)))


def staff_seats(model: dict, vocabulary: dict) -> list[dict]:
    """The 접수(처리) 기관 block: cells a citizen must not write in.

    Two independent recognizers, both derived from the document:

    ``label``    the cell carries a 접수·처리 label from the vocabulary. This is
                 the 「민원 처리에 관한 법률 시행규칙」 접수란 convention and it
                 is what covers 사업자등록 신청서, whose 접수번호 row is shaded
                 but carries no shading declaration.
    ``shaded``   the cell's fill is at or below the declared brightness AND the
                 form declares the shading rule. Cells whose text carries a
                 checkbox glyph are exempt: marking a box inside a shaded
                 instruction block is a legitimate edit, not a staff-seat write.
    """
    labels = _terms(vocabulary, "staff", "labels")
    limit = vocabulary["shaded_face_max_brightness"]
    shading_declared = declares_shading_rule(model, vocabulary)
    seats = []
    for location, cell, _table in iter_cells(model):
        if location["addr"] is None:
            continue
        found = [label for label in labels if _contains(cell["text"], label)]
        brightness = cell["face_brightness"]
        shaded = (shading_declared and brightness is not None
                  and brightness <= limit
                  and not _findall(vocabulary["unmarked_glyph_re"],
                                   cell["text"])
                  and not _findall(vocabulary["marked_glyph_re"],
                                   cell["text"]))
        if not found and not shaded:
            continue
        basis = ["label"] if found else []
        if shaded:
            basis.append("shaded")
        seats.append({"at": location, "text": cell["text"], "labels": found,
                      "basis": basis, "face_brightness": brightness})
    return seats


def _is_seat_cell(text: str, vocabulary: dict) -> bool:
    """Is this cell a SEAT, or prose that merely mentions a label?

    Two criteria, both read off the cell:

    - it carries no checkbox glyph — '7. 주민등록번호 뒷자리 [ ]포함( □본인,
      □세대원)' is a selection option, not a place a number goes;
    - its squeezed text is short — 주민등록 등초본 신청서's instruction block runs
      to ~150 characters and mentions 생년월일 in passing. A seat is a label.

    Getting this wrong is not academic: without it, marking a checkbox inside
    that instruction block registered as writing into an identity seat.
    """
    limit = int(vocabulary.get("identity_seat_max_cell_chars") or 40)
    if _findall(vocabulary["unmarked_glyph_re"], text):
        return False
    if _findall(vocabulary["marked_glyph_re"], text):
        return False
    return len(_squeeze(text)) <= limit


def identity_seats(model: dict, vocabulary: dict) -> list[dict]:
    """Identity-number seats, with the slots their value would land in.

    A 별지서식 writes the value in one of three places and the corpus has all
    three: in the label's OWN cell ('주민등록번호' then the digits — 주민등록
    등초본 신청서, 정보공개 청구서), in the cell to the RIGHT (행정규칙 가족돌봄
    서식's 생년월일), or in the cell BELOW when the label is a column header
    (사업자등록 신청서 부표's 공동사업자 명세). All three are computed from the
    blank form's own topology, never declared per file.
    """
    labels = _terms(vocabulary, "identity", "labels")
    by_addr = addressed_cells(model)
    seats = []
    for location, cell, _table in iter_cells(model):
        if location["addr"] is None:
            continue
        found = [label for label in labels if _contains(cell["text"], label)]
        if not found or not _is_seat_cell(cell["text"], vocabulary):
            continue
        own_value = residual_text(cell["text"], found, vocabulary)
        slots = [{"at": location, "kind": "own_cell"}]
        row, col = location["addr"]
        neighbours = [
            ("right", (location["table"],
                       _next_in_row(model, location["table"], row, col))),
            ("below", (location["table"],
                       _next_in_column(model, location["table"], row, col))),
        ]
        for kind, (table_index, addr) in neighbours:
            if addr is None:
                continue
            neighbour = by_addr.get((table_index, addr))
            if neighbour is None or residual_text(
                    neighbour["text"], (), vocabulary):
                continue
            if not _is_seat_cell(neighbour["text"], vocabulary):
                continue
            slots.append({"at": {"table": table_index, "addr": list(addr)},
                          "kind": kind})
        seats.append({"at": location, "labels": found, "text": cell["text"],
                      "own_value": own_value, "slots": slots})
    return seats


def _next_in_row(model: dict, table_index: int, row: int, col: int):
    """The addressable cell immediately after (row, col) in the same row."""
    candidates = sorted(
        tuple(cell["addr"]) for _at, cell, table in iter_cells(model)
        if table["index"] == table_index and cell["addr"]
        and cell["addr"][0] == row and cell["addr"][1] > col)
    return candidates[0] if candidates else None


def _next_in_column(model: dict, table_index: int, row: int, col: int):
    """The addressable cell immediately below (row, col) in the same column."""
    candidates = sorted(
        tuple(cell["addr"]) for _at, cell, table in iter_cells(model)
        if table["index"] == table_index and cell["addr"]
        and cell["addr"][1] == col and cell["addr"][0] > row)
    return candidates[0] if candidates else None


def signature_cells(model: dict, vocabulary: dict) -> list[dict]:
    """Addressed cells that carry a 서명/인 marker, with the markers they carry."""
    pattern = vocabulary["signature_marker_re"]
    cells = []
    for location, cell, _table in iter_cells(model):
        if location["addr"] is None:
            continue
        markers = _findall(pattern, cell["text"])
        if markers:
            cells.append({"at": location, "markers": _dedupe(markers),
                          "text": cell["text"]})
    return cells


def signature_paragraph_count(model: dict, vocabulary: dict) -> int:
    """서명/인 markers living in TOP-LEVEL paragraphs, counted not located.

    행정규직 서식 keeps '신청인 : ○○○ (인)' and '확인자 : (부서장) (인)' as plain
    paragraphs, and a paragraph has no stable address — inserting one line
    renumbers every index after it. Counting is the honest comparison for that
    domain; the addressed-cell domain gets the positional rule, and the two
    domains are disjoint so nothing is judged twice.
    """
    pattern = vocabulary["signature_marker_re"]
    return sum(_count(pattern, text) for text in model["paragraphs"])


def seal_cells(model: dict, vocabulary: dict) -> list[dict]:
    """Cells that carry a 직인/관인 label — a placement, never a fill target."""
    labels = _terms(vocabulary, "human", "seal_labels")
    cells = []
    for location, cell, _table in iter_cells(model):
        found = [label for label in labels if _contains(cell["text"], label)]
        if found:
            cells.append({"at": location, "labels": found,
                          "text": cell["text"],
                          "residue": residual_text(cell["text"], found,
                                                   vocabulary)})
    return cells


def checkbox_cells(model: dict, vocabulary: dict) -> list[dict]:
    """Cells and paragraphs carrying checkbox glyphs, with marked/unmarked counts."""
    out = []
    for location, text in iter_seats(model):
        unmarked = _count(vocabulary["unmarked_glyph_re"], text)
        marked = _count(vocabulary["marked_glyph_re"], text)
        if unmarked or marked:
            out.append({"at": location, "unmarked": unmarked,
                        "marked": marked, "slots": unmarked + marked})
    return out


def checkbox_slots_by_cell(model: dict, vocabulary: dict) -> dict:
    """(table, addr) -> total checkbox slots in that cell (marked + unmarked)."""
    out: dict = {}
    for location, cell, _table in iter_cells(model):
        if location["addr"] is None:
            continue
        slots = (_count(vocabulary["unmarked_glyph_re"], cell["text"])
                 + _count(vocabulary["marked_glyph_re"], cell["text"]))
        if slots:
            out[(location["table"], tuple(cell["addr"]))] = slots
    return out


def header_lines(model: dict, vocabulary: dict) -> list[str]:
    return _dedupe(_findall(vocabulary["byeolji_header_re"], haystack(model)))


def paper_spec_count(model: dict, vocabulary: dict) -> int:
    return sum(_count(vocabulary["paper_spec_re"], text)
               for _at, text in iter_seats(model))


def addressee_count(model: dict, vocabulary: dict) -> int:
    labels = _terms(vocabulary, "furniture", "labels")
    return sum(1 for _at, text in iter_seats(model)
               if any(_contains(text, label) for label in labels))


# --------------------------------------------------------------------------- #
# state classification — the document says which state it is in
# --------------------------------------------------------------------------- #
def classify_state(model: dict, vocabulary: dict,
                   baseline_model: dict | None = None) -> dict:
    """Blank / draft / final, from the document's own evidence.

    ``written``  a checkbox is marked, or (with a baseline) some cell's text
                 differs from the blank form's. A pristine 서식 has neither.
    ``dated``    no unfilled 년 월 일 / 20 . . . seat remains. A submitted 민원
                 서식 is dated; the seat is the form's own declaration of that.

    ``blank`` = nothing written. ``final`` = written AND dated. ``draft`` =
    written but still undated. ``auto`` never reaches ``final`` while an unfilled
    date seat survives, which is deliberately conservative: 정보공개 청구서 has a
    SECOND date seat inside its staff-only 접수증 block that the citizen must
    leave alone, so that form reads ``draft`` unless the caller passes
    ``--mode final``. Documented in ``skill/references/minwon_flow.md`` §6.
    """
    marked = sum(row["marked"] for row in checkbox_cells(model, vocabulary))
    unfilled_dates = sum(_count(vocabulary["unfilled_date_seat_re"], text)
                         for _at, text in iter_seats(model))
    changed = []
    if baseline_model is not None:
        current = addressed_cells(model)
        for key, cell in addressed_cells(baseline_model).items():
            now = current.get(key)
            if now is None or _squeeze(now["text"]) != _squeeze(cell["text"]):
                changed.append({"table": key[0], "addr": list(key[1])})
    written = bool(marked or changed or not unfilled_dates)
    if not written:
        state = STATE_BLANK
    elif unfilled_dates:
        state = STATE_DRAFT
    else:
        state = STATE_FINAL
    return {"state": state, "marked_checkboxes": marked,
            "unfilled_date_seats": unfilled_dates,
            "cells_changed": len(changed),
            "changed_sample": changed[:5]}


def rule_families(model: dict, vocabulary: dict) -> list[str]:
    """Which 민원 서식 seat families the document actually carries."""
    text = haystack(model)
    families = []
    for section in vocabulary["sections"]:
        terms = (_terms(vocabulary, section, "labels")
                 + _terms(vocabulary, section, "seal_labels"))
        if any(_contains(text, term) for term in terms):
            families.append(section)
    if "furniture" not in families and _findall(
            vocabulary["byeolji_header_re"], text):
        families.append("furniture")
    if "select" not in families and (
            _findall(vocabulary["unmarked_glyph_re"], text)
            or _findall(vocabulary["marked_glyph_re"], text)):
        families.append("select")
    if "human" not in families and _findall(
            vocabulary["signature_marker_re"], text):
        families.append("human")
    return families


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _finding(code: str, msg: str, at, **extra) -> dict:
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


def _check_furniture(model, vocabulary, baseline_model, hard, warn, info,
                     skipped):
    """R1 — the 별지서식's own frame survives the fill."""
    current_headers = header_lines(model, vocabulary)
    if baseline_model is None:
        skipped.append({"rule": "byeolji_header_lost", "reason": "no_baseline"})
        skipped.append({"rule": "paper_spec_footer_lost",
                        "reason": "no_baseline"})
        skipped.append({"rule": "addressee_line_lost", "reason": "no_baseline"})
        if not current_headers:
            # Decidable without a baseline only as a WARN: a document produced
            # from something that was never a 별지서식 legitimately has none.
            warn.append(_finding(
                "byeolji_header_lost",
                "no 별지서식 header line (■ …시행규칙 [별지 제N호서식]) anywhere "
                "in the document, and no blank form to compare against",
                None, basis="artifact_only"))
        else:
            info.append({"seat": "byeolji_header", "state": "present",
                         "lines": current_headers})
        return

    for line in header_lines(baseline_model, vocabulary):
        if line not in current_headers:
            hard.append(_finding(
                "byeolji_header_lost",
                "a 별지서식 header line the blank form carries is gone — the "
                "statutory form identity must survive a fill",
                line, basis="baseline"))
        else:
            info.append({"seat": "byeolji_header", "state": "present",
                         "line": line})

    blank_footers = paper_spec_count(baseline_model, vocabulary)
    footers = paper_spec_count(model, vocabulary)
    if blank_footers == 0:
        info.append({"seat": "paper_spec_footer", "state": "none_in_baseline"})
    elif footers < blank_footers:
        hard.append(_finding(
            "paper_spec_footer_lost",
            "the regulation's paper-spec footer (210mm×297mm[백상지…]) is gone "
            "from at least one page — the 별지서식 prescribes it",
            None, baseline=blank_footers, artifact=footers))
    else:
        info.append({"seat": "paper_spec_footer", "state": "present",
                     "count": footers})

    blank_addressees = addressee_count(baseline_model, vocabulary)
    addressees = addressee_count(model, vocabulary)
    if blank_addressees == 0:
        info.append({"seat": "addressee_line", "state": "none_in_baseline"})
    elif addressees < blank_addressees:
        hard.append(_finding(
            "addressee_line_lost",
            "a 귀하 addressee line the blank form carries is gone — a 민원 "
            "서식 must say which authority it is submitted to",
            None, baseline=blank_addressees, artifact=addressees))
    else:
        info.append({"seat": "addressee_line", "state": "present",
                     "count": addressees})


def _check_staff(model, vocabulary, baseline_model, hard, info, skipped):
    """R2 — the 접수(처리) 기관 block belongs to the receiving office."""
    if baseline_model is None:
        skipped.append({"rule": "staff_seat_filled", "reason": "no_baseline"})
        skipped.append({"rule": "staff_seat_removed", "reason": "no_baseline"})
        for seat in staff_seats(model, vocabulary):
            info.append({"seat": "staff", "state": "recognized",
                         "basis": seat["basis"], "at": seat["at"]})
        return

    seats = staff_seats(baseline_model, vocabulary)
    if not seats:
        skipped.append({"rule": "staff_seat_filled", "reason": "seat_absent"})
        return
    current = addressed_cells(model)
    for seat in seats:
        key = (seat["at"]["table"], tuple(seat["at"]["addr"]))
        now = current.get(key)
        if now is None:
            hard.append(_finding(
                "staff_seat_removed",
                "a 접수·처리 기관 seat the blank form carries no longer exists "
                "in the artifact — the receiving office's block was deleted",
                seat["at"], basis=seat["basis"], labels=seat["labels"]))
            continue
        if _squeeze(now["text"]) != _squeeze(seat["text"]):
            hard.append(_finding(
                "staff_seat_filled",
                "a 접수·처리 기관 seat changed — 접수번호/접수일/처리기간 and "
                "every dark cell the form reserves are the office's to fill, "
                "never the applicant's",
                seat["at"], basis=seat["basis"], labels=seat["labels"],
                baseline=seat["text"], artifact=now["text"]))
        else:
            info.append({"seat": "staff", "state": "untouched",
                         "basis": seat["basis"], "at": seat["at"]})


def _check_select(model, vocabulary, state, baseline_model, hard, warn, info,
                  skipped):
    """R3 — 선택 항목: the selection must be made, the options must survive."""
    boxes = checkbox_cells(model, vocabulary)
    declares_instruction = bool(
        _findall(vocabulary["select_instruction_re"], haystack(model))
        or (baseline_model is not None
            and _findall(vocabulary["select_instruction_re"],
                         haystack(baseline_model))))
    marked = sum(row["marked"] for row in boxes)

    # ── the selection itself ───────────────────────────────────────────────
    if not boxes:
        skipped.append({"rule": "checkbox_selection_absent",
                        "reason": "seat_absent"})
    elif state == STATE_BLANK:
        skipped.append({"rule": "checkbox_selection_absent",
                        "reason": "document_state_blank"})
        info.append({"seat": "select", "state": "unmarked",
                     "groups": len(boxes),
                     "instruction_declared": declares_instruction})
    elif marked:
        info.append({"seat": "select", "state": "marked", "marked": marked,
                     "groups": len(boxes),
                     "instruction_declared": declares_instruction})
    else:
        row = _finding(
            "checkbox_selection_absent",
            "the document carries 선택 항목 ([ ] / □ groups) and not one box is "
            "marked — the form's own instruction is that the applicable option "
            "gets a √",
            boxes[0]["at"], groups=len(boxes),
            instruction_declared=declares_instruction)
        (hard if declares_instruction and state == STATE_FINAL
         else warn).append(row)

    # ── option preservation ────────────────────────────────────────────────
    # Deliberately NOT gated on the artifact having boxes: a fill that deleted
    # EVERY option leaves no boxes to iterate, and that is the worst case of
    # this rule rather than a reason to skip it.
    if baseline_model is None:
        skipped.append({"rule": "checkbox_option_lost", "reason": "no_baseline"})
        return
    blank_slots = checkbox_slots_by_cell(baseline_model, vocabulary)
    if not blank_slots:
        skipped.append({"rule": "checkbox_option_lost", "reason": "seat_absent"})
        return
    current = checkbox_slots_by_cell(model, vocabulary)
    for key, slots in blank_slots.items():
        now = current.get(key, 0)
        if now < slots:
            hard.append(_finding(
                "checkbox_option_lost",
                "a 선택 항목 slot the blank form carries is gone — marking a box "
                "turns [ ] into [√] and keeps the count; deleting an option "
                "removes a choice the regulation grants",
                {"table": key[0], "addr": list(key[1])},
                baseline=slots, artifact=now))


def _check_human(model, vocabulary, baseline_model, hard, info, skipped):
    """R4 — the seats a person completes by hand stay for that person."""
    if baseline_model is None:
        skipped.append({"rule": "signature_marker_lost",
                        "reason": "no_baseline"})
        skipped.append({"rule": "seal_seat_overwritten",
                        "reason": "no_baseline"})
        for cell in signature_cells(model, vocabulary):
            info.append({"seat": "signature", "state": "present",
                         "markers": cell["markers"], "at": cell["at"]})
        return

    current = addressed_cells(model)
    blank_signatures = signature_cells(baseline_model, vocabulary)
    blank_paragraph_markers = signature_paragraph_count(baseline_model,
                                                        vocabulary)
    if not blank_signatures and not blank_paragraph_markers:
        skipped.append({"rule": "signature_marker_lost",
                        "reason": "seat_absent"})
    if blank_paragraph_markers:
        markers = signature_paragraph_count(model, vocabulary)
        if markers < blank_paragraph_markers:
            hard.append(_finding(
                "signature_marker_lost",
                "a (서명 또는 인) marker the blank form carries in a top-level "
                "paragraph is gone — the signature seat stays for the human",
                None, basis="paragraph_count",
                baseline=blank_paragraph_markers, artifact=markers))
        else:
            info.append({"seat": "signature", "state": "reserved",
                         "basis": "paragraph_count",
                         "count": markers})
    for cell in blank_signatures:
        location = cell["at"]
        if location["addr"] is None:
            continue
        now = current.get((location["table"], tuple(location["addr"])))
        text = now["text"] if now is not None else ""
        missing = [marker for marker in cell["markers"]
                   if not _contains(text, marker)]
        if missing:
            hard.append(_finding(
                "signature_marker_lost",
                "a (서명 또는 인) marker the blank form carries is gone — the "
                "applicant's name may share the cell, but the signature seat "
                "itself stays for the human",
                location, markers=missing, artifact=text))
        else:
            info.append({"seat": "signature", "state": "reserved",
                         "markers": cell["markers"], "at": location})

    blank_seals = seal_cells(baseline_model, vocabulary)
    if not blank_seals:
        skipped.append({"rule": "seal_seat_overwritten",
                        "reason": "seat_absent"})
    for cell in blank_seals:
        location = cell["at"]
        if location["addr"] is None:
            continue
        now = current.get((location["table"], tuple(location["addr"])))
        if now is None:
            hard.append(_finding(
                "seal_seat_overwritten",
                "the 직인 slot the blank form carries is gone from the artifact "
                "— the seal position must survive for a human to stamp",
                location, labels=cell["labels"]))
            continue
        residue = residual_text(now["text"], cell["labels"], vocabulary)
        if residue != cell["residue"]:
            hard.append(_finding(
                "seal_seat_overwritten",
                "the 직인 slot carries text the blank form did not — the slot "
                "is a placement for a physical impression, never a fill target",
                location, labels=cell["labels"], value=residue))
        else:
            info.append({"seat": "seal", "state": "reserved",
                         "labels": cell["labels"], "at": location})


def _check_guide(model, vocabulary, baseline_model, hard, info, skipped):
    """R5 — the printed guide blocks are part of the submitted document."""
    if baseline_model is None:
        skipped.append({"rule": "guide_block_lost", "reason": "no_baseline"})
        return
    text = haystack(model)
    blank_text = haystack(baseline_model)
    present = [label for label in keep_labels(vocabulary)
               if _contains(blank_text, label)]
    if not present:
        skipped.append({"rule": "guide_block_lost", "reason": "seat_absent"})
        return
    for label in present:
        if not _contains(text, label):
            hard.append(_finding(
                "guide_block_lost",
                "a printed guide block the blank form carries is gone — a 민원 "
                "서식's 유의사항 / 수수료 / 제출서류 / 동의 text is part of the "
                "document the applicant submits, not scaffolding to strip",
                label))
        else:
            info.append({"seat": "guide_block", "state": "present",
                         "label": label})


def _check_identity(model, vocabulary, baseline_model, fill_map, hard, info,
                    skipped):
    """R6 — the privacy rule: the tool never invents an identity number."""
    declared = declared_values(fill_map)
    minimum = int(vocabulary.get("identity_value_min_length") or 2)

    # R6a: an RRN-shaped value nobody declared. Decidable WITHOUT a baseline —
    # if nothing declared it, its presence is the finding.
    found = _dedupe(_findall(vocabulary["rrn_re"], haystack(model)))
    allowed = set()
    for value in declared:
        allowed.update(_findall(vocabulary["rrn_re"], value))
    if baseline_model is not None:
        allowed.update(_findall(vocabulary["rrn_re"], haystack(baseline_model)))
    for value in found:
        if value in allowed:
            info.append({"seat": "identity_value", "state": "declared"})
            continue
        hard.append(_finding(
            "identity_value_invented",
            "a 주민등록번호-shaped value appears in the document and the "
            "operator did not declare it — an identity number is never "
            "synthesized, and an empty seat is the correct output",
            None, shape="rrn", declared_values=len(declared)))
    if not found:
        info.append({"seat": "identity_value", "state": "none_present"})

    # R6b: a value written into an identity seat the blank form left empty.
    if baseline_model is None:
        skipped.append({"rule": "identity_seat_autofilled",
                        "reason": "no_baseline"})
        return
    seats = identity_seats(baseline_model, vocabulary)
    if not seats:
        skipped.append({"rule": "identity_seat_autofilled",
                        "reason": "seat_absent"})
        return
    current = addressed_cells(model)
    blank_cells = addressed_cells(baseline_model)
    for seat in seats:
        for slot in seat["slots"]:
            key = (slot["at"]["table"], tuple(slot["at"]["addr"]))
            now = current.get(key)
            if now is None:
                continue
            was = blank_cells.get(key)
            value = residual_text(now["text"], seat["labels"], vocabulary)
            before = residual_text(was["text"] if was else "", seat["labels"],
                                   vocabulary)
            if value == before or len(value) < minimum:
                continue
            written = value[len(before):] if value.startswith(before) else value
            # A declared value is compared through the SAME residual reduction:
            # the operator writes '주민등록번호 900101-1234567' and the cell holds
            # '9001011234567' once the label and the layout hyphen are gone.
            allowed_values = [residual_text(item, seat["labels"], vocabulary)
                              for item in declared]
            if any(written and written in item
                   for item in allowed_values if item):
                info.append({"seat": "identity_seat", "state": "declared",
                             "labels": seat["labels"], "at": slot["at"]})
                continue
            hard.append(_finding(
                "identity_seat_autofilled",
                "an identity seat (주민등록번호 / 생년월일 / 등록번호) the blank "
                "form left empty now carries a value the operator did not "
                "declare — leave it for the applicant and say so",
                slot["at"], labels=seat["labels"], slot=slot["kind"],
                declared_values=len(declared)))


def _check_glyphs(model, vocabulary, state, hard, warn, skipped):
    """R7 — unfilled ○ placeholder runs (행정규칙 서식's '신청인 : ○○○ (인)')."""
    if state == STATE_BLANK:
        skipped.append({"rule": "placeholder_glyphs_retained",
                        "reason": "document_state_blank"})
        return
    hits = [at for at, text in iter_seats(model)
            if _findall(vocabulary["placeholder_glyph_re"], text)]
    if not hits:
        return
    row = _finding(
        "placeholder_glyphs_retained",
        "unfilled ○ placeholder runs survive — the 서식 writes the applicant's "
        "own name there",
        hits[0], seats=len(hits))
    (hard if state == STATE_FINAL else warn).append(row)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def check(
    artifact: str | Path,
    *,
    mode: str = "auto",
    vocabulary: str | Path | None = None,
    baseline: str | Path | None = None,
    fill_map: str | Path | None = None,
) -> tuple[dict, int]:
    artifact_path = Path(artifact)
    if mode not in MODES:
        return usage_error(str(artifact_path), CHECKER,
                           f"--mode must be one of {list(MODES)} (got {mode!r})")
    try:
        vocab = load_vocabulary(vocabulary)
        declared_map = load_fill_map(fill_map)
    except MinwonError as exc:
        return usage_error(str(artifact_path), CHECKER, str(exc))

    hard: list[dict] = []
    warn: list[dict] = []
    info: list[dict] = []
    skipped: list[dict] = []

    # Loud-failure contract (shared with check_residue): a missing pinned target
    # is a HARD finding, never a silent pass.
    if not artifact_path.is_file():
        hard.append(_finding(
            "artifact_missing",
            "pinned artifact path does not exist — refusing to pass a 민원 "
            "서식 gate against a missing target",
            str(artifact_path)))
        return (_verdict(artifact_path, None, hard, warn, info, skipped),
                exit_code(hard=hard))
    if not zipfile.is_zipfile(artifact_path):
        return usage_error(
            str(artifact_path), CHECKER,
            "artifact is not an hwpx (zip) document — 민원 서식 checks read "
            "Contents/section*.xml")

    # Validity precedes structure: a malformed section renders BLANK in Hancom,
    # so judging its text would certify an unopenable document.
    try:
        broken = check_residue.malformed_members(artifact_path)
    except (OSError, zipfile.BadZipFile) as exc:
        return usage_error(str(artifact_path), CHECKER,
                           f"artifact unreadable: {exc}")
    if broken:
        for row in broken:
            hard.append(_finding(
                "artifact_malformed",
                f"render-critical member {row['member']} is not well-formed "
                f"XML ({row['error']}) — 민원 서식 structure checks skipped",
                row["member"]))
        return (_verdict(artifact_path, None, hard, warn, info, skipped),
                exit_code(hard=hard))

    try:
        model = document_model(artifact_path)
        baseline_model = (document_model(Path(baseline))
                          if baseline is not None else None)
    except (OSError, zipfile.BadZipFile) as exc:
        return usage_error(str(artifact_path), CHECKER,
                           f"artifact unreadable: {exc}")

    families = rule_families(model, vocab)
    minimum = int(vocab.get("family_minimum") or 2)
    if len(families) < minimum:
        hard.append(_finding(
            "minwon_structure_absent",
            f"only {len(families)} 민원 서식 seat family/families recognized "
            f"(minimum {minimum}) — this document is not a 신청서/청구서/신고서",
            None, families=families))
        return (_verdict(artifact_path, {"families": families}, hard, warn,
                         info, skipped),
                exit_code(hard=hard))

    classification = classify_state(model, vocab, baseline_model)
    # The helper applies the declared mode AND reports a declaration
    # that disagrees with the evidence (T103); recording the override
    # in a sibling key was never the same as saying the two differ.
    conflict = resolve_state(classification, mode)
    state = classification["state_used"]
    if conflict:
        warn.append(conflict)
    classification["families"] = families
    classification["shading_rule_declared"] = declares_shading_rule(model,
                                                                   vocab)
    classification["fill_map_declared"] = len(declared_values(declared_map))

    _check_furniture(model, vocab, baseline_model, hard, warn, info, skipped)
    _check_staff(model, vocab, baseline_model, hard, info, skipped)
    _check_select(model, vocab, state, baseline_model, hard, warn, info,
                  skipped)
    _check_human(model, vocab, baseline_model, hard, info, skipped)
    _check_guide(model, vocab, baseline_model, hard, info, skipped)
    _check_identity(model, vocab, baseline_model, declared_map, hard, info,
                    skipped)
    _check_glyphs(model, vocab, state, hard, warn, skipped)

    return (_verdict(artifact_path, classification, hard, warn, info, skipped),
            exit_code(hard=hard))


def _verdict(artifact_path, classification, hard, warn, info, skipped) -> dict:
    return verdict_skeleton(
        str(artifact_path), CHECKER,
        hard=hard, warn=warn,
        extra={
            "artifact": str(artifact_path),
            "document": classification,
            "seats": info,
            "skipped": skipped,
            "rules": rule_states(RULES, hard, warn, skipped),
        },
        counts={
            "hard": len(hard),
            "warn": len(warn),
            "seats": len(info),
            "skipped": len(skipped),
        },
    )


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="deterministic 민원·신고 서식 gate for a filled artifact "
                    "(법령·행정규칙 별지서식 신청서/청구서/신고서)")
    parser.add_argument("artifact", help="hwpx document to check")
    parser.add_argument(
        "--mode", default="auto", choices=MODES,
        help="document state; 'auto' reads it from the document (default)")
    parser.add_argument(
        "--vocabulary", default=None,
        help=f"minwon vocabulary JSON (default: {DEFAULT_VOCABULARY.name} "
             "shipped with this module)")
    parser.add_argument(
        "--baseline", default=None,
        help="the BLANK form this artifact was filled from; enables the "
             "preservation rules (furniture, staff seats, checkbox options, "
             "signature markers, guide blocks, identity seats)")
    parser.add_argument(
        "--fill-map", dest="fill_map", default=None,
        help="the {placeholder: value} map the OPERATOR declared for this "
             "document — a bare map (preedit.py replace --map) or an object "
             "with a 'fill_map' member (visual_verify --expectations); "
             "either shape is accepted. Values here are what makes "
             "an identity number declared rather than invented")
    return cli_main(
        parser,
        lambda args: check(
            args.artifact,
            mode=args.mode,
            vocabulary=args.vocabulary,
            baseline=args.baseline,
            fill_map=args.fill_map,
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
