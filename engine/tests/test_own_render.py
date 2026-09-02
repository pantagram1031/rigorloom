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
    assert report["fonts"]["fallback_regular"]
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


# ---------------------------------------------------------------- fonts

def test_the_font_index_reads_a_faces_own_family_names():
    """Including the Korean records FreeType does not expose.

    This is the whole mechanism of face resolution: a document says 돋움 and
    only the font file itself knows that Dotum answers to that name.
    """
    index = own_render.SystemFontIndex.shared()
    if not index.families:
        pytest.skip("no system fonts found on this machine")
    assert index.scanned > 0
    # Latin families resolve by their only name.
    latin = index.lookup("Times New Roman")
    if latin is None:
        pytest.skip("Times New Roman is not installed")
    assert latin["regular"] is not None


def test_normalising_a_face_name_ignores_separators_but_not_identity():
    assert own_render._normalise_face("맑은 고딕") == own_render._normalise_face(
        "맑은고딕")
    assert own_render._normalise_face("Times New Roman") == "timesnewroman"
    # 돋움 and 돋움체 are different faces and must not collapse together.
    assert own_render._normalise_face("돋움") != own_render._normalise_face("돋움체")


def test_gianmun_resolves_every_face_it_declares(gianmun_render):
    """gianmun declares 돋움 / 돋움체 / 한양중고딕 / 한양견고딕.

    Hancom's own render of this form uses Dotum and DotumChe (the reference
    PDF names them in its font descriptors), so a resolver that lands on the
    same families is measurably right, not merely plausible.  On a machine
    missing them the share drops and the sidecar says which face was
    substituted — that is the honest failure, and it is what makes this test
    a skip rather than a lie elsewhere.
    """
    fonts = gianmun_render["report"]["fonts"]
    assert fonts["pinned_single_face"] is False
    if fonts["resolved_character_share"] in (None, 0):
        pytest.skip("no declared face of this form is installed here")
    declared = {f["declared"] for f in fonts["faces"]}
    assert "돋움" in declared and "돋움체" in declared, declared
    families = {f["installed_family"] for f in fonts["faces"] if f["resolved"]}
    assert "돋움" in families or "Dotum" in families, families
    for face in fonts["faces"]:
        assert face["characters"] >= 1
        if face["resolved"]:
            assert face["file"], face
        else:
            assert face["substituted_with"], face


def test_a_face_the_machine_does_not_have_is_named_as_substituted(tmp_path):
    """The substitution path, driven without depending on a missing font.

    An empty font index cannot resolve anything, so every declared face has to
    come back substituted — and every one of them has to appear in
    ``elements_skipped``, not just in the fonts block.
    """
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=96)
    renderer.font_index = own_render.SystemFontIndex(directories=[
        str(tmp_path / "no-such-directory")])
    renderer._face_cache.clear()
    _images, report = renderer.render()
    fonts = report["fonts"]
    assert fonts["characters_on_a_resolved_face"] == 0
    assert fonts["characters_on_a_substituted_face"] > 0
    assert fonts["resolved_character_share"] == 0.0
    named = {e["element"] for e in report["elements_skipped"]}
    assert any(e.startswith("hh:fontface[") for e in named), named


def test_pinning_one_face_turns_per_face_resolution_off(monkeypatch, tmp_path):
    """RIGORLOOM_OWN_RENDER_FONT is how a run takes the machine out of the
    measurement: one face, declared as pinned, no system index at all."""
    import os

    face = os.path.join("C:\\Windows\\Fonts", "malgun.ttf")
    if not os.path.isfile(face):
        pytest.skip("no pinnable face on this machine")
    monkeypatch.setenv("RIGORLOOM_OWN_RENDER_FONT", face)
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=96)
    assert renderer.pinned_face is True
    assert renderer.font_index is None
    _images, report = renderer.render()
    assert report["fonts"]["pinned_single_face"] is True
    assert report["fonts"]["faces"] == []


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


# ------------------------------------------------- line breaking (E2.1)
#
# The breaker is graded twice over.  Its *mechanics* — which positions the
# paragraph's own hh:breakSetting permits, what 금칙처리 forbids, what condense
# tolerates, what the vertical metrics come to — are pinned on synthetic
# paragraphs, because the corpus declares far too narrow a range of these
# attributes to tell a working implementation from a broken one.  Its
# *agreement with the authoring engine* is measured on the corpus, exactly,
# below.

def _synthetic_paragraph(renderer, text, cid, para_id="__para__", **parapr):
    """An ``hp:p`` carrying ``text`` under a paraPr the test declares."""
    from xml.etree import ElementTree as ET

    settings = {
        "align": "LEFT", "break_latin": "KEEP_WORD",
        "break_non_latin": "KEEP_WORD", "line_wrap": "BREAK",
        "widow_orphan": 0, "keep_with_next": 0, "keep_lines": 0,
        "page_break_before": 0, "condense": 0, "font_line_height": 0,
        "snap_to_grid": 0, "tab_pr": None, "line_spacing_type": "PERCENT",
        "line_spacing_value": 100, "line_spacing_unit": "HWPUNIT",
        "margin_left": 0, "margin_right": 0, "indent": 0,
    }
    settings.update(parapr)
    renderer.defs["para_pr"][para_id] = settings
    element = ET.fromstring(
        '<hp:p xmlns:hp="urn:x" paraPrIDRef="{pid}">'
        '<hp:run charPrIDRef="{cid}"><hp:t>{text}</hp:t></hp:run>'
        "</hp:p>".format(pid=para_id, cid=cid, text=text))
    return own_render.Paragraph(element, renderer.defs["para_pr"])


def _breaks(renderer, draw, text, cid, column_hwp, **parapr):
    para = _synthetic_paragraph(renderer, text, cid, **parapr)
    lines = renderer.compute_lines(draw, para, column_hwp)
    return [(line["start"], line["end"]) for line in lines], lines


def test_break_opportunities_follow_the_paragraphs_own_break_setting():
    """hh:breakSetting decides where a line MAY break; nothing else does."""
    hangul = "가나다라마"
    # KEEP_WORD (어절 단위): no break inside a run of Hangul with no space.
    assert own_render.break_opportunities(hangul, break_non_latin="KEEP_WORD") == []
    # BREAK_WORD (글자 단위): between every pair of syllables.
    assert own_render.break_opportunities(
        hangul, break_non_latin="BREAK_WORD") == [1, 2, 3, 4]
    # A space is a break opportunity whatever the attributes say, and the
    # break goes AFTER the space, never before it.
    assert own_render.break_opportunities("가나 다라") == [3]
    latin = "abcde"
    assert own_render.break_opportunities(latin, break_latin="KEEP_WORD") == []
    assert own_render.break_opportunities(
        latin, break_latin="BREAK_WORD") == [1, 2, 3, 4]
    # The two attributes are independent, and the boundary between the two
    # scripts is governed by the non-Latin one.
    assert own_render.break_opportunities(
        "가abc나", break_latin="BREAK_WORD",
        break_non_latin="KEEP_WORD") == [2, 3]


def test_prohibited_characters_never_start_or_end_a_line():
    """금칙처리, on the table this renderer declares in every sidecar."""
    # ')' may not start a line, so the break before it is withdrawn.
    assert own_render.break_opportunities(
        "가나)다", break_non_latin="BREAK_WORD") == [1, 3]
    # '(' may not end one, so the break after it is withdrawn.
    assert own_render.break_opportunities(
        "가(나다", break_non_latin="BREAK_WORD") == [1, 3]
    # The filter applies to a space break too, not only a syllable break.
    assert own_render.break_opportunities("가나 ”다") == []
    for ch in ")]}.,?!。、":
        assert ch in own_render.LINE_START_PROHIBITED, ch
    for ch in "([{（「":
        assert ch in own_render.LINE_END_PROHIBITED, ch


def test_hangul_wraps_at_the_syllable_the_box_ends_on(typo_probe):
    """BREAK_WORD puts as many syllables on the line as the box holds."""
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__brk__", height=1000)
    em = own_render.HWPUNIT_PER_PT * 10          # one 10 pt cell, in HWPUNIT
    spans, lines = _breaks(renderer, draw, "가나다라마바사아자차", cid, em * 4,
                           break_non_latin="BREAK_WORD")
    assert spans == [(0, 4), (4, 8), (8, 10)], spans
    assert not any(line["forced"] for line in lines)
    for line in lines:
        assert line["width_px"] <= renderer.pxf(line["horzsize"]) + 1e-6


def test_a_latin_word_moves_whole_unless_the_paragraph_breaks_words(typo_probe):
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__lat__", height=1000)
    column = own_render.HWPUNIT_PER_PT * 10 * 4
    keep, _ = _breaks(renderer, draw, "aa bbbbbbbb cc", cid, column,
                      break_latin="KEEP_WORD")
    assert keep[0][1] == 3, keep      # 'aa ' then the whole long word moves
    split, lines = _breaks(renderer, draw, "aa bbbbbbbb cc", cid, column,
                           break_latin="BREAK_WORD")
    assert split != keep, "BREAK_WORD must be able to split the word"
    assert all(not line["forced"] for line in lines)


def test_a_line_with_no_permitted_break_is_cut_and_counted(typo_probe):
    """KEEP_WORD plus one very long word: the box wins, and it is recorded."""
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__forced__", height=1000)
    before = renderer._forced_breaks
    spans, lines = _breaks(renderer, draw, "가나다라마바사아자차", cid,
                           own_render.HWPUNIT_PER_PT * 10 * 3,
                           break_non_latin="KEEP_WORD")
    assert len(spans) > 1, "an unbreakable run still has to fit the page"
    assert any(line["forced"] for line in lines)
    assert renderer._forced_breaks > before


def test_condense_lets_a_line_keep_what_its_spaces_can_give_up(typo_probe):
    """hp:paraPr@condense is 공백 축소: spaces may shrink BY that percentage.

    Which way round the attribute reads was decided by measuring the corpus,
    not by reading its name — see the comment in ``compute_lines``.  What is
    pinned here is the mechanism: with condense=0 (the corpus default, and
    the value 603 of its 774 paraPr carry) a line that overruns breaks, and
    with a condense budget large enough to cover the overrun it does not.
    """
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__cond__", height=1000)
    text = "가나 다라 마바 사아"
    para = _synthetic_paragraph(renderer, text, cid, para_id="__condmeasure__")
    full = renderer.span_width(draw, para, 0, len(text))
    space = renderer._measure(draw, " ", cid)
    # A box narrower than the line by less than what its three spaces can give
    # up at condense=75: the line breaks without that budget and holds with it.
    column = int(renderer.hwp_from_px(full - 1.5 * space))
    tight, _ = _breaks(renderer, draw, text, cid, column, condense=0)
    loose, _ = _breaks(renderer, draw, text, cid, column, condense=75)
    assert len(tight) == 2, tight
    assert len(loose) == 1, loose


def test_line_advance_follows_the_declared_line_spacing(typo_probe):
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__ls__", height=1300)
    _spans, percent = _breaks(renderer, draw, "가나 다라", cid, 100000,
                              line_spacing_type="PERCENT",
                              line_spacing_value=160)
    line = percent[0]
    # The corpus relations, on a synthetic paragraph: vertsize == textheight,
    # baseline == round(0.85 * textheight), vertsize + spacing == 160%.
    assert line["textheight"] == 1300
    assert line["vertsize"] == 1300
    assert line["baseline"] == round(1300 * own_render.BASELINE_RATIO)
    assert line["vertsize"] + line["spacing"] == round(1300 * 1.6)
    _spans, fixed = _breaks(renderer, draw, "가나 다라", cid, 100000,
                            line_spacing_type="FIXED",
                            line_spacing_value=2000)
    assert fixed[0]["vertsize"] + fixed[0]["spacing"] == 2000


def test_the_first_line_carries_the_declared_indent(typo_probe):
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__ind__", height=1000)
    _spans, lines = _breaks(renderer, draw, "가나다라마바사아자차카타파하", cid,
                            own_render.HWPUNIT_PER_PT * 10 * 5,
                            break_non_latin="BREAK_WORD",
                            margin_left=1000, margin_right=500, indent=2000)
    assert lines[0]["horzpos"] == 3000
    assert lines[1]["horzpos"] == 1000
    column = own_render.HWPUNIT_PER_PT * 10 * 5
    assert lines[0]["horzsize"] == column - 3000 - 500
    assert lines[1]["horzsize"] == column - 1000 - 500
    # A negative intent (내어쓰기) moves no box — the corpus's cached boxes
    # say so; see OwnRenderer._line_box.
    _spans, hanging = _breaks(renderer, draw, "가나다라마바사아자차카타파하", cid,
                              column, break_non_latin="BREAK_WORD",
                              margin_left=1000, indent=-2000)
    assert len(hanging) > 1
    assert hanging[0]["horzpos"] == 0        # 1000 + (-2000), clamped at 0
    assert all(line["horzpos"] == 1000 for line in hanging[1:])


def test_line_vertpos_stacks_the_way_the_cached_layout_does(typo_probe):
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__stack__", height=1000)
    _spans, lines = _breaks(renderer, draw, "가나다라마바사아자차", cid,
                            own_render.HWPUNIT_PER_PT * 10 * 4,
                            break_non_latin="BREAK_WORD",
                            line_spacing_value=160)
    assert len(lines) == 3
    assert lines[0]["vertpos"] == 0
    for previous, line in zip(lines, lines[1:]):
        assert line["vertpos"] == (previous["vertpos"] + previous["vertsize"]
                                   + previous["spacing"])


def test_a_tab_advances_to_the_paragraphs_next_declared_stop(typo_probe):
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__tab__", height=1000)
    renderer.defs.setdefault("tab_pr", {})["__stops__"] = {
        "stops": [(20000, "LEFT"), (40000, "LEFT")],
        "auto_left": 0, "auto_right": 0,
    }
    para = _synthetic_paragraph(renderer, "가\t나", cid, para_id="__tabpara__",
                                tab_pr="__stops__")
    # <hp:t> keeps the tab as a literal character here, which is exactly the
    # shape an edited paragraph has when a user presses Tab.
    assert "\t" in para.text
    lines = renderer.compute_lines(draw, para, 100000)
    assert len(lines) == 1
    # 가 + the jump to 20000 HWPUNIT + 나 — the tab is not zero-width.
    assert lines[0]["width_px"] > renderer.pxf(20000)


# ------------------------------------------- line breaking vs the authoring
# engine.  These are THE measurement of this slice, and they are asserted
# exactly: a change that moves any of them has to move the number here too.

LINESEG_AGREEMENT = {
    # form: (scored, line_count_exact, sequence_exact, multiline_scored,
    #        multiline_line_count_exact, cached_break_positions, matched)
    "admrul-gajokdolbom-hyuga-sinchengseo": (22, 22, 21, 2, 2, 2, 1),
    "gianmun-byeolji-1ho": (32, 32, 31, 1, 1, 2, 0),
    "gianmun-byeolji-2ho": (20, 19, 19, 2, 1, 2, 1),
    "jeongbo-gonggae-cheongguseo": (58, 58, 52, 6, 6, 7, 1),
    "jumin-deungchobon-sinchengseo": (133, 132, 113, 27, 26, 36, 9),
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo": (453, 435, 416, 29, 26, 44, 12),
    "moel-pyojun-geunrogyeyakseo-2013": (263, 254, 234, 34, 25, 49, 7),
    "moel-pyojun-geunrogyeyakseo-2025": (314, 304, 283, 37, 27, 47, 6),
    "nrf-gyeolgwa-bogoseo-yangsik": (89, 89, 87, 3, 3, 3, 1),
    "saeopja-deungnok-sinchengseo": (764, 758, 747, 17, 14, 24, 5),
}


@pytest.mark.parametrize("name", sorted(LINESEG_AGREEMENT))
def test_the_breaker_agrees_with_the_authoring_engine_exactly_this_much(name):
    """Run our breaker on unedited text; compare to the document's own cache.

    This number is NOT high and is not presented as if it were.  It is the
    honest state of a from-scratch line breaker measured against the engine
    that wrote the file, and every one of these counts is reproduced by
    ``python own_render.py FORM.hwpx --lineseg-agreement``.

    It depends on which faces this machine has installed — an unresolved face
    is measured with a substitute whose advances differ — so a failure here on
    another machine is a font difference, not necessarily a regression. The
    reference machine is the one named in engine/references/own-render-notes.md.
    """
    path = os.path.join(CORPUS, name + ".hwpx")
    _need(path)
    report = own_render.lineseg_agreement(path, dpi=144)
    a = report["all_paragraphs"]
    m = report["multiline_paragraphs"]
    expected = LINESEG_AGREEMENT[name]
    actual = (a["paragraphs_scored"], a["paragraphs_line_count_exact"],
              a["paragraphs_break_sequence_exact"], m["paragraphs_scored"],
              m["paragraphs_line_count_exact"], a["break_positions_cached"],
              a["break_positions_matched"])
    assert actual == expected, (
        f"{name}: measured {actual}, pinned {expected}. If this machine's "
        "installed fonts differ from the reference machine's, that is the "
        "first thing to check — see report['fonts'].")


def test_the_corpus_wide_agreement_is_exactly_this(tmp_path):
    """The single number the slice is graded on, summed over the corpus."""
    totals = [0] * 7
    for name in sorted(LINESEG_AGREEMENT):
        path = os.path.join(CORPUS, name + ".hwpx")
        _need(path)
        report = own_render.lineseg_agreement(path, dpi=144)
        a = report["all_paragraphs"]
        m = report["multiline_paragraphs"]
        for index, value in enumerate((
                a["paragraphs_scored"], a["paragraphs_line_count_exact"],
                a["paragraphs_break_sequence_exact"], m["paragraphs_scored"],
                m["paragraphs_line_count_exact"],
                a["break_positions_cached"], a["break_positions_matched"])):
            totals[index] += value
    # 2148 paragraphs carry a usable cache; the breaker reproduces the
    # authoring engine's line COUNT on 2103 of them and its exact break
    # SEQUENCE on 2003.  Restricted to the 158 paragraphs that actually break
    # (the rest cannot disagree), it reproduces the line count on 131 and 43
    # of the 216 individual break positions.
    assert totals == [2148, 2103, 2003, 158, 131, 216, 43], totals


def test_the_measurement_says_which_way_each_disagreement_falls():
    """early vs late is the diagnosis, and it must be in the report."""
    path = os.path.join(CORPUS, "moel-pyojun-geunrogyeyakseo-2025.hwpx")
    _need(path)
    conditional = own_render.lineseg_agreement(
        path, dpi=144)["conditional_breaks"]
    assert conditional["decisions"] == 47
    assert (conditional["exact"] + conditional["early"]
            + conditional["late"]) == conditional["decisions"]
    # The residual is an advance-width gap, not a rule gap: this renderer
    # measures the authoring engine's own line as well under its box, so it
    # keeps fitting the next word.  That is what `late` dominating and a
    # cached-line fill below 1.0 mean, together.
    assert conditional["late"] > conditional["early"]
    assert conditional["cached_line_fill"]["median"] < 1.0


# ------------------------------------------- the cache goes stale (E2.1/E2.5)

def test_no_unedited_corpus_paragraph_is_judged_stale(tmp_path):
    """Soundness of the staleness detector, on all ten forms.

    The detector must never fire on a document nobody edited, or every render
    would silently switch to a line breaker that measurably disagrees with the
    authoring engine.  This is the test that makes ``auto`` safe.
    """
    for name in sorted(LINESEG_AGREEMENT):
        path = os.path.join(CORPUS, name + ".hwpx")
        _need(path)
        result = own_render.render_to_dir(path, tmp_path / name, dpi=96)
        layout = result["report"]["line_layout"]
        assert layout["policy"] == "auto"
        assert layout["computed_reasons"].get("stale_line_width", 0) == 0, (
            f"{name}: {layout['computed_reasons']}")
        assert layout["computed_reasons"].get("caller_marked_edited", 0) == 0


def _edited_copy(source, target, paragraph_index, suffix):
    """A corpus form with one paragraph's text lengthened.  E1's edit, offline.

    Rewrites ``Contents/section0.xml`` through ElementTree, which is exactly
    what the byte-preserving lanes must never do — but this is a test fixture
    for the renderer, not an edit of a submission, and the renderer reads by
    local name so the prefix rewrite is invisible to it.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        payload = {name: archive.read(name) for name in names}
    root = ET.fromstring(payload["Contents/section0.xml"])
    seen = 0
    for element in root.iter():
        if own_render._local(element.tag) != "p":
            continue
        if seen == paragraph_index:
            last = None
            for run in element:
                if own_render._local(run.tag) != "run":
                    continue
                for node in run:
                    if (own_render._local(node.tag) == "t"
                            and (node.text or "").strip()):
                        last = node
            assert last is not None, "fixture drifted: paragraph has no text"
            last.text = (last.text or "") + suffix
        seen += 1
    payload["Contents/section0.xml"] = ET.tostring(root, encoding="utf-8")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, payload[name])
    return target


EDIT_FORM = os.path.join(CORPUS, "moel-pyojun-geunrogyeyakseo-2025.hwpx")
EDIT_PARAGRAPH = 2
EDIT_TEXT = ("추가로 입력한 문장을 여기에 길게 붙여넣어서 이 문단이 캐시된 "
             "줄 상자보다 훨씬 길어지게 만든다.")


@pytest.fixture(scope="module")
def edited_render(tmp_path_factory):
    out = tmp_path_factory.mktemp("edited")
    edited = _edited_copy(_need(EDIT_FORM), out / "edited.hwpx",
                          EDIT_PARAGRAPH, EDIT_TEXT)
    return own_render.render_to_dir(edited, out / "render", dpi=96)


def test_an_edited_paragraph_is_never_drawn_from_a_stale_box(edited_render):
    """The rule this slice exists for: a stale cached box is never drawn.

    The text of one paragraph is lengthened past what its cached line boxes
    can hold.  The renderer must notice from the file alone, relay that
    paragraph out itself, and say so — and it must leave every other
    paragraph on the authoring engine's own boxes.
    """
    report = edited_render["report"]
    layout = report["line_layout"]
    assert layout["paragraphs"]["computed"] == 1, layout["paragraphs"]
    assert layout["computed_reasons"] == {"stale_line_width": 1}
    relaid = layout["paragraphs_relaid_out"]
    assert len(relaid) == 1
    record = relaid[0]
    assert record["paragraph"] == EDIT_PARAGRAPH
    assert record["mode"] == "computed"
    assert record["reason"] == "stale_line_width"
    assert record["cached_lines"] == 2
    assert record["computed_lines"] > record["cached_lines"], (
        "a longer paragraph must take more lines")
    assert record["height_delta_hwpunit"] > 0


def test_every_line_box_says_which_engine_broke_it(edited_render):
    report = edited_render["report"]
    modes = {}
    for box in report["line_boxes"]:
        modes[box["mode"]] = modes.get(box["mode"], 0) + 1
    assert set(modes) == {"lineseg", "computed"}
    assert modes["computed"] == (
        report["line_layout"]["paragraphs_relaid_out"][0]["computed_lines"])
    assert modes["lineseg"] > 0


def test_a_relaid_out_paragraph_stays_inside_its_column(edited_render):
    """No computed line may run out of the text column it was broken for."""
    report = edited_render["report"]
    geo = report["page_geometry_hwpunit"]
    dpi = report["dpi"]
    left = geo["body_left"] * dpi / own_render.HWPUNIT_PER_INCH
    right = ((geo["body_left"] + geo["usable_width"]) * dpi
             / own_render.HWPUNIT_PER_INCH)
    computed = [b for b in report["line_boxes"] if b["mode"] == "computed"]
    assert computed
    for box in computed:
        assert box["x0"] >= left - 1.0, box
        # One pixel of tolerance, and no more: a space that lands at a line
        # end hangs outside the box rather than forcing a break, so the drawn
        # advance can exceed the fitted width by that space.
        assert box["x1"] <= right + 1.0, box


def test_the_caller_can_declare_an_edit_the_file_cannot_show(tmp_path):
    """The detector is sound but incomplete, so the editor gets a channel.

    An edit that leaves every line still fitting is invisible in the file.
    ``relayout_paragraphs`` is how E1's apply path says "I changed this one",
    and the sidecar has to repeat the claim rather than absorb it.
    """
    # Paragraph numbering is document order over every hp:p in section0, which
    # the caller can compute from the same file; an empty paragraph never
    # reaches the decision at all, so pick the first one that carries text.
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=96)
    chosen = next(
        renderer.paragraph_index[id(el)]
        for el in renderer.sections[0].iter()
        if own_render._local(el.tag) == "p"
        and own_render.Paragraph(el, renderer.defs["para_pr"]).chars)

    result = own_render.render_to_dir(
        _need(GIANMUN), tmp_path / "marked", dpi=96,
        relayout_paragraphs={chosen})
    layout = result["report"]["line_layout"]
    assert layout["caller_marked_edited"] == [chosen]
    assert layout["computed_reasons"] == {"caller_marked_edited": 1}
    assert layout["paragraphs"]["computed"] == 1
    assert [r["paragraph"]
            for r in layout["paragraphs_relaid_out"]] == [chosen]


def test_computed_policy_relays_out_every_paragraph(tmp_path):
    default = own_render.render_to_dir(_need(GIANMUN), tmp_path / "auto",
                                       dpi=96)
    forced = own_render.render_to_dir(
        _need(GIANMUN), tmp_path / "computed", dpi=96,
        line_layout=own_render.LINE_LAYOUT_COMPUTED)
    assert default["report"]["line_layout"]["paragraphs"]["computed"] == 0
    assert forced["report"]["line_layout"]["paragraphs"]["lineseg"] == 0
    assert forced["report"]["line_layout"]["paragraphs"]["computed"] > 0
    assert forced["report"]["line_layout"]["computed_reasons"] == {
        "policy": forced["report"]["line_layout"]["paragraphs"]["computed"]}
    assert all(box["mode"] == "computed"
               for box in forced["report"]["line_boxes"])


def test_the_sidecar_declares_what_the_breaker_honours_and_what_it_does_not(
        gianmun_render):
    layout = gianmun_render["report"]["line_layout"]
    honored = " ".join(layout["parapr_honored"])
    not_honored = " ".join(layout["parapr_not_honored"])
    for attribute in ("breakLatinWord", "breakNonLatinWord", "lineWrap",
                      "condense", "lineSpacing", "intent"):
        assert attribute in honored, attribute
    for attribute in ("HYPHENATION", "widowOrphan", "keepWithNext",
                      "fontLineHeight", "snapToGrid"):
        assert attribute in not_honored, attribute
    assert layout["prohibition_table"]["line_start_forbidden"]
    assert layout["prohibition_table"]["line_end_forbidden"]
    assert "not the spec" in layout["prohibition_table"]["note"]
    assert "0.85" in layout["line_geometry_model"]["baseline"]


def test_the_break_settings_the_corpus_actually_declares():
    """Pin what the corpus can and cannot tell us about these attributes.

    The same discipline the language-slot model is held to: a mechanism the
    corpus never exercises is pinned by unit test, not by a document, and the
    count of what it does exercise is itself pinned so the claim stays
    falsifiable.
    """
    import zipfile
    from xml.etree import ElementTree as ET
    from collections import Counter

    census = {"breakLatinWord": Counter(), "breakNonLatinWord": Counter(),
              "lineWrap": Counter(), "condense": Counter()}
    for name in sorted(LINESEG_AGREEMENT):
        path = os.path.join(CORPUS, name + ".hwpx")
        _need(path)
        with zipfile.ZipFile(path) as archive:
            header = next(n for n in archive.namelist()
                          if n.endswith("header.xml"))
            root = ET.fromstring(archive.read(header))
        for element in root.iter():
            if own_render._local(element.tag) != "paraPr":
                continue
            census["condense"][element.get("condense")] += 1
            brk = own_render._kid(element, "breakSetting")
            if brk is None:
                continue
            for key in ("breakLatinWord", "breakNonLatinWord", "lineWrap"):
                census[key][brk.get(key)] += 1
    assert dict(census["breakLatinWord"]) == {
        "KEEP_WORD": 669, "BREAK_WORD": 104, "HYPHENATION": 1}
    assert dict(census["breakNonLatinWord"]) == {
        "KEEP_WORD": 592, "BREAK_WORD": 182}
    # lineWrap has exactly one value in the corpus, so BREAK is the only
    # branch a document has ever driven here.
    assert dict(census["lineWrap"]) == {"BREAK": 774}
    assert dict(census["condense"]) == {
        "0": 603, "25": 130, "20": 37, "30": 4}


def test_the_cached_line_geometry_relations_hold_across_the_corpus():
    """The four relations the vertical model is built on, re-measured.

    They are not quoted from KS X 6101 — the standard does not publish them —
    so the model is only as good as this measurement, and the measurement is
    a test rather than a comment.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    segments = 0
    vertsize_is_textheight = 0
    baseline_exact = 0
    baseline_within_one = 0
    chained = 0
    chain_exact = 0
    for name in sorted(LINESEG_AGREEMENT):
        path = os.path.join(CORPUS, name + ".hwpx")
        _need(path)
        with zipfile.ZipFile(path) as archive:
            for entry in sorted(n for n in archive.namelist()
                                if own_render.SECTION_RE.match(n)):
                root = ET.fromstring(archive.read(entry))
                for array in root.iter():
                    if own_render._local(array.tag) != "linesegarray":
                        continue
                    segs = own_render._kids(array, "lineseg")
                    previous = None
                    for seg in segs:
                        segments += 1
                        height = own_render._iattr(seg, "textheight")
                        size = own_render._iattr(seg, "vertsize")
                        base = own_render._iattr(seg, "baseline")
                        top = own_render._iattr(seg, "vertpos")
                        if size == height:
                            vertsize_is_textheight += 1
                        want = height * own_render.BASELINE_RATIO
                        if base == round(want):
                            baseline_exact += 1
                        if abs(base - want) <= 1:
                            baseline_within_one += 1
                        if previous is not None:
                            chained += 1
                            if top == previous:
                                chain_exact += 1
                        previous = (top + size
                                    + own_render._iattr(seg, "spacing"))
    assert segments == 3214
    assert vertsize_is_textheight == 3214
    assert baseline_exact == 3212
    assert baseline_within_one == 3214
    assert chained == 219
    assert chain_exact == 219


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


def test_the_computed_breaker_is_deterministic_too(tmp_path):
    """The mode the editor will actually run in has to be reproducible."""
    first = own_render.render_to_dir(
        _need(GIANMUN), tmp_path / "c1", dpi=144,
        line_layout=own_render.LINE_LAYOUT_COMPUTED)
    second = own_render.render_to_dir(
        _need(GIANMUN), tmp_path / "c2", dpi=144,
        line_layout=own_render.LINE_LAYOUT_COMPUTED)
    for left, right in zip(first["pngs"], second["pngs"]):
        with open(left, "rb") as fh:
            a = fh.read()
        with open(right, "rb") as fh:
            b = fh.read()
        assert a == b, "the computed line breaker is not deterministic"
    assert (first["report"]["line_boxes"]
            == second["report"]["line_boxes"])


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
    # Row heights are now measured from the layout each paragraph will
    # actually get, so track solving needs a drawing context to measure with.
    canvas = renderer.Image.new("RGB", (8, 8), (255, 255, 255))
    renderer._image = canvas
    xs, ys, cells = renderer._table_tracks(
        renderer.ImageDraw.Draw(canvas), table)
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
