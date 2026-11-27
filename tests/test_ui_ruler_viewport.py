"""Verify that the canvas cm rulers stay pinned to the canvas viewport while markings follow the page."""

from __future__ import annotations

from test_ui_wp3_canvas import (
    _open_sample,
    _wait_for_cell_geometry,
    browser,
    canvas_bundle,
    expect,
    server,
)

# Base page sheet coordinates measured on commit 1 at scroll (0, 0).
BASE_PAPER_1440 = {"x": 237.5, "y": 54.0, "width": 790.82, "height": 1118.51}
BASE_PAPER_390 = {"x": 26.5, "y": 93.0, "width": 355.36, "height": 501.53}


def _measure_canvas(page) -> dict:
    """Return bounding boxes of the scroller, page sheet, rulers, and 0-cm ticks.

    The 0 point of each ruler is measured from its first tick path (`M 0 0 v 7`
    in `.rl-ruler-h` and `M 0 0 h 7` in `.rl-ruler-v`), which sits at 0 mm on
    the ruler scale.
    """
    return page.evaluate(
        """() => {
            const box = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {
                    x: r.x,
                    y: r.y,
                    width: r.width,
                    height: r.height,
                    top: r.top,
                    left: r.left,
                    right: r.right,
                    bottom: r.bottom,
                };
            };
            const scroller = document.querySelector('[data-testid="canvas-scroll"]');
            const guides = document.querySelector('.rl-page-guides');
            return {
                desk: box('.rl-desk'),
                scroll: box('[data-testid="canvas-scroll"]'),
                scrollTop: scroller ? scroller.scrollTop : 0,
                scrollLeft: scroller ? scroller.scrollLeft : 0,
                paper: box('[data-testid="paper"]'),
                rulerH: box('.rl-ruler-h'),
                rulerV: box('.rl-ruler-v'),
                corner: box('.rl-ruler-corner'),
                rulerH0: box('.rl-ruler-h path'),
                rulerV0: box('.rl-ruler-v path'),
                rulerHBody: box('.rl-ruler-h .rl-ruler-body'),
                rulerVBody: box('.rl-ruler-v .rl-ruler-body'),
                cropmarks: box('.rl-cropmarks'),
                guidesAriaHidden: guides ? guides.getAttribute('aria-hidden') : null,
                guidesPointerEvents: guides ? getComputedStyle(guides).pointerEvents : null,
            };
        }"""
    )


def _scroll_to(page, *, top: int | None = None, left: int | None = None) -> None:
    page.evaluate(
        """({ top, left }) => new Promise((resolve) => {
            const el = document.querySelector('[data-testid="canvas-scroll"]');
            if (typeof top === 'number') el.scrollTop = top;
            if (typeof left === 'number') el.scrollLeft = left;
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })""",
        {"top": top, "left": left},
    )


def test_rulers_stay_pinned_while_markings_follow_scroll_and_zoom_at_1440(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light") as page:
        _open_sample(page, server)
        _wait_for_cell_geometry(page)

        at_rest = _measure_canvas(page)
        assert at_rest["guidesAriaHidden"] == "true"
        assert at_rest["guidesPointerEvents"] == "none"

        # At scroll (0, 0), the page sheet sits within 2 px of base at 1440x900.
        assert abs(at_rest["paper"]["x"] - BASE_PAPER_1440["x"]) <= 2.0, at_rest["paper"]
        assert abs(at_rest["paper"]["y"] - BASE_PAPER_1440["y"]) <= 2.0, at_rest["paper"]
        assert abs(at_rest["paper"]["width"] - BASE_PAPER_1440["width"]) <= 2.0, at_rest["paper"]

        # 0 points start aligned with the page sheet's top-left outer edges.
        assert abs(at_rest["rulerH0"]["left"] - at_rest["paper"]["left"]) <= 1.0
        assert abs(at_rest["rulerV0"]["top"] - at_rest["paper"]["top"]) <= 1.0

        # Scroll down by 300 px and wait a frame.
        _scroll_to(page, top=300)
        scrolled_down = _measure_canvas(page)
        assert abs(scrolled_down["scrollTop"] - 300.0) <= 1.0

        # Horizontal ruler top is unchanged within 1 px; vertical ruler 0 point moved up by 300 px
        # and stays level with the page's top edge.
        assert abs(scrolled_down["rulerH"]["top"] - at_rest["rulerH"]["top"]) <= 1.0
        assert abs(scrolled_down["rulerV"]["top"] - at_rest["rulerV"]["top"]) <= 1.0
        assert abs((scrolled_down["rulerV0"]["top"] - at_rest["rulerV0"]["top"]) - (-300.0)) <= 1.0
        assert abs(scrolled_down["rulerV0"]["top"] - scrolled_down["paper"]["top"]) <= 1.0
        assert abs((scrolled_down["rulerVBody"]["top"] - at_rest["rulerVBody"]["top"]) - (-300.0)) <= 1.0

        # Ruler bands are 20 px thick, meet at the cm corner, span the canvas viewport,
        # and do not cover the page at rest.
        assert abs(at_rest["rulerH"]["height"] - 20.0) <= 1.0
        assert abs(at_rest["rulerV"]["width"] - 20.0) <= 1.0
        assert abs(at_rest["corner"]["width"] - 20.0) <= 1.0
        assert abs(at_rest["corner"]["height"] - 20.0) <= 1.0
        assert abs(at_rest["corner"]["right"] - at_rest["rulerH"]["left"]) <= 1.0
        assert abs(at_rest["corner"]["bottom"] - at_rest["rulerV"]["top"]) <= 1.0
        assert abs(at_rest["rulerH"]["width"] - (at_rest["desk"]["width"] - 20.0)) <= 1.0
        assert abs(at_rest["rulerV"]["height"] - (at_rest["desk"]["height"] - 20.0)) <= 1.0
        assert at_rest["rulerH"]["bottom"] <= at_rest["paper"]["top"] + 0.5
        assert at_rest["rulerV"]["right"] <= at_rest["paper"]["left"] + 0.5

        # Zoom in until the page is wider than the viewport, reset scroll to (0, 0), then scroll right by 200 px.
        _scroll_to(page, top=0, left=0)
        for _ in range(5):
            page.get_by_test_id("zoom-in").click()
        page.wait_for_function(
            """() => {
                const paper = document.querySelector('[data-testid="paper"]');
                const scroller = document.querySelector('[data-testid="canvas-scroll"]');
                return paper && scroller && paper.getBoundingClientRect().width > scroller.clientWidth + 240;
            }"""
        )
        _scroll_to(page, top=0, left=0)
        zoomed_rest = _measure_canvas(page)
        assert abs(zoomed_rest["rulerH0"]["left"] - zoomed_rest["paper"]["left"]) <= 1.0
        assert abs(zoomed_rest["rulerV0"]["top"] - zoomed_rest["paper"]["top"]) <= 1.0

        _scroll_to(page, left=200)
        scrolled_right = _measure_canvas(page)
        assert abs(scrolled_right["scrollLeft"] - 200.0) <= 1.0

        # Vertical ruler left is unchanged within 1 px; horizontal ruler 0 point moved left by 200 px
        # and stays aligned with the page's left outer edge.
        assert abs(scrolled_right["rulerV"]["left"] - zoomed_rest["rulerV"]["left"]) <= 1.0
        assert abs(scrolled_right["rulerH"]["left"] - zoomed_rest["rulerH"]["left"]) <= 1.0
        assert abs((scrolled_right["rulerH0"]["left"] - zoomed_rest["rulerH0"]["left"]) - (-200.0)) <= 1.0
        assert abs(scrolled_right["rulerH0"]["left"] - scrolled_right["paper"]["left"]) <= 1.0
        assert abs((scrolled_right["rulerHBody"]["left"] - zoomed_rest["rulerHBody"]["left"]) - (-200.0)) <= 1.0


def test_rulers_stay_pinned_without_horizontal_overflow_at_390(browser, server):
    with browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="light") as page:
        _open_sample(page, server)
        _wait_for_cell_geometry(page)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=paper]').getBoundingClientRect().width < 390"
        )

        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        at_rest = _measure_canvas(page)
        assert abs(at_rest["paper"]["x"] - BASE_PAPER_390["x"]) <= 2.0, at_rest["paper"]
        assert abs(at_rest["paper"]["y"] - BASE_PAPER_390["y"]) <= 2.0, at_rest["paper"]
        assert abs(at_rest["rulerH0"]["left"] - at_rest["paper"]["left"]) <= 1.0
        assert abs(at_rest["rulerV0"]["top"] - at_rest["paper"]["top"]) <= 1.0

        _scroll_to(page, top=200)
        scrolled = _measure_canvas(page)
        assert abs(scrolled["scrollTop"] - 200.0) <= 1.0
        assert abs(scrolled["rulerH"]["top"] - at_rest["rulerH"]["top"]) <= 1.0
        assert abs((scrolled["rulerV0"]["top"] - at_rest["rulerV0"]["top"]) - (-200.0)) <= 1.0
        assert abs(scrolled["rulerV0"]["top"] - scrolled["paper"]["top"]) <= 1.0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
