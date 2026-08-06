from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.editor.sample_factory import write_synthetic_hwpx
from studio.editor.session import DocumentSession, RevisionConflict


def test_session_logs_ordered_edit_and_undo(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    session = DocumentSession(source, tmp_path / "session")
    target = next(item for item in session.paragraphs() if item.editable)

    edited = session.edit(
        paragraph_id=target.id,
        new_text="Revision one.",
        expected_revision=0,
    )
    undone = session.undo(expected_revision=1)

    assert edited.revision == 1
    assert undone.revision == 2
    assert next(item for item in session.paragraphs() if item.id == target.id).text == target.text
    records = [json.loads(line) for line in session.log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["sequence"] for record in records] == [1, 2]
    assert [record["kind"] for record in records] == ["edit", "undo"]
    assert records[1]["undoes"] == records[0]["op_id"]


def test_session_rejects_stale_revision(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    session = DocumentSession(source, tmp_path / "session")
    target = next(item for item in session.paragraphs() if item.editable)
    session.edit(paragraph_id=target.id, new_text="Revision one.", expected_revision=0)

    with pytest.raises(RevisionConflict):
        session.edit(paragraph_id=target.id, new_text="Stale edit.", expected_revision=0)

