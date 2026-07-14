"""Tests for profile_backup.py — backup/restore for a private --profile-root.

Runs the script as a subprocess (matches the convention in
test_privacy_scan.py) so exit codes and JSON output are exercised exactly as
a CI step or the operator's shell would see them. Only tmp_path is used —
never a real profile root — per the privacy rule that this tool must never
embed real paths.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "profile_backup.py"
SPEC = importlib.util.spec_from_file_location("profile_backup", SCRIPT)
profile_backup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(profile_backup)


def run(*args: str) -> tuple[dict, int]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        raise AssertionError(
            f"non-JSON stdout\nargs={args}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return payload, proc.returncode


def make_profile_root(root: Path) -> None:
    (root / "packs").mkdir(parents=True)
    (root / "packs" / "prose_rules.json").write_text('{"schema": "v1"}\n', encoding="utf-8")
    (root / "skill-overlay").mkdir()
    (root / "skill-overlay" / "SKILL.md").write_text("# overlay\n", encoding="utf-8")
    (root / "manifest.json").write_text('{"schema": "v1"}\n', encoding="utf-8")
    (root / "privacy_denylist.txt").write_text("secret-term\n", encoding="utf-8")


def test_backup_creates_zip_and_sidecar_and_excludes(tmp_path: Path):
    root = tmp_path / "profile"
    make_profile_root(root)
    # A backups dir living *inside* the root — must be excluded.
    inside_dest = root / "backups"
    inside_dest.mkdir()
    (inside_dest / "stale.zip").write_bytes(b"not a real backup")
    # skills-backups/ and *.bundle are excluded regardless of location.
    (root / "skills-backups").mkdir()
    (root / "skills-backups" / "report-pipeline.bak-1").mkdir()
    (root / "skills-backups" / "report-pipeline.bak-1" / "SKILL.md").write_text("x", encoding="utf-8")
    (root / "prescrub.bundle").write_bytes(b"bundle contents")

    payload, code = run("backup", "--profile-root", str(root), "--dest", str(inside_dest))

    assert code == 0
    zip_path = Path(payload["backup"])
    sidecar_path = Path(payload["sidecar"])
    assert zip_path.exists()
    assert sidecar_path.exists()
    assert sidecar_path.read_text(encoding="utf-8").split()[0] == payload["sha256"]

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert "packs/prose_rules.json" in names
    assert "skill-overlay/SKILL.md" in names
    assert not any(n.startswith("backups/") for n in names)
    assert not any(n.startswith("skills-backups/") for n in names)
    assert not any(n.endswith(".bundle") for n in names)


def test_rotation_keeps_n(tmp_path: Path):
    root = tmp_path / "profile"
    make_profile_root(root)
    dest = tmp_path / "backups-out"

    for _ in range(7):
        payload, code = run(
            "backup", "--profile-root", str(root), "--dest", str(dest), "--keep", "3"
        )
        assert code == 0

    zips = sorted(dest.glob("profile-backup-*.zip"))
    sidecars = sorted(dest.glob("profile-backup-*.zip.sha256"))
    assert len(zips) == 3
    assert len(sidecars) == 3


def test_restore_onto_empty_root_works(tmp_path: Path):
    source = tmp_path / "profile"
    make_profile_root(source)
    dest = tmp_path / "backups-out"
    payload, code = run("backup", "--profile-root", str(source), "--dest", str(dest))
    assert code == 0

    target = tmp_path / "restored"  # does not exist yet
    payload, code = run("restore", "--archive", payload["backup"], "--profile-root", str(target))

    assert code == 0
    assert (target / "packs" / "prose_rules.json").exists()
    assert (target / "skill-overlay" / "SKILL.md").exists()
    assert payload["sha256_verified"] is True
    assert payload["pre_restore_backup"] is None


def test_restore_refuses_non_empty_without_force(tmp_path: Path):
    source = tmp_path / "profile"
    make_profile_root(source)
    dest = tmp_path / "backups-out"
    backup_payload, code = run("backup", "--profile-root", str(source), "--dest", str(dest))
    assert code == 0

    target = tmp_path / "restored"
    target.mkdir()
    (target / "existing_marker.txt").write_text("do not lose me\n", encoding="utf-8")

    payload, code = run("restore", "--archive", backup_payload["backup"], "--profile-root", str(target))

    assert code == 2
    assert (target / "existing_marker.txt").exists()
    assert not (target / "packs").exists()


def test_restore_force_preserves_pre_restore_copy(tmp_path: Path):
    source = tmp_path / "profile"
    make_profile_root(source)
    dest = tmp_path / "backups-out"
    backup_payload, code = run("backup", "--profile-root", str(source), "--dest", str(dest))
    assert code == 0

    target = tmp_path / "restored"
    target.mkdir()
    (target / "existing_marker.txt").write_text("do not lose me\n", encoding="utf-8")

    payload, code = run(
        "restore", "--archive", backup_payload["backup"], "--profile-root", str(target), "--force"
    )

    assert code == 0
    assert (target / "packs" / "prose_rules.json").exists()
    pre_restore = Path(payload["pre_restore_backup"])
    assert pre_restore.is_dir()
    assert (pre_restore / "existing_marker.txt").exists()


def test_restore_zip_slip_refused(tmp_path: Path):
    malicious = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("packs/prose_rules.json", "{}")
        archive.writestr("../../escaped.txt", "pwned")

    target = tmp_path / "restored"  # empty/nonexistent target

    payload, code = run("restore", "--archive", str(malicious), "--profile-root", str(target))

    assert code == 3
    assert not (tmp_path.parent / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_refuses_preexisting_symlink_parent(tmp_path: Path):
    target = tmp_path / "restored"
    actual = target / "actual"
    actual.mkdir(parents=True)
    linked = target / "linked"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    archive_path = tmp_path / "safe-name.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("linked/payload.txt", "must not follow the link")

    with zipfile.ZipFile(archive_path) as archive:
        # Refusal is the invariant; which guard fires first is platform-dependent
        # (a pre-existing symlink parent trips either the symlink check or the
        # containment/"escapes target root" check).
        with pytest.raises(profile_backup.IntegrityError, match="symlink|escapes"):
            profile_backup._extract_members(archive, target)

    assert not (actual / "payload.txt").exists()


def test_extract_parent_swap_immediately_before_open_is_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "restored"
    parent = target / "linked"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    archive_path = tmp_path / "race.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("linked/payload.txt", "must stay contained")

    real_open = profile_backup.os.open
    swapped = False

    def swap_parent_then_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and Path(path).name == "payload.txt":
            swapped = True
            moved = target / "linked-original"
            parent.rename(moved)
            try:
                parent.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                pytest.skip(f"directory symlinks unavailable: {exc}")
        kwargs = {} if dir_fd is None else {"dir_fd": dir_fd}
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(profile_backup.os, "open", swap_parent_then_open)
    with zipfile.ZipFile(archive_path) as archive:
        try:
            profile_backup._extract_members(archive, target)
        except profile_backup.IntegrityError:
            pass

    assert swapped
    assert not (outside / "payload.txt").exists()


def test_restore_refuses_symlink_member(tmp_path: Path):
    malicious = tmp_path / "symlink-member.zip"
    info = zipfile.ZipInfo("linked-profile")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr(info, "outside")

    target = tmp_path / "restored"
    payload, code = run("restore", "--archive", str(malicious), "--profile-root", str(target))

    assert code == 3
    assert "symlink" in payload["error"].lower()
    assert not target.exists()


def test_restore_hash_mismatch_refused(tmp_path: Path):
    source = tmp_path / "profile"
    make_profile_root(source)
    dest = tmp_path / "backups-out"
    backup_payload, code = run("backup", "--profile-root", str(source), "--dest", str(dest))
    assert code == 0

    sidecar = Path(backup_payload["sidecar"])
    sidecar.write_text("0" * 64 + "  tampered.zip\n", encoding="utf-8")

    target = tmp_path / "restored"
    payload, code = run("restore", "--archive", backup_payload["backup"], "--profile-root", str(target))

    assert code == 3
    assert not target.exists()


def test_list_reports_backups(tmp_path: Path):
    root = tmp_path / "profile"
    make_profile_root(root)
    dest = tmp_path / "backups-out"
    for _ in range(2):
        _, code = run("backup", "--profile-root", str(root), "--dest", str(dest), "--keep", "10")
        assert code == 0

    payload, code = run("list", "--dest", str(dest))

    assert code == 0
    assert len(payload["backups"]) == 2
    assert all(row["sha256_status"] == "ok" for row in payload["backups"])
