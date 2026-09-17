#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace/posterRun: drive the report module's poster + poster-verify CLI.

No new poster semantics. The Runtime validates a report workspace's poster
inputs, spawns the same ``poster`` then ``poster-verify`` children
``module.yaml`` already declares, and returns hashed PPTX/PNG paths plus the
verifier's gate rows. A missing report module is ``module_unavailable``.

The GUI must not treat the PNG preview as rendering proof.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import Cancelled  # noqa: E402
from rt_codes import (  # noqa: E402
    CHILD_TIMEOUT_SECONDS,
    MAX_INLINE_IMAGE_BYTES,
    POSTER_TIMEOUT_SECONDS,
    RpcError,
)
from rt_engine import child_python, run_child  # noqa: E402
from rt_pipeline import (  # noqa: E402
    find_workspace,
    pipeline_status,
    poster_inputs,
)
from rt_session import sha256_file  # noqa: E402

POSTER_BUILD_ENV = "RIGORLOOM_POSTER_BUILD"
POSTER_VERIFY_ENV = "RIGORLOOM_POSTER_VERIFY"


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


def _artifact(role: str, path: Path) -> dict | None:
    if not path.is_file():
        return None
    digest, size = sha256_file(path)
    return {"role": role, "path": str(path), "sha256": digest, "bytes": size}


def _preview(path: Path) -> dict | None:
    if not path.is_file():
        return None
    digest, size = sha256_file(path)
    row: dict = {
        "path": str(path),
        "sha256": digest,
        "bytes": size,
        "mediaType": "image/png",
        "data": None,
        "label": "미리보기 이미지, 증명 아님",
    }
    if size <= MAX_INLINE_IMAGE_BYTES:
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        if raw:
            row["data"] = base64.standard_b64encode(raw).decode("ascii")
    return row


def _gate_row(gate: dict) -> dict:
    """P2-shaped row that still carries the verifier gate fields verbatim."""
    name = str(gate.get("name") or "gate")
    passed = bool(gate.get("passed"))
    detail = gate.get("detail") if isinstance(gate.get("detail"), str) else ""
    warn: list[dict] = []
    raw_warn = gate.get("warn")
    if isinstance(raw_warn, list):
        for item in raw_warn:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("code", name)
                warn.append(row)
            else:
                warn.append({"code": name, "msg": str(item)})
    hard: list[dict] = []
    if not passed:
        hard.append({"code": name, "msg": detail or name})
    return {
        "checker": name,
        "state": "ran",
        "ok": passed,
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "name": name,
        "passed": passed,
        "detail": detail,
    }


def _verify_rows(payload: dict) -> list[dict]:
    gates = payload.get("gates")
    if isinstance(gates, list):
        rows = []
        for item in gates:
            if isinstance(item, dict):
                rows.append(_gate_row(item))
        if rows:
            return rows
    checks = payload.get("checks")
    if isinstance(checks, list):
        rows = []
        for item in checks:
            if isinstance(item, dict) and item.get("checker"):
                rows.append(item)
        if rows:
            return rows
    return []


def _terminal_state(rows: list[dict], verify_ok: bool | None) -> str:
    hard = False
    warn = False
    for row in rows:
        counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
        if row.get("ok") is False or int(counts.get("hard") or 0) > 0:
            hard = True
        if int(counts.get("warn") or 0) > 0:
            warn = True
    if hard or verify_ok is False:
        return "fail"
    if warn:
        return "warn"
    return "pass"


def _child_error(payload: dict | None, *, tool: str, stdout: str,
                 stderr: str, exit_code, timed_out: bool) -> RpcError:
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    message = None
    if isinstance(error, dict):
        message = error.get("message")
    elif isinstance(error, str):
        message = error
    if code == "poster_dependency_missing":
        return RpcError(
            "module_unavailable",
            str(message or "the poster extra is not installed"),
            extra="poster",
            tool=tool,
        )
    if timed_out:
        return RpcError(
            "backend_refused",
            f"{tool} exceeded its time bound",
            tool=tool,
            timedOut=True,
            stderr=stderr[-4000:],
        )
    return RpcError(
        "backend_refused",
        str(message or f"{tool} exited without a verdict"),
        tool=tool,
        exitCode=exit_code,
        stdout=stdout[-4000:],
        stderr=stderr[-4000:],
        detail=payload,
    )


def _run_json_child(argv: list[str], *, cwd: Path, timeout: float,
                    checkpoint=None, tool: str) -> dict:
    if checkpoint is not None:
        checkpoint()
    result = run_child(argv, cwd=cwd, timeout=timeout)
    stdout = result.text
    stderr = result.stderr.decode("utf-8", errors="replace")
    payload = _parse_json_object(stdout)
    if result.timed_out:
        raise _child_error(payload, tool=tool, stdout=stdout, stderr=stderr,
                           exit_code=result.returncode, timed_out=True)
    if payload is None:
        raise _child_error(None, tool=tool, stdout=stdout, stderr=stderr,
                           exit_code=result.returncode, timed_out=False)
    error = payload.get("error")
    if payload.get("ok") is False or (
            isinstance(error, dict) and error.get("code") == "poster_dependency_missing"):
        # poster-verify prints gates even when ok is false — that is an
        # answer, not a spawn refusal. Dependency missing is install-shaped.
        if isinstance(error, dict) and error.get("code") == "poster_dependency_missing":
            raise _child_error(payload, tool=tool, stdout=stdout, stderr=stderr,
                               exit_code=result.returncode, timed_out=False)
        if tool == "poster":
            raise _child_error(payload, tool=tool, stdout=stdout, stderr=stderr,
                               exit_code=result.returncode, timed_out=False)
    return payload


def _scripts(tools) -> tuple[Path, Path]:
    build_ov = (os.environ.get(POSTER_BUILD_ENV) or "").strip()
    verify_ov = (os.environ.get(POSTER_VERIFY_ENV) or "").strip()
    if build_ov or verify_ov:
        build = Path(build_ov) if build_ov else Path()
        verify = Path(verify_ov) if verify_ov else Path()
        missing = []
        if not build_ov or not build.is_file():
            missing.append("poster")
        if not verify_ov or not verify.is_file():
            missing.append("poster-verify")
        if missing:
            raise RpcError(
                "module_unavailable",
                "poster CLI override does not name both poster scripts",
                missing=missing,
                module="report",
            )
        return build, verify

    from rt_module import load_registry  # noqa: PLC0415

    try:
        registry, _facts = load_registry(tools.root)
        commands = {row["command"]: row for row in registry.enabled_cli()}
    except RpcError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RpcError(
            "module_unavailable",
            "the report module's poster CLI is not installed",
            module="report",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    missing = [name for name in ("poster", "poster-verify") if name not in commands]
    if missing:
        raise RpcError(
            "module_unavailable",
            "the report module's poster CLI is not enabled in this install",
            missing=missing,
            module="report",
        )
    build = Path(commands["poster"]["script"])
    verify = Path(commands["poster-verify"]["script"])
    absent = []
    if not build.is_file():
        absent.append("poster")
    if not verify.is_file():
        absent.append("poster-verify")
    if absent:
        raise RpcError(
            "module_unavailable",
            "the report module's poster scripts are not on disk",
            missing=absent,
            module="report",
        )
    return build, verify


def _export_png(pptx: Path, png: Path, *, timeout: float) -> bool:
    """Same PowerPoint COM export G5 used. Optional; never a new poster rule."""
    if os.name != "nt" or not pptx.is_file():
        return False
    script = (
        "import sys, shutil\n"
        "from pathlib import Path\n"
        "pptx = Path(sys.argv[1]).resolve()\n"
        "png = Path(sys.argv[2]).resolve()\n"
        "out_dir = png.parent / (png.stem + '-slides')\n"
        "out_dir.mkdir(parents=True, exist_ok=True)\n"
        "try:\n"
        "    import win32com.client\n"
        "except ImportError:\n"
        "    raise SystemExit(2)\n"
        "app = win32com.client.DispatchEx('PowerPoint.Application')\n"
        "try:\n"
        "    try:\n"
        "        app.Visible = 0\n"
        "    except Exception:\n"
        "        pass\n"
        "    pres = app.Presentations.Open(str(pptx), WithWindow=False)\n"
        "    try:\n"
        "        pres.Export(str(out_dir), 'PNG')\n"
        "    finally:\n"
        "        pres.Close()\n"
        "finally:\n"
        "    try:\n"
        "        app.Quit()\n"
        "    except Exception:\n"
        "        pass\n"
        "cands = sorted(out_dir.glob('*.PNG')) + sorted(out_dir.glob('*.png'))\n"
        "if not cands:\n"
        "    raise SystemExit(1)\n"
        "shutil.copyfile(cands[0], png)\n"
    )
    result = run_child(
        [child_python(), "-c", script, str(pptx), str(png)],
        cwd=pptx.parent,
        timeout=timeout,
    )
    return (not result.timed_out) and png.is_file()


def workspace_poster_run(core, workspace, *, session_id=None,
                         checkpoint=None, timeout: float | None = None) -> dict:
    """HOST ONLY. Spawn poster then poster-verify; return hashed outputs."""
    ws = _workspace_dir(workspace)
    header = pipeline_status(str(ws), engine_root=core.tools.root)
    if not header.get("found"):
        raise RpcError(
            "artifact_missing",
            "PIPELINE.md was not found as a report workspace header",
            workspacePath=str(ws),
            missing=["PIPELINE.md"],
        )
    inputs = header.get("posterInputs") or poster_inputs(ws)
    if not inputs.get("complete"):
        raise RpcError(
            "artifact_missing",
            "this report workspace is missing files the poster CLI needs",
            workspacePath=str(ws),
            missing=list(inputs.get("missing") or []),
            posterInputs=inputs,
        )

    session = None
    if session_id is not None:
        session = core.store.get(session_id)

    build_script, verify_script = _scripts(core.tools)
    bound = POSTER_TIMEOUT_SECONDS if timeout is None else float(timeout)
    child_bound = min(bound, CHILD_TIMEOUT_SECONDS)

    poster_dir = ws / "poster"
    poster_dir.mkdir(parents=True, exist_ok=True)
    out_pptx = poster_dir / "poster_v1.pptx"
    out_png = poster_dir / "poster_v1.png"
    form_path = Path(inputs["formPath"])
    try:
        form_mtime = form_path.stat().st_mtime
    except OSError as exc:
        raise RpcError(
            "artifact_missing",
            "poster form could not be read",
            workspacePath=str(ws),
            missing=["poster/form.pptx"],
            path=str(form_path),
        ) from exc

    build_argv = [
        child_python(), str(build_script),
        "--content", inputs["contentPath"],
        "--figures", inputs["figuresPath"],
        "--form", str(form_path),
        "--out", str(out_pptx),
    ]
    try:
        build_payload = _run_json_child(
            build_argv, cwd=core.tools.root, timeout=child_bound,
            checkpoint=checkpoint, tool="poster",
        )
    except Cancelled:
        raise

    built = Path(build_payload["out"]) if isinstance(build_payload.get("out"), str) else out_pptx
    if not built.is_file():
        raise RpcError(
            "backend_refused",
            "poster produced no PPTX",
            tool="poster",
            detail=build_payload,
        )

    verify_argv = [
        child_python(), str(verify_script),
        "--out", str(built),
        "--form", str(form_path),
        "--form-mtime", str(form_mtime),
        "--no-numbers",
    ]
    verify_payload = _run_json_child(
        verify_argv, cwd=core.tools.root, timeout=child_bound,
        checkpoint=checkpoint, tool="poster-verify",
    )
    rows = _verify_rows(verify_payload)
    verify_ok = verify_payload.get("ok")
    if verify_ok is None:
        verify_ok = all(row.get("ok") is not False for row in rows) if rows else False

    if not out_png.is_file() and built.is_file():
        try:
            _export_png(built, out_png, timeout=child_bound)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 — PNG is preview, not a poster rule
            pass

    outputs = []
    pptx_row = _artifact("pptx", built)
    if pptx_row:
        outputs.append(pptx_row)
    png_row = _artifact("png", out_png)
    if png_row:
        outputs.append(png_row)
    preview = _preview(out_png)
    state = _terminal_state(rows, verify_ok if isinstance(verify_ok, bool) else None)
    return {
        "workspacePath": str(ws),
        "sessionId": session.id if session is not None else None,
        "state": state,
        "outputs": outputs,
        "verify": rows,
        "preview": preview,
        "ok": bool(verify_ok) and state != "fail",
        "posterInputs": inputs,
        "build": build_payload,
        "argv": {
            "poster": [Path(build_argv[1]).name, *build_argv[2:]],
            "posterVerify": [Path(verify_argv[1]).name, *verify_argv[2:]],
        },
    }
