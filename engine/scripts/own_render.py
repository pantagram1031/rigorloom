#!/usr/bin/env python3
"""own_render.py — Rigorloom's own OWPML (HWPX) page renderer. Tier 3.

WHAT THIS IS
    A pure-Python + Pillow renderer for the *fixed-form subset* of OWPML
    (KS X 6101), the public XML document format used by ``.hwpx`` files.
    Everything here is written against the published format and against the
    XML the corpus files themselves carry.  No Hancom binary, no Hancom code,
    no COM call is involved, at build time or at run time.

WHY IT EXISTS
    The product needs page rendering where Hancom is not installed.  Three
    tiers exist:

        1. Hancom COM         — ground truth, only where Hancom is present.
        2. LibreOffice/H2O    — advisory.
        3. this renderer      — always available, and *uncertified* until
                                ``pipeline/scripts/render_cert.py`` says
                                otherwise, per document class.

HONESTY RULE (enforced by the output contract, not by convention)
    Every render carries ``grade: "own-uncertified"`` in its JSON sidecar and
    a named ``elements_skipped`` list.  Nothing this renderer produces may be
    presented as Hancom-faithful.  Elements it cannot draw are *named*, never
    silently dropped; objects it cannot lay out get a visible placeholder box.

UNITS
    1 HWPUNIT = 1/7200 inch, 1 pt = 100 HWPUNIT.  Cited from
    ``engine/scripts/form_inspect.py::_page_metrics`` ("HWP unit: 1 hwpunit =
    1/7200 inch, 1pt = 100 hwpunit") and confirmed against the corpus: every
    A4 form declares ``<hp:pagePr width="59528" height="84188">`` and
    210 mm = 8.2677 in x 7200 = 59528.

LAYOUT STRATEGY — trust the file's own cached layout
    OWPML paragraphs carry ``<hp:linesegarray><hp:lineseg .../>``: the line
    box positions a full layout engine already computed (``vertpos``,
    ``horzpos``, ``horzsize``, ``vertsize``, ``baseline``, ``textpos``).
    This renderer *reads* that cache instead of re-deriving line breaking.
    Consequences, all recorded in the sidecar:
      - line breaking matches the authoring engine exactly where the cache is
        present and self-consistent;
      - where it is absent or inconsistent with the run text (``textpos`` past
        the end of the paragraph's character stream) the renderer falls back
        to its own CJK-aware greedy wrap and says so;
      - alignment is *not* baked into the cache (``horzpos`` stays 0 for a
        centred line), so horizontal alignment is applied here from
        ``hh:paraPr/hh:align@horizontal``.

WHY ElementTree AND NOT THE HOUSE REGEX STYLE
    ``form_inspect``/``preedit``/``hwpx_tables`` parse with regex because they
    perform *byte-preserving edits* — a tree round-trip would rewrite the file.
    A renderer only reads, and needs true nesting (tables inside cells inside
    paragraphs).  Table/cell addressing here follows the same conventions
    ``hwpx_tables.scan_tables`` documents: document order for table index,
    ``cellAddr`` is the merged cell's top-left grid coordinate, and the
    coordinates a span covers carry no ``tc`` of their own.

CLI
    python own_render.py FORM.hwpx --out-dir DIR [--dpi 144]
    python own_render.py FORM.hwpx OUT.pdf          # render_cert argv shape
    python own_render.py --version

    Writes ``<stem>-p<N>.png`` per page plus ``<stem>.render.json``.

DETERMINISM
    Identical input bytes -> identical PNG bytes on one machine/build.  No
    timestamps are written, font rasterisation is pinned to Pillow's BASIC
    layout engine (Raqm, when present, is a build-dependent variable), and
    every geometric quantity is derived from integers in the file.  Font
    *metrics* differ between machines with different fonts installed, so
    cross-machine byte equality is not claimed — see ``fonts`` in the sidecar,
    which names exactly which face was rasterised.

exit 0: rendered.  exit 2: usage/input error.  exit 3: Pillow unavailable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli_io import utf8_stdio  # noqa: E402

RENDERER_ID = "rigorloom-own"
RENDERER_VERSION = "0.1.0"
RENDERER_STAMP = f"{RENDERER_ID}/{RENDERER_VERSION.rsplit('.', 1)[0]}"
GRADE = "own-uncertified"

HWPUNIT_PER_INCH = 7200
HWPUNIT_PER_PT = 100
DEFAULT_DPI = 144

# U+FFFC OBJECT REPLACEMENT CHARACTER: the single textpos slot an
# inline object occupies in a paragraph character stream.
OBJECT_SLOT = "\ufffc"

SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")
HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

# Inline objects this tier draws as a named placeholder box instead of art.
# The label is what a human sees on the page; the sidecar carries the element.
PLACEHOLDER_LABELS = {
    "equation": "수식",
    "pic": "그림",
    "ole": "그림",
    "chart": "그림",
    "container": "그림",
    "rect": "도형",
    "ellipse": "도형",
    "line": "도형",
    "arc": "도형",
    "polygon": "도형",
    "curve": "도형",
    "connectLine": "도형",
    "textart": "도형",
    "video": "그림",
}

# Elements that carry no ink at this tier.  Listed so the skipped-element
# report stays about *visible* gaps rather than drowning in bookkeeping tags.
STRUCTURAL_TAGS = frozenset({
    "sec", "p", "run", "t", "tbl", "tr", "tc", "subList", "cellAddr",
    "cellSpan", "cellSz", "cellMargin", "linesegarray", "lineseg", "sz",
    "pos", "inMargin", "outMargin", "shapeComment", "secPr", "grid",
    "startNum", "visibility", "lineNumberShape", "pagePr", "margin",
    "footNotePr", "endNotePr", "pageBorderFill", "offset", "masterPage",
    "autoNumFormat", "noteLine", "noteSpacing", "numbering", "placement",
    "ctrl", "colPr", "switch", "case", "default", "markpenBegin",
    "markpenEnd", "insertBegin", "insertEnd", "deleteBegin", "deleteEnd",
    "titleMark", "tab", "lineBreak", "hiddenComment", "fieldBegin",
    "fieldEnd", "bookmark", "parameterset", "parameteritem", "parameterarray",
    "imgRect", "imgClip", "effects", "img", "drawText", "lineShape",
    "fillBrush", "winBrush", "gradation", "imgBrush", "shadow", "pt0", "pt1",
    "pt2", "pt3", "curSz", "flip", "rotationInfo", "renderingInfo",
    "transMatrix", "scaMatrix", "rotMatrix", "matrix", "colorTrans",
})


class RendererUnavailable(RuntimeError):
    """Pillow (or a usable font) is missing.  Honest, not silent."""


# --------------------------------------------------------------------------
# XML helpers — namespace-agnostic, because the prefix (hp/hh/hs/hc) is not
# guaranteed by the format, only the namespace URI is, and different producers
# bind different prefixes.
# --------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el, name):
    return [c for c in el if _local(c.tag) == name]


def _kid(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _iattr(el, name, default=0):
    if el is None:
        return default
    raw = el.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _colour(raw):
    """OWPML colour attribute -> ``(r, g, b)`` or ``None`` for none/invalid."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower() in ("none", "auto"):
        return None
    if not HEX_COLOR_RE.match(raw):
        return None
    raw = raw.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _mm_to_hwp(raw):
    """``width="0.12 mm"`` -> HWPUNIT.  Border widths are declared in mm."""
    if not raw:
        return 0
    m = re.match(r"\s*([0-9.]+)\s*mm", str(raw))
    if not m:
        return 0
    return float(m.group(1)) / 25.4 * HWPUNIT_PER_INCH


# --------------------------------------------------------------------------
# Header definitions (Contents/header.xml)
# --------------------------------------------------------------------------

def parse_header(header_xml: bytes) -> dict:
    """charPr / borderFill / paraPr / fontface tables, keyed by id string.

    Mirrors what ``form_inspect._charpr_defs`` / ``_borderfill_shaded`` /
    ``_fontfaces`` read, extended with the fields a renderer needs (per-side
    border geometry, fill colour, paragraph alignment).
    """
    root = ET.fromstring(header_xml)

    fontfaces = {}
    for ff in root.iter():
        if _local(ff.tag) != "fontface":
            continue
        lang = ff.get("lang") or "HANGUL"
        table = fontfaces.setdefault(lang, {})
        for f in _kids(ff, "font"):
            if f.get("id") is not None:
                table[f.get("id")] = f.get("face")

    char_pr = {}
    for cp in root.iter():
        if _local(cp.tag) != "charPr":
            continue
        cid = cp.get("id")
        if cid is None:
            continue
        height = cp.get("height")
        underline = _kid(cp, "underline")
        font_ref = _kid(cp, "fontRef")
        char_pr[cid] = {
            "height_pt": (int(height) / HWPUNIT_PER_PT) if height else None,
            "color": _colour(cp.get("textColor")),
            "shade_color": _colour(cp.get("shadeColor")),
            "bold": _kid(cp, "bold") is not None,
            "italic": _kid(cp, "italic") is not None,
            "underline": (underline.get("type") if underline is not None else None),
            "underline_color": (_colour(underline.get("color"))
                                if underline is not None else None),
            "font_ids": dict(font_ref.attrib) if font_ref is not None else {},
        }

    border_fill = {}
    for bf in root.iter():
        if _local(bf.tag) != "borderFill":
            continue
        bid = bf.get("id")
        if bid is None:
            continue
        entry = {"fill": None}
        for side in ("left", "right", "top", "bottom"):
            b = _kid(bf, f"{side}Border")
            entry[side] = {
                "type": (b.get("type") if b is not None else "NONE") or "NONE",
                "width_hwp": _mm_to_hwp(b.get("width")) if b is not None else 0,
                "color": _colour(b.get("color")) if b is not None else None,
            }
        brush = _kid(bf, "fillBrush")
        if brush is not None:
            win = _kid(brush, "winBrush")
            if win is not None:
                entry["fill"] = _colour(win.get("faceColor"))
        border_fill[bid] = entry

    para_pr = {}
    for pp in root.iter():
        if _local(pp.tag) != "paraPr":
            continue
        pid = pp.get("id")
        if pid is None:
            continue
        align = _kid(pp, "align")
        para_pr[pid] = {
            "align": (align.get("horizontal") if align is not None else None) or "LEFT",
        }

    return {
        "char_pr": char_pr,
        "border_fill": border_fill,
        "para_pr": para_pr,
        "fontfaces": fontfaces,
    }


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------

_FONT_SEARCH = (
    # 1. explicit override, so a certification run can pin the exact face
    ("env", "RIGORLOOM_OWN_RENDER_FONT", "RIGORLOOM_OWN_RENDER_FONT_BOLD"),
    # 2. a face committed next to this renderer, if one is ever vendored
    ("repo", "engine/references/fonts/Pretendard-Regular.ttf",
     "engine/references/fonts/Pretendard-Bold.ttf"),
    ("repo", "desktop/sidecar/fonts/Pretendard-Regular.ttf",
     "desktop/sidecar/fonts/Pretendard-Bold.ttf"),
    # 3. the system Korean UI face — present on every Windows install
    ("system", r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("system", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
)


def resolve_fonts(repo_root: Path | None = None) -> dict:
    """Pick the single face this render rasterises with.

    Every HWP face name in the document (돋움, 바탕, 함초롬돋움, 한양신명조 …)
    maps to this one family.  That is a *named fidelity limit*, not an
    oversight: glyph advance widths differ between families, so intra-line
    text extents drift from the authoring engine's even though the line boxes
    (from the cached ``lineseg``) do not.
    """
    import os
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    for kind, regular, bold in _FONT_SEARCH:
        if kind == "env":
            reg = os.environ.get(regular)
            bld = os.environ.get(bold) or reg
            if reg and Path(reg).is_file():
                return {"regular": str(reg), "bold": str(bld), "source": "env"}
            continue
        base = repo_root if kind == "repo" else Path("/")
        reg_p = (base / regular) if kind == "repo" else Path(regular)
        bld_p = (base / bold) if kind == "repo" else Path(bold)
        if reg_p.is_file():
            return {
                "regular": str(reg_p),
                "bold": str(bld_p if bld_p.is_file() else reg_p),
                "source": kind,
            }
    raise RendererUnavailable(
        "no usable TrueType face found; set RIGORLOOM_OWN_RENDER_FONT")


def _require_pillow():
    """Lazy import.  Pillow is an optional dependency of the engine."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RendererUnavailable(
            "Pillow is not installed; own_render cannot rasterise") from exc
    return Image, ImageDraw, ImageFont


def pillow_available() -> bool:
    try:
        _require_pillow()
    except RendererUnavailable:
        return False
    return True


class FontBook:
    """Deterministic (path, px) -> ImageFont cache.

    ``layout_engine=BASIC`` is pinned on purpose: Pillow uses Raqm when the
    build has it, and Raqm's shaping differs from BASIC's, so the same script
    on two machines would otherwise produce different pixels for reasons that
    have nothing to do with the document.
    """

    def __init__(self, fonts: dict):
        _, _, ImageFont = _require_pillow()
        self._ImageFont = ImageFont
        self._paths = fonts
        self._cache = {}
        self._layout = getattr(ImageFont, "Layout", None)

    def get(self, size_px: int, bold: bool = False):
        size_px = max(1, int(size_px))
        key = (bold, size_px)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        path = self._paths["bold" if bold else "regular"]
        kwargs = {}
        if self._layout is not None:
            kwargs["layout_engine"] = self._layout.BASIC
        font = self._ImageFont.truetype(path, size_px, **kwargs)
        self._cache[key] = font
        return font


# --------------------------------------------------------------------------
# Track (column / row) solving
# --------------------------------------------------------------------------

def solve_tracks(count: int, constraints, declared_total=None):
    """Recover per-column widths / per-row heights from span constraints.

    ``constraints`` is ``[(start, span, total), ...]``.  OWPML only stores a
    ``cellSz`` per *cell*, so a grid whose every column is covered by a merged
    cell is underdetermined by the unit-span cells alone.  Gauss-style
    elimination (repeatedly solve any constraint with exactly one unknown left)
    closes it: on the corpus that recovers every column exactly, and the
    reconstructed row/column sums land within 2% of the table's declared
    ``hp:sz`` on 73 of 81 tables.

    Anything still unknown after the fixpoint is filled by splitting its
    constraint's residual evenly (deterministic integer split, remainder on the
    last track).  Finally the residual against ``declared_total`` — the
    authoritative outer box — is distributed proportionally so the table always
    occupies exactly the space the file says it does.
    """
    sizes = [None] * count
    for start, span, total in constraints:
        if span == 1 and 0 <= start < count and sizes[start] is None:
            sizes[start] = total

    changed = True
    while changed:
        changed = False
        for start, span, total in constraints:
            idx = [i for i in range(start, min(start + span, count))]
            if not idx:
                continue
            unknown = [i for i in idx if sizes[i] is None]
            if len(unknown) != 1:
                continue
            known = sum(sizes[i] for i in idx if sizes[i] is not None)
            sizes[unknown[0]] = max(0, total - known)
            changed = True

    for start, span, total in constraints:
        idx = [i for i in range(start, min(start + span, count))]
        unknown = [i for i in idx if sizes[i] is None]
        if not unknown:
            continue
        known = sum(sizes[i] for i in idx if sizes[i] is not None)
        residual = max(0, total - known)
        share = residual // len(unknown)
        for i in unknown[:-1]:
            sizes[i] = share
        sizes[unknown[-1]] = residual - share * (len(unknown) - 1)

    sizes = [s if s is not None else 0 for s in sizes]

    if declared_total and count:
        current = sum(sizes)
        if current > 0 and current != declared_total:
            scaled = [s * declared_total // current for s in sizes]
            scaled[-1] += declared_total - sum(scaled)
            sizes = [max(0, s) for s in scaled]
    return sizes


# --------------------------------------------------------------------------
# Paragraph model
# --------------------------------------------------------------------------

class Segment:
    """A maximal run of characters sharing one charPr, inside one line."""

    __slots__ = ("text", "charpr")

    def __init__(self, text, charpr):
        self.text = text
        self.charpr = charpr


class Paragraph:
    """One ``<hp:p>`` reduced to what the renderer needs.

    ``chars`` is the paragraph's character stream as ``(char, charPrIDRef)``
    pairs; inline objects occupy exactly one slot, matching how ``textpos``
    counts them.  ``objects`` records those slots so a placeholder or nested
    table can be positioned at the right line.
    """

    def __init__(self, el, para_pr):
        self.el = el
        self.para_pr = para_pr.get(el.get("paraPrIDRef") or "", {})
        self.align = self.para_pr.get("align", "LEFT")
        self.chars = []
        self.objects = []      # [(char_index, element_local_name, element, charpr)]
        self.object_at = {}    # char_index -> (name, element, charpr, floating)
        self.tabs = 0
        for run in _kids(el, "run"):
            charpr = run.get("charPrIDRef")
            for child in run:
                name = _local(child.tag)
                if name == "t":
                    for piece in child.itertext():
                        for ch in piece:
                            self.chars.append((ch, charpr))
                    # <hp:tab/> and friends sit inside <hp:t>; itertext skips
                    # them, so count them here to keep textpos honest.
                    for sub in child.iter():
                        if _local(sub.tag) == "tab":
                            self.tabs += 1
                elif name in ("tbl", "equation", "pic", "ole", "chart",
                              "container", "rect", "ellipse", "line", "arc",
                              "polygon", "curve", "connectLine", "textart",
                              "video"):
                    pos = _kid(child, "pos")
                    # treatAsChar="1" -> the object occupies a character cell
                    # in the line; anything else is anchored and positioned by
                    # its own offsets, so it must not consume inline width.
                    floating = (pos is not None
                                and (pos.get("treatAsChar") or "1") != "1")
                    index = len(self.chars)
                    self.objects.append((index, name, child, charpr))
                    self.object_at[index] = (name, child, charpr, floating)
                    self.chars.append((OBJECT_SLOT, charpr))
        self.linesegs = []
        la = _kid(el, "linesegarray")
        if la is not None:
            self.linesegs = _kids(la, "lineseg")

    @property
    def text(self):
        return "".join(c for c, _ in self.chars)

    def extent_hwp(self):
        """Vertical extent of the cached line boxes, in HWPUNIT.

        The trailing ``spacing`` of the last line is deliberately excluded:
        including it inflates single-line cell heights by up to 50% against
        the table's declared ``hp:sz`` on the corpus.
        """
        ext = 0
        for seg in self.linesegs:
            ext = max(ext, _iattr(seg, "vertpos") + _iattr(seg, "vertsize"))
        return ext


def own_paragraphs(container):
    """Direct ``<hp:p>`` children of a container's ``<hp:subList>``.

    Recursion stops naturally at a nested table: it lives inside a run inside
    one of these paragraphs, so a nested cell's paragraphs are never mistaken
    for the outer cell's (the same trap ``hwpx_tables._strip_nested_tables``
    guards against for cellAddr).
    """
    sub = _kid(container, "subList")
    return _kids(sub, "p") if sub is not None else []


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------

class OwnRenderer:
    def __init__(self, hwpx_path, dpi=DEFAULT_DPI, repo_root=None):
        self.path = Path(hwpx_path)
        self.dpi = int(dpi)
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")
        self.Image, self.ImageDraw, self._ImageFont = _require_pillow()
        self.fonts_meta = resolve_fonts(repo_root)
        self.fontbook = FontBook(self.fonts_meta)
        self.skipped = {}
        self.counts = {"paragraphs": 0, "runs": 0, "tables": 0, "cells": 0,
                       "text_lines": 0, "placeholders": 0, "borders": 0}
        # Every text line box this render drew, in device pixels, page-indexed.
        # Emitted in the sidecar because it is the only channel on which this
        # renderer can be compared to a Hancom reference *geometrically* (the
        # raster channel drowns in font substitution) — see
        # engine/scripts/render_scoreboard.py.  E1's caret work needs the same
        # record.
        self.line_boxes = []
        self._page = 1
        # Standing caveats that apply to every render, not just this document.
        # They belong in the artefact, not only in the notes file, because the
        # sidecar is what travels with the PNG.
        self.notes = [
            "line boxes come from the document's own cached hp:lineseg layout; "
            "line breaking matches the authoring engine, intra-line text "
            "extents do not (see fonts)",
            "character-level typography (hh:ratio, hh:spacing, hh:relSz, "
            "hh:offset) is not applied",
            "headers, footers, footnotes, endnotes and master pages are not "
            "drawn",
            "full limits and the certification path: "
            "engine/references/own-render-notes.md",
        ]
        self._load()

    # -- input -----------------------------------------------------------
    def _load(self):
        if not self.path.is_file():
            raise ValueError(f"not a file: {self.path}")
        with zipfile.ZipFile(self.path) as z:
            names = z.namelist()
            header_name = next(
                (n for n in names if n.endswith("header.xml")), None)
            if header_name is None:
                raise ValueError("HWPX is missing Contents/header.xml")
            self.defs = parse_header(z.read(header_name))
            self.sections = [
                ET.fromstring(z.read(n))
                for n in sorted(n for n in names if SECTION_RE.match(n))
            ]
        if not self.sections:
            raise ValueError("HWPX carries no Contents/section*.xml")
        if len(self.sections) > 1:
            self._skip("multi-section document",
                       f"only section0 is laid out; {len(self.sections)} present")

    def _skip(self, element, reason, where=None):
        key = (element, reason)
        entry = self.skipped.get(key)
        if entry is None:
            entry = {"element": element, "reason": reason, "count": 0}
            if where:
                entry["where"] = where
            self.skipped[key] = entry
        entry["count"] += 1

    # -- units -----------------------------------------------------------
    def px(self, hwp):
        """HWPUNIT -> device pixels at this render's DPI (rounded, integral)."""
        return int(round(hwp * self.dpi / HWPUNIT_PER_INCH))

    def pxf(self, hwp):
        """HWPUNIT -> device pixels, unrounded (for text metrics)."""
        return hwp * self.dpi / HWPUNIT_PER_INCH

    def hwp_from_px(self, px):
        """Device pixels -> HWPUNIT.  Line layout runs in px (that is where
        the font metrics live); nested boxes are addressed in HWPUNIT, so the
        inline cursor has to cross back exactly once, here."""
        return px * HWPUNIT_PER_INCH / self.dpi

    def pt_to_px(self, pt):
        return max(1, int(round(pt * self.dpi / 72.0)))

    # -- page geometry ---------------------------------------------------
    def page_geometry(self):
        root = self.sections[0]
        page_pr = next((e for e in root.iter() if _local(e.tag) == "pagePr"), None)
        if page_pr is None:
            raise ValueError("section0 declares no hp:pagePr")
        margin = _kid(page_pr, "margin")
        m = {k: _iattr(margin, k) for k in
             ("left", "right", "top", "bottom", "header", "footer", "gutter")}
        width = _iattr(page_pr, "width")
        height = _iattr(page_pr, "height")
        # Same formula and the same gutter caveat as
        # form_inspect._page_metrics: gutterType decides which side the gutter
        # lands on, so it is reported but never folded into the usable box.
        return {
            "width": width,
            "height": height,
            "margin": m,
            "landscape": page_pr.get("landscape"),
            "body_left": m["left"],
            "body_top": m["top"] + m["header"],
            "usable_width": width - m["left"] - m["right"],
            "usable_height": (height - m["top"] - m["bottom"]
                              - m["header"] - m["footer"]),
        }

    # -- page splitting --------------------------------------------------
    def paginate(self):
        """Assign each top-level paragraph a page index.

        OWPML's cached ``vertpos`` is measured from the top of the body box of
        the *current page* and restarts on every page — verified across the ten
        corpus forms, where the maximum top-level ``vertpos`` never exceeds one
        usable page height.  A page therefore begins wherever ``vertpos`` jumps
        backwards.  Two clauses, because both shapes occur:

          - ``first < prev_first`` — the ordinary restart.
          - a backward jump of more than a quarter page against the previous
            paragraph's *bottom*.  Some forms (saeopja, jumin) put one
            full-page table in each of several top-level paragraphs, all
            starting at ``vertpos=0``: the first clause alone stacks six pages
            on top of each other.  The quarter-page floor keeps a duplicated
            line box (nrf has two paragraphs at the same ``vertpos``) from
            being mistaken for a page.

        ``@pageBreak`` is deliberately *not* consulted: on this corpus it is
        also set on paragraphs whose ``vertpos`` does not restart, so honouring
        it would invent pages the cached layout does not have.
        """
        usable = max(1, self.page_geometry()["usable_height"])
        pages = []
        current = []
        prev_first = -1
        prev_bottom = -1
        for el in _kids(self.sections[0], "p"):
            para = Paragraph(el, self.defs["para_pr"])
            if para.linesegs:
                first = _iattr(para.linesegs[0], "vertpos")
                last = para.linesegs[-1]
                bottom = _iattr(last, "vertpos") + _iattr(last, "vertsize")
                restart = (first < prev_first
                           or (prev_bottom - first) > usable // 4)
                if restart and current:
                    pages.append(current)
                    current = []
                prev_first, prev_bottom = first, bottom
            current.append(para)
        if current or not pages:
            pages.append(current)
        return pages

    # -- text ------------------------------------------------------------
    def _charpr(self, cid):
        return self.defs["char_pr"].get(cid or "", {})

    def _font_for(self, cid):
        cp = self._charpr(cid)
        pt = cp.get("height_pt") or 10.0
        return self.fontbook.get(self.pt_to_px(pt), bool(cp.get("bold")))

    def _measure(self, draw, text, cid):
        if not text:
            return 0.0
        return float(draw.textlength(text, font=self._font_for(cid)))

    def _line_items(self, para, chars, base_index):
        """Ordered ``("text", Segment)`` / ``("obj", record)`` items for a line.

        An inline object shares the line with the text around it, so it has to
        be laid out *in* the line — positioning it separately puts a centred
        object at the left edge (gianmun's 발신명의 box did exactly that before
        this existed).  Floating objects are dropped from the inline stream;
        ``_render_floating`` places them from their own anchor offsets.
        """
        out = []
        for offset, (ch, cid) in enumerate(chars):
            if ch == OBJECT_SLOT:
                record = para.object_at.get(base_index + offset)
                if record is not None and not record[3]:
                    out.append(("obj", record))
                continue
            if out and out[-1][0] == "text" and out[-1][1].charpr == cid:
                out[-1][1].text += ch
            else:
                out.append(("text", Segment(ch, cid)))
        return out

    def _align_offset(self, align, avail_px, used_px):
        slack = avail_px - used_px
        if slack <= 0:
            return 0.0
        if align in ("CENTER", "DISTRIBUTE"):
            return slack / 2.0
        if align == "RIGHT":
            return slack
        return 0.0

    def _greedy_wrap(self, draw, chars, avail_px):
        """CJK-aware greedy wrap, used only when the cached layout is unusable.

        Latin words stay whole (break at spaces); Hangul/CJK breaks anywhere,
        which is what the format's own ``breakNonLatinWord`` default does.
        """
        lines = []
        current = []
        width = 0.0
        for ch, cid in chars:
            if ch == "\n":
                lines.append(current)
                current, width = [], 0.0
                continue
            w = self._measure(draw, ch, cid)
            if current and width + w > avail_px:
                if ch.isascii() and ch.isalnum():
                    # back up to the last space so a Latin word is not split
                    cut = len(current)
                    while cut > 0 and current[cut - 1][0] not in " \t":
                        cut -= 1
                    if 0 < cut < len(current):
                        carry = current[cut:]
                        lines.append(current[:cut])
                        current = carry
                        width = sum(self._measure(draw, c, i) for c, i in current)
                    else:
                        lines.append(current)
                        current, width = [], 0.0
                else:
                    lines.append(current)
                    current, width = [], 0.0
            current.append((ch, cid))
            width += w
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _object_extent(el):
        sz = _kid(el, "sz")
        return (_iattr(sz, "width") if sz is not None else 0,
                _iattr(sz, "height") if sz is not None else 0)

    def _draw_line(self, draw, items, x_hwp, line_top_hwp, baseline_hwp,
                   align, avail_hwp):
        """Draw one line box: text segments and inline objects, in order.

        The cached ``lineseg`` gives the box (``horzpos``/``horzsize``) but not
        the alignment offset inside it — ``horzpos`` stays 0 even for a centred
        line — so the offset is computed here from the measured content width.
        """
        if not items:
            return
        widths = []
        for kind, payload in items:
            if kind == "text":
                widths.append(self._measure(draw, payload.text, payload.charpr))
            else:
                widths.append(self.pxf(self._object_extent(payload[1])[0]))
        total = sum(widths)
        x_px = self.pxf(x_hwp)
        cursor = x_px + self._align_offset(align, self.pxf(avail_hwp), total)
        baseline_px = self.pxf(baseline_hwp)
        drew_text = False
        text_x0 = text_x1 = None
        ascent = descent = 0
        for (kind, payload), w in zip(items, widths):
            if kind == "obj":
                name, el, _charpr, _floating = payload
                origin = (self.hwp_from_px(cursor), line_top_hwp)
                if name == "tbl":
                    self._render_table(draw, el, origin)
                else:
                    self._render_placeholder(draw, el, name, origin)
                cursor += w
                continue
            seg = payload
            cp = self._charpr(seg.charpr)
            colour = cp.get("color") or (0, 0, 0)
            font = self._font_for(seg.charpr)
            draw.text((cursor, baseline_px), seg.text, font=font,
                      fill=colour, anchor="ls")
            drew_text = True
            seg_ascent, seg_descent = font.getmetrics()
            ascent = max(ascent, seg_ascent)
            descent = max(descent, seg_descent)
            text_x0 = cursor if text_x0 is None else min(text_x0, cursor)
            text_x1 = (cursor + w) if text_x1 is None else max(text_x1,
                                                              cursor + w)
            underline = (cp.get("underline") or "NONE").upper()
            if underline not in ("NONE", ""):
                # Ruled blanks in government forms are underline runs, and the
                # repo already treats them as load-bearing (form_inspect._is_ruled,
                # T112) — dropping them would erase the field the form provides.
                uy = baseline_px + max(1, self.pt_to_px(1.2))
                draw.line([(cursor, uy), (cursor + w, uy)],
                          fill=cp.get("underline_color") or colour,
                          width=max(1, self.dpi // 144))
            cursor += w
        if drew_text:
            self.counts["text_lines"] += 1
            # The box is the *text* extent, not the item extent: an inline
            # placeholder sharing the line must not inflate a box that is
            # about to be paired against a reference PDF's text lines.
            self.line_boxes.append({
                "page": self._page,
                "x0": round(text_x0, 3),
                "y0": round(baseline_px - ascent, 3),
                "x1": round(text_x1, 3),
                "y1": round(baseline_px + descent, 3),
            })

    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        """Lay out a paragraph list whose ``vertpos`` is relative to ``origin``."""
        ox, oy = origin_hwp
        oy += block_offset_hwp
        for para in paragraphs:
            self.counts["paragraphs"] += 1
            self.counts["runs"] += len(_kids(para.el, "run"))
            if para.tabs:
                self._skip("hp:tab", "tab stops are not resolved; the cached "
                                     "line box absorbs them")
            self._render_floating(draw, para, (ox, oy))
            if not para.chars:
                continue
            if para.linesegs:
                self._render_cached_lines(draw, para, (ox, oy), avail_w_hwp)
            else:
                self._skip("hp:linesegarray",
                           "paragraph carries no cached layout; own greedy "
                           "wrap used instead")
                self._render_wrapped(draw, para, (ox, oy), avail_w_hwp)

    def _render_cached_lines(self, draw, para, origin_hwp, avail_w_hwp):
        ox, oy = origin_hwp
        positions = [_iattr(s, "textpos") for s in para.linesegs]
        if positions and max(positions) > len(para.chars):
            # textpos disagrees with the character stream we reconstructed —
            # most likely an inline control this tier does not count.  Say so
            # and fall back rather than slicing text onto the wrong lines.
            self._skip("hp:lineseg@textpos",
                       "cached line offsets exceed the reconstructed character "
                       "stream; own greedy wrap used for this paragraph")
            self._render_wrapped(draw, para, origin_hwp, avail_w_hwp)
            return
        for i, seg in enumerate(para.linesegs):
            start = positions[i]
            end = positions[i + 1] if i + 1 < len(positions) else len(para.chars)
            chunk = para.chars[start:end]
            if not chunk:
                continue
            horzpos = _iattr(seg, "horzpos")
            horzsize = _iattr(seg, "horzsize") or avail_w_hwp
            baseline = _iattr(seg, "baseline")
            vertpos = _iattr(seg, "vertpos")
            self._draw_line(
                draw,
                self._line_items(para, chunk, start),
                ox + horzpos,
                oy + vertpos,
                oy + vertpos + baseline,
                para.align,
                horzsize,
            )

    def _render_wrapped(self, draw, para, origin_hwp, avail_w_hwp):
        ox, oy = origin_hwp
        avail_px = self.pxf(avail_w_hwp)
        cid = para.chars[0][1] if para.chars else None
        pt = self._charpr(cid).get("height_pt") or 10.0
        line_h = pt * HWPUNIT_PER_PT * 1.6
        baseline = pt * HWPUNIT_PER_PT * 0.85
        y = oy
        if para.linesegs:
            y = oy + _iattr(para.linesegs[0], "vertpos")
        consumed = 0
        for line in self._greedy_wrap(draw, para.chars, avail_px):
            self._draw_line(draw, self._line_items(para, line, consumed),
                            ox, y, y + baseline, para.align, avail_w_hwp)
            consumed += len(line)
            y += line_h

    # -- anchored (non-inline) objects -----------------------------------
    def _object_line(self, para, char_index):
        """The cached line box an object anchored at ``char_index`` sits on."""
        chosen = None
        for seg in para.linesegs:
            if _iattr(seg, "textpos") <= char_index:
                chosen = seg
            else:
                break
        return chosen or (para.linesegs[0] if para.linesegs else None)

    def _render_floating(self, draw, para, origin_hwp):
        """Place ``treatAsChar="0"`` objects from their own anchor offsets.

        ``hp:pos`` names the frame each offset is measured against.  PARA and
        COLUMN both resolve to the container the paragraph lives in (this tier
        does not implement multi-column text), PAGE/PAPER to the sheet origin.
        Text does not flow around these objects — that is recorded, not faked.
        """
        ox, oy = origin_hwp
        for char_index, name, el, _charpr in para.objects:
            record = para.object_at.get(char_index)
            if record is None or not record[3]:
                continue
            pos = _kid(el, "pos")
            seg = self._object_line(para, char_index)
            para_top = oy + (_iattr(seg, "vertpos") if seg is not None else 0)
            hrel = (pos.get("horzRelTo") or "PARA").upper()
            vrel = (pos.get("vertRelTo") or "PARA").upper()
            x = (0 if hrel in ("PAGE", "PAPER") else ox) + _iattr(pos, "horzOffset")
            if vrel in ("PAGE", "PAPER"):
                y = _iattr(pos, "vertOffset")
            elif vrel in ("PARA", "PARAGRAPH"):
                y = para_top + _iattr(pos, "vertOffset")
            else:
                y = oy + _iattr(pos, "vertOffset")
            self._skip(f"hp:{name}@pos",
                       f"anchored object (treatAsChar=0, horzRelTo={hrel}, "
                       f"vertRelTo={vrel}) placed at its declared offset; "
                       "text wrap around it is not computed")
            if name == "tbl":
                self._render_table(draw, el, (x, y))
            else:
                self._render_placeholder(draw, el, name, (x, y))

    def _render_placeholder(self, draw, el, name, origin_hwp):
        """An honest box where art would be, never a silent hole."""
        ox, oy = origin_hwp
        sz = _kid(el, "sz")
        w = _iattr(sz, "width") if sz is not None else 0
        h = _iattr(sz, "height") if sz is not None else 0
        extent_known = bool(w and h)
        if not extent_known:
            w = w or 6000
            h = h or 3000
            self._skip(f"hp:{name}",
                       "object drawn as a placeholder box with UNKNOWN extent "
                       "(no hp:sz); the box size is a fallback, not the file's")
        else:
            self._skip(f"hp:{name}",
                       "object drawn as a placeholder box at its declared "
                       "hp:sz extent; its content is not rendered")
        x0, y0 = self.px(ox), self.px(oy)
        x1, y1 = self.px(ox + w), self.px(oy + h)
        if x1 <= x0:
            x1 = x0 + 1
        if y1 <= y0:
            y1 = y0 + 1
        draw.rectangle([x0, y0, x1, y1], outline=(150, 150, 150),
                       width=max(1, self.dpi // 144))
        label = PLACEHOLDER_LABELS.get(name, name)
        if not extent_known:
            label += " ?"
        font = self.fontbook.get(self.pt_to_px(8.0))
        draw.text(((x0 + x1) / 2, (y0 + y1) / 2), label, font=font,
                  fill=(150, 150, 150), anchor="mm")
        self.counts["placeholders"] += 1

    # -- tables ----------------------------------------------------------
    def _table_tracks(self, tbl):
        rows = _iattr(tbl, "rowCnt", 0)
        cols = _iattr(tbl, "colCnt", 0)
        sz = _kid(tbl, "sz")
        decl_w = _iattr(sz, "width") if sz is not None else None
        decl_h = _iattr(sz, "height") if sz is not None else None
        col_cons, row_cons, cells = [], [], []
        for tr in _kids(tbl, "tr"):
            for tc in _kids(tr, "tc"):
                addr = _kid(tc, "cellAddr")
                span = _kid(tc, "cellSpan")
                size = _kid(tc, "cellSz")
                cmargin = _kid(tc, "cellMargin")
                if addr is None or size is None:
                    self._skip("hp:tc", "cell without cellAddr/cellSz skipped")
                    continue
                row = _iattr(addr, "rowAddr")
                col = _iattr(addr, "colAddr")
                rspan = max(1, _iattr(span, "rowSpan", 1))
                cspan = max(1, _iattr(span, "colSpan", 1))
                width = _iattr(size, "width")
                height = _iattr(size, "height")
                mt = _iattr(cmargin, "top")
                mb = _iattr(cmargin, "bottom")
                paras = [Paragraph(p, self.defs["para_pr"])
                         for p in own_paragraphs(tc)]
                content_h = max((p.extent_hwp() for p in paras), default=0)
                col_cons.append((col, cspan, width))
                # cellSz height is a *minimum*: HWP grows a row to fit its
                # content and leaves the stored value behind.  Taking the max
                # of the two is what tracks the declared table height.
                row_cons.append((row, rspan, max(height, content_h + mt + mb)))
                cells.append({
                    "tc": tc, "row": row, "col": col,
                    "rspan": rspan, "cspan": cspan,
                    "margin": {
                        "left": _iattr(cmargin, "left"),
                        "right": _iattr(cmargin, "right"),
                        "top": mt, "bottom": mb,
                    },
                    "paras": paras,
                })
        widths = solve_tracks(cols, col_cons, decl_w)
        heights = solve_tracks(rows, row_cons, decl_h)
        xs = [0]
        for w in widths:
            xs.append(xs[-1] + w)
        ys = [0]
        for h in heights:
            ys.append(ys[-1] + h)
        return xs, ys, cells

    def _render_table(self, draw, tbl, origin_hwp):
        ox, oy = origin_hwp
        self.counts["tables"] += 1
        xs, ys, cells = self._table_tracks(tbl)
        if not cells:
            return
        rects = []
        for cell in cells:
            self.counts["cells"] += 1
            c0 = min(cell["col"], len(xs) - 1)
            c1 = min(cell["col"] + cell["cspan"], len(xs) - 1)
            r0 = min(cell["row"], len(ys) - 1)
            r1 = min(cell["row"] + cell["rspan"], len(ys) - 1)
            rects.append((cell, ox + xs[c0], oy + ys[r0],
                          ox + xs[c1], oy + ys[r1]))

        # 1. fills, 2. borders, 3. content — so a neighbour's fill can never
        #    paint over a border that is already down.
        for cell, x0, y0, x1, y1 in rects:
            bf = self.defs["border_fill"].get(
                cell["tc"].get("borderFillIDRef") or "")
            if bf and bf.get("fill"):
                draw.rectangle([self.px(x0), self.px(y0),
                                self.px(x1), self.px(y1)], fill=bf["fill"])
        for cell, x0, y0, x1, y1 in rects:
            self._draw_cell_borders(draw, cell, x0, y0, x1, y1)
        for cell, x0, y0, x1, y1 in rects:
            self._render_cell_content(draw, cell, x0, y0, x1, y1)

    def _draw_cell_borders(self, draw, cell, x0, y0, x1, y1):
        bf = self.defs["border_fill"].get(cell["tc"].get("borderFillIDRef") or "")
        if not bf:
            self._skip("hh:borderFill",
                       "cell references an undefined borderFill; no border drawn")
            return
        edges = {
            "left": ((x0, y0), (x0, y1)),
            "right": ((x1, y0), (x1, y1)),
            "top": ((x0, y0), (x1, y0)),
            "bottom": ((x0, y1), (x1, y1)),
        }
        for side, ((ax, ay), (bx, by)) in edges.items():
            spec = bf.get(side) or {}
            btype = (spec.get("type") or "NONE").upper()
            if btype == "NONE":
                continue
            if btype != "SOLID":
                self._skip(f"hh:{side}Border@type={btype}",
                           "non-solid border stroked as solid")
            width = max(1, self.px(spec.get("width_hwp") or 0))
            draw.line([(self.px(ax), self.px(ay)), (self.px(bx), self.px(by))],
                      fill=spec.get("color") or (0, 0, 0), width=width)
            self.counts["borders"] += 1

    def _render_cell_content(self, draw, cell, x0, y0, x1, y1):
        margin = cell["margin"]
        cx = x0 + margin["left"]
        cy = y0 + margin["top"]
        avail_w = max(0, (x1 - x0) - margin["left"] - margin["right"])
        avail_h = max(0, (y1 - y0) - margin["top"] - margin["bottom"])
        sub = _kid(cell["tc"], "subList")
        valign = (sub.get("vertAlign") if sub is not None else "TOP") or "TOP"
        block = max((p.extent_hwp() for p in cell["paras"]), default=0)
        offset = 0
        if valign.upper() == "CENTER":
            offset = max(0, (avail_h - block) // 2)
        elif valign.upper() == "BOTTOM":
            offset = max(0, avail_h - block)
        self._render_paragraphs(draw, cell["paras"], (cx, cy), avail_w, offset)

    # -- top level -------------------------------------------------------
    def _audit_unsupported(self):
        """Name every element local-name this tier has no handler for."""
        handled = (STRUCTURAL_TAGS | set(PLACEHOLDER_LABELS)
                   | {"linesegarray", "lineseg"})
        seen = {}
        for root in self.sections:
            for el in root.iter():
                name = _local(el.tag)
                if name in handled:
                    continue
                seen[name] = seen.get(name, 0) + 1
        for name, count in sorted(seen.items()):
            self._skip(f"hp:{name}",
                       "element has no handler in this tier; nothing drawn")
            self.skipped[(f"hp:{name}",
                          "element has no handler in this tier; nothing drawn"
                          )]["count"] = count

    def render(self):
        geo = self.page_geometry()
        pages = self.paginate()
        page_w = self.px(geo["width"])
        page_h = self.px(geo["height"])
        images = []
        for page_number, page_paras in enumerate(pages, start=1):
            self._page = page_number
            img = self.Image.new("RGB", (page_w, page_h), (255, 255, 255))
            draw = self.ImageDraw.Draw(img)
            self._render_paragraphs(
                draw, page_paras,
                (geo["body_left"], geo["body_top"]),
                geo["usable_width"],
            )
            images.append(img)
        self._audit_unsupported()
        sidecar = {
            "renderer": RENDERER_STAMP,
            "renderer_version": RENDERER_VERSION,
            "grade": GRADE,
            "grade_meaning": (
                "rendered by Rigorloom's own OWPML renderer; NOT certified "
                "against a Hancom reference render. Certification is per "
                "document class via pipeline/scripts/render_cert.py."
            ),
            "source": self.path.name,
            "dpi": self.dpi,
            "pages": len(images),
            "page_size_px": [page_w, page_h],
            "page_geometry_hwpunit": geo,
            "hwpunit_per_inch": HWPUNIT_PER_INCH,
            "fonts": dict(self.fonts_meta, note=(
                "every HWP face in the document is rasterised with this one "
                "family; advance widths therefore differ from the authoring "
                "engine's")),
            "elements_rendered": dict(self.counts),
            "line_boxes": list(self.line_boxes),
            "line_boxes_meaning": (
                "every text line box drawn, in device pixels at this render's "
                "dpi; y bounds are the font's ascent/descent about the cached "
                "baseline, x bounds are the measured text extent (inline "
                "objects excluded). The comparison channel "
                "engine/scripts/render_scoreboard.py pairs these against a "
                "reference PDF's text lines."
            ),
            "elements_skipped": sorted(
                self.skipped.values(),
                key=lambda e: (e["element"], e["reason"])),
            "notes": self.notes,
        }
        return images, sidecar


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def save_png(image, path):
    """Write a PNG with no timestamp chunk and a pinned compression level."""
    image.save(path, format="PNG", optimize=False, compress_level=6)


def render_to_dir(hwpx_path, out_dir, dpi=DEFAULT_DPI, stem=None):
    renderer = OwnRenderer(hwpx_path, dpi=dpi)
    images, sidecar = renderer.render()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or Path(hwpx_path).stem
    written = []
    for index, image in enumerate(images, start=1):
        target = out_dir / f"{stem}-p{index}.png"
        save_png(image, target)
        written.append(str(target))
    sidecar["png_pages"] = [Path(p).name for p in written]
    sidecar_path = out_dir / f"{stem}.render.json"
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return {"pngs": written, "sidecar": str(sidecar_path), "report": sidecar}


def render_to_pdf(hwpx_path, out_pdf, dpi=DEFAULT_DPI):
    """Raster PDF, for the ``[binary, {in}, {out}]`` argv render_cert expects.

    The pages carry no text layer, so ``render_cert``'s unique-word anchor
    channel cannot score this output — only page count and the raster channel
    can.  A vector text backend is the prerequisite for full certification;
    see engine/references/own-render-notes.md.
    """
    renderer = OwnRenderer(hwpx_path, dpi=dpi)
    images, sidecar = renderer.render()
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    head, rest = images[0], images[1:]
    head.save(out_pdf, format="PDF", save_all=bool(rest), append_images=rest,
              resolution=float(dpi))
    return {"pdf": str(out_pdf), "report": sidecar}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="own_render.py",
        description="Render an HWPX (OWPML) form to page PNGs with Rigorloom's "
                    "own uncertified renderer.")
    parser.add_argument("--version", action="store_true",
                        help="print the renderer version and exit")
    parser.add_argument("input", nargs="?", help="input .hwpx")
    parser.add_argument("output", nargs="?",
                        help="optional output .pdf (render_cert argv shape)")
    parser.add_argument("--out-dir", help="directory for per-page PNG + sidecar")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--stem", help="override the output filename stem")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"{RENDERER_ID} {RENDERER_VERSION}")
        return 0
    if not args.input:
        print("own_render: an input .hwpx is required", file=sys.stderr)
        return 2
    try:
        if args.output:
            result = render_to_pdf(args.input, args.output, dpi=args.dpi)
        else:
            out_dir = args.out_dir or Path(args.input).with_suffix("").name + "-render"
            result = render_to_dir(args.input, out_dir, dpi=args.dpi,
                                   stem=args.stem)
    except RendererUnavailable as exc:
        print(f"own_render: unavailable — {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f"own_render: {exc}", file=sys.stderr)
        return 2
    report = result.pop("report")
    print(json.dumps({**result, "report": report},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
