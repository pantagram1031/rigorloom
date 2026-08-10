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
import shutil
import stat
import sys
import tempfile
from typing import Any

try:
    import hwp_ingress as _ingress
except ImportError:  # pragma: no cover - direct package import fallback
    from pipeline.scripts import hwp_ingress as _ingress

try:
    import diagnostic_candidate_core as _core
except ImportError:  # pragma: no cover - direct package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core


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
        data = _core.read_regular_once(path, MAX_BINARY_BYTES,
                                       "rhwp_binary_unavailable")
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)
    except (OSError, ValueError, TypeError):
        raise DiagnosticError("rhwp_binary_unavailable")
    if not data:
        raise DiagnosticError("rhwp_binary_invalid")
    # The configured binary's mode is untrusted metadata.  Stage with a fixed
    # owner-only executable mode rather than propagating setuid/setgid/sticky,
    # group, or world bits into the diagnostic snapshot.
    return data, hashlib.sha256(data).hexdigest(), 0o700


def _read_regular_once(path: Path, max_bytes: int, reason: str) -> bytes:
    try:
        return _core.read_regular_once(path, max_bytes, reason)
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


def _hash_binary(path: Path) -> str:
    try:
        return _core.hash_regular(path, MAX_BINARY_BYTES, "rhwp_binary_drift")
    except (_core.CoreError, OSError, ValueError, TypeError):
        raise DiagnosticError("rhwp_binary_drift")


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
        return _core.hash_regular(path, _ingress.MAX_INPUT_BYTES,
                                  "source_changed")
    except (DiagnosticError, _core.CoreError, _ingress.IngressError,
            OSError, ValueError, TypeError):
        raise DiagnosticError("source_changed")


def _configure_windows_job(proc):
    return _core.configure_windows_job(proc)


def _terminate_windows_descendants(parent_pid: int, kernel=None) -> None:
    return _core.terminate_windows_descendants(parent_pid, kernel)



def _run_child_capture(argv: list[str], *, timeout: float,
                       cwd: Path | None = None,
                       env: dict[str, str] | None = None):
    """Run one child with bounded output and an isolated staging cwd.

    This local seam intentionally mirrors the ingress bounded-child contract
    while adding ``cwd``: an adapter must not be able to leave logs or
    sidecars in the caller's repository/current directory.  Tests replace
    this function, keeping process execution deterministic.
    """
    return _core.run_child_capture(
        argv, timeout=timeout, cwd=cwd, env=env,
        timeout_validator=_validate_timeout,
        max_output_bytes=_ingress.MAX_CHILD_OUTPUT_BYTES)



def _write_bytes(path: Path, data: bytes) -> None:
    try:
        _core.write_bytes(path, data)
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes(path, (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode("utf-8"))


def _node_identity(path: Path) -> tuple[int, int, int, int, int, str]:
    try:
        return _core.node_identity(
            path, read_once=_read_regular_once,
            max_bytes=_ingress.MAX_HWPX_ARCHIVE_BYTES,
            reason="diagnostic_publish_failed")
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


def _same_file_identity(
        actual: tuple[int, int, int, int, int, str],
        expected: tuple[int, int, int, int, int, str]) -> bool:
    return _core.same_file_identity(actual, expected)


def _core_node_identity(path: Path):
    """Bridge the adapter's closed error type into the generic core seam."""
    try:
        return _node_identity(path)
    except DiagnosticError as exc:
        raise _core.CoreError(exc.reason)


def _remove_owned(path: Path, identity: tuple[int, int, int, int, int, str] | None) -> bool:
    return _core.remove_owned(path, identity, node_identity_fn=_core_node_identity)


def _remove_owned_dir(path: Path, identity: tuple[int, int, int, int, int, str] | None) -> None:
    _core.remove_owned_dir(path, identity, node_identity_fn=_core_node_identity)


def _rollback_publication(
        run_path: Path,
        reserved_identity: tuple[int, int, int, int, int, str] | None,
        receipt_target: Path,
        receipt_identity: tuple[int, int, int, int, int, str] | None,
        candidate_target: Path,
        candidate_identity: tuple[int, int, int, int, int, str] | None,
        token_target: Path | None = None,
        token_identity: tuple[int, int, int, int, int, str] | None = None) -> None:
    _core.rollback_publication(
        run_path, reserved_identity, receipt_target, receipt_identity,
        candidate_target, candidate_identity, token_target, token_identity,
        remove_owned_fn=_remove_owned, node_identity_fn=_core_node_identity,
        remove_owned_dir_fn=_remove_owned_dir)


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


def _prepare_root(path: Path, *, expected_leaf: str = "hwp-diagnostic") -> Path:
    try:
        return _core.prepare_root(path, expected_leaf=expected_leaf)
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


def _capture_root_guard(supplied: Path, resolved: Path) -> dict[str, Any]:
    return _core.capture_root_guard(
        supplied, resolved, node_identity_fn=_core_node_identity)


def _check_root_guard(guard: dict[str, Any], *, refresh: bool = False) -> None:
    try:
        _core.check_root_guard(
            guard, refresh=refresh, node_identity_fn=_core_node_identity)
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


def _publish_pair(
        *, run_path: Path, publish_stage: Path, staged_candidate: Path,
        payload: dict[str, Any], run_id: str, root_guard: dict[str, Any],
        source_path: Path, binary_path: Path, staged_binary: Path,
        staged_source: Path, source_descriptor: dict[str, Any], pin: str,
        final_validated: dict[str, Any]) -> dict[str, Any]:
    """Adapter callback layer over the generic owner-token publisher."""
    def check_guard(guard, *, refresh=False):
        try:
            _check_root_guard(guard, refresh=refresh)
        except DiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def write_bytes(path: Path, data: bytes):
        try:
            _write_bytes(path, data)
        except DiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def validate_receipt(receipt_target: Path, output: Path):
        try:
            target_receipt = _load_receipt(receipt_target)
            _validate_receipt_shape(target_receipt, output=output, run_id=run_id)
        except DiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    def before_candidate_link():
        try:
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
        except DiagnosticError as exc:
            raise _core.CoreError(exc.reason)

    try:
        return _core.publish_owner_token_pair(
            run_path, publish_stage, staged_candidate, payload,
            run_id=run_id, root_guard=root_guard,
            validate_receipt_fn=validate_receipt,
            before_candidate_link_fn=before_candidate_link,
            check_root_guard_fn=check_guard,
            write_bytes_fn=write_bytes,
            link_fn=os.link,
            node_identity_fn=_core_node_identity,
            same_identity_fn=_same_file_identity,
            remove_owned_fn=_remove_owned,
            rollback_fn=_rollback_publication,
        )
    except _core.CoreError as exc:
        raise DiagnosticError(exc.reason)


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
            return _publish_pair(
                run_path=run_path, publish_stage=publish_stage,
                staged_candidate=staged_candidate, payload=payload,
                run_id=run_id, root_guard=root_guard,
                source_path=source_path, binary_path=binary_path,
                staged_binary=staged_binary, staged_source=staged_source,
                source_descriptor=source_descriptor, pin=pin,
                final_validated=final_validated)

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
