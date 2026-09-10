# -*- coding: utf-8 -*-
"""Consumer installer for Rigorloom (DIST-INSTALL-03).

Installs Rigorloom engine and distribution modules from pre-built bundles
(core, style, report ZIPs) without requiring a git checkout or importing
evals/cleanroom.py. Trusted wheel code implements manifest verification,
zip-slip rejection, atomic sibling swap, and optional skill provisioning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_SCHEMA = "rigorloom-bundle-manifest/v1"
SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_INTERNAL = 4


class InstallError(Exception):
    """Structured installation failure mapped to runtime exit codes."""

    def __init__(self, exit_code: int, error_code: str, message: str,
                 data: dict[str, Any] | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code
        self.message = message
        self.data = data or {}


def _emit(payload: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2,
                                sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()
    return code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_zip_traversal(name: str, bundle_name: str) -> None:
    norm = name.replace("\\", "/")
    if norm.startswith("/") or norm.startswith("\\"):
        raise InstallError(EXIT_REFUSED, "tamper_detected",
                           f"{bundle_name}: absolute path in zip entry: {name!r}")
    if ":" in norm or re.match(r"^[a-zA-Z]:", norm):
        raise InstallError(EXIT_REFUSED, "tamper_detected",
                           f"{bundle_name}: drive letter or scheme in zip entry: {name!r}")
    parts = PurePosixPath(norm).parts
    if any(p in ("..", "") for p in parts if p != "."):
        if any(p == ".." for p in parts):
            raise InstallError(EXIT_REFUSED, "tamper_detected",
                               f"{bundle_name}: directory traversal '..' in zip entry: {name!r}")


def verify_bundle_zip(zip_path: Path) -> dict[str, Any]:
    """Verify zip bundle against its MANIFEST.json in trusted wheel code.

    Refuses hash mismatch, missing files, extra unlisted files, traversal
    attempts, duplicate entries, and collision attacks with EXIT_REFUSED (exit 3).
    """
    if not zip_path.is_file():
        raise InstallError(EXIT_USAGE, "invalid_params",
                           f"bundle file not found: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path) as archive:
            # Check duplicate archive member names
            raw_members = [info.filename for info in archive.infolist() if not info.is_dir()]
            if len(raw_members) != len(set(raw_members)):
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: duplicate archive member names detected")

            # Check case-fold / normalized destination collisions
            norm_names = [n.replace("\\", "/").lower() for n in raw_members]
            if len(norm_names) != len(set(norm_names)):
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: case-fold/normalized destination collision in archive members")

            # Check directory/file prefix collisions (e.g. member 'foo' and 'foo/bar')
            sorted_norms = sorted(norm_names)
            for i in range(len(sorted_norms) - 1):
                prefix = sorted_norms[i] + "/"
                if sorted_norms[i + 1].startswith(prefix):
                    raise InstallError(EXIT_REFUSED, "tamper_detected",
                                       f"{zip_path.name}: directory/file prefix collision in archive members: "
                                       f"{sorted_norms[i]} and {sorted_norms[i+1]}")

            members = {
                info.filename.replace("\\", "/"): info
                for info in archive.infolist()
                if not info.is_dir()
            }
            if "MANIFEST.json" not in members:
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: missing MANIFEST.json — not a rigorloom bundle")
            try:
                raw_manifest = archive.read(members["MANIFEST.json"])
                manifest = json.loads(raw_manifest.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: unreadable MANIFEST.json: {exc}")

            if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: MANIFEST.json schema must be '{MANIFEST_SCHEMA}'")

            # Validate name, version, files
            name = manifest.get("name")
            if not isinstance(name, str) or not name.strip():
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: MANIFEST.json missing required 'name'")
            version = manifest.get("version")
            if not isinstance(version, str) or not version.strip():
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: MANIFEST.json missing required 'version'")
            files_list = manifest.get("files")
            if not isinstance(files_list, list):
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: MANIFEST.json 'files' must be an array")

            # Validate each entry and check for duplicate manifest paths
            manifest_paths: list[str] = []
            listed: dict[str, str] = {}
            for idx, entry in enumerate(files_list):
                if not isinstance(entry, dict):
                    raise InstallError(EXIT_REFUSED, "tamper_detected",
                                       f"{zip_path.name}: manifest files[{idx}] is not an object")
                p = entry.get("path")
                if not isinstance(p, str) or not p.strip():
                    raise InstallError(EXIT_REFUSED, "tamper_detected",
                                       f"{zip_path.name}: manifest files[{idx}] missing valid 'path'")
                h = entry.get("sha256")
                if not isinstance(h, str) or not SHA256_HEX_RE.fullmatch(h):
                    raise InstallError(EXIT_REFUSED, "tamper_detected",
                                       f"{zip_path.name}: manifest files[{idx}] path '{p}' has invalid sha256 (must be 64-hex)")
                manifest_paths.append(p)
                listed[p] = h.lower()

            if len(manifest_paths) != len(set(manifest_paths)):
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: duplicate path in MANIFEST.json files[]")

            problems: list[dict[str, str]] = []

            # Check every member for traversal / zip-slip
            for m_name in members:
                _check_zip_traversal(m_name, zip_path.name)

            # Verify sha256 for all declared files
            for path, expected_hash in sorted(listed.items()):
                info = members.get(path)
                if info is None:
                    problems.append({"path": path, "problem": "missing"})
                else:
                    data = archive.read(info)
                    if _sha256_bytes(data).lower() != expected_hash:
                        problems.append({"path": path, "problem": "hash_mismatch"})

            # Detect undeclared files in archive
            for m_name in sorted(set(members) - set(listed)):
                if m_name != "MANIFEST.json":
                    problems.append({"path": m_name, "problem": "not_in_manifest"})

            if problems:
                raise InstallError(
                    EXIT_REFUSED, "tamper_detected",
                    f"{zip_path.name}: integrity verification failed against MANIFEST.json",
                    data={"bundle": zip_path.name, "problems": problems}
                )
            return manifest
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as exc:
        raise InstallError(EXIT_REFUSED, "tamper_detected",
                           f"{zip_path.name}: corrupted zip file: {exc}")


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    """Extract zip entries with strict containment checking."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target_resolved = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            _check_zip_traversal(name, zip_path.name)
            dest = (target_dir / name).resolve()
            try:
                dest.relative_to(target_resolved)
            except ValueError:
                raise InstallError(EXIT_REFUSED, "tamper_detected",
                                   f"{zip_path.name}: traversal escape detected: {name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)


class SiblingLock:
    """Lock file sibling to engine-root preventing concurrent modifications."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.acquired = False
        self.token = str(uuid.uuid4())

    def acquire(self) -> None:
        if self.lock_path.exists():
            owner_info = "unknown"
            try:
                owner_info = self.lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise InstallError(
                EXIT_REFUSED, "lock_held",
                f"install lock held: {self.lock_path}\n"
                f"Lock info:\n{owner_info}\n"
                "Another installation is in progress or a previous installation did not release the lock. "
                "Verify no install process is running and manually remove the lock file if stale."
            )
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with open(fd, "w", encoding="utf-8") as f:
                f.write(f"token={self.token}\npid={os.getpid()}\ntime={time.time()}\n")
            self.acquired = True
        except FileExistsError:
            owner_info = "unknown"
            try:
                owner_info = self.lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise InstallError(
                EXIT_REFUSED, "lock_held",
                f"install lock held: {self.lock_path}\n"
                f"Lock info:\n{owner_info}\n"
                "Another installation is in progress or a previous installation did not release the lock. "
                "Verify no install process is running and manually remove the lock file if stale."
            )

    def release(self) -> None:
        if self.acquired and self.lock_path.is_file():
            try:
                content = self.lock_path.read_text(encoding="utf-8")
                if f"token={self.token}" in content:
                    self.lock_path.unlink()
            except OSError:
                pass


def _enable_modules_in_staging(staging_dir: Path, module_names: list[str]) -> dict[str, Any]:
    reg_script = staging_dir / "pipeline" / "scripts" / "module_registry.py"
    if not reg_script.is_file():
        raise InstallError(EXIT_REFUSED, "installation_corrupt",
                           f"module_registry.py missing from extracted core bundle at {reg_script}")
    pyproject = staging_dir / "pyproject.toml"
    modules_root = staging_dir / "modules"
    selector = ["--names", *module_names] if module_names else ["--none"]
    cmd = [
        sys.executable, str(reg_script),
        "--modules-root", str(modules_root),
        "--pyproject", str(pyproject),
        "write-enabled",
        *selector
    ]
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "RIGORLOOM_BACKENDS", "RIGORLOOM_PROFILE_ROOT"):
        env.pop(k, None)
    env["RIGORLOOM_ROOT"] = str(staging_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise InstallError(EXIT_REFUSED, "module_enablement_failed",
                           f"module_registry failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {}


def _probe_in_staging(staging_dir: Path) -> dict[str, Any]:
    probe_script = staging_dir / "engine" / "scripts" / "probe.py"
    if not probe_script.is_file():
        raise InstallError(EXIT_REFUSED, "installation_corrupt",
                           f"probe.py missing from extracted core bundle at {probe_script}")
    cmd = [sys.executable, str(probe_script), "--json"]
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    env["RIGORLOOM_ROOT"] = str(staging_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise InstallError(EXIT_REFUSED, "probe_failed",
                           f"engine probe failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {}


def _probe_origin_split(engine_root: Path, target_python: str | None = None) -> dict[str, Any]:
    exe = target_python or sys.executable
    # The path travels in the ENVIRONMENT, never in the source text. Embedding
    # it produced a SyntaxError for any root containing an apostrophe
    # (C:\\Users\\O'Brien\\...) or ending in a backslash (a drive root such as
    # C:\\), because a raw string cannot end with one — and the child's non-zero
    # exit was then reported as "containment_breach", which named a security
    # failure for what was a quoting bug. RIGORLOOM_ROOT is already set to
    # engine_root below, so there is nothing to interpolate.
    code = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "engine_root = Path(os.environ['RIGORLOOM_ROOT']).resolve()\n"
        "sys.path.insert(0, str(engine_root / 'pipeline' / 'scripts'))\n"
        "import module_registry, privacy_scan\n"
        "reg_file = Path(module_registry.__file__).resolve()\n"
        "priv_file = Path(privacy_scan.__file__).resolve()\n"
        "assert reg_file.is_relative_to(engine_root), f'module_registry leaked: {reg_file}'\n"
        "assert priv_file.is_relative_to(engine_root), f'privacy_scan leaked: {priv_file}'\n"
        "print(json.dumps({'ok': True, 'registry': str(reg_file), 'sys_executable': sys.executable}))\n"
    )
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "RIGORLOOM_BACKENDS", "RIGORLOOM_PROFILE_ROOT"):
        env.pop(k, None)
    env["RIGORLOOM_ROOT"] = str(engine_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([exe, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise InstallError(EXIT_REFUSED, "containment_breach",
                           f"origin probe failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"ok": True}


def _provision_skills(engine_root: Path, skills_root: Path) -> dict[str, Any]:
    sync_script = engine_root / "scripts" / "sync_local.py"
    if not sync_script.is_file():
        raise InstallError(EXIT_REFUSED, "installation_corrupt",
                           f"sync_local.py missing from installed core at {sync_script}")
    target_install = skills_root / "rigorloom-hwp"
    target_install.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = engine_root / f".skill_sync_manifest_{uuid.uuid4().hex}.yaml"
    manifest_content = (
        f'install_root: "{str(target_install).replace(chr(92), "/")}"\n'
        'merge_skill_fragments: true\n'
        'source_map:\n'
        '  - from: "skill/SKILL.md"\n'
        '    to: "SKILL.md"\n'
        '  - from: "skill/references"\n'
        '    to: "references"\n'
        '  - from: "engine/scripts"\n'
        '    to: "engine/scripts"\n'
        '  - from: "pipeline/scripts"\n'
        '    to: "pipeline/scripts"\n'
        '  - from: "pipeline/adapters_impl"\n'
        '    to: "pipeline/adapters_impl"\n'
        'exclude:\n'
        '  - "__pycache__"\n'
        '  - "*.pyc"\n'
        '  - ".sync*"\n'
    )
    manifest_path.write_text(manifest_content, encoding="utf-8")
    try:
        cmd = [
            sys.executable, str(sync_script),
            "--manifest", str(manifest_path),
            "--checkout-root", str(engine_root)
        ]
        env = dict(os.environ)
        for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
            env.pop(k, None)
        env["RIGORLOOM_ROOT"] = str(engine_root)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise InstallError(EXIT_REFUSED, "skill_install_failed",
                               f"sync_local.py failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
        return {"installed": True, "path": str(target_install)}
    finally:
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError:
                pass


def _find_bundle(bundles_dir: Path, name: str) -> Path:
    candidates = sorted(bundles_dir.glob(f"rigorloom-{name}-*.zip"))
    if not candidates:
        candidate_exact = bundles_dir / f"rigorloom-{name}.zip"
        if candidate_exact.is_file():
            return candidate_exact
        raise InstallError(EXIT_USAGE, "invalid_params",
                           f"required bundle for '{name}' not found in {bundles_dir} "
                           "(pass --modules none to install core only)")
    if len(candidates) > 1:
        # sorted() is a STRING sort over a dotted version, so 0.9.0 sorts after
        # 0.17.0 and "newest" would silently install the older bundle while
        # reporting success. Choosing for the operator here is the failure mode,
        # not the ambiguity, so the ambiguity is what gets reported.
        raise InstallError(
            EXIT_USAGE, "invalid_params",
            f"{len(candidates)} bundles for '{name}' in {bundles_dir}: "
            f"{[c.name for c in candidates]}. Filename order is not version "
            "order, so the installer will not choose for you — leave exactly "
            "one, or point --bundles-dir at a directory that has one.")
    return candidates[0]


def run_install(args: argparse.Namespace) -> int:
    """Execute consumer install workflow."""
    staging_dir: Path | None = None
    lock: SiblingLock | None = None
    try:
        engine_root = Path(args.engine_root).resolve()
        bundles_dir = Path(args.bundles_dir).resolve()

        if not bundles_dir.is_dir():
            raise InstallError(EXIT_USAGE, "invalid_params",
                               f"--bundles-dir does not exist or is not a directory: {bundles_dir}")

        raw_modules = getattr(args, "modules", "style,report")
        if raw_modules is None:
            raw_modules = "style,report"
        if raw_modules.strip().lower() in ("", "none"):
            module_names = []
        else:
            module_names = [m.strip() for m in raw_modules.split(",") if m.strip()]
            if "report" in module_names and "style" not in module_names:
                module_names.insert(0, "style")

        skills_root: Path | None = None
        if getattr(args, "skills_root", None):
            skills_root = Path(args.skills_root).resolve()
            if skills_root.exists():
                # Even if empty, refuse before mutating engine!
                manual_cmd = (
                    f"python {engine_root / 'scripts' / 'sync_local.py'} "
                    f"--manifest {engine_root / 'my-skill-manifest.yaml'} "
                    f"--checkout-root {engine_root}"
                )
                raise InstallError(
                    EXIT_USAGE, "invalid_params",
                    f"--skills-root already exists: {skills_root}. "
                    "The installer will not overwrite an existing skills directory. "
                    f"To sync skills into an existing directory, run:\n"
                    f"  {manual_cmd} --dry-run\n"
                    f"  {manual_cmd}"
                )

        replace = bool(getattr(args, "replace", False))
        if engine_root.exists() and any(engine_root.iterdir()):
            if not replace:
                raise InstallError(
                    EXIT_USAGE, "invalid_params",
                    f"--engine-root already exists and is not empty ({engine_root}); "
                    "pass --replace to replace an existing install"
                )
            has_inspect = (engine_root / "engine" / "scripts" / "form_inspect.py").is_file()
            has_registry = (engine_root / "pipeline" / "scripts" / "module_registry.py").is_file()
            if not (has_inspect and has_registry):
                raise InstallError(
                    EXIT_USAGE, "invalid_params",
                    f"--engine-root exists and is not empty ({engine_root}), but does not appear "
                    "to be a prior rigorloom install (missing form_inspect.py or module_registry.py)"
                )

        # Locate required bundles
        core_zip = _find_bundle(bundles_dir, "core")
        module_zips = {name: _find_bundle(bundles_dir, name) for name in module_names}

        # Sibling lock and staging directory on the SAME volume
        parent_dir = engine_root.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        lock = SiblingLock(parent_dir / f"{engine_root.name}.sync.lock")
        lock.acquire()

        staging_dir = parent_dir / f"{engine_root.name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Verify all bundles in trusted wheel code before extraction
        verify_bundle_zip(core_zip)
        for name, mod_zip in module_zips.items():
            verify_bundle_zip(mod_zip)

        # Extract core bundle via scratch directory and isolate control files
        core_scratch = staging_dir / ".core-scratch"
        _safe_extract_zip(core_zip, core_scratch)
        bundles_ctrl = staging_dir / ".bundles"
        core_ctrl = bundles_ctrl / "core"
        core_ctrl.mkdir(parents=True, exist_ok=True)
        for control in ("MANIFEST.json", "INSTALL.md"):
            src = core_scratch / control
            if src.is_file():
                shutil.move(str(src), str(core_ctrl / control))
        for item in list(core_scratch.iterdir()):
            shutil.move(str(item), str(staging_dir / item.name))
        shutil.rmtree(core_scratch, ignore_errors=True)

        # Extract each module bundle via its own scratch, verify modules/<name>/ payload, and move
        for name, mod_zip in module_zips.items():
            mod_scratch = staging_dir / f".module-scratch-{name}"
            _safe_extract_zip(mod_zip, mod_scratch)
            payload = mod_scratch / "modules" / name
            if not payload.is_dir():
                shutil.rmtree(mod_scratch, ignore_errors=True)
                raise InstallError(
                    EXIT_REFUSED, "tamper_detected",
                    f"{mod_zip.name}: module bundle missing required modules/{name}/ payload"
                )
            mod_ctrl = bundles_ctrl / name
            mod_ctrl.mkdir(parents=True, exist_ok=True)
            for control in ("MANIFEST.json", "INSTALL.md"):
                src = mod_scratch / control
                if src.is_file():
                    shutil.move(str(src), str(mod_ctrl / control))
            dest_module = staging_dir / "modules" / name
            dest_module.parent.mkdir(parents=True, exist_ok=True)
            if dest_module.exists():
                shutil.rmtree(dest_module, ignore_errors=True)
            shutil.move(str(payload), str(dest_module))
            shutil.rmtree(mod_scratch, ignore_errors=True)

        # Configure modules in staging
        _enable_modules_in_staging(staging_dir, module_names)

        # Capability probe smoke check in staging
        _probe_in_staging(staging_dir)

        # Atomic swap via rename
        bak_dir = parent_dir / f"{engine_root.name}.bak-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        prior_existed = engine_root.exists()
        if prior_existed:
            try:
                os.rename(str(engine_root), str(bak_dir))
            except OSError as exc:
                raise InstallError(
                    EXIT_REFUSED, "engine_root_locked",
                    f"cannot rename existing --engine-root (possibly locked by a running process): {exc}"
                )

        try:
            os.rename(str(staging_dir), str(engine_root))
            staging_dir = None  # moved successfully
        except OSError as exc:
            # Restore backup if swap failed
            if prior_existed and bak_dir.exists():
                try:
                    os.rename(str(bak_dir), str(engine_root))
                except Exception as rb_exc:
                    raise InstallError(
                        EXIT_INTERNAL, "swap_and_rollback_failed",
                        f"Failed to swap staging to {engine_root} ({exc}); rollback of prior install also failed ({rb_exc}). "
                        f"Preserved backup at {bak_dir}, staging at {staging_dir}."
                    )
            raise InstallError(
                EXIT_REFUSED, "swap_failed",
                f"failed to swap staging directory into place: {exc}"
            )

        # Post-swap steps: origin split and optional skills
        try:
            _probe_origin_split(engine_root)

            skills_info: dict[str, Any] | None = None
            if skills_root is not None:
                skills_info = _provision_skills(engine_root, skills_root)
        except Exception as post_exc:
            # Post-swap failure: rollback engine!
            try:
                if engine_root.exists():
                    shutil.rmtree(engine_root, ignore_errors=True)
                if prior_existed and bak_dir.exists():
                    os.rename(str(bak_dir), str(engine_root))
            except Exception as rb_exc:
                raise InstallError(
                    EXIT_INTERNAL, "post_swap_rollback_failed",
                    f"Post-swap step failed: {post_exc}. Rollback of engine also failed ({rb_exc}). "
                    f"Preserved backup at {bak_dir}, engine at {engine_root}."
                )
            if isinstance(post_exc, InstallError):
                raise post_exc
            raise InstallError(
                EXIT_REFUSED, "post_swap_failed",
                f"Post-swap step failed: {post_exc}. Prior engine restored from {bak_dir}."
                if prior_existed else f"Post-swap step failed: {post_exc}. Cleaned new engine at {engine_root}."
            )

        # SUCCESS: Do NOT delete bak_dir! Leave for operator recovery.
        result_payload = {
            "engine_root": str(engine_root),
            "modules": module_names,
            "backup_path": str(bak_dir) if prior_existed and bak_dir.exists() else None,
            "skills_installed": bool(skills_info and skills_info.get("installed")),
            "skills_path": skills_info.get("path") if skills_info else None,
        }
        return _emit({"ok": True, "command": "install", "result": result_payload}, EXIT_OK)

    except InstallError as exc:
        err_payload = {
            "code": exc.error_code,
            "message": exc.message,
        }
        if exc.data:
            err_payload["data"] = exc.data
        return _emit({"ok": False, "command": "install", "error": err_payload}, exc.exit_code)
    except Exception as exc:
        return _emit({
            "ok": False,
            "command": "install",
            "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}
        }, EXIT_INTERNAL)
    finally:
        if staging_dir and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if lock:
            lock.release()
