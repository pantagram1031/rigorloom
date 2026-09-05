# -*- coding: utf-8 -*-
"""page_fit_probe.py — what brackets the page-bottom fit test, and how.

The measurement this module supports is written up in
``engine/references/own-render-notes.md``; what is pinned here is the
MECHANISM, so that a later change to the fit rule has to move a named term
rather than a corpus tally.  No count of corpus events, forms or pages is
asserted anywhere below: the corpus is discovered, and the assertions are
about the relations the probe computes from a lineseg, not about how many of
them there happen to be.

Four things:

  * every candidate measure is an OFFSET added to ``vertpos``, derived from
    the lineseg's own attributes, with ``top`` and ``vertsize + spacing`` as
    the two ends of the bracket;
  * ``OwnRenderer._row_extent`` — the term the flow pass actually compares
    against the room left on the page — is ``baseline`` for a line of text,
    which is what makes it one of those candidates and not something else;
  * a line taller than the whole body box, and a line with no characters, are
    excluded from the kept-side evidence, because neither can refute a
    candidate: the first is placed by a guard that never runs the fit test
    and the second draws no ink;
  * the rejected-side evidence excludes a break that some OTHER rule already
    explains — a forced break, a ``keepWithNext`` push, a whole inline table
    moving, or a page whose room is taken by an anchored object no lineseg
    records.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import own_render  # noqa: E402
import page_fit_probe as PFP  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")


class _Seg:
    """The attribute bag ``_iattr`` reads, without an XML parse."""

    def __init__(self, **attrs):
        self._attrs = {k: str(v) for k, v in attrs.items()}

    def get(self, name, default=None):
        return self._attrs.get(name, default)


def seg(vertsize, spacing, baseline=None, textheight=None):
    attrs = {"vertsize": vertsize, "spacing": spacing,
             "textheight": textheight if textheight is not None else vertsize}
    if baseline is not None:
        attrs["baseline"] = baseline
    return _Seg(**attrs)


def test_every_candidate_is_an_offset_off_the_lineseg():
    """Each measure is computed from this line's own attributes, not a
    tolerance: the same lineseg gives the same offsets, and a taller line
    gives proportionally larger ones for every term that is not ``top``."""
    small = PFP.candidate_measures(seg(1000, 600, baseline=850))
    large = PFP.candidate_measures(seg(2000, 1200, baseline=1700))
    assert set(small) == set(PFP.MEASURE_ORDER)
    assert small["top"] == 0 and large["top"] == 0
    for name in PFP.MEASURE_ORDER:
        if name == "top":
            continue
        assert large[name] > small[name], name


@pytest.mark.parametrize("vertsize,spacing,baseline", [
    (1000, 600, 850), (1200, 516, 1020), (1400, 1120, 1190), (1900, 1140, 1615),
])
def test_the_bracket_has_a_widest_and_a_narrowest_end(vertsize, spacing,
                                                      baseline):
    """``top`` accepts everything any other candidate accepts and
    ``vertsize + spacing`` accepts the least, whatever the line's metrics —
    so those two are the ends of the bracket and the rest sit inside it.
    The candidates BETWEEN them are not ordered against each other: which of
    ``vertsize - spacing`` and half the line box is larger depends on the
    line's own spacing, which is why the report states each separately."""
    offsets = PFP.candidate_measures(seg(vertsize, spacing, baseline=baseline))
    assert offsets["top"] == min(offsets.values())
    assert offsets["vertsize_plus_spacing"] == max(offsets.values())


def test_baseline_is_absent_then_derived_from_textheight():
    """A lineseg that omits ``baseline`` still yields one, from the ratio the
    renderer measured on the corpus — otherwise the candidate would silently
    become ``top`` on any document that leaves the attribute out."""
    derived = PFP.candidate_measures(seg(1000, 600))["baseline"]
    assert derived == round(own_render.BASELINE_RATIO * 1000)


def test_the_flow_pass_compares_baseline_for_a_text_line():
    """``_row_extent`` IS one of the candidates, and which one it is decides
    every page break this renderer makes.  A change to the fit rule has to
    move this assertion."""
    offsets = PFP.candidate_measures(seg(1000, 600, baseline=850))
    extent = own_render.OwnRenderer._row_extent(850, 1000, None)
    assert extent == offsets["baseline"]


def test_a_line_carrying_an_inline_table_clears_its_whole_box():
    """A table has no descender to hang past the margin, so the permissive
    reading does not apply to it: the extent is the full box."""
    assert own_render.OwnRenderer._row_extent(850, 1000, object()) == 1000


def test_a_line_taller_than_the_page_is_not_kept_side_evidence():
    """It is placed by ``_place_block``'s ``cursor > 0`` guard, which never
    consults the fit test, so its overhang says nothing about the rule."""
    usable = 70000
    assert PFP.classify({"vertsize": usable + 1}, True, usable) == \
        "taller_than_page"
    assert PFP.classify({"vertsize": 1000}, True, usable) == "text"


def test_a_line_with_no_characters_is_not_kept_side_evidence():
    assert PFP.classify({"vertsize": 1000}, False, 70000) == "empty"


def _event(**over):
    base = {
        "deepest_class": "text",
        "next_class": "text",
        "next_forced": False,
        "last_keep_with_next": False,
        "next_has_inline_table": False,
        "page_has_floating_object": False,
    }
    base.update(over)
    return base


@pytest.mark.parametrize("field", [
    "next_forced", "last_keep_with_next", "next_has_inline_table",
    "page_has_floating_object",
])
def test_a_break_another_rule_explains_is_not_rejected_side_evidence(field):
    """Each of these breaks a page on its own account.  Counting it as the
    fit test refuting a candidate is how a measurement talks itself into a
    rule the document never demonstrated."""
    assert PFP.is_evidence_rejected(_event())
    assert not PFP.is_evidence_rejected(_event(**{field: True}))


def test_the_kept_side_admits_only_a_text_line():
    assert PFP.is_evidence_kept(_event())
    assert not PFP.is_evidence_kept(_event(deepest_class="empty"))
    assert not PFP.is_evidence_kept(_event(deepest_class="taller_than_page"))


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="corpus absent")
def test_the_corpus_report_states_a_verdict_per_candidate():
    """End to end on one discovered form: every candidate gets a kept and a
    rejected column and a consistency verdict, and the verdict follows from
    the two violation counts rather than being asserted separately."""
    forms = sorted(f for f in os.listdir(CORPUS) if f.endswith(".hwpx"))
    assert forms, "no corpus form discovered"
    report = PFP.probe_document(os.path.join(CORPUS, forms[0]))
    summary = PFP.summarise([report])
    assert set(summary["measures"]) == set(PFP.MEASURE_ORDER)
    for name in PFP.MEASURE_ORDER:
        row = summary["measures"][name]
        assert row["consistent"] == (row["kept_violations"] == 0
                                     and row["rejected_violations"] == 0)
