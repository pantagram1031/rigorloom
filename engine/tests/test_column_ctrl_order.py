"""Pin the one thing that makes ``hp:colPr`` take effect in Hancom.

The OWPML schema (``DevDoc/OWPML SCHEMA/ParaList XML schema.xml``) lets the
section-head paragraph carry its ``hp:ctrl`` children in any order, and
``colCount="2"`` survives a COM round-trip whatever the order is.  Hancom
still only *lays out* two columns when the ``hp:colPr`` control is not
preceded by a header or footer control in that paragraph.  Measured with two
probe documents (Hwp 2024 13.0.0.2986; one section per case, PDF export read
back for the x-extent of the text), recorded in
``docs/research/render-check-01.md`` note 4:

    secPr, header, footer, colPr   -> one column   (P1, P2, P3, P6, P7)
    secPr, header, colPr, footer   -> one column   (Q1)
    secPr, footer, colPr           -> one column   (Q3)
    secPr, colPr                   -> two columns  (Q2)
    secPr, colPr, header, footer   -> two columns  (P4, Q4)
    secPr, header, footer;         -> two columns  (P5)
      colPr in the next paragraph

Neither ``type`` (NEWSPAPER / BALANCED_NEWSPAPER), ``layout``, ``sameSz``,
``sameGap`` nor explicit ``hp:colSz`` children moved a single case across
that line.

``render-check-01`` used to emit the first order, which is why its `F49`
다단 block declared two columns and Hancom rendered it full width.  That was
the *document* being malformed, not ``own_render``, so the fix is in the
writer — and this module keeps it fixed, for the builder and for the bytes
that ship.
"""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
CORPUS = os.path.join(ROOT, "tests", "corpus", "render-check")
DOCUMENT = os.path.join(CORPUS, "render-check-01.hwpx")
REFERENCE = os.path.join(CORPUS, "render-check-01.pdf")

sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, CORPUS)


def _builder():
    try:
        import build_render_check
    except Exception as exc:                       # pragma: no cover
        pytest.skip("build_render_check is not importable: %s" % exc)
    return build_render_check


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _section_head_order(xml):
    """The control tags of the section-head paragraph, in document order.

    Parsed, not scanned: a header's ``hp:subList`` carries whole paragraphs of
    its own, so a text scan would run past the head paragraph's real end.
    Only ``hp:secPr``, ``hp:colPr``, ``hp:header`` and ``hp:footer`` reached
    through the head paragraph's own runs are reported, and a control's own
    subtree is not descended into.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    head = next((e for e in root.iter() if _local(e.tag) == "p"), None)
    assert head is not None, "no hp:p in the section"
    order = []

    def walk(node, depth=0):
        for child in node:
            name = _local(child.tag)
            if name in ("secPr", "colPr", "header", "footer"):
                order.append(name)
                continue                      # never descend into a control
            if name in ("run", "ctrl", "switch", "case", "default"):
                walk(child, depth + 1)
    walk(head)
    return order


def _assert_colpr_is_not_shadowed(order, where):
    assert "colPr" in order, "%s declares no hp:colPr" % where
    for name in order[:order.index("colPr")]:
        assert name not in ("header", "footer"), (
            "%s puts %r before hp:colPr; Hancom ignores a column definition "
            "a header or footer control precedes (order=%r)"
            % (where, name, order))


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------
def _sec_pr_payload():
    B = _builder()
    return B, B.sec_pr(width=B.A4_W, height=B.A4_H, landscape="WIDELY",
                       margin=B.MARGIN, col_count=2,
                       furniture=B.header_ctrl("h") + B.footer_ctrl("f"))


def _as_section(B, payload):
    return ('<hs:sec' + B.NS + '><hp:p id="1" paraPrIDRef="0" styleIDRef="0"'
            ' pageBreak="0" columnBreak="0" merged="0">'
            '<hp:run charPrIDRef="0">' + payload + '</hp:run></hp:p></hs:sec>')


def test_sec_pr_emits_colpr_before_the_furniture():
    B, payload = _sec_pr_payload()
    order = _section_head_order(_as_section(B, payload))
    assert order[:2] == ["secPr", "colPr"], order
    _assert_colpr_is_not_shadowed(order, "sec_pr()")


def test_sec_pr_still_carries_the_furniture_and_the_count():
    B, payload = _sec_pr_payload()
    assert _section_head_order(_as_section(B, payload)) == [
        "secPr", "colPr", "header", "footer"]
    assert 'colCount="2"' in payload
    assert "<hp:header " in payload and "<hp:footer " in payload
    # The column definition is a sibling of hp:secPr, not a child of it.
    assert payload.index("</hp:secPr>") < payload.index("<hp:colPr")


# ---------------------------------------------------------------------------
# The bytes that ship
# ---------------------------------------------------------------------------
def test_shipped_document_puts_colpr_first_in_every_section():
    if not os.path.isfile(DOCUMENT):
        pytest.skip("corpus fixture missing: %s" % DOCUMENT)
    import zipfile
    with zipfile.ZipFile(DOCUMENT) as package:
        names = sorted(n for n in package.namelist()
                       if re.match(r"Contents/section\d+\.xml$", n))
        assert names, "no section parts in %s" % DOCUMENT
        for name in names:
            xml = package.read(name).decode("utf-8")
            _assert_colpr_is_not_shadowed(_section_head_order(xml), name)


def test_reference_render_of_F49_is_two_columns():
    """Hancom's own export is the evidence, not our reading of the rule."""
    if not os.path.isfile(REFERENCE):
        pytest.skip("corpus fixture missing: %s" % REFERENCE)
    fitz = pytest.importorskip("fitz", reason="PyMuPDF is not installed")
    right = width = None
    with fitz.open(REFERENCE) as document:
        for index in range(document.page_count):
            page = document[index]
            if "[F49]" not in page.get_text():
                continue
            width, height = page.rect.width, page.rect.height
            body = [b for b in page.get_text("blocks")
                    if height * 0.09 < b[1] < height * 0.88]
            assert body, "no body text on the [F49] page"
            right = max(b[2] for b in body)
            break
    assert right is not None, "no [F49] marker in the reference PDF"
    # Body box is 42520 HWPUNIT (425.2 pt) wide from an 85 pt left margin; one
    # column reaches ~510 pt, two columns stop near the middle of the page.
    assert right < width * 0.6, (
        "the reference renders F49 full width (right edge %.0f pt of %.0f): "
        "the shipped document's hp:colPr is not being honoured"
        % (right, width))
