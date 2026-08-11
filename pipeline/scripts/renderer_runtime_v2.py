"""Quarantine-only native renderer runtime v2 candidate.

The lane is intentionally narrow.  It executes only a staged, hash-pinned
``rhwp export-pdf`` adapter against the fixed HWPX source
``<workspace>/output/out.hwpx``.  It publishes an owned ``artifact.pdf`` and a
privacy-safe receipt under the pre-created
``<workspace>/output/proof/renderer-runtime-v2/<run-id>`` leaf.  The receipt is
diagnostic evidence only: no certificate is semantically validated, no
comparison/render proof is claimed, and no grade is promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

try:
    import diagnostic_candidate_core as _core
    import hwp_equation_diagnostic as _eqdiag
    import hwp_ingress as _ingress
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_equation_diagnostic as _eqdiag
    from pipeline.scripts import hwp_ingress as _ingress


SCHEMA = "rigorloom/renderer-runtime-v2/v1"
ROOT_LEAF = "renderer-runtime-v2"
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
RENDERER_ID = "rhwp_pdf"
ARGV_TEMPLATE = (
    ("{binary}", "--version"),
    ("{binary}", "export-pdf", "{input}", "-o", "{output}"),
)
ARGV_TEMPLATE_SHA256 = hashlib.sha256(
    json.dumps(ARGV_TEMPLATE, separators=(",", ":")).encode("utf-8")
).hexdigest()
ENV_POLICY = "minimal_allowlist_v1"
PROCESS_POLICY = (
    "windows_job_kill_on_close_v1" if os.name == "nt"
    else "posix_process_group_v1"
)
ACCEPTED_PROCESS_POLICIES = frozenset({
    "windows_job_kill_on_close_v1",
    "posix_process_group_v1",
})
DESCENDANT_CONTAINMENT = "not_established"
EVIDENCE_AUTHENTICATION = "not_established"
CWD_POLICY = "private_stage"
MAX_BINARY_BYTES = 256 * 1024 * 1024
MAX_INPUT_BYTES = getattr(_ingress, "MAX_HWPX_BYTES", 256 * 1024 * 1024)
MAX_CERTIFICATE_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_CHILD_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT = 300.0

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

_TOP_KEYS = frozenset({
    "schema", "status", "renderer", "execution", "input", "output",
    "certificate", "dependency_closure", "comparison", "render",
    "proof_grade", "submission_grade", "promotion",
})


class RuntimeRefusal(RuntimeError):
    """Expected fail-closed refusal carrying a stable privacy-safe reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, "error: invalid arguments\n")


def _coerce_path(value: Any, reason: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise RuntimeRefusal(reason)
    try:
        return Path(value)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RuntimeRefusal(reason)


def _validate_sha(value: Any, reason: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RuntimeRefusal(reason)
    return value


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise RuntimeRefusal("run_id_invalid")
    return value


def _validate_timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeRefusal("timeout_invalid")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RuntimeRefusal("timeout_invalid")
    if not math.isfinite(value) or value <= 0 or value > MAX_TIMEOUT:
        raise RuntimeRefusal("timeout_invalid")
    return value


def _is_reparse(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


def _check_directory_chain(path: Path, reason: str) -> None:
    """Reject symlink/reparse directory components in a supplied path."""
    try:
        probe = path.expanduser().absolute()
        while True:
            info = probe.lstat()
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise RuntimeRefusal(reason)
            if probe == probe.parent:
                break
            probe = probe.parent
    except RuntimeRefusal:
        raise
    except (OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeRefusal(reason)


def _prepare_layout(workspace_value: Any) -> tuple[
        Path, Path, Path, dict[str, Any], dict[str, Any],
        _core.DirectoryBinding, _core.DirectoryBinding]:
    workspace_input = _coerce_path(workspace_value, "workspace_invalid")
    try:
        supplied = workspace_input.expanduser().absolute()
        info = supplied.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or _is_reparse(info)):
            raise RuntimeRefusal("workspace_invalid")
        # A stable platform alias (for example macOS /var -> /private/var)
        # is acceptable; bind all subsequent custody checks to its canonical
        # target rather than rejecting the spelling's parent components.
        workspace = supplied.resolve(strict=True)
        _check_directory_chain(workspace, "workspace_invalid")
        output = workspace / "output"
        proof = output / "proof"
        root = proof / ROOT_LEAF
        for directory in (output, proof, root):
            _check_directory_chain(directory, "runtime_root_invalid")
            item = directory.lstat()
            if not stat.S_ISDIR(item.st_mode):
                raise RuntimeRefusal("runtime_root_invalid")
        if root.name != ROOT_LEAF:
            raise RuntimeRefusal("runtime_root_invalid")
        source = output / "out.hwpx"
        workspace_guard = _core.capture_root_guard(workspace, workspace)
        root_guard = _core.capture_root_guard(root, root)
        _core.check_root_guard(workspace_guard)
        _core.check_root_guard(root_guard)
        output_binding = _core.DirectoryBinding.open(output)
        try:
            root_binding = _core.DirectoryBinding.open(root)
        except Exception:
            output_binding.close()
            raise
        return (workspace, source, root, workspace_guard, root_guard,
                output_binding, root_binding)
    except RuntimeRefusal:
        raise
    except _core.CoreError as exc:
        raise RuntimeRefusal(exc.reason)
    except (OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeRefusal("runtime_root_invalid")


def _path_overlap(left: Path, right: Path) -> bool:
    try:
        left = left.expanduser().absolute()
        right = right.expanduser().absolute()
        return left == right or left in right.parents or right in left.parents
    except (OSError, RuntimeError, TypeError, ValueError):
        return True


def _snapshot_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("sha256") == right.get("sha256")
        and left.get("bytes") == right.get("bytes")
        and tuple(left.get("identity", ()))
        == tuple(right.get("identity", ()))
    )


def _normalise_real_path(value: str) -> str:
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return os.path.normcase(os.path.realpath(value))


def _opened_real_path(fd: int) -> str | None:
    """Return the path bound to an opened fd/handle, or fail closed."""
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetFinalPathNameByHandleW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            kernel.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
            handle = msvcrt.get_osfhandle(fd)
            size = 512
            while size <= 32768:
                buffer = ctypes.create_unicode_buffer(size)
                result = kernel.GetFinalPathNameByHandleW(handle, buffer, size, 0)
                if result == 0:
                    return None
                if result < size:
                    return buffer.value
                size *= 2
        except (AttributeError, OSError, ValueError, TypeError):
            return None
        return None
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ValueError, TypeError):
        try:
            import fcntl
            getpath = getattr(fcntl, "F_GETPATH", 50)
            buffer = bytearray(1024)
            value = fcntl.fcntl(fd, getpath, bytes(buffer))
            if isinstance(value, bytes):
                value = value.split(b"\\0", 1)[0]
                return os.fsdecode(value)
        except (AttributeError, OSError, ValueError, TypeError):
            pass
    return None


def _capture_file(path: Path, max_bytes: int, reason: str,
                  *, allow_hardlink: bool = False,
                  binding: _core.DirectoryBinding | None = None,
                  relative_name: str | None = None) -> dict[str, Any]:
    """Capture bytes, digest, and fd identity as one no-follow operation."""
    try:
        if binding is not None:
            if relative_name is None:
                raise RuntimeRefusal("directory_binding_name_invalid")
            try:
                binding.check()
            except _core.CoreError as exc:
                raise RuntimeRefusal(exc.reason)
            path = binding.path / relative_name
        else:
            _check_directory_chain(path.parent, reason)
        before = path.lstat()
        if (stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode)
                or _is_reparse(before)
                or (not allow_hardlink and getattr(before, "st_nlink", 1) != 1)
                or before.st_size < 0 or before.st_size > max_bytes):
            raise RuntimeRefusal(reason)
        try:
            expected_real = _normalise_real_path(str(path.resolve(strict=True)))
        except (OSError, RuntimeError, ValueError, TypeError):
            raise RuntimeRefusal(reason)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if binding is not None and relative_name is not None:
            try:
                fd = binding.open_file(relative_name, flags)
            except _core.CoreError as exc:
                raise RuntimeRefusal(exc.reason)
        else:
            fd = os.open(str(path), flags)
        try:
            opened = os.fstat(fd)
            actual_real = _opened_real_path(fd)
            if actual_real is None:
                raise RuntimeRefusal("artifact_binding_unavailable")
            if _normalise_real_path(actual_real) != expected_real:
                raise RuntimeRefusal(reason)
            if (not stat.S_ISREG(opened.st_mode) or _is_reparse(opened)
                    or (getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0))
                    != (getattr(before, "st_dev", 0), getattr(before, "st_ino", 0))
                    or opened.st_size != before.st_size
                    or getattr(opened, "st_mtime_ns", 0)
                    != getattr(before, "st_mtime_ns", 0)
                    or getattr(opened, "st_ctime_ns", 0)
                    != getattr(before, "st_ctime_ns", 0)
                    or (not allow_hardlink and getattr(opened, "st_nlink", 1) != 1)):
                raise RuntimeRefusal(reason)
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeRefusal("file_too_large")
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(fd)
            if (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    after.st_size) != (getattr(opened, "st_dev", 0),
                                       getattr(opened, "st_ino", 0), total):
                raise RuntimeRefusal(reason)
            if (getattr(after, "st_mtime_ns", 0)
                    != getattr(opened, "st_mtime_ns", 0)
                    or getattr(after, "st_ctime_ns", 0)
                    != getattr(opened, "st_ctime_ns", 0)):
                raise RuntimeRefusal(reason)
            final = path.lstat()
            if (stat.S_ISLNK(final.st_mode) or not stat.S_ISREG(final.st_mode)
                    or _is_reparse(final)
                    or (not allow_hardlink and getattr(final, "st_nlink", 1) != 1)
                    or (getattr(final, "st_dev", 0), getattr(final, "st_ino", 0))
                    != (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0))
                    or final.st_size != total
                    or getattr(final, "st_mtime_ns", 0)
                    != getattr(after, "st_mtime_ns", 0)
                    or getattr(final, "st_ctime_ns", 0)
                    != getattr(after, "st_ctime_ns", 0)):
                raise RuntimeRefusal(reason)
            return {
                "data": b"".join(chunks),
                "sha256": digest.hexdigest(),
                "bytes": total,
                "identity": (
                    getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    getattr(after, "st_size", total),
                    getattr(after, "st_mtime_ns", 0),
                    getattr(after, "st_ctime_ns", 0), digest.hexdigest(),
                ),
            }
        finally:
            os.close(fd)
    except RuntimeRefusal:
        raise
    except (OSError, ValueError, TypeError):
        raise RuntimeRefusal(reason)


def _write_private(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    try:
        _core.write_bytes(path, data, write_reason="staging_write_failed")
        try:
            path.chmod(mode)
        except OSError:
            raise RuntimeRefusal("staging_write_failed")
    except RuntimeRefusal:
        raise
    except _core.CoreError as exc:
        raise RuntimeRefusal(exc.reason)


def _preflight_source(data: bytes) -> dict[str, Any]:
    try:
        scanned = _eqdiag._scan_bytes(data)
    except Exception as exc:  # format scanners expose only closed reasons
        reason = getattr(exc, "reason", "input_preflight_failed")
        raise RuntimeRefusal("input_preflight_failed") from None
    try:
        count = scanned["equations"]["count"]
    except (KeyError, TypeError, ValueError):
        raise RuntimeRefusal("input_preflight_failed")
    if count != 0:
        raise RuntimeRefusal("equation_input_unsupported")
    return scanned["source"]


def _scrub_env() -> tuple[dict[str, str], str]:
    # Direct execution uses a staged absolute binary, so PATH and temporary
    # directory search are unnecessary.  SystemRoot/WINDIR are the minimum
    # Windows loader context; their values are bound by env_sha256 only.
    env = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR")
        if isinstance(os.environ.get(key), str) and os.environ[key]
    }
    encoded = json.dumps(sorted(env.items()), separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return env, hashlib.sha256(encoded).hexdigest()


def _run_child_capture(argv: list[str], *, timeout: float,
                       cwd: Path | None = None,
                       env: dict[str, str] | None = None,
                       return_evidence: bool = False):
    return _core.run_child_capture(
        argv, timeout=timeout, cwd=cwd, env=env,
        timeout_validator=_validate_timeout,
        max_output_bytes=MAX_CHILD_OUTPUT_BYTES,
        return_evidence=return_evidence)


def _child_result(value: Any) -> tuple[int, bool, bool, dict[str, Any]]:
    if (not isinstance(value, tuple) or len(value) != 4
            or type(value[0]) is not int or type(value[1]) is not bool
            or type(value[2]) is not bool or not isinstance(value[3], dict)):
        raise RuntimeRefusal("child_result_invalid")
    evidence = value[3]
    if set(evidence) != {"output", "error"}:
        raise RuntimeRefusal("child_result_invalid")
    for key in ("output", "error"):
        item = evidence[key]
        if (not isinstance(item, dict) or set(item) != {"sha256", "bytes"}
                or not isinstance(item.get("sha256"), str)
                or SHA256_RE.fullmatch(item["sha256"]) is None
                or type(item.get("bytes")) is not int or item["bytes"] < 0
                or item["bytes"] > MAX_CHILD_OUTPUT_BYTES + 65536):
            raise RuntimeRefusal("child_result_invalid")
    return value


def _validate_pdf(data: bytes) -> int:
    if not data or len(data) > MAX_OUTPUT_BYTES:
        raise RuntimeRefusal("artifact_invalid")
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as document:
            pages = int(document.page_count)
    except (ImportError, OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeRefusal("artifact_invalid")
    if pages < 1:
        raise RuntimeRefusal("artifact_invalid")
    return pages


def _argv_digest(version_argv: list[str], render_argv: list[str]) -> str:
    encoded = json.dumps([version_argv, render_argv], ensure_ascii=False,
                         separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_copy(item: dict[str, Any]) -> dict[str, Any]:
    # Names are intentionally generic; no child stream bytes or diagnostics
    # leave the process.
    return {"sha256": item["sha256"], "bytes": item["bytes"]}


def _build_payload(*, binary: dict[str, Any], source: dict[str, Any],
                   certificate: dict[str, Any], output: dict[str, Any],
                   pages: int, argv_sha256: str,
                   env_sha256: str,
                   version_evidence: dict[str, Any],
                   render_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "analyzed",
        "renderer": {"id": RENDERER_ID, "binary_sha256": binary["sha256"]},
        "execution": {
            "state": "succeeded",
            "adapter": RENDERER_ID,
            "binary_sha256": binary["sha256"],
            "argv_sha256": argv_sha256,
            "argv_template_sha256": ARGV_TEMPLATE_SHA256,
            "cwd_policy": CWD_POLICY,
            "env_policy": ENV_POLICY,
            "env_sha256": env_sha256,
            "process_policy": PROCESS_POLICY,
            "descendant_containment": DESCENDANT_CONTAINMENT,
            "evidence_authentication": EVIDENCE_AUTHENTICATION,
            "version_probe": {
                "state": "succeeded", "exit_code": 0,
                "timed_out": False, "overflow": False,
                "stdout": _evidence_copy(version_evidence),
                "stderr": _evidence_copy(version_evidence["_error"]),
            },
            "render_process": {
                "state": "succeeded", "exit_code": 0,
                "timed_out": False, "overflow": False,
                "stdout": _evidence_copy(render_evidence),
                "stderr": _evidence_copy(render_evidence["_error"]),
            },
        },
        "input": {
            "format": "hwpx", "bytes": source["bytes"],
            "sha256": source["sha256"], "preflight": "strict_complete",
        },
        "output": {
            "format": "pdf", "state": "captured", "bytes": output["bytes"],
            "sha256": output["sha256"], "pages": pages,
        },
        "certificate": {
            "bytes": certificate["bytes"], "sha256": certificate["sha256"],
            "validation": "not_run",
        },
        "dependency_closure": "unknown",
        "comparison": {"state": "unknown"},
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
        "promotion": "not_run",
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _validate_payload(payload: Any, *, run_id: str | None = None,
                      require_local_process_policy: bool = True
                      ) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _TOP_KEYS:
        raise RuntimeRefusal("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "analyzed"
            or payload.get("dependency_closure") != "unknown"
            or payload.get("comparison") != {"state": "unknown"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False
            or payload.get("promotion") != "not_run"):
        raise RuntimeRefusal("receipt_state_invalid")
    renderer = payload.get("renderer")
    if (not isinstance(renderer, dict) or set(renderer) != {"id", "binary_sha256"}
            or renderer.get("id") != RENDERER_ID
            or SHA256_RE.fullmatch(renderer.get("binary_sha256", "")) is None):
        raise RuntimeRefusal("receipt_renderer_invalid")
    execution = payload.get("execution")
    if not isinstance(execution, dict) or set(execution) != {
            "state", "adapter", "binary_sha256", "argv_sha256",
            "argv_template_sha256", "cwd_policy", "env_policy", "env_sha256",
            "process_policy", "descendant_containment",
            "evidence_authentication", "version_probe", "render_process"}:
        raise RuntimeRefusal("receipt_execution_invalid")
    if (execution.get("state") != "succeeded"
            or execution.get("adapter") != RENDERER_ID
            or execution.get("binary_sha256") != renderer["binary_sha256"]
            or SHA256_RE.fullmatch(execution.get("argv_sha256", "")) is None
            or execution.get("argv_template_sha256") != ARGV_TEMPLATE_SHA256
            or execution.get("cwd_policy") != CWD_POLICY
            or execution.get("env_policy") != ENV_POLICY
            or SHA256_RE.fullmatch(execution.get("env_sha256", "")) is None
            or execution.get("process_policy") not in ACCEPTED_PROCESS_POLICIES
            or (require_local_process_policy
                and execution.get("process_policy") != PROCESS_POLICY)
            or execution.get("descendant_containment") != DESCENDANT_CONTAINMENT
            or execution.get("evidence_authentication") != EVIDENCE_AUTHENTICATION):
        raise RuntimeRefusal("receipt_execution_invalid")
    for key in ("version_probe", "render_process"):
        item = execution.get(key)
        if (not isinstance(item, dict)
                or set(item) != {"state", "exit_code", "timed_out", "overflow",
                                 "stdout", "stderr"}
                or item.get("state") != "succeeded"
                or type(item.get("exit_code")) is not int
                or item.get("exit_code") != 0
                or item.get("timed_out") is not False
                or item.get("overflow") is not False):
            raise RuntimeRefusal("receipt_execution_invalid")
        for stream in ("stdout", "stderr"):
            evidence = item.get(stream)
            if (not isinstance(evidence, dict)
                    or set(evidence) != {"sha256", "bytes"}
                    or SHA256_RE.fullmatch(evidence.get("sha256", "")) is None
                    or type(evidence.get("bytes")) is not int
                    or evidence["bytes"] < 0
                    or evidence["bytes"] > MAX_CHILD_OUTPUT_BYTES):
                raise RuntimeRefusal("receipt_execution_invalid")
    source = payload.get("input")
    if (not isinstance(source, dict)
            or set(source) != {"format", "bytes", "sha256", "preflight"}
            or source.get("format") != "hwpx"
            or source.get("preflight") != "strict_complete"
            or type(source.get("bytes")) is not int or source["bytes"] <= 0
            or SHA256_RE.fullmatch(source.get("sha256", "")) is None):
        raise RuntimeRefusal("receipt_input_invalid")
    output = payload.get("output")
    if (not isinstance(output, dict)
            or set(output) != {"format", "state", "bytes", "sha256", "pages"}
            or output.get("format") != "pdf" or output.get("state") != "captured"
            or type(output.get("bytes")) is not int or output["bytes"] <= 0
            or output["bytes"] > MAX_OUTPUT_BYTES
            or SHA256_RE.fullmatch(output.get("sha256", "")) is None
            or type(output.get("pages")) is not int or output["pages"] < 1):
        raise RuntimeRefusal("receipt_output_invalid")
    certificate = payload.get("certificate")
    if (not isinstance(certificate, dict)
            or set(certificate) != {"bytes", "sha256", "validation"}
            or type(certificate.get("bytes")) is not int
            or certificate["bytes"] <= 0
            or SHA256_RE.fullmatch(certificate.get("sha256", "")) is None
            or certificate.get("validation") != "not_run"):
        raise RuntimeRefusal("receipt_certificate_invalid")
    if run_id is not None:
        _validate_run_id(run_id)
    return payload


def _read_receipt(path: Path, *, allow_hardlink: bool = False,
                  run_id: str | None = None,
                  allow_cross_host_process_policy: bool = False
                  ) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or _is_reparse(info)
                or (not allow_hardlink and getattr(info, "st_nlink", 1) != 1)):
            raise RuntimeRefusal("receipt_invalid")
        snapshot = _capture_file(path, MAX_RECEIPT_BYTES, "receipt_invalid",
                                 allow_hardlink=allow_hardlink)
        payload = json.loads(snapshot["data"].decode("utf-8"),
                             object_pairs_hook=_no_duplicate_keys)
        _validate_payload(
            payload, run_id=run_id,
            require_local_process_policy=not allow_cross_host_process_policy)
        if snapshot["data"] != _json_bytes(payload):
            raise RuntimeRefusal("receipt_not_canonical")
        return payload, snapshot["data"], snapshot
    except RuntimeRefusal:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise RuntimeRefusal("receipt_invalid")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeRefusal("receipt_duplicate_key")
        result[key] = value
    return result


def _node_identity(path: Path) -> tuple[int, int, int, int, int, str]:
    try:
        return _core.node_identity(path, max_bytes=MAX_OUTPUT_BYTES,
                                   reason="diagnostic_publish_failed")
    except _core.CoreError as exc:
        raise RuntimeRefusal(exc.reason)


def _same_identity(actual: tuple[int, int, int, int, int, str],
                   expected: tuple[int, int, int, int, int, str]) -> bool:
    return _core.same_file_identity(actual, expected)


def _remove_owned(path: Path, identity: Any) -> bool:
    return _core.remove_owned(path, identity)


def _rollback(*args: Any) -> None:
    _core.rollback_publication(*args)


def _public_validate(receipt: Path, candidate: Path, run_id: str) -> None:
    payload, _, _ = _read_receipt(receipt, allow_hardlink=True, run_id=run_id)
    candidate_snapshot = _capture_file(candidate, MAX_OUTPUT_BYTES,
                                       "diagnostic_publish_failed",
                                       allow_hardlink=True)
    if (payload["output"]["sha256"] != candidate_snapshot["sha256"]
            or payload["output"]["bytes"] != candidate_snapshot["bytes"]
            or _validate_pdf(candidate_snapshot["data"]) != payload["output"]["pages"]):
        raise RuntimeRefusal("artifact_changed")


def _check_live_rebind(*, binary_path: Path, binary_snapshot: dict[str, Any],
                       source_path: Path, source_snapshot: dict[str, Any],
                       source_binding: _core.DirectoryBinding | None,
                       certificate_path: Path,
                       certificate_snapshot: dict[str, Any],
                       staged_binary: Path | None,
                       staged_binary_snapshot: dict[str, Any] | None,
                       staged_source: Path | None,
                       staged_source_snapshot: dict[str, Any] | None,
                       staged_candidate: Path,
                       output_snapshot: dict[str, Any], pages: int,
                       include_candidate: bool = True) -> None:
    try:
        if not _snapshot_equal(_capture_file(binary_path, MAX_BINARY_BYTES,
                                             "binary_changed"), binary_snapshot):
            raise RuntimeRefusal("binary_changed")
        if not _snapshot_equal(_capture_file(
                source_path, MAX_INPUT_BYTES, "input_changed",
                binding=source_binding,
                relative_name="out.hwpx" if source_binding is not None else None),
                source_snapshot):
            raise RuntimeRefusal("input_changed")
        if not _snapshot_equal(_capture_file(certificate_path,
                                             MAX_CERTIFICATE_BYTES,
                                             "certificate_changed"),
                               certificate_snapshot):
            raise RuntimeRefusal("certificate_changed")
        if staged_binary is not None and staged_binary_snapshot is not None:
            if not _snapshot_equal(_capture_file(staged_binary, MAX_BINARY_BYTES,
                                                 "staged_binary_changed"),
                                   staged_binary_snapshot):
                raise RuntimeRefusal("staged_binary_changed")
        if staged_source is not None and staged_source_snapshot is not None:
            if not _snapshot_equal(_capture_file(staged_source, MAX_INPUT_BYTES,
                                                 "staged_input_changed"),
                                   staged_source_snapshot):
                raise RuntimeRefusal("staged_input_changed")
        if include_candidate:
            candidate = _capture_file(staged_candidate, MAX_OUTPUT_BYTES,
                                      "artifact_changed")
            if (candidate["sha256"] != output_snapshot["sha256"]
                    or candidate["bytes"] != output_snapshot["bytes"]):
                raise RuntimeRefusal("artifact_changed")
            if _validate_pdf(candidate["data"]) != pages:
                raise RuntimeRefusal("artifact_changed")
    except RuntimeRefusal:
        raise


def _publish(*, root: Path, run_id: str, payload: dict[str, Any],
             root_guard: dict[str, Any], workspace_guard: dict[str, Any],
             root_binding: _core.DirectoryBinding | None,
             source_path: Path, source_snapshot: dict[str, Any],
             source_binding: _core.DirectoryBinding | None,
             binary_path: Path, binary_snapshot: dict[str, Any],
             certificate_path: Path, certificate_snapshot: dict[str, Any],
             staged_binary: Path | None,
             staged_binary_snapshot: dict[str, Any] | None,
             staged_source: Path | None,
             staged_source_snapshot: dict[str, Any] | None,
             staged_candidate: Path, output_snapshot: dict[str, Any],
             pages: int, temp_root: Path) -> dict[str, Any]:
    stage = temp_root / "publish" / run_id
    stage.mkdir(parents=True, exist_ok=False)
    staged_receipt = stage / "receipt.json"
    staged_artifact = stage / "artifact.pdf"
    _write_private(staged_artifact, output_snapshot["data"], mode=0o400)
    _write_private(staged_receipt, _json_bytes(payload), mode=0o600)

    def check_guard(value: dict[str, Any], *, refresh: bool = False) -> None:
        try:
            if root_binding is not None:
                root_binding.check()
            _core.check_root_guard(workspace_guard,
                                  node_identity_fn=_core.node_identity)
            _core.check_root_guard(value, refresh=refresh,
                                   node_identity_fn=_core.node_identity)
        except _core.CoreError as exc:
            raise _core.CoreError(exc.reason)

    def write_bytes(path: Path, data: bytes) -> None:
        try:
            _core.write_bytes(path, data, exists_reason="run_exists",
                              write_reason="diagnostic_publish_failed")
        except _core.CoreError as exc:
            raise _core.CoreError(exc.reason)

    def validate(receipt: Path, candidate: Path) -> None:
        try:
            _public_validate(receipt, candidate, run_id)
        except RuntimeRefusal as exc:
            raise _core.CoreError(exc.reason)

    def before_candidate() -> None:
        try:
            _check_live_rebind(
                binary_path=binary_path, binary_snapshot=binary_snapshot,
                source_path=source_path, source_snapshot=source_snapshot,
                source_binding=source_binding,
                certificate_path=certificate_path,
                certificate_snapshot=certificate_snapshot,
                staged_binary=staged_binary,
                staged_binary_snapshot=staged_binary_snapshot,
                staged_source=staged_source,
                staged_source_snapshot=staged_source_snapshot,
                staged_candidate=staged_artifact,
                output_snapshot=output_snapshot, pages=pages)
        except RuntimeRefusal as exc:
            raise _core.CoreError(exc.reason)

    def final_commit() -> None:
        try:
            _check_live_rebind(
                binary_path=binary_path, binary_snapshot=binary_snapshot,
                source_path=source_path, source_snapshot=source_snapshot,
                source_binding=source_binding,
                certificate_path=certificate_path,
                certificate_snapshot=certificate_snapshot,
                staged_binary=staged_binary,
                staged_binary_snapshot=staged_binary_snapshot,
                staged_source=staged_source,
                staged_source_snapshot=staged_source_snapshot,
                staged_candidate=staged_artifact,
                output_snapshot=output_snapshot, pages=pages,
                include_candidate=False)
        except RuntimeRefusal as exc:
            raise _core.CoreError(exc.reason)

    try:
        return _core.publish_owner_token_pair(
            root / run_id, stage, staged_artifact, payload,
            run_id=run_id, root_guard=root_guard,
            validate_receipt_fn=validate,
            before_candidate_link_fn=before_candidate,
            final_commit_fn=final_commit,
            check_root_guard_fn=check_guard,
            write_bytes_fn=write_bytes,
            link_fn=os.link,
            node_identity_fn=_core.node_identity,
            same_identity_fn=_core.same_file_identity,
            remove_owned_fn=_core.remove_owned,
            rollback_fn=_core.rollback_publication,
            candidate_name="artifact.pdf",
            directory_binding=root_binding,
            token_prefix=".t150-owner-",
        )
    except _core.CoreError as exc:
        raise RuntimeRefusal(exc.reason)


def _execute_runtime_impl(*, workspace: str | Path, run_id: str,
                    renderer_id: str, binary: str | Path,
                    binary_sha256: str,
                    certificate_path: str | Path,
                    certificate_sha256: str,
                    timeout: float = 60.0,
                    _layout: tuple[Path, Path, Path, dict[str, Any], dict[str, Any],
                                    _core.DirectoryBinding, _core.DirectoryBinding]
                    | None = None) -> dict[str, Any]:
    """Run the closed ``rhwp_pdf`` adapter and publish its receipt."""
    run_id = _validate_run_id(run_id)
    if renderer_id != RENDERER_ID:
        raise RuntimeRefusal("renderer_id_invalid")
    binary_sha256 = _validate_sha(binary_sha256, "binary_pin_invalid")
    certificate_sha256 = _validate_sha(certificate_sha256,
                                       "certificate_pin_invalid")
    timeout = _validate_timeout(timeout)
    if _layout is None:
        (workspace, source_path, root, workspace_guard, root_guard,
         output_binding, root_binding) = _prepare_layout(workspace)
    else:
        (workspace, source_path, root, workspace_guard, root_guard,
         output_binding, root_binding) = _layout
    binary_path = _coerce_path(binary, "binary_unavailable").expanduser().absolute()
    certificate_path = _coerce_path(certificate_path,
                                    "certificate_unavailable").expanduser().absolute()
    if (_path_overlap(root, binary_path) or _path_overlap(root, certificate_path)
            or _path_overlap(source_path, binary_path)
            or _path_overlap(source_path, certificate_path)):
        raise RuntimeRefusal("paths_not_distinct")
    run_path = root / run_id
    try:
        if run_path.exists() or run_path.is_symlink():
            raise RuntimeRefusal("run_exists")
    except OSError:
        raise RuntimeRefusal("run_exists")
    binary_snapshot = _capture_file(binary_path, MAX_BINARY_BYTES,
                                    "binary_unavailable")
    if binary_snapshot["sha256"] != binary_sha256:
        raise RuntimeRefusal("binary_hash_mismatch")
    source_snapshot = _capture_file(
        source_path, MAX_INPUT_BYTES, "input_unavailable",
        binding=output_binding, relative_name="out.hwpx")
    source_descriptor = _preflight_source(source_snapshot["data"])
    certificate_snapshot = _capture_file(certificate_path,
                                          MAX_CERTIFICATE_BYTES,
                                          "certificate_unavailable")
    if certificate_snapshot["sha256"] != certificate_sha256:
        raise RuntimeRefusal("certificate_hash_mismatch")
    committed = False
    committed_result: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=".t150-") as temp_name:
            temp_root = Path(temp_name)
            root_binding.check()
            _core.check_root_guard(root_guard, refresh=True)
            _core.check_root_guard(workspace_guard)
            suffix = binary_path.suffix if re.fullmatch(
                r"\.[A-Za-z0-9]{1,8}", binary_path.suffix) else ""
            staged_binary = temp_root / ("rhwp" + suffix)
            staged_source = temp_root / "input.hwpx"
            staged_output = temp_root / "artifact.pdf"
            _write_private(staged_binary, binary_snapshot["data"], mode=0o700)
            _write_private(staged_source, source_snapshot["data"], mode=0o600)
            staged_binary_snapshot = _capture_file(staged_binary, MAX_BINARY_BYTES,
                                                   "staging_write_failed")
            staged_source_snapshot = _capture_file(staged_source, MAX_INPUT_BYTES,
                                                   "staging_write_failed")
            env, env_sha256 = _scrub_env()
            version_argv = [str(staged_binary), "--version"]
            render_argv = [str(staged_binary), "export-pdf", str(staged_source),
                           "-o", str(staged_output)]
            version_result = _child_result(_run_child_capture(
                version_argv, timeout=timeout, cwd=temp_root, env=env,
                return_evidence=True))
            code, timed_out, overflow, evidence = version_result
            if timed_out:
                raise RuntimeRefusal("version_timeout")
            if overflow:
                raise RuntimeRefusal("version_output_too_large")
            if code != 0:
                raise RuntimeRefusal("version_failed")
            version_output = evidence["output"]
            version_error = evidence["error"]
            if version_output["bytes"] <= 0:
                raise RuntimeRefusal("version_output_missing")
            render_result = _child_result(_run_child_capture(
                render_argv, timeout=timeout, cwd=temp_root, env=env,
                return_evidence=True))
            code, timed_out, overflow, render_evidence = render_result
            if timed_out:
                raise RuntimeRefusal("renderer_timeout")
            if overflow:
                raise RuntimeRefusal("renderer_output_too_large")
            if code != 0:
                raise RuntimeRefusal("renderer_failed")
            if staged_output.exists() or staged_output.is_symlink():
                output_snapshot = _capture_file(staged_output, MAX_OUTPUT_BYTES,
                                                "artifact_invalid")
            else:
                raise RuntimeRefusal("artifact_missing")
            pages = _validate_pdf(output_snapshot["data"])
            # Preserve the evidence dictionaries without inserting private
            # child streams into the receipt.
            version_evidence = dict(version_output)
            version_evidence["_error"] = version_error
            render_output = render_evidence["output"]
            render_error = render_evidence["error"]
            argv_sha = _argv_digest(version_argv, render_argv)
            # Make the exact staged output immutable before publication.
            staged_output.chmod(0o400)
            _check_live_rebind(
                binary_path=binary_path, binary_snapshot=binary_snapshot,
                source_path=source_path, source_snapshot=source_snapshot,
                source_binding=output_binding,
                certificate_path=certificate_path,
                certificate_snapshot=certificate_snapshot,
                staged_binary=staged_binary,
                staged_binary_snapshot=staged_binary_snapshot,
                staged_source=staged_source,
                staged_source_snapshot=staged_source_snapshot,
                staged_candidate=staged_output,
                output_snapshot=output_snapshot, pages=pages)
            # No private source/binary snapshot survives into the publication
            # stage.  The immutable PDF is the only candidate input retained.
            staged_binary.unlink()
            staged_source.unlink()
            publish_payload = _build_payload(
                binary=binary_snapshot, source=source_descriptor,
                certificate=certificate_snapshot, output=output_snapshot,
                pages=pages, argv_sha256=argv_sha, env_sha256=env_sha256,
                version_evidence=version_evidence,
                render_evidence={**render_output, "_error": render_error})
            _validate_payload(publish_payload, run_id=run_id)
            result = _publish(
                root=root, run_id=run_id, payload=publish_payload,
                root_guard=root_guard, workspace_guard=workspace_guard,
                root_binding=root_binding,
                source_path=source_path, source_snapshot=source_snapshot,
                source_binding=output_binding,
                binary_path=binary_path, binary_snapshot=binary_snapshot,
                certificate_path=certificate_path,
                certificate_snapshot=certificate_snapshot,
                staged_binary=None,
                staged_binary_snapshot=None,
                staged_source=None,
                staged_source_snapshot=None,
                staged_candidate=staged_output,
                 output_snapshot=output_snapshot, pages=pages,
                 temp_root=temp_root)
            committed_result = result
            committed = True
            return result
    except RuntimeRefusal:
        if committed and committed_result is not None:
            return committed_result
        raise
    except _core.CoreError as exc:
        if committed and committed_result is not None:
            return committed_result
        raise RuntimeRefusal(exc.reason)
    except (OSError, RuntimeError, ValueError, TypeError):
        if committed and committed_result is not None:
            return committed_result
        raise RuntimeRefusal("runtime_failed")


def execute_runtime(*, workspace: str | Path, run_id: str,
                    renderer_id: str, binary: str | Path,
                    binary_sha256: str,
                    certificate_path: str | Path,
                    certificate_sha256: str,
                    timeout: float = 60.0) -> dict[str, Any]:
    """Run the adapter while explicitly closing held custody bindings."""
    layout = _prepare_layout(workspace)
    output_binding = layout[-2]
    root_binding = layout[-1]
    try:
        return _execute_runtime_impl(
            workspace=workspace, run_id=run_id, renderer_id=renderer_id,
            binary=binary, binary_sha256=binary_sha256,
            certificate_path=certificate_path,
            certificate_sha256=certificate_sha256, timeout=timeout,
            _layout=layout)
    finally:
        output_binding.close()
        root_binding.close()


def _public_layout(root: Path, run_id: str) -> tuple[Path, Path, Path]:
    run_path = root / run_id
    receipt = run_path / "receipt.json"
    artifact = run_path / "artifact.pdf"
    try:
        info = run_path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or _is_reparse(info)):
            raise RuntimeRefusal("receipt_layout_invalid")
        children = sorted(item.name for item in run_path.iterdir())
        if children != ["artifact.pdf", "receipt.json"]:
            raise RuntimeRefusal("receipt_layout_invalid")
    except RuntimeRefusal:
        raise
    except (OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeRefusal("receipt_layout_invalid")
    return run_path, receipt, artifact


def _verify_runtime_impl(*, workspace: str | Path, run_id: str,
                   binary: str | Path,
                   certificate_path: str | Path,
                   _layout: tuple[Path, Path, Path, dict[str, Any], dict[str, Any],
                                   _core.DirectoryBinding, _core.DirectoryBinding]
                   | None = None) -> dict[str, Any]:
    """Rebind a published receipt to current input/dependency/artifact bytes."""
    run_id = _validate_run_id(run_id)
    if _layout is None:
        (workspace, source_path, root, workspace_guard, root_guard,
         output_binding, root_binding) = _prepare_layout(workspace)
    else:
        (workspace, source_path, root, workspace_guard, root_guard,
         output_binding, root_binding) = _layout
    binary_path = _coerce_path(binary, "binary_unavailable").expanduser().absolute()
    certificate_path = _coerce_path(certificate_path,
                                    "certificate_unavailable").expanduser().absolute()
    if (_path_overlap(root, binary_path) or _path_overlap(root, certificate_path)
            or _path_overlap(source_path, binary_path)
            or _path_overlap(source_path, certificate_path)):
        raise RuntimeRefusal("paths_not_distinct")
    run_path, receipt_path, artifact_path = _public_layout(root, run_id)
    root_binding.check()
    payload, raw, receipt_snapshot = _read_receipt(
        receipt_path, run_id=run_id,
        allow_cross_host_process_policy=True)
    binary_snapshot = _capture_file(binary_path, MAX_BINARY_BYTES,
                                    "binary_changed")
    if binary_snapshot["sha256"] != payload["renderer"]["binary_sha256"]:
        raise RuntimeRefusal("binary_changed")
    source_snapshot = _capture_file(
        source_path, MAX_INPUT_BYTES, "input_changed",
        binding=output_binding, relative_name="out.hwpx")
    if (source_snapshot["sha256"] != payload["input"]["sha256"]
            or source_snapshot["bytes"] != payload["input"]["bytes"]):
        raise RuntimeRefusal("input_changed")
    source_descriptor = _preflight_source(source_snapshot["data"])
    certificate_snapshot = _capture_file(certificate_path,
                                          MAX_CERTIFICATE_BYTES,
                                          "certificate_changed")
    if (certificate_snapshot["sha256"] != payload["certificate"]["sha256"]
            or certificate_snapshot["bytes"] != payload["certificate"]["bytes"]):
        raise RuntimeRefusal("certificate_changed")
    artifact_snapshot = _capture_file(artifact_path, MAX_OUTPUT_BYTES,
                                      "artifact_changed")
    pages = _validate_pdf(artifact_snapshot["data"])
    if (artifact_snapshot["sha256"] != payload["output"]["sha256"]
            or artifact_snapshot["bytes"] != payload["output"]["bytes"]
            or pages != payload["output"]["pages"]):
        raise RuntimeRefusal("artifact_changed")
    # Final receipt is captured first.  The final artifact capture and parse
    # are deliberately last so a receipt seam that mutates the artifact after
    # returning a valid payload cannot produce a false-green verification.
    _core.check_root_guard(workspace_guard)
    _core.check_root_guard(root_guard)
    root_binding.check()
    final_payload, final_raw, final_receipt_snapshot = _read_receipt(
        receipt_path, run_id=run_id,
        allow_cross_host_process_policy=True)
    final_source = _capture_file(
        source_path, MAX_INPUT_BYTES, "input_changed",
        binding=output_binding, relative_name="out.hwpx")
    final_binary = _capture_file(binary_path, MAX_BINARY_BYTES,
                                 "binary_changed")
    final_certificate = _capture_file(certificate_path,
                                       MAX_CERTIFICATE_BYTES,
                                       "certificate_changed")
    final_artifact = _capture_file(artifact_path, MAX_OUTPUT_BYTES,
                                   "artifact_changed")
    final_pages = _validate_pdf(final_artifact["data"])
    if (final_payload != payload or final_raw != raw
            or not _snapshot_equal(final_artifact, artifact_snapshot)
            or not _snapshot_equal(final_source, source_snapshot)
            or not _snapshot_equal(final_binary, binary_snapshot)
            or not _snapshot_equal(final_certificate, certificate_snapshot)
            or not _snapshot_equal(final_receipt_snapshot, receipt_snapshot)
            or final_pages != payload["output"]["pages"]):
        raise RuntimeRefusal("receipt_changed")
    return payload


def verify_runtime(*, workspace: str | Path, run_id: str,
                   binary: str | Path,
                   certificate_path: str | Path) -> dict[str, Any]:
    """Verify a receipt while explicitly closing held custody bindings."""
    layout = _prepare_layout(workspace)
    output_binding = layout[-2]
    root_binding = layout[-1]
    try:
        return _verify_runtime_impl(
            workspace=workspace, run_id=run_id, binary=binary,
            certificate_path=certificate_path, _layout=layout)
    finally:
        output_binding.close()
        root_binding.close()


def _print(payload: dict[str, Any]) -> None:
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":")) + "\n")
    except (BrokenPipeError, OSError, UnicodeError):
        raise RuntimeRefusal("output_write_failed")


def build_parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(
        prog="renderer-runtime-v2",
        description="quarantine-only staged rhwp export-pdf runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="execute and publish one receipt")
    inspect.add_argument("workspace")
    inspect.add_argument("--run-id", required=True)
    inspect.add_argument("--renderer-id", required=True)
    inspect.add_argument("--binary", required=True)
    inspect.add_argument("--binary-sha256", required=True)
    inspect.add_argument("--certificate", required=True)
    inspect.add_argument("--certificate-sha256", required=True)
    inspect.add_argument("--timeout", type=float, default=60.0)
    verify = sub.add_parser("verify", help="verify one published receipt")
    verify.add_argument("workspace")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--binary", required=True)
    verify.add_argument("--certificate", required=True)
    return parser


def _base_refusal(reason: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": "refused", "reason": reason,
            "proof_grade": "none", "submission_grade": False,
            "promotion": "not_run"}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    try:
        if args.command == "inspect":
            payload = execute_runtime(
                workspace=args.workspace, run_id=args.run_id,
                renderer_id=args.renderer_id, binary=args.binary,
                binary_sha256=args.binary_sha256,
                certificate_path=args.certificate,
                certificate_sha256=args.certificate_sha256,
                timeout=args.timeout)
        else:
            payload = verify_runtime(
                workspace=args.workspace, run_id=args.run_id,
                binary=args.binary, certificate_path=args.certificate)
        _print(payload)
        return EXIT_REFUSED
    except RuntimeRefusal as exc:
        try:
            _print(_base_refusal(exc.reason))
        except RuntimeRefusal:
            pass
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
