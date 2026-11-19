# -*- coding: utf-8 -*-
"""Security, confinement, oracle-resistance, and HTTP parity tests for rt_workspace.py."""
from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import quote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402
import rt_workspace  # noqa: E402


class _WorkspaceClient:
    """Minimal stdlib HTTP/1.1 client targeting WorkspaceHTTPServer."""

    def __init__(self, server: rt_workspace.WorkspaceHTTPServer) -> None:
        self.server = server
        self.host = "127.0.0.1"
        self.port = server.port
        self.token = server.token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | bytes | None = None,
        token: str | None = ...,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        hdrs: dict[str, str] = {}
        if token is ...:
            hdrs["X-Rigorloom-Token"] = self.token
        elif token is not None:
            hdrs["X-Rigorloom-Token"] = token
        if headers:
            hdrs.update(headers)
        raw: bytes | None = None
        if isinstance(body, bytes):
            raw = body
        elif body is not None:
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


@pytest.fixture()
def workspace_env(tmp_path: Path):
    """Build a confined workspace root with sibling outside-root secrets and symlinks."""
    root = tmp_path / "문서 폴더"
    root.mkdir()
    sub = root / "기록관리과" / "2026 협조"
    sub.mkdir(parents=True)

    # Supported files inside root
    (root / "기안문(별지 제1호서식).hwpx").write_bytes(b"PK\x03\x04hwpx-sample")
    (root / "표준근로계약서.docx").write_bytes(b"PK\x03\x04docx-sample")
    (root / "협조요청_개요.md").write_text("# 개요\n공문 초안\n", encoding="utf-8")
    (sub / "정보공개 청구서.HWP").write_bytes(b"hwp5-sample")

    # Unsupported and hidden files inside root (must never be listed or readable)
    (root / "secret.txt").write_text("do not expose", encoding="utf-8")
    (root / "script.py").write_text("print(1)\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (root / ".hidden.hwpx").write_bytes(b"hidden-hwpx")
    hidden_dir = root / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config.md").write_text("git-config", encoding="utf-8")

    # Files strictly outside root
    outside_dir = tmp_path / "outside-secrets"
    outside_dir.mkdir()
    outside_file = outside_dir / "outside-secret.hwpx"
    outside_file.write_bytes(b"OUTSIDE-SECRET-DATA")
    outside_sibling = tmp_path / "sibling-secret.hwpx"
    outside_sibling.write_bytes(b"SIBLING-SECRET-DATA")

    # Symlink attack fixtures inside root
    (root / "escape-file.hwpx").symlink_to(outside_file)
    (root / "escape-dir").symlink_to(outside_dir)
    (root / "chain-hop1.hwpx").symlink_to(root / "escape-file.hwpx")
    (root / "dangling.hwpx").symlink_to(tmp_path / "does-not-exist-anywhere.hwpx")
    (root / "loop-root").symlink_to(root)
    (root / "internal-link.hwpx").symlink_to(root / "기안문(별지 제1호서식).hwpx")
    (root / "sneaky-env.hwpx").symlink_to(root / ".env")
    (root / "sneaky-git.md").symlink_to(hidden_dir / "config.md")
    (root / "sneaky-txt.hwpx").symlink_to(root / "secret.txt")

    # Non-regular FIFO trap inside root (POSIX only)
    fifo_path = root / "trap.hwpx"
    if hasattr(os, "mkfifo"):
        os.mkfifo(fifo_path)

    srv = rt_workspace.create_workspace_server(root=root, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "server": srv,
            "client": _WorkspaceClient(srv),
            "root": root,
            "outside_dir": outside_dir,
            "outside_file": outside_file,
            "outside_sibling": outside_sibling,
        }
    finally:
        srv.shutdown_workspace()
        thread.join(timeout=5)


def test_listing_filters_supported_files_hides_dotfiles_and_excludes_escaping_symlinks(workspace_env):
    client: _WorkspaceClient = workspace_env["client"]

    status, headers, raw = client.request("GET", "/api/workspace/list")
    assert status == 200
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert "no-store" in (headers.get("Cache-Control") or "")

    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["path"] == ""
    assert payload["truncated"] is False

    names = [e["name"] for e in payload["entries"]]
    assert "기록관리과" in names
    assert "기안문(별지 제1호서식).hwpx" in names
    assert "표준근로계약서.docx" in names
    assert "협조요청_개요.md" in names
    assert "internal-link.hwpx" in names

    # Unsupported, hidden, escaping symlinks, dangling symlinks, and FIFO must never appear
    for forbidden in (
        "secret.txt",
        "script.py",
        ".env",
        ".hidden.hwpx",
        ".git",
        "escape-file.hwpx",
        "escape-dir",
        "chain-hop1.hwpx",
        "dangling.hwpx",
        "sneaky-env.hwpx",
        "sneaky-git.md",
        "sneaky-txt.hwpx",
        "trap.hwpx",
    ):
        assert forbidden not in names, f"{forbidden!r} leaked into listing: {names}"

    # Recursive listing descends into real subdirs without hanging on loop-root
    s_rec, rec = client.get_json("/api/workspace/list?recursive=1&maxDepth=5")
    assert s_rec == 200
    rel_paths = [e["relPath"] for e in rec["entries"]]
    assert "기록관리과/2026 협조/정보공개 청구서.HWP" in rel_paths
    assert not any("outside" in rp for rp in rel_paths)
    assert not any(".git" in rp for rp in rel_paths)

    # Stat and read confined files (GET json, GET raw, POST json)
    target_rel = "협조요청_개요.md"
    s_stat, stat_body = client.get_json(f"/api/workspace/stat?path={quote(target_rel)}")
    assert s_stat == 200
    assert stat_body["entry"]["kind"] == "file"
    assert stat_body["entry"]["extension"] == ".md"

    s_read, read_body = client.get_json(f"/api/workspace/read?path={quote(target_rel)}")
    assert s_read == 200
    assert base64.b64decode(read_body["bytesBase64"]).decode("utf-8") == "# 개요\n공문 초안\n"

    s_raw, _, raw_bytes = client.request("GET", f"/api/workspace/read?path={quote(target_rel)}&format=raw")
    assert s_raw == 200
    assert raw_bytes.decode("utf-8") == "# 개요\n공문 초안\n"

    s_post, post_body = client.post_json("/api/workspace/read", {"path": "기록관리과/2026 협조/정보공개 청구서.HWP"})
    assert s_post == 200
    assert base64.b64decode(post_body["bytesBase64"]) == b"hwp5-sample"


def test_path_confinement_and_identical_response_for_missing_vs_outside_root(workspace_env):
    """Every missing, traversal, absolute, drive, UNC, NUL, symlink-escape, hidden, or
    unsupported path must return the exact same HTTP 404 and byte-identical JSON body."""
    client: _WorkspaceClient = workspace_env["client"]
    root: Path = workspace_env["root"]
    outside_file: Path = workspace_env["outside_file"]

    # Baseline response for a genuinely missing file inside root
    base_status, _, base_body = client.request("GET", "/api/workspace/read?path=does-not-exist.hwpx")
    assert base_status == 404
    base_json = json.loads(base_body.decode("utf-8"))
    assert base_json == {
        "ok": False,
        "error": {
            "code": rt_workspace.UNIFORM_NOT_FOUND_CODE,
            "message": rt_workspace.UNIFORM_NOT_FOUND_MESSAGE,
        },
    }

    attack_paths = [
        # Missing inside root
        "missing-a.hwpx",
        "기록관리과/missing-b.hwpx",
        # Dot-dot traversal (POSIX & backslash, existing outside vs missing outside)
        "..",
        "../sibling-secret.hwpx",
        "../outside-secrets/outside-secret.hwpx",
        "../outside-secrets/does-not-exist.hwpx",
        "기록관리과/../../sibling-secret.hwpx",
        r"..\sibling-secret.hwpx",
        r"기록관리과\..\..\outside-secrets\outside-secret.hwpx",
        # Absolute paths (existing outside, missing outside, existing inside)
        "/etc/hosts",
        "/etc/passwd",
        "/nonexistent/abs/doc.hwpx",
        str(outside_file),
        str(root / "기안문(별지 제1호서식).hwpx"),
        # Symlink escapes (direct file, dir, chained, dangling)
        "escape-file.hwpx",
        "escape-dir",
        "escape-dir/outside-secret.hwpx",
        "escape-dir/nonexistent.hwpx",
        "chain-hop1.hwpx",
        "dangling.hwpx",
        # Windows drive letters, drive-relative, extended paths, NTFS ADS
        r"C:\Windows\win.ini",
        "C:/Windows/win.ini",
        "C:relative.hwpx",
        r"\\?\C:\Windows\win.ini",
        "기안문(별지 제1호서식).hwpx:secretstream",
        # Windows / POSIX UNC paths
        r"\\server\share\doc.hwpx",
        "//server/share/doc.hwpx",
        r"\\?\UNC\server\share\doc.hwpx",
        # NUL bytes and control characters
        "기안문(별지 제1호서식).hwpx\x00.txt",
        "기록관리과/\x00/doc.hwpx",
        "doc\r\n.hwpx",
        # Hidden dotfiles / dotdirs / unsupported files inside root / sneaky symlinks / FIFO trap
        ".env",
        ".hidden.hwpx",
        ".git/config.md",
        "secret.txt",
        "script.py",
        "sneaky-env.hwpx",
        "sneaky-git.md",
        "sneaky-txt.hwpx",
        "trap.hwpx",
    ]

    for raw_encoded in (
        "%2e%2e%2fsibling-secret.hwpx",
        "%2e%2e%5csibling-secret.hwpx",
        "%2fetc%2fhosts",
        "doc%00.hwpx",
    ):
        s_enc, _, b_enc = client.request("GET", f"/api/workspace/read?path={raw_encoded}")
        assert (s_enc, b_enc) == (base_status, base_body), (
            f"Oracle mismatch on raw encoded GET read {raw_encoded!r}"
        )

    for candidate in attack_paths:
        # Test via GET /api/workspace/read (URL-encoded)
        q = quote(candidate, safe="")
        s_read, _, b_read = client.request("GET", f"/api/workspace/read?path={q}")
        assert (s_read, b_read) == (base_status, base_body), (
            f"Oracle mismatch on GET read for {candidate!r}: got {(s_read, b_read)!r}"
        )

        # Test via GET /api/workspace/stat
        s_stat, _, b_stat = client.request("GET", f"/api/workspace/stat?path={q}")
        assert (s_stat, b_stat) == (base_status, base_body), (
            f"Oracle mismatch on GET stat for {candidate!r}: got {(s_stat, b_stat)!r}"
        )

        # Test via POST /api/workspace/read (raw JSON string including literal NUL/backslashes)
        s_post, _, b_post = client.request("POST", "/api/workspace/read", body={"path": candidate})
        assert (s_post, b_post) == (base_status, base_body), (
            f"Oracle mismatch on POST read for {candidate!r}: got {(s_post, b_post)!r}"
        )

    # Also verify GET /api/workspace/list rejects traversal/symlink-dir/missing identically
    list_base_s, _, list_base_b = client.request("GET", "/api/workspace/list?path=no-such-dir")
    assert (list_base_s, list_base_b) == (base_status, base_body)
    for bad_dir in (
        "..",
        "../outside-secrets",
        "/etc",
        "escape-dir",
        r"C:\Windows",
        r"\\server\share",
        "기록관리과\x00",
        ".git",
    ):
        s_l, _, b_l = client.request("GET", f"/api/workspace/list?path={quote(bad_dir, safe='')}")
        assert (s_l, b_l) == (base_status, base_body), (
            f"Oracle mismatch on GET list for {bad_dir!r}: got {(s_l, b_l)!r}"
        )


def test_workspace_routes_are_strictly_read_only_and_refuse_root_override(workspace_env):
    client: _WorkspaceClient = workspace_env["client"]
    root: Path = workspace_env["root"]
    before_files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_symlink())

    # Mutating HTTP verbs refused with 405
    for method in ("PUT", "DELETE", "PATCH"):
        for ep in ("/api/workspace/list", "/api/workspace/stat", "/api/workspace/read"):
            s, body = client.request(method, ep, body={"path": "협조요청_개요.md"})[0::2]
            parsed = json.loads(body.decode("utf-8"))
            assert s == 405, f"expected 405 for {method} {ep}, got {s}"
            assert parsed["error"]["code"] == "method_not_allowed"

    # Write-shaped endpoints do not exist (404)
    for ep in (
        "/api/workspace/write",
        "/api/workspace/create",
        "/api/workspace/delete",
        "/api/workspace/rename",
        "/api/workspace/move",
        "/api/workspace/mkdir",
    ):
        s_p, body_p = client.post_json(ep, {"path": "x.hwpx"})
        assert s_p == 404, f"expected 404 for POST {ep}, got {s_p}"
        assert body_p["error"]["code"] == "not_found"

    # Client cannot override workspace root via query or JSON body
    s_q, body_q = client.get_json("/api/workspace/list?root=/etc")
    assert s_q == 400 and body_q["error"]["code"] == "invalid_params"
    s_b, body_b = client.post_json("/api/workspace/list", {"root": "/etc", "path": ""})
    assert s_b == 400 and body_b["error"]["code"] == "invalid_params"

    after_files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_symlink())
    assert after_files == before_files


def test_http_security_parity_token_host_origin_sec_fetch_and_body_caps(workspace_env):
    srv: rt_workspace.WorkspaceHTTPServer = workspace_env["server"]
    client: _WorkspaceClient = workspace_env["client"]

    # Bound strictly to 127.0.0.1
    assert srv.server_address[0] == "127.0.0.1"

    # Unauthenticated requests refused (missing token and wrong token) on GET & POST
    encoded_md = quote("협조요청_개요.md")
    for method, ep in (
        ("GET", "/api/workspace/list"),
        ("GET", f"/api/workspace/stat?path={encoded_md}"),
        ("GET", f"/api/workspace/read?path={encoded_md}"),
        ("POST", "/api/workspace/list"),
        ("POST", "/api/workspace/stat"),
        ("POST", "/api/workspace/read"),
    ):
        s_none, _, d_none = client.request(method, ep, body={} if method == "POST" else None, token=None)
        assert s_none == 403, f"expected 403 without token on {method} {ep}"
        assert json.loads(d_none)["error"]["code"] == "unauthorized"

        s_bad, _, d_bad = client.request(method, ep, body={} if method == "POST" else None, token="wrong-token")
        assert s_bad == 403, f"expected 403 with wrong token on {method} {ep}"
        assert json.loads(d_bad)["error"]["code"] == "unauthorized"

    # Invalid Host headers refused 403
    for bad_host in ("evil.example:8080", "10.0.0.1:8765", "127.0.0.1@evil.example", "localhost:abc"):
        s, _, d = client.request("GET", "/api/workspace/list", headers={"Host": bad_host})
        assert s == 403 and json.loads(d)["error"]["code"] == "invalid_host"

    # Valid localhost Host accepted
    s_lh, lh_body = client.get_json("/api/workspace/list", headers={"Host": f"localhost:{srv.port}"})
    assert s_lh == 200 and lh_body["ok"] is True

    # Cross-site Sec-Fetch-Site refused 403
    s_cs, _, d_cs = client.request("GET", "/api/workspace/list", headers={"Sec-Fetch-Site": "cross-site"})
    assert s_cs == 403 and json.loads(d_cs)["error"]["code"] == "cross_site_refused"

    # Disallowed Origin headers refused 403; localhost Origin accepted
    for bad_origin in (
        "https://evil.example",
        "http://evil.example:8765",
        "null",
        "https://127.0.0.1:8765",
        "http://127.0.0.1@evil.example",
        "http://127.0.0.1:8765/extra",
    ):
        s_o, _, d_o = client.request("GET", "/api/workspace/list", headers={"Origin": bad_origin})
        assert s_o == 403, f"expected 403 for Origin={bad_origin!r}"
        assert json.loads(d_o)["error"]["code"] == "invalid_origin"

    s_ok_o, ok_o = client.get_json(
        "/api/workspace/list",
        headers={"Origin": f"http://127.0.0.1:{srv.port}"},
    )
    assert s_ok_o == 200 and ok_o["ok"] is True

    # Body size cap parity with rt_ui.MAX_JSON_BODY_BYTES (tested via Content-Length without allocating RAM)
    assert srv.max_body_bytes == rt_ui.MAX_JSON_BODY_BYTES
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    try:
        conn.putrequest("POST", "/api/workspace/list")
        conn.putheader("Host", f"127.0.0.1:{srv.port}")
        conn.putheader("X-Rigorloom-Token", srv.token)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(rt_ui.MAX_JSON_BODY_BYTES + 1))
        conn.endheaders()
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 413
        assert data["error"]["code"] == "body_too_large"
    finally:
        conn.close()

    # Chunked transfer encoding refused 411; malformed JSON refused 400
    s_chunk, _, d_chunk = client.request(
        "POST",
        "/api/workspace/list",
        body=b"2\r\n{}\r\n0\r\n\r\n",
        headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
    )
    assert s_chunk == 411 and json.loads(d_chunk)["error"]["code"] == "length_required"

    s_bad_json, _, d_bad_json = client.request(
        "POST",
        "/api/workspace/list",
        body=b"{not-valid-json",
        headers={"Content-Type": "application/json"},
    )
    assert s_bad_json == 400 and json.loads(d_bad_json)["error"]["code"] == "invalid_json"

    s_arr, _, d_arr = client.request(
        "POST",
        "/api/workspace/list",
        body=b"[]",
        headers={"Content-Type": "application/json"},
    )
    assert s_arr == 400 and json.loads(d_arr)["error"]["code"] == "invalid_params"


def test_workspace_read_enforces_max_source_bytes_cap(workspace_env, monkeypatch):
    client: _WorkspaceClient = workspace_env["client"]
    monkeypatch.setattr(rt_workspace, "MAX_SOURCE_BYTES", 4)
    s, body = client.get_json(f"/api/workspace/read?path={quote('협조요청_개요.md')}")
    assert s == 413
    assert body["error"]["code"] == "file_too_large"


def test_extension_hook_integrates_with_bridge_application(tmp_path: Path):
    """Verify rt_workspace.register_routes / handle_get / handle_post work with rt_ui.BridgeApplication."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "공문.hwpx").write_bytes(b"PK\x03\x04demo")

    app = rt_ui.BridgeApplication(
        root=tmp_path / "rt-root",
        engine_root=REPO_ROOT,
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
    )
    app.patch_prefs({"patch": {"documentsRoot": str(docs_dir)}})

    routes = rt_workspace.register_routes(app)
    assert set(routes["get"].keys()) == {"/api/workspace/list", "/api/workspace/stat", "/api/workspace/read"}
    assert set(routes["post"].keys()) == {"/api/workspace/list", "/api/workspace/stat", "/api/workspace/read"}

    listed = routes["get"]["/api/workspace/list"]({})
    assert listed["ok"] is True
    assert [e["name"] for e in listed["entries"]] == ["공문.hwpx"]

    status, stat_res = rt_workspace.handle_get(app, "/api/workspace/stat", {"path": ["공문.hwpx"]})
    assert status == 200 and stat_res["entry"]["size"] == 8

    # Non-workspace path returns None so rt_ui continues routing normally
    assert rt_workspace.handle_get(app, "/api/prefs", {}) is None
    assert rt_workspace.handle_post(app, "/api/prefs", {}) is None


def test_workspace_routes_through_the_rigorloom_ui_extension_hook(tmp_path: Path):
    """The same routes, registered by rt_ui's own hook (`register_routes(router)`)."""
    import http.client
    import threading

    docs_dir = tmp_path / "문서"
    docs_dir.mkdir()
    (docs_dir / "공문.hwpx").write_bytes(b"PK\x03\x04demo")
    (docs_dir / "메모.txt").write_text("x", encoding="utf-8")
    prefs = tmp_path / "prefs.json"
    srv = rt_ui.create_bridge_server(root=tmp_path / "rt-root", port=0, prefs_path=prefs)
    assert "rt_workspace" in srv.extensions.modules
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    def get(path: str, token: object = ...):
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        headers = {} if token is None else {"X-Rigorloom-Token": srv.token if token is ... else str(token)}
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        finally:
            conn.close()

    try:
        # No 문서 폴더 chosen: nothing is listed, and the runtime store is never offered.
        status, body = get("/api/workspace/list")
        assert status == 404, body
        # The shell's setting writes `docFolder`.
        srv.bridge.patch_prefs({"patch": {"docFolder": str(docs_dir)}})
        status, body = get("/api/workspace/list")
        assert status == 200, body
        assert [e["name"] for e in body["entries"]] == ["공문.hwpx"]
        assert body["entries"][0]["relPath"] == "공문.hwpx"
        # Same token rule as every route.
        assert get("/api/workspace/list", token=None)[0] == 403
        assert get("/api/workspace/list", token="wrong")[0] == 403
        # Outside the root and missing answer the same 404 body.
        outside = get("/api/workspace/stat?path=..%2F..%2Fetc%2Fpasswd")
        missing = get("/api/workspace/stat?path=%EC%97%86%EC%9D%8C.hwpx")
        assert outside[0] == missing[0] == 404
        assert outside[1] == missing[1]
    finally:
        srv.shutdown_bridge()
