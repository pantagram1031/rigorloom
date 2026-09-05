# -*- coding: utf-8 -*-
"""lineseg_vs_pdf.py — the rule that lines a paragraph up with a PDF's text.

The measurement this module supports is written up in
``engine/references/own-render-notes.md``.  What is pinned here is the
MECHANISM of the matching rule, on synthetic input, so that a change to the
rule has to move a named term rather than a corpus tally.  Nothing below
counts corpus paragraphs, forms, pages or lines: every fixture is built in
the test.

Five things:

  * the matching key deletes whitespace and soft hyphens and nothing else,
    because whitespace is exactly what a line break is entitled to eat;
  * a paragraph matches a run of WHOLE PDF lines, never a substring that
    begins or ends inside one, and the cursor only moves forward;
  * the hyphenation relaxation is a second attempt, not the first, so a
    document that does not hyphenate is matched by the plain rule;
  * PyMuPDF's line records are regrouped into visual lines inside a matched
    run — a widely tracked line arrives as several records at one height —
    and never across a page or a height;
  * ``hp:lineseg@textpos`` indexes a character stream in which an inline
    control occupies a cell.  ``own_render.Paragraph.chars`` does not carry
    those cells, so this module builds its own, and the difference is one
    whole character per control.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import lineseg_vs_pdf as LVP  # noqa: E402
import own_render  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def paragraph(inner, textpos):
    """A synthetic top-level ``hp:p`` with the given runs and line seats."""
    segs = "".join(
        f'<hp:lineseg textpos="{pos}" vertpos="{1000 + 1500 * i}" '
        f'vertsize="1300" textheight="1300" baseline="1105" spacing="196" '
        f'horzpos="0" horzsize="48000"/>'
        for i, pos in enumerate(textpos))
    xml = (f'<hp:p xmlns:hp="{HP}" paraPrIDRef="0">{inner}'
           f'<hp:linesegarray>{segs}</hp:linesegarray></hp:p>')
    return own_render.Paragraph(ET.fromstring(xml), {})


def pdf_line(text, page=0, top=1000, height=1300, x0=0, width=None):
    """One PyMuPDF-shaped text-line record, in HWPUNIT."""
    key = LVP.normalise(text)
    return {
        "page": page,
        "text": text,
        "key": key,
        "chars": len(key),
        "top_hwp": float(top),
        "bottom_hwp": float(top + height),
        "x0_hwp": float(x0),
        "x1_hwp": float(x0 + (width if width is not None
                              else 1300 * max(1, len(key)))),
    }


# --------------------------------------------------------------------------
# 1 · the key


def test_the_key_deletes_whitespace_and_soft_hyphens_and_nothing_else():
    assert LVP.normalise("a b\tc\nd") == "abcd"
    assert LVP.normalise("가　나 다") == "가나다"
    assert LVP.normalise("re­sume") == "resume"
    # everything that is not whitespace survives, punctuation and case alike
    assert LVP.normalise(" A-b, (C) 가! ") == "A-b,(C)가!"


def test_the_key_is_what_lets_the_two_sides_disagree_about_a_space():
    # The same line with and without the space a break ate.
    assert LVP.normalise("주 소 :") == LVP.normalise("주    소 :")


# --------------------------------------------------------------------------
# 2 · a run of whole lines, found forward


def build(lines):
    return LVP.PdfLines(lines)


def test_a_paragraph_matches_a_run_of_whole_lines():
    pdf = build([pdf_line("가나다"), pdf_line("라마"), pdf_line("바사아")])
    assert pdf.find_run(LVP.normalise("가나다 라마"), 0) == (0, 2, False, False)
    assert pdf.find_run(LVP.normalise("바사아"), 0) == (2, 3, False, False)


def test_a_substring_that_starts_inside_a_line_is_not_a_match():
    pdf = build([pdf_line("가나다"), pdf_line("라마")])
    # "나다라" is present in the concatenation but begins mid-line.
    assert pdf.find_run("나다라", 0) is None


def test_a_substring_that_ends_inside_a_line_is_not_a_match():
    pdf = build([pdf_line("가나다"), pdf_line("라마")])
    assert pdf.find_run("가나다라", 0) is None


def test_the_cursor_only_moves_forward_and_says_so_when_it_cannot():
    pdf = build([pdf_line("같은줄"), pdf_line("다른줄"), pdf_line("같은줄")])
    # The second copy is the one found once the cursor has passed the first.
    assert pdf.find_run("같은줄", 0) == (0, 1, False, False)
    assert pdf.find_run("같은줄", 1) == (2, 3, False, False)
    # Nothing at or after the cursor: found earlier, and flagged.
    _lo, _hi, _relaxed, out_of_order = pdf.find_run("다른줄", 2)
    assert out_of_order is True


def test_the_cursor_never_rewinds_on_an_out_of_order_match():
    assert LVP._cursor_after(7, 3, out_of_order=True) == 7
    assert LVP._cursor_after(7, 9, out_of_order=False) == 9


# --------------------------------------------------------------------------
# 3 · hyphenation is the second attempt, not the first


def test_the_plain_rule_is_tried_before_the_hyphen_relaxation():
    pdf = build([pdf_line("co-"), pdf_line("operate")])
    # The document really does carry the hyphen: plain rule, not relaxed.
    assert pdf.find_run("co-operate", 0) == (0, 2, False, False)


def test_a_hyphen_the_paragraph_does_not_carry_is_dropped():
    pdf = build([pdf_line("coop-"), pdf_line("erate")])
    lo, hi, relaxed, _out = pdf.find_run("cooperate", 0)
    assert (lo, hi) == (0, 2)
    assert relaxed is True


# --------------------------------------------------------------------------
# 4 · a PyMuPDF line is not a laid-out line


def test_pieces_at_one_height_on_one_page_are_one_line():
    pieces = [pdf_line("가", top=1000, x0=0),
              pdf_line("나", top=1005, x0=9000),
              pdf_line("다", top=1000, x0=18000)]
    merged = LVP.merge_visual_lines(pieces)
    assert len(merged) == 1
    assert merged[0]["key"] == "가나다"
    assert merged[0]["pieces"] == len(pieces)
    # the merged extent spans the pieces
    assert merged[0]["x0_hwp"] == 0
    assert merged[0]["x1_hwp"] == pieces[-1]["x1_hwp"]


def test_pieces_at_different_heights_are_different_lines():
    pieces = [pdf_line("가", top=1000), pdf_line("나", top=4000)]
    merged = LVP.merge_visual_lines(pieces)
    assert [group["key"] for group in merged] == ["가", "나"]
    assert [group["pieces"] for group in merged] == [1, 1]


def test_pieces_on_different_pages_are_never_one_line():
    pieces = [pdf_line("가", page=0, top=1000),
              pdf_line("나", page=1, top=1000)]
    assert len(LVP.merge_visual_lines(pieces)) == 2


def test_the_merge_needs_more_than_a_grazing_overlap():
    tall = pdf_line("가", top=1000, height=1300)
    grazing = pdf_line("나", top=2200, height=1300)   # 100 of 1300 overlap
    assert LVP._same_visual_line(tall, grazing) is False
    seated = pdf_line("나", top=1200, height=1300)    # 1100 of 1300
    assert LVP._same_visual_line(tall, seated) is True


# --------------------------------------------------------------------------
# 5 · textpos counts cells, and a control is a cell


def test_an_inline_line_break_occupies_one_textpos_cell():
    inner = ('<hp:run charPrIDRef="0"><hp:t>가나<hp:lineBreak/>다라'
             '</hp:t></hp:run>')
    para = paragraph(inner, [0, 3])
    cells = LVP.character_cells(para)
    assert "".join(cells) == "가나\n다라"
    # own_render's own stream is the one that is short, and by exactly the
    # control: this is why the split has to be read off `character_cells`.
    assert len(cells) - len(para.chars) == 1


def test_a_tab_and_a_full_width_space_each_occupy_one_cell():
    inner = ('<hp:run charPrIDRef="0"><hp:t>가<hp:tab/>나<hp:fwSpace/>다'
             '</hp:t></hp:run>')
    cells = LVP.character_cells(paragraph(inner, [0]))
    assert "".join(cells) == "가\t나　다"


def test_a_formatting_mark_occupies_no_cell():
    inner = ('<hp:run charPrIDRef="0"><hp:t>가<hp:markpenBegin/>나'
             '<hp:markpenEnd/>다</hp:t></hp:run>')
    cells = LVP.character_cells(paragraph(inner, [0]))
    assert "".join(cells) == "가나다"


def test_an_unknown_inline_control_is_counted_as_a_cell_and_reported():
    inner = ('<hp:run charPrIDRef="0"><hp:t>가<hp:somethingNew/>나'
             '</hp:t></hp:run>')
    unknown = {}
    cells = LVP.character_cells(paragraph(inner, [0]), unknown)
    assert len(cells) == 3
    assert unknown == {"somethingNew": 1}


def test_the_split_is_read_at_textpos_over_the_cell_stream():
    inner = ('<hp:run charPrIDRef="0"><hp:t>가나<hp:lineBreak/>다라마'
             '</hp:t></hp:run>')
    para = paragraph(inner, [0, 3])
    cells = LVP.character_cells(para)
    assert LVP.cached_split(para, cells) == [(0, 3), (3, 6)]
    # The break is deleted by the key, so the two lines hold 2 and 3.
    lo, hi = LVP.cached_split(para, cells)[0]
    assert LVP.normalise(LVP.paragraph_text(cells[lo:hi])) == "가나"


def test_the_lineBreak_off_by_one_is_what_the_cell_stream_repairs():
    """The whole point, on the shape the corpus actually carries."""
    inner = ('<hp:run charPrIDRef="0"><hp:t>주소:<hp:lineBreak/>연락처:'
             '</hp:t></hp:run>')
    para = paragraph(inner, [0, 4])
    naive = "".join(ch for ch, _ in para.chars[0:4])
    repaired = LVP.paragraph_text(LVP.character_cells(para)[0:4])
    assert naive == "주소:연"          # one character too many
    assert LVP.normalise(repaired) == "주소:"


# --------------------------------------------------------------------------
# 6 · what is excluded, and why


def test_a_paragraph_with_no_cached_lineseg_cannot_be_compared():
    xml = f'<hp:p xmlns:hp="{HP}" paraPrIDRef="0">' \
          '<hp:run charPrIDRef="0"><hp:t>가나</hp:t></hp:run></hp:p>'
    para = own_render.Paragraph(ET.fromstring(xml), {})
    assert LVP.skip_reason(para, LVP.character_cells(para)) == "no_lineseg"


def test_an_inkless_paragraph_is_excluded():
    inner = '<hp:run charPrIDRef="0"><hp:t>   </hp:t></hp:run>'
    para = paragraph(inner, [0])
    assert LVP.skip_reason(para, LVP.character_cells(para)) == "inkless"


def test_a_paragraph_holding_a_table_is_excluded_before_anything_else():
    inner = ('<hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="1"/>'
             '</hp:run>')
    para = paragraph(inner, [0])
    assert LVP.skip_reason(para, LVP.character_cells(para)) == "table"


def test_a_textpos_the_cell_stream_cannot_reach_is_excluded():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나</hp:t></hp:run>'
    para = paragraph(inner, [0, 99])
    assert (LVP.skip_reason(para, LVP.character_cells(para))
            == "textpos_overruns_stream")


def test_a_comparable_paragraph_has_no_reason_to_be_skipped():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나다라</hp:t></hp:run>'
    para = paragraph(inner, [0, 2])
    assert LVP.skip_reason(para, LVP.character_cells(para)) is None


# --------------------------------------------------------------------------
# 7 · the comparison itself, end to end on synthetic input


def compare(inner, textpos, pdf_lines, body_top=0, cursor=0):
    para = paragraph(inner, textpos)
    cells = LVP.character_cells(para)
    return LVP._compare_paragraph(
        para, cells, order=0, section=0, body_top=body_top,
        page_map={i: 0 for i in range(len(textpos))},
        pdf=build(pdf_lines), cursor=cursor, keep_text=True)


def test_two_passes_that_agree_report_no_divergence():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나다 라마바</hp:t></hp:run>'
    record = compare(inner, [0, 4],
                     [pdf_line("가나다", top=1000),
                      pdf_line("라마바", top=2500)])
    assert record["cached_lines"] == record["pdf_lines"]
    assert record["split_equal"] is True
    assert record["first_divergence"] is None
    assert record["chars_in_agreeing_lines"] == record["chars"]


def test_one_character_across_the_break_is_a_split_divergence():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나다라마바</hp:t></hp:run>'
    record = compare(inner, [0, 4],
                     [pdf_line("가나다", top=1000),
                      pdf_line("라마바", top=2500)])
    assert record["count_equal"] is True
    assert record["split_equal"] is False
    assert record["first_divergence"] == 0
    # only the lines at and after the divergence stop agreeing
    assert record["chars_in_agreeing_lines"] == 0


def test_a_line_count_difference_is_reported_as_such():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나다라</hp:t></hp:run>'
    record = compare(inner, [0],
                     [pdf_line("가나", top=1000),
                      pdf_line("다라", top=2500)])
    assert record["cached_lines"] < record["pdf_lines"]
    assert record["count_equal"] is False
    assert record["first_divergence"] is not None


def test_dy_is_the_cached_seat_less_the_glyph_top_relative_to_the_body():
    inner = '<hp:run charPrIDRef="0"><hp:t>가나</hp:t></hp:run>'
    record = compare(inner, [0], [pdf_line("가나", top=1400)],
                     body_top=500)
    # the fixture seats line 0 at vertpos 1000; the glyph top is 1400 - 500
    assert record["cached"][0]["vertpos"] == 1000
    assert record["pdf"][0]["top"] == 900
    assert record["cached"][0]["dy"] == 100


def test_a_paragraph_that_matches_nowhere_is_a_skip_not_a_guess():
    inner = '<hp:run charPrIDRef="0"><hp:t>없는문장</hp:t></hp:run>'
    record = compare(inner, [0], [pdf_line("다른문장")])
    assert record["reason"] == "no_pdf_match"


# --------------------------------------------------------------------------
# 8 · the summary channels


def synthetic_report(paragraphs):
    return {"document": "x.hwpx", "reference": "x.pdf", "pdf_pages": 1,
            "pdf_text_lines": 0, "unknown_inline_controls": {},
            "sections": [], "paragraphs": paragraphs, "skipped": []}


def test_the_page_channel_separates_a_partition_from_an_index():
    """A constant page offset must not read as a layout difference."""
    def para(pages):
        return {
            "cached_lines": len(pages), "pdf_lines": len(pages),
            "chars": len(pages), "chars_in_agreeing_lines": len(pages),
            "split_equal": True, "count_equal": True,
            "cached": [{"page": c, "pdf_page": p, "dy": 0, "chars": 1}
                       for c, p in pages],
        }
    # every line two pages later in the PDF, but grouped identically
    shifted = summarise_paragraphs([para([(0, 2), (0, 2), (1, 3)])])
    assert shifted["lines_on_a_different_page"] == 3
    assert shifted["page_grouping_breaks"] == 0
    # a line that genuinely changed page splits the partition
    moved = summarise_paragraphs([para([(0, 0), (0, 1), (1, 1)])])
    assert moved["page_grouping_breaks"] > 0


def summarise_paragraphs(paragraphs):
    return LVP.summarise(synthetic_report(paragraphs))


def test_the_character_share_counts_only_lines_that_hold_the_same_text():
    agreeing = {
        "cached_lines": 2, "pdf_lines": 2, "chars": 10,
        "chars_in_agreeing_lines": 10, "split_equal": True,
        "count_equal": True, "cached": [],
    }
    half = dict(agreeing, chars_in_agreeing_lines=5, split_equal=False)
    assert summarise_paragraphs([agreeing])["character_share_agreeing"] == 1.0
    assert summarise_paragraphs([agreeing, half])[
        "character_share_agreeing"] == 0.75


def test_dy_reports_a_residual_around_the_form_s_own_constant():
    """The box top sits above the glyph top by the leading; that is not drift."""
    para = {
        "cached_lines": 3, "pdf_lines": 3, "chars": 3,
        "chars_in_agreeing_lines": 3, "split_equal": True,
        "count_equal": True,
        "cached": [{"page": 0, "pdf_page": 0, "dy": dy, "chars": 1}
                   for dy in (240, 241, 239)],
    }
    summary = summarise_paragraphs([para])
    assert summary["dy"]["median"] == 240
    assert summary["dy_residual_abs_median"] <= 1
    assert summary["dy_spread_within_paragraph_median"] == 2


# --------------------------------------------------------------------------
# 9 · the tool refuses to invent a pairing


def test_an_empty_target_matches_nothing():
    pdf = build([pdf_line("가나다")])
    assert pdf.find_run("", 0) is None


def test_a_cursor_past_the_end_finds_nothing_forward():
    stream = LVP._Stream(["가", "나"])
    assert stream.search("가", from_line=5) is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
