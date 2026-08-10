#!/usr/bin/env python3
"""Strictly quarantined ``rhwp`` HWP5 diagnostic-candidate runner.

This is deliberately separate from :mod:`hwp_ingress`: it never publishes a
canonical HWPX and never participates in document-backend or submission
receipts.  The only destination it can create is a caller-selected diagnostic
root/run-id pair containing ``candidate.hwpx`` and ``receipt.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

try:
    import hwp_ingress as _ingress
except ImportError:  # pragma: no cover - direct package import fallback
    from pipeline.scripts import hwp_ingress as _ingress


SCHEMA = "rigorloom/hwp-diagnostic-candidate/v1"
ADAPTER = "rhwp"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
MAX_BINARY_BYTES = 256 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class DiagnosticError(Exception):
    """Expected fail-closed refusal with a closed reason token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _empty_source() -> dict[str, Any]:
    return {
        "format": "hwp", "version": None, "bytes": None,
        "sha256": None, "compressed": None, "security_flags": [],
    }


def _execution(state: str, binary_sha256: str | None = None,
               exit_code: int | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "binary_sha256": binary_sha256,
        "exit_code": exit_code,
    }


def _base(*, status: str, reason: str, source: dict[str, Any] | None = None,
          execution: dict[str, Any] | None = None,
          output: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "adapter": ADAPTER,
        "source": source or _empty_source(),
        "execution": execution or _execution("not_run"),
        "comparison": {
            "state": "unknown",
            "method": "none",
            "reason": "independent_oracle_not_run",
        },
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
        "output": output or {"state": "none"},
    }


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise DiagnosticError("run_id_invalid")
    return value


def _validate_pin(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise DiagnosticError("rhwp_unpinned")
    pin = value.casefold()
    if SHA256_RE.fullmatch(pin) is None:
        raise DiagnosticError("rhwp_pin_invalid")
    return pin


def _validate_timeout(value: float) -> float:
    try:
        return _ingress._validate_timeout(value)
    except (_ingress.IngressError, TypeError, ValueError, OverflowError):
        raise DiagnosticError("timeout_invalid")


def _read_binary_once(path: Path) -> tuple[bytes, str, int]:
    try:
        data = _read_regular_once(path, MAX_BINARY_BYTES,
                                  "rhwp_binary_unavailable")
    except DiagnosticError:
        raise
    except (OSError, ValueError):
        raise DiagnosticError("rhwp_binary_unavailable")
    if not data:
        raise DiagnosticError("rhwp_binary_invalid")
    # The configured binary's mode is untrusted metadata.  Stage with a fixed
    # owner-only executable mode rather than propagating setuid/setgid/sticky,
    # group, or world bits into the diagnostic snapshot.
    return data, hashlib.sha256(data).hexdigest(), 0o700


def _read_regular_once(path: Path, max_bytes: int, reason: str) -> bytes:
    """Read one bounded regular file without following a replaceable path."""
    try:
        before = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & reparse):
            raise DiagnosticError(reason)
        if before.st_size < 0 or before.st_size > max_bytes:
            raise DiagnosticError("file_too_large")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK") and os.name != "nt":
            flags |= os.O_NONBLOCK
        fd = os.open(str(path), flags)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode)
                    or getattr(opened, "st_file_attributes", 0) & reparse
                    or (getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0))
                    != (getattr(before, "st_dev", 0), getattr(before, "st_ino", 0))
                    or opened.st_size != before.st_size):
                raise DiagnosticError(reason)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DiagnosticError("file_too_large")
                chunks.append(chunk)
            after = os.fstat(fd)
            if (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    after.st_size) != (getattr(opened, "st_dev", 0),
                                       getattr(opened, "st_ino", 0), total):
                raise DiagnosticError(reason)
            return b"".join(chunks)
        finally:
            os.close(fd)
    except DiagnosticError:
        raise
    except (OSError, ValueError, TypeError):
        raise DiagnosticError(reason)


def _hash_binary(path: Path) -> str:
    try:
        data = _read_regular_once(path, MAX_BINARY_BYTES, "rhwp_binary_drift")
    except (DiagnosticError, OSError, ValueError):
        raise DiagnosticError("rhwp_binary_drift")
    if not data:
        raise DiagnosticError("rhwp_binary_drift")
    return hashlib.sha256(data).hexdigest()


def _read_source(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        if path.suffix.casefold() != ".hwp":
            raise DiagnosticError("extension_not_hwp")
        data = _read_regular_once(path, _ingress.MAX_INPUT_BYTES,
                                  "input_unavailable")
        source = _ingress.parse_hwp_bytes(data)
    except _ingress.IngressError as exc:
        raise DiagnosticError(exc.reason)
    except DiagnosticError as exc:
        if exc.reason == "file_too_large":
            raise DiagnosticError("input_too_large")
        raise
    return data, source.descriptor()


def _hash_source(path: Path) -> str:
    try:
        if path.suffix.casefold() != ".hwp":
            raise DiagnosticError("source_changed")
        data = _read_regular_once(path, _ingress.MAX_INPUT_BYTES,
                                  "source_changed")
        return hashlib.sha256(data).hexdigest()
    except (DiagnosticError, _ingress.IngressError, OSError, ValueError):
        raise DiagnosticError("source_changed")


def _configure_windows_job(proc):
    """Assign a suspended child to a kill-on-close Job and resume its thread."""
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    dword = ctypes.c_uint32
    boolean = ctypes.c_int
    kernel.CreateJobObjectW.argtypes = [handle, ctypes.c_wchar_p]
    kernel.CreateJobObjectW.restype = handle
    kernel.SetInformationJobObject.argtypes = [handle, ctypes.c_int,
                                               ctypes.c_void_p, dword]
    kernel.SetInformationJobObject.restype = boolean
    kernel.AssignProcessToJobObject.argtypes = [handle, handle]
    kernel.AssignProcessToJobObject.restype = boolean
    kernel.TerminateJobObject.argtypes = [handle, dword]
    kernel.TerminateJobObject.restype = boolean
    kernel.CloseHandle.argtypes = [handle]
    kernel.CloseHandle.restype = boolean
    kernel.CreateToolhelp32Snapshot.argtypes = [dword, dword]
    kernel.CreateToolhelp32Snapshot.restype = handle
    kernel.Thread32First.argtypes = [handle, ctypes.c_void_p]
    kernel.Thread32First.restype = boolean
    kernel.Thread32Next.argtypes = [handle, ctypes.c_void_p]
    kernel.Thread32Next.restype = boolean
    kernel.OpenThread.argtypes = [dword, boolean, dword]
    kernel.OpenThread.restype = handle
    kernel.ResumeThread.argtypes = [handle]
    kernel.ResumeThread.restype = dword
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW")

    class BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JobLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit),
                    ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    limits = JobLimits()
    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    limits.BasicLimitInformation.LimitFlags = 0x2000
    if not kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise OSError("SetInformationJobObject")
    if not kernel.AssignProcessToJobObject(job, ctypes.c_void_p(proc._handle)):
        kernel.CloseHandle(job)
        raise OSError("AssignProcessToJobObject")

    # Popen does not expose the primary thread handle.  Enumerate the still
    # suspended owner thread before allowing it to run; no grandchild can
    # spawn before Job assignment.
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)
        raise OSError("CreateToolhelp32Snapshot")

    class ThreadEntry(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32),
                    ("cntUsage", ctypes.c_uint32),
                    ("th32ThreadID", ctypes.c_uint32),
                    ("th32OwnerProcessID", ctypes.c_uint32),
                    ("tpBasePri", ctypes.c_long),
                    ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", ctypes.c_uint32)]

    entry = ThreadEntry()
    entry.dwSize = ctypes.sizeof(entry)
    found = None
    first = kernel.Thread32First(snapshot, ctypes.byref(entry))
    while first:
        if entry.th32OwnerProcessID == proc.pid:
            found = entry.th32ThreadID
            break
        if not kernel.Thread32Next(snapshot, ctypes.byref(entry)):
            break
    kernel.CloseHandle(snapshot)
    if found is None:
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)
        raise OSError("primary thread unavailable")
    thread_handle = kernel.OpenThread(0x0002, False, found)  # THREAD_SUSPEND_RESUME
    if not thread_handle:
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)
        raise OSError("OpenThread")
    try:
        if kernel.ResumeThread(thread_handle) == 0xFFFFFFFF:
            kernel.TerminateJobObject(job, 1)
            kernel.CloseHandle(job)
            raise OSError("ResumeThread")
    finally:
        kernel.CloseHandle(thread_handle)
    return job, kernel


def _terminate_windows_descendants(parent_pid: int, kernel=None) -> None:
    """Terminate only the process tree rooted at ``parent_pid``.

    A Job normally owns the tree, but nested-job restrictions and third-party
    launchers can make ``TerminateJobObject`` report success while a child
    process still has an inherited pipe.  The Toolhelp walk is deliberately
    scoped to descendants of this invocation; it never uses ``taskkill`` or a
    global process-name match.
    """
    import ctypes

    own_kernel = kernel is None
    if kernel is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    boolean = ctypes.c_int
    dword = ctypes.c_uint32
    for name, argtypes, restype in (
        ("CreateToolhelp32Snapshot", [dword, dword], handle),
        ("Process32FirstW", [handle, ctypes.c_void_p], boolean),
        ("Process32NextW", [handle, ctypes.c_void_p], boolean),
        ("OpenProcess", [dword, boolean, dword], handle),
        ("TerminateProcess", [handle, dword], boolean),
        ("CloseHandle", [handle], boolean),
    ):
        fn = getattr(kernel, name)
        fn.argtypes = argtypes
        fn.restype = restype

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        rows: list[tuple[int, int]] = []
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)

    descendants: set[int] = set()
    frontier = {int(parent_pid)}
    while frontier:
        children = {pid for pid, ppid in rows if ppid in frontier and pid != parent_pid}
        children -= descendants
        descendants.update(children)
        frontier = children
    # Kill deepest descendants first, then the direct child if it is still
    # present.  OpenProcess is scoped to these exact PIDs and no stale-name
    # process can be selected.
    for pid in sorted(descendants, reverse=True):
        process = kernel.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if process:
            try:
                kernel.TerminateProcess(process, 1)
            finally:
                kernel.CloseHandle(process)

    if own_kernel:
        # ``kernel`` is a module handle, not an owned OS handle; there is no
        # close operation for the DLL reference itself.
        del kernel


def _run_child_capture(argv: list[str], *, timeout: float,
                       cwd: Path | None = None):
    """Run one child with bounded output and an isolated staging cwd.

    This local seam intentionally mirrors the ingress bounded-child contract
    while adding ``cwd``: an adapter must not be able to leave logs or
    sidecars in the caller's repository/current directory.  Tests replace
    this function, keeping process execution deterministic.
    """
    timeout = _validate_timeout(timeout)
    job = None
    job_kernel = None
    windows_suspended = os.name == "nt"
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(cwd) if cwd is not None else None,
            start_new_session=(os.name != "nt"),
            creationflags=((getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                            | 0x00000004) if windows_suspended else 0),
        )
    except (OSError, ValueError, TypeError):
        return -1, False, False
    if os.name == "nt":
        try:
            job, job_kernel = _configure_windows_job(proc)
        except (OSError, AttributeError, TypeError, ValueError):
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if job and job_kernel is not None:
                job_kernel.CloseHandle(job)
            return -1, False, False
    stdout_total = [0]
    stderr_total = [0]
    overflow = [False]
    stop = threading.Event()

    def drain(pipe, total):
        try:
            while not stop.is_set():
                chunk = pipe.read(65536)
                if not chunk:
                    return
                total[0] += len(chunk)
                if total[0] > _ingress.MAX_CHILD_OUTPUT_BYTES:
                    overflow[0] = True
                    stop.set()
                    return
        except OSError:
            return

    threads = [threading.Thread(target=drain, args=(proc.stdout, stdout_total), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, stderr_total), daemon=True)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    def kill_tree() -> None:
        if job and job_kernel is not None:
            try:
                job_kernel.TerminateJobObject(job, 1)
            except (OSError, AttributeError):
                pass
            try:
                _terminate_windows_descendants(proc.pid, job_kernel)
            except (OSError, AttributeError, TypeError, ValueError):
                pass
            try:
                proc.kill()
            except OSError:
                pass
            return
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                return
            except (OSError, ProcessLookupError):
                pass
        try:
            proc.kill()
        except OSError:
            pass

    while proc.poll() is None:
        if overflow[0]:
            kill_tree()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            kill_tree()
            break
        time.sleep(0.01)
    try:
        code = proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        kill_tree()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        code = -1
    # A well-behaved adapter may still leave descendants holding the output
    # pipes (or a handle to the staged output) after its direct process exits.
    # Contain those descendants before returning to the publication path.  On
    # POSIX the process group is owned by this invocation; on Windows the Job
    # owns the complete suspended/resumed tree.
    if not timed_out and not overflow[0]:
        kill_tree()
    stop.set()
    for thread in threads:
        thread.join(timeout=1)
    if job and job_kernel is not None:
        try:
            job_kernel.CloseHandle(job)
        except OSError:
            pass
    return code, timed_out, overflow[0]


def _write_bytes(path: Path, data: bytes) -> None:
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise DiagnosticError("run_exists")
    except OSError:
        raise DiagnosticError("diagnostic_write_failed")


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes(path, (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode("utf-8"))


def _node_identity(path: Path) -> tuple[int, int, int, int, int, str]:
    try:
        info = path.lstat()
        digest = ""
        if stat.S_ISREG(info.st_mode):
            data = _read_regular_once(
                path, _ingress.MAX_HWPX_ARCHIVE_BYTES,
                "diagnostic_publish_failed")
            digest = hashlib.sha256(data).hexdigest()
    except (DiagnosticError, OSError, ValueError, TypeError):
        raise DiagnosticError("diagnostic_publish_failed")
    return (
        getattr(info, "st_dev", 0), getattr(info, "st_ino", 0),
        getattr(info, "st_size", 0), getattr(info, "st_mtime_ns", 0),
        getattr(info, "st_ctime_ns", 0), digest,
    )


def _same_file_identity(
        actual: tuple[int, int, int, int, int, str],
        expected: tuple[int, int, int, int, int, str]) -> bool:
    """Compare a file identity while allowing hard-link ctime churn.

    Creating a hard link updates the inode ctime on POSIX/Windows.  The
    remaining identity fields include device/inode, size, mtime and a full
    content digest, so an in-place overwrite or path swap still fails closed.
    """
    return (actual[0], actual[1], actual[2], actual[3], actual[5]) == (
        expected[0], expected[1], expected[2], expected[3], expected[5])


def _remove_owned(path: Path, identity: tuple[int, int, int, int, int, str] | None) -> bool:
    if identity is None:
        return False
    try:
        info = path.lstat()
        actual = _node_identity(path)
        if (_same_file_identity(actual, identity)
                and stat.S_ISREG(info.st_mode)):
            try:
                path.chmod(0o600)
            except OSError:
                pass
            path.unlink()
            return True
    except (DiagnosticError, OSError):
        return False
    return False


def _remove_owned_dir(path: Path, identity: tuple[int, int, int, int, int, str] | None) -> None:
    if identity is None:
        return
    try:
        info = path.lstat()
        if (identity is not None and stat.S_ISDIR(info.st_mode)
                and _node_identity(path) == identity):
            if any(path.iterdir()):
                return
            path.rmdir()
    except (DiagnosticError, OSError):
        pass


def _rollback_publication(
        run_path: Path,
        reserved_identity: tuple[int, int, int, int, int, str] | None,
        receipt_target: Path,
        receipt_identity: tuple[int, int, int, int, int, str] | None,
        candidate_target: Path,
        candidate_identity: tuple[int, int, int, int, int, str] | None,
        token_target: Path | None = None,
        token_identity: tuple[int, int, int, int, int, str] | None = None) -> None:
    """Remove only our files, then rebind the reserved directory identity."""
    _remove_owned(receipt_target, receipt_identity)
    _remove_owned(candidate_target, candidate_identity)
    if token_target is None or token_identity is None:
        return
    if not _remove_owned(token_target, token_identity):
        return
    if reserved_identity is None:
        return
    try:
        current = _node_identity(run_path)
    except DiagnosticError:
        return
    # A swapped directory is never removed.  Own link/unlink operations can
    # update mtime/ctime, so the post-cleanup identity is the one that is
    # checked by _remove_owned_dir; device/inode must still match reservation.
    if current[:2] != reserved_identity[:2]:
        return
    _remove_owned_dir(run_path, current)


def _validate_receipt_shape(payload: dict[str, Any], *, output: Path | None = None,
                            run_id: str | None = None) -> dict[str, Any]:
    if set(payload) != {
            "schema", "status", "reason", "adapter", "source", "execution",
            "comparison", "render", "proof_grade", "submission_grade", "output"}:
        raise DiagnosticError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "candidate"
            or payload.get("reason") != "candidate_created"
            or payload.get("adapter") != ADAPTER
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False
            or payload.get("render") != {"state": "not_run"}
            or payload.get("comparison") != {
                "state": "unknown", "method": "none",
                "reason": "independent_oracle_not_run"}):
        raise DiagnosticError("receipt_state_invalid")
    source = payload.get("source")
    if (not isinstance(source, dict) or set(source) != {
            "format", "version", "bytes", "sha256", "compressed", "security_flags"}
            or source.get("format") != "hwp"
            or not isinstance(source.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", source["version"]) is None
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not isinstance(source.get("sha256"), str)
            or SHA256_RE.fullmatch(source["sha256"]) is None
            or not isinstance(source.get("compressed"), bool)
            or source.get("security_flags") != []):
        raise DiagnosticError("receipt_source_invalid")
    execution = payload.get("execution")
    if (not isinstance(execution, dict) or set(execution) != {
            "state", "binary_sha256", "exit_code"}
            or execution.get("state") != "succeeded"
            or SHA256_RE.fullmatch(execution.get("binary_sha256", "")) is None
            or execution.get("exit_code") != 0):
        raise DiagnosticError("receipt_execution_invalid")
    recorded = payload.get("output")
    if (not isinstance(recorded, dict) or set(recorded) != {
            "state", "path", "sha256", "bytes", "counts"}
            or recorded.get("state") != "quarantined"
            or not isinstance(recorded.get("path"), str)):
        raise DiagnosticError("receipt_output_invalid")
    if (run_id is None or Path(recorded["path"]).is_absolute()
            or recorded["path"] != f"{run_id}/candidate.hwpx"
            or SHA256_RE.fullmatch(recorded.get("sha256", "")) is None
            or isinstance(recorded.get("bytes"), bool)
            or not isinstance(recorded.get("bytes"), int)
            or recorded["bytes"] <= 0):
        raise DiagnosticError("receipt_output_invalid")
    counts = recorded.get("counts")
    if (not isinstance(counts, dict) or set(counts) != {"tables", "pictures", "equations"}
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in counts.values())):
        raise DiagnosticError("receipt_output_invalid")
    if output is not None:
        actual = _validate_hwpx_current(output)
        if (actual["bytes"] != recorded["bytes"]
                or actual["sha256"] != recorded["sha256"]
                or actual["counts"] != counts):
            raise DiagnosticError("receipt_output_mismatch")
    return payload


def _validate_hwpx_current(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError:
        raise DiagnosticError("rhwp_output_missing")
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise DiagnosticError("hwpx_invalid")
    try:
        before = _node_identity(path)
        if before[2] <= 0 or before[2] > _ingress.MAX_HWPX_ARCHIVE_BYTES:
            raise DiagnosticError("hwpx_invalid")
        result = _ingress._validate_hwpx(path)
        after = _node_identity(path)
        if not _same_file_identity(after, before):
            raise DiagnosticError("hwpx_invalid")
        return result
    except _ingress.IngressError as exc:
        if exc.reason == "hwpx_missing":
            raise DiagnosticError("rhwp_output_missing")
        raise DiagnosticError("hwpx_invalid")
    except (OSError, ValueError, RuntimeError, KeyError):
        raise DiagnosticError("hwpx_invalid")


def _load_receipt(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DiagnosticError("receipt_duplicate_key")
            result[key] = value
        return result

    try:
        raw = _read_regular_once(path, MAX_RECEIPT_BYTES, "receipt_invalid")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except DiagnosticError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DiagnosticError("receipt_invalid")
    if not isinstance(payload, dict):
        raise DiagnosticError("receipt_invalid")
    return payload


def _prepare_root(path: Path) -> Path:
    try:
        root_input = path.expanduser()
        info = root_input.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse):
            raise DiagnosticError("diagnostic_root_invalid")
        probe = root_input
        while True:
            ancestor = probe.lstat()
            if (stat.S_ISLNK(ancestor.st_mode)
                    or getattr(ancestor, "st_file_attributes", 0) & reparse):
                raise DiagnosticError("diagnostic_root_invalid")
            if probe == probe.parent:
                break
            probe = probe.parent
        root = root_input.resolve(strict=True)
        if (root.name.casefold() != "hwp-diagnostic"
                or any(part.casefold() == "output" for part in root.parts)):
            raise DiagnosticError("diagnostic_root_invalid")
        return root
    except DiagnosticError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise DiagnosticError("diagnostic_root_invalid")


def _capture_root_guard(supplied: Path, resolved: Path) -> dict[str, Any]:
    """Bind the supplied path and every existing ancestor to full identities."""
    supplied_abs = supplied.expanduser().absolute()
    rows: list[tuple[Path, tuple[int, int, int, int, int, str], bool]] = []
    probe = supplied_abs
    is_root = True
    while True:
        rows.append((probe, _node_identity(probe), is_root))
        if probe == probe.parent:
            break
        probe = probe.parent
        is_root = False
    return {"supplied": supplied_abs, "resolved": resolved, "rows": rows}


def _check_root_guard(guard: dict[str, Any], *, refresh: bool = False) -> None:
    rows = guard["rows"]
    current: list[tuple[Path, tuple[int, int, int, int, int, str], bool]] = []
    try:
        for path, expected, is_root in rows:
            info = path.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & reparse):
                raise DiagnosticError("diagnostic_root_changed")
            actual = _node_identity(path)
            if ((is_root and not refresh and actual != expected)
                    or (is_root and refresh and actual[:2] != expected[:2])
                    or (not is_root and actual[:2] != expected[:2])):
                raise DiagnosticError("diagnostic_root_changed")
            current.append((path, actual, is_root))
    except (DiagnosticError, OSError, RuntimeError, ValueError, TypeError):
        raise DiagnosticError("diagnostic_root_changed")
    if refresh:
        guard["rows"] = current


def _require_regular(path: Path, reason: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise DiagnosticError(reason)
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_nlink", 1) != 1:
        raise DiagnosticError(reason)


def run_diagnostic(input_path: str | Path, *, diagnostic_root: str | Path,
                   run_id: str, rhwp: str | Path,
                   rhwp_sha256: str | None, timeout: float = 60.0) -> dict[str, Any]:
    """Create one quarantined rhwp candidate or return a refusal payload."""
    source_descriptor: dict[str, Any] | None = None
    binary_digest: str | None = None
    execution = _execution("not_run")
    try:
        run_id = _validate_run_id(run_id)
        pin = _validate_pin(rhwp_sha256)
        timeout = _validate_timeout(timeout)
        source_path = Path(input_path)
        binary_path = Path(rhwp)
        supplied_root = Path(diagnostic_root)
        root = _prepare_root(supplied_root)
        root_guard = _capture_root_guard(supplied_root, root)
        _check_root_guard(root_guard)
        source_resolved = source_path.expanduser().resolve()
        binary_resolved = binary_path.expanduser().resolve()
        if (source_resolved == binary_resolved or source_resolved == root
                or binary_resolved == root):
            raise DiagnosticError("paths_not_distinct")
        run_path = root / run_id
        if run_path.exists():
            raise DiagnosticError("run_exists")
        source_data, source_descriptor = _read_source(source_path)
        binary_data, binary_digest, binary_mode = _read_binary_once(binary_path)
        execution = _execution("not_run", binary_digest, None)
        if binary_digest != pin:
            raise DiagnosticError("rhwp_hash_mismatch")
        # All staging remains inside a hidden sibling and is removed on every
        # refusal.  The binary and source are immutable snapshots for rhwp.
        with tempfile.TemporaryDirectory(prefix=".t86-", dir=str(root)) as temp:
            temp_dir = Path(temp)
            # TemporaryDirectory creation legitimately updates the root
            # directory's mtime/ctime; refresh only after the pre-use check.
            _check_root_guard(root_guard, refresh=True)
            staged_source = temp_dir / "input.hwp"
            suffix = binary_path.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", binary_path.suffix) else ""
            staged_binary = temp_dir / ("rhwp" + suffix)
            staged_output = temp_dir / "candidate.hwpx"
            _write_bytes(staged_source, source_data)
            _write_bytes(staged_binary, binary_data)
            try:
                staged_binary.chmod(binary_mode)
            except OSError:
                raise DiagnosticError("rhwp_binary_invalid")
            command = [str(staged_binary), "export-hwpx", str(staged_source),
                       str(staged_output), "--verify", "--verify-pages"]
            code, timed_out, overflow = _run_child_capture(
                command, timeout=timeout, cwd=temp_dir)
            if (type(code) is not int or type(timed_out) is not bool
                    or type(overflow) is not bool):
                execution = _execution("failed", binary_digest, None)
                raise DiagnosticError("rhwp_failed")
            execution = _execution("failed", binary_digest, code)
            if timed_out:
                raise DiagnosticError("rhwp_timeout")
            if overflow:
                raise DiagnosticError("rhwp_output_too_large")
            if code != 0:
                raise DiagnosticError("rhwp_failed")
            validated = _validate_hwpx_current(staged_output)
            if _hash_binary(binary_path) != pin or _hash_binary(staged_binary) != pin:
                raise DiagnosticError("rhwp_binary_drift")
            if _hash_source(source_path) != source_descriptor["sha256"]:
                raise DiagnosticError("source_changed")
            if _hash_source(staged_source) != source_descriptor["sha256"]:
                raise DiagnosticError("source_changed")

            publish_stage = temp_dir / "publish" / run_id
            publish_stage.mkdir(parents=True, exist_ok=False)
            staged_candidate = publish_stage / "candidate.hwpx"
            shutil.copyfile(staged_output, staged_candidate)
            # Revalidate the exact bytes that will be renamed into the run.
            final_validated = _validate_hwpx_current(staged_candidate)
            if final_validated != validated:
                raise DiagnosticError("rhwp_output_drift")
            output_record = {
                "state": "quarantined",
                "path": f"{run_id}/candidate.hwpx",
                "sha256": final_validated["sha256"],
                "bytes": final_validated["bytes"],
                "counts": final_validated["counts"],
            }
            execution = _execution("succeeded", pin, 0)
            payload = _base(status="candidate", reason="candidate_created",
                            source=source_descriptor, execution=execution,
                            output=output_record)
            _validate_receipt_shape(payload, output=staged_candidate, run_id=run_id)
            _write_receipt(publish_stage / "receipt.json", payload)
            # Reserve the final run directory exclusively, then publish the
            # receipt first and candidate last with exclusive hard links.  A
            # racing destination preserves its owner and removes no files.
            reserved_identity: tuple[int, int, int, int, int, str] | None = None
            receipt_identity: tuple[int, int, int, int, int, str] | None = None
            candidate_identity: tuple[int, int, int, int, int, str] | None = None
            token_target: Path | None = None
            token_identity: tuple[int, int, int, int, int, str] | None = None
            try:
                _check_root_guard(root_guard)
                os.mkdir(str(run_path))
                reserved_identity = _node_identity(run_path)
                _check_root_guard(root_guard, refresh=True)
                receipt_target = run_path / "receipt.json"
                candidate_target = run_path / "candidate.hwpx"
                token_target = run_path / (".t86-owner-" + secrets.token_hex(16))
                _write_bytes(token_target, secrets.token_bytes(32))
                token_identity = _node_identity(token_target)
                reserved_identity = _node_identity(run_path)
                staged_receipt = publish_stage / "receipt.json"
                receipt_identity = _node_identity(staged_receipt)
                _check_root_guard(root_guard)
                os.link(str(staged_receipt), str(receipt_target))
                reserved_identity = _node_identity(run_path)
                # Check the target after recording the source identity; if
                # this check faults, rollback can still unlink only our inode.
                if not _same_file_identity(_node_identity(receipt_target), receipt_identity):
                    raise DiagnosticError("diagnostic_publish_failed")
                target_receipt = _load_receipt(receipt_target)
                _validate_receipt_shape(target_receipt, output=staged_candidate,
                                        run_id=run_id)
                if not _same_file_identity(_node_identity(receipt_target), receipt_identity):
                    raise DiagnosticError("diagnostic_publish_failed")
                # Recheck every mutable input and the exact candidate bytes
                # after receipt creation and immediately before commit.
                if (_hash_binary(binary_path) != pin
                        or _hash_binary(staged_binary) != pin):
                    raise DiagnosticError("rhwp_binary_drift")
                if _hash_source(source_path) != source_descriptor["sha256"]:
                    raise DiagnosticError("source_changed")
                if _hash_source(staged_source) != source_descriptor["sha256"]:
                    raise DiagnosticError("source_changed")
                final_again = _validate_hwpx_current(staged_candidate)
                if final_again != final_validated:
                    raise DiagnosticError("rhwp_output_drift")
                staged_candidate.chmod(0o400)
                candidate_identity = _node_identity(staged_candidate)
                _check_root_guard(root_guard)
                os.link(str(staged_candidate), str(candidate_target))
                reserved_identity = _node_identity(run_path)
                if not _same_file_identity(_node_identity(candidate_target), candidate_identity):
                    raise DiagnosticError("diagnostic_publish_failed")
                target_receipt = _load_receipt(receipt_target)
                _validate_receipt_shape(target_receipt, output=candidate_target,
                                        run_id=run_id)
                if (not _same_file_identity(_node_identity(receipt_target), receipt_identity)
                        or not _same_file_identity(_node_identity(candidate_target), candidate_identity)):
                    raise DiagnosticError("diagnostic_publish_failed")
                _check_root_guard(root_guard)
                if not _remove_owned(token_target, token_identity):
                    raise DiagnosticError("diagnostic_publish_failed")
                # Token removal is the final commit marker.  There is no
                # fallible root/output check after it; the surrounding
                # temporary-directory cleanup cannot publish anything.
                return payload
            except FileExistsError:
                _rollback_publication(
                    run_path, reserved_identity,
                    receipt_target if 'receipt_target' in locals() else run_path / "receipt.json",
                    receipt_identity,
                    candidate_target if 'candidate_target' in locals() else run_path / "candidate.hwpx",
                    candidate_identity, token_target, token_identity)
                raise DiagnosticError("run_exists")
            except DiagnosticError:
                _rollback_publication(
                    run_path, reserved_identity,
                    receipt_target if 'receipt_target' in locals() else run_path / "receipt.json",
                    receipt_identity,
                    candidate_target if 'candidate_target' in locals() else run_path / "candidate.hwpx",
                    candidate_identity, token_target, token_identity)
                raise
            except OSError:
                _rollback_publication(
                    run_path, reserved_identity,
                    receipt_target if 'receipt_target' in locals() else run_path / "receipt.json",
                    receipt_identity,
                    candidate_target if 'candidate_target' in locals() else run_path / "candidate.hwpx",
                    candidate_identity, token_target, token_identity)
                raise DiagnosticError("diagnostic_publish_failed")
    except DiagnosticError as exc:
        return _base(status="refused", reason=exc.reason,
                     source=source_descriptor,
                     execution=execution)
    except (OSError, TypeError, ValueError, RuntimeError):
        return _base(status="refused", reason="diagnostic_io_failed",
                     source=source_descriptor, execution=execution)


def verify_diagnostic(diagnostic_root: str | Path, run_id: str) -> dict[str, Any]:
    try:
        run_id = _validate_run_id(run_id)
        supplied_root = Path(diagnostic_root)
        root = _prepare_root(supplied_root)
        root_guard = _capture_root_guard(supplied_root, root)
        _check_root_guard(root_guard)
        run_path = root / run_id
        _check_root_guard(root_guard)
        try:
            root_info = root.lstat()
            run_info = run_path.lstat()
        except OSError:
            raise DiagnosticError("receipt_invalid")
        if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
                or not stat.S_ISDIR(run_info.st_mode) or stat.S_ISLNK(run_info.st_mode)):
            raise DiagnosticError("receipt_invalid")
        try:
            entries = {entry.name for entry in run_path.iterdir()}
        except OSError:
            raise DiagnosticError("receipt_invalid")
        if entries != {"candidate.hwpx", "receipt.json"}:
            raise DiagnosticError("receipt_layout_invalid")
        candidate_path = run_path / "candidate.hwpx"
        receipt_path = run_path / "receipt.json"
        _require_regular(candidate_path, "receipt_invalid")
        _require_regular(receipt_path, "receipt_invalid")
        receipt = _load_receipt(receipt_path)
        return _validate_receipt_shape(receipt, output=candidate_path, run_id=run_id)
    except DiagnosticError as exc:
        return _base(status="refused", reason=exc.reason)
    except (OSError, TypeError, RuntimeError, ValueError):
        return _base(status="refused", reason="diagnostic_io_failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="quarantined rhwp HWP diagnostic candidate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="create one diagnostic candidate")
    run.add_argument("input")
    run.add_argument("--diagnostic-root", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--rhwp", required=True)
    run.add_argument("--rhwp-sha256", required=True)
    run.add_argument("--timeout", type=float, default=60.0)
    verify = sub.add_parser("verify", help="verify one diagnostic candidate receipt")
    verify.add_argument("--diagnostic-root", required=True)
    verify.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        payload = run_diagnostic(args.input, diagnostic_root=args.diagnostic_root,
                                 run_id=args.run_id, rhwp=args.rhwp,
                                 rhwp_sha256=args.rhwp_sha256, timeout=args.timeout)
    else:
        payload = verify_diagnostic(args.diagnostic_root, args.run_id)
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except (BrokenPipeError, OSError, UnicodeError):
        return EXIT_REFUSED
    return EXIT_OK if payload["status"] == "candidate" else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
