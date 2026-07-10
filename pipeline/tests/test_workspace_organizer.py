from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "workspace_organizer.py"
SPEC = importlib.util.spec_from_file_location("workspace_organizer", MODULE_PATH)
organizer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(organizer)


def test_writes_handoff_and_archives_only_transients(tmp_path: Path):
    ws = tmp_path / "report-demo"
    (ws / "output").mkdir(parents=True)
    (ws / "bundle").mkdir()
    (ws / "bundle" / "content.md").write_text("keep", encoding="utf-8")
    (ws / "output" / "out.pdf").write_bytes(b"keep")
    (ws / "output" / "loop01_stderr.log").write_text("log", encoding="utf-8")
    (ws / "notes.tmp").write_text("temp", encoding="utf-8")
    hdr = {
        "pipeline_version": "0.6",
        "mode": "supervised",
        "stages": {
            "0": {"status": "done", "gate": None},
            "1": {"status": "pending", "gate": None},
        },
    }

    result = organizer.organize_workspace(ws, hdr, ["0", "1"], completed_stage="0")

    assert result["next_stage"] == "1"
    assert (ws / "bundle" / "content.md").exists()
    assert (ws / "output" / "out.pdf").exists()
    assert not (ws / "notes.tmp").exists()
    assert not (ws / "output" / "loop01_stderr.log").exists()
    assert len(result["archived"]) == 2
    handoff = json.loads((ws / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["playbook"].endswith("stage-1.md")
    assert "Next stage: `1`" in (ws / "NEXT_TASK.md").read_text(encoding="utf-8")


def test_completed_workflow_has_no_next_stage(tmp_path: Path):
    ws = tmp_path / "report-done"
    ws.mkdir()
    hdr = {"stages": {"0": {"status": "done", "gate": None}}}
    result = organizer.organize_workspace(ws, hdr, ["0"], completed_stage="0")
    assert result["next_stage"] is None
    assert "Workflow complete" in (ws / "NEXT_TASK.md").read_text(encoding="utf-8")
