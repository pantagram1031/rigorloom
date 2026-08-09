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
import tempfile
from pathlib import Path
from typing import Any


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
    "font_capacity_insufficient", "ambiguous_font_mapping",
    "font_mapping_missing", "font_buffer_unavailable", "nonembedded_font",
    "type3_font", "source_unreadable", "pdf_unreadable", "pdf_no_pages",
    "pdf_no_extractable_text", "checker_unavailable", "layout_hard_failed",
    "visual_quality_gate_pending",
})
_QUALITY_REASONS_BY_STATE = {
    "passed": frozenset({"passed"}),
    "failed": frozenset({
        "missing_hangul_glyphs", "missing_hangul_text",
        "font_capacity_insufficient",
        "layout_hard_failed", "visual_quality_gate_pending",
    }),
    "unknown": frozenset({
        "ambiguous_font_mapping", "font_mapping_missing",
        "font_buffer_unavailable", "nonembedded_font", "type3_font",
        "source_visibility_ambiguous",
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
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _normalise_workspace(workspace: Path | str) -> Path:
    try:
        return Path(workspace).expanduser().resolve()
    except OSError as exc:
        raise EvidenceError({"code": "workspace_unreadable", "path": "workspace",
                             "message": str(exc)}) from exc


def _safe_relative_path(workspace: Path, value: Path | str, *, require_exists: bool = False) -> str:
    """Return a workspace-relative POSIX path, rejecting escapes/symlinks."""
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(workspace)
        except (OSError, ValueError) as exc:
            raise EvidenceError({"code": "path_escape", "path": str(value),
                                 "message": "path is outside the workspace"}) from exc
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


def _artifact_descriptor(workspace: Path, path: Path | str | None,
                        role: str, *, require_exists: bool = False) -> dict[str, Any] | None:
    if path is None:
        return None
    if not isinstance(role, str) or role not in ARTIFACT_ROLES:
        raise EvidenceError({
            "code": "invalid_artifact_role",
            "path": "execution.artifact.role",
            "message": "artifact role is not a closed value",
            "actual": role,
        })
    relative = _safe_relative_path(workspace, path, require_exists=require_exists)
    candidate = workspace / relative
    descriptor: dict[str, Any] = {"role": str(role), "path": relative}
    if candidate.is_file() and not candidate.is_symlink():
        digest, size = _sha256_file(candidate)
        descriptor.update({"sha256": digest, "bytes": size})
    return descriptor


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
    errors: list[dict[str, Any]] = []
    _validate_enum(backend, BACKEND_IDS, "unknown_backend", "execution.backend", errors)
    _validate_enum(evidence_class, EVIDENCE_CLASSES,
                   "unknown_evidence_class", "evidence_class", errors)
    _validate_enum(terminal_state, TERMINAL_STATES,
                   "unknown_terminal_state", "execution.state", errors)
    if errors:
        raise EvidenceError(errors)
    succeeded = terminal_state == "succeeded"
    try:
        input_descriptor = _artifact_descriptor(
            workspace_path, input_path, input_role, require_exists=succeeded)
        output_descriptor = _artifact_descriptor(
            workspace_path, output_path, output_role, require_exists=succeeded)
    except EvidenceError:
        raise
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
                       *, required: bool, errors: list[dict[str, Any]]) -> None:
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
    candidate = workspace / safe_rel
    expected_hash = descriptor.get("sha256")
    expected_bytes = descriptor.get("bytes")
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
    if not candidate.is_file() or candidate.is_symlink():
        if required:
            errors.append({"code": "artifact_missing", "path": f"{path}.path",
                           "message": "bound artifact is missing or symlinked"})
        return
    try:
        actual_hash, actual_bytes = _sha256_file(candidate)
    except OSError as exc:
        errors.append({"code": "artifact_unreadable", "path": f"{path}.path",
                       "message": str(exc)})
        return
    if actual_hash != expected_hash or actual_bytes != expected_bytes:
        errors.append({"code": "artifact_hash_mismatch", "path": path,
                       "message": "current artifact bytes differ from the receipt",
                       "expected_sha256": expected_hash,
                       "actual_sha256": actual_hash,
                       "expected_bytes": expected_bytes,
                       "actual_bytes": actual_bytes})


def validate_receipt(workspace: Path | str, receipt: Any) -> dict[str, Any]:
    """Validate a receipt and current bound bytes, raising ``EvidenceError``."""
    workspace_path = _normalise_workspace(workspace)
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
                       required=required, errors=errors)
    _validate_artifact(workspace_path, execution.get("output"), "execution.output",
                       required=required, errors=errors)
    self_hash = receipt.get("receipt_sha256")
    if not isinstance(self_hash, str) or not _SHA256_RE.fullmatch(self_hash):
        errors.append({"code": "invalid_receipt_hash", "path": "receipt_sha256",
                       "message": "receipt_sha256 must be 64 lowercase hex characters"})
    elif hashlib.sha256(_canonical_bytes(receipt, omit_hash=True)).hexdigest() != self_hash:
        errors.append({"code": "receipt_hash_mismatch", "path": "receipt_sha256",
                       "message": "receipt self-hash does not match its canonical content"})
    if errors:
        raise EvidenceError(errors)
    return receipt


def write_receipt(workspace: Path | str, receipt: dict[str, Any]) -> Path:
    """Validate and atomically write ``output/proof/backend/receipt.json``."""
    workspace_path = _normalise_workspace(workspace)
    validate_receipt(workspace_path, receipt)
    target = workspace_path / RECEIPT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement in the destination directory prevents readers from
    # observing a truncated JSON document.  Never leave the temporary path in
    # the receipt directory after a failed write.
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp",
                                     dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def load_and_validate_receipt(workspace: Path | str) -> dict[str, Any]:
    """Load the canonical receipt and validate it against current workspace bytes."""
    workspace_path = _normalise_workspace(workspace)
    target = workspace_path / RECEIPT_REL
    if target.is_symlink():
        raise EvidenceError({"code": "path_escape", "path": RECEIPT_REL.as_posix(),
                             "message": "canonical receipt may not be a symlink"})
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvidenceError({"code": "receipt_missing", "path": RECEIPT_REL.as_posix(),
                             "message": str(exc)}) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceError({"code": "receipt_malformed",
                             "path": RECEIPT_REL.as_posix(),
                             "message": str(exc)}) from exc
    return validate_receipt(workspace_path, payload)


__all__ = [
    "ADVISORY_PROOF_RELEASE_ENABLED",
    "ARTIFACT_ROLES", "BACKEND_IDS", "EVIDENCE_CLASSES", "EvidenceError", "RECEIPT_REL",
    "QUALITY_REASON_CODES", "QUALITY_SCHEMA", "QUALITY_STATES",
    "RECEIPT_SCHEMA", "TERMINAL_STATES", "build_receipt",
    "derive_proof_grade", "load_and_validate_receipt", "validate_receipt",
    "write_receipt",
]
