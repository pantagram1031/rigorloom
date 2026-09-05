#!/usr/bin/env python3
"""A MEASURED advance table for HWP's own HFT faces, and what it is worth.

#288 established what the anonymous Type 3 fonts in the reference exports
are: HWP's own **HFT** faces -- 한양신명조, 한양중고딕, 명조, 고딕, HCI Poppy
and the rest of the 한양 set -- and that ``hh:font@type="HFT"`` on the slot
HWP meters a character off predicts, 8566 of 8566, that Hancom drew it from
one.  It also established that nothing on this machine reproduces their
advances (0 of 492 candidate faces) and that no fixed fraction of the em per
character class does either (93.0% against a 99% gate).

What is left is the table itself.  A Type 3 font declares its advances in
``/Widths``, in the font's own grid, and ``Widths[code] x FontMatrix[0]`` is
that advance in em.  Those numbers are the export's own output -- the same
black-box output every other measurement in this repo reads -- so reading
them, grouping them by the HFT face the paired runs declare, and writing them
down is a MEASUREMENT of Hancom's published behaviour and not an extraction
of anything from Hancom's software.

WHAT THIS EMITS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
``engine/references/fonts/hft-widths.measured.json`` carries, per (HFT face,
code point): the advance in em, how many characters were observed at it, and
which reference forms they came from.  It carries **advance widths only**.
No glyph outline, no ``CharProcs`` stream, no font program, no byte of any
Hancom font file -- none of which this script even opens.  The header of the
emitted file declares all of that, with the coverage, so a reader of the
table never has to reconstruct where it came from.

Usage::

    python engine/scripts/hft_width_table.py --build
    python engine/scripts/hft_width_table.py --build --out PATH
    python engine/scripts/hft_width_table.py --score
    python engine/scripts/hft_width_table.py --score --carriers

``--build`` measures the corpus and writes the table.  ``--score`` prices it:
the table as the metric source for HFT-declared runs, #283's full-width cell
rule for substituted faces, and both together, each against the cached break
positions, the one-sided fit test and the two ``moel-2013`` carriers.

HOW ``--score`` SWITCHES RULES
------------------------------
The renderer implements the table rule behind ``_advance_hwp``; the cell rule
lives here, as a mixin, because it is #283's proposal and this slice only
needs to PRICE it.  A variant is installed by rebinding
``own_render.OwnRenderer`` and ``advance_probe.BreakRecordingRenderer`` for
the length of one measurement, which is what makes the break test the REAL
breaker on real inputs rather than a second model of it.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import advance_probe  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import pdf_face_probe  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402
import own_render  # noqa: E402
from own_render import HWPUNIT_PER_PT, hwp_metric_slot  # noqa: E402


#: Where the measured table is written and where the renderer reads it.
TABLE_REL = own_render.HFT_WIDTH_TABLE_REL

#: The month the corpus references were read in.  Written into the emitted
#: header so a later reader can tell how old the measurement is without
#: consulting git.
MEASURED_ON = "2026-09"

#: The paragraphs #267 named and #281 and #288 could not close.
CARRIERS = {"moel-pyojun-geunrogyeyakseo-2013": (118, 141)}


# -- the measurement -----------------------------------------------------

def attribute_by_metric_slot(hwpx_path, pdf_path, repo_root):
    """``{pdf font: {char: Counter((face, type))}}``, on the METRIC slot.

    ``pdf_face_probe.attribute_spans`` files a character's declared face
    under ``script_slot``'s slot, which is the slot the glyph is DRAWN from.
    A width table is looked up by the slot the character is METERED off, and
    #288 measured that the two disagree on ASCII punctuation -- so the two
    carriers, whose ``hh:charPr`` names 한양신명조 for ``symbol`` and HCI
    Poppy for ``latin``, would be written under one name and read under the
    other.  Both slots are HFT there, so this is not the 22-character
    prediction question #288 settled; it is which face's table the advance
    belongs in, and it has to be the one the renderer will ask for.

    The pairing is ``lineseg_vs_pdf``'s, reached through the same
    ``advance_probe`` helpers ``attribute_spans`` uses.
    """
    renderer = own_render.OwnRenderer(hwpx_path, repo_root=repo_root)
    types = pdf_face_probe.declared_font_types(hwpx_path)
    pdf = advance_probe.read_pdf_chars(pdf_path)
    cursor = 0
    usage = defaultdict(lambda: defaultdict(Counter))
    for section in range(len(renderer.sections)):
        renderer._current_section = section
        for el in own_render._kids(renderer.sections[section], "p"):
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
            for index, (clo, chi) in enumerate(
                    lineseg_vs_pdf.cached_split(para, cells)):
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
                    face, ftype, _sf, _st = pdf_face_probe.declared_for(
                        renderer, types, cid, hwp_metric_slot(char))
                    if face:
                        usage[boxes[j].get("font")][char][(face, ftype)] += 1
    return usage


def read_corpus(targets, repo_root, keep_text=True):
    """``(fonts_by_form, attribution)`` for every (hwpx, pdf) pair given."""
    fonts_by_form = {}
    attribution = {}
    for hwpx, pdf in targets:
        form = Path(pdf).stem
        fonts_by_form[form] = pdf_face_probe.read_font_objects(pdf)
        if hwpx is not None:
            attribution[form] = attribute_by_metric_slot(hwpx, pdf, repo_root)
    return fonts_by_form, attribution


def measure(fonts_by_form, attribution):
    """Per (declared face, code point): the em advances observed, with source.

    ``pdf_face_probe.fraction_table`` groups the same way and is what #288's
    fixed-fraction question was priced on; this keeps the per-form provenance
    and the observation counts a shipped table has to declare, and it filters
    to the faces the file itself calls ``HFT``.
    """
    per_face = defaultdict(lambda: defaultdict(
        lambda: {"widths": Counter(), "forms": Counter(),
                 "pdf_fonts": Counter(), "declarations": 0}))
    unattributed = Counter()
    non_hft = Counter()
    for form, fonts in sorted(fonts_by_form.items()):
        seats = attribution.get(form, {})
        for font in fonts.values():
            if font["subtype"] != "Type3":
                continue
            drawn = seats.get(font["span_name"], {})
            for glyph in font["glyphs"].values():
                char = glyph.get("char")
                if not char:
                    continue
                faces = drawn.get(char)
                if not faces:
                    unattributed[char] += 1
                    continue
                (face, ftype), count = faces.most_common(1)[0]
                if (ftype or "").upper() != "HFT":
                    non_hft[(face, ftype)] += count
                    continue
                seat = per_face[face][char]
                seat["widths"][glyph["width_em"]] += count
                seat["forms"][form] += count
                seat["pdf_fonts"][font["span_name"]] += count
                seat["declarations"] += 1
    return per_face, unattributed, non_hft


def verify_against_anchors(targets, fonts_by_form, repo_root, keep_text=True):
    """Do the declared ``Widths`` agree with the pen distances #267 measured?

    ``Widths`` is what the export SAYS a glyph advances by; the anchored
    comparison is how far Hancom actually moved the pen between two aligned
    glyph origins.  They are two different readings of the same export and a
    table built on the first is only usable if the second agrees.

    Only singleton segments are compared -- one character on our side, one
    glyph on Hancom's -- because a segment that swallowed characters Hancom
    never drew carries the space model as well as the glyph.  Three further
    filters, each of which moved the answer when it was missing:

    * only ``comparable`` lines, which is ``advance_probe``'s own name for a
      line whose gaps are its own.  A JUSTIFY or DISTRIBUTE line has its pen
      distances opened or squeezed by the paragraph, and reading one as an
      advance puts a Hangul syllable 0.03 em out and one ``moel-2013`` line
      0.18 em out;
    * no ``hh:spacing``, whose gap is a real pen move and not the glyph's;
    * against the size the PDF sets the font in, not against our declared
      cell, because ``Widths`` are the font's own em.
    """
    rows = []
    for hwpx, pdf in targets:
        if hwpx is None:
            continue
        form = Path(pdf).stem
        type3 = {}
        for font in fonts_by_form[form].values():
            if font["subtype"] != "Type3":
                continue
            for glyph in font["glyphs"].values():
                if glyph.get("char"):
                    type3.setdefault((font["span_name"], glyph["char"]),
                                     glyph["width_em"])
        report = advance_probe.probe_document(hwpx, pdf, repo_root=repo_root,
                                              keep_text=keep_text)
        for para in report["paragraphs"]:
            for line in para["lines"]:
                if not line.get("comparable"):
                    continue
                for char in line.get("chars", []):
                    if char.get("spacing"):
                        continue
                    # Against the size the PDF sets that font in, not against
                    # our declared cell: ``Widths`` are the font's own em and
                    # the export writes the size it drew at.  Dividing by the
                    # declared cell instead reads any 장평 or grid-rounded
                    # size into the residual, which is the mistake the first
                    # version of this check made -- it put Hangul 0.03 em
                    # out while digits and punctuation agreed to 0.0002.
                    size = char.get("pdf_size") or 0.0
                    declared = type3.get((char.get("pdf_font"),
                                          char.get("char")))
                    if declared is None or size <= 0:
                        continue
                    rows.append({
                        "form": form,
                        "char": char.get("char"),
                        "pdf_font": char.get("pdf_font"),
                        "widths_em": declared,
                        "anchored_em": (char["hancom_hwp"] / HWPUNIT_PER_PT
                                        / size),
                    })
    return rows


def hangul_em(per_face):
    """Per face, the em a Hangul syllable is observed at, if it is observed.

    #288 read 1.0000 for 고딕 and 한양중고딕 off the same arrays.  The rule
    the renderer falls back on for an UNCOVERED syllable is the declared cell,
    so this is the check that the declared cell is what the covered syllables
    of that face were drawn at -- per face, not assumed across them.
    """
    out = {}
    for face, chars in per_face.items():
        seen = Counter()
        for char, seat in chars.items():
            if advance_probe.char_class(char) != "hangul":
                continue
            for em, count in seat["widths"].items():
                seen[em] += count
        if seen:
            modal, hits = seen.most_common(1)[0]
            out[face] = {"em": modal, "observations": sum(seen.values()),
                         "modal_share": hits / sum(seen.values()),
                         "distinct": len(seen)}
    return out


def build_payload(per_face, unattributed, non_hft, verify_rows, forms):
    """The JSON document, header and all."""
    faces = {}
    total_points = 0
    conflicts = 0
    for face in sorted(per_face):
        points = {}
        for char in sorted(per_face[face]):
            seat = per_face[face][char]
            modal, hits = seat["widths"].most_common(1)[0]
            observations = sum(seat["widths"].values())
            entry = {
                "char": char,
                "advance_em": round(modal, 6),
                # Characters Hancom drew from this face at this code point,
                # and the number of Type 3 font objects that declared the
                # width.  A subset per page means many declarations of one
                # number; the two counts answer different questions about
                # how well attested a row is.
                "observations": observations,
                "declarations": seat["declarations"],
                "forms": sorted(seat["forms"]),
                "class": advance_probe.char_class(char),
                "slot": hwp_metric_slot(char),
            }
            if len(seat["widths"]) > 1:
                conflicts += 1
                entry["widths_seen"] = {
                    f"{em:.6f}": count
                    for em, count in sorted(seat["widths"].items())}
                entry["modal_share"] = round(hits / observations, 4)
            points[f"U+{ord(char):04X}"] = entry
            total_points += 1
        faces[face] = {
            "declared_type": "HFT",
            "code_points": len(points),
            "observations": sum(p["observations"] for p in points.values()),
            "forms": sorted({form for p in points.values()
                             for form in p["forms"]}),
            "widths": points,
        }
    residuals = [abs(row["widths_em"] - row["anchored_em"])
                 for row in verify_rows]
    per_class = defaultdict(list)
    for row in verify_rows:
        per_class[advance_probe.char_class(row["char"])].append(
            abs(row["widths_em"] - row["anchored_em"]))
    verification = {
        "what": "the declared /Widths against the pen distance between two "
                "aligned glyph origins, on unstretched lines with no "
                "hh:spacing, per singleton segment",
        "observations": len(residuals),
        "median_abs_em": (round(statistics.median(residuals), 6)
                          if residuals else None),
        "within_0.01_em": sum(1 for r in residuals if r <= 0.01),
        "within_0.02_em": sum(1 for r in residuals if r <= 0.02),
        "per_class": {
            klass: {"n": len(values),
                    "median_abs_em": round(statistics.median(values), 6)}
            for klass, values in sorted(per_class.items())},
        "note": "a singleton's pen distance runs to the NEXT glyph's origin, "
                "so it still carries any gap Hancom opens at a class "
                "boundary; the residual is an upper bound",
    }
    return {
        "declaration": {
            "status": "MEASURED",
            "what": "advance widths, in em, of HWP's own HFT faces",
            "how": "Widths[code] x FontMatrix[0], read out of the Type 3 "
                   "font objects Hancom Office's own PDF export emits for a "
                   "face it cannot embed, grouped by the HFT face the paired "
                   "HWPX runs declare (hh:font@type=\"HFT\")",
            "source": "the ten reference PDFs under "
                      "tests/corpus/forms/render/, exported by Hancom Office",
            "measured_on": MEASURED_ON,
            "contains": "advance widths only",
            "does_not_contain": "no glyph outlines, no CharProcs streams, no "
                                "font program, no font file, no byte of any "
                                "Hancom font",
            "legal": "black-box output of a public document pipeline. "
                     "Nothing here opens, reads or decompiles a Hancom font "
                     "file; the numbers are the export's own declared "
                     "advances, which any reader of those public PDFs can "
                     "read the same way.",
            "forms": sorted(forms),
            "coverage": {
                "faces": len(faces),
                "code_points": total_points,
                "code_points_per_face": {face: seat["code_points"]
                                         for face, seat in faces.items()},
                "observations": sum(seat["observations"]
                                    for seat in faces.values()),
                "code_points_with_more_than_one_width": conflicts,
                "type3_code_points_no_paired_run_used":
                    sum(unattributed.values()),
                "attributed_to_a_non_HFT_face": sum(non_hft.values()),
            },
            "verification": verification,
            "hangul_fallback": "a Hangul syllable this table does not cover "
                               "is advanced by the declared cell; see the "
                               "per-face hangul_em below",
        },
        "hangul_em": {face: seat for face, seat in
                      sorted(hangul_em(per_face).items())},
        "faces": faces,
    }


# -- coverage reporting ---------------------------------------------------

def format_coverage(payload):
    dec = payload["declaration"]["coverage"]
    out = ["", "MEASURED HFT advance table -- coverage", ""]
    out.append(f"{'declared face':<22} {'code points':>12} "
               f"{'observations':>13} {'forms':>6} {'split':>6}")
    out.append("-" * 64)
    for face, seat in sorted(payload["faces"].items()):
        split = sum(1 for p in seat["widths"].values() if "widths_seen" in p)
        out.append(f"{face[:22]:<22} {seat['code_points']:>12} "
                   f"{seat['observations']:>13} {len(seat['forms']):>6} "
                   f"{split:>6}")
    out.append("-" * 64)
    out.append(f"{'all':<22} {dec['code_points']:>12} "
               f"{dec['observations']:>13}")
    out.append("")
    out.append(f"  {dec['faces']} faces x {dec['code_points']} "
               f"(face, code point) pairs")
    out.append(f"  {dec['type3_code_points_no_paired_run_used']} Type 3 code "
               f"points belong to a font no paired run used, so no face can "
               f"be attributed to them")
    out.append(f"  {dec['attributed_to_a_non_HFT_face']} characters were "
               f"attributed to a face the file does not call HFT")
    ver = payload["declaration"]["verification"]
    out.append("")
    out.append(f"  verified against the anchored pen distances: "
               f"{ver['observations']} singleton segments, median abs "
               f"{ver['median_abs_em']} em, {ver['within_0.01_em']} within "
               f"0.01 em, {ver['within_0.02_em']} within 0.02")
    for klass, seat in ver["per_class"].items():
        out.append(f"      {klass:<10} n={seat['n']:<5} median abs "
                   f"{seat['median_abs_em']:.4f} em")
    out.append("")
    out.append("  Hangul, per face (the uncovered-syllable fallback is the "
               "declared cell = 1.0 em)")
    for face, seat in sorted(payload["hangul_em"].items()):
        out.append(f"    {face:<20} {seat['em']:.4f} em over "
                   f"{seat['observations']} observations, "
                   f"{seat['distinct']} distinct")
    return "\n".join(out)


def carrier_coverage(targets, repo_root):
    """Which code points on the two carriers the table covers.

    Asked of the renderer's own gate -- ``_declared_hft_face`` and the loaded
    table -- rather than of the emitted JSON, so what is reported is what the
    line breaker will actually find.
    """
    rows = []
    for hwpx, _pdf in targets:
        addresses = CARRIERS.get(Path(hwpx).stem)
        if not addresses:
            continue
        renderer = own_render.OwnRenderer(hwpx, repo_root=repo_root)
        table = renderer.hft_widths
        for section in range(len(renderer.sections)):
            renderer._current_section = section
            for el in own_render._kids(renderer.sections[section], "p"):
                address = renderer.paragraph_index.get(id(el))
                if address not in addresses:
                    continue
                para = own_render.Paragraph(el, renderer.defs["para_pr"])
                seen = {}
                for char, cid in para.chars:
                    face = renderer._declared_hft_face(cid, char)
                    if face is None:
                        continue
                    em = table.advance_em(face, char) if table else None
                    seat = seen.setdefault((face, char), {
                        "n": 0, "em": em,
                        "covered": em is not None,
                        "half_cell": char in own_render.HALF_WIDTH_CELL_CHARS,
                    })
                    seat["n"] += 1
                rows.append({"form": Path(hwpx).stem, "paragraph": address,
                             "chars": seen})
    return rows


def format_carrier_coverage(rows):
    out = ["", "the carriers: every HFT-declared code point on them, as the "
                "renderer's own gate sees it", ""]
    for row in rows:
        covered = sum(seat["n"] for seat in row["chars"].values()
                      if seat["covered"] or seat["half_cell"])
        total = sum(seat["n"] for seat in row["chars"].values())
        out.append(f"  {row['form']} ¶{row['paragraph']}: {covered} / "
                   f"{total} HFT characters metered by the table (a space "
                   f"keeps the half cell and needs no row)")
        for (face, char), seat in sorted(row["chars"].items(),
                                         key=lambda kv: -kv[1]["n"]):
            if seat["half_cell"]:
                mark, em = "half cell", "  --  "
            elif seat["covered"]:
                mark, em = "measured ", f"{seat['em']:.4f}"
            else:
                mark, em = "NOT COVERED", "  --  "
            out.append(f"      {char!r:<6} {face:<12} n={seat['n']:<3} "
                       f"{mark} {em}")
    return "\n".join(out)


# -- the rules under test -------------------------------------------------

class NoTableMixin:
    """The renderer with the measured HFT table switched off.

    ``current`` and ``cell`` are scored through this, so the control is the
    shipped renderer with one rule disabled rather than a second model of it.
    """

    def _hft_advance_hwp(self, font, chunk, cid, slot, pt, ratio, rel_sz):
        return None


class CellRuleMixin:
    """#283's rule: a SUBSTITUTED face advances a full-width cell by the cell.

    #283 measured that the bundled ``NanumMyeongjo`` answering for 휴먼명조
    advances a Hangul syllable at 0.9502 em where the embedded 휴먼명조 --
    the declared face, on the machine that exported the reference -- advances
    0.9964, which is −60 HWPUNIT per character at 13 pt.  The rule it drew
    from that is that a full-width cell advances by the declared cell
    whatever the stand-in's own ``hmtx`` says.

    It lives in the probe and not in the renderer because it is the other
    slice's proposal; this slice only has to PRICE it, alone and beside the
    measured table, because #288 found the two errors cancel on the carriers.
    """

    def _advance_hwp(self, font, chunk, cid, slot, pt, ratio, rel_sz=100):
        # The measured table first where both rules could speak: it is the
        # one read off Hancom's own output, and the cell rule is a model.
        hft = self._hft_advance_hwp(font, chunk, cid, slot, pt, ratio, rel_sz)
        if hft is not None:
            return hft
        if chunk and all(own_render.is_full_width(ch) for ch in chunk) \
                and self._substituted(cid, slot):
            return len(chunk) * pt * HWPUNIT_PER_PT * ratio / 100.0
        return super()._advance_hwp(font, chunk, cid, slot, pt, ratio, rel_sz)

    def _substituted(self, cid, slot):
        """Is this run drawn by a stand-in rather than the declared face?

        Read out of ``face_resolution``, which ``_font_for`` has already
        filled in for this chunk, so asking never adds a character to the
        per-face counts the sidecar reports.
        """
        bold = bool(self._charpr(cid).get("bold"))
        name = (advance_probe.declared_face(self, cid, slot)
                or "(no hh:fontRef for this slot)")
        record = self.face_resolution.get((name, slot, bold))
        return bool(record) and record["source"] != "installed"


def variant_classes(name):
    """``(renderer_cls, break_recorder_cls)`` for one rule combination."""
    bases = []
    if "table" not in name:
        bases.append(NoTableMixin)
    if "cell" in name:
        bases.append(CellRuleMixin)
    renderer = type(f"Renderer_{name}", tuple(bases) + (own_render.OwnRenderer,),
                    {})
    recorder = type(f"BreakRecorder_{name}",
                    tuple(bases) + (advance_probe.BreakRecordingRenderer,), {})
    return renderer, recorder


@contextlib.contextmanager
def variant(name):
    """Install one rule combination for the length of a measurement.

    Rebinding the module attribute is what lets ``advance_probe``'s own
    scoreboards -- the real breaker, on real column widths -- run under a
    candidate rule without either script growing a rule parameter.
    """
    renderer_cls, recorder_cls = variant_classes(name)
    old_renderer = own_render.OwnRenderer
    old_recorder = advance_probe.BreakRecordingRenderer
    own_render.OwnRenderer = renderer_cls
    advance_probe.BreakRecordingRenderer = recorder_cls
    try:
        yield
    finally:
        own_render.OwnRenderer = old_renderer
        advance_probe.BreakRecordingRenderer = old_recorder


VARIANTS = ("current", "table", "cell", "table+cell")


# -- scoring --------------------------------------------------------------

def score_variant(name, targets, repo_root, dpi=144, keep_text=True):
    """Break test, fit test, per-line widths and the carriers, under ``name``."""
    breaks = {"installed": 0, "installed_match": 0,
              "other": 0, "other_match": 0}
    fit = {"lines": 0, "over": 0}
    reports = []
    carriers = []
    with variant(name):
        for hwpx, pdf in targets:
            for row in advance_probe.break_scoreboard(hwpx, dpi=dpi,
                                                      repo_root=repo_root):
                key = "installed" if row["installed"] else "other"
                breaks[key] += 1
                if row["match"]:
                    breaks[key + "_match"] += 1
            for row in advance_probe.fit_scoreboard(hwpx,
                                                    repo_root=repo_root):
                fit["lines"] += 1
                fit["over"] += 1 if row["now_over"] else 0
            reports.append(advance_probe.probe_document(
                hwpx, pdf, repo_root=repo_root, keep_text=keep_text))
            addresses = CARRIERS.get(Path(hwpx).stem)
            if addresses:
                carriers.extend(
                    pdf_face_probe.reconcile(hwpx, pdf, addresses, repo_root,
                                             keep_text=keep_text))
    widths = advance_probe.line_delta_stats(reports)
    return {"variant": name, "breaks": breaks, "fit": fit, "widths": widths,
            "carriers": [
                {"paragraph": line["paragraph"], "line": line["line"],
                 "horzsize": line["horzsize"],
                 "ours": round(line["ours_span_hwp"], 1),
                 "hancom": round(line["hancom_span_hwp"], 1),
                 "delta": round(line["ours_span_hwp"]
                                - line["hancom_span_hwp"], 1)}
                for line in carriers]}


def format_scores(rows):
    out = ["", "three ways to meter an HFT run, priced against the cache and "
                "the reference", "",
           "exact = per-line width within 2 HWPUNIT of Hancom's own; "
           "¶ match = every cached break reproduced", ""]
    out.append(f"{'variant':<12} {'exact inst':>12} {'exact subst':>13} "
               f"{'inst ¶':>12} {'other ¶':>12} {'over-measured':>14}")
    out.append("-" * 80)
    for row in rows:
        b = row["breaks"]
        inst = row["widths"]["installed_only"] or {}
        subs = row["widths"]["substituted"] or {}
        out.append(
            f"{row['variant']:<12} "
            f"{inst.get('within_tol', 0):>5} / {inst.get('n', 0):<4} "
            f"{subs.get('within_tol', 0):>6} / {subs.get('n', 0):<4} "
            f"{b['installed_match']:>5} / {b['installed']:<4} "
            f"{b['other_match']:>5} / {b['other']:<4} "
            f"{row['fit']['over']:>7} / {row['fit']['lines']:<4}")
    out.append("-" * 80)
    out.append("")
    out.append(f"{'variant':<12} {'inst median':>12} {'med abs':>9} "
               f"{'subst median':>13} {'med abs':>9}")
    for row in rows:
        inst = row["widths"]["installed_only"] or {}
        subs = row["widths"]["substituted"] or {}
        out.append(f"{row['variant']:<12} {inst.get('median', 0):>12.2f} "
                   f"{inst.get('median_abs', 0):>9.2f} "
                   f"{subs.get('median', 0):>13.2f} "
                   f"{subs.get('median_abs', 0):>9.2f}")
    out.append("")
    out.append("the carriers, line by line (ours - hancom, HWPUNIT)")
    out.append("")
    keys = []
    for row in rows:
        for line in row["carriers"]:
            key = (line["paragraph"], line["line"])
            if key not in keys:
                keys.append(key)
    head = "".join(f"{row['variant']:>13}" for row in rows)
    out.append(f"{'paragraph / line':<20}{head}")
    out.append("-" * (20 + 13 * len(rows)))
    for para, index in keys:
        cells = ""
        for row in rows:
            hit = next((line for line in row["carriers"]
                        if (line["paragraph"], line["line"]) == (para, index)),
                       None)
            cells += f"{hit['delta']:>13.1f}" if hit else f"{'--':>13}"
        out.append(f"{'¶' + str(para) + ' line ' + str(index):<20}{cells}")
    return "\n".join(out)


# -- CLI ------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", action="store_true",
                        help="measure the corpus and write the table")
    parser.add_argument("--score", action="store_true",
                        help="price the table, the cell rule and both")
    parser.add_argument("--carriers", action="store_true",
                        help="with --build, print the carriers' coverage")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"where to write the table (default {TABLE_REL})")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--json", type=Path, default=None,
                        help="with --score, write the score rows here")
    parser.add_argument("--no-text", action="store_true",
                        help="keep the document's text out of the output")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    if not args.build and not args.score:
        build_parser().error("give --build, --score, or both")
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    targets = lineseg_vs_pdf.corpus_targets(repo_root)
    keep_text = not args.no_text

    if args.build:
        fonts_by_form, attribution = read_corpus(targets, repo_root,
                                                 keep_text=True)
        per_face, unattributed, non_hft = measure(fonts_by_form, attribution)
        verify_rows = verify_against_anchors(targets, fonts_by_form,
                                             repo_root, keep_text=True)
        payload = build_payload(per_face, unattributed, non_hft, verify_rows,
                                sorted(fonts_by_form))
        print(format_coverage(payload))
        out = args.out or (repo_root / TABLE_REL)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\nwrote {out}")
        # A renderer built before the file existed cached its absence.
        own_render.HftWidthTable._shared.clear()
        if args.carriers:
            print(format_carrier_coverage(carrier_coverage(targets,
                                                           repo_root)))

    if args.score:
        rows = []
        for name in VARIANTS:
            print(f"scoring {name} ...", file=sys.stderr)
            rows.append(score_variant(name, targets, repo_root, dpi=args.dpi,
                                      keep_text=keep_text))
        print(format_scores(rows))
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(rows, indent=2, ensure_ascii=False),
                encoding="utf-8")
            print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
