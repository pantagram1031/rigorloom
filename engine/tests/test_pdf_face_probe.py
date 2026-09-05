# -*- coding: utf-8 -*-
"""pdf_face_probe.py — what Hancom's export actually drew each glyph with.

The measurement is written up in ``engine/references/own-render-notes.md``.
What is pinned here is the MECHANISM, on synthetic input: every fixture below
is a PDF fragment built in the test, and nothing counts corpus glyphs, fonts,
forms or faces.

Five things:

  * a PDF number may have no leading digit — ``.001`` is how every
    ``FontMatrix`` in these exports is written, and reading it as ``001``
    turns a per-mille glyph space into a per-unit one;
  * an ``Encoding``'s ``Differences`` array may restart at a new code, so a
    glyph name is seated at the code the array puts it at and not at its
    position in ``Widths``;
  * a Type 3 glyph procedure is a real outline — ``d1`` then a path then a
    paint operator — and ``B`` with a line width in front of it is one
    outline STROKED, which is how a driver fakes a bold cut;
  * because of that, the outline fingerprint ignores the paint operator and
    its stroke width, so a filled glyph and its emboldened copy hash alike
    and two different shapes do not;
  * the em frame both sides of the identification are rasterised into is
    fixed, so the overlap score compares position and size as well as shape.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import pdf_face_probe as PFP  # noqa: E402


# -- PDF numbers ---------------------------------------------------------

def test_a_pdf_number_without_a_leading_digit_is_read_as_a_fraction():
    assert PFP._numbers("[.001 0 0 .001 0 0]") == [0.001, 0.0, 0.0,
                                                   0.001, 0.0, 0.0]


def test_a_negative_and_an_integer_number_are_read_beside_it():
    assert PFP._numbers("[0 -199 1000 1000]") == [0.0, -199.0, 1000.0, 1000.0]


# -- Encoding / Differences ----------------------------------------------

def test_a_differences_array_seats_names_at_consecutive_codes():
    names = PFP.parse_differences(
        "<</Type/Encoding/Differences[0/HFT1/HFT2/HFT3]>>")
    assert names == {0: "HFT1", 1: "HFT2", 2: "HFT3"}


def test_a_differences_array_restarts_at_the_code_it_names():
    """The failure this guards is silent: without the restart every glyph
    after it is read one seat early and gets another glyph's width."""
    names = PFP.parse_differences(
        "<</Type/Encoding/Differences[0/A/B 7/C/D]>>")
    assert names == {0: "A", 1: "B", 7: "C", 8: "D"}


def test_an_encoding_without_differences_names_nothing():
    assert PFP.parse_differences("/WinAnsiEncoding") == {}


# -- glyph procedures ----------------------------------------------------

FILLED = (b"332.000000 0.000000 0.000000 -199.000000 1000.000000 "
          b"1000.000000 d1\n \n285 726 m\n132 589 70 402 70 226 c\n"
          b"70 0 160 -152 281 -269 c\n304 -242 l\nh\nf\n")

STROKED = (b"332.000000 0.000000 0.000000 -199.000000 1000.000000 "
           b"1000.000000 d1\n \n285 726 m\n132 589 70 402 70 226 c\n"
           b"70 0 160 -152 281 -269 c\n304 -242 l\nh\n20 w\nB\n")

OTHER = (b"498.000000 0.000000 0.000000 -199.000000 1000.000000 "
         b"1000.000000 d1\n \n100 700 m\n400 700 l\n400 0 l\n100 0 l\n"
         b"h\nf\n")


def test_a_glyph_procedure_declares_its_own_advance_on_the_d1_operator():
    _paths, _paint, _width, declared = PFP.parse_charproc(FILLED)
    assert declared == 332.0


def test_a_glyph_procedure_is_a_path_and_the_curves_are_flattened():
    subpaths, paint, line_width, _declared = PFP.parse_charproc(FILLED)
    assert paint == "f"
    assert line_width == 0.0
    assert len(subpaths) == 1
    # moveto, two curves flattened into BEZIER_STEPS segments each, one line.
    assert len(subpaths[0]) == 1 + 2 * PFP.BEZIER_STEPS + 1


def test_a_stroked_glyph_carries_the_line_width_the_driver_emboldened_with():
    _paths, paint, line_width, _declared = PFP.parse_charproc(STROKED)
    assert paint == "B"
    assert line_width == 20.0


# -- the outline fingerprint ---------------------------------------------

def test_one_outline_filled_and_stroked_hashes_the_same():
    """HWP fakes a bold cut by stroking the regular outline.  The
    fingerprint has to see through that, or the two font objects that
    carry one design would never be recognised as one design."""
    assert PFP.outline_hash(FILLED) == PFP.outline_hash(STROKED)


def test_two_different_outlines_do_not_hash_the_same():
    assert PFP.outline_hash(FILLED) != PFP.outline_hash(OTHER)


# -- the em frame --------------------------------------------------------

def _box(x0, y0, x1, y1):
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]


def test_a_glyph_is_rasterised_into_the_fixed_em_frame():
    pytest.importorskip("PIL")
    mask = PFP.rasterise_outline(_box(0, 0, 1000, 1000), 0.001)
    inked = sum(mask.convert("L").point(lambda v: 1 if v else 0).getdata())
    expected = PFP.FINGERPRINT_PX_PER_EM ** 2
    # One em square, filled: the frame is in em, so the count is the square
    # of the frame's resolution, give or take the polygon's edge pixels.
    assert abs(inked - expected) <= 2 * PFP.FINGERPRINT_PX_PER_EM + 2


def test_identical_masks_overlap_completely_and_disjoint_ones_not_at_all():
    pytest.importorskip("PIL")
    left = PFP.rasterise_outline(_box(0, 0, 400, 400), 0.001)
    right = PFP.rasterise_outline(_box(600, 0, 1000, 400), 0.001)
    assert PFP.mask_iou(left, left) == pytest.approx(1.0)
    assert PFP.mask_iou(left, right) == pytest.approx(0.0)


def test_a_half_width_glyph_does_not_score_as_a_full_width_one():
    """The frame is in em and anchored on the origin, so a face whose
    advance agrees but whose glyph sits elsewhere does not score as a
    match."""
    pytest.importorskip("PIL")
    narrow = PFP.rasterise_outline(_box(0, 0, 500, 700), 0.001)
    wide = PFP.rasterise_outline(_box(0, 0, 1000, 700), 0.001)
    assert PFP.mask_iou(narrow, wide) == pytest.approx(0.5, abs=0.05)
