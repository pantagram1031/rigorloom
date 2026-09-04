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
    being an omission, not an empty string.

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
SMALL_FORM = os.path.join(CORPUS, "admrul-gajokdolbom-hyuga-sinchengseo.hwpx")


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
