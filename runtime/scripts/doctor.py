#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only installed-product diagnostics for the Runtime CLI."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .rt_codes import CHILD_PYTHON_ENV, EXIT_OK, EXIT_REFUSED
    from .rt_engine import child_env
except ImportError:
    from rt_codes import CHILD_PYTHON_ENV, EXIT_OK, EXIT_REFUSED
    from rt_engine import child_env

DOCTOR_SCHEMA = "rigorloom-doctor/v1"
PROBE_SCHEMA = "rigorloom-capability-probe/v1"
ENABLED_SCHEMA = "rigorloom-enabled-modules/v1"
MIN_PYTHON = (3, 10)
PROBE_TIMEOUT_SECONDS = 30
MAX_DIAGNOSTIC_CHARS = 1000

ENGINE_MARKERS = (
    "engine/scripts/form_inspect.py",
    "engine/scripts/probe.py",
    "pipeline/scripts/module_registry.py",
    "pipeline/scripts/privacy_scan.py",
    "pyproject.toml",
)

_CHILD_FACTS_CODE = r"""
import importlib.metadata as metadata
import json
import sys

def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

print(json.dumps({
    "schema": "rigorloom-child-python/v1",
    "version": list(sys.version_info[:3]),
    "implementation": sys.implementation.name,
    "setuptools": version("setuptools"),
    "wheel": version("wheel"),
}, separators=(",", ":")))
"""


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _check(
    check_id: str,
    *,
    required: bool,
    state: str,
    facts: dict[str, Any] | None = None,
    reason: dict[str, str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": check_id,
        "required": required,
        "state": state,
    }
    if facts is not None:
        row["facts"] = facts
    if reason is not None:
        row["reason"] = reason
    return row


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    numbers = re.findall(r"\d+", value)
    return tuple(int(part) for part in numbers[:3])


def _runtime_python_check(
    version: tuple[int, int, int] | None = None,
) -> dict[str, Any]:
    actual = version or tuple(sys.version_info[:3])
    compatible = actual >= MIN_PYTHON
    return _check(
        "runtime_python",
        required=True,
        state="pass" if compatible else "fail",
        facts={"version": list(actual), "requires": ">=3.10"},
        reason=None if compatible else _reason(
            "python_version_unsupported",
            f"Rigorloom requires Python >=3.10; running {'.'.join(map(str, actual))}.",
        ),
    )


def _resolve_child_python(environ: dict[str, str]) -> tuple[dict[str, Any], Path | None]:
    override = (environ.get(CHILD_PYTHON_ENV) or "").strip()
    configured = override or sys.executable
    source = "override" if override else "sys.executable"
    expanded = os.path.expanduser(configured)
    candidate = Path(expanded)
    if candidate.is_absolute() or candidate.parent != Path("."):
        resolved_text = str(candidate.resolve())
    else:
        resolved_text = shutil.which(expanded, path=environ.get("PATH")) or ""
    if not resolved_text:
        return _check(
            "child_python",
            required=True,
            state="fail",
            facts={"configured": configured, "source": source, "env": CHILD_PYTHON_ENV},
            reason=_reason(
                "child_python_unresolved",
                f"{CHILD_PYTHON_ENV if override else 'sys.executable'} did not resolve to an executable.",
            ),
        ), None
    resolved = Path(resolved_text).resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return _check(
            "child_python",
            required=True,
            state="fail",
            facts={
                "configured": configured,
                "resolved": str(resolved),
                "source": source,
                "env": CHILD_PYTHON_ENV,
            },
            reason=_reason(
                "child_python_not_executable",
                "The configured child Python is not an executable file.",
            ),
        ), None
    return _check(
        "child_python",
        required=True,
        state="pending",
        facts={
            "configured": configured,
            "resolved": str(resolved),
            "source": source,
            "env": CHILD_PYTHON_ENV,
        },
    ), resolved


def _builder_check(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return _check(
            "wheel_builder",
            required=False,
            state="unavailable",
            reason=_reason(
                "child_probe_unavailable",
                "Builder availability could not be observed because child Python failed.",
            ),
        )
    setuptools_version = payload.get("setuptools")
    wheel_version = payload.get("wheel")
    available = (
        _version_tuple(setuptools_version) >= (70, 1)
        or isinstance(wheel_version, str)
    )
    return _check(
        "wheel_builder",
        required=False,
        state="pass" if available else "unavailable",
        facts={
            "setuptools": setuptools_version,
            "wheel": wheel_version,
            "available": available,
            "consumerRequired": False,
        },
        reason=None if available else _reason(
            "wheel_toolchain_unavailable",
            "No offline wheel builder was found; consumer operation remains supported.",
        ),
    )


def _probe_child_python(
    row: dict[str, Any],
    executable: Path | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if executable is None:
        return row, None
    try:
        completed = subprocess.run(
            [str(executable), "-c", _CHILD_FACTS_CODE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=child_env(),
            cwd=str(executable.parent),
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        row["state"] = "fail"
        row["reason"] = _reason(
            "child_python_timeout", "Child Python did not respond within 30 seconds."
        )
        return row, None
    except (OSError, ValueError) as exc:
        row["state"] = "fail"
        row["reason"] = _reason("child_python_spawn_failed", f"Child Python could not start: {exc}")
        return row, None

    stdout = _decode(completed.stdout)
    stderr = _decode(completed.stderr)
    if completed.returncode != 0:
        row["state"] = "fail"
        row["reason"] = _reason(
            "child_python_nonzero",
            f"Child Python exited {completed.returncode}: {(stderr or stdout)[:MAX_DIAGNOSTIC_CHARS]}",
        )
        return row, None
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        row["state"] = "fail"
        row["reason"] = _reason(
            "child_python_output_invalid",
            f"Child Python returned malformed UTF-8/JSON: {stdout[:MAX_DIAGNOSTIC_CHARS]}",
        )
        return row, None
    version = payload.get("version") if isinstance(payload, dict) else None
    valid = (
        isinstance(payload, dict)
        and payload.get("schema") == "rigorloom-child-python/v1"
        and isinstance(version, list)
        and len(version) >= 2
        and all(isinstance(part, int) for part in version)
    )
    if not valid:
        row["state"] = "fail"
        row["reason"] = _reason(
            "child_python_output_invalid",
            "Child Python output did not match rigorloom-child-python/v1.",
        )
        return row, None
    row["facts"].update({
        "version": version,
        "implementation": payload.get("implementation"),
    })
    if tuple(version) < MIN_PYTHON:
        row["state"] = "fail"
        row["reason"] = _reason(
            "child_python_version_unsupported",
            f"Engine children require Python >=3.10; configured child is {version}.",
        )
        return row, payload
    row["state"] = "pass"
    return row, payload


def _read_enabled_modules(engine_root: Path) -> tuple[list[str] | None, dict[str, str] | None]:
    enabled_file = engine_root / "modules" / "enabled.yaml"
    if not enabled_file.is_file():
        return [], None
    try:
        text = enabled_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, _reason("enabled_modules_unreadable", f"enabled.yaml is unreadable: {exc}")
    fields: dict[str, str] = {}
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or key not in {"schema", "enabled"} or key in fields:
            return None, _reason(
                "enabled_modules_invalid",
                f"enabled.yaml line {number} is outside the supported installed schema.",
            )
        fields[key] = value.strip()
    if fields.get("schema") != ENABLED_SCHEMA:
        return None, _reason(
            "enabled_modules_invalid",
            f"enabled.yaml schema must be {ENABLED_SCHEMA}.",
        )
    raw_enabled = fields.get("enabled")
    if raw_enabled is None or not raw_enabled.startswith("[") or not raw_enabled.endswith("]"):
        return None, _reason(
            "enabled_modules_invalid", "enabled.yaml enabled must be an inline list."
        )
    body = raw_enabled[1:-1].strip()
    names = [] if not body else [part.strip() for part in body.split(",")]
    if (
        any(not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) for name in names)
        or len(names) != len(set(names))
    ):
        return None, _reason(
            "enabled_modules_invalid",
            "enabled.yaml contains an invalid or duplicate module name.",
        )
    missing = [
        name for name in names
        if not (engine_root / "modules" / name / "module.yaml").is_file()
    ]
    if missing:
        return None, _reason(
            "enabled_module_missing",
            f"enabled module manifests are missing: {missing}.",
        )
    return names, None


def _engine_check(engine_root_value: str | None, child_python: Path | None) -> dict[str, Any]:
    if not engine_root_value:
        return _check(
            "engine",
            required=False,
            state="unavailable",
            reason=_reason(
                "engine_root_not_configured",
                "No --engine-root was configured; installed-engine checks were not run.",
            ),
        )
    engine_root = Path(engine_root_value).expanduser().resolve()
    marker_state = {
        relative: (engine_root / Path(relative)).is_file()
        for relative in ENGINE_MARKERS
    }
    missing = [relative for relative, present in marker_state.items() if not present]
    facts: dict[str, Any] = {
        "engineRoot": str(engine_root),
        "markers": marker_state,
    }
    if missing:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason(
                "engine_markers_missing",
                f"Configured engine root is not a recognized install; missing markers: {missing}.",
            ),
        )
    enabled, enabled_error = _read_enabled_modules(engine_root)
    if enabled_error is not None:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=enabled_error,
        )
    facts["enabledModules"] = enabled
    facts["enabledState"] = "configured" if enabled else "core-only"
    if child_python is None:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason(
                "engine_probe_unavailable",
                "Installed probe could not run because child Python is unavailable.",
            ),
        )

    environment = child_env()
    environment["RIGORLOOM_ROOT"] = str(engine_root)
    probe_path = engine_root / "engine" / "scripts" / "probe.py"
    try:
        completed = subprocess.run(
            [str(child_python), str(probe_path), "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=environment,
            cwd=str(engine_root),
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason("engine_probe_timeout", "Installed probe timed out after 30 seconds."),
        )
    except (OSError, ValueError) as exc:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason("engine_probe_spawn_failed", f"Installed probe could not start: {exc}"),
        )
    stdout = _decode(completed.stdout)
    stderr = _decode(completed.stderr)
    if completed.returncode != 0:
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason(
                "engine_probe_nonzero",
                f"Installed probe exited {completed.returncode}: {(stderr or stdout)[:MAX_DIAGNOSTIC_CHARS]}",
            ),
        )
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason(
                "engine_probe_output_invalid",
                f"Installed probe returned malformed UTF-8/JSON: {stdout[:MAX_DIAGNOSTIC_CHARS]}",
            ),
        )
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != PROBE_SCHEMA
        or not isinstance(payload.get("render"), dict)
    ):
        return _check(
            "engine",
            required=True,
            state="fail",
            facts=facts,
            reason=_reason(
                "engine_probe_output_invalid",
                f"Installed probe must return {PROBE_SCHEMA} with a render object.",
            ),
        )
    facts["probeSchema"] = payload["schema"]
    facts["render"] = payload["render"]
    return _check("engine", required=True, state="pass", facts=facts)


def run_doctor(
    engine_root: str | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Run all read-only checks and return a JSON-ready result plus exit code."""
    environment = dict(os.environ if environ is None else environ)
    checks = [_runtime_python_check()]
    child_row, executable = _resolve_child_python(environment)
    child_row, child_payload = _probe_child_python(child_row, executable)
    checks.append(child_row)
    checks.append(_builder_check(child_payload))
    checks.append(_engine_check(engine_root, executable if child_row["state"] == "pass" else None))
    required_passed = all(
        row["state"] == "pass" for row in checks if row["required"]
    )
    result = {
        "schema": DOCTOR_SCHEMA,
        "requiredPassed": required_passed,
        "checks": checks,
    }
    return result, EXIT_OK if required_passed else EXIT_REFUSED
