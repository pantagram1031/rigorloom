# -*- coding: utf-8 -*-
"""layout_divergence.py — the A/B/C classification, and the report it writes.

What is pinned here, and why:

  * the classification rule itself, on synthetic boxes.  It is the whole
    product — an ad-hoc pass produced #247's table and was never committed,
    so the rule has to be executable and re-runnable or the next measurement
    is another ad-hoc pass;
  * the precedence between the classes.  A line that both re-broke and
    changed page is ONE class, and which one it is decides whether a page
    difference reads as a break error;
  * the report's shape: the keys a reader (or the next tool) indexes, and the
    fact that every divergent paragraph gets a first-divergence record;
  * ``--no-text`` omits the text field entirely rather than blanking it.  A
    holdout measurement that leaves the operator's machine depends on that
    being an omission, not an empty string;
  * the first-drift predecessor rule: which paragraph on a page is reported,
    that a predecessor drawing NO line box is still reported (it is the
    population the A/B/C classification cannot see at all), and that the
    histogram is keyed on the three fields the report names.

No count of corpus forms or of report rows is pinned as an integer here:
``tests/test_no_inventory_pins.py`` forbids it, and the counts are the
measurement, not the contract.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import layout_divergence as LD  # noqa: E402
import own_render  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")
#: The smallest corpus form that diverges between the two policies at all,
#: so the report has something in every section without costing a big render.
#:
#: This was ``admrul`` until the PERCENT leading was put on its measured 4
#: HWPUNIT grid (``own_render.percent_leading``).  admrul's only disagreement
#: WAS that residual — one class-B line at -0.02 px — so computed layout now
#: reproduces its cache exactly and its report has an empty
#: ``first_divergence_per_paragraph``, which makes every test below vacuous.
#: ``gianmun-byeolji-1ho`` is smaller still (one page) and diverges for a
#: reason this renderer has not closed: one class-A paragraph, three lines,
#: the font-substitution advance gap.
SMALL_FORM = os.path.join(CORPUS, "gianmun-byeolji-1ho.hwpx")


def box(text="hello", page=1, y0=100.0, x0=10.0, address=0):
    return {"address": address, "text": text, "page": page,
            "y0": y0, "y1": y0 + 20.0, "x0": x0, "x1": x0 + 50.0}


# -- the rule ---------------------------------------------------------------

def test_identical_boxes_agree():
    assert LD.classify_line(box(), box()) == "agree"


def test_a_when_the_paragraph_broke_into_a_different_number_of_lines():
    assert LD.classify_line(box(), None) == "A"
    assert LD.classify_line(None, box()) == "A"


def test_a_when_the_same_ordinal_carries_different_text():
    assert LD.classify_line(box(text="one two"), box(text="one")) == "A"


def test_c_when_the_line_changed_page():
    assert LD.classify_line(box(page=1), box(page=2)) == "C"


def test_b_when_only_y_moved():
    assert LD.classify_line(box(y0=100.0), box(y0=80.0)) == "B"


def test_a_beats_c_so_a_rebroken_line_is_not_read_as_a_page_move():
    """Different text on a different page is a break error, not a page move."""
    assert LD.classify_line(box(text="one", page=1),
                            box(text="two", page=2)) == "A"


def test_c_beats_b_so_a_moved_page_is_not_read_as_vertical_drift():
    """``y0`` on another page is measured from another page top: no dy."""
    assert LD.classify_line(box(page=1, y0=100.0),
                            box(page=2, y0=700.0)) == "C"


def test_x_alone_is_not_a_class():
    """#247 has three classes; a horizontal-only difference is none of them."""
    assert LD.classify_line(box(x0=10.0), box(x0=40.0)) == "agree"


def test_the_tolerance_is_what_decides_b():
    small = LD.classify_line(box(y0=100.0), box(y0=100.02), y_tol=0.5)
    assert small == "agree"
    assert LD.classify_line(box(y0=100.0), box(y0=100.02),
                            y_tol=LD.DEFAULT_Y_TOL) == "B"


def test_lines_pair_by_ordinal_within_the_paragraph():
    cache = [box(text="one", y0=100.0), box(text="two", y0=120.0)]
    computed = [box(text="one", y0=100.0), box(text="two", y0=140.0)]
    classes = [row["class"]
               for row in LD.classify_paragraph(cache, computed)]
    assert classes == ["agree", "B"]


def test_an_unpaired_tail_line_is_class_a():
    cache = [box(text="one"), box(text="two")]
    computed = [box(text="one")]
    classes = [row["class"]
               for row in LD.classify_paragraph(cache, computed)]
    assert classes == ["agree", "A"]


def test_untagged_boxes_are_dropped_rather_than_paired():
    """Page furniture draws outside any paragraph and has nothing to pair to."""
    grouped = LD.by_paragraph([box(address=3), dict(box(), address=None)])
    assert set(grouped) == {3}


def test_short_labels_disambiguate_a_shared_leading_token():
    labels = LD.short_labels(["moel-pyojun-2013", "moel-pyojun-2025",
                              "admrul-gajokdolbom"])
    assert labels["admrul-gajokdolbom"] == "admrul"
    assert labels["moel-pyojun-2013"] == "moel-2013"
    assert labels["moel-pyojun-2025"] == "moel-2025"


# -- the report -------------------------------------------------------------

def _need(path):
    if not os.path.isfile(path):
        pytest.skip(f"corpus fixture missing: {path}")
    if not own_render.pillow_available():
        pytest.skip("Pillow is not installed; own_render cannot rasterise")
    return path


@pytest.fixture(scope="module")
def small_report():
    return LD.divergence_report(_need(SMALL_FORM))


def test_report_carries_both_policies_and_the_rule(small_report):
    assert small_report["tool"] == "layout_divergence"
    assert set(small_report["pages"]) == {"cache", "computed"}
    assert set(small_report["lines"]) == set(LD.CLASSES)
    assert set(LD.CLASSES) <= set(small_report["paragraphs"])
    # The rule is IN the artefact: a reader must not have to find the source.
    assert small_report["rule"] == LD.RULE
    assert small_report["y_tolerance_px"] == LD.DEFAULT_Y_TOL


def test_report_counts_are_non_vacuous_and_add_up(small_report):
    lines = small_report["lines"]
    assert sum(lines.values()) > 0
    paragraphs = small_report["paragraphs"]
    assert paragraphs["compared"] > 0
    diverged = sum(paragraphs[name] for name in ("A", "B", "C"))
    # Every paragraph is agree or carries at least one class; the class
    # columns may overlap, so this is a floor, never an equality.
    assert paragraphs["agree"] + diverged >= paragraphs["compared"]
    assert paragraphs["A_and_B"] <= min(paragraphs["A"], paragraphs["B"])


def test_every_divergent_paragraph_has_a_first_divergence(small_report):
    firsts = small_report["first_divergence_per_paragraph"]
    paragraphs = small_report["paragraphs"]
    assert len(firsts) == paragraphs["compared"] - paragraphs["agree"]
    for record in firsts:
        assert record["class"] in ("A", "B", "C")
        assert record["paragraph"] is not None
        assert "cache_y" in record and "computed_y" in record
        assert "dy_px" in record


def test_class_b_histogram_only_holds_class_b_lines(small_report):
    histogram = small_report["class_b_dy_px"]
    assert sum(row["lines"] for row in histogram) == small_report["lines"]["B"]
    counts = [row["lines"] for row in histogram]
    assert counts == sorted(counts, reverse=True)


def test_iou_is_absent_and_says_so_rather_than_being_silently_missing(
        small_report):
    assert small_report["iou"] is None
    assert "reference" in small_report["iou_note"]


def test_text_is_present_by_default_and_truncated(small_report):
    firsts = small_report["first_divergence_per_paragraph"]
    if not firsts:
        pytest.skip("this form does not diverge; nothing to truncate")
    assert small_report["text_included"] is True
    for record in firsts:
        assert len(record["text"]) <= LD.TEXT_CHARS


def test_no_text_omits_the_field_entirely():
    report = LD.divergence_report(_need(SMALL_FORM), include_text=False)
    assert report["text_included"] is False
    firsts = report["first_divergence_per_paragraph"]
    assert firsts, "the fixture must diverge for this to mean anything"
    for record in firsts:
        assert "text" not in record
    # …and no other section smuggled a text FIELD back in.  The word itself
    # is in the rule prose, so the key is what this looks for.
    assert '"text":' not in json.dumps(report, ensure_ascii=False)


def test_write_report_names_the_file_after_the_form(tmp_path, small_report):
    path = LD.write_report(small_report, tmp_path, "somestem")
    assert path.name == "somestem.divergence.json"
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["rule"] == LD.RULE


def test_summary_line_names_every_class(small_report):
    line = LD.summary_line("somestem", small_report)
    assert line.startswith("somestem:")
    for name in LD.CLASSES:
        assert name in line


def test_corpus_table_has_a_row_per_form_and_a_total(small_report):
    rows = [("alpha", small_report), ("beta", small_report)]
    table = LD.corpus_table(rows)
    assert "alpha" in table and "beta" in table
    assert "total" in table
    assert "A&B" in table


# -- the attribution rule ---------------------------------------------------
#
# Synthetic paragraphs throughout: the rule has to be checkable without a
# render, and a rendered form would pin its own inventory into a core test.


def faced(source, characters=5, declared="Batang", **kwargs):
    """A box whose runs all resolved the same way."""
    record = box(**kwargs)
    record["faces"] = [{
        "declared": declared, "slot": "hangul", "bold": False,
        "source": source, "resolved_family": None,
        "resolved_file": "some.ttf", "characters": characters,
    }]
    return record


def test_pitch_is_the_dominant_step_between_consecutive_lines():
    boxes = [box(y0=100.0), box(y0=130.0), box(y0=160.0), box(y0=200.0)]
    assert LD.dominant_pitch(boxes) == 30.0


def test_pitch_ignores_a_step_across_a_page_boundary():
    """The next page's y0 restarts at its own top; that is not an advance."""
    boxes = [box(page=1, y0=100.0), box(page=1, y0=130.0),
             box(page=2, y0=80.0)]
    assert LD.dominant_pitch(boxes) == 30.0


def test_a_single_line_has_no_pitch_of_its_own():
    assert LD.dominant_pitch([box()]) is None
    assert LD.dominant_pitch([]) is None


def test_pitch_prefers_the_paragraphs_own_computed_lines():
    computed = [box(y0=100.0), box(y0=130.0)]
    cache = [box(y0=100.0), box(y0=150.0)]
    assert LD.paragraph_pitch(computed, cache, 99.0) == (30.0, "own_computed")


def test_pitch_falls_back_to_the_paragraphs_own_linesegs():
    """One computed line, two cached: the cache step IS vertsize + spacing."""
    cache = [box(y0=100.0), box(y0=150.0)]
    assert LD.paragraph_pitch([box(y0=100.0)], cache, 99.0) == (
        50.0, "own_lineseg")


def test_pitch_then_falls_back_to_the_nearest_preceding_paragraph():
    assert LD.paragraph_pitch([box()], [box()], 42.0) == (
        42.0, "preceding_computed")


def test_pitch_says_none_rather_than_guessing():
    assert LD.paragraph_pitch([box()], [box()], None) == (None, "none")


def test_a_drift_matching_the_upstream_prediction_is_inherited():
    assert LD.attribute_class_b(30.0, 30.0, 1.0, 1) == "B_inherited"
    assert LD.attribute_class_b(30.4, 30.0, 1.0, 1) == "B_inherited"


def test_a_drift_the_prediction_misses_is_the_paragraphs_own():
    assert LD.attribute_class_b(36.0, 30.0, 1.0, 1) == "B_own"


def test_nothing_rebroken_upstream_means_nothing_was_inherited():
    """Without the guard every sub-pixel drift matches a prediction of zero."""
    assert LD.attribute_class_b(0.02, 0.0, 1.0, 0) == "B_own"
    assert LD.attribute_class_b(0.02, 0.0, 1.0, None) == "B_own"


def test_an_unmeasurable_drift_is_never_called_inherited():
    assert LD.attribute_class_b(None, 30.0, 1.0, 1) == "B_own"
    assert LD.attribute_class_b(30.0, None, 1.0, 1) == "B_own"


# -- the walk ---------------------------------------------------------------

def _walk(cache, computed, **kwargs):
    return LD.walk_paragraphs(cache, computed, **kwargs)["attribution"]


def test_a_paragraph_pushed_down_by_an_upstream_rebreak_is_inherited():
    """0 gains a line; 1 and 2 move by exactly that line's pitch."""
    cache = {0: [box(text="a0", y0=100.0)],
             1: [box(text="b0", y0=130.0)],
             2: [box(text="c0", y0=160.0)]}
    computed = {0: [box(text="a0", y0=100.0), box(text="a1", y0=130.0)],
                1: [box(text="b0", y0=160.0)],
                2: [box(text="c0", y0=190.0)]}
    attribution = _walk(cache, computed)
    split = attribution["class_b_paragraphs"]
    assert split["B_own"] == 0
    assert split["B_inherited"] == len(attribution["class_b"])
    for row in attribution["class_b"]:
        assert row["upstream_line_delta"] == 1
        assert row["residual_px"] == 0.0


def test_the_same_drift_with_nothing_rebroken_above_it_is_its_own():
    cache = {0: [box(text="a0", y0=100.0)], 1: [box(text="b0", y0=130.0)]}
    computed = {0: [box(text="a0", y0=100.0)], 1: [box(text="b0", y0=160.0)]}
    split = _walk(cache, computed)["class_b_paragraphs"]
    assert split["B_inherited"] == 0
    assert split["B_own_no_upstream_rebreak"] == split["B_own"]


def test_a_rebreak_upstream_that_mispredicts_is_booked_with_its_upstream():
    """The cause is upstream even when the predicted magnitude is wrong."""
    cache = {0: [box(text="a0", y0=100.0)], 1: [box(text="b0", y0=130.0)]}
    computed = {0: [box(text="a0", y0=100.0), box(text="a1", y0=130.0)],
                1: [box(text="b0", y0=200.0)]}
    split = _walk(cache, computed)["class_b_paragraphs"]
    assert split["B_inherited"] == 0
    assert split["B_own_with_upstream_rebreak"] == split["B_own"]
    assert split["B_own_no_upstream_rebreak"] == 0


def test_the_accumulators_reset_at_a_page_boundary():
    """A dy is measured from a page top, so a total carried over is nonsense."""
    cache = {0: [box(text="a0", page=1, y0=100.0)],
             1: [box(text="b0", page=2, y0=100.0)]}
    computed = {0: [box(text="a0", page=1, y0=100.0),
                    box(text="a1", page=1, y0=130.0)],
                1: [box(text="b0", page=2, y0=130.0)]}
    attribution = _walk(cache, computed)
    assert attribution["class_b_paragraphs"]["B_inherited"] == 0
    for row in attribution["class_b"]:
        assert row["upstream_line_delta"] == 0


def test_the_residual_histogram_puts_the_tallest_bar_first():
    cache = {index: [box(text=f"p{index}", y0=100.0 + 30.0 * index)]
             for index in range(4)}
    computed = {index: [box(text=f"p{index}", y0=140.0 + 30.0 * index)]
                for index in range(4)}
    histogram = _walk(cache, computed)["class_b_residual_px"]
    counts = [row["paragraphs"] for row in histogram]
    assert counts == sorted(counts, reverse=True)
    assert histogram[0]["residual_px"] == 40.0


# -- the class-A break cause ------------------------------------------------

def test_a_shorter_computed_line_reads_as_a_break_that_moved_earlier():
    cache = {0: [box(text="abcdefgh", x0=10.0)]}
    computed = {0: [box(text="abcde", x0=10.0)]}
    record = _walk(cache, computed)["class_a_lines"][0]
    assert record["break"] == "computed_broke_earlier"
    assert record["cache_chars"] > record["computed_chars"]


def test_a_longer_computed_line_reads_as_a_break_that_moved_later():
    cache = {0: [box(text="abc")]}
    computed = {0: [box(text="abcdefgh")]}
    assert _walk(cache, computed)["class_a_lines"][0]["break"] == \
        "computed_broke_later"


def test_the_class_a_record_carries_both_drawn_widths():
    cache = {0: [box(text="abcdefgh", x0=10.0)]}
    computed = {0: [box(text="abcde", x0=10.0)]}
    record = _walk(cache, computed)["class_a_lines"][0]
    assert record["cache_width_px"] == 50.0
    assert record["computed_width_px"] == 50.0
    assert record["dwidth_px"] == 0.0


def test_an_unpaired_line_names_which_side_has_it():
    cache = {0: [box(text="one"), box(text="two")]}
    computed = {0: [box(text="one")]}
    record = _walk(cache, computed)["class_a_lines"][0]
    assert record["break"] == "cache_only"
    assert record["line_delta"] < 0


def test_a_line_with_one_substituted_run_counts_as_substituted():
    cache = {0: [faced("installed", text="abcdefgh")]}
    computed = {0: [faced("bundled", text="abcde")]}
    share = _walk(cache, computed)["class_a_font_sources"]
    assert share["lines"]["substituted"] == 1
    assert share["lines"]["installed"] == 0
    assert share["substituted_share"] == 1.0


def test_a_line_whose_runs_all_resolved_is_not_counted_as_substituted():
    cache = {0: [faced("installed", text="abcdefgh")]}
    computed = {0: [faced("installed", text="abcde")]}
    share = _walk(cache, computed)["class_a_font_sources"]
    assert share["lines"]["installed"] == 1
    assert share["lines"]["substituted"] == 0
    assert share["substituted_share"] == 0.0


def test_the_font_share_weights_characters_as_well_as_lines():
    cache = {0: [faced("installed", characters=8, text="abcdefgh")]}
    computed = {0: [faced("bundled", characters=5, text="abcde")]}
    characters = _walk(cache, computed)["class_a_font_sources"]["characters"]
    assert characters["installed"] == 8
    assert characters["bundled"] == 5


# -- the attribution in the report ------------------------------------------

def test_the_report_carries_the_attribution_rule_and_its_tolerance(
        small_report):
    attribution = small_report["attribution"]
    assert attribution["rule"] == LD.ATTRIBUTION_RULE
    assert attribution["tolerance_px"] == LD.DEFAULT_ATTRIBUTION_TOL
    split = attribution["class_b_paragraphs"]
    assert set(split) == {"B_inherited", "B_own",
                          "B_own_with_upstream_rebreak",
                          "B_own_no_upstream_rebreak"}


def test_the_b_split_accounts_for_every_class_b_paragraph(small_report):
    split = small_report["attribution"]["class_b_paragraphs"]
    assert (split["B_inherited"] + split["B_own"]
            == small_report["paragraphs"]["B"])
    assert (split["B_own_with_upstream_rebreak"]
            + split["B_own_no_upstream_rebreak"] == split["B_own"])


def test_every_class_a_paragraph_gets_a_break_cause(small_report):
    records = small_report["attribution"]["class_a_lines"]
    assert len(records) == small_report["paragraphs"]["A"]
    for record in records:
        assert record["break"] in ("computed_broke_earlier",
                                   "computed_broke_later",
                                   "same_length_different_text",
                                   "cache_only", "computed_only")


def test_the_corpus_table_shows_the_attribution_columns(small_report):
    table = LD.corpus_table([("alpha", small_report)])
    for column in ("B_inh", "B_own", "A_sub", "A_ins"):
        assert column in table


# -- the first-drift predecessor --------------------------------------------

def metric(vertsize=1600, spacing=960, vertpos=0):
    return {"source": "lineseg", "vertpos_hwp": vertpos,
            "vertsize_hwp": vertsize, "spacing_hwp": spacing,
            "advance_hwp": vertsize + spacing}


def mbox(metrics=None, **kwargs):
    """A ``box`` carrying the advance metrics the predecessor pass reads."""
    out = box(**kwargs)
    out["metrics"] = metrics if metrics is not None else metric()
    return out


def fact(address, **kwargs):
    base = {"address": address, "empty_text": False, "characters": 4,
            "objects": [], "anchor_kind": "none",
            "line_spacing_type": "PERCENT", "line_spacing_value": 160,
            "margin_prev_hwp": 0, "margin_next_hwp": 0, "linesegs": [],
            "cache_advance_hwp": 2560, "cache_extent_hwp": 1600}
    base.update(kwargs)
    return base


#: 144 dpi, the scale every corpus measurement in this repo is made at.
PX_PER_HWP = 144 / 7200


def _predecessors(cache, computed, facts, seats=None, **kwargs):
    return LD.first_drift_predecessors(cache, computed, facts, seats or {},
                                       PX_PER_HWP, **kwargs)


def test_the_paragraph_above_the_first_drift_is_the_one_reported():
    """2 drifts, 3 drifts with it; the report names 1, not 2."""
    cache = {index: [mbox(text=f"p{index}", y0=100.0 + 30.0 * index)]
             for index in range(4)}
    computed = dict(cache)
    computed[2] = [mbox(text="p2", y0=190.0)]
    computed[3] = [mbox(text="p3", y0=220.0)]
    report = _predecessors(cache, computed,
                           {index: fact(index) for index in range(4)})
    assert len(report["pages"]) == 1
    row = report["pages"][0]
    assert row["drift_paragraph"] == 2
    assert row["predecessor"] == 1
    assert row["drift_dy_px"] == 30.0


def test_each_page_gets_its_own_first_drift():
    cache = {0: [mbox(text="a", page=1, y0=100.0)],
             1: [mbox(text="b", page=1, y0=130.0)],
             2: [mbox(text="c", page=2, y0=100.0)],
             3: [mbox(text="d", page=2, y0=130.0)]}
    computed = dict(cache)
    computed[1] = [mbox(text="b", page=1, y0=160.0)]
    computed[3] = [mbox(text="d", page=2, y0=160.0)]
    report = _predecessors(cache, computed,
                           {index: fact(index) for index in range(4)})
    assert [row["page"] for row in report["pages"]] == [1, 2]
    assert [row["predecessor"] for row in report["pages"]] == [0, 2]


def test_a_page_whose_first_paragraph_drifts_has_no_predecessor():
    cache = {0: [mbox(text="a", y0=100.0)]}
    computed = {0: [mbox(text="a", y0=140.0)]}
    row = _predecessors(cache, computed, {0: fact(0)})["pages"][0]
    assert row["predecessor"] is None
    assert "page_top" in row["predecessor_note"]


def test_a_page_with_no_drift_is_not_reported_at_all():
    cache = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=130.0)]}
    report = _predecessors(cache, dict(cache), {0: fact(0), 1: fact(1)})
    assert report["pages"] == []
    assert report["dominant_kind"] is None


def test_the_tolerance_is_what_decides_a_drift():
    cache = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=130.0)]}
    computed = {0: [mbox(text="a", y0=100.0)],
                1: [mbox(text="b", y0=130.4)]}
    facts = {0: fact(0), 1: fact(1)}
    assert _predecessors(cache, computed, facts, y_tol=0.5)["pages"] == []
    assert _predecessors(cache, computed, facts, y_tol=0.1)["pages"]


def test_a_predecessor_that_draws_nothing_is_still_reported():
    """The empty paragraph is the whole reason this pass exists.

    It is in neither policy's boxes, so the A/B/C classification cannot see
    it and its line-count delta is 0 either way — the paragraph below it is
    booked ``B_own_no_upstream_rebreak`` however wrong its height is.
    """
    cache = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=160.0)]}
    computed = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=200.0)]}
    facts = {0: fact(0), 1: fact(1, empty_text=True, characters=0),
             2: fact(2)}
    seats = {(1, 1): {"address": 1, "page": 1, "top_hwp": 2560,
                      "height_hwp": 4560}}
    row = _predecessors(cache, computed, facts, seats)["pages"][0]
    assert row["predecessor"] == 1
    assert row["predecessor_drawn"] is False
    assert row["empty_text"] is True
    # No box either side, so the drift is stated in the units it was made in.
    assert row["gap_px"]["cache_from_ink"] is None
    assert row["height_delta_hwp"] == 4560 - 2560


def test_a_cached_seat_past_the_body_box_is_named_as_such():
    cache = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=160.0)]}
    computed = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=200.0)]}
    facts = {0: fact(0),
             1: fact(1, empty_text=True,
                     linesegs=[{"textpos": 0, "vertpos": 71630,
                                "vertsize": 1600, "spacing": 960}]),
             2: fact(2)}
    row = _predecessors(cache, computed, facts,
                        usable_height_hwp=71436)["pages"][0]
    assert row["cache_seat_vertpos_hwp"] == 71630
    assert row["cache_seat_past_page_bottom"] is True


def test_a_cached_seat_inside_the_body_box_is_not():
    cache = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=160.0)]}
    computed = {0: [mbox(text="a", y0=100.0)], 2: [mbox(text="c", y0=200.0)]}
    facts = {0: fact(0),
             1: fact(1, empty_text=True,
                     linesegs=[{"textpos": 0, "vertpos": 1000,
                                "vertsize": 1600, "spacing": 960}]),
             2: fact(2)}
    row = _predecessors(cache, computed, facts,
                        usable_height_hwp=71436)["pages"][0]
    assert row["cache_seat_past_page_bottom"] is False


def test_the_two_bottoms_differ_by_the_last_lines_trailing_spacing():
    """``ink`` is ``y0 + vertsize``; ``advance`` adds the trailing spacing.

    Which of the two the gap below a paragraph is measured from is the
    question the pass was opened on, so both have to be in the report.
    """
    cache = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=200.0)]}
    computed = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=240.0)]}
    row = _predecessors(cache, computed, {0: fact(0), 1: fact(1)})["pages"][0]
    ink = row["cache"]["bottom_ink_px"]
    advance = row["cache"]["bottom_advance_px"]
    assert advance - ink == pytest.approx(960 * PX_PER_HWP)
    assert (row["gap_px"]["cache_from_ink"]
            - row["gap_px"]["cache_from_advance"]
            == pytest.approx(960 * PX_PER_HWP))


def test_the_gap_is_measured_under_both_policies():
    cache = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=200.0)]}
    computed = {0: [mbox(text="a", y0=100.0)], 1: [mbox(text="b", y0=240.0)]}
    row = _predecessors(cache, computed, {0: fact(0), 1: fact(1)})["pages"][0]
    assert (row["gap_px"]["computed_from_ink"]
            - row["gap_px"]["cache_from_ink"]) == pytest.approx(40.0)


def test_the_histogram_is_keyed_on_the_three_fields_the_report_names():
    cache = {0: [mbox(text="a", page=1, y0=100.0)],
             1: [mbox(text="b", page=1, y0=200.0)],
             2: [mbox(text="c", page=2, y0=100.0)],
             3: [mbox(text="d", page=2, y0=200.0)]}
    computed = dict(cache)
    computed[1] = [mbox(text="b", page=1, y0=240.0)]
    computed[3] = [mbox(text="d", page=2, y0=240.0)]
    facts = {0: fact(0, anchor_kind="anchored:pic"),
             1: fact(1), 2: fact(2, anchor_kind="anchored:pic"), 3: fact(3)}
    report = _predecessors(cache, computed, facts)
    assert report["kinds"] == [{"anchor_kind": "anchored:pic",
                                "empty_text": False,
                                "line_spacing_type": "PERCENT", "pages": 2}]
    assert set(LD.PREDECESSOR_KEY_FIELDS) == set(report["kinds"][0]) - {"pages"}
    assert report["dominant_kind"]["pages"] == 2
    assert report["dominant_kind"]["share"] == 1.0


def test_the_tallest_bar_is_the_dominant_kind():
    cache = {index: [mbox(text=f"p{index}", page=index // 2 + 1,
                          y0=100.0 + 100.0 * (index % 2))]
             for index in range(6)}
    computed = dict(cache)
    facts = {}
    for index in range(6):
        odd = index % 2
        computed[index] = ([mbox(text=f"p{index}", page=index // 2 + 1,
                                 y0=240.0)] if odd else cache[index])
        facts[index] = fact(index, empty_text=bool(index == 0))
    report = _predecessors(cache, computed, facts)
    counts = [row["pages"] for row in report["kinds"]]
    assert counts == sorted(counts, reverse=True)
    assert report["dominant_kind"]["kind"].endswith("/PERCENT")
    assert report["pages_with_a_predecessor"] == sum(counts)


# -- the anchor label -------------------------------------------------------

def test_a_paragraph_with_no_object_has_no_anchor_kind():
    assert LD.anchor_kind([]) == "none"


def test_an_anchored_object_names_the_paragraph_over_an_inline_one():
    objects = [{"kind": "tbl", "treat_as_char": True},
               {"kind": "pic", "treat_as_char": False}]
    assert LD.anchor_kind(objects) == "anchored:pic"


def test_an_inline_object_is_labelled_inline():
    assert LD.anchor_kind([{"kind": "equation", "treat_as_char": True}]) == \
        "inline:equation"


# -- the predecessor section in the report ----------------------------------

def test_the_report_carries_the_predecessor_rule(small_report):
    section = small_report["first_drift_predecessors"]
    assert section["rule"] == LD.PREDECESSOR_RULE
    assert section["key_fields"] == list(LD.PREDECESSOR_KEY_FIELDS)


def test_every_predecessor_row_names_a_page_and_a_drift(small_report):
    for row in small_report["first_drift_predecessors"]["pages"]:
        assert row["drift_paragraph"] is not None
        assert row["drift_dy_px"] is not None


def test_the_histogram_counts_the_rows_that_have_a_predecessor(small_report):
    section = small_report["first_drift_predecessors"]
    with_predecessor = [row for row in section["pages"]
                        if row["predecessor"] is not None]
    assert len(with_predecessor) == section["pages_with_a_predecessor"]
    assert sum(row["pages"] for row in section["kinds"]) \
        == section["pages_with_a_predecessor"]


def test_the_predecessor_section_carries_no_document_text():
    """``--no-text`` has to hold here too: this is a holdout channel."""
    report = LD.divergence_report(SMALL_FORM, include_text=False)
    blob = json.dumps(report["first_drift_predecessors"], ensure_ascii=False)
    assert '"text"' not in blob


def test_the_corpus_table_shows_the_dominant_predecessor(small_report):
    table = LD.corpus_table([("alpha", small_report)])
    assert "dominant first-drift predecessor" in table


# -- the seat pass ----------------------------------------------------------

def seat_fact(address, **kwargs):
    """A ``paragraph_facts`` entry for a top-level paragraph."""
    base = fact(address)
    base.update({"section": 0, "top_level": True, "empty_runs": [],
                 "page_break_before": False, "column_break": False,
                 "keep_with_next": False, "keep_lines": False,
                 "widow_orphan": False,
                 "linesegs": [{"textpos": 0, "vertpos": 0,
                               "vertsize": 1600, "spacing": 960}]})
    base.update(kwargs)
    return base


def cache_seat(page=1, vertpos=0, advance=2560):
    """The pair a cache seat is read from: the drawn page and the linesegs."""
    return ({"page": page, "drawn_pages": 1},
            {"linesegs": [{"textpos": 0, "vertpos": vertpos,
                           "vertsize": 1600, "spacing": advance - 1600}],
             "cache_advance_hwp": advance})


def build_seats(spec):
    """``{address: (cache page, top, advance, computed page, top, advance)}``.

    Returns the three dicts ``seat_rows`` takes, so a test states a document
    as its seats and nothing else.
    """
    facts, cache_seats, flow_seats = {}, {}, {}
    for address, values in spec.items():
        cpage, ctop, cadv, kpage, ktop, kadv = values
        drawn, seg = cache_seat(page=cpage, vertpos=ctop, advance=cadv)
        facts[address] = seat_fact(address, **seg)
        cache_seats[address] = drawn
        flow_seats[(address, kpage)] = {"address": address, "page": kpage,
                                        "top_hwp": ktop, "height_hwp": kadv}
    return facts, cache_seats, flow_seats


def rows_for(spec, **kwargs):
    facts, cache_seats, flow_seats = build_seats(spec)
    return LD.seat_rows(facts, cache_seats, flow_seats, {}, {}, PX_PER_HWP,
                        **kwargs)


def test_a_seat_row_states_both_policies_and_their_delta():
    row = rows_for({0: (1, 0, 2560, 1, 0, 3560)})[0]
    assert row["cache"]["top_hwp"] == 0
    assert row["computed"]["advance_hwp"] == 3560
    assert row["delta"]["advance_hwp"] == 1000
    assert row["delta"]["top_hwp"] == 0


def test_a_seat_delta_is_stated_in_pixels_as_well_as_hwpunit():
    row = rows_for({0: (1, 0, 2560, 1, 7200, 2560)})[0]
    assert row["delta"]["top_hwp"] == 7200
    assert row["delta"]["top_px"] == round(7200 * PX_PER_HWP, 3)


def test_a_paragraph_inside_a_table_cell_is_not_a_seat_row():
    facts, cache_seats, flow_seats = build_seats({0: (1, 0, 2560, 1, 0, 2560)})
    facts[1] = seat_fact(1, top_level=False)
    rows = LD.seat_rows(facts, cache_seats, flow_seats, {}, {}, PX_PER_HWP)
    assert [row["address"] for row in rows] == [0]


def test_a_paragraph_with_no_cached_lineseg_has_no_cache_seat():
    """A package this repo wrote carries no lineseg, so path A does not exist
    for it and the pass says so instead of inventing a zero."""
    facts = {0: seat_fact(0, linesegs=[], cache_advance_hwp=0)}
    rows = LD.seat_rows(facts, {0: {"page": 1, "drawn_pages": 1}},
                        {(0, 1): {"page": 1, "top_hwp": 0,
                                  "height_hwp": 2560}},
                        {}, {}, PX_PER_HWP)
    assert rows[0]["cache"] is None
    assert rows[0]["delta"] is None


def test_a_paragraph_the_flow_pass_split_keeps_its_first_top_and_all_height():
    facts, cache_seats, flow_seats = build_seats({0: (1, 0, 5000, 1, 0, 3000)})
    flow_seats[(0, 2)] = {"address": 0, "page": 2, "top_hwp": 0,
                          "height_hwp": 2000}
    rows = LD.seat_rows(facts, cache_seats, flow_seats, {}, {}, PX_PER_HWP)
    assert rows[0]["computed"]["page"] == 1
    assert rows[0]["computed"]["top_hwp"] == 0
    assert rows[0]["computed"]["advance_hwp"] == 5000
    assert rows[0]["computed"]["records"] == 2


def _seats(spec, **kwargs):
    return LD.first_seat_divergences(rows_for(spec), px_per_hwp=PX_PER_HWP,
                                     **kwargs)


def test_a_document_whose_seats_agree_reports_nothing():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (1, 2560, 2560, 1, 2560, 2560)})
    assert report["pages"] == []
    assert report["dominant_kind"] is None
    assert report["paragraphs_with_a_seat_delta"] == 0


def test_only_the_first_differing_seat_on_a_page_is_reported():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (1, 2560, 2560, 1, 2860, 2560),
                     2: (1, 5120, 2560, 1, 5420, 2560)})
    assert [row["paragraph"] for row in report["pages"]] == [1]
    assert report["paragraphs_with_a_seat_delta"] == 2


def test_each_page_reports_its_own_first_differing_seat():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (1, 2560, 2560, 1, 2860, 2560),
                     2: (2, 0, 2560, 2, 0, 2560),
                     3: (2, 2560, 2560, 2, 2960, 2560)})
    assert [(row["page"], row["paragraph"]) for row in report["pages"]] == \
        [(1, 1), (2, 3)]


def test_a_taller_predecessor_puts_the_delta_on_its_advance():
    """The gap between the two is unchanged; the block above grew."""
    report = _seats({0: (1, 0, 2560, 1, 0, 3560),
                     1: (1, 2560, 2560, 1, 3560, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "d_prev_advance_hwp"
    assert row["single_term"] is True
    assert row["terms_hwp"]["d_prev_advance_hwp"] == 1000
    assert row["terms_hwp"]["d_gap_hwp"] == 0
    assert row["identity_ok"] is True


def test_a_wider_space_between_two_paragraphs_puts_the_delta_on_the_gap():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (1, 2560, 2560, 1, 3560, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "d_gap_hwp"
    assert row["single_term"] is True
    assert row["terms_hwp"]["d_gap_hwp"] == 1000
    assert row["terms_hwp"]["gap_cache_hwp"] == 0
    assert row["terms_hwp"]["gap_computed_hwp"] == 1000


def test_two_terms_over_the_tolerance_are_not_called_a_single_term():
    """nrf's shape: the block above grew and the gap below it shrank."""
    report = _seats({0: (1, 0, 2560, 1, 0, 63674),
                     1: (1, 63950, 2560, 1, 63674, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "d_gap_hwp"
    assert row["single_term"] is False
    assert row["terms_hwp"]["d_prev_advance_hwp"] == 61114
    assert row["terms_hwp"]["d_gap_hwp"] == -61390
    assert row["delta_top_hwp"] == -276
    assert row["identity_ok"] is True


def test_the_three_terms_always_add_up_to_the_seat_delta():
    report = _seats({0: (1, 0, 2560, 1, 0, 3000),
                     1: (1, 2560, 2560, 1, 4200, 2560)})
    row = report["pages"][0]
    terms = row["terms_hwp"]
    assert (terms["d_prev_top_hwp"] + terms["d_prev_advance_hwp"]
            + terms["d_gap_hwp"]) == row["delta_top_hwp"] == 1640
    assert row["identity_ok"] is True


def test_a_predecessor_that_itself_moved_carries_the_delta_it_inherited():
    """The only way to see ``d_prev_top`` non-zero: the pair is decomposed
    directly, because on a real page the predecessor would have been the
    first differing seat and reported instead of this one."""
    rows = rows_for({0: (1, 100, 2560, 1, 400, 3000),
                     1: (1, 3000, 2560, 1, 4200, 2560)})
    split = LD.decompose_seat_delta(rows[0], rows[1])
    terms = split["terms"]
    assert terms["d_prev_top_hwp"] == 300
    assert terms["d_prev_advance_hwp"] == 440
    assert terms["d_gap_hwp"] == 460
    assert split["carrier"] == "d_gap_hwp"
    assert split["single_term"] is False
    assert split["identity_sum_hwp"] == rows[1]["delta"]["top_hwp"] == 1200


def test_the_first_seated_paragraph_on_a_page_has_no_terms():
    report = _seats({0: (1, 0, 2560, 1, 300, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "page_top"
    assert row["terms_hwp"] is None
    assert "page" in row["note"]


def test_a_paragraph_the_two_policies_put_on_different_pages_is_named():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (1, 2560, 2560, 2, 0, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "page_move"
    assert row["delta_page"] == 1
    assert row["terms_hwp"] is None


def test_a_predecessor_on_another_page_leaves_no_gap_to_measure():
    report = _seats({0: (1, 0, 2560, 1, 0, 2560),
                     1: (2, 0, 2560, 2, 300, 2560)})
    row = report["pages"][0]
    assert row["carrier"] == "page_top"
    assert row["terms_hwp"] is None


def test_a_predecessor_with_no_seat_is_named_rather_than_guessed():
    facts, cache_seats, flow_seats = build_seats(
        {0: (1, 0, 2560, 1, 0, 2560), 1: (1, 2560, 2560, 1, 2860, 2560)})
    facts[0]["linesegs"] = []
    rows = LD.seat_rows(facts, cache_seats, flow_seats, {}, {}, PX_PER_HWP)
    report = LD.first_seat_divergences(rows, px_per_hwp=PX_PER_HWP)
    assert report["pages"][0]["carrier"] == "page_top"


def test_the_tolerance_is_what_decides_a_seat_difference():
    spec = {0: (1, 0, 2560, 1, 0, 2560), 1: (1, 2560, 2560, 1, 2562, 2560)}
    assert _seats(spec, tol=0.5)["pages"]
    assert _seats(spec, tol=2.5)["pages"] == []


def test_a_delta_spread_under_the_tolerance_has_no_carrier():
    report = _seats({0: (1, 0, 2560, 1, 0, 2562),
                     1: (1, 2560, 2560, 1, 2564, 2560)}, tol=2.5)
    row = report["pages"][0]
    assert row["carrier"] == "none"
    assert row["single_term"] is None


def test_the_histogram_is_keyed_on_both_kinds_and_the_carrier():
    report = _seats({0: (1, 0, 2560, 1, 0, 3560),
                     1: (1, 2560, 2560, 1, 3560, 2560)})
    assert set(LD.SEAT_KEY_FIELDS) == set(report["kinds"][0]) - {"pages"}
    assert report["kinds"][0]["carrier"] == "d_prev_advance_hwp"
    assert report["dominant_kind"]["carrier"] == "d_prev_advance_hwp"
    assert report["dominant_kind"]["share"] == 1.0


def test_the_tallest_carrier_bar_is_the_dominant_kind():
    spec = {}
    for page in range(1, 4):
        base = (page - 1) * 4
        grew = page < 3
        spec[base] = (page, 0, 2560, page, 0, 3560 if grew else 2560)
        spec[base + 1] = (page, 2560, 2560, page, 3560, 2560)
    report = _seats(spec)
    counts = [row["pages"] for row in report["kinds"]]
    assert counts == sorted(counts, reverse=True)
    assert report["dominant_kind"]["carrier"] == "d_prev_advance_hwp"
    assert report["carriers"]["d_prev_advance_hwp"] == 2
    assert report["carriers"]["d_gap_hwp"] == 1


# -- the seat section in the report -----------------------------------------

def test_the_report_carries_the_seat_rule(small_report):
    section = small_report["first_seat_divergences"]
    assert section["rule"] == LD.SEAT_RULE
    assert section["key_fields"] == list(LD.SEAT_KEY_FIELDS)
    assert section["seat_tolerance_hwp"] == LD.DEFAULT_SEAT_TOL_HWP


def test_every_seat_row_of_the_report_is_seated_under_both_policies(
        small_report):
    section = small_report["first_seat_divergences"]
    assert section["paragraphs_seated_both"] > 0
    for row in section["pages"]:
        assert row["this"]["cache"] is not None
        assert row["this"]["computed"] is not None


def test_the_seat_rows_are_off_by_default_and_optional(small_report):
    assert "seat_rows" not in small_report["first_seat_divergences"]
    with_rows = LD.divergence_report(_need(SMALL_FORM), include_seat_rows=True)
    rows = with_rows["first_seat_divergences"]["seat_rows"]
    assert [row["address"] for row in rows] == sorted(
        row["address"] for row in rows)


def test_the_seat_section_carries_no_document_text():
    report = LD.divergence_report(_need(SMALL_FORM), include_text=False,
                                  include_seat_rows=True)
    blob = json.dumps(report["first_seat_divergences"], ensure_ascii=False)
    assert '"text"' not in blob


def test_the_seat_table_has_a_row_per_form(small_report):
    table = LD.seat_table([("alpha", small_report), ("beta", small_report)])
    assert "carrier" in table
    assert "alpha" in table and "beta" in table
