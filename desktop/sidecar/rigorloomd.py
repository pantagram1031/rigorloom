#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen entry for the Runtime, and a stand-in for the interpreter it spawns.

Two jobs, decided by ``sys.argv[1]``.

**Job 1 — serve.** With no ``.py`` first argument this is
``runtime/scripts/serve.py``: it forwards straight to that module's ``main``,
adding ``--engine-root`` pointing at the bundled repo scripts when the caller
did not pass one.

**Job 2 — be the interpreter.** This is the part that makes freezing possible at
all. ``runtime/scripts/rt_engine.py:192`` spawns its engine children as::

    [sys.executable, "<engine-root>/engine/scripts/form_inspect.py", ...]

Under PyInstaller ``sys.executable`` is *this executable*, not a Python. Left
alone, ``document/inspect`` would recursively launch a second protocol server
instead of running ``form_inspect``, and every inspect call would hang. So when
argv[1] names a ``.py`` file, this entry behaves exactly like ``python
script.py ...``: it puts the script's own directory on ``sys.path`` — which is
what CPython does for a script invocation, and what those scripts rely on to
import their siblings (``from cli_io import utf8_stdio``) — and runs it as
``__main__``.

``rt_engine.child_env()`` is an allowlist that deliberately omits ``PYTHONPATH``
(runtime/scripts/rt_engine.py:54), so the path setup has to happen here and
cannot be inherited.

This works because the three children the Runtime spawns —
``engine/scripts/form_inspect.py``, ``engine/scripts/preedit.py`` and
``pipeline/scripts/check_residue.py`` — import only the standard library plus
their repo siblings. No third-party package is involved, so the frozen
interpreter can execute them from source with no import hook.

Nothing in ``runtime/``, ``engine/`` or ``pipeline/`` is modified. This file is
an adapter that lives entirely in ``desktop/``.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _frozen_root() -> Path | None:
    """The one-dir bundle's own directory, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def bundled_engine_root() -> Path:
    """Where ``engine/scripts`` and ``pipeline/scripts`` live for this build.

    Frozen: ``<bundle>/repo`` — laid down by ``build.ps1`` as ``--add-data``.
    Source: the checkout this file sits in (``desktop/sidecar`` -> repo root).
    """
    frozen = _frozen_root()
    if frozen is not None:
        candidate = frozen / "repo"
        if candidate.is_dir():
            return candidate
        # PyInstaller's onefile/temp layout, kept as a fallback so a one-file
        # build is diagnosable rather than mysteriously broken.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "repo"
            if candidate.is_dir():
                return candidate
        return frozen
    return Path(__file__).resolve().parents[2]


def run_as_script(script: Path, argv_tail: list[str]) -> int:
    """``python script.py args...`` — the interpreter half of this entry."""
    if not script.is_file():
        sys.stderr.write(f"rigorloomd: no such script: {script}\n")
        return 2
    # sys.path[0] is the script's directory for a script invocation. These
    # scripts depend on it: engine/scripts/form_inspect.py does
    # `from cli_io import utf8_stdio`.
    here = str(script.parent)
    sys.path.insert(0, here)
    # pipeline/scripts and engine/scripts import across the boundary in places;
    # add the sibling so a cross-import does not fail in the frozen build only.
    root = bundled_engine_root()
    for sibling in (root / "engine" / "scripts", root / "pipeline" / "scripts"):
        text = str(sibling)
        if sibling.is_dir() and text not in sys.path:
            sys.path.append(text)
    sys.argv = [str(script)] + argv_tail
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        sys.stderr.write(f"{code}\n")
        return 1
    return 0


def run_server(argv: list[str]) -> int:
    """The protocol server. Adds --engine-root when the caller omitted it."""
    root = bundled_engine_root()
    runtime_scripts = root / "runtime" / "scripts"
    if runtime_scripts.is_dir() and str(runtime_scripts) not in sys.path:
        sys.path.insert(0, str(runtime_scripts))
    if "--engine-root" not in argv:
        argv = list(argv) + ["--engine-root", str(root)]
    import serve  # noqa: PLC0415 — after sys.path is arranged

    return serve.main(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # UTF-8 before anything prints, for the cp949 reason at
    # engine/scripts/cli_io.py:3.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    if argv and argv[0].lower().endswith(".py"):
        return run_as_script(Path(argv[0]), argv[1:])
    return run_server(argv)


if __name__ == "__main__":
    raise SystemExit(main())
