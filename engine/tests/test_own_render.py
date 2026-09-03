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

import io
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
    """Whatever this tier cannot draw must be named, with a reason and a count.

    The element this probe used to hang on — ``hp:pic`` — is now drawn from
    ``BinData``, so the contract is checked on whatever the form still cannot
    render rather than on one named tag: every entry carries a non-empty
    reason and a positive count, and nothing is dropped silently.
    """
    result = own_render.render_to_dir(_need(PICTURE_FORM), tmp_path, dpi=144)
    report = result["report"]
    assert report["elements_skipped"], "a form with unhandled elements said nothing"
    for entry in report["elements_skipped"]:
        assert entry["reason"], entry
        assert entry["count"] >= 1


def test_embedded_pictures_are_drawn_from_bindata(tmp_path):
    """``hp:pic`` draws its embedded raster, not a placeholder box.

    The corpus form carries pictures whose bytes are in ``BinData/``; the
    manifest in ``Contents/content.hpf`` is what maps ``binaryItemIDRef`` to
    the container entry.  Drawing them has to count as an image and drop
    ``hp:pic`` out of ``elements_skipped``.
    """
    result = own_render.render_to_dir(_need(PICTURE_FORM), tmp_path, dpi=144)
    report = result["report"]
    skipped = {entry["element"] for entry in report["elements_skipped"]}
    assert "hp:pic" not in skipped, skipped
    assert report["elements_rendered"]["images"] >= 1


def test_binary_items_reads_the_opf_manifest(tmp_path):
    """The id a picture cites is resolved through the manifest, not guessed.

    The href in ``content.hpf`` and the id differ in case and extension often
    enough that a stem guess is not sound; the stem fallback exists only for a
    container that ships no manifest at all.
    """
    import zipfile as _zip

    path = tmp_path / "manifest.hwpx"
    with _zip.ZipFile(path, "w") as z:
        z.writestr(
            "Contents/content.hpf",
            '<opf:package xmlns:opf="urn:x"><opf:manifest>'
            '<opf:item id="image1" href="BinData/PICTURE1.BMP"/>'
            "</opf:manifest></opf:package>")
        z.writestr("BinData/PICTURE1.BMP", b"\x00")
        z.writestr("BinData/loose9.png", b"\x00")
    with _zip.ZipFile(path) as z:
        items = own_render.binary_items(z, z.namelist())
    assert items["image1"] == "BinData/PICTURE1.BMP"
    assert items["loose9"] == "BinData/loose9.png"


def test_an_undecodable_picture_falls_back_to_the_placeholder():
    """Vector art (EMF/WMF) and corrupt bytes get a box and a named reason.

    HWP embeds EMF as readily as PNG, and this tier does not rasterise vector
    art.  The contract is that such a picture is still visible as a box and
    still declared — never a silent hole.
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    renderer.bin_items = {"image9": "BinData/image9.emf"}
    renderer._bin_cache = {"image9": b"\x01\x00\x09\x00not-a-raster"}
    renderer._image = renderer.Image.new("RGB", (400, 200), (255, 255, 255))
    draw = renderer.ImageDraw.Draw(renderer._image)
    pic = ET.fromstring(
        '<hp:pic xmlns:hp="urn:x" xmlns:hc="urn:y">'
        '<hc:img binaryItemIDRef="image9"/>'
        '<hp:sz width="7200" height="3600"/></hp:pic>')
    renderer._render_placeholder(draw, pic, "pic", (0, 0))
    assert renderer.counts["images"] == 0
    assert renderer.counts["placeholders"] == 1
    reasons = [e["reason"] for e in renderer.skipped.values()
               if e["element"] == "hp:pic"]
    assert any("Pillow cannot" in r for r in reasons), reasons


def test_a_clipped_picture_crops_by_the_declared_fraction(tmp_path):
    """``hp:imgClip`` is a crop against ``hp:imgDim``, not against pixels.

    A half-width clip on a two-colour source must leave only the kept half's
    colour in the box, whatever the embedded file's own resolution is.
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    source = renderer.Image.new("RGB", (40, 10), (255, 0, 0))
    source.paste((0, 0, 255), (20, 0, 40, 10))
    buf = io.BytesIO()
    source.save(buf, format="PNG")
    renderer.bin_items = {"i": "BinData/i.png"}
    renderer._bin_cache = {"i": buf.getvalue()}
    renderer._image = renderer.Image.new("RGB", (200, 100), (255, 255, 255))
    pic = ET.fromstring(
        '<hp:pic xmlns:hp="urn:x" xmlns:hc="urn:y">'
        '<hc:img binaryItemIDRef="i"/>'
        '<hp:imgDim dimwidth="4000" dimheight="1000"/>'
        '<hp:imgClip left="0" right="2000" top="0" bottom="1000"/>'
        '<hp:sz width="7200" height="3600"/></hp:pic>')
    assert renderer._render_picture(pic, (0, 0), 7200, 3600)
    assert renderer.counts["images"] == 1
    box_w, box_h = renderer.px(7200), renderer.px(3600)
    kept = renderer._image.crop((0, 0, box_w, box_h))
    colours = {c for _n, c in kept.getcolors(maxcolors=1 << 16)}
    assert all(c[0] > c[2] for c in colours), colours


def _pagenum_renderer(pos, side="-", fmt="DIGIT", start=1, hide_first=0):
    """A renderer whose section declares one ``hp:pageNum`` control.

    No corpus form uses 쪽 번호 매기기, so the control is injected the way the
    equation path is driven directly: the geometry under test is the page
    box's, which the corpus form supplies for real.
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    run = ET.fromstring(
        '<hp:run xmlns:hp="urn:x" charPrIDRef="0"><hp:ctrl>'
        f'<hp:pageNum pos="{pos}" formatType="{fmt}" sideChar="{side}"/>'
        "</hp:ctrl></hp:run>")
    section = renderer.sections[0]
    section.append(run)
    # The form already declares hp:startNum / hp:visibility; the renderer
    # reads the first of each, so the test has to edit those rather than
    # append rivals it would never see.
    for tag, attr, value in (("startNum", "page", start),
                             ("visibility", "hideFirstPageNum", hide_first)):
        el = next((e for e in section.iter() if e.tag.rsplit("}", 1)[-1] == tag),
                  None)
        if el is None:
            el = ET.SubElement(section, tag)
        el.set(attr, str(value))
    renderer._page_num_spec = own_render._UNSET
    return renderer


def test_a_page_number_is_stamped_on_every_page():
    """``hp:pageNum`` is a control, not a footer: every page gets a number."""
    renderer = _pagenum_renderer("BOTTOM_CENTER")
    _images, sidecar = renderer.render()
    assert sidecar["elements_rendered"]["page_numbers"] == sidecar["pages"]
    assert sidecar["pages"] >= 1


def test_a_bottom_page_number_sits_on_the_bottom_margin():
    """Measured placement, not a guess.

    Against a Hancom reference the number's line box has its BOTTOM EDGE on
    ``page height - bottom margin`` and is centred in the body box.  Both are
    asserted here in the renderer's own pixel units, so a change to either
    rule is caught.
    """
    renderer = _pagenum_renderer("BOTTOM_CENTER")
    _images, sidecar = renderer.render()
    geo = renderer.page_geometry()
    boxes = [b for b in sidecar["line_boxes"] if b["mode"] == "pagenum"]
    assert boxes
    bottom = renderer.px(geo["height"] - geo["margin"]["bottom"])
    left = renderer.px(geo["margin"]["left"])
    right = renderer.px(geo["width"] - geo["margin"]["right"])
    for box in boxes:
        assert abs(box["y1"] - bottom) <= 1, box
        centre = (box["x0"] + box["x1"]) / 2.0
        assert abs(centre - (left + right) / 2.0) <= 1, box


def test_page_number_alignment_follows_pos():
    """LEFT and RIGHT anchor on the body box's own edges."""
    left_boxes = [b for b in _pagenum_renderer("BOTTOM_LEFT").render()[1]
                  ["line_boxes"] if b["mode"] == "pagenum"]
    right_boxes = [b for b in _pagenum_renderer("BOTTOM_RIGHT").render()[1]
                   ["line_boxes"] if b["mode"] == "pagenum"]
    renderer = _pagenum_renderer("BOTTOM_LEFT")
    geo = renderer.page_geometry()
    assert abs(left_boxes[0]["x0"] - renderer.px(geo["margin"]["left"])) <= 1
    assert abs(right_boxes[0]["x1"]
               - renderer.px(geo["width"] - geo["margin"]["right"])) <= 1


def test_an_unmeasured_page_number_position_is_declared_not_guessed():
    """A TOP_* or INSIDE_* number has never been measured; draw nothing."""
    renderer = _pagenum_renderer("TOP_CENTER")
    _images, sidecar = renderer.render()
    assert sidecar["elements_rendered"]["page_numbers"] == 0
    skipped = {e["element"] for e in sidecar["elements_skipped"]}
    assert "hp:pageNum@pos=TOP_CENTER" in skipped, skipped


def test_hide_first_page_number_is_honoured():
    renderer = _pagenum_renderer("BOTTOM_CENTER", hide_first=1)
    _images, sidecar = renderer.render()
    assert sidecar["elements_rendered"]["page_numbers"] == sidecar["pages"] - 1


def test_start_number_offsets_the_stamped_number():
    """``hp:startNum@page`` renumbers; the count of stamps does not change."""
    renderer = _pagenum_renderer("BOTTOM_CENTER", start=7)
    assert renderer.page_number_spec()["first_number"] == 7


# ------------------------------------------------- headers and footers (E2.6)
#
# No corpus form carries an hp:footer, and the one that carries an hp:header
# (jeongbo) carries an EMPTY one, so nothing here can be measured against a
# Hancom reference render.  The fixtures below are synthetic, and what they
# pin is geometry the format publishes: the areas hh:margin@header/@footer
# declare, @applyPageType, and @hideFirstHeader/@hideFirstFooter.

MULTIPAGE = os.path.join(CORPUS, "saeopja-deungnok-sinchengseo.hwpx")


def _furniture_xml(kind, text, apply_type="BOTH", char_height=1000):
    """One hp:header / hp:footer control, as HWP writes it: inside a run."""
    return (
        '<hp:run xmlns:hp="urn:x" charPrIDRef="0"><hp:ctrl>'
        f'<hp:{kind} id="1" applyPageType="{apply_type}"><hp:subList>'
        '<hp:p id="1" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>'
        '<hp:linesegarray>'
        f'<hp:lineseg textpos="0" vertpos="0" vertsize="{char_height}" '
        f'textheight="{char_height}" baseline="{int(char_height * 0.85)}" '
        'spacing="0" horzpos="0" horzsize="40000" flags="0"/>'
        '</hp:linesegarray></hp:p></hp:subList>'
        f'</hp:{kind}></hp:ctrl></hp:run>')


def _furniture_renderer(source=None, header=None, footer=None,
                        header_margin=2000, footer_margin=2000,
                        hide_first_header=0, hide_first_footer=0,
                        apply_type="BOTH"):
    """A corpus form with a header and/or footer control grafted onto it.

    The control goes into the first TOP-LEVEL paragraph, which is where HWP
    puts it and where ``_furniture_scan`` looks; the margins are edited on the
    form's own ``hh:margin`` so the header/footer areas have a real height
    (every corpus form declares header="0" footer="0").
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(source or GIANMUN), dpi=144)
    section = renderer.sections[0]
    margin = next(e for e in section.iter()
                  if own_render._local(e.tag) == "margin"
                  and e.get("header") is not None)
    margin.set("header", str(header_margin))
    margin.set("footer", str(footer_margin))
    vis = next(e for e in section.iter()
               if own_render._local(e.tag) == "visibility")
    vis.set("hideFirstHeader", str(hide_first_header))
    vis.set("hideFirstFooter", str(hide_first_footer))
    host = own_render._kids(section, "p")[0]
    for kind, text in (("header", header), ("footer", footer)):
        if text is None:
            continue
        host.append(ET.fromstring(_furniture_xml(kind, text, apply_type)))
    renderer._furniture = None
    renderer.paragraph_index = {
        id(el): index
        for index, el in enumerate(
            e for e in section.iter() if own_render._local(e.tag) == "p")
    }
    return renderer


def test_the_corpus_carries_exactly_one_header_and_no_footer_or_note():
    """The measurement this whole slice rests on, asserted rather than told.

    If a form with a real header, footer or note is ever added, this test is
    what says so — and the claim "no reference render exercises this lane"
    has to be rewritten rather than quietly left standing.
    """
    import glob
    import zipfile

    found = {"header": [], "footer": [], "footNote": [], "endNote": []}
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.hwpx"))):
        stem = os.path.basename(path)[:-5]
        renderer = own_render.OwnRenderer(path, dpi=96)
        scan = renderer._furniture_scan()
        for tag, key in (("header", "header"), ("footer", "footer"),
                         ("footNote", "footnote"), ("endNote", "endnote")):
            if scan[key]:
                found[tag].append((stem, len(scan[key])))
        with zipfile.ZipFile(path) as archive:
            assert any(n.endswith("section0.xml") for n in archive.namelist())
    assert found["header"] == [("jeongbo-gonggae-cheongguseo", 1)], found
    assert found["footer"] == [], found
    assert found["footNote"] == [], found
    assert found["endNote"] == [], found
    # And that one header is empty: drawing it adds no ink, which is why the
    # corpus renders stay byte-identical across this slice.
    renderer = own_render.OwnRenderer(_need(PICTURE_FORM), dpi=96)
    entry = renderer._furniture_scan()["header"][0]
    paras = renderer._sublist_paragraphs(entry["el"])
    assert paras and not any(p.chars for p in paras)


def _extreme_box(sidecar, top):
    boxes = [b for b in sidecar["line_boxes"] if b["page"] == 1]
    return min(boxes, key=lambda b: b["y0"]) if top else max(
        boxes, key=lambda b: b["y1"])


def test_a_header_and_a_footer_land_in_the_areas_the_margins_declare():
    """The two areas, pinned against each other so no font metric leaks in.

    ``line_boxes`` are *ink* boxes -- the font ascent about the cached
    baseline -- so asserting one against a margin would really be asserting
    the fallback face's ascent.  The same text drawn in both areas has the
    same ink box shape, so the DIFFERENCE between the two is pure geometry,
    and that difference is exactly what ``hh:margin`` declares:
    ``(height - bottom - footer) - top``.
    """
    text = "\ubc38\ub9ac\ub9d0"
    head = _furniture_renderer(header=text)
    _images, head_side = head.render()
    foot = _furniture_renderer(footer=text)
    _images, foot_side = foot.render()
    geo = head.page_geometry()
    m = geo["margin"]
    head_box = _extreme_box(head_side, top=True)
    foot_box = _extreme_box(foot_side, top=False)
    expected = (head.px(geo["height"] - m["bottom"] - m["footer"])
                - head.px(m["top"]))
    assert abs((foot_box["y0"] - head_box["y0"]) - expected) <= 1, (
        head_box, foot_box, expected)
    # And each stays on its own side of the body box.
    assert head_box["y1"] <= head.px(geo["body_top"]), head_box
    assert foot_box["y0"] >= head.px(geo["body_top"]), foot_box
    assert head_side["elements_rendered"]["headers"] == head_side["pages"]
    assert foot_side["elements_rendered"]["footers"] == foot_side["pages"]
    assert head_side["page_furniture"]["areas_hwpunit"]["header"] == [
        m["top"], m["top"] + m["header"]]
    assert foot_side["page_furniture"]["areas_hwpunit"]["footer"] == [
        geo["height"] - m["bottom"] - m["footer"],
        geo["height"] - m["bottom"]]


def test_the_header_area_moves_with_the_declared_header_margin():
    """A header is set from the TOP of its area, so growing ``@header``
    leaves the header where it is and pushes the BODY down."""
    small = _furniture_renderer(header="H", header_margin=2000)
    _images, small_side = small.render()
    big = _furniture_renderer(header="H", header_margin=6000)
    _images, big_side = big.render()
    assert (_extreme_box(small_side, top=True)["y0"]
            == _extreme_box(big_side, top=True)["y0"])
    assert (big.page_geometry()["body_top"]
            - small.page_geometry()["body_top"]) == 4000


def test_a_header_and_the_page_number_stamp_coexist():
    """쪽 번호 is a control and the header is a container; both draw."""
    renderer = _furniture_renderer(header="머리말", footer="꼬리말")
    from xml.etree import ElementTree as ET
    own_render._kids(renderer.sections[0], "p")[0].append(ET.fromstring(
        '<hp:run xmlns:hp="urn:x" charPrIDRef="0"><hp:ctrl>'
        '<hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar=""/>'
        "</hp:ctrl></hp:run>"))
    renderer._page_num_spec = own_render._UNSET
    _images, sidecar = renderer.render()
    drawn = sidecar["elements_rendered"]
    assert drawn["headers"] == drawn["footers"] == sidecar["pages"]
    assert drawn["page_numbers"] == sidecar["pages"]
    assert any(b["mode"] == "pagenum" for b in sidecar["line_boxes"])


def test_apply_page_type_selects_odd_and_even_pages():
    odd = _furniture_renderer(source=MULTIPAGE, header="홀", apply_type="ODD")
    _images, sidecar = odd.render()
    pages = sidecar["pages"]
    assert pages > 1, "fixture drifted: need a multi-page form"
    assert sidecar["elements_rendered"]["headers"] == len(
        [n for n in range(1, pages + 1) if n % 2 == 1])
    even = _furniture_renderer(source=MULTIPAGE, header="짝", apply_type="EVEN")
    _images, sidecar = even.render()
    assert sidecar["elements_rendered"]["headers"] == len(
        [n for n in range(1, pages + 1) if n % 2 == 0])


def test_an_unknown_apply_page_type_is_declared_not_guessed():
    renderer = _furniture_renderer(header="?", apply_type="MASTER_ODD")
    _images, sidecar = renderer.render()
    assert sidecar["elements_rendered"]["headers"] == 0
    assert "hp:header@applyPageType=MASTER_ODD" in {
        e["element"] for e in sidecar["elements_skipped"]}


def test_hide_first_header_and_footer_are_honoured():
    renderer = _furniture_renderer(source=MULTIPAGE, header="h", footer="f",
                                   hide_first_header=1, hide_first_footer=1)
    _images, sidecar = renderer.render()
    assert sidecar["elements_rendered"]["headers"] == sidecar["pages"] - 1
    assert sidecar["elements_rendered"]["footers"] == sidecar["pages"] - 1


def test_a_header_taller_than_its_area_is_named_not_clipped():
    renderer = _furniture_renderer(header="머리말", header_margin=100)
    _images, sidecar = renderer.render()
    skipped = {e["element"] for e in sidecar["elements_skipped"]}
    assert "hp:header taller than hh:margin@header" in skipped, skipped
    assert sidecar["elements_rendered"]["headers"] == sidecar["pages"]


def test_the_furniture_lane_declares_that_no_reference_render_measures_it():
    renderer = _furniture_renderer(header="머리말")
    _images, sidecar = renderer.render()
    evidence = sidecar["page_furniture"]["evidence"]
    assert "NOT measured against any Hancom reference render" in evidence
    assert any("NO Hancom reference render" in n for n in sidecar["notes"])


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


# ------------------------------------- the space is a half-width cell (E2.2)

RENDER_REFS = os.path.join(ROOT, "tests", "corpus", "forms", "render")


def _reference_pdfs():
    """Every Hancom reference render, or a skip naming what is missing."""
    try:
        import fitz  # noqa: F401
    except ImportError:
        pytest.skip("PyMuPDF is not installed; the reference PDFs cannot be "
                    "read, so the per-class advance measurement cannot run")
    if not os.path.isdir(RENDER_REFS):
        pytest.skip(f"reference renders missing: {RENDER_REFS}")
    paths = sorted(os.path.join(RENDER_REFS, n)
                   for n in os.listdir(RENDER_REFS) if n.endswith(".pdf"))
    if not paths:
        pytest.skip(f"no reference PDF under {RENDER_REFS}")
    return paths


def _unstretched_span_advances(paths):
    """``{(face, char): [advance/em, ...]}`` from the reference PDFs.

    Only spans whose every Hangul cell measures exactly 1.000 em are sampled,
    which is what makes the numbers comparable to a bare font advance: on such
    a span no ``hh:ratio``, no 공백 축소 and no justification stretch is acting.
    The advance of a glyph is the distance to the NEXT glyph's origin, so the
    last glyph of a span is never sampled.
    """
    import fitz
    import collections
    out = collections.defaultdict(list)
    for path in paths:
        with fitz.open(path) as doc:
            for page in doc:
                for block in page.get_text("rawdict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block["lines"]:
                        if abs(line["dir"][0] - 1.0) > 1e-6:
                            continue      # not a horizontal run
                        for span in line["spans"]:
                            face, size = span["font"], span["size"]
                            if size <= 0:
                                continue
                            glyphs = span["chars"]
                            pairs, hangul = [], []
                            for i in range(len(glyphs) - 1):
                                a, b = glyphs[i], glyphs[i + 1]
                                adv = (b["origin"][0] - a["origin"][0]) / size
                                if adv <= 0:
                                    continue
                                pairs.append((a["c"], adv))
                                if 0xAC00 <= ord(a["c"]) <= 0xD7A3:
                                    hangul.append(adv)
                            if not hangul:
                                continue
                            if any(abs(h - 1.0) >= 0.004 for h in hangul):
                                continue
                            for ch, adv in pairs:
                                out[(face, ch)].append(adv)
    return out


def _glyph_class(ch):
    code = ord(ch)
    if ch in own_render.HALF_WIDTH_CELL_CHARS:
        return "space"
    if 0xAC00 <= code <= 0xD7A3:
        return "hangul"
    if 48 <= code <= 57:
        return "digit"
    if (65 <= code <= 90) or (97 <= code <= 122):
        return "latin"
    if code < 128:
        return "ascii-punct"
    return "other"


def test_a_space_advances_by_half_the_character_cell(typo_probe):
    """The rule itself, in the renderer's own units.

    A space is half the declared character size — not the advance the face's
    ``hmtx`` gives U+0020, and not half of some measured glyph.  Stated
    against the full-width cell the same charPr gives a Hangul syllable, so
    the test says *half of what* rather than repeating a constant.
    """
    renderer, _image, draw = typo_probe
    cid = _synthetic_charpr(renderer, "__cell__", height=1000)
    em = 10.0 * 144 / 72.0
    full = renderer._measure(draw, "가", cid)
    space = renderer._measure(draw, " ", cid)
    assert full == pytest.approx(em, rel=1e-3), "fixture: 가 is not a full cell"
    assert space == pytest.approx(em / 2.0, rel=1e-9)
    # ...and it does not depend on the face, which is the whole claim.
    assert space == pytest.approx(
        renderer._half_cell_px(cid, 100, 100), rel=1e-9)


def test_the_space_cell_scales_with_ratio_like_a_full_cell(typo_probe):
    """``hh:ratio`` scales the half cell exactly as it scales the full one."""
    renderer, _image, draw = typo_probe
    plain = _synthetic_charpr(renderer, "__c100__", height=1000)
    narrow = _synthetic_charpr(renderer, "__c70__", height=1000, ratio=70)
    assert (renderer._measure(draw, " ", narrow)
            == pytest.approx(0.7 * renderer._measure(draw, " ", plain),
                             rel=1e-9))


def test_the_reference_pdfs_advance_a_space_by_half_the_character_cell():
    """Where ``SPACE_CELL_FRACTION`` comes from: Hancom's own renders.

    Black box: the ten reference PDFs are read for the advances they actually
    drew.  Five of the faces the corpus uses have ``hmtx`` space advances
    between 0.333 and 0.352 em and one (the monospaced DotumChe) has 0.5; all
    six render a space at 0.50 em, so 0.5 is a property of HWP's cell model
    rather than of any face.
    """
    samples = _unstretched_span_advances(_reference_pdfs())
    spaces = [v for (_face, ch), vals in samples.items()
              if ch in own_render.HALF_WIDTH_CELL_CHARS for v in vals]
    assert len(spaces) >= 1000, len(spaces)
    inside = sum(1 for v in spaces if 0.49 <= v <= 0.51)
    assert inside / len(spaces) > 0.9, (
        f"{inside} of {len(spaces)} space advances within 0.01 em of 0.50")
    spaces.sort()
    assert spaces[len(spaces) // 2] == pytest.approx(
        own_render.SPACE_CELL_FRACTION, abs=0.01)


def test_no_glyph_class_is_measured_more_than_a_hundredth_of_an_em_out():
    """The per-class advance error against the reference PDFs, as a gate.

    For every (face, character) the reference PDFs drew, this renderer's
    advance is compared to the PDF's median advance for that same glyph on
    that same face, and the signed errors are aggregated by class.  Before the
    half-width space cell the ``space`` row was -0.1373 em and every other row
    was already inside 0.007; the bound below is therefore a regression gate
    on the space rule, not a fresh fit.

    Faces the machine does not have installed are skipped, not substituted —
    a substitute's advances would measure the substitution, not the renderer.
    """
    samples = _unstretched_span_advances(_reference_pdfs())
    index = own_render.SystemFontIndex.shared()
    Image, ImageDraw, ImageFont = own_render._require_pillow()
    draw = ImageDraw.Draw(Image.new("L", (8, 8)))
    unit, fonts = 2048, {}

    def face(family):
        if family not in fonts:
            entry = index.lookup(family)
            if entry is None:
                fonts[family] = None
            else:
                path, sub = entry["regular"] or entry["bold"]
                kwargs = {"index": sub} if sub else {}
                kwargs["layout_engine"] = ImageFont.Layout.BASIC
                fonts[family] = ImageFont.truetype(path, unit, **kwargs)
        return fonts[family]

    totals = {}
    for (family, ch), vals in samples.items():
        if ch in own_render.HALF_WIDTH_CELL_CHARS:
            ours = own_render.SPACE_CELL_FRACTION
        else:
            font = face(family)
            if font is None:
                continue
            ours = draw.textlength(ch, font=font) / unit
        vals = sorted(vals)
        reference = vals[len(vals) // 2]
        bucket = totals.setdefault(_glyph_class(ch), [0.0, 0])
        bucket[0] += (ours - reference) * len(vals)
        bucket[1] += len(vals)
    if not totals:
        pytest.skip("no reference face is installed on this machine")
    assert totals["space"][1] >= 1000, totals["space"]
    worst = {c: t[0] / t[1] for c, t in totals.items()}
    assert all(abs(e) <= 0.01 for e in worst.values()), worst


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
    "jeongbo-gonggae-cheongguseo": (58, 58, 53, 6, 6, 7, 2),
    "jumin-deungchobon-sinchengseo": (133, 133, 117, 27, 27, 36, 14),
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo": (453, 434, 415, 29, 26, 44, 13),
    "moel-pyojun-geunrogyeyakseo-2013": (263, 242, 222, 34, 26, 49, 10),
    "moel-pyojun-geunrogyeyakseo-2025": (314, 296, 271, 37, 27, 47, 7),
    "nrf-gyeolgwa-bogoseo-yangsik": (89, 89, 87, 3, 3, 3, 1),
    "saeopja-deungnok-sinchengseo": (764, 758, 749, 17, 14, 24, 9),
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
    # authoring engine's line COUNT on 2083 of them and its exact break
    # SEQUENCE on 1985.  Restricted to the 158 paragraphs that actually break
    # (the rest cannot disagree), it reproduces the line count on 133 and 58
    # of the 216 individual break positions.
    #
    # The break-position column moved 43 -> 58 when the space stopped being
    # measured from the resolved face's hmtx and became the half-width cell
    # the reference PDFs show it to be (``SPACE_CELL_FRACTION``).  The two
    # paragraph-level columns moved the other way, 2103 -> 2083 and
    # 2003 -> 1985, and that is not hidden here: widening every space pushes
    # a handful of paragraphs that the authoring engine kept on one line onto
    # two.  The break column is the one this measures — a paragraph that
    # cannot break cannot disagree — and the scoreboard against the Hancom
    # rasters moved with it (ssim +0.0035, ssim_inked +0.0087, line-box IoU
    # +0.0105, means over the corpus), which the paragraph columns cannot say.
    assert totals == [2148, 2083, 1985, 158, 133, 216, 58], totals


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


# ------------------------------------------------------------- block flow (E2.5)

REFLOW_FORM = os.path.join(CORPUS, "moel-pyojun-geunrogyeyakseo-2025.hwpx")
REFLOW_PARAGRAPH = 2
# Long enough that the edited paragraph alone outgrows the room left on its
# page: this is the edit the whole slice exists for, and a shorter one would
# only exercise the intra-paragraph relayout E2.1 already covers.
REFLOW_TEXT = ("추가로 입력한 문장을 여기에 아주 길게 붙여넣어서 이 문단이 "
               "캐시된 줄 상자보다 훨씬 길어지게 만든다. ") * 40


@pytest.fixture(scope="module")
def reflow_renders(tmp_path_factory):
    """The same form, before and after one paragraph is lengthened."""
    out = tmp_path_factory.mktemp("reflow")
    base = own_render.render_to_dir(_need(REFLOW_FORM), out / "base", dpi=96)
    edited_path = _edited_copy(_need(REFLOW_FORM), out / "edited.hwpx",
                               REFLOW_PARAGRAPH, REFLOW_TEXT)
    edited = own_render.render_to_dir(edited_path, out / "edited", dpi=96)
    return base, edited


def test_an_unedited_document_is_never_reflowed(reflow_renders):
    """The mode discipline, stated as a property of the sidecar.

    Nothing is relaid out, so nothing is re-placed: every block keeps the seat
    the authoring engine's cache gave it and every page says so.  This is what
    makes the byte-identity of an unedited render a consequence rather than a
    coincidence.
    """
    base, _edited = reflow_renders
    block = base["report"]["block_layout"]
    assert block["policy"] == own_render.BLOCK_LAYOUT_AUTO
    assert block["reflow_triggered"] is False
    assert block["pages_reflowed"] == 0
    assert block["blocks_placement"]["flowed"] == 0
    assert block["blocks_placement"]["cached"] == len(block["blocks"])
    assert set(block["page_reflowed"].values()) == {False}


def test_every_corpus_form_renders_unreflowed_and_declares_it():
    """No corpus form is stale, so no corpus form may reach the flow pass."""
    import glob

    for path in sorted(glob.glob(os.path.join(CORPUS, "*.hwpx"))):
        renderer = own_render.OwnRenderer(path, dpi=96)
        assert renderer.flow_plan() == (None, None), os.path.basename(path)


def test_an_edit_pushes_the_following_paragraph_onto_the_next_page(
        reflow_renders):
    """The rule E2.5 exists for: what grows moves everything after it."""
    base, edited = reflow_renders
    before = {b["block"]: b["page"]
              for b in base["report"]["block_layout"]["blocks"]}
    after = {}
    for b in edited["report"]["block_layout"]["blocks"]:
        after.setdefault(b["block"], b["page"])
    following = [n for n in sorted(before)
                 if n is not None and n > REFLOW_PARAGRAPH and n in after]
    assert following, "fixture drifted: nothing follows the edited paragraph"
    assert after[following[0]] > before[following[0]], (
        "the paragraph after the edited one did not move to a later page")
    # And nothing ABOVE the edit moved, which is the other half of the rule.
    for n in sorted(before):
        if n is None or n >= REFLOW_PARAGRAPH:
            continue
        assert after[n] == before[n], f"block {n} moved above the edit"


def test_the_page_count_grows_by_exactly_what_the_flow_computed(
        reflow_renders):
    base, edited = reflow_renders
    block = edited["report"]["block_layout"]
    assert block["reflow_triggered"] is True
    assert block["pages"] == len(edited["pngs"])
    assert block["pages"] > base["report"]["block_layout"]["pages"]
    assert block["pages"] == max(int(k) for k in block["page_reflowed"]) + 1
    assert len(edited["pngs"]) == edited["report"]["pages"]


def test_no_line_box_overflows_a_page_after_the_reflow(reflow_renders):
    """A relaid-out paragraph used to be drawn past the bottom of the body
    box; after the flow pass no drawn line may leave it."""
    _base, edited = reflow_renders
    report = edited["report"]
    geo = report["page_geometry_hwpunit"]
    dpi = report["dpi"]
    scale = dpi / own_render.HWPUNIT_PER_INCH
    top = geo["margin"]["top"] * scale
    bottom = ((geo["height"] - geo["margin"]["bottom"]
               - geo["margin"]["footer"]) * scale)
    for box in report["line_boxes"]:
        if box["mode"] == "pagenum":
            continue
        assert box["y0"] >= top - 1.0, box
        assert box["y1"] <= bottom + 1.0, box


def test_the_sidecar_declares_every_block_cached_or_flowed(reflow_renders):
    _base, edited = reflow_renders
    block = edited["report"]["block_layout"]
    assert block["first_flowed_block"] == REFLOW_PARAGRAPH
    assert {b["placement"] for b in block["blocks"]} <= {"cached", "flowed"}
    assert block["blocks_placement"]["flowed"] > 0
    assert block["blocks_placement"]["cached"] > 0
    assert (block["blocks_placement"]["cached"]
            + block["blocks_placement"]["flowed"]) == len(block["blocks"])
    assert block["pages_reflowed"] > 0
    assert block["flow_counters"] is not None
    for name in ("keep_lines_moved", "widow_orphan_moved",
                 "keep_with_next_moved", "tables_split",
                 "tables_moved_whole", "blocks_taller_than_page"):
        assert name in block["flow_counters"], name


def test_the_flow_pass_is_deterministic(tmp_path):
    edited = _edited_copy(_need(REFLOW_FORM), tmp_path / "edited.hwpx",
                          REFLOW_PARAGRAPH, REFLOW_TEXT)
    first = own_render.render_to_dir(edited, tmp_path / "r1", dpi=96)
    second = own_render.render_to_dir(edited, tmp_path / "r2", dpi=96)
    assert len(first["pngs"]) == len(second["pngs"])
    for left, right in zip(first["pngs"], second["pngs"]):
        with open(left, "rb") as fh:
            a = fh.read()
        with open(right, "rb") as fh:
            b = fh.read()
        assert a == b, "the flow pass is not deterministic"
    assert (first["report"]["block_layout"]["blocks"]
            == second["report"]["block_layout"]["blocks"])


def test_a_table_only_splits_across_a_page_when_it_says_it_may():
    """hp:tbl@pageBreak is the whole permission, and it is checked, not
    assumed: the corpus declares CELL on 62 tables and NONE on 19."""
    renderer = own_render.OwnRenderer(
        _need(os.path.join(CORPUS, "saeopja-deungnok-sinchengseo.hwpx")),
        dpi=96, block_layout=own_render.BLOCK_LAYOUT_COMPUTED)
    draw = renderer._scratch_draw()
    seen = {"CELL": 0, "other": 0}
    for element in renderer.sections[0].iter():
        if own_render._local(element.tag) != "tbl":
            continue
        splittable, ys = renderer._table_split_rows(draw, element)
        declared = (element.get("pageBreak") or "").upper()
        assert splittable == (declared == "CELL"), declared
        seen["CELL" if declared == "CELL" else "other"] += 1
        if not splittable:
            # Room for every row but the last, and it still refuses to split.
            assert renderer._split_table_row(draw, element, ys[-2]) is None
    assert seen["CELL"] and seen["other"], "fixture drifted"


def test_the_flow_pass_agrees_with_the_authoring_engine_on_the_corpus():
    """The honest measure of the flow pass, the way lineseg_agreement is the
    honest measure of the breaker.  A regression floor, not a fidelity bar:
    these are the numbers measured on 2026-09, and the point of pinning them
    is that a change that moves them has to say so."""
    floor = {
        "admrul-gajokdolbom-hyuga-sinchengseo": 15,
        "gianmun-byeolji-1ho": 3,
        "gianmun-byeolji-2ho": 3,
        "jeongbo-gonggae-cheongguseo": 1,
        "jumin-deungchobon-sinchengseo": 3,
        "moel-pyojun-geunrogyeyakseo-2013": 154,
        "moel-pyojun-geunrogyeyakseo-2025": 187,
        "nrf-gyeolgwa-bogoseo-yangsik": 51,
        "saeopja-deungnok-sinchengseo": 5,
    }
    for stem, expected in sorted(floor.items()):
        report = own_render.flow_agreement(
            _need(os.path.join(CORPUS, stem + ".hwpx")), dpi=144)
        hits, compared = report["page_assignment_agreement"]
        assert hits >= expected, (stem, hits, compared, expected)
        assert report["abs_dy_hwpunit"]["median"] == 0.0, (
            stem, report["abs_dy_hwpunit"])


def test_the_flow_pass_finds_the_two_pages_the_vertpos_heuristic_misses():
    """kstartup is the corpus form whose cached layout ``paginate`` reads
    wrong: it merges pages the authoring engine did break, because the
    paragraph after a full-page ANCHORED table does not restart at vertpos 0.
    Hancom's own reference render of this form is 22 pages; ``paginate``
    reads 20; the flow pass, from the geometry alone, computes 22."""
    report = own_render.flow_agreement(
        _need(os.path.join(
            CORPUS, "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx")),
        dpi=144)
    assert report["pages_cached"] == 20
    assert report["pages_computed"] == 22
    # And the disagreement is a clean offset, not scatter: the flow puts every
    # block at the cached vertical position, on a page two later.
    assert report["abs_dy_hwpunit"]["median"] == 0.0


def test_cli_reports_flow_agreement():
    proc = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "scripts", "own_render.py"),
         _need(GIANMUN), "--flow-agreement", "--dpi", "96"],
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["block_layout"] == own_render.BLOCK_LAYOUT_COMPUTED
    assert payload["page_assignment_agreement"][1] > 0


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


def _ink(image):
    return sum(image.convert("L").histogram()[:160])


def test_the_face_cache_is_keyed_by_what_the_lookup_asks_for():
    """A shadowed loop variable filed every entry under the wrong key.

    ``_face_for`` reads ``self._face_cache[(cid, slot, bold)]`` and used to
    write ``self._face_cache["hangul"]``, so the cache could never hit and
    every character re-ran a system font-index lookup.
    """
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    if renderer.font_index is None:
        pytest.skip("no system font index on this machine")
    cid = next(iter(renderer.defs["char_pr"]))
    renderer._face_for(cid, "hangul", False)
    assert renderer._face_cache, "nothing was cached at all"
    assert all(isinstance(k, tuple) and len(k) == 3
               for k in renderer._face_cache), list(renderer._face_cache)
    before = dict(renderer._face_cache)
    renderer._face_for(cid, "hangul", False)
    assert list(renderer._face_cache) == list(before), "the cache missed"


def test_a_bold_run_on_a_family_with_no_bold_cut_is_smeared():
    """HWP fakes the weight; drawing regular glyphs loses the emphasis.

    바탕 / Batang ships no bold cut, and it is the face a report-class
    document is set in, so this is the ordinary case rather than an edge one.
    The smear is horizontal — a vertical one would read as an outline — and
    it must not change the advance, or a cached line stops fitting its box.
    """
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    font = renderer.fontbook.get(30, False, None)
    piece = {"kind": "glyph", "text": "강", "font": font, "ratio": 100,
             "size_px": 30, "offset_px": 0, "colour": (0, 0, 0),
             "embolden": 0}
    plain = renderer.Image.new("RGB", (120, 60), (255, 255, 255))
    renderer._image = plain
    renderer._draw_glyph_piece(renderer.ImageDraw.Draw(plain), piece, 5, 45)
    heavy = renderer.Image.new("RGB", (120, 60), (255, 255, 255))
    renderer._image = heavy
    renderer._draw_glyph_piece(renderer.ImageDraw.Draw(heavy),
                               {**piece, "embolden": 1}, 5, 45)
    assert _ink(heavy) > _ink(plain), (_ink(heavy), _ink(plain))
    # Horizontal only: the smeared glyph occupies no extra rows.
    def rows(image):
        grey = image.convert("L").load()
        return {y for y in range(60) for x in range(120) if grey[x, y] < 160}
    assert rows(heavy) == rows(plain)


def test_embolden_is_asked_for_only_when_no_real_bold_cut_resolved():
    """A family that does have a bold face is drawn with it, not smeared."""
    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=144)
    cid = next(iter(renderer.defs["char_pr"]))
    font = renderer.fontbook.get(30, False, None)
    renderer.defs["char_pr"][cid] = {
        **renderer.defs["char_pr"][cid], "bold": True}
    renderer._synthetic_bold[(cid, "hangul", True)] = False
    assert renderer._embolden_px(cid, "hangul", font) == 0
    renderer._synthetic_bold[(cid, "hangul", True)] = True
    assert renderer._embolden_px(cid, "hangul", font) >= 1
    renderer.defs["char_pr"][cid] = {
        **renderer.defs["char_pr"][cid], "bold": False}
    assert renderer._embolden_px(cid, "hangul", font) == 0


def _border_probe(btype, width_hwp, dpi=144):
    """Draw one top border of ``btype`` and return its dark-pixel runs.

    ``px`` at 144 dpi is ``hwpunit / 50``, so the geometry below puts the edge
    at y=20 px across a 100 px span.
    """
    from xml.etree import ElementTree as ET

    renderer = own_render.OwnRenderer(_need(GIANMUN), dpi=dpi)
    renderer.defs["border_fill"]["probe"] = {
        "top": {"type": btype, "width_hwp": width_hwp, "color": (0, 0, 0)},
        "bottom": {"type": "NONE"}, "left": {"type": "NONE"},
        "right": {"type": "NONE"},
    }
    image = renderer.Image.new("RGB", (120, 60), (255, 255, 255))
    draw = renderer.ImageDraw.Draw(image)
    tc = ET.fromstring('<hp:tc xmlns:hp="urn:x" borderFillIDRef="probe"/>')
    renderer._draw_cell_borders(draw, {"tc": tc}, 0, 1000, 5000, 2000)
    grey = image.convert("L").load()
    runs, y = [], 0
    while y < 60:
        if grey[50, y] < 160:
            y0 = y
            while y < 60 and grey[50, y] < 160:
                y += 1
            runs.append((y0, y - y0))
        else:
            y += 1
    return renderer, runs


def test_a_double_slim_border_is_two_strokes_not_one_fat_one():
    """이중 실선: the declared width is the BAND, not the stroke.

    Measured against a Hancom reference at 144 dpi — a 283.46 HWPUNIT border
    (6 px) is drawn as two 2-px strokes with a 2-px gap, spanning those 6 px.
    Stroking the band solid put three times the ink on every such edge.
    """
    renderer, runs = _border_probe("DOUBLE_SLIM", 283.46456692913387)
    assert len(runs) == 2, runs
    assert runs[0][1] == runs[1][1] == 2, runs
    span = runs[1][0] + runs[1][1] - runs[0][0]
    assert span == 6, runs
    skipped = {e["element"] for e in renderer.skipped.values()}
    assert not any("DOUBLE_SLIM" in s for s in skipped), skipped


def test_a_double_border_too_narrow_to_resolve_stays_solid_and_declared():
    """Below three pixels there is no room for two strokes and a gap."""
    renderer, runs = _border_probe("DOUBLE_SLIM", 100.0)
    assert len(runs) == 1, runs
    reasons = [e["reason"] for e in renderer.skipped.values()
               if "DOUBLE_SLIM" in e["element"]]
    assert any("too narrow" in r for r in reasons), reasons


def test_other_non_solid_border_types_are_still_declared_as_solid():
    """DASH is in the corpus and is still stroked solid — say so."""
    renderer, runs = _border_probe("DASH", 283.46456692913387)
    assert len(runs) == 1, runs
    reasons = [e["reason"] for e in renderer.skipped.values()
               if "DASH" in e["element"]]
    assert any("stroked as solid" in r for r in reasons), reasons


def test_a_track_is_as_big_as_its_largest_constraint_not_its_first():
    """Row 0 holds a one-line cell and a two-line cell; it must fit both.

    Document order puts the short cell first.  Resolving the track from the
    first constraint that covers it gives the row the short cell's height and
    draws the tall cell's second line over the row below — which is what a
    report-class table does and a one-line-per-row government form never
    does.
    """
    heights = own_render.solve_tracks(
        2, [(0, 1, 1182), (0, 1, 2622), (1, 1, 1182)])
    assert heights == [2622, 1182]


def test_a_track_takes_the_max_whichever_order_the_cells_arrive_in():
    """The result cannot depend on the order the file lists its cells."""
    forward = own_render.solve_tracks(1, [(0, 1, 900), (0, 1, 2400)])
    backward = own_render.solve_tracks(1, [(0, 1, 2400), (0, 1, 900)])
    assert forward == backward == [2400]


def test_row_heights_sum_to_the_tables_own_declared_height(tmp_path):
    """A synthetic two-column table whose rows differ in line count.

    The check is the file's own internal agreement: solved rows must sum to
    the table's declared hp:sz@height without the declared-total rescale
    having to make up a shortfall, which is only true under the max reading.
    """
    rows = [(0, 1200), (1, 2400), (2, 1200)]
    constraints = []
    for row, tall in rows:
        constraints.append((row, 1, 1200))   # the short cell, listed first
        constraints.append((row, 1, tall))   # the tall cell, listed second
    total = sum(tall for _row, tall in rows)
    heights = own_render.solve_tracks(len(rows), constraints,
                                      declared_total=total)
    assert heights == [1200, 2400, 1200]
    assert sum(heights) == total


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


# ------------------------------------------------------------- equations
# No corpus form carries an hp:equation — every one of them is a blank
# government form — so the fixtures here are synthesised: a corpus form, plus
# equations whose scripts come from the repo's own LaTeX-to-HwpEqn converter
# (``engine/scripts/eqn.py``), so the thing under test is fed exactly what the
# authoring lane produces rather than hand-written HwpEqn.

sys.path.insert(0, os.path.join(ENGINE, "scripts"))
import eqn as eqn_tool  # noqa: E402
import hwpeqn_parse  # noqa: E402

EQUATION_FORM = os.path.join(CORPUS, "moel-pyojun-geunrogyeyakseo-2025.hwpx")
EQUATION_PARAGRAPH = 2


def _hwpeqn(latex):
    """The repo's own converter, refusing to hand a test a warning-carrying
    script: a fixture that is already wrong proves nothing about the reader."""
    script, warnings = eqn_tool.latex_to_hwpeqn(latex)
    assert not warnings, (latex, warnings)
    return script


def _form_with_equations(source, target, specs,
                         paragraph_index=EQUATION_PARAGRAPH):
    """A corpus form with ``hp:equation`` runs appended to one paragraph.

    ``specs`` is ``[(hwpeqn_script, sz_width, sz_height)]`` in HWPUNIT.  The
    attributes are the ones a Hancom-written equation carries — ``baseUnit``
    (the base size), ``baseLine`` (where in the box the equation's baseline
    sits), ``font``, ``treatAsChar`` — because those are the ones the renderer
    reads.  Written with ElementTree, which rewrites namespace prefixes; the
    renderer reads by local name, so that is invisible to it (same reasoning
    as ``_edited_copy``).
    """
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        payload = {name: archive.read(name) for name in names}
    root = ET.fromstring(payload["Contents/section0.xml"])
    ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    seen = 0
    host = None
    for element in root.iter():
        if own_render._local(element.tag) != "p":
            continue
        if seen == paragraph_index:
            host = element
        seen += 1
    assert host is not None, "fixture drifted: no such paragraph"
    charpr = "0"
    for run in host:
        if own_render._local(run.tag) == "run":
            charpr = run.get("charPrIDRef") or charpr
    for script, width, height in specs:
        run = ET.SubElement(host, ns + "run", {"charPrIDRef": charpr})
        equation = ET.SubElement(run, ns + "equation", {
            "version": "Equation Version 60",
            "baseLine": "69",
            "textColor": "#000000",
            "baseUnit": "1000",
            "lineMode": "CHAR",
            "font": "HancomEQN",
        })
        ET.SubElement(equation, ns + "sz", {
            "width": str(width), "widthRelTo": "ABSOLUTE",
            "height": str(height), "heightRelTo": "ABSOLUTE"})
        ET.SubElement(equation, ns + "pos", {
            "treatAsChar": "1", "vertRelTo": "PARA", "horzRelTo": "PARA",
            "vertOffset": "0", "horzOffset": "0"})
        ET.SubElement(equation, ns + "script").text = script
    payload["Contents/section0.xml"] = ET.tostring(root, encoding="utf-8")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, payload[name])
    return str(target)


ROOMY_SPECS = [
    (_hwpeqn(r"\frac{a+b}{c}"), 9000, 4200),
    (_hwpeqn(r"\sqrt{x^{2}+y^{2}}"), 11000, 3600),
    (_hwpeqn(r"\sum_{i=1}^{n} i^{2}"), 9000, 5200),
    (_hwpeqn(r"\int_{0}^{1} f(x) dx"), 11000, 4200),
    (_hwpeqn(r"\alpha \le \beta \times \Gamma"), 12000, 2600),
    ("left ( {1} over {2} right )", 6000, 4200),
]


@pytest.fixture(scope="module")
def equation_render(tmp_path_factory):
    out = tmp_path_factory.mktemp("equations")
    path = _form_with_equations(_need(EQUATION_FORM),
                                out / "equations.hwpx", ROOMY_SPECS)
    return own_render.render_to_dir(path, out / "render", dpi=144)


# -- parser mechanics, one test per construct ---------------------------

def test_over_binds_the_preceding_primary_not_the_whole_row():
    tree, info = hwpeqn_parse.parse("x = {a+b} over {c}")
    assert info["constructs"]["over"] == 1
    items = tree.items
    assert isinstance(items[-1], hwpeqn_parse.Frac)
    # ``x`` and ``=`` stayed OUTSIDE the numerator.  Under the other reading
    # of ``over`` the whole left-hand side would have been swallowed.
    assert [type(i).__name__ for i in items[:2]] == ["Row", "Atom"]


def test_a_sub_and_a_sup_on_one_base_make_one_script_node():
    tree, _info = hwpeqn_parse.parse("W_{e}^{(s)}")
    node = tree.items[0]
    assert isinstance(node, hwpeqn_parse.Script)
    assert node.sub is not None and node.sup is not None
    assert isinstance(node.base, hwpeqn_parse.Row)


def test_limits_stack_for_sums_and_sit_to_the_right_for_integrals():
    """Measured off the reference render, not assumed from the symbol."""
    assert hwpeqn_parse.parse("sum_{x}")[0].items[0].limits is True
    assert hwpeqn_parse.parse("int_{e}")[0].items[0].limits is False
    assert hwpeqn_parse.parse("min_{s}")[0].items[0].limits is False


def test_sqrt_and_root_of_build_the_same_node_with_and_without_an_index():
    plain, _ = hwpeqn_parse.parse("sqrt{x}")
    indexed, info = hwpeqn_parse.parse("root {3} of {x}")
    assert isinstance(plain.items[0], hwpeqn_parse.Radical)
    assert plain.items[0].index is None
    assert isinstance(indexed.items[0], hwpeqn_parse.Radical)
    assert indexed.items[0].index is not None
    assert info["constructs"]["root"] == 1


def test_a_fence_pairs_its_delimiters_and_an_unpaired_one_is_declared():
    paired, info = hwpeqn_parse.parse("left ( x right )")
    node = paired.items[0]
    assert isinstance(node, hwpeqn_parse.Fence)
    assert (node.left, node.right) == ("(", ")")
    assert not info["unsupported"]
    _open, open_info = hwpeqn_parse.parse("left ( x")
    assert open_info["unsupported"] == {"left-without-right": 1}


def test_a_matrix_keeps_its_rows_and_columns():
    tree, info = hwpeqn_parse.parse("pmatrix{a & b # c & d}")
    grid = tree.items[0]
    assert isinstance(grid, hwpeqn_parse.Grid)
    assert [len(row) for row in grid.rows] == [2, 2]
    assert (grid.left, grid.right) == ("(", ")")
    assert info["constructs"]["grid:pmatrix"] == 1


def test_an_unknown_word_is_a_run_of_variables_not_one_token():
    """``v_{sn}`` is v with two letters under it, exactly as HwpEqn sets it."""
    tree, _info = hwpeqn_parse.parse("sn")
    row = tree.items[0]
    assert [atom.text for atom in row.items] == ["s", "n"]


def test_greek_operators_and_quoted_literals_reach_their_own_styles():
    tree, info = hwpeqn_parse.parse('mu leq 3 ` "m"')
    styles = [(node.style, node.text) for node in tree.items
              if isinstance(node, hwpeqn_parse.Atom)]
    assert ("sym", "μ") in styles
    assert ("sym", "≤") in styles
    assert ("text", "m") in styles
    assert any(isinstance(n, hwpeqn_parse.Space) for n in tree.items)
    assert info["constructs"]["literal"] == 1


def test_an_unsupported_construct_keeps_its_own_token_text():
    tree, info = hwpeqn_parse.parse("size 12 {x}")
    assert info["unsupported"] == {"size": 1}
    raw = tree.items[0]
    assert isinstance(raw, hwpeqn_parse.Raw)
    assert raw.text == "size"


# -- the renderer ------------------------------------------------------

def test_equations_are_drawn_rather_than_boxed(equation_render):
    report = equation_render["report"]
    assert report["elements_rendered"]["equations"] == len(ROOMY_SPECS)
    assert report["elements_rendered"]["placeholders"] == 0
    laid = report["equations"]
    assert laid["laid_out"] == len(ROOMY_SPECS)
    assert laid["unsupported_constructs"] == {}
    # Every construct the fixture exercises came back named.
    for construct in ("over", "sqrt", "fence", "bigop:sum", "bigop:int",
                      "greek", "symbol", "subscript", "superscript"):
        assert construct in laid["constructs"], construct


def test_hp_script_is_no_longer_reported_as_an_unhandled_element(
        equation_render):
    skipped = {entry["element"] for entry
               in equation_render["report"]["elements_skipped"]}
    assert "hp:script" not in skipped
    assert "hp:equation" in skipped, "the lane still has to declare itself"


def test_every_equation_stays_inside_its_declared_hp_sz(equation_render):
    """The promise of this lane, checked on the render's own record."""
    placements = equation_render["report"]["equations"]["placements"]
    assert len(placements) == len(ROOMY_SPECS)
    for place in placements:
        bx0, by0, bx1, by1 = place["box_px"]
        ix0, iy0, ix1, iy1 = place["ink_px"]
        assert bx0 <= ix0 <= ix1 <= bx1, place
        assert by0 <= iy0 <= iy1 <= by1, place


def test_a_roomy_equation_is_not_scaled(equation_render):
    """Scale-to-fit is a FALLBACK.  A box the equation fits must not fire it."""
    report = equation_render["report"]
    assert report["equations"]["scaled_to_fit"] == 0
    assert report["equations"]["scale_factors"] == []
    assert all(place["scale"] == 1.0
               for place in report["equations"]["placements"])


def test_an_equation_larger_than_its_box_is_scaled_and_declared(tmp_path):
    """A box far too small for the equation: it shrinks, and it says so."""
    path = _form_with_equations(
        _need(EQUATION_FORM), tmp_path / "tight.hwpx",
        [(_hwpeqn(r"\frac{a+b+c+d+e}{f+g+h+i+j}"), 2400, 900)])
    report = own_render.render_to_dir(path, tmp_path / "render",
                                      dpi=144)["report"]
    equations = report["equations"]
    assert equations["laid_out"] == 1
    assert equations["scaled_to_fit"] == 1
    assert 0 < equations["scale_factors"][0] < 1
    place = equations["placements"][0]
    assert place["scale"] < 1.0
    bx0, by0, bx1, by1 = place["box_px"]
    ix0, iy0, ix1, iy1 = place["ink_px"]
    assert bx0 <= ix0 <= ix1 <= bx1 and by0 <= iy0 <= iy1 <= by1
    declared = {entry["element"] for entry in report["elements_skipped"]}
    assert "hp:equation@equation_scaled" in declared


def test_an_unsupported_construct_is_declared_per_construct(tmp_path):
    path = _form_with_equations(
        _need(EQUATION_FORM), tmp_path / "unsupported.hwpx",
        [("size 12 {x} + binom {n} {k}", 12000, 3000)])
    report = own_render.render_to_dir(path, tmp_path / "render",
                                      dpi=144)["report"]
    assert report["equations"]["unsupported_constructs"] == {"size": 1,
                                                             "binom": 1}
    declared = {entry["element"]: entry
                for entry in report["elements_skipped"]}
    assert "hp:equation@script[size]" in declared
    assert "hp:equation@script[binom]" in declared
    # The equation is still drawn: an unsupported construct costs its own
    # token text, not the whole equation.
    assert report["equations"]["laid_out"] == 1


def test_an_equation_with_no_script_falls_back_to_the_placeholder(tmp_path):
    path = _form_with_equations(_need(EQUATION_FORM), tmp_path / "empty.hwpx",
                                [("   ", 9000, 3000)])
    report = own_render.render_to_dir(path, tmp_path / "render",
                                      dpi=144)["report"]
    assert report["equations"]["laid_out"] == 0
    assert report["elements_rendered"]["placeholders"] == 1
    reasons = [entry["reason"] for entry in report["elements_skipped"]
               if entry["element"] == "hp:equation"]
    assert any("no hp:script" in reason for reason in reasons)


def test_the_maths_face_is_resolved_or_substituted_and_named(equation_render):
    """A maths face is a face: it goes through the same declaration path."""
    faces = [face for face in equation_render["report"]["fonts"]["faces"]
             if face["slot"] == "equation"]
    assert faces, "the equation face was never declared"
    face = faces[0]
    assert face["declared"] == "HancomEQN"
    assert face["characters"] == len(ROOMY_SPECS)
    if face["resolved"]:
        assert face["file"]
    else:
        assert face["substituted_with"]


def test_a_stacked_equation_records_one_line_box_per_baseline(
        equation_render):
    """A PDF text extractor reads a fraction as two lines; so does this."""
    boxes = [box for box in equation_render["report"]["line_boxes"]
             if box["mode"] == "equation"]
    assert len(boxes) > len(ROOMY_SPECS), (
        "a stacked equation has to contribute more than one line box")
    placements = equation_render["report"]["equations"]["placements"]
    assert sum(place["baselines"] for place in placements) == len(boxes)
    assert any(place["baselines"] >= 2 for place in placements)


def test_a_form_with_no_equation_reports_an_empty_equation_lane(
        gianmun_render):
    """The lane must not invent work on a document that has none."""
    equations = gianmun_render["report"]["equations"]
    assert equations["laid_out"] == 0
    assert equations["constructs"] == {}
    assert equations["placements"] == []
    assert gianmun_render["report"]["elements_rendered"]["equations"] == 0


def test_two_equation_renders_are_byte_identical(tmp_path):
    """Determinism has to survive the new lane, mask compositing included."""
    path = _form_with_equations(_need(EQUATION_FORM), tmp_path / "det.hwpx",
                                ROOMY_SPECS)
    first = own_render.render_to_dir(path, tmp_path / "a", dpi=144)
    second = own_render.render_to_dir(path, tmp_path / "b", dpi=144)
    assert len(first["pngs"]) == len(second["pngs"])
    for left, right in zip(first["pngs"], second["pngs"]):
        with open(left, "rb") as handle:
            a = handle.read()
        with open(right, "rb") as handle:
            b = handle.read()
        assert a == b, "identical input produced different PNG bytes"


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
