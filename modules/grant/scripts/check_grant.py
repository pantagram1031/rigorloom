# -*- coding: utf-8 -*-
"""check_grant.py — deterministic 지원사업 신청 gate for a filled packet.

The 지원사업/공모 신청 family (HWP usage landscape family ⑥) is the one work type
whose submission is a **PACKET, not a document**. A 민원 서식 is one fixed grid; a
기안문 is one 공문; a 표준근로계약서 is one instrument in prose. A 지원사업
submission is a *bundle inside one file*: a 신청서 grid, a flowing 사업계획서, parts
cited by number, per-programme budget tables, and standalone 동의서 sheets. Two
properties follow, and every rule here is one of them:

  1. **Parts reference each other by number.** kstartup cites 별첨 2-1 from three
     different places and carries 【별첨 2-1】 as a section header, so "does this
     citation resolve?" is a question the document can answer about itself.
  2. **Row count is a legitimate degree of freedom.** The applicant EXTENDS the
     budget tables and the rosters — kstartup's own guidance says so out loud
     ('견적서 1개 초과시 표 추가'). This is the sharpest difference from every
     other form family: the geometry rule may compare **column structure and the
     header row** and must never compare a cell count.

This module carries **no Korean literals in code** — every term and pattern lives
in ``references/grant_vocabulary.json``, asserted by
``tests/test_grant_contract.py``.

Rules — see ``skill/references/grant_flow.md`` §4 for the full table; each has a
positive fixture and a still-catches negative in ``tests/``:

  R0  artifact_missing / artifact_malformed / grant_structure_absent
  R1  packet:   packet_reference_dangling                 (no baseline needed)
                packet_section_lost                       (needs --baseline)
  R2  tables:   table_structure_lost, table_column_changed
                                                          (needs --baseline)
  R3  budget:   budget_total_mismatch                     (no baseline needed)
  R4  consent:  consent_unmarked                          (no baseline needed)
                consent_block_lost, consent_option_lost   (needs --baseline)
  R5  human:    signature_seat_lost                       (needs --baseline)
  R6  identity: identity_value_invented, account_number_invented
                                                          (no baseline needed)
  R7  residue:  self_deleting_guide_retained, example_placeholder_retained
                                                          (no baseline needed)
  R8  length:   length_budget_unverified            (always reported skipped)

Seventeen rules in nine groups; **six of them need the blank form** as
``--baseline``, so the module declares ``wants: [baseline]``. Without it those six
report ``skipped: no_baseline`` and the checker still exits 0.

R6 is the privacy rule and it is never gated behind an input the caller might
forget. **The tool never invents an identity number or an account number.** This
family asks for more of them than any other — 주민등록번호, 여권번호,
법인등록번호, 사업자등록번호, 생년월일 — and supplies a value for none.

R8 is a declared dependency rather than a check. The landscape predicted
per-section page budgets ('5쪽 이내'); no corpus form declares one, and a page
count is not derivable from ``Contents/section*.xml`` anyway. So the detector
ships, and the rule says out loud whether it found nothing (``not_declared``) or
found a budget it cannot decide offline (``needs_render``). Guessing a page count
would be worse than either.

Document state decides severity, and this family makes that honestly hard: the
kstartup form ships **pre-filled with worked examples** (budget figures, a marked
``■동의함``), so a marked box and a number in a cell are not evidence that anyone
wrote anything. With a baseline the state comes from what actually changed; with
no baseline it comes from the date seat alone, and the verdict records which
(``document.state_basis``). ``--mode`` forces a state.

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
    verdict_skeleton,
)
import check_residue  # noqa: E402  (core: render-critical XML validation)
import form_inspect  # noqa: E402  (core engine: paragraph/cell scanners)
from hwpx_tables import attr as tbl_attr, scan_tables  # noqa: E402

CHECKER = "check_grant"
VOCABULARY_SCHEMA = "rigorloom-grant-vocabulary/v1"
DEFAULT_VOCABULARY = MODULE_ROOT / "references" / "grant_vocabulary.json"

MODES = ("auto", "blank", "draft", "final")
STATE_BLANK, STATE_DRAFT, STATE_FINAL = "blank", "draft", "final"

#: Patterns applied to a seat's RAW text, where the run of spaces IS the seat.
#: Squeezing first would delete the very thing they look for.
RAW_REGEX_KEYS = (
    "blank_run_re", "unfilled_date_seat_re", "rrn_re", "account_number_re",
)
#: Patterns applied to whitespace-squeezed text, because these forms
#: letter-space their own labels ('기 업 명', '합        계', '주    소').
SQUEEZED_REGEX_KEYS = (
    "packet_header_re", "packet_reference_re", "amount_re", "box_unmarked_re",
    "box_marked_re", "option_group_re", "option_split_re",
    "signature_marker_re", "self_deleting_guide_re", "optional_section_re",
    "example_placeholder_re", "page_budget_re", "char_budget_re",
    "budget_cap_re", "noise_re",
)
REGEX_KEYS = RAW_REGEX_KEYS + SQUEEZED_REGEX_KEYS

#: Positive-integer thresholds the rules read. Every one has a ``_note`` sibling
#: in the vocabulary carrying its measured corpus number.
INT_KEYS = (
    "grid_min_cols", "header_min_labels", "budget_min_addends",
    "family_minimum", "min_options", "account_number_min_digits",
    "optional_lookahead_seats",
)

#: Every rule this checker can name, in the order the docstring groups them.
#: Some are emitted from a loop over a (rule, pattern, shape) table, so grepping
#: the source for finding literals under-counts — this tuple is the inventory,
#: and ``tests/test_grant_contract.py`` holds it to both the source and the flow
#: doc's rule table.
RULES = (
    "artifact_missing", "artifact_malformed", "grant_structure_absent",
    "packet_reference_dangling", "packet_section_lost",
    "table_structure_lost", "table_column_changed",
    "budget_total_mismatch",
    "consent_unmarked", "consent_block_lost", "consent_option_lost",
    "signature_seat_lost",
    "identity_value_invented", "account_number_invented",
    "self_deleting_guide_retained", "example_placeholder_retained",
    "length_budget_unverified",
)

_WS_RE = re.compile(r"\s+")
_SECTION_MEMBER_RE = re.compile(r"^Contents/section\d*\.xml$", re.IGNORECASE)


class GrantError(Exception):
    """Usage-level refusal (exit 2)."""


# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #
def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GrantError(f"{label} not found: {path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GrantError(f"{label} unreadable: {exc}")
    if not isinstance(payload, dict):
        raise GrantError(f"{label} must be a JSON object: {path}")
    return payload


def load_vocabulary(path: Path | str | None = None) -> dict:
    """The family's structural vocabulary, as data (never code literals)."""
    vocabulary = _load_json(Path(path or DEFAULT_VOCABULARY), "vocabulary")
    if vocabulary.get("schema") != VOCABULARY_SCHEMA:
        raise GrantError(
            f"vocabulary schema must be {VOCABULARY_SCHEMA!r} "
            f"(got {vocabulary.get('schema')!r})")
    sections = vocabulary.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise GrantError("vocabulary.sections must be a non-empty object")
    for name, spec in sections.items():
        if not isinstance(spec, dict):
            raise GrantError(f"vocabulary.sections.{name} must be an object")
    for key in REGEX_KEYS:
        if not isinstance(vocabulary.get(key), str) or not vocabulary[key]:
            raise GrantError(f"vocabulary.{key} must be a non-empty string")
        try:
            re.compile(vocabulary[key])
        except re.error as exc:
            raise GrantError(f"vocabulary.{key} is not a valid regex: {exc}")
    for key in INT_KEYS:
        value = vocabulary.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise GrantError(f"vocabulary.{key} must be a positive integer")
    ratio = vocabulary.get("header_match_min_ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) \
            or not 0 < ratio <= 1:
        raise GrantError(
            "vocabulary.header_match_min_ratio must be a number in (0, 1]")
    if not _terms(vocabulary, "packet", "markers"):
        raise GrantError(
            "vocabulary.sections.packet.markers must be a non-empty list — a "
            "packet with no part markers has no packet-integrity rule, which "
            "is this family's distinguishing property")
    if not _terms(vocabulary, "budget", "total_labels"):
        raise GrantError(
            "vocabulary.sections.budget.total_labels must be a non-empty list")
    return vocabulary


def load_fill_map(path: Path | str | None) -> dict | None:
    """The values the OPERATOR declared for this packet, or None.

    Shape handling is core's (``check_residue.load_fill_map``): a bare
    ``{placeholder: value}`` object (the ``preedit.py replace --map`` shape) OR
    a wrapper object carrying a ``fill_map`` member, so ONE file serves this
    checker and ``visual_verify`` alike (T35). Only the values matter here —
    they are what makes an identity or account number "declared" rather than
    "invented".
    """
    if path is None:
        return None
    payload, error = check_residue.load_fill_map(Path(path))
    if error:
        raise GrantError(error)
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float)):
            raise GrantError(
                "fill map must map strings to scalar values "
                f"(offending key {key!r})")
    return payload


def declared_values(fill_map: dict | None) -> list[str]:
    if not fill_map:
        return []
    return [str(value) for value in fill_map.values() if str(value).strip()]


def _terms(vocabulary: dict, section: str, key: str) -> list[str]:
    spec = (vocabulary.get("sections") or {}).get(section) or {}
    value = spec.get(key) or []
    if isinstance(value, str):
        value = [value]
    return [item for item in value if isinstance(item, str) and item.strip()]


def _dedupe(items) -> list:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
# whitespace handling — two domains, and the difference is the point
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _squeeze(text: str) -> str:
    """Drop every whitespace character (term-matching domain)."""
    return _WS_RE.sub("", text or "")


def _contains(text: str, term: str) -> bool:
    return bool(term) and _squeeze(term) in _squeeze(text)


def _findall_sq(pattern: str, text: str) -> list:
    return re.findall(pattern, _squeeze(text))


def _findall_raw(pattern: str, text: str) -> list:
    """Hits over the text AS WRITTEN — blank runs are the seats here."""
    return re.findall(pattern, text or "")


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #
def document_model(path: Path) -> dict:
    """Tables with per-cell text and geometry, plus top-level paragraph text.

    Cell text is the cell's OWN text (nested-table spans removed, via the
    engine's ``_own_cell_body``) and top-level paragraphs come from the
    stack-based scanner with depth-0 table spans removed, so a paragraph that
    merely *holds* a table never absorbs that table's cell text. That matters
    more here than anywhere: the kstartup packet keeps its 【별첨】 headers, its
    작성방법 block and its 동의 questions in top-level paragraphs while 42 tables
    sit between them. XML entities are unescaped.
    """
    tables: list[dict] = []
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        index = 0
        for name in sorted(archive.namelist()):
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
                    cells.append({
                        "addr": list(cell["addr"]) if cell["addr"] else None,
                        "span": list(cell["span"]),
                        "text": " ".join(item for item in texts
                                         if item.strip()),
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


def _own_top_level_texts(xml: str, scanned: list) -> list:
    """Top-level paragraph text with depth-0 table spans removed."""
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


def iter_seats(model: dict):
    """(location, raw text) for every table cell and every top-level paragraph.

    Cells first, in table order, then paragraphs — the order the packet-header
    scanner walks, so a header's ordinal position is stable across a run.
    """
    for table in model["tables"]:
        for cell in table["cells"]:
            if cell["text"].strip():
                yield {"table": table["index"], "addr": cell["addr"]}, \
                    cell["text"]
    for position, text in enumerate(model["paragraphs"]):
        if text.strip():
            yield {"paragraph": position}, text


def haystack(model: dict) -> str:
    """Every seat's text, newline-joined.

    Newline rather than space so a digit ending one seat and a digit opening the
    next never fuse into one long run — that would be a fabricated 계좌번호 the
    packet does not contain.
    """
    return "\n".join(text for _at, text in iter_seats(model))


def _count_raw(pattern: str, model: dict) -> int:
    return sum(len(_findall_raw(pattern, text))
               for _at, text in iter_seats(model))


def _count_sq(pattern: str, model: dict) -> int:
    return sum(len(_findall_sq(pattern, text))
               for _at, text in iter_seats(model))


# --------------------------------------------------------------------------- #
# detectors — every one of them reads the form, not a hardcoded map
# --------------------------------------------------------------------------- #
def packet_headers(model: dict, vocabulary: dict) -> list:
    """Packet SECTION headers: ``【별첨 2-1】`` at the very start of a seat.

    Anchored at the start on purpose. kstartup cites the same section mid-cell
    ('[별첨 2-1] 개인정보 제공 및 활용(제3자 제공)동의서 1부'), and counting that
    as a second header would make a reference resolve against itself.
    """
    pattern = vocabulary["packet_header_re"]
    found = []
    for location, text in iter_seats(model):
        match = re.search(pattern, _squeeze(text))
        if match:
            found.append({"marker": match.group(1), "number": match.group(2),
                          "at": location, "text": _normalize(text)[:80]})
    return found


def packet_references(model: dict, vocabulary: dict) -> list:
    """Citations of a packet part by number, with header matches removed.

    A header's own text matches the reference pattern too, so the header span is
    cut out of each seat before the reference scan — otherwise every section
    would trivially cite itself.
    """
    header_re = vocabulary["packet_header_re"]
    reference_re = vocabulary["packet_reference_re"]
    found = []
    for location, text in iter_seats(model):
        squeezed = _squeeze(text)
        header = re.search(header_re, squeezed)
        if header:
            squeezed = squeezed[header.end():]
        for match in re.finditer(reference_re, squeezed):
            found.append({"marker": match.group(1), "number": match.group(2),
                          "at": location})
    return found


def packet_marker_classes(model: dict, vocabulary: dict) -> dict:
    """marker -> {'headers': [...], 'references': [...], 'internal': bool}.

    Whether a marker class is INTERNAL is read off the document, not declared:
    a class the document carries at least one header for is internal and every
    reference of that class must resolve; a class with no header at all is
    external — it cites a separate file, and the packet cannot be asked to
    contain it. On kstartup that makes 별첨 internal (3 headers) and 붙임
    external (0 headers — 붙임3 and 붙임5 live in the 공고문). Hardcoding either
    way would have failed a pristine form.
    """
    classes: dict = {}
    for marker in _terms(vocabulary, "packet", "markers"):
        classes[marker] = {"headers": [], "references": [], "internal": False}
    for row in packet_headers(model, vocabulary):
        classes.setdefault(row["marker"],
                           {"headers": [], "references": [],
                            "internal": False})["headers"].append(row)
    for row in packet_references(model, vocabulary):
        classes.setdefault(row["marker"],
                           {"headers": [], "references": [],
                            "internal": False})["references"].append(row)
    for spec in classes.values():
        spec["internal"] = bool(spec["headers"])
    return classes


def section_is_optional(model: dict, vocabulary: dict, header: dict) -> bool:
    """Does the form itself license dropping this packet part?

    kstartup writes the licence on the line after the placeholder
    ('※ 해당자에 한함 (없을 시 삭제)'), so the header's own seat plus the next
    ``optional_lookahead_seats`` seats are what is read.
    """
    lookahead = int(vocabulary["optional_lookahead_seats"])
    seats = list(iter_seats(model))
    start = next((index for index, (location, _text) in enumerate(seats)
                  if location == header["at"]), None)
    if start is None:
        return False
    window = seats[start:start + 1 + lookahead]
    return any(_findall_sq(vocabulary["optional_section_re"], text)
               for _at, text in window)


def grid_tables(model: dict, vocabulary: dict) -> list:
    """The tables the extendable-table geometry rule judges.

    A GRID is a table with at least ``grid_min_cols`` columns whose header row —
    the FIRST row carrying at least ``header_min_labels`` non-empty cells — gives
    it a text signature. An extendable table is one whose ROW IS A RECORD, and
    the column floor is what expresses that: a two-column table is a label/value
    pair list, and kstartup's 사업계획서 sections are exactly that shape with a
    prose fill target in the value column — the text the form tells the applicant
    to delete. Pairing on it would fail a correct fill, so they are out of scope
    along with the 25 single-column prose banners.

    The signature is **mark-insensitive**: box glyphs are stripped, because
    marking '□ 1. 기술이전 완료' into '■ 1. 기술이전 완료' must not look like a
    different table.
    """
    minimum_cols = int(vocabulary["grid_min_cols"])
    minimum_labels = int(vocabulary["header_min_labels"])
    grids = []
    for table in model["tables"]:
        if (table["colCnt"] or 0) < minimum_cols:
            continue
        by_row: dict = {}
        for cell in table["cells"]:
            if not cell["addr"]:
                continue
            by_row.setdefault(cell["addr"][0], []).append(cell)
        header_row = None
        signature: list = []
        for row in sorted(by_row):
            labels = [_signature_text(cell["text"], vocabulary)
                      for cell in by_row[row]]
            labels = [item for item in labels if item]
            if len(labels) >= minimum_labels:
                header_row, signature = row, sorted(set(labels))
                break
        if header_row is None:
            continue
        grids.append({
            "index": table["index"], "depth": table["depth"],
            "colCnt": table["colCnt"], "rowCnt": table["rowCnt"],
            "rows": len(by_row), "header_row": header_row,
            "signature": signature,
            # Every row's labels, kept so matching can ask "what does this
            # table look like at the row the BASELINE calls its header" instead
            # of only comparing two independently-derived header rows (T117).
            "labels_by_row": {
                row: sorted({label for label in (
                    _signature_text(cell["text"], vocabulary)
                    for cell in cells) if label})
                for row, cells in by_row.items()},
        })
    return grids


def _signature_text(text: str, vocabulary: dict) -> str:
    """A header cell's identity: squeezed text with selection marks removed."""
    squeezed = _squeeze(text)
    squeezed = re.sub(vocabulary["box_unmarked_re"], "", squeezed)
    squeezed = re.sub(vocabulary["box_marked_re"], "", squeezed)
    return squeezed


def match_grid(wanted: dict, candidates: list, vocabulary: dict) -> dict | None:
    """The artifact grid that IS ``wanted``, or None.

    Pairing is by header-label containment, never by table index: this family
    lets the applicant add tables ('견적서 1개 초과시 표 추가'), and one added
    table shifts every index after it. The best candidate above
    ``header_match_min_ratio`` wins; ties go to the closer column count so two
    tables sharing a header (kstartup ships its 개인정보 consent row twice) pair
    one-to-one rather than both onto the same partner.
    """
    ratio = float(vocabulary["header_match_min_ratio"])
    labels = set(wanted["signature"])
    if not labels:
        return None
    best, best_score = None, 0.0
    for candidate in candidates:
        # Two readings, and the better one wins. A candidate's OWN header row is
        # re-derived per document, so a legitimate fill can move it: the header
        # row is "the first row with >= header_min_labels non-empty cells", and
        # writing a value into a sparse earlier row promotes THAT row, making
        # the operator's own text part of the table's identity. Measured on
        # kstartup table 0 — filling (0,1) moved header_row 1 -> 0 and turned
        # the signature from the form's three labels into
        # ["과제(창업아이템)명", <the filled value>], so the table paired with
        # nothing and was reported deleted (T117). Asking what the candidate
        # looks like at the row the BASELINE calls its header keeps identity on
        # the baseline's side, which is the T49/T100 rule: never judge the
        # artifact by something derived differently on the two sides.
        readings = [set(candidate["signature"])]
        at_baseline_row = candidate.get("labels_by_row", {}).get(
            wanted["header_row"])
        if at_baseline_row:
            readings.append(set(at_baseline_row))
        shared = max(len(labels & reading) / len(labels)
                     for reading in readings)
        if shared < ratio:
            continue
        score = shared + (0.001 if candidate["colCnt"] == wanted["colCnt"]
                          else 0.0)
        if score > best_score:
            best, best_score = candidate, score
    return best


def budget_totals(model: dict, vocabulary: dict) -> list:
    """Every 합계 cell, with the column sum that must equal it.

    A 합계 row is found by label, and each numeric cell in that row is compared
    against the sum of the numeric cells ABOVE it in the same column address.
    Rows are not enumerated and no row count is assumed — which is the whole
    point in a family where the applicant adds rows.
    """
    labels = _terms(vocabulary, "budget", "total_labels")
    amount_re = vocabulary["amount_re"]
    minimum = int(vocabulary["budget_min_addends"])
    found = []
    for table in model["tables"]:
        addressed = [cell for cell in table["cells"] if cell["addr"]]
        total_rows = sorted({
            cell["addr"][0] for cell in addressed
            if any(_contains(cell["text"], label) for label in labels)})
        for row in total_rows:
            for cell in addressed:
                if cell["addr"][0] != row:
                    continue
                total = _amount(cell["text"], amount_re)
                if total is None:
                    continue
                column = cell["addr"][1]
                addends = [
                    _amount(other["text"], amount_re) for other in addressed
                    if other["addr"][1] == column and other["addr"][0] < row]
                addends = [value for value in addends if value is not None]
                found.append({
                    "at": {"table": table["index"], "addr": cell["addr"]},
                    "total": total, "sum": sum(addends),
                    "addends": len(addends),
                    "decidable": len(addends) >= minimum,
                })
    return found


def _amount(text: str, amount_re: str) -> int | None:
    """The integer a cell IS, or None when the cell is prose about a number."""
    squeezed = _squeeze(text)
    if not re.match(amount_re, squeezed):
        return None
    try:
        return int(squeezed.replace(",", ""))
    except ValueError:  # pragma: no cover — amount_re admits only digits/commas
        return None


def consent_groups(model: dict, vocabulary: dict) -> list:
    """Consent CHOICES: an option group in a seat whose UNIT carries a 동의 label.

    The 동의 label is looked for in the seat's *container* — the whole table for
    a cell, the paragraph itself for a paragraph — because a form may put the
    label and the choice in adjacent cells. On the corpus that changes nothing
    (both readings find exactly 2 groups in kstartup, 2 in pps-jeongbogonggae, 0
    in pps-hyeopeop), and it is what makes a '동의 여부' cell beside a
    '( □예  □아니오 )' cell readable.

    Two counters, and the glyph one wins when it applies. kstartup's
    '( ■동의함    □동의하지 않음 )' has no separator and is counted by its two
    glyphs; pps-jeongbogonggae's '(예,  아니오)' has no glyph and is counted by
    exact token match. Exact rather than substring is load-bearing: '예' is a
    substring of 예비창업자 / 예시 / 예정, and '(예비)창업자 부담금율' is not a
    consent choice.
    """
    consent_labels = _terms(vocabulary, "consent", "labels")
    option_labels = {_squeeze(item)
                     for item in _terms(vocabulary, "consent", "option_labels")}
    required_labels = _terms(vocabulary, "consent", "required_labels")
    minimum = int(vocabulary["min_options"])
    containers = _seat_containers(model)
    groups = []
    for location, text in iter_seats(model):
        container = containers.get(_key(location), _squeeze(text))
        if not any(_contains(container, label) for label in consent_labels):
            continue
        required = any(_contains(container, label)
                       for label in required_labels)
        for match in re.finditer(vocabulary["option_group_re"], _squeeze(text)):
            inner = match.group(1)
            marked = len(re.findall(vocabulary["box_marked_re"], inner))
            unmarked = len(re.findall(vocabulary["box_unmarked_re"], inner))
            glyphs = marked + unmarked
            if glyphs >= minimum:
                options, basis = glyphs, "glyphs"
            else:
                tokens = [_strip_glyphs(token, vocabulary)
                          for token in re.split(vocabulary["option_split_re"],
                                                inner)]
                options = sum(1 for token in tokens if token in option_labels)
                basis = "tokens"
            if options < minimum:
                continue
            groups.append({"at": location, "options": options, "basis": basis,
                           "marked": marked, "glyph_bearing": glyphs >= minimum,
                           "required": required, "text": _normalize(inner)[:60]})
    return groups


def _strip_glyphs(text: str, vocabulary: dict) -> str:
    stripped = re.sub(vocabulary["box_marked_re"], "", _squeeze(text))
    return re.sub(vocabulary["box_unmarked_re"], "", stripped)


def _key(location: dict):
    return (location.get("table"), tuple(location["addr"])
            if location.get("addr") else None, location.get("paragraph"))


def _seat_containers(model: dict) -> dict:
    """seat key -> the squeezed text of the unit the seat lives in.

    A cell's container is its whole TABLE, a paragraph's is itself. This is what
    makes a consent choice's ``required`` flag readable: kstartup writes
    '필수항목' in one cell of a row and the option group in the next.
    """
    containers: dict = {}
    for table in model["tables"]:
        joined = _squeeze(" ".join(cell["text"] for cell in table["cells"]))
        for cell in table["cells"]:
            containers[(table["index"],
                        tuple(cell["addr"]) if cell["addr"] else None,
                        None)] = joined
    for position, text in enumerate(model["paragraphs"]):
        containers[(None, None, position)] = _squeeze(text)
    return containers


def signature_marker_count(model: dict, vocabulary: dict) -> int:
    """(서명 또는 인) / (서명) / (인) markers, counted not located.

    Counted because they live in top-level paragraphs, and a paragraph has no
    stable address in a family that adds lines by design.
    """
    return _count_sq(vocabulary["signature_marker_re"], model)


def addressee_count(model: dict, vocabulary: dict) -> int:
    labels = _terms(vocabulary, "addressee", "labels")
    return sum(1 for _at, text in iter_seats(model)
               if any(_contains(text, label) for label in labels))


def identity_labels_present(model: dict, vocabulary: dict) -> list:
    text = haystack(model)
    return [label for label in _terms(vocabulary, "identity", "labels")
            if _contains(text, label)]


def declared_caps(model: dict, vocabulary: dict) -> list:
    """Monetary caps the form states about its own budget — reported, not gated.

    See ``budget_cap_note`` in the vocabulary: binding a cap to a figure needs a
    guess this checker refuses to make.
    """
    found = []
    for _at, text in iter_seats(model):
        for match in re.finditer(vocabulary["budget_cap_re"], _squeeze(text)):
            found.append(match.group(1) or match.group(2))
    return _dedupe(found)


def length_budgets(model: dict, vocabulary: dict) -> dict:
    """Page and character budgets the form declares, if any."""
    text = _squeeze(haystack(model))
    return {"pages": _dedupe(re.findall(vocabulary["page_budget_re"], text)),
            "chars": _dedupe(re.findall(vocabulary["char_budget_re"], text))}


def rule_families(model: dict, vocabulary: dict) -> list:
    """Which 지원사업 packet seat families the document actually carries."""
    families = []
    classes = packet_marker_classes(model, vocabulary)
    text = haystack(model)
    if (any(spec["headers"] or spec["references"] for spec in classes.values())
            or any(_contains(text, label) for label
                   in _terms(vocabulary, "packet", "attachment_list_labels"))):
        families.append("packet")
    if budget_totals(model, vocabulary):
        families.append("budget")
    if consent_groups(model, vocabulary):
        families.append("consent")
    if signature_marker_count(model, vocabulary):
        families.append("signature")
    if addressee_count(model, vocabulary):
        families.append("addressee")
    if grid_tables(model, vocabulary):
        families.append("grid")
    return families


# --------------------------------------------------------------------------- #
# state classification — and an honest account of what it cannot know
# --------------------------------------------------------------------------- #
def classify_state(model: dict, vocabulary: dict,
                   baseline_model: dict | None = None) -> dict:
    """Blank / draft / final, and which evidence decided it.

    This family makes state genuinely hard: the kstartup form ships **pre-filled
    with worked examples** — nine budget figures, a marked ``■동의함``, example
    prose — so neither a marked box nor a number in a cell is evidence that
    anyone wrote anything.

    ``baseline_diff``    with a blank form, ``written`` is what actually changed:
                         a seat the blank form carries whose text no longer
                         reads the same. Set-based, never positional — this
                         family adds rows and paragraphs on purpose.
    ``date_seat_only``   with no blank form there is no such evidence, so state
                         falls back to the date seat: ``final`` once no unfilled
                         date seat remains, ``blank`` while one does. The basis
                         is reported so nobody reads ``blank`` as a claim that
                         the packet is pristine.
    """
    unfilled_dates = _count_raw(vocabulary["unfilled_date_seat_re"], model)
    marked = sum(row["marked"] for row in consent_groups(model, vocabulary))
    changed = 0
    basis = "date_seat_only"
    if baseline_model is not None:
        basis = "baseline_diff"
        current = {_squeeze(text) for _at, text in iter_seats(model)}
        changed = sum(1 for _at, text in iter_seats(baseline_model)
                      if _squeeze(text) not in current)
    written = bool(changed or not unfilled_dates)
    if not written:
        state = STATE_BLANK
    elif unfilled_dates:
        state = STATE_DRAFT
    else:
        state = STATE_FINAL
    return {"state": state, "state_basis": basis,
            "seats_changed": changed,
            "unfilled_date_seats": unfilled_dates,
            "marked_consent_options": marked,
            "blank_runs": _count_raw(vocabulary["blank_run_re"], model)}


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _finding(code: str, msg: str, at, **extra) -> dict:
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


def _check_packet(model, vocabulary, baseline_model, hard, warn, info, skipped):
    """R1 — a 붙임/별첨 citation must land on a part that exists."""
    classes = packet_marker_classes(model, vocabulary)

    # ── R1a: dangling internal reference. No baseline needed: the packet is
    # being asked about ITSELF, and that is the strongest form of this rule.
    internal = {marker: spec for marker, spec in classes.items()
                if spec["internal"]}
    if not internal:
        skipped.append({"rule": "packet_reference_dangling",
                        "reason": "no_internal_marker_class"})
    for marker, spec in internal.items():
        numbers = {row["number"] for row in spec["headers"]}
        for reference in spec["references"]:
            if reference["number"] in numbers:
                info.append({"seat": "packet_reference", "state": "resolved",
                             "marker": marker, "number": reference["number"],
                             "at": reference["at"]})
                continue
            hard.append(_finding(
                "packet_reference_dangling",
                "the packet cites a part by number and carries no section for "
                "it — a 붙임/별첨 reference whose target is gone tells the "
                "reviewer to look for a page that is not in the file",
                reference["at"], marker=marker, number=reference["number"],
                headers=sorted(numbers)))
    for marker, spec in classes.items():
        if spec["internal"] or not spec["references"]:
            continue
        # A class with references and NO header cites separate files. kstartup's
        # 붙임3 / 붙임5 are 공고문 attachments; demanding them here would fail
        # the pristine form.
        info.append({"seat": "packet_reference", "state": "external",
                     "marker": marker,
                     "numbers": sorted({row["number"]
                                        for row in spec["references"]})})

    # ── R1b: a section the blank form carries is gone ──────────────────────
    if baseline_model is None:
        skipped.append({"rule": "packet_section_lost", "reason": "no_baseline"})
        return
    baseline_headers = packet_headers(baseline_model, vocabulary)
    if not baseline_headers:
        skipped.append({"rule": "packet_section_lost", "reason": "seat_absent"})
        return
    present = {(row["marker"], row["number"])
               for row in packet_headers(model, vocabulary)}
    for header in baseline_headers:
        key = (header["marker"], header["number"])
        if key in present:
            info.append({"seat": "packet_section", "state": "present",
                         "marker": key[0], "number": key[1]})
            continue
        optional = section_is_optional(baseline_model, vocabulary, header)
        row = _finding(
            "packet_section_lost",
            "a 붙임/별첨 section the blank form carries is gone from the "
            "packet — the part list is what the reviewer checks the "
            "submission against",
            header["at"], marker=key[0], number=key[1], optional=optional)
        (warn if optional else hard).append(row)


def _check_tables(model, vocabulary, baseline_model, hard, info, skipped):
    """R2 — the extendable-table geometry rule, and why it is not a cell count.

    Adding rows to a budget table or a roster is what this family's applicant
    DOES. So the comparison is the column count and the header row, and a row
    count that moved is reported as an extension rather than judged.
    """
    grids = grid_tables(model, vocabulary)
    if baseline_model is None:
        for rule in ("table_structure_lost", "table_column_changed"):
            skipped.append({"rule": rule, "reason": "no_baseline"})
        info.append({"seat": "grid_inventory", "state": "reported",
                     "grids": len(grids)})
        return
    baseline_grids = grid_tables(baseline_model, vocabulary)
    if not baseline_grids:
        for rule in ("table_structure_lost", "table_column_changed"):
            skipped.append({"rule": rule, "reason": "seat_absent"})
        return
    available = list(grids)
    for wanted in baseline_grids:
        match = match_grid(wanted, available, vocabulary)
        if match is None:
            hard.append(_finding(
                "table_structure_lost",
                "a table the blank form carries has no counterpart in the "
                "packet — its header row is gone, so the grid was deleted or "
                "rewritten rather than filled",
                {"table": wanted["index"]},
                signature=wanted["signature"][:6],
                colCnt=wanted["colCnt"]))
            continue
        available.remove(match)
        if match["colCnt"] != wanted["colCnt"]:
            hard.append(_finding(
                "table_column_changed",
                "a table's COLUMN structure changed — adding rows to a budget "
                "table or a roster is what this family's applicant does and is "
                "fine; adding or dropping a column changes what the reviewer "
                "is reading",
                {"table": match["index"]}, baseline=wanted["colCnt"],
                artifact=match["colCnt"],
                signature=wanted["signature"][:6]))
            continue
        info.append({"seat": "grid", "state": "extendable",
                     "at": {"table": match["index"]},
                     "colCnt": match["colCnt"],
                     "rows_baseline": wanted["rows"],
                     "rows_artifact": match["rows"],
                     "rows_added": match["rows"] - wanted["rows"]})


def _check_budget(model, vocabulary, hard, info, skipped):
    """R3 — a 합계 must equal the sum of its column.

    The family's one genuinely numeric invariant, and it needs no baseline: the
    document is being checked against its own arithmetic.
    """
    totals = budget_totals(model, vocabulary)
    if not totals:
        skipped.append({"rule": "budget_total_mismatch",
                        "reason": "seat_absent"})
        return
    for row in totals:
        if not row["decidable"]:
            skipped.append({"rule": "budget_total_mismatch",
                            "reason": "no_addends", "at": row["at"],
                            "total": row["total"]})
            continue
        if row["total"] != row["sum"]:
            hard.append(_finding(
                "budget_total_mismatch",
                "a 합계 cell does not equal the sum of its column — a 지원사업 "
                "budget is read by someone who adds it up, and a total that "
                "does not add up is a rejected application",
                row["at"], total=row["total"], column_sum=row["sum"],
                addends=row["addends"]))
        else:
            info.append({"seat": "budget_total", "state": "balanced",
                         "at": row["at"], "total": row["total"],
                         "addends": row["addends"]})
    caps = declared_caps(model, vocabulary)
    if caps:
        info.append({"seat": "budget_cap", "state": "declared", "caps": caps})


def _check_consent(model, vocabulary, state, baseline_model, hard, warn, info,
                   skipped):
    """R4 — the 동의서 is a document with a legal effect, not a neutral table."""
    groups = consent_groups(model, vocabulary)

    # ── R4a: an unmarked consent. Decidable without a baseline. ────────────
    glyph_groups = [row for row in groups if row["glyph_bearing"]]
    if not glyph_groups:
        skipped.append({"rule": "consent_unmarked",
                        "reason": "no_mark_glyphs" if groups else "seat_absent",
                        "groups": len(groups)})
    elif state == STATE_BLANK:
        skipped.append({"rule": "consent_unmarked",
                        "reason": "document_state_blank",
                        "groups": len(glyph_groups)})
    else:
        for row in glyph_groups:
            if row["marked"]:
                info.append({"seat": "consent", "state": "marked",
                             "at": row["at"], "options": row["options"],
                             "required": row["required"]})
                continue
            finding = _finding(
                "consent_unmarked",
                "a consent choice the packet carries has no option marked — an "
                "unmarked required consent is a submission the receiving body "
                "cannot act on, and marking it is the applicant's decision to "
                "make, never the tool's",
                row["at"], options=row["options"], required=row["required"])
            (hard if row["required"] and state == STATE_FINAL
             else warn).append(finding)

    if baseline_model is None:
        skipped.append({"rule": "consent_block_lost", "reason": "no_baseline"})
        skipped.append({"rule": "consent_option_lost", "reason": "no_baseline"})
        return

    baseline_groups = consent_groups(baseline_model, vocabulary)
    if not baseline_groups:
        skipped.append({"rule": "consent_block_lost", "reason": "seat_absent"})
        skipped.append({"rule": "consent_option_lost", "reason": "seat_absent"})
        return
    if len(groups) < len(baseline_groups):
        hard.append(_finding(
            "consent_block_lost",
            "a consent block the blank form carries is gone — a packet that "
            "drops a 동의서 has not been given the consent it needs, whatever "
            "the rest of it says",
            None, baseline=len(baseline_groups), artifact=len(groups)))
    else:
        info.append({"seat": "consent_block", "state": "present",
                     "groups": len(groups)})
    baseline_options = sum(row["options"] for row in baseline_groups)
    options = sum(row["options"] for row in groups)
    if options < baseline_options:
        hard.append(_finding(
            "consent_option_lost",
            "the packet offers fewer consent options than the blank form — "
            "deleting the refuse option manufactures a consent nobody gave",
            None, baseline=baseline_options, artifact=options))
    else:
        info.append({"seat": "consent_option", "state": "preserved",
                     "options": options})


def _check_human(model, vocabulary, baseline_model, hard, info, skipped):
    """R5 — the signature seats stay for the humans who sign the packet."""
    markers = signature_marker_count(model, vocabulary)
    if baseline_model is None:
        skipped.append({"rule": "signature_seat_lost", "reason": "no_baseline"})
        info.append({"seat": "signature", "state": "reported",
                     "count": markers})
        return
    baseline_markers = signature_marker_count(baseline_model, vocabulary)
    if not baseline_markers:
        skipped.append({"rule": "signature_seat_lost",
                        "reason": "seat_absent"})
        return
    if markers < baseline_markers:
        hard.append(_finding(
            "signature_seat_lost",
            "a (서명 또는 인) / (인) seat the blank form carries is gone — a "
            "지원사업 packet is signed once per sheet and every sheet's seat "
            "stays for the human",
            None, baseline=baseline_markers, artifact=markers))
    else:
        info.append({"seat": "signature", "state": "reserved",
                     "count": markers})


def _check_identity(model, vocabulary, baseline_model, fill_map, hard, info):
    """R6 — the privacy rule: the tool never invents a personal number.

    Never gated behind a baseline. This family asks for more identity numbers
    than any other and supplies a value for none of them, so a
    주민등록번호-shaped or account-shaped value nobody declared is a finding on
    its own evidence.
    """
    declared = declared_values(fill_map)
    floor = int(vocabulary["account_number_min_digits"])
    for rule, key, shape in (
            ("identity_value_invented", "rrn_re", "rrn"),
            ("account_number_invented", "account_number_re", "account_like"),
    ):
        found = _dedupe(value for _at, text in iter_seats(model)
                        for value in _findall_raw(vocabulary[key], text))
        if shape == "account_like":
            found = [value for value in found
                     if sum(char.isdigit() for char in value) >= floor
                     and not _findall_raw(vocabulary["rrn_re"], value)]
        allowed = set()
        for value in declared:
            allowed.update(_findall_raw(vocabulary[key], value))
        if baseline_model is not None:
            for _at, text in iter_seats(baseline_model):
                allowed.update(_findall_raw(vocabulary[key], text))
        offenders = [value for value in found if value not in allowed]
        for _value in offenders:
            hard.append(_finding(
                rule,
                "a personal-number-shaped value appears in the packet and the "
                "operator did not declare it — 주민등록번호, 여권번호, "
                "사업자등록번호 and 계좌번호 are never synthesized, and an "
                "empty seat is the correct output",
                None, shape=shape, declared_values=len(declared)))
        if not offenders:
            info.append({"seat": shape, "state": "none_undeclared",
                         "present": len(found)})
    labels = identity_labels_present(model, vocabulary)
    if labels:
        info.append({"seat": "identity_seat", "state": "reported",
                     "labels": labels})


def _check_residue(model, vocabulary, state, hard, warn, info, skipped):
    """R7 — what the form told the applicant to remove before submitting."""
    guide = [at for at, text in iter_seats(model)
             if _findall_sq(vocabulary["self_deleting_guide_re"], text)]
    placeholders = [at for at, text in iter_seats(model)
                    if _findall_sq(vocabulary["example_placeholder_re"], text)]
    for rule, hits, message in (
            ("self_deleting_guide_retained", guide,
             "the form's own instruction to delete its guidance is still in "
             "the packet — the sentence includes itself ('해당 안내를 포함한'), "
             "so its survival means the guide text went out with the "
             "submission"),
            ("example_placeholder_retained", placeholders,
             "the form's worked-example stand-ins (~~~~, ㅇㅇㅇ) are still in "
             "the packet — those are the places the applicant's own words and "
             "name go"),
    ):
        if state == STATE_BLANK:
            skipped.append({"rule": rule, "reason": "document_state_blank",
                            "seats": len(hits)})
            continue
        if not hits:
            info.append({"seat": rule, "state": "clean"})
            continue
        row = _finding(rule, message, hits[0], seats=len(hits))
        (hard if state == STATE_FINAL else warn).append(row)


def _check_length_budget(model, vocabulary, info, skipped):
    """R8 — the declared dependency, stated instead of guessed.

    The landscape predicts per-section page budgets for this family ('5쪽 이내').
    No corpus form declares one, and a page count is not derivable from
    ``Contents/section*.xml`` — it needs a render. So this rule never passes and
    never fails: it says which of the two it is.
    """
    budgets = length_budgets(model, vocabulary)
    if not budgets["pages"] and not budgets["chars"]:
        skipped.append({"rule": "length_budget_unverified",
                        "reason": "not_declared"})
        return
    info.append({"seat": "length_budget", "state": "declared", **budgets})
    if budgets["pages"]:
        skipped.append({"rule": "length_budget_unverified",
                        "reason": "needs_render", "pages": budgets["pages"],
                        "dependency": "pipeline/scripts/visual_verify.py "
                                      "--expectations (page_budget)"})
    if budgets["chars"]:
        skipped.append({"rule": "length_budget_unverified",
                        "reason": "needs_section_scoping",
                        "chars": budgets["chars"]})


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
    except GrantError as exc:
        return usage_error(str(artifact_path), CHECKER, str(exc))

    hard: list = []
    warn: list = []
    info: list = []
    skipped: list = []

    # Loud-failure contract (shared with check_residue): a missing pinned target
    # is a HARD finding, never a silent pass.
    if not artifact_path.is_file():
        hard.append(_finding(
            "artifact_missing",
            "pinned artifact path does not exist — refusing to pass a "
            "지원사업 신청 gate against a missing target",
            str(artifact_path)))
        return (_verdict(artifact_path, None, hard, warn, info, skipped),
                exit_code(hard=hard))
    if not zipfile.is_zipfile(artifact_path):
        return usage_error(
            str(artifact_path), CHECKER,
            "artifact is not an hwpx (zip) document — 지원사업 신청 checks read "
            "Contents/section*.xml")

    # Validity precedes structure: a malformed section renders BLANK in Hancom,
    # so judging its text would certify an unopenable packet.
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
                f"XML ({row['error']}) — 지원사업 신청 structure checks skipped",
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
    minimum = int(vocab["family_minimum"])
    if len(families) < minimum:
        hard.append(_finding(
            "grant_structure_absent",
            f"only {len(families)} 지원사업 신청 seat family/families "
            f"recognized (minimum {minimum}) — this document is not a "
            "지원사업 신청 packet",
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
    classification["fill_map_declared"] = len(declared_values(declared_map))

    _check_packet(model, vocab, baseline_model, hard, warn, info, skipped)
    _check_tables(model, vocab, baseline_model, hard, info, skipped)
    _check_budget(model, vocab, hard, info, skipped)
    _check_consent(model, vocab, state, baseline_model, hard, warn, info,
                   skipped)
    _check_human(model, vocab, baseline_model, hard, info, skipped)
    _check_identity(model, vocab, baseline_model, declared_map, hard, info)
    _check_residue(model, vocab, state, hard, warn, info, skipped)
    _check_length_budget(model, vocab, info, skipped)

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
        description="deterministic 지원사업 신청 gate for a filled packet "
                    "(신청서 + 사업계획서 + 붙임/별첨 + 동의서)")
    parser.add_argument("artifact", help="hwpx packet to check")
    parser.add_argument(
        "--mode", default="auto", choices=MODES,
        help="document state; 'auto' reads it from the document (default)")
    parser.add_argument(
        "--vocabulary", default=None,
        help=f"grant vocabulary JSON (default: {DEFAULT_VOCABULARY.name} "
             "shipped with this module)")
    parser.add_argument(
        "--baseline", default=None,
        help="the BLANK form this packet was filled from; enables the "
             "preservation rules (붙임/별첨 sections, table column structure, "
             "consent blocks and options, signature seats)")
    parser.add_argument(
        "--fill-map", dest="fill_map", default=None,
        help="the {placeholder: value} map the OPERATOR declared for this "
             "packet — a bare map (preedit.py replace --map) or an object "
             "with a 'fill_map' member (visual_verify --expectations); "
             "either shape is accepted. Values here are what makes a "
             "personal number declared rather than invented")
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
