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
    def __init__(self, hwpx_path, dpi=DEFAULT_DPI, repo_root=None):
        self.path = Path(hwpx_path)
        self.dpi = int(dpi)
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")
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
        # Standing caveats that apply to every render, not just this document.
        # They belong in the artefact, not only in the notes file, because the
        # sidecar is what travels with the PNG.
        self.notes = [
            "line boxes come from the document's own cached hp:lineseg layout; "
            "line breaking matches the authoring engine, intra-line text "
            "extents do not (see fonts)",
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
                last_line=(i == len(para.linesegs) - 1),
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
        wrapped = self._greedy_wrap(draw, para.chars, avail_px)
        for index, line in enumerate(wrapped):
            self._draw_line(draw, self._line_items(para, line, consumed),
                            ox, y, y + baseline, para.align, avail_w_hwp,
                            last_line=(index == len(wrapped) - 1))
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
