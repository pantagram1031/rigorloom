# -*- coding: utf-8 -*-
"""Shared support for the Agent Host tests: paths, and a local fake router.

Helper, not a test module — same convention as ``tests/_module_gating.py`` and
``tests/_runtime_client.py``.

The fake router is a stdlib ``http.server`` bound to 127.0.0.1 on an ephemeral
port, started and stopped by the test that uses it. There is no live provider
in this suite and none is claimed: every router assertion is made against this
process.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTHOST_SCRIPTS = REPO_ROOT / "agenthost" / "scripts"
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
HOST_CLI = AGENTHOST_SCRIPTS / "host.py"

#: Obviously fake, and shaped so no secret scanner mistakes it for a real one.
PLACEHOLDER_CREDENTIAL = "PLACEHOLDER-NOT-A-REAL-CREDENTIAL"
CREDENTIAL_ENV = "RIGORLOOM_TEST_ROUTER_REF"


def agenthost_scripts_on_path() -> None:
    for directory in (AGENTHOST_SCRIPTS, RUNTIME_SCRIPTS):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))


class FakeRouter:
    """A deterministic local endpoint. Responses are scripted by the test.

    ``responder`` receives ``(path, parsed_body)`` and returns one of:

        {"status": 200, "json": {...}}          a JSON body
        {"status": 200, "sse": ["...", ...]}    server-sent event lines
        {"status": 500, "text": "..."}          a raw body with a status
        {"delaySeconds": 1.5, ...}              sleep first, to force a timeout
    """

    def __init__(self, responder):
        self.responder = responder
        self.requests: list[dict] = []
        self._server = None
        self._thread = None

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> "FakeRouter":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep pytest output clean
                pass

            def do_GET(self):  # noqa: N802 - stdlib naming
                self._serve(b"")

            def do_POST(self):  # noqa: N802 - stdlib naming
                length = int(self.headers.get("Content-Length") or 0)
                self._serve(self.rfile.read(length) if length else b"")

            def _serve(self, raw: bytes):
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    body = {"_unparsed": raw.decode("utf-8", errors="replace")}
                outer.requests.append({
                    "path": self.path,
                    "headers": {name: value for name, value in self.headers.items()},
                    "body": body,
                })
                try:
                    reply = outer.responder(self.path, body)
                except Exception as exc:  # pragma: no cover - test bug
                    reply = {"status": 599, "text": f"responder blew up: {exc}"}
                delay = reply.get("delaySeconds")
                if delay:
                    time.sleep(delay)
                status = reply.get("status", 200)
                if "sse" in reply:
                    payload = ("\n".join(reply["sse"]) + "\n\n").encode("utf-8")
                    content_type = "text/event-stream"
                elif "json" in reply:
                    payload = json.dumps(reply["json"],
                                         ensure_ascii=False).encode("utf-8")
                    content_type = "application/json"
                else:
                    payload = reply.get("text", "").encode("utf-8")
                    content_type = reply.get("contentType", "text/plain")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    for name, value in (reply.get("headers") or {}).items():
                        self.send_header(name, str(value))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    # The client gave up (a timeout test). Not a server fault.
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=30)

    def __enter__(self) -> "FakeRouter":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- convenience -------------------------------------------------------
    def last_authorization(self) -> str | None:
        if not self.requests:
            return None
        headers = self.requests[-1]["headers"]
        for name, value in headers.items():
            if name.lower() == "authorization":
                return value
        return None


def completion(content: str | None = None, tool_calls=None,
               finish_reason: str | None = None) -> dict:
    """An OpenAI-shaped chat completion body."""
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": call.get("id", f"call-{index}"), "type": "function",
             "function": {"name": call["name"],
                          "arguments": json.dumps(call.get("arguments", {}),
                                                  ensure_ascii=False)}}
            for index, call in enumerate(tool_calls)
        ]
    return {
        "id": "fake-completion",
        "model": "fake-model",
        "choices": [{"index": 0, "message": message,
                     "finish_reason": finish_reason
                     or ("tool_calls" if tool_calls else "stop")}],
    }


def sse_lines(pieces, tool_calls=None) -> list:
    """SSE data lines for a streamed completion, ending with [DONE]."""
    lines = []
    for piece in pieces:
        lines.append("data: " + json.dumps(
            {"choices": [{"index": 0, "delta": {"content": piece}}]},
            ensure_ascii=False))
    for index, call in enumerate(tool_calls or []):
        lines.append("data: " + json.dumps(
            {"choices": [{"index": 0, "delta": {"tool_calls": [
                {"id": call.get("id", f"call-{index}"), "type": "function",
                 "function": {"name": call["name"],
                              "arguments": json.dumps(call.get("arguments", {}),
                                                      ensure_ascii=False)}}]}}]},
            ensure_ascii=False))
    lines.append("data: [DONE]")
    return lines


# --- Anthropic Messages API shapes ------------------------------------------
#: Obviously fake. No `sk-ant-` prefix, so nothing mistakes it for a real key.
PLACEHOLDER_ANTHROPIC_KEY = "PLACEHOLDER-NOT-A-REAL-ANTHROPIC-KEY"
ANTHROPIC_ENV = "RIGORLOOM_TEST_ANTHROPIC_REF"


def anthropic_message(text: str | None = None, tool_calls=None,
                      stop_reason: str | None = None,
                      model: str = "claude-opus-5") -> dict:
    """A Messages API response body (verified shape: curl/examples.md)."""
    content: list[dict] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    for index, call in enumerate(tool_calls or []):
        content.append({
            "type": "tool_use",
            "id": call.get("id", f"toolu_{index}"),
            "name": call["name"],
            "input": call.get("input", {}),
        })
    return {
        "id": "msg_fake_0001",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason or ("tool_use" if tool_calls else "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }


def anthropic_error(error_type: str, message: str = "nope") -> dict:
    """The documented error envelope (shared/error-codes.md)."""
    return {"type": "error", "error": {"type": error_type, "message": message},
            "request_id": "req_fake_0001"}


def anthropic_sse(pieces=(), tool_call=None, stop_reason: str = "end_turn") -> str:
    """A full SSE body: message_start .. message_stop (curl/examples.md)."""
    frames: list[str] = []

    def frame(name: str, payload: dict) -> None:
        frames.append(f"event: {name}\ndata: "
                      + json.dumps(payload, ensure_ascii=False))

    frame("message_start", {"type": "message_start",
                            "message": {"id": "msg_fake_stream",
                                        "type": "message", "role": "assistant",
                                        "content": [], "usage": {}}})
    if pieces:
        frame("content_block_start",
              {"type": "content_block_start", "index": 0,
               "content_block": {"type": "text", "text": ""}})
        for piece in pieces:
            frame("content_block_delta",
                  {"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": piece}})
        frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    if tool_call is not None:
        index = 1 if pieces else 0
        frame("content_block_start",
              {"type": "content_block_start", "index": index,
               "content_block": {"type": "tool_use",
                                 "id": tool_call.get("id", "toolu_stream"),
                                 "name": tool_call["name"], "input": {}}})
        # the input arrives in fragments, as input_json_delta does on the wire
        blob = json.dumps(tool_call.get("input", {}), ensure_ascii=False)
        for start in range(0, len(blob), 5):
            frame("content_block_delta",
                  {"type": "content_block_delta", "index": index,
                   "delta": {"type": "input_json_delta",
                             "partial_json": blob[start:start + 5]}})
        frame("content_block_stop",
              {"type": "content_block_stop", "index": index})
    frame("message_delta", {"type": "message_delta",
                            "delta": {"stop_reason": stop_reason},
                            "usage": {"output_tokens": 9}})
    frame("message_stop", {"type": "message_stop"})
    return "\n\n".join(frames) + "\n\n"


def anthropic_config(base_url: str, **overrides) -> dict:
    config = {
        "providerId": "fake-anthropic",
        "baseUrl": base_url,
        "model": "claude-opus-5",
        "credential": {"source": "env", "key": ANTHROPIC_ENV,
                       "header": "x-api-key", "scheme": "raw"},
        "timeoutSeconds": 30,
    }
    config.update(overrides)
    return config


def router_config(base_url: str, **overrides) -> dict:
    config = {
        "providerId": "fake-router",
        "baseUrl": base_url,
        "model": "fake-model",
        "credential": {"source": "env", "key": CREDENTIAL_ENV},
        "capabilities": {"structuredToolUse": "yes"},
        "timeoutSeconds": 30,
    }
    config.update(overrides)
    return config
