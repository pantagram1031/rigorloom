"""Pins for ``engine/scripts/render_check.py``.

Three things have to hold for a per-feature score to mean anything, and each
is pinned here rather than eyeballed:

1. *Region derivation.*  A feature is located by its own block ordinal, and
   the ordinal→placement lookup has to survive the two shapes real documents
   produce: a table listed once per page fragment under the same block id,
   and a page-furniture feature that has no top-level block at all.  Get this
   wrong and every metric is measured on the wrong pixels while still looking
   plausible.

2. *Verdict thresholds.*  The bounds are a judgement call, so the boundary
   behaviour is pinned: a value exactly on a bound passes it.

3. *Declared-limit attribution.*  ``elements_skipped`` says both "nothing
   drawn" and "drawn, but stroked as solid".  Only the first makes a feature
   ``unsupported``; conflating them was a real bug in the first pass, where
   ``hp:footNotePr/hp:noteLine`` marked 각주 unsupported and
   ``hp:equation`` marked four equations unsupported even though the ledger
   said both were on the page.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import own_render  # noqa: E402
import render_check as rc  # noqa: E402
import render_scoreboard as rs  # noqa: E402

pytestmark = pytest.mark.skipif(not own_render.pillow_available(),
                                reason="Pillow is not installed")

CORPUS = os.path.join(ROOT, "tests", "corpus", "render-check")
DOCUMENT = os.path.join(CORPUS, "render-check-01.hwpx")
REFERENCE = os.path.join(CORPUS, "render-check-01.pdf")
BLOCKS = os.path.join(CORPUS, "render-check-01.blocks.json")


def _need(path):
    if not os.path.isfile(path):
        pytest.skip("corpus fixture missing: %s" % path)
    return path


# ---------------------------------------------------------------------------
# Region derivation
# ---------------------------------------------------------------------------
def _sidecar(page_height=84188, body_top=9920, bottom=4252, footer=4252,
             blocks=None, first_page=1):
    return {
        "sections": [{
            "index": 0,
            "pages": [first_page, first_page],
            "page_geometry_hwpunit": {
                "height": page_height,
                "body_top": body_top,
                "margin": {"top": 5668, "bottom": bottom, "header": 4252,
                           "footer": footer, "left": 8504, "right": 8504,
                           "gutter": 0},
            },
        }],
        "block_layout": [{"blocks": blocks or []}],
    }


def test_a_feature_is_placed_at_its_own_block_not_at_a_guessed_offset():
    sidecar = _sidecar(blocks=[
        {"block": 0, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 0},
        {"block": 4, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 1600},
        {"block": 5, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 4800},
    ])
    features = [{"id": "F01", "label": "a", "section": 0, "block_ordinal": 1},
                {"id": "F02", "label": "b", "section": 0, "block_ordinal": 2}]
    regions, bands = rc.candidate_regions(sidecar, features)

    assert bands == {}
    height = 84188.0
    # F01 starts at its own block and stops where F02 starts.
    assert regions["F01"].page == 1
    assert regions["F01"].top == pytest.approx((9920 + 1600) / height, abs=1e-5)
    assert regions["F01"].bottom == pytest.approx((9920 + 4800) / height,
                                                  abs=1e-5)
    # The last feature runs to the foot of the printable body, not the page.
    assert regions["F02"].bottom == pytest.approx(
        (84188 - 4252 - 4252) / height, abs=1e-5)


def test_a_table_split_across_a_page_is_still_one_feature():
    # own_render lists a split table once per page fragment, under the same
    # block id.  The feature owns all of them and starts at the first.
    sidecar = _sidecar(blocks=[
        {"block": 0, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 0},
        {"block": 7, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 2000},
        {"block": 7, "kind": "paragraph", "page": 1, "vertpos_hwpunit": 0},
        {"block": 9, "kind": "paragraph", "page": 1, "vertpos_hwpunit": 9000},
    ])
    features = [{"id": "F01", "label": "table", "section": 0,
                 "block_ordinal": 1},
                {"id": "F02", "label": "after", "section": 0,
                 "block_ordinal": 2}]
    regions, _ = rc.candidate_regions(sidecar, features)

    assert regions["F01"].page == 1
    assert regions["F01"].top == pytest.approx((9920 + 2000) / 84188.0,
                                               abs=1e-5)
    # F02 is on another page, so F01 runs to the foot of its own page.
    assert regions["F01"].bottom == pytest.approx((84188 - 8504) / 84188.0,
                                                  abs=1e-5)
    assert regions["F02"].page == 2


def test_page_furniture_is_located_by_band_because_it_has_no_block():
    sidecar = _sidecar(blocks=[
        {"block": 0, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 0}])
    features = [{"id": "F50", "label": "머리말", "section": 0,
                 "band": "header"},
                {"id": "F51", "label": "꼬리말", "section": 0,
                 "band": "footer"}]
    regions, bands = rc.candidate_regions(sidecar, features)

    assert set(bands) == {"F50", "F51"}
    height = 84188.0
    assert regions["F50"].top == pytest.approx(5668 / height, abs=1e-5)
    assert regions["F50"].bottom == pytest.approx((5668 + 4252) / height,
                                                  abs=1e-5)
    assert regions["F51"].bottom == pytest.approx((84188 - 4252) / height,
                                                  abs=1e-5)
    assert regions["F51"].top < regions["F51"].bottom


def test_an_ordinal_past_the_end_of_the_section_yields_no_region():
    sidecar = _sidecar(blocks=[
        {"block": 0, "kind": "paragraph", "page": 0, "vertpos_hwpunit": 0}])
    features = [{"id": "F99", "label": "z", "section": 0, "block_ordinal": 8}]
    regions, _ = rc.candidate_regions(sidecar, features)
    assert "F99" not in regions


def test_body_bottom_fraction_excludes_the_footer_band():
    fractions = rc.body_bottom_fractions(_sidecar())
    assert fractions[0] == pytest.approx((84188 - 4252 - 4252) / 84188.0,
                                         abs=1e-6)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _grey(pixels, size):
    from PIL import Image
    image = Image.new("L", size, 255)
    image.putdata(pixels)
    return image


def test_ink_masks_of_one_image_against_itself_have_iou_one():
    from PIL import Image
    image = Image.new("L", (16, 16), 255)
    for x in range(4, 12):
        for y in range(4, 12):
            image.putpixel((x, y), 0)
    mask = rc._ink_mask(image, 128)
    assert rc._mask_iou(mask, mask) == pytest.approx(1.0)


def test_two_blank_regions_agree_rather_than_dividing_by_zero():
    from PIL import Image
    blank = rc._ink_mask(Image.new("L", (16, 16), 255), 128)
    assert rc._mask_iou(blank, blank) == 1.0


def test_disjoint_ink_scores_zero_iou():
    from PIL import Image
    left = Image.new("L", (40, 8), 255)
    right = Image.new("L", (40, 8), 255)
    for y in range(8):
        left.putpixel((2, y), 0)
        right.putpixel((36, y), 0)
    assert rc._mask_iou(rc._ink_mask(left, 128),
                        rc._ink_mask(right, 128)) == pytest.approx(0.0)


def test_the_one_pixel_tolerance_forgives_a_one_pixel_shift():
    # The point of the tolerance: a glyph in the right place but hinted one
    # pixel over must not read as a layout failure.
    from PIL import Image
    left = Image.new("L", (40, 12), 255)
    right = Image.new("L", (40, 12), 255)
    for y in range(3, 9):
        for x in range(10, 20):
            left.putpixel((x, y), 0)
            right.putpixel((x + 1, y), 0)
    exact = rc._mask_iou(rc._ink_mask(left, 128, tolerance=0),
                         rc._ink_mask(right, 128, tolerance=0))
    tolerant = rc._mask_iou(rc._ink_mask(left, 128),
                            rc._ink_mask(right, 128))
    assert tolerant > exact
    assert tolerant > 0.75


def test_padding_never_rescales_a_crop():
    from PIL import Image
    small = Image.new("RGB", (10, 4), (0, 0, 0))
    padded = rc._pad_to(small, (20, 9))
    assert padded.size == (20, 9)
    assert padded.getpixel((0, 0)) == (0, 0, 0)        # content kept, top-left
    assert padded.getpixel((15, 7)) == (255, 255, 255)  # pad is white


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------
def _metrics(ssim=0.95, iou=0.60, delta=0.0):
    return {"ssim": ssim, "iou": iou, "ink": {"delta": delta},
            "ssim_inked": None}


def test_a_value_exactly_on_a_bound_passes_it():
    good = rc.THRESHOLDS["match"]
    assert rc.verdict_for(_metrics(ssim=good["ssim_min"],
                                   iou=good["iou_min"],
                                   delta=good["ink_delta_abs_max"]),
                          []) == "match"
    okay = rc.THRESHOLDS["close"]
    assert rc.verdict_for(_metrics(ssim=okay["ssim_min"],
                                   iou=okay["iou_min"],
                                   delta=-okay["ink_delta_abs_max"]),
                          []) == "close"


def test_each_gated_channel_can_demote_a_verdict_on_its_own():
    good = rc.THRESHOLDS["match"]
    assert rc.verdict_for(_metrics(iou=good["iou_min"] - 0.01),
                          []) == "close"
    assert rc.verdict_for(_metrics(delta=good["ink_delta_abs_max"] + 0.001),
                          []) == "close"
    assert rc.verdict_for(_metrics(ssim=good["ssim_min"] - 0.01),
                          []) == "close"
    assert rc.verdict_for(_metrics(iou=0.01, ssim=0.2, delta=0.4),
                          []) == "differs"


def test_a_declared_not_drawn_element_outranks_the_pixels():
    # A placeholder box can score well on SSIM against a white-ish region;
    # the ledger, not the score, is what makes a feature unsupported.
    assert rc.verdict_for(_metrics(ssim=0.99, iou=0.9),
                          [{"element": "hp:rect",
                            "reason": "placeholder"}]) == "unsupported"


# ---------------------------------------------------------------------------
# Declared-limit attribution
# ---------------------------------------------------------------------------
LEDGER = [
    {"element": "hp:rect", "count": 1,
     "reason": "object drawn as a placeholder box at its declared hp:sz"
               " extent; its content is not rendered"},
    {"element": "hp:equation", "count": 4,
     "reason": "laid out from its hp:script inside the declared hp:sz extent;"
               " identifier tokens are approximated"},
    {"element": "hp:footNotePr/hp:noteLine@length=-1", "count": 1,
     "reason": "a non-positive separator length is the writer asking for the"
               " default"},
    {"element": "hh:topBorder@type=DASH", "count": 1,
     "reason": "non-solid border stroked as solid"},
    {"element": "hp:autoNum", "count": 3,
     "reason": "element has no handler in this tier; nothing drawn"},
]


def test_a_drawn_element_with_a_named_limit_is_not_called_unsupported():
    feature = {"label": "수식 — 분수 (fraction)"}
    limits, not_drawn = rc.declared_limits(feature, LEDGER)
    assert [e["element"] for e in limits] == ["hp:equation"]
    assert not_drawn == []


def test_a_placeholder_element_is_called_unsupported():
    feature = {"label": "글상자 / 그리기 개체 사각형 (text box)"}
    limits, not_drawn = rc.declared_limits(feature, LEDGER)
    assert [e["element"] for e in not_drawn] == ["hp:rect"]


def test_footnote_pr_does_not_claim_to_be_the_footnote():
    # `hp:footNotePr/...` starts with `hp:footNote`; a substring match made
    # 각주 unsupported on the strength of a separator-length note.
    feature = {"label": "각주 (footnote)"}
    limits, not_drawn = rc.declared_limits(feature, LEDGER)
    assert limits == []
    assert not_drawn == []


def test_border_limits_attach_to_the_border_feature_without_unsupporting_it():
    feature = {"label": "표 — 테두리 종류 (SOLID / DASH / DOT / DOUBLE / 굵기)"}
    limits, not_drawn = rc.declared_limits(feature, LEDGER)
    assert [e["element"] for e in limits] == ["hh:topBorder@type=DASH"]
    assert not_drawn == []


def test_base_tag_strips_attribute_and_index_suffixes():
    assert rc._base_tag("hh:topBorder@type=DASH") == "hh:topBorder"
    assert rc._base_tag("hp:equation@script[matrix]") == "hp:equation"
    assert rc._base_tag("hp:rect") == "hp:rect"


# ---------------------------------------------------------------------------
# End to end on the committed fixture
# ---------------------------------------------------------------------------
def test_the_report_has_the_shape_downstream_readers_expect():
    _need(DOCUMENT)
    _need(REFERENCE)
    _need(BLOCKS)
    report = rc.run(DOCUMENT, REFERENCE, BLOCKS, dpi=48)

    for key in ("render_check_version", "renderer", "document",
                "reference_pdf", "dpi", "pages", "reference_geometry_scale",
                "thresholds", "region_derivation", "elements_skipped",
                "features", "tally"):
        assert key in report, key

    expected = json.load(open(BLOCKS, encoding="utf-8"))["features"]
    assert len(report["features"]) == len(expected)
    assert [row["id"] for row in report["features"]] == \
        [f["id"] for f in expected]

    assert sum(report["tally"].values()) == len(expected)
    assert set(report["tally"]) <= set(rc.VERDICT_ORDER)

    for row in report["features"]:
        assert row["verdict"] in rc.VERDICT_ORDER
        assert row["region"]["candidate"] is not None
        assert row["region"]["reference"] is not None
        assert -1.0 <= row["ssim"] <= 1.0
        assert 0.0 <= row["iou"] <= 1.0


def test_the_reference_is_still_pinned_at_one_to_one():
    _need(DOCUMENT)
    _need(REFERENCE)
    import render_scoreboard as rs
    geometry = rs.reference_geometry_scale(DOCUMENT, REFERENCE)
    assert geometry["comparable"] is True
    assert abs(geometry["scale"] - 1.0) <= geometry["tolerance"]


def test_the_markdown_table_has_one_row_per_feature():
    _need(BLOCKS)
    report = {
        "features": [
            {"id": "F01", "label": "a", "ssim": 0.9, "ssim_inked": 0.5,
             "iou": 0.6, "ink": {"delta": 0.001}, "verdict": "match",
             "page_agreement": True,
             "region": {"candidate": {"page": 1}, "reference": {"page": 1}}},
            {"id": "F02", "label": "b", "verdict": "differs",
             "region": {"candidate": None, "reference": None}},
        ],
    }
    table = rc.markdown(report, None).splitlines()
    assert len(table) == 4          # header, rule, two rows
    assert "`F01`" in table[2] and "match" in table[2]
    assert "`F02`" in table[3] and "differs" in table[3]


# ---------------------------------------------------------------------------
# table-break-probe — the measured table placement rule
# (docs/research/table-page-break-rule.md)
# ---------------------------------------------------------------------------
PROBE = os.path.join(CORPUS, "table-break-probe.hwpx")
PROBE_REFERENCE = os.path.join(CORPUS, "table-break-probe.pdf")
PROBE_CASES = os.path.join(CORPUS, "table-break-probe.cases.json")

#: The eleven cases, in document order.  Read from the sidecar so the test
#: fails loudly if the builder and the committed document ever disagree.
PROBE_CASE_IDS = ["T%02d" % n for n in range(1, 12)]


def _probe_reference_pages():
    """``{case id: (label page, first table row page)}`` read out of Hancom's
    own PDF export — the reference side, located independently of ours."""
    import re
    fitz = rs._require_fitz()
    label = re.compile(r"\[(T\d\d)\]")
    first_row = re.compile(r"(T\d\d) R01 C1")
    labels, rows = {}, {}
    with fitz.open(PROBE_REFERENCE) as document:
        for index, page in enumerate(document):
            text = page.get_text()
            for match in label.finditer(text):
                labels.setdefault(match.group(1), index)
            for match in first_row.finditer(text):
                rows.setdefault(match.group(1), index)
    return {cid: (labels.get(cid), rows.get(cid)) for cid in PROBE_CASE_IDS}


def _probe_table_block_pages():
    """``[page, ...]`` for the eleven table-carrying blocks, in document
    order, from ``own_render``'s own computed flow pass."""
    renderer = own_render.OwnRenderer(
        _need(PROBE), dpi=96,
        block_layout=own_render.BLOCK_LAYOUT_COMPUTED)
    _images, sidecar = renderer.render()
    layout = sidecar["block_layout"]
    section = layout[0] if isinstance(layout, list) else layout
    # ``blocks[*]["block"]`` is the renderer's own paragraph index, which
    # counts cell paragraphs too — so the handle has to come from
    # ``paragraph_index``, not from the top-level ordinal.
    carries_table = []
    for element in own_render._kids(renderer.sections[0], "p"):
        if any(own_render._local(child.tag) == "tbl"
               for child in element.iter()):
            carries_table.append(renderer.paragraph_index[id(element)])
    by_block = {}
    for record in section["blocks"]:
        by_block.setdefault(record["block"], record["page"])
    return sidecar, section, [by_block[i] for i in carries_table]


def test_the_probe_document_declares_the_eleven_cases_it_is_pinned_for():
    with open(_need(PROBE_CASES), encoding="utf-8") as handle:
        cases = json.load(handle)
    assert [c["id"] for c in cases] == PROBE_CASE_IDS
    # The geometry the rule turns on: 25 rows of 2600 fit the 65 764 HWPUNIT
    # body box and 26 do not.
    assert [c["rows"] for c in cases] == [25, 26, 30, 55, 15, 15, 15,
                                          30, 30, 30, 27]
    assert [c["pageBreak"] for c in cases] == [
        "CELL", "CELL", "CELL", "CELL", "CELL", "TABLE", "NONE",
        "TABLE", "NONE", "CELL", "CELL"]


def test_every_probe_table_is_inline_and_therefore_unsplittable():
    """The measured half of the permission, on the document that measured it:
    all eleven tables are 글자처럼 취급, seven of them declare ``CELL``, and
    not one of them may split."""
    renderer = own_render.OwnRenderer(_need(PROBE), dpi=96)
    tables = [element for element in renderer.sections[0].iter()
              if own_render._local(element.tag) == "tbl"]
    assert len(tables) == 11
    assert all(renderer._table_is_inline(t) for t in tables)
    assert sum((t.get("pageBreak") or "").upper() == "CELL"
               for t in tables) == 7
    assert not any(renderer._table_may_split(t) for t in tables)


def test_the_flow_pass_places_every_probe_table_where_hancom_does():
    """The rule, end to end, against Hancom's own export.

    Neither side is hand-placed: ours is the flow pass's page for the block
    that carries the table, Hancom's is the page its ``Tnn R01 C1`` cell text
    lands on.  Eleven cases, no exception — and no table split on either
    side, which is the whole finding
    (``docs/research/table-page-break-rule.md``).
    """
    _need(PROBE_REFERENCE)
    reference = _probe_reference_pages()
    sidecar, section, ours = _probe_table_block_pages()

    assert sidecar["pages"] == 23, sidecar["pages"]
    counters = section["flow_counters"]
    # Nothing splits.  Three tables move whole: T05/T06/T07, the three that
    # differ only in pageBreak and land identically.  The other eight already
    # start a page of their own, so they have nowhere to move to.
    assert counters["tables_split"] == 0, counters
    assert counters["tables_moved_whole"] == 3, counters

    mismatch = []
    for case, ourpage in zip(PROBE_CASE_IDS, ours):
        label_page, ref_page = reference[case]
        if ref_page is None or ourpage != ref_page:
            mismatch.append((case, ourpage, ref_page, label_page))
        # Every table starts the page after its own label: the moved ones
        # because they moved, the rest because they carry the page break.
        assert label_page is not None and ref_page == label_page + 1, case
    assert mismatch == [], mismatch


# ---------------------------------------------------------------------------
# Resolution-aware bounds (docs/research/ink-residual.md)
#
# Two of this harness's channels are stated in PIXELS but mean something
# PHYSICAL: the IoU tolerance is 0.26 mm of registration slack, and the ink
# bound is a bound on a residual that lives in the ~1 px antialias band along
# every glyph outline.  Both are now derived from the raster in use.  The one
# thing that must never move is the ratified 96 dpi baseline, so that is
# pinned first.
# ---------------------------------------------------------------------------
def test_the_derived_bounds_are_exact_no_ops_at_the_default_dpi():
    assert rc.iou_tolerance_px(rc.DEFAULT_DPI) == rc.IOU_TOLERANCE_PX == 1
    for band in ("match", "close"):
        base = rc.THRESHOLDS[band]["ink_delta_abs_max"]
        assert rc.ink_delta_bound(base, rc.DEFAULT_DPI) == base


def test_the_iou_tolerance_holds_its_physical_size_across_rasters():
    # 0.26 mm is one pixel at 96 dpi, two at 144 and 192, three at 288.
    assert rc.iou_tolerance_px(96) == 1
    assert rc.iou_tolerance_px(144) == 2
    assert rc.iou_tolerance_px(192) == 2
    assert rc.iou_tolerance_px(288) == 3
    # Never zero: a zero-tolerance IoU measures rasteriser luck, which is the
    # whole reason the tolerance exists.
    assert rc.iou_tolerance_px(48) == 1


def test_the_ink_bound_only_ever_tightens_above_the_default_dpi():
    base = rc.THRESHOLDS["close"]["ink_delta_abs_max"]
    bounds = [rc.ink_delta_bound(base, d) for d in (96, 144, 192, 288)]
    assert bounds == sorted(bounds, reverse=True)
    assert bounds[0] == base
    # The residual it bounds decays FASTER than 1/dpi (measured coverage ratio
    # 1.80 -> 1.16 -> ~1.0 over 96 -> 144 -> 192), so the bound stays
    # conservative rather than chasing the measurement.
    assert bounds[1] == pytest.approx(base * 96 / 144.0)


def test_verdict_for_applies_the_bound_of_the_dpi_it_is_given():
    base = rc.THRESHOLDS["close"]["ink_delta_abs_max"]
    metrics = _metrics(ssim=0.70, iou=0.40, delta=base)
    assert rc.verdict_for(metrics, [], 96) == "close"
    # The same delta is out of bounds on a finer raster, where the rasteriser
    # cannot account for it.
    assert rc.verdict_for(metrics, [], 288) == "differs"


# ---------------------------------------------------------------------------
# The rasteriser floor is recorded, not tuned away
# ---------------------------------------------------------------------------
def test_the_ink_mass_channel_is_threshold_free_and_not_gated():
    from PIL import Image
    # A band of pure 50% grey: every pixel is lighter than the ink threshold,
    # so the thresholded channel calls it blank and the coverage channel does
    # not.  That gap is exactly what RASTERISER_FLOOR is about.
    grey = Image.new("L", (20, 10), 128)
    assert rs._ink_fraction(grey) == 0.0
    assert rc.ink_mass_fraction(grey) == pytest.approx((255 - 128) / 255.0)
    assert rc.ink_mass_fraction(Image.new("L", (4, 4), 255)) == 0.0
    assert rc.ink_mass_fraction(Image.new("L", (4, 4), 0)) == 1.0
    # Reported, never gated: the bounds are stated against ink.delta.
    assert "ink_mass" in rc.THRESHOLDS["reported_not_gated"]
    assert "ink_ratio" in rc.THRESHOLDS["reported_not_gated"]
    assert rc.THRESHOLDS["gated_on"] == ["iou", "ink_delta", "ssim"]


def test_score_region_reports_the_coverage_channel_beside_the_gated_one():
    from PIL import Image
    reference = Image.new("RGB", (24, 12), (255, 255, 255))
    candidate = Image.new("RGB", (24, 12), (255, 255, 255))
    for y in range(4, 8):
        for x in range(6, 14):
            reference.putpixel((x, y), (0, 0, 0))
            candidate.putpixel((x, y), (0, 0, 0))
    metrics = rc.score_region(reference, candidate, rs.INK_THRESHOLD)
    ink = metrics["ink"]
    assert ink["mass_ratio"] == pytest.approx(1.0)
    assert ink["mass_delta"] == 0.0
    assert metrics["iou_tolerance_px"] == rc.IOU_TOLERANCE_PX
    # A heavier candidate shows up on the coverage channel as a ratio, which
    # is the shape the residual actually has.
    for y in range(3, 9):
        for x in range(5, 15):
            candidate.putpixel((x, y), (0, 0, 0))
    heavier = rc.score_region(reference, candidate, rs.INK_THRESHOLD)
    assert heavier["ink"]["mass_ratio"] > 1.5


def test_the_rasteriser_floor_is_declared_with_its_measurement():
    floor = rc.RASTERISER_FLOOR
    assert (floor["coverage_ratio_body_text"]["96"]
            > floor["coverage_ratio_body_text"]["144"]
            >= floor["coverage_ratio_body_text"]["192"])
    # The floor at 96 dpi is the close bound: the ink channel cannot separate
    # a real ink error from the rasteriser there, and says so.
    assert (floor["floor_at_96_dpi"]
            == rc.THRESHOLDS["close"]["ink_delta_abs_max"])
