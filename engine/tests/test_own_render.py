# -*- coding: utf-8 -*-
"""own_render.py — Rigorloom's own OWPML renderer, first slice.

What is pinned here, and why each one is worth a test:

  * the page is the document's own page, not a guess — pixel size follows
    ``hp:pagePr`` at the requested DPI;
  * ``gianmun-byeolji-1ho`` is one page.  It is the canonical fixture and the
    pagination heuristic (``vertpos`` restart) has to not split it;
  * the same bytes in give the same bytes out.  Certification
    (``pipeline/scripts/render_cert.py``) compares rasters, so a renderer that
    wobbles between runs cannot be measured at all;
  * text actually lands where the table geometry says the row is.  Coarse on
    purpose: this asserts ink in a band, never glyph shapes;
  * the sidecar's ``elements_skipped`` is non-vacuous on a document with an
    element this tier does not draw.  The honesty rule is only real if a
    silent drop would fail a test.

Corpus fixtures are the committed public forms under ``tests/corpus/forms``;
the module skips when they or Pillow are absent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import own_render  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")
GIANMUN = os.path.join(CORPUS, "gianmun-byeolji-1ho.hwpx")
PICTURE_FORM = os.path.join(CORPUS, "jeongbo-gonggae-cheongguseo.hwpx")

pytestmark = pytest.mark.skipif(
    not own_render.pillow_available(),
    reason="Pillow is not installed; own_render cannot rasterise")


def _need(path):
    if not os.path.isfile(path):
        pytest.skip(f"corpus fixture missing: {path}")
    return path


@pytest.fixture(scope="module")
def gianmun_render(tmp_path_factory):
    out = tmp_path_factory.mktemp("gianmun")
    return own_render.render_to_dir(_need(GIANMUN), out, dpi=144)


# ---------------------------------------------------------------- page shape

def test_gianmun_renders_as_a_single_page(gianmun_render):
    report = gianmun_render["report"]
    assert report["pages"] == 1
    assert len(gianmun_render["pngs"]) == 1
    assert os.path.isfile(gianmun_render["pngs"][0])


def test_page_pixels_follow_the_documents_own_page_metrics(gianmun_render):
    from PIL import Image

    report = gianmun_render["report"]
    geo = report["page_geometry_hwpunit"]
    # A4 in HWPUNIT, as every corpus form declares it and as
    # form_inspect._page_metrics documents the unit (1/7200 inch).
    assert (geo["width"], geo["height"]) == (59528, 84188)
    expected = (round(geo["width"] * 144 / own_render.HWPUNIT_PER_INCH),
                round(geo["height"] * 144 / own_render.HWPUNIT_PER_INCH))
    assert tuple(report["page_size_px"]) == expected
    with Image.open(gianmun_render["pngs"][0]) as img:
        assert img.size == expected


def test_dpi_scales_the_page(tmp_path):
    low = own_render.render_to_dir(_need(GIANMUN), tmp_path / "low", dpi=72)
    high = own_render.render_to_dir(_need(GIANMUN), tmp_path / "high", dpi=144)
    lw, lh = low["report"]["page_size_px"]
    hw, hh = high["report"]["page_size_px"]
    # Each dimension is rounded independently at each DPI, so doubling the DPI
    # doubles the page to within one pixel, not exactly.
    assert abs(hw - lw * 2) <= 1 and abs(hh - lh * 2) <= 1


# ---------------------------------------------------------------- honesty

def test_sidecar_declares_an_uncertified_grade(gianmun_render):
    report = gianmun_render["report"]
    assert report["grade"] == "own-uncertified"
    assert report["renderer"].startswith("rigorloom-own/")
    assert "NOT certified" in report["grade_meaning"]
    assert report["fonts"]["regular"]
    assert report["elements_rendered"]["tables"] >= 1
    assert report["elements_rendered"]["cells"] >= 1
    assert report["elements_rendered"]["text_lines"] >= 1


def test_sidecar_is_written_next_to_the_pages(gianmun_render):
    with open(gianmun_render["sidecar"], encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk["grade"] == "own-uncertified"
    assert on_disk["png_pages"] == [
        os.path.basename(p) for p in gianmun_render["pngs"]]


def test_skipped_elements_are_named_not_dropped(tmp_path):
    """A form carrying an element this tier cannot draw must say so.

    ``hp:equation`` is the element the slice was scoped around, but none of the
    ten committed corpus forms contains one (verified by scanning every
    ``Contents/section*.xml``), so the probe uses the same contract on the
    element the corpus does carry: ``hp:pic``.  Both take the same code path —
    ``_render_placeholder`` — so this pins the behaviour for equations too.
    """
    result = own_render.render_to_dir(_need(PICTURE_FORM), tmp_path, dpi=144)
    report = result["report"]
    skipped = {entry["element"] for entry in report["elements_skipped"]}
    assert "hp:pic" in skipped, skipped
    assert report["elements_rendered"]["placeholders"] >= 1
    for entry in report["elements_skipped"]:
        assert entry["reason"], entry
        assert entry["count"] >= 1


def test_equation_reaches_the_placeholder_path(tmp_path):
    """No corpus form has an equation, so drive the path directly.

    Keeps the 수식 placeholder honest without inventing a fixture document.
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    image = renderer.Image.new("RGB", (400, 200), (255, 255, 255))
    draw = renderer.ImageDraw.Draw(image)
    equation = ET.fromstring(
        '<hp:equation xmlns:hp="urn:x"><hp:sz width="7200" height="3600"/>'
        "</hp:equation>")
    renderer._render_placeholder(draw, equation, "equation", (0, 0))
    assert renderer.counts["placeholders"] == 1
    skipped = {entry["element"] for entry in renderer.skipped.values()}
    assert "hp:equation" in skipped
    assert image.convert("L").getextrema()[0] < 255  # the box was drawn


def test_sidecar_records_every_text_line_box(gianmun_render):
    """The geometry channel a Hancom comparison actually runs on.

    The raster channel drowns in font substitution, so ``render_scoreboard``
    pairs these boxes against the reference PDF's text lines instead.  A box
    per counted text line, inside the page, is the contract.
    """
    report = gianmun_render["report"]
    boxes = report["line_boxes"]
    assert len(boxes) == report["elements_rendered"]["text_lines"]
    width, height = report["page_size_px"]
    for box in boxes:
        assert box["page"] == 1
        assert box["x1"] > box["x0"], box
        assert box["y1"] > box["y0"], box
        assert -1 <= box["x0"] and box["x1"] <= width + 1, box
        assert -1 <= box["y0"] and box["y1"] <= height + 1, box


def test_line_boxes_exclude_an_inline_placeholder(gianmun_render):
    """A box is the *text* extent, not the item extent.

    gianmun's 발신명의 line carries an inline 직인 rectangle beside the text.
    If the placeholder inflated the line box, every such box would be paired
    against a reference text line it does not describe.
    """
    report = gianmun_render["report"]
    widths = [b["x1"] - b["x0"] for b in report["line_boxes"]]
    # The page is 1191 px at 144 dpi; no text line on this form spans it.
    assert max(widths) < report["page_size_px"][0]
    assert min(widths) > 0


# ------------------------------------------------------- character typography

@pytest.fixture(scope="module")
def typo_probe():
    """A renderer plus a scratch canvas, for measuring advances directly."""
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    image = renderer.Image.new("RGB", (2000, 300), (255, 255, 255))
    renderer._image = image
    return renderer, image, renderer.ImageDraw.Draw(image)


def _synthetic_charpr(renderer, cid, height=1000, **metrics):
    """Install a charPr with the named character metrics, all slots alike."""
    typography = {}
    for metric, default in own_render.TYPOGRAPHY_DEFAULTS.items():
        value = metrics.get(metric, default)
        typography[metric] = {slot: value for slot in own_render.LANG_SLOTS}
    renderer.defs["char_pr"][cid] = {
        "height_pt": height / 100.0, "color": None, "shade_color": None,
        "bold": False, "italic": False, "underline": None,
        "underline_color": None, "font_ids": {}, "typography": typography,
    }
    renderer._typo_cache.clear()
    return cid


def test_script_slot_assigns_each_script_to_its_own_slot():
    assert own_render.script_slot("가") == "hangul"
    assert own_render.script_slot("ᄀ") == "hangul"
    assert own_render.script_slot("A") == "latin"
    assert own_render.script_slot("7") == "latin"
    assert own_render.script_slot("é") == "latin"
    assert own_render.script_slot("漢") == "hanja"
    assert own_render.script_slot("ひ") == "japanese"
    assert own_render.script_slot("カ") == "japanese"
    assert own_render.script_slot("(") == "symbol"
    assert own_render.script_slot("—") == "symbol"
    # The user slot is never reachable by codepoint; see the sidecar note.
    assert all(own_render.script_slot(chr(c)) != "user"
               for c in range(0x20, 0x3000, 7))


def test_spacing_widens_a_run_by_the_declared_percentage(typo_probe):
    """+50% letter spacing must add 0.5 em per gap, and only per *gap*.

    Measured against the Hancom reference: gianmun's four-character
    발신명의 run is 15 pt with ``spacing="50"`` and the reference PDF draws it
    5.496 em wide — 4 advances plus 3 gaps, not 4 gaps.
    """
    renderer, _image, draw = typo_probe
    plain = _synthetic_charpr(renderer, "__plain__", height=1500)
    spread = _synthetic_charpr(renderer, "__spread__", height=1500, spacing=50)
    text = "발신명의"
    base = renderer._measure(draw, text, plain)
    wide = renderer._measure(draw, text, spread)
    em = 15.0 * 144 / 72.0          # 15 pt at 144 dpi
    assert wide - base == pytest.approx(3 * 0.5 * em, rel=1e-6)
    # ... and the total is the 5.5 em the reference reports as 5.496.
    assert wide / em == pytest.approx(5.5, rel=1e-3)


def test_negative_spacing_narrows_a_run(typo_probe):
    renderer, _image, draw = typo_probe
    plain = _synthetic_charpr(renderer, "__p2__", height=1200)
    tight = _synthetic_charpr(renderer, "__t2__", height=1200, spacing=-7)
    text = "행정기관명"
    em = 12.0 * 144 / 72.0
    delta = (renderer._measure(draw, text, tight)
             - renderer._measure(draw, text, plain))
    assert delta == pytest.approx(-4 * 0.07 * em, rel=1e-6)


def test_ratio_scales_the_advance_and_the_drawn_ink(typo_probe):
    """hh:ratio is a horizontal glyph scale: advance *and* ink must narrow."""
    renderer, image, draw = typo_probe
    plain = _synthetic_charpr(renderer, "__r100__", height=2000)
    narrow = _synthetic_charpr(renderer, "__r60__", height=2000, ratio=60)
    text = "행정기관명"
    base = renderer._measure(draw, text, plain)
    assert renderer._measure(draw, text, narrow) == pytest.approx(
        base * 0.60, rel=1e-6)

    def ink_width(cid):
        canvas = renderer.Image.new("RGB", (2000, 300), (255, 255, 255))
        renderer._image = canvas
        canvas_draw = renderer.ImageDraw.Draw(canvas)
        pieces = renderer._text_pieces(canvas_draw, cid, text)
        x = 20.0
        for piece in pieces:
            if piece["kind"] == "glyph":
                piece["colour"] = (0, 0, 0)
                renderer._draw_glyph_piece(canvas_draw, piece, x, 200.0)
            x += piece["advance"]
        box = canvas.convert("L").point(lambda v: 255 if v < 200 else 0)
        return box.getbbox()[2] - box.getbbox()[0]

    try:
        wide_ink = ink_width(plain)
        narrow_ink = ink_width(narrow)
    finally:
        renderer._image = image
    assert narrow_ink < wide_ink
    assert narrow_ink / wide_ink == pytest.approx(0.60, abs=0.03)


def test_relsz_scales_the_character_size(typo_probe):
    """hh:relSz is not exercised by any corpus form; drive it directly."""
    renderer, _image, draw = typo_probe
    plain = _synthetic_charpr(renderer, "__s100__", height=2000)
    half = _synthetic_charpr(renderer, "__s50__", height=2000, relSz=50)
    text = "행정기관명"
    assert renderer._measure(draw, text, half) == pytest.approx(
        renderer._measure(draw, text, plain) * 0.5, rel=0.02)


def test_offset_raises_the_baseline_and_the_line_box(typo_probe):
    """hh:offset is not exercised by any corpus form; drive it directly."""
    renderer, _image, draw = typo_probe
    raised = _synthetic_charpr(renderer, "__up__", height=1000, offset=30)
    piece = renderer._text_pieces(draw, raised, "가")[0]
    size_px = piece["size_px"]
    assert piece["offset_px"] == pytest.approx(size_px * 0.30)

    canvas = renderer.Image.new("RGB", (400, 400), (255, 255, 255))
    keep = renderer._image
    renderer._image = canvas
    try:
        canvas_draw = renderer.ImageDraw.Draw(canvas)
        piece["colour"] = (0, 0, 0)
        renderer._draw_glyph_piece(canvas_draw, piece, 20.0, 300.0)
        top_raised = canvas.convert("L").point(
            lambda v: 255 if v < 200 else 0).getbbox()[1]
        flat = renderer._text_pieces(
            canvas_draw, _synthetic_charpr(renderer, "__flat__",
                                           height=1000), "가")[0]
        canvas2 = renderer.Image.new("RGB", (400, 400), (255, 255, 255))
        renderer._image = canvas2
        flat["colour"] = (0, 0, 0)
        renderer._draw_glyph_piece(renderer.ImageDraw.Draw(canvas2), flat,
                                   20.0, 300.0)
        top_flat = canvas2.convert("L").point(
            lambda v: 255 if v < 200 else 0).getbbox()[1]
    finally:
        renderer._image = keep
    assert top_flat - top_raised == pytest.approx(size_px * 0.30, abs=2)


def test_the_slot_model_is_load_bearing_on_exactly_three_corpus_metrics():
    """Measured, so a change to the slot table cannot pass unnoticed.

    Of the 791 charPr definitions across the ten corpus forms, only three
    give one language slot a different value from the rest (kstartup 188/189
    ratio, saeopja 90 spacing).  The slot model is therefore *nearly* inert on
    this corpus — worth writing down, because a test suite that only exercised
    these forms could not tell a working slot model from a broken one, which is
    why the mechanics above use synthetic charPr instead.
    """
    import glob
    import zipfile

    varying = 0
    definitions = 0
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.hwpx"))):
        with zipfile.ZipFile(path) as archive:
            name = next(n for n in archive.namelist()
                        if n.endswith("header.xml"))
            defs = own_render.parse_header(archive.read(name))
        for entry in defs["char_pr"].values():
            definitions += 1
            for slots in entry["typography"].values():
                values = {v for slot, v in slots.items() if slot != "user"}
                if len(values) > 1:
                    varying += 1
    if definitions == 0:
        pytest.skip("corpus fixtures missing")
    assert definitions == 791, f"corpus drifted: {definitions} charPr"
    assert varying == 3, f"corpus drifted: {varying} slot-varying metrics"


def test_the_spread_run_matches_the_hancom_reference_in_em(typo_probe):
    """The named gap from the endgame plan, closed against a Hancom number.

    gianmun's 발신명의 run carries ``charPr`` id 8: 15 pt, ``ratio="100"``,
    ``spacing="50"``.  Hancom's own render of the same form draws that span
    58.65 pt wide at a reported size of 10.67 pt = **5.496 em**.  Em is the
    right unit here because that reference PDF is one of the three the
    scoreboard flags as a ~0.707 print reduction — the ratio is scale-free,
    the absolute pixels are not.

    Before this slice the same run measured 4.0 em (spacing dropped), which is
    exactly the "renders tight where the authoring engine spreads it" defect.
    """
    renderer, _image, draw = typo_probe
    cp = renderer.defs["char_pr"]["8"]
    assert cp["height_pt"] == 15.0, "fixture drifted: charPr 8 height"
    assert cp["typography"]["spacing"]["hangul"] == 50
    assert cp["typography"]["ratio"]["hangul"] == 100
    em = 15.0 * 144 / 72.0
    measured = renderer._measure(draw, "발신명의", "8") / em
    assert measured == pytest.approx(5.496, abs=0.02), measured


def test_gianmun_declares_and_applies_the_metrics_it_carries(gianmun_render):
    """The sidecar must say what was applied, not only what was skipped."""
    applied = gianmun_render["report"]["typography"]["applied_characters"]
    assert applied["hh:spacing"] > 300, applied
    assert applied["hh:ratio"] > 0, applied
    # No corpus form declares relSz or offset away from neutral, so claiming
    # them here would be a lie the tests above cover instead.
    assert "hh:relSz" not in applied
    assert "hh:offset" not in applied


# ------------------------------------------------------------- alignment

def test_centring_lands_at_the_computed_centre(typo_probe):
    renderer, _image, _draw = typo_probe
    assert renderer._align_offset("CENTER", 1000.0, 400.0) == 300.0
    assert renderer._align_offset("RIGHT", 1000.0, 400.0) == 600.0
    assert renderer._align_offset("LEFT", 1000.0, 400.0) == 0.0
    # JUSTIFY and DISTRIBUTE start at the left; their slack goes into gaps.
    assert renderer._align_offset("JUSTIFY", 1000.0, 400.0) == 0.0
    assert renderer._align_offset("DISTRIBUTE", 1000.0, 400.0) == 0.0
    # An overrunning line is never pulled back.
    assert renderer._align_offset("CENTER", 400.0, 1000.0) == 0.0


def test_a_centred_line_lands_on_its_boxs_centre_with_typography_applied():
    """Centring is computed from the *resulting* advance, spacing included.

    The failure this guards against is subtle and was the reason the endgame
    plan names centring alongside typography: if the alignment offset were
    taken from the unspaced width, a run with ``spacing="50"`` would be drawn
    half its added width to the right of where the authoring engine puts it.
    """
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    box_hwp = 40000                       # the line box, in HWPUNIT
    for spacing in (0, 50, -10):
        canvas = renderer.Image.new("RGB", (1200, 400), (255, 255, 255))
        renderer._image = canvas
        renderer.line_boxes = []
        cid = _synthetic_charpr(renderer, f"__c{spacing}__", height=1500,
                                spacing=spacing)
        draw = renderer.ImageDraw.Draw(canvas)
        items = [("text", own_render.Segment("발신명의", cid))]
        renderer._draw_line(draw, items, 0, 0, 20000, "CENTER", box_hwp)
        assert len(renderer.line_boxes) == 1
        drawn = renderer.line_boxes[0]
        used = renderer._measure(draw, "발신명의", cid)
        box_px = renderer.pxf(box_hwp)
        assert drawn["x0"] == pytest.approx((box_px - used) / 2.0, abs=0.01)
        assert ((drawn["x0"] + drawn["x1"]) / 2.0
                == pytest.approx(box_px / 2.0, abs=0.01))


def test_justify_stretches_every_line_but_the_last(typo_probe):
    renderer, _image, _draw = typo_probe
    # 10 elastic slots, 300 px of slack.
    assert renderer._justify_extra("JUSTIFY", 1000.0, 700.0, 10,
                                   last_line=False) == 30.0
    assert renderer._justify_extra("JUSTIFY", 1000.0, 700.0, 10,
                                   last_line=True) == 0.0
    # DISTRIBUTE stretches the last line too.
    assert renderer._justify_extra("DISTRIBUTE", 1000.0, 700.0, 10,
                                   last_line=True) == 30.0
    # Nothing is ever shrunk, and a line with no slots absorbs nothing.
    assert renderer._justify_extra("DISTRIBUTE", 700.0, 1000.0, 10,
                                   last_line=True) == 0.0
    assert renderer._justify_extra("DISTRIBUTE", 1000.0, 700.0, 0,
                                   last_line=True) == 0.0
    assert renderer._justify_extra("LEFT", 1000.0, 700.0, 10,
                                   last_line=False) == 0.0


def test_justification_stretches_spaces_when_the_line_has_them():
    pieces = [
        {"kind": "glyph", "text": "the ", "advance": 40.0},
        {"kind": "gap", "advance": 0.0},
        {"kind": "glyph", "text": "cat", "advance": 30.0},
        {"kind": "gap", "advance": 0.0},
    ]
    assert own_render.OwnRenderer._elastic_slots(pieces) == [1]
    hangul = [
        {"kind": "glyph", "text": "가", "advance": 20.0},
        {"kind": "gap", "advance": 0.0},
        {"kind": "glyph", "text": "나", "advance": 20.0},
        {"kind": "gap", "advance": 0.0},
    ]
    assert own_render.OwnRenderer._elastic_slots(hangul) == [1, 3]


# ---------------------------------------------------------------- determinism

def test_two_renders_are_byte_identical(tmp_path):
    first = own_render.render_to_dir(_need(GIANMUN), tmp_path / "a", dpi=144)
    second = own_render.render_to_dir(_need(GIANMUN), tmp_path / "b", dpi=144)
    assert len(first["pngs"]) == len(second["pngs"])
    for left, right in zip(first["pngs"], second["pngs"]):
        with open(left, "rb") as fh:
            a = fh.read()
        with open(right, "rb") as fh:
            b = fh.read()
        assert a == b, "identical input produced different PNG bytes"


# ---------------------------------------------------------------- geometry

def test_solve_tracks_closes_an_underdetermined_grid():
    """Column widths come out of span constraints, not out of unit cells alone.

    The gianmun header table declares 15 columns but only 6 of them carry a
    ``colSpan="1"`` cell; the other 9 are only ever covered by merged cells.
    Elimination recovers all 15 and the total matches the table's ``hp:sz``.
    """
    constraints = [
        (0, 14, 39408), (14, 1, 5636), (0, 15, 45044),
        (0, 3, 14934), (3, 6, 14073), (9, 6, 16037),
        (0, 1, 5900), (1, 1, 5598), (2, 2, 6237), (4, 1, 4369),
        (5, 3, 5325), (8, 2, 8713), (10, 3, 2134), (13, 2, 6768),
        (1, 4, 16204), (8, 7, 17615), (1, 5, 19018), (6, 1, 848),
        (7, 8, 19278), (0, 2, 11498), (2, 4, 13420), (11, 1, 565),
        (7, 4, 11336), (12, 3, 7377),
    ]
    widths = own_render.solve_tracks(15, constraints, declared_total=45044)
    assert all(w > 0 for w in widths), widths
    assert sum(widths) == 45044
    # every constraint the file gave must still hold after the solve
    for start, span, total in constraints:
        assert sum(widths[start:start + span]) == total, (start, span)


def test_solve_tracks_matches_declared_total_even_when_underdetermined():
    widths = own_render.solve_tracks(3, [(0, 3, 300)], declared_total=300)
    assert widths == [100, 100, 100]
    assert sum(widths) == 300


# ---------------------------------------------------------------- ink probe

def _table_zero_geometry(path, dpi=144):
    renderer = own_render.OwnRenderer(path, dpi=dpi)
    geo = renderer.page_geometry()
    section = renderer.sections[0]
    table = next(el for el in section.iter()
                 if own_render._local(el.tag) == "tbl")
    xs, ys, cells = renderer._table_tracks(table)
    return renderer, geo, xs, ys, cells


def test_ink_lands_in_the_row_the_table_geometry_names(gianmun_render):
    """Coarse text-presence probe over the 행정기관명 row.

    Cross-checked against the repo's existing structural view: the row is
    located by ``form_inspect``'s table_map (whose ``text_preview`` names the
    cell), and the band is then taken from this renderer's own solved track
    geometry.  The assertion is only that the band has dark pixels and that a
    band the form leaves blank does not — never where a glyph sits.
    """
    from PIL import Image

    import form_inspect

    # 1. locate the row with the repo's existing structural view, so the probe
    #    is anchored to table_map's addressing and not to this renderer's.
    profile, _baseline = form_inspect.analyze(_need(GIANMUN))
    table = profile["table_map"][0]
    seat = next(c for c in table["cells"]
                if "행 정 기 관 명" in (c["text_preview"] or ""))
    row, col = seat["addr"]["row"], seat["addr"]["col"]
    assert (row, col) == (1, 0), "fixture drifted: 행정기관명 moved"

    # 2. take the band from this renderer's own solved tracks — that is where
    #    it actually drew, so a mismatch between the two is a real failure.
    renderer, geo, xs, ys, cells = _table_zero_geometry(_need(GIANMUN))
    top = geo["body_top"] + ys[row]
    bottom = geo["body_top"] + ys[row + seat["span"]["row"]]
    left = geo["body_left"] + xs[col]
    right = geo["body_left"] + xs[col + seat["span"]["col"]]

    with Image.open(gianmun_render["pngs"][0]) as img:
        grey = img.convert("L")
        band = grey.crop((renderer.px(left), renderer.px(top),
                          renderer.px(right), renderer.px(bottom)))
        assert band.getextrema()[0] < 128, "no ink in the 행정기관명 row"

        # The row directly under it is the blank body area of the form; its
        # upper strip must stay paper-white, or the probe above proves nothing.
        blank_top = geo["body_top"] + ys[2]
        blank = grey.crop((renderer.px(left), renderer.px(blank_top) + 4,
                           renderer.px(right), renderer.px(blank_top) + 60))
        assert blank.getextrema()[0] == 255, "ink where the form is blank"


def test_every_declared_solid_border_is_drawn_and_no_others(gianmun_render):
    """gianmun looks border-less because it *is*, not because we drop borders.

    Counting the file's own declarations: of the 136 cell sides across its 34
    cells, 13 are SOLID and the rest are type="NONE" (19 cells share a
    borderFill whose four sides are all NONE — the blank body of the letter).
    The renderer must draw exactly those 13. This pins both directions: a
    regression that stops drawing real rules fails, and one that starts
    stroking the invisible grid fails too.
    """
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    declared = 0
    for el in renderer.sections[0].iter():
        if own_render._local(el.tag) != "tc":
            continue
        cellpr = own_render._kid(el, "cellPr") or el
        fill = renderer.defs["border_fill"].get(
            cellpr.get("borderFillIDRef") or "")
        if fill is None:
            continue
        for side in ("left", "right", "top", "bottom"):
            if (fill[side]["type"] or "NONE").upper() != "NONE":
                declared += 1

    assert declared == 13, f"fixture drifted: {declared} solid sides declared"
    assert gianmun_render["report"]["elements_rendered"]["borders"] == declared


def test_a_form_with_a_real_grid_draws_it(tmp_path):
    """Positive control for the test above — border drawing does work."""
    result = own_render.render_to_dir(_need(PICTURE_FORM), tmp_path, dpi=96)
    assert result["report"]["elements_rendered"]["borders"] > 100


# ---------------------------------------------------------------- corpus sweep

@pytest.mark.parametrize("name", [
    "admrul-gajokdolbom-hyuga-sinchengseo.hwpx",
    "gianmun-byeolji-1ho.hwpx",
    "gianmun-byeolji-2ho.hwpx",
    "jeongbo-gonggae-cheongguseo.hwpx",
    "jumin-deungchobon-sinchengseo.hwpx",
    "moel-pyojun-geunrogyeyakseo-2013.hwpx",
    "moel-pyojun-geunrogyeyakseo-2025.hwpx",
    "nrf-gyeolgwa-bogoseo-yangsik.hwpx",
    "saeopja-deungnok-sinchengseo.hwpx",
])
def test_every_corpus_form_renders(tmp_path, name):
    """No corpus form may crash the renderer, and none may render blank."""
    result = own_render.render_to_dir(
        _need(os.path.join(CORPUS, name)), tmp_path, dpi=96)
    report = result["report"]
    assert report["pages"] >= 1
    assert report["elements_rendered"]["text_lines"] >= 1


# ---------------------------------------------------------------- CLI

def test_version_flag_prints_one_line():
    proc = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "scripts", "own_render.py"),
         "--version"],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"rigorloom-own {own_render.RENDERER_VERSION}"


def test_cli_writes_pages_and_sidecar(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "scripts", "own_render.py"),
         _need(GIANMUN), "--out-dir", str(tmp_path), "--dpi", "96"],
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["report"]["grade"] == "own-uncertified"
    assert (tmp_path / "gianmun-byeolji-1ho.render.json").is_file()
    assert (tmp_path / "gianmun-byeolji-1ho-p1.png").is_file()


def test_cli_rejects_a_missing_input(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "scripts", "own_render.py"),
         str(tmp_path / "nope.hwpx"), "--out-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 2
