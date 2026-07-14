#!/usr/bin/env python3
"""Backup and restore for a private `--profile-root` (packs/, skill-overlay/,
manifests, denylist, resolved/ ...). Guards against the profile being a single
point of loss: every backup gets a sha256 sidecar, restores are refused onto a
non-empty root unless explicitly forced (and even then the prior root is moved
aside, never deleted), and zip entries that would escape the target root are
rejected. Stdlib only.

CLI:
    profile_backup.py backup --profile-root <p> [--dest <dir>] [--keep N] [--json]
    profile_backup.py restore --archive <zip> --profile-root <p> [--force] [--json]
    profile_backup.py list --dest <dir> [--json]

Exit codes:
    0  success
    2  usage error (bad path/args, non-empty root refused without --force)
    3  integrity/safety failure (sha256 mismatch, corrupt zip, zip-slip entry)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DEFAULT_KEEP = 5
EXCLUDED_DIR_NAME = "skills-backups"
EXCLUDED_FILE_SUFFIX = ".bundle"
BACKUP_NAME_RE = re.compile(r"^profile-backup-\d{8}T\d{6}Z(-\d+)?\.zip$")
BACKUP_DEST_DIRNAME = ".report-profile-backups"


class UsageError(Exception):
    """Bad arguments or a precondition the caller must fix (exit 2)."""


class IntegrityError(Exception):
    """A verification/safety check failed: corrupt archive, hash mismatch, or
    a zip entry that would escape the restore target (exit 3)."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_dest(profile_root: Path) -> Path:
    """Sibling of the profile root, outside it, so a backup never backs up
    itself."""
    return profile_root.parent / BACKUP_DEST_DIRNAME


def _unique_path(candidate: Path) -> Path:
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.name, ""
    if candidate.suffix:
        stem, suffix = candidate.name[: -len(candidate.suffix)], candidate.suffix
    counter = 1
    while True:
        alt = candidate.with_name(f"{stem}-{counter}{suffix}")
        if not alt.exists():
            return alt
        counter += 1


def _sidecar_for(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.name + ".sha256")


def _iter_backup_zips(dest: Path):
    return sorted(
        (p for p in dest.glob("profile-backup-*.zip") if BACKUP_NAME_RE.match(p.name)),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )


def _rotate(dest: Path, keep: int) -> list[str]:
    """Delete backup zips (+ sidecars) older than the newest `keep`, matching
    only this tool's own naming pattern so unrelated files are never touched."""
    zips = _iter_backup_zips(dest)
    removed = []
    for path in zips[keep:]:
        sidecar = _sidecar_for(path)
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path.name)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass
    return removed


def backup(profile_root: Path, dest: Path | None, keep: int) -> dict:
    profile_root = profile_root.resolve()
    if not profile_root.is_dir():
        raise UsageError(f"profile root not found or not a directory: {profile_root}")
    if keep < 1:
        raise UsageError("--keep must be >= 1")

    dest = (dest.resolve() if dest else default_dest(profile_root))
    dest.mkdir(parents=True, exist_ok=True)

    zip_path = _unique_path(dest / f"profile-backup-{_stamp()}.zip")

    included = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(profile_root):
            dp = Path(dirpath)
            kept_dirs = []
            for name in dirnames:
                child = dp / name
                if name == EXCLUDED_DIR_NAME:
                    continue
                if child.resolve() == dest:
                    continue
                kept_dirs.append(name)
            dirnames[:] = sorted(kept_dirs)

            for fname in sorted(filenames):
                fpath = dp / fname
                if fpath.suffix.lower() == EXCLUDED_FILE_SUFFIX:
                    continue
                archive.write(fpath, fpath.relative_to(profile_root).as_posix())
                included += 1

    digest = _sha256(zip_path)
    sidecar_path = _sidecar_for(zip_path)
    sidecar_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")

    removed = _rotate(dest, keep)

    return {
        "ok": True,
        "profile_root": str(profile_root),
        "dest": str(dest),
        "backup": str(zip_path),
        "sidecar": str(sidecar_path),
        "sha256": digest,
        "size": zip_path.stat().st_size,
        "files_included": included,
        "rotated_removed": removed,
    }


def _verify_sidecar(archive_path: Path) -> bool:
    """Return True if a sidecar was present and matched; False if no sidecar
    exists. Raises IntegrityError on a mismatch."""
    sidecar = _sidecar_for(archive_path)
    if not sidecar.exists():
        return False
    try:
        expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
    except OSError as exc:
        raise IntegrityError(f"cannot read sidecar: {sidecar}: {exc}") from exc
    actual = _sha256(archive_path)
    if expected.lower() != actual.lower():
        raise IntegrityError(
            f"sha256 mismatch for {archive_path.name}: sidecar={expected} actual={actual}"
        )
    return True


def _check_zip_slip(archive: zipfile.ZipFile, root: Path) -> None:
    root_resolved = Path(os.path.realpath(root))
    for info in archive.infolist():
        name = info.filename
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise IntegrityError(f"unsafe zip entry is a symlink: {name!r}")
        if not name or name.startswith("/") or name.startswith("\\"):
            raise IntegrityError(f"unsafe zip entry (absolute path): {name!r}")
        # A drive-qualified or otherwise absolute member also fails the
        # relative_to() check below once resolved, but reject it explicitly
        # first for a clearer error message.
        if re.match(r"^[A-Za-z]:[\\/]", name):
            raise IntegrityError(f"unsafe zip entry (drive path): {name!r}")
        target = Path(os.path.realpath(root_resolved / name))
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise IntegrityError(f"unsafe zip entry escapes target root: {name!r}") from None


def _member_parts(info: zipfile.ZipInfo) -> tuple[str, ...]:
    name = info.filename
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise IntegrityError(f"unsafe zip entry is a symlink: {name!r}")
    normalized = name.replace(chr(92), "/")
    path = PurePosixPath(normalized)
    parts = tuple(part for part in path.parts if part != ".")
    if (not name or path.is_absolute() or re.match(r"^[A-Za-z]:", normalized)
            or not parts or any(part in {"", ".."} for part in parts)):
        raise IntegrityError(f"unsafe zip entry path: {name!r}")
    return parts


def _supports_secure_openat() -> bool:
    return bool(
        getattr(os, "O_NOFOLLOW", 0)
        and getattr(os, "O_DIRECTORY", 0)
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
    )


def _open_directory_chain(root_fd: int, parts: tuple[str, ...], name: str) -> int:
    current_fd = os.dup(root_fd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        for part in parts:
            try:
                child_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise IntegrityError(
            f"unsafe zip target directory for {name!r}: {exc}"
        ) from exc


def _extract_members_openat(archive: zipfile.ZipFile, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise IntegrityError(f"unsafe restore staging root: {root}: {exc}") from exc
    try:
        for info in archive.infolist():
            parts = _member_parts(info)
            if info.is_dir():
                directory_fd = _open_directory_chain(root_fd, parts, info.filename)
                os.close(directory_fd)
                continue

            parent_fd = _open_directory_chain(root_fd, parts[:-1], info.filename)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                flags |= getattr(os, "O_BINARY", 0)
                descriptor = os.open(
                    parts[-1], flags, 0o600, dir_fd=parent_fd)
                with archive.open(info) as source, os.fdopen(descriptor, "wb") as destination:
                    shutil.copyfileobj(source, destination)
            except OSError as exc:
                raise IntegrityError(
                    f"cannot securely extract zip entry {info.filename!r}: {exc}"
                ) from exc
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


def _assert_no_symlink_components(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            continue
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise IntegrityError(f"cannot inspect {label}: {current}: {exc}") from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise IntegrityError(f"unsafe {label} has symlink component: {current}")


def _assert_destination_members_safe(
    root: Path, members: list[zipfile.ZipInfo],
) -> None:
    _assert_no_symlink_components(root, "restore destination")
    for info in members:
        parts = _member_parts(info)
        _assert_no_symlink_components(
            root.joinpath(*parts), f"zip target for {info.filename!r}")


def _extract_fresh_tree(
    archive: zipfile.ZipFile, root: Path, members: list[zipfile.ZipInfo],
) -> None:
    for info in members:
        parts = _member_parts(info)
        target = root.joinpath(*parts)
        try:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0)
            descriptor = os.open(target, flags, 0o600)
            with archive.open(info) as source, os.fdopen(descriptor, "wb") as destination:
                shutil.copyfileobj(source, destination)
        except OSError as exc:
            raise IntegrityError(f"cannot extract zip entry {info.filename!r}: {exc}") from exc


def _extract_members_fresh(archive: zipfile.ZipFile, root: Path) -> None:
    """Windows fallback: populate an unpredictable empty tree, then replace."""
    root = Path(os.path.abspath(root))
    root.parent.mkdir(parents=True, exist_ok=True)
    members = archive.infolist()
    _assert_destination_members_safe(root, members)
    fresh = Path(tempfile.mkdtemp(prefix=f".{root.name}.extract-", dir=root.parent))
    try:
        _extract_fresh_tree(archive, fresh, members)
        _assert_destination_members_safe(root, members)
        if os.path.lexists(root):
            if not root.is_dir() or any(root.iterdir()):
                raise IntegrityError(
                    f"restore staging destination changed or is non-empty: {root}"
                )
            root.rmdir()
        _assert_no_symlink_components(root.parent, "restore destination parent")
        if os.path.lexists(root):
            raise IntegrityError(f"restore staging destination changed: {root}")
        os.replace(fresh, root)
        fresh = None
    except OSError as exc:
        raise IntegrityError(f"cannot install fresh restore staging tree: {exc}") from exc
    finally:
        if fresh is not None:
            shutil.rmtree(fresh, ignore_errors=True)


def _extract_members(archive: zipfile.ZipFile, root: Path) -> None:
    """Extract without a check/open race on any archive-controlled component."""
    if _supports_secure_openat():
        _extract_members_openat(archive, Path(os.path.abspath(root)))
    else:
        _extract_members_fresh(archive, root)


def restore(archive_path: Path, profile_root: Path, force: bool) -> dict:
    if not archive_path.is_file():
        raise UsageError(f"archive not found: {archive_path}")

    sha256_verified = _verify_sidecar(archive_path)

    profile_root = Path(os.path.abspath(profile_root))
    _assert_no_symlink_components(profile_root, "restore destination")
    if profile_root.exists() and not profile_root.is_dir():
        raise UsageError(f"profile root exists and is not a directory: {profile_root}")
    non_empty = profile_root.is_dir() and any(profile_root.iterdir())

    pre_restore_path = None
    staging_path = None
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _check_zip_slip(archive, profile_root)

            if non_empty:
                if not force:
                    raise UsageError(
                        f"profile root is non-empty, refusing restore without --force: {profile_root}"
                    )
            profile_root.parent.mkdir(parents=True, exist_ok=True)
            staging_path = Path(tempfile.mkdtemp(
                prefix=f".{profile_root.name}.restore-", dir=profile_root.parent,
            ))
            _extract_members(archive, staging_path)

        _assert_no_symlink_components(profile_root, "restore destination")
        if non_empty:
            pre_restore_path = _unique_path(
                profile_root.with_name(f"{profile_root.name}.pre-restore-{_stamp()}")
            )
            shutil.move(str(profile_root), str(pre_restore_path))
        elif profile_root.exists():
            profile_root.rmdir()
        _assert_no_symlink_components(profile_root.parent, "restore destination parent")
        if os.path.lexists(profile_root):
            raise IntegrityError(f"restore destination changed before replace: {profile_root}")
        try:
            os.replace(staging_path, profile_root)
        except OSError as exc:
            raise IntegrityError(f"cannot install restored profile: {exc}") from exc
        staging_path = None
    except zipfile.BadZipFile as exc:
        raise IntegrityError(f"corrupt or unreadable archive: {archive_path}: {exc}") from exc
    finally:
        if staging_path is not None:
            shutil.rmtree(staging_path, ignore_errors=True)

    return {
        "ok": True,
        "restored_to": str(profile_root),
        "archive": str(archive_path),
        "sha256_verified": sha256_verified,
        "pre_restore_backup": str(pre_restore_path) if pre_restore_path else None,
    }


def list_backups(dest: Path) -> dict:
    if not dest.is_dir():
        raise UsageError(f"backup destination not found: {dest}")

    rows = []
    for path in _iter_backup_zips(dest):
        sidecar = _sidecar_for(path)
        if not sidecar.exists():
            status = "no-sidecar"
        else:
            try:
                expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
                status = "ok" if expected.lower() == _sha256(path).lower() else "mismatch"
            except OSError:
                status = "error"
        rows.append({"name": path.name, "size": path.stat().st_size, "sha256_status": status})

    return {"ok": True, "dest": str(dest.resolve()), "backups": rows}


def _print_backup(result: dict) -> None:
    print(f"backup: {result['backup']}")
    print(f"sidecar: {result['sidecar']}")
    print(f"sha256: {result['sha256']}")
    print(f"size: {result['size']} bytes")
    print(f"files_included: {result['files_included']}")
    if result["rotated_removed"]:
        print(f"rotated_removed: {', '.join(result['rotated_removed'])}")


def _print_restore(result: dict) -> None:
    print(f"restored_to: {result['restored_to']}")
    print(f"archive: {result['archive']}")
    print(f"sha256_verified: {result['sha256_verified']}")
    if result["pre_restore_backup"]:
        print(f"pre_restore_backup: {result['pre_restore_backup']}")


def _print_list(result: dict) -> None:
    print(f"dest: {result['dest']}")
    if not result["backups"]:
        print("(no backups found)")
        return
    for row in result["backups"]:
        print(f"{row['name']:48}  {row['size']:>12} bytes  sha256={row['sha256_status']}")


def _emit(result: dict, as_json: bool, printer) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        printer(result)


def _emit_error(exc: Exception, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
    else:
        print(f"error: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="profile_backup.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backup", help="Zip the entire profile root")
    p.add_argument("--profile-root", required=True, type=Path)
    p.add_argument("--dest", type=Path, help="Backup destination (default: sibling .report-profile-backups)")
    p.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="Backups to retain after rotation")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("restore", help="Restore a profile root from a backup zip")
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--profile-root", required=True, type=Path)
    p.add_argument("--force", action="store_true", help="Allow restoring onto a non-empty root")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list", help="List backups at a destination")
    p.add_argument("--dest", required=True, type=Path)
    p.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))

    try:
        if args.command == "backup":
            result = backup(args.profile_root, args.dest, args.keep)
            _emit(result, as_json, _print_backup)
            return 0

        if args.command == "restore":
            result = restore(args.archive, args.profile_root, args.force)
            _emit(result, as_json, _print_restore)
            return 0

        if args.command == "list":
            result = list_backups(args.dest)
            _emit(result, as_json, _print_list)
            return 0

        parser.error(f"unknown command: {args.command}")
        return 2
    except UsageError as exc:
        _emit_error(exc, as_json)
        return 2
    except IntegrityError as exc:
        _emit_error(exc, as_json)
        return 3


def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
