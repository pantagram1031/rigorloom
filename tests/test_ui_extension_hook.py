# -*- coding: utf-8 -*-
"""The rt_ui.py extension hook (WP2, J1 §5): routes from rt_workspace / rt_page /
rt_ui_style pass the same guards as core routes and cannot shadow them."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402

EXT = "rt_wp2_fake_extension"


def _fake_module(calls: list) -> types.ModuleType:
    mod = types.ModuleType(EXT)

    def ping(bridge, query):
        calls.append(("GET", query))
        return {"ok": True, "pong": (query.get("q") or [""])[0], "bridge": type(bridge).__name__}

    def echo(bridge, body):
        calls.append(("POST", body))
        return {"ok": True, "echo": body}

    def refuse(bridge, query):
        raise rt_ui.BridgeError("forbidden", "outside the root", status=403)

    def crash(bridge, query):
        raise RuntimeError("boom")

    def register_routes(router):
        router.get("/api/wp2-fake/ping", ping)
        router.post("/api/wp2-fake/echo", echo)
        router.get("/api/wp2-fake/refuse", refuse)
        router.get("/api/wp2-fake/crash", crash)

    mod.register_routes = register_routes
    return mod


@pytest.fixture()
def server(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setitem(sys.modules, EXT, _fake_module(calls))
    monkeypatch.setattr(rt_ui, "UI_EXTENSION_MODULES", (EXT, "rt_wp2_absent_extension"))
    srv = rt_ui.create_bridge_server(root=tmp_path, port=0, prefs_path=tmp_path / "prefs.json")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, calls
    finally:
        srv.shutdown_bridge()


def _request(srv, method, path, *, body=None, token=..., headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    hdrs = {}
    if token is ...:
        hdrs["X-Rigorloom-Token"] = srv.token
    elif token is not None:
        hdrs["X-Rigorloom-Token"] = token
    hdrs.update(headers or {})
    raw = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data.decode("utf-8") or "{}")
    finally:
        conn.close()


def test_extension_routes_are_served_with_the_token(server):
    srv, calls = server
    assert srv.extensions.modules == [EXT]
    status, payload = _request(srv, "GET", "/api/wp2-fake/ping?q=1")
    assert status == 200 and payload["pong"] == "1"
    assert payload["bridge"] == "BridgeApplication"
    status, payload = _request(srv, "POST", "/api/wp2-fake/echo", body={"a": 1})
    assert status == 200 and payload["echo"] == {"a": 1}
    assert [c[0] for c in calls] == ["GET", "POST"]


def test_unauthenticated_extension_request_is_refused(server):
    srv, calls = server
    for token in (None, "wrong-token"):
        status, _ = _request(srv, "GET", "/api/wp2-fake/ping", token=token)
        assert status in (401, 403)
        status, _ = _request(srv, "POST", "/api/wp2-fake/echo", body={}, token=token)
        assert status in (401, 403)
    assert calls == []


def test_extension_request_with_a_foreign_host_or_origin_is_refused(server):
    srv, calls = server
    status, _ = _request(srv, "GET", "/api/wp2-fake/ping", headers={"Host": "evil.example"})
    assert status in (400, 403, 421)
    status, _ = _request(
        srv, "POST", "/api/wp2-fake/echo", body={}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert status == 403
    # A page on another origin holds no token by design, but even with one it
    # never reaches an extension handler.
    for origin in ("https://evil.example", "null"):
        status, payload = _request(srv, "GET", "/api/wp2-fake/ping", headers={"Origin": origin})
        assert status == 403 and payload["error"]["code"] == "invalid_origin", origin
        status, payload = _request(
            srv, "POST", "/api/wp2-fake/echo", body={}, headers={"Origin": origin}
        )
        assert status == 403 and payload["error"]["code"] == "invalid_origin", origin
    assert calls == []
    # The bridge's own page and the desktop webview do reach it.
    for origin in (f"http://127.0.0.1:{srv.port}", "tauri://localhost"):
        status, _ = _request(srv, "GET", "/api/wp2-fake/ping", headers={"Origin": origin})
        assert status == 200, origin


def test_extension_post_body_is_capped_like_core_routes(server):
    srv, calls = server
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.putrequest("POST", "/api/wp2-fake/echo")
        conn.putheader("X-Rigorloom-Token", srv.token)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(rt_ui.MAX_JSON_BODY_BYTES + 1))
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 413
    finally:
        conn.close()
    assert calls == []


def test_extension_and_confirmation_bodies_have_their_own_small_cap(server):
    """Finding 15: routes that take a few ids answer 413 above 16 KiB, not 64 MiB."""
    srv, calls = server
    for path in ("/api/wp2-fake/echo", "/api/approval/confirmation"):
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        try:
            conn.putrequest("POST", path)
            conn.putheader("X-Rigorloom-Token", srv.token)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(rt_ui.SMALL_JSON_BODY_BYTES + 1))
            conn.endheaders()
            resp = conn.getresponse()
            assert resp.status == 413, path
        finally:
            conn.close()
    assert calls == []
    # A small body is served as before.
    status, payload = _request(srv, "POST", "/api/wp2-fake/echo", body={"a": "x" * 1000})
    assert status == 200 and payload["echo"] == {"a": "x" * 1000}


def test_bridge_responses_refuse_framing(server):
    """Finding 19: every bridge answer says no page may frame it."""
    srv, _ = server
    for path in ("/api/wp2-fake/ping", "/api/prefs"):
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        try:
            conn.request("GET", path, headers={"X-Rigorloom-Token": srv.token})
            resp = conn.getresponse()
            resp.read()
            assert resp.getheader("Content-Security-Policy") == "frame-ancestors 'none'", path
            assert resp.getheader("X-Content-Type-Options") == "nosniff", path
        finally:
            conn.close()


def test_extension_errors_keep_the_server_alive(server):
    srv, _ = server
    status, payload = _request(srv, "GET", "/api/wp2-fake/refuse")
    assert status == 403 and payload["error"]["code"] == "forbidden"
    status, payload = _request(srv, "GET", "/api/wp2-fake/crash")
    assert status == 500 and payload["error"]["code"] == "internal_error"
    status, payload = _request(srv, "GET", "/api/wp2-fake/ping")
    assert status == 200


def test_unknown_paths_still_404(server):
    srv, _ = server
    status, payload = _request(srv, "GET", "/api/wp2-fake/nope")
    assert status == 404
    status, payload = _request(srv, "POST", "/api/wp2-fake/nope", body={})
    assert status == 404


def test_router_refuses_shadowing_and_non_api_paths():
    router = rt_ui.ExtensionRouter()
    with pytest.raises(ValueError):
        router.get("/api/prefs", lambda b, q: {})
    with pytest.raises(ValueError):
        router.post("/api/export", lambda b, q: {})
    with pytest.raises(ValueError):
        router.get("/rpc", lambda b, q: {})
    with pytest.raises(ValueError):
        router.get("/api/../prefs", lambda b, q: {})
    with pytest.raises(ValueError):
        router.get("/events", lambda b, q: {})
    router.get("/api/workspace/list", lambda b, q: {})
    with pytest.raises(ValueError):
        router.get("/api/workspace/list", lambda b, q: {})


def test_core_route_tables_match_the_handler():
    """The shadow lists must name every core /api/ path the handler serves."""
    source = (RUNTIME_SCRIPTS / "rt_ui.py").read_text(encoding="utf-8")
    handler = source[source.index("class BridgeHTTPHandler"):]
    get_paths = set(
        p for p in __import__("re").findall(r'path == "(/api/[^"]+)"', handler)
    )
    post_paths = set(__import__("re").findall(r'"(/api/[^"]+)": ', handler))
    assert get_paths <= rt_ui._CORE_GET_API_PATHS
    assert post_paths <= rt_ui._CORE_POST_API_PATHS


def test_absent_extensions_are_skipped_and_default_names_are_fixed():
    assert rt_ui.UI_EXTENSION_MODULES == ("rt_workspace", "rt_page", "rt_ui_style", "rt_ui_doc")
    router = rt_ui.load_ui_extensions(("rt_wp2_definitely_absent",))
    assert router.get_routes == {} and router.post_routes == {} and router.modules == []
