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


# -- the offset scan ------------------------------------------------------
#
# The bracket above takes ``usable_height`` as given.  These pin the
# arithmetic of asking what happens when it is not: the band is closed-open,
# it says the same thing as the two violation counts printed beside it, and
# the named candidates are read off the document's own margins rather than
# chosen from a list of constants that happen to fit.


def test_the_band_is_the_kept_maximum_up_to_the_rejected_minimum():
    """``[max(kept), min(rejected))``.  An offset at the low end is exactly
    large enough to accept every kept line; one at the high end has grown the
    body box until it would have accepted a line Hancom moved."""
    lo, hi = PFP.evidence_band([-296, -1000, -50], [911, 1014, 4032])
    assert (lo, hi) == (-50, 911)


def test_a_side_with_no_evidence_does_not_bound_the_offset():
    assert PFP.evidence_band([], [700]) == (None, 700)
    assert PFP.evidence_band([-5], []) == (-5, None)
    assert PFP.evidence_band([], []) == (None, None)


def test_the_band_and_the_violation_counts_are_the_same_statement():
    """Whatever the scan prints at an offset has to agree with the band it
    prints beside it, or one of the two is decoration."""
    kept, rejected = [-296, -720], [395, 911]
    lo, hi = PFP.evidence_band(kept, rejected)
    for offset in range(-1000, 1500, 37):
        k = sum(1 for v in kept if v - offset > 0)
        r = sum(1 for v in rejected if v - offset <= 0)
        assert (k == 0 and r == 0) == (lo <= offset < hi)


def test_the_named_offsets_are_this_document_s_own_margin_terms():
    """Each named candidate is a term ``page_geometry`` subtracts from the
    body box, read off the section."""
    report = {"document": "d.hwpx", "events": [], "sections": [
        {"margin": {"header": 332, "footer": 2936}, "headers": 0,
         "footers": 0},
    ]}
    named = PFP.named_offsets(report)
    assert named["zero"] == 0
    assert named["header"] == 332
    assert named["footer"] == 2936
    assert named["header_plus_footer"] == 3268
    # No hp:footer in the section, so the narrower reading offers the band
    # back; with one declared it offers nothing.
    assert named["footer_if_no_footer"] == 2936
    report["sections"][0]["footers"] = 1
    assert PFP.named_offsets(report)["footer_if_no_footer"] == 0


def test_the_scan_reports_every_form_and_a_joint_band():
    """The joint band is an intersection, so a rule has to clear the worst
    form rather than the average one."""
    reports = [
        {"document": "a.hwpx", "events": [], "sections": [
            {"margin": {"header": 0, "footer": 0}, "headers": 0,
             "footers": 0}]},
        {"document": "b.hwpx", "events": [], "sections": [
            {"margin": {"header": 0, "footer": 0}, "headers": 0,
             "footers": 0}]},
    ]
    scan = PFP.offset_scan(reports, lo=-100, hi=100, step=50)
    assert set(scan["per_form"]) == {"a", "b"}
    assert scan["grid"] == [-100, -50, 0, 50, 100]
    for name in PFP.SCAN_MEASURES:
        assert scan["joint"][name]["band"] == [None, None]


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="corpus absent")
def test_the_joint_band_is_inside_every_form_s_own_band():
    forms = sorted(f for f in os.listdir(CORPUS) if f.endswith(".hwpx"))
    assert forms, "no corpus form discovered"
    reports = [PFP.probe_document(os.path.join(CORPUS, f)) for f in forms[:3]]
    scan = PFP.offset_scan(reports, lo=0, hi=0, step=1)
    for name in PFP.SCAN_MEASURES:
        jlo, jhi = scan["joint"][name]["band"]
        for entry in scan["per_form"].values():
            lo, hi = entry["measures"][name]["band"]
            if lo is not None:
                assert jlo is not None and jlo >= lo
            if hi is not None:
                assert jhi is not None and jhi <= hi


# -- the body box against the reference PDF -------------------------------


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="corpus absent")
def test_the_reference_ink_is_measured_against_the_derived_body_box():
    """The mode reports the derived box and the drawn extent side by side,
    per page, so an offset hypothesis has a number to survive; the ruling and
    the glyph boxes stay apart, because a form's paper-spec line is drawn in
    the bottom margin and is evidence about nothing."""
    fitz = pytest.importorskip("fitz")
    assert fitz is not None
    render = os.path.join(ROOT, "tests", "corpus", "forms", "render")
    forms = sorted(f for f in os.listdir(CORPUS) if f.endswith(".hwpx"))
    pair = next(((f, os.path.join(render, f[:-5] + ".pdf")) for f in forms
                 if os.path.exists(os.path.join(render, f[:-5] + ".pdf"))),
                None)
    if pair is None:
        pytest.skip("no reference PDF beside the corpus")
    record = PFP.reference_ink(os.path.join(CORPUS, pair[0]), pair[1],
                               repo_root=ROOT)
    renderer = own_render.OwnRenderer(os.path.join(CORPUS, pair[0]),
                                      repo_root=ROOT)
    renderer._current_section = 0
    geo = renderer.page_geometry()
    assert record["body_top"] == geo["body_top"]
    assert record["body_bottom"] == geo["body_top"] + geo["usable_height"]
    assert record["margin_bottom"] == geo["height"] - geo["margin"]["bottom"]
    assert record["pages"]
    for page in record["pages"]:
        for key in ("vector_top", "vector_bottom", "text_top", "text_bottom"):
            assert key in page


# --------------------------------------------------------------------------
# --scan-all: the direct scan, on synthetic linesegs
#
# The scan drops the page-break structure and measures every cached line
# where it was seated, so what has to be pinned is the arithmetic that turns
# a seat into an overhang and the exclusions that decide whether the overhang
# is evidence.  Nothing below reads the corpus: the records are built here,
# so a form gaining or losing a page cannot move an assertion.
# --------------------------------------------------------------------------

def scanned(rel_top, vertsize=1000, spacing=600, usable=70000,
            container="top-level", **over):
    """One ``SeatScanner`` record, built by hand."""
    line = seg(vertsize, spacing, baseline=over.pop("baseline", None))
    record = {
        "form": "synthetic",
        "page": 0,
        "para": 0,
        "lineseg": 0,
        "container": container,
        "table": 0 if container == "cell" else None,
        "row": 0 if container == "cell" else None,
        "col": 0 if container == "cell" else None,
        "table_may_split": True if container == "cell" else None,
        "under_anchor": False,
        "inline_table": False,
        "usable": usable,
        "body_top": 6000,
        "rel_top": rel_top,
        "line_class": "text",
        "on_sheet": True,
        "text": "x",
        "vertsize": vertsize,
        "spacing": spacing,
        "overhang": PFP.line_overhangs(rel_top, line, usable),
    }
    record.update(over)
    record["excluded"] = PFP.scan_evidence_reason(record)
    record["evidence"] = record["excluded"] is None
    return record


def test_an_overhang_is_the_seat_plus_the_measure_less_the_body_box():
    """The whole arithmetic of the scan, stated once.  A line seated one
    HWPUNIT lower overhangs one HWPUNIT more under EVERY candidate, and the
    spread between candidates is the spread between their offsets — the scan
    adds no term of its own to what ``candidate_measures`` already says."""
    line = seg(1000, 600, baseline=850)
    usable = 70000
    low = PFP.line_overhangs(69000, line, usable)
    lower = PFP.line_overhangs(69001, line, usable)
    offsets = PFP.candidate_measures(line)
    for name in PFP.MEASURE_ORDER:
        assert lower[name] - low[name] == 1
        assert low[name] == 69000 + offsets[name] - usable


def test_a_seat_that_misses_the_paper_is_not_a_fit_test_decision():
    """kstartup's table 36 declares an unsigned-wrapped ``vertOffset`` and
    seats its cells four thousand million HWPUNIT down the page.  A scan that
    took that for a Hancom decision would report the largest overhang in the
    corpus off a coordinate no page has, so the geometric test is whether the
    box intersects the sheet at all."""
    page_height, body_top = 84188, 6000
    assert PFP.seat_on_sheet(60000, 1000, body_top, page_height)
    assert not PFP.seat_on_sheet(4294967000, 1000, body_top, page_height)
    # A box that starts above the paper but reaches onto it is still on it;
    # one that ends before the paper starts is not.
    assert PFP.seat_on_sheet(-body_top - 500, 1000, body_top, page_height)
    assert not PFP.seat_on_sheet(-body_top - 2000, 1000, body_top,
                                 page_height)


@pytest.mark.parametrize("over,reason", [
    ({}, None),
    ({"line_class": "empty"}, "empty line"),
    ({"line_class": "taller_than_page"}, "line taller than the body box"),
    ({"on_sheet": False}, "seat off the sheet (a wild anchor offset)"),
    ({"container": "cell", "table_may_split": False},
     "cell of a table that may not split"),
    ({"container": "cell", "table_may_split": True}, None),
])
def test_what_the_scan_refuses_to_read_as_the_fit_rule(over, reason):
    """Four exclusions, each of them another rule that already explains the
    seat: no ink, a guard that never runs the fit test, a broken anchor
    offset, and a table Hancom is not permitted to cut."""
    record = scanned(69000, **over)
    assert PFP.scan_evidence_reason(record) == reason
    assert record["evidence"] is (reason is None)


def test_a_cell_line_is_evidence_only_when_its_table_may_be_cut():
    """The one exclusion the page-break pass never needed.  A line inside a
    table that may not split moves with the table or not at all, so however
    far past the body bottom it sits, the table rule put it there."""
    cuttable = scanned(69800, container="cell", table_may_split=True)
    welded = scanned(69800, container="cell", table_may_split=False)
    assert cuttable["overhang"] == welded["overhang"]
    assert cuttable["evidence"] and not welded["evidence"]


def test_the_tail_is_ordered_and_drops_the_seats_that_miss_the_paper():
    """The tail exists to show the deepest lines; one broken anchor offset
    would otherwise fill it and hide every line it was cut for."""
    deep = scanned(69900)
    shallow = scanned(60000)
    wild = scanned(4294967000, on_sheet=False)
    tail = PFP.scan_tail([shallow, wild, deep], floor=-300)
    assert tail == [deep]
    wide = PFP.scan_tail([shallow, wild, deep], floor=-100000)
    assert wide == [deep, shallow]


def test_the_tail_floor_is_a_threshold_on_the_sort_measure():
    """A line enters the tail exactly when its box under the sort measure
    ends within the floor of the body bottom, so moving the floor down by one
    admits the line that ends one HWPUNIT higher and nothing else."""
    usable = 70000
    just_in = scanned(usable - 1000 - 250)   # vertsize box ends at -250
    just_out = scanned(usable - 1000 - 350)  # ... at -350
    assert PFP.scan_tail([just_in, just_out], floor=-300) == [just_in]
    assert PFP.scan_tail([just_in, just_out], floor=-400) == [just_in,
                                                              just_out]


def test_the_union_bound_is_the_larger_of_the_two_kept_readings():
    """The scan and the page-break pass disagree about one line in this
    corpus — #278 rebases the page it sits on — and neither reading owns it,
    so a measure has to clear whichever bound is higher."""
    records = [scanned(60000)]
    events = [{"deepest_overhang": {name: 99 for name in PFP.MEASURE_ORDER}}]
    alone = PFP.scan_bracket(records, [], [])
    both = PFP.scan_bracket(records, [], events)
    for name in PFP.MEASURE_ORDER:
        assert alone[name]["union_max"] == alone[name]["kept_max"]
        assert both[name]["union_max"] == 99
        assert both[name]["event_max"] == 99
        # A kept line the measure would have refused refutes it, and the
        # folded-in reading counts for that exactly as the scan's own does.
        assert alone[name]["kept_violations"] == 0
        assert both[name]["kept_violations"] == 1
        assert not both[name]["consistent"]


def test_a_whole_inline_table_s_box_is_reported_apart_from_a_text_line():
    """A paragraph carrying an inline table has a lineseg whose ``vertsize``
    is the TABLE's height.  #256 left those on the kept side and this keeps
    that parity, but a bracket read off one of them is not a statement about
    a line of text, so the two maxima are separate columns."""
    table_line = scanned(60000, vertsize=9000, inline_table=True)
    text_line = scanned(50000)
    bracket = PFP.scan_bracket([table_line, text_line], [])
    for name in PFP.MEASURE_ORDER:
        assert bracket[name]["kept_max"] >= bracket[name]["text_max"]
        assert bracket[name]["text_n"] == 1
        assert bracket[name]["kept_n"] == 2


def test_a_near_miss_is_a_moved_line_that_almost_stayed():
    """The mirror of the tail.  A moved line bounds the rule from above, and
    one whose would-be overhang is small bounds it hardest; the ceiling is a
    threshold on the same measure the tail is sorted by."""
    close = _event(rejected_overhang={name: 100 for name in PFP.MEASURE_ORDER},
                   next={"vertsize": 1000, "spacing": 600},
                   next_para_order=1, next_lineseg=0, page=0,
                   would_be_top=69000, usable_height=70000)
    far = _event(rejected_overhang={name: 5000 for name in PFP.MEASURE_ORDER},
                 next={"vertsize": 1000, "spacing": 600},
                 next_para_order=2, next_lineseg=0, page=1,
                 would_be_top=60000, usable_height=70000)
    reports = [{"document": "synthetic.hwpx", "events": [far, close]}]
    misses = PFP.near_misses(reports, ceiling=300)
    assert [m["para"] for m in misses] == [1]
    assert misses[0]["evidence"] is True
    both = PFP.near_misses(reports, ceiling=10000)
    assert [m["para"] for m in both] == [1, 2]
