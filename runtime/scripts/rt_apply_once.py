"""One published candidate per approved plan, including lost-response retries.

An OS lock serializes hosts. A durable intent reserves the run before execution;
a verified receipt is the commit record. A crash without a receipt is unknown,
never permission to execute again. This protects process restarts, not power-loss
or hostile changes to the runtime's private state directory.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import re
import threading
import time
import uuid

from rt_apply import RECEIPT_NAME, list_candidates, read_receipt
from rt_codes import RpcError
from rt_jsonl import canonical_bytes, loads_strict
from rt_session import atomic_write_bytes


@contextmanager
def plan_lock(root, plan_id):
    if not re.fullmatch(r"[0-9a-f]{32}", plan_id):
        raise RpcError("invalid_params", "invalid plan identifier")
    directory = root / "apply-attempts"
    directory.mkdir(parents=True, exist_ok=True)
    # Never unlink a lock file: a waiter must not acquire a different inode.
    with (directory / f"{plan_id}.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RpcError("apply_in_progress", "this plan is locked by another apply; retry later",
                           planId=plan_id) from exc
        try:
            yield directory / f"{plan_id}.json"
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


#: How long a writer waits for another host's transition on the same session.
SESSION_LOCK_TIMEOUT_S = 300.0

_held = threading.local()


def _os_lock(handle, *, blocking: bool) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def session_lock(root, session_id, *, timeout=None):
    """One writer per session, across threads AND host processes on one root.

    Held from the ``plan_behind_head`` check through the receipt and the
    candidate write, and around every approval-record replacement and its
    event, so "is this plan still on the head?" and "publish it" are one step.
    The plan lock alone serialised one plan; two plans on the same base could
    both pass the head check before either receipt landed and publish siblings.

    Blocking (with a timeout), unlike the plan lock: a second transition on the
    same session is not a mistake, it simply goes second and then sees the
    head the first one produced. Re-entrant within a thread. The file is a
    separate open file description per acquisition, so threads of one process
    exclude each other exactly as processes do.
    """
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise RpcError("invalid_params", "invalid session identifier")
    path = (root / "locks" / f"session-{session_id}.lock")
    key = str(path)
    held = getattr(_held, "locks", None)
    if held is None:
        held = _held.locks = {}
    if key in held:
        held[key][1] += 1
        try:
            yield
        finally:
            held[key][1] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never unlink a lock file: a waiter must not acquire a different inode.
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + (SESSION_LOCK_TIMEOUT_S if timeout is None else timeout)
        while not _os_lock(handle, blocking=False):
            if time.monotonic() >= deadline:
                raise RpcError("apply_in_progress",
                               "another transition on this session holds its lock; retry later",
                               sessionId=session_id)
            time.sleep(0.05)
        held[key] = [handle, 1]
        try:
            yield
        finally:
            del held[key]
            _os_unlock(handle)
    finally:
        handle.close()


def verified_result(session, plan, approval, run_id):
    receipt = read_receipt(session, run_id)
    expected = {"runId": run_id, "sessionId": session.id,
                "planId": plan.id, "planHash": plan.hash}
    recorded = receipt.get("approval") or {}
    if (any(receipt.get(k) != v for k, v in expected.items())
            or recorded.get("approvalId") != approval.id
            or recorded.get("planId") != plan.id
            or recorded.get("planHash") != plan.hash
            or recorded.get("state") != "approved"):
        raise RpcError("approval_binding_mismatch", "published receipt does not bind this apply",
                       planId=plan.id, runId=run_id)
    return {"candidate": {
        "runId": run_id, "sessionId": session.id, "planId": plan.id,
        "candidate": receipt["candidate"], "base": receipt.get("base"),
        "reverses": receipt.get("reverses"), "checks": receipt["checks"],
        "receipt": f"{run_id}/{RECEIPT_NAME}", "canonical": True,
    }}


def apply_once(root, session, plan, approval, execute, reconcile):
    binding = {"sessionId": session.id, "planId": plan.id,
               "planHash": plan.hash, "approvalId": approval.id}
    with plan_lock(root, plan.id) as journal:
        def replay(run_id, completed):
            result = verified_result(session, plan, approval, run_id)
            if completed:
                # The transition already committed and reconciled: a retry
                # answers with the same candidate and changes nothing else —
                # no events, no supersession, no journal rewrite.
                return result
            reconcile(result, emit_events=True)
            atomic_write_bytes(journal, canonical_bytes({**binding, "runId": run_id, "state": "published"}))
            return result

        if journal.exists():
            try:
                attempt = loads_strict(journal.read_text(encoding="utf-8"))
                valid = (isinstance(attempt, dict)
                         and all(attempt.get(k) == v for k, v in binding.items() if k != "approvalId")
                         and isinstance(attempt.get("runId"), str)
                         and re.fullmatch(r"[0-9a-f]{32}", attempt["runId"])
                         and attempt.get("state") in {"pending", "not_applied", "published"})
            except (OSError, ValueError, UnicodeError):
                valid = False
            if not valid:
                raise RpcError("apply_outcome_unknown", "apply journal is unreadable or has a different binding",
                               planId=plan.id)
            run_id = attempt["runId"]
            if (session.candidates_dir / run_id / RECEIPT_NAME).exists():
                return replay(run_id, attempt["state"] == "published")
            if attempt["state"] != "not_applied":
                raise RpcError("apply_outcome_unknown", "previous apply has no verified receipt; reexecution is blocked",
                               planId=plan.id, runId=run_id)
        else:
            # Upgrade compatibility: an older runtime may have published before
            # this journal existed. Never silently duplicate its candidate.
            matches = [row for row in list_candidates(session) if row.get("planId") == plan.id]
            if len(matches) == 1:
                return replay(matches[0]["runId"], False)
            if matches or plan.state == "applied":
                raise RpcError("apply_outcome_unknown", "historical publication is ambiguous or missing",
                               planId=plan.id)
        run_id = uuid.uuid4().hex
        attempt = {**binding, "runId": run_id, "state": "pending"}
        atomic_write_bytes(journal, canonical_bytes(attempt))
        try:
            result = execute(run_id)
            atomic_write_bytes(journal, canonical_bytes({**attempt, "state": "published"}))
            return result
        except RpcError:
            # A handled refusal/cancellation is retryable only after the apply
            # path demonstrably removed BOTH of its private directories.
            if (not (session.candidates_dir / run_id).exists()
                    and not (session.work_dir / run_id).exists()):
                atomic_write_bytes(journal, canonical_bytes({**attempt, "state": "not_applied"}))
            raise
