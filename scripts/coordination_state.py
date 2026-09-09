#!/usr/bin/env python3
"""Small, durable coordination state and fenced-lease layer.

The coordination directory is deliberately explicit.  It is operational state,
not source, and callers must pass a state root (``CoordinationState(root)`` or
the CLI's ``--state-root``).  The module intentionally has no dependencies
outside the Python standard library.

The public object is :class:`CoordinationState`.  Mutating operations take a
short filesystem lock, update JSON by temporary-file/``os.replace`` and append
one event to ``events.jsonl``.  A lease contains both a monotonically increasing
epoch and an unpredictable fencing token.  Result publication checks the lease
*and* the task input revision, so a worker that was replaced cannot publish a
late result.
"""
from __future__ import annotations

import argparse
import ctypes
import fnmatch
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA = "rigorloom/coordination-state-v1"
MODES = {
    "working",
    "reserve",
    "draining",
    "quota-blocked",
    "reset-pending",
    "available",
    "failed",
    "stopped",
}
TERMINAL_WORKER_MODES = {"failed", "stopped"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_LEASE = "active"
RELEASED_LEASE = "released"


class CoordinationError(RuntimeError):
    """Base class for state/coordination failures."""


class StateRootError(CoordinationError, ValueError):
    """The caller omitted or supplied an unusable state root."""


class StateBusy(CoordinationError):
    """Another process currently holds the coordination lock."""


class LeaseConflict(CoordinationError):
    """The requested resource is fenced by a different live lease."""


class FencedError(CoordinationError):
    """A stale holder/epoch/token or task input revision tried to mutate state."""


class RecoveryRequired(CoordinationError):
    """An operation has unknown completion and cannot be replayed safely."""


class ScopeRefused(CoordinationError):
    """A request crossed the task's explicit safety boundary."""


class InvalidRequest(CoordinationError, ValueError):
    """Malformed caller input."""


class CrashInjected(CoordinationError):
    """Deterministic test fault raised at a transaction boundary."""


class _Clock:
    def now(self) -> float:
        return time.time()


def _now_from(clock: Any) -> float:
    if clock is None:
        return time.time()
    if callable(clock):
        return float(clock())
    method = getattr(clock, "now", None)
    if method is None:
        raise TypeError("clock must be callable or provide now()")
    return float(method())


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _token() -> str:
    return uuid.uuid4().hex


def _clean_id(value: str, label: str = "id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest(f"{label} must be a non-empty string")
    value = value.strip()
    if any(ch in value for ch in "\\\x00\n\r"):
        raise InvalidRequest(f"{label} contains an invalid character")
    return value


def _safe(value: Any, *, _key: str = "") -> Any:
    """Redact credential-like values before they enter an event/request log."""
    lowered = _key.lower()
    if any(word in lowered for word in ("secret", "password", "passwd", "cookie", "credential", "access_token", "refresh_token", "api_key")):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _safe(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v, _key=_key) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _as_list(value: Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        raise InvalidRequest("expected a sequence, not a string")
    return [str(item) for item in value]


def _process_start_identity(pid: int | None = None) -> str | None:
    """Return a process-start identity, or ``None`` when it is uninspectable.

    PID reuse makes a PID-only lock unsafe.  Linux hosts expose a monotonic
    start tick in ``/proc/<pid>/stat``.  Windows uses the kernel process
    creation FILETIME via ``GetProcessTimes``.  Unknown/permission failures
    deliberately return ``None`` so callers keep the lock busy rather than
    guessing.
    """
    pid = os.getpid() if pid is None else int(pid)
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            # FILETIME is two DWORDs, not one integer.  Keep a tiny compatible
            # structure to avoid a third-party dependency.
            class _FileTime(ctypes.Structure):
                _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

            created = _FileTime()
            exited = _FileTime()
            kernel = _FileTime()
            user = _FileTime()
            ok = ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user))
            if not ok:
                return None
            value = (int(created.high) << 32) | int(created.low)
            return f"win-filetime:{value}"
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        raw = proc_stat.read_text(encoding="ascii")
        # The comm field may contain spaces, so split only after the final
        # closing parenthesis.  The first field after it is state; starttime
        # is then field 22, i.e. offset 19 in this suffix.
        closing = raw.rfind(")")
        if closing < 0:
            return None
        fields = raw[closing + 1 :].split()
        return f"proc-start:{fields[19]}"
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, IndexError, ValueError):
        return None


def _lock_owner_alive(payload: Mapping[str, Any]) -> bool | None:
    """Return True/False/None for exact PID+start identity liveness."""
    try:
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError):
        return None
    expected = payload.get("process_start")
    if not isinstance(expected, str) or not expected:
        return None
    current = _process_start_identity(pid)
    if current is None:
        # On POSIX a missing /proc entry is strong dead evidence.  On Windows
        # an unavailable handle can be either dead or access denied; use a
        # zero-time OpenProcess probe to separate the common dead case.
        if os.name == "nt":
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return None
            # ``OpenProcess`` failing with these errors is strong evidence
            # that the PID no longer exists.  Other errors (notably access
            # denied) remain unknown and must keep the lock busy.
            error = ctypes.get_last_error() or ctypes.windll.kernel32.GetLastError()
            if int(error) in {6, 87, 1168}:  # INVALID_HANDLE, INVALID_PARAMETER, NOT_FOUND
                return False
        else:
            try:
                os.stat(f"/proc/{pid}")
            except FileNotFoundError:
                return False
            except OSError:
                return None
        return None
    return current == expected


class _FileLock:
    """A tiny cross-process lock based on atomic create.

    The lock is held only while one logical state mutation is assembled and
    written.  We never delete an unknown lock merely because it is old: a stale
    heartbeat is not evidence that a process stopped.  A caller may therefore
    receive ``StateBusy`` and retry at its own safe boundary.
    """

    def __init__(self, path: Path, *, timeout: float = 10.0, poll: float = 0.01):
        self.path = path
        self.timeout = max(0.0, float(timeout))
        self.poll = max(0.001, float(poll))
        self._token: str | None = None

    def _unlink_if_token(self, token: str, *, deadline: float) -> bool:
        """Remove our lock, tolerating short Windows sharing violations.

        A reader may briefly hold the lock path open while parsing its owner
        record.  Re-read the token before every unlink attempt so a retry can
        never delete a newly claimed lock.
        """
        delay = self.poll
        while True:
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return True
            except (OSError, json.JSONDecodeError):
                current = None
            if isinstance(current, Mapping) and current.get("token") != token:
                return False
            if current is None:
                now = time.monotonic()
                if now >= deadline:
                    return False
                time.sleep(min(delay, max(0.0, deadline - now)))
                delay = min(delay * 2.0, 0.05)
                continue
            try:
                self.path.unlink()
                return True
            except FileNotFoundError:
                return True
            except OSError:
                now = time.monotonic()
                if now >= deadline:
                    return False
                time.sleep(min(delay, max(0.0, deadline - now)))
                delay = min(delay * 2.0, 0.05)

    def __enter__(self) -> "_FileLock":
        started = time.monotonic()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = _token()
        process_start = _process_start_identity()
        if not process_start:
            # Never publish a PID-only owner record: if start identity is not
            # inspectable, a later process cannot safely distinguish PID reuse
            # from the original owner.  Fail closed without creating a lock.
            raise StateBusy("cannot acquire coordination lock without process-start identity")
        payload = {"pid": os.getpid(), "process_start": process_start, "token": token, "created_at": time.time()}
        encoded = _json_bytes(payload)
        stage_path = self.path.with_name(f".{self.path.name}.{token}.tmp")
        fd: int | None = None
        try:
            # Fully materialize and fsync the owner record before exposing it
            # at the canonical lock path.  Hard-link creation is atomic and
            # no-clobber on POSIX and NTFS, unlike replacing an existing path.
            fd = os.open(str(stage_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            offset = 0
            while offset < len(encoded):
                offset += os.write(fd, encoded[offset:])
            os.fsync(fd)
            os.close(fd)
            fd = None
            while True:
                try:
                    os.link(str(stage_path), str(self.path))
                    self._token = token
                    return self
                except FileExistsError:
                    # Reclaim only a lock whose exact PID + process-start
                    # identity is proven dead.  Permission/identity failures
                    # remain busy; an old mtime alone is never a revocation
                    # signal.
                    try:
                        owner = json.loads(self.path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        owner = None
                    if isinstance(owner, Mapping) and _lock_owner_alive(owner) is False:
                        try:
                            current = json.loads(self.path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            current = None
                        if isinstance(current, Mapping) and current.get("token") == owner.get("token"):
                            if self._unlink_if_token(str(owner.get("token")), deadline=started + self.timeout):
                                continue
                    if time.monotonic() - started >= self.timeout:
                        raise StateBusy(f"coordination lock is busy: {self.path}")
                    time.sleep(self.poll)
                except OSError as exc:
                    # Do not fall back to an unsafe overwrite/create sequence
                    # on filesystems without atomic no-clobber links.
                    raise CoordinationError(f"filesystem cannot atomically claim coordination lock: {self.path}") from exc
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                stage_path.unlink()
            except FileNotFoundError:
                pass

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        token = self._token
        self._token = None
        if token is None:
            return
        # A brief reader sharing violation is normal on Windows.  Unlocking
        # is best-effort after bounded retries; a later contender can reclaim
        # the exact dead PID+start identity if this process exits meanwhile.
        self._unlink_if_token(token, deadline=time.monotonic() + max(self.timeout, 0.5))


class CoordinationState:
    """Durable coordination state rooted at an explicit operational directory."""

    FILES = {
        "meta": "meta.json",
        "workers": "workers.json",
        "tasks": "tasks.json",
        "leases": "leases.json",
        "quotas": "quota_snapshots.json",
        "checkpoints": "checkpoints.json",
        "results": "results.json",
        "requests": "requests.json",
        "operations": "operations.json",
        "inbox": "inbox.json",
        "outbox": "outbox.json",
        "handoffs": "handoffs.json",
    }

    def __init__(self, state_root: os.PathLike[str] | str | None, *, clock: Any = None,
                 lock_timeout: float = 10.0):
        if state_root is None or (isinstance(state_root, str) and not state_root.strip()):
            raise StateRootError("an explicit --state-root is required")
        try:
            root = Path(state_root).expanduser().resolve()
        except (TypeError, OSError) as exc:
            raise StateRootError("invalid state root") from exc
        if root == Path(root.anchor):
            raise StateRootError("a filesystem root is not a suitable coordination state root")
        self.root = root
        self.clock = clock if clock is not None else _Clock()
        self.lock_timeout = float(lock_timeout)
        self._thread_lock = threading.RLock()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StateRootError(f"cannot create state root: {self.root}") from exc
        self._lock_path = self.root / ".coordination.lock"
        self._transactions = self.root / ".transactions"
        self._txn_hook: Callable[[str, int, str], None] | None = None

    # -- low-level persistence -------------------------------------------------

    def _lock(self) -> _FileLock:
        return _FileLock(self._lock_path, timeout=self.lock_timeout)

    def _path(self, key: str) -> Path:
        return self.root / self.FILES[key]

    def _default(self, key: str) -> dict[str, Any]:
        if key == "meta":
            return {"schema": SCHEMA, "revision": 0}
        plural = {
            "workers": "workers",
            "tasks": "tasks",
            "leases": "leases",
            "quotas": "snapshots",
            "checkpoints": "checkpoints",
            "results": "results",
            "requests": "requests",
            "operations": "operations",
            "inbox": "messages",
            "outbox": "messages",
            "handoffs": "handoffs",
        }[key]
        value: dict[str, Any] = {"schema": SCHEMA, "revision": 0, plural: {}}
        if key in {"inbox", "outbox"}:
            value["acknowledged_ids"] = []
        return value

    def _read(self, key: str) -> dict[str, Any]:
        path = self._path(key)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._default(key)
        except (OSError, json.JSONDecodeError) as exc:
            raise CoordinationError(f"invalid coordination state: {path}") from exc
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise CoordinationError(f"unsupported coordination state: {path}")
        return value

    def _write(self, key: str, value: Mapping[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(_safe(value), stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _repair_event_tail(self) -> None:
        """Discard a torn final JSONL record before any stable append."""
        path = self.root / "events.jsonl"
        if not path.exists():
            return
        try:
            raw = path.read_bytes()
        except OSError:
            return
        if not raw:
            return
        # A process can die after writing an incomplete line *with* its
        # newline, so inspect the final non-empty record as JSON rather than
        # relying on a trailing newline alone.  Only the trailing record is
        # discarded; prior complete records remain append-only evidence.
        chunks = raw.splitlines(keepends=True)
        cut = len(raw)
        last_start = None
        last_payload = b""
        offset = 0
        for chunk in chunks:
            payload = chunk.rstrip(b"\r\n")
            if payload.strip():
                last_start = offset
                last_payload = payload
            offset += len(chunk)
        if last_start is None:
            return
        try:
            parsed = json.loads(last_payload.decode("utf-8"))
            if isinstance(parsed, Mapping):
                # A complete record without its newline is salvageable, but
                # must be terminated before the next append can remain valid
                # JSONL.  Treat it as a stable standalone line.
                if not raw.endswith(b"\n"):
                    try:
                        with path.open("ab") as stream:
                            stream.write(b"\n")
                            stream.flush()
                            os.fsync(stream.fileno())
                    except OSError:
                        raise CoordinationError(f"cannot repair events tail: {path}")
                return
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        cut = int(last_start)
        if cut == len(raw):
            return
        try:
            with path.open("r+b") as stream:
                stream.truncate(cut)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise CoordinationError(f"cannot repair events tail: {path}")

    def _event_ids(self) -> set[str]:
        path = self.root / "events.jsonl"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return set()
        ids: set[str] = set()
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping) and isinstance(value.get("event_id"), str):
                ids.add(value["event_id"])
        return ids

    def _event(self, kind: str, detail: Mapping[str, Any] | None = None,
               *, revision: int | None = None, event_id: str | None = None,
               at: float | None = None) -> dict[str, Any]:
        """Append one stable redacted event while the caller holds the lock."""
        self._repair_event_tail()
        event_path = self.root / "events.jsonl"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        seq = 0
        try:
            with event_path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    if line.strip():
                        seq += 1
        except FileNotFoundError:
            pass
        event = {
            "seq": seq,
            "event_id": event_id or _token(),
            "at": _now_from(self.clock) if at is None else float(at),
            "kind": _clean_id(kind, "event kind"),
            "state_revision": int(revision if revision is not None else self._read("meta").get("revision", 0)),
            "detail": _safe(dict(detail or {})),
        }
        with event_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def _write_raw_json(self, path: Path, value: Mapping[str, Any]) -> None:
        """Atomic writer for WAL files (which are not regular state docs)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(_safe(value), stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _txn_hook_call(self, stage: str, index: int, name: str) -> None:
        hook = self._txn_hook
        if hook is not None:
            hook(stage, index, name)

    def _atomic_transaction(self, updates: Mapping[str, Mapping[str, Any]],
                            event_specs: Sequence[tuple[str, Mapping[str, Any]]]) -> tuple[int, list[dict[str, Any]]]:
        """Commit a complete logical mutation through a prepared WAL.

        The caller holds ``self._lock()``.  Every update and event is included
        in one durable transaction record before any target is replaced.
        """
        self._ensure_locked()
        # Canonicalize exactly what is written to the WAL.  ``_write`` also
        # redacts, and checksumming the unsanitized in-memory value would make
        # an otherwise valid WAL unrecoverable when a credential-like key is
        # present.
        docs = {key: _safe(dict(value)) for key, value in updates.items()}
        unknown = set(docs) - set(self.FILES)
        if unknown:
            raise InvalidRequest(f"unknown state documents: {sorted(unknown)}")
        meta = self._read("meta")
        revision = int(meta.get("revision", 0)) + 1
        meta["revision"] = revision
        docs["meta"] = meta
        for value in docs.values():
            if isinstance(value, dict) and "revision" in value:
                value["revision"] = revision
        now = _now_from(self.clock)
        events = [{
            "event_id": _token(),
            "at": now,
            "kind": _clean_id(kind, "event kind"),
            "state_revision": revision,
            "detail": _safe(dict(detail)),
        } for kind, detail in event_specs]
        transaction = {
            "schema": SCHEMA,
            "transaction_id": _token(),
            "revision": revision,
            "updates": docs,
            "events": events,
        }
        transaction["checksum"] = _sha256(transaction)
        wal_path = self._transactions / f"tx-{transaction['transaction_id']}.json"
        self._write_raw_json(wal_path, transaction)
        self._txn_hook_call("prepared", 0, wal_path.name)
        index = 0
        for key, value in docs.items():
            self._write(key, value)
            index += 1
            self._txn_hook_call("json", index, key)
        appended: list[dict[str, Any]] = []
        for event in events:
            appended.append(self._event(event["kind"], event["detail"], revision=revision, event_id=event["event_id"], at=event["at"]))
            index += 1
            self._txn_hook_call("event", index, event["event_id"])
        try:
            wal_path.unlink()
        except FileNotFoundError:
            pass
        self._txn_hook_call("committed", index, transaction["transaction_id"])
        return revision, appended

    def _recover_locked(self) -> None:
        """Finish prepared WALs idempotently under the coordination lock."""
        self._transactions.mkdir(parents=True, exist_ok=True)
        # Repair a torn append even when no prepared transaction remains (for
        # example, a process died while writing an informational event).
        self._repair_event_tail()
        for wal_path in sorted(self._transactions.glob("tx-*.json")):
            try:
                transaction = json.loads(wal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CoordinationError(f"invalid transaction WAL: {wal_path}") from exc
            if not isinstance(transaction, dict) or transaction.get("schema") != SCHEMA:
                raise CoordinationError(f"unsupported transaction WAL: {wal_path}")
            checksum = transaction.get("checksum")
            unsigned = dict(transaction)
            unsigned.pop("checksum", None)
            if checksum != _sha256(unsigned):
                raise CoordinationError(f"transaction WAL checksum mismatch: {wal_path}")
            updates = transaction.get("updates")
            if not isinstance(updates, Mapping):
                raise CoordinationError(f"transaction WAL updates missing: {wal_path}")
            events = transaction.get("events", [])
            if not isinstance(events, list):
                raise CoordinationError(f"transaction WAL events missing: {wal_path}")
            for key, value in updates.items():
                if key not in self.FILES or not isinstance(value, Mapping):
                    raise CoordinationError(f"transaction WAL target invalid: {wal_path}")
                self._write(key, value)
            self._repair_event_tail()
            existing_ids = self._event_ids()
            for event in events:
                if not isinstance(event, Mapping):
                    raise CoordinationError(f"transaction WAL event invalid: {wal_path}")
                event_id = event.get("event_id")
                kind = event.get("kind")
                detail = event.get("detail", {})
                if not isinstance(event_id, str) or not event_id or not isinstance(kind, str) or not isinstance(detail, Mapping):
                    raise CoordinationError(f"transaction WAL event invalid: {wal_path}")
                if event_id in existing_ids:
                    continue
                self._event(kind, detail, revision=int(event.get("state_revision", transaction.get("revision", 0))), event_id=event_id, at=float(event.get("at", _now_from(self.clock))))
                existing_ids.add(event_id)
            try:
                wal_path.unlink()
            except FileNotFoundError:
                pass

    def _next_revision(self) -> int:
        """Compatibility helper for callers that only need a meta revision."""
        revision, _ = self._atomic_transaction({}, [])
        return revision

    def _commit(self, key: str, value: dict[str, Any], kind: str,
                detail: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        revision, events = self._atomic_transaction({key: value}, [(kind, detail or {})])
        return revision, events[0]

    def initialize(self) -> dict[str, Any]:
        """Create the root and empty files atomically enough for a fresh root."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return {"schema": SCHEMA, "state_root": str(self.root), "revision": self._read("meta").get("revision", 0)}

    def _ensure_locked(self) -> None:
        for key in self.FILES:
            path = self._path(key)
            if not path.exists():
                self._write(key, self._default(key))
        events = self.root / "events.jsonl"
        if not events.exists():
            events.touch()
        # Recovery is part of every lock acquisition's read/modify/write
        # boundary.  A prepared WAL therefore cannot be bypassed by a fresh
        # process that happens to call a getter or mutator first.
        self._recover_locked()

    def read_events(self, after: int = -1, limit: int | None = None) -> dict[str, Any]:
        if limit is not None and (limit <= 0 or limit > 10_000):
            raise InvalidRequest("limit must be between 1 and 10000")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            events: list[dict[str, Any]] = []
            next_seq = 0
            path = self.root / "events.jsonl"
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Recovery repairs only a torn trailing record; malformed
                    # interior records are retained as evidence but ignored.
                    next_seq += 1
                    continue
                if not isinstance(event, dict):
                    next_seq += 1
                    continue
                seq = int(event.get("seq", next_seq))
                next_seq = max(next_seq, seq + 1)
                if seq > after:
                    events.append(event)
        more = limit is not None and len(events) > limit
        if limit is not None:
            events = events[:limit]
        return {"events": events, "next_seq": next_seq, "more": bool(more)}

    events = read_events

    def append_event(self, kind: str, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Append a redacted informational event without changing a record."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            _, events = self._atomic_transaction({}, [(kind, detail or {})])
            return events[0]

    def snapshot(self) -> dict[str, Any]:
        """Return all persisted state; useful for a restart/recovery probe."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return {
                "schema": SCHEMA,
                "state_root": str(self.root),
                "revision": int(self._read("meta").get("revision", 0)),
                "workers": self._read("workers").get("workers", {}),
                "tasks": self._read("tasks").get("tasks", {}),
                "leases": self._read("leases").get("leases", {}),
                "quota_snapshots": self._read("quotas").get("snapshots", {}),
                "checkpoints": self._read("checkpoints").get("checkpoints", {}),
                "results": self._read("results").get("results", {}),
                "requests": self._read("requests").get("requests", {}),
                "operations": self._read("operations").get("operations", {}),
                "inbox": self._read("inbox").get("messages", {}),
                "outbox": self._read("outbox").get("messages", {}),
                "handoffs": self._read("handoffs").get("handoffs", {}),
            }

    # -- workers and tasks -----------------------------------------------------

    def register_worker(
        self,
        worker_id: str,
        provider: str,
        *,
        model: str | None = None,
        account_alias: str | None = None,
        capabilities: Sequence[str] | None = None,
        mode: str = "available",
        availability: bool = True,
        heartbeat: float | None = None,
        process_id: str | int | None = None,
        process_alive: bool | None = None,
        quota_snapshot_id: str | None = None,
        question_budget: int = 0,
        herdr_id: str | None = None,
        app_bridge_id: str | None = None,
    ) -> dict[str, Any]:
        worker_id = _clean_id(worker_id, "worker_id")
        provider = _clean_id(provider, "provider")
        mode = _clean_id(mode, "mode")
        if mode not in MODES:
            raise InvalidRequest(f"unsupported worker mode: {mode}")
        if int(question_budget) < 0:
            raise InvalidRequest("question_budget cannot be negative")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            workers_doc = self._read("workers")
            old = workers_doc.get("workers", {}).get(worker_id)
            worker = {
                "worker_id": worker_id,
                "provider": provider,
                "model": model,
                "account_alias": account_alias,
                "herdr_id": herdr_id,
                "app_bridge_id": app_bridge_id,
                "capabilities": sorted(set(_as_list(capabilities))),
                "mode": mode,
                "heartbeat": float(_now_from(self.clock) if heartbeat is None else heartbeat),
                "availability": bool(availability),
                "process_id": None if process_id is None else str(process_id),
                "process_alive": process_alive,
                "quota_snapshot_id": quota_snapshot_id,
                "question_budget": int(question_budget),
                "revision": int(old.get("revision", 0) if old else 0) + 1,
            }
            workers_doc.setdefault("workers", {})[worker_id] = worker
            self._commit("workers", workers_doc, "worker.registered" if old is None else "worker.updated", {"worker_id": worker_id, "mode": mode})
            return dict(worker)

    def update_worker(self, worker_id: str, **changes: Any) -> dict[str, Any]:
        worker_id = _clean_id(worker_id, "worker_id")
        allowed = {"provider", "model", "account_alias", "herdr_id", "app_bridge_id", "capabilities", "mode", "heartbeat", "availability", "process_id", "process_alive", "quota_snapshot_id", "question_budget"}
        unknown = set(changes) - allowed
        if unknown:
            raise InvalidRequest(f"unknown worker fields: {sorted(unknown)}")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("workers")
            current = doc.get("workers", {}).get(worker_id)
            if current is None:
                raise InvalidRequest(f"unknown worker: {worker_id}")
            merged = dict(current)
            merged.update(changes)
            if "mode" in merged and merged["mode"] not in MODES:
                raise InvalidRequest(f"unsupported worker mode: {merged['mode']}")
            if "capabilities" in merged:
                merged["capabilities"] = sorted(set(_as_list(merged["capabilities"])))
            merged["revision"] = int(current.get("revision", 0)) + 1
            doc["workers"][worker_id] = merged
            self._commit("workers", doc, "worker.updated", {"worker_id": worker_id, "changes": sorted(changes)})
            return dict(merged)

    def _worker_locked(self, worker_id: str) -> dict[str, Any]:
        worker = self._read("workers").get("workers", {}).get(_clean_id(worker_id, "worker_id"))
        if worker is None:
            raise InvalidRequest(f"unknown worker: {worker_id}")
        return dict(worker)

    def worker(self, worker_id: str) -> dict[str, Any]:
        """Read one worker through the same lock/recovery boundary as writes."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._worker_locked(worker_id)

    get_worker = worker

    def register_task(
        self,
        task_id: str,
        *,
        dependencies: Sequence[str] | None = None,
        allowed_paths: Sequence[str] | None = None,
        input_hashes: Mapping[str, str] | None = None,
        acceptance_commands: Sequence[str] | None = None,
        assignee: str | None = None,
        status: str = "queued",
        capability: Sequence[str] | None = None,
        max_spawn: int = 3,
    ) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        if int(max_spawn) < 0:
            raise InvalidRequest("max_spawn cannot be negative")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("tasks")
            old = doc.get("tasks", {}).get(task_id)
            if old is not None:
                return dict(old)
            task = {
                "task_id": task_id,
                "dependencies": _as_list(dependencies),
                "allowed_paths": _as_list(allowed_paths),
                "input_hashes": dict(input_hashes or {}),
                "base_hashes": dict(input_hashes or {}),
                "acceptance_commands": _as_list(acceptance_commands),
                "capabilities": sorted(set(_as_list(capability))),
                "max_spawn": int(max_spawn),
                "assignee": assignee,
                "status": status,
                "revision": 0,
                "last_receipt": None,
                "handoff": None,
                "checkpoint_id": None,
                "recovery_required": False,
                "recovery_reason": None,
                "result_id": None,
                "result_hash": None,
                "integrated_count": 0,
                "pending_question": None,
                "blocked_reason": None,
            }
            doc.setdefault("tasks", {})[task_id] = task
            self._commit("tasks", doc, "task.registered", {"task_id": task_id})
            return dict(task)

    def _task_locked(self, task_id: str) -> dict[str, Any]:
        task = self._read("tasks").get("tasks", {}).get(_clean_id(task_id, "task_id"))
        if task is None:
            raise InvalidRequest(f"unknown task: {task_id}")
        return dict(task)

    def task(self, task_id: str) -> dict[str, Any]:
        """Read one task through the same lock/recovery boundary as writes."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._task_locked(task_id)

    get_task = task

    # -- leases ----------------------------------------------------------------

    @staticmethod
    def _lease_key(kind: str, resource_id: str) -> str:
        return f"{_clean_id(kind, 'lease kind')}:{_clean_id(resource_id, 'resource_id')}"

    def _holder_process_alive_locked(self, holder: str) -> bool | None:
        worker = self._read("workers").get("workers", {}).get(holder)
        return None if worker is None else worker.get("process_alive")

    def _lease_current_locked(self, lease: Mapping[str, Any] | None, holder: str, epoch: int | None, token: str | None) -> bool:
        if not lease or lease.get("state") != ACTIVE_LEASE:
            return False
        if lease.get("holder") != holder or int(lease.get("epoch", -1)) != int(epoch if epoch is not None else -2):
            return False
        return bool(token and lease.get("fencing_token") == token)

    def acquire_lease(
        self,
        kind: str,
        resource_id: str | None = None,
        holder: str | None = None,
        *,
        ttl: float = 60.0,
        expected_task_revision: int | None = None,
        handoff_id: str | None = None,
    ) -> dict[str, Any]:
        # Compact task form: acquire_lease(task_id, holder).  The explicit
        # three-argument form remains canonical for coordinator/COM leases.
        if holder is None:
            if resource_id is None:
                raise InvalidRequest("lease holder is required")
            holder = resource_id
            resource_id = kind
            kind = "task"
        if resource_id is None or holder is None:
            raise InvalidRequest("lease resource and holder are required")
        if ttl <= 0:
            raise InvalidRequest("lease ttl must be positive")
        kind = _clean_id(kind, "lease kind")
        resource_id = _clean_id(resource_id, "resource_id")
        holder = _clean_id(holder, "holder")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._acquire_lease_locked(
                kind,
                resource_id,
                holder,
                ttl=ttl,
                expected_task_revision=expected_task_revision,
                handoff_id=handoff_id,
            )

    def acquire_task_lease(self, task_id: str, holder: str, **kwargs: Any) -> dict[str, Any]:
        return self.acquire_lease("task", task_id, holder, **kwargs)

    def acquire_coordinator_lease(self, holder: str, **kwargs: Any) -> dict[str, Any]:
        return self.acquire_lease("coordinator", "default", holder, **kwargs)

    def _lease_locked(self, kind: str, resource_id: str) -> dict[str, Any] | None:
        return self._read("leases").get("leases", {}).get(self._lease_key(kind, resource_id))

    def lease(self, kind: str, resource_id: str) -> dict[str, Any] | None:
        """Read one lease through the same lock/recovery boundary as writes."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            value = self._lease_locked(kind, resource_id)
            return None if value is None else dict(value)

    get_lease = lease

    def release_lease(
        self,
        kind: str,
        resource_id: str,
        holder: str,
        epoch: int,
        fencing_token: str,
        *,
        reason: str = "released",
        proof: str = "explicit",
    ) -> dict[str, Any]:
        key = self._lease_key(kind, resource_id)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("leases")
            current = doc.get("leases", {}).get(key)
            if not self._lease_current_locked(current, holder, epoch, fencing_token):
                raise FencedError(f"lease is no longer current: {key}")
            current = dict(current)
            current.update({"state": RELEASED_LEASE, "released_at": _now_from(self.clock), "release_reason": reason, "release_proof": proof})
            doc["leases"][key] = current
            self._commit("leases", doc, "lease.released", {"kind": kind, "resource_id": resource_id, "holder": holder, "epoch": epoch, "reason": reason})
            return current

    def lease_is_current(self, kind: str, resource_id: str, holder: str, epoch: int, fencing_token: str) -> bool:
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._lease_current_locked(self._lease_locked(kind, resource_id), holder, epoch, fencing_token)

    def release(self, lease: Mapping[str, Any], *, reason: str = "released", proof: str = "explicit") -> dict[str, Any]:
        """Release a lease record returned by an acquire operation."""
        try:
            return self.release_lease(str(lease["kind"]), str(lease["resource_id"]), str(lease["holder"]), int(lease["epoch"]), str(lease["fencing_token"]), reason=reason, proof=proof)
        except KeyError as exc:
            raise InvalidRequest("lease record is missing fencing fields") from exc

    def renew_lease(self, kind: str, resource_id: str, holder: str, epoch: int,
                    fencing_token: str, *, ttl: float = 60.0) -> dict[str, Any]:
        if ttl <= 0:
            raise InvalidRequest("lease ttl must be positive")
        key = self._lease_key(kind, resource_id)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("leases")
            current = doc.get("leases", {}).get(key)
            if not self._lease_current_locked(current, holder, epoch, fencing_token):
                raise FencedError(f"lease is no longer current: {key}")
            now = _now_from(self.clock)
            renewed = dict(current)
            renewed["expires_at"] = now + float(ttl)
            doc["leases"][key] = renewed
            self._commit("leases", doc, "lease.renewed", {"kind": kind, "resource_id": resource_id, "holder": holder, "epoch": epoch})
            return renewed

    # -- checkpoints, handover and recovery -----------------------------------

    def _mark_recovery_state_locked(self, task_id: str, reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
        tasks_doc = self._read("tasks")
        task = tasks_doc.get("tasks", {}).get(task_id)
        if task is None:
            raise InvalidRequest(f"unknown task: {task_id}")
        task = dict(task)
        task["revision"] = int(task.get("revision", 0)) + 1
        task["status"] = "recovery-required"
        task["recovery_required"] = True
        task["recovery_reason"] = reason
        task["blocked_reason"] = "unknown-operation-completion"
        tasks_doc["tasks"][task_id] = task
        return tasks_doc, task

    def _mark_recovery_locked(self, task_id: str, reason: str, *, operation_id: str | None = None) -> dict[str, Any]:
        tasks_doc, task = self._mark_recovery_state_locked(task_id, reason)
        self._commit("tasks", tasks_doc, "task.recovery_required", {"task_id": task_id, "reason": reason, "operation_id": operation_id})
        return dict(task)

    def checkpoint_task(
        self,
        task_id: str,
        holder: str,
        epoch: int,
        fencing_token: str,
        *,
        state: Mapping[str, Any] | None = None,
        dirty_paths: Sequence[str] | None = None,
        current_edits: Sequence[str] | None = None,
        outputs: Mapping[str, Any] | None = None,
        tests: Sequence[str] | None = None,
        unrun_checks: Sequence[str] | None = None,
        completed_commands: Sequence[str] | None = None,
        next_safe_action: str | None = None,
        base_hash: str | None = None,
        head: str | None = None,
        operation_receipt: Mapping[str, Any] | None = None,
        pipeline_state: Mapping[str, Any] | None = None,
        observe_timeout: bool = False,
        process_alive: bool | None = None,
        operation_kind: str | None = None,
        operation_status: str | None = None,
        worker_mode: str = "draining",
    ) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        if worker_mode not in MODES:
            raise InvalidRequest(f"unsupported worker mode: {worker_mode}")
        key = self._lease_key("task", task_id)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            leases_doc = self._read("leases")
            lease = leases_doc.get("leases", {}).get(key)
            if not self._lease_current_locked(lease, holder, epoch, fencing_token):
                raise FencedError(f"task lease is no longer current: {task_id}")
            worker = self._read("workers").get("workers", {}).get(holder, {})
            alive = worker.get("process_alive") if process_alive is None else process_alive
            if observe_timeout:
                if alive is True:
                    self._atomic_transaction({}, [("checkpoint.observation_timeout", {"task_id": task_id, "holder": holder, "duplicate_prevented": True, "process_alive": True})])
                    return {"status": "observation-pending", "duplicate_prevented": True, "lease": dict(lease), "task": self._task_locked(task_id)}
                if alive is None:
                    task_doc, task = self._mark_recovery_state_locked(task_id, "checkpoint-observation-unknown")
                    lease = dict(lease)
                    lease.update({"state": RELEASED_LEASE, "released_at": _now_from(self.clock), "release_reason": "recovery-required", "release_proof": "terminal-unknown"})
                    leases_doc["leases"][key] = lease
                    self._atomic_transaction(
                        {"tasks": task_doc, "leases": leases_doc},
                        [
                            ("task.recovery_required", {"task_id": task_id, "reason": "checkpoint-observation-unknown"}),
                            ("lease.released", {"kind": "task", "resource_id": task_id, "holder": holder, "reason": "recovery-required"}),
                        ],
                    )
                    return {"status": "recovery-required", "task": task, "lease": lease}
                # A known-dead process still needs operation status if an
                # irreversible operation was in flight; continue below.
            if (operation_kind or "").lower() in {"com", "hancom", "native-com"} and (operation_status or "unknown").lower() == "unknown":
                task_doc, task = self._mark_recovery_state_locked(task_id, "unknown-com-save-status")
                lease = dict(lease)
                lease.update({"state": RELEASED_LEASE, "released_at": _now_from(self.clock), "release_reason": "recovery-required", "release_proof": "unknown-com"})
                leases_doc["leases"][key] = lease
                self._atomic_transaction(
                    {"tasks": task_doc, "leases": leases_doc},
                    [
                        ("task.recovery_required", {"task_id": task_id, "reason": "unknown-com-save-status"}),
                        ("lease.released", {"kind": "task", "resource_id": task_id, "holder": holder, "reason": "recovery-required"}),
                    ],
                )
                return {"status": "recovery-required", "task": task, "lease": lease}
            task_doc = self._read("tasks")
            task = task_doc.get("tasks", {}).get(task_id)
            if task is None:
                raise InvalidRequest(f"unknown task: {task_id}")
            checkpoint_id = _token()
            now = _now_from(self.clock)
            checkpoint = {
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "holder": holder,
                "epoch": int(epoch),
                "fencing_token": fencing_token,
                "captured_at": now,
                "base_task_revision": int(task.get("revision", 0)),
                "state": _safe(dict(state or {})),
                "dirty_paths": _as_list(dirty_paths),
                "current_edits": _as_list(current_edits),
                "outputs": _safe(dict(outputs or {})),
                "tests": _as_list(tests),
                "unrun_checks": _as_list(unrun_checks),
                "completed_commands": _as_list(completed_commands),
                "next_safe_action": next_safe_action,
                "base_hash": base_hash,
                "head": head,
                "operation_receipt": _safe(dict(operation_receipt or {})),
                "pipeline_state": _safe(dict(pipeline_state or {})),
                "safe_boundary": True,
            }
            checkpoint["checkpoint_hash"] = _sha256(checkpoint)
            cp_doc = self._read("checkpoints")
            cp_doc.setdefault("checkpoints", {})[checkpoint_id] = checkpoint
            task["revision"] = int(task.get("revision", 0)) + 1
            task["status"] = "checkpointed"
            task["checkpoint_id"] = checkpoint_id
            task["handoff"] = {"checkpoint_id": checkpoint_id, "from_holder": holder, "from_epoch": int(epoch), "claimed_by": None, "claimed_at": None, "safe_boundary": True}
            task["assignee"] = holder
            task["blocked_reason"] = None
            task_doc["tasks"][task_id] = task
            handoffs_doc = self._read("handoffs")
            handoff = {
                "handoff_id": checkpoint_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_hash": checkpoint["checkpoint_hash"],
                "task_id": task_id,
                "from_holder": holder,
                "from_epoch": int(epoch),
                "input_revision": int(task["revision"]),
                "created_at": now,
                "safe_boundary": True,
                "claimed_by": None,
                "claimed_at": None,
                "completed_at": None,
            }
            handoffs_doc.setdefault("handoffs", {})[checkpoint_id] = handoff
            lease = dict(lease)
            lease.update({"state": RELEASED_LEASE, "released_at": now, "release_reason": "checkpoint", "release_proof": "signed-handoff"})
            leases_doc["leases"][key] = lease
            # A draining worker must not be assigned new heavy work.
            workers_doc = self._read("workers")
            worker_changed = False
            if holder in workers_doc.get("workers", {}):
                worker = workers_doc["workers"][holder]
                worker["mode"] = worker_mode
                worker["availability"] = False
                worker["revision"] = int(worker.get("revision", 0)) + 1
                worker_changed = True
            updates = {"checkpoints": cp_doc, "tasks": task_doc, "handoffs": handoffs_doc, "leases": leases_doc}
            event_specs: list[tuple[str, Mapping[str, Any]]] = [
                ("checkpoint.written", {"task_id": task_id, "checkpoint_id": checkpoint_id, "holder": holder}),
                ("task.checkpointed", {"task_id": task_id, "checkpoint_id": checkpoint_id, "holder": holder}),
                ("handoff.created", {"handoff_id": checkpoint_id, "task_id": task_id, "from_holder": holder}),
                ("lease.released", {"kind": "task", "resource_id": task_id, "holder": holder, "epoch": epoch, "reason": "checkpoint"}),
            ]
            if worker_changed:
                updates["workers"] = workers_doc
                event_specs.append(("worker.draining", {"worker_id": holder, "task_id": task_id}))
            self._atomic_transaction(updates, event_specs)
            return {"status": "checkpointed", "checkpoint": checkpoint, "task": dict(task), "lease": lease, "replacement_input_revision": int(task["revision"])}

    request_checkpoint = checkpoint_task
    checkpoint_and_release = checkpoint_task
    handover_task = checkpoint_task

    def claim_replacement(self, task_id: str, worker_id: str, checkpoint_id: str, *, ttl: float = 60.0,
                          expected_task_revision: int | None = None,
                          expected_checkpoint_hash: str | None = None,
                          checkpoint_hash: str | None = None) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        checkpoint_id = _clean_id(checkpoint_id, "checkpoint_id")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            task = self._read("tasks").get("tasks", {}).get(task_id)
            checkpoint = self._read("checkpoints").get("checkpoints", {}).get(checkpoint_id)
            if task is None or checkpoint is None or task.get("checkpoint_id") != checkpoint_id:
                raise FencedError("checkpoint does not match the current task")
            expected_checkpoint_hash = expected_checkpoint_hash or checkpoint_hash
            checkpoint_for_hash = dict(checkpoint)
            checkpoint_for_hash.pop("checkpoint_hash", None)
            if expected_checkpoint_hash is not None and _sha256(checkpoint_for_hash) != expected_checkpoint_hash:
                raise FencedError("checkpoint hash changed")
            if task.get("recovery_required"):
                raise RecoveryRequired(f"task {task_id} requires recovery before replacement")
            if task.get("status") != "checkpointed":
                raise LeaseConflict(f"task {task_id} has already been resumed or completed")
            if expected_task_revision is not None and int(task.get("revision", 0)) != int(expected_task_revision):
                raise FencedError("checkpoint task revision changed")
            # Delegate to a lock-free internal acquisition to avoid nested lock.
            return self._acquire_lease_locked("task", task_id, worker_id, ttl=ttl, expected_task_revision=int(task["revision"]), handoff_id=checkpoint_id)

    def _acquire_lease_locked(self, kind: str, resource_id: str, holder: str, *, ttl: float,
                              expected_task_revision: int | None = None, handoff_id: str | None = None) -> dict[str, Any]:
        """Single locked lease CAS used by public and routing callers."""
        kind = _clean_id(kind, "lease kind")
        resource_id = _clean_id(resource_id, "resource_id")
        holder = _clean_id(holder, "holder")
        if ttl <= 0:
            raise InvalidRequest("lease ttl must be positive")
        key = self._lease_key(kind, resource_id)
        leases_doc = self._read("leases")
        workers = self._read("workers").get("workers", {})
        if holder not in workers and kind != "coordinator":
            raise InvalidRequest(f"unknown worker: {holder}")
        current = leases_doc.get("leases", {}).get(key)
        now = _now_from(self.clock)
        task_revision = None
        task_doc: dict[str, Any] | None = None
        handoffs_doc: dict[str, Any] | None = None
        task: dict[str, Any] | None = None
        if kind == "task":
            task_doc = self._read("tasks")
            task = task_doc["tasks"].get(resource_id)
            if task is None:
                raise InvalidRequest(f"unknown task: {resource_id}")
            # Fail closed on task state before inspecting a potentially still
            # active lease, matching the public error semantics and avoiding
            # any invitation to replay a known recovery-required task.
            if task.get("recovery_required"):
                raise RecoveryRequired(f"task {resource_id} requires recovery before replay")
            if task.get("status") == "checkpointed" and not handoff_id:
                raise FencedError(f"task {resource_id} must resume from its checkpoint")
            if task.get("status") == "completed":
                raise LeaseConflict(f"task {resource_id} is already completed")
        if current and current.get("state") == ACTIVE_LEASE:
            if float(current.get("expires_at", 0)) > now:
                raise LeaseConflict(f"{key} is held by {current.get('holder')}")
            prior_holder = str(current.get("holder"))
            prior_alive = self._holder_process_alive_locked(prior_holder)
            prior_worker = workers.get(prior_holder, {})
            if prior_alive is True or (prior_alive is None and prior_worker.get("mode") not in TERMINAL_WORKER_MODES):
                raise LeaseConflict(f"expired {key} still needs terminal-process evidence")
        if kind == "task":
            assert task_doc is not None and task is not None
            claimed_by = (task.get("handoff") or {}).get("claimed_by")
            if claimed_by and claimed_by != holder:
                prior_alive = self._holder_process_alive_locked(str(claimed_by))
                can_reclaim = bool(current and current.get("state") == ACTIVE_LEASE and float(current.get("expires_at", 0)) <= now and prior_alive is False)
                if not can_reclaim:
                    raise LeaseConflict(f"task {resource_id} already resumed by {claimed_by}")
            if expected_task_revision is not None and int(task.get("revision", 0)) != int(expected_task_revision):
                raise FencedError("task revision changed")
            task["revision"] = int(task.get("revision", 0)) + 1
            task["assignee"] = holder
            task["status"] = "working"
            task["blocked_reason"] = None
            if handoff_id:
                if task.get("checkpoint_id") != handoff_id and (task.get("handoff") or {}).get("checkpoint_id") != handoff_id:
                    raise FencedError("handoff checkpoint does not match task")
                handoffs_doc = self._read("handoffs")
                handoff = handoffs_doc.get("handoffs", {}).get(handoff_id)
                if handoff is None:
                    raise FencedError("handoff record is missing")
                task.setdefault("handoff", {})["claimed_by"] = holder
                task["handoff"]["claimed_at"] = now
            task_revision = int(task["revision"])
            task_doc["tasks"][resource_id] = task
            if handoff_id:
                handoff = dict(handoff)
                handoff["claimed_by"] = holder
                handoff["claimed_at"] = now
                handoffs_doc["handoffs"][handoff_id] = handoff
        previous_epoch = int(current.get("epoch", 0)) if current else 0
        lease = {
            "lease_id": _token(), "kind": kind, "resource_id": resource_id,
            "holder": holder, "epoch": previous_epoch + 1, "fencing_token": _token(),
            "revision": int(self._read("meta").get("revision", 0)) + 1,
            "state": ACTIVE_LEASE, "created_at": now, "expires_at": now + float(ttl),
            "released_at": None, "release_reason": None, "release_proof": None,
            "task_revision": task_revision,
        }
        leases_doc.setdefault("leases", {})[key] = lease
        updates: dict[str, dict[str, Any]] = {"leases": leases_doc}
        event_specs: list[tuple[str, Mapping[str, Any]]] = []
        if kind == "task" and task_doc is not None:
            updates["tasks"] = task_doc
            event_specs.append(("task.claimed", {"task_id": resource_id, "holder": holder, "handoff_id": handoff_id}))
        if handoff_id and handoffs_doc is not None:
            updates["handoffs"] = handoffs_doc
            event_specs.append(("handoff.claimed", {"handoff_id": handoff_id, "task_id": resource_id, "holder": holder}))
        event_specs.append(("lease.acquired", {"kind": kind, "resource_id": resource_id, "holder": holder, "epoch": lease["epoch"], "handoff_id": handoff_id}))
        self._atomic_transaction(updates, event_specs)
        return dict(lease)

    def resolve_recovery(self, task_id: str, *, resolution: str, receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        if not resolution.strip():
            raise InvalidRequest("resolution is required")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("tasks")
            task = doc.get("tasks", {}).get(task_id)
            if task is None:
                raise InvalidRequest(f"unknown task: {task_id}")
            if not task.get("recovery_required"):
                return dict(task)
            task["revision"] = int(task.get("revision", 0)) + 1
            task["recovery_required"] = False
            task["recovery_reason"] = None
            task["blocked_reason"] = None
            task["status"] = "checkpointed" if task.get("checkpoint_id") else "queued"
            task["last_receipt"] = _safe(dict(receipt or {"resolution": resolution}))
            doc["tasks"][task_id] = task
            self._commit("tasks", doc, "task.recovery_resolved", {"task_id": task_id, "resolution": resolution})
            return dict(task)

    def mark_recovery_required(self, task_id: str, reason: str) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        if not reason.strip():
            raise InvalidRequest("recovery reason is required")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._mark_recovery_locked(task_id, reason)

    recover_task = resolve_recovery

    def begin_operation(self, task_id: str, holder: str, epoch: int, fencing_token: str, *, operation_kind: str, operation_id: str | None = None) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        operation_kind = _clean_id(operation_kind, "operation_kind")
        operation_id = operation_id or _token()
        key = self._lease_key("task", task_id)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            task = self._read("tasks").get("tasks", {}).get(task_id)
            if task is None:
                raise InvalidRequest(f"unknown task: {task_id}")
            if task.get("recovery_required"):
                raise RecoveryRequired(f"task {task_id} requires recovery before replay")
            lease = self._read("leases").get("leases", {}).get(key)
            if not self._lease_current_locked(lease, holder, epoch, fencing_token):
                raise FencedError("operation holder no longer owns the task lease")
            doc = self._read("operations")
            operation = {"operation_id": operation_id, "task_id": task_id, "holder": holder, "epoch": int(epoch), "kind": operation_kind, "status": "in-flight", "started_at": _now_from(self.clock), "finished_at": None}
            doc.setdefault("operations", {})[operation_id] = operation
            self._commit("operations", doc, "operation.started", {"task_id": task_id, "operation_id": operation_id, "kind": operation_kind})
            return operation

    def finish_operation(self, operation_id: str, *, status: str, receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
        operation_id = _clean_id(operation_id, "operation_id")
        status = _clean_id(status, "status").lower()
        if status not in {"committed", "failed", "unknown"}:
            raise InvalidRequest("operation status must be committed, failed, or unknown")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("operations")
            operation = doc.get("operations", {}).get(operation_id)
            if operation is None:
                raise InvalidRequest(f"unknown operation: {operation_id}")
            if operation.get("status") != "in-flight":
                return dict(operation)
            operation = dict(operation)
            operation.update({"status": status, "finished_at": _now_from(self.clock), "receipt": _safe(dict(receipt or {}))})
            doc["operations"][operation_id] = operation
            if status == "unknown":
                task_doc, _ = self._mark_recovery_state_locked(operation["task_id"], "unknown-operation-completion")
                self._atomic_transaction(
                    {"operations": doc, "tasks": task_doc},
                    [
                        ("operation.finished", {"operation_id": operation_id, "status": status}),
                        ("task.recovery_required", {"task_id": operation["task_id"], "reason": "unknown-operation-completion", "operation_id": operation_id}),
                    ],
                )
            else:
                self._atomic_transaction({"operations": doc}, [("operation.finished", {"operation_id": operation_id, "status": status})])
            return operation

    def replay_operation(self, task_id: str, operation_id: str) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        operation_id = _clean_id(operation_id, "operation_id")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            task = self._task_locked(task_id)
            if task.get("recovery_required"):
                raise RecoveryRequired(f"task {task_id} requires recovery before replay")
            if task.get("status") in TERMINAL_TASK_STATUSES:
                raise RecoveryRequired(f"task {task_id} is already terminal; replay is fenced")
            operation = self._read("operations").get("operations", {}).get(operation_id)
            if operation is None:
                raise InvalidRequest(f"unknown operation: {operation_id}")
            if operation.get("status") not in {"failed"}:
                raise RecoveryRequired("only an explicitly failed operation may be replayed")
            return dict(operation)

    # -- result publication ----------------------------------------------------

    def publish_result(
        self,
        task_id: str,
        holder: str,
        epoch: int,
        fencing_token: str,
        input_revision: int,
        result: Any,
        *,
        result_id: str | None = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        result_id = result_id or _sha256(result)[:24]
        key = self._lease_key("task", task_id)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            leases = self._read("leases").get("leases", {})
            lease = leases.get(key)
            task_doc = self._read("tasks")
            task = task_doc.get("tasks", {}).get(task_id)
            if task is None:
                raise InvalidRequest(f"unknown task: {task_id}")
            existing_id = task.get("result_id")
            if existing_id is not None:
                if existing_id == result_id and task.get("accepted_holder") == holder and int(task.get("accepted_epoch", -1)) == int(epoch) and task.get("accepted_token") == fencing_token:
                    return {"status": "duplicate", "accepted": False, "integrated": False, "result_id": result_id, "task": dict(task)}
                raise FencedError("a result has already been published for this task")
            if not self._lease_current_locked(lease, holder, epoch, fencing_token):
                raise FencedError(f"late or foreign result for task {task_id}")
            if int(task.get("revision", 0)) != int(input_revision):
                raise FencedError(f"task {task_id} input revision changed")
            digest = _sha256(result)
            result_doc = self._read("results")
            record = {
                "result_id": result_id, "task_id": task_id, "holder": holder,
                "epoch": int(epoch), "fencing_token": fencing_token,
                "input_revision": int(input_revision), "result_hash": digest,
                "result": _safe(result), "receipt": _safe(dict(receipt or {})),
                "published_at": _now_from(self.clock), "integrated": True,
            }
            result_doc.setdefault("results", {})[task_id] = record
            task["revision"] = int(task.get("revision", 0)) + 1
            task.update({"status": "completed", "result_id": result_id, "result_hash": digest, "accepted_holder": holder, "accepted_epoch": int(epoch), "accepted_token": fencing_token, "integrated_count": int(task.get("integrated_count", 0)) + 1, "last_receipt": _safe(dict(receipt or {}))})
            task_doc["tasks"][task_id] = task
            handoff_id = task.get("checkpoint_id")
            handoffs_doc: dict[str, Any] | None = None
            if handoff_id:
                handoffs_doc = self._read("handoffs")
                handoff = handoffs_doc.get("handoffs", {}).get(handoff_id)
                if handoff is not None:
                    handoff = dict(handoff)
                    handoff["completed_at"] = _now_from(self.clock)
                    handoffs_doc["handoffs"][handoff_id] = handoff
            lease_doc = self._read("leases")
            lease = dict(lease)
            lease.update({"state": RELEASED_LEASE, "released_at": _now_from(self.clock), "release_reason": "result-integrated", "release_proof": "canonical-result"})
            lease_doc["leases"][key] = lease
            updates: dict[str, dict[str, Any]] = {"results": result_doc, "tasks": task_doc, "leases": lease_doc}
            event_specs: list[tuple[str, Mapping[str, Any]]] = [
                ("result.accepted", {"task_id": task_id, "result_id": result_id, "holder": holder, "epoch": epoch}),
                ("result.integrated", {"task_id": task_id, "result_id": result_id, "integrated_count": task["integrated_count"]}),
            ]
            if handoff_id and handoffs_doc is not None and handoff_id in handoffs_doc.get("handoffs", {}):
                updates["handoffs"] = handoffs_doc
                event_specs.append(("handoff.completed", {"handoff_id": handoff_id, "task_id": task_id, "result_id": result_id}))
            event_specs.append(("lease.released", {"kind": "task", "resource_id": task_id, "holder": holder, "epoch": epoch, "reason": "result-integrated"}))
            self._atomic_transaction(updates, event_specs)
            return {"status": "accepted", "accepted": True, "integrated": True, "result": record, "task": dict(task), "lease": lease}

    publish_task_result = publish_result
    integrate_result = publish_result
    publish_output = publish_result

    # -- quota and routing -----------------------------------------------------

    def capture_quota(
        self,
        service: str,
        account_alias: str,
        window: str,
        *,
        direction: str,
        value: float,
        reset_at: float | None = None,
        captured_at: float | None = None,
        stale: bool = False,
        exhausted: bool | None = None,
        snapshot_id: str | None = None,
        worker_id: str | None = None,
        window_id: str | None = None,
    ) -> dict[str, Any]:
        service = _clean_id(service, "service")
        account_alias = _clean_id(account_alias, "account_alias")
        window = _clean_id(window, "window")
        direction = _clean_id(direction, "direction").lower()
        if direction not in {"used", "remaining"}:
            raise InvalidRequest("quota direction must be used or remaining")
        value = float(value)
        if exhausted is None:
            exhausted = value <= 0 if direction == "remaining" else value >= 100.0
        snapshot_id = snapshot_id or _token()
        captured_at = _now_from(self.clock) if captured_at is None else float(captured_at)
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("quotas")
            workers_doc: dict[str, Any] | None = None
            worker: dict[str, Any] | None = None
            if worker_id is not None:
                workers_doc = self._read("workers")
                worker = workers_doc.get("workers", {}).get(worker_id)
                if worker is None:
                    raise InvalidRequest(f"unknown worker: {worker_id}")
            snapshot = {
                "snapshot_id": snapshot_id, "service": service, "account_alias": account_alias,
                "window": window, "window_id": window_id or window, "capture_time": captured_at,
                "captured_at": captured_at,
                "direction": direction, "value": value, "reset_time": reset_at,
                "reset_at": reset_at,
                "stale": bool(stale), "exhausted": bool(exhausted),
            }
            doc.setdefault("snapshots", {})[snapshot_id] = snapshot
            updates: dict[str, dict[str, Any]] = {"quotas": doc}
            event_specs: list[tuple[str, Mapping[str, Any]]] = [(
                "quota.captured",
                {"snapshot_id": snapshot_id, "service": service, "account_alias": account_alias, "window": window, "stale": bool(stale), "exhausted": bool(exhausted)},
            )]
            if worker_id is not None and workers_doc is not None and worker is not None:
                worker["quota_snapshot_id"] = snapshot_id
                worker["availability"] = not bool(exhausted) and not bool(stale)
                if exhausted:
                    worker["mode"] = "quota-blocked"
                elif worker.get("mode") in {"quota-blocked", "reset-pending"}:
                    worker["mode"] = "available"
                worker["revision"] = int(worker.get("revision", 0)) + 1
                updates["workers"] = workers_doc
                event_specs.append(("worker.quota_bound", {"worker_id": worker_id, "snapshot_id": snapshot_id, "exhausted": bool(exhausted)}))
            self._atomic_transaction(updates, event_specs)
            return snapshot

    record_quota_snapshot = capture_quota
    record_quota = capture_quota

    def _quota_snapshot_locked(self, snapshot_id: str) -> dict[str, Any]:
        value = self._read("quotas").get("snapshots", {}).get(_clean_id(snapshot_id, "snapshot_id"))
        if value is None:
            raise InvalidRequest(f"unknown quota snapshot: {snapshot_id}")
        return dict(value)

    def quota_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Read one quota snapshot through the lock/recovery boundary."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._quota_snapshot_locked(snapshot_id)

    get_quota_snapshot = quota_snapshot

    def _quota_eligible_locked(self, worker: Mapping[str, Any], *, service: str | None = None,
                               account_alias: str | None = None, window: str | None = None,
                               required_tokens: float = 0, max_age: float = 900.0,
                               now: float | None = None) -> tuple[bool, str]:
        sid = worker.get("quota_snapshot_id")
        if not sid:
            return False, "quota-missing"
        snapshot = self._read("quotas").get("snapshots", {}).get(sid)
        if snapshot is None:
            return False, "quota-missing"
        if snapshot.get("stale"):
            return False, "quota-stale"
        if service is not None and snapshot.get("service") != service:
            return False, "quota-service-mismatch"
        if account_alias is not None and snapshot.get("account_alias") != account_alias:
            return False, "quota-account-mismatch"
        if window is not None and snapshot.get("window") != window:
            return False, "quota-window-mismatch"
        current = _now_from(self.clock) if now is None else float(now)
        if current - float(snapshot.get("capture_time", 0)) > float(max_age):
            return False, "quota-old"
        # Reaching reset_time does not magically refresh a snapshot.  A fresh
        # exhausted capture remains unavailable until a newer non-exhausted
        # snapshot is recorded.
        if snapshot.get("exhausted"):
            return False, "quota-exhausted"
        if snapshot.get("direction") == "remaining" and float(snapshot.get("value", 0)) <= float(required_tokens):
            return False, "quota-insufficient"
        if worker.get("mode") in {"draining", "quota-blocked", "reset-pending", "failed", "stopped"}:
            return False, f"mode-{worker.get('mode')}"
        if not worker.get("availability", False):
            return False, "availability-false"
        return True, "eligible"

    def worker_available(self, worker_id: str, *, service: str | None = None,
                         account_alias: str | None = None, window: str | None = None,
                         required_tokens: float = 0, max_age: float = 900.0,
                         purpose: str = "task") -> bool:
        with self._thread_lock, self._lock():
            self._ensure_locked()
            worker = self._worker_locked(worker_id)
            ok, _ = self._quota_eligible_locked(worker, service=service, account_alias=account_alias, window=window, required_tokens=required_tokens, max_age=max_age)
            if purpose == "question" and worker.get("mode") == "reserve" and int(worker.get("question_budget", 0)) <= 0:
                return False
            return ok

    is_available = worker_available

    def route_task(
        self,
        task_id: str,
        *,
        capabilities: Sequence[str] | None = None,
        service: str | None = None,
        account_alias: str | None = None,
        window: str | None = None,
        required_tokens: float = 0,
        preferred_worker: str | None = None,
        ttl: float = 60.0,
    ) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            task = self._task_locked(task_id)
            if task.get("recovery_required"):
                return {"status": "recovery-required", "task_id": task_id, "yield": True, "busy_loop": False, "rejected": []}
            if task.get("status") == "checkpointed":
                return {"status": "checkpointed", "task_id": task_id, "requires_handoff": True, "handoff": task.get("handoff"), "yield": True, "busy_loop": False, "rejected": []}
            if task.get("status") in TERMINAL_TASK_STATUSES:
                return {"status": task.get("status"), "task_id": task_id, "already_integrated": bool(task.get("result_id")), "yield": False, "busy_loop": False, "rejected": []}
            required = set(_as_list(capabilities)) or set(task.get("capabilities", []))
            workers = self._read("workers").get("workers", {})
            ordered = list(workers)
            if preferred_worker in ordered:
                ordered.remove(preferred_worker)
                ordered.insert(0, preferred_worker)
            rejected: list[dict[str, str]] = []
            for worker_id in ordered:
                worker = workers[worker_id]
                if not required.issubset(set(worker.get("capabilities", []))):
                    rejected.append({"worker_id": worker_id, "reason": "capability-mismatch"})
                    continue
                ok, reason = self._quota_eligible_locked(worker, service=service, account_alias=account_alias, window=window, required_tokens=required_tokens)
                if not ok:
                    rejected.append({"worker_id": worker_id, "reason": reason})
                    continue
                try:
                    # Selection, quota validation and lease CAS share this
                    # lock, so a concurrent result/quota change cannot route
                    # from a split projection.
                    lease = self._acquire_lease_locked("task", task_id, worker_id, ttl=ttl, expected_task_revision=int(task.get("revision", 0)))
                except LeaseConflict as exc:
                    current = self._lease_locked("task", task_id)
                    if current and current.get("state") == ACTIVE_LEASE:
                        return {"status": "already-routed", "task_id": task_id, "worker_id": current.get("holder"), "lease": dict(current), "rejected": rejected}
                    rejected.append({"worker_id": worker_id, "reason": type(exc).__name__})
                    continue
                except FencedError as exc:
                    rejected.append({"worker_id": worker_id, "reason": type(exc).__name__})
                    continue
                return {"status": "routed", "worker_id": worker_id, "lease": lease, "rejected": rejected}
            # Persist one blocked decision and yield.  There is intentionally
            # no retry loop or prompt submission here.
            doc = self._read("tasks")
            current = doc["tasks"][task_id]
            if not current.get("recovery_required"):
                current["revision"] = int(current.get("revision", 0)) + 1
                current["status"] = "blocked"
                current["blocked_reason"] = "all-providers-unavailable"
                doc["tasks"][task_id] = current
                self._commit("tasks", doc, "routing.blocked", {"task_id": task_id, "rejected": rejected, "yield": True, "attempts": 1})
            else:
                self._atomic_transaction({}, [("routing.blocked", {"task_id": task_id, "reason": "recovery-required", "yield": True, "attempts": 1})])
            return {"status": "blocked", "task_id": task_id, "reason": "all-providers-unavailable", "yield": True, "busy_loop": False, "rejected": rejected}

    def route_question(
        self,
        question: str,
        *,
        capabilities: Sequence[str] | None = None,
        service: str | None = None,
        account_alias: str | None = None,
        window: str | None = None,
        required_tokens: float = 0,
        preferred_worker: str | None = None,
        deputy_worker: str | None = None,
        task_id: str | None = None,
        bounded: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise InvalidRequest("question is required")
        if not bounded:
            # Unbounded delegation is outside the reserve-question contract;
            # keep the refusal durable without submitting any prompt.
            with self._thread_lock, self._lock():
                self._ensure_locked()
                _, events = self._atomic_transaction({}, [("question.refused", {"reason": "unbounded-question", "yield": True, "busy_loop": False})])
                event = events[0]
            return {"status": "refused", "worker_id": None, "accepted": False, "yield": True, "busy_loop": False, "event": event, "rejected": [{"reason": "unbounded-question"}]}
        required = set(_as_list(capabilities))
        # Selection, quota validation and the bounded reserve decrement all
        # happen under one recovery-aware lock.  A route cannot be based on a
        # projection that is being replaced by a concurrent publish/quota WAL.
        with self._thread_lock, self._lock():
            self._ensure_locked()
            workers = self._read("workers").get("workers", {})
            ordered = list(workers)
            if preferred_worker in ordered:
                ordered.remove(preferred_worker)
                ordered.insert(0, preferred_worker)
            if deputy_worker in ordered and preferred_worker is None:
                ordered.remove(deputy_worker)
                ordered.insert(0, deputy_worker)
            elif deputy_worker in ordered:
                ordered.remove(deputy_worker)
                ordered.append(deputy_worker)
            rejected: list[dict[str, str]] = []
            for worker_id in ordered:
                worker = workers[worker_id]
                if required and not required.issubset(set(worker.get("capabilities", []))):
                    rejected.append({"worker_id": worker_id, "reason": "capability-mismatch"})
                    continue
                if worker.get("mode") == "reserve":
                    if int(worker.get("question_budget", 0)) <= 0:
                        rejected.append({"worker_id": worker_id, "reason": "question-budget-exhausted"})
                        continue
                ok, reason = self._quota_eligible_locked(worker, service=service, account_alias=account_alias, window=window, required_tokens=required_tokens)
                if not ok:
                    rejected.append({"worker_id": worker_id, "reason": reason})
                    continue
                # Question consumption is one bounded decision, not an
                # open-ended worker spawn.  Persist the decrement before
                # returning while still holding the selection lock.
                doc = self._read("workers")
                current = doc["workers"][worker_id]
                if current.get("mode") == "reserve":
                    current["question_budget"] = max(0, int(current.get("question_budget", 0)) - 1)
                    current["revision"] = int(current.get("revision", 0)) + 1
                    doc["workers"][worker_id] = current
                    self._commit("workers", doc, "question.reserved", {"worker_id": worker_id, "bounded": True, "task_id": task_id})
                else:
                    self._atomic_transaction({}, [("question.routed", {"worker_id": worker_id, "bounded": True, "task_id": task_id})])
                return {"status": "routed", "worker_id": worker_id, "bounded": True, "rejected": rejected}
            task_doc: dict[str, Any] | None = None
            if task_id:
                task_doc = self._read("tasks")
                task = task_doc.get("tasks", {}).get(task_id)
                if task is not None:
                    task["pending_question"] = {"question_hash": _sha256(question), "capabilities": sorted(required), "recorded_at": _now_from(self.clock)}
                    task["status"] = "blocked" if not task.get("recovery_required") else task["status"]
                    task["revision"] = int(task.get("revision", 0)) + 1
                    task_doc["tasks"][task_id] = task
            updates: dict[str, dict[str, Any]] = {}
            event_specs: list[tuple[str, Mapping[str, Any]]] = [(
                "question.blocked",
                {"task_id": task_id, "reason": "all-providers-unavailable", "yield": True, "busy_loop": False, "rejected": rejected},
            )]
            if task_doc is not None and task_id in task_doc.get("tasks", {}):
                updates["tasks"] = task_doc
                event_specs.append(("question.persisted", {"task_id": task_id, "question_hash": _sha256(question)}))
            _, events = self._atomic_transaction(updates, event_specs)
            event = events[0]
        return {"status": "blocked", "worker_id": None, "yield": True, "busy_loop": False, "event": event, "rejected": rejected}

    route = route_task
    route_provider = route_task

    # -- bounded request/refusal ----------------------------------------------

    def evaluate_request(
        self,
        task_id: str,
        sender: str,
        action: str,
        *,
        paths: Sequence[str] | None = None,
        requires_credentials: bool = False,
        unrestricted_spawn: bool = False,
        spawn_count: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = _clean_id(task_id, "task_id")
        sender = _clean_id(sender, "sender")
        action = _clean_id(action, "action")
        task = self.task(task_id)
        requested_paths = _as_list(paths)
        reasons: list[str] = []
        allowed = task.get("allowed_paths", [])
        for path in requested_paths:
            normalized = Path(path).as_posix()
            if not allowed or not any(fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized.lstrip("./"), pattern.lstrip("./")) for pattern in allowed):
                reasons.append("outside-scope")
                break
        action_lower = action.lower()
        if requires_credentials or any(term in action_lower for term in ("credential", "password", "api key", "access token", "refresh token", "cookie")):
            reasons.append("credential-access")
        if unrestricted_spawn or spawn_count is None and ("spawn" in action_lower or "worker" in action_lower):
            reasons.append("unrestricted-spawn")
        if spawn_count is not None and int(spawn_count) < 0:
            reasons.append("unrestricted-spawn")
        if spawn_count is not None and int(spawn_count) > int(task.get("max_spawn", 3)):
            reasons.append("unrestricted-spawn")
        request_id = _token()
        request = {
            "request_id": request_id, "task_id": task_id, "sender": sender,
            "action": action, "paths": requested_paths, "accepted": not reasons,
            "reasons": sorted(set(reasons)), "recorded_at": _now_from(self.clock),
            "metadata": _safe(dict(metadata or {})),
        }
        with self._thread_lock, self._lock():
            self._ensure_locked()
            doc = self._read("requests")
            doc.setdefault("requests", {})[request_id] = request
            kind = "request.refused" if reasons else "request.accepted"
            self._commit("requests", doc, kind, {"request_id": request_id, "task_id": task_id, "sender": sender, "reason_codes": sorted(set(reasons))})
        if reasons:
            return {"status": "refused", "accepted": False, "request": request}
        return {"status": "accepted", "accepted": True, "request": request}

    request = evaluate_request
    record_request = evaluate_request

    def require_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        decision = self.evaluate_request(*args, **kwargs)
        if not decision.get("accepted"):
            reasons = ",".join(decision["request"].get("reasons", []))
            raise ScopeRefused(f"request refused: {reasons}")
        return decision

    submit_request = require_request

    # -- immutable inbox/outbox and handoff records ---------------------------

    def send_message(
        self,
        task_id: str,
        sender: str,
        recipient: str,
        kind: str,
        *,
        state: str = "pending",
        artifact_references: Sequence[str] | None = None,
        payload: Mapping[str, Any] | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a small, redacted peer message to outbox and inbox.

        Messages are immutable records.  ``acknowledge_message`` writes an
        acknowledgement in the recipient's inbox instead of rewriting the
        original payload, which preserves a replayable handoff history.
        """
        task_id = _clean_id(task_id, "task_id")
        sender = _clean_id(sender, "sender")
        recipient = _clean_id(recipient, "recipient")
        kind = _clean_id(kind, "message kind")
        if state not in {"pending", "acknowledged", "completed", "refused"}:
            raise InvalidRequest("unsupported message state")
        message_id = message_id or _token()
        with self._thread_lock, self._lock():
            self._ensure_locked()
            existing_outbox = self._read("outbox").get("messages", {}).get(message_id)
            existing_inbox = self._read("inbox").get("messages", {}).get(message_id)
            if existing_outbox is not None or existing_inbox is not None:
                existing = existing_outbox or existing_inbox
                if existing_outbox == existing_inbox and all(existing.get(field) == expected for field, expected in {
                    "task_id": task_id,
                    "sender": sender,
                    "recipient": recipient,
                    "kind": kind,
                }.items()):
                    # A retried send with the same immutable ID is a safe
                    # idempotent replay after a crash/restart.
                    return dict(existing)
                raise FencedError(f"message id is already used: {message_id}")
            revision = int(self._read("meta").get("revision", 0)) + 1
            message = {
                "message_id": message_id,
                "task_id": task_id,
                "sender": sender,
                "recipient": recipient,
                "kind": kind,
                "timestamp": _now_from(self.clock),
                "state_revision": revision,
                "state": state,
                "artifact_references": _as_list(artifact_references),
                "payload": _safe(dict(payload or {})),
                "acknowledged_at": None,
            }
            outbox = self._read("outbox")
            inbox = self._read("inbox")
            outbox.setdefault("messages", {})[message_id] = message
            inbox.setdefault("messages", {})[message_id] = message
            # Both files carry the same immutable message; the event and pair
            # are one prepared transaction so a crash cannot split them.
            self._atomic_transaction(
                {"outbox": outbox, "inbox": inbox},
                [("message.sent", {"message_id": message_id, "task_id": task_id, "sender": sender, "recipient": recipient, "kind": kind})],
            )
            return dict(message)

    def acknowledge_message(self, message_id: str, recipient: str, *, state: str = "acknowledged") -> dict[str, Any]:
        message_id = _clean_id(message_id, "message_id")
        recipient = _clean_id(recipient, "recipient")
        if state not in {"acknowledged", "completed", "refused"}:
            raise InvalidRequest("unsupported acknowledgement state")
        with self._thread_lock, self._lock():
            self._ensure_locked()
            inbox = self._read("inbox")
            message = inbox.get("messages", {}).get(message_id)
            if message is None:
                raise InvalidRequest(f"unknown message: {message_id}")
            if message.get("recipient") != recipient:
                raise FencedError("only the message recipient may acknowledge it")
            if message.get("acknowledged_at") is not None:
                return dict(message)
            revision = int(self._read("meta").get("revision", 0)) + 1
            updated = dict(message)
            updated["state"] = state
            updated["acknowledged_at"] = _now_from(self.clock)
            updated["ack_state_revision"] = revision
            inbox["messages"][message_id] = updated
            inbox["revision"] = revision
            acknowledged_ids = list(inbox.get("acknowledged_ids", []))
            if message_id not in acknowledged_ids:
                acknowledged_ids.append(message_id)
            inbox["acknowledged_ids"] = acknowledged_ids
            self._atomic_transaction({"inbox": inbox}, [("message.acknowledged", {"message_id": message_id, "recipient": recipient, "state": state})])
            return updated

    def _message_locked(self, message_id: str) -> dict[str, Any]:
        message_id = _clean_id(message_id, "message_id")
        value = self._read("inbox").get("messages", {}).get(message_id)
        if value is None:
            raise InvalidRequest(f"unknown message: {message_id}")
        return dict(value)

    def message(self, message_id: str) -> dict[str, Any]:
        """Read one inbox message through the lock/recovery boundary."""
        with self._thread_lock, self._lock():
            self._ensure_locked()
            return self._message_locked(message_id)

    # -- convenience/status ----------------------------------------------------

    def recover(self) -> dict[str, Any]:
        """Reload persisted state without replaying integrations."""
        state = self.snapshot()
        # Recovered tasks retain result_id/integrated_count.  This operation is
        # observational and intentionally emits no mutation/event.
        return state

    def integration_count(self, task_id: str) -> int:
        return int(self.task(task_id).get("integrated_count", 0))


# Friendly names for callers that think of this as a state store rather than a
# coordinator.  They are aliases, not separate implementations or state roots.
StateStore = CoordinationState
CoordinationStore = CoordinationState


# -- CLI ----------------------------------------------------------------------

def _json_arg(value: str, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidRequest(f"invalid JSON argument: {value!r}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True, type=Path, help="explicit operational state directory (never source)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")
    ev = sub.add_parser("events")
    ev.add_argument("--after", type=int, default=-1)
    ev.add_argument("--limit", type=int)

    worker = sub.add_parser("register-worker", aliases=["worker-register"])
    worker.add_argument("worker_id")
    worker.add_argument("provider")
    worker.add_argument("--model")
    worker.add_argument("--account-alias")
    worker.add_argument("--capability", action="append", default=[])
    worker.add_argument("--mode", default="available")
    worker.add_argument("--quota-snapshot-id")
    worker.add_argument("--question-budget", type=int, default=0)
    worker.add_argument("--process-id")
    worker.add_argument("--process-alive", choices=["true", "false", "unknown"], default="unknown")

    task = sub.add_parser("register-task", aliases=["task-register"])
    task.add_argument("task_id")
    task.add_argument("--allowed-path", action="append", default=[])
    task.add_argument("--capability", action="append", default=[])
    task.add_argument("--dependency", action="append", default=[])
    task.add_argument("--input-hashes", default="{}")
    task.add_argument("--acceptance-command", action="append", default=[])
    task.add_argument("--max-spawn", type=int, default=3)

    acquire = sub.add_parser("acquire-lease", aliases=["lease-acquire"])
    acquire.add_argument("kind")
    acquire.add_argument("resource_id")
    acquire.add_argument("holder")
    acquire.add_argument("--ttl", type=float, default=60.0)
    acquire.add_argument("--expected-task-revision", type=int)

    release = sub.add_parser("release-lease", aliases=["lease-release"])
    release.add_argument("kind")
    release.add_argument("resource_id")
    release.add_argument("holder")
    release.add_argument("epoch", type=int)
    release.add_argument("fencing_token")
    release.add_argument("--reason", default="released")

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("task_id")
    checkpoint.add_argument("holder")
    checkpoint.add_argument("epoch", type=int)
    checkpoint.add_argument("fencing_token")
    checkpoint.add_argument("--state", default="{}")
    checkpoint.add_argument("--dirty-path", action="append", default=[])
    checkpoint.add_argument("--current-edit", action="append", default=[])
    checkpoint.add_argument("--output", action="append", default=[])
    checkpoint.add_argument("--test", action="append", default=[])
    checkpoint.add_argument("--unrun-check", action="append", default=[])
    checkpoint.add_argument("--completed-command", action="append", default=[])
    checkpoint.add_argument("--base-hash")
    checkpoint.add_argument("--head")
    checkpoint.add_argument("--operation-receipt", default="{}")
    checkpoint.add_argument("--pipeline-state", default="{}")
    checkpoint.add_argument("--observe-timeout", action="store_true")
    checkpoint.add_argument("--operation-kind")
    checkpoint.add_argument("--operation-status")
    checkpoint.add_argument("--worker-mode", default="draining")

    claim = sub.add_parser("claim-replacement")
    claim.add_argument("task_id")
    claim.add_argument("worker_id")
    claim.add_argument("checkpoint_id")
    claim.add_argument("--expected-task-revision", type=int)
    claim.add_argument("--expected-checkpoint-hash")
    claim.add_argument("--ttl", type=float, default=60.0)

    publish = sub.add_parser("publish-result", aliases=["result-publish"])
    publish.add_argument("task_id")
    publish.add_argument("holder")
    publish.add_argument("epoch", type=int)
    publish.add_argument("fencing_token")
    publish.add_argument("input_revision", type=int)
    publish.add_argument("result")
    publish.add_argument("--result-id")

    quota = sub.add_parser("quota-capture")
    quota.add_argument("service")
    quota.add_argument("account_alias")
    quota.add_argument("window")
    quota.add_argument("--direction", required=True, choices=["used", "remaining"])
    quota.add_argument("--value", required=True, type=float)
    quota.add_argument("--reset-at", type=float)
    quota.add_argument("--stale", action="store_true")
    quota.add_argument("--exhausted", action="store_true")
    quota.add_argument("--snapshot-id")
    quota.add_argument("--worker-id")

    route = sub.add_parser("route-task")
    route.add_argument("task_id")
    route.add_argument("--capability", action="append", default=[])
    route.add_argument("--service")
    route.add_argument("--window")
    route.add_argument("--preferred-worker")

    question = sub.add_parser("route-question")
    question.add_argument("question")
    question.add_argument("--capability", action="append", default=[])
    question.add_argument("--service")
    question.add_argument("--window")
    question.add_argument("--preferred-worker")
    question.add_argument("--deputy-worker")
    question.add_argument("--task-id")
    question.add_argument("--unbounded", action="store_true")

    request = sub.add_parser("request")
    request.add_argument("task_id")
    request.add_argument("sender")
    request.add_argument("action")
    request.add_argument("--path", action="append", default=[])
    request.add_argument("--requires-credentials", action="store_true")
    request.add_argument("--unrestricted-spawn", action="store_true")
    request.add_argument("--spawn-count", type=int)

    message = sub.add_parser("message")
    message.add_argument("task_id")
    message.add_argument("sender")
    message.add_argument("recipient")
    message.add_argument("kind")
    message.add_argument("--artifact-reference", action="append", default=[])
    message.add_argument("--payload", default="{}")
    ack = sub.add_parser("acknowledge")
    ack.add_argument("message_id")
    ack.add_argument("recipient")
    ack.add_argument("--state", default="acknowledged", choices=["acknowledged", "completed", "refused"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        state = CoordinationState(args.state_root)
        command = args.command
        if command == "init":
            result = state.initialize()
        elif command == "status":
            result = state.recover()
        elif command == "events":
            result = state.read_events(after=args.after, limit=args.limit)
        elif command in {"register-worker", "worker-register"}:
            alive = {"true": True, "false": False, "unknown": None}[args.process_alive]
            result = state.register_worker(args.worker_id, args.provider, model=args.model, account_alias=args.account_alias, capabilities=args.capability, mode=args.mode, quota_snapshot_id=args.quota_snapshot_id, question_budget=args.question_budget, process_id=args.process_id, process_alive=alive)
        elif command in {"register-task", "task-register"}:
            result = state.register_task(args.task_id, dependencies=args.dependency, allowed_paths=args.allowed_path, input_hashes=_json_arg(args.input_hashes, {}), acceptance_commands=args.acceptance_command, capability=args.capability, max_spawn=args.max_spawn)
        elif command in {"acquire-lease", "lease-acquire"}:
            result = state.acquire_lease(args.kind, args.resource_id, args.holder, ttl=args.ttl, expected_task_revision=args.expected_task_revision)
        elif command in {"release-lease", "lease-release"}:
            result = state.release_lease(args.kind, args.resource_id, args.holder, args.epoch, args.fencing_token, reason=args.reason)
        elif command == "checkpoint":
            result = state.checkpoint_task(args.task_id, args.holder, args.epoch, args.fencing_token, state=_json_arg(args.state, {}), dirty_paths=args.dirty_path, current_edits=args.current_edit, outputs={"paths": args.output}, tests=args.test, unrun_checks=args.unrun_check, completed_commands=args.completed_command, base_hash=args.base_hash, head=args.head, operation_receipt=_json_arg(args.operation_receipt, {}), pipeline_state=_json_arg(args.pipeline_state, {}), observe_timeout=args.observe_timeout, operation_kind=args.operation_kind, operation_status=args.operation_status, worker_mode=args.worker_mode)
        elif command == "claim-replacement":
            result = state.claim_replacement(args.task_id, args.worker_id, args.checkpoint_id, ttl=args.ttl, expected_task_revision=args.expected_task_revision, expected_checkpoint_hash=args.expected_checkpoint_hash)
        elif command in {"publish-result", "result-publish"}:
            result = state.publish_result(args.task_id, args.holder, args.epoch, args.fencing_token, args.input_revision, _json_arg(args.result), result_id=args.result_id)
        elif command == "quota-capture":
            result = state.capture_quota(args.service, args.account_alias, args.window, direction=args.direction, value=args.value, reset_at=args.reset_at, stale=args.stale, exhausted=True if args.exhausted else None, snapshot_id=args.snapshot_id, worker_id=args.worker_id)
        elif command == "route-task":
            result = state.route_task(args.task_id, capabilities=args.capability, service=args.service, window=args.window, preferred_worker=args.preferred_worker)
        elif command == "route-question":
            result = state.route_question(args.question, capabilities=args.capability, service=args.service, window=args.window, preferred_worker=args.preferred_worker, deputy_worker=args.deputy_worker, task_id=args.task_id, bounded=not args.unbounded)
        elif command == "request":
            result = state.evaluate_request(args.task_id, args.sender, args.action, paths=args.path, requires_credentials=args.requires_credentials, unrestricted_spawn=args.unrestricted_spawn, spawn_count=args.spawn_count)
        elif command == "message":
            result = state.send_message(args.task_id, args.sender, args.recipient, args.kind, artifact_references=args.artifact_reference, payload=_json_arg(args.payload, {}))
        elif command == "acknowledge":
            result = state.acknowledge_message(args.message_id, args.recipient, state=args.state)
        else:  # pragma: no cover - argparse enforces this
            raise InvalidRequest(f"unknown command: {command}")
        print(json.dumps(_safe(result), ensure_ascii=False, sort_keys=True))
        return 0
    except CoordinationError as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
