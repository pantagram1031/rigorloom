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
    from .rt_drafts import key_for_path
    from .rt_paths import (PathRefused, create_new, private_dir, replace_checked,
                           sha256_bytes, sha256_file, state_home)
    from .rt_tools import ToolError
except ImportError:  # a checkout, runtime/scripts on sys.path
    from rt_drafts import key_for_path
    from rt_paths import (PathRefused, create_new, private_dir, replace_checked,
                          sha256_bytes, sha256_file, state_home)
    from rt_tools import ToolError

ABSENT = "absent"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history_dir(home: Path, target: Path) -> Path:
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


def commit(candidate: Path, target: Path, *, expected: str, by: str,
           policy: str, home: Path | None = None) -> dict:
    """Publish ``candidate``'s bytes at ``target``.

    ``expected`` is ``"absent"`` (create only) or the full sha256 the target
    must still have. Returns a receipt; raises ToolError and writes nothing
    when the binding does not hold.
    """
    home = Path(home) if home else state_home()
    data = candidate.read_bytes()
    new_sha = sha256_bytes(data)
    entry = {"at": _now(), "target": str(target), "newSha256": new_sha,
             "by": by, "policy": policy, "oldSha256": None, "kept": None}
    try:
        if expected == ABSENT:
            create_new(target, data)
        else:
            folder = private_dir(_history_dir(home, target))
            current = sha256_file(target) if target.exists() else None
            if current != expected:
                raise ToolError("target_changed",
                                "저장하려는 사이에 대상 파일이 바뀌었습니다.",
                                hint="파일을 다시 열어 확인한 뒤 저장하세요.",
                                at=str(target))
            kept = folder / f"{entry['at'].replace(':', '')}-{expected[:12]}{target.suffix}"
            kept.write_bytes(target.read_bytes())
            if sha256_file(kept) != expected:
                raise ToolError("internal", "저장 기록에 이전 판을 보관하지 못했습니다.")
            entry["oldSha256"] = expected
            entry["kept"] = kept.name
            replace_checked(target, data, expected)
    except PathRefused as exc:
        raise _refusal(exc) from exc
    folder = private_dir(_history_dir(home, target))
    entries = _load_index(folder)
    entries.append(entry)
    _save_index(folder, entries)
    return {"target": str(target), "sha256": new_sha, "replaced": entry["oldSha256"],
            "policy": policy, "by": by, "at": entry["at"],
            "undo": entry["oldSha256"] is not None}


def last_commit(target: Path, home: Path | None = None) -> dict | None:
    home = Path(home) if home else state_home()
    entries = _load_index(_history_dir(home, target))
    return entries[-1] if entries else None


def owned(target: Path, home: Path | None = None) -> bool:
    """Does ``target`` still hold exactly the bytes our last commit wrote?"""
    entry = last_commit(target, home)
    if entry is None or not target.exists():
        return False
    return sha256_file(target) == entry["newSha256"]


def undo(target: Path, *, by: str, home: Path | None = None) -> dict:
    """Put back what the last commit replaced, if the file is still ours."""
    home = Path(home) if home else state_home()
    folder = _history_dir(home, target)
    entries = _load_index(folder)
    if not entries:
        raise ToolError("not_found", "되돌릴 저장 기록이 없습니다.", at=str(target))
    entry = entries[-1]
    if entry.get("undone"):
        raise ToolError("not_found", "마지막 저장은 이미 되돌렸습니다.", at=str(target))
    current = sha256_file(target) if target.exists() else None
    if current != entry["newSha256"]:
        raise ToolError("target_changed",
                        "마지막으로 저장했을 때와 파일 상태가 달라 되돌리지 않았습니다.",
                        hint="지금 내용을 지키려면 그대로 두세요. 이전 판은 저장 기록에 남아 있습니다.",
                        at=str(target), data={"history": str(folder)})
    try:
        if entry["oldSha256"] is None:
            # We created this file; undo removes it by moving it into history.
            stamp = _now().replace(":", "")
            kept = private_dir(folder) / f"{stamp}-created-{current[:12]}{target.suffix}"
            os.replace(target, kept)
            restored = None
        else:
            old = (folder / entry["kept"]).read_bytes()
            if sha256_bytes(old) != entry["oldSha256"]:
                raise ToolError("internal", "보관한 이전 판이 저장 기록과 달라 되돌릴 수 없습니다.",
                                at=str(folder / entry["kept"]))
            replace_checked(target, old, current)
            restored = entry["oldSha256"]
    except PathRefused as exc:
        raise _refusal(exc) from exc
    entry["undone"] = {"at": _now(), "by": by}
    _save_index(folder, entries)
    return {"target": str(target), "restored": restored,
            "removed": entry["oldSha256"] is None}
