# -*- coding: utf-8 -*-
"""advance_probe.py — our glyph advances against Hancom's PDF positions.

The measurement is written up in ``engine/references/own-render-notes.md``.
What is pinned here is the MECHANISM, on synthetic input, so that a change to
the probe has to move a named term rather than a corpus tally.  Nothing below
counts corpus characters, lines, forms or faces: every fixture is built in the
test.

Five things:

  * an advance is the distance to the NEXT character's origin, and only
    inside one text-showing run — across a run boundary the distance is
    Hancom moving the pen, which is not a glyph's width;
  * Hancom does not draw every character, so the comparison is anchor to
    anchor and both sides of a segment cover the SAME characters;
  * the character classes are the ones the renderer treats differently: a
    full-width cell, a half-width space, and the proportional rest;
  * the device grid the reference sits on is 1/600 inch — a cell is rounded
    onto it and an advance truncated onto it — and the arithmetic of that is
    pinned against sizes read off the reference, not against a corpus tally;
  * a Korean face name that reached the PDF as CP949 read for Latin-1 is put
    back together, and a genuinely Latin name is left alone.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import advance_probe as AP  # noqa: E402
import own_render  # noqa: E402


PT = own_render.HWPUNIT_PER_PT


def box(ch, origin_pt, width_pt, piece=(0, 0)):
    """One PyMuPDF ``rawdict`` character, in points."""
    return {
        "c": ch,
        "ox": float(origin_pt),
        "oy": 100.0,
        "x0": float(origin_pt),
        "x1": float(origin_pt + width_pt),
        "y0": 90.0,
        "y1": 103.0,
        "size": 13.0,
        "font": "Batang",
        "piece": piece,
    }


class Metrics:
    """A stand-in for ``OurMetrics``: fixed advances by character."""

    def __init__(self, advances, gap=0.0):
        self.advances = advances
        self.gap = gap

    def run(self, ch, cid):
        advance = self.advances[ch]
        return {
            "declared": "declared", "resolved": "resolved.ttf",
            "source": "installed",
            "slot": "hangul", "bold": False, "size_pt": 13.0,
            "spacing": 0, "ratio": 100, "class": AP.char_class(ch),
            "advance_hwp": advance, "gap_hwp": self.gap,
            "grid_advance_hwp": advance, "grid_gap_hwp": self.gap,
        }


def ours(text, cid="0"):
    return [(index, ch, cid) for index, ch in enumerate(text)]


# --------------------------------------------------------------------------
# 1 · an advance is the step to the next origin, inside one run


def test_an_advance_is_the_distance_to_the_next_origin():
    boxes = [box("가", 0, 13), box("나", 13, 13), box("다", 26, 13)]
    advances = AP.hancom_advances(boxes)
    assert advances[0] == (pytest.approx(13 * PT), False)
    assert advances[1] == (pytest.approx(13 * PT), False)


def test_the_last_character_of_a_run_reports_its_bbox_and_says_so():
    boxes = [box("가", 0, 13), box("나", 13, 11)]
    advances = AP.hancom_advances(boxes)
    # The last one has no successor, so its INK width stands in and the flag
    # is what keeps it out of every ratio.
    assert advances[-1][1] is True
    assert advances[-1][0] == pytest.approx(11 * PT)


def test_a_run_boundary_is_a_pen_move_and_not_a_width():
    # Two runs 40 pt apart: the gap is Hancom moving the pen over characters
    # it never drew, and charging it to 가 would make one glyph 40 pt wide.
    boxes = [box("가", 0, 13, piece=(0, 0)),
             box("나", 53, 13, piece=(0, 1))]
    advances = AP.hancom_advances(boxes)
    assert advances[0][1] is True
    assert advances[0][0] == pytest.approx(13 * PT)


# --------------------------------------------------------------------------
# 2 · anchor to anchor, both sides covering the same characters


def test_alignment_pairs_across_a_character_the_pdf_never_drew():
    boxes = [box("가", 0, 13), box("나", 20, 13)]
    pairs, n_ours, n_theirs = AP.align([(ch, "0") for ch in "가 나"], boxes)
    assert (n_ours, n_theirs) == (3, 2)
    assert pairs == [(0, 0), (2, 1)]


def test_a_segment_charges_both_sides_the_same_characters():
    # 가 then an undrawn space then 나.  Hancom moved the pen 20 pt; our two
    # advances over the same stretch are 13 + 7.  They agree, and they only
    # agree because the space is on OUR side of the segment too.
    boxes = [box("가", 0, 13), box("나", 20, 13)]
    metrics = Metrics({"가": 13 * PT, " ": 7 * PT, "나": 13 * PT})
    _pairs, _no, _nt, chars, segments = AP.analyse_line(
        ours("가 나"), boxes, metrics)
    assert len(segments) == 1
    assert segments[0]["chars"] == 2
    assert segments[0]["ours_hwp"] == pytest.approx(20 * PT)
    assert segments[0]["hancom_hwp"] == pytest.approx(20 * PT)
    # A segment that swallowed an undrawn character is not a glyph advance,
    # so it never reaches the per-character ratio table.
    assert chars == []


def test_a_one_to_one_segment_is_a_glyph_advance_and_does_reach_the_table():
    boxes = [box("가", 0, 13), box("나", 13, 13)]
    metrics = Metrics({"가": 13 * PT, "나": 13 * PT})
    _pairs, _no, _nt, chars, segments = AP.analyse_line(
        ours("가나"), boxes, metrics)
    assert [seg["singleton"] for seg in segments] == [True]
    assert len(chars) == 1
    assert chars[0]["ours_hwp"] == pytest.approx(13 * PT)
    assert chars[0]["hancom_hwp"] == pytest.approx(13 * PT)
    assert chars[0]["pdf_font"] == "Batang"


def test_the_line_total_is_the_sum_of_the_segments_on_both_sides():
    boxes = [box("가", 0, 13), box("나", 20, 13), box("다", 33, 13)]
    metrics = Metrics({"가": 13 * PT, " ": 7 * PT, "나": 13 * PT,
                       "다": 13 * PT})
    _pairs, _no, _nt, _chars, segments = AP.analyse_line(
        ours("가 나다"), boxes, metrics)
    assert sum(seg["ours_hwp"] for seg in segments) == pytest.approx(33 * PT)
    assert sum(seg["hancom_hwp"] for seg in segments) == pytest.approx(33 * PT)


# --------------------------------------------------------------------------
# 3 · the classes


@pytest.mark.parametrize("ch,expected", [
    ("가", "hangul"),
    ("ㄱ", "hangul"),
    ("漢", "hanja"),
    ("A", "latin"),
    ("7", "digit"),
    ("(", "punct"),
    (" ", "space"),
    ("　", "space"),
    ("」", "fw_punct"),
    ("“", "fw_punct"),
])
def test_the_character_classes(ch, expected):
    assert AP.char_class(ch) == expected


# --------------------------------------------------------------------------
# 4 · the 1/600 inch device grid


def test_the_grid_is_one_six_hundredth_of_an_inch():
    assert AP.DEVICE_GRID_HWP == pytest.approx(own_render.HWPUNIT_PER_INCH
                                               / 600.0)
    assert AP.DEVICE_GRID_HWP == pytest.approx(12.0)


@pytest.mark.parametrize("pt,cell", [
    (12.0, 1200.0),   # already whole units
    (13.0, 1296.0),   # 108.33 -> 108
    (14.0, 1404.0),   # 116.67 -> 117
    (11.0, 1104.0),   # 91.67  -> 92
    (15.0, 1500.0),   # 125    -> 125
    (20.0, 2004.0),   # 166.67 -> 167
])
def test_a_cell_rounds_onto_the_grid(pt, cell):
    assert AP.cell_on_grid(pt * PT) == pytest.approx(cell)


def test_an_advance_truncates_onto_the_grid():
    # A 15 pt cell is 125 units and its half is 62.5, which truncates to 62
    # and not to 63 -- the direction is what the reference's own space
    # advances show.
    half = AP.cell_on_grid(15 * PT) * own_render.SPACE_CELL_FRACTION
    assert half == pytest.approx(750.0)
    assert AP.truncate_to_grid(half) == pytest.approx(744.0)
    # A value already on the grid is left alone.
    assert AP.truncate_to_grid(1296.0) == pytest.approx(1296.0)


def test_quantise_leaves_a_value_alone_when_there_is_no_grid():
    assert AP.quantise(1234.5678, None) == 1234.5678
    assert AP.quantise(1234.5678, 4.0) == pytest.approx(1236.0)


# --------------------------------------------------------------------------
# 5 · reading the reference


def test_a_cp949_face_name_read_for_latin1_is_put_back_together():
    korean = "휴먼명조"
    mangled = korean.encode("cp949").decode("latin-1")
    assert mangled != korean
    assert AP.readable_font_name(mangled) == korean


def test_a_latin_face_name_is_left_alone():
    assert AP.readable_font_name("MalgunGothicBold") == "MalgunGothicBold"
    assert AP.readable_font_name("Batang") == "Batang"
    assert AP.readable_font_name(None) is None


def test_the_merge_carries_the_character_boxes_in_reading_order():
    # Two PyMuPDF records at one height are one laid-out line, and the
    # characters of both have to survive the regrouping in order or every
    # advance after the join is taken between the wrong pair.
    pieces = []
    for index, (text, x0) in enumerate((("가나", 0.0), ("다", 40.0))):
        boxes = [box(ch, x0 + 13 * step, 13, piece=(index, 0))
                 for step, ch in enumerate(text)]
        pieces.append({
            "page": 0, "text": text, "key": text, "chars": len(text),
            "top_hwp": 1000.0, "bottom_hwp": 2300.0,
            "x0_hwp": x0 * PT, "x1_hwp": (x0 + 13 * len(text)) * PT,
            "dir": (1.0, 0.0), "boxes": boxes,
        })
    merged = AP.merge_lines_with_boxes(pieces)
    assert len(merged) == 1
    assert [entry["c"] for entry in merged[0]["boxes"]] == ["가", "나", "다"]
    assert merged[0]["pieces"] == 2


def test_the_pdf_size_table_says_which_sizes_sit_on_the_grid():
    reports = [{"paragraphs": [{"lines": [{"chars": [
        {"size_pt": 13.0, "pdf_font": "Batang", "pdf_size": 12.96},
        {"size_pt": 13.0, "pdf_font": "Other", "pdf_size": 13.0},
    ]}]}]}]
    rows = {row["pdf_font"]: row for row in AP.pdf_size_table(reports)}
    assert rows["Batang"]["grid_pt"] == pytest.approx(12.96)
    assert rows["Batang"]["on_grid"] is True
    assert rows["Other"]["on_grid"] is False
