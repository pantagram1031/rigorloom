"""Focused regression tests for the shared child evidence extension."""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnostic_candidate_core as core  # noqa: E402


def test_run_child_capture_evidence_is_hash_and_count_only() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(bytes((118,101,114,115,105,111,110,10))); "
        "sys.stderr.buffer.write(bytes((110,111,105,115,101,10)))"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", script], timeout=5.0,
        return_evidence=True,
    )
    code, timed_out, overflow, evidence = result
    assert code == 0
    assert timed_out is False
    assert overflow is False
    assert evidence == {
        "output": {"sha256": hashlib.sha256(b"version\n").hexdigest(),
                   "bytes": len(b"version\n")},
        "error": {"sha256": hashlib.sha256(b"noise\n").hexdigest(),
                  "bytes": len(b"noise\n")},
    }
    assert core.run_child_capture(
        [sys.executable, "-c", "pass"], timeout=5.0
    ) == (0, False, False)


def _pid_is_live(pid: int) -> bool:
    if os.name == "nt":
        # ``os.kill(pid, 0)`` maps to an unsupported Windows signal and
        # raises WinError 87 even for a valid PID.  Query the process handle
        # instead so the cleanup assertion is meaningful on Windows too.
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_uint32()
        try:
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    if os.name != "nt":
        try:
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            if any(line.startswith("State:") and "\tZ" in line
                       for line in status.splitlines()):
                return False
        except OSError:
            pass
    return True


def test_run_child_capture_cleans_ordinary_grandchild_cross_platform(tmp_path: Path):
    pid_path = tmp_path / "ordinary-grandchild.pid"
    child = (
        "import os,time; "
        f"open({str(pid_path)!r}, 'w').write(str(os.getpid())); "
        "time.sleep(30)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(0.3)"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", parent], timeout=5.0, return_evidence=True)
    assert result[:3] == (0, False, False), result[:3]
    for _ in range(100):
        if pid_path.exists():
            break
        time.sleep(0.01)
    assert pid_path.exists()
    pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        assert not _pid_is_live(pid)
    finally:
        if _pid_is_live(pid):
            if os.name == "nt":
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
                if handle:
                    try:
                        ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass


def test_run_child_capture_posix_process_group_boundary_has_no_live_escape(
        tmp_path: Path):
    if os.name == "nt":
        import pytest
        pytest.skip("setsid process-group boundary is POSIX-specific")
    record_path = tmp_path / "setsid-grandchild.txt"
    child = (
        "import os,time; os.setsid(); "
        f"open({str(record_path)!r}, 'w').write(','.join(map(str, "
        "(os.getpid(), os.getsid(0), os.getpgrp(), "
        "int(os.environ['PARENT_PGRP']))))); "
        "time.sleep(0.2)"
    )
    parent = (
        "import os,subprocess,sys,time; "
        "env=dict(os.environ, PARENT_PGRP=str(os.getpgrp())); "
        f"subprocess.Popen([sys.executable, '-c', {child!r}], env=env); "
        "time.sleep(0.4)"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", parent], timeout=5.0, return_evidence=True)
    assert result[:3] == (0, False, False), result[:3]
    for _ in range(100):
        if record_path.exists():
            break
        time.sleep(0.01)
    assert record_path.exists()
    pid, session, process_group, parent_group = map(
        int, record_path.read_text(encoding="utf-8").split(","))
    assert session == process_group
    assert session != parent_group
    assert not _pid_is_live(pid)
