# -*- coding: utf-8 -*-
"""Focused report-module placement and explicit-root scaffold tests."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_SOURCE = REPO_ROOT / "modules" / "report" / "scripts" / "new_report.py"
SHIM_SOURCE = REPO_ROOT / "scripts" / "new_report.py"
PIPELINE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _write_stub(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def installed_module(tmp_path: Path) -> dict[str, Path]:
    engine = tmp_path / "installed"
    report_scripts = engine / "modules" / "report" / "scripts"
    report_scripts.mkdir(parents=True)
    module_script = report_scripts / "new_report.py"
    shutil.copyfile(MODULE_SOURCE, module_script)
    _write_stub(
        report_scripts / "pipeline_ctl.py",
        "import json, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1] != 'init': raise SystemExit(2)\n"
        "workspace = Path(sys.argv[2])\n"
        "(workspace / 'PIPELINE.md').write_text("
        "'status: initialized\\n', encoding='utf-8')\n"
        "print(json.dumps({'ok': True, 'workspace': str(workspace)}))\n",
    )
    _write_stub(
        report_scripts / "workspace_organizer.py",
        "import json, sys\n"
        "from pathlib import Path\n"
        "workspace = Path(sys.argv[1])\n"
        "(workspace / 'NEXT_TASK.md').write_text('next\\n', encoding='utf-8')\n"
        "(workspace / 'WORKSPACE_INDEX.md').write_text('index\\n', encoding='utf-8')\n"
        "print(json.dumps({'ok': True, 'workspace': str(workspace)}))\n",
    )
    _write_stub(
        engine / "pipeline" / "scripts" / "personalization_ctl.py",
        "import json, sys\n"
        "from pathlib import Path\n"
        "profile = Path(sys.argv[sys.argv.index('--profile-root') + 1])\n"
        "profile.mkdir(parents=True, exist_ok=True)\n"
        "(profile / 'resolved.json').write_text('{}', encoding='utf-8')\n"
        "print(json.dumps({'ok': True, 'profile': str(profile)}))\n",
    )
    (engine / "pyproject.toml").write_text(
        "[project]\nname='rigorloom'\nversion='0.17.0'\n", encoding="utf-8"
    )
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"portable fixture")
    return {
        "engine": engine,
        "script": module_script,
        "pipeline": report_scripts / "pipeline_ctl.py",
        "form": form,
    }


def _run(
    installed: dict[str, Path],
    *extra: str,
    include_roots: bool = True,
) -> subprocess.CompletedProcess:
    argv = [
        sys.executable, str(installed["script"]),
        "--slug", "demo",
        "--subject", "science",
        "--topic", "portable report",
        "--form", str(installed["form"]),
    ]
    if include_roots:
        argv += [
            "--workspace-root", str(installed["engine"].parent / "workspaces"),
            "--profile-root", str(installed["engine"].parent / "profile"),
        ]
    argv += list(extra)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "single_root",
    [
        ("--workspace-root", "workspace-only"),
        ("--profile-root", "profile-only"),
    ],
)
def test_installed_surface_requires_both_explicit_roots(
    installed_module, single_root
):
    proc = _run(
        installed_module,
        single_root[0],
        str(installed_module["engine"].parent / single_root[1]),
        include_roots=False,
    )

    assert proc.returncode == 2
    missing = (
        "--profile-root"
        if single_root[0] == "--workspace-root"
        else "--workspace-root"
    )
    assert missing in proc.stderr
    assert not (installed_module["engine"].parent / "workspaces").exists()


@pytest.mark.parametrize("location", ["engine", "checkout"])
def test_profile_inside_engine_or_checkout_is_refused(
    installed_module, tmp_path, location
):
    if location == "engine":
        profile = installed_module["engine"] / "private-profile"
        named_root = installed_module["engine"]
    else:
        checkout = tmp_path / "other-checkout"
        checkout.mkdir()
        (checkout / "pyproject.toml").write_text(
            "[project]\nname = \"rigorloom\"\nversion = \"9.9\"\n",
            encoding="utf-8",
        )
        profile = checkout / ".local" / "profile"
        named_root = checkout

    proc = _run(
        installed_module,
        "--profile-root", str(profile),
    )

    assert proc.returncode == 2
    assert str(profile.resolve()) in proc.stderr
    assert str(named_root.resolve()) in proc.stderr
    assert not (installed_module["engine"].parent / "workspaces").exists()


def test_temp_root_scaffold_is_atomic_and_next_is_absolute(installed_module):
    proc = _run(installed_module)

    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    workspace_root = (installed_module["engine"].parent / "workspaces").resolve()
    workspace = Path(payload["workspace"])
    assert workspace.is_absolute()
    assert workspace_root in workspace.parents
    assert (workspace / "PIPELINE.md").is_file()
    assert (workspace / "NEXT_TASK.md").is_file()
    assert (installed_module["engine"].parent / "profile" / "resolved.json").is_file()
    pipeline = installed_module["pipeline"].resolve()
    assert pipeline.is_absolute()
    assert str(pipeline) in payload["next"]
    assert str(workspace) in payload["next"]
    assert not list(workspace_root.glob(".creating-*"))


def test_binary_hwp_remains_a_portable_refusal(installed_module):
    hwp = installed_module["engine"].parent / "binary.hwp"
    hwp.write_bytes(b"not opened")
    installed_module["form"] = hwp

    proc = _run(installed_module)

    assert proc.returncode == 3
    assert "hwp_ingress.py" in proc.stderr
    assert not (installed_module["engine"].parent / "workspaces").exists()


def test_registry_discovers_new_report_on_enabled_report_module(tmp_path):
    if str(PIPELINE_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(PIPELINE_SCRIPTS))
    from module_registry import ModuleRegistry

    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\nenabled: [style, report]\n",
        encoding="utf-8",
    )
    registry = ModuleRegistry(
        REPO_ROOT / "modules",
        enabled_file=enabled,
        version="0.17.0",
        pyproject=REPO_ROOT / "pyproject.toml",
    )

    rows = registry.enabled_cli()
    new_report = [row for row in rows if row["command"] == "new-report"]
    assert len(new_report) == 1
    assert new_report[0]["module"] == "report"
    assert Path(new_report[0]["script"]).resolve() == MODULE_SOURCE.resolve()


def test_checkout_shim_delegates_and_adds_only_omitted_defaults(monkeypatch):
    shim = _load("_report_scaffold_checkout_shim", SHIM_SOURCE)
    registered = REPO_ROOT / "modules" / "report" / "scripts" / "new_report.py"
    calls: list[list[str]] = []

    def fake_run(argv):
        calls.append([str(item) for item in argv])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(shim, "_module_cli_script", lambda command: registered)
    monkeypatch.setattr(shim.subprocess, "run", fake_run)
    base = [
        "--slug", "shim", "--subject", "science",
        "--topic", "topic", "--form", "form.hwpx",
    ]

    assert shim.main(base) == 0
    assert calls[0][:2] == [sys.executable, str(registered)]
    forwarded = calls[0][2:]
    assert forwarded.count("--workspace-root") == 1
    assert forwarded.count("--profile-root") == 1
    assert str(REPO_ROOT / "workspaces") in forwarded
    assert str(REPO_ROOT / ".local" / "personalization") in forwarded

    calls.clear()
    explicit_workspace = REPO_ROOT.parent / "explicit-workspace"
    explicit_profile = REPO_ROOT.parent / "explicit-profile"
    assert shim.main([
        *base,
        f"--workspace-root={explicit_workspace}",
        "--profile-root", str(explicit_profile),
    ]) == 0
    forwarded = calls[0][2:]
    assert not any(
        token == "--workspace-root" for token in forwarded
    )
    assert forwarded.count("--profile-root") == 1
    assert str(REPO_ROOT / "workspaces") not in forwarded
    assert str(REPO_ROOT / ".local" / "personalization") not in forwarded
