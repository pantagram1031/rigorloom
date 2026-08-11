#!/usr/bin/env python3
"""Document-scoped renderer measurement, certification, and eligibility checks.

The harness never invokes Hancom.  Corpus reference PDFs and their hashes are
immutable inputs produced by the operator's Windows reference facility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import stat
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable

import feature_extract
import receipt_sign
import diagnostic_candidate_core


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_ID_RE = re.compile(r"^[^./\\]+$")
DEFAULT_DPI = 300
DEFAULT_RENDER_TIMEOUT = 240.0
CERTIFICATE_HMAC_FIELD = "certificate_hmac_sha256"


def _absolute_lexical(path: str | Path) -> Path:
    """Normalize ``..`` without resolving a symlink leaf or ancestor."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _json_bytes(payload) -> bytes:
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except ValueError as exc:
        if "Out of range float values" in str(exc):
            raise ValueError("nonfinite_json_value") from exc
        raise


def _reject_duplicate_json_pairs(pairs):
    """Build JSON objects without silently accepting duplicate member names."""
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate_json_key")
        payload[key] = value
    return payload


def _reject_nonfinite_json_constant(_constant: str):
    raise ValueError("nonfinite_json_value")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite_json_value")
    return parsed


def _json_loads(text: str):
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=_reject_nonfinite_json_constant,
        parse_float=_parse_finite_json_float,
    )


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


PRIVATE_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024


def _private_json_bytes(payload: dict) -> bytes:
    """Encode a private measure/certificate artifact once before publication."""
    try:
        return (json.dumps(
            payload, ensure_ascii=False, indent=2, allow_nan=False,
        ) + "\n").encode("utf-8")
    except ValueError as exc:
        if "Out of range float values" in str(exc):
            raise ValueError("nonfinite_json_value") from exc
        raise


def _private_capture_bound(binding, name: str, *, lexical_path: Path | None = None,
                           parent_guard: dict | None = None):
    """Capture one bounded generation from one opened no-follow handle.

    Publication cleanup uses the held directory descriptor.  The final
    success check additionally supplies ``lexical_path`` so the requested
    output spelling is reopened no-follow and rebound to the same generation
    immediately before return.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if parent_guard is not None:
        diagnostic_candidate_core.check_root_guard(parent_guard)
    if lexical_path is not None:
        try:
            fd = os.open(str(lexical_path), flags)
        except (OSError, TypeError, ValueError) as exc:
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed") from exc
    elif binding.fd is not None:
        try:
            fd = os.open(name, flags, dir_fd=binding.fd)
        except (OSError, TypeError, ValueError) as exc:
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed") from exc
    else:
        fd = binding.open_file(name, flags)
    try:
        before = os.fstat(fd)
        if parent_guard is not None:
            diagnostic_candidate_core.check_root_guard(parent_guard)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISREG(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & reparse
                or before.st_size < 0
                or before.st_size > PRIVATE_ARTIFACT_MAX_BYTES):
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                fd, min(65536, PRIVATE_ARTIFACT_MAX_BYTES - total + 1),
            )
            if not chunk:
                break
            total += len(chunk)
            if total > PRIVATE_ARTIFACT_MAX_BYTES:
                raise diagnostic_candidate_core.CoreError(
                    "private_output_changed")
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        stable = (
            getattr(before, "st_dev", 0), getattr(before, "st_ino", 0),
            before.st_size, getattr(before, "st_nlink", 0),
            getattr(before, "st_mtime_ns", 0),
            getattr(before, "st_ctime_ns", 0),
        )
        final = (
            getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
            after.st_size, getattr(after, "st_nlink", 0),
            getattr(after, "st_mtime_ns", 0),
            getattr(after, "st_ctime_ns", 0),
        )
        if stable != final or after.st_size != len(raw):
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed")

        # Rebind the path spelling to the same opened generation while the
        # handle remains live.  POSIX uses the held dirfd; Windows' held
        # directory handle blocks parent deletion/rename.
        if lexical_path is not None:
            path_info = lexical_path.lstat()
        elif binding.fd is not None:
            path_info = os.stat(name, dir_fd=binding.fd, follow_symlinks=False)
        else:
            path_info = (binding.path / name).lstat()
        if parent_guard is not None:
            diagnostic_candidate_core.check_root_guard(parent_guard)
        if ((getattr(path_info, "st_dev", 0), getattr(path_info, "st_ino", 0),
             getattr(path_info, "st_size", 0),
             getattr(path_info, "st_nlink", 0),
             getattr(path_info, "st_mtime_ns", 0),
             getattr(path_info, "st_ctime_ns", 0),
             stat.S_IFMT(getattr(path_info, "st_mode", 0)),
             getattr(path_info, "st_file_attributes", 0))
                != (getattr(after, "st_dev", 0), getattr(after, "st_ino", 0),
                    getattr(after, "st_size", 0),
                    getattr(after, "st_nlink", 0),
                    getattr(after, "st_mtime_ns", 0),
                    getattr(after, "st_ctime_ns", 0),
                    stat.S_IFMT(getattr(after, "st_mode", 0)),
                    getattr(after, "st_file_attributes", 0))):
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed")

        # The path rebind itself is a race seam: a same-size in-place write
        # can occur immediately after the path stat.  Rewind the still-held
        # descriptor and read a second generation before returning; no path
        # operation follows this final raw/identity check.
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            second_chunks: list[bytes] = []
            second_total = 0
            while True:
                chunk = os.read(
                    fd, min(65536,
                           PRIVATE_ARTIFACT_MAX_BYTES - second_total + 1),
                )
                if not chunk:
                    break
                second_total += len(chunk)
                if second_total > PRIVATE_ARTIFACT_MAX_BYTES:
                    raise diagnostic_candidate_core.CoreError(
                        "private_output_changed")
                second_chunks.append(chunk)
            second_raw = b"".join(second_chunks)
            final_after = os.fstat(fd)
        except diagnostic_candidate_core.CoreError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed") from exc
        if ((second_raw != raw or second_total != len(raw)
             or getattr(final_after, "st_dev", 0)
                != getattr(after, "st_dev", 0)
             or getattr(final_after, "st_ino", 0)
                != getattr(after, "st_ino", 0)
             or getattr(final_after, "st_size", 0)
                != getattr(after, "st_size", 0)
             or getattr(final_after, "st_nlink", 0)
                != getattr(after, "st_nlink", 0)
             or getattr(final_after, "st_mtime_ns", 0)
                != getattr(after, "st_mtime_ns", 0)
             or getattr(final_after, "st_ctime_ns", 0)
                != getattr(after, "st_ctime_ns", 0))):
            raise diagnostic_candidate_core.CoreError(
                "private_output_changed")
        identity = (
            getattr(final_after, "st_dev", 0),
            getattr(final_after, "st_ino", 0),
            second_total, getattr(final_after, "st_mtime_ns", 0),
            getattr(final_after, "st_ctime_ns", 0),
            hashlib.sha256(second_raw).hexdigest(),
        )
        return identity, getattr(final_after, "st_nlink", 0), second_raw
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _private_bound_identity(binding, name: str):
    identity, nlink, _ = _private_capture_bound(binding, name)
    return identity, nlink


def _private_same_identity(actual, expected) -> bool:
    return diagnostic_candidate_core.same_file_identity(actual, expected)


def _private_bound_rename(binding, source: str, destination: str) -> None:
    if binding.fd is not None:
        os.rename(source, destination, src_dir_fd=binding.fd,
                  dst_dir_fd=binding.fd)
    else:
        binding.check()
        os.rename(str(binding.path / source), str(binding.path / destination))


def _private_bound_link(binding, source: str, destination: str) -> None:
    if binding.fd is not None:
        binding.check()
        os.link(source, destination, src_dir_fd=binding.fd,
                dst_dir_fd=binding.fd)
    else:
        binding.link(binding.path / source, destination)


def _private_restore_quarantine(binding, quarantine: str, original: str) -> None:
    try:
        _private_bound_link(binding, quarantine, original)
    except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
        return
    try:
        if binding.fd is not None:
            os.unlink(quarantine, dir_fd=binding.fd)
        else:
            binding.unlink(quarantine)
    except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
        pass


def _private_quarantine_owned(binding, name: str, expected,
                              *, allow_partial: bool = False) -> bool:
    """Move a candidate to a unique bound name before identity inspection."""
    quarantine = f".{name}.rollback.{secrets.token_hex(16)}"
    try:
        _private_bound_rename(binding, name, quarantine)
    except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
        return False
    try:
        actual, nlink, observed = _private_capture_bound(binding, quarantine)
        owned = _private_same_identity(actual, expected)
        if allow_partial and expected[5] == "":
            owned = (actual[0], actual[1]) == (expected[0], expected[1])
        if not owned:
            _private_restore_quarantine(binding, quarantine, name)
            return False
        # Rebind the quarantine generation immediately before deletion.  A
        # same-name overwrite after the first capture is foreign and must be
        # restored/preserved rather than unlinked.
        confirmed, confirmed_nlink, confirmed_raw = _private_capture_bound(
            binding, quarantine,
        )
        if ((not _private_same_identity(confirmed, actual))
                or confirmed_nlink != nlink or confirmed_raw != observed):
            _private_restore_quarantine(binding, quarantine, name)
            return False
        # Atomically move the confirmed generation once more before deletion.
        # A replacement after the second capture therefore lands in the final
        # quarantine name and is rechecked instead of being unlinked blindly.
        final_name = f"{quarantine}.final.{secrets.token_hex(16)}"
        try:
            _private_bound_rename(binding, quarantine, final_name)
        except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
            _private_restore_quarantine(binding, quarantine, name)
            return False
        try:
            final_actual, final_nlink, final_raw = _private_capture_bound(
                binding, final_name,
            )
            final_owned = _private_same_identity(final_actual, expected)
            if allow_partial and expected[5] == "":
                final_owned = (final_actual[0], final_actual[1]) == (
                    expected[0], expected[1],
                )
            if (not final_owned or final_nlink != nlink
                    or final_raw != observed):
                _private_restore_quarantine(binding, final_name, name)
                return False
            if binding.fd is not None:
                os.unlink(final_name, dir_fd=binding.fd)
            else:
                binding.unlink(final_name)
            return True
        except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
            # If the unlink completed but reported a post-commit fault, the
            # final quarantine is gone and ownership was already resolved.
            try:
                if binding.fd is not None:
                    os.stat(final_name, dir_fd=binding.fd,
                            follow_symlinks=False)
                else:
                    (binding.path / final_name).lstat()
            except FileNotFoundError:
                return True
            except (OSError, TypeError, ValueError):
                return False
            _private_restore_quarantine(binding, final_name, name)
            return False
    except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
        # If the unlink completed but reported a post-commit fault, the
        # quarantine is gone and ownership was already resolved.
        try:
            if binding.fd is not None:
                os.stat(quarantine, dir_fd=binding.fd, follow_symlinks=False)
            else:
                (binding.path / quarantine).lstat()
        except FileNotFoundError:
            return True
        except (OSError, TypeError, ValueError):
            return False
        _private_restore_quarantine(binding, quarantine, name)
        return False


def _private_validate_target(binding, name: str, expected, raw: bytes,
                             *, lexical_path: Path | None = None,
                             parent_guard: dict | None = None) -> None:
    actual, nlink, observed = _private_capture_bound(
        binding, name, lexical_path=lexical_path,
        parent_guard=parent_guard,
    )
    if (nlink != 1 or not _private_same_identity(actual, expected)
            or observed != raw):
        raise diagnostic_candidate_core.CoreError("private_output_changed")


def _private_stage_bytes(binding, name: str, raw: bytes):
    """Create a temp with an owned pre-write identity, then fsync its bytes."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if binding.fd is not None:
        binding.check()
        fd = os.open(name, flags, 0o600, dir_fd=binding.fd)
    else:
        fd = binding.open_file(name, flags, 0o600)
    before = os.fstat(fd)
    owned_identity = (
        getattr(before, "st_dev", 0), getattr(before, "st_ino", 0), 0,
        getattr(before, "st_mtime_ns", 0), getattr(before, "st_ctime_ns", 0), "",
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        identity, nlink, observed = _private_capture_bound(binding, name)
        if nlink != 1 or observed != raw:
            raise diagnostic_candidate_core.CoreError("private_output_changed")
        return identity
    except diagnostic_candidate_core.CoreError as exc:
        setattr(exc, "private_owned_identity", owned_identity)
        raise
    except (OSError, TypeError, ValueError) as exc:
        error = diagnostic_candidate_core.CoreError("private_output_write_failed")
        setattr(error, "private_owned_identity", owned_identity)
        raise error from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _write_private_artifact_json(path: str | Path, payload: dict) -> None:
    """Publish a fresh private measure/certificate artifact with custody."""
    target = Path(path).expanduser().absolute()
    parent = target.parent
    raw = _private_json_bytes(payload)
    if len(raw) > PRIVATE_ARTIFACT_MAX_BYTES:
        raise diagnostic_candidate_core.CoreError("private_output_too_large")
    # Bind the complete lexical parent chain before opening the held leaf.
    # A regular immediate parent can still be reached through an interior
    # symlink/reparse alias; reject that spelling rather than allowing the
    # private artifact to escape the caller's canonical output tree.
    try:
        parent_guard = diagnostic_candidate_core.capture_root_guard(
            parent, parent.resolve(strict=True),
        )
        diagnostic_candidate_core.check_root_guard(parent_guard)
    except diagnostic_candidate_core.CoreError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise diagnostic_candidate_core.CoreError(
            "private_output_parent_invalid",
        ) from exc
    try:
        binding = diagnostic_candidate_core.DirectoryBinding.open(
            parent, reason="private_output_parent_invalid",
        )
    except diagnostic_candidate_core.CoreError:
        raise

    temporary = f".{target.name}.{secrets.token_hex(16)}.tmp"
    staged_identity = None
    target_identity = None
    linked = False
    try:
        diagnostic_candidate_core.check_root_guard(parent_guard)
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise diagnostic_candidate_core.CoreError("private_output_exists")

        try:
            staged_identity = _private_stage_bytes(binding, temporary, raw)
        except diagnostic_candidate_core.CoreError as exc:
            staged_identity = getattr(exc, "private_owned_identity", None)
            raise
        # Staging intentionally changes the held directory's timestamps;
        # refresh the generation while retaining its device/inode guard.
        diagnostic_candidate_core.check_root_guard(
            parent_guard, refresh=True,
        )
        # No-replace publication is relative to the held parent.  A target
        # created after the initial lstat therefore fails without overwrite.
        diagnostic_candidate_core.check_root_guard(parent_guard)
        _private_bound_link(binding, temporary, target.name)
        linked = True
        target_identity, _ = _private_bound_identity(binding, target.name)
        if not _private_same_identity(target_identity, staged_identity):
            raise diagnostic_candidate_core.CoreError("private_output_changed")

        # The parent guard is checked before final artifact validation.  No
        # path-based work follows the final bound identity check on success.
        binding.check()
        diagnostic_candidate_core.check_root_guard(
            parent_guard, refresh=True,
        )
        detached = _private_quarantine_owned(
            binding, temporary, staged_identity,
        )
        try:
            binding.check()
            diagnostic_candidate_core.check_root_guard(
                parent_guard, refresh=True,
            )
            _private_validate_target(
                binding, target.name, staged_identity, raw,
                lexical_path=target, parent_guard=parent_guard,
            )
        except diagnostic_candidate_core.CoreError:
            if detached:
                raise
            raise
        # If cleanup raised after unlinking the token, target validation above
        # proves the commit completed; do not turn it into a false failure.
        temporary = ""
        return
    except FileExistsError:
        raise diagnostic_candidate_core.CoreError("private_output_exists")
    except (diagnostic_candidate_core.CoreError, OSError, TypeError, ValueError):
        # Roll back only identities created by this call.  Bound relative
        # operations remain usable even when the parent spelling was swapped.
        # A link primitive may create the destination and then raise before
        # returning (or before this function records ``linked``).  Probe the
        # target whenever we have the staged identity; the bound quarantine
        # helper removes it only when it is still ours and preserves foreign
        # replacements.
        if staged_identity is not None:
            removed_target = _private_quarantine_owned(
                binding, target.name, staged_identity,
            )
            if not removed_target and temporary:
                # If the source temp was replaced just before link, the
                # operation-created target is a hardlink to that foreign temp.
                # Remove only the target generation sharing the temp inode;
                # preserve the foreign temp for the caller.
                try:
                    temp_actual, _, _ = _private_capture_bound(
                        binding, temporary,
                    )
                    target_actual, target_nlink, _ = _private_capture_bound(
                        binding, target.name,
                    )
                    if (target_nlink >= 2
                            and _private_same_identity(
                                target_actual, temp_actual)):
                        _private_quarantine_owned(
                            binding, target.name, temp_actual,
                        )
                except (diagnostic_candidate_core.CoreError, OSError,
                        TypeError, ValueError):
                    pass
        if temporary:
            cleanup_identity = staged_identity
            if cleanup_identity is not None:
                _private_quarantine_owned(
                    binding, temporary, cleanup_identity,
                    allow_partial=cleanup_identity[5] == "",
                )
        raise diagnostic_candidate_core.CoreError("private_output_publish_failed")
    finally:
        binding.close()


def write_json(path: str | Path, payload: dict) -> None:
    """Atomically write canonical human-readable JSON with a final newline."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{target.name}.", suffix=".tmp",
        dir=target.parent, delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            try:
                json.dump(payload, handle, ensure_ascii=False, indent=2,
                          allow_nan=False)
            except ValueError as exc:
                if "Out of range float values" in str(exc):
                    raise ValueError("nonfinite_json_value") from exc
                raise
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: str | Path):
    return _json_loads(Path(path).read_text(encoding="utf-8"))


def _result(ok: bool, reason_codes: list[str], **extra) -> dict:
    codes = list(dict.fromkeys(reason_codes))
    primary = codes[0] if codes else ("eligible" if ok else "unknown_failure")
    payload = {
        "ok": ok,
        "reason_code": primary,
        "reason": primary,
        "reason_codes": codes or [primary],
    }
    payload.update(extra)
    return payload


def _strict_output_payload(payload: dict) -> dict:
    """Return payload only when it can be emitted as standard JSON."""
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return _result(False, ["operation_failed"])
    return payload


def _validate_feature_map(value, *, allow_none: bool = False) -> dict[str, int] | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, dict):
        raise ValueError("features must be an object of positive integer counts")
    normalized: dict[str, int] = {}
    for raw_tag, raw_count in value.items():
        tag = str(raw_tag)
        if not tag or isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
            raise ValueError("feature tags must have positive integer counts")
        normalized[tag] = raw_count
    return dict(sorted(normalized.items()))


def _validate_manifest_document_id(value) -> str:
    if (not isinstance(value, str) or not value
            or MANIFEST_ID_RE.fullmatch(value) is None
            or value in {".", ".."}
            or ":" in value
            or "\x00" in value
            or PureWindowsPath(value).drive
            or PureWindowsPath(value).is_absolute()):
        raise ValueError("manifest_document_id_invalid")
    return value


def _capture_private_generation(path: str | Path, reason: str) -> dict:
    """Capture one no-follow, bounded, one-link file generation.

    Measurement records are private pathful artifacts, but their hashes must
    still describe a single stable generation rather than a path that can be
    replaced between ``stat`` and read.  The parent is held for the complete
    capture and the returned raw bytes are retained only in-process.
    """
    try:
        target = Path(path).expanduser().absolute()
        parent = target.parent
        resolved_parent = parent.resolve(strict=True)
        guard = diagnostic_candidate_core.capture_root_guard(parent, resolved_parent)
        diagnostic_candidate_core.check_root_guard(guard)
        binding = diagnostic_candidate_core.DirectoryBinding.open(
            parent, reason=reason,
        )
        try:
            diagnostic_candidate_core.check_root_guard(guard)
            identity, nlink, raw = _private_capture_bound(
                binding, target.name, parent_guard=guard,
            )
            diagnostic_candidate_core.check_root_guard(guard)
            if nlink != 1:
                raise diagnostic_candidate_core.CoreError(reason)
            return {
                "path": target,
                "identity": identity,
                "nlink": nlink,
                "raw": raw,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        finally:
            binding.close()
    except diagnostic_candidate_core.CoreError as exc:
        raise ValueError(reason) from exc
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        # Do not expose a private path or platform detail in measurement
        # records; callers map this stable token to their record reason.
        raise ValueError(reason) from exc


def _same_private_generation(first: dict, second: dict) -> bool:
    return (
        isinstance(first, dict) and isinstance(second, dict)
        and first.get("sha256") == second.get("sha256")
        and first.get("bytes") == second.get("bytes")
        and first.get("nlink") == second.get("nlink") == 1
        and _private_same_identity(first.get("identity"), second.get("identity"))
        and first.get("raw") == second.get("raw")
    )


def load_manifest(path: str | Path, *, require_ready: bool = True) -> dict:
    manifest_path = Path(path)
    payload = _read_json(manifest_path)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("corpus manifest must be a schema v1 object")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("corpus manifest documents must be an array")
    seen: set[str] = set()
    normalized = []
    for raw in documents:
        if not isinstance(raw, dict):
            raise ValueError("every corpus entry must be an object")
        try:
            entry_id = _validate_manifest_document_id(raw.get("id"))
        except ValueError:
            raise
        if entry_id in seen:
            raise ValueError("corpus entry ids must be unique non-empty strings")
        seen.add(entry_id)
        if raw.get("split") not in {"train", "holdout"}:
            raise ValueError(f"corpus entry {entry_id} has an invalid split")
        if not isinstance(raw.get("document"), str) or not raw["document"]:
            raise ValueError(f"corpus entry {entry_id} has no document path")
        if not isinstance(raw.get("generator"), dict):
            raise ValueError(f"corpus entry {entry_id} has no generator record")
        features = _validate_feature_map(raw.get("features"), allow_none=True)
        reference = raw.get("reference_pdf")
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ValueError(f"corpus entry {entry_id} has no reference PDF record")
        digest = reference.get("sha256")
        hancom = raw.get("hancom_version")
        ready = (
            features is not None
            and isinstance(digest, str) and SHA256_RE.fullmatch(digest.lower())
            and isinstance(hancom, str) and bool(hancom.strip())
            and raw.get("status", "ready") == "ready"
        )
        if require_ready and not ready:
            raise ValueError(f"corpus entry {entry_id} is awaiting its Windows reference")
        entry = dict(raw)
        entry["features"] = features
        if isinstance(digest, str):
            entry["reference_pdf"] = dict(reference, sha256=digest.lower())
        normalized.append(entry)
    return {"schema_version": SCHEMA_VERSION, "documents": normalized}


# Word-anchor comparison intentionally retains the existing research comparer's
# metric: same-page words that occur exactly once, candidate coordinates scaled
# to the reference page dimensions, Euclidean centre-point displacement.
def _words_by_page(pdf) -> list[list[tuple]]:
    return [page.get_text("words") for page in pdf]


def _unique_words(words: list[tuple]) -> dict[str, tuple]:
    counts = Counter(word[4] for word in words)
    return {word[4]: word for word in words if counts[word[4]] == 1}


def _centre(word: tuple, x_scale: float, y_scale: float) -> tuple[float, float]:
    return (
        ((word[0] + word[2]) / 2.0) * x_scale,
        ((word[1] + word[3]) / 2.0) * y_scale,
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _compare_word_anchors(reference, candidate, dpi: int) -> dict:
    ref_words = _words_by_page(reference)
    cand_words = _words_by_page(candidate)
    distances: list[float] = []
    for page_index in range(min(reference.page_count, candidate.page_count)):
        ref_page = reference[page_index]
        cand_page = candidate[page_index]
        ref_unique = _unique_words(ref_words[page_index])
        cand_unique = _unique_words(cand_words[page_index])
        x_scale = ref_page.rect.width / cand_page.rect.width
        y_scale = ref_page.rect.height / cand_page.rect.height
        for token in sorted(ref_unique.keys() & cand_unique.keys()):
            ref_xy = _centre(ref_unique[token], 1.0, 1.0)
            cand_xy = _centre(cand_unique[token], x_scale, y_scale)
            distances.append(math.hypot(cand_xy[0] - ref_xy[0], cand_xy[1] - ref_xy[1]))
    scale = dpi / 72.0
    maximum = max(distances, default=None)
    return {
        "matched_unique_words": len(distances),
        "dpi": dpi,
        "normalization": "candidate coordinates scaled to reference page dimensions",
        "max_displacement_px": round(maximum * scale, 2) if maximum is not None else None,
        "p95_displacement_px": round(_percentile(distances, 0.95) * scale, 2)
        if distances else None,
        "median_displacement_px": round(_percentile(distances, 0.50) * scale, 2)
        if distances else None,
    }


def _pixmap_samples(page, dpi: int) -> bytes:
    import fitz
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    return bytes(page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False).samples)


def _compare_rasters(reference, candidate, dpi: int) -> dict:
    changed = 0
    total = 0
    page_records = []
    maximum_pages = max(reference.page_count, candidate.page_count)
    for page_index in range(maximum_pages):
        ref_samples = _pixmap_samples(reference[page_index], dpi) \
            if page_index < reference.page_count else b""
        cand_samples = _pixmap_samples(candidate[page_index], dpi) \
            if page_index < candidate.page_count else b""
        overlap = min(len(ref_samples), len(cand_samples))
        page_changed = sum(
            left != right for left, right in zip(ref_samples[:overlap], cand_samples[:overlap])
        ) + abs(len(ref_samples) - len(cand_samples))
        page_total = max(len(ref_samples), len(cand_samples))
        changed += page_changed
        total += page_total
        page_records.append({
            "page": page_index + 1,
            "changed_channels": page_changed,
            "total_channels": page_total,
            "changed_channel_ratio": round(page_changed / page_total, 12)
            if page_total else 0.0,
        })
    return {
        "dpi": dpi,
        "changed_channels": changed,
        "total_channels": total,
        "changed_channel_ratio": round(changed / total, 12) if total else 0.0,
        "pages": page_records,
    }


def compare_pdf_metrics(reference_pdf: str | Path, candidate_pdf: str | Path, *, dpi: int = DEFAULT_DPI) -> dict:
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for renderer certification") from exc
    with fitz.open(reference_pdf) as reference, fitz.open(candidate_pdf) as candidate:
        page_count = {
            "reference": reference.page_count,
            "candidate": candidate.page_count,
            "exact": reference.page_count == candidate.page_count,
        }
        word_anchor = _compare_word_anchors(reference, candidate, dpi)
        raster = _compare_rasters(reference, candidate, dpi)
    return {"page_count": page_count, "word_anchor": word_anchor, "raster": raster}


def pdf_page_count(path: str | Path) -> int:
    """Reopen a runtime candidate and return a positive page count."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to verify a certified PDF") from exc
    with fitz.open(path) as document:
        if document.page_count <= 0:
            raise ValueError("certified PDF contains no pages")
        return document.page_count


def _probe_renderer_version(binary: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if completed.returncode != 0:
        return None
    blob = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return next((line.strip() for line in blob.splitlines() if line.strip()), None)


def resolve_renderer(
    renderer_id: str,
    *,
    renderer_binary: str | Path | None = None,
    renderer_argv: list[str] | None = None,
    renderer_version: str | None = None,
) -> dict:
    token = re.sub(r"[^A-Za-z0-9]", "_", renderer_id).upper()
    configured = renderer_binary or os.environ.get(f"RENDER_CERT_{token}_BIN")
    if renderer_id in {"rhwp", "rhwp_pdf"}:
        configured = configured or os.environ.get("RHWP_BIN") or shutil.which("rhwp")
    elif renderer_id in {"soffice", "soffice_local"}:
        configured = configured or os.environ.get("SOFFICE_BIN") or shutil.which("soffice")
    else:
        configured = configured or shutil.which(renderer_id)
    if not configured:
        raise ValueError(f"renderer binary not found for {renderer_id}")
    binary = Path(configured).expanduser().resolve()
    if not binary.is_file():
        raise ValueError(f"renderer binary is missing: {binary}")
    if renderer_argv is None:
        if renderer_id in {"rhwp", "rhwp_pdf"}:
            renderer_argv = [str(binary), "export-pdf", "{in}", "-o", "{out}"]
        elif renderer_id in {"soffice", "soffice_local"}:
            renderer_argv = [
                str(binary), "--headless", "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", "{outdir}", "{in}",
            ]
        else:
            renderer_argv = [str(binary), "{in}", "{out}"]
    if (not isinstance(renderer_argv, list) or not renderer_argv
            or not isinstance(renderer_argv[0], str)
            or not renderer_argv[0].strip()):
        raise ValueError("renderer_argv_invalid")
    try:
        argv_binary = Path(renderer_argv[0]).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("renderer_argv_binary_mismatch") from exc
    if argv_binary != binary:
        raise ValueError("renderer_argv_binary_mismatch")
    version = renderer_version or _probe_renderer_version(binary)
    if not version:
        raise ValueError(f"renderer version probe failed: {binary}")
    return {
        "id": renderer_id,
        "version": version,
        "binary_path": str(binary),
        "binary_sha256": _sha256_file(binary),
        "argv": [str(item) for item in renderer_argv],
    }


def _render_command(argv: list[str], document: Path, candidate: Path) -> list[str]:
    return [
        item.replace("{in}", str(document)).replace("{out}", str(candidate))
        .replace("{outdir}", str(candidate.parent))
        for item in argv
    ]


def measure_corpus(
    renderer_id: str,
    corpus: str | Path,
    *,
    work_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    renderer_binary: str | Path | None = None,
    renderer_argv: list[str] | None = None,
    renderer_version: str | None = None,
    render_callback: Callable[[dict, Path, Path], object] | None = None,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
) -> dict:
    manifest_path = Path(corpus).resolve()
    manifest = load_manifest(manifest_path, require_ready=True)
    renderer = resolve_renderer(
        renderer_id, renderer_binary=renderer_binary, renderer_argv=renderer_argv,
        renderer_version=renderer_version,
    )
    root = Path(work_dir).resolve() if work_dir else manifest_path.parent / ".render-cert-work" / renderer_id
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    hancom_versions = sorted({entry["hancom_version"] for entry in manifest["documents"]})
    if len(hancom_versions) != 1:
        raise ValueError("a certification manifest must pin exactly one Hancom version")

    for entry in manifest["documents"]:
        record = {
            "id": entry["id"], "split": entry["split"],
            "features": entry["features"], "ok": False, "reason_codes": [],
        }
        document = _absolute_lexical(manifest_path.parent / entry["document"])
        reference = _absolute_lexical(
            manifest_path.parent / entry["reference_pdf"]["path"],
        )
        candidate_dir = root / entry["id"]
        candidate = candidate_dir / "candidate.pdf"
        generated = candidate_dir / f"{document.stem}.pdf"
        try:
            candidate_dir.mkdir(parents=True, exist_ok=True)
            dir_info = candidate_dir.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (not stat.S_ISDIR(dir_info.st_mode) or stat.S_ISLNK(dir_info.st_mode)
                    or getattr(dir_info, "st_file_attributes", 0) & reparse):
                raise ValueError("renderer_output_path_invalid")
            # Every renderer run owns a fresh output generation.  A stale
            # candidate or alternate renderer filename is never overwritten.
            for stale in (candidate, generated):
                try:
                    stale.lstat()
                except FileNotFoundError:
                    continue
                raise ValueError("renderer_output_stale")

            document_before = _capture_private_generation(
                document, "document_missing",
            )
            reference_before = _capture_private_generation(
                reference, "reference_pdf_missing",
            )
            if reference_before["sha256"] != entry["reference_pdf"]["sha256"]:
                raise ValueError("reference_pdf_hash_mismatch")
            actual_features = feature_extract.extract_feature_counts(
                document_before["path"],
            )
            if actual_features != entry["features"]:
                raise ValueError("manifest_feature_mismatch")
            if render_callback is not None:
                callback_output = render_callback(
                    entry, document_before["path"], candidate,
                )
                if callback_output is not None:
                    callback_path = Path(callback_output)
                    if callback_path.resolve() != candidate.resolve():
                        shutil.copyfile(callback_path, candidate)
                completed_record = {"exit_code": 0, "command": ["mocked-render-callback"]}
            else:
                command = _render_command(renderer["argv"], document, candidate)
                completed = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout,
                )
                completed_record = {
                    "command": command,
                    "exit_code": completed.returncode,
                    "stdout": (completed.stdout or "")[-16000:],
                    "stderr": (completed.stderr or "")[-16000:],
                }
                if completed.returncode != 0:
                    raise ValueError("renderer_nonzero")
                if not candidate.is_file() and generated.is_file():
                    generated.replace(candidate)
            if generated != candidate:
                try:
                    generated.lstat()
                except FileNotFoundError:
                    pass
                else:
                    # Two renderer output generations are ambiguous; do not
                    # silently choose one while leaving the other unbound.
                    raise ValueError("renderer_output_ambiguous")
            document_after = _capture_private_generation(
                document, "document_changed",
            )
            if not _same_private_generation(document_before, document_after):
                raise ValueError("document_changed")
            reference_after = _capture_private_generation(
                reference, "reference_pdf_changed",
            )
            if not _same_private_generation(reference_before, reference_after):
                raise ValueError("reference_pdf_changed")
            candidate_after = _capture_private_generation(
                candidate, "renderer_output_missing",
            )
            record.update({
                "ok": True,
                "document": str(document_before["path"]),
                "document_sha256": document_before["sha256"],
                "reference_pdf": str(reference_before["path"]),
                "reference_pdf_sha256": reference_before["sha256"],
                "candidate_pdf": str(candidate_after["path"]),
                "candidate_pdf_sha256": candidate_after["sha256"],
                "renderer_run": completed_record,
                "metrics": compare_pdf_metrics(
                    reference_before["path"], candidate_after["path"], dpi=dpi,
                ),
            })
        except subprocess.TimeoutExpired:
            record["reason_codes"].append("renderer_timeout")
        except (OSError, RuntimeError, ValueError) as exc:
            code = str(exc)
            record["reason_codes"].append(code if re.fullmatch(r"[a-z0-9_]+", code) else "measurement_failed")
            record["error"] = str(exc)
        entries.append(record)

    return {
        "schema_version": SCHEMA_VERSION,
        "renderer": renderer,
        "corpus": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256_file(manifest_path),
            "hancom_version": hancom_versions[0],
        },
        "dpi": dpi,
        "documents": entries,
    }


def _validate_thresholds(thresholds) -> dict:
    required = {"page_count_exact", "word_anchor_px", "raster_changed_channel_ratio"}
    if not isinstance(thresholds, dict) or not required.issubset(thresholds):
        raise ValueError("thresholds require page_count_exact, word_anchor_px, and raster_changed_channel_ratio")
    if thresholds["page_count_exact"] is not True:
        raise ValueError("page_count_exact must be true")
    normalized = {"page_count_exact": True}
    for key in ("word_anchor_px", "raster_changed_channel_ratio"):
        value = thresholds[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"threshold {key} must be a non-negative number")
        try:
            finite = math.isfinite(value)
        except (OverflowError, TypeError):
            finite = False
        if not finite or value < 0:
            raise ValueError(f"threshold {key} must be a finite non-negative number")
        normalized[key] = float(value)
    if "min_matched_unique_words" in thresholds:
        value = thresholds["min_matched_unique_words"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("min_matched_unique_words must be a non-negative integer")
        normalized["min_matched_unique_words"] = value
    return normalized


def _document_passes(record: dict, thresholds: dict) -> bool:
    if record.get("ok") is False or record.get("reason_codes"):
        return False
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return False
    try:
        page_ok = metrics["page_count"]["exact"] is True
        anchor = metrics["word_anchor"]["max_displacement_px"]
        matched = metrics["word_anchor"]["matched_unique_words"]
        raster = metrics["raster"]["changed_channel_ratio"]
        return (
            page_ok
            and isinstance(anchor, (int, float)) and anchor <= thresholds["word_anchor_px"]
            and isinstance(raster, (int, float)) and raster <= thresholds["raster_changed_channel_ratio"]
            and matched >= thresholds.get("min_matched_unique_words", 0)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _split_stats(records: list[dict], thresholds: dict) -> dict:
    passed = [record for record in records if _document_passes(record, thresholds)]
    failed = [record for record in records if not _document_passes(record, thresholds)]
    anchors = [
        record["metrics"]["word_anchor"]["max_displacement_px"]
        for record in records if isinstance(record.get("metrics"), dict)
        and isinstance(record["metrics"].get("word_anchor", {}).get("max_displacement_px"), (int, float))
    ]
    rasters = [
        record["metrics"]["raster"]["changed_channel_ratio"]
        for record in records if isinstance(record.get("metrics"), dict)
        and isinstance(record["metrics"].get("raster", {}).get("changed_channel_ratio"), (int, float))
    ]
    return {
        "total": len(records), "passed": len(passed), "failed": len(failed),
        "document_ids": [record.get("id") for record in records],
        "failed_ids": [record.get("id") for record in failed],
        "max_word_anchor_px": max(anchors, default=None),
        "max_raster_changed_channel_ratio": max(rasters, default=None),
    }


def _certificate_digest(certificate: dict) -> str:
    body = dict(certificate)
    body.pop("certificate_sha256", None)
    body.pop(CERTIFICATE_HMAC_FIELD, None)
    return _sha256_payload(body)


def _measurement_records_for_manifest(
    manifest_documents: list[dict], records,
) -> list[dict]:
    if not isinstance(records, list):
        raise ValueError("certificate measurement records must be an array")
    manifest_by_id = {entry["id"]: entry for entry in manifest_documents}
    record_by_id: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("every measurement record must be an object")
        record_id = record.get("id")
        if not isinstance(record_id, str) or record_id in record_by_id:
            raise ValueError("measurement record ids must be unique strings")
        record_by_id[record_id] = record
    if set(record_by_id) != set(manifest_by_id):
        raise ValueError("measurement records must exactly cover the manifest")

    normalized = []
    for entry in manifest_documents:
        record = record_by_id[entry["id"]]
        if record.get("split") != entry["split"]:
            raise ValueError("measurement split does not match the manifest")
        if _validate_feature_map(record.get("features")) != entry["features"]:
            raise ValueError("measurement features do not match the manifest")
        normalized_record = dict(record)
        normalized_record.update({
            "id": entry["id"],
            "split": entry["split"],
            "features": entry["features"],
        })
        normalized.append(normalized_record)
    return normalized


def _validate_measurement_generations(
    manifest_path: Path, manifest_documents: list[dict], records: list[dict],
    measurement_base: Path,
) -> list[dict]:
    """Rebind every recorded source/reference/candidate before signing.

    The measurement JSON is an operator-private artifact, but it is still an
    input to a certificate claim.  A path or digest supplied by that artifact
    is accepted only when it names the manifest's document/reference and a
    fresh candidate generation whose current bounded snapshot matches exactly.
    """
    normalized = _measurement_records_for_manifest(manifest_documents, records)
    captured: list[tuple[dict, dict, dict, dict]] = []
    for entry, record in zip(manifest_documents, normalized):
        required = (
            "document", "document_sha256", "reference_pdf",
            "reference_pdf_sha256", "candidate_pdf", "candidate_pdf_sha256",
        )
        if any(key not in record for key in required):
            raise ValueError("measurement_generation_binding_missing")
        if any(
            not isinstance(record[key], str) or not record[key]
            for key in ("document", "reference_pdf", "candidate_pdf")
        ):
            raise ValueError("measurement_generation_binding_invalid")
        if any(
            not isinstance(record[key], str)
            or SHA256_RE.fullmatch(record[key].lower()) is None
            for key in (
                "document_sha256", "reference_pdf_sha256", "candidate_pdf_sha256",
            )
        ):
            raise ValueError("measurement_generation_hash_invalid")

        expected_document = _absolute_lexical(
            manifest_path.parent / entry["document"],
        )
        expected_reference = _absolute_lexical(
            manifest_path.parent / entry["reference_pdf"]["path"],
        )
        try:
            recorded_document = _absolute_lexical(
                Path(record["document"]) if Path(record["document"]).is_absolute()
                else measurement_base / record["document"],
            )
            recorded_reference = _absolute_lexical(
                Path(record["reference_pdf"])
                if Path(record["reference_pdf"]).is_absolute()
                else measurement_base / record["reference_pdf"],
            )
            recorded_candidate = _absolute_lexical(
                Path(record["candidate_pdf"])
                if Path(record["candidate_pdf"]).is_absolute()
                else measurement_base / record["candidate_pdf"],
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ValueError("measurement_generation_binding_invalid") from exc
        if recorded_document != expected_document:
            raise ValueError("measurement_document_path_mismatch")
        if recorded_reference != expected_reference:
            raise ValueError("measurement_reference_path_mismatch")
        if recorded_candidate in {recorded_document, recorded_reference}:
            raise ValueError("measurement_candidate_alias")

        document_snapshot = _capture_private_generation(
            recorded_document, "measurement_document_changed",
        )
        reference_snapshot = _capture_private_generation(
            recorded_reference, "measurement_reference_changed",
        )
        candidate_snapshot = _capture_private_generation(
            recorded_candidate, "measurement_candidate_changed",
        )
        if (_private_same_identity(candidate_snapshot["identity"], document_snapshot["identity"])
                or _private_same_identity(
                    candidate_snapshot["identity"], reference_snapshot["identity"],
                )):
            raise ValueError("measurement_candidate_alias")
        if document_snapshot["sha256"] != record["document_sha256"].lower():
            raise ValueError("measurement_document_changed")
        if reference_snapshot["sha256"] != record["reference_pdf_sha256"].lower():
            raise ValueError("measurement_reference_changed")
        if candidate_snapshot["sha256"] != record["candidate_pdf_sha256"].lower():
            raise ValueError("measurement_candidate_changed")
        if reference_snapshot["sha256"] != entry["reference_pdf"]["sha256"]:
            raise ValueError("reference_pdf_hash_mismatch")
        captured.append((record, document_snapshot, reference_snapshot,
                         candidate_snapshot))
    # Rebind every component once more after the complete record set has been
    # inspected.  A source/reference/candidate mutation between two first
    # captures must not be able to become a signed measurement by timing its
    # write in that gap.
    for record, document_before, reference_before, candidate_before in captured:
        document_after = _capture_private_generation(
            document_before["path"], "measurement_document_changed",
        )
        reference_after = _capture_private_generation(
            reference_before["path"], "measurement_reference_changed",
        )
        candidate_after = _capture_private_generation(
            candidate_before["path"], "measurement_candidate_changed",
        )
        if not _same_private_generation(document_before, document_after):
            raise ValueError("measurement_document_changed")
        if not _same_private_generation(reference_before, reference_after):
            raise ValueError("measurement_reference_changed")
        if not _same_private_generation(candidate_before, candidate_after):
            raise ValueError("measurement_candidate_changed")
    return normalized


def _derive_certificate_claims(
    manifest_documents: list[dict], records, thresholds: dict,
) -> dict:
    threshold_values = _validate_thresholds(thresholds)
    documents = _measurement_records_for_manifest(manifest_documents, records)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in documents:
        key = json.dumps(record["features"], sort_keys=True, separators=(",", ":"))
        grouped[key].append(record)
    failed_holdout_features = [
        record["features"] for record in documents
        if record["split"] == "holdout"
        and not _document_passes(record, threshold_values)
    ]
    envelope = []
    for key in sorted(grouped):
        group = grouped[key]
        train = [record for record in group if record["split"] == "train"]
        holdout = [record for record in group if record["split"] == "holdout"]
        group_features = _json_loads(key)
        covers_failed_holdout = any(
            all(
                tag in group_features and count <= group_features[tag]
                for tag, count in failed.items()
            )
            for failed in failed_holdout_features
        )
        if (train and holdout
                and not any(tag.startswith("unknown:") for tag in group_features)
                and not covers_failed_holdout
                and all(_document_passes(record, threshold_values) for record in group)):
            envelope.append({
                "features": group_features,
                "train_document_ids": [record["id"] for record in train],
                "holdout_document_ids": [record["id"] for record in holdout],
            })

    train_records = [record for record in documents if record["split"] == "train"]
    holdout_records = [record for record in documents if record["split"] == "holdout"]
    if not holdout_records:
        raise ValueError("certification requires at least one holdout document")
    return {
        "records": documents,
        "envelope": envelope,
        "train_stats": _split_stats(train_records, threshold_values),
        "holdout_stats": _split_stats(holdout_records, threshold_values),
    }


def issue_certificate(
    measurements: dict | str | Path,
    thresholds: dict,
    *,
    issued_at: str | None = None,
) -> dict:
    measurement_path = (
        Path(measurements).resolve() if isinstance(measurements, (str, Path)) else None
    )
    measured = _read_json(measurement_path) if measurement_path else measurements
    if not isinstance(measured, dict) or measured.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("measurements must be a schema v1 object")
    renderer = measured.get("renderer")
    corpus = measured.get("corpus")
    documents = measured.get("documents")
    if not isinstance(renderer, dict) or not isinstance(corpus, dict) or not isinstance(documents, list):
        raise ValueError("measurements are missing renderer, corpus, or documents")
    threshold_values = _validate_thresholds(thresholds)
    manifest_raw = corpus.get("manifest_path")
    manifest_hash = corpus.get("manifest_sha256")
    if not isinstance(manifest_raw, str) or not manifest_raw:
        raise ValueError("measurements do not contain a corpus manifest path")
    manifest_base = measurement_path.parent if measurement_path else Path.cwd()
    manifest_path = _resolve_recorded_path(manifest_raw, manifest_base)
    manifest_snapshot = _capture_private_generation(
        manifest_path, "manifest_changed",
    )
    if (not isinstance(manifest_hash, str)
            or manifest_snapshot["sha256"] != manifest_hash.lower()):
        raise ValueError("measurement corpus manifest hash does not verify")
    manifest = load_manifest(manifest_path, require_ready=True)
    manifest_final = _capture_private_generation(
        manifest_path, "manifest_changed",
    )
    if not _same_private_generation(manifest_snapshot, manifest_final):
        raise ValueError("manifest_changed")
    bound_documents = _validate_measurement_generations(
        manifest_path, manifest["documents"], documents, manifest_base,
    )
    claims = _derive_certificate_claims(
        manifest["documents"], bound_documents, threshold_values,
    )
    measurement_records = claims["records"]
    hancom_versions = {entry["hancom_version"] for entry in manifest["documents"]}
    if hancom_versions != {corpus.get("hancom_version")}:
        raise ValueError("measurement Hancom version does not match the manifest")

    certificate = {
        "schema_version": SCHEMA_VERSION,
        "renderer_id": renderer.get("id"),
        "renderer_version": renderer.get("version"),
        "renderer_binary_path": renderer.get("binary_path"),
        "renderer_binary_hash": renderer.get("binary_sha256"),
        "renderer_argv": renderer.get("argv"),
        "hancom_version": corpus.get("hancom_version"),
        "corpus_manifest_path": corpus.get("manifest_path"),
        "corpus_manifest_hash": corpus.get("manifest_sha256"),
        "measurement_records": measurement_records,
        "measurement_hash": _sha256_payload(measurement_records),
        "thresholds": threshold_values,
        "envelope": claims["envelope"],
        "train_stats": claims["train_stats"],
        "holdout_stats": claims["holdout_stats"],
        "issued_at": issued_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    required_strings = (
        "renderer_id", "renderer_version", "renderer_binary_path", "renderer_binary_hash",
        "hancom_version", "corpus_manifest_path", "corpus_manifest_hash",
    )
    if any(not isinstance(certificate[key], str) or not certificate[key] for key in required_strings):
        raise ValueError("measurements do not contain complete renderer/corpus provenance")
    if not isinstance(certificate["renderer_argv"], list) or not certificate["renderer_argv"]:
        raise ValueError("measurements do not contain a renderer argv template")
    certificate["certificate_sha256"] = _certificate_digest(certificate)
    key = receipt_sign.load_operator_key(create=True)
    certificate[CERTIFICATE_HMAC_FIELD] = receipt_sign.hmac_sha256(
        certificate, key, omit_fields=(CERTIFICATE_HMAC_FIELD,),
    )
    return certificate


def _resolve_recorded_path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _verify_certificate_rich(
    certificate: dict | str | Path,
    *,
    renderer_binary: str | Path | None = None,
    renderer_version: str | None = None,
) -> dict:
    source_path = Path(certificate).resolve() if isinstance(certificate, (str, Path)) else None
    base = source_path.parent if source_path else Path.cwd()
    try:
        cert = _read_json(source_path) if source_path else certificate
    except FileNotFoundError:
        return _result(False, ["certificate_missing"])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _result(False, ["certificate_invalid_json"])
    if not isinstance(cert, dict):
        return _result(False, ["certificate_schema_invalid"])
    expected_self_hash = cert.get("certificate_sha256")
    if not isinstance(expected_self_hash, str) or _certificate_digest(cert) != expected_self_hash:
        return _result(False, ["certificate_hash_mismatch"])
    expected_hmac = cert.get(CERTIFICATE_HMAC_FIELD)
    if expected_hmac is None:
        return _result(False, ["certificate_hmac_missing"])
    if not isinstance(expected_hmac, str) or not SHA256_RE.fullmatch(expected_hmac):
        return _result(False, ["certificate_hmac_mismatch"])
    try:
        key = receipt_sign.load_operator_key(create=False)
    except receipt_sign.ReceiptKeyMissing:
        return _result(False, ["certificate_key_missing"])
    except receipt_sign.ReceiptKeyInvalid:
        return _result(False, ["certificate_key_invalid"])
    if not receipt_sign.verify_hmac_sha256(
        cert, key, expected_hmac, omit_fields=(CERTIFICATE_HMAC_FIELD,),
    ):
        return _result(False, ["certificate_hmac_mismatch"])

    required = (
        "renderer_id", "renderer_version", "renderer_binary_path", "renderer_binary_hash",
        "renderer_argv", "hancom_version", "corpus_manifest_path",
        "corpus_manifest_hash", "measurement_records", "measurement_hash",
        "thresholds", "envelope", "train_stats", "holdout_stats", "issued_at",
    )
    if cert.get("schema_version") != SCHEMA_VERSION or any(key not in cert for key in required):
        return _result(False, ["certificate_schema_invalid"])
    try:
        if _validate_thresholds(cert["thresholds"]) != cert["thresholds"]:
            raise ValueError
        if not isinstance(cert["envelope"], list):
            raise ValueError
        for entry in cert["envelope"]:
            features = entry.get("features") if isinstance(entry, dict) else None
            _validate_feature_map(features)
            if any(tag.startswith("unknown:") for tag in features):
                raise ValueError
        if not isinstance(cert["renderer_argv"], list) or not cert["renderer_argv"]:
            raise ValueError
        if not SHA256_RE.fullmatch(str(cert["renderer_binary_hash"])):
            raise ValueError
        if not SHA256_RE.fullmatch(str(cert["corpus_manifest_hash"])):
            raise ValueError
        if not SHA256_RE.fullmatch(str(cert["measurement_hash"])):
            raise ValueError
        if not isinstance(cert["measurement_records"], list):
            raise ValueError
        if not isinstance(cert["train_stats"], dict) or not isinstance(cert["holdout_stats"], dict):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return _result(False, ["certificate_schema_invalid"])

    try:
        manifest_path = _resolve_recorded_path(cert["corpus_manifest_path"], base)
    except (OSError, TypeError, ValueError):
        return _result(False, ["manifest_missing"])
    if not manifest_path.is_file():
        return _result(False, ["manifest_missing"])
    if _sha256_file(manifest_path) != cert["corpus_manifest_hash"]:
        return _result(False, ["manifest_hash_mismatch"])
    try:
        manifest = load_manifest(manifest_path, require_ready=True)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _result(False, ["manifest_invalid"])
    hancom_versions = {entry["hancom_version"] for entry in manifest["documents"]}
    if hancom_versions != {cert["hancom_version"]}:
        return _result(False, ["hancom_version_mismatch"])
    if _sha256_payload(cert["measurement_records"]) != cert["measurement_hash"]:
        return _result(False, ["measurement_hash_mismatch"])
    try:
        claims = _derive_certificate_claims(
            manifest["documents"], cert["measurement_records"], cert["thresholds"],
        )
    except (AttributeError, TypeError, ValueError):
        return _result(False, ["measurement_records_invalid"])
    if cert["envelope"] != claims["envelope"]:
        return _result(False, ["certificate_envelope_mismatch"])
    if (cert["train_stats"] != claims["train_stats"]
            or cert["holdout_stats"] != claims["holdout_stats"]):
        return _result(False, ["certificate_stats_mismatch"])

    try:
        binary = Path(renderer_binary).expanduser().resolve() if renderer_binary is not None \
            else _resolve_recorded_path(cert["renderer_binary_path"], base)
    except (OSError, TypeError, ValueError):
        return _result(False, ["renderer_binary_missing"])
    if not binary.is_file():
        return _result(False, ["renderer_binary_missing"])
    if _sha256_file(binary) != cert["renderer_binary_hash"]:
        return _result(False, ["renderer_binary_hash_mismatch"])
    live_version = renderer_version if renderer_version is not None else _probe_renderer_version(binary)
    if live_version is None:
        return _result(False, ["renderer_probe_failed"])
    if str(live_version).strip() != str(cert["renderer_version"]).strip():
        return _result(False, ["renderer_version_mismatch"])
    return _result(
        True, ["certificate_valid"], certificate=cert,
        certificate_path=str(source_path) if source_path else None,
        manifest_path=str(manifest_path), renderer_binary=str(binary),
        renderer_version=str(live_version).strip(),
    )


def verify_certificate(
    certificate: dict | str | Path,
    *,
    renderer_binary: str | Path | None = None,
    renderer_version: str | None = None,
) -> dict:
    """Return the closed public certificate-verification projection.

    The full certificate/manifest/binary evidence remains available only to
    the private helper used by the document eligibility check.  Public callers
    receive stable status and reason fields without paths, argv, certificate
    members, or renderer identifiers.
    """
    try:
        rich = _verify_certificate_rich(
            certificate, renderer_binary=renderer_binary, renderer_version=renderer_version,
        )
    except Exception:
        return _result(False, ["certificate_invalid"])
    return _result(
        rich.get("ok") is True,
        list(rich.get("reason_codes") or [rich.get("reason_code", "unknown_failure")]),
    )


def _inside_envelope(features: dict[str, int], envelope: list[dict]) -> bool:
    for entry in envelope:
        maximum = entry.get("features", {})
        if all(tag in maximum and count <= maximum[tag] for tag, count in features.items()):
            return True
    return False


def check_document(
    document: str | Path,
    certificate: dict | str | Path,
    *,
    renderer_binary: str | Path | None = None,
    renderer_version: str | None = None,
) -> dict:
    try:
        verification = _verify_certificate_rich(
            certificate, renderer_binary=renderer_binary, renderer_version=renderer_version
        )
    except Exception:
        return {**_result(False, ["certificate_invalid"]), "eligible": False}
    if verification.get("ok") is not True:
        return {**_result(False, verification.get("reason_codes", [
            verification.get("reason_code", "certificate_invalid")
        ])), "eligible": False}
    try:
        features = feature_extract.extract_feature_counts(document)
    except Exception:
        return {**_result(False, ["document_unreadable"]), "eligible": False}
    unknown = sorted(tag for tag in features if tag.startswith("unknown:"))
    if unknown:
        return {**_result(False, ["unknown_feature"]), "eligible": False}
    certificate_payload = verification["certificate"]
    if not _inside_envelope(features, certificate_payload["envelope"]):
        return {**_result(False, ["envelope_mismatch"]), "eligible": False}
    return {**_result(True, ["eligible"]), "eligible": True}


def _threshold_args(args) -> dict:
    if args.thresholds:
        candidate = Path(args.thresholds)
        if candidate.is_file():
            return _read_json(candidate)
        return _json_loads(args.thresholds)
    if args.word_anchor_px is None or args.raster_changed_channel_ratio is None:
        raise ValueError("certify requires --thresholds or both metric threshold options")
    return {
        "page_count_exact": True,
        "word_anchor_px": args.word_anchor_px,
        "raster_changed_channel_ratio": args.raster_changed_channel_ratio,
        **({"min_matched_unique_words": args.min_matched_unique_words}
           if args.min_matched_unique_words is not None else {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    measure_parser = subparsers.add_parser("measure")
    measure_parser.add_argument("--renderer", required=True)
    measure_parser.add_argument("--corpus", required=True)
    measure_parser.add_argument("--out")
    measure_parser.add_argument("--work-dir")
    measure_parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    measure_parser.add_argument("--renderer-binary")
    measure_parser.add_argument("--renderer-version")
    measure_parser.add_argument("--renderer-command",
                                help="shell-like argv template using {in}, {out}, {outdir}")
    measure_parser.add_argument("--timeout", type=float, default=DEFAULT_RENDER_TIMEOUT)

    certify_parser = subparsers.add_parser("certify")
    certify_parser.add_argument("measurements_pos", nargs="?")
    certify_parser.add_argument("--measurements")
    certify_parser.add_argument("--thresholds", help="JSON file or inline JSON object")
    certify_parser.add_argument("--word-anchor-px", type=float)
    certify_parser.add_argument("--raster-changed-channel-ratio", type=float)
    certify_parser.add_argument("--min-matched-unique-words", type=int)
    certify_parser.add_argument("--issued-at")
    certify_parser.add_argument("--out")

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("document")
    check_parser.add_argument("certificate")
    check_parser.add_argument("--renderer-binary")
    check_parser.add_argument("--renderer-version")
    check_parser.add_argument("--out")

    args = parser.parse_args(argv)
    try:
        if args.command == "measure":
            renderer_argv = shlex.split(args.renderer_command) if args.renderer_command else None
            payload = measure_corpus(
                args.renderer, args.corpus, work_dir=args.work_dir, dpi=args.dpi,
                renderer_binary=args.renderer_binary, renderer_argv=renderer_argv,
                renderer_version=args.renderer_version,
                timeout=args.timeout,
            )
            code = 0 if all(record.get("ok") for record in payload["documents"]) else 3
        elif args.command == "certify":
            measurement_path = args.measurements or args.measurements_pos
            if not measurement_path:
                raise ValueError("certify requires a measurements JSON path")
            payload = issue_certificate(
                measurement_path, _threshold_args(args), issued_at=args.issued_at
            )
            code = 0
        else:
            payload = check_document(
                args.document, args.certificate,
                renderer_binary=args.renderer_binary,
                renderer_version=args.renderer_version,
            )
            code = 0 if payload["eligible"] else 3
    except Exception:
        payload = _result(False, ["operation_failed"])
        code = 3
    safe_payload = _strict_output_payload(payload)
    if safe_payload is not payload:
        payload = safe_payload
        code = 3
    if getattr(args, "out", None):
        try:
            if args.command in {"measure", "certify"}:
                _write_private_artifact_json(args.out, payload)
            else:
                write_json(args.out, payload)
        except (OSError, TypeError, ValueError):
            payload = _result(False, ["operation_failed"])
            code = 3
        except diagnostic_candidate_core.CoreError:
            payload = _result(False, ["operation_failed"])
            code = 3
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, TypeError, UnicodeError, ValueError):
        return 3
    return code


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
