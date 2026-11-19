#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The one function that writes into a person's folder, and its undo.

Everything else in PLATFORM writes only under the state directory. A write
here is bound to what the caller saw: the exact candidate bytes (by full
sha256) and the target's expected state (absent, or a full sha256). If either
moved, nothing is written.

Before any existing file is replaced, its bytes go to history, so
``undo`` can put them back; ``undo`` itself only restores over bytes that
this module wrote (it checks), never over something the person saved since.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

try:  # installed as rigorloom_runtime
    from .rt_drafts import _Lock, key_for_path
    from .rt_paths import (PathRefused, create_new, mark_state, private_dir, replace_checked,
                           sha256_bytes, sha256_file, state_home)
    from .rt_tools import ToolError
except ImportError:  # a checkout, runtime/scripts on sys.path
    from rt_drafts import _Lock, key_for_path
    from rt_paths import (PathRefused, create_new, mark_state, private_dir, replace_checked,
                          sha256_bytes, sha256_file, state_home)
    from rt_tools import ToolError

ABSENT = "absent"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history_dir(home: Path, target: Path) -> Path:
    mark_state(home)
    return home / "history" / key_for_path(target)


def _load_index(folder: Path) -> list[dict]:
    path = folder / "index.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_index(folder: Path, entries: list[dict]) -> None:
    temp = folder / f".index.{secrets.token_hex(4)}.tmp"
    temp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, folder / "index.json")


def _refusal(exc: PathRefused) -> ToolError:
    hints = {
        "target_exists": "다른 이름을 고르거나, 덮어쓰려면 사람이 확인해야 합니다.",
        "target_changed": "파일을 다시 열어 최신 내용으로 확인한 뒤 저장하세요.",
        "locked": "한글에서 파일을 닫은 뒤 다시 저장하거나, 다른 이름으로 저장하세요.",
        "not_found": "저장할 폴더가 있는지 확인하세요.",
    }
    return ToolError(exc.code if exc.code in hints else "invalid_params",
                     exc.message, hint=hints.get(exc.code), at=exc.path,
                     retryable=exc.code == "locked")


def _lock(folder: Path):
    """One commit or undo per target at a time, across processes."""
    return _Lock(private_dir(folder) / ".lock", code="locked",
                 message="다른 저장이 이 파일에 쓰는 중입니다.")


def _settled(entries: list[dict], target: Path) -> list[dict]:
    """History as it really happened.

    An entry is written as ``pending`` before the file is published and marked
    ``done`` after. A crash in between leaves ``pending``: if the target holds
    the new bytes it was published, otherwise it never was.
    """
    if not entries or entries[-1].get("state") != "pending":
        return entries
    last = entries[-1]
    current = sha256_file(target) if target.exists() else None
    last["state"] = "done" if current == last["newSha256"] else "failed"
    return entries


def _done(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e.get("state", "done") == "done"]


def commit(candidate: Path, target: Path, *, expected: str, by: str,
           policy: str, home: Path | None = None,
           provenance: dict | None = None, candidate_sha256: str | None = None,
           draft: str | None = None) -> dict:
    """Publish ``candidate``'s bytes at ``target``.

    ``expected`` is ``"absent"`` (create only) or the full sha256 the target
    must still have. ``candidate_sha256``, when given, is the digest the
    caller approved: other bytes are refused, not published. ``draft`` names
    the draft that wrote it (the own-file exemption is per draft).
    ``provenance`` (``{"mock": bool, ...}``) goes into the history entry and
    the receipt unchanged, so a test-only proposal stays labelled wherever its
    bytes end up. Returns a receipt; raises ToolError and writes nothing when
    a binding does not hold.
    """
    home = Path(home) if home else state_home()
    data = candidate.read_bytes()
    new_sha = sha256_bytes(data)
    if candidate_sha256 is not None and new_sha != candidate_sha256:
        raise ToolError("stale", "확인받은 뒤 초안이 바뀌어 저장하지 않았습니다.",
                        hint="초안을 다시 확인하고 저장하세요.", retryable=True,
                        data={"reason": "superseded_by_newer_candidate"})
    folder = private_dir(_history_dir(home, target))
    with _lock(folder):
        entries = _settled(_load_index(folder), target)
        entry = {"at": _now(), "target": str(target), "newSha256": new_sha,
                 "by": by, "policy": policy, "draft": draft, "oldSha256": None,
                 "kept": None, "provenance": provenance or {"mock": False},
                 "state": "pending"}
        try:
            if expected == ABSENT:
                if target.exists() or target.is_symlink():
                    raise PathRefused("target_exists",
                                      f"같은 이름이 이미 있어 새 파일을 만들 수 없습니다({target}).",
                                      str(target))
                entries.append(entry)
                _save_index(folder, entries)
                create_new(target, data)
            else:
                current = sha256_file(target) if target.exists() else None
                if current != expected:
                    raise ToolError("target_changed",
                                    "저장하려는 사이에 대상 파일이 바뀌었습니다.",
                                    hint="파일을 다시 열어 확인한 뒤 저장하세요.",
                                    at=str(target))
                kept = folder / f"{entry['at'].replace(':', '')}-{secrets.token_hex(3)}" \
                                f"-{expected[:12]}{target.suffix}"
                _write_durable(kept, target.read_bytes())
                if sha256_file(kept) != expected:
                    raise ToolError("internal", "저장 기록에 이전 판을 보관하지 못했습니다.")
                entry["oldSha256"] = expected
                entry["kept"] = kept.name
                entries.append(entry)
                _save_index(folder, entries)
                replace_checked(target, data, expected)
        except PathRefused as exc:
            _drop_pending(folder, entries, entry)
            raise _refusal(exc) from exc
        except BaseException:
            _drop_pending(folder, entries, entry)
            raise
        entry["state"] = "done"
        _save_index(folder, entries)
    return {"target": str(target), "sha256": new_sha, "replaced": entry["oldSha256"],
            "policy": policy, "by": by, "at": entry["at"],
            "provenance": entry["provenance"], "undo": True}


def _write_durable(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _drop_pending(folder: Path, entries: list[dict], entry: dict) -> None:
    """The publish did not happen: the pending entry goes, unless it did."""
    if entry in entries:
        _settled(entries, Path(entry["target"]))
        if entry.get("state") != "done":
            entries.remove(entry)
        try:
            _save_index(folder, entries)
        except OSError:
            pass


def last_commit(target: Path, home: Path | None = None) -> dict | None:
    home = Path(home) if home else state_home()
    entries = _done(_settled(_load_index(_history_dir(home, target)), target))
    return entries[-1] if entries else None


def owned(target: Path, home: Path | None = None, *, draft: str | None = None) -> bool:
    """May ``draft`` re-save over ``target`` without asking?

    Only when that draft created the file, every save since was its own
    policy save, nothing was undone, and the file still holds the bytes of the
    last one. A person's approval to replace a file is for that save alone.
    """
    if draft is None or not target.exists():
        return False
    home = Path(home) if home else state_home()
    entries = _done(_settled(_load_index(_history_dir(home, target)), target))
    created = [i for i, e in enumerate(entries) if e.get("oldSha256") is None]
    if not created:
        return False
    since = entries[created[-1]:]
    if any(e.get("draft") != draft or e.get("undone")
           or e.get("policy") not in ("policy:new-file", "policy:own-file") for e in since):
        return False
    return sha256_file(target) == since[-1]["newSha256"]


def declined(target: Path, digest: str, home: Path | None = None) -> bool:
    """Did a person already say no to these bytes at this target, from any draft?"""
    home = Path(home) if home else state_home()
    path = _history_dir(home, target) / "declines.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(r.get("sha256") == digest for r in rows if isinstance(r, dict))


def record_decline(target: Path, digest: str, *, by: str, home: Path | None = None) -> None:
    home = Path(home) if home else state_home()
    folder = private_dir(_history_dir(home, target))
    with _lock(folder):
        path = folder / "declines.json"
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        rows.append({"sha256": digest, "target": str(target), "by": by, "at": _now()})
        temp = folder / f".declines.{secrets.token_hex(4)}.tmp"
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, path)


def _last_undoable(entries: list[dict], target: Path, folder: Path) -> dict:
    done = _done(entries)
    if not done:
        raise ToolError("not_found", "이 파일에는 되돌릴 저장 기록이 없습니다.", at=str(target),
                        hint="Rigorloom으로 저장한 파일만 되돌릴 수 있습니다.")
    entry = done[-1]
    if entry.get("undone"):
        raise ToolError("not_found", "마지막 저장은 이미 되돌렸습니다.", at=str(target))
    current = sha256_file(target) if target.exists() else None
    if current != entry["newSha256"]:
        raise ToolError("target_changed",
                        "마지막으로 저장한 뒤 파일이 바뀌어 되돌리지 않았습니다.",
                        hint="지금 내용을 지키려면 그대로 두세요. 이전 판은 저장 기록에 남아 있습니다.",
                        at=str(target), data={"history": str(folder)})
    return entry


def undoable(target: Path, home: Path | None = None) -> dict:
    """The history entry ``undo`` would reverse now, or the ToolError it would raise.

    A preview for asking the person first; ``undo`` checks again under the lock.
    """
    home = Path(home) if home else state_home()
    folder = _history_dir(home, target)
    return _last_undoable(_settled(_load_index(folder), target), target, folder)


def undo(target: Path, *, by: str, home: Path | None = None) -> dict:
    """Put back what the last commit replaced, if the file is still ours.

    The bytes undo displaces go to history too, so undo itself can be undone
    by hand from the history folder.
    """
    home = Path(home) if home else state_home()
    folder = private_dir(_history_dir(home, target))
    with _lock(folder):
        entries = _settled(_load_index(folder), target)
        entry = _last_undoable(entries, target, folder)
        current = sha256_file(target) if target.exists() else None
        stamp = f"{_now().replace(':', '')}-{secrets.token_hex(3)}"
        try:
            if entry["oldSha256"] is None:
                # We created this file; undo removes it by moving it into history.
                kept = folder / f"{stamp}-created-{current[:12]}{target.suffix}"
                os.replace(target, kept)
                restored = None
            else:
                old = (folder / entry["kept"]).read_bytes()
                if sha256_bytes(old) != entry["oldSha256"]:
                    raise ToolError("internal",
                                    "보관한 이전 판이 저장 기록과 달라 되돌릴 수 없습니다.",
                                    at=str(folder / entry["kept"]))
                _write_durable(folder / f"{stamp}-undone-{current[:12]}{target.suffix}",
                               target.read_bytes())
                replace_checked(target, old, current)
                restored = entry["oldSha256"]
        except PathRefused as exc:
            raise _refusal(exc) from exc
        entry["undone"] = {"at": _now(), "by": by}
        _save_index(folder, entries)
    return {"target": str(target), "restored": restored,
            "removed": entry["oldSha256"] is None}
