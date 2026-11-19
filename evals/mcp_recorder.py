#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transparent stdio MCP JSON-RPC 2.0 proxy and recorder.

Sits between an MCP client (Claude Code or Codex) and ``rigorloom mcp --allow DIR``,
forwarding every newline-delimited JSON-RPC frame verbatim on stdin/stdout while
recording ``c2s`` (client -> server) and ``s2c`` (server -> client) frames into
a JSONL file for deterministic CI replay (ruling-1.md §4).

Usage::

    python evals/mcp_recorder.py --record /path/mcp_replay.jsonl -- \
        python runtime/scripts/cli.py mcp --allow /path/task
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _write_record(handle, lock: threading.Lock, seq: list[int],
                  direction: str, raw_line: bytes) -> None:
    text = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
    if not text:
        return
    try:
        msg: Any = json.loads(text)
    except json.JSONDecodeError:
        msg = {"_raw": text}
    with lock:
        seq[0] += 1
        entry = {
            "seq": seq[0],
            "dir": direction,
            "ts": round(time.time(), 6),
            "msg": msg,
        }
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def _pump(src, dst, record_handle, lock: threading.Lock, seq: list[int],
          direction: str) -> None:
    try:
        while True:
            line = src.readline()
            if not line:
                break
            _write_record(record_handle, lock, seq, direction, line)
            dst.write(line)
            dst.flush()
    except (OSError, BrokenPipeError, ValueError):
        pass
    finally:
        try:
            dst.close()
        except OSError:
            pass


def run_proxy(record_path: Path, server_cmd: list[str],
              *, stdin=None, stdout=None, stderr=None) -> int:
    """Spawn ``server_cmd`` and forward stdio while logging JSON-RPC frames."""
    record_path = Path(record_path)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    err_stream = stderr if stderr is not None else sys.stderr.buffer

    proc = subprocess.Popen(
        server_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err_stream,
    )
    assert proc.stdin is not None and proc.stdout is not None
    lock = threading.Lock()
    seq = [0]
    with open(record_path, "w", encoding="utf-8") as rec:
        t_in = threading.Thread(
            target=_pump,
            args=(in_stream, proc.stdin, rec, lock, seq, "c2s"),
            daemon=True,
        )
        t_out = threading.Thread(
            target=_pump,
            args=(proc.stdout, out_stream, rec, lock, seq, "s2c"),
            daemon=True,
        )
        t_in.start()
        t_out.start()
        code = proc.wait()
        t_out.join(timeout=5.0)
        t_in.join(timeout=1.0)
    return code


def extract_replay_fixture(
    record_path: Path,
    *,
    task_id: str,
    task_dir: Path | str,
    final_answer: str = "",
    expected_passed: bool | None = None,
) -> dict[str, Any]:
    """Turn a recorded ``mcp_replay.jsonl`` into a portable CI replay fixture.

    Replaces the concrete ``task_dir`` path with ``${TASK_DIR}`` (zero absolute
    paths, privacy-gate safe) and abstracts random ``draft:new-<hex>`` tokens
    into ``${DRAFT}`` so the recorded sequence replays cleanly in any temp dir.
    """
    tdir = str(Path(os.path.realpath(str(task_dir))))
    tdir_posix = tdir.replace("\\", "/")
    draft_map: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for line in Path(record_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

    # First discover any draft:<id> tokens emitted by server responses.
    for row in records:
        if row.get("dir") != "s2c":
            continue
        msg = row.get("msg")
        if not isinstance(msg, dict):
            continue
        res = msg.get("result")
        if isinstance(res, dict):
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                path_val = sc.get("path")
                if isinstance(path_val, str) and path_val.startswith("draft:") and path_val not in draft_map:
                    draft_map[path_val] = "${DRAFT}"

    def scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            out = obj.replace(tdir, "${TASK_DIR}").replace(tdir_posix, "${TASK_DIR}")
            for real_draft, token in draft_map.items():
                out = out.replace(real_draft, token)
            return out
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        return obj

    requests: list[dict[str, Any]] = []
    responses_by_id: dict[Any, dict[str, Any]] = {}
    for row in records:
        msg = row.get("msg")
        if not isinstance(msg, dict):
            continue
        if row.get("dir") == "c2s":
            requests.append(scrub(msg))
        elif row.get("dir") == "s2c" and "id" in msg:
            responses_by_id[msg["id"]] = scrub(msg)

    expected_outcomes: list[dict[str, Any]] = []
    for req in requests:
        if req.get("method") == "tools/call":
            rid = req.get("id")
            resp = responses_by_id.get(rid) or {}
            res = resp.get("result") if isinstance(resp.get("result"), dict) else {}
            sc = res.get("structuredContent") if isinstance(res.get("structuredContent"), dict) else {}
            err = sc.get("error") if isinstance(sc.get("error"), dict) else None
            expected_outcomes.append({
                "id": rid,
                "tool": (req.get("params") or {}).get("name"),
                "isError": bool(res.get("isError", False)),
                "error_code": err.get("code") if err else None,
            })

    return {
        "schema": "rigorloom-mcp-replay/v1",
        "task_id": task_id,
        "requests": requests,
        "expected_call_outcomes": expected_outcomes,
        "final_answer": scrub(final_answer),
        "expected_passed": expected_passed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Transparent stdio MCP JSON-RPC 2.0 proxy and recorder."
    )
    parser.add_argument("--record", required=True, help="Output JSONL path")
    parser.add_argument("cmd", nargs=argparse.REMAINDER,
                        help="Server command after '--'")
    args = parser.parse_args(argv)
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("mcp_recorder: server command required after '--'", file=sys.stderr)
        return 2
    return run_proxy(Path(args.record), cmd)


if __name__ == "__main__":
    sys.exit(main())
