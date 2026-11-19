# -*- coding: utf-8 -*-
"""The MCP v2 server (``rigorloom mcp``): every wire rule, in process and over real pipes.

In-process tests drive :class:`rt_mcp.McpServer` through in-memory byte
streams with the fake document layer (tests/_fake_rt_doc.py). Subprocess
tests start ``python runtime/scripts/cli.py mcp`` with real pipes and the same
fake loaded through the test-only ``RIGORLOOM_TEST_DOC_MODULE`` seam. One test
builds the wheel and runs the server from a fresh venv without PyMuPDF.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "runtime" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _fake_rt_doc as fake  # noqa: E402
import rt_mcp  # noqa: E402
import rt_tools  # noqa: E402
import rt_toolset  # noqa: E402
from rt_codes import MAX_FRAME_BYTES  # noqa: E402
from rt_paths import sha256_file  # noqa: E402

LATEST, OLDER = "2025-06-18", "2025-03-26"
SEAM = Path(__file__).resolve().parent / "_mcp_fake_doc.py"
WAIT = 10.0

FORM = """\
# 출장 신청서

신청인은 아래와 같이 출장을 신청합니다.

| 항목 | 내용 |
|---|---|
| 기간 | 2026. 11. 3. ~ 11. 5. |
| 금액 | 450,000원 |

[[place:성명|성명]]

[[place:소속|소속]]

[[place:서명|신청인 서명 (인)]]
"""


# ---------------------------------------------------------------------------
# in-memory transport
# ---------------------------------------------------------------------------

class Chan:
    """A blocking in-memory byte pipe with ``readline(limit)``."""

    def __init__(self):
        self._buf = bytearray()
        self._closed = False
        self._cv = threading.Condition()
        self.lines: list[bytes] = []  # every complete line written, for audits

    def write(self, data: bytes) -> int:
        with self._cv:
            self._buf += data
            self._cv.notify_all()
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def readline(self, limit: int = -1, timeout: float | None = None) -> bytes:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while True:
                i = self._buf.find(b"\n")
                if i >= 0 or self._closed or (limit > 0 and len(self._buf) >= limit):
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("no line in time")
                self._cv.wait(remaining)
            n = i + 1 if i >= 0 else len(self._buf)
            if limit > 0:
                n = min(n, limit)
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out


class Session:
    """A test client wired to an McpServer running in a thread."""

    def __init__(self, **server_kw):
        self.cin, self.cout = Chan(), Chan()
        self.server = rt_mcp.McpServer(self.cin, self.cout, **server_kw)
        self.rc: list[int] = []
        self.thread = threading.Thread(target=lambda: self.rc.append(self.server.serve()),
                                       daemon=True)
        self.thread.start()
        self.stash: list[dict] = []
        self.raw: list[bytes] = []
        self._id = 0

    # wire
    def send(self, message: dict) -> None:
        self.cin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)

    def request(self, method: str, params: dict | None = None) -> int:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self._id

    def _read(self, timeout: float) -> dict:
        line = self.cout.readline(timeout=timeout)
        assert line.endswith(b"\n"), line[:200]
        assert len(line) <= MAX_FRAME_BYTES, len(line)
        self.raw.append(line)
        return json.loads(line)

    def wait_for(self, pred, timeout: float = WAIT) -> dict:
        for i, frame in enumerate(self.stash):
            if pred(frame):
                return self.stash.pop(i)
        deadline = time.monotonic() + timeout
        while True:
            frame = self._read(max(0.01, deadline - time.monotonic()))
            if pred(frame):
                return frame
            self.stash.append(frame)

    def response(self, rid) -> dict:
        return self.wait_for(lambda f: f.get("id") == rid and "method" not in f)

    def server_request(self, method: str) -> dict:
        return self.wait_for(lambda f: f.get("method") == method and "id" in f)

    def call(self, method: str, params: dict | None = None) -> dict:
        return self.response(self.request(method, params))

    def reply(self, rid, result: dict) -> None:
        self.send({"jsonrpc": "2.0", "id": rid, "result": result})

    def tool(self, name: str, args: dict | None = None) -> dict:
        frame = self.call("tools/call", {"name": name, "arguments": args or {}})
        assert "result" in frame, frame
        return frame["result"]

    def handshake(self, caps: dict | None = None, version: str = LATEST,
                  name: str = "test-client", client_version: str = "9.9") -> dict:
        frame = self.call("initialize", {
            "protocolVersion": version, "capabilities": caps or {},
            "clientInfo": {"name": name, "version": client_version}})
        self.notify("notifications/initialized")
        return frame["result"]

    def nothing_pending(self, wait: float = 0.3) -> list[dict]:
        """Frames that arrive within ``wait`` seconds (normally none)."""
        out = list(self.stash)
        self.stash.clear()
        deadline = time.monotonic() + wait
        while True:
            try:
                out.append(self._read(max(0.01, deadline - time.monotonic())))
            except TimeoutError:
                return out

    def close(self) -> int:
        self.cin.close()
        self.thread.join(WAIT)
        assert not self.thread.is_alive()
        return self.rc[0]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    for d in (home, work, outside):
        d.mkdir()
    monkeypatch.setenv("RIGORLOOM_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("RIGORLOOM_DEBUG", raising=False)
    monkeypatch.delenv(rt_tools.TEST_DOC_ENV, raising=False)
    monkeypatch.setattr(rt_toolset, "FORMATS_IN", rt_toolset.FORMATS_IN + ("fdoc",))
    monkeypatch.setattr(rt_toolset, "FORMATS_OUT", rt_toolset.FORMATS_OUT + ("fdoc",))
    monkeypatch.setattr(fake, "NATIVE_SUFFIX", ".fdoc", raising=False)
    monkeypatch.setattr(rt_tools, "load_doc", lambda: fake)
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "gongmun.md").write_text("# 공문\n\n끝. 표시를 붙입니다.\n", encoding="utf-8")
    (knowledge / "_index.md").write_text("주제: gongmun\n", encoding="utf-8")
    monkeypatch.setattr(rt_toolset, "KNOWLEDGE_DIR", knowledge)

    class Env:
        pass

    e = Env()
    e.tmp, e.home, e.work, e.outside = tmp_path, home, work, outside
    sessions: list[Session] = []

    def doc(name="신청서.fdoc", text=FORM, folder=None):
        path = (folder or work) / name
        path.write_text(text, encoding="utf-8")
        return path

    def session(**kw):
        base = dict(allow=[work], cwd=home, home=home)
        base.update(kw)
        s = Session(**base)
        sessions.append(s)
        return s

    e.doc, e.session = doc, session
    yield e
    for s in sessions:
        s.cin.close()
        s.thread.join(WAIT)


def text_of(result: dict) -> str:
    return result["content"][0]["text"]


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


# ---------------------------------------------------------------------------
# framing and lifecycle
# ---------------------------------------------------------------------------

def test_frames_are_newline_delimited_json_rpc(env):
    s = env.session()
    s.handshake()
    s.cin.write(b"{not json}\n")
    assert s.wait_for(lambda f: f.get("error", {}).get("code") == -32700)["id"] is None
    s.cin.write(b"[1, 2]\n")
    assert s.wait_for(lambda f: f.get("error", {}).get("code") == -32600)["id"] is None
    s.send({"jsonrpc": "1.0", "id": 77, "method": "tools/list"})
    assert s.response(77)["error"]["code"] == -32600
    s.cin.write(b'{"jsonrpc":"2.0","id":5,"method":"tools/list"}\n')
    assert "tools" in s.response(5)["result"]
    s.send({"jsonrpc": "2.0", "id": [1], "result": {}})  # a reply nobody asked for
    s.send({"jsonrpc": "2.0", "id": "rl-999", "result": {}})
    s.cin.write(b"\n")  # blank lines are not frames
    assert s.call("ping")["result"] == {}
    assert s.close() == 0
    for line in s.raw:
        assert line.count(b"\n") == 1 and line.endswith(b"\n")
        assert json.loads(line)["jsonrpc"] == "2.0"


def test_oversized_inbound_frame_is_refused_unread(env):
    s = env.session(max_frame=4096)
    s.handshake()
    s.cin.write(b'{"jsonrpc":"2.0","id":1,"method":"ping","x":"' + b"a" * 9000 + b'"}\n')
    assert s.wait_for(lambda f: "error" in f)["error"]["code"] == -32600
    assert s.call("ping")["result"] == {}


def test_initialize_prefers_2025_06_18_and_accepts_2025_03_26(env):
    for asked, got in ((LATEST, LATEST), (OLDER, OLDER), ("2024-11-05", LATEST),
                       ("1999-01-01", LATEST)):
        s = env.session()
        r = s.handshake(version=asked)
        assert r["protocolVersion"] == got, asked


def test_initialize_result_names_the_server(env):
    s = env.session()
    r = s.handshake()
    assert r["serverInfo"] == {"name": "rigorloom", "title": "Rigorloom",
                               "version": rt_mcp.package_version()}
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{r["serverInfo"]["version"]}"' in pyproject
    assert r["capabilities"] == {"tools": {"listChanged": False}}
    assert r["instructions"] == rt_mcp.instructions()


def test_instructions_come_from_the_knowledge_pack_capped(env, monkeypatch, tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    monkeypatch.setattr(rt_mcp, "KNOWLEDGE_DIR", pack)
    builtin = rt_mcp.instructions()
    assert builtin == rt_mcp.BUILTIN_INSTRUCTIONS
    assert "open → read/find → edit/fill → preview → check → save" in builtin
    (pack / "_instructions.md").write_text("- 첫 줄\n- 둘째 줄\n", encoding="utf-8")
    assert rt_mcp.instructions() == "- 첫 줄\n- 둘째 줄"
    (pack / "_instructions.md").write_text("\n".join(f"- 규칙 {i} " + "가" * 40
                                                     for i in range(200)), encoding="utf-8")
    capped = rt_mcp.instructions()
    assert 1000 < len(capped) <= 2000 and capped.endswith("가")
    s = env.session()
    assert s.handshake()["instructions"] == capped


def test_the_shipped_instructions_file_is_used(env):
    shipped = (SCRIPTS / "knowledge" / "_instructions.md").read_text(encoding="utf-8").strip()
    assert rt_mcp.instructions() == shipped[:2000]


def test_requests_before_initialized_are_refused_except_ping(env):
    s = env.session()
    assert s.call("tools/list")["error"]["code"] == -32600
    assert s.call("ping")["result"] == {}
    init = s.call("initialize", {"protocolVersion": LATEST, "capabilities": {},
                                 "clientInfo": {"name": "c", "version": "1"}})
    assert init["result"]["protocolVersion"] == LATEST
    assert s.call("tools/call", {"name": "guide", "arguments": {}})["error"]["code"] == -32600
    assert s.call("tools/list")["error"]["code"] == -32600
    assert s.call("ping")["result"] == {}
    s.notify("notifications/initialized")
    assert len(s.call("tools/list")["result"]["tools"]) == len(rt_tools.surface("mcp"))
    assert s.call("initialize", {"protocolVersion": LATEST})["error"]["code"] == -32600
    assert s.call("resources/list")["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# tools/list and tools/call
# ---------------------------------------------------------------------------

def test_tools_list_is_the_registry_mcp_surface(env):
    s = env.session()
    s.handshake()
    tools = s.call("tools/list")["result"]["tools"]
    registry = rt_tools.surface("mcp")
    assert [t["name"] for t in tools] == [t.name for t in registry]
    assert len(tools) == 11
    for listed, tool in zip(tools, registry):
        assert list(listed) == ["name", "title", "description", "inputSchema",
                                "outputSchema", "annotations"]
        assert listed["title"] == tool.title
        assert listed["description"] == tool.description
        assert listed["inputSchema"] == tool.input_schema
        assert listed["outputSchema"]["type"] == "object"
        assert listed["outputSchema"]["properties"]["error"] == rt_mcp.ERROR_SCHEMA
        ann = listed["annotations"]
        assert ann == tool.annotations()
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert isinstance(ann[hint], bool)
    save = next(t for t in tools if t["name"] == "save")["annotations"]
    assert save["destructiveHint"] is True and save["readOnlyHint"] is False


def test_2025_03_26_gets_no_output_schema_structured_content_or_elicitation(env):
    path = env.doc()
    s = env.session()
    r = s.handshake(caps={"elicitation": {}}, version=OLDER)
    assert "title" not in r["serverInfo"]
    tools = s.call("tools/list")["result"]["tools"]
    assert all("outputSchema" not in t and "title" not in t for t in tools)
    ok = s.tool("open", {"path": str(path)})
    assert ok["isError"] is False and "structuredContent" not in ok
    assert s.server.context().ask is None
    rev = json.loads(json.dumps(rt_tools.call(s.server.context(), "open",
                                              {"path": str(path)})))["result"]["rev"]
    s.tool("edit", {"path": str(path), "base": rev,
                    "ops": [{"op": "set", "at": "p1", "text": "다시 신청합니다."}]})
    refused = s.tool("save", {"path": str(path)})
    assert refused["isError"] is True and "structuredContent" not in refused
    assert not [f for f in s.nothing_pending() if f.get("method") == "elicitation/create"]


def test_unknown_tool_is_a_json_rpc_error(env):
    s = env.session()
    s.handshake()
    frame = s.call("tools/call", {"name": "format_disk", "arguments": {}})
    assert frame["error"]["code"] == -32602 and "result" not in frame
    assert s.call("tools/call", {"arguments": {}})["error"]["code"] == -32602
    assert s.call("tools/call", {"name": "guide", "arguments": [1]})["error"]["code"] == -32602


def test_ok_result_is_rendered_text_plus_structured_content(env):
    path = env.doc()
    s = env.session()
    s.handshake()
    r = s.tool("open", {"path": str(path)})
    assert r["isError"] is False
    assert r["content"] == [{"type": "text", "text": rt_tools.render_text(
        rt_tools.REGISTRY["open"], r["structuredContent"])}]
    assert r["structuredContent"]["rev"] == sha256_file(path)[:12]


def test_refusal_is_is_error_with_message_hint_and_candidates(env):
    path = env.doc()
    s = env.session()
    s.handshake()
    r = s.tool("fill", {"path": str(path), "values": {"place:셩명": "x"}})
    assert r["isError"] is True
    error = r["structuredContent"]["error"]
    assert error["code"] == "bad_address" and "place:성명" in error["candidates"]
    lines = text_of(r).split("\n")
    assert lines[0] == error["message"]
    if error.get("hint"):
        assert lines[1] == error["hint"]
    assert lines[-1] == "후보: " + ", ".join(error["candidates"])
    bad = s.tool("open", {"path": str(path), "extra": 1})
    assert bad["isError"] is True
    assert bad["structuredContent"]["error"]["code"] == "invalid_params"


def _validate_both(tool_name: str, listed: dict, structured: dict) -> None:
    rt_tools.validate(listed[tool_name]["outputSchema"], structured)
    rt_tools.validate(rt_tools.REGISTRY[tool_name].output_schema, structured)


def test_every_tool_result_validates_against_its_output_schema(env):
    path = env.doc()
    draft_target = env.work / "회의록.fdoc"
    s = env.session()
    s.handshake()
    listed = {t["name"]: t for t in s.call("tools/list")["result"]["tools"]}
    seen_ok, seen_err = set(), set()

    def run(name, args, want_error):
        r = s.tool(name, args)
        assert r["isError"] is want_error, (name, r["content"][0]["text"])
        assert isinstance(r["structuredContent"], dict)
        _validate_both(name, listed, r["structuredContent"])
        json.dumps(r["structuredContent"])
        (seen_err if want_error else seen_ok).add(name)
        return r["structuredContent"]

    rev = run("open", {"path": str(path)}, False)["rev"]
    run("read", {"path": str(path)}, False)
    run("find", {"path": str(path), "query": "출장"}, False)
    edited = run("edit", {"path": str(path), "base": rev, "ops": [
        {"op": "set", "at": "p1", "text": "신청인은 다시 신청합니다."}]}, False)
    run("fill", {"path": str(path), "values": {"성명": "홍길동"}}, False)
    draft = run("new", {"markdown": "# 회의록\n\n안건은 둘입니다.\n"}, False)["path"]
    run("preview", {"path": str(path)}, False)
    run("check", {"path": str(path)}, False)
    run("save", {"path": draft, "to": str(draft_target)}, False)
    run("changes", {"action": "show", "path": str(path)}, False)
    run("changes", {}, False)
    run("guide", {"topic": "gongmun"}, False)
    run("guide", {}, False)

    outside = env.doc("밖.fdoc", folder=env.outside)
    run("open", {"path": str(outside)}, True)
    run("read", {"path": str(path), "at": "p999"}, True)
    run("find", {"path": str(env.work / "없는.fdoc"), "query": "x"}, True)
    run("edit", {"path": str(path), "base": rev, "ops": [
        {"op": "set", "at": "p1", "text": "낡은 판 위에"}]}, True)
    assert edited["rev"] != rev
    run("fill", {"path": str(path), "values": {"place:서명": "홍길동"}}, True)
    run("new", {"markdown": "![x](https://example.com/a.png)"}, True)
    run("preview", {"path": str(path), "pages": [99]}, True)
    run("check", {"path": str(env.work / "없는.fdoc")}, True)
    run("save", {"path": str(path)}, True)  # no elicitation: needs_person
    run("changes", {"action": "show", "path": str(path), "id": "nope"}, True)
    run("guide", {"topic": "없는주제"}, True)

    names = {t.name for t in rt_tools.surface("mcp")}
    assert seen_ok == names and seen_err == names


# ---------------------------------------------------------------------------
# preview images and the frame cap
# ---------------------------------------------------------------------------

def test_preview_sends_one_png_image_block_per_page(env):
    path = env.doc(text=FORM + "\n---page---\n\n둘째 쪽\n\n---page---\n\n셋째 쪽\n")
    s = env.session()
    s.handshake()
    r = s.tool("preview", {"path": str(path), "pages": [1, 2, 3]})
    assert r["isError"] is False
    images = [c for c in r["content"] if c["type"] == "image"]
    assert len(images) == 3 == len(r["structuredContent"]["images"])
    for block, meta in zip(images, r["structuredContent"]["images"]):
        assert block["mimeType"] == "image/png"
        assert base64.b64decode(block["data"]) == Path(meta["file"]).read_bytes()
        assert base64.b64decode(block["data"]).startswith(b"\x89PNG")
    assert r["content"][0]["type"] == "text"


def _big_render(size: int):
    real = fake.render

    def render(path, pages=None, **kw):
        out = real(path, pages, **kw)
        for page in out.get("pages", []):
            Path(page["file"]).write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(size))
        return out
    return render


def test_preview_drops_images_from_the_end_to_fit_the_frame_cap(env, monkeypatch):
    path = env.doc(text=FORM + "\n---page---\n\n둘째\n\n---page---\n\n셋째\n")
    monkeypatch.setattr(fake, "render", _big_render(400_000))
    s = env.session()
    s.handshake()
    rid = s.request("tools/call", {"name": "preview",
                                   "arguments": {"path": str(path), "pages": [1, 2, 3]}})
    frame = s.response(rid)
    line = s.raw[-1]
    assert len(line) <= MAX_FRAME_BYTES
    r = frame["result"]
    images = [c for c in r["content"] if c["type"] == "image"]
    assert len(images) == 1  # 3 x 533 KB of base64 do not fit in 1 MiB; one does
    text = text_of(r)
    assert "not sent" in text and "2, 3" in text
    assert [i["page"] for i in r["structuredContent"]["images"]] == [1, 2, 3]


def test_preview_with_one_image_over_the_cap_sends_none(env, monkeypatch):
    path = env.doc()
    monkeypatch.setattr(fake, "render", _big_render(MAX_FRAME_BYTES))
    s = env.session()
    s.handshake()
    r = s.tool("preview", {"path": str(path), "pages": [1]})
    assert [c["type"] for c in r["content"]] == ["text"]
    assert "not sent" in text_of(r) and ": 1" in text_of(r)
    assert all(len(line) <= MAX_FRAME_BYTES for line in s.raw)


# ---------------------------------------------------------------------------
# the call context
# ---------------------------------------------------------------------------

def test_context_names_the_client_and_reads_drafts(env):
    path = env.doc()
    s = env.session()
    s.handshake(name="Claude Code", client_version="2.1.0")
    ctx = s.server.context()
    assert ctx.client == "mcp:Claude Code"
    assert ctx.provenance == {"clientVersion": "2.1.0"}
    assert ctx.source == "draft" and ctx.write_mode == "draft"
    assert ctx.ask is None  # no elicitation declared
    rev = s.tool("open", {"path": str(path)})["structuredContent"]["rev"]
    s.tool("edit", {"path": str(path), "base": rev,
                    "ops": [{"op": "set", "at": "p1", "text": "고친 문장"}]})
    shown = s.tool("changes", {"action": "show", "path": str(path)})["structuredContent"]
    assert shown["changesets"][-1]["author"] == "mcp:Claude Code"
    seen = s.tool("read", {"path": str(path), "at": "p1"})["structuredContent"]
    assert seen["source"] == "draft" and seen["blocks"][0]["text"] == "고친 문장"


# ---------------------------------------------------------------------------
# roots
# ---------------------------------------------------------------------------

def test_root_uris(monkeypatch):
    f = rt_mcp.root_uri_to_path
    assert f("file:///home/kim/%EB%AC%B8%EC%84%9C", windows=False) == "/home/kim/문서"
    assert f("file:///home/kim/my%20docs", windows=False) == "/home/kim/my docs"
    assert f("file://localhost/srv/x", windows=False) == "/srv/x"
    assert f("file:///C:/Users/kim/%EB%AC%B8%EC%84%9C", windows=True) == "C:\\Users\\kim\\문서"
    assert f("file:///c:/", windows=True) == "C:\\"
    assert f("file:///C|/x", windows=True) == "C:\\x"
    assert f("file:///C:/x", windows=False) is None        # a drive path on POSIX
    assert f("file:///home/x", windows=True) is None       # no drive on Windows
    for uri in ("file://server/share/docs", "file:////server/share", "file://///server/s",
                "https://example.com/x", "smb://server/share", "", None, 42,
                "file:///a%00b", "file:///%FF%FE", "relative/path"):
        assert f(uri, windows=False) is None, uri
        assert f(uri, windows=True) is None, uri


def test_roots_round_trip(env):
    folder = env.tmp / "문서 폴더"
    folder.mkdir()
    inside = env.doc(folder=folder)
    outside = env.doc("밖.fdoc", folder=env.outside)
    s = env.session(allow=[])
    s.handshake(caps={"roots": {"listChanged": True}})
    ask = s.server_request("roots/list")
    assert "params" not in ask or ask["params"] in ({}, None)
    s.reply(ask["id"], {"roots": [{"uri": file_uri(folder), "name": "문서"},
                                  {"uri": "https://example.com/"}]})
    assert s.tool("open", {"path": str(inside)})["isError"] is False
    r = s.tool("open", {"path": str(outside)})
    assert r["structuredContent"]["error"]["code"] == "outside_roots"
    assert s.server.client_roots == [folder.resolve()]


def test_a_call_before_the_roots_answer_waits_and_pings_still_work(env):
    path = env.doc()
    s = env.session(allow=[])
    s.handshake(caps={"roots": {}})
    ask = s.server_request("roots/list")
    call_id = s.request("tools/call", {"name": "open", "arguments": {"path": str(path)}})
    ping_id = s.request("ping")
    assert s.response(ping_id)["result"] == {}
    assert not [f for f in s.nothing_pending(0.2) if f.get("id") == call_id]
    s.reply(ask["id"], {"roots": [{"uri": file_uri(env.work)}]})
    assert s.response(call_id)["result"]["isError"] is False


def test_roots_wait_is_bounded(env):
    path = env.doc()
    s = env.session(allow=[], cwd=env.work, roots_timeout=0.3)
    s.handshake(caps={"roots": {}})
    s.server_request("roots/list")  # never answered
    started = time.monotonic()
    r = s.tool("open", {"path": str(path)})
    assert 0.25 <= time.monotonic() - started < 5
    assert r["isError"] is False  # fell back to the working folder
    started = time.monotonic()
    s.tool("open", {"path": str(path)})
    assert time.monotonic() - started < 0.25  # gave up once, does not wait again


def test_roots_list_changed_refreshes(env):
    a, b = env.tmp / "a", env.tmp / "b"
    a.mkdir(), b.mkdir()
    in_a, in_b = env.doc(folder=a), env.doc(folder=b)
    s = env.session(allow=[])
    s.handshake(caps={"roots": {"listChanged": True}})
    s.reply(s.server_request("roots/list")["id"], {"roots": [{"uri": file_uri(a)}]})
    assert s.tool("open", {"path": str(in_a)})["isError"] is False
    assert s.tool("open", {"path": str(in_b)})["isError"] is True
    s.notify("notifications/roots/list_changed")
    s.reply(s.server_request("roots/list")["id"], {"roots": [{"uri": file_uri(b)}]})
    assert s.tool("open", {"path": str(in_b)})["isError"] is False
    r = s.tool("open", {"path": str(in_a)})
    assert r["structuredContent"]["error"]["code"] == "outside_roots"


def test_allow_adds_to_client_roots(env):
    a, b = env.tmp / "a", env.tmp / "b"
    a.mkdir(), b.mkdir()
    in_a, in_b = env.doc(folder=a), env.doc(folder=b)
    s = env.session(allow=[b], cwd=env.work)
    s.handshake(caps={"roots": {}})
    s.reply(s.server_request("roots/list")["id"], {"roots": [{"uri": file_uri(a)}]})
    assert s.tool("open", {"path": str(in_a)})["isError"] is False
    assert s.tool("open", {"path": str(in_b)})["isError"] is False
    # client roots given: the working folder is not added
    assert s.tool("open", {"path": str(env.doc(folder=env.work))})["isError"] is True


def test_no_roots_capability_falls_back_to_a_safe_cwd(env):
    path = env.doc()
    s = env.session(allow=[], cwd=env.work)
    s.handshake()
    assert not [f for f in s.nothing_pending(0.2) if f.get("method") == "roots/list"]
    assert s.tool("open", {"path": str(path)})["isError"] is False
    outside = env.doc(folder=env.outside)
    assert s.tool("open", {"path": str(outside)})["structuredContent"]["error"]["code"] \
        == "outside_roots"


def test_an_empty_roots_list_falls_back_to_a_safe_cwd(env):
    path = env.doc()
    s = env.session(allow=[], cwd=env.work)
    s.handshake(caps={"roots": {}})
    s.reply(s.server_request("roots/list")["id"], {"roots": []})
    assert s.tool("open", {"path": str(path)})["isError"] is False


def _expected_allow_line() -> str:
    folder = "D:\\문서" if os.name == "nt" else "$HOME/문서"
    return f'rigorloom mcp --allow "{folder}"'


def test_cwd_fallback_refused_for_home(env):
    path = env.doc(folder=env.home)
    s = env.session(allow=[], cwd=env.home, home=env.home)
    s.handshake()
    r = s.tool("open", {"path": str(path)})
    error = r["structuredContent"]["error"]
    assert error["code"] == "no_roots"
    assert _expected_allow_line() in error["hint"]
    assert _expected_allow_line() in text_of(r)


def test_cwd_fallback_refused_for_a_filesystem_root(env):
    anchor = Path(env.tmp.anchor)
    s = env.session(allow=[], cwd=anchor, home=env.home)
    s.handshake(caps={"roots": {}})
    s.reply(s.server_request("roots/list")["id"], {"roots": []})
    path = env.doc()
    for tool, args in (("open", {"path": str(path)}), ("read", {"path": str(path)}),
                       ("save", {"path": str(path), "to": str(env.work / "x.fdoc")})):
        r = s.tool(tool, args)
        assert r["structuredContent"]["error"]["code"] == "no_roots", tool
    assert rt_mcp.cwd_fallback(anchor, env.home) is None
    assert rt_mcp.cwd_fallback(env.home, env.home) is None
    assert rt_mcp.cwd_fallback(env.work, env.home) == env.work.resolve()


def test_allow_line_examples():
    assert rt_mcp.allow_line(None, windows=True) == 'rigorloom mcp --allow "D:\\문서"'
    assert rt_mcp.allow_line(None, windows=False) == 'rigorloom mcp --allow "$HOME/문서"'
    assert rt_mcp.allow_line(Path("/srv/docs"), windows=False) \
        == f'rigorloom mcp --allow "{Path("/srv/docs")}"'


# ---------------------------------------------------------------------------
# save and elicitation
# ---------------------------------------------------------------------------

ELICIT = {"elicitation": {}}


def _edited(s: Session, path: Path) -> None:
    rev = s.tool("open", {"path": str(path)})["structuredContent"]["rev"]
    r = s.tool("edit", {"path": str(path), "base": rev, "ops": [
        {"op": "replace", "find": "450,000원", "with": "480,000원"}]})
    assert r["isError"] is False, text_of(r)


def _save_and_get_question(s: Session, path: Path) -> tuple[int, dict]:
    rid = s.request("tools/call", {"name": "save", "arguments": {"path": str(path)}})
    return rid, s.server_request("elicitation/create")


def test_save_to_a_new_path_creates_without_asking(env):
    path = env.doc()
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    target = env.work / "신청서-수정.fdoc"
    r = s.tool("save", {"path": str(path), "to": str(target)})
    assert r["structuredContent"]["acceptedVia"] == "policy:new-file"
    assert "480,000원" in target.read_text(encoding="utf-8")
    assert not [f for f in s.nothing_pending(0.2) if f.get("method") == "elicitation/create"]
    # re-save over the file this draft created: allowed, unprompted
    rev = s.tool("open", {"path": str(path)})["structuredContent"]["rev"]
    s.tool("edit", {"path": str(path), "base": rev, "ops": [
        {"op": "replace", "find": "480,000원", "with": "490,000원"}]})
    r2 = s.tool("save", {"path": str(path), "to": str(target)})
    assert r2["structuredContent"]["acceptedVia"] == "policy:own-file"
    assert not [f for f in s.nothing_pending(0.2) if f.get("method") == "elicitation/create"]


def test_elicitation_accept_overwrites(env):
    path = env.doc()
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    params = ask["params"]
    assert params["requestedSchema"] == {
        "type": "object",
        "properties": {"overwrite": {"type": "boolean", "title": "덮어쓰기"}},
        "required": ["overwrite"]}
    message = params["message"].splitlines()
    assert message[0] == f'"{path.resolve()}" 파일을 덮어쓸까요?'
    assert "바뀐 쪽: 1" in message
    assert "에이전트가 고친 내용 중 아직 아무도 확인하지 않은 항목: 1건" in message
    assert not any(line.startswith("변환하면 빠지는 항목") for line in message)
    assert message[-2:] == ["이전 내용은 저장 기록에 남습니다.",
                            f'되돌리기: rigorloom undo "{path.resolve()}"']
    s.reply(ask["id"], {"action": "accept", "content": {"overwrite": True}})
    r = s.response(rid)["result"]
    assert r["isError"] is False
    assert r["structuredContent"]["acceptedVia"] == "person:elicitation"
    assert "480,000원" in path.read_text(encoding="utf-8")


def test_elicitation_names_a_file_with_an_invisible_character(env):
    # The same escape and warning line as the terminal prompt: a zero-width
    # space must not let one file pass for another in the question.
    path = env.doc(name="신청서\u200b.fdoc")
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    message = ask["params"]["message"].splitlines()
    shown = str(path.resolve()).replace("\\", "\\\\").replace("\u200b", "\\u200b")
    assert message[0] == f'"{shown}" 파일을 덮어쓸까요?'
    assert message[1] == "파일 이름에 보이지 않는 문자가 있습니다: U+200B"
    s.reply(ask["id"], {"action": "decline"})
    assert s.response(rid)["result"]["isError"] is True


@pytest.mark.parametrize("answer,code", [
    ({"action": "accept", "content": {"overwrite": False}}, "declined_by_person"),
    ({"action": "decline"}, "declined_by_person"),
    ({"action": "cancel"}, "needs_person"),
])
def test_elicitation_no_and_cancel_keep_the_file(env, answer, code):
    path = env.doc()
    before = path.read_bytes()
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    s.reply(ask["id"], answer)
    r = s.response(rid)["result"]
    assert r["isError"] is True
    assert r["structuredContent"]["error"]["code"] == code
    assert path.read_bytes() == before
    if code == "declined_by_person":
        # a decline is final for this content and target: not asked again
        again = s.tool("save", {"path": str(path)})
        assert again["structuredContent"]["error"]["code"] == "declined_by_person"
        assert not [f for f in s.nothing_pending(0.2)
                    if f.get("method") == "elicitation/create"]


def test_elicitation_error_reply_is_no_answer(env):
    path = env.doc()
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    s.send({"jsonrpc": "2.0", "id": ask["id"], "error": {"code": -32601, "message": "no"}})
    assert s.response(rid)["result"]["structuredContent"]["error"]["code"] == "needs_person"


def test_elicitation_unsupported_is_needs_person(env):
    path = env.doc()
    before = path.read_bytes()
    s = env.session()
    s.handshake(caps={})
    _edited(s, path)
    r = s.tool("save", {"path": str(path)})
    error = r["structuredContent"]["error"]
    assert error["code"] == "needs_person" and "rigorloom save" in error["hint"]
    assert path.read_bytes() == before
    assert not [f for f in s.nothing_pending(0.2) if f.get("method") == "elicitation/create"]


def test_elicitation_timeout_is_no_answer(env):
    path = env.doc()
    before = path.read_bytes()
    s = env.session(elicit_timeout=0.3)
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    r = s.response(rid)["result"]
    assert r["structuredContent"]["error"]["code"] == "needs_person"
    cancel = s.wait_for(lambda f: f.get("method") == "notifications/cancelled")
    assert cancel["params"]["requestId"] == ask["id"] and "id" not in cancel
    assert path.read_bytes() == before
    s.reply(ask["id"], {"action": "accept", "content": {"overwrite": True}})  # too late
    assert s.call("ping")["result"] == {}
    assert path.read_bytes() == before


def test_while_a_person_decides_pings_answer_and_requests_queue(env):
    path = env.doc()
    s = env.session()
    s.handshake(caps=ELICIT)
    _edited(s, path)
    rid, ask = _save_and_get_question(s, path)
    ping = s.request("ping")
    assert s.response(ping)["result"] == {}
    listed = s.request("tools/list")
    dropped = s.request("tools/call", {"name": "guide", "arguments": {}})
    s.notify("notifications/cancelled", {"requestId": dropped, "reason": "user"})
    s.notify("notifications/cancelled", {"requestId": rid, "reason": "user"})  # running: ignored
    assert not [f for f in s.nothing_pending(0.2) if f.get("id") in (listed, rid)]
    s.reply(ask["id"], {"action": "accept", "content": {"overwrite": True}})
    order = []
    while len(order) < 2:
        frame = s.wait_for(lambda f: f.get("id") in (rid, listed, dropped))
        order.append(frame["id"])
    assert order == [rid, listed]
    assert not [f for f in s.nothing_pending(0.3) if f.get("id") == dropped]


def test_cancel_for_a_queued_request_drops_it(env):
    s = env.session()
    s.handshake()
    server = s.server
    server._backlog.append({"jsonrpc": "2.0", "id": 41, "method": "tools/list"})
    server._notification("notifications/cancelled", {"requestId": 41})
    assert server._backlog == []


# ---------------------------------------------------------------------------
# the CLI entry and the test seam
# ---------------------------------------------------------------------------

def test_mcp_is_a_product_verb_that_no_legacy_command_uses():
    import cli
    import rt_cli_product
    assert "mcp" in rt_cli_product.PRODUCT_VERBS
    assert rt_cli_product.is_product(["mcp", "--allow", "x"])
    assert not rt_cli_product.is_product(["--root", "r", "mcp"])
    legacy = cli.build_parser()
    subs = next(a for a in legacy._actions if a.__class__.__name__ == "_SubParsersAction")
    assert "mcp" not in subs.choices


def test_test_seam_loads_a_document_module_from_a_file(monkeypatch):
    # the seam widens the accepted formats; restore them afterwards
    monkeypatch.setattr(rt_toolset, "FORMATS_IN", rt_toolset.FORMATS_IN)
    monkeypatch.setattr(rt_toolset, "FORMATS_OUT", rt_toolset.FORMATS_OUT)
    monkeypatch.setattr(rt_tools, "_test_docs", {})
    monkeypatch.setenv(rt_tools.TEST_DOC_ENV, str(SEAM))
    doc = rt_tools.load_doc()
    assert doc.NATIVE_SUFFIX == ".fdoc" and doc.render is fake.render
    assert rt_tools.load_doc() is doc
    assert "fdoc" in rt_toolset.FORMATS_IN and "fdoc" in rt_toolset.FORMATS_OUT


def test_no_pymupdf_in_the_mcp_import_path():
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import rt_mcp, rt_toolset, rt_tools; "
             "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('fitz', 'pymupdf')); "
             "print(bad)")
    out = subprocess.run([sys.executable, "-c", probe, str(SCRIPTS)], capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ---------------------------------------------------------------------------
# subprocess: real pipes
# ---------------------------------------------------------------------------

class Proc:
    """A server process with line readers on stdout and stderr (no select: Windows)."""

    def __init__(self, argv: list[str], env: dict, cwd: Path):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, cwd=str(cwd))
        self.lines: queue.Queue = queue.Queue()
        self.stdout: list[bytes] = []
        self.stderr = bytearray()
        self._id = 0
        threading.Thread(target=self._pump_out, daemon=True).start()
        self._err_thread = threading.Thread(target=self._pump_err, daemon=True)
        self._err_thread.start()

    def _pump_out(self):
        for line in iter(self.p.stdout.readline, b""):
            self.stdout.append(line)
            self.lines.put(line)
        self.lines.put(None)

    def _pump_err(self):
        for chunk in iter(lambda: self.p.stderr.read(4096), b""):
            self.stderr += chunk

    def send(self, msg: dict) -> None:
        self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError(f"no answer to {method}; stderr:\n"
                                     + self.stderr.decode("utf-8", "replace")) from None
            assert line is not None, "server closed stdout: " + self.stderr.decode(
                "utf-8", "replace")
            frame = json.loads(line)
            if frame.get("id") == self._id and "method" not in frame:
                return frame

    def tool(self, name: str, args: dict) -> dict:
        frame = self.call("tools/call", {"name": name, "arguments": args})
        assert "result" in frame, frame
        return frame["result"]

    def finish(self, timeout: float = 30) -> int:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            rc = self.p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait(timeout=timeout)
            raise
        self._err_thread.join(timeout)
        self.p.stdout.close()
        self.p.stderr.close()
        return rc

    def kill(self) -> None:
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait(timeout=30)
        for stream in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                stream.close()
            except OSError:
                pass


def _no_pymupdf_dir(tmp: Path) -> tuple[Path, Path]:
    """A sys.path entry where importing fitz/pymupdf fails and leaves a marker."""
    blocker = tmp / "no-pymupdf"
    blocker.mkdir()
    marker = tmp / "pymupdf-imported"
    body = ("import os\n"
            "open(os.environ['RL_TEST_PYMUPDF_MARKER'], 'w').close()\n"
            "raise ImportError('PyMuPDF is not installed (test)')\n")
    for name in ("fitz.py", "pymupdf.py"):
        (blocker / name).write_text(body, encoding="utf-8")
    return blocker, marker


def _child_env(tmp: Path, **extra) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               RIGORLOOM_HOME=str(tmp / "state"))
    env.pop("RIGORLOOM_DEBUG", None)
    env.update(extra)
    return env


def test_stdio_server_end_to_end(tmp_path):
    work = tmp_path / "작업 폴더"
    elsewhere = tmp_path / "cwd"
    work.mkdir(), elsewhere.mkdir()
    source = work / "신청서.fdoc"
    source.write_text(FORM, encoding="utf-8")
    blocker, marker = _no_pymupdf_dir(tmp_path)
    env = _child_env(tmp_path, RIGORLOOM_TEST_DOC_MODULE=str(SEAM),
                     PYTHONPATH=str(blocker), RL_TEST_PYMUPDF_MARKER=str(marker))
    proc = Proc([sys.executable, str(SCRIPTS / "cli.py"), "mcp", "--allow", str(work)],
                env, elsewhere)
    try:
        init = proc.call("initialize", {"protocolVersion": LATEST, "capabilities": {},
                                        "clientInfo": {"name": "pipe-test", "version": "1"}})
        assert init["result"]["protocolVersion"] == LATEST
        assert init["result"]["serverInfo"]["name"] == "rigorloom"
        proc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = proc.call("tools/list")["result"]["tools"]
        assert len(tools) == 11

        opened = proc.tool("open", {"path": str(source)})
        assert opened["isError"] is False, opened["content"][0]["text"]
        rev = opened["structuredContent"]["rev"]
        edited = proc.tool("edit", {"path": str(source), "base": rev, "ops": [
            {"op": "replace", "find": "450,000원", "with": "480,000원"}]})
        assert edited["isError"] is False, edited["content"][0]["text"]
        assert "450,000원" in source.read_text(encoding="utf-8")

        preview = proc.tool("preview", {"path": str(source)})
        assert preview["isError"] is False, preview["content"][0]["text"]
        assert [c["type"] for c in preview["content"]] == ["text", "image"]

        target = work / "신청서-수정.fdoc"
        saved = proc.tool("save", {"path": str(source), "to": str(target)})
        assert saved["isError"] is False, saved["content"][0]["text"]
        assert "480,000원" in target.read_text(encoding="utf-8")

        refused = proc.tool("save", {"path": str(source)})
        assert refused["isError"] is True
        assert refused["structuredContent"]["error"]["code"] == "needs_person"
        assert "450,000원" in source.read_text(encoding="utf-8")

        outside = proc.tool("open", {"path": str(tmp_path / "밖.fdoc")})
        assert outside["structuredContent"]["error"]["code"] in ("outside_roots", "not_found")
    except BaseException:
        proc.kill()
        raise
    assert proc.finish() == 0
    for line in proc.stdout:
        assert line.endswith(b"\n") and json.loads(line)["jsonrpc"] == "2.0"
    log = proc.stderr.decode("utf-8", "replace")
    assert "rigorloom mcp" in log and "RIGORLOOM_TEST_DOC_MODULE" in log
    assert not marker.exists(), "something imported PyMuPDF"


def test_stdio_server_with_no_roots_refuses_with_the_allow_line(tmp_path):
    home = Path.home()
    env = _child_env(tmp_path, RIGORLOOM_TEST_DOC_MODULE=str(SEAM))
    proc = Proc([sys.executable, str(SCRIPTS / "cli.py"), "mcp"], env, home)
    try:
        proc.call("initialize", {"protocolVersion": LATEST, "capabilities": {},
                                 "clientInfo": {"name": "pipe-test", "version": "1"}})
        proc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = proc.tool("open", {"path": str(home / "x.fdoc")})
        assert r["structuredContent"]["error"]["code"] == "no_roots"
        assert _expected_allow_line() in r["content"][0]["text"]
    except BaseException:
        proc.kill()
        raise
    assert proc.finish() == 0


# ---------------------------------------------------------------------------
# the installed wheel: knowledge ships, PyMuPDF absent
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    from test_cli_distribution import _build_python, _export_clean_tree, _run
    build_python = _build_python()
    if build_python is None:
        pytest.skip("no offline wheel toolchain (see test_cli_distribution.py)")
    base = tmp_path_factory.mktemp("mcp-wheel")
    source = _export_clean_tree(base / "source")
    topic = source / "runtime" / "scripts" / "knowledge" / "gongmun.md"
    topic.write_text("# 공문\n\n끝. 표시를 붙입니다.\n", encoding="utf-8")
    wheelhouse = base / "wheelhouse"
    wheelhouse.mkdir()
    built = _run([build_python, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                  "--no-index", "--wheel-dir", str(wheelhouse), str(source)], timeout=600)
    assert built.returncode == 0, built.stderr[-3000:]
    venv = base / "venv"
    created = _run([sys.executable, "-m", "venv", str(venv)], timeout=600)
    assert created.returncode == 0, created.stderr[-2000:]
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    if _run([str(python), "-m", "pip", "--version"]).returncode != 0:
        pytest.skip("the fresh venv has no pip")
    wheel = next(wheelhouse.glob("*.whl"))
    done = _run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
                timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    command = bindir / ("rigorloom.exe" if os.name == "nt" else "rigorloom")
    return {"python": python, "command": command, "source": source}


def test_installed_wheel_serves_guide_instructions_and_preview_without_pymupdf(
        installed, tmp_path):
    probe = subprocess.run([str(installed["python"]), "-c", "import fitz"],
                           capture_output=True, timeout=120)
    assert probe.returncode != 0, "the fresh venv should not have PyMuPDF"
    work = tmp_path / "work"
    work.mkdir()
    source = work / "신청서.fdoc"
    source.write_text(FORM, encoding="utf-8")
    env = _child_env(tmp_path, RIGORLOOM_TEST_DOC_MODULE=str(SEAM))
    env.pop("PYTHONPATH", None)
    proc = Proc([str(installed["command"]), "mcp", "--allow", str(work)], env, tmp_path)
    try:
        init = proc.call("initialize", {"protocolVersion": LATEST, "capabilities": {},
                                        "clientInfo": {"name": "wheel", "version": "1"}})
        shipped = (installed["source"] / "runtime" / "scripts" / "knowledge"
                   / "_instructions.md").read_text(encoding="utf-8").strip()
        assert init["result"]["instructions"] == shipped
        assert init["result"]["serverInfo"]["version"] == rt_mcp.package_version()
        proc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        guide = proc.tool("guide", {"topic": "gongmun"})
        assert guide["isError"] is False and "끝. 표시" in guide["content"][0]["text"]
        index = proc.tool("guide", {})
        assert index["structuredContent"]["topics"] == ["gongmun"]
        preview = proc.tool("preview", {"path": str(source), "pages": [1]})
        assert preview["isError"] is False, preview["content"][0]["text"]
        assert any(c["type"] == "image" for c in preview["content"])
    except BaseException:
        proc.kill()
        raise
    assert proc.finish() == 0
