"""Exercise the review panel and approval sheet through the real editor and bridge."""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.request
from zipfile import ZipFile
from pathlib import Path

import pytest

from test_ui_playwright import _assert_principles
from test_ui_playwright_v1 import _confirmation_token, _rpc_post
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
        for row in (first, second):
            headers = row.get_by_role("table").get_by_role("rowheader")
            expect(headers).to_have_count(2)
            expect(headers.nth(0)).to_contain_text("−")
            expect(headers.nth(1)).to_contain_text("+")

        page.get_by_test_id("change-summary-1").click()
        expect(first.get_by_text("변경 전", exact=True)).to_be_visible()
        expect(first.get_by_text("변경 후", exact=True)).to_be_visible()
        expect(first.get_by_test_id("act-accept")).to_have_attribute("title", "받아들이기 · Y")
        expect(first.locator("button kbd")).to_have_count(0)
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
        applied_plan = projected["result"]["plan"]
        assert [op["opId"] for op in applied_plan["ops"]] == ["keeper"]
        assert applied_plan["planHash"] != proposal["planHash"]
        page.get_by_test_id("applied-details").locator("summary").click()
        expect(page.get_by_test_id("applied-plan-hash")).to_have_attribute("title", applied_plan["planHash"])
        expect(page.get_by_test_id("applied-plan-hash")).to_have_text(applied_plan["planHash"][:12])
        page.get_by_test_id("panel-tab-agent").click()
        page.get_by_test_id("thread-applied-details").locator("summary").click()
        expect(page.get_by_test_id("thread-applied-plan-hash")).to_have_attribute("title", applied_plan["planHash"])
        page.get_by_test_id("panel-tab-changes").click()
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
            # In the compact sheet 돌려보내기 and 승인 stay reachable: the sheet
            # scrolls to them instead of leaving them under the composer (T288).
            uncovered = """el => { const r = el.getBoundingClientRect();
                const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return el.contains(hit); }"""
            for test_id in ("return", "approve"):
                button = panel.get_by_test_id(test_id)
                button.scroll_into_view_if_needed()
                assert button.evaluate(uncovered), test_id
            # A change's head, its actions and the agent thread row are touch
            # targets, and no filter is narrower than 24 px (T289).
            page.get_by_test_id("change-summary-1").click()
            for sel in (".rp-thread-row", ".rp-row-head", ".rp-row[aria-selected='true'] .rp-row-actions .rp-btn"):
                targets = panel.locator(sel)
                assert targets.count() > 0, sel
                for el in targets.all():
                    box = el.bounding_box()
                    assert box is not None and box["height"] >= 43.5, (sel, box)
            for el in panel.locator(".rp-filter").all():
                box = el.bounding_box()
                assert box is not None and box["width"] >= 24, box
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
        expect(row.locator(".rp-row-meta .rp-source")).to_be_visible()
        expect(row.locator(".rp-row-meta .rp-source")).to_have_text("내 입력")
        expect(row).to_contain_text(value)
        expect(body.locator('.rl-review-mark[data-selected][data-decision="accepted"]')).to_be_visible()
        expect(page.get_by_test_id("scrollmap-tick-1")).to_be_visible()
        approve = page.get_by_test_id("approve")
        expect(approve).to_be_enabled(timeout=30_000)
        page.keyboard.press("Control+Shift+Enter")
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


def test_review_keys_stand_down_and_text_fields_pass_palette_chords(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        _propose(server, _session_id(page), [("pending", 5, "담당관")])
        row = page.get_by_test_id("change-row-1")
        expect(row).to_have_attribute("data-decision", "pending", timeout=20_000)
        page.get_by_test_id("change-summary-1").click()
        page.keyboard.press("Control+Comma")
        settings = page.get_by_test_id("settings-dialog")
        expect(settings).to_be_visible()
        page.keyboard.press("n")
        expect(row).to_have_attribute("data-decision", "pending")
        page.keyboard.press("Escape")
        page.get_by_test_id("return").click()
        reason = page.get_by_test_id("return-reason")
        expect(reason).to_be_focused()
        page.keyboard.press("n")
        expect(reason).to_have_value("n")
        page.keyboard.press("Control+k")
        expect(page.get_by_test_id("palette")).to_be_visible()
        expect(row).to_have_attribute("data-decision", "pending")


def test_files_pane_opens_a_resolved_document_folder_file(browser, server, tmp_path):
    folder = tmp_path / "문서 폴더"
    folder.mkdir()
    source = Path(__file__).parent / "corpus" / "forms" / "converted" / "gianmun-byeolji-2ho.hwpx"
    document = folder / "기안문.hwpx"
    shutil.copyfile(source, document)
    request = urllib.request.Request(
        server.url.rstrip("/") + "/api/doc-folder",
        data=json.dumps({"path": str(folder)}).encode(),
        headers={"Content-Type": "application/json", "X-Rigorloom-Token": server.token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        assert response.status == 200

    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        original = _session_id(page)
        page.get_by_test_id("pane-tab-files").click()
        row = page.locator('.sh-tree-row[data-kind="file"]', has_text=document.name)
        with page.expect_request(lambda req: _rpc_payload(req).get("method") == "workspace/openPath") as opened:
            row.click()
        assert _rpc_payload(opened.value)["params"]["path"] == str(document.resolve())
        expect(page.locator(".shell-v2")).not_to_have_attribute("data-session", original)
        expect(page.get_by_test_id("paper").first).to_be_visible(timeout=20_000)


def test_reproposal_reaches_a_revision_published_by_another_client(browser, server, tmp_path):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        sid = _session_id(page)
        cell = page.locator('[data-cell-key="c:0:5:1"]')
        cell.click()
        seat = page.get_by_test_id("seat-input")
        seat.fill("기록정책담당관")
        seat.press("Enter")
        approve = page.get_by_test_id("approve")
        expect(approve).to_be_enabled(timeout=20_000)
        approve.click()
        sheet = page.get_by_test_id("approve-sheet")
        expect(sheet).to_have_attribute("data-ready", "")

        def rpc(method, params):
            reply = _rpc_post(server.url, server.token, method, params)
            assert reply["ok"], reply
            return reply["result"]

        fixture = Path(__file__).resolve().parents[1] / "examples" / "gongmun" / "expected" / "plan.json"
        other = json.loads(fixture.read_text())["ops"][5]
        plan = rpc("plan/propose", {
            "sessionId": sid, "backend": "preedit",
            "ops": [{"kind": other["kind"], **other["params"]}],
        })["plan"]
        approval = rpc("approval/request", {"planId": plan["planId"]})["approval"]
        rpc("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": plan["planId"], "planHash": plan["planHash"],
            "decision": "approved", "approver": "another-client",
            "confirmationToken": _confirmation_token(server.url, server.token, sid, plan),
        })
        candidate = rpc("plan/apply", {"planId": plan["planId"], "approvalId": approval["approvalId"]})["candidate"]

        _confirm_ticks(page)
        page.get_by_test_id("approve-confirm").click()
        expect(sheet).to_have_count(0, timeout=20_000)
        expect(page.get_by_test_id("stale-banner")).to_contain_text("수정본 1", timeout=20_000)
        assert len(_receipts(tmp_path, sid)) == 1
        with page.expect_request(lambda req: _rpc_payload(req).get("method") == "plan/propose") as reproposed:
            page.get_by_test_id("stale-repropose").click()
        assert _rpc_payload(reproposed.value)["params"]["baseRunId"] == candidate["runId"]
        expect(page.get_by_test_id("stale-banner")).to_have_count(0, timeout=20_000)
        expect(approve).to_be_enabled(timeout=20_000)


def test_refused_decision_retries_with_a_new_sheet_token(browser, server, tmp_path):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        tokens = []

        def refuse_once(route):
            payload = _rpc_payload(route.request)
            if payload.get("method") == "approval/resolve" and payload["params"]["decision"] == "approved":
                tokens.append(payload["params"].get("confirmationToken"))
                if len(tokens) == 1:
                    route.fulfill(json={"ok": False, "error": {"code": "confirmation_required", "message": "Retry"}})
                    return
            route.continue_()

        page.route("**/rpc", refuse_once)
        _open_sample(page, server)
        sid = _session_id(page)
        _propose(server, sid, [("approve-on-retry", 5, "담당관")])
        page.get_by_test_id("change-summary-1").click(timeout=20_000)
        page.keyboard.press("y")
        approve = page.get_by_test_id("approve")
        expect(approve).to_be_enabled(timeout=20_000)
        approve.click()
        _confirm_ticks(page)
        confirm = page.get_by_test_id("approve-confirm")
        confirm.click()
        expect(page.get_by_test_id("sheet-error")).to_be_visible()
        assert not _receipts(tmp_path, sid)
        _confirm_ticks(page)
        confirm.click()
        expect(page.get_by_test_id("applied-footer")).to_be_visible(timeout=30_000)
        assert len(tokens) == 2 and all(tokens) and tokens[0] != tokens[1]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_required_tick_takes_keyboard_focus_with_visible_ring(browser, server, tmp_path, theme):
    with browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=theme) as page:
        _open_sample(page, server)
        sid = _session_id(page)
        value = "시험 값"
        provenance = tmp_path / "rt-root" / "provenance"
        provenance.mkdir(exist_ok=True)
        (provenance / f"{sid}.json").write_text(
            json.dumps({"mockOps": [json.dumps(["cell", 0, 5, 1, value], ensure_ascii=False)]}),
            encoding="utf-8",
        )
        plan = _propose(server, sid, [("test-value", 5, value)])
        assert plan.get("mockOps") == ["test-value"]
        page.get_by_test_id("change-summary-1").click(timeout=20_000)
        page.keyboard.press("y")
        expect(page.get_by_test_id("approve")).to_be_enabled(timeout=20_000)
        page.keyboard.press("Control+Shift+Enter")
        sheet = page.get_by_test_id("approve-sheet")
        expect(sheet).to_have_attribute("data-ready", "")
        tick = page.get_by_test_id("tick-test")
        expect(tick).to_be_focused()
        expect(tick).to_have_css("outline-style", "solid")
        expect(tick).to_have_css("outline-width", "2px")
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("approve-confirm")).to_be_disabled()
        assert not _receipts(tmp_path, sid)
        page.keyboard.press("Space")
        expect(tick).to_be_checked()
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("applied-footer")).to_be_visible(timeout=30_000)


def test_open_settings_switches_an_already_open_dialog_to_the_requested_section(browser, server):
    with browser.new_page(viewport={"width": 1440, "height": 900}) as page:
        _open_sample(page, server)
        page.get_by_test_id("composer-connect").click()
        dialog = page.get_by_test_id("settings-dialog")
        agent = dialog.get_by_test_id("settings-nav-settings-agent")
        general = dialog.get_by_test_id("settings-nav-general")
        expect(agent).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Control+Comma")
        expect(dialog).to_be_visible()
        expect(general).to_have_attribute("aria-selected", "true")
        expect(general).to_be_focused()
        expect(agent).to_have_attribute("aria-selected", "false")
        folders = dialog.get_by_test_id("settings-nav-folders")
        folders.click()
        expect(folders).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Control+Comma")
        expect(general).to_have_attribute("aria-selected", "true")
