# -*- coding: utf-8 -*-
"""The v1 review UI is still main's v1, at the default URL and at `?ui=v1`.

Editor v2 reaches main in several pull requests while v1 stays the default.
`tests/fixtures/ui_v1_identity.json` records main dbc1b18's five v1 screens
(열기, 검토, 채우기, 기록, 설정) and its toast, 1440 px in light and dark: the
normalized DOM and a digest of every element's computed style. This test
captures the committed bundle the same way and requires both captures to match,
so a v2 token, stylesheet or component that changes what a v1 user sees fails
here. `tests/_v1_identity.py` explains how the fixture was recorded.
"""
from __future__ import annotations

import json

import pytest

from _browser_gate import no_browser  # noqa: E402
import _v1_identity as v1  # noqa: E402

UI_DIST = v1.SCRIPTS / "ui_dist"


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        no_browser(f"playwright unavailable: {exc}")
    if not (UI_DIST / "index.html").is_file():
        pytest.skip("ui_dist not built")
    mp = pytest.MonkeyPatch()
    mp.delenv("RIGORLOOM_DEV_MOCK_AGENT", raising=False)
    out = {}
    try:
        with sync_playwright() as pw:
            try:
                browser = v1.launch_browser(pw)
            except Exception as exc:  # pragma: no cover - environment dependent
                no_browser(f"headless Chromium unavailable: {exc}")
            try:
                # A fresh bridge per URL: the v1 UI reopens a session the
                # bridge already holds, so the second run would skip 열기.
                for label, query in (("default", ""), ("?ui=v1", "?ui=v1")):
                    tmp = tmp_path_factory.mktemp("v1-identity")
                    mp.setenv("XDG_DATA_HOME", str(tmp / "xdg"))
                    server, thread = v1.start_bridge(tmp)
                    try:
                        out[label] = v1.capture_v1(browser, server.url, query=query)
                    finally:
                        server.shutdown_bridge()
                        thread.join(timeout=5)
            finally:
                browser.close()
    finally:
        mp.undo()
    return out


@pytest.fixture(scope="module")
def expected():
    screens = v1.load_fixture()
    # The fixture covers every screen in both themes, plus the toast.
    for name in (*v1.SCREENS, "toast"):
        for theme in v1.THEMES:
            assert screens.get(f"{name}-{theme}"), f"fixture lacks {name}-{theme}"
    return screens


@pytest.mark.parametrize("url", ["default", "?ui=v1"])
def test_v1_screens_match_main(captures, expected, url):
    problems = v1.compare(expected, captures[url])
    assert not problems, f"v1 at {url} differs from main dbc1b18:\n" + "\n".join(problems)


def test_the_comparison_catches_a_restyled_toast(expected):
    """The detector itself: one changed colour or DOM attribute is reported."""
    actual = json.loads(json.dumps(expected))
    toast = actual["toast-light"][0]
    toast["style"] = "0" * 16
    toast["key"] = {**toast["key"], "background-color": "rgb(27, 27, 26)"}
    actual["open-dark"][0]["attrs"] = {**actual["open-dark"][0]["attrs"], "data-probe": "1"}
    problems = v1.compare(expected, actual)
    assert any(p.startswith("toast-light") and "rgb(27, 27, 26)" in p for p in problems), problems
    assert any(p.startswith("open-dark") and "data-probe" in p for p in problems), problems
    assert len(problems) == 2, problems
