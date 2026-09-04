#!/usr/bin/env python3
"""Author ``render-check-01.hwpx`` — one labelled block per catalog feature.

The render-check document is Rigorloom-authored and synthetic: every string in
it is a feature label or lorem-style Korean filler, so it carries no personal
data and can be committed to the corpus.  It exists so a human (and
``engine/scripts/render_check.py``) can put Hancom's rendering and
``own_render``'s rendering side by side, one feature at a time.

Each feature block opens with a label paragraph whose text begins with a
``[Fnn]`` marker.  The marker is what makes per-block scoring possible: the
block's own paragraph ordinal is recorded in the emitted
``render-check-01.blocks.json`` sidecar, and ``render_check.py`` turns that
ordinal into a page + vertical band by looking the ordinal up in
``own_render``'s ``block_layout.blocks`` coordinates.  No region is
hand-placed.

Build:

    python tests/corpus/render-check/build_render_check.py \
        --out tests/corpus/render-check/render-check-01.hwpx

The writer is ``engine/scripts/hwpx_write.py`` (``blank_package`` + the Hancom
package writer); this module only supplies ``Contents/header.xml``,
``Contents/section*.xml``, ``Contents/content.hpf`` and the one ``BinData``
image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
sys.path.insert(0, str(_REPO / "engine" / "scripts"))

import hwpx_write as W  # noqa: E402  (path shim above is deliberate)

# ---------------------------------------------------------------------------
# Page geometry (HWPUNIT; 7200 per inch)
# ---------------------------------------------------------------------------
A4_W, A4_H = 59528, 84188
MARGIN = dict(left=8504, right=8504, top=5668, bottom=4252, header=4252,
              footer=4252, gutter=0)
BODY_W = A4_W - MARGIN["left"] - MARGIN["right"]          # 42520

# Landscape section 1 uses a different paper orientation *and* different
# margins, so the two knobs are separable in the report.
LAND_MARGIN = dict(left=4252, right=4252, top=3402, bottom=3402, header=2834,
                   footer=2834, gutter=0)
LAND_BODY_W = A4_H - LAND_MARGIN["left"] - LAND_MARGIN["right"]

NS = W._NS_ATTRS


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Reference tables (header.xml)
# ---------------------------------------------------------------------------
FONTS = ["바탕", "돋움", "궁서"]          # ids 0,1,2 — declared by name
FONT_LANGS = ["HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"]

_TYPEINFO = ('<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="0"'
             ' contrast="0" strokeVariation="1" armStyle="1" letterform="1"'
             ' midline="1" xHeight="1"/>')


def fontfaces() -> str:
    groups = []
    for lang in FONT_LANGS:
        fonts = "".join(
            '<hh:font id="%d" face="%s" type="TTF" isEmbedded="0">%s</hh:font>'
            % (i, face, _TYPEINFO) for i, face in enumerate(FONTS))
        groups.append('<hh:fontface lang="%s" fontCnt="%d">%s</hh:fontface>'
                      % (lang, len(FONTS), fonts))
    return ('<hh:fontfaces itemCnt="%d">%s</hh:fontfaces>'
            % (len(FONT_LANGS), "".join(groups)))


def _border(side: str, kind: str, width: str) -> str:
    return ('<hh:%sBorder type="%s" width="%s" color="#000000"/>'
            % (side, kind, width))


def border_fill(idx: int, kind: str = "NONE", width: str = "0.1 mm",
                face: str | None = None) -> str:
    """One ``hh:borderFill``.  ``face`` non-None adds a solid cell shading."""
    body = ('<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
            '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            + "".join(_border(s, kind, width)
                      for s in ("left", "right", "top", "bottom"))
            + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>')
    if face is not None:
        body += ('<hc:fillBrush><hc:winBrush faceColor="%s"'
                 ' hatchColor="#000000" alpha="0"/></hc:fillBrush>' % face)
    return ('<hh:borderFill id="%d" threeD="0" shadow="0" centerLine="NONE"'
            ' breakCellSeparateLine="0">%s</hh:borderFill>' % (idx, body))


#: borderFill ids used by the table blocks.  1 is the mandatory "no border"
#: default every charPr/paraPr points at.
BF_NONE, BF_SOLID, BF_SHADE, BF_DASH, BF_DOT, BF_DOUBLE, BF_THICK = range(1, 8)

BORDER_FILLS = [
    border_fill(BF_NONE),
    border_fill(BF_SOLID, "SOLID", "0.12 mm"),
    border_fill(BF_SHADE, "SOLID", "0.12 mm", face="#D9D9D9"),
    border_fill(BF_DASH, "DASH", "0.12 mm"),
    border_fill(BF_DOT, "DOT", "0.12 mm"),
    border_fill(BF_DOUBLE, "DOUBLE_SLIM", "0.4 mm"),
    border_fill(BF_THICK, "SOLID", "0.5 mm"),
]


def _slot(tag: str, value) -> str:
    return ('<hh:%s hangul="%s" latin="%s" hanja="%s" japanese="%s"'
            ' other="%s" symbol="%s" user="%s"/>'
            % (tag, value, value, value, value, value, value, value))


def char_pr(idx: int, *, height=1000, font=0, bold=False, italic=False,
            underline="NONE", strike="NONE", ratio=100, spacing=0,
            rel_sz=100, offset=0, color="#000000", shade="none") -> str:
    body = [_slot("fontRef", font), _slot("ratio", ratio),
            _slot("spacing", spacing), _slot("relSz", rel_sz),
            _slot("offset", offset)]
    if bold:
        body.append("<hh:bold/>")
    if italic:
        body.append("<hh:italic/>")
    body.append('<hh:underline type="%s" shape="SOLID" color="#000000"/>'
                % underline)
    body.append('<hh:strikeout shape="%s" color="#000000"/>' % strike)
    body.append('<hh:outline type="NONE"/>')
    body.append('<hh:shadow type="NONE" color="#B2B2B2" offsetX="10"'
                ' offsetY="10"/>')
    return ('<hh:charPr id="%d" height="%d" textColor="%s" shadeColor="%s"'
            ' useFontSpace="0" useKerning="0" symMark="NONE"'
            ' borderFillIDRef="%d">%s</hh:charPr>'
            % (idx, height, color, shade, BF_NONE, "".join(body)))


# charPr ids, named so the section builder reads as prose.
CP = {}


def _cp(name: str, **kw) -> int:
    idx = len(CP)
    CP[name] = (idx, kw)
    return idx


_cp("base")
_cp("label", height=1100, font=1, bold=True, color="#1F3864")
_cp("bold", bold=True)
_cp("italic", italic=True)
_cp("underline", underline="SOLID")
_cp("strike", strike="SOLID")
_cp("super", rel_sz=65, offset=35)
_cp("sub", rel_sz=65, offset=-35)
_cp("spacing_tight", spacing=-15)
_cp("spacing_wide", spacing=30)
_cp("ratio_narrow", ratio=50)
_cp("ratio_wide", ratio=150)
_cp("relsz_small", rel_sz=60)
_cp("relsz_large", rel_sz=140)
_cp("offset_up", offset=40)
_cp("offset_down", offset=-40)
_cp("batang", font=0)
_cp("dotum", font=1)
_cp("gungsu", font=2)
_cp("pt8", height=800)
_cp("pt10", height=1000)
_cp("pt12", height=1200)
_cp("pt14", height=1400)
_cp("pt18", height=1800)
_cp("pt24", height=2400)
_cp("cell", height=900)
_cp("caption", height=900, font=1, color="#404040")
_cp("link", underline="SOLID", color="#0563C1")
_cp("note", height=800)
_cp("furniture", height=900, font=1, color="#595959")

CHAR_PRS = [char_pr(idx, **kw) for _, (idx, kw) in
            sorted(CP.items(), key=lambda kv: kv[1][0])]


def para_pr(idx: int, *, align="JUSTIFY", line_type="PERCENT", line_value=160,
            intent=0, left=0, right=0, prev=0, nxt=0, heading=None,
            page_break=False) -> str:
    if heading is None:
        head = '<hh:heading type="NONE" idRef="0" level="0"/>'
    else:
        kind, id_ref, level = heading
        head = ('<hh:heading type="%s" idRef="%d" level="%d"/>'
                % (kind, id_ref, level))
    return (
        '<hh:paraPr id="%d" tabPrIDRef="0" condense="0" fontLineHeight="0"'
        ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
        '<hh:align horizontal="%s" vertical="BASELINE"/>'
        '%s'
        '<hh:breakSetting breakLatinWord="KEEP_WORD"'
        ' breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0"'
        ' keepLines="0" pageBreakBefore="%d" lineWrap="BREAK"/>'
        '<hh:margin>'
        '<hc:intent value="%d" unit="HWPUNIT"/>'
        '<hc:left value="%d" unit="HWPUNIT"/>'
        '<hc:right value="%d" unit="HWPUNIT"/>'
        '<hc:prev value="%d" unit="HWPUNIT"/>'
        '<hc:next value="%d" unit="HWPUNIT"/>'
        '</hh:margin>'
        '<hh:lineSpacing type="%s" value="%d" unit="HWPUNIT"/>'
        '<hh:border borderFillIDRef="%d" offsetLeft="0" offsetRight="0"'
        ' offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>'
        '</hh:paraPr>'
        % (idx, align, head, 1 if page_break else 0, intent, left, right,
           prev, nxt, line_type, line_value, BF_NONE))


PP = {}


def _pp(name: str, **kw) -> int:
    idx = len(PP)
    PP[name] = (idx, kw)
    return idx


_pp("base", align="LEFT")
_pp("label", align="LEFT", prev=600, nxt=200)
_pp("align_left", align="LEFT")
_pp("align_center", align="CENTER")
_pp("align_right", align="RIGHT")
_pp("align_justify", align="JUSTIFY")
_pp("align_distribute", align="DISTRIBUTE")
_pp("ls_130", align="JUSTIFY", line_value=130)
_pp("ls_160", align="JUSTIFY", line_value=160)
_pp("ls_200", align="JUSTIFY", line_value=200)
_pp("ls_fixed", align="JUSTIFY", line_type="FIXED", line_value=2400)
_pp("indent_first", align="JUSTIFY", intent=2000)
_pp("indent_hanging", align="JUSTIFY", intent=-2000, left=2000)
_pp("indent_lr", align="JUSTIFY", left=4000, right=4000)
_pp("cell", align="CENTER")
_pp("cell_left", align="LEFT")
_pp("caption", align="CENTER", prev=100, nxt=300)
_pp("outline1", align="LEFT", heading=("OUTLINE", 1, 0))
_pp("outline2", align="LEFT", heading=("OUTLINE", 1, 1), left=2000)
_pp("outline3", align="LEFT", heading=("OUTLINE", 1, 2), left=4000)
_pp("bullet", align="LEFT", heading=("BULLET", 2, 0), left=2000, intent=-1000)
_pp("page_break", align="LEFT", page_break=True)
_pp("furniture", align="CENTER")
_pp("note", align="LEFT", line_value=130)

PARA_PRS = [para_pr(idx, **kw) for _, (idx, kw) in
            sorted(PP.items(), key=lambda kv: kv[1][0])]


def _para_head(level: int, fmt: str, text: str, left: int) -> str:
    return ('<hh:paraHead start="1" level="%d" align="LEFT" useInstWidth="1"'
            ' autoIndent="1" widthAdjust="0" textOffsetType="HWPUNIT"'
            ' textOffset="%d" numFormat="%s" charPrIDRef="4294967295"'
            ' checkable="0">%s</hh:paraHead>' % (level, left, fmt, text))


#: id 1 = the 3-level 개요 번호 (1. / 1.1 / 1.1.1); levels 4-10 exist because
#: Hancom writes a full 10-level ladder even when only three are used.
NUMBERINGS = (
    '<hh:numberings itemCnt="1">'
    '<hh:numbering id="1" start="1">'
    + _para_head(1, "DIGIT", "^1.", 1000)
    + _para_head(2, "DIGIT", "^1.^2", 1400)
    + _para_head(3, "DIGIT", "^1.^2.^3", 1800)
    + "".join(_para_head(n, "DIGIT", "^%d)" % n, 1000) for n in range(4, 11))
    + '</hh:numbering>'
    '</hh:numberings>'
)

BULLETS = (
    '<hh:bullets itemCnt="1">'
    '<hh:bullet id="2" char="&#x2022;" checkable="0" useImage="0">'
    '<hh:paraHead start="1" level="1" align="LEFT" useInstWidth="1"'
    ' autoIndent="1" widthAdjust="0" textOffsetType="HWPUNIT"'
    ' textOffset="1000" numFormat="DIGIT" charPrIDRef="4294967295"'
    ' checkable="0"/>'
    '<hh:img binaryItemIDRef="" bright="0" contrast="0" effect="REAL_PIC"'
    ' alpha="0"/>'
    '</hh:bullet>'
    '</hh:bullets>'
)

STYLES = (
    '<hh:styles itemCnt="1">'
    '<hh:style id="0" type="PARA" name="바탕글" engName="Normal"'
    ' paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042"'
    ' lockForm="0"/>'
    '</hh:styles>'
)


def header_xml(sec_cnt: int) -> bytes:
    body = (
        '<hh:head' + NS + ' version="1.5" secCnt="%d">' % sec_cnt
        + '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1"'
          ' equation="1"/>'
        + '<hh:refList>'
        + fontfaces()
        + '<hh:borderFills itemCnt="%d">%s</hh:borderFills>'
          % (len(BORDER_FILLS), "".join(BORDER_FILLS))
        + '<hh:charProperties itemCnt="%d">%s</hh:charProperties>'
          % (len(CHAR_PRS), "".join(CHAR_PRS))
        + '<hh:tabProperties itemCnt="1">'
          '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
          '</hh:tabProperties>'
        + NUMBERINGS + BULLETS
        + '<hh:paraProperties itemCnt="%d">%s</hh:paraProperties>'
          % (len(PARA_PRS), "".join(PARA_PRS))
        + STYLES
        + '</hh:refList>'
        + '<hh:compatibleDocument targetProgram="HWP201X">'
          '<hh:layoutCompatibility/></hh:compatibleDocument>'
        + '<hh:docOption>'
          '<hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/>'
          '</hh:docOption>'
        + '</hh:head>')
    return W._xml_bytes(body)


# ---------------------------------------------------------------------------
# Section body builders
# ---------------------------------------------------------------------------
_next_id = [1000]


def oid() -> int:
    _next_id[0] += 7
    return _next_id[0]


class Section:
    """Accumulates top-level blocks (paragraphs) and records feature markers."""

    def __init__(self, index: int):
        self.index = index
        self.blocks: list[str] = []
        #: feature id -> ordinal of the block that opens it
        self.markers: list[dict] = []

    def para(self, text_runs: str, para: str = "base", *, lineseg=True) -> int:
        ordinal = len(self.blocks)
        seg = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
               ' vertsize="1000" textheight="1000" baseline="850"'
               ' spacing="600" horzpos="0" horzsize="%d" flags="393216"/>'
               '</hp:linesegarray>' % BODY_W) if lineseg else ""
        self.blocks.append(
            '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s%s</hp:p>'
            % (oid(), PP[para][0], text_runs, seg))
        return ordinal

    def raw(self, xml: str) -> int:
        ordinal = len(self.blocks)
        self.blocks.append(xml)
        return ordinal


def run(text: str = "", char: str = "base", extra: str = "") -> str:
    body = extra
    if text:
        body += "<hp:t>%s</hp:t>" % esc(text)
    if not body:
        body = "<hp:t/>"
    return '<hp:run charPrIDRef="%d">%s</hp:run>' % (CP[char][0], body)


def runs(*parts: str) -> str:
    return "".join(parts)


# --- tables ----------------------------------------------------------------
def cell(text: str, *, col: int, row: int, colspan: int = 1, rowspan: int = 1,
         width: int, height: int, bf: int = BF_SOLID, valign: str = "CENTER",
         char: str = "cell", para: str = "cell") -> str:
    seg = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' vertsize="900" textheight="900" baseline="765" spacing="540"'
           ' horzpos="0" horzsize="%d" flags="393216"/></hp:linesegarray>'
           % max(width - 282, 100))
    return (
        '<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0"'
        ' dirty="0" borderFillIDRef="%d">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
        ' vertAlign="%s" linkListIDRef="0" linkListNextIDRef="0"'
        ' textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0">%s%s</hp:p>'
        '</hp:subList>'
        '<hp:cellAddr colAddr="%d" rowAddr="%d"/>'
        '<hp:cellSpan colSpan="%d" rowSpan="%d"/>'
        '<hp:cellSz width="%d" height="%d"/>'
        '<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
        '</hp:tc>'
        % (bf, valign, oid(), PP[para][0], run(text, char), seg,
           col, row, colspan, rowspan, width, height))


def table(rows: list[str], *, width: int, height: int, row_cnt: int,
          col_cnt: int, page_break: str = "TABLE",
          repeat_header: int = 0) -> str:
    return (
        '<hp:tbl id="%d" zOrder="0" numberingType="TABLE"'
        ' textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0"'
        ' dropcapstyle="None" pageBreak="%s" repeatHeader="%d" rowCnt="%d"'
        ' colCnt="%d" cellSpacing="0" borderFillIDRef="%d" noAdjust="0">'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d"'
        ' heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1"'
        ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
        ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0"'
        ' horzOffset="0"/>'
        '<hp:outMargin left="141" right="141" top="141" bottom="141"/>'
        '<hp:inMargin left="140" right="140" top="140" bottom="140"/>'
        '%s</hp:tbl>'
        % (oid(), page_break, repeat_header, row_cnt, col_cnt, BF_SOLID,
           width, height, "".join(rows)))


def table_para(tbl: str) -> str:
    """A table is carried by a paragraph whose single run holds it."""
    return ('<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
            ' vertsize="1000" textheight="1000" baseline="850" spacing="0"'
            ' horzpos="0" horzsize="%d" flags="393216"/></hp:linesegarray>'
            '</hp:p>' % (oid(), PP["base"][0], CP["base"][0], tbl, BODY_W))


# --- picture ---------------------------------------------------------------
def png_bytes(width: int, height: int) -> bytes:
    """A deterministic synthetic PNG: a bordered chequer with a diagonal.

    Written by hand (zlib + struct) so the corpus image needs no image
    library at build time and is byte-reproducible.
    """
    rows = []
    for y in range(height):
        row = bytearray([0])          # filter 0 (None)
        for x in range(width):
            edge = x < 2 or y < 2 or x >= width - 2 or y >= height - 2
            diag = abs(x - y) < 2
            check = ((x // 8) + (y // 8)) % 2 == 0
            if edge or diag:
                row += bytes((32, 48, 96))
            elif check:
                row += bytes((214, 224, 240))
            else:
                row += bytes((255, 255, 255))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


IMG_PX = 120
IMG_W, IMG_H = 12000, 9000          # HWPUNIT on the page


def picture(*, treat_as_char: bool, text_wrap: str) -> str:
    org_w, org_h = IMG_PX * 75, IMG_PX * 75      # 1 px == 75 HWPUNIT @96dpi
    return (
        '<hp:pic id="%d" zOrder="1" numberingType="PICTURE" textWrap="%s"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href=""'
        ' groupLevel="0" instid="%d" reverse="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d"'
        ' rotateimage="0"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="%.6f" e2="0" e3="0" e4="0" e5="%.6f" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>'
        '<hc:img binaryItemIDRef="image1" bright="0" contrast="0"'
        ' effect="REAL_PIC" alpha="0"/>'
        '<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/>'
        '<hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/></hp:imgRect>'
        '<hp:imgClip left="0" right="%d" top="0" bottom="%d"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:imgDim dimwidth="%d" dimheight="%d"/>'
        '<hp:effects/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d"'
        ' heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="%d" affectLSpacing="0" flowWithText="1"'
        ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
        ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="CENTER"'
        ' vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '</hp:pic>'
        % (oid(), text_wrap, oid(), org_w, org_h, IMG_W, IMG_H,
           IMG_W // 2, IMG_H // 2, IMG_W / org_w, IMG_H / org_h,
           org_w, org_w, org_h, org_h, org_w, org_h, org_w, org_h,
           IMG_W, IMG_H, 1 if treat_as_char else 0))


# --- equation --------------------------------------------------------------
def equation(script: str, *, width: int, height: int) -> str:
    return (
        '<hp:equation id="%d" zOrder="2" numberingType="EQUATION"'
        ' textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0"'
        ' dropcapstyle="None" version="Equation Version 60" baseLine="85"'
        ' textColor="#000000" baseUnit="1000" lineMode="CHAR"'
        ' font="HancomEQN">'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d"'
        ' heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1"'
        ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
        ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT"'
        ' vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:script>%s</hp:script>'
        '</hp:equation>' % (oid(), width, height, esc(script)))


# --- notes, fields, shapes -------------------------------------------------
def _note_sublist(text: str) -> str:
    seg = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' vertsize="800" textheight="800" baseline="680" spacing="240"'
           ' horzpos="0" horzsize="%d" flags="393216"/></hp:linesegarray>'
           % BODY_W)
    return ('<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
            ' vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0"'
            ' textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s%s</hp:p></hp:subList>'
            % (oid(), PP["note"][0], run(text, "note"), seg))


def foot_note(text: str) -> str:
    # Notes are controls: Hancom silently drops an hp:footNote that is not
    # wrapped in hp:ctrl (measured on this document's first COM round-trip).
    return ('<hp:ctrl><hp:footNote number="1" suffixChar=")" prefixChar=""'
            ' instId="%d">%s</hp:footNote></hp:ctrl>'
            % (oid(), _note_sublist(text)))


def end_note(text: str) -> str:
    return ('<hp:ctrl><hp:endNote number="1" suffixChar=")" prefixChar=""'
            ' instId="%d">%s</hp:endNote></hp:ctrl>'
            % (oid(), _note_sublist(text)))


def hyperlink(text: str, href: str) -> str:
    fid = oid()
    return (
        '<hp:ctrl><hp:fieldBegin id="%d" type="HYPERLINK" name=""'
        ' editable="0" dirty="0" zorder="0" fieldid="%d">'
        '<hp:parameters count="1" name="">'
        '<hp:stringParam name="Command">%s;0;1;0;0;</hp:stringParam>'
        '</hp:parameters></hp:fieldBegin></hp:ctrl>'
        '%s'
        '<hp:ctrl><hp:fieldEnd beginIDRef="%d" fieldid="%d"/></hp:ctrl>'
        % (fid, fid, esc(href), "<hp:t>%s</hp:t>" % esc(text), fid, fid))


def rect_with_text(text: str, *, width: int, height: int) -> str:
    seg = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' vertsize="1000" textheight="1000" baseline="850" spacing="0"'
           ' horzpos="0" horzsize="%d" flags="1441792"/></hp:linesegarray>'
           % max(width - 566, 100))
    return (
        '<hp:rect id="%d" zOrder="3" numberingType="NONE"'
        ' textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0"'
        ' dropcapstyle="None" href="" groupLevel="0" instid="%d" ratio="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d"'
        ' rotateimage="0"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>'
        '<hp:lineShape color="#1F3864" width="150" style="SOLID"'
        ' endCap="FLAT" headStyle="NORMAL" tailStyle="NORMAL" headfill="1"'
        ' tailfill="1" headSz="MEDIUM_MEDIUM" tailSz="MEDIUM_MEDIUM"'
        ' outlineStyle="NORMAL" alpha="0"/>'
        '<hc:fillBrush><hc:winBrush faceColor="#EDF2FA" hatchColor="#000000"'
        ' alpha="0"/></hc:fillBrush>'
        '<hp:shadow type="NONE" color="#000000" offsetX="0" offsetY="0"'
        ' alpha="0"/>'
        '<hp:drawText lastWidth="%d" name="" editable="0">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
        ' vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0"'
        ' textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0">%s%s</hp:p></hp:subList>'
        '<hp:textMargin left="283" right="283" top="283" bottom="283"/>'
        '</hp:drawText>'
        '<hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/>'
        '<hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d"'
        ' heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1"'
        ' allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA"'
        ' horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT"'
        ' vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '</hp:rect>'
        % (oid(), oid(), width, height, width, height, width // 2,
           height // 2, width, oid(), PP["cell"][0], run(text, "cell"), seg,
           width, width, height, height, width, height))


# --- section properties ----------------------------------------------------
def _furniture_para(text: str, with_page_num: bool) -> str:
    seg = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' vertsize="900" textheight="900" baseline="765" spacing="270"'
           ' horzpos="0" horzsize="%d" flags="393216"/></hp:linesegarray>'
           % BODY_W)
    body = run(text, "furniture")
    if with_page_num:
        body += ('<hp:run charPrIDRef="%d"><hp:t> </hp:t>'
                 '<hp:ctrl><hp:pageNum pos="BOTTOM_CENTER"'
                 ' formatType="DIGIT" sideChar="-"/></hp:ctrl>'
                 '<hp:ctrl><hp:autoNum num="1" numType="PAGE"/></hp:ctrl>'
                 '</hp:run>' % CP["furniture"][0])
    return ('<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0">%s%s</hp:p>'
            % (oid(), PP["furniture"][0], body, seg))


def header_ctrl(text: str) -> str:
    return ('<hp:ctrl><hp:header id="1" applyPageType="BOTH">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
            ' vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0"'
            ' textWidth="%d" textHeight="0" hasTextRef="0" hasNumRef="0">'
            '%s</hp:subList></hp:header></hp:ctrl>'
            % (BODY_W, _furniture_para(text, False)))


def footer_ctrl(text: str) -> str:
    return ('<hp:ctrl><hp:footer id="2" applyPageType="BOTH">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
            ' vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0"'
            ' textWidth="%d" textHeight="0" hasTextRef="0" hasNumRef="0">'
            '%s</hp:subList></hp:footer></hp:ctrl>'
            % (BODY_W, _furniture_para(text, True)))




_PAGE_BORDER_FILLS = "".join(
    '<hp:pageBorderFill type="%s" borderFillIDRef="%d" textBorder="PAPER"'
    ' headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
    '</hp:pageBorderFill>' % (kind, BF_NONE)
    for kind in ("BOTH", "EVEN", "ODD"))

_NOTE_PR = (
    '<hp:footNotePr>'
    '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
    ' supscript="0"/>'
    '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="850" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="EACH_COLUMN" beneathText="0"/>'
    '</hp:footNotePr>'
    '<hp:endNotePr>'
    '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
    ' supscript="0"/>'
    '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm"'
    ' color="#000000"/>'
    '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
    '</hp:endNotePr>')


def sec_pr(*, width: int, height: int, landscape: str, margin: dict,
           col_count: int, furniture: str = "") -> str:
    """The ``hp:secPr`` + ``hp:colPr`` + furniture run payload for a section.

    Order matters, and it is not the schema's business: ``ParaList XML
    schema.xml`` lets the section-head paragraph carry its ``hp:ctrl``
    children in any order, but **Hancom only honours an ``hp:colPr`` that is
    the first control after ``hp:secPr``**.  Measured (two probe documents,
    Hwp 2024 13.0.0.2986, one section per case, PDF export read back for the
    x-extent of the text):

    ======  =====================================  ==============
    case    section-head control order             Hancom renders
    ======  =====================================  ==============
    P1/P2   secPr, header, footer, colPr           one column
    Q1      secPr, header, colPr, footer           one column
    Q3      secPr, footer, colPr                   one column
    Q2      secPr, colPr                           two columns
    P4/Q4   secPr, colPr, header, footer           two columns
    P5      secPr, header, footer; colPr in the    two columns
            *next* paragraph
    ======  =====================================  ==============

    ``colCount``, ``type``, ``layout``, ``sameSz``, ``sameGap`` and explicit
    ``hp:colSz`` children make no difference to this: ``sameGap="0"`` in the
    honoured position gives two columns (P5, Q2, Q4), and
    ``BALANCED_NEWSPAPER`` / ``sameSz="0"`` + ``hp:colSz`` / ``sameSz="true"``
    in the ignored position all still give one (P3, P6, P7).  A header or
    footer control between ``hp:secPr`` and ``hp:colPr`` is the whole
    mechanism.

    This document used to emit the P1 order, which is why `F49` 다단 declared
    ``colCount="2"`` and Hancom rendered it full width — the document was
    malformed, not the renderer.
    """
    return (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134"'
        ' tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT"'
        ' outlineShapeIDRef="0" memoShapeIDRef="0" textVerticalWidthHead="0"'
        ' masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0"'
        ' equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0"'
        ' hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL"'
        ' hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0"'
        ' startNumber="0"/>'
        '<hp:pagePr landscape="%s" width="%d" height="%d"'
        ' gutterType="LEFT_ONLY">'
        '<hp:margin header="%d" footer="%d" gutter="%d" left="%d" right="%d"'
        ' top="%d" bottom="%d"/>'
        '</hp:pagePr>'
        % (landscape, width, height, margin["header"], margin["footer"],
           margin["gutter"], margin["left"], margin["right"], margin["top"],
           margin["bottom"])
        + _NOTE_PR + _PAGE_BORDER_FILLS + '</hp:secPr>'
        + '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT"'
          ' colCount="%d" sameSz="1" sameGap="0"/></hp:ctrl>' % col_count
        + furniture)


#: Ship the document with NO cached line layout.
#:
#: Measured on this document's first Hancom round-trip: Hancom's HWPX reader
#: *trusts* ``hp:linesegarray`` when it is present and its ``horzsize`` agrees
#: with the paragraph's available width.  A generator cannot know where the
#: lines will fall before Hancom lays them out, so the one-lineseg cache the
#: builders below emit made Hancom draw each whole paragraph as a single
#: justified line of overlapping glyphs — every alignment and line-spacing
#: block looked identical and wrong.  Paragraphs whose own margins made the
#: cached ``horzsize`` stale (내어쓰기, 좌우 여백) were the only ones Hancom
#: relaid out, which is what identified the mechanism.
#:
#: With no cache, both engines run their own line breaker, which is the only
#: state in which their output is comparable.  The builders keep emitting a
#: cache so the code still documents the full paragraph shape; this is the one
#: place it is dropped, and flipping the flag restores the trusted-cache
#: behaviour for anyone who wants to study it.
EMIT_LINE_CACHE = False

_LINESEG_RE = None


def section_xml(sec: "Section") -> bytes:
    global _LINESEG_RE
    body = "".join(sec.blocks)
    if not EMIT_LINE_CACHE:
        import re
        if _LINESEG_RE is None:
            _LINESEG_RE = re.compile(
                r"<hp:linesegarray>.*?</hp:linesegarray>", re.S)
        body = _LINESEG_RE.sub("", body)
    return W._xml_bytes('<hs:sec' + NS + '>' + body + '</hs:sec>')


# ---------------------------------------------------------------------------
# The feature blocks
# ---------------------------------------------------------------------------
#: Filler that is long enough to wrap, so alignment and line spacing are
#: actually visible.  Synthetic Korean, no personal data.
FILLER = ("가나다라마바사 아자차카타파하 렌더 비교용 표본 문장이며 줄바꿈이"
          " 일어나도록 충분히 길게 이어 붙인 합성 문자열입니다. 같은 문장을"
          " 모든 블록이 공유하므로 차이는 서식에서만 나옵니다.")
SHORT = "가나다라마바사 아자차카타파하 ABCdef 0123"


class Feature:
    """One labelled feature block.

    ``ordinal`` is the position of the block that *opens* the feature among
    its section's top-level blocks — the only handle ``render_check.py``
    needs, because ``own_render``'s ``block_layout[sec]["blocks"]`` lists
    exactly those blocks, in the same order, with their page and vertical
    position.  Page furniture has no top-level block, so a header/footer
    feature carries ``band`` instead and is located from the section's
    ``page_furniture.areas_hwpunit``.
    """

    __slots__ = ("fid", "label", "section", "ordinal", "band")

    def __init__(self, fid, label, section, ordinal, band=None):
        self.fid = fid
        self.label = label
        self.section = section
        self.ordinal = ordinal
        self.band = band

    def as_dict(self):
        row = {"id": self.fid, "label": self.label, "section": self.section}
        if self.band:
            row["band"] = self.band
        else:
            row["block_ordinal"] = self.ordinal
        return row


class Doc:
    def __init__(self):
        self.sections: list[Section] = []
        self.features: list[Feature] = []
        self._n = 0

    def new_section(self) -> Section:
        sec = Section(len(self.sections))
        self.sections.append(sec)
        return sec

    def feature(self, sec: Section, label: str, *, declared_skip=None,
                para: str = "label") -> str:
        """Open a feature block: emit its label paragraph, record the ordinal."""
        self._n += 1
        fid = "F%02d" % self._n
        ordinal = sec.para(run("[%s] %s" % (fid, label), "label"), para)
        self.features.append(
            Feature(fid, label, sec.index, ordinal, declared_skip))
        return fid


def build() -> Doc:
    doc = Doc()

    # -- section 0: portrait, single column, header + footer -----------------
    s0 = doc.new_section()
    s0.raw(
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="%d">%s</hp:run>'
        '<hp:run charPrIDRef="%d"><hp:t>렌더 검수 문서 · render-check-01'
        '</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1100"'
        ' textheight="1100" baseline="935" spacing="660" horzpos="0"'
        ' horzsize="%d" flags="393216"/></hp:linesegarray></hp:p>'
        % (oid(), PP["align_center"][0], CP["base"][0],
           sec_pr(width=A4_W, height=A4_H, landscape="WIDELY", margin=MARGIN,
                  col_count=1,
                  furniture=(header_ctrl("render-check-01 · 머리말 (header)")
                             + footer_ctrl("꼬리말 · 쪽"))),
           CP["label"][0], BODY_W))

    # 문단 정렬 ×5
    for label, para in (("정렬 — 왼쪽 (align LEFT)", "align_left"),
                        ("정렬 — 가운데 (align CENTER)", "align_center"),
                        ("정렬 — 오른쪽 (align RIGHT)", "align_right"),
                        ("정렬 — 양쪽 (align JUSTIFY)", "align_justify"),
                        ("정렬 — 배분 (align DISTRIBUTE)", "align_distribute")):
        doc.feature(s0, label)
        s0.para(run(FILLER), para)

    # 줄 간격
    for label, para in (("줄간격 — 130% (PERCENT)", "ls_130"),
                        ("줄간격 — 160% (PERCENT)", "ls_160"),
                        ("줄간격 — 200% (PERCENT)", "ls_200"),
                        ("줄간격 — 고정 24pt (FIXED)", "ls_fixed")):
        doc.feature(s0, label)
        s0.para(run(FILLER + FILLER), para)

    # 들여쓰기 / 여백
    for label, para in (("첫줄 들여쓰기 (first-line indent)", "indent_first"),
                        ("내어쓰기 (hanging indent)", "indent_hanging"),
                        ("좌우 여백 (left/right margin)", "indent_lr")):
        doc.feature(s0, label)
        s0.para(run(FILLER), para)

    # 글자 모양 — 자간/장평/relSz/offset
    doc.feature(s0, "자간 (hh:spacing −15 / 0 / +30)")
    s0.para(runs(run("좁게 " + SHORT, "spacing_tight"),
                 run(" 보통 " + SHORT, "base"),
                 run(" 넓게 " + SHORT, "spacing_wide")), "align_left")
    doc.feature(s0, "장평 (hh:ratio 50 / 100 / 150)")
    s0.para(runs(run("50% " + SHORT, "ratio_narrow"),
                 run(" 100% " + SHORT, "base"),
                 run(" 150% " + SHORT, "ratio_wide")), "align_left")
    doc.feature(s0, "상대 크기 (hh:relSz 60 / 100 / 140)")
    s0.para(runs(run("60% " + SHORT, "relsz_small"),
                 run(" 100% " + SHORT, "base"),
                 run(" 140% " + SHORT, "relsz_large")), "align_left")
    doc.feature(s0, "글자 위치 (hh:offset +40 / 0 / −40)")
    s0.para(runs(run("위 " + SHORT, "offset_up"),
                 run(" 기준 " + SHORT, "base"),
                 run(" 아래 " + SHORT, "offset_down")), "align_left")

    # 글자 속성 — one block each, so each gets its own verdict
    for label, char in (("진하게 (bold)", "bold"),
                        ("기울임 (italic)", "italic"),
                        ("밑줄 (underline)", "underline"),
                        ("취소선 (strikeout)", "strike")):
        doc.feature(s0, label)
        s0.para(runs(run("보통 " + SHORT + "  →  "), run(SHORT, char)),
                "align_left")

    doc.feature(s0, "위첨자 (superscript)")
    s0.para(runs(run("x"), run("2", "super"), run(" + y"), run("2", "super"),
                 run(" = r"), run("2", "super"),
                 run("   n"), run("k+1", "super")), "align_left")
    doc.feature(s0, "아래첨자 (subscript)")
    s0.para(runs(run("H"), run("2", "sub"), run("O, CO"), run("2", "sub"),
                 run(", a"), run("i,j", "sub")), "align_left")

    # 글꼴 3종 — declared by name
    for label, char in (("글꼴 — 바탕 (declared face 바탕)", "batang"),
                        ("글꼴 — 돋움 (declared face 돋움)", "dotum"),
                        ("글꼴 — 궁서 (declared face 궁서)", "gungsu")):
        doc.feature(s0, label)
        s0.para(run(SHORT + " " + SHORT, char), "align_left")

    # 글자 크기 8–24 pt
    doc.feature(s0, "글자 크기 8 / 10 / 12 / 14 / 18 / 24 pt")
    s0.para(runs(run("8pt ", "pt8"), run("10pt ", "pt10"),
                 run("12pt ", "pt12"), run("14pt ", "pt14"),
                 run("18pt ", "pt18"), run("24pt", "pt24")), "align_left")

    # -- 표 -------------------------------------------------------------------
    doc.feature(s0, "표 — 기본 격자 (plain grid 3×3)")
    w = BODY_W // 3
    rows = []
    for r in range(3):
        rows.append("<hp:tr>" + "".join(
            cell("R%dC%d" % (r + 1, c + 1), col=c, row=r, width=w, height=2400)
            for c in range(3)) + "</hp:tr>")
    s0.raw(table_para(table(rows, width=w * 3, height=7200, row_cnt=3,
                            col_cnt=3)))

    doc.feature(s0, "표 — 셀 병합 (colSpan 2 + rowSpan 2)")
    rows = [
        "<hp:tr>"
        + cell("가로 병합 (colSpan=2)", col=0, row=0, colspan=2, width=w * 2,
               height=2400)
        + cell("세로 병합 (rowSpan=2)", col=2, row=0, rowspan=2, width=w,
               height=4800) + "</hp:tr>",
        "<hp:tr>" + cell("R2C1", col=0, row=1, width=w, height=2400)
        + cell("R2C2", col=1, row=1, width=w, height=2400) + "</hp:tr>",
        "<hp:tr>" + "".join(
            cell("R3C%d" % (c + 1), col=c, row=2, width=w, height=2400)
            for c in range(3)) + "</hp:tr>",
    ]
    s0.raw(table_para(table(rows, width=w * 3, height=7200, row_cnt=3,
                            col_cnt=3)))

    doc.feature(s0, "표 — 셀 음영 (cell shading #D9D9D9)")
    rows = [
        "<hp:tr>" + "".join(
            cell("음영 %d" % (c + 1), col=c, row=0, width=w, height=2400,
                 bf=BF_SHADE) for c in range(3)) + "</hp:tr>",
        "<hp:tr>" + "".join(
            cell("보통 %d" % (c + 1), col=c, row=1, width=w, height=2400)
            for c in range(3)) + "</hp:tr>",
    ]
    s0.raw(table_para(table(rows, width=w * 3, height=4800, row_cnt=2,
                            col_cnt=3)))
    # 캡션 on a table — an ordinary paragraph that follows the object, which
    # is how Hancom bakes 캡션 text into the saved document.
    doc.feature(s0, "캡션 — 표 (table caption)", para="caption")
    s0.para(run("〈표 1〉 셀 음영 표본", "caption"), "caption")

    doc.feature(s0, "표 — 테두리 종류 (SOLID / DASH / DOT / DOUBLE / 굵기)")
    w4 = BODY_W // 4
    rows = ["<hp:tr>" + "".join(
        cell(name, col=i, row=0, width=w4, height=2400, bf=bf)
        for i, (name, bf) in enumerate(
            (("SOLID", BF_SOLID), ("DASH", BF_DASH), ("DOT", BF_DOT),
             ("DOUBLE", BF_DOUBLE)))) + "</hp:tr>",
        "<hp:tr>" + "".join(
        cell(name, col=i, row=1, width=w4, height=2400, bf=bf)
        for i, (name, bf) in enumerate(
            (("0.12mm", BF_SOLID), ("0.5mm", BF_THICK), ("0.12mm", BF_SOLID),
             ("0.5mm", BF_THICK)))) + "</hp:tr>"]
    s0.raw(table_para(table(rows, width=w4 * 4, height=4800, row_cnt=2,
                            col_cnt=4)))

    doc.feature(s0, "표 — 셀 세로 정렬 (TOP / CENTER / BOTTOM)")
    rows = ["<hp:tr>" + "".join(
        cell(v, col=i, row=0, width=w, height=6000, valign=v)
        for i, v in enumerate(("TOP", "CENTER", "BOTTOM"))) + "</hp:tr>"]
    s0.raw(table_para(table(rows, width=w * 3, height=6000, row_cnt=1,
                            col_cnt=3)))

    # -- 그림 ------------------------------------------------------------------
    doc.feature(s0, "그림 — 본문 안 (inline, treatAsChar)")
    s0.para(runs(run("본문 흐름 안의 그림 "),
                 run(extra=picture(treat_as_char=True,
                                   text_wrap="TOP_AND_BOTTOM")),
                 run(" 뒤 텍스트")), "align_left")
    doc.feature(s0, "캡션 — 그림 (image caption)", para="caption")
    s0.para(run("[그림 1] 합성 격자 이미지 (120×120 px PNG)", "caption"),
            "caption")

    doc.feature(s0, "그림 — 어울림 TOP_AND_BOTTOM (anchored, text wrap)")
    s0.para(run(extra=picture(treat_as_char=False,
                              text_wrap="TOP_AND_BOTTOM")), "align_center")
    s0.para(run(FILLER), "align_justify")

    # -- 수식 ------------------------------------------------------------------
    for label, script, ew, eh in (
            ("수식 — 분수 (fraction)", "a over b", 4000, 2400),
            ("수식 — 근호 (sqrt)", "sqrt {x^{2} + y^{2}}", 9000, 2400),
            ("수식 — 총합·상하한 (sum with limits)",
             "sum _{i=1} ^{n} i^{2} = {n(n+1)(2n+1)} over 6", 22000, 3600),
            ("수식 — 행렬 (matrix)",
             "left [ matrix{ 1 & 2 # 3 & 4 } right ]", 8000, 3600)):
        doc.feature(s0, label)
        s0.para(run(extra=equation(script, width=ew, height=eh)),
                "align_center")

    # -- 개요 번호 / 글머리표 ----------------------------------------------------
    doc.feature(s0, "개요 번호 — 3수준 (numbered outline, 1. / 1.1 / 1.1.1)")
    s0.para(run("1수준 항목"), "outline1")
    s0.para(run("2수준 항목"), "outline2")
    s0.para(run("3수준 항목"), "outline3")
    s0.para(run("두 번째 1수준 항목"), "outline1")

    doc.feature(s0, "글머리표 (bullets)")
    s0.para(run("첫 번째 글머리 항목"), "bullet")
    s0.para(run("두 번째 글머리 항목"), "bullet")

    # -- 각주 / 미주 -------------------------------------------------------------
    doc.feature(s0, "각주 (footnote)")
    s0.para(runs(run("각주가 달린 문장입니다"),
                 run(extra=foot_note("각주 본문 — 합성 문자열")),
                 run(" 그리고 이어지는 본문.")), "align_left")
    doc.feature(s0, "미주 (endnote)")
    s0.para(runs(run("미주가 달린 문장입니다"),
                 run(extra=end_note("미주 본문 — 합성 문자열")),
                 run(" 그리고 이어지는 본문.")), "align_left")

    # -- 하이퍼링크 --------------------------------------------------------------
    doc.feature(s0, "하이퍼링크 (hyperlink field)")
    s0.para('<hp:run charPrIDRef="%d">%s</hp:run>'
            % (CP["link"][0],
               hyperlink("tech.hancom.com/hwpxformat",
                         "https://tech.hancom.com/hwpxformat/")), "align_left")

    # -- 글상자 -----------------------------------------------------------------
    doc.feature(s0, "글상자 / 그리기 개체 사각형 (text box)")
    s0.para(run(extra=rect_with_text("글상자 안의 텍스트 — 사각형 개체",
                                     width=28000, height=5000)),
            "align_center")

    # -- 쪽 나누기 --------------------------------------------------------------
    doc.feature(s0, "쪽 나누기 (page break, pageBreakBefore)",
                para="page_break")
    s0.para(run("이 문단은 강제 쪽 나누기 뒤 첫 문단입니다."), "align_left")

    # -- 페이지를 넘기는 표 -------------------------------------------------------
    doc.feature(s0, "표 — 쪽을 넘기는 표 (table split across a page)")
    rows = []
    for r in range(26):
        rows.append("<hp:tr>" + "".join(
            cell("행 %02d · 열 %d" % (r + 1, c + 1), col=c, row=r, width=w,
                 height=2600) for c in range(3)) + "</hp:tr>")
    s0.raw(table_para(table(rows, width=w * 3, height=2600 * 26, row_cnt=26,
                            col_cnt=3, page_break="CELL", repeat_header=1)))

    # -- section 1: 구역 나누기 — 가로 용지 + 다른 여백 ---------------------------
    s1 = doc.new_section()
    s1.raw(
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
        '<hp:run charPrIDRef="%d"><hp:t>[F%02d] 구역 나누기 — 가로 용지 +'
        ' 다른 여백 (section break, landscape)</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1100"'
        ' textheight="1100" baseline="935" spacing="660" horzpos="0"'
        ' horzsize="%d" flags="393216"/></hp:linesegarray></hp:p>'
        % (oid(), PP["label"][0], CP["base"][0],
           sec_pr(width=A4_H, height=A4_W, landscape="NARROWLY",
                  margin=LAND_MARGIN, col_count=1,
                  furniture=(header_ctrl("render-check-01 · 가로 구역 머리말")
                             + footer_ctrl("가로 구역 · 쪽"))),
           CP["label"][0], doc._n + 1, LAND_BODY_W))
    doc._n += 1
    doc.features.append(Feature("F%02d" % doc._n,
                                "구역 나누기 — 가로 용지 + 다른 여백"
                                " (section break, landscape)", 1, 0))
    s1.para(run(FILLER + FILLER), "align_justify")

    # -- section 2: 다단 (two-column) ------------------------------------------
    s2 = doc.new_section()
    s2.raw(
        '<hp:p id="%d" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
        ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
        '<hp:run charPrIDRef="%d"><hp:t>[F%02d] 다단 — 2단 구역 (two-column'
        ' section)</hp:t></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1100"'
        ' textheight="1100" baseline="935" spacing="660" horzpos="0"'
        ' horzsize="%d" flags="393216"/></hp:linesegarray></hp:p>'
        % (oid(), PP["label"][0], CP["base"][0],
           sec_pr(width=A4_W, height=A4_H, landscape="WIDELY", margin=MARGIN,
                  col_count=2,
                  furniture=(header_ctrl("render-check-01 · 다단 구역 머리말")
                             + footer_ctrl("다단 구역 · 쪽"))),
           CP["label"][0], doc._n + 1, BODY_W))
    doc._n += 1
    doc.features.append(Feature("F%02d" % doc._n,
                                "다단 — 2단 구역 (two-column section)", 2, 0))
    for _ in range(4):
        s2.para(run(FILLER), "align_justify")

    # -- page furniture: located by band, not by block --------------------------
    for label, band in (("머리말 (header)", "header"),
                        ("꼬리말 + 쪽 번호 (footer with page number)",
                         "footer")):
        doc._n += 1
        doc.features.append(
            Feature("F%02d" % doc._n, label, 0, None, band=band))

    return doc


# ---------------------------------------------------------------------------
# Package assembly
# ---------------------------------------------------------------------------
def content_hpf(sec_cnt: int) -> bytes:
    items = ['<opf:item id="header" href="Contents/header.xml"'
             ' media-type="application/xml"/>',
             '<opf:item id="image1" href="BinData/image1.png"'
             ' media-type="image/png" isEmbeded="1"/>']
    spine = ['<opf:itemref idref="header" linear="yes"/>']
    for i in range(sec_cnt):
        items.append('<opf:item id="section%d" href="Contents/section%d.xml"'
                     ' media-type="application/xml"/>' % (i, i))
        spine.append('<opf:itemref idref="section%d" linear="yes"/>' % i)
    items.append('<opf:item id="settings" href="settings.xml"'
                 ' media-type="application/xml"/>')
    return W._xml_bytes(
        '<opf:package' + NS + ' version="" unique-identifier="" id="">'
        '<opf:metadata>'
        '<opf:title>render-check-01</opf:title>'
        '<opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="Rigorloom"/>'
        '<opf:meta name="subject" content="render check"/>'
        '<opf:meta name="description" content="synthetic renderer'
        ' feature-comparison document"/>'
        '</opf:metadata>'
        '<opf:manifest>' + "".join(items) + '</opf:manifest>'
        '<opf:spine>' + "".join(spine) + '</opf:spine>'
        '</opf:package>')


def container_rdf(sec_cnt: int) -> bytes:
    pkg = W._PKG
    parts = [('Contents/header.xml', 'HeaderFile')]
    parts += [('Contents/section%d.xml' % i, 'SectionFile')
              for i in range(sec_cnt)]
    body = "".join(
        '<rdf:Description rdf:about="">'
        '<ns0:hasPart xmlns:ns0="%s" rdf:resource="%s"/>'
        '</rdf:Description>'
        '<rdf:Description rdf:about="%s">'
        '<rdf:type rdf:resource="%s%s"/></rdf:Description>'
        % (pkg, href, href, pkg, kind) for href, kind in parts)
    return W._xml_bytes(
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        + body
        + '<rdf:Description rdf:about="">'
          '<rdf:type rdf:resource="%sDocument"/></rdf:Description>'
          '</rdf:RDF>' % pkg)


def assemble(doc: Doc):
    sec_cnt = len(doc.sections)
    members = [("mimetype", W.MIMETYPE),
               ("version.xml", W._xml_bytes(W._BLANK_VERSION)),
               ("Contents/header.xml", header_xml(sec_cnt))]
    for sec in doc.sections:
        members.append(("Contents/section%d.xml" % sec.index,
                        section_xml(sec)))
    members += [
        ("BinData/image1.png", png_bytes(IMG_PX, IMG_PX)),
        ("Preview/PrvText.txt", b""),
        ("settings.xml", W._xml_bytes(W._BLANK_SETTINGS)),
        ("META-INF/container.rdf", container_rdf(sec_cnt)),
        ("Contents/content.hpf", content_hpf(sec_cnt)),
        ("META-INF/container.xml", W._xml_bytes(W._BLANK_CONTAINER)),
        ("META-INF/manifest.xml", W._xml_bytes(W._BLANK_MANIFEST)),
    ]
    package = W.hancom_package(members)
    package.validate()
    return package


def blocks_sidecar(doc: Doc) -> dict:
    return {
        "schema": "rigorloom/render-check-blocks/v1",
        "document": "render-check-01.hwpx",
        "provenance": "Rigorloom-authored synthetic",
        "sections": [
            {"index": s.index, "block_count": len(s.blocks)}
            for s in doc.sections],
        "features": [f.as_dict() for f in doc.features],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(_HERE / "render-check-01.hwpx"))
    parser.add_argument("--blocks", default=None,
                        help="where to write the feature/block sidecar"
                             " (default: <out> with .blocks.json)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    doc = build()
    package = assemble(doc)
    package.write(out)

    blocks = Path(args.blocks) if args.blocks else out.with_suffix(
        "").with_suffix(".blocks.json")
    sidecar = blocks_sidecar(doc)
    with blocks.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n")

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(json.dumps({"ok": True, "out": str(out), "sha256": digest,
                      "bytes": out.stat().st_size,
                      "sections": len(doc.sections),
                      "features": len(doc.features),
                      "blocks": str(blocks)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
