#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent launchers for the P7 evaluation loop: Claude Code, Codex, and scripted replay.

Each run executes inside a fresh task directory with an isolated ``RIGORLOOM_HOME``
state directory, enforces the task's tool-call cap (10/12/20/8) and wall-time
cap (10 minutes; abort = fail), records the agent transcript and MCP JSON-RPC
exchange, runs all four safety checks and all task pass-rule checks, and writes
``run.json`` conforming to ``evals/run_record.schema.json``.

Model and account selection are always caller-supplied CLI arguments — this
module never hard-codes an account or credential.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_ROOT.parent
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"

for _p in (str(HARNESS_ROOT), str(RUNTIME_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_checks  # noqa: E402
import agent_fixtures  # noqa: E402
import agent_replay  # noqa: E402
import agent_safety  # noqa: E402
import score  # noqa: E402

DEFAULT_RIGORLOOM_CMD = [sys.executable, str(RUNTIME_SCRIPTS / "cli.py")]


@dataclass
class AgentConfig:
    """Caller-supplied launcher configuration. Never hard-codes an account."""

    agent: str                                  # "claude" | "codex" | "scripted"
    binary: str | None = None                   # override claude/codex binary
    model: str | None = None                    # CLI --model / -m
    account_dir: str | None = None              # CLAUDE_CONFIG_DIR or CODEX_HOME
    profile: str | None = None                  # Codex -p profile
    rigorloom_cmd: list[str] = field(default_factory=lambda: list(DEFAULT_RIGORLOOM_CMD))
    record_mcp: bool = True                     # proxy through evals/mcp_recorder.py
    hwp_engine: str | None = None               # RIGORLOOM_HWP_ENGINE
    extra_args: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# MCP server command & client config builders
# --------------------------------------------------------------------------- #
def build_mcp_server_command(
    task_dir: Path,
    state_dir: Path,
    *,
    rigorloom_cmd: list[str] | None = None,
    mcp_replay_file: Path | None = None,
    hwp_engine: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Build ``rigorloom mcp --allow <task_dir>`` command + isolated env."""
    base = list(rigorloom_cmd or DEFAULT_RIGORLOOM_CMD)
    server_cmd = [*base, "mcp", "--allow", str(task_dir)]
    if mcp_replay_file is not None:
        server_cmd = [
            sys.executable,
            str(HARNESS_ROOT / "mcp_recorder.py"),
            "--record", str(mcp_replay_file),
            "--",
            *server_cmd,
        ]
    env: dict[str, str] = {
        "RIGORLOOM_HOME": str(state_dir),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    engine = hwp_engine if hwp_engine is not None else os.environ.get("RIGORLOOM_HWP_ENGINE")
    if engine:
        env["RIGORLOOM_HWP_ENGINE"] = str(engine)
    return server_cmd, env


def write_claude_mcp_config(
    config_path: Path,
    server_cmd: list[str],
    server_env: dict[str, str],
) -> Path:
    """Write a Claude Code ``--mcp-config`` JSON file for the Rigorloom server."""
    payload = {
        "mcpServers": {
            "rigorloom": {
                "command": server_cmd[0],
                "args": server_cmd[1:],
                "env": dict(server_env),
            }
        }
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def build_claude_command(
    prompt: str,
    mcp_config_path: Path,
    config: AgentConfig,
) -> tuple[list[str], dict[str, str]]:
    """Construct the ``claude -p`` invocation and child environment."""
    binary = config.binary or "claude"
    cmd = [
        binary,
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--mcp-config", str(mcp_config_path),
        "--strict-mcp-config",
        "--allowedTools", "mcp__rigorloom__*",
        "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
    ]
    if config.model:
        cmd += ["--model", config.model]
    if config.extra_args:
        cmd += list(config.extra_args)

    env = dict(os.environ)
    if config.account_dir:
        env["CLAUDE_CONFIG_DIR"] = str(config.account_dir)
    return cmd, env


def build_codex_command(
    prompt: str,
    task_dir: Path,
    server_cmd: list[str],
    server_env: dict[str, str],
    last_message_path: Path,
    config: AgentConfig,
) -> tuple[list[str], dict[str, str]]:
    """Construct the ``codex exec`` invocation and child environment."""
    binary = config.binary or "codex"
    cmd = [
        binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C", str(task_dir),
        "-s", "read-only",
        "-c", f"mcp_servers.rigorloom.command={json.dumps(server_cmd[0])}",
        "-c", f"mcp_servers.rigorloom.args={json.dumps(server_cmd[1:])}",
    ]
    for k, v in sorted(server_env.items()):
        cmd += ["-c", f"mcp_servers.rigorloom.env.{k}={json.dumps(str(v))}"]
    cmd += ["-o", str(last_message_path)]
    if config.model:
        cmd += ["-m", config.model]
    if config.profile:
        cmd += ["-p", config.profile]
    if config.extra_args:
        cmd += list(config.extra_args)
    cmd.append(prompt)

    env = dict(os.environ)
    if config.account_dir:
        env["CODEX_HOME"] = str(config.account_dir)
    return cmd, env


# --------------------------------------------------------------------------- #
# Transcript parsers (Claude stream-json + Codex exec --json)
# --------------------------------------------------------------------------- #
_REFUSAL_CODE_RE = re.compile(
    r"\b(needs_person|declined_by_person|outside_roots|no_roots|person_only_seat|"
    r"stale|source_changed|target_exists|target_changed|locked|no_draft|"
    r"capability_unavailable|unsupported_format|invalid_params|not_found|"
    r"ambiguous_match|expect_mismatch|bad_address|conflict|engine_refused|"
    r"source_rejected|engine_unavailable|page_out_of_range|internal)\b"
)


def _extract_structured(raw_content: Any) -> tuple[str, dict[str, Any]]:
    """Extract text and optional JSON structured payload from a tool_result body."""
    if isinstance(raw_content, dict):
        if isinstance(raw_content.get("structuredContent"), dict):
            text_parts = [
                b.get("text", "") for b in (raw_content.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return "\n".join(text_parts), raw_content["structuredContent"]
        return json.dumps(raw_content, ensure_ascii=False), raw_content
    if isinstance(raw_content, list):
        texts: list[str] = []
        structured: dict[str, Any] = {}
        for part in raw_content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(part.get("structuredContent"), dict):
                    structured = part["structuredContent"]
            elif isinstance(part, str):
                texts.append(part)
        joined = "\n".join(texts)
        if not structured and joined.strip().startswith("{"):
            try:
                parsed = json.loads(joined)
                if isinstance(parsed, dict):
                    structured = parsed
            except json.JSONDecodeError:
                pass
        return joined, structured
    text = str(raw_content or "")
    structured = {}
    if text.strip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                structured = parsed
        except json.JSONDecodeError:
            pass
    return text, structured


def _infer_error_code(text: str, structured: dict[str, Any], is_error: bool) -> str | None:
    err = structured.get("error") if isinstance(structured, dict) else None
    if isinstance(err, dict) and err.get("code"):
        return str(err["code"])
    if is_error:
        m = _REFUSAL_CODE_RE.search(text)
        return m.group(1) if m else "error"
    return None


def _count_claude_line_tool_calls(obj: dict[str, Any]) -> int:
    if obj.get("type") != "assistant":
        return 0
    msg = obj.get("message") or {}
    content = msg.get("content") or []
    return sum(
        1 for blk in content
        if isinstance(blk, dict) and blk.get("type") == "tool_use"
    )


def _count_codex_line_tool_calls(obj: dict[str, Any]) -> int:
    etype = obj.get("type")
    if etype in ("item.started", "item.completed"):
        item = obj.get("item") or {}
        if item.get("type") in ("mcp_tool_call", "command_execution", "tool_call"):
            # Count on item.started if present, or item.completed if no started was emitted.
            return 1 if etype == "item.started" else 0
    if etype == "tool_call":
        return 1
    return 0


def parse_claude_stream_json(lines: list[str]) -> dict[str, Any]:
    """Parse Claude Code ``--output-format stream-json`` JSONL output."""
    steps = 0
    tool_calls = 0
    by_use_id: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    assistant_texts: list[str] = []
    final_answer = ""
    usage_totals: dict[str, int] = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    has_usage = False
    result_usage: dict[str, Any] | None = None
    result_is_error = False

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        etype = obj.get("type")

        if etype == "assistant":
            steps += 1
            msg = obj.get("message") or {}
            u = msg.get("usage")
            if isinstance(u, dict):
                has_usage = True
                usage_totals["input"] += int(u.get("input_tokens") or 0)
                usage_totals["output"] += int(u.get("output_tokens") or 0)
                usage_totals["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
                usage_totals["cache_creation"] += int(u.get("cache_creation_input_tokens") or 0)
            for blk in msg.get("content") or []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text" and isinstance(blk.get("text"), str):
                    assistant_texts.append(blk["text"])
                elif blk.get("type") == "tool_use":
                    tool_calls += 1
                    uid = str(blk.get("id") or f"call-{tool_calls}")
                    ev = {
                        "id": uid,
                        "tool": str(blk.get("name") or ""),
                        "args": blk.get("input") or {},
                        "is_error": False,
                        "ok": True,
                        "error_code": None,
                        "result_text": "",
                        "structured": {},
                    }
                    by_use_id[uid] = ev
                    events.append(ev)

        elif etype == "user":
            msg = obj.get("message") or {}
            for blk in msg.get("content") or []:
                if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                    continue
                uid = str(blk.get("tool_use_id") or "")
                is_err = bool(blk.get("is_error", False))
                text, structured = _extract_structured(blk.get("content"))
                if isinstance(structured.get("error"), dict):
                    is_err = True
                code = _infer_error_code(text, structured, is_err)
                ev = by_use_id.get(uid)
                if ev is not None:
                    ev["is_error"] = is_err
                    ev["ok"] = not is_err
                    ev["error_code"] = code
                    ev["result_text"] = text
                    ev["structured"] = structured
                else:
                    events.append({
                        "id": uid or f"res-{len(events) + 1}",
                        "tool": "",
                        "args": {},
                        "is_error": is_err,
                        "ok": not is_err,
                        "error_code": code,
                        "result_text": text,
                        "structured": structured,
                    })

        elif etype == "result":
            if isinstance(obj.get("result"), str):
                final_answer = obj["result"]
            if obj.get("is_error"):
                result_is_error = True
            if isinstance(obj.get("usage"), dict):
                result_usage = obj["usage"]
            if isinstance(obj.get("num_turns"), int) and steps == 0:
                steps = obj["num_turns"]

    if not final_answer and assistant_texts:
        final_answer = assistant_texts[-1]

    if result_usage is not None:
        inp = int(result_usage.get("input_tokens") or 0)
        out = int(result_usage.get("output_tokens") or 0)
        cr = int(result_usage.get("cache_read_input_tokens") or 0)
        cc = int(result_usage.get("cache_creation_input_tokens") or 0)
        tokens: dict[str, int | None] | None = {
            "input": inp,
            "output": out,
            "cache_read": cr,
            "cache_creation": cc,
            "total": inp + out + cr + cc,
        }
    elif has_usage:
        tokens = {
            **usage_totals,
            "total": sum(usage_totals.values()),
        }
    else:
        tokens = None

    return {
        "steps": steps,
        "tool_calls": tool_calls,
        "retries": sum(1 for e in events if e["is_error"]),
        "tokens": tokens,
        "final_answer": final_answer,
        "transcript_events": events,
        "result_is_error": result_is_error,
    }


def parse_codex_jsonl(lines: list[str], *, last_message_text: str = "") -> dict[str, Any]:
    """Parse Codex ``codex exec --json`` JSONL output."""
    steps = 0
    tool_calls = 0
    by_item_id: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    messages: list[str] = []
    usage_totals = {"input": 0, "output": 0, "cache_read": 0}
    has_usage = False
    result_is_error = False

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        etype = obj.get("type")

        if etype == "turn.completed":
            steps += 1
            u = obj.get("usage")
            if isinstance(u, dict):
                has_usage = True
                usage_totals["input"] += int(u.get("input_tokens") or 0)
                usage_totals["output"] += int(u.get("output_tokens") or 0)
                usage_totals["cache_read"] += int(u.get("cached_input_tokens") or 0)
        elif etype in ("turn.failed", "error"):
            result_is_error = True
        elif etype in ("item.started", "item.completed"):
            item = obj.get("item") or {}
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            iid = str(item.get("id") or f"item-{len(events) + 1}")
            if itype == "agent_message" and etype == "item.completed":
                txt = item.get("text")
                if isinstance(txt, str) and txt.strip():
                    messages.append(txt)
            elif itype in ("mcp_tool_call", "command_execution", "tool_call"):
                tname = str(item.get("tool") or item.get("name") or itype)
                ev = by_item_id.get(iid)
                if ev is None:
                    tool_calls += 1
                    ev = {
                        "id": iid,
                        "tool": tname,
                        "args": item.get("arguments") or item.get("command") or {},
                        "is_error": False,
                        "ok": True,
                        "error_code": None,
                        "result_text": "",
                        "structured": {},
                    }
                    by_item_id[iid] = ev
                    events.append(ev)
                if etype == "item.completed":
                    err_field = item.get("error")
                    status = str(item.get("status") or "")
                    res_field = item.get("result")
                    text, structured = _extract_structured(res_field)
                    is_err = bool(
                        err_field
                        or status in ("failed", "error")
                        or (isinstance(res_field, dict) and res_field.get("isError"))
                        or (isinstance(structured, dict) and isinstance(structured.get("error"), dict))
                    )
                    if err_field and not text:
                        text = str(err_field.get("message") if isinstance(err_field, dict) else err_field)
                    code = _infer_error_code(text, structured, is_err)
                    ev["is_error"] = is_err
                    ev["ok"] = not is_err
                    ev["error_code"] = code
                    ev["result_text"] = text
                    ev["structured"] = structured

    final_answer = last_message_text.strip() or (messages[-1] if messages else "")
    tokens: dict[str, int | None] | None = (
        {
            "input": usage_totals["input"],
            "output": usage_totals["output"],
            "cache_read": usage_totals["cache_read"],
            "total": usage_totals["input"] + usage_totals["output"],
        }
        if has_usage else None
    )
    return {
        "steps": steps or (1 if (messages or events) else 0),
        "tool_calls": tool_calls,
        "retries": sum(1 for e in events if e["is_error"]),
        "tokens": tokens,
        "final_answer": final_answer,
        "transcript_events": events,
        "result_is_error": result_is_error,
    }


def merge_mcp_replay_events(
    transcript_events: list[dict[str, Any]],
    mcp_replay_file: Path,
) -> list[dict[str, Any]]:
    """Enrich launcher events with exact ``structuredContent`` from ``mcp_replay.jsonl``."""
    if not mcp_replay_file.is_file():
        return transcript_events
    mcp_calls: list[dict[str, Any]] = []
    req_by_id: dict[Any, dict[str, Any]] = {}
    for line in mcp_replay_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = row.get("msg")
        if not isinstance(msg, dict):
            continue
        if row.get("dir") == "c2s" and msg.get("method") == "tools/call":
            req_by_id[msg.get("id")] = msg
        elif row.get("dir") == "s2c" and msg.get("id") in req_by_id:
            req = req_by_id.pop(msg.get("id"))
            params = req.get("params") or {}
            res = msg.get("result") if isinstance(msg.get("result"), dict) else {}
            rpc_err = msg.get("error")
            sc = res.get("structuredContent") if isinstance(res.get("structuredContent"), dict) else {}
            err_obj = sc.get("error") if isinstance(sc.get("error"), dict) else None
            is_err = bool(res.get("isError", False)) or rpc_err is not None
            err_code = (
                err_obj.get("code") if err_obj
                else (f"jsonrpc:{rpc_err.get('code')}" if isinstance(rpc_err, dict) else None)
            )
            text_blocks = [
                b.get("text", "") for b in (res.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            mcp_calls.append({
                "id": req.get("id"),
                "tool": str(params.get("name") or ""),
                "args": params.get("arguments") or {},
                "is_error": is_err,
                "ok": not is_err,
                "error_code": err_code,
                "result_text": "\n".join(text_blocks),
                "structured": sc,
            })
    return mcp_calls if mcp_calls else transcript_events


# --------------------------------------------------------------------------- #
# Streaming subprocess runner with live cap enforcement
# --------------------------------------------------------------------------- #
def _terminate_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=3.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


def run_streaming_process(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    transcript_path: Path,
    stderr_path: Path,
    tool_call_cap: int,
    wall_s_cap: float,
    line_tool_counter,
) -> dict[str, Any]:
    """Run ``cmd`` capturing JSONL stdout live and aborting immediately on cap breach."""
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None and proc.stderr is not None

    q: queue.Queue[str | None] = queue.Queue()
    stderr_chunks: list[str] = []

    def _read_stdout() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                q.put(line)
        finally:
            q.put(None)

    def _read_stderr() -> None:
        try:
            stderr_chunks.append(proc.stderr.read())  # type: ignore[union-attr]
        except OSError:
            pass

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    lines: list[str] = []
    live_tool_calls = 0
    aborted = False
    abort_reason: str | None = None
    t0 = time.monotonic()
    deadline = t0 + wall_s_cap

    with open(transcript_path, "w", encoding="utf-8") as tf:
        eof = False
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                aborted = True
                abort_reason = "wall_time_cap"
                _terminate_proc(proc)
                break
            try:
                item = q.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if proc.poll() is not None and not t_out.is_alive():
                    break
                continue
            if item is None:
                eof = True
                break
            lines.append(item)
            tf.write(item)
            tf.flush()
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                live_tool_calls += int(line_tool_counter(parsed))
                if live_tool_calls > tool_call_cap:
                    aborted = True
                    abort_reason = "tool_call_cap"
                    _terminate_proc(proc)
                    break

    if not aborted:
        try:
            proc.wait(timeout=max(0.5, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            aborted = True
            abort_reason = "wall_time_cap"
            _terminate_proc(proc)

    t_out.join(timeout=2.0)
    t_err.join(timeout=2.0)
    wall_s = round(time.monotonic() - t0, 4)
    stderr_path.write_text("".join(stderr_chunks), encoding="utf-8")

    return {
        "returncode": proc.returncode,
        "lines": lines,
        "wall_s": wall_s,
        "aborted": aborted,
        "abort_reason": abort_reason,
    }


# --------------------------------------------------------------------------- #
# Single-run orchestrator
# --------------------------------------------------------------------------- #
def _render_prompt(task: dict[str, Any], task_dir: Path, files: list[dict[str, Any]]) -> str:
    listing = "\n".join(f"- {f['name']} ({f['path']})" for f in files)
    return (
        f"{task['prompt'].strip()}\n\n"
        f"[작업 폴더]\n{task_dir}\n\n"
        f"[입력 파일]\n{listing}\n"
    )


def _engine_available(config: AgentConfig) -> bool:
    engine = config.hwp_engine if config.hwp_engine is not None else os.environ.get("RIGORLOOM_HWP_ENGINE")
    if not engine:
        return False
    return (Path(engine) / "kit_api.py").is_file()


def run_single(
    task: dict[str, Any],
    config: AgentConfig,
    run_dir: Path,
    *,
    round_id: int | str = 0,
    run_index: int = 1,
    scripted_fixture: Path | dict[str, Any] | None = None,
    watch_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Execute one agent run in a fresh task dir and write ``run.json``."""
    task_id = task["id"]
    run_dir = Path(run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = run_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Scripted replay path (used for CI and dry runs without a live model).
    if config.agent == "scripted" or scripted_fixture is not None:
        if scripted_fixture is None:
            scripted_fixture = agent_replay.REPLAYS_DIR / f"{task_id}.perfect.json"
        res = agent_replay.replay_fixture(
            scripted_fixture,
            task=task,
            doc_layer="fake",
            run_dir=run_dir,
            enforce_caps=True,
            round_id=round_id,
            agent_label=config.agent,
            run_index=run_index,
        )
        score.validate_run_record(res["run_record"])
        return res["run_record"]

    # Engine-only task skips cleanly when RIGORLOOM_HWP_ENGINE is absent.
    if task.get("engine_only") and not _engine_available(config):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        skip_reason = "engine_only: requires RIGORLOOM_HWP_ENGINE"
        skipped_checks = [
            {
                "id": r["id"],
                "rule": r["rule"],
                "status": "skipped",
                "ok": None,
                "detail": skip_reason,
            }
            for r in task.get("pass_rules") or []
        ]
        checks_payload = {
            "schema": agent_checks.CHECKS_SCHEMA,
            "task_id": task_id,
            "counts": {
                "pass": 0, "fail": 0, "skipped": len(skipped_checks),
                "unavailable": 0, "total": len(skipped_checks),
            },
            "ok": None,
            "checks": skipped_checks,
        }
        run_id = f"r{round_id}-{config.agent}-{task['short_id']}-{run_index:02d}"
        record: dict[str, Any] = {
            "schema": "rigorloom-eval-run/v1",
            "run_id": run_id,
            "task_id": task_id,
            "round": round_id,
            "agent": config.agent,
            "model": config.model,
            "tier": {"label": config.agent, "model": config.model or "default", "harness": config.agent},
            "launcher": {"kind": "cli", "detail": config.agent, "skill_loaded": False},
            "started_at": now,
            "finished_at": now,
            "caps": dict(task["caps"]),
            "outcome": {"completed": False, "operator_intervened": False},
            "transcript": {"steps": 0, "tool_calls": 0, "retries": 0, "wall_seconds": 0.0, "tokens": None},
            "tool_calls": 0,
            "tokens": None,
            "wall_s": 0.0,
            "aborted": False,
            "abort_reason": None,
            "skipped": True,
            "skip_reason": skip_reason,
            "safety": {"ok": True, "violations": [], "checks": {}},
            "checks": checks_payload,
            "passed": None,
            "transcript_file": None,
            "mcp_replay_file": None,
            "final_answer": "",
            "artifacts": [],
            "failure_mode": None,
            "notes": skip_reason,
        }
        score.validate_run_record(record)
        (meta_dir / "checks.json").write_text(
            json.dumps(checks_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (meta_dir / "run.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return record

    # Live Claude Code or Codex run in a fresh task dir.
    task_dir = run_dir / "task"
    state_dir = meta_dir / "state"
    task_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    mat = agent_fixtures.materialize_fixture(task_id, task_dir, mode="hwpx")
    source_path = Path(mat["source"]) if mat.get("source") else None
    output_name = mat["output_name"]
    output_path = task_dir / output_name

    prompt_text = _render_prompt(task, task_dir, mat["files"])
    (meta_dir / "PROMPT.txt").write_text(prompt_text, encoding="utf-8")

    source_hashes = {f["path"]: f["sha256"] for f in mat["files"]}
    pre_existing = agent_safety.snapshot_task_files(task_dir)
    watched = list(watch_roots) if watch_roots else [run_dir]
    before_snap = agent_safety.snapshot_tree(
        watched, ignore_dirs=[task_dir, meta_dir, state_dir]
    )

    mcp_replay_file = (meta_dir / "mcp_replay.jsonl") if config.record_mcp else None
    server_cmd, server_env = build_mcp_server_command(
        task_dir, state_dir,
        rigorloom_cmd=config.rigorloom_cmd,
        mcp_replay_file=mcp_replay_file,
        hwp_engine=config.hwp_engine,
    )

    transcript_path = meta_dir / "transcript.jsonl"
    stderr_path = meta_dir / "stderr.log"
    last_msg_path = meta_dir / "last_message.txt"

    if config.agent == "claude":
        mcp_cfg = write_claude_mcp_config(meta_dir / "mcp-config.json", server_cmd, server_env)
        cmd, child_env = build_claude_command(prompt_text, mcp_cfg, config)
        counter = _count_claude_line_tool_calls
    elif config.agent == "codex":
        cmd, child_env = build_codex_command(
            prompt_text, task_dir, server_cmd, server_env, last_msg_path, config
        )
        counter = _count_codex_line_tool_calls
    else:
        raise ValueError(f"unsupported agent launcher: {config.agent!r}")

    tool_cap = int(task["caps"]["tool_calls"])
    wall_cap = float(task["caps"]["wall_s"])
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    proc_info = run_streaming_process(
        cmd,
        cwd=task_dir,
        env=child_env,
        transcript_path=transcript_path,
        stderr_path=stderr_path,
        tool_call_cap=tool_cap,
        wall_s_cap=wall_cap,
        line_tool_counter=counter,
    )
    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if config.agent == "claude":
        parsed = parse_claude_stream_json(proc_info["lines"])
    else:
        last_txt = last_msg_path.read_text(encoding="utf-8") if last_msg_path.is_file() else ""
        parsed = parse_codex_jsonl(proc_info["lines"], last_message_text=last_txt)

    events = (
        merge_mcp_replay_events(parsed["transcript_events"], mcp_replay_file)
        if mcp_replay_file is not None else parsed["transcript_events"]
    )
    tool_calls = max(int(parsed["tool_calls"]), len(events))
    aborted = bool(proc_info["aborted"])
    abort_reason = proc_info["abort_reason"]
    if not aborted and tool_calls > tool_cap:
        aborted = True
        abort_reason = "tool_call_cap"
    if not aborted and proc_info["wall_s"] > wall_cap:
        aborted = True
        abort_reason = "wall_time_cap"

    after_snap = agent_safety.snapshot_tree(
        watched, ignore_dirs=[task_dir, meta_dir, state_dir]
    )
    safety = agent_safety.run_safety_checks(
        task_dir=task_dir,
        source_hashes=source_hashes,
        pre_existing_hashes=pre_existing,
        before_snapshot=before_snap,
        after_snapshot=after_snap,
        transcript_events=events,
        final_answer=parsed["final_answer"],
        allowed_dirs=[meta_dir, state_dir],
    )

    doc_mod = agent_replay._load_doc_layer("real")
    checks = agent_checks.evaluate_task_checks(
        task,
        doc_mod,
        task_dir=task_dir,
        source_path=source_path,
        output_path=output_path if output_path.is_file() else None,
        final_answer=parsed["final_answer"],
        transcript_events=events,
    )

    completed = (not aborted) and (proc_info["returncode"] == 0) and (not parsed["result_is_error"])
    passed = bool(completed and safety["ok"] and (checks["ok"] is True))
    run_id = f"r{round_id}-{config.agent}-{task['short_id']}-{run_index:02d}"

    record = {
        "schema": "rigorloom-eval-run/v1",
        "run_id": run_id,
        "task_id": task_id,
        "round": round_id,
        "agent": config.agent,
        "model": config.model,
        "tier": {"label": config.agent, "model": config.model or "default", "harness": config.agent},
        "launcher": {"kind": "cli", "detail": config.agent, "skill_loaded": False},
        "started_at": started_at,
        "finished_at": finished_at,
        "caps": dict(task["caps"]),
        "outcome": {
            "completed": completed,
            "operator_intervened": False,
            "refused": any(e.get("is_error") for e in events),
        },
        "transcript": {
            "steps": parsed["steps"],
            "tool_calls": tool_calls,
            "retries": parsed["retries"],
            "wall_seconds": proc_info["wall_s"],
            "tokens": parsed["tokens"],
        },
        "tool_calls": tool_calls,
        "tokens": parsed["tokens"],
        "wall_s": proc_info["wall_s"],
        "aborted": aborted,
        "abort_reason": abort_reason,
        "safety": safety,
        "checks": checks,
        "passed": passed,
        "transcript_file": str(transcript_path),
        "mcp_replay_file": str(mcp_replay_file) if mcp_replay_file else None,
        "final_answer": parsed["final_answer"],
        "artifacts": (
            [{"path": output_name, "role": "output",
              "sha256": agent_safety.sha256_file(output_path)}]
            if output_path.is_file() else []
        ),
        "failure_mode": None if passed else (
            abort_reason
            or (f"safety:{','.join(safety['violations'])}" if not safety["ok"] else None)
            or (f"exit:{proc_info['returncode']}" if proc_info["returncode"] != 0 else None)
            or ",".join(c["id"] for c in checks["checks"] if c["status"] != "pass")
            or "failed"
        ),
    }
    score.validate_run_record(record)
    (meta_dir / "checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (meta_dir / "run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record
