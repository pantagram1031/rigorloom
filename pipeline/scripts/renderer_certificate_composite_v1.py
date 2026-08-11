#!/usr/bin/env python3
"""Receipt-only composition of the quarantined T150 runtime and T151 cert.

The composite lane never starts a renderer.  It re-verifies the published
runtime receipt, re-verifies the T151 certificate and exact-document match,
then binds the current source/certificate/runtime-receipt/PDF snapshots into
one diagnostic-only receipt.  No field in this schema is an eligibility or
proof claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

try:
    import diagnostic_candidate_core as _core
    import render_cert_envelope_v2 as _envelope
    import renderer_runtime_v2 as _runtime
except ImportError:  # pragma: no cover
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import render_cert_envelope_v2 as _envelope
    from pipeline.scripts import renderer_runtime_v2 as _runtime


SCHEMA = "rigorloom/renderer-certificate-composite/v1"
ROOT_LEAF = "renderer-certificate-composite"
EVIDENCE_CEILING = "runtime_input_exact_document_certificate_binding_only"
RUN_ID_RE = re.compile(r"[0-9a-f]{16,32}\Z")
OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = getattr(_runtime, "MAX_INPUT_BYTES", 256 * 1024 * 1024)
MAX_CERTIFICATE_BYTES = getattr(_runtime, "MAX_CERTIFICATE_BYTES", 4 * 1024 * 1024)
MAX_OUTPUT_BYTES = getattr(_runtime, "MAX_OUTPUT_BYTES", 256 * 1024 * 1024)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

_RECEIPT_KEYS = frozenset({
    "schema", "status", "run_id", "runtime", "certificate", "input", "output",
    "match", "binding_scope", "evidence_ceiling", "dependency_closure",
    "comparison", "render", "proof_grade", "submission_grade", "promotion",
    "receipt_sha256",
})


class CompositeError(RuntimeError):
    """Expected fail-closed refusal carrying a privacy-safe reason token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.print_usage(sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        raise CompositeError("receipt_schema_invalid")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return _canonical(value) + b"\n"


def _body_hash(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.pop("receipt_sha256", None)
    return _sha(_canonical(body))


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompositeError("receipt_duplicate_key")
        result[key] = value
    return result


def _parse(raw: bytes, *, reason: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_closed,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              CompositeError(reason)))
    except CompositeError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError,
            OverflowError):
        raise CompositeError(reason)


def _result(ok: bool, reason: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok, "reason_code": reason,
        "runtime_binding": "not_established", "proof_grade": "none",
        "submission_grade": False, "promotion": "not_run",
    }
    result.update(extra)
    return result


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise CompositeError("run_id_invalid")
    return value


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _capture(path: Path, max_bytes: int, reason: str) -> dict[str, Any]:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or _is_reparse(info) or getattr(info, "st_nlink", 1) != 1
                or info.st_size <= 0 or info.st_size > max_bytes):
            raise CompositeError(reason)
        raw = _core.read_regular_once(path, max_bytes, reason)
        after = path.lstat()
        if (not stat.S_ISREG(after.st_mode) or stat.S_ISLNK(after.st_mode)
                or _is_reparse(after) or getattr(after, "st_nlink", 1) != 1
                or (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    after.st_size)
                != (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0), len(raw))):
            raise CompositeError(reason)
        if (getattr(after, "st_mtime_ns", 0), getattr(after, "st_ctime_ns", 0)) != (
                getattr(info, "st_mtime_ns", 0), getattr(info, "st_ctime_ns", 0)):
            raise CompositeError(reason)
        return {"data": raw, "sha256": _sha(raw), "bytes": len(raw)}
    except CompositeError:
        raise
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        raise CompositeError(reason)


def _path(path: str | Path, reason: str) -> Path:
    try:
        value = Path(path).expanduser().absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CompositeError(reason)
    return value


def _directory(path: Path, reason: str) -> _core.DirectoryBinding:
    try:
        return _core.DirectoryBinding.open(path, reason=reason)
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        raise CompositeError(reason)


def _workspace_layout(workspace: str | Path, run_id: str,
                     out: str | Path | None = None
                     ) -> tuple[Path, Path, Path, Path, _core.DirectoryBinding]:
    run_id = _validate_run_id(run_id)
    ws = _path(workspace, "workspace_invalid")
    source = ws / "output" / "out.hwpx"
    runtime_root = ws / "output" / "proof" / "renderer-runtime-v2"
    composite_root = ws / "output" / "proof" / ROOT_LEAF
    canonical = composite_root / run_id / "receipt.json"
    if out is not None:
        supplied = _path(out, "output_invalid")
        if supplied != canonical:
            raise CompositeError("output_invalid")
    # Binding the canonical leaf and runtime root rejects leaf aliases and
    # lets the T150 verifier own its own runtime-root custody checks.
    composite_binding = _directory(composite_root, "output_invalid")
    try:
        runtime_binding = _directory(runtime_root, "runtime_receipt_invalid")
        runtime_binding.close()
    except Exception:
        composite_binding.close()
        raise
    return ws, source, runtime_root / run_id / "receipt.json", canonical, composite_binding


def _runtime_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CompositeError("runtime_receipt_invalid")
    if (payload.get("schema") != getattr(_runtime, "SCHEMA", "")
            or payload.get("status") != "analyzed"):
        raise CompositeError("runtime_receipt_invalid")
    for key in ("input", "output", "certificate"):
        if not isinstance(payload.get(key), dict):
            raise CompositeError("runtime_receipt_invalid")
    if payload.get("proof_grade") != "none" or payload.get("submission_grade") is not False \
            or payload.get("promotion") != "not_run":
        raise CompositeError("runtime_receipt_state_invalid")
    renderer = payload.get("renderer")
    if (not isinstance(renderer, dict)
            or SHA256_RE.fullmatch(renderer.get("binary_sha256", "")) is None):
        raise CompositeError("runtime_renderer_invalid")
    source = payload["input"]
    if (source.get("format") != "hwpx" or source.get("preflight") != "strict_complete"
            or type(source.get("bytes")) is not int or source["bytes"] <= 0
            or SHA256_RE.fullmatch(source.get("sha256", "")) is None):
        raise CompositeError("runtime_input_invalid")
    output = payload["output"]
    if (output.get("format") != "pdf" or output.get("state") != "captured"
            or type(output.get("bytes")) is not int or output["bytes"] <= 0
            or SHA256_RE.fullmatch(output.get("sha256", "")) is None
            or type(output.get("pages")) is not int or output["pages"] < 1):
        raise CompositeError("runtime_output_invalid")
    cert = payload["certificate"]
    if (type(cert.get("bytes")) is not int or cert["bytes"] <= 0
            or SHA256_RE.fullmatch(cert.get("sha256", "")) is None
            or cert.get("validation") != "not_run"):
        raise CompositeError("runtime_certificate_invalid")
    return payload


def _certificate_body_sha(raw: bytes) -> str:
    payload = _parse(raw, reason="certificate_schema_invalid")
    if not isinstance(payload, dict):
        raise CompositeError("certificate_schema_invalid")
    value = payload.get("certificate_sha256")
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CompositeError("certificate_schema_invalid")
    return value


def _stage_snapshot(directory: Path, name: str, data: bytes) -> Path:
    """Create one private, no-follow staging file for an exact snapshot."""
    try:
        fd = os.open(str(directory / name), os.O_WRONLY | os.O_CREAT
                     | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return directory / name
    except (OSError, TypeError, ValueError):
        try:
            os.close(fd)  # type: ignore[possibly-undefined]
        except (OSError, UnboundLocalError):
            pass
        raise CompositeError("private_snapshot_failed")


def _component_snapshot(*, workspace: Path, run_id: str, binary: Path,
                        certificate: Path, runtime_path: Path,
                        source_path: Path) -> dict[str, Any]:
    try:
        runtime_payload = _runtime.verify_runtime(
            workspace=workspace, run_id=run_id, binary=binary,
            certificate_path=certificate)
    except Exception as exc:
        reason = getattr(exc, "reason", "runtime_receipt_invalid")
        raise CompositeError(reason)
    runtime_payload = _runtime_shape(runtime_payload)

    binary_path = binary
    binary = _capture(binary_path,
                      getattr(_runtime, "MAX_BINARY_BYTES", 256 * 1024 * 1024),
                      "binary_mismatch")
    if runtime_payload["renderer"]["binary_sha256"] != binary["sha256"]:
        raise CompositeError("binary_mismatch")

    runtime_raw = _capture(runtime_path, MAX_RECEIPT_BYTES,
                            "runtime_receipt_invalid")
    # The runtime verifier has already validated the receipt.  Reparse it here
    # so this lane binds the exact current bytes rather than a returned dict.
    runtime_on_disk = _parse(runtime_raw["data"], reason="runtime_receipt_invalid")
    if not isinstance(runtime_on_disk, dict) or runtime_on_disk != runtime_payload:
        raise CompositeError("runtime_receipt_changed")

    source = _capture(source_path, MAX_SOURCE_BYTES, "runtime_input_mismatch")
    cert_raw = _capture(certificate, MAX_CERTIFICATE_BYTES,
                        "certificate_invalid")
    # Validate T151 only against these already-captured bytes.  This avoids a
    # path generation swap where an invalid certificate A is captured but a
    # valid certificate B is read by the verifier (or vice versa).
    try:
        with tempfile.TemporaryDirectory(prefix="rigorloom-composite-") as staged:
            staged_dir = Path(staged)
            staged_source = _stage_snapshot(staged_dir, "source.hwpx",
                                             source["data"])
            staged_certificate = _stage_snapshot(staged_dir, "certificate.json",
                                                 cert_raw["data"])
            cert_verify = _envelope.verify_certificate(staged_certificate)
            if (not isinstance(cert_verify, dict)
                    or cert_verify.get("ok") is not True):
                raise CompositeError(
                    str(cert_verify.get("reason_code", "certificate_invalid"))
                    if isinstance(cert_verify, dict) else "certificate_invalid")
            body_sha = cert_verify.get("certificate_sha256")
            if not isinstance(body_sha, str) or SHA256_RE.fullmatch(body_sha) is None:
                raise CompositeError("certificate_body_invalid")
            if body_sha != _certificate_body_sha(cert_raw["data"]):
                raise CompositeError("certificate_body_mismatch")

            doc_check = _envelope.check_document(staged_source, staged_certificate)
            if (not isinstance(doc_check, dict) or doc_check.get("ok") is not True
                    or doc_check.get("match") != "exact_measurement_match"
                    or "eligible" in doc_check):
                reason = doc_check.get("reason_code", "exact_measurement_mismatch") \
                    if isinstance(doc_check, dict) else "exact_measurement_mismatch"
                raise CompositeError(str(reason))
            document_id = doc_check.get("document_id")
            if (not isinstance(document_id, str)
                    or OPAQUE_ID_RE.fullmatch(document_id) is None):
                raise CompositeError("exact_measurement_mismatch")
            if doc_check.get("certificate_sha256") != body_sha:
                raise CompositeError("certificate_body_mismatch")
    except CompositeError:
        raise
    except OSError:
        raise CompositeError("private_snapshot_failed")

    runtime_input = runtime_payload["input"]
    if (runtime_input["sha256"] != source["sha256"]
            or runtime_input["bytes"] != source["bytes"]
            or doc_check.get("source_sha256") != source["sha256"]
            or doc_check.get("source_bytes") != source["bytes"]):
        raise CompositeError("runtime_input_mismatch")
    runtime_cert = runtime_payload["certificate"]
    if (runtime_cert["sha256"] != cert_raw["sha256"]
            or runtime_cert["bytes"] != cert_raw["bytes"]):
        raise CompositeError("certificate_hash_mismatch")

    artifact_path = runtime_path.parent / "artifact.pdf"
    artifact = _capture(artifact_path, MAX_OUTPUT_BYTES, "artifact_mismatch")
    runtime_output = runtime_payload["output"]
    if (runtime_output["sha256"] != artifact["sha256"]
            or runtime_output["bytes"] != artifact["bytes"]):
        raise CompositeError("artifact_mismatch")
    try:
        pages = _runtime._validate_pdf(artifact["data"])
    except Exception:
        raise CompositeError("artifact_mismatch")
    if pages != runtime_output["pages"]:
        raise CompositeError("artifact_mismatch")

    # The verifier calls above are fallible callbacks.  Rebind every external
    # input/output after them and compare the complete captured generations.
    final_runtime = _capture(runtime_path, MAX_RECEIPT_BYTES,
                             "runtime_receipt_changed")
    final_source = _capture(source_path, MAX_SOURCE_BYTES, "runtime_input_mismatch")
    final_binary = _capture(binary_path,
                            getattr(_runtime, "MAX_BINARY_BYTES", 256 * 1024 * 1024),
                            "binary_mismatch")
    final_certificate = _capture(certificate, MAX_CERTIFICATE_BYTES,
                                 "certificate_changed")
    final_artifact = _capture(artifact_path, MAX_OUTPUT_BYTES, "artifact_mismatch")
    if (final_runtime["sha256"] != runtime_raw["sha256"]
            or final_runtime["bytes"] != runtime_raw["bytes"]):
        raise CompositeError("runtime_receipt_changed")
    if (final_source["sha256"] != source["sha256"]
            or final_source["bytes"] != source["bytes"]):
        raise CompositeError("runtime_input_mismatch")
    if (final_binary["sha256"] != binary["sha256"]
            or final_binary["bytes"] != binary["bytes"]):
        raise CompositeError("binary_mismatch")
    if (final_certificate["sha256"] != cert_raw["sha256"]
            or final_certificate["bytes"] != cert_raw["bytes"]):
        raise CompositeError("certificate_changed")
    if (final_artifact["sha256"] != artifact["sha256"]
            or final_artifact["bytes"] != artifact["bytes"]):
        raise CompositeError("artifact_mismatch")
    return {
        "runtime": runtime_payload, "runtime_raw": runtime_raw,
        "certificate": cert_raw, "certificate_body_sha256": body_sha,
        "document_id": document_id,
        "source": source, "binary": binary, "artifact": artifact, "pages": pages,
    }


def _build_payload(run_id: str, snap: dict[str, Any]) -> dict[str, Any]:
    runtime_payload = snap["runtime"]
    payload: dict[str, Any] = {
        "schema": SCHEMA, "status": "analyzed", "run_id": run_id,
        "runtime": {
            "receipt_sha256": snap["runtime_raw"]["sha256"],
            "receipt_bytes": snap["runtime_raw"]["bytes"],
            "binary_sha256": runtime_payload["renderer"]["binary_sha256"],
            "binary_bytes": snap["binary"]["bytes"],
            "input_sha256": runtime_payload["input"]["sha256"],
            "input_bytes": runtime_payload["input"]["bytes"],
        },
        "certificate": {
            "file_sha256": snap["certificate"]["sha256"],
            "file_bytes": snap["certificate"]["bytes"],
            "body_sha256": snap["certificate_body_sha256"],
            "document_id": snap["document_id"],
        },
        "input": {
            "format": "hwpx", "sha256": snap["source"]["sha256"],
            "bytes": snap["source"]["bytes"],
        },
        "output": {
            "format": "pdf", "sha256": snap["artifact"]["sha256"],
            "bytes": snap["artifact"]["bytes"], "pages": snap["pages"],
        },
        "match": "exact_measurement_match",
        "binding_scope": "captured_snapshot_only",
        "evidence_ceiling": EVIDENCE_CEILING,
        "dependency_closure": "unknown", "comparison": {"state": "unknown"},
        "render": {"state": "not_run"}, "proof_grade": "none",
        "submission_grade": False, "promotion": "not_run",
    }
    payload["receipt_sha256"] = _body_hash(payload)
    return payload


def _validate_payload(payload: Any, *, run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _RECEIPT_KEYS:
        raise CompositeError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA or payload.get("status") != "analyzed"
            or (run_id is not None and payload.get("run_id") != run_id)
            or payload.get("match") != "exact_measurement_match"
            or payload.get("binding_scope") != "captured_snapshot_only"
            or payload.get("evidence_ceiling") != EVIDENCE_CEILING
            or payload.get("dependency_closure") != "unknown"
            or payload.get("comparison") != {"state": "unknown"}
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False
            or payload.get("promotion") != "not_run"):
        raise CompositeError("receipt_state_invalid")
    for section in ("runtime", "certificate", "input", "output"):
        if not isinstance(payload.get(section), dict):
            raise CompositeError("receipt_schema_invalid")
    runtime = payload["runtime"]
    if (set(runtime) != {"receipt_sha256", "receipt_bytes", "binary_sha256",
                         "binary_bytes", "input_sha256", "input_bytes"}
            or SHA256_RE.fullmatch(runtime.get("receipt_sha256", "")) is None
            or SHA256_RE.fullmatch(runtime.get("binary_sha256", "")) is None
            or SHA256_RE.fullmatch(runtime.get("input_sha256", "")) is None
            or type(runtime.get("receipt_bytes")) is not int or runtime["receipt_bytes"] <= 0
            or type(runtime.get("binary_bytes")) is not int or runtime["binary_bytes"] <= 0
            or type(runtime.get("input_bytes")) is not int or runtime["input_bytes"] <= 0):
        raise CompositeError("receipt_runtime_invalid")
    cert = payload["certificate"]
    if (set(cert) != {"file_sha256", "file_bytes", "body_sha256", "document_id"}
            or SHA256_RE.fullmatch(cert.get("file_sha256", "")) is None
            or SHA256_RE.fullmatch(cert.get("body_sha256", "")) is None
            or type(cert.get("file_bytes")) is not int or cert["file_bytes"] <= 0
            or not isinstance(cert.get("document_id"), str)
            or OPAQUE_ID_RE.fullmatch(cert["document_id"]) is None):
        raise CompositeError("receipt_certificate_invalid")
    source = payload["input"]
    if (set(source) != {"format", "sha256", "bytes"} or source.get("format") != "hwpx"
            or SHA256_RE.fullmatch(source.get("sha256", "")) is None
            or type(source.get("bytes")) is not int or source["bytes"] <= 0):
        raise CompositeError("receipt_input_invalid")
    output = payload["output"]
    if (set(output) != {"format", "sha256", "bytes", "pages"}
            or output.get("format") != "pdf"
            or SHA256_RE.fullmatch(output.get("sha256", "")) is None
            or type(output.get("bytes")) is not int or output["bytes"] <= 0
            or type(output.get("pages")) is not int or output["pages"] < 1):
        raise CompositeError("receipt_output_invalid")
    if (not isinstance(payload.get("run_id"), str)
            or RUN_ID_RE.fullmatch(payload["run_id"]) is None
            or not SHA256_RE.fullmatch(payload.get("receipt_sha256", ""))
            or payload["receipt_sha256"] != _body_hash(payload)):
        raise CompositeError("receipt_hash_mismatch")
    return payload


def _publish(root: Path, run_id: str, output: Path, raw: bytes,
             *, root_binding: _core.DirectoryBinding | None = None) -> None:
    if output != root / run_id / "receipt.json":
        raise CompositeError("output_invalid")
    owned_binding = root_binding is None
    if root_binding is None:
        root_binding = _directory(root, "output_invalid")
    run_binding: _core.DirectoryBinding | None = None
    temporary = f".composite-{os.urandom(10).hex()}"
    temporary_identity: Any = None
    receipt_identity: Any = None
    created_run = False
    try:
        root_binding.mkdir(run_id)
        created_run = True
        run_binding = root_binding.open_directory(run_id)
        temporary_identity = run_binding.write_bytes(temporary, raw)
        try:
            run_binding.link(run_binding.path / temporary, "receipt.json")
        except (_core.CoreError, OSError):
            raise CompositeError("receipt_publish_failed")
        receipt_identity = run_binding.file_identity("receipt.json")
        try:
            run_binding.unlink(temporary)
        except _core.CoreError:
            raise CompositeError("receipt_publish_failed")
        current = _capture(run_binding.path / "receipt.json", MAX_RECEIPT_BYTES,
                           "receipt_publish_failed")
        if current["data"] != raw or current["sha256"] != _sha(raw):
            raise CompositeError("receipt_publish_failed")
        info = (run_binding.path / "receipt.json").lstat()
        if getattr(info, "st_nlink", 1) != 1 or not stat.S_ISREG(info.st_mode):
            raise CompositeError("receipt_publish_failed")
        # The held root guard precedes the final run-layout and receipt
        # identity check.  _validate_run_contents ends with its held-dir
        # listing; no callback or path operation follows before return.
        root_binding.check()
        _validate_run_contents(run_binding, receipt_identity)
    except FileExistsError:
        raise CompositeError("run_exists")
    except CompositeError:
        try:
            if run_binding is not None and temporary_identity is not None:
                try:
                    actual = run_binding.file_identity(temporary)
                    if (actual[0], actual[1], actual[2], actual[5]) == (
                            temporary_identity[0], temporary_identity[1],
                            temporary_identity[2], temporary_identity[5]):
                        run_binding.unlink(temporary)
                except Exception:
                    pass
                if receipt_identity is not None:
                    try:
                        actual = run_binding.file_identity("receipt.json")
                        if (actual[0], actual[1], actual[2], actual[5]) == (
                                receipt_identity[0], receipt_identity[1],
                                receipt_identity[2], receipt_identity[5]):
                            run_binding.unlink("receipt.json")
                    except Exception:
                        pass
            if created_run:
                root_binding.rmdir(run_id)
        except Exception:
            pass
        raise
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        try:
            if run_binding is not None and temporary_identity is not None:
                try:
                    actual = run_binding.file_identity(temporary)
                    if (actual[0], actual[1], actual[2], actual[5]) == (
                            temporary_identity[0], temporary_identity[1],
                            temporary_identity[2], temporary_identity[5]):
                        run_binding.unlink(temporary)
                except Exception:
                    pass
                if receipt_identity is not None:
                    try:
                        actual = run_binding.file_identity("receipt.json")
                        if (actual[0], actual[1], actual[2], actual[5]) == (
                                receipt_identity[0], receipt_identity[1],
                                receipt_identity[2], receipt_identity[5]):
                            run_binding.unlink("receipt.json")
                    except Exception:
                        pass
            if created_run:
                root_binding.rmdir(run_id)
        except Exception:
            pass
        raise CompositeError("receipt_publish_failed")
    finally:
        if run_binding is not None:
            run_binding.close()
        if owned_binding:
            root_binding.close()


def _read_receipt(path: Path, run_id: str) -> tuple[dict[str, Any], bytes]:
    snap = _capture(path, MAX_RECEIPT_BYTES, "receipt_invalid")
    payload = _parse(snap["data"], reason="receipt_schema_invalid")
    _validate_payload(payload, run_id=run_id)
    if snap["data"] != _json_bytes(payload):
        raise CompositeError("receipt_not_canonical")
    return payload, snap["data"]


def _validate_run_contents(
        run_binding: _core.DirectoryBinding,
        expected_identity: _core.FileIdentity | None = None,
        expected_raw: bytes | None = None,
        ) -> _core.FileIdentity:
    """Require a receipt-only run directory under its held directory handle."""
    try:
        run_binding.check()
        receipt = run_binding.path / "receipt.json"
        info = receipt.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or _is_reparse(info) or getattr(info, "st_nlink", 1) != 1):
            raise CompositeError("run_layout_invalid")
        identity = run_binding.file_identity("receipt.json", MAX_RECEIPT_BYTES)
        if expected_identity is not None and (
                identity[0], identity[1], identity[2], identity[5]) != (
                    expected_identity[0], expected_identity[1],
                    expected_identity[2], expected_identity[5]):
            raise CompositeError("run_layout_invalid")
        if expected_raw is not None and (
                identity[2] != len(expected_raw)
                or identity[5] != _sha(expected_raw)):
            raise CompositeError("run_layout_invalid")
        # Keep this as the final filesystem operation.  The caller must not
        # perform another path/callback check after this exact-name listing.
        if run_binding.fd is not None:
            names = list(os.listdir(run_binding.fd))
        else:
            names = [entry.name for entry in run_binding.path.iterdir()]
        if sorted(names) != ["receipt.json"]:
            raise CompositeError("run_layout_invalid")
        return identity
    except CompositeError:
        raise
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        raise CompositeError("run_layout_invalid")


def check_composite(*, workspace: str | Path, run_id: str,
                    binary: str | Path, certificate: str | Path,
                    out: str | Path) -> dict[str, Any]:
    root_binding: _core.DirectoryBinding | None = None
    try:
        workspace_path, source_path, runtime_path, output, root_binding = _workspace_layout(
            workspace, run_id, out)
        try:
            binary_path = _path(binary, "binary_invalid")
            certificate_path = _path(certificate, "certificate_invalid")
            if output in {source_path, runtime_path, certificate_path, binary_path}:
                raise CompositeError("output_invalid")
            snap = _component_snapshot(
                workspace=workspace_path, run_id=run_id, binary=binary_path,
                certificate=certificate_path, runtime_path=runtime_path,
                source_path=source_path)
            payload = _build_payload(run_id, snap)
            _validate_payload(payload, run_id=run_id)
            raw = _json_bytes(payload)
            _publish(output.parent.parent, run_id, output, raw,
                     root_binding=root_binding)
            return payload
        finally:
            root_binding.close()
    except CompositeError as exc:
        return _result(False, exc.reason)
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        return _result(False, "composite_failed")


def verify_composite(*, workspace: str | Path, run_id: str,
                     binary: str | Path, certificate: str | Path) -> dict[str, Any]:
    root_binding: _core.DirectoryBinding | None = None
    try:
        workspace_path, source_path, runtime_path, output, root_binding = _workspace_layout(
            workspace, run_id)
        del output
        run_binding: _core.DirectoryBinding | None = None
        try:
            binary_path = _path(binary, "binary_invalid")
            certificate_path = _path(certificate, "certificate_invalid")
            run_binding = root_binding.open_directory(run_id)
            _validate_run_contents(run_binding)
            payload, raw = _read_receipt(
                run_binding.path / "receipt.json", run_id)
            snap = _component_snapshot(
                workspace=workspace_path, run_id=run_id, binary=binary_path,
                certificate=certificate_path, runtime_path=runtime_path,
                source_path=source_path)
            expected = _build_payload(run_id, snap)
            if expected != payload:
                raise CompositeError("receipt_changed")
            root_binding.check()
            final_payload, final_raw = _read_receipt(
                run_binding.path / "receipt.json", run_id)
            if final_payload != payload or final_raw != raw:
                raise CompositeError("receipt_changed")
            # The exact held-directory layout/digest check is the last
            # filesystem operation.  Nothing fallible follows it.
            _validate_run_contents(run_binding, expected_raw=final_raw)
            return payload
        finally:
            if run_binding is not None:
                run_binding.close()
            root_binding.close()
    except CompositeError as exc:
        return _result(False, exc.reason)
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        return _result(False, "composite_failed")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="renderer_certificate_composite_v1.py")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("workspace")
    check.add_argument("--run-id", required=True)
    check.add_argument("--binary", required=True)
    check.add_argument("--certificate", required=True)
    check.add_argument("--out", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("workspace")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--binary", required=True)
    verify.add_argument("--certificate", required=True)
    return parser


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.command == "check":
            result = check_composite(
                workspace=args.workspace, run_id=args.run_id, binary=args.binary,
                certificate=args.certificate, out=args.out)
        else:
            result = verify_composite(
                workspace=args.workspace, run_id=args.run_id, binary=args.binary,
                certificate=args.certificate)
    except CompositeError as exc:
        result = _result(False, exc.reason)
    try:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    except (BrokenPipeError, OSError, UnicodeError):
        return EXIT_REFUSED
    if args.command == "check":
        return EXIT_REFUSED
    return EXIT_REFUSED if result.get("ok") is not True else EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
