# -*- coding: utf-8 -*-
"""check_hr.py — deterministic 계약·인사 서식 gate for a filled artifact.

The 계약·인사 family (HWP usage landscape family ⑦, 고용노동부 표준근로계약서) is
the one work type in the landscape whose document **is** the legal instrument.
A 민원 서식 is a fixed grid whose printed guide text must survive; a 공문's
별지서식 guide vocabulary must be consumed. A 표준근로계약서 is neither: it is
numbered clause prose that carries the 근로기준법 제17조 서면 명시 의무 in its
own words, and every rule here follows from that:

    8. 근로계약서 교부
      - 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의
        교부요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)

Lose that sentence and the document stops being the thing it claims to be. This
module carries **no Korean literals in code** — every term and pattern lives in
``references/hr_vocabulary.json``, asserted by ``tests/test_hr_contract.py``.

Rules — see ``skill/references/hr_flow.md`` §3 for the full table; each has a
positive fixture and a still-catches negative in ``tests/``:

  R0  artifact_missing / artifact_malformed / hr_structure_absent
  R1  skeleton:  clause_block_lost, clause_lost, clause_renumbered
                                                            (needs --baseline)
  R2  variants:  contract_variant_lost                       (needs --baseline)
  R3  seats:     clause_text_consumed, option_slot_lost      (needs --baseline)
                 seat_unfilled                       (reported, never invented)
  R4  parties:   party_block_lost, signature_marker_lost     (needs --baseline)
                 party_half_filled                        (no baseline needed)
  R5  statute:   statute_reference_lost, statute_reference_invented
                                                            (needs --baseline)
  R6  version:   template_version_mixed                   (no baseline needed)
                 template_version_changed                  (needs --baseline)
  R7  identity:  identity_value_invented, personal_number_invented
                                                         (no baseline needed)
                 identity_seat_autofilled                  (needs --baseline)

Twenty rules in eight groups; **twelve of them need the blank form** as
``--baseline``, so the module declares ``wants: [baseline]``. Without it those
twelve report ``skipped: no_baseline`` and the checker still exits 0.

R7 is the privacy rule and it is never gated behind an input the caller might
forget. **The tool never invents an identity number or an account number.** A
주민등록번호-shaped value the operator did not declare in ``--fill-map`` is HARD;
so is any hyphen-grouped or bare digit run carrying at least
``personal_number_min_digits`` digits — the 계좌번호 shape, for which this family
has no seat at all, only the 지급방법 clause naming an account.

R3's other half is the family's own asymmetry: an **unfilled** seat is
*reported*, never a HARD finding. Pressuring a filler to make the report go away
is how a tool ends up inventing a 임금지급일 nobody gave it.

Document state decides severity, and the document says which state it is in. A
pristine pack has no marked slot and still shows its unfilled ``년 월 일`` seat,
so ``--mode auto`` classifies it ``blank``. ``draft`` = something was written but
the date seat is still unfilled. ``final`` = no unfilled date seat remains.
``--mode`` forces a state.

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
from hwpx_tables import scan_tables  # noqa: E402

CHECKER = "check_hr"

#: This checker's rule inventory. Needed so a rule that never appears in any
#: bucket can be reported ``clean`` rather than by silence — the convention T118
#: retired. DERIVED, not remembered: a regression parses this module's own
#: ``_finding("<name>"`` and ``{"rule": "<name>"}`` literals and asserts set
#: equality, so adding a rule without listing it here fails.
RULES = (
    "artifact_malformed", "artifact_missing", "clause_block_lost",
    "clause_lost", "clause_renumbered", "clause_text_consumed",
    "contract_variant_lost", "hr_structure_absent",
    "identity_seat_autofilled", "option_slot_lost", "party_block_lost",
    "party_half_filled", "seat_unfilled", "signature_marker_lost",
    "statute_reference_invented", "statute_reference_lost",
    "template_version_changed", "template_version_mixed",
)
VOCABULARY_SCHEMA = "rigorloom-hr-vocabulary/v1"
DEFAULT_VOCABULARY = MODULE_ROOT / "references" / "hr_vocabulary.json"

MODES = ("auto", "blank", "draft", "final")
STATE_BLANK, STATE_DRAFT, STATE_FINAL = "blank", "draft", "final"

#: Patterns applied to a seat's RAW text, where the run of spaces IS the seat.
#: Squeezing first would delete the very thing they look for.
RAW_REGEX_KEYS = (
    "blank_run_re", "stencil_split_re", "unmarked_slot_re", "marked_slot_re",
    "mark_glyph_re", "unfilled_date_seat_re", "unfilled_time_seat_re",
    "clause_head_re", "rrn_re", "personal_number_re",
)
#: Patterns applied to whitespace-squeezed text, because the form letter-spaces
#: its own labels ('근 무 장 소', '대 표 자', '임  금').
SQUEEZED_REGEX_KEYS = (
    "clause_label_stop_re", "signature_marker_re", "statute_article_re",
    "noise_re",
)
REGEX_KEYS = RAW_REGEX_KEYS + SQUEEZED_REGEX_KEYS

_WS_RE = re.compile(r"\s+")
_SECTION_MEMBER_RE = re.compile(r"^Contents/section\d*\.xml$", re.IGNORECASE)


class HrError(Exception):
    """Usage-level refusal (exit 2)."""


# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #
def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HrError(f"{label} not found: {path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HrError(f"{label} unreadable: {exc}")
    if not isinstance(payload, dict):
        raise HrError(f"{label} must be a JSON object: {path}")
    return payload


def load_vocabulary(path: Path | str | None = None) -> dict:
    """The family's structural vocabulary, as data (never code literals)."""
    vocabulary = _load_json(Path(path or DEFAULT_VOCABULARY), "vocabulary")
    if vocabulary.get("schema") != VOCABULARY_SCHEMA:
        raise HrError(
            f"vocabulary schema must be {VOCABULARY_SCHEMA!r} "
            f"(got {vocabulary.get('schema')!r})")
    sections = vocabulary.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise HrError("vocabulary.sections must be a non-empty object")
    for name, spec in sections.items():
        if not isinstance(spec, dict):
            raise HrError(f"vocabulary.sections.{name} must be an object")
    for key in REGEX_KEYS:
        if not isinstance(vocabulary.get(key), str) or not vocabulary[key]:
            raise HrError(f"vocabulary.{key} must be a non-empty string")
        try:
            re.compile(vocabulary[key])
        except re.error as exc:
            raise HrError(f"vocabulary.{key} is not a valid regex: {exc}")
    versions = vocabulary.get("versions")
    if not isinstance(versions, dict):
        raise HrError("vocabulary.versions must be an object")
    named = version_names(vocabulary)
    if len(named) < 2:
        raise HrError(
            "vocabulary.versions must declare at least two versions — the "
            "2013/2025 pair is this family's distinguishing feature and a "
            "single-version table cannot detect a splice")
    for name in named:
        markers = _markers(vocabulary, name)
        if not markers:
            raise HrError(f"vocabulary.versions.{name}.markers must be a "
                          "non-empty list of strings")
    for key in ("clause_label_max_chars", "contract_title_max_chars",
                "identity_seat_max_chars", "stencil_fragment_min_chars",
                "personal_number_min_digits", "family_minimum",
                "identity_value_min_length"):
        value = vocabulary.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise HrError(f"vocabulary.{key} must be a positive integer")
    return vocabulary


def load_fill_map(path: Path | str | None) -> dict | None:
    """The values the OPERATOR declared for this document, or None.

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
        raise HrError(error)
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float)):
            raise HrError(
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


def version_names(vocabulary: dict) -> list[str]:
    """Declared template versions, in declaration order (``_note`` skipped)."""
    return [name for name, spec in (vocabulary.get("versions") or {}).items()
            if not name.startswith("_") and isinstance(spec, dict)]


def _markers(vocabulary: dict, version: str) -> list[str]:
    spec = (vocabulary.get("versions") or {}).get(version) or {}
    value = spec.get("markers") or []
    return [item for item in value if isinstance(item, str) and item.strip()]


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


def _findall_sq(pattern: str, text: str) -> list[str]:
    return re.findall(pattern, _squeeze(text))


def _findall_raw(pattern: str, text: str) -> list[str]:
    """Hits over the text AS WRITTEN — blank runs are the seats here."""
    return re.findall(pattern, text or "")


def residual_text(text: str, terms, vocabulary: dict) -> str:
    """What is left of ``text`` once the given terms and layout noise go."""
    remainder = _squeeze(text)
    for term in sorted((item for item in terms if item), key=len, reverse=True):
        remainder = remainder.replace(_squeeze(term), " ")
    remainder = re.sub(vocabulary["signature_marker_re"], " ", remainder)
    remainder = re.sub(vocabulary["noise_re"], " ", remainder)
    return remainder.strip()


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #
def document_model(path: Path) -> dict:
    """Top-level paragraphs and table cells, each with its text AS WRITTEN.

    Paragraph text comes from the stack-based scanner with depth-0 table spans
    removed, so a paragraph that merely *holds* a table never absorbs that
    table's cell text — this family keeps almost everything in top-level
    paragraphs, so getting that wrong would collapse the whole document into one
    string. Cell text is the cell's OWN text (nested-table spans removed). XML
    entities are unescaped, and **runs are joined without a separator**: the
    2013 pack splits '근로기준법 제17조' across runs and a rule that reads it must
    see the sentence, not the fragments.
    """
    paragraphs: list[str] = []
    cells: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        index = 0
        for name in sorted(archive.namelist()):
            if not _SECTION_MEMBER_RE.match(name.replace("\\", "/")):
                continue
            xml = archive.read(name).decode("utf-8", errors="replace")
            scanned = scan_tables(xml)
            for table in scanned:
                for cell in table["cells"]:
                    body = form_inspect._own_cell_body(xml, cell, scanned)
                    texts = [html.unescape(para["text"])
                             for para in form_inspect._paragraphs(body, {})]
                    joined = " ".join(item for item in texts if item.strip())
                    if joined.strip():
                        cells.append({
                            "table": index,
                            "addr": list(cell["addr"]) if cell["addr"] else None,
                            "depth": table["depth"],
                            "text": joined,
                        })
                index += 1
            paragraphs.extend(_own_top_level_texts(xml))
    return {"paragraphs": [text for text in paragraphs if text.strip()],
            "cells": cells}


def _own_top_level_texts(xml: str) -> list[str]:
    """Top-level paragraph text with depth-0 table spans removed."""
    scanned = scan_tables(xml)
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


def iter_seats(model: dict):
    """(location, raw text) for every top-level paragraph and every cell."""
    for position, text in enumerate(model["paragraphs"]):
        yield {"paragraph": position}, text
    for cell in model["cells"]:
        yield {"table": cell["table"], "addr": cell["addr"]}, cell["text"]


def haystack(model: dict) -> str:
    """Every seat's text, newline-joined.

    Newline rather than space so a digit ending one seat and a digit opening the
    next never fuse into one long run — that would be a fabricated 계좌번호 the
    document does not contain.
    """
    return "\n".join(text for _at, text in iter_seats(model))


def _count_raw(pattern: str, model: dict) -> int:
    return sum(len(_findall_raw(pattern, text)) for _at, text in iter_seats(model))


# --------------------------------------------------------------------------- #
# detectors — every one of them reads the form, not a hardcoded map
# --------------------------------------------------------------------------- #
def contract_titles(model: dict, vocabulary: dict) -> list[dict]:
    """Contract-variant banners: SHORT table cells carrying a contract label.

    Cells only, on purpose: '8. 가족관계증명서 및 동의서' is a numbered clause
    living in a top-level paragraph, and counting it as a variant banner would
    make the 연소근로자 sheet look like two sheets.
    """
    labels = _terms(vocabulary, "contract", "labels")
    limit = int(vocabulary["contract_title_max_chars"])
    found = []
    for cell in model["cells"]:
        squeezed = _squeeze(cell["text"])
        if len(squeezed) > limit:
            continue
        if any(_contains(cell["text"], label) for label in labels):
            found.append({"at": {"table": cell["table"], "addr": cell["addr"]},
                          "title": _normalize(cell["text"])})
    return found


def clause_blocks(model: dict, vocabulary: dict) -> list[list[dict]]:
    """Numbered-clause blocks, split where the numbering restarts.

    A block boundary is a clause number that does not advance — that is how the
    pack's separate contracts are told apart without interleaving paragraph and
    table offsets. Contiguity inside a block is NOT assumed: 2013's 단시간
    sheet runs 1,2,3,4,5,6,8,9 on the pristine form because its clause 7 is
    written mid-paragraph, so 'numbers must run 1..N' would fail the blank form.
    The inventory a rule judges against comes from the baseline instead.
    """
    head = re.compile(vocabulary["clause_head_re"])
    stop = vocabulary["clause_label_stop_re"]
    cap = int(vocabulary["clause_label_max_chars"])
    blocks: list[list[dict]] = []
    current: list[dict] = []
    previous = 0
    for position, text in enumerate(model["paragraphs"]):
        match = head.match(_normalize(text))
        if not match:
            continue
        number = int(match.group(1))
        label = _squeeze(re.split(stop, match.group(2))[0])[:cap]
        if number <= previous and current:
            blocks.append(current)
            current = []
        current.append({"number": number, "label": label,
                        "at": {"paragraph": position}})
        previous = number
    if current:
        blocks.append(current)
    return blocks


def clause_keys(block) -> list[list]:
    return [[row["number"], row["label"]] for row in block]


def party_blocks(model: dict, vocabulary: dict) -> list[dict]:
    """The 사업주 / 근로자 signature blocks, as paragraph runs.

    A block opens at the paragraph carrying the party marker and stays open
    while the paragraphs that follow still carry a seat label. That single rule
    covers both versions: 2013 spreads a party over three paragraphs
    ('(사업주) 사업체명 :' / '주    소 :' / '대 표 자 :  (서명)') and 2025
    collapses the same three seats into one. It also closes the block before the
    next sheet's opening sentence, which carries the word 사업주 but not the
    marker and no seat label at all.
    """
    employer = _terms(vocabulary, "party", "employer_labels")
    worker = _terms(vocabulary, "party", "worker_labels")
    seats = _terms(vocabulary, "party", "seat_labels")
    blocks: list[dict] = []
    current: dict | None = None
    for position, text in enumerate(model["paragraphs"]):
        party = None
        if any(_contains(text, term) for term in employer):
            party = "employer"
        elif any(_contains(text, term) for term in worker):
            party = "worker"
        if party is not None:
            current = {"party": party, "at": {"paragraph": position},
                       "texts": [text]}
            blocks.append(current)
            continue
        if current is not None and any(_contains(text, seat) for seat in seats):
            current["texts"].append(text)
        else:
            current = None
    return blocks


def party_seat_values(block: dict, vocabulary: dict) -> list[dict]:
    """Each seat label in the block, with the value that landed after it.

    The block's text is squeezed into one string, every seat label is located,
    and a seat's value is the slice up to the next label. Overlapping labels
    (사업체명 / 업체명) collapse to the longest match so one seat is never
    counted twice. Signature markers and layout punctuation are stripped, which
    is what makes a pristine block read as empty: '대 표 자 :   (서명)' reduces
    to nothing at all.
    """
    labels = _terms(vocabulary, "party", "seat_labels")
    text = _squeeze(" ".join(block["texts"]))
    hits: list[tuple[int, int, str]] = []
    for label in labels:
        key = _squeeze(label)
        start = 0
        while True:
            position = text.find(key, start)
            if position < 0:
                break
            hits.append((position, position + len(key), label))
            start = position + 1
    hits.sort(key=lambda row: (row[0], -(row[1] - row[0])))
    pruned: list[tuple[int, int, str]] = []
    for hit in hits:
        if pruned and hit[0] < pruned[-1][1]:
            continue
        pruned.append(hit)
    values = []
    for index, (_start, end, label) in enumerate(pruned):
        stop = pruned[index + 1][0] if index + 1 < len(pruned) else len(text)
        values.append({"label": label,
                       "value": residual_text(text[end:stop], (), vocabulary)})
    return values


def party_pairs(blocks) -> list[tuple[dict, dict]]:
    """Adjacent (employer, worker) blocks — one contract's signature block."""
    pairs = []
    index = 0
    while index < len(blocks) - 1:
        if (blocks[index]["party"] == "employer"
                and blocks[index + 1]["party"] == "worker"):
            pairs.append((blocks[index], blocks[index + 1]))
            index += 2
        else:
            index += 1
    return pairs


def statute_terms(model: dict, vocabulary: dict) -> dict[str, int]:
    """law term -> how many times the document cites it."""
    text = _squeeze(haystack(model))
    return {label: text.count(_squeeze(label))
            for label in _terms(vocabulary, "statute", "labels")
            if text.count(_squeeze(label))}


def statute_articles(model: dict, vocabulary: dict) -> list[str]:
    """The set of 제N조 citations the document carries, squeezed and sorted."""
    return sorted(set(_findall_sq(vocabulary["statute_article_re"],
                                  haystack(model))))


def signature_marker_count(model: dict, vocabulary: dict) -> int:
    """(서명 또는 인) / (서명) / (인) markers, counted not located.

    Counted rather than addressed because they live in top-level paragraphs,
    and a paragraph has no stable address — inserting one line renumbers every
    index after it. What must survive is the seat, and the count is the honest
    comparison for that.
    """
    return sum(len(_findall_sq(vocabulary["signature_marker_re"], text))
               for _at, text in iter_seats(model))


def slot_counts(model: dict, vocabulary: dict) -> dict[str, int]:
    """Option slots over the raw text, in two granularities.

    ``total`` (unmarked + occupied) is what option_slot_lost compares, and it
    counts printed parentheticals too — harmless, because they are stable across
    a fill and both sides of the comparison see them. ``glyph_marks`` is the
    narrow count: only a slot carrying a selection mark. That distinction is
    load-bearing — classifying state by ``occupied`` reports every pristine pack
    as a draft (32 printed parentheticals in 2013, 66 in 2025).
    """
    unmarked = _count_raw(vocabulary["unmarked_slot_re"], model)
    occupied = _count_raw(vocabulary["marked_slot_re"], model)
    return {"unmarked": unmarked, "occupied": occupied,
            "glyph_marks": _count_raw(vocabulary["mark_glyph_re"], model),
            "total": unmarked + occupied}


def stencil_fragments(model: dict, vocabulary: dict) -> list[str]:
    """The form's own literal fragments, squeezed.

    Split every seat on its blank runs and its colons, and keep what is left.
    Those pieces are the text a fill writes BETWEEN, never over — which is
    exactly the 'a filled seat must not consume the surrounding legal text'
    rule, expressed without needing to pair paragraphs between two documents.

    The colon is a boundary for a measured reason: this family letter-spaces its
    labels, so '주    소 :' carries a four-space run of its own and a
    blank-run-only split fuses it with the '대 표 자 :' that follows. Filling
    주소 then separates the two and reads as consumed text — a false finding on
    a correct fill.
    """
    minimum = int(vocabulary["stencil_fragment_min_chars"])
    fragments = []
    for _at, text in iter_seats(model):
        for piece in re.split(vocabulary["stencil_split_re"], text):
            squeezed = _squeeze(piece)
            if len(squeezed) >= minimum:
                fragments.append(squeezed)
    return _dedupe(fragments)


def identity_seats(model: dict, vocabulary: dict) -> dict[str, list[dict]]:
    """label -> the ordered seats carrying it, with their current residual.

    A seat is a LABEL, not prose: the 지급방법 clause names an 예금통장 inside a
    hundred-character sentence and is not a place a number goes.
    """
    labels = _terms(vocabulary, "identity", "labels")
    limit = int(vocabulary["identity_seat_max_chars"])
    found: dict[str, list[dict]] = {}
    for location, text in iter_seats(model):
        squeezed = _squeeze(text)
        if len(squeezed) > limit:
            continue
        for label in labels:
            if not _contains(text, label):
                continue
            found.setdefault(label, []).append({
                "at": location,
                "value": residual_text(text, [label], vocabulary),
            })
    return found


def template_version(model: dict, vocabulary: dict) -> dict:
    """Which declared template version(s) this document's vocabulary matches."""
    text = _squeeze(haystack(model))
    hits = {}
    for name in version_names(vocabulary):
        count = sum(text.count(_squeeze(marker))
                    for marker in _markers(vocabulary, name))
        if count:
            hits[name] = count
    detected = sorted(hits, key=lambda name: (-hits[name], name))
    return {"detected": detected, "marker_hits": hits,
            "version": detected[0] if len(detected) == 1 else None}


def rule_families(model: dict, vocabulary: dict) -> list[str]:
    """Which 계약·인사 seat families the document actually carries."""
    families = []
    if contract_titles(model, vocabulary):
        families.append("contract")
    if clause_blocks(model, vocabulary):
        families.append("clause")
    if party_blocks(model, vocabulary):
        families.append("party")
    if statute_terms(model, vocabulary):
        families.append("statute")
    if signature_marker_count(model, vocabulary):
        families.append("signature")
    if slot_counts(model, vocabulary)["total"]:
        families.append("slot")
    if identity_seats(model, vocabulary):
        families.append("identity")
    return families


# --------------------------------------------------------------------------- #
# state classification — the document says which state it is in
# --------------------------------------------------------------------------- #
def classify_state(model: dict, vocabulary: dict,
                   baseline_model: dict | None = None) -> dict:
    """Blank / draft / final, from the document's own evidence.

    ``written``  a slot carries a selection mark, or a party seat carries a
                 value, or (with a baseline) some paragraph the blank form
                 carries no longer reads the same. A pristine pack has none of
                 the three. The party-seat term is what makes the no-baseline
                 path honest: this family has no checkbox culture, so a filled
                 contract with no baseline would otherwise read as blank.
    ``dated``    no unfilled ``년 월 일`` seat remains.

    ``blank`` = nothing written. ``final`` = written AND dated. ``draft`` =
    written but still undated. Paragraph comparison is SET-based, never
    positional: a contract pack has five near-identical sheets and an index
    shifts the moment one paragraph is added.
    """
    slots = slot_counts(model, vocabulary)
    unfilled_dates = _count_raw(vocabulary["unfilled_date_seat_re"], model)
    unfilled_times = _count_raw(vocabulary["unfilled_time_seat_re"], model)
    blank_runs = _count_raw(vocabulary["blank_run_re"], model)
    changed = 0
    if baseline_model is not None:
        current = {_squeeze(text) for text in model["paragraphs"]}
        changed = sum(1 for text in baseline_model["paragraphs"]
                      if _squeeze(text) not in current)
    party_values = sum(
        1 for block in party_blocks(model, vocabulary)
        for row in party_seat_values(block, vocabulary) if row["value"])
    written = bool(slots["glyph_marks"] or changed or party_values
                   or not unfilled_dates)
    if not written:
        state = STATE_BLANK
    elif unfilled_dates:
        state = STATE_DRAFT
    else:
        state = STATE_FINAL
    return {"state": state, "marked_slots": slots["glyph_marks"],
            "party_seats_filled": party_values,
            "option_slots": slots["total"],
            "unfilled_date_seats": unfilled_dates,
            "unfilled_time_seats": unfilled_times,
            "blank_runs": blank_runs,
            "paragraphs_changed": changed}


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _finding(code: str, msg: str, at, **extra) -> dict:
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


def _check_skeleton(model, vocabulary, baseline_model, hard, info, skipped):
    """R1 — the numbered-clause skeleton survives the fill."""
    blocks = clause_blocks(model, vocabulary)
    if baseline_model is None:
        for rule in ("clause_block_lost", "clause_lost", "clause_renumbered"):
            skipped.append({"rule": rule, "reason": "no_baseline"})
        info.append({"seat": "clause_inventory", "state": "reported",
                     "blocks": [clause_keys(block) for block in blocks]})
        return

    baseline_blocks = clause_blocks(baseline_model, vocabulary)
    if not baseline_blocks:
        for rule in ("clause_block_lost", "clause_lost", "clause_renumbered"):
            skipped.append({"rule": rule, "reason": "seat_absent"})
        return
    if len(blocks) < len(baseline_blocks):
        hard.append(_finding(
            "clause_block_lost",
            "a numbered-clause block the blank form carries is gone — each "
            "block is one contract in the pack, and dropping one drops a "
            "contract the 고용노동부 서식 offers",
            None, baseline=len(baseline_blocks), artifact=len(blocks)))
    for index, baseline_block in enumerate(baseline_blocks):
        if index >= len(blocks):
            continue
        wanted = clause_keys(baseline_block)
        present = clause_keys(blocks[index])
        for key in wanted:
            if key not in present:
                hard.append(_finding(
                    "clause_lost",
                    "a numbered clause the blank form carries is gone — the "
                    "clause list IS the 근로기준법 제17조 서면 명시 항목",
                    {"block": index, "clause": key}, baseline=key))
        numbers = [row[0] for row in wanted]
        got = [row[0] for row in present]
        if numbers != got:
            hard.append(_finding(
                "clause_renumbered",
                "the clause numbering of a contract changed — a renumbered "
                "clause is a different clause to anyone reading the contract",
                {"block": index}, baseline=numbers, artifact=got))
        else:
            info.append({"seat": "clause_block", "state": "intact",
                         "block": index, "clauses": len(wanted)})


def _check_variants(model, vocabulary, baseline_model, hard, info, skipped):
    """R2 — the pack keeps every contract variant it shipped with."""
    titles = contract_titles(model, vocabulary)
    if baseline_model is None:
        skipped.append({"rule": "contract_variant_lost", "reason": "no_baseline"})
        info.append({"seat": "contract_variant", "state": "reported",
                     "titles": [row["title"] for row in titles]})
        return
    baseline_titles = [row["title"] for row in contract_titles(baseline_model,
                                                               vocabulary)]
    if not baseline_titles:
        skipped.append({"rule": "contract_variant_lost", "reason": "seat_absent"})
        return
    present = [_squeeze(row["title"]) for row in titles]
    for title in baseline_titles:
        if _squeeze(title) not in present:
            hard.append(_finding(
                "contract_variant_lost",
                "a contract-variant banner the blank form carries is gone — "
                "the 고용노동부 서식 ships as a pack and filling one sheet is "
                "not a licence to delete the others",
                title))
        else:
            info.append({"seat": "contract_variant", "state": "present",
                         "title": title})


def _check_seats(model, vocabulary, state, baseline_model, hard, warn, info,
                 skipped):
    """R3 — a fill writes into the seats and over nothing else."""
    slots = slot_counts(model, vocabulary)

    # ── the unfilled seats: REPORTED, never a HARD finding ─────────────────
    # This is the family's own asymmetry. Turning "you did not fill 임금지급일"
    # into a failure is how a tool learns to invent one.
    unfilled = (_count_raw(vocabulary["unfilled_date_seat_re"], model)
                + _count_raw(vocabulary["unfilled_time_seat_re"], model)
                + slots["unmarked"])
    if state == STATE_BLANK:
        skipped.append({"rule": "seat_unfilled", "reason": "document_state_blank"})
        info.append({"seat": "fill_seat", "state": "unfilled",
                     "seats": unfilled})
    elif unfilled:
        warn.append(_finding(
            "seat_unfilled",
            "seats are still unfilled (date / time skeletons and unmarked "
            "option slots). This is a REPORT, never a failure: an unfilled "
            "seat is handed back to the person who has the value, never "
            "invented",
            None, seats=unfilled, marked_slots=slots["glyph_marks"]))
    else:
        info.append({"seat": "fill_seat", "state": "complete"})

    if baseline_model is None:
        skipped.append({"rule": "clause_text_consumed", "reason": "no_baseline"})
        skipped.append({"rule": "option_slot_lost", "reason": "no_baseline"})
        return

    # ── the surrounding legal text ─────────────────────────────────────────
    wanted = stencil_fragments(baseline_model, vocabulary)
    if not wanted:
        skipped.append({"rule": "clause_text_consumed", "reason": "seat_absent"})
    else:
        text = _squeeze(haystack(model))
        missing = [fragment for fragment in wanted if fragment not in text]
        for fragment in missing:
            hard.append(_finding(
                "clause_text_consumed",
                "text the blank form prints between its seats is gone — a "
                "fill writes INTO a seat; consuming the clause around it "
                "rewrites the contract",
                fragment[:60], length=len(fragment)))
        if not missing:
            info.append({"seat": "clause_text", "state": "intact",
                         "fragments": len(wanted)})

    # ── option slots ───────────────────────────────────────────────────────
    baseline_slots = slot_counts(baseline_model, vocabulary)
    if not baseline_slots["total"]:
        skipped.append({"rule": "option_slot_lost", "reason": "seat_absent"})
        return
    if slots["total"] < baseline_slots["total"]:
        hard.append(_finding(
            "option_slot_lost",
            "an option slot the blank form carries is gone — marking a slot "
            "turns ( ) into (○) and keeps the count; deleting one removes a "
            "choice the contract offers",
            None, baseline=baseline_slots["total"], artifact=slots["total"]))
    else:
        info.append({"seat": "option_slot", "state": "preserved",
                     "total": slots["total"],
                     "glyph_marks": slots["glyph_marks"]})


def _check_parties(model, vocabulary, state, baseline_model, hard, warn, info,
                   skipped):
    """R4 — the two-party signature block, and whose job the signature is."""
    blocks = party_blocks(model, vocabulary)

    # ── half a party is a defect; both blank is blank-by-design ────────────
    pairs = party_pairs(blocks)
    if not pairs:
        skipped.append({"rule": "party_half_filled", "reason": "seat_absent"})
    for employer, worker in pairs:
        filled = {}
        for role, block in (("employer", employer), ("worker", worker)):
            values = party_seat_values(block, vocabulary)
            filled[role] = sum(1 for row in values if row["value"])
        if filled["employer"] and filled["worker"]:
            info.append({"seat": "party_pair", "state": "both_filled",
                         "at": employer["at"], **filled})
        elif not filled["employer"] and not filled["worker"]:
            info.append({"seat": "party_pair", "state": "both_blank",
                         "at": employer["at"]})
        else:
            row = _finding(
                "party_half_filled",
                "one contracting party's seats are filled and the other's are "
                "empty — a 근로계약서 with one identified party is not a "
                "contract, and the missing side is asked for, not invented",
                employer["at"], employer_seats=filled["employer"],
                worker_seats=filled["worker"])
            (hard if state == STATE_FINAL else warn).append(row)

    if baseline_model is None:
        skipped.append({"rule": "party_block_lost", "reason": "no_baseline"})
        skipped.append({"rule": "signature_marker_lost", "reason": "no_baseline"})
        info.append({"seat": "party_block", "state": "reported",
                     "blocks": len(blocks)})
        return

    baseline_blocks = party_blocks(baseline_model, vocabulary)
    if not baseline_blocks:
        skipped.append({"rule": "party_block_lost", "reason": "seat_absent"})
    elif len(blocks) < len(baseline_blocks):
        hard.append(_finding(
            "party_block_lost",
            "a 사업주 / 근로자 signature block the blank form carries is gone "
            "— the two-party block is where the contract is executed",
            None, baseline=len(baseline_blocks), artifact=len(blocks)))
    else:
        info.append({"seat": "party_block", "state": "present",
                     "blocks": len(blocks)})

    baseline_markers = signature_marker_count(baseline_model, vocabulary)
    markers = signature_marker_count(model, vocabulary)
    if not baseline_markers:
        skipped.append({"rule": "signature_marker_lost", "reason": "seat_absent"})
    elif markers < baseline_markers:
        hard.append(_finding(
            "signature_marker_lost",
            "a (서명) / (인) marker the blank form carries is gone — the "
            "party's name may share the line, but the signature seat itself "
            "stays for the human",
            None, baseline=baseline_markers, artifact=markers))
    else:
        info.append({"seat": "signature", "state": "reserved",
                     "count": markers})


def _check_statute(model, vocabulary, baseline_model, hard, info, skipped):
    """R5 — this family's text IS the legal instrument."""
    terms = statute_terms(model, vocabulary)
    articles = statute_articles(model, vocabulary)
    if baseline_model is None:
        skipped.append({"rule": "statute_reference_lost", "reason": "no_baseline"})
        skipped.append({"rule": "statute_reference_invented",
                        "reason": "no_baseline"})
        info.append({"seat": "statute", "state": "reported",
                     "terms": terms, "articles": articles})
        return

    baseline_terms = statute_terms(baseline_model, vocabulary)
    baseline_articles = statute_articles(baseline_model, vocabulary)
    if not baseline_terms and not baseline_articles:
        skipped.append({"rule": "statute_reference_lost", "reason": "seat_absent"})
        skipped.append({"rule": "statute_reference_invented",
                        "reason": "seat_absent"})
        return

    for label, count in baseline_terms.items():
        current = terms.get(label, 0)
        if current < count:
            hard.append(_finding(
                "statute_reference_lost",
                "a statutory reference the blank form carries was thinned or "
                "removed — a 표준근로계약서's citations are the instrument, "
                "not commentary on it",
                label, baseline=count, artifact=current))
    for article in baseline_articles:
        if article not in articles:
            hard.append(_finding(
                "statute_reference_lost",
                "a statute article citation the blank form carries is gone",
                article))
    for article in articles:
        if article not in baseline_articles:
            hard.append(_finding(
                "statute_reference_invented",
                "the artifact cites a statute article the blank form does not "
                "— a citation nobody put in the form is a fabricated legal "
                "claim, which is worse than a missing one",
                article, baseline=baseline_articles))
    if not any(row["code"].startswith("statute_") for row in hard):
        info.append({"seat": "statute", "state": "verbatim",
                     "terms": terms, "articles": articles})


def _check_version(model, vocabulary, baseline_model, hard, info, skipped):
    """R6 — the versioned pair is this family's distinguishing feature."""
    detected = template_version(model, vocabulary)
    info.append({"seat": "template_version", "state": "detected", **detected})
    if len(detected["detected"]) > 1:
        hard.append(_finding(
            "template_version_mixed",
            "the document carries vocabulary from more than one 표준근로계약서 "
            "revision — text was spliced across template versions, and the "
            "result matches no 고용노동부 서식 that was ever published",
            None, versions=detected["detected"],
            marker_hits=detected["marker_hits"]))
    if baseline_model is None:
        skipped.append({"rule": "template_version_changed",
                        "reason": "no_baseline"})
        return
    baseline_detected = template_version(baseline_model, vocabulary)
    if not baseline_detected["version"]:
        skipped.append({"rule": "template_version_changed",
                        "reason": "baseline_version_undetermined"})
        return
    if detected["version"] != baseline_detected["version"]:
        hard.append(_finding(
            "template_version_changed",
            "the artifact's template version does not match the blank form it "
            "came from — a fill never migrates a contract to another revision",
            None, baseline=baseline_detected["version"],
            artifact=detected["version"]))


def _check_identity(model, vocabulary, baseline_model, fill_map, hard, info,
                    skipped):
    """R7 — the privacy rule: the tool never invents a personal number."""
    declared = declared_values(fill_map)
    minimum = int(vocabulary["identity_value_min_length"])
    floor = int(vocabulary["personal_number_min_digits"])

    # R7a/R7b: identity- and account-shaped values nobody declared. Decidable
    # WITHOUT a baseline — if nothing declared it, its presence is the finding.
    for rule, key, shape in (
            ("identity_value_invented", "rrn_re", "rrn"),
            ("personal_number_invented", "personal_number_re", "account_like"),
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
                "a personal-number-shaped value appears in the document and "
                "the operator did not declare it — 주민등록번호 and 계좌번호 "
                "are never synthesized, and an empty seat is the correct "
                "output",
                None, shape=shape, declared_values=len(declared)))
        if not offenders:
            info.append({"seat": shape, "state": "none_undeclared",
                         "present": len(found)})

    # R7c: a value written into an identity seat the blank form left empty.
    if baseline_model is None:
        skipped.append({"rule": "identity_seat_autofilled",
                        "reason": "no_baseline"})
        return
    baseline_seats = identity_seats(baseline_model, vocabulary)
    if not baseline_seats:
        skipped.append({"rule": "identity_seat_autofilled",
                        "reason": "seat_absent"})
        return
    current_seats = identity_seats(model, vocabulary)
    allowed_values = [residual_text(item, (), vocabulary) for item in declared]
    for label, seats in baseline_seats.items():
        now = current_seats.get(label, [])
        if len(now) != len(seats):
            # Seats are keyed by LABEL, in document order: a count that moved
            # means the seats themselves changed and a pairwise comparison
            # would be comparing the wrong two things. Say so instead.
            skipped.append({"rule": "identity_seat_autofilled",
                            "reason": "seat_count_drift", "label": label,
                            "baseline": len(seats), "artifact": len(now)})
            continue
        for before, after in zip(seats, now):
            value = after["value"]
            if value == before["value"] or len(value) < minimum:
                continue
            written = (value[len(before["value"]):]
                       if value.startswith(before["value"]) else value)
            if any(written and written in item
                   for item in allowed_values if item):
                info.append({"seat": "identity_seat", "state": "declared",
                             "label": label, "at": after["at"]})
                continue
            hard.append(_finding(
                "identity_seat_autofilled",
                "an identity seat (주민등록번호 / 생년월일 / 등록번호) the "
                "blank form left empty now carries a value the operator did "
                "not declare — leave it for the person and say so",
                after["at"], label=label, declared_values=len(declared)))


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
    except HrError as exc:
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
            "pinned artifact path does not exist — refusing to pass a "
            "근로계약서 gate against a missing target",
            str(artifact_path)))
        return (_verdict(artifact_path, None, hard, warn, info, skipped),
                exit_code(hard=hard))
    if not zipfile.is_zipfile(artifact_path):
        return usage_error(
            str(artifact_path), CHECKER,
            "artifact is not an hwpx (zip) document — 근로계약서 checks read "
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
                f"XML ({row['error']}) — 근로계약서 structure checks skipped",
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
            "hr_structure_absent",
            f"only {len(families)} 계약·인사 서식 seat family/families "
            f"recognized (minimum {minimum}) — this document is not a "
            "근로계약서",
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

    _check_skeleton(model, vocab, baseline_model, hard, info, skipped)
    _check_variants(model, vocab, baseline_model, hard, info, skipped)
    _check_seats(model, vocab, state, baseline_model, hard, warn, info, skipped)
    _check_parties(model, vocab, state, baseline_model, hard, warn, info,
                   skipped)
    _check_statute(model, vocab, baseline_model, hard, info, skipped)
    _check_version(model, vocab, baseline_model, hard, info, skipped)
    _check_identity(model, vocab, baseline_model, declared_map, hard, info,
                    skipped)

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
        description="deterministic 계약·인사 서식 gate for a filled artifact "
                    "(고용노동부 표준근로계약서 pack)")
    parser.add_argument("artifact", help="hwpx document to check")
    parser.add_argument(
        "--mode", default="auto", choices=MODES,
        help="document state; 'auto' reads it from the document (default)")
    parser.add_argument(
        "--vocabulary", default=None,
        help=f"hr vocabulary JSON (default: {DEFAULT_VOCABULARY.name} shipped "
             "with this module)")
    parser.add_argument(
        "--baseline", default=None,
        help="the BLANK form this artifact was filled from; enables the "
             "preservation rules (clause skeleton, contract variants, "
             "surrounding clause text, option slots, party blocks, signature "
             "markers, statute citations, template version, identity seats)")
    parser.add_argument(
        "--fill-map", dest="fill_map", default=None,
        help="the {placeholder: value} map the OPERATOR declared for this "
             "document — a bare map (preedit.py replace --map) or an object "
             "with a 'fill_map' member (visual_verify --expectations); "
             "either shape is accepted. Values here are what makes "
             "a personal number declared rather than invented")
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
