"""Run Desktop's isolated workspace tests when its declared tools are installed.

These exercise UI state and asynchronous ownership; they are not native GUI
or IME card evidence.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / "desktop"


def test_desktop_workspace_node_suite():
    node = shutil.which("node")
    if node is None or not (DESKTOP / "node_modules" / "typescript").is_dir():
        pytest.skip("Desktop Node and TypeScript dependencies are not installed")
    result = subprocess.run(
        [node, "--experimental-strip-types", "--test"],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
