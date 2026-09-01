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

            def do_POST(self):  # noqa: N802 - stdlib naming
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
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
