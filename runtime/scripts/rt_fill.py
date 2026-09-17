#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace/fillRun: drive engine/scripts/fill_report.py --loop.

No new document semantics. The Runtime validates a report workspace, spawns
the same ``fill_report.py --loop`` argv the Stage 5 playbook / AURALAB
assembly command uses, tails ``output/fill_events.jsonl`` into Runtime
``fill/progress`` events, and returns the loop's verdict verbatim plus hashed
output paths. Hancom absence is ``needs_hancom``. One run per workspace
(lock file). Cancellable by killing the direct child.

The GUI must not treat a contact sheet as rendering proof beyond
``proof_grade``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import Cancelled  # noqa: E402
from rt_codes import (  # noqa: E402
    FILL_TIMEOUT_SECONDS,
    MAX_INLINE_IMAGE_BYTES,
    RpcError,
)
from rt_engine import child_env, child_python  # noqa: E402
from rt_pipeline import (  # noqa: E402
    fill_inputs,
    find_workspace,
    pipeline_status,
)
from rt_session import append_event, sha256_file  # noqa: E402

FILL_POLL_SECONDS = 0.15
VERIFY_FORMAT_TIMEOUT_SECONDS = 120.0


def _require_absolute_path(raw, *, name: str = "workspace") -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    path = Path(raw)
    if not path.is_absolute():
        raise RpcError(
            "invalid_params",
            f"{name} must be absolute; the Runtime has no ambient cwd",
        )
    try:
        return path.expanduser()
    except OSError as exc:
        raise RpcError("invalid_params", f"{name} is not usable: {exc}") from exc


def _workspace_dir(raw) -> Path:
    start = _require_absolute_path(raw, name="workspace")
    found = find_workspace(start)
    if found is None:
        raise RpcError(
            "artifact_missing",
            "no PIPELINE.md within four ancestors of this path; "
            "not a report workspace",
            path=str(start),
            missing=["PIPELINE.md"],
        )
    return found


def _lock_path(root: Path, workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:32]
    directory = Path(root) / "fill-runs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.lock"


@contextmanager
def workspace_fill_lock(root: Path, workspace: Path):
    """One fill-run at a time per workspace. Cross-process, never unlinked."""
    path = _lock_path(root, workspace)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RpcError(
                "fill_in_progress",
                "this workspace already has a fill-run in flight; retry later",
                workspacePath=str(workspace),
            ) from exc
        try:
            yield path
        finally:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        handle.close()


def _tail_events(path: Path, offset: int) -> tuple[int, list[dict]]:
    if not path.is_file():
        return offset, []
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return offset, []
    if not data:
        return offset, []
    if data.endswith(b"\n"):
        consumed = data
    elif b"\n" in data:
        consumed = data.rsplit(b"\n", 1)[0] + b"\n"
    else:
        return offset, []
    rows: list[dict] = []
    for line in consumed.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped.decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return offset + len(consumed), rows


def _layout_qa_summary(checks) -> dict:
    if not isinstance(checks, dict):
        return {"pass": None, "flagged": [], "counts": {}}
    flagged = []
    counts: dict[str, int] = {}
    for name, value in checks.items():
        n = len(value) if isinstance(value, list) else int(bool(value))
        counts[str(name)] = n
        if n:
            flagged.append(str(name))
    return {"pass": not flagged, "flagged": flagged, "counts": counts}


def progress_from_fill_event(event: dict) -> dict:
    """Runtime ``fill/progress`` detail: iteration, state, layout QA, proof grade."""
    verdict = event.get("verdict") if isinstance(event.get("verdict"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    checks = verdict.get("checks") if isinstance(verdict.get("checks"), dict) else {}
    proof = verdict.get("proof_grade") or result.get("proof_grade")
    state = (
        verdict.get("state")
        or result.get("status")
        or event.get("phase")
    )
    iteration = event.get("iter")
    if iteration is None:
        iteration = event.get("proof_iter")
    if iteration is None:
        iteration = verdict.get("iter")
    return {
        "iteration": iteration,
        "state": state,
        "phase": event.get("phase") or "fill",
        "proofGrade": proof,
        "layoutQa": _layout_qa_summary(checks),
        "pageCount": verdict.get("page_count"),
    }


def _terminal_state(verdict: dict) -> str:
    status = str(verdict.get("status") or "").strip().lower()
    if status == "escalate_human":
        return "escalate_human"
    state = str(verdict.get("state") or "").strip().lower()
    if state:
        return state
    if verdict.get("converged"):
        return "converged"
    return "gappy"


def _layout_qa_row(verdict: dict) -> dict:
    checks = verdict.get("checks") if isinstance(verdict.get("checks"), dict) else None
    if checks is None:
        return {
            "checker": "layout_qa",
            "state": "unavailable",
            "ok": None,
            "reason": "fill_report verdict did not include layout QA checks",
        }
    findings: list[dict] = []
    for name, value in checks.items():
        if not value:
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("code", str(name))
                    findings.append(row)
                else:
                    findings.append({"code": str(name), "msg": str(item)})
        else:
            findings.append({"code": str(name), "msg": str(value)})
    return {
        "checker": "layout_qa",
        "state": "ran",
        "ok": not findings,
        "hard": findings,
        "warn": [],
        "counts": {"hard": len(findings), "warn": 0},
        "checks": checks,
    }


def _verify_format_row(payload: dict | None, reason: str | None = None) -> dict:
    if payload is None:
        return {
            "checker": "verify_format",
            "state": "unavailable",
            "ok": None,
            "reason": reason or "verify_format did not run",
        }
    hard = payload.get("hard") if isinstance(payload.get("hard"), list) else []
    warn = payload.get("warn") if isinstance(payload.get("warn"), list) else []
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        counts = {"hard": len(hard), "warn": len(warn)}
    return {
        "checker": "verify_format",
        "state": "ran",
        "ok": payload.get("ok"),
        "hard": hard,
        "warn": warn,
        "counts": counts,
        "verdict": payload.get("verdict"),
        "measured": payload.get("measured"),
        "expected": payload.get("expected"),
    }


def _artifact(role: str, path: Path) -> dict | None:
    if not path.is_file():
        return None
    digest, size = sha256_file(path)
    return {"role": role, "path": str(path), "sha256": digest, "bytes": size}


def _contact_sheet(path: Path) -> dict | None:
    if not path.is_file():
        return None
    digest, size = sha256_file(path)
    row: dict = {
        "path": str(path),
        "sha256": digest,
        "bytes": size,
        "mediaType": "image/png",
        "data": None,
    }
    if size <= MAX_INLINE_IMAGE_BYTES:
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        if raw:
            row["data"] = base64.standard_b64encode(raw).decode("ascii")
    return row


def _contact_paths(verdict: dict, extra: list | None = None) -> list[Path]:
    seen: list[Path] = []
    names: set[str] = set()
    values = []
    if extra:
        values.extend(extra)
    raw = verdict.get("contact_sheets")
    if isinstance(raw, list):
        values.extend(raw)
    for item in values:
        text = item if isinstance(item, str) else None
        if text is None and isinstance(item, dict):
            for key in ("path", "png", "file"):
                if isinstance(item.get(key), str):
                    text = item[key]
                    break
        if not text:
            continue
        path = Path(text)
        key = str(path)
        if key in names:
            continue
        names.add(key)
        seen.append(path)
    return seen


def _parse_json_object(text: str) -> dict | None:
    if not text or not text.strip():
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        start = text.rfind("{")
        if start < 0:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
        except ValueError:
            return None
    return obj if isinstance(obj, dict) else None


def _load_verdict(out_dir: Path, stdout: str) -> dict:
    path = out_dir / "verdict_v06.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, UnicodeError, ValueError):
            pass
    parsed = _parse_json_object(stdout)
    if parsed is not None and "error" not in parsed:
        return parsed
    if parsed is not None and parsed.get("ok") is False:
        raise RpcError(
            "backend_refused",
            str(parsed.get("error") or "fill_report refused"),
            tool="fill_report",
            detail=parsed,
        )
    raise RpcError(
        "backend_refused",
        "fill_report produced no verdict JSON",
        tool="fill_report",
        stdout=stdout[-4000:],
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _spawn_fill(argv: list[str], cwd: Path) -> subprocess.Popen:
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=child_env(),
        )
    except (OSError, ValueError) as exc:
        raise RpcError(
            "capability_unavailable",
            "could not start fill_report.py",
            detail=str(exc),
        ) from exc


def _drain_pipe(pipe, sink: list[bytes], cap: int) -> None:
    total = 0
    try:
        while True:
            chunk = pipe.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total <= cap:
                sink.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _run_verify_format(tools, workspace: Path, out_hwpx: Path) -> dict:
    script = Path(tools.root) / "pipeline" / "scripts" / "verify_format.py"
    if not script.is_file():
        return _verify_format_row(
            None, "pipeline/scripts/verify_format.py is not in this install")
    if not out_hwpx.is_file():
        return _verify_format_row(None, "output/out.hwpx is missing")
    out_json = workspace / "output" / "verify_format.json"
    argv = [child_python(), str(script), str(workspace), "--out", str(out_json)]
    from rt_engine import run_child  # noqa: PLC0415

    result = run_child(argv, cwd=workspace, timeout=VERIFY_FORMAT_TIMEOUT_SECONDS)
    payload = None
    if out_json.is_file():
        try:
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, UnicodeError, ValueError):
            payload = None
    if payload is None:
        payload = _parse_json_object(result.text)
    if payload is None:
        reason = "verify_format produced no JSON"
        if result.timed_out:
            reason = "verify_format exceeded its time bound"
        return _verify_format_row(None, reason)
    return _verify_format_row(payload)


def _fill_script(tools) -> Path:
    override = (os.environ.get("RIGORLOOM_FILL_REPORT") or "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise RpcError(
                "capability_unavailable",
                "RIGORLOOM_FILL_REPORT does not name a fill_report.py",
                path=override,
            )
        return path
    tools._require("fill_report", tools.fill_report)
    return Path(tools.fill_report)


def _fill_argv(tools, workspace: Path, inputs: dict, *,
               spacing_skip_pages=None, max_proof_iters=None) -> list[str]:
    script = _fill_script(tools)
    out_dir = workspace / "output"
    argv = [
        child_python(), str(script),
        "--loop",
        "--form", inputs["formPath"],
        "--content", inputs["contentPath"],
        "--out-dir", str(out_dir),
        "--build-yaml", inputs["buildYamlPath"],
        "--form-profile", inputs["formProfilePath"],
        "--proof",
    ]
    if inputs.get("baselinePath"):
        argv += ["--baseline", inputs["baselinePath"]]
    if spacing_skip_pages:
        argv += ["--spacing-skip-pages", str(spacing_skip_pages)]
    iters = 3 if max_proof_iters is None else max_proof_iters
    argv += ["--max-proof-iters", str(int(iters))]
    return argv


def _assert_hancom() -> None:
    from rt_convert import (  # noqa: PLC0415
        hancom_facts,
        hancom_is_busy,
        running_hancom_processes,
    )

    forced = (os.environ.get("RIGORLOOM_FILL_HANCOM") or "").strip().lower()
    if forced in ("yes", "1", "true"):
        return
    if forced in ("no", "0", "false"):
        raise RpcError(
            "needs_hancom",
            "this machine cannot run fill_report --loop: "
            "RIGORLOOM_FILL_HANCOM=no",
            hancom={"state": "no", "reason": "forced by RIGORLOOM_FILL_HANCOM",
                    "progid": None, "pyhwpx": False},
        )

    hancom = hancom_facts()
    if hancom.get("state") != "yes":
        raise RpcError(
            "needs_hancom",
            "this machine cannot run fill_report --loop: "
            + (hancom.get("reason") or "Hancom is not available"),
            hancom=hancom,
        )
    busy = running_hancom_processes()
    if hancom_is_busy(busy):
        raise RpcError(
            "com_busy",
            "a Hancom instance is already running on this machine; "
            "close it and try again — the Runtime will not "
            "terminate somebody else's session",
            processes=busy.get("processes") or [],
            state=busy.get("state"),
            reason=busy.get("reason"),
        )


def workspace_fill_run(core, workspace, *, session_id=None,
                       spacing_skip_pages=None, max_proof_iters=None,
                       checkpoint=None, timeout: float | None = None) -> dict:
    """HOST ONLY. Spawn fill_report --loop; tail events; return the verdict."""
    ws = _workspace_dir(workspace)
    header = pipeline_status(str(ws), engine_root=core.tools.root)
    if not header.get("found"):
        raise RpcError(
            "artifact_missing",
            "PIPELINE.md was not found as a report workspace header",
            workspacePath=str(ws),
            missing=["PIPELINE.md"],
        )
    inputs = header.get("fillInputs") or fill_inputs(ws)
    if not inputs.get("complete"):
        raise RpcError(
            "artifact_missing",
            "this report workspace is missing files fill_report --loop needs",
            workspacePath=str(ws),
            missing=list(inputs.get("missing") or []),
            fillInputs=inputs,
        )

    session = None
    if session_id is not None:
        session = core.store.get(session_id)

    if max_proof_iters is not None:
        if not isinstance(max_proof_iters, int) or isinstance(max_proof_iters, bool):
            raise RpcError("invalid_params", "maxProofIters must be an integer")
        if max_proof_iters < 1:
            raise RpcError("invalid_params", "maxProofIters must be >= 1")
    if spacing_skip_pages is not None and not isinstance(spacing_skip_pages, str):
        raise RpcError("invalid_params", "spacingSkipPages must be a string")

    _assert_hancom()
    argv = _fill_argv(
        core.tools, ws, inputs,
        spacing_skip_pages=spacing_skip_pages,
        max_proof_iters=max_proof_iters,
    )
    out_dir = ws / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "fill_events.jsonl"
    bound = FILL_TIMEOUT_SECONDS if timeout is None else float(timeout)

    with workspace_fill_lock(core.store.root, ws):
        if events_path.is_file():
            try:
                events_path.write_text("", encoding="utf-8")
            except OSError:
                pass
        proc = _spawn_fill(argv, cwd=core.tools.root)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        from rt_codes import MAX_CHILD_OUTPUT_BYTES  # noqa: PLC0415

        threads = [
            threading.Thread(
                target=_drain_pipe,
                args=(proc.stdout, stdout_chunks, MAX_CHILD_OUTPUT_BYTES),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_pipe,
                args=(proc.stderr, stderr_chunks, MAX_CHILD_OUTPUT_BYTES),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()

        offset = 0
        sheets_seen: list[str] = []
        started = time.monotonic()
        timed_out = False
        try:
            while True:
                if checkpoint is not None:
                    checkpoint()
                offset, rows = _tail_events(events_path, offset)
                for event in rows:
                    detail = progress_from_fill_event(event)
                    result = event.get("result")
                    if isinstance(result, dict):
                        raw_sheets = result.get("contact_sheets")
                        if isinstance(raw_sheets, list):
                            for item in raw_sheets:
                                if isinstance(item, str):
                                    sheets_seen.append(item)
                    if session is not None:
                        append_event(session, "fill/progress", **detail)
                if proc.poll() is not None:
                    offset, rows = _tail_events(events_path, offset)
                    for event in rows:
                        detail = progress_from_fill_event(event)
                        if session is not None:
                            append_event(session, "fill/progress", **detail)
                    break
                if time.monotonic() - started > bound:
                    timed_out = True
                    _kill(proc)
                    break
                time.sleep(FILL_POLL_SECONDS)
        except Cancelled:
            _kill(proc)
            raise
        finally:
            for thread in threads:
                thread.join(timeout=10)

        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if timed_out:
            raise RpcError(
                "backend_refused",
                "fill_report exceeded its time bound",
                tool="fill_report",
                timedOut=True,
                stderr=stderr[-4000:],
            )
        if proc.returncode not in (0, None) and not (out_dir / "verdict_v06.json").is_file():
            parsed = _parse_json_object(stdout)
            message = "fill_report exited without a verdict"
            if isinstance(parsed, dict) and parsed.get("error"):
                message = str(parsed["error"])
            raise RpcError(
                "backend_refused",
                message,
                tool="fill_report",
                exitCode=proc.returncode,
                stdout=stdout[-4000:],
                stderr=stderr[-4000:],
            )

        verdict = _load_verdict(out_dir, stdout)
        state = _terminal_state(verdict)
        proof_grade = verdict.get("proof_grade") or "none"
        hwpx = Path(verdict["hwpx"]) if verdict.get("hwpx") else out_dir / "out.hwpx"
        pdf = Path(verdict["pdf"]) if verdict.get("pdf") else out_dir / "out.pdf"
        verdict_path = out_dir / "verdict_v06.json"
        outputs = []
        for role, path in (("hwpx", hwpx), ("pdf", pdf), ("verdict", verdict_path)):
            row = _artifact(role, path)
            if row:
                outputs.append(row)
        sheets = []
        for path in _contact_paths(verdict, sheets_seen):
            row = _contact_sheet(path)
            if row:
                sheets.append(row)
        layout_row = _layout_qa_row(verdict)
        verify_row = _run_verify_format(core.tools, ws, hwpx)
        return {
            "workspacePath": str(ws),
            "sessionId": session.id if session is not None else None,
            "state": state,
            "converged": bool(verdict.get("converged")),
            "proofGrade": proof_grade,
            "pageCount": verdict.get("page_count"),
            "iterations": verdict.get("iterations"),
            "verdict": verdict,
            "outputs": outputs,
            "contactSheets": sheets,
            "layoutQa": layout_row,
            "verifyFormat": verify_row,
            "checks": {
                "required": ["layout_qa", "verify_format"],
                "ranAll": layout_row.get("state") == "ran" and verify_row.get("state") == "ran",
                "acceptance": (
                    layout_row.get("state") == "ran"
                    and layout_row.get("ok") is True
                    and verify_row.get("state") == "ran"
                    and verify_row.get("ok") is True
                ),
                "reason": None,
                "note": (
                    "layout QA is copied from fill_report; verify_format is the "
                    "pipeline checker on output/out.hwpx. Neither is a render proof. "
                    "proofGrade is what fill_report reported."
                ),
                "checks": [layout_row, verify_row],
            },
            "argv": [Path(argv[1]).name if len(argv) > 1 else argv[0],
                     *[a for a in argv[2:]]],
        }
