#!/usr/bin/env python3
"""Pathless exact-document measurement envelopes (T151).

This module does not execute a renderer and does not decide whether a new
document is eligible for a certified route.  It seals operator-owned,
already-measured HWPX/reference-PDF pairs and later reports only an exact
source-byte match.  The evidence ceiling is deliberately ``none`` for proof
and submission purposes.
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
from typing import Any

try:
    import diagnostic_candidate_core as _core
    import hwp_equation_diagnostic as _hwpx
    import receipt_sign
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_equation_diagnostic as _hwpx
    from pipeline.scripts import receipt_sign


SCHEMA = "rigorloom/render-cert-envelope/v2"
PRIVATE_SCHEMA = "rigorloom/render-cert-private-manifest/v2"
EVIDENCE_CEILING = "exact_document_measurement_only"
RUNTIME_BINDING = "not_established"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CERTIFICATE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = getattr(_hwpx, "MAX_INPUT_BYTES", 256 * 1024 * 1024)
MAX_REFERENCE_BYTES = 256 * 1024 * 1024
MAX_DOCUMENTS = 256
MAX_JSON_DEPTH = 16
MAX_JSON_ITEMS = 4096
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+ -]{0,63}\Z")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

_MANIFEST_KEYS = frozenset({
    "schema", "reference_renderer", "thresholds", "documents",
})
_RENDERER_KEYS = frozenset({"id", "version"})
_DOCUMENT_KEYS = frozenset({
    "id", "document", "reference_pdf", "metrics", "metrics_sha256",
})
_CERTIFICATE_KEYS = frozenset({
    "schema", "reference_renderer", "manifest_sha256", "thresholds_sha256",
    "measurements", "evidence_ceiling", "runtime_binding", "proof_grade",
    "submission_grade", "promotion", "certificate_sha256",
    "certificate_hmac_sha256",
})
_MEASUREMENT_KEYS = frozenset({
    "id", "source", "reference_pdf_sha256", "reference_pdf_bytes",
    "metrics_sha256",
})
_SOURCE_KEYS = frozenset({"sha256", "bytes"})


class EnvelopeError(RuntimeError):
    """Expected fail-closed refusal with a stable privacy-safe reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.print_usage(sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EnvelopeError("json_duplicate_key")
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        raise EnvelopeError("json_value_invalid")


def _certificate_bytes(value: dict[str, Any]) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _result(ok: bool, reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "reason_code": reason,
        "runtime_binding": RUNTIME_BINDING,
        "proof_grade": "none",
        "submission_grade": False,
        "promotion": "not_run",
    }
    payload.update(extra)
    return payload


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def _safe_id(value: Any, reason: str) -> str:
    if (not isinstance(value, str) or value in {".", ".."}
            or OPAQUE_ID_RE.fullmatch(value) is None):
        raise EnvelopeError(reason)
    return value


def _safe_leaf(value: Any, reason: str) -> str:
    # T151 intentionally implements the smallest contained relative subset:
    # one non-hidden leaf below the private manifest directory.
    if (not isinstance(value, str) or not value or value in {".", ".."}
            or value.startswith(".") or Path(value).name != value
            or "/" in value or "\\" in value or ":" in value):
        raise EnvelopeError(reason)
    return value


def _validate_json_value(value: Any, *, depth: int = 0,
                         budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [MAX_JSON_ITEMS]
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_JSON_DEPTH:
        raise EnvelopeError("measurement_value_invalid")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EnvelopeError("measurement_value_invalid")
        return
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            raise EnvelopeError("measurement_value_invalid")
        if len(encoded) > 1024 or "\x00" in value:
            raise EnvelopeError("measurement_value_invalid")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1, budget=budget)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str) or not key or len(key) > 128
                    or "\x00" in key):
                raise EnvelopeError("measurement_value_invalid")
            _validate_json_value(item, depth=depth + 1, budget=budget)
        return
    raise EnvelopeError("measurement_value_invalid")


def _parse_json(raw: bytes, *, duplicate_reason: str,
                invalid_reason: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_duplicates_closed,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                EnvelopeError(invalid_reason)),
        )
    except EnvelopeError as exc:
        if exc.reason == "json_duplicate_key":
            raise EnvelopeError(duplicate_reason)
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError,
            OverflowError):
        raise EnvelopeError(invalid_reason)


def _capture_bound(binding: _core.DirectoryBinding, name: str, *,
                   max_bytes: int, reason: str) -> bytes:
    """Capture one leaf through a held parent directory."""
    path = binding.path / name
    try:
        binding.check()
        before = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & reparse
                or getattr(before, "st_nlink", 1) != 1
                or before.st_size <= 0 or before.st_size > max_bytes):
            raise EnvelopeError(reason)
        fd = binding.open_file(name, os.O_RDONLY)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode)
                    or getattr(opened, "st_file_attributes", 0) & reparse
                    or getattr(opened, "st_nlink", 1) != 1
                    or (getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0),
                        opened.st_size)
                    != (getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
                        before.st_size)):
                raise EnvelopeError(reason)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise EnvelopeError(reason)
                chunks.append(chunk)
            after = os.fstat(fd)
            if ((getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                 after.st_size, getattr(after, "st_nlink", 1))
                    != (getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0),
                        total, 1)):
                raise EnvelopeError(reason)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
        final = path.lstat()
        if ((getattr(final, "st_dev", 0), getattr(final, "st_ino", 0),
             final.st_size, getattr(final, "st_nlink", 1))
                != (getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
                    len(raw), 1)):
            raise EnvelopeError(reason)
        binding.check()
        return raw
    except EnvelopeError:
        raise
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        raise EnvelopeError(reason)


def _identity_bytes_bound(binding: _core.DirectoryBinding, name: str,
                          raw: bytes, *, max_bytes: int, reason: str) -> None:
    if _capture_bound(binding, name, max_bytes=max_bytes, reason=reason) != raw:
        raise EnvelopeError(reason)


def _validate_hwpx(raw: bytes) -> None:
    try:
        _hwpx._scan_bytes(raw)
    except Exception as exc:
        reason = getattr(exc, "reason", "document_invalid")
        del reason
        raise EnvelopeError("document_invalid")


def _validate_reference_pdf(raw: bytes) -> None:
    # Reference rendering quality is operator evidence, not interpreted here.
    # The v2 envelope only binds a non-empty PDF snapshot.
    if not raw.startswith(b"%PDF-"):
        raise EnvelopeError("reference_pdf_invalid")


def _load_private_manifest(binding: _core.DirectoryBinding,
                           name: str) -> tuple[dict[str, Any], bytes]:
    raw = _capture_bound(
        binding, name, max_bytes=MAX_MANIFEST_BYTES, reason="manifest_identity")
    payload = _parse_json(
        raw, duplicate_reason="manifest_duplicate_key",
        invalid_reason="manifest_schema_invalid",
    )
    if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
        raise EnvelopeError("manifest_schema_invalid")
    if payload.get("schema") != PRIVATE_SCHEMA:
        raise EnvelopeError("manifest_schema_invalid")
    renderer = payload.get("reference_renderer")
    if (not isinstance(renderer, dict) or set(renderer) != _RENDERER_KEYS
            or renderer.get("id") != "hancom_windows"
            or not isinstance(renderer.get("version"), str)
            or VERSION_RE.fullmatch(renderer["version"]) is None):
        raise EnvelopeError("manifest_renderer_invalid")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise EnvelopeError("manifest_thresholds_invalid")
    _validate_json_value(thresholds)
    documents = payload.get("documents")
    if (not isinstance(documents, list) or not documents
            or len(documents) > MAX_DOCUMENTS):
        raise EnvelopeError("manifest_documents_invalid")
    seen_ids: set[str] = set()
    for item in documents:
        if not isinstance(item, dict) or set(item) != _DOCUMENT_KEYS:
            raise EnvelopeError("manifest_document_invalid")
        item_id = _safe_id(item.get("id"), "manifest_document_id")
        if item_id in seen_ids:
            raise EnvelopeError("manifest_document_id")
        seen_ids.add(item_id)
        _safe_leaf(item.get("document"), "manifest_document_path")
        _safe_leaf(item.get("reference_pdf"), "manifest_reference_path")
        metrics = item.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise EnvelopeError("manifest_metrics_invalid")
        _validate_json_value(metrics)
        expected = item.get("metrics_sha256")
        actual = _sha256(_canonical_bytes(metrics))
        if (not isinstance(expected, str) or expected != actual
                or SHA256_RE.fullmatch(expected) is None):
            raise EnvelopeError("manifest_metrics_hash_mismatch")
    return payload, raw


def _validate_measurement(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != _MEASUREMENT_KEYS:
        raise EnvelopeError("certificate_measurement_invalid")
    _safe_id(item.get("id"), "certificate_measurement_invalid")
    source = item.get("source")
    if (not isinstance(source, dict) or set(source) != _SOURCE_KEYS
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not isinstance(source.get("sha256"), str)
            or SHA256_RE.fullmatch(source["sha256"]) is None):
        raise EnvelopeError("certificate_measurement_invalid")
    for name in ("reference_pdf_sha256", "metrics_sha256"):
        if (not isinstance(item.get(name), str)
                or SHA256_RE.fullmatch(item[name]) is None):
            raise EnvelopeError("certificate_measurement_invalid")
    if (isinstance(item.get("reference_pdf_bytes"), bool)
            or not isinstance(item.get("reference_pdf_bytes"), int)
            or item["reference_pdf_bytes"] <= 0):
        raise EnvelopeError("certificate_measurement_invalid")
    return item


def _validate_certificate_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _CERTIFICATE_KEYS:
        raise EnvelopeError("certificate_schema_invalid")
    if (payload.get("schema") != SCHEMA
            or payload.get("evidence_ceiling") != EVIDENCE_CEILING
            or payload.get("runtime_binding") != RUNTIME_BINDING
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False
            or payload.get("promotion") != "not_run"):
        raise EnvelopeError("certificate_state_invalid")
    renderer = payload.get("reference_renderer")
    if (not isinstance(renderer, dict) or set(renderer) != _RENDERER_KEYS
            or renderer.get("id") != "hancom_windows"
            or not isinstance(renderer.get("version"), str)
            or VERSION_RE.fullmatch(renderer["version"]) is None):
        raise EnvelopeError("certificate_renderer_invalid")
    for name in ("manifest_sha256", "thresholds_sha256",
                 "certificate_sha256", "certificate_hmac_sha256"):
        if (not isinstance(payload.get(name), str)
                or SHA256_RE.fullmatch(payload[name]) is None):
            raise EnvelopeError("certificate_hash_invalid")
    measurements = payload.get("measurements")
    if (not isinstance(measurements, list) or not measurements
            or len(measurements) > MAX_DOCUMENTS):
        raise EnvelopeError("certificate_measurements_invalid")
    ids: set[str] = set()
    hashes: set[str] = set()
    for item in measurements:
        _validate_measurement(item)
        if item["id"] in ids or item["source"]["sha256"] in hashes:
            raise EnvelopeError("certificate_measurements_invalid")
        ids.add(item["id"])
        hashes.add(item["source"]["sha256"])
    return payload


def _certificate_body_hash(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.pop("certificate_sha256", None)
    body.pop("certificate_hmac_sha256", None)
    return _sha256(_canonical_bytes(body))


def _read_certificate_bound(binding: _core.DirectoryBinding,
                            name: str) -> tuple[dict[str, Any], bytes]:
    raw = _capture_bound(
        binding, name, max_bytes=MAX_CERTIFICATE_BYTES,
        reason="certificate_invalid")
    payload = _parse_json(
        raw, duplicate_reason="certificate_duplicate_key",
        invalid_reason="certificate_schema_invalid",
    )
    _validate_certificate_shape(payload)
    if raw != _certificate_bytes(payload):
        raise EnvelopeError("certificate_not_canonical")
    if payload["certificate_sha256"] != _certificate_body_hash(payload):
        raise EnvelopeError("certificate_hash_mismatch")
    try:
        key = receipt_sign.load_operator_key(create=False)
    except receipt_sign.ReceiptKeyError:
        raise EnvelopeError("certificate_key_unavailable")
    if not receipt_sign.verify_hmac_sha256(
        payload, key, payload["certificate_hmac_sha256"],
        omit_fields=("certificate_hmac_sha256",),
    ):
        raise EnvelopeError("certificate_hmac_mismatch")
    return payload, raw


def _remove_owned_bound(binding: _core.DirectoryBinding, name: str,
                        expected: tuple[Any, ...], raw: bytes) -> None:
    """Remove only the inode created by this publisher, even if hardlinked."""
    try:
        path = binding.path / name
        before = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & reparse
                or (getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
                    before.st_size) != (expected[0], expected[1], len(raw))):
            return
        fd = binding.open_file(name, os.O_RDONLY)
        try:
            opened = os.fstat(fd)
            if ((getattr(opened, "st_dev", 0), getattr(opened, "st_ino", 0),
                 opened.st_size) != (expected[0], expected[1], len(raw))):
                return
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > len(raw):
                    return
            if b"".join(chunks) != raw:
                return
        finally:
            os.close(fd)
        final = path.lstat()
        if ((getattr(final, "st_dev", 0), getattr(final, "st_ino", 0),
             final.st_size) != (expected[0], expected[1], len(raw))):
            return
        binding.unlink(name)
    except (OSError, _core.CoreError, RuntimeError, TypeError, ValueError):
        return


def _atomic_publish(target: Path, raw: bytes) -> None:
    parent = target.parent
    if not target.name:
        raise EnvelopeError("certificate_output_invalid")
    try:
        binding = _core.DirectoryBinding.open(
            parent, reason="certificate_output_invalid")
    except _core.CoreError:
        raise EnvelopeError("certificate_output_invalid")
    temporary = f".{target.name}.{os.urandom(8).hex()}.tmp"
    target_created = False
    owned_identity: tuple[Any, ...] | None = None
    try:
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise EnvelopeError("certificate_output_exists")
        owned_identity = binding.write_bytes(temporary, raw)
        try:
            if binding.fd is not None:
                os.link(temporary, target.name,
                        src_dir_fd=binding.fd, dst_dir_fd=binding.fd)
            else:
                os.link(str(parent / temporary), str(target))
            target_created = True
        except FileExistsError:
            raise EnvelopeError("certificate_output_exists")
        except OSError:
            raise EnvelopeError("certificate_publish_failed")
        try:
            binding.unlink(temporary)
        except _core.CoreError:
            raise EnvelopeError("certificate_publish_failed")
        temporary = ""
        if _capture_bound(binding, target.name, max_bytes=MAX_CERTIFICATE_BYTES,
                          reason="certificate_publish_failed") != raw:
            raise EnvelopeError("certificate_publish_failed")
        final_payload, final_raw = _read_certificate_bound(binding, target.name)
        if final_raw != raw or _certificate_bytes(final_payload) != raw:
            raise EnvelopeError("certificate_publish_failed")
    except Exception:
        if temporary:
            try:
                binding.unlink(temporary)
            except Exception:
                pass
        if target_created and owned_identity is not None:
            _remove_owned_bound(binding, target.name, owned_identity, raw)
        raise
    finally:
        binding.close()


def issue_certificate(manifest_path: str | Path,
                      output_path: str | Path) -> dict[str, Any]:
    try:
        manifest = Path(manifest_path).expanduser().absolute()
        output = Path(output_path).expanduser().absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        raise EnvelopeError("path_invalid")
    try:
        root = _core.DirectoryBinding.open(
            manifest.parent, reason="manifest_root_invalid")
    except _core.CoreError:
        raise EnvelopeError("manifest_root_invalid")
    captures: list[tuple[str, bytes, int, str]] = []
    measurements: list[dict[str, Any]] = []
    source_hashes: set[str] = set()
    try:
        manifest_payload, manifest_raw = _load_private_manifest(root, manifest.name)
        for item in manifest_payload["documents"]:
            source_name = item["document"]
            reference_name = item["reference_pdf"]
            source = _capture_bound(
                root, source_name, max_bytes=MAX_SOURCE_BYTES,
                reason="document_identity",
            )
            _validate_hwpx(source)
            reference = _capture_bound(
                root, reference_name, max_bytes=MAX_REFERENCE_BYTES,
                reason="reference_identity",
            )
            _validate_reference_pdf(reference)
            source_hash = _sha256(source)
            if source_hash in source_hashes:
                raise EnvelopeError("manifest_document_duplicate")
            source_hashes.add(source_hash)
            measurements.append({
                "id": item["id"],
                "source": {"sha256": source_hash, "bytes": len(source)},
                "reference_pdf_sha256": _sha256(reference),
                "reference_pdf_bytes": len(reference),
                "metrics_sha256": item["metrics_sha256"],
            })
            captures.append((source_name, source, MAX_SOURCE_BYTES,
                             "document_changed"))
            captures.append((reference_name, reference, MAX_REFERENCE_BYTES,
                             "reference_changed"))
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "reference_renderer": manifest_payload["reference_renderer"],
            "manifest_sha256": _sha256(manifest_raw),
            "thresholds_sha256": _sha256(
                _canonical_bytes(manifest_payload["thresholds"])),
            "measurements": measurements,
            "evidence_ceiling": EVIDENCE_CEILING,
            "runtime_binding": RUNTIME_BINDING,
            "proof_grade": "none",
            "submission_grade": False,
            "promotion": "not_run",
        }
        payload["certificate_sha256"] = _certificate_body_hash(payload)
        try:
            key = receipt_sign.load_operator_key(create=True)
        except receipt_sign.ReceiptKeyError:
            raise EnvelopeError("certificate_key_unavailable")
        payload["certificate_hmac_sha256"] = receipt_sign.hmac_sha256(
            payload, key, omit_fields=("certificate_hmac_sha256",),
        )
        _validate_certificate_shape(payload)
        raw = _certificate_bytes(payload)

        # All private inputs are rebound before any public certificate appears.
        _identity_bytes_bound(
            root, manifest.name, manifest_raw, max_bytes=MAX_MANIFEST_BYTES,
            reason="manifest_changed")
        for name, captured, limit, reason in captures:
            _identity_bytes_bound(root, name, captured, max_bytes=limit,
                                  reason=reason)
        root.check()
        _atomic_publish(output, raw)
        return _result(True, "certificate_issued",
                       certificate_sha256=payload["certificate_sha256"])
    except _core.CoreError as exc:
        raise EnvelopeError(exc.reason)
    finally:
        root.close()


def verify_certificate(certificate_path: str | Path) -> dict[str, Any]:
    try:
        path = Path(certificate_path).expanduser().absolute()
        binding = _core.DirectoryBinding.open(
            path.parent, reason="certificate_invalid")
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        return _result(False, "certificate_invalid")
    try:
        payload, raw = _read_certificate_bound(binding, path.name)
        final_payload, final_raw = _read_certificate_bound(binding, path.name)
        if final_payload != payload or final_raw != raw:
            raise EnvelopeError("certificate_changed")
        return _result(True, "certificate_verified",
                       certificate_sha256=payload["certificate_sha256"],
                       evidence_ceiling=EVIDENCE_CEILING)
    except EnvelopeError as exc:
        return _result(False, exc.reason)
    finally:
        binding.close()


def check_document(document_path: str | Path,
                   certificate_path: str | Path) -> dict[str, Any]:
    try:
        document = Path(document_path).expanduser().absolute()
        certificate = Path(certificate_path).expanduser().absolute()
        document_binding = _core.DirectoryBinding.open(
            document.parent, reason="document_identity")
        certificate_binding = _core.DirectoryBinding.open(
            certificate.parent, reason="certificate_invalid")
    except (_core.CoreError, OSError, RuntimeError, TypeError, ValueError):
        return _result(False, "path_invalid")
    try:
        cert, cert_raw = _read_certificate_bound(
            certificate_binding, certificate.name)
        captured = _capture_bound(
            document_binding, document.name, max_bytes=MAX_SOURCE_BYTES,
            reason="document_identity",
        )
        _validate_hwpx(captured)
        digest = _sha256(captured)
        matches = [item for item in cert["measurements"]
                   if item["source"] == {"sha256": digest,
                                         "bytes": len(captured)}]
        if len(matches) != 1:
            raise EnvelopeError("exact_measurement_mismatch")
        # Alternate the final captures so mutation of either independently
        # mutable input during the other input's validation is detected.  The
        # result still describes these captured snapshots, never future path
        # state.
        _identity_bytes_bound(
            document_binding, document.name, captured,
            max_bytes=MAX_SOURCE_BYTES, reason="document_changed")
        _validate_hwpx(captured)
        final_cert, final_cert_raw = _read_certificate_bound(
            certificate_binding, certificate.name)
        if final_cert != cert or final_cert_raw != cert_raw:
            raise EnvelopeError("certificate_changed")
        _identity_bytes_bound(
            document_binding, document.name, captured,
            max_bytes=MAX_SOURCE_BYTES, reason="document_changed")
        return _result(
            True, "exact_measurement_match",
            match="exact_measurement_match", document_id=matches[0]["id"],
            certificate_sha256=cert["certificate_sha256"],
            source_sha256=digest, source_bytes=len(captured),
            binding_scope="captured_snapshot_only",
            evidence_ceiling=EVIDENCE_CEILING,
        )
    except EnvelopeError as exc:
        return _result(False, exc.reason)
    finally:
        certificate_binding.close()
        document_binding.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(prog="render_cert_envelope_v2.py")
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("manifest")
    issue.add_argument("--out", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("certificate")
    check = commands.add_parser("check")
    check.add_argument("document")
    check.add_argument("certificate")
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.command == "issue":
            result = issue_certificate(args.manifest, args.out)
            code = EXIT_OK
        elif args.command == "verify":
            result = verify_certificate(args.certificate)
            code = EXIT_OK if result["ok"] else EXIT_REFUSED
        else:
            result = check_document(args.document, args.certificate)
            # Exact-measurement provenance is diagnostic-only, even on match.
            code = EXIT_REFUSED
    except EnvelopeError as exc:
        result = _result(False, exc.reason)
        code = EXIT_REFUSED
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
