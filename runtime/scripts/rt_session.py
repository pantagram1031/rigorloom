#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sessions: bounded ingress, a contained copy, and the read-only document views.

Source immutability is the invariant this module exists to hold. ``openPath``
never opens the user's file for writing and never operates in place: it
validates, copies into ``<root>/sessions/<id>/source/``, and records the
SHA-256 of what it copied. Everything downstream — inspect, validate, apply —
addresses the COPY. ``engine/scripts/preedit.py:2335`` already states the same
rule for the engine ("원본 비파괴 원칙: --out 필수").

Ingress bounds are the same VALUES as ``pipeline/scripts/hwp_ingress.py:40-46``
(``MAX_INPUT_BYTES``, ``MAX_HWPX_MEMBERS``, ``MAX_HWPX_TOTAL_UNCOMPRESSED``,
``MAX_HWPX_COMPRESSION_RATIO``), reimplemented stdlib-only in ``rt_codes``
rather than imported, for the reason recorded in ``rt_engine``. This slice
checks size + zip sanity only; it does NOT do the HWP5 CFB structural walk
that ``hwp_ingress`` does (pipeline/scripts/hwp_ingress.py:3-6). A non-hwpx
source is accepted as opaque bytes and can be copied and hashed, but no
offline op kind can address it — that is a stated gap, not a claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    MAX_REGION_BYTES,
    MAX_SOURCE_BYTES,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_MEMBERS,
    MAX_ZIP_TOTAL_UNCOMPRESSED,
    RpcError,
)
from rt_jsonl import canonical_bytes  # noqa: E402

_SAFE_NAME = "-_. ()[]"
_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")
RECORD_KINDS = ("plans", "approvals")


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """tmp + fsync + rename inside the destination directory.

    Same shape as ``document_evidence.write_receipt``
    (engine/scripts/document_evidence.py:1998, fsync at :1737, replace at :1766),
    without that module's fd-bound directory custody — a stated Phase 2 gap.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".tmp-{uuid.uuid4().hex}-{target.name}")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_reparse(info: os.stat_result) -> bool:
    """Windows reparse-point detection, as engine/scripts/document_evidence.py:176."""
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def safe_component(name: str) -> str:
    """A filename with no path meaning at all."""
    base = Path(name).name
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in _SAFE_NAME).strip()
    return cleaned or "source.bin"


def _reject(reason: str, **data) -> RpcError:
    return RpcError("source_rejected", reason, **data)


def validate_source(path: Path) -> dict:
    """Bounded, no-follow validation of a candidate source. Returns facts."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise _reject("source path cannot be read", detail=str(exc)) from exc
    if stat.S_ISLNK(info.st_mode) or is_reparse(info):
        raise _reject("source is a symlink or reparse point; open the real file")
    if not stat.S_ISREG(info.st_mode):
        raise _reject("source is not a regular file")
    if info.st_size > MAX_SOURCE_BYTES:
        raise _reject("source exceeds the ingress size bound",
                      bytes=info.st_size, limit=MAX_SOURCE_BYTES)
    facts = {"bytes": info.st_size, "container": "opaque"}
    with path.open("rb") as handle:
        head = handle.read(4)
    if head[:2] == b"PK":
        facts["container"] = "zip"
        facts.update(_zip_sanity(path))
    return facts


def _zip_sanity(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise _reject("source looks like a zip but does not open",
                      detail=str(exc)) from exc
    if len(infos) > MAX_ZIP_MEMBERS:
        raise _reject("zip member count exceeds the ingress bound",
                      members=len(infos), limit=MAX_ZIP_MEMBERS)
    total = 0
    compressed = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
            raise _reject("zip member name escapes its archive", member=name)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise _reject("zip member is a symlink", member=name)
        total += info.file_size
        compressed += info.compress_size
    if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
        raise _reject("zip uncompressed total exceeds the ingress bound",
                      bytes=total, limit=MAX_ZIP_TOTAL_UNCOMPRESSED)
    if compressed > 0 and total / compressed > MAX_ZIP_COMPRESSION_RATIO:
        raise _reject("zip compression ratio exceeds the ingress bound",
                      ratio=round(total / compressed, 2),
                      limit=MAX_ZIP_COMPRESSION_RATIO)
    names = {info.filename for info in infos}
    is_hwpx = "Contents/header.xml" in names and any(
        n.startswith("Contents/section") and n.endswith(".xml") for n in names)
    return {"members": len(infos), "uncompressedBytes": total,
            "documentKind": "hwpx" if is_hwpx else "zip"}


class Session:
    """One opened document and everything derived from it."""

    def __init__(self, root: Path, session_id: str):
        self.id = session_id
        self.dir = root / "sessions" / session_id
        self.source_dir = self.dir / "source"
        self.profile_dir = self.dir / "profile"
        self.work_dir = self.dir / "work"
        self.candidates_dir = self.dir / "candidates"
        self.meta_path = self.dir / "meta.json"
        self.meta: dict = {}

    # -- creation -----------------------------------------------------------
    @classmethod
    def open_path(cls, root: Path, raw_path: str) -> "Session":
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RpcError("invalid_params", "path must be a non-empty string")
        source = Path(raw_path).expanduser()
        if not source.is_absolute():
            raise RpcError("invalid_params",
                           "path must be absolute; the Runtime has no ambient cwd")
        facts = validate_source(source)
        session = cls(root, uuid.uuid4().hex)
        for directory in (session.source_dir, session.profile_dir,
                          session.work_dir, session.candidates_dir):
            directory.mkdir(parents=True, exist_ok=False)
        name = safe_component(source.name)
        target = session.source_dir / name
        resolved = target.resolve()
        if session.source_dir.resolve() not in resolved.parents:
            raise RpcError("path_escape", "copied source escapes the session")
        # Read-only on the source side: shutil.copyfile opens it 'rb'.
        shutil.copyfile(source, target)
        digest, size = sha256_file(target)
        session.meta = {
            "sessionId": session.id,
            "openedUtc": now_utc(),
            "sourceName": name,
            "sourceSha256": digest,
            "sourceBytes": size,
            "ingress": facts,
        }
        atomic_write_bytes(
            session.meta_path,
            json.dumps(session.meta, ensure_ascii=False, indent=2,
                       allow_nan=False).encode("utf-8"))
        return session

    @classmethod
    def load(cls, root: Path, session_id: str) -> "Session | None":
        if not _ID_RE.match(session_id or ""):
            return None
        session = cls(root, session_id)
        if not session.meta_path.is_file():
            return None
        try:
            meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        if not isinstance(meta, dict) or "sourceName" not in meta:
            return None
        session.meta = meta
        return session

    # -- accessors ----------------------------------------------------------
    @property
    def source(self) -> Path:
        return self.source_dir / self.meta["sourceName"]

    def current_source_sha256(self) -> str:
        return sha256_file(self.source)[0]

    def summary(self) -> dict:
        return {
            "sessionId": self.id,
            "openedUtc": self.meta["openedUtc"],
            "source": {
                "name": self.meta["sourceName"],
                "sha256": self.meta["sourceSha256"],
                "bytes": self.meta["sourceBytes"],
                "documentKind": self.meta["ingress"].get("documentKind", "opaque"),
            },
        }


class SessionStore:
    """Sessions, plans and approvals, keyed on disk under one root.

    ON-DISK RATHER THAN PER-CONNECTION, and the reason is the authority split
    itself: ``workspace/openPath`` is host-only and ``plan/propose`` is
    agent-safe (orchestrator decision D8). With per-connection state an agent
    connection could never reach a document at all — ``session/list`` would be
    empty forever and the whole agent surface would be decorative. The root
    directory is the shared state, exactly as a report workspace is
    (``PIPELINE.md`` / ``APPROVALS.md``:
    modules/report/scripts/pipeline_ctl.py:1112).

    Concurrency is last-writer-wins across processes. Two hosts driving one
    root can race a plan's state field; nothing here serialises them. Stated,
    not solved — see the open questions in docs/runtime-protocol-v0.md.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}

    def open_path(self, raw_path: str) -> Session:
        session = Session.open_path(self.root, raw_path)
        self._sessions[session.id] = session
        return session

    def get(self, session_id) -> Session:
        if isinstance(session_id, str) and session_id in self._sessions:
            return self._sessions[session_id]
        session = (Session.load(self.root, session_id)
                   if isinstance(session_id, str) else None)
        if session is None:
            raise RpcError("unknown_session", "no such session under this root",
                           sessionId=session_id)
        self._sessions[session.id] = session
        return session

    def list(self) -> list[dict]:
        rows: dict[str, dict] = {}
        sessions_dir = self.root / "sessions"
        if sessions_dir.is_dir():
            for entry in sorted(sessions_dir.iterdir()):
                if not entry.is_dir():
                    continue
                session = Session.load(self.root, entry.name)
                if session is not None:
                    self._sessions.setdefault(session.id, session)
                    rows[session.id] = session.summary()
        for session in self._sessions.values():
            rows.setdefault(session.id, session.summary())
        return [rows[key] for key in sorted(rows)]

    # -- generic records ----------------------------------------------------
    def _record_path(self, kind: str, ident: str) -> Path:
        if kind not in RECORD_KINDS:
            raise ValueError(f"unknown record kind: {kind!r}")
        if not _ID_RE.match(ident or ""):
            raise RpcError("invalid_params", "record ids are 32 hex characters",
                           id=ident)
        return self.root / kind / f"{ident}.json"

    def save_record(self, kind: str, ident: str, payload: dict) -> None:
        atomic_write_bytes(
            self._record_path(kind, ident),
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False).encode("utf-8"))

    def load_record(self, kind: str, ident) -> dict | None:
        if not isinstance(ident, str) or not _ID_RE.match(ident):
            return None
        path = self._record_path(kind, ident)
        if not path.is_file():
            return None
        from rt_jsonl import StrictJsonError, loads_strict
        try:
            payload = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, StrictJsonError):
            return None
        return payload if isinstance(payload, dict) else None


# --- derived views ----------------------------------------------------------

def _profile_path(session: Session, tag: str) -> Path:
    return session.profile_dir / f"profile-{tag}.json"


def load_profile(tools, session: Session, *, tag: str = "base",
                 full_text: list[str] | None = None) -> dict:
    """Run form_inspect against the session copy and return its profile object."""
    out = _profile_path(session, tag)
    tools.profile(session.source, out, full_text=full_text)
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RpcError("backend_refused", "form_inspect wrote an unreadable profile",
                       tool="form_inspect", detail=str(exc)) from exc


def document_summary(profile: dict, session: Session) -> dict:
    """DocumentSummary per docs/runtime-protocol-v0.md §3.3, from the profile."""
    return {
        "sessionId": session.id,
        "documentHash": profile.get("form_hash"),
        "anchors": profile.get("anchors", []),
        "pageMetrics": profile.get("page_metrics"),
        "constraints": profile.get("constraints"),
        "formatHints": profile.get("format_hints"),
        "baselineCharPr": profile.get("body_baseline_charpr"),
        "blackCharPr": profile.get("body_black_charpr"),
        "fillTargetCount": profile.get("fill_target_count"),
        "spacerCells": profile.get("spacer_cells", []),
        "scriptAnomalyTargets": profile.get("script_anomaly_targets", []),
        "removalTargets": profile.get("removal_targets", []),
    }


def document_graph(profile: dict, session: Session) -> dict:
    """DocumentGraph: the profile's own addressing, never renumbered (§3.4)."""
    tables = []
    for table in profile.get("table_map", []):
        cells = []
        for cell in table.get("cells", []):
            row = {
                "addr": cell.get("addr"),
                "classification": cell.get("classification"),
                "textPreview": cell.get("text_preview"),
                "truncated": bool(cell.get("truncated")),
            }
            for key, out_key in (("charpr", "charPr"),
                                 ("charpr_suggested", "charPrSuggested"),
                                 ("script_anomaly", "scriptAnomaly"),
                                 ("color_anomaly", "colorAnomaly"),
                                 ("color_value", "colorValue"),
                                 ("spacer_pattern", "spacerPattern")):
                if key in cell:
                    row[out_key] = cell[key]
            cells.append(row)
        tables.append({"index": table.get("index"), "cells": cells})
    return {
        "sessionId": session.id,
        "documentHash": profile.get("form_hash"),
        "paragraphs": profile.get("anchor_records", []),
        "tables": tables,
    }


def editable_regions(profile: dict, session: Session) -> dict:
    """EditableRegion list (§3.5): fill_target cells with their preflight."""
    regions = []
    for table in profile.get("table_map", []):
        for cell in table.get("cells", []):
            if cell.get("classification") != "fill_target":
                continue
            addr = cell.get("addr") or {}
            region = {
                "kind": "cell",
                "table": table.get("index"),
                "row": addr.get("row"),
                "col": addr.get("col"),
                "charPr": cell.get("charpr"),
                "charPrSuggested": cell.get("charpr_suggested"),
                "scriptAnomaly": cell.get("script_anomaly"),
            }
            if "color_anomaly" in cell:
                region["colorAnomaly"] = cell["color_anomaly"]
            if "color_value" in cell:
                region["colorValue"] = cell["color_value"]
            regions.append(region)
    return {"sessionId": session.id,
            "documentHash": profile.get("form_hash"),
            "regions": regions}


def full_text_spec(entry: dict) -> str:
    """A readRegion entry -> the form_inspect --full-text spelling."""
    if "atPara" in entry:
        return f"PARA:{int(entry['atPara'])}"
    table = int(entry.get("table", 0))
    return f"{table}:{int(entry['row'])},{int(entry['col'])}"


def bound_region_result(payload: dict) -> dict:
    """Refuse an oversized region result; never truncate it silently."""
    size = len(canonical_bytes(payload))
    if size > MAX_REGION_BYTES:
        raise RpcError("region_too_large",
                       "the requested regions exceed the response bound; ask for "
                       "fewer",
                       bytes=size, limit=MAX_REGION_BYTES)
    return payload
