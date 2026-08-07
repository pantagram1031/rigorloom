# -*- coding: utf-8 -*-
"""check_gongmun.py — deterministic 공문/기안문 structure gate for a filled artifact.

The 공문 family (HWP usage landscape family ②) is defined by
「행정업무의 운영 및 혁신에 관한 규정 시행규칙」: a 기안문 is 두문 / 본문 /
결문 with a 결재란, a 발신명의 line and a 관인·직인 slot, and the 별지서식's own
비고 block states the rule this checker enforces hardest —

    문서를 작성할 때 "행정기관명", "발신명", "기안자", "검토자", "결재권자",
    "직위(직급) 서명", "처리과명-연도별 일련번호(시행일)", "도로명주소",
    "홈페이지 주소", "공무원의 전자우편주소", "공개 구분"의 용어는
    표시하지 아니하고 그 내용을 적는다.

i.e. the *guide vocabulary itself* must not survive into a finished document,
while the section labels (수신 / 경유 / 제목 / 협조자 / 시행 / 접수 / 직인 …)
legitimately do. That is the residue class with a gongmun keep-list, and it is
regulation-level, not per-file: this module carries **no Korean literals in
code**. Every term lives in ``references/gongmun_vocabulary.json``, and each
form's own 비고 block is parsed at run time and unioned in, so a 서식 that names
a term the shipped table misses is still covered.

Rules — see ``skill/references/gongmun_flow.md`` §3 for the full table; each
has a positive fixture and a still-catches negative in ``tests/``:

  R0  artifact_missing / artifact_malformed / gongmun_structure_absent
  R1  두문:   dumun_label_missing, dumun_seat_unfilled, dumun_seat_half_filled
  R2  결재란: gyeoljae_seat_half_filled, gyeoljae_row_half_filled
  R3  결문:   gyeolmun_seat_half_filled, gyeolmun_issue_number_malformed,
              gyeolmun_seat_unfilled (WARN)
  R4  발신명의: balsin_myeongui_missing, balsin_myeongui_unfilled
  R5  직인:   seal_slot_overwritten, seal_slot_removed (needs --baseline)
  R6  guide_vocabulary_residue
  R7  bigo_block_retained
  R8  placeholder_glyphs_retained
  R9  issuer_not_in_pack (HARD), rank_not_in_pack (WARN) — only with a
      non-empty ``gongmun_org`` pack; the shipped default is deliberately empty
  R10 seat_emptied (needs --baseline)

Document state decides severity, and the document says which state it is in:
a pristine 별지서식 still carries its 비고 block and has written no value
anywhere, so ``--mode auto`` classifies it ``blank`` and reports the unfilled
shape instead of failing it. ``draft`` = 비고 still present but values written:
fill-consistency rules are HARD, finishing rules (R6/R7/R8) WARN. ``final`` =
비고 gone, everything HARD. ``--mode`` forces a state explicitly.

Exit 0 = clean, 2 = usage/input error, 3 = HARD finding. Rules that cannot be
decided from the inputs given are listed under ``skipped`` with a reason —
never silently passed.
"""
from __future__ import annotations

import argparse
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
    usage_error,
    verdict_skeleton,
)
import check_residue  # noqa: E402  (core: render-critical XML validation)
import form_inspect  # noqa: E402  (core engine: paragraph/cell scanners)
from hwpx_tables import attr as tbl_attr, scan_tables  # noqa: E402

CHECKER = "check_gongmun"
VOCABULARY_SCHEMA = "rigorloom-gongmun-vocabulary/v1"
DEFAULT_VOCABULARY = MODULE_ROOT / "references" / "gongmun_vocabulary.json"
PACK_TYPE = "gongmun_org"
DEFAULT_PACK = (MODULE_ROOT / "references" / "preference_packs" / "defaults"
                / f"{PACK_TYPE}.json")

MODES = ("auto", "blank", "draft", "final")
STATE_BLANK, STATE_DRAFT, STATE_FINAL = "blank", "draft", "final"

_WS_RE = re.compile(r"\s+")
_SECTION_MEMBER_RE = re.compile(r"^Contents/section\d*\.xml$", re.IGNORECASE)
_HEADER_MEMBER = "Contents/header.xml"


class GongmunError(Exception):
    """Usage-level refusal (exit 2)."""


# --------------------------------------------------------------------------- #
# vocabulary + pack
# --------------------------------------------------------------------------- #
def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GongmunError(f"{label} not found: {path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GongmunError(f"{label} unreadable: {exc}")
    if not isinstance(payload, dict):
        raise GongmunError(f"{label} must be a JSON object: {path}")
    return payload


def load_vocabulary(path: Path | str | None = None) -> dict:
    """The regulation's structural vocabulary, as data (never code literals)."""
    vocabulary = _load_json(Path(path or DEFAULT_VOCABULARY), "vocabulary")
    if vocabulary.get("schema") != VOCABULARY_SCHEMA:
        raise GongmunError(
            f"vocabulary schema must be {VOCABULARY_SCHEMA!r} "
            f"(got {vocabulary.get('schema')!r})")
    sections = vocabulary.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise GongmunError("vocabulary.sections must be a non-empty object")
    for name, spec in sections.items():
        if not isinstance(spec, dict):
            raise GongmunError(f"vocabulary.sections.{name} must be an object")
    regexes = ("bigo_quoted_term_re", "placeholder_glyph_re",
               "issue_number_re", "noise_re")
    for key in ("bigo_marker", *regexes):
        if not isinstance(vocabulary.get(key), str) or not vocabulary[key]:
            raise GongmunError(f"vocabulary.{key} must be a non-empty string")
    for key in regexes:
        try:
            re.compile(vocabulary[key])
        except re.error as exc:
            raise GongmunError(f"vocabulary.{key} is not a valid regex: {exc}")
    return vocabulary


def load_pack(path: Path | str | None) -> dict | None:
    """A ``gongmun_org`` pack instance, or None when none was supplied."""
    if path is None:
        return None
    pack = _load_json(Path(path), f"{PACK_TYPE} pack")
    if pack.get("pack_type") != PACK_TYPE:
        raise GongmunError(
            f"pack_type must be {PACK_TYPE!r} (got {pack.get('pack_type')!r})")
    for key in ("organizations", "departments", "ranks"):
        value = pack.get(key, [])
        if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value):
            raise GongmunError(f"{PACK_TYPE}.{key} must be a list of strings")
    return pack


def _terms(vocabulary: dict, section: str, key: str) -> list[str]:
    spec = vocabulary["sections"].get(section) or {}
    value = spec.get(key) or []
    if isinstance(value, str):
        value = [value]
    return [item for item in value if isinstance(item, str) and item.strip()]


def _dedupe(items) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def all_placeholders(vocabulary: dict) -> list[str]:
    """Every guide term the regulation says must be replaced by its content."""
    return _dedupe(term for section in vocabulary["sections"]
                   for term in _terms(vocabulary, section, "placeholders"))


def keep_labels(vocabulary: dict) -> list[str]:
    """The gongmun keep-list: section labels that legitimately remain.

    ``approver_roles`` is deliberately NOT here — 기안자/검토자/결재권자 are named
    by the 비고 as terms to replace, so they belong to the residue class even
    though they read like labels.
    """
    return _dedupe(term for section in vocabulary["sections"]
                   for key in ("labels", "required_labels", "issue_labels")
                   for term in _terms(vocabulary, section, key))


# --------------------------------------------------------------------------- #
# whitespace-insensitive term matching
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _squeeze(text: str) -> str:
    """Drop every whitespace character.

    The 별지서식 letter-spaces its own labels ("행 정 기 관 명", "( 제    목 )"),
    so a plain substring test misses them. Every term comparison in this module
    runs on squeezed text.
    """
    return _WS_RE.sub("", text or "")


def _contains(text: str, term: str) -> bool:
    return bool(term) and _squeeze(term) in _squeeze(text)


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #
_BORDER_RE = re.compile(
    r"<" + form_inspect.NS + r":\w*[Bb]order\b([^>]*?)/?>", re.S)


def _borderfill_colors(header_xml: str) -> dict[str, list[str]]:
    """borderFillIDRef -> the colours of the borders it actually DRAWS.

    ``type="NONE"`` borders are skipped even when they carry a colour: the
    corpus 발신명의 box declares ``rightBorder type="NONE" color="#FF0000"`` and
    would otherwise be mistaken for the red 직인 box.
    """
    out: dict[str, list[str]] = {}
    pattern = (r"<" + form_inspect.NS + r":borderFill\b([^>]*)>(.*?)</"
               + form_inspect.NS + r":borderFill>")
    for match in re.finditer(pattern, header_xml, re.S):
        bfid = form_inspect._attr(match.group(1), "id")
        if bfid is None:
            continue
        colors = []
        for border in _BORDER_RE.finditer(match.group(2)):
            attrs = border.group(1)
            kind = (form_inspect._attr(attrs, "type") or "").upper()
            color = form_inspect._attr(attrs, "color")
            if kind and kind != "NONE" and color:
                colors.append(color.upper())
        out[bfid] = colors
    return out


def document_model(path: Path) -> dict:
    """Tables with per-cell paragraph text, plus top-level paragraph text.

    Cell text is the cell's OWN text (nested-table spans removed, via the
    engine's ``_own_cell_body``) and top-level paragraphs come from the
    stack-based scanner, so a paragraph that merely *holds* a table never
    absorbs that table's cell text.
    """
    tables: list[dict] = []
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        header_xml = ""
        if _HEADER_MEMBER in names:
            header_xml = archive.read(_HEADER_MEMBER).decode(
                "utf-8", errors="replace")
        borderfills = _borderfill_colors(header_xml)
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
                    texts = [para["text"]
                             for para in form_inspect._paragraphs(body, {})]
                    bfid = form_inspect._attr(cell["attrs"], "borderFillIDRef")
                    cells.append({
                        "addr": list(cell["addr"]) if cell["addr"] else None,
                        "span": list(cell["span"]),
                        "borderFillIDRef": bfid,
                        "border_colors": borderfills.get(bfid or "", []),
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
    """Top-level paragraph text with nested-table spans removed.

    ``form_inspect._find_top_level_paragraphs`` returns the paragraph's WHOLE
    span, so the paragraph that merely *holds* the 기안문 frame table reports
    every cell's text as its own. Cutting the depth-0 table spans out first is
    what keeps 두문 seats from being counted twice (once per cell paragraph and
    once inside the holder paragraph).
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
        texts.append("".join(re.sub(r"<[^>]+>", "", found)
                             for found in form_inspect.T_RE.findall(own)))
    return texts


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iter_all(model: dict):
    """(location, text) for every cell, cell paragraph and top-level paragraph."""
    for table in model["tables"]:
        for cell in table["cells"]:
            base = {"table": table["index"], "addr": cell["addr"]}
            yield dict(base), cell["text"], cell
            for position, text in enumerate(cell["paragraphs"]):
                yield {**base, "para": position}, _normalize(text), cell
    for position, text in enumerate(model["paragraphs"]):
        yield {"paragraph": position}, _normalize(text), None


def iter_seats(model: dict, vocabulary: dict):
    """Seat-granularity (location, text): one entry per paragraph.

    The 비고 cell is excluded wholesale — it is regulation commentary that
    *quotes* the guide vocabulary, not a seat. Scanning it would classify every
    blank form as half-filled and make residue detection meaningless.
    """
    marker = vocabulary["bigo_marker"]
    for location, text, cell in _iter_all(model):
        if "para" not in location and "paragraph" not in location:
            continue  # cell-level rows are served by iter_cells()
        owner = cell["text"] if cell is not None else text
        if _contains(owner, marker):
            continue
        if text:
            yield location, text


def iter_cells(model: dict, vocabulary: dict):
    """Cell-granularity (location, cell) with the 비고 cell excluded."""
    marker = vocabulary["bigo_marker"]
    for table in model["tables"]:
        for cell in table["cells"]:
            if _contains(cell["text"], marker):
                continue
            yield {"table": table["index"], "addr": cell["addr"]}, cell, table


def haystack(model: dict, vocabulary: dict) -> str:
    return " ".join(text for _at, text in iter_seats(model, vocabulary))


# --------------------------------------------------------------------------- #
# seat state — the one mechanism every fill rule is built on
# --------------------------------------------------------------------------- #
def residual_text(text: str, terms, vocabulary: dict) -> str:
    """What is left of ``text`` once the given terms and layout noise go.

    Placeholder glyph runs (○○○○) are layout, not content: a seat carrying
    nothing but ○ runs is unfilled, not filled.
    """
    remainder = _squeeze(text)
    for term in sorted((t for t in terms if t), key=len, reverse=True):
        remainder = remainder.replace(_squeeze(term), " ")
    remainder = re.sub(vocabulary["placeholder_glyph_re"], " ", remainder)
    remainder = re.sub(vocabulary["noise_re"], " ", remainder)
    return remainder.strip()


def seat_state(text: str, terms, vocabulary: dict) -> dict:
    """Tri-state fill judgment for one seat, from its own text alone.

    ``blank_by_design`` every guide term intact and nothing else written;
    ``filled``          every guide term consumed and a value present;
    ``emptied``         terms gone and nothing written (the seat was wiped);
    ``half_filled``     anything in between — some terms consumed but not all,
                        or a value written beside a surviving guide term.
    """
    terms = [term for term in terms if term]
    surviving = [term for term in terms if _contains(text, term)]
    other = residual_text(text, surviving, vocabulary)
    if not surviving:
        state = "filled" if other else "emptied"
    elif len(surviving) == len(terms) and not other:
        state = "blank_by_design"
    else:
        state = "half_filled"
    return {"state": state, "surviving": surviving, "value": other,
            "text": _normalize(text)}


def _seats_for(model: dict, vocabulary: dict, terms) -> list[dict]:
    """Every seat whose text carries at least one of ``terms``."""
    seats = []
    for location, text in iter_seats(model, vocabulary):
        present = [term for term in terms if _contains(text, term)]
        if present:
            seats.append({"at": location, "text": text, "terms": present})
    return seats


def _label_seats_for(model: dict, vocabulary: dict, labels) -> list[dict]:
    """Seats that OPEN with one of ``labels`` (leading layout noise ignored)."""
    leading = re.compile("^(?:" + vocabulary["noise_re"] + ")")
    seats = []
    for location, text in iter_seats(model, vocabulary):
        head = leading.sub("", _squeeze(text))
        present = [label for label in labels
                   if head.startswith(_squeeze(label))]
        if present:
            # longest match wins: "전화번호" over a hypothetical "전화"
            present.sort(key=len, reverse=True)
            seats.append({"at": location, "text": text,
                          "terms": present[:1]})
    return seats


# --------------------------------------------------------------------------- #
# locating the 비고 block and the seal slots
# --------------------------------------------------------------------------- #
def bigo_paragraphs(model: dict, vocabulary: dict) -> list[str]:
    marker = vocabulary["bigo_marker"]
    return [text for _at, text, _cell in _iter_all(model)
            if "para" in _at or "paragraph" in _at
            if _contains(text, marker)]


def bigo_terms(model: dict, vocabulary: dict) -> list[str]:
    """Guide terms the form's OWN 비고 block quotes — self-describing forms."""
    pattern = re.compile(vocabulary["bigo_quoted_term_re"])
    terms: list[str] = []
    for _at, text, cell in _iter_all(model):
        owner = cell["text"] if cell is not None else text
        if not _contains(owner, vocabulary["bigo_marker"]):
            continue
        for term in pattern.findall(text):
            candidate = _normalize(term)
            if candidate and candidate not in terms:
                terms.append(candidate)
    return terms


def seal_slots(model: dict, vocabulary: dict) -> list[dict]:
    """The 관인/직인 slots: a 1x1 box drawn in the regulation's red, or a 1x1
    box whose whole text is a seal label."""
    labels = _terms(vocabulary, "seal", "labels")
    reds = {color.upper() for color in vocabulary.get("seal_border_colors", [])}
    slots = []
    for location, cell, table in iter_cells(model, vocabulary):
        single = table["rowCnt"] == 1 and table["colCnt"] == 1
        if not single:
            continue
        red = bool(reds.intersection(cell["border_colors"]))
        present = [label for label in labels if _contains(cell["text"], label)]
        if red or present:
            slots.append({"at": location, "text": cell["text"],
                          "red_bordered": red, "labels": present})
    return slots


def issuer_boxes(model: dict, vocabulary: dict) -> list[dict]:
    """Nested single-cell boxes that are not seal slots — the 발신명의 seat's
    structural home in 별지 제1호서식 (a box inside the 본문 cell)."""
    seal_at = {json.dumps(slot["at"], sort_keys=True)
               for slot in seal_slots(model, vocabulary)}
    boxes = []
    for location, cell, table in iter_cells(model, vocabulary):
        if table["depth"] < 1:
            continue
        if json.dumps(location, sort_keys=True) in seal_at:
            continue
        boxes.append({"at": location, "text": cell["text"]})
    return boxes


def _table_rows(table: dict) -> dict[int, list[dict]]:
    rows: dict[int, list[dict]] = {}
    for cell in table["cells"]:
        if cell["addr"]:
            rows.setdefault(cell["addr"][0], []).append(cell)
    return rows


# --------------------------------------------------------------------------- #
# state classification — the document says which state it is in
# --------------------------------------------------------------------------- #
def classify_state(model: dict, vocabulary: dict) -> dict:
    """Blank / draft / final, from the document's own evidence.

    Two independent signals of "somebody wrote in this form": a placeholder
    seat that is no longer intact, and a kept section label that now carries a
    value ("수신 국가유산청장"). The second one matters because a *correctly*
    filled form has consumed every placeholder, so the first signal alone would
    read a finished-but-비고-bearing draft as a pristine blank.
    """
    placeholders = all_placeholders(vocabulary)
    bigo = bool(bigo_paragraphs(model, vocabulary))
    written = []
    for seat in _seats_for(model, vocabulary, placeholders):
        judged = seat_state(seat["text"], seat["terms"], vocabulary)
        if judged["state"] in ("filled", "half_filled"):
            written.append({"at": seat["at"], "state": judged["state"]})
    for seat in _label_seats_for(model, vocabulary, keep_labels(vocabulary)):
        if residual_text(seat["text"], seat["terms"], vocabulary):
            written.append({"at": seat["at"], "state": "label_value"})
    if not bigo:
        state = STATE_FINAL
    elif written:
        state = STATE_DRAFT
    else:
        state = STATE_BLANK
    return {"state": state, "bigo_present": bigo, "values_written": written}


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _finding(code: str, msg: str, at, **extra) -> dict:
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


def rule_families(model: dict, vocabulary: dict) -> list[str]:
    """Which of the five 공문 seat families the document actually carries."""
    text = haystack(model, vocabulary)
    families = []
    for section in vocabulary["sections"]:
        terms = (_terms(vocabulary, section, "labels")
                 + _terms(vocabulary, section, "placeholders")
                 + _terms(vocabulary, section, "approver_roles"))
        if any(_contains(text, term) for term in terms):
            families.append(section)
    return families


def _check_dumun(model, vocabulary, state, baseline_model, hard, warn, info,
                 skipped):
    labels = _terms(vocabulary, "dumun", "labels")
    required = _terms(vocabulary, "dumun", "required_labels")
    placeholders = _terms(vocabulary, "dumun", "placeholders")
    text = haystack(model, vocabulary)

    # "A label is gone" is only decidable against the form it came from:
    # 별지 제2호서식 (보고서형 기안문) legitimately has no 수신 seat at all, so
    # absence alone is not destruction.
    if baseline_model is None:
        skipped.append({"rule": "dumun_label_missing", "reason": "no_baseline"})
    else:
        blank_text = haystack(baseline_model, vocabulary)
        for label in labels:
            if _contains(blank_text, label) and not _contains(text, label):
                hard.append(_finding(
                    "dumun_label_missing",
                    "두문 section label the blank form carries is gone from "
                    "the document — the 기안문 frame was destroyed, not filled",
                    label))

    for seat in _label_seats_for(model, vocabulary, labels):
        # A 두문 label seat KEEPS its label; the value is written after it.
        value = residual_text(seat["text"], seat["terms"], vocabulary)
        if value:
            info.append({"seat": "dumun", "label": seat["terms"],
                         "state": "filled", "at": seat["at"]})
            continue
        if state == STATE_BLANK:
            info.append({"seat": "dumun", "label": seat["terms"],
                         "state": "unfilled", "at": seat["at"]})
            continue
        row = _finding(
            "dumun_seat_unfilled",
            "두문 seat carries its label and no value",
            seat["at"], label=seat["terms"])
        is_required = any(term in required for term in seat["terms"])
        (hard if state == STATE_FINAL and is_required else warn).append(row)

    for seat in _seats_for(model, vocabulary, placeholders):
        judged = seat_state(seat["text"], seat["terms"], vocabulary)
        if judged["state"] == "half_filled":
            hard.append(_finding(
                "dumun_seat_half_filled",
                "두문 guide term survives beside a written value — the "
                "regulation requires the term be replaced, not annotated",
                seat["at"], surviving=judged["surviving"],
                value=judged["value"]))
        else:
            info.append({"seat": "dumun_agency", "state": judged["state"],
                         "at": seat["at"]})


def _check_gyeoljae(model, vocabulary, hard, info, skipped):
    roles = _terms(vocabulary, "gyeoljae", "approver_roles")
    extra_terms = (_terms(vocabulary, "gyeoljae", "rank_term")
                   + _terms(vocabulary, "gyeoljae", "signature_term"))
    if not roles:
        skipped.append({"rule": "gyeoljae", "reason": "vocabulary_empty"})
        return
    seats = _seats_for(model, vocabulary, roles)
    if not seats:
        skipped.append({"rule": "gyeoljae", "reason": "seat_absent"})
        return

    approver_rows: set[tuple] = set()
    for seat in seats:
        judged = seat_state(seat["text"], seat["terms"] + extra_terms,
                            vocabulary)
        if judged["state"] == "half_filled":
            hard.append(_finding(
                "gyeoljae_seat_half_filled",
                "결재란 seat is neither filled nor blank-by-design — part of "
                "its guide vocabulary was consumed and part survives",
                seat["at"], role=seat["terms"],
                surviving=judged["surviving"], value=judged["value"]))
        else:
            info.append({"seat": "gyeoljae", "role": seat["terms"],
                         "state": judged["state"], "at": seat["at"]})
        at = seat["at"]
        if "table" in at and at.get("addr"):
            approver_rows.add((at["table"], at["addr"][0]))

    # Row-level consistency. The row is read from the TABLE, not from the seat
    # list: a seat that has already been filled carries no role term, so a
    # term-anchored view of the row would never see the filled sibling that
    # makes the row half-filled.
    for table in model["tables"]:
        for row_index, cells in sorted(_table_rows(table).items()):
            if (table["index"], row_index) not in approver_rows:
                continue
            members = []
            for cell in sorted(cells, key=lambda item: item["addr"][1]):
                present = [role for role in roles
                           if _contains(cell["text"], role)]
                if present:
                    judged = seat_state(cell["text"], present + extra_terms,
                                        vocabulary)
                    state_name = judged["state"]
                else:
                    state_name = ("filled"
                                  if residual_text(cell["text"], (), vocabulary)
                                  else "emptied")
                members.append({"addr": cell["addr"], "role": present,
                                "state": state_name})
            states = {member["state"] for member in members}
            if len(members) > 1 and "filled" in states and (
                    states & {"blank_by_design", "emptied"}):
                hard.append(_finding(
                    "gyeoljae_row_half_filled",
                    "결재란 row mixes filled and unfilled approver seats — the "
                    "row must be fully filled or blank by design",
                    {"table": table["index"], "row": row_index},
                    members=members))


def _check_gyeolmun(model, vocabulary, state, hard, warn, info, skipped):
    labels = _terms(vocabulary, "gyeolmun", "labels")
    issue_labels = _terms(vocabulary, "gyeolmun", "issue_labels")
    placeholders = _terms(vocabulary, "gyeolmun", "placeholders")
    issue_re = re.compile(vocabulary["issue_number_re"])

    seats = _seats_for(model, vocabulary, placeholders)
    if not seats and not _seats_for(model, vocabulary, labels):
        skipped.append({"rule": "gyeolmun", "reason": "seat_absent"})
        return

    for seat in seats:
        judged = seat_state(seat["text"], seat["terms"], vocabulary)
        if judged["state"] == "half_filled":
            hard.append(_finding(
                "gyeolmun_seat_half_filled",
                "결문 seat carries a value beside a surviving guide term",
                seat["at"], surviving=judged["surviving"],
                value=judged["value"]))
        elif judged["state"] == "blank_by_design" and state == STATE_FINAL:
            warn.append(_finding(
                "gyeolmun_seat_unfilled",
                "결문 seat is still the blank form's guide term in a document "
                "classified final",
                seat["at"], surviving=judged["surviving"]))
        else:
            info.append({"seat": "gyeolmun", "state": judged["state"],
                         "at": seat["at"]})

    # 시행/접수 numbering: 처리과명-연도별 일련번호(날짜). A value that is not in
    # that shape is a regulation violation, not a style choice.
    for table in model["tables"]:
        for row_index, cells in sorted(_table_rows(table).items()):
            ordered = sorted(cells, key=lambda cell: cell["addr"][1])
            for position, cell in enumerate(ordered):
                label = next((item for item in issue_labels
                              if _squeeze(cell["text"]) == _squeeze(item)),
                             None)
                if label is None or position + 1 >= len(ordered):
                    continue
                neighbour = ordered[position + 1]
                if not residual_text(neighbour["text"], placeholders,
                                     vocabulary):
                    continue  # blank, or still the guide term — other rules
                if issue_re.match(_normalize(neighbour["text"])):
                    info.append({"seat": "gyeolmun_issue", "label": label,
                                 "value": _normalize(neighbour["text"])})
                else:
                    hard.append(_finding(
                        "gyeolmun_issue_number_malformed",
                        "결문 시행/접수 value is not in the regulated "
                        "처리과명-일련번호(날짜) shape",
                        {"table": table["index"], "addr": neighbour["addr"]},
                        label=label, value=_normalize(neighbour["text"])))


def _check_balsin(model, vocabulary, state, hard, info):
    placeholders = _terms(vocabulary, "balsin", "placeholders")
    glyph_re = re.compile(vocabulary["placeholder_glyph_re"])
    seats = _seats_for(model, vocabulary, placeholders)

    if seats:
        for seat in seats:
            judged = seat_state(seat["text"], seat["terms"], vocabulary)
            if judged["state"] == "half_filled" or (
                    state == STATE_FINAL and judged["state"] != "filled"):
                hard.append(_finding(
                    "balsin_myeongui_unfilled",
                    "발신명의 seat still shows the form's guide term — a "
                    "finished 공문 must name its issuer",
                    seat["at"], surviving=judged["surviving"]))
            else:
                info.append({"seat": "balsin", "state": judged["state"],
                             "at": seat["at"]})
        return

    # No 발신명의 term: either the seat is a glyph placeholder (별지 제2호서식's
    # ○○○○부) or it was filled — in which case the box it lives in still has
    # content — or the issuer line is gone entirely.
    glyphs = [at for at, text in iter_seats(model, vocabulary)
              if glyph_re.search(_squeeze(text))]
    if glyphs:
        row = _finding(
            "balsin_myeongui_unfilled",
            "issuing-organization seat is still a ○ placeholder",
            glyphs[0], seats=len(glyphs))
        if state == STATE_FINAL:
            hard.append(row)
        else:
            info.append({"seat": "balsin", "state": "placeholder_glyphs",
                         "seats": len(glyphs)})
        return
    filled_boxes = [box for box in issuer_boxes(model, vocabulary)
                    if box["text"]]
    if filled_boxes:
        info.append({"seat": "balsin", "state": "filled",
                     "at": filled_boxes[0]["at"]})
        return
    if state == STATE_FINAL:
        hard.append(_finding(
            "balsin_myeongui_missing",
            "no 발신명의 seat and no issuing-organization line — a 공문 must "
            "say who issues it",
            None))
    else:
        info.append({"seat": "balsin", "state": "absent"})


def _check_seal(model, vocabulary, baseline_model, hard, info, skipped):
    labels = _terms(vocabulary, "seal", "labels")
    slots = seal_slots(model, vocabulary)
    if not slots:
        if baseline_model is not None and seal_slots(baseline_model,
                                                    vocabulary):
            hard.append(_finding(
                "seal_slot_removed",
                "the form's 직인 slot is gone from the artifact — the seal "
                "position must survive for a human to stamp",
                None))
        else:
            skipped.append({"rule": "seal_slot", "reason": "seat_absent"
                            if baseline_model is not None else "no_baseline"})
        return
    for slot in slots:
        extra = residual_text(slot["text"], labels, vocabulary)
        if extra:
            hard.append(_finding(
                "seal_slot_overwritten",
                "직인 slot carries text other than the seal label — the slot "
                "is a placement for a physical impression, never a fill target",
                slot["at"], value=extra))
        else:
            info.append({"seat": "seal", "state": "reserved",
                         "red_bordered": slot["red_bordered"],
                         "at": slot["at"]})


def _maximal(terms) -> list[str]:
    """Drop terms that are substrings of another term in the same list."""
    squeezed = {term: _squeeze(term) for term in terms}
    out = []
    for term in terms:
        if any(other != term and squeezed[term] in squeezed[other]
               for other in terms):
            continue
        out.append(term)
    return out


def _check_residue(model, vocabulary, state, guide_terms, hard, warn, skipped):
    if state == STATE_BLANK:
        skipped.append({"rule": "guide_vocabulary_residue",
                        "reason": "document_state_blank"})
        return
    text = haystack(model, vocabulary)
    keep = set(keep_labels(vocabulary))
    for term in _maximal([t for t in guide_terms if t not in keep]):
        if not _contains(text, term):
            continue
        row = _finding(
            "guide_vocabulary_residue",
            "form guide vocabulary survives as literal text — the 별지서식's "
            "비고 requires the term be replaced by its content",
            term)
        (hard if state == STATE_FINAL else warn).append(row)


def _check_bigo(model, vocabulary, state, hard, warn, skipped):
    if state == STATE_BLANK:
        skipped.append({"rule": "bigo_block_retained",
                        "reason": "document_state_blank"})
        return
    if not bigo_paragraphs(model, vocabulary):
        return
    row = _finding(
        "bigo_block_retained",
        "the 비고 block survives — it declares itself outside the 서식 "
        "(이 난은 서식에 포함하지 아니한다) and must not ship in a 공문",
        vocabulary["bigo_marker"])
    (hard if state == STATE_FINAL else warn).append(row)


def _check_glyphs(model, vocabulary, state, hard, warn, skipped):
    if state == STATE_BLANK:
        skipped.append({"rule": "placeholder_glyphs_retained",
                        "reason": "document_state_blank"})
        return
    glyph_re = re.compile(vocabulary["placeholder_glyph_re"])
    hits = [at for at, text in iter_seats(model, vocabulary)
            if glyph_re.search(_squeeze(text))]
    if not hits:
        return
    row = _finding(
        "placeholder_glyphs_retained",
        "unfilled ○ placeholder runs survive in the document",
        hits[0], seats=len(hits))
    (hard if state == STATE_FINAL else warn).append(row)


def _check_pack(model, vocabulary, pack, baseline_model, hard, warn, info,
                skipped):
    if pack is None:
        skipped.append({"rule": "issuing_organization_pack",
                        "reason": "no_pack"})
        return
    organizations = list(pack.get("organizations") or [])
    departments = list(pack.get("departments") or [])
    ranks = list(pack.get("ranks") or [])
    if not (organizations or departments or ranks):
        skipped.append({"rule": "issuing_organization_pack",
                        "reason": "pack_vocabulary_empty",
                        "pack": pack.get("name")})
        return

    text = haystack(model, vocabulary)
    declared = organizations + departments
    if declared:
        if not any(_contains(text, name) for name in declared):
            hard.append(_finding(
                "issuer_not_in_pack",
                "no declared issuing organization or department appears in "
                "the document — the 발신명의/행정기관명 seats do not match the "
                f"{PACK_TYPE} pack",
                pack.get("name"), declared=declared))
        else:
            info.append({"seat": "issuer", "state": "in_pack",
                         "pack": pack.get("name")})
    if not ranks:
        return
    # A FILLED 결재란 seat no longer carries its role term, so the seat cannot
    # be found by vocabulary alone — the blank form is what says where the
    # approver seats are. Without it the rank rule is undecidable, not passing.
    roles = _terms(vocabulary, "gyeoljae", "approver_roles")
    if baseline_model is None:
        skipped.append({"rule": "rank_not_in_pack", "reason": "no_baseline"})
        return
    current = {(location["table"], tuple(location["addr"])): cell["text"]
               for location, cell, _table in iter_cells(model, vocabulary)
               if location["addr"]}
    for location, cell, _table in iter_cells(baseline_model, vocabulary):
        if not location["addr"]:
            continue
        if not any(_contains(cell["text"], role) for role in roles):
            continue
        value = current.get((location["table"], tuple(location["addr"])), "")
        if not value or any(_contains(value, role) for role in roles):
            continue  # empty or still unfilled — other rules own those
        if not any(_contains(value, rank) for rank in ranks):
            warn.append(_finding(
                "rank_not_in_pack",
                "결재란 seat names a 직위 the issuing-organization pack does "
                "not declare",
                location, value=_normalize(value), declared=ranks))
        else:
            info.append({"seat": "gyeoljae_rank", "state": "in_pack",
                         "at": location})


def _check_baseline_seats(model, vocabulary, baseline_model, guide_terms,
                          hard, info, skipped):
    if baseline_model is None:
        skipped.append({"rule": "seat_emptied", "reason": "no_baseline"})
        return
    exempt = vocabulary.get("human_completed_terms") or []
    current = {(location["table"], tuple(location["addr"])): cell["text"]
               for location, cell, _table in iter_cells(model, vocabulary)
               if location["addr"]}
    for location, cell, _table in iter_cells(baseline_model, vocabulary):
        if not location["addr"]:
            continue
        if not any(_contains(cell["text"], term) for term in guide_terms):
            continue
        if any(_contains(cell["text"], term) for term in exempt):
            info.append({"seat": "baseline_position", "state": "human_completed",
                         "at": location})
            continue
        key = (location["table"], tuple(location["addr"]))
        if key not in current:
            hard.append(_finding(
                "seat_emptied",
                "a seat the blank form carries no longer exists in the "
                "artifact — the fill deleted the seat instead of using it",
                location))
        elif not current[key]:
            hard.append(_finding(
                "seat_emptied",
                "a seat the blank form carries is empty in the artifact — its "
                "guide term was deleted and nothing was written",
                location))
        else:
            info.append({"seat": "baseline_position", "state": "present",
                         "at": location})


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def check(
    artifact: str | Path,
    *,
    mode: str = "auto",
    vocabulary: str | Path | None = None,
    pack: str | Path | None = None,
    baseline: str | Path | None = None,
) -> tuple[dict, int]:
    artifact_path = Path(artifact)
    if mode not in MODES:
        return usage_error(str(artifact_path), CHECKER,
                           f"--mode must be one of {list(MODES)} (got {mode!r})")
    try:
        vocab = load_vocabulary(vocabulary)
        pack_instance = load_pack(pack)
    except GongmunError as exc:
        return usage_error(str(artifact_path), CHECKER, str(exc))

    hard: list[dict] = []
    warn: list[dict] = []
    info: list[dict] = []
    skipped: list[dict] = []

    # Loud-failure contract (shared with check_residue): a missing pinned
    # target is a HARD finding, never a silent pass.
    if not artifact_path.is_file():
        hard.append(_finding(
            "artifact_missing",
            "pinned artifact path does not exist — refusing to pass a 공문 "
            "gate against a missing target",
            str(artifact_path)))
        return (_verdict(artifact_path, None, hard, warn, info, skipped),
                exit_code(hard=hard))
    if not zipfile.is_zipfile(artifact_path):
        return usage_error(
            str(artifact_path), CHECKER,
            "artifact is not an hwpx (zip) document — 공문 checks read "
            "Contents/section*.xml")

    # Validity precedes structure: a malformed section renders BLANK in
    # Hancom, so judging its text would certify an unopenable document.
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
                f"XML ({row['error']}) — 공문 structure checks skipped",
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

    guide_terms = _dedupe(all_placeholders(vocab)
                          + bigo_terms(model, vocab)
                          + (bigo_terms(baseline_model, vocab)
                             if baseline_model is not None else []))
    families = rule_families(model, vocab)
    minimum = int(vocab.get("family_minimum") or 2)
    if len(families) < minimum:
        hard.append(_finding(
            "gongmun_structure_absent",
            f"only {len(families)} 공문 seat family/families recognized "
            f"(minimum {minimum}) — this document is not a 기안문/공문",
            None, families=families))
        return (_verdict(artifact_path, {"families": families}, hard, warn,
                         info, skipped, guide_terms=guide_terms),
                exit_code(hard=hard))

    classification = classify_state(model, vocab)
    state = classification["state"] if mode == "auto" else mode
    classification["mode"] = mode
    classification["state_used"] = state
    classification["families"] = families

    _check_dumun(model, vocab, state, baseline_model, hard, warn, info,
                 skipped)
    _check_gyeoljae(model, vocab, hard, info, skipped)
    _check_gyeolmun(model, vocab, state, hard, warn, info, skipped)
    _check_balsin(model, vocab, state, hard, info)
    _check_seal(model, vocab, baseline_model, hard, info, skipped)
    _check_residue(model, vocab, state, guide_terms, hard, warn, skipped)
    _check_bigo(model, vocab, state, hard, warn, skipped)
    _check_glyphs(model, vocab, state, hard, warn, skipped)
    _check_pack(model, vocab, pack_instance, baseline_model, hard, warn,
                info, skipped)
    _check_baseline_seats(model, vocab, baseline_model, guide_terms, hard,
                          info, skipped)

    return (_verdict(artifact_path, classification, hard, warn, info, skipped,
                     guide_terms=guide_terms), exit_code(hard=hard))


def _verdict(artifact_path, classification, hard, warn, info, skipped,
             guide_terms=()) -> dict:
    return verdict_skeleton(
        str(artifact_path), CHECKER,
        hard=hard, warn=warn,
        extra={
            "artifact": str(artifact_path),
            "document": classification,
            "guide_terms": list(guide_terms),
            "seats": info,
            "skipped": skipped,
        },
        counts={
            "hard": len(hard),
            "warn": len(warn),
            "seats": len(info),
            "skipped": len(skipped),
            "guide_terms": len(guide_terms),
        },
    )


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="deterministic 공문/기안문 structure gate for a filled "
                    "artifact (행정업무 운영·혁신 규정 시행규칙 별지서식)")
    parser.add_argument("artifact", help="hwpx document to check")
    parser.add_argument(
        "--mode", default="auto", choices=MODES,
        help="document state; 'auto' reads it from the document (default)")
    parser.add_argument(
        "--vocabulary", default=None,
        help=f"gongmun vocabulary JSON (default: {DEFAULT_VOCABULARY.name} "
             "shipped with this module)")
    parser.add_argument(
        "--pack", default=None,
        help=f"{PACK_TYPE} pack instance (issuing 기관명/부서/직위 vocabulary)")
    parser.add_argument(
        "--baseline", default=None,
        help="the BLANK form this artifact was filled from; enables the "
             "seat_emptied and seal_slot_removed rules")
    return cli_main(
        parser,
        lambda args: check(
            args.artifact,
            mode=args.mode,
            vocabulary=args.vocabulary,
            pack=args.pack,
            baseline=args.baseline,
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
