"""The mounted v2 canvas adopts decoded pages and retains them on redraw failure."""
from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlsplit

from test_ui_wp3_canvas import _open_sample, browser, canvas_bundle, expect, server  # noqa: F401


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2X8AAAAASUVORK5CYII="
)


def test_rendered_page_shows_source_keeps_image_and_uses_local_caret(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2) as page:
        requests = []
        fail = False
        sequence = 2

        def handle(route):
            url = urlsplit(route.request.url)
            query = parse_qs(url.query)
            operation = url.path.rsplit("/", 1)[-1]
            rev = query["rev"][0]
            requests.append((operation, query))
            if operation == "geometry":
                route.fulfill(json={
                    "rev": rev, "page": 1, "width_pt": 595, "height_pt": 842,
                    "boxes": [
                        {"kind": "cell", "at": "t0/r5/c1", "rect": [50, 100, 140, 40]},
                        {"kind": "line", "at": "t0/r5/c1/p0#L0", "rect": [60, 110, 20, 15],
                         "text": "한글", "xs": [60, 70, 80]},
                    ],
                })
            elif operation == "render":
                if fail:
                    route.fulfill(status=504, json={"error": {"code": "engine_timeout"}})
                else:
                    route.fulfill(body=PNG, headers={
                        "Content-Type": "image/png", "X-Rigorloom-Rev": rev, "X-Rigorloom-Seq": str(sequence),
                        "X-Rigorloom-Page": "1", "X-Rigorloom-Source": "engine",
                        "X-Rigorloom-Width-Pt": "595", "X-Rigorloom-Height-Pt": "842",
                        "X-Rigorloom-Approx": "1", "X-Rigorloom-Page-Count": "1",
                    })
            else:
                route.abort()

        page.route("**/api/doc/**", handle)
        _open_sample(page, server)
        raster = page.get_by_test_id("page-raster")
        expect(raster).to_be_visible()
        expect(page.get_by_test_id("status-page-source")).to_contain_text("대체 글꼴 사용")
        expect(page.get_by_test_id("paper")).to_have_attribute("data-engine-geometry", "true")
        cell = page.locator('[data-cell-key="c:0:5:1"]')
        paper = page.get_by_test_id("paper").bounding_box()
        cell_rect = cell.bounding_box()
        assert abs((cell_rect["x"] - paper["x"]) / paper["width"] - 50 / 595) < 0.002
        # The click is inside the measured first line, in fractions of the cell.
        page.mouse.click(cell_rect["x"] + cell_rect["width"] * 0.13,
                         cell_rect["y"] + cell_rect["height"] * 0.35)
        expect(page.locator(".rl-raster-caret")).to_be_visible()
        expect(page.get_by_test_id("seat-input")).to_be_visible()
        page.keyboard.press("Escape")
        held_url = raster.get_attribute("src")
        assert not any(operation in {"hit", "caret"} for operation, _ in requests)

        fail = True
        for _ in range(5):
            page.get_by_test_id("zoom-in").click()
        expect(page.get_by_test_id("page-render-failed")).to_have_text("다시 그리지 못했습니다")
        expect(raster).to_have_attribute("src", held_url)
        assert [float(query["scale"][0]) for operation, query in requests if operation == "render"][-1] == 3

        fail = False
        sequence = 1
        with page.expect_response(lambda r: "/api/doc/render?" in r.url):
            page.get_by_test_id("zoom-fit-reset").click()
        expect(raster).to_have_attribute("src", held_url)

        sequence = 3
        page.get_by_test_id("zoom-out").click()
        expect(raster).not_to_have_attribute("src", held_url)
