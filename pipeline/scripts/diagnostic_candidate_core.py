"""Shared bounded primitives for quarantined diagnostic-candidate adapters.

This module has no document-format knowledge.  It owns only the security
boundaries that every diagnostic adapter needs: no-follow regular snapshots,
bounded child execution with OS-specific process-group/Job containment,
exclusive writes, full file identities, root anchoring, and identity-safe
rollback helpers.  Detached-descendant containment is deliberately not
established by this generic primitive.
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
    "DirectoryBinding",
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


class DirectoryBinding:
    """Hold a directory identity for no-follow relative operations.

    POSIX uses an ``O_DIRECTORY|O_NOFOLLOW`` descriptor and ``dir_fd`` calls.
    Windows holds a backup-semantics directory handle with delete sharing
    disabled; callers still perform the final identity check before return.
    """

    def __init__(self, path: Path, *, fd: int | None = None,
                 handle: Any = None):
        self.path = path.expanduser().absolute()
        self.fd = fd
        self.handle = handle
        self.real_path: str | None = None
        try:
            if self.fd is not None:
                opened = os.fstat(self.fd)
                if not stat.S_ISDIR(opened.st_mode):
                    raise CoreError("directory_binding_unavailable")
                self.identity = self._stable_identity(opened)
                self.real_path = self._fd_real_path(self.fd)
            elif self.handle is not None:
                self.identity = self._handle_identity(self.handle)
                self.real_path = self._handle_real_path(self.handle)
            else:
                raise CoreError("directory_binding_unavailable")
            expected = self._normalise_path(str(self.path))
            if self.real_path is None or self._normalise_path(
                    self.real_path) != expected:
                raise CoreError("directory_binding_unavailable")
        except CoreError:
            self.close()
            raise
        except (OSError, RuntimeError, ValueError, TypeError):
            self.close()
            raise CoreError("directory_binding_unavailable")

    @staticmethod
    def _stable_identity(info: os.stat_result) -> FileIdentity:
        """Return directory identity without mutable size/time/digest fields."""
        return (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0),
                0, 0, 0, "")

    @staticmethod
    def _normalise_path(value: str) -> str:
        if os.name == "nt":
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
        return os.path.normcase(os.path.realpath(value))

    @staticmethod
    def _fd_real_path(fd: int) -> str | None:
        try:
            return os.readlink(f"/proc/self/fd/{fd}")
        except (OSError, ValueError, TypeError):
            try:
                import fcntl
                getpath = getattr(fcntl, "F_GETPATH", 50)
                value = fcntl.fcntl(fd, getpath, bytes(1024))
                if isinstance(value, bytes):
                    return os.fsdecode(value.split(b"\\0", 1)[0])
            except (AttributeError, OSError, ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _handle_real_path(handle: Any) -> str | None:
        try:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetFinalPathNameByHandleW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            kernel.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
            size = 512
            while size <= 32768:
                buffer = ctypes.create_unicode_buffer(size)
                result = kernel.GetFinalPathNameByHandleW(
                    handle, buffer, size, 0)
                if result == 0:
                    return None
                if result < size:
                    return buffer.value
                size *= 2
        except (AttributeError, OSError, ValueError, TypeError):
            return None
        return None

    @staticmethod
    def _handle_identity(handle: Any) -> FileIdentity:
        """Read Windows volume/file-index identity from the held handle."""
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        class _ByHandle(ctypes.Structure):
            _fields_ = [
                ("file_attributes", ctypes.c_uint32),
                ("creation_time", ctypes.c_ulonglong),
                ("last_access_time", ctypes.c_ulonglong),
                ("last_write_time", ctypes.c_ulonglong),
                ("volume_serial", ctypes.c_uint32),
                ("file_size_high", ctypes.c_uint32),
                ("file_size_low", ctypes.c_uint32),
                ("number_of_links", ctypes.c_uint32),
                ("file_index_high", ctypes.c_uint32),
                ("file_index_low", ctypes.c_uint32),
            ]
        kernel.GetFileInformationByHandle.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_ByHandle)]
        kernel.GetFileInformationByHandle.restype = ctypes.c_int
        info = _ByHandle()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise CoreError("directory_binding_unavailable")
        index = (int(info.file_index_high) << 32) | int(info.file_index_low)
        return (int(info.volume_serial), index, 0, 0, 0, "")

    @classmethod
    def open(cls, path: Path, reason: str = "directory_binding_unavailable"):
        try:
            supplied = path.expanduser().absolute()
            info = supplied.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & reparse):
                raise CoreError(reason)
            if os.name != "nt":
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(str(supplied), flags)
                opened = os.fstat(fd)
                if ((getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0))
                        != (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0))):
                    os.close(fd)
                    raise CoreError(reason)
                return cls(supplied, fd=fd)
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [
                ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            kernel.CreateFileW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            handle = kernel.CreateFileW(
                str(supplied), 0x0001,
                0x00000001 | 0x00000002, None, 3, 0x02000000, None)
            invalid = ctypes.c_void_p(-1).value
            if not handle or handle == invalid:
                raise CoreError(reason)
            # Bind the handle to the directory observed before CreateFileW.
            # The handle blocks subsequent delete/rename, but a replacement
            # could otherwise win between the initial lstat and this open.
            post = supplied.lstat()
            if (not stat.S_ISDIR(post.st_mode) or stat.S_ISLNK(post.st_mode)
                    or getattr(post, "st_file_attributes", 0) & reparse
                    or (getattr(post, "st_dev", 0), getattr(post, "st_ino", 0))
                    != (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0))):
                kernel.CloseHandle(ctypes.c_void_p(handle))
                raise CoreError(reason)
            return cls(supplied, handle=handle)
        except CoreError:
            raise
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            raise CoreError(reason)

    def check(self) -> None:
        try:
            info = self.path.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & reparse):
                raise CoreError("directory_binding_changed")
            if self.fd is not None:
                held = os.fstat(self.fd)
                actual = self._stable_identity(held)
                if ((getattr(info, "st_dev", 0), getattr(info, "st_ino", 0))
                        != (self.identity[0], self.identity[1])
                        or not same_file_identity(actual, self.identity)):
                    raise CoreError("directory_binding_changed")
                real = self._fd_real_path(self.fd)
            else:
                actual = self._handle_identity(self.handle)
                if not same_file_identity(actual, self.identity):
                    raise CoreError("directory_binding_changed")
                real = self._handle_real_path(self.handle)
            expected = self._normalise_path(str(self.path))
            if real is None or self._normalise_path(real) != expected:
                raise CoreError("directory_binding_changed")
        except CoreError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError):
            raise CoreError("directory_binding_changed")

    def open_file(self, name: str, flags: int, mode: int = 0o600) -> int:
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            flags |= getattr(os, "O_BINARY", 0)
            if self.fd is not None:
                flags |= getattr(os, "O_NOFOLLOW", 0)
                return os.open(name, flags, mode, dir_fd=self.fd)
            return os.open(str(self.path / name), flags, mode)
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_open_failed")

    def open_directory(self, name: str) -> "DirectoryBinding":
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            if self.fd is not None:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                child_fd = os.open(name, flags, dir_fd=self.fd)
                return DirectoryBinding(self.path / name, fd=child_fd)
            child_path = self.path / name
            return DirectoryBinding.open(child_path,
                                         reason="directory_binding_open_failed")
        except CoreError:
            raise
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_open_failed")

    def write_bytes(self, name: str, data: bytes, mode: int = 0o600) -> FileIdentity:
        fd = self.open_file(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                info = os.fstat(stream.fileno())
                return (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0),
                        getattr(info, "st_size", 0),
                        getattr(info, "st_mtime_ns", 0),
                        getattr(info, "st_ctime_ns", 0),
                        hashlib.sha256(data).hexdigest())
        except (OSError, TypeError, ValueError):
            try:
                os.close(fd)
            except OSError:
                pass
            raise CoreError("directory_binding_write_failed")

    def file_identity(self, name: str, max_bytes: int = 64 * 1024 * 1024) -> FileIdentity:
        fd = self.open_file(name, os.O_RDONLY)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise CoreError("directory_binding_file_invalid")
            if before.st_size < 0 or before.st_size > max_bytes:
                raise CoreError("file_too_large")
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CoreError("file_too_large")
                digest.update(chunk)
            after = os.fstat(fd)
            # Reading a just-created file can update platform access/status
            # timestamps (notably Windows ctime).  Digest, size, and inode are
            # the custody identity for this held-dir publication seam; the
            # format-specific capture path still enforces full generation
            # timestamps before/after its bounded read.
            if ((getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
                 getattr(before, "st_size", 0))
                    != (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                        total)):
                raise CoreError("directory_binding_file_changed")
            return (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    total, getattr(after, "st_mtime_ns", 0),
                    getattr(after, "st_ctime_ns", 0), digest.hexdigest())
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def mkdir(self, name: str, mode: int = 0o700) -> None:
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            if self.fd is not None:
                os.mkdir(name, mode, dir_fd=self.fd)
            else:
                os.mkdir(str(self.path / name), mode)
        except FileExistsError:
            raise
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_mkdir_failed")

    def link(self, source: Path, name: str) -> None:
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            if self.fd is not None:
                os.link(str(source), name, dst_dir_fd=self.fd)
            else:
                os.link(str(source), str(self.path / name))
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_link_failed")

    def unlink(self, name: str) -> None:
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            if self.fd is not None:
                os.unlink(name, dir_fd=self.fd)
            else:
                os.unlink(str(self.path / name))
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_unlink_failed")

    def rmdir(self, name: str) -> None:
        if (not isinstance(name, str) or not name or "/" in name
                or "\\" in name or name in {".", ".."}):
            raise CoreError("directory_binding_name_invalid")
        self.check()
        try:
            if self.fd is not None:
                os.rmdir(name, dir_fd=self.fd)
            else:
                os.rmdir(str(self.path / name))
        except (OSError, TypeError, ValueError):
            raise CoreError("directory_binding_rmdir_failed")

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.handle is not None:
            try:
                import ctypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel.CloseHandle.restype = ctypes.c_int
                kernel.CloseHandle(ctypes.c_void_p(self.handle))
            except (AttributeError, OSError, TypeError):
                pass
            self.handle = None

    def __del__(self):  # pragma: no cover - interpreter cleanup fallback
        try:
            self.close()
        except Exception:
            pass


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
         candidate_name: str = "candidate.hwpx",
         final_commit_fn: Callable[[], None] | None = None,
         directory_binding: DirectoryBinding | None = None,
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
    run_binding: DirectoryBinding | None = None
    created_run = False
    receipt_target = run_path / "receipt.json"
    if candidate_name not in {"candidate.hwpx", "artifact.pdf"}:
        raise CoreError("diagnostic_publish_failed")
    candidate_target = run_path / candidate_name
    if link_fn is None:
        link_fn = os.link

    def public_identity(path: Path) -> FileIdentity:
        if run_binding is not None and path.parent == run_path:
            return run_binding.file_identity(path.name)
        return node_identity_fn(path)

    def publish_write(path: Path, data: bytes) -> FileIdentity | None:
        if run_binding is not None and path.parent == run_path:
            return run_binding.write_bytes(path.name, data)
        else:
            write_bytes_fn(path, data)
        return None

    def publish_link(source: str, target: str) -> None:
        if run_binding is not None and Path(target).parent == run_path:
            run_binding.link(Path(source), Path(target).name)
        else:
            link_fn(source, target)

    def publish_unlink(path: Path, identity: FileIdentity | None) -> bool:
        if run_binding is not None and path.parent == run_path and identity is not None:
            try:
                actual = run_binding.file_identity(path.name)
                if same_identity_fn(actual, identity):
                    run_binding.unlink(path.name)
                    return True
            except CoreError:
                return False
        return remove_owned_fn(path, identity)

    def rollback_bound() -> None:
        """Rollback only through the held run/root directory when available."""
        if run_binding is not None:
            for name, identity in (("receipt.json", receipt_identity),
                                   (candidate_name, candidate_identity),
                                   (token_target.name if token_target else "",
                                    token_identity)):
                if not name or identity is None:
                    continue
                try:
                    if same_identity_fn(run_binding.file_identity(name), identity):
                        run_binding.unlink(name)
                except CoreError:
                    pass
            try:
                if directory_binding is not None and created_run:
                    directory_binding.rmdir(run_id)
            except CoreError:
                pass
            return
        if directory_binding is not None:
            if created_run:
                try:
                    directory_binding.rmdir(run_id)
                except CoreError:
                    pass
            return
        rollback_fn(
            run_path, reserved_identity, receipt_target, receipt_identity,
            candidate_target, candidate_identity, token_target, token_identity)
    try:
        check_root_guard_fn(root_guard)
        if directory_binding is not None:
            directory_binding.mkdir(run_id)
            created_run = True
            run_binding = directory_binding.open_directory(run_id)
        else:
            os.mkdir(str(run_path))
            created_run = True
        reserved_identity = node_identity_fn(run_path)
        check_root_guard_fn(root_guard, refresh=True)
        token_target = run_path / (token_prefix + secrets.token_hex(16))
        token_identity = publish_write(token_target, secrets.token_bytes(32))
        if token_identity is None:
            token_identity = public_identity(token_target)
        reserved_identity = node_identity_fn(run_path)
        staged_receipt = publish_stage / "receipt.json"
        receipt_identity = node_identity_fn(staged_receipt)
        check_root_guard_fn(root_guard)
        publish_link(str(staged_receipt), str(receipt_target))
        reserved_identity = node_identity_fn(run_path)
        if not same_identity_fn(public_identity(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target, staged_candidate)
        if not same_identity_fn(public_identity(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")

        # Adapter-controlled source/binary/output checks run only after the
        # receipt is durable and immediately before candidate publication.
        before_candidate_link_fn()
        candidate_identity = node_identity_fn(staged_candidate)
        check_root_guard_fn(root_guard)
        publish_link(str(staged_candidate), str(candidate_target))
        reserved_identity = node_identity_fn(run_path)
        if not same_identity_fn(public_identity(candidate_target), candidate_identity):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target, candidate_target)
        if (not same_identity_fn(public_identity(receipt_target), receipt_identity)
                or not same_identity_fn(public_identity(candidate_target), candidate_identity)):
            raise CoreError("diagnostic_publish_failed")
        if final_commit_fn is not None:
            final_commit_fn()
        # The root guard is the final directory-custody check.  No guard or
        # callback follows the receipt/candidate checks below.
        # Detach staged hard-links before token removal so a committed public
        # pair is always owner-only even if temporary-directory cleanup fails.
        if not remove_owned_fn(publish_stage / "receipt.json", receipt_identity):
            raise CoreError("diagnostic_publish_failed")
        if not remove_owned_fn(publish_stage / candidate_name, candidate_identity):
            raise CoreError("diagnostic_publish_failed")
        for target, identity in ((receipt_target, receipt_identity),
                                 (candidate_target, candidate_identity)):
            info = target.lstat()
            if (not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_nlink", 1) != 1
                    or not same_identity_fn(public_identity(target), identity)):
                raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target, candidate_target)
        if (not same_identity_fn(public_identity(receipt_target), receipt_identity)
                or not same_identity_fn(public_identity(candidate_target), candidate_identity)):
            raise CoreError("diagnostic_publish_failed")
        # The final path/root guard precedes the last held-directory identity
        # checks and token removal.  No callback or path-based validation may
        # run after this point.
        check_root_guard_fn(root_guard)
        if run_binding is not None:
            for target, identity in ((receipt_target, receipt_identity),
                                     (candidate_target, candidate_identity)):
                if not same_identity_fn(public_identity(target), identity):
                    raise CoreError("diagnostic_publish_failed")
        if not publish_unlink(token_target, token_identity):
            raise CoreError("diagnostic_publish_failed")
        return payload
    except FileExistsError:
        rollback_bound()
        raise CoreError("run_exists")
    except CoreError:
        rollback_bound()
        raise
    except OSError:
        rollback_bound()
        raise CoreError("diagnostic_publish_failed")
    finally:
        if run_binding is not None:
            run_binding.close()


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
        final_commit_fn: Callable[[], None] | None = None,
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
        if final_commit_fn is not None:
            final_commit_fn()
        check_root_guard_fn(root_guard)
        # The final custody callback may itself be the last fallible seam and
        # can race a same-inode overwrite of the already-linked receipt.  The
        # root guard is also fallible and can expose the same race.  Therefore
        # the public receipt is the last persistent state revalidated before
        # the owner token is removed; no callback or guard follows it.
        receipt_info = receipt_target.lstat()
        if (not stat.S_ISREG(receipt_info.st_mode)
                or stat.S_ISLNK(receipt_info.st_mode)
                or getattr(receipt_info, "st_nlink", 1) != 1
                or not same_identity_fn(
                    node_identity_fn(receipt_target), receipt_identity)):
            raise CoreError("diagnostic_publish_failed")
        validate_receipt_fn(receipt_target)
        if not same_identity_fn(node_identity_fn(receipt_target), receipt_identity):
            raise CoreError("diagnostic_publish_failed")
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
        max_output_bytes: int = 8 * 1024 * 1024,
        return_evidence: bool = False):
    """Run one bounded child with POSIX group/Windows Job containment.

    The parent process and its ordinary descendants are contained by the
    platform boundary.  A descendant that deliberately creates a new session
    (POSIX) or otherwise escapes the Job boundary is not proven contained;
    callers must keep that limitation explicit in their receipts.
    """
    if type(return_evidence) is not bool:
        raise CoreError("return_evidence_invalid")
    if timeout_validator is not None:
        timeout = timeout_validator(timeout)
    def failed_result():
        result = (-1, False, False)
        if not return_evidence:
            return result
        return result + ({
            "output": {"sha256": hashlib.sha256(b"").hexdigest(), "bytes": 0},
            "error": {"sha256": hashlib.sha256(b"").hexdigest(), "bytes": 0},
        },)
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
        return failed_result()
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
            return failed_result()
    stdout_total = [0]
    stderr_total = [0]
    stdout_digest = hashlib.sha256()
    stderr_digest = hashlib.sha256()
    overflow = [False]

    def drain(pipe, total, digest):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    return
                total[0] += len(chunk)
                digest.update(chunk)
                if total[0] > max_output_bytes:
                    overflow[0] = True
                    return
        except OSError:
            return

    threads = [threading.Thread(target=drain,
                                args=(proc.stdout, stdout_total, stdout_digest),
                                daemon=True),
               threading.Thread(target=drain,
                                args=(proc.stderr, stderr_total, stderr_digest),
                                daemon=True)]
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
    for thread in threads:
        thread.join(timeout=2)
    if any(thread.is_alive() for thread in threads):
        overflow[0] = True
    if job and job_kernel is not None:
        try:
            job_kernel.CloseHandle(job)
        except OSError:
            pass
    result = (code, timed_out, overflow[0])
    if not return_evidence:
        return result
    return result + ({
        "output": {"sha256": stdout_digest.hexdigest(),
                   "bytes": stdout_total[0]},
        "error": {"sha256": stderr_digest.hexdigest(),
                   "bytes": stderr_total[0]},
    },)
