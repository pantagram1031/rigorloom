#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Completion card 5: install-candidate hash verification.

Links SHA-256 for source / EXE / sidecar(s) / installer(s). An install
candidate may PASS only when those hashes were collected **outside the
checkout** and the bytes still match. Checkout-only or mock results are
NOT_RUN, never install-candidate PASS. This script never claims GUI, IME,
or Windows install success.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_OUT = ROOT / "qa" / "_artifacts" / "card5-hashes.json"
EVIDENCE_DIR_ENV = "RIGORLOOM_CARD5_EVIDENCE_DIR"
SCHEMA = "rigorloom-card5-evidence/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"

EXIT_OK = 0
EXIT_FAIL = 3
EXIT_NOT_RUN = 2

REQUIRED_ROLES = ("source", "exe", "sidecar", "installer")
MANIFEST_NAMES = ("card5-evidence.json", "manifest.json", "hashes.json")

# Tauri NSIS / PyInstaller one-dir names. Discovery is relative to an
# evidence dir or the checkout; never a machine home directory.
EXE_NAMES = ("Rigorloom.exe", "rigorloom.exe")
SIDECAR_NAMES = ("rigorloomd.exe",)
INSTALLER_GLOBS = ("*setup.exe", "*nsis.exe", "Rigorloom_*.exe")
LOCAL_EXE_REL = (
    "desktop/src-tauri/target/release/Rigorloom.exe",
    "desktop/src-tauri/target/release/rigorloom.exe",
    "desktop/src-tauri/target/release/Rigorloom",
)
LOCAL_SIDECAR_REL = "desktop/src-tauri/resources/rigorloomd/rigorloomd.exe"
LOCAL_INSTALLER_GLOB = "desktop/src-tauri/target/release/bundle/nsis/*setup.exe"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value.lower()))


def normalize_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    hexdigest = value.strip().lower()
    return hexdigest if is_sha256(hexdigest) else None


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith("win")


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_evidence_dir(
    *,
    explicit: Path | None = None,
    environ: dict[str, str] | None = None,
    workspace: Path | None = None,
) -> tuple[Path | None, str | None]:
    """Configurable evidence dir. No machine-home default is ever applied."""
    env = os.environ if environ is None else environ
    if explicit is not None:
        return explicit, "cli"
    raw = (env.get(EVIDENCE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw), "env"
    _ = workspace  # workspace is never a fallback evidence dir
    return None, None


def git_identity(workspace: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"isRepo": False, "gitSha": None, "branch": None, "treeSha": None}

    def _run(args: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                args,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    sha = _run(["git", "rev-parse", "HEAD"])
    if sha:
        info["isRepo"] = True
        info["gitSha"] = sha
        info["branch"] = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        info["treeSha"] = _run(["git", "rev-parse", "HEAD^{tree}"])
    return info


def git_ls_files(workspace: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(workspace),
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return [name.decode("utf-8") for name in proc.stdout.split(b"\0") if name]


def source_tree_manifest(workspace: Path, rel_paths: Iterable[str] | None = None) -> dict[str, Any]:
    paths = list(rel_paths) if rel_paths is not None else (git_ls_files(workspace) or [])
    entries: list[dict[str, Any]] = []
    lines: list[str] = []
    missing: list[str] = []
    for rel in sorted(paths):
        posix = rel.replace("\\", "/")
        path = workspace / posix
        if not path.is_file():
            missing.append(posix)
            continue
        digest = sha256_file(path)
        size = path.stat().st_size
        entries.append({"path": posix, "sha256": digest, "bytes": size})
        lines.append(f"{digest}  {size}  {posix}")
    body = "\n".join(lines) + ("\n" if lines else "")
    return {
        "fileCount": len(entries),
        "missingCount": len(missing),
        "missing": missing[:20],
        "sha256": sha256_text(body),
        "encoding": "sha256  bytes  posix-path, sorted, newline-terminated",
    }


def checkout_context(workspace: Path, *, hash_source_tree: bool = True) -> dict[str, Any]:
    identity = git_identity(workspace)
    context: dict[str, Any] = {
        "workspace": str(workspace),
        "gitSha": identity.get("gitSha"),
        "branch": identity.get("branch"),
        "gitTreeSha": identity.get("treeSha"),
        "note": "checkout context only; not install-candidate evidence",
    }
    if hash_source_tree:
        manifest = source_tree_manifest(workspace)
        context["sourceTreeSha256"] = manifest["sha256"]
        context["sourceTreeFileCount"] = manifest["fileCount"]
        context["sourceTreeMissingCount"] = manifest["missingCount"]
    return context


def artifact_record(path: Path, *, role: str, origin: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "name": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "origin": origin,
    }


def _first_existing(root: Path, names: Iterable[str]) -> Path | None:
    for name in names:
        path = root / name
        if path.is_file():
            return path
    return None


def _glob_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            resolved = path.resolve()
            if path.is_file() and resolved not in seen:
                seen.add(resolved)
                found.append(path)
    return sorted(found, key=lambda item: item.name.lower())


def discover_local_checkout_artifacts(workspace: Path) -> dict[str, Any]:
    """Build-dir files inside the checkout. Recording them never confers PASS."""
    found: dict[str, Any] = {"exe": [], "sidecar": [], "installer": []}
    for rel in LOCAL_EXE_REL:
        path = workspace / rel
        if path.is_file():
            found["exe"].append(artifact_record(path, role="exe", origin="checkout_build_dir"))
    sidecar = workspace / LOCAL_SIDECAR_REL
    if sidecar.is_file():
        found["sidecar"].append(
            artifact_record(sidecar, role="sidecar", origin="checkout_build_dir")
        )
    for path in workspace.glob(LOCAL_INSTALLER_GLOB):
        if path.is_file():
            found["installer"].append(
                artifact_record(path, role="installer", origin="checkout_build_dir")
            )
    found["present"] = bool(found["exe"] or found["sidecar"] or found["installer"])
    found["note"] = (
        "Local checkout build outputs are recorded for operators only. "
        "They are not an install candidate and cannot PASS Card 5."
    )
    return found


def discover_evidence_files(evidence_dir: Path) -> dict[str, list[Path]]:
    files_root = evidence_dir / "files"
    search_roots = [evidence_dir]
    if files_root.is_dir():
        search_roots.append(files_root)
        sidecar_dir = files_root / "sidecar"
        installer_dir = files_root / "installer"
        if sidecar_dir.is_dir():
            search_roots.append(sidecar_dir)
        if installer_dir.is_dir():
            search_roots.append(installer_dir)
        nested = files_root / "rigorloomd"
        if nested.is_dir():
            search_roots.append(nested)

    exe: list[Path] = []
    sidecar: list[Path] = []
    installer: list[Path] = []
    for root in search_roots:
        for name in EXE_NAMES:
            path = root / name
            if path.is_file() and path not in exe:
                exe.append(path)
        for name in SIDECAR_NAMES:
            path = root / name
            if path.is_file() and path not in sidecar:
                sidecar.append(path)
        for path in _glob_files(root, INSTALLER_GLOBS):
            if path not in installer and path.name.lower() not in {
                item.name.lower() for item in exe + sidecar
            }:
                installer.append(path)
    return {"exe": exe, "sidecar": sidecar, "installer": installer}


def find_manifest(evidence_dir: Path) -> Path | None:
    for name in MANIFEST_NAMES:
        path = evidence_dir / name
        if path.is_file():
            return path
    return None


def _as_artifact_list(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def parse_claimed_roles(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    if not source and isinstance(artifacts.get("source"), dict):
        source = artifacts["source"]
    return {
        "source": source,
        "exe": _as_artifact_list(artifacts.get("exe")),
        "sidecar": _as_artifact_list(artifacts.get("sidecar")),
        "installer": _as_artifact_list(artifacts.get("installer")),
    }


def role_check(
    *,
    role: str,
    status: str,
    reason: str | None = None,
    detail: str | None = None,
    **extra: object,
) -> dict[str, Any]:
    row: dict[str, Any] = {"id": role, "role": role, "status": status}
    if reason:
        row["reason"] = reason
    if detail:
        row["detail"] = detail
    row.update(extra)
    return row


def _claimed_truthy(manifest: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if manifest.get(key) is True:
            return True
    return False


def verify_source_role(
    *,
    claimed: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    git_sha = claimed.get("gitSha") or claimed.get("sha") or claimed.get("sourceTipSha")
    tree_sha = claimed.get("sourceTreeSha256") or claimed.get("sha256")
    recorded = []
    if isinstance(git_sha, str) and git_sha.strip():
        recorded.append(("gitSha", git_sha.strip()))
    if is_sha256(tree_sha):
        recorded.append(("sourceTreeSha256", str(tree_sha).lower()))
    if not recorded:
        return role_check(
            role="source",
            status=STATUS_NOT_RUN,
            reason="source_hash_absent",
            detail="Evidence must record source gitSha and/or sourceTreeSha256.",
        )

    mismatches = []
    checkout_git = context.get("gitSha")
    checkout_tree = context.get("sourceTreeSha256")
    for kind, value in recorded:
        if kind == "gitSha" and checkout_git and value != checkout_git:
            mismatches.append(
                f"evidence gitSha {value} != checkout gitSha {checkout_git}"
            )
        if kind == "sourceTreeSha256" and checkout_tree and value != checkout_tree:
            mismatches.append("evidence sourceTreeSha256 != checkout source tree")
    if mismatches:
        return role_check(
            role="source",
            status=STATUS_FAIL,
            reason="source_sha_mismatch",
            detail="; ".join(mismatches),
            recorded={kind: value for kind, value in recorded},
            checkout={"gitSha": checkout_git, "sourceTreeSha256": checkout_tree},
        )
    return role_check(
        role="source",
        status=STATUS_PASS,
        recorded={kind: value for kind, value in recorded},
        checkout={"gitSha": checkout_git, "sourceTreeSha256": checkout_tree},
    )


def verify_file_role(
    *,
    role: str,
    claimed: list[dict[str, Any]],
    files: list[Path],
    origin: str,
) -> dict[str, Any]:
    if not claimed and not files:
        return role_check(
            role=role,
            status=STATUS_NOT_RUN,
            reason=f"{role}_absent",
            detail=(
                f"No {role} bytes and no recorded {role} SHA-256 in the "
                "external evidence directory."
            ),
        )
    if not files:
        return role_check(
            role=role,
            status=STATUS_NOT_RUN,
            reason="artifact_bytes_absent_cannot_rehash",
            detail=(
                f"Recorded {role} hashes exist but the evidence directory has "
                "no files to re-hash. Card 5 cannot PASS on JSON-only claims."
            ),
            recorded=claimed,
        )

    computed = [artifact_record(path, role=role, origin=origin) for path in files]
    claimed_hex = [normalize_sha256(item.get("sha256")) for item in claimed]
    claimed_hex = [item for item in claimed_hex if item]
    computed_hex = [item["sha256"] for item in computed]

    if claimed_hex and set(claimed_hex) != set(computed_hex):
        return role_check(
            role=role,
            status=STATUS_FAIL,
            reason="hash_mismatch",
            detail=f"Recorded {role} SHA-256 does not match bytes in the evidence directory.",
            recorded=claimed,
            computed=computed,
        )
    if not claimed_hex:
        # Files present but operator did not record hashes yet: still not PASS.
        return role_check(
            role=role,
            status=STATUS_NOT_RUN,
            reason="recorded_hash_absent",
            detail=(
                f"{role} bytes were hashed from the evidence directory but the "
                "manifest does not yet record the digest to link against."
            ),
            computed=computed,
        )
    return role_check(
        role=role,
        status=STATUS_PASS,
        recorded=claimed,
        computed=computed,
    )


def _summarize(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for row in checks if row["status"] == STATUS_PASS),
        "fail": sum(1 for row in checks if row["status"] == STATUS_FAIL),
        "not_run": sum(1 for row in checks if row["status"] == STATUS_NOT_RUN),
    }


def overall_status(checks: list[dict[str, Any]]) -> tuple[str, str | None]:
    if any(row["status"] == STATUS_FAIL for row in checks):
        fail = next(row for row in checks if row["status"] == STATUS_FAIL)
        return STATUS_FAIL, str(fail.get("reason") or "hash_mismatch")
    if checks and all(row["status"] == STATUS_PASS for row in checks):
        return STATUS_PASS, None
    missing = next(
        (row for row in checks if row["status"] == STATUS_NOT_RUN),
        None,
    )
    return STATUS_NOT_RUN, str((missing or {}).get("reason") or "incomplete_evidence")


def format_summary(report: dict[str, Any]) -> str:
    lines = [
        "Card 5 install-candidate hash verification",
        f"status: {report.get('status')}",
        f"installCandidatePass: {report.get('installCandidatePass')}",
        f"guiImeClaimed: {report.get('guiImeClaimed')}",
        f"reason: {report.get('reason') or '-'}",
    ]
    if report.get("detail"):
        lines.append(f"detail: {report['detail']}")
    lines.append("roles:")
    for row in report.get("checks") or []:
        extra = row.get("reason") or ""
        suffix = f" ({extra})" if extra else ""
        lines.append(f"  - {row.get('role')}: {row.get('status')}{suffix}")
    if report.get("note"):
        lines.append(report["note"])
    return "\n".join(lines) + "\n"


def empty_report(
    *,
    platform: str,
    workspace: Path,
    context: dict[str, Any],
    evidence_dir: Path | None,
    evidence_source: str | None,
    local_artifacts: dict[str, Any],
    reason: str,
    detail: str,
    status: str = STATUS_NOT_RUN,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks = checks or [
        role_check(role=role, status=STATUS_NOT_RUN, reason=reason, detail=detail)
        for role in REQUIRED_ROLES
    ]
    summary = _summarize(checks)
    install_pass = status == STATUS_PASS
    return {
        "schema": SCHEMA,
        "card": "completion-card-5",
        "topic": "install-candidate hash verification",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "status": status,
        "installCandidatePass": install_pass,
        "guiImeClaimed": False,
        "ok": status != STATUS_FAIL,
        "reason": reason,
        "detail": detail,
        "evidenceDir": str(evidence_dir) if evidence_dir else None,
        "evidenceDirSource": evidence_source,
        "checkoutContext": context,
        "localCheckoutArtifacts": local_artifacts,
        "checks": checks,
        "summary": summary,
        "note": (
            "PASS requires source + EXE + sidecar + installer SHA-256 collected "
            "outside the checkout and re-hashed to match. Checkout-only, mock, "
            "JSON-only, GUI, IME, and install claims are not Card 5 PASS."
        ),
        "workspace": str(workspace),
    }


def build_report(
    *,
    workspace: Path | None = None,
    evidence_dir: Path | None = None,
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    hash_source_tree: bool = True,
    checkout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = workspace or ROOT
    platform = platform or sys.platform
    context = checkout if checkout is not None else checkout_context(
        workspace, hash_source_tree=hash_source_tree
    )
    local_artifacts = discover_local_checkout_artifacts(workspace)
    resolved, source = resolve_evidence_dir(
        explicit=evidence_dir,
        environ=environ,
        workspace=workspace,
    )

    if resolved is None:
        reason = "external_windows_evidence_absent"
        detail = (
            "No external evidence directory. Set --evidence-dir or "
            f"{EVIDENCE_DIR_ENV}. Local checkout hashes are not an "
            "install candidate."
        )
        if local_artifacts.get("present"):
            detail += " Checkout build artifacts were found and recorded as non-PASS."
        return empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=None,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason=reason,
            detail=detail,
        )

    if not resolved.is_dir():
        return empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=resolved,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason="evidence_dir_missing",
            detail=f"Evidence directory does not exist: {resolved}",
        )

    inside = path_is_inside(resolved, workspace)
    manifest_path = find_manifest(resolved)
    manifest = load_json(manifest_path) if manifest_path else {}
    if manifest is None:
        return empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=resolved,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason="evidence_manifest_unreadable",
            detail=f"Could not parse {manifest_path}",
            status=STATUS_FAIL,
            checks=[
                role_check(
                    role="manifest",
                    status=STATUS_FAIL,
                    reason="evidence_manifest_unreadable",
                    detail=f"Could not parse {manifest_path}",
                )
            ],
        )

    if _claimed_truthy(
        manifest,
        "gui_ime_claimed",
        "guiImeClaimed",
        "install_pass",
        "installPass",
        "gui_pass",
        "ime_pass",
    ):
        return empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=resolved,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason="forbidden_gui_ime_or_install_claim",
            detail=(
                "Evidence claims GUI, IME, or install PASS. Card 5 scripts "
                "must not accept or repeat that claim."
            ),
            status=STATUS_FAIL,
            checks=[
                role_check(
                    role="claims",
                    status=STATUS_FAIL,
                    reason="forbidden_gui_ime_or_install_claim",
                )
            ],
        )

    collected_outside = bool(manifest.get("collectedOutsideCheckout"))
    if inside:
        reason = "evidence_dir_inside_checkout"
        detail = (
            "Evidence directory is inside the product checkout. Card 5 "
            "requires hashes verified outside the checkout."
        )
        return empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=resolved,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason=reason,
            detail=detail,
        )
    if not collected_outside:
        reason = "not_collected_outside_checkout"
        detail = (
            "Manifest does not set collectedOutsideCheckout=true. "
            "Checkout-only or mock collection cannot PASS."
        )
        files = discover_evidence_files(resolved)
        claimed = parse_claimed_roles(manifest)
        checks = [
            verify_source_role(claimed=claimed["source"], context=context),
            verify_file_role(
                role="exe", claimed=claimed["exe"], files=files["exe"], origin="evidence_dir"
            ),
            verify_file_role(
                role="sidecar",
                claimed=claimed["sidecar"],
                files=files["sidecar"],
                origin="evidence_dir",
            ),
            verify_file_role(
                role="installer",
                claimed=claimed["installer"],
                files=files["installer"],
                origin="evidence_dir",
            ),
        ]
        # Even if hashes would otherwise match, force NOT_RUN / FAIL: never PASS.
        for row in checks:
            if row["status"] == STATUS_PASS:
                row["status"] = STATUS_NOT_RUN
                row["reason"] = "not_collected_outside_checkout"
        report = empty_report(
            platform=platform,
            workspace=workspace,
            context=context,
            evidence_dir=resolved,
            evidence_source=source,
            local_artifacts=local_artifacts,
            reason=reason,
            detail=detail,
            checks=checks,
        )
        report["manifestPath"] = str(manifest_path) if manifest_path else None
        return report

    files = discover_evidence_files(resolved)
    claimed = parse_claimed_roles(manifest)
    checks = [
        verify_source_role(claimed=claimed["source"], context=context),
        verify_file_role(
            role="exe", claimed=claimed["exe"], files=files["exe"], origin="evidence_dir"
        ),
        verify_file_role(
            role="sidecar",
            claimed=claimed["sidecar"],
            files=files["sidecar"],
            origin="evidence_dir",
        ),
        verify_file_role(
            role="installer",
            claimed=claimed["installer"],
            files=files["installer"],
            origin="evidence_dir",
        ),
    ]
    status, reason = overall_status(checks)
    summary = _summarize(checks)
    install_pass = status == STATUS_PASS
    detail = {
        STATUS_PASS: "All required hashes are present, outside the checkout, and match.",
        STATUS_FAIL: "One or more required hashes mismatched or a forbidden claim was made.",
        STATUS_NOT_RUN: "Required Windows install artifacts or linked hashes are incomplete.",
    }[status]
    fail_detail = next(
        (row.get("detail") for row in checks if row["status"] == STATUS_FAIL and row.get("detail")),
        None,
    )
    return {
        "schema": SCHEMA,
        "card": "completion-card-5",
        "topic": "install-candidate hash verification",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "status": status,
        "installCandidatePass": install_pass,
        "guiImeClaimed": False,
        "ok": status != STATUS_FAIL,
        "reason": reason,
        "detail": fail_detail or detail,
        "evidenceDir": str(resolved),
        "evidenceDirSource": source,
        "manifestPath": str(manifest_path) if manifest_path else None,
        "collectedOutsideCheckout": True,
        "checkoutContext": context,
        "localCheckoutArtifacts": local_artifacts,
        "checks": checks,
        "summary": summary,
        "note": (
            "PASS requires source + EXE + sidecar + installer SHA-256 collected "
            "outside the checkout and re-hashed to match. Checkout-only, mock, "
            "JSON-only, GUI, IME, and install claims are not Card 5 PASS."
        ),
        "workspace": str(workspace),
    }


def copy_into_evidence(src: Path, dest_dir: Path, name: str | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (name or src.name)
    shutil.copy2(src, dest)
    return dest


def collect_report(
    *,
    workspace: Path,
    evidence_dir: Path,
    exe: Path | None,
    sidecars: list[Path],
    installers: list[Path],
    outside_checkout: bool,
    copy_files: bool,
    platform: str | None = None,
    hash_source_tree: bool = True,
    checkout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    platform = platform or sys.platform
    context = checkout if checkout is not None else checkout_context(
        workspace, hash_source_tree=hash_source_tree
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    files_dir = evidence_dir / "files"
    inside = path_is_inside(evidence_dir, workspace)

    collected_outside = bool(outside_checkout) and not inside
    reason = None
    detail = None
    if outside_checkout and inside:
        reason = "evidence_dir_inside_checkout"
        detail = (
            "--outside-checkout was set but the evidence directory is inside "
            "the product checkout. Collection is recorded as NOT_RUN."
        )
        collected_outside = False
    elif not outside_checkout:
        reason = "collect_draft_not_outside_checkout"
        detail = (
            "Collect writes a draft evidence manifest. It never PASSes Card 5. "
            "Re-run with --outside-checkout against a directory outside the "
            "checkout after copying Windows artifacts there."
        )

    def _ingest(path: Path | None, role: str, dest_name: str | None = None) -> dict[str, Any] | None:
        if path is None:
            return None
        if not path.is_file():
            return {"role": role, "path": str(path), "missing": True}
        stored = path
        origin = "collect_path"
        if copy_files:
            stored = copy_into_evidence(path, files_dir, dest_name)
            origin = "copied_into_evidence"
        record = artifact_record(stored, role=role, origin=origin)
        record["sourcePath"] = str(path)
        return record

    exe_record = _ingest(exe, "exe")
    sidecar_records = [item for item in (_ingest(path, "sidecar") for path in sidecars) if item]
    installer_records = [
        item for item in (_ingest(path, "installer") for path in installers) if item
    ]

    source = {
        "gitSha": context.get("gitSha"),
        "sourceTreeSha256": context.get("sourceTreeSha256"),
        "branch": context.get("branch"),
    }
    manifest = {
        "schema": SCHEMA,
        "card": "completion-card-5",
        "collectedOutsideCheckout": collected_outside,
        "gui_ime_claimed": False,
        "guiImeClaimed": False,
        "install_pass": False,
        "source": source,
        "artifacts": {
            "exe": exe_record,
            "sidecar": sidecar_records,
            "installer": installer_records,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "note": "Collection draft. Verify against the copied bytes to obtain PASS.",
    }
    manifest_path = evidence_dir / "card5-evidence.json"
    write_json(manifest_path, manifest)

    report = build_report(
        workspace=workspace,
        evidence_dir=evidence_dir,
        platform=platform,
        hash_source_tree=hash_source_tree,
        checkout=context,
    )
    report["mode"] = "collect"
    if report["status"] == STATUS_PASS and not collected_outside:
        # Belt: collect must never PASS.
        report["status"] = STATUS_NOT_RUN
        report["installCandidatePass"] = False
        report["reason"] = reason or "collect_never_pass"
    if report["status"] == STATUS_PASS:
        # Collect is a write step; PASS belongs to verify. Downgrade with a note.
        report["status"] = STATUS_NOT_RUN
        report["installCandidatePass"] = False
        report["ok"] = True
        report["reason"] = "collect_draft_run_verify"
        report["detail"] = (
            "Artifacts were hashed into the evidence directory. Run verify "
            "on that directory for an install-candidate verdict. Collect "
            "itself never labels PASS."
        )
    if reason and report["status"] != STATUS_FAIL:
        report["reason"] = reason
        if detail:
            report["detail"] = detail
    report["manifestPath"] = str(manifest_path)
    return report


def _parse_paths(values: list[str] | None) -> list[Path]:
    return [Path(item) for item in (values or []) if item]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        nargs="?",
        default="verify",
        choices=("verify", "collect"),
        help="verify (default) an evidence dir, or collect hashes into one.",
    )
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help=(
            "External Windows evidence directory. Overrides "
            f"{EVIDENCE_DIR_ENV}. Do not hardcode a machine home path."
        ),
    )
    parser.add_argument("--json-out", default=None, help="Write the JSON report here.")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Product checkout to treat as source. Defaults to the repo root.",
    )
    parser.add_argument(
        "--no-source-tree",
        action="store_true",
        help="Record git SHA only; skip hashing every tracked file.",
    )
    parser.add_argument("--exe", default=None, help="EXE path for collect mode.")
    parser.add_argument(
        "--sidecar",
        action="append",
        default=[],
        help="Sidecar path for collect mode (repeatable).",
    )
    parser.add_argument(
        "--installer",
        action="append",
        default=[],
        help="Installer path for collect mode (repeatable).",
    )
    parser.add_argument(
        "--outside-checkout",
        action="store_true",
        help="Declare that collect is writing to a directory outside the checkout.",
    )
    parser.add_argument(
        "--copy-into-evidence",
        action="store_true",
        help="Copy collect inputs into <evidence-dir>/files so verify can re-hash.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print the human summary only (JSON still written if --json-out).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace) if args.workspace else ROOT
    evidence = Path(args.evidence_dir) if args.evidence_dir else None
    hash_tree = not args.no_source_tree
    json_out = Path(args.json_out) if args.json_out else None

    if args.mode == "collect":
        if evidence is None:
            print(
                "collect requires --evidence-dir (a path outside the checkout).",
                file=sys.stderr,
            )
            return EXIT_NOT_RUN
        report = collect_report(
            workspace=workspace,
            evidence_dir=evidence,
            exe=Path(args.exe) if args.exe else None,
            sidecars=_parse_paths(args.sidecar),
            installers=_parse_paths(args.installer),
            outside_checkout=args.outside_checkout,
            copy_files=args.copy_into_evidence,
            hash_source_tree=hash_tree,
        )
    else:
        report = build_report(
            workspace=workspace,
            evidence_dir=evidence,
            hash_source_tree=hash_tree,
        )

    summary = format_summary(report)
    if args.summary_only:
        print(summary, end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(summary, end="")
    if json_out is not None:
        write_json(json_out, report)

    if report["status"] == STATUS_FAIL:
        return EXIT_FAIL
    if report["status"] == STATUS_NOT_RUN:
        return EXIT_OK if report.get("ok", True) else EXIT_NOT_RUN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
