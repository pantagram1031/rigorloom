#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional adapter to a separately installed HWP/HWPX engine (``kit_api``).

Rigorloom does not ship this engine. It is a private, separate install whose
JSON API (api version 1) is a set of functions that each return a dict and
never raise: ``{"api": 1, "ok": true, "backend": ..., "fn": ..., ...}`` or
``{"api": 1, "ok": false, "error": {"code", "message"}}``. This module only
knows that contract. No engine source, fonts or documents live here.

WHEN THE ENGINE IS ABSENT nothing changes: the built-in ``preedit`` path keeps
working exactly as before, and every call here returns a structured refusal
naming what cannot be done without the engine (the ``CANNOT`` table below).
The adapter never falls back silently and never pretends a result.

HOW IT IS FOUND. Only one way, on purpose: the environment variable
``RIGORLOOM_HWP_ENGINE`` points at the directory that holds ``kit_api.py``.
Nothing is imported into this process. Each call runs
``python kit_api.py FN --args JSON --json`` as a child, so the engine's own
imports, ``sys.path`` changes and backends stay in its process, and a crash
there is a refusal here, not a crash. The child runs in the caller's working
directory, so relative paths in ``args`` mean what the caller meant.

Full integration (routing runtime plans through the engine) is a later work
package. This module is the boundary that work will use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_ENV = "RIGORLOOM_HWP_ENGINE"
ENGINE_ENTRY = "kit_api.py"
ENGINE_API = 1
ADAPTER_SCHEMA = "rigorloom/hwp-engine-adapter/v0"
DEFAULT_TIMEOUT_S = 120
#: An engine answer bigger than this is refused rather than parsed.
MAX_RESULT_BYTES = 16 * 1024 * 1024

#: The engine functions this adapter forwards (kit_api api 1).
FUNCTIONS = ("to_hwpx", "analyze", "check_form", "fill", "build", "pages",
             "pdf", "save", "edit", "features_used", "features")

#: What Rigorloom cannot do on its own, per function: the reason a caller gets
#: when the engine is absent. Each line is a limit of the built-in path, not a
#: limit of the engine.
CANNOT: dict[str, tuple[str, str]] = {
    "to_hwpx": ("hwp_binary_unsupported",
                "Without the engine, .hwp (HWP 5 binary) files cannot be "
                "converted, read or edited on Linux; only .hwpx is supported."),
    "analyze": ("engine_analysis_unavailable",
                "Without the engine, form analysis is the built-in "
                "form_inspect profile only (.hwpx, no .hwp)."),
    "check_form": ("engine_form_check_unavailable",
                   "Without the engine, plans are validated by the built-in "
                   "runtime rules only."),
    "fill": ("engine_fill_unavailable",
             "Without the engine, filling is limited to the built-in preedit "
             "operations (fill_cell, replace_at_cell, set_run, delete_guides)."),
    "build": ("structural_build_unsupported",
              "Without the engine, a document cannot be built from a blank "
              "form: no new paragraphs, tables or sections."),
    "pages": ("page_layout_unavailable",
              "Without the engine, Hancom-equivalent line and page breaking "
              "cannot be predicted."),
    "pdf": ("text_pdf_unavailable",
            "Without the engine, no PDF with a text layer can be produced; "
            "the built-in renderer gives uncertified PNG pages only."),
    "save": ("engine_save_unavailable",
             "Without the engine, saving uses the built-in preedit writer."),
    "edit": ("structural_edit_unsupported",
             "Without the engine, paragraphs, tables, equations and pictures "
             "cannot be inserted or restyled."),
    "features_used": ("feature_scan_unavailable",
                      "Without the engine, feature detection is the built-in "
                      "form_inspect inventory only."),
    "features": ("engine_features_unavailable",
                 "The engine is not installed, so it has no feature list."),
}


def _refusal(fn: str, reason: str, message: str, **extra) -> dict:
    out = {"schema": ADAPTER_SCHEMA, "ok": False, "fn": fn,
           "error": {"code": "capability_unavailable", "reason": reason,
                     "message": message}}
    out["error"].update(extra)
    return out


def detect(env: dict | None = None) -> dict:
    """Where the engine is, or why it is not available. Never raises."""
    env = os.environ if env is None else env
    raw = env.get(ENGINE_ENV, "").strip()
    if not raw:
        return {"schema": ADAPTER_SCHEMA, "available": False,
                "reason": "engine_not_configured",
                "message": f"Set {ENGINE_ENV} to the directory that holds "
                           f"{ENGINE_ENTRY} to use the separately installed "
                           "HWP engine. Rigorloom works without it."}
    root = Path(raw).expanduser()
    entry = root / ENGINE_ENTRY
    if not entry.is_file():
        return {"schema": ADAPTER_SCHEMA, "available": False,
                "reason": "engine_path_missing",
                "message": f"{ENGINE_ENV} is set, but {ENGINE_ENTRY} is not "
                           "in that directory.",
                "path": str(root)}
    return {"schema": ADAPTER_SCHEMA, "available": True, "path": str(root),
            "entry": str(entry)}


def _python() -> str:
    return os.environ.get("RIGORLOOM_CHILD_PYTHON") or sys.executable


def call(fn: str, args: dict | None = None, *, env: dict | None = None,
         timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """Run one engine function. Returns the engine's dict or a refusal.

    The refusal shape is always ``{"ok": False, "error": {"code":
    "capability_unavailable", "reason": ..., "message": ...}}``; ``reason``
    says which limit applied. An engine-side failure keeps the engine's own
    error under ``error.engine``.
    """
    if fn not in FUNCTIONS:
        return _refusal(fn, "unknown_engine_function",
                        f"{fn!r} is not an engine function this adapter "
                        f"forwards ({', '.join(FUNCTIONS)}).")
    found = detect(env)
    if not found["available"]:
        reason, message = CANNOT[fn]
        return _refusal(fn, reason, message, engine=found["reason"])
    payload = json.dumps(args or {}, ensure_ascii=False)
    child_env = dict(os.environ if env is None else env)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(
            [_python(), found["entry"], fn, "--args", payload, "--json"],
            env=child_env, capture_output=True,
            timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return _refusal(fn, "engine_timeout",
                        f"The engine did not answer within {timeout:g} s.")
    except OSError as exc:
        return _refusal(fn, "engine_not_runnable",
                        f"The engine could not be started: {type(exc).__name__}.")
    if len(proc.stdout) > MAX_RESULT_BYTES:
        return _refusal(fn, "engine_result_too_large",
                        "The engine's answer exceeded the adapter's size limit.")
    result = _parse_last_json(proc.stdout)
    if result is None:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-400:]
        return _refusal(fn, "engine_contract_violation",
                        "The engine did not print a JSON result.",
                        exit_code=proc.returncode, stderr_tail=tail)
    if result.get("api") != ENGINE_API or not isinstance(result.get("ok"), bool):
        return _refusal(fn, "engine_contract_violation",
                        f"The engine answered outside api {ENGINE_API}.",
                        exit_code=proc.returncode)
    if not result["ok"]:
        return _refusal(fn, "engine_refused",
                        "The engine refused this call.",
                        engine=result.get("error"), exit_code=proc.returncode)
    result.setdefault("schema", ADAPTER_SCHEMA)
    return result


def _parse_last_json(raw: bytes):
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    for candidate in (text, text.splitlines()[-1]):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def status(env: dict | None = None) -> dict:
    """``detect`` plus the engine's own feature list when it is available."""
    found = detect(env)
    out = dict(found)
    out["functions"] = list(FUNCTIONS)
    if not found["available"]:
        out["withoutEngine"] = {fn: {"reason": r, "message": m}
                                for fn, (r, m) in CANNOT.items()}
        return out
    feats = call("features", env=env)
    out["engine"] = {"ok": feats.get("ok", False),
                     "backend": feats.get("backend"),
                     "error": feats.get("error")}
    return out
