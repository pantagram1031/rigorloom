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
    (ws / "work" / "stage-0" / "scratch").mkdir(parents=True)
    (ws / "work" / "stage-0" / "scratch" / "draft.txt").write_text("draft", encoding="utf-8")
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
    assert len(result["archived"]) == 3
    assert result["schema"] == "report-pipeline-handoff/v2"
    assert result["work_dir"] == "work/stage-1"
    assert "research/evidence.md" in result["expected_outputs"]
    handoff = json.loads((ws / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["playbook"].endswith("stage-1.md")
    assert "Next stage: `1`" in (ws / "NEXT_TASK.md").read_text(encoding="utf-8")
    assert (ws / ".pipeline" / "artifacts.json").exists()
    assert (ws / "WORKSPACE_INDEX.md").exists()
    assert list((ws / ".pipeline" / "receipts").glob("stage-0-*.json"))
    assert not (ws / "work" / "stage-0").exists()
    assert (ws / "work" / "stage-1" / "scratch").is_dir()


def test_completed_workflow_has_no_next_stage(tmp_path: Path):
    ws = tmp_path / "report-done"
    ws.mkdir()
    hdr = {"stages": {"0": {"status": "done", "gate": None}}}
    result = organizer.organize_workspace(ws, hdr, ["0"], completed_stage="0")
    assert result["next_stage"] is None
    assert "Workflow complete" in (ws / "NEXT_TASK.md").read_text(encoding="utf-8")


def test_inventory_hashes_existing_artifacts(tmp_path: Path):
    ws = tmp_path / "report-inventory"
    (ws / "research").mkdir(parents=True)
    evidence = ws / "research" / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    hdr = {"stages": {"0": {"status": "done"}, "1": {"status": "in_progress"}}}
    layout = organizer.load_layout()
    inventory = organizer.build_inventory(ws, hdr, ["0", "1"], layout)
    entry = next(item for item in inventory["stages"]["1"]["outputs"] if item["pattern"] == "research/evidence.md")
    assert entry["present"]
    assert len(entry["files"][0]["sha256"]) == 64
    assert "research/sources.json" in inventory["stages"]["1"]["missing_outputs"]


def test_layout_covers_every_kernel_stage():
    layout = organizer.load_layout()
    assert set(layout["stages"]) == {"-1", "0", "1", "2", "2.5", "3", "4", "5", "5.5", "5.7", "6"}
