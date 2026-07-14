from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

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
        "4.5": "{status: done, gate: {name: content_audit, state: auto_approved, by: script, at: now}}",
        "5": "{status: done, gate: null}",
        "5.3": "{status: done, gate: {name: format_check, state: auto_approved, by: script, at: now}}",
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


def test_dashboard_lists_all_workspaces(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    for slug in ("report-alpha", "report-beta"):
        ws = root / slug
        ws.mkdir(parents=True)
        (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_lint_result",
                        lambda base: {"state": "na", "label": "lint n/a", "hard": []})

    page = studio.root().body.decode("utf-8")

    assert "report-alpha" in page
    assert "report-beta" in page
    assert 'class="card' in page


def test_gate_check_provenance_is_renderable(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    checks = root / "report-demo" / ".pipeline"
    checks.mkdir(parents=True)
    record = {
        "gate": "layout", "checker_argv": ["python", "checker.py", "a & b"],
        "exit": 3, "stdout_sha256": "1234567890abcdef", "checked_at": "now",
    }
    (checks / "gate_checks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    result = studio.workspace_gate_checks("report-demo")

    assert result["entries"] == [{
        "gate": "layout", "argv": ["python", "checker.py", "a & b"],
        "argv_joined": "python checker.py a & b", "exit_code": 3,
        "stdout_sha256": "1234567890ab", "checked_at": "now",
    }]
    shell = (MODULE_PATH.parent / "index.html").read_text(encoding="utf-8")
    assert "esc(r.argv_joined)" in shell


def test_action_post_is_forbidden_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("STUDIO_ALLOW_ACTIONS", raising=False)
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", tmp_path)

    with pytest.raises(HTTPException) as exc:
        studio.workspace_action("report-demo", "check-gate", "layout")

    assert exc.value.status_code == 403


def test_check_gate_action_uses_argv_when_enabled(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="checked", stderr="")

    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")
    monkeypatch.setattr(studio.subprocess, "run", fake_run)

    result = studio.workspace_action(
        "report-demo", "check-gate", "layout",
        x_studio_token="test-token", host="127.0.0.1",
    )

    assert result["argv"] == calls[0][0]
    assert result["argv"][0] == studio.sys.executable
    assert result["argv"][2:] == ["check", str(ws.resolve()), "layout"]
    assert result["exit_code"] == 0
    assert result["output_tail"] == "checked"
    assert "shell" not in calls[0][1]


def test_action_post_rejected_without_token(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")

    with pytest.raises(HTTPException) as exc:
        studio.workspace_action("report-demo", "check-gate", "layout", host="127.0.0.1")

    assert exc.value.status_code == 403


def test_action_post_rejected_with_wrong_host(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")

    with pytest.raises(HTTPException) as exc:
        studio.workspace_action(
            "report-demo", "check-gate", "layout",
            x_studio_token="test-token", host="evil.example.com",
        )

    assert exc.value.status_code == 403


def test_action_rejects_gate_absent_from_workspace_header(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")

    with pytest.raises(HTTPException) as exc:
        studio.workspace_action(
            "report-demo", "check-gate", "not-a-real-gate",
            x_studio_token="test-token", host="127.0.0.1",
        )

    assert exc.value.status_code == 400


def test_action_rejects_gate_absent_from_stage_graph(tmp_path: Path, monkeypatch):
    # The header claims a "layout" gate exists (via _pipeline_text), but the
    # stage graph the workspace declares (default "build") never registers
    # it — this must be rejected even though the header alone would accept it.
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(_pipeline_text(), encoding="utf-8")
    fake_graph = tmp_path / "fake-stages.yaml"
    fake_graph.write_text(
        '- {id: "0", name: "form_intake", gate: null}\n'
        '- {id: "2", name: "design", gate: {name: "design", type: "human"}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setenv("STUDIO_STAGES_YAML", str(fake_graph))
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")

    with pytest.raises(HTTPException) as exc:
        studio.workspace_action(
            "report-demo", "check-gate", "layout",
            x_studio_token="test-token", host="127.0.0.1",
        )

    assert exc.value.status_code == 400


def test_lint_badge_is_na_for_unparseable_output(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    script = repo / "pipeline" / "scripts" / "workflow_lint.py"
    script.parent.mkdir(parents=True)
    script.write_text("# feature detected", encoding="utf-8")
    ws = tmp_path / "report-demo"
    ws.mkdir()
    monkeypatch.setattr(studio, "REPO_ROOT", repo)
    monkeypatch.setattr(
        studio.subprocess, "run",
        lambda argv, **kwargs: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )
    studio._LINT_CACHE.clear()

    result = studio._lint_result(ws)

    assert result == {"state": "na", "label": "lint n/a", "hard": []}


def test_lint_probe_is_single_flight_per_workspace(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    script = repo / "pipeline" / "scripts" / "workflow_lint.py"
    script.parent.mkdir(parents=True)
    script.write_text("# feature detected", encoding="utf-8")
    ws = tmp_path / "report-demo"
    ws.mkdir()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        entered.set()
        assert release.wait(timeout=2)
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"findings": []}), stderr="",
        )

    monkeypatch.setattr(studio, "REPO_ROOT", repo)
    monkeypatch.setattr(studio.subprocess, "run", fake_run)
    studio._LINT_CACHE.clear()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(studio._lint_result, ws)
        assert entered.wait(timeout=2)
        second_started = threading.Event()

        def call_second():
            second_started.set()
            return studio._lint_result(ws)

        second = pool.submit(call_second)
        assert second_started.wait(timeout=2)
        threading.Event().wait(0.05)
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert len(calls) == 1


def test_capability_strip_renders_probe_results_once(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    probe = repo / "pipeline" / "scripts" / "render_probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("def probe(): return {}", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "capabilities": {
                    "hancom_com": True, "soffice": False,
                    "soffice_wsl": True, "h2orestart": False,
                },
                "renderers": [{"name": "soffice-wsl"}],
            }),
            stderr="",
        )

    monkeypatch.setattr(studio, "REPO_ROOT", repo)
    monkeypatch.setattr(studio.subprocess, "run", fake_run)
    studio._CAPABILITY_CACHE = None

    first = studio._capability_status()
    second = studio._capability_status()
    page = studio.root().body.decode("utf-8")

    assert first == second
    assert len(calls) == 1
    assert calls[0][0][0] == studio.sys.executable
    assert calls[0][1]["timeout"] == 20
    assert [(chip["label"], chip["available"]) for chip in first["chips"]] == [
        ("Hancom COM", True), ("soffice", False),
        ("soffice(WSL)", True), ("H2Orestart", False),
    ]
    assert "Hancom COM" in page
    assert 'id="dashboard-capabilities"' in page
    assert 'id="detail-capabilities"' in page


def test_capability_probe_is_single_flight(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    probe = repo / "pipeline" / "scripts" / "render_probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("def probe(): return {}", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        entered.set()
        assert release.wait(timeout=2)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"capabilities": {}, "renderers": []}),
            stderr="",
        )

    monkeypatch.setattr(studio, "REPO_ROOT", repo)
    monkeypatch.setattr(studio.subprocess, "run", fake_run)
    studio._CAPABILITY_CACHE = None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(studio._capability_status)
        assert entered.wait(timeout=2)
        second_started = threading.Event()

        def call_second():
            second_started.set()
            return studio._capability_status()

        second = pool.submit(call_second)
        assert second_started.wait(timeout=2)
        threading.Event().wait(0.05)
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert len(calls) == 1


def test_capability_strip_renders_probe_na_when_module_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(studio, "REPO_ROOT", tmp_path)
    studio._CAPABILITY_CACHE = None

    status = studio._capability_status()
    page = studio.root().body.decode("utf-8")

    assert status["available"] is False
    assert status["chips"] == [{"key": "probe", "label": "probe n/a", "available": False}]
    assert "probe n/a" in page


def test_build_hwpx_action_uses_guarded_argv(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    ws = root / "report-demo"
    ws.mkdir(parents=True)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="built", stderr="")

    monkeypatch.setenv("STUDIO_ALLOW_ACTIONS", "1")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(studio, "_ACTION_TOKEN", "test-token")
    monkeypatch.setattr(studio.subprocess, "run", fake_run)

    result = studio.workspace_action(
        "report-demo", "build-hwpx",
        x_studio_token="test-token", host="localhost:8000",
    )

    assert result["argv"] == [
        studio.sys.executable,
        str(studio.REPO_ROOT / "pipeline" / "scripts" / "doc_backend.py"),
        str(ws.resolve()), "--backend", "hwpx",
    ]
    assert result["exit_code"] == 0
    assert "shell" not in calls[0][1]


@pytest.mark.parametrize(
    ("grade", "label", "badge_class"),
    [
        ("hancom", "submission proof", "proof-hancom"),
        ("advisory", "advisory render", "proof-advisory"),
        ("none", "no render proof", "proof-none"),
    ],
)
def test_proof_grade_badges_from_verdict_files(
    tmp_path: Path, monkeypatch, grade: str, label: str, badge_class: str,
):
    root = tmp_path / "workspaces"
    output = root / "report-demo" / "output"
    output.mkdir(parents=True)
    (output / "verdict_v06.json").write_text(json.dumps({
        "proof_grade": grade,
        "gappy_pages": [2, 4],
        "needs": ["tighten", "rerender"],
        "renderer_failed": grade == "none",
    }), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    verdict = studio.workspace_verdict("report-demo")

    assert verdict["available"] is True
    assert verdict["proof_grade"] == grade
    assert verdict["proof_label_en"] == label
    assert verdict["proof_badge_class"] == badge_class
    assert verdict["gappy_pages"] == [2, 4]
    assert verdict["needs_count"] == 2
    assert verdict["renderer_failed"] is (grade == "none")


def test_verdict_bound_to_canonical_file_not_spoofable_by_newer_json(tmp_path: Path, monkeypatch):
    # The badge must read ONLY the assembler's canonical verdict_v06.json; a newer
    # arbitrarily-named *verdict*.json must NOT override the canonical proof grade.
    root = tmp_path / "workspaces"
    output = root / "report-demo" / "output"
    output.mkdir(parents=True)
    canonical = output / "verdict_v06.json"
    spoof = output / "xml_loop_verdict_latest.json"
    canonical.write_text(json.dumps({"verdict": {
        "proof_grade": "none", "gappy": [], "needs": [],
    }}), encoding="utf-8")
    spoof.write_text(json.dumps({"verdict": {
        "proof_grade": "advisory", "gappy": [3], "needs": [],
        "renderer_failed": "timeout",
    }}), encoding="utf-8")
    import os
    base_mtime = canonical.stat().st_mtime_ns
    os.utime(spoof, ns=(base_mtime + 1_000_000, base_mtime + 1_000_000))
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    verdict = studio.workspace_verdict("report-demo")

    assert verdict["source"] == canonical.name
    assert verdict["proof_grade"] == "none"


def test_verdict_absent_when_no_canonical_file(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspaces"
    output = root / "report-demo" / "output"
    output.mkdir(parents=True)
    (output / "xml_loop_verdict_latest.json").write_text(
        json.dumps({"proof_grade": "advisory"}), encoding="utf-8")
    monkeypatch.setattr(studio, "WORKSPACE_ROOT", root)

    verdict = studio.workspace_verdict("report-demo")

    assert verdict["available"] is False
    assert verdict["proof_grade"] == "none"
