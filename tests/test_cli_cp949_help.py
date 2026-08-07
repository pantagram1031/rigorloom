# -*- coding: utf-8 -*-
"""Every shipped CLI must survive ``--help`` on a cp949 console.

``engine/scripts/com_backend.py --help`` died with ``UnicodeEncodeError:
'cp949' codec can't encode character '\\u2014'`` on a Korean-locale Windows
console — the exact platform the COM path exists for. Subcommand help worked,
which is why nobody noticed: argparse writes the TOP-LEVEL parser description
(usually the module docstring, em-dashes and all) straight to ``sys.stdout``,
so the guard has to run before ``parse_args``, and only the top-level
``--help`` exercises that string.

This test is the actual fix. Patching the em-dashes out, or guarding the
scripts that happen to be broken today, leaves the class reintroducible by
the next docstring. So the CLI list is DISCOVERED from the shipped script
trees, never hand-maintained: a new argparse entry point is covered the
moment it lands, and it fails here until it calls the guard.

``PYTHONIOENCODING=cp949`` is how the failure is reproduced portably — it
forces the same encoder Windows picks from the Korean locale, so the test is
meaningful on the Linux CI matrix point too.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The shipped script trees. ``modules/*/scripts`` are covered by their own
#: module suites; these two are the core surface every bundle carries.
SHIPPED_DIRS = (
    REPO_ROOT / "engine" / "scripts",
    REPO_ROOT / "pipeline" / "scripts",
)

_MAIN_GUARD_RE = re.compile(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:",
                            re.M)


def _is_cli(path: Path) -> bool:
    """A shipped CLI = builds an argparse parser AND is runnable as a script."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return ("argparse.ArgumentParser" in text
            and bool(_MAIN_GUARD_RE.search(text)))


def discover_clis() -> list[Path]:
    return sorted((path for directory in SHIPPED_DIRS
                   for path in directory.glob("*.py") if _is_cli(path)),
                  key=lambda p: p.relative_to(REPO_ROOT).as_posix())


CLIS = discover_clis()
CLI_IDS = [p.relative_to(REPO_ROOT).as_posix() for p in CLIS]


def _run_help(path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp949"
    # PYTHONUTF8/PYTHONLEGACYWINDOWSSTDIO would mask the very thing under
    # test — the guard has to work without any interpreter-level opt-in.
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONLEGACYWINDOWSSTDIO", None)
    return subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True, env=env, cwd=str(REPO_ROOT),
        # Decode ourselves: the child writes UTF-8 once the guard is in place,
        # and a decode error here must not be reported as a CLI failure.
        timeout=120)


def test_discovery_found_the_shipped_clis():
    """A guard on the guard: an empty or shrunken list would make every
    parametrized case below vacuously pass."""
    assert len(CLIS) >= 30, CLI_IDS
    # the two entry points the incident named, and the one the fix imitates
    for expected in ("engine/scripts/com_backend.py",
                     "engine/scripts/preedit.py",
                     "pipeline/scripts/module_registry.py"):
        assert expected in CLI_IDS


@pytest.mark.parametrize("cli", CLIS, ids=CLI_IDS)
def test_help_is_cp949_safe(cli: Path):
    proc = _run_help(cli)
    stderr = proc.stderr.decode("utf-8", "replace")
    stdout = proc.stdout.decode("utf-8", "replace")
    assert "Traceback" not in stderr, stderr
    assert "UnicodeEncodeError" not in stderr, stderr
    assert proc.returncode == 0, (
        f"{cli.relative_to(REPO_ROOT).as_posix()} --help exited "
        f"{proc.returncode} under PYTHONIOENCODING=cp949.\n"
        f"stderr:\n{stderr}\nstdout:\n{stdout}\n\n"
        "Fix: call the utf8 stdio guard as the FIRST statement of main() "
        "(engine: `from cli_io import utf8_stdio` / pipeline: "
        "`from checker_base import _utf8_stdio`) — before parse_args, which "
        "is where --help prints.")
    # --help must actually have printed something, or the assertion above
    # would pass for a CLI that silently no-ops.
    assert stdout.strip(), (
        f"{cli.relative_to(REPO_ROOT).as_posix()} --help printed nothing")


def test_guard_degrades_silently_when_reconfigure_is_unavailable():
    """The guard must never be the thing that crashes. A stream without
    ``reconfigure`` (pytest capture, a plain file object, a pipe wrapper) is
    a no-op, not an AttributeError."""
    sys.path.insert(0, str(REPO_ROOT / "engine" / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "pipeline" / "scripts"))
    from cli_io import utf8_stdio
    from checker_base import _utf8_stdio

    class NoReconfigure:
        def write(self, _text):  # pragma: no cover - never called
            return 0

    real_out, real_err = sys.stdout, sys.stderr
    try:
        sys.stdout = sys.stderr = NoReconfigure()
        utf8_stdio()    # must not raise
        _utf8_stdio()   # must not raise
    finally:
        sys.stdout, sys.stderr = real_out, real_err


def test_engine_and_pipeline_guards_agree():
    """Two copies exist for a packaging reason (a distribution-module bundle
    ships ``modules/`` against an installed core and must not reach into
    ``engine/``). They must still do the same thing."""
    sys.path.insert(0, str(REPO_ROOT / "engine" / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "pipeline" / "scripts"))
    import cli_io
    import checker_base

    recorded = []

    class Recorder:
        def reconfigure(self, **kwargs):
            recorded.append(kwargs)

    real_out, real_err = sys.stdout, sys.stderr
    try:
        sys.stdout = sys.stderr = Recorder()
        cli_io.utf8_stdio()
        first = list(recorded)
        recorded.clear()
        checker_base._utf8_stdio()
        second = list(recorded)
    finally:
        sys.stdout, sys.stderr = real_out, real_err

    assert first == second == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]
