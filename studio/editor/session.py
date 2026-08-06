"""Single-user document session with ordered operations and linear undo."""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .doc_backend import EditResult, ParagraphRecord, apply_paragraph_edit, inspect_paragraphs


class RevisionConflict(RuntimeError):
    """The client proposed an operation against a stale session revision."""


class NothingToUndo(RuntimeError):
    """The linear edit stack is empty."""


@dataclass(frozen=True)
class SessionResult:
    revision: int
    document_path: Path
    operation: dict
    edit_result: EditResult


class DocumentSession:
    """One document, one ordered writer, and optimistic revision checks."""

    def __init__(self, source: Path, session_dir: Path):
        self.source = Path(source).resolve()
        self.session_dir = Path(session_dir).resolve()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.session_dir / "operations.jsonl"
        initial = self.session_dir / "revision-0000.hwpx"
        if initial.exists() or self.log_path.exists():
            raise FileExistsError(f"session directory is not empty: {self.session_dir}")
        shutil.copyfile(self.source, initial)
        self.revision = 0
        self.current_path = initial
        self._lock = threading.RLock()
        self._sequence = 0
        self._undo_stack: list[dict] = []

    def paragraphs(self) -> list[ParagraphRecord]:
        with self._lock:
            return inspect_paragraphs(self.current_path)

    def _check_revision(self, expected: int) -> None:
        if expected != self.revision:
            raise RevisionConflict(
                f"stale revision {expected}; current revision is {self.revision}"
            )

    def _append(self, record: dict) -> None:
        with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _base_record(self, kind: str) -> dict:
        self._sequence += 1
        return {
            "sequence": self._sequence,
            "op_id": str(uuid.uuid4()),
            "kind": kind,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_revision": self.revision,
            "result_revision": self.revision + 1,
        }

    def edit(self, *, paragraph_id: str, new_text: str, expected_revision: int) -> SessionResult:
        with self._lock:
            self._check_revision(expected_revision)
            current = next(
                (item for item in inspect_paragraphs(self.current_path) if item.id == paragraph_id),
                None,
            )
            if current is None:
                raise RevisionConflict("paragraph no longer exists")
            output = self.session_dir / f"revision-{self.revision + 1:04d}.hwpx"
            result = apply_paragraph_edit(
                self.current_path,
                output,
                paragraph_id=paragraph_id,
                new_text=new_text,
                expected_old_text=current.text,
            )
            record = self._base_record("edit")
            record.update({
                "paragraph_id": paragraph_id,
                "before_text": result.old_text,
                "after_text": result.new_text,
                "fidelity": result.fidelity.to_dict(),
            })
            self._append(record)
            self.revision += 1
            self.current_path = output
            self._undo_stack.append(record)
            return SessionResult(self.revision, output, record, result)

    def undo(self, *, expected_revision: int) -> SessionResult:
        with self._lock:
            self._check_revision(expected_revision)
            if not self._undo_stack:
                raise NothingToUndo("no accepted edit remains to undo")
            original = self._undo_stack[-1]
            output = self.session_dir / f"revision-{self.revision + 1:04d}.hwpx"
            result = apply_paragraph_edit(
                self.current_path,
                output,
                paragraph_id=original["paragraph_id"],
                new_text=original["before_text"],
                expected_old_text=original["after_text"],
            )
            record = self._base_record("undo")
            record.update({
                "undoes": original["op_id"],
                "paragraph_id": original["paragraph_id"],
                "before_text": result.old_text,
                "after_text": result.new_text,
                "fidelity": result.fidelity.to_dict(),
            })
            self._append(record)
            self.revision += 1
            self.current_path = output
            self._undo_stack.pop()
            return SessionResult(self.revision, output, record, result)

