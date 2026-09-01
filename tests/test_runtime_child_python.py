# -*- coding: utf-8 -*-
"""RIGORLOOM_CHILD_PYTHON: point engine children at a real interpreter.

``sys.executable`` is the wrong default for a packaged host — in a frozen
executable it IS the host, so every engine child re-launches the application.
The desktop sidecar worked around that with an argv convention; this override
removes the need for one.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from _runtime_client import (
    CORPUS_FORM,
    RuntimeClient,
    run_cli,
    runtime_scripts_on_path,
)

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_engine  # noqa: E402

SPAWN_TIMEOUT = 300.0
ENV = rt_codes.CHILD_PYTHON_ENV


def _source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


# --- resolution -------------------------------------------------------------

def test_without_the_override_children_use_sys_executable():
    facts = rt_engine.child_python_facts({})
    assert facts["path"] == sys.executable
    assert facts["source"] == "sys.executable"
    assert facts["overrideSet"] is False
    assert rt_engine.child_python({}) == sys.executable


def test_the_override_replaces_it():
    facts = rt_engine.child_python_facts({ENV: sys.executable})
    assert facts["source"] == "override"
    assert facts["overrideSet"] is True
    assert rt_engine.child_python({ENV: sys.executable}) == sys.executable


def test_an_empty_override_is_treated_as_unset():
    """A blank environment variable is a common accident, not a request."""
    for blank in ("", "   "):
        assert rt_engine.child_python({ENV: blank}) == sys.executable
        assert rt_engine.child_python_facts({ENV: blank})["overrideSet"] is False


# --- validation -------------------------------------------------------------

def test_an_unset_override_validates_quietly():
    facts = rt_engine.validate_child_python({})
    assert facts["overrideSet"] is False


def test_a_real_interpreter_validates_and_is_resolved():
    facts = rt_engine.validate_child_python({ENV: sys.executable})
    assert facts["overrideSet"] is True
    assert facts["path"]


def test_an_override_naming_nothing_is_refused(tmp_path):
    missing = tmp_path / "no-such-python.exe"
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_engine.validate_child_python({ENV: str(missing)})
    error = excinfo.value
    assert error.code == "child_python_invalid"
    assert error.data["env"] == ENV
    assert error.data["path"] == str(missing)
    assert "names no file" in error.message


def test_an_override_naming_a_directory_is_refused(tmp_path):
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_engine.validate_child_python({ENV: str(tmp_path)})
    assert excinfo.value.code == "child_python_invalid"


# --- at initialize ----------------------------------------------------------

def _serve(root, env_extra):
    """Start a server with a doctored environment and read one frame."""
    from _runtime_client import SERVE

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra)
    root.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(SERVE), "--entry", "host", "--root", str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env)
    try:
        proc.stdin.write((json.dumps({
            "kind": "request", "id": "i1", "method": "initialize",
            "params": {"protocolVersion": "0",
                       "client": {"name": "t", "version": "0"}}}) + "\n"
        ).encode("utf-8"))
        proc.stdin.flush()
        line = proc.stdout.readline()
        return json.loads(line.decode("utf-8"))
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)


def test_initialize_refuses_a_broken_override(tmp_path):
    """The operator meets this here, not twenty seconds into the first call."""
    frame = _serve(tmp_path / "root",
                   {ENV: str(tmp_path / "definitely-not-here")})
    assert frame["kind"] == "error"
    assert frame["error"]["code"] == "child_python_invalid"
    assert frame["error"]["data"]["env"] == ENV


def test_initialize_accepts_a_good_override_and_reports_it(tmp_path):
    frame = _serve(tmp_path / "root", {ENV: sys.executable})
    assert frame["kind"] == "response"
    child = frame["result"]["capabilities"]["childPython"]
    assert child["source"] == "override"
    assert child["env"] == ENV


def test_capabilities_report_the_default_when_nothing_is_set(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        capabilities = client.initialize()["result"]["capabilities"]
    child = capabilities["childPython"]
    assert child["env"] == ENV
    # the harness itself may set the override; either way the report is true
    assert child["source"] in ("sys.executable", "override")
    assert child["path"]


# --- it actually spawns children with it ------------------------------------

def test_engine_children_really_run_under_the_override(tmp_path, monkeypatch):
    """End to end: a document call under an override still inspects the form."""
    monkeypatch.setenv(ENV, sys.executable)
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    result = run_cli(root, "inspect", "--session", session, "--include", "summary")
    assert result.code == 0
    assert result.result["summary"]["fillTargetCount"] == 9


def test_a_broken_override_reaches_the_call_sites_not_just_initialize(
        tmp_path, monkeypatch):
    """Even bypassing initialize, a child cannot start under a bad interpreter."""
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    monkeypatch.setenv(ENV, str(tmp_path / "nope.exe"))
    result = run_cli(root, "inspect", "--session", session)
    assert result.code == 3
    assert result.error["code"] == "capability_unavailable"


def test_every_engine_spawn_goes_through_the_helper():
    """No call site may quietly keep using sys.executable."""
    source = (rt_engine.__file__)
    text = open(source, encoding="utf-8").read()
    body = text.split("def child_python_facts", 1)[1]
    assert "sys.executable, str(" not in body, (
        "an engine spawn still hardcodes sys.executable")
    assert body.count("child_python(), str(") >= 3
