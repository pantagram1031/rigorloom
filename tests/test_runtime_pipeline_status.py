# -*- coding: utf-8 -*-
"""workspace/pipelineStatus: read-only PIPELINE.md header, verdicts verbatim."""
from __future__ import annotations

import json

import pytest

from _runtime_client import RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_core  # noqa: E402
import rt_pipeline  # noqa: E402

AURALAB_HEADER = """\
```yaml
# pipeline-state: v0.4
pipeline_version: "0.6"
graph: "build"
slug: "report-auralab-classroom"
mode: "autonomous"
subject: "physics"
topic: "교실 창호"
form: "C:\\\\templates\\\\form.hwpx"
updated: "2026-09-16T21:39:00"
canonical_output: "output/out.hwpx"
stages:
  "0":   {status: done, gate: {name: topic_pick, state: auto_approved, by: autonomous, at: 2026-09-16T18:13:13}}
  "1":   {status: done, gate: null}
  "2":   {status: done, gate: {name: design, state: auto_approved, by: autonomous, at: 2026-09-16T18:25:36}}
  "2.5":   {status: done, gate: {name: layout, state: auto_approved, by: script, at: 2026-09-16T18:25:39}}
  "3":   {status: done, gate: {name: sane, state: auto_approved, by: script, at: 2026-09-16T18:27:25}}
  "4":   {status: done, gate: {name: draft, state: auto_approved, by: autonomous, at: 2026-09-16T18:34:52}}
  "4.5":   {status: done, gate: {name: content_audit, state: auto_approved, by: script, at: 2026-09-16T21:34:33}}
  "5":   {status: done, gate: null}
  "5.3":   {status: done, gate: {name: format_check, state: auto_approved, by: script, at: 2026-09-16T21:38:37}}
  "5.5":   {status: done, gate: {name: understand, state: auto_approved, by: script, at: 2026-09-16T21:38:40}}
  "5.7":   {status: done, gate: {name: final_panel, state: auto_approved, by: script, at: 2026-09-16T21:38:43}}
  "6":   {status: done, gate: {name: submission_preflight, state: auto_approved, by: script, at: 2026-09-16T21:38:59}}
```

# report-auralab-classroom
"""

PENDING_HEADER = """\
```yaml
# pipeline-state: v0.4
slug: "report-mid"
mode: "supervised"
subject: "physics"
updated: "2026-09-18T01:00:00"
canonical_output: null
stages:
  "0":   {status: done, gate: {name: topic_pick, state: auto_approved, by: autonomous, at: 2026-09-16T18:13:13}}
  "1":   {status: done, gate: null}
  "2":   {status: awaiting_gate, gate: {name: design, state: pending, by: null, at: null}}
  "3":   {status: pending, gate: {name: sane, state: rejected, by: script, at: 2026-09-16T18:27:25}}
```

# mid
"""


def _workspace(tmp_path, text=AURALAB_HEADER, nested=True):
    ws = tmp_path / "report-auralab-classroom"
    out_dir = ws / "output"
    out_dir.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(text, encoding="utf-8")
    doc = out_dir / "out.hwpx"
    doc.write_bytes(b"PK\x03\x04dummy")
    return ws, doc


@pytest.fixture()
def client(tmp_path):
    with RuntimeClient(tmp_path / "root", entry="host") as handle:
        handle.initialize()
        yield handle


# --- found / not found / malformed ------------------------------------------

def test_a_nested_document_finds_the_header_and_copies_gates(client, tmp_path):
    ws, doc = _workspace(tmp_path)
    result = client.ok("workspace/pipelineStatus", {"path": str(doc)})
    assert result["found"] is True
    assert result["workspacePath"] == str(ws)
    assert result["slug"] == "report-auralab-classroom"
    assert result["mode"] == "autonomous"
    assert result["subject"] == "physics"
    assert result["updated"] == "2026-09-16T21:39:00"
    assert result["canonicalOutput"] == "output/out.hwpx"
    assert result["nextGate"] is None
    by_id = {row["id"]: row for row in result["stages"]}
    assert by_id["0"]["status"] == "done"
    assert by_id["0"]["gate"] == {
        "name": "topic_pick",
        "state": "auto_approved",
        "by": "autonomous",
        "at": "2026-09-16T18:13:13",
    }
    assert by_id["1"]["gate"] is None
    assert by_id["2.5"]["gate"]["state"] == "auto_approved"
    assert by_id["0"]["label"] == "form_intake"
    assert [row["id"] for row in result["stages"]][:4] == ["0", "1", "2", "2.5"]


def test_not_found_is_an_answer_not_a_refusal(client, tmp_path):
    doc = tmp_path / "lonely" / "out.hwpx"
    doc.parent.mkdir()
    doc.write_bytes(b"x")
    result = client.ok("workspace/pipelineStatus", {"path": str(doc)})
    assert result == rt_pipeline.NOT_FOUND


def test_a_directory_four_levels_up_is_still_found(client, tmp_path):
    ws = tmp_path / "ws"
    deep = ws / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(AURALAB_HEADER, encoding="utf-8")
    result = client.ok("workspace/pipelineStatus", {"path": str(deep)})
    assert result["found"] is True
    assert result["workspacePath"] == str(ws)


def test_five_levels_up_is_not_found(client, tmp_path):
    ws = tmp_path / "ws"
    deep = ws / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(AURALAB_HEADER, encoding="utf-8")
    result = client.ok("workspace/pipelineStatus", {"path": str(deep)})
    assert result["found"] is False


def test_a_missing_fence_is_a_named_refusal(client, tmp_path):
    ws, doc = _workspace(tmp_path, text="# no header here\n")
    error = client.err("workspace/pipelineStatus", {"path": str(doc)})
    assert error["code"] == "pipeline_header_missing"
    assert error["data"]["workspacePath"] == str(ws)


def test_an_unreadable_encoding_is_unparsable(client, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "PIPELINE.md").write_bytes(b"```yaml\n# pipeline-state: v0.4\n\xff\xfe\n```\n")
    error = client.err("workspace/pipelineStatus", {"path": str(ws)})
    assert error["code"] == "pipeline_header_unparsable"


def test_a_relative_path_is_refused(client):
    error = client.err("workspace/pipelineStatus", {"path": "PIPELINE.md"})
    assert error["code"] == "invalid_params"


# --- verdicts verbatim, no writes -------------------------------------------

def test_gate_verdicts_are_copied_not_recomputed(client, tmp_path):
    _, doc = _workspace(tmp_path, text=PENDING_HEADER)
    result = client.ok("workspace/pipelineStatus", {"path": str(doc)})
    by_id = {row["id"]: row for row in result["stages"]}
    # A rejected predecessor is still rejected here. Status is not rewritten
    # to blocked, and pending is not auto_approved.
    assert by_id["3"]["gate"]["state"] == "rejected"
    assert by_id["3"]["gate"]["by"] == "script"
    assert by_id["3"]["status"] == "pending"
    assert by_id["2"]["status"] == "awaiting_gate"
    assert by_id["2"]["gate"] == {
        "name": "design",
        "state": "pending",
        "by": None,
        "at": None,
    }
    assert result["nextGate"] == {
        "stageId": "2",
        "status": "awaiting_gate",
        "gate": {
            "name": "design",
            "state": "pending",
            "by": None,
            "at": None,
        },
    }


def test_the_call_does_not_write_pipeline_md(client, tmp_path):
    ws, doc = _workspace(tmp_path, text=PENDING_HEADER)
    before = (ws / "PIPELINE.md").read_bytes()
    client.ok("workspace/pipelineStatus", {"path": str(doc)})
    assert (ws / "PIPELINE.md").read_bytes() == before
    assert not (ws / "events.jsonl").exists()
    assert not (ws / "heartbeat").exists()


def test_the_cli_matches_the_jsonl_payload(client, tmp_path):
    _, doc = _workspace(tmp_path, text=PENDING_HEADER)
    wire = client.ok("workspace/pipelineStatus", {"path": str(doc)})
    cli = run_cli(tmp_path / "cli-root", "pipeline-status", "--path", str(doc))
    assert cli.code == 0
    assert cli.payload["ok"] is True
    assert cli.payload["command"] == "pipeline-status"
    assert cli.result == wire


def test_the_method_is_host_only(tmp_path):
    assert "workspace/pipelineStatus" in rt_core.HOST_ONLY_METHODS
    assert "workspace/pipelineStatus" not in rt_core.AGENT_METHODS
    ws, doc = _workspace(tmp_path)
    with RuntimeClient(tmp_path / "agent-root", entry="agent") as agent:
        agent.initialize()
        error = agent.err("workspace/pipelineStatus", {"path": str(doc)})
    assert error["code"] == "unknown_method"
    assert error["data"]["knownOnHostEntry"] is True
