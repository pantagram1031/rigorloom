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
        "target_exists": "다른 파일 이름을 지정하세요. 기존 파일을 덮어쓰려면 사용자 확인이 필요합니다.",
        "target_changed": "파일을 다시 열어 최신 내용을 확인한 뒤 저장하세요.",
        "locked": "한글에서 파일을 닫은 뒤 다시 저장하거나, 다른 이름으로 저장하세요.",
        "not_found": "저장할 폴더가 있는지 확인하세요.",
    }
    return ToolError(exc.code if exc.code in hints else "invalid_params",
                     exc.message, hint=hints.get(exc.code), at=exc.path,
                     retryable=exc.code == "locked")


def _lock(folder: Path):
    """One commit or undo per target at a time, across processes."""
    return _Lock(private_dir(folder) / ".lock", code="locked",
                 message="다른 작업이 이 파일을 저장하고 있습니다.")


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
    if last["state"] == "done":
        # Matching bytes cannot tell our publish from an identical copy put
        # there by someone else (Sol re-check F4): such an entry never makes
        # the file "ours", and undo will not remove a file it may not own.
        last["settled"] = "digest"
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
        raise ToolError("stale", "덮어쓰기를 확인한 뒤 초안이 바뀌어 저장하지 않았습니다.",
                        hint="초안을 다시 확인하고 저장하세요.", retryable=True,
                        data={"reason": "superseded_by_newer_candidate"})
    folder = private_dir(_history_dir(home, target))
    with _lock(folder):
        entries = _settled(_load_index(folder), target)
        entry = {"id": secrets.token_hex(8), "at": _now(), "target": str(target),
                 "newSha256": new_sha,
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
                    raise ToolError("internal", "이전 파일 내용을 저장 기록에 보관하지 못했습니다.")
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
    return owned_sha256(target, home, draft=draft) is not None


def owned_sha256(target: Path, home: Path | None = None, *,
                 draft: str | None = None) -> str | None:
    """The digest ``owned()`` matched, or None when the file is not ours.

    A save under ``policy:own-file`` passes this value as ``expected``, never a
    fresh hash of the target: bytes written by someone else after this check
    then fail the commit with ``target_changed`` instead of being replaced.
    """
    if draft is None or not target.exists():
        return None
    home = Path(home) if home else state_home()
    entries = _done(_settled(_load_index(_history_dir(home, target)), target))
    created = [i for i, e in enumerate(entries) if e.get("oldSha256") is None]
    if not created:
        return None
    since = entries[created[-1]:]
    if any(e.get("draft") != draft or e.get("undone") or e.get("settled")
           or e.get("policy") not in ("policy:new-file", "policy:own-file") for e in since):
        return None
    last = since[-1]["newSha256"]
    return last if sha256_file(target) == last else None


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
    if entry.get("oldSha256") is None and entry.get("settled"):
        raise ToolError("target_changed",
                        "저장이 끝났는지 확인할 수 없어 되돌리지 않았습니다.",
                        hint="Rigorloom이 만든 파일인지 확인한 뒤 직접 정리하세요.",
                        at=str(target), data={"history": str(folder)})
    current = sha256_file(target) if target.exists() else None
    if current != entry["newSha256"]:
        raise ToolError("target_changed",
                        "마지막으로 저장한 뒤 파일이 바뀌어 되돌리지 않았습니다.",
                        hint="현재 파일 내용을 유지하려면 파일을 그대로 두세요. 이전 내용은 저장 기록에 남아 있습니다.",
                        at=str(target), data={"history": str(folder)})
    return entry


def entry_id(entry: dict) -> str:
    """Which save a history entry is; ``undo(expect=...)`` binds to it."""
    return entry.get("id") or f"{entry.get('at')}:{entry.get('newSha256')}"


def _put_back(kept: Path, target: Path) -> bool:
    """Move ``kept`` back to ``target`` without replacing whatever is there now."""
    try:
        os.link(kept, target)
    except FileExistsError:
        return False
    except OSError:
        if os.name != "nt":
            return False  # a POSIX rename would replace: leave it in history
        try:
            os.rename(kept, target)  # never replaces on Windows
            return True
        except OSError:
            return False
    try:
        os.unlink(kept)
    except OSError:
        pass
    return True


def undoable(target: Path, home: Path | None = None) -> dict:
    """The history entry ``undo`` would reverse now, or the ToolError it would raise.

    A preview for asking the person first; ``undo`` checks again under the lock.
    """
    home = Path(home) if home else state_home()
    folder = _history_dir(home, target)
    return _last_undoable(_settled(_load_index(folder), target), target, folder)


def undo(target: Path, *, by: str, home: Path | None = None,
         expect: str | None = None) -> dict:
    """Put back what the last commit replaced, if the file is still ours.

    ``expect`` is the ``entry_id`` the person was shown: a save that landed
    after the question is not the one they agreed to reverse. Every check is
    against the digest in history, never a fresh hash of the target. The
    bytes undo displaces go to history too, so undo itself can be undone by
    hand from the history folder.
    """
    home = Path(home) if home else state_home()
    folder = private_dir(_history_dir(home, target))
    with _lock(folder):
        entries = _settled(_load_index(folder), target)
        entry = _last_undoable(entries, target, folder)
        if expect is not None and entry_id(entry) != expect:
            raise ToolError("stale", "확인하는 사이에 저장 기록이 바뀌어 되돌리지 않았습니다.",
                            hint="저장 기록을 다시 확인한 뒤 실행하세요.", retryable=True,
                            at=str(target), data={"history": str(folder)})
        mine = entry["newSha256"]
        changed = ToolError("target_changed", "확인하는 사이에 파일이 바뀌어 되돌리지 않았습니다.",
                            hint="현재 파일은 그대로 두었습니다.", at=str(target),
                            data={"history": str(folder)})
        stamp = f"{_now().replace(':', '')}-{secrets.token_hex(3)}"
        try:
            if entry["oldSha256"] is None:
                # We created this file; undo removes it by moving it into
                # history. The move is one rename; what moved is checked after
                # it and put back, never replacing, if it was not ours.
                kept = folder / f"{stamp}-created-{mine[:12]}{target.suffix}"
                os.replace(target, kept)
                try:
                    ours = sha256_file(kept) == mine
                except OSError:
                    ours = False  # could not check what moved: treat it as not ours
                if not ours:
                    if not _put_back(kept, target):
                        changed.hint = f"옮긴 파일은 저장 기록 폴더에 보관했습니다: {kept}"
                    raise changed
                restored = None
            else:
                old = (folder / entry["kept"]).read_bytes()
                if sha256_bytes(old) != entry["oldSha256"]:
                    raise ToolError("internal",
                                    "보관한 파일 내용이 저장 기록과 달라 되돌릴 수 없습니다.",
                                    at=str(folder / entry["kept"]))
                displaced = target.read_bytes()
                if sha256_bytes(displaced) != mine:
                    raise changed
                kept = folder / f"{stamp}-undone-{mine[:12]}{target.suffix}"
                _write_durable(kept, displaced)
                replace_checked(target, old, mine)
                restored = entry["oldSha256"]
        except PathRefused as exc:
            raise _refusal(exc) from exc
        entry["undone"] = {"at": _now(), "by": by}
        try:
            _save_index(folder, entries)
        except OSError as exc:
            # The file is already back; only the record failed. Say so, and
            # where the bytes undo moved aside are (Sol re-check F3, round 3).
            raise ToolError("internal", "되돌렸지만 저장 기록에 남기지 못했습니다.",
                            hint=f"되돌리기 전 파일은 여기에 보관했습니다: {kept}",
                            at=str(target), data={"kept": str(kept), "error": exc.strerror}) from exc
    return {"target": str(target), "restored": restored,
            "removed": entry["oldSha256"] is None}
