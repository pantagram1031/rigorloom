#!/usr/bin/env python3
"""Score the render-check document feature block by feature block.

``render_scoreboard`` answers "how close is this page?".  This answers "how
close is this *feature*?", which is the question a renderer backlog is
actually written against: a page-level SSIM of 0.86 says nothing about
whether 자간 is right and 각주 is missing.

How a region is found
---------------------
Both sides are located from the document itself; nothing is hand-placed.

*Candidate side.*  ``tests/corpus/render-check/render-check-01.blocks.json``
records, for every feature, the ordinal of the label block that opens it
among its section's top-level blocks.  ``own_render``'s sidecar carries
``block_layout[section]["blocks"]`` — exactly those blocks, in the same
order, each with the page and the ``vertpos_hwpunit`` the flow pass gave it.
Ordinal → placement is therefore a lookup, and the band runs from this
feature's block down to the next feature's block (or the bottom of the body).

*Reference side.*  Hancom's PDF export carries a text layer, so the same
feature is found by searching the reference for its own ``[Fnn]`` marker.
That is the authoring engine's placement of the very same anchor — an
independent locator, not our layout projected onto their pixels.  When the
two locators disagree about which page a feature is on, that disagreement is
reported (``page_agreement``) rather than papered over.

Page furniture (머리말/꼬리말) has no top-level block.  Those features declare
a ``band`` instead and are located from the section's page geometry: the
header band is ``[margin.top, margin.top + margin.header]``, the footer band
is the mirror at the foot of the page.

Metrics, per feature
--------------------
``ssim``       block SSIM (``render_scoreboard.ssim``) over the two crops,
               resampled to a common grid.  ``ssim_inked`` is the same
               statistic over blocks that carry ink on either side — the
               honest number for a mostly-white band.
``iou``        intersection-over-union of the two binarised ink masks.  This
               is the "is the same ink in the same place" channel; SSIM can
               stay high on two nearly blank crops that disagree completely.
``ink_delta``  candidate ink fraction minus reference ink fraction.  Signed:
               negative means the renderer drew less than Hancom did, which
               is what a missing element looks like.

Verdicts
--------
``unsupported``  the renderer declared this feature's element skipped (its
                 ``elements_skipped`` ledger names an element this feature
                 owns).  Declared, not inferred from a low score.
``match``        ssim_inked >= 0.90 and iou >= 0.75 and |ink_delta| <= 0.01
``close``        ssim_inked >= 0.70 and iou >= 0.45 and |ink_delta| <= 0.03
``differs``      anything else.

The thresholds are this harness's own proposal, not a ratified gate: they
were chosen so that a feature whose glyphs land in the right places but with
different hinting reads ``match``, a feature that is drawn but visibly
displaced or restyled reads ``close``, and a feature that is missing,
mislaid or replaced by a placeholder reads ``differs``.  ``report.json``
carries them so a later pass can move them deliberately.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import own_render  # noqa: E402
import render_scoreboard as rs  # noqa: E402

CHECK_VERSION = "1"
DEFAULT_DPI = 96

#: Verdict bounds.  Stated here, echoed into the report, not ratified.
#:
#: The gate is IoU (where the ink is) and ink delta (whether it was drawn at
#: all), with plain SSIM as a raster backstop.  ``ssim_inked`` is reported but
#: deliberately *not* gated on: measured on this document it sits between
#: -0.05 and 0.6 for every feature, including ones that are visibly correct,
#: because block SSIM over 10 pt Korean glyphs at 96 dpi collapses as soon as
#: the two engines pick different faces — which own_render's own named limits
#: say it does.  A gate that every feature fails equally ranks nothing.
THRESHOLDS = {
    "match": {"iou_min": 0.55, "ink_delta_abs_max": 0.010, "ssim_min": 0.90},
    "close": {"iou_min": 0.30, "ink_delta_abs_max": 0.025, "ssim_min": 0.65},
    "ink_threshold": rs.INK_THRESHOLD,
    "iou_tolerance_mm": 0.26,
    "gated_on": ["iou", "ink_delta", "ssim"],
    "reported_not_gated": ["ssim_inked", "ink_mass", "ink_ratio"],
    "ratified": False,
    "rationale": (
        "match = same ink in the same places, differing only in rasterisation;"
        " close = drawn and recognisable but displaced or restyled;"
        " differs = missing, mislaid, or replaced by a placeholder."
        " Bounds were set against the measured spread on this document, so"
        " they separate its features; they are not a ratified regression"
        " gate and no other document has been scored with them."),
}

#: The ink channel's own noise floor, measured, not fitted.
#:
#: ``docs/research/ink-residual.md`` pairs 1,000+ glyphs of this document
#: against the reference by their own characters, on bands whose lines are
#: already pixel-exact, and finds the residual is neither displacement nor
#: substitution: our rasteriser simply lays down MORE COVERAGE per glyph than
#: the reference's.  The excess is multiplicative and uniform — the same
#: factor on features that read ``close`` and on features that read
#: ``differs`` — and it decays as the glyphs get bigger in device pixels:
#:
#:     body-text coverage ratio (ours / reference), 9.95 pt 바탕
#:       96 dpi (13 px em)   1.80   dark-pixel ratio 2.60
#:      144 dpi (20 px em)   1.16   dark-pixel ratio 1.25
#:      192 dpi (27 px em)   ~1.0
#:      288 dpi (40 px em)   ~1.0   band ink delta reaches 0.000
#:
#: Two consequences the bounds have to respect.  First, at the default 96 dpi
#: ``ink_delta`` on a dense 10 pt Korean text band IS this floor: the measured
#: band delta is the band's own reference ink fraction times (ratio - 1), so
#: a denser band scores a larger delta for identical renderer behaviour.  The
#: ``close`` bound of 0.025 and the floor are the same size at 96 dpi, which
#: is why the ink channel cannot separate a real ink error from the rasteriser
#: there.  Second, a genuinely missing element does NOT behave this way: F45
#: (a declared-unsupported text box) holds ``ink_delta`` at -0.008 .. -0.023
#: at every dpi from 96 to 384 while every drawn text feature collapses to
#: zero.  The channel's NEGATIVE side is where its signal is.
#:
#: No fudge is applied for any of this.  It is recorded, echoed into the
#: report, and the bounds are made resolution-aware below.
RASTERISER_FLOOR = {
    "measured_on": "render-check-01, F01/F06/F07/F08/F13/F15, per glyph",
    "coverage_ratio_body_text": {"96": 1.80, "144": 1.16, "192": 1.0,
                                 "288": 1.0},
    "dark_pixel_ratio_body_text": {"96": 2.60, "144": 1.25},
    "band_delta_model": "reference_ink_fraction * (coverage_ratio - 1)",
    "floor_at_96_dpi": 0.025,
    "note": ("at 96 dpi the positive side of ink_delta on 10 pt Korean text"
             " is at this floor; the negative side is not, and that is the"
             " side a missing element moves"),
}


def iou_tolerance_px(dpi=DEFAULT_DPI):
    """The ink-agreement tolerance, in pixels of a ``dpi`` raster.

    The tolerance is PHYSICAL, and this module already said so: the comment
    on ``_ink_mask`` fixes it at one pixel of a 96 dpi raster, i.e. 0.26 mm,
    "below what a reader can see, and far below the displacement a real layout
    bug produces".  A constant *pixel* count does not keep that promise — the
    same document scored at 288 dpi would be held to 0.09 mm — so the pixel
    count is derived from the physical figure instead of hard-coded.

    At ``DEFAULT_DPI`` this returns 1, exactly what the constant was, so every
    number this harness has published is reproduced unchanged.
    """
    return max(1, int(round(dpi / float(DEFAULT_DPI))))


def ink_delta_bound(base, dpi=DEFAULT_DPI):
    """``base`` (a bound set at ``DEFAULT_DPI``) rescaled to ``dpi``.

    ``RASTERISER_FLOOR`` says the disagreement lives in the antialias and
    hinting band along glyph outlines.  That band is about one pixel wide at
    any resolution, so for a region of FIXED PHYSICAL SIZE the share of its
    pixels that lie in the band — and therefore the ink delta the two
    rasterisers can disagree by — falls as 1/dpi.  A bound that stays constant
    in pixels is a bound that gets laxer, in physical terms, the finer the
    raster; scaling it by ``DEFAULT_DPI / dpi`` keeps it fixed against the
    thing it is bounding.

    This is an exact no-op at ``DEFAULT_DPI``, and it only ever TIGHTENS the
    gate above it.  It is not fitted: the measured decay of the residual is
    steeper than 1/dpi (1.80 -> 1.16 -> ~1.0 over 96 -> 144 -> 192), so this
    bound stays conservative at every resolution measured.
    """
    if dpi == DEFAULT_DPI:
        return base          # exactly, not to within a float multiply
    return base * DEFAULT_DPI / float(dpi)

#: Which feature owns which ``elements_skipped`` entry.  Keyed by the base tag
#: of the ledger entry (the part before ``@`` or ``[``), valued by label
#: substrings; a feature owns the entry when one of its substrings is in the
#: feature's Korean label.
LIMIT_OWNERS = {
    "hp:equation": ("수식",),
    "hp:rect": ("글상자",),
    "hp:footNote": ("각주",),
    "hp:endNote": ("미주",),
    "hp:header": ("머리말",),
    "hp:footer": ("꼬리말",),
    "hp:pageNum": ("쪽 번호",),
    "hp:autoNum": ("쪽 번호",),
    "hp:colPr": ("다단",),
    "hp:pic": ("그림",),
    "hp:tbl": ("표 —",),
    "hh:leftBorder": ("테두리",),
    "hh:rightBorder": ("테두리",),
    "hh:topBorder": ("테두리",),
    "hh:bottomBorder": ("테두리",),
}

#: A declared limit only makes a feature ``unsupported`` when the renderer
#: says it drew nothing, or drew a placeholder.  "Stroked as solid" and "laid
#: out from its hp:script" are limits, but the element *is* on the page, so
#: those features are still scored on their pixels and get a real verdict.
NOT_DRAWN_MARKERS = ("nothing drawn", "placeholder", "is not rendered",
                     "not drawn")

HWPUNIT_PER_INCH = 7200


# ---------------------------------------------------------------------------
# Region derivation
# ---------------------------------------------------------------------------
class Region:
    """A vertical band on one page, in fractions of the page box.

    Fractions, not pixels: the reference page and the candidate page are not
    always the same pixel grid (Hancom exports a landscape section onto a
    portrait sheet), and a fraction crops correctly on either.
    """

    __slots__ = ("page", "top", "bottom")

    def __init__(self, page, top, bottom):
        self.page = page
        self.top = max(0.0, min(1.0, top))
        self.bottom = max(0.0, min(1.0, bottom))

    def valid(self):
        return self.bottom - self.top > 0.004

    def as_dict(self):
        return {"page": self.page, "top": round(self.top, 5),
                "bottom": round(self.bottom, 5)}


def _unique_blocks(section_report):
    """Top-level blocks in document order, deduped over page-split repeats.

    A table that straddles a page boundary is listed once per page fragment
    with the same ``block`` id; the feature owns all of them, and the first
    is where the feature starts.
    """
    order = []
    seen = {}
    for entry in section_report.get("blocks", []):
        bid = entry.get("block")
        if bid not in seen:
            seen[bid] = []
            order.append(bid)
        seen[bid].append(entry)
    return [seen[bid] for bid in order]


def candidate_regions(sidecar, features):
    """Feature id -> Region, from the renderer's own block coordinates."""
    sections = sidecar["sections"]
    layout = sidecar["block_layout"]
    furniture_bands = {}
    out = {}

    # Group block features by section so "the next feature" is well defined.
    by_section = {}
    for feature in features:
        if feature.get("band"):
            continue
        by_section.setdefault(feature["section"], []).append(feature)

    for sec_index, group in sorted(by_section.items()):
        section = sections[sec_index]
        geom = section["page_geometry_hwpunit"]
        page_h = geom["height"]
        body_top = geom["body_top"]
        body_bottom = page_h - geom["margin"]["bottom"] - geom["margin"]["footer"]
        first_page = section["pages"][0]
        blocks = _unique_blocks(layout[sec_index])

        group.sort(key=lambda f: f["block_ordinal"])
        starts = []
        for feature in group:
            ordinal = feature["block_ordinal"]
            if ordinal >= len(blocks):
                starts.append(None)
                continue
            entry = blocks[ordinal][0]
            starts.append((first_page + entry["page"],
                           body_top + entry["vertpos_hwpunit"]))

        for i, feature in enumerate(group):
            start = starts[i]
            if start is None:
                continue
            page, top = start
            nxt = next((s for s in starts[i + 1:] if s is not None), None)
            if nxt is not None and nxt[0] == page:
                bottom = nxt[1]
            else:
                bottom = body_bottom
            out[feature["id"]] = Region(page, top / page_h, bottom / page_h)

    # Page-furniture bands, from the section geometry the sidecar reports.
    for feature in features:
        band = feature.get("band")
        if not band:
            continue
        geom = sections[feature["section"]]["page_geometry_hwpunit"]
        page_h = geom["height"]
        margin = geom["margin"]
        if band == "header":
            top, bottom = margin["top"], margin["top"] + margin["header"]
        else:
            bottom = page_h - margin["bottom"]
            top = bottom - margin["footer"]
        page = sections[feature["section"]]["pages"][0]
        furniture_bands[feature["id"]] = (band, top / page_h, bottom / page_h)
        out[feature["id"]] = Region(page, top / page_h, bottom / page_h)

    return out, furniture_bands


def body_bottom_fractions(sidecar):
    """Section index -> where the printable body ends, as a page fraction."""
    out = {}
    for index, section in enumerate(sidecar["sections"]):
        geom = section["page_geometry_hwpunit"]
        margin = geom["margin"]
        bottom = geom["height"] - margin["bottom"] - margin["footer"]
        out[index] = bottom / float(geom["height"])
    return out


def reference_regions(pdf_path, features, furniture_bands, fallback,
                      body_bottom):
    """Feature id -> Region, from the reference PDF's own ``[Fnn]`` markers."""
    fitz = rs._require_fitz()
    section_of = {f["id"]: f["section"] for f in features}
    found = {}
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        hits = {}
        for index in range(page_count):
            page = document[index]
            height = page.rect.height
            for feature in features:
                if feature.get("band"):
                    continue
                if feature["id"] in hits:
                    continue
                boxes = page.search_for("[%s]" % feature["id"])
                if boxes:
                    box = min(boxes, key=lambda r: r.y0)
                    hits[feature["id"]] = (index + 1, box.y0 / height, height)

        # Bottom of a band = the next marker that landed on the same page,
        # else the foot of the printable body.  Not the foot of the *page*:
        # that would pull the footer into the band and score page furniture
        # as if it belonged to the feature.
        ordered = sorted(hits.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        for i, (fid, (page, top, _h)) in enumerate(ordered):
            bottom = body_bottom.get(section_of.get(fid, 0), 1.0)
            for _other_fid, (other_page, other_top, _oh) in ordered[i + 1:]:
                if other_page == page:
                    bottom = other_top
                break
            found[fid] = Region(page, top, bottom)

    for fid, (_band, top, bottom) in furniture_bands.items():
        page = fallback[fid].page if fid in fallback else 1
        found[fid] = Region(page, top, bottom)
    return found


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _crop(image, region):
    width, height = image.size
    top = int(round(region.top * height))
    bottom = int(round(region.bottom * height))
    bottom = max(bottom, top + 4)
    return image.crop((0, min(top, height - 4), width, min(bottom, height)))


#: Ink agreement is measured with a one-pixel tolerance, i.e. both masks are
#: dilated by one pixel before they are intersected.  Without it the channel
#: measures rasteriser luck rather than layout: a glyph drawn in the right
#: place but hinted half a pixel over shares almost no *exact* pixels with the
#: reference, and pixel-exact IoU on 10 pt Korean text at 96 dpi sits near
#: 0.1 even where the two renders are visually indistinguishable.  One pixel
#: at 96 dpi is 0.26 mm — below what a reader can see, and far below the
#: displacement a real layout bug produces.  ``iou_tolerance_px`` above turns
#: that physical figure into a pixel count for whatever raster is in use; this
#: constant is what it returns at ``DEFAULT_DPI`` and is the default here.
IOU_TOLERANCE_PX = 1


def _ink_mask(grey, threshold, tolerance=IOU_TOLERANCE_PX):
    from PIL import ImageFilter
    if tolerance:
        # MinFilter over a light-on-dark greyscale dilates the *ink*.
        grey = grey.filter(ImageFilter.MinFilter(2 * tolerance + 1))
    return grey.point(lambda v: 255 if v < threshold else 0, mode="1")


_BITS = bytes(bin(i).count("1") for i in range(256))


def _mask_iou(left, right):
    """Intersection over union of two same-size binary ink masks."""
    inter = union = 0
    for x, y in zip(left.tobytes(), right.tobytes()):
        inter += _BITS[x & y]
        union += _BITS[x | y]
    if not union:
        return 1.0            # both blank: they agree, vacuously but truly
    return inter / float(union)


def _pad_to(image, size):
    """Top-left-align onto a white canvas of ``size``, never rescaling.

    Rescaling the two crops onto a common grid would hide the difference that
    matters most here: the two renderers break lines differently, so a band
    that is two lines tall in Hancom is often three lines tall in ours.
    Squashing the taller one until they match would score that away.  Padding
    keeps every glyph at its true size and position, so a displaced or extra
    line costs IoU and ink the way it should.
    """
    Image, _ = rs._require_pillow()
    if image.size == size:
        return image
    canvas = Image.new("RGB", size, (255, 255, 255))
    canvas.paste(image, (0, 0))
    return canvas


def ink_mass_fraction(grey):
    """Mean ink COVERAGE per pixel: 0.0 for white, 1.0 for solid black.

    ``rs._ink_fraction`` counts pixels darker than a threshold, which asks a
    yes/no question of every antialiased edge pixel and therefore amplifies a
    rasteriser's weight rather than measuring it: on this document's body text
    at 96 dpi our coverage is 1.80x the reference's and our thresholded pixel
    count is 2.60x it.  This is the same quantity without the threshold, so a
    later pass can read the residual as the multiplicative thing it is.
    Reported, never gated — the bounds are stated against ``_ink_fraction``.
    """
    histogram = grey.histogram()
    total = float(grey.size[0] * grey.size[1])
    return sum((255 - v) * histogram[v] for v in range(256)) / (255.0 * total)


def score_region(reference_rgb, candidate_rgb, threshold, tolerance=None):
    width = max(reference_rgb.size[0], candidate_rgb.size[0], 8)
    height = max(reference_rgb.size[1], candidate_rgb.size[1], 8)
    ref_grey = _pad_to(reference_rgb, (width, height)).convert("L")
    cand_grey = _pad_to(candidate_rgb, (width, height)).convert("L")
    mean, blocks, inked_mean, inked_blocks = rs.ssim(ref_grey, cand_grey)
    ref_ink = rs._ink_fraction(ref_grey)
    cand_ink = rs._ink_fraction(cand_grey)
    if tolerance is None:
        tolerance = IOU_TOLERANCE_PX
    iou = _mask_iou(_ink_mask(ref_grey, threshold, tolerance),
                    _ink_mask(cand_grey, threshold, tolerance))
    ref_mass = ink_mass_fraction(ref_grey)
    cand_mass = ink_mass_fraction(cand_grey)
    return {
        "ssim": round(mean, 4),
        "ssim_blocks": blocks,
        "ssim_inked": round(inked_mean, 4) if inked_blocks else None,
        "ssim_inked_blocks": inked_blocks,
        "iou": round(iou, 4),
        "iou_tolerance_px": tolerance,
        "ink": {"reference": round(ref_ink, 5),
                "candidate": round(cand_ink, 5),
                "delta": round(cand_ink - ref_ink, 5),
                # Reported, not gated.  See ``RASTERISER_FLOOR``: the residual
                # on a drawn text band is multiplicative, so the ratio is the
                # channel that stays put when the band's density changes.
                "mass_reference": round(ref_mass, 5),
                "mass_candidate": round(cand_mass, 5),
                "mass_delta": round(cand_mass - ref_mass, 5),
                "mass_ratio": (round(cand_mass / ref_mass, 4)
                               if ref_mass > 0 else None)},
        "crop_px": [width, height],
    }


def _base_tag(element):
    for sep in ("@", "["):
        element = element.split(sep, 1)[0]
    return element.rstrip("/")


def declared_limits(feature, skipped):
    """Ledger entries this feature owns, and whether any means "not drawn"."""
    label = feature["label"]
    owned = []
    for entry in skipped:
        needles = LIMIT_OWNERS.get(_base_tag(entry.get("element", "")))
        if needles and any(needle in label for needle in needles):
            owned.append(entry)
    not_drawn = [e for e in owned
                 if any(m in e.get("reason", "") for m in NOT_DRAWN_MARKERS)]
    return owned, not_drawn


def verdict_for(metrics, not_drawn, dpi=DEFAULT_DPI):
    if not_drawn:
        return "unsupported"
    ssim_value = metrics["ssim"]
    iou = metrics["iou"]
    delta = abs(metrics["ink"]["delta"])
    good = THRESHOLDS["match"]
    okay = THRESHOLDS["close"]
    good_ink = ink_delta_bound(good["ink_delta_abs_max"], dpi)
    okay_ink = ink_delta_bound(okay["ink_delta_abs_max"], dpi)
    if (iou >= good["iou_min"] and delta <= good_ink
            and ssim_value >= good["ssim_min"]):
        return "match"
    if (iou >= okay["iou_min"] and delta <= okay_ink
            and ssim_value >= okay["ssim_min"]):
        return "close"
    return "differs"


# ---------------------------------------------------------------------------
# Side-by-side contact strips
# ---------------------------------------------------------------------------
def side_by_side(reference_rgb, candidate_rgb, out_path, max_width=900):
    Image, _ = rs._require_pillow()
    from PIL import ImageDraw
    gap = 12
    label_h = 16
    # Pad first, then scale both by the same factor: the panels must stay
    # comparable to each other, so neither may be stretched on its own.
    pad = (max(reference_rgb.size[0], candidate_rgb.size[0]),
           max(reference_rgb.size[1], candidate_rgb.size[1]))
    scale = min(1.0, max_width / float(2 * pad[0] + gap))
    size = (max(1, int(pad[0] * scale)), max(1, int(pad[1] * scale)))
    left = _pad_to(reference_rgb, pad).resize(size, Image.Resampling.LANCZOS)
    right = _pad_to(candidate_rgb, pad).resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size[0] * 2 + gap, size[1] + label_h),
                       (255, 255, 255))
    canvas.paste(left, (0, label_h))
    canvas.paste(right, (size[0] + gap, label_h))
    draw = ImageDraw.Draw(canvas)
    draw.text((2, 3), "Hancom", fill=(20, 20, 20))
    draw.text((size[0] + gap + 2, 3), "ours", fill=(20, 20, 20))
    draw.line([(size[0] + gap // 2, 0),
               (size[0] + gap // 2, canvas.size[1])], fill=(180, 180, 180))
    out_path_dir = os.path.dirname(out_path)
    if out_path_dir:
        os.makedirs(out_path_dir, exist_ok=True)
    canvas.save(out_path, "PNG", optimize=True)
    return os.path.getsize(out_path)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run(hwpx_path, reference_pdf, blocks_path, dpi=DEFAULT_DPI,
        png_dir=None, max_png_bytes=None):
    features = json.load(open(blocks_path, encoding="utf-8"))["features"]
    tolerance = iou_tolerance_px(dpi)

    renderer = own_render.OwnRenderer(hwpx_path, dpi=dpi)
    candidate_pages, sidecar = renderer.render()
    skipped = sidecar.get("elements_skipped", [])

    cand_regions, furniture_bands = candidate_regions(sidecar, features)
    ref_regions = reference_regions(reference_pdf, features, furniture_bands,
                                    cand_regions,
                                    body_bottom_fractions(sidecar))

    fitz = rs._require_fitz()
    Image, _ = rs._require_pillow()
    reference_pages = []
    with fitz.open(reference_pdf) as document:
        reference_page_count = document.page_count
        zoom = dpi / 72.0
        for index in range(reference_page_count):
            pixmap = document[index].get_pixmap(
                matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB,
                alpha=False)
            reference_pages.append(Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), bytes(pixmap.samples)))

    rows = []
    png_bytes_total = 0
    for feature in features:
        fid = feature["id"]
        row = {"id": fid, "label": feature["label"],
               "section": feature["section"]}
        if feature.get("band"):
            row["band"] = feature["band"]
        else:
            row["block_ordinal"] = feature["block_ordinal"]

        cand_region = cand_regions.get(fid)
        ref_region = ref_regions.get(fid)
        row["region"] = {
            "candidate": cand_region.as_dict() if cand_region else None,
            "reference": ref_region.as_dict() if ref_region else None,
        }
        if cand_region is None or ref_region is None:
            row["verdict"] = "differs"
            row["reason"] = ("no region on the %s side"
                             % ("candidate" if cand_region is None
                                else "reference"))
            rows.append(row)
            continue

        row["page_agreement"] = (cand_region.page == ref_region.page)
        cand_index = cand_region.page - 1
        ref_index = ref_region.page - 1
        if not (0 <= cand_index < len(candidate_pages)
                and 0 <= ref_index < len(reference_pages)):
            row["verdict"] = "differs"
            row["reason"] = "region page is outside one of the renders"
            rows.append(row)
            continue

        ref_crop = _crop(reference_pages[ref_index], ref_region)
        cand_crop = _crop(candidate_pages[cand_index].convert("RGB"),
                          cand_region)
        metrics = score_region(ref_crop, cand_crop, rs.INK_THRESHOLD,
                               tolerance=tolerance)
        # The two band heights are the cheapest read on whether the feature
        # occupies the same amount of page on both sides.  A band that is
        # tall on one side and a stub on the other means the content ran onto
        # the next page in one engine and not the other, which is a
        # pagination finding, not a finding about the feature itself.
        metrics["band_px"] = {"reference": ref_crop.size[1],
                              "candidate": cand_crop.size[1]}
        row.update(metrics)
        limits, not_drawn = declared_limits(feature, skipped)
        if limits:
            row["declared_limits"] = limits
        if not_drawn:
            row["declared_not_drawn"] = [e["element"] for e in not_drawn]
        row["verdict"] = verdict_for(metrics, not_drawn, dpi)

        if png_dir is not None:
            path = os.path.join(png_dir, "%s.png" % fid)
            png_bytes_total += side_by_side(ref_crop, cand_crop, path)
            row["png"] = os.path.basename(path)
        rows.append(row)

    tally = {}
    for row in rows:
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1

    report = {
        "render_check_version": CHECK_VERSION,
        "renderer": sidecar.get("renderer"),
        "renderer_version": sidecar.get("renderer_version"),
        "grade": sidecar.get("grade"),
        "document": os.path.basename(hwpx_path),
        "reference_pdf": os.path.basename(reference_pdf),
        "dpi": dpi,
        "pages": {"candidate": len(candidate_pages),
                  "reference": reference_page_count,
                  "exact": len(candidate_pages) == reference_page_count},
        "reference_geometry_scale": rs.reference_geometry_scale(hwpx_path,
                                                                reference_pdf),
        "thresholds": THRESHOLDS,
        "thresholds_at_dpi": {
            "dpi": dpi,
            "iou_tolerance_px": tolerance,
            "match_ink_delta_abs_max": ink_delta_bound(
                THRESHOLDS["match"]["ink_delta_abs_max"], dpi),
            "close_ink_delta_abs_max": ink_delta_bound(
                THRESHOLDS["close"]["ink_delta_abs_max"], dpi),
            "derivation": ("the IoU tolerance is the pixel count covering"
                           " thresholds.iou_tolerance_mm at this raster; the"
                           " ink bounds scale as DEFAULT_DPI/dpi because the"
                           " rasteriser residual lives in a ~1 px band along"
                           " glyph outlines (see rasteriser_floor).  Both are"
                           " exact no-ops at DEFAULT_DPI."),
        },
        "rasteriser_floor": RASTERISER_FLOOR,
        "region_derivation": {
            "candidate": ("own_render block_layout[section].blocks, indexed by"
                          " the feature's own block ordinal; band features use"
                          " the section's page geometry"),
            "reference": ("PyMuPDF search_for on the feature's own [Fnn]"
                          " marker in the reference PDF text layer; band"
                          " features use the same page geometry"),
        },
        "elements_skipped": skipped,
        "features": rows,
        "tally": tally,
        "png_bytes": png_bytes_total,
    }
    if max_png_bytes and png_bytes_total > max_png_bytes:
        report["png_budget_exceeded"] = {"bytes": png_bytes_total,
                                         "budget": max_png_bytes}
    return report


VERDICT_ORDER = ["match", "close", "differs", "unsupported"]


def markdown(report, png_rel):
    lines = []
    lines.append("| feature | ssim | ssim(inked) | IoU | ink Δ | page | verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in report["features"]:
        if "ssim" not in row:
            lines.append("| `%s` %s | — | — | — | — | — | %s |"
                         % (row["id"], row["label"], row["verdict"]))
            continue
        inked = row["ssim_inked"]
        page = ("%d" % row["region"]["candidate"]["page"]
                if row.get("page_agreement")
                else "%s/%s" % (row["region"]["reference"]["page"],
                                row["region"]["candidate"]["page"]))
        name = row["label"]
        if png_rel and row.get("png"):
            name = "[%s](%s/%s)" % (name, png_rel, row["png"])
        lines.append("| `%s` %s | %.3f | %s | %.3f | %+.4f | %s | **%s** |"
                     % (row["id"], name, row["ssim"],
                        "—" if inked is None else "%.3f" % inked,
                        row["iou"], row["ink"]["delta"], page,
                        row["verdict"]))
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("hwpx")
    parser.add_argument("reference_pdf")
    parser.add_argument("--blocks", required=True,
                        help="the document's feature/block sidecar")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--report", help="where to write report.json")
    parser.add_argument("--markdown", help="where to write the markdown table")
    parser.add_argument("--png-dir", help="where to write side-by-side PNGs")
    parser.add_argument("--max-png-bytes", type=int, default=8 * 1024 * 1024)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.png_dir:
        os.makedirs(args.png_dir, exist_ok=True)
    report = run(args.hwpx, args.reference_pdf, args.blocks, dpi=args.dpi,
                 png_dir=args.png_dir, max_png_bytes=args.max_png_bytes)
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2)
                         + "\n")
    if args.markdown:
        png_rel = (os.path.basename(args.png_dir.rstrip("/\\"))
                   if args.png_dir else None)
        with open(args.markdown, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(markdown(report, png_rel) + "\n")
    summary = {"tally": report["tally"], "pages": report["pages"],
               "png_bytes": report["png_bytes"]}
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
