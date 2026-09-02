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
import math
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

# --------------------------------------------------------------------------
# Line geometry, read off the corpus rather than assumed
# --------------------------------------------------------------------------
# Every relation below was measured across all 3214 <hp:lineseg> elements of
# the ten committed corpus forms before any of it was implemented, and each
# one is pinned by a test in engine/tests/test_own_render.py:
#
#   vertsize == textheight                                  3214 / 3214
#   baseline == round(0.85 * textheight)                    3212 exact,
#                                                           3214 within 1
#   vertpos[i] == vertpos[i-1] + vertsize[i-1] + spacing[i-1]
#                                                            219 / 219
#                                                           (every
#                                                           continuation line
#                                                           in the corpus)
#   (vertsize + spacing) / textheight == lineSpacing@value / 100
#                                                           for every PERCENT
#                                                           paragraph
#
# The 0.85 is HWP's baseline convention: the baseline sits 85% of the way down
# the character cell.  It is a *measured constant of this corpus*, not a number
# KS X 6101 publishes, and it is declared as such in every sidecar.
BASELINE_RATIO = 0.85

# --------------------------------------------------------------------------
# Line breaking (UAX #14 class, Korean rules as hh:breakSetting declares them)
# --------------------------------------------------------------------------
# hp:paraPr/hh:breakSetting carries the two attributes that decide where a line
# may break:
#
#   breakNonLatinWord   KEEP_WORD  (어절 단위) — Hangul/CJK breaks only at word
#                                  boundaries, i.e. at spaces
#                       BREAK_WORD (글자 단위) — Hangul/CJK breaks between any
#                                  two syllables
#   breakLatinWord      KEEP_WORD  (단어)     — Latin breaks only at spaces
#                       BREAK_WORD (글자)     — Latin breaks between letters
#                       HYPHENATION (하이픈)  — hyphenated; NOT implemented,
#                                  treated as KEEP_WORD and named in the
#                                  sidecar
#
# Corpus census (774 paraPr definitions): breakLatinWord KEEP_WORD 669 /
# BREAK_WORD 104 / HYPHENATION 1; breakNonLatinWord KEEP_WORD 592 /
# BREAK_WORD 182; lineWrap BREAK 774 (the only value present).

# 금칙처리 — the characters Korean typesetting forbids at a line boundary.
# KS X 6101 does not publish the set (it is an implementing engine's table),
# so this is the conventional Korean/CJK prohibition list and is declared as
# this renderer's table in the sidecar, exactly as the language-slot partition
# is.
LINE_START_PROHIBITED = frozenset(
    "!%),.:;?]}¢°'\"‰′″℃、。｝〉》」』】〕）］｝，．：；？！"
    "’”ゝゞーぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ"
    "々〆·ㆍ…‥"
)
LINE_END_PROHIBITED = frozenset(
    "$([\\{£¥‵〈《「『【〔（［｛＄￥￦＃＠‘“#@"
)
# UAX #14 class BA/HY: a break is always allowed *after* these, whatever the
# word-integrity attributes say.
BREAK_AFTER_ALWAYS = frozenset("-–—/")
SPACE_CHARS = frozenset(" \t 　")

# HWP's default tab interval when hh:tabPr declares no explicit stop.  THIS IS
# THIS RENDERER'S CHOICE, not the standard's: 8 corpus tabPr definitions carry
# no <hh:tab> child at all, and the format does not carry the interval, so a
# renderer reading only the file has to pick one.  40 pt is HWP's documented
# default 탭 간격.  Declared in the sidecar, never presented as the spec.
DEFAULT_TAB_INTERVAL_HWP = 40 * HWPUNIT_PER_PT


# Line-layout policy.  ``auto`` is the lineseg mode: the authoring engine's
# cached boxes wherever they are present and still describe the text.
LINE_LAYOUT_AUTO = "auto"
LINE_LAYOUT_COMPUTED = "computed"
LINE_LAYOUT_MODES = (LINE_LAYOUT_AUTO, LINE_LAYOUT_COMPUTED)

# How far a cached line's *font-independent lower bound* width may exceed its
# cached horzsize before the cache is judged stale.  The bound counts only
# full-width cells (whose advance in HWP is exactly the declared character
# size x hh:ratio) plus the declared hh:spacing gaps, so it can never exceed
# the true width of text the authoring engine actually fitted.  Measured
# across the corpus, the worst unedited cached line reaches 0.901 of its box
# by this bound (admrul), so 1% of headroom leaves the detector sound with
# room to spare — it raises no false positive on any of the ten corpus forms
# — while still firing on an edit that adds a syllable to a full line.
STALE_LINE_TOLERANCE = 0.01


def break_class(ch):
    """UAX #14-ish class of ``ch``, reduced to what the paraPr attributes need.

    Four classes, because ``hh:breakSetting`` only distinguishes two scripts
    plus whitespace: ``SPACE``, ``CJK`` (Hangul/Hanja/kana/CJK punctuation and
    fullwidth forms — everything ``breakNonLatinWord`` governs), ``OBJECT``
    (the inline-object slot, which behaves as a CJK cell), and ``LATIN``
    (everything ``breakLatinWord`` governs).
    """
    if ch in SPACE_CHARS:
        return "SPACE"
    if ch == OBJECT_SLOT:
        return "OBJECT"
    slot = script_slot(ch)
    if slot in ("hangul", "hanja", "japanese"):
        return "CJK"
    code = ord(ch)
    if 0x3000 <= code <= 0x303F or 0xFF01 <= code <= 0xFF60:
        return "CJK"
    return "LATIN"


def is_full_width(ch):
    """Does ``ch`` occupy a full character cell in HWP's model?

    Hangul, Hanja, kana, CJK punctuation and the fullwidth forms advance by
    exactly the declared character size (times ``hh:ratio``); Latin is
    proportional.  Used for the *font-independent* lower bound that decides
    whether a cached line box can still be holding the text it claims to.
    """
    return break_class(ch) in ("CJK", "OBJECT")


def break_opportunities(text, break_latin="KEEP_WORD",
                        break_non_latin="KEEP_WORD"):
    """Indices ``i`` at which a line may end before ``text[i]``.

    Returned ascending.  Index 0 is never an opportunity (a line cannot be
    empty); ``len(text)`` is not returned either (the paragraph end is not a
    break).  The 금칙 filter is applied last and uniformly, so it removes a
    space break just as it removes a syllable break.
    """
    ops = []
    for i in range(1, len(text)):
        a, b = text[i - 1], text[i]
        ca, cb = break_class(a), break_class(b)
        if cb == "SPACE":
            # Never break before a space: trailing spaces hang off the line
            # end, they do not start the next one.
            continue
        if ca == "SPACE":
            allowed = True
        elif a in BREAK_AFTER_ALWAYS:
            allowed = True
        elif ca in ("CJK", "OBJECT") or cb in ("CJK", "OBJECT"):
            allowed = (break_non_latin == "BREAK_WORD")
        else:
            allowed = (break_latin == "BREAK_WORD")
        if not allowed:
            continue
        if b in LINE_START_PROHIBITED or a in LINE_END_PROHIBITED:
            continue
        ops.append(i)
    return ops

# --------------------------------------------------------------------------
# Character typography (hh:charPr children), per language slot
# --------------------------------------------------------------------------
# OWPML declares character metrics once per *language slot*, not once per
# charPr: <hh:ratio hangul="97" latin="100" .../> and the same shape for
# hh:spacing, hh:relSz and hh:offset.  The slot names below are the ones the
# format uses, in the order it lists them.
LANG_SLOTS = ("hangul", "latin", "hanja", "japanese", "other", "symbol",
              "user")

# The neutral value of each metric, i.e. what "no typography" means.
#   ratio   — horizontal glyph scale, percent
#   spacing — letter spacing, percent of the character size
#   relSz   — relative character size, percent
#   offset  — baseline shift, percent of the character size (positive = up)
TYPOGRAPHY_DEFAULTS = {"ratio": 100, "spacing": 0, "relSz": 100, "offset": 0}
NEUTRAL_TYPOGRAPHY = (100, 0, 100, 0)

# Codepoint -> language slot.  THIS TABLE IS THIS RENDERER'S CHOICE, not the
# standard's: KS X 6101 names the slots and says a character is metered by the
# slot its script belongs to, but it does not publish the codepoint partition
# (that is an implementing engine's detail).  The ranges below are the plain
# Unicode block reading of each slot name, and they are declared as an
# approximation in the sidecar rather than presented as the spec.
#
# ``user`` is never selected by any codepoint: it is the slot HWP assigns from
# a user-defined character range table that the document does not carry, so a
# renderer reading only the file cannot honour it.  Named, not silently merged.
_SLOT_RANGES = (
    ("hangul", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F),
                (0xAC00, 0xD7FB), (0xFFA0, 0xFFDC))),
    ("japanese", ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D))),
    ("hanja", ((0x2E80, 0x2FDF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
               (0xF900, 0xFAFF), (0x20000, 0x2FA1F))),
    ("latin", ((0x0030, 0x0039), (0x0041, 0x005A), (0x0061, 0x007A),
               (0x00C0, 0x024F), (0x1E00, 0x1EFF))),
    ("symbol", ((0x0020, 0x002F), (0x003A, 0x0040), (0x005B, 0x0060),
                (0x007B, 0x007E), (0x00A1, 0x00BF), (0x2000, 0x206F),
                (0x2100, 0x2BFF), (0x3000, 0x303F), (0xFF01, 0xFF65),
                (0xFFE0, 0xFFEE))),
)


def script_slot(ch):
    """Which ``hh:charPr`` language slot meters ``ch``.  See ``_SLOT_RANGES``."""
    code = ord(ch)
    for slot, ranges in _SLOT_RANGES:
        for low, high in ranges:
            if low <= code <= high:
                return slot
    return "other"

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


def _para_pr_geometry_source(pp):
    """The ``hh:paraPr`` branch a reader without the 2016 extension must take.

    Every corpus ``hh:paraPr`` wraps its ``hh:margin`` and ``hh:lineSpacing``
    in ``<hh:switch><hh:case hp:required-namespace="…/2016/HwpUnitChar">…
    </hh:case><hh:default>…</hh:default></hh:switch>`` — the MCE pattern.  The
    ``case`` branch states the same quantities in the 2016 *character* unit
    (measured: its margins are consistently half the default branch's), so a
    renderer that does not implement that namespace takes ``default``.  774 of
    774 corpus paraPr carry the switch; 477 of them differ between the two
    branches, so picking the wrong one is not cosmetic.
    """
    switch = _kid(pp, "switch")
    if switch is None:
        return pp
    default = _kid(switch, "default")
    return default if default is not None else pp


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
        typography = {}
        for metric, default in TYPOGRAPHY_DEFAULTS.items():
            el = _kid(cp, metric)
            slots = {}
            for slot in LANG_SLOTS:
                raw = el.get(slot) if el is not None else None
                try:
                    slots[slot] = int(raw) if raw is not None else default
                except (TypeError, ValueError):
                    slots[slot] = default
            typography[metric] = slots
        char_pr[cid] = {
            "typography": typography,
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
        geometry = _para_pr_geometry_source(pp)
        margin = _kid(geometry, "margin")
        spacing = _kid(geometry, "lineSpacing")
        brk = _kid(pp, "breakSetting")

        def _margin(name):
            el = _kid(margin, name) if margin is not None else None
            return _iattr(el, "value", 0)

        def _brk(name, default):
            raw = brk.get(name) if brk is not None else None
            return (raw or default).upper()

        para_pr[pid] = {
            "align": (align.get("horizontal") if align is not None else None) or "LEFT",
            # hh:breakSetting — where a line may break.
            "break_latin": _brk("breakLatinWord", "KEEP_WORD"),
            "break_non_latin": _brk("breakNonLatinWord", "KEEP_WORD"),
            "line_wrap": _brk("lineWrap", "BREAK"),
            # Parsed and reported, NOT honoured — they are block-level
            # (pagination) rules and this tier does not do block layout.
            "widow_orphan": _iattr(brk, "widowOrphan"),
            "keep_with_next": _iattr(brk, "keepWithNext"),
            "keep_lines": _iattr(brk, "keepLines"),
            "page_break_before": _iattr(brk, "pageBreakBefore"),
            # hp:paraPr attributes.
            "condense": _iattr(pp, "condense"),
            "font_line_height": _iattr(pp, "fontLineHeight"),
            "snap_to_grid": _iattr(pp, "snapToGrid"),
            "tab_pr": pp.get("tabPrIDRef"),
            # hh:lineSpacing / hh:margin, from the branch a reader that does
            # not implement the 2016 HwpUnitChar extension must take.
            "line_spacing_type": (
                (spacing.get("type") if spacing is not None else None)
                or "PERCENT").upper(),
            "line_spacing_value": _iattr(spacing, "value", 100),
            "line_spacing_unit": (
                (spacing.get("unit") if spacing is not None else None)
                or "HWPUNIT").upper(),
            "margin_left": _margin("left"),
            "margin_right": _margin("right"),
            "indent": _margin("intent"),
        }

    tab_pr = {}
    for tp in root.iter():
        if _local(tp.tag) != "tabPr":
            continue
        tid = tp.get("id")
        if tid is None:
            continue
        stops = sorted(
            (_iattr(t, "pos"), (t.get("type") or "LEFT").upper())
            for t in _kids(tp, "tab"))
        tab_pr[tid] = {
            "stops": stops,
            "auto_left": _iattr(tp, "autoTabLeft"),
            "auto_right": _iattr(tp, "autoTabRight"),
        }

    return {
        "char_pr": char_pr,
        "border_fill": border_fill,
        "para_pr": para_pr,
        "tab_pr": tab_pr,
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


# Directories a system keeps its installed faces in.  Searched in order; a
# missing directory is simply skipped.
_SYSTEM_FONT_DIRS = (
    r"C:\Windows\Fonts",
    "~/AppData/Local/Microsoft/Windows/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
)
_FONT_SUFFIXES = (".ttf", ".ttc", ".otf", ".otc")

# HWP writes the 한양 (Hanyang) foundry's faces with a 한양 prefix where the
# font files' own name records use HY (한양신명조 vs HY신명조).  This is the one
# systematic difference between what documents declare and what the installed
# faces call themselves; everything else matches a name record directly.
_FACE_PREFIX_ALIASES = (("한양", "hy"),)


def _normalise_face(name):
    """Casefold and drop the separators family names are inconsistent about."""
    if not name:
        return ""
    return re.sub(r"[\s\-_]+", "", str(name)).casefold()


def _sfnt_name_records(path):
    """``[(face_index, {nameID: {text, ...}})]`` from a font file's name table.

    Reads the OpenType ``name`` table straight out of the file — the public
    format spec, seeked rather than slurped so a 20 MB CJK face costs a few
    kilobytes.  This is what lets a document's 함초롬돋움 / 바탕 / HY신명조
    resolve at all: the faces carry their Korean family names in their own
    name records, and FreeType (hence Pillow) only ever exposes the English
    one.
    """
    import struct
    out = []
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12:
                return out
            if head[:4] == b"ttcf":
                count = struct.unpack_from(">I", head, 8)[0]
                if count > 64:
                    return out
                raw = fh.read(4 * count)
                if len(raw) < 4 * count:
                    return out
                bases = list(struct.unpack(">" + "I" * count, raw))
            else:
                bases = [0]
            for index, base in enumerate(bases):
                fh.seek(base + 4)
                raw = fh.read(2)
                if len(raw) < 2:
                    continue
                tables = struct.unpack(">H", raw)[0]
                fh.seek(base + 12)
                directory = fh.read(16 * tables)
                offset = None
                for i in range(tables):
                    record = directory[16 * i:16 * i + 16]
                    if len(record) < 16:
                        break
                    if record[:4] == b"name":
                        offset = struct.unpack_from(">I", record, 8)[0]
                        break
                if offset is None:
                    continue
                fh.seek(offset)
                header = fh.read(6)
                if len(header) < 6:
                    continue
                _fmt, count, strings = struct.unpack(">HHH", header)
                records = fh.read(12 * count)
                fh.seek(offset + strings)
                pool = fh.read(1 << 20)
                names = {}
                for i in range(count):
                    chunk = records[12 * i:12 * i + 12]
                    if len(chunk) < 12:
                        break
                    pid, _eid, _lid, nid, length, off = struct.unpack(
                        ">HHHHHH", chunk)
                    blob = pool[off:off + length]
                    if len(blob) != length:
                        continue
                    try:
                        if pid in (0, 3):
                            text = blob.decode("utf-16-be")
                        elif pid == 1:
                            text = blob.decode("mac-roman")
                        else:
                            continue
                    except (UnicodeDecodeError, LookupError):
                        continue
                    if text:
                        names.setdefault(nid, set()).add(text)
                if names:
                    out.append((index, names))
    except (OSError, ValueError, IndexError):
        return []
    return out


class SystemFontIndex:
    """Installed faces, keyed by every family name they declare.

    Built once per process and shared, because a document asks for a handful
    of families and the scan reads a few hundred files.  Deterministic: the
    directories are searched in a fixed order and each directory's entries are
    sorted, so two runs on one machine resolve the same file every time.
    """

    _shared = None

    def __init__(self, directories=None):
        import os
        self.families = {}
        self.scanned = 0
        directories = directories or _SYSTEM_FONT_DIRS
        for raw in directories:
            base = Path(os.path.expanduser(raw))
            if not base.is_dir():
                continue
            try:
                paths = sorted(
                    p for p in base.rglob("*")
                    if p.suffix.lower() in _FONT_SUFFIXES and p.is_file())
            except OSError:
                continue
            for path in paths:
                self.scanned += 1
                for index, names in _sfnt_name_records(path):
                    subfamilies = {t.casefold()
                                   for t in (names.get(2, set())
                                             | names.get(17, set()))}
                    bold = any("bold" in s for s in subfamilies)
                    for nid in (16, 1, 4, 6):
                        for text in sorted(names.get(nid, ())):
                            key = _normalise_face(text)
                            if not key:
                                continue
                            entry = self.families.setdefault(
                                key, {"regular": None, "bold": None,
                                      "family": text})
                            slot = "bold" if bold else "regular"
                            if entry[slot] is None:
                                entry[slot] = (str(path), index)

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def lookup(self, face_name):
        """The installed face a document's declared face name names, or None."""
        key = _normalise_face(face_name)
        if not key:
            return None
        hit = self.families.get(key)
        if hit is not None:
            return hit
        for declared, installed in _FACE_PREFIX_ALIASES:
            prefix = _normalise_face(declared)
            if key.startswith(prefix):
                hit = self.families.get(installed + key[len(prefix):])
                if hit is not None:
                    return hit
        return None


def resolve_fonts(repo_root: Path | None = None) -> dict:
    """The fallback face — what a document's *unresolvable* faces render with.

    Faces the document declares are resolved individually against the system
    font index (``SystemFontIndex``).  This is the face that stands in when a
    declared family is not installed, and it is the *only* face used when
    ``RIGORLOOM_OWN_RENDER_FONT`` pins one.  Substitution is always named per
    face in the sidecar.
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
    """Deterministic (path, face index, px) -> ImageFont cache.

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

    def fallback(self, bold: bool = False):
        return (self._paths["bold" if bold else "regular"], 0)

    def get(self, size_px: int, bold: bool = False, face=None):
        """``face`` is ``(path, index)``; ``None`` means the fallback face."""
        size_px = max(1, int(size_px))
        path, index = face if face else self.fallback(bold)
        key = (path, index, size_px)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        kwargs = {"index": index} if index else {}
        if self._layout is not None:
            kwargs["layout_engine"] = self._layout.BASIC
        try:
            font = self._ImageFont.truetype(path, size_px, **kwargs)
        except OSError:
            path, index = self.fallback(bold)
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
    def __init__(self, hwpx_path, dpi=DEFAULT_DPI, repo_root=None,
                 line_layout=LINE_LAYOUT_AUTO, relayout_paragraphs=None):
        self.path = Path(hwpx_path)
        self.dpi = int(dpi)
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")
        if line_layout not in LINE_LAYOUT_MODES:
            raise ValueError(
                f"line_layout must be one of {sorted(LINE_LAYOUT_MODES)}")
        # ``auto``     — a paragraph keeps the authoring engine's cached
        #                hp:lineseg boxes unless they are provably stale, in
        #                which case this renderer's own breaker lays it out.
        # ``computed`` — every paragraph is laid out by this renderer's
        #                breaker.  This is the mode that measures the breaker
        #                itself; it is not the mode that renders a document
        #                most faithfully.
        self.line_layout = line_layout
        # Paragraph identities (``id(hp:p element)`` is useless across parses,
        # so this is document-order index within section0's top-level flow,
        # counted the way ``paragraph_index`` below counts) that the CALLER
        # knows it edited.  An edit that neither shortens the text past the
        # cache nor overflows a cached line cannot be detected from the file,
        # so the edit path must say so; this is that channel.
        self.relayout_paragraphs = set(relayout_paragraphs or ())
        self.Image, self.ImageDraw, self._ImageFont = _require_pillow()
        self.fonts_meta = resolve_fonts(repo_root)
        self.fontbook = FontBook(self.fonts_meta)
        # A pinned face means "rasterise everything with this one", which is
        # what a machine-independent certification run wants; otherwise the
        # document's own declared faces are resolved against the system.
        self.pinned_face = self.fonts_meta.get("source") == "env"
        self.font_index = (None if self.pinned_face
                           else SystemFontIndex.shared())
        self.face_resolution = {}
        self._face_cache = {}
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
        self._image = None
        self._typo_cache = {}
        # Which character metrics this document actually exercised, counted in
        # characters.  The honesty rule cuts both ways: the sidecar has to say
        # what was *applied*, not only what was skipped, or "we apply hh:ratio"
        # would be unfalsifiable on a document that never declares one.
        self.applied = {}
        # Per-paragraph line-layout provenance: which engine laid out each
        # paragraph's lines, and — where it was this renderer — why.
        self.layout_records = []
        self.paragraph_index = {}
        # >0 while a measurement pass runs (a table row asking how tall its
        # content is).  Skips and forced-break counts are suppressed there so
        # the sidecar counts what was *drawn*, once, not what was measured.
        self._quiet = 0
        self._layout_counts = {"lineseg": 0, "computed": 0}
        self._layout_reasons = {}
        self._forced_breaks = 0
        # Which engine is laying out the line currently being drawn; stamped
        # onto every line box so a reader of the sidecar can tell, per line,
        # whether they are looking at Hancom's break or ours.
        self._line_mode = "lineseg"
        # Standing caveats that apply to every render, not just this document.
        # They belong in the artefact, not only in the notes file, because the
        # sidecar is what travels with the PNG.
        self.notes = [
            "line boxes come from the document's own cached hp:lineseg layout "
            "wherever that cache is present and provably still describes the "
            "paragraph's text; where it is not, this renderer's own line "
            "breaker lays the paragraph out and line_layout says which "
            "paragraphs and why",
            "line breaking therefore matches the authoring engine exactly on "
            "an unedited paragraph, and is this renderer's own answer on an "
            "edited one; intra-line text extents match neither (see fonts)",
            "character typography (hh:ratio, hh:spacing, hh:relSz, hh:offset) "
            "IS applied, per language slot; see typography for what this "
            "document exercised and typography_slot_model for how a character "
            "is assigned to a slot",
            "hh:spacing opens a gap BETWEEN characters (n-1 gaps per line, no "
            "trailing gap), measured against the Hancom reference render",
            "hh:align JUSTIFY stretches every line of a paragraph except its "
            "last; DISTRIBUTE stretches every line; neither ever shrinks a "
            "line that already overruns its box",
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
        # Paragraph identity, and the only one this format supports: hp:p@id
        # is NOT unique (moel-2025 gives 2147483648 to 329 of its 330
        # paragraphs), so a paragraph is named by its document-order position
        # among every hp:p in section0, nested table cells included, counting
        # from 0.  An editor can compute the same number from the same file
        # without asking the renderer, which is what makes it usable as the
        # ``relayout_paragraphs`` key.
        self.paragraph_index = {
            id(el): index
            for index, el in enumerate(
                e for e in self.sections[0].iter() if _local(e.tag) == "p")
        }
        if len(self.sections) > 1:
            self._skip("multi-section document",
                       f"only section0 is laid out; {len(self.sections)} present")

    def _skip(self, element, reason, where=None):
        if self._quiet:
            return
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

    def _face_for(self, cid, slot, bold):
        """The installed face this run's ``hh:fontRef`` names for ``slot``.

        ``hh:charPr/hh:fontRef`` carries one font id *per language slot*, and
        ``hh:fontfaces`` resolves each id per slot to a face name.  That name
        is matched against the system font index by the family names the
        installed faces themselves declare — including their Korean ones,
        which is what makes 함초롬돋움 / 바탕 / HY신명조 resolvable at all.

        Returns ``(path, index)`` or ``None`` for "use the fallback face".
        Every answer is recorded in ``face_resolution`` so the sidecar can
        name, per face, what was resolved and what was substituted.
        """
        if self.font_index is None:
            return None
        key = (cid, slot, bold)
        hit = self._face_cache.get(key)
        if hit is not None:
            hit[1]["characters"] += 1
            return hit[0]
        font_ids = self._charpr(cid).get("font_ids") or {}
        face_name = None
        for key in (slot, slot.upper()):
            font_id = font_ids.get(key)
            if font_id is None:
                continue
            table = (self.defs["fontfaces"].get(slot.upper())
                     or self.defs["fontfaces"].get(slot) or {})
            face_name = table.get(font_id)
            if face_name:
                break
        if not face_name:
            record = self._declare_face(None, slot, None, bold)
            self._face_cache[key] = (None, record)
            return None
        entry = self.font_index.lookup(face_name)
        chosen = None
        if entry is not None:
            chosen = entry["bold" if bold else "regular"] or entry["regular"] \
                or entry["bold"]
        record = self._declare_face(face_name, slot,
                                    entry if chosen else None, bold)
        self._face_cache[key] = (chosen, record)
        return chosen

    def _declare_face(self, face_name, slot, entry, bold):
        key = (face_name or "(no hh:fontRef for this slot)", slot, bold)
        record = self.face_resolution.get(key)
        if record is None:
            record = {
                "declared": face_name,
                "slot": slot,
                "bold": bold,
                "resolved": entry is not None,
                "installed_family": entry["family"] if entry else None,
                "file": None,
                "characters": 0,
            }
            if entry is not None:
                picked = entry["bold" if bold else "regular"] \
                    or entry["regular"] or entry["bold"]
                if picked:
                    record["file"] = Path(picked[0]).name
                    record["face_index"] = picked[1]
            else:
                record["substituted_with"] = Path(
                    self.fonts_meta["bold" if bold else "regular"]).name
            self.face_resolution[key] = record
        record["characters"] += 1
        return record

    def _font_for(self, cid, rel_sz=100, slot="hangul"):
        cp = self._charpr(cid)
        pt = (cp.get("height_pt") or 10.0) * rel_sz / 100.0
        bold = bool(cp.get("bold"))
        return self.fontbook.get(self.pt_to_px(pt), bold,
                                 self._face_for(cid, slot, bold))

    def _typography(self, cid, ch):
        """``(ratio, spacing, relSz, offset)`` for ``ch`` under ``cid``.

        Cached per ``(charPr, slot)``: a body paragraph asks this once per
        character and the answer only varies with the character's script.
        """
        slot = script_slot(ch)
        key = (cid, slot)
        hit = self._typo_cache.get(key)
        if hit is not None:
            return hit
        typo = self._charpr(cid).get("typography")
        if typo is None:
            value = NEUTRAL_TYPOGRAPHY
        else:
            value = (typo["ratio"].get(slot, 100),
                     typo["spacing"].get(slot, 0),
                     typo["relSz"].get(slot, 100),
                     typo["offset"].get(slot, 0))
        self._typo_cache[key] = value
        return value

    def _note_typography(self, ratio, spacing, rel_sz, offset):
        """Record which character metrics this document actually exercises."""
        if ratio != 100:
            self.applied["hh:ratio"] = self.applied.get("hh:ratio", 0) + 1
        if spacing:
            self.applied["hh:spacing"] = self.applied.get("hh:spacing", 0) + 1
        if rel_sz != 100:
            self.applied["hh:relSz"] = self.applied.get("hh:relSz", 0) + 1
        if offset:
            self.applied["hh:offset"] = self.applied.get("hh:offset", 0) + 1

    def _text_pieces(self, draw, cid, text):
        """Drawable pieces for one same-``charPr`` text run.

        A maximal stretch of characters whose typography is neutral stays ONE
        piece, measured and drawn by a single Pillow call, so a document that
        declares no character metrics renders exactly as it did before this
        existed (kerning included — Pillow's BASIC layout applies the kern
        table, so splitting a Latin word into characters would change its
        width).  A character carrying any non-neutral metric becomes its own
        piece, because ``hh:spacing`` has to open a gap after it and
        ``hh:ratio`` has to scale its glyph alone.

        Returns ``[{"kind": "glyph"|"gap", "advance": px, ...}]``.  A ``gap``
        is a letter-spacing gap and is the slot justification widens.
        """
        pieces = []
        if not text:
            return pieces
        run = []          # characters accumulating into a neutral piece
        run_key = None    # (metrics, slot) the accumulated run belongs to

        def flush():
            if not run:
                return
            metrics, slot = run_key
            ratio, _spacing, rel_sz, offset = metrics
            font = self._font_for(cid, rel_sz, slot)
            chunk = "".join(run)
            width = float(draw.textlength(chunk, font=font)) * ratio / 100.0
            size_px = font.size
            pieces.append({
                "kind": "glyph", "advance": width, "text": chunk, "cid": cid,
                "font": font, "ratio": ratio, "size_px": size_px,
                "offset_px": size_px * offset / 100.0,
            })
            run.clear()

        for ch in text:
            slot = script_slot(ch)
            metrics = self._typography(cid, ch)
            self._note_typography(*metrics)
            ratio, spacing, rel_sz, offset = metrics
            neutral = metrics == NEUTRAL_TYPOGRAPHY
            key = (metrics, slot)
            # A slot change is a face change (hh:fontRef is per slot), so it
            # ends the run even when the metrics are identical.
            if neutral and run_key == (NEUTRAL_TYPOGRAPHY, slot):
                run.append(ch)
                continue
            flush()
            run_key = key
            if neutral:
                run.append(ch)
                continue
            run.append(ch)
            flush()
            if spacing:
                pieces.append({
                    "kind": "gap",
                    "advance": self._spacing_px(cid, rel_sz, spacing),
                })
        flush()
        return pieces

    def _measure(self, draw, text, cid):
        """Advance of ``text`` under ``cid``, character typography included.

        The trailing letter-spacing gap is excluded: 자간 opens space
        *between* characters.  Measured against the Hancom reference —
        gianmun's four-character 발신명의 run at 15 pt with ``spacing="50"``
        is 5.5 em wide there (4 advances + 3 gaps), not 6.0.
        """
        pieces = self._text_pieces(draw, cid, text)
        while pieces and pieces[-1]["kind"] == "gap":
            pieces.pop()
        return sum(p["advance"] for p in pieces)

    def _spacing_px(self, cid, rel_sz, spacing):
        """``hh:spacing`` in pixels: a percent of the *character size*.

        Not of the ratio-scaled advance — ``hh:ratio`` scales the glyph, 자간
        is declared against the character height.  Measured against the Hancom
        reference: gianmun's four-character 발신명의 run, 15 pt with
        ``spacing="50"``, is drawn 5.5 em wide (4 advances + 3 gaps of 0.5 em),
        and the reference PDF reports 5.496 em.
        """
        pt = (self._charpr(cid).get("height_pt") or 10.0) * rel_sz / 100.0
        return pt * self.dpi / 72.0 * spacing / 100.0

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
        """Where the line's content starts inside its box.

        The cached ``lineseg`` carries the box, never the alignment offset —
        ``horzpos`` stays 0 and ``horzsize`` stays the full column even for a
        centred line — so this is computed from the measured content width.
        ``JUSTIFY`` and ``DISTRIBUTE`` start at the left and take their slack
        through ``_justify_extra`` instead.
        """
        slack = avail_px - used_px
        if slack <= 0:
            return 0.0
        if align == "CENTER":
            return slack / 2.0
        if align == "RIGHT":
            return slack
        return 0.0

    def _justify_extra(self, align, avail_px, used_px, slots, last_line):
        """Extra width per elastic slot for JUSTIFY / DISTRIBUTE.

        Per the format's alignment semantics:
          - ``JUSTIFY`` (양쪽) stretches every line of a paragraph *except its
            last* to the full box; the last line is left-aligned.  A one-line
            paragraph is therefore entirely "last line" and is untouched —
            which is most cell content on this corpus.
          - ``DISTRIBUTE`` (배분) stretches every line including the last.

        Which slots are elastic is decided in ``_elastic_slots``.  Nothing is
        ever *shrunk*: a line already wider than its box keeps its width, so a
        font substitution that overruns cannot be hidden by pulling text back.
        """
        if align not in ("JUSTIFY", "DISTRIBUTE"):
            return 0.0
        if align == "JUSTIFY" and last_line:
            return 0.0
        slack = avail_px - used_px
        if slack <= 0 or slots <= 0:
            return 0.0
        return slack / slots

    # -- line breaking from metrics (E2.1) -------------------------------
    def _char_advance_tables(self, draw, para):
        """Per-character advance and letter-spacing gap, in device pixels.

        Two arrays rather than one, because ``hh:spacing`` opens a gap
        *between* characters: a line of ``k`` characters carries ``k``
        advances and ``k-1`` gaps, and the line breaker has to be able to drop
        the trailing one exactly the way ``_measure`` does.

        An inline object contributes its declared ``hp:sz@width``; a floating
        (``treatAsChar="0"``) object contributes nothing, because it is placed
        from its own anchor offsets and never consumes inline width.
        """
        advances = []
        gaps = []
        for index, (ch, cid) in enumerate(para.chars):
            if ch == OBJECT_SLOT:
                record = para.object_at.get(index)
                if record is not None and record[3]:
                    advances.append(0.0)          # floating: no inline width
                else:
                    element = record[1] if record else None
                    width = (self._object_extent(element)[0]
                             if element is not None else 0)
                    advances.append(self.pxf(width))
                gaps.append(0.0)
                continue
            if ch == "\t":
                advances.append(0.0)              # resolved against tab stops
                gaps.append(0.0)
                continue
            _ratio, spacing, rel_sz, _offset = self._typography(cid, ch)
            advances.append(self._measure(draw, ch, cid))
            gaps.append(self._spacing_px(cid, rel_sz, spacing)
                        if spacing else 0.0)
        return advances, gaps

    def span_width(self, draw, para, start, end):
        """Advance of ``para.chars[start:end]`` in device pixels.

        The same quantity the breaker fits against a line box: character
        advances plus the ``hh:spacing`` gaps *between* them, with no trailing
        gap.  Exposed because the measurement in ``lineseg_agreement`` has to
        ask how full the authoring engine's own line is by this renderer's
        reckoning, and it must ask with the breaker's own arithmetic.
        """
        if end <= start:
            return 0.0
        advances, gaps = self._char_advance_tables(draw, para)
        return (sum(advances[start:end]) + sum(gaps[start:end])
                - gaps[end - 1])

    def _tab_advance(self, para, x_px, column_hwp):
        """Where a ``\\t`` at ``x_px`` lands, per ``hh:tabPr``.

        Explicit ``<hh:tab pos=…>`` stops are honoured (LEFT behaviour only —
        RIGHT/CENTER/DECIMAL need the *following* text, which a left-to-right
        greedy breaker does not have yet, and are named in the sidecar).
        Where the paragraph's tabPr declares no stop at all — 23 of the 42
        corpus tabPr definitions — the interval is this renderer's declared
        default, not the file's.
        """
        table = self.defs.get("tab_pr", {}).get(para.para_pr.get("tab_pr") or "")
        here = self.hwp_from_px(x_px)
        if table and table["stops"]:
            for pos, kind in table["stops"]:
                if pos > here + 1:
                    if kind != "LEFT":
                        self._skip(f"hh:tab@type={kind}",
                                   "non-left tab stop advanced as a left stop")
                    return self.pxf(min(pos, column_hwp))
        self._skip("hh:tabPr",
                   "paragraph declares no explicit tab stop; the default "
                   f"interval used is this renderer's "
                   f"({DEFAULT_TAB_INTERVAL_HWP // HWPUNIT_PER_PT} pt), not "
                   "the file's")
        step = DEFAULT_TAB_INTERVAL_HWP
        nxt = (int(here) // step + 1) * step
        return self.pxf(min(nxt, column_hwp))

    def _line_box(self, para, index, column_hwp):
        """``(horzpos, horzsize)`` in HWPUNIT for the ``index``-th line.

        ``hh:margin`` gives ``left``/``right``/``intent``.  A positive
        ``intent`` is 들여쓰기 — the first line starts that much further in.

        A negative ``intent`` is 내어쓰기, and the textbook reading of it —
        first line at the left margin, every *continuation* line pushed in by
        its magnitude — is **not** what this corpus's cached boxes show.
        Measured over all 3214 cached line boxes, three readings score:

            horzpos == max(0, left + intent), intent on line 0 only    2860
            horzpos == left, intent never moves the box                2895
            first line at left, continuations indented by |intent|     2710

        The hanging reading is the worst of the three, so it is not
        implemented: a negative ``intent`` moves no line box here.  The other
        two are within 35 boxes of each other and the first is the plain
        reading of the attribute, so that is the one kept.
        """
        pr = para.para_pr
        left = pr.get("margin_left", 0)
        right = max(0, pr.get("margin_right", 0))
        indent = pr.get("indent", 0)
        horzpos = max(0, left + (indent if index == 0 else 0))
        return horzpos, max(1, column_hwp - horzpos - right)

    def _line_metrics(self, para, start, end):
        """``(textheight, vertsize, baseline, spacing)`` in HWPUNIT.

        Every relation here is a measurement of the corpus, listed at
        ``BASELINE_RATIO``: ``vertsize == textheight`` (3214/3214),
        ``baseline == round(0.85 * textheight)``, and for a ``PERCENT``
        paragraph ``vertsize + spacing == textheight * value / 100``.
        """
        pr = para.para_pr
        heights = []
        for offset, (ch, cid) in enumerate(para.chars[start:end]):
            if ch == OBJECT_SLOT:
                # An inline object occupies a character cell whose height is
                # the OBJECT's, not the run's point size.  Measured defect
                # (kstartup): a paragraph holding one full-page inline table
                # has a cached vertsize of ~63000 HWPUNIT and a charPr height
                # of 1000, so taking the run's size shrank the paragraph by a
                # whole page and pushed everything after it up the sheet.
                record = para.object_at.get(start + offset)
                if record is not None and not record[3]:
                    heights.append(self._object_extent(record[1])[1])
                    continue
            _ratio, _spacing, rel_sz, _offset = self._typography(cid, ch)
            pt = (self._charpr(cid).get("height_pt") or 10.0) * rel_sz / 100.0
            heights.append(pt * HWPUNIT_PER_PT)
        if not heights:
            cid = para.chars[0][1] if para.chars else None
            heights.append((self._charpr(cid).get("height_pt") or 10.0)
                           * HWPUNIT_PER_PT)
        if pr.get("font_line_height"):
            self._skip("hp:paraPr@fontLineHeight",
                       "line height from the font's own ascent/descent is not "
                       "implemented; the declared character size is used")
        textheight = int(round(max(heights)))
        vertsize = textheight
        baseline = int(round(textheight * BASELINE_RATIO))
        kind = pr.get("line_spacing_type", "PERCENT")
        value = pr.get("line_spacing_value", 100)
        if kind == "PERCENT":
            spacing = int(round(textheight * value / 100.0)) - vertsize
        elif kind == "FIXED":
            spacing = value - vertsize
        elif kind in ("BETWEEN_LINES", "ATLEAST", "AT_LEAST"):
            spacing = max(0, value)
        else:
            self._skip(f"hh:lineSpacing@type={kind}",
                       "unknown line spacing type; treated as 100% PERCENT")
            spacing = 0
        return textheight, vertsize, baseline, spacing

    def compute_lines(self, draw, para, column_hwp, from_char=0,
                      from_line=0):
        """Break ``para`` into line boxes from font metrics — this is E2.1.

        Returns paragraph-relative line records:
        ``{start, end, horzpos, horzsize, vertpos, vertsize, textheight,
        baseline, spacing, forced, width_px}``, where ``start``/``end`` index
        the paragraph's character stream exactly the way ``hp:lineseg@textpos``
        does, so a record is directly comparable to a cached one.

        Greedy first-fit, which is what HWP's own line breaker is (its cached
        boxes are reproducible by a greedy pass; a Knuth-Plass total-fit pass
        would disagree with them on purpose).  ``width_px`` excludes trailing
        whitespace, because a space that falls at a line end hangs outside the
        box rather than forcing a break.
        """
        pr = para.para_pr
        chars = para.chars
        count = len(chars)
        advances, gaps = self._char_advance_tables(draw, para)
        prefix_advance = [0.0]
        prefix_gap = [0.0]
        prefix_space = [0.0]
        for i in range(count):
            prefix_advance.append(prefix_advance[-1] + advances[i])
            prefix_gap.append(prefix_gap[-1] + gaps[i])
            prefix_space.append(
                prefix_space[-1]
                + (advances[i] if chars[i][0] in SPACE_CHARS else 0.0))

        def width(start, end):
            if end <= start:
                return 0.0
            return ((prefix_advance[end] - prefix_advance[start])
                    + (prefix_gap[end] - prefix_gap[start]) - gaps[end - 1])

        opportunities = break_opportunities(
            para.text, pr.get("break_latin", "KEEP_WORD"),
            pr.get("break_non_latin", "KEEP_WORD"))
        if pr.get("break_latin") == "HYPHENATION":
            self._skip("hh:breakSetting@breakLatinWord=HYPHENATION",
                       "hyphenation is not implemented; the paragraph breaks "
                       "at word boundaries instead")
        if pr.get("line_wrap", "BREAK") != "BREAK":
            self._skip(f"hh:breakSetting@lineWrap={pr.get('line_wrap')}",
                       "only lineWrap=BREAK is implemented; the paragraph is "
                       "broken as if it were BREAK")
        # hp:paraPr@condense — 공백 축소.  The spaces on a line may be squeezed
        # by up to this percentage to keep one more character on it, so a line
        # fits while its overflow is no larger than what its spaces can give
        # up.  Corpus values: 0 (603 paraPr), 25 (130), 20 (37), 30 (4).
        #
        # WHICH WAY ROUND THIS READS WAS DECIDED BY MEASUREMENT, not by
        # reading the attribute name.  Taken as "spaces may shrink TO
        # condense%" (so 0 would mean they may vanish entirely) the corpus
        # break-position recall is 16/216 = 0.074; taken as "spaces may shrink
        # BY condense%" (so 0 is the default, no condensing) it is 48/216 =
        # 0.222.  The second reading is the one the authoring engine's own
        # cached line breaks support, by a factor of three.
        condense = max(0, min(100, pr.get("condense", 0)))

        def slack(start, end):
            spaces = prefix_space[end] - prefix_space[start]
            return spaces * condense / 100.0

        spans = []
        start = from_char
        index = from_line
        cursor = from_char
        while cursor < count:
            ch = chars[cursor][0]
            if ch == "\n":
                spans.append((start, cursor + 1, False))
                start = cursor + 1
                index += 1
                cursor += 1
                continue
            # The tab test comes first: "\t" is whitespace, and whitespace is
            # otherwise skipped without a width decision.
            if ch != "\t" and ch in SPACE_CHARS:
                cursor += 1
                continue
            horzpos, horzsize = self._line_box(para, index, column_hwp)
            avail = self.pxf(horzsize)
            if ch == "\t":
                here = self.pxf(horzpos) + width(start, cursor)
                advances[cursor] = max(
                    0.0, self._tab_advance(para, here, column_hwp) - here)
                for i in range(cursor, count):
                    prefix_advance[i + 1] = prefix_advance[i] + advances[i]
                cursor += 1
                continue
            if (cursor > start
                    and width(start, cursor + 1)
                    > avail + slack(start, cursor + 1)):
                cut = None
                for position in opportunities:
                    if start < position <= cursor:
                        cut = position
                    elif position > cursor:
                        break
                forced = cut is None
                if forced:
                    cut = cursor
                    if not self._quiet:
                        self._forced_breaks += 1
                spans.append((start, cut, forced))
                start = cut
                index += 1
                continue
            cursor += 1
        spans.append((start, count, False))

        lines = []
        vertpos = 0
        for offset, (first, last, forced) in enumerate(spans):
            index = from_line + offset
            horzpos, horzsize = self._line_box(para, index, column_hwp)
            textheight, vertsize, baseline, spacing = self._line_metrics(
                para, first, last)
            visible = last
            while visible > first and chars[visible - 1][0] in SPACE_CHARS:
                visible -= 1
            lines.append({
                "start": first, "end": last,
                "horzpos": horzpos, "horzsize": horzsize,
                "vertpos": vertpos, "vertsize": vertsize,
                "textheight": textheight, "baseline": baseline,
                "spacing": spacing, "forced": forced,
                "width_px": width(first, visible),
            })
            vertpos += vertsize + spacing
        return lines

    # -- is the cached layout still describing this paragraph? -----------
    def _cached_lower_bound_hwp(self, para, start, end):
        """Font-independent lower bound on the width of ``chars[start:end]``.

        A full-width cell (Hangul, Hanja, kana, CJK punctuation, an inline
        object slot) advances by exactly the declared character size times
        ``hh:ratio`` in HWP's model, whatever face draws it; Latin is
        proportional and contributes nothing to the bound.  ``hh:spacing``
        gaps are exact and are counted with their sign.  The result therefore
        can never exceed the width the authoring engine actually laid out, so
        exceeding the cached box proves the text changed — no font on the
        machine can explain it away.
        """
        total = 0.0
        window = para.chars[start:end]
        for offset, (ch, cid) in enumerate(window):
            ratio, spacing, rel_sz, _offset = self._typography(cid, ch)
            size = ((self._charpr(cid).get("height_pt") or 10.0)
                    * rel_sz / 100.0 * HWPUNIT_PER_PT)
            if is_full_width(ch):
                total += size * ratio / 100.0
            # n-1 gaps: the gap after the last character of the span is not
            # drawn, exactly as `_measure` drops it.
            if spacing and offset < len(window) - 1:
                total += size * spacing / 100.0
        return total

    def line_layout_mode(self, para, column_hwp, paragraph_index=None):
        """``(mode, reason)`` — which engine lays this paragraph's lines out.

        ``computed`` wins for four named reasons, and only those:

          ``policy``            the whole render was asked for computed lines;
          ``cache_absent``      the paragraph carries no ``hp:linesegarray``;
          ``textpos_past_end``  a cached line starts past the end of the
                                paragraph's character stream, so the text is
                                shorter than the cache describes;
          ``stale_line_width``  a cached line's font-independent lower-bound
                                width exceeds its own cached ``horzsize``, so
                                the text is longer than that line could hold;
          ``caller_marked_edited`` the caller said it edited this paragraph.

        The last two matter because a stale box is the one thing this renderer
        must never draw.  ``stale_line_width`` is **sound but incomplete**: it
        never fires on an unedited paragraph (the bound is a lower bound on
        text the authoring engine did fit), and it does not fire on an edit
        that leaves every line still fitting.  An editor that knows it changed
        a paragraph must say so through ``relayout_paragraphs`` rather than
        rely on detection.
        """
        if self.line_layout == LINE_LAYOUT_COMPUTED:
            return LINE_LAYOUT_COMPUTED, "policy"
        if paragraph_index is not None and paragraph_index in self.relayout_paragraphs:
            return LINE_LAYOUT_COMPUTED, "caller_marked_edited"
        if not para.linesegs:
            return LINE_LAYOUT_COMPUTED, "cache_absent"
        count = len(para.chars)
        positions = [_iattr(seg, "textpos") for seg in para.linesegs]
        if positions and max(positions) > count:
            return LINE_LAYOUT_COMPUTED, "textpos_past_end"
        if count and len(positions) > 1 and max(positions) >= count:
            return LINE_LAYOUT_COMPUTED, "textpos_past_end"
        for i, seg in enumerate(para.linesegs):
            first = positions[i]
            last = positions[i + 1] if i + 1 < len(positions) else count
            horzsize = _iattr(seg, "horzsize") or column_hwp
            if horzsize <= 0:
                continue
            bound = self._cached_lower_bound_hwp(para, first, last)
            if bound > horzsize * (1.0 + STALE_LINE_TOLERANCE):
                return LINE_LAYOUT_COMPUTED, "stale_line_width"
        return "lineseg", None

    @staticmethod
    def _object_extent(el):
        sz = _kid(el, "sz")
        return (_iattr(sz, "width") if sz is not None else 0,
                _iattr(sz, "height") if sz is not None else 0)

    def _line_pieces(self, draw, items, split_for_justification):
        """Flatten a line's items into positioned-in-order drawable pieces.

        ``split_for_justification`` breaks otherwise-neutral text into single
        characters and inserts a zero-width elastic gap after each, so a
        justified or distributed line has somewhere to put its slack.  It is
        off for every other line, which keeps the common path on Pillow's
        whole-string measurement (and its kerning).
        """
        pieces = []
        for kind, payload in items:
            if kind == "obj":
                pieces.append({
                    "kind": "obj",
                    "advance": self.pxf(self._object_extent(payload[1])[0]),
                    "payload": payload,
                })
                continue
            seg = payload
            if not split_for_justification:
                pieces.extend(self._text_pieces(draw, seg.charpr, seg.text))
                continue
            for ch in seg.text:
                pieces.extend(self._text_pieces(draw, seg.charpr, ch))
                if pieces and pieces[-1]["kind"] != "gap":
                    pieces.append({"kind": "gap", "advance": 0.0})
        while pieces and pieces[-1]["kind"] == "gap":
            pieces.pop()
        return pieces

    @staticmethod
    def _elastic_slots(pieces):
        """Indices of the gaps justification may widen.

        Latin text is stretched at its spaces, as the format's word-breaking
        attributes imply; text with no space in the line (Hangul/CJK, the
        normal case here) is stretched at every inter-character gap.
        """
        space_slots = [
            i for i, p in enumerate(pieces)
            if p["kind"] == "gap" and i and pieces[i - 1]["kind"] == "glyph"
            and pieces[i - 1]["text"].endswith((" ", "　"))
        ]
        if space_slots:
            return space_slots
        return [i for i, p in enumerate(pieces) if p["kind"] == "gap"]

    def _draw_glyph_piece(self, draw, piece, x, baseline_px):
        """Draw one text piece, applying ``hh:ratio`` and ``hh:offset``.

        ``hh:ratio`` is a *horizontal glyph* scale, which Pillow cannot ask
        FreeType for directly, so a scaled piece is rasterised into its own
        8-bit mask at natural width, resampled horizontally, and composited in
        the run's colour.  ``LANCZOS`` is pinned for the same reason
        ``Layout.BASIC`` is: the resample filter has to be part of the
        renderer, not of the build.
        """
        y = baseline_px - piece["offset_px"]
        if piece["ratio"] == 100 or self._image is None:
            if piece["ratio"] != 100:
                self._skip("hh:ratio", "horizontal glyph scaling could not be "
                                       "composited; drawn unscaled")
            draw.text((x, y), piece["text"], font=piece["font"],
                      fill=piece["colour"], anchor="ls")
            return
        font = piece["font"]
        ascent, descent = font.getmetrics()
        natural = max(1, int(math.ceil(
            float(draw.textlength(piece["text"], font=font)) + 2)))
        height = max(1, ascent + descent)
        mask = self.Image.new("L", (natural, height), 0)
        self.ImageDraw.Draw(mask).text((0, ascent), piece["text"], font=font,
                                       fill=255, anchor="ls")
        scaled = max(1, int(round(natural * piece["ratio"] / 100.0)))
        if scaled != natural:
            mask = mask.resize((scaled, height),
                               self.Image.Resampling.LANCZOS)
        self._image.paste(piece["colour"], (int(round(x)),
                                            int(round(y - ascent))), mask)

    def _draw_line(self, draw, items, x_hwp, line_top_hwp, baseline_hwp,
                   align, avail_hwp, last_line=True):
        """Draw one line box: text pieces and inline objects, in order.

        The cached ``lineseg`` gives the box (``horzpos``/``horzsize``) but not
        the alignment offset inside it — ``horzpos`` stays 0 even for a centred
        line — so the offset is computed here from the measured content width,
        which now includes character typography.
        """
        if not items:
            return
        align = (align or "LEFT").upper()
        stretch = (align == "DISTRIBUTE"
                   or (align == "JUSTIFY" and not last_line))
        pieces = self._line_pieces(draw, items, stretch)
        if not pieces:
            return
        for piece in pieces:
            if piece["kind"] == "glyph":
                cp = self._charpr(piece["cid"])
                piece["colour"] = cp.get("color") or (0, 0, 0)
                piece["underline"] = (cp.get("underline") or "NONE").upper()
                piece["underline_colour"] = cp.get("underline_color")
        total = sum(p["advance"] for p in pieces)
        avail_px = self.pxf(avail_hwp)
        slots = self._elastic_slots(pieces) if stretch else []
        extra = self._justify_extra(align, avail_px, total, len(slots),
                                    last_line)
        if extra:
            self.applied[f"hh:align@{align}"] = (
                self.applied.get(f"hh:align@{align}", 0) + 1)
            for index in slots:
                pieces[index]["advance"] += extra
        x_px = self.pxf(x_hwp)
        cursor = x_px + self._align_offset(align, avail_px, total)
        baseline_px = self.pxf(baseline_hwp)
        drew_text = False
        text_x0 = text_x1 = None
        ascent = descent = 0
        for piece in pieces:
            w = piece["advance"]
            if piece["kind"] == "gap":
                cursor += w
                continue
            if piece["kind"] == "obj":
                name, el, _charpr, _floating = piece["payload"]
                origin = (self.hwp_from_px(cursor), line_top_hwp)
                if name == "tbl":
                    self._render_table(draw, el, origin)
                else:
                    self._render_placeholder(draw, el, name, origin)
                cursor += w
                continue
            font = piece["font"]
            self._draw_glyph_piece(draw, piece, cursor, baseline_px)
            drew_text = True
            seg_ascent, seg_descent = font.getmetrics()
            shift = piece["offset_px"]
            ascent = max(ascent, seg_ascent + shift)
            descent = max(descent, seg_descent - shift)
            text_x0 = cursor if text_x0 is None else min(text_x0, cursor)
            text_x1 = (cursor + w) if text_x1 is None else max(text_x1,
                                                              cursor + w)
            if piece["underline"] not in ("NONE", ""):
                # Ruled blanks in government forms are underline runs, and the
                # repo already treats them as load-bearing (form_inspect._is_ruled,
                # T112) — dropping them would erase the field the form provides.
                uy = baseline_px + max(1, self.pt_to_px(1.2))
                draw.line([(cursor, uy), (cursor + w, uy)],
                          fill=piece["underline_colour"] or piece["colour"],
                          width=max(1, self.dpi // 144))
            cursor += w
        if drew_text:
            self.counts["text_lines"] += 1
            # The box is the *text* extent, not the item extent: an inline
            # placeholder sharing the line must not inflate a box that is
            # about to be paired against a reference PDF's text lines.
            self.line_boxes.append({
                "page": self._page,
                "mode": self._line_mode,
                "x0": round(text_x0, 3),
                "y0": round(baseline_px - ascent, 3),
                "x1": round(text_x1, 3),
                "y1": round(baseline_px + descent, 3),
            })

    def _render_paragraphs(self, draw, paragraphs, origin_hwp, avail_w_hwp,
                           block_offset_hwp=0):
        """Lay out a paragraph list whose ``vertpos`` is relative to ``origin``.

        A paragraph this renderer relaid out is very likely a different height
        from the one the cache describes, so the paragraphs after it in the
        same container are shifted by the difference.  That is the whole of
        the incremental relayout this slice does: it keeps an edited paragraph
        from drawing on top of its neighbour.  It does NOT reflow across a
        page or grow a table row — both are named limits.
        """
        ox, oy = origin_hwp
        oy += block_offset_hwp
        shift = 0
        for para in paragraphs:
            self.counts["paragraphs"] += 1
            self.counts["runs"] += len(_kids(para.el, "run"))
            if para.tabs:
                self._skip("hp:tab", "hp:tab elements inside a run are not "
                                     "placed in the character stream, so the "
                                     "line they sit on is measured without "
                                     "them")
            self._render_floating(draw, para, (ox, oy + shift))
            if not para.chars:
                continue
            index = self.paragraph_index.get(id(para.el))
            mode, reason = self.line_layout_mode(para, avail_w_hwp, index)
            self._layout_counts[mode] += 1
            if mode == "lineseg":
                self._record_layout(index, para, mode, reason, None)
                self._render_cached_lines(draw, para, (ox, oy + shift),
                                          avail_w_hwp)
                continue
            self._layout_reasons[reason] = self._layout_reasons.get(reason, 0) + 1
            lines = self.compute_lines(draw, para, avail_w_hwp)
            self._record_layout(index, para, mode, reason, lines)
            self._render_computed_lines(draw, para, (ox, oy + shift), lines)
            shift += self._extent_delta(para, lines)

    @staticmethod
    def _cached_extent(para):
        """Paragraph-relative height of the cached line boxes, or ``None``."""
        if not para.linesegs:
            return None
        top = _iattr(para.linesegs[0], "vertpos")
        last = para.linesegs[-1]
        return _iattr(last, "vertpos") + _iattr(last, "vertsize") - top

    @staticmethod
    def _computed_extent(lines):
        if not lines:
            return 0
        return lines[-1]["vertpos"] + lines[-1]["vertsize"]

    def _extent_delta(self, para, lines):
        cached = self._cached_extent(para)
        if cached is None:
            return 0
        return self._computed_extent(lines) - cached

    def _record_layout(self, index, para, mode, reason, lines):
        record = {
            "paragraph": index,
            "page": self._page,
            "mode": mode,
            "characters": len(para.chars),
            "cached_lines": len(para.linesegs),
        }
        if mode == "lineseg":
            self.layout_records.append(record)
            return
        record["reason"] = reason
        record["computed_lines"] = len(lines or ())
        record["forced_breaks"] = sum(1 for l in (lines or ()) if l["forced"])
        record["height_delta_hwpunit"] = self._extent_delta(para, lines or [])
        self.layout_records.append(record)

    def _render_computed_lines(self, draw, para, origin_hwp, lines):
        """Draw the lines this renderer's own breaker produced.

        The paragraph's *origin* still comes from the cached layout where one
        exists: this slice re-derives line breaking inside a paragraph, not
        the block stacking that decides where a paragraph starts.  A paragraph
        with no cache at all starts at the container's flow position, exactly
        as before.
        """
        ox, oy = origin_hwp
        if para.linesegs:
            oy += _iattr(para.linesegs[0], "vertpos")
        self._line_mode = "computed"
        for index, line in enumerate(lines):
            chunk = para.chars[line["start"]:line["end"]]
            if not chunk:
                continue
            self._draw_line(
                draw,
                self._line_items(para, chunk, line["start"]),
                ox + line["horzpos"],
                oy + line["vertpos"],
                oy + line["vertpos"] + line["baseline"],
                para.align,
                line["horzsize"],
                last_line=(index == len(lines) - 1),
            )

    def _render_cached_lines(self, draw, para, origin_hwp, avail_w_hwp):
        ox, oy = origin_hwp
        positions = [_iattr(s, "textpos") for s in para.linesegs]
        self._line_mode = "lineseg"
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
                last_line=(i == len(para.linesegs) - 1),
            )

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
    def _paragraph_block_extent(self, draw, paras, avail_w_hwp):
        """How tall a cell's paragraphs are, in the layout each will get.

        A paragraph the cache still describes contributes its cached extent
        (unchanged from before this slice); one this renderer has to relay out
        contributes the extent of the lines it will actually draw, so an
        edited cell grows its row instead of overflowing it.  Measurement
        only: nothing is drawn and nothing is counted.
        """
        self._quiet += 1
        try:
            extent = 0
            for para in paras:
                cached = para.extent_hwp()
                index = self.paragraph_index.get(id(para.el))
                mode, _reason = self.line_layout_mode(para, avail_w_hwp, index)
                if mode == "computed" and para.chars:
                    lines = self.compute_lines(draw, para, avail_w_hwp)
                    top = (_iattr(para.linesegs[0], "vertpos")
                           if para.linesegs else 0)
                    cached = top + self._computed_extent(lines)
                extent = max(extent, cached)
            return extent
        finally:
            self._quiet -= 1

    def _table_tracks(self, draw, tbl):
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
                col_cons.append((col, cspan, width))
                cells.append({
                    "tc": tc, "row": row, "col": col,
                    "rspan": rspan, "cspan": cspan,
                    "declared_height": height,
                    "margin": {
                        "left": _iattr(cmargin, "left"),
                        "right": _iattr(cmargin, "right"),
                        "top": mt, "bottom": mb,
                    },
                    "paras": paras,
                })
        widths = solve_tracks(cols, col_cons, decl_w)
        # Columns first, then content extents, then rows: a cell's content
        # height depends on the width it gets, and its width does not depend
        # on any content.  A paragraph this renderer has to relay out is a
        # different height from the one the cache records, so the row it sits
        # in has to be measured from the relaid-out lines or the row will be
        # too short for what is about to be drawn in it.
        for cell in cells:
            c0 = min(cell["col"], len(widths))
            c1 = min(cell["col"] + cell["cspan"], len(widths))
            inner = max(0, sum(widths[c0:c1])
                        - cell["margin"]["left"] - cell["margin"]["right"])
            content_h = self._paragraph_block_extent(draw, cell["paras"], inner)
            # cellSz height is a *minimum*: HWP grows a row to fit its content
            # and leaves the stored value behind.  Taking the max of the two is
            # what tracks the declared table height.
            row_cons.append((
                cell["row"], cell["rspan"],
                max(cell["declared_height"],
                    content_h + cell["margin"]["top"] + cell["margin"]["bottom"])))
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
        xs, ys, cells = self._table_tracks(draw, tbl)
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
        # The block being centred has to be the block that will actually be
        # DRAWN, not the one the cache describes: a relaid-out paragraph is a
        # different height, and centring the cached height would move every
        # line in the cell by half the difference.  Same measurement the row
        # height was solved from.
        block = self._paragraph_block_extent(draw, cell["paras"], avail_w)
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

    def _font_report(self):
        """Per declared face: resolved against the system, or substituted.

        The honesty rule in its sharpest form.  Before this the sidecar said
        "every HWP face is rasterised with one family" — true, and useless for
        judging a page, because it could not say *which* of the document's
        faces the reader was actually looking at.  Now every declared face is
        listed with the installed file that answered for it, or with the
        substitute that stood in, and both are counted in characters.
        """
        faces = sorted(self.face_resolution.values(),
                       key=lambda f: (not f["resolved"],
                                      f["declared"] or "", f["slot"],
                                      f["bold"]))
        resolved = sum(f["characters"] for f in faces if f["resolved"])
        substituted = sum(f["characters"] for f in faces if not f["resolved"])
        total = resolved + substituted
        for face in faces:
            if not face["resolved"] and face["declared"]:
                self._skip(
                    f"hh:fontface[{face['declared']}]",
                    "declared face is not installed on this machine; "
                    "substituted, so advance widths differ from the "
                    "authoring engine's")
        return {
            "fallback_regular": self.fonts_meta["regular"],
            "fallback_bold": self.fonts_meta["bold"],
            "fallback_source": self.fonts_meta["source"],
            "pinned_single_face": self.pinned_face,
            "system_font_files_scanned": (
                self.font_index.scanned if self.font_index else 0),
            "characters_on_a_resolved_face": resolved,
            "characters_on_a_substituted_face": substituted,
            "resolved_character_share": (
                round(resolved / total, 6) if total else None),
            "faces": faces,
            "note": (
                "declared faces are matched against the installed faces' own "
                "family names, read from each font's OpenType name table "
                "(including its Korean records, which FreeType does not "
                "expose). A face that is not installed is substituted with "
                "the fallback and named here and in elements_skipped; its "
                "advance widths then differ from the authoring engine's. "
                "This makes a render machine-dependent BY DESIGN: the same "
                "document on a machine without these faces will not produce "
                "the same pixels. Set RIGORLOOM_OWN_RENDER_FONT to pin one "
                "face and take that variable out of the measurement."
            ),
        }

    # hp:paraPr / hh:breakSetting attributes this tier reads and acts on, and
    # the ones it parses but cannot act on.  Kept next to the report that
    # emits them so a new attribute cannot be honoured without being declared.
    PARAPR_HONORED = (
        "hh:breakSetting@breakLatinWord (KEEP_WORD / BREAK_WORD)",
        "hh:breakSetting@breakNonLatinWord (KEEP_WORD / BREAK_WORD)",
        "hh:breakSetting@lineWrap=BREAK",
        "hp:paraPr@condense (최소 공백: a line may overrun by the width its "
        "spaces can give up)",
        "hh:lineSpacing@type=PERCENT and @type=FIXED, with @value",
        "hh:margin/hh:left, hh:right, hh:intent (들여쓰기 positive, 내어쓰기 "
        "negative)",
        "hh:align@horizontal (LEFT / CENTER / RIGHT / JUSTIFY / DISTRIBUTE)",
        "hp:paraPr@tabPrIDRef, for the explicit LEFT stops hh:tabPr declares",
    )
    PARAPR_NOT_HONORED = (
        "hh:breakSetting@breakLatinWord=HYPHENATION — hyphenation is not "
        "implemented; broken at word boundaries instead",
        "hh:breakSetting@widowOrphan / @keepWithNext / @keepLines / "
        "@pageBreakBefore — block-level pagination rules; this tier does not "
        "do block layout",
        "hp:paraPr@fontLineHeight=1 — line height from the resolved font's "
        "own ascent/descent; the declared character size is used instead",
        "hp:paraPr@snapToGrid — the section grid is not implemented",
        "hh:lineSpacing@type=BETWEEN_LINES — implemented as pure leading, "
        "never exercised by the corpus",
        "hh:tab@type=RIGHT / CENTER / DECIMAL — advanced as a LEFT stop",
        "hp:tab elements inside a run are not placed in the character stream",
    )

    def _line_layout_report(self):
        """Which engine laid out each paragraph's lines, and on what evidence.

        The per-paragraph list is the point: a reader has to be able to tell,
        without re-running anything, which paragraphs on a page carry the
        authoring engine's own line breaks and which carry this renderer's.
        """
        computed = [r for r in self.layout_records if r["mode"] == "computed"]
        return {
            "policy": self.line_layout,
            "policy_meaning": (
                "auto: a paragraph keeps the document's cached hp:lineseg "
                "boxes unless they provably no longer describe its text, in "
                "which case this renderer's own breaker lays it out. "
                "computed: every paragraph is laid out by this renderer's "
                "breaker, which is how the breaker itself is measured — not "
                "how a document is rendered most faithfully."
            ),
            "paragraphs": dict(self._layout_counts),
            "computed_reasons": dict(sorted(self._layout_reasons.items())),
            "forced_breaks": self._forced_breaks,
            "forced_breaks_meaning": (
                "lines this renderer had to cut at a position the paragraph's "
                "own breakSetting forbids, because no permitted break "
                "opportunity existed inside the box"
            ),
            "caller_marked_edited": sorted(self.relayout_paragraphs),
            "stale_detection": (
                "a cached line box is judged stale when a cached textpos "
                "starts past the end of the character stream, or when a "
                "cached line's FONT-INDEPENDENT lower-bound width (full-width "
                "cells at their declared size x hh:ratio, plus the declared "
                "hh:spacing gaps) exceeds that line's own cached horzsize by "
                f"more than {STALE_LINE_TOLERANCE:.0%}. The bound can never "
                "exceed the width the authoring engine actually fitted, so "
                "the detector raises no false positive on an unedited "
                "paragraph — but it is INCOMPLETE: an edit that leaves every "
                "line still fitting is invisible in the file, and an editor "
                "that knows it changed a paragraph must declare it through "
                "relayout_paragraphs instead of relying on detection."
            ),
            "paragraph_origin": (
                "a relaid-out paragraph still starts where the cached layout "
                "put it; this slice re-derives line breaking inside a "
                "paragraph, not the block stacking that decides where a "
                "paragraph begins. Paragraphs after a relaid-out one in the "
                "same container are shifted by its height change so they "
                "cannot be drawn over, but a table row does not grow and no "
                "content reflows onto another page."
            ),
            "line_geometry_model": {
                "vertsize": "== textheight (3214/3214 corpus line boxes)",
                "baseline": (f"== round({BASELINE_RATIO} * textheight) "
                             "(3212/3214 exact, all 3214 within 1 HWPUNIT); "
                             "the ratio is a measured constant of this "
                             "corpus, not a number KS X 6101 publishes"),
                "vertpos": ("== previous vertpos + previous vertsize + "
                            "previous spacing (219/219 corpus continuation "
                            "lines)"),
                "spacing": ("PERCENT: vertsize + spacing == round(textheight "
                            "* value / 100); FIXED: vertsize + spacing == "
                            "value"),
                "textheight": ("max declared hh:charPr@height x hh:relSz over "
                               "the characters on the line"),
            },
            "prohibition_table": {
                "line_start_forbidden": "".join(sorted(LINE_START_PROHIBITED)),
                "line_end_forbidden": "".join(sorted(LINE_END_PROHIBITED)),
                "note": (
                    "금칙처리. KS X 6101 does not publish the prohibited-"
                    "character sets any more than it publishes the language-"
                    "slot partition; this is the conventional Korean/CJK "
                    "table and is this renderer's, declared, not the spec's."
                ),
            },
            "parapr_honored": list(self.PARAPR_HONORED),
            "parapr_not_honored": list(self.PARAPR_NOT_HONORED),
            "paragraphs_relaid_out": computed,
        }

    def render(self):
        geo = self.page_geometry()
        pages = self.paginate()
        page_w = self.px(geo["width"])
        page_h = self.px(geo["height"])
        images = []
        for page_number, page_paras in enumerate(pages, start=1):
            self._page = page_number
            img = self.Image.new("RGB", (page_w, page_h), (255, 255, 255))
            self._image = img
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
            "fonts": self._font_report(),
            "elements_rendered": dict(self.counts),
            "typography": {
                "applied_characters": dict(sorted(self.applied.items())),
                "meaning": (
                    "how many characters (and, for hh:align, how many lines) "
                    "this render actually applied each metric to. A metric "
                    "absent here is one the document never declares away from "
                    "its neutral value, not one this renderer ignores."
                ),
            },
            "typography_slot_model": {
                "slots": list(LANG_SLOTS),
                "assignment": (
                    "OWPML declares hh:ratio/spacing/relSz/offset once per "
                    "language slot. The standard names the slots but does not "
                    "publish the codepoint partition, so the mapping used here "
                    "is this renderer's plain Unicode-block reading of the "
                    "slot names — an approximation, declared, not the spec."
                ),
                "user_slot": (
                    "never selected: HWP fills the user slot from a "
                    "user-defined character range table the document does not "
                    "carry, so a renderer reading only the file cannot honour "
                    "it"
                ),
            },
            "line_layout": self._line_layout_report(),
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

def lineseg_agreement(hwpx_path, dpi=DEFAULT_DPI, repo_root=None):
    """Measure this renderer's line breaker against the authoring engine's.

    For every paragraph of the document that carries a usable
    ``<hp:linesegarray>``, the breaker is run on the paragraph's **unedited**
    text and its line starts are compared to the cached ``@textpos`` values.
    This is the primary metric of E2.1: it is the only channel on which a
    from-scratch line breaker can be graded without a reference render, and it
    grades exactly the thing this slice built.

    Two deliberate choices, both of which make the number *about the breaker*:

      * the line box is taken from the paragraph's own cached first line
        (``horzpos + horzsize``, plus the declared right margin), not from
        this renderer's page/table geometry.  A disagreement is then the
        breaker's, never the track solver's.
      * a paragraph whose cache is unusable (absent, or a ``textpos`` past the
        end of the character stream) is *excluded and counted*, not scored as
        a failure — there is nothing to compare against.

    Two agreement numbers are reported, and they answer different questions.
    The *sequence* numbers run the breaker over the whole paragraph, so one
    wrong break throws every later one off.  ``conditional_breaks`` restarts
    the breaker at each line start the authoring engine chose and asks only
    where it would put the *next* break — the per-decision accuracy, with the
    error propagation removed.  Each disagreement is classified as ``early``
    (the authoring engine's own line already overflows the box this renderer
    measures) or ``late`` (the next word still fits it), which is what says
    whether the breaking rules or the advance widths are wrong.

    Reported separately for all paragraphs and for the multi-line subset,
    because a corpus of government forms is overwhelmingly single-line
    paragraphs (2995 paragraphs, 161 of them multi-line) and an "agreement"
    number dominated by paragraphs that cannot break is not a measurement.
    """
    renderer = OwnRenderer(hwpx_path, dpi=dpi, repo_root=repo_root)
    canvas = renderer.Image.new("RGB", (8, 8), (255, 255, 255))
    renderer._image = canvas
    draw = renderer.ImageDraw.Draw(canvas)
    renderer._quiet += 1

    totals = {
        "paragraphs_scored": 0,
        "paragraphs_excluded": 0,
        "paragraphs_line_count_exact": 0,
        "paragraphs_break_sequence_exact": 0,
        "cached_lines": 0,
        "computed_lines": 0,
        "break_positions_cached": 0,
        "break_positions_computed": 0,
        "break_positions_matched": 0,
        "first_line_box_exact": 0,
    }
    multi = dict(totals)
    disagreements = []
    conditional = {"decisions": 0, "exact": 0, "early": 0, "late": 0}
    fills = []

    for element in renderer.sections[0].iter():
        if _local(element.tag) != "p":
            continue
        para = Paragraph(element, renderer.defs["para_pr"])
        if not para.chars:
            continue
        index = renderer.paragraph_index.get(id(element))
        if not para.linesegs:
            totals["paragraphs_excluded"] += 1
            continue
        cached = [_iattr(seg, "textpos") for seg in para.linesegs]
        if max(cached) > len(para.chars) or (
                len(cached) > 1 and max(cached) >= len(para.chars)):
            totals["paragraphs_excluded"] += 1
            continue
        first = para.linesegs[0]
        column = (_iattr(first, "horzpos") + _iattr(first, "horzsize")
                  + max(0, para.para_pr.get("margin_right", 0)))
        if column <= 0:
            totals["paragraphs_excluded"] += 1
            continue
        lines = renderer.compute_lines(draw, para, column)
        computed = [line["start"] for line in lines]
        cached_breaks = set(cached[1:])
        computed_breaks = set(computed[1:])
        matched = cached_breaks & computed_breaks
        buckets = [totals] + ([multi] if len(cached) > 1 else [])
        for bucket in buckets:
            bucket["paragraphs_scored"] += 1
            bucket["cached_lines"] += len(cached)
            bucket["computed_lines"] += len(computed)
            bucket["break_positions_cached"] += len(cached_breaks)
            bucket["break_positions_computed"] += len(computed_breaks)
            bucket["break_positions_matched"] += len(matched)
            if len(cached) == len(computed):
                bucket["paragraphs_line_count_exact"] += 1
            if cached == computed:
                bucket["paragraphs_break_sequence_exact"] += 1
            if (lines[0]["horzpos"] == _iattr(first, "horzpos")
                    and lines[0]["horzsize"] == _iattr(first, "horzsize")):
                bucket["first_line_box_exact"] += 1
        # Per-decision accuracy: restart the breaker where the authoring
        # engine started each line, and ask only where it puts the next break.
        for i in range(len(cached) - 1):
            here, target = cached[i], cached[i + 1]
            one = renderer.compute_lines(draw, para, column, from_char=here,
                                         from_line=i)
            if not one:
                continue
            conditional["decisions"] += 1
            if one[0]["end"] == target:
                conditional["exact"] += 1
            elif one[0]["end"] < target:
                conditional["early"] += 1
            else:
                conditional["late"] += 1
            box_px = renderer.pxf(_iattr(para.linesegs[i], "horzsize")
                                  or column)
            visible = target
            while (visible > here
                   and para.chars[visible - 1][0] in SPACE_CHARS):
                visible -= 1
            if box_px > 0 and visible > here:
                # How full the authoring engine's own line is, measured by
                # this renderer.  A value under 1.0 says this renderer thinks
                # there was still room where the authoring engine broke.
                fills.append(renderer.span_width(draw, para, here, visible)
                             / box_px)
        if cached != computed and len(disagreements) < 40:
            disagreements.append({
                "paragraph": index,
                "cached": cached,
                "computed": computed,
                "characters": len(para.chars),
                "break_latin": para.para_pr.get("break_latin"),
                "break_non_latin": para.para_pr.get("break_non_latin"),
                "text": para.text[:120],
            })
    renderer._quiet -= 1

    def _rate(bucket, hit, total):
        return (round(bucket[hit] / bucket[total], 6)
                if bucket[total] else None)

    for bucket in (totals, multi):
        bucket["line_count_agreement"] = _rate(
            bucket, "paragraphs_line_count_exact", "paragraphs_scored")
        bucket["break_sequence_agreement"] = _rate(
            bucket, "paragraphs_break_sequence_exact", "paragraphs_scored")
        bucket["break_position_recall"] = _rate(
            bucket, "break_positions_matched", "break_positions_cached")
        bucket["first_line_box_agreement"] = _rate(
            bucket, "first_line_box_exact", "paragraphs_scored")
    multi.pop("paragraphs_excluded", None)
    conditional["accuracy"] = (
        round(conditional["exact"] / conditional["decisions"], 6)
        if conditional["decisions"] else None)
    conditional["meaning"] = (
        "the breaker restarted at each line start the authoring engine chose, "
        "asked only where it would put the NEXT break, and compared. 'early' "
        "means this renderer would break sooner (it measures the authoring "
        "engine's own line as already overflowing the box); 'late' means it "
        "would break further on (the next word still fits by its reckoning)."
    )
    ordered = sorted(fills)
    conditional["cached_line_fill"] = {
        "n": len(ordered),
        "median": round(ordered[len(ordered) // 2], 6) if ordered else None,
        "p10": (round(ordered[int(len(ordered) * 0.1)], 6)
                if ordered else None),
        "p90": (round(ordered[int(len(ordered) * 0.9)], 6)
                if ordered else None),
        "meaning": (
            "how full the authoring engine's own line is when this renderer "
            "measures it, as a fraction of that line's own cached horzsize. "
            "1.0 would mean the two agree exactly about advance widths; below "
            "1.0 says this renderer measures the same text narrower than the "
            "authoring engine did, and will therefore fit more of the next "
            "word onto the line."
        ),
    }

    return {
        "document": Path(hwpx_path).name,
        "dpi": dpi,
        "renderer": RENDERER_STAMP,
        "fonts": renderer._font_report(),
        "all_paragraphs": totals,
        "multiline_paragraphs": multi,
        "conditional_breaks": conditional,
        "disagreements": disagreements,
        "method": (
            "the breaker is run on each paragraph's unedited character stream "
            "inside the line box the authoring engine itself used (the "
            "paragraph's cached first hp:lineseg horzpos+horzsize, plus the "
            "declared right margin), and its line starts are compared to the "
            "cached hp:lineseg@textpos values. break_position_recall is the "
            "share of the authoring engine's own break positions this breaker "
            "also chose; break_sequence_agreement is the share of paragraphs "
            "where every line start matches exactly."
        ),
        "caveat": (
            "this number depends on which faces this machine has installed: "
            "an unresolved face is measured with a substitute whose advance "
            "widths differ from the authoring engine's, and a line then "
            "breaks in a different place for a reason that has nothing to do "
            "with the breaking rules. See fonts."
        ),
    }


def save_png(image, path):
    """Write a PNG with no timestamp chunk and a pinned compression level."""
    image.save(path, format="PNG", optimize=False, compress_level=6)


def render_to_dir(hwpx_path, out_dir, dpi=DEFAULT_DPI, stem=None,
                  line_layout=LINE_LAYOUT_AUTO, relayout_paragraphs=None):
    renderer = OwnRenderer(hwpx_path, dpi=dpi, line_layout=line_layout,
                           relayout_paragraphs=relayout_paragraphs)
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


def render_to_pdf(hwpx_path, out_pdf, dpi=DEFAULT_DPI,
                  line_layout=LINE_LAYOUT_AUTO):
    """Raster PDF, for the ``[binary, {in}, {out}]`` argv render_cert expects.

    The pages carry no text layer, so ``render_cert``'s unique-word anchor
    channel cannot score this output — only page count and the raster channel
    can.  A vector text backend is the prerequisite for full certification;
    see engine/references/own-render-notes.md.
    """
    renderer = OwnRenderer(hwpx_path, dpi=dpi, line_layout=line_layout)
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
    parser.add_argument(
        "--lineseg-agreement", action="store_true",
        help="do not render: measure this renderer's line breaker "
             "against the document's own cached hp:lineseg layout and "
             "print the report as JSON")
    parser.add_argument("--stem", help="override the output filename stem")
    parser.add_argument(
        "--line-layout", choices=list(LINE_LAYOUT_MODES),
        default=LINE_LAYOUT_AUTO,
        help="auto (default): keep the document's cached hp:lineseg line "
             "boxes unless they are provably stale. computed: lay every "
             "paragraph out with this renderer's own line breaker, which "
             "is how the breaker itself is measured.")
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
    if args.lineseg_agreement:
        try:
            report = lineseg_agreement(args.input, dpi=args.dpi)
        except RendererUnavailable as exc:
            print(f"own_render: unavailable - {exc}", file=sys.stderr)
            return 3
        except (ValueError, OSError, zipfile.BadZipFile,
                ET.ParseError) as exc:
            print(f"own_render: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2,
                         sort_keys=True))
        return 0
    try:
        if args.output:
            result = render_to_pdf(args.input, args.output, dpi=args.dpi,
                                   line_layout=args.line_layout)
        else:
            out_dir = args.out_dir or Path(args.input).with_suffix("").name + "-render"
            result = render_to_dir(args.input, out_dir, dpi=args.dpi,
                                   stem=args.stem,
                                   line_layout=args.line_layout)
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
