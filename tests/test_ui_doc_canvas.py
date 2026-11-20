"""The mounted v2 canvas adopts decoded pages and retains them on redraw failure."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from test_ui_wp3_canvas import _open_sample, browser, canvas_bundle, expect, server  # noqa: F401
from _editor_v2 import editor_v2_url


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
            if operation == "fonts":
                route.fallback()
                return
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


def test_superseded_render_retries_once_without_a_redraw_notice(browser, server):
    with browser.new_page() as page:
        calls = []

        def render(route):
            query = parse_qs(urlsplit(route.request.url).query)
            calls.append(query)
            if len(calls) == 1:
                route.fulfill(status=409, json={"error": {"code": "render_superseded"}})
                return
            route.fulfill(body=PNG, headers={
                "Content-Type": "image/png", "X-Rigorloom-Rev": query["rev"][0], "X-Rigorloom-Seq": "2",
                "X-Rigorloom-Page": "1", "X-Rigorloom-Source": "pdf",
                "X-Rigorloom-Width-Pt": "595", "X-Rigorloom-Height-Pt": "842",
            })

        page.route("**/api/doc/render?**", render)
        _open_sample(page, server)
        expect(page.get_by_test_id("page-raster")).to_be_visible()
        assert calls[:2] == [calls[0], calls[0]]
        assert calls.count(calls[0]) == 2
        expect(page.get_by_test_id("page-render-failed")).to_have_count(0)


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
def test_engine_body_line_edit_queues_the_document_run(browser, server):
    source = Path(__file__).resolve().parent / "corpus" / "render-check" / "render-check-01.hwpx"
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        page.goto(editor_v2_url(server.url))
        with page.expect_file_chooser() as opened:
            page.get_by_test_id("start-open-file").click()
        opened.value.set_files(source)
        raster = page.get_by_test_id("page-raster")
        expect(raster).to_be_visible(timeout=20_000)
        url = raster.get_attribute("src")
        paper = page.get_by_test_id("paper")
        expect(paper).to_have_attribute("data-engine-geometry", "true")
        bounds = paper.bounding_box()
        scale = bounds["width"] / 595.28
        page.mouse.click(bounds["x"] + 85.7 * scale, bounds["y"] + 127 * scale)
        entry = page.get_by_test_id("seat-input")
        expect(entry).to_have_value("[F01] 정렬 — 왼쪽 (align LEFT)")
        assert entry.evaluate("(input) => input.selectionStart") == 0
        with page.expect_request(lambda req: req.url.endswith("/api/doc/preview")) as request:
            entry.fill("검토 제목")
        op, = request.value.post_data_json["ops"]
        assert op["at"] == "p3" and op["run"] == 0
        expect(raster).not_to_have_attribute("src", url, timeout=12_000)
        expect(entry).to_have_count(0)
        expect(page.get_by_test_id("page-render-failed")).to_have_count(0)


def test_engine_cell_stays_over_held_raster_until_its_preview_draws(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        held_renders = []
        previews = []
        queued = []

        def queue_request(request):
            if request.url.endswith("/rpc") and request.post_data:
                payload = request.post_data_json
                if payload.get("method") == "plan/propose":
                    queued.append(payload["params"])

        def respond_png(route, rev, seq, preview_id=None):
            headers = {
                "Content-Type": "image/png", "X-Rigorloom-Rev": rev, "X-Rigorloom-Seq": str(seq),
                "X-Rigorloom-Page": "1", "X-Rigorloom-Source": "engine",
                "X-Rigorloom-Width-Pt": "595", "X-Rigorloom-Height-Pt": "842",
            }
            if preview_id:
                headers.update({"X-Rigorloom-Preview-Id": preview_id, "X-Rigorloom-Preview-Rev": preview_id[:12]})
            route.fulfill(body=PNG, headers=headers)

        def handle(route):
            url = urlsplit(route.request.url)
            query = parse_qs(url.query)
            operation = url.path.rsplit("/", 1)[-1]
            if operation == "fonts":
                route.fallback()
                return
            if operation == "preview":
                params = route.request.post_data_json
                previews.append(params)
                preview_id = str(len(previews)) * 32
                route.fulfill(json={
                    "rev": params["rev"], "seq": len(previews) * 10, "previewId": preview_id,
                    "previewRev": preview_id[:12], "count": 1, "changedPages": [1],
                    "changed": [{"i": 0, "page": 1, "rect": [60, 110, 20, 35]}],
                })
                return
            rev = query["rev"][0]
            preview_id = query.get("previewId", [None])[0]
            if operation == "geometry":
                data = {"rev": rev, "page": 1, "width_pt": 595, "height_pt": 842, "boxes": [
                    {"kind": "cell", "at": "t0/r5/c1", "rect": [50, 100, 140, 70]},
                    {"kind": "line", "at": "t0/r5/c1/p0#L0", "rect": [60, 110, 20, 35],
                     "text": "", "vertical": True, "ys": [110]},
                ]}
                if preview_id:
                    data.update(previewId=preview_id, previewRev=preview_id[:12])
                route.fulfill(json=data)
            elif operation == "render" and preview_id:
                held_renders.append((route, rev, preview_id))
                if len(held_renders) > 2:
                    respond_png(route, rev, 25, preview_id)
            elif operation == "render":
                respond_png(route, rev, 1)
            else:
                route.abort()

        page.route("**/api/doc/**", handle)
        page.on("request", queue_request)
        _open_sample(page, server)
        raster = page.get_by_test_id("page-raster")
        expect(raster).to_be_visible()
        held_url = raster.get_attribute("src")
        cell = page.locator('[data-cell-key="c:0:5:1"]')
        cell.click()
        entry = page.get_by_test_id("seat-input")
        expect(entry).to_have_css("writing-mode", "vertical-rl")
        paper = page.get_by_test_id("paper").bounding_box()
        edit_rect = entry.bounding_box()
        assert abs((edit_rect["x"] - paper["x"]) / paper["width"] - 60 / 595) < 0.002
        entry.fill("검토")
        expect(entry).to_have_value("검토")
        assert not previews
        expect(page.get_by_test_id("engine-changed-rect")).to_be_visible()
        assert previews[0]["ops"] == [{"at": "t0/r5/c1", "text": "검토"}]
        assert queued[0]["ops"][0]["kind"] == "fill_cell"
        expect(raster).to_have_attribute("src", held_url)
        expect(entry).to_have_value("검토")

        # A newer keystroke is still in the input when the first PNG swaps.
        entry.fill("검토팀")
        respond_png(*held_renders[0][:2], 12, held_renders[0][2])
        expect(raster).not_to_have_attribute("src", held_url)
        expect(entry).to_have_value("검토팀")
        first_preview_url = raster.get_attribute("src")
        expect(page.get_by_test_id("engine-changed-rect")).to_be_visible()
        assert previews[1]["ops"] == [{"at": "t0/r5/c1", "text": "검토팀"}]
        assert len(queued[1]["ops"]) == 1

        failed_route, _, _ = held_renders[1]
        failed_route.fulfill(status=504, json={"error": {"code": "engine_timeout"}})
        expect(page.get_by_test_id("page-render-failed")).to_have_text("다시 그리지 못했습니다")
        expect(raster).to_have_attribute("src", first_preview_url)
        expect(entry).to_have_value("검토팀")

        # Releasing focus keeps the queued text on paper until a redraw succeeds.
        entry.press("Enter")
        expect(page.get_by_test_id("engine-edit-pending")).to_have_text("검토팀")
        with page.expect_request(lambda req: "/api/doc/render?" in req.url and "previewId=" in req.url):
            page.get_by_test_id("zoom-in").click()
        expect(raster).not_to_have_attribute("src", first_preview_url)
        expect(page.get_by_test_id("engine-edit-pending")).to_have_count(0)
        expect(page.get_by_test_id("engine-changed-rect")).to_have_count(0)
        expect(page.get_by_test_id("page-render-failed")).to_have_count(0)
