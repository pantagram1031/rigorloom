# -*- coding: utf-8 -*-
"""hft_width_table.py — the stand-in advance rules, priced on top of the table.

The measurement is written up in ``engine/references/own-render-notes.md``.
What is pinned here is the MECHANISM, on synthetic input: no fixture below
counts a corpus character, line, paragraph or face, and no number below is a
tally of anything the corpus happens to contain.

Five things:

  * a variant name resolves to a renderer, and the name says whether the
    MEASURED HFT table is in front of the rule;
  * installing a variant is reversible — the module attributes it rebinds
    come back;
  * the stand-in gate is the face's ``source``, and ``bundled`` is the
    narrower of the two populations the rules are scored over;
  * each rule is the arithmetic it claims: a full cell for a full-width
    character, the running total on the 1/600 inch pen grid, the stand-in's
    own advance times a measured per-face factor;
  * a probe that overrides the renderer's advance seam has to have the
    seam's signature, or it is scoring a renderer that does not exist.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import advance_probe as AP  # noqa: E402
import hft_width_table as HWT  # noqa: E402
import own_render  # noqa: E402


PT = own_render.HWPUNIT_PER_PT

#: The synthetic run every rule below is asked about: 13 pt, no ``hh:ratio``
#: scaling, so one full-width cell is exactly ``13 * HWPUNIT_PER_PT``.
SIZE_PT = 13.0
CELL = SIZE_PT * PT

#: What the stand-in's own outlines say, in em.  Deliberately not 1.0 for the
#: full-width character — that gap is the thing every rule is about.
STANDIN_FULL_EM = 0.95
STANDIN_LATIN_EM = 0.5


class FakeBase:
    """The renderer's advance seam, reduced to the parts a rule touches.

    Standing in for ``OwnRenderer`` so a rule can be exercised without a
    document: the seam returns the stand-in face's own measurement, the HFT
    table has nothing to say, and the face resolution is whatever the test
    puts in it.
    """

    def __init__(self, source="bundled", declared="휴먼명조"):
        self.defs = {"fontfaces": {"HANGUL": {1: declared}}}
        self.face_resolution = {
            (declared, "hangul", False): {"source": source},
        }

    def _charpr(self, cid):
        return {"font_ids": {"HANGUL": 1}, "bold": False, "height_pt": SIZE_PT}

    def _hft_advance_hwp(self, font, chunk, cid, slot, pt, ratio, rel_sz):
        return None

    def _em_width(self, font, text):
        return sum(STANDIN_FULL_EM if own_render.is_full_width(ch)
                   else STANDIN_LATIN_EM for ch in text)

    def _metric_font_for_pt(self, cid, pt, slot, drawn):
        return drawn

    def _advance_hwp(self, font, chunk, cid, slot, pt, ratio, rel_sz=100):
        return self._em_width(font, chunk) * pt * PT * ratio / 100.0


def renderer_with(mixin, **kwargs):
    """``mixin`` in front of :class:`FakeBase`, ready to be asked for a width."""
    return type("Probe", (mixin, FakeBase), {})(**kwargs)


def advance(renderer, chunk):
    return renderer._advance_hwp(None, chunk, "0", "hangul", SIZE_PT, 100.0)


# -- variant names --------------------------------------------------------

@pytest.mark.parametrize("name", sorted(HWT.VARIANT_SPECS))
def test_every_variant_name_builds_a_renderer(name):
    """A name in the spec table resolves to a renderer and a break recorder."""
    renderer_cls, recorder_cls = HWT.variant_classes(name)
    assert issubclass(renderer_cls, own_render.OwnRenderer)
    assert issubclass(recorder_cls, AP.BreakRecordingRenderer)


@pytest.mark.parametrize("name", sorted(HWT.VARIANT_SPECS))
def test_the_name_says_whether_the_measured_table_is_in_front(name):
    """``table`` in the name means the MEASURED widths are consulted first.

    The control for every rule below is the shipped renderer with the table
    switched off, and switching it off is a mixin rather than a second model
    of the renderer -- so which one a name gets has to be the name's doing.
    """
    renderer_cls, _recorder = HWT.variant_classes(name)
    has_table = HWT.NoTableMixin not in renderer_cls.__mro__
    assert has_table is HWT.VARIANT_SPECS[name][0]
    assert has_table is name.startswith("table")


@pytest.mark.parametrize("name", HWT.VARIANTS + HWT.STANDIN_VARIANTS)
def test_the_scored_lists_only_name_variants_that_exist(name):
    assert name in HWT.VARIANT_SPECS


def test_the_stand_in_list_is_read_against_the_table_alone():
    """Every flip is reported against a baseline, and it is ``table``."""
    assert HWT.STANDIN_VARIANTS[0] == "table"
    assert HWT.VARIANT_SPECS["table"] == (True, None)


def test_installing_a_variant_puts_the_modules_back():
    before = (own_render.OwnRenderer, AP.BreakRecordingRenderer)
    with HWT.variant("table+cell"):
        assert own_render.OwnRenderer is not before[0]
        assert AP.BreakRecordingRenderer is not before[1]
    assert (own_render.OwnRenderer, AP.BreakRecordingRenderer) == before


def test_a_variant_is_restored_even_when_the_measurement_raises():
    before = (own_render.OwnRenderer, AP.BreakRecordingRenderer)
    with pytest.raises(ValueError):
        with HWT.variant("table+cell"):
            raise ValueError("the measurement fell over")
    assert (own_render.OwnRenderer, AP.BreakRecordingRenderer) == before


# -- the gate -------------------------------------------------------------

def test_an_installed_face_is_untouched_by_every_rule():
    """The control: a face the machine HAS keeps its own outlines' advance."""
    for mixin in (HWT.CellRuleMixin, HWT.BundledCellRuleMixin,
                  HWT.FullWidthCharRuleMixin, HWT.PenGridCellRuleMixin,
                  HWT.ScaleRuleMixin):
        probe = renderer_with(mixin, source="installed")
        assert advance(probe, "가나") == pytest.approx(
            2 * STANDIN_FULL_EM * CELL)


def test_the_bundled_gate_is_narrower_than_the_substituted_one():
    """``system`` is a machine fallback; ``bundled`` is the map this repo chose.

    #283 priced the cell rule over both together.  The narrower gate has to
    be a different population or scoring it says nothing.
    """
    assert set(HWT.BundledCellRuleMixin.standin_sources) < \
        set(HWT.StandinMixin.standin_sources)
    wide = renderer_with(HWT.CellRuleMixin, source="system")
    narrow = renderer_with(HWT.BundledCellRuleMixin, source="system")
    assert advance(wide, "가나") == pytest.approx(2 * CELL)
    assert advance(narrow, "가나") == pytest.approx(
        2 * STANDIN_FULL_EM * CELL)


def test_a_face_the_resolver_never_saw_is_not_a_stand_in():
    """No record means no opinion, which is the answer that changes nothing."""
    probe = renderer_with(HWT.CellRuleMixin)
    probe.face_resolution.clear()
    assert advance(probe, "가나") == pytest.approx(
        2 * STANDIN_FULL_EM * CELL)


# -- the rules ------------------------------------------------------------

def test_the_cell_rule_gives_a_full_width_character_the_declared_cell():
    probe = renderer_with(HWT.CellRuleMixin)
    assert advance(probe, "가나다") == pytest.approx(3 * CELL)


def test_the_cell_rule_gives_up_on_a_chunk_that_is_not_all_full_width():
    """One Latin character and the whole chunk keeps the stand-in's metric."""
    probe = renderer_with(HWT.CellRuleMixin)
    assert advance(probe, "가A") == pytest.approx(
        (STANDIN_FULL_EM + STANDIN_LATIN_EM) * CELL)


def test_the_per_character_rule_keeps_the_full_cells_out_of_a_mixed_chunk():
    """The same claim about the same characters, Latin left on the face.

    #283 measured 131 substituted Latin/digit characters in the whole corpus,
    123 of them one face and one class: there is no per-face Latin table to
    be had, so Latin keeps the only answer available for it.
    """
    probe = renderer_with(HWT.FullWidthCharRuleMixin)
    assert advance(probe, "가A") == pytest.approx(
        CELL + STANDIN_LATIN_EM * CELL)
    assert advance(probe, "AB") == pytest.approx(
        2 * STANDIN_LATIN_EM * CELL)


def test_the_pen_grid_is_one_six_hundredth_of_an_inch():
    assert HWT.PEN_GRID_HWP == pytest.approx(
        own_render.HWPUNIT_PER_INCH / 600.0)


def test_the_pen_rule_rounds_the_RUNNING_TOTAL_and_not_each_advance():
    """#283's correction: the grid is on the pen, so only the total moves.

    Rounding each advance instead would take a whole grid step off every
    character of a run; the difference between the two is what #267's
    "advance = size on the grid" rule cost.
    """
    probe = renderer_with(HWT.PenGridCellRuleMixin)
    grid = HWT.PEN_GRID_HWP
    for count in (1, 2, 3, 7):
        chunk = "가" * count
        assert advance(probe, chunk) == pytest.approx(
            round(count * CELL / grid) * grid)
    per_character = 4 * (round(CELL / grid) * grid)
    assert advance(probe, "가가가가") != pytest.approx(per_character)


def test_the_pen_rule_never_moves_a_chunk_by_more_than_half_a_step():
    probe = renderer_with(HWT.PenGridCellRuleMixin)
    for count in range(1, 12):
        chunk = "가" * count
        assert abs(advance(probe, chunk) - count * CELL) <= \
            HWT.PEN_GRID_HWP / 2 + 1e-9


def test_the_scale_rule_multiplies_the_stand_ins_own_advance():
    """A measured factor per DECLARED face, applied to what we measured."""
    probe = renderer_with(HWT.ScaleRuleMixin)
    probe.standin_scale = {"휴먼명조": 1 / STANDIN_FULL_EM}
    assert advance(probe, "가나") == pytest.approx(2 * CELL)
    assert advance(probe, "AB") == pytest.approx(
        2 * STANDIN_LATIN_EM * CELL / STANDIN_FULL_EM)


def test_the_scale_rule_with_no_measurement_for_the_face_changes_nothing():
    probe = renderer_with(HWT.ScaleRuleMixin)
    probe.standin_scale = {"some other face": 2.0}
    assert advance(probe, "가나") == pytest.approx(
        2 * STANDIN_FULL_EM * CELL)


def test_the_measured_table_wins_where_it_speaks():
    """Every rule here is a model; the table is read off Hancom's own output.

    A chunk the MEASURED table covers must not be re-answered by a rule, or
    the variant is not "the table plus a rule" but a rule that shadows it.
    """
    for mixin in (HWT.CellRuleMixin, HWT.BundledCellRuleMixin,
                  HWT.FullWidthCharRuleMixin, HWT.PenGridCellRuleMixin,
                  HWT.ScaleRuleMixin):
        probe = renderer_with(mixin)
        probe.standin_scale = {"휴먼명조": 4.0}
        probe._hft_advance_hwp = (
            lambda font, chunk, cid, slot, pt, ratio, rel_sz: 123.0)
        assert advance(probe, "가나") == pytest.approx(123.0)


# -- the flip report ------------------------------------------------------

def _paragraph(match, spans, widths, column=1000.0, installed=False):
    return {"address": 1, "installed": installed, "match": match,
            "cache_breaks": [2], "computed_breaks": [span[1] for span
                                                     in spans[:-1]],
            "column_hwp": column, "our_widths": widths,
            "our_spans": [list(span) for span in spans]}


def test_a_flip_names_the_first_line_whose_span_moved():
    baseline = {"paragraphs": {("form", 1): _paragraph(
        True, [(0, 2), (2, 4)], [900.0, 400.0])}}
    after = {"variant": "table+cell", "paragraphs": {("form", 1): _paragraph(
        False, [(0, 1), (1, 4)], [500.0, 800.0])}}
    flip, = HWT.break_flips(baseline, after)
    assert flip["form"] == "form"
    assert flip["gained"] is False
    assert flip["line"] == 0
    assert flip["before_hwp"] == 900.0
    assert flip["after_hwp"] == 500.0


def test_a_paragraph_that_did_not_change_verdict_is_not_a_flip():
    rows = {("form", 1): _paragraph(True, [(0, 2), (2, 4)], [900.0, 400.0])}
    assert HWT.break_flips({"paragraphs": rows},
                           {"variant": "x", "paragraphs": rows}) == []


def test_a_gain_and_a_loss_are_told_apart():
    baseline = {"paragraphs": {
        ("form", 1): _paragraph(False, [(0, 1), (1, 4)], [500.0, 800.0]),
        ("form", 2): _paragraph(True, [(0, 2), (2, 4)], [900.0, 400.0])}}
    after = {"variant": "x", "paragraphs": {
        ("form", 1): _paragraph(True, [(0, 2), (2, 4)], [900.0, 400.0]),
        ("form", 2): _paragraph(False, [(0, 1), (1, 4)], [500.0, 800.0])}}
    flips = HWT.break_flips(baseline, after)
    assert [flip["gained"] for flip in flips] == [True, False]


# -- the seam ------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    AP.RuleRenderer, HWT.CellRuleMixin, HWT.FullWidthCharRuleMixin,
    HWT.PenGridCellRuleMixin, HWT.ScaleRuleMixin,
])
def test_a_probe_override_has_the_seams_signature(cls):
    """#292 gave ``_advance_hwp`` a ``rel_sz`` and the probe kept six arguments.

    An override whose signature has drifted does not score a candidate rule
    against the renderer: it raises, or worse, silently drops the argument
    the renderer now passes.
    """
    seam = inspect.signature(own_render.OwnRenderer._advance_hwp)
    assert list(inspect.signature(cls._advance_hwp).parameters) == \
        list(seam.parameters)


def test_the_break_scoreboard_carries_what_a_flip_has_to_explain():
    """A named flip is only half an answer without the width that moved."""
    source = inspect.getsource(AP.break_scoreboard)
    for key in ("column_hwp", "our_widths", "our_spans"):
        assert f'"{key}"' in source
