#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic MCP replay engine for CI (without a live model).

Re-sends a recorded or scripted sequence of MCP JSON-RPC 2.0 requests
(``initialize``, ``notifications/initialized``, ``tools/list``, ``tools/call``...)
to the MCP server (``rt_mcp.McpServer`` when merged, or a wire-compatible
in-process MCP 2025-06-18 adapter backed directly by ``rt_tools.call`` +
``rt_toolset`` + ``DraftStore`` + ``Roots`` + ``rt_commit``), then evaluates
all P7 safety and task machine checks.

In CI, runs against the fake document layer (``tests/_fake_rt_doc.py``) with
no engine and no model.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_ROOT.parent
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
ENGINE_SCRIPTS = REPO_ROOT / "engine" / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

for _p in (str(HARNESS_ROOT), str(RUNTIME_SCRIPTS), str(ENGINE_SCRIPTS), str(TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_checks  # noqa: E402
import agent_fixtures  # noqa: E402
import agent_safety  # noqa: E402
import cleanroom  # noqa: E402
import hwpx_write  # noqa: E402
import rt_jsonl  # noqa: E402
import rt_paths  # noqa: E402
import rt_tools  # noqa: E402
import rt_toolset  # noqa: E402
from rt_drafts import DraftStore  # noqa: E402

REPLAY_SCHEMA = "rigorloom-mcp-replay/v1"
REPLAYS_DIR = HARNESS_ROOT / "replays"


# --------------------------------------------------------------------------- #
# Fake document layer wrapper for engine-free CI replay (incl. T4 .hwpx)
# --------------------------------------------------------------------------- #
class FakeReplayDoc:
    """Wraps ``tests/_fake_rt_doc`` so CI replay exercises all 4 tasks cleanly.

    * All ``.fdoc`` operations delegate directly to ``_fake_rt_doc``.
    * ``convert(..., to="hwpx")`` writes a real OCF ``.hwpx`` via
      ``_fake_rt_doc.convert`` and records the converted ``.fdoc`` view keyed by
      the output file's sha256 so ``open``/``read``/``pages``/``check`` can
      inspect the converted ``.hwpx`` without ``rt_doc.py`` or the HWP engine.
    * Corrupted or altered ``.hwpx`` files fail ``HwpxPackage.read()`` cleanly.
    * ``approx_fonts`` optionally injects font-substitution metadata on
      converted ``.hwpx`` files so T4's ``approx`` reporting check is proven.
    """

    NATIVE_SUFFIX = ".fdoc"

    def __init__(self, fake_mod: Any, *, approx_fonts: list[dict[str, str]] | None = None):
        self._fake = fake_mod
        self._approx_fonts = list(approx_fonts or [])
        self._hwpx_shadow: dict[str, str] = {}  # sha256 -> .fdoc text

    def _shadow_fdoc(self, path: str, tmpdir: Path) -> tuple[Path | None, dict | None]:
        p = Path(path)
        if p.suffix.lower() != ".hwpx":
            return p, None
        if not p.is_file():
            return None, {"ok": False, "error": {"code": "not_found", "message": "파일이 없습니다", "retryable": False}}
        try:
            pkg = hwpx_write.HwpxPackage.read(p)
            pkg.validate()
        except Exception as exc:  # noqa: BLE001
            return None, {"ok": False, "error": {"code": "source_rejected", "message": f"잘못된 HWPX: {exc}", "retryable": False}}
        digest = agent_safety.sha256_file(p)
        fdoc_text = self._hwpx_shadow.get(digest)
        if fdoc_text is None:
            return None, {"ok": False, "error": {"code": "capability_unavailable", "message": "가짜 재생 계층에 등록되지 않은 .hwpx입니다", "retryable": False}}
        shadow = tmpdir / (p.stem + ".fdoc")
        shadow.write_text(fdoc_text, encoding="utf-8")
        return shadow, None

    def open(self, path: str) -> dict:  # noqa: A001
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.open(path)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            res = self._fake.open(str(shadow))
            if res.get("ok"):
                res = dict(res)
                res["format"] = "hwpx"
                res["rev"] = agent_safety.sha256_file(Path(path))[:12]
                res["fonts"] = {
                    "used": [f.get("want", "") for f in self._approx_fonts if f.get("want")],
                    "substituted": list(self._approx_fonts),
                }
            return res

    def outline(self, path: str) -> dict:
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.outline(path)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            return self._fake.outline(str(shadow))

    def read(self, path: str, at=None, *, with_runs: bool = False) -> dict:
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.read(path, at, with_runs=with_runs)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            return self._fake.read(str(shadow), at, with_runs=with_runs)

    def find(self, path: str, query: str, *, regex: bool = False, scope=None) -> dict:
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.find(path, query, regex=regex, scope=scope)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            return self._fake.find(str(shadow), query, regex=regex, scope=scope)

    def pages(self, path: str) -> dict:
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.pages(path)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            res = self._fake.pages(str(shadow))
            if res.get("ok") and self._approx_fonts:
                res = dict(res)
                res["approx"] = [
                    f"{f['want']}→{f['got']}" if f.get("got") else f["want"]
                    for f in self._approx_fonts if f.get("want")
                ]
            return res

    def render(self, path: str, pages=None, *, scale: float = 2.0, fmt: str = "png", out_dir=None) -> dict:
        return self._fake.render(path, pages, scale=scale, fmt=fmt, out_dir=out_dir)

    def edit(self, path: str, ops: list, *, base: str, out=None, in_place: bool = False, preview: bool = False) -> dict:
        return self._fake.edit(path, ops, base=base, out=out, in_place=in_place, preview=preview)

    def new(self, markdown_path_or_text, out, *, form=None) -> dict:
        return self._fake.new(markdown_path_or_text, out, form=form)

    def convert(self, src: str, out: str, *, to: str) -> dict:
        res = self._fake.convert(src, out, to=to)
        if res.get("ok") and to == "hwpx" and Path(src).suffix.lower() == ".fdoc":
            fdoc_text = Path(src).read_text(encoding="utf-8")
            self._hwpx_shadow[agent_safety.sha256_file(Path(out))] = fdoc_text
        return res

    def diff(self, a: str, b: str) -> dict:
        if Path(a).suffix.lower() != ".hwpx" and Path(b).suffix.lower() != ".hwpx":
            return self._fake.diff(a, b)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            sa, ea = self._shadow_fdoc(a, Path(td) / "a")
            if ea:
                return ea
            sb, eb = self._shadow_fdoc(b, Path(td) / "b")
            if eb:
                return eb
            return self._fake.diff(str(sa), str(sb))

    def style(self, path: str) -> dict:
        if Path(path).suffix.lower() != ".hwpx":
            return self._fake.style(path)
        with tempfile.TemporaryDirectory(prefix="rl-fake-shadow-") as td:
            shadow, err = self._shadow_fdoc(path, Path(td))
            if err:
                return err
            return self._fake.style(str(shadow))

    def guard(self, a: str, b: str) -> dict:
        return self._fake.guard(a, b)

    def engine_status(self) -> dict:
        return {"available": True, "engine": "fake-replay"}


# --------------------------------------------------------------------------- #
# In-process MCP 2025-06-18 adapter (fallback until P2's rt_mcp.py merges)
# --------------------------------------------------------------------------- #
class _RegistryMcpServer:
    """Minimal MCP v2 (2025-06-18) JSON-RPC 2.0 server over ``rt_tools``.

    Follows TASK-P2-MCP.md wire rules so replay sequences recorded against this
    adapter and against P2's ``rt_mcp.McpServer`` share identical JSON-RPC
    request/response frames.
    """

    def __init__(self, *, allow: list[Path], state_home: Path, doc_mod: Any):
        self.roots = rt_paths.Roots.of(allow)
        self.drafts = DraftStore(state_home)
        self.doc_mod = doc_mod
        self.initialized = False
        self.protocol_version = "2025-06-18"
        self.client_name = "replay"

    def _ctx(self) -> rt_tools.Context:
        return rt_tools.Context(
            client=f"mcp:{self.client_name}",
            roots=self.roots,
            source="draft",
            _doc=self.doc_mod,
            _drafts=self.drafts,
            ask=None,
        )

    def handle_frame(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            req_ver = params.get("protocolVersion")
            self.protocol_version = req_ver if req_ver in ("2025-06-18", "2025-03-26") else "2025-06-18"
            cinfo = params.get("clientInfo") or {}
            if isinstance(cinfo, dict) and cinfo.get("name"):
                self.client_name = str(cinfo["name"])
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "rigorloom", "title": "Rigorloom", "version": "0.18.0-replay"},
                    "instructions": "Workflow: open -> read/find -> edit/fill -> preview -> check -> save.",
                },
            }

        if method == "notifications/initialized":
            self.initialized = True
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if not self.initialized:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32002, "message": "server not initialized"},
            }

        if method == "tools/list":
            tools = []
            for t in rt_tools.surface("mcp"):
                entry: dict[str, Any] = {
                    "name": t.name,
                    "title": t.title,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    "annotations": t.annotations(),
                }
                if self.protocol_version == "2025-06-18":
                    entry["outputSchema"] = t.output_schema
                tools.append(entry)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name not in rt_tools.REGISTRY:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name!r}"},
                }
            env = rt_tools.call(self._ctx(), name, arguments)
            if env["ok"]:
                res_obj = env["result"]
                text = rt_tools.render_text(rt_tools.REGISTRY[name], res_obj)
                payload: dict[str, Any] = {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                }
                if self.protocol_version == "2025-06-18":
                    payload["structuredContent"] = res_obj
                return {"jsonrpc": "2.0", "id": req_id, "result": payload}
            err_obj = env["error"]
            lines = [str(err_obj.get("message") or err_obj.get("code") or "refused")]
            if err_obj.get("hint"):
                lines.append(str(err_obj["hint"]))
            if err_obj.get("candidates"):
                lines.append("candidates: " + ", ".join(map(str, err_obj["candidates"])))
            payload = {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": True,
            }
            if self.protocol_version == "2025-06-18":
                payload["structuredContent"] = {"error": err_obj}
            return {"jsonrpc": "2.0", "id": req_id, "result": payload}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method!r}"},
        }

    def serve(self, stdin: io.BufferedIOBase | io.RawIOBase,
              stdout: io.BufferedIOBase | io.RawIOBase) -> None:
        """Serve newline-delimited JSON-RPC 2.0 frames over byte streams."""
        while True:
            kind, raw = rt_jsonl.read_raw_frame(stdin)
            if kind == rt_jsonl.READ_EOF:
                break
            if kind != rt_jsonl.READ_LINE or raw is None:
                continue
            msg = rt_jsonl.decode_frame(raw)
            resp = self.handle_frame(msg)
            if resp is not None:
                stdout.write(rt_jsonl.dumps_frame(resp))
                stdout.flush()


def _try_real_mcp_server(allow: list[Path], cwd: Path):
    """Return P2's ``rt_mcp.McpServer`` class if present on this branch, else None."""
    try:
        import rt_mcp  # type: ignore  # noqa: PLC0415
        return getattr(rt_mcp, "McpServer", None)
    except ImportError:
        return None


def _load_doc_layer(doc_layer: str, *, approx_fonts: list[dict[str, str]] | None = None) -> Any:
    if doc_layer == "fake":
        import _fake_rt_doc as fake  # noqa: PLC0415
        return FakeReplayDoc(fake, approx_fonts=approx_fonts)
    if doc_layer == "real":
        import rt_doc  # type: ignore  # noqa: PLC0415
        return rt_doc
    raise ValueError(f"unknown doc_layer: {doc_layer!r}")


_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_.-]+)\}")


def _substitute(obj: Any, variables: dict[str, str]) -> Any:
    if isinstance(obj, str):
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            return variables.get(key, m.group(0))
        return _VAR_RE.sub(repl, obj)
    if isinstance(obj, list):
        return [_substitute(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, variables) for k, v in obj.items()}
    return obj


def load_replay_fixture(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != REPLAY_SCHEMA:
        raise ValueError(f"{path.name}: expected schema {REPLAY_SCHEMA!r}, got {data.get('schema')!r}")
    return data


def _find_task(task_id: str) -> dict[str, Any]:
    for t in cleanroom.load_agent_tasks():
        if t["id"] == task_id or t["short_id"] == task_id:
            return t
    raise ValueError(f"unknown agent eval task id: {task_id!r}")


def replay_fixture(
    fixture: dict[str, Any] | Path | str,
    *,
    task: dict[str, Any] | None = None,
    doc_layer: str = "fake",
    run_dir: Path | None = None,
    enforce_caps: bool = True,
    round_id: int | str = 0,
    agent_label: str = "scripted",
    run_index: int = 1,
) -> dict[str, Any]:
    """Replay a recorded/scripted MCP JSON-RPC sequence and evaluate checks + safety."""
    if isinstance(fixture, (str, Path)):
        fixture_data = load_replay_fixture(fixture)
    else:
        fixture_data = dict(fixture)

    task_obj = task if task is not None else _find_task(fixture_data["task_id"])
    task_id = task_obj["id"]
    fixture_mode = "fake" if doc_layer == "fake" else "hwpx"

    temp_ctx = None
    if run_dir is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix=f"rl-replay-{task_obj['short_id']}-")
        base_dir = Path(temp_ctx.name)
    else:
        base_dir = Path(run_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

    try:
        task_dir = base_dir / "task"
        meta_dir = base_dir / "meta"
        state_dir = meta_dir / "state"
        task_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        mat = agent_fixtures.materialize_fixture(task_id, task_dir, mode=fixture_mode)
        source_path = Path(mat["source"]) if mat.get("source") else None
        output_name = mat["output_name"]
        output_path = task_dir / output_name

        source_hashes = {f["path"]: f["sha256"] for f in mat["files"]}
        pre_existing = agent_safety.snapshot_task_files(task_dir)
        before_snap = agent_safety.snapshot_tree(
            [base_dir], ignore_dirs=[task_dir, meta_dir, state_dir]
        )

        approx_fonts = fixture_data.get("approx_fonts") or []
        doc_mod = _load_doc_layer(doc_layer, approx_fonts=approx_fonts)

        # Allow .fdoc in rt_toolset when using the fake doc layer.
        orig_in, orig_out = rt_toolset.FORMATS_IN, rt_toolset.FORMATS_OUT
        if doc_layer == "fake":
            if "fdoc" not in rt_toolset.FORMATS_IN:
                rt_toolset.FORMATS_IN = rt_toolset.FORMATS_IN + ("fdoc",)
            if "fdoc" not in rt_toolset.FORMATS_OUT:
                rt_toolset.FORMATS_OUT = rt_toolset.FORMATS_OUT + ("fdoc",)

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()
        tool_cap = int(task_obj["caps"]["tool_calls"])
        wall_cap = float(task_obj["caps"]["wall_s"])
        aborted = False
        abort_reason: str | None = None

        variables: dict[str, str] = {
            "TASK_DIR": str(task_dir),
            "SOURCE": str(source_path) if source_path else "",
            "OUTPUT": str(output_path),
            "OUTSIDE_DIR": str(base_dir),
        }

        mcp_server = _RegistryMcpServer(
            allow=[task_dir], state_home=state_dir, doc_mod=doc_mod
        )
        replay_log: list[dict[str, Any]] = []
        transcript_events: list[dict[str, Any]] = []
        actual_call_outcomes: list[dict[str, Any]] = []
        tool_calls = 0
        seq = 0

        try:
            for req_template in fixture_data.get("requests") or []:
                req = _substitute(req_template, variables)
                if req.get("method") == "tools/call":
                    if enforce_caps and tool_calls >= tool_cap:
                        aborted = True
                        abort_reason = "tool_call_cap"
                        break
                    if enforce_caps and (time.monotonic() - t0) > wall_cap:
                        aborted = True
                        abort_reason = "wall_time_cap"
                        break
                    tool_calls += 1

                # Round-trip through rt_jsonl framing to verify wire serialization.
                wire_in = rt_jsonl.dumps_frame(req)
                decoded_req = rt_jsonl.decode_frame(wire_in[:-1])
                seq += 1
                replay_log.append({"seq": seq, "dir": "c2s", "msg": decoded_req})

                resp = mcp_server.handle_frame(decoded_req)
                if resp is not None:
                    wire_out = rt_jsonl.dumps_frame(resp)
                    decoded_resp = rt_jsonl.decode_frame(wire_out[:-1])
                    seq += 1
                    replay_log.append({"seq": seq, "dir": "s2c", "msg": decoded_resp})

                    if decoded_req.get("method") == "tools/call":
                        params = decoded_req.get("params") or {}
                        tname = str(params.get("name") or "")
                        res = decoded_resp.get("result") if isinstance(decoded_resp.get("result"), dict) else {}
                        rpc_err = decoded_resp.get("error")
                        sc = res.get("structuredContent") if isinstance(res.get("structuredContent"), dict) else {}
                        err_obj = sc.get("error") if isinstance(sc.get("error"), dict) else None
                        is_err = bool(res.get("isError", False)) or rpc_err is not None
                        err_code = (
                            err_obj.get("code") if err_obj
                            else (f"jsonrpc:{rpc_err.get('code')}" if isinstance(rpc_err, dict) else None)
                        )
                        rid = decoded_req.get("id")
                        if not is_err and isinstance(sc, dict):
                            if sc.get("rev"):
                                variables["REV"] = str(sc["rev"])
                                variables[f"STEP.{rid}.rev"] = str(sc["rev"])
                            if isinstance(sc.get("path"), str) and sc["path"].startswith("draft:"):
                                variables["DRAFT"] = sc["path"]
                                variables[f"STEP.{rid}.path"] = sc["path"]

                        text_blocks = [
                            b.get("text", "") for b in (res.get("content") or [])
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        transcript_events.append({
                            "id": rid,
                            "tool": tname,
                            "args": params.get("arguments") or {},
                            "is_error": is_err,
                            "ok": not is_err,
                            "error_code": err_code,
                            "result_text": "\n".join(text_blocks),
                            "structured": sc,
                        })
                        actual_call_outcomes.append({
                            "id": rid,
                            "tool": tname,
                            "isError": is_err,
                            "error_code": err_code,
                        })
        finally:
            rt_toolset.FORMATS_IN, rt_toolset.FORMATS_OUT = orig_in, orig_out

        # Optional post-replay hook (used only by negative safety tests/fixtures if declared).
        wall_s = round(time.monotonic() - t0, 4)
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        final_answer = _substitute(str(fixture_data.get("final_answer") or ""), variables)
        after_snap = agent_safety.snapshot_tree(
            [base_dir], ignore_dirs=[task_dir, meta_dir, state_dir]
        )
        safety = agent_safety.run_safety_checks(
            task_dir=task_dir,
            source_hashes=source_hashes,
            pre_existing_hashes=pre_existing,
            before_snapshot=before_snap,
            after_snapshot=after_snap,
            transcript_events=transcript_events,
            final_answer=final_answer,
            allowed_dirs=[meta_dir, state_dir],
        )

        # Evaluate task pass rules through the same doc_layer.
        orig_in2, orig_out2 = rt_toolset.FORMATS_IN, rt_toolset.FORMATS_OUT
        if doc_layer == "fake":
            if "fdoc" not in rt_toolset.FORMATS_IN:
                rt_toolset.FORMATS_IN = rt_toolset.FORMATS_IN + ("fdoc",)
            if "fdoc" not in rt_toolset.FORMATS_OUT:
                rt_toolset.FORMATS_OUT = rt_toolset.FORMATS_OUT + ("fdoc",)
        try:
            checks = agent_checks.evaluate_task_checks(
                task_obj,
                doc_mod,
                task_dir=task_dir,
                source_path=source_path,
                output_path=output_path if output_path.is_file() else None,
                final_answer=final_answer,
                transcript_events=transcript_events,
            )
        finally:
            rt_toolset.FORMATS_IN, rt_toolset.FORMATS_OUT = orig_in2, orig_out2

        passed = bool(
            (not aborted)
            and safety["ok"]
            and (checks["ok"] is True)
        )

        expected_outcomes = fixture_data.get("expected_call_outcomes")
        replay_outcomes_match = (
            actual_call_outcomes == expected_outcomes
            if expected_outcomes is not None else True
        )

        mcp_replay_file = meta_dir / "mcp_replay.jsonl"
        mcp_replay_file.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in replay_log) + "\n",
            encoding="utf-8",
        )
        transcript_file = meta_dir / "transcript.jsonl"
        transcript_file.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in transcript_events) + "\n",
            encoding="utf-8",
        )

        tokens_obj = fixture_data.get("simulated_tokens") or {
            "input": None, "output": None, "total": None,
        }
        run_id = f"r{round_id}-{agent_label}-{task_obj['short_id']}-{run_index:02d}"
        run_record: dict[str, Any] = {
            "schema": "rigorloom-eval-run/v1",
            "run_id": run_id,
            "task_id": task_id,
            "round": round_id,
            "agent": agent_label,
            "model": fixture_data.get("model"),
            "tier": {
                "label": agent_label,
                "model": fixture_data.get("model") or "scripted-replay",
                "harness": "mcp-replay",
            },
            "launcher": {
                "kind": "other",
                "detail": "scripted-replay",
                "skill_loaded": False,
            },
            "started_at": started_at,
            "finished_at": finished_at,
            "caps": dict(task_obj["caps"]),
            "outcome": {
                "completed": not aborted,
                "operator_intervened": False,
                "refused": any(e["is_error"] for e in transcript_events),
            },
            "transcript": {
                "steps": len(transcript_events),
                "tool_calls": tool_calls,
                "retries": sum(1 for e in transcript_events if e["is_error"]),
                "wall_seconds": wall_s,
                "tokens": tokens_obj,
            },
            "tool_calls": tool_calls,
            "tokens": tokens_obj,
            "wall_s": wall_s,
            "aborted": aborted,
            "abort_reason": abort_reason,
            "safety": safety,
            "checks": checks,
            "passed": passed,
            "transcript_file": str(transcript_file) if run_dir is not None else None,
            "mcp_replay_file": str(mcp_replay_file) if run_dir is not None else None,
            "final_answer": final_answer,
            "artifacts": (
                [{"path": output_name, "role": "output",
                  "sha256": agent_safety.sha256_file(output_path)}]
                if output_path.is_file() else []
            ),
            "failure_mode": None if passed else (
                abort_reason
                or (f"safety:{','.join(safety['violations'])}" if not safety["ok"] else None)
                or ",".join(c["id"] for c in checks["checks"] if c["status"] != "pass")
                or "failed"
            ),
        }

        if run_dir is not None:
            (meta_dir / "run.json").write_text(
                json.dumps(run_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (meta_dir / "checks.json").write_text(
                json.dumps(checks, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        return {
            "ok": True,
            "task_id": task_id,
            "passed": passed,
            "expected_passed": fixture_data.get("expected_passed"),
            "replay_outcomes_match": replay_outcomes_match,
            "actual_call_outcomes": actual_call_outcomes,
            "expected_call_outcomes": expected_outcomes,
            "safety": safety,
            "checks": checks,
            "run_record": run_record,
        }
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


def replay_raw_stream(
    requests: list[dict[str, Any]],
    *,
    allow: list[Path],
    cwd: Path,
    state_home: Path,
    doc_mod: Any,
    prefer_real_mcp: bool = True,
) -> list[dict[str, Any]]:
    """Send raw JSON-RPC 2.0 request frames through stdio byte streams.

    Uses P2's ``rt_mcp.McpServer`` when merged and ``prefer_real_mcp`` is True,
    falling back seamlessly to :class:`_RegistryMcpServer` on this branch.
    """
    stdin = io.BytesIO(b"".join(rt_jsonl.dumps_frame(req) for req in requests))
    stdout = io.BytesIO()
    real_cls = _try_real_mcp_server(allow, cwd) if prefer_real_mcp else None
    if real_cls is not None:
        old_home = os.environ.get("RIGORLOOM_HOME")
        os.environ["RIGORLOOM_HOME"] = str(state_home)
        try:
            srv = real_cls(stdin, stdout, allow=[str(p) for p in allow], cwd=str(cwd))
            srv.serve()
        finally:
            if old_home is None:
                os.environ.pop("RIGORLOOM_HOME", None)
            else:
                os.environ["RIGORLOOM_HOME"] = old_home
    else:
        srv = _RegistryMcpServer(allow=allow, state_home=state_home, doc_mod=doc_mod)
        srv.serve(stdin, stdout)
    stdout.seek(0)
    out: list[dict[str, Any]] = []
    while True:
        kind, raw = rt_jsonl.read_raw_frame(stdout)
        if kind != rt_jsonl.READ_LINE or raw is None:
            break
        out.append(rt_jsonl.decode_frame(raw))
    return out
