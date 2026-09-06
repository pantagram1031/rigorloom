# -*- coding: utf-8 -*-
"""``syllable_break_probe`` — the cut partition and the narrowing seam.

What the probe claims is that a cached line end can be READ: the pair of
characters it fell between says whether the authoring engine honoured
``breakNonLatinWord="KEEP_WORD"`` there or broke a 어절 in half.  Everything
the notes conclude rests on that partition being total and on each narrowing
being exactly ``own_render.break_opportunities`` with one extra clause, so
that is what is pinned here.

Two real cached cuts are pinned as well — the gain case and the regression
case the notes are argued from — because a corpus reading that no test can
falsify is not evidence.  Both are cache reads: no render, no reference PDF.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import own_render  # noqa: E402
import syllable_break_probe as probe  # noqa: E402

CORPUS = ROOT / "tests" / "corpus" / "forms" / "converted"


def _form(stem):
    path = CORPUS / (stem + ".hwpx")
    if not path.is_file():
        pytest.skip(f"corpus fixture missing: {path}")
    return path


def _paragraph(stem, address):
    """One corpus paragraph and its cached cuts, off the XML alone."""
    renderer = own_render.OwnRenderer(_form(stem), repo_root=ROOT)
    for section in renderer.sections:
        for element in section.iter():
            if own_render._local(element.tag) != "p":
                continue
            if renderer.paragraph_index.get(id(element)) != address:
                continue
            para = own_render.Paragraph(element, renderer.defs["para_pr"])
            return para, probe.cached_cuts(para)
    raise AssertionError(f"{stem} has no paragraph {address}")


# -- the partition --------------------------------------------------------

def test_every_cut_gets_exactly_one_class_and_the_classes_are_the_named_ones():
    """The partition is total: no pair of characters falls outside it."""
    sample = "  가價ァaZ0９.,()「」-/\t"
    for prev in sample:
        for nxt in sample:
            assert probe.cut_class(prev, nxt) in probe.CUT_CLASSES


def test_a_cut_between_two_hangul_syllables_is_read_as_inside_a_word():
    assert probe.cut_class("장", "에") == "inside-cjk-word"
    assert probe.cut_class("가", "價") == "inside-cjk-word"


def test_whitespace_on_either_side_is_a_word_boundary_whatever_else_is_there():
    assert probe.cut_class(" ", "관") == "space"
    assert probe.cut_class("관", " ") == "space"
    assert probe.cut_class("　", "a") == "space"


def test_latin_and_digit_runs_are_their_own_classes_not_script_changes():
    assert probe.cut_class("a", "b") == "inside-latin-word"
    assert probe.cut_class("6", "1") == "inside-digit-group"
    assert probe.cut_class("３", "４") == "inside-digit-group"
    # Hangul against a digit is a change of script inside one 어절, which is
    # the shape ``saeopja`` ¶189 and ``moel-2013`` ¶215 cut at.
    assert probe.cut_class("3", "항") == "script-change"
    assert probe.cut_class("조", "3") == "script-change"


def test_punctuation_on_either_side_outranks_the_scripts_around_it():
    assert probe.cut_class("과", "(") == "punctuation"
    assert probe.cut_class(")", "은") == "punctuation"
    assert probe.cut_class("」", "、") == "punctuation"


# -- the narrowing seam ---------------------------------------------------

def test_a_narrowing_only_ever_adds_to_what_the_paragraph_declares():
    """Every narrowing is a superset of the declared set, never a subset.

    That is what makes the score readable: a candidate can only move a break
    LATER, so a paragraph it loses is one where the cache stopped short of
    the widest span our metric says fits.

    The baseline here is the DECLARED semantics -- ``breakNonLatinWord``
    obeyed as written -- which is no longer what
    ``own_render.break_opportunities`` returns: the renderer now breaks Hangul
    at the syllable under either value (#316).  ``narrowed`` with a predicate
    that never fires is exactly the old shipped rule, so it is the honest
    baseline for the property this test is about.
    """
    declared_rule = probe.narrowed(lambda a, b: False)
    text = "근로자의 교부요구와 관계없이 3항 abc 처리"
    for declared_latin in ("KEEP_WORD", "BREAK_WORD"):
        for declared_cjk in ("KEEP_WORD", "BREAK_WORD"):
            base = set(declared_rule(text, declared_latin, declared_cjk))
            for name, (_basis, predicate) in probe.NARROWINGS.items():
                widened = set(probe.narrowed(predicate)(
                    text, declared_latin, declared_cjk))
                assert base <= widened, name


def test_the_shipped_breaker_now_reproduces_the_syllable_candidate_exactly():
    """The switch is the probe's own candidate, by construction (#316, #320).

    The point of the seam is that the number the probe scored and the
    behaviour the renderer ships cannot drift: whatever
    ``own_render.break_opportunities`` does must equal what
    ``narrowed(NARROWINGS['syllable'])`` does, on the paragraph the argument
    turns on and under every declared pair.  If someone re-narrows the rule
    without re-scoring it, this fails.
    """
    para, _cuts = _paragraph("moel-pyojun-geunrogyeyakseo-2013", 261)
    candidate = probe.narrowed(probe.NARROWINGS["syllable"][1])
    assert para.para_pr["break_non_latin"] == "KEEP_WORD"
    for declared_latin in ("KEEP_WORD", "BREAK_WORD"):
        for declared_cjk in ("KEEP_WORD", "BREAK_WORD"):
            assert (own_render.break_opportunities(
                        para.text, declared_latin, declared_cjk)
                    == candidate(para.text, declared_latin, declared_cjk))
    # Not vacuous: the paragraph really does carry Hangul boundaries that the
    # declared KEEP_WORD would have closed.
    shipped = own_render.break_opportunities(para.text, "KEEP_WORD",
                                             "KEEP_WORD")
    declared = probe.narrowed(lambda a, b: False)(para.text, "KEEP_WORD",
                                                  "KEEP_WORD")
    assert len(shipped) > len(declared)


def test_the_syllable_narrowing_is_break_word_forced_on_and_nothing_else():
    text = "예금통장에 지급 61조3항 abc, 처리"
    forced = own_render.break_opportunities(text, "KEEP_WORD", "BREAK_WORD")
    predicate = probe.NARROWINGS["syllable"][1]
    assert probe.narrowed(predicate)(text, "KEEP_WORD", "KEEP_WORD") == forced


def test_cjk_cjk_keeps_latin_words_digit_groups_and_punctuation_whole():
    """The synthetic counter-case: the narrowing that is NOT the syllable one.

    ``syllable`` opens every boundary with a CJK cell on one side, including
    the boundary against a Latin word or a bracket.  ``cjk-cjk`` opens only
    the boundary between two CJK cells, so the same string yields a strictly
    smaller set — and the boundaries it drops are exactly the ones whose
    other side is not a CJK cell.
    """
    text = "제61조3항abc가"
    predicate = probe.NARROWINGS["cjk-cjk"][1]
    wide = set(probe.narrowed(probe.NARROWINGS["syllable"][1])(
        text, "KEEP_WORD", "KEEP_WORD"))
    tight = set(probe.narrowed(predicate)(text, "KEEP_WORD", "KEEP_WORD"))
    assert tight < wide
    for index in wide - tight:
        prev, nxt = text[index - 1], text[index]
        assert not (own_render.break_class(prev) in ("CJK", "OBJECT")
                    and own_render.break_class(nxt) in ("CJK", "OBJECT"))
    for index in tight:
        prev, nxt = text[index - 1], text[index]
        assert own_render.break_class(prev) in ("CJK", "OBJECT")
        assert own_render.break_class(nxt) in ("CJK", "OBJECT")


def test_the_geumchik_filter_survives_every_narrowing():
    """A narrowing may not smuggle a forbidden line start past 금칙.

    ``own_render.break_opportunities`` applies the prohibition table last and
    uniformly; each narrowing re-applies it around its own clause, and this
    is the pin that it really does.
    """
    text = "처리가.있고" + "니」다"
    for _basis, predicate in probe.NARROWINGS.values():
        for index in probe.narrowed(predicate)(text, "KEEP_WORD",
                                               "KEEP_WORD"):
            assert text[index] not in own_render.LINE_START_PROHIBITED
            assert text[index - 1] not in own_render.LINE_END_PROHIBITED


# -- the two cached cuts the notes are argued from ------------------------

def test_the_cache_cuts_inside_a_hangul_word_in_a_keep_word_paragraph():
    """The gain case: ``moel-2013`` ¶261, 예금통장|에.

    The paragraph declares ``KEEP_WORD`` and the cache still put a line end
    between two syllables of one 어절.  This is the reading the whole slice
    turns on, so it is pinned rather than quoted.
    """
    para, cuts = _paragraph("moel-pyojun-geunrogyeyakseo-2013", 261)
    assert para.para_pr["break_non_latin"] == "KEEP_WORD"
    assert cuts, "¶261 has no cached line end"
    cut = cuts[0]
    assert para.text[cut - 1] == "장"
    assert para.text[cut] == "에"
    assert probe.cut_class(para.text[cut - 1], para.text[cut]) \
        == "inside-cjk-word"


def test_the_cache_stops_at_the_space_in_the_regression_paragraph():
    """The regression case: ``moel-2025`` ¶25, 성실하게 |이행하여야.

    Same declared value, same alignment, and here the cache DID stop at the
    어절 boundary — with room, by our own metric, for the next syllable.  The
    pair is what rules out a rule that reads only the characters.
    """
    para, cuts = _paragraph("moel-pyojun-geunrogyeyakseo-2025", 25)
    assert para.para_pr["break_non_latin"] == "KEEP_WORD"
    assert para.para_pr["align"] == "JUSTIFY"
    assert cuts == [45]
    assert para.text[44] == " "
    assert para.text[45] == "이"
    assert probe.cut_class(para.text[44], para.text[45]) == "space"


def test_the_probe_names_every_candidate_it_orders_and_gives_each_a_basis():
    assert probe.CANDIDATE_ORDER[0] == "shipped"
    assert set(probe.CANDIDATE_ORDER[1:]) == set(probe.NARROWINGS)
    for _name, (basis, predicate) in probe.NARROWINGS.items():
        assert basis.strip()
        assert callable(predicate)


def test_the_probe_leaves_the_module_level_breaker_where_it_found_it():
    base = own_render.break_opportunities
    with probe.installed("cjk-cjk"):
        assert own_render.break_opportunities is not base
    assert own_render.break_opportunities is base
    with probe.installed("shipped"):
        assert own_render.break_opportunities is base
    assert own_render.break_opportunities is base


def test_the_renderer_does_not_import_the_probe_that_measures_it():
    """The instrument stays outside the thing it measures.

    #316 shipped nothing and pinned that.  This branch DOES ship the syllable
    unit, so the surviving property is the weaker and more useful one: the
    renderer must not depend on the probe.  The probe rebinds the renderer's
    module-level breaker; a renderer that imported the probe back would make
    the seam circular and the scores unreadable.
    """
    source = (ROOT / "engine" / "scripts" / "own_render.py").read_text(
        encoding="utf-8")
    assert "import syllable_break_probe" not in source
    assert os.path.isfile(ROOT / "engine" / "scripts"
                          / "syllable_break_probe.py")
    # The choice the renderer did make is declared in the renderer itself.
    assert own_render.KOREAN_BREAK_UNIT["declaration_honored"] is False
