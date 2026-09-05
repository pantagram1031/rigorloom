#!/usr/bin/env python3
"""What font did Hancom actually draw with?  Every font object in the export.

#267 found that where our resolved face is the face Hancom drew with the
advance ratio is exactly 1.0000, and where it is a stand-in it is not.  #281
closed the bold half of that and named what is left: the punctuation in
``moel-2013``'s two ``text_rebreak:width`` carriers is drawn by **anonymous
Type 3 fonts** the export calls ``T2``, ``T6``, ``T19``, whose ``)`` is 0.332
em where our ``H2MJSM.TTF`` gives 0.495.  Neither slice could say what those
fonts ARE.

This script says.  It enumerates every font object of a reference PDF -- name,
subtype, whether the file carries the outlines, the descriptor, and for a
Type 3 font its ``FontMatrix``, ``CharProcs``, ``Widths`` and ``Encoding``
``Differences`` -- and then, for each Type 3 font:

* the code points it draws, read off its own ``ToUnicode`` CMap;
* the advance per code point, ``Widths[code] x FontMatrix[0]`` in em and, at
  each size the document sets that font in, in HWPUNIT;
* an outline fingerprint of every ``CharProcs`` entry: the glyph is a real
  vector path (``m`` / ``l`` / ``c`` / ``h``), so the fingerprint is a hash of
  the coordinate stream, and identical hashes across two font objects mean one
  design split into two subsets;
* which HWPX runs those spans belong to -- paragraph, ``hh:charPr`` id, slot,
  declared face name and the face's ``hh:font@type`` -- through
  ``lineseg_vs_pdf``'s pairing, the same one #258 measured and #267 and #281
  read their advances out of.

It then tries to identify each Type 3 font against every face installed on
this machine and every bundled face, two ways: by rasterising the glyph
outline into the same em frame as the candidate's own glyph and scoring the
overlap, and -- much the sharper test -- by asking whether the candidate's
``hmtx`` reproduces the Type 3 ``Widths`` for every code point at once.

Usage::

    python engine/scripts/pdf_face_probe.py REFERENCE.pdf
    python engine/scripts/pdf_face_probe.py REFERENCE.pdf --hwpx FORM.hwpx
    python engine/scripts/pdf_face_probe.py --corpus
    python engine/scripts/pdf_face_probe.py --corpus --json out.json --no-text

Without ``--hwpx`` (or ``--corpus``) only the PDF side is read, which is the
fonts table and the widths; the run attribution needs the document.

WHAT IS MEASURED, AND WHAT IS NOT
---------------------------------
* **A Type 3 ``Widths`` entry is the advance the PDF declares**, not one
  reconstructed from glyph positions.  It is read straight out of the font
  object, so unlike #267's per-character ratio it carries no pairing, no
  alignment and no MuPDF reconstruction -- but for the same reason it says
  nothing about what Hancom did with that advance on the page.
* **The outline score is a rasterised overlap, not a curve comparison.**  Both
  sides are flattened to polygons and filled by an even-odd rule; a glyph
  whose counters are wound the TrueType way still comes out right, but the
  score is a similarity and never a proof of identity.
* **``ToUnicode`` is the export's own claim** about what a glyph means.  It is
  what the reader uses and what the pairing already matched on, so it is the
  same claim every other number in this repo's PDF work rests on.

This is measurement.  It changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import advance_probe  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402
import own_render  # noqa: E402
from own_render import _kids, _local, script_slot  # noqa: E402


HWPUNIT_PER_PT = own_render.HWPUNIT_PER_PT

#: A Type 3 ``Widths`` entry and a candidate face's ``hmtx`` count as the same
#: advance within this many em.  The ``Widths`` array is integers in the
#: font's own 1/``FontMatrix`` grid (1000 here), so a face designed on 1024 or
#: 2048 units per em can only ever land within half a grid step of it.
TOL_EM = 0.0015

#: The em frame the outline fingerprint rasterises into: x from ``-0.1`` to
#: ``1.1`` em, y from ``-0.35`` (below the baseline) to ``1.05`` em above it,
#: at this many pixels per em.  Fixed so that two glyphs are compared in
#: POSITION and SIZE as well as shape.
FINGERPRINT_PX_PER_EM = 64
FINGERPRINT_X0 = -0.1
FINGERPRINT_X1 = 1.1
FINGERPRINT_Y0 = -0.35
FINGERPRINT_Y1 = 1.05

#: How many straight segments a cubic bezier is flattened into.
BEZIER_STEPS = 12

#: Code points a fingerprint is never taken on: a space has no ink, so its
#: overlap score is 1.0 against everything.
FINGERPRINT_SKIP = {" ", " ", "　", ""}


# -- the PDF's font objects ----------------------------------------------

def _deref(doc, value):
    """An indirect reference resolved to its object source, else ``value``."""
    if not isinstance(value, str):
        return value
    match = re.match(r"^\s*(\d+) 0 R\s*$", value)
    if match:
        return doc.xref_object(int(match.group(1)), compressed=True)
    return value


#: A PDF number.  ``.001`` is a legal one and has no leading digit, which is
#: exactly the form ``FontMatrix`` is written in.
_NUMBER = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)"

#: One content-stream token: a number, or an operator.  A PDF operator may
#: carry a digit (``d0``, ``d1``) or a star (``f*``, ``B*``), so the operator
#: pattern cannot be letters alone -- reading ``d1`` as ``d`` then ``1`` loses
#: the glyph's declared advance and leaves a stray number on the stack.
_TOKEN = re.compile(_NUMBER + r"|[A-Za-z][A-Za-z0-9*'\"]*")


def _numbers(text):
    return [float(n) for n in re.findall(_NUMBER, text or "")]


def _tounicode(doc, xref):
    """``{code: text}`` out of a ``ToUnicode`` CMap stream."""
    try:
        data = doc.xref_stream(xref).decode("latin-1")
    except Exception:  # pragma: no cover - a damaged stream is not our case
        return {}
    out = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                                   block):
            out[int(src, 16)] = "".join(
                chr(int(dst[at:at + 4], 16)) for at in range(0, len(dst), 4))
    for block in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                block):
            base = int(dst, 16)
            for step, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                out[code] = chr(base + step)
    return out


def _indirect(value):
    match = re.match(r"^\s*(\d+) 0 R\s*$", value or "")
    return int(match.group(1)) if match else None


def parse_charproc(data):
    """``(subpaths, paint, line_width, declared_width)`` for one glyph.

    A Type 3 glyph procedure is a content stream.  Hancom's begin with the
    ``d1`` operator -- ``wx wy llx lly urx ury d1`` -- which declares the
    glyph's advance and bounding box, and continue with an ordinary path:
    ``m`` moveto, ``l`` lineto, ``c`` curveto, ``h`` closepath, and a paint
    operator.  ``f`` fills the path; ``B`` fills AND strokes it, which with a
    ``w`` line width in front is how a printer driver fakes a bold cut out of
    a regular outline.

    Coordinates are in the font's own glyph space, so the caller divides by
    ``1/FontMatrix[0]`` to reach em.
    """
    text = data.decode("latin-1", "replace")
    tokens = _TOKEN.findall(text)
    subpaths = []
    current = []
    stack = []
    point = (0.0, 0.0)
    paint = None
    line_width = 0.0
    declared_width = None
    for token in tokens:
        try:
            stack.append(float(token))
            continue
        except ValueError:
            pass
        op = token
        if op == "d1" and len(stack) >= 6:
            declared_width = stack[-6]
        elif op == "d0" and len(stack) >= 2:
            declared_width = stack[-2]
        elif op == "w" and stack:
            line_width = stack[-1]
        elif op == "m" and len(stack) >= 2:
            if len(current) > 1:
                subpaths.append(current)
            point = (stack[-2], stack[-1])
            current = [point]
        elif op == "l" and len(stack) >= 2:
            point = (stack[-2], stack[-1])
            current.append(point)
        elif op == "c" and len(stack) >= 6:
            x1, y1, x2, y2, x3, y3 = stack[-6:]
            current.extend(_bezier(point, (x1, y1), (x2, y2), (x3, y3)))
            point = (x3, y3)
        elif op in ("v", "y") and len(stack) >= 4:
            x2, y2, x3, y3 = stack[-4:]
            first = point if op == "v" else (x2, y2)
            second = (x2, y2) if op == "v" else (x3, y3)
            current.extend(_bezier(point, first, second, (x3, y3)))
            point = (x3, y3)
        elif op == "re" and len(stack) >= 4:
            x, y, w, h = stack[-4:]
            if len(current) > 1:
                subpaths.append(current)
            current = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            subpaths.append(current)
            current = []
        elif op == "h":
            if len(current) > 1:
                subpaths.append(current)
            current = []
        elif op in ("f", "F", "f*", "B", "B*", "b", "b*", "S", "s", "n"):
            if len(current) > 1:
                subpaths.append(current)
            current = []
            if paint is None:
                paint = op
        stack = []
    if len(current) > 1:
        subpaths.append(current)
    return subpaths, paint, line_width, declared_width


def _bezier(p0, p1, p2, p3, steps=BEZIER_STEPS):
    out = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1.0 - t
        out.append((
            u * u * u * p0[0] + 3 * u * u * t * p1[0]
            + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        ))
    return out


def outline_hash(data):
    """A hash of a glyph procedure's PATH, ignoring how it is painted.

    Two Type 3 font objects that carry the same design differ in their paint
    operator -- one fills, the other strokes the same outline to fake a bold
    cut -- and in nothing else.  Hashing the coordinate and path-operator
    stream alone is what makes that visible: identical hashes, identical
    outlines, one face.
    """
    text = data.decode("latin-1", "replace")
    # Drop the d0 / d1 header: it carries the advance and the bbox, which are
    # metrics and not the shape.
    text = re.sub(r"^.*?\bd[01]\b", "", text, count=1, flags=re.S)
    tokens = _TOKEN.findall(text)
    paint = ("f", "F", "f*", "B", "B*", "b", "b*", "S", "s", "n")
    keep = []
    for token in tokens:
        if token == "w":
            # The stroke width sits on the number stack in front of ``w``.
            # Both go, or an emboldened copy of one outline would hash apart
            # from the outline it was made of, which is the whole point.
            if keep:
                keep.pop()
            continue
        if token in paint:
            continue
        keep.append(token)
    return hashlib.sha1(" ".join(keep).encode("ascii", "ignore")
                        ).hexdigest()[:16]


def parse_differences(encoding):
    """``{code: glyph name}`` out of an ``Encoding`` dictionary's source.

    ``Differences`` is a code, then the names of the glyphs seated at that
    code and the ones after it, and it may restart at a new code any number
    of times.  Reading it as a flat list of names in ``Widths`` order --
    which is what the array LOOKS like when a font uses one run -- silently
    mis-seats every glyph after the first restart.
    """
    if "Differences" not in (encoding or ""):
        return {}
    body = encoding.split("Differences", 1)[1].split("]", 1)[0]
    names = {}
    code = 0
    for token in re.findall(r"/[^\s/\[\]<>]+|\d+", body):
        if token.startswith("/"):
            names[code] = token[1:]
            code += 1
        else:
            code = int(token)
    return names


def read_font_objects(pdf_path):
    """Every font object of one PDF, keyed by xref.

    ``get_page_fonts`` is per page and the same font is reachable from many;
    the first page a font appears on is recorded so a reader can find it.
    """
    fitz = lineseg_vs_pdf._require_fitz()
    fonts = {}
    with fitz.open(pdf_path) as doc:
        for number in range(doc.page_count):
            for entry in doc.get_page_fonts(number, full=True):
                xref = entry[0]
                if xref in fonts:
                    fonts[xref]["pages"].append(number)
                    continue
                fonts[xref] = _read_font(doc, xref, entry, number)
    return fonts


def _read_font(doc, xref, entry, page):
    _x, ext, subtype, basefont, name, encoding = entry[:6]
    # What MuPDF calls this font on a span.  A Type 3 font has no base font
    # worth the name, so the reader reports its ``/Name``; every other font is
    # reported by its base font with the six-letter subset tag stripped.  The
    # span attribution below keys on it, so it is computed once here.
    readable = advance_probe.readable_font_name(basefont) or ""
    span_name = re.sub(r"^[A-Z]{6}\+", "", readable)
    record = {
        "xref": xref,
        "name": advance_probe.readable_font_name(name),
        "span_name": (advance_probe.readable_font_name(name)
                      if subtype == "Type3" else span_name),
        "basefont": readable,
        "subtype": subtype,
        "ext": ext,
        "encoding": encoding,
        "pages": [page],
        "embedded": False,
        "font_matrix": None,
        "font_bbox": None,
        "charprocs": 0,
        "inked_glyphs": 0,
        "widths_em": {},
        "glyph_names": {},
        "tounicode": {},
        "upem": None,
        "descriptor": {},
        "glyphs": {},
    }
    if subtype == "Type3":
        record.update(_read_type3(doc, xref))
        return record
    # A simple or composite font carries its outlines in the descriptor.  The
    # extractor hands back the file itself when it is there, which is the one
    # unambiguous answer to "is this embedded".
    try:
        _base, ext2, _type2, buffer = doc.extract_font(xref)
    except Exception:  # pragma: no cover - reader dependent
        buffer = b""
        ext2 = ext
    record["embedded"] = bool(buffer)
    record["ext"] = ext2 or ext
    if buffer:
        record["upem"] = _upem_of(buffer)
    descendants = doc.xref_get_key(xref, "DescendantFonts")[1]
    target = xref
    if descendants and descendants != "null":
        text = _deref(doc, descendants)
        inner = _indirect(re.sub(r"^\s*\[|\]\s*$", "", text or "").strip())
        if inner:
            target = inner
    for key in ("FontDescriptor",):
        value = doc.xref_get_key(target, key)[1]
        ref = _indirect(value)
        if ref:
            record["descriptor"] = _descriptor_fields(
                doc.xref_object(ref, compressed=True))
    return record


def _descriptor_fields(text):
    out = {}
    for key in ("Flags", "StemV", "ItalicAngle", "Ascent", "Descent",
                "CapHeight", "MissingWidth"):
        match = re.search(rf"/{key}\s*(-?[\d.]+)", text or "")
        if match:
            out[key] = float(match.group(1))
    for key in ("FontFile", "FontFile2", "FontFile3"):
        if f"/{key}" in (text or ""):
            out["fontfile"] = key
    match = re.search(r"/FontBBox\s*\[([^\]]*)\]", text or "")
    if match:
        out["FontBBox"] = _numbers(match.group(1))
    return out


def _upem_of(buffer):
    """``head.unitsPerEm`` of an sfnt in memory, or ``None``."""
    try:
        import struct
        count = struct.unpack(">H", buffer[4:6])[0]
        for index in range(count):
            at = 12 + index * 16
            tag = buffer[at:at + 4]
            offset, length = struct.unpack(">II", buffer[at + 8:at + 16])
            if tag == b"head" and length >= 20:
                return struct.unpack(">H", buffer[offset + 18:offset + 20])[0]
    except Exception:  # pragma: no cover - a damaged sfnt is not our case
        return None
    return None


def _read_type3(doc, xref):
    """``FontMatrix``, ``Widths``, ``Encoding`` and every ``CharProcs`` entry.

    A Type 3 font is the only PDF font that carries its glyphs as content
    streams rather than as a font program, which is exactly what a driver
    emits for a face it cannot embed as outlines -- HWP's own HFT faces are
    not TrueType and there is no other way to put them in a PDF.
    """
    matrix = _numbers(_deref(doc, doc.xref_get_key(xref, "FontMatrix")[1]))
    scale = matrix[0] if matrix else 0.001
    widths = _numbers(_deref(doc, doc.xref_get_key(xref, "Widths")[1]))
    first = int(_numbers(doc.xref_get_key(xref, "FirstChar")[1] or "0")[0]
                if doc.xref_get_key(xref, "FirstChar")[1] else 0)
    encoding = _deref(doc, doc.xref_get_key(xref, "Encoding")[1]) or ""
    names = parse_differences(encoding)
    charprocs_src = _deref(doc, doc.xref_get_key(xref, "CharProcs")[1]) or ""
    procs = dict(re.findall(r"/([^\s/]+)\s+(\d+) 0 R", charprocs_src))
    tounicode = {}
    ref = _indirect(doc.xref_get_key(xref, "ToUnicode")[1])
    if ref:
        tounicode = _tounicode(doc, ref)
    glyphs = {}
    for index, width in enumerate(widths):
        code = first + index
        gname = names.get(code)
        char = tounicode.get(code)
        record = {
            "code": code,
            "glyph_name": gname,
            "char": char,
            "width_raw": width,
            "width_em": round(width * scale, 6),
        }
        proc_xref = procs.get(gname or "")
        if proc_xref:
            try:
                data = doc.xref_stream(int(proc_xref))
            except Exception:  # pragma: no cover
                data = b""
            if data:
                subpaths, paint, line_width, declared = parse_charproc(data)
                record["outline_hash"] = outline_hash(data)
                record["paint"] = paint
                record["line_width"] = line_width
                record["declared_width_raw"] = declared
                record["subpath_count"] = len(subpaths)
                record["_subpaths"] = subpaths
        glyphs[code] = record
    return {
        "embedded": True,
        # How many of the glyph procedures carry a PATH.  Some of these
        # exports emit a Type 3 font whose every procedure is ``d1`` and a
        # bare ``f`` -- an advance and a bounding box and no ink at all, the
        # text layer over a page whose marks are drawn as plain paths.  The
        # ``Widths`` are still the advances the reader positions that text
        # with, but there is no outline to fingerprint.
        "inked_glyphs": sum(1 for g in glyphs.values()
                            if g.get("subpath_count")),
        "font_matrix": matrix,
        "font_bbox": _numbers(doc.xref_get_key(xref, "FontBBox")[1]),
        "charprocs": len(procs),
        "widths_em": {code: g["width_em"] for code, g in glyphs.items()},
        "glyph_names": {code: g["glyph_name"] for code, g in glyphs.items()},
        "tounicode": tounicode,
        "upem": (round(1.0 / scale) if scale else None),
        "glyphs": glyphs,
    }


# -- the outline fingerprint ---------------------------------------------

def _blank_mask():
    from PIL import Image
    width = int(round((FINGERPRINT_X1 - FINGERPRINT_X0)
                      * FINGERPRINT_PX_PER_EM))
    height = int(round((FINGERPRINT_Y1 - FINGERPRINT_Y0)
                       * FINGERPRINT_PX_PER_EM))
    return Image.new("1", (width, height), 0)


def _em_to_px(x_em, y_em):
    px = (x_em - FINGERPRINT_X0) * FINGERPRINT_PX_PER_EM
    py = (FINGERPRINT_Y1 - y_em) * FINGERPRINT_PX_PER_EM
    return px, py


def rasterise_outline(subpaths, scale):
    """A Type 3 glyph's outline as a binary mask in the fixed em frame.

    Even-odd: each subpath is drawn into its own mask and XORed in, so a
    counter punched out of a bowl comes out as a hole whichever way the two
    contours are wound.
    """
    from PIL import ImageDraw
    mask = _blank_mask()
    for subpath in subpaths:
        if len(subpath) < 3:
            continue
        layer = _blank_mask()
        ImageDraw.Draw(layer).polygon(
            [_em_to_px(x * scale, y * scale) for x, y in subpath], fill=1)
        mask = _xor(mask, layer)
    return mask


def _xor(left, right):
    from PIL import ImageChops
    return ImageChops.logical_xor(left.convert("1"), right.convert("1"))


def rasterise_face(path, index, char):
    """The same em frame, filled by an installed or bundled face's glyph.

    Drawn at ``FINGERPRINT_PX_PER_EM`` with the anchor on the baseline at the
    origin, so a face whose design agrees with the Type 3 outline lands on it
    pixel for pixel and one that does not, does not.
    """
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(path, FINGERPRINT_PX_PER_EM, index=index,
                                  layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        return None
    mask = _blank_mask()
    image = Image.new("L", mask.size, 0)
    draw = ImageDraw.Draw(image)
    origin = _em_to_px(0.0, 0.0)
    try:
        draw.text(origin, char, fill=255, font=font, anchor="ls")
    except Exception:
        return None
    return image.point(lambda v: 255 if v >= 128 else 0).convert("1")


def mask_iou(left, right):
    if left is None or right is None:
        return 0.0
    from PIL import ImageChops
    a = left.convert("1")
    b = right.convert("1")
    inter = ImageChops.logical_and(a, b).convert("L").point(
        lambda v: 1 if v else 0)
    union = ImageChops.logical_or(a, b).convert("L").point(
        lambda v: 1 if v else 0)
    hits = sum(inter.getdata())
    total = sum(union.getdata())
    return (hits / total) if total else 0.0


# -- candidate faces ------------------------------------------------------

def candidate_faces(repo_root):
    """``[(label, path, index, source)]`` -- every face this machine can offer.

    The installed index and the bundled family map, de-duplicated by
    ``(path, index)``, which is the same population #283 matched the embedded
    휴먼명조 against.
    """
    seen = {}
    index = own_render.SystemFontIndex.shared()
    for key, entry in sorted(index.families.items()):
        for cut in ("regular", "bold", "italic", "bold_italic"):
            picked = entry.get(cut)
            if not picked:
                continue
            seen.setdefault(picked, (entry["family"], picked[0], picked[1],
                                     "installed"))
    bundled = own_render.BundledFontMap.shared(repo_root)
    for entry in bundled.entries.values():
        for cut in ("regular", "bold"):
            picked = entry.get(cut)
            if picked:
                seen.setdefault(picked, (entry["family"], picked[0],
                                         picked[1], "bundled"))
    return sorted(seen.values(), key=lambda row: (row[3], row[0], row[1]))


def face_advances(path, index, chars):
    """``{char: advance in em}`` off a face's own metrics, or ``None``.

    Taken at ``own_render.LAYOUT_REFERENCE_PX`` and divided by it, the same
    dpi-free way ``OwnRenderer._em_width`` takes every advance the line
    breaker uses, so a match here is a match against what we would measure.
    """
    from PIL import ImageFont
    px = own_render.LAYOUT_REFERENCE_PX
    try:
        font = ImageFont.truetype(path, px, index=index,
                                  layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        return None
    out = {}
    for char in chars:
        try:
            out[char] = font.getlength(char) / px
        except Exception:
            return None
    return out


def identify_type3(font, candidates, max_glyphs=6):
    """Rank candidate faces against one Type 3 font, by widths and by outline.

    ``width_hits`` is the count of code points whose ``Widths`` entry the
    candidate's own advance reproduces within :data:`TOL_EM`.  It is the
    sharper of the two: a face either has these metrics or it does not, and a
    Latin-proportional set of advances is not something a full-width CJK face
    can land on by accident.  ``outline_iou`` is the mean overlap of the
    rasterised glyph against the candidate's, over the first ``max_glyphs``
    inked code points, and is what separates two faces that share metrics.
    """
    inked = [g for g in font["glyphs"].values()
             if g.get("char") and g["char"] not in FINGERPRINT_SKIP
             and g.get("_subpaths")]
    inked.sort(key=lambda g: g["code"])
    sample = inked[:max_glyphs]
    scale = font["font_matrix"][0] if font.get("font_matrix") else 0.001
    ours = {g["char"]: rasterise_outline(g["_subpaths"], scale)
            for g in sample}
    chars = [g["char"] for g in font["glyphs"].values() if g.get("char")]
    wanted = {g["char"]: g["width_em"] for g in font["glyphs"].values()
              if g.get("char")}
    rows = []
    for family, path, index, source in candidates:
        advances = face_advances(path, index, chars)
        if advances is None:
            continue
        hits = sum(1 for char, em in wanted.items()
                   if abs(advances.get(char, -9.0) - em) <= TOL_EM)
        scores = []
        for glyph in sample:
            scores.append(mask_iou(ours[glyph["char"]],
                                   rasterise_face(path, index,
                                                  glyph["char"])))
        rows.append({
            "family": family,
            "file": Path(path).name,
            "index": index,
            "source": source,
            "width_hits": hits,
            "width_total": len(wanted),
            "outline_iou": (sum(scores) / len(scores)) if scores else 0.0,
        })
    rows.sort(key=lambda row: (-row["width_hits"], -row["outline_iou"]))
    return rows, [g["char"] for g in sample]


# -- the HWPX side --------------------------------------------------------

def declared_font_types(hwpx_path):
    """``{lang: {id: (face, type, subst_face, subst_type)}}`` from the header.

    ``own_render.parse_header`` keeps the face NAME per id and drops
    everything else, and ``hh:font@type`` is the attribute this whole slice
    turns on -- OWPML declares a face as ``TTF``, ``HFT`` or ``UNKNOWN``, and
    an HFT face is one of HWP's own, which is not a TrueType file at all.
    Read here rather than added to the renderer's tables, which is #281's
    ``autospace_flags`` convention.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    out = {}
    try:
        with zipfile.ZipFile(hwpx_path) as archive:
            data = archive.read("Contents/header.xml")
    except (KeyError, OSError, zipfile.BadZipFile):
        return out
    for face_el in ET.fromstring(data).iter():
        if _local(face_el.tag) != "fontface":
            continue
        lang = face_el.get("lang") or "HANGUL"
        table = out.setdefault(lang, {})
        for font in _kids(face_el, "font"):
            fid = font.get("id")
            if fid is None:
                continue
            subst = None
            for kid in _kids(font, "substFont"):
                subst = (kid.get("face"), kid.get("type"))
                break
            table[fid] = (font.get("face"), font.get("type"),
                          subst[0] if subst else None,
                          subst[1] if subst else None)
    return out


def declared_for(renderer, types, cid, slot):
    """``(face, type, subst_face, subst_type)`` for one run's slot."""
    font_ids = renderer._charpr(cid).get("font_ids") or {}
    for slot_key in (slot, slot.upper()):
        fid = font_ids.get(slot_key)
        if fid is None:
            continue
        table = types.get(slot.upper()) or types.get(slot) or {}
        hit = table.get(fid)
        if hit and hit[0]:
            return hit
    return (None, None, None, None)


def attribute_spans(hwpx_path, pdf_path, repo_root, keep_text=True):
    """Which HWPX run every PDF span belongs to, through #258's pairing.

    Walks the same paragraphs ``advance_probe.probe_document`` does and aligns
    the same way; the payload is different -- for every aligned character, the
    PDF font that drew it against the run that asked for it.
    """
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    metrics = advance_probe.OurMetrics(renderer)
    types = declared_font_types(hwpx_path)
    pdf = advance_probe.read_pdf_chars(pdf_path)
    cursor = 0
    usage = defaultdict(lambda: {"chars": Counter(), "runs": {},
                                 "sizes": Counter(), "n": 0,
                                 "char_faces": defaultdict(Counter),
                                 "slot_faces": Counter()})
    unpaired = 0
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        for _order, el in enumerate(_kids(renderer.sections[section], "p")):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = lineseg_vs_pdf.character_cells(para)
            if lineseg_vs_pdf.skip_reason(para, cells) is not None:
                continue
            target = lineseg_vs_pdf.normalise(
                lineseg_vs_pdf.paragraph_text(cells))
            hit = pdf.find_run(target, cursor)
            if hit is None:
                unpaired += 1
                continue
            lo, hi, _relaxed, out_of_order = hit
            pdf_run = advance_probe.merge_lines_with_boxes(pdf.lines[lo:hi])
            cursor = lineseg_vs_pdf._cursor_after(cursor, hi, out_of_order)
            address = renderer.paragraph_index.get(id(el))
            spans = lineseg_vs_pdf.cached_split(para, cells)
            for index, (clo, chi) in enumerate(spans):
                if index >= len(pdf_run):
                    break
                ours = advance_probe._para_chars_in_cells(para, clo, chi)
                boxes = pdf_run[index]["boxes"]
                if not ours or not boxes:
                    continue
                pairs, _n1, _n2 = advance_probe.align(
                    [(ch, cid) for _i, ch, cid in ours], boxes)
                for i, j in pairs:
                    _pos, char, cid = ours[i]
                    box = boxes[j]
                    slot = script_slot(char)
                    face, ftype, sface, stype = declared_for(
                        renderer, types, cid, slot)
                    run = metrics.run(char, cid)
                    bucket = usage[box.get("font")]
                    bucket["n"] += 1
                    # Which slot's ``@type`` predicts that Hancom reached for
                    # a Type 3 font.  ``script_slot`` files ASCII punctuation
                    # under ``symbol``; whether HWP does is the question the
                    # slot table below answers, so both candidates are
                    # recorded for every character.
                    for probe_slot in ("latin", "symbol", "hangul"):
                        pface, ptype, _a, _b = declared_for(
                            renderer, types, cid, probe_slot)
                        bucket["slot_faces"][
                            (probe_slot, char, pface, ptype)] += 1
                    if face:
                        # Per CODE POINT, not per font object: one Type 3
                        # subset can carry glyphs asked for by two declared
                        # faces (``moel-2013``'s ``T4`` holds ※ from one and
                        # ○ from the other), and attributing the whole font
                        # to its modal face would put one face's advance
                        # under the other's name.
                        bucket["char_faces"][char][(face, ftype)] += 1
                    if keep_text:
                        bucket["chars"][char] += 1
                    if box.get("size"):
                        bucket["sizes"][round(box["size"], 2)] += 1
                    key = (address, cid, slot, face, ftype)
                    seat = bucket["runs"].setdefault(key, {
                        "paragraph": address, "charpr": cid, "slot": slot,
                        "declared": face, "declared_type": ftype,
                        "subst_face": sface, "subst_type": stype,
                        "resolved": run["resolved"], "source": run["source"],
                        "bold": run["bold"], "size_pt": run["size_pt"],
                        "n": 0,
                    })
                    seat["n"] += 1
    return {"usage": usage, "unpaired": unpaired,
            "font_types": types}


# -- the fixed-fraction question -----------------------------------------

def fraction_table(fonts_by_form, attribution):
    """Per declared HFT face, the em advance every code point is drawn at.

    The question the task sets: are the Type 3 advances a small set of fixed
    fractions of the em per character class?  This groups every Type 3 code
    point by the HFT face the runs that used that font declare, so a face
    whose Latin is proportional shows one width per code point and a face that
    is uniformly full-width shows one width for all of them.
    """
    per_face = defaultdict(lambda: defaultdict(Counter))
    unattributed = Counter()
    for form, fonts in fonts_by_form.items():
        seats = attribution.get(form, {}).get("usage", {})
        for font in fonts.values():
            if font["subtype"] != "Type3":
                continue
            drawn = seats.get(font["span_name"], {}).get("char_faces", {})
            for glyph in font["glyphs"].values():
                char = glyph.get("char")
                if not char:
                    continue
                faces = drawn.get(char)
                if not faces:
                    unattributed[char] += 1
                    continue
                face = faces.most_common(1)[0][0]
                per_face[face][char][glyph["width_em"]] += 1
    return per_face, unattributed


def slot_prediction(fonts_by_form, attribution):
    """Which slot's ``hh:font@type`` says Hancom would reach for a Type 3 font.

    ``script_slot`` files ASCII punctuation under ``symbol``.  If HWP files it
    under ``latin`` instead, then a run whose latin slot names an HFT face and
    whose symbol slot names a TrueType one is drawn from HWP's own face and
    metered from it -- and our advance comes off the wrong face even when the
    declared name we used is installed.  This scores both readings against
    what the export actually did: per character, was the drawing font a Type 3
    one, and did that slot's ``@type`` predict it.
    """
    rows = defaultdict(lambda: Counter())
    for form, fonts in fonts_by_form.items():
        t3names = {font["span_name"] for font in fonts.values()
                   if font["subtype"] == "Type3"}
        for name, seat in attribution.get(form, {}).get("usage", {}).items():
            is_type3 = name in t3names
            for (slot, char, face, ftype), count in \
                    seat["slot_faces"].items():
                if char is None or char.isspace() or char == "　":
                    continue
                klass = advance_probe.char_class(char)
                hit = "type3" if is_type3 else "sfnt"
                said = "HFT" if ftype == "HFT" else "other"
                rows[(slot, klass)][(said, hit)] += count
    out = []
    for (slot, klass), counts in sorted(rows.items()):
        hft_t3 = counts[("HFT", "type3")]
        hft_sfnt = counts[("HFT", "sfnt")]
        other_t3 = counts[("other", "type3")]
        other_sfnt = counts[("other", "sfnt")]
        total = hft_t3 + hft_sfnt + other_t3 + other_sfnt
        agree = hft_t3 + other_sfnt
        out.append({
            "slot": slot, "class": klass, "n": total,
            "hft_type3": hft_t3, "hft_sfnt": hft_sfnt,
            "other_type3": other_t3, "other_sfnt": other_sfnt,
            "agreement": (agree / total) if total else 0.0,
        })
    return out


def format_slots(rows):
    out = ["\ndoes a slot's hh:font@type predict that Hancom drew the "
           "character from a Type 3 font?", ""]
    out.append(f"{'slot':<8} {'class':<9} {'n':>6} {'HFT/T3':>7} "
               f"{'HFT/sfnt':>9} {'other/T3':>9} {'other/sfnt':>11} "
               f"{'agrees':>7}")
    out.append("-" * 74)
    for row in rows:
        out.append(f"{row['slot']:<8} {row['class']:<9} {row['n']:>6} "
                   f"{row['hft_type3']:>7} {row['hft_sfnt']:>9} "
                   f"{row['other_type3']:>9} {row['other_sfnt']:>11} "
                   f"{row['agreement'] * 100:>6.1f}%")
    for slot in ("latin", "symbol", "hangul"):
        seats = [row for row in rows if row["slot"] == slot]
        total = sum(row["n"] for row in seats)
        agree = sum(row["hft_type3"] + row["other_sfnt"] for row in seats)
        out.append(f"{slot:<8} {'ALL':<9} {total:>6} "
                   f"{sum(r['hft_type3'] for r in seats):>7} "
                   f"{sum(r['hft_sfnt'] for r in seats):>9} "
                   f"{sum(r['other_type3'] for r in seats):>9} "
                   f"{sum(r['other_sfnt'] for r in seats):>11} "
                   f"{(agree / total * 100 if total else 0):>6.1f}%")
    return "\n".join(out)


def class_fraction_fit(per_face):
    """Whether one width per (face, class) covers the code points seen.

    The rule the task asks for is a table of fixed fractions per character
    class.  This scores the strongest form of it: for each declared face and
    each ``advance_probe.char_class``, the modal width, and how many of the
    face's code-point observations that one number reproduces.
    """
    rows = []
    for face, chars in sorted(per_face.items(), key=lambda kv: str(kv[0])):
        per_class = defaultdict(Counter)
        for char, widths in chars.items():
            klass = advance_probe.char_class(char)
            for width, count in widths.items():
                per_class[klass][width] += count
        for klass, widths in sorted(per_class.items()):
            total = sum(widths.values())
            modal, hits = widths.most_common(1)[0]
            rows.append({
                "declared": face[0], "declared_type": face[1],
                "class": klass, "modal_em": modal,
                "hits": hits, "total": total,
                "distinct": len(widths),
            })
    return rows


def font_class_fit(fonts_by_form):
    """The same fixed-fraction rule, on EVERY Type 3 code point in the corpus.

    ``fraction_table`` can only reach the code points a paired paragraph used,
    and ``lineseg_vs_pdf`` pairs top-level paragraphs only, so most of a
    form's Type 3 glyphs never get a declared face.  This asks the same
    question of the font objects themselves -- within one Type 3 font, does
    one width per character class cover every code point it carries? -- which
    needs no attribution and so scores the whole population.
    """
    per_class = defaultdict(Counter)
    for _form, fonts in fonts_by_form.items():
        for font in fonts.values():
            if font["subtype"] != "Type3":
                continue
            for glyph in font["glyphs"].values():
                char = glyph.get("char")
                if not char:
                    continue
                per_class[(font["xref"], _form,
                           advance_probe.char_class(char))][
                    glyph["width_em"]] += 1
    rows = defaultdict(Counter)
    for (_xref, _form, klass), widths in per_class.items():
        total = sum(widths.values())
        _modal, best = widths.most_common(1)[0]
        rows[klass]["total"] += total
        rows[klass]["hits"] += best
        rows[klass]["fonts"] += 1
        rows[klass]["split"] += 1 if len(widths) > 1 else 0
    return rows


def format_font_class_fit(rows):
    out = ["\nwithin ONE Type 3 font, does one width per class cover every "
           "code point it carries?", ""]
    out.append(f"{'class':<9} {'fonts':>6} {'split':>6} {'cps':>6} "
               f"{'covered':>8} {'fit':>7}")
    out.append("-" * 48)
    total = hits = 0
    for klass, seat in sorted(rows.items()):
        total += seat["total"]
        hits += seat["hits"]
        out.append(f"{klass:<9} {seat['fonts']:>6} {seat['split']:>6} "
                   f"{seat['total']:>6} {seat['hits']:>8} "
                   f"{seat['hits'] / seat['total'] * 100:>6.1f}%")
    out.append(f"{'ALL':<9} {'':>6} {'':>6} {total:>6} {hits:>8} "
               f"{(hits / total * 100 if total else 0):>6.1f}%")
    return "\n".join(out)


def code_point_fit(per_face):
    """The weaker, per-CODE-POINT rule: one width per (face, code point)."""
    rows = []
    for face, chars in sorted(per_face.items(), key=lambda kv: str(kv[0])):
        total = 0
        hits = 0
        conflicts = []
        for char, widths in chars.items():
            count = sum(widths.values())
            modal, best = widths.most_common(1)[0]
            total += count
            hits += best
            if len(widths) > 1:
                conflicts.append((char, dict(widths)))
        rows.append({
            "declared": face[0], "declared_type": face[1],
            "code_points": len(chars), "observations": total, "hits": hits,
            "conflicts": conflicts,
        })
    return rows


# -- reconciliation of two named paragraphs -------------------------------

#: The two ``moel-2013`` paragraphs #267 named and #281 could not close.
RECONCILE = {"moel-pyojun-geunrogyeyakseo-2013": (118, 141)}


def reconcile(hwpx_path, pdf_path, addresses, repo_root, keep_text=True):
    """Per character, on named paragraphs: ours against Hancom, and by what.

    The anchored comparison is #267's, term for term -- our advance is
    ``_measure_hwp`` plus the ``hh:spacing`` gap, Hancom's is the pen distance
    between two aligned glyph origins, and both sides cover the same
    characters.  The walk is repeated here rather than
    ``advance_probe.probe_document`` reused because the ``hh:charPr`` id is
    what the DECLARED face name has to be looked up from, and the upstream
    record does not carry it (its ``declared`` field is the full-width cell,
    not the face).

    Each row also carries the PDF font that drew the character and, when that
    is a Type 3 font, the ``Widths`` advance it declares -- which is the
    quantity a metric source for these runs would have to supply.
    """
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    metrics = advance_probe.OurMetrics(renderer)
    types = declared_font_types(hwpx_path)
    pdf = advance_probe.read_pdf_chars(pdf_path)
    type3 = {}
    for font in read_font_objects(pdf_path).values():
        if font["subtype"] != "Type3":
            continue
        for glyph in font["glyphs"].values():
            if glyph.get("char"):
                type3.setdefault((font["span_name"], glyph["char"]),
                                 glyph["width_em"])
    cursor = 0
    out = []
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        for el in _kids(renderer.sections[section], "p"):
            para = own_render.Paragraph(el, renderer.defs["para_pr"])
            cells = lineseg_vs_pdf.character_cells(para)
            if lineseg_vs_pdf.skip_reason(para, cells) is not None:
                continue
            target = lineseg_vs_pdf.normalise(
                lineseg_vs_pdf.paragraph_text(cells))
            hit = pdf.find_run(target, cursor)
            if hit is None:
                continue
            lo, hi, _relaxed, out_of_order = hit
            pdf_run = advance_probe.merge_lines_with_boxes(pdf.lines[lo:hi])
            cursor = lineseg_vs_pdf._cursor_after(cursor, hi, out_of_order)
            address = renderer.paragraph_index.get(id(el))
            if address not in addresses:
                continue
            align_mode = para.para_pr.get("align", "LEFT")
            spans = lineseg_vs_pdf.cached_split(para, cells)
            for index, (clo, chi) in enumerate(spans):
                if index >= len(pdf_run):
                    break
                ours = advance_probe._para_chars_in_cells(para, clo, chi)
                boxes = pdf_run[index]["boxes"]
                if not ours or not boxes:
                    continue
                pairs, _n1, _n2 = advance_probe.align(
                    [(ch, cid) for _i, ch, cid in ours], boxes)
                rows = []
                for step in range(len(pairs) - 1):
                    i1, j1 = pairs[step]
                    i2, j2 = pairs[step + 1]
                    covered = [ours[i] for i in range(i1, i2)]
                    ours_hwp = 0.0
                    for _pos, char, cid in covered:
                        run = metrics.run(char, cid)
                        ours_hwp += run["advance_hwp"] + run["gap_hwp"]
                    hancom_hwp = ((boxes[j2]["ox"] - boxes[j1]["ox"])
                                  * HWPUNIT_PER_PT)
                    head_char, head_cid = covered[0][1], covered[0][2]
                    slot = script_slot(head_char)
                    face, ftype, _sf, _st = declared_for(
                        renderer, types, head_cid, slot)
                    run = metrics.run(head_char, head_cid)
                    pdf_font = boxes[j1].get("font")
                    # What this segment would measure if the head character
                    # were metered off the Type 3 font's own ``Widths``
                    # instead of off the face we resolved.  Only the head is
                    # substituted: the rest of a multi-character segment is
                    # characters Hancom never drew, which have no PDF width
                    # to read.
                    t3_em = type3.get((pdf_font, head_char))
                    hft_hwp = ours_hwp
                    if t3_em is not None and run["declared"]:
                        want = t3_em * run["declared"]
                        gap = (renderer._spacing_gap(want, run["spacing"])
                               if run["spacing"] else 0.0)
                        hft_hwp = (ours_hwp - run["advance_hwp"]
                                   - run["gap_hwp"] + want + gap)
                    rows.append({
                        "char": head_char if keep_text else None,
                        "chars_covered": len(covered),
                        "class": run["class"],
                        "slot": slot,
                        "declared": face,
                        "declared_type": ftype,
                        "resolved": run["resolved"],
                        "source": run["source"],
                        "pdf_font": pdf_font,
                        "type3_width_em": type3.get((pdf_font, head_char)),
                        "cell_hwp": run["declared"],
                        "ours_hwp": ours_hwp,
                        "hft_hwp": hft_hwp,
                        "hancom_hwp": hancom_hwp,
                        "delta_hwp": ours_hwp - hancom_hwp,
                    })
                is_last = (index == len(spans) - 1)
                out.append({
                    "paragraph": address,
                    "line": index,
                    "align": align_mode,
                    "stretched": (align_mode == "DISTRIBUTE"
                                  or (align_mode == "JUSTIFY"
                                      and not is_last)),
                    "horzsize": own_render._iattr(para.linesegs[index],
                                                  "horzsize")
                    if index < len(para.linesegs) else None,
                    "ours_span_hwp": sum(row["ours_hwp"] for row in rows),
                    "hft_span_hwp": sum(row["hft_hwp"] for row in rows),
                    "hancom_span_hwp": sum(row["hancom_hwp"] for row in rows),
                    "chars": rows,
                })
    return out


# -- formatting -----------------------------------------------------------

def format_fonts(form, fonts, attribution):
    seats = attribution.get("usage", {}) if attribution else {}
    out = [f"\n{form}: every font object in the export", ""]
    out.append(f"{'name':<16} {'subtype':<9} {'emb':>3} {'upem':>5} "
               f"{'glyphs':>6} {'inked':>5} {'chars':>6}  "
               f"code points / stands for")
    out.append("-" * 112)
    for font in sorted(fonts.values(), key=lambda f: (f["subtype"], f["name"])):
        seat = seats.get(font["span_name"], {})
        drawn = seat.get("n", 0)
        if font["subtype"] == "Type3":
            chars = "".join(sorted(
                {g["char"] for g in font["glyphs"].values()
                 if g.get("char") and g["char"].strip()}))
            faces = Counter()
            for run in seat.get("runs", {}).values():
                if run["declared"]:
                    faces[f"{run['declared']} ({run['declared_type']})"] += \
                        run["n"]
            tail = chars[:36]
            if faces:
                tail += "  -> " + ", ".join(
                    f"{name} x{count}" for name, count in faces.most_common(3))
            count = len(font["glyphs"])
        else:
            faces = Counter()
            for run in seat.get("runs", {}).values():
                if run["declared"]:
                    faces[f"{run['declared']} ({run['declared_type']})"] += \
                        run["n"]
            tail = (font["basefont"] or "")
            if faces:
                tail += "  -> " + ", ".join(
                    f"{name} x{count}" for name, count in faces.most_common(3))
            count = 0
        out.append(f"{font['name']:<16} {font['subtype']:<9} "
                   f"{'yes' if font['embedded'] else 'no':>3} "
                   f"{font['upem'] or '':>5} {count:>6} "
                   f"{font['inked_glyphs']:>5} {drawn:>6}  {tail}")
    return "\n".join(out)


def format_type3_widths(form, fonts):
    out = [f"\n{form}: Type 3 advances, per code point "
           f"(em = Widths x FontMatrix)", ""]
    for font in sorted(fonts.values(), key=lambda f: f["name"]):
        if font["subtype"] != "Type3":
            continue
        paints = Counter(g.get("paint") for g in font["glyphs"].values()
                         if g.get("paint"))
        widths = Counter(g.get("line_width") for g in font["glyphs"].values()
                         if g.get("line_width"))
        head = (f"  {font['name']}: {len(font['glyphs'])} glyphs, "
                f"FontMatrix {font['font_matrix'][0] if font['font_matrix'] else '?'}, "
                f"paint {dict(paints)}")
        if widths:
            head += f", stroke width {dict(widths)}"
        out.append(head)
        cells = []
        for glyph in sorted(font["glyphs"].values(), key=lambda g: g["code"]):
            char = glyph.get("char") or "?"
            label = char if char.strip() else "SP"
            cells.append(f"{label}={glyph['width_em']:.4f}")
        for at in range(0, len(cells), 8):
            out.append("      " + "  ".join(cells[at:at + 8]))
    return "\n".join(out)


def format_outline_clusters(fonts_by_form):
    """Which Type 3 fonts share an outline, corpus-wide.

    One HFT design reaches the export as several font objects -- a subset per
    size run, and a second one when the run is bold -- and the only thing that
    ties them together is the glyph path itself.
    """
    labels = _short_labels(fonts_by_form)
    clusters = defaultdict(set)
    for form, fonts in fonts_by_form.items():
        for font in fonts.values():
            if font["subtype"] != "Type3":
                continue
            for glyph in font["glyphs"].values():
                # An inkless glyph -- a space -- has the same (empty) outline
                # in every face, so it would cluster every font object in the
                # corpus together and say nothing.
                if (glyph.get("outline_hash") and glyph.get("char")
                        and glyph.get("subpath_count")):
                    clusters[(glyph["char"], glyph["outline_hash"])].add(
                        (form, font["name"], glyph.get("paint"),
                         glyph["width_em"]))
    shared = {key: seats for key, seats in clusters.items()
              if len({(form, name) for form, name, _p, _w in seats}) > 1}
    out = ["\none outline, more than one Type 3 font object", ""]
    out.append(f"  {len(shared)} of {len(clusters)} (code point, outline) "
               f"pairs are drawn by more than one font object")
    counts = Counter()
    for key, seats in shared.items():
        counts[tuple(sorted({(form, name)
                             for form, name, _p, _w in seats}))] += 1
    for group, count in counts.most_common(12):
        painted = set()
        for key, seats in shared.items():
            if tuple(sorted({(f, n) for f, n, _p, _w in seats})) == group:
                painted |= {p for _f, _n, p, _w in seats}
        out.append(f"    {count:>3} glyphs shared by "
                   + ", ".join(f"{labels[form]}/{name}"
                               for form, name in group)
                   + f"   paint {sorted(x for x in painted if x)}")
    # The bold question, straight off the outline: where one design reaches
    # the export both filled and stroked -- HWP's synthetic bold, ``20 w B``
    # over the regular outline -- is the ADVANCE the same on both sides?
    both = 0
    same = 0
    differ = []
    for key, seats in clusters.items():
        paints = {paint for _f, _n, paint, _w in seats}
        if not ({"f", "F"} & paints) or "B" not in paints:
            continue
        both += 1
        regular = {w for _f, _n, p, w in seats if p in ("f", "F")}
        bold = {w for _f, _n, p, w in seats if p == "B"}
        if regular == bold and len(regular) == 1:
            same += 1
        else:
            differ.append((key[0], sorted(regular), sorted(bold)))
    out.append("")
    out.append(f"  {both} outlines reach the export both filled and stroked "
               f"(HWP's synthetic bold); {same} of them carry the SAME "
               f"advance on both sides")
    for char, regular, bold in differ[:6]:
        out.append(f"      {char!r}: filled {regular}, stroked {bold}")
    return "\n".join(out)


def _short_labels(fonts_by_form):
    """``{form stem: short label}``, disambiguated the way the corpus is."""
    heads = Counter(form.split("-")[0] for form in fonts_by_form)
    return {form: (form.split("-")[0] if heads[form.split("-")[0]] == 1
                   else f"{form.split('-')[0]}-{form.split('-')[-1]}")
            for form in fonts_by_form}


def format_identity(rows, form, name, sample, limit=5):
    out = [f"  {form} / {name}  sample {''.join(sample)}"]
    if not rows:
        out.append("      no candidate face could be read")
        return "\n".join(out)
    exact = sum(1 for row in rows if row["width_hits"] == row["width_total"])
    out.append(f"      {exact} of {len(rows)} faces reproduce EVERY width; "
               f"best {rows[0]['width_hits']}/{rows[0]['width_total']}, "
               f"best outline iou "
               f"{max(row['outline_iou'] for row in rows):.3f}")
    for row in rows[:limit]:
        out.append(f"      {row['width_hits']:>2}/{row['width_total']:<2} "
                   f"widths  iou {row['outline_iou']:.3f}  "
                   f"{row['source']:<9} {row['family']} "
                   f"({row['file']}#{row['index']})")
    return "\n".join(out)


def format_fractions(per_face, class_rows, cp_rows):
    out = ["\nType 3 advances grouped by the HFT face the runs declare", ""]
    out.append(f"{'declared face':<18} {'type':<5} {'class':<9} "
               f"{'modal em':>9} {'hits':>6} {'total':>6} {'widths':>7}")
    out.append("-" * 72)
    for row in class_rows:
        out.append(f"{row['declared']:<18} {row['declared_type'] or '?':<5} "
                   f"{row['class']:<9} {row['modal_em']:>9.4f} "
                   f"{row['hits']:>6} {row['total']:>6} {row['distinct']:>7}")
    total = sum(row["total"] for row in class_rows)
    hits = sum(row["hits"] for row in class_rows)
    out.append(f"{'ALL':<18} {'':<5} {'':<9} {'':>9} {hits:>6} {total:>6}"
               f"   = {(hits / total * 100 if total else 0):.1f}%")
    out.append("")
    out.append("the weaker rule -- one width per (face, code point):")
    out.append(f"{'declared face':<18} {'type':<5} {'cps':>5} {'obs':>6} "
               f"{'hits':>6} {'fit':>7}  conflicts")
    out.append("-" * 84)
    for row in cp_rows:
        share = row["hits"] / row["observations"] * 100 \
            if row["observations"] else 0.0
        conf = ", ".join(f"{c}{sorted(w)}" for c, w in row["conflicts"][:4])
        out.append(f"{row['declared']:<18} {row['declared_type'] or '?':<5} "
                   f"{row['code_points']:>5} {row['observations']:>6} "
                   f"{row['hits']:>6} {share:>6.1f}%  {conf}")
    total = sum(row["observations"] for row in cp_rows)
    hits = sum(row["hits"] for row in cp_rows)
    out.append(f"{'ALL':<18} {'':<5} {'':>5} {total:>6} {hits:>6} "
               f"{(hits / total * 100 if total else 0):>6.1f}%")
    return "\n".join(out)


def format_reconcile(form, lines):
    out = [f"\n{form}: per character, ours against Hancom", ""]
    for line in lines:
        out.append(f"  paragraph {line['paragraph']} line {line['line']} "
                   f"({line['align']}, horzsize {line['horzsize']}, "
                   f"stretched {line['stretched']}): "
                   f"ours {line['ours_span_hwp']:.0f} vs hancom "
                   f"{line['hancom_span_hwp']:.0f} "
                   f"(d {line['ours_span_hwp'] - line['hancom_span_hwp']:+.0f})")
        buckets = defaultdict(lambda: {"n": 0, "cov": 0, "delta": 0.0,
                                       "ours": 0.0, "theirs": 0.0})
        for row in line["chars"]:
            key = (row["char"], row["declared"], row["resolved"],
                   row["pdf_font"], row["type3_width_em"])
            seat = buckets[key]
            seat["n"] += 1
            seat["cov"] += row["chars_covered"]
            seat["delta"] += row["delta_hwp"]
            seat["ours"] += row["ours_hwp"]
            seat["theirs"] += row["hancom_hwp"]
        ordered = sorted(buckets.items(), key=lambda kv: -abs(kv[1]["delta"]))
        # ``n`` is anchored segments whose FIRST character is this one; ``cov``
        # is how many of our characters those segments cover.  A segment wider
        # than one character swallowed a character Hancom never drew (a space
        # is a pen move, not a glyph), and both sides of it still cover the
        # same text -- so the delta is attributable to the run, not to the
        # single code point the row is named after.
        out.append(f"      {'cp':<4} {'n':>3} {'cov':>4} {'declared':<12} "
                   f"{'our metric':<26} {'pdf':<6} {'t3 em':>7} "
                   f"{'ours':>8} {'hancom':>8} {'delta':>8}")
        shown = 0
        for key, seat in ordered:
            if abs(seat["delta"]) < 1.0 and shown >= 8:
                continue
            char, declared, resolved, pdf_font, t3 = key
            out.append(f"      {(char or '?'):<4} {seat['n']:>3} "
                       f"{seat['cov']:>4} "
                       f"{(declared or '?'):<12} {(resolved or '?'):<26} "
                       f"{(pdf_font or '?'):<6} "
                       f"{(f'{t3:.4f}' if t3 is not None else ''):>7} "
                       f"{seat['ours']:>8.0f} {seat['theirs']:>8.0f} "
                       f"{seat['delta']:>+8.0f}")
            shown += 1
        out.append(f"      {'sum':<4} {'':>3} "
                   f"{sum(s['cov'] for s in buckets.values()):>4} "
                   f"{'':<12} {'':<26} {'':<6} {'':>7} "
                   f"{sum(s['ours'] for s in buckets.values()):>8.0f} "
                   f"{sum(s['theirs'] for s in buckets.values()):>8.0f} "
                   f"{sum(s['delta'] for s in buckets.values()):>+8.0f}")
        # The whole point of the line: how much of the delta each PDF font
        # carries.  A Type 3 font's share is the HFT metric we do not have;
        # an sfnt font's is the substituted-face slice's.
        by_font = defaultdict(lambda: {"cov": 0, "delta": 0.0})
        for row in line["chars"]:
            seat = by_font[(row["pdf_font"], row["type3_width_em"] is not None
                            or row["char"] in ("", None))]
            seat["cov"] += row["chars_covered"]
            seat["delta"] += row["delta_hwp"]
        merged = defaultdict(lambda: {"cov": 0, "delta": 0.0})
        for (font, _t3), seat in by_font.items():
            merged[font]["cov"] += seat["cov"]
            merged[font]["delta"] += seat["delta"]
        out.append(f"      with the Type 3 Widths as the metric source: "
                   f"{line['hft_span_hwp']:.0f} vs hancom "
                   f"{line['hancom_span_hwp']:.0f} "
                   f"(d {line['hft_span_hwp'] - line['hancom_span_hwp']:+.0f}"
                   f", was "
                   f"{line['ours_span_hwp'] - line['hancom_span_hwp']:+.0f})")
        out.append("      carried by: " + ", ".join(
            f"{font} {seat['delta']:+.0f} over {seat['cov']} chars"
            for font, seat in sorted(merged.items(),
                                     key=lambda kv: -abs(kv[1]["delta"]))))
    return "\n".join(out)


# -- CLI ------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Every font object in Hancom's export, and what the "
                    "anonymous Type 3 ones stand for")
    parser.add_argument("pdf", nargs="?", type=Path,
                        help="a reference PDF")
    parser.add_argument("--hwpx", type=Path, default=None,
                        help="the document that produced it, for the run "
                             "attribution")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form with a reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--no-text", action="store_true",
                        help="omit document text from the report")
    parser.add_argument("--no-identify", action="store_true",
                        help="skip the face-identification pass, which "
                             "rasterises every installed face")
    parser.add_argument("--identify-limit", type=int, default=5,
                        help="how many candidate faces to print per Type 3 "
                             "font")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    targets = []
    if args.corpus:
        targets.extend(lineseg_vs_pdf.corpus_targets(repo_root))
    elif args.pdf:
        targets.append((args.hwpx, args.pdf))
    else:
        build_parser().error("give a reference PDF, or --corpus")
    keep_text = not args.no_text

    fonts_by_form = {}
    attribution = {}
    for hwpx, pdf in targets:
        form = Path(pdf).stem
        fonts_by_form[form] = read_font_objects(pdf)
        if hwpx is not None:
            attribution[form] = attribute_spans(hwpx, pdf, repo_root,
                                                keep_text=keep_text)
    for form in sorted(fonts_by_form):
        print(format_fonts(form, fonts_by_form[form],
                           attribution.get(form)))
        print(format_type3_widths(form, fonts_by_form[form]))
    print(format_outline_clusters(fonts_by_form))
    font_fit = font_class_fit(fonts_by_form)
    print(format_font_class_fit(font_fit))

    identities = {}
    if not args.no_identify:
        candidates = candidate_faces(repo_root)
        print(f"\nidentifying the Type 3 fonts against {len(candidates)} "
              f"faces on this machine\n")
        for form in sorted(fonts_by_form):
            for font in sorted(fonts_by_form[form].values(),
                               key=lambda f: f["name"]):
                if font["subtype"] != "Type3":
                    continue
                rows, sample = identify_type3(font, candidates)
                identities[(form, font["name"])] = rows
                print(format_identity(rows, form, font["name"], sample,
                                      limit=args.identify_limit))

    class_rows = []
    cp_rows = []
    slot_rows = []
    if attribution:
        slot_rows = slot_prediction(fonts_by_form, attribution)
        print(format_slots(slot_rows))
        per_face, unattributed = fraction_table(fonts_by_form, attribution)
        class_rows = class_fraction_fit(per_face)
        cp_rows = code_point_fit(per_face)
        print(format_fractions(per_face, class_rows, cp_rows))
        if unattributed:
            print(f"\n  {sum(unattributed.values())} Type 3 code points "
                  f"belong to a font no paired run used")

    reconciled = {}
    for hwpx, pdf in targets:
        if hwpx is None:
            continue
        addresses = RECONCILE.get(Path(hwpx).stem)
        if not addresses:
            continue
        lines = reconcile(hwpx, pdf, addresses, repo_root, keep_text=keep_text)
        reconciled[Path(hwpx).stem] = lines
        print(format_reconcile(Path(hwpx).stem, lines))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fonts": {
                form: [_jsonable_font(font) for font in fonts.values()]
                for form, fonts in fonts_by_form.items()
            },
            "attribution": {
                form: {
                    "unpaired": data["unpaired"],
                    "usage": [
                        {"pdf_font": name, "characters": seat["n"],
                         "sizes": dict(seat["sizes"]),
                         "char_faces": [
                             {"char": char, "declared": face,
                              "declared_type": ftype, "n": count}
                             for char, faces in sorted(
                                 seat["char_faces"].items())
                             for (face, ftype), count in faces.items()],
                         "runs": list(seat["runs"].values())}
                        for name, seat in sorted(data["usage"].items(),
                                                 key=lambda kv: str(kv[0]))
                    ],
                }
                for form, data in attribution.items()
            },
            "identities": [
                {"form": form, "pdf_font": name, "candidates": rows[:20]}
                for (form, name), rows in sorted(identities.items())
            ],
            "font_class_fit": {klass: dict(seat)
                               for klass, seat in font_fit.items()},
            "slot_prediction": slot_rows,
            "class_fraction_fit": class_rows,
            "code_point_fit": cp_rows,
            "reconciliation": reconciled,
        }
        args.json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


def _jsonable_font(font):
    out = {key: value for key, value in font.items() if key != "glyphs"}
    out["glyphs"] = [
        {key: value for key, value in glyph.items()
         if not key.startswith("_")}
        for glyph in sorted(font["glyphs"].values(),
                            key=lambda g: g["code"])
    ]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
