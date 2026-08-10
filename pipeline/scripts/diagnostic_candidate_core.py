"""Shared bounded primitives for quarantined diagnostic-candidate adapters.

This module has no document-format knowledge.  It owns only the security
boundaries that every diagnostic adapter needs: no-follow regular snapshots,
bounded child execution with process-tree containment, exclusive writes,
full file identities, root anchoring, and identity-safe rollback helpers.
Format-specific runners provide their own closed error class and validation
callbacks around these primitives.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Callable


__all__ = [
    "CoreError", "FileIdentity", "read_regular_once", "hash_regular",
    "write_bytes", "node_identity", "same_file_identity", "remove_owned",
    "remove_owned_dir", "rollback_publication", "publish_owner_token_pair",
    "publish_owner_token_receipt",
    "prepare_root", "capture_root_guard", "check_root_guard",
    "configure_windows_job", "terminate_windows_descendants",
    "run_child_capture",
]


class CoreError(Exception):
    """Expected fail-closed core refusal carrying a stable reason token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


FileIdentity = tuple[int, int, int, int, int, str]
NodeIdentity = Callable[[Path], FileIdentity]
RemoveOwned = Callable[[Path, FileIdentity | None], bool]


def read_regular_once(path: Path, max_bytes: int, reason: str) -> bytes:
    """Read one bounded regular file without following a replaceable path."""
    try:
        before = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & reparse):
            raise CoreError(reason)
        if before.st_size < 0 or before.st_size > max_bytes:
            raise CoreError("file_too_large")
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
                raise CoreError(reason)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CoreError("file_too_large")
                chunks.append(chunk)
            after = os.fstat(fd)
            if (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    after.st_size) != (getattr(opened, "st_dev", 0),
                                       getattr(opened, "st_ino", 0), total):
                raise CoreError(reason)
            return b"".join(chunks)
        finally:
            os.close(fd)
    except CoreError:
        raise
    except (OSError, ValueError, TypeError):
        raise CoreError(reason)


def hash_regular(path: Path, max_bytes: int, reason: str) -> str:
    data = read_regular_once(path, max_bytes, reason)
    if not data:
        raise CoreError(reason)
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes, *, exists_reason: str = "run_exists",
                write_reason: str = "diagnostic_write_failed") -> None:
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise CoreError(exists_reason)
    except OSError:
        raise CoreError(write_reason)


def node_identity(path: Path, *, read_once: Callable[[Path, int, str], bytes] = read_regular_once,
                  max_bytes: int = 64 * 1024 * 1024,
                  reason: str = "diagnostic_publish_failed") -> FileIdentity:
    try:
        info = path.lstat()
        digest = ""
        if stat.S_ISREG(info.st_mode):
            data = read_once(path, max_bytes, reason)
            digest = hashlib.sha256(data).hexdigest()
    except CoreError:
        raise
    except (OSError, ValueError, TypeError):
        raise CoreError(reason)
    return (
        getattr(info, "st_dev", 0), getattr(info, "st_ino", 0),
        getattr(info, "st_size", 0), getattr(info, "st_mtime_ns", 0),
        getattr(info, "st_ctime_ns", 0), digest,
    )


def same_file_identity(actual: FileIdentity, expected: FileIdentity) -> bool:
    """Compare identity while allowing ctime churn from hard-link creation."""
    return (actual[0], actual[1], actual[2], actual[3], actual[5]) == (
        expected[0], expected[1], expected[2], expected[3], expected[5])


def remove_owned(path: Path, identity: FileIdentity | None,
                 *, node_identity_fn: NodeIdentity = node_identity) -> bool:
    if identity is None:
        return False
    try:
        info = path.lstat()
        actual = node_identity_fn(path)
        if same_file_identity(actual, identity) and stat.S_ISREG(info.st_mode):
            try:
                path.chmod(0o600)
            except OSError:
                pass
            path.unlink()
            return True
    except (CoreError, OSError):
        return False
    return False


def remove_owned_dir(path: Path, identity: FileIdentity | None,
                     *, node_identity_fn: NodeIdentity = node_identity) -> None:
    if identity is None:
        return
    try:
        info = path.lstat()
        if (stat.S_ISDIR(info.st_mode)
                and node_identity_fn(path) == identity):
            if any(path.iterdir()):
                return
            path.rmdir()
    except (CoreError, OSError):
        pass


def rollback_publication(
        run_path: Path,
        reserved_identity: FileIdentity | None,
        receipt_target: Path,
        receipt_identity: FileIdentity | None,
        candidate_target: Path,
        candidate_identity: FileIdentity | None,
        token_target: Path | None = None,
        token_identity: FileIdentity | None = None,
        *,
        remove_owned_fn: RemoveOwned = remove_owned,
        node_identity_fn: NodeIdentity = node_identity,
        remove_owned_dir_fn: Callable[[Path, FileIdentity | None], None] = remove_owned_dir,
) -> None:
    """Remove only owned files, then rebind the reserved directory identity."""
    remove_owned_fn(receipt_target, receipt_identity)
    remove_owned_fn(candidate_target, candidate_identity)
    if token_target is None or token_identity is None:
        return
    if not remove_owned_fn(token_target, token_identity):
        return
    if reserved_identity is None:
        return
    try:
        current = node_identity_fn(run_path)
    except CoreError:
        return
    if current[:2] != reserved_identity[:2]:
        return
    remove_owned_dir_fn(run_path, current)


def publish_owner_token_pair(
        run_path: Path,
        publish_stage: Path,
        staged_candidate: Path,
        payload: dict[str, Any],
        *,
        run_id: str,
        root_guard: dict[str, Any],
        validate_receipt_fn: Callable[[Path, Path], None],
        before_candidate_link_fn: Callable[[], None],
        check_root_guard_fn: Callable[..., None],
        write_bytes_fn: Callable[[Path, bytes], None],
        link_fn: Callable[[str, str], None] | None = None,
        node_identity_fn: NodeIdentity,
        same_identity_fn: Callable[[FileIdentity, FileIdentity], bool],
        remove_owned_fn: RemoveOwned,
        rollback_fn: Callable[..., None],
        token_prefix: str = ".t86-owner-",
) -> dict[str, Any]:
    """Receipt-first/candidate-last publication with an ownership token.

    Format adapters supply closed receipt/output and mutable-input callbacks;
    this function owns the exclusive directory reservation, hard-link order,
    full identity checks, and final token commit marker.  Once the token is
    removed successfully, it performs no fallible work before returning.
    """
    reserved_identity: FileIdentity | None = None
    receipt_identity: FileIdentity | None = None
    candidate_identity: FileIdentity | None = None
    token_target: Path | None = None
    token_identity: FileIdentity | None = None
    receipt_target = run_path / "receipt.json"
    candidate_target = run_path / "candidate.hwpx"
    if link_fn is None:
        link_fn = os.link
    try:
        check_root_guard_fn(root_guard)
        os.mkdir(str(run_path))
        reserved_identity = node_identity_fn(run_path)
        check_root_guard_fn(root_guard, refresh=True)
        token_target = run_path / (token_prefix + secrets.token_hex(16))
        write_bytes_fn(token_target, secrets.token_bytes(32))
        token_identity = node_identity_fn(token_target)
        reserved_identity = node_identity_fn(run_path)
        staged_receipt = publish_stage / "receipt.json"
        receipt_identity = node_identity_fn(staged_receipt)
        check_root_guard_fn(root_guard)
        link_fn(str(staged_receipt), str(receipt_target))
        reserved_identity = node_identity_fn(run_path)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target, staged_candidate)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")

        # Adapter-controlled source/binary/output checks run only after the
        # receipt is durable and immediately before candidate publication.
        before_candidate_link_fn()
        candidate_identity = node_identity_fn(staged_candidate)
        check_root_guard_fn(root_guard)
        link_fn(str(staged_candidate), str(candidate_target))
        reserved_identity = node_identity_fn(run_path)
        if not same_identity_fn(node_identity_fn(candidate_target), candidate_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target, candidate_target)
        if (not same_identity_fn(node_identity_fn(receipt_target), receipt_identity)
                or not same_identity_fn(node_identity_fn(candidate_target), candidate_identity)):
            raise CoreError("diagnostic_publish_failed")
        check_root_guard_fn(root_guard)
        if not remove_owned_fn(token_target, token_identity):
            raise CoreError("diagnostic_publish_failed")
        return payload
    except FileExistsError:
        rollback_fn(
            run_path, reserved_identity, receipt_target, receipt_identity,
            candidate_target, candidate_identity, token_target, token_identity)
        raise CoreError("run_exists")
    except CoreError:
        rollback_fn(
            run_path, reserved_identity, receipt_target, receipt_identity,
            candidate_target, candidate_identity, token_target, token_identity)
        raise
    except OSError:
        rollback_fn(
            run_path, reserved_identity, receipt_target, receipt_identity,
            candidate_target, candidate_identity, token_target, token_identity)
        raise CoreError("diagnostic_publish_failed")


def publish_owner_token_receipt(
        run_path: Path,
        publish_stage: Path,
        payload: dict[str, Any],
        *,
        root_guard: dict[str, Any],
        check_root_guard_fn: Callable[..., None],
        write_bytes_fn: Callable[[Path, bytes], None],
        link_fn: Callable[[str, str], None] | None = None,
        node_identity_fn: NodeIdentity,
        same_identity_fn: Callable[[FileIdentity, FileIdentity], bool],
        remove_owned_fn: RemoveOwned,
        rollback_fn: Callable[..., None],
        validate_receipt_fn: Callable[[Path], None],
        before_commit_fn: Callable[[], None] | None = None,
        token_prefix: str = ".oracle-owner-",
) -> dict[str, Any]:
    """Publish a receipt-only run using the same owner-token commit protocol."""
    if link_fn is None:
        link_fn = os.link
    reserved_identity: FileIdentity | None = None
    receipt_identity: FileIdentity | None = None
    token_target: Path | None = None
    token_identity: FileIdentity | None = None
    receipt_target = run_path / "receipt.json"
    candidate_target = run_path / "candidate.hwpx"
    try:
        check_root_guard_fn(root_guard)
        os.mkdir(str(run_path))
        reserved_identity = node_identity_fn(run_path)
        check_root_guard_fn(root_guard, refresh=True)
        token_target = run_path / (token_prefix + secrets.token_hex(16))
        write_bytes_fn(token_target, secrets.token_bytes(32))
        token_identity = node_identity_fn(token_target)
        reserved_identity = node_identity_fn(run_path)
        staged_receipt = publish_stage / "receipt.json"
        receipt_identity = node_identity_fn(staged_receipt)
        check_root_guard_fn(root_guard)
        link_fn(str(staged_receipt), str(receipt_target))
        reserved_identity = node_identity_fn(run_path)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        # Detach the staged hard-link before the owner token is removed.  The
        # public receipt must be a single regular file before publication is
        # considered committed; temporary-directory cleanup is never part of
        # receipt validity and may fail after this point.
        if not remove_owned_fn(publish_stage / "receipt.json", receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        receipt_info = receipt_target.lstat()
        if (not stat.S_ISREG(receipt_info.st_mode)
                or stat.S_ISLNK(receipt_info.st_mode)
                or getattr(receipt_info, "st_nlink", 1) != 1
                or not same_identity_fn(node_identity_fn(receipt_target), receipt_identity)):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        if before_commit_fn is not None:
            before_commit_fn()
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        check_root_guard_fn(root_guard)
        if not remove_owned_fn(token_target, token_identity):
            raise CoreError("diagnostic_publish_failed")
        return payload
    except FileExistsError:
        rollback_fn(run_path, reserved_identity, receipt_target, receipt_identity,
                    candidate_target, None, token_target, token_identity)
        raise CoreError("run_exists")
    except CoreError:
        rollback_fn(run_path, reserved_identity, receipt_target, receipt_identity,
                    candidate_target, None, token_target, token_identity)
        raise
    except OSError:
        rollback_fn(run_path, reserved_identity, receipt_target, receipt_identity,
                    candidate_target, None, token_target, token_identity)
        raise CoreError("diagnostic_publish_failed")


def prepare_root(path: Path, *, expected_leaf: str = "hwp-diagnostic") -> Path:
    """Validate a pre-created diagnostic root with an exact schema leaf."""
    try:
        root_input = path.expanduser()
        info = root_input.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse):
            raise CoreError("diagnostic_root_invalid")
        probe = root_input
        while True:
            ancestor = probe.lstat()
            if (stat.S_ISLNK(ancestor.st_mode)
                    or getattr(ancestor, "st_file_attributes", 0) & reparse):
                raise CoreError("diagnostic_root_invalid")
            if probe == probe.parent:
                break
            probe = probe.parent
        root = root_input.resolve(strict=True)
        if (not isinstance(expected_leaf, str) or not expected_leaf
                or root.name.casefold() != expected_leaf.casefold()
                or any(part.casefold() == "output" for part in root.parts)):
            raise CoreError("diagnostic_root_invalid")
        return root
    except CoreError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CoreError("diagnostic_root_invalid")


def capture_root_guard(supplied: Path, resolved: Path,
                       *, node_identity_fn: NodeIdentity = node_identity) -> dict[str, Any]:
    supplied_abs = supplied.expanduser().absolute()
    rows: list[tuple[Path, FileIdentity, bool]] = []
    probe = supplied_abs
    is_root = True
    while True:
        rows.append((probe, node_identity_fn(probe), is_root))
        if probe == probe.parent:
            break
        probe = probe.parent
        is_root = False
    return {"supplied": supplied_abs, "resolved": resolved, "rows": rows}


def check_root_guard(guard: dict[str, Any], *, refresh: bool = False,
                     node_identity_fn: NodeIdentity = node_identity) -> None:
    rows = guard["rows"]
    current: list[tuple[Path, FileIdentity, bool]] = []
    try:
        for path, expected, is_root in rows:
            info = path.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & reparse):
                raise CoreError("diagnostic_root_changed")
            actual = node_identity_fn(path)
            if ((is_root and not refresh and actual != expected)
                    or (is_root and refresh and actual[:2] != expected[:2])
                    or (not is_root and actual[:2] != expected[:2])):
                raise CoreError("diagnostic_root_changed")
            current.append((path, actual, is_root))
    except (CoreError, OSError, RuntimeError, ValueError, TypeError):
        raise CoreError("diagnostic_root_changed")
    if refresh:
        guard["rows"] = current


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
    limits.BasicLimitInformation.LimitFlags = 0x2000
    if not kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise OSError("SetInformationJobObject")
    if not kernel.AssignProcessToJobObject(job, ctypes.c_void_p(proc._handle)):
        kernel.CloseHandle(job)
        raise OSError("AssignProcessToJobObject")

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
    thread_handle = kernel.OpenThread(0x0002, False, found)
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


def configure_windows_job(proc):
    """Public seam for the race-free suspended Windows launch."""
    return _configure_windows_job(proc)


def terminate_windows_descendants(parent_pid: int, kernel=None) -> None:
    """Terminate only the process tree rooted at ``parent_pid``."""
    import ctypes

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

    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
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
    for pid in sorted(descendants, reverse=True):
        process = kernel.OpenProcess(0x0001, False, pid)
        if process:
            try:
                kernel.TerminateProcess(process, 1)
            finally:
                kernel.CloseHandle(process)


def run_child_capture(
        argv: list[str], *, timeout: float, cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_validator: Callable[[float], float] | None = None,
        max_output_bytes: int = 8 * 1024 * 1024):
    """Run one bounded child with POSIX group/Windows Job containment."""
    if timeout_validator is not None:
        timeout = timeout_validator(timeout)
    job = None
    job_kernel = None
    windows_suspended = os.name == "nt"
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(cwd) if cwd is not None else None,
            env=env,
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
                if total[0] > max_output_bytes:
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
            # Enumerate descendants while the suspended-launcher root is still
            # alive.  Terminating that root first can reparent the real
            # interpreter spawned by a Windows launcher, making a later
            # parent-PID walk unable to find it.
            try:
                terminate_windows_descendants(proc.pid, job_kernel)
            except (OSError, AttributeError, TypeError, ValueError):
                pass
            try:
                job_kernel.TerminateJobObject(job, 1)
            except (OSError, AttributeError):
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
