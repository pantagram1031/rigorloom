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
