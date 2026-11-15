"""End-to-end Playwright verification for Rigorloom WP3 local web UI (`cli.py ui`).

Covers:
1. Clean `pytest.skip` when `playwright` or headless Chromium is unavailable.
2. Live subprocess launch (`cli.py ui --root <tmp> --port 0 --no-open`) with zero
   uncaught `pageerror`s and zero HTTP 5xx / unexpected API errors.
3. Opening a real corpus form (`tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`)
   via the browser open dialog and verifying `session-list`.
4. Korean IME composition safety on `SeatEditor` (`compositionstart` -> `Enter`
   blocked mid-composition -> `compositionupdate`/`compositionend` `"한글"` ->
   `Enter` commits with `composed === true`).
5. Multi-op plan with 4 distinct op kinds (`fill_cell`, `replace_at_cell`, `set_run`,
   `delete_guides`), address + before->after projection, Guard Diff protected
   expression highlights, Approval Dialog (`planHash`), re-approval gate on byte
   drift (both runtime `plan/apply` refusal on an approved plan and UI invalidation +
   re-propose), final `"승인하고 적용"` apply, and verified `.hwpx` export.
6. 16 viewport/theme screenshots in `docs/ui/` (`{session-list,plan-view,guard-diff,approval-dialog}-{1440,390}-{light,dark}.png`) with `scrollWidth <= innerWidth`.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "runtime" / "scripts" / "cli.py"
PREEDIT_PATH = REPO_ROOT / "engine" / "scripts" / "preedit.py"
DOCS_UI_DIR = REPO_ROOT / "docs" / "ui"
CORPUS_FORM_ID = "forms/converted/gianmun-byeolji-1ho.hwpx"

EXPECTED_SCREENSHOTS = [
    f"{screen}-{width}-{theme}.png"
    for screen in ("session-list", "plan-view", "guard-diff", "approval-dialog")
    for width in (1440, 390)
    for theme in ("light", "dark")
]


def _import_playwright():
    """Import Playwright or skip cleanly when unavailable in this Python environment."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip(f"playwright Python package unavailable: {exc}")
    return sync_playwright


def _launch_chromium(pw):
    """Launch headless Chromium or skip cleanly when browser binaries/libs are missing."""
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"headless Chromium unavailable: {exc}")


def _start_ui_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str, Path]:
    """Start `cli.py ui --root <tmp> --port 0 --no-open` and return (proc, url, rt_root)."""
    rt_root = tmp_path / "ui-root"
    xdg_dir = tmp_path / "xdg-data"
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(xdg_dir)
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


def _mutate_hwpx_source(hwpx_path: Path, scratch_dir: Path) -> None:
    """Mutate a valid HWPX file atomically via preedit.py to simulate external byte drift."""
    mutated = scratch_dir / "external-drift.hwpx"
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
    page.wait_for_timeout(120)
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
    """Capture 1440x900 and 390x844 in light and dark themes and validate PNG output."""
    should_sync_docs = os.environ.get("RIGORLOOM_UPDATE_UI_DOCS") == "1"
    DOCS_UI_DIR.mkdir(parents=True, exist_ok=True)
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
            doc_out = DOCS_UI_DIR / fname
            if should_sync_docs or not doc_out.is_file():
                shutil.copy2(out, doc_out)


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

            # 1) Load UI & dismiss splash cleanly
            page.goto(url, wait_until="domcontentloaded")
            splash = page.locator('[data-testid="splash"]')
            if splash.count() > 0:
                splash.first.click(force=True)
            page.wait_for_selector('[data-testid="welcome-open-form"]', timeout=15000)

            # 2) Open real corpus form via browser open dialog & inspect Session List
            page.click('[data-testid="welcome-open-form"]')
            page.wait_for_selector('[data-testid="browser-open-dialog"]', timeout=10000)
            page.click(f'[data-testid="corpus-file-{CORPUS_FORM_ID}"]')
            page.wait_for_selector('[data-testid="session-list"] [data-testid^="session-"]', timeout=15000)
            page.wait_for_selector('[data-testid="doc-cell-0-5-1"]', timeout=15000)
            assert "gianmun-byeolji-1ho.hwpx" in page.locator('[data-testid="session-list"]').inner_text()
            _save_screen_variants(page, "session-list", shots_dir, mobile_tab="mobile-tab-sessions")
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 3) Korean IME check on SeatEditor
            page.click('[data-testid="doc-cell-0-5-1"]')
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
            # Mid-composition Enter must NOT commit early or close SeatEditor
            assert page.locator('[data-testid="seat-input"]').is_visible()
            assert page.locator('[data-testid="review-queue-empty"]').is_visible()

            page.evaluate(
                """() => {
                    const el = document.querySelector('[data-testid="seat-input"]');
                    el.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: '한글' }));
                    el.value = '한글';
                    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '한글' }));
                }"""
            )
            page.keyboard.press("Enter")
            page.wait_for_selector('[data-testid="review-queue"]', timeout=10000)
            assert page.locator(".shell").get_attribute("data-last-composed") == "true"
            assert page.locator(".shell").get_attribute("data-last-commit") == "한글"

            # 4) Queue 3 additional distinct op kinds (4 total: fill_cell, replace_at_cell, set_run, delete_guides)
            page.click('[data-testid="queue-add-op-toggle"]')
            page.wait_for_selector('[data-testid="queue-add-op-form"]', timeout=5000)

            page.select_option('[data-testid="add-op-kind"]', "replace_at_cell")
            coords = page.locator('[data-testid="queue-add-op-form"] .add-op-coords input')
            coords.nth(0).fill("0")
            coords.nth(1).fill("7")
            coords.nth(2).fill("1")
            page.fill('[data-testid="add-op-text"]', "2026년 100만원")
            page.click('[data-testid="add-op-submit"]')
            page.wait_for_function(
                "document.querySelector('[data-testid=\"queue-count\"]')?.textContent?.trim() === '2'",
                timeout=10000,
            )

            page.select_option('[data-testid="add-op-kind"]', "set_run")
            coords = page.locator('[data-testid="queue-add-op-form"] .add-op-coords input')
            coords.nth(0).fill("3")
            coords.nth(1).fill("0")
            page.fill('[data-testid="add-op-text"]', "과학기술정보통신부 2026-11-15")
            page.click('[data-testid="add-op-submit"]')
            page.wait_for_function(
                "document.querySelector('[data-testid=\"queue-count\"]')?.textContent?.trim() === '3'",
                timeout=10000,
            )

            page.select_option('[data-testid="add-op-kind"]', "delete_guides")
            page.locator('[data-testid="queue-add-op-form"] input[placeholder*="#0000FF"]').fill("#0000FF")
            page.click('[data-testid="add-op-submit"]')
            page.wait_for_function(
                "document.querySelector('[data-testid=\"queue-count\"]')?.textContent?.trim() === '4'",
                timeout=10000,
            )
            page.wait_for_selector('[data-testid="queue-verdict"]', timeout=10000)
            page.click('[data-testid="queue-add-op-toggle"]')

            queue_text = page.locator('[data-testid="review-queue"]').inner_text()
            for expected_addr in ("표 0 R5C1", "표 0 R7C1", "도로명주소", "문단 3 · 덩어리 0", "안내문 삭제"):
                assert expected_addr in queue_text, f"Missing {expected_addr!r} in queue"

            op_kinds = set(
                page.evaluate(
                    "() => Array.from(document.querySelectorAll('[data-testid=\"review-queue\"] [data-kind]')).map(el => el.getAttribute('data-kind'))"
                )
            )
            assert op_kinds == {"fill_cell", "replace_at_cell", "set_run", "delete_guides"}, op_kinds

            value_texts = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-testid^=\"queue-value-\"]')).map(el => el.tagName === 'INPUT' ? el.value : el.textContent)"
            )
            for expected_after in ("한글", "2026년 100만원", "과학기술정보통신부 2026-11-15", "(안내문 삭제됨)"):
                assert expected_after in value_texts, f"Missing {expected_after!r} in {value_texts}"

            _save_screen_variants(
                page,
                "plan-view",
                shots_dir,
                mobile_tab="mobile-tab-queue",
                scroll_into_view_selector='[data-testid="review-queue"]',
            )
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 5) Guard Diff panel with highlighted protected expressions & 1-based paragraph headings
            page.click('[data-testid="tab-guard-diff"]')
            page.wait_for_selector('[data-testid="guard-diff-panel"]', timeout=10000)
            page.click('[data-testid="guard-diff-run"]')
            page.wait_for_selector('[data-testid="guard-diff-verdict"]', timeout=10000)
            assert page.locator("mark.guard-token.guard-token--added").count() >= 4
            assert "문단 #3" in page.locator('[data-testid="guard-paragraph-3"]').inner_text()
            _save_screen_variants(page, "guard-diff", shots_dir, mobile_tab="mobile-tab-guard")
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 6) Approval dialog & screenshots
            page.click('[data-testid="request-approval"]')
            page.wait_for_selector('[data-testid="approval-gate"]', timeout=10000)
            page.click('[data-testid="open-approval-dialog"]')
            page.wait_for_selector('[data-testid="approval-dialog"]', timeout=10000)

            plan_id_before = page.locator('[data-testid="dialog-plan-id"]').inner_text().strip()
            plan_hash_before = page.locator('[data-testid="dialog-plan-hash"]').inner_text().strip()
            assert re.fullmatch(r"[0-9a-f]{64}", plan_hash_before), plan_hash_before
            assert page.locator(".dialog-op-row").count() == 4
            _save_screen_variants(page, "approval-dialog", shots_dir, mobile_tab=None)
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 7) Re-approval gate: also prove backend refuses plan/apply on an APPROVED stale plan,
            # AND UI invalidates approval + blocks apply + requires Re-propose!
            bootstrap = page.evaluate("() => window.__RIGORLOOM_UI__")
            token = bootstrap["token"]
            base_url = url.split("?", 1)[0]
            session_files = list((rt_root / "sessions").glob("*/source/*.hwpx"))
            assert len(session_files) == 1, session_files
            src_hwpx = session_files[0]

            # Approve a throwaway competing plan? Even cleaner: propose + resolve("approved")
            # a plan bound to pre-drift bytes, mutate bytes, and confirm runtime refuses plan/apply!
            session_id = src_hwpx.parents[1].name
            prop_res = _rpc_post(
                base_url,
                token,
                "plan/propose",
                {
                    "sessionId": session_id,
                    "backend": "preedit",
                    "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 2, "text": "보조"}],
                },
            )
            assert prop_res["ok"] is True, prop_res
            stale_plan = prop_res["result"]["plan"]
            req_res = _rpc_post(base_url, token, "approval/request", {"planId": stale_plan["planId"]})
            assert req_res["ok"] is True, req_res
            stale_appr = req_res["result"]["approval"]
            res_ok = _rpc_post(
                base_url,
                token,
                "approval/resolve",
                {
                    "approvalId": stale_appr["approvalId"],
                    "planId": stale_plan["planId"],
                    "planHash": stale_plan["planHash"],
                    "decision": "approved",
                    "approver": "playwright-verifier",
                },
            )
            assert res_ok["ok"] is True, res_ok

            # Mutate the session source bytes externally
            _mutate_hwpx_source(src_hwpx, tmp_path)

            # Old already-approved approval must be REFUSED by runtime plan/apply
            stale_apply = _rpc_post(
                base_url,
                token,
                "plan/apply",
                {"planId": stale_plan["planId"], "approvalId": stale_appr["approvalId"]},
            )
            assert stale_apply["ok"] is False and stale_apply["error"]["code"] == "plan_stale", stale_apply

            # Now test the UI dialog re-approval gate: trying to approve/apply detects drift,
            # invalidates the old approval, refuses apply, and displays the re-approval prompt.
            page.click('[data-testid="dialog-approve-apply"]')
            page.wait_for_selector('[data-testid="reapproval-prompt"]', timeout=10000)
            assert page.locator('[data-testid="dialog-approve-apply"]').is_disabled()
            assert "없음" in page.locator('[data-testid="verification-bar"]').inner_text()

            # Re-propose against the new bytes
            page.locator('[data-testid="reapproval-prompt"] button').click()
            page.wait_for_function(
                """(prev) => {
                    const el = document.querySelector('[data-testid="dialog-plan-hash"]');
                    const txt = el ? el.textContent.trim() : '';
                    return /^[0-9a-f]{64}$/.test(txt) && txt !== prev;
                }""",
                arg=plan_hash_before,
                timeout=15000,
            )
            plan_id_after = page.locator('[data-testid="dialog-plan-id"]').inner_text().strip()
            plan_hash_after = page.locator('[data-testid="dialog-plan-hash"]').inner_text().strip()
            assert plan_id_after != plan_id_before
            assert plan_hash_after != plan_hash_before

            # Close dialog to verify ReviewQueue banner cleared, request approval, and click "승인하고 적용"
            page.click('[data-testid="dialog-close"]')
            assert page.locator('[data-testid="queue-reapproval-banner"]').count() == 0
            page.click('[data-testid="request-approval"]')
            page.wait_for_selector('[data-testid="approve"]', timeout=10000)
            assert "승인하고 적용" in page.locator('[data-testid="approve"]').inner_text()
            page.click('[data-testid="approve"]')

            page.wait_for_selector('[data-testid="candidate-hash"]', timeout=20000)
            cand_hash = page.locator('[data-testid="candidate-hash"]').inner_text().strip()
            assert len(cand_hash) >= 8

            # 8) Export candidate and verify valid HWPX ZIP download
            with page.expect_download(timeout=15000) as dl_info:
                page.click('[data-testid="export-candidate"]')
            download = dl_info.value
            exported_path = tmp_path / download.suggested_filename
            download.save_as(str(exported_path))
            assert exported_path.is_file() and exported_path.stat().st_size > 1000
            assert zipfile.is_zipfile(exported_path)

            assert not page_errors, f"Uncaught page errors: {page_errors}"
            assert not server_errors, f"HTTP 5xx responses: {server_errors}"
            assert not api_errors, f"Unexpected API 4xx responses: {api_errors}"
            browser.close()
    finally:
        _stop_ui_server(proc)

    for fname in EXPECTED_SCREENSHOTS:
        assert (shots_dir / fname).is_file(), f"Missing temp screenshot {fname}"
        assert (DOCS_UI_DIR / fname).is_file(), f"Missing docs/ui screenshot {fname}"
