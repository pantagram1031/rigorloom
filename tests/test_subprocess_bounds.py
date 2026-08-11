# -*- coding: utf-8 -*-
"""A child-process bound in the suite is a hang detector, not a stopwatch (T121).

Issue #70: ``test_inspect_privacy_safe_failure_does_not_echo_source_path``
failed once inside a full-suite run and the evidence was destroyed before it
could be read. Three full-load reruns never reproduced it. The cause was then
MEASURED rather than guessed — 15 samples of exactly that spawn, a cold
interpreter importing a repo script and exiting:

    idle            min 2.31s   median 2.76s   p90  3.58s   max  3.82s
    under CPU load  min 4.37s   median 9.00s   p90 14.17s   max 36.46s

The bound was ``timeout=10`` — BELOW the loaded median. Under a saturated run
the suite raced the bound instead of the code failing, and because the process
exits 3 either way the flake presented as a privacy regression. That is the
worst possible disguise for a timeout: a privacy assertion that fails for a
reason unrelated to privacy.

``FLOOR_SECONDS`` is derived from that measurement and nothing else. The whole
tree already satisfies it; this guard exists so the next sub-median bound has
to announce itself.

Scope, stated rather than implied:

* ``subprocess.run`` with a ``timeout=`` is the entire surface in the suite
  today — ``check_output``, ``check_call``, ``communicate`` and ``Popen`` carry
  no bound anywhere, and the six ``.wait(timeout=2)`` calls in
  ``tests/test_studio.py`` are ``threading.Event`` handshakes inside one
  interpreter, which have no process cold start to race.
* Product code is NOT scanned. A bound in a shipped script is a policy the
  product owes its caller, not a test-hygiene value, and it belongs to whoever
  set it.
* The bounds this guard leaves alone are not thereby endorsed: ten sites at
  20s and six at 30s clear the floor at 2.2x and 3.3x the loaded median, none
  has ever been observed to fail, and none was measured individually. The
  floor pins the current state; it does not claim those numbers are right.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 2.2x the measured loaded median (9.00s). A bound under this is inside the
# distribution of a normal loaded spawn, which is what #70 was.
FLOOR_SECONDS = 20.0

# The worst spawn actually observed, under synthetic saturation harsher than
# the suite produces. A bound for a spawn that HAS been measured must clear
# its own measurement, not merely the floor.
MEASURED_WORST_SECONDS = 36.46

_SKIP_PARTS = {".git", ".venv", "site-packages", "node_modules", "__pycache__"}


def _test_sources() -> list[Path]:
    return [p for p in sorted(REPO_ROOT.rglob("test_*.py"))
            if not _SKIP_PARTS.intersection(p.parts)]


def _module_number_constants(tree: ast.Module) -> dict[str, float]:
    """Module-level ``NAME = <number>`` bindings, so a named bound resolves."""
    out: dict[str, float] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, (int, float))
                and not isinstance(node.value.value, bool)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = float(node.value.value)
    return out


def _is_subprocess_run(func: ast.expr) -> bool:
    """``subprocess.run(...)`` only.

    Deliberately structural. A textual search for ``timeout=`` over this tree
    reports 54 hits and is wrong about 35 of them: ``timeout=5.0`` passed to a
    runtime helper under test, ``release.wait(timeout=2)`` on a
    ``threading.Event``, and ``subprocess.TimeoutExpired(cmd=..., timeout=10)``
    constructed inside a mock are all not process bounds.
    """
    return (isinstance(func, ast.Attribute) and func.attr == "run"
            and isinstance(func.value, ast.Name) and func.value.id == "subprocess")


def spawn_bounds(source: str) -> list[tuple[int, float | None]]:
    """[(lineno, seconds)] per ``subprocess.run`` timeout; None if unresolvable."""
    tree = ast.parse(source)
    constants = _module_number_constants(tree)
    found: list[tuple[int, float | None]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_subprocess_run(node.func)):
            continue
        for keyword in node.keywords:
            if keyword.arg != "timeout":
                continue
            value: float | None = None
            if (isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, (int, float))
                    and not isinstance(keyword.value.value, bool)):
                value = float(keyword.value.value)
            elif isinstance(keyword.value, ast.Name):
                value = constants.get(keyword.value.id)
            found.append((node.lineno, value))
    return found


def _all_bounds() -> list[tuple[Path, int, float | None]]:
    rows: list[tuple[Path, int, float | None]] = []
    for path in _test_sources():
        for lineno, value in spawn_bounds(
                path.read_text(encoding="utf-8", errors="replace")):
            rows.append((path, lineno, value))
    return rows


# ---------------------------------------------------------------------------
# the floor
# ---------------------------------------------------------------------------

def test_no_spawn_bound_sits_inside_the_loaded_distribution():
    too_tight = [
        "%s:%d timeout=%s" % (path.relative_to(REPO_ROOT).as_posix(), lineno, value)
        for path, lineno, value in _all_bounds()
        if value is not None and value < FLOOR_SECONDS
    ]
    assert not too_tight, (
        "a subprocess bound under %.0fs is inside the measured distribution of a "
        "normal loaded spawn (median 9.00s), so the suite races it instead of "
        "testing the code — that is issue #70. Raise it and record the "
        "measurement:\n  %s" % (FLOOR_SECONDS, "\n  ".join(too_tight)))


def test_a_spawn_bound_is_a_number_the_guard_can_read():
    """A bound behind an import, a call or an expression is a bound nobody audits."""
    unresolvable = [
        "%s:%d" % (path.relative_to(REPO_ROOT).as_posix(), lineno)
        for path, lineno, value in _all_bounds() if value is None
    ]
    assert not unresolvable, (
        "these timeouts are neither a literal nor a module-level constant in "
        "their own file, so this guard cannot check them: %s" % unresolvable)


def test_the_measured_privacy_spawn_clears_its_own_measurement():
    """#70's two sites: the floor is not enough where a measurement exists."""
    path = REPO_ROOT / "engine/tests/test_com_backend_offline.py"
    bounds = spawn_bounds(path.read_text(encoding="utf-8"))
    assert len(bounds) >= 2, bounds
    for lineno, value in bounds:
        assert value is not None and value > MEASURED_WORST_SECONDS, (
            "line %d bounds a spawn measured at up to %.2fs under load with "
            "timeout=%s" % (lineno, MEASURED_WORST_SECONDS, value))


def test_the_scan_actually_reaches_the_suite():
    """A scanner that silently matches nothing passes every assertion above."""
    rows = _all_bounds()
    files = {path for path, _, _ in rows}
    assert len(rows) >= 10, rows
    assert len(files) >= 4, files
    assert any(p.name == "test_com_backend_offline.py" for p in files), files


# ---------------------------------------------------------------------------
# the scanner's own scope — a derived guard is a claim, and a claim needs a check
# ---------------------------------------------------------------------------

def test_scanner_ignores_bounds_that_are_not_process_spawns():
    source = (
        "import subprocess, threading\n"
        "release = threading.Event()\n"
        "def helper(timeout=None): return timeout\n"
        "def t():\n"
        "    assert release.wait(timeout=2)\n"
        "    helper(timeout=5.0)\n"
        "    raise subprocess.TimeoutExpired(cmd='unopkg', timeout=10)\n"
        "def real():\n"
        "    subprocess.run(['x'], capture_output=True, timeout=1)\n"
    )
    assert [value for _, value in spawn_bounds(source)] == [1.0]


def test_scanner_resolves_a_named_bound():
    source = (
        "import subprocess\n"
        "HANG_TIMEOUT = 120\n"
        "def t():\n"
        "    subprocess.run(['x'], timeout=HANG_TIMEOUT)\n"
    )
    assert [value for _, value in spawn_bounds(source)] == [120.0]


def test_scanner_reports_an_unreadable_bound_rather_than_skipping_it():
    source = (
        "import subprocess\n"
        "from elsewhere import LIMIT\n"
        "def t():\n"
        "    subprocess.run(['x'], timeout=LIMIT)\n"
        "    subprocess.run(['y'], timeout=60 * 2)\n"
    )
    assert [value for _, value in spawn_bounds(source)] == [None, None]
