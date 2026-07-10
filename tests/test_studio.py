from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import HTTPException


MODULE_PATH = Path(__file__).parents[1] / "studio" / "main.py"
SPEC = importlib.util.spec_from_file_location("studio_main", MODULE_PATH)
studio = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(studio)


def _pipeline_text() -> str:
    rows = {
        "0": "{status: done, gate: null}",
        "1": "{status: done, gate: null}",
        "2": "{status: done, gate: {name: design, state: approved, by: operator, at: now}}",
        "2.5": "{status: done, gate: {name: layout, state: auto_approved, by: script, at: now}}",
        "3": "{status: done, gate: {name: sane, state: auto_approved, by: script, at: now}}",
        "4": "{status: done, gate: {name: draft, state: approved, by: operator, at: now}}",
        "5": "{status: done, gate: null}",
        "5.5": "{status: awaiting_gate, gate: {name: understand, state: pending, by: null, at: null}}",
        "5.7": "{status: pending, gate: null}",
        "6": "{status: pending, gate: null}",
    }
    stage_text = "\n".join(f'  "{key}": {value}' for key, value in rows.items())
    return f'''```yaml
# pipeline-state: v0.4
pipeline_version: "0.6"
slug: "report-demo"
mode: "supervised"
subject: "science: #1"
topic: "line one # literal\\nline two"
form: "/tmp/form.hwpx"
canonical_output: null
stages:
{stage_text}
```
'''


def test_v06_order_and_awaiting_gate_resume(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    state = studio.workspace_state("report-demo")
    assert [item["num"] for item in state["stages"]] == studio._STAGE_ORDER
    assert state["resume"] == "5.5"
    assert state["canonical_output"] == ""
    assert state["subject"] == "science: #1"
    assert "\n" in state["topic"]


def test_research_fanout_is_aggregated(tmp_path: Path):
    ws = tmp_path / "report-demo"
    research = ws / "research"
    research.mkdir(parents=True)
    (research / "evidence_R1.md").write_text("# one", encoding="utf-8")
    (research / "evidence_R2.md").write_text("# two", encoding="utf-8")
    (research / "sources_R1.json").write_text(json.dumps([{"id": "S1"}]), encoding="utf-8")
    (research / "sources_R2.json").write_text(json.dumps([{"id": "S2"}]), encoding="utf-8")
    result = studio._research(ws)
    assert result["available"]
    assert len(result["sources"]) == 2
    assert "evidence_R1" in result["evidence_html"]


def test_workspace_traversal_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(HTTPException):
        studio.safe_workspace("report-x/../../outside")
