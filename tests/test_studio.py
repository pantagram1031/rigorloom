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


def test_fill_returns_iteration_page_metadata(tmp_path: Path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    root = tmp_path / "workspaces"
    preview = root / "report-demo" / "output" / "preview"
    preview.mkdir(parents=True)
    document = fitz.open()
    document.new_page(); document.new_page()
    document.save(preview / "iter_3.pdf")
    document.close()
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    result = studio.workspace_fill("report-demo")
    assert result["iterations"] == [{
        "name": "iter_3.pdf",
        "iteration": 3,
        "page_count": 2,
        "mtime": (preview / "iter_3.pdf").stat().st_mtime,
    }]


def test_fill_normalizes_nested_verdicts_without_leaking_anchor_text(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    output = root / "report-demo" / "output"
    output.mkdir(parents=True)
    events = [
        {
            "iter": 2,
            "verdict": {
                "state": "gappy",
                "reason": "page gaps exceed threshold",
                "needs": ["reduce_gap"],
                "tidy_warnings": [{"anchor": "PRIVATE TEMPLATE TEXT", "reason": "not found"}],
            },
        },
        {"iter": 3, "phase": "proof", "result": {"status": "escalate_human"}},
    ]
    (output / "fill_events.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events), encoding="utf-8"
    )
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    result = studio.workspace_fill("report-demo")

    assert [item["kind"] for item in result["anomalies"]] == ["fill", "tidy", "proof"]
    assert all(item["status"] == "open" for item in result["anomalies"])
    assert "PRIVATE TEMPLATE TEXT" not in json.dumps(result["anomalies"])


def test_readiness_and_yourmove_follow_handoff_contract(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    pipeline_dir = ws / ".pipeline"
    pipeline_dir.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    handoff = {
        "schema": "report-pipeline-handoff/v2",
        "next_stage": "5.5",
        "next_status": "awaiting_gate",
        "next_gate": {"name": "understand", "state": "pending"},
        "playbook": "pipeline/references/playbooks/stage-5.5.md",
        "work_dir": "work/stage-5.5",
        "required_inputs": ["output/out.pdf"],
        "expected_outputs": ["UNDERSTANDING.md"],
        "missing_inputs": ["output/out.pdf"],
        "missing_outputs": ["UNDERSTANDING.md"],
        "resume_command": 'python pipeline/scripts/pipeline_ctl.py resume "C:/safe/report-demo"',
        "personalization_lock": ".pipeline/personalization.lock.json",
        "generated_at": "2026-07-11T12:00:00+09:00",
        "archived": ["archive/stages/stage-5/scratch.txt"],
    }
    (pipeline_dir / "handoff.json").write_text(json.dumps(handoff), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    readiness = studio.workspace_readiness("report-demo")
    move = studio.workspace_yourmove("report-demo")

    assert readiness["available"] is True
    assert readiness["readiness"] == "missing_inputs"
    assert readiness["missing_inputs"] == ["output/out.pdf"]
    assert readiness["archived_count"] == 1
    assert move["approval_line"].startswith("understand: approved by=<name> at=")
    assert " gate " in move["gate_command"]
    assert "--mode supervised" in move["gate_command"]
    assert move["resume_command"] == handoff["resume_command"]


def test_readiness_falls_back_to_pipeline_without_writing_workspace(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    before = sorted(path.relative_to(ws) for path in ws.rglob("*"))
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    result = studio.workspace_readiness("report-demo")

    assert result["available"] is False
    assert result["readiness"] == "legacy"
    assert result["next_stage"] == "5.5"
    assert result["next_status"] == "awaiting_gate"
    assert result["playbook"].endswith("stage-5.5.md")
    assert sorted(path.relative_to(ws) for path in ws.rglob("*")) == before


def test_personalization_endpoint_is_redacted(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    lock_dir = root / "report-demo" / ".pipeline"
    lock_dir.mkdir(parents=True)
    lock = {
        "lock_hash": "abc", "subject": "math", "form_sha256": "def",
        "identity_enabled": True,
        "effective": {
            "writing": {"language": "ko", "academic_level": "high-school",
                        "register": "formal", "avoid_patterns": ["x"]},
            "academic": {"subject": "math"}, "form_conditions": {"constraints": {}},
            "precedence": ["request explicit", "global profile"],
        },
        "identity": {"name": "PRIVATE NAME"},
    }
    (lock_dir / "personalization.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    result = studio.workspace_personalization("report-demo")
    assert result["available"] is True
    assert result["identity_enabled"] is True
    assert result["writing"]["avoid_count"] == 1
    assert "PRIVATE NAME" not in json.dumps(result)


def test_studio_shell_uses_rigorloom_and_safe_dom_bindings():
    html = (MODULE_PATH.parent / "index.html").read_text(encoding="utf-8")
    assert "Rigorloom" in html
    assert "Math.round(v*100)" not in html
    assert "probe page count" not in html
    assert 'id="copy-approval"' in html
    assert 'onclick="copyPlain(${JSON.stringify' not in html
    assert 'id="readiness-body"' in html
    assert 'id="mission-stats"' in html
    assert 'id="yamltext"' not in html
    assert "function buildYaml(" not in html
