# -*- coding: utf-8 -*-
"""The HFT rows that live inside tables, and the cell they close.

#313 left ``saeopja`` ¶393 -- a six-character line in table 4 row 0 cell 8 --
+238.0 HWPUNIT over its 2894 HWPUNIT column, with +142 of the excess
unexplained.  All six advances came from the installed ``H2MJSM.TTF``
outlines, because ``hft-widths.measured.json`` carried no 한양신명조 advance
for a digit.

The reason it carried none is the walk, not the evidence.  The builder
attributed Type 3 glyphs to declared faces over ``_kids(section, "p")`` -- the
TOP-LEVEL paragraphs -- and ``saeopja`` has six of those, every one of them
``skip_reason == "table"``.  Its 757 in-cell paragraphs were never read, so
the export's own Type 3 objects for 한양견고딕 and the 8 pt 한양신명조 were
read out of the PDF, found unclaimed, and counted as
``type3_code_points_no_paired_run_used`` (494 of them corpus-wide).

``hft_width_table.text_paragraphs`` walks every ``hp:p`` instead.  Nothing
else changed: the WIDTH still comes from ``/Widths``, the pairing still only
picks which face a font object belongs to, and every one of the 226 rows the
table already had is byte-identical afterwards.

What is pinned here:

* the walk actually reaches what the top-level one cannot, on the form that
  proves it;
* the table carries the 한양신명조 digits, declared MEASURED and widths only,
  with ``saeopja`` named as the form they were read from;
* the renderer's own gate finds them -- ``_declared_hft_face`` plus the loaded
  table, not the emitted JSON;
* every hangul row the extension adds is exactly 1.0000 em, which is the cell
  an uncovered syllable already fell back to.  This is what makes the in-table
  anchor residual (0.0435 em on hangul, where the top-level check reads
  0.0003) cost the renderer nothing: a cell line's pen distances are opened by
  the cell's own justification, and no hangul row moves an advance anyway;
* the falsifiable claim: ¶393's computed breaks equal its cached breaks WITH
  the table and do not without it.

The last one is a path-B measurement -- our own breaker against the cached
break positions -- run under the shipped renderer and its no-table control,
which is ``hft_width_table``'s own ``current`` variant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import advance_probe  # noqa: E402
import hft_width_table as HWT  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402

TABLE = ROOT / "engine" / "references" / "fonts" / "hft-widths.measured.json"
FORM = (ROOT / "tests" / "corpus" / "forms" / "converted"
        / "saeopja-deungnok-sinchengseo.hwpx")

#: The paragraph #313 named, and the cell it sits in.
PINNED = 393

#: The face the whole of ``saeopja``'s 8 pt small print is metered off, and
#: the advance its digits are DRAWN at.  The installed ``H2MJSM.TTF`` answers
#: 0.625 em for the same code points, which is the error this closes.
FACE = "한양신명조"
DIGIT_EM = 0.5


@pytest.fixture(scope="module")
def payload():
    if not TABLE.is_file():
        pytest.skip("the measured table is not in this checkout")
    return json.loads(TABLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def renderer():
    if not FORM.is_file():
        pytest.skip("the corpus form is not in this checkout")
    return own_render.OwnRenderer(FORM, repo_root=ROOT)


# -- the walk -------------------------------------------------------------

def test_the_top_level_walk_sees_nothing_of_this_form(renderer):
    """Every top-level paragraph of ``saeopja`` is skipped as a table.

    This is the whole mechanism: not that the attribution was wrong, but that
    it was never asked.
    """
    reasons = []
    for section in range(len(renderer.sections)):
        for el in own_render._kids(renderer.sections[section], "p"):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = lineseg_vs_pdf.character_cells(para)
            reasons.append(lineseg_vs_pdf.skip_reason(para, cells))
    assert reasons and set(reasons) == {"table"}


def test_the_new_walk_reaches_the_paragraphs_inside_the_tables(renderer):
    top = sum(len(list(own_render._kids(renderer.sections[s], "p")))
              for s in range(len(renderer.sections)))
    every = sum(len(HWT.text_paragraphs(renderer, s))
                for s in range(len(renderer.sections)))
    assert every > top
    assert any(HWT.text_paragraphs(renderer, s)
               and renderer.paragraph_index.get(id(el)) == PINNED
               for s in range(len(renderer.sections))
               for el in HWT.text_paragraphs(renderer, s))


# -- what the table now declares ------------------------------------------

def test_the_table_is_still_declared_measured_and_widths_only(payload):
    declaration = payload["declaration"]
    assert declaration["status"] == "MEASURED"
    assert declaration["contains"] == "advance widths only"
    assert "no font program" in declaration["does_not_contain"]


def test_the_digits_of_the_pinned_face_are_carried(payload):
    widths = payload["faces"][FACE]["widths"]
    for digit in "0123456789":
        entry = widths["U+%04X" % ord(digit)]
        assert entry["advance_em"] == pytest.approx(DIGIT_EM)
        assert entry["observations"] >= 1
        assert "saeopja-deungnok-sinchengseo" in entry["forms"]


def test_every_hangul_row_is_the_declared_cell(payload):
    """So no hangul row can move an advance, whatever the cell did to it."""
    for face, seat in payload["faces"].items():
        for cp, entry in seat["widths"].items():
            if advance_probe.char_class(entry["char"]) != "hangul":
                continue
            assert entry["advance_em"] == pytest.approx(1.0), (face, cp)


def test_the_in_table_check_is_declared_and_read_per_class(payload):
    """The residual is reported, not hidden, and says which classes agree."""
    check = payload["declaration"]["verification_in_table"]
    assert check["observations"] > 0
    per_class = check["per_class"]
    for klass in ("digit", "punct"):
        assert per_class[klass]["median_abs_em"] <= 0.01


# -- the renderer's own gate ----------------------------------------------

def test_the_renderer_meters_the_pinned_line_off_the_table(renderer):
    """Asked of ``_declared_hft_face`` and the loaded table, not the JSON."""
    para = _paragraph(renderer, PINNED)
    table = renderer.hft_widths
    assert table, "the renderer loaded no table"
    seen = 0
    for char, cid in para.chars:
        if not char.isdigit():
            continue
        assert renderer._declared_hft_face(cid, char) == FACE
        assert table.advance_em(FACE, char) == pytest.approx(DIGIT_EM)
        seen += 1
    assert seen >= 4


# -- the falsifiable claim ------------------------------------------------

def test_the_pinned_cell_breaks_with_the_table_and_not_without_it():
    """¶393: cache [7]; ours [5, 9] without the table, [7] with it."""
    if not FORM.is_file():
        pytest.skip("the corpus form is not in this checkout")
    verdicts = {}
    for variant in ("current", "table"):
        with HWT.variant(variant):
            rows = {row["address"]: row for row in
                    advance_probe.break_scoreboard(FORM, dpi=144,
                                                   repo_root=ROOT)}
        row = rows[PINNED]
        verdicts[variant] = (row["match"], list(row["cache_breaks"]),
                             list(row["computed_breaks"]))
    without_match, cache, without = verdicts["current"]
    with_match, cache_again, withtable = verdicts["table"]
    assert cache == cache_again
    assert without_match is False
    assert without != cache
    assert with_match is True
    assert withtable == cache


def _paragraph(renderer, address):
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        for el in renderer.sections[section].iter():
            if own_render._local(el.tag) != "p":
                continue
            if renderer.paragraph_index.get(id(el)) == address:
                return own_render.Paragraph(el, renderer.defs["para_pr"])
    raise AssertionError("paragraph %s is not in this form" % address)
