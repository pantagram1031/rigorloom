"""Exercise the mounted canvas in editor v2 with a real sample and runtime."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

import pytest

from _browser_gate import no_browser
from _editor_v2 import editor_v2_url
from _v1_identity import launch_browser, start_bridge
from test_ui_playwright import _assert_principles
from test_ui_playwright_v1 import _confirmation_token, _rpc_post

DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
COOP_CELL = '[data-cell-key="c:0:5:1"]'

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError as exc:
    no_browser(f"playwright Python package unavailable: {exc}", module_level=True)


@pytest.fixture(scope="module")
def canvas_bundle(tmp_path_factory):
    vite = DESKTOP / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.is_file():
        no_browser("desktop dependencies unavailable (run npm ci in desktop)")
    dist = tmp_path_factory.mktemp("wp3-web")
    build = subprocess.run(
        ["node", str(vite), "build", "--config", "vite.web.config.ts", "--outDir", str(dist)],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return dist


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            browser = launch_browser(pw)
        except Exception as exc:
            no_browser(f"headless Chromium unavailable: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def server(browser, canvas_bundle, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    bridge, thread = start_bridge(tmp_path, canvas_bundle)
    try:
        yield bridge
    finally:
        bridge.shutdown_bridge()
        thread.join(timeout=5)


def _open_sample(page, server):
    page.goto(editor_v2_url(server.url))
    page.get_by_test_id("start-sample-0").click()
    expect(page.get_by_test_id("paper").first).to_be_visible(timeout=20_000)
    expect(page.locator("[data-slot-failed]")).to_have_count(0)


def _rpc_payload(request):
    if request.url.endswith("/rpc") and request.post_data:
        return json.loads(request.post_data)
    return {}


def _wait_for_cell_geometry(page):
    if os.environ.get("RIGORLOOM_HWP_ENGINE"):
        expect(page.get_by_test_id("paper")).to_have_attribute(
            "data-engine-geometry", "true", timeout=20_000,
        )


@contextmanager
def _expect_cell_redraw(page):
    if not os.environ.get("RIGORLOOM_HWP_ENGINE"):
        yield
        return

    raster = page.get_by_test_id("page-raster")
    previous_src = raster.get_attribute("src")
    with page.expect_response(
        lambda response: "/api/doc/render?" in response.url and response.ok
        and "x-rigorloom-preview-id" in response.headers,
        timeout=20_000,
    ):
        yield
    expect(raster).not_to_have_attribute("src", previous_src, timeout=20_000)
    expect(page.get_by_test_id("page-render-failed")).to_have_count(0)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1440, 900), (390, 844)])
def test_canvas_and_panes_mount_from_start(browser, server, theme, size):
    width, height = size
    with browser.new_page(viewport={"width": width, "height": height}, color_scheme=theme) as page:
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        _open_sample(page, server)
        assert page.evaluate("document.documentElement.scrollWidth") == width
        expect(page.get_by_test_id("strip-export")).to_have_count(0)
        _assert_principles(page, f"{width} {theme}")

        if width < 600:
            page.wait_for_function(
                "width => document.querySelector('[data-testid=paper]').getBoundingClientRect().width < width",
                arg=width,
            )
            page.get_by_test_id("app-menu").click()

        for pane in ("blanks", "outline", "find"):
            page.get_by_test_id(f"pane-tab-{pane}").click()
            expect(page.get_by_test_id(f"pane-{pane}")).to_be_visible()
        expect(page.get_by_test_id("find-query-input")).to_be_visible()
        assert not errors, errors


def test_blanks_editing_and_keyboard_decisions(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        expect(page.get_by_test_id("status-font-sub")).to_contain_text("글꼴 대체")
        expect(page.get_by_test_id("blanks-counter")).to_contain_text("빈칸")
        agency = page.get_by_test_id("blanks-agency-toggle")
        expect(agency).to_have_attribute("aria-expanded", "false")
        agency.click()
        expect(page.get_by_test_id("blanks-agency-list")).to_be_visible()
        agency.click()

        coop = page.get_by_test_id("blank-seat-t0/r5/c1")
        expect(coop).to_contain_text("협조자 1")
        expect(coop).to_contain_text("표 1 6행 2열")
        coop.hover()
        expect(page.get_by_test_id("status-seat")).to_contain_text("협조자 1")
        assert "rl-cell--hovered" in page.locator(COOP_CELL).get_attribute("class")
        coop.click()

        seat = page.get_by_test_id("seat-input")
        seat.fill("기록정책담당관")
        seat.press("Enter")
        expect(seat).to_have_count(0)
        cell = page.locator(COOP_CELL)
        expect(cell).to_contain_text("기록정책담당관")
        expect(cell.locator('[data-mark-state="accepted"]')).to_have_count(1)

        page.keyboard.press("n")
        expect(cell.locator('[data-mark-state="rejected"]')).to_have_count(1)
        page.keyboard.press("Control+z")
        expect(cell.locator('[data-mark-state="accepted"]')).to_have_count(1)
        for view in ("clean", "base", "marks"):
            page.keyboard.press("v")
            expect(page.get_by_test_id(f"view-seg-{view}")).to_have_attribute("aria-selected", "true")

        page.locator('[data-cell-key="c:0:0:0"]').click()
        expect(seat).to_be_visible()
        expect(page.get_by_test_id("status-canvas-notice")).to_have_count(0)
        seat.press("Escape")
        _assert_principles(page, "marks and toolbar")


def test_find_replace_upserts_the_cell_and_keeps_its_original_baseline(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        proposals = []

        def record(request):
            payload = _rpc_payload(request)
            if payload.get("method") == "plan/propose":
                proposals.append(payload["params"]["ops"])

        page.on("request", record)
        _open_sample(page, server)
        page.locator(COOP_CELL).click()
        seat = page.get_by_test_id("seat-input")
        seat.fill("Delta alpha alpha")
        seat.press("Enter")

        page.keyboard.press("Control+f")
        query = page.get_by_test_id("find-query-input")
        expect(query).to_be_focused()
        query.fill("ALPHA")
        expect(page.get_by_test_id("find-match-0")).to_contain_text("Delta alpha alpha")
        expect(page.locator(".rl-find-hit").first).to_be_visible()
        page.keyboard.press("Control+h")
        replacement = page.get_by_test_id("find-replace-input")
        expect(replacement).to_be_focused()
        replacement.fill("beta")
        page.get_by_test_id("replace-one-btn").click()
        expect(page.get_by_test_id("find-match-0")).to_contain_text("Delta beta alpha")
        page.get_by_test_id("replace-all-btn").click()
        expect(page.get_by_test_id("find-empty")).to_be_visible()
        expect(page.locator(COOP_CELL)).to_contain_text("Delta beta beta")

        page.locator(COOP_CELL).click()
        expect(seat).to_have_value("Delta beta beta")
        seat.fill("Final")
        seat.press("Enter")
        expect(page.locator(COOP_CELL)).to_contain_text("Final")

        query.fill("없는문구xyz")
        expect(page.get_by_test_id("find-empty")).to_contain_text("검색 결과가 없습니다")
        assert len(proposals) == 4
        assert all(len(ops) == 1 and ops[0]["kind"] == "fill_cell" for ops in proposals)
        assert len({ops[0]["opId"] for ops in proposals}) == 1
        assert [ops[0]["text"] for ops in proposals] == [
            "Delta alpha alpha", "Delta beta alpha", "Delta beta beta", "Final",
        ]


def test_ime_typing_writes_only_on_commit(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        requests = []

        def record(request):
            method = _rpc_payload(request).get("method")
            if method:
                requests.append(method)

        page.on("request", record)
        with page.expect_response(
            lambda response: _rpc_payload(response.request).get("method") == "event/subscribe"
        ):
            _open_sample(page, server)
        _wait_for_cell_geometry(page)
        page.locator(COOP_CELL).click()
        seat = page.get_by_test_id("seat-input")
        baseline = len(requests)
        seat.press_sequentially("가나다라마바사", delay=15)
        assert requests[baseline:] == []
        seat.dispatch_event("compositionstart", {"data": "ㅎ"})
        seat.dispatch_event("keydown", {
            "key": "Enter", "code": "Enter", "keyCode": 229, "isComposing": True,
        })
        expect(seat).to_be_visible()
        assert requests[baseline:] == []
        seat.dispatch_event("compositionend", {"data": "가나다라마바사"})
        with _expect_cell_redraw(page):
            seat.blur()
        expect(seat).to_have_count(0)
        expect(page.locator(COOP_CELL)).to_contain_text("가나다라마바사")
        assert requests[baseline:].count("plan/propose") == 1

        page.locator(COOP_CELL).click()
        seat.press("Tab")
        expect(page.get_by_test_id("seat-input")).to_be_focused()
        expect(page.locator('[data-cell-key="c:0:5:2"].rl-cell--editing')).to_have_count(1)


def test_narrow_cell_editor_reopens_with_queued_value(browser, server):
    with browser.new_page(viewport={"width": 390, "height": 844}) as page:
        _open_sample(page, server)
        _wait_for_cell_geometry(page)
        page.get_by_test_id("app-menu").click()
        page.get_by_test_id("pane-tab-blanks").click()
        page.get_by_test_id("blank-seat-t0/r5/c1").click()
        bar = page.get_by_test_id("narrow-seat-bar")
        expect(bar).to_be_visible()
        expect(page.get_by_test_id("narrow-drawer")).to_have_count(0)
        seat = bar.get_by_test_id("seat-input")
        seat.fill("담당관")
        with _expect_cell_redraw(page):
            seat.press("Enter")
        expect(page.locator(COOP_CELL)).to_contain_text("담당관")
        page.locator(COOP_CELL).click()
        expect(seat).to_have_value("담당관")


def test_document_strip_exports_the_applied_candidate(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        tab = page.locator('[data-tab-id^="doc:"][aria-selected="true"]')
        session_id = tab.get_attribute("data-tab-id").split(":", 1)[1]
        export = page.get_by_test_id("strip-export")
        expect(export).to_have_count(0)

        def rpc(method, params):
            result = _rpc_post(server.url, server.token, method, params)
            assert result["ok"], result
            return result["result"]

        plan = rpc("plan/propose", {
            "sessionId": session_id,
            "backend": "preedit",
            "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "담당관"}],
        })["plan"]
        approval_id = rpc("approval/request", {"planId": plan["planId"]})["approval"]["approvalId"]
        rpc("approval/resolve", {
            "approvalId": approval_id,
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "decision": "approved",
            "approver": "playwright-verifier",
            "confirmationToken": _confirmation_token(server.url, server.token, session_id, plan),
        })
        candidate = rpc("plan/apply", {
            "planId": plan["planId"],
            "approvalId": approval_id,
        })["candidate"]

        page.reload()
        expect(export).to_be_visible(timeout=20_000)
        with page.expect_download() as info:
            export.click()
        download = info.value
        assert download.suggested_filename.endswith("-candidate.hwpx")
        assert sha256(download.path().read_bytes()).hexdigest() == candidate["candidate"]["sha256"]
