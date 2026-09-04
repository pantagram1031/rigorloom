"""Block by block, in flow order: Hancom's y against ours on render-check-01.

The reference side is read off ``render-check-01.pdf``'s own text layer with
PyMuPDF — every top-level paragraph of section 0 is located by its own text,
in document order, and its first baseline taken.  The candidate side is the
``computed`` flow pass's placement of the same block.  The two are located
independently of each other, exactly the way ``render_check.py`` derives its
regions, so a pagination disagreement shows up as a page number that differs
rather than as a silently cropped band.

    python tests/corpus/render-check/measure_block_drift.py

Read the drift column at the TEXT blocks.  A block whose line carries an
inline object is not comparable cell for cell: our ``y`` is the line box's own
baseline, which for an object line sits at the bottom of the object, while the
reference's is the baseline of the first character INSIDE it.  What such a
block is worth is the drift at the block AFTER it, which is why the walk keeps
the running advance.

Body text only: the reference stream is clipped to the body box, so the
header, the footer and the note area never enter the match.  A block whose
text the PDF does not carry (an empty paragraph, an equation, an anchored
picture) prints without a reference column and breaks the running advance.

Written up in ``docs/research/object-line-box.md``.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "engine", "scripts"))

import own_render  # noqa: E402
from own_render import _kids, _local  # noqa: E402

HWPX = os.path.join(HERE, "render-check-01.hwpx")
PDF = os.path.join(HERE, "render-check-01.pdf")
# Section 0 of the reference is its first seven pages; sections 1 and 2 are
# landscape and two-column and are scored, not walked.
REFERENCE_PAGES = range(0, 7)
# The body box of this document in reference points: 99.2 pt down from the
# top, 85.04 pt up from the bottom of an 841 pt page.  Clipping to it keeps
# the header, the footer and the footnote/endnote area out of the match.
BODY_TOP_PT = 95.0
BODY_BOTTOM_PT = 762.0


def paragraph_text(el):
    return "".join("".join(node.itertext())
                   for node in el.iter() if _local(node.tag) == "t")


def reference_stream(doc):
    """``(text, [(page, baseline_y), ...])`` over the body box, in order."""
    chars, meta = [], []
    for number in REFERENCE_PAGES:
        for block in doc[number].get_text("rawdict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    for char in span["chars"]:
                        y = char["origin"][1]
                        if char["c"].isspace():
                            continue
                        if not BODY_TOP_PT <= y <= BODY_BOTTOM_PT:
                            continue
                        chars.append(char["c"])
                        meta.append((number, y))
    return "".join(chars), meta


def main() -> int:
    try:
        import fitz
    except ImportError:
        print("PyMuPDF is not installed; the reference PDF cannot be read")
        return 2
    if not os.path.exists(PDF):
        print("missing reference render: %s" % PDF)
        return 2

    renderer = own_render.OwnRenderer(HWPX, block_layout="computed")
    geometry = renderer.page_geometry()
    draw = renderer._scratch_draw()
    column, _gap, _count = renderer.column_geometry(geometry)
    blocks = renderer._flow_blocks(draw, column)
    placements, pages, _counters = renderer.flow(draw)
    first = {}
    for record in placements:
        first.setdefault(record["block"], record)

    doc = fitz.open(PDF)
    page_pt = doc[0].rect.height
    stream, meta = reference_stream(doc)

    print("section 0: %d pages ours, %d in the reference; %d pages in all"
          % (len(pages), len(REFERENCE_PAGES), len(doc)))
    print()
    print("%-4s %-9s %-9s %8s %8s %8s  %s"
          % ("blk", "ref p,y", "our p,y", "drift", "refAdv", "ourAdv",
             "our block"))
    cursor = 0
    previous = None
    for position, el in enumerate(_kids(renderer.sections[0], "p")):
        block = blocks[position]
        record = first.get(renderer.paragraph_index.get(id(el)))
        text = "".join(paragraph_text(el).split())
        key = text[:24]
        hit = stream.find(key, cursor) if key else -1
        if hit < 0 or record is None:
            print("%-4d %s" % (position,
                               "no text in the reference layer"
                               if hit < 0 else "not placed"))
            previous = None
            continue
        cursor = hit + len(key)
        ref_page, ref_y = meta[hit]
        baseline = block["rows"][0]["extent"] if block["rows"] else 0
        our_y = (geometry["body_top"] + record["top"] + baseline) / 100.0
        ref_abs = ref_page * page_pt + ref_y
        our_abs = record["page"] * page_pt + our_y
        advances = ("%8.2f %8.2f" % (ref_abs - previous[0],
                                     our_abs - previous[1])
                    if previous else "%8s %8s" % ("-", "-"))
        print("%-4d %d,%7.2f %d,%7.2f %8.2f %s  h=%-7d rows=%d prev=%d next=%d"
              % (position, ref_page, ref_y, record["page"], our_y,
                 our_abs - ref_abs, advances, block["height"],
                 len(block["rows"]), block["margin_prev"],
                 block["margin_next"]))
        previous = (ref_abs, our_abs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
