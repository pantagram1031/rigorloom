#!/usr/bin/env python3
"""sync_local.py -- base+overlay installer for the report-pipeline skill.

The public git checkout (this repo) is *upstream*. The generated install lives
under a Claude skills directory. That install contains DELIBERATE local
operational files (concrete backend commands, personal prompt templates) that
must survive every sync. The solution is base + overlay:

    staged tree = (files copied from the checkout, per source_map)
                  then OVERLAID by every file under overlay_root

Overlay files REPLACE or ADD on top of base files. A per-file receipt records
each file's origin (base|overlay) and sha256 so subsequent syncs can:

  * detect drift  -- an install file hand-edited since the last sync is refused
                     ("edit upstream or move to overlay") unless --force;
  * delete stale  -- a file that was base/overlay-managed last time but is no
                     longer produced is removed;
  * keep unmanaged -- a file that was never synced (unknown origin) is preserved
                     and reported (e.g. a local-only verify_content.py).

The install itself is swapped in atomically: the current install is archived to
<install_root>.bak-<timestamp> via a single rename, then the staged tree is
renamed into place (with a copytree fallback for cross-volume moves, and a
tested rollback that restores the backup on any failure).

Stdlib only. Windows-friendly (set PYTHONIOENCODING=utf-8).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

RECEIPT_NAME = ".sync_receipt.json"
# The lock is a SIBLING of the install root (``<install_root>.sync.lock``), not a
# file inside it — so it survives the atomic rename swap and can be held through
# the unmanaged/excluded copy + swap + receipt write, closing the concurrent-sync
# race that existed when the in-tree lock had to be released before the swap.
LOCK_SUFFIX = ".sync.lock"
STAGING_SUFFIX = '.staging-'
STAGING_OWNER_MARKER = '.sync_staging_owner'
STAGING_OWNER_ID = 'rigorloom.sync_local'
STALE_LOCK_SECONDS = 30 * 60
# Control files live at the install root and are never treated as managed
# content, never compared, never deleted by the sync itself.
CONTROL_PREFIXES = (".sync",)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class SyncError(Exception):
    """Base class for controlled, user-facing sync failures."""


class DriftRefused(SyncError):
    def __init__(self, drifted: List[str]):
        self.drifted = drifted
        listing = "\n".join(f"  - {p}" for p in drifted)
        super().__init__(
            "Refusing to sync: the following install files were hand-edited "
            "since the last sync.\n"
            "Edit them upstream (in the checkout) or move them to the overlay, "
            "then re-run. Use --force to overwrite local edits.\n" + listing
        )


class PathEscape(SyncError):
    pass


class LockHeld(SyncError):
    pass


# --------------------------------------------------------------------------- #
# Minimal YAML subset parser (stdlib only)
# --------------------------------------------------------------------------- #
# Supports exactly what the manifest needs: block mappings, block sequences,
# sequences of mappings (``- key: value`` with aligned continuation lines),
# inline flow lists (``[a, b]``), scalars, quoted scalars, and ``#`` comments.
# Scalar values are taken literally (no escape processing) so Windows paths
# with backslashes survive intact.
def parse_yaml(text: str) -> Any:
    raw_lines = text.splitlines()
    lines: List[Tuple[int, str]] = []
    for raw in raw_lines:
        content = _strip_comment(raw)
        if content.strip() == "":
            continue
        indent = len(content) - len(content.lstrip(" "))
        lines.append((indent, content.strip()))
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, lines[0][0])
    if idx != len(lines):
        raise SyncError(f"manifest parse error near: {lines[idx][1]!r}")
    return value


def _strip_comment(line: str) -> str:
    out = []
    quote: Optional[str] = None
    prev = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#" and (prev == "" or prev == " "):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def _parse_block(lines: List[Tuple[int, str]], i: int, indent: int) -> Tuple[Any, int]:
    if lines[i][1].startswith("- "):
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_seq(lines: List[Tuple[int, str]], i: int, indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or not content.startswith("- "):
            break
        if ind > indent:
            raise SyncError(f"manifest bad indentation near: {content!r}")
        rest = content[2:].strip()
        key_col = indent + 2
        if ":" in rest and not rest.startswith("["):
            # sequence item that is itself a mapping; splice its first line in
            sub: List[Tuple[int, str]] = [(key_col, rest)]
            j = i + 1
            while j < len(lines) and lines[j][0] >= key_col:
                sub.append(lines[j])
                j += 1
            value, consumed = _parse_map(sub, 0, key_col)
            if consumed != len(sub):
                raise SyncError(f"manifest bad list item near: {rest!r}")
            items.append(value)
            i = j
        else:
            items.append(_scalar(rest))
            i += 1
    return items, i


def _parse_map(lines: List[Tuple[int, str]], i: int, indent: int) -> Tuple[Dict[str, Any], int]:
    result: Dict[str, Any] = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or content.startswith("- "):
            break
        if ind > indent:
            raise SyncError(f"manifest bad indentation near: {content!r}")
        if ":" not in content:
            raise SyncError(f"manifest expected 'key: value' near: {content!r}")
        key, _, val = content.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                child, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result[key] = child
            else:
                result[key] = {}
                i += 1
        else:
            result[key] = _scalar(val)
            i += 1
    return result, i


def _scalar(token: str) -> Any:
    token = token.strip()
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if inner == "":
            return []
        return [_scalar(p) for p in _split_flow(inner)]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _split_flow(inner: str) -> List[str]:
    parts: List[str] = []
    buf = []
    quote: Optional[str] = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


# --------------------------------------------------------------------------- #
# Config model
# --------------------------------------------------------------------------- #
@dataclass
class Target:
    name: str
    install_root: str
    overlay_root: Optional[str]
    source_map: List[Dict[str, str]]
    exclude: List[str] = field(default_factory=list)
    # Where the pre-install tree is archived. Default (None) = sibling of
    # install_root. Set this when siblings are harmful — e.g. a Claude skills
    # dir, where a backed-up copy containing SKILL.md registers as a duplicate
    # skill.
    backup_root: Optional[str] = None


def load_manifest(path: str, checkout_root: str) -> List[Target]:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = parse_yaml(fh.read())
    if not isinstance(cfg, dict):
        raise SyncError("manifest root must be a mapping")

    targets: List[Target] = []
    if cfg.get("source_map") or cfg.get("install_root"):
        targets.append(_target_from_section("primary", cfg))

    repo_targets = cfg.get("repo_targets") or []
    if isinstance(repo_targets, list):
        for idx, section in enumerate(repo_targets):
            if not isinstance(section, dict):
                continue
            name = section.get("name") or f"repo_target[{idx}]"
            targets.append(_target_from_section(name, section))

    if not targets:
        raise SyncError("manifest defines no targets (need source_map/install_root)")
    return targets


def _target_from_section(name: str, section: Dict[str, Any]) -> Target:
    install_root = section.get("install_root")
    if not install_root:
        raise SyncError(f"target {name!r}: install_root is required")
    source_map = section.get("source_map") or []
    norm_map: List[Dict[str, str]] = []
    for entry in source_map:
        if not isinstance(entry, dict) or "from" not in entry or "to" not in entry:
            raise SyncError(f"target {name!r}: source_map entries need 'from' and 'to'")
        norm_map.append({"from": str(entry["from"]), "to": str(entry["to"])})
    exclude = section.get("exclude") or []
    if not isinstance(exclude, list):
        raise SyncError(f"target {name!r}: exclude must be a list")
    overlay = section.get("overlay_root")
    backup_root = section.get("backup_root")
    return Target(
        name=name,
        install_root=os.path.abspath(str(install_root)),
        overlay_root=os.path.abspath(str(overlay)) if overlay else None,
        source_map=norm_map,
        exclude=[str(x) for x in exclude],
        backup_root=os.path.abspath(str(backup_root)) if backup_root else None,
    )


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_rel(rel: str) -> str:
    """Normalise an install-relative path to posix and reject escapes."""
    rel = rel.replace("\\", "/")
    normed = os.path.normpath(rel).replace("\\", "/")
    if normed.startswith("..") or normed.startswith("/") or os.path.isabs(normed):
        raise PathEscape(f"path escapes install root: {rel!r}")
    if normed == ".":
        raise PathEscape(f"empty install-relative path: {rel!r}")
    return normed


def _is_control(rel: str) -> bool:
    top = rel.split("/", 1)[0]
    return any(top.startswith(p) for p in CONTROL_PREFIXES)


def _excluded(rel: str, patterns: List[str]) -> bool:
    parts = rel.split("/")
    base = parts[-1]
    for pat in patterns:
        if fnmatch.fnmatch(base, pat):
            return True
        if fnmatch.fnmatch(rel, pat):
            return True
        if any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def _iter_files(root: str, exclude: List[str]) -> List[Tuple[str, str]]:
    """Yield (abs_path, rel_posix) for every non-excluded file under root."""
    out: List[Tuple[str, str]] = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not _excluded(os.path.relpath(os.path.join(dirpath, d), root)
                             .replace("\\", "/"), exclude)
        ]
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace("\\", "/")
            if _excluded(rel, exclude):
                continue
            out.append((ap, rel))
    return out


# --------------------------------------------------------------------------- #
# Receipt
# --------------------------------------------------------------------------- #
def load_receipt(install_root: str) -> Dict[str, Dict[str, str]]:
    path = os.path.join(install_root, RECEIPT_NAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("files", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _git_revision(checkout_root: str) -> str:
    try:
        proc = subprocess.run(
            ['git', '-C', checkout_root, 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    revision = (proc.stdout or '').strip()
    if proc.returncode != 0 or not revision:
        return 'unknown'
    return revision


def _safe_utc_timestamp() -> str:
    """Return an ISO UTC timestamp, or blank when the system clock fails."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return ""


def _safe_backup_stamp() -> str:
    """Return a filesystem-safe local timestamp without making sync clock-bound."""
    try:
        return datetime.now().strftime("%Y%m%d-%H%M%S")
    except Exception:
        return "unknown-time"


def write_receipt(
        dest_root: str, files: Dict[str, Dict[str, str]], checkout_root: str) -> None:
    synced_at = _safe_utc_timestamp()
    payload = {
        'kernel_rev': _git_revision(checkout_root),
        'synced_at': synced_at,
        "version": 1,
        "generated_at": synced_at,
        "files": files,
    }
    with open(os.path.join(dest_root, RECEIPT_NAME), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


# --------------------------------------------------------------------------- #
# Staging + planning
# --------------------------------------------------------------------------- #
@dataclass
class Plan:
    target: Target
    staging_dir: str
    origins: Dict[str, str]            # rel -> base|overlay
    staged_hashes: Dict[str, str]
    install_hashes: Dict[str, str]
    actions: Dict[str, str]           # rel -> add|update|overlay|unchanged
    deletes: List[str]                # stale (was managed, now gone)
    unmanaged: List[str]              # never synced, present in install, keep
    drift: List[str]                  # hand-edited since last receipt
    excluded_preserved: List[str] = field(default_factory=list)
    # install files skipped by an exclude pattern; carried across the swap
    # untouched so the tree swap never silently deletes them

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {"add": 0, "update": 0, "overlay": 0, "unchanged": 0}
        for act in self.actions.values():
            c[act] = c.get(act, 0) + 1
        c["delete"] = len(self.deletes)
        c["unmanaged"] = len(self.unmanaged)
        c["drift"] = len(self.drift)
        c["excluded_preserved"] = len(self.excluded_preserved)
        return c


def _copy_into(src: str, staging: str, rel: str) -> None:
    dst = os.path.join(staging, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def build_staged_tree(target: Target, checkout_root: str, staging: str) -> Dict[str, str]:
    origins: Dict[str, str] = {}
    checkout_root = os.path.abspath(checkout_root)

    # 1. base -- copy mapped files/dirs from the checkout
    for m in target.source_map:
        src = os.path.abspath(os.path.join(checkout_root, m["from"]))
        to = _norm_rel(m["to"])
        if _is_control(to):
            raise PathEscape(f"source_map 'to' targets a control path: {m['to']!r}")
        if not os.path.exists(src):
            raise SyncError(f"source_map 'from' does not exist: {m['from']!r}")
        if os.path.isfile(src):
            origins[to] = "base"
            _copy_into(src, staging, to)
        else:
            for ap, rel in _iter_files(src, target.exclude):
                dest_rel = _norm_rel(f"{to}/{rel}")
                if _is_control(dest_rel):
                    continue
                origins[dest_rel] = "base"
                _copy_into(ap, staging, dest_rel)

    # 2. overlay -- every overlay file REPLACES or ADDS on top of base
    if target.overlay_root and os.path.isdir(target.overlay_root):
        for ap, rel in _iter_files(target.overlay_root, target.exclude):
            dest_rel = _norm_rel(rel)
            if _is_control(dest_rel):
                continue
            origins[dest_rel] = "overlay"
            _copy_into(ap, staging, dest_rel)

    return origins


def _install_hashes(install_root: str, exclude: List[str]) -> Dict[str, str]:
    if not os.path.isdir(install_root):
        return {}
    result: Dict[str, str] = {}
    for ap, rel in _iter_files(install_root, exclude):
        if _is_control(rel):
            continue
        result[rel] = _sha256(ap)
    return result


def _iter_excluded_install_files(install_root: str, exclude: List[str]) -> List[Tuple[str, str]]:
    """Yield (abs, rel) for install files the MANAGED scan skips because they
    match an exclude pattern (or live under an excluded dir). Unlike
    ``_iter_files`` this does NOT prune the walk, so excluded-dir contents are
    seen. Control files (``.sync*``) are still skipped — the sync manages those
    itself. These files must be carried across the atomic swap untouched, else
    the swap silently deletes them."""
    if not os.path.isdir(install_root):
        return []
    out: List[Tuple[str, str]] = []
    install_root = os.path.abspath(install_root)
    for dirpath, _dirnames, filenames in os.walk(install_root):
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, install_root).replace("\\", "/")
            if _is_control(rel):
                continue
            if _excluded(rel, exclude):
                out.append((ap, rel))
    return out


def make_plan(target: Target, checkout_root: str, staging: str) -> Plan:
    origins = build_staged_tree(target, checkout_root, staging)
    staged_hashes = {
        rel: _sha256(os.path.join(staging, rel.replace("/", os.sep)))
        for rel in origins
    }
    install_hashes = _install_hashes(target.install_root, target.exclude)
    receipt = load_receipt(target.install_root)

    # drift: install file whose current hash differs from the last receipt
    drift = sorted(
        rel for rel, info in receipt.items()
        if rel in install_hashes and install_hashes[rel] != info.get("sha256")
    )

    actions: Dict[str, str] = {}
    for rel, origin in origins.items():
        if origin == "overlay":
            actions[rel] = "overlay"
        elif rel not in install_hashes:
            actions[rel] = "add"
        elif install_hashes[rel] != staged_hashes[rel]:
            actions[rel] = "update"
        else:
            actions[rel] = "unchanged"

    deletes: List[str] = []
    unmanaged: List[str] = []
    for rel in install_hashes:
        if rel in origins:
            continue
        if rel in receipt:
            deletes.append(rel)          # was managed, no longer produced
        else:
            unmanaged.append(rel)        # never synced -> keep
    deletes.sort()
    unmanaged.sort()

    # excluded install files: never in origins/install_hashes, so they'd vanish
    # in the swap unless explicitly carried. A managed staged file (e.g. a
    # directly-mapped file that also matches an exclude pattern) wins over the
    # excluded install copy, so drop any that collide with an origin.
    excluded_preserved = sorted({
        rel for _ap, rel in _iter_excluded_install_files(target.install_root, target.exclude)
        if rel not in origins
    })

    return Plan(
        target=target,
        staging_dir=staging,
        origins=origins,
        staged_hashes=staged_hashes,
        install_hashes=install_hashes,
        actions=actions,
        deletes=deletes,
        unmanaged=unmanaged,
        drift=drift,
        excluded_preserved=excluded_preserved,
    )


# --------------------------------------------------------------------------- #
# Orphan garbage collection
# --------------------------------------------------------------------------- #
def _staging_prefix(install_root: str) -> str:
    return f'{os.path.basename(os.path.abspath(install_root))}{STAGING_SUFFIX}'


def _write_staging_owner_marker(staging: str) -> None:
    marker = os.path.join(staging, STAGING_OWNER_MARKER)
    with open(marker, 'w', encoding='utf-8') as handle:
        handle.write(f'{STAGING_OWNER_ID} pid={os.getpid()}\n')


def _owned_staging_dir(path: str) -> bool:
    marker = os.path.join(path, STAGING_OWNER_MARKER)
    try:
        marker_stat = os.stat(marker, follow_symlinks=False)
        if not stat.S_ISREG(marker_stat.st_mode):
            return False
        with open(marker, 'r', encoding='utf-8') as handle:
            return handle.read(256).startswith(STAGING_OWNER_ID + ' ')
    except (FileNotFoundError, OSError, UnicodeError):
        return False


def _pid_is_alive(pid: int) -> bool:
    """Best-effort liveness check for the marker's owner PID."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import subprocess as _sp
        try:
            out = _sp.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                          capture_output=True, text=True, timeout=10)
        except (OSError, _sp.SubprocessError):
            return True  # cannot determine -> assume alive (never delete a live tree)
        return str(pid) in (out.stdout or '')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return True
    return True


def _staging_owner_is_dead(path: str) -> bool:
    """A marked staging dir is GC-eligible only if its owner PID is NOT alive.
    Missing/unparseable PID -> treat as ALIVE (never delete) — a concurrent live
    sync's staging tree must not be removed out from under it."""
    marker = os.path.join(path, STAGING_OWNER_MARKER)
    try:
        with open(marker, 'r', encoding='utf-8') as handle:
            text = handle.read(256)
    except (FileNotFoundError, OSError, UnicodeError):
        return False
    m = re.search(r'\bpid=(\d+)', text)
    if not m:
        return False  # no PID recorded -> cannot prove dead -> keep
    return not _pid_is_alive(int(m.group(1)))


def _foreign_lock_is_live(path: str) -> bool:
    """Return whether a POSIX lock file is held with flock; Windows probes by delete."""
    if os.name == 'nt':
        return False
    import fcntl
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def gc_target_orphans(target: Target) -> List[str]:
    install_root = os.path.abspath(target.install_root)
    parent = os.path.dirname(install_root) or '.'
    prefix = _staging_prefix(install_root)
    cleared: List[str] = []

    try:
        entries = list(os.scandir(parent))
    except FileNotFoundError:
        entries = []
    except OSError as exc:
        raise SyncError(f'cannot scan for sync orphans in {parent}: {exc}') from exc

    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        try:
            owned_staging_dir = entry.is_dir(follow_symlinks=False)
        except OSError as exc:
            raise SyncError(f'cannot inspect staging orphan {entry.path}: {exc}') from exc
        if not owned_staging_dir:
            continue
        if not _owned_staging_dir(entry.path):
            print(f'  gc kept foreign staging {entry.path} (ownership marker missing)')
            continue
        if not _staging_owner_is_dead(entry.path):
            print(f'  gc kept staging {entry.path} (owner process still alive)')
            continue
        try:
            shutil.rmtree(entry.path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SyncError(f'cannot remove staging orphan {entry.path}: {exc}') from exc
        cleared.append(entry.path)
        print(f'  gc cleared {entry.path}')

    lock_path = install_root + LOCK_SUFFIX
    try:
        lock_stat = os.stat(lock_path, follow_symlinks=False)
    except FileNotFoundError:
        return cleared
    except OSError as exc:
        raise SyncError(f'cannot inspect sync lock {lock_path}: {exc}') from exc

    age = time.time() - lock_stat.st_mtime
    if not stat.S_ISREG(lock_stat.st_mode) or age <= STALE_LOCK_SECONDS:
        return cleared
    if _foreign_lock_is_live(lock_path):
        print(f'  gc kept live lock {lock_path} (flock held)')
        return cleared
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        return cleared
    except PermissionError:
        if os.name == 'nt':
            print(f'  gc kept live lock {lock_path} (open handle)')
            return cleared
        raise
    except OSError as exc:
        raise SyncError(f'cannot remove stale sync lock {lock_path}: {exc}') from exc
    cleared.append(lock_path)
    print(f'  gc cleared {lock_path}')
    return cleared


# --------------------------------------------------------------------------- #
# Locking
# --------------------------------------------------------------------------- #
class InstallLock:
    def __init__(self, install_root: str, force: bool):
        self.install_root = os.path.abspath(install_root)
        self.force = force
        # sibling of the install root, in its PARENT dir — never inside the tree
        self.path = self.install_root + LOCK_SUFFIX
        self.acquired = False
        # Per-instance ownership token (pid + uuid) written into the lock file.
        # release() only unlinks a file that still carries OUR token, so a lock
        # stolen/overwritten by another holder is never deleted out from under it.
        self.token = f"pid={os.getpid()} uuid={uuid.uuid4().hex}"

    def _payload(self) -> str:
        return f"{self.token} at={_safe_utc_timestamp()}\n"

    def _create_exclusive(self) -> None:
        """Atomically create the lock file carrying our token. O_CREAT|O_EXCL
        makes creation-if-absent a single atomic syscall, closing the
        exists()-then-open TOCTOU race where two acquirers could both see
        'missing' and both proceed. Raises FileExistsError if it already
        exists.

        The fd is kept OPEN for the lock's lifetime: on Windows an open handle
        (default sharing mode) blocks os.remove from any other process, so a
        forced steal cannot delete the lock out from under a live holder —
        which closes the read-token-then-unlink race in release(). POSIX allows
        unlinking open files, so there we additionally hold flock(LOCK_EX) on
        the fd for the lock lifetime; liveness is probed via flock, not remove."""
        self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        if os.name != "nt":
            import fcntl
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(self._fd, self._payload().encode("utf-8"))
        self.acquired = True

    @staticmethod
    def _foreign_lock_is_live(path: str) -> bool:
        """Share the POSIX liveness probe used by orphan GC."""
        return _foreign_lock_is_live(path)

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        try:
            self._create_exclusive()
            return
        except FileExistsError:
            pass
        # Lock already present -> held by someone else. A plain acquire NEVER
        # steals it (that was the old race). Only --force may take it over, and
        # only after reading + reporting the existing holder's token.
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                existing = fh.read().strip()
        except OSError:
            existing = "<unreadable>"
        try:
            age = int(time.time() - os.path.getmtime(self.path))
        except OSError:
            age = -1
        stale = age >= 0 and age > STALE_LOCK_SECONDS
        if not self.force:
            raise LockHeld(
                f"another sync holds {self.path} "
                f"(age {age}s{', stale' if stale else ''}, held by {existing!r}). "
                f"Use --force to override."
            )
        # forced steal: old token already reported above; replace the file.
        # Liveness guard differs by platform: Windows -> os.remove fails while
        # the holder's handle is open; POSIX -> unlink always succeeds on open
        # files, so probe the holder's flock instead.
        if os.name != "nt" and self._foreign_lock_is_live(self.path):
            raise LockHeld(
                f"lock {self.path} is held by a LIVE process (flock); --force "
                f"only recovers dead locks."
            )
        try:
            os.remove(self.path)
        except OSError:
            pass
        try:
            self._create_exclusive()
        except FileExistsError:
            # re-created between remove and create -> a live holder raced back
            # in; refuse rather than clobber a lock we could not exclusively take.
            raise LockHeld(
                f"lock {self.path} was re-acquired during a forced steal; aborting."
            )

    def release(self) -> None:
        if not self.acquired:
            return
        self.acquired = False
        # Only unlink if the file still carries OUR token. If a foreign holder
        # overwrote or re-created it (forced steal, manual edit), leave it in
        # place and warn — deleting it would release a lock we no longer own.
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                current = fh.read()
        except FileNotFoundError:
            self._close_fd()
            return
        except OSError:
            current = ""
        if self.token in current:
            # Close our held fd only now: while it was open, Windows sharing
            # semantics blocked any foreign os.remove, so the token we just
            # verified cannot have been swapped by a forced steal. The residual
            # close-to-unlink window requires a manual --force steal landing in
            # those microseconds on the operator's own machine — accepted.
            self._close_fd()
            try:
                os.remove(self.path)
            except OSError:
                pass
        else:
            self._close_fd()
            print(
                f"WARNING: not removing {self.path}: it no longer carries our "
                f"lock token (foreign holder).",
                file=sys.stderr,
            )

    def _close_fd(self) -> None:
        fd = getattr(self, "_fd", None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "InstallLock":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# --------------------------------------------------------------------------- #
# Atomic install
# --------------------------------------------------------------------------- #
def _place_staged(staging: str, install_root: str) -> None:
    """Move the staged tree into place; copytree fallback for cross-volume."""
    try:
        os.rename(staging, install_root)
    except OSError:
        shutil.copytree(staging, install_root)
        shutil.rmtree(staging, ignore_errors=True)


def _atomic_install(staging: str, install_root: str, backup_root: Optional[str] = None) -> str:
    ts = _safe_backup_stamp()
    if backup_root:
        os.makedirs(backup_root, exist_ok=True)
        base = os.path.join(backup_root, f"{os.path.basename(install_root)}.bak-{ts}")
    else:
        base = f"{install_root}.bak-{ts}"
    bak = base
    n = 0
    while os.path.exists(bak):
        n += 1
        bak = f"{base}-{n}"
    backed = False
    try:
        if os.path.exists(install_root):
            try:
                os.rename(install_root, bak)
            except OSError:
                # cross-volume backup_root: copy then remove
                shutil.copytree(install_root, bak)
                shutil.rmtree(install_root)
            backed = True
        _place_staged(staging, install_root)
        return bak
    except Exception:
        # rollback: discard any partial install, restore the backup verbatim
        if backed:
            if os.path.exists(install_root):
                shutil.rmtree(install_root, ignore_errors=True)
            if os.path.exists(bak):
                try:
                    os.rename(bak, install_root)
                except OSError:
                    shutil.copytree(bak, install_root)
        raise


def apply_plan(plan: Plan, checkout_root: str) -> str:
    target = plan.target
    staging = plan.staging_dir

    # carry unmanaged (never-synced, unknown-origin) files into the new tree
    for rel in plan.unmanaged:
        src = os.path.join(target.install_root, rel.replace("/", os.sep))
        if os.path.exists(src):
            _copy_into(src, staging, rel)

    # carry excluded install files untouched (same as unmanaged) so the swap
    # never deletes a file the exclude patterns kept out of the managed set
    for rel in plan.excluded_preserved:
        src = os.path.join(target.install_root, rel.replace("/", os.sep))
        if os.path.exists(src):
            _copy_into(src, staging, rel)

    # fresh receipt records only managed (base/overlay) files
    receipt_files = {
        rel: {"sha256": plan.staged_hashes[rel], "origin": plan.origins[rel]}
        for rel in plan.origins
    }
    write_receipt(staging, receipt_files, checkout_root)

    backup = _atomic_install(staging, target.install_root, target.backup_root)
    installed_marker = os.path.join(target.install_root, STAGING_OWNER_MARKER)
    try:
        os.remove(installed_marker)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(
            f'WARNING: could not remove staging ownership marker '
            f'{installed_marker}: {exc}',
            file=sys.stderr,
        )
    return backup


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _print_plan(plan: Plan, dry_run: bool) -> None:
    tag = "DRY-RUN" if dry_run else "SYNC"
    print(f"[{tag}] target={plan.target.name} install_root={plan.target.install_root}")
    if plan.target.overlay_root:
        print(f"        overlay_root={plan.target.overlay_root}")

    ordered = [
        ("overlay", "overlay"),
        ("add", "add"),
        ("update", "update"),
    ]
    for act, label in ordered:
        for rel in sorted(r for r, a in plan.actions.items() if a == act):
            print(f"  {label:9s} {rel}")
    for rel in plan.deletes:
        print(f"  {'delete':9s} {rel}")
    for rel in plan.unmanaged:
        print(f"  {'unmanaged':9s} {rel}  (kept; never synced)")
    for rel in plan.excluded_preserved:
        print(f"  {'excluded':9s} {rel}  (kept; matches exclude pattern)")
    for rel in plan.drift:
        print(f"  {'drift':9s} {rel}  (hand-edited since last sync)")

    c = plan.counts()
    summary = ", ".join(f"{k}={c[k]}" for k in
                        ("add", "update", "overlay", "unchanged", "delete",
                         "unmanaged", "excluded_preserved", "drift"))
    print(f"  -> {summary}")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run_target(target: Target, checkout_root: str, dry_run: bool, force: bool) -> Plan:
    parent = os.path.dirname(os.path.abspath(target.install_root)) or "."
    os.makedirs(parent, exist_ok=True)
    if not dry_run:
        gc_target_orphans(target)
    staging = tempfile.mkdtemp(
        prefix=_staging_prefix(target.install_root), dir=parent
    )
    lock = InstallLock(target.install_root, force=force)
    try:
        _write_staging_owner_marker(staging)
        lock.acquire()
        plan = make_plan(target, checkout_root, staging)
        if plan.drift and not force:
            _print_plan(plan, dry_run=True)
            raise DriftRefused(plan.drift)
        _print_plan(plan, dry_run=dry_run)
        if not dry_run:
            # The sibling lock lives OUTSIDE the install tree, so it survives the
            # rename swap — hold it through the unmanaged/excluded copy + swap +
            # receipt (released only in finally), closing the concurrent-sync race.
            bak = apply_plan(plan, checkout_root)
            print(f"  installed. previous tree archived to: {bak}")
        return plan
    finally:
        lock.release()
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def default_checkout_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_manifest(checkout_root: str) -> str:
    return os.path.join(checkout_root, "scripts", "sync_manifest.example.yaml")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="base+overlay installer for the report-pipeline skill"
    )
    parser.add_argument("--manifest", default=None,
                        help="manifest YAML (default: scripts/sync_manifest.example.yaml)")
    parser.add_argument("--checkout-root", default=None,
                        help="checkout root for source_map 'from' paths (default: repo root)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print per-file actions and exit without changes")
    parser.add_argument("--force", action="store_true",
                        help="overwrite drifted files and steal a stale lock")
    parser.add_argument("--gc", action="store_true",
                        help="remove owned staging orphans and stale locks, then exit")
    parser.add_argument("--only", default=None,
                        help="process only the named target")
    args = parser.parse_args(argv)

    checkout_root = os.path.abspath(args.checkout_root or default_checkout_root())
    manifest = args.manifest or default_manifest(checkout_root)
    if not os.path.exists(manifest):
        print(f"manifest not found: {manifest}", file=sys.stderr)
        return 2

    try:
        targets = load_manifest(manifest, checkout_root)
        if args.only:
            targets = [t for t in targets if t.name == args.only]
            if not targets:
                print(f"no target named {args.only!r}", file=sys.stderr)
                return 2
        for target in targets:
            if args.gc:
                gc_target_orphans(target)
            else:
                run_target(
                    target,
                    checkout_root,
                    dry_run=args.dry_run,
                    force=args.force,
                )
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; output may contain
    non-ASCII. Reconfigure stdio so printing never dies with UnicodeEncodeError
    (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
