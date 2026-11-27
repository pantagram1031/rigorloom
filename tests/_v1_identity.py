# -*- coding: utf-8 -*-
"""Record and compare the v1 review UI, screen by screen.

The editor v2 work reaches main in several pull requests while v1 stays the
default UI. This module captures what a person sees on the five v1 screens
(열기, 검토, 채우기, 기록, 설정) and the toast, at 1440 px in light and dark:

- a normalized DOM: tag, attributes and own text of every element;
- a digest of every element's computed style, including ::before and ::after
  (custom properties left out: they show only through the properties that
  read them).

`tests/fixtures/v1_main_ui_dist/` is main's committed bundle after PR #403
(T189, the brand pull request), copied unchanged. `tests/test_ui_v1_identity.py` captures that
bundle and the current one with the same runtime, browser and fonts, at the
default URL and at `?ui=v1`, and compares. Capturing both on the same
machine keeps what depends on the machine (a preview that cannot render, font
metrics) out of the result.

Rules for `tests/fixtures/v1_main_ui_dist/` (set by the advisor):

1. The folder exists so that this test fails on an unintended v1 change.
2. It is refreshed only when an intentional change is one the captures can
   see: the DOM or the computed style of the five screens and the toast at
   1440 px, light and dark. That is exactly when this test would fail without
   a refresh. The brand pull request and the final switch to editor v2
   refresh it regardless. The refreshing pull request replaces the folder
   with its own rebuilt bundle, names the refresh in its CHANGELOG line and
   keeps this test green.
3. A copy change the captures never show gets no refresh; its CHANGELOG line
   names the change instead.
4. Each refresh adds about 730 KB to the history.
5. A section added to v1 on purpose, as a whole new subtree, may instead be
   listed in `INTENDED_V1_ADDITIONS` by its `data-testid`, with its T number
   in the comment. The captures leave that subtree out and count sibling
   positions without it; its CHANGELOG line says so. A change to any element
   that already existed still needs a refresh under rule 2.

The folder currently holds main after PR #403 (T189); before it, the folder
held main dbc1b18's bundle.

To look at one capture by hand:

    python tests/_v1_identity.py --ui-dist tests/fixtures/v1_main_ui_dist \
        --out /tmp/main-v1.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "runtime" / "scripts"
MAIN_UI_DIST = Path(__file__).resolve().parent / "fixtures" / "v1_main_ui_dist"
SAMPLE = "gianmun-byeolji-1ho.hwpx"
SCREENS = ("open", "review", "fill", "history", "settings")
THEMES = ("light", "dark")
WIDTH, HEIGHT = 1440, 900

# Used values that follow box geometry or font metrics rather than the
# stylesheet; they change with the fonts a machine has, not with the UI.
_GEOMETRY_PROPS = [
    "width", "height", "inline-size", "block-size",
    "top", "right", "bottom", "left",
    "inset-block-start", "inset-block-end", "inset-inline-start", "inset-inline-end",
    "transform-origin", "perspective-origin",
]

# Sections the v1 screens gained on purpose after PR #403. Each subtree is
# left out of both captures, and sibling positions are counted without it, so
# everything else on the screen must still match main exactly.
INTENDED_V1_ADDITIONS = (
    "settings-section-editor",  # T237: 설정 > 편집기, the way back to the new editor
)

_CAPTURE_JS = r"""
({ rootSelector, skip, exclude }) => {
  const SKIP = new Set(skip);
  const EXCLUDE = new Set(exclude);
  const hash = (str) => {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761);
      h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0");
  };
  const styleText = (cs) => {
    const parts = [];
    for (let i = 0; i < cs.length; i++) {
      const name = cs[i];
      // Custom properties are not seen; a v1 rule that reads a new one shows
      // up in the real property it sets.
      if (SKIP.has(name) || name.startsWith("--")) continue;
      parts.push(name + ":" + cs.getPropertyValue(name));
    }
    parts.sort();
    return parts.join(";");
  };
  const KEY = ["color", "background-color", "box-shadow", "border-top-color",
               "font-family", "font-size", "font-weight", "display"];
  const keyProps = (cs) => Object.fromEntries(KEY.map((k) => [k, cs.getPropertyValue(k)]));
  const root = document.querySelector(rootSelector);
  if (!root) return null;
  const out = [];
  const walk = (el, path) => {
    const cs = getComputedStyle(el);
    const before = getComputedStyle(el, "::before");
    const after = getComputedStyle(el, "::after");
    const pseudo = (p) => (p.content && p.content !== "none" ? styleText(p) : "");
    const attrs = {};
    for (const a of Array.from(el.attributes)) attrs[a.name] = a.value;
    let text = "";
    for (const n of Array.from(el.childNodes)) {
      if (n.nodeType === Node.TEXT_NODE) text += n.nodeValue;
    }
    out.push({
      path,
      tag: el.tagName.toLowerCase(),
      attrs,
      text: text.replace(/\s+/g, " ").trim(),
      style: hash(styleText(cs) + "|" + pseudo(before) + "|" + pseudo(after)),
      key: keyProps(cs),
    });
    const kids = Array.from(el.children).filter((c) => !EXCLUDE.has(c.getAttribute("data-testid")));
    kids.forEach((child, i) => walk(child, path + "/" + child.tagName.toLowerCase() + "[" + i + "]"));
  };
  walk(root, root.tagName.toLowerCase());
  return out;
}
"""

# Values that differ run to run, not UI to UI.
_VOLATILE_ATTRS = {"data-session", "data-full-hash"}


def _normalize(entries: list[dict[str, Any]], replacements: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    previous_text = ""
    for entry in entries:
        attrs = {}
        for name, value in sorted(entry["attrs"].items()):
            if name in _VOLATILE_ATTRS:
                value = "<volatile>"
            for raw, label in replacements.items():
                if raw:
                    value = value.replace(raw, label)
            attrs[name] = value
        text = entry["text"]
        for raw, label in replacements.items():
            if raw:
                text = text.replace(raw, label)
        if entry["tag"] == "dd" and "프로세스" in previous_text:
            # Settings > 자세히 lists the sidecar's process id.
            text = re.sub(r"\d+", "<n>", text)
        previous_text = entry["text"]
        out.append({**entry, "attrs": attrs, "text": text})
    return out


def _settle(page) -> None:
    page.evaluate("() => document.getAnimations().forEach((a) => { try { a.finish(); } catch {} })")
    page.wait_for_timeout(350)
    page.evaluate("() => document.getAnimations().forEach((a) => { try { a.finish(); } catch {} })")


def _set_theme(page, theme: str) -> None:
    page.emulate_media(color_scheme=theme)
    page.evaluate(
        """(t) => {
            document.documentElement.setAttribute('data-theme', t);
            try { window.localStorage.setItem('rigorloom.theme', t); } catch {}
        }""",
        theme,
    )
    _settle(page)


def _capture(page, selector: str, replacements: dict[str, str]) -> list[dict[str, Any]]:
    entries = page.evaluate(
        _CAPTURE_JS,
        {"rootSelector": selector, "skip": _GEOMETRY_PROPS, "exclude": list(INTENDED_V1_ADDITIONS)},
    )
    assert entries is not None, f"nothing matches {selector}"
    return _normalize(entries, replacements)


def start_bridge(tmp: Path, ui_dist: Path | None = None):
    """Start the browser bridge in this process; `ui_dist` overrides the bundle."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import rt_ui  # noqa: PLC0415

    server = rt_ui.create_bridge_server(
        root=tmp / "rt-root",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp / "prefs.json",
        auto_start=True,
    )
    if ui_dist is not None:
        # Only this server's bridge serves the other bundle.
        dist = ui_dist.resolve()
        server.bridge._ui_dist_dir = lambda: dist  # type: ignore[method-assign]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _v1_url(url: str) -> str:
    """`url` with `ui=v1` in its query, keeping any other parameters."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "ui"]
    query.append(("ui", "v1"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))


v1_url = _v1_url


def capture_v1(browser, base_url: str, *, query: str = "?ui=v1") -> dict[str, Any]:
    """Drive the v1 screens at `base_url + query` and capture each one."""
    context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, color_scheme="light")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        target = base_url + query if query else _v1_url(base_url)
        page.goto(target, wait_until="domcontentloaded")
        splash = page.locator('[data-testid="splash"]')
        try:
            splash.first.click(force=True, timeout=3000)
        except Exception:
            pass
        try:
            page.wait_for_selector('[data-testid="open-view"]', timeout=20000)
        except Exception as exc:
            body = page.evaluate("() => document.body.innerText.slice(0, 400)")
            raise AssertionError(f"the 열기 screen did not appear: {body!r} {errors}") from exc
        sample_list = page.locator('[data-testid="open-sample-list"]')
        if sample_list.count() == 0 or not sample_list.is_visible():
            page.click('[data-testid="open-samples-toggle"]')
        page.wait_for_selector(f'[data-testid="open-sample-item-{SAMPLE}"]', timeout=20000)
        bootstrap = page.evaluate("() => window.__RIGORLOOM_UI__ || {}")
        replacements = {
            str(bootstrap.get("token", "")): "<token>",
            str(bootstrap.get("root", "")): "<root>",
        }

        screens: dict[str, Any] = {}

        def grab(name: str) -> None:
            for theme in THEMES:
                _set_theme(page, theme)
                screens[f"{name}-{theme}"] = _capture(page, "#root", replacements)
            _set_theme(page, "light")

        grab("open")

        # The toast: Ctrl+0 resets the zoom and announces 100%.
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        for theme in THEMES:
            _set_theme(page, theme)
            page.keyboard.press("Control+0")
            page.wait_for_selector('[data-testid="toast"]', timeout=5000)
            page.evaluate("() => document.getAnimations().forEach((a) => { try { a.finish(); } catch {} })")
            screens[f"toast-{theme}"] = _capture(page, '[data-testid="toast"]', replacements)
            page.wait_for_selector('[data-testid="toast"]', state="detached", timeout=10000)
        _set_theme(page, "light")

        page.click(f'[data-testid="open-sample-item-{SAMPLE}"]')
        page.wait_for_selector('[data-testid="review-view"]', timeout=20000)
        page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=20000)
        session = page.locator(".shell").get_attribute("data-session") or ""
        if session:
            replacements[session] = "<session>"
        page.wait_for_timeout(600)
        grab("review")

        for name in ("fill", "history", "settings"):
            nav = "open-settings" if name == "settings" else f"nav-{name}"
            page.click(f'[data-testid="{nav}"]')
            page.wait_for_selector(f'[data-testid="{name}-view"]', timeout=20000)
            if name == "fill":
                page.wait_for_selector('[data-testid="page-cell-0-5-1"]', timeout=20000)
            page.wait_for_timeout(400)
            grab(name)
        assert not errors, errors
        return screens
    finally:
        context.close()


def launch_browser(pw):
    exe = os.environ.get("RL_CHROMIUM")
    if exe:
        return pw.chromium.launch(headless=True, executable_path=exe)
    return pw.chromium.launch(headless=True)


def compare(expected: dict[str, Any], actual: dict[str, Any], *, limit: int = 12) -> list[str]:
    """Human-readable differences, empty when the two captures match."""
    problems: list[str] = []
    for name in sorted(set(expected) | set(actual)):
        if name not in actual:
            problems.append(f"{name}: not captured")
            continue
        if name not in expected:
            problems.append(f"{name}: not in the fixture")
            continue
        exp = {e["path"]: e for e in expected[name]}
        act = {e["path"]: e for e in actual[name]}
        shown = 0
        for path in list(exp) + [p for p in act if p not in exp]:
            e, a = exp.get(path), act.get(path)
            if e is None or a is None:
                problems.append(f"{name} {path}: {'added' if e is None else 'missing'}")
            elif e["tag"] != a["tag"] or e["attrs"] != a["attrs"] or e["text"] != a["text"]:
                problems.append(f"{name} {path}: DOM {e['tag']} {e['attrs']} {e['text']!r} -> {a['tag']} {a['attrs']} {a['text']!r}")
            elif e["style"] != a["style"]:
                changed = {k: (e["key"].get(k), v) for k, v in a["key"].items() if e["key"].get(k) != v}
                problems.append(f"{name} {path} <{a['tag']} class={a['attrs'].get('class', '')!r}>: computed style differs {changed or '(outside the key properties)'}")
            else:
                continue
            shown += 1
            if shown >= limit:
                problems.append(f"{name}: more differences not shown")
                break
    return problems


def pack(screens: dict[str, Any]) -> dict[str, Any]:
    """File form: each distinct style digest's key properties are stored once."""
    styles: dict[str, Any] = {}
    packed: dict[str, Any] = {}
    for name, entries in screens.items():
        rows = []
        for entry in entries:
            styles.setdefault(entry["style"], entry["key"])
            rows.append({k: v for k, v in entry.items() if k != "key"})
        packed[name] = rows
    return {"screens": packed, "styles": styles}


def record(ui_dist: Path | None, out: Path, query: str = "?ui=v1") -> None:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_DATA_HOME"] = str(Path(tmp) / "xdg")
        os.environ.pop("RIGORLOOM_DEV_MOCK_AGENT", None)
        server, thread = start_bridge(Path(tmp), ui_dist)
        try:
            with sync_playwright() as pw:
                browser = launch_browser(pw)
                try:
                    screens = capture_v1(browser, server.url, query=query)
                finally:
                    browser.close()
        finally:
            server.shutdown_bridge()
            thread.join(timeout=5)
    payload = {
        "about": "v1 screens written by tests/_v1_identity.py",
        "viewport": [WIDTH, HEIGHT],
        **pack(screens),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # One element per line keeps two captures comparable with diff.
    lines = lines.replace('},{"attrs"', '},\n{"attrs"')
    out.write_text(lines + "\n", encoding="utf-8")
    print(f"wrote {out} ({sum(len(v) for v in screens.values())} elements)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ui-dist", type=Path, help="bundle to capture (default: runtime/scripts/ui_dist)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--query", default="?ui=v1", help="URL query to open, e.g. ?ui=v1")
    args = parser.parse_args()
    record(args.ui_dist, args.out, args.query)


if __name__ == "__main__":
    main()
