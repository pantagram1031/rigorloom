#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workspace sessions: a report workspace directory, opened the way a document is.

Runtime GAP 20. Thirteen of the seventeen checkers the six shipped distribution
modules declare take a report WORKSPACE directory rather than a document, and
the Runtime had no workspace concept at all — so ``module/check`` skipped every
one of them by construction (``needs_workspace``) and the report-pipeline
product, which is this repository's original product, could not run inside the
application. This module is the missing kind.

IT IS THE DOCUMENT SESSION'S SHAPE, NOT A SECOND MODEL. A workspace session is
opened by a host, validated against bounds, COPIED into
``<session>/workspace/`` and hashed; everything downstream addresses the copy.
The operator's directory is opened read-only and is never written, exactly as
``rt_session`` states for a document ("원본 비파괴 원칙", engine/scripts/preedit.py:2335).

WHAT A WORKSPACE *IS* — DECLARED, NEVER GUESSED. The paths a workspace holds
(``bundle/content.md``, ``claims.yaml``, ``output/QUESTIONS.md`` …) are a
distribution module's vocabulary, and a list of them in core is exactly the
per-module knowledge ``modules/README.md`` rule 1 forbids. So an enabled module
declares its layout — ``provides.workspace_layout``, a module-relative JSON
file — and this module reads three keys out of it and ignores the rest:

  * ``canonical_dirs``  — workspace-relative directories the pipeline routes to
  * ``stages``          — each stage's ``inputs``/``outputs``, every entry a
                          ``{pattern, required}`` pair; the stage name becomes
                          the part's role
  * ``read_only_paths`` — ``{pattern, role, required}`` for a path a checker
                          reads that no stage routes

With no enabled module declaring a layout the answer is ``undeclared`` with a
reason, and the summary carries zero parts rather than a guess. A workspace can
still be opened and its checkers can still run: a checker knows its own paths,
and nothing here needs to.

BOUNDS ARE A DIRECTORY'S THREE DIMENSIONS. A file has one (size); a tree has
bytes, entry count and depth, and the copy has to survive twice — once into the
session, once into each ``module/check`` scratch. ``rt_codes`` carries the
values and ``WORKSPACE_REJECT_REASONS`` the closed reason vocabulary; a refusal
names one of them, never prose a caller has to parse.

SYMLINKS ARE REFUSED, ROOT AND MEMBER ALIKE. A link inside the tree can point
anywhere on the operator's disk, and copying it would either follow it (pulling
unbounded bytes past the size check) or reproduce it (handing a checker a path
out of its scratch). Refusing is the only answer that keeps the bound honest —
the same posture ``rt_session._zip_sanity`` takes for a symlinked zip member.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    MAX_WORKSPACE_BYTES,
    MAX_WORKSPACE_DEPTH,
    MAX_WORKSPACE_FILES,
    WORKSPACE_REJECT_REASONS,
    RpcError,
)

#: How a declared part is addressed. ``glob`` is kept apart from ``file``
#: because "present" means something different for it: at least one match.
PART_KINDS = ("file", "directory", "glob")

#: Where a part came from in the declaration. Closed so a UI can group by it
#: without matching prose; the stage NAME rides in ``role``, which is the
#: module's own word and is passed through untouched.
PART_SOURCES = ("canonical_dir", "stage_output", "stage_input", "read_only")

#: Truncation guard for a layout declaration nobody bounded. A workspace with
#: more declared parts than this is a declaration defect, not a workspace.
MAX_DECLARED_PARTS = 512


def reject(reason: str, message: str, **data) -> RpcError:
    assert reason in WORKSPACE_REJECT_REASONS, f"undeclared reason: {reason!r}"
    return RpcError("workspace_rejected", message, reason=reason,
                    reasons=list(WORKSPACE_REJECT_REASONS), **data)


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


# --- ingress ------------------------------------------------------------------

def survey(root: Path) -> dict:
    """Walk the tree once, bounded at every step. Returns facts or refuses.

    The walk is its own bound: it stops at the first entry that would take the
    tree past a limit, so a pathological directory costs the walk it takes to
    find that entry and not a byte more.
    """
    try:
        info = root.lstat()
    except OSError as exc:
        raise reject("unreadable", "the workspace path cannot be read",
                      detail=str(exc)) from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise reject("symlink_or_reparse",
                      "the workspace path is a symlink or reparse point; open "
                      "the real directory")
    if not stat.S_ISDIR(info.st_mode):
        raise reject("not_a_directory",
                      "a workspace session is a directory; a single file is a "
                      "document session")

    files = 0
    directories = 0
    total = 0
    max_depth = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_WORKSPACE_DEPTH:
            raise reject("too_deep",
                          "the workspace nests deeper than this Runtime copies",
                          depth=depth, limit=MAX_WORKSPACE_DEPTH)
        max_depth = max(max_depth, depth)
        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            raise reject("unreadable",
                          "a directory inside the workspace cannot be listed",
                          detail=str(exc)) from exc
        for entry in entries:
            try:
                entry_info = entry.lstat()
            except OSError as exc:
                raise reject("unreadable",
                              "an entry inside the workspace cannot be read",
                              detail=str(exc)) from exc
            if stat.S_ISLNK(entry_info.st_mode) or _is_reparse(entry_info):
                raise reject(
                    "member_symlink",
                    "the workspace holds a symlink or reparse point; it could "
                    "name anything on this machine, so the copy refuses rather "
                    "than following or reproducing it",
                    member=entry.relative_to(root).as_posix())
            if stat.S_ISDIR(entry_info.st_mode):
                directories += 1
                stack.append((entry, depth + 1))
                continue
            if not stat.S_ISREG(entry_info.st_mode):
                # A fifo, socket or device is not workspace content and cannot
                # be copied with a bound; it is refused as unreadable content
                # rather than skipped silently.
                raise reject("unreadable",
                              "the workspace holds an entry that is not a "
                              "regular file",
                              member=entry.relative_to(root).as_posix())
            files += 1
            if files > MAX_WORKSPACE_FILES:
                raise reject("too_many_files",
                              "the workspace holds more files than this Runtime "
                              "copies", limit=MAX_WORKSPACE_FILES)
            total += entry_info.st_size
            if total > MAX_WORKSPACE_BYTES:
                raise reject("workspace_too_large",
                              "the workspace exceeds the ingress size bound",
                              bytes=total, limit=MAX_WORKSPACE_BYTES)
    return {"files": files, "directories": directories, "bytes": total,
            "maxDepth": max_depth,
            "limits": {"maxBytes": MAX_WORKSPACE_BYTES,
                       "maxFiles": MAX_WORKSPACE_FILES,
                       "maxDepth": MAX_WORKSPACE_DEPTH}}


def copy_tree(source: Path, target: Path) -> dict:
    """Copy the tree and hash it in the same pass. Returns copy facts.

    ONE PASS, because the alternative reads every byte twice for an answer the
    copy already had in its hands. The tree hash is over the sorted
    ``(relative posix path, sha256)`` pairs, so it is stable across filesystems
    and orderings and changes if any file's bytes, name or place changes.
    """
    started = time.monotonic()
    target.mkdir(parents=True, exist_ok=False)
    rows: list[tuple[str, str]] = []
    total = 0
    stack = [source]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            relative = entry.relative_to(source)
            destination = target / relative
            if entry.is_dir() and not entry.is_symlink():
                destination.mkdir(parents=True, exist_ok=True)
                stack.append(entry)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with entry.open("rb") as reader, destination.open("wb") as writer:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    digest.update(chunk)
                    writer.write(chunk)
                    total += len(chunk)
            rows.append((relative.as_posix(), digest.hexdigest()))
    rows.sort()
    tree = hashlib.sha256()
    for name, digest_hex in rows:
        tree.update(name.encode("utf-8"))
        tree.update(b"\0")
        tree.update(digest_hex.encode("ascii"))
        tree.update(b"\n")
    return {"files": len(rows), "bytes": total, "treeSha256": tree.hexdigest(),
            "millis": int((time.monotonic() - started) * 1000)}


# --- the declared layout --------------------------------------------------------

def _entry_rows(payload: dict) -> list[dict]:
    """The declaration's parts, in declaration order, de-duplicated by path."""
    rows: list[dict] = []
    seen: dict[str, dict] = {}

    def add(pattern, *, kind: str, role, required: bool, source: str) -> None:
        if not isinstance(pattern, str) or not pattern.strip():
            return
        path = pattern.strip().replace("\\", "/").rstrip("/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            # A declaration that escapes its own workspace is a declaration
            # defect; it is dropped rather than resolved against anything.
            return
        existing = seen.get(path)
        if existing is not None:
            # Required wins: a pattern declared required anywhere IS required.
            existing["required"] = existing["required"] or required
            return
        row = {"path": path, "kind": kind,
               "role": role if isinstance(role, str) else None,
               "required": bool(required), "source": source}
        seen[path] = row
        rows.append(row)

    for name in payload.get("canonical_dirs", []) or []:
        add(name, kind="directory", role="canonical_dir", required=False,
            source="canonical_dir")
    stages = payload.get("stages")
    if isinstance(stages, dict):
        for stage_id in sorted(stages, key=str):
            stage = stages[stage_id]
            if not isinstance(stage, dict):
                continue
            role = stage.get("name") if isinstance(stage.get("name"), str) else str(stage_id)
            for key, source in (("outputs", "stage_output"), ("inputs", "stage_input")):
                for entry in stage.get(key, []) or []:
                    if not isinstance(entry, dict):
                        continue
                    pattern = entry.get("pattern")
                    kind = "glob" if isinstance(pattern, str) and any(
                        ch in pattern for ch in "*?[") else "file"
                    add(pattern, kind=kind, role=role,
                        required=bool(entry.get("required", False)), source=source)
    for entry in payload.get("read_only_paths", []) or []:
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern")
        if isinstance(pattern, str) and pattern.rstrip().endswith("/"):
            kind = "directory"
        elif isinstance(pattern, str) and any(ch in pattern for ch in "*?["):
            kind = "glob"
        else:
            kind = "file"
        add(pattern, kind=kind, role=entry.get("role"),
            required=bool(entry.get("required", False)), source="read_only")
    return rows[:MAX_DECLARED_PARTS]


def declared_layout(registry, module_registry) -> dict:
    """Merge every enabled module's workspace-layout declaration.

    Two modules declaring a layout is a union, not a conflict: a part declared
    by either is a part, and a part either calls required is required. The
    modules that declared are named, because ``module/list`` already names
    modules on the wire and a reader has to know whose contract this is.
    """
    base = {"state": "undeclared", "reason": None, "declaredBy": [],
            "schemas": [], "parts": [],
            "sources": list(PART_SOURCES), "kinds": list(PART_KINDS)}
    try:
        declarations = registry.enabled_workspace_layouts()
    except getattr(module_registry, "ModuleError", Exception) as exc:
        base["reason"] = (
            "the distribution-module declarations on disk do not validate, so "
            "no workspace layout could be read: %s" % exc)
        return base
    if not declarations:
        base["reason"] = (
            "no enabled distribution module declares provides.workspace_layout; "
            "this build cannot say which parts a report workspace should have, "
            "so it reports none rather than guessing")
        return base

    parts: list[dict] = []
    seen: set[str] = set()
    for row in declarations:
        path = Path(row["path"])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            base["declaredBy"].append(row["module"])
            base["reason"] = (
                "a declared workspace layout is not readable JSON: %s" % exc)
            return base
        if not isinstance(payload, dict):
            base["declaredBy"].append(row["module"])
            base["reason"] = "a declared workspace layout is not a JSON object"
            return base
        base["declaredBy"].append(row["module"])
        schema = payload.get("schema")
        if isinstance(schema, str):
            base["schemas"].append(schema)
        for part in _entry_rows(payload):
            if part["path"] in seen:
                for existing in parts:
                    if existing["path"] == part["path"]:
                        existing["required"] = (existing["required"]
                                                or part["required"])
                        break
                continue
            seen.add(part["path"])
            parts.append(part)
    base["state"] = "declared"
    base["parts"] = parts
    return base


def _present(root: Path, part: dict) -> dict:
    """Is this declared part there? Per part, honestly, never inferred."""
    row = dict(part)
    path = root / part["path"]
    if part["kind"] == "glob":
        try:
            matches = [entry for entry in root.glob(part["path"])]
        except (OSError, ValueError):
            matches = []
        row["present"] = bool(matches)
        row["matches"] = len(matches)
        return row
    if part["kind"] == "directory":
        present = path.is_dir()
        row["present"] = present
        row["matches"] = (sum(1 for _ in path.iterdir()) if present else 0)
        return row
    row["present"] = path.is_file()
    row["matches"] = 1 if row["present"] else 0
    return row


def layout_report(root: Path, layout: dict) -> dict:
    """The declared layout answered against one workspace copy."""
    parts = [_present(root, part) for part in layout["parts"]]
    present = [part for part in parts if part["present"]]
    absent_required = [part for part in parts
                       if not part["present"] and part["required"]]
    return {
        "state": layout["state"],
        "reason": layout["reason"],
        "declaredBy": list(layout["declaredBy"]),
        "schemas": list(layout["schemas"]),
        "sources": list(layout["sources"]),
        "kinds": list(layout["kinds"]),
        "parts": parts,
        "counts": {
            "declared": len(parts),
            "present": len(present),
            "absent": len(parts) - len(present),
            "absentRequired": len(absent_required),
        },
        "note": ("presence is answered per part against the session's own copy; "
                 "a part nobody declared is not reported, and an absent part is "
                 "reported absent rather than defaulted"),
    }


def scan_undeclared(root: Path, layout: dict, *, limit: int = 64) -> dict:
    """Top-level entries the declaration does not name. Reported, never judged.

    A workspace is a person's directory and will hold things no contract knows
    about. Hiding them would make the summary read like a complete inventory
    when it is a declared one, so the top level is listed and bounded.
    """
    declared_tops = {part["path"].split("/", 1)[0] for part in layout["parts"]}
    rows = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if entry.name in declared_tops:
            continue
        rows.append({"name": entry.name,
                     "kind": "directory" if entry.is_dir() else "file"})
    return {"entries": rows[:limit], "count": len(rows),
            "truncated": len(rows) > limit}
