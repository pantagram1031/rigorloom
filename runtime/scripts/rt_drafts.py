#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drafts: where agent edits live until a person saves them.

An agent never edits the person's file. Each edit goes into that document's
DRAFT under the state directory: numbered candidate files (revision 1, 2, ...)
and the change sets that made them. Later reads by agent surfaces see the
draft head, so a multi-step edit builds on itself instead of forking. Writing
into the person's folder is a separate, explicit step (``save``) handled by
:mod:`rt_commit`, never here.

There is ONE draft per canonical file path per OS user, shared by every
client (CLI, MCP, UI): a person reviewing in the UI and an agent editing over
MCP look at the same thing. A document made from scratch (``new``) has a
draft with no source file; it is addressed as ``draft:<key>`` wherever a path
is accepted.

Layout (``rt_paths.state_home()/drafts/<key>/``)::

    draft.json         the record
    rev-0001.hwpx      candidate after change set 1
    rev-0002.hwpx      ...

If the source changes on disk after a draft started (someone saved it in
Hancom), the draft refuses new edits with ``source_changed`` until it is
discarded (rebasing by ``expect`` is a later step): editing bytes the person
no longer has would silently undo their work at save time.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rt_paths import private_dir, sha256_file, state_home
from rt_tools import ToolError

DRAFT_SCHEMA = "rigorloom/draft/1"
VIRTUAL_PREFIX = "draft:"
LOCK_TIMEOUT_S = 30.0
LOCK_STALE_S = 300.0


def rev_of(sha256: str) -> str:
    """The short revision id used for addressing: 12 hex characters.

    Bindings that protect bytes (save, undo) always use the full digest.
    """
    return sha256[:12]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_for_path(source: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest()[:16]


def is_virtual(ref: str | os.PathLike) -> bool:
    return isinstance(ref, str) and ref.startswith(VIRTUAL_PREFIX)


@dataclass(frozen=True)
class Ref:
    """A document as the draft store knows it: a file, or a draft with none."""

    key: str
    source: Path | None       # None for a document made with ``new``

    @property
    def label(self) -> str:
        return str(self.source) if self.source else f"{VIRTUAL_PREFIX}{self.key}"


@dataclass
class Input:
    """What a read or edit operates on right now."""

    path: Path            # the file to read: draft head or the source itself
    rev: str              # short revision (addressing)
    sha256: str           # full digest (binding)
    source: str           # "draft" | "disk"
    revision: int         # 0 = the source, n = draft revision n
    draft: dict | None    # summary of the draft, when one exists


class _Lock:
    """One writer per draft, across processes (CLI, MCP, UI)."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    continue
                if age > LOCK_STALE_S:
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise ToolError("locked", "다른 작업이 이 초안을 고치는 중입니다.",
                                    hint="잠시 뒤 다시 시도하세요.", retryable=True)
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        return False


class DraftStore:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else state_home()

    # -- refs and paths ----------------------------------------------------
    def ref(self, target: str | os.PathLike) -> Ref:
        """A Ref for a canonical file path or a ``draft:<key>`` string."""
        if is_virtual(target):
            key = str(target)[len(VIRTUAL_PREFIX):]
            if not key or not all(c.isalnum() or c == "-" for c in key):
                raise ToolError("invalid_params", f"초안 이름이 잘못되었습니다: {target}")
            if self.load(Ref(key, None)) is None:
                raise ToolError("not_found", f"그런 초안이 없습니다: {target}",
                                hint="초안 목록: rigorloom changes")
            return Ref(key, None)
        path = Path(target)
        return Ref(key_for_path(path), path)

    def dir_for(self, ref: Ref) -> Path:
        return self.home / "drafts" / ref.key

    # -- records -----------------------------------------------------------
    def load(self, ref: Ref) -> dict | None:
        path = self.dir_for(ref) / "draft.json"
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ToolError("internal", f"초안 기록을 읽지 못했습니다: {path}",
                            data={"reason": str(exc)}) from exc
        if record.get("schema") != DRAFT_SCHEMA:
            raise ToolError("internal", f"알 수 없는 초안 형식입니다: {path}")
        return record

    def write(self, ref: Ref, record: dict) -> None:
        folder = private_dir(self.dir_for(ref))
        record["updated"] = _now()
        temp = folder / f".draft.{secrets.token_hex(4)}.tmp"
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        os.replace(temp, folder / "draft.json")

    def lock(self, ref: Ref) -> _Lock:
        return _Lock(private_dir(self.dir_for(ref)) / ".lock")

    def list(self) -> list[dict]:
        root = self.home / "drafts"
        out: list[dict] = []
        if not root.is_dir():
            return out
        for record_path in sorted(root.glob("*/draft.json")):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append(summary(record))
        return out

    # -- reading -----------------------------------------------------------
    def input_for(self, ref: Ref, *, use_draft: bool = True) -> Input:
        """The file a read should see: the draft head, else the source."""
        record = self.load(ref)
        if ref.source is None:
            if record is None or not record.get("head"):
                raise ToolError("not_found", f"그런 초안이 없습니다: {ref.label}")
            return self._head_input(ref, record)
        source_sha = sha256_file(ref.source)
        if use_draft and record and record.get("head"):
            self._require_source_unchanged(record, source_sha)
            return self._head_input(ref, record)
        return Input(path=ref.source, rev=rev_of(source_sha), sha256=source_sha,
                     source="disk", revision=0,
                     draft=summary(record) if record else None)

    def _head_input(self, ref: Ref, record: dict) -> Input:
        head = record["head"]
        return Input(path=self.dir_for(ref) / head["file"], rev=head["rev"],
                     sha256=head["sha256"], source="draft",
                     revision=head["revision"], draft=summary(record))

    @staticmethod
    def _require_source_unchanged(record: dict, source_sha: str) -> None:
        if record["source"]["sha256"] != source_sha:
            raise ToolError(
                "source_changed",
                "초안을 만든 뒤 원본 파일이 바뀌었습니다.",
                hint="원본을 기준으로 다시 시작하려면 초안을 버리세요: "
                     "rigorloom changes discard <파일>",
                data={"draftSource": record["source"]["rev"],
                      "diskSource": rev_of(source_sha)})

    # -- writing (inside the state dir only) --------------------------------
    def stage(self, ref: Ref, *, base: str | None, ops: list, author: str,
              provenance: dict, apply: Callable[[Path, str, Path], dict],
              kind: str = "edit") -> dict:
        """Run ``apply(input_path, input_rev, out_path)`` on the head; record it.

        ``base`` is the revision the caller read. If the head moved since, the
        edit is refused as ``stale`` before the engine is asked, so an agent
        never edits bytes it has not seen.
        """
        if ref.source is None and self.load(ref) is None:
            raise ToolError("not_found", f"그런 초안이 없습니다: {ref.label}")
        with self.lock(ref):
            folder = self.dir_for(ref)
            record = self.load(ref)
            source_sha = sha256_file(ref.source) if ref.source else None
            if record is None:
                assert ref.source is not None and source_sha is not None
                record = new_record(source=ref.source, sha256=source_sha)
            elif source_sha is not None:
                self._require_source_unchanged(record, source_sha)
            head = record.get("head")
            if head:
                in_path, in_rev, revision = folder / head["file"], head["rev"], head["revision"]
                base_kind = "candidate"
            else:
                assert ref.source is not None and source_sha is not None
                in_path, in_rev, revision = ref.source, rev_of(source_sha), 0
                base_kind = "source"
            if base is not None and base != in_rev:
                raise ToolError(
                    "stale",
                    f"문서가 그 사이 바뀌었습니다(읽은 판 {base}, 지금 판 {in_rev}).",
                    hint="다시 읽고(open 또는 read) 새 rev로 고치세요.",
                    retryable=True, data={"base": base, "current": in_rev})
            out_name = f"rev-{revision + 1:04d}{_work_suffix(in_path)}"
            out_path = folder / out_name
            result = apply(in_path, in_rev, out_path)
            if not out_path.exists():
                raise ToolError("internal", "편집 결과 파일이 만들어지지 않았습니다.")
            changeset = self._append(record, kind=kind, ops=ops, author=author,
                                     provenance=provenance, base_kind=base_kind,
                                     base_revision=revision, base_rev=in_rev,
                                     out_name=out_name, out_path=out_path,
                                     result=result)
            self.write(ref, record)
            return {"changeset": changeset, "draft": summary(record),
                    "headPath": str(out_path), "engine": result}

    def create_virtual(self, *, name: str | None, author: str, provenance: dict,
                       build: Callable[[Path], dict],
                       suffix: str = ".hwpx") -> tuple[Ref, dict]:
        """A draft with no source file (``new``). ``build(out_path)`` makes rev 1.

        ``suffix`` is the engine's native working format (``.hwpx`` for the
        real engine).
        """
        key = f"new-{secrets.token_hex(5)}"
        ref = Ref(key, None)
        with self.lock(ref):
            record = new_record(source=None, sha256=None, name=name,
                                fmt=suffix.lstrip("."))
            out_name = f"rev-0001{suffix}"
            out_path = self.dir_for(ref) / out_name
            result = build(out_path)
            if not out_path.exists():
                raise ToolError("internal", "새 문서 파일이 만들어지지 않았습니다.")
            changeset = self._append(record, kind="new", ops=[], author=author,
                                     provenance=provenance, base_kind="empty",
                                     base_revision=0, base_rev=None,
                                     out_name=out_name, out_path=out_path,
                                     result=result)
            self.write(ref, record)
        return ref, {"changeset": changeset, "draft": summary(record),
                     "headPath": str(out_path), "engine": result}

    @staticmethod
    def _append(record: dict, *, kind: str, ops: list, author: str,
                provenance: dict, base_kind: str, base_revision: int,
                base_rev: str | None, out_name: str, out_path: Path,
                result: dict) -> dict:
        out_sha = sha256_file(out_path)
        revision = base_revision + 1
        changeset = {
            "id": f"cs-{revision:04d}-{secrets.token_hex(3)}",
            "kind": kind,
            "created": _now(),
            "author": author,
            "provenance": provenance,
            "base": {"kind": base_kind, "revision": base_revision, "rev": base_rev},
            "ops": ops,
            "revision": revision,
            "rev": rev_of(out_sha),
            "sha256": out_sha,
            "changedPages": result.get("changed_pages", []),
            "signals": result.get("signals", []),
            "remap": result.get("remap", []),
            "applied": result.get("applied", []),
            "status": "proposed",
        }
        record["changesets"].append(changeset)
        record["head"] = {"revision": revision, "file": out_name,
                          "sha256": out_sha, "rev": rev_of(out_sha)}
        return changeset

    def discard(self, ref: Ref) -> dict:
        record = self.load(ref)
        if record is None:
            raise ToolError("no_draft", "이 문서에는 초안이 없습니다.")
        with self.lock(ref):
            archive = private_dir(self.home / "drafts-discarded") / \
                f"{ref.key}-{int(time.time())}"
            shutil.move(str(self.dir_for(ref)), str(archive))
        lock_left = archive / ".lock"
        if lock_left.exists():
            try:
                lock_left.unlink()
            except OSError:
                pass
        return {"discarded": summary(record), "keptAt": str(archive)}


def _work_suffix(path: Path) -> str:
    """Edits are written as HWPX (a .hwp is converted on the way in)."""
    suffix = path.suffix.lower()
    if suffix in ("", ".hwp"):
        return ".hwpx"
    return suffix


def new_record(*, source: Path | None, sha256: str | None,
               name: str | None = None, fmt: str = "hwpx") -> dict:
    return {
        "schema": DRAFT_SCHEMA,
        "source": ({"path": str(source), "sha256": sha256, "rev": rev_of(sha256),
                    "format": source.suffix.lower().lstrip(".")}
                   if source is not None else
                   {"path": None, "sha256": None, "rev": None, "format": fmt,
                    "name": name}),
        "head": None,
        "changesets": [],
        "saves": [],
        "declines": [],
        "created": _now(),
    }


def summary(record: dict) -> dict[str, Any]:
    head = record.get("head") or {}
    source = record["source"]
    return {
        "source": source.get("path"),
        "name": source.get("name"),
        "sourceRev": source.get("rev"),
        "revision": head.get("revision", 0),
        "rev": head.get("rev", source.get("rev")),
        "changesets": len(record.get("changesets", [])),
        "pending": sum(1 for c in record.get("changesets", [])
                       if c.get("status") == "proposed"),
        "updated": record.get("updated"),
        "saved": len(record.get("saves", [])),
    }
