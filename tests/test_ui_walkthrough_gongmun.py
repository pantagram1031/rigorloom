"""End-to-end gongmun walkthrough Playwright verification and canonical screenshot capture.

Run 1b protocol & approval-persistence notes:
- How `examples/gongmun/expected/plan.json` is loaded:
  The browser Review screen has no JSON plan upload widget by design; external
  agents and CLIs propose plans over `/rpc` (`plan/propose` + `approval/request`).
  This walkthrough opens `gianmun-byeolji-1ho.hwpx` from `예시 양식`, flattens the
  deterministic 24-op `examples/gongmun/expected/plan.json` into runtime ops, and
  submits `plan/propose` + `approval/request` via `/rpc`, which the React Review
  workspace automatically adopts from session events.
- Why no `APPROVALS.md` file exists in this flow:
  `APPROVALS.md` belongs exclusively to report-pipeline stage gates
  (`/api/pipeline/gate-resolve`). Interactive document-editing approvals go through
  `rt_ui.py` (`rt_ui.py:1900`, `rt_plan.py:762`) and persist to
  `<root>/approvals/<approvalId>.json`, `<root>/sessions/<sessionId>/events.jsonl`,
  and `<root>/sessions/<sessionId>/candidates/<runId>/receipt.json`. Compared to
  `examples/gongmun/expected/approval.json`, the live runtime record written by the
  Desktop ApprovalDialog uses `requestedBy="rigorloom-desktop"`, `approver="host-operator"`,
  generated `approvalId`/`planId` UUIDs, wall-clock UTC timestamps, and the drafted
  plan's `planHash`, while matching `state == "approved"` and `decision == "approved"`.
  Do NOT re-add `APPROVALS.md` assertions to this walkthrough.

Covers:
1. Clean `pytest.skip` when `playwright` or headless Chromium is unavailable.
2. Live subprocess launch (`cli.py ui --root <tmp> --port 0 --no-open`) with zero
   uncaught `pageerror`s and zero HTTP 5xx / unexpected API 4xx responses.
3. Open screen checks: hidden `파일 내보내기` when no doc is open, `경로로 문서 열기`
   in `명령창` only, and `예시 양식 열기` vocabulary (`기본 양식 열기` absent).
4. Opening `gianmun-byeolji-1ho.hwpx` -> top bar title `기안문 (별지 제1호서식)`
   with raw filename only under `자세히`; proposing 24-op `expected/plan.json`,
   verifying `/api/guard/diff` `{sessionId, planId}` contract, zero `바뀐 사실` pills
   matching header count `0`, Op 1 `기호 지움` `[별지 제1호서식]`, guide-fill `빈칸 채움`
   classification, grouped range marker (`1-4`) + peer row highlight, inline
   `변경 전:` callout in selected row only (never inside `page-sheet`), separated
   기안문 header paragraphs, dashed empty blanks without vertical Hangul syllable wrap,
   and 390 px mobile layout (`page-sheet` within 120 px of top, left edge >= 0,
   `scrollWidth <= innerWidth`).
5. Capturing all 20 canonical PNGs in `docs/ui/`:
   `{open,review,fill,history,settings}-{1440,390}-{light,dark}.png`.
6. Automated surface-leak checks & live DOM WCAG 2.1 contrast audit (>= 4.5:1) across
   all five screens (Open, Fill, Review, Settings, History) in light and dark themes.
7. Fill-in-place blank entry, Enter commit, Esc exit to sheet anchor -> Tab into
   right pane, Ruling J empty-value removal + undo, and round-trip into Review.
8. Approving and exporting `.hwpx` ZIP (`수정본 1 내보내기`, matching
   `examples/gongmun/expected/filled.hwpx`), then checking Settings folder lock and
   History revision node (`승인 시각`, `적용 시각`, `승인 방식: 직접 승인`,
   `수정본 1 내보내기`) plus on-disk persistence under `approvals/<approvalId>.json`,
   `sessions/<sessionId>/events.jsonl`, and `sessions/<sessionId>/candidates/<runId>/receipt.json`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "runtime" / "scripts" / "cli.py"
DOCS_UI_DIR = REPO_ROOT / "docs" / "ui"
GONGMUN_PLAN_PATH = REPO_ROOT / "examples" / "gongmun" / "expected" / "plan.json"
GONGMUN_FILLED_HWPX_PATH = REPO_ROOT / "examples" / "gongmun" / "expected" / "filled.hwpx"
CORPUS_FORM_FILENAME = "gianmun-byeolji-1ho.hwpx"
# The live contrast audit is written only when this variable names a file;
# otherwise it goes to the test's temporary directory.
LIVE_CONTRAST_ENV = "RIGORLOOM_LIVE_CONTRAST_OUT"
WALKTHROUGH_METRICS_ENV = "RIGORLOOM_WALKTHROUGH_METRICS_OUT"

CANONICAL_SCREENSHOTS = [
    f"{screen}-{width}-{theme}.png"
    for screen in ("open", "review", "fill", "history", "settings")
    for width in (1440, 390)
    for theme in ("light", "dark")
]

FORBIDDEN_UI_STRINGS = (
    "\ub9ac\uac78\ub8f8",
    "\ud64d\uae38\ub3d9",
    "\uc815\ud655\ub3c4 100%",
    "Claude \uae30\ubc18",
    "AI \ud0d0\uc9c0 \ud68c\ud53c",
    "AI \ud2f0 \uc81c\uac70",
    "Astra",
    "Herdr",
    "F:/",
)

SURFACE_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("raw_path", re.compile(r"(?:/home/|/Users/|/tmp/|[A-Za-z]:\\\\|F:/)")),
    (
        "raw_event",
        re.compile(
            r"\b(?:plan\.proposed|approval\.requested|approval\.resolved|plan\.applied)\b"
        ),
    ),
    ("raw_hex32", re.compile(r"\b[0-9a-f]{32}\b")),
    (
        "internal_jargon",
        re.compile(
            r"\b(?:at_para|atPara|replace_at_cell|fill_cell|set_run|delete_guides|"
            r"charPr|paraPr|boundSha256|planHash|planId|approvalId|opsHash|implVersion)\b"
        ),
    ),
]


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip(f"playwright Python package unavailable: {exc}")
    return sync_playwright


def _launch_chromium(pw):
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"headless Chromium unavailable: {exc}")


def _start_ui_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str, Path]:
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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _set_viewport_and_theme(page, width: int, height: int, theme: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(color_scheme=theme)
    page.evaluate(
        """(t) => {
            document.documentElement.setAttribute('data-theme', t);
            try { window.localStorage.setItem('rigorloom.theme', t); } catch {}
            void document.documentElement.offsetHeight;
        }""",
        theme,
    )
    page.evaluate(
        """async () => {
            if (document.fonts) await document.fonts.ready;
            const waitFrames = (n) => new Promise((resolve) => {
                const step = (rem) => rem <= 0 ? resolve() : requestAnimationFrame(() => step(rem - 1));
                step(n);
            });
            await waitFrames(2);
            if (typeof document.getAnimations === 'function') {
                const anims = document.getAnimations({ subtree: true }).filter((a) => {
                    const timing = a.effect && typeof a.effect.getComputedTiming === 'function'
                        ? a.effect.getComputedTiming()
                        : null;
                    return !timing || timing.iterations !== Infinity;
                });
                await Promise.all(anims.map((a) => a.finished.catch(() => {})));
            }
            const vp = document.querySelector('.page-sheet-viewport');
            if (vp) {
                let prevTop = vp.scrollTop;
                let prevLeft = vp.scrollLeft;
                let stable = 0;
                while (stable < 3) {
                    await waitFrames(1);
                    if (vp.scrollTop === prevTop && vp.scrollLeft === prevLeft) {
                        stable += 1;
                    } else {
                        prevTop = vp.scrollTop;
                        prevLeft = vp.scrollLeft;
                        stable = 0;
                    }
                }
            } else {
                await waitFrames(2);
            }
        }"""
    )
    if width <= 400:
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        inner_w = page.evaluate("window.innerWidth")
        assert scroll_w <= inner_w, (
            f"Horizontal overflow at {width}x{height} ({theme}): "
            f"scrollWidth={scroll_w} > innerWidth={inner_w}"
        )


def _extract_visible_surface_text(page) -> str:
    return page.evaluate(
        """() => {
            const parts = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const text = (node.nodeValue || '').trim();
                if (!text) continue;
                const el = node.parentElement;
                if (!el) continue;
                const tag = el.tagName;
                if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEMPLATE') {
                    continue;
                }
                if (el.closest('input, textarea, .approval-hash, [data-testid="approval-plan-hash"], [data-testid="approval-bound-hash"]')) {
                    continue;
                }
                const closedDetails = el.closest('details:not([open])');
                if (closedDetails && !el.closest('summary')) {
                    continue;
                }
                const rect = el.getBoundingClientRect();
                if (rect.width < 1 || rect.height < 1) continue;
                let cur = el;
                let visible = true;
                while (cur) {
                    const cs = getComputedStyle(cur);
                    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) <= 0.01) {
                        visible = false;
                        break;
                    }
                    cur = cur.parentElement;
                }
                if (visible) parts.push(text);
            }
            return parts.join('\\n');
        }"""
    )


def _assert_surface_clean(page, surface_name: str) -> None:
    text = _extract_visible_surface_text(page)
    for bad in FORBIDDEN_UI_STRINGS:
        assert bad not in text, f"Forbidden string {bad!r} found on {surface_name}"
    for label, pattern in SURFACE_LEAK_PATTERNS:
        m = pattern.search(text)
        assert not m, f"Surface leak ({label}={m.group(0)!r}) on {surface_name}"


def _audit_live_dom_contrast(page, screen: str, theme: str) -> dict:
    return page.evaluate(
        """({screen, theme}) => {
            function parseRgba(str) {
                if (!str || str === 'transparent') return [0, 0, 0, 0];
                const m = str.match(/rgba?\\(\\s*([0-9.]+)\\s*,\\s*([0-9.]+)\\s*,\\s*([0-9.]+)(?:\\s*[,/]\\s*([0-9.]+))?\\s*\\)/i);
                if (!m) return null;
                return [
                    parseFloat(m[1]),
                    parseFloat(m[2]),
                    parseFloat(m[3]),
                    m[4] === undefined ? 1 : parseFloat(m[4]),
                ];
            }
            function compositeOver(fg, bg) {
                const a = fg[3];
                const outA = a + bg[3] * (1 - a);
                if (outA <= 0) return [0, 0, 0, 0];
                return [
                    (fg[0] * a + bg[0] * bg[3] * (1 - a)) / outA,
                    (fg[1] * a + bg[1] * bg[3] * (1 - a)) / outA,
                    (fg[2] * a + bg[2] * bg[3] * (1 - a)) / outA,
                    outA,
                ];
            }
            function relLum(rgb) {
                const ch = [rgb[0], rgb[1], rgb[2]].map((v) => {
                    const s = Math.max(0, Math.min(255, v)) / 255;
                    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
                });
                return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
            }
            function contrastRatio(rgb1, rgb2) {
                const l1 = relLum(rgb1);
                const l2 = relLum(rgb2);
                const hi = Math.max(l1, l2);
                const lo = Math.min(l1, l2);
                return (hi + 0.05) / (lo + 0.05);
            }
            function isDisabledOrHidden(el) {
                let cur = el;
                while (cur) {
                    if (cur.disabled === true || cur.getAttribute('aria-disabled') === 'true') {
                        return true;
                    }
                    const cs = getComputedStyle(cur);
                    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) <= 0.01) {
                        return true;
                    }
                    cur = cur.parentElement;
                }
                const closedDetails = el.closest('details:not([open])');
                if (closedDetails && !el.closest('summary')) return true;
                return false;
            }
            function effectiveBg(el) {
                const stack = [];
                let cur = el;
                while (cur) {
                    const parsed = parseRgba(getComputedStyle(cur).backgroundColor);
                    if (parsed && parsed[3] > 0) stack.push(parsed);
                    cur = cur.parentElement;
                }
                let bg = theme === 'dark' ? [20, 20, 19, 1] : [247, 247, 245, 1];
                for (let i = stack.length - 1; i >= 0; i -= 1) {
                    bg = compositeOver(stack[i], bg);
                }
                return bg;
            }
            function describeEl(el) {
                const tid = el.getAttribute('data-testid');
                if (tid) return `[data-testid="${tid}"]`;
                const cls = typeof el.className === 'string'
                    ? el.className.trim().split(/\\s+/).filter(Boolean).slice(0, 2).join('.')
                    : '';
                return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`;
            }

            let checked = 0;
            let skippedDisabled = 0;
            let minRatio = 999;
            const failures = [];
            const seen = new Set();

            const all = document.body.querySelectorAll('*');
            for (const el of all) {
                const hasDirectText = Array.from(el.childNodes).some(
                    (n) => n.nodeType === Node.TEXT_NODE && (n.nodeValue || '').trim().length > 0
                );
                if (!hasDirectText) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 1 || rect.height < 1) continue;

                let cur = el;
                let disabled = false;
                while (cur) {
                    if (cur.disabled === true || cur.getAttribute('aria-disabled') === 'true') {
                        disabled = true;
                        break;
                    }
                    cur = cur.parentElement;
                }
                if (disabled) {
                    skippedDisabled += 1;
                    continue;
                }
                if (isDisabledOrHidden(el)) continue;

                const cs = getComputedStyle(el);
                const rawFg = parseRgba(cs.color);
                if (!rawFg) continue;
                const bg = effectiveBg(el);
                const fg = rawFg[3] < 1 ? compositeOver(rawFg, bg) : rawFg;
                const ratio = Number(contrastRatio(fg, bg).toFixed(2));
                const fontSize = parseFloat(cs.fontSize) || 13;
                const fontWeight = parseInt(cs.fontWeight, 10) || 400;
                const isLarge = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
                const threshold = isLarge ? 3.0 : 4.5;

                checked += 1;
                if (ratio < minRatio) minRatio = ratio;

                if (ratio < threshold) {
                    const key = `${describeEl(el)}:${cs.color}:${bg.join(',')}`;
                    if (!seen.has(key)) {
                        seen.add(key);
                        failures.push({
                            screen,
                            theme,
                            selector: describeEl(el),
                            text: (el.textContent || '').trim().slice(0, 60),
                            color: cs.color,
                            bg: bg.slice(0, 3).map((x) => Math.round(x)),
                            ratio,
                            threshold,
                            fontSize,
                            fontWeight,
                        });
                    }
                }
            }
            return {
                screen,
                theme,
                checked,
                skippedDisabled,
                minRatio: checked > 0 ? minRatio : null,
                failureCount: failures.length,
                failures,
            };
        }""",
        {"screen": screen, "theme": theme},
    )


def _save_canonical_variants(
    page,
    screen: str,
    overflow_390: list[dict] | None = None,
) -> None:
    DOCS_UI_DIR.mkdir(parents=True, exist_ok=True)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"toast\"]')",
        timeout=10000,
    )
    for width, height in ((1440, 900), (390, 844)):
        for theme in ("light", "dark"):
            _set_viewport_and_theme(page, width, height, theme)
            if width == 390:
                _assert_surface_clean(page, f"{screen}-390-{theme}")
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                inner_w = page.evaluate("window.innerWidth")
                assert scroll_w <= inner_w, (screen, theme, scroll_w, inner_w)
                if overflow_390 is not None:
                    overflow_390.append(
                        {
                            "screen": screen,
                            "theme": theme,
                            "scrollWidth": scroll_w,
                            "innerWidth": inner_w,
                        }
                    )
            fname = f"{screen}-{width}-{theme}.png"
            out = DOCS_UI_DIR / fname
            page.screenshot(path=str(out))
            raw = out.read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 5000, fname


def test_ui_walkthrough_gongmun_e2e_and_canonical_docs(tmp_path: Path) -> None:
    sync_playwright = _import_playwright()
    expected_plan = json.loads(GONGMUN_PLAN_PATH.read_text(encoding="utf-8"))
    flat_ops = [
        {"opId": op["opId"], "kind": op["kind"], **op["params"]}
        for op in expected_plan["ops"]
    ]
    assert len(flat_ops) == 24

    proc, url, rt_root = _start_ui_server(tmp_path)
    page_errors: list[str] = []
    server_errors: list[tuple[int, str]] = []
    api_errors: list[tuple[int, str]] = []
    guard_diff_requests: list[dict] = []
    guard_diff_responses: list[int] = []
    contrast_reports: list[dict] = []
    overflow_390: list[dict] = []
    metrics_snapshot: dict = {}

    def _on_request(req) -> None:
        if "/api/guard/diff" in req.url and req.method == "POST":
            try:
                guard_diff_requests.append(json.loads(req.post_data or "{}"))
            except json.JSONDecodeError:
                guard_diff_requests.append({"raw": req.post_data})

    def _on_response(resp) -> None:
        if resp.status >= 500:
            server_errors.append((resp.status, resp.url))
        elif resp.status >= 400 and ("/api/" in resp.url or "/rpc" in resp.url):
            api_errors.append((resp.status, resp.url))
        elif "/api/guard/diff" in resp.url and resp.status == 200:
            guard_diff_responses.append(resp.status)

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
            page.on("request", _on_request)
            page.on("response", _on_response)

            # 1) Load Open view, check Item 13/14 surface controls, cleanliness & contrast
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

            assert page.locator('[data-testid="topbar-export"]').count() == 0
            assert page.locator('[data-testid="open-path-disclosure"]').count() == 0
            page.click('[data-testid="topbar-palette"]')
            page.wait_for_selector('[data-testid="palette-cmd-open-by-path"]', timeout=5000)
            assert page.locator('[data-testid="palette-cmd-open-by-path"]').is_visible()
            assert page.locator('[data-testid="palette-cmd-export"]').count() == 0
            open_builtin_text = page.locator('[data-testid="palette-cmd-open-builtin"]').inner_text().strip()
            assert open_builtin_text == "예시 양식 열기", open_builtin_text
            assert "기본 양식 열기" not in page.locator("body").inner_text()
            page.keyboard.press("Escape")
            page.wait_for_function(
                "() => !document.querySelector('[data-testid=\"palette-cmd-open-by-path\"]')",
                timeout=5000,
            )

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"open-1440-{theme}")
                report = _audit_live_dom_contrast(page, "open", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )
                assert report["minRatio"] is not None and report["minRatio"] >= 4.5, report

            _save_canonical_variants(page, "open", overflow_390)
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 2) Open gianmun-byeolji-1ho.hwpx, check Item 12 title & Item 14 export gating,
            #    then propose 24-op gongmun plan + approval/request via /rpc
            page.click(f'[data-testid="open-sample-item-{CORPUS_FORM_FILENAME}"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=15000)
            page.wait_for_selector('[data-testid="page-sheet"]', timeout=15000)

            doc_title = page.locator('[data-testid="doc-name"]').inner_text().strip()
            assert doc_title == "기안문 (별지 제1호서식)", doc_title
            assert CORPUS_FORM_FILENAME not in _extract_visible_surface_text(page)
            page.click('[data-testid="review-source-detail"] summary')
            assert CORPUS_FORM_FILENAME in page.locator('[data-testid="review-source-detail"]').inner_text()
            page.click('[data-testid="review-source-detail"] summary')
            assert CORPUS_FORM_FILENAME not in _extract_visible_surface_text(page)

            # Before an applied export revision exists, TopBar export stays hidden while palette exposes it
            assert page.locator('[data-testid="topbar-export"]').count() == 0
            page.click('[data-testid="topbar-palette"]')
            page.wait_for_selector('[data-testid="palette-cmd-export"]', timeout=5000)
            assert page.locator('[data-testid="palette-cmd-export"]').is_visible()
            page.keyboard.press("Escape")
            page.wait_for_function(
                "() => !document.querySelector('[data-testid=\"palette-cmd-export\"]')",
                timeout=5000,
            )

            # 2b) Fill screen: click blank in place, commit Korean with Enter, Esc -> Tab,
            #     capture Fill PNGs & contrast, round-trip to Review, test Ruling J empty-clear undo
            page.click('[data-testid="nav-fill"]')
            page.wait_for_selector('[data-testid="fill-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="fill-counter"]', timeout=10000)

            page.click('[data-testid="page-cell-0-5-1"]')
            page.wait_for_selector('[data-testid="page-cell-0-5-1"] [data-testid="seat-input"]', timeout=5000)
            page.locator('[data-testid="seat-input"]').fill("기획조정실")
            page.keyboard.press("Enter")
            page.wait_for_function(
                """() => {
                    const c = document.querySelector('[data-testid="fill-counter"]')?.textContent || '';
                    return c.includes('1개 입력')
                        && !document.querySelector('[data-testid="page-cell-0-5-1"] [data-testid="seat-input"]')
                        && document.activeElement?.getAttribute('data-testid') === 'seat-input';
                }""",
                timeout=10000,
            )

            page.keyboard.press("Escape")
            page.wait_for_function(
                """() => !document.querySelector('[data-testid="seat-input"]')
                    && document.activeElement?.getAttribute('data-testid') === 'fill-sheet-anchor'""",
                timeout=5000,
            )
            page.evaluate(
                "() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            page.keyboard.press("Tab")
            tab_target = page.evaluate(
                """() => ({
                    ok: Boolean(document.activeElement?.closest('[data-testid="fill-right-pane"]')),
                    tag: document.activeElement?.tagName || null,
                    testId: document.activeElement?.getAttribute?.('data-testid') || null,
                    cls: document.activeElement?.className || null,
                })"""
            )
            assert tab_target["ok"], tab_target

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"fill-1440-{theme}")
                report = _audit_live_dom_contrast(page, "fill", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )
                assert report["minRatio"] is not None and report["minRatio"] >= 4.5, report

            _save_canonical_variants(page, "fill", overflow_390)
            _set_viewport_and_theme(page, 1440, 900, "light")

            page.click('[data-testid="fill-to-review"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="change-row-1"]', timeout=10000)
            assert "기획조정실" in page.locator('[data-testid="change-row-1"]').inner_text()

            page.click('[data-testid="nav-fill"]')
            page.wait_for_selector('[data-testid="fill-view"]', timeout=10000)
            page.click('[data-testid="page-cell-0-5-1"]')
            page.wait_for_selector('[data-testid="seat-input"]', timeout=5000)
            page.locator('[data-testid="seat-input"]').fill("")
            page.keyboard.press("Enter")
            page.wait_for_selector('[data-testid="fill-undo-banner"]', timeout=10000)
            page.click('[data-testid="fill-undo-restore"]')
            page.wait_for_selector('[data-testid^="fill-entry-row-"]', timeout=10000)
            page.locator('[data-testid^="fill-remove-entry-"]').first.click()
            page.wait_for_selector('[data-testid="fill-entries-empty"]', timeout=10000)

            page.click('[data-testid="nav-review"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_function(
                "() => document.querySelectorAll('[data-testid^=\"change-row-\"]').length === 0",
                timeout=10000,
            )
            guard_diff_requests.clear()
            guard_diff_responses.clear()

            bootstrap = page.evaluate("() => window.__RIGORLOOM_UI__")
            token = bootstrap["token"]
            base_url = url.split("?", 1)[0]
            sessions_res = _rpc_post(base_url, token, "session/list", {})
            assert sessions_res["ok"] is True, sessions_res
            session_id = sessions_res["result"]["sessions"][0]["sessionId"]

            prop_res = _rpc_post(
                base_url,
                token,
                "plan/propose",
                {
                    "sessionId": session_id,
                    "backend": expected_plan["backend"],
                    "ops": flat_ops,
                    "declares": expected_plan["declares"],
                },
            )
            assert prop_res["ok"] is True, prop_res
            proposed_plan = prop_res["result"]["plan"]

            req_res = _rpc_post(
                base_url,
                token,
                "approval/request",
                {"planId": proposed_plan["planId"], "requestedBy": "gongmun-walkthrough"},
            )
            assert req_res["ok"] is True, req_res

            # 3) Verify auto-adoption of all 24 changes & /api/guard/diff DOM readiness (Items 1-4, 6-7)
            page.wait_for_selector('[data-testid="change-row-24"]', timeout=20000)
            page.wait_for_selector(
                f'[data-testid="guard-list-header"][data-guard-state="ready"][data-guard-plan-id="{proposed_plan["planId"]}"]',
                timeout=20000,
            )
            assert len(guard_diff_responses) >= 1, guard_diff_responses

            assert len(guard_diff_requests) >= 1, guard_diff_requests
            for payload in guard_diff_requests:
                assert set(payload.keys()) == {"sessionId", "planId"}, payload
                assert payload["sessionId"] == session_id, payload
                assert payload["planId"] == proposed_plan["planId"], payload

            rows = page.locator('[data-testid^="change-row-"]')
            assert rows.count() == 24
            for i in range(rows.count()):
                box = rows.nth(i).bounding_box()
                assert box is not None and box["height"] <= 56.5, (i + 1, box)

            assert page.locator('[data-testid^="change-pill-"]').count() == 0
            assert page.locator('[data-testid="changed-facts-jumper"]').count() == 0
            guard_header_text = page.locator('[data-testid="guard-list-header"]').inner_text().strip()
            assert "수정한 문단의" in guard_header_text, guard_header_text

            row_meta = page.evaluate(
                r"""() => Array.from(document.querySelectorAll('[data-testid^="change-row-"]')).map((li) => {
                    const m = (li.getAttribute('data-testid') || '').match(/^change-row-(\d+)$/);
                    return {
                        ordinal: m ? Number(m[1]) : 0,
                        field: (li.querySelector('.change-row-field')?.textContent || '').trim(),
                        kind: (li.querySelector('.change-row-kind')?.textContent || '').trim(),
                        preview: (li.querySelector('.change-row-preview')?.textContent || '').trim(),
                        text: (li.textContent || ''),
                    };
                })"""
            )
            assert len(row_meta) == 24
            kind_counts: dict[str, int] = {}
            for item in row_meta:
                assert not re.fullmatch(r"빈칸 \d+", item["field"]), item
                assert "행 정 기 관 명" not in item["text"], item
                kind_counts[item["kind"]] = kind_counts.get(item["kind"], 0) + 1
            assert kind_counts == {
                "기호 지움": 2,
                "안내문 지움": 6,
                "빈칸 채움": 16,
            }, kind_counts
            assert row_meta[0]["ordinal"] == 1
            assert row_meta[0]["field"] == "[별지 제1호서식]", row_meta[0]
            assert row_meta[0]["kind"] == "기호 지움", row_meta[0]
            assert "■" in row_meta[0]["preview"], row_meta[0]

            # Verify unselected row hides inline before, expanding shows technical detail guard=paragraph,
            # and selected+collapsed guide-fill row reveals inline "변경 전:"
            fill_ord = next(r["ordinal"] for r in row_meta if r["kind"] == "빈칸 채움")
            assert page.locator(f'[data-testid="change-before-inline-{fill_ord}"]').count() == 0
            fill_summary = page.locator(f'[data-testid="change-summary-{fill_ord}"]')
            fill_summary.scroll_into_view_if_needed()
            fill_summary.click()
            assert page.locator(f'[data-testid="change-row-{fill_ord}"]').get_attribute("aria-selected") == "true"
            page.wait_for_selector(f'[data-testid="change-detail-{fill_ord}"]', timeout=5000)
            page.click(f'[data-testid="change-details-{fill_ord}"] summary')
            assert "guard: paragraph=" in page.locator(f'[data-testid="change-details-{fill_ord}"]').inner_text()
            page.click(f'[data-testid="change-details-{fill_ord}"] summary')
            fill_summary.click()
            page.wait_for_function(
                f"() => !document.querySelector('[data-testid=\"change-detail-{fill_ord}\"]')",
                timeout=5000,
            )
            inline_before = page.locator(f'[data-testid="change-before-inline-{fill_ord}"]')
            assert inline_before.is_visible()
            assert "변경 전:" in inline_before.inner_text()

            # 4) Bidirectional grouped marker <-> peer row sync
            marker_1 = page.locator('[data-testid="page-marker-1"]').first
            marker_1.scroll_into_view_if_needed()
            assert marker_1.inner_text().strip() == "1-4"
            marker_1.click()
            assert (
                page.locator('[data-testid="change-row-1"]').get_attribute("aria-selected")
                == "true"
            )
            for peer_ord in (2, 3, 4):
                peer_cls = page.locator(f'[data-testid="change-row-{peer_ord}"]').get_attribute("class") or ""
                assert "change-row--group-peer" in peer_cls, (peer_ord, peer_cls)

            summary_10 = page.locator('[data-testid="change-summary-10"]')
            summary_10.scroll_into_view_if_needed()
            summary_10.click()
            assert (
                page.locator('[data-testid="change-row-10"]').get_attribute("aria-selected")
                == "true"
            )
            page.wait_for_selector('[data-testid="change-detail-10"]', timeout=5000)
            assert (
                page.locator('[data-testid="page-marker-10"]').first.get_attribute("aria-pressed")
                == "true"
            )
            # Collapse row 10 back and return selection to row 1 for clean canonical capture
            summary_10.click()
            page.wait_for_function(
                "document.querySelector('[data-testid=\"change-detail-10\"]') === null",
                timeout=5000,
            )
            page.locator('[data-testid="page-marker-1"]').first.scroll_into_view_if_needed()
            page.locator('[data-testid="page-marker-1"]').first.click()

            # 5) Check Item 5/8 PageSheet rendering, live DOM contrast & cleanliness on 1440 light/dark
            sheet_audit = page.evaluate(
                """() => {
                    const sheet = document.querySelector('[data-testid="page-sheet"]');
                    const sheetText = sheet ? (sheet.textContent || '') : '';
                    const headerParas = document.querySelectorAll('[data-testid="page-cell-0-1-0"] .page-cell-para').length;
                    const unlabeledBlanks = Array.from(
                        document.querySelectorAll('.page-empty-blank')
                    )
                        .filter((el) => !el.querySelector('.page-seat-hint'))
                        .map((el) => el.innerText.trim());
                    const seatHintIssues = [];
                    for (const el of document.querySelectorAll('.page-empty-blank .page-seat-hint')) {
                        const rect = el.getBoundingClientRect();
                        if (el.scrollWidth > el.clientWidth + 1 || rect.height > 30) {
                            seatHintIssues.push({
                                text: el.innerText.trim(),
                                scrollWidth: el.scrollWidth,
                                clientWidth: el.clientWidth,
                                height: rect.height,
                            });
                        }
                    }
                    const verticalBreaks = [];
                    for (const cell of document.querySelectorAll('.page-cell')) {
                        const fontSize = parseFloat(getComputedStyle(cell).fontSize) || 13;
                        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
                        let node;
                        while ((node = walker.nextNode())) {
                            const txt = node.nodeValue || '';
                            const re = /[가-힣]{2,}/g;
                            let m;
                            while ((m = re.exec(txt)) !== null) {
                                const range = document.createRange();
                                range.setStart(node, m.index);
                                range.setEnd(node, m.index + m[0].length);
                                const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
                                const distinctTops = new Set(rects.map((r) => Math.round(r.top)));
                                if (distinctTops.size >= m[0].length && rects.every((r) => r.width <= fontSize * 1.65)) {
                                    verticalBreaks.push({word: m[0], lines: distinctTops.size});
                                }
                            }
                        }
                    }
                    const sheetRect = sheet ? sheet.getBoundingClientRect() : null;
                    const tableOverflow = [];
                    for (const tbl of document.querySelectorAll('.page-doc-table')) {
                        const r = tbl.getBoundingClientRect();
                        if (sheetRect && r.right > sheetRect.right + 2) {
                            tableOverflow.push({tableRight: r.right, sheetRight: sheetRect.right});
                        }
                    }
                    return {
                        hasBeforeTextInSheet: sheetText.includes('변경 전'),
                        headerParas,
                        unlabeledBlanks,
                        seatHintIssues,
                        verticalBreaks,
                        tableOverflow,
                    };
                }"""
            )
            assert not sheet_audit["hasBeforeTextInSheet"], sheet_audit
            assert sheet_audit["headerParas"] >= 4, sheet_audit
            assert all(t == "" for t in sheet_audit["unlabeledBlanks"]), sheet_audit["unlabeledBlanks"]
            assert not sheet_audit["seatHintIssues"], sheet_audit["seatHintIssues"]
            assert not sheet_audit["verticalBreaks"], sheet_audit["verticalBreaks"]
            assert not sheet_audit["tableOverflow"], sheet_audit["tableOverflow"]

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"review-1440-{theme}")
                report = _audit_live_dom_contrast(page, "review", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )
                assert report["minRatio"] is not None and report["minRatio"] >= 4.5, report

            # Verify 390px mobile layout: Review opens on 변경, 문서 tab shows 100% + stepper + sheet box
            mobile_sheet_box = None
            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 390, 844, theme)
                assert not page.locator(".page-sheet-zoom").is_visible()
                assert page.locator('[data-testid="topbar-menu-btn"]').is_visible()
                assert page.locator('[data-testid="review-mobile-stepper"]').is_visible()
                assert (
                    page.locator('[data-testid="review-mobile-tab-list"]').get_attribute("aria-selected")
                    == "true"
                )
                assert (
                    page.locator('[data-testid="review-view"]').get_attribute("data-mobile-pane")
                    == "list"
                )
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                inner_w = page.evaluate("window.innerWidth")
                assert scroll_w <= inner_w, (scroll_w, inner_w)

                page.click('[data-testid="review-mobile-tab-sheet"]')
                page.wait_for_timeout(150)
                sheet_box = page.locator('[data-testid="page-sheet"]').bounding_box()
                assert sheet_box is not None and sheet_box["x"] >= 0 and sheet_box["y"] <= 120, sheet_box
                mobile_sheet_box = sheet_box
                scroll_w2 = page.evaluate("document.documentElement.scrollWidth")
                inner_w2 = page.evaluate("window.innerWidth")
                assert scroll_w2 <= inner_w2, (scroll_w2, inner_w2)

                page.click('[data-testid="review-mobile-tab-list"]')
                page.wait_for_timeout(100)

            _save_canonical_variants(page, "review", overflow_390)
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 5b) Settings screen while 24-op plan is live: folder change disabled with reason
            page.click('[data-testid="open-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=10000)
            assert page.locator('[data-testid="settings-folder-change"]').is_disabled()
            assert page.locator('[data-testid="settings-folder-locked-reason"]').is_visible()

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"settings-1440-{theme}")
                report = _audit_live_dom_contrast(page, "settings", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )
                assert report["minRatio"] is not None and report["minRatio"] >= 4.5, report

            _save_canonical_variants(page, "settings", overflow_390)
            _set_viewport_and_theme(page, 1440, 900, "light")
            page.click('[data-testid="nav-review"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="change-row-24"]', timeout=10000)

            # 6) Approve via ApprovalDialog (zero changed-facts ack needed) and export verified .hwpx ZIP
            page.click('[data-testid="review-approve-btn"]')
            page.wait_for_selector('[data-testid="approval-dialog"]', timeout=10000)

            plan_hash = page.locator('[data-testid="approval-plan-hash"]').inner_text().strip()
            assert re.fullmatch(r"[0-9a-f]{64}", plan_hash), plan_hash

            page.wait_for_function(
                "() => !document.querySelector('.approval-guard-note:not(.approval-guard-note--warn)')",
                timeout=15000,
            )
            assert page.locator('[data-testid="approval-changed-facts-ack"]').count() == 0
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-testid=\"approval-confirm-btn\"]'); return b && !b.disabled; }",
                timeout=10000,
            )
            page.click('[data-testid="approval-confirm-btn"]')

            page.wait_for_selector('[data-testid="review-export-btn"]', timeout=30000)
            page.wait_for_selector('[data-testid="topbar-export"]', timeout=10000)
            topbar_export_cls = page.locator('[data-testid="topbar-export"]').get_attribute("class") or ""
            assert "topbar-btn--primary" in topbar_export_cls, topbar_export_cls
            assert page.locator('[data-testid="review-export-btn"]').inner_text().strip() == "수정본 1 내보내기"
            assert page.locator('[data-testid="topbar-export"]').inner_text().strip() == "수정본 1 내보내기"

            with page.expect_download(timeout=15000) as dl_info:
                page.click('[data-testid="review-export-btn"]')
            download = dl_info.value
            exported_path = tmp_path / download.suggested_filename
            download.save_as(str(exported_path))
            exported_bytes = exported_path.read_bytes()
            assert exported_path.is_file() and len(exported_bytes) > 1000
            assert zipfile.is_zipfile(exported_path)

            exported_hwpx_sha256 = hashlib.sha256(exported_bytes).hexdigest()
            expected_filled_sha256 = hashlib.sha256(GONGMUN_FILLED_HWPX_PATH.read_bytes()).hexdigest()
            with zipfile.ZipFile(exported_path) as z_exp, zipfile.ZipFile(GONGMUN_FILLED_HWPX_PATH) as z_ref:
                exp_names = sorted(z_exp.namelist())
                ref_names = sorted(z_ref.namelist())
                assert exp_names == ref_names, (exp_names, ref_names)
                mismatched_entries = [
                    name for name in ref_names if z_exp.read(name) != z_ref.read(name)
                ]
                assert not mismatched_entries, mismatched_entries

            # 6b) History screen: applied 수정본 1, separate 승인/적용 시각, 직접 승인, 내보내기
            page.click('[data-testid="nav-history"]')
            page.wait_for_selector('[data-testid="history-view"]', timeout=10000)
            page.wait_for_selector('[data-testid="history-node-1"]', timeout=10000)
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('[data-testid="history-approved-at-1"]');
                    const txt = el ? (el.textContent || '').trim() : '';
                    return txt.length > 0 && !txt.includes('아직 불러오지');
                }""",
                timeout=15000,
            )
            page.wait_for_selector('[data-testid="history-compare-summary"]', timeout=15000)
            page.wait_for_selector('[data-testid="history-compare-detail"]', timeout=15000)
            assert page.locator('[data-testid="history-approved-at-1"]').is_visible()
            assert page.locator('[data-testid="history-applied-at-1"]').is_visible()
            live_approved_at = page.locator('[data-testid="history-approved-at-1"]').inner_text().strip()
            live_applied_at = page.locator('[data-testid="history-applied-at-1"]').inner_text().strip()
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", live_approved_at), live_approved_at
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", live_applied_at), live_applied_at
            assert (
                page.locator('[data-testid="history-approval-method-1"]').inner_text().strip()
                == "승인 방식: 직접 승인"
            )
            assert (
                page.locator('[data-testid="history-export-1"]').inner_text().strip()
                == "수정본 1 내보내기"
            )
            assert page.locator('[data-testid="history-undo-scope-1"]').is_visible()
            assert page.locator('[data-testid="history-propose-undo-1"]').is_visible()

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"history-1440-{theme}")
                report = _audit_live_dom_contrast(page, "history", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )
                assert report["minRatio"] is not None and report["minRatio"] >= 4.5, report

            fixed_history_time = "2026-11-15 00:00:00"
            page.evaluate(
                "(ts) => document.documentElement.setAttribute('data-capture-fixed-time', ts)",
                fixed_history_time,
            )
            try:
                page.wait_for_function(
                    """(ts) => {
                        const a = document.querySelector('[data-testid="history-approved-at-1"]')?.textContent?.trim();
                        const b = document.querySelector('[data-testid="history-applied-at-1"]')?.textContent?.trim();
                        return a === ts && b === ts;
                    }""",
                    arg=fixed_history_time,
                    timeout=5000,
                )
                _save_canonical_variants(page, "history", overflow_390)
            finally:
                page.evaluate(
                    "() => document.documentElement.removeAttribute('data-capture-fixed-time')"
                )
            _set_viewport_and_theme(page, 1440, 900, "light")
            page.click('[data-testid="open-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=10000)
            assert not page.locator('[data-testid="settings-folder-change"]').is_disabled()

            metrics_snapshot = {
                "docTitle": doc_title,
                "guardDiffRequestCount": len(guard_diff_requests),
                "guardDiffResponseCount": len(guard_diff_responses),
                "kindCounts": kind_counts,
                "changedFactsPills": 0,
                "changedFactsHeaderCount": 0,
                "guardHeaderText": guard_header_text,
                "headerParas": sheet_audit["headerParas"],
                "mobileSheetBox": mobile_sheet_box,
                "overflow390": overflow_390,
                "exportedHwpxSha256": exported_hwpx_sha256,
                "expectedFilledHwpxSha256": expected_filled_sha256,
                "containerSha256Match": exported_hwpx_sha256 == expected_filled_sha256,
                "zipEntriesMatch": True,
                "zipEntryCount": len(ref_names),
            }

            assert not page_errors, f"Uncaught page errors: {page_errors}"
            assert not server_errors, f"HTTP 5xx responses: {server_errors}"
            assert not api_errors, f"Unexpected API 4xx responses: {api_errors}"
            browser.close()
    finally:
        _stop_ui_server(proc)

    # 7) Save live DOM WCAG contrast audit summary
    live_contrast_output = Path(os.environ.get(LIVE_CONTRAST_ENV) or tmp_path / "live_contrast.json")
    live_contrast_output.parent.mkdir(parents=True, exist_ok=True)
    contrast_summary = {
        "schema": "rigorloom/live-contrast-audit-v1",
        "thresholdNormal": 4.5,
        "thresholdLarge": 3.0,
        "totalPairsChecked": sum(r["checked"] for r in contrast_reports),
        "totalSkippedDisabled": sum(r["skippedDisabled"] for r in contrast_reports),
        "totalFailures": sum(r["failureCount"] for r in contrast_reports),
        "surfaces": contrast_reports,
    }
    live_contrast_output.write_text(
        json.dumps(contrast_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 8) Verify canonical screenshots exist
    for fname in CANONICAL_SCREENSHOTS:
        p = DOCS_UI_DIR / fname
        assert p.is_file() and p.stat().st_size > 5000, fname

    # 9) Verify on-disk persistence: approvals JSON, events.jsonl, receipt.json
    approval_files = list((rt_root / "approvals").glob("*.json"))
    assert len(approval_files) >= 1, approval_files
    approved_records = [
        json.loads(p.read_text(encoding="utf-8")) for p in approval_files
    ]
    matched_approval = next(
        (
            rec
            for rec in approved_records
            if rec.get("state") == "approved" and rec.get("planHash") == plan_hash
        ),
        None,
    )
    assert matched_approval is not None, approved_records

    session_dir = rt_root / "sessions" / session_id
    events_path = session_dir / "events.jsonl"
    assert events_path.is_file()
    event_kinds = [
        json.loads(line).get("kind")
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for expected_kind in (
        "plan.proposed",
        "approval.requested",
        "approval.resolved",
        "plan.applied",
    ):
        assert expected_kind in event_kinds, (expected_kind, event_kinds)

    receipt_files = list((session_dir / "candidates").glob("*/receipt.json"))
    assert len(receipt_files) == 1, receipt_files
    receipt = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert receipt.get("planId") == proposed_plan["planId"]

    metrics_env = os.environ.get(WALKTHROUGH_METRICS_ENV)
    if metrics_env:
        metrics_out = Path(metrics_env)
        metrics_out.parent.mkdir(parents=True, exist_ok=True)
        metrics_snapshot["contrastSummary"] = contrast_summary
        metrics_snapshot["approvalRecord"] = matched_approval
        metrics_out.write_text(
            json.dumps(metrics_snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
