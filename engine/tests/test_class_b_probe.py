# -*- coding: utf-8 -*-
"""class_b_probe.py — the four-term split and the mechanism it is charged to.

What is pinned here, and why:

  * the identity.  ``d_top = d_container_y + d_block_offset + d_seat +
    d_first_offset`` is the whole product: it is what lets a paragraph inside
    a table cell — which is most of class B on the corpus, and which the seat
    pass cannot see at all — be attributed instead of counted.  It is checked
    against the drawn ``dy``, in pixels, not asserted;
  * the telescoping.  A step in ``d_seat`` is charged to the paragraph that
    paid for it, and a paragraph that draws nothing is stepped OVER rather
    than breaking the chain — an empty paragraph moves no cursor, and if it
    broke the chain the run of them above a class-B paragraph would hide its
    cause;
  * the ORDER ``mechanism`` decides in.  A forced break beats every height
    because it decides the page before a height is asked for; an anchored
    object beats an inline one because only one of them is placed outside the
    line; a re-break beats a height difference because a different line COUNT
    is a different question from a different line height.  Changing that
    order re-labels the histogram, so it has to be executable;
  * that a re-break is split by whether the paragraph carries ``hp:tab``.
    This renderer declares it does not place that control, so a re-break in a
    tabbed paragraph is a named gap and one without a tab is a glyph-advance
    difference, and reading them as one number hides which;
  * that a container term is followed UP to the paragraph that holds the
    table, because "the table moved" names nothing on its own.

No count of corpus paragraphs, class-B rows or mechanisms is pinned as an
integer here: ``tests/test_no_inventory_pins.py`` forbids it, and those
counts are the measurement, not the contract.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import class_b_probe as CB  # noqa: E402
import own_render  # noqa: E402

PX_PER_HWP = 144.0 / own_render.HWPUNIT_PER_INCH


def fact(address, **over):
    base = {
        "address": address,
        "top_level": True,
        "empty_text": False,
        "characters": 20,
        "objects": [],
        "anchor_kind": "none",
        "empty_runs": [],
        "line_spacing_type": "PERCENT",
        "line_spacing_value": 160,
        "margin_prev_hwp": 0,
        "margin_next_hwp": 0,
        "page_break_before": False,
        "column_break": False,
        "keep_with_next": False,
        "keep_lines": False,
        "widow_orphan": False,
        "linesegs": [],
        "tabs": 0,
    }
    base.update(over)
    return base


def origin(address, seat, page=1, container_y=0, block_offset=0,
           first_offset=0, lines=1, advance=2560, mode="lineseg"):
    return {
        "address": address,
        "page": page,
        "container_y_hwp": container_y,
        "block_offset_hwp": block_offset,
        "seat_hwp": seat,
        "first_offset_hwp": first_offset,
        "abs_top_hwp": container_y + block_offset + seat + first_offset,
        "line_count": lines,
        "advance_hwp": advance,
        "mode": mode,
    }


def box(address, y0, text="hello", page=1):
    return {"address": address, "text": text, "page": page,
            "y0": y0, "y1": y0 + 20.0, "x0": 10.0, "x1": 60.0}


def trace(origins, facts, boxes, cells=None, cell_boxes=None,
          containers=None, flow_seats=None, cache_seats=None):
    return {
        "origins": {o["address"]: o for o in origins},
        "cell_boxes": cell_boxes or {},
        "line_boxes": boxes,
        "facts": {f["address"]: f for f in facts},
        "containers": containers or {f["address"]: "body" for f in facts},
        "cell_of": cells or {},
        "flow_seats": flow_seats or {},
        "cache_seats": cache_seats or {},
        "px_per_hwp": PX_PER_HWP,
    }


# -- mechanism: the order the labels are decided in ----------------------

def test_forced_break_beats_every_height():
    """A page break decides the page before a height is asked for."""
    name, _detail = CB.mechanism(
        fact(0, page_break_before=True, anchor_kind="inline:tbl",
             objects=[{"kind": "tbl", "treat_as_char": True}]),
        {"line_count": 1, "advance_hwp": 100},
        {"line_count": 3, "advance_hwp": 900})
    assert name == "forced_break"


def test_anchored_object_beats_inline():
    anchored = fact(0, anchor_kind="anchored:tbl",
                    objects=[{"kind": "tbl", "treat_as_char": False}])
    inline = fact(0, anchor_kind="inline:pic",
                  objects=[{"kind": "pic", "treat_as_char": True}])
    assert CB.mechanism(anchored, None, None)[0] == "anchored_object:tbl"
    assert CB.mechanism(inline, None, None)[0] == "inline_object:pic"


def test_empty_paragraph_is_its_own_case():
    name, detail = CB.mechanism(
        fact(0, empty_text=True, characters=0,
             empty_runs=[{"char_index": 0, "charpr": "8",
                          "height_hwp": 1600, "height_pt": 16.0}]),
        {"line_count": 1, "advance_hwp": 2560},
        {"line_count": 1, "advance_hwp": 2560})
    assert name == "empty_paragraph"
    assert detail["empty_runs"], "the declared height is the whole mechanism"


def test_a_rebreak_is_split_by_whether_the_paragraph_carries_a_tab():
    """``hp:tab`` is a declared gap; a re-break without one is not."""
    plain = CB.mechanism(fact(0),
                         {"line_count": 1, "advance_hwp": 1496},
                         {"line_count": 2, "advance_hwp": 2992})
    tabbed = CB.mechanism(fact(0, tabs=2),
                          {"line_count": 1, "advance_hwp": 1496},
                          {"line_count": 2, "advance_hwp": 2992})
    assert plain[0] == "text_rebreak:width"
    assert tabbed[0] == "text_rebreak:tab"
    assert tabbed[1]["tabs"] == 2


def test_same_line_count_different_advance_is_a_height_not_a_break():
    name, detail = CB.mechanism(fact(0),
                                {"line_count": 2, "advance_hwp": 2992},
                                {"line_count": 2, "advance_hwp": 3000})
    assert name == "text_line_height"
    assert detail["advance_delta_hwp"] == 8


def test_same_height_predecessor_is_charged_to_the_gap_not_to_itself():
    """If the paragraph came out the same, the step is the space after it."""
    name, _detail = CB.mechanism(fact(0),
                                 {"line_count": 2, "advance_hwp": 2992},
                                 {"line_count": 2, "advance_hwp": 2992})
    assert name == "interparagraph_gap"


# -- decompose: the identity, and who the step is charged to -------------

def two_paragraph_case(second_seat_computed):
    """¶0 comes out taller under computed; ¶1 is the class-B paragraph."""
    facts = [fact(0), fact(1)]
    cache = trace(
        [origin(0, 0, advance=1496, lines=1),
         origin(1, 1496, advance=1496, lines=1)],
        facts, [box(0, 10.0), box(1, 39.92)])
    computed = trace(
        [origin(0, 0, advance=2992, lines=2, mode="computed"),
         origin(1, second_seat_computed, advance=1496, lines=1,
                mode="computed")],
        facts, [box(0, 10.0), box(1, 39.92 + 29.92)])
    return cache, computed


def test_the_identity_is_checked_against_the_drawn_dy():
    cache, computed = two_paragraph_case(1496 + 1496)
    records = CB.decompose(cache, computed, y_tol=0.01)
    assert [r["paragraph"] for r in records] == [1]
    row = records[0]
    assert row["identity_ok"] is True
    assert sum(row["terms_hwp"].values()) == row["d_top_hwp"]


def test_the_step_is_charged_to_the_predecessor_that_paid_for_it():
    cache, computed = two_paragraph_case(1496 + 1496)
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["split"] == "inherited"
    assert row["carrier_term"] == "d_seat_hwp"
    assert [c["paragraph"] for c in row["carriers"]] == [0]
    assert row["carriers"][0]["mechanism"] == "text_rebreak:width"
    assert row["root_mechanism"] == "text_rebreak:width"


def test_an_inkless_paragraph_is_stepped_over_not_a_wall():
    """A paragraph that draws nothing moved no cursor; it must not hide the
    paragraph above it that did."""
    facts = [fact(0), fact(1, empty_text=True, characters=0), fact(2)]
    cache = trace([origin(0, 0, advance=1496),
                   origin(2, 4056, advance=1496)],
                  facts, [box(0, 10.0), box(2, 91.12)])
    computed = trace([origin(0, 0, advance=2992, lines=2, mode="computed"),
                      origin(2, 4056 + 1496, advance=1496, mode="computed")],
                     facts, [box(0, 10.0), box(2, 91.12 + 29.92)])
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["paragraph"] == 2
    assert [c["paragraph"] for c in row["carriers"]] == [0]


def test_own_first_offset_is_the_paragraphs_own_and_is_named_as_such():
    facts = [fact(0)]
    cache = trace([origin(0, 0, first_offset=0)], facts, [box(0, 10.0)])
    computed = trace([origin(0, 0, first_offset=200, mode="computed")],
                     facts, [box(0, 14.0)])
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["split"] == "own"
    assert row["carrier_term"] == "d_first_offset_hwp"
    assert row["root_mechanism"].startswith("own:")


def test_a_moved_cell_is_followed_up_to_the_paragraph_holding_the_table():
    """"The table moved" names nothing; the holder's own step does.

    ¶0 re-breaks and comes out one line taller, ¶1 holds the table and is
    seated 1496 lower for it, and ¶9 sits in one of the table's cells.  The
    cell has no predecessor of its own, so the only way to say why it moved
    is to follow the table up to ¶1 and then the step up to ¶0.
    """
    facts = [fact(0), fact(1, anchor_kind="inline:tbl",
                           objects=[{"kind": "tbl", "treat_as_char": True}]),
             fact(9, top_level=False)]
    cells = {9: "tc-1"}

    def side(seat_one, table_y, mode):
        return trace(
            [origin(0, 0, advance=(1496 if mode == "lineseg" else 2992),
                    lines=(1 if mode == "lineseg" else 2), mode=mode),
             origin(1, seat_one, advance=20000, mode=mode),
             origin(9, 0, container_y=table_y + 200, mode=mode)],
            facts, [box(0, 10.0), box(1, 39.92), box(9, 60.0)], cells=cells,
            cell_boxes={"tc-1": {"row": 0, "col": 0,
                                 "y0_hwp": table_y + 200,
                                 "margin_top_hwp": 0, "table": "t",
                                 "table_y_hwp": table_y, "holder": 1,
                                 "page": 1}},
            containers={0: "body", 1: "body", 9: "cell-1"})

    cache = side(1496, 4000, "lineseg")
    computed = side(1496 + 1496, 4000 + 1496, "computed")
    computed["line_boxes"] = [box(0, 10.0), box(1, 39.92 + 29.92),
                              box(9, 60.0 + 29.92)]
    row = next(r for r in CB.decompose(cache, computed, y_tol=0.01)
               if r["paragraph"] == 9)
    assert row["container"] == "in_cell"
    assert row["carrier_term"] == "d_container_y_hwp"
    assert row["cell"]["carrier"] == "table_origin"
    assert row["holder"]["paragraph"] == 1
    assert row["root_mechanism"] == "text_rebreak:width"
    assert any(name.startswith("via_holder:") for name in row["mechanisms"])


def test_a_row_that_grew_is_not_confused_with_a_table_that_moved():
    facts = [fact(9, top_level=False)]
    cells = {9: "tc-1"}
    cache = trace([origin(9, 0, container_y=5000)], facts, [box(9, 110.0)],
                  cells=cells,
                  cell_boxes={"tc-1": {"row": 1, "col": 0, "y0_hwp": 5000,
                                       "margin_top_hwp": 0, "table": "t",
                                       "table_y_hwp": 4000, "holder": None,
                                       "page": 1}},
                  containers={9: "cell-1"})
    computed = trace([origin(9, 0, container_y=5300, mode="computed")], facts,
                     [box(9, 116.0)], cells=cells,
                     cell_boxes={"tc-1": {"row": 1, "col": 0, "y0_hwp": 5300,
                                          "margin_top_hwp": 0, "table": "t",
                                          "table_y_hwp": 4000,
                                          "holder": None, "page": 1}},
                     containers={9: "cell-1"})
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["cell"]["carrier"] == "table_row_heights"
    assert row["root_mechanism"] == "table_row_heights"


def test_a_table_nested_in_a_cell_is_followed_up_to_the_outer_holder():
    """One level up is not enough when a table sits in another table's cell.

    ¶1 holds the outer table and is seated 1000 lower under the cache — its
    space-before at a page top.  ¶5 lives in one of that table's cells and
    holds the INNER table; ¶9 lives in a cell of the inner one.  ¶5 has no
    predecessor and no step of its own: the whole of its displacement came
    from the cell it sits in, so the only way to name ¶9 is to ask ¶5 the
    same question again and land on ¶1.
    """
    facts = [fact(1, anchor_kind="inline:tbl", empty_text=True, characters=1,
                  margin_prev_hwp=1000,
                  objects=[{"kind": "tbl", "treat_as_char": True}]),
             fact(5, top_level=False, anchor_kind="inline:tbl",
                  empty_text=True, characters=1,
                  objects=[{"kind": "tbl", "treat_as_char": True}]),
             fact(9, top_level=False)]

    def side(seat_one, mode):
        outer_cell = 4000 + seat_one
        inner_cell = outer_cell + 600
        return trace(
            [origin(1, seat_one, page=2, advance=20000, mode=mode),
             origin(5, 0, page=2, container_y=outer_cell, mode=mode),
             origin(9, 0, page=2, container_y=inner_cell, mode=mode)],
            facts,
            [box(1, 10.0, page=2), box(5, 40.0 + seat_one * PX_PER_HWP,
                                       page=2),
             box(9, 60.0 + seat_one * PX_PER_HWP, page=2)],
            cells={5: "tc-outer", 9: "tc-inner"},
            cell_boxes={
                "tc-outer": {"row": 0, "col": 0, "y0_hwp": outer_cell,
                             "margin_top_hwp": 0, "table": "outer",
                             "table_y_hwp": outer_cell, "holder": 1,
                             "page": 2},
                "tc-inner": {"row": 0, "col": 0, "y0_hwp": inner_cell,
                             "margin_top_hwp": 0, "table": "inner",
                             "table_y_hwp": inner_cell, "holder": 5,
                             "page": 2}},
            containers={1: "body", 5: "cell-outer", 9: "cell-inner"})

    cache = side(1000, "lineseg")
    computed = side(0, "computed")
    rows = {r["paragraph"]: r for r in CB.decompose(cache, computed,
                                                    y_tol=0.01)}
    inner = rows[9]
    assert inner["carrier_term"] == "d_container_y_hwp"
    assert inner["cell"]["carrier"] == "table_origin"
    assert inner["cell"]["holder"] == 5
    # ¶5 has no carriers of its own — the old walk stopped here.
    assert inner["holder"]["carriers"] == []
    assert inner["root_mechanism"] == "page_top:margin_prev"
    assert "via_holder:page_top:margin_prev" in inner["mechanisms"]


def test_a_step_is_not_charged_across_a_page_boundary():
    """Seats are page-relative, so their difference across a break is not a
    step anybody paid for.  ¶0 must not be charged for ¶1."""
    facts = [fact(0), fact(1, margin_prev_hwp=1000)]
    cache = trace([origin(0, 0, page=1, advance=1496),
                   origin(1, 1000, page=2, advance=1496)],
                  facts, [box(0, 10.0, page=1), box(1, 30.0, page=2)])
    computed = trace([origin(0, 0, page=1, advance=2992, lines=2,
                             mode="computed"),
                      origin(1, 0, page=2, advance=1496, mode="computed")],
                     facts, [box(0, 10.0, page=1), box(1, 10.0, page=2)])
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["paragraph"] == 1
    assert row["carrier_term"] == "d_seat_hwp"
    assert row["carriers"] == []
    assert row["root_mechanism"] == "page_top:margin_prev"


def test_the_space_before_at_a_page_top_is_checked_not_assumed():
    """The margin has to ACCOUNT for the seat, or the band stays visible."""
    facts = [fact(0), fact(1, margin_prev_hwp=40)]
    cache = trace([origin(0, 0, page=1, advance=1496),
                   origin(1, 1000, page=2, advance=1496)],
                  facts, [box(0, 10.0, page=1), box(1, 30.0, page=2)])
    computed = trace([origin(0, 0, page=1, advance=1496),
                      origin(1, 0, page=2, advance=1496, mode="computed")],
                     facts, [box(0, 10.0, page=1), box(1, 10.0, page=2)])
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["root_mechanism"] == "page_top_unattributed"


def test_a_paragraph_carried_across_the_break_pays_for_the_page_head():
    """The flow pass put ¶1 on page 2; the cache left it on page 1.  Its
    computed height is exactly the room ¶2 lost, so ¶1 is the root."""
    facts = [fact(0), fact(1, empty_text=True, characters=0), fact(2)]
    cache = trace(
        [origin(0, 0, page=1, advance=1496),
         origin(2, 0, page=2, advance=1496)],
        facts, [box(0, 10.0, page=1), box(2, 10.0, page=2)],
        cache_seats={0: {"address": 0, "page": 1, "drawn_pages": 1},
                     1: {"address": 1, "page": 1, "drawn_pages": 1},
                     2: {"address": 2, "page": 2, "drawn_pages": 1}})
    computed = trace(
        [origin(0, 0, page=1, advance=1496, mode="computed"),
         origin(2, 2560, page=2, advance=1496, mode="computed")],
        facts, [box(0, 10.0, page=1), box(2, 61.2, page=2)],
        cache_seats={0: {"address": 0, "page": 1, "drawn_pages": 1},
                     1: {"address": 1, "page": 1, "drawn_pages": 1},
                     2: {"address": 2, "page": 2, "drawn_pages": 1}},
        flow_seats={(1, 2): {"address": 1, "page": 2, "top_hwp": 0,
                             "height_hwp": 2560}})
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["paragraph"] == 2
    assert row["carriers"] == []
    assert row["root_mechanism"] == "empty_paragraph"


def test_a_paragraph_the_policies_put_on_different_pages_is_named_not_guessed():
    facts = [fact(0)]
    cache = trace([origin(0, 100, page=1)], facts, [box(0, 10.0, page=1)])
    computed = trace([origin(0, 100, page=2, mode="computed")], facts,
                     [box(0, 40.0, page=1)])
    row = CB.decompose(cache, computed, y_tol=0.01)[0]
    assert row["split"] == "unmeasurable"
    assert "terms_hwp" not in row


# -- the histograms ------------------------------------------------------

def test_the_root_histogram_partitions_the_population():
    cache, computed = two_paragraph_case(1496 + 1496)
    records = CB.decompose(cache, computed, y_tol=0.01)
    roots = CB.root_histogram(records)
    assert sum(row["paragraphs"] for row in roots) == len(records)
    assert roots[0]["dy_px_carried"] >= 0


def test_every_mechanism_histogram_books_each_label_once_per_paragraph():
    cache, computed = two_paragraph_case(1496 + 1496)
    records = CB.decompose(cache, computed, y_tol=0.01)
    rows, breadth = CB.histogram(records)
    assert {row["mechanism"] for row in rows} == {"text_rebreak:width"}
    assert sum(breadth.values()) == len(records)


def test_the_report_shape_a_reader_indexes():
    cache, computed = two_paragraph_case(1496 + 1496)
    records = CB.decompose(cache, computed, y_tol=0.01)
    rows, breadth = CB.histogram(records)
    report = {
        "class_b_paragraphs": len(records),
        "mechanisms": rows,
        "root_mechanisms": CB.root_histogram(records),
        "mechanism_breadth": breadth,
        "paragraphs": records,
    }
    for key in ("class_b_paragraphs", "mechanisms", "root_mechanisms",
                "paragraphs"):
        assert key in report
    for record in report["paragraphs"]:
        assert "root_mechanism" in record
        assert "carriers" in record


# -- the CLI still parses ------------------------------------------------

def test_the_parser_offers_corpus_and_a_tolerance_in_hwpunit():
    args = CB.build_parser().parse_args(["--corpus", "--dpi", "144"])
    assert args.corpus and args.dpi == 144
    assert args.tol == CB.DEFAULT_TOL_HWP


def test_an_input_is_required_without_corpus():
    with pytest.raises(SystemExit):
        CB.main([])
