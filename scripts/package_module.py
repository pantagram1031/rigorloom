#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-module packaging (v0.16 plan §3.5): standalone installable bundles.

``--module <name>`` emits ``rigorloom-<name>-<version>.zip`` containing the
distribution module's directory (payload + module.yaml) plus a generated
``MANIFEST.json`` (name, version = rigorloom project version, requires,
per-file sha256, provides summary) and an ``INSTALL.md`` (drop into
``modules/<name>/``, enable via the module_registry CLI).

``--module core`` emits the core bundle: ``engine/`` + the pipeline core
(``pipeline/scripts``, ``pipeline/references``) + ``studio/`` +
``modules/README.md`` (the distribution-module contract; no module
payloads) + ``pyproject.toml``/``LICENSE``.

Validation before anything is written:

- the module's ``module.yaml`` must validate (registry discovery is reused —
  a malformed declaration is a loud refusal, exit 2);
- every declared payload file must exist (dangling path = refusal, exit 2);
- ``privacy_scan`` runs over the staged bundle and any HARD finding refuses
  the build (exit 3) — a bundle is a distribution artifact, repo hygiene
  applies with no exceptions.

``--verify <bundle>`` re-hashes a built bundle (zip or extracted directory)
against its MANIFEST.json: any mismatch, missing, or unlisted file is a
loud failure (exit 3) — tamper detection, not a checksum suggestion.

Exit codes follow the checker convention: 0 ok, 2 usage/config refusal,
3 hard findings (privacy HARD / verification mismatch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

import module_registry  # noqa: E402
import privacy_scan  # noqa: E402

MANIFEST_NAME = "MANIFEST.json"
INSTALL_NAME = "INSTALL.md"
MANIFEST_SCHEMA = "rigorloom-bundle-manifest/v1"
CORE_NAME = "core"

# Never staged into a bundle: caches and VCS state.
_JUNK_DIRS = {"__pycache__", ".git", ".pytest_cache", "node_modules"}
_JUNK_SUFFIXES = {".pyc", ".pyo"}

# Core bundle contents (--module core): general document-engine surface
# only — no distribution-module payloads, no test suites.
_CORE_COMPONENTS = (
    "engine",
    "pipeline/scripts",
    "pipeline/references",
    "studio",
    "modules/README.md",
    "pyproject.toml",
    "LICENSE",
)
_CORE_EXCLUDED_DIRS = _JUNK_DIRS | {"tests"}


class PackageError(Exception):
    """Loud packaging refusal; ``exit_code`` follows the checker convention."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_junk(path: Path) -> bool:
    return (any(part in _JUNK_DIRS for part in path.parts)
            or path.suffix.lower() in _JUNK_SUFFIXES)


def _copy_tree(source: Path, target: Path, excluded_dirs: set[str]) -> None:
    def _ignore(directory: str, names: list[str]) -> set[str]:
        del directory
        return {name for name in names
                if name in excluded_dirs
                or Path(name).suffix.lower() in _JUNK_SUFFIXES}
    shutil.copytree(source, target, ignore=_ignore)


def _provides_summary(provides: dict[str, Any]) -> dict[str, Any]:
    """Compact human/machine summary of a module's contributions."""
    keyed = {
        "checkers": "name", "cli": "command", "run_modes": "name",
        "gate_kinds": "kind", "studio_panels": "id", "preflight": "name",
    }
    summary: dict[str, Any] = {}
    for key, field in keyed.items():
        entries = provides.get(key) or []
        if entries:
            summary[key] = [entry[field] for entry in entries]
    if provides.get("pack_types"):
        summary["pack_types"] = list(provides["pack_types"])
    if provides.get("playbooks"):
        summary["playbooks"] = len(provides["playbooks"])
    if provides.get("skill"):
        summary["skill"] = True
    return summary


def _staged_files(staging: Path) -> list[Path]:
    return sorted(
        path for path in staging.rglob("*")
        if path.is_file() and not _is_junk(path.relative_to(staging))
        and path.name != MANIFEST_NAME
    )


def _run_privacy_gate(staging: Path) -> None:
    findings = privacy_scan.scan_tree(staging.resolve(), None)
    hard = [f for f in findings if f["severity"] == "HARD"]
    if hard:
        lines = "\n".join(
            f"  {f['file']}:{f['line'] or '-'} {f['rule']}: {f['snippet']}"
            for f in hard[:20])
        raise PackageError(
            f"privacy_scan found {len(hard)} HARD finding(s) in the staged "
            f"bundle — refusing to package:\n{lines}", exit_code=3)


def _module_install_md(name: str, version: str, requires: str) -> str:
    return f"""# rigorloom-{name} {version} — distribution module bundle

Standalone installable bundle for the `{name}` distribution module
(requires rigorloom `{requires}`).

## Install

1. Copy `modules/{name}/` from this bundle into your rigorloom install's
   `modules/` directory (the whole directory, `module.yaml` included).
2. Enable it:

   ```sh
   python pipeline/scripts/module_registry.py write-enabled --names {name}
   ```

   (or `--all` to enable every discovered module; `enabled.yaml` is
   per-install state and is never committed.)
3. Verify: `python pipeline/scripts/module_registry.py list` must show the
   module under `enabled` with its contributions surfaced.

Presence is integration: enabling the module surfaces its checkers, CLI,
run modes, gate kinds, and studio panels with no further configuration.
Verify bundle integrity any time with
`python scripts/package_module.py --verify <this bundle>`.
"""


def _core_install_md(version: str) -> str:
    return f"""# rigorloom-core {version} — core bundle

The core document engine: `engine/`, the pipeline core
(`pipeline/scripts`, `pipeline/references`), `studio/`, and the
distribution-module contract (`modules/README.md`). No distribution-module
payloads are included — core ships alone and runs green alone (absence is
not failure).

## Install

1. Extract this bundle into an empty directory.
2. Install runtime dependencies as needed (`studio/requirements.txt` for
   the studio dashboard).
3. Add capability bundles later by installing distribution modules
   (`rigorloom-<name>-<version>.zip`) into `modules/` and enabling them via
   `python pipeline/scripts/module_registry.py write-enabled`.

Verify bundle integrity any time with
`python scripts/package_module.py --verify <this bundle>`.
"""


def _stage_module(name: str, staging: Path,
                  registry: "module_registry.ModuleRegistry") -> dict:
    discovered = registry.discover()  # loud on any malformed module.yaml
    if name not in discovered:
        raise PackageError(
            f"no distribution module named {name!r} under "
            f"{registry.modules_root} (discovered: {sorted(discovered)})")
    spec = discovered[name]
    # Reuse the registry's payload contract: every declared payload file
    # must exist — a dangling path is a refusal, not a silent skip.
    for relative in module_registry._declared_paths(spec.provides):
        if not spec.payload_path(relative).is_file():
            raise PackageError(
                f"distribution module '{name}': declared payload file is "
                f"missing: {relative}")
    _copy_tree(spec.root, staging / "modules" / name, _JUNK_DIRS)
    return {
        "requires": {"rigorloom": spec.requires},
        "provides": _provides_summary(spec.provides),
        "install_md": _module_install_md(
            name, registry.version, spec.requires),
    }


def _stage_core(staging: Path, repo_root: Path, version: str) -> dict:
    for component in _CORE_COMPONENTS:
        source = repo_root / component
        target = staging / component
        if source.is_dir():
            _copy_tree(source, target, _CORE_EXCLUDED_DIRS)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise PackageError(f"core component missing: {component}")
    # The verify tool itself ships with core so a target install can check
    # its own bundles.
    scripts_dir = staging / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), scripts_dir / "package_module.py")
    return {
        "requires": None,
        "provides": {"core_components": list(_CORE_COMPONENTS)},
        "install_md": _core_install_md(version),
    }


def build_bundle(
    name: str,
    out_dir: Path | str = REPO_ROOT / "dist",
    *,
    modules_root: Path | str | None = None,
    repo_root: Path | str = REPO_ROOT,
    version: str | None = None,
) -> Path:
    """Build one bundle zip; returns its path. Raises PackageError loudly."""
    repo_root = Path(repo_root)
    registry = module_registry.ModuleRegistry(
        Path(modules_root) if modules_root is not None
        else repo_root / "modules",
        version=version,
        pyproject=repo_root / "pyproject.toml",
    )
    bundle_version = registry.version
    out_dir = Path(out_dir)

    with tempfile.TemporaryDirectory(prefix="rigorloom-bundle-") as tmp:
        staging = Path(tmp) / f"rigorloom-{name}"
        staging.mkdir(parents=True)
        if name == CORE_NAME:
            meta = _stage_core(staging, repo_root, bundle_version)
        else:
            meta = _stage_module(name, staging, registry)

        # Privacy gate BEFORE the manifest exists: nothing HARD ships.
        _run_privacy_gate(staging)

        (staging / INSTALL_NAME).write_text(
            meta["install_md"], encoding="utf-8", newline="\n")
        files = [
            {"path": path.relative_to(staging).as_posix(),
             "sha256": _sha256_file(path)}
            for path in _staged_files(staging)
        ]
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "name": name,
            "version": bundle_version,
            "requires": meta["requires"],
            "provides": meta["provides"],
            "files": files,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")

        out_dir.mkdir(parents=True, exist_ok=True)
        bundle = out_dir / f"rigorloom-{name}-{bundle_version}.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
    return bundle


# ── verification (tamper detection) ─────────────────────────────────


def _bundle_contents(target: Path) -> tuple[dict, dict[str, bytes]]:
    """(manifest, {relative_path: bytes}) from a zip or extracted dir."""
    contents: dict[str, bytes] = {}
    if target.is_file() and target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                contents[info.filename.replace("\\", "/")] = (
                    archive.read(info))
    elif target.is_dir():
        for path in sorted(target.rglob("*")):
            if path.is_file() and not _is_junk(path.relative_to(target)):
                contents[path.relative_to(target).as_posix()] = (
                    path.read_bytes())
    else:
        raise PackageError(f"not a bundle zip or directory: {target}")
    raw = contents.pop(MANIFEST_NAME, None)
    if raw is None:
        raise PackageError(f"bundle has no {MANIFEST_NAME}: {target}")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"unreadable {MANIFEST_NAME}: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise PackageError(
            f"{MANIFEST_NAME} schema must be '{MANIFEST_SCHEMA}'")
    return manifest, contents


def verify_bundle(target: Path | str) -> tuple[dict, int]:
    """Re-hash a bundle against its manifest. Any drift is a hard failure."""
    manifest, contents = _bundle_contents(Path(target))
    listed = {entry["path"]: entry["sha256"]
              for entry in manifest.get("files", [])}
    problems = []
    for path, expected in sorted(listed.items()):
        data = contents.get(path)
        if data is None:
            problems.append({"path": path, "problem": "missing"})
        elif _sha256_bytes(data) != expected:
            problems.append({"path": path, "problem": "hash_mismatch"})
    for path in sorted(set(contents) - set(listed)):
        problems.append({"path": path, "problem": "not_in_manifest"})
    report = {
        "ok": not problems,
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "files": len(listed),
        "problems": problems,
    }
    return report, (0 if not problems else 3)


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify standalone rigorloom bundles "
                    "(per-distribution-module, or --module core).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--module", metavar="NAME",
                       help="distribution module name, or 'core'")
    group.add_argument("--verify", metavar="BUNDLE",
                       help="verify a built bundle (zip or extracted dir) "
                            "against its MANIFEST.json")
    parser.add_argument("--out", default=str(REPO_ROOT / "dist"),
                        help="output directory for bundle zips "
                             "(default: dist/)")
    parser.add_argument("--modules-root", default=None,
                        help="modules directory to package from "
                             "(default: <repo>/modules)")
    args = parser.parse_args(argv)

    try:
        if args.verify:
            report, code = verify_bundle(Path(args.verify))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return code
        bundle = build_bundle(
            args.module, Path(args.out),
            modules_root=args.modules_root)
    except (PackageError, module_registry.ModuleError) as exc:
        code = getattr(exc, "exit_code", 2)
        print(json.dumps({"ok": False, "error": str(exc)},
                         ensure_ascii=False))
        return code
    report, code = verify_bundle(bundle)
    print(json.dumps({"ok": code == 0, "bundle": str(bundle),
                      "files": report["files"]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
