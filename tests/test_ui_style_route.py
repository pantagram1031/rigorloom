"""``POST /api/style/check`` (runtime/scripts/rt_ui_style.py), advisor ruling B.

Read-only, confined to the bridge root, and behind the same token, Host and
body-cap checks as every other ``/api/`` route. The route takes ids, never a
path; the confinement tests prove an id cannot be turned into one.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
CORPUS_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402
import rt_ui_style  # noqa: E402
from rt_session import Session  # noqa: E402


def _session(root: Path, source: Path = CORPUS_FORM) -> Session:
    return Session.open_path(root, str(source))


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


# --- handler level ------------------------------------------------------------------


def test_style_check_reads_the_session_source(tmp_path: Path) -> None:
    root = tmp_path / "root"
    session = _session(root)
    before = _snapshot(root)
    out = rt_ui_style.style_check(root, {"sessionId": session.id})
    assert out["ok"] is True
    assert isinstance(out["findings"], list)
    assert set(out["counts"]) == {"error", "notice"}
    # Read-only: nothing under the root changed.
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "session_id",
    [
        "../outside",
        "..",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "\\\\server\\share\\x",
        "abc\x00def",
        "a/b",
        "",
        123,
        None,
    ],
)
def test_ids_that_look_like_paths_are_refused(tmp_path: Path, session_id) -> None:
    root = tmp_path / "root"
    _session(root)
    with pytest.raises(rt_ui_style.StyleRouteError) as exc:
        rt_ui_style.style_check(root, {"sessionId": session_id})
    assert exc.value.code == "invalid_params"


def test_unknown_session_and_outside_targets_answer_the_same(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # A well-formed id that does not exist.
    with pytest.raises(rt_ui_style.StyleRouteError) as missing:
        rt_ui_style.style_check(root, {"sessionId": "0" * 32})
    # A session whose source is a symlink to a file outside the root.
    outside = tmp_path / "outside.txt"
    outside.write_text("이 방법은 널리 사용되어지고 있다.\n", encoding="utf-8")
    session = _session(root)
    name = session.meta["sourceName"]
    src = session.source_dir / name
    src.unlink()
    os.symlink(outside, src)
    with pytest.raises(rt_ui_style.StyleRouteError) as escaped:
        rt_ui_style.style_check(root, {"sessionId": session.id})
    assert missing.value.status == escaped.value.status == 404
    assert missing.value.payload() == escaped.value.payload()


def test_symlinked_session_directory_is_refused_even_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    session = _session(root)
    real = root / "sessions" / session.id
    moved = root / "elsewhere"
    shutil.move(str(real), str(moved))
    os.symlink(moved, real)
    with pytest.raises(rt_ui_style.StyleRouteError) as exc:
        rt_ui_style.style_check(root, {"sessionId": session.id})
    assert exc.value.status == 404


def test_a_symlinked_root_is_the_root(tmp_path: Path) -> None:
    """Finding 7: a runtime root that is itself a symlink (macOS /tmp, a
    Documents folder redirected to a cloud drive) serves its documents; a
    symlink below it is still refused."""
    real = tmp_path / "real-root"
    session = _session(real)
    link = tmp_path / "Documents-link"
    os.symlink(real, link)
    assert rt_ui_style.style_check(link, {"sessionId": session.id})["ok"] is True
    # Below the (symlinked) root, a symlinked session directory is refused.
    inner = real / "sessions" / session.id
    moved = real / "elsewhere"
    shutil.move(str(inner), str(moved))
    os.symlink(moved, inner)
    with pytest.raises(rt_ui_style.StyleRouteError) as exc:
        rt_ui_style.style_check(link, {"sessionId": session.id})
    assert exc.value.status == 404


def test_a_source_name_that_climbs_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    session = _session(root)
    meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
    meta["sourceName"] = "../../../outside.hwpx"
    session.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(rt_ui_style.StyleRouteError) as exc:
        rt_ui_style.style_check(root, {"sessionId": session.id})
    assert exc.value.status == 404


def test_unknown_run_is_not_found_and_unknown_fields_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    session = _session(root)
    with pytest.raises(rt_ui_style.StyleRouteError) as exc:
        rt_ui_style.style_check(root, {"sessionId": session.id, "runId": "f" * 32})
    assert exc.value.status == 404
    with pytest.raises(rt_ui_style.StyleRouteError) as extra:
        rt_ui_style.style_check(root, {"sessionId": session.id, "path": "/etc/passwd"})
    assert extra.value.code == "unknown_field"
    with pytest.raises(rt_ui_style.StyleRouteError) as dt:
        rt_ui_style.style_check(root, {"sessionId": session.id, "docType": "../x"})
    assert dt.value.code == "invalid_params"
    # A docType that is not a string is a bad request, not a crash (finding 11).
    for bad in (["gongmun"], {"a": 1}, 3):
        with pytest.raises(rt_ui_style.StyleRouteError) as dt:
            rt_ui_style.style_check(root, {"sessionId": session.id, "docType": bad})
        assert dt.value.status == 400 and dt.value.code == "invalid_params", bad


# --- over HTTP ------------------------------------------------------------------------


@pytest.fixture()
def bridge(tmp_path: Path):
    root = tmp_path / "rt-root"
    srv = rt_ui.create_bridge_server(
        root=root, engine_root=REPO_ROOT, port=0, explicit_root=True,
        prefs_path=tmp_path / "prefs.json", auto_start=False,
    )
    # The production path: the route is on the bridge's own extension router,
    # and the handler class is the bridge's, unpatched.
    assert rt_ui_style.ROUTE in srv.extensions.post_routes
    assert rt_ui.BridgeHTTPHandler.do_POST.__module__ == rt_ui.__name__
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, root
    finally:
        srv.shutdown_bridge()
        thread.join(timeout=5)


def _post(srv, body: bytes, headers: dict[str, str]) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.request("POST", rt_ui_style.ROUTE, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    finally:
        conn.close()


def test_unauthenticated_request_is_refused(bridge) -> None:
    srv, root = bridge
    session = _session(root)
    body = json.dumps({"sessionId": session.id}).encode()
    status, payload = _post(srv, body, {"Content-Type": "application/json"})
    assert status == 403
    assert payload["error"]["code"] == "unauthorized"
    status, payload = _post(srv, body, {"Content-Type": "application/json", "X-Rigorloom-Token": "wrong"})
    assert status == 403


def test_host_origin_and_cross_site_guards_apply(bridge) -> None:
    srv, root = bridge
    session = _session(root)
    body = json.dumps({"sessionId": session.id}).encode()
    status, payload = _post(srv, body, {"X-Rigorloom-Token": srv.token, "Host": "evil.example"})
    assert status == 403 and payload["error"]["code"] == "invalid_host"
    status, payload = _post(srv, body, {"X-Rigorloom-Token": srv.token, "Sec-Fetch-Site": "cross-site"})
    assert status == 403 and payload["error"]["code"] == "cross_site_refused"
    status, payload = _post(srv, body, {"X-Rigorloom-Token": srv.token, "Origin": "https://evil.example"})
    assert status == 403 and payload["error"]["code"] == "invalid_origin"


def test_body_cap_applies(bridge) -> None:
    srv, _root = bridge
    # The cap is checked on Content-Length before the body is read.
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.putrequest("POST", rt_ui_style.ROUTE)
        conn.putheader("X-Rigorloom-Token", srv.token)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(rt_ui.MAX_JSON_BODY_BYTES + 1))
        conn.endheaders()
        conn.send(b"{}")
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()
    assert resp.status == 413
    assert payload["error"]["code"] == "body_too_large"


def test_authenticated_request_runs_the_check(bridge) -> None:
    srv, root = bridge
    session = _session(root)
    before = _snapshot(root)
    status, payload = _post(
        srv, json.dumps({"sessionId": session.id}).encode(),
        {"X-Rigorloom-Token": srv.token, "Content-Type": "application/json"},
    )
    assert status == 200, payload
    assert payload["ok"] is True
    assert _snapshot(root) == before
    status, payload = _post(
        srv, json.dumps({"sessionId": "../" + session.id}).encode(),
        {"X-Rigorloom-Token": srv.token, "Content-Type": "application/json"},
    )
    assert status == 400
    # Other POST routes are unaffected.
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.request("POST", "/api/no-such-route", body=b"{}",
                     headers={"X-Rigorloom-Token": srv.token, "Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
    finally:
        conn.close()
    assert resp.status == 404


def test_style_route_registers_on_the_rigorloom_ui_extension_hook(tmp_path: Path) -> None:
    """`rigorloom ui` serves the route through WP2's hook, with the same answers."""
    assert rt_ui_style.ROUTE in rt_ui.load_ui_extensions().post_routes
    router = rt_ui.ExtensionRouter()
    rt_ui_style.register_routes(router)
    handler = router.post_routes[rt_ui_style.ROUTE]
    root = tmp_path / "root"
    session = _session(root)

    class Bridge:
        def current_root(self) -> Path:
            return root

    out = handler(Bridge(), {"sessionId": session.id})
    assert out["ok"] is True and "findings" in out
    with pytest.raises(rt_ui.BridgeError) as missing:
        handler(Bridge(), {"sessionId": "0" * 32})
    with pytest.raises(rt_ui.BridgeError) as bad:
        handler(Bridge(), {"sessionId": session.id, "extra": 1})
    assert missing.value.status == 404 and missing.value.code == "not_found"
    assert bad.value.status == 400 and bad.value.code == "unknown_field"
