"""Exercise the review panel and approval sheet through the real editor and bridge."""

from __future__ import annotations

import json
import os
import re
from zipfile import ZipFile
from pathlib import Path

import pytest

from test_ui_playwright import _assert_principles
from test_ui_playwright_v1 import _rpc_post
from test_ui_wp3_canvas import _open_sample, _rpc_payload, browser, canvas_bundle, expect, server


def _session_id(page):
    page.wait_for_function("() => Boolean(document.querySelector('.shell-v2')?.dataset.session)")
    return page.locator(".shell-v2").get_attribute("data-session")


def _propose(server, session_id, edits, *, replaces=None):
    params = {
        "sessionId": session_id,
        "backend": "preedit",
        "ops": [
            {"opId": op_id, "kind": "fill_cell", "table": 0, "row": row, "col": 1, "text": text}
            for op_id, row, text in edits
        ],
    }
    if replaces is not None:
        params["replaces"] = replaces
    result = _rpc_post(server.url, server.token, "plan/propose", params)
    assert result["ok"], result
    return result["result"]["plan"]


def _confirm_ticks(page):
    for tick in page.locator('[data-testid^="tick-"]').all():
        tick.check()


def _receipts(tmp_path, session_id):
    candidates = tmp_path / "rt-root" / "sessions" / session_id / "candidates"
    return [json.loads(path.read_text()) for path in candidates.glob("*/receipt.json")]


def test_panel_keys_share_changes_and_apply_only_the_reviewed_subset(browser, server, tmp_path):
    with browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light") as page:
        _open_sample(page, server)
        sid = _session_id(page)
        proposal = _propose(server, sid, [("keeper", 5, "담당관"), ("excluded", 6, "제외할 내용")])
        first, second = (page.get_by_test_id(f"change-row-{i}") for i in (1, 2))
        expect(first).to_have_attribute("data-decision", "pending", timeout=20_000)
        expect(second).to_have_attribute("data-decision", "pending")

        page.get_by_test_id("change-summary-1").click()
        page.keyboard.press("j")
        expect(second).to_have_attribute("aria-selected", "true")
        page.keyboard.press("k")
        expect(first).to_have_attribute("aria-selected", "true")
        page.keyboard.press("y")
        expect(first).to_have_attribute("data-decision", "accepted")
        expect(page.locator('[data-mark-item="keeper"][data-mark-state="accepted"]').first).to_be_visible()
        expect(second).to_have_attribute("aria-selected", "true")

        # The panel is still on 변경, but the canvas has focus.
        page.get_by_test_id("canvas-scroll").evaluate("(el) => { el.tabIndex = -1; el.focus(); }")
        page.keyboard.press("n")
        expect(second).to_have_attribute("data-decision", "rejected")
        page.keyboard.press("Control+z")
        expect(second).to_have_attribute("data-decision", "pending")
        page.get_by_test_id("change-summary-2").click()
        page.keyboard.press("n")
        expect(second).to_have_attribute("data-decision", "rejected")

        approve = page.get_by_test_id("approve")
        expect(approve).to_be_enabled(timeout=20_000)
        page.keyboard.press("Control+Shift+Enter")
        expect(page.get_by_test_id("approve-sheet")).to_be_visible()
        _assert_principles(page, "editor v2 approval sheet")
        _confirm_ticks(page)
        token_requests, resolves = [], []
        page.on("request", lambda req: resolves.append(_rpc_payload(req)) if _rpc_payload(req).get("method") == "approval/resolve" else None)
        page.on("request", lambda req: token_requests.append(req.post_data_json) if req.url.endswith("/api/approval/confirmation") else None)
        page.get_by_test_id("approve-confirm").click()
        expect(page.get_by_test_id("applied-footer")).to_be_visible(timeout=30_000)

        receipts = _receipts(tmp_path, sid)
        assert len(receipts) == 1
        applied_id = receipts[0]["planId"]
        assert applied_id != proposal["planId"]
        projected = _rpc_post(server.url, server.token, "plan/get", {"planId": applied_id})
        assert [op["opId"] for op in projected["result"]["plan"]["ops"]] == ["keeper"]
        assert len(resolves) == 1
        assert resolves[0]["params"]["planId"] == applied_id
        assert resolves[0]["params"]["confirmationToken"]
        assert any(token["planId"] == applied_id for token in token_requests)
        with page.expect_download() as download:
            page.get_by_test_id("applied-export").click()
        assert download.value.suggested_filename.endswith(".hwpx")


def test_gongmun_approval_exports_the_expected_document(browser, server, tmp_path):
    expected = Path(__file__).resolve().parents[1] / "examples" / "gongmun" / "expected"
    proposal = json.loads((expected / "plan.json").read_text())
    ops = [{"opId": op["opId"], "kind": op["kind"], **op["params"]} for op in proposal["ops"]]
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        sid = _session_id(page)
        result = _rpc_post(server.url, server.token, "plan/propose", {
            "sessionId": sid, "backend": "preedit", "ops": ops, "declares": proposal["declares"],
        })
        assert result["ok"], result
        plan_id = result["result"]["plan"]["planId"]
        pending = _rpc_post(server.url, server.token, "approval/request", {"planId": plan_id})
        assert pending["ok"], pending

        expect(page.get_by_test_id("filter-pending")).to_contain_text("24", timeout=20_000)
        approve = page.get_by_test_id("approve")
        expect(approve).to_be_disabled()
        page.keyboard.press("Control+Shift+Enter")
        sheet = page.get_by_test_id("approve-sheet")
        expect(sheet).to_have_count(0)
        page.get_by_test_id("change-summary-1").click()
        for count in range(23, -1, -1):
            page.keyboard.press("y")
            expect(page.get_by_test_id("filter-pending")).to_contain_text(re.compile(rf"\b{count}$"))
        expect(approve).to_be_enabled(timeout=20_000)
        page.keyboard.press("Control+Shift+Enter")
        expect(sheet).to_contain_text("변경 24건 승인")
        expect(sheet.locator('[data-testid^="sheet-after-"]')).to_have_count(0)
        page.get_by_test_id("sheet-details").locator("summary").click()
        expect(page.get_by_test_id("sheet-all").locator("li")).to_have_count(24)
        page.get_by_test_id("sheet-details").locator("summary").click()
        expect(page.get_by_test_id("guard-scope")).to_be_visible()
        expect(page.get_by_test_id("sheet-effect")).to_be_visible()
        assert not re.search(r"[0-9a-f]{13,}", sheet.inner_text())
        _confirm_ticks(page)
        sheet.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("gate-approved")).to_contain_text("직접 승인", timeout=30_000)

        with page.expect_download() as download:
            page.get_by_test_id("applied-export").click()
        with ZipFile(download.value.path()) as actual, ZipFile(expected / "filled.hwpx") as known:
            assert sorted(actual.namelist()) == sorted(known.namelist())
            assert [name for name in known.namelist() if actual.read(name) != known.read(name)] == []

    receipts = _receipts(tmp_path, sid)
    assert [receipt["planId"] for receipt in receipts] == [plan_id]
    approval_id = pending["result"]["approval"]["approvalId"]
    approved = json.loads((tmp_path / "rt-root" / "approvals" / f"{approval_id}.json").read_text())
    assert approved["state"] == "approved"
    assert approved["approver"] == "host-operator"


def test_open_approval_dries_when_replaced(browser, server, tmp_path):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        sid = _session_id(page)
        plan = _propose(server, sid, [("old", 5, "검토한 값")])
        page.get_by_test_id("change-summary-1").click(timeout=20_000)
        page.keyboard.press("y")
        expect(page.get_by_test_id("approve")).to_be_enabled(timeout=20_000)
        with page.expect_response(lambda res: res.url.endswith("/api/approval/confirmation")) as issued:
            page.get_by_test_id("approve").click()
        assert issued.value.ok
        sheet = page.get_by_test_id("approve-sheet")
        expect(sheet).to_be_visible()
        _confirm_ticks(page)
        expect(page.get_by_test_id("approve-confirm")).to_be_enabled()

        calls = []
        page.on("request", lambda req: calls.append(_rpc_payload(req).get("method")) if _rpc_payload(req) else None)
        replacement = _propose(server, sid, [("new", 5, "새 제안 값")], replaces=plan["planId"])
        assert replacement["planHash"] != plan["planHash"]
        expect(sheet).to_have_count(0, timeout=20_000)
        row = page.get_by_test_id("change-row-1")
        expect(row).to_have_attribute("data-item-id", "new")
        expect(row).to_have_attribute("data-decision", "pending")
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("approve")).to_be_disabled()
        assert "approval/resolve" not in calls
        assert "plan/apply" not in calls
        assert not _receipts(tmp_path, sid)


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_panel_layout_with_sample(browser, server, width, height):
    with browser.new_page(viewport={"width": width, "height": height}, color_scheme="light") as page:
        _open_sample(page, server)
        sid = _session_id(page)
        _propose(server, sid, [("first", 5, "문서 담당관"), ("second", 6, "공공기록 검토")])
        panel = page.get_by_test_id("right-panel")
        expect(panel).to_be_visible()
        expect(page.get_by_test_id("change-row-2")).to_be_visible(timeout=20_000)
        _assert_principles(page, f"editor v2 panel at {width}")
        assert page.evaluate("document.documentElement.scrollWidth") == width

        if width == 390:
            paper = page.get_by_test_id("canvas-scroll").bounding_box()
            sheet = panel.bounding_box()
            assert paper["y"] + paper["height"] <= sheet["y"]
            page.get_by_test_id("toggle-right").click()
            expect(panel).to_be_hidden()
            page.get_by_test_id("toggle-right").click()
            expect(panel).to_be_visible()

        if output := os.environ.get("RL_WP4A_SCREENSHOTS"):
            expect(page.get_by_test_id("gate-box")).not_to_contain_text("점검 중", timeout=20_000)
            image = Path(output) / f"v2-panel-{width}-light.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=image, animations="disabled")

        page.get_by_test_id("panel-tab-checks").click()
        expect(page.get_by_test_id("checks-pane")).to_be_visible()
        page.get_by_test_id("panel-tab-agent").click()
        expect(page.get_by_test_id("agent-pane")).to_be_visible()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_gongmun_typing_approval_history_and_export(browser, server, tmp_path, theme):
    from test_ui_walkthrough_gongmun import _assert_surface_clean

    with browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=theme) as page:
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        _open_sample(page, server)
        _assert_surface_clean(page, f"mounted document {theme}")
        body = page.locator('[data-cell-key="c:0:2:0"]')
        value = "1. 관련: 기록정책과-88(2026. 10. 30.)"
        body.click()
        seat = page.get_by_test_id("seat-input")
        seat.fill(value)
        seat.press("Enter")
        row = page.get_by_test_id("change-row-1")
        expect(row).to_have_attribute("data-decision", "accepted")
        expect(row).to_contain_text("내 입력")
        expect(row).to_contain_text(value)
        expect(page.get_by_test_id("mark-1").first).to_be_visible()
        approve = page.get_by_test_id("approve")
        expect(approve).to_be_enabled(timeout=30_000)
        approve.click()
        sheet = page.get_by_test_id("approve-sheet")
        expect(sheet).to_contain_text("변경 1건 승인")
        expect(page.get_by_test_id("sheet-after-1")).to_have_text(value)
        page.get_by_test_id("sheet-details").locator("summary").click()
        expect(page.get_by_test_id("sheet-all-after-1")).to_have_text(value)
        _assert_principles(page, f"mounted approval {theme}")
        _assert_surface_clean(page, f"mounted approval {theme}")
        _confirm_ticks(page)
        page.get_by_test_id("approve-confirm").click()
        expect(page.get_by_test_id("applied-footer")).to_be_visible(timeout=30_000)
        expect(body).to_contain_text(value)
        expect(page.get_by_test_id("strip-version")).to_have_text("수정본 1")
        page.keyboard.press("Alt+5")
        expect(page.get_by_test_id("history-row-1")).to_have_attribute("aria-current", "true")
        expect(page.get_by_test_id("history-box-1")).to_contain_text("내 입력")
        expect(page.get_by_test_id("history-row-source")).to_be_visible()
        with page.expect_download() as download:
            page.get_by_test_id("strip-export").click()
        assert download.value.suggested_filename.endswith(".hwpx")
        assert len(_receipts(tmp_path, _session_id(page))) == 1
        assert not errors, errors
