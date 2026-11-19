"""End-to-end Playwright verification for Rigorloom local web UI (`cli.py ui`).

Covers:
1. Clean `pytest.skip` when `playwright` or headless Chromium is unavailable
   (a failure instead under `RL_REQUIRE_BROWSER=1`).
2. Live subprocess launch (`cli.py ui --root <tmp> --port 0 --no-open`) with zero
   uncaught `pageerror`s and zero HTTP 5xx / unexpected API errors.
3. Opening a real corpus form (`gianmun-byeolji-1ho.hwpx`) via the Open screen
   sample catalog, verifying recent-item navigation via `nav-open` reuses the
   active session without duplicating it or leaking raw paths.
4. Korean IME composition safety on `SeatEditor` (`compositionstart` -> `'ㅎ'` ->
   `Enter` blocked mid-composition, plus Ruling H `j`/`k`/`a`/`r` shortcut guard
   inside focused inputs -> `compositionupdate`/`compositionend` `'한글'` ->
   `Enter` commits with `composed === true`).
5. Removing the temporary edit, proposing a 4-op plan via `/rpc` `plan/propose`
   containing all 4 distinct op kinds (`fill_cell`, `replace_at_cell`, `set_run`,
   `delete_guides`), waiting for auto-adoption into `ChangeList` (`change-row-1..4`),
   verifying Ruling D pills (`fill_cell` without pill, existing-text ops with guard
   pills, `change-added-numbers-*` for newly introduced numbers), collapsed row
   height <= 56 px, and row expansion (`change-detail-1`).
6. `ApprovalDialog` 12-character `approval-plan-hash` / `approval-bound-hash`
   (full 64-hex in `data-full-hash`, under 자세히) and `approval-changed-facts-ack`
   gating before confirm.
7. External byte-drift `plan_stale` defense: runtime `/rpc` `plan/apply` refusal on
   an approved stale plan and UI `approval-stale-banner` -> `approval-repropose-btn`
   -> new 64-hex `approval-plan-hash` -> re-ack -> apply -> verified `.hwpx` export.
8. Viewport/theme screenshots (`{open,review,fill,history,settings}-{1440,390}-{light,dark}.png`)
   saved only under `tmp_path` (`scrollWidth <= innerWidth`), leaving `docs/ui/` untouched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

from _browser_gate import no_browser  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "runtime" / "scripts" / "cli.py"
PREEDIT_PATH = REPO_ROOT / "engine" / "scripts" / "preedit.py"
CORPUS_FORM_PATH = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
CORPUS_FORM_FILENAME = "gianmun-byeolji-1ho.hwpx"

EXPECTED_TEMP_SCREENSHOTS = [
    f"{screen}-{width}-{theme}.png"
    for screen in ("open", "review", "fill", "history", "settings")
    for width in (1440, 390)
    for theme in ("light", "dark")
]


def _import_playwright():
    """Import Playwright or skip cleanly when unavailable in this Python environment."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        no_browser(f"playwright Python package unavailable: {exc}")
    return sync_playwright


def _launch_chromium(pw):
    """Launch headless Chromium or skip cleanly when browser binaries/libs are missing."""
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - environment dependent
        no_browser(f"headless Chromium unavailable: {exc}")


def _start_ui_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str, Path]:
    """Start `cli.py ui --root <tmp> --port 0 --no-open` and return (proc, url, rt_root)."""
    rt_root = tmp_path / "ui-root"
    xdg_dir = tmp_path / "xdg-data"
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(xdg_dir)
    # The agent request box is enabled only with a real provider or the
    # developer test-agent setting; the Ruling H typing check below needs it.
    env["RIGORLOOM_DEV_MOCK_AGENT"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(CLI_PATH),
            "ui",
            "--root",
            str(rt_root),
            "--port",
            "0",
            "--no-open",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    url = None
    deadline = time.monotonic() + 20.0
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"cli.py ui exited early ({proc.returncode}): {err}")
            continue
        match = re.search(r"(http://127\.0\.0\.1:\d+/\S*)", line)
        if match:
            url = match.group(1)
            break
    if not url:
        proc.terminate()
        raise RuntimeError("Timed out waiting for Rigorloom UI listening URL")
    return proc, url, rt_root


def _stop_ui_server(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _rpc_post(base_url: str, token: str, method: str, params: dict) -> dict:
    """Invoke POST /rpc with bridge auth headers directly for protocol assertions."""
    endpoint = base_url.rstrip("/") + "/rpc"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({"method": method, "params": params}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Rigorloom-Token": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _confirmation_token(base_url: str, token: str, session_id: str, plan: dict) -> str:
    """The approval sheet's single-use token, which the bridge requires to approve."""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/approval/confirmation",
        data=json.dumps(
            {
                "sessionId": session_id,
                "planId": plan["planId"],
                "planHash": plan["planHash"],
                "baseDigest": plan["boundSha256"],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Rigorloom-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))["confirmationToken"]


def _mutate_hwpx_source(hwpx_path: Path, scratch_dir: Path, name: str = "external-drift.hwpx") -> None:
    """Mutate a valid HWPX file atomically via preedit.py to simulate external byte drift."""
    mutated = scratch_dir / name
    res = subprocess.run(
        [
            sys.executable,
            str(PREEDIT_PATH),
            "fill-cells",
            str(hwpx_path),
            "--out",
            str(mutated),
            "--table",
            "0",
            "--cell",
            "5,13=외부변경",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    os.replace(mutated, hwpx_path)


def _set_viewport_and_theme(page, width: int, height: int, theme: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(color_scheme=theme)
    page.evaluate(
        """(t) => {
            document.documentElement.setAttribute('data-theme', t);
            try { window.localStorage.setItem('rigorloom.theme', t); } catch {}
        }""",
        theme,
    )
    page.wait_for_timeout(250)
    if width <= 400:
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        inner_w = page.evaluate("window.innerWidth")
        assert scroll_w <= inner_w, (
            f"Horizontal overflow at {width}x{height} ({theme}): "
            f"scrollWidth={scroll_w} > innerWidth={inner_w}"
        )


def _save_screen_variants(
    page,
    screen: str,
    run_dir: Path,
    *,
    mobile_tab: str | None = None,
    scroll_into_view_selector: str | None = None,
) -> None:
    """Capture 1440x900 and 390x844 in light and dark themes into tmp_path only."""
    for width, height in ((1440, 900), (390, 844)):
        if width <= 400 and mobile_tab:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(80)
            btn = page.locator(f'[data-testid="{mobile_tab}"]')
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                page.wait_for_timeout(100)
        for theme in ("light", "dark"):
            _set_viewport_and_theme(page, width, height, theme)
            if scroll_into_view_selector:
                page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (el) el.scrollIntoView({ block: 'start' });
                    }""",
                    scroll_into_view_selector,
                )
                page.wait_for_timeout(60)
            fname = f"{screen}-{width}-{theme}.png"
            out = run_dir / fname
            page.screenshot(path=str(out))
            raw = out.read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 5000, fname


def test_ui_playwright_e2e_ime_reapproval_and_screenshots(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    proc, url, rt_root = _start_ui_server(tmp_path)
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    page_errors: list[str] = []
    server_errors: list[tuple[int, str]] = []
    api_errors: list[tuple[int, str]] = []

    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="light",
                accept_downloads=True,
            )
            page = context.new_page()
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.on(
                "response",
                lambda resp: (
                    server_errors.append((resp.status, resp.url))
                    if resp.status >= 500
                    else (
                        api_errors.append((resp.status, resp.url))
                        if resp.status >= 400 and ("/api/" in resp.url or "/rpc" in resp.url)
                        else None
                    )
                ),
            )

            # 1) Load UI & Open screen
            page.goto(url, wait_until="domcontentloaded")
            splash = page.locator('[data-testid="splash"]')
            if splash.count() > 0:
                splash.first.click(force=True)
            page.wait_for_selector('[data-testid="open-view"]', timeout=15000)

            sample_list = page.locator('[data-testid="open-sample-list"]')
            if sample_list.count() == 0 or not sample_list.is_visible():
                page.click('[data-testid="open-samples-toggle"]')
            page.wait_for_selector(
                f'[data-testid="open-sample-item-{CORPUS_FORM_FILENAME}"]',
                timeout=15000,
            )
            _save_screen_variants(page, "open", shots_dir)
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 2) Open real corpus form and test nav-open recent session reuse
            page.click(f'[data-testid="open-sample-item-{CORPUS_FORM_FILENAME}"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=15000)
            page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=15000)

            bootstrap = page.evaluate("() => window.__RIGORLOOM_UI__")
            token = bootstrap["token"]
            base_url = url.split("?", 1)[0]

            page.click('[data-testid="nav-open"]')
            page.wait_for_selector(
                f'[data-testid="open-recent-item-{CORPUS_FORM_FILENAME}"]',
                timeout=10000,
            )
            recent_text = page.locator('[data-testid="open-recent-list"]').inner_text()
            assert "/home/" not in recent_text and "/tmp/" not in recent_text, recent_text
            page.click(f'[data-testid="open-recent-item-{CORPUS_FORM_FILENAME}"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=10000)

            sessions_res = _rpc_post(base_url, token, "session/list", {})
            assert sessions_res["ok"] is True, sessions_res
            assert len(sessions_res["result"]["sessions"]) == 1, sessions_res
            session_id = sessions_res["result"]["sessions"][0]["sessionId"]

            # Capture Fill screen temp variants and return to Review before IME check
            page.click('[data-testid="nav-fill"]')
            page.wait_for_selector('[data-testid="fill-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=10000)
            _save_screen_variants(page, "fill", shots_dir)
            _set_viewport_and_theme(page, 1440, 900, "light")
            page.click('[data-testid="nav-review"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=10000)

            # 3) Korean IME safety + Ruling H shortcut guard on SeatEditor & composer
            page.click('[data-testid="page-cell-0-5-1"]')
            page.wait_for_selector('[data-testid="seat-input"]', timeout=5000)
            page.evaluate(
                """() => {
                    const el = document.querySelector('[data-testid="seat-input"]');
                    el.focus();
                    el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '' }));
                    el.value = 'ㅎ';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }"""
            )
            page.keyboard.press("Enter")
            assert page.locator('[data-testid="seat-input"]').is_visible()
            assert page.locator('[data-testid^="change-row-"]').count() == 0

            # Ruling H: typing shortcut letters inside SeatEditor must never trigger dialogs
            for key in ("j", "k", "a", "r"):
                page.keyboard.press(key)
            assert page.locator('[data-testid="approval-dialog"]').count() == 0
            assert page.locator('[data-testid="return-popover"]').count() == 0
            assert page.locator('[data-testid="seat-input"]').is_visible()

            page.evaluate(
                """() => {
                    const el = document.querySelector('[data-testid="seat-input"]');
                    el.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: '한글' }));
                    el.value = '한글';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '한글' }));
                }"""
            )
            page.keyboard.press("Enter")
            page.wait_for_selector('[data-testid="change-row-1"]', timeout=10000)
            assert page.locator(".shell").get_attribute("data-last-composed") == "true"
            assert page.locator(".shell").get_attribute("data-last-commit") == "한글"

            # Ruling H: typing shortcut letters inside prompt input must type text, not fire nav/modals
            prompt_input = page.locator('[data-testid="review-prompt-input"]')
            prompt_input.click()
            prompt_input.type("jkar")
            assert prompt_input.input_value() == "jkar"
            assert page.locator('[data-testid="approval-dialog"]').count() == 0
            assert page.locator('[data-testid="return-popover"]').count() == 0
            prompt_input.fill("")

            # 4) Remove temporary 1-op edit, propose 4-op plan via /rpc & verify Ruling D + collapse height
            page.click('[data-testid="change-summary-1"]')
            page.wait_for_selector('[data-testid="change-detail-1"]', timeout=5000)
            page.locator('[data-testid="change-detail-1"] [data-testid^="change-remove-"]').click()
            page.wait_for_function(
                "document.querySelectorAll('[data-testid^=\"change-row-\"]').length === 0",
                timeout=10000,
            )

            four_ops = [
                {
                    "opId": "op-fill",
                    "kind": "fill_cell",
                    "table": 0,
                    "row": 5,
                    "col": 1,
                    "text": "한글",
                },
                {
                    "opId": "op-replace",
                    "kind": "replace_at_cell",
                    "table": 0,
                    "row": 6,
                    "col": 0,
                    "text": "공고 2026년 100만원",
                },
                {
                    "opId": "op-set-run",
                    "kind": "set_run",
                    "atPara": 3,
                    "run": 0,
                    "text": "과학기술정보통신부 2026-11-15",
                },
                {
                    "opId": "op-delete-guides",
                    "kind": "delete_guides",
                    "color": "#0000FF",
                },
            ]
            prop_4 = _rpc_post(
                base_url,
                token,
                "plan/propose",
                {"sessionId": session_id, "backend": "preedit", "ops": four_ops},
            )
            assert prop_4["ok"] is True, prop_4

            page.wait_for_selector('[data-testid="change-row-4"]', timeout=15000)
            page.wait_for_selector('[data-testid="guard-list-header"]', timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('[data-testid^=\"change-pill-\"]').length >= 3",
                timeout=15000,
            )

            # Collapsed row height <= 56 px for all 4 rows
            rows = page.locator('[data-testid^="change-row-"]')
            assert rows.count() == 4
            for i in range(rows.count()):
                box = rows.nth(i).bounding_box()
                assert box is not None and box["height"] <= 56.5, (i, box)

            # Ruling D pills: empty fill_cell gets NO pill; 3 existing-text ops get pills; new numbers show badge
            row_by_op = page.evaluate(
                """() => {
                    const out = {};
                    for (const el of document.querySelectorAll('[data-testid^="change-row-"]')) {
                        const opId = el.getAttribute('data-op-id');
                        const tid = el.getAttribute('data-testid') || '';
                        const ord = tid.replace('change-row-', '');
                        if (opId) out[opId] = ord;
                    }
                    return out;
                }"""
            )
            assert set(row_by_op.keys()) == {
                "op-fill",
                "op-replace",
                "op-set-run",
                "op-delete-guides",
            }, row_by_op

            assert page.locator(f'[data-testid="change-pill-{row_by_op["op-fill"]}"]').count() == 0
            for audited_op in ("op-replace", "op-set-run", "op-delete-guides"):
                assert page.locator(f'[data-testid="change-pill-{row_by_op[audited_op]}"]').count() == 1
            assert (
                page.locator(f'[data-testid="change-added-numbers-{row_by_op["op-replace"]}"]').count() == 1
            )

            # Expand row 1 and verify change-detail-1 contains op details
            page.click('[data-testid="change-summary-1"]')
            page.wait_for_selector('[data-testid="change-detail-1"]', timeout=5000)
            detail_text = page.locator('[data-testid="change-detail-1"]').inner_text()
            assert len(detail_text.strip()) > 0

            _save_screen_variants(
                page,
                "review",
                shots_dir,
                mobile_tab="review-mobile-tab-list",
                scroll_into_view_selector='[data-testid="change-detail-1"]',
            )
            _set_viewport_and_theme(page, 1440, 900, "light")

            # Capture Settings screen temp variants while 4-op plan is live, then return to Review
            page.click('[data-testid="open-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=10000)
            assert page.locator('[data-testid="settings-folder-change"]').is_disabled()
            _save_screen_variants(page, "settings", shots_dir)
            _set_viewport_and_theme(page, 1440, 900, "light")
            page.click('[data-testid="nav-review"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="change-row-4"]', timeout=10000)

            # 5 & 6) ApprovalDialog: full 64-hex hashes and changed-fact ack gating
            page.click('[data-testid="review-approve-btn"]')
            page.wait_for_selector('[data-testid="approval-dialog"]', timeout=10000)

            plan_hash_before = page.locator('[data-testid="approval-plan-hash"]').get_attribute("data-full-hash")
            bound_hash_before = page.locator('[data-testid="approval-bound-hash"]').get_attribute("data-full-hash")
            assert re.fullmatch(r"[0-9a-f]{64}", plan_hash_before), plan_hash_before
            assert re.fullmatch(r"[0-9a-f]{64}", bound_hash_before), bound_hash_before
            shown_hash = page.locator('[data-testid="approval-plan-hash"]').text_content().strip()
            assert shown_hash == plan_hash_before[:12], shown_hash

            ack_box = page.locator('[data-testid="approval-changed-facts-ack"]')
            confirm_btn = page.locator('[data-testid="approval-confirm-btn"]')
            ack_box.wait_for(state="visible", timeout=10000)
            assert not ack_box.is_checked()
            assert confirm_btn.is_disabled()

            # 7) External byte-drift plan_stale defense (runtime /rpc refusal + UI re-propose)
            stale_copy = tmp_path / "stale-competing.hwpx"
            shutil.copy2(CORPUS_FORM_PATH, stale_copy)
            stale_open = _rpc_post(
                base_url,
                token,
                "workspace/openPath",
                {"path": str(stale_copy)},
            )
            assert stale_open["ok"] is True, stale_open
            stale_session_id = stale_open["result"]["sessionId"]
            stale_src_files = list((rt_root / "sessions" / stale_session_id / "source").glob("*.hwpx"))
            assert len(stale_src_files) == 1, stale_src_files
            stale_src_hwpx = stale_src_files[0]

            prop_stale = _rpc_post(
                base_url,
                token,
                "plan/propose",
                {
                    "sessionId": stale_session_id,
                    "backend": "preedit",
                    "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 2, "text": "보조"}],
                },
            )
            assert prop_stale["ok"] is True, prop_stale
            stale_plan = prop_stale["result"]["plan"]
            req_stale = _rpc_post(
                base_url,
                token,
                "approval/request",
                {"planId": stale_plan["planId"]},
            )
            assert req_stale["ok"] is True, req_stale
            stale_appr = req_stale["result"]["approval"]
            res_stale = _rpc_post(
                base_url,
                token,
                "approval/resolve",
                {
                    "approvalId": stale_appr["approvalId"],
                    "planId": stale_plan["planId"],
                    "planHash": stale_plan["planHash"],
                    "decision": "approved",
                    "approver": "playwright-verifier",
                    "confirmationToken": _confirmation_token(
                        base_url, token, stale_session_id, stale_plan
                    ),
                },
            )
            assert res_stale["ok"] is True, res_stale

            active_src_files = list((rt_root / "sessions" / session_id / "source").glob("*.hwpx"))
            assert len(active_src_files) == 1, active_src_files
            active_src_hwpx = active_src_files[0]

            _mutate_hwpx_source(stale_src_hwpx, tmp_path, "stale-drift.hwpx")
            _mutate_hwpx_source(active_src_hwpx, tmp_path, "active-drift.hwpx")

            stale_apply = _rpc_post(
                base_url,
                token,
                "plan/apply",
                {"planId": stale_plan["planId"], "approvalId": stale_appr["approvalId"]},
            )
            assert stale_apply["ok"] is False and stale_apply["error"]["code"] == "plan_stale", stale_apply

            # UI confirm checks validity -> catches plan_stale and renders re-propose banner
            ack_box.check()
            assert not confirm_btn.is_disabled()
            confirm_btn.click()

            page.wait_for_selector('[data-testid="approval-stale-banner"]', timeout=10000)
            assert confirm_btn.is_disabled()

            page.click('[data-testid="approval-repropose-btn"]')
            page.wait_for_function(
                """(prev) => {
                    const el = document.querySelector('[data-testid="approval-plan-hash"]');
                    const txt = el ? (el.getAttribute('data-full-hash') || '').trim() : '';
                    return /^[0-9a-f]{64}$/.test(txt) && txt !== prev;
                }""",
                arg=plan_hash_before,
                timeout=15000,
            )
            plan_hash_after = page.locator('[data-testid="approval-plan-hash"]').get_attribute("data-full-hash")
            assert plan_hash_after != plan_hash_before

            # Confirm again after re-propose & check ack for newly reproposed plan
            ack_box.wait_for(state="visible", timeout=10000)
            if not ack_box.is_checked():
                ack_box.check()
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-testid=\"approval-confirm-btn\"]'); return b && !b.disabled; }",
                timeout=10000,
            )
            confirm_btn.click()

            # 8) Wait for applied state and verify valid .hwpx ZIP export
            page.wait_for_selector('[data-testid="review-export-btn"]', timeout=25000)
            with page.expect_download(timeout=15000) as dl_info:
                page.click('[data-testid="review-export-btn"]')
            download = dl_info.value
            exported_path = tmp_path / download.suggested_filename
            download.save_as(str(exported_path))
            assert exported_path.is_file() and exported_path.stat().st_size > 1000
            assert zipfile.is_zipfile(exported_path)

            # Capture History screen temp variants after apply & export
            page.click('[data-testid="nav-history"]')
            page.wait_for_selector('[data-testid="history-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="history-node-1"]', timeout=10000)
            _save_screen_variants(page, "history", shots_dir)

            assert not page_errors, f"Uncaught page errors: {page_errors}"
            assert not server_errors, f"HTTP 5xx responses: {server_errors}"
            assert not api_errors, f"Unexpected API 4xx responses: {api_errors}"
            browser.close()
    finally:
        _stop_ui_server(proc)

    for fname in EXPECTED_TEMP_SCREENSHOTS:
        assert (shots_dir / fname).is_file(), f"Missing temp screenshot {fname}"
