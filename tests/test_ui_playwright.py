"""End-to-end Playwright checks for the editor v2 shell (WP2) served by `cli.py ui`.

Covers the WP2 gates in J1 §5:
1. Start tab: boundary sentence, three actions, sample list; no recents on a
   fresh root; the principle assertions on the chrome.
2. Palette: `Ctrl+K` and the permanent alias `Ctrl+Shift+P`; `Esc` closes.
3. Keys and IME: nothing fires while composing; single keys typed into an
   input stay text.
4. Document isolation: changes proposed for document A never show on
   document B's tab or status bar; B's pane choice is its own.
5. Eight tabs overflow into the tab list; a corrupt file opens as a failed tab
   that keeps its file name.
6. 1280: only one side docks; opening the left pane hides the right panel.
7. Budgets from performance measures (and a Chromium trace when
   `RIGORLOOM_TRACE_DIR` is set): palette open under 50 ms, cached tab switch
   under 100 ms.
8. Screenshots of the states above under `tmp_path` only.

The served bundle is `runtime/scripts/ui_dist`, rebuilt by the integrator per
merge. A bundle from before the shell is skipped with that reason.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from urllib.parse import urlsplit

from _browser_gate import no_browser
from _editor_v2 import editor_v2_url
from _v1_identity import launch_browser, start_bridge

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "runtime" / "scripts" / "cli.py"
UI_DIST = REPO_ROOT / "runtime" / "scripts" / "ui_dist"

HEX13 = re.compile(r"[0-9a-f]{13,}")


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        no_browser(f"playwright Python package unavailable: {exc}")
    return sync_playwright


def _launch_chromium(pw):
    try:
        return launch_browser(pw)
    except Exception as exc:  # pragma: no cover - environment dependent
        no_browser(f"headless Chromium unavailable: {exc}")


def _bundle_has_shell() -> bool:
    assets = UI_DIST / "assets"
    if not assets.is_dir():
        return False
    return any("sh-root" in p.read_text(encoding="utf-8", errors="ignore") for p in assets.glob("*.css"))


def _start_ui_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str]:
    rt_root = tmp_path / "ui-root"
    xdg_dir = tmp_path / "xdg"
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(xdg_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(CLI_PATH), "ui", "--root", str(rt_root), "--port", "0", "--no-open"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    url = None
    deadline = time.monotonic() + 30.0
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
    return proc, url


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
    req = urllib.request.Request(
        base_url.rstrip("/") + "/rpc",
        data=json.dumps({"method": method, "params": params}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Rigorloom-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


PRINCIPLES_JS = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const out = {primary: 0, shadowDocked: [], fonts: new Set(), weights: new Set(), radius: [], hex: []};
  for (const el of document.querySelectorAll('[data-variant=primary]')) if (visible(el)) out.primary += 1;
  for (const el of document.querySelectorAll('[data-docked]')) {
    const s = getComputedStyle(el).boxShadow;
    if (s && s !== 'none') out.shadowDocked.push(el.className);
  }
  const chrome = document.querySelector('[data-testid=shell]');
  for (const el of chrome.querySelectorAll('*')) {
    if (el.closest('[data-testid=paper]') || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (hasText) {
      out.fonts.add(cs.fontSize);
      out.weights.add(cs.fontWeight);
      const m = el.textContent.match(/[0-9a-f]{13,}/);
      if (m) out.hex.push(m[0]);
    }
    for (const k of ['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomLeftRadius', 'borderBottomRightRadius']) {
      const v = parseFloat(cs[k]);
      if (v > 6) out.radius.push(el.className + ':' + v);
    }
  }
  return {primary: out.primary, shadowDocked: out.shadowDocked, fonts: [...out.fonts], weights: [...out.weights], radius: out.radius.slice(0, 5), hex: out.hex};
}
"""


def _assert_principles(page, where: str) -> None:
    res = page.evaluate(PRINCIPLES_JS)
    assert res["primary"] <= 1, (where, res)
    assert res["shadowDocked"] == [], (where, res)
    assert set(res["fonts"]) <= {"9px", "10px", "11px", "11.5px", "12px", "12.5px", "13px", "14px", "15px", "16px", "20px"}, (where, res["fonts"])
    assert set(res["weights"]) <= {"400", "600"}, (where, res["weights"])
    assert res["radius"] == [], (where, res["radius"])
    assert res["hex"] == [], (where, res["hex"])


def _measure(page, name: str) -> float:
    return page.evaluate(
        "(n) => { const e = performance.getEntriesByName(n, 'measure'); return e.length ? e[e.length - 1].duration : -1; }",
        name,
    )


def _open_sample(page, index: int) -> str:
    """Open a sample from a Start tab and return the new session id."""
    if page.locator('[data-testid="start"]').count() == 0:
        page.click('[data-testid="tab-add"]')
        page.wait_for_selector('[data-testid="start"]')
    before = page.evaluate("[...document.querySelectorAll('[data-tab-id^=\"doc:\"]')].map(e => e.dataset.tabId)")
    page.click(f'[data-testid="start-sample-{index}"]')
    page.wait_for_function(
        "(before) => { const ids = [...document.querySelectorAll('[data-tab-id^=\"doc:\"]')].map(e => e.dataset.tabId); return ids.some(i => !before.includes(i)) && document.querySelector('[data-testid=strip-host]'); }",
        arg=before,
        timeout=60000,
    )
    after = page.evaluate("[...document.querySelectorAll('[data-tab-id^=\"doc:\"]')].map(e => e.dataset.tabId)")
    new = [t for t in after if t not in before]
    return new[0].split(":", 1)[1]


def test_ui_default_url_with_empty_prefs_opens_editor_v2_shell(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    prefs_path = tmp_path / "prefs.json"
    prefs_path.write_text("{}\n", encoding="utf-8")
    server, thread = start_bridge(tmp_path)
    try:
        assert json.loads(prefs_path.read_text(encoding="utf-8")) == {}
        assert urlsplit(server.url).query == ""
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(server.url, wait_until="domcontentloaded")
            page.wait_for_selector(
                '[data-testid="shell"], [data-testid="open-view"], [data-testid="splash"]',
                timeout=30000,
            )
            splash = page.locator('[data-testid="splash"]')
            if splash.count() > 0:
                try:
                    splash.first.click(force=True, timeout=3000)
                except Exception:
                    pass
            page.wait_for_selector('[data-testid="shell"], [data-testid="open-view"]', timeout=30000)
            assert page.locator('[data-testid="shell"]').count() == 1
            assert page.locator('[data-testid="start"]').count() == 1
            assert page.locator('[data-testid="open-view"]').count() == 0
            assert page.evaluate("document.documentElement.dataset.ui") == "v2"
            assert page_errors == [], page_errors
            context.close()
            browser.close()
    finally:
        server.shutdown_bridge()
        thread.join(timeout=5)


def test_ui_settings_editor_variant_roundtrip_and_unsaved_refusal(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    prefs_path = tmp_path / "prefs.json"
    prefs_path.write_text("{}\n", encoding="utf-8")
    server, thread = start_bridge(tmp_path)
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            page.goto(server.url, wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="shell"]', timeout=30000)
            assert page.evaluate("document.documentElement.dataset.ui") == "v2"

            # 1) Open 설정 in v2 and check the 편집기 row shows 새 편집기 selected.
            page.keyboard.press("Control+Comma")
            dialog = page.get_by_test_id("settings-dialog")
            dialog.wait_for(timeout=10000)
            editor_seg = dialog.get_by_test_id("settings-editor")
            editor_seg.wait_for(timeout=10000)
            v2_btn = dialog.get_by_test_id("settings-editor-v2")
            v1_btn = dialog.get_by_test_id("settings-editor-v1")
            assert v2_btn.inner_text().strip() == "새 편집기"
            assert v2_btn.get_attribute("aria-checked") == "true"
            assert v1_btn.inner_text().strip() == "이전 화면 (v1)"
            assert v1_btn.get_attribute("aria-checked") == "false"
            note_el = dialog.get_by_test_id("settings-editor-note")
            assert note_el.is_visible()
            assert "이전 화면" in note_el.inner_text()
            page.keyboard.press("Escape")
            page.wait_for_selector('[data-testid="settings-dialog"]', state="detached")

            # 2) With a draft save in flight, the switch is refused with the existing note.
            _open_sample(page, 0)
            page.wait_for_selector('[data-cell-key="c:0:5:1"]', timeout=20000)
            page.evaluate(
                """() => {
                    const origFetch = window.fetch.bind(window);
                    window.__draftSaveInFlight = false;
                    window.__releaseDraftSave = null;
                    window.fetch = (...args) => {
                        const [url, init] = args;
                        if (
                            String(url).includes("/api/prefs") &&
                            init &&
                            init.method === "POST" &&
                            String(init.body || "").includes('"drafts"')
                        ) {
                            window.__draftSaveInFlight = true;
                            return new Promise((resolve) => {
                                window.__releaseDraftSave = () => {
                                    window.fetch = origFetch;
                                    resolve(origFetch(...args));
                                };
                            });
                        }
                        return origFetch(...args);
                    };
                }"""
            )
            page.click('[data-cell-key="c:0:5:1"]')
            page.wait_for_selector('[data-testid="seat-input"]', timeout=10000)
            page.locator('[data-testid="seat-input"]').fill("한글")
            page.locator('[data-testid="seat-input"]').press("Enter")
            page.wait_for_function("() => window.__draftSaveInFlight === true", timeout=10000)

            page.keyboard.press("Control+Comma")
            dialog.wait_for(timeout=10000)
            dialog.get_by_test_id("settings-editor-v1").click()
            page.wait_for_timeout(200)
            assert page.locator('[data-testid="shell"]').count() == 1
            assert page.evaluate("document.documentElement.dataset.ui") == "v2"
            assert json.loads(prefs_path.read_text(encoding="utf-8")).get("editorVariant") is None
            refusal_notice = page.locator('[data-testid="status-canvas-notice"]').inner_text().strip()
            assert refusal_notice == "입력 중이거나 아직 저장되지 않은 작업을 먼저 마치세요", refusal_notice
            # The dialog covers the canvas status line, so the row says it too.
            refused_el = dialog.get_by_test_id("settings-editor-refused")
            refused_el.wait_for(timeout=5000)
            assert refused_el.inner_text().strip() == "입력 중이거나 아직 저장되지 않은 작업을 먼저 마치세요"

            # Release the in-flight draft save and wait for the queued change to settle.
            page.evaluate("() => { if (window.__releaseDraftSave) window.__releaseDraftSave(); }")
            page.wait_for_selector('[data-testid="change-row-1"]', timeout=20000)
            page.wait_for_timeout(200)

            # 3) Choose 이전 화면 in v2 설정 and check the v1 shell loads and prefs hold editorVariant: "v1".
            dialog.get_by_test_id("settings-editor-v1").click()
            page.wait_for_selector('[data-testid="open-view"], [data-testid="review-view"], [data-testid="splash"]', timeout=30000)
            splash = page.locator('[data-testid="splash"]')
            if splash.count() > 0:
                try:
                    splash.first.click(force=True, timeout=3000)
                except Exception:
                    pass
            page.wait_for_selector('[data-testid="open-view"], [data-testid="review-view"]', timeout=30000)
            assert page.evaluate("document.documentElement.dataset.ui") == "v1"
            assert json.loads(prefs_path.read_text(encoding="utf-8")).get("editorVariant") == "v1"

            # 4) In v1 설정 choose 새 편집기 and check v2 loads again.
            page.click('[data-testid="open-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=15000)
            v1_settings_editor = page.get_by_test_id("settings-editor")
            v1_settings_editor.wait_for(timeout=10000)
            assert page.get_by_test_id("settings-editor-v1").get_attribute("aria-pressed") == "true"
            assert page.get_by_test_id("settings-editor-v2").get_attribute("aria-pressed") == "false"
            page.get_by_test_id("settings-editor-v2").click()
            page.wait_for_selector('[data-testid="shell"]', timeout=30000)
            assert page.evaluate("document.documentElement.dataset.ui") == "v2"
            assert json.loads(prefs_path.read_text(encoding="utf-8")).get("editorVariant") == "v2"

            assert page_errors == [], page_errors
            context.close()
            browser.close()
    finally:
        server.shutdown_bridge()
        thread.join(timeout=5)


def test_ui_shell_e2e_keys_isolation_tabs_and_budgets(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    if not _bundle_has_shell():
        no_browser("runtime/scripts/ui_dist predates the v2 shell; rebuild with `npm run build:web`")

    shots = tmp_path / "shots"
    shots.mkdir()
    proc, base_url = _start_ui_server(tmp_path)
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page = context.new_page()
            page_errors: list[str] = []
            server_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("response", lambda r: server_errors.append(f"{r.status} {r.url}") if r.status >= 500 else None)

            trace_dir = os.environ.get("RIGORLOOM_TRACE_DIR")
            page.goto(editor_v2_url(base_url))
            page.wait_for_selector('[data-testid="shell"]', timeout=60000)
            token = page.evaluate("window.__RIGORLOOM_UI__.token")

            # 1) Start on a fresh root.
            start = page.locator('[data-testid="start"]')
            start.wait_for()
            assert page.locator('[data-testid="start-open-file"]').is_visible()
            assert page.locator('[data-testid="start-open-folder"]').is_visible()
            assert page.get_by_test_id("start-samples").get_by_role("heading").is_visible()
            assert page.get_by_test_id("start-filter").is_visible()
            assert page.locator('[data-testid="titlebar"] button kbd').count() == 0
            assert page.get_by_test_id("palette-field").get_attribute("title").endswith("Ctrl+K")
            assert page.locator('[data-testid="start-recent"]').count() == 0
            page.wait_for_selector('[data-testid="start-sample-0"]', timeout=30000)
            assert page.title() == "Rigorloom"
            _assert_principles(page, "start")
            page.screenshot(path=str(shots / "start-empty-1440-light.png"))
            launcher_filter = page.get_by_test_id("start-filter")
            launcher_filter.fill("gianmun-byeolji-1ho")
            assert page.get_by_test_id("start-sample-list").get_by_role("button").count() == 1
            assert page.locator('[data-file="gianmun-byeolji-1ho.hwpx"]').is_visible()
            launcher_filter.clear()
            launcher_filter.blur()

            # 2) Palette: Ctrl+Shift+P and Ctrl+K; Esc closes. Budget: open under 50 ms.
            page.keyboard.press("Control+Shift+P")
            page.wait_for_selector('[data-testid="palette"]')
            page.keyboard.press("Escape")
            page.wait_for_selector('[data-testid="palette"]', state="detached")
            if trace_dir:
                browser.start_tracing(page=page, path=str(Path(trace_dir) / "wp2-budgets-trace.json"), categories=["devtools.timeline", "blink.user_timing"])
            palette_ms = []
            for _ in range(7):
                page.keyboard.press("Control+K")
                page.wait_for_selector('[data-testid="palette"]')
                palette_ms.append(_measure(page, "palette-open"))
                page.keyboard.press("Escape")
                page.wait_for_selector('[data-testid="palette"]', state="detached")
            assert min(palette_ms) >= 0, palette_ms
            assert statistics.median(palette_ms) < 50, palette_ms

            # 3) IME: a composing Ctrl+K opens nothing; letters typed in an input stay text.
            page.evaluate(
                """() => window.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyK', key: 'Process', ctrlKey: true, isComposing: true, bubbles: true}))"""
            )
            page.evaluate(
                """() => window.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyK', key: 'Process', ctrlKey: true, keyCode: 229, bubbles: true}))"""
            )
            page.wait_for_timeout(100)
            assert page.locator('[data-testid="palette"]').count() == 0
            page.keyboard.press("Control+K")
            inp = page.locator('[data-testid="palette-input"]')
            inp.type("jkynreuv")
            assert inp.input_value() == "jkynreuv"
            assert page.locator('[data-testid="palette"]').count() == 1
            page.keyboard.press("Escape")

            # 4) Two documents. Pane choice and changes stay with their document.
            sid_a = _open_sample(page, 0)
            assert re.fullmatch(r".+ — Rigorloom", page.title()), page.title()
            assert page.locator(f'[data-testid="tab-{sid_a}"]').get_attribute("aria-selected") == "true"
            page.click('[data-testid="pane-tab-find"]')
            ops = [
                {"opId": "op-a1", "kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한글"},
                {"opId": "op-a2", "kind": "replace_at_cell", "table": 0, "row": 6, "col": 0, "text": "공고 2026년"},
            ]
            prop = _rpc_post(base_url, token, "plan/propose", {"sessionId": sid_a, "backend": "preedit", "ops": ops})
            assert prop["ok"] is True, prop
            # The panel (WP4) adopts an external plan into the document's draft.
            # Without it nothing is adopted, and A's count is not asserted.
            panel_present = page.locator('[data-testid="right-panel-host"] [data-slot-empty]').count() == 0
            if panel_present:
                page.wait_for_selector(f'[data-testid="tab-{sid_a}"] .sh-tab-count', timeout=30000)
                assert int(page.locator(f'[data-testid="tab-{sid_a}"] .sh-tab-count').inner_text()) >= 1

            sid_b = _open_sample(page, 3)
            assert sid_b != sid_a
            assert page.locator(f'[data-testid="tab-{sid_b}"] .sh-tab-count').count() == 0
            assert page.locator('[data-testid="status-changes"]').count() == 0
            assert page.locator('[data-testid="pane-tab-find"]').get_attribute("aria-selected") == "false"
            # A keeps its own pane and its count.
            page.click(f'[data-testid="tab-{sid_a}"]')
            page.wait_for_function(
                "(sid) => document.querySelector('.shell-v2')?.dataset.session === sid", arg=sid_a, timeout=30000
            )
            assert page.locator('[data-testid="pane-tab-find"]').get_attribute("aria-selected") == "true"
            if panel_present:
                assert page.locator(f'[data-testid="tab-{sid_a}"] .sh-tab-count').count() == 1
            _assert_principles(page, "document")
            page.screenshot(path=str(shots / "doc-1440-light.png"))

            # Budget: cached tab switch under 100 ms (click to committed frame).
            switch_ms = []
            for i in range(8):
                target = sid_b if i % 2 == 0 else sid_a
                page.click(f'[data-testid="tab-{target}"]')
                page.wait_for_function(
                    "(sid) => document.querySelector('.shell-v2')?.dataset.session === sid", arg=target, timeout=30000
                )
                switch_ms.append(_measure(page, "tab-switch"))
            if trace_dir:
                browser.stop_tracing()
            assert min(switch_ms) >= 0, switch_ms
            assert statistics.median(switch_ms) < 100, switch_ms

            # 5) Eight tabs overflow into the tab list.
            for idx in (1, 2, 4, 5, 6, 7):
                _open_sample(page, idx)
            assert page.locator('[data-tab-id^="doc:"]').count() == 8
            # The document controls share the title bar and the overflow menu tracks the available width.
            overflows = page.get_by_test_id("tabbar").evaluate("el => el.scrollWidth > el.clientWidth + 1")
            assert page.get_by_test_id("tab-list").count() == int(overflows)
            assert page.get_by_test_id("tabbar").get_by_role("tab", selected=True).is_visible()
            assert page.get_by_test_id("titlebar").get_by_test_id("strip-host").is_visible()
            page.screenshot(path=str(shots / "tabs-eight-1440-light.png"))
            # At 900 they overflow into the tab list, which names every tab.
            page.set_viewport_size({"width": 900, "height": 800})
            page.wait_for_selector('[data-testid="tab-list"]', timeout=5000)
            page.click('[data-testid="tab-list"]')
            assert page.locator('[data-testid="tab-list-menu"] [role=menuitem]').count() >= 8
            page.screenshot(path=str(shots / "tabs-overflow-900-light.png"))
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": 1440, "height": 900})

            # A corrupt file opens as a failed tab that keeps its name.
            page.click('[data-testid="tab-add"]')
            page.wait_for_selector('[data-testid="start"]')
            bad = tmp_path / "깨진 문서.hwpx"
            bad.write_bytes(b"PK\x03\x04 not really a zip")
            with page.expect_file_chooser() as chooser:
                page.click('[data-testid="start-open-file"]')
            chooser.value.set_files(str(bad))
            page.wait_for_selector('[data-testid="doc-failed"]', timeout=30000)
            failed_tab = page.locator('[data-kind="failed"][aria-selected="true"]')
            assert "깨진 문서" in failed_tab.inner_text()
            page.click('[data-testid="doc-failed-details"]')
            page.wait_for_selector('[data-testid="doc-failed-detail"]')
            page.screenshot(path=str(shots / "failed-tab-1440-light.png"))

            # 6) 1280: one side docked. Right by default; Alt+1 docks the left and hides the right.
            page.click(f'[data-testid="tab-{sid_a}"]')
            page.set_viewport_size({"width": 1280, "height": 800})
            page.wait_for_function("document.querySelector('[data-testid=shell]').dataset.breakpoint === 'medium'")
            assert page.locator('[data-testid="right-panel-host"]').is_visible()
            assert page.locator('[data-testid="left-pane"]').count() == 0
            page.keyboard.press("Alt+1")
            page.wait_for_selector('[data-testid="left-pane"]')
            assert page.locator('[data-testid="right-panel-host"]').is_hidden()
            page.screenshot(path=str(shots / "doc-1280-left-light.png"))
            if panel_present:
                page.click('[data-testid="status-changes"]')
            else:
                page.click('[data-testid="toggle-right"]')
            page.wait_for_selector('[data-testid="right-panel-host"]')
            assert page.locator('[data-testid="left-pane"]').count() == 0

            # 390: narrow frame, no horizontal overflow.
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("document.querySelector('[data-testid=shell]').dataset.breakpoint === 'narrow'")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(shots / "doc-390-light.png"))

            assert page_errors == [], page_errors
            assert server_errors == [], server_errors
            print(json.dumps({"palette_open_ms": palette_ms, "tab_switch_ms": switch_ms}))
            context.close()
            browser.close()
    finally:
        _stop_ui_server(proc)
