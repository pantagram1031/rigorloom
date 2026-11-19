# -*- coding: utf-8 -*-
"""The native shell gates the bundled test agent like the browser bridge does.

``rt_ui`` refuses ``/api/run-mock-agent`` and a mock agent-host turn unless
``RIGORLOOM_DEV_MOCK_AGENT`` is on or the ``devMockAgent`` preference is true.
The Tauri commands ``run_mock_agent`` and ``agent_host_run`` launched the same
provider with no check (S-WP0 finding 10). Building the Tauri app is out of
reach for a unit test, so the rule lives in a dependency-free module
(``desktop/src-tauri/src/devgate.rs``) whose own tests run under plain
``rustc --test``, and the two commands are checked to call it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TAURI_SRC = REPO / "desktop" / "src-tauri" / "src"
MAIN_RS = TAURI_SRC / "main.rs"
DEVGATE_RS = TAURI_SRC / "devgate.rs"


def _command_body(source: str, name: str) -> str:
    match = re.search(rf"fn {name}\(.*?\n}}\n", source, re.S)
    assert match, f"{name} not found in main.rs"
    return match.group(0)


def test_native_launch_commands_check_the_developer_setting():
    source = MAIN_RS.read_text(encoding="utf-8")
    assert DEVGATE_RS.is_file()
    assert "mod devgate;" in source
    run_mock = _command_body(source, "run_mock_agent")
    assert "require_mock_allowed(&app)?" in run_mock
    host_run = _command_body(source, "agent_host_run")
    assert "provider_needs_dev_setting(&provider)" in host_run
    assert "require_mock_allowed(&app)?" in host_run
    # The check comes before anything is spawned.
    assert host_run.index("require_mock_allowed") < host_run.index("agenthost::run_turn")
    assert run_mock.index("require_mock_allowed") < run_mock.index("Command::new")
    status = _command_body(source, "agent_host_status")
    assert '"mockAllowed"' in status


def test_the_native_gate_reads_the_same_switches_as_the_bridge():
    import sys
    sys.path.insert(0, str(REPO / "runtime" / "scripts"))
    import rt_ui

    gate = DEVGATE_RS.read_text(encoding="utf-8")
    assert f'"{rt_ui.DEV_MOCK_AGENT_ENV}"' in gate
    assert f'"{rt_ui.DEV_MOCK_AGENT_PREF}"' in gate


def test_devgate_unit_tests_pass_under_rustc(tmp_path):
    rustc = shutil.which("rustc")
    if rustc is None:
        pytest.skip("rustc is not installed")
    binary = tmp_path / "devgate-tests"
    built = subprocess.run([rustc, "--edition", "2021", "--test", str(DEVGATE_RS),
                            "-o", str(binary)], capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "3 passed" in ran.stdout
