"""layout_qa.check_line_spacing_uniformity 오탐 방지 회귀 테스트.

세 신규 면제(그림 블록 겹침, footer로 이어지는 갭, 표 인접 여백)를 합성
PDF(fitz로 직접 생성)로 검증한다 — 실제 픽스처 불필요, 완전 오프라인·결정론적.
`python -m pytest tests/ -q`.
"""
import os
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fitz  # noqa: E402
import layout_qa as lq  # noqa: E402

PAGE_W, PAGE_H = 595, 842


def _new_page():
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return doc, page


def test_gap_spanning_image_block_not_flagged():
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
        pix.set_rect(pix.irect, (200, 200, 200))
        page.insert_image(fitz.Rect(72, 150, 300, 260), pixmap=pix)
        page.insert_text((72, 280), "line after image", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert violations == []
    finally:
        doc.close()


def test_gap_to_footer_line_not_flagged():
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        # caption ends well above the bottom-10% margin (page_height*0.9 ~= 757.8),
        # so the pre-existing _in_bottom_margin exemption does NOT apply here —
        # only the new footer-specific exemption should suppress this gap.
        page.insert_text((72, 142), "caption line ends here", fontsize=9)
        assert 142 < PAGE_H * 0.9
        page.insert_text((280, PAGE_H - 20), "- 1 -", fontsize=9)

        violations = lq.check_line_spacing_uniformity(page)
        assert violations == []
    finally:
        doc.close()


def test_genuine_hole_still_flagged():
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        # big gap to a plain body line: no image, no footer, not in bottom margin,
        # not a bigger heading-sized line -- this must still be caught.
        page.insert_text((72, 300), "line after genuine hole", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert len(violations) == 1
        assert violations[0]["gap_pt"] > 100
    finally:
        doc.close()


def _draw_table(page, x0, y0, x1, y1):
    """2x2 grid table find_tables() can detect, matching check_tables()'s
    own fixture pattern (drawn rect + one horizontal + one vertical line)."""
    page.draw_rect(fitz.Rect(x0, y0, x1, y1))
    my = (y0 + y1) / 2
    mx = (x0 + x1) / 2
    page.draw_line((x0, my), (x1, my))
    page.draw_line((mx, y0), (mx, y1))
    page.insert_text((x0 + 5, y0 + 15), "H1", fontsize=9)
    page.insert_text((mx + 5, y0 + 15), "H2", fontsize=9)
    page.insert_text((x0 + 5, my + 15), "a", fontsize=9)
    page.insert_text((mx + 5, my + 15), "b", fontsize=9)


def test_gap_adjacent_to_image_not_flagged():
    """(a) gap adjacent to an image block -> not flagged (dedicated case for
    the operator blank-line-before-object rule, distinct from the pre-existing
    image-span-overlap test above which uses a gap that fully spans the image)."""
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        # one blank line worth of gap (~20pt), then an image directly below.
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
        pix.set_rect(pix.irect, (200, 200, 200))
        page.insert_image(fitz.Rect(72, 150, 300, 260), pixmap=pix)
        page.insert_text((72, 280), "line after image", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert violations == []
    finally:
        doc.close()


def test_gap_in_pure_prose_same_size_still_flagged():
    """(b) same-size gap (~130pt) in pure prose, no table/image/footer nearby
    -> must still be flagged exactly as before (regression pin for the new
    table-adjacency exemption not over-firing)."""
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        page.insert_text((72, 230), "line after prose gap", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert len(violations) == 1
        assert violations[0]["gap_pt"] > 80
    finally:
        doc.close()


def test_gap_adjacent_to_table_not_flagged():
    """(c) gap adjacent to a drawn-table-like block (same find_tables()
    detection signal check_tables() itself uses: rect + grid lines) -> the
    blank-before-table gap must not be flagged."""
    doc, page = _new_page()
    try:
        page.insert_text((72, 100), "line one", fontsize=10)
        page.insert_text((72, 114), "line two", fontsize=10)
        page.insert_text((72, 128), "line three", fontsize=10)
        # ~1 blank line of whitespace (median line height ~14pt) before table top.
        _draw_table(page, 72, 150, 300, 210)
        page.insert_text((72, 230), "line after table", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert violations == []
    finally:
        doc.close()


def test_gap_after_table_caption_not_flagged():
    """(c) caption-after-table spacing: gap between the table's bottom and the
    next body line (simulating a caption immediately under the table, then a
    blank-line gap before body resumes) must not be flagged."""
    doc, page = _new_page()
    try:
        page.insert_text((72, 60), "line before table", fontsize=10)
        _draw_table(page, 72, 90, 300, 150)
        page.insert_text((72, 165), "caption: Table 1. synthetic", fontsize=9)
        # ~20pt operator blank-line gap after the caption before body resumes.
        page.insert_text((72, 200), "body resumes after caption gap", fontsize=10)

        violations = lq.check_line_spacing_uniformity(page)
        assert violations == []
    finally:
        doc.close()
