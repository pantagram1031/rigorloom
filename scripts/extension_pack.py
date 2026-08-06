#!/usr/bin/env python3
"""Install and verify immutable, data-only Rigorloom extension packs."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"
if str(PIPELINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS))

import personalization_ctl as pctl  # noqa: E402


SCHEMA = "rigorloom/extension-pack-v1"
REGISTRY_SCHEMA = "rigorloom/extension-registry-v1"
RECEIPT_SCHEMA = "rigorloom/extension-receipt-v1"
RIGORLOOM_API = 1
MANIFEST_NAME = "manifest.json"
RECEIPT_NAME = ".receipt.json"
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MANIFEST_KEYS = {
    "schema", "id", "version", "kind", "rigorloom_api", "priority",
    "description", "packs",
}


def _extensions_root(profile: Path) -> Path:
    return Path(profile) / "extensions"


def _registry_path(profile: Path) -> Path:
    return _extensions_root(profile) / "registry.json"


def _empty_registry() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "api": RIGORLOOM_API, "extensions": {}}


def _read_registry(profile: Path) -> dict[str, Any]:
    path = _registry_path(profile)
    if not path.exists():
        return _empty_registry()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"invalid extension registry: {path}")
    if data.get("api") != RIGORLOOM_API or not isinstance(data.get("extensions"), dict):
        raise ValueError(f"unsupported extension registry: {path}")
    return data


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_member(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("pack path must be a non-empty relative path")
    rel = Path(relative)
    if rel.is_absolute() or rel.drive or ".." in rel.parts:
        raise ValueError(f"pack path escapes extension root: {relative}")
    root_resolved = root.resolve()
    candidate = root / rel
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"pack path escapes extension root: {relative}") from exc
    current = root
    for part in rel.parts:
        current = current / part
        if current.exists() and _is_reparse(current):
            raise ValueError(f"pack path uses a symlink or reparse point: {relative}")
    return resolved


def _manifest(source: Path) -> dict[str, Any]:
    path = Path(source) / MANIFEST_NAME
    if not path.is_file():
        raise ValueError(f"extension manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("extension manifest must be a JSON object")
    unknown = sorted(set(data) - _MANIFEST_KEYS)
    if unknown:
        raise ValueError("unsupported manifest fields: " + ", ".join(unknown))
    missing = sorted(_MANIFEST_KEYS - set(data))
    if missing:
        raise ValueError("missing manifest fields: " + ", ".join(missing))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unsupported extension schema: {data.get('schema')!r}")
    if data.get("kind") != "data-pack":
        raise ValueError("extension kind must be 'data-pack'; executable extensions are forbidden")
    if data.get("rigorloom_api") != RIGORLOOM_API:
        raise ValueError(f"unsupported rigorloom_api: {data.get('rigorloom_api')!r}")
    if not isinstance(data.get("id"), str) or not _ID.fullmatch(data["id"]):
        raise ValueError("extension id must match [a-z0-9][a-z0-9._-]{2,63}")
    if not isinstance(data.get("version"), str) or not _SEMVER.fullmatch(data["version"]):
        raise ValueError("extension version must be semantic N.N.N")
    priority = data.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not -1000 <= priority <= 1000:
        raise ValueError("extension priority must be an integer from -1000 to 1000")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        raise ValueError("extension description must be a non-empty string")
    packs = data.get("packs")
    if not isinstance(packs, dict) or not packs:
        raise ValueError("extension packs must be a non-empty object")
    for pack_type, relative in packs.items():
        if pack_type not in pctl.DATA_EXTENSION_PACK_TYPES:
            raise ValueError(
                f"pack type is not allowed in a data-only extension: {pack_type}; "
                "backends and policy_floors require a separate trust model, and "
                "constants_allowlist relaxes deterministic checks (profile-level only)"
            )
        if not isinstance(relative, str):
            raise ValueError(f"pack path for {pack_type} must be a string")
    return data


def _source_fingerprint(manifest: dict[str, Any], files: dict[str, str]) -> str:
    identity = {"manifest": manifest, "files": files}
    return pctl.sha256_bytes(pctl.canonical_bytes(identity))


def validate_pack(source: Path) -> dict[str, Any]:
    source = Path(source).expanduser().resolve()
    manifest = _manifest(source)
    files = {MANIFEST_NAME: pctl.sha256(source / MANIFEST_NAME)}
    pack_rows: list[dict[str, Any]] = []
    for pack_type, relative in sorted(manifest["packs"].items()):
        path = _safe_member(source, relative)
        if not path.is_file():
            raise ValueError(f"declared pack file not found: {relative}")
        content = pctl.load_pack_file(path)
        declared = content.get("pack_type") if isinstance(content, dict) else None
        if declared is not None and declared != pack_type:
            raise ValueError(
                f"pack_type mismatch for {relative}: declares {declared!r}, expected {pack_type!r}"
            )
        errors = pctl.validate_instance(content, pctl.pack_schema(pack_type))
        if errors:
            raise ValueError(
                f"{relative} failed schema validation:\n  - " + "\n  - ".join(errors)
            )
        files[relative] = pctl.sha256(path)
        pack_rows.append({
            "pack_type": pack_type,
            "path": relative,
            "sha256": files[relative],
            "content_sha256": pctl.sha256_bytes(pctl.canonical_bytes(content)),
        })
    return {
        "ok": True,
        "source": str(source),
        "id": manifest["id"],
        "version": manifest["version"],
        "priority": manifest["priority"],
        "manifest": manifest,
        "files": dict(sorted(files.items())),
        "packs": pack_rows,
        "content_sha256": _source_fingerprint(manifest, dict(sorted(files.items()))),
    }


def _receipt_hash(receipt: dict[str, Any]) -> str:
    return pctl.sha256_bytes(pctl.canonical_bytes(receipt))


def _registry_record(
    registry: dict[str, Any], validated: dict[str, Any], receipt_hash: str, installed_at: str
) -> None:
    ext_id = validated["id"]
    version = validated["version"]
    entry = registry["extensions"].setdefault(ext_id, {"versions": {}})
    entry["active_version"] = version
    entry["priority"] = validated["priority"]
    entry.setdefault("versions", {})[version] = {
        "installed_at": installed_at,
        "receipt_sha256": receipt_hash,
    }


def _validate_registry_identity(extension_id: Any, version: Any) -> None:
    if not isinstance(extension_id, str) or not _ID.fullmatch(extension_id):
        raise ValueError(f"invalid extension id in registry: {extension_id!r}")
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ValueError(f"invalid extension version in registry: {extension_id}@{version!r}")


def install_pack(source: Path, profile: Path, dry_run: bool = False) -> dict[str, Any]:
    validated = validate_pack(source)
    profile = Path(profile).expanduser().resolve()
    target = _extensions_root(profile) / validated["id"] / validated["version"]
    if dry_run:
        return {
            "ok": True, "action": "install", "dry_run": True,
            "id": validated["id"], "version": validated["version"],
            "installed": str(target), "content_sha256": validated["content_sha256"],
        }

    registry = _read_registry(profile)
    if target.exists():
        receipt_path = target / RECEIPT_NAME
        if not receipt_path.is_file():
            raise ValueError(f"immutable version exists without a receipt: {target}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        entry = registry["extensions"].get(validated["id"])
        record = (entry.get("versions", {}).get(validated["version"])
                  if isinstance(entry, dict) else None)
        if not isinstance(record, dict):
            raise ValueError(
                f"immutable version exists but is not registered: {validated['id']}@{validated['version']}"
            )
        receipt_hash = _receipt_hash(receipt)
        if receipt_hash != record.get("receipt_sha256"):
            raise ValueError(
                f"immutable version receipt differs from registry: {validated['id']}@{validated['version']}"
            )
        expected_identity = {
            "schema": RECEIPT_SCHEMA,
            "id": validated["id"],
            "version": validated["version"],
            "priority": validated["priority"],
            "rigorloom_api": RIGORLOOM_API,
            "content_sha256": validated["content_sha256"],
            "files": validated["files"],
            "packs": validated["packs"],
        }
        actual_identity = {key: receipt.get(key) for key in expected_identity}
        if actual_identity != expected_identity:
            raise ValueError(
                f"immutable version differs from installed content: {validated['id']}@{validated['version']}"
            )
        for relative, expected in receipt.get("files", {}).items():
            installed_file = _safe_member(target, relative)
            if not installed_file.is_file() or pctl.sha256(installed_file) != expected:
                raise ValueError(
                    f"immutable version is locally modified: {validated['id']}@{validated['version']}/{relative}"
                )
        _registry_record(registry, validated, receipt_hash, receipt.get("installed_at", pctl.now()))
        pctl.write_json(_registry_path(profile), registry)
        return {
            "ok": True, "action": "already-installed", "dry_run": False,
            "id": validated["id"], "version": validated["version"],
            "installed": str(target), "receipt_sha256": receipt_hash,
        }

    extensions_root = _extensions_root(profile)
    extensions_root.mkdir(parents=True, exist_ok=True)
    stage = extensions_root / f".installing-{validated['id']}-{uuid.uuid4().hex}"
    installed_at = pctl.now()
    try:
        stage.mkdir()
        for relative in validated["files"]:
            source_file = _safe_member(Path(validated["source"]), relative)
            destination = stage / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination)
            if pctl.sha256(destination) != validated["files"][relative]:
                raise ValueError(f"extension source changed while installing: {relative}")
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "id": validated["id"],
            "version": validated["version"],
            "priority": validated["priority"],
            "rigorloom_api": RIGORLOOM_API,
            "installed_at": installed_at,
            "content_sha256": validated["content_sha256"],
            "files": validated["files"],
            "packs": validated["packs"],
        }
        pctl.write_json(stage / RECEIPT_NAME, receipt)
        receipt_hash = _receipt_hash(receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    _registry_record(registry, validated, receipt_hash, installed_at)
    try:
        pctl.write_json(_registry_path(profile), registry)
    except Exception:
        # The registry is the activation commit point. A failed commit must not
        # leave a fresh version looking installed but unreachable.
        if target.exists():
            shutil.rmtree(target)
        raise
    return {
        "ok": True, "action": "installed", "dry_run": False,
        "id": validated["id"], "version": validated["version"],
        "installed": str(target), "receipt_sha256": receipt_hash,
    }


def list_installed(profile: Path) -> dict[str, Any]:
    registry = _read_registry(Path(profile).expanduser().resolve())
    rows: list[dict[str, Any]] = []
    for ext_id, entry in sorted(registry["extensions"].items()):
        if not isinstance(entry, dict) or not isinstance(entry.get("versions"), dict):
            raise ValueError(f"invalid extension registry entry: {ext_id}")
        active_version = entry.get("active_version")
        _validate_registry_identity(ext_id, active_version)
        for version, record in sorted(entry["versions"].items()):
            _validate_registry_identity(ext_id, version)
            if not isinstance(record, dict):
                raise ValueError(f"invalid extension version record: {ext_id}@{version}")
            rows.append({
                "id": ext_id,
                "version": version,
                "priority": entry.get("priority", 0),
                "active": version == active_version,
                "receipt_sha256": record.get("receipt_sha256"),
            })
    return {"ok": True, "extensions": rows}


def doctor(profile: Path) -> dict[str, Any]:
    profile = Path(profile).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        registry = _read_registry(profile)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "extensions": []}
    try:
        rows = list_installed(profile)["extensions"]
    except (ValueError, OSError, json.JSONDecodeError, AttributeError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "extensions": []}
    for ext_id, entry in sorted(registry["extensions"].items()):
        active = entry.get("active_version")
        versions = entry.get("versions", {})
        try:
            _validate_registry_identity(ext_id, active)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if active not in versions:
            errors.append(f"{ext_id}: active version is not registered: {active!r}")
        for version, record in sorted(versions.items()):
            target = _extensions_root(profile) / ext_id / version
            receipt_path = target / RECEIPT_NAME
            if not receipt_path.is_file():
                errors.append(f"{ext_id}@{version}: receipt missing")
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{ext_id}@{version}: invalid receipt: {exc}")
                continue
            if receipt.get("schema") != RECEIPT_SCHEMA:
                errors.append(f"{ext_id}@{version}: receipt schema mismatch")
            if receipt.get("id") != ext_id or receipt.get("version") != version:
                errors.append(f"{ext_id}@{version}: receipt identity mismatch")
            actual_receipt = _receipt_hash(receipt)
            if actual_receipt != record.get("receipt_sha256"):
                errors.append(f"{ext_id}@{version}: receipt sha256 mismatch")
            receipt_files = receipt.get("files")
            if not isinstance(receipt_files, dict):
                errors.append(f"{ext_id}@{version}: receipt file map is invalid")
                continue
            for relative, expected in sorted(receipt_files.items()):
                try:
                    path = _safe_member(target, relative)
                except ValueError as exc:
                    errors.append(f"{ext_id}@{version}: {exc}")
                    continue
                if not path.is_file():
                    errors.append(f"{ext_id}@{version}: file missing: {relative}")
                elif pctl.sha256(path) != expected:
                    errors.append(f"{ext_id}@{version}: sha256 mismatch: {relative}")
            expected_files = {Path(name).as_posix() for name in receipt_files}
            expected_files.add(RECEIPT_NAME)
            if target.is_dir():
                actual_files = {
                    path.relative_to(target).as_posix()
                    for path in target.rglob("*") if path.is_file()
                }
                for extra in sorted(actual_files - expected_files):
                    errors.append(f"{ext_id}@{version}: unexpected installed file: {extra}")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "extensions": rows}


def activate(profile: Path, extension_id: str, version: str) -> dict[str, Any]:
    profile = Path(profile).expanduser().resolve()
    registry = _read_registry(profile)
    entry = registry["extensions"].get(extension_id)
    if not isinstance(entry, dict) or version not in entry.get("versions", {}):
        raise ValueError(f"extension version is not installed: {extension_id}@{version}")
    target = _extensions_root(profile) / extension_id / version
    receipt_path = target / RECEIPT_NAME
    if not receipt_path.is_file():
        raise ValueError(f"extension receipt is missing: {extension_id}@{version}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    record = entry["versions"][version]
    if (receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("id") != extension_id
            or receipt.get("version") != version):
        raise ValueError(f"extension receipt identity is invalid: {extension_id}@{version}")
    if _receipt_hash(receipt) != record.get("receipt_sha256"):
        raise ValueError(f"extension receipt is invalid: {extension_id}@{version}")
    for relative, expected in receipt.get("files", {}).items():
        path = _safe_member(target, relative)
        if not path.is_file() or pctl.sha256(path) != expected:
            raise ValueError(f"extension file is invalid: {extension_id}@{version}/{relative}")
    entry["active_version"] = version
    entry["priority"] = receipt.get("priority", 0)
    pctl.write_json(_registry_path(profile), registry)
    return {"ok": True, "id": extension_id, "active_version": version}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("source", type=Path)
    install = sub.add_parser("install")
    install.add_argument("source", type=Path)
    install.add_argument("--profile", type=Path, required=True)
    install.add_argument("--dry-run", action="store_true")
    listing = sub.add_parser("list")
    listing.add_argument("--profile", type=Path, required=True)
    health = sub.add_parser("doctor")
    health.add_argument("--profile", type=Path, required=True)
    active = sub.add_parser("activate")
    active.add_argument("extension_id")
    active.add_argument("version")
    active.add_argument("--profile", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            result = validate_pack(args.source)
        elif args.command == "install":
            result = install_pack(args.source, args.profile, args.dry_run)
        elif args.command == "list":
            result = list_installed(args.profile)
        elif args.command == "doctor":
            result = doctor(args.profile)
        else:
            result = activate(args.profile, args.extension_id, args.version)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
