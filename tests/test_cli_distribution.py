# -*- coding: utf-8 -*-
"""DIST-CLI-01 — the Python wheel distribution of the Runtime CLI.

The repository ships two independent distribution paths and this file guards
the boundary between them:

  * the module/skill ZIP bundles (``scripts/package_module.py``,
    ``scripts/sync_local.py``, ``evals/cleanroom.py``) — unchanged, and proven
    still absent from the wheel by ``test_wheel_excludes_the_zip_bundle_path``;
  * the Python wheel built here, which carries the Runtime layer and one
    console command, ``rigorloom``.

The wheel surface is an ALLOWLIST, not a sweep. A flat-layout repository with
twelve importable top-level directories will, left to setuptools' automatic
discovery, either refuse to build or ship all twelve; both are wrong, and
``test_wheel_inventory_is_narrow`` is what keeps the third answer honest.

``rigorloom`` is not a second CLI. The console entry point resolves to the same
``main`` that ``python runtime/scripts/cli.py`` runs, and
``test_installed_cli_is_the_repository_implementation`` compares the installed
file with the checkout's byte for byte rather than asserting it in a comment.

Building a wheel needs a toolchain this repository does not vendor and must not
download. The tests that build therefore skip — loudly, with the reason — when
the interpreter cannot produce one. Point ``RIGORLOOM_WHEEL_PYTHON`` at an
interpreter that can (setuptools plus ``wheel``, or setuptools >= 70.1, which
carries ``bdist_wheel`` itself) to run them against a different toolchain than
the one running pytest.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

try:  # 3.11+, and this repository requires 3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 has no tomllib
    tomllib = None

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: The one package the wheel is allowed to carry, and where it lives in the
#: checkout. Both halves are asserted against pyproject.toml, so renaming one
#: without the other fails here rather than in someone's install.
WHEEL_PACKAGE = "rigorloom_runtime"
WHEEL_PACKAGE_DIR = "runtime/scripts"

#: Console command the wheel must expose, and the callable behind it.
CONSOLE_SCRIPT = "rigorloom"
CONSOLE_TARGET = f"{WHEEL_PACKAGE}.cli:main"

#: Top-level checkout directories that must never reach an installed wheel.
#: ``modules``/``skill`` are here because they belong to the OTHER distribution
#: path; ``tests``/``qa``/``evals`` because a user installs a product, not a
#: harness; ``archive``/``desktop`` because they are unshipped work.
FORBIDDEN_TOP_LEVEL = (
    "adapters", "agenthost", "archive", "desktop", "docs", "engine", "evals",
    "examples", "modules", "pipeline", "qa", "scripts", "skill", "studio",
    "tests", "workspaces",
)

#: Evidence and corpus extensions. A wheel carrying one of these is shipping
#: somebody's document, which is a privacy failure before it is a size one.
FORBIDDEN_SUFFIXES = (
    ".hwp", ".hwpx", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".zip",
    ".jsonl", ".yaml", ".yml",
)

BUILD_TIMEOUT = 600
RUN_TIMEOUT = 300

#: Probe run in a candidate interpreter: can it turn an sdist into a wheel
#: without reaching the network? setuptools vendored ``bdist_wheel`` in 70.1;
#: before that the separate ``wheel`` distribution supplied the command.
_TOOLCHAIN_PROBE = """
import importlib.util as u
spec = u.find_spec("setuptools")
if spec is None:
    print("no setuptools"); raise SystemExit(1)
import setuptools
version = tuple(int(p) for p in setuptools.__version__.split(".")[:2] if p.isdigit())
if version >= (70, 1) or u.find_spec("wheel") is not None:
    print(setuptools.__version__); raise SystemExit(0)
print("setuptools %s without the wheel package" % setuptools.__version__)
raise SystemExit(1)
"""


def _run(argv, **kwargs):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    kwargs.setdefault("env", env)
    kwargs.setdefault("timeout", RUN_TIMEOUT)
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


def _pyproject() -> dict:
    if tomllib is None:  # pragma: no cover - 3.10 only
        pytest.skip("tomllib is 3.11+; the wheel contract is read from TOML")
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _build_python() -> str | None:
    """An interpreter that can build a wheel offline, or None."""
    candidates = []
    override = (os.environ.get("RIGORLOOM_WHEEL_PYTHON") or "").strip()
    if override:
        candidates.append(override)
    candidates.append(sys.executable)
    for candidate in candidates:
        try:
            probe = _run([candidate, "-c", _TOOLCHAIN_PROBE], timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


def _export_clean_tree(dest: Path) -> Path:
    """Copy the tracked (and not-ignored) tree — no worktrees, no build junk.

    ``git ls-files`` is the definition of "clean export" used here: it never
    lists ``.git``, an ignored ``__pycache__``, a nested worktree, or a local
    scratch file, so a wheel built from this tree can only pick up files the
    repository actually publishes.
    """
    listing = _run(["git", "-C", str(REPO_ROOT), "ls-files", "-z",
                    "--cached", "--others", "--exclude-standard"])
    if listing.returncode != 0:
        pytest.skip(f"git ls-files failed: {listing.stderr.strip()[:200]}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in listing.stdout.split("\0"):
        if not name:
            continue
        source = REPO_ROOT / name
        if not source.is_file():
            continue  # staged-but-deleted, or a submodule gitlink
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return dest


@pytest.fixture(scope="session")
def build_python() -> str:
    interpreter = _build_python()
    if interpreter is None:
        pytest.skip(
            "no offline wheel toolchain: this interpreter has no setuptools "
            "with bdist_wheel (setuptools >= 70.1, or setuptools plus the "
            "wheel package). Set RIGORLOOM_WHEEL_PYTHON to one that has. "
            "Installing it here would be a dependency download, which "
            "DIST-CLI-01 forbids.")
    return interpreter


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory, build_python) -> Path:
    """Build the wheel once, from a clean export, into a temporary directory."""
    base = tmp_path_factory.mktemp("dist")
    source = _export_clean_tree(base / "source")
    wheelhouse = base / "wheelhouse"
    wheelhouse.mkdir()
    built = _run([build_python, "-m", "pip", "wheel",
                  "--no-deps", "--no-build-isolation", "--no-index",
                  "--wheel-dir", str(wheelhouse), str(source)],
                 timeout=BUILD_TIMEOUT)
    assert built.returncode == 0, (
        "pip wheel --no-deps --no-build-isolation --no-index failed:\n"
        f"{built.stdout[-4000:]}\n{built.stderr[-4000:]}")
    wheels = sorted(wheelhouse.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def installed_cli(tmp_path_factory, built_wheel) -> Path:
    """Install the wheel into a fresh venv; yield the ``rigorloom`` command."""
    venv_dir = tmp_path_factory.mktemp("venv") / "fresh"
    created = _run([sys.executable, "-m", "venv", str(venv_dir)],
                   timeout=BUILD_TIMEOUT)
    assert created.returncode == 0, (
        f"venv creation failed:\n{created.stdout[-2000:]}\n{created.stderr[-2000:]}")
    bindir = "Scripts" if os.name == "nt" else "bin"
    venv_python = venv_dir / bindir / ("python.exe" if os.name == "nt" else "python")
    assert venv_python.is_file(), f"no interpreter at {venv_python}"

    probe = _run([str(venv_python), "-m", "pip", "--version"])
    if probe.returncode != 0:
        pytest.skip("the fresh venv has no pip, and bootstrapping one would "
                    "be a dependency download")

    installed = _run([str(venv_python), "-m", "pip", "install",
                      "--no-deps", "--no-index", str(built_wheel)],
                     timeout=BUILD_TIMEOUT)
    assert installed.returncode == 0, (
        f"wheel install failed:\n{installed.stdout[-4000:]}\n{installed.stderr[-4000:]}")

    command = venv_dir / bindir / (f"{CONSOLE_SCRIPT}.exe" if os.name == "nt"
                                   else CONSOLE_SCRIPT)
    assert command.is_file(), (
        f"the wheel installed no {CONSOLE_SCRIPT} command at {command}; "
        f"{bindir} holds {sorted(p.name for p in (venv_dir / bindir).iterdir())}")
    return command


@pytest.fixture(scope="session")
def installed_site(tmp_path_factory, built_wheel) -> Path:
    """Unpack the wheel and yield the installed package directory."""
    unpacked = tmp_path_factory.mktemp("unpacked")
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(unpacked)
    return unpacked / WHEEL_PACKAGE


# --- the declared contract ----------------------------------------------------

def test_pyproject_declares_a_build_system():
    """Without this table there is no wheel at all — pip has no backend."""
    config = _pyproject()
    build_system = config.get("build-system")
    assert build_system, "pyproject.toml declares no [build-system]"
    assert build_system.get("build-backend"), "no build-backend named"
    assert build_system.get("requires"), "no build requirements named"


def test_pyproject_declares_the_console_script():
    config = _pyproject()
    scripts = config.get("project", {}).get("scripts", {})
    assert scripts.get(CONSOLE_SCRIPT) == CONSOLE_TARGET, (
        f"{CONSOLE_SCRIPT} must resolve to {CONSOLE_TARGET} so the command and "
        "the checkout run the same main()")


def test_pyproject_pins_an_explicit_package_allowlist():
    """Automatic discovery over a flat layout is the bug this replaces."""
    config = _pyproject()
    setuptools_table = config.get("tool", {}).get("setuptools", {})
    assert setuptools_table.get("packages") == [WHEEL_PACKAGE], (
        "the wheel must name its packages explicitly; automatic discovery "
        "either refuses this flat layout or sweeps every top-level directory "
        "into the distribution")
    package_dir = setuptools_table.get("package-dir", {})
    assert package_dir.get(WHEEL_PACKAGE) == WHEEL_PACKAGE_DIR, (
        f"{WHEEL_PACKAGE} must map to {WHEEL_PACKAGE_DIR}, the Runtime layer "
        "the CLI already lives in")
    assert setuptools_table.get("include-package-data") is False, (
        "include-package-data must be explicitly false: the allowlist is the "
        "package list, and data sweeping would defeat it")


def test_package_dir_is_importable_as_a_package():
    """setuptools needs an ``__init__.py`` to treat the directory as a package."""
    assert (REPO_ROOT / WHEEL_PACKAGE_DIR / "__init__.py").is_file()


def test_the_zip_bundle_distribution_is_still_present():
    """DIST-CLI-01 adds a path; it does not replace the module/skill one."""
    for relative in ("scripts/package_module.py", "scripts/sync_local.py",
                     "evals/cleanroom.py"):
        assert (REPO_ROOT / relative).is_file(), f"{relative} disappeared"


# --- the built wheel ----------------------------------------------------------

def test_wheel_builds_from_a_clean_source_tree(built_wheel):
    """Requirement 1: the build itself, offline, without build isolation."""
    assert built_wheel.name.startswith("rigorloom-")
    assert built_wheel.name.endswith("-py3-none-any.whl"), (
        f"expected a pure-Python wheel, got {built_wheel.name}")


def test_wheel_inventory_is_narrow(built_wheel):
    """Requirement 2: an allowlist, checked entry by entry."""
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
    assert names, "the wheel is empty"
    tops = {name.split("/")[0] for name in names}
    allowed_dist_info = {name for name in tops if name.endswith(".dist-info")}
    assert len(allowed_dist_info) == 1, f"odd .dist-info set: {allowed_dist_info}"
    assert tops == {WHEEL_PACKAGE} | allowed_dist_info, (
        f"the wheel carries unexpected top-level entries: "
        f"{sorted(tops - ({WHEEL_PACKAGE} | allowed_dist_info))}")

    lowered = [name.lower() for name in names]
    for forbidden in FORBIDDEN_TOP_LEVEL:
        assert not any(part == forbidden
                       for name in lowered for part in name.split("/")[:-1]), (
            f"the wheel reaches into {forbidden}/")
    for suffix in FORBIDDEN_SUFFIXES:
        offenders = [name for name in lowered if name.endswith(suffix)]
        assert not offenders, f"the wheel ships {suffix} files: {offenders[:5]}"
    assert not any("__pycache__" in name or name.endswith(".pyc")
                   for name in lowered), "the wheel ships bytecode"


def test_wheel_excludes_the_zip_bundle_path(built_wheel):
    """The other distribution system must not be swept in as a side effect."""
    with zipfile.ZipFile(built_wheel) as archive:
        names = "\n".join(archive.namelist())
    for marker in ("package_module.py", "sync_local.py", "cleanroom.py",
                   "SKILL.md", "module.yaml"):
        assert marker not in names, f"the wheel swept in {marker}"


def test_wheel_carries_the_runtime_cli(built_wheel):
    with zipfile.ZipFile(built_wheel) as archive:
        names = set(archive.namelist())
    for expected in (f"{WHEEL_PACKAGE}/__init__.py", f"{WHEEL_PACKAGE}/cli.py",
                     f"{WHEEL_PACKAGE}/rt_core.py", f"{WHEEL_PACKAGE}/rt_codes.py"):
        assert expected in names, f"{expected} is missing from the wheel"


def test_installed_cli_is_the_repository_implementation(installed_site):
    """Requirement 3: one implementation, not a packaged copy that drifts."""
    shipped = (installed_site / "cli.py").read_bytes()
    checkout = (REPO_ROOT / WHEEL_PACKAGE_DIR / "cli.py").read_bytes()
    assert shipped == checkout, (
        "the wheel's cli.py differs from runtime/scripts/cli.py; the console "
        "command must be the same implementation, not a fork of it")


# --- the installed command ----------------------------------------------------

def test_installed_help_exits_zero_and_names_the_commands(installed_cli):
    """Requirement 3: ``rigorloom --help`` works in a fresh venv."""
    result = _run([str(installed_cli), "--help"])
    assert result.returncode == 0, (
        f"--help exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    for command in ("capabilities", "inspect", "propose", "apply", "verify",
                    "modules", "receipt"):
        assert command in result.stdout, f"--help never names {command}"


def test_installed_capabilities_emits_one_json_document(installed_cli, tmp_path):
    """Requirement 4: one JSON document, exit 0, from a fresh root."""
    root = tmp_path / "root"
    result = _run([str(installed_cli), "--root", str(root), "capabilities"])
    assert result.returncode == 0, (
        f"capabilities exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout)  # one document, or this raises
    assert payload["ok"] is True
    assert payload["command"] == "capabilities"
    assert payload["result"]["protocolVersion"]
    assert "capabilities" in payload["result"]["methods"] or \
        payload["result"]["methods"], "no method roster reported"


def test_installed_capabilities_never_claims_a_missing_resource(installed_cli,
                                                                tmp_path):
    """Requirement 4: absence is reported with a reason, never as availability.

    The wheel deliberately omits ``engine/`` and ``pipeline/`` — they belong to
    the checkout, not to the CLI distribution — so a wheel-only install MUST
    report those tools unavailable. A build that claimed them would send a
    caller down a COM path that cannot exist.
    """
    root = tmp_path / "root"
    result = _run([str(installed_cli), "--root", str(root), "capabilities"])
    assert result.returncode == 0
    snapshot = json.loads(result.stdout)["result"]

    for tool in ("form_inspect", "preedit", "check_residue"):
        row = snapshot["tools"][tool]
        assert row["state"] == "unavailable", (
            f"a wheel-only install claims {tool} is {row['state']}, but the "
            "wheel ships no engine/ or pipeline/ scripts")
        assert row["reason"], f"{tool} is unavailable with no reason given"

    assert snapshot["modules"]["state"] == "unavailable"
    assert snapshot["modules"]["reason"], "modules unavailable with no reason"

    negative = {"unavailable", "no", "not_established", "false"}
    unexplained = []

    def walk(node, path="result"):
        if isinstance(node, dict):
            state = node.get("state")
            if isinstance(state, str) and state in negative and not node.get("reason"):
                unexplained.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(snapshot)
    assert not unexplained, f"unavailable without a reason: {unexplained}"


def test_installed_cli_refuses_a_missing_root(installed_cli):
    """--root has no default, ever (runtime/scripts/cli.py:150-152)."""
    result = _run([str(installed_cli), "capabilities"])
    assert result.returncode == 2, (
        f"expected the usage exit 2, got {result.returncode}:\n{result.stderr}")


# --- the source path, unchanged -----------------------------------------------

def test_source_invocation_still_works(tmp_path):
    """Requirement 5: the editable/source entry point is not regressed."""
    root = tmp_path / "root"
    result = _run([sys.executable, str(REPO_ROOT / "runtime" / "scripts" / "cli.py"),
                   "--root", str(root), "capabilities"])
    assert result.returncode == 0, (
        f"source CLI exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "capabilities"


def test_source_invocation_still_sees_the_checkout(tmp_path):
    """The checkout keeps what the wheel omits: engine and pipeline scripts."""
    root = tmp_path / "root"
    result = _run([sys.executable, str(REPO_ROOT / "runtime" / "scripts" / "cli.py"),
                   "--root", str(root), "capabilities"])
    assert result.returncode == 0
    tools = json.loads(result.stdout)["result"]["tools"]
    assert tools["form_inspect"]["state"] == "available", (
        "the source CLI stopped resolving engine/scripts/form_inspect.py; the "
        "packaging change must not move the default engine root")
