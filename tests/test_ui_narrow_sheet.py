"""Playwright checks for the two-height narrow bottom sheet (T233)."""

from __future__ import annotations

from pathlib import Path

from _browser_gate import no_browser
from _editor_v2 import editor_v2_url
from test_ui_playwright import (
    _assert_principles,
    _bundle_has_shell,
    _import_playwright,
    _launch_chromium,
    _open_sample,
    _start_ui_server,
    _stop_ui_server,
)

VIEWPORT_W = 390
VIEWPORT_H = 844


def _drag_handle(page, handle, dy: float, *, check_no_live_move: bool = False) -> None:
    box = handle.bounding_box()
    assert box is not None
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    before_expanded = handle.get_attribute("aria-expanded")
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx, cy + dy, steps=5)
    if check_no_live_move:
        assert handle.get_attribute("aria-expanded") == before_expanded
    page.mouse.up()


def test_narrow_bottom_sheet_compact_expanded_close_and_escape(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    proc, base_url = _start_ui_server(tmp_path)
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            page = context.new_page()
            page_errors: list[str] = []
            server_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on(
                "response",
                lambda r: server_errors.append(f"{r.status} {r.url}") if r.status >= 500 else None,
            )

            page.goto(editor_v2_url(base_url))
            page.wait_for_selector('[data-testid="shell"]', timeout=60000)
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=30000)
            _open_sample(page, 0)
            _open_sample(page, 1)

            page.set_viewport_size({"width": VIEWPORT_W, "height": VIEWPORT_H})
            page.wait_for_function(
                "document.querySelector('[data-testid=shell]').dataset.breakpoint === 'narrow'"
            )

            sheet = page.locator("#sh-narrow-sheet")
            main = page.locator(".sh-narrow-main")
            handle = page.get_by_test_id("narrow-sheet-handle")
            toggle = page.get_by_test_id("toggle-right")

            sheet.wait_for(state="visible")
            main.wait_for(state="visible")

            # 1) Default compact state: sheet <= 0.35 * 844, .sh-narrow-main >= 0.5 * 844.
            compact_sheet_box = sheet.bounding_box()
            compact_main_box = main.bounding_box()
            assert compact_sheet_box is not None and compact_main_box is not None
            assert compact_sheet_box["height"] <= 0.35 * VIEWPORT_H, compact_sheet_box
            assert compact_main_box["height"] >= 0.5 * VIEWPORT_H, compact_main_box
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            _assert_principles(page, "narrow-compact")

            # The sheet's tabs and the 연결 설정 link are touch-sized; 점검 was
            # 22 px wide and the tabs 36 px tall (T283).
            for tab_box in [t.bounding_box() for t in sheet.locator(".rp-tab").all()]:
                assert tab_box is not None and tab_box["height"] >= 43.5 and tab_box["width"] >= 36, tab_box
            for link in sheet.locator(".rp-composer--off .rp-link").all():
                link_box = link.bounding_box()
                assert link_box is not None and link_box["height"] >= 43.5, link_box

            # 2) Handle toggles compact <-> expanded.
            handle.wait_for(state="visible")
            assert handle.get_attribute("aria-expanded") == "false"
            assert handle.get_attribute("aria-controls") == "sh-narrow-sheet"
            assert handle.get_attribute("aria-label") == "변경 창 크게 보기"

            handle.click()
            assert handle.get_attribute("aria-expanded") == "true"
            assert handle.get_attribute("aria-label") == "변경 창 작게 보기"
            expanded_sheet_box = sheet.bounding_box()
            expanded_main_box = main.bounding_box()
            titlebar_box = page.get_by_test_id("titlebar").bounding_box()
            assert expanded_sheet_box is not None and expanded_main_box is not None and titlebar_box is not None
            assert expanded_sheet_box["height"] >= 0.6 * VIEWPORT_H, expanded_sheet_box
            assert titlebar_box["height"] >= 48 and expanded_sheet_box["y"] >= titlebar_box["height"], (
                titlebar_box,
                expanded_sheet_box,
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            _assert_principles(page, "narrow-expanded")

            handle.click()
            assert handle.get_attribute("aria-expanded") == "false"
            again_compact_box = sheet.bounding_box()
            assert again_compact_box is not None
            assert again_compact_box["height"] <= 0.35 * VIEWPORT_H, again_compact_box

            # 3) Expand, then close the sheet with the top-bar toggle and reopen it: compact again.
            handle.click()
            assert handle.get_attribute("aria-expanded") == "true"
            toggle.click()
            assert sheet.is_hidden()
            toggle.click()
            sheet.wait_for(state="visible")
            assert handle.get_attribute("aria-expanded") == "false"
            reopened_box = sheet.bounding_box()
            assert reopened_box is not None
            assert reopened_box["height"] <= 0.35 * VIEWPORT_H, reopened_box

            # 4) Expand, focus the handle, press Escape: compact again, and the sheet is still open.
            handle.click()
            assert handle.get_attribute("aria-expanded") == "true"
            handle.focus()
            page.keyboard.press("Escape")
            assert sheet.is_visible()
            assert handle.get_attribute("aria-expanded") == "false"
            escaped_box = sheet.bounding_box()
            assert escaped_box is not None
            assert escaped_box["height"] <= 0.35 * VIEWPORT_H, escaped_box

            # Escape with focus inside the sheet also collapses it to compact while keeping it open.
            handle.click()
            assert handle.get_attribute("aria-expanded") == "true"
            page.get_by_test_id("panel-tab-agent").focus()
            page.keyboard.press("Escape")
            assert sheet.is_visible()
            assert handle.get_attribute("aria-expanded") == "false"

            # Switching tabs in the drawer resets the expanded sheet to compact.
            handle.click()
            assert handle.get_attribute("aria-expanded") == "true"
            page.get_by_test_id("app-menu").click()
            page.locator('[data-testid="narrow-drawer"] .sh-drawer-row:not([data-selected])').first.click()
            assert sheet.is_visible()
            assert handle.get_attribute("aria-expanded") == "false"

            # 5) Pointer drag on the handle: >32 px up expands, >32 px down collapses,
            # downward drag when already compact keeps it compact without closing, and
            # a short (10 px) drag behaves like a single click toggle.
            _drag_handle(page, handle, -80, check_no_live_move=True)
            assert handle.get_attribute("aria-expanded") == "true"
            assert handle.get_attribute("aria-label") == "변경 창 작게 보기"
            assert handle.evaluate("el => getComputedStyle(el).touchAction") == "none"
            drag_expanded_box = sheet.bounding_box()
            assert drag_expanded_box is not None
            assert drag_expanded_box["height"] >= 0.6 * VIEWPORT_H, drag_expanded_box

            _drag_handle(page, handle, 80, check_no_live_move=True)
            assert sheet.is_visible()
            assert handle.get_attribute("aria-expanded") == "false"
            assert handle.get_attribute("aria-label") == "변경 창 크게 보기"
            drag_compact_box = sheet.bounding_box()
            assert drag_compact_box is not None
            assert drag_compact_box["height"] <= 0.35 * VIEWPORT_H, drag_compact_box

            # Downward drag when already compact closes nothing and stays compact.
            _drag_handle(page, handle, 80)
            assert sheet.is_visible()
            assert handle.get_attribute("aria-expanded") == "false"

            # Short 10 px drag then release behaves like a click (toggles once).
            _drag_handle(page, handle, -10)
            assert handle.get_attribute("aria-expanded") == "true"
            _drag_handle(page, handle, 10)
            assert handle.get_attribute("aria-expanded") == "false"

            assert page_errors == [], page_errors
            assert server_errors == [], server_errors
            context.close()
            browser.close()
    finally:
        _stop_ui_server(proc)


def test_narrow_drawer_opens_a_document_and_closes_tabs(tmp_path: Path) -> None:
    """Under 600 px the tab strip is gone; the drawer opens and closes tabs instead (T278)."""
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    proc, base_url = _start_ui_server(tmp_path)
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(editor_v2_url(base_url), wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="shell"]', timeout=60000)
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=30000)
            _open_sample(page, 0)

            page.set_viewport_size({"width": VIEWPORT_W, "height": VIEWPORT_H})
            page.wait_for_function(
                "document.querySelector('[data-testid=shell]').dataset.breakpoint === 'narrow'"
            )
            drawer = page.get_by_test_id("narrow-drawer")
            rows = drawer.locator(".sh-drawer-tab")

            # The drawer offers 문서 열기, which brings back the start page.
            page.get_by_test_id("app-menu").click()
            assert rows.count() == 1

            # The document's pane tabs under the tab list show their whole labels.
            tab_box = drawer.locator(".sh-pane-tab").first.bounding_box()
            row_box = drawer.locator(".sh-pane-tabs").bounding_box()
            assert tab_box is not None and row_box is not None
            assert tab_box["y"] + tab_box["height"] <= row_box["y"] + row_box["height"] + 0.5, (tab_box, row_box)

            # Every pane shares the drawer's colour; the outline, blanks and find
            # panes used to show as grey blocks on a white drawer (T281).
            drawer_bg = drawer.evaluate("el => getComputedStyle(el).backgroundColor")
            pane_tabs = drawer.locator(".sh-pane-tab")
            for i in range(pane_tabs.count()):
                pane_tabs.nth(i).click()
                pane = drawer.locator(".rl-pane")
                if pane.count():
                    pane_bg = pane.first.evaluate("el => getComputedStyle(el).backgroundColor")
                    assert pane_bg == drawer_bg, (i, pane_bg, drawer_bg)
                # Rows, fields and buttons in the drawer's panes are touch-sized (T282).
                for sel in (".sh-tree-row", ".rl-outline-btn", ".rl-blank-btn", ".rl-find-input", ".rl-pane-btn"):
                    target = drawer.locator(sel)
                    if target.count():
                        box = target.first.bounding_box()
                        assert box is not None and box["height"] >= 43.5, (i, sel, box)
                        if sel == ".rl-pane-btn":
                            assert box["width"] >= 43.5, (i, sel, box)
            pane_tabs.first.click()

            add = page.get_by_test_id("narrow-tab-add")
            assert add.inner_text().endswith("문서 열기")
            add.click()
            assert drawer.count() == 0
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=30000)

            # Both tabs are listed, each with its own close button.
            page.get_by_test_id("app-menu").click()
            assert rows.count() == 2
            close = rows.nth(0).locator(".sh-drawer-tab-close")
            assert close.get_attribute("aria-label").startswith("탭 닫기 · ")
            close.click()
            assert rows.count() == 1

            # Closing the last tab leaves the start page, listed in the drawer.
            rows.nth(0).locator(".sh-drawer-tab-close").click()
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=30000)
            if drawer.count() == 0:
                page.get_by_test_id("app-menu").click()
            assert rows.count() == 1
            assert rows.nth(0).locator(".sh-drawer-row").inner_text() == "시작"
            assert page_errors == [], page_errors
            context.close()
            browser.close()
    finally:
        _stop_ui_server(proc)


def test_narrow_settings_dialog_is_touch_sized_and_keeps_its_buttons(tmp_path: Path) -> None:
    """Under 600 px the settings dialog's controls are touch-sized and fit (T284)."""
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    proc, base_url = _start_ui_server(tmp_path)
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(editor_v2_url(base_url), wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=60000)
            _open_sample(page, 0)
            page.set_viewport_size({"width": VIEWPORT_W, "height": VIEWPORT_H})
            page.wait_for_function(
                "document.querySelector('[data-testid=shell]').dataset.breakpoint === 'narrow'"
            )
            page.get_by_test_id("app-menu").click()
            page.locator(".sh-drawer-foot button").first.click()
            dialog = page.locator('[role="dialog"]')
            dialog.wait_for(state="visible")
            dialog_box = dialog.bounding_box()
            assert dialog_box is not None

            # Nav rows and option groups are touch-sized.
            for sel in (".sh-settings-navrow", ".sh-seg-item"):
                for el in dialog.locator(sel).all():
                    box = el.bounding_box()
                    assert box is not None and box["height"] >= 43.5, (sel, box)

            # A long work folder path shortens; 폴더 바꾸기 stays inside the dialog.
            page.get_by_test_id("settings-nav-folders").click()
            change = page.get_by_test_id("settings-folder-change")
            change_box = change.bounding_box()
            assert change_box is not None and change_box["height"] >= 43.5, change_box
            assert change_box["x"] + change_box["width"] <= dialog_box["x"] + dialog_box["width"], (change_box, dialog_box)
            content = dialog.locator(".sh-settings-content")
            assert content.evaluate("el => el.scrollWidth <= el.clientWidth"), "settings content scrolls sideways"
            assert page_errors == [], page_errors
            context.close()
            browser.close()
    finally:
        _stop_ui_server(proc)
