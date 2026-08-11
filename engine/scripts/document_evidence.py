#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hash-bound, privacy-safe document execution evidence.

This module deliberately keeps capability discovery separate from proof.  A
renderer being advertised by :mod:`render_probe` is only a capability fact;
proof is derived from a terminal execution state and the hashes of the bytes
that execution consumed and produced.  The module is pure stdlib so it can be
used by both the XML and Windows/Hancom engine paths.

The receipt is local integrity evidence, not hostile-author attestation.  The
stronger HMAC/certificate semantics remain owned by ``render_cert``.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, Callable


RECEIPT_SCHEMA = "rigorloom/document-evidence/v1"
RECEIPT_REL = Path("output/proof/backend/receipt.json")

BACKEND_IDS = frozenset({
    "xml_only",
    "native_hancom_windows",
    "oss_preview_libreoffice",
    "oss_preview_rhwp",
    "certified_renderer",
    "none",
})
EVIDENCE_CLASSES = frozenset({
    "structural_only",
    "diagnostic_render",
    "advisory_render",
    "certified_render",
    "native_render",
})
ARTIFACT_ROLES = frozenset({
    "source_form",
    "assembled_hwpx",
    "rendered_pdf",
    "diagnostic_svg",
})
_BACKEND_EVIDENCE = {
    "xml_only": "structural_only",
    "native_hancom_windows": "native_render",
    "oss_preview_libreoffice": "advisory_render",
    "oss_preview_rhwp": "diagnostic_render",
    "certified_renderer": "certified_render",
    "none": "structural_only",
}
_RENDER_EVIDENCE = frozenset({
    "native_render", "advisory_render", "diagnostic_render",
    "certified_render",
})
_RENDER_OUTPUT_ROLE = {
    "native_render": ("rendered_pdf", ".pdf"),
    "advisory_render": ("rendered_pdf", ".pdf"),
    "certified_render": ("rendered_pdf", ".pdf"),
    "diagnostic_render": ("diagnostic_svg", ".svg"),
}
QUALITY_SCHEMA = "rigorloom/render-quality/v1"
QUALITY_STATES = frozenset({"passed", "failed", "unknown", "not_applicable"})
QUALITY_REASON_CODES = frozenset({
    "passed", "source_ascii_only", "missing_hangul_glyphs",
    "missing_hangul_text",
    "source_visibility_ambiguous",
    "semantic_text_ambiguous",
    "font_capacity_insufficient", "ambiguous_font_mapping",
    "font_mapping_missing", "font_buffer_unavailable", "nonembedded_font",
    "type3_font", "glyph_identity_collapse", "glyph_geometry_missing",
    "unsupported_charproc_state", "unsupported_graphics_state",
    "malformed_pdf_content", "pdf_content_unbounded", "source_unreadable",
    "pdf_unreadable", "pdf_no_pages", "pdf_no_extractable_text",
    "checker_unavailable", "layout_hard_failed", "visual_quality_gate_pending",
})
_QUALITY_REASONS_BY_STATE = {
    "passed": frozenset({"passed"}),
    "failed": frozenset({
        "missing_hangul_glyphs", "missing_hangul_text",
        "font_capacity_insufficient", "glyph_identity_collapse",
        "glyph_geometry_missing",
        "layout_hard_failed", "visual_quality_gate_pending",
    }),
    "unknown": frozenset({
        "ambiguous_font_mapping", "font_mapping_missing",
        "font_buffer_unavailable", "nonembedded_font", "type3_font",
        "unsupported_charproc_state", "unsupported_graphics_state",
        "malformed_pdf_content", "pdf_content_unbounded",
        "source_visibility_ambiguous",
        "semantic_text_ambiguous",
        "source_unreadable", "pdf_unreadable", "pdf_no_pages",
        "pdf_no_extractable_text", "checker_unavailable",
    }),
    "not_applicable": frozenset({"source_ascii_only"}),
}
_QUALITY_REQUIRED = frozenset({
    "schema", "checker", "version", "artifact_sha256", "artifact_bytes",
    "state", "reason_code", "source_hangul_count", "pdf_hangul_count",
    "page_count", "mapped_font_xrefs", "checked_font_xrefs",
    "max_unique_hangul_per_xref", "min_glyph_capacity",
})
_QUALITY_ALLOWED = _QUALITY_REQUIRED
# One release switch owns advisory proof promotion for every entrypoint. Keep
# it false until independent visual/layout and real LibreOffice evidence are
# shipped; callers must not maintain local copies.
ADVISORY_PROOF_RELEASE_ENABLED = False
# Certified renderer execution/promotion is deliberately quarantined.  The
# certificate tooling remains diagnostic-only until a separately reviewed
# runtime/root/receipt contract is released; no forged or legacy certified
# verdict may become a submission grade in the meantime.
CERTIFIED_PROOF_RELEASE_ENABLED = False
_CAPABILITY_KEYS = frozenset({
    "hancom_com", "h2orestart", "soffice", "rhwp", "certified_renderer",
})
TERMINAL_STATES = frozenset({
    "succeeded",
    "failed",
    "refused",
    "not_run",
    "unknown",
    "hash_mismatch",
})
PROOF_GRADES = frozenset({
    "none",
    "experimental-rhwp",
    "advisory",
    "certified",
    "hancom",
})

_GRADE_BY_EVIDENCE = {
    "structural_only": "none",
    "diagnostic_render": "experimental-rhwp",
    "advisory_render": "advisory",
    "certified_render": "certified",
    "native_render": "hancom",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_UTC_SECONDS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TOP_LEVEL_REQUIRED = frozenset({
    "schema", "created_utc", "execution", "evidence_class",
    "proof_grade", "proof_unavailable", "receipt_sha256",
})
_TOP_LEVEL_OPTIONAL = frozenset({"reproducible_here", "capability_facts", "quality"})
_TOP_LEVEL_ALLOWED = _TOP_LEVEL_REQUIRED | _TOP_LEVEL_OPTIONAL
_EXECUTION_REQUIRED = frozenset({"backend", "state", "input", "output"})
_EXECUTION_OPTIONAL = frozenset({
    "exit_code", "reason_code", "renderer_id", "renderer_version",
})
_EXECUTION_ALLOWED = _EXECUTION_REQUIRED | _EXECUTION_OPTIONAL
_ARTIFACT_REQUIRED = frozenset({"role", "path"})
_ARTIFACT_OPTIONAL = frozenset({"sha256", "bytes"})
_ARTIFACT_ALLOWED = _ARTIFACT_REQUIRED | _ARTIFACT_OPTIONAL
_FORBIDDEN_KEYS = frozenset({
    "argv", "command", "stdout", "stderr", "environment", "env",
    "hostname", "host", "document_text", "text", "user_path",
})
_FORBIDDEN_ABS = re.compile(
    r"(?:^[A-Za-z]:[\\/]|^[\\/]{1,2}|^\\\\|^file://)", re.IGNORECASE)
_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _is_reparse(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


def _node_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return a local-only identity; it is never serialized in receipts."""
    return (
        int(getattr(info, "st_dev", 0)), int(getattr(info, "st_ino", 0)),
        int(getattr(info, "st_size", 0)), int(getattr(info, "st_mtime_ns", 0)),
        int(getattr(info, "st_ctime_ns", 0)), int(getattr(info, "st_nlink", 0)),
    )


def _same_identity(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    return tuple(left) == tuple(right)


def _same_filesystem_node(left: Path, right: Path) -> bool:
    """Compare two existing path spellings by filesystem identity."""
    try:
        return os.path.samefile(str(left), str(right))
    except (OSError, RuntimeError, ValueError, TypeError):
        return False


def _same_bound_path(left: Path, right: Path) -> bool:
    """Accept spelling aliases only when both names bind the same live node."""
    left_text = os.path.normcase(os.path.normpath(str(left)))
    right_text = os.path.normcase(os.path.normpath(str(right)))
    return left_text == right_text or _same_filesystem_node(left, right)


def _opened_real_path(fd: int) -> Path | None:
    """Return the kernel-resolved path for an already opened descriptor.

    This is a second custody binding for the interior-parent race: a parent
    component can be swapped to a symlink after the lexical lstat walk and
    restored before the next capture.  The descriptor's final path still
    points outside the intended tree and must be refused.
    """
    try:
        if os.name == "nt":
            import ctypes
            import msvcrt

            handle = msvcrt.get_osfhandle(fd)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            fn = kernel32.GetFinalPathNameByHandleW
            fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                           ctypes.c_uint32, ctypes.c_uint32]
            fn.restype = ctypes.c_uint32
            size = 512
            while size <= 32768:
                buf = ctypes.create_unicode_buffer(size)
                used = fn(handle, buf, size, 0)
                if used == 0:
                    return None
                if used < size - 1:
                    value = buf.value
                    if value.startswith("\\\\?\\UNC\\"):
                        # GetFinalPathNameByHandleW uses an extended UNC
                        # spelling; compare it with the ordinary UNC path
                        # produced by ``abspath``.
                        value = "\\\\" + value[8:]
                    elif value.startswith("\\\\?\\"):
                        value = value[4:]
                    return Path(value)
                size *= 2
            return None
        proc_link = Path(f"/proc/self/fd/{fd}")
        if proc_link.exists():
            return proc_link.resolve(strict=True)
        if sys.platform == "darwin":
            import fcntl

            getpath = getattr(fcntl, "F_GETPATH", 50)
            raw = fcntl.fcntl(fd, getpath, b"\0" * 1024)
            if isinstance(raw, bytes):
                value = raw.split(b"\0", 1)[0]
                if value:
                    return Path(value.decode(sys.getfilesystemencoding(),
                                             errors="surrogateescape"))
    except (OSError, RuntimeError, ValueError, TypeError):
        return None
    return None


def _open_regular(path: Path, reason: str) -> tuple[int, os.stat_result]:
    """Open one regular, one-link file and bind its path to the opened inode."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or _is_reparse(before) or getattr(before, "st_nlink", 1) != 1):
            raise EvidenceError({
                "code": "artifact_not_single_link",
                "path": path.as_posix(),
                "message": reason,
            })
        if before.st_size < 0 or before.st_size > _MAX_ARTIFACT_BYTES:
            raise EvidenceError({
                "code": "artifact_too_large",
                "path": path.as_posix(),
                "message": "artifact exceeds the bounded receipt capture",
            })
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags)
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or _is_reparse(opened)
                or getattr(opened, "st_nlink", 1) != 1
                or _node_identity(opened)[:2] != _node_identity(before)[:2]
                or opened.st_size != before.st_size):
            os.close(fd)
            raise EvidenceError({
                "code": "artifact_replaced",
                "path": path.as_posix(),
                "message": "artifact changed while it was opened",
            })
        opened_real = _opened_real_path(fd)
        if opened_real is None:
            os.close(fd)
            raise EvidenceError({
                "code": "artifact_parent_binding_unavailable",
                "path": path.as_posix(),
                "message": "opened artifact path could not be custody-bound",
            })
        try:
            # ``resolve()`` here would follow a swapped parent and make the
            # attacker's outside target look expected.  Compare the handle
            # against the lexical absolute path instead; all components were
            # already required to be non-reparse dirs.
            expected_real = Path(os.path.abspath(str(path)))
            actual_value = str(opened_real)
            expected_value = str(expected_real)
            for value_name, value in (("actual", actual_value),
                                      ("expected", expected_value)):
                if value.startswith("\\\\?\\UNC\\"):
                    value = "\\\\" + value[8:]
                elif value.startswith("\\\\?\\"):
                    value = value[4:]
                if value_name == "actual":
                    actual_value = value
                else:
                    expected_value = value
            if not _same_bound_path(Path(actual_value), Path(expected_value)):
                os.close(fd)
                raise EvidenceError({
                    "code": "artifact_parent_changed",
                    "path": path.as_posix(),
                    "message": "artifact parent changed during open",
                })
        except EvidenceError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            os.close(fd)
            raise EvidenceError({
                "code": "artifact_parent_changed",
                "path": path.as_posix(),
                "message": "artifact parent could not be rebound",
            }) from exc
        return fd, opened
    except EvidenceError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise EvidenceError({
            "code": "artifact_unreadable",
            "path": path.as_posix(),
            "message": str(exc),
        }) from exc


def _read_regular_once(
    path: Path, *, max_bytes: int = _MAX_RECEIPT_BYTES,
) -> tuple[bytes, tuple[int, ...]]:
    fd, opened = _open_regular(path, "artifact must be a regular one-link file")
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise EvidenceError({
                    "code": "artifact_too_large",
                    "path": path.as_posix(),
                    "message": "artifact exceeds the bounded receipt capture",
                })
            chunks.append(chunk)
        after = os.fstat(fd)
        if (_node_identity(after)[:2] != _node_identity(opened)[:2]
                or after.st_size != total
                or getattr(after, "st_nlink", 1) != 1
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns):
            raise EvidenceError({
                "code": "artifact_changed_during_read",
                "path": path.as_posix(),
                "message": "artifact changed during one-link capture",
            })
        return b"".join(chunks), _node_identity(after)
    finally:
        os.close(fd)


def _capture_identity(path: Path) -> tuple[int, ...]:
    """Capture identity through a no-follow open, without serializing it."""
    fd, opened = _open_regular(path, "artifact must be a regular one-link file")
    try:
        after = os.fstat(fd)
        if not _same_identity(_node_identity(opened), _node_identity(after)):
            raise EvidenceError({
                "code": "artifact_changed_during_capture",
                "path": path.as_posix(),
                "message": "artifact identity changed during capture",
            })
        return _node_identity(after)
    finally:
        os.close(fd)


class EvidenceError(ValueError):
    """Receipt validation failure with machine-readable ``errors`` rows."""

    def __init__(self, errors: list[dict[str, Any]] | dict[str, Any] | str):
        if isinstance(errors, str):
            errors = [{"code": "invalid_receipt", "path": "receipt",
                       "message": errors}]
        elif isinstance(errors, dict):
            errors = [errors]
        self.errors = list(errors)
        super().__init__(self._format())

    def _format(self) -> str:
        return "; ".join(
            f"{item.get('code', 'invalid_receipt')}: "
            f"{item.get('message', '')}" for item in self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "errors": self.errors}


def _now_utc() -> str:
    return (_datetime.datetime.now(_datetime.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"))


def _canonical_bytes(payload: dict[str, Any], *, omit_hash: bool = False) -> bytes:
    value = dict(payload)
    if omit_hash:
        value.pop("receipt_sha256", None)
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n").encode("utf-8")


def _sha256_file(path: Path) -> tuple[str, int]:
    digest, size, _identity = _capture_file(path)
    return digest, size


def _capture_file(path: Path) -> tuple[str, int, tuple[int, ...]]:
    """Hash and bind one file from the same opened descriptor."""
    fd, opened = _open_regular(path, "artifact must be a regular one-link file")
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            chunk = os.read(fd, min(1024 * 1024, _MAX_ARTIFACT_BYTES - size + 1))
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if size > _MAX_ARTIFACT_BYTES:
                raise EvidenceError({
                    "code": "artifact_too_large",
                    "path": path.as_posix(),
                    "message": "artifact exceeds the bounded receipt capture",
                })
        after = os.fstat(fd)
        if (_node_identity(after)[:2] != _node_identity(opened)[:2]
                or after.st_size != size
                or getattr(after, "st_nlink", 1) != 1
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns):
            raise EvidenceError({
                "code": "artifact_changed_during_read",
                "path": path.as_posix(),
                "message": "artifact changed during one-link hash capture",
            })
        return digest.hexdigest(), size, _node_identity(after)
    finally:
        os.close(fd)


def _normalise_workspace(workspace: Path | str) -> Path:
    try:
        supplied = Path(workspace).expanduser()
        info = supplied.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) \
                or _is_reparse(info):
            raise EvidenceError({
                "code": "workspace_root_invalid",
                "path": "workspace",
                "message": "workspace root must be a non-reparse directory",
            })
        return supplied.resolve(strict=True)
    except EvidenceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvidenceError({"code": "workspace_unreadable", "path": "workspace",
                             "message": str(exc)}) from exc


def _workspace_guard(workspace: Path) -> tuple[tuple[Path, tuple[int, ...]], ...]:
    rows: list[tuple[Path, tuple[int, ...]]] = []
    probe = workspace.absolute()
    while True:
        try:
            info = probe.lstat()
        except OSError as exc:
            raise EvidenceError({
                "code": "workspace_root_changed",
                "path": "workspace",
                "message": str(exc),
            }) from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise EvidenceError({
                "code": "workspace_root_changed",
                "path": "workspace",
                "message": "workspace root or ancestor became a reparse point",
            })
        rows.append((probe, _node_identity(info)[:2]))
        if probe == probe.parent:
            break
        probe = probe.parent
    return tuple(rows)


def _check_workspace_guard(
    guard: tuple[tuple[Path, tuple[int, ...]], ...],
) -> None:
    try:
        for path, expected in guard:
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or _is_reparse(info)
                    or _node_identity(info)[:2] != expected):
                raise EvidenceError({
                    "code": "workspace_root_changed",
                    "path": "workspace",
                    "message": "workspace root or ancestor changed during capture",
                })
    except EvidenceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvidenceError({
            "code": "workspace_root_changed",
            "path": "workspace",
            "message": str(exc),
        }) from exc


def _safe_relative_path(workspace: Path, value: Path | str, *, require_exists: bool = False) -> str:
    """Return a workspace-relative POSIX path, rejecting escapes/symlinks."""
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            # Preserve the caller's lexical components (notably an interior
            # symlink) for the custody check below.  Only the containment test
            # later resolves the target.
            candidate = candidate.absolute().relative_to(workspace.absolute())
        except (OSError, ValueError) as exc:
            # Windows may expose one directory through both its 8.3 and long
            # spellings (for example RUNNER~1 and runneradmin).  Preserve the
            # lexical tail below the workspace instead of resolving it, so an
            # interior junction/reparse point remains visible to the custody
            # checks.  Only a real, non-reparse ancestor that is the same
            # filesystem node as the workspace can bridge the two spellings.
            relative_alias: Path | None = None
            if os.name == "nt":
                absolute = candidate.absolute()
                for ancestor in absolute.parents:
                    try:
                        info = ancestor.lstat()
                    except OSError:
                        continue
                    if (not stat.S_ISDIR(info.st_mode)
                            or stat.S_ISLNK(info.st_mode) or _is_reparse(info)):
                        continue
                    if _same_filesystem_node(ancestor, workspace):
                        relative_alias = absolute.relative_to(ancestor)
                        break
            if relative_alias is None:
                raise EvidenceError({"code": "path_escape", "path": str(value),
                                     "message": "path is outside the workspace"}) from exc
            candidate = relative_alias
    raw = candidate.as_posix()
    if raw in {"", "."} or any(part in {"", ".", ".."} for part in candidate.parts):
        raise EvidenceError({"code": "path_escape", "path": raw,
                             "message": "receipt paths must be relative and traversal-free"})
    # resolve() follows existing symlinks.  A path which resolves outside the
    # workspace is not a valid binding even when its spelling is relative.
    resolved = (workspace / candidate)
    try:
        resolved_real = resolved.resolve(strict=False)
        resolved_real.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise EvidenceError({"code": "path_escape", "path": raw,
                             "message": "path resolves outside the workspace"}) from exc
    if require_exists and (not resolved.is_file() or resolved.is_symlink()):
        raise EvidenceError({"code": "artifact_missing", "path": raw,
                             "message": "bound artifact is missing or symlinked"})
    return raw


def _check_directory_chain(workspace: Path, directory: Path) -> None:
    """Reject symlink/reparse/non-directory components under ``workspace``.

    ``Path.resolve`` alone is not a custody check: an interior symlink can
    still resolve to another directory inside the workspace.  Receipt and
    artifact paths therefore require every existing parent component to be a
    real directory in the canonical workspace tree.
    """
    try:
        relative = directory.absolute().relative_to(workspace.absolute())
    except ValueError as exc:
        raise EvidenceError({
            "code": "path_escape",
            "path": directory.as_posix(),
            "message": "directory escapes the workspace",
        }) from exc
    current = workspace
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            # The caller may create the remaining directory chain.  Existing
            # components have still been checked, and mkdir is rechecked by
            # the publication path after creation.
            break
        except OSError as exc:
            raise EvidenceError({
                "code": "artifact_parent_unreadable",
                "path": "workspace",
                "message": str(exc),
            }) from exc
        if (stat.S_ISLNK(info.st_mode) or _is_reparse(info)
                or not stat.S_ISDIR(info.st_mode)):
            raise EvidenceError({
                "code": "artifact_parent_not_directory",
                "path": "workspace",
                "message": "artifact parent contains a symlink or non-directory",
            })


def _artifact_descriptor(workspace: Path, path: Path | str | None,
                        role: str, *, require_exists: bool = False) -> dict[str, Any] | None:
    capture = _capture_artifact(
        workspace, path, role, require_exists=require_exists)
    return capture[0] if capture is not None else None


def _capture_artifact(
    workspace: Path,
    path: Path | str | None,
    role: str,
    *,
    require_exists: bool = False,
) -> tuple[dict[str, Any], tuple[int, ...]] | None:
    """Capture bytes and local identity from one regular one-link artifact."""
    if path is None:
        return None
    if not isinstance(role, str) or role not in ARTIFACT_ROLES:
        raise EvidenceError({
            "code": "invalid_artifact_role",
            "path": "execution.artifact.role",
            "message": "artifact role is not a closed value",
            "actual": role,
        })
    relative = _safe_relative_path(workspace, path, require_exists=False)
    candidate = workspace / relative
    expected_leaf: tuple[int, ...] | None = None
    try:
        before_leaf = candidate.lstat()
        expected_leaf = _node_identity(before_leaf)
    except FileNotFoundError:
        pass
    except OSError as exc:
        if require_exists:
            raise EvidenceError({
                "code": "artifact_unreadable", "path": relative,
                "message": str(exc),
            }) from exc
    _check_directory_chain(workspace, candidate.parent)
    descriptor: dict[str, Any] = {"role": str(role), "path": relative}
    try:
        candidate.lstat()
    except FileNotFoundError:
        if require_exists:
            raise EvidenceError({
                "code": "artifact_missing", "path": relative,
                "message": "bound artifact is missing",
            })
        return descriptor, tuple()
    except OSError as exc:
        if require_exists:
            raise EvidenceError({
                "code": "artifact_unreadable", "path": relative,
                "message": str(exc),
            }) from exc
        return descriptor, tuple()
    if expected_leaf is not None:
        try:
            after_leaf = _node_identity(candidate.lstat())
        except OSError as exc:
            raise EvidenceError({
                "code": "artifact_parent_changed", "path": relative,
                "message": "artifact changed during parent custody check",
            }) from exc
        if after_leaf != expected_leaf:
            raise EvidenceError({
                "code": "artifact_parent_changed", "path": relative,
                "message": "artifact changed during parent custody check",
            })
    digest, size, identity = _capture_file(candidate)
    descriptor.update({"sha256": digest, "bytes": size})
    return descriptor, identity


def _captures_match(
    first: tuple[dict[str, Any], tuple[int, ...]] | None,
    second: tuple[dict[str, Any], tuple[int, ...]] | None,
) -> bool:
    if first is None or second is None:
        return first is second
    descriptor_a, identity_a = first
    descriptor_b, identity_b = second
    return (descriptor_a == descriptor_b and _same_identity(identity_a, identity_b))


def _capture_receipt_artifacts(
    workspace: Path,
    receipt: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], tuple[int, ...]]]:
    execution = receipt.get("execution")
    if not isinstance(execution, dict):
        return {}
    required = execution.get("state") == "succeeded"
    captures: dict[str, tuple[dict[str, Any], tuple[int, ...]]] = {}
    # Capture the produced output first and the source last.  The source is
    # the custody anchor and therefore gets the closest possible rebind to the
    # final receipt read.  Callers perform a second pass to close a mutation
    # seam between the two descriptors.
    for key in ("output", "input"):
        descriptor = execution.get(key)
        if not isinstance(descriptor, dict):
            continue
        role = descriptor.get("role")
        rel = descriptor.get("path")
        if not isinstance(role, str) or not isinstance(rel, str):
            continue
        # Refused/failed receipts may retain a diagnostic path without a
        # captured artifact.  ``validate_receipt`` deliberately does not bind
        # such a missing optional file, so the final rebind set must not grow
        # a synthetic empty capture here.
        if (not required and "sha256" not in descriptor
                and "bytes" not in descriptor):
            continue
        capture = _capture_artifact(workspace, rel, role, require_exists=required)
        if capture is not None:
            captures[f"execution.{key}"] = capture
    return captures


def _capture_sets_match(
    first: dict[str, tuple[dict[str, Any], tuple[int, ...]]],
    second: dict[str, tuple[dict[str, Any], tuple[int, ...]]],
) -> bool:
    if set(first) != set(second):
        return False
    return all(_captures_match(first[key], second[key]) for key in first)


def derive_proof_grade(
    evidence_class: str,
    terminal_state: str,
    quality: dict[str, Any] | None = None,
) -> str:
    """Derive the legacy grade from a closed evidence/state pair.

    Any unknown value or non-success terminal state fails closed to ``none``.
    This function does not inspect capabilities and intentionally has no
    renderer-probe input.
    """
    if terminal_state != "succeeded":
        return "none"
    if evidence_class == "certified_render" and not CERTIFIED_PROOF_RELEASE_ENABLED:
        return "none"
    grade = _GRADE_BY_EVIDENCE.get(evidence_class, "none")
    if grade != "none":
        # Advisory LibreOffice proof is never a claim without the Hangul
        # quality result.  Native/certified legacy paths remain compatible
        # when no quality checker was recorded; if they do record one, a
        # failed/unknown result still downgrades rather than being ignored.
        if evidence_class == "advisory_render":
            if not ADVISORY_PROOF_RELEASE_ENABLED:
                return "none"
            if not isinstance(quality, dict):
                return "none"
        if isinstance(quality, dict):
            quality_state = quality.get("state")
            if evidence_class == "native_render":
                # Native Hancom is renderer provenance, not a promise that
                # this checker can inspect every font (notably Type3).  Only a
                # confirmed failed quality result downgrades that provenance;
                # unknown/not_applicable remains diagnostic and hash-bound.
                if quality_state == "failed":
                    return "none"
            elif quality_state != "passed":
                # Certified and diagnostic paths retain their existing strict
                # semantics: an attached non-pass quality result cannot be a
                # higher proof claim. Advisory is handled above and requires
                # an actual passed quality result plus the release switch.
                return "none"
    return grade


def _validate_enum(value: Any, allowed: frozenset[str], code: str,
                   path: str, errors: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or value not in allowed:
        errors.append({"code": code, "path": path,
                       "message": f"unknown closed value: {value!r}"})


def _validate_key_set(
    value: Any,
    allowed: frozenset[str],
    required: frozenset[str],
    path: str,
    errors: list[dict[str, Any]],
    *,
    unknown_code: str,
    missing_code: str,
) -> None:
    """Reject schema drift instead of accepting arbitrary v1 metadata."""
    if not isinstance(value, dict):
        return
    for key in value:
        if key not in allowed:
            errors.append({
                "code": unknown_code,
                "path": f"{path}.{key}",
                "message": "field is not part of the closed receipt schema",
            })
    for key in sorted(required - set(value)):
        errors.append({
            "code": missing_code,
            "path": f"{path}.{key}",
            "message": "required field is missing from the receipt schema",
        })


def _validate_created_utc(value: Any, errors: list[dict[str, Any]]) -> None:
    """Require UTC timestamps at exact second precision (no free-form text)."""
    if not isinstance(value, str) or not _UTC_SECONDS_RE.fullmatch(value):
        errors.append({
            "code": "invalid_created_utc",
            "path": "created_utc",
            "message": "created_utc must be YYYY-MM-DDTHH:MM:SSZ",
        })
        return
    try:
        _datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append({
            "code": "invalid_created_utc",
            "path": "created_utc",
            "message": "created_utc is not a valid UTC timestamp",
        })


def _validate_token(value: Any, code: str, path: str,
                    errors: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        errors.append({
            "code": code,
            "path": path,
            "message": "metadata must be a bounded machine token",
        })


def _validate_capability_facts(value: Any, errors: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append({
            "code": "invalid_capability_facts",
            "path": "capability_facts",
            "message": "capability_facts must be an allowlisted boolean object",
        })
        return
    for key, fact in value.items():
        if key not in _CAPABILITY_KEYS:
            errors.append({
                "code": "unknown_capability_fact",
                "path": f"capability_facts.{key}",
                "message": "capability fact key is not allowlisted",
            })
        if type(fact) is not bool:
            errors.append({
                "code": "invalid_capability_fact",
                "path": f"capability_facts.{key}",
                "message": "capability facts must be scalar booleans",
            })


def _validate_quality(
    value: Any,
    evidence_class: Any,
    output_descriptor: dict[str, Any] | None,
    errors: list[dict[str, Any]],
) -> None:
    """Validate the closed render-quality object and bind it to PDF bytes."""
    if value is None:
        return
    path = "quality"
    if evidence_class not in _RENDER_EVIDENCE:
        errors.append({
            "code": "quality_not_allowed",
            "path": path,
            "message": "quality is only valid for rendered evidence",
        })
        return
    if not isinstance(value, dict):
        errors.append({
            "code": "invalid_quality",
            "path": path,
            "message": "quality must be a closed object",
        })
        return
    _validate_key_set(
        value, _QUALITY_ALLOWED, _QUALITY_REQUIRED, path, errors,
        unknown_code="unknown_quality_field",
        missing_code="missing_quality_field",
    )
    if value.get("schema") != QUALITY_SCHEMA:
        errors.append({
            "code": "quality_schema_mismatch",
            "path": f"{path}.schema",
            "message": f"quality schema must be {QUALITY_SCHEMA!r}",
        })
    if value.get("checker") != "hangul_glyphs":
        errors.append({
            "code": "unknown_quality_checker",
            "path": f"{path}.checker",
            "message": "quality checker is not the shipped closed checker",
        })
    _validate_token(value.get("checker"), "invalid_quality_checker",
                    f"{path}.checker", errors)
    _validate_token(value.get("version"), "invalid_quality_version",
                    f"{path}.version", errors)
    _validate_enum(value.get("state"), QUALITY_STATES,
                   "unknown_quality_state", f"{path}.state", errors)
    _validate_enum(value.get("reason_code"), QUALITY_REASON_CODES,
                   "unknown_quality_reason", f"{path}.reason_code", errors)
    state = value.get("state")
    reason_code = value.get("reason_code")
    if (state in _QUALITY_REASONS_BY_STATE
            and reason_code not in _QUALITY_REASONS_BY_STATE[state]):
        errors.append({
            "code": "quality_reason_state_mismatch",
            "path": f"{path}.reason_code",
            "message": "quality reason_code is not valid for its state",
            "state": state,
            "actual": reason_code,
        })

    artifact_hash = value.get("artifact_sha256")
    artifact_bytes = value.get("artifact_bytes")
    if not isinstance(artifact_hash, str) or not _SHA256_RE.fullmatch(artifact_hash):
        errors.append({
            "code": "invalid_quality_artifact_hash",
            "path": f"{path}.artifact_sha256",
            "message": "quality artifact_sha256 must be lowercase hex",
        })
    if type(artifact_bytes) is not int or artifact_bytes < 0:
        errors.append({
            "code": "invalid_quality_artifact_size",
            "path": f"{path}.artifact_bytes",
            "message": "quality artifact_bytes must be a non-negative integer",
        })
    if not isinstance(output_descriptor, dict) \
            or output_descriptor.get("role") != "rendered_pdf":
        errors.append({
            "code": "quality_output_binding_missing",
            "path": path,
            "message": "quality must bind a rendered_pdf output descriptor",
        })
    if isinstance(artifact_hash, str) and isinstance(output_descriptor, dict):
        output_hash = output_descriptor.get("sha256")
        output_role = output_descriptor.get("role")
        if output_role == "rendered_pdf" and output_hash != artifact_hash:
            errors.append({
                "code": "quality_artifact_hash_mismatch",
                "path": path,
                "message": "quality artifact hash must equal the bound rendered PDF",
                "expected": output_hash,
                "actual": artifact_hash,
            })

    numeric = (
        "source_hangul_count", "pdf_hangul_count", "page_count",
        "mapped_font_xrefs", "checked_font_xrefs",
        "max_unique_hangul_per_xref", "min_glyph_capacity",
    )
    for key in numeric:
        number = value.get(key)
        if type(number) is not int or number < 0:
            errors.append({
                "code": "invalid_quality_count",
                "path": f"{path}.{key}",
                "message": "quality evidence counts must be non-negative integers",
            })


def _validate_success_exit_code(
    execution: dict[str, Any], errors: list[dict[str, Any]]
) -> None:
    """Every successful terminal execution records the native zero exit."""
    exit_code = execution.get("exit_code")
    if "exit_code" not in execution:
        errors.append({
            "code": "successful_exit_code_missing",
            "path": "execution.exit_code",
            "message": "successful evidence must record exit_code 0",
        })
    elif type(exit_code) is not int:
        errors.append({
            "code": "invalid_exit_code",
            "path": "execution.exit_code",
            "message": "exit_code must be an integer",
        })
    elif exit_code != 0:
        errors.append({
            "code": "successful_exit_nonzero",
            "path": "execution.exit_code",
            "message": "successful evidence requires exit_code 0",
            "actual": exit_code,
        })


def _validate_execution_contract(
    backend: Any,
    evidence_class: Any,
    execution: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """Enforce backend/evidence and successful artifact-role contracts."""
    expected_class = _BACKEND_EVIDENCE.get(backend)
    if expected_class is not None and evidence_class != expected_class:
        errors.append({
            "code": "backend_evidence_mismatch",
            "path": "evidence_class",
            "message": "backend and evidence class are not a closed pair",
            "expected": expected_class,
            "actual": evidence_class,
        })
    state = execution.get("state")
    if state != "succeeded":
        return

    _validate_success_exit_code(execution, errors)

    input_descriptor = execution.get("input")
    output_descriptor = execution.get("output")
    if not isinstance(input_descriptor, dict) or not isinstance(output_descriptor, dict):
        return
    input_role = input_descriptor.get("role")
    output_role = output_descriptor.get("role")
    input_path = input_descriptor.get("path")
    output_path = output_descriptor.get("path")
    if not isinstance(input_path, str) or not isinstance(output_path, str):
        return
    if input_path.casefold() == output_path.casefold():
        errors.append({
            "code": "artifact_binding_not_distinct",
            "path": "execution",
            "message": "successful evidence input and output must be distinct artifacts",
        })
    input_suffix = Path(input_path).suffix.casefold()
    output_suffix = Path(output_path).suffix.casefold()
    if evidence_class == "structural_only":
        if input_role != "source_form" or input_suffix != ".hwpx":
            errors.append({
                "code": "structural_input_role_invalid",
                "path": "execution.input",
                "message": "structural evidence requires a source_form HWPX input",
            })
        if output_role != "assembled_hwpx" or output_suffix != ".hwpx":
            errors.append({
                "code": "structural_output_role_invalid",
                "path": "execution.output",
                "message": "structural evidence requires an assembled_hwpx HWPX output",
            })
        return
    if evidence_class not in _RENDER_EVIDENCE:
        return
    if input_role != "assembled_hwpx" or input_suffix != ".hwpx":
        errors.append({
            "code": "render_input_role_invalid",
            "path": "execution.input",
            "message": "render evidence requires an assembled_hwpx HWPX input",
        })
    expected_role, expected_suffix = _RENDER_OUTPUT_ROLE[evidence_class]
    if output_role != expected_role or output_suffix != expected_suffix:
        errors.append({
            "code": "render_output_role_invalid",
            "path": "execution.output",
            "message": "render evidence output role/extension does not match its backend",
            "expected_role": expected_role,
            "expected_suffix": expected_suffix,
            "actual_role": output_role,
            "actual_suffix": output_suffix,
        })


def build_receipt(
    workspace: Path | str,
    *,
    backend: str,
    evidence_class: str,
    terminal_state: str,
    input_path: Path | str | None = None,
    output_path: Path | str | None = None,
    input_role: str = "assembled_hwpx",
    output_role: str = "rendered_pdf",
    exit_code: int | None = None,
    reason_code: str | None = None,
    renderer_id: str | None = None,
    renderer_version: str | None = None,
    reproducible_here: bool | None = None,
    capability_facts: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one terminal, artifact-bound receipt without writing it.

    ``input_path`` and ``output_path`` may be absolute for a caller's
    convenience, but the serialized receipt always stores workspace-relative
    paths.  Successful executions require both current files; non-success
    states may omit an output because a failed renderer need not produce one.
    """
    workspace_path = _normalise_workspace(workspace)
    root_guard = _workspace_guard(workspace_path)
    errors: list[dict[str, Any]] = []
    _validate_enum(backend, BACKEND_IDS, "unknown_backend", "execution.backend", errors)
    _validate_enum(evidence_class, EVIDENCE_CLASSES,
                   "unknown_evidence_class", "evidence_class", errors)
    _validate_enum(terminal_state, TERMINAL_STATES,
                   "unknown_terminal_state", "execution.state", errors)
    if errors:
        raise EvidenceError(errors)
    succeeded = terminal_state == "succeeded"
    input_capture = _capture_artifact(
        workspace_path, input_path, input_role, require_exists=succeeded)
    output_capture = _capture_artifact(
        workspace_path, output_path, output_role, require_exists=succeeded)
    input_descriptor = input_capture[0] if input_capture is not None else None
    output_descriptor = output_capture[0] if output_capture is not None else None
    if succeeded and (input_descriptor is None or output_descriptor is None):
        raise EvidenceError({
            "code": "artifact_binding_missing", "path": "execution",
            "message": "successful evidence requires current input and output artifacts",
        })
    if exit_code is not None and (type(exit_code) is not int or exit_code < 0):
        raise EvidenceError({"code": "invalid_exit_code", "path": "execution.exit_code",
                             "message": "exit_code must be a non-negative integer"})
    execution: dict[str, Any] = {
        "backend": backend,
        "state": terminal_state,
        "input": input_descriptor,
        "output": output_descriptor,
    }
    if exit_code is not None:
        execution["exit_code"] = exit_code
    if reason_code:
        execution["reason_code"] = str(reason_code)
    if renderer_id:
        execution["renderer_id"] = str(renderer_id)
    if renderer_version:
        execution["renderer_version"] = str(renderer_version)
    contract_errors: list[dict[str, Any]] = []
    _validate_key_set(
        execution, _EXECUTION_ALLOWED, _EXECUTION_REQUIRED, "execution",
        contract_errors, unknown_code="unknown_execution_field",
        missing_code="missing_execution_field",
    )
    _validate_execution_contract(backend, evidence_class, execution, contract_errors)
    _validate_token(reason_code, "invalid_reason_code", "execution.reason_code",
                    contract_errors)
    _validate_token(renderer_id, "invalid_renderer_id", "execution.renderer_id",
                    contract_errors)
    _validate_token(renderer_version, "invalid_renderer_version",
                    "execution.renderer_version", contract_errors)
    _validate_capability_facts(capability_facts, contract_errors)
    _validate_quality(quality, evidence_class, output_descriptor, contract_errors)
    if contract_errors:
        raise EvidenceError(contract_errors)
    grade = derive_proof_grade(evidence_class, terminal_state, quality)
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "created_utc": _now_utc(),
        "execution": execution,
        "evidence_class": evidence_class,
        "proof_grade": grade,
        "proof_unavailable": grade == "none",
    }
    if reproducible_here is not None:
        receipt["reproducible_here"] = bool(reproducible_here)
    if capability_facts is not None:
        # Facts are informative only.  Keep the field intentionally nested and
        # never let it participate in grade derivation.
        receipt["capability_facts"] = dict(capability_facts)
    if quality is not None:
        receipt["quality"] = dict(quality)
    receipt_errors: list[dict[str, Any]] = []
    _validate_key_set(
        receipt, _TOP_LEVEL_ALLOWED, _TOP_LEVEL_REQUIRED - {"receipt_sha256"}, "receipt",
        receipt_errors, unknown_code="unknown_receipt_field",
        missing_code="missing_receipt_field",
    )
    _validate_created_utc(receipt.get("created_utc"), receipt_errors)
    if receipt_errors:
        raise EvidenceError(receipt_errors)
    receipt["receipt_sha256"] = hashlib.sha256(
        _canonical_bytes(receipt, omit_hash=True)).hexdigest()
    _check_workspace_guard(root_guard)
    initial_bound: dict[str, tuple[dict[str, Any], tuple[int, ...]]] = {}
    if input_capture is not None and "sha256" in input_capture[0]:
        initial_bound["execution.input"] = input_capture
    if output_capture is not None and "sha256" in output_capture[0]:
        initial_bound["execution.output"] = output_capture
    # Two complete output-then-source passes close a mutation seam between
    # sibling descriptors (and keep the source capture closest to return).
    final_bound = _capture_receipt_artifacts(workspace_path, receipt)
    final_bound_again = _capture_receipt_artifacts(workspace_path, receipt)
    if (not _capture_sets_match(initial_bound, final_bound)
            or not _capture_sets_match(final_bound, final_bound_again)):
        raise EvidenceError({
            "code": "artifact_rebind_mismatch",
            "path": "execution",
            "message": "input/output changed during receipt capture",
        })
    return receipt


def _walk_forbidden(value: Any, path: str, errors: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).casefold()
            if key_text in _FORBIDDEN_KEYS:
                errors.append({"code": "privacy_field", "path": f"{path}.{key}",
                               "message": "runtime-private field is not allowed in a receipt"})
            _walk_forbidden(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]", errors)
    elif isinstance(value, str) and _FORBIDDEN_ABS.search(value.strip()):
        errors.append({"code": "privacy_field", "path": path,
                       "message": "absolute/user paths are not allowed in a receipt"})


def _validate_artifact(workspace: Path, descriptor: Any, path: str,
                       *, required: bool, errors: list[dict[str, Any]],
                       capture_out: dict[str, tuple[dict[str, Any], tuple[int, ...]]] | None = None,
                       ) -> None:
    if descriptor is None:
        if required:
            errors.append({"code": "artifact_binding_missing", "path": path,
                           "message": "successful execution requires an artifact"})
        return
    if not isinstance(descriptor, dict):
        errors.append({"code": "invalid_artifact", "path": path,
                       "message": "artifact binding must be an object"})
        return
    role = descriptor.get("role")
    if not isinstance(role, str) or role not in ARTIFACT_ROLES:
        errors.append({
            "code": "invalid_artifact_role",
            "path": f"{path}.role",
            "message": "artifact role is not a closed value",
            "actual": role,
        })
    rel = descriptor.get("path")
    if not isinstance(rel, str):
        errors.append({"code": "invalid_artifact_path", "path": f"{path}.path",
                       "message": "artifact path must be a relative string"})
        return
    if _FORBIDDEN_ABS.search(rel) or rel.replace("\\", "/").startswith("../"):
        errors.append({"code": "path_escape", "path": f"{path}.path",
                       "message": "artifact path must stay relative to the workspace"})
        return
    try:
        safe_rel = _safe_relative_path(workspace, rel, require_exists=False)
    except EvidenceError as exc:
        errors.extend(exc.errors)
        return
    if safe_rel != rel.replace("\\", "/"):
        errors.append({"code": "invalid_artifact_path", "path": f"{path}.path",
                       "message": "artifact path is not canonical POSIX-relative"})
        return
    expected_hash = descriptor.get("sha256")
    expected_bytes = descriptor.get("bytes")
    candidate = workspace / safe_rel
    # A failed/refused/not-run terminal may legitimately have no output.  The
    # path remains useful diagnostic context, but there are no bytes to bind.
    if not required and not candidate.is_file() and expected_hash is None \
            and expected_bytes is None:
        return
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        errors.append({"code": "invalid_artifact_hash", "path": f"{path}.sha256",
                       "message": "artifact sha256 must be 64 lowercase hex characters"})
        return
    if not isinstance(expected_bytes, int) or expected_bytes < 0:
        errors.append({"code": "invalid_artifact_size", "path": f"{path}.bytes",
                       "message": "artifact bytes must be a non-negative integer"})
        return
    try:
        capture = _capture_artifact(
            workspace, candidate, role, require_exists=required)
    except EvidenceError as exc:
        errors.extend({
            **item,
            # Never expose an absolute workspace/temp path through a public
            # Stage-6 finding.  The descriptor location is sufficient for
            # diagnosis and remains stable across workspaces.
            "path": path,
        } for item in exc.errors)
        return
    if capture is None:
        if required:
            errors.append({"code": "artifact_missing", "path": f"{path}.path",
                           "message": "bound artifact is missing or symlinked"})
        return
    if capture_out is not None:
        capture_out[path] = capture
    actual_descriptor, _identity = capture
    actual_hash = actual_descriptor.get("sha256")
    actual_bytes = actual_descriptor.get("bytes")
    if actual_hash != expected_hash or actual_bytes != expected_bytes:
        errors.append({"code": "artifact_hash_mismatch", "path": path,
                       "message": "current artifact bytes differ from the receipt",
                       "expected_sha256": expected_hash,
                       "actual_sha256": actual_hash,
                       "expected_bytes": expected_bytes,
                       "actual_bytes": actual_bytes})


def validate_receipt(
    workspace: Path | str,
    receipt: Any,
    *,
    _capture_out: dict[str, tuple[dict[str, Any], tuple[int, ...]]] | None = None,
) -> dict[str, Any]:
    """Validate a receipt and current bound bytes, raising ``EvidenceError``."""
    workspace_path = _normalise_workspace(workspace)
    root_guard = _workspace_guard(workspace_path)
    errors: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise EvidenceError({"code": "invalid_receipt", "path": "receipt",
                             "message": "receipt must be a JSON object"})
    _walk_forbidden(receipt, "receipt", errors)
    _validate_key_set(
        receipt, _TOP_LEVEL_ALLOWED, _TOP_LEVEL_REQUIRED, "receipt", errors,
        unknown_code="unknown_receipt_field", missing_code="missing_receipt_field",
    )
    _validate_created_utc(receipt.get("created_utc"), errors)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        errors.append({"code": "schema_mismatch", "path": "schema",
                       "message": f"schema must be {RECEIPT_SCHEMA!r}"})
    execution = receipt.get("execution")
    if not isinstance(execution, dict):
        errors.append({"code": "invalid_execution", "path": "execution",
                       "message": "execution must be an object"})
        execution = {}
    else:
        _validate_key_set(
            execution, _EXECUTION_ALLOWED, _EXECUTION_REQUIRED, "execution", errors,
            unknown_code="unknown_execution_field", missing_code="missing_execution_field",
        )
    backend = execution.get("backend")
    state = execution.get("state")
    evidence_class = receipt.get("evidence_class")
    _validate_enum(backend, BACKEND_IDS, "unknown_backend", "execution.backend", errors)
    _validate_enum(evidence_class, EVIDENCE_CLASSES,
                   "unknown_evidence_class", "evidence_class", errors)
    _validate_enum(state, TERMINAL_STATES, "unknown_terminal_state",
                   "execution.state", errors)
    quality = receipt.get("quality")
    expected_grade = derive_proof_grade(evidence_class, state, quality)
    if receipt.get("proof_grade") != expected_grade:
        errors.append({"code": "grade_mismatch", "path": "proof_grade",
                       "message": "proof_grade does not match the terminal receipt",
                       "expected": expected_grade, "actual": receipt.get("proof_grade")})
    if receipt.get("proof_unavailable") is not (expected_grade == "none"):
        errors.append({"code": "proof_unavailable_mismatch", "path": "proof_unavailable",
                       "message": "proof_unavailable must be true exactly when grade is none"})
    if "reproducible_here" in receipt and not isinstance(receipt["reproducible_here"], bool):
        errors.append({"code": "invalid_reproducible_here", "path": "reproducible_here",
                        "message": "reproducible_here must be boolean"})
    if "exit_code" in execution and (
            type(execution["exit_code"]) is not int or execution["exit_code"] < 0):
        errors.append({
            "code": "invalid_exit_code",
            "path": "execution.exit_code",
            "message": "exit_code must be a non-negative integer",
        })
    for artifact_name in ("input", "output"):
        descriptor = execution.get(artifact_name)
        if isinstance(descriptor, dict):
            _validate_key_set(
                descriptor, _ARTIFACT_ALLOWED, _ARTIFACT_REQUIRED,
                f"execution.{artifact_name}", errors,
                unknown_code="unknown_artifact_field",
                missing_code="missing_artifact_field",
            )
    _validate_execution_contract(backend, evidence_class, execution, errors)
    _validate_token(execution.get("reason_code"), "invalid_reason_code",
                    "execution.reason_code", errors)
    _validate_token(execution.get("renderer_id"), "invalid_renderer_id",
                    "execution.renderer_id", errors)
    _validate_token(execution.get("renderer_version"),
                    "invalid_renderer_version", "execution.renderer_version", errors)
    _validate_capability_facts(receipt.get("capability_facts"), errors)
    _validate_quality(quality, evidence_class, execution.get("output"), errors)
    required = state == "succeeded"
    _validate_artifact(workspace_path, execution.get("input"), "execution.input",
                       required=required, errors=errors, capture_out=_capture_out)
    _validate_artifact(workspace_path, execution.get("output"), "execution.output",
                       required=required, errors=errors, capture_out=_capture_out)
    self_hash = receipt.get("receipt_sha256")
    if not isinstance(self_hash, str) or not _SHA256_RE.fullmatch(self_hash):
        errors.append({"code": "invalid_receipt_hash", "path": "receipt_sha256",
                       "message": "receipt_sha256 must be 64 lowercase hex characters"})
    elif hashlib.sha256(_canonical_bytes(receipt, omit_hash=True)).hexdigest() != self_hash:
        errors.append({"code": "receipt_hash_mismatch", "path": "receipt_sha256",
                       "message": "receipt self-hash does not match its canonical content"})
    if errors:
        raise EvidenceError(errors)
    _check_workspace_guard(root_guard)
    return receipt


def _remove_owned_receipt(
    target: Path,
    identity: tuple[int, ...] | None,
    expected_raw: bytes | None = None,
) -> None:
    """Rollback only the inode published by this call, without unlink races.

    A plain ``lstat``/``read``/``unlink`` sequence can unlink a foreign
    replacement that wins the final race.  First move the pathname to a
    private same-directory quarantine (rename is atomic), inspect that moved
    inode, and only unlink it when its stable identity and canonical bytes
    still match the receipt we wrote.  A foreign replacement is restored with
    a no-clobber hard-link; if another process has recreated the public name,
    the quarantine is retained rather than deleting either object.
    """
    if identity is None:
        return

    def _read_quarantine(path: Path) -> tuple[bytes, tuple[int, ...]] | None:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or _is_reparse(info)):
                return None
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(str(path), flags)
            try:
                opened = os.fstat(fd)
                if (_node_identity(opened)[:2] != _node_identity(info)[:2]
                        or not stat.S_ISREG(opened.st_mode)
                        or _is_reparse(opened)):
                    return None
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024,
                                            _MAX_RECEIPT_BYTES - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_RECEIPT_BYTES:
                        return None
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (_node_identity(after)[:2] != _node_identity(opened)[:2]
                        or after.st_size != total
                        or after.st_mtime_ns != opened.st_mtime_ns):
                    return None
                return b"".join(chunks), _node_identity(after)
            finally:
                os.close(fd)
        except (OSError, ValueError, TypeError):
            return None

    def _restore_no_clobber(path: Path) -> None:
        """Restore a quarantined foreign inode only if the public name is free."""
        try:
            target.lstat()
            return
        except FileNotFoundError:
            pass
        except OSError:
            return
        try:
            # Hard-linking is atomic and fails when a concurrent actor has
            # recreated ``target``; it therefore cannot clobber that actor's
            # replacement.  Unlinking the quarantine leaves a one-link file.
            os.link(str(path), str(target), follow_symlinks=False)
        except (OSError, ValueError, TypeError):
            return
        try:
            path.unlink()
        except (OSError, ValueError):
            pass

    quarantine: Path | None = None
    try:
        for _ in range(8):
            quarantine = target.with_name(
                f".{target.name}.rollback-{uuid.uuid4().hex}")
            try:
                # The random destination is private to this rollback.  A
                # collision is retried; rename itself is the atomic custody
                # operation, unlike a check followed by unlink.
                os.rename(str(target), str(quarantine))
                break
            except FileExistsError:
                quarantine = None
                continue
            except FileNotFoundError:
                return
        if quarantine is None or not quarantine.exists():
            return
        captured = _read_quarantine(quarantine)
        if captured is None:
            _restore_no_clobber(quarantine)
            return
        raw, current = captured
        # A callback may create a hardlink to our owned inode. Public reads
        # reject nlink != 1, but rollback must still recognize that inode.
        # Link creation updates ctime and nlink, so ownership compares the
        # stable device/inode/size/mtime fields and then canonical bytes.
        owned = current[:4] == tuple(identity)[:4]
        if expected_raw is not None:
            owned = owned and raw == expected_raw
        if owned:
            try:
                quarantine.unlink()
            except (OSError, ValueError):
                pass
        else:
            _restore_no_clobber(quarantine)
    except (EvidenceError, OSError, ValueError, TypeError):
        if quarantine is not None:
            _restore_no_clobber(quarantine)
        return


class _DestinationDirectoryBinding:
    """Hold the receipt directory while creating and publishing its leaf.

    POSIX uses an ``O_DIRECTORY|O_NOFOLLOW`` descriptor and ``*at`` operations
    so a renamed parent cannot redirect a relative create/replace.  Windows
    holds a ``CreateFileW`` directory handle without ``FILE_SHARE_DELETE``;
    this prevents a parent rename while path-based child operations run.
    """

    def __init__(self, path: Path, fd: int, *, posix: bool,
                 identity: tuple[int, int], opened_real: Path):
        self.path = path
        self.fd = fd
        self.posix = posix
        self.identity = identity
        self.opened_real = opened_real
        self.closed = False

    @classmethod
    def open(cls, path: Path) -> "_DestinationDirectoryBinding":
        posix = os.name != "nt"
        if posix:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(str(path), flags)
            except (OSError, ValueError, TypeError) as exc:
                raise EvidenceError({
                    "code": "artifact_parent_binding_unavailable",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory could not be held",
                }) from exc
        else:
            try:
                import ctypes
                import msvcrt

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                create = kernel32.CreateFileW
                create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                   ctypes.c_uint32, ctypes.c_void_p,
                                   ctypes.c_uint32, ctypes.c_uint32,
                                   ctypes.c_void_p]
                create.restype = ctypes.c_void_p
                # FILE_LIST_DIRECTORY; share read/write but deliberately no
                # FILE_SHARE_DELETE, so an ancestor cannot be renamed while
                # this binding is live.
                handle = create(str(path), 0x0001, 0x0001 | 0x0002, None,
                                0x0003, 0x02000000, None)
                invalid = ctypes.c_void_p(-1).value
                if handle in (None, invalid):
                    raise OSError(ctypes.get_last_error(),
                                  "receipt directory could not be opened")
                try:
                    fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
                except (OSError, ValueError, TypeError):
                    kernel32.CloseHandle(handle)
                    raise
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                raise EvidenceError({
                    "code": "artifact_parent_binding_unavailable",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory could not be held",
                }) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
                raise EvidenceError({
                    "code": "artifact_parent_not_directory",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory is not a real directory",
                })
            opened_real = _opened_real_path(fd)
            if opened_real is None:
                raise EvidenceError({
                    "code": "artifact_parent_binding_unavailable",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory handle path unavailable",
                })
            binding = cls(path, fd, posix=posix,
                          identity=_node_identity(info)[:2],
                          opened_real=opened_real)
            binding.validate()
            return binding
        except EvidenceError:
            os.close(fd)
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            os.close(fd)
            raise EvidenceError({
                "code": "artifact_parent_binding_unavailable",
                "path": RECEIPT_REL.as_posix(),
                "message": "receipt directory handle could not be validated",
            }) from exc

    def _relative_path(self, name: str) -> Path:
        return self.path / name

    @staticmethod
    def _norm_bound(value: str) -> str:
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(os.path.normpath(value))

    def validate(self) -> None:
        try:
            info = self.path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or _is_reparse(info)
                    or _node_identity(info)[:2] != self.identity):
                raise EvidenceError({
                    "code": "artifact_parent_changed",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory changed during publication",
                })
            opened_real = _opened_real_path(self.fd)
            if opened_real is None:
                raise EvidenceError({
                    "code": "artifact_parent_binding_unavailable",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory handle path unavailable",
                })
            expected = Path(os.path.abspath(str(self.path)))
            if not _same_bound_path(opened_real, expected):
                raise EvidenceError({
                    "code": "artifact_parent_changed",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt directory handle escaped its path",
                })
        except EvidenceError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise EvidenceError({
                "code": "artifact_parent_changed",
                "path": RECEIPT_REL.as_posix(),
                "message": "receipt directory could not be rebound",
            }) from exc

    def _open_relative(self, name: str, flags: int, mode: int = 0o600) -> int:
        if self.posix:
            return os.open(name, flags, mode, dir_fd=self.fd)
        return os.open(str(self._relative_path(name)), flags, mode)

    def create_temp(self, raw: bytes) -> tuple[str, tuple[int, ...]]:
        for _ in range(16):
            name = f".receipt-{uuid.uuid4().hex}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0)
            try:
                fd = self._open_relative(name, flags)
            except FileExistsError:
                continue
            complete = False
            identity: tuple[int, ...] | None = None
            try:
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:])
                    if written <= 0:
                        raise OSError("receipt temporary write made no progress")
                    offset += written
                os.fsync(fd)
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or _is_reparse(info)
                        or info.st_size != len(raw)
                        or getattr(info, "st_nlink", 1) != 1):
                    raise OSError("receipt temporary identity is invalid")
                identity = _node_identity(info)
                complete = True
            finally:
                close_error: OSError | None = None
                try:
                    os.close(fd)
                except OSError as exc:
                    close_error = exc
                if not complete or close_error is not None:
                    self.remove(name)
                if close_error is not None:
                    raise close_error
            assert identity is not None
            return name, identity
        raise EvidenceError({
            "code": "receipt_publish_failed",
            "path": RECEIPT_REL.as_posix(),
            "message": "could not allocate a private receipt temporary",
        })

    def replace(self, temporary: str, target: str) -> None:
        self.validate()
        if self.posix:
            os.replace(temporary, target, src_dir_fd=self.fd,
                       dst_dir_fd=self.fd)
        else:
            os.replace(str(self._relative_path(temporary)),
                       str(self._relative_path(target)))

    def read_receipt(self, name: str) -> tuple[bytes, tuple[int, ...]]:
        if not self.posix:
            return _read_regular_once(self._relative_path(name))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            fd = self._open_relative(name, flags)
        except (OSError, ValueError, TypeError) as exc:
            raise EvidenceError({
                "code": "receipt_missing",
                "path": RECEIPT_REL.as_posix(),
                "message": "canonical receipt is missing or unreadable",
            }) from exc
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or _is_reparse(opened)
                    or getattr(opened, "st_nlink", 1) != 1):
                raise EvidenceError({
                    "code": "receipt_not_single_link",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "canonical receipt must be one regular link",
                })
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024,
                                        _MAX_RECEIPT_BYTES - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_RECEIPT_BYTES:
                    raise EvidenceError({
                        "code": "artifact_too_large",
                        "path": RECEIPT_REL.as_posix(),
                        "message": "receipt exceeds the bounded capture",
                    })
                chunks.append(chunk)
            after = os.fstat(fd)
            if (_node_identity(after)[:2] != _node_identity(opened)[:2]
                    or after.st_size != total
                    or getattr(after, "st_nlink", 1) != 1
                    or after.st_mtime_ns != opened.st_mtime_ns
                    or after.st_ctime_ns != opened.st_ctime_ns):
                raise EvidenceError({
                    "code": "receipt_changed_during_read",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "receipt changed during one-link capture",
                })
            return b"".join(chunks), _node_identity(after)
        finally:
            os.close(fd)

    def remove(self, name: str) -> None:
        try:
            if self.posix:
                os.unlink(name, dir_fd=self.fd)
            else:
                self._relative_path(name).unlink()
        except FileNotFoundError:
            pass

    def _read_loose(self, name: str) -> tuple[bytes, tuple[int, ...]] | None:
        """Read a moved receipt while allowing a callback-created hardlink."""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            fd = self._open_relative(name, flags)
        except (OSError, ValueError, TypeError):
            return None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                return None
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024,
                                        _MAX_RECEIPT_BYTES - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_RECEIPT_BYTES:
                    return None
                chunks.append(chunk)
            after = os.fstat(fd)
            if (_node_identity(after)[:2] != _node_identity(info)[:2]
                    or after.st_size != total
                    or after.st_mtime_ns != info.st_mtime_ns):
                return None
            return b"".join(chunks), _node_identity(after)
        except (OSError, ValueError, TypeError):
            return None
        finally:
            os.close(fd)

    def remove_owned(
        self, name: str, identity: tuple[int, ...] | None,
        expected_raw: bytes | None = None,
    ) -> None:
        """Rollback through this held directory, never through a swapped path."""
        if identity is None:
            return
        if not self.posix:
            _remove_owned_receipt(self._relative_path(name), identity, expected_raw)
            return
        quarantine: str | None = None
        try:
            for _ in range(8):
                candidate = f".{name}.rollback-{uuid.uuid4().hex}"
                try:
                    os.rename(name, candidate, src_dir_fd=self.fd,
                              dst_dir_fd=self.fd)
                    quarantine = candidate
                    break
                except FileExistsError:
                    continue
                except FileNotFoundError:
                    return
            if quarantine is None:
                return
            captured = self._read_loose(quarantine)
            if captured is None:
                self._restore_loose(quarantine, name)
                return
            raw, current = captured
            owned = current[:4] == tuple(identity)[:4]
            if expected_raw is not None:
                owned = owned and raw == expected_raw
            if owned:
                try:
                    os.unlink(quarantine, dir_fd=self.fd)
                except (OSError, ValueError):
                    pass
            else:
                self._restore_loose(quarantine, name)
        except (OSError, ValueError, TypeError):
            if quarantine is not None:
                self._restore_loose(quarantine, name)

    def _restore_loose(self, quarantine: str, name: str) -> None:
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            return
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            return
        try:
            os.link(quarantine, name, src_dir_fd=self.fd,
                    dst_dir_fd=self.fd, follow_symlinks=False)
        except (OSError, ValueError, TypeError):
            return
        try:
            os.unlink(quarantine, dir_fd=self.fd)
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                os.close(self.fd)
            except OSError:
                # Once the receipt is committed, directory-handle cleanup is
                # not evidence state and must not rewrite success as failure.
                pass


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Decode one JSON object while refusing duplicate member names.

    Python's default decoder keeps the last duplicate value, which can turn a
    forged receipt into a different in-memory payload than the bytes an
    operator inspected.  The hook is recursive: ``json`` invokes it for every
    nested object before the containing object is returned.
    """
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise EvidenceError({
                "code": "receipt_duplicate_key",
                "path": RECEIPT_REL.as_posix(),
                "message": "receipt contains a duplicate JSON member",
            })
        payload[key] = value
    return payload


def _decode_receipt_bytes(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError({
            "code": "receipt_malformed",
            "path": RECEIPT_REL.as_posix(),
            "message": "receipt is not valid UTF-8 JSON",
        }) from exc
    if not isinstance(payload, dict):
        raise EvidenceError({
            "code": "invalid_receipt",
            "path": RECEIPT_REL.as_posix(),
            "message": "receipt must be a JSON object",
        })
    return payload


def write_receipt(
    workspace: Path | str,
    receipt: dict[str, Any],
    *,
    before_final_rebind: Callable[[], None] | None = None,
) -> Path:
    """Validate and atomically publish a receipt with final identity rebinding."""
    workspace_path = _normalise_workspace(workspace)
    root_guard = _workspace_guard(workspace_path)
    initial_captures: dict[str, tuple[dict[str, Any], tuple[int, ...]]] = {}
    validate_receipt(workspace_path, receipt, _capture_out=initial_captures)
    _check_workspace_guard(root_guard)
    target = workspace_path / RECEIPT_REL
    _check_directory_chain(workspace_path, target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_directory_chain(workspace_path, target.parent)
    try:
        if target.exists() or target.is_symlink():
            old = target.lstat()
            if stat.S_ISLNK(old.st_mode) or _is_reparse(old) \
                    or not stat.S_ISREG(old.st_mode) \
                    or getattr(old, "st_nlink", 1) != 1:
                raise EvidenceError({
                    "code": "receipt_not_single_link",
                    "path": RECEIPT_REL.as_posix(),
                    "message": "canonical receipt must be a regular one-link file",
                })
    except FileNotFoundError:
        pass
    # Hold the destination directory across temporary creation, replacement,
    # and final receipt reads.  Path-only ``mkstemp``/``replace`` is vulnerable
    # to an interior parent swap between the second chain check and creation.
    binding = _DestinationDirectoryBinding.open(target.parent)
    temporary: str | None = None
    owned_identity: tuple[int, ...] | None = None
    expected_raw = _canonical_bytes(receipt)
    try:
        temporary, owned_identity = binding.create_temp(expected_raw)
        binding.replace(temporary, target.name)
        # The temporary name was consumed atomically.  Do not touch that
        # pathname again: a concurrent actor could legitimately recreate it.
        temporary = None
        raw, owned_identity = binding.read_receipt(target.name)
        if raw != expected_raw:
            raise EvidenceError({
                "code": "receipt_raw_mismatch",
                "path": RECEIPT_REL.as_posix(),
                "message": "published receipt bytes differ from the canonical payload",
            })
        payload = _decode_receipt_bytes(raw)
        if payload != receipt:
            raise EvidenceError({
                "code": "receipt_payload_mismatch",
                "path": RECEIPT_REL.as_posix(),
                "message": "published receipt payload differs from the requested receipt",
            })
        if before_final_rebind is not None:
            before_final_rebind()
        _check_workspace_guard(root_guard)
        binding.validate()
        final_captures = _capture_receipt_artifacts(workspace_path, payload)
        final_captures_again = _capture_receipt_artifacts(workspace_path, payload)
        if (not _capture_sets_match(initial_captures, final_captures)
                or not _capture_sets_match(final_captures, final_captures_again)):
            raise EvidenceError({
                "code": "artifact_rebind_mismatch",
                "path": "execution",
                "message": "bound artifact changed during final publication checks",
            })
        try:
            binding.validate()
            final_raw, final_identity = binding.read_receipt(target.name)
        except EvidenceError as exc:
            raise EvidenceError([
                {**item, "path": RECEIPT_REL.as_posix()}
                for item in exc.errors
            ]) from exc
        if (final_raw != expected_raw
                or not _same_identity(final_identity, owned_identity)):
            raise EvidenceError({
                "code": "receipt_rebind_mismatch",
                "path": RECEIPT_REL.as_posix(),
                "message": "receipt changed during final publication checks",
            })
        final_payload = _decode_receipt_bytes(final_raw)
        if final_payload != receipt:
            raise EvidenceError({
                "code": "receipt_payload_mismatch",
                "path": RECEIPT_REL.as_posix(),
                "message": "receipt payload changed during final publication checks",
            })
        return target
    except EvidenceError:
        binding.remove_owned(target.name, owned_identity, expected_raw)
        raise
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        binding.remove_owned(target.name, owned_identity, expected_raw)
        raise EvidenceError({
            "code": "receipt_publish_failed",
            "path": RECEIPT_REL.as_posix(),
            "message": str(exc),
        }) from exc
    finally:
        if temporary is not None:
            binding.remove(temporary)
        binding.close()


def load_and_validate_receipt(workspace: Path | str) -> dict[str, Any]:
    """Load the canonical receipt and validate it against current workspace bytes."""
    workspace_path = _normalise_workspace(workspace)
    root_guard = _workspace_guard(workspace_path)
    target = workspace_path / RECEIPT_REL
    try:
        raw, identity = _read_regular_once(target)
    except EvidenceError as exc:
        if any(item.get("code") == "artifact_unreadable" for item in exc.errors):
            raise EvidenceError({
                "code": "receipt_missing", "path": RECEIPT_REL.as_posix(),
                "message": "canonical receipt is missing or unreadable",
            }) from exc
        raise EvidenceError([
            {**item, "path": RECEIPT_REL.as_posix()}
            for item in exc.errors
        ]) from exc
    except (OSError, UnicodeError) as exc:
        raise EvidenceError({"code": "receipt_missing", "path": RECEIPT_REL.as_posix(),
                             "message": str(exc)}) from exc
    payload = _decode_receipt_bytes(raw)
    initial_captures: dict[str, tuple[dict[str, Any], tuple[int, ...]]] = {}
    validate_receipt(workspace_path, payload, _capture_out=initial_captures)
    _check_workspace_guard(root_guard)
    final_captures = _capture_receipt_artifacts(workspace_path, payload)
    final_captures_again = _capture_receipt_artifacts(workspace_path, payload)
    if (not _capture_sets_match(initial_captures, final_captures)
            or not _capture_sets_match(final_captures, final_captures_again)):
        raise EvidenceError({
            "code": "artifact_rebind_mismatch",
            "path": "execution",
            "message": "bound artifact changed during final validation checks",
        })
    try:
        final_raw, final_identity = _read_regular_once(target)
    except EvidenceError as exc:
        raise EvidenceError([
            {**item, "path": RECEIPT_REL.as_posix()}
            for item in exc.errors
        ]) from exc
    if (final_raw != raw or not _same_identity(final_identity, identity)):
        raise EvidenceError({
            "code": "receipt_rebind_mismatch",
            "path": RECEIPT_REL.as_posix(),
            "message": "receipt changed during final validation checks",
        })
    final_payload = _decode_receipt_bytes(final_raw)
    if final_payload != payload:
        raise EvidenceError({
            "code": "receipt_payload_mismatch",
            "path": RECEIPT_REL.as_posix(),
            "message": "receipt payload changed during final validation checks",
        })
    return final_payload


__all__ = [
    "ADVISORY_PROOF_RELEASE_ENABLED",
    "CERTIFIED_PROOF_RELEASE_ENABLED",
    "ARTIFACT_ROLES", "BACKEND_IDS", "EVIDENCE_CLASSES", "EvidenceError", "RECEIPT_REL",
    "QUALITY_REASON_CODES", "QUALITY_SCHEMA", "QUALITY_STATES",
    "RECEIPT_SCHEMA", "TERMINAL_STATES", "build_receipt",
    "derive_proof_grade", "load_and_validate_receipt", "validate_receipt",
    "write_receipt",
]
