#!/usr/bin/env python3
"""Frozen report compilation snapshot capture and mechanical XML worker.

Stdlib-only module separating one-shot report bundle capture/compilation
(``freeze_report_xml_request``) and measurement-config capture
(``freeze_report_measurement_settings``) from the mechanical XML worker
(``execute_frozen_xml_worker``).  The worker consumes only validated frozen
operations, resolved post-processing settings, and content-addressed snapshot
blobs; it never re-reads workspace source files or invokes the compiler or PDF
renderer.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import hashlib
import inspect
import io
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import build_report  # noqa: E402
import eqn  # noqa: E402
import style_diff  # noqa: E402
import tidy_hwpx  # noqa: E402
import xml_backend  # noqa: E402


RECIPE_ID = "rigorloom/report-xml/v1"
BACKEND_NAME = "report-xml"
OP_KIND = "report_assemble"
MANIFEST_SCHEMA = "rigorloom/report-xml-manifest/v1"
REQUEST_SCHEMA = "rigorloom/report-xml-frozen-request/v1"
MEASUREMENT_SCHEMA = "rigorloom/report-measurement-settings/v1"
SUPPORTED_XML_OPS = frozenset(xml_backend.SUPPORTED_OPS)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")

_BUILD_YAML_SELECTIONS = frozenset({
    "explicit",
    "explicit_missing",
    "discovered_bundle",
    "discovered_parent",
    "absent",
})
_ABSENT_REASONS = frozenset({"missing", "not_requested", "absent"})

_SETTINGS_KEYS = frozenset({
    "tidy_before",
    "tidy_after",
    "tidy_soft",
    "tidy_keep_map",
    "derived_tidy_anchors",
    "use_restore",
    "baseline_ref",
    "keep_with_next",
    "use_typeset_defaults",
    "profile_anchors",
})

_REQUEST_REQUIRED_KEYS = frozenset({
    "schema",
    "backend",
    "snapshot_dir",
    "manifest_digest",
    "manifest",
    "operation",
})
_REQUEST_OPTIONAL_KEYS = frozenset({"warnings", "counts", "anchors"})
_REQUEST_ALLOWED_KEYS = _REQUEST_REQUIRED_KEYS | _REQUEST_OPTIONAL_KEYS

_MANIFEST_KEYS = frozenset({"schema", "recipe_id", "inputs", "compiled", "settings"})
_MANIFEST_INPUT_KEYS = frozenset({
    "form", "content", "build_yaml", "form_profile", "baseline", "assets",
})
_MANIFEST_COMPILED_KEYS = frozenset({"ops", "anchors", "counts", "warnings"})

_DEFAULT_FILL = {
    "min_figures": 0,
    "target_pages": [1, 999],
    "bottom_white_max": 25.0,
    "max_gap_lines": 3.0,
}

_OP_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "goto_text": frozenset({"op", "text", "next_para", "cell_below"}),
    "insert_text": frozenset({"op", "text", "pt", "break_after", "segments"}),
    "insert_equation": frozenset(
        {"op", "latex", "hwpeqn", "display", "base_pt", "font"}
    ),
    "insert_table": frozenset(
        {"op", "data", "treat_as_char", "col_ratios", "font_pt", "caption"}
    ),
    "page_binding": frozenset({"op", "mode"}),
    "replace_all": frozenset({"op", "find", "replace"}),
    "insert_blank_before": frozenset({"op", "text"}),
    "insert_picture": frozenset({
        "op",
        "asset_ref",
        "width_mm",
        "width_hwpunit",
        "width_hwp",
        "width",
        "unit",
        "own_paragraph",
        "caption",
    }),
    "set_line_spacing": frozenset({"op", "percent", "all"}),
}


class FrozenReportError(Exception):
    """Base error with machine-readable code and optional details."""

    def __init__(self, code: str, message: str | None = None, **details: Any):
        self.code = code
        self.message = message or code
        self.details = dict(details)
        super().__init__(self.message)


class FrozenRequestError(FrozenReportError):
    """Raised when snapshot capture, digest check, or blob verification fails."""


class FrozenWorkerRefusal(FrozenReportError):
    """Raised when the frozen worker refuses an unsupported or invalid request."""


@dataclasses.dataclass
class XmlWorkerRunners:
    """Optional injectable execution hooks preserving fill_report spy behavior."""

    xml_edit: Callable[[Path, Path, Path], dict] | None = None
    tidy_hwpx: Callable[..., dict] | None = None
    restore_para_formats: Callable[[Path, Path], dict] | None = None
    keep_with_next: Callable[[Path, list[str]], dict] | None = None
    typeset_defaults: Callable[[Path, list[str]], dict] | None = None
    para_format_check: Callable[[Path, Path], dict] | None = None


@dataclasses.dataclass
class XmlWorkerResult:
    """Result returned by ``execute_frozen_xml_worker``."""

    ok: bool
    out_hwpx: Path
    manifest_digest: str
    source_form_sha256: str
    output_sha256: str
    edit_result: dict
    tidy_result: dict
    tidy_warnings: list[dict]
    restore_result: dict | None
    keep_with_next_result: dict | None
    typeset_result: dict | None
    para_verification: dict
    steps_executed: list[str]


class _NullBuffer:
    def write(self, _data: bytes) -> int:
        return len(_data)

    def flush(self) -> None:
        return None


class _NullStdout:
    def __init__(self) -> None:
        self.buffer = _NullBuffer()

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


def _reject_nonfinite(value: Any, path: str = "payload") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise FrozenWorkerRefusal(
            "nonfinite_number", f"{path} contains non-finite float"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FrozenWorkerRefusal(
                    "invalid_key", f"{path} keys must be strings"
                )
            _reject_nonfinite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_nonfinite(item, f"{path}[{index}]")


def canonical_json_bytes(payload: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for manifest hashing."""
    _reject_nonfinite(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_manifest_digest(manifest: dict) -> str:
    """Return the SHA-256 hex digest of a canonicalized report manifest."""
    if not isinstance(manifest, dict):
        raise FrozenRequestError("invalid_manifest", "manifest must be a dict")
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def _is_positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_nonneg_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_safe_basename(name: Any) -> bool:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name or ":" in name or "\x00" in name:
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return False
    return Path(name).name == name


def _validate_blob_ref(
    ref: Any,
    *,
    field_name: str,
    require_name: bool = False,
) -> tuple[str, int, str]:
    if not isinstance(ref, dict):
        raise FrozenWorkerRefusal(
            "invalid_blob_ref", f"{field_name} must be an object"
        )
    expected_keys = {"blob", "sha256", "bytes"}
    if require_name:
        expected_keys.add("name")
    extra = sorted(set(ref) - expected_keys)
    missing = sorted(expected_keys - set(ref))
    if extra or missing:
        raise FrozenWorkerRefusal(
            "invalid_blob_ref",
            f"{field_name} has invalid keys (extra={extra}, missing={missing})",
            extra=extra,
            missing=missing,
        )
    sha = ref["sha256"]
    if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
        raise FrozenWorkerRefusal(
            "invalid_blob_ref", f"{field_name}.sha256 must be 64-hex"
        )
    size = ref["bytes"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise FrozenWorkerRefusal(
            "invalid_blob_ref", f"{field_name}.bytes must be a positive int"
        )
    blob = ref["blob"]
    if not isinstance(blob, str) or "\\" in blob or blob.startswith("/"):
        raise FrozenWorkerRefusal(
            "invalid_blob_ref", f"{field_name}.blob must be relative blobs/<sha256>"
        )
    posix_parts = PurePosixPath(blob).parts
    if posix_parts != ("blobs", sha) or blob != f"blobs/{sha}":
        raise FrozenWorkerRefusal(
            "invalid_blob_ref",
            f"{field_name}.blob must equal blobs/{sha}",
        )
    if require_name and not _is_safe_basename(ref["name"]):
        raise FrozenWorkerRefusal(
            "invalid_blob_ref",
            f"{field_name}.name must be a single safe basename",
        )
    return sha, size, blob


def _validate_xml_op(op: Any, index: int) -> None:
    if not isinstance(op, dict):
        raise FrozenWorkerRefusal(
            "invalid_op", f"ops[{index}] must be an object", index=index
        )
    op_name = op.get("op")
    if not isinstance(op_name, str) or not op_name:
        raise FrozenWorkerRefusal(
            "invalid_op", f"ops[{index}].op must be a non-empty string", index=index
        )
    if op_name not in SUPPORTED_XML_OPS:
        raise FrozenWorkerRefusal(
            "unsupported_xml_op",
            f"unsupported XML operation at ops[{index}]: {op_name!r}",
            op=op_name,
            index=index,
        )
    allowed_keys = _OP_ALLOWED_KEYS[op_name]
    unknown = sorted(set(op) - allowed_keys)
    if unknown:
        raise FrozenWorkerRefusal(
            "unknown_op_field",
            f"ops[{index}] ({op_name}) carries unrecognized fields: {unknown}",
            op=op_name,
            unknown=unknown,
            index=index,
        )

    if op_name == "goto_text":
        if not isinstance(op.get("text"), str) or not op["text"]:
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].text must be a non-empty string"
            )
        for flag in ("next_para", "cell_below"):
            if flag in op and not isinstance(op[flag], bool):
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].{flag} must be bool"
                )
        return

    if op_name == "insert_text":
        if not isinstance(op.get("text"), str):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].text must be a string"
            )
        if "pt" in op and op["pt"] is not None and not _is_positive_number(op["pt"]):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].pt must be a positive number"
            )
        if "break_after" in op and not isinstance(op["break_after"], bool):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].break_after must be bool"
            )
        if "segments" in op and op["segments"] is not None:
            segs = op["segments"]
            if not isinstance(segs, list):
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].segments must be a list"
                )
            for sidx, seg in enumerate(segs):
                if not isinstance(seg, dict):
                    raise FrozenWorkerRefusal(
                        "invalid_op",
                        f"ops[{index}].segments[{sidx}] must be an object",
                    )
                extra_seg = sorted(set(seg) - {"text", "bold"})
                if extra_seg or not isinstance(seg.get("text"), str):
                    raise FrozenWorkerRefusal(
                        "invalid_op",
                        f"ops[{index}].segments[{sidx}] has invalid shape",
                    )
                if "bold" in seg and not isinstance(seg["bold"], bool):
                    raise FrozenWorkerRefusal(
                        "invalid_op",
                        f"ops[{index}].segments[{sidx}].bold must be bool",
                    )
        return

    if op_name == "insert_equation":
        _script, _warns, ok, reason = eqn.validate_equation_operation(op)
        if not ok:
            raise FrozenWorkerRefusal(
                "invalid_equation",
                f"ops[{index}] insert_equation failed validation: {reason}",
                reason=reason,
                index=index,
            )
        return

    if op_name == "insert_table":
        data = op.get("data")
        if (
            not isinstance(data, list)
            or not data
            or any(not isinstance(row, list) or not row for row in data)
        ):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].data must be a non-empty 2D list"
            )
        ncols = len(data[0])
        if any(len(row) != ncols for row in data):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].data rows must have equal length"
            )
        for row in data:
            for cell in row:
                if isinstance(cell, (dict, list, tuple)) or (
                    isinstance(cell, float) and not math.isfinite(cell)
                ):
                    raise FrozenWorkerRefusal(
                        "invalid_op", f"ops[{index}].data contains invalid cell value"
                    )
        if "treat_as_char" in op and not isinstance(op["treat_as_char"], bool):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].treat_as_char must be bool"
            )
        if "col_ratios" in op and op["col_ratios"] is not None:
            ratios = op["col_ratios"]
            if (
                not isinstance(ratios, list)
                or len(ratios) != ncols
                or not all(_is_positive_number(v) for v in ratios)
            ):
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].col_ratios is invalid"
                )
        if "font_pt" in op and op["font_pt"] is not None and not _is_positive_number(
            op["font_pt"]
        ):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].font_pt must be a positive number"
            )
        if "caption" in op and op["caption"] is not None and not isinstance(
            op["caption"], str
        ):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].caption must be a string or null"
            )
        return

    if op_name == "page_binding":
        if "mode" in op:
            mode = op["mode"]
            if not isinstance(mode, str) or mode.lower() not in {"submit", "book"}:
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].mode must be 'submit' or 'book'"
                )
        return

    if op_name == "replace_all":
        if not isinstance(op.get("find"), str) or not op["find"]:
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].find must be a non-empty string"
            )
        if not isinstance(op.get("replace"), str):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].replace must be a string"
            )
        return

    if op_name == "insert_blank_before":
        if not isinstance(op.get("text"), str) or not op["text"]:
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].text must be a non-empty string"
            )
        return

    if op_name == "insert_picture":
        if "path" in op:
            raise FrozenWorkerRefusal(
                "live_path_forbidden",
                f"ops[{index}] insert_picture must not carry a live path",
                index=index,
            )
        _validate_blob_ref(
            op.get("asset_ref"), field_name=f"ops[{index}].asset_ref", require_name=True
        )
        has_width = False
        for key in ("width_mm", "width_hwpunit", "width_hwp", "width"):
            if key in op and op[key] is not None:
                if not _is_positive_number(op[key]):
                    raise FrozenWorkerRefusal(
                        "invalid_op", f"ops[{index}].{key} must be positive"
                    )
                has_width = True
        if not has_width:
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}] insert_picture requires a width field"
            )
        if "unit" in op and op["unit"] is not None:
            unit = op["unit"]
            if not isinstance(unit, str) or unit.upper() not in {
                "MM", "MILLIMETER", "MILLIMETERS", "HWPUNIT",
            }:
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].unit is unsupported"
                )
        if "own_paragraph" in op and not isinstance(op["own_paragraph"], bool):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].own_paragraph must be bool"
            )
        if "caption" in op and op["caption"] is not None and not isinstance(
            op["caption"], str
        ):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].caption must be a string or null"
            )
        return

    if op_name == "set_line_spacing":
        if "percent" in op:
            pct = op["percent"]
            if isinstance(pct, bool) or not isinstance(pct, int) or pct <= 0:
                raise FrozenWorkerRefusal(
                    "invalid_op", f"ops[{index}].percent must be a positive int"
                )
        if "all" in op and not isinstance(op["all"], bool):
            raise FrozenWorkerRefusal(
                "invalid_op", f"ops[{index}].all must be bool"
            )
        return


def _is_str_list_or_none(value: Any) -> bool:
    return value is None or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )


def _validate_settings(settings: Any) -> None:
    if not isinstance(settings, dict):
        raise FrozenWorkerRefusal("invalid_settings", "settings must be an object")
    extra = sorted(set(settings) - _SETTINGS_KEYS)
    missing = sorted(_SETTINGS_KEYS - set(settings))
    if extra or missing:
        raise FrozenWorkerRefusal(
            "invalid_settings",
            f"settings has invalid keys (extra={extra}, missing={missing})",
            extra=extra,
            missing=missing,
        )
    for key in ("tidy_before", "tidy_after", "derived_tidy_anchors", "keep_with_next"):
        if not _is_str_list_or_none(settings[key]):
            raise FrozenWorkerRefusal(
                "invalid_settings", f"settings.{key} must be list[str] or null"
            )
    if not isinstance(settings["profile_anchors"], list) or not all(
        isinstance(item, str) for item in settings["profile_anchors"]
    ):
        raise FrozenWorkerRefusal(
            "invalid_settings", "settings.profile_anchors must be list[str]"
        )
    for key in ("tidy_soft", "use_restore", "use_typeset_defaults"):
        if not isinstance(settings[key], bool):
            raise FrozenWorkerRefusal(
                "invalid_settings", f"settings.{key} must be bool"
            )
    keep_map = settings["tidy_keep_map"]
    if keep_map is not None:
        if not isinstance(keep_map, dict) or not all(
            isinstance(k, str) and _is_nonneg_int(v) for k, v in keep_map.items()
        ):
            raise FrozenWorkerRefusal(
                "invalid_settings",
                "settings.tidy_keep_map must be dict[str, int] or null",
            )
    baseline_ref = settings["baseline_ref"]
    if settings["use_restore"]:
        if baseline_ref is None:
            raise FrozenWorkerRefusal(
                "invalid_settings",
                "settings.baseline_ref required when use_restore is true",
            )
        _validate_blob_ref(baseline_ref, field_name="settings.baseline_ref")
    elif baseline_ref is not None:
        raise FrozenWorkerRefusal(
            "invalid_settings",
            "settings.baseline_ref must be null when use_restore is false",
        )


def validate_report_assemble_op(op: Any) -> None:
    """Strictly validate the closed ``report_assemble`` operation shape."""
    if not isinstance(op, dict):
        raise FrozenWorkerRefusal("invalid_op", "operation must be an object")
    extra_top = sorted(set(op) - {"kind", "params"})
    missing_top = sorted({"kind", "params"} - set(op))
    if extra_top or missing_top:
        raise FrozenWorkerRefusal(
            "unknown_field",
            f"operation carries invalid top-level keys (extra={extra_top}, missing={missing_top})",
            extra=extra_top,
            missing=missing_top,
        )
    if op["kind"] != OP_KIND:
        raise FrozenWorkerRefusal(
            "unsupported_op_kind",
            f"expected kind={OP_KIND!r}, got {op['kind']!r}",
            kind=op["kind"],
        )
    params = op["params"]
    if not isinstance(params, dict):
        raise FrozenWorkerRefusal("invalid_params", "params must be an object")
    expected_params = {"recipe", "manifest_digest", "ops", "settings"}
    extra_p = sorted(set(params) - expected_params)
    missing_p = sorted(expected_params - set(params))
    if extra_p or missing_p:
        raise FrozenWorkerRefusal(
            "unknown_field",
            f"params carries invalid keys (extra={extra_p}, missing={missing_p})",
            extra=extra_p,
            missing=missing_p,
        )
    if params["recipe"] != RECIPE_ID:
        raise FrozenWorkerRefusal(
            "unknown_recipe",
            f"unsupported recipe {params['recipe']!r}",
            recipe=params["recipe"],
        )
    digest = params["manifest_digest"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise FrozenWorkerRefusal(
            "invalid_manifest_digest", "params.manifest_digest must be 64-hex"
        )
    ops = params["ops"]
    if not isinstance(ops, list):
        raise FrozenWorkerRefusal("invalid_params", "params.ops must be a list")
    _reject_nonfinite(params)
    for index, nested in enumerate(ops):
        _validate_xml_op(nested, index)
    _validate_settings(params["settings"])


def _validate_manifest_input_entry(entry: Any, *, field_name: str) -> None:
    if not isinstance(entry, dict) or not isinstance(entry.get("present"), bool):
        raise FrozenRequestError("invalid_manifest", f"{field_name} must specify present bool")
    if entry["present"]:
        expected = {"present", "blob", "sha256", "bytes"}
        if set(entry) != expected:
            raise FrozenRequestError("invalid_manifest", f"{field_name} has invalid keys")
        _validate_blob_ref(
            {k: entry[k] for k in ("blob", "sha256", "bytes")},
            field_name=field_name,
        )
    else:
        if set(entry) != {"present", "reason"} or entry["reason"] not in _ABSENT_REASONS:
            raise FrozenRequestError("invalid_manifest", f"{field_name} has invalid absence entry")


def _validate_manifest_build_yaml(entry: Any) -> None:
    if not isinstance(entry, dict) or not isinstance(entry.get("present"), bool):
        raise FrozenRequestError("invalid_manifest", "inputs.build_yaml must be an object")
    sel = entry.get("selection")
    if sel not in _BUILD_YAML_SELECTIONS:
        raise FrozenRequestError("invalid_manifest", f"invalid build_yaml selection {sel!r}")
    if entry["present"]:
        if sel not in {"explicit", "discovered_bundle", "discovered_parent"}:
            raise FrozenRequestError("invalid_manifest", "inconsistent build_yaml selection")
        if set(entry) != {"present", "selection", "blob", "sha256", "bytes"}:
            raise FrozenRequestError("invalid_manifest", "inputs.build_yaml has invalid keys")
        _validate_blob_ref(
            {k: entry[k] for k in ("blob", "sha256", "bytes")},
            field_name="inputs.build_yaml",
        )
    else:
        if sel not in {"explicit_missing", "absent"}:
            raise FrozenRequestError("invalid_manifest", "inconsistent absent build_yaml selection")
        if set(entry) != {"present", "selection", "reason"} or entry["reason"] not in _ABSENT_REASONS:
            raise FrozenRequestError("invalid_manifest", "inputs.build_yaml has invalid absence keys")


def validate_frozen_xml_request(request: Any) -> None:
    """Validate frozen request envelope, manifest digest, and closed operation."""
    if not isinstance(request, dict):
        raise FrozenRequestError("invalid_request", "request must be an object")
    extra = sorted(set(request) - _REQUEST_ALLOWED_KEYS)
    missing = sorted(_REQUEST_REQUIRED_KEYS - set(request))
    if extra or missing:
        raise FrozenRequestError(
            "invalid_request",
            f"request has invalid keys (extra={extra}, missing={missing})",
            extra=extra,
            missing=missing,
        )
    if request["schema"] != REQUEST_SCHEMA:
        raise FrozenRequestError(
            "invalid_request_schema",
            f"unsupported request schema {request['schema']!r}",
        )
    if request["backend"] != BACKEND_NAME:
        raise FrozenRequestError(
            "invalid_backend",
            f"unsupported backend {request['backend']!r}",
        )
    if not isinstance(request["snapshot_dir"], str) or not request["snapshot_dir"]:
        raise FrozenRequestError("invalid_request", "snapshot_dir must be non-empty str")

    operation = request["operation"]
    validate_report_assemble_op(operation)
    op_params = operation["params"]

    manifest = request["manifest"]
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise FrozenRequestError("invalid_manifest", "manifest keys mismatch")
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["recipe_id"] != RECIPE_ID:
        raise FrozenRequestError("invalid_manifest", "manifest schema/recipe mismatch")

    inputs = manifest["inputs"]
    if not isinstance(inputs, dict) or set(inputs) != _MANIFEST_INPUT_KEYS:
        raise FrozenRequestError("invalid_manifest", "manifest.inputs keys mismatch")
    if not inputs["form"].get("present") or not inputs["content"].get("present"):
        raise FrozenRequestError("invalid_manifest", "form and content must be present")
    _validate_manifest_input_entry(inputs["form"], field_name="inputs.form")
    _validate_manifest_input_entry(inputs["content"], field_name="inputs.content")
    _validate_manifest_build_yaml(inputs["build_yaml"])
    _validate_manifest_input_entry(inputs["form_profile"], field_name="inputs.form_profile")
    _validate_manifest_input_entry(inputs["baseline"], field_name="inputs.baseline")

    assets = inputs["assets"]
    if not isinstance(assets, list):
        raise FrozenRequestError("invalid_manifest", "inputs.assets must be a list")
    asset_blobs: set[tuple[str, str, int, str]] = set()
    for aidx, asset in enumerate(assets):
        if not isinstance(asset, dict) or set(asset) != {
            "rel_path", "name", "blob", "sha256", "bytes"
        }:
            raise FrozenRequestError(
                "invalid_manifest", f"inputs.assets[{aidx}] has invalid keys"
            )
        rel_path = asset["rel_path"]
        if not isinstance(rel_path, str) or not rel_path or "\\" in rel_path or rel_path.startswith("/"):
            raise FrozenRequestError(
                "invalid_manifest", f"inputs.assets[{aidx}].rel_path is invalid"
            )
        if any(part in {"", ".", ".."} for part in PurePosixPath(rel_path).parts):
            raise FrozenRequestError(
                "invalid_manifest", f"inputs.assets[{aidx}].rel_path escapes"
            )
        sha, size, blob = _validate_blob_ref(
            {k: asset[k] for k in ("blob", "sha256", "bytes", "name")},
            field_name=f"inputs.assets[{aidx}]",
            require_name=True,
        )
        asset_blobs.add((blob, sha, size, asset["name"]))

    compiled = manifest["compiled"]
    if not isinstance(compiled, dict) or set(compiled) != _MANIFEST_COMPILED_KEYS:
        raise FrozenRequestError("invalid_manifest", "manifest.compiled keys mismatch")
    if compiled["ops"] != op_params["ops"]:
        raise FrozenRequestError("invalid_manifest", "manifest.compiled.ops mismatch")
    if manifest["settings"] != op_params["settings"]:
        raise FrozenRequestError("invalid_manifest", "manifest.settings mismatch")
    for opt_key in ("warnings", "counts", "anchors"):
        if opt_key in request and request[opt_key] != compiled[opt_key]:
            raise FrozenRequestError(
                "invalid_manifest", f"request.{opt_key} diverges from manifest"
            )

    for op in op_params["ops"]:
        if op["op"] == "insert_picture":
            ref = op["asset_ref"]
            key = (ref["blob"], ref["sha256"], ref["bytes"], ref["name"])
            if key not in asset_blobs:
                raise FrozenRequestError(
                    "unmanifested_asset",
                    "insert_picture asset_ref is not listed in manifest.inputs.assets",
                )

    if op_params["settings"]["use_restore"]:
        if not inputs["baseline"].get("present"):
            raise FrozenRequestError(
                "invalid_manifest",
                "use_restore is true while inputs.baseline is absent",
            )
        b_ref = op_params["settings"]["baseline_ref"]
        for k in ("blob", "sha256", "bytes"):
            if b_ref[k] != inputs["baseline"][k]:
                raise FrozenRequestError(
                    "invalid_manifest",
                    "baseline_ref diverges from manifest.inputs.baseline",
                )

    computed = compute_manifest_digest(manifest)
    if (
        request["manifest_digest"] != computed
        or op_params["manifest_digest"] != computed
    ):
        raise FrozenRequestError(
            "manifest_digest_mismatch",
            "request manifest_digest does not match canonical manifest",
        )


def _anchor_is_filled_section(anchor: str, section_anchors: list[str] | None) -> bool:
    a_stripped = (anchor or "").strip()
    if not a_stripped or not section_anchors:
        return False
    for sec_anchor in section_anchors:
        norm = tidy_hwpx._normalize_ws(sec_anchor or "")
        if norm and (norm == a_stripped or norm.startswith(a_stripped)):
            return True
    return False


def derive_keep_map(
    anchors: list[str],
    blanks_before: dict[str, int],
    section_anchors: list[str] | None,
) -> dict[str, int]:
    """Compute per-anchor tidy keep_n matching fill_report._derive_keep_map."""
    if not section_anchors:
        return {a: int(blanks_before.get(a, 1)) for a in anchors}
    keep_map: dict[str, int] = {}
    filled_prev = False
    for a in anchors:
        keep_map[a] = 1 if filled_prev else int(blanks_before.get(a, 1))
        filled_prev = _anchor_is_filled_section(a, section_anchors)
    return keep_map


def _resolve_postprocess_settings(
    *,
    postprocess_build_yaml_text: str | None,
    form_profile_requested: bool,
    form_profile_obj: dict | None,
    section_anchors: list[str] | None,
    baseline_ref: dict | None,
    baseline_obj: dict | None,
) -> dict[str, Any]:
    explicit_before = None
    explicit_after = None
    keep_with_next = None
    if postprocess_build_yaml_text is not None:
        cfg = build_report.parse_build_yaml_text(postprocess_build_yaml_text)
        explicit_before = cfg.get("tidy_blank_before") or None
        explicit_after = cfg.get("tidy_blank_after") or None
        keep_with_next = cfg.get("keep_with_next") or None

    derived_tidy_anchors: list[str] | None = None
    tidy_keep_map: dict[str, int] | None = None
    if explicit_before or explicit_after:
        tidy_before = list(explicit_before) if explicit_before else None
        tidy_after = list(explicit_after) if explicit_after else None
        tidy_soft = False
    elif form_profile_obj and form_profile_obj.get("anchors"):
        anchors = list(form_profile_obj.get("anchors") or [])
        blanks_before = form_profile_obj.get("anchors_blanks_before") or {}
        tidy_before = list(anchors)
        tidy_after = None
        derived_tidy_anchors = list(anchors)
        tidy_keep_map = derive_keep_map(anchors, blanks_before, section_anchors)
        tidy_soft = True
    else:
        tidy_before = None
        tidy_after = None
        tidy_soft = False

    use_restore = bool(
        isinstance(baseline_obj, dict) and baseline_obj.get("para_formats")
    )
    use_typeset_defaults = bool(form_profile_requested)
    profile_anchors = (
        list(form_profile_obj.get("anchors") or [])
        if isinstance(form_profile_obj, dict)
        else []
    )
    return {
        "tidy_before": tidy_before,
        "tidy_after": tidy_after,
        "tidy_soft": tidy_soft,
        "tidy_keep_map": tidy_keep_map,
        "derived_tidy_anchors": derived_tidy_anchors,
        "use_restore": use_restore,
        "baseline_ref": dict(baseline_ref) if use_restore and baseline_ref else None,
        "keep_with_next": list(keep_with_next) if keep_with_next else None,
        "use_typeset_defaults": use_typeset_defaults,
        "profile_anchors": profile_anchors,
    }


def _stat_tuple(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(getattr(st, "st_dev", 0)),
        int(getattr(st, "st_ino", 0)),
        int(getattr(st, "st_size", 0)),
        int(getattr(st, "st_mtime_ns", 0)),
        int(getattr(st, "st_ctime_ns", 0)),
    )


def _capture_regular_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        st_before = path.stat()
    except OSError as exc:
        raise FrozenRequestError(
            f"missing_{label}", f"{label} could not be accessed: {path}"
        ) from exc
    if not stat.S_ISREG(st_before.st_mode):
        raise FrozenRequestError(
            f"invalid_{label}", f"{label} is not a regular file: {path}"
        )
    try:
        data = path.read_bytes()
        st_after = path.stat()
    except OSError as exc:
        raise FrozenRequestError(
            f"unreadable_{label}", f"{label} could not be read: {path}"
        ) from exc
    if _stat_tuple(st_before) != _stat_tuple(st_after) or len(data) != st_before.st_size:
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"{label} changed while reading: {path}",
            path=str(path),
        )
    sha256 = hashlib.sha256(data).hexdigest()
    return {
        "path": path,
        "label": label,
        "data": data,
        "sha256": sha256,
        "bytes": len(data),
        "stat": _stat_tuple(st_after),
    }


def _verify_captured_file(record: dict[str, Any]) -> None:
    path: Path = record["path"]
    try:
        st = path.stat()
    except OSError as exc:
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"{record['label']} disappeared or became unreadable during capture: {path}",
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"{record['label']} changed file type during capture: {path}",
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"{record['label']} became unreadable during capture: {path}",
        ) from exc
    if _stat_tuple(st) != record["stat"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"{record['label']} changed during capture: {path}",
            path=str(path),
        )


def _verify_still_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise FrozenRequestError(
            "input_changed_during_capture",
            f"candidate input state changed during capture: {path}",
        ) from exc
    raise FrozenRequestError(
        "input_changed_during_capture",
        f"previously absent input appeared during capture: {path}",
        path=str(path),
    )


def _resolve_bundle_figure(bundle_dir: Path, raw_file: Any) -> tuple[Path, str, str]:
    if not isinstance(raw_file, str) or not raw_file or "\x00" in raw_file:
        raise FrozenRequestError(
            "invalid_asset_path", f"invalid figure reference: {raw_file!r}"
        )
    if "\\" in raw_file or _DRIVE_PREFIX_RE.match(raw_file) or raw_file.startswith("/"):
        raise FrozenRequestError(
            "asset_path_escape",
            f"figure path must be relative inside bundle/figures: {raw_file!r}",
        )
    posix = PurePosixPath(raw_file)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise FrozenRequestError(
            "asset_path_escape",
            f"figure path escapes bundle/figures: {raw_file!r}",
        )
    safe_name = posix.parts[-1]
    if not _is_safe_basename(safe_name):
        raise FrozenRequestError(
            "invalid_asset_path",
            f"figure basename is unsafe: {safe_name!r}",
        )
    try:
        bundle_real = bundle_dir.resolve(strict=True)
    except OSError as exc:
        raise FrozenRequestError(
            "invalid_bundle_dir", f"bundle directory unavailable: {bundle_dir}"
        ) from exc
    figs_dir = bundle_dir / "figures"
    try:
        figs_real = figs_dir.resolve(strict=True)
        figs_real.relative_to(bundle_real)
    except (OSError, ValueError) as exc:
        raise FrozenRequestError(
            "asset_symlink_escape",
            f"bundle/figures directory missing or escapes bundle: {figs_dir}",
        ) from exc
    candidate = figs_dir.joinpath(*posix.parts)
    try:
        candidate.lstat()
    except FileNotFoundError as exc:
        raise FrozenRequestError(
            "missing_asset", f"figure asset missing: {candidate}"
        ) from exc
    except OSError as exc:
        raise FrozenRequestError(
            "unreadable_asset", f"figure asset cannot be inspected: {candidate}"
        ) from exc
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(figs_real)
    except (OSError, ValueError) as exc:
        raise FrozenRequestError(
            "asset_symlink_escape",
            f"figure asset escapes bundle/figures: {candidate}",
        ) from exc
    if not resolved.is_file():
        raise FrozenRequestError(
            "invalid_asset", f"figure asset is not a regular file: {candidate}"
        )
    rel_posix = "/".join(posix.parts)
    return candidate, rel_posix, safe_name


def _write_blob(blobs_dir: Path, sha256: str, data: bytes) -> dict[str, Any]:
    target = blobs_dir / sha256
    if target.is_symlink():
        raise FrozenRequestError(
            "blob_path_escape", f"blob target cannot be a symlink: {target}"
        )
    if target.exists():
        existing = target.read_bytes()
        if hashlib.sha256(existing).hexdigest() != sha256 or len(existing) != len(data):
            raise FrozenRequestError(
                "blob_collision", f"existing blob checksum mismatch at {target}"
            )
    else:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{sha256[:12]}-", suffix=".blob", dir=str(blobs_dir)
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
            os.replace(tmp_name, target)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
    return {"blob": f"blobs/{sha256}", "sha256": sha256, "bytes": len(data)}


def _invoke_capture_hook(hook: Callable[..., Any]) -> None:
    try:
        sig = inspect.signature(hook)
        positional = [
            p for p in sig.parameters.values()
            if p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        has_varargs = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL
            for p in sig.parameters.values()
        )
        if positional or has_varargs:
            hook("after_pass1")
        else:
            hook()
    except (TypeError, ValueError):
        hook()


def _parse_content_silently(content_text: str) -> tuple[dict, list]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            return build_report.parse_content(content_text)
        except SystemExit as exc:
            raw_out = buf.getvalue().strip()
            msg = None
            if raw_out:
                try:
                    err = json.loads(raw_out.splitlines()[-1])
                    if isinstance(err, dict) and err.get("error"):
                        msg = str(err["error"])
                except Exception:
                    msg = raw_out
            raise build_report.CompileReportError(
                msg or str(exc) or "parse_content failed",
                exit_code=(exc.code if isinstance(exc.code, int) else 2),
            ) from exc


def freeze_report_xml_request(
    form_path: str | Path,
    content_path: str | Path,
    snapshot_dir: str | Path,
    *,
    build_yaml_path: str | Path | None = None,
    form_profile_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    expected_form_sha256: str | None = None,
    compile_override: Callable[..., dict] | None = None,
    _capture_hook: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Capture consistent snapshots, compile once, and freeze a report_assemble request."""
    build_yaml_path = build_yaml_path or None
    form_profile_path = form_profile_path or None
    baseline_path = baseline_path or None
    form_p = Path(form_path)
    content_p = Path(content_path)
    snap_p = Path(snapshot_dir)
    if snap_p.is_symlink():
        raise FrozenRequestError(
            "invalid_snapshot_dir", f"snapshot_dir cannot be a symlink: {snap_p}"
        )

    captured_records: list[dict[str, Any]] = []
    absent_candidates: list[Path] = []

    # Pass 1: stat + read form and content.
    form_rec = _capture_regular_file(form_p, label="form")
    captured_records.append(form_rec)
    if expected_form_sha256 is not None and form_rec["sha256"] != expected_form_sha256:
        raise FrozenRequestError(
            "form_digest_mismatch",
            f"form sha256 {form_rec['sha256']} != expected {expected_form_sha256}",
            actual=form_rec["sha256"],
            expected=expected_form_sha256,
        )

    content_rec = _capture_regular_file(content_p, label="content")
    captured_records.append(content_rec)
    try:
        content_text = content_rec["data"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrozenRequestError(
            "invalid_content_encoding", f"content.md is not UTF-8: {exc}"
        ) from exc

    # Pass 1: preserve exact build.yaml discovery semantics.
    build_yaml_rec: dict[str, Any] | None = None
    if build_yaml_path is not None:
        by_p = Path(build_yaml_path)
        try:
            by_p.lstat()
        except FileNotFoundError:
            build_selection = "explicit_missing"
            absent_candidates.append(by_p)
        else:
            build_selection = "explicit"
            build_yaml_rec = _capture_regular_file(by_p, label="build_yaml")
            captured_records.append(build_yaml_rec)
    else:
        content_dir = content_p.resolve().parent
        cand_bundle = content_dir / "build.yaml"
        cand_parent = content_dir.parent / "build.yaml"
        try:
            cand_bundle.lstat()
        except FileNotFoundError:
            absent_candidates.append(cand_bundle)
            if cand_parent != cand_bundle:
                try:
                    cand_parent.lstat()
                except FileNotFoundError:
                    absent_candidates.append(cand_parent)
                    build_selection = "absent"
                else:
                    build_selection = "discovered_parent"
                    build_yaml_rec = _capture_regular_file(
                        cand_parent, label="build_yaml"
                    )
                    captured_records.append(build_yaml_rec)
            else:
                build_selection = "absent"
        else:
            build_selection = "discovered_bundle"
            build_yaml_rec = _capture_regular_file(cand_bundle, label="build_yaml")
            captured_records.append(build_yaml_rec)

    compiler_build_yaml_text: str | None = None
    if build_yaml_rec is not None:
        try:
            compiler_build_yaml_text = build_yaml_rec["data"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FrozenRequestError(
                "invalid_build_yaml_encoding", f"build.yaml is not UTF-8: {exc}"
            ) from exc
    postprocess_build_yaml_text = (
        compiler_build_yaml_text if build_selection == "explicit" else None
    )

    # Pass 1: optional form_profile.
    form_profile_rec: dict[str, Any] | None = None
    form_profile_requested = bool(form_profile_path)
    form_profile_reason = "not_requested"
    if form_profile_path is not None:
        fp_p = Path(form_profile_path)
        try:
            fp_p.lstat()
        except FileNotFoundError:
            form_profile_reason = "missing"
            absent_candidates.append(fp_p)
        else:
            form_profile_rec = _capture_regular_file(fp_p, label="form_profile")
            captured_records.append(form_profile_rec)
    form_profile_text = (
        form_profile_rec["data"].decode("utf-8", errors="replace")
        if form_profile_rec is not None
        else None
    )
    form_profile_obj = build_report.load_form_profile_text(form_profile_text)

    # Pass 1: optional baseline.
    baseline_rec: dict[str, Any] | None = None
    baseline_reason = "not_requested"
    if baseline_path is not None:
        bl_p = Path(baseline_path)
        try:
            bl_p.lstat()
        except FileNotFoundError:
            baseline_reason = "missing"
            absent_candidates.append(bl_p)
        else:
            baseline_rec = _capture_regular_file(bl_p, label="baseline")
            captured_records.append(baseline_rec)
    baseline_obj: dict | None = None
    if baseline_rec is not None:
        try:
            loaded_bl = json.loads(baseline_rec["data"].decode("utf-8"))
            if isinstance(loaded_bl, dict):
                baseline_obj = loaded_bl
        except (UnicodeDecodeError, json.JSONDecodeError):
            baseline_obj = None

    # Pass 1: identify and capture referenced figure assets before any hook.
    bundle_dir = content_p.parent
    fig_records: dict[str, dict[str, Any]] = {}
    parsed_sections: list | None = None
    if compile_override is None:
        _parsed_meta, parsed_sections = _parse_content_silently(content_text)
        for sec in parsed_sections:
            for blk in sec["blocks"]:
                if blk.get("kind") != "fig":
                    continue
                raw_file = blk.get("file")
                if not raw_file:
                    continue
                cand_path, rel_posix, safe_name = _resolve_bundle_figure(
                    bundle_dir, raw_file
                )
                if raw_file not in fig_records:
                    rec = _capture_regular_file(cand_path, label="asset")
                    rec["rel_path"] = rel_posix
                    rec["name"] = safe_name
                    fig_records[raw_file] = rec
                    captured_records.append(rec)

    if _capture_hook is not None:
        _invoke_capture_hook(_capture_hook)

    # Pass 2: re-stat & re-hash all captured files; verify absent stayed absent.
    for rec in captured_records:
        _verify_captured_file(rec)
    for absent_p in absent_candidates:
        _verify_still_absent(absent_p)

    # Compile ONCE from captured bytes (never re-reading live files).
    if compile_override is not None:
        compiled = compile_override(
            content_text=content_text,
            build_yaml_text=compiler_build_yaml_text,
            form_profile_obj=form_profile_obj,
            bundle_dir=bundle_dir,
        )
        raw_ops = copy.deepcopy(compiled["ops"])
        compiled_warnings = list(compiled.get("warnings") or [])
        compiled_anchors = list(compiled.get("anchors") or [])
        compiled_counts = dict(compiled.get("counts") or {})
        sections_for_keep = compiled.get("sections")
        if sections_for_keep is None:
            try:
                _m, sections_for_keep = _parse_content_silently(content_text)
            except build_report.CompileReportError:
                sections_for_keep = None
        section_anchors = (
            [s["anchor"] for s in sections_for_keep]
            if sections_for_keep is not None
            else None
        )
    else:
        compiled = build_report.compile_bundle_text(
            content_text,
            build_yaml_text=compiler_build_yaml_text,
            form_profile_obj=form_profile_obj,
            bundle_dir=bundle_dir,
        )
        raw_ops = copy.deepcopy(compiled["ops"])
        compiled_warnings = list(compiled["warnings"])
        compiled_anchors = list(compiled["anchors"])
        compiled_counts = dict(compiled["counts"])
        section_anchors = [s["anchor"] for s in compiled["sections"]]

    # Materialize snapshot directory and write content-addressed blobs.
    snap_p.mkdir(parents=True, exist_ok=True)
    snap_real = snap_p.resolve(strict=True)
    blobs_dir = snap_real / "blobs"
    if blobs_dir.is_symlink():
        raise FrozenRequestError(
            "blob_path_escape", f"blobs dir cannot be a symlink: {blobs_dir}"
        )
    blobs_dir.mkdir(exist_ok=True)

    form_blob_ref = _write_blob(blobs_dir, form_rec["sha256"], form_rec["data"])
    content_blob_ref = _write_blob(
        blobs_dir, content_rec["sha256"], content_rec["data"]
    )

    if build_yaml_rec is not None:
        by_blob_ref = _write_blob(
            blobs_dir, build_yaml_rec["sha256"], build_yaml_rec["data"]
        )
        build_yaml_input: dict[str, Any] = {
            "present": True,
            "selection": build_selection,
            **by_blob_ref,
        }
    else:
        build_yaml_input = {
            "present": False,
            "selection": build_selection,
            "reason": "missing" if build_selection == "explicit_missing" else "absent",
        }

    if form_profile_rec is not None:
        fp_blob_ref = _write_blob(
            blobs_dir, form_profile_rec["sha256"], form_profile_rec["data"]
        )
        form_profile_input: dict[str, Any] = {"present": True, **fp_blob_ref}
    else:
        form_profile_input = {"present": False, "reason": form_profile_reason}

    if baseline_rec is not None:
        bl_blob_ref = _write_blob(
            blobs_dir, baseline_rec["sha256"], baseline_rec["data"]
        )
        baseline_input: dict[str, Any] = {"present": True, **bl_blob_ref}
    else:
        bl_blob_ref = None
        baseline_input = {"present": False, "reason": baseline_reason}

    # Rewrite insert_picture["path"] -> insert_picture["asset_ref"] using captured blobs.
    frozen_ops: list[dict[str, Any]] = []
    manifest_assets_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if compile_override is None and parsed_sections is not None:
        fig_blocks = [
            blk
            for sec in compiled["sections"]
            for blk in sec["blocks"]
            if blk.get("kind") == "fig"
        ]
        fig_iter = iter(fig_blocks)
    else:
        fig_iter = iter(())

    for op in raw_ops:
        op_copy = copy.deepcopy(op)
        if op_copy.get("op") == "insert_picture":
            raw_path = op_copy.pop("path", None)
            if compile_override is None:
                fig_blk = next(fig_iter, None)
                if fig_blk is None or not fig_blk.get("file"):
                    raise FrozenRequestError(
                        "asset_mapping_error",
                        "compiled insert_picture did not match a captured FIG block",
                    )
                rec = fig_records[fig_blk["file"]]
            else:
                if not isinstance(raw_path, str) or not raw_path:
                    raise FrozenRequestError(
                        "invalid_asset_path",
                        "compile_override insert_picture missing path",
                    )
                figs_real = (bundle_dir / "figures").resolve()
                p_obj = Path(raw_path)
                try:
                    rel_part = p_obj.resolve(strict=True).relative_to(figs_real).as_posix()
                except (OSError, ValueError) as exc:
                    raise FrozenRequestError(
                        "asset_path_escape",
                        f"compile_override insert_picture path escapes bundle/figures: {raw_path}",
                    ) from exc
                cand_path, rel_posix, safe_name = _resolve_bundle_figure(
                    bundle_dir, rel_part
                )
                rec = _capture_regular_file(cand_path, label="asset")
                rec["rel_path"] = rel_posix
                rec["name"] = safe_name

            blob_ref = _write_blob(blobs_dir, rec["sha256"], rec["data"])
            op_copy["asset_ref"] = {
                **blob_ref,
                "name": rec["name"],
            }
            manifest_assets_by_key[(rec["rel_path"], rec["sha256"])] = {
                "rel_path": rec["rel_path"],
                "name": rec["name"],
                **blob_ref,
            }
        frozen_ops.append(op_copy)

    manifest_assets = [
        manifest_assets_by_key[key] for key in sorted(manifest_assets_by_key)
    ]

    settings = _resolve_postprocess_settings(
        postprocess_build_yaml_text=postprocess_build_yaml_text,
        form_profile_requested=form_profile_requested,
        form_profile_obj=form_profile_obj,
        section_anchors=section_anchors,
        baseline_ref=bl_blob_ref,
        baseline_obj=baseline_obj,
    )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "recipe_id": RECIPE_ID,
        "inputs": {
            "form": {"present": True, **form_blob_ref},
            "content": {"present": True, **content_blob_ref},
            "build_yaml": build_yaml_input,
            "form_profile": form_profile_input,
            "baseline": baseline_input,
            "assets": manifest_assets,
        },
        "compiled": {
            "ops": frozen_ops,
            "anchors": compiled_anchors,
            "counts": compiled_counts,
            "warnings": compiled_warnings,
        },
        "settings": settings,
    }
    manifest_digest = compute_manifest_digest(manifest)
    operation = {
        "kind": OP_KIND,
        "params": {
            "recipe": RECIPE_ID,
            "manifest_digest": manifest_digest,
            "ops": copy.deepcopy(frozen_ops),
            "settings": copy.deepcopy(settings),
        },
    }
    request = {
        "schema": REQUEST_SCHEMA,
        "backend": BACKEND_NAME,
        "snapshot_dir": str(snap_real),
        "manifest_digest": manifest_digest,
        "manifest": manifest,
        "operation": operation,
        "warnings": list(compiled_warnings),
        "counts": dict(compiled_counts),
        "anchors": list(compiled_anchors),
    }
    validate_frozen_xml_request(request)
    return request


def freeze_report_measurement_settings(
    *,
    build_yaml_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    pdf_cmd: str | list[str] | tuple[str, ...] | None = None,
    renderer_id: str | None = None,
    pdf_timeout: float = 120.0,
    calibration: dict | None = None,
    fig_count: int | None = None,
    guide_strings: list[str] | None = None,
    spacing_skip_pages: list[int] | set[int] | None = None,
    gap_skip_pages: list[int] | set[int] | None = None,
    bottom_skip_pages: list[int] | set[int] | None = None,
    fill_overrides: dict | None = None,
) -> dict[str, Any]:
    """Capture rendering and layout-measurement settings separately from report_assemble."""
    build_yaml_path = build_yaml_path or None
    baseline_path = baseline_path or None
    fill: dict[str, Any] = dict(_DEFAULT_FILL)
    build_yaml_info: dict[str, Any] = {"present": False, "reason": "not_requested"}
    if build_yaml_path is not None:
        by_p = Path(build_yaml_path)
        if by_p.exists():
            rec = _capture_regular_file(by_p, label="build_yaml")
            cfg = build_report.parse_build_yaml_text(
                rec["data"].decode("utf-8")
            )
            for key, val in (cfg.get("fill") or {}).items():
                fill[key] = val
            build_yaml_info = {
                "present": True,
                "sha256": rec["sha256"],
                "bytes": rec["bytes"],
            }
        else:
            build_yaml_info = {"present": False, "reason": "missing"}
    if fill_overrides:
        for key, val in fill_overrides.items():
            fill[key] = val

    tp = fill.get("target_pages") or _DEFAULT_FILL["target_pages"]
    if not (isinstance(tp, list) and len(tp) == 2):
        raise FrozenRequestError(
            "invalid_fill_settings",
            f"build.yaml fill.target_pages는 [lo,hi]여야 함: {tp!r}",
        )
    fill["target_pages"] = [int(tp[0]), int(tp[1])]
    fill["min_figures"] = int(fill["min_figures"])
    fill["bottom_white_max"] = float(fill["bottom_white_max"])
    fill["max_gap_lines"] = float(fill["max_gap_lines"])

    baseline_info: dict[str, Any] = {"present": False, "reason": "not_requested"}
    if baseline_path is not None:
        bl_p = Path(baseline_path)
        if bl_p.exists():
            bl_rec = _capture_regular_file(bl_p, label="baseline")
            baseline_info = {
                "present": True,
                "sha256": bl_rec["sha256"],
                "bytes": bl_rec["bytes"],
            }
        else:
            baseline_info = {"present": False, "reason": "missing"}

    return {
        "schema": MEASUREMENT_SCHEMA,
        "proof_grade_policy": "advisory" if pdf_cmd else "none",
        "pdf_cmd": (
            list(pdf_cmd) if isinstance(pdf_cmd, (list, tuple)) else pdf_cmd
        ),
        "renderer_id": renderer_id,
        "pdf_timeout": float(pdf_timeout),
        "calibration": dict(calibration) if calibration is not None else None,
        "fill": fill,
        "fig_count": int(fig_count) if fig_count is not None else None,
        "guide_strings": list(guide_strings) if guide_strings is not None else None,
        "spacing_skip_pages": (
            sorted(spacing_skip_pages) if spacing_skip_pages else None
        ),
        "gap_skip_pages": sorted(gap_skip_pages) if gap_skip_pages else None,
        "bottom_skip_pages": (
            sorted(bottom_skip_pages) if bottom_skip_pages else None
        ),
        "build_yaml": build_yaml_info,
        "baseline": baseline_info,
    }


def _read_verified_blob(snap_root: Path, ref: dict[str, Any]) -> bytes:
    sha_expected, size_expected, blob_rel = _validate_blob_ref(
        ref, field_name="blob_ref", require_name=False
    ) if set(ref) == {"blob", "sha256", "bytes"} else _validate_blob_ref(
        ref, field_name="blob_ref", require_name=True
    )
    try:
        snap_st = snap_root.lstat()
    except OSError as exc:
        raise FrozenRequestError(
            "invalid_snapshot_dir", f"snapshot_dir unreadable: {snap_root}"
        ) from exc
    if stat.S_ISLNK(snap_st.st_mode) or not stat.S_ISDIR(snap_st.st_mode):
        raise FrozenRequestError(
            "invalid_snapshot_dir",
            f"snapshot_dir must be a non-symlink directory: {snap_root}",
        )
    snap_real = snap_root.resolve(strict=True)
    blobs_dir = snap_root / "blobs"
    try:
        blobs_st = blobs_dir.lstat()
    except OSError as exc:
        raise FrozenRequestError(
            "missing_blob", f"blobs directory missing in snapshot: {blobs_dir}"
        ) from exc
    if stat.S_ISLNK(blobs_st.st_mode) or not stat.S_ISDIR(blobs_st.st_mode):
        raise FrozenRequestError(
            "blob_path_escape", f"blobs directory cannot be a symlink: {blobs_dir}"
        )
    target = snap_root / blob_rel
    try:
        leaf_st = target.lstat()
    except FileNotFoundError as exc:
        raise FrozenRequestError(
            "missing_blob", f"snapshot blob missing: {blob_rel}"
        ) from exc
    except OSError as exc:
        raise FrozenRequestError(
            "missing_blob", f"snapshot blob unreadable: {blob_rel}"
        ) from exc
    if stat.S_ISLNK(leaf_st.st_mode) or not stat.S_ISREG(leaf_st.st_mode):
        raise FrozenRequestError(
            "blob_path_escape", f"snapshot blob must be a non-symlink file: {blob_rel}"
        )
    try:
        target.resolve(strict=True).relative_to(snap_real)
    except (OSError, ValueError) as exc:
        raise FrozenRequestError(
            "blob_path_escape", f"snapshot blob escapes snapshot_dir: {blob_rel}"
        ) from exc

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(target), flags)
    try:
        with os.fdopen(fd, "rb") as stream:
            data = stream.read()
    except OSError as exc:
        raise FrozenRequestError(
            "unreadable_blob", f"failed reading blob {blob_rel}: {exc}"
        ) from exc

    if len(data) != size_expected or hashlib.sha256(data).hexdigest() != sha_expected:
        raise FrozenRequestError(
            "blob_digest_mismatch",
            f"blob digest or byte size mismatch for {blob_rel}",
            blob=blob_rel,
            expected_sha256=sha_expected,
            expected_bytes=size_expected,
            actual_bytes=len(data),
        )
    return data


def _default_xml_edit(form_path: Path, ops_path: Path, out_hwpx: Path) -> dict:
    class _CapturedBufferStdout:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()

        def write(self, text: str) -> int:
            return self.buffer.write(text.encode("utf-8"))

        def flush(self) -> None:
            return None

    fake_stdout = _CapturedBufferStdout()
    saved_stdout = sys.stdout
    sys.stdout = fake_stdout
    try:
        rc = xml_backend.main([
            "edit",
            "--file",
            str(form_path),
            "--ops",
            str(ops_path),
            "--save-as",
            str(out_hwpx),
            "--json",
        ])
    finally:
        sys.stdout = saved_stdout
    raw = fake_stdout.buffer.getvalue().decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise FrozenWorkerRefusal(
            "xml_edit_failed", f"xml_backend output parse failed: {raw[:300]}"
        ) from exc
    if rc != 0 or not payload.get("ok"):
        unsupported = payload.get("unsupported", [])
        anchors_missing = payload.get("anchors_missing", [])
        if unsupported:
            code = "xml_backend_unsupported"
        elif anchors_missing:
            code = "anchors_missing"
        else:
            code = "xml_edit_failed"
        raise FrozenWorkerRefusal(
            code,
            f"xml_backend edit failed: unsupported={unsupported} anchors_missing={anchors_missing}",
            unsupported=unsupported,
            anchors_missing=anchors_missing,
        )
    return payload


def _call_tidy_quiet(
    hwpx_path: Path,
    before_anchors: list[str],
    after_anchors: list[str],
    keep_map: dict[str, int] | None = None,
) -> dict:
    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        return tidy_hwpx.tidy_hwpx(
            hwpx_path,
            before_anchors,
            after_anchors,
            keep=1,
            out_path=hwpx_path,
            keep_map=keep_map,
        )
    finally:
        sys.stdout = saved_stdout


def _default_tidy_hwpx(
    hwpx_path: Path,
    before_anchors: list[str] | None,
    after_anchors: list[str] | None,
    soft: bool = False,
    keep_map: dict[str, int] | None = None,
) -> dict:
    keep_map = keep_map or {}
    if not soft:
        try:
            return _call_tidy_quiet(
                hwpx_path,
                before_anchors or [],
                after_anchors or [],
                keep_map=keep_map,
            )
        except SystemExit as exc:
            raise FrozenWorkerRefusal(
                "tidy_failed",
                f"tidy_hwpx failed (exit {exc.code}): before={before_anchors} after={after_anchors}",
            ) from exc

    removed: dict[str, int] = {}
    warnings: list[dict[str, str]] = []
    for anchor in before_anchors or []:
        try:
            res = _call_tidy_quiet(hwpx_path, [anchor], [], keep_map=keep_map)
            removed.update(res.get("removed", {}))
        except SystemExit:
            warnings.append({
                "anchor": anchor,
                "direction": "before",
                "reason": "not found or ambiguous — skipped (auto-derived)",
            })
    for anchor in after_anchors or []:
        try:
            res = _call_tidy_quiet(hwpx_path, [], [anchor], keep_map=keep_map)
            removed.update(res.get("removed", {}))
        except SystemExit:
            warnings.append({
                "anchor": anchor,
                "direction": "after",
                "reason": "not found or ambiguous — skipped (auto-derived)",
            })
    return {"ok": True, "removed": removed, "warnings": warnings}


def _default_restore_para_formats(hwpx_path: Path, baseline_path: Path) -> dict:
    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        return tidy_hwpx.restore_para_formats(
            hwpx_path, baseline_path, out_path=hwpx_path
        )
    except SystemExit as exc:
        raise FrozenWorkerRefusal(
            "restore_para_formats_failed",
            f"restore_para_formats failed (exit {exc.code})",
        ) from exc
    finally:
        sys.stdout = saved_stdout


def _default_keep_with_next(hwpx_path: Path, prefixes: list[str]) -> dict:
    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        return tidy_hwpx.apply_keep_with_next(
            hwpx_path, prefixes or [], out_path=hwpx_path
        )
    except SystemExit as exc:
        raise FrozenWorkerRefusal(
            "keep_with_next_failed",
            f"apply_keep_with_next failed (exit {exc.code}): prefixes={prefixes}",
        ) from exc
    finally:
        sys.stdout = saved_stdout


def _default_typeset_defaults(hwpx_path: Path, anchors: list[str]) -> dict:
    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        return tidy_hwpx.apply_typeset_defaults(
            hwpx_path, anchors or [], out_path=hwpx_path
        )
    except SystemExit as exc:
        raise FrozenWorkerRefusal(
            "typeset_defaults_failed",
            f"apply_typeset_defaults failed (exit {exc.code}): anchors={anchors}",
        ) from exc
    finally:
        sys.stdout = saved_stdout


def _default_para_format_check(hwpx_path: Path, form_path: Path) -> dict:
    try:
        return style_diff.check_para_formats(form_path, hwpx_path)
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise FrozenWorkerRefusal(
            "para_format_check_failed",
            f"style_diff --check-para-formats failed: {exc}",
        ) from exc


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}-", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def execute_frozen_xml_worker(
    request: dict[str, Any],
    out_hwpx: str | Path,
    *,
    snapshot_dir: str | Path | None = None,
    form_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    legacy_ops_out: str | Path | None = None,
    runners: XmlWorkerRunners | None = None,
) -> XmlWorkerResult:
    """Execute one frozen ``report_assemble`` XML request without re-compiling."""
    validate_frozen_xml_request(request)

    snap_root = (
        Path(snapshot_dir)
        if snapshot_dir is not None
        else Path(request["snapshot_dir"])
    )
    manifest = request["manifest"]
    params = request["operation"]["params"]
    settings = params["settings"]
    form_input = manifest["inputs"]["form"]
    form_ref = {
        "blob": form_input["blob"],
        "sha256": form_input["sha256"],
        "bytes": form_input["bytes"],
    }

    if form_path is not None:
        live_form = _capture_regular_file(Path(form_path), label="form")
        if live_form["sha256"] != form_ref["sha256"]:
            raise FrozenRequestError(
                "form_digest_mismatch",
                f"form_path digest {live_form['sha256']} != frozen {form_ref['sha256']}",
                actual=live_form["sha256"],
                expected=form_ref["sha256"],
            )

    form_bytes = _read_verified_blob(snap_root, form_ref)
    baseline_bytes: bytes | None = None
    if settings["use_restore"]:
        baseline_bytes = _read_verified_blob(snap_root, settings["baseline_ref"])

    staged_ops = copy.deepcopy(params["ops"])
    staged_asset_blobs: list[tuple[int, str, bytes]] = []
    for idx, op in enumerate(staged_ops):
        if op.get("op") == "insert_picture":
            asset_ref = op.pop("asset_ref")
            asset_bytes = _read_verified_blob(snap_root, asset_ref)
            staged_asset_blobs.append((idx, asset_ref["name"], asset_bytes))

    active_runners = runners or XmlWorkerRunners()
    run_edit = active_runners.xml_edit or _default_xml_edit
    run_tidy = active_runners.tidy_hwpx or _default_tidy_hwpx
    run_restore = active_runners.restore_para_formats or _default_restore_para_formats
    run_kwn = active_runners.keep_with_next or _default_keep_with_next
    run_typeset = active_runners.typeset_defaults or _default_typeset_defaults
    run_para_check = active_runners.para_format_check or _default_para_format_check

    def _run_in_work_dir(work_root: Path) -> XmlWorkerResult:
        staged_form = work_root / "source_form.hwpx"
        staged_form.write_bytes(form_bytes)

        for idx, asset_name, asset_bytes in staged_asset_blobs:
            asset_dest = work_root / "assets" / str(idx) / asset_name
            asset_dest.parent.mkdir(parents=True, exist_ok=True)
            asset_dest.write_bytes(asset_bytes)
            staged_ops[idx]["path"] = str(asset_dest)

        staged_ops_path = work_root / "ops.json"
        ops_json_text = json.dumps(staged_ops, ensure_ascii=False)
        staged_ops_path.write_text(ops_json_text, encoding="utf-8")

        if legacy_ops_out is not None:
            legacy_p = Path(legacy_ops_out)
            legacy_p.parent.mkdir(parents=True, exist_ok=True)
            legacy_p.write_text(ops_json_text, encoding="utf-8")

        staged_baseline: Path | None = None
        if baseline_bytes is not None:
            staged_baseline = work_root / "baseline.json"
            staged_baseline.write_bytes(baseline_bytes)

        staged_candidate = work_root / "candidate.hwpx"
        steps_executed: list[str] = []

        # 1. xml_edit
        edit_result = run_edit(staged_form, staged_ops_path, staged_candidate)
        steps_executed.append("xml_edit")

        # 2. tidy_hwpx (always executed in XML path, even when anchors are empty/None)
        tidy_result = run_tidy(
            staged_candidate,
            settings["tidy_before"],
            settings["tidy_after"],
            soft=settings["tidy_soft"],
            keep_map=settings["tidy_keep_map"],
        )
        steps_executed.append("tidy_hwpx")
        tidy_warnings = list((tidy_result or {}).get("warnings") or [])

        # 3. optional restore_para_formats
        restore_result: dict | None = None
        if settings["use_restore"]:
            assert staged_baseline is not None
            restore_result = run_restore(staged_candidate, staged_baseline)
            steps_executed.append("restore_para_formats")

        # 4. optional keep_with_next
        keep_with_next_result: dict | None = None
        if settings["keep_with_next"]:
            keep_with_next_result = run_kwn(
                staged_candidate, settings["keep_with_next"]
            )
            steps_executed.append("keep_with_next")

        # 5. optional typeset_defaults
        typeset_result: dict | None = None
        if settings["use_typeset_defaults"]:
            typeset_result = run_typeset(
                staged_candidate, settings["profile_anchors"]
            )
            steps_executed.append("typeset_defaults")

        # 6. para_format_check
        para_verification = run_para_check(staged_candidate, staged_form)
        steps_executed.append("para_format_check")

        out_bytes = staged_candidate.read_bytes()
        out_path = Path(out_hwpx)
        _atomic_write_bytes(out_path, out_bytes)
        output_sha256 = hashlib.sha256(out_bytes).hexdigest()

        return XmlWorkerResult(
            ok=True,
            out_hwpx=out_path,
            manifest_digest=request["manifest_digest"],
            source_form_sha256=form_ref["sha256"],
            output_sha256=output_sha256,
            edit_result=dict(edit_result or {}),
            tidy_result=dict(tidy_result or {}),
            tidy_warnings=tidy_warnings,
            restore_result=(
                dict(restore_result) if restore_result is not None else None
            ),
            keep_with_next_result=(
                dict(keep_with_next_result)
                if keep_with_next_result is not None
                else None
            ),
            typeset_result=(
                dict(typeset_result) if typeset_result is not None else None
            ),
            para_verification=dict(para_verification or {}),
            steps_executed=steps_executed,
        )

    if work_dir is not None:
        wroot = Path(work_dir)
        wroot.mkdir(parents=True, exist_ok=True)
        return _run_in_work_dir(wroot)

    with tempfile.TemporaryDirectory(prefix="report-xml-worker-") as tmp_dir:
        return _run_in_work_dir(Path(tmp_dir))
