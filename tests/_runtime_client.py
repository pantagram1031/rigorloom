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
