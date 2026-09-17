# -*- coding: utf-8 -*-
"""workspace/fillRun: fake fill_report child, progress, finish, refusal, cancel."""
from __future__ import annotations

import shutil
import textwrap
import time
from pathlib import Path

import pytest

from _runtime_client import (
    CORPUS_FORM,
    RuntimeClient,
    run_cli,
    runtime_scripts_on_path,
)

runtime_scripts_on_path()

import rt_core  # noqa: E402
import rt_fill  # noqa: E402
import rt_session  # noqa: E402
from rt_codes import RpcError  # noqa: E402

STUB = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import argparse, json, os, sys, time
    from pathlib import Path

    PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--loop", action="store_true")
        ap.add_argument("--form")
        ap.add_argument("--content")
        ap.add_argument("--out-dir")
        ap.add_argument("--build-yaml")
        ap.add_argument("--form-profile")
        ap.add_argument("--proof", action="store_true")
        ap.add_argument("--max-proof-iters", type=int, default=3)
        ap.add_argument("--spacing-skip-pages")
        ap.add_argument("--baseline")
        ap.add_argument("--out")
        args, _unknown = ap.parse_known_args()
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        events = out_dir / "fill_events.jsonl"
        def emit(obj):
            with events.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

        emit({
            "iter": 1, "ts": time.time(),
            "verdict": {
                "state": "gappy", "proof_grade": "hancom", "page_count": 19,
                "iter": 1,
                "checks": {"line_spacing_uniformity": ["cover"]},
                "converged": False,
            },
        })
        emit({
            "iter": 1, "ts": time.time(),
            "verdict": {
                "state": "converged", "proof_grade": "hancom", "page_count": 20,
                "iter": 1,
                "checks": {"line_spacing_uniformity": []},
                "converged": True,
            },
        })
        proof = out_dir / "proof"
        proof.mkdir(parents=True, exist_ok=True)
        sheet = proof / "sheet-1.png"
        sheet.write_bytes(PNG)
        emit({
            "ts": time.time(), "iter": 1, "phase": "proof", "proof_iter": 1,
            "result": {
                "contact_sheets": [str(sheet)],
                "status": "awaiting_judge",
                "proof_grade": "hancom",
            },
        })
        hwpx = out_dir / "out.hwpx"
        pdf = out_dir / "out.pdf"
        hwpx.write_bytes(b"PK\x03\x04dummy-fill")
        pdf.write_bytes(b"%PDF-1.4 dummy")
        verdict = {
            "converged": True,
            "state": "converged",
            "status": "awaiting_judge",
            "proof_grade": "hancom",
            "page_count": 20,
            "iterations": 1,
            "checks": {"line_spacing_uniformity": []},
            "style_anomalies": [],
            "hwpx": str(hwpx),
            "pdf": str(pdf),
            "contact_sheets": [str(sheet)],
            "phase": "proof",
        }
        target = Path(args.out) if args.out else out_dir / "verdict_v06.json"
        target.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
        sys.stdout.write(json.dumps(verdict, ensure_ascii=False))
        sys.stdout.flush()

    if __name__ == "__main__":
        main()
''')

STUB_HANG = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import argparse, json, os, sys, time
    from pathlib import Path

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--out-dir")
        args, _unknown = ap.parse_known_args()
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        events = out_dir / "fill_events.jsonl"
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "iter": 1, "ts": time.time(),
                "verdict": {
                    "state": "gappy", "proof_grade": "hancom", "page_count": 19,
                    "iter": 1,
                    "checks": {"line_spacing_uniformity": ["cover"]},
                    "converged": False,
                },
            }, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        time.sleep(120)

    if __name__ == "__main__":
        main()
''')

AURALAB_HEADER = """\
```yaml
# pipeline-state: v0.4
pipeline_version: "0.6"
graph: "build"
slug: "report-auralab-classroom"
mode: "autonomous"
subject: "physics"
form: "output/form_copy.hwpx"
updated: "2026-09-16T21:39:00"
canonical_output: "output/out.hwpx"
stages:
  "0":   {status: done, gate: {name: topic_pick, state: auto_approved, by: autonomous, at: 2026-09-16T18:13:13}}
  "5":   {status: done, gate: null}
```

# report-auralab-classroom
"""


def _workspace(tmp_path, *, complete=True):
    ws = tmp_path / "report-auralab-classroom"
    (ws / "bundle").mkdir(parents=True)
    (ws / "output").mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(AURALAB_HEADER, encoding="utf-8")
    if complete:
        (ws / "build.yaml").write_text("base_pt: 10\nfill:\n  target_pages: [18, 22]\n", encoding="utf-8")
        (ws / "bundle" / "content.md").write_text("# body\n", encoding="utf-8")
        (ws / "form_profile.json").write_text("{}", encoding="utf-8")
        (ws / "output" / "form_copy.hwpx").write_bytes(b"PK\x03\x04form")
    return ws


def _write_stub(tmp_path, text=STUB, name="fill_report.py") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _wait_for_fill_event(workspace: Path, timeout: float = 15.0) -> None:
    events = workspace / "output" / "fill_events.jsonl"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if events.is_file() and events.stat().st_size > 0:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("fill stub never wrote output/fill_events.jsonl")


@pytest.fixture()
def hancom_yes(monkeypatch):
    monkeypatch.setenv("RIGORLOOM_FILL_HANCOM", "yes")


@pytest.fixture()
def fill_stub(tmp_path, monkeypatch, hancom_yes):
    path = _write_stub(tmp_path, STUB)
    monkeypatch.setenv("RIGORLOOM_FILL_REPORT", str(path))
    return path


def test_fill_progress_is_a_runtime_event_kind():
    assert "fill/progress" in rt_session.EVENT_KINDS


def test_progress_from_a_fill_event_carries_iteration_state_qa_and_grade():
    detail = rt_fill.progress_from_fill_event({
        "iter": 2,
        "verdict": {
            "state": "gappy",
            "proof_grade": "hancom",
            "page_count": 19,
            "checks": {"line_spacing_uniformity": ["p1"], "max_gap_lines": []},
        },
    })
    assert detail["iteration"] == 2
    assert detail["state"] == "gappy"
    assert detail["proofGrade"] == "hancom"
    assert detail["layoutQa"]["pass"] is False
    assert detail["layoutQa"]["flagged"] == ["line_spacing_uniformity"]


def test_incomplete_workspace_is_artifact_missing(tmp_path, hancom_yes):
    ws = _workspace(tmp_path, complete=False)
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_fill_run(str(ws))
    assert caught.value.code == "artifact_missing"
    assert "build.yaml" in caught.value.data["missing"]
    assert "bundle/content.md" in caught.value.data["missing"]


def test_needs_hancom_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORLOOM_FILL_HANCOM", "no")
    ws = _workspace(tmp_path)
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_fill_run(str(ws))
    assert caught.value.code == "needs_hancom"


def test_finish_returns_state_paths_hashes_and_verdicts(tmp_path, fill_stub):
    ws = _workspace(tmp_path)
    root = tmp_path / "root"
    core = rt_core.RuntimeCore(root)
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    session = core.open_path(str(source))["sessionId"]
    result = core.workspace_fill_run(str(ws), session_id=session)
    assert result["state"] == "converged"
    assert result["proofGrade"] == "hancom"
    assert result["pageCount"] == 20
    assert result["verdict"]["state"] == "converged"
    assert result["verdict"]["proof_grade"] == "hancom"
    roles = {row["role"] for row in result["outputs"]}
    assert {"hwpx", "pdf", "verdict"} <= roles
    for row in result["outputs"]:
        assert len(row["sha256"]) == 64
        assert row["bytes"] > 0
        assert Path(row["path"]).is_file()
    assert result["contactSheets"]
    assert result["contactSheets"][0]["data"]
    assert result["layoutQa"]["checker"] == "layout_qa"
    assert result["layoutQa"]["state"] == "ran"
    assert result["verifyFormat"]["checker"] == "verify_format"
    events, _ = rt_session.read_events(core.store.get(session))
    kinds = [event["kind"] for event in events]
    assert "fill/progress" in kinds
    progress = [event for event in events if event["kind"] == "fill/progress"]
    assert progress[0]["detail"]["iteration"] == 1
    assert progress[0]["detail"]["state"] == "gappy"
    assert progress[0]["detail"]["proofGrade"] == "hancom"
    assert "line_spacing_uniformity" in progress[0]["detail"]["layoutQa"]["flagged"]
    assert any(event["detail"].get("state") == "converged" for event in progress)


def test_cli_fill_run_matches_the_core(tmp_path, fill_stub):
    ws = _workspace(tmp_path)
    root = tmp_path / "cli-root"
    cli = run_cli(root, "fill-run", "--workspace", str(ws))
    assert cli.code == 0, cli.stderr
    assert cli.payload["command"] == "fill-run"
    assert cli.result["state"] == "converged"
    assert cli.result["proofGrade"] == "hancom"
    core = rt_core.RuntimeCore(tmp_path / "core-root")
    wire = core.workspace_fill_run(str(ws))
    assert cli.result["state"] == wire["state"]
    assert cli.result["pageCount"] == wire["pageCount"]
    assert cli.result["proofGrade"] == wire["proofGrade"]


def test_relative_workspace_is_invalid_params(tmp_path, hancom_yes):
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_fill_run("report-auralab-classroom")
    assert caught.value.code == "invalid_params"


def test_fill_run_is_host_only(tmp_path):
    assert "workspace/fillRun" in rt_core.HOST_ONLY_METHODS
    assert "workspace/fillRun" not in rt_core.AGENT_METHODS
    with RuntimeClient(tmp_path / "agent", entry="agent") as agent:
        agent.initialize()
        error = agent.err("workspace/fillRun", {"workspace": str(tmp_path)})
    assert error["code"] == "unknown_method"
    assert error["data"]["knownOnHostEntry"] is True


def test_cancel_kills_the_hanging_child(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORLOOM_FILL_HANCOM", "yes")
    hang = _write_stub(tmp_path, STUB_HANG, name="fill_hang.py")
    monkeypatch.setenv("RIGORLOOM_FILL_REPORT", str(hang))
    ws = _workspace(tmp_path)
    with RuntimeClient(tmp_path / "root", entry="host") as client:
        client.initialize()
        client.send_frame({
            "kind": "request", "id": "fill-1", "method": "workspace/fillRun",
            "params": {"workspace": str(ws)},
        })
        _wait_for_fill_event(ws)
        client.send_frame({"kind": "cancel", "id": "fill-1"})
        frame = client.recv_answer("fill-1", timeout=30)
    assert frame["kind"] == "error"
    assert frame["error"]["code"] == "cancelled"


def test_second_run_on_the_same_workspace_is_fill_in_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORLOOM_FILL_HANCOM", "yes")
    hang = _write_stub(tmp_path, STUB_HANG, name="fill_hang.py")
    monkeypatch.setenv("RIGORLOOM_FILL_REPORT", str(hang))
    ws = _workspace(tmp_path)
    shared = tmp_path / "shared-root"
    with RuntimeClient(shared, entry="host") as first:
        first.initialize()
        first.send_frame({
            "kind": "request", "id": "fill-1", "method": "workspace/fillRun",
            "params": {"workspace": str(ws)},
        })
        _wait_for_fill_event(ws)
        with RuntimeClient(shared, entry="host") as second:
            second.initialize()
            error = second.err("workspace/fillRun", {"workspace": str(ws)})
        assert error["code"] == "fill_in_progress"
        first.send_frame({"kind": "cancel", "id": "fill-1"})
        frame = first.recv_answer("fill-1", timeout=30)
    assert frame["error"]["code"] == "cancelled"


def test_pipeline_status_reports_fill_inputs(tmp_path):
    ws = _workspace(tmp_path)
    core = rt_core.RuntimeCore(tmp_path / "root")
    result = core.pipeline_status(str(ws))
    assert result["fillInputs"]["complete"] is True
    assert result["fillInputs"]["formPath"].endswith("form_copy.hwpx")
    incomplete = _workspace(tmp_path / "other", complete=False)
    missing = core.pipeline_status(str(incomplete))
    assert missing["fillInputs"]["complete"] is False
    assert "build.yaml" in missing["fillInputs"]["missing"]
