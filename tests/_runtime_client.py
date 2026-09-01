# -*- coding: utf-8 -*-
"""Test client for the Runtime's JSONL/stdio server.

Helper, not a test module — same convention as ``tests/_module_gating.py``.

WHY THE RUNTIME TESTS LIVE IN ``tests/`` AND NOT ``runtime/tests/``:
``pyproject.toml``'s ``testpaths`` is ``tests``, ``pipeline/tests``,
``engine/tests``, ``modules/*/tests``. A ``runtime/tests`` directory would not
be collected, and adding it to ``testpaths`` means editing ``pyproject.toml``,
which this slice does not own. One location, and it is the collected one.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVE = REPO_ROOT / "runtime" / "scripts" / "serve.py"
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
CORPUS_FORM = (REPO_ROOT / "tests" / "corpus" / "forms" / "converted"
               / "gianmun-byeolji-1ho.hwpx")

#: Generous by design. tests/test_subprocess_bounds.py measured a cold repo-script
#: spawn at a loaded median of 9.00s and a worst observed 36.46s; the Runtime
#: then spawns form_inspect/preedit children of its own inside one call.
CLIENT_TIMEOUT = 180.0


def runtime_scripts_on_path() -> None:
    """Import the runtime modules the way the server does (repo script idiom)."""
    if str(RUNTIME_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(RUNTIME_SCRIPTS))


class RuntimeClient:
    """One server process; frames in, frames out, stderr kept apart."""

    def __init__(self, root: Path, *, entry: str = "host",
                 engine_root: Path | None = None):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.stderr_path = root / f"runtime-{entry}.stderr.log"
        self._stderr = self.stderr_path.open("wb")
        argv = [sys.executable, str(SERVE), "--entry", entry, "--root", str(root)]
        if engine_root is not None:
            argv += ["--engine-root", str(engine_root)]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._stderr, env=env)
        self._lines: "queue.Queue[bytes | None]" = queue.Queue()
        self._raw: list[bytes] = []
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._next_id = 0

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                self._raw.append(line)
                self._lines.put(line)
        finally:
            self._lines.put(None)

    # -- raw ---------------------------------------------------------------
    def write_raw(self, payload: bytes) -> None:
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

    def send_frame(self, frame: dict) -> None:
        self.write_raw((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))

    def recv(self, timeout: float = CLIENT_TIMEOUT) -> dict:
        line = self._lines.get(timeout=timeout)
        if line is None:
            raise AssertionError(
                "the server closed stdout before answering; stderr:\n"
                + self.stderr_text())
        return json.loads(line.decode("utf-8"))

    def stdout_lines(self) -> list[bytes]:
        return list(self._raw)

    def stderr_text(self) -> str:
        try:
            self._stderr.flush()
        except ValueError:
            pass
        try:
            return self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # -- convenience -------------------------------------------------------
    def call(self, method: str, params: dict | None = None, *,
             request_id: str | None = None, timeout: float = CLIENT_TIMEOUT) -> dict:
        self._next_id += 1
        frame_id = request_id or f"r{self._next_id}"
        frame: dict = {"kind": "request", "id": frame_id, "method": method}
        if params is not None:
            frame["params"] = params
        self.send_frame(frame)
        return self.recv(timeout=timeout)

    def initialize(self, *, version: str = "0", policy: str = "reject") -> dict:
        return self.call("initialize", {
            "protocolVersion": version,
            "client": {"name": "runtime-test", "version": "0"},
            "unknownFieldPolicy": policy,
        })

    def ok(self, method: str, params: dict | None = None, **kwargs) -> dict:
        frame = self.call(method, params, **kwargs)
        assert frame.get("kind") == "response", (
            f"{method} failed: {json.dumps(frame, ensure_ascii=False)}\n"
            f"stderr:\n{self.stderr_text()}")
        return frame["result"]

    def err(self, method: str, params: dict | None = None, **kwargs) -> dict:
        frame = self.call(method, params, **kwargs)
        assert frame.get("kind") == "error", (
            f"{method} unexpectedly succeeded: "
            f"{json.dumps(frame, ensure_ascii=False)}")
        return frame["error"]

    # -- lifecycle ---------------------------------------------------------
    def close_stdin(self) -> None:
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass

    def wait(self, timeout: float = CLIENT_TIMEOUT) -> int:
        return self.proc.wait(timeout=timeout)

    def close(self) -> None:
        self.close_stdin()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=30)
        try:
            self._stderr.close()
        except (OSError, ValueError):
            pass

    def __enter__(self) -> "RuntimeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def opened_session(client: RuntimeClient, source: Path) -> str:
    client.initialize()
    return client.ok("workspace/openPath", {"path": str(source)})["sessionId"]


# --- Phase 2: the CLI and the MCP adapter ----------------------------------

CLI = REPO_ROOT / "runtime" / "scripts" / "cli.py"
MCP = REPO_ROOT / "runtime" / "scripts" / "mcp_server.py"


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class CliResult:
    __slots__ = ("code", "payload", "stdout", "stderr")

    def __init__(self, code, payload, stdout, stderr):
        self.code = code
        self.payload = payload
        self.stdout = stdout
        self.stderr = stderr

    @property
    def result(self) -> dict:
        assert self.payload.get("ok") is True, (
            f"cli failed ({self.code}): {self.stdout}\nstderr:\n{self.stderr}")
        return self.payload["result"]

    @property
    def error(self) -> dict:
        assert self.payload.get("ok") is False, (
            f"cli unexpectedly succeeded: {self.stdout}")
        return self.payload["error"]


def run_cli(root: Path, *argv: str, engine_root: Path | None = None) -> CliResult:
    """One CLI invocation; parses its single JSON document."""
    command = [sys.executable, str(CLI), "--root", str(root)]
    if engine_root is not None:
        command += ["--engine-root", str(engine_root)]
    command += [str(item) for item in argv]
    completed = subprocess.run(command, capture_output=True, env=_env(),
                               timeout=CLIENT_TIMEOUT)
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = {}
    return CliResult(completed.returncode, payload, stdout, stderr)


class McpClient:
    """Newline-delimited JSON-RPC 2.0 over the adapter's stdio."""

    def __init__(self, root: Path, *, engine_root: Path | None = None):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.stderr_path = root / "mcp.stderr.log"
        self._stderr = self.stderr_path.open("wb")
        argv = [sys.executable, str(MCP), "--root", str(root)]
        if engine_root is not None:
            argv += ["--engine-root", str(engine_root)]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=self._stderr, env=_env())
        self._lines: "queue.Queue[bytes | None]" = queue.Queue()
        self._raw: list[bytes] = []
        threading.Thread(target=self._pump, daemon=True).start()
        self._next_id = 0

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                self._raw.append(line)
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def write_raw(self, payload: bytes) -> None:
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

    def send(self, message: dict) -> None:
        self.write_raw((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

    def recv(self, timeout: float = CLIENT_TIMEOUT) -> dict:
        line = self._lines.get(timeout=timeout)
        if line is None:
            raise AssertionError("the MCP adapter closed stdout; stderr:\n"
                                 + self.stderr_text())
        return json.loads(line.decode("utf-8"))

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.recv()

    def notify(self, method: str, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def initialize(self, version: str = "2025-06-18") -> dict:
        response = self.request("initialize", {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "runtime-test", "version": "0"},
        })
        self.notify("notifications/initialized")
        return response

    def tools(self) -> list[dict]:
        return self.request("tools/list")["result"]["tools"]

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        return self.request("tools/call",
                            {"name": tool, "arguments": arguments or {}})

    def call_payload(self, tool: str, arguments: dict | None = None) -> dict:
        """The decoded tool payload: {"ok": bool, "result"|"error": ...}."""
        response = self.call(tool, arguments)
        assert "result" in response, response
        content = response["result"]["content"]
        assert content and content[0]["type"] == "text", content
        payload = json.loads(content[0]["text"])
        payload["_isError"] = response["result"]["isError"]
        return payload

    def ok(self, tool: str, arguments: dict | None = None) -> dict:
        payload = self.call_payload(tool, arguments)
        assert payload["ok"] is True, payload
        assert payload["_isError"] is False
        return payload["result"]

    def err(self, tool: str, arguments: dict | None = None) -> dict:
        payload = self.call_payload(tool, arguments)
        assert payload["ok"] is False, payload
        assert payload["_isError"] is True
        return payload["error"]

    def stdout_lines(self) -> list[bytes]:
        return list(self._raw)

    def stderr_text(self) -> str:
        try:
            self._stderr.flush()
        except ValueError:
            pass
        try:
            return self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=30)
        try:
            self._stderr.close()
        except (OSError, ValueError):
            pass

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
