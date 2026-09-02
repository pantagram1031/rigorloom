#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded child adapters onto the EXISTING engine and pipeline entrypoints.

The Runtime adapts; it does not reimplement. Every document operation here
terminates in a script this repository already ships:

  * ``engine/scripts/form_inspect.py``   — profile / graph / regions (:1530)
  * ``engine/scripts/preedit.py``        — the offline typed edits (:2417)
  * ``pipeline/scripts/check_residue.py``— the offline residue gate (:770)

SUBPROCESS, NOT IMPORT — recorded choice, with reasons:

  1. crash isolation, which is the whole point of boundary B3 in
     docs/desktop-architecture.md;
  2. the engine scripts are not import-clean for a host process: they mutate
     ``sys.path`` at module scope and import each other by bare basename
     (``form_inspect`` does ``from preedit import ...`` at
     engine/scripts/form_inspect.py:92), so importing one would put
     ``engine/scripts`` permanently on the Runtime's path;
  3. their contract is already a process contract — one JSON object on stdout
     and an exit code in {0, 2, 3} (pipeline/scripts/checker_base.py:13-16).

HONEST LIMITATION, stated rather than hidden: this slice bounds a child's wall
clock and its captured output, and kills the direct child on timeout. It does
NOT establish descendant containment — there is no process group or Windows
Job here. ``pipeline/scripts/diagnostic_candidate_core.py:1128`` does that
properly and records the residual gap as
``DESCENDANT_CONTAINMENT = "not_established"``
(pipeline/scripts/renderer_runtime_v2.py:56). Wiring the Runtime onto that
primitive is Phase 2 work; claiming containment we did not implement would be
worse than the gap.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    CHILD_PYTHON_ENV,
    CHILD_TIMEOUT_SECONDS,
    MAX_CHILD_OUTPUT_BYTES,
    RpcError,
)

#: Repo root = runtime/scripts/../..
DEFAULT_ENGINE_ROOT = Path(__file__).resolve().parents[2]

#: Environment allowlist, not inheritance. Same posture as
#: ``renderer_runtime_v2.ENV_POLICY = "minimal_allowlist_v1"``
#: (pipeline/scripts/renderer_runtime_v2.py:47). PYTHONPATH is deliberately
#: absent: a child must resolve its siblings the way it does on the CLI.
_ENV_KEYS_COMMON = ("PATH", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
_ENV_KEYS_WINDOWS = ("SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT",
                     "SYSTEMDRIVE", "WINDIR", "USERPROFILE", "APPDATA",
                     "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")
_ENV_KEYS_POSIX = ("HOME",)


def child_python(environ: dict | None = None) -> str:
    """The interpreter engine children run under.

    ``sys.executable`` is wrong for a packaged host: in a frozen executable it
    IS the host, so every engine child re-launches the application. The desktop
    sidecar worked around that with an argv convention; this override removes
    the need for one. Set ``RIGORLOOM_CHILD_PYTHON`` to a real interpreter and
    children use it, with no other change anywhere.
    """
    environ = os.environ if environ is None else environ
    override = (environ.get(CHILD_PYTHON_ENV) or "").strip()
    return override or sys.executable


def child_python_facts(environ: dict | None = None) -> dict:
    """What interpreter children will use, and where that came from."""
    environ = os.environ if environ is None else environ
    override = (environ.get(CHILD_PYTHON_ENV) or "").strip()
    return {
        "path": override or sys.executable,
        "source": "override" if override else "sys.executable",
        "env": CHILD_PYTHON_ENV,
        "overrideSet": bool(override),
    }


def validate_child_python(environ: dict | None = None) -> dict:
    """Refuse a broken override up front, not on the first document call.

    An unset override is fine — that is the default path. A SET override that
    does not resolve to a file is a misconfiguration the operator must see at
    initialize, not as a mystifying ``capability_unavailable`` twenty seconds
    into the first inspect.
    """
    facts = child_python_facts(environ)
    if not facts["overrideSet"]:
        return facts
    candidate = Path(facts["path"]).expanduser()
    try:
        resolved = candidate if candidate.is_absolute() else candidate.resolve()
        ok = resolved.is_file()
    except OSError as exc:
        raise RpcError("child_python_invalid",
                       f"{CHILD_PYTHON_ENV} could not be checked: {exc}",
                       env=CHILD_PYTHON_ENV, path=facts["path"]) from exc
    if not ok:
        raise RpcError(
            "child_python_invalid",
            f"{CHILD_PYTHON_ENV} is set but names no file; engine children "
            "would fail on the first call",
            env=CHILD_PYTHON_ENV, path=facts["path"])
    facts["path"] = str(resolved)
    return facts


def child_env() -> dict[str, str]:
    keys = _ENV_KEYS_COMMON + (_ENV_KEYS_WINDOWS if os.name == "nt" else _ENV_KEYS_POSIX)
    env = {key: os.environ[key] for key in keys if key in os.environ}
    # The cp949 lesson (engine/scripts/cli_io.py:3): a Korean-locale console
    # kills --help and any non-ASCII JSON unless UTF-8 is forced.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class ChildResult:
    __slots__ = ("argv", "returncode", "stdout", "stderr", "truncated", "timed_out")

    def __init__(self, argv, returncode, stdout, stderr, truncated, timed_out):
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.truncated = truncated
        self.timed_out = timed_out

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


def run_child(argv: list[str], *, cwd: Path | None = None,
              timeout: float = CHILD_TIMEOUT_SECONDS,
              max_output: int = MAX_CHILD_OUTPUT_BYTES,
              extra_env: dict | None = None) -> ChildResult:
    """One bounded child. stdin is closed; stdout and stderr are drained apart.

    ``extra_env`` ADDS to the allowlist; it does not inherit. The caller names
    each variable and its value, so the child's environment stays something
    somebody decided. It exists because a child can need to see a choice the
    Runtime already made — which module installation is in use, for one — and a
    child answering about a DIFFERENT installation than the caller selected is
    worse than a child that cannot answer at all.
    """
    env = child_env()
    for key, value in (extra_env or {}).items():
        if value is not None:
            env[str(key)] = str(value)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
        )
    except (OSError, ValueError) as exc:
        raise RpcError("capability_unavailable",
                       f"could not start {Path(argv[1]).name if len(argv) > 1 else argv[0]}",
                       detail=str(exc)) from exc

    sinks: dict[str, list[bytes]] = {"out": [], "err": []}
    over = {"out": False, "err": False}

    def drain(pipe, key):
        total = 0
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total <= max_output:
                    sinks[key].append(chunk)
                else:
                    over[key] = True
        except (OSError, ValueError):
            over[key] = True
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for thread in threads:
        thread.join(timeout=10)

    return ChildResult(
        list(argv),
        proc.returncode if proc.returncode is not None else -1,
        b"".join(sinks["out"]), b"".join(sinks["err"]),
        over["out"] or over["err"], timed_out,
    )


class EngineTools:
    """Resolved paths to the shipped entrypoints, with honest availability."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or DEFAULT_ENGINE_ROOT).resolve()
        self.form_inspect = self.root / "engine" / "scripts" / "form_inspect.py"
        self.preedit = self.root / "engine" / "scripts" / "preedit.py"
        self.check_residue = self.root / "pipeline" / "scripts" / "check_residue.py"

    def availability(self) -> dict[str, dict]:
        rows = {}
        for name, path in (("form_inspect", self.form_inspect),
                           ("preedit", self.preedit),
                           ("check_residue", self.check_residue)):
            present = path.is_file()
            rows[name] = {
                "state": "available" if present else "unavailable",
                "reason": None if present else "script not found under the engine root",
                "path": path.relative_to(self.root).as_posix() if present else None,
            }
        return rows

    def _require(self, name: str, path: Path) -> None:
        if not path.is_file():
            raise RpcError("capability_unavailable",
                           f"{name} is not available in this install",
                           tool=name)

    # -- form_inspect -------------------------------------------------------
    def profile(self, source: Path, out_path: Path,
                full_text: list[str] | None = None) -> dict:
        """Write a form profile to ``out_path``; return the child result meta."""
        self._require("form_inspect", self.form_inspect)
        argv = [child_python(), str(self.form_inspect), str(source),
                "--out", str(out_path)]
        for spec in (full_text or ()):
            argv += ["--full-text", spec]
        result = run_child(argv)
        if result.returncode != 0 or not out_path.is_file():
            raise RpcError(
                "backend_refused",
                "form_inspect refused this document",
                tool="form_inspect", exitCode=result.returncode,
                timedOut=result.timed_out,
                stdout=result.text[:4000],
                stderr=result.stderr.decode("utf-8", errors="replace")[:4000],
            )
        return {"exitCode": result.returncode, "profile": str(out_path)}

    # -- preedit ------------------------------------------------------------
    def preedit_run(self, argv_tail: list[str]) -> tuple[int, dict | None, str]:
        """Run one preedit subcommand. Returns (exit, parsed JSON or None, raw)."""
        self._require("preedit", self.preedit)
        result = run_child([child_python(), str(self.preedit)] + argv_tail)
        raw = result.text
        parsed = None
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    import json as _json
                    parsed = _json.loads(line)
                except ValueError:
                    parsed = None
                break
        if result.timed_out:
            raise RpcError("backend_refused", "preedit exceeded its time bound",
                           tool="preedit", timedOut=True)
        return result.returncode, parsed, raw

    # -- render_probe -------------------------------------------------------
    def render_probe(self) -> dict:
        """This MACHINE's renderer inventory. Opt-in: it costs seconds.

        ``pipeline/scripts/render_probe.py`` shells out to ``soffice`` and, on
        Windows, to ``wsl``; measured at ~8s on the bench. That is fine for a
        button and ruinous for ``initialize``, so nothing calls this unless a
        caller asks for it, and the answer is cached for the process.

        What it reports is what the machine HAS, not what this build USES: the
        Runtime calls no converter, and ``capabilities.render.converter`` says
        so regardless of what turns up here.
        """
        probe = self.root / "pipeline" / "scripts" / "render_probe.py"
        if not probe.is_file():
            return {"state": "unavailable",
                    "reason": "pipeline/scripts/render_probe.py not found",
                    "capabilities": None, "renderers": []}
        result = run_child([child_python(), str(probe), "--json"])
        if result.timed_out or result.returncode != 0:
            return {"state": "unavailable",
                    "reason": (f"render_probe exited {result.returncode}"
                               + (" after timing out" if result.timed_out else "")),
                    "capabilities": None, "renderers": []}
        try:
            import json as _json
            payload = _json.loads(result.text)
        except ValueError:
            return {"state": "unavailable",
                    "reason": "render_probe produced no JSON object",
                    "capabilities": None, "renderers": []}
        return {"state": "probed", "reason": None,
                "capabilities": payload.get("capabilities"),
                "renderers": payload.get("renderers", []),
                "note": ("machine inventory only; this build calls none of "
                         "these, see capabilities.render.converter")}

    # -- check_residue ------------------------------------------------------
    def residue(self, profile: Path, artifact: Path) -> dict:
        """Run the residue gate. NEVER raises for a finding — a finding is data."""
        if not self.check_residue.is_file():
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "pipeline/scripts/check_residue.py not found under "
                              "the engine root",
                    "verdict": None, "ok": None}
        result = run_child([child_python(), str(self.check_residue),
                            "--form-profile", str(profile),
                            "--artifact", str(artifact)])
        if result.timed_out:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "checker exceeded its time bound",
                    "verdict": None, "ok": None}
        parsed = None
        text = result.text.strip()
        if text.startswith("{"):
            try:
                import json as _json
                parsed = _json.loads(text)
            except ValueError:
                parsed = None
        if parsed is None:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": f"checker produced no verdict object (exit "
                              f"{result.returncode})",
                    "verdict": None, "ok": None}
        return {
            "checker": "check_residue",
            "state": "ran",
            "exitCode": result.returncode,
            "verdict": parsed.get("verdict"),
            "ok": parsed.get("ok"),
            "counts": parsed.get("counts"),
            "hard": parsed.get("hard", [])[:50],
            "warn": parsed.get("warn", [])[:50],
        }
