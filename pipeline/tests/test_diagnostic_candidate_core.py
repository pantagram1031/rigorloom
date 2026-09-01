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

# A spawn bound here is a HANG detector, not a stopwatch (T134 — the T121
# class in a second spelling). These four calls assert ``timed_out is False``
# on healthy children, and the old ``timeout=5.0`` sat BELOW the measured
# loaded median cold spawn of 9.00s (tests/test_subprocess_bounds.py carries
# the measurement: idle median 2.76s, loaded median 9.00s, loaded max 36.46s)
# — so under load the bound killed a healthy child and the test flaked, while
# the floor guard reported the tree clean because its scanner only read
# ``subprocess.run(timeout=)`` and this bound is spelled through
# ``run_child_capture``. 120s matches the deliberately-generous-bound
# convention (engine/tests/test_com_backend_offline.py HANG_TIMEOUT): a child
# that trips it is hung, not slow.
HANG_TIMEOUT = 120.0



def test_run_child_capture_evidence_is_hash_and_count_only() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(bytes((118,101,114,115,105,111,110,10))); "
        "sys.stderr.buffer.write(bytes((110,111,105,115,101,10)))"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", script], timeout=HANG_TIMEOUT,
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
        [sys.executable, "-c", "pass"], timeout=HANG_TIMEOUT
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
    # T134: the parent must not exit until the grandchild has WRITTEN its pid.
    # A blind sleep(0.3) lost that race under load — a cold python grandchild
    # takes a loaded-median 9.00s to start (tests/test_subprocess_bounds.py),
    # so cleanup killed it before the pid existed and the file never appeared
    # no matter how long the test polled afterwards. The wait is bounded and
    # exits the moment the file exists, so the fast path costs milliseconds.
    parent = (
        "import os.path,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "end = time.time() + 60\n"
        f"while not os.path.exists({str(pid_path)!r}) and time.time() < end:\n"
        "    time.sleep(0.05)\n"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", parent], timeout=HANG_TIMEOUT, return_evidence=True)
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
    # T134: same handshake as the cross-platform test — wait for the record,
    # never a blind sleep (this arm runs on the POSIX CI runners, which are
    # loaded machines).
    parent = (
        "import os,os.path,subprocess,sys,time\n"
        "env = dict(os.environ, PARENT_PGRP=str(os.getpgrp()))\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], env=env)\n"
        "end = time.time() + 60\n"
        f"while not os.path.exists({str(record_path)!r}) and time.time() < end:\n"
        "    time.sleep(0.05)\n"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", parent], timeout=HANG_TIMEOUT, return_evidence=True)
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
