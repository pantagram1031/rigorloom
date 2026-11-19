#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where Rigorloom may read and write, and how it writes without losing a file.

Two jobs, both small and both easy to get wrong:

1. CONFINEMENT. An agent names paths; the person decided which folders it may
   touch (MCP roots, ``--allow``). ``Roots.check`` resolves a path at USE time
   (symlinks and junctions followed, ``..`` collapsed) and refuses anything
   outside, plus the Windows names that are not files at all (``CON``,
   ``NUL``, ``COM1``), alternate data streams (``a.hwpx:secret``) and empty or
   NUL-bearing strings. A check made when a path was first seen is not enough:
   the folder can change between the check and the open.

2. WRITING. ``create_new`` never replaces an existing file, even under a race
   (hard link on POSIX, rename-without-replace on Windows). ``replace_checked``
   overwrites only when the target still has the bytes we expect, and turns a
   file another program holds open (Hancom on Windows) into a ``locked``
   refusal instead of a half-written document.

Stdlib only.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_WINDOWS_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)])


class PathRefused(Exception):
    """A path the caller may not use. ``code`` is from the tool error set."""

    def __init__(self, code: str, message: str, path: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(path: Path) -> str:
    """Comparison key: case-folded on Windows, exact elsewhere."""
    return os.path.normcase(str(path))


def _validate_text(raw: str) -> None:
    if not raw or not raw.strip():
        raise PathRefused("invalid_params", "경로가 비어 있습니다.")
    if "\x00" in raw:
        raise PathRefused("invalid_params", "경로에 NUL 문자가 있습니다.", raw)


def _validate_components(path: Path) -> None:
    """Refuse names Windows treats as devices or streams, on every platform.

    Checked everywhere, not only on Windows, so a document folder shared
    between the two systems never ends up holding a name one of them cannot
    open.
    """
    parts = path.parts
    for index, part in enumerate(parts):
        if index == 0 and (path.anchor and part == path.anchor):
            continue
        stem = part.split(".", 1)[0].rstrip(" ").upper()
        if stem in _WINDOWS_RESERVED:
            raise PathRefused("invalid_params",
                              f"'{part}'는 Windows에서 장치 이름이라 쓸 수 없습니다.",
                              str(path))
        if ":" in part:
            raise PathRefused("invalid_params",
                              f"'{part}'에 콜론이 있습니다(대체 데이터 스트림).",
                              str(path))


def canonical(raw: str | os.PathLike, base: Path | None = None) -> Path:
    """Absolute, symlink-resolved path. Does not require the path to exist."""
    text = os.fspath(raw)
    _validate_text(text)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    resolved = Path(os.path.realpath(path))
    _validate_components(resolved)
    return resolved


@dataclass
class Roots:
    """Folders the person allowed. Empty means nothing is allowed."""

    paths: list[Path] = field(default_factory=list)

    @classmethod
    def of(cls, items: Iterable[str | os.PathLike]) -> "Roots":
        out: list[Path] = []
        seen: set[str] = set()
        for item in items:
            path = canonical(item)
            key = _norm(path)
            if key not in seen:
                seen.add(key)
                out.append(path)
        return cls(out)

    def contains(self, path: Path) -> bool:
        key = _norm(path)
        for root in self.paths:
            root_key = _norm(root)
            if key == root_key or key.startswith(root_key.rstrip(os.sep) + os.sep):
                return True
        return False

    def check(self, raw: str | os.PathLike, *, base: Path | None = None) -> Path:
        """The resolved path, or ``PathRefused('outside_roots')``."""
        path = canonical(raw, base)
        if not self.contains(path):
            shown = ", ".join(str(r) for r in self.paths) or "(없음)"
            raise PathRefused(
                "outside_roots",
                f"허용한 폴더 밖의 경로입니다: {path} (허용: {shown})", str(path))
        return path


def check_readable(path: Path) -> Path:
    if not path.exists():
        raise PathRefused("not_found", f"파일이 없습니다: {path}", str(path))
    if not path.is_file():
        raise PathRefused("invalid_params", f"파일이 아닙니다: {path}", str(path))
    return path


def _temp_beside(target: Path) -> Path:
    return target.with_name(f".{target.name}.{secrets.token_hex(6)}.tmp")


def create_new(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` only if ``target`` does not exist.

    The temporary file sits in the target's own folder so the final step is a
    same-volume link or rename, never a copy that can be seen half-written.
    """
    if not target.parent.is_dir():
        raise PathRefused("not_found", f"폴더가 없습니다: {target.parent}",
                          str(target))
    if target.exists() or target.is_symlink():
        raise PathRefused("target_exists", f"이미 있는 파일입니다: {target}",
                          str(target))
    temp = _temp_beside(target)
    with open(temp, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if os.name == "nt":
            # os.rename refuses to replace an existing file on Windows.
            os.rename(temp, target)
        else:
            os.link(temp, target)  # fails with EEXIST instead of replacing
            os.unlink(temp)
    except FileExistsError as exc:
        _quiet_unlink(temp)
        raise PathRefused("target_exists", f"이미 있는 파일입니다: {target}",
                          str(target)) from exc
    except PermissionError as exc:
        _quiet_unlink(temp)
        raise PathRefused("locked", f"다른 프로그램이 쓰고 있는 위치입니다: {target}",
                          str(target)) from exc
    except OSError:
        _quiet_unlink(temp)
        raise


def replace_checked(target: Path, data: bytes, expected_sha256: str) -> None:
    """Overwrite ``target`` only while it still holds ``expected_sha256``.

    There is a gap between the final hash check and the rename that no
    portable API closes; a program saving in that instant can still lose to
    us. The window is one ``os.replace`` wide, and the old bytes are always
    kept by the caller (history) before this runs.
    """
    if not target.exists():
        raise PathRefused("target_changed", f"파일이 사라졌습니다: {target}",
                          str(target))
    temp = _temp_beside(target)
    with open(temp, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if sha256_file(target) != expected_sha256:
            raise PathRefused("target_changed",
                              f"저장하려는 사이에 파일이 바뀌었습니다: {target}",
                              str(target))
        os.replace(temp, target)
    except PathRefused:
        _quiet_unlink(temp)
        raise
    except PermissionError as exc:
        _quiet_unlink(temp)
        raise PathRefused(
            "locked",
            f"다른 프로그램(한글 등)이 파일을 열고 있어 덮어쓸 수 없습니다: {target}",
            str(target)) from exc
    except OSError:
        _quiet_unlink(temp)
        raise


def _quiet_unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def state_home() -> Path:
    """Where drafts, history and previews live. Never next to the person's files.

    ``RIGORLOOM_HOME`` wins. Otherwise ``%LOCALAPPDATA%\\Rigorloom`` on Windows
    and ``$XDG_STATE_HOME/rigorloom`` (default ``~/.local/state/rigorloom``)
    elsewhere.
    """
    env = os.environ.get("RIGORLOOM_HOME")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Rigorloom"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "rigorloom"


def private_dir(path: Path) -> Path:
    """Create ``path`` (and parents) readable only by this user where we can."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


if __name__ == "__main__":  # pragma: no cover - manual probe
    print(state_home())
    sys.exit(0)
