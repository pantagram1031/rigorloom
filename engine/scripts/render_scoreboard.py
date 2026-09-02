#!/usr/bin/env python3
"""render_scoreboard.py — measure Rigorloom's own renderer against Hancom.

WHAT THIS IS
    The groundwork half of ``render_cert`` certification (endgame plan E2.4).
    ``pipeline/scripts/render_cert.py`` is the *certification* path: it drives a
    renderer binary, compares PDF against PDF on three channels (page count,
    unique-word anchors, raster changed-channel ratio), and issues a signed
    certificate against an operator-ratified threshold set.  It cannot score
    this renderer yet, because ``own_render.render_to_pdf`` writes raster pages
    with no text layer, so the word-anchor channel matches nothing.

    This script closes the measurement gap without pretending to certify.  It
    rasterises the immutable Hancom reference PDF to exactly the pixel grid the
    own renderer drew, and reports per-page structural metrics plus text-line
    box IoU — the two numbers that actually move when layout improves.  It
    emits a scoreboard JSON whose ``grade`` stays ``own-uncertified`` and whose
    thresholds are marked ``ratified: false`` until the operator says otherwise.

    Nothing here invokes Hancom.  The reference PDFs under
    ``tests/corpus/forms/render/`` are immutable inputs produced by the
    operator's reference facility; this script only reads them.

METRICS, AND EXACTLY WHAT EACH ONE MEANS

  ``ssim``
      Structural similarity, Wang et al. 2004, on 8-bit greyscale.
      **scikit-image is not installed in this environment**, so this is a
      documented in-repo implementation, not ``skimage.metrics.ssim``, and it
      differs from it in one stated way: the window is a *non-overlapping*
      8x8 box rather than an 11x11 Gaussian sliding window.  Constants are the
      paper's: ``C1 = (0.01*L)^2``, ``C2 = (0.03*L)^2``, ``L = 255``.  The
      block variant is the standard cheap form of the same statistic; it is
      slightly more forgiving of sub-block misregistration and slightly
      harsher at block boundaries.  Reported as ``ssim_variant`` in the
      output so a later run against real scikit-image is comparable rather
      than silently swapped in.

  ``changed_channel_ratio``
      The *same* definition ``render_cert._compare_rasters`` uses: the
      fraction of RGB byte channels that differ at all.  Included so a number
      from this scoreboard can be read against a render_cert threshold
      directly.  It is a brutal metric for a font-substituting renderer — a
      one-pixel glyph shift changes every channel it touches — which is
      precisely why SSIM carries the signal here.

  ``ink``
      Fraction of pixels darker than 128.  ``delta`` is candidate minus
      reference: positive means we draw more ink than Hancom did (text too
      wide / too heavy), negative means we draw less (dropped elements).

  ``text_line_iou``
      Text *line boxes*, paired one-to-one between the reference PDF's
      ``page.get_text("dict")`` lines and the own renderer's own line-box
      record (``line_boxes`` in the sidecar), greedy by ascending centre
      distance with a cap of a quarter page height.  Reports mean/median IoU
      over the pairs and the unpaired counts on both sides.  A pair with IoU
      0 still counts as a pair — dropping it would flatter the mean.

THE REFERENCE SET IS NOT UNIFORMLY 1:1 — MEASURED, NOT ASSUMED
    Three of the ten corpus reference PDFs (``gianmun-byeolji-1ho``,
    ``gianmun-byeolji-2ho``, ``nrf-gyeolgwa-bogoseo-yangsik``) were produced at
    ~0.707 = 1/sqrt(2) of the document's declared geometry: their text is drawn
    at 70.7% of the ``hh:charPr@height`` the file declares, anchored near the
    top-left of an otherwise A4 page.  The documents' own embedded
    ``Preview/PrvImage.png`` shows the content filling the page, so the
    documents are right and those three reference *renders* carry a print
    reduction.

    Comparing a 1:1 render against a 0.707 reference measures the reference
    facility, not the renderer.  ``reference_geometry_scale`` therefore
    estimates the scale from the reference's own span sizes against the
    document's declared character heights, and a form whose scale is more than
    ``SCALE_TOLERANCE`` off 1.0 is marked ``comparable: false`` and its verdict
    is **blocked** rather than passed or failed.  Its metrics are still
    reported, because a before/after delta on a fixed misaligned pair still
    shows movement — but only as a relative number, flagged as such.

CALIBRATION HONESTY
    Every number here depends on which fonts this machine has installed,
    because the renderer resolves declared faces against the system font
    directory and falls back where it cannot.  The scoreboard therefore
    embeds the render sidecar's ``fonts`` block verbatim.  A number measured
    on a machine with Hancom's faces installed is NOT the number a bare
    Windows install produces, and the scoreboard says so in ``caveats``.

CLI
    python render_scoreboard.py FORM.hwpx REFERENCE.pdf --out DIR
        [--dpi 144] [--label before]
    python render_scoreboard.py --corpus --out DIR      # every paired form

exit 0: scored.  exit 2: usage/input error.  exit 3: a dependency is missing.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli_io import utf8_stdio  # noqa: E402
import own_render  # noqa: E402

SCOREBOARD_VERSION = "2"
DEFAULT_DPI = 144
# A reference whose geometry scale is further than this from 1.0 is not a
# render of the same page the document declares.  5% is wide enough to absorb
# the hh:ratio spread the estimator cannot attribute per span, and far tighter
# than the 29% the three known-reduced references carry.
SCALE_TOLERANCE = 0.05
SSIM_BLOCK = 8
SSIM_L = 255.0
SSIM_C1 = (0.01 * SSIM_L) ** 2
SSIM_C2 = (0.03 * SSIM_L) ** 2
INK_THRESHOLD = 128
# A block whose mean is below this carries ink.  254/255 on a white ground is
# roughly one fully black pixel in a 64-pixel block, i.e. the faintest mark a
# renderer can actually make.
SSIM_INK_BLOCK_MEAN = 254.0

# Proposed, NOT ratified.  These are a REGRESSION FLOOR, not a fidelity bar:
# each bound sits just below the worst value the seven comparable corpus forms
# measure today, so a renderer change that makes any of them worse fails and
# the current state passes.  Clearing this floor says only "no worse than
# 2026-09"; it does not say the render is faithful.  ``FIDELITY_TARGET`` below
# is what certification should eventually demand, and nothing today reaches it.
PROPOSED_THRESHOLDS = {
    "page_count_exact": True,
    "ssim_min": 0.40,
    "ssim_inked_min": -0.10,
    "text_line_iou_mean_min": 0.20,
    "text_line_pair_rate_min": 0.40,
    "ink_delta_abs_max": 0.05,
    "ratified": False,
    "kind": "regression_floor",
    "rationale": (
        "measured worst-of-seven on the comparable corpus forms at 144 dpi: "
        "ssim_min 0.4867 (jumin), ssim_inked_min -0.0224 (saeopja), "
        "text_line_iou_mean 0.2470 (kstartup), text_line_pair_rate 0.4490 "
        "(admrul), ink_delta_abs_max 0.0375 (kstartup). Each bound is set "
        "below (or above, for the max) that worst value with a little "
        "headroom. raster changed_channel_ratio carries NO threshold: a "
        "font-substituting renderer cannot reach a meaningful one, and a gate "
        "nobody can pass is not a gate."
    ),
}

# What a per-class `own-certified` grade should actually require.  Recorded so
# the distance is visible and nothing here reads as "nearly certified"; NOT
# evaluated, because failing every form against an aspiration is noise.
FIDELITY_TARGET = {
    "page_count_exact": True,
    "ssim_min": 0.95,
    "ssim_inked_min": 0.70,
    "text_line_iou_mean_min": 0.80,
    "text_line_pair_rate_min": 0.95,
    "ink_delta_abs_max": 0.002,
    "note": ("not evaluated. The gap to it is the honest measure of how far "
             "tier 3 is from Hancom, and the largest remaining term is "
             "sub-pixel glyph registration, not any single unimplemented "
             "element."),
}


class ScoreboardUnavailable(RuntimeError):
    """A dependency this measurement needs is not installed."""


def _require_fitz():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:
        raise ScoreboardUnavailable(
            "PyMuPDF is required to rasterise the Hancom reference PDF"
        ) from exc
    return fitz


def _require_pillow():
    try:
        from PIL import Image, ImageMath  # noqa: F401
    except ImportError as exc:
        raise ScoreboardUnavailable("Pillow is required") from exc
    return Image, ImageMath


def _multiply_f(x, y):
    """Elementwise product of two mode-``F`` images.

    ``ImageChops`` refuses mode ``F`` and ``ImageMath.eval`` was renamed in
    Pillow 10.3 (``lambda_eval`` / ``unsafe_eval``), so both spellings are
    handled rather than pinning a Pillow minor.
    """
    _, ImageMath = _require_pillow()
    if hasattr(ImageMath, "lambda_eval"):
        return ImageMath.lambda_eval(lambda a: a["x"] * a["y"], x=x, y=y)
    return ImageMath.eval("x*y", x=x, y=y)  # pragma: no cover - old Pillow


def _block_means(image_f, blocks_wide, blocks_high):
    """Per-block arithmetic mean, computed by Pillow's BOX downsample.

    ``Image.resize(..., BOX)`` on an exact integer factor *is* the block mean,
    so the 2-megapixel pass runs in C and only the per-block arithmetic
    (~30k values) runs in Python.
    """
    Image, _ = _require_pillow()
    small = image_f.resize((blocks_wide, blocks_high), Image.Resampling.BOX)
    # Pillow 12 deprecates Image.getdata() in favour of get_flattened_data();
    # both spellings are handled so this does not pin a Pillow minor.
    flattened = getattr(small, "get_flattened_data", None)
    return list(flattened() if flattened is not None else small.getdata())


def ssim(reference_grey, candidate_grey, block=SSIM_BLOCK):
    """Block SSIM over two same-size mode-``L`` images.  See module docstring.

    Returns ``(mean_ssim, block_count, inked_mean, inked_blocks)``.

    ``inked_mean`` is the mean over blocks where either image has ink — a
    block mean below ``SSIM_INK_BLOCK_MEAN``.  It exists because these are
    government forms: most of a page is paper, every blank block scores ~1.0
    on both sides, and the plain mean is therefore dominated by agreement
    about emptiness.  Measured on this corpus, a change that moves the plain
    mean by 0.004 moves the inked mean by an order of magnitude more.  Both
    are reported; neither is presented as the other.
    """
    if reference_grey.size != candidate_grey.size:
        raise ValueError("ssim operands must be the same size")
    width, height = reference_grey.size
    bw, bh = width // block, height // block
    if bw < 1 or bh < 1:
        return None, 0, None, 0
    box = (0, 0, bw * block, bh * block)
    ref = reference_grey.crop(box)
    cand = candidate_grey.crop(box)

    ref_f = ref.convert("F")
    cand_f = cand.convert("F")
    # A mode-"L" point() with an "F" target builds a 256-entry LUT once, so the
    # squares cost one table lookup per pixel rather than a Python multiply.
    ref_sq = ref.point(lambda v: float(v) * float(v), "F")
    cand_sq = cand.point(lambda v: float(v) * float(v), "F")
    cross = _multiply_f(ref_f, cand_f)

    mu_x = _block_means(ref_f, bw, bh)
    mu_y = _block_means(cand_f, bw, bh)
    m_xx = _block_means(ref_sq, bw, bh)
    m_yy = _block_means(cand_sq, bw, bh)
    m_xy = _block_means(cross, bw, bh)

    total = 0.0
    inked_total = 0.0
    inked_blocks = 0
    for i in range(bw * bh):
        ux, uy = mu_x[i], mu_y[i]
        vx = m_xx[i] - ux * ux
        vy = m_yy[i] - uy * uy
        cxy = m_xy[i] - ux * uy
        numerator = (2 * ux * uy + SSIM_C1) * (2 * cxy + SSIM_C2)
        denominator = (ux * ux + uy * uy + SSIM_C1) * (vx + vy + SSIM_C2)
        value = numerator / denominator if denominator else 1.0
        total += value
        if ux < SSIM_INK_BLOCK_MEAN or uy < SSIM_INK_BLOCK_MEAN:
            inked_total += value
            inked_blocks += 1
    return (total / (bw * bh), bw * bh,
            (inked_total / inked_blocks) if inked_blocks else None,
            inked_blocks)


def _changed_channel_ratio(reference_rgb, candidate_rgb):
    """render_cert's raster channel, byte for byte, on same-size RGB images."""
    left = reference_rgb.tobytes()
    right = candidate_rgb.tobytes()
    overlap = min(len(left), len(right))
    changed = sum(a != b for a, b in zip(left[:overlap], right[:overlap]))
    changed += abs(len(left) - len(right))
    total = max(len(left), len(right))
    return (changed / total) if total else 0.0


def _ink_fraction(grey):
    histogram = grey.histogram()
    dark = sum(histogram[:INK_THRESHOLD])
    return dark / float(grey.size[0] * grey.size[1])


def _reference_pages(pdf_path, page_size_px, page_count):
    """Rasterise the reference onto exactly the candidate's pixel grid.

    The reference is a real A4 page at 595x841/842 pt; the candidate's pixel
    size comes from ``hp:pagePr`` at the render DPI.  Scaling the reference to
    the candidate grid (rather than the other way round) keeps the candidate
    pixels untouched, so a metric change can only come from the renderer.
    """
    fitz = _require_fitz()
    Image, _ = _require_pillow()
    target_w, target_h = page_size_px
    pages = []
    with fitz.open(pdf_path) as document:
        for index in range(min(document.page_count, page_count)):
            page = document[index]
            rect = page.rect
            matrix = fitz.Matrix(target_w / rect.width, target_h / rect.height)
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB,
                                     alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height),
                                    bytes(pixmap.samples))
            if image.size != (target_w, target_h):
                image = image.resize((target_w, target_h),
                                     Image.Resampling.LANCZOS)
            pages.append(image)
        total = document.page_count
    return pages, total


def _reference_line_boxes(pdf_path, page_size_px):
    """Reference text-line boxes, in the candidate's pixel coordinates."""
    fitz = _require_fitz()
    target_w, target_h = page_size_px
    per_page = []
    with fitz.open(pdf_path) as document:
        for page in document:
            sx = target_w / page.rect.width
            sy = target_h / page.rect.height
            boxes = []
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    x0, y0, x1, y1 = line["bbox"]
                    text = "".join(s.get("text", "")
                                   for s in line.get("spans", []))
                    if not text.strip():
                        continue
                    boxes.append({
                        "x0": x0 * sx, "y0": y0 * sy,
                        "x1": x1 * sx, "y1": y1 * sy,
                    })
            per_page.append(boxes)
    return per_page


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _weighted_median(counter):
    total = sum(counter.values())
    if not total:
        return None
    seen = 0
    for value in sorted(counter):
        seen += counter[value]
        if seen * 2 >= total:
            return value
    return None


def _declared_character_sizes(hwpx_path):
    """Glyph-weighted census of the character heights the document declares.

    Read straight from ``Contents/header.xml`` and the sections rather than
    through ``own_render``'s parsed model, on purpose: this estimator must not
    move when the renderer's model changes, or a before/after comparison would
    be measuring the estimator.  ``hh:ratio`` is folded in because the
    reference PDF's reported span size folds it in too (measured: gianmun's
    ``수신`` is 12 pt declared, ``ratio=97``, reference span size 8.27 =
    12 x 0.97 x 0.7113).
    """
    heights, ratios = {}, {}
    with zipfile.ZipFile(hwpx_path) as archive:
        names = archive.namelist()
        header = next((n for n in names if n.endswith("header.xml")), None)
        if header is None:
            return {}
        root = ET.fromstring(archive.read(header))
        for cp in root.iter():
            if _local(cp.tag) != "charPr":
                continue
            cid = cp.get("id")
            try:
                heights[cid] = int(cp.get("height") or 1000) / 100.0
            except ValueError:
                heights[cid] = 10.0
            for child in cp:
                if _local(child.tag) == "ratio":
                    try:
                        ratios[cid] = int(child.get("hangul") or 100) / 100.0
                    except ValueError:
                        ratios[cid] = 1.0
        census = {}
        for name in sorted(n for n in names
                           if own_render.SECTION_RE.match(n)):
            section = ET.fromstring(archive.read(name))
            for run in section.iter():
                if _local(run.tag) != "run":
                    continue
                text = "".join("".join(t.itertext()) for t in run
                               if _local(t.tag) == "t").strip()
                if not text:
                    continue
                cid = run.get("charPrIDRef")
                size = round(heights.get(cid, 10.0) * ratios.get(cid, 1.0), 2)
                census[size] = census.get(size, 0) + len(text)
    return census


def _reference_character_sizes(pdf_path):
    _require_fitz()
    import fitz
    census = {}
    with fitz.open(pdf_path) as document:
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        size = round(span["size"], 2)
                        census[size] = census.get(size, 0) + len(text)
    return census


def reference_geometry_scale(hwpx_path, pdf_path):
    """Is this reference a 1:1 render of the geometry the document declares?

    Estimator: glyph-weighted median reference span size divided by
    glyph-weighted median declared (height x ratio).  Robust to a few outlier
    runs and needs no pairing between the two documents.
    """
    declared = _declared_character_sizes(hwpx_path)
    reference = _reference_character_sizes(pdf_path)
    dm = _weighted_median(declared)
    rm = _weighted_median(reference)
    scale = (rm / dm) if (dm and rm) else None
    comparable = scale is not None and abs(scale - 1.0) <= SCALE_TOLERANCE
    record = {
        "scale": round(scale, 6) if scale is not None else None,
        "declared_median_pt": dm,
        "reference_median_pt": rm,
        "tolerance": SCALE_TOLERANCE,
        "comparable": comparable,
        "method": ("glyph-weighted median of reference PDF span sizes over "
                   "glyph-weighted median of declared hh:charPr@height x "
                   "hh:ratio"),
    }
    if not comparable:
        record["reason"] = (
            "the reference PDF is not a 1:1 render of the geometry this "
            "document declares; comparing against it measures the reference "
            "facility's print scaling, not the renderer. Metrics below are "
            "RELATIVE ONLY (a before/after delta on this same pair still "
            "shows movement) and the verdict is blocked."
        )
    return record


def _iou(a, b):
    ix0 = max(a["x0"], b["x0"])
    iy0 = max(a["y0"], b["y0"])
    ix1 = min(a["x1"], b["x1"])
    iy1 = min(a["y1"], b["y1"])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(0.0, a["x1"] - a["x0"]) * max(0.0, a["y1"] - a["y0"])
    area_b = max(0.0, b["x1"] - b["x0"]) * max(0.0, b["y1"] - b["y0"])
    union = area_a + area_b - inter
    return (inter / union) if union > 0 else 0.0


def _centre(box):
    return ((box["x0"] + box["x1"]) / 2.0, (box["y0"] + box["y1"]) / 2.0)


def pair_line_boxes(reference_boxes, candidate_boxes, cap):
    """Greedy one-to-one pairing by ascending centre distance.

    Deterministic: candidate pairs are enumerated in a fixed order and sorted
    by ``(distance, reference_index, candidate_index)``, so ties never depend
    on dict or set iteration order.
    """
    pairs = []
    for ri, ref in enumerate(reference_boxes):
        rx, ry = _centre(ref)
        for ci, cand in enumerate(candidate_boxes):
            cx, cy = _centre(cand)
            distance = math.hypot(cx - rx, cy - ry)
            if distance <= cap:
                pairs.append((distance, ri, ci))
    pairs.sort()
    used_ref, used_cand, matched = set(), set(), []
    for distance, ri, ci in pairs:
        if ri in used_ref or ci in used_cand:
            continue
        used_ref.add(ri)
        used_cand.add(ci)
        matched.append({
            "reference_index": ri,
            "candidate_index": ci,
            "centre_distance_px": round(distance, 3),
            "iou": round(_iou(reference_boxes[ri], candidate_boxes[ci]), 6),
        })
    matched.sort(key=lambda m: (m["reference_index"], m["candidate_index"]))
    return matched, len(reference_boxes) - len(used_ref), \
        len(candidate_boxes) - len(used_cand)


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def score_form(hwpx_path, reference_pdf, dpi=DEFAULT_DPI, label=None,
               out_dir=None, stem=None,
               line_layout=own_render.LINE_LAYOUT_AUTO):
    """Render the form and score it against its Hancom reference PDF."""
    Image, _ = _require_pillow()
    hwpx_path = Path(hwpx_path)
    reference_pdf = Path(reference_pdf)
    if not hwpx_path.is_file():
        raise ValueError(f"not a file: {hwpx_path}")
    if not reference_pdf.is_file():
        raise ValueError(f"not a file: {reference_pdf}")

    renderer = own_render.OwnRenderer(hwpx_path, dpi=dpi,
                                      line_layout=line_layout)
    images, sidecar = renderer.render()
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = stem or hwpx_path.stem
        for index, image in enumerate(images, start=1):
            own_render.save_png(image, out_dir / f"{stem}-p{index}.png")

    page_size = tuple(sidecar["page_size_px"])
    ref_pages, ref_page_count = _reference_pages(
        reference_pdf, page_size, len(images))
    ref_lines = _reference_line_boxes(reference_pdf, page_size)
    own_lines = sidecar.get("line_boxes") or []

    cap = page_size[1] / 4.0
    page_records = []
    for index, candidate in enumerate(images):
        if index >= len(ref_pages):
            page_records.append({
                "page": index + 1,
                "scored": False,
                "reason": "reference PDF has no such page",
            })
            continue
        reference = ref_pages[index]
        ref_grey = reference.convert("L")
        cand_grey = candidate.convert("L")
        value, blocks, inked, inked_blocks = ssim(ref_grey, cand_grey)
        ref_ink = _ink_fraction(ref_grey)
        cand_ink = _ink_fraction(cand_grey)
        page_ref_lines = ref_lines[index] if index < len(ref_lines) else []
        page_own_lines = [b for b in own_lines if b.get("page") == index + 1]
        matched, unpaired_ref, unpaired_cand = pair_line_boxes(
            page_ref_lines, page_own_lines, cap)
        ious = [m["iou"] for m in matched]
        page_records.append({
            "page": index + 1,
            "scored": True,
            "ssim": round(value, 6) if value is not None else None,
            "ssim_blocks": blocks,
            "ssim_inked": round(inked, 6) if inked is not None else None,
            "ssim_inked_blocks": inked_blocks,
            "changed_channel_ratio": round(
                _changed_channel_ratio(reference, candidate), 9),
            "ink": {
                "reference": round(ref_ink, 6),
                "candidate": round(cand_ink, 6),
                "delta": round(cand_ink - ref_ink, 6),
            },
            "text_line_iou": {
                "reference_lines": len(page_ref_lines),
                "candidate_lines": len(page_own_lines),
                "pairs": len(matched),
                "unpaired_reference": unpaired_ref,
                "unpaired_candidate": unpaired_cand,
                "mean": round(sum(ious) / len(ious), 6) if ious else None,
                "median": round(_median(ious), 6) if ious else None,
                "pair_rate": round(len(matched) / len(page_ref_lines), 6)
                if page_ref_lines else None,
            },
        })

    scored = [p for p in page_records if p.get("scored")]
    ssims = [p["ssim"] for p in scored if p["ssim"] is not None]
    inked = [p["ssim_inked"] for p in scored if p["ssim_inked"] is not None]
    iou_means = [p["text_line_iou"]["mean"] for p in scored
                 if p["text_line_iou"]["mean"] is not None]
    pair_rates = [p["text_line_iou"]["pair_rate"] for p in scored
                  if p["text_line_iou"]["pair_rate"] is not None]
    ink_deltas = [abs(p["ink"]["delta"]) for p in scored]
    ratios = [p["changed_channel_ratio"] for p in scored]

    summary = {
        "pages_scored": len(scored),
        "page_count": {
            "reference": ref_page_count,
            "candidate": len(images),
            "exact": ref_page_count == len(images),
        },
        "ssim_mean": round(sum(ssims) / len(ssims), 6) if ssims else None,
        "ssim_min": round(min(ssims), 6) if ssims else None,
        "ssim_inked_mean": round(sum(inked) / len(inked), 6) if inked else None,
        "ssim_inked_min": round(min(inked), 6) if inked else None,
        "text_line_iou_mean": round(sum(iou_means) / len(iou_means), 6)
        if iou_means else None,
        "text_line_pair_rate_mean": round(
            sum(pair_rates) / len(pair_rates), 6) if pair_rates else None,
        "ink_delta_abs_max": round(max(ink_deltas), 6) if ink_deltas else None,
        "changed_channel_ratio_mean": round(
            sum(ratios) / len(ratios), 9) if ratios else None,
    }
    geometry = reference_geometry_scale(hwpx_path, reference_pdf)
    verdict = evaluate(summary, PROPOSED_THRESHOLDS, geometry)

    return {
        "scoreboard_version": SCOREBOARD_VERSION,
        "renderer": sidecar["renderer"],
        "renderer_version": sidecar["renderer_version"],
        "grade": sidecar["grade"],
        "grade_meaning": (
            "measured against a Hancom reference render; the grade stays "
            "own-uncertified because the thresholds below are PROPOSED and "
            "not operator-ratified, and because pipeline/scripts/"
            "render_cert.py — the certification path — cannot score this "
            "renderer until it emits a PDF text layer."
        ),
        "label": label,
        "line_layout": sidecar.get("line_layout", {}).get("policy"),
        "line_layout_paragraphs": (
            sidecar.get("line_layout", {}).get("paragraphs")),
        "line_layout_meaning": (
            "which engine laid out the line boxes being scored. auto: the document's own cached hp:lineseg wherever it still describes the text, so this column measures everything EXCEPT the line breaker. computed: every line broken by this renderer, so this column is the honest measure OF the line breaker."),
        "document": hwpx_path.name,
        "reference_pdf": reference_pdf.name,
        "dpi": dpi,
        "page_size_px": list(page_size),
        "ssim_variant": (
            f"block-{SSIM_BLOCK}x{SSIM_BLOCK} non-overlapping, C1={SSIM_C1}, "
            f"C2={SSIM_C2}, L={SSIM_L}; in-repo implementation because "
            "scikit-image is not installed in this environment"
        ),
        "fonts": sidecar.get("fonts"),
        "elements_rendered": sidecar.get("elements_rendered"),
        "reference_geometry_scale": geometry,
        "caveats": [
            "every number here depends on which fonts this machine has "
            "installed; see fonts.faces for what resolved and what was "
            "substituted",
            "changed_channel_ratio is render_cert's raster channel verbatim "
            "and carries no threshold here — see thresholds.rationale",
            "the reference raster is scaled to the candidate's pixel grid, "
            "never the reverse",
        ],
        "thresholds": dict(PROPOSED_THRESHOLDS),
        "fidelity_target": dict(FIDELITY_TARGET),
        "summary": summary,
        "verdict": verdict,
        "pages": page_records,
    }


def evaluate(summary, thresholds, geometry=None):
    """Pass/fail each threshold, with the value that decided it.

    A reference that is not a 1:1 render of the document's declared geometry
    blocks the verdict outright: the checks are still computed and shown, but
    ``pass`` is ``None`` rather than a boolean, because neither answer would
    be about the renderer.
    """
    checks = []

    def add(name, value, ok, bound):
        checks.append({"check": name, "value": value, "bound": bound,
                       "pass": bool(ok)})

    add("page_count_exact", summary["page_count"]["exact"],
        summary["page_count"]["exact"] is True, True)
    for key, bound_key, direction in (
        ("ssim_min", "ssim_min", "min"),
        ("ssim_inked_min", "ssim_inked_min", "min"),
        ("text_line_iou_mean", "text_line_iou_mean_min", "min"),
        ("text_line_pair_rate_mean", "text_line_pair_rate_min", "min"),
        ("ink_delta_abs_max", "ink_delta_abs_max", "max"),
    ):
        value = summary.get(key)
        bound = thresholds[bound_key]
        if value is None:
            add(key, None, False, bound)
        elif direction == "min":
            add(key, value, value >= bound, bound)
        else:
            add(key, value, value <= bound, bound)
    blocked = bool(geometry) and geometry.get("comparable") is False
    return {
        "pass": None if blocked else all(c["pass"] for c in checks),
        "blocked": blocked,
        "blocked_reason": ("reference_geometry_scale" if blocked else None),
        "ratified": bool(thresholds.get("ratified")),
        "note": ("a passing verdict against UNRATIFIED thresholds promotes "
                 "nothing; the grade stays own-uncertified"),
        "checks": checks,
    }


def _corpus_pairs(repo_root):
    """Forms that have both a converted HWPX and a Hancom reference PDF."""
    converted = repo_root / "tests" / "corpus" / "forms" / "converted"
    renders = repo_root / "tests" / "corpus" / "forms" / "render"
    classes = {}
    manifest = repo_root / "tests" / "corpus" / "forms" / "manifest.json"
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in payload.get("documents", []):
            if entry.get("slug"):
                classes[entry["slug"]] = entry.get("family") or "unknown"
    pairs = []
    for pdf in sorted(renders.glob("*.pdf")):
        hwpx = converted / (pdf.stem + ".hwpx")
        if hwpx.is_file():
            pairs.append((hwpx, pdf, classes.get(pdf.stem, "unknown")))
    return pairs


def write_scoreboard(report, out_dir, stem, label=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f".{label}" if label else ""
    path = out_dir / f"{stem}{suffix}.scoreboard.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return path


def build_parser():
    parser = argparse.ArgumentParser(
        prog="render_scoreboard.py",
        description="Score Rigorloom's own OWPML renderer against an immutable "
                    "Hancom reference PDF.  Measures; never certifies.")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("reference", nargs="?", help="Hancom reference .pdf")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--label", help="scoreboard label, e.g. before / after")
    parser.add_argument(
        "--line-layout", choices=list(own_render.LINE_LAYOUT_MODES),
        default=own_render.LINE_LAYOUT_AUTO,
        help="auto (default) scores the render as it ships; computed scores it with every paragraph relaid out by the own line breaker")
    parser.add_argument("--corpus", action="store_true",
                        help="score every corpus form that has a reference PDF")
    parser.add_argument("--save-pages", action="store_true",
                        help="also write the candidate page PNGs into --out")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        if args.corpus:
            reports = []
            for hwpx, pdf, family in _corpus_pairs(repo_root):
                report = score_form(
                    hwpx, pdf, dpi=args.dpi, label=args.label,
                    out_dir=args.out if args.save_pages else None,
                    line_layout=args.line_layout)
                report["document_class"] = family
                write_scoreboard(report, args.out, hwpx.stem, args.label)
                reports.append({
                    "document": report["document"],
                    "document_class": family,
                    "reference_geometry_scale":
                        report["reference_geometry_scale"]["scale"],
                    "comparable":
                        report["reference_geometry_scale"]["comparable"],
                    "summary": report["summary"],
                    "verdict": {"pass": report["verdict"]["pass"],
                                "blocked": report["verdict"]["blocked"]},
                })
            print(json.dumps({"scored": reports}, ensure_ascii=False,
                             indent=2, sort_keys=True))
            return 0
        if not args.input or not args.reference:
            print("render_scoreboard: an input .hwpx and a reference .pdf are "
                  "required (or --corpus)", file=sys.stderr)
            return 2
        report = score_form(args.input, args.reference, dpi=args.dpi,
                            label=args.label,
                            out_dir=args.out if args.save_pages else None,
                            line_layout=args.line_layout)
        path = write_scoreboard(report, args.out, Path(args.input).stem,
                                args.label)
        print(json.dumps({"scoreboard": str(path), "report": report},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ScoreboardUnavailable, own_render.RendererUnavailable) as exc:
        print(f"render_scoreboard: unavailable — {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError) as exc:
        print(f"render_scoreboard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
