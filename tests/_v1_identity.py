# -*- coding: utf-8 -*-
"""Record and compare the v1 review UI, screen by screen.

The editor v2 work reaches main in several pull requests while v1 stays the
default UI. This module captures what a person sees on the five v1 screens
(열기, 검토, 채우기, 기록, 설정) and the toast, at 1440 px in light and dark:

- a normalized DOM: tag, attributes and own text of every element;
- a digest of every element's computed style, including ::before and ::after
  (custom properties left out: they show only through the properties that
  read them).

`tests/fixtures/ui_v1_identity.json` holds main dbc1b18's capture.
`tests/test_ui_v1_identity.py` captures the current bundle, at the default URL
and at `?ui=v1`, and compares.

Re-record only from main's bundle (the fixture is main's v1, not the branch's):

    git archive dbc1b18 runtime/scripts/ui_dist | tar -x -C /tmp/main-ui
    python tests/_v1_identity.py --ui-dist /tmp/main-ui/runtime/scripts/ui_dist \
        --out tests/fixtures/ui_v1_identity.json
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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "runtime" / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ui_v1_identity.json"
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

_CAPTURE_JS = r"""
({ rootSelector, skip }) => {
  const SKIP = new Set(skip);
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
    const kids = Array.from(el.children);
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
    entries = page.evaluate(_CAPTURE_JS, {"rootSelector": selector, "skip": _GEOMETRY_PROPS})
    assert entries is not None, f"nothing matches {selector}"
    return _normalize(entries, replacements)


def start_bridge(tmp: Path, ui_dist: Path | None = None):
    """Start the browser bridge in this process; `ui_dist` overrides the bundle."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import rt_ui  # noqa: PLC0415

    if ui_dist is not None:
        dist = ui_dist.resolve()
        rt_ui.BridgeApplication._ui_dist_dir = lambda self: dist  # type: ignore[method-assign]
    server = rt_ui.create_bridge_server(
        root=tmp / "rt-root",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp / "prefs.json",
        auto_start=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def capture_v1(browser, base_url: str, *, query: str = "") -> dict[str, Any]:
    """Drive the v1 screens at `base_url + query` and capture each one."""
    context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, color_scheme="light")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(base_url + query, wait_until="domcontentloaded")
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
    """Fixture form: each distinct style digest's key properties are stored once."""
    styles: dict[str, Any] = {}
    packed: dict[str, Any] = {}
    for name, entries in screens.items():
        rows = []
        for entry in entries:
            styles.setdefault(entry["style"], entry["key"])
            rows.append({k: v for k, v in entry.items() if k != "key"})
        packed[name] = rows
    return {"screens": packed, "styles": styles}


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    """The fixture's screens, with each element's key properties restored."""
    data = json.loads(path.read_text(encoding="utf-8"))
    styles = data["styles"]
    return {
        name: [{**row, "key": styles.get(row["style"], {})} for row in rows]
        for name, rows in data["screens"].items()
    }


def record(ui_dist: Path | None, out: Path, query: str = "") -> None:
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
        "about": "main dbc1b18 v1 screens; written by tests/_v1_identity.py",
        "viewport": [WIDTH, HEIGHT],
        **pack(screens),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # One element per line keeps a re-recorded fixture reviewable as a diff.
    lines = lines.replace('},{"attrs"', '},\n{"attrs"')
    out.write_text(lines + "\n", encoding="utf-8")
    print(f"wrote {out} ({sum(len(v) for v in screens.values())} elements)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ui-dist", type=Path, help="bundle to capture (default: runtime/scripts/ui_dist)")
    parser.add_argument("--out", type=Path, default=FIXTURE)
    parser.add_argument("--query", default="", help="URL query to open, e.g. ?ui=v1")
    args = parser.parse_args()
    record(args.ui_dist, args.out, args.query)


if __name__ == "__main__":
    main()
