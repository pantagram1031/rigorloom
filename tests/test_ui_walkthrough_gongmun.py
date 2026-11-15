"""End-to-end gongmun walkthrough Playwright verification and canonical screenshot capture.

Covers:
1. Clean `pytest.skip` when `playwright` or headless Chromium is unavailable.
2. Live subprocess launch (`cli.py ui --root <tmp> --port 0 --no-open`) with zero
   uncaught `pageerror`s and zero HTTP 5xx / unexpected API 4xx responses.
3. Opening real corpus form `gianmun-byeolji-1ho.hwpx` via Open screen.
4. Proposing the deterministic 24-op `examples/gongmun/expected/plan.json` plan +
   external `approval/request` via `/rpc`, verifying automatic UI adoption of all
   24 changes (`change-row-1..24`), collapsed row height <= 56 px, and bidirectional
   marker <-> row selection synchronization.
5. Capturing the 8 canonical PNGs in `docs/ui/`:
   `{open,review}-{1440,390}-{light,dark}.png`, verifying `scrollWidth <= innerWidth`
   at 390 px across mobile tabs.
6. Automated surface-leak checks (no raw file paths, no raw event names, no
   32-hex IDs outside `<details>` or `.approval-hash`, no internal schema jargon,
   and zero forbidden strings).
7. Live DOM WCAG 2.1 contrast audit across Open & Review light/dark (>= 4.5:1 on
   all enabled visible text elements), writing results to `scratch/live_contrast.json`.
8. Approving and exporting `.hwpx` ZIP, then verifying on-disk persistence under
   `approvals/<approvalId>.json`, `sessions/<sessionId>/events.jsonl`, and
   `sessions/<sessionId>/candidates/<runId>/receipt.json`.
"""

from __future__ import annotations

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
CORPUS_FORM_FILENAME = "gianmun-byeolji-1ho.hwpx"
LIVE_CONTRAST_OUTPUT = Path(
    os.environ.get(
        "RIGORLOOM_LIVE_CONTRAST_OUT",
        "/home/ubuntu/.gemini/antigravity-cli/brain/6c4670bc-d333-4cdf-a615-d794a28c7218/scratch/live_contrast.json",
    )
)

CANONICAL_SCREENSHOTS = [
    f"{screen}-{width}-{theme}.png"
    for screen in ("open", "review")
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


def _save_canonical_variants(page, screen: str) -> None:
    DOCS_UI_DIR.mkdir(parents=True, exist_ok=True)
    for width, height in ((1440, 900), (390, 844)):
        for theme in ("light", "dark"):
            _set_viewport_and_theme(page, width, height, theme)
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
    contrast_reports: list[dict] = []

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

            # 1) Load Open view, check surface cleanliness & contrast, capture Open canonical PNGs
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

            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"open-1440-{theme}")
                report = _audit_live_dom_contrast(page, "open", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )

            _save_canonical_variants(page, "open")
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 2) Open gianmun-byeolji-1ho.hwpx and propose 24-op gongmun plan + approval/request via /rpc
            page.click(f'[data-testid="open-sample-item-{CORPUS_FORM_FILENAME}"]')
            page.wait_for_selector('[data-testid="review-view"]', timeout=15000)
            page.wait_for_selector('[data-testid="page-sheet"]', timeout=15000)

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

            # 3) Verify auto-adoption of all 24 changes & guard readiness
            page.wait_for_selector('[data-testid="change-row-24"]', timeout=20000)
            page.wait_for_selector('[data-testid="guard-list-header"]', timeout=20000)
            page.wait_for_function(
                "() => document.querySelectorAll('[data-testid^=\"change-pill-\"]').length >= 23",
                timeout=20000,
            )

            rows = page.locator('[data-testid^="change-row-"]')
            assert rows.count() == 24
            for i in range(rows.count()):
                box = rows.nth(i).bounding_box()
                assert box is not None and box["height"] <= 56.5, (i + 1, box)

            # 4) Bidirectional marker <-> row sync
            marker_1 = page.locator('[data-testid="page-marker-1"]').first
            marker_1.scroll_into_view_if_needed()
            marker_1.click()
            assert (
                page.locator('[data-testid="change-row-1"]').get_attribute("aria-selected")
                == "true"
            )

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

            # 5) Check live DOM contrast & surface cleanliness on Review 1440 light/dark
            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 1440, 900, theme)
                _assert_surface_clean(page, f"review-1440-{theme}")
                report = _audit_live_dom_contrast(page, "review", theme)
                contrast_reports.append(report)
                assert report["failureCount"] == 0, json.dumps(
                    report["failures"], ensure_ascii=False
                )

            # Also verify 390px mobile tabs (sheet and list) both render with zero overflow
            for theme in ("light", "dark"):
                _set_viewport_and_theme(page, 390, 844, theme)
                page.click('[data-testid="review-mobile-tab-list"]')
                page.wait_for_timeout(100)
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                inner_w = page.evaluate("window.innerWidth")
                assert scroll_w <= inner_w, (scroll_w, inner_w)
                page.click('[data-testid="review-mobile-tab-sheet"]')
                page.wait_for_timeout(100)

            _save_canonical_variants(page, "review")
            _set_viewport_and_theme(page, 1440, 900, "light")

            # 6) Approve via ApprovalDialog and export verified .hwpx ZIP
            page.click('[data-testid="review-approve-btn"]')
            page.wait_for_selector('[data-testid="approval-dialog"]', timeout=10000)

            plan_hash = page.locator('[data-testid="approval-plan-hash"]').inner_text().strip()
            assert re.fullmatch(r"[0-9a-f]{64}", plan_hash), plan_hash

            page.wait_for_function(
                "() => !document.querySelector('.approval-guard-note:not(.approval-guard-note--warn)')",
                timeout=15000,
            )
            ack = page.locator('[data-testid="approval-changed-facts-ack"]')
            if ack.count() > 0 and ack.is_visible() and not ack.is_checked():
                ack.check()
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-testid=\"approval-confirm-btn\"]'); return b && !b.disabled; }",
                timeout=10000,
            )
            page.click('[data-testid="approval-confirm-btn"]')

            page.wait_for_selector('[data-testid="review-export-btn"]', timeout=30000)
            with page.expect_download(timeout=15000) as dl_info:
                page.click('[data-testid="review-export-btn"]')
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

    # 7) Save live DOM WCAG contrast audit summary
    LIVE_CONTRAST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    contrast_summary = {
        "schema": "rigorloom/live-contrast-audit-v1",
        "thresholdNormal": 4.5,
        "thresholdLarge": 3.0,
        "totalPairsChecked": sum(r["checked"] for r in contrast_reports),
        "totalSkippedDisabled": sum(r["skippedDisabled"] for r in contrast_reports),
        "totalFailures": sum(r["failureCount"] for r in contrast_reports),
        "surfaces": contrast_reports,
    }
    LIVE_CONTRAST_OUTPUT.write_text(
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
    assert any(
        rec.get("state") == "approved" and rec.get("planHash") == plan_hash
        for rec in approved_records
    ), approved_records

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
