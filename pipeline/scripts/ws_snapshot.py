#!/usr/bin/env python3
"""Create, inspect, and restore pre-assembly workspace snapshots.

Snapshots contain ``bundle/``, ``output/``, ``PIPELINE.md``, and optional
``.pipeline/``. Archives have required SHA-256 sidecars. Restore extraction is
member-by-member and rejects zip-slip, symlink members, and symlink parents.

Exit codes: 0 success, 2 usage/precondition, 3 integrity/safety failure.
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
SNAPSHOT_DIRNAME = ".snapshots"
SNAPSHOT_RE = re.compile(r"^pre-assembly-\d{8}T\d{6}Z(?:-\d+)?\.zip$")
ARCHIVE_ROOTS = {"bundle", "output", "PIPELINE.md", ".pipeline"}


class UsageError(Exception):
    """Caller-fixable argument or precondition error (exit 2)."""


class IntegrityError(Exception):
    """Snapshot verification or filesystem safety failed (exit 3)."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar_for(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.name + ".sha256")


def _unique_path(candidate: Path) -> Path:
    if not os.path.lexists(candidate):
        return candidate
    stem = candidate.name[: -len(candidate.suffix)] if candidate.suffix else candidate.name
    suffix = candidate.suffix
    counter = 1
    while True:
        alternate = candidate.with_name(f"{stem}-{counter}{suffix}")
        if not os.path.lexists(alternate):
            return alternate
        counter += 1


def _snapshot_dir(workspace: Path) -> Path:
    return workspace / SNAPSHOT_DIRNAME


def _is_reparse_point(path: Path) -> bool:
    """Return whether an existing Windows path is a junction/reparse point."""
    if os.name != "nt":
        return False
    info = os.stat(path, follow_symlinks=False)
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and attributes & flag)


def _iter_snapshot_zips(snapshot_dir: Path) -> list[Path]:
    if not snapshot_dir.is_dir():
        return []
    return sorted(
        (path for path in snapshot_dir.glob("pre-assembly-*.zip")
         if SNAPSHOT_RE.fullmatch(path.name)),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )


def _rotate(snapshot_dir: Path, keep: int) -> list[str]:
    removed: list[str] = []
    for path in _iter_snapshot_zips(snapshot_dir)[keep:]:
        sidecar = _sidecar_for(path)
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path.name)
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:
            pass
    return removed


def _assert_regular_source(path: Path, label: str, *, directory: bool) -> None:
    try:
        mode = os.lstat(path).st_mode
        is_reparse = _is_reparse_point(path)
    except OSError as exc:
        raise UsageError(f"{label} not found: {path}: {exc}") from exc
    if stat.S_ISLNK(mode) or is_reparse:
        raise IntegrityError(
            f"unsafe {label} is a symlink or reparse point: {path}"
        )
    if directory and not stat.S_ISDIR(mode):
        raise UsageError(f"{label} is not a directory: {path}")
    if not directory and not stat.S_ISREG(mode):
        raise UsageError(f"{label} is not a regular file: {path}")


def _write_tree(archive: zipfile.ZipFile, root: Path, arc_root: str) -> int:
    """Write a real directory tree without following symlinks."""
    included = 0
    archive.write(root, f"{arc_root}/")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            if name == SNAPSHOT_DIRNAME or name.lower().endswith(".bak"):
                continue
            if (stat.S_ISLNK(os.lstat(child).st_mode)
                    or _is_reparse_point(child)):
                raise IntegrityError(
                    f"unsafe snapshot source is a symlink or reparse point: {child}"
                )
            kept_dirs.append(name)
            archive.write(child, child.relative_to(root.parent).as_posix() + "/")
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            if name.lower().endswith(".bak"):
                continue
            child = current / name
            if (stat.S_ISLNK(os.lstat(child).st_mode)
                    or _is_reparse_point(child)):
                raise IntegrityError(
                    f"unsafe snapshot source is a symlink or reparse point: {child}"
                )
            archive.write(child, child.relative_to(root.parent).as_posix())
            included += 1
    return included


def snapshot(workspace: Path, keep: int = DEFAULT_KEEP) -> dict:
    workspace = Path(os.path.abspath(workspace))
    if keep < 1:
        raise UsageError("--keep must be >= 1")
    _assert_regular_source(workspace, "workspace", directory=True)
    _assert_no_symlink_components(workspace, "workspace")

    bundle = workspace / "bundle"
    output = workspace / "output"
    pipeline_md = workspace / "PIPELINE.md"
    _assert_regular_source(bundle, "bundle directory", directory=True)
    _assert_regular_source(output, "output directory", directory=True)
    _assert_regular_source(pipeline_md, "PIPELINE.md", directory=False)
    pipeline_state = workspace / ".pipeline"
    if os.path.lexists(pipeline_state):
        _assert_regular_source(pipeline_state, ".pipeline directory", directory=True)

    snapshot_dir = _snapshot_dir(workspace)
    if os.path.lexists(snapshot_dir):
        _assert_regular_source(snapshot_dir, "snapshot directory", directory=True)
    else:
        snapshot_dir.mkdir(parents=True)
    _assert_no_symlink_components(snapshot_dir, "snapshot directory")

    archive_path = _unique_path(snapshot_dir / f"pre-assembly-{_stamp()}.zip")
    included = 0
    try:
        with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
            included += _write_tree(archive, bundle, "bundle")
            included += _write_tree(archive, output, "output")
            archive.write(pipeline_md, "PIPELINE.md")
            included += 1
            if pipeline_state.is_dir():
                included += _write_tree(archive, pipeline_state, ".pipeline")
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    digest = _sha256(archive_path)
    sidecar = _sidecar_for(archive_path)
    sidecar.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    removed = _rotate(snapshot_dir, keep)
    return {
        "ok": True, "workspace": str(workspace), "snapshot": str(archive_path),
        "sidecar": str(sidecar), "sha256": digest,
        "size": archive_path.stat().st_size, "files_included": included,
        "rotated_removed": removed,
    }


def _verify_sidecar(archive_path: Path) -> None:
    sidecar = _sidecar_for(archive_path)
    if not os.path.lexists(sidecar):
        raise IntegrityError(f"sha256 sidecar missing for {archive_path.name}")
    try:
        mode = os.lstat(sidecar).st_mode
    except OSError as exc:
        raise IntegrityError(f"cannot inspect sha256 sidecar: {sidecar}: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise IntegrityError(f"unsafe sha256 sidecar is not a regular file: {sidecar}")
    _assert_no_symlink_components(sidecar, "sha256 sidecar")
    try:
        expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, UnicodeError, IndexError) as exc:
        raise IntegrityError(f"cannot read sha256 sidecar: {sidecar}: {exc}") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise IntegrityError(f"invalid sha256 sidecar for {archive_path.name}")
    actual = _sha256(archive_path)
    if expected.lower() != actual.lower():
        raise IntegrityError(
            f"sha256 mismatch for {archive_path.name}: sidecar={expected} actual={actual}"
        )


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
    if parts[0] not in ARCHIVE_ROOTS:
        raise IntegrityError(f"unexpected workspace snapshot entry: {name!r}")
    if parts[0] == "PIPELINE.md" and len(parts) != 1:
        raise IntegrityError(f"unsafe PIPELINE.md snapshot entry: {name!r}")
    if any(part == SNAPSHOT_DIRNAME for part in parts) or parts[-1].lower().endswith(".bak"):
        raise IntegrityError(f"excluded path present in workspace snapshot: {name!r}")
    return parts


def _assert_no_symlink_components(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            continue
        try:
            mode = os.lstat(current).st_mode
            is_reparse = _is_reparse_point(current)
        except OSError as exc:
            raise IntegrityError(f"cannot inspect {label}: {current}: {exc}") from exc
        if stat.S_ISLNK(mode) or is_reparse:
            raise IntegrityError(
                f"unsafe {label} has symlink or reparse point component: {current}"
            )


def _target_for(root: Path, info: zipfile.ZipInfo) -> tuple[Path, tuple[str, ...]]:
    parts = _member_parts(info)
    root_real = Path(os.path.realpath(root))
    target = root.joinpath(*parts)
    target_real = Path(os.path.realpath(target))
    try:
        target_real.relative_to(root_real)
    except ValueError:
        raise IntegrityError(f"unsafe zip entry escapes target root: {info.filename!r}") from None
    return target, parts


def _assert_destination_members_safe(
    root: Path, members: list[zipfile.ZipInfo]
) -> None:
    _assert_no_symlink_components(root, "restore destination")
    for info in members:
        target, _ = _target_for(root, info)
        _assert_no_symlink_components(target, f"zip target for {info.filename!r}")


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
        raise IntegrityError(f"unsafe zip target directory for {name!r}: {exc}") from exc


def _extract_members_openat(archive: zipfile.ZipFile, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise IntegrityError(f"unsafe restore staging root: {root}: {exc}") from exc
    try:
        for info in archive.infolist():
            _, parts = _target_for(root, info)
            _assert_no_symlink_components(
                root.joinpath(*parts), f"zip target for {info.filename!r}"
            )
            if info.is_dir():
                directory_fd = _open_directory_chain(root_fd, parts, info.filename)
                os.close(directory_fd)
                continue
            parent_fd = _open_directory_chain(root_fd, parts[:-1], info.filename)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                flags |= getattr(os, "O_BINARY", 0)
                descriptor = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
                with archive.open(info) as source, os.fdopen(descriptor, "wb") as target:
                    shutil.copyfileobj(source, target)
            except OSError as exc:
                raise IntegrityError(
                    f"cannot securely extract zip entry {info.filename!r}: {exc}"
                ) from exc
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


def _extract_fresh_tree(
    archive: zipfile.ZipFile, root: Path, members: list[zipfile.ZipInfo]
) -> None:
    for info in members:
        target, _ = _target_for(root, info)
        _assert_no_symlink_components(target, f"zip target for {info.filename!r}")
        try:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            _target_for(root, info)  # containment re-check immediately before write
            _assert_no_symlink_components(target.parent, "zip target parent")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(target, flags, 0o600)
            with archive.open(info) as source, os.fdopen(descriptor, "wb") as destination:
                shutil.copyfileobj(source, destination)
        except OSError as exc:
            raise IntegrityError(f"cannot extract zip entry {info.filename!r}: {exc}") from exc


def _extract_members_fresh(archive: zipfile.ZipFile, root: Path) -> None:
    """Windows fallback: fill an unpredictable empty tree, then replace."""
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
                raise IntegrityError(f"restore staging destination changed or is non-empty: {root}")
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
    """Extract without following an archive-controlled or existing symlink."""
    if _supports_secure_openat():
        _extract_members_openat(archive, Path(os.path.abspath(root)))
    else:
        _extract_members_fresh(archive, root)


def _resolve_snapshot(workspace: Path, name: str) -> Path:
    snapshot_dir = _snapshot_dir(workspace)
    _assert_no_symlink_components(snapshot_dir, "snapshot directory")
    if name == "latest":
        snapshots = _iter_snapshot_zips(snapshot_dir)
        if not snapshots:
            raise UsageError(f"no workspace snapshots found in {snapshot_dir}")
        return snapshots[0]
    if not name.endswith(".zip"):
        name += ".zip"
    if not SNAPSHOT_RE.fullmatch(name):
        raise UsageError(f"invalid snapshot name: {name}")
    archive_path = snapshot_dir / name
    if not os.path.lexists(archive_path):
        raise UsageError(f"snapshot not found: {archive_path}")
    try:
        mode = os.lstat(archive_path).st_mode
    except OSError as exc:
        raise IntegrityError(f"cannot inspect snapshot: {archive_path}: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise IntegrityError(f"unsafe snapshot is not a regular file: {archive_path}")
    _assert_no_symlink_components(archive_path, "snapshot archive")
    return archive_path


def _target_has_content(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    if not path.is_dir():
        return True
    return any(path.iterdir())


def _move_existing(path: Path, destination: Path) -> bool:
    if not os.path.lexists(path):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))
    return True


def _install_pipeline_metadata(staging: Path, workspace: Path) -> None:
    source = staging / "PIPELINE.md"
    target = workspace / "PIPELINE.md"
    _assert_no_symlink_components(target, "PIPELINE.md restore target")
    if source.is_file():
        os.replace(source, target)

    source_dir = staging / ".pipeline"
    if not source_dir.is_dir():
        return
    target_dir = workspace / ".pipeline"
    _assert_no_symlink_components(target_dir, ".pipeline restore target")
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.rglob("*"), key=lambda path: (len(path.parts), str(path))):
        relative = source_path.relative_to(source_dir)
        target_path = target_dir / relative
        _assert_no_symlink_components(target_path, ".pipeline restore target")
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            _assert_no_symlink_components(target_path.parent, ".pipeline restore parent")
            os.replace(source_path, target_path)


def restore(workspace: Path, snapshot_name: str = "latest", force: bool = False) -> dict:
    workspace = Path(os.path.abspath(workspace))
    _assert_regular_source(workspace, "workspace", directory=True)
    _assert_no_symlink_components(workspace, "workspace")
    archive_path = _resolve_snapshot(workspace, snapshot_name)
    _verify_sidecar(archive_path)

    bundle = workspace / "bundle"
    output = workspace / "output"
    pre_restore: Path | None = None
    staging: Path | None = None
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members:
                raise IntegrityError(f"empty workspace snapshot: {archive_path}")
            _assert_destination_members_safe(workspace, members)
            roots = {_member_parts(info)[0] for info in members}
            if not {"bundle", "output", "PIPELINE.md"}.issubset(roots):
                raise IntegrityError("workspace snapshot is missing required roots")

            occupied = [path.name for path in (bundle, output) if _target_has_content(path)]
            if occupied and not force:
                raise UsageError(
                    "workspace restore target is non-empty, refusing without --force: "
                    + ", ".join(occupied)
                )

            snapshot_dir = _snapshot_dir(workspace)
            staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=snapshot_dir))
            _extract_members(archive, staging)

        _assert_destination_members_safe(workspace, members)
        if force:
            pre_restore = _unique_path(workspace / f".pre-restore-{_stamp()}")
            moved_any = False
            for name in ("bundle", "output", "PIPELINE.md", ".pipeline"):
                moved_any = _move_existing(workspace / name, pre_restore / name) or moved_any
            if not moved_any:
                pre_restore = None
        else:
            for path in (bundle, output):
                if path.is_dir():
                    path.rmdir()

        for name in ("bundle", "output"):
            source = staging / name
            target = workspace / name
            _assert_no_symlink_components(target.parent, "workspace restore parent")
            if os.path.lexists(target):
                raise IntegrityError(f"restore target changed before install: {target}")
            os.replace(source, target)
        _install_pipeline_metadata(staging, workspace)
    except zipfile.BadZipFile as exc:
        raise IntegrityError(f"corrupt or unreadable snapshot: {archive_path}: {exc}") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)

    return {
        "ok": True, "workspace": str(workspace), "snapshot": str(archive_path),
        "sha256_verified": True,
        "pre_restore_backup": str(pre_restore) if pre_restore else None,
    }


def list_snapshots(workspace: Path) -> dict:
    workspace = Path(os.path.abspath(workspace))
    _assert_regular_source(workspace, "workspace", directory=True)
    snapshot_dir = _snapshot_dir(workspace)
    if os.path.lexists(snapshot_dir):
        _assert_regular_source(snapshot_dir, "snapshot directory", directory=True)
        _assert_no_symlink_components(snapshot_dir, "snapshot directory")

    rows = []
    for path in _iter_snapshot_zips(snapshot_dir):
        sidecar = _sidecar_for(path)
        if not sidecar.is_file():
            status = "missing"
        else:
            try:
                expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
                status = "ok" if expected.lower() == _sha256(path).lower() else "mismatch"
            except (OSError, UnicodeError, IndexError):
                status = "error"
        rows.append({"name": path.name, "size": path.stat().st_size,
                     "sha256_status": status})
    return {
        "ok": True, "workspace": str(workspace),
        "snapshot_dir": str(snapshot_dir), "snapshots": rows,
    }


def _print_snapshot(result: dict) -> None:
    print(f"snapshot: {result['snapshot']}")
    print(f"sidecar: {result['sidecar']}")
    print(f"sha256: {result['sha256']}")
    print(f"files_included: {result['files_included']}")
    if result["rotated_removed"]:
        print(f"rotated_removed: {', '.join(result['rotated_removed'])}")


def _print_restore(result: dict) -> None:
    print(f"restored_from: {result['snapshot']}")
    print(f"restored_to: {result['workspace']}")
    print("sha256_verified: true")
    if result["pre_restore_backup"]:
        print(f"pre_restore_backup: {result['pre_restore_backup']}")


def _print_list(result: dict) -> None:
    print(f"snapshot_dir: {result['snapshot_dir']}")
    if not result["snapshots"]:
        print("(no snapshots found)")
        return
    for row in result["snapshots"]:
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
    parser = argparse.ArgumentParser(prog="ws_snapshot.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("snapshot", help="Create a pre-assembly snapshot")
    command.add_argument("workspace", type=Path)
    command.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("restore", help="Restore a workspace snapshot")
    command.add_argument("workspace", type=Path)
    command.add_argument("--snapshot", default="latest", help="Snapshot filename or latest")
    command.add_argument("--force", action="store_true")
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("list", help="List workspace snapshots")
    command.add_argument("workspace", type=Path)
    command.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    try:
        if args.command == "snapshot":
            _emit(snapshot(args.workspace, args.keep), as_json, _print_snapshot)
        elif args.command == "restore":
            _emit(restore(args.workspace, args.snapshot, args.force), as_json, _print_restore)
        elif args.command == "list":
            _emit(list_snapshots(args.workspace), as_json, _print_list)
        else:
            parser.error(f"unknown command: {args.command}")
        return 0
    except UsageError as exc:
        _emit_error(exc, as_json)
        return 2
    except (IntegrityError, OSError, zipfile.BadZipFile, RuntimeError,
            EOFError, UnicodeError) as exc:
        _emit_error(exc, as_json)
        return 3


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
