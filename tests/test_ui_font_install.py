"""Opt-in editor font guidance on the existing document-core fixture."""
import json
import os
from pathlib import Path

import pytest

from _editor_v2 import editor_v2_url
from test_ui_wp3_canvas import browser, canvas_bundle, expect, server  # noqa: F401

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rt_doc_contract" / "basic.hwpx"
REPO = FIXTURE.parents[3]


def open_font_fixture(page, server):
    page.goto(editor_v2_url(server.url))
    with page.expect_file_chooser() as opened:
        page.get_by_test_id("start-open-file").click()
    opened.value.set_files(FIXTURE)
    expect(page.get_by_test_id("page-raster")).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("paper")).to_have_attribute("data-engine-geometry", "true")


def test_no_engine_fallback_shows_builtin_source_and_font_guidance(browser, server, monkeypatch):
    import rt_font_install
    import rt_ui_doc

    monkeypatch.setattr(rt_ui_doc.rt_doc, "engine_status", lambda: {"available": False})
    monkeypatch.setattr(rt_font_install, "installed_states", lambda names: dict.fromkeys(names, "missing"))

    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        page.goto(editor_v2_url(server.url))
        with page.expect_file_chooser() as opened:
            page.get_by_test_id("start-open-file").click()
        opened.value.set_files(FIXTURE)
        expect(page.get_by_test_id("page-raster")).to_be_visible(timeout=20_000)
        expect(page.get_by_test_id("status-page-source")).to_have_attribute("data-page-source", "own-uncertified")
        expect(page.get_by_test_id("status-page-source")).to_contain_text("내장 기능으로 그린 쪽")
        expect(page.get_by_test_id("strip-grade")).to_contain_text("인쇄 결과와 다를 수 있습니다")
        trigger = page.get_by_role("button", name="글꼴 대체 1")
        trigger.click()
        panel = page.get_by_test_id("font-install-panel")
        expect(panel).to_be_visible()
        expect(panel.get_by_text("함초롬바탕", exact=True)).to_be_visible()
        expect(panel.get_by_text("공식 배포처에서 받아 설치", exact=False)).to_be_visible()
        link = panel.get_by_role("link", name="공식 배포처 열기")
        url = json.loads((REPO / "desktop" / "src" / "model" / "hancomFontSource.json").read_text())
        expect(link).to_have_attribute("href", url)


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
def test_engine_font_panel_lists_real_substitution_and_rechecks(browser, server, monkeypatch):
    state = "missing"

    def detected(names):
        return dict.fromkeys(names, state)

    # start_bridge imports the runtime from its script directory.
    import rt_font_install
    monkeypatch.setattr(rt_font_install, "installed_states", detected)

    with browser.new_page(viewport={"width": 390, "height": 844}) as page:
        open_font_fixture(page, server)
        trigger = page.get_by_role("button", name="글꼴 대체 1")
        trigger.click()
        panel = page.get_by_test_id("font-install-panel")
        expect(panel).to_be_visible()
        expect(panel.get_by_text("함초롬바탕", exact=True)).to_be_visible()
        expect(panel.locator("dd")).to_contain_text("표시 글꼴 · ")
        expect(panel.get_by_text("공식 배포처에서 받아 설치", exact=False)).to_be_visible()
        link = panel.get_by_role("link", name="공식 배포처 열기")
        url = json.loads((REPO / "desktop" / "src" / "model" / "hancomFontSource.json").read_text())
        expect(link).to_have_attribute("href", url)
        expect(link).to_have_attribute("rel", "noopener noreferrer")
        expect(link).to_have_attribute("target", "_blank")
        assert page.evaluate("document.documentElement.scrollWidth") == 390

        page.keyboard.press("Escape")
        expect(panel).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        state = "unknown"
        panel.get_by_role("button", name="다시 확인").click()
        expect(panel.get_by_role("status")).to_have_text("글꼴 설치 여부를 확인할 수 없습니다.")
        expect(link).to_have_count(0)
        state = "installed"
        raster = page.get_by_test_id("page-raster")
        old = raster.get_attribute("src")
        with page.expect_request(lambda req: "/api/doc/render?" in req.url and "refreshFonts=1" in req.url):
            panel.get_by_role("button", name="다시 확인").click()
        expect(panel.get_by_role("status")).to_have_text("누락된 한컴 글꼴이 없습니다.")
        expect(raster).not_to_have_attribute("src", old)
