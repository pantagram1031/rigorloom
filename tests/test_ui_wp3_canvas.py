"""Playwright UI verification & screenshot suite for WP3 (Page canvas & editing).

Requires:
  - Vite dev/preview server serving `desktop/src/canvas/harness.html`
  - Live `rigorloom ui` backend for real HWPX `/rpc` typeface & SeatEditor gates

Run:
  pytest tests/test_ui_wp3_canvas.py -v

Screenshots go to RL_WP3_SHOTS_DIR, or desktop/scripts/_run/wp3-shots.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from _browser_gate import no_browser  # noqa: E402

try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError as _exc:  # pragma: no cover - environment dependent
    no_browser(f"playwright Python package unavailable: {_exc}", module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = REPO_ROOT / "desktop"
SHOTS_DIR = Path(os.environ.get("RL_WP3_SHOTS_DIR") or (DESKTOP_ROOT / "scripts" / "_run" / "wp3-shots"))
BRIDGE_TOKEN = "wp3-canvas-test-token"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from runtime.scripts.rt_ui import create_bridge_server  # noqa: E402

# Exact J1 §4 token definitions injected when running in pre-WP1a worktree
J1_TOKENS_CSS = """
:root {
  --font-sans: "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Malgun Gothic", system-ui, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, "Cascadia Mono", monospace;
  --text-xs: 11px; --lh-xs: 14px;
  --text-sm: 12px; --lh-sm: 16px;
  --text-base: 13px; --lh-base: 18px;
  --text-lg: 15px; --lh-lg: 22px;
  --text-display: 20px; --lh-display: 28px;
  --weight-regular: 400; --weight-semibold: 600;
  --leading-ui: 1.4;
  --font-page-serif: "함초롬바탕", "HCR Batang", "한컴바탕", "바탕", Batang, "Nanum Myeongjo", NanumMyeongjo, "Noto Serif CJK KR", serif;
  --font-page-sans: "함초롬돋움", "HCR Dotum", "맑은 고딕", "Malgun Gothic", "Nanum Gothic", NanumGothic, "Noto Sans CJK KR", sans-serif;
  --page-w: 793.7px; --page-h: 1122.5px;
  --page-pt: 1.3333px;
  --page-size-default: 10pt; --page-leading-default: 1.6;
  --s-4: 4px; --s-8: 8px; --s-12: 12px; --s-16: 16px; --s-24: 24px; --s-32: 32px; --s-48: 48px; --s-64: 64px;
  --h-titlebar: 36px; --h-strip: 32px; --h-tabrow: 32px; --h-status: 24px;
  --row-tree: 28px; --row: 32px; --row-change: 52px;
  --ctl: 28px; --ctl-lg: 32px; --ctl-touch: 44px;
  --w-left: 240px; --w-right: 360px;
  --radius-0: 0; --radius-sm: 4px; --radius-md: 6px;
  --divider: 1px;
  --border-hair: 1px solid var(--line);
  --border-strong-line: 1px solid var(--line-strong);
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --dur-pop: 120ms; --dur-panel: 160ms; --dur-scroll: 180ms;
  --dur-mark-in: 240ms; --dur-mark-dry: 400ms; --dur-splash: 700ms;
  --focus-width: 2px; --focus-offset: 1px;
  --paper: #FFFFFF; --paper-ink: #111111; --seat: #F5F2E8;
  --mark-insert: #2A48A4; --mark-insert-tint: rgba(42, 72, 164, .10);
  --mark-delete: #2A48A4; --mark-delete-text: #66696F;
  --mark-accepted: #1B1B1A;
  --mark-fact: #B4232A; --mark-fact-tint: rgba(180, 35, 42, .10);
  --mark-test: #B8860B; --mark-test-tint: rgba(217, 162, 27, .18);
  --mark-stale: #B8860B;
  --mark-rejected: #CCC9C1;
  --mark-selected-tint: rgba(42, 72, 164, .16);
  --focus-paper: #2A48A4;
}
:root, :root[data-theme="light"] {
  --desk: #DEDCD5; --chrome: #ECEBE7; --panel: #F4F3F0; --field: #FBFBF9; --raised: #FFFFFF;
  --ink: #1B1B1A; --on-ink: #FFFFFF;
  --text-2: #45443F; --text-3: #605E58; --text-disabled: #A3A099;
  --line: #E0DED8; --line-strong: #CCC9C1; --line-control: #86847D;
  --hover: rgba(27, 27, 26, .05); --selected: rgba(27, 27, 26, .08);
  --accent: #2A48A4; --accent-tint: #E7EBF6; --accent-line: #BFC9E8;
  --focus: var(--accent);
  --fact: #B4232A; --fact-tint: #FBE9E9;
  --attn: #7A4F00; --attn-tint: #FAF0DC; --attn-line: #B8860B;
  --expected: #45443F; --expected-tint: #E8E7E2;
  --paper-veil: transparent;
  --shadow-paper: 0 0 0 1px rgba(27, 27, 26, .08), 0 1px 2px rgba(27, 27, 26, .06), 0 8px 24px rgba(27, 27, 26, .08);
  --shadow-float: 0 0 0 1px rgba(27, 27, 26, .06), 0 8px 28px rgba(27, 27, 26, .14);
}
:root[data-theme="dark"] {
  --desk: #0B0C0D; --chrome: #0F1012; --panel: #141518; --field: #1B1C20; --raised: #222327;
  --ink: #ECEBE7; --on-ink: #141518;
  --text-2: #C2C0BA; --text-3: #96948E; --text-disabled: #5F5D58;
  --line: #26272B; --line-strong: #36373D; --line-control: #74757C;
  --hover: rgba(236, 235, 231, .06); --selected: rgba(236, 235, 231, .10);
  --accent: #9FB4F0; --accent-tint: #1A2340; --accent-line: #33457A;
  --fact: #F0787C; --fact-tint: #3A1719;
  --attn: #E8B867; --attn-tint: #2E240F; --attn-line: #B98A1E;
  --expected: #C2C0BA; --expected-tint: #2A2B30;
  --paper-veil: rgba(0, 0, 0, .06);
  --shadow-paper: 0 0 0 1px rgba(255, 255, 255, .06);
  --shadow-float: 0 0 0 1px rgba(255, 255, 255, .08), 0 16px 40px rgba(0, 0, 0, .55);
}
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status < 500:
                    return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError(f"Server did not become ready: {url}")


@pytest.fixture(scope="module")
def servers(tmp_path_factory: pytest.TempPathFactory):
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    vite_port = _free_port()

    vite_proc = subprocess.Popen(
        [
            str(DESKTOP_ROOT / "node_modules" / ".bin" / "vite"),
            "--host",
            "127.0.0.1",
            "--port",
            str(vite_port),
            "--strictPort",
        ],
        cwd=str(DESKTOP_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    tmp_root = tmp_path_factory.mktemp("wp3-runtime-root")
    bridge_server = create_bridge_server(
        root=tmp_root,
        port=0,
        token=BRIDGE_TOKEN,
        explicit_root=True,
        auto_start=True,
    )
    bridge_port = bridge_server.server_port
    bridge_thread = threading.Thread(target=bridge_server.serve_forever, daemon=True)
    bridge_thread.start()

    try:
        _wait_http(f"http://127.0.0.1:{vite_port}/src/canvas/harness.html", timeout=25.0)
        # Ensure sidecar runtime is initialized before live Playwright test
        bridge_server.bridge.runtime_start({"root": str(tmp_root)})
    except Exception:
        vite_proc.terminate()
        bridge_server.shutdown()
        bridge_server.server_close()
        raise

    yield {
        "base_url": f"http://127.0.0.1:{vite_port}/src/canvas/harness.html",
        "bridge_base": f"http://127.0.0.1:{bridge_port}",
    }

    vite_proc.terminate()
    vite_proc.wait(timeout=5)
    try:
        bridge_server.bridge.sidecar.stop()
    except Exception:
        pass
    bridge_server.shutdown()
    bridge_server.server_close()


def _launch_browser(p):
    pw_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or (Path.home() / ".cache" / "ms-playwright"))
    candidates = [
        pw_root / "chromium_headless_shell-1248" / "chrome-headless-shell-linux-arm64" / "chrome-headless-shell",
        pw_root / "chromium-1248" / "chrome-linux-arm64" / "chrome",
    ]
    exec_path = next((str(c) for c in candidates if c.is_file()), None)
    kwargs: dict[str, Any] = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    if exec_path:
        kwargs["executable_path"] = exec_path
    return p.chromium.launch(**kwargs)


def _open_scenario(
    page,
    base_url: str,
    scenario: str,
    theme: str = "light",
    width: int = 1440,
    height: int = 900,
    extra: str = "",
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    url = f"{base_url}?scenario={scenario}&theme={theme}{extra}"
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector('[data-testid="canvas-pane"]')
    has_paper_var = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()"
    )
    if not has_paper_var:
        page.add_style_tag(content=J1_TOKENS_CSS)
    page.wait_for_timeout(120)


def _assert_j1_principles(page, *, check_chrome_periods: bool = True) -> None:
    report = page.evaluate(
        r"""(checkPeriods) => {
          const out = { errors: [] };
          const paper = document.querySelector('[data-testid="paper"]');
          if (!paper) {
            out.errors.push("missing paper element");
            return out;
          }
          const paperCs = getComputedStyle(paper);
          if (paperCs.backgroundColor !== "rgb(255, 255, 255)") {
            out.errors.push(`paper bg expected rgb(255, 255, 255), got ${paperCs.backgroundColor}`);
          }
          if (paperCs.borderRadius !== "0px") {
            out.errors.push(`paper borderRadius expected 0px, got ${paperCs.borderRadius}`);
          }

          // Paper font must never resolve to Pretendard
          const paperNodes = [paper, ...paper.querySelectorAll('*')];
          for (const el of paperNodes) {
            const ff = getComputedStyle(el).fontFamily;
            if (/pretendard/i.test(ff)) {
              out.errors.push(`Pretendard leaked into paper fontFamily: ${ff}`);
              break;
            }
          }

          // Inserted text glyphs stay --paper-ink (#111111)
          const insEls = paper.querySelectorAll('ins.rl-ins');
          for (const ins of insEls) {
            const col = getComputedStyle(ins).color;
            if (col !== "rgb(17, 17, 17)") {
              out.errors.push(`ins glyph color expected rgb(17, 17, 17), got ${col}`);
              break;
            }
          }

          // At most 1 visible [data-variant="primary"]
          const primaries = [...document.querySelectorAll('[data-variant="primary"]')].filter(
            (el) => el.offsetParent !== null,
          );
          if (primaries.length > 1) {
            out.errors.push(`expected <= 1 visible primary button, got ${primaries.length}`);
          }

          // Zero box-shadow on [data-docked]
          for (const docked of document.querySelectorAll('[data-docked]')) {
            if (docked.offsetParent === null) continue;
            const bs = getComputedStyle(docked).boxShadow;
            if (bs && bs !== "none") {
              out.errors.push(`docked element has non-none boxShadow: ${bs}`);
            }
          }

          // No visible hash [0-9a-f]{13,}
          const bodyText = document.body.innerText || "";
          const hashMatch = bodyText.match(/[0-9a-f]{13,}/);
          if (hashMatch) {
            out.errors.push(`hex hash leaked into visible UI: ${hashMatch[0]}`);
          }

          // Chrome font sizes in {11,12,13,15,20} & weights in {400,600} & radius <= 6
          const allowedSizes = new Set([11, 12, 13, 15, 20]);
          const allowedWeights = new Set(["400", "600"]);
          const chromeEls = document.querySelectorAll(
            '.rl-harness-titlebar *, .rl-harness-left *, .rl-harness-right *, .rl-harness-statusbar *, .rl-doc-strip *, .rl-margin-gutter *, .rl-mark-toolbar *'
          );
          for (const el of chromeEls) {
            if (el.offsetParent === null) continue;
            const cs = getComputedStyle(el);
            const px = Math.round(parseFloat(cs.fontSize));
            if (!allowedSizes.has(px)) {
              out.errors.push(`chrome font-size ${px}px not in {11,12,13,15,20} on ${el.className}`);
              break;
            }
            if (!allowedWeights.has(cs.fontWeight)) {
              out.errors.push(`chrome font-weight ${cs.fontWeight} not in {400,600} on ${el.className}`);
              break;
            }
            const r = parseFloat(cs.borderTopLeftRadius);
            if (r > 6.1) {
              out.errors.push(`chrome radius ${r}px > 6 on ${el.className}`);
              break;
            }
          }

          // No UI chrome text ending in 다. in default scenario (exclude document text excerpts/snippets)
          if (checkPeriods) {
            const chromeRoots = document.querySelectorAll(
              '.rl-harness-titlebar, .rl-harness-pane-tabs, .rl-pane-header, .rl-pane-group-hdr, .rl-harness-statusbar, .rl-doc-strip, .rl-blank-label, .rl-blank-loc, .rl-blanks-group-toggle'
            );
            for (const root of chromeRoots) {
              if (root.offsetParent === null) continue;
              const txt = (root.innerText || "").trim();
              if (/다\.(?:\s|$)/.test(txt)) {
                out.errors.push(`chrome text ends with 다.: ${txt.slice(0, 80)}`);
              }
            }
          }
          return out;
        }""",
        check_chrome_periods,
    )
    assert not report["errors"], f"J1 principle violations: {report['errors']}"


def _assert_contrast_pairs(page) -> None:
    """Verify >= 4.5:1 contrast for key WP3 chrome & margin-over-white-paper text."""
    results = page.evaluate(
        """() => {
          function parseRgb(str) {
            const m = /rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/.exec(str);
            if (!m) return null;
            return { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] };
          }
          function blend(fg, bg) {
            return {
              r: Math.round(fg.r * fg.a + bg.r * (1 - fg.a)),
              g: Math.round(fg.g * fg.a + bg.g * (1 - fg.a)),
              b: Math.round(fg.b * fg.a + bg.b * (1 - fg.a)),
              a: 1,
            };
          }
          function relLum({r, g, b}) {
            const f = (c) => {
              const s = c / 255;
              return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
            };
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          }
          function contrast(a, b) {
            const l1 = relLum(a), l2 = relLum(b);
            return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
          }
          const checks = [];
          const paperBg = { r: 255, g: 255, b: 255, a: 1 };
          for (const el of document.querySelectorAll('.rl-margin-mark')) {
            if (el.offsetParent === null) continue;
            const cs = getComputedStyle(el);
            const fg = parseRgb(cs.color);
            let bg = parseRgb(cs.backgroundColor);
            if (!fg || !bg) continue;
            bg = bg.a === 0 ? paperBg : blend(bg, paperBg);
            checks.push({ selector: el.className, ratio: contrast(fg, bg) });
          }
          for (const el of document.querySelectorAll('.rl-mark-toolbar-btn, .rl-seg-btn')) {
            if (el.offsetParent === null) continue;
            const cs = getComputedStyle(el);
            const fg = parseRgb(cs.color);
            let bg = parseRgb(cs.backgroundColor);
            if (!fg || !bg) continue;
            if (bg.a === 0) {
              const parentBg = parseRgb(getComputedStyle(el.parentElement).backgroundColor) || { r: 244, g: 243, b: 240, a: 1 };
              bg = parentBg;
            }
            checks.push({ selector: el.className, ratio: contrast(fg, bg) });
          }
          return checks;
        }"""
    )
    low = [c for c in results if c["ratio"] < 4.49]
    assert not low, f"Low contrast elements (< 4.5:1): {low}"


def test_default_workspace_viewports_and_view_switch(servers) -> None:
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # 1440x900 light + dark
        _open_scenario(page, servers["base_url"], "default", "light", 1440, 900)
        _assert_j1_principles(page)
        _assert_contrast_pairs(page)

        strip_text = page.locator('[data-testid="doc-strip"]').inner_text()
        assert "변경 표시" in strip_text
        assert "표시 없이" in strip_text
        assert "원본" in strip_text
        assert "F8" not in strip_text
        assert "나란히" not in strip_text
        assert "공문 규칙 점검" not in strip_text
        assert page.locator('[data-testid="scroll-map"]').is_visible()
        assert page.locator('[data-testid="mark-toolbar"]').is_visible()
        assert page.locator('[data-testid="status-font-sub"]').is_visible()

        page.screenshot(path=str(SHOTS_DIR / "ws-default-1440-light.png"))

        # Dark theme at 1440x900
        page.click('[data-testid="harness-theme-toggle"]')
        page.wait_for_timeout(120)
        _assert_j1_principles(page)
        _assert_contrast_pairs(page)
        page.screenshot(path=str(SHOTS_DIR / "ws-default-1440-dark.png"))

        # 1280x800 light: right panel must be hidden (1280 single-docked rule)
        _open_scenario(page, servers["base_url"], "default", "light", 1280, 800)
        _assert_j1_principles(page)
        assert not page.locator(".rl-harness-right").is_visible()
        page.screenshot(path=str(SHOTS_DIR / "ws-default-1280-light.png"))

        # 390x844 light & dark
        _open_scenario(page, servers["base_url"], "default", "light", 390, 844)
        _assert_j1_principles(page)
        page.screenshot(path=str(SHOTS_DIR / "ws-default-390-light.png"))
        page.click('[data-testid="harness-theme-toggle"]')
        page.wait_for_timeout(120)
        _assert_j1_principles(page)
        page.screenshot(path=str(SHOTS_DIR / "ws-default-390-dark.png"))

        # Verify V cycles views & Ctrl+Shift+0 toggles page fit
        _open_scenario(page, servers["base_url"], "default", "light", 1440, 900)
        page.locator('[data-testid="canvas-pane"]').click(position={"x": 10, "y": 10})
        page.keyboard.press("KeyV")
        page.wait_for_timeout(60)
        assert page.locator('[data-testid="view-seg-clean"]').get_attribute("aria-selected") == "true"
        assert page.locator('[data-testid="margin-marks"]').count() == 0
        page.keyboard.press("KeyV")
        page.wait_for_timeout(60)
        assert page.locator('[data-testid="view-seg-base"]').get_attribute("aria-selected") == "true"
        page.keyboard.press("KeyV")
        page.wait_for_timeout(60)
        assert page.locator('[data-testid="view-seg-marks"]').get_attribute("aria-selected") == "true"

        assert not errors, f"Uncaught page errors: {errors}"
        browser.close()


def test_marks_all_states_and_keyboard_decisions(servers) -> None:
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page()

        _open_scenario(page, servers["base_url"], "marks", "light", 1440, 900)
        _assert_j1_principles(page)
        _assert_contrast_pairs(page)

        assert page.locator('[data-mark-state="pending"]').count() >= 1
        assert page.locator('[data-mark-state="accepted"]').count() >= 1
        assert page.locator('[data-mark-state="rejected"]').count() >= 1
        assert page.locator('[data-mark-state="test"]').count() >= 1
        assert page.locator('[data-mark-state="stale"]').count() >= 1
        assert page.locator('[data-fact="true"]').count() >= 1
        assert page.locator('[data-testid="mark-toolbar"]').is_visible()

        page.screenshot(path=str(SHOTS_DIR / "marks-states-1440-light.png"))

        page.click('[data-testid="harness-theme-toggle"]')
        page.wait_for_timeout(120)
        _assert_j1_principles(page)
        _assert_contrast_pairs(page)
        page.screenshot(path=str(SHOTS_DIR / "marks-states-1440-dark.png"))

        # Verify Y accepts op-24 & Ctrl+Z restores it
        page.keyboard.press("KeyY")
        page.wait_for_timeout(80)
        assert page.locator('[data-testid="page-mark-op-24"]').get_attribute("data-mark-state") == "accepted"
        page.keyboard.press("Control+KeyZ")
        page.wait_for_timeout(80)
        assert page.locator('[data-testid="page-mark-op-24"]').get_attribute("data-mark-state") == "pending"

        browser.close()


def test_seats_blanks_hover_editing_and_narrow_bar(servers) -> None:
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page()

        _open_scenario(page, servers["base_url"], "typing", "light", 1440, 900)
        _assert_j1_principles(page)

        # BlanksPane disambiguates 협조자 1..7 & starts 접수 기관이 쓰는 칸 collapsed
        counter_text = page.locator('[data-testid="blanks-counter"]').inner_text()
        assert "빈칸" in counter_text
        assert page.locator('[data-testid="blanks-agency-toggle"]').get_attribute("aria-expanded") == "false"
        assert page.locator('[data-testid="blanks-agency-list"]').count() == 0

        # Expand & verify 접수 기관이 쓰는 칸 reveals receiving agency cells
        page.click('[data-testid="blanks-agency-toggle"]')
        assert page.locator('[data-testid="blanks-agency-list"]').is_visible()
        page.click('[data-testid="blanks-agency-toggle"]')

        # Hover seat -> illuminates cell on paper & updates status bar
        coop_btn = page.locator('[data-testid="blank-seat-t0/r5/c1"]')
        assert "협조자 1" in coop_btn.inner_text()
        assert "표 1 6행 2열" in coop_btn.inner_text()
        coop_btn.hover()
        page.wait_for_timeout(80)
        assert "rl-cell--hovered" in (
            page.locator('[data-cell-key="c:0:5:1"]').get_attribute("class") or ""
        )
        assert "협조자 1" in page.locator('[data-testid="status-seat"]').inner_text()
        page.screenshot(path=str(SHOTS_DIR / "seats-hover-1440-light.png"))

        # Click blank -> opens SeatEditor inside paper
        coop_btn.click()
        seat_input = page.locator('[data-testid="seat-input"]')
        assert seat_input.is_visible()
        seat_input.fill("기록정책담당관")
        page.screenshot(path=str(SHOTS_DIR / "seat-editing-1440-light.png"))

        # Enter commits (single line) -> committed mark appears with --paper-ink glyphs
        seat_input.press("Enter")
        page.wait_for_timeout(80)
        assert page.locator('[data-testid="seat-input"]').count() == 0
        assert "기록정책담당관" in page.locator('[data-cell-key="c:0:5:1"]').inner_text()
        page.screenshot(path=str(SHOTS_DIR / "seat-committed-1440-light.png"))

        # Static/guide cell also opens cleanly with ZERO refusal string
        page.click('[data-cell-key="c:0:0:0"]')
        assert page.locator('[data-testid="seat-input"]').is_visible()
        assert page.locator('[data-testid="status-canvas-notice"]').count() == 0
        page.keyboard.press("Escape")

        # 390 narrow viewport: clicking blank opens bottom seat bar instead of cramped cell input
        _open_scenario(page, servers["base_url"], "typing", "light", 390, 844)
        page.click('[data-cell-key="c:0:5:1"]')
        page.wait_for_timeout(80)
        assert page.locator('[data-testid="narrow-seat-bar"]').is_visible()
        page.screenshot(path=str(SHOTS_DIR / "seat-narrow-390-light.png"))
        page.click('[data-testid="harness-theme-toggle"]')
        page.wait_for_timeout(80)
        page.screenshot(path=str(SHOTS_DIR / "seat-narrow-390-dark.png"))

        browser.close()


def test_outline_find_and_drying_states(servers) -> None:
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page()

        # Outline pane
        _open_scenario(page, servers["base_url"], "outline", "light", 1440, 900)
        _assert_j1_principles(page)
        assert page.locator('[data-testid="pane-outline"]').is_visible()
        assert "1쪽" in page.locator('[data-testid="pane-outline"]').inner_text()
        page.screenshot(path=str(SHOTS_DIR / "pane-outline-1440-light.png"))

        # Find pane & replace
        _open_scenario(page, servers["base_url"], "find", "light", 1440, 900)
        _assert_j1_principles(page)
        assert page.locator('[data-testid="pane-find"]').is_visible()
        assert "1번째" in page.locator('[data-testid="find-match-count"]').inner_text()
        assert page.locator(".rl-find-hit").count() >= 1
        page.screenshot(path=str(SHOTS_DIR / "pane-find-1440-light.png"))

        # Miss search shows Korean empty copy cleanly
        page.fill('[data-testid="find-query-input"]', "없는문구xyz")
        page.wait_for_timeout(60)
        assert "검색 결과가 없습니다." in page.locator('[data-testid="find-empty"]').inner_text()

        # Approval drying state
        _open_scenario(page, servers["base_url"], "drying", "light", 1440, 900)
        _assert_j1_principles(page)
        assert "rl-paper--drying" in (page.locator('[data-testid="paper"]').get_attribute("class") or "")
        page.screenshot(path=str(SHOTS_DIR / "paper-drying-1440-light.png"))

        browser.close()


def test_live_backend_font_sub_and_ime_and_zero_network_per_keystroke(servers) -> None:
    """Connects harness live mode to `rigorloom ui` /rpc for real HWPX gates."""
    bridge_base = servers["bridge_base"]
    gongmun_path = str(
        REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
    )

    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page()
        rpc_log: list[dict[str, Any]] = []

        def proxy_bridge(route):
            req = route.request
            parsed_path = urlparse(req.url).path
            body = req.post_data or ""
            if parsed_path == "/rpc":
                try:
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                rpc_log.append(payload)
            target_url = f"{bridge_base}{parsed_path}"
            headers = {
                "X-Rigorloom-Token": BRIDGE_TOKEN,
                "Origin": bridge_base,
                "Referer": f"{bridge_base}/",
            }
            if req.method == "POST":
                headers["Content-Type"] = "application/json"
            up = urllib.request.Request(
                target_url,
                data=body.encode("utf-8") if req.method == "POST" else None,
                headers=headers,
                method=req.method,
            )
            try:
                with urllib.request.urlopen(up, timeout=15) as resp:
                    raw = resp.read()
                    route.fulfill(
                        status=resp.status,
                        content_type="application/json",
                        body=raw,
                    )
            except urllib.error.HTTPError as err:
                route.fulfill(
                    status=err.code,
                    content_type="application/json",
                    body=err.read(),
                )

        page.route("**/rpc", proxy_bridge)
        page.route("**/api/**", proxy_bridge)
        _open_scenario(
            page,
            servers["base_url"],
            "live",
            "light",
            1440,
            900,
            extra=f"&path={gongmun_path}",
        )
        page.wait_for_selector('[data-testid="paper"]', timeout=15000)

        # Gate 1: Real rt_core typefaces report font substitution count in status bar
        font_badge = page.locator('[data-testid="status-font-sub"]')
        assert font_badge.is_visible(), "Expected live HWPX to report font substitution count"
        assert re.search(r"글꼴 대체 \d+", font_badge.inner_text())

        # Gate 2: Click a blank & verify ZERO /rpc calls during typing keystrokes
        page.click('[data-cell-key="c:0:5:1"]')
        seat = page.locator('[data-testid="seat-input"]')
        assert seat.is_visible()

        before_typing_calls = len(rpc_log)
        seat.type("가나다라마바사", delay=15)
        page.wait_for_timeout(120)
        assert len(rpc_log) == before_typing_calls, "Network/RPC fired during keystrokes!"

        # Gate 3: IME composition + Enter must NOT commit while composing
        page.evaluate(
            """() => {
              const el = document.querySelector('[data-testid="seat-input"]');
              el.dispatchEvent(new CompositionEvent("compositionstart", { data: "ㅎ", bubbles: true }));
              const ev = new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 229, isComposing: true, bubbles: true, cancelable: true });
              el.dispatchEvent(ev);
            }"""
        )
        page.wait_for_timeout(60)
        assert page.locator('[data-testid="seat-input"]').count() == 1, "Enter during IME composition wrongly committed!"

        # End composition + blur commits cleanly
        page.evaluate(
            """() => {
              const el = document.querySelector('[data-testid="seat-input"]');
              el.dispatchEvent(new CompositionEvent("compositionend", { data: "가나다라마바사", bubbles: true }));
              el.blur();
            }"""
        )
        page.wait_for_timeout(100)
        assert page.locator('[data-testid="seat-input"]').count() == 0, "Blur should commit SeatEditor"
        assert "가나다라마바사" in page.locator('[data-cell-key="c:0:5:1"]').inner_text()

        # Gate 4: Tab cycles across editable seats cleanly
        page.click('[data-cell-key="c:0:5:1"]')
        page.locator('[data-testid="seat-input"]').press("Tab")
        page.wait_for_timeout(60)
        assert page.locator('[data-testid="seat-input"]').count() == 1

        browser.close()
