# -*- coding: utf-8 -*-
"""The Runtime owns the process tree behind every engine/checker child."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_engine  # noqa: E402


def test_process_cleanup_capability_keeps_the_claim_narrow():
    facts = rt_engine.process_containment_facts()
    expected = ("windows_job_kill_on_close_v1" if os.name == "nt"
                else "posix_process_group_v1")
    assert facts["processPolicy"] == expected
    assert facts["ordinaryDescendantCleanup"] == "established"
    assert facts["descendantContainment"] == "not_established"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job kill-on-close contract")
def test_runtime_parent_death_kills_its_child_before_a_late_write(tmp_path):
    """Killing Runtime must close its Job and kill the still-running child."""
    started = tmp_path / "started.txt"
    late = tmp_path / "late.txt"
    child_code = (
        "import pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text('started', encoding='ascii'); "
        "time.sleep(1.5); "
        "pathlib.Path(sys.argv[2]).write_text('escaped', encoding='ascii')"
    )
    controller_code = (
        "import json,sys; "
        f"sys.path.insert(0, {json.dumps(str(RUNTIME_SCRIPTS))}); "
        "import rt_engine; "
        "args=json.loads(sys.argv[1]); "
        "rt_engine.run_child(args, timeout=120)"
    )
    child_argv = [sys.executable, "-c", child_code, str(started), str(late)]
    controller = subprocess.Popen(
        [sys.executable, "-c", controller_code, json.dumps(child_argv)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 40
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert started.exists(), "the contained child never started"
    controller.kill()
    controller.wait(timeout=20)
    time.sleep(2.0)
    assert not late.exists(), "the Runtime child survived its parent"
