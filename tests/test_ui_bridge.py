# -*- coding: utf-8 -*-
"""Bridge tests: CLI wiring, packaging allowlist, HTTP/SSE security, /api/*, guard, export."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
from pathlib import Path
import queue
import re
import select
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
CORPUS_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import cli  # noqa: E402
import rt_ui  # noqa: E402


class _BridgeClient:
    """Minimal stdlib HTTP/1.1 + SSE helper bound to a test BridgeHTTPServer."""

    def __init__(self, server: rt_ui.BridgeHTTPServer) -> None:
        self.server = server
        self.host = "127.0.0.1"
        self.port = server.port
        self.token = server.token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str | None = ...,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=90)
        hdrs: dict[str, str] = {}
        if token is ...:
            hdrs["X-Rigorloom-Token"] = self.token
        elif token is not None:
            hdrs["X-Rigorloom-Token"] = token
        if headers:
            hdrs.update(headers)
        raw: bytes | None = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=raw, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, resp.headers, data
        finally:
            conn.close()

    def get_json(self, path: str, **kwargs) -> tuple[int, dict]:
        status, _, data = self.request("GET", path, **kwargs)
        return status, json.loads(data.decode("utf-8"))

    def post_json(self, path: str, body: dict | None = None, **kwargs) -> tuple[int, dict]:
        status, _, data = self.request("POST", path, body=body if body is not None else {}, **kwargs)
        return status, json.loads(data.decode("utf-8"))

    def rpc(self, method: str, params: dict | None = None, *, tag: str | None = None) -> dict:
        payload: dict = {"method": method, "params": params or {}}
        if tag is not None:
            payload["tag"] = tag
        status, data = self.post_json("/rpc", payload)
        assert status == 200
        return data

    def open_sse(self) -> tuple[http.client.HTTPResponse, queue.Queue[tuple[str, object]], threading.Event]:
        resp = urllib.request.urlopen(f"{self.server.url}events?token={self.token}", timeout=10)
        out_q: queue.Queue[tuple[str, object]] = queue.Queue()
        stop = threading.Event()

        def reader() -> None:
            event_name = "message"
            data_lines: list[str] = []
            try:
                while not stop.is_set():
                    raw = resp.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line == "":
                        if data_lines:
                            raw_payload = "\n".join(data_lines)
                            try:
                                parsed: object = json.loads(raw_payload)
                            except json.JSONDecodeError:
                                parsed = raw_payload
                            out_q.put((event_name, parsed))
                            event_name = "message"
                            data_lines = []
                    elif line.startswith(":"):
                        continue
                    elif line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
            except OSError:
                pass

        threading.Thread(target=reader, daemon=True).start()
        return resp, out_q, stop


@pytest.fixture()
def started_bridge(tmp_path: Path):
    rt_root = tmp_path / "rt-root"
    prefs_file = tmp_path / "ui-prefs.json"
    srv = rt_ui.create_bridge_server(
        root=rt_root,
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=prefs_file,
        auto_start=True,
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, _BridgeClient(srv), rt_root
    finally:
        srv.shutdown_bridge()
        thread.join(timeout=5)


def test_pyproject_package_data_and_cli_ui_subcommand(tmp_path: Path, monkeypatch):
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    st_cfg = pyproject["tool"]["setuptools"]
    assert st_cfg["packages"] == ["rigorloom_runtime", "rigorloom_runtime.style_packs"]
    assert st_cfg["include-package-data"] is False
    assert st_cfg["package-dir"] == {
        "rigorloom_runtime": "runtime/scripts",
        "rigorloom_runtime.style_packs": "runtime/style_packs",
    }
    assert st_cfg["package-data"] == {
        # knowledge/*.md: the guide topics and the MCP server's instructions.
        "rigorloom_runtime": ["ui_dist/*", "ui_dist/assets/*", "knowledge/*.md"],
        "rigorloom_runtime.style_packs": ["*.json"],
    }

    # Global --root must stay un-defaulted so `capabilities` without --root exits 2.
    parser = cli.build_parser()
    assert parser.get_default("root") is None
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["capabilities"])
    assert exc_info.value.code == 2

    # XDG_DATA_HOME drives default ui root when neither --root nor ui --root is given.
    xdg_dir = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_dir))
    assert rt_ui.default_runtime_root() == xdg_dir / "rigorloom" / "runtime-root"

    captured: dict = {}
    monkeypatch.setattr(rt_ui, "run_ui", lambda **kw: captured.update(kw) or 0)
    assert cli.main(["ui", "--port", "0", "--no-open"]) == 0
    assert captured == {
        "root": None,
        "engine_root": None,
        "port": 0,
        "no_open": True,
        "explicit_root": False,
    }
    captured.clear()
    assert cli.main(["ui", "--root", str(tmp_path / "custom"), "--port", "9123"]) == 0
    assert captured["root"] == tmp_path / "custom"
    assert captured["port"] == 9123
    assert captured["no_open"] is False
    assert captured["explicit_root"] is True


def test_http_security_bootstrap_and_static_fallback(tmp_path: Path):
    srv = rt_ui.create_bridge_server(
        root=tmp_path / "rt",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
        auto_start=False,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    client = _BridgeClient(srv)
    try:
        # Invalid Host header is rejected 403.
        s, _, _ = client.request("GET", "/", token=None, headers={"Host": "evil.example:8080"})
        assert s == 403
        s, _, _ = client.request("POST", "/rpc", body={"method": "capabilities/list"}, headers={"Host": "10.0.0.1:8765"})
        assert s == 403

        # Cross-site fetch on HTML index is refused 403.
        s, _, _ = client.request("GET", "/", token=None, headers={"Sec-Fetch-Site": "cross-site"})
        assert s == 403
        s, _, _ = client.request("GET", "/index.html", token=None, headers={"Sec-Fetch-Site": "cross-site"})
        assert s == 403

        # Valid local GET / injects window.__RIGORLOOM_UI__ bootstrap before </head>.
        s, hdrs, raw = client.request("GET", "/", token=None, headers={"Host": f"localhost:{srv.port}"})
        assert s == 200
        assert "no-store" in (hdrs.get("Cache-Control") or "")
        html = raw.decode("utf-8")
        m = re.search(r"<script>window\.__RIGORLOOM_UI__=(\{.*?\});</script>", html)
        assert m is not None
        bootstrap = json.loads(m.group(1))
        assert bootstrap["token"] == srv.token
        assert Path(bootstrap["root"]) == (tmp_path / "rt").resolve()

        # Pretendard font route works if font file exists in checkout, else 404 cleanly.
        font_exists = (REPO_ROOT / "desktop" / "src" / "assets" / "fonts" / "PretendardVariable.woff2").is_file()
        s_font, _, _ = client.request("GET", "/assets/fonts/PretendardVariable.woff2", token=None)
        assert s_font == (200 if font_exists else 404)

        # Missing or wrong token on /rpc and /api/* returns 403.
        for method, path in (
            ("POST", "/rpc"),
            ("GET", "/api/runtime/status"),
            ("GET", "/api/prefs"),
            ("POST", "/api/prefs"),
            ("POST", "/api/guard/diff"),
            ("GET", "/api/pipeline/gates?workspace=x"),
        ):
            s_missing, _ = (
                client.get_json(path, token=None) if method == "GET" else client.post_json(path, {}, token=None)
            )
            assert s_missing == 403, f"expected 403 without token on {method} {path}"
            s_wrong, _ = (
                client.get_json(path, token="wrong-token")
                if method == "GET"
                else client.post_json(path, {}, token="wrong-token")
            )
            assert s_wrong == 403, f"expected 403 with wrong token on {method} {path}"

        # Missing or wrong ?token= on /events and /api/export-download returns 403.
        for path in ("/events", "/events?token=wrong", "/api/export-download?name=x.hwpx", "/api/export-download?token=wrong&name=x.hwpx"):
            s_q, _, _ = client.request("GET", path, token=None)
            assert s_q == 403, f"expected 403 on {path}"
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def _start_bare_bridge(tmp_path: Path) -> tuple[rt_ui.BridgeHTTPServer, threading.Thread]:
    srv = rt_ui.create_bridge_server(
        root=tmp_path / "rt",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
        auto_start=False,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t


def _post_head(port: int, headers: dict[str, str], path: str = "/rpc", timeout: float = 30,
               method: str = "POST") -> socket.socket:
    """Send only the head of a POST (untokened unless `headers` has the token); the caller sends any body."""
    lines = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{port}", "Content-Type: application/json"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    return sock


def _read_to_eof(sock: socket.socket) -> bytes:
    data = b""
    while chunk := sock.recv(65536):
        data += chunk
    return data


def test_a_refused_post_reads_its_small_body_before_answering(tmp_path: Path):
    """The 403 waits for the declared body, so the close after it is not a reset
    that can reach the client first (Windows aborts the read with WinError 10053)."""
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, {"Content-Length": "2"})
        try:
            readable, _, _ = select.select([sock], [], [], 0.3)
            assert not readable, "the bridge answered before the body it was sent"
            sock.sendall(b"{}")
            data = _read_to_eof(sock)
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 403")
        assert b'"unauthorized"' in data
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def test_a_refused_body_that_never_comes_is_waited_on_briefly(tmp_path: Path):
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, {"Content-Length": "10"})
        try:
            started = time.monotonic()
            data = _read_to_eof(sock)
            elapsed = time.monotonic() - started
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 403")
        assert elapsed < rt_ui.REFUSED_BODY_DRAIN_SECONDS + 3
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


@pytest.mark.parametrize("headers", [
    {"Content-Length": str(rt_ui.REFUSED_BODY_DRAIN_BYTES + 1)},
    {"Content-Length": "1_0"},
    {"Content-Length": "-5"},
    {"Transfer-Encoding": "chunked"},
], ids=["over-the-cap", "not-digits", "negative", "chunked"])
def test_a_refused_body_too_large_or_unframed_is_not_read(tmp_path: Path, headers):
    """Only a small body with a plain Content-Length is drained; the 403 for the
    rest goes out at once, without reading anything."""
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, headers)
        try:
            readable, _, _ = select.select([sock], [], [], rt_ui.REFUSED_BODY_DRAIN_SECONDS / 2)
            assert readable, "the bridge waited for a body it should not read"
            data = _read_to_eof(sock)
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 403")
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def test_a_post_outside_rpc_and_api_drains_its_body_and_closes(tmp_path: Path):
    """The 404 for a path the bridge does not serve never reads the body: it
    drains a small one like a refusal, and closes so the body is not read as
    the next request."""
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, {"Content-Length": "2"}, path="/nope", timeout=5)
        try:
            readable, _, _ = select.select([sock], [], [], 0.3)
            assert not readable, "the bridge answered before the body it was sent"
            sock.sendall(b"{}")
            data = _read_to_eof(sock)   # a kept-alive connection times out here
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 404")
        assert data.count(b"HTTP/1.1 ") == 1
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


@pytest.mark.parametrize("path, headers, status", [
    ("/api/doc-folder", {"Content-Length": str(rt_ui.SMALL_JSON_BODY_BYTES + 1)}, b"413"),
    ("/rpc", {"Content-Length": "abc"}, b"400"),
    ("/rpc", {"Transfer-Encoding": "chunked"}, b"400"),
], ids=["too-large", "bad-length", "chunked"])
def test_a_post_body_the_bridge_will_not_read_closes_the_connection(tmp_path: Path, path, headers, status):
    """An authorised POST whose body is left unread (too large, unreadable
    length, chunked) is answered and the connection closed, instead of kept
    alive with the body still waiting on it."""
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, {"X-Rigorloom-Token": srv.token, **headers}, path=path, timeout=5)
        try:
            data = _read_to_eof(sock)   # a kept-alive connection times out here
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 " + status), data[:80]
        assert data.count(b"HTTP/1.1 ") == 1
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def _peer_reset(sock: socket.socket, tries: int) -> bool:
    """Send a little at a time; True once the peer's reset shows on this socket."""
    for _ in range(tries):
        try:
            sock.sendall(b"x" * 1024)
        except OSError:
            return True
        time.sleep(0.05)
        if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
            return True
    return False


@pytest.mark.parametrize("method, path, token, headers, status", [
    ("POST", "/rpc", True, {"Content-Length": str(rt_ui.MAX_JSON_BODY_BYTES + 1)}, b"413"),
    ("POST", "/rpc", True, {"Content-Length": "abc"}, b"400"),
    ("POST", "/rpc", True, {"Transfer-Encoding": "chunked"}, b"400"),
    ("POST", "/rpc", False, {"Content-Length": str(rt_ui.REFUSED_BODY_DRAIN_BYTES + 1)}, b"403"),
    ("POST", "/nope", True, {"Content-Length": str(rt_ui.REFUSED_BODY_DRAIN_BYTES + 1)}, b"404"),
    ("GET", "/api/doc/pages", True, {"Content-Length": "2"}, b"400"),
], ids=["too-large", "bad-length", "chunked", "refused-large", "not-found-large", "get-with-body"])
def test_a_body_left_unread_is_read_off_before_the_bridge_closes(tmp_path: Path, method, path, token,
                                                                    headers, status):
    """When the bridge answers without reading the body, it shuts its side and
    reads off what the client still sends before it closes. Closing with those
    bytes arriving is a reset, and on Windows the reset can abort the client's
    read of the answer (WinError 10053). Linux shows it as a reset on the
    client's next send, so the test sends the body after reading the answer."""
    srv, t = _start_bare_bridge(tmp_path)
    try:
        if token:
            headers = {"X-Rigorloom-Token": srv.token, **headers}
        sock = _post_head(srv.port, headers, path=path, timeout=5, method=method)
        try:
            data = _read_to_eof(sock)
            sock.sendall(b"{}")
            reset = _peer_reset(sock, tries=4)
        finally:
            sock.close()
        head = data.split(b"\r\n\r\n", 1)[0] + b"\r\n"
        assert data.startswith(b"HTTP/1.1 " + status), data[:80]
        assert not reset, "the bridge closed with the body unread"
        assert b"\r\nConnection: close\r\n" in head
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


@pytest.mark.parametrize("bound", ["seconds", "bytes"])
def test_the_read_off_after_an_unread_body_is_bounded(tmp_path: Path, monkeypatch, bound):
    """A client that keeps the connection open, or keeps sending, holds the
    bridge for at most UNREAD_BODY_LINGER_SECONDS and UNREAD_BODY_LINGER_BYTES."""
    if bound == "seconds":
        monkeypatch.setattr(rt_ui, "UNREAD_BODY_LINGER_SECONDS", 0.3)
    else:
        monkeypatch.setattr(rt_ui, "UNREAD_BODY_LINGER_BYTES", 4096)
    srv, t = _start_bare_bridge(tmp_path)
    try:
        sock = _post_head(srv.port, {"X-Rigorloom-Token": srv.token,
                                     "Content-Length": str(rt_ui.MAX_JSON_BODY_BYTES + 1)}, timeout=5)
        try:
            data = _read_to_eof(sock)
            if bound == "seconds":
                time.sleep(1.0)
            # Both ways finish well inside the 2 s default, so a reset here
            # comes from the bound under test.
            reset = _peer_reset(sock, tries=4 if bound == "seconds" else 20)
        finally:
            sock.close()
        assert data.startswith(b"HTTP/1.1 413")
        assert reset, "the bridge kept reading past its bound"
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def test_wheel_fallback_html_and_missing_font_clean_404(tmp_path: Path):
    """When ui_dist/ and desktop/ are absent (wheel without bundle), serve minimal HTML & 404 font cleanly."""
    app = rt_ui.BridgeApplication(
        root=tmp_path / "wheel-root",
        engine_root=tmp_path / "no-repo",
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
    )
    app.repo_root = None
    app.engine_root = None
    srv = rt_ui.BridgeHTTPServer(("127.0.0.1", 0), app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    client = _BridgeClient(srv)
    try:
        if not (RUNTIME_SCRIPTS / "ui_dist" / "index.html").is_file():
            s, _, raw = client.request("GET", "/", token=None)
            assert s == 200
            assert "window.__RIGORLOOM_UI__" in raw.decode("utf-8")
            s_font, _, _ = client.request("GET", "/assets/fonts/PretendardVariable.woff2", token=None)
            assert s_font == 404
        s_packs, packs = client.get_json("/api/task-packs")
        assert s_packs == 200
        assert packs["available"] is False
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def test_sidecar_lifecycle_rpc_cancel_and_sse(started_bridge):
    _, client, rt_root = started_bridge
    resp, sse_q, sse_stop = client.open_sse()
    try:
        # Initial runtime://status pushed on SSE connect.
        ev_name, ev_data = sse_q.get(timeout=5)
        assert ev_name == "runtime://status"
        assert ev_data["running"] is True
        assert ev_data["initialized"] is True

        s, status_body = client.get_json("/api/runtime/status")
        assert s == 200
        assert status_body["running"] is True
        assert Path(status_body["root"]) == rt_root.resolve()

        # Idempotent /api/runtime/start returns handshake + status.
        s, started = client.post_json("/api/runtime/start", {"root": str(rt_root)})
        assert s == 200
        assert started["handshake"]["protocolVersion"] == "0"
        assert started["status"]["running"] is True

        # JSON-RPC works and malformed params return HTTP 200 ok=false envelope.
        caps = client.rpc("capabilities/list")
        assert caps["ok"] is True, caps
        assert "methods" in caps["result"]
        assert "approval/resolve" in caps["result"]["methods"]
        bad = client.rpc("session/get", {})
        assert bad["ok"] is False
        assert "code" in bad["error"]

        # Test tagged RPC cancellation sends {"kind":"cancel","id":...} to serve.py.
        mgr = client.server.bridge.sidecar
        fake_in_lines: list[str] = []

        class _FakeStdin:
            closed = False

            def write(self, data: str) -> int:
                fake_in_lines.append(data)
                frame = json.loads(data)
                if frame.get("kind") == "cancel":
                    req_id = frame["id"]
                    with mgr._lock:
                        waiter = mgr._waiters.get(req_id)
                    if waiter:
                        waiter[1]["ok"] = False
                        waiter[1]["payload"] = {"code": "cancelled", "message": "cancelled by caller"}
                        waiter[0].set()
                return len(data)

            def flush(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        # Stop real sidecar first so we observe SSE runtime://status stop event too.
        s_stop, stopped = client.post_json("/api/runtime/stop")
        assert s_stop == 200 and stopped == {"stopped": True}

        seen_stopped_sse = False
        for _ in range(10):
            try:
                en, ed = sse_q.get(timeout=3)
            except queue.Empty:
                break
            if en == "runtime://status" and isinstance(ed, dict) and ed.get("running") is False:
                seen_stopped_sse = True
                break
        assert seen_stopped_sse

        # Exercise tagged cancel mechanics via an active pending frame.
        class _FakeProc:
            pid = 999999
            stdin = _FakeStdin()

            def poll(self):
                return None

        with mgr._lock:
            mgr._proc = _FakeProc()
        rpc_holder: dict = {}
        t_rpc = threading.Thread(
            target=lambda: rpc_holder.update(client.rpc("document/inspect", {"sessionId": "x"}, tag="tag-42")),
            daemon=True,
        )
        t_rpc.start()
        for _ in range(100):
            with mgr._lock:
                if "tag-42" in mgr._inflight_tags:
                    break
            threading.Event().wait(0.01)
        s_c, c_res = client.post_json("/api/runtime/cancel", {"tag": "tag-42"})
        assert s_c == 200 and c_res == {"cancelled": True}
        t_rpc.join(timeout=5)
        assert rpc_holder["ok"] is False
        assert rpc_holder["error"]["code"] == "cancelled"
        assert any(json.loads(ln).get("kind") == "cancel" for ln in fake_in_lines)
        with mgr._lock:
            mgr._proc = None

        # Unknown tag returns cancelled=false.
        s_c2, c_res2 = client.post_json("/api/runtime/cancel", {"tag": "no-such-tag"})
        assert s_c2 == 200 and c_res2 == {"cancelled": False}
    finally:
        sse_stop.set()
        resp.close()


def test_get_prefs_migrates_legacy_dev_editor_v2_once(started_bridge):
    srv, client, _ = started_bridge
    prefs_file: Path = srv.bridge._prefs_path

    # 1. false -> editorVariant: "v1" and devEditorV2 removed from the file; second read is a no-op byte for byte
    prefs_file.write_text(json.dumps({"devEditorV2": False, "theme": "dark"}) + "\n", encoding="utf-8")
    s1, p1 = client.get_json("/api/prefs")
    assert s1 == 200
    assert p1.get("editorVariant") == "v1"
    assert "devEditorV2" not in p1
    assert p1.get("theme") == "dark"
    raw_after_first = prefs_file.read_bytes()
    on_disk_1 = json.loads(raw_after_first.decode("utf-8"))
    assert on_disk_1 == {"theme": "dark", "editorVariant": "v1"}
    assert "devEditorV2" not in on_disk_1

    s2, p2 = client.get_json("/api/prefs")
    assert s2 == 200 and p2 == p1
    assert prefs_file.read_bytes() == raw_after_first

    # 2. true -> editorVariant: "v2" and devEditorV2 removed from the file
    prefs_file.write_text(json.dumps({"devEditorV2": True}) + "\n", encoding="utf-8")
    s_true, p_true = client.get_json("/api/prefs")
    assert s_true == 200
    assert p_true.get("editorVariant") == "v2"
    assert "devEditorV2" not in p_true
    assert json.loads(prefs_file.read_text(encoding="utf-8")) == {"editorVariant": "v2"}

    # 3. both present -> keeps editorVariant and drops devEditorV2
    for kept, legacy in (("v1", True), ("v2", False)):
        prefs_file.write_text(
            json.dumps({"editorVariant": kept, "devEditorV2": legacy}) + "\n",
            encoding="utf-8",
        )
        s_both, p_both = client.get_json("/api/prefs")
        assert s_both == 200
        assert p_both.get("editorVariant") == kept
        assert "devEditorV2" not in p_both
        assert json.loads(prefs_file.read_text(encoding="utf-8")) == {"editorVariant": kept}

    # 4. non-boolean devEditorV2 -> dropped without setting editorVariant; second read is a no-op
    for bad in ("false", "true", 0, 1, None, ["v1"], {"v": 1}):
        prefs_file.write_text(
            json.dumps({"devEditorV2": bad, "language": "ko"}) + "\n",
            encoding="utf-8",
        )
        s_bad, p_bad = client.get_json("/api/prefs")
        assert s_bad == 200
        assert "devEditorV2" not in p_bad
        assert "editorVariant" not in p_bad
        raw_bad_after = prefs_file.read_bytes()
        assert json.loads(raw_bad_after.decode("utf-8")) == {"language": "ko"}
        s_again, p_again = client.get_json("/api/prefs")
        assert s_again == 200 and p_again == p_bad
        assert prefs_file.read_bytes() == raw_bad_after


def test_get_prefs_migration_survives_a_failed_write(started_bridge, monkeypatch):
    srv, client, _ = started_bridge
    prefs_file: Path = srv.bridge._prefs_path
    raw = json.dumps({"devEditorV2": False}) + "\n"
    prefs_file.write_text(raw, encoding="utf-8")

    def refuse_write(*_args, **_kwargs):
        raise OSError("read-only profile")

    monkeypatch.setattr(sys.modules[type(srv.bridge).__module__], "atomic_write_bytes", refuse_write)
    status, prefs = client.get_json("/api/prefs")
    assert status == 200
    assert prefs.get("editorVariant") == "v1"
    assert "devEditorV2" not in prefs
    assert prefs_file.read_text(encoding="utf-8") == raw

def test_prefs_corpus_credentials_agenthost_mock_and_taskpacks(started_bridge):
    _, client, rt_root = started_bridge

    # Prefs + default-root
    s, def_root = client.get_json("/api/default-root")
    assert s == 200 and Path(def_root["root"]) == rt_root.resolve()
    s, prefs = client.get_json("/api/prefs")
    assert s == 200 and Path(prefs["root"]) == rt_root.resolve()
    s, updated = client.post_json("/api/prefs", {"patch": {"theme": "warm", "dropMe": "yes"}})
    assert s == 200 and updated["theme"] == "warm" and updated["dropMe"] == "yes"
    s, updated2 = client.post_json("/api/prefs", {"patch": {"dropMe": None}})
    assert s == 200 and "dropMe" not in updated2

    # Corpus files
    s, corpus = client.get_json("/api/corpus-files")
    assert s == 200
    assert any(f["name"].endswith("gianmun-byeolji-1ho.hwpx") for f in corpus["files"])

    # Credentials live strictly in server RAM and never echo back.
    secret_val = "super-secret-never-echo-xyz"
    assert client.post_json("/api/credential/status", {"key": "bad key!"})[0] == 400
    s, c0 = client.post_json("/api/credential/status", {"key": "rigorloom.agenthost.router"})
    assert s == 200 and c0 == {"key": "rigorloom.agenthost.router", "present": False}
    s, c1 = client.post_json("/api/credential/set", {"key": "rigorloom.agenthost.router", "secret": secret_val})
    assert s == 200 and c1 == {"key": "rigorloom.agenthost.router", "present": True}
    assert secret_val not in json.dumps(c1)
    s, c2 = client.post_json("/api/credential/status", {"key": "rigorloom.agenthost.router"})
    assert s == 200 and c2 == {"key": "rigorloom.agenthost.router", "present": True}
    s, c3 = client.post_json("/api/credential/delete", {"key": "rigorloom.agenthost.router"})
    assert s == 200 and c3 == {"key": "rigorloom.agenthost.router", "present": False}

    # Agent Host status + config secret-key refusal + valid save/read + capabilities
    s, ah_status = client.get_json("/api/agent-host/status")
    assert s == 200 and ah_status["available"] is True
    s_bad_cfg, bad_cfg = client.post_json(
        "/api/agent-host/save-config",
        {"provider": "router", "settings": {"baseUrl": "http://127.0.0.1:9999", "apiKey": "nope"}, "hasCredential": False},
    )
    assert s_bad_cfg == 400 and bad_cfg["error"]["code"] == "secret_in_config"

    s_cfg, saved_cfg = client.post_json(
        "/api/agent-host/save-config",
        {
            "provider": "router",
            "settings": {"baseUrl": "http://127.0.0.1:9999/v1", "model": "local-model"},
            "hasCredential": True,
        },
    )
    assert s_cfg == 200 and saved_cfg["saved"] is True
    assert secret_val not in Path(saved_cfg["configPath"]).read_text(encoding="utf-8")
    s_read, read_cfg = client.post_json("/api/agent-host/read-config", {"provider": "router"})
    assert s_read == 200 and read_cfg["exists"] is True
    assert read_cfg["settings"]["credential"] == {"source": "env", "key": "RIGORLOOM_PROVIDER_CREDENTIAL"}

    s_cap, ah_caps = client.post_json("/api/agent-host/capabilities", {"provider": "mock"})
    assert s_cap == 200 and ah_caps["ok"] is True, (s_cap, ah_caps)

    # Tool status + task packs
    s_tool, tool_status = client.get_json("/api/agent-tool-status")
    assert s_tool == 200 and tool_status["available"] is True, (s_tool, tool_status)
    s_tp, task_packs = client.get_json("/api/task-packs")
    assert s_tp == 200 and task_packs["available"] is True, (s_tp, task_packs)


def test_guard_diff_text_and_hwpx_plan_preview_and_export_safety(started_bridge, tmp_path: Path):
    _, client, rt_root = started_bridge

    # 1) guard/diff beforeText/afterText: preserved numbers pass, dropped numbers/direction fail.
    s_ok, g_ok = client.post_json(
        "/api/guard/diff",
        {
            "beforeText": "총 예산은 2026년 100만원이며 전년 대비 증가하였다.",
            "afterText": "총 예산은 2026년 100만원 규모로 전년 대비 증가했다.",
        },
    )
    assert s_ok == 200, (s_ok, g_ok)
    assert g_ok["schema"] == "rigorloom/guard-v1"
    assert g_ok["pass"] is True
    assert g_ok["paragraphs"] == 1
    assert g_ok["edited"] == 1

    s_bad, g_bad = client.post_json(
        "/api/guard/diff",
        {
            "beforeText": "총 예산은 2026년 100만원이며 전년 대비 증가하였다.",
            "afterText": "총 예산은 2026년 250만원이며 전년 대비 감소하였다.",
        },
    )
    assert s_bad == 200
    assert g_bad["schema"] == "rigorloom/guard-v1"
    assert g_bad["pass"] is False
    row = g_bad["changed"][0]
    assert row["pass"] is False
    assert "numbers" in row["kinds"]
    # A number is shown with its magnitude and unit, as the guard reads it (T183).
    assert any(sp["text"] == "100만원" and sp["status"] == "removed" for sp in row["beforeProtected"])
    assert any(sp["text"] == "250만원" and sp["status"] == "added" for sp in row["afterProtected"])

    # The same amount written another way passes and is not marked as changed.
    s_same, g_same = client.post_json(
        "/api/guard/diff",
        {"beforeText": "총 예산은 500만원이다.", "afterText": "총 예산은 5,000,000원이다."},
    )
    assert s_same == 200 and g_same["pass"] is True, (s_same, g_same)
    same_row = g_same["changed"][0]
    spans = same_row["beforeProtected"] + same_row["afterProtected"]
    assert spans and all(sp["status"] == "kept" for sp in spans), spans

    # A bare amount is compared in the unit its field declares, as the guard
    # does: 43 under 운송비(천원) is 43,000원, 93 under (천원) is not 93 under
    # (백만원) (the reviewer's re-check of T183).
    s_decl, g_decl = client.post_json(
        "/api/guard/diff",
        {"beforeText": "운송비(천원)는 43으로 확정했다.", "afterText": "운송비는 43,000원으로 확정했다."},
    )
    assert s_decl == 200 and g_decl["pass"] is True, (s_decl, g_decl)
    decl_row = g_decl["changed"][0]
    spans = [sp for sp in decl_row["beforeProtected"] + decl_row["afterProtected"]
             if sp["kind"] == "numbers"]
    assert spans and all(sp["status"] == "kept" for sp in spans), spans

    s_unit, g_unit = client.post_json(
        "/api/guard/diff",
        {"beforeText": "검수비(천원)는 93으로 확정했다.", "afterText": "검수비(백만원)는 93으로 확정했다."},
    )
    assert s_unit == 200 and g_unit["pass"] is False, (s_unit, g_unit)
    unit_row = g_unit["changed"][0]
    assert [sp["status"] for sp in unit_row["beforeProtected"] if sp["kind"] == "numbers"] == ["removed"]
    assert [sp["status"] for sp in unit_row["afterProtected"] if sp["kind"] == "numbers"] == ["added"]

    # 2) Real HWPX open-upload + planId preview via preedit BEFORE plan/apply.
    b64 = base64.b64encode(CORPUS_FORM.read_bytes()).decode("ascii")
    s_up, opened = client.post_json("/api/open-upload", {"filename": "한글 양식 (테스트).hwpx", "bytesBase64": b64})
    assert s_up == 200
    session_id = opened["sessionId"]

    proposed = client.rpc(
        "plan/propose",
        {
            "sessionId": session_id,
            "backend": "preedit",
            "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛 2026년 100만원"}],
        },
    )
    assert proposed["ok"] is True
    plan = proposed["result"]["plan"]

    s_prev, g_prev = client.post_json("/api/guard/diff", {"sessionId": session_id, "planId": plan["planId"]})
    assert s_prev == 200, (s_prev, g_prev)
    assert g_prev["schema"] == "rigorloom/guard-v1"
    assert g_prev["before"] == "source"
    assert g_prev["after"] == f"plan:{plan['planId']}"
    assert g_prev["edited"] >= 1
    assert any("한빛 2026년 100만원" in c["after"] for c in g_prev["changed"])
    assert any(
        sp["text"] == "100만원" and sp["kind"] == "numbers" and sp["status"] == "added"
        for c in g_prev["changed"]
        for sp in c["afterProtected"]
    )

    # Approve & apply, then test staged export + export-download + alias/tamper refusal.
    assert client.rpc("plan/validate", {"planId": plan["planId"]})["ok"] is True
    appr = client.rpc("approval/request", {"planId": plan["planId"]})["result"]["approval"]
    # The bridge records an approval only with the sheet's single-use token.
    s_tok, issued = client.post_json("/api/approval/confirmation", {
        "sessionId": session_id, "planId": plan["planId"],
        "planHash": plan["planHash"], "baseDigest": plan["boundSha256"],
    })
    assert s_tok == 200, issued
    assert client.rpc(
        "approval/resolve",
        {
            "approvalId": appr["approvalId"],
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "decision": "approved",
            "approver": "bridge-test",
            "confirmationToken": issued["confirmationToken"],
        },
    )["ok"] is True
    applied = client.rpc("plan/apply", {"planId": plan["planId"], "approvalId": appr["approvalId"]})
    assert applied["ok"] is True
    run_id = applied["result"]["candidate"]["runId"]

    # guard/diff against applied runId matches plan preview!
    s_run, g_run = client.post_json("/api/guard/diff", {"sessionId": session_id, "runId": run_id})
    assert s_run == 200 and g_run["edited"] >= 1
    assert any("한빛 2026년 100만원" in c["after"] for c in g_run["changed"])

    # Staged export (no destination) + authenticated download
    s_exp, exp = client.post_json("/api/export", {"sessionId": session_id, "runId": run_id})
    assert s_exp == 200
    assert Path(exp["receiptPath"]).is_file()
    assert f"token={client.token}" in exp["downloadUrl"]
    dl_status, dl_hdrs, dl_bytes = client.request("GET", exp["downloadUrl"], token=None)
    assert dl_status == 200
    assert "attachment;" in (dl_hdrs.get("Content-Disposition") or "")
    assert hashlib.sha256(dl_bytes).hexdigest() == exp["sha256"]

    # Destination export + durable sidecar receipt
    dest_file = tmp_path / "out" / "published.hwpx"
    s_dest, exp_dest = client.post_json(
        "/api/export",
        {"sessionId": session_id, "runId": run_id, "destination": str(dest_file)},
    )
    assert s_dest == 200
    assert exp_dest["downloadUrl"] is None
    assert dest_file.is_file()
    assert Path(f"{dest_file}.receipt.json").is_file()
    assert hashlib.sha256(dest_file.read_bytes()).hexdigest() == exp_dest["sha256"]

    # Alias path refused with export_alias
    cand_artifact = rt_root / "sessions" / session_id / "candidates" / run_id / "artifact.hwpx"
    s_alias, alias_err = client.post_json(
        "/api/export",
        {"sessionId": session_id, "runId": run_id, "destination": str(cand_artifact)},
    )
    assert s_alias == 409 and alias_err["error"]["code"] == "export_alias"

    # Candidate tampering fails closed BEFORE copy!
    cand_artifact.write_bytes(b"corrupted-bytes")
    s_tamper, tamper_err = client.post_json(
        "/api/export",
        {"sessionId": session_id, "runId": run_id, "destination": str(tmp_path / "should-not-exist.hwpx")},
    )
    assert s_tamper == 409 and tamper_err["error"]["code"] == "candidate_hash_mismatch"
    assert not (tmp_path / "should-not-exist.hwpx").exists()
