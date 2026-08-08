# -*- coding: utf-8 -*-
"""T40: the seat — the same form field located in two documents.

``check_fill_charpr_script`` had one baseline, the document's own body charPr
(the id carrying the most non-fill text). On a mostly-empty FORM that baseline
is boilerplate: on the 기안문 별지 제1호서식 the heaviest charPr is the 비고
fine print (10pt, ratio 100%), so every substantive seat on the form — 수신,
(경유), 제목, 직인, 발신명의, all ratio 97% — differed from it and HARDed. The
detector was inverted on that whole document class.

The fix needs the same field located in the BLANK form and in the artifact, so
"did the fill introduce this signature" becomes answerable. These tests pin the
seat-matching rule that makes that possible, and the two properties it must
have to be trustworthy:

  * it survives the text change a fill makes (``--at-cell-append`` keeps the
    printed label and appends the value, ``--at-cell`` replaces it outright),
    which is why the key is structural and not textual;
  * it holds on the REAL corpus, not just on this one form —
    ``test_every_corpus_form_addresses_every_cell_by_cellAddr`` is the check
    that the primary key is not a private convention of the 기안문 별지.
"""
import glob
import os
import re
import sys
import zipfile

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import charpr_script  # noqa: E402

CORPUS = os.path.join(REPO, "tests", "corpus", "forms", "converted")
SECTION_MEMBER = re.compile(r"^Contents/section\d+\.xml$")


def _sec(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            + body + '</hs:sec>')


def _cell(row, col, body):
    """A cell in the REAL OWPML order: subList first, cellAddr LAST."""
    return ('<hp:tc name="" header="0"><hp:subList>' + body + '</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')


def _run(cid, text):
    return f'<hp:run charPrIDRef="{cid}"><hp:t>{text}</hp:t></hp:run>'


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

def test_cellAddr_after_the_sublist_still_labels_the_runs_inside_it():
    """The whole reason seat resolution takes two passes.

    OWPML puts ``<hp:cellAddr>`` at the END of ``<hp:tc>``, after the
    ``<hp:subList>`` holding the paragraphs — so a single forward scan reaches
    every run in the cell BEFORE it learns the cell's address. A one-pass
    implementation labels them all by fallback ordinal and the seat is unusable
    as a key across two documents.
    """
    xml = _sec('<hp:p id="1"><hp:tbl id="20">'
               '<hp:tr>' + _cell(2, 5, '<hp:p id="9">' + _run(14, "수신")
                                 + '</hp:p>') + '</hp:tr>'
               '</hp:tbl></hp:p>')
    seats = charpr_script.iter_seat_runs(xml, "Contents/section0.xml")
    assert seats == [(("Contents/section0.xml", "t1/2,5"), "14", "수신")]


def test_a_run_outside_every_cell_is_unaddressed_not_seat_zero():
    """Prose paragraphs shift when a fill adds one, so there is no honest
    identity to offer — the empty seat is the answer, and a caller must read it
    as "no baseline available" rather than as a match."""
    xml = _sec(f'<hp:p id="1">{_run(0, "본문 문장")}</hp:p>')
    assert charpr_script.iter_seat_runs(xml, "s0") == [((), "0", "본문 문장")]


def test_an_append_fill_keeps_the_seat_a_replace_fill_keeps_it_too():
    """The property the rule exists for: the seat key must survive BOTH fill
    shapes, and text cannot do that. ``--at-cell-append`` leaves the label as a
    prefix; ``--at-cell`` leaves nothing textual in common at all."""
    def seat_of(text):
        xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
                   + _cell(1, 0, '<hp:p id="9">' + _run(14, text) + '</hp:p>')
                   + '</hp:tr></hp:tbl></hp:p>')
        return charpr_script.iter_seat_runs(xml, "s0")[0][0]

    blank = seat_of("수신")
    assert seat_of("수신 국가유산청장") == blank      # --at-cell-append
    assert seat_of("2026. 3. 1. ~ 2027. 2. 28.") == blank   # --at-cell
    assert blank == ("s0", "t1/1,0")


def test_nested_tables_address_outermost_cell_first():
    inner = ('<hp:tbl id="30"><hp:tr>'
             + _cell(0, 0, '<hp:p id="8">' + _run(7, "안쪽") + '</hp:p>')
             + '</hp:tr></hp:tbl>')
    xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
               + _cell(3, 4, '<hp:p id="9">' + inner + '</hp:p>')
               + '</hp:tr></hp:tbl></hp:p>')
    (seat, cid, text), = charpr_script.iter_seat_runs(xml, "s0")
    assert (cid, text) == ("7", "안쪽")
    assert seat == ("s0", "t1/3,4", "t2/0,0")


def test_a_cell_with_no_celladdr_falls_back_to_its_ordinal():
    """Hand-built and minimal documents still address. The fallback is visible
    in the seat string, and both documents are read by the same function, so
    they cannot disagree about which form was used."""
    xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
               '<hp:tc><hp:subList><hp:p id="9">' + _run(0, "가") +
               '</hp:p></hp:subList></hp:tc>'
               '<hp:tc><hp:subList><hp:p id="10">' + _run(0, "나") +
               '</hp:p></hp:subList></hp:tc>'
               '</hp:tr></hp:tbl></hp:p>')
    assert [seat for seat, _c, _t in charpr_script.iter_seat_runs(xml, "s0")] \
        == [("s0", "t1/#1"), ("s0", "t1/#2")]


def test_seat_label_runs_pick_the_exact_blank_run_not_the_seat_majority():
    xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
               + _cell(1, 0, '<hp:p id="9">' + _run(12, "행 정 기 관 명")
                       + _run(14, "수신") + '</hp:p>')
               + '</hp:tr></hp:tbl></hp:p>')
    runs = charpr_script.iter_seat_runs(xml, "s0")
    seat = ("s0", "t1/1,0")
    assert charpr_script.seat_label_runs(runs, seat, "수 신") == [
        ("14", "수신")]
    assert charpr_script.seat_label_runs(runs, seat, "기관명") == [
        ("12", "행 정 기 관 명")]
    assert charpr_script.seat_label_runs(runs, ("s0", "t1/9,9"), "수신") == []
    assert charpr_script.seat_label_runs(runs, (), "수신") == []


def test_an_empty_seat_has_no_label_run_to_match():
    """The genuinely empty run a ``fill-cells`` target holds. The seat EXISTS
    but has no typography, so nothing can be inherited from it — that is what
    keeps the T30 catch alive after the relaxation."""
    xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
               + _cell(1, 0, '<hp:p id="9"><hp:run charPrIDRef="0"/></hp:p>')
               + '</hp:tr></hp:tbl></hp:p>')
    runs = charpr_script.iter_seat_runs(xml, "s0")
    assert runs == []
    assert charpr_script.seat_label_runs(runs, ("s0", "t1/1,0"), "수신") == []


def test_empty_runs_keep_their_exact_structural_seat_and_charpr():
    """T42 needs the typography of a reserved blank block without pretending
    that it is visible text. Self-closing runs, paired empty runs and an empty
    ``<hp:t/>`` all count; a nested table keeps its own deeper seat."""
    inner = ('<hp:tbl id="30"><hp:tr>'
             + _cell(0, 0, '<hp:p id="8"><hp:run charPrIDRef="7"/></hp:p>')
             + '</hp:tr></hp:tbl>')
    xml = _sec('<hp:p id="1"><hp:tbl id="20"><hp:tr>'
               + _cell(2, 0, '<hp:p id="9">'
                       '<hp:run charPrIDRef="14"/>'
                       '<hp:run charPrIDRef="14"><hp:t/></hp:run>'
                       '<hp:run charPrIDRef="14"><hp:t></hp:t></hp:run>'
                       + inner + '</hp:p>')
               + '</hp:tr></hp:tbl></hp:p>')
    assert charpr_script.iter_seat_empty_runs(xml, "s0") == [
        (("s0", "t1/2,0"), "14"),
        (("s0", "t1/2,0"), "14"),
        (("s0", "t1/2,0"), "14"),
        (("s0", "t1/2,0", "t2/0,0"), "7"),
    ]


def test_iter_runs_is_iter_seat_runs_with_the_seat_dropped():
    """One traversal, two views. The seat-aware and seat-blind readings of a
    document must never report different runs, different text or a different
    order — the document body baseline is weighted from one and the seat
    baseline from the other."""
    xml = _sec('<hp:p id="1">' + _run(3, "■ ") + '</hp:p>'
               '<hp:p id="2"><hp:tbl id="20"><hp:tr>'
               + _cell(0, 0, '<hp:p id="9">' + _run(26, "규정 시행규칙")
                       + '<hp:run charPrIDRef="13"/>'
                       + _run(14, "수신") + '</hp:p>')
               + '</hp:tr></hp:tbl></hp:p>')
    assert charpr_script.iter_runs(xml) == [
        (cid, text) for _seat, cid, text in charpr_script.iter_seat_runs(xml)]
    # and the T37 self-closing run still steals nothing
    assert charpr_script.iter_runs(xml) == [
        ("3", "■ "), ("26", "규정 시행규칙"), ("14", "수신")]


# --------------------------------------------------------------------------
# the generalisation claim, checked against the real corpus
# --------------------------------------------------------------------------

def _corpus_forms():
    return sorted(glob.glob(os.path.join(CORPUS, "*.hwpx")))


def test_every_corpus_form_addresses_every_cell_by_cellAddr():
    """``cellAddr`` is the primary key because it is what the fill CLIs
    address (``--cell ROW,COL``, ``--at-cell ROW,COL``) — the same coordinate
    the operator typed. This asserts that on all ten rendered corpus forms the
    ordinal fallback is never needed, i.e. the rule is not a private
    convention of the one form that motivated it."""
    forms = _corpus_forms()
    assert len(forms) >= 10, forms
    for path in forms:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(n for n in archive.namelist()
                               if SECTION_MEMBER.match(n)):
                xml = archive.read(name).decode("utf-8", "replace")
                fallback = [cell["label"]
                            for cell in charpr_script._seat_cells(xml)
                            if "#" in cell["label"]]
                assert not fallback, (os.path.basename(path), name, fallback)


def test_corpus_seats_are_stable_and_runs_stay_in_document_order():
    """Two properties the comparison depends on, over the real forms: a seat
    label round-trips through the weighting map, and the seat-aware traversal
    yields exactly the runs ``iter_runs`` does."""
    for path in _corpus_forms():
        with zipfile.ZipFile(path) as archive:
            for name in sorted(n for n in archive.namelist()
                               if SECTION_MEMBER.match(n)):
                xml = archive.read(name).decode("utf-8", "replace")
                seat_runs = charpr_script.iter_seat_runs(xml, name)
                assert charpr_script.iter_runs(xml) == [
                    (cid, text) for _s, cid, text in seat_runs]
                for seat, cid, text in seat_runs:
                    if seat:
                        assert (cid, text) in charpr_script.seat_label_runs(
                            seat_runs, seat, text)
