# -*- coding: utf-8 -*-
"""The loopback bridge refuses a request whose Origin is not its own kind.

Every route, core or extension, passes the Host/Origin guard before the token
is even looked at: a page served from another origin (or an opaque "null"
one) gets 403 `invalid_origin`. A loopback page and the desktop app's webview
(`tauri://localhost`, `http://tauri.localhost`) pass, and so does a request
with no Origin at all (a same-origin GET, or a local client).
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import sys
import threading

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402


@pytest.fixture()
def bridge(tmp_path: Path):
    srv = rt_ui.create_bridge_server(
        root=tmp_path / "rt-root",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
        auto_start=False,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def _request(srv, method: str, path: str, origin: str | None, body: dict | None = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    headers = {"X-Rigorloom-Token": srv.token, "Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    raw = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    try:
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, (json.loads(data.decode("utf-8")) if data else {})
    finally:
        conn.close()


FOREIGN = (
    "https://evil.example",
    "http://evil.example:8765",
    "null",
    "file://",
    "https://127.0.0.1:8765",
    "http://127.0.0.1@evil.example",
    "http://127.0.0.1:8765/extra",
    "tauri://evil.example",
    "http://tauri.localhost.evil.example",
)


@pytest.mark.parametrize("path", ["/api/prefs", "/api/workspace/list"])
def test_a_foreign_origin_is_refused_on_get(bridge, path):
    for origin in FOREIGN:
        status, data = _request(bridge, "GET", path, origin)
        assert status == 403, (origin, status, data)
        assert data["error"]["code"] == "invalid_origin", (origin, data)


def test_a_foreign_origin_is_refused_on_post(bridge):
    for origin in ("https://evil.example", "null"):
        status, data = _request(bridge, "POST", "/rpc", origin, {"method": "session/list", "params": {}})
        assert status == 403 and data["error"]["code"] == "invalid_origin", (origin, data)
        status, data = _request(bridge, "POST", "/api/approval/confirmation", origin, {})
        assert status == 403 and data["error"]["code"] == "invalid_origin", (origin, data)


def test_a_loopback_page_and_the_desktop_webview_pass(bridge):
    for origin in (
        None,
        f"http://127.0.0.1:{bridge.port}",
        f"http://localhost:{bridge.port}",
        "http://localhost:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ):
        status, data = _request(bridge, "GET", "/api/prefs", origin)
        assert status == 200, (origin, status, data)
